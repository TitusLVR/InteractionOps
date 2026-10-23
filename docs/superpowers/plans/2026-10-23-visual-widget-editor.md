# Visual Widget Editor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** WYSIWYG edit mode for JSON-composed GPU widgets: drag/resize/reorder cells on the live widget, drag new elements in from a floating GPU palette, edit properties in the N-panel, Save/Cancel, continuous draft.

**Architecture:** Two new pure (bpy-free, pytest) modules carry all logic: `ui/widgets/editor_model.py` (the editable def document, mutations, undo/redo, preview rows) and `ui/widgets/editor_geom.py` (edit-mode hit-testing, drop targets, palette layout). A bpy runtime module `ui/widgets/editor.py` holds the single active edit session and wires it to the existing draw handler (`state.py`/`render.py`), the existing transient interact modal (`events.py`), and an N-panel (`ui/widgets/editor_panel.py`). The schema gains `span` (12-step grid), `SPACER`, and per-cell `show_if`.

**Tech Stack:** Blender 5.1+ Python (bpy, gpu via existing `ui/draw` primitives), pytest for pure modules.

**Spec:** `docs/superpowers/specs/2026-10-23-visual-widget-editor-design.md`

## Global Constraints

- Blender 5.1+. Existing `ui/widgets` architecture: persistent POST_PIXEL draw handler + transient per-gesture modal `iops.widget_interact`; no long-running modal.
- `panel.py`, `controls.py`, `predicates.py`, `persistence.py`, new `editor_model.py`, new `editor_geom.py`, and `widgets/composed.py` stay importable WITHOUT bpy (defer bpy imports to call time).
- **Lag is the anti-goal:** MOUSEMOVE handlers in edit gestures only update plain drag state and `area.tag_redraw()`. No disk I/O, no `validate_def`, no `build_controls` on MOUSEMOVE — only on commit (drop, resize release, property edit, undo/redo).
- Zero idle cost when not editing: editor keymap items exist only while a session is active.
- Grid = 12 steps (`GRID = 12`). Spans are ints 1–12.
- Python-built widgets (no `composed_def`) never enter edit mode.
- Widget JSONs live in the user widgets folder (`composed.widgets_folder()`), never in the repo.
- Run pure tests: `cd tests && python -m pytest ui/widgets -q` (baseline: 270 passed).
- Work on branch `visual-widget-editor` in the main checkout (no worktrees). The working tree has unrelated uncommitted changes (negative-scale overlay etc.) — **stage only the files your task touches**, never `git add -A`.
- Commit messages: Conventional Commits; never name any company in commit messages (public repo). End with the session attribution lines.
- Match surrounding code: comment density, docstring style, naming (`IOPS_OT_*`, `iops.*` idnames).

## Review Focus

1. **Legacy file opened then saved with no edits** must render identically after save (adjacent FLIPBOX runs, unspanned ROWs) → `test_normalize_roundtrip_renders_same_structure` in Task 3.
2. **Dropping into a full row** (spans sum to 12) must split the neighbour or refuse without corrupting spans → `test_insert_into_full_row_splits_neighbour`, `test_insert_into_full_row_of_ones_refused` in Task 3.
3. **Deleting the last row / empty widget** must stay a valid def and still accept a drop → `test_delete_last_row_leaves_empty_rows` (Task 3) and `test_drop_target_empty_panel` (Task 4).
4. **Rename onto an existing widget name** must not overwrite the other widget → `test_resolve_save_name_collision` in Task 3.
5. **Resume draft then Cancel / Undo** — Resume is one undoable commit; Cancel still restores the on-disk original → `test_resume_is_undoable` in Task 3 + live check in Task 8.

---

### Task 1: Schema — `span`, `SPACER`, per-cell `show_if`, merge exclusion, draft files

**Files:**
- Modify: `widgets/composed.py` (`ROW_TYPES`, `_clean_row_body`, `_clean_row`, `merge_flipbox_runs`, `build_controls`, `list_widget_files`, module docstring)
- Modify: `ui/widgets/controls.py` (new `Spacer`)
- Modify: `ui/widgets/__init__.py` (export `Spacer`)
- Test: `tests/ui/widgets/test_composed.py`

**Interfaces:**
- Produces:
  - `composed.GRID = 12`
  - Row def key `span: int` (1–12) on any top-level row or ROW cell; invalid/out-of-range → dropped with error message, row kept.
  - Row type `"SPACER"`: `{"type": "SPACER", "span"?: int, "height"?: float}`; `height` only meaningful top-level (px, >= 2).
  - ROW cells may carry `show_if` (same grammar as top-level, via `_clean_show_if`).
  - `composed.normalize_spans(spans: list[int|None]) -> list[int] | None` — None when every entry is None; otherwise fills missing entries with `max(1, (12 - sum_given) // n_missing)` and clips from the right so the total is <= 12 (every span >= 1).
  - ROW validation applies `normalize_spans` to its cells' spans (all-or-nothing: once any cell has a span, every cell gets one).
  - `merge_flipbox_runs` excludes FLIPBOX rows carrying `span` (like `show_if`).
  - `composed.DRAFT_SUFFIX = ".draft.json"`, `composed.draft_path(name) -> str`; `list_widget_files()` skips names ending in `DRAFT_SUFFIX`.
  - `controls.Spacer(span=None, height=None, placeholder="")` — `kind = "spacer"`, `interactive = False`; `placeholder` is the element-type label shown for incomplete elements in edit mode (Task 3/6).
  - Every control built by `build_controls` carries `_span` (int or None); Row children also carry `_show_if`.

