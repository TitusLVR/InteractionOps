import bpy
import os
import json
import shutil


from ...utils.functions import merge_missing_defaults

# Programmatically managed keymap entries that must NEVER be serialized:
# the save tuple can't round-trip them. iops.widget_interact: no `any`
# flag, and a load would route the space-typed "3D View" entry into the
# space-agnostic "Window" keymap as a duplicate global LMB binding.
# iops.widget_toggle: the tuple drops the `name` operator property, so
# the per-widget entries would collapse into nameless duplicates. Their
# owner (ui/widgets/events.py) registers both itself at addon register.
NEVER_SAVE = {"iops.widget_interact", "iops.widget_toggle"}


def save_hotkeys():
    path = bpy.utils.script_path_user()
    folder = os.path.join(path, "presets", "IOPS")
    user_hotkeys_file = os.path.join(path, "presets", "IOPS", "iops_hotkeys_user.py")
    if not os.path.exists(folder):
        os.makedirs(folder)
    # Save is a full snapshot of the live keymap, not a merge — after a
    # Load Default it overwrites every custom binding. Keep the previous
    # file as .bak so that is one copy away from undone.
    if os.path.exists(user_hotkeys_file):
        shutil.copy2(user_hotkeys_file, user_hotkeys_file + ".bak")
    # Persist every current iops kmi, plus any default not yet bound, so
    # newly shipped operators survive a save/load round-trip.
    data = merge_missing_defaults(get_iops_keys())
    temp_file = user_hotkeys_file + ".tmp"
    with open(temp_file, "w", encoding="utf-8") as f:
        f.write("[" + ",\n".join(json.dumps(i) for i in data) + "]\n")
    os.replace(temp_file, user_hotkeys_file)


def get_iops_keys():
    keys = []

    keyconfig = bpy.context.window_manager.keyconfigs.user

    for keymap in keyconfig.keymaps:
        if keymap:
            keymapItems = keymap.keymap_items
            toSave = tuple(
                item for item in keymapItems
                if item.idname.startswith("iops.")
                and item.idname not in NEVER_SAVE
            )
            for item in toSave:
                entry = (
                    item.idname,
                    item.type,
                    item.value,
                    item.ctrl,
                    item.alt,
                    item.shift,
                    item.oskey,
                )
                keys.append(entry)
    for k in keys:
        print(k)
    return keys


class IOPS_OT_SaveUserHotkeys(bpy.types.Operator):
    bl_idname = "iops.save_user_hotkeys"
    bl_label = "Save User's Hotkeys"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        save_hotkeys()
        print("Saved user's hotkeys")
        return {"FINISHED"}
