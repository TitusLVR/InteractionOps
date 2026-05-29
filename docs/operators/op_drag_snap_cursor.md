# Drag Snap Cursor

Modal point-to-point translation driven by the 3D Cursor. Press Q three times to snap the cursor onto a source vertex (A), then onto a target vertex (B); the operator then translates the active selection by the B-A vector. Useful when you need a precise vertex-to-vertex move on objects without entering Edit Mode.

<div class="iops-meta" markdown="1">
<span class="key">bl_idname: iops.object_drag_snap_cursor</span>
<span class="mode">Mode: Object</span>
<span>Context: VIEW_3D</span>
<span class="modal">Modal: yes</span>
<span class="hud">HUD: yes</span>
</div>

## Overview
The operator drives Blender's `transform.translate` with `cursor_transform=True` and vertex snapping (`snap_target="CLOSEST"`, `snap_elements={"VERTEX"}`, `use_snap_nonedit=True`), so each Q press starts an interactive cursor drag that snaps to the nearest vertex under the mouse. After two snaps it stores both cursor positions in `scene.IOPS.dragsnap_point_a` / `dragsnap_point_b` and applies the resulting global translation to the current object selection.

Prefer this over a manual `G` move when you need exact vertex alignment between two objects without toggling Edit Mode or repositioning origins.

## Usage
- Object Mode in a 3D Viewport with at least one selected object.
- Default keymap: <kbd>Ctrl</kbd>+<kbd>Alt</kbd>+<kbd>Shift</kbd>+<kbd>F19</kbd> (placeholder binding; rebind in preferences).
- Sequence:
  1. Invoke the operator. Status bar: "Step 1: Q to place cursor at point A".
  2. Press <kbd>Q</kbd>, drag, release on vertex A (snap to closest vertex).
  3. Press <kbd>Q</kbd> again to confirm and store A. Status bar: "Step 3: press Q".
  4. Press <kbd>Q</kbd>, drag, release on vertex B; the selection is translated by B - A and the operator finishes.

## Modal Controls
| Key | Action |
| --- | --- |
| <kbd>Q</kbd> | Run cursor-drag translate; advances the A/B/finish state machine |
| <kbd>MMB</kbd> / <kbd>WheelUp</kbd> / <kbd>WheelDown</kbd> | Pass through (orbit / zoom) |
| <kbd>Esc</kbd> / <kbd>RMB</kbd> | Cancel |
| <kbd>H</kbd> | Toggle help overlay (handled by HUD layer) |
| <kbd>LMB</kbd> drag on HUD | Reposition HUD / Help panels |

Note: the HUD help panel lists "LMB" as the snap target, but the actual snap is performed by the nested `transform.translate` modal that <kbd>Q</kbd> invokes; LMB release inside that nested modal confirms the snap because of `release_confirm=True`.

## HUD
- Title strip "Drag Snap (Cursor)".
- Help overlay (toggle <kbd>H</kbd>) lists: Place point (Q), Snap target (LMB), Cancel (Esc), Help / Toggle HUD (H).
- HUD and Help panels are draggable; positions and visibility are persisted by the HUD layer.
- Colours follow the `iops_theme` preferences block; see HUD theme keys for HUD background / text roles.

## Notes
- Only one class is registered: `IOPS_OT_DragSnapCursor`.
- Uses `scene.IOPS.dragsnap_point_a` and `scene.IOPS.dragsnap_point_b` (defined on the IOPS scene PropertyGroup) as scratch storage between Q presses.
- Cancelling after step 2 leaves the 3D Cursor at the last snapped position; no undo step is pushed for cursor movement itself.
- `poll` requires `VIEW_3D` + `OBJECT` mode + non-empty selection. Curve / mesh edit modes are not supported.
- The operator does not expose any `bl_props`; behaviour is fully modal.

## Related
- [Drag Snap](op_drag_snap.md)
- [UV Drag Snap](op_drag_snap_uv.md)
- [Cursor Rotate](op_cursor_rotate.md)
