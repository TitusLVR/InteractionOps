"""Smart shear operator. Detects selection and dispatches to the
appropriate algorithm.

For face mode, F toggles between the face's two principal in-plane
directions (PCA on face vert positions). This works for arbitrary
profiles — beveled squares, custom hand-built shapes, anything where
"X and Y" are the natural shear axes given the face normal as Z.


- face selection (any face selected) → face shear: each face vert
  slides along its non-face rail edge to where the rail meets the
  face plane rotated by the typed angle around the pivot side —
  `proj·sin(angle)/(rail·n')` where `proj` is the vert's offset from
  the pivot side along the axis and `n'` the rotated plane normal.
  The typed angle is the actual resulting tilt on any rail obliquity.
  Verts sharing a projection (one profile cross-section) slide as a
  rigid row along their averaged rail direction.

- edge selection (any edge selected, no faces) → edge shear: each
  selected edge's "active" vert slides perpendicular to the edge
  within the face plane by `edge_length·tan(angle)`. Edge tilts.

Both paths share modal UX: numeric angle input (0-9 . -), F (mode-
specific), D (flip sign), Enter confirm, Esc/RMB cancel. LMB clicks
only pick widget handles — never confirm.
"""
import bpy
import bmesh
import math
import gpu

from ..ui.draw import primitives as draw_prim, Role
from ..ui.draw import safe_handler_add, safe_handler_remove
from ..ui.draw.theme import get_theme
from ..ui.hud import (HUDOverlay, HelpOverlay, HUDSection, HUDItem,
                      HUDParam, ItemState,
                      handle_hud_toggle, handle_help_toggle, capture_event)
from ..utils.hinge_core import flush_angle
from bpy_extras import view3d_utils
from mathutils import Matrix, Vector
from mathutils.bvhtree import BVHTree


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


def _find_external_rail(vert, edge, face):
    """First link_edge of `vert` that is neither `edge` nor inside
    `face`. Returns (rail_edge, anchor_vert, rail_dir, rail_length)
    or None if no rail exists."""
    face_edge_set = set(face.edges)
    for e in vert.link_edges:
        if e is edge or e in face_edge_set:
            continue
        anchor = e.other_vert(vert)
        rail_vec = vert.co - anchor.co
        L = rail_vec.length
        if L < 1e-9:
            continue
        return e, anchor, rail_vec / L, L
    return None


def _find_face_adjacent_rail(vert, edge, face):
    """Fallback rail for isolated faces: the active vert's adjacent
    face edge (an edge of `face` that touches `vert` but isn't the
    selected `edge`). Sliding along this rail keeps the rail's line
    stable — only the rail's length changes, not its direction."""
    face_edge_set = set(face.edges)
    for e in vert.link_edges:
        if e is edge:
            continue
        if e not in face_edge_set:
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


def build_edge_record(edge, hist_vert):
    """Edge shear record using the saw-off model — the active endpoint
    slides along its non-face external edge ("rail") rather than
    perpendicular to the edge inside the face plane. This keeps the
    sheared vert anchored to its rail line, which is what the user
    sees on slanted-edge inputs (the rail is the geometric constraint;
    moving off it would break the surrounding mesh)."""
    if not edge.link_faces:
        return None, "edge has no adjacent face"
    face = edge.link_faces[0]
    v0, v1 = edge.verts
    if hist_vert is v0:
        active, fixed = v0, v1
    elif hist_vert is v1:
        active, fixed = v1, v0
    else:
        active, fixed = v1, v0

    edge_vec = active.co - fixed.co
    L = edge_vec.length
    if L < 1e-9:
        return None, "edge has zero length"

    rail = _find_external_rail(active, edge, face)
    if rail is None:
        rail = _find_face_adjacent_rail(active, edge, face)
    if rail is None:
        return None, "active vert has no rail edge"
    rail_edge, anchor, rail_dir, rail_L = rail

    return {
        "type": "edge",
        "edge": edge,
        "face": face,
        "active": active,
        "fixed": fixed,
        "orig_active_co": active.co.copy(),
        "orig_fixed_co": fixed.co.copy(),
        "edge_length": L,
        "rail_edge": rail_edge,
        "rail_anchor": anchor,
        "rail_dir": rail_dir.copy(),
        "rail_length": rail_L,
    }, None


def flip_edge_record_active(rec):
    """Swap active and fixed verts and re-derive the rail for the new
    active. Both endpoint hotspots produce the same visual slide
    direction because the rail is sourced from the active vert's own
    incident edges, not from `normal × edge_dir`."""
    rec["active"], rec["fixed"] = rec["fixed"], rec["active"]
    rec["orig_active_co"], rec["orig_fixed_co"] = (
        rec["orig_fixed_co"], rec["orig_active_co"]
    )
    edge_vec = rec["orig_active_co"] - rec["orig_fixed_co"]
    L = edge_vec.length
    if L < 1e-9:
        return
    rail = _find_external_rail(rec["active"], rec["edge"], rec["face"])
    if rail is None:
        rail = _find_face_adjacent_rail(rec["active"], rec["edge"], rec["face"])
    if rail is None:
        return
    rail_edge, anchor, rail_dir, rail_L = rail
    rec["rail_edge"] = rail_edge
    rec["rail_anchor"] = anchor
    rec["rail_dir"] = rail_dir.copy()
    rec["rail_length"] = rail_L
    rec["edge_length"] = L


