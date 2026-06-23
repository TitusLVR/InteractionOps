# Widget conditional rendering + context sensitivity — design

Date: 2026-06-23
Status: approved (brainstorming) — pending implementation plan

## Goal

Extend the JSON-composed GPU widget system (`widgets/composed.py`,
`ui/widgets/`) with two capabilities that converge on one mechanism:

1. **Conditional element rendering** — local "switches" (flip toggles held
   by the widget) that show some rows and hide others. A "show more" /
   advanced toggle.
2. **Context sensitivity** — rows appear or disappear based on the active
   object's context or scene context, like a per-row Blender `poll()`.

Both reduce to: **a top-level row carries an optional `show_if` predicate,
evaluated each frame against context + local switch state.**

## Decisions (from brainstorming)

- Context sensitivity **varies rows within one widget** (not whole-widget
  swapping).
- Predicate vocabulary is fixed and declarative: `mode`, `object_type`,
  `selection`, RNA `prop`, local `switch`. No arbitrary expressions.
- The "show more" toggle is **local panel state** ("switches"), not a
  scene/RNA flag. Switch state **persists** per-widget.
- **Approach A**: per-row `show_if` + a new `switch` FlipBox binding, on the
  existing **flat row list** model. No nested `GROUP` containers in v1.

## Architecture

The framework keeps its core invariant: *the per-cell rects computed by
layout are the single source of truth for both rendering and hit-testing.*
Conditional rows preserve it by funnelling everything through one filtered
visible-row list.

### 1. JSON schema additions

`show_if` — optional, on **any top-level row** (SECTION, SLIDER, PRESETS,
FLIPBOX, BUTTON, ROW, SWATCH). An object; **all present keys are ANDed**:

```jsonc
"show_if": {
  "mode": "EDIT_MESH",              // str | list; context.mode ∈ set
  "object_type": ["MESH","CURVE"],  // str | list; active_object.type ∈ set
                                    //   (no active object → condition false)
  "selection": "edges",             // edges|verts|faces|objects — "has any"
  "prop": "scene.foo.bar",          // RNA dotted path; truthy …
  "switch": "advanced",             // local switch; truthy …
  "equals": <value>                 // … or with "equals", an equality test
                                    //   applied to prop OR switch in clause
}
```

- No OR / nesting in v1 (YAGNI — author two rows). A row needing two
  independent prop tests is also out of scope; use a switch.
- A missing or invalid `show_if` **drops only the clause** and reports an
  error; the **row stays always-visible** (safe: rows never silently
  vanish from a typo).
- `equals` applies to whichever of `prop`/`switch` is present in the same
  clause. Without `equals`, those are truthiness tests.

New FLIPBOX binding `switch` — a **third mutually-exclusive** option beside
`target` and `prop`:

```json
{"type": "FLIPBOX", "switch": "advanced", "label": "Advanced"}
```

- Validation: **exactly one** of `target` / `prop` / `switch` (zero or two+
  → row dropped, as today for target/prop).
- Default `label` = the switch name when omitted.

Optional top-level `"switches"` map for non-false defaults:

```json
"switches": {"advanced": true}
```

- Any switch name referenced anywhere (a `switch` flipbox or a `show_if`
  `switch`) defaults to `false` unless listed here.
- A `show_if` that references a switch with no defining flipbox is allowed
  (stays at default) — reported as a warning, not dropped.

### 2. Local switch state + persistence

- The live `Widget` instance gains `self.switches = {name: bool}`.
- Seeded in `make_widget()` from the def's collected switch names + the
  `switches` defaults map.
- Re-seeded from persisted state in `register_composed()` — the same place
  panel `x`/`y` is restored today, so a reload/hot-reload keeps switch
  positions.
- `ui/widgets/state.py` per-widget state grows a `switches: {name: bool}`
  key alongside `visible` / `x` / `y`.
- The `switch` flipbox adapter:
  - `get(context)` → `(self.switches.get(name, False), False)`
  - `set(context, value)` → writes `self.switches[name]`, marks the widget
    dirty, and persists to `widgets_state`.
  - The store mutation is pure/testable; the persistence call is a deferred
    bpy-side hook (same pattern as `widgets_folder()` deferring its `bpy`
    import inside the function body).

### 3. Visible-row resolution (core change)

- Each built control carries its compiled predicate: `control._show_if`
  (a validated dict) or `None`.
- `Widget.rows(context)` returns the **filtered** visible controls. (Was
  `rows()` with no argument.)
- `Widget.control_at(context, row, col)` indexes that **same** filtered
  list.
