# Object Normalize

Rounds the location, rotation (in degrees), and dimensions of every selected object to a chosen number of decimal digits. Useful for cleaning up values that drifted off whole numbers after transforms, snaps, or imports.

<div class="iops-meta" markdown="1">
<span class="key">bl_idname: iops.object_normalize</span>
<span class="mode">Mode: Object</span>
<span>Context: VIEW_3D</span>
<span class="modal">Modal: no</span>
<span class="hud">HUD: no</span>
</div>

## Overview
After modelling, kitbashing, or array-driven layouts it is common to end up with object transforms like `1.99999998` or rotations like `89.9999°`. This operator iterates the current selection and rounds each component (X/Y/Z) of location, rotation_euler, and dimensions to `precision` decimal digits. Rotation is rounded in degrees, then written back as radians, so the rounding matches what is shown in the N-panel.

Prefer this over manually retyping values when many objects need to be tidied at once. It is a one-shot `REGISTER`/`UNDO` operator, so the redo panel exposes the toggles.

## Usage
- Required context: 3D Viewport in Object Mode with at least one selected object; the active object must be a `MESH` or `EMPTY`.
- Default keymap: <kbd>UP_ARROW</kbd> (no modifiers) in the 3D View.
- Adjust `Precision` and the per-channel toggles in the redo panel after execution.

## Properties

| Name | Type | Default | Description |
| --- | --- | --- | --- |
| `precision` | Int | 2 | Number of decimal digits to keep. Soft range 0–10. |
| `location` | Bool | True | Round object location X/Y/Z. |
| `rotation` | Bool | True | Round object rotation_euler X/Y/Z (rounding done in degrees). |
| `dimensions` | Bool | True | Round object dimensions X/Y/Z. |

## Notes
- The operator polls only the active object's type (`MESH` or `EMPTY`), but it iterates all selected objects and rounds them regardless of their individual type. Non-mesh/empty objects in the selection are still affected.
- Writing to `ob.dimensions` triggers a scale change on meshes; on objects without geometry bounds this is a no-op or undefined.
- Rotation is processed via Euler only; objects using Quaternion or Axis-Angle rotation modes will not see their displayed rotation channel rounded.
- A `depsgraph.update()` is issued after the loop. Standard `UNDO` applies.

## Related
- [Object Rotate](op_object_rotate.md)
- [Object To Grid From Active](op_grid_from_active.md)
- [Object Drag Snap](op_drag_snap.md)
