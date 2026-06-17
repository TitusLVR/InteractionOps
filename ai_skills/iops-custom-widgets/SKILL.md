---
name: iops-custom-widgets
description: Use when adding, editing or debugging a persistent GPU widget panel in the InteractionOps (iOps) Blender addon — clickable viewport panels with sliders/checkboxes/buttons, widget JSON defs, the widgets library folder, the scan-to-popup list, iops.widget_toggle hotkeys, or "widget doesn't show/refresh/click" issues.
---

# Writing iOps Custom Widgets

## Overview

A widget is a persistent, clickable GPU panel in the 3D viewport. Framework:
`ui/widgets/` (registry, controls, render, events, state). Everything is
drawn by one shared POST_PIXEL handler and clicked through the transient
`iops.widget_interact` modal — a widget only declares **controls bound to
get/set callables**. Show/hide, dragging, position persistence, and
per-widget toggle hotkeys are all free.

**Widgets are authored as JSON files**, one per widget, in the widgets
library folder. There are no shipped Python widget classes — the runtime
(`widgets/composed.py`) builds live widgets from JSON. (`ui/widgets`'s
`Widget` base + `register_widget` still exist for programmatic use, but
normal authoring is JSON.)

## Where widgets live

The library folder is a preference (executor-parity), resolved by
`widgets/composed.py:widgets_folder()`:
- **Widgets tab** (addon prefs) → "Widgets Folder": a "Use user script
  path" toggle + subfolder (default `presets/IOPS/widgets`), or an
  explicit path. Stored in prefs and round-tripped through the prefs JSON.
- All `*.json` there auto-load and register at addon enable
  (`composed.load_all`); the Widgets-tab list mirrors them (name +
  toggle-hotkey field per row). Edit them by hand (the tab's Open Folder
  button) or via Add / Duplicate / Import.

## JSON schema

Validated + normalized by `composed.py:validate_def`. A def:

```json
{
  "version": 1,
  "name": "my_widget",
  "title": "My Widget",
  "space": "VIEW_3D",
  "rows": [ <row>, ... ]
}
```

Row types:

| type | keys | binds |
|---|---|---|
| `SECTION` | `label` | — (non-interactive header) |
| `SLIDER` | `target` (BEVEL/CREASE), `snap` | edge float attribute |
| `PRESETS` | `target` (BEVEL/CREASE), `values` (list 0..1) | edge float attribute |
| `FLIPBOX` | EITHER `target` (SHARP/SEAM/FREESTYLE) OR `prop` (dotted RNA path), `label` | edge bool OR arbitrary RNA bool |
| `BUTTON` | `op` (operator idname), `op_kwargs`, `label`, `role` (default/error) | fires an operator |
| `ROW` | `cells` (list of the above, no nested ROW) | lays its cells on one panel line |

