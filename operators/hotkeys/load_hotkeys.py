import bpy


class IOPS_OT_LoadUserHotkeys(bpy.types.Operator):
    bl_idname = "iops.load_user_hotkeys"
    bl_label = "Load User's Hotkeys"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        print("Loaded user's hotkeys")
        return("FINISHED")


class IOPS_OT_LoadDefaultHotkeys(bpy.types.Operator):
    bl_idname = "iops.load_default_hotkeys"
    bl_label = "Load User's Hotkeys"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        print("Loaded default hotkeys")
        return("FINISHED")