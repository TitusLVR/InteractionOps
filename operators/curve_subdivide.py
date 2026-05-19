import bpy
from bpy.props import (
    IntProperty
)

from ..ui.draw import primitives as draw, draw_scope, Role
from ..ui.draw import safe_handler_add, safe_handler_remove
from ..ui.draw.theme import get_theme
from ..ui.hud import HUDOverlay, HUDSection, HUDItem, ItemState, handle_hud_toggle


class IOPS_OT_CurveSubdivide(bpy.types.Operator):
    """Subdivide Curve"""

    bl_idname = "iops.curve_subdivide"
    bl_label = "CURVE: Subdivide"
    bl_options = {"REGISTER", "UNDO"}

    pairs = []

    points_num: IntProperty(name="Number of cuts", description="", default=1)

    @classmethod
    def poll(self, context):
        return (
            context.view_layer.objects.active.type == "CURVE"
            and context.view_layer.objects.active.mode == "EDIT"
        )

    def execute(self, context):
        self.subdivide(self.points_num)
        return {"FINISHED"}

    def subdivide(self, points):
        self.points_num = points
        bpy.ops.curve.subdivide(number_cuts=self.points_num)

    def get_curve_pts(self):
        obj = bpy.context.view_layer.objects.active
        pts = []
        sequence = []

        if obj.type == "CURVE":
            for s in obj.data.splines:
                for b in s.bezier_points:
                    if b.select_control_point:
                        pts.append(b)

        for idx in range(len(pts) - 1):
            A = pts[idx].co @ obj.matrix_world + obj.location
            Ahr = pts[idx].handle_right @ obj.matrix_world + obj.location

            B = pts[idx + 1].co @ obj.matrix_world + obj.location
            Bhl = pts[idx + 1].handle_left @ obj.matrix_world + obj.location

            for ip in range(self.points_num):
                p = 1 / (self.points_num + 1) * (ip + 1)
                point = (
                    (1 - p) ** 3 * A
                    + 3 * (1 - p) ** 2 * p * Ahr
                    + 3 * (1 - p) * p**2 * Bhl
                    + p**3 * B
                )
                sequence.append(point)
        return sequence

    def _build_hud(self, context):
        hud = HUDOverlay("curve_subdivide",
                         verbosity=get_theme(context).hud.verbosity)
        hud.add_section(HUDSection("Curve Subdivide", [
            HUDItem("Cuts",     "Wheel",          ItemState.ON, default_state=ItemState.OFF, always_show=True),
            HUDItem("Confirm",  "LMB / Space",    ItemState.ON, default_state=ItemState.OFF, always_show=True),
            HUDItem("Cancel",   "Esc / RMB",      ItemState.ON, default_state=ItemState.OFF, always_show=True),
            HUDItem("Help / Toggle HUD", "H", ItemState.ON, default_state=ItemState.OFF, always_show=True),
        ]))
        hud.bind_region(context.region)
        return hud

    def _draw_hud(self, context):
        hud = getattr(self, "_hud", None)
        if hud is None:
            return
        hud.set_header(f"Cuts: {self.points_num}")
        hud.draw(context, getattr(self, "_last_event", None))

    def _draw_curve_pts(self, context):
        coords = self.get_curve_pts()
        if not coords:
            return
        with draw_scope(blend="ALPHA", depth="ALWAYS"):
            draw.points(coords, role=Role.PREVIEW_POINT, context=context)

    def modal(self, context, event):
        context.area.tag_redraw()
        self._last_event = event
        if handle_hud_toggle(getattr(self, "_hud", None) or getattr(self, "hud", None), context, event):
            return {'RUNNING_MODAL'}

        if event.type in {"MIDDLEMOUSE"}:
            return {"PASS_THROUGH"}

        elif event.type == "WHEELDOWNMOUSE":
            if self.points_num > 1:
                self.points_num -= 1

        elif event.type == "WHEELUPMOUSE":
            self.points_num += 1

        elif event.type in {"LEFTMOUSE", "SPACE"} and event.value == "PRESS":
            self.execute(context)
            safe_handler_remove(self._handle_curve, bpy.types.SpaceView3D, "WINDOW")
            safe_handler_remove(self._handle_ui, bpy.types.SpaceView3D, "WINDOW")
            return {"FINISHED"}

        elif event.type in {"RIGHTMOUSE", "ESC"}:
            safe_handler_remove(self._handle_ui, bpy.types.SpaceView3D, "WINDOW")
            safe_handler_remove(self._handle_curve, bpy.types.SpaceView3D, "WINDOW")
            return {"CANCELLED"}

        return {"RUNNING_MODAL"}

    def invoke(self, context, event):
        if not (context.object and context.area.type == "VIEW_3D"):
            self.report({"WARNING"}, "No active object, could not finish")
            return {"CANCELLED"}

        self.points_num = 1
        self._hud = self._build_hud(context)
        self._last_event = event
        self._handle_ui = safe_handler_add(bpy.types.SpaceView3D,
            self._draw_hud, (context,), "WINDOW", "POST_PIXEL"
        )
        self._handle_curve = safe_handler_add(bpy.types.SpaceView3D,
            self._draw_curve_pts, (context,), "WINDOW", "POST_VIEW"
        )
        self.pairs = self.get_curve_pts()
        context.window_manager.modal_handler_add(self)
        return {"RUNNING_MODAL"}
