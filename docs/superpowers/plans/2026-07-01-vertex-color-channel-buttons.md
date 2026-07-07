# Per-Channel Vertex Color Buttons (= / + / −) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an `iops.mesh_vertex_color_channel` operator (set/add/subtract one R/G/B channel, alpha preserved) and rewire the Vertex Color widget so each channel is a `[colored swatch =] [+] [−]` row.

**Architecture:** A new operator in `operators/assign_vertex_color.py` applies a pure per-element transform (`_channel_transform`) via read-modify-write over the active color attribute, mirroring the existing assign operator's edit/object + POINT/CORNER + float/byte iteration. The widget JSON replaces the pure-fill R/G/B swatch row with three per-channel rows. The existing assign operator is untouched.

**Tech Stack:** Blender 5.1.2 `bpy`/`bmesh`; the iOps GPU widget framework (JSON defs). No pytest for the bpy operator (verified live, per project convention); a bpy-free JSON validation check only.

## Global Constraints

- Target Blender **5.1.2**.
- SET (`=`): chosen channel → 1.0, other two RGB channels → 0.0, **alpha preserved**.
- ADD (`+`): `chosen = min(1.0, chosen + amount)`; other RGB channels and alpha untouched.
- SUB (`−`): `chosen = max(0.0, chosen − amount)`; other RGB channels and alpha untouched.
- `amount` default `1.0`; the widget always sends the default.
- Existing `IOPS_OT_VertexColorAssign` and `IOPS_OT_VertexColorAlphaAssign` must be unchanged.
- Support the same targets as the assign op: Edit Mesh (selected verts / corners of faces touching a selected vert) and Object Mode (whole attribute); POINT and CORNER domains; FLOAT_COLOR and BYTE_COLOR.
- The widget JSON lives in `B:\scripts\presets\iops\widgets\vertex_color.json` (NOT repo-tracked).
- `widgets/composed.py` stays bpy-free; `python -m pytest tests -q` shows no NEW failures (one pre-existing unrelated `test_polygon_match` failure is known).
- Live Blender verification runs through the `blender` MCP (controller), addon reloaded via disable → purge `sys.modules['InteractionOps.*']` → enable.

---

### Task 1: `iops.mesh_vertex_color_channel` operator

**Files:**
- Modify: `operators/assign_vertex_color.py` (append the pure helper + new operator class after `IOPS_OT_VertexColorAlphaAssign`, at end of file)
- Modify: `__init__.py` (import ~line 106-109; classes tuple ~line 440)

**Interfaces:**
- Consumes: nothing.
- Produces: operator `iops.mesh_vertex_color_channel` with `channel` (enum R/G/B), `mode` (enum SET/ADD/SUB), `amount` (float, default 1.0); module-level `CHANNEL_INDEX` dict and `_channel_transform(rgba, ch_idx, mode, amount)`.

bpy-dependent — verified live by the controller (no pytest).

- [ ] **Step 1: Append the helper + operator to `operators/assign_vertex_color.py`**

At the END of the file (after the `IOPS_OT_VertexColorAlphaAssign` class), add:

