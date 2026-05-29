# Instance Collection Append

Appends the source collection of a linked collection-instance asset into the current scene, preserving the instance's world transform. The workflow has two steps: scan the source .blend referenced by the selected instance for available collections, then append one or more of them in place of (or alongside) the instances.

## Scan Source Collections (bl_idname: iops.scan_source_collections)

<div class="iops-meta" markdown="1">
<span class="key">bl_idname: iops.scan_source_collections</span>
<span class="mode">Mode: Object</span>
<span>Context: VIEW_3D</span>
<span class="modal">Modal: no</span>
<span class="hud">HUD: no</span>
</div>

### Overview
Opens the source library referenced by the active object's `instance_collection` and lists every collection found inside. Results are written to `WindowManager.IOPS_AddonProperties.iops_source_collections` and shown via the `IOPS_UL_SourceCollectionsList` UIList. Run this before `iops.instance_collection_append` to pick which collections to bring in.

### Usage
- Active object must be a collection instance whose `instance_collection` comes from a linked library (`.library` is set).
- Object Mode, VIEW_3D.
- No default keymap binding — invoke via the addon panel that hosts the UIList, or via search.

### Notes
- Clears the existing source-collections list on every run.
- Fails with a warning if the active object is not a linked collection instance, or if the resolved library filepath does not exist on disk.
- Reports the count of collections discovered.

## Append Collection from Linked Asset (bl_idname: iops.instance_collection_append)

<div class="iops-meta" markdown="1">
<span class="key">bl_idname: iops.instance_collection_append</span>
<span class="mode">Mode: Object</span>
<span>Context: VIEW_3D</span>
<span class="modal">Modal: no</span>
<span class="hud">HUD: no</span>
</div>

### Overview
For every selected object that is a linked collection instance, appends the user-ticked collections from that instance's source .blend into the current scene and re-applies the instance's `matrix_world` to each object in the freshly appended collection (multiplied by each object's original `matrix_basis`). The result is real, editable geometry sitting where the instance used to sit.

Use this when you need to break a linked collection instance into local data without losing its placement, or when one source file should contribute multiple collections at the locations of multiple instances.

### Usage
1. Select one or more linked collection instances in Object Mode.
2. Run `iops.scan_source_collections` with the desired instance active to populate the picker.
3. Tick collections in the UIList.
4. Run this operator.
- No default keymap binding.

### Notes
- Selected objects that are not collection instances are silently counted as skipped.
- Selected instances whose `instance_collection` is local (not from a library) emit a warning and are skipped.
- Each picked collection is appended once per qualifying selected object — selecting N instances and ticking M collections triggers up to N x M appends. If a collection already exists in the scene with the same name, Blender's standard append-name-collision rules apply.
- A newly appended collection is linked into `context.scene.collection.children` only if a child with the same name is not already present.
- The transform applied to each appended object is `instance_object.matrix_world @ coll_obj.matrix_basis`.
- Marks `REGISTER` and `UNDO`.

## Select All Collections (bl_idname: iops.select_all_collections)

<div class="iops-meta" markdown="1">
<span class="key">bl_idname: iops.select_all_collections</span>
<span class="mode">Mode: any</span>
<span>Context: any</span>
<span class="modal">Modal: no</span>
<span class="hud">HUD: no</span>
</div>

Helper that mass-toggles the `is_selected` checkboxes in the source-collections list. No default keymap binding.

### Properties
| Name | Type | Default | Description |
| --- | --- | --- | --- |
| `action` | Enum | `TOGGLE` | `SELECT` ticks everything, `DESELECT` clears everything, `TOGGLE` clears all if any are ticked, otherwise ticks all. |

## Notes
- The file also registers `IOPS_UL_SourceCollectionsList`, a `UIList` used to render the discovered collections with a checkbox and `OUTLINER_COLLECTION` icon.
- The list of discovered collections lives on `WindowManager.IOPS_AddonProperties.iops_source_collections` (a `CollectionProperty` defined elsewhere with `name` and `is_selected` fields).

## Related
- (no sibling operators in this module)
