# Dropdown Scroll + Type-to-Filter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Open widget dropdowns clamp to the region (flip up / scroll) and filter as you type, so every item of a long list is reachable.

**Architecture:** All list math (layout, flip, filtering, scrolling, hit-test) lives in a pure `DropdownState` class in `ui/widgets/controls.py` (same pattern as `TextEditState` — no bpy, pytest-covered). `ui/widgets/events.py` maps Blender events to state-method calls; `ui/widgets/render.py` draws whatever `DropdownState.window()` / `.rects()` return. Render and hit-test share one geometry source so they can never disagree.

**Tech Stack:** Python 3.11 (Blender 5.1 addon), pure-stdlib control logic, pytest for pure parts, Blender MCP for live verification.

**Spec:** `docs/superpowers/specs/2026-07-15-dropdown-scroll-filter-design.md`

## Global Constraints

- `ui/widgets/controls.py` stays importable WITHOUT bpy (pure stdlib) — never import bpy or render there.
- New params on `dropdown_item_rects` / `dropdown_index_at` must default so existing call sites and tests pass unchanged (`flipped=False, field_h=0.0`).
- Coordinate system: region pixels, y grows UP, y=0 at region bottom. A field's rect is (x, y, w, h) with y its BOTTOM edge.
- Run tests with: `python -m pytest tests/ui/widgets/test_controls.py -v` from repo root `D:\git\InteractionOps`.
- Commit after each task; message style `feat(widgets): ...` / `test(widgets): ...`. Never mention CCP in any commit message (public repo).
- Do NOT commit `operators/object_uvmaps_add_remove.py` — it has unrelated pre-existing local changes. Stage files explicitly, never `git add -A`.

---

### Task 1: Pure geometry — `dropdown_layout` + flipped rects/hit-test

**Files:**
- Modify: `ui/widgets/controls.py` (currently ~505–521: `dropdown_item_rects`, `dropdown_index_at`)
- Test: `tests/ui/widgets/test_controls.py` (existing dropdown-geometry section ~line 330)

**Interfaces:**
- Consumes: nothing new.
- Produces:
  - `dropdown_layout(field_y, field_h, item_h, n, region_h) -> (flipped: bool, visible: int, max_offset: int)`
  - `dropdown_item_rects(rect_x, rect_y, rect_w, item_h, n, flipped=False, field_h=0.0) -> [(x, y, w, h)]`
  - `dropdown_index_at(my, rect_x, rect_y, rect_w, item_h, n, flipped=False, field_h=0.0) -> int`

- [ ] **Step 1: Write the failing tests**

Append to the "Open-dropdown geometry" section of `tests/ui/widgets/test_controls.py` (after `test_dropdown_index_at_hits_and_misses`), and add `dropdown_layout` to the existing `from ... import` at the top of the file (line ~8):

```python
def test_dropdown_layout_fits_below_opens_down():
    # below = field_y = 100 -> 3*20=60 fits: open down, all visible.
    assert dropdown_layout(100.0, 20.0, 20.0, 3, 400.0) == (False, 3, 0)


def test_dropdown_layout_flips_up_when_more_room_above():
    # below=60, above=400-60-20=320; 10 items don't fit below but do above.
    assert dropdown_layout(60.0, 20.0, 20.0, 10, 400.0) == (True, 10, 0)


def test_dropdown_layout_scrolls_when_nowhere_fits():
    # below=100 (5 cells), above=280 (14 cells), n=20 -> up, 14 visible.
    assert dropdown_layout(100.0, 20.0, 20.0, 20, 400.0) == (True, 14, 6)


def test_dropdown_layout_visible_floor_three():
    # below=30, above=70-30-20=20: nothing fits; floor of 3 still applies.
    assert dropdown_layout(30.0, 20.0, 20.0, 10, 70.0) == (False, 3, 7)


def test_dropdown_layout_zero_items_is_one_placeholder_cell():
    # n=0 lays out ONE cell (the "no match" placeholder).
    assert dropdown_layout(100.0, 20.0, 20.0, 0, 400.0) == (False, 1, 0)


def test_dropdown_item_rects_flipped_stack_up_reading_order():
    rects = dropdown_item_rects(10.0, 100.0, 50.0, 20.0, 3,
                                flipped=True, field_h=20.0)
    # Field top = 120. rects[0] is the visually TOPMOST cell (reading
    # order top->bottom matches the non-flipped list); rects[-1] sits
    # directly above the field.
    assert rects[0] == (10.0, 160.0, 50.0, 20.0)
    assert rects[1] == (10.0, 140.0, 50.0, 20.0)
    assert rects[2] == (10.0, 120.0, 50.0, 20.0)


def test_dropdown_index_at_flipped():
    args = (10.0, 100.0, 50.0, 20.0, 3)
    assert dropdown_index_at(170.0, *args, flipped=True, field_h=20.0) == 0
    assert dropdown_index_at(125.0, *args, flipped=True, field_h=20.0) == 2
    assert dropdown_index_at(90.0, *args, flipped=True, field_h=20.0) == -1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/ui/widgets/test_controls.py -v -k dropdown`
