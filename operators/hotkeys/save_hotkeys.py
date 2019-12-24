import bpy
from ... utils.functions import (register_keymaps, unregister_keymaps)

class IOPS_OT_SaveUserHotkeys(bpy.types.Operator):
    bl_idname = "iops.save_user_hotkeys"
    bl_label = "Save User's Hotkeys"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        unregister_keymaps()
        print("Saved user's hotkeys")
        return {"FINISHED"}
