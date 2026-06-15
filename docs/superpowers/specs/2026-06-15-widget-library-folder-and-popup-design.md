# Widget Library Folder + Scan-to-Popup — Design

Date: 2026-06-15
Status: approved (brainstorming)

## Goal

Turn the JSON-composed widget system into a user-managed *library*:

1. The widgets folder becomes a configurable preference (executor-parity:
   a "use user script path" toggle + subfolder, or an explicit path),
   saved with user prefs and shown in the Widgets prefs tab.
2. A bindable operator scans that folder and pops an executor-style panel
   listing every widget; clicking a name summons that widget's GPU panel.
3. The two currently-hardcoded Python widgets (`edge_data`,
   `ccp_data_ops`) are extracted to JSON files in the folder and their
   Python classes removed — "everything is data".
4. The JSON schema is extended so `ccp_data_ops` (and future widgets) can
   bind arbitrary scene/RNA booleans and lay a toggle beside a button on
   one row — capabilities the edge-attribute-only schema lacks today.

## Non-goals

- No auto-seed / bundled defaults. Writing the two JSON files into the
  user folder is a one-time action; a fresh install (or a folder pointed
  elsewhere) starts empty until the user adds widgets. (Explicit choice.)
- No filter field on the popup (executor has one; YAGNI here).
- No generic RNA *float* binding (slider/presets). Only RNA *bool*
  (FLIPBOX) is needed for ccp; floats stay edge-adapter-only for now.

## Current state (baseline)

- `widgets/composed.widgets_folder()` is hardcoded to
  `bpy.utils.script_path_user()/presets/IOPS/widgets`.
- Two Python widgets register unconditionally in `widgets/__init__.py`:
  `EdgeDataWidget` (`widgets/edge_data.py`) and `CCPDataOpsWidget`
  (`widgets/ccp_data_ops.py`).
- `widgets/composed.py` holds `EDGE_DATA_DEF` (a JSON mirror of edge_data)
  and `validate_def`; `prefs/widget_composer.py` exposes `builtin_defs()`
  (returns `{"edge_data": EDGE_DATA_DEF}`) and renders built-ins as locked
  prefs rows. `register_composed` has a "may not shadow a built-in" guard.
- JSON FLIPBOX/SLIDER/PRESETS bind ONLY to the fixed `adapters.ADAPTERS`
  registry (BEVEL/CREASE float, SHARP/SEAM/FREESTYLE bool). Composed
  BUTTON/PRESETS are wired with `enabled_get=has_selected_edges`.
- Rows are single controls; consecutive FLIPBOX defs merge into one panel
  row via `merge_flipbox_runs`. There is no way to mix control types on a
  row, and no way to bind a non-edge property.
- Executor reference (the analogy), `operators/executor.py`:
  `IOPS_OT_Call_MT_Executor` (`iops.scripts_call_mt_executor`, bindable)
  scans the scripts folder, fills a CollectionProperty, and
  `wm.call_panel("IOPS_PT_ExecuteList")`. The panel draws one
  `iops.executor` button per script. Executor folder prefs:
  `executor_use_script_path_user` (bool), `executor_scripts_subfolder`,
  `executor_scripts_folder` (DIR_PATH).

## Design

### 1. Configurable widgets folder (executor-parity)

Add to `IOPS_AddonPreferences` (`prefs/addon_preferences.py`):

```python
widgets_use_script_path_user: BoolProperty(
    name="Use user script path", default=True)
widgets_subfolder: StringProperty(
    name="Widgets sub-folder", default="presets/IOPS/widgets")
widgets_folder: StringProperty(
    name="Widgets Folder", subtype="DIR_PATH",
    default=bpy.utils.script_path_user())
```

`composed.widgets_folder()` is rewritten to read these:

```python
def widgets_folder():
    import bpy
    prefs = bpy.context.preferences.addons["InteractionOps"].preferences
    if prefs.widgets_use_script_path_user:
        sub = prefs.widgets_subfolder.strip()
        base = bpy.utils.script_path_user()
        return os.path.join(base, sub) if sub else base
    return prefs.widgets_folder
```

Resolution must be defensive: if prefs are unavailable (early
register / factory-startup), fall back to the old hardcoded path so
`load_all()` at register never throws.

Drawn at the top of the Widgets tab (`draw_widgets_tab`), mirroring the
executor section's layout: the toggle, then either the
`script_path_user()` label + subfolder field (computed path shown), or
the explicit `widgets_folder` DIR_PATH field.

Saved with prefs automatically (AddonPreferences round-trip + the addon's
existing prefs JSON export — verify `widgets_*` land in
`prefs/iops_prefs.py` if it maintains an explicit field list).

### 2. JSON schema extension

In `widgets/composed.py` `validate_def` and `build_controls`, plus a new
adapter:

**RNA bool toggle (FLIPBOX `prop`):**
- A FLIPBOX def may carry `"prop": "<dotted RNA path on context>"`
  INSTEAD of `"target"`. Exactly one of the two must be present; a FLIPBOX
  with neither (or both) is dropped with an error (row-level, keeps the
  rest of the widget).
- New generic adapter (in `adapters.py`), e.g. `rna_bool_adapter(path)`
  returning `{"get": ..., "set": ...}`:
  - `get(context)`: walk the dotted path from `context` via `getattr`;
    any missing attribute → `(None, False)` (renders disabled). Otherwise
    `(bool(value), False)` — scalar, never mixed.
  - `set(context, value)`: resolve the owner (all but last segment) and
    `setattr(owner, last, bool(value))`; no-op if the path can't resolve.
- `build_controls` builds `FlipBox(label, get, set)` from the adapter.

