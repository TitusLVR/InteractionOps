# Cursor Rotate

Rotates the scene's 3D cursor around its own X, Y, or Z axis by a fixed angle. The rotation is applied to the cursor's local matrix, so it composes with the cursor's current orientation rather than aligning to world axes.

<div class="iops-meta" markdown="1">
<span class="key">bl_idname: iops.cursor_rotate</span>
<span class="mode">Mode: any</span>
<span>Context: VIEW_3D</span>
<span class="modal">Modal: no</span>
<span class="hud">HUD: no</span>
</div>

## Overview
Useful for nudging the 3D cursor into a specific orientation for custom transform orientations, snapping, or tool pivots without leaving the viewport. Because the operator multiplies the cursor matrix by a local-axis rotation, repeated calls accumulate; combine with the `reverse` flag to step the other way.

## Usage
- Works in the 3D Viewport in any mode.
- Default keymap: <kbd>Ctrl</kbd>+<kbd>Alt</kbd>+<kbd>Shift</kbd>+<kbd>F19</kbd>.
- Set `rotation_axis`, `angle`, and optionally `reverse` via the operator redo panel (F9) or when calling from a menu/script.

## Properties
| Name | Type | Default | Description |
| --- | --- | --- | --- |
| `rotation_axis` | Enum | `X` | Local cursor axis to rotate around. Items: `X`, `Y`, `Z`. |
| `angle` | Float | `90` | Rotation amount in degrees. |
| `reverse` | Bool | `False` | If true, rotates by `-angle` instead of `+angle`. |

## Notes
- Rotation is applied as `cursor.matrix @ Rotation(angle, axis)`, i.e. in the cursor's local frame; world-axis rotation is not supported.
- Registered under `REGISTER` + `UNDO`, so the action is undoable and adjustable from the redo panel.
- Reports `Cursor rotated <angle> around <axis> axis` to the info area on success.

## Related
- [Object Rotate](op_object_rotate.md)