- [ ] **Step 1: Create the branch**

Run: `git checkout -b visual-widget-editor`
Expected: `Switched to a new branch 'visual-widget-editor'`

- [ ] **Step 2: Write failing tests** in `tests/ui/widgets/test_composed.py`:

```python
def test_spacer_row_validates():
    d, errs = composed.validate_def({"name": "w", "rows": [
        {"type": "SPACER"}, {"type": "SPACER", "span": 3, "height": 12}]})
    assert errs == []
    assert d["rows"][0] == {"type": "SPACER"}
    assert d["rows"][1] == {"type": "SPACER", "span": 3, "height": 12.0}

def test_span_out_of_range_dropped_row_kept():
    d, errs = composed.validate_def({"name": "w", "rows": [
        {"type": "SECTION", "label": "A", "span": 13}]})
    assert "span" not in d["rows"][0] and errs

def test_row_spans_normalized_all_or_nothing():
    d, _ = composed.validate_def({"name": "w", "rows": [{"type": "ROW", "cells": [
        {"type": "SPACER", "span": 3},
        {"type": "BUTTON", "op": "a.b"},
        {"type": "SPACER", "span": 3}]}]})
    assert [c["span"] for c in d["rows"][0]["cells"]] == [3, 6, 3]

def test_normalize_spans():
    assert composed.normalize_spans([None, None]) is None
    assert composed.normalize_spans([4, None, None]) == [4, 4, 4]
    assert composed.normalize_spans([10, 10]) == [10, 2]
    assert composed.normalize_spans([12, None]) == [11, 1]

def test_cell_show_if_kept():
    d, errs = composed.validate_def({"name": "w", "rows": [{"type": "ROW", "cells": [
        {"type": "BUTTON", "op": "a.b", "show_if": {"mode": "OBJECT"}}]}]})
    assert d["rows"][0]["cells"][0]["show_if"] == {"mode": "OBJECT"}

def test_spanned_flipboxes_not_merged():
    rows = [{"type": "FLIPBOX", "switch": "a", "span": 12},
            {"type": "FLIPBOX", "switch": "b", "span": 12}]
    assert composed.merge_flipbox_runs(rows) == rows

def test_list_widget_files_skips_drafts(tmp_path, monkeypatch):
    for fn in ("a.json", "a.draft.json", "b.json.bak"):
        (tmp_path / fn).write_text("{}")
    monkeypatch.setattr(composed, "widgets_folder", lambda: str(tmp_path))
    assert composed.list_widget_files() == ["a.json"]

def test_build_controls_spacer_and_span():
    ctrls = composed.build_controls([
        {"type": "SPACER", "span": 4},
        {"type": "ROW", "cells": [{"type": "SECTION", "label": "x", "span": 6,
                                   "show_if": {"mode": "OBJECT"}},
                                  {"type": "SPACER", "span": 6}]}])
    assert ctrls[0].kind == "spacer" and ctrls[0]._span == 4
    cell = ctrls[1].children[0]
    assert cell._span == 6 and cell._show_if == {"mode": "OBJECT"}
```

- [ ] **Step 3: Run** `cd tests && python -m pytest ui/widgets/test_composed.py -q` — Expected: the new tests FAIL.

- [ ] **Step 4: Implement** the Interfaces above. `span` is parsed in `_clean_row` (after `_clean_row_body`) so it applies uniformly; ROW cell cleaning calls `_clean_row` (not `_clean_row_body`) so cells get `span`/`show_if`; then the ROW applies `normalize_spans`. Add `SPACER` to `ROW_TYPES`. Update the module docstring schema example with `span`/`SPACER`.

- [ ] **Step 5: Run** `cd tests && python -m pytest ui/widgets -q` — Expected: all pass (270 + new).

- [ ] **Step 6: Commit** `feat(widgets): span grid, SPACER rows and per-cell show_if in schema` (stage `widgets/composed.py ui/widgets/controls.py ui/widgets/__init__.py tests/ui/widgets/test_composed.py`).

---

### Task 2: Grid layout + cell-level visibility in the runtime

**Files:**
- Modify: `ui/widgets/panel.py` (`layout` accepts grid spec; new pure helpers)
- Modify: `ui/widgets/__init__.py` (`Widget.rows`, `Widget.control_at`)
- Modify: `ui/widgets/predicates.py` (`filter_controls` handles Row cells)
- Modify: `ui/widgets/render.py` (`_row_height`, `_control_min_width`, `compute_layout`, `_draw_control` for `spacer`)
- Test: `tests/ui/widgets/test_layout.py`, `tests/ui/widgets/test_widget_rows.py`

**Interfaces:**
- Consumes: `_span`, `_show_if` on controls, `Spacer` (Task 1).
- Produces:
  - `panel.GRID = 12`
  - `panel.grid_cells(spans: list[int], content_width: float, col_gap: float) -> list[tuple[float, float]]` — `(dx, w)` per cell, consecutive from column 0: unit `u = (content_width - col_gap*(GRID-1)) / GRID`, cell starting at column `c` with span `s` → `dx = c*(u+col_gap)`, `w = s*u + (s-1)*col_gap`.
  - `panel.grid_min_content(spans: list[int], mins: list[float], col_gap: float) -> float` — smallest content width where every cell `i` is >= `mins[i]` (`12*max_i((m_i-(s_i-1)*g)/s_i) + 11*g`, floored at 0).
  - `WidgetPanel.layout` row entry third element may be `{"spans": [..]}` → cells placed via `grid_cells` (existing float/None list spec unchanged).
  - `predicates.filter_controls(controls, ctx)` now returns, for a `Row` with any child `_show_if`, a **new** `Row` view: hidden children are replaced by `Spacer(span=child._span)` when the row is a grid row (any `_span` set), else dropped; a Row whose children are all hidden is dropped. View carries the original's `_show_if`/`_span` and `_source = original`.
  - Render: top-level control with `_span < 12` lays out as one grid cell `{"spans": [s]}`; Row with spans uses `{"spans": [...]}` and `grid_min_content` for its min width; `spacer` row height = `height` if set else `label_h + ROW_PAD_CONTROL`; `spacer` draws nothing outside edit mode.