```python

CHANNEL_INDEX = {"R": 0, "G": 1, "B": 2}


def _channel_transform(rgba, ch_idx, mode, amount):
    """Pure per-element transform for one RGB channel; alpha always preserved.

    SET: zero all RGB, set the chosen channel to 1.0 (pure color).
    ADD: chosen = min(1.0, chosen + amount); other channels unchanged.
    SUB: chosen = max(0.0, chosen - amount); other channels unchanged.
    """
    r, g, b, a = rgba[0], rgba[1], rgba[2], rgba[3]
    rgb = [r, g, b]
    if mode == "SET":
        rgb = [0.0, 0.0, 0.0]
        rgb[ch_idx] = 1.0
    elif mode == "ADD":
        rgb[ch_idx] = min(1.0, rgb[ch_idx] + amount)
    elif mode == "SUB":
        rgb[ch_idx] = max(0.0, rgb[ch_idx] - amount)
    return (rgb[0], rgb[1], rgb[2], a)


class IOPS_OT_VertexColorChannel(bpy.types.Operator):
    """Set (=), add (+) or subtract (-) a single R/G/B vertex-color channel on
    the selection; other channels and alpha are preserved (SET zeros the other
    two RGB channels)."""

    bl_idname = "iops.mesh_vertex_color_channel"
    bl_label = "Vertex Color Channel"
    bl_options = {"REGISTER", "UNDO"}

    channel: bpy.props.EnumProperty(
        name="Channel",
        items=[("R", "R", "Red"), ("G", "G", "Green"), ("B", "B", "Blue")],
        default="R",
    )
    mode: bpy.props.EnumProperty(
        name="Mode",
        items=[("SET", "=", "Set channel to 1.0, zero the other two RGB channels"),
               ("ADD", "+", "Add amount to the channel (clamped 0-1)"),
               ("SUB", "-", "Subtract amount from the channel (clamped 0-1)")],
        default="SET",
    )
    amount: bpy.props.FloatProperty(name="Amount", default=1.0)

    @classmethod
    def poll(cls, context):
        return context.object and context.object.type == "MESH"

    def execute(self, context):
        ch = CHANNEL_INDEX[self.channel]
        sel = [o for o in context.selected_objects if o.type == "MESH"]
        if context.object and context.object.type == "MESH" and context.object not in sel:
            sel.append(context.object)
        if not sel:
            return {"CANCELLED"}

        # Ensure the active object has an active color attribute (create a
        # default one if missing), then propagate its name/type/domain.
        me0 = context.object.data
        if me0.color_attributes.active_color is None:
            me0.color_attributes.new("Color", "FLOAT_COLOR", "POINT")
            me0.color_attributes.active_color = me0.color_attributes["Color"]
        active = me0.color_attributes.active_color
        attr_name, attr_domain, attr_type = active.name, active.domain, active.data_type

        for obj in sel:
            if attr_name not in obj.data.color_attributes:
                obj.data.color_attributes.new(attr_name, attr_type, attr_domain)
            obj.data.color_attributes.active_color = obj.data.color_attributes[attr_name]

        if context.mode == "EDIT_MESH":
            for obj in sel:
                bm = bmesh.from_edit_mesh(obj.data)
                if attr_domain == "POINT":
                    layers = (bm.verts.layers.float_color if attr_type == "FLOAT_COLOR"
                              else bm.verts.layers.color)
                    if attr_name not in layers:
                        continue
                    lyr = layers[attr_name]
                    for v in bm.verts:
                        if v.select:
                            v[lyr] = _channel_transform(tuple(v[lyr]), ch, self.mode, self.amount)
                elif attr_domain == "CORNER":
                    layers = (bm.loops.layers.float_color if attr_type == "FLOAT_COLOR"
                              else bm.loops.layers.color)
                    if attr_name not in layers:
                        continue
                    lyr = layers[attr_name]
                    for f in bm.faces:
                        if any(v.select for v in f.verts):
                            for loop in f.loops:
                                loop[lyr] = _channel_transform(tuple(loop[lyr]), ch, self.mode, self.amount)
                bmesh.update_edit_mesh(obj.data)
        elif context.mode == "OBJECT":
            for obj in sel:
                ca = obj.data.color_attributes.get(attr_name)
                if ca is None:
                    continue
                for d in ca.data:
                    d.color = _channel_transform(tuple(d.color), ch, self.mode, self.amount)
                obj.data.update()
                obj.update_tag()

        if context.area:
            context.area.tag_redraw()
        return {"FINISHED"}
```

- [ ] **Step 2: Register the operator in `__init__.py`**

In the import block (currently):
```python
from .operators.assign_vertex_color import (
    IOPS_OT_VertexColorAssign,
    IOPS_OT_VertexColorAlphaAssign,
)
```
change to:
```python
from .operators.assign_vertex_color import (
    IOPS_OT_VertexColorAssign,
    IOPS_OT_VertexColorAlphaAssign,
    IOPS_OT_VertexColorChannel,
)
```

In the `classes` tuple, after the line `IOPS_OT_VertexColorAlphaAssign,` (~line 441), add on the next line:
```python
    IOPS_OT_VertexColorChannel,
```

- [ ] **Step 3: Syntax-check**

Run:
```bash
cd "D:/git/InteractionOps" && python -c "import ast; ast.parse(open('operators/assign_vertex_color.py').read()); ast.parse(open('__init__.py').read()); print('AST OK')"
```
Expected: `AST OK`

