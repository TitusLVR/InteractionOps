# Executor

Browses a configured folder of standalone Python scripts and runs the chosen one via `exec()`. A side panel lists every `.py` file in the executor scripts folder, grouped alphabetically by first letter, with a live text filter. Pick a script and it executes in the current Blender context.

<div class="iops-meta" markdown="1">
<span class="key">bl_idname: iops.scripts_call_mt_executor</span>
<span class="mode">Mode: any</span>
<span>Context: VIEW_3D</span>
<span class="modal">Modal: no</span>
<span class="hud">HUD: no</span>
</div>

<div class="iops-meta" markdown="1">
<span class="key">bl_idname: iops.executor</span>
<span class="mode">Mode: any</span>
<span>Context: any</span>
<span class="modal">Modal: no</span>
<span class="hud">HUD: no</span>
</div>

## Overview
The Executor is a lightweight script launcher. Drop arbitrary `.py` files into the folder set in the addon preferences (`executor_scripts_folder`) and call the picker to run them on demand. There is no project structure, no manifest, no registration — each file is read and `exec()`-compiled at invocation time.

It is useful for one-off macros, scene-cleanup helpers, and debug snippets that do not warrant becoming proper operators. Compared to Blender's built-in Text Editor flow, it skips the editor entirely: scripts live on disk and are surfaced through a popup panel.

## Usage
- Set the scripts folder in InteractionOps preferences (`executor_scripts_folder`). Only files ending in `.py` directly inside that folder are picked up (no recursion).
- Invoke the picker: default keymap <kbd>Ctrl</kbd>+<kbd>Alt</kbd>+<kbd>X</kbd> in the 3D View calls `iops.scripts_call_mt_executor`, which rescans the folder and pops up the `IOPS_PT_ExecuteList` panel.
- Type into the filter field (magnifier icon) to narrow the list; click a script name to run it.
- `iops.executor` itself takes a single `script` string property (full path) and is what each list button invokes — it has no default keymap binding and is not meant to be hit directly.

## Properties

### iops.executor

| Name | Type | Default | Description |
| --- | --- | --- | --- |
| `script` | StringProperty | `""` | Absolute path of the `.py` file to compile and execute. |

`iops.scripts_call_mt_executor` exposes no properties.

## Notes
- Scripts run via `exec(compile(open(filename).read(), filename, "exec"))`. No sandboxing, no argument passing, no return value handling — they have full access to `bpy` and the current context.
- The picker clears `iops_exec_filter` and rebuilds `scene.IOPS.executor_scripts` on every call, so adding a new file to the folder shows up the next time the panel is opened.
- Filtering relies on `scene.IOPS.filtered_executor_scripts` being populated by the filter property's update callback (defined elsewhere); when the filter field is empty the full list is shown.
- Column count is derived from `prefs.executor_column_count` and column width from `prefs.executor_name_length` plus the longest script name.
- Companion classes registered in this module: `IOPS_PT_ExecuteList` (the popup panel that draws the script grid) and `IOPS_OT_Executor` (the per-button runner).
- If `scene.IOPS` is missing (addon scene props not registered yet), the panel draws a placeholder label and the call operator returns `CANCELLED`.

## Related
- [Run Text](op_run_text.md)
- [Function Keys](op_modes.md)
