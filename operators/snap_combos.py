import bpy


class IOPS_OT_SnapCombo_1(bpy.types.Operator):
    '''IOPS Snap combo 1 - Sets Transform Orientation, Pivot Point, and Snap Target from IOPS addon preferences.'''
    bl_idname = "iops.snap_combo_1"
    bl_label = "Snap Combo 1"     
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        prefs = bpy.context.preferences.addons["InteractionOps"].preferences
        snap_combo_1 = prefs.snap_combo_1.replace(" ", "").split(",")
        if len(snap_combo_1) == 3:
            bpy.context.scene.transform_orientation_slots[0].type = snap_combo_1[0]
            bpy.context.scene.tool_settings.transform_pivot_point = snap_combo_1[1]
            bpy.context.scene.tool_settings.snap_target = snap_combo_1[2]
            self.report({"INFO"}, f"Snap combo 1!")
        else:
            self.report({"WARNING"}, f"Bad Snap combo 1 format: {prefs.snap_combo_1}")
        return {"FINISHED"}

class IOPS_OT_SnapCombo_2(bpy.types.Operator):
    '''IOPS Snap combo 2 - Sets Transform Orientation, Pivot Point, and Snap Target from IOPS addon preferences.'''
    bl_idname = "iops.snap_combo_2"
    bl_label = "Snap Combo 2"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        prefs = bpy.context.preferences.addons["InteractionOps"].preferences
        snap_combo_2 = prefs.snap_combo_2.replace(" ", "").split(",")
        if len(snap_combo_2) == 3:
            bpy.context.scene.transform_orientation_slots[0].type = snap_combo_2[0]
            bpy.context.scene.tool_settings.transform_pivot_point = snap_combo_2[1]
            bpy.context.scene.tool_settings.snap_target = snap_combo_2[2]
            self.report({"INFO"}, f"Snap combo 2!")
        else:
            self.report({"WARNING"}, f"Bad Snap combo 2 format: {prefs.snap_combo_2}")
        return {"FINISHED"}

class IOPS_OT_SnapCombo_3(bpy.types.Operator):
    '''IOPS Snap combo 3 - Sets Transform Orientation, Pivot Point, and Snap Target from IOPS addon preferences.'''
    bl_idname = "iops.snap_combo_3"
    bl_label = "Snap Combo 3"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        prefs = bpy.context.preferences.addons["InteractionOps"].preferences
        snap_combo_3 = prefs.snap_combo_3.replace(" ", "").split(",")
        if len(snap_combo_3) == 3:
            bpy.context.scene.transform_orientation_slots[0].type = snap_combo_3[0]
            bpy.context.scene.tool_settings.transform_pivot_point = snap_combo_3[1]
            bpy.context.scene.tool_settings.snap_target = snap_combo_3[2]
            self.report({"INFO"}, f"Snap combo 3!")
        else:
            self.report({"WARNING"}, f"Bad Snap combo 3 format: {prefs.snap_combo_3}")
        return {"FINISHED"}

class IOPS_OT_SnapCombo_4(bpy.types.Operator):
    '''IOPS Snap combo 4 - Sets Transform Orientation, Pivot Point, and Snap Target from IOPS addon preferences.'''
    bl_idname = "iops.snap_combo_4"
    bl_label = "Snap Combo 4"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        prefs = bpy.context.preferences.addons["InteractionOps"].preferences
        snap_combo_4 = prefs.snap_combo_4.replace(" ", "").split(",")
        if len(snap_combo_4) == 3:
            bpy.context.scene.transform_orientation_slots[0].type = snap_combo_4[0]
            bpy.context.scene.tool_settings.transform_pivot_point = snap_combo_4[1]
            bpy.context.scene.tool_settings.snap_target = snap_combo_4[2]
            self.report({"INFO"}, f"Snap combo 4!")
        else:
            self.report({"WARNING"}, f"Bad Snap combo 4 format: {prefs.snap_combo_4}")
        return {"FINISHED"}