def build_face_record(face, axis_dir):
    """Face shear record. ALL face verts slide along their non-face
    rail edges by `proj·sin(angle)`. `axis_dir` is a unit Vector in
    the face plane along which projections are measured.

    The record caches the face's principal axes (PCA) so F can toggle
    between them without recomputing."""
    if axis_dir is None or axis_dir.length < 1e-9:
        return None, "no axis direction"

    centroid = face.verts[0].co * 0.0
    for v in face.verts:
        centroid = centroid + v.co
    centroid = centroid / len(face.verts)

    # Project axis_dir onto face plane (defensive — caller should pass
    # an in-plane vector but enforce here).
    normal = _face_normal_safe(face)
    if normal.length > 1e-9:
        axis_dir = (axis_dir - axis_dir.dot(normal) * normal)
        if axis_dir.length < 1e-9:
            return None, "axis direction is parallel to face normal"
        axis_dir = axis_dir.normalized()
    else:
        axis_dir = axis_dir.normalized()

    face_edge_set = set(face.edges)
    active_verts = list(face.verts)
    rails = []
    centroid_projs = []
    for av in active_verts:
        rail_edge = None
        for e in av.link_edges:
            if e in face_edge_set:
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

    pa, pb = face_principal_axes(face)
    return {
        "type": "face",
        "face": face,
        "normal": (normal.normalized() if normal.length > 1e-9
                   else None),
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


def build_face_record_from_edge(face, axis_edge):
    """Legacy helper: derive axis_dir from an edge with the original
    canonicalization rule (cross(face_normal, axis_dir) points toward
    the face centroid). Preserved so existing tests and callers keyed
    to the prior axis_edge convention continue to work."""
    if axis_edge not in face.edges:
        return None, "axis edge not in face"
    av0, av1 = axis_edge.verts
    axis_vec = av1.co - av0.co
    if axis_vec.length < 1e-9:
        return None, "axis edge has zero length"
    axis_dir = axis_vec / axis_vec.length
    normal = _face_normal_safe(face)
    if normal.length > 1e-9:
        axis_mid = (av0.co + av1.co) * 0.5
        centroid = av0.co * 0.0
        for v in face.verts:
            centroid = centroid + v.co
        centroid = centroid / len(face.verts)
        if normal.cross(axis_dir).dot(centroid - axis_mid) < 0:
            axis_dir = -axis_dir
    return build_face_record(face, axis_dir)


def face_principal_axes(face):
    """Two unit axes in the face plane aligned to the face's own
    minimum oriented bounding box: axis_a is the OBB's longer side,
    axis_b = normal × axis_a. This keeps the widget/pivot hugging the
    face for faces rotated away from the world axes ("global bounds"
    complaint) while still landing on the sides — not the diagonal —
    for beveled squares (the OBB side is edge-colinear, unlike PCA).
    For world-axis-aligned faces the result matches the old world-Z
    projection exactly.

    Fallback when the OBB is degenerate: world +Z projected onto the
    face plane, then +Y, then +X."""
    normal = _face_normal_safe(face)
    if normal.length < 1e-9:
        return None, None

    axis_a = _min_obb_axis_for_face(face)
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
    """Returns the in-plane unit Vector along the longer side of the
    face's minimum oriented bounding box. Uses the rotating-calipers
    short-cut that the optimal OBB has one side colinear with an edge
    of the convex hull — for typical shear targets (convex faces) the
    face's own edges are the candidate axes. None if degenerate.
    """
    normal = _face_normal_safe(face)
    if normal.length < 1e-9 or len(face.verts) < 3:
        return None
    # Orthonormal basis (u, v) in the face plane.
    helper = Vector((0.0, 1.0, 0.0))
    if abs(normal.dot(helper)) > 0.99:
        helper = Vector((1.0, 0.0, 0.0))
    u = (helper - helper.dot(normal) * normal)
    if u.length < 1e-9:
        return None
    u = u.normalized()
    v = normal.cross(u).normalized()
    # 2D coords relative to centroid.
    centroid = face.verts[0].co * 0.0
    for vt in face.verts:
        centroid = centroid + vt.co
    centroid = centroid / len(face.verts)
    pts = []
    for vt in face.verts:
        d = vt.co - centroid
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


def compute_reset_angle_edge(rec):
    """Angle θ that makes the sheared edge perpendicular to the
    surrounding-mesh "rest" direction.

    Rest reference depends on whether the active vert has an external
    rail (= the surrounding mesh's incident edge):
    - External rail present: rest = rail direction. The new edge will
      be perpendicular to that external edge (cube top edge → vertical
      down edge: the result is the original orientation, θ ≈ 0 for
      orig-perpendicular inputs).
    - Isolated-face fallback: rest = the active vert's adjacent face
      edge direction (the face edge from active that isn't the
      selected edge). For a slanted edge this snaps the result so the
      edge becomes perpendicular to its neighbouring face edge.

    Solves `(orig_edge + rail_dir·L·tan(θ)) · rest_dir = 0`."""
    active = rec["active"]
    fixed = rec["fixed"]
    edge = rec["edge"]
    face = rec["face"]
    rail_dir = rec.get("rail_dir")
    if rail_dir is None or rail_dir.length < 1e-9:
        return 0.0

    if rec.get("rail_edge") is not None:
        rest_dir = rail_dir
    else:
        rest_dir = None
        face_edge_set = set(face.edges)
        for e in active.link_edges:
            if e is edge:
                continue
            if e not in face_edge_set:
                continue
            other = e.other_vert(active)
            d = active.co - other.co
            if d.length < 1e-9:
                continue
            rest_dir = d.normalized()
            break
        if rest_dir is None:
            return 0.0

    edge_vec = rec["orig_active_co"] - fixed.co
    L = edge_vec.length
    if L < 1e-9:
        return 0.0
    rd_dot_rest = rail_dir.dot(rest_dir)
    if abs(rd_dot_rest) < 1e-9:
        return 0.0
    return math.degrees(math.atan(
        -edge_vec.dot(rest_dir) / (L * rd_dot_rest)))


def compute_reset_angle(records):
    """Average reset angle across records of the same mode. Records of
    different modes can't be averaged meaningfully, so the operator
    only ever passes records of one mode here."""
    if not records:
        return 0.0
    angles = []
    for r in records:
        if r["type"] == "face":
            angles.append(compute_reset_angle_face(r))
        elif r["type"] == "edge":
            angles.append(compute_reset_angle_edge(r))
    if not angles:
        return 0.0
    return sum(angles) / len(angles)


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
        if r["type"] == "edge":
            if r["active"].is_valid and r["fixed"].is_valid:
                # Saw-off slide: active moves along its rail by
                # edge_length × tan(angle). Rail constraint keeps the
                # active vert on the surrounding mesh line.
                shift = r["rail_dir"] * r["edge_length"] * t
                r["active"].co = r["orig_active_co"] + shift
        elif r["type"] == "face":
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
        if r["type"] == "edge":
            if r["active"].is_valid:
                r["active"].co = r["orig_active_co"]
        elif r["type"] == "face":
            for av, oc in zip(r["active_verts"], r["orig_active_cos"]):
                if av.is_valid:
                    av.co = oc


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
        selected_edges = [
            e for e in self.bm.edges
            if e.select and len(e.link_faces) > 0
        ]

        if not selected_faces and not selected_edges:
            self.report(
                {"WARNING"},
                "Select at least one face or edge with an adjacent face",
            )
            return {"CANCELLED"}

        # Last edge in select_history seeds axis_edge / hist_vert.
        hist_edge = None
        hist_vert = None
        try:
            for item in self.bm.select_history:
                if isinstance(item, bmesh.types.BMEdge):
                    hist_edge = item
                elif isinstance(item, bmesh.types.BMVert):
                    hist_vert = item
        except (TypeError, RuntimeError):
            pass

        self.records = []
        skip_reasons = []

        if selected_faces:
            self.mode = "face"
            for face in selected_faces:
                if len(face.edges) < 3:
                    skip_reasons.append("face has fewer than 3 edges")
                    continue
                # Default axis is the first principal axis. If the user
                # has an edge in select_history that's part of the face,
                # honor it as the seed direction so they can steer the
                # initial axis explicitly.
                if hist_edge is not None and hist_edge in face.edges:
                    ev0, ev1 = hist_edge.verts
                    seed = ev1.co - ev0.co
                    if seed.length > 1e-9:
                        rec, reason = build_face_record(face, seed)
                    else:
                        pa, _ = face_principal_axes(face)
                        rec, reason = build_face_record(face, pa) if pa else (None, "degenerate face")
                else:
                    pa, _ = face_principal_axes(face)
                    if pa is None:
                        skip_reasons.append("face is degenerate (no principal axes)")
                        continue
                    rec, reason = build_face_record(face, pa)
                if rec is not None:
                    self.records.append(rec)
                else:
                    skip_reasons.append(reason)
        else:
            self.mode = "edge"
            for edge in selected_edges:
                rec, reason = build_edge_record(edge, hist_vert)
                if rec is not None:
                    self.records.append(rec)
                else:
                    skip_reasons.append(reason)

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
        # Last angle a shear actually used — seeds Q hinge after an
        # extrude confirm has reset angle_deg on the new cap.
        self._last_shear_angle = 0.0
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

        # Hinge sub-modal state. Q enters; selected faces rotate around
        # the active edge from select_history. Preview is a draw-only
        # ghost of the spin result — the mesh itself doesn't move until
        # bmesh.ops.spin runs once at confirm. Mutating verts during
        # preview would drag/shear the unselected neighbor faces that
        # share them, which the baked spin never does (it extrudes
        # walls instead) — the preview must not lie.
        self._hinge_active = False
        self._hinge_data = None
        self._hinge_angle_deg = 0.0

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
        face_label = ("Cycle axis edge" if self.mode == "face"
                      else "Flip active vert")
        items = [
            HUDItem("Type angle",         "0-9 . -",   ItemState.ON, default_state=ItemState.OFF, always_show=True),
            HUDItem("Angle ±5°",          "Alt+Wheel", ItemState.ON, default_state=ItemState.OFF, always_show=True),
            HUDItem("Delete digit",       "Backspace", ItemState.ON, default_state=ItemState.OFF, always_show=True),
            HUDItem(face_label,           "F",         ItemState.ON, default_state=ItemState.OFF, always_show=True),
            HUDItem("Flip direction",     "D",         ItemState.ON, default_state=ItemState.OFF, always_show=True),
            HUDItem("Perp to rails",      "R",         ItemState.ON, default_state=ItemState.OFF, always_show=True),
            HUDItem("Extrude perp",       "E",         ItemState.ON, default_state=ItemState.OFF, always_show=True),
            HUDItem("Hinge around active edge / pivot side", "Q", ItemState.ON, default_state=ItemState.OFF, always_show=True),
        ]
        if self.mode == "face":
            items.append(HUDItem("Align axis to face", "A",   ItemState.ON, default_state=ItemState.OFF, always_show=True))
            items.append(HUDItem("Axis to min OBB",    "B",   ItemState.ON, default_state=ItemState.OFF, always_show=True))
        items.extend([
            HUDItem("Confirm", "Enter",   ItemState.ON, default_state=ItemState.OFF, always_show=True),
            HUDItem("Cancel",  "Esc / RMB", ItemState.ON, default_state=ItemState.OFF, always_show=True),
            HUDItem("Help / Toggle HUD", "H", ItemState.ON, default_state=ItemState.OFF, always_show=True),
        ])
        self._help.add_section(HUDSection("Shear", items))
        hinge_items = [
            HUDItem("Type angle",     "0-9 . -",    ItemState.ON, default_state=ItemState.OFF, always_show=True),
            HUDItem("Angle ±5°",      "Alt+Wheel",  ItemState.ON, default_state=ItemState.OFF, always_show=True),
            HUDItem("Segments",       "Ctrl+Wheel", ItemState.ON, default_state=ItemState.OFF, always_show=True),
            HUDItem("Flip direction", "D",          ItemState.ON, default_state=ItemState.OFF, always_show=True),
            HUDItem("Flush to face",  "A",          ItemState.ON, default_state=ItemState.OFF, always_show=True),
            HUDItem("Confirm",        "Enter",      ItemState.ON, default_state=ItemState.OFF, always_show=True),
            HUDItem("Cancel hinge",   "Q / Esc / RMB", ItemState.ON, default_state=ItemState.OFF, always_show=True),
        ]
        self._help.add_section(HUDSection("Hinge (Q)", hinge_items))
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
        self._last_shear_angle = props.shear_last_angle
        self._saved_hinge_angle = props.shear_hinge_last_angle
        self._saved_hinge_steps = max(1, props.shear_hinge_last_steps)
        self._saved_extrude_distance = props.shear_extrude_last_distance

    def _save_shear_angle(self, context):
        context.scene.IOPS.shear_last_angle = self.angle_deg

    def _save_hinge_params(self, context, angle_deg, steps):
        props = context.scene.IOPS
        props.shear_hinge_last_angle = angle_deg
        props.shear_hinge_last_steps = steps

    def _save_extrude_distance(self, context, distance):
        context.scene.IOPS.shear_extrude_last_distance = distance

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
        rec = self.records[0]
        t = _angle_to_t(self.angle_deg)

        if rec["type"] == "face":
            # Multi-face: every face record extrudes together as ONE
            # region (shared edges between selected faces get no wall,
            # exactly like the native extrude), while side direction
            # and saw-off delay are still derived per record. A vert
            # shared by several records averages their sides and takes
            # the smallest delay.
            face_recs = [r for r in self.records
                         if r["type"] == "face" and r["face"].is_valid]
            if len(face_recs) != len(self.records):
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
                # Use the CURRENT (sheared) face normal as the mirror
                # plane. bm.normal_update() is assumed current here;
                # the modal path always calls it after each shear edit.
                face_normal = _face_normal_safe(face)
                if face_normal.length < 1e-9:
                    return False
                face_normals[face] = face_normal
                rec_n = r.get("normal")
                n_prime = (rec_n * cos_t - r["axis_dir"] * sin_t
                           if rec_n is not None else None)

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

            orig_faces = [r["face"] for r in face_recs]
            res = bmesh.ops.extrude_face_region(self.bm, geom=orig_faces)
            new_geom = res.get("geom", [])
            new_verts = [g for g in new_geom
                         if isinstance(g, bmesh.types.BMVert)]
            new_faces = [g for g in new_geom
                         if isinstance(g, bmesh.types.BMFace)]
            # Caps: new faces whose verts are all new (side walls
            # always touch an old vert). Pair them with the originals
            # by centroid so record order is preserved.
            new_vert_set = set(new_verts)
            caps = [f for f in new_faces
                    if all(v in new_vert_set for v in f.verts)]
            if len(caps) != len(orig_faces) or not new_verts:
                return False
            target_faces = []
            for of in orig_faces:
                c = of.calc_center_median()
                best = min(caps,
                           key=lambda f: (f.calc_center_median() - c).length)
                target_faces.append(best)
                caps.remove(best)

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
                "kind": "face",
                "verts": new_verts,
                "anchors": anchors,
                "sides": sides,
                "delays": delays,
                "avg_dir": avg_dir.copy(),
                "center": center.copy(),
                "target": target_faces[0],
                "targets": target_faces,
                "orig_face": orig_faces[0],
                "orig_faces": orig_faces,
            }
        else:
            edge = rec["edge"]
            face = rec["face"]
            active = rec["active"]
            fixed = rec["fixed"]
            face_edge_set = set(face.edges)

            def adj_rail_dir(vert):
                for e in vert.link_edges:
                    if e is edge or e not in face_edge_set:
                        continue
                    other = e.other_vert(vert)
                    d = other.co - vert.co
                    if d.length < 1e-9:
                        continue
                    return d.normalized()
                return None

            active_rail = adj_rail_dir(active)
            fixed_rail = adj_rail_dir(fixed)
            if active_rail is None or fixed_rail is None:
                return False

            sheared_edge_vec = active.co - fixed.co
            if sheared_edge_vec.length < 1e-9:
                return False
            sheared_dir = sheared_edge_vec.normalized()

            def mirror(vec, n):
                return 2.0 * vec.dot(n) * n - vec

            # At each end, mirror the old rail across the sheared edge
            # direction. The sheared edge bisects the angle between
            # old rail (going into existing geometry) and new side
            # (going into the extruded segment). Sign convention: the
            # sheared edge direction at a vert points TOWARD the other
            # end of the orig edge.
            active_side_dir = mirror(active_rail, -sheared_dir)
            fixed_side_dir = mirror(fixed_rail, sheared_dir)

            # Offset between side magnitudes = saw-off slide amount.
            # Uses the pre-shear edge length captured in the record.
            offset = abs(rec["edge_length"] * t)

            res = bmesh.ops.extrude_edge_only(self.bm, edges=[edge])
            new_geom = res.get("geom", [])
            new_verts = [g for g in new_geom
                         if isinstance(g, bmesh.types.BMVert)]
            new_edges = [g for g in new_geom
                         if isinstance(g, bmesh.types.BMEdge)]
            target_edge = next(
                (e for e in new_edges
                 if e is not edge and len(e.verts) == 2
                 and all(v in new_verts for v in e.verts)),
                None,
            )
            if target_edge is None or not new_verts:
                return False

            new_active = None
            new_fixed = None
            for nv in new_verts:
                if (nv.co - active.co).length < 1e-6:
                    new_active = nv
                elif (nv.co - fixed.co).length < 1e-6:
                    new_fixed = nv
            if new_active is None or new_fixed is None:
                return False

            self._extrude_data = {
                "kind": "edge",
                "new_active": new_active,
                "new_fixed": new_fixed,
                "active_anchor": active.co.copy(),
                "fixed_anchor": fixed.co.copy(),
                "active_side_dir": active_side_dir.copy(),
                "fixed_side_dir": fixed_side_dir.copy(),
                "offset": offset,
                "target": target_edge,
            }
        self._extrude_active = True
        self._extrude_distance = 0.0
        self._extrude_start_x = event.mouse_region_x
        self._extrude_start_y = event.mouse_region_y
        self.bm.normal_update()
        bmesh.update_edit_mesh(self.obj.data)
        return True

    def _extrude_modal(self, context, event):
        if event.type == "MOUSEMOVE":
            # Project mouse delta onto the on-screen direction of the
            # extrude arrow so dragging follows the arrow visually
            # rather than pure screen +X. Recomputed each frame so it
            # tracks camera orbits during the drag.
            d = self._extrude_data
            if d.get("kind") == "edge":
                world_center = (d["active_anchor"] + d["fixed_anchor"]) * 0.5
                world_dir_3d = d["active_side_dir"] + d["fixed_side_dir"]
            else:
                world_center = d["center"]
                world_dir_3d = d["avg_dir"]
            screen_dir = self._screen_direction(
                context, world_center, world_dir_3d)
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
            sens = 0.01
            if event.shift:
                sens *= 0.1
            t = max(0.0, projected * sens)
            self._extrude_distance = t
            if d["kind"] == "edge":
                # Active end gets the full mouse t; fixed end stays at
                # zero until t exceeds the saw-off offset, then grows.
                # Net: the orig sheared edge bisects the corner between
                # old rails and new sides at every distance.
                offset = d["offset"]
                a_t = t
                f_t = max(0.0, t - offset)
                if d["new_active"].is_valid:
                    d["new_active"].co = (
                        d["active_anchor"]
                        + d["active_side_dir"] * a_t
                    )
                if d["new_fixed"].is_valid:
                    d["new_fixed"].co = (
                        d["fixed_anchor"]
                        + d["fixed_side_dir"] * f_t
                    )
            else:
                # Face mode saw-off mirror: each new face vert gets its
                # own side direction (rail mirrored across the sheared
                # face plane) and its own delay (proj-based). Vert with
                # max projection moves immediately; pivot-edge verts
                # wait until t exceeds their delay.
                for v, anchor, side, delay in zip(
                        d["verts"], d["anchors"],
                        d["sides"], d["delays"]):
                    if v.is_valid:
                        v.co = anchor + side * max(0.0, t - delay)
            self.bm.normal_update()
            bmesh.update_edit_mesh(self.obj.data)
            context.workspace.status_text_set(self._status_text())
            if context.area:
                context.area.tag_redraw()
            return {"RUNNING_MODAL"}
        if event.value == "PRESS":
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
        target = d["target"]
        kind = d["kind"]
        # Remember the shear angle that shaped this segment's miter —
        # a following Q hinge seeds from it (the shear itself resets
        # to 0 on the new cap).
        if abs(self.angle_deg) > 1e-6:
            self._last_shear_angle = self.angle_deg
        # Now that the user committed, the original face becomes an
        # interior face and must be removed. Side walls already share
        # its verts and edges so FACES_ONLY leaves the surrounding
        # topology intact. Cancel doesn't reach this path so the
        # face survives a cancel.
        # "FACES" (not FACES_ONLY): edges shared between two extruded
        # faces got no side wall, so they'd be left as wire otherwise.
        orig_faces = [f for f in d.get("orig_faces", [d.get("orig_face")])
                      if f is not None and f.is_valid]
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
        targets = [f for f in d.get("targets", [target]) if f.is_valid]
        if kind == "face" and targets:
            # Full deselect (not just faces) — stray selected edges or
            # verts left by earlier chained ops would otherwise keep
            # accumulating in the selection.
            for v in self.bm.verts:
                v.select = False
            for e in self.bm.edges:
                e.select = False
            for f in self.bm.faces:
                f.select = False
            new_records = []
            for tf in targets:
                tf.select_set(True)
                pa, _ = face_principal_axes(tf)
                if pa is None:
                    continue
                new_rec, _ = build_face_record(tf, pa)
                if new_rec is not None:
                    new_records.append(new_rec)
            self.bm.select_flush_mode()
            if new_records:
                self.records = new_records
                self.mode = "face"
        elif kind == "edge" and target.is_valid:
            target.select_set(True)
            new_rec, _ = build_edge_record(target, None)
            if new_rec is not None:
                self.records = [new_rec]
                self.mode = "edge"
        self._extrude_active = False
        self._extrude_data = None
        self.angle_deg = 0.0
        self.input_str = ""
        self._hotspots = []
        self._hover_idx = None

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
        if d["kind"] == "edge":
            candidates = [d.get("new_active"), d.get("new_fixed")]
        else:
            candidates = list(d.get("verts", []))
        new_verts = [v for v in candidates if v is not None and v.is_valid]
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

    def _hinge_line_from_shear(self):
        """Hinge line from the active shear record's pivot side — the
        amber saw-entry line the widget draws (perp to axis_dir through
        pivot_point). Returns (center, axis, edge_or_None, (a, b)) or
        None. `edge` is the real pivot BMEdge when the pivot side is a
        boundary edge (enables the flap case at confirm); (a, b) are
        world-space endpoints for drawing the axis."""
        if self.mode != "face" or not self.records:
            return None
        rec = self.records[0]
        try:
            active = self.bm.select_history.active
        except (TypeError, RuntimeError):
            active = None
        if isinstance(active, bmesh.types.BMFace):
            for r in self.records:
                if r["face"] is active:
                    rec = r
                    break
        face = rec["face"]
        if not face.is_valid:
            return None

        # Pivot verts have projection ~0 (same tolerance the widget
        # uses to highlight the pivot boundary).
        projs = rec["projections"]
        max_p = max(projs) if projs else 0.0
        pivot_tol = max(max_p * 0.001, 1e-5)
        proj_of = {v: p for v, p in zip(rec["active_verts"], projs)}
        for e in face.edges:
            ev0, ev1 = e.verts
            if (proj_of.get(ev0, 1.0) < pivot_tol
                    and proj_of.get(ev1, 1.0) < pivot_tol):
                axis = ev1.co - ev0.co
                if axis.length < 1e-9:
                    continue
                axis = axis.normalized()
                a, b = ev0.co.copy(), ev1.co.copy()
                return (a + b) * 0.5, axis, e, (a, b)

        # No boundary edge on the pivot side (pivot is a single corner
        # of an n-gon): abstract line through pivot_point, in-plane
        # perpendicular to axis_dir, spanning the face extent.
        normal = _face_normal_safe(face)
        axis = normal.cross(rec["axis_dir"])
        if axis.length < 1e-9:
            return None
        axis = axis.normalized()
        center = rec["pivot_point"].copy()
        ts = [(oc - center).dot(axis) for oc in rec["orig_active_cos"]]
        t0, t1 = (min(ts), max(ts)) if ts else (0.0, 0.0)
        return center, axis, None, (center + axis * t0, center + axis * t1)

    def _enter_hinge(self, context, event):
        """Q: begin the hinge sub-modal. Selected faces rotate around
        the active edge (select_history) when one exists, otherwise
        around the active shear record's pivot side — the same amber
        line the shear widget shows. Q is a mode switch, not a confirm:
        any in-progress shear preview (including the auto-45° kick from
        an axis-pick click) is dropped so the hinge rotates the
        unsheared pose — but its angle carries over as the initial
        hinge angle so the ghost picks up where the shear left off."""
        sel_faces = [f for f in self.bm.faces if f.select]
        if not sel_faces:
            self.report({"INFO"}, "hinge: needs selected faces")
            return False
        # Axis edge = the selection's edge nearest to the mouse (same
        # pick as cursor_bisect), re-picked live on mouse move inside
        # the sub-modal. Selection-history edge is the fallback when
        # nothing projects (cursor off-screen).
        self._mouse_xy = (event.mouse_region_x, event.mouse_region_y)
        hist_edge = self._hinge_pick_edge(context, sel_faces)
        if hist_edge is None:
            try:
                for item in self.bm.select_history:
                    if isinstance(item, bmesh.types.BMEdge):
                        hist_edge = item
            except (TypeError, RuntimeError):
                pass
        # Restore BEFORE deriving axis/center — the shear preview may
        # have moved the very verts the hinge line passes through.
        # The shear angle (typed included) seeds the hinge angle; when
        # the shear is at 0 (always the case right after an extrude
        # confirm), fall back to the last angle a shear actually used.
        seed_angle = self._effective_angle()
        if abs(seed_angle) < 1e-6:
            seed_angle = getattr(self, "_last_shear_angle", 0.0)
        else:
            self._last_shear_angle = seed_angle
        if abs(seed_angle) < 1e-6:
            seed_angle = getattr(self, "_saved_hinge_angle", 0.0)
        if self.records:
            restore_records(self.records)
            self.bm.normal_update()
            bmesh.update_edit_mesh(self.obj.data)
        self.angle_deg = 0.0
        if hist_edge is not None and hist_edge.is_valid:
            v0, v1 = hist_edge.verts
            axis = v1.co - v0.co
            if axis.length < 1e-9:
                self.report({"INFO"}, "hinge: active edge has zero length")
                return False
            axis = axis.normalized()
            center = (v0.co + v1.co) * 0.5
            hinge_edge = hist_edge
            axis_pts = (v0.co.copy(), v1.co.copy())
        else:
            line = self._hinge_line_from_shear()
            if line is None:
                self.report({"INFO"},
                            "hinge: needs an active edge or a shear pivot side")
                return False
            center, axis, hinge_edge, axis_pts = line

        vert_set = set()
        for f in sel_faces:
            vert_set.update(f.verts)
        verts = list(vert_set)
        orig_cos = [v.co.copy() for v in verts]

        # Average selection normal at entry — the flush reference (A).
        n_sum = Vector((0.0, 0.0, 0.0))
        for f in sel_faces:
            n_sum += _face_normal_safe(f)
        orig_normal = (n_sum.normalized() if n_sum.length > 1e-9
                       else _face_normal_safe(sel_faces[0]))

        axis = self._hinge_orient_axis(axis, center, orig_cos)

        self._hinge_data = {
            "faces": sel_faces,
            "verts": verts,
            "orig_cos": orig_cos,
            "orig_co_map": {v: c for v, c in zip(verts, orig_cos)},
            "center": center.copy(),
            "axis": axis.copy(),
            "edge": hinge_edge,       # None when axis came from the pivot line
            "axis_pts": axis_pts,
            "orig_normal": orig_normal.copy(),
            "steps": getattr(self, "_saved_hinge_steps", 6),
        }
        self._hinge_active = True
        self._hinge_angle_deg = seed_angle if abs(seed_angle) > 1e-6 else 0.0
        self.input_str = ""
        self._hotspots = []
        self._hover_idx = None
        self._align_active = False  # latched align highlight must not draw over hinge preview
        self._align_face = None
        return True

    def _hinge_orient_axis(self, axis, center, orig_cos):
        """Match the hinge's positive direction to the shear's: a
        positive angle must swing the flap the way a positive shear
        slides it — along the record's rails. The tangential velocity
        of the selection centroid under +rotation is axis × (centroid
        - center); if it opposes the mean rail direction, flip the
        axis. Without this the sign of the inherited angle (and of
        typed input) depends on the arbitrary vert order of the
        active edge."""
        rec0 = self.records[0] if self.records else None
        if rec0 is not None and rec0.get("type") == "face":
            r_mean = Vector((0.0, 0.0, 0.0))
            for rl in rec0["rails"]:
                r_mean += rl["dir"]
            sel_centroid = Vector((0.0, 0.0, 0.0))
            for co in orig_cos:
                sel_centroid += co
            sel_centroid /= max(1, len(orig_cos))
            tangent = axis.cross(sel_centroid - center)
            if (r_mean.length > 1e-9 and tangent.length > 1e-9
                    and tangent.dot(r_mean) < 0):
                return -axis
        return axis

    def _hinge_pick_edge(self, context, faces):
        """Edge of ``faces`` nearest to the mouse in screen space, or
        None when nothing projects."""
        from ..utils.picking import closest_edge_screen
        edges = []
        seen = set()
        for f in faces:
            for e in f.edges:
                if e not in seen:
                    seen.add(e)
                    edges.append(e)
        if not edges or context.region_data is None:
            return None
        idx, _ = closest_edge_screen(context, edges, self.obj.matrix_world,
                                     self._mouse_xy)
        return None if idx is None else edges[idx]

    def _hinge_repick(self, context):
        """MOUSEMOVE inside the hinge: swap the axis to the edge now
        under the mouse. Angle, steps and typed input are kept — only
        the hinge line moves."""
        d = self._hinge_data
        if d is None:
            return False
        edge = self._hinge_pick_edge(context, d["faces"])
        if edge is None or edge is d["edge"] or not edge.is_valid:
            return False
        v0, v1 = edge.verts
        axis = v1.co - v0.co
        if axis.length < 1e-9:
            return False
        axis = axis.normalized()
        center = (v0.co + v1.co) * 0.5
        d["axis"] = self._hinge_orient_axis(axis, center, d["orig_cos"]).copy()
        d["center"] = center.copy()
        d["edge"] = edge
        d["axis_pts"] = (v0.co.copy(), v1.co.copy())
        return True

    def _hinge_effective_angle(self):
        if self.input_str and self.input_str not in ("-", ".", "-."):
            try:
                return float(self.input_str)
            except ValueError:
                return self._hinge_angle_deg
        return self._hinge_angle_deg

    def _hinge_modal(self, context, event):
        # Navigation passes through (Q sub-modal owns Ctrl+wheel for
        # segments and Alt+wheel for the angle).
        if (event.type == "MIDDLEMOUSE" or event.type.startswith("NDOF")
                or (event.type in {"WHEELUPMOUSE", "WHEELDOWNMOUSE"}
                    and not event.ctrl and not event.alt)):
            return {"PASS_THROUGH"}

        if event.type in {"WHEELUPMOUSE", "WHEELDOWNMOUSE"} and event.alt:
            delta = 5.0 if event.type == "WHEELUPMOUSE" else -5.0
            self._hinge_angle_deg = self._hinge_effective_angle() + delta
            self.input_str = ""
            context.workspace.status_text_set(self._status_text())
            if context.area:
                context.area.tag_redraw()
            return {"RUNNING_MODAL"}

        if event.type in {"WHEELUPMOUSE", "WHEELDOWNMOUSE"} and event.ctrl:
            d = self._hinge_data
            delta = 1 if event.type == "WHEELUPMOUSE" else -1
            d["steps"] = max(1, min(64, d["steps"] + delta))
            context.workspace.status_text_set(self._status_text())
            if context.area:
                context.area.tag_redraw()
            return {"RUNNING_MODAL"}

        if event.type == "MOUSEMOVE":
            self._mouse_xy = (event.mouse_region_x, event.mouse_region_y)
            if self._hinge_repick(context) and context.area:
                context.area.tag_redraw()
            return {"RUNNING_MODAL"}

        if event.value == "PRESS":
            if event.type in DIGIT_TYPES:
                self.input_str += DIGIT_TYPES[event.type]
            elif event.type in {"PERIOD", "NUMPAD_PERIOD"}:
                if "." not in self.input_str:
                    self.input_str += "."
            elif event.type in {"MINUS", "NUMPAD_MINUS"}:
                if self.input_str.startswith("-"):
                    self.input_str = self.input_str[1:]
                else:
                    self.input_str = "-" + self.input_str
            elif event.type == "BACK_SPACE":
                self.input_str = self.input_str[:-1]
            elif event.type == "D":
                if self.input_str:
                    if self.input_str.startswith("-"):
                        self.input_str = self.input_str[1:]
                    else:
                        self.input_str = "-" + self.input_str
                else:
                    self._hinge_angle_deg = -self._hinge_angle_deg
            elif event.type == "A":
                self._hinge_flush_pick(context, event)   # Task 4
            elif event.type == "Q":
                # Q toggles the sub-modal: second press drops back to
                # shear. Preview is draw-only, nothing to restore.
                self._cancel_hinge(context)
            elif event.type in {"RET", "NUMPAD_ENTER", "SPACE"}:
                return self._confirm_hinge(context)      # Task 3
            elif event.type in {"RIGHTMOUSE", "ESC"}:
                self._cancel_hinge(context)
            context.workspace.status_text_set(self._status_text())
            if context.area:
                context.area.tag_redraw()
            return {"RUNNING_MODAL"}
        return {"RUNNING_MODAL"}

    def _cancel_hinge(self, context):
        # Preview is draw-only (ghost) — no geometry to restore.
        self._hinge_active = False
        self._hinge_data = None
        self._hinge_angle_deg = 0.0
        self.input_str = ""
        self._hotspots = []
        self._hover_idx = None
        return {"RUNNING_MODAL"}

    def _confirm_hinge(self, context):
        """Enter/Space: bake the hinge. The preview is draw-only, so
        the mesh is still in its original pose — run bmesh.ops.spin
        with the chosen steps (real segment geometry), merge doubles
        at the hinge line, select the resulting cap and rebuild shear
        records on it so the modal chains back to shear. Zero angle is
        a clean no-op exit back to shear."""
        d = self._hinge_data
        angle_rad = math.radians(self._hinge_effective_angle())
        if abs(angle_rad) < 1e-6:
            return self._cancel_hinge(context)
        self._save_hinge_params(context, math.degrees(angle_rad), d["steps"])

        edge = d["edge"]
        # Flap case (all faces at the hinge edge are selected): drop the
        # edge from the selection so spin bends the flap instead of
        # extruding a new wall from the hinge line. Mirrors forgotten
        # hinge.
        if (edge is not None and edge.is_valid and edge.link_faces
                and all(f.select for f in edge.link_faces)):
            edge.select = False
            edge.verts[0].select = False
            edge.verts[1].select = False

        faces = [f for f in self.bm.faces if f.select]
        edges = [e for e in self.bm.edges if e.select]
        verts = [v for v in self.bm.verts if v.select]
        geom = edges + faces + verts
        if not geom:
            self.report({"WARNING"}, "hinge: nothing to spin")
            return self._cancel_hinge(context)
        for g in geom:
            g.select = False

        result = bmesh.ops.spin(
            self.bm, geom=geom, cent=d["center"], axis=d["axis"],
            angle=angle_rad, steps=d["steps"], use_merge=False)
        last = result["geom_last"]

        dist = 0.001
        seed = [g for g in last if isinstance(g, bmesh.types.BMVert)]
        if seed:
            bmesh.ops.remove_doubles(
                self.bm, verts=_gather_double_verts(seed, dist), dist=dist)

        # Drop select_history — the old hinge edge survives the spin
        # (it becomes a wall edge), so a following Q would hinge the
        # new cap around that distant edge and the ghost preview would
        # detach from the cap face. Same rule as _confirm_extrude.
        try:
            self.bm.select_history.clear()
        except (TypeError, RuntimeError):
            pass
        # Full deselect before selecting the new cap: the pre-spin
        # `g.select = False` doesn't flush, so verts/edges of the old
        # cap stay selected and accumulate across chained
        # extrude/hinge rounds.
        for v in self.bm.verts:
            v.select = False
        for e in self.bm.edges:
            e.select = False
        for f in self.bm.faces:
            f.select = False
        for g in last:
            if g.is_valid:
                g.select_set(True)
        self.bm.select_flush_mode()
        self.bm.normal_update()
        bmesh.update_edit_mesh(self.obj.data, loop_triangles=True,
                               destructive=True)

        # Exit the sub-modal before rebuilding shear records.
        self._hinge_active = False
        self._hinge_data = None
        self._hinge_angle_deg = 0.0
        self.input_str = ""
        self._hotspots = []
        self._hover_idx = None

        cap_faces = [g for g in last
                     if isinstance(g, bmesh.types.BMFace) and g.is_valid]
        new_records = []
        for f in cap_faces:
            pa, _ = face_principal_axes(f)
            if pa is None:
                continue
            rec, _ = build_face_record(f, pa)
            if rec is not None:
                new_records.append(rec)
        if new_records:
            self.records = new_records
            self.mode = "face"
            self.angle_deg = 0.0
            context.workspace.status_text_set(self._status_text())
            return {"RUNNING_MODAL"}
        # No usable cap (e.g. rails gone after merge) — finish cleanly
        # rather than leaving shear pointed at dead records.
        bpy.ops.ed.undo_push(message="Shear")
        self._finish(context)
        return {"FINISHED"}

    def _hinge_flush_pick(self, context, event):
        """A: raycast the face under the cursor; set the hinge angle so
        the selection's ORIGINAL plane lands coplanar with the picked
        face's plane (smallest-magnitude solution). Picking one of the
        hinged faces or empty space is a no-op."""
        d = self._hinge_data
        self.bm.normal_update()
        self.bm.faces.ensure_lookup_table()
        self._align_bvh = BVHTree.FromBMesh(self.bm)
        self._mouse_xy = (event.mouse_region_x, event.mouse_region_y)
        picked = self._raycast_face_under_cursor(context)
        self._align_bvh = None
        if picked is None or picked in set(d["faces"]):
            self.report({"INFO"}, "hinge flush: pick a face outside the selection")
            return
        n_t = _face_normal_safe(picked)
        if n_t.length < 1e-9:
            self.report({"INFO"}, "hinge flush: degenerate target face")
            return
        ang = flush_angle(tuple(d["orig_normal"]), tuple(n_t),
                          tuple(d["axis"]))
        if ang is None:
            self.report({"INFO"}, "hinge flush: target parallel to hinge axis")
            return
        self._hinge_angle_deg = math.degrees(ang)
        self.input_str = ""

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
        if rec.get("type") != "face":
            return
        face = rec["face"]
        if not face.is_valid or target is face:
            return
        # Compute the axis BEFORE touching the records — this way any
        # degenerate / parallel-plane miss bails without disturbing
        # the visible shear pose.
        n_current = _face_normal_safe(face)
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
        new_rec, err = build_face_record(face, axis)
        if new_rec is None:
            # build_face_record failed (e.g. isolated face): re-apply
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
        if rec.get("type") != "face":
            return
        face = rec["face"]
        if not face.is_valid:
            return
        axis = _min_obb_axis_for_face(face)
        if axis is None:
            self.report({"INFO"}, "min-OBB axis unavailable")
            return
        restore_records(self.records)
        self.bm.normal_update()
        new_rec, err = build_face_record(face, axis)
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
            face = self.records[rec_idx]["face"]
            new_rec, _ = build_face_record(face, h["axis"])
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
            new_rec, _ = build_face_record(r["face"], new_axis)
            if new_rec is not None:
                apply_records([new_rec], angle)
                self.bm.normal_update()
                rebuilt, _ = build_face_record(new_rec["face"], new_rec["axis_dir"])
                if rebuilt is not None:
                    self.records[rec_idx] = rebuilt
            self.angle_deg = 0.0
            bmesh.update_edit_mesh(self.obj.data)
        elif kind == "edge_set_fixed":
            # Click an endpoint to set that vert as the fixed anchor.
            # Calling flip_edge_record_active swaps active/fixed, so we
            # only flip when the target isn't already fixed. The restore
            # before the flip is critical: without it, the previously-
            # active vert stays at its sheared position even though the
            # flipped record thinks it's the new fixed-and-at-orig vert,
            # which leaves blue/R unable to find a clean reset.
            r = self.records[rec_idx]
            target = h.get("target_vert")
            if target is not None and r["fixed"] is not target:
                restore_records([r])
                flip_edge_record_active(r)
            if abs(self.angle_deg) < 1e-3 and not self.input_str:
                self.angle_deg = 45.0
            self._apply()
        elif kind == "edge_reset":
            self.input_str = ""
            r = self.records[rec_idx]
            restore_records([r])
            self.bm.normal_update()
            angle = compute_reset_angle_edge(r)
            apply_records([r], angle)
            self.bm.normal_update()
            # Rebuild the record at the post-reset state so the widget
            # hotspots (which use orig_active_co / orig_fixed_co)
            # reflect the new perpendicular geometry, and so future
            # angle inputs shear relative to the snapped pose.
            rebuilt, _ = build_edge_record(r["edge"], r["active"])
            if rebuilt is not None:
                self.records[rec_idx] = rebuilt
            self.angle_deg = 0.0
            bmesh.update_edit_mesh(self.obj.data)
        self._hotspots = []  # invalidate; redraw rebuilds
        self._hover_idx = None

    @staticmethod
    def _face_axis_edges(face):
        """Face edges with pairwise non-parallel directions, in face
        winding order. Parallel edges (opposite sides of a quad) give
        the same shear axis, so only the first of each direction is
        kept — F then visits every distinct axis once per lap."""
        out = []
        dirs = []
        for e in face.edges:
            d = e.verts[1].co - e.verts[0].co
            if d.length < 1e-9:
                continue
            d = d / d.length
            if any(abs(d.dot(k)) > 0.9999 for k in dirs):
                continue
            out.append(e)
            dirs.append(d)
        return out, dirs

    def _f_action(self):
        """Face mode: cycle the shear axis through the face's edge
        directions (every distinct direction once per lap, in winding
        order), starting from the edge closest to the current axis.
        Edge mode: flip which endpoint is active."""
        if self.mode == "face":
            restore_records(self.records)
            self.bm.normal_update()
            new_records = []
            for r in self.records:
                face = r["face"]
                if not face.is_valid:
                    new_records.append(r)
                    continue
                edges, dirs = self._face_axis_edges(face)
                if len(edges) < 2:
                    new_records.append(r)
                    continue
                cur = r["axis_dir"]
                cur_i = max(range(len(dirs)),
                            key=lambda i: abs(cur.dot(dirs[i])))
                nxt = edges[(cur_i + 1) % len(edges)]
                new_rec, _ = build_face_record_from_edge(face, nxt)
                new_records.append(new_rec if new_rec is not None else r)
            self.records = new_records
        else:
            for r in self.records:
                flip_edge_record_active(r)
        self._apply()

    # ----------------------------------------------------------------------
    # Modal
    # ----------------------------------------------------------------------

    def _status_text(self):
        if self._hinge_active:
            d = self._hinge_data
            typed = f" | typing: {self.input_str}" if self.input_str else ""
            return (
                f"Hinge: {self._hinge_effective_angle():.2f}° | "
                f"steps: {d['steps']}{typed} | [0-9 . -] type | "
                "[Alt+Wheel] ±5° | [Ctrl+Wheel] steps | [D] flip | "
                "[A] flush to face | "
                "[Enter] confirm | [Q/Esc/RMB] cancel hinge"
            )
        if self._extrude_active:
            return (
                f"Extrude ({self.mode}): {self._extrude_distance:.4f} | "
                "[Mouse] drag | [Shift] precise | "
                "[LMB/Enter] confirm + back to shear | "
                "[Esc/RMB] cancel extrude"
            )
        typed = f" | typing: {self.input_str}" if self.input_str else ""
        f_label = "cycle axis edge" if self.mode == "face" else "flip active vert"
        align_hint = " | [A] align axis to face" if self.mode == "face" else ""
        return (
            f"Shear ({self.mode}): {self._effective_angle():.2f}°{typed} | "
            "[0-9 . -] type | [Alt+Wheel] ±5° | [Backspace] del | "
            f"[F] {f_label} | [D] flip direction | "
            f"[R] perpendicular to rails | [E] extrude{align_hint} | "
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

        if self._hinge_active:
            return self._hinge_modal(context, event)

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
                if self._enter_hinge(context, event):
                    context.workspace.status_text_set(self._status_text())
                return {"RUNNING_MODAL"}

            if event.type == "A":
                if self.mode == "face":
                    self._toggle_align_highlight(context, event)
                    context.workspace.status_text_set(self._status_text())
                return {"RUNNING_MODAL"}

            if event.type == "B":
                if self.mode == "face":
                    self._b_action()
                    context.workspace.status_text_set(self._status_text())
                return {"RUNNING_MODAL"}

            if event.type == "R":
                self.input_str = ""
                if self.mode == "face":
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
                        new_rec, _ = build_face_record(r["face"], new_axis)
                        if new_rec is not None:
                            apply_records([new_rec], angle)
                            self.bm.normal_update()
                            perp_records.append(new_rec)
                        else:
                            perp_records.append(r)
                    rebased = []
                    for r in perp_records:
                        rebuilt, _ = build_face_record(r["face"], r["axis_dir"])
                        rebased.append(rebuilt if rebuilt is not None else r)
                    self.records = rebased
                    bmesh.update_edit_mesh(self.obj.data)
                else:
                    # Edge mode: mirror the blue-dot reset path —
                    # restore, snap perpendicular, rebuild record at
                    # the new perp state so the gizmo handles redraw
                    # against fresh orig coords.
                    new_records = []
                    for r in self.records:
                        restore_records([r])
                        self.bm.normal_update()
                        angle = compute_reset_angle_edge(r)
                        apply_records([r], angle)
                        self.bm.normal_update()
                        rebuilt, _ = build_edge_record(r["edge"], r["active"])
                        new_records.append(rebuilt if rebuilt is not None else r)
                    self.records = new_records
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
                elif self.mode == "face":
                    # Saw-off semantics: flipping axis_dir moves the
                    # pivot to the opposite face edge.
                    restore_records(self.records)
                    self.bm.normal_update()
                    new_records = []
                    for r in self.records:
                        new_axis = -r["axis_dir"]
                        new_rec, _ = build_face_record(r["face"], new_axis)
                        new_records.append(new_rec if new_rec is not None else r)
                    self.records = new_records
                else:
                    self.angle_deg = -self.angle_deg
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
        self._hinge_active = False
        self._hinge_data = None
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
        if self._hinge_active:
            self._draw_hinge(region, rv3d, mw, context=context, theme=theme)
        else:
            for ri, r in enumerate(self.records):
                if r["type"] == "edge":
                    self._draw_edge_record(region, rv3d, mw, r, ri, context=context, theme=theme)
                else:
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
        if d.get("kind") == "edge":
            center = (d["active_anchor"] + d["fixed_anchor"]) * 0.5
            avg_dir = d["active_side_dir"] + d["fixed_side_dir"]
        else:
            center = d["center"]
            avg_dir = d["avg_dir"]
        if avg_dir.length < 1e-9:
            return
        avg_dir = avg_dir.normalized()
        length = max(self._extrude_distance, 0.05)

        tail_world = center
        head_world = center + avg_dir * length
        p_t = view3d_utils.location_3d_to_region_2d(
            region, rv3d, mw @ tail_world)
        p_h = view3d_utils.location_3d_to_region_2d(
            region, rv3d, mw @ head_world)
        if p_t is None or p_h is None:
            return
        draw_prim.edges_3d([p_t, p_h], role=Role.ACTIVE_LINE, context=context)
        hx, hy = p_h
        tx, ty = p_t
        dx, dy = hx - tx, hy - ty
        seg_len = math.hypot(dx, dy)
        if seg_len < 1e-3:
            self._draw_dot(p_t, radius=4.0,
                           color=theme.color_for(Role.ACTIVE_POINT), context=context)
            return
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

    def _draw_hinge(self, region, rv3d, mw, *, context, theme):
        """Ghost of the FINAL spin result: face outlines at the target
        angle (bright), intermediate segment rings (dim), the swept
        wall edges each vert will trace, the hinge axis (amber), and
        an angle arc with per-segment ticks around the edge midpoint.
        The real mesh doesn't move until confirm — this preview is the
        only feedback, so it mirrors the baked spin's segmentation."""
        d = self._hinge_data
        if d is None:
            return

        def s2d(co):
            return view3d_utils.location_3d_to_region_2d(
                region, rv3d, mw @ co)

        angle_rad = math.radians(self._hinge_effective_angle())
        axis = d["axis"]
        center = d["center"]
        steps = max(1, d["steps"])

        # Rotated copies of every hinged vert at each spin segment
        # boundary: k=0 is the original pose, k=steps the final cap.
        step_cos = []
        for k in range(steps + 1):
            rot = Matrix.Rotation(angle_rad * (k / steps), 4, axis)
            step_cos.append({
                v: center + rot @ (oc - center)
                for v, oc in d["orig_co_map"].items()
            })

        def outline_segs(co_map):
            segs = []
            for f in d["faces"]:
                if not f.is_valid:
                    continue
                loops = list(f.verts)
                n = len(loops)
                for i in range(n):
                    a = co_map.get(loops[i])
                    b = co_map.get(loops[(i + 1) % n])
                    if a is None or b is None:
                        continue
                    pa, pb = s2d(a), s2d(b)
                    if pa is not None and pb is not None:
                        segs.extend([pa, pb])
            return segs

        def fill_tris(co_map):
            tris = []
            for f in d["faces"]:
                if not f.is_valid:
                    continue
                pts = []
                for v in f.verts:
                    co = co_map.get(v)
                    if co is None:
                        pts = []
                        break
                    p = s2d(co)
                    if p is None:
                        pts = []
                        break
                    pts.append(p)
                for i in range(1, len(pts) - 1):
                    tris.extend([pts[0], pts[i], pts[i + 1]])
            return tris

        moving = abs(angle_rad) > 1e-6
        # Intermediate segment rings — preview tint from the theme;
        # the k=0 ring coincides with the real mesh already on screen.
        if moving:
            for k in range(1, steps):
                segs = outline_segs(step_cos[k])
                if segs:
                    draw_prim.edges_3d(segs, role=Role.PREVIEW_LINE,
                                       context=context)
            # Swept wall edges: the arc polyline each vert travels,
            # segmented exactly like the baked spin walls.
            wall_segs = []
            for v in d["verts"]:
                for k in range(steps):
                    a = step_cos[k].get(v)
                    b = step_cos[k + 1].get(v)
                    if a is None or b is None:
                        continue
                    pa, pb = s2d(a), s2d(b)
                    if pa is not None and pb is not None:
                        wall_segs.extend([pa, pb])
            if wall_segs:
                draw_prim.edges_3d(wall_segs, role=Role.PREVIEW_LINE,
                                   context=context)
        # Final cap — active fill + outline from the theme. At zero
        # angle it sits on the original pose and doubles as the
        # "hinge armed" highlight.
        cap_tris = fill_tris(step_cos[steps])
        if cap_tris:
            draw_prim.tris(cap_tris,
                           color=theme.color_for(Role.GHOST_ACTIVE),
                           context=context)
        final_segs = outline_segs(step_cos[steps])
        if final_segs:
            draw_prim.edges_3d(final_segs, role=Role.ACTIVE_LINE,
                               context=context)

        # Hinge axis line — amber (locked role). Endpoints captured at
        # entry; axis points don't move (they're on the rotation axis).
        pa, pb = d["axis_pts"]
        p0, p1 = s2d(pa), s2d(pb)
        if p0 is not None and p1 is not None:
            draw_prim.edges_3d([p0, p1], role=Role.LOCKED_LINE,
                               context=context)

        # No angle arc / segment dots — the mesh ghost itself shows
        # the angle and the segment rings.
        # Center dot at the hinge midpoint.
        pc = s2d(center)
        if pc is not None:
            self._draw_dot(pc, radius=5.0,
                           color=theme.color_for(Role.LOCKED_POINT),
                           context=context)

    def _draw_edge_record(self, region, rv3d, mw, r, rec_idx=0, *, context, theme):
        if not (r["active"].is_valid and r["fixed"].is_valid):
            return

        def s2d(co):
            return view3d_utils.location_3d_to_region_2d(region, rv3d, mw @ co)

        p_active = s2d(r["active"].co)
        p_fixed = s2d(r["fixed"].co)
        p_orig_active = s2d(r["orig_active_co"])
        p_orig_fixed = s2d(r["orig_fixed_co"])
        if p_active is None or p_fixed is None:
            return

        # Ghost edge (orig position) — subtle grey, no role match.
        if p_orig_active is not None and p_orig_fixed is not None:
            draw_prim.edges_3d([p_orig_fixed, p_orig_active],
                               color=(0.45, 0.45, 0.45, 0.55), context=context)
        # Current sheared edge — active.
        draw_prim.edges_3d([p_fixed, p_active], role=Role.ACTIVE_LINE, context=context)

        # Endpoint hotspots — click either to make that vert the fixed
        # anchor (= F-action when clicking the currently active end).
        locked = theme.color_for(Role.LOCKED_POINT)
        for target_vert, screen_pt in (
            (r["fixed"], p_orig_fixed),
            (r["active"], p_orig_active),
        ):
            if screen_pt is None:
                continue
            self._hotspots.append({
                "kind": "edge_set_fixed",
                "region_pt": (screen_pt[0], screen_pt[1]),
                "target_vert": target_vert,
                "rec_idx": rec_idx,
            })
            self._draw_dot(screen_pt, radius=5.0,
                           color=(*locked[:3], 0.75), context=context)

        # Blue center dot — click to reset (= R for edge: angle to 0
        # via the regression).
        if p_orig_active is not None and p_orig_fixed is not None:
            mid = (r["orig_active_co"] + r["orig_fixed_co"]) * 0.5
            p_mid = s2d(mid)
            if p_mid is not None:
                self._hotspots.append({
                    "kind": "edge_reset",
                    "region_pt": (p_mid[0], p_mid[1]),
                    "rec_idx": rec_idx,
                })
                closest = theme.color_for(Role.CLOSEST_POINT)
                self._draw_dot(p_mid, radius=5.0,
                               color=(*closest[:3], 0.75), context=context)

    def _draw_face_record(self, region, rv3d, mw, r, rec_idx=0, *, context, theme):
        verts = r["active_verts"]
        origs = r["orig_active_cos"]
        projs = r["projections"]
        n = len(verts)
        if n < 3:
            return

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
            for i in range(n):
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
        if curr:
            normal_segs = []
            pivot_segs = []
            for i in range(n):
                j = (i + 1) % n
                a, b = curr[i], curr[j]
                if on_pivot[i] and on_pivot[j]:
                    pivot_segs.extend([a, b])
                else:
                    normal_segs.extend([a, b])
            if normal_segs:
                draw_prim.edges_3d(normal_segs, role=Role.ACTIVE_LINE, context=context)
            if pivot_segs:
                # Pivot edges (on-pivot boundary) — brighter amber via LOCKED_POINT role.
                draw_prim.edges_3d(pivot_segs, role=Role.LOCKED_LINE, context=context)

        # ----- Bbox-anchored direction widget -------------------------
        # Anchored to the *orig* face bounding box (the perpendicular /
        # reset-state selection bbox). The cross of orange dots follows
        # the current axis_dir + in-plane perpendicular so any change
        # to axis_dir (A-align, B-OBB, axis click, F toggle, D flip)
        # immediately reorients the widget on the next redraw.
        face_normal = _face_normal_safe(r["face"])
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
        if self._hinge_active and self._hinge_data is not None:
            lines = [f"Mode: hinge",
                     f"Angle: {self._hinge_effective_angle():.2f}°",
                     f"Steps: {self._hinge_data['steps']}"]
        else:
            lines = [f"Mode: {self.mode}",
                     f"Angle: {self._effective_angle():.2f}°"]
        if self.input_str:
            lines.append(f"Typing: {self.input_str}")
        hud.set_header(*lines)
        hud.draw(context, last_event)
