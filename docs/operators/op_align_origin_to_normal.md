# Align Origin to Normal

Aligns the active mesh object's origin and rotation to the active face: the origin is moved to the face centroid and the object is rotated so its local Z axis matches the face normal and its local X axis follows the face's longest-edge tangent. Useful when you need an object's transform to match a surface so subsequent moves, scales, and child placements respect that surface.

<div class="iops-meta" markdown="1">
<span class="key">bl_idname: iops.mesh_align_origin_to_normal</span>
<span class="mode">Mode: Edit Mesh</span>
<span>Context: VIEW_3D</span>
<span class="modal">Modal: no</span>
<span class="hud">HUD: no</span>
</div>

## Overview

Blender's "Set Origin" lets you place the origin at the 3D cursor or at the selected geometry, but it does not reorient the object to that geometry's normal. This operator combines both steps: it snaps the cursor to the current selection, sets the origin there, then rebuilds the object's world matrix from the active face's normal and longest-edge tangent so the resulting local axes are predictable (Z = normal, X follows the longest edge).

Before computing the new matrix, the operator applies any pending rotation so it can be invoked repeatedly without compounding error. Location and scale are preserved across the realignment.

## Usage

- Enter Edit Mode on a mesh object.
- Make a face the active element (the active face is what `bm.faces.active` returns; click a face last to make it active).
- Run the operator.

Default keymap: <kbd>Alt</kbd>+<kbd>F5</kbd> in Edit Mesh (from `prefs/hotkeys_default.py`).

The poll requires VIEW_3D, EDIT_MESH mode, at least one selected object, and an active object of type MESH.

## Notes

- The new local axes are built as `Z = face.normal`, `X = -face.calc_tangent_edge()` (longest-edge tangent, negated), `Y = (normal x tangent) * -1`.
- The operator calls `view3d.snap_cursor_to_selected` and `object.origin_set(type="ORIGIN_CURSOR")`, so the 3D cursor is moved as a side effect.
- It also calls `object.transform_apply(rotation=True)` twice (once at the start of `execute`, once inside the alignment routine) so repeated invocations produce stable results; this bakes any prior rotation into the mesh data.
- If there is no active face the call to `face.calc_tangent_edge()` will fail - select a face explicitly before running.
- Registered as a single `REGISTER`/`UNDO` operator; no panel, menu, or PropertyGroup is registered alongside it.

## Related

- Align View to Active
- [Object Aligner](op_object_aligner.md)
