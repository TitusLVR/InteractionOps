"""IOPS_OT_DrawThemePreview — modal preview of all theme primitives + HUD.

Run from preferences "Theme" tab. Renders one of each primitive in the
viewport plus a sample HUD (live params near cursor) and a sample Help
overlay (corner). ESC or right-click to exit.

Implementation note: draw handlers receive a plain `state` dict, not the
operator instance. This avoids `ReferenceError: StructRNA ... has been
removed` when the operator is destroyed (addon reload, exceptions during
invoke, unusual exit paths) while Blender still holds the draw handler.
"""
import bpy

from ..ui.draw import (primitives as draw, draw_scope, Role,
                       safe_handler_add, safe_handler_remove)
from ..ui.hud import (HUDOverlay, HelpOverlay, HUDSection, HUDItem,
                      HUDParam, ItemState)


def _draw_view(state):
    if state.get("dead"):
        return
    with draw_scope(blend="ALPHA", depth="ALWAYS"):
        draw.edges_3d(state["edges"],     role=Role.LOCKED_LINE)
        draw.polyline(state["preview"],   role=Role.PREVIEW_LINE)
        draw.points(state["snaps"],       role=Role.POINT)
        draw.points([state["closest"]],   role=Role.CLOSEST_POINT)


def _draw_px(state, context):
    if state.get("dead"):
        return
    event = state.get("event")
    state["hud"].draw(context, event)
    state["help"].draw(context, event)


class IOPS_OT_DrawThemePreview(bpy.types.Operator):
    bl_idname = "iops.draw_theme_preview"
    bl_label = "Preview Theme"
    bl_description = "Modal preview of all unified UI primitives"
    bl_options = {"REGISTER"}

    # Class-level coordination with IOPS_OT_StopThemePreview so the
    # Theme tab can flip the button between "Preview" and "Stop" and
    # request an exit from outside the modal.
    is_running: bool = False
    _stop_requested: bool = False

    def invoke(self, context, event):
        self._state = {
            "dead": False,
            "event": event,
            "snap_on": False,
            "subdivisions": 2,
            "offset": 0.25,
        }
        try:
            self._build_geometry(context, self._state)
            self._state["hud"] = self._build_hud(self._state)
            self._state["help"] = self._build_help(context)
            self._h_view = safe_handler_add(
                bpy.types.SpaceView3D,
                _draw_view, (self._state,), "WINDOW", "POST_VIEW")
            self._h_px = safe_handler_add(
                bpy.types.SpaceView3D,
                _draw_px, (self._state, context), "WINDOW", "POST_PIXEL")
            context.window_manager.modal_handler_add(self)
            context.area.tag_redraw()
            type(self).is_running = True
            type(self)._stop_requested = False
        except Exception:
            self._cleanup()
            raise
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        self._state["event"] = event
        context.area.tag_redraw()
        try:
            theme_prefs = context.preferences.addons["InteractionOps"]\
                .preferences.iops_theme
        except (KeyError, AttributeError):
            theme_prefs = None

        if (event.type in {"ESC", "RIGHTMOUSE"} and event.value == "PRESS"
                or type(self)._stop_requested):
            self._cleanup()
            return {"FINISHED"}

        hud = self._state["hud"]
        helpo = self._state["help"]

        if theme_prefs is not None:
            if hud.handle_param_toggle_event(event, theme_prefs):
                return {"RUNNING_MODAL"}
            if helpo.handle_toggle_event(event, theme_prefs):
                return {"RUNNING_MODAL"}

        if event.value == "PRESS":
            if event.type == "S":
                self._state["snap_on"] = not self._state["snap_on"]
                hud.set_state(
                    "S",
                    ItemState.ON if self._state["snap_on"] else ItemState.OFF)
            elif event.type in {"WHEELUPMOUSE", "EQUAL", "PLUS"}:
                self._state["subdivisions"] = min(
                    20, self._state["subdivisions"] + 1)
            elif event.type in {"WHEELDOWNMOUSE", "MINUS"}:
                self._state["subdivisions"] = max(
                    0, self._state["subdivisions"] - 1)

        return {"PASS_THROUGH"}

    def _cleanup(self):
        if getattr(self, "_state", None) is not None:
            self._state["dead"] = True
        safe_handler_remove(getattr(self, "_h_view", None),
                            bpy.types.SpaceView3D, "WINDOW")
        safe_handler_remove(getattr(self, "_h_px", None),
                            bpy.types.SpaceView3D, "WINDOW")
        self._h_view = None
        self._h_px = None
        type(self).is_running = False
        type(self)._stop_requested = False

    def _build_geometry(self, context, state):
        from mathutils import Vector
        c = context.scene.cursor.location
        state["edges"] = [
            c + Vector((-1, 0, 0)), c + Vector((1, 0, 0)),
            c + Vector((0, -1, 0)), c + Vector((0, 1, 0)),
        ]
        state["snaps"] = [c + Vector((1, 1, 0)), c + Vector((-1, 1, 0)),
                          c + Vector((1, -1, 0))]
        state["closest"] = c + Vector((-1, -1, 0))
        state["preview"] = [c + Vector((-1.5, 0, 0)), c + Vector((1.5, 0, 0))]

    def _build_hud(self, state):
        hud = HUDOverlay("theme_preview")
        hud.title = "Theme preview"
        hud.add_param(HUDParam(
            "Snap", lambda: state["snap_on"], kind="bool"))
        hud.add_param(HUDParam(
            "Subdivisions", lambda: state["subdivisions"], kind="int"))
        hud.add_param(HUDParam(
            "Offset", lambda: state["offset"], kind="float", fmt="{:.3f}",
            active_getter=lambda: state["snap_on"]))
        # Keep one HUDItem section so the legacy `S`-toggle highlight works
        # for the smoke-test, but the hotkeys list will move to Help.
        hud.add_section(HUDSection("", [
            HUDItem("Snap toggle marker", "S", ItemState.OFF,
                    always_show=False),
        ]))
        return hud

    def _build_help(self, context):
        helpo = HelpOverlay("theme_preview")
        helpo.bind_region(context.region)
        helpo.add_section(HUDSection("Theme preview", [
            HUDItem("Toggle snap",      "S",       ItemState.ON),
            HUDItem("More / fewer subs", "Wheel",  ItemState.ON),
            HUDItem("Hide params",      "/",       ItemState.ON),
            HUDItem("Toggle this help", "H",       ItemState.ON),
            HUDItem("Exit",             "ESC/RMB", ItemState.ON),
        ]))
        return helpo


class IOPS_OT_StopThemePreview(bpy.types.Operator):
    bl_idname = "iops.stop_theme_preview"
    bl_label = "Stop Preview"
    bl_description = "Stop the running theme preview"
    bl_options = {"REGISTER"}

    @classmethod
    def poll(cls, context):
        return IOPS_OT_DrawThemePreview.is_running

    def execute(self, context):
        IOPS_OT_DrawThemePreview._stop_requested = True
        # Nudge the viewport so the preview's modal wakes up.
        for win in context.window_manager.windows:
            for area in win.screen.areas:
                if area.type == "VIEW_3D":
                    area.tag_redraw()
        return {"FINISHED"}


classes = (IOPS_OT_DrawThemePreview, IOPS_OT_StopThemePreview)
