import bpy
from ..iops import IOPS_OT_Main


class IOPS_OT_CursorOrigin_Empty(IOPS_OT_Main):
    bl_idname = "iops.cursor_origin_empty"
    bl_label = "EMPTY: Align to cursor"

    @classmethod
    def poll(self, context):
        return (context.area.type == "VIEW_3D" and
                context.view_layer.objects.active.type == "EMPTY")

    def execute(self, context):
        scene = bpy.context.scene
        objs = bpy.context.selected_objects
        if len(objs) != 0:
            for ob in objs:
                ob.location = scene.cursor.location
                ob.rotation_euler = scene.cursor.rotation_euler
            return{"FINISHED"}