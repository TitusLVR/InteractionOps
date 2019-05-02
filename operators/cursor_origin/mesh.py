import bpy
from ..iops import IOPS


class IOPS_OT_CursorOrigin_Mesh(IOPS):
    bl_idname = "iops.cursor_origin_mesh"
    bl_label ="IOPS_OT_CursorOrigin_Mesh"

    @classmethod
    def poll (self, context):
        return (context.area.type == "VIEW_3D" and
                context.mode == "OBJECT" and
                context.active_object.type == "MESH")

    def execute(self, context):
        scene = bpy.context.scene
        objs = bpy.context.selected_objects
        if len(objs) != 0:
            for ob in objs:
                ob.location = scene.cursor.location
                ob.rotation_euler = scene.cursor.rotation_euler
            return{"FINISHED"}


class IOPS_OT_CursorOrigin_Mesh_Edit(IOPS):
    bl_idname = "iops.cursor_origin_mesh_edit"
    bl_label ="IOPS_OT_CursorOrigin_EditMesh"

    @classmethod
    def poll (self, context):
        return (context.area.type == "VIEW_3D" and
                context.mode == "EDIT_MESH")

    def execute(self, context):
        scene = bpy.context.scene
        objs = bpy.context.selected_objects
        bpy.ops.view3d.snap_cursor_to_selected()
        bpy.ops.object.editmode_toggle()
        bpy.ops.object.origin_set(type="ORIGIN_CURSOR")
        return{"FINISHED"}