# Vertex Color Quick-Assign Widget Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a lean GPU viewport widget that assigns vertex colors via clickable swatches — R/G/B pure-color fill and Alpha-0/Alpha-1 alpha-only writes.

**Architecture:** Reuse the two existing vertex-color operators (extending the fill operator with an explicit-color override); extend the widget framework's `SWATCH` control to take a literal color and an alpha-aware (checkerboard) render mode; ship the widget as a JSON def in the widgets library folder.

**Tech Stack:** Blender 5.1.2 `bpy` operators; the iOps GPU widget framework (`widgets/composed.py` builder — bpy-free; `ui/widgets/{controls,render}.py` runtime); pytest for the bpy-free layers.

## Global Constraints

- Target Blender **5.1.2**.
- `widgets/composed.py` and `ui/widgets/controls.py` must stay **bpy-free** (importable under plain pytest); `python -m pytest tests -q` must stay green.
- Widget JSON filename stem **must equal** its `name` field.
- Follow existing widget conventions: invalid rows are **dropped with a reported error**, the rest of the widget survives.
- Do **not** introduce modal operators on swatch/button clicks (clicks fire `INVOKE_DEFAULT`).
- Existing behavior of `iops.mesh_assign_vertex_color` (picker color, black/grey/white fill flags) must be unchanged when the new override is off.
- Blender live-verification runs through the `blender` MCP (`execute_blender_code`); addon reload per the iops-custom-widgets skill (blinker port 9902, or disable → purge `sys.modules['InteractionOps.*']` → enable).

---

### Task 1: Explicit-color override on the fill operator

**Files:**
- Modify: `operators/assign_vertex_color.py` (props block ~21-32; `execute` ~52-71; `draw` ~211-225)

**Interfaces:**
- Consumes: nothing.
- Produces: `iops.mesh_assign_vertex_color` accepts two new operator properties —
  `use_override_color: bool` (default `False`) and
  `override_color: float[4]` (RGBA, subtype COLOR, default `(1,0,0,1)`).
  When `use_override_color` is `True`, the fill color is `tuple(override_color)`,
  overriding both the scene picker and the `fill_color_black/grey/white` flags.

This operator depends on `bpy` and is verified live in Blender (no pytest).

- [ ] **Step 1: Add the two properties**

In `operators/assign_vertex_color.py`, inside `IOPS_OT_VertexColorAssign`, immediately after the `fill_color_grey` / `fill_color_white` property block (before `domain:`), add:

```python
    use_override_color: BoolProperty(
        name="Use Override Color",
        description="Fill with override_color instead of the picker / fill flags",
        default=False
    )
    override_color: bpy.props.FloatVectorProperty(
        name="Override Color",
        description="Explicit RGBA fill color used when Use Override Color is on",
        size=4,
        subtype="COLOR",
        min=0.0,
        max=1.0,
        default=(1.0, 0.0, 0.0, 1.0)
    )
```

(`bpy.props.FloatVectorProperty` is fully qualified, matching the existing `bpy.props.StringProperty` / `EnumProperty` usage — no import change needed.)

- [ ] **Step 2: Apply the override in `execute()`**

Replace the color-selection block (the lines from `color = color_picker` through the three `fill_color_* = False` resets) with:

```python
        # Determine color BEFORE processing objects
        color = color_picker
        if self.use_override_color:
            color = tuple(self.override_color)
        elif self.fill_color_black:
            color = color_black
        elif self.fill_color_grey:
            color = color_grey
        elif self.fill_color_white:
            color = color_white

        # Reset the one-shot fill flags after determining color.
        # use_override_color is NOT reset: it is driven per-click by the
        # widget's op_kwargs, not a sticky redo-panel toggle.
        self.fill_color_black = False
        self.fill_color_grey = False
        self.fill_color_white = False
```

- [ ] **Step 3: Expose the props in `draw()`**

In `draw()`, after the existing `col.prop(self, "fill_color_white", ...)` line, append:

```python
        col.prop(self, "use_override_color", text="Use Override Color")
        col.prop(self, "override_color", text="Override Color")
```

- [ ] **Step 4: Live-verify in Blender**

Reload the addon, then run via `execute_blender_code` (assumes an active mesh in Edit Mode with some verts selected):

```python
import bpy
bpy.ops.iops.mesh_assign_vertex_color(
    use_override_color=True, override_color=(0.0, 1.0, 0.0, 1.0))
me = bpy.context.object.data
ca = me.color_attributes.active_color
# spot-check a couple of stored values are green
print([tuple(round(c, 3) for c in d.color) for d in list(ca.data)[:3]])
```

