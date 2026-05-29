# Replace

Replaces selected target objects with copies of the active object, inheriting each target's world position (and optionally rotation/scale). Useful for swapping placeholders, scattering an asset across pre-positioned dummies, or instancing a master asset over an existing layout without re-aligning everything by hand.

<div class="iops-meta" markdown="1">
<span class="key">bl_idname: iops.object_replace</span>
<span class="mode">Mode: Object</span>
<span>Context: VIEW_3D</span>
<span class="modal">Modal: no</span>
<span class="hud">HUD: no</span>
</div>

## Overview

The active object is treated as the Source; all other selected objects are Targets. For each target, a copy of the source is created at the target's world location. By default the target's rotation and scale are preserved and the original target is deleted (Replace mode). Add mode keeps the targets intact and only places source copies on top of them.

Group mode treats the source as a hierarchy: either a parent Empty with children, or any object whose parent chain leads to such an Empty. The whole group (root Empty plus all descendants) is duplicated at each target, with parent relationships rebuilt locally.

Placement matrices are stored on the operator after execution, so tweaking properties in the F6 redo panel re-applies the change at the same positions instead of needing the original selection.

## Usage

- Object Mode. Select one or more Target objects, then Shift-click the Source (so it becomes Active).
- Invoke via menu / search / Pie — no default keymap binding.
- Adjust mode and transform options in the redo panel; placement is preserved when re-executing from history with only the result selected.

## Properties

| Name | Type | Default | Description |
| --- | --- | --- | --- |
| `mode` | Enum | `REPLACE` | `ADD` places source copies at each target without removing targets. `REPLACE` places copies and deletes the targets (and, in group mode, their descendants). |
| `select_replaced` | Bool | `True` | Select the newly created objects after the operation; the last new root becomes active. When off, the previous selection is left untouched. |
| `keep_rotation` | Bool | `False` | Use the source's world rotation. When off, the target's rotation is kept. |
| `keep_scale` | Bool | `False` | Use the source's world scale. When off, the target's scale is kept. |
| `keep_source_collection` | Bool | `True` | When the fallback "Object Replace" collection would otherwise be created, this keeps source copies in the source's own collection instead. Only matters when `keep_target_collection` is off. |
| `keep_target_collection` | Bool | `True` | Link each new copy into the corresponding target's collection. When off, copies go into the source collection (if `keep_source_collection`) or into a newly created `Object Replace` collection. Overrides `keep_source_collection` for placement decisions. |
| `use_groups` | Bool | `False` | Treat the source as a group rooted at the nearest parent Empty (walking up to the top group Empty). Each target receives a full duplicate of that hierarchy. Fails if no group root can be resolved from the source. |
| `use_linked_data` | Bool | `False` | Create linked (instanced) copies that share mesh data with the source. When off, mesh data is duplicated per copy (library-linked data is always shared). |

## Notes

- Source = active object; Targets = remaining selected objects. With nothing selected besides the source, the operator reports an error unless stored matrices from a previous run are available.
- Stored matrices are kept in an internal `HIDDEN` / `SKIP_SAVE` string property and are only consulted when re-executing with no targets selected (typical redo-panel case).
- In Replace mode with `use_groups`, source-group members are filtered out of the removal list to avoid deleting freshly duplicated content when redoing from the panel.
- Removal order is sorted leaves-first (descendants before parents) to keep `bpy.data.objects.remove` consistent.
- Target's parent hierarchy is preserved when the target's parent is not itself one of the targets: the new copy is reparented and `matrix_parent_inverse` is propagated, then `matrix_world` is reasserted.
- Non-mesh source objects (curves, empties, etc.) are duplicated as-is; the per-copy data duplication only triggers for local mesh data.

## Related

- [Drag Snap](op_drag_snap.md)
- [Three Point Rotation](op_object_three_point_rotation.md)
- [Align to Active](op_object_aligner.md)
