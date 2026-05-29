# Materials from Textures

Batch-creates Blender materials from texture files picked in the File Browser. For each selected image, the operator builds a node-based material wired to Principled BSDF, optionally pulling sibling textures from the same directory and connecting normal and mask maps by suffix.

<div class="iops-meta" markdown="1">
<span class="key">bl_idname: iops.materials_from_textures</span>
<span class="mode">Mode: any</span>
<span>Context: VIEW_3D (invoked from the IOPS Pie); opens a File Browser</span>
<span class="modal">Modal: no</span>
<span class="hud">HUD: no</span>
</div>

## Overview

The operator extends `ImportHelper`, so invoking it pops a File Browser. The user multi-selects diffuse/base-color images; each selected file becomes one new material. A material name is derived from the filename by stripping the extension and any prefix/suffix tokens defined in the addon preferences (`texture_to_material_prefixes`, `texture_to_material_suffixes`).

When `Import all textures` is enabled, the directory is scanned for other files whose names contain the derived material name. Files ending in `_nm` are wired through a Normal Map node into the BSDF Normal input. Files ending in `_mk` are routed through a Separate RGB: R goes to Metallic, G to Roughness. Any other matching sibling is loaded as an unconnected `ShaderNodeTexImage` placed to the right of the BSDF.

All created materials and loaded images get `use_fake_user = True` so they survive a save/reload even without an assignment.

## Usage

- No selection required; runs in any context.
- Invoke from the IOPS Pie ("Materials from Textures") or via operator search. No default keymap binding.
- In the File Browser, select one or more base-color images and confirm. Toggle `Import all textures` in the right panel to control sibling import.

## Properties

| Name | Type | Default | Description |
| --- | --- | --- | --- |
| `files` | CollectionProperty (PropertyGroup) | empty | File Browser multi-selection, populated by `ImportHelper`. |
| `import_all` | BoolProperty | `True` | When on, scans the source directory and links sibling textures whose filename contains the derived material name. |

The operator reads two addon preferences (defined on the addon's `AddonPreferences`):

| Preference | Default | Purpose |
| --- | --- | --- |
| `texture_to_material_prefixes` | `env_` | Comma-separated prefixes stripped from the filename when building the material name. |
| `texture_to_material_suffixes` | `_df,_dfa,_mk,_emk,_nm` | Comma-separated suffixes stripped from the filename when building the material name. |

## Notes

- Material naming: the filename is truncated at the first `.` (so `name.001.png` collapses to `name`), then each configured prefix/suffix is removed once. Blender will auto-suffix `.001`, `.002` on name collisions.
- Sibling detection is a substring match (`mat_name in file`) against the full filename, then `_nm` / `_mk` are matched against the constructed `<mat_name>_nm` / `<mat_name>_mk` strings. Files with non-PBR suffixes are imported but left unlinked.
- Normal and mask images are forced to `Non-Color` colorspace; the base color image keeps the loaded default.
- No undo grouping is set; each created material/image/node is a separate datablock and undo will roll back the whole batch in one step only if Blender groups it.
- The operator does not check whether a file is a valid image - `bpy.data.images.load` will accept any path and may produce broken image datablocks.
- A `print("DIRNAME", ...)` debug line still fires to the console on every run.

## Related

- [Cleanup Materials](op_materials_from_textures.md)
- Convert Image Path
- [Reload Textures](op_image_reload.md)
