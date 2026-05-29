# Quick Snap (Mesh)

Snaps selected vertices of every mesh object currently in Edit Mode onto the nearest geometry of other visible meshes. Each selected vertex is moved either to the closest point on a target face (surface mode) or to the closest vertex of the face the BVH returns (point mode), with an optional face-normal facing filter.

<div class="iops-meta" markdown="1">
<span class="key">bl_idname: iops.mesh_quick_snap</span>
<span class="mode">Mode: Edit Mesh</span>
<span>Context: VIEW_3D</span>
<span class="modal">Modal: no</span>
<span class="hud">HUD: no</span>
</div>

## Overview
A one-shot snap pass that bypasses Blender's transform snapping. It collects every selected vertex across all meshes in Edit Mode and, for each, picks the best target across other edit objects and external visible meshes. The result is applied immediately via `bmesh.update_edit_mesh` and registered as an undoable step (`REGISTER`, `UNDO`).

External targets must be visible meshes with at least one polygon and no modifiers — meshes carrying any modifier are skipped because the operator uses `closest_point_on_mesh` on the evaluated `Object.data`. Edit-mode objects build a BVH over their own non-selected geometry, so other edit objects (and the same object, if self-snap is enabled) are valid targets.

## Usage
- Enter Edit Mode on one or more meshes and select the vertices you want to move. Operating outside Edit Mode emits a warning and exits.
- Invoke via menu / F3 search; no default keymap binding.
- Toggle the operator's redo-panel options to switch between surface vs. vertex snapping, allow self-snap, and enable normal-based rejection.

## Properties
| Name | Type | Default | Description |
| --- | --- | --- | --- |
| `quick_snap_surface` | Bool | `False` | When on, vertices snap to the closest point on the hit face. When off, they snap to the closest vertex of that face. |
| `quick_snap_self` | Bool | `False` | Also allow each edit object to snap its selected verts onto its own non-selected geometry. |
| `quick_snap_normal_check` | Bool | `False` | Reject candidates where the face normal points away from the vertex being moved. |
| `quick_snap_normal_angle` | Float | `90.0` | Maximum allowed angle (degrees) between the hit face normal and the vector from the hit point to the vertex. Range `0.0–180.0`. Only applied when `quick_snap_normal_check` is on. |

## Notes
- External target filter: `type == "MESH"`, has polygons, `visible_get()` is true, and `modifiers[:] == []`. Meshes with modifiers are silently ignored.
- For each edit object, a temporary bmesh copy with the selected verts deleted is built and a `BVHTree.FromBMesh` is constructed from it; edit objects with no remaining faces are skipped as targets.
- Per vertex, the operator iterates every target object and keeps the shortest-distance candidate. There is no spatial culling beyond the per-object BVH / `closest_point_on_mesh` query, so cost scales with `selected_verts * target_objects`.
- The normal-check angle compares the world-space face normal against the vector from the hit point to the vertex (`vert - hit`), clamped to `pi`. Zero-length vectors (vertex already on the surface) bypass the check.
- The final report is always `INFO: POINTS ARE SNAPPED!!!`, even when nothing moved.

## Related
- [Mesh Align](op_align_origin_to_normal.md)
- [Vert Align](op_align_origin_to_normal.md)
- Edge Slide Pro