Expected: new tests FAIL — `ImportError: cannot import name 'dropdown_layout'`. Fix nothing else; existing dropdown tests must still be collected.

- [ ] **Step 3: Implement**

In `ui/widgets/controls.py`, replace the existing `dropdown_item_rects` and `dropdown_index_at` (lines ~505–521) with:

```python
def dropdown_layout(field_y, field_h, item_h, n, region_h):
    """(flipped, visible, max_offset) for an open list of n filtered items.

    Space below the field = field_y (cells stack down toward y=0); space
    above = region_h - field_y - field_h. If everything fits below, open
    downward with no scroll. Otherwise open toward the larger side and
    clamp `visible` to what fits (floored at 3 so a cramped region still
    shows a usable list). n=0 lays out ONE cell — the "no match"
    placeholder. Pure."""
    n_cells = max(1, n)
    below = field_y
    above = region_h - field_y - field_h
    if n_cells * item_h <= below:
        return (False, n_cells, 0)
    flipped = above > below
    space = above if flipped else below
    visible = min(n_cells, max(3, int(space // item_h)))
    return (flipped, visible, max(0, n_cells - visible))


def dropdown_item_rects(rect_x, rect_y, rect_w, item_h, n,
                        flipped=False, field_h=0.0):
    """Geometry for an open dropdown list of n cells. Not flipped: cells
    stack DOWNWARD from the field's bottom edge (`rect_y`), item 0
    directly below the field. Flipped: cells stack UPWARD from the
    field's top edge (`rect_y + field_h`), but rects[0] is still the
    visually TOPMOST cell so reading order (top->bottom) matches the
    non-flipped list. Returns [(x, y, w, h)] in item order. Shared by
    render (draw) and events (hit-test) so the two never disagree.
    Pure."""
    if not flipped:
        return [(rect_x, rect_y - (i + 1) * item_h, rect_w, item_h)
                for i in range(n)]
    top = rect_y + field_h
    return [(rect_x, top + (n - 1 - i) * item_h, rect_w, item_h)
            for i in range(n)]


def dropdown_index_at(my, rect_x, rect_y, rect_w, item_h, n,
                      flipped=False, field_h=0.0):
    """Which open-dropdown item a pixel y falls in; -1 when outside the
    list. (x is not tested — the list spans the field width.) Pure."""
    for i, (_x, y, _w, h) in enumerate(
            dropdown_item_rects(rect_x, rect_y, rect_w, item_h, n,
                                flipped=flipped, field_h=field_h)):
        if y <= my <= y + h:
            return i
    return -1
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/ui/widgets/test_controls.py -v`
Expected: ALL pass, including the pre-existing `test_dropdown_item_rects_stack_downward` / `test_dropdown_index_at_hits_and_misses` (defaults preserve old behavior).

- [ ] **Step 5: Commit**

