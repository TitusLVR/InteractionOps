import bpy
import math
from mathutils import Vector, Matrix

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
        HUDItem("Axis offset mode (drag point)", "E",   ItemState.ON, default_state=ItemState.OFF, always_show=True),
        HUDItem("Orientation (Align / Rotate / Random …)", "R", ItemState.ON, default_state=ItemState.OFF, always_show=True),
        HUDItem("Local rot step (1°/5°/15°/45°/90°)", "1..5", ItemState.ON, default_state=ItemState.OFF, always_show=True),
        HUDItem("Nudge local X / Y / Z",  "← / → / ↑ (Shift = reverse)", ItemState.ON, default_state=ItemState.OFF, always_show=True),
        HUDItem("Reset local rotation",   "↓",                  ItemState.ON, default_state=ItemState.OFF, always_show=True),
        HUDItem("Clone type",     "D",                  ItemState.ON, default_state=ItemState.OFF, always_show=True),
        HUDItem("Start point clone", "S",                ItemState.ON, default_state=ItemState.OFF, always_show=True),
        HUDItem("End point inclusive", "F",              ItemState.ON, default_state=ItemState.OFF, always_show=True),
        HUDItem("Axis (toggle Global / pivot frame)", "X / Y / Z", ItemState.ON, default_state=ItemState.OFF, always_show=True),
        HUDItem("Source mode (Active/Hier/Group/Pool)", "T", ItemState.ON, default_state=ItemState.OFF, always_show=True),
        HUDItem("Match from origins", "A (toggle)",      ItemState.ON, default_state=ItemState.OFF, always_show=True),
        HUDItem("Reroll pool seed",   "G",                ItemState.ON, default_state=ItemState.OFF, always_show=True),
        HUDItem("Snap cursor to face (vert/edge-mid/center, Z=normal)", "C + LMB", ItemState.ON, default_state=ItemState.OFF, always_show=True),
        HUDItem("Lock clones out (hover + LMB) · N = Show/Hide locked", "N", ItemState.ON, default_state=ItemState.OFF, always_show=True),
        HUDItem("View axis",      "V",                  ItemState.ON, default_state=ItemState.OFF, always_show=True),
        HUDItem("Reset to defaults", "B",                ItemState.ON, default_state=ItemState.OFF, always_show=True),
        HUDItem("Count +/-",      "+ / -  or  Ctrl+Wheel", ItemState.ON, default_state=ItemState.OFF, always_show=True),
        HUDItem("Radius drag (360/180/90/45)", "LMB on ring + drag", ItemState.ON, default_state=ItemState.OFF, always_show=True),
        HUDItem("Move arc center (Active→Cursor)", "LMB on center + drag", ItemState.ON, default_state=ItemState.OFF, always_show=True),
        HUDItem("Flip arc apex", "I",                 ItemState.ON, default_state=ItemState.OFF, always_show=True),
        HUDItem("Undo / Redo",    "Ctrl+Z / Ctrl+Shift+Z", ItemState.ON, default_state=ItemState.OFF, always_show=True),
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

PIVOT_ACTIVE        = "ACTIVE"          # center & axis from the active object
PIVOT_CURSOR        = "CURSOR"          # center & axis from the 3D cursor
PIVOT_ACTIVE_CURSOR = "ACTIVE_CURSOR"   # axis from cursor, circle plane through active
# Cycle order requested: Active-Cursor → Cursor → Active.
PIVOT_CYCLE        = (PIVOT_ACTIVE_CURSOR, PIVOT_CURSOR, PIVOT_ACTIVE)

PIVOT_LABELS = {
    PIVOT_ACTIVE_CURSOR: "Active-Cursor",
    PIVOT_CURSOR:        "Cursor",
    PIVOT_ACTIVE:        "Active",
}


def _pivot_label(pivot_mode):
    return PIVOT_LABELS.get(pivot_mode, pivot_mode)

CLONE_DUP          = "DUPLICATE"
CLONE_INST         = "INSTANCE"
CLONE_REPLACE      = "REPLACE"
CLONE_CYCLE        = (CLONE_DUP, CLONE_INST, CLONE_REPLACE)

SOURCE_ACTIVE      = "ACTIVE"        # only the active object (no children)
SOURCE_HIERARCHY   = "HIERARCHY"     # active + its parented children (single subtree)
SOURCE_GROUP       = "GROUP"         # all selected, rigid group, anchor = active
SOURCE_POOL        = "POOL"          # all selected; one per slot, random extras
SOURCE_CYCLE       = (SOURCE_ACTIVE, SOURCE_HIERARCHY, SOURCE_GROUP, SOURCE_POOL)

# Clone orientation modes (R cycles):
#   ALIGN  — re-orient each clone to a consistent radial frame (+X to center,
#            +Y tangent, +Z = axis). Replaces the old "rigid/tilt" base.
#   ROTATE — pure rigid rotation of the source around the axis through the pivot,
#            exactly like rotate-duplicating by hand: the orientation co-rotates.
#   RANDOM_* — random spin layered on top of the ALIGN frame.
ALIGN_ALIGN        = "ALIGN"
ALIGN_ROTATE       = "ROTATE"
ALIGN_RANDOM_ALL   = "RANDOM_ALL"    # random rotation around all 3 local axes
ALIGN_RANDOM_X     = "RANDOM_X"      # random rotation around local X
ALIGN_RANDOM_Y     = "RANDOM_Y"      # random rotation around local Y
ALIGN_RANDOM_Z     = "RANDOM_Z"      # random rotation around local Z
ALIGN_CYCLE        = (ALIGN_ALIGN, ALIGN_ROTATE, ALIGN_RANDOM_ALL, ALIGN_RANDOM_X, ALIGN_RANDOM_Y, ALIGN_RANDOM_Z)

ALIGN_LABELS = {
    ALIGN_ALIGN: "Align", ALIGN_ROTATE: "Rotate",
    ALIGN_RANDOM_ALL: "Random all", ALIGN_RANDOM_X: "Random X",
    ALIGN_RANDOM_Y: "Random Y", ALIGN_RANDOM_Z: "Random Z",
}


def _align_label(align_mode):
    return ALIGN_LABELS.get(align_mode, align_mode)

# Skip/delete display mode (N toggles). Picking (hover a clone + click to
# lock/unlock) is always active; the mode only controls how locked clones look:
#   SHOW — locked clones stay visible, tinted in the locked colour.
#   HIDE — locked clones are hidden (a marker keeps them clickable).
SKIP_SHOW  = "SHOW"
SKIP_HIDE  = "HIDE"
SKIP_CYCLE = (SKIP_SHOW, SKIP_HIDE)

# Local-axis rotation step presets bound to number keys 1..5 (degrees).
# Arrow keys nudge per-clone local rotation by the current step.
LOCAL_ROT_STEP_PRESETS = (1.0, 5.0, 15.0, 45.0, 90.0)

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
AXIS_LOCAL_X       = "LX"     # active object's local axes
AXIS_LOCAL_Y       = "LY"
AXIS_LOCAL_Z       = "LZ"
AXIS_CURSOR_X      = "CX"     # 3D cursor's axes
AXIS_CURSOR_Y      = "CY"
AXIS_CURSOR_Z      = "CZ"
AXIS_VIEW          = "VIEW"
AXIS_NORMAL        = "NORMAL"

