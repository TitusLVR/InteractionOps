# Widget Input Controls — Dropdown, Input Field, Button Group

**Date:** 2026-06-25
**Status:** Design — approved for spec review
**Branch:** (to be created) `feat/widget-input-controls`

## Summary

Extend the JSON-composed GPU widget palette with three new control types
that bind **arbitrary RNA properties** (not just edge data):

- **DROPDOWN** — an enum property, edited via a borderless native popup.
- **INPUT** — a number (int/float) or string property, edited via a
  borderless native popup, live-apply.
- **BUTTONS** — a segmented row of buttons that writes directly to the
  bound property. Two modes: a list of preset *values* written to a
  number prop, or one button per item of a true RNA enum.

The driving use case and integration test is a **Rename Objects** widget
modeled on `iops.object_name_from_active`, backed by new persistent
settings on `scene.IOPS`.

## Motivation

The current palette (Section / Slider / Presets / FlipBox / Button /
Swatch / Row) covers booleans, floats, and operator triggers. It cannot
expose enums (named choices), free text/number entry, or a discrete
"pick one of N values" selector. Real widgets — a rename panel, a
shading-angle switcher, a units selector — need these.

The architectural constraint: the widget panel is a **GPU overlay**
drawn POST_PIXEL, not native Blender UI. There is no in-overlay text
caret or popup menu. So dropdowns and input fields cannot be rendered or
handled in-overlay; on click they must delegate to a tiny Blender
operator that hosts native UI in a popup. Button groups, by contrast,
are fully native to the overlay (PresetRow generalized).

## Binding model

All three controls bind an **arbitrary dotted RNA path** resolved against
`context` (e.g. `object.data.use_auto_smooth`,
`scene.IOPS.rename.pattern`), generalizing the existing
`rna_bool_adapter` / `rna_color_adapter` pattern.

- **Scalar, single-owner.** One resolved owner; `is_mixed` is always
  `False`. (Unlike the edge adapters, which aggregate across the
  selection. RNA props live on one datablock.)
- **Absence-safe.** A missing/unresolvable path returns `(None, False)`
  → the control renders disabled and writes/edits no-op. Same contract
  as the prop-flipbox and swatch.
- **Pure closures.** The adapter and the enum-items getter are
  `getattr`-only closures with no `bpy` import, so they live in
  `widgets/composed.py` alongside `rna_bool_adapter` and stay
  pytest-coverable with fake objects.

### Value type is declared in JSON, the adapter just reads it

The widget author declares the value type in the JSON row via
`value_type`; the adapter reads that declared type to coerce on write and
convert on read. We deliberately **do not** introspect the live RNA
property (`owner.bl_rna.properties[attr].type/.unit/.enum_items`) — that
auto-detection is fragile, and it forces fake-`bl_rna` scaffolding into
the pure tests. Declaring the type is one short field and keeps the
adapter trivial.

`value_type` ∈ `STRING | INT | FLOAT | DEGREES | RADIANS | ENUM`:

| value_type | write coercion (set) | read conversion (get) |
| --- | --- | --- |
| `STRING` | `str(value)` | identity |
| `INT` | `int(value)` | identity |
| `FLOAT` | `float(value)` | identity |
| `DEGREES` | `math.radians(float(value))` | `math.degrees(value)` |
| `RADIANS` | `float(value)` | identity |
| `ENUM` | `str(value)` | identity |

Blender stores angle properties in **radians**. The author states which
unit their JSON numbers are in — `DEGREES` (convert) or `RADIANS`
(identity) — so the system **never guesses**. `DEGREES` is the only
converting type; with it the end-user only ever sees degrees (in-overlay
and in the native popup), while storage stays radians. Enum item lists for
BUTTONS are likewise declared in JSON (`items`), not introspected.

### New adapter helpers (composed.py)

