import bpy
from bpy.props import BoolProperty

from ..ui.draw.theme import get_theme
from ..ui.hud import HUDOverlay, HUDSection, HUDItem, ItemState


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

    def _build_hud(self, context):
        hud = HUDOverlay("curve_spline_type",
                         verbosity=get_theme(context).hud.verbosity)
        hud.add_section(HUDSection("Curve Spline Type", [
            HUDItem("Use handles",    "H",   ItemState.ON if self.handles else ItemState.OFF),
            HUDItem("Spline POLY",    "F1",  ItemState.ON, default_state=ItemState.OFF, always_show=True),
            HUDItem("Spline BEZIER",  "F2",  ItemState.ON, default_state=ItemState.OFF, always_show=True),
            HUDItem("Spline NURBS",   "F3",  ItemState.ON, default_state=ItemState.OFF, always_show=True),
            HUDItem("Cancel",         "Esc / RMB", ItemState.ON, default_state=ItemState.OFF, always_show=True),
        ]))
        hud.bind_region(context.region)
        return hud

    def _draw_hud(self, context):
        hud = getattr(self, "_hud", None)
        if hud is None:
            return
        hud.set_state("H", ItemState.ON if self.handles else ItemState.OFF)
        hud.set_header(f"Current type: {self.curv_spline_type}")
        hud.draw(context, getattr(self, "_last_event", None))

    def modal(self, context, event):
        context.area.tag_redraw()
        self._last_event = event

        if event.type in {"MIDDLEMOUSE", "WHEELDOWNMOUSE", "WHEELUPMOUSE"}:
            return {"PASS_THROUGH"}

        elif event.type in {"F1"} and event.value == "PRESS":
            self.spl_type = "POLY"
            bpy.types.SpaceView3D.draw_handler_remove(self._handle_text, "WINDOW")
            self.execute(context)
            return {"FINISHED"}

        elif event.type in {"F2"} and event.value == "PRESS":
            self.spl_type = "BEZIER"
            bpy.types.SpaceView3D.draw_handler_remove(self._handle_text, "WINDOW")
            self.execute(context)
            return {"FINISHED"}

        elif event.type in {"F3"} and event.value == "PRESS":
            self.spl_type = "NURBS"
            bpy.types.SpaceView3D.draw_handler_remove(self._handle_text, "WINDOW")
            self.execute(context)
            return {"FINISHED"}

        elif event.type in {"H"} and event.value == "PRESS":
            self.handles = not self.handles

        elif event.type in {"RIGHTMOUSE", "ESC"}:
            bpy.types.SpaceView3D.draw_handler_remove(self._handle_text, "WINDOW")
            return {"CANCELLED"}
        return {"RUNNING_MODAL"}

    def invoke(self, context, event):
        if not (context.object and context.area.type == "VIEW_3D"):
            self.report({"WARNING"}, "No active object, could not finish")
            return {"CANCELLED"}

        self.handles = False
        self.spl_type = "POLY"
        self.curv_spline_type = self.get_curve_active_spline_type(context)

        self._hud = self._build_hud(context)
        self._last_event = event
        self._handle_text = bpy.types.SpaceView3D.draw_handler_add(
            self._draw_hud, (context,), "WINDOW", "POST_PIXEL"
        )
        context.window_manager.modal_handler_add(self)
        return {"RUNNING_MODAL"}


def register():
    bpy.utils.register_class(IOPS_OT_CurveSplineType)


def unregister():
    bpy.utils.unregister_class(IOPS_OT_CurveSplineType)


if __name__ == "__main__":
    register()