- `render.compute_layout`, `render.draw_widget`, and the
  `iops.widget_interact` modal in `events.py` all already hold `context`
  and all flow through `rows()` / `control_at` — so the row↔`row_rects`
  correspondence (and thus the draw/hit-test agreement) is preserved with
  no per-site special-casing.
- **Evaluated live every call** — no visibility cache:
  - Predicates are cheap: `mode`/`object_type`/`switch`/`prop` are a few
    `getattr`s; `selection` reuses the existing per-frame
    `has_selected_edges`-style check (already run for enabled gating).
  - Context is stable within a synchronous draw or gesture, so the ~4
    `rows(context)` calls per frame return identical lists → layout, draw,
    and hit-test always agree.
  - Existing per-control value caches (`_ValueControl._dirty`) are
    untouched; only visibility is live.

### 4. Merge interaction (rule)

`merge_flipbox_runs` groups consecutive bare flipboxes at **build time**,
before visibility filtering — so a merged Row could otherwise contain a
cell that should be individually hidden (no per-cell visibility in v1).

Rule: **auto-merge only groups consecutive flipboxes that have no
`show_if`.** A flipbox carrying a `show_if` breaks the run and stands as
its own one-cell row, so its predicate hides exactly it. (A `switch`
flipbox with no `show_if` still merges normally.)

### 5. Predicate evaluator (pure, pytest-covered)

`eval_show_if(pred, ctx) -> bool` in `composed.py`:

- `pred` is the validated `show_if` dict, or `None` → `True`.
- `ctx` is a small accessor with: `mode: str`, `object_type: str | None`,
  `has_selection(kind) -> bool`, `prop(path) -> (value, found)`,
  `switch(name) -> bool`.
- Condition semantics (all present keys ANDed):
  - `mode`: `ctx.mode in as_set(pred["mode"])`
  - `object_type`: `ctx.object_type in as_set(...)`; `None` → `False`
  - `selection`: `ctx.has_selection(pred["selection"])`
  - `prop`: `(value, found) = ctx.prop(path)`; `found and (value == equals
    if "equals" else bool(value))`; missing path → `False`
  - `switch`: `val = ctx.switch(name)`; `val == equals if "equals" else
    bool(val)`
- Bpy side builds a real `Ctx` from `context` + `widget.switches`; tests
  use a fake `Ctx`. Mirrors the module's existing bpy-free test discipline.

### 6. Edge cases

- **All rows hidden** (widget in-context, every predicate false): render a
  **title-bar-only** panel — draggable and closable. Zero-row layout
  already yields height `title_h + 2·padding`; the draw loop over zero rows
  is a no-op.
- **Widget-level `poll` unchanged**: existing edge-bound widgets still
  collapse to the hardcoded "Go back to Edit Mode" hint out of EDIT_MESH.
  Row predicates are **additive** and only filter inside an in-context
  widget. A new context-sensitive widget binds no edge `target`, so it
  polls always-true and simply filters rows.
- **Press-cell stability**: a `switch` flipbox writes on **release**, so
  visibility changes only on the next frame. Within one press→release
  gesture the visible set is constant and `_press_cell` `(row, col)`
  indices stay valid.

## Out of scope (v1)

- Nested `GROUP` / collapsible containers.
- OR / NOT / nested boolean expressions in `show_if`.
- Exact selection counts (only coarse "has any").
- Per-cell visibility inside a `ROW`.

## Touched files

- `widgets/composed.py` — `show_if` validation (`_clean_show_if`), `switch`
  flipbox binding, `switches` map, `eval_show_if` + `Ctx`, switch adapter,
  merge-rule change, predicate attach in `build_controls`, switch seeding
  in `make_widget` / `register_composed`.
- `ui/widgets/__init__.py` — `rows(context)` filtering, `control_at(context,
  …)`, `self.switches` on the instance.
- `ui/widgets/state.py` — persist/restore the `switches` key.
- `ui/widgets/render.py` — thread `context` into `rows`/`control_at`,
  title-bar-only draw when the visible list is empty.
- `ui/widgets/events.py` — thread `context` into `rows`/`control_at` in the
  interact modal.
- `tests/ui/widgets/` — evaluator truth table, `show_if` + `switch` +
  `switches` validation, visible-row filtering, merge rule.
- `ai_skills/iops-custom-widgets/SKILL.md` — document `show_if`, the
  `switch` flipbox, the `switches` map, the merge rule, and gotchas.

## Verification

- `python -m pytest tests -q` green (composed.py stays bpy-free).
- In Blender 5.1: a widget with a `switch` flipbox and `show_if` rows;
  toggling the switch relayouts the panel; rows appear/disappear per
  context (mode / object type / selection); switch state survives an addon
  reload and a `iops.scripts_call_widgets_panel` hot-reload.
