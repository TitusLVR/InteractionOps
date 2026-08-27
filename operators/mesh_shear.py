"""Smart shear operator.

Every selection becomes one or more *profile records*: an ordered vert
loop (a face's verts, or a connected chain of selected edges) with a
plane normal and a minimum oriented bounding box in that plane. The
shear tilts the profile around the OBB side the axis points away from
(the "saw entry" pivot): each vert slides along its rail — its edge
leaving the profile, or the plane normal on open geometry — to where
the rail meets the profile plane rotated by the typed angle,
`proj·sin(angle)/(rail·n')`. Verts sharing a projection (one cross-
section) slide as a rigid row along their averaged rail.

- face selection → one record per face (rails = non-face edges).
- edge selection (no faces) → one record per connected chain of
  selected edges: open boundary loops, wire profiles, single edges.
  Rails = edges leaving the chain; the plane comes from the linked
  faces (else best-fit of the verts).

Modal UX: numeric angle (0-9 . -), F cycles the four OBB sides, D flips
the axis, R snaps perpendicular to the rails, A aligns the axis to a
picked face, B min-OBB axis, E extrudes the profile along a grabbable
arrow, Q confirms and hands over to the Hinge operator. Enter confirms,
Esc/RMB cancels. LMB only picks widget handles.
"""
import bpy
import bmesh
import math
import gpu

from ..ui.draw import primitives as draw_prim, Role
from ..ui.draw import safe_handler_add, safe_handler_remove
from ..ui.draw.theme import get_theme
from ..ui.hud import (HUDOverlay, HelpOverlay, HUDSection, HUDItem,
                      ItemState, capture_event)
from bpy_extras import view3d_utils
from mathutils import Vector
from mathutils.bvhtree import BVHTree
from mathutils.geometry import normal as poly_normal


DIGIT_TYPES = {
    "ZERO": "0", "ONE": "1", "TWO": "2", "THREE": "3", "FOUR": "4",
    "FIVE": "5", "SIX": "6", "SEVEN": "7", "EIGHT": "8", "NINE": "9",
    "NUMPAD_0": "0", "NUMPAD_1": "1", "NUMPAD_2": "2", "NUMPAD_3": "3",
    "NUMPAD_4": "4", "NUMPAD_5": "5", "NUMPAD_6": "6", "NUMPAD_7": "7",
    "NUMPAD_8": "8", "NUMPAD_9": "9",
}


# --------------------------------------------------------------------------
# Math (module-level so headless tests can drive it)
# --------------------------------------------------------------------------


def _angle_to_t(angle_deg):
    a_rad = math.radians(angle_deg)
    c = math.cos(a_rad)
    if abs(c) < 1e-6:
        t = math.copysign(1e4, math.sin(a_rad))
    else:
        t = math.sin(a_rad) / c
    return max(-1e4, min(1e4, t))


def _face_normal_safe(face):
    n = face.normal.copy()
    if n.length >= 1e-9:
        return n
    verts = [l.vert.co for l in face.loops]
    if len(verts) >= 3:
        for i in range(1, len(verts) - 1):
            a = verts[i] - verts[0]
            b = verts[i + 1] - verts[0]
            cr = a.cross(b)
            if cr.length > 1e-9:
                return cr.normalized()
    return n  # zero — caller checks


def _find_external_rail(vert, exclude_edges):
    """First link_edge of `vert` outside `exclude_edges` (the profile's
    own edges). Returns (rail_edge, anchor_vert, rail_dir, rail_length)
    or None if no rail exists."""
    for e in vert.link_edges:
        if e in exclude_edges:
            continue
        anchor = e.other_vert(vert)
        rail_vec = vert.co - anchor.co
        L = rail_vec.length
        if L < 1e-9:
            continue
        return e, anchor, rail_vec / L, L
    return None


def _gather_double_verts(seed_verts, dist):
    """Grow `seed_verts` across link_loops to every vert closer than
    `dist` to an already-collected vert. Recursion via list growth."""
    verts = list(seed_verts)
    seen = set(verts)
    for v in verts:
        co = v.co
        for loop in v.link_loops:
            nv = loop.link_loop_next.vert
            if nv not in seen and (nv.co - co).length < dist:
                seen.add(nv)
                verts.append(nv)
    return verts


def chains_from_edges(edges):
    """Split ``edges`` into connected chains. Returns a list of
    ``(verts, edges, closed)`` with verts in walk order (closed rings
    start anywhere), or raises ValueError when a vert joins more than
    two of the edges (branching selection)."""
    adj = {}
    for e in edges:
        for v in e.verts:
            adj.setdefault(v, []).append(e)
    for v, lst in adj.items():
        if len(lst) > 2:
            raise ValueError(f"vert {v.index} joins {len(lst)} selected edges")
    remaining = set(edges)
    out = []
    while remaining:
        # prefer an open end as the walk start
        start_v = None
        for e in remaining:
            for v in e.verts:
                if len(adj[v]) == 1:
                    start_v = v
                    break
            if start_v is not None:
                break
        if start_v is None:
            start_v = next(iter(remaining)).verts[0]
        verts = [start_v]
        chain = []
        v = start_v
        prev = None
        while True:
            nxt = [e for e in adj[v] if e is not prev and e in remaining]
            if not nxt:
                break
            e = nxt[0]
            remaining.discard(e)
            chain.append(e)
            v = e.other_vert(v)
            prev = e
            if v is start_v:
                break
            verts.append(v)
        closed = (v is start_v) and len(chain) >= 3
        out.append((verts, chain, closed))
    return out


def chain_normal(edges, cos):
    """Plane normal of the virtual face an edge chain spans.

    The chain's own verts define the plane (best fit) — the faces
    linked to a boundary chain are the walls *adjacent* to the profile,
    perpendicular to it, so their normals say nothing about the profile
    plane. Sign: toward the mean rail direction (edges leaving the chain
    point from the body to the profile), so positive shear / extrude
    head away from the body; +Z when there are no rails.

    Collinear chains have no plane of their own: fall back to the mean
    linked-face normal (a straight border of a flat sheet shears in the
    sheet's plane). None when nothing works (a lone wire edge)."""
    exclude = set(edges)
    rail_mean = Vector((0.0, 0.0, 0.0))
    verts = []
    seen_v = set()
    for e in edges:
        for v in e.verts:
            if v not in seen_v:
                seen_v.add(v)
                verts.append(v)
    for v in verts:
        for le in v.link_edges:
            if le in exclude:
                continue
            d = v.co - le.other_vert(v).co
            if d.length > 1e-9:
                rail_mean += d.normalized()

    n = Vector((0.0, 0.0, 0.0))
    if len(cos) >= 3:
        try:
            n = Vector(poly_normal(cos))
        except (ValueError, TypeError):
            n = Vector((0.0, 0.0, 0.0))
    if n.length > 1e-6:
        n.normalize()
        ref = rail_mean if rail_mean.length > 1e-9 else Vector((0.0, 0.0, 1.0))
        if n.dot(ref) < 0:
            n = -n
        return n

    n = Vector((0.0, 0.0, 0.0))
    seen = set()
    for e in edges:
        for f in e.link_faces:
            if f not in seen:
                seen.add(f)
                n += _face_normal_safe(f)
    if n.length > 1e-9:
        return n.normalized()
    return None


def build_face_record(face, axis_dir):
    """Profile record for a BMFace: rails are the edges leaving the face."""
    if not face.is_valid or len(face.verts) < 3:
        return None, "face has fewer than 3 verts"
    normal = _face_normal_safe(face)
    if normal.length < 1e-9:
        return None, "degenerate face normal"
    return build_profile_record(list(face.verts), list(face.edges),
                                normal.normalized(), axis_dir,
                                face=face, closed=True)


def build_chain_record(edges, axis_dir, normal=None):
    """Profile record for one connected chain of edges (open loop, ring
    or a single edge). Rails are the edges leaving the chain."""
    edges = [e for e in edges if e.is_valid]
    if not edges:
        return None, "no edges"
    try:
        chains = chains_from_edges(edges)
    except ValueError as exc:
        return None, str(exc)
    if len(chains) != 1:
        return None, "edges form more than one chain"
    verts, chain, closed = chains[0]
    cos = [v.co for v in verts]
    if normal is None or normal.length < 1e-9:
        normal = chain_normal(chain, cos)
    if normal is None:
        return None, "edge chain has no plane (wire edge without faces)"
    # An open chain of 3+ verts is closed by a virtual edge between its
    # ends — the profile is then a polygon like a face (same OBB, same
    # pivot sides). A lone edge stays a 2-vert open profile.
    virtual_close = (not closed) and len(verts) >= 3
    rec, reason = build_profile_record(verts, chain, normal.normalized(), axis_dir,
                                       face=None, closed=closed or virtual_close)
    if rec is not None:
        rec["virtual_close"] = virtual_close
    return rec, reason