- [ ] **Step 1: Write failing tests**

`test_layout.py`:
```python
from ui.widgets.panel import grid_cells, grid_min_content

def test_grid_cells_thirds():
    cells = grid_cells([4, 4, 4], 120.0 + 11 * 2.0, 2.0)   # u = 10
    assert [round(dx, 3) for dx, _ in cells] == [0.0, 48.0, 96.0]
    assert [round(w, 3) for _, w in cells] == [46.0, 46.0, 46.0]

def test_grid_cells_partial_row_leaves_right_empty():
    (dx, w), = grid_cells([6], 122.0, 2.0)
    assert dx == 0.0 and w == pytest.approx(6 * 10 + 5 * 2)

def test_grid_min_content():
    # 1-span cell needing 20px -> u >= 20 -> W = 240 + 22
    assert grid_min_content([1, 11], [20.0, 0.0], 2.0) == pytest.approx(262.0)

def test_layout_grid_spec():
    p = make_panel([(20.0, 3, {"spans": [3, 6, 3]})],
                   content_width=120.0 + 11 * 6.0, col_gap=6.0)
    xs = [round(c.x - p.row_rects[0][0].x, 3) for c in p.row_rects[0]]
    assert xs == [0.0, 48.0, 144.0]
```

`test_widget_rows.py` (use the real `Widget` + fake context already used in that file):
```python
def test_hidden_cell_in_grid_row_keeps_slot():   # hidden span-4 cell -> Spacer(span=4) at same index
def test_hidden_cell_in_legacy_row_collapses():  # no spans -> child removed
def test_all_cells_hidden_drops_row():
def test_control_at_resolves_through_row_view(): # control_at returns the ORIGINAL child, not the Spacer stand-in, for visible cells
```

- [ ] **Step 2: Run** `cd tests && python -m pytest ui/widgets/test_layout.py ui/widgets/test_widget_rows.py -q` — Expected: new tests FAIL.

- [ ] **Step 3: Implement** panel helpers + `layout` grid branch, `filter_controls` Row views, `Widget.control_at` indexing the view (children of the view are the original control objects except stand-in Spacers), render changes per Interfaces. Grid rows (`_span` present on any Row child, or top-level `_span < 12`) use the grid spec; everything else keeps today's hug/equal-split rules exactly.

- [ ] **Step 4: Run** `cd tests && python -m pytest ui/widgets -q` — Expected: all pass.

- [ ] **Step 5: Live smoke** (Blender via MCP, after a dev reload per `reference_dev_reload_infra`): write a temp widget JSON `vwe_grid_test.json` into the widgets folder with a `ROW` of spans `[3,6,3]` (SPACER, BUTTON, SPACER), a top-level `SECTION` with `span: 6`, and a `SPACER` with `height: 20`; `composed.load_all()`; toggle it visible; screenshot the viewport. Expected: button centered at half width, section at half width, visible gap. Also open an existing widget (e.g. `falloff_tools`) and confirm it looks unchanged. Delete the temp JSON afterwards.

- [ ] **Step 6: Commit** `feat(widgets): 12-step grid layout and per-cell visibility`.

---

### Task 3: Editor model (pure)

**Files:**
- Create: `ui/widgets/editor_model.py`
- Test: `tests/ui/widgets/test_editor_model.py`

