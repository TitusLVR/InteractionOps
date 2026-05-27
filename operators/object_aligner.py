import bpy
import numpy as np
from mathutils import Matrix, Vector

from ..ui.draw import safe_handler_add, safe_handler_remove
from ..ui.draw import primitives as iops_draw
from ..ui.draw import draw_scope
from ..ui.draw.theme import Role
from ..ui.hud import (
    HUDOverlay, HelpOverlay, HUDSection, HUDItem,
    HUDParam, ItemState, capture_event,
)
from ..utils.picking import raycast_from_mouse
from ..utils.alignment_fit import solve_fit


# --- State enums ----------------------------------------------------------

MODE_PICK_REF = "PICK_REF"
MODE_STAMP    = "STAMP"

CLONE_DUP  = "DUPLICATE"
CLONE_INST = "INSTANCE"
CLONE_CYCLE = (CLONE_DUP, CLONE_INST)

SCALE_KEEP    = "KEEP"
SCALE_UNIFORM = "UNIFORM"
SCALE_STRETCH = "STRETCH"
SCALE_CYCLE   = (SCALE_UNIFORM, SCALE_KEEP, SCALE_STRETCH)
SCALE_LABELS  = {SCALE_KEEP: "Keep", SCALE_UNIFORM: "Uniform", SCALE_STRETCH: "Stretch"}

FIT_GEOMETRY = "geometry"
FIT_MATRIX   = "matrix"


def _cycle(value, options):
    i = options.index(value) if value in options else 0
    return options[(i + 1) % len(options)]


# --- HUD / Help builders ---------------------------------------------------

def _build_hud(context, op):
    hud = HUDOverlay("object_aligner")
    hud.title = "Object Aligner"
    hud.bind_region(context.region)
    hud.add_param(HUDParam("Mode", lambda: "Pick reference" if op.mode == MODE_PICK_REF else "Stamp"))
    hud.add_param(HUDParam("Reference", lambda: op.ref_name or "—",
                           visible_getter=lambda: bool(op.ref_name)))
    hud.add_param(HUDParam("Clone", lambda: op.clone_mode))
    hud.add_param(HUDParam("Scale", lambda: SCALE_LABELS.get(op.scale_mode, op.scale_mode)))
    hud.add_param(HUDParam("Fit", lambda: op.last_fit or "—",
                           visible_getter=lambda: bool(op.last_fit)))
    hud.add_param(HUDParam("Stamped", lambda: op.stamped_count, kind="int"))
    return hud


def _build_help(context):
    helpo = HelpOverlay("object_aligner")
    helpo.add_section(HUDSection("Object Aligner", [
        HUDItem("Pick reference / target", "LMB",          ItemState.ON, default_state=ItemState.OFF, always_show=True),
        HUDItem("Re-pick reference",       "R",            ItemState.ON, default_state=ItemState.OFF, always_show=True),
        HUDItem("Clone type (Duplicate/Instance)", "D",    ItemState.ON, default_state=ItemState.OFF, always_show=True),
        HUDItem("Scale (Uniform/Keep/Stretch)",    "S",    ItemState.ON, default_state=ItemState.OFF, always_show=True),
        HUDItem("Apply",                   "Enter / Space / RMB", ItemState.ON, default_state=ItemState.OFF, always_show=True),
        HUDItem("Cancel",                  "Esc",          ItemState.ON, default_state=ItemState.OFF, always_show=True),
        HUDItem("Help / HUD",              "H",            ItemState.ON, default_state=ItemState.OFF, always_show=True),
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


# --- Operator -------------------------------------------------------------

class IOPS_OT_Object_Aligner(bpy.types.Operator):
    """Stamp the selected rig onto raycast-picked objects, preserving the
    transform relative to a picked reference (topology-aware)."""

    bl_idname = "iops.object_aligner"
    bl_label = "OBJECT: Object Aligner"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return (
            context.mode == "OBJECT"
            and context.area is not None
            and context.area.type == "VIEW_3D"
        )

    def invoke(self, context, event):
        sel = list(context.selected_objects)
        if not sel:
            self.report({"WARNING"}, "Select the rig objects to transfer")
            return {"CANCELLED"}

        self.source_objs = sel
        self.source_set = set(sel)
        self.mode = MODE_PICK_REF
        self.clone_mode = CLONE_DUP
        self.scale_mode = SCALE_UNIFORM
        self.ref_obj = None
        self.ref_name = ""
        self.ref_world_np = None        # cached Nx3 reference verts (world)
        self.hover_obj = None
        self.last_fit = ""
        self.stamped_count = 0
        self.stamped_objs = []          # everything created this session (for cancel)
        self.stamped_targets = []       # picked target objects (for highlight)
        self._last_event = None

        self._hud = _build_hud(context, self)
        self._help = _build_help(context)
        self._handle = safe_handler_add(
            bpy.types.SpaceView3D, _draw_callback, (self, context),
            "WINDOW", "POST_PIXEL", tick=True,
        )
        self._handle_3d = None
        # POST_VIEW handler (3D preview) added in Task 6.
        context.window_manager.modal_handler_add(self)
        context.area.tag_redraw()
        return {"RUNNING_MODAL"}

    def _finish(self, context):
        if getattr(self, "_handle", None) is not None:
            safe_handler_remove(self._handle, bpy.types.SpaceView3D, "WINDOW")
            self._handle = None
        if getattr(self, "_handle_3d", None) is not None:
            safe_handler_remove(self._handle_3d, bpy.types.SpaceView3D, "WINDOW")
            self._handle_3d = None
        context.area.tag_redraw()

    def modal(self, context, event):
        context.area.tag_redraw()
        self._last_event = capture_event(event, getattr(self, "_last_event", None))

        # HUD/Help drag + toggle handling (verified pattern from
        # object_radial_array.py — the `handle_*_toggle` module helpers have a
        # different arity and must NOT be called as (op, event)).
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

        if event.type in {"ESC"} and event.value == "PRESS":
            return self._cancel(context)
        if event.type in {"RET", "NUMPAD_ENTER", "SPACE", "RIGHTMOUSE"} and event.value == "PRESS":
            self._finish(context)
            self.report({"INFO"}, f"Aligner: stamped {self.stamped_count}")
            return {"FINISHED"}

        return {"PASS_THROUGH"}

    def _cancel(self, context):
        self._finish(context)
        return {"CANCELLED"}
