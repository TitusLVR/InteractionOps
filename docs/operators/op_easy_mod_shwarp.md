# Easy Mod — Shwarp

Adds a pre-configured Shrinkwrap modifier (named `iOps Shwarp`) to every selected mesh, targeting the active object. Optionally adds a Data Transfer modifier (`iOps Transfer Normals`) that copies custom normals from the target, and can place the new modifier at a chosen position in each object's stack. Saves the repetitive clicks of wiring up shrinkwrap-to-active across a batch of meshes.

<div class="iops-meta" markdown="1">
<span class="key">bl_idname: iops.modifier_easy_shwarp</span>
<span class="mode">Mode: Object</span>
<span>Context: VIEW_3D</span>
<span class="modal">Modal: no</span>
<span class="hud">HUD: no</span>
</div>

## Overview
Use this when you have a hi-res or sculpted target and one or more lower-res meshes that should conform to it. The active object is the target; all other selected meshes receive the modifier. The Shrinkwrap is created with `show_in_editmode` and `show_on_cage` enabled so edits on the source mesh stay snapped to the target while you work.

When `PROJECT` is chosen, the operator also flips on Z-axis projection with both positive and negative directions, which matches the common "drape this onto that" workflow.

## Usage
- Select two or more mesh objects in Object Mode in the 3D View. The active object is the shrinkwrap target; the other selected meshes get the modifier.
- No default keymap binding — invoke via menu / F3 search.
- If a selected object already has a modifier named `iOps Shwarp`, that object is skipped (no re-configuration).
- If `Use vertex groups` is on and an object has no vertex groups, both `Use vertex groups` and `Transfer Normals` are silently disabled for the rest of that run.

## Properties
| Name | Type | Default | Description |
| --- | --- | --- | --- |
| `shwarp_offset` | Float | `0.0` | Shrinkwrap offset distance. Range `0.0`–`9999.0`. |
| `shwarp_method` | Enum | `PROJECT` | Wrap method. Items: `NEAREST_SURFACEPOINT`, `PROJECT`, `NEAREST_VERTEX`, `TARGET_PROJECT`. |
| `shwarp_use_vg` | Bool | `False` | Use the first vertex group on each source mesh to mask the shrinkwrap (and the Data Transfer mod if added). |
| `transfer_normals` | Bool | `False` | Also add an `iOps Transfer Normals` Data Transfer modifier copying custom loop normals (`POLYINTERP_NEAREST`) from the target. |
| `stack_location` | Enum | `Last` | Where to place the new modifier in each object's stack. Items: `First`, `Last`, `Before Active`, `After Active`. |

## Notes
- The added Shrinkwrap is named `iOps Shwarp`; if it already exists on a target object, that object is skipped entirely.
- The added normal-transfer modifier is named `iOps Transfer Normals`; if already present, it is left alone.
- `show_in_editmode` and `show_on_cage` are forced on for the new Shrinkwrap so editing the source mesh stays snapped to the target.
- `PROJECT` mode forces `use_project_z`, `use_negative_direction`, and `use_positive_direction` on.
- Stack placement uses `bpy.ops.object.modifier_move_down` inside a `temp_override`, iterating until the modifier reaches the requested slot. `First` is handled by the same loop using the current modifier count, so `iOps Shwarp` ends up at the top when chosen.
- Vertex-group masking always picks `ob.vertex_groups[0]` — the first group on the object, not a named one.
- Poll requires an active MESH object in `VIEW_3D` with at least 2 selected objects.

## Related
- Easy Mod — Bevel
- Easy Mod — Solidify
- [Easy Mod — Curve](op_easy_mod_curve.md)
