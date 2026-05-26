import bpy
import math
from mathutils import Vector, Matrix, Quaternion

from ..ui.draw import safe_handler_add, safe_handler_remove
from ..ui.draw.theme import get_theme, Role
from ..ui.hud import (
    HUDOverlay, HelpOverlay, HUDSection, HUDItem,
    HUDParam, ItemState,
    handle_hud_toggle, handle_help_toggle, capture_event,
)


# --- HUD / Help builders ---------------------------------------------------

def _build_hud(context):
    hud = HUDOverlay("object_radial_array")
    hud.title = "Radial Array"
    hud.bind_region(context.region)
    return hud


def _build_help(context):
    helpo = HelpOverlay("object_radial_array")
    helpo.add_section(HUDSection("Radial Array", [
        HUDItem("Pivot mode",     "Q",                  ItemState.ON, default_state=ItemState.OFF, always_show=True),
        HUDItem("Arc mode (360/180/90/45/Cursor)", "W", ItemState.ON, default_state=ItemState.OFF, always_show=True),
        HUDItem("End inclusive",  "E",                  ItemState.ON, default_state=ItemState.OFF, always_show=True),
        HUDItem("Alignment cycle (Original/Outward/Inward/Follow/Follow-rev/Random)", "R", ItemState.ON, default_state=ItemState.OFF, always_show=True),
        HUDItem("Clone type",     "D",                  ItemState.ON, default_state=ItemState.OFF, always_show=True),
        HUDItem("Skip first",     "F",                  ItemState.ON, default_state=ItemState.OFF, always_show=True),
        HUDItem("Axis X/Y/Z",     "X / Y / Z",          ItemState.ON, default_state=ItemState.OFF, always_show=True),
        HUDItem("Local axis",     "C",                  ItemState.ON, default_state=ItemState.OFF, always_show=True),
        HUDItem("View axis",      "V",                  ItemState.ON, default_state=ItemState.OFF, always_show=True),
        HUDItem("Normal pick",    "T + LMB",            ItemState.ON, default_state=ItemState.OFF, always_show=True),
        HUDItem("Count +/-",      "+ / -  or  Ctrl+Wheel", ItemState.ON, default_state=ItemState.OFF, always_show=True),
        HUDItem("Radius drag (360/180/90/45)", "LMB on ring + drag", ItemState.ON, default_state=ItemState.OFF, always_show=True),
        HUDItem("Move arc center (Active→Cursor)", "LMB on center + drag", ItemState.ON, default_state=ItemState.OFF, always_show=True),
        HUDItem("Flip arc center", "I",                 ItemState.ON, default_state=ItemState.OFF, always_show=True),
        HUDItem("Reset to defaults", "B",                ItemState.ON, default_state=ItemState.OFF, always_show=True),
        HUDItem("Match from origins", "M (toggle)",      ItemState.ON, default_state=ItemState.OFF, always_show=True),
        HUDItem("Source mode (Active/Hier/Group/Pool)", "U", ItemState.ON, default_state=ItemState.OFF, always_show=True),
        HUDItem("Reroll pool seed",   "K",                ItemState.ON, default_state=ItemState.OFF, always_show=True),
        HUDItem("Apply",          "Space / Enter",      ItemState.ON, default_state=ItemState.OFF, always_show=True),
        HUDItem("Cancel",         "Esc / RMB",          ItemState.ON, default_state=ItemState.OFF, always_show=True),
        HUDItem("Help / HUD",     "H",                  ItemState.ON, default_state=ItemState.OFF, always_show=True),
    ]))
    helpo.bind_region(context.region)
    return helpo


def _draw_callback(op, context):
    helpo = getattr(op, "_help", None)
    hud = getattr(op, "_hud", None)
    last_event = getattr(op, "_last_event", None)
    if helpo is not None:
        helpo.draw(context, last_event)
    if hud is not None:
        hud.draw(context, last_event)


# --- State enums (string constants — Blender modal idiom) ----------------

PIVOT_ACTIVE       = "ACTIVE"
PIVOT_CURSOR       = "CURSOR"
PIVOT_LAST         = "LAST_SELECTED"
PIVOT_CYCLE        = (PIVOT_ACTIVE, PIVOT_CURSOR, PIVOT_LAST)

CLONE_DUP          = "DUPLICATE"
CLONE_INST         = "INSTANCE"
CLONE_REPLACE      = "REPLACE"
CLONE_CYCLE        = (CLONE_DUP, CLONE_INST, CLONE_REPLACE)

SOURCE_ACTIVE      = "ACTIVE"        # only the active object (no children)
SOURCE_HIERARCHY   = "HIERARCHY"     # active + its parented children (single subtree)
SOURCE_GROUP       = "GROUP"         # all selected, rigid group, anchor = active
SOURCE_POOL        = "POOL"          # all selected; one per slot, random extras
SOURCE_CYCLE       = (SOURCE_ACTIVE, SOURCE_HIERARCHY, SOURCE_GROUP, SOURCE_POOL)

ALIGN_NONE         = "ORIGINAL"      # keep clone orientation identical to source
ALIGN_OUTWARD      = "OUTWARD"       # face away from pivot
ALIGN_INWARD       = "INWARD"        # face toward pivot
ALIGN_FOLLOW       = "FOLLOW"        # face along the tangent (direction of motion around ring)
ALIGN_FOLLOW_REV   = "FOLLOW_REV"    # face along the opposite tangent
ALIGN_RANDOM_ALL   = "RANDOM_ALL"    # random rotation around all 3 local axes
ALIGN_RANDOM_X     = "RANDOM_X"      # random rotation around local X
ALIGN_RANDOM_Y     = "RANDOM_Y"      # random rotation around local Y
ALIGN_RANDOM_Z     = "RANDOM_Z"      # random rotation around local Z
ALIGN_CYCLE        = (ALIGN_NONE, ALIGN_OUTWARD, ALIGN_INWARD,
                      ALIGN_FOLLOW, ALIGN_FOLLOW_REV,
                      ALIGN_RANDOM_ALL, ALIGN_RANDOM_X, ALIGN_RANDOM_Y, ALIGN_RANDOM_Z)

ARC_FULL           = "360°"
ARC_180            = "180°"
ARC_90             = "90°"
ARC_45             = "45°"
ARC_CURSOR         = "Active→Cursor"
ARC_CYCLE          = (ARC_FULL, ARC_180, ARC_90, ARC_45, ARC_CURSOR)

_ARC_FIXED_SWEEPS = {
    ARC_FULL:   2 * math.pi,
    ARC_180:    math.pi,
    ARC_90:     math.pi / 2,
    ARC_45:     math.pi / 4,
}

AXIS_GLOBAL_X      = "GX"
AXIS_GLOBAL_Y      = "GY"
AXIS_GLOBAL_Z      = "GZ"
AXIS_LOCAL_X       = "LX"
AXIS_LOCAL_Y       = "LY"
AXIS_LOCAL_Z       = "LZ"
AXIS_VIEW          = "VIEW"
AXIS_NORMAL        = "NORMAL"


def _cycle(value, options):
    i = options.index(value) if value in options else 0
    return options[(i + 1) % len(options)]


def _subtree_roots_and_descendants(obj):
    """Return [root, *children_recursive] in stable order."""
    return [obj, *obj.children_recursive]


def _build_subtree_data(roots, include_children):
    """Build subtree_data: list of [(obj, rel_matrix_to_root), ...] entries per root."""
    out = []
    for root in roots:
        try:
            inv = root.matrix_world.inverted()
        except (ReferenceError, ValueError):
            continue
        sub = [(root, inv @ root.matrix_world)]
        if include_children:
            for child in root.children_recursive:
                sub.append((child, inv @ child.matrix_world))
        out.append(sub)
    return out


def _resolve_source_roots(context, source_mode):
    """Return (roots, anchor_obj). anchor_obj is the active in GROUP mode (None otherwise)."""
    sel = list(context.selected_objects)
    active = context.active_object
    if source_mode == SOURCE_ACTIVE:
        return ([active] if active else []), None
    if source_mode == SOURCE_HIERARCHY:
        return ([active] if active else []), None
    if source_mode == SOURCE_GROUP:
        # active first so it owns slot 0 / acts as anchor; others keep selection order.
        if active and active in sel:
            others = [o for o in sel if o is not active]
            return [active, *others], active
        return list(sel), active
    if source_mode == SOURCE_POOL:
        if active and active in sel:
            others = [o for o in sel if o is not active]
            return [active, *others], None
        return list(sel), None
    return list(sel), None


