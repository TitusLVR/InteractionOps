# Name from Active

Renames selected objects based on the active object's name using a token-based pattern. Supports counter padding, distance-based ordering relative to the active object, prefix/suffix trimming, optional mesh-data renaming, and clipboard copy of the active name. When only one object is selected the operator collapses to a clipboard / mesh-data sync action.

<div class="iops-meta" markdown="1">
<span class="key">bl_idname: iops.object_name_from_active</span>
<span class="mode">Mode: Object</span>
<span>Context: VIEW_3D</span>
<span class="modal">Modal: no</span>
<span class="hud">HUD: no</span>
</div>

## Overview
Blender's built-in batch rename works on the literal active name and is order-agnostic. This operator builds a name from a pattern (`[N]`, `[C]`, `[T]`, `[COL]`) and assigns it across the selection in a defined order — by default, sorted by world-space distance from the active object — so that ordered sets like fence segments, lamp posts, or modular props get contiguous numbering relative to a chosen anchor.

The single-selection branch handles a different but common need: push the active name to the OS clipboard and optionally sync `.data.name` to the object name.

## Usage
- Required: Object Mode, one or more selected objects with a valid active object.
- No default keymap binding — invoke via menu, search, or a user-bound key.
- Multi-selection flow:
  1. Select the targets, then make the anchor object active last.
  2. Run the operator.
  3. Tweak `New Name`, `Pattern`, counter digits, trim, and toggles in the redo panel; the rename re-evaluates on each change.
- Single-selection flow: running with one object copies its name to the clipboard (if enabled) and optionally renames its mesh data.

## Properties

| Name | Type | Default | Description |
| --- | --- | --- | --- |
| `new_name` | String | `""` (filled from active on invoke) | Base name substituted for `[N]` in the pattern. |
| `active_name` | String | `""` (filled from active on invoke) | Read-only display of the active object name; also written back to the active object if edited. |
| `pattern` | String | `[N]_[C]` | Naming pattern. Tokens: `[N]` name, `[C]` counter, `[T]` object type (lowercased), `[COL]` collection name(s) via `get_object_col_names`. |
| `use_distance` | Bool | `True` | Sort selection by distance from the active object before numbering. |
| `counter_digits` | Int | `2` (min 2, max 10) | Zero-padding width for `[C]`. |
| `counter_shift` | Bool | `True` | Start counter at 1 instead of 0 (useful when the active object is renamed too). |
| `rename_active` | Bool | `True` | Include the active object in the rename pass. |
| `rename_mesh_data` | Bool | `True` | For each renamed mesh object, set `data.name` to the new object name. |
| `rename_mesh_data_single` | Bool | `False` | Single-selection variant of the above. |
| `trim_prefix` | Int | `0` (min 0, max 100) | Characters to strip from the start of the active name when building `new_name`. |
| `trim_suffix` | Int | `0` (min 0, max 100) | Characters to strip from the end. |
| `use_trim` | Bool | `False` | Enable prefix/suffix trim; when off, both trim counts reset to 0. |
| `rename_linked` | Bool | `False` | Also rename the active object's `children_recursive`. |
| `copy_to_clipboard` | Bool | `True` | Copy the active object's name to the window manager clipboard (used by the single-selection branch). |

## Notes
- The operator only enters the pattern path when more than one object is selected. With a single object, only `copy_to_clipboard` and `rename_mesh_data_single` matter.
- Order of rename is the iteration order of `context.selected_objects`, optionally pre-sorted by distance. Without `use_distance`, ordering follows Blender's selection list.
- `rename_active` controls whether the active object is included in the numbered set; combine with `counter_shift` to keep numbering aligned when the active is renamed too.
- `rename_linked` appends recursive children of the active object to the rename list after the main selection — they receive the next counter values, not values aligned with their parent.
- An empty `pattern` reports an error and renames nothing (in the multi-selection branch).
- Mesh-data renaming only acts on `MESH` objects; other types are left with their original data name.
- Registered in `REGISTER, UNDO`; redo panel exposes the full property set.

## Related
- [Object Rotate](op_object_rotate.md)
- [Object UVMaps Cleaner](op_object_uvmaps_cleaner.md)
