import bpy
from ..iops import IOPS


class IOPS_OT_CursorOrigin_Gpen(IOPS):
    bl_idname = "iops.cursor_origin_gpen"
    bl_label ="IOPS_OT_CursorOrigin_Gpen"

    @classmethod
    def poll (self, context):
        return (context.area.type == "VIEW_3D" and
                context.mode == "OBJECT" and
                context.active_object.type == "GPENCIL")


class IOPS_OT_CursorOrigin_Gpen_Edit(IOPS):
    bl_idname = "iops.cursor_origin_gpen_edit"
    bl_label ="IOPS_OT_CursorOrigin_Gpen_Edit"

    @classmethod
    def poll (self, context):
        return (context.area.type == "VIEW_3D" and
                context.mode == "EDIT_GPENCIL" and
                context.active_object.type == "GPENCIL")

    def execute(self, context):
        bpy.ops.gpencil.snap_cursor_to_selected()
        bpy.ops.object.origin_set(type="ORIGIN_CURSOR")
        bpy.ops.object.mode_set(mode="OBJECT")
        return{"FINISHED"}