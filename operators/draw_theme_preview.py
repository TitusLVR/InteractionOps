"""IOPS_OT_DrawThemePreview — modal preview of all theme primitives + HUD.

Run from preferences "Theme" tab. Renders one of each primitive in the
viewport and a sample HUD. ESC or right-click to exit.

Implementation note: draw handlers receive a plain `state` dict, not the
operator instance. This avoids `ReferenceError: StructRNA ... has been
removed` when the operator is destroyed (addon reload, exceptions during
invoke, unusual exit paths) while Blender still holds the draw handler.
"""
import bpy

from ..ui.draw import (primitives as draw, draw_scope, Role,
                       safe_handler_add, safe_handler_remove)
from ..ui.hud import HUDOverlay, HUDSection, HUDItem, ItemState


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
    state["hud"].draw(context, state.get("event"))


class IOPS_OT_DrawThemePreview(bpy.types.Operator):
    bl_idname = "iops.draw_theme_preview"
    bl_label = "Preview Theme"
    bl_description = "Modal preview of all unified UI primitives"
    bl_options = {"REGISTER"}

    def invoke(self, context, event):
        self._state = {"dead": False, "event": event}
        try:
            self._build_geometry(context, self._state)
            self._state["hud"] = self._build_hud()
            self._h_view = safe_handler_add(
                bpy.types.SpaceView3D,
                _draw_view, (self._state,), "WINDOW", "POST_VIEW")
            self._h_px = safe_handler_add(
                bpy.types.SpaceView3D,
                _draw_px, (self._state, context), "WINDOW", "POST_PIXEL")
            context.window_manager.modal_handler_add(self)
            context.area.tag_redraw()
        except Exception:
            self._cleanup()
            raise
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        self._state["event"] = event
        context.area.tag_redraw()
        if event.type in {"ESC", "RIGHTMOUSE"} and event.value == "PRESS":
            self._cleanup()
            return {"FINISHED"}
        if event.type == "S" and event.value == "PRESS":
            hud = self._state["hud"]
            current = hud._items_by_key["S"].state
            hud.set_state("S",
                ItemState.ON if current is ItemState.OFF else ItemState.OFF)
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

    def _build_hud(self):
        hud = HUDOverlay("theme_preview")
        hud.add_section(HUDSection("Theme preview", [
            HUDItem("Toggle snap",    "S", ItemState.OFF),
            HUDItem("Locked example", "L", ItemState.ON),
            HUDItem("Disabled item",  "D", ItemState.DISABLED),
            HUDItem("Exit",           "ESC", ItemState.ON),
        ]))
        return hud


classes = (IOPS_OT_DrawThemePreview,)
