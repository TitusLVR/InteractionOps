# Stats Overlay Extension — Design

**Date:** 2026-07-03
**Status:** Approved

## Goal

Extend the persistent viewport statistics overlay (`utils/draw_stats.py`) with
modular, individually-toggleable stat lines inspired by Maya HUD / 3ds Max
viewport stats. Every new stat is a pure property read per redraw — no geometry
traversal, no caches needed.

## New stat lines

Each line gets its own `BoolProperty` in addon preferences (Statistics Overlay
section). All new toggles default **OFF** so the overlay does not change
unexpectedly after update.

| Pref | Overlay line | Notes |
|------|--------------|-------|
| `show_dimensions_stat` | `Dims: 2.00 x 1.50 x 0.75 m` | `obj.dimensions` formatted with scene units (`bpy.utils.units.to_string`). Any object type with dimensions. |
| `show_instances_stat` | `Instances: 3` | Only drawn when `obj.data.users > 1` (warning color) — editing shared data. |
| `show_modifiers_stat` | `Mods: 4` + `viewport != render` warning | Count of modifiers; red suffix when any modifier has `show_viewport != show_render`. Line hidden when stack is empty. |
| `show_material_stat` | `Mat: Metal [2/3]` | Active material name + filled/total slot count. `No material` / `Empty slots` in warning color. |
| `show_material_users_stat` | appends `(3 users)` | Appended to the material line when the active material has `users > 1`. Only effective when `show_material_stat` is on. |
| `show_parent_stat` | `Parent: Rig_Root  +2 constraints` | Only drawn when the active object has a parent and/or constraints. |
| `show_units_stat` | `Units: scale 0.01` | **Warning-only line**: drawn in error color only when `scene.unit_settings.scale_length != 1.0`. Silent when units are sane. |
| `show_view_position_stat` | `Pos: 1.00, 2.00, 0.50   Dist: 14.2 m` | Active object world location + distance from viewpoint (`(rv3d.view_matrix @ loc).length`). One matrix multiply per redraw. |

## Layout / rendering

- Reuse the existing pattern: `_t(label, role=Role.HUD_LABEL)` +
  `_t(value, x=base_column_x)`, `offset_y -= row_step` per line.
- Warnings use `Role.HUD_STATS_ERROR`, normal values `Role.HUD_LABEL_ACTIVE` /
  `Role.HUD_LABEL`, matching current lines.
- Conditional lines (instances, parent, units) occupy no row when their
  condition is false — the overlay stays compact.
- Order (top to bottom): File, Dims, Pos/Dist, Mat, Mods, Instances, Parent,
  Units, then the existing UVMaps / Scale / Selection block.

## Performance

Draw handler runs on every viewport redraw, so the budget is strict:

- All new stats are O(1) property reads or O(modifier-stack) loops (single
  digits). No polygon/vertex iteration anywhere.
- No caching layer required.
- Unit formatting via `bpy.utils.units.to_string` (C call).

## Files touched

- `utils/draw_stats.py` — new stat lines.
- `prefs/addon_preferences.py` — 8 new `BoolProperty` + checkboxes in the
  Statistics Overlay section.
- `prefs/iops_prefs.py` — defaults for save/export.
- `operators/preferences/io_addon_preferences.py` — load path for new props.
- `docs/preferences.md` — document new prefs.

## Out of scope

- Tris/Ngons counter (needs mesh-change cache) — possible follow-up.
- Broken-texture scan (node-tree walk + cache) — possible follow-up.
- Theme/color/position knobs — already covered by IOPS_Theme.
