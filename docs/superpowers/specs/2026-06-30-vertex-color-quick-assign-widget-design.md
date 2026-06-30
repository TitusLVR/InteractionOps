# Vertex Color Quick-Assign Widget — Design

**Date:** 2026-06-30
**Status:** Approved (design), pending implementation plan

## Goal

A persistent GPU viewport widget for fast vertex-color assignment via clickable
color swatches:

- **R / G / B** — fill the selection with pure red `(1,0,0,1)`, green
  `(0,1,0,1)`, blue `(0,0,1,1)` (full-color replacement).
- **Alpha-0 / Alpha-1** — write only the alpha channel (`0.0` / `1.0`),
  leaving RGB untouched.

Scope is deliberately **lean**: only those five swatches. No picker swatch, no
Apply button, no black/grey/white in this pass.

## Behavior

- **R/G/B** fire the existing `iops.mesh_assign_vertex_color` operator with an
  explicit color override. They work in both modes per that operator's existing
  semantics: Edit Mesh fills selected verts/corners; Object Mode fills the whole
  attribute of each selected mesh.
- **Alpha-0/1** fire the existing `iops.mesh_assign_vertex_color_alpha`
  operator, which preserves RGB and is **Edit-Mesh only**. The Alpha row is
  therefore gated to `EDIT_MESH`.

## Components

### 1. Operator change — `operators/assign_vertex_color.py`

Extend `IOPS_OT_VertexColorAssign` with an explicit-color override (cleaner than
adding three more `fill_*` booleans):

- `use_override_color: BoolProperty(default=False)`
- `override_color: FloatVectorProperty(name="Override Color", size=4, subtype="COLOR", min=0.0, max=1.0, default=(1.0, 0.0, 0.0, 1.0))`

In `execute()`, color selection becomes: if `use_override_color`, `color =
tuple(self.override_color)` and this **wins over** the scene picker and the
black/grey/white fill flags. When unset, all existing behavior is unchanged. The
override flag is **not** auto-reset (unlike the fill flags) — it is driven by the
widget's `op_kwargs` each click, not a sticky redo-panel toggle.

Add `override_color` / `use_override_color` to the operator's `draw()` for redo-
panel completeness.

`iops.mesh_assign_vertex_color_alpha` is reused unchanged.

### 2. Framework change — literal-color + alpha-aware SWATCH

The `SWATCH` control today requires a `prop` (RNA color path) and the renderer
forces the fill opaque (`render.py:_draw_swatch`, alpha hard-set to `1.0`). Two
small additions:

**`widgets/composed.py`**
- `validate_def` SWATCH branch: accept **either** `prop` **or** a literal
  `color` (a list/tuple of 4 numbers in `0..1`). Exactly one of the two is
  required; `op` is still required. Reject both-present and neither-present with
  a clear error (row dropped, rest of widget survives — existing convention).
- Optional new SWATCH key `show_alpha: bool` (default `false`); validated and
  passed through.
- Build step: when `color` is present, bind a constant getter
  `get = lambda ctx: (tuple(color), False)` instead of `rna_color_adapter`.
  Thread `show_alpha` to the `Swatch` control (new optional attribute).

**`ui/widgets/controls.py`**
- `Swatch.__init__` gains `show_alpha=False`, stored on the instance. No
  behavior change to `execute()`.

**`ui/widgets/render.py`**
- `_draw_swatch`: when the control's `show_alpha` is true, draw a transparency
  **checkerboard** in the fill rect first, then draw the fill using the color's
  **actual alpha** (so Alpha-0 reads as fully transparent over the checker,
  Alpha-1 as solid). When `show_alpha` is false, keep the current
  force-opaque behavior. The existing centered `label` (e.g. "A0"/"A1") renders
  on top either way.
- Checker = a small fixed grid of `primitives.rect_2d` quads (two greys) clipped
  to the inset fill rect. Keep the cell count small/fixed; no theming needed.

