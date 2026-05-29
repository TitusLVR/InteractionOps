# Image Reload

Reloads every image data-block in the current .blend from its source file on disk. Useful after textures have been edited externally (Photoshop, Substance, etc.) so the viewport, shaders, and UV/Image editors pick up the new pixels without manually clicking Reload per image.

<div class="iops-meta" markdown="1">
<span class="key">bl_idname: iops.reload_images</span>
<span class="mode">Mode: Any</span>
<span>Context: Any</span>
<span class="modal">Modal: no</span>
<span class="hud">HUD: no</span>
</div>

## Overview
Blender's built-in Image > Reload only acts on one image at a time from the Image Editor. This operator iterates `bpy.data.images` and calls `image.reload()` on each, reporting a per-image INFO message. Use it after a batch external edit to refresh all textures in one shot.

## Usage
- Poll requires `bpy.data.images` to be non-empty (at least one image data-block present).
- No default keymap binding. Invoke via F3 search ("Reload Images") or wire it into a menu/pie of your choice.
- Each reloaded image emits an INFO report (`Image '<name>' reloaded.`) visible in the Info editor / status bar.

## Notes
- No filtering by selection, dirty state, or file existence — every image data-block is touched, including packed images and ones with missing source paths. Blender's own `Image.reload()` handles those internally.
- The operator does not declare `REGISTER`/`UNDO` in `bl_options`; reloads read from disk and are not undoable regardless.
- Despite the previous documentation claim, this operator does not walk material node trees or "validate paths" — it just calls `reload()` on every image.

## Related
- (no sibling operators in this module)
