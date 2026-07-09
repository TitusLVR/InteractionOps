# Widget Scene Store — per-.blend widget data

**Date:** 2026-07-09
**Status:** Approved design, pending implementation plan

## Problem

Composed widgets have no way to store their data in the .blend file. The
UV image slots widget, for example, keeps its slot choices in
`WindowManager` StringProperties with `SKIP_SAVE` — session-only, gone on
file close. Widget authors who want per-file state have no supported
mechanism: `prop` paths can only bind properties that already exist in
Python-registered RNA.

## Goal

A **generic** mechanism: any composed widget (UGC JSON, no Python) can
declare values that are stored in the scene and therefore saved/loaded
with the .blend file. Nothing widget-specific ships in the addon; the UV
image slots widget is NOT migrated as part of this work (its author can
rewire its JSON later, on their own).

## Non-goals

- No migration of `operators/uv_image_slots.py` or any existing widget.
- Panel position / visibility / switches stay in addon prefs (global UI
  state — correct as-is). Only widget *data* is per-file.
- No per-file singleton beyond Scene: data is per-scene, which is the
  standard Blender approximation of per-file. Multi-scene files get one
  store per scene. Accepted.

## Storage — RNA CollectionProperty on Scene.IOPS

Canonical Blender pattern for dynamic per-file addon data. Saved in the
.blend automatically, clean per-key undo, inspectable from the Python
console, real RNA types, well-defined linking behavior.

```python
# prefs/addon_properties.py
class IOPS_WidgetDataKV(PropertyGroup):
    # .name = key (e.g. "slot_0")
    value: StringProperty(default="")

class IOPS_WidgetDataBlock(PropertyGroup):
    # .name = widget name (e.g. "uv_image_slots")
    entries: CollectionProperty(type=IOPS_WidgetDataKV)

class IOPS_SceneProperties(PropertyGroup):
    ...existing...
    widget_data: CollectionProperty(type=IOPS_WidgetDataBlock)
```

Registration order in `__init__.py` classes tuple: `IOPS_WidgetDataKV`,
then `IOPS_WidgetDataBlock`, before `IOPS_SceneProperties` (same rule as
`IOPS_RenameSettings`, `__init__.py:337`).

Values are stored as **strings**; interpretation is declared by the
control's `value_type` in the widget JSON — matching the existing
"declared, never guessed" schema philosophy (same as INPUT/BUTTONS
angle handling).

## API — `widgets/scene_store.py`

Thin module, bpy imports deferred to call time (keeps pytest importable
where pure). All access defensive: missing `Scene.IOPS` /
`widget_data` (addon half-registered) degrades to no-op/None.

```python
def get(context, widget, key, default=None) -> str | None
    # raw stored string; default when block/entry missing

def set(context, widget, key, value) -> None
    # lazy block+entry creation; stores str(value)

def delete(context, widget, key) -> bool
    # remove one entry; True if it existed

def purge(context, widget=None) -> int
    # widget given: remove that block; None: clear the whole store.
    # Returns number of blocks removed.
```

Lookup by collection key: `scene.IOPS.widget_data.get(widget)` /
`block.entries.get(key)` — native RNA collection name-lookup, no
custom resolver.

### Adapters (same file)

Get/set bundles in the shape `composed.py` adapters use
(`{"get": fn, "set": fn}`, get returns `(value, is_mixed)`):

```python
def store_value_adapter(widget, key, value_type="STRING")
def store_bool_adapter(widget, key)   # for FLIPBOX; "1"/"0" storage
```

Conversion rules (reuses `composed._coerce` / `_to_display` semantics):

| value_type | stored string | get returns (author space) |
|---|---|---|
| STRING / ENUM | as-is | str |
| INT | repr | int (unparseable → default) |
| FLOAT | repr | float |
| DEGREES | radians repr | degrees |
| RADIANS | radians repr | radians |
| bool (FLIPBOX) | "1" / "0" | bool |

**Absence semantics differ from `prop` binding deliberately:** a missing
block/entry means "not set yet", NOT "binding broken". get returns the
type's default (`""` / `0` / `0.0` / `False`) with the control enabled.
Only a missing `Scene.IOPS.widget_data` property itself (framework not
registered) returns `(None, False)` → control renders disabled, matching
prop-binding absence behavior.

## Schema — `"data"` binding key

