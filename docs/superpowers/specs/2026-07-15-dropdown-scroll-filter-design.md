# Dropdown scroll + type-to-filter — design

Date: 2026-07-15
Status: approved

## Problem

Open widget dropdowns (`ui/widgets`) stack all items straight down from the
field's bottom edge (`dropdown_item_rects`, controls.py). No region clamp, no
scroll: a long enum/image list runs off the bottom of the screen, and since
the hit-test (`dropdown_index_at`) uses the same math, offscreen items are
also unpickable.

## Goals

- Every item of an arbitrarily long list is reachable.
- List never renders outside the region.
- Keyboard filtering while the list is open (typical lists 10–30 items, but
  image datablock lists can grow).
- Render and hit-test keep sharing one pure geometry source; pure parts stay
  pytest-covered without bpy.

## Non-goals

- Multi-column layouts.
- Caret/selection editing in the filter (plain append/backspace buffer).
- Re-layout while open (the modal owns input; the panel cannot move
  mid-open).

## Design

### 1. State

`widget._dropdown` (currently the tuple `(where, items, hover)`) becomes a
small dataclass `DropdownState`:

| field     | meaning                                              |
|-----------|------------------------------------------------------|
| `field`   | owning field rect (x, y, w, h), captured at open     |
| `items`   | full `[(identifier, display), ...]` list             |
| `filter`  | typed filter string (`""` = no filter)               |
| `offset`  | index of first visible item in the *filtered* list   |
| `hover`   | hovered index in the *filtered* list, -1 = none      |
| `flipped` | list opens upward from the field's top edge          |
| `visible` | number of item cells drawn                           |

The modal (`events.py`) owns and mutates the state; render reads it. The
filtered view is computed on demand by a pure helper: case-insensitive
substring match on the display name.

### 2. Geometry (pure, controls.py)

New pure function:

```
dropdown_layout(field_y, field_h, item_h, n, region_h)
    -> (flipped, visible, max_offset)
```

- Space below the field = `field_y` (cells stack down toward y=0); space
  above = `region_h - field_y - field_h`.
- If all `n` items fit below: open downward, `visible = n`, no scroll.
- Otherwise open toward the side with more room;
  `visible = min(n, floor(space / item_h))`, floored at 3.
- `max_offset = max(0, n - visible)`.

`dropdown_item_rects` gains a `flipped` parameter: when flipped, cells stack
UPWARD from the field's top edge (`field_y + field_h`), item 0 nearest the
field. `dropdown_index_at` takes the same parameters, so render and events
stay geometrically identical. Both stay pure and pytest-covered.

Region height is read once at open time from `context.region` in `invoke`.
Layout is recomputed when the filter changes (n_filtered shrinks), never
from panel movement.

### 3. Scroll

In `_modal_dropdown`, `WHEELUPMOUSE` / `WHEELDOWNMOUSE` step `offset` by ±1
and clamp to `[0, max_offset]` (recomputed against the filtered list).
Hover is recomputed from the current mouse position after each scroll.

Render draws the visible slice `filtered[offset : offset + visible]`. When
items are clipped above/below, a thin indicator strip ("▲" / "▼") is drawn
on the corresponding edge cell so the user knows there is more.

### 4. Type-to-filter

- Printable ASCII key events append to `filter`; `BACK_SPACE` pops the last
  character.
- While open, the collapsed field cell shows the filter buffer (with a
  trailing `_` as a caret hint) instead of the current value.
- Any filter change resets `offset = 0`, `hover = 0`, and re-runs
  `dropdown_layout` with the new filtered count.
- Empty filtered result: one dimmed "no match" cell; clicks on it are
  swallowed.
- `ESC`: if `filter` is non-empty, clear the filter (stay open); if empty,
  close the dropdown.
- `RET` / `NUMPAD_ENTER`: commit the hovered item (if any) via the normal
  pick path.

### 5. Pick path (unchanged semantics)

Click / drag-release on a cell maps the hit index through
`offset` + filtered list to an identifier, then as today:
`control.write(context, identifier)` → `mark_dirty` → undo push → close.

### 6. Tests

- Pure geometry (`dropdown_layout`; `dropdown_item_rects` /
  `dropdown_index_at` with `flipped` and offsets) and the filter helper →
  `tests/ui/widgets/test_controls.py`.
- Modal behavior (wheel clamping, two-stage ESC, enter-commit, filter reset
  of offset/hover) → alongside the existing event-layer tests.

## Files touched

- `ui/widgets/controls.py` — `dropdown_layout`, `flipped` support in rect /
  hit-test fns, filter helper.
- `ui/widgets/events.py` — `DropdownState`, wheel/typing/ESC/enter handling
  in `_modal_dropdown`, open-time layout in `invoke`.
- `ui/widgets/render.py` — visible-slice drawing, flip support, scroll
  indicators, filter text in the field cell.
- `tests/ui/widgets/test_controls.py` — new pure-function coverage.