# Each X/Y/Z key toggles between Global and the pivot-dependent frame:
#   pivot CURSOR → cursor axes, pivot ACTIVE → the active object's local axes.
# Global is always kept as the second toggle state.
_AXIS_GLOBAL = {"X": AXIS_GLOBAL_X, "Y": AXIS_GLOBAL_Y, "Z": AXIS_GLOBAL_Z}
_AXIS_LOCAL  = {"X": AXIS_LOCAL_X,  "Y": AXIS_LOCAL_Y,  "Z": AXIS_LOCAL_Z}
_AXIS_CURSOR = {"X": AXIS_CURSOR_X, "Y": AXIS_CURSOR_Y, "Z": AXIS_CURSOR_Z}
# Reverse map: which letter does an axis-mode belong to (for pivot remap).
_AXIS_TO_LETTER = {}
for _letter in ("X", "Y", "Z"):
    for _m in (_AXIS_GLOBAL[_letter], _AXIS_LOCAL[_letter], _AXIS_CURSOR[_letter]):
        _AXIS_TO_LETTER[_m] = _letter


def _pivot_frame_axis(letter, pivot_mode):
    """The non-global axis for `letter` under the current pivot: local axes for
    the ACTIVE pivot, cursor axes otherwise (CURSOR and ACTIVE_CURSOR both take
    the axis from the 3D cursor)."""
    table = _AXIS_LOCAL if pivot_mode == PIVOT_ACTIVE else _AXIS_CURSOR
    return table[letter]


def _axis_letter_cycle(letter, pivot_mode):
    """Two-state toggle for an X/Y/Z key: pivot-frame axis ↔ global axis."""
    return (_pivot_frame_axis(letter, pivot_mode), _AXIS_GLOBAL[letter])


def _remap_axis_to_pivot(axis_mode, pivot_mode):
    """When the pivot changes, move a local/cursor axis into the new pivot's
    frame keeping the same letter. Global / View / Normal axes are left as-is."""
    letter = _AXIS_TO_LETTER.get(axis_mode)
    if letter is None:
        return axis_mode                      # VIEW / NORMAL — untouched
    if axis_mode in _AXIS_GLOBAL.values():
        return axis_mode                      # keep explicit Global
    return _pivot_frame_axis(letter, pivot_mode)

# Human-readable axis names for the HUD / reports (no terse GX/LZ/CZ codes).
AXIS_LABELS = {
    AXIS_GLOBAL_X: "Global X", AXIS_GLOBAL_Y: "Global Y", AXIS_GLOBAL_Z: "Global Z",
    AXIS_LOCAL_X:  "Local X",  AXIS_LOCAL_Y:  "Local Y",  AXIS_LOCAL_Z:  "Local Z",
    AXIS_CURSOR_X: "Cursor X", AXIS_CURSOR_Y: "Cursor Y", AXIS_CURSOR_Z: "Cursor Z",
    AXIS_VIEW:     "View",     AXIS_NORMAL:   "Normal",
}


def _axis_label(axis_mode):
    """Readable axis name for UI; falls back to the raw code if unknown."""
    return AXIS_LABELS.get(axis_mode, axis_mode)


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
    else:  # PIVOT_CURSOR
        pivot_obj = None
        pivot_co = context.scene.cursor.location.copy()
        sources = list(sel)

    return pivot_co, pivot_obj, sources, None


def _resolve_axis(self, context):
    """Return a normalized world-space axis vector based on self.axis_mode."""
    am = self.axis_mode
    if am == AXIS_GLOBAL_X: return Vector((1, 0, 0))
    if am == AXIS_GLOBAL_Y: return Vector((0, 1, 0))
    if am == AXIS_GLOBAL_Z: return Vector((0, 0, 1))
    _LOCAL_VEC = {AXIS_LOCAL_X: Vector((1, 0, 0)), AXIS_CURSOR_X: Vector((1, 0, 0)),
                  AXIS_LOCAL_Y: Vector((0, 1, 0)), AXIS_CURSOR_Y: Vector((0, 1, 0)),
                  AXIS_LOCAL_Z: Vector((0, 0, 1)), AXIS_CURSOR_Z: Vector((0, 0, 1))}
    if am in (AXIS_LOCAL_X, AXIS_LOCAL_Y, AXIS_LOCAL_Z):
        local = _LOCAL_VEC[am]
        active = getattr(self, "active_obj", None)
        if active is not None:
            try:
                return (active.matrix_world.to_3x3() @ local).normalized()
            except ReferenceError:
                pass
        return local
    if am in (AXIS_CURSOR_X, AXIS_CURSOR_Y, AXIS_CURSOR_Z):
        local = _LOCAL_VEC[am]
        try:
            return (bpy.context.scene.cursor.matrix.to_3x3() @ local).normalized()
        except AttributeError:
            return local
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
    """Effective start offset (radians). Slot 0 sits at the active object's
    angle around the pivot — for every arc mode, so slot 0 always lines up
    with the active's origin."""
    active = getattr(op, "active_obj", None)
    if active is None:
        return 0.0
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
                      seed, slot_index,
                      local_rot=(0.0, 0.0, 0.0)):
    """Apply alignment on top of `base_mw`. `base_mw` is the clone's natural
    pre-alignment matrix (caller already built the ALIGN/ROTATE frame and applied
    R_step). ALIGN / ROTATE return it unchanged; RANDOM_* layer a deterministic
    random rotation around `base_mw.translation`. `local_rot` is applied last as
    a rotation around the clone's local X/Y/Z (right-mult)."""
    clone_pos = base_mw.translation
    T_to   = Matrix.Translation(clone_pos)
    T_from = Matrix.Translation(-clone_pos)

    # Stage 1: random spin (the only non-rigid alignment).
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
        base_mw = T_to @ R @ T_from @ base_mw
    # ALIGN / ROTATE: base_mw already encodes the desired orientation.

    # Stage 2: per-clone local-axis rotation (arrow keys nudge `local_rot`).
    lx, ly, lz = local_rot
    if lx or ly or lz:
        local_R = (Matrix.Rotation(lx, 4, 'X') @
                   Matrix.Rotation(ly, 4, 'Y') @
                   Matrix.Rotation(lz, 4, 'Z'))
        # Apply on the right so axes are the clone's LOCAL X/Y/Z.
        rotated = (base_mw.to_3x3() @ local_R.to_3x3()).to_4x4()
        rotated.translation = base_mw.translation
        base_mw = rotated
    return base_mw


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


def _mouse_signed_along_axis(context, event, base_co, axis_vec):
    """Signed distance along `axis_vec` (from `base_co`) of the point on the axis
    line closest to the mouse ray. Used to drag the axis-offset handle. None if
    the view direction is parallel to the axis."""
    from bpy_extras.view3d_utils import region_2d_to_origin_3d, region_2d_to_vector_3d
    region = context.region
    rv3d = context.region_data
    if region is None or rv3d is None:
        return None
    mouse = Vector((event.mouse_region_x, event.mouse_region_y))
    O = region_2d_to_origin_3d(region, rv3d, mouse)
    D = region_2d_to_vector_3d(region, rv3d, mouse)
    A = axis_vec.normalized()
    w0 = O - base_co
    a = D.dot(D); b = D.dot(A); c = 1.0
    d = D.dot(w0); e = A.dot(w0)
    denom = a * c - b * b
    if abs(denom) < 1e-9:
        return None
    # parameter along the axis line of the closest point to the ray
    return (a * e - b * d) / denom


# --- Preview (POST_VIEW) -------------------------------------------------

def _mesh_geom_cache(obj):
    """Return ([verts_local], [edge_idx_pairs], [tri_idx_triplets]) for the mesh,
    computed once and cached on the operator. Loop triangles are pre-computed
    so per-clone draw work is just matrix multiplies, not topology re-walks."""
    mesh = obj.data
    verts_local = [v.co.copy() for v in mesh.vertices]
    edge_pairs = [(e.vertices[0], e.vertices[1]) for e in mesh.edges]
    if not mesh.loop_triangles:
        try:
            mesh.calc_loop_triangles()
        except RuntimeError:
            pass
    loops = mesh.loops
    tri_idx = [(loops[lt.loops[0]].vertex_index,
                loops[lt.loops[1]].vertex_index,
                loops[lt.loops[2]].vertex_index)
               for lt in mesh.loop_triangles]
    return verts_local, edge_pairs, tri_idx


