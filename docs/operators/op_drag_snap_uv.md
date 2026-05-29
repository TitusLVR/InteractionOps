# Drag Snap UV

Interactive modal for the UV/Image Editor that picks a source UV under the mouse, then snaps the current UV selection to a target UV (or moves the 2D cursor) using a KD-tree of all UVs. It removes the multi-step "place cursor, snap selection to cursor" dance for aligning UV vertices to other UVs.

<div class="iops-meta" markdown="1">
<span class="key">bl_idname: iops.uv_drag_snap_uv</span>
<span class="mode">Mode: Edit Mesh</span>
<span>Context: IMAGE_EDITOR</span>
<span class="modal">Modal: yes</span>
<span class="hud">HUD: yes</span>
</div>

## Overview
Builds two KD-trees on invoke: one over all UVs of the active mesh (with the 2D cursor included as a snap target), and one over only the selected UVs. The modal continuously finds the nearest UV to the cursor and uses it either as the source for a drag or, after a source is locked in, as the snap target driving a `transform.translate`.

Use it instead of Blender's snap-selected-to-cursor / cursor-to-selected chain when you need to align arbitrary UV vertices to other UV vertices visually.

## Usage
- Active object must be a mesh in Edit Mode, and the active area must be the UV/Image Editor.
- Default keymap: <kbd>Ctrl</kbd>+<kbd>Alt</kbd>+<kbd>G</kbd> in the Image Editor.
- Flow: hover over a UV to highlight it, <kbd>LMB</kbd> to lock it as source, hover the target UV, <kbd>LMB</kbd> again to snap the selection from source to target. Axis constraints (<kbd>X</kbd>/<kbd>Y</kbd>) and cursor-based shortcuts (<kbd>1</kbd>/<kbd>2</kbd>/<kbd>4</kbd>) are also available.

## Modal Controls
| Key | Action |
| --- | --- |
| <kbd>MouseMove</kbd> | Update nearest UV under cursor (preview / target) |
| <kbd>LMB</kbd> press | First click: lock highlighted UV as source. Second click: set target to highlighted UV and translate selection |
| <kbd>Ctrl</kbd>+<kbd>LMB</kbd> | After source is set: copy current source-to-target distance (vector length) to clipboard and finish |
| <kbd>LMB</kbd> release | Confirm if both source and target exist; if only source is set, prompt to click target |
| <kbd>1</kbd> | Move selection so highlighted UV lands on the 2D cursor (source = highlighted, target = cursor) |
| <kbd>2</kbd> | Move selection so the UV nearest the mouse, among selected UVs, lands on the 2D cursor |
| <kbd>4</kbd> | Move the 2D cursor to the currently highlighted UV |
| <kbd>X</kbd> | Constrain translation to X (requires source and target locked) |
| <kbd>Y</kbd> | Constrain translation to Y (requires source and target locked) |
| <kbd>H</kbd> | Toggle help / HUD overlay |
| <kbd>MMB</kbd> / <kbd>WheelUp</kbd> / <kbd>WheelDown</kbd> | Pass through (pan / zoom) |
| <kbd>RMB</kbd> / <kbd>Esc</kbd> | Cancel |

## HUD
Overlay rendered in the Image Editor:
- Two on-canvas markers via `Role.ACTIVE_POINT`: the source UV (once picked) and the current preview/target UV.
- A connecting segment between source and preview using `Role.PREVIEW_LINE`.
- HUD title "Drag Snap UV" plus a help section listing all modal shortcuts. The HUD supports the standard drag-to-reposition and parameter-toggle interactions provided by `HUDOverlay` / `HelpOverlay`, driven by the addon's theme preferences.

## Notes
- Source picking uses the UV under the mouse at the moment <kbd>LMB</kbd> is pressed; the KD-tree includes the 2D cursor location, so the cursor itself can be picked as source/target.
- The "move closest to cursor" (<kbd>2</kbd>) shortcut queries the selected-only KD-tree; if no UV is selected it reports a warning.
- The actual move is performed by `bpy.ops.transform.translate` with `orient_type="GLOBAL"`, so the action is captured in Blender's undo stack as a translate step.
- Axis constraint (<kbd>X</kbd>/<kbd>Y</kbd>) is only meaningful after both source and target are set; pressing it earlier reports "Nothing to move" and ends the modal.
- Cancelling with <kbd>Esc</kbd>/<kbd>RMB</kbd> removes draw handlers but does not undo any translate already applied this session.

## Related
- [Drag Snap](op_drag_snap.md)
- [Drag Snap Cursor](op_drag_snap_cursor.md)
