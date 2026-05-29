# UVMaps Add/Remove

Batch UV layer management across multiple selected mesh objects. Adds a fresh UV map to every selected mesh, removes a UV map by the active object's active UV name across the selection, or syncs the active UV index across the selection to match the active object's active UV index.

<div class="iops-meta" markdown="1">
<span class="key">bl_idname: iops.uv_add_uvmap</span>
<span class="mode">Mode: Object</span>
<span>Context: VIEW_3D</span>
<span class="modal">Modal: no</span>
<span class="hud">HUD: no</span>
</div>

<div class="iops-meta" markdown="1">
<span class="key">bl_idname: iops.uv_remove_uvmap_by_active_name</span>
<span class="mode">Mode: Object</span>
<span>Context: VIEW_3D</span>
<span class="modal">Modal: no</span>
<span class="hud">HUD: no</span>
</div>

<div class="iops-meta" markdown="1">
<span class="key">bl_idname: iops.uv_active_uvmap_by_active_object</span>
<span class="mode">Mode: Object</span>
<span>Context: VIEW_3D</span>
<span class="modal">Modal: no</span>
<span class="hud">HUD: no</span>
</div>

## Overview
Blender's UV layer list lives on each mesh and is not selection-aware: adding, removing, or activating a UV map only touches the active object. This module exposes three small operators that fan the same action out across every selected mesh, which is the common case when prepping batches of assets for an unwrap, a lightmap channel, or a baking pass.

The remove and "set active by active" operators key off the active object's active UV layer name / index, so the active object acts as the reference and the rest of the selection is brought in line.

## Usage
- Object Mode, VIEW_3D. Select one or more mesh objects. For remove and set-active variants, the active object must be part of the selection and must have UV layers.
- Only meshes that are visible (`obj.visible_get()`) and have at least one polygon are processed.
- For `iops.uv_add_uvmap`, linked-data instances are deduplicated: only one object per unique mesh datablock is processed, so a UV map is not added twice to the same mesh.
- No default keymap binding for any of the three operators. Invoke via search (F3) or wire them into a pie/menu manually.

## Add UVMap (bl_idname: iops.uv_add_uvmap)

Adds a new UV layer to every selected, visible mesh with at least one polygon. The new layer is named `ch<N+1>` where N is the current UV layer count on that mesh, and is created with `do_init=True` so the new layer is initialised from existing geometry. Linked duplicates of the same mesh datablock are processed only once.

Reports `UVMaps Were Added` on success, or `Select MESH objects.` if the filter yields nothing.

## Remove UVMap by Active Name (bl_idname: iops.uv_remove_uvmap_by_active_name)

Reads the active UV layer name from the active object, then removes a UV layer of that exact name from every selected, visible mesh that has UV layers. Meshes that do not have a UV layer with that name are left untouched.

Reports `UVMap <name> Was Deleted` on success, or `Select MESH objects.` if the active object is not in the selection or the filter yields nothing.

## Set Active UVMap by Active Object (bl_idname: iops.uv_active_uvmap_by_active_object)

Reads the active UV layer index from the active object and sets `active_index` to that value on every selected, visible mesh that has at least that many UV layers. Meshes with fewer UV layers are skipped silently.

Note: the operator matches by index, not by name. If the active object's active UV is at index 1, every selected mesh that has at least two UV layers will have its active UV set to whatever sits at index 1 — regardless of name.

Reports `UVMap <name> Active` on success, or `Select MESH objects.` otherwise.

## Notes
- All three operators are `REGISTER | UNDO`. They are not modal and draw no HUD.
- Selection filter is consistent across all three: `type == 'MESH'`, has polygons, and `visible_get()` is true.
- Only the add operator deduplicates linked instances. The remove and set-active variants iterate the raw selection, which is harmless because both target named/indexed UV layers on the mesh datablock.
- A 3D viewport tag-redraw is issued after each per-object remove / set-active step so the Properties editor UV list updates immediately.

## Related
- [UVMaps Cleaner](op_object_uvmaps_cleaner.md)