```python
def _coerce(value_type, value):
    """Author space -> storage space, by declared type. Pure stdlib."""
    if value_type == "INT":      return int(value)
    if value_type == "FLOAT":    return float(value)
    if value_type == "DEGREES":  return math.radians(float(value))
    if value_type == "RADIANS":  return float(value)
    return str(value)            # STRING / ENUM

def _to_display(value_type, value):
    """Storage space -> author space. Only DEGREES converts."""
    return math.degrees(value) if value_type == "DEGREES" else value

def rna_value_adapter(path, value_type="STRING"):
    """get/set bundle for an arbitrary RNA scalar resolved against
    context. Absence-safe. Scalar, so is_mixed is always False. Works in
    AUTHOR/DISPLAY space: get() returns the author-space value (degrees
    when value_type is DEGREES), set() coerces back to storage space
    (radians for DEGREES) by the DECLARED value_type — no RNA
    introspection."""
    def get(context):
        owner, attr = resolve_rna_owner(context, path)
        if owner is None or not hasattr(owner, attr):
            return (None, False)
        return (_to_display(value_type, getattr(owner, attr)), False)
    def set(context, value):
        owner, attr = resolve_rna_owner(context, path)
        if owner is not None and hasattr(owner, attr):
            setattr(owner, attr, _coerce(value_type, value))
    return {"get": get, "set": set}
```

`_coerce` / `_to_display` are pure (stdlib `math` only) and pytest-covered
with a plain fake object holding a settable attribute — no `bl_rna`
scaffolding needed.

### Angle handling — declared, obscured from the end-user

Blender stores angle properties in **radians** but displays degrees. The
author opts in with `value_type: "DEGREES"` (or `RADIANS` to author in raw
radians); everything downstream is then in the author's unit and the
end-user, for `DEGREES`, never sees radians:

- Author writes **degrees** in JSON:
  `{"type": "BUTTONS", "prop": "...angle", "value_type": "DEGREES",
  "values": [0, 15, 45, 60, 90, 180]}`. A `"°"` suffix is auto-appended in
  the label when `unit` is omitted for a `DEGREES` row.