Key capabilities:
- **`FLIPBOX` `prop`** binds any scene/RNA boolean, e.g.
  `"prop": "scene.CCP.red_export_opaqueAreas"`. Resolved against `context`
  per call; absence-safe → renders **disabled** when the path is missing
  (e.g. the owning addon isn't loaded). Edge `target` flipboxes still work.
- **`ROW`** puts a toggle next to its Export button (the 2-column look).
  A **single-cell ROW forces one-per-row** — needed because consecutive
  bare `FLIPBOX` rows implicitly merge into one multi-column row
  (`merge_flipbox_runs`), which you usually don't want for stacked toggles.
- **Edit-mesh gating is automatic**: if any control binds an edge `target`,
  the widget polls EDIT_MESH and its buttons/presets gray out with no edge
  selection. A widget with no edge `target` (e.g. all `prop` flipboxes)
  polls always-True and keeps its buttons enabled.

Example (toggle + per-item export, stacked + paired), mirroring a sidebar
panel:

```json
"rows": [
  {"type": "SECTION", "label": "Materials"},
  {"type": "ROW", "cells": [{"type": "FLIPBOX", "prop": "scene.CCP.red_export_opaqueAreas", "label": "Opaque"}]},
  {"type": "SECTION", "label": "Sets"},
  {"type": "ROW", "cells": [
    {"type": "FLIPBOX", "prop": "scene.CCP.red_export_bannerSets", "label": "Banner"},
    {"type": "BUTTON", "label": "Export", "op": "ccp_tools.export_banner_data"}]},
  {"type": "BUTTON", "label": "Update Red File", "op": "ccp_tools.update_red_file"}
]
```

Invalid rows are dropped with an error (the rest of the widget survives);
`composed.load_def` / `validate_def` return `(clean_def, errors)`.

## Summon + popup + hotkey

- `bpy.ops.iops.widget_toggle(name="my_widget")` — toggles that widget at
  the cursor.
- `bpy.ops.iops.scripts_call_widgets_panel()` — scans the folder,
  registers everything, and pops `IOPS_PT_WidgetList`: one button per
  widget; clicking summons it. Bindable (appears in the Keymaps "Scripts"
  bucket) and exposed as the Widgets-tab "Open Widgets Panel" button.
- `events.sync_toggle_kmis()` keeps one unbound `iops.widget_toggle`
  keymap entry per registered widget; the Widgets-tab list row draws its
  key-capture field. Bindings persist in userpref (NOT the iops hotkey
  save file — the tuple can't carry the `name` property; it's in
  `NEVER_SAVE`).

## Gotchas

| Symptom / trap | Reality |
|---|---|
| Stacked toggles merged into one row | Consecutive bare `FLIPBOX` rows auto-merge; wrap each in a single-cell `ROW` to force one-per-row |
| `FLIPBOX` rejected on validate | Needs EXACTLY ONE of `target` or `prop` (neither/both → dropped) |
| Scene-prop toggle always disabled | The RNA `prop` path doesn't resolve against `context` (owning addon absent, or wrong path) — that's the intended disabled state |
| ActionButton op does nothing | Buttons fire `op("INVOKE_DEFAULT", **kwargs)`; invoke-only operators called EXEC_DEFAULT return `{'PASS_THROUGH'}` silently. INVOKE_DEFAULT is already used — if still silent, check the operator's own `poll` |
| Button grays out unexpectedly | Edge-bound widgets gate buttons/presets on edge selection; a scene-prop widget (no edge `target`) keeps them enabled |
| `poll() False` shows wrong hint | Edge widgets out of EDIT_MESH collapse to title + HARDCODED "Go back to Edit Mode" (`render.py OUT_OF_CONTEXT_TEXT`). For "addon missing", don't gate poll — let `prop` flipboxes go disabled via `(None, False)` |
| Widget doesn't refresh after external change | Cache invalidates on depsgraph/undo/redo (`ui/widgets/state.py`); no depsgraph tick = stale until one |
| Rename lost the file/binding | Rename moves the JSON on disk (load old → save new) and re-points the hotkey via `events.rename_toggle_kmi`; the prefs list mirrors only name/title, never row contents |
| Toggle hotkey absent from Keymaps tab | Intentional — drawn only in the Widgets-tab list, excluded from hotkey save (`NEVER_SAVE`) |

## Control signatures (ui/widgets/controls.py)

For reference when reading the runtime / building programmatically:

```
Section(label)
Slider(get, set, vmin=0.0, vmax=1.0, snap=0.125, fmt="{:.3f}", snapshot=None, restore=None)
PresetRow(values, set, fmt="{:g}", enabled_get=None)
FlipBox(label, get, set)
ActionButton(label, op, kwargs=None, role="default", enabled_get=None)
Row(children)
```

get(context) → `(value, is_mixed)`; `value is None` renders disabled.
set(context, value) writes to all targets; re-resolve data per call, never
cache bmesh/RNA refs. `is_mixed` is for multi-element edge selections;
scalar bindings always return `False`.

## Verify

Reload addon (blinker port 9902, or disable → purge `sys.modules` →
enable), then `bpy.ops.iops.scripts_call_widgets_panel()` and
`bpy.ops.iops.widget_toggle(name="...")` in a VIEW_3D context; click every
control. `python -m pytest tests -q` must stay green
(`widgets/composed.py` stays bpy-free for the standalone test harness).
