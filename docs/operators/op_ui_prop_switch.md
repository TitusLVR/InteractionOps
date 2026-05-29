# UI Prop Switch

Cycles the active object within the current selection. Two operators step the active marker forward or backward through `view_layer.objects.selected`, wrapping at either end. Useful when an operation depends on which selected object is "active" (e.g. parenting, snap targets, modifier copying) without deselecting anything.

Despite the module name `ui_prop_switch.py`, this file does not toggle UI properties — it registers two object-active scroll operators.

## Scroll Active UP (bl_idname: iops.object_active_object_scroll_up)

<div class="iops-meta" markdown="1">
<span class="key">bl_idname: iops.object_active_object_scroll_up</span>
<span class="mode">Mode: Object</span>
<span>Context: VIEW_3D</span>
<span class="modal">Modal: no</span>
<span class="hud">HUD: no</span>
</div>

### Overview
Walks the selection list one step forward from the current active object. When the active is the last item, it wraps to index 0. Reports the new active object's name via `INFO`.

### Usage
- Requires an active object that is part of the current selection.
- Default keymap: <kbd>Ctrl</kbd>+<kbd>Alt</kbd>+<kbd>WheelUp</kbd> (repeatable, `any` modifier slot set).
- Selection itself is not modified; only the active marker moves.

## Scroll Active DOWN (bl_idname: iops.object_active_object_scroll_down)

<div class="iops-meta" markdown="1">
<span class="key">bl_idname: iops.object_active_object_scroll_down</span>
<span class="mode">Mode: Object</span>
<span>Context: VIEW_3D</span>
<span class="modal">Modal: no</span>
<span class="hud">HUD: no</span>
</div>

### Overview
Steps the active object one position backward in the selection list. When the active is index 0, it wraps to the last item. Reports the new active via `INFO`.

### Usage
- Requires an active object that is part of the current selection.
- Default keymap: <kbd>Ctrl</kbd>+<kbd>Alt</kbd>+<kbd>WheelDown</kbd>.

## Notes
- Order of iteration follows `bpy.context.view_layer.objects.selected`, which is not user-sortable; the cycle order reflects Blender's internal order of selected objects.
- If the active object is not in the selected set, neither operator does anything (the loop never matches).
- No properties, no modal state, no HUD.
- The file name `ui_prop_switch.py` is legacy — the operators it registers are object-active scrollers.

## Related
- [Object Rotate](op_object_rotate.md)
- [Object Drag Snap](op_drag_snap.md)
- [Object Normalize](op_object_normalize.md)
