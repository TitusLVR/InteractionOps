# Object Color

Picker-driven assignment of `obj.color` (the RGBA used by the viewport's Solid > Object color shading mode) to every selected object. The module also exposes copy-from-active and a recent-swatch row backed by eight scene-level color slots, so frequently used tints can be re-applied without re-opening the picker.

## Overview

Blender's per-object color lives on `obj.color` and is read by the Solid shading "Object" color mode. There is no built-in convenience for batch-assigning it, sampling it from the active object, or recalling recent tints. This module provides three small operators that the Object Color panel wires together:

- One operator writes the picker color to all selected objects.
- One operator samples the active object's color back into the picker (no write).
- One operator applies a stored recent swatch to the selection and loads it into the picker.

Recents are stored as `iops_object_color_recent_0..7` on `IOPS_SceneProperties`, with slot 0 being the most recent. They are only mutated on explicit Apply (or push-on-equal dedup), so scrubbing the picker does not flood the swatch row.

## Apply Color (bl_idname: iops.object_color_apply)

<div class="iops-meta" markdown="1">
<span class="key">bl_idname: iops.object_color_apply</span>
<span class="mode">Mode: Object</span>
<span>Context: VIEW_3D</span>
<span class="modal">Modal: no</span>
<span class="hud">HUD: no</span>
</div>

### Usage
- Requires at least one selected object (poll fails otherwise).
- No default keymap binding — invoked from the Object Color panel / search.
- Reads `context.scene.IOPS.iops_object_color` and assigns it to `obj.color` for every selected object. Object types that reject the assignment are silently skipped.
- On success the picker color is pushed into the recents row (dedup: if the color already exists in a slot, that slot is moved to position 0 and earlier slots shift down).
- Reports `CANCELLED` with an error if no selected object accepted the color.

### Properties
None.

## Copy From Active (bl_idname: iops.object_color_copy_from_active)

<div class="iops-meta" markdown="1">
<span class="key">bl_idname: iops.object_color_copy_from_active</span>
<span class="mode">Mode: Object</span>
<span>Context: VIEW_3D</span>
<span class="modal">Modal: no</span>
<span class="hud">HUD: no</span>
</div>

### Usage
- Requires an active object.
- No default keymap binding.
- Reads `active_object.color` and writes it into `scene.IOPS.iops_object_color`. Does not modify any object, does not touch recents.

### Properties
None.

## Apply Recent Color (bl_idname: iops.object_color_apply_recent)

<div class="iops-meta" markdown="1">
<span class="key">bl_idname: iops.object_color_apply_recent</span>
<span class="mode">Mode: Object</span>
<span>Context: VIEW_3D</span>
<span class="modal">Modal: no</span>
<span class="hud">HUD: no</span>
</div>

### Usage
- Requires at least one selected object.
- No default keymap binding — fired by clicking a swatch in the Object Color panel's recent row, passing `index` to address the slot.
- Reads `iops_object_color_recent_<index>`, applies it to every selected object, then loads the same color into the picker so subsequent Apply matches the swatch.
- Recents are intentionally NOT reordered here — the swatch row stays stable while the user clicks through it.

### Properties

| Name | Type | Default | Description |
| --- | --- | --- | --- |
| `index` | IntProperty | 0 | Recent slot (0 = most recent). Clamped to `0..7`. |

## Notes
- Recents are stored on the scene (`IOPS_SceneProperties`), so they persist with the .blend file. The slot count is fixed at 8 and must match the number of `iops_object_color_recent_N` properties declared on `IOPS_SceneProperties`.
- All three operators carry `REGISTER`/`UNDO`, so the color assignments are individually undoable. Sampling via Copy From Active is also undoable (it edits the picker prop).
- `_apply_to_selected` swallows `AttributeError`/`TypeError` per object, so object types that don't expose `.color` won't break a batch apply; they're just skipped from the count.
- The picker property itself (`iops_object_color`) and the recent slots live on `IOPS_SceneProperties`, declared elsewhere — this module only reads/writes them.

## Related
- [Object Normalize](op_object_normalize.md)
- [Object Rotate](op_object_rotate.md)
- [Object Drag Snap](op_drag_snap.md)
