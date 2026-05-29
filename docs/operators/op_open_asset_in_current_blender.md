# Open Asset in Current Blender

Opens the source `.blend` file that backs the active asset, linked object, or collection instance in the running Blender session via `wm.open_mainfile`. Resolves the path from the Asset Browser context, an object's library, its data's library, an `EMPTY` collection instance, or a locally marked asset.

<div class="iops-meta" markdown="1">
<span class="key">bl_idname: iops.open_asset_in_current_blender</span>
<span class="mode">Mode: any</span>
<span>Context: VIEW_3D / FILE_BROWSER (Asset Browser)</span>
<span class="modal">Modal: no</span>
<span class="hud">HUD: no</span>
</div>

## Overview
Jumps from an asset reference back to its authoring file without spawning a second Blender process. Useful when you want to edit the original asset source after spotting it in the Asset Browser, in a linked outliner entry, or as a collection instance dropped into the scene.

The path resolver checks, in order: the Asset Browser `context.asset`, the active object's `library`, the object data's `library`, an `EMPTY` of `instance_type == 'COLLECTION'` (collection library, then asset-marked collection in the current file), and finally an asset-marked active object in the current file. Files whose name ends in `.asset.blend` (Blender's asset-system managed files) are refused.

## Usage
- Hover the Asset Browser over an external (non-local) asset, or select an object/collection-instance whose source is a linked `.blend`, or select an object/collection marked as an asset in the saved current file.
- Invoke via menu or operator search (`F3`). No default keymap binding.
- The operator replaces the current session with the resolved `.blend` via `wm.open_mainfile` — unsaved changes will follow Blender's normal save prompt behaviour.

## Poll messages
The poll fails with one of these reasons (also reported on execute if state changes):

| Reason | Message |
| --- | --- |
| `browser_local` | Selected asset is contained in the current file |
| `missing_file` | Asset library file not found |
| `asset_blend_guard` | This file is managed by the asset system; manual edits should be avoided |
| `no_active` | No active object |
| `unsaved_blend` | Save the blend file to open it |
| `no_external_asset` | Not a linked asset, collection instance, or marked asset |

## Notes
- No properties; behaviour is fully driven by context.
- Files ending in `.asset.blend` are intentionally blocked to discourage hand-editing asset-system-managed bundles.
- For an asset marked in the current (unsaved) file, you must save first — the operator needs a real filepath to reopen.
- `wm.open_mainfile` is not undoable; this is a session swap, not an edit.

## Related
- [Open Asset in New Blender](op_open_asset_in_new_blender.md)
