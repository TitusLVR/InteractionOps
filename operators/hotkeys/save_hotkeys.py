import bpy
import os
import json
from ... utils.functions import (register_keymaps, unregister_keymaps, get_addon)


def save_hotkeys():
    keys = []
    path = bpy.utils.script_path_user()
    user_hotkeys_file = os.path.join(path, 'addons', 'InteractionOps', 'prefs', "hotkeys_user.py")
   
    with open(user_hotkeys_file, 'w') as f:
        data = get_iops_keys()
        f.write(
        '[' +
        ',\n'.join(json.dumps(i) for i in data) +
        ']\n')

def get_iops_keys():
    keys = []
    keyconfig = bpy.context.window_manager.keyconfigs['blender user']
    keymap = keyconfig.keymaps.get("Window")
    if keymap:
        keymapItems = keymap.keymap_items
        toSave = tuple(
            item for item in keymapItems if item.idname.startswith('iops.'))
        for item in toSave:
            entry = (item.idname, item.type, item.value, item.ctrl, item.alt, item.shift)
            keys.append(entry)
    for k in keys:
        print(k)
    return keys

    # keys = []
    # keyconfigs = bpy.context.window_manager.keyconfigs['blender']
    # for kc in keyconfigs:
    #     keymap = kc.keymaps.get("Window")
    #     if keymap:
    #         keymapItems = keymap.keymap_items
    #         toSave = tuple(
    #             item for item in keymapItems if item.idname.startswith('iops.'))
    #         for item in toSave:
    #             entry = (item.idname, item.type, item.value, item.ctrl, item.alt, item.shift)
    #             keys.append(entry)
    # for k in keys:
    #     print(k)
    # return keys
    


class IOPS_OT_SaveUserHotkeys(bpy.types.Operator):
    bl_idname = "iops.save_user_hotkeys"
    bl_label = "Save User's Hotkeys"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        save_hotkeys()
        print("Saved user's hotkeys")
        return {"FINISHED"}