def _resolve_selection(context, pivot_mode):
    """Return (pivot_world_co, pivot_object_or_none, source_roots, end_target_or_none).
    end_target is legacy / unused — kept None for signature stability."""
    sel = list(context.selected_objects)
    active = context.active_object

    if pivot_mode == PIVOT_ACTIVE:
        pivot_obj = active
        pivot_co = active.matrix_world.translation.copy() if active else None
        sources = [o for o in sel if o is not active]
    elif pivot_mode == PIVOT_CURSOR:
        pivot_obj = None
        pivot_co = context.scene.cursor.location.copy()
        sources = list(sel)
    else:  # PIVOT_LAST
        non_active = [o for o in sel if o is not active]
        pivot_obj = non_active[-1] if non_active else active
        pivot_co = pivot_obj.matrix_world.translation.copy() if pivot_obj else None
        sources = [o for o in sel if o is not pivot_obj]

    return pivot_co, pivot_obj, sources, None


def _resolve_axis(self, context):
    """Return a normalized world-space axis vector based on self.axis_mode."""
    am = self.axis_mode
    if am == AXIS_GLOBAL_X: return Vector((1, 0, 0))
    if am == AXIS_GLOBAL_Y: return Vector((0, 1, 0))
    if am == AXIS_GLOBAL_Z: return Vector((0, 0, 1))
    if am in (AXIS_LOCAL_X, AXIS_LOCAL_Y, AXIS_LOCAL_Z):
        if self.pivot_obj is None:
            return Vector((0, 0, 1))  # cursor pivot fallback
        rot = self.pivot_obj.matrix_world.to_3x3()
        local = {AXIS_LOCAL_X: Vector((1,0,0)),
                 AXIS_LOCAL_Y: Vector((0,1,0)),
                 AXIS_LOCAL_Z: Vector((0,0,1))}[am]
        return (rot @ local).normalized()
    if am == AXIS_VIEW:
        rv3d = context.region_data
        if rv3d is None:
            return Vector((0, 0, 1))
        return (rv3d.view_rotation @ Vector((0, 0, -1))).normalized()
    if am == AXIS_NORMAL:
        return self._cached_axis_vec.copy() if self._cached_axis_vec.length > 0 else Vector((0,0,1))
    return Vector((0, 0, 1))


def _signed_angle_around(v_from, v_to, axis):
    """Signed angle from v_from to v_to about axis (right-hand). Returns radians in (-pi, pi]."""
    a = v_from.normalized()
    b = v_to.normalized()
    n = axis.normalized()
    a = (a - n * a.dot(n)).normalized()
    b = (b - n * b.dot(n)).normalized()
    if a.length < 1e-8 or b.length < 1e-8:
        return 0.0
    dot = max(-1.0, min(1.0, a.dot(b)))
    ang = math.acos(dot)
    if a.cross(b).dot(n) < 0:
        ang = -ang
    return ang


def _arc_effective_start(op, axis_vec):
    """Effective start offset (radians). For non-full arcs we anchor the start
    at the active object's angle around the pivot."""
    if op.arc_mode != ARC_FULL:
        active = getattr(op, "active_obj", None)
        if active is not None:
            try:
                v = active.matrix_world.translation - op.pivot_co
            except ReferenceError:
                return 0.0
            right, fwd = _arc_frame(axis_vec)
            v_planar = v - axis_vec * v.dot(axis_vec)
            if v_planar.length > 1e-6:
                return math.atan2(v_planar.dot(fwd), v_planar.dot(right))
    return 0.0


def _compute_arc(self, axis_vec):
    """Return (arc_angle_radians, step_radians, n_clones) for the current mode."""
    n = max(2, int(self.count))
    if self.arc_mode == ARC_FULL:
        return 2 * math.pi, (2 * math.pi) / n, n - 1
    if self.arc_mode in _ARC_FIXED_SWEEPS:
        ang = _ARC_FIXED_SWEEPS[self.arc_mode]
        step = ang / (n - 1) if self.end_inclusive else ang / n
        return ang, step, n - 1
    # ARC_CURSOR — sweep derived from active→cursor geometry
    g = _arc_two_point_geometry(self, axis_vec)
    if g is None:
        return 0.0, 0.0, 0
    _center, _R, _start, sweep = g
    if abs(sweep) < 1e-6:
        return 0.0, 0.0, 0
    step = sweep / (n - 1) if self.end_inclusive else sweep / n
    return sweep, step, n - 1


def _clone_matrix(pivot_co, axis_vec, angle, source_mw):
    """Position-only world matrix for a clone of a source root at the given angle
    around pivot. Alignment is applied as a separate post-rotation via
    `_alignment_extra_rot`."""
    R = Matrix.Rotation(angle, 4, axis_vec)
    T_to   = Matrix.Translation(pivot_co)
    T_from = Matrix.Translation(-pivot_co)
    return T_to @ R @ T_from @ source_mw


def _aligned_clone_mw(align_mode, pivot_co, axis_vec, base_mw,
                      seed, slot_index, follow_target=None):
    """Apply alignment on top of `base_mw`. `base_mw` is the clone's natural
    pre-alignment matrix — for group-rigid that's the source rotated around the
    pivot; for pool/replace that's the source with translation set to the slot.
    ALIGN_NONE returns `base_mw` unchanged. Other modes layer an in-place
    rotation around `base_mw.translation`.

    `follow_target` = position of the next clone (used by FOLLOW modes to take
    the direction between consecutive ring slots, not the analytic tangent)."""
    if align_mode == ALIGN_NONE:
        return base_mw

    clone_pos = base_mw.translation
    T_to   = Matrix.Translation(clone_pos)
    T_from = Matrix.Translation(-clone_pos)

    if align_mode in (ALIGN_RANDOM_ALL, ALIGN_RANDOM_X, ALIGN_RANDOM_Y, ALIGN_RANDOM_Z):
        import random
        rng = random.Random(seed * 1000003 + slot_index + 7)
        if align_mode == ALIGN_RANDOM_ALL:
            rx = rng.uniform(-math.pi, math.pi)
            ry = rng.uniform(-math.pi, math.pi)
            rz = rng.uniform(-math.pi, math.pi)
            R = (Matrix.Rotation(rx, 4, 'X') @
                 Matrix.Rotation(ry, 4, 'Y') @
                 Matrix.Rotation(rz, 4, 'Z'))
        else:
            axis_letter = {ALIGN_RANDOM_X: 'X',
                           ALIGN_RANDOM_Y: 'Y',
                           ALIGN_RANDOM_Z: 'Z'}[align_mode]
            R = Matrix.Rotation(rng.uniform(-math.pi, math.pi), 4, axis_letter)
        return T_to @ R @ T_from @ base_mw

    # Direction-based: pick target direction.
    if align_mode == ALIGN_OUTWARD:
        target = clone_pos - pivot_co
    elif align_mode == ALIGN_INWARD:
        target = pivot_co - clone_pos
    elif align_mode == ALIGN_FOLLOW and follow_target is not None:
        target = follow_target - clone_pos
    elif align_mode == ALIGN_FOLLOW_REV and follow_target is not None:
        target = clone_pos - follow_target
    else:
        return base_mw  # missing data — fall back to ORIGINAL

    target = target - axis_vec * target.dot(axis_vec)
    if target.length < 1e-6:
        return base_mw
    target.normalize()

    src_x = base_mw.to_3x3() @ Vector((1, 0, 0))
    src_x = src_x - axis_vec * src_x.dot(axis_vec)
    if src_x.length < 1e-6:
        return base_mw
    src_x.normalize()

    ang = _signed_angle_around(src_x, target, axis_vec)
    R = Matrix.Rotation(ang, 4, axis_vec)
    return T_to @ R @ T_from @ base_mw


def _clone_step_deg(op):
    """Angle (radians) between consecutive clones for the current mode."""
    try:
        axis_vec = _resolve_axis(op, bpy.context)
    except AttributeError:
        return 0.0
    _, step, _ = _compute_arc(op, axis_vec)
    return step


def _iter_clone_angles(start_offset, step, n_clones, start_index=1):
    """Yield (clone_index, angle) for each clone. Index 0 reserved for source position."""
    for i in range(start_index, n_clones + 1):
        yield i, start_offset + i * step