```powershell
git add ui/widgets/controls.py tests/ui/widgets/test_controls.py && git commit -m "feat(widgets): dropdown layout with flip-up and scroll window"
```

---

### Task 2: Pure state — `dropdown_filter` + `DropdownState`

**Files:**
- Modify: `ui/widgets/controls.py` (add right after `dropdown_index_at`)
- Test: `tests/ui/widgets/test_controls.py`

**Interfaces:**
- Consumes: Task 1's `dropdown_layout` / `dropdown_item_rects` / `dropdown_index_at`.
- Produces (used verbatim by Tasks 3–4):
  - `dropdown_filter(items, needle) -> [(ident, display)]`
  - `class DropdownState` with constructor `DropdownState(items, field, region_h, item_h, current=None)` where `field` is a plain `(x, y, w, h)` float tuple, and members: `.items .field .region_h .item_h .filter .offset .hover .flipped .visible .max_offset`, methods `.filtered() .window() .relayout() .rects() .clipped_above() .clipped_below() .scroll(delta) .index_at(my) .in_list(my) .type_char(ch) .backspace() .clear_filter() .hovered()`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/ui/widgets/test_controls.py`; add `dropdown_filter, DropdownState` to the import at the top:

```python
# ----------------------------------------------------------------------
# DropdownState (open-dropdown scroll/filter state)
# ----------------------------------------------------------------------
DD_ITEMS = [("A", "Alpha"), ("B", "Bravo"), ("C", "Charlie"),
            ("D", "Delta"), ("E", "Echo"), ("F", "Foxtrot"),
            ("G", "Golf"), ("H", "Hotel"), ("I", "India"),
            ("J", "Juliett")]


def test_dropdown_filter_case_insensitive_substring():
    assert dropdown_filter(DD_ITEMS, "OT") == [("F", "Foxtrot"),
                                               ("H", "Hotel")]
    assert dropdown_filter(DD_ITEMS, "") == DD_ITEMS
    assert dropdown_filter(DD_ITEMS, "zz") == []


def test_dd_state_fits_below_shows_all():
    dd = DropdownState(DD_ITEMS, (10.0, 300.0, 50.0, 20.0), 400.0, 20.0)
    assert (dd.flipped, dd.visible, dd.max_offset) == (False, 10, 0)
    assert dd.hover == -1 and dd.offset == 0


def test_dd_state_open_centers_current_value():
    # below=60 (3), above=160-80=80 (4) -> flipped, visible 4, max 6.
    dd = DropdownState(DD_ITEMS, (10.0, 60.0, 50.0, 20.0), 160.0, 20.0,
                       current="H")
    assert (dd.flipped, dd.visible, dd.max_offset) == (True, 4, 6)
    assert dd.hover == 7
    assert dd.offset == 5              # 7 - 4//2, clamped to [0, 6]
    assert dd.window()[0][0] == "F"


def test_dd_state_scroll_clamps():
    dd = DropdownState(DD_ITEMS, (10.0, 60.0, 50.0, 20.0), 160.0, 20.0)
    dd.scroll(100)
    assert dd.offset == 6
    assert dd.clipped_above() and not dd.clipped_below()
    dd.scroll(-100)
    assert dd.offset == 0
    assert dd.clipped_below() and not dd.clipped_above()


def test_dd_state_type_filters_and_resets_window():
    dd = DropdownState(DD_ITEMS, (10.0, 60.0, 50.0, 20.0), 160.0, 20.0)
    dd.scroll(3)
    dd.type_char("o")
    # displays containing "o": Bravo Echo Foxtrot Golf Hotel
    assert [i for i, _ in dd.filtered()] == ["B", "E", "F", "G", "H"]
    assert dd.offset == 0 and dd.hover == 0
    assert dd.visible == 4             # relayout against 5 filtered items
    dd.type_char("t")                  # Foxtrot, Hotel
    assert len(dd.filtered()) == 2
    assert (dd.flipped, dd.visible) == (False, 2)   # 2 cells now fit below
    dd.backspace()
    assert len(dd.filtered()) == 5
    dd.clear_filter()
    assert dd.filter == "" and len(dd.filtered()) == 10


