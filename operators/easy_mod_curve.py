import bpy
from bpy.props import (
    BoolProperty,
    EnumProperty,
)


class IOPS_OT_Easy_Mod_Curve(bpy.types.Operator):
    """Select picked curve in curve modifier"""

    bl_idname = "iops.modifier_easy_curve"
    bl_label = "Easy Modifier - Curve"
    bl_options = {"REGISTER", "UNDO"}

    use_curve_radius: BoolProperty(
        name="Use Curve Radius",
        description="Causes the deformed object to be scaled by the set curve radius.",
        default=True,
    )
    use_curve_stretch: BoolProperty(
        name="Use Curve Length",
        description="The Stretch curve option allows you to let the mesh object stretch, or squeeze, over the entire curve.",
        default=True,
    )
    use_curve_bounds_clamp: BoolProperty(
        name="Use Curve Bounds",
        description="When this option is enabled, the object and mesh offset along the deformation axis is ignored.",
        default=True,
    )

    curve_modifier_axis: EnumProperty(
        name="Deformation Axis",
        description="Deformation along selected axis",
        items=[
            ("POS_X", "X", "", "", 0),
            ("POS_Y", "Y", "", "", 1),
            ("POS_Z", "Z", "", "", 2),
            ("NEG_X", "-X", "", "", 3),
            ("NEG_Y", "-Y", "", "", 4),
            ("NEG_Z", "-Z", "", "", 5),
        ],
        default="POS_X",
    )
    find_array_and_set_curve_fit: BoolProperty(
        name="Array - Fit Curve",
        description="Find Array modifier in the active object modifier list and set Array Fit type to - Fit Curve and pick selected spline there",
        default=False,
    )
    Replace_Curve_Modifier: BoolProperty(
        name="Find and Replace Curve Modifier",
        description="Find and replace iOps curve modifier",
        default=True,
    )

    @classmethod
    def poll(cls, context):
        return context.mode == "OBJECT" and context.area.type == "VIEW_3D"

    def execute(self, context):
        if (
            len(context.view_layer.objects.selected) == 1
            and context.active_object.type == "MESH"
        ):
            for mod in bpy.context.active_object.modifiers:
                if mod.type == "CURVE":
                    bpy.ops.object.select_all(action="DESELECT")
                    mod.object.select_set(True)
                    context.view_layer.objects.active = mod.object
                    self.report({"INFO"}, "Curve Modifer - Object selected.")

        if len(context.view_layer.objects.selected) == 2:
            obj = None
            curve = None

            for ob in context.view_layer.objects.selected:
                if ob.type == "MESH":
                    obj = ob
                if ob.type == "CURVE":
                    curve = ob

            if obj and curve:
                cur = context.scene.cursor
                curve.data.use_radius = self.use_curve_radius
                curve.data.use_stretch = self.use_curve_stretch
                curve.data.use_deform_bounds = self.use_curve_bounds_clamp

                if obj.location != curve.location:
                    bpy.ops.object.select_all(action="DESELECT")
                    curve.select_set(True)
                    context.view_layer.objects.active = curve

                    if curve.data.splines.active.type == "POLY":
                        cur.location = (
                            curve.data.splines.active.points[0].co.xyz
                            @ curve.matrix_world.transposed()
                        )
                        bpy.ops.object.origin_set(type="ORIGIN_CURSOR", center="MEDIAN")

                    if curve.data.splines.active.type == "BEZIER":
                        cur.location = (
                            curve.data.splines.active.bezier_points[0].co
                            @ curve.matrix_world.transposed()
                        )
                        bpy.ops.object.origin_set(type="ORIGIN_CURSOR", center="MEDIAN")

                    bpy.ops.object.select_all(action="DESELECT")
                    obj.location = curve.location

                if obj.modifiers:
                    if self.Replace_Curve_Modifier:
                        for mod in obj.modifiers:
                            if mod.type == "CURVE":
                                mod.object = curve
                                mod.deform_axis = self.curve_modifier_axis
                                curve.select_set(True)
                                obj.select_set(True)
                                context.view_layer.objects.active = obj
                                self.report({"INFO"}, "Curve Modifier Replaced")
                    else:
                        mod = obj.modifiers.new("iOps Curve", type="CURVE")
                        mod.object = curve
                        mod.deform_axis = self.curve_modifier_axis
                        curve.select_set(True)
                        obj.select_set(True)
                        context.view_layer.objects.active = obj
                        self.report(
                            {"INFO"}, "New Curve Modifier added and curve object picked"
                        )

                    if self.find_array_and_set_curve_fit:
                        for mod in obj.modifiers:
                            if mod.type == "ARRAY":
                                mod.fit_type = "FIT_CURVE"
                                mod.curve = curve
                                self.report(
                                    {"INFO"}, "Array modifier found and curve setted"
                                )
                else:
                    mod = obj.modifiers.new("iOps Curve", type="CURVE")
                    mod.object = curve
                    mod.deform_axis = self.curve_modifier_axis
                    curve.select_set(True)
                    obj.select_set(True)
                    context.view_layer.objects.active = obj
                    self.report(
                        {"INFO"}, "New Curve Modifier added and curve object picked"
                    )
            else:
                self.report({"WARNING"}, "Mesh or Curve missing!!!")
        return {"FINISHED"}
