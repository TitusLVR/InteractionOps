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


def _iter_clone_angles(start_offset, step, n_clones, start_index=1):
    """Yield (clone_index, angle) for each clone. Index 0 reserved for source position."""
    for i in range(start_index, n_clones + 1):
        yield i, start_offset + i * step


# --- Preview (POST_VIEW) -------------------------------------------------

def _mesh_edge_segments_world(obj_mw, mesh):
    """Return list of (Vector, Vector) world-space edge segments for a mesh."""
    verts_world = [obj_mw @ v.co for v in mesh.vertices]
    return [(verts_world[e.vertices[0]], verts_world[e.vertices[1]]) for e in mesh.edges]


def _build_ghost_segments(op, context):
    """Build the list of edge segments (in world space) for every predicted clone."""
    # Drop any subtrees whose objects have been removed since invoke().
    valid = []
    for sub in op.subtree_data:
        try:
            sub[0][0].matrix_world  # touch to detect dead StructRNA
            valid.append(sub)
        except ReferenceError:
            continue
    op.subtree_data = valid

    axis_vec = _resolve_axis(op, context)
    ang_total, step, n_clones = _compute_arc(op, axis_vec)

    segs = []
    crosses = []

    if op.arc_mode == ARC_FULL and op.skip_first:
        start_index = 0
    else:
        start_index = 1

    subtrees = (op.subtree_data[:1] if op.arc_mode == ARC_TWO_POINTS else op.subtree_data)
    for subtree in subtrees:
        root_obj = subtree[0][0]
        root_mw = root_obj.matrix_world.copy()

        for ci, angle in _iter_clone_angles(op.start_offset, step, n_clones, start_index=start_index):
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
    from ..ui.draw import primitives as iops_draw

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
        # With a single object selected, default to 3D-cursor pivot so the
        # object can be arrayed around the cursor without needing a 2nd object.
        self.pivot_mode  = PIVOT_CURSOR if len(sel) == 1 else PIVOT_ACTIVE
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
        self._hud.add_param(HUDParam("Pivot",       lambda: self.pivot_mode, "str"))
        self._hud.add_param(HUDParam("Clone",       lambda: self.clone_mode, "str"))
        self._hud.add_param(HUDParam("Arc",         lambda: self.arc_mode, "str"))
        self._hud.add_param(HUDParam("Axis",        lambda: self.axis_mode, "str"))
        self._hud.add_param(HUDParam("Count",       lambda: self.count, "int"))
        self._hud.add_param(HUDParam("Angle",       lambda: math.degrees(self.arc_angle), "float", fmt="{:.1f}°",
                                     active_getter=lambda: self.arc_mode == ARC_ANGLE))
        self._hud.add_param(HUDParam("Offset",      lambda: math.degrees(self.start_offset), "float", fmt="{:.1f}°",
                                     active_getter=lambda: self.start_offset_enabled))
        self._hud.add_param(HUDParam("Face outward", lambda: self.align_to_radius, "bool"))
        self._hud.add_param(HUDParam("Skip first",   lambda: self.skip_first, "bool"))
        self._hud.add_param(HUDParam("End inclusive", lambda: self.end_inclusive, "bool",
                                     active_getter=lambda: self.arc_mode in (ARC_ANGLE, ARC_TWO_POINTS)))
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

        # --- mode cycles ---
        if event.type == "P" and event.value == "PRESS":
            self.pivot_mode = _cycle(self.pivot_mode, PIVOT_CYCLE)
            pivot_co, pivot_obj, sources, end_target = _resolve_selection(context, self.pivot_mode)
            if sources:
                self.pivot_co = pivot_co
                self.pivot_obj = pivot_obj
                self.sources = sources
                self.end_target = end_target
                # rebuild subtree snapshots
                self.subtree_data = []
                for root in sources:
                    root_inv = root.matrix_world.inverted()
                    subtree = []
                    for child in _subtree_roots_and_descendants(root):
                        subtree.append((child, root_inv @ child.matrix_world))
                    self.subtree_data.append(subtree)
            self._dirty = True
            return {"RUNNING_MODAL"}

        if event.type == "I" and event.value == "PRESS":
            self.clone_mode = _cycle(self.clone_mode, CLONE_CYCLE)
            return {"RUNNING_MODAL"}

        if event.type == "A" and event.value == "PRESS":
            self.arc_mode = _cycle(self.arc_mode, ARC_CYCLE)
            self._dirty = True
            return {"RUNNING_MODAL"}

        # --- axis ---
        if event.type in {"X", "Y", "Z"} and event.value == "PRESS":
            self.axis_mode = {"X": AXIS_GLOBAL_X, "Y": AXIS_GLOBAL_Y, "Z": AXIS_GLOBAL_Z}[event.type]
            self.pending_normal_pick = False
            self._dirty = True
            return {"RUNNING_MODAL"}

        if event.type == "L" and event.value == "PRESS":
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

        if event.type == "N" and event.value == "PRESS":
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

        if event.type == "O" and event.value == "PRESS":
            self.skip_first = not self.skip_first
            self._dirty = True
            return {"RUNNING_MODAL"}

        if event.type == "E" and event.value == "PRESS":
            self.end_inclusive = not self.end_inclusive
            self._dirty = True
            return {"RUNNING_MODAL"}

        # --- count ---
        if event.type in {"NUMPAD_PLUS", "EQUAL", "WHEELUPMOUSE"} and event.value == "PRESS" \
                and (event.type == "WHEELUPMOUSE" or self.numeric_channel is None):
            step = 10 if event.ctrl else 1
            self.count = min(1024, self.count + step)
            self._dirty = True
            return {"RUNNING_MODAL"}
        if event.type in {"NUMPAD_MINUS", "MINUS", "WHEELDOWNMOUSE"} and event.value == "PRESS" \
                and (event.type == "WHEELDOWNMOUSE" or self.numeric_channel is None):
            step = 10 if event.ctrl else 1
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

        if event.type in {"LEFTMOUSE", "RET", "NUMPAD_ENTER", "SPACE"} and event.value == "PRESS":
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
        for subtree in subtrees:
            root_obj = subtree[0][0]
            try:
                root_mw = root_obj.matrix_world.copy()
            except ReferenceError:
                continue  # source object was removed since invoke()

            ra_name = f"_RadialArray_{root_obj.name}"
            ra_coll = bpy.data.collections.new(ra_name)  # Blender uniquifies
            context.scene.collection.children.link(ra_coll)

            for ci, angle in _iter_clone_angles(self.start_offset, step, n_clones, start_index=start_index):
                M_root = _clone_matrix(self.pivot_co, axis_vec, angle,
                                       self.align_to_radius, root_mw)
                delta = M_root @ root_mw.inverted()

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
                    if new.name not in ra_coll.objects:
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

                created_roots.append(clone_map[root_obj])

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
