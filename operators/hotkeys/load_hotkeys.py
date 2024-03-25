import bpy
import os
import json
from ...utils.functions import register_keymaps, unregister_keymaps
from ...prefs.hotkeys_default import keys_default


class IOPS_OT_LoadUserHotkeys(bpy.types.Operator):
    bl_idname = "iops.load_user_hotkeys"
    bl_label = "Load User's Hotkeys"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        unregister_keymaps()
        bpy.context.window_manager.keyconfigs.update()

        keys_user = []

        path = bpy.utils.script_path_user()
        user_hotkeys_file = os.path.join(
            path, "presets", "IOPS", "iops_hotkeys_user.py"
        )
        user_hotkeys_path = os.path.join(path, "presets", "IOPS")

        if os.path.exists(user_hotkeys_file):
            with open(user_hotkeys_file) as f:
                keys_user = json.load(f)
        else:
            if not os.path.exists(user_hotkeys_path):
                os.makedirs(user_hotkeys_path)
            with open(user_hotkeys_file, "w") as f:
                f.write("[]")

        register_keymaps(keys_user)
        print("Loaded user's hotkeys")
        return {"FINISHED"}


class IOPS_OT_LoadDefaultHotkeys(bpy.types.Operator):
    bl_idname = "iops.load_default_hotkeys"
    bl_label = "Load Default Hotkeys"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        unregister_keymaps()
        bpy.context.window_manager.keyconfigs.update()
        register_keymaps(keys_default)
        print("Loaded default hotkeys")
        return {"FINISHED"}
