"""Edit-mode geometry for the visual widget editor (pure, no bpy).

Answers "what is under the mouse" and "where would a drop land" from the
panel's existing layout rects. Called on every MOUSEMOVE during edit
gestures, so everything here is plain arithmetic with no heavy allocation.

Conventions (see editor_model): Path = (row, cell | None); Target =
(row, None) is a new top-level row at index `row` (0..len), (row, cell) is
an insertion into row `row` at cell index `cell` (0..ncells). In edit mode
every def row is one visual row, so visual row index == def row index.
"""

from .panel import GRID

HANDLE_W = 6.0        # resize grip width, centred on a cell's right edge
MOVE_THRESHOLD = 4.0  # px of mouse travel before a press becomes a drag
EDGE_BAND = 0.25      # top/bottom fraction of a row meaning new row before/after

_LAYOUT = (("SECTION", "Section"), ("SPACER", "Spacer"), ("ROW", "Row"))
_CONTROLS = (("SLIDER", "Slider"), ("PRESETS", "Presets"),
             ("FLIPBOX", "Flipbox"), ("BUTTON", "Button"),
             ("BUTTONS", "Buttons"), ("DROPDOWN", "Dropdown"),
             ("INPUT", "Input"), ("SWATCH", "Swatch"))


def edit_hit(panel, row_kinds, mx, my):
    """Resolve the mouse to ("resize"|"cell"|"row", Path) or None."""
    half = HANDLE_W * 0.5
    gutter_x2 = panel.x + panel.padding
    for r, cells in enumerate(panel.row_rects):
        if not cells:
            continue
        c0 = cells[0]
        if my < c0.y or my > c0.y2:
            continue
        if panel.x <= mx < gutter_x2:
            return ("row", (r, None))
        is_row = r < len(row_kinds) and row_kinds[r]
        for i, c in enumerate(cells):
            if abs(mx - c.x2) <= half:
                return ("resize", (r, i if is_row else None))
        for i, c in enumerate(cells):
            if c.contains(mx, my):
                return ("cell", (r, i if is_row else None))
        return None
    return None


def panel_edge_hit(panel, mx, my):
    """True when (mx, my) is on the panel's right edge (within HANDLE_W/2
    either side) anywhere along the BODY height — the title bar (close
    cell) is excluded. Cells end `panel.padding` px before the edge, so
    with padding > HANDLE_W this band never overlaps a cell resize grip."""
    if panel.width <= 0.0 or panel.height <= 0.0:
        return False
    if abs(mx - (panel.x + panel.width)) > HANDLE_W * 0.5:
        return False
    return panel.y - panel.height <= my < panel.y - panel.title_h


def drag_moved(x0, x):
    """True once a horizontal drag travelled MOVE_THRESHOLD px or more —
    below that a press+release is a click and must not commit."""
    return abs(float(x) - float(x0)) >= MOVE_THRESHOLD


def _hline(panel, y):
    return ("hline", panel.x + panel.padding, y,
            panel.width - 2.0 * panel.padding)


def _row_gap_y(panel, index):
    """y of the new-row indicator for insertion index `index`."""
    rows = panel.row_rects
    pad = panel.padding * 0.5
    if not rows:
        return panel.y - panel.title_h - pad
    if index <= 0:
        return rows[0][0].y2 + pad
    if index >= len(rows):
        return rows[-1][0].y - pad
    return (rows[index - 1][0].y + rows[index][0].y2) * 0.5


def drop_target(panel, row_kinds, mx, my, rows_only=False):
    """Return (Target, indicator) for a drop at (mx, my), or None."""
    if not panel.contains(mx, my) or panel.title_rect.contains(mx, my):
        return None
    rows = panel.row_rects
    if not rows:
        return ((0, None), _hline(panel, _row_gap_y(panel, 0)))
    # Pick the row owning this y: gaps split at their midpoints.
    r = len(rows) - 1
    for i in range(len(rows) - 1):
        if my >= (rows[i][0].y + rows[i + 1][0].y2) * 0.5:
            r = i
            break
    cells = rows[r]
    if not cells:
        return ((r, None), _hline(panel, _row_gap_y(panel, r)))
    c0 = cells[0]
    h = c0.h if c0.h > 0 else 1.0
    frac = (my - c0.y) / h
    if frac >= 1.0 - EDGE_BAND:
        return ((r, None), _hline(panel, _row_gap_y(panel, r)))
    if frac <= EDGE_BAND:
        return ((r + 1, None), _hline(panel, _row_gap_y(panel, r + 1)))
    if rows_only:
        # Rows-only drag: snap to the nearer edge.
        idx = r if frac >= 0.5 else r + 1
        return ((idx, None), _hline(panel, _row_gap_y(panel, idx)))
    nearest = min(range(len(cells)), key=lambda i: abs(mx - cells[i].cx))
    c = cells[nearest]
    if mx > c.cx:
        return ((r, nearest + 1), ("vline", c.x2, c.y, c.h))
    return ((r, nearest), ("vline", c.x, c.y, c.h))


def palette_items():
    """[(row_type, label)] in display order; "" row_type = section header."""
    return ([("", "Layout")] + list(_LAYOUT)
            + [("", "Controls")] + list(_CONTROLS))


def palette_hit(row_rects, items, mx, my):
    """Row type under the mouse in the palette panel (headers -> None)."""
    for (rtype, _label), rect in zip(items, row_rects):
        if isinstance(rect, (list, tuple)):
            if not rect:
                continue
            rect = rect[0]
        if rect.contains(mx, my):
            return rtype or None
    return None


def _grid_unit(content_w, col_gap):
    return (content_w - col_gap * (GRID - 1)) / GRID


def span_from_mouse(mx, row_left, content_w, col_gap, start_col, max_span):
    """Snapped span for a resize drag whose right edge follows `mx`, on the
    same 12-step grid `panel.grid_cells` lays out (cell right edge at
    column end e sits at row_left + e*(u+gap) - gap). Clamped to
    1..max_span (<= GRID)."""
    u = _grid_unit(content_w, col_gap)
    step = u + col_gap
    if step <= 0.0:
        return 1
    end = int(round((mx - row_left + col_gap) / step))
    return max(1, min(int(max_span), GRID, end - int(start_col)))


def grid_edge_x(row_left, content_w, col_gap, col):
    """x of the right edge of a cell ending at grid column `col`."""
    return row_left + col * (_grid_unit(content_w, col_gap) + col_gap) \
        - col_gap


def is_noop_move(src, target):
    """True when dropping `src` at `target` would leave it where it is:
    the target is its own slot or the slot right after it, in the same
    container (top-level rows, or the cells of the same ROW)."""
    if src is None or target is None:
        return False
    sr, sc = src
    tr, tc = target
    if sc is None:
        return tc is None and tr in (sr, sr + 1)
    return tc is not None and tr == sr and tc in (sc, sc + 1)