**Interfaces:**
- Consumes: `composed.validate_def`, `composed._clean_row`, `composed.normalize_spans`, `composed.merge_flipbox_runs`, `composed.GRID`, `composed.unique_name`, `composed.sanitize_name` (import with the same try-relative / absolute-fallback pattern `build_controls` uses).
- Produces:
  - Path type: `Path = tuple[int, int | None]` — `(row, None)` = top-level row `row`; `(row, cell)` = cell `cell` inside ROW `row`. A non-ROW top-level row is addressed as `(row, None)` only.
  - Drop target type: `Target = tuple[int, int | None]` — `(row, None)` = insert as a new top-level row at index `row` (0..len); `(row, cell)` = insert into row `row` at cell index `cell` (0..ncells); a non-ROW top-level target row is first wrapped into `{"type": "ROW", "cells": [row]}` (its `show_if` moves to the ROW, its `span` stays on the cell).
  - `normalize_for_edit(wdef: dict) -> dict` — deep copy; every merged FLIPBOX run (per `merge_flipbox_runs`) becomes an explicit `ROW` of those flipboxes; every remaining top-level FLIPBOX gets `span: 12` (so it never re-merges).
  - `new_element(rtype: str) -> dict` — placeholder defaults: SECTION `{"label": "Section"}`; SPACER `{}`; ROW `{"cells": [{"type": "SPACER"}]}`; BUTTON `{"label": "Button", "op": ""}`; FLIPBOX `{"label": "Flip", "switch": ""}`; SLIDER `{"prop": "", "value_type": "FLOAT", "min": 0.0, "max": 1.0}`; PRESETS `{"target": "BEVEL", "values": [0, 0.5, 1.0]}`; BUTTONS `{"prop": "", "value_type": "FLOAT", "values": [0, 1]}`; DROPDOWN `{"label": "Dropdown", "prop": ""}`; INPUT `{"label": "Input", "prop": "", "value_type": "STRING"}`; SWATCH `{"color": [1, 1, 1, 1], "op": ""}`. Top-level FLIPBOX inserts get `span: 12`.
  - `is_complete(el: dict) -> bool` — `composed._clean_row(el)[0] is not None` (ROW: True when it has >= 1 cell; its cells are checked individually).
  - `class EditorDoc`:
    - `__init__(self, wdef: dict, history_limit: int = 200)` — stores `normalize_for_edit(wdef)` as `self.wdef`; `self.original = deepcopy(wdef)`; `self.selection: Path | None = None`; `self.dirty = False`.
    - `get(self, path) -> dict | None`
    - `commit(self, fn: Callable[[dict], bool]) -> bool` — snapshot, run `fn(self.wdef)`; on False restore snapshot and return False; on True push snapshot to undo, clear redo, `dirty = True`. Every mutator below goes through `commit`.
    - `insert(self, target: Target, element: dict) -> Path | None` — returns the new element's path (and selects it) or None if refused.
    - `move(self, src: Path, target: Target) -> Path | None` — moving a ROW container (`(r, None)` where row is ROW) only accepts `(row, None)` targets; a ROW left with 0 cells is removed; a single-cell ROW is kept. Indices of the target are interpreted BEFORE removal of `src` (the function adjusts).
    - `delete(self, path) -> bool`
    - `set_span(self, path, span: int) -> bool` — clamps to `1..(GRID - sum(other spans in the row))`; on an unspanned ROW first assigns `normalize_spans` defaults (equal split, remainder to the left cells: `[4,4,4]`, `[6,6]`, `[3,3,3,3]`, 5 cells → `[3,3,2,2,2]`); top-level non-ROW → sets the row's own `span` (1..12).
    - `set_field(self, path, key: str, value) -> bool` — `value is None` deletes the key.
    - `set_widget_field(self, key: str, value) -> bool` — title/width/space/switches/name.
    - `replace_all(self, wdef: dict) -> bool` — used by Resume Draft; one undoable commit.
    - `undo(self) -> bool`, `redo(self) -> bool`, `can_undo`, `can_redo` properties. Undo/redo keep `selection` if the path still resolves, else None.
    - `incomplete(self) -> list[Path]`
    - `preview_rows(self) -> list[dict]` — validated rows for building the live preview with a 1:1 mapping to `self.wdef["rows"]`: complete elements → their cleaned form; incomplete → `{"type": "SPACER", "span": <its span or None>, "_placeholder": "<Type>"}` (`build_controls` passes `_placeholder` to `Spacer(placeholder=...)`).
  - Insert into a row with explicit spans: new cell span = free columns if free >= 1 (capped at 4); if free == 0, split the neighbour (cell at `cell-1`, or `cell` when inserting at 0): neighbour keeps `ceil(s/2)`, new cell gets `floor(s/2)`; refuse (None) when that neighbour has span 1. Unspanned rows: append without spans.
  - `resolve_save_name(new: str, old: str, taken: set[str]) -> str` — `sanitize_name(new) or old`; if equal to `old` return it; else `unique_name(sanitized, taken - {old})`.

- [ ] **Step 1: Write failing tests** `tests/ui/widgets/test_editor_model.py` (load module like `test_composed.py` does). Tests with their key assertions:

```python
def test_normalize_roundtrip_renders_same_structure():
    # rows: SECTION, FLIPBOX a, FLIPBOX b, FLIPBOX c(show_if), BUTTON
    # after normalize_for_edit + validate_def + build_controls:
    # control kinds == ["section", "row", "flipbox", "button"]; row has 2 children
    # == same kinds/child counts as building the ORIGINAL def

def test_insert_new_row_and_select():          # insert((1, None), new_element("BUTTON")) -> (1, None); selection == (1, None)
def test_insert_into_plain_row_wraps():        # target (0, 1) on a top-level BUTTON -> rows[0]["type"] == "ROW", 2 cells, show_if moved to ROW
def test_insert_into_spanned_row_uses_free():  # spans [3,6] -> new span 3
def test_insert_into_full_row_splits_neighbour():  # [4,4,4] insert at cell 1 -> [2,2,4,4]
def test_insert_into_full_row_of_ones_refused():   # 12 x span1 -> None, wdef unchanged, can_undo False
def test_move_within_row_and_between_rows():
def test_move_last_cell_out_removes_row():
def test_move_row_container_only_to_row_targets():  # (r, c) target -> None
def test_set_span_clamps_and_assigns_defaults():    # see sequence below
def test_five_cell_default_spans():                 # [3,3,2,2,2]
def test_delete_last_row_leaves_empty_rows():       # rows == [], validate_def(doc.wdef)[0]["rows"] == []
def test_undo_redo_and_refused_commit_not_recorded():
def test_preview_rows_placeholder_keeps_mapping():  # BUTTON with op "" -> {"type": "SPACER", "_placeholder": "Button"}; len(preview_rows) == len(wdef["rows"])
def test_incomplete_lists_paths():                  # includes ROW cell paths
def test_resume_is_undoable():                      # replace_all(draft); undo -> wdef back to pre-resume
def test_resolve_save_name_collision():             # resolve_save_name("b", "a", {"a","b"}) == "b_1"
def test_resolve_save_name_unchanged():             # ("a", "a", {"a","b"}) == "a"
```

