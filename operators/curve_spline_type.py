import bpy
from bpy.props import BoolProperty

from ..ui.draw import safe_handler_add, safe_handler_remove
from ..ui.hud import HUDOverlay, HUDParam, capture_event
from ..ui.hud.more import build_help


class IOPS_OT_CurveSplineType(bpy.types.Operator):
    """Curve select spline type"""

    bl_idname = "iops.curve_spline_type"
    bl_label = "CURVE: Spline type"
    bl_options = {"REGISTER", "UNDO"}

    handles: BoolProperty(name="Use handles", description="Use handles", default=False)

    spl_type = []
    curv_spline_type = []

    @classmethod
    def poll(self, context):
        return (
            len(context.view_layer.objects.selected) != 0
            and context.view_layer.objects.active.type == "CURVE"
            and context.view_layer.objects.active.mode == "EDIT"
        )

    def get_curve_active_spline_type(self, context):
        curve = context.view_layer.objects.active.data
        active_spline_type = curve.splines.active.type
        return active_spline_type

    def execute(self, context):
        bpy.ops.curve.spline_type_set(type=self.spl_type, use_handles=self.handles)
        return {"FINISHED"}

    def _build_overlays(self, region):
        hud = self._hud = HUDOverlay("curve_spline_type")
        hud.title = "Curve Spline Type"
        hud.bind_region(region)
        hud.add_param(HUDParam("Spline Type (F1 / F2 / F3)", lambda: self.curv_spline_type, "str"))
        hud.add_param(HUDParam("Handles (A)", lambda: self.handles, "bool"))
        self._help = build_help("curve_spline_type", [
            ("Curve Spline Type", [
                ("Poly Spline, Confirm", "F1"),
                ("Bezier Spline, Confirm", "F2"),
                ("NURBS Spline, Confirm", "F3"),
                ("Use handles", "A"),
                ("Cancel", "Esc / RMB"),
            ]),
        ], region)

    def _draw_hud(self, context):
        hud = getattr(self, "_hud", None)
        helpo = getattr(self, "_help", None)
        last_event = getattr(self, "_last_event", None)
        if helpo is not None:
            helpo.draw(context, last_event)
        if hud is not None:
            hud.draw(context, last_event)

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

        if event.type in {"MIDDLEMOUSE", "WHEELDOWNMOUSE", "WHEELUPMOUSE"}:
            return {"PASS_THROUGH"}

        elif event.type in {"F1"} and event.value == "PRESS":
            self.spl_type = "POLY"
            safe_handler_remove(self._handle_text, bpy.types.SpaceView3D, "WINDOW")
            self.execute(context)
            return {"FINISHED"}

        elif event.type in {"F2"} and event.value == "PRESS":
            self.spl_type = "BEZIER"
            safe_handler_remove(self._handle_text, bpy.types.SpaceView3D, "WINDOW")
            self.execute(context)
            return {"FINISHED"}

        elif event.type in {"F3"} and event.value == "PRESS":
            self.spl_type = "NURBS"
            safe_handler_remove(self._handle_text, bpy.types.SpaceView3D, "WINDOW")
            self.execute(context)
            return {"FINISHED"}

        elif event.type in {"A"} and event.value == "PRESS":
            self.handles = not self.handles

        elif event.type in {"RIGHTMOUSE", "ESC"}:
            safe_handler_remove(self._handle_text, bpy.types.SpaceView3D, "WINDOW")
            return {"CANCELLED"}
        return {"RUNNING_MODAL"}

    def invoke(self, context, event):
        if not (context.object and context.area.type == "VIEW_3D"):
            self.report({"WARNING"}, "No active object, could not finish")
            return {"CANCELLED"}

        self.handles = False
        self.spl_type = "POLY"
        self.curv_spline_type = self.get_curve_active_spline_type(context)

        self._build_overlays(context.region)
        self._last_event = capture_event(event, getattr(self, "_last_event", None))
        self._handle_text = safe_handler_add(bpy.types.SpaceView3D,
            self._draw_hud, (context,), "WINDOW", "POST_PIXEL", tick=True)
        context.window_manager.modal_handler_add(self)
        return {"RUNNING_MODAL"}


def register():
    bpy.utils.register_class(IOPS_OT_CurveSplineType)


def unregister():
    bpy.utils.unregister_class(IOPS_OT_CurveSplineType)


if __name__ == "__main__":
    register()
