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
| `space` | str | no | Editor space. Only `"VIEW_3D"` is supported; always forced to it. |
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
| `prop` | dotted RNA color path (FloatVector subtype COLOR) | **yes** | — |
| `op` | operator idname (must contain `.`) | **yes** | — |
| `op_kwargs` | object | no | `{}` |
| `label` | str | no | `""` (centered glyph on the fill) |

Color is read absence-safe (missing path → faded/disabled). subtype=COLOR
values are scene-linear and sRGB-encoded for display.

### `ROW` — horizontal container
| key | type | required | default |
|---|---|---|---|
| `cells` | list of the above row objects (no nested `ROW`) | **yes** | — (empty → dropped) |

Splits the content width equally among its cells. Nested `ROW` cells are
dropped. A **single-cell `ROW`** forces one control per line (overrides the
auto-merge of adjacent bare flipboxes).

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
