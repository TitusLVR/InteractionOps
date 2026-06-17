# Object Color GPU Widget — Design

Date: 2026-06-16
Branch: feat/widget-library-folder

> **Addendum (2026-06-17): converted to a JSON composed widget.** The branch
> moved to JSON-first widget authoring (widgets live as definition files in
> the library folder, loaded by `composed.load_all()`), so the Python
> `ObjectColorWidget` was retired. Instead, the JSON composer
> (`widgets/composed.py`) gained a **SWATCH** row type + `rna_color_adapter`,
> and the widget now ships as `presets/IOPS/widgets/object_color.json`. The
> `Swatch` control, render, and events work below are unchanged — the SWATCH
> JSON block reuses them. Swatches/buttons are **always enabled** in the JSON
> version (operator poll handles no-selection), dropping the Python version's
> `enabled_get` graying. This supersedes the "JSON composer support for
> swatches — out of scope" note at the end of this document.

## Goal

A persistent, draggable GPU widget in the 3D viewport that mirrors the IOPS
Object Color panel (`ui/iops_object_color_panel.py`), built on the existing
GPU widget framework (`ui/widgets/`). The widget is **recents-focused**:
the eight recent-color swatches are the primary surface, each click-to-apply,
backed by the same operators the sidebar panel uses.

A GPU panel cannot host Blender's native color wheel, so there is **no
in-panel color editing**. Color editing stays in the sidebar panel; the
widget covers the basic operations (Apply, Copy From Active) and color
selection by clicking a swatch.

## Background

The Object Color panel exposes:
- a native color picker bound to `scene.IOPS.iops_object_color`,
- **Copy From Active** (`iops.object_color_copy_from_active`),
- **Apply Color** (`iops.object_color_apply`),
- 8 recent swatches (`iops_object_color_recent_0..7`), each with an apply
  button (`iops.object_color_apply_recent`, `index` property).

Recents live as eight `FloatVectorProperty(subtype="COLOR", size=4)` props on
`IOPS_SceneProperties`; slot 0 is most recent. `push_recent_color()` in
`operators/object_color.py` handles dedup/shift on Apply. `apply_recent` does
**not** reorder (the swatch row stays stable while clicking through it).

The widget framework (`ui/widgets/`) offers declarative controls — `Section`,
`Slider`, `PresetRow`, `FlipBox`, `ActionButton`, `Row`. None can draw an
arbitrary RGBA fill, so a new control is required.

All `iops_object_color*` props are `subtype="COLOR"` (scene-linear). The
POST_PIXEL draw path writes display-referred pixels, so swatch fills must be
encoded scene-linear → sRGB. `ui/draw/theme.py` already exposes `_srgb_encode`
for exactly this (it is used for every screen-space HUD role).

## New primitive: `Swatch` control

A new control kind, added additively to the framework.

```
Swatch(get, op, kwargs=None, label="", enabled_get=None)
    kind = "swatch"
    interactive = True
```

- `get(context) -> (rgba, is_mixed)` — returns the 4-tuple color to fill.
  `rgba is None` → control renders disabled. Scalar binding, so `is_mixed`
  is always `False` (returns `(color, False)` / `(None, False)`), matching
  the `_ValueControl` getter contract.
- Subclasses `_ValueControl` with `set=None` (value-cached like every other
  bound control; `write()` is never called — the swatch only reads + fires an
  operator).
- `op` / `kwargs` mirror `ActionButton`: the operator fires on
  release-inside-rect via `INVOKE_DEFAULT`.
- `label` — optional short text drawn centered on the fill (unused for this
  widget; reserved for future use).
- `enabled_get` — live enabled hook (same dirty-cached contract as
  `PresetRow`/`ActionButton`); a disabled swatch keeps its fill readable but
  dims its outline/label.
- `execute(context)` — identical to `ActionButton.execute` (deferred `bpy`
  import; `INVOKE_DEFAULT` so invoke-only and execute-only operators both
  work).

### Framework files touched (all additive)

- `ui/widgets/controls.py` — add the `Swatch` class.
- `ui/widgets/render.py`:
  - `_draw_swatch(control, rect, theme, dim, context, live)` — fills the cell
    (small inset) with the sRGB-encoded color, draws an outline, and the
    optional centered label. Disabled (`value is None` or `not enabled`):
    outline/label fade to `DISABLED_ALPHA`, fill stays readable.
  - `_row_height` — swatch rows use the control row height (label height +
    `ROW_PAD_CONTROL`); the current swatch is one such row, each recents row
    is one row.
  - `_control_min_width` — swatch returns a fixed minimum (so 4 recents fit a
    row); a `Row` of swatches already multiplies by column count.
  - `_draw_control` — dispatch `kind == "swatch"` to `_draw_swatch`.
- `ui/widgets/events.py` — in `_begin_gesture`, add
  `if control.kind == "swatch":` routing to the existing **button** path
  (`self._mode = "button"`; fire on release inside rect; one `ed.undo_push`;
  `mark_dirty`). No new gesture machinery.
