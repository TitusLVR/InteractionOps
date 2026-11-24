# operators/uv_info.py
"""UV-context information operators (Image Editor).

IOPS_OT_UVInfoRect: rubber-band a rectangle in the UV editor and report its
UV min/max/size, copying them to the clipboard."""

import bpy
from mathutils import Vector

from ..ui.draw import primitives as draw, draw_scope, Role
from ..ui.draw import safe_handler_add, safe_handler_remove
from ..ui.hud import HUDOverlay, HUDParam, capture_event
from ..ui.hud.more import build_help
from ..utils.uv_info import uv_rect_bounds, format_uv_rect


class IOPS_OT_UVInfoRect(bpy.types.Operator):
    """Draw a rectangle in the UV editor; reports UV min/max/size and copies them"""

    bl_idname = "iops.uv_info_rect"
    is_bindable = True
    bl_label = "IOPS UV Info Rect"
    bl_options = {"REGISTER"}

    sd_handlers = []

    @classmethod
    def poll(cls, context):
        return context.area is not None and context.area.type == "IMAGE_EDITOR"

    def clear_draw_handlers(self):
        for handler in self.sd_handlers:
            safe_handler_remove(handler, bpy.types.SpaceImageEditor, "WINDOW")

    def _build_overlays(self, region):
        hud = self._hud = HUDOverlay("uv_info_rect")
        hud.title = "UV Info Rect"
        hud.bind_region(region)

        def pair(index):
            def text():
                bounds = self._bounds
                if bounds is None:
                    return "-"
                return f"({bounds[index][0]:.4f}, {bounds[index][1]:.4f})"
            return text

        def has_rect():
            return self._bounds is not None

        hud.add_param(HUDParam("Minimum", pair(0), "str", visible_getter=has_rect))
        hud.add_param(HUDParam("Maximum", pair(1), "str", visible_getter=has_rect))
        hud.add_param(HUDParam("Size", pair(2), "str", visible_getter=has_rect))
        self._help = build_help("uv_info_rect", [
            ("UV Info Rect", [
                ("Draw rectangle", "LMB"),
                ("Copy bounds to the clipboard", "LMB release"),
                ("Cancel", "Esc / RMB"),
            ]),
        ], region)

    def _bounds_uv(self, context):
        """Current rectangle bounds in UV space, or None if no rectangle."""
        if self.start is None or self.end is None:
            return None
        v2d = context.region.view2d
        c0 = v2d.region_to_view(self.start[0], self.start[1])
        c1 = v2d.region_to_view(self.end[0], self.end[1])
        return uv_rect_bounds(c0, c1)

    def _draw_rect(self, context):
        if self.start is None or self.end is None:
            return
        x0, y0 = self.start
        x1, y1 = self.end
        loop = [Vector((x0, y0, 0.0)), Vector((x1, y0, 0.0)),
                Vector((x1, y1, 0.0)), Vector((x0, y1, 0.0)),
                Vector((x0, y0, 0.0))]
        with draw_scope(blend="ALPHA"):
            draw.polyline(loop, role=Role.PREVIEW_LINE, context=context)
        bounds = self._bounds_uv(context)
        if bounds is not None:
            uv_min, uv_max, _ = bounds
            v2d = context.region.view2d
            pmin = v2d.view_to_region(uv_min[0], uv_min[1], clip=False)
            pmax = v2d.view_to_region(uv_max[0], uv_max[1], clip=False)
            draw.points([Vector((pmin[0], pmin[1], 0.0)),
                         Vector((pmax[0], pmax[1], 0.0))],
                        role=Role.ACTIVE_POINT, context=context)

    def _draw_hud(self, context):
        self._bounds = self._bounds_uv(context)
        helpo = getattr(self, "_help", None)
        if helpo is not None:
            helpo.draw(context, getattr(self, "_last_event", None))
        if getattr(self, "_hud", None) is not None:
            self._hud.draw(context, getattr(self, "_last_event", None))

    def _copy_bounds(self, context):
        bounds = self._bounds_uv(context)
        if bounds is None:
            return
        text = format_uv_rect(*bounds)
        context.window_manager.clipboard = text
        self.report({"INFO"}, text)

    def modal(self, context, event):
        context.area.tag_redraw()
        self._last_event = capture_event(event, getattr(self, "_last_event", None))
        try:
            theme_prefs = context.preferences.addons["InteractionOps"]\
                .preferences.iops_theme
        except (KeyError, AttributeError):
            theme_prefs = None
        if theme_prefs is not None:
            helpo = getattr(self, "_help", None)
            hud = getattr(self, "_hud", None)
            if helpo is not None and helpo.handle_drag_event(context, event, theme_prefs):
                return {'RUNNING_MODAL'}
            if hud is not None and hud.handle_drag_event(context, event, theme_prefs):
                return {'RUNNING_MODAL'}
            if helpo is not None and helpo.handle_toggle_event(event, theme_prefs):
                return {'RUNNING_MODAL'}
            if hud is not None and hud.handle_param_toggle_event(event, theme_prefs):
                return {'RUNNING_MODAL'}

        if event.type in {"MIDDLEMOUSE", "WHEELUPMOUSE", "WHEELDOWNMOUSE"}:
            return {"PASS_THROUGH"}

        elif event.type == "MOUSEMOVE":
            if self.dragging:
                self.end = (event.mouse_region_x, event.mouse_region_y)

        elif event.type == "LEFTMOUSE" and event.value == "PRESS":
            self.start = (event.mouse_region_x, event.mouse_region_y)
            self.end = (event.mouse_region_x, event.mouse_region_y)
            self.dragging = True

        elif event.type == "LEFTMOUSE" and event.value == "RELEASE":
            if self.dragging:
                self.end = (event.mouse_region_x, event.mouse_region_y)
                self.dragging = False
                self._copy_bounds(context)

        elif event.type in {"RIGHTMOUSE", "ESC"}:
            self.clear_draw_handlers()
            self.report({"INFO"}, "UV Info Rect - cancelled")
            return {"CANCELLED"}

        return {"RUNNING_MODAL"}

    def invoke(self, context, event):
        if context.space_data.type != "IMAGE_EDITOR":
            self.report({"WARNING"}, "Active space must be an Image Editor")
            return {"CANCELLED"}

        self.start = None
        self.end = None
        self.dragging = False

        self._bounds = None
        self._build_overlays(context.region)
        self._last_event = capture_event(event, None)

        self.handle_rect = safe_handler_add(bpy.types.SpaceImageEditor,
            self._draw_rect, (context,), "WINDOW", "POST_PIXEL", tick=True)
        self.handle_hud = safe_handler_add(bpy.types.SpaceImageEditor,
            self._draw_hud, (context,), "WINDOW", "POST_PIXEL", tick=True)
        self.sd_handlers = [self.handle_rect, self.handle_hud]

        context.window_manager.modal_handler_add(self)
        self.report({"INFO"}, "UV Info Rect: drag to measure")
        return {"RUNNING_MODAL"}