**Explicit ROW grouping:**
- New row type `{"type": "ROW", "cells": [ <rowdef>, <rowdef>, ... ]}`.
  Each cell is a normal row def (FLIPBOX/BUTTON/SLIDER/PRESETS/SECTION;
  nested ROW disallowed). `validate_def` validates each cell, dropping
  invalid cells; an empty ROW is dropped.
- `build_controls` maps a ROW to `Row([build each cell])`. This coexists
  with the existing implicit adjacent-FLIPBOX merge (edge_data's Flags
  row keeps working without an explicit ROW).

**Button/preset enable gating:**
- `build_controls` already computes `_binds_edges(row_defs)`. Pass that
  in: composed BUTTON and PRESETS get `enabled_get=has_selected_edges`
  ONLY when the widget binds edges; otherwise `enabled_get=None`
  (always enabled). This stops CCP export buttons from graying out with
  no edge selection.
- `make_widget` poll stays: `EDIT_MESH` when edge-bound, else `True`
  (ccp → True, matching the old Python widget).

### 3. Extract the two widgets; remove Python classes

- Generate and write `edge_data.json` and `ccp_data_ops.json` into the
  resolved widgets folder (`B:\scripts\presets\IOPS\widgets`):
  - `edge_data.json` ← the existing `EDGE_DATA_DEF` content (sections,
    bevel/crease sliders + presets, three Flags flipboxes via implicit
    merge, Clear button role=error).
  - `ccp_data_ops.json` ← Materials section (5 bare `prop` flipboxes),
    then Sets/Light/Locators sections where each item is a
    `ROW: [FLIPBOX prop=scene.CCP.red_export_*, BUTTON op=ccp_tools.export_*_data label="Export"]`,
    then a final `BUTTON op=ccp_tools.update_red_file label="Update Red File"`.
- Delete `widgets/edge_data.py` and `widgets/ccp_data_ops.py`.
- `widgets/__init__.py`: drop the two imports and their
  register/unregister calls; the package now only wires `composed`
  (load_all / unregister_all). Keep the bpy-guard structure.
- `widgets/composed.py`: remove `EDGE_DATA_DEF` and the built-in shadow
  guard in `register_composed` (no built-ins to shadow anymore).
- `prefs/widget_composer.py`: remove `builtin_defs()` and the built-in
  branch in `sync_from_files` / `def_to_item` / the UIList lock icon. All
  list entries are now editable JSON widgets. (The registry-only fallback
  rows added earlier become dead and are removed.)
- `adapters.py` stays (composed widgets use `ADAPTERS` + the new RNA
  adapter). Drop the edge_data re-export comments if any dangle.
- Grep for stray imports of `widgets.edge_data` / `EdgeDataWidget` /
  `EDGE_DATA_DEF` / `builtin_defs` and clean each.

### 4. Scan-to-popup

In a new file `operators/widgets_panel.py` (kept separate from the
executor so each stays focused):

- `IOPS_OT_Call_Widgets_Panel` — `bl_idname =
  "iops.scripts_call_widgets_panel"`, `is_bindable = True`:
  1. `folder = composed.widgets_folder()`.
  2. For each `*.json`: `load_def`; if valid, `register_composed`
     (idempotent — re-scan after a folder change makes them live).
  3. `events.sync_toggle_kmis()` so new widgets get toggle entries +
     prefs rows.
  4. Store `(name, title)` for the found widgets in a CollectionProperty
     (on `IOPS_AddonProperties` / WM, mirroring executor's
     `executor_scripts`).
  5. `bpy.ops.wm.call_panel(name="IOPS_PT_WidgetList")`.
- `IOPS_PT_WidgetList` (`bl_region_type="WINDOW"`, VIEW_3D): draw one
  `iops.widget_toggle` button per stored widget (text = title, sorted),
  alphabetical letter headers like the executor list. Empty-folder case:
  a label ("No widgets in folder").

### 5. Tests + skill doc

- `tests/ui/widgets/test_composed.py`: add cases for FLIPBOX `prop`
  (valid path string accepted; neither/both target+prop dropped), ROW
  (cells built, empty dropped, invalid cell dropped), and button/preset
  enable gating by `_binds_edges`. The RNA adapter get/set is bpy-bound,
  so unit-test the path-resolution helper with a fake object, not bmesh.
- Folder resolution: a small test for `widgets_folder()` prefs branches
  (mock prefs) if feasible without bpy; otherwise covered in live verify.
- Remove/adjust any `EdgeDataWidget` / `EDGE_DATA_DEF` references in
  tests.
- `ai_skills/iops-custom-widgets/SKILL.md`: document the `prop` FLIPBOX,
  the `ROW` row type, the configurable folder, and the scan-to-popup
  operator; note that authoring is now JSON-first (no Python widget
  classes shipped).

## Verification

- `python -m pytest tests -q` green.
- Live in Blender 5.1.2 (reload addon): both JSON widgets load from the
  folder; `iops.scripts_call_widgets_panel` pops the list; clicking
  summons each; ccp toggles + per-item Export buttons + Update Red File
  work and the toggles render disabled when CCP Tools is absent; folder
  pref toggle + subfolder/explicit path resolve correctly and persist
  across reload.

## Risks / open points

- Removing built-ins changes `widget_composer` list semantics (no locked
  rows). Confirm the hotkey-capture column still renders for plain JSON
  rows.
- `register_composed` on scan must remain idempotent and must not double-
  register the auto-loaded ones (same names) — keyed by name, so safe.
- Prefs JSON export (`prefs/iops_prefs.py`) may enumerate fields
  explicitly; the new `widgets_*` props must be added there or they won't
  round-trip through the addon's Save/Load Prefs buttons.
