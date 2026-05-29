# Snap Combos

Stores and recalls up to eight snapshots of Blender's snap stack (snap elements, tool-settings flags, transform pivot, transform orientation) to a user JSON file. Clicking a slot loads it; clicking with the configured modifier overwrites that slot with the current scene state.

<div class="iops-meta" markdown="1">
<span class="key">bl_idname: iops.set_snap_combo</span>
<span class="mode">Mode: any</span>
<span>Context: any (driven from the IOPS TM panel)</span>
<span class="modal">Modal: no</span>
<span class="hud">HUD: no</span>
</div>

## Overview

Blender's snap settings are a global state spread across `tool_settings.snap_elements`, several `use_snap_*` flags, `snap_target`, `transform_pivot_point`, and the active transform orientation. Switching between, say, "vertex snap with Active pivot" and "face-project with Median pivot" by hand is tedious. Snap Combos collapses that into eight named slots persisted to disk.

The slots live in `<scripts>/presets/IOPS/iops_prefs_user.json` under the `SNAP_COMBOS` key as `snap_combo_1` through `snap_combo_8`. The file is created with sensible defaults on first use and written atomically through a `.tmp` file. A corrupted JSON file is moved aside to `.backup` and replaced.

## Usage

- Open the IOPS TM panel (default keymap: `Ctrl+Alt+Shift+T`, see `iops.call_panel_tm`). The Snap Combo section exposes eight buttons labeled A through H, mapped to `idx` 1..8.
- Click a slot to load that combo into the scene's tool settings and transform orientation.
- Hold the configured save modifier and click a slot to overwrite it with the current snap state. The modifier is set in the addon preferences (`snap_combo_mod`, default `SHIFT`); the operator's tooltip is generated from that preference.
- The operator has no default keymap binding of its own; it is invoked from the panel buttons.

## Properties

| Name | Type | Default | Description |
| --- | --- | --- | --- |
| `idx` | IntProperty | 0 | Slot index (1..8) wired by the panel buttons; selects which `snap_combo_<idx>` entry to load or save. |

## Notes

- Save modifier is read from `context.preferences.addons["InteractionOps"].preferences.snap_combo_mod` and accepts `SHIFT`, `CTRL`, `ALT`, `CTRL_ALT`, `SHIFT_ALT`, `SHIFT_CTRL`, `SHIFT_CTRL_ALT`. The modifier check matches the chord exactly.
- Each combo persists:
  - `SNAP_ELEMENTS`: per-element booleans for `VERTEX`, `EDGE`, `FACE`, `VOLUME`, `INCREMENT`, `EDGE_MIDPOINT`, `EDGE_PERPENDICULAR`, `FACE_PROJECT`, `FACE_NEAREST`.
  - `TOOL_SETTINGS`: `transform_pivot_point`, `snap_target`, and the flags `use_snap_self`, `use_snap_align_rotation`, `use_snap_peel_object`, `use_snap_backface_culling`, `use_snap_selectable`, `use_snap_translate`, `use_snap_rotate`, `use_snap_scale`, `use_snap_to_same_target`.
  - `TRANSFORMATION`: type of `scene.transform_orientation_slots[0]` (e.g. `GLOBAL`, `LOCAL`, `NORMAL`).
- Default seed values when a slot does not yet exist: `VERTEX` only, pivot `ACTIVE_ELEMENT`, snap target `ACTIVE`, `use_snap_self=True`, `use_snap_peel_object=True`, transform `GLOBAL`.
- `bl_options` includes `REGISTER, UNDO`. The load path mutates scene tool settings and the active transform orientation, which is undoable; the save path only writes the JSON file on disk and is not reversible by undo.
- Loading a missing slot triggers `ensure_snap_combos_prefs()` to seed defaults and a `WARNING` report; corrupt JSON is recovered by writing a fresh defaults file and renaming the broken one to `iops_prefs_user.json.backup`.
- File path resolution uses `bpy.utils.script_path_user()`, so the JSON lives in the user scripts directory, not the addon folder; it survives addon reinstalls.

## Related

- [Drag Snap](op_drag_snap.md)
- [Drag Snap Cursor](op_drag_snap_cursor.md)
- [UV Drag Snap](op_drag_snap_uv.md)