- [ ] **Step 4: Run the full test suite (no regression)**

Run: `python -m pytest tests -q`
Expected: no NEW failures (only the known pre-existing `test_polygon_match` failure).

- [ ] **Step 5: Live-verify in Blender (controller)**

Reload addon, then via `execute_blender_code` on a cube in Edit Mesh, all verts selected, with a POINT FLOAT_COLOR attribute initialized to a mixed color e.g. (0.2, 0.4, 0.6, 0.3):
```python
import bpy, bmesh
# = on G  -> (0,1,0, 0.3)   (pure green, alpha preserved)
bpy.ops.iops.mesh_vertex_color_channel(channel='G', mode='SET')
# + on R  -> R=1 ; from pure green that's (1,1,0,0.3)
bpy.ops.iops.mesh_vertex_color_channel(channel='R', mode='ADD')
# - on G  -> G=0 ; (1,0,0,0.3)
bpy.ops.iops.mesh_vertex_color_channel(channel='G', mode='SUB')
```
Read back via bmesh float_color layer; expected final `(1.0, 0.0, 0.0, 0.3)` (alpha 0.3 preserved throughout). Confirm `=` zeroed the other two channels and `+`/`−` touched only the named channel.

- [ ] **Step 6: Commit**

```bash
git add operators/assign_vertex_color.py __init__.py
git commit -m "feat(vertex-color): per-channel set/add/subtract operator"
```

---

### Task 2: Widget JSON — three per-channel rows

**Files:**
- Modify: `B:/scripts/presets/iops/widgets/vertex_color.json` (Blender user-scripts folder; not repo-tracked)

**Interfaces:**
- Consumes: `iops.mesh_vertex_color_channel` (Task 1).
- Produces: the updated `vertex_color` widget (9 rows).

- [ ] **Step 1: Replace the pure-fill RGB row with three per-channel rows**

The current file has a single `{"type": "ROW", ...}` holding the three R/G/B pure-fill swatches (the first ROW after `{"type": "SECTION", "label": "Fill RGB"}`). Replace that one ROW with these three ROWs (leave the Black/White ROW, Alpha section/row, and Preview section/flipbox exactly as they are):

```json
    {"type": "ROW", "cells": [
      {"type": "SWATCH", "color": [1, 0, 0, 1],
       "op": "iops.mesh_vertex_color_channel", "op_kwargs": {"channel": "R", "mode": "SET"}},
      {"type": "BUTTON", "label": "+", "op": "iops.mesh_vertex_color_channel", "op_kwargs": {"channel": "R", "mode": "ADD"}},
      {"type": "BUTTON", "label": "-", "op": "iops.mesh_vertex_color_channel", "op_kwargs": {"channel": "R", "mode": "SUB"}}
    ]},
    {"type": "ROW", "cells": [
      {"type": "SWATCH", "color": [0, 1, 0, 1],
       "op": "iops.mesh_vertex_color_channel", "op_kwargs": {"channel": "G", "mode": "SET"}},
      {"type": "BUTTON", "label": "+", "op": "iops.mesh_vertex_color_channel", "op_kwargs": {"channel": "G", "mode": "ADD"}},
      {"type": "BUTTON", "label": "-", "op": "iops.mesh_vertex_color_channel", "op_kwargs": {"channel": "G", "mode": "SUB"}}
    ]},
    {"type": "ROW", "cells": [
      {"type": "SWATCH", "color": [0, 0, 1, 1],
       "op": "iops.mesh_vertex_color_channel", "op_kwargs": {"channel": "B", "mode": "SET"}},
      {"type": "BUTTON", "label": "+", "op": "iops.mesh_vertex_color_channel", "op_kwargs": {"channel": "B", "mode": "ADD"}},
      {"type": "BUTTON", "label": "-", "op": "iops.mesh_vertex_color_channel", "op_kwargs": {"channel": "B", "mode": "SUB"}}
    ]},
```

For reference, the full intended `rows` array is: `SECTION "Fill RGB"` → R row → G row → B row → Black/White ROW (unchanged) → `SECTION "Alpha"` (show_if EDIT_MESH) → A0/A1 ROW (show_if EDIT_MESH) → `SECTION "Preview"` → `FLIPBOX "Preview VC"`.

- [ ] **Step 2: Validate bpy-free**