- `ui/widgets/__init__.py` — export `Swatch` in `__all__` and the
  `from .controls import (...)` line.

## The widget: `widgets/object_color.py`

Hand-coded, following `widgets/edge_data.py` and `widgets/ccp_data_ops.py`.
bpy-import-guarded the same way (importable under plain pytest).

### Adapters (read `scene.IOPS`)

```
def _scene_props(context):  # IOPS scene property group, or None
def get_current(context) -> (rgba, False) | (None, False)
def get_recent(index):      # returns a get(context) closure for slot `index`
def has_selected_objects(context) -> bool
def has_active_object(context) -> bool
```

Getters re-resolve `scene.IOPS` from context on every call (never cached);
absence-safe (`None` → disabled control).

### Controls

```
Section("Current")
Swatch(get=get_current, op="iops.object_color_apply",
       enabled_get=has_selected_objects)              # click = Apply current
Row([ActionButton("Copy From Active",
                  op="iops.object_color_copy_from_active",
                  enabled_get=has_active_object),
     ActionButton("Apply", op="iops.object_color_apply",
                  enabled_get=has_selected_objects)])
Section("Recent")
Row([Swatch(get=get_recent(0), op="iops.object_color_apply_recent",
            kwargs={"index": 0}, enabled_get=has_selected_objects),
     ... indices 1, 2, 3])                             # recents row 1
Row([... indices 4, 5, 6, 7])                          # recents row 2
```

- Clicking the current swatch applies the current color to selected objects
  (same as the Apply button — convenient given the recents-focused layout).
- Recents apply on click via `apply_recent` (`index` kwarg); no reorder.
- `poll(context)` returns `True` — no mode gating. Selection/active-object
  state grays the relevant controls via `enabled_get` instead of collapsing
  the panel (same philosophy as `CCPDataOpsWidget`).

### Registration

`widgets/__init__.py` registers `ObjectColorWidget` alongside `EdgeDataWidget`
and `CCPDataOpsWidget` (in both the module-level register block and the
`register()` / `unregister()` hooks). The widget then:
- appears automatically in the prefs **Widgets** tab list (`iter_widgets`),
- gets an unbound toggle hotkey entry via `sync_toggle_kmis()` for the user
  to assign.

No operator changes — the three existing object-color operators are reused
verbatim.

## Refresh / data flow

Swatch values come from scene props, not selection, so they are always
present. They recompute lazily when the widget is marked dirty:
- `depsgraph_update_post` marks all visible widgets dirty (covers `obj.color`
  writes and scene-prop changes that tick the depsgraph),
- the interact modal calls `mark_dirty()` after a button/swatch gesture
  (covers recents reordering after an in-widget Apply),
- undo/redo handlers mark dirty + redraw.

External edits via the sidebar picker that do not tick the depsgraph refresh
on the next gesture/redraw — acceptable for a display swatch.

## Testing

`controls.py` is bpy-free (pytest imports it directly); `object_color.py`
keeps its framework import deferred so it can be standalone-loaded
(`importlib`, the `test_composed.py` pattern) and its pure adapters tested
against a fake context. `render.py` / `events.py` pull `gpu` / `blf` and are
**not** importable under plain pytest — the swatch draw and gesture routing
are verified manually in Blender.

bpy-free pytest (fake context object, mirroring `test_composed.py`'s
`rna_bool_adapter` tests):

- `tests/ui/widgets/test_controls.py` (new — `from ui.widgets.controls
  import Swatch`):
  - `Swatch.value()` caches and re-reads on `mark_dirty`;
  - `Swatch` with `set=None` never errors on the value path;
  - `Swatch.execute()` resolves `op`/`kwargs` through the shared
    `_invoke_operator` helper (patched, so no real `bpy` call).
- `tests/ui/widgets/test_object_color.py` (new — standalone-loaded module):
  - `get_current` / `get_recent` return `(color, False)` from a fake
    `scene.IOPS`, `(None, False)` when absent;
  - `has_selected_objects` / `has_active_object` reflect a fake context.

Manual Blender verification (no unit coverage — `gpu`/`blf` required):

- swatch fills render at the correct (sRGB-encoded) color, matching the
  sidebar panel's color fields;
- clicking the current swatch applies the current color; clicking a recent
  swatch applies that slot; Copy From Active / Apply behave as in the panel;
- controls gray out with no selection / no active object;
- panel drag + close + toggle hotkey work (inherited from the framework).

## Out of scope

- JSON composer (`widgets/composed.py`) support for swatch rows. This widget
  binds fixed scene props + specific operators, not the edge-adapter registry
  the composer targets. A `SWATCH` row type can be added later if desired.
- In-panel color editing / color picker popup (explicitly excluded).
- IMAGE_EDITOR placement (`space="VIEW_3D"` only, like the other widgets).