class IOPS_OT_SnapCombo_5(bpy.types.Operator):
    '''IOPS Snap combo 5 - Sets Transform Orientation, Pivot Point, and Snap Target from IOPS addon preferences.'''
    bl_idname = "iops.snap_combo_5"
    bl_label = "Snap Combo 5"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        prefs = bpy.context.preferences.addons["InteractionOps"].preferences
        snap_combo_5 = prefs.snap_combo_5.replace(" ", "").split(",")
        if len(snap_combo_5) == 3:
            bpy.context.scene.transform_orientation_slots[0].type = snap_combo_5[0]
            bpy.context.scene.tool_settings.transform_pivot_point = snap_combo_5[1]
            bpy.context.scene.tool_settings.snap_target = snap_combo_5[2]
            self.report({"INFO"}, f"Snap combo 5!")
        else:
            self.report({"WARNING"}, f"Bad Snap combo 5 format: {prefs.snap_combo_5}")
        return {"FINISHED"}

class IOPS_OT_SnapCombo_6(bpy.types.Operator):
    '''IOPS Snap combo 6 - Sets Transform Orientation, Pivot Point, and Snap Target from IOPS addon preferences.'''
    bl_idname = "iops.snap_combo_6"
    bl_label = "Snap Combo 6"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        prefs = bpy.context.preferences.addons["InteractionOps"].preferences
        snap_combo_6 = prefs.snap_combo_6.replace(" ", "").split(",")
        if len(snap_combo_6) == 3:
            bpy.context.scene.transform_orientation_slots[0].type = snap_combo_6[0]
            bpy.context.scene.tool_settings.transform_pivot_point = snap_combo_6[1]
            bpy.context.scene.tool_settings.snap_target = snap_combo_6[2]
            self.report({"INFO"}, f"Snap combo 6!")
        else:
            self.report({"WARNING"}, f"Bad Snap combo 6 format: {prefs.snap_combo_6}")
        return {"FINISHED"}

class IOPS_OT_SnapCombo_7(bpy.types.Operator):
    '''IOPS Snap combo 7 - Sets Transform Orientation, Pivot Point, and Snap Target from IOPS addon preferences.'''
    bl_idname = "iops.snap_combo_7"
    bl_label = "Snap Combo 7"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        prefs = bpy.context.preferences.addons["InteractionOps"].preferences
        snap_combo_7 = prefs.snap_combo_7.replace(" ", "").split(",")
        if len(snap_combo_7) == 3:
            bpy.context.scene.transform_orientation_slots[0].type = snap_combo_7[0]
            bpy.context.scene.tool_settings.transform_pivot_point = snap_combo_7[1]
            bpy.context.scene.tool_settings.snap_target = snap_combo_7[2]
            self.report({"INFO"}, f"Snap combo 7!")
        else:
            self.report({"WARNING"}, f"Bad Snap combo 7 format: {prefs.snap_combo_7}")
        return {"FINISHED"}

class IOPS_OT_SnapCombo_8(bpy.types.Operator):
    '''IOPS Snap combo 8 - Sets Transform Orientation, Pivot Point, and Snap Target from IOPS addon preferences.'''
    bl_idname = "iops.snap_combo_8"
    bl_label = "Snap Combo 8"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        prefs = bpy.context.preferences.addons["InteractionOps"].preferences
        snap_combo_8 = prefs.snap_combo_8.replace(" ", "").split(",")
        if len(snap_combo_8) == 3:
            bpy.context.scene.transform_orientation_slots[0].type = snap_combo_8[0]
            bpy.context.scene.tool_settings.transform_pivot_point = snap_combo_8[1]
            bpy.context.scene.tool_settings.snap_target = snap_combo_8[2]
            self.report({"INFO"}, f"Snap combo 8!")
        else:
            self.report({"WARNING"}, f"Bad Snap combo 8 format: {prefs.snap_combo_8}")
        return {"FINISHED"}
