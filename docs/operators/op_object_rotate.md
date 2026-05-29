# Object Rotate (XYZ ±)

Six sibling operators that rotate selected objects by a fixed angle around the active object's local X, Y, or Z axis (positive and negative variants). The rotation pivot is each object's own origin and the orientation is taken from a temporarily relocated 3D Cursor, so each object spins in place around its local axis rather than around the scene origin or the active object's pivot.

## Overview

Blender's stock `transform.rotate` rotates everything around a single pivot or the median of the selection. These operators replicate the common DCC behaviour of "rotate every selected object 90 degrees around its own local axis" in a single keystroke. The shared rotation angle is read from `WindowManager.IOPS_AddonProperties.iops_rotation_angle` and applied as `+angle` for the positive variants and `-angle` for the M (minus) variants.

Under the hood each operator moves the 3D Cursor to the current object, aligns the cursor's rotation to the object's world rotation, runs `transform.rotate` with `orient_type="CURSOR"` constrained to one axis, and (optionally) restores the cursor's prior rotation mode. When `per_object` is on the operator iterates the selection one object at a time and reselects the original set at the end.

## Usage

- Object Mode in the 3D View with at least one selected object.
- Default keymap (3D View, Object Mode):

| bl_idname | Key |
| --- | --- |
| `iops.object_rotate_x`  | <kbd>Left</kbd> |
| `iops.object_rotate_mx` | <kbd>Shift</kbd> + <kbd>Left</kbd> |
| `iops.object_rotate_y`  | <kbd>Down</kbd> |
| `iops.object_rotate_my` | <kbd>Shift</kbd> + <kbd>Down</kbd> |
| `iops.object_rotate_z`  | <kbd>Right</kbd> |
| `iops.object_rotate_mz` | <kbd>Shift</kbd> + <kbd>Right</kbd> |

The angle is set globally via `WindowManager.IOPS_AddonProperties.iops_rotation_angle` (also exposed in the operator redo panel as "Rotation Angle"). Default is 90 degrees.

## IOPS Rotate +X (bl_idname: `iops.object_rotate_x`)

<div class="iops-meta" markdown="1">
<span class="key">bl_idname: iops.object_rotate_x</span>
<span class="mode">Mode: Object</span>
<span>Context: VIEW_3D</span>
<span class="modal">Modal: no</span>
<span class="hud">HUD: no</span>
</div>

Rotates by `+iops_rotation_angle` around each object's local X axis.

### Properties

| Name | Type | Default | Description |
| --- | --- | --- | --- |
| `per_object` | Bool | `True` | When on, iterates the selection and rotates each object around its own origin. When off, rotates only the active object. |
| `reset_cursor` | Bool | `True` | Saves the cursor's rotation mode, zeroes the cursor location/rotation before aligning it to the object, then restores the original rotation mode afterwards. The cursor location/rotation is not restored. |

## IOPS Rotate -X (bl_idname: `iops.object_rotate_mx`)

<div class="iops-meta" markdown="1">
<span class="key">bl_idname: iops.object_rotate_mx</span>
<span class="mode">Mode: Object</span>
<span>Context: VIEW_3D</span>
<span class="modal">Modal: no</span>
<span class="hud">HUD: no</span>
</div>

Rotates by `-iops_rotation_angle` around each object's local X axis. Same properties as `iops.object_rotate_x`.

## IOPS Rotate +Y (bl_idname: `iops.object_rotate_y`)

<div class="iops-meta" markdown="1">
<span class="key">bl_idname: iops.object_rotate_y</span>
<span class="mode">Mode: Object</span>
<span>Context: VIEW_3D</span>
<span class="modal">Modal: no</span>
<span class="hud">HUD: no</span>
</div>

Rotates by `+iops_rotation_angle` around each object's local Y axis. Same properties as `iops.object_rotate_x`.

## IOPS Rotate -Y (bl_idname: `iops.object_rotate_my`)

<div class="iops-meta" markdown="1">
<span class="key">bl_idname: iops.object_rotate_my</span>
<span class="mode">Mode: Object</span>
<span>Context: VIEW_3D</span>
<span class="modal">Modal: no</span>
<span class="hud">HUD: no</span>
</div>

Rotates by `-iops_rotation_angle` around each object's local Y axis. Same properties as `iops.object_rotate_x`.

## IOPS Rotate +Z (bl_idname: `iops.object_rotate_z`)

<div class="iops-meta" markdown="1">
<span class="key">bl_idname: iops.object_rotate_z</span>
<span class="mode">Mode: Object</span>
<span>Context: VIEW_3D</span>
<span class="modal">Modal: no</span>
<span class="hud">HUD: no</span>
</div>

Rotates by `+iops_rotation_angle` around each object's local Z axis. Same properties as `iops.object_rotate_x`.

## IOPS Rotate -Z (bl_idname: `iops.object_rotate_mz`)

<div class="iops-meta" markdown="1">
<span class="key">bl_idname: iops.object_rotate_mz</span>
<span class="mode">Mode: Object</span>
<span>Context: VIEW_3D</span>
<span class="modal">Modal: no</span>
<span class="hud">HUD: no</span>
</div>

Rotates by `-iops_rotation_angle` around each object's local Z axis. Same properties as `iops.object_rotate_x`.

## Notes

- The angle property `iops_rotation_angle` lives on the addon's `WindowManager.IOPS_AddonProperties` group and is shared across all six operators; changing it in the redo panel changes the next press of any of them.
- The 3D Cursor is moved by these operators. With `reset_cursor=True` the cursor's rotation mode is restored, but its final location/rotation is left at the last processed object. Disable `reset_cursor` if you have a custom cursor rotation mode worth preserving but accept that the cursor will be repositioned regardless.
- Rotation is built on `bpy.ops.transform.rotate` with `use_accurate=True`, so it goes through the standard transform stack and is undoable as a single step per press.
- When `per_object` is on, the operator deselects everything, processes objects one by one, then restores the original selection set. The active object after the operation is the last processed object, not necessarily the one that was active before.
- Poll requires `area.type == "VIEW_3D"`, `mode == "OBJECT"`, and at least one selected object.

## Related

- [Object Modal Three Point Rotation](op_object_three_point_rotation.md)
- [Cursor Rotate](op_cursor_rotate.md)
- [Object Drag Snap](op_drag_snap.md)
