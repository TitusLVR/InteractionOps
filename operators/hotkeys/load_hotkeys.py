import bpy
import os
import json
from ...utils.functions import (
    register_keymaps,
    unregister_keymaps,
    merge_missing_defaults,
    build_bindable_defaults,
    register_ui_toggle_keymaps,
)
from ...ui.widgets import events as widget_events


def _reload_keymaps(keys):
    """Shared reload: sweep every iops.* entry, re-register `keys`, then
    re-add the programmatic entries the sweep also removes — the widget
    LEFTMOUSE interact entry and the UI-toggle markers are NOT part of
    the bindable key tables, so register_keymaps() alone would leave the
    widget panels inert and the HUD toggles dead until addon reload."""
    # Detach the widget entry cleanly first so events._keymap_items never
    # holds references the iops.* sweep below already removed.
    widget_events.unregister_keymap()
    unregister_keymaps()
    register_keymaps(keys)
    register_ui_toggle_keymaps()
    widget_events.register_keymap()
    bpy.context.window_manager.keyconfigs.update()


class IOPS_OT_LoadUserHotkeys(bpy.types.Operator):
    bl_idname = "iops.load_user_hotkeys"
    bl_label = "Load User's Hotkeys"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        keys_user = []

        path = bpy.utils.script_path_user()
        user_hotkeys_file = os.path.join(
            path, "presets", "IOPS", "iops_hotkeys_user.py"
        )
        user_hotkeys_path = os.path.join(path, "presets", "IOPS")

        if os.path.exists(user_hotkeys_file):
            try:
                with open(user_hotkeys_file, encoding='utf-8') as f:
                    keys_user = json.load(f)
                if not isinstance(keys_user, list):
                    print("IOPS: Invalid hotkeys file format, using empty list")
                    keys_user = []
            except (json.JSONDecodeError, IOError, UnicodeDecodeError, Exception) as e:
                print(f"IOPS: Error loading user hotkeys - {e}, using empty list")
                keys_user = []
        else:
            try:
                os.makedirs(user_hotkeys_path, exist_ok=True)
                with open(user_hotkeys_file, "w", encoding='utf-8') as f:
                    f.write("[]")
            except Exception as e:
                print(f"IOPS: Error creating hotkeys file - {e}")

        _reload_keymaps(merge_missing_defaults(keys_user))
        print("Loaded user's hotkeys")
        return {"FINISHED"}


class IOPS_OT_LoadDefaultHotkeys(bpy.types.Operator):
    bl_idname = "iops.load_default_hotkeys"
    bl_label = "Load Default Hotkeys"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        _reload_keymaps(build_bindable_defaults())
        print("Loaded default hotkeys")
        return {"FINISHED"}