def test_dd_state_no_match_placeholder():
    dd = DropdownState(DD_ITEMS, (10.0, 300.0, 50.0, 20.0), 400.0, 20.0)
    dd.type_char("z")
    dd.type_char("z")
    assert dd.filtered() == []
    assert dd.hover == -1 and dd.hovered() is None
    assert dd.index_at(290.0) == -1    # placeholder cell not pickable
    assert dd.in_list(290.0)           # ...but still swallows the click
    assert len(dd.rects()) == 1        # one "no match" cell drawn


def test_dd_state_index_at_maps_through_offset():
    dd = DropdownState(DD_ITEMS, (10.0, 300.0, 50.0, 20.0), 400.0, 20.0)
    # Down-stacked from y=300: window[0] spans 280-300, window[1] 260-280.
    assert dd.index_at(290.0) == 0
    assert dd.index_at(265.0) == 1
    assert dd.index_at(310.0) == -1    # inside the field itself


def test_dd_state_index_at_flipped_with_offset():
    dd = DropdownState(DD_ITEMS, (10.0, 60.0, 50.0, 20.0), 160.0, 20.0)
    dd.scroll(2)                       # window = items 2..5, flipped
    # field top=80; rects[0] topmost at 140-160 -> window[0] -> item 2.
    assert dd.index_at(150.0) == 2
    assert dd.index_at(85.0) == 5      # bottom cell -> window[3] -> item 5
    assert dd.in_list(100.0) and not dd.in_list(170.0)


def test_dd_state_hovered_returns_pair():
    dd = DropdownState(DD_ITEMS, (10.0, 300.0, 50.0, 20.0), 400.0, 20.0,
                       current="C")
    assert dd.hovered() == ("C", "Charlie")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/ui/widgets/test_controls.py -v -k "dd_state or dropdown_filter"`
Expected: FAIL — `ImportError: cannot import name 'dropdown_filter'`.

- [ ] **Step 3: Implement**

In `ui/widgets/controls.py`, add directly after `dropdown_index_at`:

```python
def dropdown_filter(items, needle):
    """Filter (identifier, display) pairs by case-insensitive substring
    match on the DISPLAY name; empty needle returns everything. Pure."""
    if not needle:
        return list(items)
    low = needle.lower()
    return [(ident, disp) for ident, disp in items if low in disp.lower()]


