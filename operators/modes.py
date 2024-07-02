from .iops import IOPS_OT_Main


class IOPS_OT_F1(IOPS_OT_Main):
    bl_idname = "iops.function_f1"
    bl_label = "IOPS OPERATOR F1"
    operator = "F1"


class IOPS_OT_F2(IOPS_OT_Main):
    bl_idname = "iops.function_f2"
    bl_label = "IOPS OPERATOR F2"
    operator = "F2"


class IOPS_OT_F3(IOPS_OT_Main):
    bl_idname = "iops.function_f3"
    bl_label = "IOPS OPERATOR F3"
    operator = "F3"


class IOPS_OT_F4(IOPS_OT_Main):
    bl_idname = "iops.function_f4"
    bl_label = "IOPS OPERATOR F4"
    operator = "F4"


class IOPS_OT_F5(IOPS_OT_Main):
    bl_idname = "iops.function_f5"
    bl_label = "IOPS OPERATOR F5"
    operator = "F5"


class IOPS_OT_ESC(IOPS_OT_Main):
    bl_idname = "iops.function_esc"
    bl_label = "IOPS OPERATOR ESC"
    operator = "ESC"
