# Grid from Active

Snaps the locations of all selected objects to a 3D grid whose origin is the active object's location and whose cell sizes are the active object's bounding-box dimensions (X, Y, Z). Useful for tiling kit pieces, modular blockouts, or any layout where every object should land on a multiple of the active's footprint.

<div class="iops-meta" markdown="1">
<span class="key">bl_idname: iops.object_to_grid_from_active</span>
<span class="mode">Mode: Object</span>
<span>Context: VIEW_3D</span>
<span class="modal">Modal: no</span>
<span class="hud">HUD: no</span>
</div>

## Overview
Each selected object's world location is quantised to the nearest grid cell defined by `(active.dimensions.x, active.dimensions.y, active.dimensions.z)` around the active object's origin. Locations already on the grid (within a near-zero tolerance) are left alone.

Prefer this over the built-in snap-to-grid when your modular pieces are not 1m cubes — the active's actual dimensions drive the cell size, so non-uniform kit parts still align cleanly.

## Usage
- Object Mode, VIEW_3D.
- Select two or more objects; the active one defines both the grid origin and the cell size via its bounding box dimensions.
- Run via menu / operator search. No default keymap binding.

## Notes
- The operator temporarily parents the selection to the active to neutralise transforms (`parent_set` with `keep_transform=True`, invert the active's matrix, then `parent_clear`). The active's original `matrix_world` is restored at the end. Two undo steps may be visible because of the parent/clear cycle.
- Cell size comes from `active.dimensions`, which is world-space bounding-box size — non-uniform scale and rotation on the active will skew the grid.
- If any component of `active.dimensions` is zero (flat/degenerate active), the division will produce NaN/Inf and locations will not be sensible. Make sure the active has volume on all three axes you care about.
- Objects whose locations already match the computed grid point (within `rtol=1e-21, atol=1e-24`) are skipped.
- Debug `print()` calls write per-object location deltas to the system console.
- Reports `"Aligned to grid from active"` on completion.

## Related
- [Mesh to Grid](op_mesh_to_grid.md)
- [Object Drag Snap](op_drag_snap.md)
- [Object Normalize](op_object_normalize.md)
