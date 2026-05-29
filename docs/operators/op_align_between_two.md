# Align Between Two

Duplicates the active object and distributes the copies along the straight line connecting two reference objects (or between three selected objects, pairwise). Optionally orients each duplicate so a chosen local axis tracks along the line. Useful for evenly spacing instances between two anchors without having to compute positions by hand.

<div class="iops-meta" markdown="1">
<span class="key">bl_idname: iops.object_align_between_two</span>
<span class="mode">Mode: Object</span>
<span>Context: VIEW_3D</span>
<span class="modal">Modal: no</span>
<span class="hud">HUD: no</span>
</div>

## Overview
The operator reads the current selection and the active object, then builds a sequence of interpolated positions between anchor locations. With two objects selected, copies are placed between the active object and the other selected object. With three objects selected, copies are placed in two segments along the chain `objects[0] -> objects[1] -> objects[2]` (pairwise interpolation between consecutive items in the selected-but-not-active list).

All duplicates are linked into a fresh collection named `Objects Between` at the scene root. Each duplicate is a shallow copy of the active object with its own `data` block (`active.data.copy()`), so meshes are not linked.

## Usage
- Object Mode. Select either 2 or 3 objects; the active object is treated as one of the anchors when only 2 are selected.
- No default keymap binding. Invoke via F3 search ("Align Between Two") or through the menus where the operator is wired.
- Adjust `Count`, `Align`, `Track`, `Up`, and `Select Duplicated` in the redo (F6 / Adjust Last Operation) panel.
- If `Track` equals `Up`, the operator reports `SAME AXIS` and does nothing (no duplicates are created).
- If selection count is not 2 or 3, a message box `Must be 2 or 3 Objects Selected.` is shown and the operator aborts before creating the collection.

## Properties

| Name | Type | Default | Description |
| --- | --- | --- | --- |
| `track_axis` | Enum: `X`, `Y`, `Z`, `-X`, `-Y`, `-Z` | `Y` | Local axis of each duplicate that tracks along the line between the anchors. Only used when `Align` is on. |
| `up_axis` | Enum: `X`, `Y`, `Z` | `Z` | Up axis passed to `Vector.to_track_quat`. Must differ from `track_axis`. |
| `align` | Bool | `False` | When enabled, rotate each duplicate so `track_axis` points along the anchor-to-anchor vector, using `up_axis` as the up reference. Rotation is written via quaternion and then the rotation mode is switched back to `XYZ`. |
| `count` | Int | `1` (soft range `0..100000000`) | Number of duplicates created per segment. Positions are evenly spaced at `p = i / (count + 1)` for `i` in `1..count`, so endpoints are never occupied. |
| `select_duplicated` | Bool | `True` | When enabled, deselect the original active and anchor objects and select all newly created duplicates, making the last duplicate active. When disabled, the original selection is preserved. |

## Notes
- A new collection `Objects Between` is created on every run and linked into the scene's root collection. Repeated runs produce `Objects Between`, `Objects Between.001`, etc.
- Each duplicate copies the active object's `data`, so this is not memory-cheap for heavy meshes. There is no instancing option.
- The interpolation uses `p = 1 / (count + 1) * (i + 1)`, which excludes both endpoints. With `count = 1` you get a single midpoint duplicate per segment.
- With 3 selected objects, the direction used for `track_axis` alignment in every duplicate is `posA - posB` (the first segment's direction); the second segment uses the same axis vector, not its own.
- The operator's `draw` method references a `mode` property that is not defined on the class, which will raise an error if Blender invokes the custom redo panel draw. The Adjust Last Operation panel may therefore fall back or error; properties remain editable via the operator's auto-generated UI in practice.
- `REGISTER` and `UNDO` are set, so the operator participates in normal undo.

## Related
- Align Origin To Selection
- Align Origin To Bottom
- [Object Aligner](op_object_aligner.md)
