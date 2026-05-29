# Split Screen Area (New)

Splits the current screen area to create a sibling area of a requested editor type, or joins/closes a matching neighbour to toggle it off. Used as the workhorse behind the Split pie menu so a single shortcut both opens and closes a paired editor on a chosen side. Saves and restores the closed area's space data via `iops.space_data_save` / `iops.space_data_load`.

<div class="iops-meta" markdown="1">
<span class="key">bl_idname: iops.split_screen_area</span>
<span class="mode">Mode: any</span>
<span>Context: any editor area</span>
<span class="modal">Modal: no</span>
<span class="hud">HUD: no</span>
</div>

## Overview
The operator is a toggle-style area manager. Given a target `area_type` + `ui_type` and a side (`LEFT`/`RIGHT`/`TOP`/`BOTTOM`), it picks one of three branches:

1. If the active area already matches the target type, close it (with space data saved).
2. If any other area on the screen matches the target type and ui_type, close that area.
3. Otherwise, split the current area at the requested side and convert the new area to the target type/ui, then call `iops.space_data_load` to restore previously stored space settings.

It also detects Blender's fullscreen toggle screen (name contains `nonnormal`) and exits back to the previous screen instead of splitting.

## Usage
- Works from any editor area; the area being split is `context.area`.
- No default keymap binding. Invoked from the Split pie (`iops.call_pie_split`) and other UI hooks that pass the four properties below.
- Call with `area_type`, `ui`, `pos`, and `factor` set; for example `bpy.ops.iops.split_screen_area(area_type='IMAGE_EDITOR', ui='UV', pos='RIGHT', factor=0.5)`.

## Properties
| Name | Type | Default | Description |
| --- | --- | --- | --- |
| `area_type` | String | `""` | Blender area type to create or match (e.g. `VIEW_3D`, `IMAGE_EDITOR`, `OUTLINER`). |
| `ui` | String | `""` | Target `ui_type` to set on the newly created area (e.g. `UV`, `ShaderNodeTree`). Also used when matching existing areas to close. |
| `pos` | String | `""` | Side on which to split: `LEFT`, `RIGHT`, `TOP`, or `BOTTOM`. |
| `factor` | Float | `0.01` | Split factor passed to `screen.area_split`. Soft range 0.01..1, step 0.01, precision 2. Value `0.5` is silently clamped to `0.499` to dodge a Blender splitter glitch. The factor is mirrored to `1 - factor` when `pos` is `RIGHT` or `TOP`. |

## Notes
- Only one Operator (`IOPS_OT_SplitScreenArea`) is registered in this file. No panels, menus, or property groups.
- Depends on sibling operators `iops.space_data_save` and `iops.space_data_load` to round-trip editor settings across close/open cycles.
- Area-matching when joining a mirrored side uses exact pixel-perfect comparisons of `x`, `y`, `width`, `height` between neighbours; areas that don't line up cleanly are skipped and the operator reports "No side area to join".
- When the active screen name contains `nonnormal` (Blender's fullscreen toggle state), the operator calls `screen.back_to_previous` and returns immediately without splitting.
- Uses `context.temp_override` with a manually built context dict from `ContextOverride()` to drive `screen.area_close` and the space-data operators on the correct area.

## Related
- [Space Data Save / Load](op_save_load_space_data.md)
- [Pie: Split](../ui/ui_pies.md)
