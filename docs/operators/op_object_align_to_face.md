# Align Object to Face

Reorients the active mesh object so that the active face's normal lines up with a chosen world axis, using one of the face's edges as the secondary axis reference. Runs as a modal so you can cycle the reference edge, flip the normal, switch the target axis, and nudge the object's position before committing. Useful when you need an object's local frame to match a piece of geometry instead of eyeballing rotations.

<div class="iops-meta" markdown="1">
<span class="key">bl_idname: iops.mesh_align_object_to_face</span>
<span class="mode">Mode: Edit Mesh</span>
<span>Context: VIEW_3D</span>
<span class="modal">Modal: yes</span>
<span class="hud">HUD: yes</span>
</div>

## Overview
The operator is launched from Edit Mode on a mesh that has an active face. It computes a new world matrix from that face: the face normal becomes the chosen world axis, the selected face edge becomes the second axis, and the cross product fills in the third. Because it rewrites `matrix_world` directly, scale and translation are preserved separately, so the object stays where it was while its rotation snaps to the face.

Prefer this over manual rotation snapping when you want to seat an object flat against a specific polygon and don't want to bother with a custom transform orientation just for the operation. The modal exposes edge cycling so you can also pick which in-plane direction becomes "forward".

## Usage
- Edit Mode on a `MESH` object, with at least one face set as the active face (the last clicked face).
- No default keymap binding. Invoke via search (F3) `MESH: Align object to face`, or call `bpy.ops.iops.mesh_align_object_to_face('INVOKE_DEFAULT')`. A wrapper `align_to_face()` in `utils/functions.py` is the canonical entry point.
- On invoke the operator immediately aligns the active face normal to world Z using edge index 0; from there use the modal keys to refine.

## Modal Controls

| Key | Action |
| --- | --- |
| <kbd>X</kbd> / <kbd>Y</kbd> / <kbd>Z</kbd> | Set target rotation axis (the axis the face normal aligns to). Each press also flips the normal direction. |
| <kbd>Shift</kbd> + <kbd>X</kbd> / <kbd>Y</kbd> / <kbd>Z</kbd> | Arm a move axis for subsequent wheel nudges. |
| <kbd>Wheel Up</kbd> | Cycle to next reference edge of the active face. |
| <kbd>Wheel Down</kbd> | Cycle to previous reference edge (clamped at 0). |
| <kbd>Shift</kbd> + <kbd>Wheel Up</kbd> | Move object by +0.5 along the armed move axis. |
| <kbd>Shift</kbd> + <kbd>Wheel Down</kbd> | Move object by -0.5 along the armed move axis. |
| <kbd>MMB</kbd> | Pass through (viewport navigation). |
| <kbd>H</kbd> | Toggle help overlay / HUD visibility (handled by the HUD/Help machinery). |
| <kbd>LMB</kbd> / <kbd>Space</kbd> | Confirm. |
| <kbd>RMB</kbd> / <kbd>Esc</kbd> | Cancel and restore the object's original `matrix_world`. |

The HUD and help overlays also respond to drag (to reposition) and to the param-toggle events implemented by the HUD module.

## HUD
On-screen overlay shows:
- Header line 1: `Edge: <index>` — current reference edge within the active face (0-based, modulo edge count).
- Header line 2: `Axis: <X|Y|Z>` — the world axis the face normal is currently aligned to.

The help overlay (`H`) lists modal bindings: cycle edge (wheel), align axis (X/Y/Z), move with Shift, confirm, cancel, help toggle.

A separate POST_VIEW pass draws the chosen face edge in 3D using the theme's `ACTIVE_LINE` and `ACTIVE_POINT` roles, so you can see which edge currently defines the secondary axis.

## Properties

| Name | Type | Default | Description |
| --- | --- | --- | --- |
| `axis_move` | String | `"Z"` (set in invoke) | Currently armed translation axis for Shift+Wheel nudges. |
| `axis_rotate` | String | `"Z"` (set in invoke) | World axis the active face normal is aligned to. |
| `loc` | FloatVector | `(0,0,0)` | Accumulated translation offset applied via Shift+Wheel. |
| `edge_idx` | Int | `0` | Initial edge index used on invoke. |
| `counter` | Int | `0` | Wheel counter; `counter % len(face.edges)` selects the reference edge. |
| `flip` | Bool | `True` (set in invoke) | Whether to flip the face normal before building the basis. Toggles on every X/Y/Z press. |

All props are operational state, not user-facing tuning knobs — there is no redo panel exposure beyond what Blender auto-generates.

## Notes
- Poll requires `VIEW_3D` + `EDIT_MESH` + active object of type `MESH` and a non-empty selection. The operator does not validate that a face is actually active; if none is active, `bm.faces.active` will be `None` and the call will error.
- Cancel (`RMB` / `Esc`) restores `matrix_world` from a snapshot taken at invoke; confirm leaves the new matrix in place and the operator participates in undo via `REGISTER | UNDO`.
- Movement nudges (`Shift+Wheel`) accumulate into `self.loc` and are written straight to `object.location`; they are not axis-locked to the new basis, they translate along world axes.
- The Shift+X/Y/Z press re-applies the cached `self.loc` to `object.location` but does not change rotation — it only arms the move axis.
- Pressing the same axis key twice toggles the normal flip, so X/Y/Z can be used to invert face-up direction without changing axis.

## Related
- [Align Origin to Normal](op_align_origin_to_normal.md)
- [Align View to Face](op_object_align_to_face.md)
