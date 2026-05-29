# Split Screen Area

Splits the current screen area into a new editor of the requested type, or joins a matching neighbour back into the current area when one already exists on the requested side. Used by the InteractionOps split pie to build and tear down viewport / editor layouts with a single shortcut. The companion `iops.switch_screen_area` operator toggles the current area's type in place, or closes it when it already matches.

## Split Screen Area (bl_idname: iops.split_screen_area)

<div class="iops-meta" markdown="1">
<span class="key">bl_idname: iops.split_screen_area</span>
<span class="mode">Mode: Any</span>
<span>Context: Any editor area</span>
<span class="modal">Modal: no</span>
<span class="hud">HUD: no</span>
</div>

### Overview
Given a target `ui_type`, a `pos` (LEFT/RIGHT/TOP/BOTTOM), and a split `factor`, the operator either:

- Joins an adjacent area on `pos` back into the current area when that neighbour's `ui_type` matches `ui` (calling `iops.space_data_save` on the neighbour first).
- If the current area already is `ui`, joins the neighbour on the mirrored side back into the current one.
- Otherwise splits the current area with `screen.area_split`, sets the new area's `type` / `ui_type`, optionally swaps it with the original via `screen.area_swap` so the new editor lands on the requested side, then restores its space data via `iops.space_data_load`.

If the screen is in toggled fullscreen (`nonnormal` in screen name), it exits fullscreen with hidden panels and returns. A `factor` of exactly `0.5` is clamped to `0.499` to work around a Blender split quirk.

### Usage
- Invoked from the InteractionOps Split pie (`ui/iops_pie_split.py`) with the modifier-driven primary / alternate editor slots from preferences. No default keymap binding on the operator itself.
- Callers pass `area_type`, `ui` (Blender `ui_type` string), `pos`, and `factor`.

### Properties

| Name | Type | Default | Description |
| --- | --- | --- | --- |
| `area_type` | StringProperty | `""` | Blender area type to assign to the new area (e.g. `VIEW_3D`, `IMAGE_EDITOR`). |
| `ui` | StringProperty | `""` | Blender `ui_type` to assign / match against (e.g. `VIEW_3D`, `UV`, `ShaderNodeTree`). |
| `pos` | StringProperty | `""` | Side relative to the current area: `LEFT`, `RIGHT`, `TOP`, `BOTTOM`. |
| `factor` | FloatProperty | `0.01` | Split factor; soft range `0.01..1`, step `0.01`, precision `2`. `0.5` is internally clamped to `0.499`. |

### Notes
- Depends on `iops.space_data_save` / `iops.space_data_load` to round-trip per-editor settings across the join/split.
- Uses `bpy.context.temp_override` plus a manual context override helper to drive `screen.*` operators on the correct window/screen/area/region.
- "Joining" requires the neighbour to span the same width/height and align on the matching edge; otherwise the operator falls through to a split.

## Switch Screen Area (bl_idname: iops.switch_screen_area)

<div class="iops-meta" markdown="1">
<span class="key">bl_idname: iops.switch_screen_area</span>
<span class="mode">Mode: Any</span>
<span>Context: Any editor area</span>
<span class="modal">Modal: no</span>
<span class="hud">HUD: no</span>
</div>

### Overview
Toggles the current area between its existing editor and a requested `area_type` / `ui` pair:

- If the current area already matches both `area_type` and `ui`, calls `screen.area_close` on it (skipped silently if only one area remains or the operator's poll fails).
- Otherwise sets `area.type` and `area.ui_type` to the requested values and calls `iops.space_data_load` under a context override to restore that editor's stored space data.
- When the screen is in toggled fullscreen, it exits fullscreen with hidden panels and returns.

### Usage
- Invoked from the InteractionOps Split pie with the Alt modifier. No default keymap binding on the operator itself.

### Properties

| Name | Type | Default | Description |
| --- | --- | --- | --- |
| `area_type` | StringProperty | `""` | Blender area type to switch to / compare against. |
| `ui` | StringProperty | `""` | Blender `ui_type` to switch to / compare against. |

### Notes
- Will not close the last remaining area on the screen.
- Errors from `area_close` / `space_data_load` are swallowed to keep the pie responsive.

## Related
- [Space Data Save/Load](op_save_load_space_data.md)
- [Pie Split](../ui/ui_pies.md)
