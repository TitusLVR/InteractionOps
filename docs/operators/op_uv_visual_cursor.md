# Visual Cursor UV

Interactive modal for the UV/Image Editor that places the 2D cursor on a snap point of a bounding-box cage — the UV-editor counterpart of the 3D Visual Origin tool. Draws a 9-point cage (4 corners + 4 edge midpoints + center) over the selected UVs, highlights the point nearest the mouse, and on confirm sets `space.cursor_location` (which doubles as the UV transform pivot) to that point.

<div class="iops-meta" markdown="1">
<span class="key">bl_idname: iops.uv_visual_cursor</span>
<span class="mode">Mode: Edit Mesh</span>
<span>Context: IMAGE_EDITOR</span>
<span class="modal">Modal: yes</span>
<span class="hud">HUD: yes</span>
</div>

## Overview
On invoke the operator computes the bounding box of the currently selected UV verts on the active mesh and builds 9 snap points from it. Each tick the points are re-projected to region space to find the one nearest the mouse, which is highlighted. Confirming writes that point to the 2D cursor.

Holding <kbd>Alt</kbd> switches to **tile mode**: the cage ignores the selection and snaps to the unit UDIM tile (`floor(u),floor(v)`..`+1,+1`) under the mouse, following the mouse across tiles. If nothing is selected when the tool starts, it begins in tile mode automatically.

## Usage
- Active object must be a mesh in Edit Mode, and the active area must be the UV/Image Editor.
- Default keymap: `Ctrl+Alt+Shift+F19` placeholder (rebind in addon preferences before using). Note: on installs with previously saved user hotkeys, the new default binding only appears after re-saving user hotkeys (which merges new defaults) or loading default hotkeys; until then, invoke via the operator search.
- Flow: hover to highlight the nearest cage point, <kbd>LMB</kbd>/<kbd>Space</kbd> to set the 2D cursor there. Hold <kbd>Alt</kbd> to snap against the hovered UDIM tile instead of the selection.

## Modal Controls
| Key | Action |
| --- | --- |
| <kbd>MouseMove</kbd> | Update highlighted cage point (and, in tile mode, the hovered tile) |
| <kbd>LMB</kbd> / <kbd>Space</kbd> | Set the 2D cursor to the highlighted point and finish |
| <kbd>Alt</kbd> (hold) | Tile mode: cage snaps to the unit UDIM tile under the mouse |
| <kbd>H</kbd> | Toggle help / HUD overlay |
| <kbd>MMB</kbd> / <kbd>WheelUp</kbd> / <kbd>WheelDown</kbd> | Pass through (pan / zoom) |
| <kbd>RMB</kbd> / <kbd>Esc</kbd> | Cancel |

## HUD
Overlay rendered in the Image Editor:
- The bounding-box cage via `Role.BBOX` and its 9 snap points via `Role.POINT`.
- The highlighted (nearest) point via `Role.CLOSEST_POINT`.
- HUD title "Visual Cursor UV" plus a help section listing the modal shortcuts. Supports the standard drag-to-reposition and parameter-toggle interactions provided by `HUDOverlay` / `HelpOverlay`, driven by the addon's theme preferences.

## Notes
- Scope is the active mesh only; multi-object UV edit is not aggregated.
- Confirm only moves the 2D cursor — it does not move the UV selection (see [Drag Snap UV](op_drag_snap_uv.md) for selection moves).
- The 2D cursor value is not clamped to 0..1; tiles outside the unit square are valid targets.

## Related
- [Drag Snap UV](op_drag_snap_uv.md)
- [Visual Origin (3D)](op_object_visual_origin.md)