class DropdownState:
    """Pure state of one open dropdown: the full item list, the typed
    filter, and the scroll window + hover over the filtered view. Owns
    all list math (layout/flip, filtering, scrolling, hit-testing) so the
    events modal stays a thin event->method mapping and render just draws
    `window()` at `rects()`. `hover`/`offset`/`index_at` all index into
    `filtered()`, never into `items`. No bpy — fully pytest-covered, same
    pattern as TextEditState. `field` is the owning field's rect as plain
    (x, y, w, h) floats, captured at open time (the panel cannot move
    while the dropdown modal owns input)."""

    def __init__(self, items, field, region_h, item_h, current=None):
        self.items = list(items)       # full [(ident, display), ...]
        self.field = tuple(field)      # (x, y, w, h)
        self.region_h = float(region_h)
        self.item_h = float(item_h)
        self.filter = ""
        self.offset = 0                # first visible index in filtered()
        self.hover = -1                # hovered index in filtered(); -1 none
        self.flipped = False
        self.visible = 0
        self.max_offset = 0
        self.relayout()
        if current is not None:
            for i, (ident, _disp) in enumerate(self.items):
                if ident == current:
                    # Start hovering the current value, window centered
                    # on it so it's visible even deep in a long list.
                    self.hover = i
                    self.offset = max(0, min(self.max_offset,
                                             i - self.visible // 2))
                    break

    # -- filtered view ---------------------------------------------------
    def filtered(self):
        return dropdown_filter(self.items, self.filter)

    def window(self):
        """The visible slice of filtered() — exactly what render draws."""
        return self.filtered()[self.offset:self.offset + self.visible]

    # -- geometry ----------------------------------------------------------
    def relayout(self):
        _x, y, _w, h = self.field
        self.flipped, self.visible, self.max_offset = dropdown_layout(
            y, h, self.item_h, len(self.filtered()), self.region_h)
        self.offset = max(0, min(self.offset, self.max_offset))

    def rects(self):
        """Cell rects for the visible window (one placeholder cell when
        the filter matches nothing). rects()[i] belongs to window()[i]."""
        x, y, w, h = self.field
        n = max(1, len(self.window()))
        return dropdown_item_rects(x, y, w, self.item_h, n,
                                   flipped=self.flipped, field_h=h)

    def clipped_above(self):
        return self.offset > 0

    def clipped_below(self):
        return self.offset + self.visible < len(self.filtered())

    # -- interaction -------------------------------------------------------
    def scroll(self, delta):
        """+1 reveals later items, -1 earlier; clamped."""
        self.offset = max(0, min(self.offset + delta, self.max_offset))

    def index_at(self, my):
        """filtered() index under pixel y; -1 outside the list or on the
        no-match placeholder cell."""
        if not self.filtered():
            return -1
        x, y, w, h = self.field
        i = dropdown_index_at(my, x, y, w, self.item_h,
                              len(self.window()),
                              flipped=self.flipped, field_h=h)
        return self.offset + i if i >= 0 else -1

    def in_list(self, my):
        """y within the open list's vertical span (including the no-match
        placeholder) — used to swallow clicks instead of closing."""
        rs = self.rects()
        lo = min(r[1] for r in rs)
        hi = max(r[1] + r[3] for r in rs)
        return lo <= my <= hi

    def type_char(self, ch):
        self.filter += ch
        self._filter_changed()

    def backspace(self):
        if self.filter:
            self.filter = self.filter[:-1]
            self._filter_changed()

    def clear_filter(self):
        self.filter = ""
        self._filter_changed()

    def _filter_changed(self):
        self.offset = 0
        self.hover = 0 if self.filtered() else -1
        self.relayout()

    def hovered(self):
        """(ident, display) under hover, or None."""
        flt = self.filtered()
        if 0 <= self.hover < len(flt):
            return flt[self.hover]
        return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/ui/widgets/test_controls.py -v`
Expected: ALL pass.

- [ ] **Step 5: Commit**

```powershell
git add ui/widgets/controls.py tests/ui/widgets/test_controls.py && git commit -m "feat(widgets): DropdownState with filter, scroll and flip"
```

---

### Task 3: Events — wire modal to DropdownState

**Files:**
- Modify: `ui/widgets/events.py` — import (line ~27), the `widget._dropdown = None` comment (line ~140), the dropdown branch of `_begin_gesture` (lines ~243–257), and the whole dropdown-modal section (lines ~435–475: `_dd_index_at`, `_modal_dropdown`, `_close_dropdown`).

**Interfaces:**
- Consumes: `DropdownState` (Task 2, exact API above); `render.DROPDOWN_ITEM_H` (existing constant, render.py line 52).
- Produces: `widget._dropdown` now holds a `DropdownState` (or `None`) — Task 4's render reads `.window() .rects() .offset .hover .filter .field .clipped_above() .clipped_below()`.

- [ ] **Step 1: Update the import and comment**

Line 27, replace:
```python
from .controls import TextEditState, dropdown_index_at
```
with:
```python
from .controls import TextEditState, DropdownState
```

Line 140, replace:
```python
        widget._dropdown = None        # (where, items, hover) while open
```
with:
```python
        widget._dropdown = None        # DropdownState while open
```

- [ ] **Step 2: Rewrite the dropdown branch of `_begin_gesture`**

Replace the existing `if control.kind == "dropdown":` block (lines ~243–257) with:

```python
        if control.kind == "dropdown":
            # In-overlay item list: opens below/above the field (whichever
            # fits), scrolls when clipped, filters as you type. Empty list
            # (no items, no labels) -> swallow.
            items = control.items(context)
            if not items:
                return None
            from . import render
            cur, _ = control.get(context)
            r = self._rect
            self._control = control
            self._dd = DropdownState(items, (r.x, r.y, r.w, r.h),
                                     context.region.height,
                                     render.DROPDOWN_ITEM_H, current=cur)
            self._mode = "dropdown_open"
            self._widget._dropdown = self._dd
            return self._begin_modal(context)
```

- [ ] **Step 3: Rewrite the dropdown-modal section**

Replace everything from the `# In-overlay dropdown list (mode "dropdown_open")` banner through `_close_dropdown` (lines ~435–475) with:

```python
    # ------------------------------------------------------------------
    # In-overlay dropdown list (mode "dropdown_open")
    # ------------------------------------------------------------------
    def _modal_dropdown(self, context, event):
        dd = self._dd
        mx, my = event.mouse_region_x, event.mouse_region_y
        et, ev = event.type, event.value

        if et == "ESC" and ev == "PRESS":
            if dd.filter:
                dd.clear_filter()          # first ESC clears the filter
                _tag_redraw(context)
                return {"RUNNING_MODAL"}
            return self._close_dropdown(context)

        if et in {"RET", "NUMPAD_ENTER"} and ev == "PRESS":
            picked = dd.hovered()
            if picked is not None:
                return self._dd_pick(context, picked[0])
            return {"RUNNING_MODAL"}

        if et in {"WHEELUPMOUSE", "WHEELDOWNMOUSE"} and ev == "PRESS":
            dd.scroll(1 if et == "WHEELDOWNMOUSE" else -1)
            dd.hover = dd.index_at(my)     # window moved under the mouse
            _tag_redraw(context)
            return {"RUNNING_MODAL"}

        if et in {"MOUSEMOVE", "INBETWEEN_MOUSEMOVE"}:
            dd.hover = dd.index_at(my)
            _tag_redraw(context)
            return {"RUNNING_MODAL"}

        if et == "LEFTMOUSE":
            idx = dd.index_at(my)
            if idx >= 0:
                # Pick on either the opening drag-release or a later click.
                return self._dd_pick(context, dd.filtered()[idx][0])
            if (ev == "PRESS" and not self._rect.contains(mx, my)
                    and not dd.in_list(my)):
                return self._close_dropdown(context)   # click-away cancels
            return {"RUNNING_MODAL"}                   # opening release etc.

        if ev == "PRESS":
            # Type-to-filter: printable chars append, backspace pops.
            if et == "BACK_SPACE":
                dd.backspace()
                _tag_redraw(context)
                return {"RUNNING_MODAL"}
            if event.unicode and not event.ctrl and not event.alt:
                dd.type_char(event.unicode)
                _tag_redraw(context)
                return {"RUNNING_MODAL"}

        return {"RUNNING_MODAL"}

    def _dd_pick(self, context, ident):
        self._control.write(context, ident)
        self._widget.mark_dirty()
        self._undo_push()
        return self._close_dropdown(context)

    def _close_dropdown(self, context):
        self._widget._dropdown = None
        self._dd = None
        _tag_redraw(context)
        return {"FINISHED"}
```

Note: the old `_dd_index_at` helper and the `self._dd_items` / `self._dd_field` attributes are gone entirely — `DropdownState` replaced them. Verify no other references remain:

Run: `python -c "import pathlib; s = pathlib.Path('ui/widgets/events.py').read_text(); print([w for w in ('_dd_items', '_dd_field', '_dd_index_at', 'dropdown_index_at') if w in s])"`
Expected: `[]`

- [ ] **Step 4: Run the pure suite (regression only — events has no pytest coverage)**

Run: `python -m pytest tests/ui/widgets/ -v`
Expected: ALL pass (nothing here imports events.py; this catches accidental controls.py breakage).

- [ ] **Step 5: Commit**

```powershell
git add ui/widgets/events.py && git commit -m "feat(widgets): dropdown modal scrolls, flips and filters via DropdownState"
```

---

### Task 4: Render — draw window, scroll hints, filter overlay

**Files:**
- Modify: `ui/widgets/render.py` — import (line ~23), constants (near line 52), `_draw_dropdown_list` (lines ~566–585), `draw_widget` tail (lines ~650–654).

**Interfaces:**
- Consumes: `DropdownState` API from Task 2; existing render helpers `_col`, `_outline`, `_text_left`, `_truncate_middle`, `_active_fill`, `primitives.rect_2d`, `Rect`, `Role`, `CELL_INSET`.
- Produces: final user-visible behavior; nothing downstream.

- [ ] **Step 1: Update import and add constants**

Line ~23: remove `dropdown_item_rects` from the `from .controls import (...)` list (render no longer computes geometry itself — `dd.rects()` does). Keep the other imported names as-is.

Near `DROPDOWN_ITEM_H` (line ~52) add:

```python
SCROLL_UP_GLYPH = "▲"       # clipped-items hint at the list's top edge
SCROLL_DOWN_GLYPH = "▼"     # clipped-items hint at the list's bottom edge
NO_MATCH_TEXT = "(no match)"
```

- [ ] **Step 2: Replace `_draw_dropdown_list`**

Replace the whole function (lines ~566–585) with:

```python
def _draw_dropdown_list(dd, theme):
    """Draw an open dropdown (a controls.DropdownState) on top of the
    panel: the visible window of filtered items, ▲/▼ hints when the list
    is clipped, and the typed filter over the field cell. Geometry comes
    from dd.rects(), the same source events hit-tests against, so draw
    and pick can never disagree."""
    window = dd.window()
    rects = dd.rects()
    bg = theme.hud.bg_color
    line_color = _col(theme, Role.BBOX, 1.0)
    label_color = _col(theme, Role.HUD_LABEL, 1.0)
    hint_color = _col(theme, Role.HUD_LABEL_INACTIVE, 1.0)
    fill = _active_fill(theme)

    if not window:
        # Filter matched nothing: one dimmed placeholder cell.
        x, y, w, h = rects[0]
        cell = Rect(x, y, w, h)
        primitives.rect_2d(x, y, w, h, color=bg, theme=theme)
        _outline(cell, line_color, theme)
        _text_left(NO_MATCH_TEXT, cell, x + CELL_INSET,
                   theme=theme, color=hint_color)
    else:
        for i, ((x, y, w, h), (_ident, disp)) in enumerate(
                zip(rects, window)):
            cell = Rect(x, y, w, h)
            primitives.rect_2d(x, y, w, h, color=bg, theme=theme)
            if dd.offset + i == dd.hover:
                primitives.rect_2d(x, y, w, h, color=fill, theme=theme)
            _outline(cell, line_color, theme)
            disp = _truncate_middle(disp, w - CELL_INSET * 3.0
                                    - hud_text.measure(SCROLL_UP_GLYPH,
                                                       theme=theme)[0],
                                    theme)
            _text_left(disp, cell, x + CELL_INSET,
                       theme=theme, color=label_color)
        # Clip hints: rects[0] is the visually topmost cell in BOTH
        # orientations (reading order is preserved when flipped), so
        # "more before the window" is always the top edge.
        if dd.clipped_above():
            x, y, w, h = rects[0]
            gw, _ = hud_text.measure(SCROLL_UP_GLYPH, theme=theme)
            _text_left(SCROLL_UP_GLYPH, Rect(x, y, w, h),
                       x + w - CELL_INSET - gw,
                       theme=theme, color=hint_color)
        if dd.clipped_below():
            x, y, w, h = rects[-1]
            gw, _ = hud_text.measure(SCROLL_DOWN_GLYPH, theme=theme)
            _text_left(SCROLL_DOWN_GLYPH, Rect(x, y, w, h),
                       x + w - CELL_INSET - gw,
                       theme=theme, color=hint_color)

    if dd.filter:
        # Typed filter replaces the field's value text while open (with a
        # trailing underscore as a caret hint), in the active-value color
        # so it reads as "editing".
        x, y, w, h = dd.field
        cell = Rect(x, y, w, h)
        active = _col(theme, Role.HUD_ACTIVE_VALUE, 1.0)
        primitives.rect_2d(x, y, w, h, color=bg, theme=theme)
        _outline(cell, active, theme)
        shown = _truncate_middle(dd.filter + "_", w - CELL_INSET * 2.0,
                                 theme)
        _text_left(shown, cell, x + CELL_INSET, theme=theme, color=active)
```

- [ ] **Step 3: Update the `draw_widget` tail**

Replace (lines ~650–654):

```python
            # Open dropdown list draws last so it sits on top of the panel.
            dd = getattr(widget, "_dropdown", None)
            if dd is not None:
                where, items, hover = dd
                _draw_dropdown_list(panel, where, items, hover, theme)
```

with:

```python
            # Open dropdown list draws last so it sits on top of the panel.
            dd = getattr(widget, "_dropdown", None)
            if dd is not None:
                _draw_dropdown_list(dd, theme)
```

- [ ] **Step 4: Sanity checks**

Run: `python -m pytest tests/ui/widgets/ -v`
Expected: ALL pass.

Run: `python -c "import pathlib; s = pathlib.Path('ui/widgets/render.py').read_text(); print('dropdown_item_rects' in s)"`
Expected: `False` (render no longer computes list geometry).

- [ ] **Step 5: Commit**

```powershell
git add ui/widgets/render.py && git commit -m "feat(widgets): render dropdown window with scroll hints and filter overlay"
```

---

### Task 5: Live verification in Blender

**Files:** none modified — verification only.

**Interfaces:**
- Consumes: everything above; the running Blender instance with the iops dev-reload infra.

- [ ] **Step 1: Read the reload procedure**

Read `C:\Users\cvitk\.claude\projects\D--git-InteractionOps\memory\reference_dev_reload_infra.md` and follow it to hot-reload the addon in the running Blender (blinker reload on port 9902; Blender MCP on 9999). If Blender is not running, ask the user to start it rather than launching it yourself.

- [ ] **Step 2: Exercise a long dropdown near the screen bottom**

Via the Blender MCP tools:
1. Create ~30 dummy images so an image dropdown has a long list: `mcp__blender__execute_blender_code` with `import bpy; [bpy.data.images.new(f"test_img_{i:02d}", 8, 8) for i in range(30)]`.
2. Open a widget with a dropdown (the UV image slots widget binds image enums — toggle it via `bpy.ops.iops.widget_toggle(name=...)`; list registered names via the widgets registry if unsure).
3. Take a screenshot (`mcp__blender__get_screenshot_of_area_as_image`) with the dropdown CLOSED, then ask the user to click the dropdown near the bottom of the viewport and screenshot again OPEN.

- [ ] **Step 3: Verify against the spec, with the user driving**

Confirm on screenshots / user report:
- List opens upward when the field is near the bottom (flip).
- Long list is clamped with ▼ hint; wheel scrolls; ▲ appears after scrolling.
- Typing narrows the list and shows the filter text in the field; Backspace edits it; ESC once clears the filter, ESC again closes.
- Clicking an item still writes the value + undo-pushes; `zz`-style no-match shows "(no match)" and clicks on it don't close or pick.

- [ ] **Step 4: Clean up test images**

`mcp__blender__execute_blender_code`: `import bpy; [bpy.data.images.remove(i) for i in list(bpy.data.images) if i.name.startswith("test_img_")]`

- [ ] **Step 5: Report results**

No commit — report pass/fail per spec item to the user. Any failure goes back to the owning task (geometry → Task 1/2, event handling → Task 3, drawing → Task 4).
