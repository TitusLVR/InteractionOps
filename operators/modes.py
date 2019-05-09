import bpy
from .iops import IOPS


class IOPS_OT_MODE_F1(IOPS):
    bl_idname = "iops.mode_f1"
    bl_label = "iOps mode 1"
    _mode_3d = IOPS.modes_3d[0]
    _mode_uv = IOPS.modes_uv[0]
    _mode_gpen = IOPS.modes_gpen[0]


class IOPS_OT_MODE_F2(IOPS):
    bl_idname = "iops.mode_f2"
    bl_label = "iOps mode 2"
    _mode_3d = IOPS.modes_3d[1]
    _mode_uv = IOPS.modes_uv[1]
    _mode_gpen = IOPS.modes_gpen[1]


class IOPS_OT_MODE_F3(IOPS):
    bl_idname = "iops.mode_f3"
    bl_label = "iOps mode 3"
    _mode_3d = IOPS.modes_3d[2]
    _mode_uv = IOPS.modes_uv[2]
    _mode_gpen = IOPS.modes_gpen[2]


class IOPS_OT_MODE_F4(IOPS):
    bl_idname = "iops.mode_f4"
    bl_label = "iOps mode 4"
    _mode_uv = IOPS.modes_uv[3]

    @classmethod
    def poll(cls, context):
        return bpy.context.area.type == "IMAGE_EDITOR"
