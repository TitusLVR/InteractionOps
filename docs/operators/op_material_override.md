# Material Override

A popup panel and operator set for managing the active view layer's `material_override` slot. It lists every material in the file, lets you apply or clear the override in one click, and offers utilities to refresh or pre-generate material previews so the panel can be browsed quickly.

<div class="iops-meta" markdown="1">
<span class="key">bl_idname: iops.call_panel_material_override</span>
<span class="mode">Mode: any</span>
<span>Context: VIEW_3D</span>
<span class="modal">Modal: no</span>
<span class="hud">HUD: no</span>
</div>

## Overview

Blender's view layer material override is buried in Properties > View Layer. This operator surfaces it as a floating panel callable from the 3D View, showing all scene materials in either a compact list or a grid ("Fancy Mode") and applying the override on click. Companion operators clear the override, force a refresh of cached previews, or pre-generate all previews so they survive a `.blend` save.

Use this when you want to swap the whole render to a clay/AO/checker material per view layer without manually selecting objects.

## Usage

- Works in the 3D Viewport (the panel operator's `poll` requires `VIEW_3D`).
- No default keymap binding — invoke via menu / F3 search / Pie.
- The panel header offers a `Clear` button next to the current override and a `Fancy Mode` toggle that switches between a list and an icon grid (grid columns are auto-fit to a 5:3 aspect ratio).
- Clicking a material name in the panel calls `iops.material_override_apply` with that material; the active material is shown depressed with a check mark.

## Properties

### iops.material_override_apply

| Name | Type | Default | Description |
| --- | --- | --- | --- |
| material_name | StringProperty | "" | Name of the material to set as the view layer override. Must exist in `bpy.data.materials`. |

The other registered operators (`iops.material_override_clear`, `iops.material_override_refresh_previews`, `iops.material_override_generate_previews`, `iops.material_override_clear_rendering_flag`, `iops.call_panel_material_override`) take no properties.

## Notes

- Registered alongside the popup operator:
    - `IOPS_OT_Material_Override_Apply` (`iops.material_override_apply`) — sets `view_layer.material_override` to the named material. REGISTER, UNDO.
    - `IOPS_OT_Material_Override_Clear` (`iops.material_override_clear`) — sets the override to `None`. REGISTER, UNDO.
    - `IOPS_OT_Material_Override_Refresh_Previews` (`iops.material_override_refresh_previews`) — calls `mat.preview.reload()` on every material so caches re-render lazily.
    - `IOPS_OT_Material_Override_Generate_Previews` (`iops.material_override_generate_previews`) — calls `mat.preview_ensure()` on every material to pre-bake previews so they save with the file.
    - `IOPS_OT_Material_Override_Clear_Rendering_Flag` (`iops.material_override_clear_rendering_flag`) — resets `is_rendering` on the settings PropertyGroup. INTERNAL.
    - `IOPS_PT_Material_Override_Panel` — the popup panel drawn by `wm.call_panel`.
    - `IOPS_MaterialOverrideSettings` — scene PropertyGroup attached as `scene.iops_material_override_settings`; stores `fancy_mode` (BoolProperty, default `False`).
- The panel draws static `SHADING_RENDERED` / `MATERIAL_DATA` icons rather than live material previews to avoid blocking the UI during draw. Use `Refresh Previews` / `Generate All Previews` operators explicitly if you need preview thumbnails.
- The invoke path catches the `drawing/rendering` RuntimeError that `wm.call_panel` raises when Blender is mid-redraw and reports a friendly "try again in a moment" message instead of failing.
- The override is per view layer — switching view layers shows that layer's own override state.

## Related

- [Channel Hop](op_mesh_uv_channel_hop.md)
- [Object UVMaps Cleaner](op_object_uvmaps_cleaner.md)
