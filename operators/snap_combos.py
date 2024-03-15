import bpy

class IOPS_OT_SetSnapCombo(bpy.types.Operator):
    '''IOPS Set Snap combo - Sets Transform Orientation, Pivot Point, and Snap Target from IOPS addon preferences.'''
    bl_idname = "iops.set_snap_combo"
    bl_label = "Set Snap Combo "
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        prefs = bpy.context.preferences.addons["InteractionOps"].preferences
        index = int(prefs.snap_combo_list)
        match index:
            case 0:
                prefs.snap_combo_1 = f"{bpy.context.scene.transform_orientation_slots[0].type}, {bpy.context.scene.tool_settings.transform_pivot_point}, {bpy.context.scene.tool_settings.snap_target}"
            case 1:
                prefs.snap_combo_2 = f"{bpy.context.scene.transform_orientation_slots[0].type}, {bpy.context.scene.tool_settings.transform_pivot_point}, {bpy.context.scene.tool_settings.snap_target}"
            case 2:
                prefs.snap_combo_3 = f"{bpy.context.scene.transform_orientation_slots[0].type}, {bpy.context.scene.tool_settings.transform_pivot_point}, {bpy.context.scene.tool_settings.snap_target}"
            case 3:
                prefs.snap_combo_4 = f"{bpy.context.scene.transform_orientation_slots[0].type}, {bpy.context.scene.tool_settings.transform_pivot_point}, {bpy.context.scene.tool_settings.snap_target}"
            case 4:
                prefs.snap_combo_5 = f"{bpy.context.scene.transform_orientation_slots[0].type}, {bpy.context.scene.tool_settings.transform_pivot_point}, {bpy.context.scene.tool_settings.snap_target}"
            case 5:
                prefs.snap_combo_6 = f"{bpy.context.scene.transform_orientation_slots[0].type}, {bpy.context.scene.tool_settings.transform_pivot_point}, {bpy.context.scene.tool_settings.snap_target}"        
              
        self.report({"INFO"}, f"Snapping Combo {index+1} Saved!")
        return {"FINISHED"}




