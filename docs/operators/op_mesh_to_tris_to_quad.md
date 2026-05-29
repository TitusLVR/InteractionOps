# Tris to Quads

Runs Blender's Triangulate followed by Tris-to-Quads in a single undo step. Useful for re-flowing a mesh: blow it down to triangles with controlled diagonals, then merge back to quads with explicit thresholds and attribute boundaries.

<div class="iops-meta" markdown="1">
<span class="key">bl_idname: iops.mesh_to_tris_to_quads</span>
<span class="mode">Mode: Edit Mesh</span>
<span>Context: VIEW_3D</span>
<span class="modal">Modal: no</span>
<span class="hud">HUD: no</span>
</div>

## Overview

The operator chains `mesh.quads_convert_to_tris` and `mesh.tris_convert_to_quads` with all relevant parameters exposed on one panel. It exists to make full-mesh requadding a single redo-panel adjustment instead of two separate operator calls with two F6 panels.

Typical use: cleaning up imported geometry, normalising diagonals after boolean work, or forcing a consistent triangulation method before re-merging to quads with seam/sharp/UV boundaries respected.

## Usage

- Active mesh object in Edit Mode. The faces affected are the current selection (both sub-operators inherit Blender's normal selection semantics).
- No default keymap binding (registered against `F19` placeholder in `hotkeys_default.py`). Invoke via F3 search or bind a key in preferences.
- After running, use the redo panel to tweak `Quad Method`, `N-gon Method`, the face/shape thresholds, and attribute-comparison toggles.

## Properties

| Name | Type | Default | Description |
| --- | --- | --- | --- |
| `quad_method` | Enum | `BEAUTY` | Diagonal strategy for splitting quads. Items: `BEAUTY`, `FIXED`, `FIXED_ALTERNATE`, `SHORTEST_DIAGONAL`. |
| `ngon_method` | Enum | `BEAUTY` | N-gon triangulation strategy. Items: `BEAUTY`, `CLIP` (ear clipping). |
| `face_threshold` | Float (angle) | `0.698132` rad (~40 deg) | Max face angle for tri pairs to be merged. Range 0 to pi. |
| `shape_threshold` | Float (angle) | `1.5708` rad (90 deg) | Max shape angle. Range 0 to pi. |
| `topology_influence` | Float | `2.0` | Weight of existing edge topology when choosing pairs. Range 0 to 2. |
| `uvs` | Bool | `False` | Don't merge across UV seams. |
| `vcols` | Bool | `False` | Don't merge across color-attribute discontinuities. |
| `seam` | Bool | `False` | Don't merge across marked seams. |
| `sharp` | Bool | `False` | Don't merge across sharp edges. |
| `materials` | Bool | `False` | Don't merge across material boundaries. |
| `deselect_joined` | Bool | `False` | Deselect faces that got merged. |

## Notes

- Single undo step covers both Blender ops.
- Triangulation always runs first, so even quads already in the selection are split and then re-merged according to the thresholds; this can change diagonals on faces that were "fine" beforehand.
- Poll requires an active mesh in Edit Mode; nothing is done in Object Mode.
- No panel, menu, or PropertyGroup is registered alongside the operator.

## Related

- [Quick Connect](op_mesh_quick_connect.md)
- [Mesh to Grid](op_mesh_to_grid.md)
- [Cursor Bisect](op_mesh_cursor_bisect.md)
