# UVMaps Cleaner

Batch-removes UV map layers from selected mesh objects starting at a chosen slot index. Eight sibling operators expose slot positions 0..7: each removes every UV map at and after its index, so slot 0 wipes them all and slot 7 removes only the last one. Useful for cleaning up imported assets that accumulated stray or duplicate UV channels.

## Overview

Blender's UI removes UV maps one at a time on a single active object. This module provides per-slot operators that iterate over the current selection and trim UV layers in one click. Each operator targets a fixed start index; pick the one matching the first slot you want to discard.

Only `MESH` objects that are visible in the current view layer and have at least one polygon are processed. Non-mesh and empty-mesh selections are silently skipped.

## Usage

- Select one or more mesh objects in Object Mode.
- Invoke the slot operator that corresponds to the first UV map you want to remove (slot 0 = remove all, slot N = keep maps 0..N-1, drop the rest).
- All eight operators have no default keymap binding; invoke via F3 search or wire them into a custom menu / pie.

## The eight slot operators

All eight share the same logic — they differ only by the start index passed to the internal cleaner. Pattern: for a selected mesh, iterate UV layers from the last down to the start index and remove them.

| bl_idname | Label | First slot removed | Result |
| --- | --- | --- | --- |
| `iops.object_clean_uvmap_0` | Remove All UVMaps | 0 | All UV maps removed |
| `iops.object_clean_uvmap_1` | Remove UVMap 1 | 1 | Keeps UV map 1; removes 2..8 |
| `iops.object_clean_uvmap_2` | Remove UVMap 2 | 2 | Keeps 1..2; removes 3..8 |
| `iops.object_clean_uvmap_3` | Remove UVMap 3 | 3 | Keeps 1..3; removes 4..8 |
| `iops.object_clean_uvmap_4` | Remove UVMap 4 | 4 | Keeps 1..4; removes 5..8 |
| `iops.object_clean_uvmap_5` | Remove UVMap 5 | 5 | Keeps 1..5; removes 6..8 |
| `iops.object_clean_uvmap_6` | Remove UVMap 6 | 6 | Keeps 1..6; removes 7..8 |
| `iops.object_clean_uvmap_7` | Remove UVMap 7 | 7 | Keeps 1..7; removes slot 8 |

<div class="iops-meta" markdown="1">
<span class="key">bl_idname: iops.object_clean_uvmap_0 .. iops.object_clean_uvmap_7</span>
<span class="mode">Mode: Object</span>
<span>Context: VIEW_3D</span>
<span class="modal">Modal: no</span>
<span class="hud">HUD: no</span>
</div>

All eight register `REGISTER` and `UNDO`, so the removal is undoable. There is no poll restriction — the operators check selection inside `execute`.

## Properties

None. Each operator's start index is hard-coded into its class.

## Notes

- Objects without polygons, hidden objects, or non-mesh objects in the selection are filtered out before processing.
- If no eligible mesh is found, the operator reports `Select MESH objects.` as an error and returns `FINISHED` without changing data.
- Removal is destructive to UV data but reversible via Undo.
- All viewports are tagged for redraw after a successful pass.
- Slot indexing is zero-based internally (the labels say "UVMap 1..7" but the source removes from index N onward). Labels and report strings still use 1-based human counting.

## Related

- [Visual UV](op_mesh_visual_uv.md)
- [UV Channel Hop](op_mesh_uv_channel_hop.md)
- [UV Shortest Mark](op_mesh_uv_shortest_mark.md)