### 3. Widget JSON — `presets/IOPS/widgets/vertex_color.json`

```json
{
  "version": 1,
  "name": "vertex_color",
  "title": "Vertex Color",
  "space": "VIEW_3D",
  "rows": [
    {"type": "SECTION", "label": "Fill RGB"},
    {"type": "ROW", "cells": [
      {"type": "SWATCH", "color": [1,0,0,1], "label": "R",
       "op": "iops.mesh_assign_vertex_color",
       "op_kwargs": {"use_override_color": true, "override_color": [1,0,0,1]}},
      {"type": "SWATCH", "color": [0,1,0,1], "label": "G",
       "op": "iops.mesh_assign_vertex_color",
       "op_kwargs": {"use_override_color": true, "override_color": [0,1,0,1]}},
      {"type": "SWATCH", "color": [0,0,1,1], "label": "B",
       "op": "iops.mesh_assign_vertex_color",
       "op_kwargs": {"use_override_color": true, "override_color": [0,0,1,1]}}
    ]},
    {"type": "SECTION", "label": "Alpha", "show_if": {"mode": "EDIT_MESH"}},
    {"type": "ROW", "show_if": {"mode": "EDIT_MESH"}, "cells": [
      {"type": "SWATCH", "color": [0.5,0.5,0.5,0], "show_alpha": true, "label": "A0",
       "op": "iops.mesh_assign_vertex_color_alpha",
       "op_kwargs": {"vertex_color_alpha": 0.0}},
      {"type": "SWATCH", "color": [0.5,0.5,0.5,1], "show_alpha": true, "label": "A1",
       "op": "iops.mesh_assign_vertex_color_alpha",
       "op_kwargs": {"vertex_color_alpha": 1.0}}
    ]}
  ]
}
```

The widget binds no edge `target`, so it polls always-visible and its swatches
stay enabled. The Alpha section + row carry `show_if: {mode: EDIT_MESH}` because
the alpha operator only runs in Edit Mesh.

## Data flow

Click swatch → `Swatch.execute` → `_invoke_operator(op, kwargs)` →
`bpy.ops.iops.mesh_assign_vertex_color("INVOKE_DEFAULT", use_override_color=True,
override_color=[…])`. JSON arrays arrive as Python lists; `FloatVectorProperty`
accepts a sequence. Both operators have `execute` and no `invoke`, so
`INVOKE_DEFAULT` falls through to `execute` correctly.

## Error handling / edge cases

- `_draw_swatch` color value is `None` → disabled sentinel (existing path). A
  literal-color swatch never returns `None`, so it is always enabled; per-context
  gating is handled by `show_if`, and per-operator readiness by each op's `poll`.
- R/G/B in Object Mode fill the entire attribute (existing operator behavior) —
  intentional, documented, not changed here.
- Invalid SWATCH `color` (wrong length / non-numeric / both `prop` and `color`)
  → row dropped with a reported error, rest of widget survives.

## Testing

`tests/ui/widgets/test_composed.py` (bpy-free, must stay green):
- SWATCH with literal `color` validates; constant getter returns `(color, False)`.
- SWATCH with both `color` and `prop` → dropped with error.
- SWATCH with neither → dropped with error (message updated from the current
  "swatch needs a prop").
- `show_alpha` parsed and defaulted to `false`.

Live verification in Blender 5.1.2 (per the widget skill's Verify section):
reload addon, `iops.scripts_call_widgets_panel`, summon `vertex_color`, click
each swatch in Edit Mesh (selection) and Object Mode; confirm Alpha row hidden
outside Edit Mesh and the checker/label render on A0/A1.

## Out of scope

Picker swatch, Apply button, black/grey/white quick-fills, per-channel masking
(R = set only red channel), C/M/Y swatches, adjustable fill intensity. Any of
these can be a follow-up by adding rows — the operator + framework changes here
already support them.
