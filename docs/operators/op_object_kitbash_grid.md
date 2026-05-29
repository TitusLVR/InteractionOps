# KitBash Grid

Sorts the current selection by bounding-box criteria and re-places the objects in a linear row or grid, starting from the active object's position. Designed for laying out kitbash parts, prop libraries, or scattered mesh sets into a tidy, inspectable arrangement without manual measuring.

<div class="iops-meta" markdown="1">
<span class="key">bl_idname: iops.object_kitbash_grid</span>
<span class="mode">Mode: Object</span>
<span>Context: VIEW_3D</span>
<span class="modal">Modal: no</span>
<span class="hud">HUD: no</span>
</div>

## Overview
The operator measures each selected object's world-space bounding box (mesh objects directly, empties via the compound bbox of their recursive mesh children), sorts the result by the chosen criterion, then walks the sorted list outward from the active object's maximum edge. Each placed object is offset by the configured gap so bounding boxes never overlap, and a chosen alignment per axis (min / center / max) decides which face of each bbox lands on the cursor line.

Use it after dropping a pile of kitbash meshes into a scene to get a sortable, comparable grid; or to re-flow an existing layout after adding new pieces. Unlike Blender's built-in Array, this works across heterogeneous, independently-sized objects and is sort-aware.

## Usage
- Object Mode in the 3D Viewport, with at least one selected object and an active object.
- Selection may be all meshes, or all empties (in which case each empty is sized by the union bbox of its recursive mesh children); mixed selections fall back to mesh-only sizing.
- Invoke via search / menu; no default keymap binding. A redo-style props dialog opens (`invoke_props_dialog`) so columns can be auto-suggested and parameters tweaked before applying.
- On invoke in Grid mode, `grid_columns` is auto-set to `ceil(sqrt(valid_count))` to bias toward a square grid.
- Press OK to apply. Undo is supported (`REGISTER | UNDO`).

## Properties
| Name | Type | Default | Description |
| --- | --- | --- | --- |
| `arrange_mode` | Enum (`LINEAR`, `GRID`) | `GRID` | Single line, or wrapped grid. |
| `grid_columns` | Int (min 1) | 5 (auto-set on invoke) | Column count when `arrange_mode = GRID`. |
| `arrange_axis` | Enum (`X`, `Y`) | `X` | Primary axis: linear direction, or grid column direction. |
| `gap_x` | Float distance (min 0) | 0.1 | Gap between bboxes along X. |
| `gap_y` | Float distance (min 0) | 0.1 | Gap between bboxes along Y. |
| `sort_by` | Enum | `VOLUME` | Sort criterion. Items: `VOLUME`, `X_DIM`, `Y_DIM`, `Z_DIM`, `VOLUME_INV`, `X_DIM_INV`, `Y_DIM_INV`, `Z_DIM_INV`, `NAME`, `NAME_INV`. `_INV` variants reverse the order. |
| `align_x` | Enum (`MIN`, `CENTER`, `MAX`) | `CENTER` | Which X face of each bbox aligns to its target line. |
| `align_y` | Enum (`MIN`, `CENTER`, `MAX`) | `CENTER` | Same for Y. |
| `align_z` | Enum (`MIN`, `CENTER`, `MAX`) | `CENTER` | Same for Z; Z target is taken from the active object's reference point. |

## Notes
- The active object itself is included in the sorted/placed set; it can move from its initial position. The initial active bbox is captured before any placement so the layout origin and Z reference stay stable.
- Placement walks the cursor outward from the active object's `max` edge on the primary axis, plus `gap_primary`. In Grid mode, the secondary axis advances by `max(secondary dim in row) + gap_secondary` per new row.
- Per-object bbox is recomputed via `depsgraph.update()` after each placement, so modifier-driven dimensions are honoured.
- For empty-only selections, `obj.location.z` is forced to 0 after each move; the union bbox of recursive mesh children defines the empty's effective size. Empties without mesh descendants collapse to a zero-size point at their origin.
- Objects without a valid bbox (no mesh data, evaluation error) are silently skipped. If the active object itself fails to evaluate, the operator cancels.
- Non-numeric (`NAME`) sort with `_INV` is handled separately: the reverse flag is applied at sort time rather than via key negation.
- No HUD, no modal, no panel registration; this file registers only `IOPS_OT_KitBash_Grid`.

## Related
- [Object Drag Snap](op_drag_snap.md)
- [Object To Grid From Active](op_grid_from_active.md)
- [Object Normalize](op_object_normalize.md)