def _natural_radius(op):
    """Distance from pivot to the anchor (active object). The preview ring uses
    this so it visibly passes through the active — and through every clone slot,
    since slots are produced by rotating the anchor around the pivot."""
    target = getattr(op, "active_obj", None)
    if target is None and op.subtree_data:
        try:
            target = op.subtree_data[0][0][0]
        except IndexError:
            target = None
    if target is None:
        return 0.0
    try:
        return (target.matrix_world.translation - op.pivot_co).length
    except ReferenceError:
        return 0.0


def _effective_radius(op):
    """Active array radius: override if set, else the natural source distance."""
    if op.radius_override is not None:
        return op.radius_override
    r = _natural_radius(op)
    return r if r > 1e-6 else 1.0


def _effective_source_mw(source_mw, pivot_co, axis_vec, radius_override):
    """If radius_override is set, scale (or place) the source's radial offset in
    the rotation plane so its in-plane distance from pivot equals the override.
    Axial component is preserved. When the source coincides with the pivot the
    direction is picked from the rotation frame's `right` so the slot has a
    deterministic anchor and clones still appear."""
    if radius_override is None:
        return source_mw
    offset = source_mw.translation - pivot_co
    axial = axis_vec * offset.dot(axis_vec)
    radial = offset - axial
    cur = radial.length
    if cur < 1e-6:
        right, _ = _arc_frame(axis_vec)
        scaled = right * radius_override
    else:
        scaled = radial * (radius_override / cur)
    new_translation = pivot_co + axial + scaled
    M = source_mw.copy()
    M.translation = new_translation
    return M


def _mouse_on_rot_plane(context, event, pivot_co, axis_vec):
    """Project mouse onto the rotation plane (axis-perpendicular through pivot). None if parallel."""
    from bpy_extras.view3d_utils import region_2d_to_origin_3d, region_2d_to_vector_3d
    region = context.region
    rv3d = context.region_data
    if region is None or rv3d is None:
        return None
    mouse = Vector((event.mouse_region_x, event.mouse_region_y))
    origin = region_2d_to_origin_3d(region, rv3d, mouse)
    direction = region_2d_to_vector_3d(region, rv3d, mouse)
    denom = direction.dot(axis_vec)
    if abs(denom) < 1e-6:
        return None
    t = (pivot_co - origin).dot(axis_vec) / denom
    return origin + direction * t


def _mouse_radius_in_plane(context, event, pivot_co, axis_vec):
    """In-plane distance from pivot to where the mouse-ray hits the rotation plane."""
    hit = _mouse_on_rot_plane(context, event, pivot_co, axis_vec)
    if hit is None:
        return None
    offset = hit - pivot_co
    radial = offset - axis_vec * offset.dot(axis_vec)
    return radial.length


# --- Preview (POST_VIEW) -------------------------------------------------

def _mesh_edge_segments_world(obj_mw, mesh):
    """Return list of (Vector, Vector) world-space edge segments for a mesh."""
    verts_world = [obj_mw @ v.co for v in mesh.vertices]
    return [(verts_world[e.vertices[0]], verts_world[e.vertices[1]]) for e in mesh.edges]


def _mesh_face_tris_world(obj_mw, mesh):
    """Use Blender's precomputed loop_triangles — handles quads and n-gons,
    including concave shapes, correctly. Falls back silently if data is empty."""
    if not mesh.loop_triangles:
        try:
            mesh.calc_loop_triangles()
        except RuntimeError:
            return []
    verts_world = [obj_mw @ v.co for v in mesh.vertices]
    loops = mesh.loops
    tris = []
    for lt in mesh.loop_triangles:
        a, b, cc = lt.loops
        tris.append(verts_world[loops[a].vertex_index])
        tris.append(verts_world[loops[b].vertex_index])
        tris.append(verts_world[loops[cc].vertex_index])
    return tris


def _arc_frame(axis_vec):
    """Return (right, fwd) orthonormal basis in the plane perpendicular to axis_vec."""
    up = axis_vec
    right = Vector((1, 0, 0)) if abs(up.x) < 0.9 else Vector((0, 1, 0))
    right = (right - up * right.dot(up)).normalized()
    fwd = up.cross(right)
    return right, fwd


def _arc_two_point_geometry(op, axis_vec):
    """For ARC_CURSOR: arc through active (A) and cursor (B), parameterized by
    `op.arc_apex_h_signed` — signed distance along AB's perpendicular bisector
    from the midpoint to the **arc apex** (deepest point on the curve).

    * |h| < R_min ⇒ minor arc, center on the opposite side of AB from apex.
    * |h| = R_min ⇒ semicircle (R = R_min, center at midpoint).
    * |h| > R_min ⇒ major arc, center on the SAME side as apex; the arc keeps
      growing toward a full circle as |h| → ∞.

    Returns (center_world, radius, start_angle, sweep) or None if degenerate."""
    A_obj = getattr(op, "active_obj", None)
    if A_obj is None:
        return None
    try:
        A = A_obj.matrix_world.translation.copy()
    except ReferenceError:
        return None
    B = bpy.context.scene.cursor.location.copy()

    AB = B - A
    ab_planar = AB - axis_vec * AB.dot(axis_vec)
    ab_len = ab_planar.length
    if ab_len < 1e-6:
        return None

    midpoint = (A + B) * 0.5
    r_min = ab_len * 0.5
    perp = axis_vec.cross(ab_planar).normalized()

    h_signed = getattr(op, "arc_apex_h_signed", None)
    if h_signed is None:
        h_signed = r_min   # default: semicircle bulging on +perp side
    h = abs(h_signed)
    if h < 1e-4:
        h = 1e-4
    asign = 1.0 if h_signed >= 0.0 else -1.0
    is_major = h > r_min

    if is_major:
        R = (h * h + r_min * r_min) / (2.0 * h)
        d = (h * h - r_min * r_min) / (2.0 * h)
        center = midpoint + perp * (asign * d)
    else:
        d = (r_min * r_min - h * h) / (2.0 * h)
        R = math.sqrt(d * d + r_min * r_min)
        center = midpoint - perp * (asign * d)

    right, fwd = _arc_frame(axis_vec)

    def _angle_of(p):
        v = p - center
        v_planar = v - axis_vec * v.dot(axis_vec)
        return math.atan2(v_planar.dot(fwd), v_planar.dot(right))

    start_angle = _angle_of(A)
    end_angle = _angle_of(B)
    sweep = end_angle - start_angle
    while sweep > math.pi:
        sweep -= 2 * math.pi
    while sweep <= -math.pi:
        sweep += 2 * math.pi
    if is_major:
        # Major arc — go the long way around instead of the signed-shortest path.
        sweep = sweep - math.copysign(2 * math.pi, sweep) if sweep != 0 else 2 * math.pi
    return center, R, start_angle, sweep


def _arc_params(op, axis_vec):
    """Unified arc parameters: (center_world, radius, start_angle, sweep).
    - ARC_FULL/180°/90°/45°: center = pivot, radius = effective_radius,
      sweep = fixed constant, start = angle of active (or 0 for ARC_FULL).
    - ARC_CURSOR: arc passes through active and cursor; center, radius and sweep
      derived. None if A and B coincide."""
    if op.arc_mode == ARC_CURSOR:
        return _arc_two_point_geometry(op, axis_vec)
    center = op.pivot_co.copy()
    R = _effective_radius(op)
    start = _arc_effective_start(op, axis_vec)
    if op.arc_mode == ARC_FULL:
        sweep = 2 * math.pi
    else:
        sweep = _ARC_FIXED_SWEEPS.get(op.arc_mode, 0.0)
    return center, R, start, sweep


def _arc_endpoint_world(op, axis_vec):
    """World position of the arc-end marker (last slot). None for ARC_FULL."""
    if op.arc_mode == ARC_FULL:
        return None
    params = _arc_params(op, axis_vec)
    if params is None:
        return None
    center, R, start, sweep = params
    end_angle = start + sweep
    right, fwd = _arc_frame(axis_vec)
    return center + (right * math.cos(end_angle) + fwd * math.sin(end_angle)) * R


