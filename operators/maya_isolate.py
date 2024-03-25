# In edit mode hides unselected and enters local view
# In object mode uses default blende behavior

import bpy


class IOPS_OT_MayaIsolate(bpy.types.Operator):
    """Maya-like isolate selection"""

    bl_idname = "iops.view3d_maya_isolate"
    bl_label = "IOPS Maya Isolate"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(self, context):
        return (
            context.area.type == "VIEW_3D"
            and (context.mode == "OBJECT" or context.mode == "EDIT_MESH")
            and context.view_layer.objects.active.type == "MESH"
            and len(context.view_layer.objects.selected) != 0
        )

    def mesh_isolate(self, context):
        bpy.ops.mesh.hide(unselected=True)
        bpy.ops.view3d.localview(frame_selected=False)

    def object_isolate(self, context):
        bpy.ops.view3d.localview(frame_selected=False)

    def execute(self, context):
        if context.mode == "OBJECT":
            self.object_isolate(context)
        elif context.mode == "EDIT_MESH":
            self.mesh_isolate(context)

        return {"FINISHED"}
