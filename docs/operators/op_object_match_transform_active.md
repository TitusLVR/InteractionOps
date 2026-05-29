# Match Transform Active

Copies the active mesh object's `dimensions` onto every other selected object. It is a one-shot way to make a batch of objects share the bounding-box size of the active one without manually computing scale ratios.

<div class="iops-meta" markdown="1">
<span class="key">bl_idname: iops.object_match_transform_active</span>
<span class="mode">Mode: Object</span>
<span>Context: VIEW_3D</span>
<span class="modal">Modal: no</span>
<span class="hud">HUD: no</span>
</div>

## Overview
The operator iterates over `context.view_layer.objects.selected` and assigns `active.dimensions` to each object's `dimensions`. Because Blender's `Object.dimensions` setter rewrites object scale to match the requested world-space bounding-box size, this effectively matches each selected object's overall size to the active one, regardless of its original mesh extents.

Use it when you need several differently-shaped meshes to share the same bounding-box footprint (kit-bash blockouts, prop substitution, scale normalization passes).

## Usage
- Object Mode in the 3D Viewport.
- Selection must be non-empty, and the active object must be a `MESH`.
- No default keymap binding. Invoke via menu, F3 search, or a pie.
- Select the donor object last so it becomes active, then run the operator. Every other selected object will be resized to match.

## Notes
- Only `dimensions` is copied. Location and rotation are not touched; the name "Match Transform Active" is historical and the operator label in Blender is "Match dimensions".
- The active object is included in the iteration but assigning its own dimensions back to itself is a no-op.
- Selected non-mesh objects are still processed; `Object.dimensions` is valid on any object with geometry, but the result on lights/empties/etc. may be uninteresting. The poll only checks that the active is a mesh.
- Registered with `REGISTER` and `UNDO`; a single undo step rolls back all touched objects.
- Reports `INFO: "Dimensions matched"` on success.

## Related
- [Object Normalize](op_object_normalize.md)
- [Object To Grid From Active](op_grid_from_active.md)
- [Three Point Rotation](op_object_three_point_rotation.md)