def _pool_fill_iter(op, axis_vec):
    """For pool_fill: yield (delta_matrix, subtree, slot_pos) per ring slot.
    Slot i takes subtree[i] if i < N, else a deterministic random pick from the pool.
    Subtree is rotated/translated so its root lands on the slot position at radius R."""
    import random
    N = len(op.subtree_data)
    if N == 0:
        return
    params = _arc_params(op, axis_vec)
    if params is None:
        return
    arc_center, radius, arc_start, arc_sweep = params
    n_slots = max(1, int(op.count))
    if op.arc_mode == ARC_FULL:
        step = 2 * math.pi / n_slots
    else:
        if n_slots > 1:
            step = arc_sweep / (n_slots - 1) if op.end_inclusive else arc_sweep / n_slots
        else:
            step = 0.0
    rng = random.Random(op._pool_seed)
    if radius < 1e-6:
        radius = 1.0
    right, fwd = _arc_frame(axis_vec)

    # First sweep — compute every slot's target position so FOLLOW knows neighbours.
    slot_positions = []
    for s in range(n_slots):
        ang = arc_start + s * step
        slot_positions.append(arc_center + (right * math.cos(ang) + fwd * math.sin(ang)) * radius)

    def _follow_target(i):
        if i + 1 < n_slots:
            return slot_positions[i + 1]
        if op.arc_mode == ARC_FULL:
            return slot_positions[0]
        if i - 1 >= 0:
            return slot_positions[i] + (slot_positions[i] - slot_positions[i - 1])
        return None

    for s in range(n_slots):
        sub_idx = s if s < N else rng.randrange(N)
        subtree = op.subtree_data[sub_idx]
        try:
            src_root = subtree[0][0]
            src_mw = src_root.matrix_world.copy()
        except ReferenceError:
            continue
        target_pos = slot_positions[s]
        # base_mw — source orientation at the slot position (pool placement is
        # per-source so no group-style pivot rotation here).
        base_mw = src_mw.copy()
        base_mw.translation = target_pos
        new_mw = _aligned_clone_mw(op.align_mode, arc_center, axis_vec,
                                   base_mw, op._pool_seed, s,
                                   follow_target=_follow_target(s))
        delta = new_mw @ src_mw.inverted()
        yield delta, subtree, target_pos


def _group_anchor_co(op):
    """Anchor for the rigid group rotation. In SOURCE_GROUP we anchor on the
    active object so all other selected objects keep their offsets relative to
    the active's copy. Otherwise fall back to the centroid of source origins."""
    anchor = getattr(op, "anchor_obj", None)
    if anchor is not None:
        try:
            return anchor.matrix_world.translation.copy()
        except ReferenceError:
            pass
    pts = []
    for sub in op.subtree_data:
        try:
            pts.append(sub[0][0].matrix_world.translation.copy())
        except ReferenceError:
            continue
    if not pts:
        return op.pivot_co.copy()
    acc = Vector((0.0, 0.0, 0.0))
    for p in pts:
        acc += p
    return acc / len(pts)


def _build_ghost_segments(op, context):
    """Build the list of edge segments (in world space) for every predicted clone."""
    valid = []
    for sub in op.subtree_data:
        try:
            sub[0][0].matrix_world
            valid.append(sub)
        except ReferenceError:
            continue
    op.subtree_data = valid

    axis_vec = _resolve_axis(op, context)
    ang_total, step, n_clones = _compute_arc(op, axis_vec)

    segs = []
    tris = []
    crosses = []

    # After Match, the sources sit on the arc themselves — no preview clones
    # so they don't visually pile on top of the snapped objects.
    if getattr(op, "match_active", False):
        return segs, tris, crosses, axis_vec, ang_total

    if op.arc_mode == ARC_FULL and op.skip_first:
        start_index = 0
    else:
        start_index = 1

    subtrees = op.subtree_data
    if not subtrees:
        return segs, tris, crosses, axis_vec, ang_total

    if op.source_mode == SOURCE_POOL:
        for delta, subtree, slot_pos in _pool_fill_iter(op, axis_vec):
            crosses.append(slot_pos.copy())
            for child_obj, _rel in subtree:
                child_clone_mw = delta @ child_obj.matrix_world
                if child_obj.type == "MESH" and child_obj.data is not None:
                    for a, b in _mesh_edge_segments_world(child_clone_mw, child_obj.data):
                        segs.append((a, b))
                    tris.extend(_mesh_face_tris_world(child_clone_mw, child_obj.data))
                else:
                    crosses.append(child_clone_mw.translation.copy())
        return segs, tris, crosses, axis_vec, ang_total

    # Build slot positions from unified arc params (handles ARC_FULL/ANGLE/CURSOR).
    params = _arc_params(op, axis_vec)
    if params is None:
        return segs, tris, crosses, axis_vec, ang_total
    arc_center, arc_R, arc_start, arc_sweep = params
    anchor_actual = (op.anchor_obj.matrix_world.copy()
                     if op.anchor_obj is not None else Matrix.Translation(_group_anchor_co(op)))

    n_total = max(2, int(op.count))
    if op.arc_mode == ARC_FULL:
        slot_step = (2 * math.pi) / n_total
    else:
        if n_total > 1:
            slot_step = arc_sweep / (n_total - 1) if op.end_inclusive else arc_sweep / n_total
        else:
            slot_step = 0.0
    right, fwd = _arc_frame(axis_vec)
    all_positions = []
    for ci in range(n_total):
        a = arc_start + ci * slot_step
        all_positions.append(arc_center + (right * math.cos(a) + fwd * math.sin(a)) * arc_R)

    wraps = (op.arc_mode == ARC_FULL)
    # alias for downstream rotation step
    step = slot_step

    def _follow_target(i):
        if i + 1 < n_total:
            return all_positions[i + 1]
        if wraps:
            return all_positions[0]
        if i - 1 >= 0:
            return all_positions[i] + (all_positions[i] - all_positions[i - 1])
        return None

    # Drawn indices: skip_first OFF leaves source visible at slot 0, so we draw
    # clones from slot 1 onward. skip_first ON also clones slot 0.
    for ci in range(start_index, n_total):
        slot_pos = all_positions[ci]
        if op.align_mode == ALIGN_NONE:
            # ORIGINAL — spawn the source at the slot with NO rotation at all.
            base_mw = anchor_actual.copy()
            base_mw.translation = slot_pos
        else:
            R_step = Matrix.Rotation(ci * step, 4, axis_vec).to_3x3()
            rotated_3x3 = R_step @ anchor_actual.to_3x3()
            base_mw = rotated_3x3.to_4x4()
            base_mw.translation = slot_pos
        M_anchor_final = _aligned_clone_mw(
            op.align_mode, arc_center, axis_vec, base_mw,
            op._pool_seed, ci, follow_target=_follow_target(ci))
        delta = M_anchor_final @ anchor_actual.inverted()
        crosses.append(slot_pos.copy())
        for subtree in subtrees:
            for child_obj, _rel in subtree:
                child_clone_mw = delta @ child_obj.matrix_world
                if child_obj.type == "MESH" and child_obj.data is not None:
                    for a, b in _mesh_edge_segments_world(child_clone_mw, child_obj.data):
                        segs.append((a, b))
                    tris.extend(_mesh_face_tris_world(child_clone_mw, child_obj.data))
                else:
                    crosses.append(child_clone_mw.translation.copy())

    return segs, tris, crosses, axis_vec, ang_total


def _draw_preview_3d(op, context):
    """POST_VIEW draw: ghost faces + wires + axis line + arc/circle + pivot."""
    from ..ui.draw import primitives as iops_draw
    from ..ui.draw import draw_scope

    if op._dirty or getattr(op, "_ghost_cache", None) is None:
        op._ghost_cache = _build_ghost_segments(op, context)
        op._dirty = False
    segs, tris, crosses, axis_vec, ang_total = op._ghost_cache

    # Two-pass transparent fill to avoid alpha-stacking when clones overlap:
    #   1. Depth pre-pass — write only the depth buffer, no color, so the
    #      nearest front-face of every clone owns its pixels.
    #   2. Color pass with depth=EQUAL — each pixel gets shaded exactly once
    #      by the front-most clone; behind clones fail the equality test.
    if tris:
        with draw_scope(blend="NONE", depth="LESS_EQUAL",
                        face_culling="BACK", depth_mask=True,
                        color_mask=(False, False, False, False)):
            iops_draw.tris(tris, role=Role.GHOST_DEFAULT, context=context)
        with draw_scope(blend="ALPHA", depth="EQUAL",
                        face_culling="BACK", depth_mask=False):
            iops_draw.tris(tris, role=Role.GHOST_DEFAULT, context=context)
    if segs:
        flat = []
        for a, b in segs:
            flat.append(a)
            flat.append(b)
        with draw_scope(blend="ALPHA", depth="LESS_EQUAL"):
            iops_draw.edges_3d(flat, role=Role.GHOST_EDGE, context=context)

    if crosses:
        iops_draw.points(crosses, role=Role.PREVIEW_POINT, context=context)

    # Visualization uses the unified arc params so ARC_CURSOR draws around the
    # derived center, not the user pivot.
    params = _arc_params(op, axis_vec)
    if params is not None:
        center, radius, start_a, sweep = params
    else:
        center = op.pivot_co.copy()
        radius = _effective_radius(op)
        start_a = 0.0
        sweep = 2 * math.pi if op.arc_mode == ARC_FULL else 0.0
    if radius < 1e-3:
        radius = 1.0

    a_half = axis_vec * (radius * 2.0)
    iops_draw.edges_3d([center - a_half, center + a_half],
                       role=Role.ACTIVE_LINE, context=context)

    if radius > 1e-3:
        steps = 64
        right, fwd = _arc_frame(axis_vec)
        ring_sweep = sweep if op.arc_mode != ARC_FULL else 2 * math.pi
        ring = []
        for i in range(steps + 1):
            t = i / steps
            ang = start_a + t * ring_sweep
            p = center + (right * math.cos(ang) + fwd * math.sin(ang)) * radius
            ring.append(p)
        pairs = []
        for i in range(len(ring) - 1):
            pairs.append(ring[i])
            pairs.append(ring[i + 1])
        iops_draw.edges_3d(pairs, role=Role.PREVIEW_LINE, context=context)

    # Marker at the derived arc center.
    iops_draw.points([center], role=Role.PIVOT, context=context)

    # arc end marker (draggable; absent in FULL_360 or two-points-without-target)
    end_pt = _arc_endpoint_world(op, axis_vec)
    if end_pt is not None:
        iops_draw.points([end_pt], role=Role.ACTIVE_POINT, context=context)