Expected: selected elements report `(0.0, 1.0, 0.0, 1.0)`. Also confirm a plain call with no kwargs still uses the scene picker (unchanged behavior).

- [ ] **Step 5: Commit**

```bash
git add operators/assign_vertex_color.py
git commit -m "feat(vertex-color): explicit-color override on assign operator"
```

---

### Task 2: `SWATCH` accepts a literal `color` and `show_alpha`

**Files:**
- Modify: `widgets/composed.py` (`validate_def` SWATCH branch, ~434-446)
- Test: `tests/ui/widgets/test_composed.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `validate_def` SWATCH rules — a SWATCH requires **exactly one** of
  `prop` (RNA color path) or `color` (list of 4 numbers); `op` still required.
  Normalized output: color-swatches carry `"color": [floats]` (no `prop`);
  prop-swatches carry `"prop"` (unchanged, no `color` key). `show_alpha: true`
  is added to the normalized row only when provided truthy.

- [ ] **Step 1: Write the failing tests**

Append to `tests/ui/widgets/test_composed.py` (after the existing SWATCH tests, ~line 304):

```python
def test_validate_swatch_literal_color():
    data = {"name": "vc", "rows": [
        {"type": "SWATCH", "color": [1, 0, 0, 1], "op": "iops.x.y",
         "label": "R"}]}
    wdef, errors = composed.validate_def(data)
    assert errors == []
    r = wdef["rows"][0]
    assert r["color"] == [1.0, 0.0, 0.0, 1.0]
    assert "prop" not in r
    assert r["op"] == "iops.x.y"
    assert r["label"] == "R"


def test_validate_swatch_color_and_prop_dropped():
    data = {"name": "vc", "rows": [
        {"type": "SWATCH", "color": [1, 0, 0, 1],
         "prop": "scene.IOPS.iops_object_color", "op": "iops.x.y"}]}
    wdef, errors = composed.validate_def(data)
    assert wdef["rows"] == []
    assert errors


def test_validate_swatch_neither_color_nor_prop_dropped():
    data = {"name": "vc", "rows": [{"type": "SWATCH", "op": "iops.x.y"}]}
    wdef, errors = composed.validate_def(data)
    assert wdef["rows"] == []
    assert errors


def test_validate_swatch_bad_color_dropped():
    data = {"name": "vc", "rows": [
        {"type": "SWATCH", "color": [1, 0, 0], "op": "iops.x.y"}]}
    wdef, errors = composed.validate_def(data)
    assert wdef["rows"] == []
    assert errors


def test_validate_swatch_show_alpha():
    data = {"name": "vc", "rows": [
        {"type": "SWATCH", "color": [0.5, 0.5, 0.5, 0], "op": "iops.x.y",
         "show_alpha": True}]}
    wdef, errors = composed.validate_def(data)
    assert errors == []
    assert wdef["rows"][0]["show_alpha"] is True


def test_validate_swatch_no_show_alpha_key_when_absent():
    data = {"name": "vc", "rows": [
        {"type": "SWATCH", "color": [1, 0, 0, 1], "op": "iops.x.y"}]}
    wdef, errors = composed.validate_def(data)
    assert "show_alpha" not in wdef["rows"][0]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/ui/widgets/test_composed.py -q -k swatch`
Expected: the 6 new tests FAIL (literal color currently rejected — "swatch needs a prop").

- [ ] **Step 3: Implement the new SWATCH validation**

In `widgets/composed.py`, replace the entire `if rtype == "SWATCH":` branch in `validate_def` with:

```python
    if rtype == "SWATCH":
        prop = str(row.get("prop", "")).strip()
        color = row.get("color", None)
        has_color = color is not None
        if prop and has_color:
            return None, "swatch needs exactly one of prop or color, not both"
        if not prop and not has_color:
            return None, "swatch needs a prop (RNA color path) or a literal color"
        op = str(row.get("op", "")).strip()
        if "." not in op:
            return None, f"swatch op '{op}' is not an operator idname"
        if has_color:
            if (not isinstance(color, (list, tuple)) or len(color) != 4
                    or not all(isinstance(c, (int, float)) for c in color)):
                return None, "swatch color must be a list of 4 numbers"
            out["color"] = [float(c) for c in color]
        else:
            out["prop"] = prop
        out["op"] = op
        out["label"] = str(row.get("label", ""))
        kwargs = row.get("op_kwargs", {})
        out["op_kwargs"] = kwargs if isinstance(kwargs, dict) else {}
        if bool(row.get("show_alpha", False)):
            out["show_alpha"] = True
        return out, None