- For `DEGREES`, `rna_value_adapter` converts deg→rad on write and rad→deg
  on read, so BUTTONS value matching/highlight, BUTTONS labels, and the
  INPUT field's in-overlay display all read degrees uniformly. `RADIANS`
  is identity (the author's numbers already match storage).
- The native edit popup (`iops.widget_edit_prop` → `layout.prop`) edits
  the raw prop directly and is **independently correct** — Blender shows
  degrees and converts natively. It never touches the adapter, so no
  double conversion.

Scope is rotation only; other units use Blender's own display.

## Control classes (ui/widgets/controls.py — bpy-free)

Each new class follows the established pattern: a `kind` string for
render/event dispatch, `interactive = True`. They are plain `Control`
subclasses (each holds a `get`/`set` and reads the getter **live each
draw**, not via the `_ValueControl` dirty cache) — because their value
can be changed by the external native popup, which never triggers the
widget's `mark_dirty`. A live scalar `getattr` per draw is cheap, and
these widgets always poll in-context (RNA, not edge data), so the draw
path is always `live=True`.

### `Dropdown(Control)` — `kind = "dropdown"`
- `__init__(self, get, path, labels=None, label="")`
- Holds `path` (the dotted RNA path, passed to the edit operator) and an
  optional `labels` dict (`{identifier: display}`, declared in JSON) for a
  prettier current-value display.
- `display(self, context)` → `labels.get(value, value)` (the raw enum
  identifier when no label is declared), or `"—"` when value is None. No
  RNA introspection — the editing UI is the native popup, which lists all
  items itself.
- `execute(self, context)` → fires `iops.widget_edit_prop(path=self.path)`
  via `_invoke_operator`, mirroring `ActionButton.execute` so the existing
  `"button"` release path is reused. Not written in-overlay.

### `InputField(Control)` — `kind = "input"`
- `__init__(self, get, path, fmt="{}", label="")`
- `display(self, context)` → `fmt.format(value)` (number, already in
  author space — degrees for an angle) or the string value, `"—"` when
  None.
- `execute(self, context)` → fires `iops.widget_edit_prop(path=self.path)`,
  same as Dropdown.

### `ButtonGroup(Control)` — `kind = "buttons"`
Radio-button behavior: an arbitrary author-defined set of buttons, each
holding one predefined value; **at most one is active** at a time — the
one whose value matches the live bound property. Clicking a button writes
its value, making it the new active one. Mutual exclusion is intrinsic
(one prop value matches one option).

- `__init__(self, get, set, options, enabled_get=None)`
- `options` is a normalized list of `(value, label)` pairs, built at
  construction from the declared JSON. Number mode: value = the coerced
  number (author space), label = `fmt.format(value) + unit`. Enum mode:
  value = the identifier, label = the declared display (or the identifier).
- `active_index(self, context)` → index of the option matching the live
  value (number: `abs(a-b) <= 1e-6`; enum/string: `==`), or **-1 when the
  value matches no option** → no button highlighted (an honest "off-grid"
  state; we do not force a button on). Read live each draw.
- `index_at(mx, rect_x, rect_w)` → reuses `preset_index` (shared cell
  math, identical to PresetRow).
- `write(self, context, value)` → `self.set(context, value)`.

Pure helper added to `controls.py` and pytest-covered:
`button_group_options(values, items, fmt, unit)` — normalizes either the
number `values` list or the declared enum `items` list into `(value,
label)` pairs. Reuses `preset_cell_rects`/`preset_index`.

## Edit operator — `iops.widget_edit_prop`

A tiny operator hosting native RNA editing in a borderless popup. Serves
both DROPDOWN and INPUT.

```python
class IOPS_OT_WidgetEditProp(bpy.types.Operator):
    bl_idname = "iops.widget_edit_prop"
    bl_options = {"REGISTER", "UNDO"}
    path: StringProperty()        # dotted RNA path resolved vs context

    def invoke(self, context, event):
        owner, attr = resolve_rna_owner(context, self.path)
        if owner is None or not hasattr(owner, attr):
            self.report({"WARNING"}, f"IOPS: cannot resolve '{self.path}'")
            return {"CANCELLED"}
        return context.window_manager.invoke_popup(self, width=220)

    def draw(self, context):
        owner, attr = resolve_rna_owner(context, self.path)
        if owner is not None and hasattr(owner, attr):
            self.layout.prop(owner, attr)   # native widget, live-apply

    def execute(self, context):
        return {"FINISHED"}
```

- `invoke_popup` → borderless, no OK button; the native widget edits the
  real datablock directly, so edits apply live and click-away dismisses.
- An enum prop renders as the native dropdown button (one extra click
  opens the item list); a number prop is a draggable/typeable field; a
  string prop is a text field.
- Native field edits push their own undo step — the widget's interact
  modal does **not** add one for dropdown/input gestures.

Lives in `ui/widgets/events.py` alongside the existing widget operators;
added to its `classes` tuple.

## Schema additions (widgets/composed.py)

`ROW_TYPES` gains `"DROPDOWN"`, `"INPUT"`, `"BUTTONS"`.

`_clean_row_body` branches:

`value_type` (declared per row) ∈ `STRING` | `INT` | `FLOAT` | `DEGREES`
| `RADIANS` | `ENUM`, upper-cased on validation like `type`/`target`.

```jsonc
// DROPDOWN — enum prop (value_type forced ENUM). Optional labels map.
{"type": "DROPDOWN", "prop": "scene.IOPS.rename.order", "label": "Order",
 "labels": {"DISTANCE": "By Distance", "SELECTION": "By Selection"}}

// INPUT — string / number / angle
{"type": "INPUT", "prop": "scene.IOPS.rename.pattern",
 "value_type": "STRING", "label": "Pattern"}
{"type": "INPUT", "prop": "scene.IOPS.rename.trim_prefix",
 "value_type": "INT", "label": "Prefix"}

// BUTTONS — number presets (write to a number prop)
{"type": "BUTTONS", "prop": "scene.IOPS.rename.counter_digits",
 "value_type": "INT", "values": [2, 3, 4]}

// BUTTONS — angle presets, authored in degrees (stored radians)
{"type": "BUTTONS", "prop": "object.data....angle",
 "value_type": "DEGREES", "values": [0, 15, 45, 60, 90, 180]}

// BUTTONS — enum items (declared in JSON, identifier or [id, label])
{"type": "BUTTONS", "prop": "space_data.shading.type", "value_type": "ENUM",
 "items": ["SOLID", "MATERIAL", ["RENDERED", "Render"]]}
```

Validation rules (each returns `(out, error)`, drop-and-report on
failure, consistent with existing rows):

- **DROPDOWN**: requires non-empty `prop`. `value_type` forced to `ENUM`.
  Optional `label` (defaults to the last path segment) and `labels`
  (identifier→display map for the current-value display).
- **INPUT**: requires non-empty `prop`. Optional `value_type` (default
  `STRING`), `label` (default = last segment), `fmt` (default `"{}"`).
- **BUTTONS**: requires non-empty `prop`. If `value_type` is `ENUM` →
  enum mode: requires a non-empty `items` list (identifiers, or
  `[id, label]` pairs — declared, never introspected). Else → number mode:
  `value_type` defaults to `FLOAT` (or `INT`/`DEGREES`/`RADIANS`); requires
  a non-empty `values` list, coerced to floats and **not** clamped to
  [0,1] (unlike PRESETS — counters/angles exceed 1); `values` are in
  author space (degrees for `DEGREES`). Optional `unit` (display suffix;
  for `DEGREES`, `"°"` is auto-applied when `unit` is omitted) and `fmt`
  (default `"{:g}"`). A BUTTONS row that ends up with no options is
  dropped-and-reported.

`build_controls.one()` constructs the three classes, wiring
`rna_value_adapter(prop, value_type)` for get/set and passing declared
`items`/`labels` straight through (no RNA introspection). These are
**not** edge-bound, so `_binds_edges` stays False and the widget polls
"always visible" (correct for an object-mode rename widget). `show_if`
already applies at the row level via `build_controls` — no extra work.

Merge behavior: the new types are **not** merged into flipbox runs (only
adjacent FLIPBOXes merge). They lay out one per row unless wrapped in a
`ROW` (which already splits width among cells) — so `INPUT`/`DROPDOWN`
work inside a `ROW` cell too.

## Render (ui/widgets/render.py)

New `kind` branches in `_draw_control`, `_row_height`,
`_control_min_width`:

- **dropdown**: outlined box, left-aligned current display text, a `▾`
  glyph right-aligned. Disabled fade when value is None. Min width =
  widest item name + glyph + insets.
- **input**: outlined box, left-aligned `label`, right-aligned current
  value text (the editable region). Disabled fade when None. Min width =
  label + value + insets.
- **buttons**: identical cell layout to presets (`preset_cell_rects`),
  each cell outlined + centered label; the **active** cell (from
  `active_index`) gets the filled/active-value highlight (reuse the
  pressed-tint fill from `_draw_button`). Min width = sum of label widths
  + gaps.

Colors map to existing theme roles (`Role.LINE` outline,
`Role.HUD_LABEL` text, `Role.HUD_ACTIVE_VALUE` active fill/glyph) — no
new theme prefs, consistent with the rest of the panel.

## Events (ui/widgets/events.py)

In `_begin_gesture`, new dispatch by `control.kind`:

- **dropdown / input**: treat like a button — arm `_press_cell`, mode
  `"button"`, fire on **release-inside**. On fire, call
  `iops.widget_edit_prop(path=control.path)` via `_invoke_operator`
  (INVOKE_DEFAULT → the popup appears at the cursor). **No** widget
  `undo_push` (the native edit pushes its own). Add an `execute()` on the
  Dropdown/InputField controls that invokes the editor, mirroring
  `ActionButton.execute` so the existing `"button"` release path is
  reused unchanged.
- **buttons**: like PRESETS — resolve `index_at`, `write` the option
  value on press, mark dirty, mode `"release_undo"` (one `undo_push` on
  release). Gap clicks swallow.

No changes to the modal loop, drag, or close handling.

## Part 2 — Rename Objects widget

### Persistent settings — `IOPS_RenameSettings` (prefs/addon_properties.py)

A new `PropertyGroup` pointed to by `scene.IOPS.rename`
(`PointerProperty` added to `IOPS_SceneProperties`):

| Prop | Type | Default | Maps to op prop |
| --- | --- | --- | --- |
| `new_name` | String | `""` | `new_name` |
| `pattern` | String | `[N]_[C]` | `pattern` |
| `counter_digits` | Int (2–10) | `2` | `counter_digits` |
| `counter_shift` | Bool | `True` | `counter_shift` |
| `order` | Enum `DISTANCE`/`SELECTION` | `DISTANCE` | → `use_distance` |
| `rename_active` | Bool | `True` | `rename_active` |
| `rename_mesh_data` | Bool | `True` | `rename_mesh_data` |
| `rename_linked` | Bool | `False` | `rename_linked` |
| `copy_to_clipboard` | Bool | `True` | `copy_to_clipboard` |
| `use_trim` | Bool | `False` | `use_trim` |
| `trim_prefix` | Int (0–100) | `0` | `trim_prefix` |
| `trim_suffix` | Int (0–100) | `0` | `trim_suffix` |

Registered with the other `*_widget_composer_classes`/scene props in
`__init__.py`; `del`-ed on unregister.

### Apply operator — `iops.object_name_from_active_apply`

Reads `scene.IOPS.rename.*`, maps `order` → `use_distance`, sets
`active_name` from `context.view_layer.objects.active.name`, then calls
`bpy.ops.iops.object_name_from_active('EXEC_DEFAULT', **kwargs)`. The
existing operator already runs headless under `EXEC_DEFAULT` (its
`invoke` only pre-fills names), so **no refactor** of the rename logic is
needed — one source of truth stays in `object_name_from_active.py`.
`poll`: at least one selected object with an active object.

### Widget JSON — `B:\scripts\presets\iops\widgets\rename_objects.json`

```jsonc
{
  "version": 1,
  "name": "rename_objects",
  "title": "Rename Objects",
  "space": "VIEW_3D",
  "rows": [
    {"type": "SECTION", "label": "Name"},
    {"type": "INPUT",  "prop": "scene.IOPS.rename.new_name", "value_type": "STRING", "label": "New Name"},
    {"type": "INPUT",  "prop": "scene.IOPS.rename.pattern",  "value_type": "STRING", "label": "Pattern"},
    {"type": "SECTION", "label": "Counter"},
    {"type": "BUTTONS", "prop": "scene.IOPS.rename.counter_digits", "value_type": "INT", "values": [2, 3, 4]},
    {"type": "FLIPBOX", "prop": "scene.IOPS.rename.counter_shift", "label": "+1 Shift"},
    {"type": "SECTION", "label": "Order"},
    {"type": "DROPDOWN", "prop": "scene.IOPS.rename.order", "label": "Order",
     "labels": {"DISTANCE": "By Distance", "SELECTION": "By Selection"}},
    {"type": "FLIPBOX", "prop": "scene.IOPS.rename.rename_active",    "label": "Include Active"},
    {"type": "FLIPBOX", "prop": "scene.IOPS.rename.rename_mesh_data", "label": "Mesh Data"},
    {"type": "FLIPBOX", "prop": "scene.IOPS.rename.rename_linked",    "label": "Linked"},
    {"type": "BUTTON",  "label": "Apply", "op": "iops.object_name_from_active_apply"}
  ]
}
```

Exercises every new control type (INPUT string, BUTTONS int presets,
DROPDOWN enum) plus existing prop-flipboxes and a button, against live
RNA. Placed in the user's configured widgets folder so `load_all()` picks
it up on reload.

## Testing

**Pure pytest** (no Blender), extending the existing suites:

- `tests/ui/widgets/test_controls.py`: construct `Dropdown`, `InputField`,
  `ButtonGroup`; `button_group_options` normalization (number `values` +
  enum `items`, incl. `[id, label]` pairs); `active_index` matching (float
  epsilon, enum equality); `display`/`labels` fallbacks; `index_at` via
  `preset_index`.
- `tests/ui/widgets/test_composed.py`: `validate_def` accepts the three
  new row types and rejects/repairs bad ones (missing `prop`, empty
  `values`, ENUM-BUTTONS without `items`, bad `value_type`);
  `_coerce`/`_to_display` for every `value_type` including the `DEGREES`
  round-trip (`_coerce("DEGREES", 90) ≈ math.radians(90)`,
  `_to_display("DEGREES", radians(90)) ≈ 90`) and `RADIANS` identity;
  `rna_value_adapter` get/set against a **plain** fake object (a settable
  attribute, no `bl_rna`); `build_controls` produces the right `kind`s,
  threads `value_type`/`items`/`labels`, and is not edge-bound.

**Live verification in Blender 5.1.2** (MCP), after the build:
1. Reload the addon; confirm `rename_objects.json` loads with no errors.
2. Toggle the widget; verify INPUT/DROPDOWN/BUTTONS render and the active
   button highlights.
3. Click each: input popup edits `new_name`/`pattern`; dropdown switches
   `order`; button row sets `counter_digits`.
4. Select objects, click Apply; confirm rename matches the operator's
   own redo-panel result.
5. Confirm `show_if`, drag, close, and out-of-context collapse still work.

## Documentation

- `ai_skills/iops-custom-widgets/schema-reference.md`: add DROPDOWN,
  INPUT, BUTTONS row specs (fields, defaults, examples).
- `ai_skills/iops-custom-widgets/SKILL.md`: note the new types, the
  arbitrary-RNA binding, and that dropdown/input delegate to a native
  popup (no in-overlay editing).
- `widgets/composed.py` module docstring: extend the block palette list.

## Out of scope (YAGNI)

- Multi-element / multi-object aggregation for RNA props (scalar only).
- OR / nested `show_if` (unchanged from the conditional-rendering work).
- A direct-at-cursor enum menu (the borderless popup's native dropdown is
  enough; revisit only if the extra click proves annoying).
- Unit conversion beyond rotation/angles (length, time, etc.) — Blender's
  own unit display covers those; only radian↔degree needs special-casing.
- IMAGE_EDITOR-space widgets (still VIEW_3D only).
- In-prefs visual editor rows for the new types (widgets are authored as
  JSON, per the existing decision).

## Build order

1. `rna_value_adapter` + `_coerce` / `_to_display` (composed.py).
2. `Dropdown` / `InputField` / `ButtonGroup` + pure helpers (controls.py).
3. Schema validation + `build_controls` wiring (composed.py).
4. `iops.widget_edit_prop` operator (events.py).
5. Render + events dispatch (render.py, events.py).
6. Pytest for 1–3.
7. `IOPS_RenameSettings` + Apply op + registration.
8. `rename_objects.json` + live-verify in Blender.
9. Docs + skill.

## Addendum (2026-06-25) — in-overlay editing supersedes the popup

User feedback on the first cut: the native `invoke_popup` for DROPDOWN/INPUT
was wonky — it didn't take keyboard focus immediately, didn't close when done,
and floated over the panel. **Editing now happens in-overlay**, which fixes all
three (the interact modal owns input, so typing is immediate, the field closes
on commit/cancel, and nothing floats). `iops.widget_edit_prop` is **removed**.

- **INPUT** → modal mode `text_edit`. A pure `controls.TextEditState` (caret +
  selection) backs it: printable insert, Backspace/Delete, Left/Right/Home/End
  (Shift extends), Ctrl+A/C/X/V, Enter/click-away commit, Esc cancel. Commit
  writes the buffer through the bound adapter (which coerces to the prop type —
  unparseable numbers are discarded); one undo per edit.
- **DROPDOWN** → modal mode `dropdown_open`. An in-overlay list draws below the
  field (`controls.dropdown_item_rects` / `dropdown_index_at`, shared by render +
  events). Items come from declared `labels` else the live enum (`rna_enum_items`,
  a getattr-only convenience). Click/drag-release picks; Esc/click-away closes.
- The one-gesture "zero idle cost" property holds except while a field is
  actively being edited (the modal stays open until commit/cancel).
- `TextEditState` and the list geometry are pure and unit-tested; the live
  plumbing (items/write/display, operator removal) was verified in Blender 5.1.2.
  The keystroke/click *gestures* themselves are covered by the unit tests, not a
  simulated live keypress (MCP can't inject modal input events).
