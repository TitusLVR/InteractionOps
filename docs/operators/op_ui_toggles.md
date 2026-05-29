# UI Toggles

Two no-op marker operators whose only purpose is to own keymap items. Modal operators that draw a HUD or Help overlay read these keymap items to discover which keys the user has bound for "toggle help" and "toggle HUD parameter rows", instead of hard-coding a key or duplicating a `StringProperty` in addon preferences.

<div class="iops-meta" markdown="1">
<span class="key">bl_idname: iops.ui_help_toggle</span>
<span class="mode">Mode: any</span>
<span>Context: any</span>
<span class="modal">Modal: no</span>
<span class="hud">HUD: no</span>
</div>

<div class="iops-meta" markdown="1">
<span class="key">bl_idname: iops.ui_hud_params_toggle</span>
<span class="mode">Mode: any</span>
<span>Context: any</span>
<span class="modal">Modal: no</span>
<span class="hud">HUD: no</span>
</div>

## Overview

Both operators are tagged `INTERNAL` and their `execute()` returns `{"CANCELLED"}` — invoking them directly does nothing. They exist purely so the addon can register standard Blender keymap items for them. A running modal operator inspects the relevant keymap item's current `type` (and modifier flags) at event time, so the user can rebind the help/HUD-params keys from the standard Keymap UI rather than from a custom string field in preferences.

Centralising these bindings as real keymap items keeps every iops hotkey discoverable in one place and removed the previously duplicated "default H" key that lived in both `AddonPreferences` and the Theme tab.

## Help Toggle Marker (bl_idname: iops.ui_help_toggle)

Marker for the key that expands/collapses the corner Help overlay drawn by modal operators.

- No default keymap binding — bound by the user (or installed by another part of the addon's keymap setup) via the Keymaps UI.
- Read by HUD/help-drawing modals (see `ui/hud/help.py`, `ui/hud/overlay.py`).

## HUD Params Toggle Marker (bl_idname: iops.ui_hud_params_toggle)

Marker for the key that hides/shows the HUD parameter rows while a modal is running.

- No default keymap binding.
- Read by the HUD overlay code to gate the parameter section visibility.

## Usage

These operators are not meant to be called from the user. Bind a key to each via Blender's Keymap editor (or via the addon's keymap setup), then run any iops modal that draws a HUD or Help overlay — the modal will pick up your binding automatically.

## Notes

- Both classes carry `bl_options = {"INTERNAL"}` so they do not appear in the operator search menu.
- `execute()` returns `{"CANCELLED"}` so invoking them never lands on the undo stack.
- Other files that read these idnames: `prefs/theme.py`, `prefs/addon_preferences.py`, `ui/hud/help.py`, `ui/hud/overlay.py`, `operators/mesh_cursor_bisect.py`, `utils/functions.py`.

## Related

- [Addon Preferences](../preferences.md)
- [Theme](../preferences.md)
