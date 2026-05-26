import bpy
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