```

- [ ] **Step 4: Run the SWATCH tests + the full suite**

Run: `python -m pytest tests/ui/widgets/test_composed.py -q -k swatch`
Expected: PASS (including the pre-existing `test_validate_swatch_minimal`, `test_validate_swatch_missing_prop_dropped` — the latter has neither `color` nor `prop` so it still drops).

Run: `python -m pytest tests -q`
Expected: PASS (no regressions).

- [ ] **Step 5: Commit**

```bash
git add widgets/composed.py tests/ui/widgets/test_composed.py
git commit -m "feat(widgets): SWATCH accepts literal color + show_alpha"
```

---

### Task 3: Build a constant-color `Swatch` control with `show_alpha`

**Files:**
- Modify: `ui/widgets/controls.py` (`Swatch.__init__`, ~299-304)
- Modify: `widgets/composed.py` (`build_controls` SWATCH branch, ~615-619)
- Test: `tests/ui/widgets/test_composed.py`

**Interfaces:**
- Consumes: Task 2's normalized SWATCH row (`color` or `prop`, optional `show_alpha`).
- Produces: `Swatch.__init__(get, op, kwargs=None, label="", enabled_get=None, show_alpha=False)` storing `self.show_alpha`. `build_controls` builds a constant getter `get(context) -> (tuple(color), False)` for color-swatches and threads `show_alpha` into the `Swatch`.

- [ ] **Step 1: Add `show_alpha` to `Swatch`**

In `ui/widgets/controls.py`, change `Swatch.__init__` signature and body:

```python
    def __init__(self, get, op, kwargs=None, label="", enabled_get=None,
                 show_alpha=False):
        super().__init__(get, None)
        self.op = op            # operator idname, e.g. "iops.object_color_apply"
        self.kwargs = dict(kwargs) if kwargs else {}
        self.label = label      # optional centered glyph/text on the fill
        self.enabled_get = enabled_get
        self.show_alpha = bool(show_alpha)
```

- [ ] **Step 2: Write the failing build test**

Append to `tests/ui/widgets/test_composed.py`:

Build through `composed.build_controls(rows)` — the bpy-free path the existing `test_build_controls_*` tests use (it returns a list of `Control` instances directly; no Blender registration). The normalized rows come from `validate_def` first:

```python
def test_build_swatch_literal_color_constant_getter():
    data = {"name": "vc", "rows": [
        {"type": "SWATCH", "color": [1, 0, 0, 1], "op": "iops.x.y",
         "label": "R", "show_alpha": True}]}
    clean, errors = composed.validate_def(data)
    assert errors == []
    ctrls = composed.build_controls(clean["rows"])
    sw = ctrls[0]
    assert sw.kind == "swatch"
    assert sw.show_alpha is True
    value, mixed = sw.get(None)          # constant getter, context ignored
    assert value == (1.0, 0.0, 0.0, 1.0)
    assert mixed is False
```

- [ ] **Step 3: Run it to verify it fails**

Run: `python -m pytest tests/ui/widgets/test_composed.py -q -k swatch_literal_color_constant`
Expected: FAIL (build still calls `rna_color_adapter(row["prop"])` → `KeyError: 'prop'`).

- [ ] **Step 4: Implement the build branch**

In `widgets/composed.py`, replace the `if rtype == "SWATCH":` branch in `build_controls` with:

```python
        if rtype == "SWATCH":
            if "color" in row:
                const = tuple(row["color"])
                get = lambda context, _c=const: (_c, False)
            else:
                get = rna_color_adapter(row["prop"])["get"]
            return Swatch(get=get, op=row["op"],
                          kwargs=row.get("op_kwargs") or {},
                          label=row.get("label", ""),
                          show_alpha=bool(row.get("show_alpha", False)))