def build_profile_record(active_verts, edges, normal, axis_dir, *, face,
                         closed):
    """Shear record for an ordered vert loop with plane `normal`. ALL
    verts slide along their rails — the first link edge outside `edges`,
    or `normal` when the vert has none (open geometry). `axis_dir` is
    projected into the plane; projections are measured along it from
    the pivot side (smallest projection).

    The record caches the profile's min-OBB axes so F can cycle the
    four bbox sides without recomputing."""
    if axis_dir is None or axis_dir.length < 1e-9:
        return None, "no axis direction"
    if len(active_verts) < 2:
        return None, "profile needs at least 2 verts"

    centroid = Vector((0.0, 0.0, 0.0))
    for v in active_verts:
        centroid = centroid + v.co
    centroid = centroid / len(active_verts)

    # Project axis_dir onto the profile plane (defensive — caller
    # should pass an in-plane vector but enforce here).
    axis_dir = (axis_dir - axis_dir.dot(normal) * normal)
    if axis_dir.length < 1e-9:
        return None, "axis direction is parallel to the profile normal"
    axis_dir = axis_dir.normalized()

    exclude = set(edges)
    rails = []
    centroid_projs = []
    for av in active_verts:
        # First link edge outside the profile with a usable length. A
        # zero-length one is a fresh extrude wall whose vert hasn't
        # left its anchor yet (saw-off delay) — skip it, another edge
        # or the normal fallback carries the rail.
        rail_edge = None
        for e in av.link_edges:
            if e in exclude:
                continue
            if (e.other_vert(av).co - av.co).length < 1e-9:
                continue
            rail_edge = e
            break
        if rail_edge is None:
            # Open geometry (boundary vert of a plane / strip): no
            # external edge to slide along. Fall back to the face
            # normal — the vert still lands on the rotated plane, the
            # slide just isn't constrained by surrounding mesh.
            if normal.length < 1e-9:
                return None, (
                    f"vert {av.index} has no external rail edge and the "
                    "face normal is degenerate"
                )
            rails.append({
                "rail_edge": None,
                "anchor": None,
                "dir": normal.normalized(),
                "length": 0.0,
            })
            centroid_projs.append((av.co - centroid).dot(axis_dir))
            continue
        ev0, ev1 = rail_edge.verts
        anchor = ev1 if ev0 is av else ev0
        rail_vec = av.co - anchor.co
        rail_L = rail_vec.length
        if rail_L < 1e-9:
            return None, "rail edge has zero length"
        rails.append({
            "rail_edge": rail_edge,
            "anchor": anchor,
            "dir": rail_vec / rail_L,
            "length": rail_L,
        })
        centroid_projs.append((av.co - centroid).dot(axis_dir))

    # Saw-off: pivot is the face boundary where axis_dir projection is
    # smallest (the "saw entry" edge). Shift so that pivot verts have
    # proj = 0 and the rest have proj > 0. At positive angle, every
    # vert slides along its rail away from the pivot edge onto the
    # rotated face plane (see apply_records).
    min_centroid_proj = min(centroid_projs)
    projections = [cp - min_centroid_proj for cp in centroid_projs]
    pivot_point = centroid + axis_dir * min_centroid_proj

    # Row-rigid slide: verts sharing the same projection form one
    # profile cross-section and must translate as a rigid unit —
    # per-vert rails that diverge (the two long sides of a chamfer
    # strip point along different world axes) would otherwise twist
    # the cross-section into a bowtie. Each row slides along the
    # normalized mean of its members' unit rail dirs: identical to
    # the old behavior for parallel rails, a rigid diagonal slide
    # for diverging ones.
    max_p = max(projections) if projections else 0.0
    row_tol = max(max_p * 1e-3, 1e-6)
    order = sorted(range(len(projections)), key=lambda i: projections[i])
    row = []
    rows = []
    for i in order:
        if row and projections[i] - projections[row[-1]] > row_tol:
            rows.append(row)
            row = []
        row.append(i)
    if row:
        rows.append(row)
    for row in rows:
        if len(row) < 2:
            continue
        mean_dir = rails[row[0]]["dir"] * 0.0
        for i in row:
            mean_dir = mean_dir + rails[i]["dir"]
        if mean_dir.length < 1e-6:
            continue  # opposing rails cancel — keep per-vert dirs
        mean_dir = mean_dir / mean_dir.length
        for i in row:
            rails[i]["dir"] = mean_dir.copy()

    pa, pb = profile_principal_axes([v.co for v in active_verts], normal)
    return {
        "type": "face",
        "face": face,               # None for an edge-chain record
        "edges": list(edges),
        "closed": closed,
        "normal": normal.copy(),
        "axis_dir": axis_dir.copy(),
        "centroid": centroid.copy(),
        "pivot_point": pivot_point.copy(),
        "active_verts": active_verts,
        "orig_active_cos": [v.co.copy() for v in active_verts],
        "rails": rails,
        "projections": projections,
        "principal_axes": (pa.copy() if pa else None,
                           pb.copy() if pb else None),
    }, None


def face_principal_axes(face):
    """OBB axes of a BMFace — see profile_principal_axes."""
    normal = _face_normal_safe(face)
    if normal.length < 1e-9:
        return None, None
    return profile_principal_axes([v.co for v in face.verts], normal)


def profile_principal_axes(cos, normal):
    """Two unit axes in the profile plane aligned to the profile's own
    minimum oriented bounding box: axis_a is the OBB's longer side,
    axis_b = normal × axis_a. This keeps the widget/pivot hugging the
    profile for shapes rotated away from the world axes while still
    landing on the sides — not the diagonal — for beveled squares
    (the OBB side is edge-colinear, unlike PCA). A two-point profile
    (single edge) uses the edge direction.

    Fallback when the OBB is degenerate: world +Z projected onto the
    plane, then +Y, then +X."""
    if normal is None or normal.length < 1e-9:
        return None, None
    normal = normal.normalized()

    axis_a = _min_obb_axis(cos, normal)
    if axis_a is None:
        seeds = (
            Vector((0.0, 0.0, 1.0)),
            Vector((0.0, 1.0, 0.0)),
            Vector((1.0, 0.0, 0.0)),
        )
        for s in seeds:
            if abs(s.dot(normal)) > 0.99:
                continue
            proj = s - s.dot(normal) * normal
            if proj.length < 1e-9:
                continue
            axis_a = proj.normalized()
            break
    if axis_a is None:
        return None, None
    axis_b = normal.cross(axis_a)
    if axis_b.length < 1e-9:
        return None, None
    axis_b.normalize()
    return axis_a, axis_b


def _min_obb_axis_for_face(face):
    normal = _face_normal_safe(face)
    if normal.length < 1e-9:
        return None
    return _min_obb_axis([v.co for v in face.verts], normal)


def _min_obb_axis(cos, normal):
    """Returns the in-plane unit Vector along the longer side of the
    point set's minimum oriented bounding box. Uses the rotating-
    calipers short-cut that the optimal OBB has one side colinear with
    an edge of the convex hull — consecutive points stand in for hull
    edges (exact for convex profiles). Two points: their direction.
    None if degenerate.
    """
    if normal.length < 1e-9 or len(cos) < 2:
        return None
    if len(cos) == 2:
        d = cos[1] - cos[0]
        d = d - d.dot(normal) * normal
        return d.normalized() if d.length > 1e-9 else None
    # Orthonormal basis (u, v) in the profile plane.
    helper = Vector((0.0, 1.0, 0.0))
    if abs(normal.dot(helper)) > 0.99:
        helper = Vector((1.0, 0.0, 0.0))
    u = (helper - helper.dot(normal) * normal)
    if u.length < 1e-9:
        return None
    u = u.normalized()
    v = normal.cross(u).normalized()
    # 2D coords relative to centroid.
    centroid = Vector((0.0, 0.0, 0.0))
    for co in cos:
        centroid = centroid + co
    centroid = centroid / len(cos)
    pts = []
    for co in cos:
        d = co - centroid
        pts.append((d.dot(u), d.dot(v)))
    best = None  # (area, longer_2d_dir)
    n = len(pts)
    for i in range(n):
        ax, ay = pts[i]
        bx, by = pts[(i + 1) % n]
        ex, ey = bx - ax, by - ay
        L = math.hypot(ex, ey)
        if L < 1e-9:
            continue
        ex, ey = ex / L, ey / L
        # Perpendicular in 2D (rotate +90°): (-ey, ex).
        amin = amax = pts[0][0] * ex + pts[0][1] * ey
        pmin = pmax = pts[0][0] * (-ey) + pts[0][1] * ex
        for px, py in pts:
            a = px * ex + py * ey
            p = px * (-ey) + py * ex
            if a < amin:
                amin = a
            elif a > amax:
                amax = a
            if p < pmin:
                pmin = p
            elif p > pmax:
                pmax = p
        a_extent = amax - amin
        p_extent = pmax - pmin
        area = a_extent * p_extent
        if a_extent >= p_extent:
            longer = (ex, ey)
        else:
            longer = (-ey, ex)
        if best is None or area < best[0]:
            best = (area, longer)
    if best is None:
        return None
    lx, ly = best[1]
    axis = (u * lx + v * ly)
    if axis.length < 1e-9:
        return None
    return axis.normalized()


def _invert_slide_slope(rec, axis_dir, slope, R):
    """Angle θ whose plane-intersection slide cancels a measured
    offset-vs-projection slope `slope` along the mean rail R:
    sin(θ)/(R·n'(θ)) = -slope  →
    tan(θ) = -slope·(R·n) / (1 - slope·(R·a))."""
    n = rec.get("normal")
    if n is None:
        return math.degrees(math.atan(-slope))
    return math.degrees(math.atan2(
        -slope * R.dot(n), 1.0 - slope * R.dot(axis_dir)))


def _fit_reset_for_axis(rec, axis_dir):
    """Linear-regression fit of `offset_along_rail = slope * proj +
    C` for the given axis. Returns (slope, residual_sum_squares, R)
    — R is the mean rail direction the offsets were measured along —
    so a caller can pick the best axis and invert the slide model.
    None if the system is degenerate."""
    rails = rec["rails"]
    if not rails:
        return None
    r_sum = rails[0]["dir"] * 0.0
    for rl in rails:
        r_sum = r_sum + rl["dir"]
    if r_sum.length < 1e-6:
        return None
    R = r_sum.normalized()
    centroid = rec["centroid"]
    orig_cos = rec["orig_active_cos"]
    n = len(orig_cos)
    if n < 2:
        return None
    cprojs = [(p - centroid).dot(axis_dir) for p in orig_cos]
    offs = [(p - centroid).dot(R) for p in orig_cos]
    mean_p = sum(cprojs) / n
    mean_o = sum(offs) / n
    num = 0.0
    den = 0.0
    for i in range(n):
        dp = cprojs[i] - mean_p
        do = offs[i] - mean_o
        num += dp * do
        den += dp * dp
    if abs(den) < 1e-9:
        return None
    slope = num / den
    intercept = mean_o - slope * mean_p
    rss = 0.0
    for i in range(n):
        residual = offs[i] - (slope * cprojs[i] + intercept)
        rss += residual * residual
    return slope, rss, R


def compute_reset_for_face_record(rec):
    """Returns (axis_dir, angle_deg) so that rebuilding the record
    with axis_dir and applying angle_deg makes the face perpendicular
    to its rails. Tries both principal axes and picks the one with the
    smaller residual — i.e., the axis along which the face is actually
    sheared. Falls back to (current axis_dir, 0) if both axes are
    degenerate."""
    pa, pb = rec.get("principal_axes", (None, None))
    candidates = [a for a in (pa, pb) if a is not None]
    if rec["axis_dir"] not in candidates:
        candidates.append(rec["axis_dir"])
    best = None  # (axis, angle, rss)
    for axis in candidates:
        fit = _fit_reset_for_axis(rec, axis)
        if fit is None:
            continue
        slope, rss, R = fit
        angle = _invert_slide_slope(rec, axis, slope, R)
        if best is None or rss < best[2] - 1e-9:
            best = (axis, angle, rss)
    if best is None:
        return rec["axis_dir"], 0.0
    return best[0], best[1]