(Write exact expected values inline when implementing the tests; the comments fix the behaviour. For `test_set_span_clamps_and_assigns_defaults`, on an unspanned 3-cell ROW: `set_span((0,0), 8)` assigns defaults `[4,4,4]` first, then clamps to `12-8=4` → `[4,4,4]`; `set_span((0,1), 2)` → `[4,2,4]`; `set_span((0,0), 6)` → `[6,2,4]`; `set_span((0,0), 12)` clamps to `12-6=6` → `[6,2,4]`.)

- [ ] **Step 2: Run** `cd tests && python -m pytest ui/widgets/test_editor_model.py -q` — Expected: FAIL (module missing).

- [ ] **Step 3: Implement** `ui/widgets/editor_model.py` per Interfaces (snapshots = `copy.deepcopy` of `wdef`; history capped at `history_limit`). Add `_placeholder` handling to `composed.build_controls` (SPACER branch).

- [ ] **Step 4: Run** `cd tests && python -m pytest ui/widgets -q` — Expected: all pass.

- [ ] **Step 5: Commit** `feat(widgets): pure editor document model with undo/redo`.

---

### Task 4: Edit-mode geometry (pure)

**Files:**
- Create: `ui/widgets/editor_geom.py`
- Test: `tests/ui/widgets/test_editor_geom.py`