Run:
```bash
cd "D:/git/InteractionOps" && python -c "import json,sys; sys.path.insert(0,'.'); from widgets import composed; d=json.load(open('B:/scripts/presets/iops/widgets/vertex_color.json')); c,e=composed.validate_def(d); print('errors:', e); print('rows:', [r['type'] for r in c['rows']]); print('R row cells:', [x['type'] for x in c['rows'][1]['cells']])"
```
Expected: `errors: []`; `rows: ['SECTION','ROW','ROW','ROW','ROW','SECTION','ROW','SECTION','FLIPBOX']` (9 rows); R row cells `['swatch','button','button']` — note `validate_def` lowercases the `type` into control kinds, so accept either the raw `SWATCH/BUTTON` or normalized form your validator emits; the key check is 9 rows and no errors.

- [ ] **Step 3: Live-verify in Blender (controller)**

Reload addon; `composed.load_all()`; summon `vertex_color`. In Edit Mesh with a selection: clicking the red swatch sets pure red (alpha kept), `+`/`−` on each row nudge only that channel. Screenshot: three color rows each `[swatch] [+] [-]`, then Black/White, Alpha, Preview.

- [ ] **Step 4: No git commit (file is outside the repo).**

---

### Task 3: Documentation

**Files:**
- Modify: `docs/operators/op_assign_vertex_color.md`

**Interfaces:**
- Consumes: Task 1 (the new operator).
- Produces: docs only.

- [ ] **Step 1: Document the channel operator + revised widget layout**

In `docs/operators/op_assign_vertex_color.md`, before the `## Related` section, add:

```markdown
## Vertex Color Channel (bl_idname: iops.mesh_vertex_color_channel)

Sets, adds to, or subtracts from a single R/G/B channel of the active color
attribute on the selection, preserving the other channels and alpha.

### Properties
| Name | Type | Default | Description |
| --- | --- | --- | --- |
| `channel` | Enum | `R` | Target channel: `R` / `G` / `B`. |
| `mode` | Enum | `SET` | `SET` (=): set channel to 1.0 and zero the other two RGB channels; `ADD` (+): `min(1, channel + amount)`; `SUB` (−): `max(0, channel − amount)`. |
| `amount` | Float | `1.0` | Step for `ADD` / `SUB`. |

Alpha is always preserved. Works in Edit Mesh (selected verts / corners of faces
with a selected vert) and Object Mode (whole attribute), on POINT/CORNER domains
and FLOAT_COLOR/BYTE_COLOR types. If the active object has no color attribute, a
default `Color` (FLOAT_COLOR, POINT) is created.

The Vertex Color widget's "Fill RGB" section drives this operator: each channel
is a row of a colored swatch (`=`, pure fill via `mode=SET`) plus `+` (`ADD`) and
`−` (`SUB`) buttons.
```

- [ ] **Step 2: Commit**

```bash
git add docs/operators/op_assign_vertex_color.md
git commit -m "docs(vertex-color): per-channel =/+/- operator"
```

---

## Self-Review

**Spec coverage:**
- New operator `iops.mesh_vertex_color_channel` with channel/mode/amount → Task 1. ✓
- `_channel_transform` SET/ADD/SUB semantics, alpha preserved → Task 1 helper. ✓
- Edit/Object + POINT/CORNER + float/byte iteration (RMW) → Task 1 execute. ✓
- Attribute-ensure parity → Task 1 (`create default Color if none`). ✓
- Registration → Task 1 Step 2. ✓
- Widget: replace pure-fill RGB row with three `[swatch =][+][−]` rows; keep Black/White, Alpha, Preview; 9 rows → Task 2. ✓
- Docs → Task 3. ✓

**Placeholder scan:** No TBD/TODO; every code step is complete. Task 2 Step 2's note about validator normalization is a concrete "accept either form" instruction with the load-bearing check named (9 rows, no errors), not a gap.

**Type consistency:** `iops.mesh_vertex_color_channel`, `channel`/`mode`/`amount`, `CHANNEL_INDEX`, `_channel_transform(rgba, ch_idx, mode, amount)`, modes `SET`/`ADD`/`SUB`, class `IOPS_OT_VertexColorChannel` are identical across Task 1 code, the Task 2 `op_kwargs` (`channel`/`mode`), the Task 1 registration, and the Task 3 docs.