def _mesh_edge_segments_world(obj_mw, geom):
    """Flat edge endpoints in world space using a precomputed local-geom cache."""
    verts_local, edge_pairs, _ = geom
    verts_world = [obj_mw @ v for v in verts_local]
    return [(verts_world[a], verts_world[b]) for a, b in edge_pairs]


def _mesh_face_tris_world(obj_mw, geom):
    """Triangulated faces in world space using a precomputed local-geom cache."""
    verts_local, _, tri_idx = geom
    verts_world = [obj_mw @ v for v in verts_local]
    out = []
    for a, b, c in tri_idx:
        out.append(verts_world[a])
        out.append(verts_world[b])
        out.append(verts_world[c])
    return out


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
    B_raw = bpy.context.scene.cursor.location.copy()
    # Force the arc into the plane perpendicular to axis_vec that PASSES through
    # the active object — so slot 0 is exactly at the active's origin. B is
    # projected to that same plane (cursor's axial component is dropped).
    A_axial_co = axis_vec * A.dot(axis_vec)
    B = (B_raw - axis_vec * B_raw.dot(axis_vec)) + A_axial_co

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
        h_signed = -r_min  # default: semicircle bulging on −perp side (intuitive, no flip needed)
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
      derived. None if A and B coincide.
    The whole arc is slid along the rotation axis by `op.axis_offset`."""
    off = axis_vec * getattr(op, "axis_offset", 0.0)
    if op.arc_mode == ARC_CURSOR:
        g = _arc_two_point_geometry(op, axis_vec)
        if g is None:
            return None
        center, R, start, sweep = g
        return center + off, R, start, sweep
    # Center is the user pivot.
    center = op.pivot_co.copy()
    active = getattr(op, "active_obj", None)
    # Radius: planar distance from pivot to active when no override.
    if op.radius_override is not None:
        R = op.radius_override
    elif active is not None:
        try:
            v = active.matrix_world.translation - op.pivot_co
            R = (v - axis_vec * v.dot(axis_vec)).length
        except ReferenceError:
            R = 0.0
    else:
        R = 0.0
    if R < 1e-3:
        R = 1.0
    start = _arc_effective_start(op, axis_vec)
    if op.arc_mode == ARC_FULL:
        sweep = 2 * math.pi
    else:
        sweep = _ARC_FIXED_SWEEPS.get(op.arc_mode, 0.0)
    return center + off, R, start, sweep


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


def _slot_step(op, arc_sweep, n_total):
    """Angular step between slots for the current arc mode."""
    if op.arc_mode == ARC_FULL:
        return (2 * math.pi) / n_total
    if n_total > 1:
        return arc_sweep / (n_total - 1) if op.end_inclusive else arc_sweep / n_total
    return 0.0


def _slot_positions(op, axis_vec):
    """World positions of every slot (indexed by ci, 0..n_total-1). [] if no arc."""
    params = _arc_params(op, axis_vec)
    if params is None:
        return []
    arc_center, arc_R, arc_start, arc_sweep = params
    n_total = max(2, int(op.count))
    step = _slot_step(op, arc_sweep, n_total)
    right, fwd = _arc_frame(axis_vec)
    return [arc_center + (right * math.cos(arc_start + ci * step)
                          + fwd * math.sin(arc_start + ci * step)) * arc_R
            for ci in range(n_total)]


def _drawn_slot_range(op):
    """Indices of slots that get a clone: skip_first adds slot 0."""
    n_total = max(2, int(op.count))
    return range(0 if op.skip_first else 1, n_total)


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

    for s in range(n_slots):
        sub_idx = s if s < N else rng.randrange(N)
        subtree = op.subtree_data[sub_idx]
        try:
            src_root = subtree[0][0]
            src_mw = src_root.matrix_world.copy()
        except ReferenceError:
            continue
        ang = arc_start + s * step
        target_pos = arc_center + (right * math.cos(ang) + fwd * math.sin(ang)) * radius
        base_mw = _base_anchor(op.align_mode, src_mw, axis_vec, target_pos, arc_center)
        base_mw.translation = target_pos
        new_mw = _aligned_clone_mw(op.align_mode, arc_center, axis_vec,
                                   base_mw, op._pool_seed, s,
                                   local_rot=tuple(op.local_rot))
        delta = new_mw @ src_mw.inverted()
        yield delta, subtree, target_pos


def _tilt_z_to_axis(mw, axis_vec):
    """Pre-rotate `mw` so its +Z aligns with `axis_vec` (shortest rotation),
    preserving translation. This makes the clones lie flat in the plane
    perpendicular to the rotation axis — so the chosen axis (global / active /
    cursor) directly determines the array's plane."""
    if axis_vec is None or axis_vec.length < 1e-6:
        return mw
    src_z = mw.to_3x3() @ Vector((0, 0, 1))
    if src_z.length < 1e-6:
        return mw
    q = src_z.rotation_difference(axis_vec)
    out = (q.to_matrix() @ mw.to_3x3()).to_4x4()
    out.translation = mw.translation
    return out


def _aim_radial(mw, axis_vec, pos, center):
    """Build a base orientation for a clone sitting at `pos` so that:
      * +Z == `axis_vec` (clone lies flat in the rotation plane),
      * +X == the inward radial at `pos` (points toward `center`),
      * +Y == Z×X (the circle tangent — the 'forward' direction of travel).
    Scale is taken from `mw`; translation is preserved. Because both the slot
    position and this frame co-rotate by the same step around the axis, every
    clone's local X keeps pointing at the center. Falls back to the shortest-arc
    Z-tilt when the clone sits on the axis (radius undefined)."""
    if axis_vec is None or axis_vec.length < 1e-6:
        return mw
    axis = axis_vec.normalized()
    radial = pos - center
    radial = radial - axis * radial.dot(axis)   # project into the rotation plane
    if radial.length < 1e-6:
        return _tilt_z_to_axis(mw, axis)
    x_axis = (-radial).normalized()               # toward center
    y_axis = axis.cross(x_axis).normalized()      # tangent / forward (= Z×X)
    rot = Matrix((x_axis, y_axis, axis)).transposed()   # columns = basis vectors
    _, _, scale = mw.decompose()
    base = (rot @ Matrix.Diagonal(scale)).to_4x4()
    base.translation = mw.translation
    return base


def _base_anchor(align_mode, mw, axis_vec, pos, center):
    """Pick the clone's base orientation by mode:
      * ROTATE — keep the source orientation untouched (pure rigid rotation
        around the axis; R_step co-rotates it, like a hand rotate-duplicate).
      * everything else (ALIGN, RANDOM_*) — aim +X at the center (consistent
        radial frame); RANDOM_* then layers spin on top in `_aligned_clone_mw`."""
    if align_mode == ALIGN_ROTATE:
        return mw.copy()
    return _aim_radial(mw, axis_vec, pos, center)