**Interfaces:**
- Consumes: `panel.Rect`, `panel.WidgetPanel` (`row_rects`, `padding`, `x`, `width`, `title_rect`), Task 3 `Path`/`Target` conventions.
- Produces:
  - Constants: `HANDLE_W = 6.0` (resize grip width, centred on a cell's right edge), `MOVE_THRESHOLD = 4.0` px, `EDGE_BAND = 0.25` (top/bottom fraction of a row that means "new row before/after").
  - `edit_hit(panel, row_kinds: list[bool], mx, my) -> tuple[str, Path] | None` — `row_kinds[r]` True when top-level row `r` is a ROW. Returns `("resize", path)` inside a cell's handle zone, `("cell", path)` inside a cell, `("row", (r, None))` inside the left padding gutter beside row `r`, None otherwise (title-bar hits stay with `panel.hit_test`). For a non-ROW row, cells resolve to `(r, None)`.
  - `drop_target(panel, row_kinds, mx, my, rows_only: bool = False) -> tuple[Target, tuple] | None` — target plus indicator geometry: `("hline", x, y, w)` for new-row targets (y at the gap between rows / above first / below last), `("vline", x, y, h)` for into-row targets (x at the left/right edge of the nearest cell by x-midpoint). Upper/lower `EDGE_BAND` of a row → `(r, None)` / `(r+1, None)`; middle band → into-row unless `rows_only`. Panel with zero rows → `((0, None), ("hline", ...))` anywhere inside the panel body. Outside the panel bounds → None.
  - `palette_items() -> list[tuple[str, str]]` — `(row_type, label)` in display order, with section headers as `("", "Layout")` / `("", "Controls")`: Layout = SECTION, SPACER, ROW; Controls = SLIDER, PRESETS, FLIPBOX, BUTTON, BUTTONS, DROPDOWN, INPUT, SWATCH.
  - `palette_hit(row_rects, items, mx, my) -> str | None` — the row type under the mouse (headers → None).

- [ ] **Step 1: Write failing tests** `tests/ui/widgets/test_editor_geom.py` (build panels with `WidgetPanel.layout` like `test_layout.make_panel`):

```python
def test_edit_hit_resize_beats_cell():     # x within HANDLE_W/2 of cell.x2 -> ("resize", (0, 1))
def test_edit_hit_cell_in_plain_row():     # non-ROW row -> ("cell", (0, None))
def test_edit_hit_gutter_selects_row():    # x in [panel.x, panel.x + padding) -> ("row", (1, None))
def test_drop_target_top_band_new_row_before():
def test_drop_target_bottom_band_new_row_after():
def test_drop_target_middle_into_row_right_of_cell():  # mx right of cell 0 midpoint -> ((0, 1), ("vline", ...))
def test_drop_target_rows_only():          # middle band with rows_only -> new-row target
def test_drop_target_empty_panel():        # layout([]) -> ((0, None), ("hline", ...))
def test_drop_target_outside_none():
def test_palette_items_order_and_hit():
```

- [ ] **Step 2: Run** `cd tests && python -m pytest ui/widgets/test_editor_geom.py -q` — Expected: FAIL.
- [ ] **Step 3: Implement** `ui/widgets/editor_geom.py`.
- [ ] **Step 4: Run** `cd tests && python -m pytest ui/widgets -q` — Expected: all pass.
- [ ] **Step 5: Commit** `feat(widgets): edit-mode hit testing and drop targets`.

---

### Task 5: Edit session runtime

**Files:**
- Create: `ui/widgets/editor.py`
- Modify: `ui/widgets/__init__.py` (register/unregister hooks; `Widget.rows` returns unfiltered controls while `widget._editor` is set)
- Modify: `ui/widgets/state.py` (`hide_widget` → `editor.on_widget_hidden(name)`; `load_pre` handler slot ends the session)
- Modify: `widgets/composed.py` (`unregister_composed` → `editor.on_widget_unregistered(name)`)

**Interfaces:**
- Consumes: Task 3 `EditorDoc`, `resolve_save_name`; Task 1 `draft_path`; `composed.save_def/register_composed/unregister_composed/delete_def/widget_path/load_def/build_controls`; `prefs.widget_composer.sync_from_files`; `events.rename_toggle_kmi`.
- Produces (module `editor`):
  - `class Session` with fields: `name: str` (original name), `doc: EditorDoc`, `widget` (live widget instance), `area_ptr: int`, `sidebar_was_open: bool`, `is_new: bool`, `load_problems: list[str]`, `draft_available: bool`, `palette: WidgetPanel`, `drag: dict | None` (gesture state read by render: `{"kind": "move"|"add"|"resize", "src": Path|None, "rtype": str|None, "target": Target|None, "indicator": tuple|None, "ghost": (x, y, label)}`).
  - `active() -> Session | None`
  - `begin(context, name: str, is_new: bool = False) -> Session | None` — refuses (returns None, reports via return) for non-composed widgets; ends any other active session first (implicit exit); re-reads the raw file with `composed.load_def` to collect `load_problems`; builds `EditorDoc(widget.composed_def)`; sets `widget._editor = session`; places palette panel left of the widget (clamped later at layout); opens the sidebar (`space.show_region_ui = True`, then `try: region.active_panel_category = "iOps"` on the UI region, except → ignore); adds editor keymap items (Task 7 operator) in "3D View" and "Image"; `draft_available = os.path.isfile(composed.draft_path(name))`; `rebuild_preview()`.
  - `rebuild_preview()` — `widget.controls = composed.build_controls(doc.preview_rows(), ...)` with the widget's switch store; updates `widget.panel.title`, `widget.min_content_w`; `state.tag_redraw_all()`. Called after every commit/undo/redo — never on MOUSEMOVE.
  - `after_commit()` — `rebuild_preview()` + `write_draft()` + sync N-panel props (Task 8 hook `editor_panel.sync_from_selection`).
  - `write_draft()` — plain `json.dump` of `doc.wdef` to `draft_path(session.name)` (atomic tmp+replace), no bpy data access.
  - `save() -> tuple[bool, str]` — fails with message listing incomplete paths if `doc.incomplete()`; writes `<name>.json.bak` once (copy of the original file, only if `load_problems` and no .bak exists); resolves name via `resolve_save_name`; on rename: save new, `register_composed`, hide+unregister+delete old, `events.rename_toggle_kmi(old, new)`, show the new widget at the old position; else `save_def` + `register_composed`; deletes the draft; `sync_from_files(select=name)`; `end()`.
  - `cancel()` — deletes the draft; if `is_new`, hides/unregisters/deletes the widget file and syncs prefs; else re-registers the original via `register_composed(doc.original)`; `end()`.
  - `end(keep_draft: bool = True)` — implicit-exit path: clears `widget._editor`, rebuilds the widget from its unchanged `composed_def`, restores `show_region_ui` if it was closed, removes editor keymap items, clears `_session`; redraw.
  - `on_widget_hidden(name)`, `on_widget_unregistered(name)` — `end()` when `name` is the session widget (draft stays on disk).
  - `discard_draft()`, `resume_draft() -> bool` (loads draft JSON, `doc.replace_all`, `after_commit`, deletes nothing until Save/Cancel; sets `draft_available = False`).
  - `register()` / `unregister()` — install/remove a `@persistent load_pre` handler calling `end()`; `unregister()` calls `end()` (draft already on disk from the last commit).

- [ ] **Step 1: Implement** `editor.py` and the hooks per Interfaces. (No pytest: bpy runtime; pure parts are covered by Tasks 3–4.)
- [ ] **Step 2: Run** `cd tests && python -m pytest ui/widgets -q` — Expected: still all pass (no pure regressions).
- [ ] **Step 3: Live check via MCP** (dev reload first; confirm the open blend is a throwaway test file before touching state — `feedback_verify_test_blend`): with a copy `vwe_test.json` of `falloff_tools`, run in Blender: `s = editor.begin(ctx, "vwe_test")`; `s.doc.insert((0, None), editor_model.new_element("BUTTON"))`; `editor.after_commit()` → draft file exists; screenshot shows a placeholder row; `editor.end()` → widget back to original, sidebar restored, draft still on disk; `begin` again → `draft_available is True`; `resume_draft()`; set the button op via `doc.set_field((0, None), "op", "iops.mesh_falloff_move")`; `save()` → file contains the new row, draft gone. Repeat with a rename to an existing name → saved as `<name>_1`, old file gone, toggle kmi carried. Then addon disable/enable with a session active → no errors, session gone, draft present. Expected: every listed condition true; report the dict of checks.
- [ ] **Step 4: Commit** `feat(widgets): widget edit session with drafts, save and cancel`.

---

### Task 6: Edit-mode rendering + palette

**Files:**
- Modify: `ui/widgets/render.py` (edit overlays; `draw_palette(context, session)`; in-context forced while editing)
- Modify: `ui/widgets/state.py` (`_draw_widgets` draws the palette for the session's area after widgets)

**Interfaces:**
- Consumes: `editor.active()`, `Session.drag`, `Session.doc.selection`, `editor_geom.palette_items`, `predicates.eval_show_if`/`build_eval_ctx` (to mark hidden rows), `controls.Spacer.placeholder`.
- Produces:
  - `render.EDIT_TAG = "EDITING"`; edit colors: outline/selection/handles `Role.HUD_ACTIVE_VALUE`, grid lines `Role.HUD_LABEL_INACTIVE` at 0.25, drop indicator `Role.HUD_ACTIVE_VALUE` (2 px), spacer = dashed-look outline `Role.HUD_LABEL_INACTIVE` at 0.6 + faint fill, placeholder text = type label in `Role.HUD_STATS_ERROR`.
  - While `widget._editor` is set: `compute_layout` lays out ALL rows (no `show_if`, poll ignored); controls draw dimmed at `DISABLED_ALPHA` when their `show_if` is false in the current context, with a small "hidden" glyph at the cell's right; title bar shows `EDIT_TAG`; 12 faint grid ticks per row; selection outline + `HANDLE_W` grip on the selected cell; drag ghost (label box under the cursor) and indicator from `session.drag`.
  - `render.compute_palette_layout(context, session) -> theme` — lays out `session.palette` (`WidgetPanel`) with one row per `palette_items()` entry; `draw_palette` draws title "Add", headers as sections, items as outlined buttons.

- [ ] **Step 1: Implement.** Keep per-frame cost flat: no def validation in draw; only reads of `session.drag` and existing controls.
- [ ] **Step 2: Run** `cd tests && python -m pytest ui/widgets -q` — Expected: all pass.
- [ ] **Step 3: Live check via MCP:** begin a session on `vwe_test`, set `session.drag` manually to an "add" drag with a target/indicator and a selection, screenshot. Expected: orange outline, EDITING tag, grid ticks, palette left of the widget, indicator line, rows with `show_if` false drawn dimmed. Then `end()` → normal render unchanged (compare with pre-session screenshot).
- [ ] **Step 4: Commit** `feat(widgets): edit-mode overlays and add palette`.

---

### Task 7: Edit gestures + editor hotkeys

**Files:**
- Modify: `ui/widgets/events.py` (edit routing in `IOPS_OT_widget_interact`; new `IOPS_OT_widget_editor_key`; pen button → `editor.begin`; editor kmi helpers)
- Modify: `operators/hotkeys/save_hotkeys.py:16` (add `"iops.widget_editor_key"` to `NEVER_SAVE`)
- Modify: `operators/preferences/io_widgets.py` (`IOPS_OT_WidgetEdit` keeps opening JSON — now only used by the N-panel "Open JSON" button; update `bl_description`)

**Interfaces:**
- Consumes: `editor.active()/begin()/after_commit()`, `Session.drag`, `editor_geom.edit_hit/drop_target/palette_hit/MOVE_THRESHOLD`, `EditorDoc.insert/move/set_span/delete/undo/redo`, `editor_model.new_element`.
- Produces:
  - In `invoke`, before normal routing: if a session is active and the click is on the palette panel or the session widget, route to edit gestures (title-bar drag and close keep their current behaviour on both panels; the pen on the edited widget is inert). Modes:
    - `ed_add`: press on a palette item → `drag = {"kind": "add", "rtype": ...}`; MOUSEMOVE updates `target/indicator/ghost` via `drop_target(... rows_only = rtype == "ROW")`; release with a target → `doc.insert(target, new_element(rtype))` → `after_commit()`; release without target → nothing.
    - `ed_resize`: press on a handle → MOUSEMOVE computes the snapped span from mouse x against the row's grid (`round((mx - row_left + gap) / (u + gap)) - start_col`), stores it in `drag["span"]` and redraws a preview outline; release → `doc.set_span(path, span)` → `after_commit()`.
    - `ed_move`: press on a cell / gutter → `doc.selection = path`, N-panel sync, redraw; after `MOVE_THRESHOLD` px movement becomes a move drag (`rows_only` for ROW containers); release with target → `doc.move(src, target)` → `after_commit()`; release without movement → selection only.
    - ESC/RMB during any edit drag → clear `drag`, no change.
  - Clicks on other widgets while editing behave normally.
  - `IOPS_OT_widget_editor_key` (`bl_idname = "iops.widget_editor_key"`, `action: EnumProperty(items=UNDO, REDO, DELETE)`, `bl_options = {"INTERNAL"}`): poll = `editor.active() is not None`; `invoke` PASS_THROUGHs unless the mouse is over the session widget or the palette in the session's area; performs `doc.undo()` / `doc.redo()` / `doc.delete(selection)` + `after_commit()`.
  - `events.add_editor_kmis()` / `events.remove_editor_kmis()` — Ctrl+Z → UNDO, Ctrl+Shift+Z → REDO, X and DEL → DELETE, in the addon "3D View" and "Image" keymaps; called by `editor.begin`/`editor.end` (replace the Task 5 stub calls). Excluded from hotkey save (add the idname to `NEVER_SAVE` where `iops.widget_interact` is listed).
  - Title-bar pen (`mode == "title_edit"`) now calls `editor.begin(context, widget.name)` instead of `bpy.ops.iops.widget_edit`.

- [ ] **Step 1: Implement.** MOUSEMOVE branches only touch `session.drag` + `_tag_redraw(context)`.
- [ ] **Step 2: Run** `cd tests && python -m pytest ui/widgets -q` — Expected: all pass.
- [ ] **Step 3: Live check via MCP** (modal events can't be injected): verify kmis appear on `begin` and vanish on `end` (count `iops.widget_editor_key` items in addon keyconfig before/during/after); call the key operator's logic paths directly for UNDO/DELETE; confirm `iops.widget_interact` still PASS_THROUGHs off-panel. Record in the task report that drag feel (add/move/resize/lag) is a **user-owned manual check**.
- [ ] **Step 4: Commit** `feat(widgets): drag, resize and add gestures in widget edit mode`.

---

### Task 8: N-panel editor, properties and operators; New Widget flow

**Files:**
- Create: `ui/widgets/editor_panel.py` (PropertyGroup, panels, operators, `sync_from_selection`)
- Modify: `__init__.py` (register `editor_panel` classes; `WindowManager.iops_widget_editor` PointerProperty; call `editor.register/unregister`)
- Modify: `operators/preferences/io_widgets.py` (`IOPS_OT_WidgetDefAdd` → blank def `rows: []`, show it in the largest VIEW_3D, `editor.begin(..., is_new=True)`)
- Modify: `prefs/widget_composer.py` (Add button tooltip text if needed)

**Interfaces:**
- Consumes: `editor.*` (Task 5), `EditorDoc.set_field/set_widget_field/get/selection/can_undo/can_redo`, `composed.parse_values`, `composed.VALUE_TYPES`, `composed.WIDGET_SPACES`.
- Produces:
  - `IOPS_WidgetEditorProps(PropertyGroup)` on `WindowManager.iops_widget_editor`, fields with `update` callbacks writing through `doc.set_field(selection, key, value)` → `editor.after_commit()`, guarded by a module `_SYNC` flag (same pattern as `prefs/widget_composer.py`): `label`, `op`, `op_kwargs` (JSON text; invalid JSON → report, no write), `role` (enum default/error), `prop`, `data`, `switch`, `target` (enum BEVEL/CREASE/SHARP/SEAM/FREESTYLE), `binding` (enum PROP/DATA/SWITCH/TARGET per type, switching clears the others), `value_type` (enum from `VALUE_TYPES`), `min`, `max`, `snap`, `fmt`, `values` (text, `parse_values`), `items` (text `ID:Label, ID2`), `labels` (text `ID=Label; ID2=Label`), `items_from`, `unit`, `color` (FloatVector size 4, subtype COLOR), `show_alpha`, `span` (int 0–12, 0 = unset), `height`, show_if fields `si_mode`, `si_object_type`, `si_selection`, `si_prop`, `si_switch`, `si_equals` (empty = absent); widget fields `w_name`, `w_title`, `w_width` (0 = unset), `w_space_view3d`, `w_space_image`, `w_switches` (text `name=1, other=0`).
  - `sync_from_selection()` — fills the props from the selected element / widget under `_SYNC`.
  - Panels `IOPS_PT_widget_editor_view3d` (VIEW_3D) and `IOPS_PT_widget_editor_image` (IMAGE_EDITOR), `bl_region_type = "UI"`, `bl_category = "iOps"`, `bl_label = "Widget Editor"`, poll = session active; shared draw: draft banner (Resume / Discard) when `draft_available`; load-problems warning box; "Selected: <Type>" block showing only fields relevant to that type and binding; Widget block; row of Undo / Redo / Delete; Save / Cancel; "Open JSON" (`iops.widget_edit`).
  - Operators (`bl_options = {"INTERNAL"}`): `iops.widget_editor_save` (reports `save()` failures as ERROR), `iops.widget_editor_cancel`, `iops.widget_editor_undo`, `iops.widget_editor_redo`, `iops.widget_editor_delete`, `iops.widget_editor_resume_draft`, `iops.widget_editor_discard_draft`, `iops.widget_editor_pick_operator` (`bl_property = "op_enum"`, `invoke_search_popup`, items built lazily from `dir(bpy.ops)` × submodule names as `"mod.name"`, cached per session; writes `op`).

- [ ] **Step 1: Implement.**
- [ ] **Step 2: Run** `cd tests && python -m pytest ui/widgets -q` — Expected: all pass.
- [ ] **Step 3: Live check via MCP** (dev reload, test blend): pen → (call `editor.begin`) N-panel opens on iOps tab (report whether `active_panel_category` assignment worked); screenshot the panel with a BUTTON selected; set label/op through the props → widget preview updates; type invalid JSON into `op_kwargs` → no change + report; Save → file updated; prefs "+" → new blank widget visible in edit mode; Cancel on it → file deleted, list synced. Review-focus 5: Resume draft, then Cancel → on-disk file unchanged; Resume then Undo → pre-resume doc.
- [ ] **Step 4: Commit** `feat(widgets): widget editor N-panel and New Widget flow`.

---

### Task 9: Docs + final verification

**Files:**
- Modify: `ai_skills/iops-custom-widgets/schema-reference.md`, `ai_skills/iops-custom-widgets/SKILL.md` (`span`, `SPACER`, cell `show_if`, spanned flipboxes don't merge, drafts/.bak files)
- Modify: user docs page covering widgets under `docs/` (find with `grep -ril widget docs/*.md docs/ui`), adding a "Visual Widget Editor" section (enter via pen, palette, N-panel, snapping, spacers, drafts)
- Modify: `.superpowers/` stays untracked (already in `.gitignore`)

- [ ] **Step 1: Write the docs.**
- [ ] **Step 2: Run** `cd tests && python -m pytest -q` — Expected: whole suite passes.
- [ ] **Step 3: Commit** `docs(widgets): visual widget editor and grid schema`.
- [ ] **Step 4: Hand the user the manual checklist** (drag feel / no lag during add, move, resize; Ctrl+Z over vs off the widget; X over the widget vs mesh delete elsewhere; palette drag; resize snapping at halves/thirds/quarters).
- [ ] **Step 5: Squash** the branch's feature commits into one commit before finishing (user preference), then use superpowers:finishing-a-development-branch.
