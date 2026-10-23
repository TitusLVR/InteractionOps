"""Pure-pytest tests for ui/widgets/editor_geom.py (no bpy required)."""
import pytest

from ui.widgets.panel import WidgetPanel
from ui.widgets import editor_geom as eg


def make_panel(rows, content_width=200.0, x=80.0, y=400.0, **kw):
    panel = WidgetPanel(title="T", x=x, y=y)
    panel.layout(rows, content_width, **kw)
    return panel


def two_rows():
    # row 0: plain (height 20); row 1: ROW with two cells
    panel = make_panel([(20.0, 1), (20.0, 2)])
    return panel, [False, True]


def test_edit_hit_resize_beats_cell():
    panel, kinds = two_rows()
    c = panel.row_rects[1][0]
    assert eg.edit_hit(panel, kinds, c.x2 + 1.0, c.cy) == ("resize", (1, 0))
    assert eg.edit_hit(panel, kinds, c.x2 - 1.0, c.cy) == ("resize", (1, 0))
    c1 = panel.row_rects[1][1]
    assert eg.edit_hit(panel, kinds, c1.cx, c1.cy) == ("cell", (1, 1))


def test_edit_hit_cell_in_plain_row():
    panel, kinds = two_rows()
    c = panel.row_rects[0][0]
    assert eg.edit_hit(panel, kinds, c.cx, c.cy) == ("cell", (0, None))
    # plain rows are resizable too, addressed as (r, None)
    assert eg.edit_hit(panel, kinds, c.x2 - 1.0, c.cy) == ("resize", (0, None))


def test_edit_hit_gutter_selects_row():
    panel, kinds = two_rows()
    c = panel.row_rects[1][0]
    assert eg.edit_hit(panel, kinds, panel.x + 2.0, c.cy) == ("row", (1, None))
    assert eg.edit_hit(panel, kinds, panel.x + panel.width * 2, c.cy) is None


def test_drop_target_top_band_new_row_before():
    panel, kinds = two_rows()
    c = panel.row_rects[1][0]
    tgt, ind = eg.drop_target(panel, kinds, c.cx, c.y2 - 1.0)
    assert tgt == (1, None)
    assert ind[0] == "hline"


def test_drop_target_bottom_band_new_row_after():
    panel, kinds = two_rows()
    c = panel.row_rects[1][0]
    tgt, ind = eg.drop_target(panel, kinds, c.cx, c.y + 1.0)
    assert tgt == (2, None)
    assert ind[0] == "hline" and ind[2] < c.y


def test_drop_target_middle_into_row_right_of_cell():
    panel, kinds = two_rows()
    c = panel.row_rects[1][0]
    tgt, ind = eg.drop_target(panel, kinds, c.cx + 5.0, c.cy)
    assert tgt == (1, 1)
    assert ind[0] == "vline" and ind[1] == pytest.approx(c.x2)
    tgt, ind = eg.drop_target(panel, kinds, c.cx - 5.0, c.cy)
    assert tgt == (1, 0)
    assert ind[1] == pytest.approx(c.x)


def test_drop_target_rows_only():
    panel, kinds = two_rows()
    c = panel.row_rects[1][0]
    tgt, ind = eg.drop_target(panel, kinds, c.cx, c.cy + 0.1, rows_only=True)
    assert tgt == (1, None) and ind[0] == "hline"
    tgt, ind = eg.drop_target(panel, kinds, c.cx, c.cy - 0.1, rows_only=True)
    assert tgt == (2, None) and ind[0] == "hline"


def test_drop_target_plain_row_middle_into_row():
    panel, kinds = two_rows()
    c = panel.row_rects[0][0]
    tgt, ind = eg.drop_target(panel, kinds, c.cx + 5.0, c.cy)
    assert tgt == (0, 1) and ind[0] == "vline"
    tgt, ind = eg.drop_target(panel, kinds, c.cx - 5.0, c.cy)
    assert tgt == (0, 0) and ind[0] == "vline"


def test_drop_target_empty_panel():
    panel = make_panel([])
    b = panel.bounds()
    tgt, ind = eg.drop_target(panel, [], b.cx, b.y + 3.0)
    assert tgt == (0, None) and ind[0] == "hline"


def test_drop_target_outside_none():
    panel, kinds = two_rows()
    assert eg.drop_target(panel, kinds, panel.x - 50, panel.y - 50) is None
    assert eg.drop_target(panel, kinds, panel.x + 5000, panel.y - 50) is None


def test_palette_items_order_and_hit():
    items = eg.palette_items()
    types = [t for t, _ in items]
    assert items[0] == ("", "Layout")
    assert types[1:4] == ["SECTION", "SPACER", "ROW"]
    assert items[4] == ("", "Controls")
    assert types[5:] == ["SLIDER", "PRESETS", "FLIPBOX", "BUTTON", "BUTTONS",
                         "DROPDOWN", "INPUT", "SWATCH"]
    panel = make_panel([(20.0, 1)] * len(items))
    rects = panel.row_rects
    c = rects[3][0]
    assert eg.palette_hit(rects, items, c.cx, c.cy) == "ROW"
    c = rects[0][0]
    assert eg.palette_hit(rects, items, c.cx, c.cy) is None
    assert eg.palette_hit(rects, items, -999, -999) is None


