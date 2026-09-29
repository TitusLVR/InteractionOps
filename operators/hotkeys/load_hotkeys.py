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
    # Per-widget toggle entries are NEVER_SAVE (the saved tuple can't
    # carry the widget-name property) — rebuild them from the registry.
    widget_events.sync_toggle_kmis()
    bpy.context.window_manager.keyconfigs.update()


class IOPS_OT_LoadUserHotkeys(bpy.types.Operator):
    bl_idname = "iops.load_user_hotkeys"
    bl_label = "Load User's Hotkeys"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        path = bpy.utils.script_path_user()
        user_hotkeys_file = os.path.join(
            path, "presets", "IOPS", "iops_hotkeys_user.py"
        )

        # A missing or unreadable file must leave the current keymap alone:
        # reloading an empty list swaps every binding for the defaults, and
        # the next Save would then persist that wipe over the user's file.
        if not os.path.exists(user_hotkeys_file):
            self.report({"WARNING"},
                        f"No saved hotkeys file: {user_hotkeys_file}")
            return {"CANCELLED"}
        try:
            with open(user_hotkeys_file, encoding='utf-8') as f:
                keys_user = json.load(f)
        except (json.JSONDecodeError, IOError, UnicodeDecodeError) as e:
            self.report({"ERROR"}, f"Can't read saved hotkeys: {e}")
            return {"CANCELLED"}
        if not isinstance(keys_user, list):
            self.report({"ERROR"}, "Invalid hotkeys file format")
            return {"CANCELLED"}

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
