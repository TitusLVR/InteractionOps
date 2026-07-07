# Per-Channel Vertex Color Buttons (= / + / −) — Design

**Date:** 2026-07-01
**Status:** Approved (design), pending implementation plan

## Goal

Replace the three pure-fill R/G/B swatches in the Vertex Color widget with three
**per-channel rows**, one per color channel. Each row is `[swatch] [+] [−]`:

- **swatch** (`=`) — set that channel to 1.0 and zero the other two RGB channels
  (pure color); alpha preserved. Also serves as the row's color label.
- **`+`** — add 1.0 to that channel (clamped 0–1 → effectively 1.0); other RGB
  channels and alpha untouched.
- **`−`** — subtract 1.0 from that channel (clamped 0–1 → effectively 0.0);
  other RGB channels and alpha untouched.

Black/White swatches, the Alpha row, and the Preview toggle are unchanged.

## Components

### 1. New operator `iops.mesh_vertex_color_channel`

Added to `operators/assign_vertex_color.py` (same feature file).

**Properties:**
- `channel: EnumProperty` — items `("R","R",""), ("G","G",""), ("B","B","")`;
  default `"R"`. Maps to RGB index 0/1/2.
- `mode: EnumProperty` — items `("SET","=",""), ("ADD","+",""), ("SUB","-","")`;
  default `"SET"`.
- `amount: FloatProperty` — default `1.0` (the step used by ADD/SUB).
- `bl_options = {"REGISTER", "UNDO"}`; `poll` requires an active MESH object.

**Pure transform** — a module-level helper, applied per element:

```
_channel_transform(rgba, ch_idx, mode, amount) -> (r, g, b, a)
  SET: rgb = [0,0,0]; rgb[ch_idx] = 1.0        # pure channel; a preserved
  ADD: rgb[ch_idx] = min(1.0, rgb[ch_idx] + amount)
  SUB: rgb[ch_idx] = max(0.0, rgb[ch_idx] - amount)
  # alpha (a) is always carried through unchanged
```

