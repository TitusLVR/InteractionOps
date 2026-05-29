# Save/Load Space Data

Saves and restores per-area UI visibility state (header, menus, and Outliner column toggles) into the current `Scene` as a custom `IOPS` dictionary. The pair lets you stash a tidy editor layout once and snap any area back to it later without juggling Blender workspaces.

<div class="iops-meta" markdown="1">
<span class="key">bl_idname: iops.space_data_save</span>
<span class="mode">Mode: any</span>
<span>Context: any editor (VIEW_3D, OUTLINER, IMAGE_EDITOR, ...)</span>
<span class="modal">Modal: no</span>
<span class="hud">HUD: no</span>
</div>

<div class="iops-meta" markdown="1">
<span class="key">bl_idname: iops.space_data_load</span>
<span class="mode">Mode: any</span>
<span>Context: any editor (VIEW_3D, OUTLINER, IMAGE_EDITOR, ...)</span>
<span class="modal">Modal: no</span>
<span class="hud">HUD: no</span>
</div>

## Overview
Both operators read the type of the area under the mouse (`context.area.type`) and key the saved state by that type. Generic editors get two flags stored: header visibility (`show_region_header`) and menu visibility (`show_menus`). The Outliner is special-cased and additionally captures the display mode and the column toggles relevant to `VIEW_LAYER` and `SCENES` modes, plus the `use_sort_alpha` flag for every mode except `DATA_API`.

Useful when you keep custom-trimmed editors (no header, no menus, no Outliner filter columns) and want a one-click way to re-apply that look after Blender, a workspace switch, or someone else's blend file scrambles it.

State lives on the current `Scene` under `scene["IOPS"][<AREA_TYPE>]`, so it is scene-local and survives save/reload of the .blend.

## Usage
- Hover the cursor over the editor you want to save or restore (the active area is read from `context.area`).
- Run `iops.space_data_save` to capture the current visibility state for that area type.
- Run `iops.space_data_load` later to push the stored state back into any area of the same type.
- No default keymap binding. Invoke via F3 search or wire into your own keymap / pie.

## Notes
- Save overwrites the existing entry for the area type without prompting.
- Load reports `"No space data to load!"` if `scene["IOPS"]` is empty, or `"No space data for <AREA_TYPE>"` if nothing was ever saved for that editor.
- Outliner load relies on the keys that save wrote for the current display mode; switching the display mode between save and load can leave some toggles unchanged because the branch that writes them is gated on `display_mode`.
- State is per-scene. Switching scenes gives you a fresh, empty store.
- Both operators always return `{'FINISHED'}` and contribute to undo as ordinary operators (no special undo handling).

## Related
- Toggle Header
- Toggle Menus