def _build_anchor_matrix(op):
    """Anchor matrix used as the base orientation for clones — raw source frame.
    For SOURCE_GROUP we anchor on the active object's full matrix; otherwise we
    use a pure translation at the group centroid. Callers tilt this onto the
    rotation axis with `_tilt_z_to_axis` before R_step is applied."""
    if op.anchor_obj is not None:
        try:
            return op.anchor_obj.matrix_world.copy()
        except ReferenceError:
            pass
    return Matrix.Translation(_group_anchor_co(op))


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
    hover_tris = []        # skip/delete mode: faces of the clone under the mouse
    hover_segs = []
    locked_tris = []       # clones locked out — shown tinted in the locked colour
    locked_segs = []
    locked_crosses = []    # slot markers for locked clones
    locked = getattr(op, "locked_slots", set())
    skip_mode = getattr(op, "skip_mode", SKIP_SHOW)
    show_locked = (skip_mode == SKIP_SHOW)        # locked mesh visible (tinted) vs hidden
    mark_locked = True                            # locked marker always clickable
    hover_slot = getattr(op, "_hover_slot", None)

    def _pack():
        return (segs, tris, crosses, hover_tris, hover_segs,
                locked_tris, locked_segs, locked_crosses, axis_vec, ang_total)

    # After Match, the sources sit on the arc themselves — no preview clones
    # so they don't visually pile on top of the snapped objects.
    if getattr(op, "match_active", False):
        return _pack()

    # skip_first (F) clones slot 0 too — works for every arc mode, including
    # the Active→Cursor arc, not just the full circle.
    start_index = 0 if op.skip_first else 1

    subtrees = op.subtree_data
    if not subtrees:
        return _pack()

    cache = getattr(op, "_mesh_cache", {})
    if op.source_mode == SOURCE_POOL:
        for s, (delta, subtree, slot_pos) in enumerate(_pool_fill_iter(op, axis_vec)):
            # Edges always use the theme edge colour; only the fill state varies.
            if s in locked:
                if mark_locked:
                    locked_crosses.append(slot_pos.copy())
                if not show_locked:
                    continue            # HIDE / OFF — locked clone not drawn
                into_tris = locked_tris
            elif s == hover_slot:
                into_tris = hover_tris
            else:
                into_tris = tris
            crosses.append(slot_pos.copy())
            for child_obj, _rel in subtree:
                child_clone_mw = delta @ child_obj.matrix_world
                geom = cache.get(child_obj)
                if geom is not None:
                    for a, b in _mesh_edge_segments_world(child_clone_mw, geom):
                        segs.append((a, b))
                    into_tris.extend(_mesh_face_tris_world(child_clone_mw, geom))
                else:
                    crosses.append(child_clone_mw.translation.copy())
        return _pack()

    # Build slot positions from unified arc params (handles ARC_FULL/ANGLE/CURSOR).
    params = _arc_params(op, axis_vec)
    if params is None:
        return _pack()
    arc_center, arc_R, arc_start, arc_sweep = params
    right, fwd = _arc_frame(axis_vec)
    anchor_raw = _build_anchor_matrix(op)
    # Base orientation per align mode (ALIGN aims +X at center; ROTATE keeps the
    # source frame). R_step co-rotates it per slot.
    _pos0 = arc_center + (right * math.cos(arc_start) + fwd * math.sin(arc_start)) * arc_R
    anchor_actual = _base_anchor(op.align_mode, anchor_raw, axis_vec, _pos0, arc_center)

    n_total = max(2, int(op.count))
    if op.arc_mode == ARC_FULL:
        slot_step = (2 * math.pi) / n_total
    else:
        if n_total > 1:
            slot_step = arc_sweep / (n_total - 1) if op.end_inclusive else arc_sweep / n_total
        else:
            slot_step = 0.0
    all_positions = []
    for ci in range(n_total):
        a = arc_start + ci * slot_step
        all_positions.append(arc_center + (right * math.cos(a) + fwd * math.sin(a)) * arc_R)

    step = slot_step  # alias for downstream rotation step

    # Drawn indices: skip_first OFF leaves source visible at slot 0, so we draw
    # clones from slot 1 onward. skip_first ON also clones slot 0.
    for ci in range(start_index, n_total):
        slot_pos = all_positions[ci]
        # Locked clones: SHOW → tinted-locked mesh; HIDE/OFF → not drawn (a
        # marker keeps them clickable in SHOW/HIDE). Hovered clone → closest
        # tint; rest → normal. Edges always use the theme edge colour.
        if ci in locked:
            if mark_locked:
                locked_crosses.append(slot_pos.copy())
            if not show_locked:
                continue
            into_tris = locked_tris
        elif ci == hover_slot:
            into_tris = hover_tris
        else:
            into_tris = tris
        R_step = Matrix.Rotation(ci * step, 4, axis_vec).to_3x3()
        base_mw = (R_step @ anchor_actual.to_3x3()).to_4x4()
        base_mw.translation = slot_pos
        M_anchor_final = _aligned_clone_mw(
            op.align_mode, arc_center, axis_vec, base_mw,
            op._pool_seed, ci,
            local_rot=tuple(op.local_rot))
        # Divide by the RAW (untilted) anchor: the tilt lives in M_anchor_final,
        # and children's matrix_world are untilted, so dividing by the tilted
        # anchor would cancel the tilt (clones tumble instead of staying flat).
        delta = M_anchor_final @ anchor_raw.inverted()
        crosses.append(slot_pos.copy())
        for subtree in subtrees:
            for child_obj, _rel in subtree:
                child_clone_mw = delta @ child_obj.matrix_world
                geom = cache.get(child_obj)
                if geom is not None:
                    for a, b in _mesh_edge_segments_world(child_clone_mw, geom):
                        segs.append((a, b))
                    into_tris.extend(_mesh_face_tris_world(child_clone_mw, geom))
                else:
                    crosses.append(child_clone_mw.translation.copy())

    return _pack()


def _draw_preview_3d(op, context):
    """POST_VIEW draw: ghost faces + wires + axis line + arc/circle + pivot."""
    from ..ui.draw import primitives as iops_draw
    from ..ui.draw import draw_scope

    if op._dirty or getattr(op, "_ghost_cache", None) is None:
        op._ghost_cache = _build_ghost_segments(op, context)
        op._dirty = False
    (segs, tris, crosses, hover_tris, hover_segs,
     locked_tris, locked_segs, locked_crosses, axis_vec, ang_total) = op._ghost_cache

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
    # Locked-out clones: stay visible, tinted in the locked colour.
    if locked_tris:
        with draw_scope(blend="ALPHA", depth="LESS_EQUAL",
                        face_culling="NONE", depth_mask=False):
            iops_draw.tris(locked_tris, role=Role.GHOST_LOCKED, context=context)
    # Hovered clone (skip/delete mode): tint its faces with the closest colour.
    if hover_tris:
        with draw_scope(blend="ALPHA", depth="LESS_EQUAL",
                        face_culling="NONE", depth_mask=False):
            iops_draw.tris(hover_tris, role=Role.GHOST_CLOSEST, context=context)
    # All clone edges share the theme edge colour, regardless of fill state.
    if segs:
        flat = []
        for a, b in segs:
            flat.append(a)
            flat.append(b)
        with draw_scope(blend="ALPHA", depth="LESS_EQUAL"):
            iops_draw.edges_3d(flat, role=Role.GHOST_EDGE, context=context)

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

    # Axis indicator: total length = 1/3 of the radius (half each side). Doubles
    # as the axis-offset handle — coloured like the ring by default, and like an
    # active control while the offset mode is engaged.
    a_half = axis_vec * (radius / 6.0)
    axis_role = (Role.ACTIVE_LINE
                 if getattr(op, "axis_offset_mode", False) or getattr(op, "axis_offset_drag_active", False)
                 else Role.PREVIEW_LINE)
    iops_draw.edges_3d([center - a_half, center + a_half],
                       role=axis_role, context=context)

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

    # All markers draw last, on top of every line (depth test off).
    end_pt = _arc_endpoint_world(op, axis_vec)
    with draw_scope(blend="ALPHA", depth="NONE"):
        if crosses:
            iops_draw.points(crosses, role=Role.PREVIEW_POINT, context=context)
        if locked_crosses:
            iops_draw.points(locked_crosses, role=Role.LOCKED_POINT, context=context)
        iops_draw.points([center], role=Role.PIVOT, context=context)
        if end_pt is not None:
            iops_draw.points([end_pt], role=Role.ACTIVE_POINT, context=context)

    # T (normal-pick) hover overlay on top of the array preview.
    if getattr(op, "pending_normal_pick", False):
        _draw_tpick(op, context)