**Element iteration** — read-modify-write (needed because +/− touch only one
channel), mirroring the existing `IOPS_OT_VertexColorAssign` structure so it
supports the same targets:
- Determines the active color attribute of the active object; if none exists,
  creates a default `"Color"` `FLOAT_COLOR` `POINT` attribute and makes it
  active (parity with the assign operator's `use_active_color` path).
- **Edit Mesh:** for each selected mesh object, via bmesh — POINT domain →
  `verts.layers.float_color`/`.color`, iterate selected verts; CORNER domain →
  `loops.layers.float_color`/`.color`, iterate loops of faces with any selected
  vert. For each element: `elem[layer] = _channel_transform(elem[layer], …)`.
- **Object Mode:** for each selected mesh, iterate the whole attribute data
  array (POINT per vertex, CORNER per loop): `d.color = _channel_transform(d.color, …)`.
- Handles `FLOAT_COLOR` and `BYTE_COLOR` like the assign op.

The existing `IOPS_OT_VertexColorAssign` is left untouched. Its
constant-color-to-all iteration and the new per-element RMW iteration are
similar but not identical (RMW vs constant write); this design accepts the
structural duplication rather than refactoring the verified assign operator.
`_channel_transform` is pure but, per the project convention for these bpy
operators, is verified live in Blender rather than via pytest.

**Registration:** import `IOPS_OT_VertexColorChannel` in `__init__.py`
(alongside `IOPS_OT_VertexColorAssign`, ~line 106-109) and add it to the
`classes` tuple (~line 440).

### 2. Widget layout (`vertex_color.json`)

Replace the single pure-fill R/G/B swatch ROW with three per-channel ROWs. Each
row: a literal-color `SWATCH` firing `mode=SET` for that channel, then two
`BUTTON`s `+` (`mode=ADD`) and `−` (`mode=SUB`):

```json
{"type": "ROW", "cells": [
  {"type": "SWATCH", "color": [1,0,0,1],
   "op": "iops.mesh_vertex_color_channel", "op_kwargs": {"channel": "R", "mode": "SET"}},
  {"type": "BUTTON", "label": "+", "op": "iops.mesh_vertex_color_channel", "op_kwargs": {"channel": "R", "mode": "ADD"}},
  {"type": "BUTTON", "label": "-", "op": "iops.mesh_vertex_color_channel", "op_kwargs": {"channel": "R", "mode": "SUB"}}
]},
{"type": "ROW", "cells": [
  {"type": "SWATCH", "color": [0,1,0,1],
   "op": "iops.mesh_vertex_color_channel", "op_kwargs": {"channel": "G", "mode": "SET"}},
  {"type": "BUTTON", "label": "+", "op": "iops.mesh_vertex_color_channel", "op_kwargs": {"channel": "G", "mode": "ADD"}},
  {"type": "BUTTON", "label": "-", "op": "iops.mesh_vertex_color_channel", "op_kwargs": {"channel": "G", "mode": "SUB"}}
]},
{"type": "ROW", "cells": [
  {"type": "SWATCH", "color": [0,0,1,1],
   "op": "iops.mesh_vertex_color_channel", "op_kwargs": {"channel": "B", "mode": "SET"}},
  {"type": "BUTTON", "label": "+", "op": "iops.mesh_vertex_color_channel", "op_kwargs": {"channel": "B", "mode": "ADD"}},
  {"type": "BUTTON", "label": "-", "op": "iops.mesh_vertex_color_channel", "op_kwargs": {"channel": "B", "mode": "SUB"}}
]}
```

The rest of the widget (unchanged) after these three rows:
- Black/White pure-fill swatch ROW (still `iops.mesh_assign_vertex_color` with
  `use_override_color`/`override_color`).
- `SECTION "Alpha"` + A0/A1 ROW (`show_if mode=EDIT_MESH`).
- `SECTION "Preview"` + `Preview VC` flipbox.

Row structure: `SECTION "Fill RGB"`, then R row, G row, B row, then the
Black/White row, then `SECTION "Alpha"` + Alpha row, then `SECTION "Preview"` +
flipbox. Total widget rows = 9 (Fill-RGB section + 3 channel rows + Black/White
row + Alpha section + Alpha row + Preview section + Preview flipbox).

The JSON lives in `B:\scripts\presets\iops\widgets\vertex_color.json` (user-data,
not repo-tracked — established convention).

## Error handling / edge cases

- No active mesh / no selection in Edit Mesh → operator creates the attribute if
  missing but writes nothing (no selected elements); no error.
- BYTE_COLOR values are 0–1 floats via the RNA `.color` accessor, so the same
  transform + clamp applies.
- `+`/`−` with `amount=1.0` are effectively "max"/"min" for the channel; the
  read-modify-write still preserves the other channels and alpha per element.
- SET zeros the two non-selected RGB channels but preserves alpha (matches the
  agreed "erase the other 2 channels" semantics; alpha is managed by A0/A1).

## Testing

- **bpy-free:** confirm the updated `vertex_color.json` validates
  (`composed.validate_def` → `errors == []`, 8 rows; the three RGB rows each
  have a SWATCH + two BUTTONs bound to `iops.mesh_vertex_color_channel` with the
  right `channel`/`mode` kwargs).
- **Live Blender 5.1.2:**
  - `=` (swatch) on R → selected verts become `(1,0,0, oldA)` (other RGB zeroed,
    alpha preserved); likewise G/B.
  - Starting from a mixed color, `+` on G sets G→1.0 leaving R/B/alpha; `−` on G
    sets G→0.0 leaving R/B/alpha.
  - Works in Edit Mesh (selection) and Object Mode (whole mesh); POINT domain.
  - Black/White, Alpha, Preview still function; widget renders 9 rows.

## Out of scope

Per-channel alpha +/−, a configurable step other than 1.0, channel isolation
preview, and any change to the Black/White swatches, Alpha row, or Preview
toggle. The `amount` property exists for completeness but the widget always
sends the default 1.0.
