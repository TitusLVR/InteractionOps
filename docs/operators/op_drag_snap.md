# Drag Snap

Modal point-to-point snap for the active object in Object Mode. Pick a source vertex under the cursor, then pick a target vertex on any mesh under the cursor; the active object (and the rest of the selection) is translated globally by the resulting delta. With Ctrl on the second click the distance is copied to the clipboard instead of moving anything.

<div class="iops-meta" markdown="1">
<span class="key">bl_idname: iops.object_drag_snap</span>
<span class="mode">Mode: Object</span>
<span>Context: VIEW_3D</span>
<span class="modal">Modal: yes</span>
<span class="hud">HUD: yes</span>
</div>

## Overview
The operator raycasts under the mouse, then within the hit mesh finds the nearest vertex in screen space (within `SNAP_THRESHOLD_PX`). The first LMB click stores that vertex as the source, the second click stores the target and runs `bpy.ops.transform.translate` with the `target - source` delta in `GLOBAL` orientation. If source and target end up equal, the 3D cursor is moved to that point instead.

Use it for fast align-by-vertex operations between objects where Blender's built-in snap-during-transform is more clicks than necessary. It does not enter Edit Mode and does not modify mesh data.

## Usage
- Requires `VIEW_3D`, Object Mode, at least one selected object.
- Default keymap: <kbd>Ctrl</kbd>+<kbd>Alt</kbd>+<kbd>Shift</kbd>+<kbd>S</kbd>.
- Move the cursor over a mesh; the candidate vertex is highlighted as a point.
- LMB to lock the source point.
- Move to the target vertex on any mesh, then LMB to translate the active selection, or <kbd>Ctrl</kbd>+LMB to copy the source-to-target distance into the system clipboard.
- RMB or Esc cancels.

## Modal Controls
| Key | Action |
| --- | --- |
| <kbd>MouseMove</kbd> | Update nearest-vertex preview; once source is set, also update target preview |
| <kbd>LMB</kbd> (press, no source) | Set source vertex |
| <kbd>LMB</kbd> (press, source set) | Set target and translate the selection (finish) |
| <kbd>Ctrl</kbd>+<kbd>LMB</kbd> (source set) | Copy `length(target - source)` to the clipboard as a string, then finish |
| <kbd>LMB</kbd> (release, no source under cursor) | Cancel with "WRONG SOURCE OR TARGET" warning |
| <kbd>LMB</kbd> (release, source set, no target) | Re-arm: replace source with the current nearest vertex, prompt for target |
| <kbd>MMB</kbd> / <kbd>WheelUp</kbd> / <kbd>WheelDown</kbd> | Pass through (viewport navigation) |
| <kbd>RMB</kbd> / <kbd>Esc</kbd> | Cancel |
| <kbd>H</kbd> | Toggle help / HUD (handled by the shared HUD overlay) |
| Drag on HUD / Help panel | Reposition the overlay (handled by the shared HUD overlay) |

## HUD
On-screen overlay shows:
- Title `Drag Snap`.
- Help section listing: pick source / snap target (LMB), copy distance (Ctrl+LMB), cancel (Esc / RMB), help toggle (H).
- A preview line between source and current candidate target, plus point markers at both. Both use viewport draw roles: `Role.PREVIEW_LINE` for the line and `Role.ACTIVE_POINT` for the markers. Colours come from the addon theme.

## Notes
- The translate call is a real `transform.translate` operator invocation, so undo behaves as a single transform step.
- When the resolved target equals the source, the operator moves `scene.cursor.location` instead of running translate.
- Snapping always picks the closest mesh vertex under the mouse via raycast plus screen-space nearest-vertex search; edges, faces, grid, and non-mesh objects are not snap targets despite legacy doc text.
- Ctrl+LMB writes `str(distance)` (a raw Python float) into `WindowManager.clipboard`.
- The operator only registers `IOPS_OT_DragSnap`; no panels or property groups are added by this file.

## Related
- [Drag Snap Cursor](op_drag_snap_cursor.md)
- [Drag Snap UV](op_drag_snap_uv.md)
- [Mesh To Grid](op_mesh_to_grid.md)
