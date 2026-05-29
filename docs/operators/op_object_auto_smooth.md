# Auto Smooth

Applies Blender 4.x "Shade Auto Smooth" (the Smooth by Angle geometry-nodes modifier) to every selected mesh in one pass, with a user-specified angle. Before applying, any existing modifier whose name contains "Auto Smooth" or "Smooth by Angle" is removed so the stack does not accumulate duplicates. After application, the resulting modifier is unpinned and moved to the top of the stack on each mesh. A companion operator strips custom split normals.

## Add Auto Smooth (bl_idname: iops.object_auto_smooth)

<div class="iops-meta" markdown="1">
<span class="key">bl_idname: iops.object_auto_smooth</span>
<span class="mode">Mode: Object (also tolerates meshes currently in Edit Mode)</span>
<span>Context: VIEW_3D</span>
<span class="modal">Modal: no</span>
<span class="hud">HUD: no</span>
</div>

### Overview
Blender 4.x replaced the per-mesh `use_auto_smooth` flag with a Smooth by Angle geometry-nodes modifier. This operator restores a one-shot batch workflow: select any number of objects, run the operator, and every mesh ends up with exactly one Smooth by Angle modifier at the top of its stack, configured to the chosen angle. Useful for hard-surface batches where mixed objects accumulate stale auto-smooth modifiers over time.

### Usage
- Select one or more objects. The poll succeeds as long as at least one selected object is of type `MESH`; non-mesh objects are skipped.
- No default keymap binding. Invoke via menu / F3 search.
- If any selected mesh is currently in Edit Mode, the operator temporarily switches it to Object Mode, applies the change, then restores Edit Mode.

### Properties
| Name | Type | Default | Description |
| --- | --- | --- | --- |
| `angle` | Float (degrees) | `30.0` (min `0.0`, max `180.0`) | Smooth angle. Converted to radians and passed to `bpy.ops.object.shade_auto_smooth`. |

### Notes
- Modifier cleanup only touches modifiers of type `NODES` whose name contains "Auto Smooth" or "Smooth by Angle". Other modifiers are left alone.
- After `shade_auto_smooth`, the resulting "Smooth by Angle" modifier is force-enabled (`show_viewport`, `show_render` set true), unpinned (`use_pin_to_last = False`), and bubbled to slot 0 via repeated `modifier_move_up` calls (bounded by stack length).
- Progress is reported per-mesh through the addon's `with_progress` wrapper.
- Operator is `REGISTER | UNDO`; the redo panel exposes `angle`.

---

## Clear Custom Normals (bl_idname: iops.object_clear_normals)

<div class="iops-meta" markdown="1">
<span class="key">bl_idname: iops.object_clear_normals</span>
<span class="mode">Mode: Object</span>
<span>Context: VIEW_3D</span>
<span class="modal">Modal: no</span>
<span class="hud">HUD: no</span>
</div>

### Overview
Removes custom split normal data from every selected mesh. Pairs with Auto Smooth: custom normals override the Smooth by Angle modifier, so clearing them is often a prerequisite for clean auto-smooth results on imported geometry.

### Usage
- Select one or more mesh objects that actually carry custom normals. Poll requires at least one selected mesh with `data.has_custom_normals == True`.
- No default keymap binding. Invoke via menu / F3 search.
- For each mesh, runs `bpy.ops.mesh.customdata_custom_splitnormals_clear()` under a `temp_override(object=obj)`.

### Properties
This operator has no properties.

### Notes
- Logs `Clearing custom normals from <name>, N of M` to the console for each processed object.
- `REGISTER | UNDO`.

## Related
- [Shading toggles and helpers](op_object_auto_smooth.md)
- [Object utilities index](../index.md)
