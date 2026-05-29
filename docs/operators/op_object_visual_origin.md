# Visual Origin

Modal helper for placing object origins onto visually meaningful points of a bounding cage. The operator builds a bounding-box cage (with subdivided midpoints) around the selection or the active object, snaps the scene cursor to the cage point closest to the mouse, and applies `object.origin_set(ORIGIN_CURSOR)` to every selected mesh. By default the previous cursor location and rotation are restored on confirm so it acts purely as an origin-placement tool.

<div class="iops-meta" markdown="1">
<span class="key">bl_idname: iops.object_visual_origin</span>
<span class="mode">Mode: Object</span>
<span>Context: VIEW_3D</span>
<span class="modal">Modal: yes</span>
<span class="hud">HUD: yes</span>
</div>

## Overview
Blender's built-in origin tools require you to first place the 3D cursor, then run Set Origin. Visual Origin folds that into one modal: the cage shows you the candidate snap points (corners, edge midpoints, face centers, body center), the closest cage point to the mouse is highlighted in real time, and confirming sets the origin there for the whole selection at once.

Three cage modes cover the common cases: a single cage spanning the whole selection (group), a cage in the active object's local space, or a cage in world axes for the active object. There is also a one-shot "send origin to world" and "send object to world" exit.

## Usage
- Object Mode, VIEW_3D, with a MESH active object and at least one selected object.
- No default keymap binding — invoke via menu / F3 search or bind manually.
- On invoke the cage is built from the active object's local bound box; move the mouse to highlight the nearest cage point; press LMB or Space to drop the origin.

## Modal Controls
| Key | Action |
| --- | --- |
| <kbd>MouseMove</kbd> | update closest cage point under the cursor |
| <kbd>F1</kbd> | rebuild cage from joined selection (world-space group cage) |
| <kbd>F2</kbd> | rebuild cage in the active object's local space |
| <kbd>F3</kbd> | rebuild cage in world space for the active object (transforms applied) |
| <kbd>Shift</kbd>+<kbd>LMB</kbd> | raycast under the mouse and re-pick the active cage object from the selection |
| <kbd>W</kbd> | snap origins of all selected to world center and finish |
| <kbd>M</kbd> | move all selected objects' `location` to world origin and finish |
| <kbd>I</kbd> | toggle Offset Instances (compensate linked-data duplicates) |
| <kbd>LMB</kbd> / <kbd>Space</kbd> | confirm — set origin to highlighted cage point |
| <kbd>Esc</kbd> / <kbd>RMB</kbd> | cancel |
| <kbd>MMB</kbd>, <kbd>WheelUp</kbd>, <kbd>WheelDown</kbd> | pass-through for viewport navigation |
| <kbd>H</kbd> | toggle help / HUD (handled by the HUD framework) |

## HUD
The HUD shows the operator title plus a Help overlay listing every modal action above. The state of the Offset Instances toggle is mirrored in the Help overlay (item `I`). Cage drawing uses three theme roles:

- `Role.LINE` — cage edges (depth ALWAYS, alpha blended).
- `Role.POINT` — all cage candidate points.
- `Role.CLOSEST_POINT` — the currently highlighted (closest to cursor) point.

## Properties
| Name | Type | Default | Description |
| --- | --- | --- | --- |
| `hold_cursor` | Bool | `True` | After confirming, restore the scene cursor's location and rotation to what they were on invoke. |
| `offset_instances` | Bool | `False` | When setting the origin, record world positions of objects sharing the same mesh data and shift their `location` back so linked duplicates do not jump. |

## Notes
- Cage construction for F1 and F3 temporarily duplicates and joins meshes, applies transforms, reads `bound_box`, then removes the temp. Heavy selections cost real time on each rebuild.
- Local View is exited (`view3d.localview(frame_selected=False)`) during F1/F3 cage builds.
- After confirm/cancel the operator runs an orphan purge over `bpy.data.meshes`, `materials`, `textures`, and `images` with zero users — this is global, not scoped to the operator's temps.
- `place_origin` and `origin_to_world` set the scene cursor and then call `bpy.ops.object.origin_set(type="ORIGIN_CURSOR")` per object; `hold_cursor=True` restores the cursor afterwards.
- The cage is reprojected to 2D every `calc_distance` call so viewport navigation during the modal does not desync the closest-point pick.
- The operator skips non-MESH objects when building the cage and when looking up linked instances, but still runs `origin_set` on the full selection.

## Related
- [Object Align Origin to Normal](op_align_origin_to_normal.md)
- [Object to Grid from Active](op_grid_from_active.md)
- [Object Drag Snap](op_drag_snap.md)
