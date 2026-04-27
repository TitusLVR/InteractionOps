"""Smart shear operator. Detects selection and dispatches to the
appropriate algorithm.

For face mode, F toggles between the face's two principal in-plane
directions (PCA on face vert positions). This works for arbitrary
profiles — beveled squares, custom hand-built shapes, anything where
"X and Y" are the natural shear axes given the face normal as Z.


- face selection (any face selected) → face shear: each face vert
  slides along its non-face rail edge by `-(proj·tan(angle))` where
  `proj` is the vert's offset from face centroid along the axis edge.
  Face tilts around its centroid.

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
import blf
from gpu_extras.batch import batch_for_shader
from bpy_extras import view3d_utils
from mathutils import Vector
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
    rail edges by `-(proj·tan(angle))`. `axis_dir` is a unit Vector in
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
            return None, (
                f"vert {av.index} has no external rail edge "
                "(face is isolated at this corner)"
            )
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
    # vert slides along its rail away from the pivot edge by
    # `proj * tan(angle)`.
    min_centroid_proj = min(centroid_projs)
    projections = [cp - min_centroid_proj for cp in centroid_projs]
    pivot_point = centroid + axis_dir * min_centroid_proj

    pa, pb = face_principal_axes(face)
    return {
        "type": "face",
        "face": face,
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
    """Two unit axes in the face plane aligned to world axes (not to
    the face's vertex distribution). axis_a is world +Z projected onto
    the face plane; axis_b = normal × axis_a. When the face normal is
    near-parallel to ±Z (so +Z projects to nothing), seeds fall back
    to +Y, then +X.

    PCA on the vert distribution would lock onto the face's geometric
    diagonal for shapes like a beveled square (where the bevel adds
    variance along that diagonal), giving an axis the user almost
    never wants. World-axis projection gives the intuitive "X and Y
    when face normal is Z" behaviour for arbitrary profiles."""
    normal = _face_normal_safe(face)
    if normal.length < 1e-9:
        return None, None

    seeds = (
        Vector((0.0, 0.0, 1.0)),
        Vector((0.0, 1.0, 0.0)),
        Vector((1.0, 0.0, 0.0)),
    )
    axis_a = None
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


def _fit_reset_for_axis(rec, axis_dir):
    """Linear-regression fit of `offset_along_rail = -tan(θ) * proj +
    C` for the given axis. Returns (slope, residual_sum_squares) so a
    caller can pick the best axis. None if the system is degenerate."""
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
    return slope, rss


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
        slope, rss = fit
        angle = math.degrees(math.atan(-slope))
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

    # Linear-least-squares fit: solve `offs ≈ -tan(θ) * projs + C`
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
    return math.degrees(math.atan(-slope))


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


def apply_records(records, angle_deg):
    t = _angle_to_t(angle_deg)
    for r in records:
        if r["type"] == "edge":
            if r["active"].is_valid and r["fixed"].is_valid:
                # Saw-off slide: active moves along its rail by
                # edge_length × tan(angle). Rail constraint keeps the
                # active vert on the surrounding mesh line.
                shift = r["rail_dir"] * r["edge_length"] * t
                r["active"].co = r["orig_active_co"] + shift
        elif r["type"] == "face":
            for av, oc, rail, proj in zip(
                    r["active_verts"], r["orig_active_cos"],
                    r["rails"], r["projections"]):
                if av.is_valid:
                    av.co = oc + rail["dir"] * (proj * t)


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
        # Point-and-click state. Each entry: {"region_pt": (x,y),
        # "axis": Vector, "rec_idx": int}. Click on any hotspot
        # rebuilds that record with the picked axis (= switches both
        # the F-toggle direction and the D-pivot side in one action).
        self._hotspots = []
        self._hover_idx = None
        self._mouse_xy = (event.mouse_region_x, event.mouse_region_y)
        # Extrude sub-modal state. While `_extrude_active`, MOUSEMOVE
        # adjusts distance, LMB/Enter confirms (rebuilds shear records
        # on the new geometry and chains back to shear), Esc/RMB
        # cancels (deletes the new geometry).
        self._extrude_active = False
        self._extrude_data = None
        self._extrude_distance = 0.0
        self._extrude_start_x = 0

        # Align sub-modal state. A enters; mouse hovers a face which
        # gets a 35% red overlay; LMB picks it and sets axis_dir to the
        # intersection line of the current face plane and the picked
        # face plane (projected into the current face plane). Esc/RMB
        # exits without applying.
        self._align_active = False
        self._align_face = None
        self._align_bvh = None

        bpy.ops.ed.undo_push(message="Shear")

        self.shader = gpu.shader.from_builtin("UNIFORM_COLOR")
        self._handle = bpy.types.SpaceView3D.draw_handler_add(
            self._draw_callback, (context,), "WINDOW", "POST_PIXEL")

        self._apply()
        context.workspace.status_text_set(self._status_text())
        context.window_manager.modal_handler_add(self)
        if context.area:
            context.area.tag_redraw()
        return {"RUNNING_MODAL"}

    # ----------------------------------------------------------------------
    # Math wrappers
    # ----------------------------------------------------------------------

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
            face = rec["face"]
            rails = rec.get("rails", [])
            projs = rec.get("projections", [])
            active_verts = rec["active_verts"]
            if not rails or not projs:
                return False

            def mirror(vec, n):
                # Same convention as edge mode: 2(v·n)n - v. This is
                # the negation of the textbook plane-reflection so the
                # OUTGOING direction points away from the existing body.
                # At zero shear (n parallel to rail) this collapses to
                # +rail_dir, which is the natural "extrude outward"
                # direction (rail goes from anchor INTO the face vert).
                return 2.0 * vec.dot(n) * n - vec

            # Use the CURRENT (sheared) face normal as the mirror plane.
            # bm.normal_update() is assumed to be current at this point;
            # the modal path always calls it after each shear edit.
            face_normal = _face_normal_safe(face)
            if face_normal.length < 1e-9:
                return False

            # Per-vert side direction = mirror of the rail across the
            # sheared face plane (using the edge-mode convention so the
            # direction points OUT of the existing body). The sheared
            # face acts as the angle bisector between old rail (going
            # INTO existing geometry) and new side (going INTO the
            # extruded segment). Per-vert delay = (proj_max - proj) *
            # tan(angle): vert with the largest projection (opposite-
            # pivot edge) has zero delay and moves immediately; pivot-
            # edge verts wait the longest. Mirrors the edge-mode saw-
            # off rule one-vert-at-a-time for every face vert.
            proj_max = max(projs) if projs else 0.0
            per_old_vert = {}
            for av, rail, proj in zip(active_verts, rails, projs):
                side = mirror(rail["dir"], face_normal)
                if side.length < 1e-9:
                    side = rail["dir"]  # rail parallel to normal — fallback
                else:
                    side = side.normalized()
                delay = (proj_max - proj) * t
                per_old_vert[av] = (av.co.copy(), side, delay)

            res = bmesh.ops.extrude_face_region(self.bm, geom=[face])
            new_geom = res.get("geom", [])
            new_verts = [g for g in new_geom
                         if isinstance(g, bmesh.types.BMVert)]
            new_faces = [g for g in new_geom
                         if isinstance(g, bmesh.types.BMFace)]
            target_face = next(
                (f for f in new_faces if len(f.verts) == len(face.verts)),
                None,
            )
            if target_face is None or not new_verts:
                return False

            # Match each new vert to its old counterpart by position
            # (they coincide right after extrude_face_region).
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
                    sides.append(face_normal.copy())
                    delays.append(0.0)
                else:
                    anchors.append(best[0])
                    sides.append(best[1])
                    delays.append(best[2])

            # Average side direction (for the on-screen arrow indicator).
            avg = anchors[0] * 0.0
            for s in sides:
                avg = avg + s
            avg_dir = avg.normalized() if avg.length > 1e-9 else face_normal

            # Centroid of the sheared face (arrow tail anchor).
            center = anchors[0] * 0.0
            for a in anchors:
                center = center + a
            center = center / len(anchors)

            # NOTE: extrude_face_region leaves the original face in
            # place under the new cap. We DEFER deleting it until
            # _confirm_extrude — if the user cancels, the original
            # face must still be present (records[0]["face"] points
            # at it and downstream callers like apply_records and
            # _draw_face_record deref it without is_valid checks).
            self._extrude_data = {
                "kind": "face",
                "verts": new_verts,
                "anchors": anchors,
                "sides": sides,
                "delays": delays,
                "avg_dir": avg_dir.copy(),
                "center": center.copy(),
                "target": target_face,
                "orig_face": face,
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
        self.bm.normal_update()
        bmesh.update_edit_mesh(self.obj.data)
        return True

    def _extrude_modal(self, context, event):
        if event.type == "MOUSEMOVE":
            dx = event.mouse_region_x - self._extrude_start_x
            sens = 0.01
            if event.shift:
                sens *= 0.1
            t = max(0.0, dx * sens)
            self._extrude_distance = t
            d = self._extrude_data
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
        # Now that the user committed, the original face becomes an
        # interior face and must be removed. Side walls already share
        # its verts and edges so FACES_ONLY leaves the surrounding
        # topology intact. Cancel doesn't reach this path so the
        # face survives a cancel.
        orig_face = d.get("orig_face")
        if (kind == "face" and orig_face is not None
                and orig_face.is_valid):
            bmesh.ops.delete(
                self.bm, geom=[orig_face], context="FACES_ONLY",
            )
        if kind == "face" and target.is_valid:
            pa, _ = face_principal_axes(target)
            if pa is not None:
                new_rec, _ = build_face_record(target, pa)
                if new_rec is not None:
                    self.records = [new_rec]
                    self.mode = "face"
        elif kind == "edge" and target.is_valid:
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

    def _f_action(self):
        """Face mode: toggle between the two principal in-plane axes
        (PCA), so F lands on the OTHER main direction in one press
        regardless of how many edges the face has. Edge mode: flip
        which endpoint is active."""
        if self.mode == "face":
            restore_records(self.records)
            self.bm.normal_update()
            new_records = []
            for r in self.records:
                pa, pb = r.get("principal_axes", (None, None))
                if pa is None or pb is None:
                    new_records.append(r)
                    continue
                # Pick whichever principal axis is NOT the current one.
                cur = r["axis_dir"]
                if abs(cur.dot(pa)) > abs(cur.dot(pb)):
                    next_axis = pb
                else:
                    next_axis = pa
                new_rec, _ = build_face_record(r["face"], next_axis)
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
            "[0-9 . -] type | [Backspace] del | "
            f"[F] {f_label} | [D] flip direction | "
            f"[R] perpendicular to rails | [E] extrude{align_hint} | "
            "[Enter] confirm | [Esc/RMB] cancel"
        )

    def modal(self, context, event):
        if context.area:
            context.area.tag_redraw()

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
                self._finish(context)
                return {"FINISHED"}

            if event.type in {"RIGHTMOUSE", "ESC"}:
                self._restore_records()
                self._finish(context)
                return {"CANCELLED"}

        return {"RUNNING_MODAL"}

    def _finish(self, context):
        if getattr(self, "_handle", None):
            bpy.types.SpaceView3D.draw_handler_remove(self._handle, "WINDOW")
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

    def _draw_dot(self, p, radius=6.0):
        cx, cy = p
        segs = 24
        ring = [
            (cx + math.cos(2 * math.pi * i / segs) * radius,
             cy + math.sin(2 * math.pi * i / segs) * radius)
            for i in range(segs)
        ]
        tris = []
        for i in range(segs):
            j = (i + 1) % segs
            tris.extend([(cx, cy), ring[i], ring[j]])
        batch = batch_for_shader(self.shader, "TRIS", {"pos": tris})
        batch.draw(self.shader)

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
                    bpy.types.SpaceView3D.draw_handler_remove(h, "WINDOW")
                except (ValueError, RuntimeError, ReferenceError):
                    pass
            return

        gpu.state.blend_set("ALPHA")
        gpu.state.line_width_set(2.0)
        self.shader.bind()

        # Rebuild hotspot list each draw — view changes & axis edits
        # invalidate prior screen positions.
        self._hotspots = []
        for ri, r in enumerate(self.records):
            if r["type"] == "edge":
                self._draw_edge_record(region, rv3d, mw, r, ri)
            else:
                self._draw_face_record(region, rv3d, mw, r, ri)
        self._update_hover()
        # Draw hover highlight on top.
        if self._hover_idx is not None and self._hover_idx < len(self._hotspots):
            rp = self._hotspots[self._hover_idx].get("region_pt")
            if rp is not None:
                self.shader.uniform_float("color", (1.0, 1.0, 1.0, 1.0))
                self._draw_dot(rp, radius=8.0)

        if self._extrude_active:
            self._draw_extrude_arrows(region, rv3d, mw)

        if self._align_active:
            self._draw_align_highlight(region, rv3d, mw)

        gpu.state.line_width_set(1.0)
        gpu.state.blend_set("NONE")

        self._draw_hud(context)

    def _draw_align_highlight(self, region, rv3d, mw):
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
        self.shader.uniform_float("color", (1.0, 0.0, 0.0, 0.35))
        batch = batch_for_shader(self.shader, "TRIS", {"pos": tris})
        batch.draw(self.shader)

    def _draw_extrude_arrows(self, region, rv3d, mw):
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
        self.shader.uniform_float("color", (1.0, 0.6, 0.1, 1.0))
        batch = batch_for_shader(
            self.shader, "LINES", {"pos": [p_t, p_h]})
        batch.draw(self.shader)
        hx, hy = p_h
        tx, ty = p_t
        dx, dy = hx - tx, hy - ty
        seg_len = math.hypot(dx, dy)
        if seg_len < 1e-3:
            self._draw_dot(p_t, radius=4.0)
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
        batch = batch_for_shader(
            self.shader, "LINES",
            {"pos": [p_h, leg1, p_h, leg2]},
        )
        batch.draw(self.shader)
        self._draw_dot(p_t, radius=4.0)

    def _draw_edge_record(self, region, rv3d, mw, r, rec_idx=0):
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

        # Ghost edge (orig position) and current sheared edge.
        if p_orig_active is not None and p_orig_fixed is not None:
            self.shader.uniform_float("color", (0.45, 0.45, 0.45, 0.55))
            batch = batch_for_shader(
                self.shader, "LINES", {"pos": [p_orig_fixed, p_orig_active]})
            batch.draw(self.shader)
        self.shader.uniform_float("color", (1.0, 0.6, 0.1, 1.0))
        batch = batch_for_shader(self.shader, "LINES", {"pos": [p_fixed, p_active]})
        batch.draw(self.shader)

        # Endpoint hotspots — click either to make that vert the fixed
        # anchor (= F-action when clicking the currently active end).
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
            self.shader.uniform_float("color", (1.0, 0.85, 0.3, 0.75))
            self._draw_dot(screen_pt, radius=5.0)

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
                self.shader.uniform_float("color", (0.3, 0.55, 1.0, 0.75))
                self._draw_dot(p_mid, radius=5.0)

    def _draw_face_record(self, region, rv3d, mw, r, rec_idx=0):
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
            self.shader.uniform_float("color", (0.45, 0.45, 0.45, 0.55))
            segs = []
            for i in range(n):
                segs.extend([ghost[i], ghost[(i + 1) % n]])
            batch = batch_for_shader(self.shader, "LINES", {"pos": segs})
            batch.draw(self.shader)

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
                self.shader.uniform_float("color", (1.0, 0.6, 0.1, 1.0))
                batch = batch_for_shader(
                    self.shader, "LINES", {"pos": normal_segs})
                batch.draw(self.shader)
            if pivot_segs:
                gpu.state.line_width_set(4.0)
                self.shader.uniform_float("color", (1.0, 0.9, 0.4, 1.0))
                batch = batch_for_shader(
                    self.shader, "LINES", {"pos": pivot_segs})
                batch.draw(self.shader)
                gpu.state.line_width_set(2.0)

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
                    gpu.state.line_width_set(3.0)
                    self.shader.uniform_float("color", (1.0, 0.85, 0.3, 1.0))
                    batch = batch_for_shader(
                        self.shader, "LINES", {"pos": [p_tick_a, p_tick_b]})
                    batch.draw(self.shader)
                    gpu.state.line_width_set(2.0)

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
                    self.shader.uniform_float("color", (1.0, 0.85, 0.3, 0.75))
                    self._draw_dot(rp, radius=5.0)

                if p_bbox_center is not None:
                    # Blue center dot is a click-to-reset handle (= R).
                    self._hotspots.append({
                        "kind": "reset",
                        "region_pt": (p_bbox_center[0], p_bbox_center[1]),
                        "rec_idx": rec_idx,
                    })
                    self.shader.uniform_float("color", (0.3, 0.55, 1.0, 0.75))
                    self._draw_dot(p_bbox_center, radius=5.0)

    def _draw_hud(self, context):
        font_id = 0
        try:
            prefs = context.preferences.addons["InteractionOps"].preferences
            tCSize = getattr(prefs, "text_size", 18)
            tCPosX = getattr(prefs, "text_pos_x", 30)
            tCPosY = getattr(prefs, "text_pos_y", 90)
            tColor = getattr(prefs, "text_color", (1.0, 1.0, 1.0, 1.0))
        except (KeyError, AttributeError):
            tCSize, tCPosX, tCPosY = 18, 30, 90
            tColor = (1.0, 1.0, 1.0, 1.0)
        uifactor = context.preferences.system.ui_scale

        label = f"Shear ({self.mode}): {self._effective_angle():.2f}°"
        if self.input_str:
            label += f"  (typing: {self.input_str})"

        main_px = int(tCSize * uifactor)
        hint_px = max(int(tCSize * 0.75 * uifactor), 11)
        x = tCPosX * uifactor
        y_main = tCPosY * uifactor

        f_label = (
            "F                cycle axis edge" if self.mode == "face"
            else "F                flip active vert"
        )
        hints = [
            "Esc / RMB     cancel",
            "Enter            confirm",
            "E                extrude perpendicular",
            "R                perpendicular to rails",
            "D                flip direction",
            f_label,
            "Backspace       delete digit",
            "0-9  .  -        type angle",
        ]
        if self.mode == "face":
            hints.insert(2, "B                axis to min OBB")
            hints.insert(2, "A                align axis to face under cursor")
        hint_color = (tColor[0], tColor[1], tColor[2], tColor[3] * 0.7)
        line_h = int(hint_px * 1.4)
        blf.size(font_id, hint_px)
        blf.color(font_id, *hint_color)
        for i, hint in enumerate(hints):
            y_hint = y_main + int(main_px * 1.6) + line_h * i
            blf.position(font_id, x, y_hint, 0)
            blf.draw(font_id, hint)

        blf.size(font_id, main_px)
        blf.color(font_id, *tColor)
        blf.position(font_id, x, y_main, 0)
        blf.draw(font_id, label)