# ----------------------------------------------------------------------
# Resize span from mouse x / no-op move detection
# ----------------------------------------------------------------------
from ui.widgets.panel import grid_cells


@pytest.mark.parametrize("span", range(1, 13))
def test_span_from_mouse_lands_on_drawn_edges(span):
    cw, gap, left = 246.0, 6.0, 88.0
    dx, w = grid_cells([span], cw, gap)[0]
    edge = left + dx + w
    assert eg.span_from_mouse(edge, left, cw, gap, 0, 12) == span
    assert eg.grid_edge_x(left, cw, gap, span) == pytest.approx(edge)


def test_span_from_mouse_snaps_halves_thirds_quarters():
    cw, gap, left = 246.0, 6.0, 0.0
    for frac, want in ((0.5, 6), (1 / 3, 4), (2 / 3, 8), (0.25, 3),
                       (0.75, 9)):
        assert eg.span_from_mouse(left + cw * frac, left, cw, gap, 0,
                                  12) == want


def test_span_from_mouse_offset_start_and_clamps():
    cw, gap, left = 246.0, 6.0, 0.0
    # cell starting at column 4: mouse at the 8-column edge -> span 4
    edge8 = eg.grid_edge_x(left, cw, gap, 8)
    assert eg.span_from_mouse(edge8, left, cw, gap, 4, 12) == 4
    # left of its own start -> 1; far right -> max_span
    assert eg.span_from_mouse(left - 100.0, left, cw, gap, 4, 12) == 1
    assert eg.span_from_mouse(left + 999.0, left, cw, gap, 4, 6) == 6
    assert eg.span_from_mouse(left + 999.0, left, cw, gap, 0, 99) == 12


def test_is_noop_move():
    assert eg.is_noop_move((2, None), (2, None))
    assert eg.is_noop_move((2, None), (3, None))
    assert not eg.is_noop_move((2, None), (1, None))
    assert not eg.is_noop_move((2, None), (4, None))
    assert not eg.is_noop_move((2, None), (2, 0))     # into its own row
    assert eg.is_noop_move((1, 2), (1, 2))
    assert eg.is_noop_move((1, 2), (1, 3))
    assert not eg.is_noop_move((1, 2), (1, 1))
    assert not eg.is_noop_move((1, 2), (1, 4))
    assert not eg.is_noop_move((1, 2), (2, 2))
    assert not eg.is_noop_move((1, 2), (1, None))
    assert not eg.is_noop_move((1, 2), (2, None))


# ----------------------------------------------------------------------
# Panel right-edge (width) grip
# ----------------------------------------------------------------------
def test_panel_edge_hit_body_band():
    panel = make_panel([(20.0, 1), (20.0, 2)], padding=8.0)
    x2 = panel.x + panel.width
    body_y = panel.y - panel.title_h - 10.0
    half = eg.HANDLE_W * 0.5
    assert eg.panel_edge_hit(panel, x2, body_y)
    assert eg.panel_edge_hit(panel, x2 - half, body_y)
    assert eg.panel_edge_hit(panel, x2 + half, body_y)
    assert not eg.panel_edge_hit(panel, x2 - half - 1.0, body_y)
    assert not eg.panel_edge_hit(panel, x2 + half + 1.0, body_y)


def test_panel_edge_hit_spans_body_height_not_title():
    panel = make_panel([(20.0, 1), (20.0, 2)], padding=8.0)
    x2 = panel.x + panel.width
    bottom = panel.y - panel.height
    assert eg.panel_edge_hit(panel, x2, bottom)            # bottom padding
    assert eg.panel_edge_hit(panel, x2, panel.y - panel.title_h - 0.5)
    # title bar (close cell) is excluded
    assert not eg.panel_edge_hit(panel, x2, panel.y - 2.0)
    assert not eg.panel_edge_hit(panel, x2, bottom - 1.0)  # below the panel


def test_panel_edge_band_disjoint_from_cell_grips():
    # cells end `padding` px before the panel edge: a cell's resize band
    # (c.x2 +- HANDLE_W/2) never reaches the panel-edge band.
    panel = make_panel([(20.0, 1), (20.0, 2)], padding=8.0)
    kinds = [False, True]
    half = eg.HANDLE_W * 0.5
    for cells in panel.row_rects:
        c = cells[-1]
        assert not eg.panel_edge_hit(panel, c.x2 + half, c.cy)
        assert eg.edit_hit(panel, kinds, panel.x + panel.width - half,
                           c.cy) != ("resize", (0, None))
        assert c.x2 + half < panel.x + panel.width - half


def test_drag_moved_threshold():
    t = eg.MOVE_THRESHOLD
    assert not eg.drag_moved(100.0, 100.0)
    assert not eg.drag_moved(100.0, 100.0 + t - 0.5)
    assert not eg.drag_moved(100.0, 100.0 - t + 0.5)
    assert eg.drag_moved(100.0, 100.0 + t)
    assert eg.drag_moved(100.0, 100.0 - t - 1.0)


def test_panel_edge_hit_empty_layout_is_false():
    panel = WidgetPanel(title="T")
    assert not eg.panel_edge_hit(panel, panel.x, panel.y - 30.0)
