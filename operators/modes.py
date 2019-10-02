import bpy
from .iops import IOPS_OT_Main


class IOPS_OT_MODE_F1(IOPS_OT_Main):
    bl_idname = "iops.mode_f1"
    bl_label = "iOps mode 1"
    _mode_3d = IOPS_OT_Main.modes_3d[0]
    _mode_uv = IOPS_OT_Main.modes_uv[0]
    _mode_gpen = IOPS_OT_Main.modes_gpen[0]
    _mode_text = IOPS_OT_Main.modes_text[0]
    _mode_meta = IOPS_OT_Main.modes_meta[0]
    _mode_armature = IOPS_OT_Main.modes_armature[0]
    _mode_lattice = IOPS_OT_Main.modes_lattice[0]


class IOPS_OT_MODE_F2(IOPS_OT_Main):
    bl_idname = "iops.mode_f2"
    bl_label = "iOps mode 2"
    _mode_3d = IOPS_OT_Main.modes_3d[1]
    _mode_uv = IOPS_OT_Main.modes_uv[1]
    _mode_gpen = IOPS_OT_Main.modes_gpen[1]
    _mode_armature = IOPS_OT_Main.modes_armature[1]


class IOPS_OT_MODE_F3(IOPS_OT_Main):
    bl_idname = "iops.mode_f3"
    bl_label = "iOps mode 3"
    _mode_3d = IOPS_OT_Main.modes_3d[2]
    _mode_uv = IOPS_OT_Main.modes_uv[2]
    _mode_gpen = IOPS_OT_Main.modes_gpen[2]


class IOPS_OT_MODE_F4(IOPS_OT_Main):
    bl_idname = "iops.mode_f4"
    bl_label = "iOps mode 4"
    _mode_uv = IOPS_OT_Main.modes_uv[3]

    @classmethod
    def poll(cls, context):
        return (bpy.context.area.type == "IMAGE_EDITOR" and not bpy.context.tool_settings.use_uv_select_sync)

class IOPS_OT_ESC(IOPS_OT_Main):
    bl_idname = "iops.esc"
    bl_label = "iOps ESC"

    @classmethod
    def poll(cls, context):
        return (bpy.context.active_object.mode == "EDIT")

    def execute(self, context):
        bpy.ops.object.mode_set(mode="OBJECT")
        return {'FINISHED'}




    
