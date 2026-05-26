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
        HUDItem("Arc mode",       "W",                  ItemState.ON, default_state=ItemState.OFF, always_show=True),
        HUDItem("End inclusive",  "E",                  ItemState.ON, default_state=ItemState.OFF, always_show=True),
        HUDItem("Face outward",   "R",                  ItemState.ON, default_state=ItemState.OFF, always_show=True),
        HUDItem("Start offset",   "S + digits",         ItemState.ON, default_state=ItemState.OFF, always_show=True),
        HUDItem("Clone type",     "D",                  ItemState.ON, default_state=ItemState.OFF, always_show=True),
        HUDItem("Skip first",     "F",                  ItemState.ON, default_state=ItemState.OFF, always_show=True),
        HUDItem("Axis X/Y/Z",     "X / Y / Z",          ItemState.ON, default_state=ItemState.OFF, always_show=True),
        HUDItem("Local axis",     "C",                  ItemState.ON, default_state=ItemState.OFF, always_show=True),
        HUDItem("View axis",      "V",                  ItemState.ON, default_state=ItemState.OFF, always_show=True),
        HUDItem("Normal pick",    "T + LMB",            ItemState.ON, default_state=ItemState.OFF, always_show=True),
        HUDItem("Angle drag",     "G + mouse",          ItemState.ON, default_state=ItemState.OFF, always_show=True),
        HUDItem("Count +/-",      "+ / -  or  Ctrl+Wheel", ItemState.ON, default_state=ItemState.OFF, always_show=True),
        HUDItem("Radius drag",    "LMB on ring + drag", ItemState.ON, default_state=ItemState.OFF, always_show=True),
        HUDItem("Arc end drag",   "LMB on end marker + drag", ItemState.ON, default_state=ItemState.OFF, always_show=True),
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