class IOPS_OT_Object_Radial_Array(bpy.types.Operator):
    """Radially array selected object hierarchies around a pivot"""

    bl_idname = "iops.object_radial_array"
    bl_label = "OBJECT: Radial Array"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return (
            context.mode == "OBJECT"
            and context.area is not None
            and context.area.type == "VIEW_3D"
            and context.active_object is not None
        )

    def invoke(self, context, event):
        sel = list(context.selected_objects)
        active = context.active_object
        if not sel or active is None:
            self.report({"WARNING"}, "Select at least one object")
            return {"CANCELLED"}

        # --- mode defaults ---
        # Default to 3D-cursor pivot so every selected object (including active)
        # is part of the rotated group and keeps its position relative to the rest.
        # Press P during modal to cycle to ACTIVE-as-pivot or LAST_SELECTED-as-pivot.
        self.pivot_mode  = PIVOT_CURSOR
        self.clone_mode  = CLONE_DUP
        self.arc_mode    = ARC_FULL
        self.axis_mode   = AXIS_GLOBAL_Z
        self.align_mode  = ALIGN_NONE
        self.skip_first  = False
        self.end_inclusive = True
        self.count = 6
        self.pending_normal_pick = False
        self._cached_axis_vec = Vector((0, 0, 1))
        self.radius_override = None       # None = use natural source distance
        self.radius_drag_active = False
        self.arc_center_drag_active = False   # ARC_CURSOR: drag the derived center
        self.arc_apex_h_signed = None         # ARC_CURSOR: signed apex distance on AB's perpendicular bisector
        self.match_active = False
        self._match_saved = None          # snapshot used to un-apply Match
        self.source_mode = SOURCE_GROUP   # U cycles ACTIVE / HIERARCHY / GROUP / POOL
        self.anchor_obj = None            # the active object when source_mode == GROUP
        self.active_obj = context.active_object  # always tracked; arc start sits at this object
        self._pool_seed = 12345
        self._dirty = True

        pivot_co, pivot_obj, _legacy_sources, _et = _resolve_selection(context, self.pivot_mode)
        self.pivot_co  = pivot_co
        self.pivot_obj = pivot_obj

        self._rebuild_sources(context)
        if not self.subtree_data:
            self.report({"WARNING"}, "Select at least one source object")
            return {"CANCELLED"}

        self._hud = _build_hud(context)
        self._hud.add_param(HUDParam("Pivot",       lambda: self.pivot_mode, "str"))
        self._hud.add_param(HUDParam("Clone",       lambda: self.clone_mode, "str"))
        self._hud.add_param(HUDParam("Arc",         lambda: self.arc_mode, "str"))
        self._hud.add_param(HUDParam("Axis",        lambda: self.axis_mode, "str"))
        self._hud.add_param(HUDParam("Count",       lambda: self.count, "int"))
        self._hud.add_param(HUDParam("Radius",      lambda: _effective_radius(self), "float", fmt="{:.3f}"))
        self._hud.add_param(HUDParam("Step",        lambda: math.degrees(_clone_step_deg(self)), "float", fmt="{:.2f}°"))
        self._hud.add_param(HUDParam("Apex h",      lambda: (self.arc_apex_h_signed if self.arc_apex_h_signed is not None else 0.0),
                                     "float", fmt="{:.3f}",
                                     active_getter=lambda: self.arc_mode == ARC_CURSOR))
        self._hud.add_param(HUDParam("Alignment",   lambda: self.align_mode, "str"))
        self._hud.add_param(HUDParam("Skip first",   lambda: self.skip_first, "bool"))
        self._hud.add_param(HUDParam("End inclusive", lambda: self.end_inclusive, "bool",
                                     active_getter=lambda: self.arc_mode != ARC_FULL))
        self._hud.add_param(HUDParam("Match",       lambda: self.match_active, "bool"))
        self._hud.add_param(HUDParam("Source",      lambda: self.source_mode, "str"))
        self._help = _build_help(context)
        self._last_event = capture_event(event, None)
        self._handle = safe_handler_add(
            bpy.types.SpaceView3D, _draw_callback, (self, context),
            "WINDOW", "POST_PIXEL", tick=True,
        )
        self._handle_3d = safe_handler_add(
            bpy.types.SpaceView3D, _draw_preview_3d, (self, context),
            "WINDOW", "POST_VIEW", tick=False,
        )
        context.window_manager.modal_handler_add(self)
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        context.area.tag_redraw()
        self._last_event = capture_event(event, getattr(self, "_last_event", None))

        # Live re-snap when Match is on so parameter tweaks stay interactive.
        if self.match_active and self._dirty:
            self._snap_to_arc(context)

        try:
            theme_prefs = context.preferences.addons["InteractionOps"].preferences.iops_theme
        except (KeyError, AttributeError):
            theme_prefs = None
        if theme_prefs is not None:
            for ov in (self._help, self._hud):
                if ov is None:
                    continue
                if ov.handle_drag_event(context, event, theme_prefs):
                    return {"RUNNING_MODAL"}
            if self._help.handle_toggle_event(event, theme_prefs):
                return {"RUNNING_MODAL"}
            if self._hud.handle_param_toggle_event(event, theme_prefs):
                return {"RUNNING_MODAL"}

        # Navigation: MMB drag, plain wheel, trackpad — always pass through.
        # Ctrl+wheel is used for count (handled below).
        if event.type == "MIDDLEMOUSE":
            return {"PASS_THROUGH"}
        if event.type in {"WHEELUPMOUSE", "WHEELDOWNMOUSE"} and not event.ctrl:
            return {"PASS_THROUGH"}
        if event.type in {"TRACKPADPAN", "TRACKPADZOOM"}:
            return {"PASS_THROUGH"}

        # --- mode cycles (QWER cluster) ---
        if event.type == "Q" and event.value == "PRESS":
            self.pivot_mode = _cycle(self.pivot_mode, PIVOT_CYCLE)
            pivot_co, pivot_obj, _legacy_sources, _et = _resolve_selection(context, self.pivot_mode)
            self.pivot_co = pivot_co
            self.pivot_obj = pivot_obj
            self._rebuild_sources(context)
            self._dirty = True
            return {"RUNNING_MODAL"}

        if event.type == "D" and event.value == "PRESS":
            self.clone_mode = _cycle(self.clone_mode, CLONE_CYCLE)
            return {"RUNNING_MODAL"}

        if event.type == "W" and event.value == "PRESS":
            self.arc_mode = _cycle(self.arc_mode, ARC_CYCLE)
            self._dirty = True
            return {"RUNNING_MODAL"}

        # --- reset everything to defaults ---
        if event.type == "B" and event.value == "PRESS":
            self._reset_defaults()
            self.report({"INFO"}, "Radial Array reset to defaults")
            return {"RUNNING_MODAL"}

        # --- match radius / count (and arc) from current source origins (toggle) ---
        if event.type == "M" and event.value == "PRESS":
            self._toggle_match(context)
            return {"RUNNING_MODAL"}

        # --- source mode cycle (Active / Hierarchy / Group / Pool) ---
        if event.type == "U" and event.value == "PRESS":
            self.source_mode = _cycle(self.source_mode, SOURCE_CYCLE)
            self._rebuild_sources(context)
            self._dirty = True
            self.report({"INFO"}, f"Source: {self.source_mode}")
            return {"RUNNING_MODAL"}

        # --- reroll random seed for SOURCE_POOL extras ---
        if event.type == "K" and event.value == "PRESS":
            if self.source_mode == SOURCE_POOL:
                import time
                self._pool_seed = int(time.time() * 1000) & 0xFFFFFF
                self._dirty = True
                self.report({"INFO"}, "Pool seed re-rolled")
            return {"RUNNING_MODAL"}

        # --- axis ---
        if event.type in {"X", "Y", "Z"} and event.value == "PRESS":
            self.axis_mode = {"X": AXIS_GLOBAL_X, "Y": AXIS_GLOBAL_Y, "Z": AXIS_GLOBAL_Z}[event.type]
            self.pending_normal_pick = False
            self._dirty = True
            return {"RUNNING_MODAL"}

        if event.type == "C" and event.value == "PRESS":
            mapping = {
                AXIS_GLOBAL_X: AXIS_LOCAL_X, AXIS_GLOBAL_Y: AXIS_LOCAL_Y, AXIS_GLOBAL_Z: AXIS_LOCAL_Z,
                AXIS_LOCAL_X:  AXIS_GLOBAL_X, AXIS_LOCAL_Y: AXIS_GLOBAL_Y, AXIS_LOCAL_Z: AXIS_GLOBAL_Z,
            }
            self.axis_mode = mapping.get(self.axis_mode, AXIS_GLOBAL_Z)
            self._dirty = True
            return {"RUNNING_MODAL"}

        if event.type == "V" and event.value == "PRESS":
            self.axis_mode = AXIS_VIEW
            self.pending_normal_pick = False
            self._dirty = True
            return {"RUNNING_MODAL"}

        if event.type == "T" and event.value == "PRESS":
            self.pending_normal_pick = True
            self.report({"INFO"}, "Click a face to set rotation axis from its normal")
            return {"RUNNING_MODAL"}

        # --- normal pick via LMB while pending (MUST come before apply LMB) ---
        if self.pending_normal_pick and event.type == "LEFTMOUSE" and event.value == "PRESS":
            region = context.region
            rv3d = context.region_data
            mouse = Vector((event.mouse_region_x, event.mouse_region_y))
            from bpy_extras.view3d_utils import region_2d_to_origin_3d, region_2d_to_vector_3d
            origin = region_2d_to_origin_3d(region, rv3d, mouse)
            direction = region_2d_to_vector_3d(region, rv3d, mouse)
            depsgraph = context.evaluated_depsgraph_get()
            hit, loc, normal, idx, obj, mat = context.scene.ray_cast(depsgraph, origin, direction)
            if hit:
                self._cached_axis_vec = normal.normalized()
                self.axis_mode = AXIS_NORMAL
                self._dirty = True
                self.report({"INFO"}, "Axis set from face normal")
            else:
                self.report({"WARNING"}, "No face hit")
            self.pending_normal_pick = False
            return {"RUNNING_MODAL"}

        # --- toggles ---
        if event.type == "R" and event.value == "PRESS":
            self.align_mode = _cycle(self.align_mode, ALIGN_CYCLE)
            self._dirty = True
            self.report({"INFO"}, f"Alignment: {self.align_mode}")
            return {"RUNNING_MODAL"}

        if event.type == "F" and event.value == "PRESS":
            self.skip_first = not self.skip_first
            self._dirty = True
            return {"RUNNING_MODAL"}

        if event.type == "E" and event.value == "PRESS":
            self.end_inclusive = not self.end_inclusive
            self._dirty = True
            return {"RUNNING_MODAL"}

        # --- count ---
        if event.type in {"NUMPAD_PLUS", "EQUAL"} and event.value == "PRESS":
            self.count = min(1024, self.count + 1)
            self._dirty = True
            return {"RUNNING_MODAL"}
        if event.type in {"NUMPAD_MINUS", "MINUS"} and event.value == "PRESS":
            self.count = max(2, self.count - 1)
            self._dirty = True
            return {"RUNNING_MODAL"}
        if event.type in {"WHEELUPMOUSE", "WHEELDOWNMOUSE"} and event.value == "PRESS" and event.ctrl:
            step = 10 if event.shift else 1
            sign = 1 if event.type == "WHEELUPMOUSE" else -1
            self.count = max(2, min(1024, self.count + sign * step))
            self._dirty = True
            return {"RUNNING_MODAL"}

        # --- flip arc apex side (ARC_CURSOR only) ---
        if event.type == "I" and event.value == "PRESS":
            if self.arc_mode == ARC_CURSOR:
                if self.arc_apex_h_signed is not None:
                    self.arc_apex_h_signed = -self.arc_apex_h_signed
                else:
                    # default semicircle on +perp side; flipped → semicircle on −perp
                    axis_vec = _resolve_axis(self, context)
                    params = _arc_two_point_geometry(self, axis_vec)
                    if params is not None:
                        # Use r_min derived from A/B
                        active = getattr(self, "active_obj", None)
                        if active is not None:
                            try:
                                A = active.matrix_world.translation
                                B = bpy.context.scene.cursor.location
                                ab_planar = (B - A) - axis_vec * (B - A).dot(axis_vec)
                                self.arc_apex_h_signed = -(ab_planar.length * 0.5)
                            except ReferenceError:
                                pass
                self._dirty = True
                self.report({"INFO"}, "Arc apex flipped")
            return {"RUNNING_MODAL"}

        # --- LMB PRESS: two controllers in ARC_CURSOR (center marker / arc curve)
        #               and one in fixed-angle arcs (ring = radius).
        if event.type == "LEFTMOUSE" and event.value == "PRESS":
            axis_vec = _resolve_axis(self, context)
            params = _arc_params(self, axis_vec)
            arc_center = params[0] if params is not None else self.pivot_co
            arc_R = params[1] if params is not None else _effective_radius(self)
            hit = _mouse_on_rot_plane(context, event, arc_center, axis_vec)
            if hit is None:
                return {"RUNNING_MODAL"}
            radial_world = hit - arc_center
            radial = radial_world - axis_vec * radial_world.dot(axis_vec)
            r_mouse = radial.length
            on_center = (hit - arc_center).length < max(0.18 * arc_R, 0.3)
            on_ring = abs(r_mouse - arc_R) < max(0.25 * arc_R, 0.4)

            if self.arc_mode == ARC_CURSOR:
                if on_center:
                    # Drag the center along AB's perpendicular bisector.
                    self.arc_center_drag_active = True
                    self._dirty = True
                    return {"RUNNING_MODAL"}
                if on_ring:
                    # Drag the arc curve — radius changes, center is recomputed
                    # from A, B and the new R. Snapshot the starting center so
                    # distance measurement stays stable across frames.
                    self.radius_drag_active = True
                    self._radius_drag_start_center = arc_center.copy()
                    self.radius_override = max(1e-4, r_mouse)
                    self._dirty = True
                    return {"RUNNING_MODAL"}
                return {"RUNNING_MODAL"}

            # Fixed-angle arcs (360/180/90/45): ring drag = direct radius change.
            if on_ring:
                self.radius_drag_active = True
                self._radius_drag_start_center = arc_center.copy()
                self.radius_override = max(1e-4, r_mouse)
                self._dirty = True
            return {"RUNNING_MODAL"}

        if self.radius_drag_active and event.type == "MOUSEMOVE":
            axis_vec = _resolve_axis(self, context)
            if self.arc_mode == ARC_CURSOR:
                # Mouse = desired arc apex. arc_apex_h_signed captures it
                # directly; the geometry function picks minor or major based
                # on |h| vs R_min, so dragging through R_min grows the arc
                # smoothly from minor → semicircle → major (toward full circle).
                active = getattr(self, "active_obj", None)
                if active is None:
                    return {"RUNNING_MODAL"}
                try:
                    A = active.matrix_world.translation.copy()
                except ReferenceError:
                    return {"RUNNING_MODAL"}
                B = bpy.context.scene.cursor.location.copy()
                AB = B - A
                ab_planar = AB - axis_vec * AB.dot(axis_vec)
                if ab_planar.length < 1e-6:
                    return {"RUNNING_MODAL"}
                midpoint = (A + B) * 0.5
                perp = axis_vec.cross(ab_planar).normalized()
                hit = _mouse_on_rot_plane(context, event, midpoint, axis_vec)
                if hit is None:
                    return {"RUNNING_MODAL"}
                self.arc_apex_h_signed = (hit - midpoint).dot(perp)
                self._dirty = True
                return {"RUNNING_MODAL"}
            # Fixed-angle arcs: snapshot-center distance keeps R reading stable.
            ref = getattr(self, "_radius_drag_start_center", None)
            if ref is None:
                params = _arc_params(self, axis_vec)
                ref = params[0] if params is not None else self.pivot_co
            r_mouse = _mouse_radius_in_plane(context, event, ref, axis_vec)
            if r_mouse is not None:
                self.radius_override = max(1e-4, r_mouse)
                self._dirty = True
            return {"RUNNING_MODAL"}

        if self.arc_center_drag_active and event.type == "MOUSEMOVE":
            axis_vec = _resolve_axis(self, context)
            active = getattr(self, "active_obj", None)
            if active is None:
                return {"RUNNING_MODAL"}
            try:
                A = active.matrix_world.translation.copy()
            except ReferenceError:
                return {"RUNNING_MODAL"}
            B = bpy.context.scene.cursor.location.copy()
            AB = B - A
            ab_planar = AB - axis_vec * AB.dot(axis_vec)
            ab_len = ab_planar.length
            if ab_len < 1e-6:
                return {"RUNNING_MODAL"}
            midpoint = (A + B) * 0.5
            perp = axis_vec.cross(ab_planar).normalized()
            hit = _mouse_on_rot_plane(context, event, midpoint, axis_vec)
            if hit is None:
                return {"RUNNING_MODAL"}
            d_signed = (hit - midpoint).dot(perp)
            r_min = ab_len * 0.5
            d = abs(d_signed)
            R = math.sqrt(d * d + r_min * r_min)
            # Continuity: keep the arc on whichever side it was on, swap minor↔major as
            # the center crosses AB so the arc keeps growing instead of flipping.
            cur_asign = 1.0
            if self.arc_apex_h_signed is not None and self.arc_apex_h_signed != 0.0:
                cur_asign = 1.0 if self.arc_apex_h_signed > 0 else -1.0
            csign = 1.0 if d_signed >= 0 else -1.0
            if csign == cur_asign:
                # center same side as arc apex → major arc, apex = R + d away.
                self.arc_apex_h_signed = cur_asign * (R + d)
            else:
                # center opposite side from apex → minor arc, apex = R - d.
                self.arc_apex_h_signed = cur_asign * (R - d)
            self._dirty = True
            return {"RUNNING_MODAL"}

        if event.type == "LEFTMOUSE" and event.value == "RELEASE" \
                and (self.radius_drag_active or self.arc_center_drag_active):
            self.radius_drag_active = False
            self.arc_center_drag_active = False
            return {"RUNNING_MODAL"}

        if event.type in {"RET", "NUMPAD_ENTER", "SPACE"} and event.value == "PRESS":
            self._apply(context)
            self._cleanup()
            return {"FINISHED"}

        if self.pending_normal_pick and event.type == "ESC" and event.value == "PRESS":
            self.pending_normal_pick = False
            self.report({"INFO"}, "Normal pick cancelled")
            return {"RUNNING_MODAL"}

        if event.type in {"ESC", "RIGHTMOUSE"} and event.value == "PRESS":
            self._cleanup()
            return {"CANCELLED"}

        return {"RUNNING_MODAL"}

    def _rebuild_sources(self, context):
        """Resolve source roots + subtree snapshots according to current source_mode.
        Updates self.subtree_data, self.sources, self.anchor_obj."""
        roots, anchor = _resolve_source_roots(context, self.source_mode)
        include_children = self.source_mode in (SOURCE_HIERARCHY, SOURCE_GROUP, SOURCE_POOL)
        self.subtree_data = _build_subtree_data(roots, include_children)
        self.sources = roots
        self.anchor_obj = anchor

    def _toggle_match(self, context):
        """Toggle Match. First press snapshots original matrices and snaps to
        the arc. Second press restores those originals. While active, parameter
        changes trigger live re-snap via `_snap_to_arc`."""
        if self.match_active and self._match_saved is not None:
            for obj, mw in self._match_saved.items():
                try:
                    obj.matrix_world = mw
                except ReferenceError:
                    pass
            self._match_saved = None
            self.match_active = False
            self._dirty = True
            self.report({"INFO"}, "Match undone")
            return

        # Snapshot originals for every root + child once.
        saved = {}
        for sub in self.subtree_data:
            for child_obj, _rel in sub:
                try:
                    saved[child_obj] = child_obj.matrix_world.copy()
                except ReferenceError:
                    pass
        if not saved:
            self.report({"WARNING"}, "Nothing to snap")
            return
        self._match_saved = saved
        self.match_active = True
        n = self._snap_to_arc(context)
        if n == 0:
            # snap failed; revert match state
            self._match_saved = None
            self.match_active = False
            self.report({"WARNING"}, "Cannot match — arc geometry undefined")
            return
        self._dirty = True
        self.report({"INFO"}, f"Snapped {n} sources to nearest arc slot")

    def _snap_to_arc(self, context):
        """Move every source root from its ORIGINAL matrix (in `_match_saved`)
        to the nearest slot of the current arc/ring, applying current alignment.
        Children of each subtree move rigidly with their root. Returns the
        number of subtrees actually snapped."""
        if not self._match_saved:
            return 0
        axis_vec = _resolve_axis(self, context)
        params = _arc_params(self, axis_vec)
        if params is None:
            return 0
        arc_center, arc_R, arc_start, arc_sweep = params
        n_total = max(2, int(self.count))
        if self.arc_mode == ARC_FULL:
            slot_step = (2 * math.pi) / n_total
        else:
            slot_step = arc_sweep / (n_total - 1) if (n_total > 1 and self.end_inclusive) else arc_sweep / max(1, n_total)
        right, fwd = _arc_frame(axis_vec)
        slot_positions = []
        for ci in range(n_total):
            a = arc_start + ci * slot_step
            slot_positions.append(arc_center + (right * math.cos(a) + fwd * math.sin(a)) * arc_R)
        if not slot_positions:
            return 0

        def _follow_target_local(i):
            if i + 1 < n_total:
                return slot_positions[i + 1]
            if self.arc_mode == ARC_FULL:
                return slot_positions[0]
            if i - 1 >= 0:
                return slot_positions[i] + (slot_positions[i] - slot_positions[i - 1])
            return None

        snapped = 0
        for sub in self.subtree_data:
            try:
                root = sub[0][0]
            except IndexError:
                continue
            original_root_mw = self._match_saved.get(root)
            if original_root_mw is None:
                continue
            # nearest slot relative to ORIGINAL position so the assignment is
            # stable as the user tweaks params.
            best_i = min(range(len(slot_positions)),
                         key=lambda i: (slot_positions[i] - original_root_mw.translation).length)
            slot_pos = slot_positions[best_i]
            if self.align_mode == ALIGN_NONE:
                base_mw = original_root_mw.copy()
                base_mw.translation = slot_pos
            else:
                R_step = Matrix.Rotation(best_i * slot_step, 4, axis_vec).to_3x3()
                base_mw = (R_step @ original_root_mw.to_3x3()).to_4x4()
                base_mw.translation = slot_pos
            final_mw = _aligned_clone_mw(self.align_mode, arc_center, axis_vec,
                                         base_mw, self._pool_seed, best_i,
                                         follow_target=_follow_target_local(best_i))
            delta = final_mw @ original_root_mw.inverted()
            for child_obj, _rel in sub:
                orig = self._match_saved.get(child_obj)
                if orig is None:
                    continue
                try:
                    child_obj.matrix_world = delta @ orig
                except ReferenceError:
                    pass
            snapped += 1
        return snapped

    def _reset_defaults(self):
        """Restore all parameters to factory defaults. Sources & pivot stay."""
        self.pivot_mode  = PIVOT_CURSOR
        self.clone_mode  = CLONE_DUP
        self.arc_mode    = ARC_FULL
        self.axis_mode   = AXIS_GLOBAL_Z
        self.align_mode  = ALIGN_NONE
        self.skip_first  = False
        self.end_inclusive = True
        self.count = 6
        self.pending_normal_pick = False
        self.radius_override = None
        self.radius_drag_active = False
        self.arc_center_drag_active = False
        self.arc_apex_h_signed = None
        self.match_active = False
        self._match_saved = None
        self.source_mode = SOURCE_GROUP
        self._cached_axis_vec = Vector((0, 0, 1))
        self._dirty = True

    def _cleanup(self):
        if getattr(self, "_handle", None) is not None:
            safe_handler_remove(self._handle, bpy.types.SpaceView3D, "WINDOW")
            self._handle = None
        if getattr(self, "_handle_3d", None) is not None:
            safe_handler_remove(self._handle_3d, bpy.types.SpaceView3D, "WINDOW")
            self._handle_3d = None

    def _apply(self, context):
        # When Match is active the source objects already sit on the arc and
        # were moved in place — no clones to create. Just commit (the matrices
        # are already on the scene; we drop the undo snapshot so they stay).
        if self.match_active:
            self._match_saved = None
            self.match_active = False
            return
        axis_vec = _resolve_axis(self, context)
        ang_total, step, n_clones = _compute_arc(self, axis_vec)
        if n_clones <= 0:
            return

        created_roots = []

        if self.arc_mode == ARC_FULL and self.skip_first:
            start_index = 0
        else:
            start_index = 1

        subtrees = self.subtree_data
        if not subtrees:
            return

        # Replace mode never creates objects for the first N slots — it moves the
        # source objects themselves. Only the (count - N) overflow slots become
        # linked instances. No working collection in pure Replace.
        replace_mode = (self.clone_mode == CLONE_REPLACE)
        ra_coll = None
        if not replace_mode:
            first_root_name = subtrees[0][0][0].name
            ra_coll = bpy.data.collections.new(f"_RadialArray_{first_root_name}")
            context.scene.collection.children.link(ra_coll)

        def _clone_subtree(subtree, delta):
            clone_map = {}
            for child_obj, _rel in subtree:
                new = child_obj.copy()
                if self.clone_mode == CLONE_DUP and child_obj.data is not None:
                    new.data = child_obj.data.copy()
                for c in child_obj.users_collection:
                    try:
                        c.objects.link(new)
                    except RuntimeError:
                        pass
                if ra_coll is not None:
                    try:
                        ra_coll.objects.link(new)
                    except RuntimeError:
                        pass
                clone_map[child_obj] = new
            for child_obj, _rel in subtree:
                new = clone_map[child_obj]
                if child_obj.parent is not None and child_obj.parent in clone_map:
                    new.parent = clone_map[child_obj.parent]
                    new.matrix_parent_inverse = child_obj.matrix_parent_inverse.copy()
                else:
                    new.parent = None
                new.matrix_world = delta @ child_obj.matrix_world
            created_roots.append(clone_map[subtree[0][0]])

        def _replace_subtree(subtree, delta):
            for child_obj, _rel in subtree:
                try:
                    child_obj.matrix_world = delta @ child_obj.matrix_world
                except ReferenceError:
                    pass
            try:
                created_roots.append(subtree[0][0])
            except (ReferenceError, IndexError):
                pass

        if replace_mode:
            # Replace only makes sense with one source per slot — that's pool fill.
            # In group-rigid mode, every "slot" multiplies the whole selection, so
            # there's nothing to "replace into" with the same source set.
            N = len(subtrees)
            used = set()
            if self.source_mode == SOURCE_POOL:
                for i, (delta, subtree, _slot_pos) in enumerate(_pool_fill_iter(self, axis_vec)):
                    sub_id = id(subtree)
                    if sub_id in used:
                        # extras (count > N): can't move the same source twice, so
                        # fall back to a linked instance.
                        first_root_name = subtrees[0][0][0].name
                        if ra_coll is None:
                            ra_coll = bpy.data.collections.new(f"_RadialArray_{first_root_name}")
                            context.scene.collection.children.link(ra_coll)
                        _clone_subtree(subtree, delta)
                    else:
                        used.add(sub_id)
                        _replace_subtree(subtree, delta)
            else:
                # Treat the whole selection as one rigid group: move it to slot 0.
                anchor_raw = Matrix.Translation(_group_anchor_co(self))
                anchor_eff = _effective_source_mw(anchor_raw, self.pivot_co, axis_vec,
                                                  self.radius_override if self.radius_override is not None else _effective_radius(self))
                anchor_actual = (self.anchor_obj.matrix_world.copy()
                                 if self.anchor_obj is not None else anchor_raw)
                _replace_params = _arc_params(self, axis_vec)
                replace_center = _replace_params[0] if _replace_params is not None else self.pivot_co
                M_slot0 = _clone_matrix(self.pivot_co, axis_vec, _arc_effective_start(self, axis_vec), anchor_eff)
                base0 = anchor_actual.copy()
                base0.translation = M_slot0.translation
                M_final0 = _aligned_clone_mw(self.align_mode, replace_center, axis_vec,
                                             base0, self._pool_seed, 0, follow_target=None)
                delta = M_final0 @ anchor_actual.inverted()
                for subtree in subtrees:
                    _replace_subtree(subtree, delta)
                # Build the rest as instances around the ring.
                if ra_coll is None:
                    first_root_name = subtrees[0][0][0].name
                    ra_coll = bpy.data.collections.new(f"_RadialArray_{first_root_name}")
                    context.scene.collection.children.link(ra_coll)
                for ci, angle in _iter_clone_angles(_arc_effective_start(self, axis_vec), step, n_clones, start_index=start_index):
                    M_anchor = _clone_matrix(self.pivot_co, axis_vec, angle, anchor_eff)
                    if self.align_mode == ALIGN_NONE:
                        base_i = anchor_actual.copy()
                        base_i.translation = M_anchor.translation
                    else:
                        R_step = Matrix.Rotation(ci * step, 4, axis_vec).to_3x3()
                        base_i = (R_step @ anchor_actual.to_3x3()).to_4x4()
                        base_i.translation = M_anchor.translation
                    M_final = _aligned_clone_mw(self.align_mode, replace_center, axis_vec,
                                                base_i, self._pool_seed, ci, follow_target=None)
                    delta_i = M_final @ anchor_actual.inverted()
                    for subtree in subtrees:
                        _clone_subtree(subtree, delta_i)
        elif self.source_mode == SOURCE_POOL:
            for delta, subtree, _slot_pos in _pool_fill_iter(self, axis_vec):
                _clone_subtree(subtree, delta)
        else:
            params = _arc_params(self, axis_vec)
            if params is None:
                return
            arc_center, arc_R, arc_start, arc_sweep = params
            anchor_actual = (self.anchor_obj.matrix_world.copy()
                             if self.anchor_obj is not None else Matrix.Translation(_group_anchor_co(self)))
            n_total = max(2, int(self.count))
            if self.arc_mode == ARC_FULL:
                slot_step = (2 * math.pi) / n_total
            else:
                slot_step = arc_sweep / (n_total - 1) if (n_total > 1 and self.end_inclusive) else arc_sweep / max(1, n_total)
            step = slot_step  # for downstream R_step
            right, fwd = _arc_frame(axis_vec)
            all_positions = []
            for ci in range(n_total):
                a = arc_start + ci * slot_step
                all_positions.append(arc_center + (right * math.cos(a) + fwd * math.sin(a)) * arc_R)

            wraps = (self.arc_mode == ARC_FULL)

            def _follow_target(i):
                if i + 1 < n_total:
                    return all_positions[i + 1]
                if wraps:
                    return all_positions[0]
                if i - 1 >= 0:
                    return all_positions[i] + (all_positions[i] - all_positions[i - 1])
                return None

            for ci in range(start_index, n_total):
                slot_pos = all_positions[ci]
                if self.align_mode == ALIGN_NONE:
                    base_mw = anchor_actual.copy()
                    base_mw.translation = slot_pos
                else:
                    R_step = Matrix.Rotation(ci * step, 4, axis_vec).to_3x3()
                    base_mw = (R_step @ anchor_actual.to_3x3()).to_4x4()
                    base_mw.translation = slot_pos
                M_final = _aligned_clone_mw(
                    self.align_mode, arc_center, axis_vec, base_mw,
                    self._pool_seed, ci, follow_target=_follow_target(ci))
                delta = M_final @ anchor_actual.inverted()
                for subtree in subtrees:
                    _clone_subtree(subtree, delta)

        for obj in context.view_layer.objects:
            try:
                obj.select_set(False)
            except RuntimeError:
                pass
        for r in created_roots:
            try:
                r.select_set(True)
            except RuntimeError:
                pass
        if created_roots:
            try:
                context.view_layer.objects.active = created_roots[0]
            except (AttributeError, RuntimeError):
                pass
