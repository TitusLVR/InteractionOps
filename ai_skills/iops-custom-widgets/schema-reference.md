# iOps Widget JSON — complete schema reference

Authoritative field reference for a widget definition file. Validated and
normalized by `widgets/composed.py:validate_def`, which returns
`(clean_def, errors)`: a bad **row** is dropped and reported but the rest of
the widget survives; a bad **definition** (not an object / no name) returns
`clean_def = None`. One file per widget, `<name>.json`, in the widgets
library folder (`composed.widgets_folder()`, default
`<script_path_user>/presets/IOPS/widgets`).

## Top-level keys

| key | type | required | notes |
|---|---|---|---|
| `version` | int | no | Schema version, always normalized to `1`. |
| `name` | str | **yes** | Registry key + filename stem. Sanitized: `<>:"/\|?*` → `_`. Empty name → whole def rejected. |
| `title` | str | no | Title-bar text. Defaults to `name`. |
| `space` | str or list of str | no | Editor space(s) the panel can anchor in: `"VIEW_3D"` and/or `"IMAGE_EDITOR"`. A string or a list is accepted; unknown values are dropped; defaults to `"VIEW_3D"`. A multi-space widget anchors to whichever listed editor it is toggled from (one at a time). |
| `switches` | object `{name: bool}` | no | Non-false defaults for local panel switches. See [Switches](#switches). |
| `rows` | list of row objects | no | The panel body, top to bottom. Non-list → empty + reported. |

## Row types

Every row is an object with a `type` key (case-insensitive, normalized to
upper). Unknown types are dropped + reported.

### `SECTION` — non-interactive header
| key | type | required | default |
|---|---|---|---|
| `label` | str | no | `""` |

### `SLIDER` — edge float attribute (drag)
| key | type | required | default |
|---|---|---|---|
| `target` | `"BEVEL"` \| `"CREASE"` | **yes** | — (other targets rejected) |
| `snap` | float ≥ 0 | no | `0.125` (0 disables snapping) |

### `PRESETS` — edge float attribute (preset buttons)
| key | type | required | default |
|---|---|---|---|
| `target` | `"BEVEL"` \| `"CREASE"` | **yes** | — |
| `values` | list of float in `[0,1]` | **yes** | — (empty/none → row dropped) |

### `FLIPBOX` — checkbox bound to a boolean
Needs **exactly one** of `target` / `prop` / `switch` (zero or two+ → dropped).
| key | type | required | default |
|---|---|---|---|
| `target` | `"SHARP"` \| `"SEAM"` \| `"FREESTYLE"` | one-of | — |
| `prop` | dotted RNA bool path (e.g. `scene.foo.bar`) | one-of | — |
| `switch` | local switch name | one-of | — |
| `label` | str | no | derived from target/prop/switch |

- `prop` is resolved against `context` per draw; **absence-safe** — a missing
  path renders the box **disabled**, never errors.
- `switch` reads/writes local per-widget state (see [Switches](#switches)).

### `BUTTON` — fires an operator on click
| key | type | required | default |
|---|---|---|---|
| `op` | operator idname (must contain `.`) | **yes** | — (no dot → dropped) |
| `op_kwargs` | object | no | `{}` |
| `label` | str | no | `op` |
| `role` | `"default"` \| `"error"` | no | `"default"` (error = red styling) |

Fires `op("INVOKE_DEFAULT", **op_kwargs)`.

### `SWATCH` — color display that fires an operator
Read-only color preview (no setter) that fires `op` on click, like a button.
| key | type | required | default |
|---|---|---|---|
| `prop` | dotted RNA color path (FloatVector subtype COLOR) | one of `prop`/`color` | — |
| `color` | list of 4 numbers `0..1` (literal RGBA) | one of `prop`/`color` | — |
| `op` | operator idname (must contain `.`) | **yes** | — |
| `op_kwargs` | object | no | `{}` |
| `label` | str | no | `""` (centered glyph on the fill) |
| `show_alpha` | bool | no | `false` (true → checker bg + honor the color's alpha) |

Color is read absence-safe (missing path → faded/disabled). subtype=COLOR
values are scene-linear and sRGB-encoded for display.

A SWATCH takes **exactly one** of `prop` (live RNA color, absence-safe) or
`color` (fixed literal RGBA). With `show_alpha: true` the swatch draws a
transparency checker and honors the color's alpha (alpha 0 = checker only,
1 = solid) — used for alpha-set buttons.

### `DROPDOWN` — enum RNA prop, edited in-overlay
| key | type | required | default |
|---|---|---|---|
| `prop` | dotted RNA path to an enum property | **yes** | — (empty/missing → dropped) |
| `label` | str | no | last segment of `prop` |
| `labels` | object `{identifier: display}` | no | `{}` (raw identifier shown) |
| `items_from` | str (registered provider name) | no | — (use RNA enum items) |
| `value_type` | (ignored — forced to `ENUM`) | no | `ENUM` |

Shows the current value (mapped through `labels` for a prettier display,
falling back to the raw identifier; `"—"` when the path is unresolvable).
Clicking opens an **in-overlay item list** drawn in the panel (no native popup);
move and click/drag-release to pick, Esc or a click-away closes. The selectable
items come from `labels` (its keys, in declared order) when declared; else from
an `items_from` **live provider** when set; else from the live enum's items
(`enum_items`, read only as a convenience — never required).

`items_from` names a provider registered in Python via
`widgets.composed.register_dropdown_items(name, provider)`, where
`provider(context) -> [(identifier, label), ...]`. Use it for **dynamic**
lists that `bl_rna` can't expose — e.g. a dynamic (items-callback)
`EnumProperty`'s items are empty via `bl_rna`, and a live list like
`bpy.data.images` isn't an enum at all. The DROPDOWN's `prop` (the stored
value) can then be a plain `StringProperty` holding the chosen identifier;
the provider supplies what's shown. Unknown/unregistered `items_from` falls
back to the RNA enum reader. (Example: the `uv_image_slots` widget uses
provider `"uv_images"` and binds each row to `window_manager.iops_uv_slot_N_name`.)
Absence-safe: a missing path renders disabled and the click no-ops.

### `INPUT` — string / number / angle RNA prop, edited in-overlay
| key | type | required | default |
|---|---|---|---|
| `prop` | dotted RNA path to a scalar property | **yes** | — (empty/missing → dropped) |
| `value_type` | `STRING` \| `INT` \| `FLOAT` \| `DEGREES` \| `RADIANS` | no | `STRING` |
| `label` | str | no | last segment of `prop` |
| `fmt` | Python format string for the value display | no | `"{}"` |

Shows `label` left-aligned and the current value (`fmt.format(value)`,
already in author space) right-aligned; `"—"` when the path is unresolvable.
Clicking starts an **in-overlay text caret** (no popup): typing is immediate, with
Left/Right/Home/End caret movement, Backspace/Delete, Ctrl+A select-all, Ctrl+C/X
copy/cut, Ctrl+V paste. Enter or a click-away commits; Esc cancels. Numbers parse
on commit (unparseable input is discarded, keeping the old value); `DEGREES` text
is read as degrees and stored as radians. Absence-safe (missing path → disabled).
See [Value types & angle handling](#value-types--angle-handling) for `DEGREES`/`RADIANS`.

### `BUTTONS` — radio row writing a preset value to an RNA prop
A segmented row of buttons, each holding one predefined value. **At most one is
active** at a time — the button whose value matches the live bound property.
Clicking a button writes its value (making it the new active one); mutual
exclusion is intrinsic (one prop value matches one option). When the live value
matches **no** option, **no** button is highlighted (an honest off-grid state —
a button is never force-highlighted).

Two modes, selected by `value_type`:

**Number mode** (`value_type` ∈ `INT` \| `FLOAT` \| `DEGREES` \| `RADIANS`, default `FLOAT`):
| key | type | required | default |
|---|---|---|---|
| `prop` | dotted RNA path to a number property | **yes** | — |
| `value_type` | `INT` \| `FLOAT` \| `DEGREES` \| `RADIANS` | no | `FLOAT` |
| `values` | list of numbers (author space) | **yes** | — (empty/none → row dropped) |
| `unit` | display suffix appended to each label | no | `""` (auto `"°"` for `DEGREES`) |
| `fmt` | Python format string per button label | no | `"{:g}"` |

`values` are **not** clamped to `[0,1]` (unlike `PRESETS`) — counters and angles
exceed 1. Active match uses a float epsilon (`abs(a-b) <= 1e-6`).

**Enum mode** (`value_type` = `ENUM`):
| key | type | required | default |
|---|---|---|---|
| `prop` | dotted RNA path to an enum property | **yes** | — |
| `value_type` | `ENUM` | **yes** | — |
| `items` | list of `identifier` strings or `[identifier, label]` pairs | **yes** | — (empty/none → row dropped) |

One button per declared item — the identifier list is **declared in JSON, never
introspected** from RNA. A bare string is used as both value and label; a
`[id, label]` pair sets a custom display. Active match uses string equality.

A `BUTTONS` row that ends up with no options (empty `values`/`items`) is dropped
and reported.

### `ROW` — horizontal container
| key | type | required | default |
|---|---|---|---|
| `cells` | list of the above row objects (no nested `ROW`) | **yes** | — (empty → dropped) |

Splits the content width equally among its cells. Nested `ROW` cells are
dropped. A **single-cell `ROW`** forces one control per line (overrides the
auto-merge of adjacent bare flipboxes). `INPUT`/`DROPDOWN`/`BUTTONS` lay out one
per row on their own, but also work inside a `ROW` cell (the cell splits width).
The new types are **not** part of the flipbox auto-merge (only adjacent
`FLIPBOX`es merge).

## Value types & angle handling

`DROPDOWN`, `INPUT`, and number-mode `BUTTONS` bind an **arbitrary scalar RNA
property** (not just edge data). The widget author declares how to interpret the
value with `value_type` — the binding **reads that declared type to coerce on
write and convert on read; it never introspects the live RNA property**.

`value_type` ∈ `STRING | INT | FLOAT | DEGREES | RADIANS | ENUM` (case-insensitive,
upper-cased on validation):

| `value_type` | write coercion (set) | read conversion (get) |
|---|---|---|
| `STRING` | `str(value)` | identity |
| `INT` | `int(value)` | identity |
| `FLOAT` | `float(value)` | identity |
| `DEGREES` | `math.radians(value)` | `math.degrees(value)` |
| `RADIANS` | `float(value)` | identity |
| `ENUM` | `str(value)` | identity |

**Angle handling — declared, never guessed.** Blender stores angle properties in
**radians**. The author states which unit their JSON numbers are in:

- `DEGREES` — author writes degrees in JSON; the binding converts deg→rad on
  write and rad→deg on read, so the in-overlay display, `BUTTONS` value matching,
  and `BUTTONS` labels all read **degrees** while storage stays radians. The
  end-user never sees radians. A `"°"` suffix is auto-appended to `BUTTONS`
  labels when `unit` is omitted for a `DEGREES` row.
- `RADIANS` — author's numbers already match storage; identity both ways.

The system **never guesses** the unit — declaring `DEGREES` or `RADIANS` is the
only way to opt in. `DEGREES` `INPUT` text is read as degrees and stored as
radians on commit; `BUTTONS` `DEGREES` values are authored in degrees. Scope is
rotation only — other units (length, time) use Blender's own display.

## In-overlay editing (no popups)

`DROPDOWN` and `INPUT` edit **directly in the panel** — there is no native popup.
The widget's interact modal owns the keyboard/mouse for the duration of the edit,
which is why typing starts immediately (no focus-click), the field closes on
commit/cancel, and nothing floats over the panel:

- **`INPUT`** — clicking starts a text caret in the field. Keys: printable chars
  insert at the caret; Backspace/Delete; Left/Right/Home/End (Shift extends the
  selection); Ctrl+A select-all; Ctrl+C/X copy/cut; Ctrl+V paste. **Enter** or a
  **click-away** commits (numbers parse then; bad input is discarded), **Esc**
  cancels. The commit is one undo step.
- **`DROPDOWN`** — clicking opens an item list below the field, drawn on top of
  the panel; hover highlights, click or drag-release picks, Esc/click-away closes.
  Items come from declared `labels` else the live enum.
- **`BUTTONS`** — already native to the overlay; writes the clicked option's value
  directly on press (one undo per gesture).

The caret/selection logic (`controls.TextEditState`) and the list geometry
(`controls.dropdown_item_rects` / `dropdown_index_at`) are pure and unit-tested.

## `show_if` (per top-level row)

Optional on any **top-level** row (NOT on `ROW` cells). An object; **all keys
ANDed** (no OR / NOT / nesting in v1). Invalid clause → dropped + reported,
row stays **always-visible**. A valid but unsatisfiable predicate just hides
the row (e.g. a missing `prop` path is falsy → hidden; this is normal, not
the error fallback).

| key | type | passes when |
|---|---|---|
| `mode` | str or list[str] | `context.mode` ∈ set |
| `object_type` | str or list[str] | `context.active_object.type` ∈ set (no active object → fails) |
| `selection` | `"verts"`\|`"edges"`\|`"faces"`\|`"objects"` | that kind has a selection (coarse) |
| `prop` | dotted RNA path | resolved value truthy, or `== equals` if present |
| `switch` | local switch name | switch truthy, or `== equals` if present |
| `equals` | any scalar | equality target for the clause's `prop` or `switch` |

`DROPDOWN`/`INPUT`/`BUTTONS` are **not** edge-bound, so a widget made only of them
polls always-visible (correct for an object-mode panel like the rename widget).
`show_if` applies to them at the row level exactly as it does to every other row.

## Switches

Local per-widget boolean state — lightweight panel UI state, NOT scene/RNA
data. Declared/seeded by the top-level `switches` map and/or referenced by a
`FLIPBOX` `switch` binding or a `show_if` `switch` key.

- Any referenced switch defaults to `false` unless the `switches` map lists it.
- A switch used only in `show_if` (no defining `FLIPBOX`) is valid — it stays
  at its default until set programmatically.
- State **persists** per-widget in the `widgets_state` prefs JSON (same file
  as panel position) and survives addon reload.

## Context vocabulary (for `show_if`)

**`mode`** — common `context.mode` values: `OBJECT`, `EDIT_MESH`,
`EDIT_CURVE`, `EDIT_SURFACE`, `EDIT_TEXT`, `EDIT_ARMATURE`, `EDIT_METABALL`,
`EDIT_LATTICE`, `POSE`, `SCULPT`, `PAINT_WEIGHT`, `PAINT_VERTEX`,
`PAINT_TEXTURE`. Note edit modes are type-specific (a mesh edits as
`EDIT_MESH`, a curve as `EDIT_CURVE`), so `mode` alone usually distinguishes
object types **in edit mode**; use `object_type` to distinguish them **in
`OBJECT` mode**.

**`object_type`** — `context.active_object.type`: `MESH`, `CURVE`, `SURFACE`,
`META`, `FONT`, `CURVES`, `POINTCLOUD`, `VOLUME`, `GREASEPENCIL`, `ARMATURE`,
`LATTICE`, `EMPTY`, `LIGHT`, `LIGHT_PROBE`, `CAMERA`, `SPEAKER`.

**`selection`** — `verts`/`edges`/`faces` are backed by `Mesh.total_*_sel`,
so they are **mesh-edit-mode only** (a curve in edit mode, or any object
mode, reports them as 0 → false). `objects` is `context.selected_objects`
non-empty (works in object mode).