def _draw_tpick(op, context):
    """Draw the T-mode face pick overlay: highlighted face fill + outline, the
    candidate snap points (edge midpoints + face center), the closest snap, and
    a short normal indicator. All colors come from the addon theme."""
    tp = getattr(op, "_tpick", None)
    if not tp:
        return
    from ..ui.draw import primitives as iops_draw
    from ..ui.draw import draw_scope

    if tp["tris"]:
        with draw_scope(blend="ALPHA", depth="LESS_EQUAL",
                        face_culling="NONE", depth_mask=False):
            iops_draw.tris(tp["tris"], role=Role.GHOST_DEFAULT, context=context)
    if tp["edges"]:
        with draw_scope(blend="ALPHA", depth="LESS_EQUAL"):
            iops_draw.edges_3d(tp["edges"], role=Role.CLOSEST_LINE, context=context)
    # Normal indicator from the closest snap point.
    nlen = tp.get("nlen", 0.3) or 0.3
    with draw_scope(blend="ALPHA", depth="LESS_EQUAL"):
        iops_draw.edges_3d([tp["closest"], tp["closest"] + tp["normal"] * nlen],
                           role=Role.ACTIVE_LINE, context=context)
    # Snap points draw on top of the face/edge/normal lines.
    with draw_scope(blend="ALPHA", depth="NONE"):
        if tp["snaps"]:
            iops_draw.points(tp["snaps"], role=Role.PREVIEW_POINT, context=context)
        iops_draw.points([tp["closest"]], role=Role.CLOSEST_POINT, context=context)


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
        # Default to Active-Cursor: axis from the 3D cursor, but the circle plane
        # passes through the active object. Q cycles Active-Cursor → Cursor → Active.
        self.pivot_mode  = PIVOT_ACTIVE_CURSOR
        self.clone_mode  = CLONE_DUP
        self.arc_mode    = ARC_FULL
        self.axis_mode   = AXIS_CURSOR_Z   # default: rotate around the 3D cursor's Z
        self.align_mode  = ALIGN_ALIGN
        self.skip_first  = False
        self.end_inclusive = True
        self.count = 6
        self.pending_normal_pick = False
        self._tpick = None                 # T-mode face-pick hover snapshot
        self.skip_mode = SKIP_SHOW          # N toggles SHOW / HIDE for locked clones
        self.locked_slots = set()          # slot indices excluded at apply
        self._hover_slot = None            # slot index under the mouse in skip mode
        self._history = []                 # Ctrl+Z/Ctrl+Shift+Z state history
        self._hist_i = 0                   # index of the current state in _history
        self._cached_axis_vec = Vector((0, 0, 1))
        self.local_rot_step = math.radians(90.0)
        self.local_rot = [0.0, 0.0, 0.0]   # per-clone local-axis rotation (X, Y, Z) radians
        self.radius_override = None       # None = use natural source distance
        self.radius_drag_active = False
        self.arc_center_drag_active = False   # ARC_CURSOR: drag the derived center
        self.arc_apex_h_signed = None         # ARC_CURSOR: signed apex distance on AB's perpendicular bisector
        self.axis_offset = 0.0                # signed slide of the whole array along the rotation axis
        self.axis_offset_mode = False         # E: drag the axis-offset preview point
        self.axis_offset_drag_active = False
        self.match_active = False
        self._match_saved = None          # snapshot used to un-apply Match
        self.source_mode = SOURCE_GROUP   # U cycles ACTIVE / HIERARCHY / GROUP / POOL
        self.anchor_obj = None            # the active object when source_mode == GROUP
        self.active_obj = context.active_object  # always tracked; arc start sits at this object
        self._pool_seed = 12345
        self._dirty = True

        self._resolve_pivot(context)

        self._rebuild_sources(context)
        if not self.subtree_data:
            self.report({"WARNING"}, "Select at least one source object")
            return {"CANCELLED"}

        self._history = [self._snapshot()]   # seed undo history with the initial state
        self._hist_i = 0

        def _local_rot_used():
            return any(abs(a) > 1e-9 for a in self.local_rot)

        self._hud = _build_hud(context)
        # Always-on core params.
        self._hud.add_param(HUDParam("Count",      lambda: self.count, "int"))
        self._hud.add_param(HUDParam("Pivot",      lambda: _pivot_label(self.pivot_mode), "str"))
        self._hud.add_param(HUDParam("Type",       lambda: self.arc_mode, "str"))
        self._hud.add_param(HUDParam("Alignment",  lambda: _align_label(self.align_mode), "str"))
        self._hud.add_param(HUDParam("Axis",       lambda: _axis_label(self.axis_mode), "str"))
        # Contextual params — only shown once touched / relevant.
        self._hud.add_param(HUDParam("Axis offset", lambda: self.axis_offset, "float", fmt="{:.3f}",
                                     visible_getter=lambda: self.axis_offset_mode or abs(self.axis_offset) > 1e-6))
        self._hud.add_param(HUDParam("Start point", lambda: self.skip_first, "bool",
                                     visible_getter=lambda: self.skip_first))
        self._hud.add_param(HUDParam("End point",   lambda: self.end_inclusive, "bool",
                                     visible_getter=lambda: self.arc_mode != ARC_FULL))
        self._hud.add_param(HUDParam("Rot step",    lambda: math.degrees(self.local_rot_step), "float", fmt="{:.0f}°",
                                     visible_getter=_local_rot_used))
        self._hud.add_param(HUDParam("Local Rot",
                                     lambda: "{:.0f}°/{:.0f}°/{:.0f}°".format(
                                         math.degrees(self.local_rot[0]),
                                         math.degrees(self.local_rot[1]),
                                         math.degrees(self.local_rot[2])), "str",
                                     visible_getter=_local_rot_used))
        self._hud.add_param(HUDParam("Skip/delete", lambda: f"{self.skip_mode} · {len(self.locked_slots)} locked", "str",
                                     visible_getter=lambda: bool(self.locked_slots) or self.skip_mode == SKIP_HIDE))
        self._hud.add_param(HUDParam("Match",       lambda: self.match_active, "bool",
                                     visible_getter=lambda: self.match_active))
        self._hud.add_param(HUDParam("Clone type",  lambda: self.clone_mode, "str",
                                     visible_getter=lambda: self.clone_mode != CLONE_DUP))
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

        # Commit the previous event's result to the undo history before handling
        # the new event (so Ctrl+Z always reverts in a single press).
        self._commit_history()

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

        # --- redo (Ctrl+Shift+Z): step forward in history ---
        if event.type == "Z" and event.value == "PRESS" and event.ctrl and event.shift:
            if self._hist_i < len(self._history) - 1:
                self._hist_i += 1
                self._restore(context, self._history[self._hist_i])
                self.report({"INFO"}, "Redo")
            else:
                self.report({"INFO"}, "Nothing to redo")
            return {"RUNNING_MODAL"}

        # --- undo (Ctrl+Z): step back in history ---
        if event.type == "Z" and event.value == "PRESS" and event.ctrl and not event.shift:
            if self._hist_i > 0:
                self._hist_i -= 1
                self._restore(context, self._history[self._hist_i])
                self.report({"INFO"}, "Undo")
            else:
                self.report({"INFO"}, "Nothing to undo")
            return {"RUNNING_MODAL"}

        # --- mode cycles (QWER cluster) ---
        if event.type == "Q" and event.value == "PRESS":
            self.pivot_mode = _cycle(self.pivot_mode, PIVOT_CYCLE)
            # Keep the axis letter, move it into the new pivot's frame
            # (cursor↔local); Global / View / Normal are left untouched.
            self.axis_mode = _remap_axis_to_pivot(self.axis_mode, self.pivot_mode)
            self._resolve_pivot(context)
            self._rebuild_sources(context)
            self._dirty = True
            self.report({"INFO"}, f"Pivot: {_pivot_label(self.pivot_mode)}  |  Axis: {_axis_label(self.axis_mode)}")
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
        if event.type == "A" and event.value == "PRESS":
            self._toggle_match(context)
            return {"RUNNING_MODAL"}

        # --- source mode cycle (Active / Hierarchy / Group / Pool) ---
        if event.type == "T" and event.value == "PRESS":
            self.source_mode = _cycle(self.source_mode, SOURCE_CYCLE)
            self._rebuild_sources(context)
            self._dirty = True
            self.report({"INFO"}, f"Source: {self.source_mode}")
            return {"RUNNING_MODAL"}

        # --- reroll random seed for SOURCE_POOL extras ---
        if event.type == "G" and event.value == "PRESS":
            if self.source_mode == SOURCE_POOL:
                import time
                self._pool_seed = int(time.time() * 1000) & 0xFFFFFF
                self._dirty = True
                self.report({"INFO"}, "Pool seed re-rolled")
            return {"RUNNING_MODAL"}

        # --- axis ---
        # Each X/Y/Z key toggles between the pivot-dependent frame (cursor axes
        # when pivot=CURSOR, local axes when pivot=ACTIVE) and the global axis.
        if event.type in {"X", "Y", "Z"} and event.value == "PRESS":
            cyc = _axis_letter_cycle(event.type, self.pivot_mode)
            self.axis_mode = _cycle(self.axis_mode, cyc) if self.axis_mode in cyc else cyc[0]
            self.pending_normal_pick = False
            self._resolve_pivot(context)   # ACTIVE_CURSOR center depends on the axis
            self._dirty = True
            self.report({"INFO"}, f"Axis: {_axis_label(self.axis_mode)}")
            return {"RUNNING_MODAL"}

        if event.type == "V" and event.value == "PRESS":
            self.axis_mode = AXIS_VIEW
            self.pending_normal_pick = False
            self._resolve_pivot(context)
            self._dirty = True
            return {"RUNNING_MODAL"}

        if event.type == "C" and event.value == "PRESS":
            self.pending_normal_pick = True
            self._tpick_update(context, event)
            context.area.tag_redraw()
            self.report({"INFO"}, "Hover a face; click an edge-mid / center to snap the 3D cursor there")
            return {"RUNNING_MODAL"}

        # --- live hover while T is armed: highlight face + snap points ---
        if self.pending_normal_pick and event.type == "MOUSEMOVE":
            self._tpick_update(context, event)
            context.area.tag_redraw()
            return {"RUNNING_MODAL"}

        # --- snap the 3D cursor on click (MUST come before the apply LMB) ---
        if self.pending_normal_pick and event.type == "LEFTMOUSE" and event.value == "PRESS":
            self._tpick_update(context, event)
            tp = self._tpick
            if tp is not None:
                cursor = context.scene.cursor
                cursor.location = tp["closest"].copy()
                # Orient the cursor so its +Z aligns with the face normal — the
                # array plane (Cursor Z) then lies flat on the picked face.
                cursor.rotation_mode = "XYZ"
                cursor.rotation_euler = tp["normal"].to_track_quat("Z", "Y").to_euler()
                self.axis_mode = AXIS_CURSOR_Z
                self._resolve_pivot(context)
                self._dirty = True
                self.report({"INFO"}, "Cursor snapped to face (Z = face normal)")
            else:
                self.report({"WARNING"}, "No face under cursor")
            self.pending_normal_pick = False
            self._tpick = None
            return {"RUNNING_MODAL"}

        # --- toggles ---
        if event.type == "R" and event.value == "PRESS":
            self.align_mode = _cycle(self.align_mode, ALIGN_CYCLE)
            self._dirty = True
            self.report({"INFO"}, f"Alignment: {_align_label(self.align_mode)}")
            return {"RUNNING_MODAL"}

        # --- local rotation step presets (1..5 → degrees) ---
        if event.type in {"ONE", "TWO", "THREE", "FOUR", "FIVE"} and event.value == "PRESS":
            idx = {"ONE": 0, "TWO": 1, "THREE": 2, "FOUR": 3, "FIVE": 4}[event.type]
            self.local_rot_step = math.radians(LOCAL_ROT_STEP_PRESETS[idx])
            self.report({"INFO"}, f"Local rot step: {LOCAL_ROT_STEP_PRESETS[idx]:g}°")
            return {"RUNNING_MODAL"}

        # --- arrow keys nudge per-clone local rotation; Shift inverts direction ---
        if event.type in {"LEFT_ARROW", "RIGHT_ARROW", "UP_ARROW", "DOWN_ARROW"} and event.value == "PRESS":
            if event.type == "DOWN_ARROW":
                self.local_rot = [0.0, 0.0, 0.0]
                self.report({"INFO"}, "Local rotation reset")
            else:
                sign = -1.0 if event.shift else 1.0
                axis_idx = {"LEFT_ARROW": 0, "RIGHT_ARROW": 1, "UP_ARROW": 2}[event.type]
                self.local_rot[axis_idx] += sign * self.local_rot_step
                axis_letter = "XYZ"[axis_idx]
                self.report({"INFO"},
                            f"Local rot {axis_letter}: {math.degrees(self.local_rot[axis_idx]):.1f}°")
            self._dirty = True
            return {"RUNNING_MODAL"}

        # Start / Finish point toggles (S = first/start point, F = end/finish).
        if event.type == "S" and event.value == "PRESS":
            self.skip_first = not self.skip_first
            self._dirty = True
            self.report({"INFO"}, f"Start point clone: {'on' if self.skip_first else 'off'}")
            return {"RUNNING_MODAL"}

        if event.type == "F" and event.value == "PRESS":
            self.end_inclusive = not self.end_inclusive
            self._dirty = True
            self.report({"INFO"}, f"End point inclusive: {'on' if self.end_inclusive else 'off'}")
            return {"RUNNING_MODAL"}

        # E toggles axis-offset mode: drag the preview point to slide the array
        # along the rotation axis.
        if event.type == "E" and event.value == "PRESS":
            self.axis_offset_mode = not self.axis_offset_mode
            self._dirty = True
            self.report({"INFO"}, f"Axis offset mode: {'on' if self.axis_offset_mode else 'off'}")
            return {"RUNNING_MODAL"}

        # N toggles how locked clones display (SHOW ↔ HIDE). Picking is always
        # active: hover a clone and click to lock/unlock. Locked clones are
        # always excluded at apply.
        if event.type == "N" and event.value == "PRESS":
            self.skip_mode = _cycle(self.skip_mode, SKIP_CYCLE)
            self._dirty = True
            self.report({"INFO"}, f"Locked clones: {self.skip_mode}")
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
                    # default semicircle on −perp side; flipped → semicircle on +perp
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
                                self.arc_apex_h_signed = (ab_planar.length * 0.5)
                            except ReferenceError:
                                pass
                self._dirty = True
                self.report({"INFO"}, "Arc apex flipped")
            return {"RUNNING_MODAL"}

        # --- skip/delete picking (always active): hover-highlight, click to lock ---
        # Hover updates only when no drag is in progress; the event is NOT
        # consumed so ring/center/offset drags keep working.
        if event.type == "MOUSEMOVE" and not (self.radius_drag_active
                                              or self.arc_center_drag_active
                                              or self.axis_offset_drag_active):
            hs = self._nearest_slot(context, event)
            if hs != self._hover_slot:
                self._hover_slot = hs
                self._dirty = True
                context.area.tag_redraw()
        # Click ON a clone toggles its lock; a click elsewhere falls through to
        # the ring/center/offset controllers below.
        if event.type == "LEFTMOUSE" and event.value == "PRESS":
            hs = self._nearest_slot(context, event)
            if hs is not None:
                if hs in self.locked_slots:
                    self.locked_slots.discard(hs)
                else:
                    self.locked_slots.add(hs)
                self._dirty = True
                context.area.tag_redraw()
                return {"RUNNING_MODAL"}

        # --- axis-offset drag (E mode): slide the whole array along the axis ---
        if self.axis_offset_mode and event.type == "LEFTMOUSE" and event.value == "PRESS":
            self.axis_offset_drag_active = True
            return {"RUNNING_MODAL"}
        if self.axis_offset_drag_active and event.type == "MOUSEMOVE":
            axis_vec = _resolve_axis(self, context)
            params = _arc_params(self, axis_vec)
            center = params[0] if params is not None else self.pivot_co.copy()
            base_center = center - axis_vec * self.axis_offset   # undo current offset
            s = _mouse_signed_along_axis(context, event, base_center, axis_vec)
            if s is not None:
                self.axis_offset = s
                self._dirty = True
            return {"RUNNING_MODAL"}
        if self.axis_offset_drag_active and event.type == "LEFTMOUSE" and event.value == "RELEASE":
            self.axis_offset_drag_active = False
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
            self._tpick = None
            context.area.tag_redraw()
            self.report({"INFO"}, "Face pick cancelled")
            return {"RUNNING_MODAL"}

        if event.type in {"ESC", "RIGHTMOUSE"} and event.value == "PRESS":
            self._cleanup()
            return {"CANCELLED"}

        return {"RUNNING_MODAL"}

    def _tpick_update(self, context, event):
        """Raycast under the mouse and snapshot the hovered face for the T-pick
        overlay: triangulated fill, boundary edges, candidate snap points
        (edge midpoints + face center), the closest snap to the hit, and the
        face normal. Stores the result on `self._tpick` (None when nothing hit)."""
        region = context.region
        rv3d = context.region_data
        if region is None or rv3d is None:
            self._tpick = None
            return
        from bpy_extras.view3d_utils import region_2d_to_origin_3d, region_2d_to_vector_3d
        mouse = Vector((event.mouse_region_x, event.mouse_region_y))
        origin = region_2d_to_origin_3d(region, rv3d, mouse)
        direction = region_2d_to_vector_3d(region, rv3d, mouse)
        depsgraph = context.evaluated_depsgraph_get()
        hit, loc, normal, idx, obj, mat = context.scene.ray_cast(depsgraph, origin, direction)
        if not hit or obj is None:
            self._tpick = None
            return
        try:
            mesh = obj.evaluated_get(depsgraph).data
            poly = mesh.polygons[idx]
            vids = list(poly.vertices)
            vw = [mat @ mesh.vertices[vi].co for vi in vids]
        except (AttributeError, IndexError, ReferenceError):
            self._tpick = None
            return
        n = len(vw)
        if n < 3:
            self._tpick = None
            return
        center = mat @ poly.center
        mids = [(vw[i] + vw[(i + 1) % n]) * 0.5 for i in range(n)]
        # Snap candidates: face corner vertices + edge midpoints + face center.
        snaps = list(vw) + mids + [center]
        closest = min(snaps, key=lambda p: (p - loc).length)
        tris = []
        for i in range(1, n - 1):
            tris.extend([vw[0], vw[i], vw[i + 1]])
        edges = []
        for i in range(n):
            edges.append(vw[i])
            edges.append(vw[(i + 1) % n])
        nlen = sum((m - center).length for m in mids) / n if n else 0.3
        self._tpick = {
            "tris": tris, "edges": edges, "snaps": snaps,
            "closest": closest, "normal": normal.normalized(),
            "nlen": max(nlen, 1e-3),
        }

    # --- modal undo (Ctrl+Z) ------------------------------------------------
    _UNDO_KEYS = ("count", "pivot_mode", "clone_mode", "arc_mode", "axis_mode",
                  "align_mode", "skip_first", "end_inclusive", "local_rot_step",
                  "radius_override", "arc_apex_h_signed", "axis_offset",
                  "axis_offset_mode", "source_mode", "skip_mode", "_pool_seed")
    _UNDO_MAX = 64

    def _snapshot(self):
        """Capture the undoable parameter state (Match is excluded — it moves
        real objects and has its own toggle)."""
        snap = {k: getattr(self, k) for k in self._UNDO_KEYS}
        snap["local_rot"] = list(self.local_rot)
        snap["locked_slots"] = set(self.locked_slots)
        snap["pivot_co"] = self.pivot_co.copy()
        return snap

    def _commit_history(self):
        """Record the current state if it changed since the last committed one.
        Called at the top of modal so each event's result is committed before
        the next event — undo/redo then just walk the `_history` index. Skipped
        during drags (so a whole drag is one undo step) and while Match is
        active (Match moves real objects and has its own toggle)."""
        if getattr(self, "match_active", False):
            return
        if (self.radius_drag_active or self.arc_center_drag_active
                or self.axis_offset_drag_active):
            return
        if not self._history:
            self._history = [self._snapshot()]
            self._hist_i = 0
            return
        snap = self._snapshot()
        if snap == self._history[self._hist_i]:
            return
        del self._history[self._hist_i + 1:]      # drop redo branch
        self._history.append(snap)
        if len(self._history) > self._UNDO_MAX:
            self._history.pop(0)
        self._hist_i = len(self._history) - 1

    def _restore(self, context, snap):
        for k in self._UNDO_KEYS:
            setattr(self, k, snap[k])
        self.local_rot = list(snap["local_rot"])
        self.locked_slots = set(snap["locked_slots"])
        self.pivot_co = snap["pivot_co"].copy()
        self._hover_slot = None
        self._rebuild_sources(context)
        self._dirty = True

    def _resolve_pivot(self, context):
        """Set self.pivot_co / self.pivot_obj from the current pivot mode:
          * ACTIVE         — center & axis at the active object.
          * CURSOR         — center at the 3D cursor.
          * ACTIVE_CURSOR  — axis from the cursor, but the circle plane is lifted
                             along that axis to pass through the active object
                             (center = cursor, shifted axially to active's level).
        The ACTIVE_CURSOR center depends on the axis, so this must be re-run
        whenever the axis or the pivot mode changes."""
        active = context.active_object
        cursor = context.scene.cursor
        if self.pivot_mode == PIVOT_ACTIVE:
            self.pivot_obj = active
            self.pivot_co = (active.matrix_world.translation.copy()
                             if active else cursor.location.copy())
        elif self.pivot_mode == PIVOT_CURSOR:
            self.pivot_obj = None
            self.pivot_co = cursor.location.copy()
        else:  # PIVOT_ACTIVE_CURSOR
            self.pivot_obj = None
            cur = cursor.location.copy()
            axis = _resolve_axis(self, context)
            if active is not None and axis.length > 1e-6:
                act = active.matrix_world.translation
                # cursor in-plane position, but on the plane that passes through active
                self.pivot_co = cur + axis * (act - cur).dot(axis)
            else:
                self.pivot_co = cur

    def _nearest_slot(self, context, event):
        """Slot index whose ring position is closest to the mouse on screen
        (within a pixel threshold), among the slots that get a clone. None if
        nothing is close enough."""
        region = context.region
        rv3d = context.region_data
        if region is None or rv3d is None:
            return None
        from bpy_extras.view3d_utils import location_3d_to_region_2d
        axis_vec = _resolve_axis(self, context)
        positions = _slot_positions(self, axis_vec)
        if not positions:
            return None
        mouse = Vector((event.mouse_region_x, event.mouse_region_y))
        best_ci, best_d = None, 1e9
        for ci in _drawn_slot_range(self):
            if ci >= len(positions):
                continue
            p2 = location_3d_to_region_2d(region, rv3d, positions[ci])
            if p2 is None:
                continue
            d = (p2 - mouse).length
            if d < best_d:
                best_d, best_ci = d, ci
        return best_ci if best_d <= 40.0 else None

    def _rebuild_sources(self, context):
        """Resolve source roots + subtree snapshots according to current source_mode.
        Updates self.subtree_data, self.sources, self.anchor_obj. Also pre-builds
        a per-mesh geometry cache (verts_local + edge/tri indices) so the modal
        redraw path doesn't re-walk mesh topology per slot."""
        roots, anchor = _resolve_source_roots(context, self.source_mode)
        include_children = self.source_mode in (SOURCE_HIERARCHY, SOURCE_GROUP, SOURCE_POOL)
        self.subtree_data = _build_subtree_data(roots, include_children)
        self.sources = roots
        self.anchor_obj = anchor
        cache = {}
        for sub in self.subtree_data:
            for child_obj, _rel in sub:
                if child_obj.type == "MESH" and child_obj.data is not None and child_obj not in cache:
                    try:
                        cache[child_obj] = _mesh_geom_cache(child_obj)
                    except (ReferenceError, AttributeError):
                        pass
        self._mesh_cache = cache

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
            if self.align_mode == ALIGN_ROTATE:
                # Rigid hand-rotation: spin the source by its slot angle.
                R_step = Matrix.Rotation(best_i * slot_step, 4, axis_vec).to_3x3()
                base_mw = (R_step @ original_root_mw.to_3x3()).to_4x4()
            else:
                # ALIGN/RANDOM: aim +X at center for this slot (no extra R_step).
                base_mw = _aim_radial(original_root_mw, axis_vec, slot_pos, arc_center)
            base_mw.translation = slot_pos
            final_mw = _aligned_clone_mw(self.align_mode, arc_center, axis_vec,
                                         base_mw, self._pool_seed, best_i,
                                         local_rot=tuple(self.local_rot))
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
        self.pivot_mode  = PIVOT_ACTIVE_CURSOR
        self.clone_mode  = CLONE_DUP
        self.arc_mode    = ARC_FULL
        self.axis_mode   = AXIS_CURSOR_Z   # default: rotate around the 3D cursor's Z
        self.align_mode  = ALIGN_ALIGN
        self.local_rot_step = math.radians(90.0)
        self.local_rot = [0.0, 0.0, 0.0]
        self.skip_first  = False
        self.end_inclusive = True
        self.count = 6
        self.pending_normal_pick = False
        self._tpick = None
        self.skip_mode = SKIP_SHOW
        self.locked_slots = set()
        self._hover_slot = None
        self.radius_override = None
        self.radius_drag_active = False
        self.arc_center_drag_active = False
        self.arc_apex_h_signed = None
        self.axis_offset = 0.0
        self.axis_offset_mode = False
        self.axis_offset_drag_active = False
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

        # skip_first (F) clones slot 0 too — works for every arc mode, including
        # the Active→Cursor arc, not just the full circle.
        start_index = 0 if self.skip_first else 1

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
                # Clones live only in the addon's _RadialArray_ collection. Fall back
                # to the source object's collections only when there's no ra_coll.
                if ra_coll is not None:
                    try:
                        ra_coll.objects.link(new)
                    except RuntimeError:
                        pass
                else:
                    for c in child_obj.users_collection:
                        try:
                            c.objects.link(new)
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
                anchor_base_raw = _build_anchor_matrix(self)
                _replace_params = _arc_params(self, axis_vec)
                replace_center = _replace_params[0] if _replace_params is not None else self.pivot_co
                M_slot0 = _clone_matrix(self.pivot_co, axis_vec, _arc_effective_start(self, axis_vec), anchor_eff)
                # Base orientation per align mode for slot 0; R_step co-rotates per slot.
                anchor_actual = _base_anchor(self.align_mode, anchor_base_raw, axis_vec, M_slot0.translation, replace_center)
                base0 = anchor_actual.copy()
                base0.translation = M_slot0.translation
                M_final0 = _aligned_clone_mw(self.align_mode, replace_center, axis_vec,
                                             base0, self._pool_seed, 0,
                                             local_rot=tuple(self.local_rot))
                # Divide by the RAW (untilted) anchor — the tilt is carried by
                # M_final0; dividing by the tilted anchor would cancel it.
                delta = M_final0 @ anchor_base_raw.inverted()
                for subtree in subtrees:
                    _replace_subtree(subtree, delta)
                # Build the rest as instances around the ring.
                if ra_coll is None:
                    first_root_name = subtrees[0][0][0].name
                    ra_coll = bpy.data.collections.new(f"_RadialArray_{first_root_name}")
                    context.scene.collection.children.link(ra_coll)
                for ci, angle in _iter_clone_angles(_arc_effective_start(self, axis_vec), step, n_clones, start_index=start_index):
                    M_anchor = _clone_matrix(self.pivot_co, axis_vec, angle, anchor_eff)
                    R_step = Matrix.Rotation(ci * step, 4, axis_vec).to_3x3()
                    base_i = (R_step @ anchor_actual.to_3x3()).to_4x4()
                    base_i.translation = M_anchor.translation
                    M_final = _aligned_clone_mw(self.align_mode, replace_center, axis_vec,
                                                base_i, self._pool_seed, ci,
                                                local_rot=tuple(self.local_rot))
                    delta_i = M_final @ anchor_base_raw.inverted()
                    for subtree in subtrees:
                        _clone_subtree(subtree, delta_i)
        elif self.source_mode == SOURCE_POOL:
            for s, (delta, subtree, _slot_pos) in enumerate(_pool_fill_iter(self, axis_vec)):
                if s in self.locked_slots:
                    continue
                _clone_subtree(subtree, delta)
        else:
            params = _arc_params(self, axis_vec)
            if params is None:
                return
            arc_center, arc_R, arc_start, arc_sweep = params
            right, fwd = _arc_frame(axis_vec)
            anchor_raw = _build_anchor_matrix(self)
            # Base orientation per align mode for slot 0; R_step co-rotates it per
            # slot (ALIGN keeps X at center; ROTATE spins the source frame).
            _pos0 = arc_center + (right * math.cos(arc_start) + fwd * math.sin(arc_start)) * arc_R
            anchor_actual = _base_anchor(self.align_mode, anchor_raw, axis_vec, _pos0, arc_center)
            n_total = max(2, int(self.count))
            if self.arc_mode == ARC_FULL:
                slot_step = (2 * math.pi) / n_total
            else:
                slot_step = arc_sweep / (n_total - 1) if (n_total > 1 and self.end_inclusive) else arc_sweep / max(1, n_total)
            step = slot_step  # for downstream R_step
            all_positions = []
            for ci in range(n_total):
                a = arc_start + ci * slot_step
                all_positions.append(arc_center + (right * math.cos(a) + fwd * math.sin(a)) * arc_R)

            for ci in range(start_index, n_total):
                if ci in self.locked_slots:
                    continue   # clone locked out via skip/delete mode
                slot_pos = all_positions[ci]
                R_step = Matrix.Rotation(ci * step, 4, axis_vec).to_3x3()
                base_mw = (R_step @ anchor_actual.to_3x3()).to_4x4()
                base_mw.translation = slot_pos
                M_final = _aligned_clone_mw(
                    self.align_mode, arc_center, axis_vec, base_mw,
                    self._pool_seed, ci,
                    local_rot=tuple(self.local_rot))
                # Divide by the RAW (untilted) anchor — the tilt is carried by
                # M_final; dividing by the tilted anchor would cancel it and the
                # clones would tumble instead of staying flat in the axis plane.
                delta = M_final @ anchor_raw.inverted()
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