```

- [ ] **Step 5: Run the test + full suite**

Run: `python -m pytest tests/ui/widgets/test_composed.py -q -k swatch`
Expected: PASS.

Run: `python -m pytest tests -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add ui/widgets/controls.py widgets/composed.py tests/ui/widgets/test_composed.py
git commit -m "feat(widgets): build constant-color Swatch with show_alpha"
```

---

### Task 4: Alpha-aware (checkerboard) swatch rendering

**Files:**
- Modify: `ui/widgets/render.py` (constants block ~36-41; `_draw_swatch`, ~360-376)

**Interfaces:**
- Consumes: a `Swatch` control with a `show_alpha` attribute (Task 3) and a color getter.
- Produces: `_draw_swatch` draws a transparency checker behind the fill and honors the color's alpha when `control.show_alpha` is true; unchanged force-opaque fill otherwise. A `_draw_checker(x, y, w, h, theme)` helper.

Rendering depends on `bpy`/GPU and is verified live in Blender (no pytest).

- [ ] **Step 1: Add checker constants + helper**

In `ui/widgets/render.py`, after the swatch constants (`SWATCH_HEIGHT_FACTOR` line ~38), add:

```python
CHECKER_COLS = 4            # transparency-checker cells across an alpha swatch
CHECKER_ROWS = 2
CHECKER_LIGHT = (0.55, 0.55, 0.55, 1.0)
CHECKER_DARK = (0.30, 0.30, 0.30, 1.0)
```

Then, just above `_draw_swatch` (before line ~360), add the helper:

```python
def _draw_checker(x, y, w, h, theme):
    """Opaque transparency checker filling a swatch's inset rect (two greys).
    Drawn at full opacity so it shows through wherever the alpha fill above
    it is < 1.0 — used by show_alpha swatches to read alpha as transparency."""
    cw = w / CHECKER_COLS
    ch = h / CHECKER_ROWS
    for r in range(CHECKER_ROWS):
        for c in range(CHECKER_COLS):
            col = CHECKER_LIGHT if (r + c) % 2 == 0 else CHECKER_DARK
            primitives.rect_2d(x + c * cw, y + r * ch, cw, ch,
                               color=col, theme=theme)
```

- [ ] **Step 2: Rewrite `_draw_swatch`**

Replace the body of `_draw_swatch` with:

```python
def _draw_swatch(control, rect, theme, dim, context, live):
    value, _ = control.value(context) if live else control.cached()
    disabled = (value is None) or not control.enabled
    eff = dim * (DISABLED_ALPHA if disabled else 1.0)
    show_alpha = getattr(control, "show_alpha", False)
    if value is not None:
        # subtype=COLOR props are scene-linear; encode to sRGB to match the
        # native color field.
        enc = _srgb_encode(value)
        ix, iy = rect.x + SWATCH_INSET, rect.y + SWATCH_INSET
        iw, ih = rect.w - SWATCH_INSET * 2.0, rect.h - SWATCH_INSET * 2.0
        if show_alpha:
            # Checker behind, fill honoring the color's real alpha on top.
            # Alpha 0 => checker only (transparent); 1 => solid over checker.
            _draw_checker(ix, iy, iw, ih, theme)
            a = value[3]
            if a > 0.0:
                primitives.rect_2d(ix, iy, iw, ih,
                                   color=(enc[0], enc[1], enc[2], a),
                                   theme=theme)
        else:
            # Force opaque so a low-alpha stored color is still visible
            # (alpha is not part of a normal swatch's job).
            primitives.rect_2d(ix, iy, iw, ih,
                               color=(enc[0], enc[1], enc[2], 1.0), theme=theme)
    # Outline/label carry the disabled fade; the fill stays readable.
    _outline(rect, _col(theme, Role.LINE, eff), theme)
    if control.label:
        _text_centered(control.label, rect, theme=theme,
                       color=_col(theme, Role.HUD_LABEL, eff))
```

- [ ] **Step 3: Live-verify rendering**

Build a throwaway widget with one normal and two `show_alpha` swatches and summon it, via `execute_blender_code`:

```python
import bpy
from InteractionOps.widgets import composed
wdef = {"version": 1, "name": "swatch_check", "title": "Swatch Check",
        "space": "VIEW_3D", "rows": [{"type": "ROW", "cells": [
    {"type": "SWATCH", "color": [1, 0, 0, 1], "op": "iops.iops_panel",
     "label": "R"},
    {"type": "SWATCH", "color": [0.5, 0.5, 0.5, 0], "show_alpha": True,
     "op": "iops.iops_panel", "label": "A0"},
    {"type": "SWATCH", "color": [0.5, 0.5, 0.5, 1], "show_alpha": True,
     "op": "iops.iops_panel", "label": "A1"}]}]}