ARC_FULL           = "FULL_360"
ARC_ANGLE          = "ARC_ANGLE"
ARC_TWO_POINTS     = "ARC_TWO_POINTS"
ARC_CYCLE          = (ARC_FULL, ARC_ANGLE, ARC_TWO_POINTS)

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

    end_target is the last-selected object (for ARC_TWO_POINTS), distinct from pivot_object and
    from source_roots[0]. May be None if not applicable.
    """
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

    end_target = None
    if sources:
        for o in reversed(sel):
            if o is pivot_obj:
                continue
            if o is sources[0]:
                continue
            end_target = o
            break

    return pivot_co, pivot_obj, sources, end_target


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


def _compute_arc(self, axis_vec):
    """Return (arc_angle_radians, step_radians, n_clones) for the current mode."""
    n = max(2, int(self.count))
    if self.arc_mode == ARC_FULL:
        step = 2 * math.pi / n
        return 2 * math.pi, step, n - 1
    if self.arc_mode == ARC_ANGLE:
        ang = self.arc_angle
        if abs(ang) < 1e-8:
            return 0.0, 0.0, 0
        step = ang / (n - 1) if self.end_inclusive else ang / n
        return ang, step, n - 1
    # ARC_TWO_POINTS
    if not self.sources or self.end_target is None:
        return 0.0, 0.0, 0
    start_vec = self.sources[0].matrix_world.translation - self.pivot_co
    end_vec   = self.end_target.matrix_world.translation - self.pivot_co
    ang = _signed_angle_around(start_vec, end_vec, axis_vec)
    if abs(ang) < 1e-6:
        ang = 2 * math.pi
    step = ang / (n - 1) if self.end_inclusive else ang / n
    return ang, step, n - 1


def _clone_matrix(pivot_co, axis_vec, angle, align_to_radius, source_mw):
    """Compute world matrix for a clone of a source root at given angle around pivot."""
    R = Matrix.Rotation(angle, 4, axis_vec)
    T_to   = Matrix.Translation(pivot_co)
    T_from = Matrix.Translation(-pivot_co)
    M = T_to @ R @ T_from @ source_mw

    if align_to_radius:
        clone_pos = M.translation
        radial = (clone_pos - pivot_co)
        radial = radial - axis_vec * radial.dot(axis_vec)
        if radial.length > 1e-6:
            radial.normalize()
            src_x = (source_mw.to_3x3() @ Vector((1, 0, 0)))
            src_x = src_x - axis_vec * src_x.dot(axis_vec)
            if src_x.length > 1e-6:
                src_x.normalize()
                extra_ang = _signed_angle_around(src_x, radial, axis_vec)
                R_extra = Matrix.Rotation(extra_ang, 4, axis_vec)
                T_cto   = Matrix.Translation(clone_pos)
                T_cfrom = Matrix.Translation(-clone_pos)
                M = T_cto @ R_extra @ T_cfrom @ M
    return M


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
    """Max distance from pivot to any source root, in world space."""
    max_r = 0.0
    for sub in op.subtree_data:
        root = sub[0][0]
        try:
            r = (root.matrix_world.translation - op.pivot_co).length
        except ReferenceError:
            continue
        if r > max_r:
            max_r = r
    return max_r


def _effective_radius(op):
    """Active array radius: override if set, else the natural source distance."""
    if op.radius_override is not None:
        return op.radius_override
    r = _natural_radius(op)
    return r if r > 1e-6 else 1.0


def _effective_source_mw(source_mw, pivot_co, axis_vec, radius_override):
    """If radius_override is set, scale the source's radial offset (in the rotation plane)
    so its in-plane distance from pivot equals the override. Axial component is preserved."""
    if radius_override is None:
        return source_mw
    offset = source_mw.translation - pivot_co
    axial = axis_vec * offset.dot(axis_vec)
    radial = offset - axial
    cur = radial.length
    if cur < 1e-6:
        return source_mw  # can't scale a zero vector
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


def _arc_endpoint_world(op, axis_vec):
    """World position of the arc-end marker. None if no meaningful endpoint (FULL_360 has no endpoint)."""
    if op.arc_mode == ARC_FULL:
        return None
    if op.arc_mode == ARC_ANGLE:
        end_angle = op.start_offset + op.arc_angle
    else:  # ARC_TWO_POINTS — endpoint is the end_target's projected position
        if op.end_target is None:
            return None
        try:
            v = op.end_target.matrix_world.translation - op.pivot_co
        except ReferenceError:
            return None
        end_angle = math.atan2(v.dot(_arc_frame(axis_vec)[1]), v.dot(_arc_frame(axis_vec)[0]))
    right, fwd = _arc_frame(axis_vec)
    r = _effective_radius(op)
    return op.pivot_co + (right * math.cos(end_angle) + fwd * math.sin(end_angle)) * r


def _pool_fill_iter(op, axis_vec):
    """For pool_fill: yield (delta_matrix, subtree) per ring slot.
    Slot i takes subtree[i] if i < N, else a deterministic random pick from the pool.
    Subtree is rotated/translated so its root lands on the slot position at radius R."""
    import random
    N = len(op.subtree_data)
    if N == 0:
        return
    n_slots = max(1, int(op.count))
    if op.arc_mode == ARC_FULL:
        if op.skip_first:
            step = 2 * math.pi / n_slots
        else:
            step = 2 * math.pi / n_slots
    else:
        ang_total, _step_unused, _ = _compute_arc(op, axis_vec)
        if n_slots > 1:
            step = ang_total / (n_slots - 1) if op.end_inclusive else ang_total / n_slots
        else:
            step = 0.0
    rng = random.Random(op._pool_seed)
    radius = _effective_radius(op)
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
        ang = op.start_offset + s * step
        target_pos = op.pivot_co + (right * math.cos(ang) + fwd * math.sin(ang)) * radius
        new_mw = src_mw.copy()
        new_mw.translation = target_pos
        if op.align_to_radius:
            radial = target_pos - op.pivot_co
            radial = radial - axis_vec * radial.dot(axis_vec)
            if radial.length > 1e-6:
                radial.normalize()
                src_x = src_mw.to_3x3() @ Vector((1, 0, 0))
                src_x = src_x - axis_vec * src_x.dot(axis_vec)
                if src_x.length > 1e-6:
                    src_x.normalize()
                    extra_ang = _signed_angle_around(src_x, radial, axis_vec)
                    R = Matrix.Rotation(extra_ang, 4, axis_vec)
                    T_to = Matrix.Translation(target_pos)
                    T_from = Matrix.Translation(-target_pos)
                    new_mw = T_to @ R @ T_from @ new_mw
        delta = new_mw @ src_mw.inverted()
        yield delta, subtree


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

    if op.arc_mode == ARC_FULL and op.skip_first:
        start_index = 0
    else:
        start_index = 1

    subtrees = (op.subtree_data[:1] if op.arc_mode == ARC_TWO_POINTS else op.subtree_data)
    if not subtrees:
        return segs, tris, crosses, axis_vec, ang_total

    if op.source_mode == SOURCE_POOL:
        for delta, subtree in _pool_fill_iter(op, axis_vec):
            for child_obj, _rel in subtree:
                child_clone_mw = delta @ child_obj.matrix_world
                if child_obj.type == "MESH" and child_obj.data is not None:
                    for a, b in _mesh_edge_segments_world(child_clone_mw, child_obj.data):
                        segs.append((a, b))
                    tris.extend(_mesh_face_tris_world(child_clone_mw, child_obj.data))
                else:
                    crosses.append(child_clone_mw.translation.copy())
        return segs, tris, crosses, axis_vec, ang_total

    # Treat all sources as one rigid group: centroid is the rotation anchor.
    anchor_raw = Matrix.Translation(_group_anchor_co(op))
    anchor_eff = _effective_source_mw(anchor_raw, op.pivot_co, axis_vec, op.radius_override)

    for ci, angle in _iter_clone_angles(op.start_offset, step, n_clones, start_index=start_index):
        M_anchor = _clone_matrix(op.pivot_co, axis_vec, angle, op.align_to_radius, anchor_eff)
        delta = M_anchor @ anchor_raw.inverted()
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

    # axis line through pivot; use effective radius so ring tracks override drag
    max_r = _effective_radius(op)
    if max_r < 1e-3:
        max_r = 1.0
    a_half = axis_vec * (max_r * 2.0)
    iops_draw.edges_3d([op.pivot_co - a_half, op.pivot_co + a_half],
                       role=Role.ACTIVE_LINE, context=context)

    # circle/arc in plane perpendicular to axis
    if max_r > 1e-3:
        steps = 64
        right, fwd = _arc_frame(axis_vec)
        sweep = ang_total if op.arc_mode != ARC_FULL else 2 * math.pi
        ring = []
        for i in range(steps + 1):
            t = i / steps
            ang = op.start_offset + t * sweep
            p = op.pivot_co + (right * math.cos(ang) + fwd * math.sin(ang)) * max_r
            ring.append(p)
        pairs = []
        for i in range(len(ring) - 1):
            pairs.append(ring[i])
            pairs.append(ring[i + 1])
        iops_draw.edges_3d(pairs, role=Role.PREVIEW_LINE, context=context)

    # pivot marker
    iops_draw.points([op.pivot_co], role=Role.PIVOT, context=context)

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
        self.align_to_radius = False
        self.skip_first  = False
        self.end_inclusive = True
        self.count = 6
        self.arc_angle = 0.0          # radians
        self.start_offset = 0.0       # radians
        self.start_offset_enabled = False
        self.numeric_channel = None   # None | "ANGLE" | "OFFSET"
        self.numeric_string = ""
        self.pending_normal_pick = False
        self._cached_axis_vec = Vector((0, 0, 1))
        self.radius_override = None       # None = use natural source distance
        self.radius_drag_active = False
        self.arc_end_drag_active = False
        self.match_active = False
        self._match_saved = None          # snapshot used to un-apply Match
        self.source_mode = SOURCE_GROUP   # U cycles ACTIVE / HIERARCHY / GROUP / POOL
        self.anchor_obj = None            # the active object when source_mode == GROUP
        self._pool_seed = 12345
        self._dirty = True

        pivot_co, pivot_obj, _legacy_sources, end_target = _resolve_selection(context, self.pivot_mode)
        self.pivot_co  = pivot_co
        self.pivot_obj = pivot_obj
        self.end_target = end_target

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
        self._hud.add_param(HUDParam("Angle",       lambda: math.degrees(self.arc_angle), "float", fmt="{:.1f}°",
                                     active_getter=lambda: self.arc_mode == ARC_ANGLE))
        self._hud.add_param(HUDParam("Offset",      lambda: math.degrees(self.start_offset), "float", fmt="{:.1f}°",
                                     active_getter=lambda: self.start_offset_enabled))
        self._hud.add_param(HUDParam("Face outward", lambda: self.align_to_radius, "bool"))
        self._hud.add_param(HUDParam("Skip first",   lambda: self.skip_first, "bool"))
        self._hud.add_param(HUDParam("End inclusive", lambda: self.end_inclusive, "bool",
                                     active_getter=lambda: self.arc_mode in (ARC_ANGLE, ARC_TWO_POINTS)))
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
            pivot_co, pivot_obj, _legacy_sources, end_target = _resolve_selection(context, self.pivot_mode)
            self.pivot_co = pivot_co
            self.pivot_obj = pivot_obj
            self.end_target = end_target
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
            self.align_to_radius = not self.align_to_radius
            self._dirty = True
            return {"RUNNING_MODAL"}

        if event.type == "F" and event.value == "PRESS":
            self.skip_first = not self.skip_first
            self._dirty = True
            return {"RUNNING_MODAL"}

        if event.type == "E" and event.value == "PRESS":
            self.end_inclusive = not self.end_inclusive
            self._dirty = True
            return {"RUNNING_MODAL"}

        # --- count (Ctrl+wheel, or NUMPAD_+/-, or EQUAL/MINUS when not typing) ---
        if event.type in {"NUMPAD_PLUS", "EQUAL", "WHEELUPMOUSE"} and event.value == "PRESS" \
                and (event.type == "WHEELUPMOUSE" and event.ctrl or
                     event.type in {"NUMPAD_PLUS", "EQUAL"} and self.numeric_channel is None):
            step = 10 if (event.shift and event.type == "WHEELUPMOUSE") else 1
            self.count = min(1024, self.count + step)
            self._dirty = True
            return {"RUNNING_MODAL"}
        if event.type in {"NUMPAD_MINUS", "MINUS", "WHEELDOWNMOUSE"} and event.value == "PRESS" \
                and (event.type == "WHEELDOWNMOUSE" and event.ctrl or
                     event.type in {"NUMPAD_MINUS", "MINUS"} and self.numeric_channel is None):
            step = 10 if (event.shift and event.type == "WHEELDOWNMOUSE") else 1
            self.count = max(2, self.count - step)
            self._dirty = True
            return {"RUNNING_MODAL"}

        # --- numeric channel selection ---
        if event.type == "G" and event.value == "PRESS":
            if self.numeric_channel == "ANGLE":
                self.numeric_channel = None
            else:
                self.numeric_channel = "ANGLE"
                self.numeric_string = ""
                self._angle_drag_start_x = event.mouse_region_x
                self._angle_drag_start_value = self.arc_angle
            return {"RUNNING_MODAL"}
        if event.type == "S" and event.value == "PRESS":
            if self.numeric_channel == "OFFSET":
                self.numeric_channel = None
                self.start_offset_enabled = not self.start_offset_enabled
            else:
                self.start_offset_enabled = True
                self.numeric_channel = "OFFSET"
                self.numeric_string = ""
            return {"RUNNING_MODAL"}

        # angle drag in ANGLE channel
        if self.numeric_channel == "ANGLE" and event.type == "MOUSEMOVE":
            dx = event.mouse_region_x - getattr(self, "_angle_drag_start_x", event.mouse_region_x)
            ang = getattr(self, "_angle_drag_start_value", 0.0) + math.radians(dx * 0.5)
            if event.ctrl and event.shift:
                snap = math.radians(15.0)
                ang = round(ang / snap) * snap
            elif event.ctrl:
                snap = math.radians(5.0)
                ang = round(ang / snap) * snap
            self.arc_angle = ang
            self._dirty = True
            return {"RUNNING_MODAL"}

        # numeric digits
        if self.numeric_channel is not None and event.value == "PRESS":
            digit_map = {
                "ZERO": "0", "ONE": "1", "TWO": "2", "THREE": "3", "FOUR": "4",
                "FIVE": "5", "SIX": "6", "SEVEN": "7", "EIGHT": "8", "NINE": "9",
                "NUMPAD_0": "0", "NUMPAD_1": "1", "NUMPAD_2": "2", "NUMPAD_3": "3",
                "NUMPAD_4": "4", "NUMPAD_5": "5", "NUMPAD_6": "6", "NUMPAD_7": "7",
                "NUMPAD_8": "8", "NUMPAD_9": "9",
            }
            if event.type in digit_map:
                self.numeric_string += digit_map[event.type]
            elif event.type in {"PERIOD", "NUMPAD_PERIOD"}:
                if "." not in self.numeric_string:
                    self.numeric_string += "."
            elif event.type == "BACK_SPACE":
                self.numeric_string = self.numeric_string[:-1]
            elif event.type == "MINUS":
                if self.numeric_string.startswith("-"):
                    self.numeric_string = self.numeric_string[1:]
                else:
                    self.numeric_string = "-" + self.numeric_string
            else:
                # not a digit-input key — let it fall through to other handlers below
                pass
            try:
                if self.numeric_string in ("", "-", ".", "-."):
                    val_deg = 0.0
                else:
                    val_deg = float(self.numeric_string)
                val_rad = math.radians(val_deg)
                if self.numeric_channel == "ANGLE":
                    self.arc_angle = val_rad
                elif self.numeric_channel == "OFFSET":
                    self.start_offset = val_rad
                self._dirty = True
            except ValueError:
                pass
            # Only consume if it was actually a numeric-input key
            if event.type in digit_map or event.type in {"PERIOD", "NUMPAD_PERIOD", "BACK_SPACE", "MINUS"}:
                return {"RUNNING_MODAL"}

        # --- LMB PRESS: hit-test arc endpoint first, then ring ---
        if event.type == "LEFTMOUSE" and event.value == "PRESS":
            axis_vec = _resolve_axis(self, context)
            hit = _mouse_on_rot_plane(context, event, self.pivot_co, axis_vec)
            cur_r = _effective_radius(self)
            # arc endpoint hit?
            end_pt = _arc_endpoint_world(self, axis_vec)
            if hit is not None and end_pt is not None:
                if (hit - end_pt).length < max(0.18 * cur_r, 0.3):
                    self.arc_end_drag_active = True
                    # Promote FULL_360 to ARC_ANGLE at full sweep so drag can shorten it.
                    if self.arc_mode == ARC_FULL:
                        self.arc_mode = ARC_ANGLE
                        self.arc_angle = 2 * math.pi
                    right, fwd = _arc_frame(axis_vec)
                    v = hit - self.pivot_co
                    self._arc_drag_prev_angle = math.atan2(v.dot(fwd), v.dot(right))
                    return {"RUNNING_MODAL"}
            # ring hit (radius)?
            if hit is not None:
                radial = hit - self.pivot_co
                radial = radial - axis_vec * radial.dot(axis_vec)
                r_mouse = radial.length
                tol = max(0.25 * cur_r, 0.4)
                if abs(r_mouse - cur_r) < tol:
                    self.radius_drag_active = True
                    self.radius_override = max(1e-4, r_mouse)
                    self._dirty = True
            return {"RUNNING_MODAL"}

        if self.radius_drag_active and event.type == "MOUSEMOVE":
            axis_vec = _resolve_axis(self, context)
            r_mouse = _mouse_radius_in_plane(context, event, self.pivot_co, axis_vec)
            if r_mouse is not None:
                self.radius_override = max(1e-4, r_mouse)
                self._dirty = True
            return {"RUNNING_MODAL"}

        if self.arc_end_drag_active and event.type == "MOUSEMOVE":
            axis_vec = _resolve_axis(self, context)
            hit = _mouse_on_rot_plane(context, event, self.pivot_co, axis_vec)
            if hit is not None:
                right, fwd = _arc_frame(axis_vec)
                v = hit - self.pivot_co
                cur_mouse_angle = math.atan2(v.dot(fwd), v.dot(right))
                # accumulate delta so drag is smooth across the +π/−π seam
                delta = cur_mouse_angle - getattr(self, "_arc_drag_prev_angle", cur_mouse_angle)
                while delta > math.pi:
                    delta -= 2 * math.pi
                while delta <= -math.pi:
                    delta += 2 * math.pi
                TWO_PI = 2 * math.pi
                new_arc = max(-TWO_PI, min(TWO_PI, self.arc_angle + delta))
                if event.ctrl and event.shift:
                    snap = math.radians(15.0)
                    new_arc = round(new_arc / snap) * snap
                elif event.ctrl:
                    snap = math.radians(5.0)
                    new_arc = round(new_arc / snap) * snap
                self.arc_angle = new_arc
                self._arc_drag_prev_angle = cur_mouse_angle
                # snap visual to full circle when sweep saturates
                if abs(self.arc_angle) >= TWO_PI - 1e-4:
                    self.arc_mode = ARC_FULL
                else:
                    self.arc_mode = ARC_ANGLE
                self._dirty = True
            return {"RUNNING_MODAL"}

        if event.type == "LEFTMOUSE" and event.value == "RELEASE" \
                and (self.radius_drag_active or self.arc_end_drag_active):
            self.radius_drag_active = False
            self.arc_end_drag_active = False
            return {"RUNNING_MODAL"}

        if event.type in {"RET", "NUMPAD_ENTER", "SPACE"} and event.value == "PRESS":
            self._apply(context)
            self._cleanup()
            return {"FINISHED"}

        if self.pending_normal_pick and event.type == "ESC" and event.value == "PRESS":
            self.pending_normal_pick = False
            self.report({"INFO"}, "Normal pick cancelled")
            return {"RUNNING_MODAL"}

        if event.type == "ESC" and event.value == "PRESS" and self.numeric_channel is not None:
            self.numeric_channel = None
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
        """Toggle: apply Match (compute pivot/radius/count from source origins)
        or restore the snapshot taken when Match was applied."""
        if self.match_active and self._match_saved is not None:
            s = self._match_saved
            self.pivot_co = s["pivot_co"]
            self.pivot_obj = s["pivot_obj"]
            self.pivot_mode = s["pivot_mode"]
            self.radius_override = s["radius_override"]
            self.count = s["count"]
            self.start_offset = s["start_offset"]
            self.start_offset_enabled = s["start_offset_enabled"]
            self.arc_angle = s["arc_angle"]
            self._match_saved = None
            self.match_active = False
            self._dirty = True
            self.report({"INFO"}, "Match undone")
            return

        origins = []
        for sub in self.subtree_data:
            try:
                origins.append(sub[0][0].matrix_world.translation.copy())
            except ReferenceError:
                continue
        if not origins:
            self.report({"WARNING"}, "No live source origins")
            return

        self._match_saved = {
            "pivot_co": self.pivot_co.copy(),
            "pivot_obj": self.pivot_obj,
            "pivot_mode": self.pivot_mode,
            "radius_override": self.radius_override,
            "count": self.count,
            "start_offset": self.start_offset,
            "start_offset_enabled": self.start_offset_enabled,
            "arc_angle": self.arc_angle,
        }

        center = Vector((0.0, 0.0, 0.0))
        for o in origins:
            center += o
        center /= len(origins)
        self.pivot_co = center
        self.pivot_obj = None
        self.pivot_mode = PIVOT_CURSOR

        axis_vec = _resolve_axis(self, context)
        radii = []
        for o in origins:
            v = o - center
            v_radial = v - axis_vec * v.dot(axis_vec)
            radii.append(v_radial.length)
        avg_r = sum(radii) / len(radii)
        self.radius_override = avg_r if avg_r > 1e-6 else None
        self.count = max(2, len(origins))

        if self.arc_mode != ARC_FULL and len(origins) >= 2:
            right, fwd = _arc_frame(axis_vec)
            angles = [math.atan2((o - center).dot(fwd), (o - center).dot(right))
                      for o in origins]
            self.start_offset = angles[0]
            self.start_offset_enabled = True
            sweep = angles[-1] - angles[0]
            while sweep > math.pi:
                sweep -= 2 * math.pi
            while sweep <= -math.pi:
                sweep += 2 * math.pi
            self.arc_angle = sweep

        self.match_active = True
        self._dirty = True
        self.report({"INFO"},
                    f"Matched from {len(origins)} origins: r={avg_r:.3f}, count={self.count}")

    def _reset_defaults(self):
        """Restore all parameters to factory defaults. Sources & pivot stay.
        Numeric channels and drag states close so the modal returns to idle."""
        self.pivot_mode  = PIVOT_CURSOR
        self.clone_mode  = CLONE_DUP
        self.arc_mode    = ARC_FULL
        self.axis_mode   = AXIS_GLOBAL_Z
        self.align_to_radius = False
        self.skip_first  = False
        self.end_inclusive = True
        self.count = 6
        self.arc_angle = 0.0
        self.start_offset = 0.0
        self.start_offset_enabled = False
        self.numeric_channel = None
        self.numeric_string = ""
        self.pending_normal_pick = False
        self.radius_override = None
        self.radius_drag_active = False
        self.arc_end_drag_active = False
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
        axis_vec = _resolve_axis(self, context)
        ang_total, step, n_clones = _compute_arc(self, axis_vec)
        if n_clones <= 0:
            return

        created_roots = []

        if self.arc_mode == ARC_FULL and self.skip_first:
            start_index = 0
        else:
            start_index = 1

        subtrees = (self.subtree_data[:1] if self.arc_mode == ARC_TWO_POINTS else self.subtree_data)
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
                for i, (delta, subtree) in enumerate(_pool_fill_iter(self, axis_vec)):
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
                anchor_eff = _effective_source_mw(anchor_raw, self.pivot_co, axis_vec, self.radius_override)
                M_anchor = _clone_matrix(self.pivot_co, axis_vec, self.start_offset,
                                         self.align_to_radius, anchor_eff)
                delta = M_anchor @ anchor_raw.inverted()
                for subtree in subtrees:
                    _replace_subtree(subtree, delta)
                # Build the rest as instances around the ring.
                if ra_coll is None:
                    first_root_name = subtrees[0][0][0].name
                    ra_coll = bpy.data.collections.new(f"_RadialArray_{first_root_name}")
                    context.scene.collection.children.link(ra_coll)
                for ci, angle in _iter_clone_angles(self.start_offset, step, n_clones, start_index=start_index):
                    M_anchor = _clone_matrix(self.pivot_co, axis_vec, angle,
                                             self.align_to_radius, anchor_eff)
                    delta_i = M_anchor @ anchor_raw.inverted()
                    for subtree in subtrees:
                        _clone_subtree(subtree, delta_i)
        elif self.source_mode == SOURCE_POOL:
            for delta, subtree in _pool_fill_iter(self, axis_vec):
                _clone_subtree(subtree, delta)
        else:
            anchor_raw = Matrix.Translation(_group_anchor_co(self))
            anchor_eff = _effective_source_mw(anchor_raw, self.pivot_co, axis_vec, self.radius_override)
            for ci, angle in _iter_clone_angles(self.start_offset, step, n_clones, start_index=start_index):
                M_anchor = _clone_matrix(self.pivot_co, axis_vec, angle,
                                         self.align_to_radius, anchor_eff)
                delta = M_anchor @ anchor_raw.inverted()
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
