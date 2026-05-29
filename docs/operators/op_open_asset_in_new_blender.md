# Open Asset in New Blender

Launches a `.blend` file in a separate Blender process using the same executable that is currently running. The current session and its unsaved state are left untouched, which is useful for inspecting linked-library sources or asset-browser sources without disturbing the active scene.

<div class="iops-meta" markdown="1">
<span class="key">bl_idname: iops.open_asset_in_new_blender</span>
<span class="mode">Mode: any</span>
<span>Context: any</span>
<span class="modal">Modal: no</span>
<span class="hud">HUD: no</span>
</div>

## Overview
Asset Browser and linked-library workflows often need to jump from a referenced datablock back to its source `.blend`. Blender's built-in "Open" replaces the current session. This operator spawns a second Blender process pointed at the target file, so both the host scene and the source remain open side by side.

On Windows the child process is started with `DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP`, so closing the host Blender does not terminate the spawned instance.

## Usage
- Provide `blendpath` as an absolute path or a `//`-relative blend path; it is resolved with `bpy.path.abspath`.
- Invoke via menu, search (F3), or by calling the operator from another script/Pie (typical caller: Asset Browser context menus).
- No default keymap binding.

## Properties
| Name | Type | Default | Description |
| --- | --- | --- | --- |
| `blendpath` | StringProperty (FILE_PATH) | "" | Absolute or blend-relative path to the `.blend` file to open. |
| `library` | StringProperty | "" | Optional metadata field for the linked library name; not used by execution logic. |

## Notes
- Reports `ERROR` and returns `CANCELLED` if the resolved path is not an existing file, or if `bpy.app.binary_path` cannot be resolved.
- The child process is launched via `subprocess.Popen([bpy.app.binary_path, path])`. No command-line flags besides the file path are passed.
- On non-Windows platforms no special creation flags are used; the child inherits the standard process group.
- The operator registers only `REGISTER` (no `UNDO`); it makes no changes to the current blend file.

## Related
- (no sibling operators in this module)
