# UV Channel Hop

Cycles the active UV channel on the active mesh in Edit Mode. Optionally promotes the new active channel to the render channel and rebuilds seams from UV islands so the seam display follows the channel you are looking at.

<div class="iops-meta" markdown="1">
<span class="key">bl_idname: iops.mesh_uv_channel_hop</span>
<span class="mode">Mode: Edit Mesh</span>
<span>Context: VIEW_3D</span>
<span class="modal">Modal: no</span>
<span class="hud">HUD: no</span>
</div>

## Overview
Switching the active UV map in Blender normally takes a trip to the Object Data Properties panel. This operator advances `uv_layers.active_index` modulo the number of channels, so a single shortcut walks forward (or backward) through every UV map on the active mesh.

It also keeps two side effects in sync with the channel you just moved to: the render channel can be promoted automatically, and edge seams can be regenerated from the new active UV's islands so the seam overlay reflects the current layout instead of the previous one.

## Usage
- Active object must be a `MESH` in Edit Mode in a 3D Viewport.
- The mesh needs at least one UV layer for the hop to do anything meaningful.
- Default keymap: `Ctrl+Alt+Shift+F19` (placeholder binding from `hotkeys_default.py` — rebind in the addon preferences before using).
- Run repeatedly to cycle; toggle `Hop to Previous` in the redo (F6) panel to step backward instead.

## Properties
| Name | Type | Default | Description |
| --- | --- | --- | --- |
| `mark_seam` | Bool | `True` | After switching, clear existing seams and re-mark them from the new active UV's islands (`mesh.mark_seam` + `uv.seams_from_islands`). |
| `hop_previous` | Bool | `False` | Step to the previous channel instead of the next. |
| `set_render` | Bool | `True` | Set the new active UV layer as the render channel (`active_render = True`). |

## Notes
- The operator temporarily selects all faces to run the seam rebuild, then restores the original face selection from the bmesh snapshot taken at the start. Vertex / edge selection state is not separately preserved.
- `mark_seam=True` wipes all existing seams on the mesh and replaces them with seams derived from the new active UV's islands. If you author seams by hand, disable this property.
- Reports the resulting active UV channel and active render channel via `self.report({'INFO'}, ...)` — visible in the status bar / Info editor.
- Registered as `REGISTER | UNDO`, so a single Undo step reverts the channel change, seam edit, and render flag together.

## Related
- [Visual UV](op_mesh_visual_uv.md)
- [UV Shortest Mark](op_mesh_uv_shortest_mark.md)