clean, errs = composed.validate_def(wdef)
print("errors:", errs)
composed.register_composed(clean)
bpy.ops.iops.widget_toggle(name="swatch_check")
```

Then capture the viewport (`get_screenshot_of_area_as_image`) and confirm: R = solid red; A0 = full checker (no grey overlay); A1 = solid grey hiding the checker; labels visible on each. Toggle it off afterward (`bpy.ops.iops.widget_toggle(name="swatch_check")`); no JSON file was written so it won't persist past reload.

- [ ] **Step 4: Run the full suite (no render regressions in bpy-free layer)**

Run: `python -m pytest tests -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add ui/widgets/render.py
git commit -m "feat(widgets): alpha-aware checkerboard swatch rendering"
```

---

### Task 5: Ship the `vertex_color` widget JSON + end-to-end verify

**Files:**
- Create: `presets/IOPS/widgets/vertex_color.json` (i.e. `B:\scripts\presets\iops\widgets\vertex_color.json` via the B: symlink — same folder as `object_color.json`)

**Interfaces:**
- Consumes: the operators (Task 1, plus existing `iops.mesh_assign_vertex_color_alpha`) and the SWATCH `color`/`show_alpha` support (Tasks 2-4).
- Produces: a registered widget `vertex_color` summonable via `iops.widget_toggle(name="vertex_color")`.

- [ ] **Step 1: Write the widget JSON**

Create `presets/IOPS/widgets/vertex_color.json`:

```json
{
  "version": 1,
  "name": "vertex_color",
  "title": "Vertex Color",
  "space": "VIEW_3D",
  "rows": [
    {"type": "SECTION", "label": "Fill RGB"},
    {"type": "ROW", "cells": [
      {"type": "SWATCH", "color": [1, 0, 0, 1], "label": "R",
       "op": "iops.mesh_assign_vertex_color",
       "op_kwargs": {"use_override_color": true, "override_color": [1, 0, 0, 1]}},
      {"type": "SWATCH", "color": [0, 1, 0, 1], "label": "G",
       "op": "iops.mesh_assign_vertex_color",
       "op_kwargs": {"use_override_color": true, "override_color": [0, 1, 0, 1]}},
      {"type": "SWATCH", "color": [0, 0, 1, 1], "label": "B",
       "op": "iops.mesh_assign_vertex_color",
       "op_kwargs": {"use_override_color": true, "override_color": [0, 0, 1, 1]}}
    ]},
    {"type": "SECTION", "label": "Alpha", "show_if": {"mode": "EDIT_MESH"}},
    {"type": "ROW", "show_if": {"mode": "EDIT_MESH"}, "cells": [
      {"type": "SWATCH", "color": [0.5, 0.5, 0.5, 0], "show_alpha": true, "label": "A0",
       "op": "iops.mesh_assign_vertex_color_alpha",
       "op_kwargs": {"vertex_color_alpha": 0.0}},
      {"type": "SWATCH", "color": [0.5, 0.5, 0.5, 1], "show_alpha": true, "label": "A1",
       "op": "iops.mesh_assign_vertex_color_alpha",
       "op_kwargs": {"vertex_color_alpha": 1.0}}
    ]}
  ]
}
```

- [ ] **Step 2: Validate the def is clean (bpy-free)**

Run via python (no Blender needed):

```bash
python -c "import json, sys; sys.path.insert(0, '.'); from widgets import composed; d=json.load(open('presets/IOPS/widgets/vertex_color.json')); clean, errs=composed.validate_def(d); print('errors:', errs); print('rows:', [r['type'] for r in clean['rows']])"
```

Expected: `errors: []` and 4 rows `['SECTION', 'ROW', 'SECTION', 'ROW']`.

- [ ] **Step 3: Live end-to-end verify in Blender**

Reload the addon (so the new JSON auto-loads), then run via `execute_blender_code` on a mesh with a vertex selection in **Edit Mesh**:

```python
import bpy
bpy.ops.iops.scripts_call_widgets_panel()  # re-scans the folder, registers vertex_color
bpy.ops.iops.widget_toggle(name="vertex_color")
```

Checks (screenshot + data):
1. In Edit Mesh: both sections visible; click **R** → selected verts/corners become red; click **G**/**B** likewise. Click **A1** then **A0** → only the alpha channel of selected elements changes (RGB preserved). Confirm by reading `color_attributes.active_color.data`.
2. Switch to **Object Mode**: the **Alpha** section + row disappear (`show_if mode=EDIT_MESH`); the RGB row stays and clicking R fills the whole active mesh's attribute.
3. A0/A1 swatches render as checker (A0) / solid grey (A1) with labels.

- [ ] **Step 4: Commit**

```bash
git add presets/IOPS/widgets/vertex_color.json
git commit -m "feat(widgets): vertex color quick-assign widget (R/G/B + alpha)"
```

---

### Task 6: Documentation

**Files:**
- Modify: `docs/operators/op_assign_vertex_color.md` (properties table for `iops.mesh_assign_vertex_color`)
- Modify: `ai_skills/iops-custom-widgets/schema-reference.md` (`SWATCH` section, ~67-77)
- Modify: `ai_skills/iops-custom-widgets/SKILL.md` (SWATCH row in the row-types table, ~58)

**Interfaces:**
- Consumes: Tasks 1-4 (the shipped operator props + SWATCH keys).
- Produces: docs only.

- [ ] **Step 1: Document the operator props**

In `docs/operators/op_assign_vertex_color.md`, add two rows to the `Assign Vertex Color` properties table:

```markdown
| `use_override_color` | Bool | `False` | Fill with `override_color` instead of the picker / black-grey-white flags. Not auto-reset (driven by callers like the Vertex Color widget). |
| `override_color` | Float[4] | `(1, 0, 0, 1)` | Explicit RGBA fill color used when `use_override_color` is on. Wins over the scene picker and the fill flags. |
```

- [ ] **Step 2: Document the SWATCH `color` / `show_alpha` keys**

In `ai_skills/iops-custom-widgets/schema-reference.md`, replace the `SWATCH` key table (lines ~71-74) with:

```markdown
| `prop` | dotted RNA color path (FloatVector subtype COLOR) | one of `prop`/`color` | — |
| `color` | list of 4 numbers `0..1` (literal RGBA) | one of `prop`/`color` | — |
| `op` | operator idname (must contain `.`) | **yes** | — |
| `op_kwargs` | object | no | `{}` |
| `label` | str | no | `""` (centered glyph on the fill) |
| `show_alpha` | bool | no | `false` (true → checker bg + honor the color's alpha) |
```

And append after the existing absence-safe note (line ~77):

```markdown
A SWATCH takes **exactly one** of `prop` (live RNA color, absence-safe) or
`color` (fixed literal RGBA). With `show_alpha: true` the swatch draws a
transparency checker and honors the color's alpha (alpha 0 = checker only,
1 = solid) — used for alpha-set buttons.
```

- [ ] **Step 3: Update the SKILL.md SWATCH row**

In `ai_skills/iops-custom-widgets/SKILL.md`, change the `SWATCH` row of the row-types table (line ~58) to:

```markdown
| `SWATCH` | EXACTLY ONE of `prop` (RNA color path) or `color` (literal RGBA list); `op` (operator idname), `op_kwargs`, `label`, `show_alpha` | shows a color (live or fixed), fires an operator on click |
```

- [ ] **Step 4: Commit**

```bash
git add docs/operators/op_assign_vertex_color.md ai_skills/iops-custom-widgets/schema-reference.md ai_skills/iops-custom-widgets/SKILL.md
git commit -m "docs(widgets): SWATCH literal color/show_alpha + override_color op props"
```

---

## Self-Review

**Spec coverage:**
- Operator explicit-color override → Task 1. ✓
- SWATCH literal `color` validation → Task 2. ✓
- SWATCH constant getter + `show_alpha` on control → Task 3. ✓
- Alpha-aware checker rendering → Task 4. ✓
- `vertex_color.json` (R/G/B both modes; Alpha gated to Edit Mesh) → Task 5. ✓
- Tests (literal color, both/neither, show_alpha, constant getter) → Tasks 2-3. ✓
- Docs (op doc + schema-reference + SKILL) → Task 6 (additive to the spec's test section; keeps the widget skill accurate). ✓

**Placeholder scan:** No TBD/TODO; every code step shows full code. The one soft spot — Task 3 Step 2's note about the build helper import — gives an explicit fallback and the exact assertion that must hold, not a vague instruction.

**Type consistency:** `use_override_color`/`override_color` named identically in Task 1 props, Task 1 `execute`, and Task 5 `op_kwargs`. `show_alpha` consistent across validate output (Task 2), `Swatch.__init__` param + attribute (Task 3), and `_draw_swatch`'s `getattr(control, "show_alpha", False)` (Task 4). SWATCH normalized keys (`color` vs `prop`) consistent between Task 2 validation and Task 3 build (`if "color" in row`). `_draw_checker(x, y, w, h, theme)` signature matches its call site.