def compute_reset_angle_face(rec):
    """Angle θ (degrees) that makes the sheared face perpendicular to
    its rails (leading edges). Assumes rails are roughly parallel; the
    average rail direction stands in for "the" rail axis. Returns 0.0
    if rails cancel out or the face is already perpendicular."""
    rails = rec["rails"]
    if not rails:
        return 0.0
    r_sum = rails[0]["dir"] * 0.0
    for rl in rails:
        r_sum = r_sum + rl["dir"]
    if r_sum.length < 1e-6:
        return 0.0
    R = r_sum.normalized()

    centroid = rec["centroid"]
    orig_cos = rec["orig_active_cos"]
    projs = rec["projections"]
    offs = [(p - centroid).dot(R) for p in orig_cos]

    # Linear-least-squares fit: solve `offs ≈ -sin(θ) * projs + C`
    # across all verts. Picking a single best pair fails on beveled or
    # multi-vert faces where multiple pairs share the same proj
    # difference but have inconsistent offs differences. Fitting all
    # verts gives the angle that best equalises offset_along_rail.
    n = len(orig_cos)
    if n < 2:
        return 0.0
    mean_p = sum(projs) / n
    mean_o = sum(offs) / n
    num = 0.0
    den = 0.0
    for i in range(n):
        dp = projs[i] - mean_p
        do = offs[i] - mean_o
        num += dp * do
        den += dp * dp
    if abs(den) < 1e-9:
        return 0.0
    slope = num / den
    return _invert_slide_slope(rec, rec["axis_dir"], slope, R)


def _face_slide_factor(rail_dir, n_prime, sin_a):
    """Per-rail slide factor of the plane-intersection model: the vert
    slides along its rail to where the rail meets the face plane
    rotated by the typed angle (slide = proj · factor). Clamped like
    _angle_to_t when the rail runs parallel to the rotated plane."""
    denom = rail_dir.dot(n_prime)
    if abs(denom) < 1e-6:
        return math.copysign(1e4, sin_a) if sin_a else 0.0
    return max(-1e4, min(1e4, sin_a / denom))


def apply_records(records, angle_deg):
    t = _angle_to_t(angle_deg)
    # Face mode lands each vert on the face plane rotated by the typed
    # angle around the pivot line: slide = proj·sin(θ)/(rail·n') with
    # n' = normal·cosθ − axis·sinθ (the rotated plane normal). On
    # rails perpendicular to the face this reduces to proj·tan(θ), so
    # the typed angle IS the resulting tilt (the earlier proj·sin(θ)
    # slide under-tilted: typed 45 gave atan(sin 45) = 35.26° on a
    # cube). On oblique rails the verts still land exactly on the
    # rotated plane, so chamfer faces also tilt by the typed angle
    # (plain proj·tan(θ) overshot there: 67.5° for a typed 45°).
    a_rad = math.radians(angle_deg)
    sin_a = math.sin(a_rad)
    cos_a = math.cos(a_rad)
    for r in records:
        if r["type"] == "face":
            n = r.get("normal")
            n_prime = (n * cos_a - r["axis_dir"] * sin_a
                       if n is not None else None)
            for av, oc, rail, proj in zip(
                    r["active_verts"], r["orig_active_cos"],
                    r["rails"], r["projections"]):
                if av.is_valid:
                    factor = (t if n_prime is None else
                              _face_slide_factor(rail["dir"], n_prime,
                                                 sin_a))
                    av.co = oc + rail["dir"] * (proj * factor)


def restore_records(records):
    for r in records:
        for av, oc in zip(r["active_verts"], r["orig_active_cos"]):
            if av.is_valid:
                av.co = oc


def rebuild_record(rec, axis_dir):
    """Rebuild `rec` (face or chain) with a new axis. Returns
    (record_or_None, reason)."""
    face = rec.get("face")
    if face is not None:
        if not face.is_valid:
            return None, "face record invalid"
        return build_face_record(face, axis_dir)
    return build_chain_record(rec["edges"], axis_dir, normal=rec.get("normal"))


def records_for_faces(faces):
    """One profile record per face along its OBB axis. Returns
    (records, skip_reasons)."""
    records, reasons = [], []
    for face in faces:
        if not face.is_valid or len(face.edges) < 3:
            reasons.append("face has fewer than 3 edges")
            continue
        pa, _ = face_principal_axes(face)
        if pa is None:
            reasons.append("face is degenerate (no principal axes)")
            continue
        rec, reason = build_face_record(face, pa)
        if rec is not None:
            records.append(rec)
        else:
            reasons.append(reason)
    return records, reasons


def records_for_edges(edges):
    """One profile record per connected chain of `edges`, along the
    chain's OBB axis. Returns (records, skip_reasons)."""
    records, reasons = [], []
    edges = [e for e in edges if e.is_valid]
    try:
        chains = chains_from_edges(edges)
    except ValueError as exc:
        return [], [str(exc)]
    for verts, chain, closed in chains:
        cos = [v.co for v in verts]
        normal = chain_normal(chain, cos)
        if normal is None:
            reasons.append("edge chain has no plane (wire edge without faces)")
            continue
        pa, _ = profile_principal_axes(cos, normal)
        if pa is None:
            reasons.append("edge chain is degenerate")
            continue
        rec, reason = build_chain_record(chain, pa, normal=normal)
        if rec is not None:
            records.append(rec)
        else:
            reasons.append(reason)
    return records, reasons


# --------------------------------------------------------------------------
# Operator
# --------------------------------------------------------------------------


