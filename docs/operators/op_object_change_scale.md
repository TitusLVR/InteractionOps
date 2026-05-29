# Change Scale

Sets the object's `scale` to a new value while compensating mesh data so the visible dimensions stay the same. Useful when you need a specific scale value on the transform (for export, rigging, or downstream tooling) without altering how the object looks in the viewport.

<div class="iops-meta" markdown="1">
<span class="key">bl_idname: iops.object_change_scale</span>
<span class="mode">Mode: Object</span>
<span>Context: VIEW_3D</span>
<span class="modal">Modal: no</span>
<span class="hud">HUD: no</span>
</div>

## Overview
Blender's `Object > Apply > Scale` zeroes the scale to 1,1,1 by baking it into mesh data. This operator does the opposite direction: you pick the scale value you want the object to end up with, and the mesh vertices are rescaled by `obj.scale / new_scale` so visual dimensions are preserved. Typical use is forcing a non-unit scale (e.g. 100, 100, 100 for unit conversion targets) without distorting the model.

The dialog initializes from the active object's current scale, so confirming without edits is a no-op.

## Usage
- Object Mode in the 3D Viewport with at least one object selected.
- Invoke via menu / search — no default keymap binding.
- A property dialog opens with an XYZ scale field; confirm with OK.
- Only mesh objects in the selection have their data rescaled; other object types are skipped (their `scale` is not changed either).
- Selected objects that happen to be in Edit Mode are temporarily switched to Object Mode for the operation and restored afterwards.

## Properties
| Name | Type | Default | Description |
| --- | --- | --- | --- |
| `scale` | FloatVector (XYZ subtype) | `(1.0, 1.0, 1.0)` | Target scale to write into `obj.scale`. Min 0.0001, soft max 10.0. On invoke this is preset to the active object's current scale. Any axis component equal to 0 is treated as 1.0 internally to avoid division by zero. |

## Notes
- Registered with `REGISTER | UNDO`, so the operation is undoable and the redo panel can adjust the scale value after execution.
- Mesh data is mutated in place via `vertex.co *= factor` followed by `data.update()`. Linked/shared mesh data will therefore affect every user of that mesh.
- Non-mesh object types (curve, empty, armature, etc.) are silently skipped — neither their data nor their `scale` is touched.
- The original active object is restored at the end; selection is not changed.
- Reports the final scale as an INFO message.

## Related
- [Normalize Scale](op_object_normalize.md)
- [Object Rotate](op_object_rotate.md)
- [Drag Snap](op_drag_snap.md)
