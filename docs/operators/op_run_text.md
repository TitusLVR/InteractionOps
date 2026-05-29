# Run Text

Executes the script currently open in any Text Editor area without requiring focus or hover over that editor. The operator searches all open windows for a `TEXT_EDITOR` area, builds a context override targeting it, and invokes `bpy.ops.text.run_script()` against that context.

<div class="iops-meta" markdown="1">
<span class="key">bl_idname: iops.scripts_run_text</span>
<span class="mode">Mode: any</span>
<span>Context: any (driven by a visible TEXT_EDITOR area)</span>
<span class="modal">Modal: no</span>
<span class="hud">HUD: no</span>
</div>

## Overview
Blender's built-in `text.run_script` only runs when the Text Editor is the active context. This operator lets you trigger the active text from a global shortcut while the mouse is in the 3D View (or anywhere else), as long as a Text Editor area exists somewhere on screen. Useful for iterating on tool scripts without parking the cursor in the Text Editor every time.

## Usage
- Open the script you want to run in any Text Editor area in any open Blender window.
- Press the shortcut from any other editor; the script in the Text Editor will run.
- Default keymap: <kbd>Ctrl</kbd>+<kbd>Alt</kbd>+<kbd>Shift</kbd>+<kbd>F19</kbd>.

## Notes
- If no `TEXT_EDITOR` area is open anywhere, the operator raises an exception (`ERROR: TEXT_EDITOR not found!`) rather than reporting a soft error.
- When multiple Text Editor areas are open, the first one found while iterating windows/screens/areas is used.
- The override forwards `scene`, `edit_object`, `active_object`, and `selected_objects` from the current context, so scripts that inspect those see the originating viewport state.
- Registered with `REGISTER` and `UNDO` flags; the underlying `text.run_script` handles its own undo behaviour.

## Related
- [Call MT Executor](op_executor.md)
