import bpy
import blf
from bpy.props import BoolProperty


def draw_iops_curve_spline_types_text_px(self, context, _uidpi, _uifactor):
    prefs = bpy.context.preferences.addons["InteractionOps"].preferences
    tColor = prefs.text_color
    tKColor = prefs.text_color_key
    tCSize = prefs.text_size
    tCPosX = prefs.text_pos_x
    tCPosY = prefs.text_pos_y
    tShadow = prefs.text_shadow_toggle
    tSColor = prefs.text_shadow_color
    tSBlur = prefs.text_shadow_blur
    tSPosX = prefs.text_shadow_pos_x
    tSPosY = prefs.text_shadow_pos_y

    iops_text = (
        ("Present type is", str(self.curv_spline_type)),
        ("Handles state", str(self.handles)),
        ("Enable/Disable handles", "H"),
        ("Spline type POLY", "F1"),
        ("Spline type BEZIER", "F2"),
        ("Spline type NURBS", "F3"),
    )

    # FontID
    font = 0
    blf.color(font, tColor[0], tColor[1], tColor[2], tColor[3])
    blf.size(font, tCSize)
    if tShadow:
        blf.enable(font, blf.SHADOW)
        blf.shadow(font, int(tSBlur), tSColor[0], tSColor[1], tSColor[2], tSColor[3])
        blf.shadow_offset(font, tSPosX, tSPosY)
    else:
        blf.disable(0, blf.SHADOW)

    textsize = tCSize
    # get leftbottom corner
    offset = tCPosY
    columnoffs = (textsize * 13) * _uifactor
    for line in reversed(iops_text):
        blf.color(font, tColor[0], tColor[1], tColor[2], tColor[3])
        blf.position(font, tCPosX * _uifactor, offset, 0)
        blf.draw(font, line[0])

        blf.color(font, tKColor[0], tKColor[1], tKColor[2], tKColor[3])
        textdim = blf.dimensions(0, line[1])
        coloffset = columnoffs - textdim[0] + tCPosX
        blf.position(0, coloffset, offset, 0)
        blf.draw(font, line[1])
        offset += (tCSize + 5) * _uifactor


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

    def modal(self, context, event):
        context.area.tag_redraw()

        if event.type in {"MIDDLEMOUSE", "WHEELDOWNMOUSE", "WHEELUPMOUSE"}:
            # Allow navigation
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
            hnd = self.handles
            if hnd:
                self.handles = False
            else:
                self.handles = True

        elif event.type in {"RIGHTMOUSE", "ESC"}:
            bpy.types.SpaceView3D.draw_handler_remove(self._handle_text, "WINDOW")
            return {"CANCELLED"}
        return {"RUNNING_MODAL"}

    def invoke(self, context, event):
        preferences = context.preferences
        if context.object and context.area.type == "VIEW_3D":
            self.handles = False
            self.spl_type = "POLY"
            self.curv_spline_type = self.get_curve_active_spline_type(context)
            # Add drawing handler for text overlay rendering
            uidpi = int((72 * preferences.system.ui_scale))
            args = (self, context, uidpi, preferences.system.ui_scale)
            self._handle_text = bpy.types.SpaceView3D.draw_handler_add(
                draw_iops_curve_spline_types_text_px, args, "WINDOW", "POST_PIXEL"
            )
            # Add modal handler to enter modal mode
            context.window_manager.modal_handler_add(self)
            return {"RUNNING_MODAL"}
        else:
            self.report({"WARNING"}, "No active object, could not finish")
            return {"CANCELLED"}


def register():
    bpy.utils.register_class(IOPS_OT_CurveSplineType)


def unregister():
    bpy.utils.unregister_class(IOPS_OT_CurveSplineType)


if __name__ == "__main__":
    register()
