import bpy


class IOPS_OT_MatchTransformActive(bpy.types.Operator):
    """Match dimensions of selected object to active"""

    bl_idname = "iops.object_match_transform_active"
    bl_label = "Match dimensions"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(self, context):
        return (
            context.area.type == "VIEW_3D"
            and context.mode == "OBJECT"
            and len(context.view_layer.objects.selected) != 0
            and context.view_layer.objects.active.type == "MESH"
        )

    def execute(self, context):
        selection = context.view_layer.objects.selected
        active = context.view_layer.objects.active

        for ob in selection:
            ob.dimensions = active.dimensions

        self.report({"INFO"}, "Dimensions matched")

        return {"FINISHED"}
