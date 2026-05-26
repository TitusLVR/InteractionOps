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
        HUDItem("Pivot mode",     "P",                  ItemState.ON, default_state=ItemState.OFF, always_show=True),
        HUDItem("Clone type",     "I",                  ItemState.ON, default_state=ItemState.OFF, always_show=True),
        HUDItem("Arc mode",       "A",                  ItemState.ON, default_state=ItemState.OFF, always_show=True),
        HUDItem("Axis X/Y/Z",     "X / Y / Z",          ItemState.ON, default_state=ItemState.OFF, always_show=True),
        HUDItem("Local axis",     "L",                  ItemState.ON, default_state=ItemState.OFF, always_show=True),
        HUDItem("View axis",      "V",                  ItemState.ON, default_state=ItemState.OFF, always_show=True),
        HUDItem("Normal pick",    "N + LMB",            ItemState.ON, default_state=ItemState.OFF, always_show=True),
        HUDItem("Face outward",   "R",                  ItemState.ON, default_state=ItemState.OFF, always_show=True),
        HUDItem("Skip first",     "O",                  ItemState.ON, default_state=ItemState.OFF, always_show=True),
        HUDItem("End inclusive",  "E",                  ItemState.ON, default_state=ItemState.OFF, always_show=True),
        HUDItem("Count +/-",      "+ / -  or  Wheel",   ItemState.ON, default_state=ItemState.OFF, always_show=True),
        HUDItem("Angle drag",     "G + mouse",          ItemState.ON, default_state=ItemState.OFF, always_show=True),
        HUDItem("Start offset",   "S + digits",         ItemState.ON, default_state=ItemState.OFF, always_show=True),
        HUDItem("Apply",          "LMB / Enter / Space",ItemState.ON, default_state=ItemState.OFF, always_show=True),
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
CLONE_CYCLE        = (CLONE_DUP, CLONE_INST)

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


def _iter_clone_angles(start_offset, step, n_clones):
    """Yield (clone_index, angle) for each clone. Index 0 reserved for source position."""
    for i in range(1, n_clones + 1):
        yield i, start_offset + i * step


# --- Preview (POST_VIEW) -------------------------------------------------

def _mesh_edge_segments_world(obj_mw, mesh):
    """Return list of (Vector, Vector) world-space edge segments for a mesh."""
    verts_world = [obj_mw @ v.co for v in mesh.vertices]
    return [(verts_world[e.vertices[0]], verts_world[e.vertices[1]]) for e in mesh.edges]


def _build_ghost_segments(op, context):
    """Build the list of edge segments (in world space) for every predicted clone."""
    axis_vec = _resolve_axis(op, context)
    ang_total, step, n_clones = _compute_arc(op, axis_vec)

    segs = []
    crosses = []

    for subtree in op.subtree_data:
        root_obj = subtree[0][0]
        root_mw = root_obj.matrix_world.copy()

        for ci, angle in _iter_clone_angles(op.start_offset, step, n_clones):
            if op.skip_first and ci == 0:
                continue
            M_root = _clone_matrix(op.pivot_co, axis_vec, angle, op.align_to_radius, root_mw)
            delta = M_root @ root_mw.inverted()
            for child_obj, rel in subtree:
                child_clone_mw = delta @ child_obj.matrix_world
                if child_obj.type == "MESH" and child_obj.data is not None:
                    for a, b in _mesh_edge_segments_world(child_clone_mw, child_obj.data):
                        segs.append((a, b))
                else:
                    crosses.append(child_clone_mw.translation.copy())

    return segs, crosses, axis_vec, ang_total


def _draw_preview_3d(op, context):
    """POST_VIEW draw: ghost wires + axis line + arc/circle + pivot."""
    from ..ui import draw as iops_draw

    if op._dirty or getattr(op, "_ghost_cache", None) is None:
        op._ghost_cache = _build_ghost_segments(op, context)
        op._dirty = False
    segs, crosses, axis_vec, ang_total = op._ghost_cache

    if segs:
        flat = []
        for a, b in segs:
            flat.append(a)
            flat.append(b)
        iops_draw.edges_3d(flat, role=Role.PREVIEW_LINE, context=context)

    if crosses:
        iops_draw.points(crosses, role=Role.PREVIEW_POINT, context=context)

    # axis line through pivot
    max_r = 0.0
    for sub in op.subtree_data:
        root = sub[0][0]
        r = (root.matrix_world.translation - op.pivot_co).length
        if r > max_r:
            max_r = r
    if max_r < 1e-3:
        max_r = 1.0
    a_half = axis_vec * (max_r * 2.0)
    iops_draw.edges_3d([op.pivot_co - a_half, op.pivot_co + a_half],
                       role=Role.ACTIVE_LINE, context=context)

    # circle/arc in plane perpendicular to axis
    if max_r > 1e-3:
        steps = 64
        up = axis_vec
        right = Vector((1, 0, 0)) if abs(up.x) < 0.9 else Vector((0, 1, 0))
        right = (right - up * right.dot(up)).normalized()
        fwd = up.cross(right)
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
        self.pivot_mode  = PIVOT_ACTIVE
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
        self._dirty = True

        pivot_co, pivot_obj, sources, end_target = _resolve_selection(context, self.pivot_mode)
        if not sources:
            self.report({"WARNING"}, "Select at least one source object besides the pivot")
            return {"CANCELLED"}

        self.pivot_co  = pivot_co
        self.pivot_obj = pivot_obj
        self.sources   = sources
        self.end_target = end_target

        # snapshot subtree matrices once (relative to source root)
        self.subtree_data = []
        for root in sources:
            root_inv = root.matrix_world.inverted()
            subtree = []
            for child in _subtree_roots_and_descendants(root):
                subtree.append((child, root_inv @ child.matrix_world))
            self.subtree_data.append(subtree)

        self._hud = _build_hud(context)
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

        if event.type in {"MIDDLEMOUSE", "WHEELUPMOUSE", "WHEELDOWNMOUSE"} and event.value != "PRESS":
            return {"PASS_THROUGH"}

        if event.type in {"LEFTMOUSE", "RET", "NUMPAD_ENTER", "SPACE"} and event.value == "PRESS":
            self._cleanup()
            return {"FINISHED"}

        if event.type in {"ESC", "RIGHTMOUSE"} and event.value == "PRESS":
            self._cleanup()
            return {"CANCELLED"}

        return {"RUNNING_MODAL"}

    def _cleanup(self):
        if getattr(self, "_handle", None) is not None:
            safe_handler_remove(self._handle, bpy.types.SpaceView3D, "WINDOW")
            self._handle = None
        if getattr(self, "_handle_3d", None) is not None:
            safe_handler_remove(self._handle_3d, bpy.types.SpaceView3D, "WINDOW")
            self._handle_3d = None
