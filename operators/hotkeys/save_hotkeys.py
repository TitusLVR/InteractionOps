import bpy
import os
import json
from ... utils.functions import (register_keymaps, unregister_keymaps)


def save_hotkeys():
    # keys = []
    # user_hotkeys_file = "../../../prefs/hotkeys_user.py"
    # with open(user_hotkeys_file, 'w') as f:
    #     keys = json.loads(f.read())
    # print(keys)
    print(os.path.dirname(__file__))


class IOPS_OT_SaveUserHotkeys(bpy.types.Operator):
    bl_idname = "iops.save_user_hotkeys"
    bl_label = "Save User's Hotkeys"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        save_hotkeys()
        print("Saved user's hotkeys")
        return {"FINISHED"}
