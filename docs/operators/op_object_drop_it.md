# Drop It

Drops selected mesh objects onto the nearest surface beneath them by raycasting from each object and snapping it to the hit point. Optionally aligns each object to the surface normal and respects the object's lowest face so it sits flush instead of intersecting the ground. Batch-processes all selected mesh objects in one invocation.

<div class="iops-meta" markdown="1">
<span class="key">bl_idname: iops.object_drop_it</span>
<span class="mode">Mode: Object</span>
<span>Context: VIEW_3D</span>
<span class="modal">Modal: no</span>
<span class="hud">HUD: no</span>
</div>

## Overview

Drop It is the alignment companion for placing props on terrain, floors, or any arbitrary mesh surface. Instead of eyeballing Z or using "Snap to Face" which only works during transforms, Drop It performs a real `scene.ray_cast` per object and rewrites its world matrix in one undo step.

It uses a `SmartRaycaster` with several fallback strategies — if the primary ray misses, it retries from a higher origin, then with a pure `-Z` direction, then with lateral origin offsets — so concave or recessed geometry is much less likely to leave an object stuck where it started. Non-mesh objects in the selection are skipped silently.

## Usage

- Select one or more mesh objects in Object mode in a 3D View.
- Run via F3 search ("Drop It!"), the Object - Alignment menu, or a custom shortcut — there is no default keymap binding.
- Tweak the redo panel (F9) to change direction, alignment, or offset after the drop.

## Properties

| Name | Type | Default | Description |
| --- | --- | --- | --- |
| `use_local_z` | Bool | `True` | Cast along the object's local `-Z`. When off, `drop_it_direction` is used. |
| `drop_it_direction` | FloatVector(3) | `(0, 0, -1)` | World-space raycast direction. Components clamped to `[-1, 1]`. Only used when `use_local_z` is off. |
| `respect_lowest_face` | Bool | `False` | After the hit, shift the object so the centre of its lowest-Z polygon (world space) sits on the hit point instead of the object origin. |
| `drop_it_align_to_surf` | Bool | `True` | Rotate the object to match the surface. If off, original rotation is preserved. |
| `alignment_method` | Enum | `NORMAL_ONLY` | How to build the new rotation. Items: `TRACK_TO` (Track To), `PROJECT` (Project), `NORMAL_ONLY` (Normal Only). |
| `track_axis` | Enum | `Z` | Axis pointed along the surface normal in `TRACK_TO` mode. Items: `X`, `Y`, `Z`, `-X`, `-Y`, `-Z`. If equal to `up_axis`, falls back to `NORMAL_ONLY`. |
| `up_axis` | Enum | `Y` | Up axis for `TRACK_TO`. Items: `X`, `Y`, `Z`. |
| `drop_it_offset` | FloatVector(3) | `(0, 0, 0)` | Post-drop world-space translation applied via `matrix_world @= Translation`. |
| `max_raycast_distance` | Float | `10000.0` | Maximum ray length. Range `[1.0, 100000.0]`. |
| `continue_on_failure` | Bool | `True` | Keep processing remaining objects when one fails to find a surface. |
| `detailed_reporting` | Bool | `False` | Emit per-object INFO/ERROR reports plus tracebacks instead of just a summary line. Exposed as "Debug" in the redo panel. |

Alignment methods:

- `NORMAL_ONLY` — builds a basis from the hit normal and an arbitrary up (`+Z`, or `+Y` if the normal is near-vertical). Cheapest and most predictable.
- `TRACK_TO` — uses `Vector.to_track_quat(track_axis, up_axis)` against the hit normal.
- `PROJECT` — projects the object's current world `+Y` onto the surface plane and rebuilds the basis around it, preserving heading where possible.

## Notes

- Only mesh objects from the selection are processed; others are skipped with no warning. If nothing in the selection is a mesh, the operator reports an error and cancels.
- The object itself is hidden during its own raycast to prevent self-hits, and its visibility is restored afterwards.
- Original scale is preserved when alignment is applied. When `drop_it_align_to_surf` is off, the original rotation matrix is reapplied at the new location.
- On a per-object exception the object's original `matrix_world` is restored before reporting the failure.
- Final summary is INFO on full success, WARNING on partial success, ERROR if every object failed (first error is re-reported).
- The module also defines internal helpers `RaycastResult`, `GeometryAnalyzer`, and `SmartRaycaster`; they are not registered as Blender classes.
- Registered classes: `IOPS_OT_Drop_It` only.

## Related

- [Object Aligner](op_object_aligner.md)
- [Object Drag Snap](op_drag_snap.md)
- [Object To Grid From Active](op_grid_from_active.md)
- [Mesh Align Origin to Normal](op_align_origin_to_normal.md)