Value controls accept `data: "<key>"` as an alternative to `prop`. The
key is scoped to the owning widget's block (widget name from the def),
so two widgets using `"data": "slot_0"` never collide.

| Control | binding rule after change |
|---|---|
| FLIPBOX | exactly one of `prop` / `target` / `switch` / `data` |
| DROPDOWN | exactly one of `prop` / `data` |
| INPUT | exactly one of `prop` / `data` |
| BUTTONS | exactly one of `prop` / `data` |

SECTION / SLIDER / PRESETS / BUTTON / SWATCH are unchanged (SWATCH's
`prop` is a read-only RNA color — a string store has nothing to offer
it; SLIDER/PRESETS bind edge adapters).

Example (what a rewired UV slots row would look like — illustration
only, not shipped):

```json
{ "type": "ROW", "cells": [
  { "type": "DROPDOWN", "data": "slot_0", "items_from": "uv_images", "label": "1" },
  { "type": "BUTTON", "label": "Set", "op": "iops.uv_image_slot_flip", "op_kwargs": { "slot": 0 } }
]}
```

### Validation (`composed._clean_row_body`)

- `data` value: non-empty string after strip; else row dropped with a
  reported error, same policy as a missing `prop`.
- Label default: `data` key (mirrors "last segment of prop").
- DROPDOWN with `data` keeps `value_type: "ENUM"` (forced, as today) and
  supports `items_from` unchanged. A `data` DROPDOWN with no `items_from`
  has no RNA enum to introspect — falls back to the empty-items path that
  already exists for unknown providers.
- Pure/pytest-covered like the rest of validation — new tests for each
  control type: data accepted, prop+data rejected, empty data rejected.

### Control building (`composed.build_controls`)

`build_controls` gains a `widget_name` parameter (passed by
`make_widget` from `wdef["name"]`; defaults to `""` for direct/pytest
callers). Rows with `data` build their control from
`scene_store.store_value_adapter(widget_name, key, value_type)` (or
`store_bool_adapter` for FLIPBOX) instead of `rna_value_adapter` /
`rna_bool_adapter`. Everything downstream (Dropdown/InputField/
ButtonGroup/FlipBox) is adapter-agnostic already.

The Dropdown/InputField `path` argument (used for identity/debug)
becomes `"<widget>:<key>"` for data bindings.

## Purge operator

`IOPS_OT_purge_widget_data` (`operators/purge_widget_data.py`):

- `widget: StringProperty` — empty = purge ALL widget data in the scene;
  non-empty = that widget's block only.
- `invoke_confirm` dialog (destructive, per-scene).
- Reports how many blocks were removed.
- Exposed as a button in the prefs **Widgets** tab (purge-all). Per-widget
  purge reachable via operator search / scripting; a widget author can
  also put it on a BUTTON row in their own widget JSON
  (`"op": "iops.purge_widget_data", "op_kwargs": {"widget": "my_widget"}`).

## Redraw / dirty behavior

Writes go through the existing widget interaction path, which already
marks widgets dirty and redraws; the depsgraph/undo handlers in
`ui/widgets/state.py` already re-sync values after undo. No new
handlers needed.

## Docs

- `ai_skills/iops-custom-widgets/schema-reference.md`: document `data`
  binding on the four control types + storage/typing semantics + the
  purge operator.
- New demo JSON in `presets/widgets_demo/` showing `data` binding
  (docs-only sample, like the existing demos).

## Testing

- Pure pytest: validation of `data` rows (accept/reject matrix),
  string↔typed conversion helpers.
- Live (Blender via reload harness): set values through a demo widget,
  save .blend, reload file, confirm values restored; purge operator
  clears; undo after a data write restores the prior value.

## Files touched

| File | Change |
|---|---|
| `prefs/addon_properties.py` | +`IOPS_WidgetDataKV`, +`IOPS_WidgetDataBlock`, +`widget_data` on `IOPS_SceneProperties` |
| `__init__.py` | class registration order |
| `widgets/scene_store.py` | new — API + adapters |
| `widgets/composed.py` | `data` in validation + `build_controls(widget_name=...)` |
| `operators/purge_widget_data.py` | new operator |
| prefs Widgets tab UI | purge-all button |
| `ai_skills/iops-custom-widgets/schema-reference.md` | schema docs |
| `presets/widgets_demo/` | demo JSON |
| tests | validation + conversion coverage |
