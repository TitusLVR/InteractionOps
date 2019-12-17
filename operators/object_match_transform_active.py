import bpy


class IOPS_OT_MatchTransformActive(bpy.types.Operator):
    """ Match transformation of selected object to active one """
    bl_idname = "iops.match_transform_active"
    bl_label = "Match transform"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(self, context):
        return (context.area.type == "VIEW_3D" and
                context.mode == "OBJECT" and
                len(context.view_layer.objects.selected) != 0 and
                context.view_layer.objects.active.type == "MESH")
    
    def execute(self, context):
        selection = context.view_layer.objects.selected        
        active = context.view_layer.objects.active
        
        for ob in selection:
            ob.dimensions = active.dimensions
        
        return {"FINISHED"}
