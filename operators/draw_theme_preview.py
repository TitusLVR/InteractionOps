"""IOPS_OT_DrawThemePreview — modal preview of all theme primitives + HUD.

Run from preferences "Theme" tab. Renders one of each primitive in the
viewport and a sample HUD. ESC or right-click to exit.
"""
import bpy

from ..ui.draw import primitives as draw, draw_scope, Role
from ..ui.hud import HUDOverlay, HUDSection, HUDItem, ItemState


class IOPS_OT_DrawThemePreview(bpy.types.Operator):
    bl_idname = "iops.draw_theme_preview"
    bl_label = "Preview Theme"
    bl_description = "Modal preview of all unified UI primitives"
    bl_options = {"REGISTER"}

    def invoke(self, context, event):
        self._build_geometry(context)
        self._build_hud()
        self._last_event = event
        self._h_view = bpy.types.SpaceView3D.draw_handler_add(
            self._draw_view, (context,), "WINDOW", "POST_VIEW")
        self._h_px = bpy.types.SpaceView3D.draw_handler_add(
            self._draw_px, (context,), "WINDOW", "POST_PIXEL")
        context.window_manager.modal_handler_add(self)
        context.area.tag_redraw()
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        self._last_event = event
        context.area.tag_redraw()
        if event.type in {"ESC", "RIGHTMOUSE"} and event.value == "PRESS":
            self._cleanup()
            return {"FINISHED"}
        if event.type == "S" and event.value == "PRESS":
            current = self.hud._items_by_key["S"].state
            self.hud.set_state("S",
                ItemState.ON if current is ItemState.OFF else ItemState.OFF)
        return {"PASS_THROUGH"}

    def _cleanup(self):
        bpy.types.SpaceView3D.draw_handler_remove(self._h_view, "WINDOW")
        bpy.types.SpaceView3D.draw_handler_remove(self._h_px,   "WINDOW")

    def _build_geometry(self, context):
        from mathutils import Vector
        c = context.scene.cursor.location
        self.edges = [
            c + Vector((-1, 0, 0)), c + Vector((1, 0, 0)),
            c + Vector((0, -1, 0)), c + Vector((0, 1, 0)),
        ]
        self.snaps = [c + Vector((1, 1, 0)), c + Vector((-1, 1, 0)),
                      c + Vector((1, -1, 0))]
        self.closest = c + Vector((-1, -1, 0))
        self.preview = [c + Vector((-1.5, 0, 0)), c + Vector((1.5, 0, 0))]

    def _build_hud(self):
        self.hud = HUDOverlay("theme_preview")
        self.hud.add_section(HUDSection("Theme preview", [
            HUDItem("Toggle snap",    "S", ItemState.OFF),
            HUDItem("Locked example", "L", ItemState.ON),
            HUDItem("Disabled item",  "D", ItemState.DISABLED),
            HUDItem("Exit",           "ESC", ItemState.ON),
        ]))

    def _draw_view(self, context):
        with draw_scope(blend="ALPHA", depth="ALWAYS"):
            draw.edges_3d(self.edges,   role=Role.LOCKED_LINE)
            draw.polyline(self.preview, role=Role.PREVIEW_LINE)
            draw.points(self.snaps,     role=Role.POINT)
            draw.points([self.closest], role=Role.CLOSEST_POINT)

    def _draw_px(self, context):
        self.hud.draw(context, self._last_event)


classes = (IOPS_OT_DrawThemePreview,)
