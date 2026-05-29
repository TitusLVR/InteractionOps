# Select Similar Name

Selects every visible object in the scene whose name shares the same base as the active object, ignoring Blender's numeric duplicate suffixes (`.001`, `.002`, ...). Useful for grabbing all instances of a duplicated asset in one step without relying on data-block linkage.

<div class="iops-meta" markdown="1">
<span class="key">bl_idname: iops.object_select_similar_name</span>
<span class="mode">Mode: Object</span>
<span>Context: VIEW_3D</span>
<span class="modal">Modal: no</span>
<span class="hud">HUD: no</span>
</div>

## Overview
Blender's built-in "Select Linked" matches by mesh data, material, or library. This operator matches purely by name stem, which is the common case when objects were duplicated with Shift+D (sharing nothing but a name prefix) or imported in batches. The base name is computed by stripping a trailing `.NNN` numeric suffix from the active object's name and comparing against every other object's stripped name.

## Usage
- Requires an active object.
- Only visible objects are considered (`obj.visible_get()`); hidden, filtered-out, or excluded-collection objects are skipped.
- No default keymap binding — invoke via F3 search ("Select Similar Name") or wire it into a menu/pie manually.
- The active object itself is included in the resulting selection.
- A report line shows the count and the base name used for matching.

## Notes
- Base-name extraction uses the regex `^(.+?)(\.\d+)?$`. Names without a numeric suffix are matched as-is. Names like `Cube.001.002` strip only the trailing `.002`.
- Previously selected objects are not deselected first — this operator only adds to the selection. Run Alt+A before invoking if you want a clean match set.
- Registered with `REGISTER`/`UNDO`, so the selection change can be undone with Ctrl+Z.
- Matching is case-sensitive.

## Related
- [Active Object Scroll](op_ui_prop_switch.md)
- [Object Normalize](op_object_normalize.md)
