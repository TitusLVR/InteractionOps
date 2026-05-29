# Library Reload

Reloads every linked library in the current `.blend` file in a single pass. Iterates `bpy.data.libraries`, resolves each library's absolute filepath, calls `library.reload()` when the file exists, and reports per-library results to the info area. Saves the trip through Blender's Outliner / File menu when a scene has many linked assets.

<div class="iops-meta" markdown="1">
<span class="key">bl_idname: iops.reload_libraries</span>
<span class="mode">Mode: any</span>
<span>Context: any</span>
<span class="modal">Modal: no</span>
<span class="hud">HUD: no</span>
</div>

## Overview
When you work with linked assets and the source `.blend` files change on disk, Blender does not pick the updates up until each library is reloaded. The built-in workflow requires expanding the Outliner's Blender File view and reloading libraries one by one. This operator does the same job for the whole `bpy.data.libraries` collection in one click and emits per-library status so missing or broken links are visible without digging through the Outliner.

## Usage
- Poll requires at least one entry in `bpy.data.libraries` (the operator is disabled in files with no linked libraries).
- No default keymap binding. Invoke via F3 search ("Reload Libraries") or wire it into a menu / pie.
- For every library:
  - If `filepath` is empty or the resolved absolute path does not exist on disk, the library is skipped and a `WARNING` is reported.
  - Otherwise `library.reload()` is called. Success is reported as `INFO`; a `RuntimeError` from Blender is reported as `WARNING` and the loop continues.

## Notes
- The operator never aborts mid-loop; one bad library does not stop the others from reloading.
- Paths are resolved with `bpy.path.abspath`, so libraries using `//` relative paths are handled relative to the current `.blend`.
- No properties, no modal, no HUD; this is a plain `execute()` operator returning `{'FINISHED'}`.
- Only `IOPS_OT_Reload_Libraries` is registered from this module.

## Related
- Material & Texture group operators in `docs/operators/`.
