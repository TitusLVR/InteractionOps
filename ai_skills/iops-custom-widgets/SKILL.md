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
| `FLIPBOX` | EXACTLY ONE of `target` (SHARP/SEAM/FREESTYLE), `prop` (dotted RNA path), or `switch` (local switch name); `label` | edge bool, arbitrary RNA bool, or local panel switch |
| `BUTTON` | `op` (operator idname), `op_kwargs`, `label`, `role` (default/error) | fires an operator |
| `SWATCH` | `prop` (RNA color path), `op` (operator idname), `op_kwargs`, `label` | shows a color, fires an operator on click |
| `ROW` | `cells` (list of the above, no nested ROW) | lays its cells on one panel line |

Any top-level row (not cells inside a `ROW`) may carry an optional `"show_if"` key — see [Conditional row rendering (`show_if`)](#conditional-row-rendering-show_if) below.

**Full field-by-field reference** (every key, type, default, and constraint
for top-level keys + all row types + `show_if` + `switches` + the context
vocabulary): see [schema-reference.md](schema-reference.md).

Key capabilities:
- **`FLIPBOX` `prop`** binds any scene/RNA boolean, e.g.
  `"prop": "scene.CCP.red_export_opaqueAreas"`. Resolved against `context`
  per call; absence-safe → renders **disabled** when the path is missing
  (e.g. the owning addon isn't loaded). Edge `target` flipboxes still work.
- **`FLIPBOX` `switch`** binds a *local panel switch* — lightweight boolean
  state stored per-widget in `widgets_state` JSON (like position). The top-level
  `"switches"` map sets non-false defaults; any switch referenced but absent
  there defaults to `false`. A FLIPBOX needs EXACTLY ONE of `target`/`prop`/`switch`.
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

### Top-level `switches` map

Optional. Sets non-false defaults for local panel switches:

```json
"switches": {"advanced": false, "show_extra": true}
```

Any switch name referenced by a `FLIPBOX` `switch` binding or a `show_if`
`switch` key defaults to `false` unless listed here. Switch state persists
per-widget in `widgets_state` JSON (same file as position) and survives
addon reload. A switch with no defining `FLIPBOX` (used only in `show_if`)
is valid — it stays at its default until changed programmatically.

### Conditional row rendering (`show_if`)

Any **top-level row** (not cells inside a `ROW`) may carry an optional
`"show_if"` object. When present, the row is rendered only if **all keys**
in the object evaluate to true (AND semantics — no OR/nesting/NOT in v1).

**`show_if` key reference:**

| key | type | passes when |
|---|---|---|
| `mode` | `str` or `list[str]` | `context.mode` is in the given set |
| `object_type` | `str` or `list[str]` | `context.active_object.type` is in the set; no active object → fails |
| `selection` | `"verts"`, `"edges"`, `"faces"`, or `"objects"` | at least one element of that kind is selected (coarse check) |
| `prop` | dotted RNA path string | the resolved value is truthy, or equals `equals` if that key is present |
| `switch` | local switch name string | the switch value is truthy, or equals `equals` if that key is present |
| `equals` | any scalar | equality target for the `prop` or `switch` in the same clause |

**Semantics and error handling:**

- All keys in the clause are ANDed; the row appears only when every key passes.
- `mode`/`object_type` accept a single string or a list — either form works.
- `prop` uses the same absence-safe resolver as `FLIPBOX` `prop`; a missing
  RNA path is **not** an error — the predicate simply evaluates falsy and the
  row is **hidden** (this is normal evaluation, distinct from the
  always-visible fallback below). Make sure the path resolves if you want the
  row visible when the value is falsy.
- An **invalid or unrecognisable `show_if`** (bad key, wrong type, etc.) is
  **dropped with a reported error** and the row becomes **always-visible** —
  rows never silently vanish from a typo. Check `load_def` errors if a row
  disappears unexpectedly.
- **v1 scope**: `show_if` applies to top-level rows only (not cells inside
  a `ROW`). No OR, negation, nesting, or cell-level visibility. Counts
  (`has_N_selected`) and GROUP rows are also out of scope.
- Evaluation is live on every draw; no extra invalidation is needed beyond
  what the depsgraph already triggers.

**Worked example** — context-sensitive panel with an Advanced toggle:

```json
{
  "version": 1, "name": "ctx_demo", "title": "Context Demo",
  "switches": {"advanced": false},
  "rows": [
    {"type": "FLIPBOX", "switch": "advanced", "label": "Advanced"},
    {"type": "BUTTON", "label": "Always", "op": "iops.executor", "op_kwargs": {"script": ""}},
    {"type": "SECTION", "label": "Advanced tools", "show_if": {"switch": "advanced"}},
    {"type": "BUTTON", "label": "Adv Only", "op": "iops.executor", "op_kwargs": {"script": ""}, "show_if": {"switch": "advanced"}},
    {"type": "SECTION", "label": "Edit-mode only", "show_if": {"mode": "EDIT_MESH"}},
    {"type": "SECTION", "label": "Mesh objects", "show_if": {"object_type": "MESH"}}
  ]
}
```

The "Always" button is always drawn. The two `show_if: {switch: advanced}`
rows appear only while the Advanced flipbox is on. The last two sections
gate on context: one appears only in Edit Mesh mode, the other only when
the active object is a mesh.

## Authoring a new widget (agent guide)

Step-by-step when building a NEW widget from scratch. Full field details are
in [schema-reference.md](schema-reference.md).

**1. Save location.** One `<name>.json` per widget in the library folder
(`composed.widgets_folder()` — default `presets/IOPS/widgets`). The filename
stem must match `name`. Drop it next to the existing widgets.

**2. Pick controls by intent:**

| Need | Use |
|---|---|
| Static label / group heading | `SECTION` |
| Run an operator | `BUTTON` (`op` + `op_kwargs`) |
| A boolean the user flips | `FLIPBOX` — `target` (edge attr), `prop` (scene/RNA bool), or `switch` (local panel state) |
| Reveal/hide other rows from a toggle | `FLIPBOX` `switch` + `show_if: {switch: …}` on the gated rows |
| Edit a bevel/crease value | `SLIDER` / `PRESETS` (edge floats; auto edit-mesh gating) |
| Show a color + apply it | `SWATCH` |
| Two controls side by side | `ROW` with `cells` |

**3. Make it context-sensitive with `show_if`.** Gate each row on `mode` /
`object_type` / `selection` / `prop` / `switch`. In `OBJECT` mode use
`object_type` to tell mesh from curve; in edit mode the `mode` string already
implies the type (`EDIT_MESH` vs `EDIT_CURVE`). Gate selection-dependent
operators on `selection` (mesh-edit only — see the vocabulary in the
reference). Enabled/disabled state is separate: edge-`target` widgets
auto-gray buttons/presets with no selection; a widget with no edge target
polls always-true and keeps buttons enabled.

**4. Choose operators that fit the click + the context:**
- Buttons fire `op("INVOKE_DEFAULT", **op_kwargs)`. **Avoid interactive modal
  operators** — the ones that grab the mouse to drag a value: `mesh.bevel`,
  `mesh.inset`, `mesh.extrude_*`, and the interactive transform tools
  `transform.translate` / `transform.resize` / `transform.rotate` /
  `transform.bevel`. INVOKE starts a modal that hijacks the viewport from a
  panel click. Non-interactive exec operators are fine even if their name
  starts with `transform`/`object` — e.g. `object.transform_apply`,
  `object.location_clear`, `pose.transforms_clear`, `mesh.subdivide`,
  `mesh.normals_make_consistent`, `object.shade_smooth`, `curve.subdivide`,
  `object.convert`. When unsure, test the click once: if it starts a drag
  instead of acting immediately, it's modal — don't use it.
- Pass enum/bool args via `op_kwargs` (e.g. `{"action": "SELECT"}`,
  `{"type": "ORIGIN_GEOMETRY"}`, `{"location": true}`).
- **Match `show_if` to the operator's own `poll`**: only show an op where it
  can actually run, or the click does nothing.

**5. Mind the flipbox auto-merge.** Consecutive bare `FLIPBOX` rows merge into
one multi-column row — this applies to **any** flipbox binding (`target`,
`prop`, or `switch`) that has no `show_if`. To keep them stacked, give each a
`show_if` (merge skips those) or wrap each in a single-cell `ROW`.

**6. Validate + verify before calling it done:**
```python
clean, errors = composed.validate_def(wdef)   # errors must be []
inst, _ = composed.register_composed(clean)
# Sweep the contexts you gated on and confirm the right rows appear:
[c.label for c in inst.rows(bpy.context)]
```
Then `python -m pytest tests -q` stays green (`composed.py` is bpy-free).

**Pre-flight checklist:**
- [ ] `validate_def` returns no errors (every row survived).
- [ ] Each `FLIPBOX` has exactly one of `target`/`prop`/`switch`.
- [ ] Every `switch` referenced in `show_if` is defined (flipbox) or defaulted (`switches` map) — else it's stuck at `false`.
- [ ] No modal operators on buttons; `op` idnames contain a `.`.
- [ ] `show_if` contexts match where each operator can run.
- [ ] Row sets verified across every gated context (object/edit, each object_type, selection on/off, switch on/off).

## Summon + popup + hotkey

- `bpy.ops.iops.widget_toggle(name="my_widget")` — toggles that widget at
  the cursor.
- `bpy.ops.iops.scripts_call_widgets_panel()` — scans the folder,
  **re-registers every def from disk** (so it doubles as a JSON
  hot-reload: edit a live widget's `*.json`, re-open the panel, and it
  rebuilds with the new rows), and pops `IOPS_PT_WidgetList`: one button
  per widget; clicking summons it. Re-registration is position- and
  visibility-preserving — both live in the module state dict
  (`ui/widgets/state.py`), not on the instance, and `register_composed`
  re-seeds the fresh panel from that state, so already-placed widgets
  don't jump to the default corner. Bindable (appears in the Keymaps
  "Scripts" bucket) and exposed as the Widgets-tab "Open Widgets Panel"
  button.
- `events.sync_toggle_kmis()` keeps one unbound `iops.widget_toggle`
  keymap entry per registered widget; the Widgets-tab list row draws its
  key-capture field. Bindings persist in userpref (NOT the iops hotkey
  save file — the tuple can't carry the `name` property; it's in
  `NEVER_SAVE`).

## Gotchas

| Symptom / trap | Reality |
|---|---|
| Stacked toggles merged into one row | Consecutive bare `FLIPBOX` rows auto-merge; wrap each in a single-cell `ROW` to force one-per-row |
| `FLIPBOX` rejected on validate | Needs EXACTLY ONE of `target`, `prop`, or `switch` (none/multiple → dropped) |
| Scene-prop toggle always disabled | The RNA `prop` path doesn't resolve against `context` (owning addon absent, or wrong path) — that's the intended disabled state |
| ActionButton op does nothing | Buttons fire `op("INVOKE_DEFAULT", **kwargs)`; invoke-only operators called EXEC_DEFAULT return `{'PASS_THROUGH'}` silently. INVOKE_DEFAULT is already used — if still silent, check the operator's own `poll` |
| Button grays out unexpectedly | Edge-bound widgets gate buttons/presets on edge selection; a scene-prop widget (no edge `target`) keeps them enabled |
| `poll() False` shows wrong hint | Edge widgets out of EDIT_MESH collapse to title + HARDCODED "Go back to Edit Mode" (`render.py OUT_OF_CONTEXT_TEXT`). For "addon missing", don't gate poll — let `prop` flipboxes go disabled via `(None, False)` |
| Widget doesn't refresh after external change | Cache invalidates on depsgraph/undo/redo (`ui/widgets/state.py`); no depsgraph tick = stale until one |
| Rename lost the file/binding | Rename moves the JSON on disk (load old → save new) and re-points the hotkey via `events.rename_toggle_kmi`; the prefs list mirrors only name/title, never row contents |
| Toggle hotkey absent from Keymaps tab | Intentional — drawn only in the Widgets-tab list, excluded from hotkey save (`NEVER_SAVE`) |
| `show_if` flipbox merged into a multi-col row | Auto-merge skips flipboxes carrying `show_if`; they stand alone so the predicate hides exactly that box |
| Row with a typo'd `show_if` shows always | Invalid `show_if` is dropped + reported; the row stays visible (never silently vanishes) — check `load_def` errors |
| Switch state lost on reload | Switches persist in `widgets_state` like position; a switch with no defining FLIPBOX stays at its default |
| Row visibility doesn't update | `show_if` is evaluated live each draw; if context changed without a depsgraph tick, nudge the viewport (same as value cache) |

## Control signatures (ui/widgets/controls.py)

For reference when reading the runtime / building programmatically:

```
Section(label)
Slider(get, set, vmin=0.0, vmax=1.0, snap=0.125, fmt="{:.3f}", snapshot=None, restore=None)
PresetRow(values, set, fmt="{:g}", enabled_get=None)
FlipBox(label, get, set)
ActionButton(label, op, kwargs=None, role="default", enabled_get=None)
Swatch(get, op, kwargs=None, label="", enabled_get=None)
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