class IOPS_OT_mesh_shear(bpy.types.Operator):
    """Smart shear. Tilts the active selection: a face tilts around its
centroid (rail-constrained), an edge tilts in its face plane.

The selection determines the mode automatically. Numeric input sets
the angle. F is mode-specific (cycle axis edge for faces, flip active
vert for edges). D flips direction. Enter confirms, Esc/RMB
cancels. LMB clicks only pick widget handles."""

    bl_idname = "iops.mesh_shear"
    bl_label = "Shear (Smart)"
    bl_description = (
        "Smart shear that auto-detects selection. Faces tilt around "
        "their centroid; edges tilt in their face plane. Type a number "
        "for the angle, F is mode-specific, D flips direction"
    )
    bl_options = {"REGISTER"}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.type == "MESH" and obj.mode == "EDIT"

    # ----------------------------------------------------------------------
    # Lifecycle
    # ----------------------------------------------------------------------

    def invoke(self, context, event):
        obj = context.active_object
        self.obj = obj
        self.bm = bmesh.from_edit_mesh(obj.data)
        self.bm.faces.ensure_lookup_table()
        self.bm.edges.ensure_lookup_table()
        self.bm.normal_update()

        selected_faces = [f for f in self.bm.faces if f.select]
        selected_edges = [e for e in self.bm.edges if e.select]

        if not selected_faces and not selected_edges:
            self.report({"WARNING"}, "Select at least one face or edge")
            return {"CANCELLED"}

        if selected_faces:
            self.mode = "face"
            self.records, skip_reasons = records_for_faces(selected_faces)
        else:
            self.mode = "edge"
            self.records, skip_reasons = records_for_edges(selected_edges)

        if not self.records:
            msg = f"No valid {self.mode}s for shear"
            if skip_reasons:
                msg += f" ({skip_reasons[0]})"
            self.report({"WARNING"}, msg)
            return {"CANCELLED"}

        # Start at 0 so invoke doesn't alter geometry — important for
        # slanted edges where pre-applying 45° on top of the existing
        # slant compounds the shear and looks broken. The first click
        # on an orange handle kicks the angle to 45°.
        self.angle_deg = 0.0
        self.input_str = ""
        self.skip_reasons = skip_reasons
        # Point-and-click state. Each entry: {"region_pt": (x,y),
        # "axis": Vector, "rec_idx": int}. Click on any hotspot
        # rebuilds that record with the picked axis (= switches both
        # the F-toggle direction and the D-pivot side in one action).
        self._hotspots = []
        self._hover_idx = None
        self._mouse_xy = (event.mouse_region_x, event.mouse_region_y)
        # Remembered parameters (Scene.IOPS): the last confirmed shear
        # angle is applied right away as the starting preview; hinge
        # angle/steps and extrude distance seed their sub-modals.
        self._load_scene_props(context)

        # Extrude sub-modal state. While `_extrude_active`, MOUSEMOVE
        # adjusts distance, LMB/Enter confirms (rebuilds shear records
        # on the new geometry and chains back to shear), Esc/RMB
        # cancels (deletes the new geometry).
        self._extrude_active = False
        self._extrude_data = None
        self._extrude_distance = 0.0
        self._extrude_start_x = 0
        self._extrude_start_y = 0
        self._extrude_grab = False
        self._extrude_hover = False
        self._extrude_head_pt = None
        self._extrude_grab_dist = 0.0

        # Align sub-modal state. A enters; mouse hovers a face which
        # gets a 35% red overlay; LMB picks it and sets axis_dir to the
        # intersection line of the current face plane and the picked
        # face plane (projected into the current face plane). Esc/RMB
        # exits without applying.
        self._align_active = False
        self._align_face = None
        self._align_bvh = None

        # Undo push is deferred to confirm. Pushing at invoke captures
        # the PRE-shear state and finalizes that step — subsequent
        # mesh changes (the modal itself) flow into the NEXT step.
        # If a follow-up operator (e.g. straight_bevel) then auto-
        # pushes its own step, the shear modal's changes get folded
        # into the bevel's step, so a single Ctrl-Z undoes both ops
        # at once. Pushing post-_apply at confirm puts the boundary
        # AFTER the shear changes, so they land in their own step.
        # (shader managed by draw_prim — no inline shader needed)

        self._hud = HUDOverlay("mesh_shear")
        self._hud.title = "Shear"
        self._hud.bind_region(context.region)
        self._help = HelpOverlay("mesh_shear")
        items = [
            HUDItem("Type angle",         "0-9 . -",   ItemState.ON, default_state=ItemState.OFF, always_show=True),
            HUDItem("Angle ±5°",          "Alt+Wheel", ItemState.ON, default_state=ItemState.OFF, always_show=True),
            HUDItem("Delete digit",       "Backspace", ItemState.ON, default_state=ItemState.OFF, always_show=True),
            HUDItem("Cycle bbox side",    "F",         ItemState.ON, default_state=ItemState.OFF, always_show=True),
            HUDItem("Flip direction",     "D",         ItemState.ON, default_state=ItemState.OFF, always_show=True),
            HUDItem("Perp to rails",      "R",         ItemState.ON, default_state=ItemState.OFF, always_show=True),
            HUDItem("Extrude (drag arrow)", "E",       ItemState.ON, default_state=ItemState.OFF, always_show=True),
            HUDItem("Confirm + Hinge",    "Q",         ItemState.ON, default_state=ItemState.OFF, always_show=True),
            HUDItem("Align axis to face", "A",         ItemState.ON, default_state=ItemState.OFF, always_show=True),
            HUDItem("Axis to min OBB",    "B",         ItemState.ON, default_state=ItemState.OFF, always_show=True),
            HUDItem("Confirm", "Enter",   ItemState.ON, default_state=ItemState.OFF, always_show=True),
            HUDItem("Cancel",  "Esc / RMB", ItemState.ON, default_state=ItemState.OFF, always_show=True),
            HUDItem("Help / Toggle HUD", "H", ItemState.ON, default_state=ItemState.OFF, always_show=True),
        ]
        self._help.add_section(HUDSection("Shear", items))
        self._help.bind_region(context.region)
        self._last_event = capture_event(event, getattr(self, "_last_event", None))

        self._handle = safe_handler_add(bpy.types.SpaceView3D,
            self._draw_callback, (context,), "WINDOW", "POST_PIXEL", tick=True)

        self._apply()
        context.workspace.status_text_set(self._status_text())
        context.window_manager.modal_handler_add(self)
        if context.area:
            context.area.tag_redraw()
        return {"RUNNING_MODAL"}

    # ----------------------------------------------------------------------
    # Math wrappers
    # ----------------------------------------------------------------------

    # ---- persistent parameters -------------------------------------------

    def _load_scene_props(self, context):
        props = context.scene.IOPS
        self.angle_deg = props.shear_last_angle
        self._last_used_angle = props.shear_last_angle
        self._saved_extrude_distance = props.shear_extrude_last_distance

    def _note_used_angle(self):
        """Remember the last non-zero angle actually applied. Extrude /
        hinge confirms reset angle_deg to 0 on the new cap, so a final
        Enter would otherwise overwrite the remembered angle with 0."""
        a = self._effective_angle()
        if abs(a) > 1e-6:
            self._last_used_angle = a

    def _save_shear_angle(self, context):
        a = self.angle_deg
        if abs(a) < 1e-6:
            a = getattr(self, "_last_used_angle", 0.0)
        context.scene.IOPS.shear_last_angle = a

    def _save_extrude_distance(self, context, distance):
        context.scene.IOPS.shear_extrude_last_distance = distance
        self._saved_extrude_distance = distance

    def _effective_angle(self):
        if self.input_str and self.input_str not in ("-", ".", "-."):
            try:
                return float(self.input_str)
            except ValueError:
                return self.angle_deg
        return self.angle_deg

    def _apply(self):
        apply_records(self.records, self._effective_angle())
        self.bm.normal_update()
        bmesh.update_edit_mesh(self.obj.data)

    def _restore_records(self):
        restore_records(self.records)
        self.bm.normal_update()
        bmesh.update_edit_mesh(self.obj.data)

    def _enter_extrude(self, event):
        """Begin the extrude sub-modal. The new face/edge is positioned
        as the *mirror* of the current shear across the un-sheared
        plane: each new vert's base position is `orig - shear_delta`,
        the mirror image of where the old vert moved to. Mouse drag
        then translates the mirrored set along the rail direction.

        Net effect: the segment between old face and new face has
        matched mitered ends (saw-off on one end, opposite saw-off on
        the other), which is what you want when chaining a frame from
        sheared faces — picture-frame mitres."""
        if not self.records:
            return False
        # Commit a typed-but-unconfirmed angle first: the mirror below
        # reads angle_deg, and the visible mesh already shows the typed
        # value via _effective_angle() — the extrude must match it.
        self.angle_deg = self._effective_angle()
        self.input_str = ""
        self._apply()
        self._note_used_angle()

        if True:
            # Every record extrudes together as ONE region (faces:
            # extrude_face_region, edge chains: extrude_edge_only), so
            # edges shared between records get no wall — like the
            # native extrude — while side direction and saw-off delay
            # are still derived per record. A vert shared by several
            # records averages their sides and takes the smallest delay.
            face_recs = list(self.records)
            if self.mode == "face" and not all(
                    r["face"] is not None and r["face"].is_valid for r in face_recs):
                self.report({"WARNING"}, "extrude: face record invalid")
                return False

            def mirror(vec, n):
                # Same convention as edge mode: 2(v·n)n - v. This is
                # the negation of the textbook plane-reflection so the
                # OUTGOING direction points away from the existing body.
                # At zero shear (n parallel to rail) this collapses to
                # +rail_dir, which is the natural "extrude outward"
                # direction (rail goes from anchor INTO the face vert).
                return 2.0 * vec.dot(n) * n - vec

            a_rad = math.radians(self.angle_deg)
            sin_t = math.sin(a_rad)
            cos_t = math.cos(a_rad)
            straight = abs(sin_t) < 1e-6

            per_old_vert = {}   # BMVert -> [anchor, [sides], min_delay]
            face_normals = {}
            for r in face_recs:
                face = r["face"]
                rails = r.get("rails", [])
                projs = r.get("projections", [])
                active_verts = r["active_verts"]
                if not rails or not projs:
                    return False
                rec_n = r.get("normal")
                n_prime = (rec_n * cos_t - r["axis_dir"] * sin_t
                           if rec_n is not None else None)
                # Mirror plane = the CURRENT (sheared) profile normal:
                # the live face normal when there is a face, else the
                # rotated plane normal n'.
                if face is not None:
                    face_normal = _face_normal_safe(face)
                else:
                    face_normal = (n_prime.copy() if n_prime is not None
                                   else rec_n.copy())
                if face_normal.length < 1e-9:
                    return False
                face_normals[id(r)] = face_normal

                def slide_of(rail, proj, n_prime=n_prime):
                    if n_prime is None:
                        return proj * sin_t
                    return proj * _face_slide_factor(rail["dir"], n_prime,
                                                     sin_t)

                slides = [slide_of(rail, proj)
                          for rail, proj in zip(rails, projs)]
                slide_max = max(slides) if slides else 0.0
                # Unsheared face (always the case right after a hinge
                # confirm): square end, not a miter — extrude straight
                # along its normal. The rail mirror only encodes a
                # miter when there IS a shear.
                unit_normal = face_normal.normalized()
                for av, rail, slide in zip(active_verts, rails, slides):
                    if straight:
                        side = unit_normal.copy()
                    else:
                        side = mirror(rail["dir"], face_normal)
                        if side.length < 1e-9:
                            side = rail["dir"]  # rail parallel to normal
                        else:
                            side = side.normalized()
                    # Same slide rule as apply_records so the mirrored
                    # saw-off delays match the actual slides.
                    delay = slide_max - slide
                    entry = per_old_vert.get(av)
                    if entry is None:
                        per_old_vert[av] = [av.co.copy(), [side], delay]
                    else:
                        entry[1].append(side)
                        entry[2] = min(entry[2], delay)

            if self.mode == "face":
                orig_faces = [r["face"] for r in face_recs]
                res = bmesh.ops.extrude_face_region(self.bm, geom=orig_faces)
                new_geom = res.get("geom", [])
                new_verts = [g for g in new_geom
                             if isinstance(g, bmesh.types.BMVert)]
                new_faces = [g for g in new_geom
                             if isinstance(g, bmesh.types.BMFace)]
                # Caps: new faces whose verts are all new (side walls
                # always touch an old vert). Pair them with the
                # originals by centroid so record order is preserved.
                new_vert_set = set(new_verts)
                caps = [f for f in new_faces
                        if all(v in new_vert_set for v in f.verts)]
                if len(caps) != len(orig_faces) or not new_verts:
                    return False
                targets = []
                for of in orig_faces:
                    c = of.calc_center_median()
                    best = min(caps,
                               key=lambda f: (f.calc_center_median() - c).length)
                    targets.append(best)
                    caps.remove(best)
                kind = "face"
            else:
                orig_faces = []
                chain_edges = []
                seen_e = set()
                for r in face_recs:
                    for e in r["edges"]:
                        if e.is_valid and e not in seen_e:
                            seen_e.add(e)
                            chain_edges.append(e)
                res = bmesh.ops.extrude_edge_only(self.bm, edges=chain_edges)
                new_geom = res.get("geom", [])
                new_verts = [g for g in new_geom
                             if isinstance(g, bmesh.types.BMVert)]
                new_vert_set = set(new_verts)
                # The copied profile edges: both verts new (the walls'
                # side edges touch an old vert).
                targets = [g for g in new_geom
                           if isinstance(g, bmesh.types.BMEdge)
                           and all(v in new_vert_set for v in g.verts)]
                if not targets or not new_verts:
                    return False
                kind = "chain"

            # Match each new vert to its old counterpart by position
            # (they coincide right after extrude_face_region).
            fallback_n = next(iter(face_normals.values()))
            anchors = []
            sides = []
            delays = []
            for nv in new_verts:
                best = None
                for ov, payload in per_old_vert.items():
                    if (nv.co - ov.co).length < 1e-6:
                        best = payload
                        break
                if best is None:
                    anchors.append(nv.co.copy())
                    sides.append(fallback_n.copy())
                    delays.append(0.0)
                else:
                    side = Vector((0.0, 0.0, 0.0))
                    for sd in best[1]:
                        side += sd
                    side = (side.normalized() if side.length > 1e-9
                            else best[1][0])
                    anchors.append(best[0])
                    sides.append(side)
                    delays.append(best[2])

            # Average side direction (for the on-screen arrow indicator).
            avg = Vector((0.0, 0.0, 0.0))
            for sd in sides:
                avg = avg + sd
            avg_dir = avg.normalized() if avg.length > 1e-9 else fallback_n

            # Centroid of all sheared faces (arrow tail anchor).
            center = Vector((0.0, 0.0, 0.0))
            for an in anchors:
                center = center + an
            center = center / len(anchors)

            # NOTE: extrude_face_region leaves the original faces in
            # place under the new caps. We DEFER deleting them until
            # _confirm_extrude — if the user cancels, the originals
            # must still be present (records point at them and
            # downstream callers deref without is_valid checks).
            self._extrude_data = {
                "kind": kind,
                "verts": new_verts,
                "anchors": anchors,
                "sides": sides,
                "delays": delays,
                "avg_dir": avg_dir.copy(),
                "center": center.copy(),
                "targets": targets,
                "orig_faces": orig_faces,
            }
        self._extrude_active = True
        # Arrow handle state: the new geometry only moves while the
        # arrow head is grabbed (LMB on it). Distance starts at the
        # remembered value so a repeated extrude lands where the last
        # one did; the handle drag adjusts from there.
        self._extrude_grab = False
        self._extrude_hover = False
        self._extrude_head_pt = None
        self._extrude_start_x = event.mouse_region_x
        self._extrude_start_y = event.mouse_region_y
        self._extrude_grab_dist = 0.0
        self._extrude_apply_distance(
            max(0.0, getattr(self, "_saved_extrude_distance", 0.0)))
        self.bm.normal_update()
        bmesh.update_edit_mesh(self.obj.data)
        return True

    def _extrude_apply_distance(self, t):
        """Position the extruded verts for distance ``t``."""
        d = self._extrude_data
        self._extrude_distance = t
        # Saw-off mirror: each new vert gets its own side direction
        # (rail mirrored across the sheared profile plane) and its own
        # delay (proj-based). Vert with max projection moves
        # immediately; pivot-side verts wait until t exceeds their delay.
        for v, anchor, side, delay in zip(
                d["verts"], d["anchors"], d["sides"], d["delays"]):
            if v.is_valid:
                v.co = anchor + side * max(0.0, t - delay)

    def _extrude_arrow_world(self):
        """(tail, unit direction, head) of the extrude arrow in object
        space. Tail = centroid of the sheared profile, head = the LIVE
        centroid of the extruded verts, so the arrow always ends on the
        resulting profile (per-vert delays make it shorter than the
        nominal distance). Direction falls back to the mean side
        direction while the head still sits on the tail."""
        d = self._extrude_data
        center = d["center"]
        live = [v.co for v in d["verts"] if v.is_valid]
        if live:
            head = Vector((0.0, 0.0, 0.0))
            for co in live:
                head += co
            head /= len(live)
        else:
            head = center.copy()
        direction = head - center
        if direction.length < 1e-6:
            direction = d["avg_dir"]
        if direction.length < 1e-9:
            return center, None, head
        return center, direction.normalized(), head

    def _extrude_unit_px(self, context, center, unit_dir):
        """Screen length (px) of one object-space unit along the arrow
        at its tail — converts a handle drag in pixels to distance."""
        region = context.region
        rv3d = context.region_data
        if region is None or rv3d is None:
            return None
        mw = self.obj.matrix_world
        a = view3d_utils.location_3d_to_region_2d(region, rv3d, mw @ center)
        b = view3d_utils.location_3d_to_region_2d(
            region, rv3d, mw @ (center + unit_dir))
        if a is None or b is None:
            return None
        L = math.hypot(b[0] - a[0], b[1] - a[1])
        return L if L > 1e-3 else None

    def _extrude_modal(self, context, event):
        HANDLE_PX = 14.0
        if event.type == "MOUSEMOVE" and not self._extrude_grab:
            # Not dragging: only track whether the arrow head is under
            # the cursor (the draw callback stores its region point).
            hp = self._extrude_head_pt
            hover = False
            if hp is not None:
                dx = event.mouse_region_x - hp[0]
                dy = event.mouse_region_y - hp[1]
                hover = (dx * dx + dy * dy) <= HANDLE_PX * HANDLE_PX
            if hover != self._extrude_hover:
                self._extrude_hover = hover
                if context.area:
                    context.area.tag_redraw()
            return {"RUNNING_MODAL"}
        if event.type == "MOUSEMOVE":
            # Handle drag: project the mouse delta since the grab onto
            # the arrow's on-screen direction and convert px -> object
            # units through the arrow's own scale, so the head follows
            # the cursor. Recomputed each frame so it tracks orbits.
            world_center, unit_dir, _head = self._extrude_arrow_world()
            screen_dir = (None if unit_dir is None else
                          self._screen_direction(context, world_center, unit_dir))
            unit_px = (None if unit_dir is None else
                       self._extrude_unit_px(context, world_center, unit_dir))
            mx, my = event.mouse_region_x, event.mouse_region_y
            region = context.region
            if region is not None:
                # Wrap the cursor at the region border so a long drag
                # isn't capped by the viewport size. The start point
                # moves by the same jump so the projected distance is
                # continuous across the wrap.
                wx, wy = mx, my
                margin = 2
                if mx <= 0:
                    wx = region.width - margin - 1
                elif mx >= region.width - 1:
                    wx = margin
                if my <= 0:
                    wy = region.height - margin - 1
                elif my >= region.height - 1:
                    wy = margin
                if (wx, wy) != (mx, my):
                    self._extrude_start_x += wx - mx
                    self._extrude_start_y += wy - my
                    context.window.cursor_warp(region.x + wx, region.y + wy)
                    mx, my = wx, wy
            dx = mx - self._extrude_start_x
            dy = my - self._extrude_start_y
            if screen_dir is None:
                # Camera looking down the arrow — fall back to
                # horizontal motion so the user isn't stuck.
                projected = dx
            else:
                projected = dx * screen_dir[0] + dy * screen_dir[1]
            if unit_px is None:
                unit_px = 100.0
            delta = projected / unit_px
            if event.shift:
                delta *= 0.1
            self._extrude_apply_distance(
                max(0.0, self._extrude_grab_dist + delta))
            self.bm.normal_update()
            bmesh.update_edit_mesh(self.obj.data)
            context.workspace.status_text_set(self._status_text())
            if context.area:
                context.area.tag_redraw()
            return {"RUNNING_MODAL"}
        if event.type == "LEFTMOUSE" and event.value == "RELEASE":
            if self._extrude_grab:
                self._extrude_grab = False
                if context.area:
                    context.area.tag_redraw()
            return {"RUNNING_MODAL"}
        if event.value == "PRESS":
            if event.type == "LEFTMOUSE" and self._extrude_hover:
                # Grab the arrow head: drag distance is measured from
                # here, on top of the current extrude distance.
                self._extrude_grab = True
                self._extrude_start_x = event.mouse_region_x
                self._extrude_start_y = event.mouse_region_y
                self._extrude_grab_dist = self._extrude_distance
                return {"RUNNING_MODAL"}
            if event.type in {"LEFTMOUSE", "RET", "NUMPAD_ENTER", "SPACE"}:
                self._save_extrude_distance(context, self._extrude_distance)
                self._confirm_extrude()
                context.workspace.status_text_set(self._status_text())
                if context.area:
                    context.area.tag_redraw()
                return {"RUNNING_MODAL"}
            if event.type in {"RIGHTMOUSE", "ESC"}:
                self._cancel_extrude()
                context.workspace.status_text_set(self._status_text())
                if context.area:
                    context.area.tag_redraw()
                return {"RUNNING_MODAL"}
        return {"RUNNING_MODAL"}

    def _confirm_extrude(self):
        d = self._extrude_data
        kind = d["kind"]
        # Now that the user committed, the original face becomes an
        # interior face and must be removed. Side walls already share
        # its verts and edges so FACES_ONLY leaves the surrounding
        # topology intact. Cancel doesn't reach this path so the
        # face survives a cancel.
        # "FACES" (not FACES_ONLY): edges shared between two extruded
        # faces got no side wall, so they'd be left as wire otherwise.
        orig_faces = [f for f in d.get("orig_faces", []) if f.is_valid]
        if kind == "face" and orig_faces:
            bmesh.ops.delete(self.bm, geom=orig_faces, context="FACES")
        # Move the selection (and select_history) onto the new cap:
        # sub-modals entered from here (Q hinge) read the selection,
        # and a stale pre-extrude edge in select_history would hand
        # the hinge a distant axis.
        try:
            self.bm.select_history.clear()
        except (TypeError, RuntimeError):
            pass
        targets = [g for g in d.get("targets", []) if g.is_valid]
        if targets:
            # Full deselect (not just faces) — stray selected edges or
            # verts left by earlier chained ops would otherwise keep
            # accumulating in the selection.
            for v in self.bm.verts:
                v.select = False
            for e in self.bm.edges:
                e.select = False
            for f in self.bm.faces:
                f.select = False
            for g in targets:
                g.select_set(True)
            self.bm.select_flush_mode()
            if kind == "face":
                new_records, _ = records_for_faces(targets)
            else:
                # The extruded chain lies in the mirrored plane: keep
                # the old normal as the orientation seed by letting
                # chain_normal read the new wall faces / vert plane.
                new_records, _ = records_for_edges(targets)
            if new_records:
                self.records = new_records
            else:
                # Never keep records pointing at the deleted originals.
                self.records = []
                self.report({"WARNING"},
                            "extrude: shear could not attach to the new geometry")
        self._extrude_active = False
        self._extrude_data = None
        # The new cap picks up the last USED angle right away, so
        # chaining E / Enter / E keeps the same miter without retyping
        # (the records were rebuilt on the cap, so applying from 0 is
        # exact). The remembered extrude distance seeds the next E.
        self.angle_deg = getattr(self, "_last_used_angle", 0.0)
        self.input_str = ""
        self._hotspots = []
        self._hover_idx = None
        if self.records and abs(self.angle_deg) > 1e-6:
            self._apply()

    def _screen_direction(self, context, world_pt, world_dir):
        """Returns a unit (dx, dy) tuple in region pixels representing
        the on-screen direction of `world_dir` originating at
        `world_pt`. None if either point fails to project or the
        screen-space length collapses (camera looks down the arrow)."""
        region = context.region
        rv3d = context.region_data
        if region is None or rv3d is None:
            return None
        mw = self.obj.matrix_world
        p_tail = view3d_utils.location_3d_to_region_2d(
            region, rv3d, mw @ world_pt)
        p_head = view3d_utils.location_3d_to_region_2d(
            region, rv3d, mw @ (world_pt + world_dir))
        if p_tail is None or p_head is None:
            return None
        dx = p_head[0] - p_tail[0]
        dy = p_head[1] - p_tail[1]
        L = math.hypot(dx, dy)
        if L < 1e-3:
            return None
        return (dx / L, dy / L)

    def _cancel_extrude(self):
        d = self._extrude_data
        new_verts = [v for v in d.get("verts", []) if v is not None and v.is_valid]
        if new_verts:
            bmesh.ops.delete(self.bm, geom=new_verts, context="VERTS")
        # The original face was NOT deleted on extrude entry (delete
        # is deferred to _confirm_extrude), so the existing record's
        # face ref is still valid here. No restore needed.
        self._extrude_active = False
        self._extrude_data = None
        self.bm.normal_update()
        bmesh.update_edit_mesh(self.obj.data)
        self._hotspots = []
        self._hover_idx = None

    def _toggle_align_highlight(self, context, event):
        """A: raycast the face under the cursor and latch it. If a
        face is hit, axis_dir aligns to the intersection line of the
        current face plane and the picked face plane, and the picked
        face stays highlighted 35% red. If A is pressed over empty
        space, the highlight is cleared. Each press re-picks — A on
        a different face switches both the highlight and the axis;
        A on nothing clears.
        """
        # Drop any prior BVH first so a raise inside FromBMesh leaves
        # a known-clean state instead of a stale tree from the last
        # press.
        self._align_bvh = None
        # Refresh face normals so the picked face's plane uses the
        # current sheared geometry — _apply_align reads target.normal
        # via _face_normal_safe which only falls back on zero-length.
        self.bm.normal_update()
        self.bm.faces.ensure_lookup_table()
        self._align_bvh = BVHTree.FromBMesh(self.bm)
        self._mouse_xy = (event.mouse_region_x, event.mouse_region_y)
        picked = self._raycast_face_under_cursor(context)
        # Drop the BVH right after the snapshot — it isn't needed
        # again until the next A press, and holding it across shears
        # would let stale geometry leak into the next pick.
        self._align_bvh = None
        if picked is None:
            self._align_active = False
            self._align_face = None
            return
        rec = self.records[0] if self.records else None
        if rec is not None and picked is not rec.get("face"):
            self._apply_align(picked)
        self._align_face = picked
        self._align_active = True

    def _raycast_face_under_cursor(self, context):
        if self._align_bvh is None:
            return None
        region = context.region
        rv3d = context.region_data
        if region is None or rv3d is None:
            return None
        mx, my = self._mouse_xy
        coord = (mx, my)
        view_dir = view3d_utils.region_2d_to_vector_3d(region, rv3d, coord)
        ray_origin = view3d_utils.region_2d_to_origin_3d(
            region, rv3d, coord)
        mw = self.obj.matrix_world
        try:
            mw_inv = mw.inverted()
        except ValueError:
            return None
        # Transform the world-space ray to object-local space. Naive
        # `mw_inv.to_3x3() @ view_dir` is wrong under non-uniform
        # scale or shear (directions transform by the inverse-
        # transpose of the linear part, not by the linear part of
        # the inverse). Compute the local direction from two
        # transformed points to stay correct under any affine mw.
        local_origin = mw_inv @ ray_origin
        local_dir = (mw_inv @ (ray_origin + view_dir)) - local_origin
        if local_dir.length < 1e-12:
            return None
        local_dir = local_dir.normalized()
        hit = self._align_bvh.ray_cast(local_origin, local_dir)
        if hit is None or hit[2] is None:
            return None
        idx = hit[2]
        self.bm.faces.ensure_lookup_table()
        if 0 <= idx < len(self.bm.faces):
            return self.bm.faces[idx]
        return None

    def _apply_align(self, target):
        """Set axis_dir on the active face record to the line of
        intersection between the current face's plane and the picked
        face's plane (projected into the current face plane). Parallel
        planes are no-ops (cross product collapses).

        Any early-return path AFTER restore_records re-applies the
        prior shear so the visible mesh stays in sync with the user's
        in-progress angle. Otherwise the user sees an unexplained
        un-shear when alignment can't be computed."""
        if not self.records:
            return
        rec = self.records[0]
        face = rec.get("face")
        if face is not None and (not face.is_valid or target is face):
            return
        # Compute the axis BEFORE touching the records — this way any
        # degenerate / parallel-plane miss bails without disturbing
        # the visible shear pose.
        n_current = rec["normal"]
        n_target = _face_normal_safe(target)
        if n_current.length < 1e-9 or n_target.length < 1e-9:
            self.report({"INFO"}, "align: degenerate face normal")
            return
        axis = n_current.cross(n_target)
        if axis.length < 1e-6:
            self.report({"INFO"}, "align: planes parallel — no axis change")
            return
        axis = axis - axis.dot(n_current) * n_current
        if axis.length < 1e-9:
            return
        axis = axis.normalized()
        # Restore so the new axis lives in the unsheared face plane.
        restore_records(self.records)
        self.bm.normal_update()
        new_rec, err = rebuild_record(rec, axis)
        if new_rec is None:
            # rebuild failed (e.g. isolated face): re-apply
            # the prior shear so the visible state matches the
            # un-rebuilt record.
            self._apply()
            self.report({"INFO"}, f"align failed: {err}")
            return
        self.records = [new_rec]
        self.angle_deg = 0.0
        self.input_str = ""
        self._hotspots = []
        self._hover_idx = None
        bmesh.update_edit_mesh(self.obj.data)

    def _b_action(self):
        """Set axis_dir to the longer side of the face's minimum
        oriented bounding box (rotating calipers over the face's own
        edges, so the axis lands along whichever edge produces the
        smallest bounding rectangle in the face plane). Records are
        restored to the unsheared pose first; angle resets to 0°.

        Same restored-but-unrebuilt safety as _apply_align: if the
        OBB or rebuild can't proceed AFTER restore, re-apply the
        prior shear before returning."""
        if not self.records:
            return
        rec = self.records[0]
        axis = _min_obb_axis(rec["orig_active_cos"], rec["normal"])
        if axis is None:
            self.report({"INFO"}, "min-OBB axis unavailable")
            return
        restore_records(self.records)
        self.bm.normal_update()
        new_rec, err = rebuild_record(rec, axis)
        if new_rec is None:
            self._apply()
            self.report({"INFO"}, f"min-OBB rebuild failed: {err}")
            return
        self.records = [new_rec]
        self.angle_deg = 0.0
        self.input_str = ""
        self._hotspots = []
        self._hover_idx = None
        bmesh.update_edit_mesh(self.obj.data)

    def _update_hover(self):
        """Pick the hotspot whose 2D position is closest to the mouse,
        within HOVER_PX. Sets self._hover_idx (or None)."""
        HOVER_PX = 14.0
        if not self._hotspots:
            self._hover_idx = None
            return
        mx, my = self._mouse_xy
        best = (None, HOVER_PX * HOVER_PX)
        for i, h in enumerate(self._hotspots):
            rp = h.get("region_pt")
            if rp is None:
                continue
            dx, dy = rp[0] - mx, rp[1] - my
            d2 = dx * dx + dy * dy
            if d2 < best[1]:
                best = (i, d2)
        self._hover_idx = best[0]

    def _click_hotspot(self, idx):
        """Dispatch a click on the hotspot at `idx`. Two kinds:
        - axis_pick: rebuild the record with the clicked axis_dir
          (saw-off pivot snaps to the corresponding face edge).
        - reset: snap the face perpendicular to its rails (= R)."""
        if idx >= len(self._hotspots):
            return
        h = self._hotspots[idx]
        kind = h.get("kind", "axis_pick")
        rec_idx = h.get("rec_idx", 0)
        if rec_idx >= len(self.records):
            return
        if kind == "axis_pick":
            restore_records(self.records)
            self.bm.normal_update()
            new_rec, _ = rebuild_record(self.records[rec_idx], h["axis"])
            if new_rec is not None:
                self.records[rec_idx] = new_rec
            # Coming out of a reset state, clicking a direction handle
            # should produce visible motion — default to a 45° saw cut.
            if abs(self.angle_deg) < 1e-3 and not self.input_str:
                self.angle_deg = 45.0
            self._apply()
        elif kind == "reset":
            self.input_str = ""
            r = self.records[rec_idx]
            restore_records([r])
            self.bm.normal_update()
            new_axis, angle = compute_reset_for_face_record(r)
            new_rec, _ = rebuild_record(r, new_axis)
            if new_rec is not None:
                apply_records([new_rec], angle)
                self.bm.normal_update()
                rebuilt, _ = rebuild_record(new_rec, new_rec["axis_dir"])
                if rebuilt is not None:
                    self.records[rec_idx] = rebuilt
            self.angle_deg = 0.0
            bmesh.update_edit_mesh(self.obj.data)
        self._hotspots = []  # invalidate; redraw rebuilds
        self._hover_idx = None

    def _f_action(self):
        """Cycle the saw-off pivot through the four sides of the
        profile's OBB: axis +a, +b, -a, -b (the pivot is the side the
        axis points away from). Starts from whichever side the current
        axis is closest to."""
        restore_records(self.records)
        self.bm.normal_update()
        new_records = []
        for r in self.records:
            pa, pb = r.get("principal_axes", (None, None))
            if pa is None or pb is None:
                new_records.append(r)
                continue
            sides = (pa, pb, -pa, -pb)
            cur = r["axis_dir"]
            cur_i = max(range(4), key=lambda i: cur.dot(sides[i]))
            new_rec, _ = rebuild_record(r, sides[(cur_i + 1) % 4])
            new_records.append(new_rec if new_rec is not None else r)
        self.records = new_records
        self._apply()

    # ----------------------------------------------------------------------
    # Modal
    # ----------------------------------------------------------------------

    def _status_text(self):
        if self._extrude_active:
            return (
                f"Extrude ({self.mode}): {self._extrude_distance:.4f} | "
                "[LMB on arrow] drag | [Shift] precise | "
                "[LMB/Enter] confirm + back to shear | "
                "[Esc/RMB] cancel extrude"
            )
        typed = f" | typing: {self.input_str}" if self.input_str else ""
        return (
            f"Shear ({self.mode}): {self._effective_angle():.2f}°{typed} | "
            "[0-9 . -] type | [Alt+Wheel] ±5° | [Backspace] del | "
            "[F] cycle bbox side | [D] flip direction | "
            "[R] perpendicular to rails | [E] extrude | [Q] hinge | "
            "[A] align axis to face | [B] min-OBB axis | "
            "[Enter] confirm | [Esc/RMB] cancel"
        )

    def modal(self, context, event):
        try:
            return self._modal(context, event)
        except ReferenceError:
            # bmesh element invalidated mid-modal (undo, addon
            # reload, or some other op that freed the underlying
            # data). Tear down the draw handler so the viewport
            # isn't left with a dangling render callback.
            self._finish(context)
            self.report({"WARNING"},
                        "shear: bmesh data became invalid — operator cancelled")
            return {"CANCELLED"}
        except Exception:
            # Any other exception leaves the draw handler stuck
            # too. Clean up before propagating.
            self._finish(context)
            raise

    def _modal(self, context, event):
        if context.area:
            context.area.tag_redraw()
        self._last_event = capture_event(event, getattr(self, "_last_event", None))
        try:
            theme_prefs = context.preferences.addons["InteractionOps"].preferences.iops_theme
        except (KeyError, AttributeError):
            theme_prefs = None
        if theme_prefs is not None:
            helpo = getattr(self, "_help", None)
            hud = getattr(self, "_hud", None)
            if helpo is not None and helpo.handle_drag_event(context, event, theme_prefs):
                return {'RUNNING_MODAL'}
            if hud is not None and hud.handle_drag_event(context, event, theme_prefs):
                return {'RUNNING_MODAL'}
            if helpo is not None and helpo.handle_toggle_event(event, theme_prefs):
                return {'RUNNING_MODAL'}
            if hud is not None and hud.handle_param_toggle_event(event, theme_prefs):
                return {'RUNNING_MODAL'}

        if (event.type in {"WHEELUPMOUSE", "WHEELDOWNMOUSE"} and event.alt
                and not self._extrude_active):
            # Alt+Wheel: nudge the angle in 5° steps. Typed input is
            # committed first so the nudge continues from what the
            # user sees on screen.
            delta = 5.0 if event.type == "WHEELUPMOUSE" else -5.0
            self.angle_deg = self._effective_angle() + delta
            self.input_str = ""
            self._apply()
            context.workspace.status_text_set(self._status_text())
            return {"RUNNING_MODAL"}

        if (event.type in {"MIDDLEMOUSE", "WHEELUPMOUSE", "WHEELDOWNMOUSE"}
                or event.type.startswith("NDOF")):
            return {"PASS_THROUGH"}

        if self._extrude_active:
            return self._extrude_modal(context, event)

        if event.type == "MOUSEMOVE":
            self._mouse_xy = (event.mouse_region_x, event.mouse_region_y)
            self._update_hover()
            return {"RUNNING_MODAL"}

        if event.value == "PRESS":
            if event.type in DIGIT_TYPES:
                self.input_str += DIGIT_TYPES[event.type]
                self._apply()
                context.workspace.status_text_set(self._status_text())
                return {"RUNNING_MODAL"}

            if event.type in {"PERIOD", "NUMPAD_PERIOD"}:
                if "." not in self.input_str:
                    self.input_str += "."
                    context.workspace.status_text_set(self._status_text())
                return {"RUNNING_MODAL"}

            if event.type in {"MINUS", "NUMPAD_MINUS"}:
                if self.input_str.startswith("-"):
                    self.input_str = self.input_str[1:]
                else:
                    self.input_str = "-" + self.input_str
                self._apply()
                context.workspace.status_text_set(self._status_text())
                return {"RUNNING_MODAL"}

            if event.type == "BACK_SPACE":
                self.input_str = self.input_str[:-1]
                self._apply()
                context.workspace.status_text_set(self._status_text())
                return {"RUNNING_MODAL"}

            if event.type == "F":
                self._f_action()
                context.workspace.status_text_set(self._status_text())
                return {"RUNNING_MODAL"}

            if event.type == "E":
                if self._enter_extrude(event):
                    context.workspace.status_text_set(self._status_text())
                return {"RUNNING_MODAL"}

            if event.type == "Q":
                # Confirm the shear and hand over to the Hinge operator
                # on the same selection (it picks its axis from the
                # mouse position, so the hand-off is seamless).
                self.angle_deg = self._effective_angle()
                self.input_str = ""
                self._apply()
                self._note_used_angle()
                self._save_shear_angle(context)
                bpy.ops.ed.undo_push(message="Shear")
                self._finish(context)
                try:
                    bpy.ops.iops.mesh_hinge("INVOKE_DEFAULT")
                except RuntimeError as exc:
                    self.report({"WARNING"}, f"hinge: {exc}")
                return {"FINISHED"}

            if event.type == "A":
                self._toggle_align_highlight(context, event)
                context.workspace.status_text_set(self._status_text())
                return {"RUNNING_MODAL"}

            if event.type == "B":
                self._b_action()
                context.workspace.status_text_set(self._status_text())
                return {"RUNNING_MODAL"}

            if event.type == "R":
                self.input_str = ""
                if True:
                    # R may pick an axis different from the current one
                    # (whichever principal axis is aligned with the
                    # actual shear direction). After R, the records are
                    # rebuilt at the perpendicular state so subsequent
                    # angle inputs shear relative to the snapped pose.
                    # face.normal must be up-to-date at every
                    # build_face_record call, or its axis-into-plane
                    # projection is computed against a stale normal and
                    # the wrong principal axis gets picked.
                    restore_records(self.records)
                    self.bm.normal_update()
                    perp_records = []
                    for r in self.records:
                        new_axis, angle = compute_reset_for_face_record(r)
                        new_rec, _ = rebuild_record(r, new_axis)
                        if new_rec is not None:
                            apply_records([new_rec], angle)
                            self.bm.normal_update()
                            perp_records.append(new_rec)
                        else:
                            perp_records.append(r)
                    rebased = []
                    for r in perp_records:
                        rebuilt, _ = rebuild_record(r, r["axis_dir"])
                        rebased.append(rebuilt if rebuilt is not None else r)
                    self.records = rebased
                    bmesh.update_edit_mesh(self.obj.data)
                # Reset shear value and invalidate the gizmo state so
                # the next draw rebuilds hotspots against the new perp
                # geometry.
                self.angle_deg = 0.0
                self._hotspots = []
                self._hover_idx = None
                context.workspace.status_text_set(self._status_text())
                return {"RUNNING_MODAL"}

            if event.type == "D":
                if self.input_str:
                    if self.input_str.startswith("-"):
                        self.input_str = self.input_str[1:]
                    else:
                        self.input_str = "-" + self.input_str
                else:
                    # Saw-off semantics: flipping axis_dir moves the
                    # pivot to the opposite bbox side.
                    restore_records(self.records)
                    self.bm.normal_update()
                    new_records = []
                    for r in self.records:
                        new_rec, _ = rebuild_record(r, -r["axis_dir"])
                        new_records.append(new_rec if new_rec is not None else r)
                    self.records = new_records
                self._apply()
                context.workspace.status_text_set(self._status_text())
                return {"RUNNING_MODAL"}

            if event.type == "LEFTMOUSE":
                # LMB only ever picks a hotspot — never confirms.
                # Misclicks outside a handle are absorbed so an
                # accidental click can't end the operator early.
                if self._hover_idx is not None:
                    self._click_hotspot(self._hover_idx)
                    context.workspace.status_text_set(self._status_text())
                return {"RUNNING_MODAL"}

            if event.type in {"RET", "NUMPAD_ENTER", "SPACE"}:
                self.angle_deg = self._effective_angle()
                self.input_str = ""
                self._apply()
                self._note_used_angle()
                self._save_shear_angle(context)
                # Push AFTER the final apply so the post-shear state
                # is the boundary; otherwise the modal's mesh changes
                # get rolled into the next operator's undo step.
                bpy.ops.ed.undo_push(message="Shear")
                self._finish(context)
                return {"FINISHED"}

            if event.type in {"RIGHTMOUSE", "ESC"}:
                self._restore_records()
                self._finish(context)
                return {"CANCELLED"}

        return {"RUNNING_MODAL"}

    def _finish(self, context):
        if getattr(self, "_handle", None):
            safe_handler_remove(self._handle, bpy.types.SpaceView3D, "WINDOW")
            self._handle = None
        context.workspace.status_text_set(None)
        if context.area:
            context.area.tag_redraw()
        # Drop the bmesh wrapper and any stored BMesh element refs so
        # the operator instance can be freed safely after a later undo
        # invalidates the underlying mesh. Without this, operator
        # destruction calls bpy_bmesh_dealloc on a stale wrapper and
        # crashes Blender during ed_undo_exec → WM_operator_stack_clear.
        self.bm = None
        self.records = []
        self._hotspots = []
        self._hover_idx = None
        self._extrude_data = None
        self._extrude_active = False
        self._align_active = False
        self._align_face = None
        self._align_bvh = None
        self.obj = None

    # ----------------------------------------------------------------------
    # Draw
    # ----------------------------------------------------------------------

    def _draw_dot(self, p, *, color, context, radius=6.0):
        """Draw a filled disc at screen point *p* using the theme primitives."""
        if radius <= 4.0:
            size_token = "preview"
        elif radius <= 6.0:
            size_token = "default"
        elif radius <= 9.0:
            size_token = "active"
        else:
            size_token = "closest"
        draw_prim.points([p], color=color, size=size_token, context=context)

    def _draw_callback(self, context):
        region = context.region
        rv3d = context.region_data
        if rv3d is None:
            return
        # Guard against blinker (or any addon reload) freeing the
        # operator's RNA while this draw handler is still registered.
        # Touching self.obj's attrs raises ReferenceError once the
        # struct is gone.
        try:
            mw = self.obj.matrix_world
        except (ReferenceError, AttributeError):
            h = getattr(self, "_handle", None)
            if h is not None:
                try:
                    safe_handler_remove(h, bpy.types.SpaceView3D, "WINDOW")
                except (ValueError, RuntimeError, ReferenceError):
                    pass
            return

        theme = get_theme(context)

        gpu.state.blend_set("ALPHA")

        # Rebuild hotspot list each draw — view changes & axis edits
        # invalidate prior screen positions.
        self._hotspots = []
        for ri, r in enumerate(self.records):
            self._draw_face_record(region, rv3d, mw, r, ri, context=context, theme=theme)
        self._update_hover()
        # Draw hover highlight on top.
        if self._hover_idx is not None and self._hover_idx < len(self._hotspots):
            rp = self._hotspots[self._hover_idx].get("region_pt")
            if rp is not None:
                # White dot — hover highlight has no specific role; draw as active point.
                self._draw_dot(rp, radius=8.0,
                               color=(1.0, 1.0, 1.0, 1.0), context=context)

        if self._extrude_active:
            self._draw_extrude_arrows(region, rv3d, mw, context=context, theme=theme)

        if self._align_active:
            self._draw_align_highlight(region, rv3d, mw, context=context, theme=theme)

        gpu.state.blend_set("NONE")

        self._draw_hud(context)

    def _draw_align_highlight(self, region, rv3d, mw, *, context, theme):
        f = self._align_face
        if f is None or not f.is_valid:
            return
        screen_pts = []
        for vt in f.verts:
            p = view3d_utils.location_3d_to_region_2d(
                region, rv3d, mw @ vt.co)
            if p is None:
                return
            screen_pts.append(p)
        if len(screen_pts) < 3:
            return
        # Triangle fan from vert 0.
        tris = []
        for i in range(1, len(screen_pts) - 1):
            tris.extend([screen_pts[0], screen_pts[i], screen_pts[i + 1]])
        err = theme.color_for(Role.ERROR_LINE)
        draw_prim.tris(tris, color=(err[0], err[1], err[2], 0.35), context=context)

    def _draw_extrude_arrows(self, region, rv3d, mw, *, context, theme):
        """Single arrow during extrude: tail at the orig sheared edge
        midpoint, head along the average side direction. Length tracks
        the current drag distance (with a small floor so the direction
        is readable at zero)."""
        d = self._extrude_data
        if d is None:
            return
        center, avg_dir, head_world = self._extrude_arrow_world()
        if avg_dir is None:
            self._extrude_head_pt = None
            return

        # Tail at the sheared profile's centroid; head ON the resulting
        # profile (live centroid), but never shorter than MIN_PX on
        # screen so the handle stays grabbable at zero distance.
        MIN_PX = 40.0
        tail_world = center
        p_t = view3d_utils.location_3d_to_region_2d(
            region, rv3d, mw @ tail_world)
        p_h = view3d_utils.location_3d_to_region_2d(
            region, rv3d, mw @ head_world)
        if p_t is None or p_h is None:
            self._extrude_head_pt = None
            return
        tx, ty = p_t
        hx, hy = p_h
        dx, dy = hx - tx, hy - ty
        seg_len = math.hypot(dx, dy)
        if seg_len < MIN_PX:
            sd = self._screen_direction(context, center, avg_dir)
            if sd is None:
                self._extrude_head_pt = None
                self._draw_dot(p_t, radius=4.0,
                               color=theme.color_for(Role.ACTIVE_POINT), context=context)
                return
            hx, hy = tx + sd[0] * MIN_PX, ty + sd[1] * MIN_PX
            p_h = (hx, hy)
            dx, dy = hx - tx, hy - ty
            seg_len = MIN_PX
        self._extrude_head_pt = (hx, hy)
        draw_prim.edges_3d([p_t, p_h], role=Role.ACTIVE_LINE, context=context)
        ux, uy = dx / seg_len, dy / seg_len
        head_size = min(14.0, max(7.0, seg_len * 0.2))
        ca, sa = math.cos(math.radians(150)), math.sin(math.radians(150))
        leg1 = (
            hx + (ux * ca - uy * sa) * head_size,
            hy + (ux * sa + uy * ca) * head_size,
        )
        leg2 = (
            hx + (ux * ca + uy * sa) * head_size,
            hy + (-ux * sa + uy * ca) * head_size,
        )
        draw_prim.edges_3d([p_h, leg1, p_h, leg2], role=Role.ACTIVE_LINE, context=context)
        self._draw_dot(p_t, radius=4.0,
                       color=theme.color_for(Role.ACTIVE_POINT), context=context)
        # Grab handle at the head: hollow-ish dot normally, bright and
        # bigger while hovered / dragged (same look as the shear
        # hotspot hover).
        if self._extrude_grab or self._extrude_hover:
            self._draw_dot(p_h, radius=8.0, color=(1.0, 1.0, 1.0, 1.0),
                           context=context)
        else:
            self._draw_dot(p_h, radius=6.0,
                           color=theme.color_for(Role.ACTIVE_POINT), context=context)

    def _draw_face_record(self, region, rv3d, mw, r, rec_idx=0, *, context, theme):
        verts = r["active_verts"]
        origs = r["orig_active_cos"]
        projs = r["projections"]
        n = len(verts)
        if n < 2:
            return
        # Open chains draw n-1 segments; faces and rings close the loop.
        n_segs = n if r.get("closed", True) else n - 1
        # Closing segment of an open chain is the virtual edge: drawn
        # dim so it reads as construction, not mesh.
        virtual_i = n - 1 if r.get("virtual_close") else None

        max_p = max(projs) if projs else 0.0
        pivot_tol = max(max_p * 0.001, 1e-5)
        on_pivot = [p < pivot_tol for p in projs]

        def s2d(co):
            return view3d_utils.location_3d_to_region_2d(region, rv3d, mw @ co)

        # ----- Pre-shear ghost outline (subtle gray) ------------------
        ghost = []
        for oc in origs:
            p = s2d(oc)
            if p is None:
                ghost = []
                break
            ghost.append(p)
        if ghost:
            segs = []
            for i in range(n_segs):
                segs.extend([ghost[i], ghost[(i + 1) % n]])
            # Muted ghost — no clean role match; keep as explicit color.
            draw_prim.edges_3d(segs, color=(0.45, 0.45, 0.45, 0.55), context=context)

        # ----- Sheared face outline -----------------------------------
        curr = []
        for v in verts:
            if not v.is_valid:
                curr = []
                break
            p = s2d(v.co)
            if p is None:
                curr = []
                break
            curr.append(p)
        if curr and virtual_i is not None and n >= 3:
            # Virtual face fill: the open chain closed by its chord is
            # the profile the OBB / pivot sides are built on — show it.
            tris = []
            for i in range(1, n - 1):
                tris.extend([curr[0], curr[i], curr[i + 1]])
            draw_prim.tris(tris, color=theme.color_for(Role.GHOST_DEFAULT),
                           context=context)
        if curr:
            normal_segs = []
            pivot_segs = []
            virtual_segs = []
            for i in range(n_segs):
                j = (i + 1) % n
                a, b = curr[i], curr[j]
                if i == virtual_i:
                    virtual_segs.extend([a, b])
                elif on_pivot[i] and on_pivot[j]:
                    pivot_segs.extend([a, b])
                else:
                    normal_segs.extend([a, b])
            if normal_segs:
                draw_prim.edges_3d(normal_segs, role=Role.ACTIVE_LINE, context=context)
            if virtual_segs:
                draw_prim.edges_3d(virtual_segs, color=(0.6, 0.6, 0.6, 0.6), context=context)
            if pivot_segs:
                # Pivot edges (on-pivot boundary) — brighter amber via LOCKED_POINT role.
                draw_prim.edges_3d(pivot_segs, role=Role.LOCKED_LINE, context=context)

        # ----- Bbox-anchored direction widget -------------------------
        # Anchored to the *orig* face bounding box (the perpendicular /
        # reset-state selection bbox). The cross of orange dots follows
        # the current axis_dir + in-plane perpendicular so any change
        # to axis_dir (A-align, B-OBB, axis click, F toggle, D flip)
        # immediately reorients the widget on the next redraw.
        face_normal = r["normal"]
        axis_dir = r["axis_dir"]

        if face_normal.length > 1e-9 and origs:
            in_plane_perp = face_normal.cross(axis_dir)
            if in_plane_perp.length > 1e-9:
                in_plane_perp.normalize()
                centroid = r["centroid"]
                a_projs = [(oc - centroid).dot(axis_dir) for oc in origs]
                p_projs = [(oc - centroid).dot(in_plane_perp) for oc in origs]
                a_min, a_max = min(a_projs), max(a_projs)
                p_min, p_max = min(p_projs), max(p_projs)

                # Bbox center: midpoint of axis_dir and in_plane_perp
                # extents in face plane. The axis hint passes through
                # this point so the widget reads the same regardless
                # of which side of the bbox is the pivot.
                bbox_center = (centroid
                               + axis_dir * ((a_min + a_max) * 0.5)
                               + in_plane_perp * ((p_min + p_max) * 0.5))
                half_a = (a_max - a_min) * 0.5
                half_p = (p_max - p_min) * 0.5
                pivot_pt = bbox_center - axis_dir * half_a
                # Saw-entry tick spans the in-plane-perp extent at the
                # pivot end of the axis line.
                tick_a = pivot_pt - in_plane_perp * half_p
                tick_b = pivot_pt + in_plane_perp * half_p

                p_tick_a = s2d(tick_a)
                p_tick_b = s2d(tick_b)
                p_bbox_center = s2d(bbox_center)

                if p_tick_a is not None and p_tick_b is not None:
                    # Saw-entry tick at the pivot end (perp to axis_dir
                    # in the face plane, spanning the bbox extent).
                    draw_prim.edges_3d([p_tick_a, p_tick_b],
                                       role=Role.LOCKED_LINE, context=context)

                locked = theme.color_for(Role.LOCKED_POINT)
                # Four cross-end orange dots aligned to the current
                # axis_dir + in-plane perp. Clicking sets axis_dir
                # such that the saw-off pivot sits at the clicked end:
                # axis_choice points FROM clicked end TOWARD opposite.
                cross_ends = (
                    (axis_dir * half_a, -axis_dir),
                    (-axis_dir * half_a, axis_dir),
                    (in_plane_perp * half_p, -in_plane_perp),
                    (-in_plane_perp * half_p, in_plane_perp),
                )
                for offset_world, axis_choice in cross_ends:
                    end_world = bbox_center + offset_world
                    rp = view3d_utils.location_3d_to_region_2d(
                        region, rv3d, mw @ end_world)
                    if rp is None:
                        continue
                    self._hotspots.append({
                        "kind": "axis_pick",
                        "region_pt": (rp[0], rp[1]),
                        "axis": axis_choice,
                        "rec_idx": rec_idx,
                    })
                    self._draw_dot(rp, radius=5.0,
                                   color=(*locked[:3], 0.75), context=context)

                if p_bbox_center is not None:
                    # Blue center dot is a click-to-reset handle (= R).
                    self._hotspots.append({
                        "kind": "reset",
                        "region_pt": (p_bbox_center[0], p_bbox_center[1]),
                        "rec_idx": rec_idx,
                    })
                    closest = theme.color_for(Role.CLOSEST_POINT)
                    self._draw_dot(p_bbox_center, radius=5.0,
                                   color=(*closest[:3], 0.75), context=context)

    def _draw_hud(self, context):
        hud = getattr(self, "_hud", None)
        helpo = getattr(self, "_help", None)
        last_event = getattr(self, "_last_event", None)
        if helpo is not None:
            helpo.draw(context, last_event)
        if hud is None:
            return
        lines = [f"Mode: {self.mode}",
                 f"Angle: {self._effective_angle():.2f}°"]
        if self.input_str:
            lines.append(f"Typing: {self.input_str}")
        hud.set_header(*lines)
        hud.draw(context, last_event)
