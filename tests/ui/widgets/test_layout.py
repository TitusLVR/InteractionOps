"""Pure-pytest tests for ui/widgets/panel.py (no bpy required).

Covers: Rect basics, row stacking, panel bounds, edge clamping to a
region, per-control (cell) rect generation, and hit-test resolution.
Coordinate space: region pixels, origin bottom-left, +y up; the panel is
anchored by its TOP-LEFT corner.
"""
import pytest

from ui.widgets.panel import Rect, WidgetPanel


# ----------------------------------------------------------------------
# Rect
# ----------------------------------------------------------------------
def test_rect_derived_coords():
    r = Rect(10.0, 20.0, 30.0, 40.0)
    assert r.x2 == pytest.approx(40.0)
    assert r.y2 == pytest.approx(60.0)
    assert r.cx == pytest.approx(25.0)
    assert r.cy == pytest.approx(40.0)


def test_rect_contains_inclusive_edges():
    r = Rect(0.0, 0.0, 10.0, 10.0)
    assert r.contains(0.0, 0.0)
    assert r.contains(10.0, 10.0)
    assert r.contains(5.0, 5.0)
    assert not r.contains(10.01, 5.0)
    assert not r.contains(5.0, -0.01)


# ----------------------------------------------------------------------
# Layout: row stacking + panel size
# ----------------------------------------------------------------------
def make_panel(rows, content_width=100.0, x=80.0, y=400.0, **kw):
    panel = WidgetPanel(title="T", x=x, y=y)
    panel.layout(rows, content_width, **kw)
    return panel


def test_layout_panel_size():
    panel = make_panel([(20.0, 1), (20.0, 1)], content_width=100.0,
                       padding=8.0, title_h=22.0, row_gap=4.0)
    assert panel.width == pytest.approx(100.0 + 2 * 8.0)
    # title + padding + 20 + gap + 20 + padding
    assert panel.height == pytest.approx(22.0 + 8.0 + 20.0 + 4.0 + 20.0 + 8.0)


def test_layout_title_and_close_rects():
    panel = make_panel([(20.0, 1)], content_width=100.0,
                       padding=8.0, title_h=22.0)
    t = panel.title_rect
    assert t.x == pytest.approx(80.0)
    assert t.y == pytest.approx(400.0 - 22.0)  # title hangs below top anchor
    assert t.w == pytest.approx(panel.width)
    assert t.h == pytest.approx(22.0)
    # Close glyph: square cell flush right inside the title bar.
    c = panel.close_rect
    assert c.w == pytest.approx(22.0)
    assert c.h == pytest.approx(22.0)
    assert c.x2 == pytest.approx(t.x2)
    assert c.y == pytest.approx(t.y)


def test_layout_rows_stack_downward():
    panel = make_panel([(20.0, 1), (30.0, 1)], content_width=100.0,
                       padding=8.0, title_h=22.0, row_gap=4.0)
    r0 = panel.row_rects[0][0]
    r1 = panel.row_rects[1][0]
    # First row sits padding below the title bar; rects store bottom-left.
    assert r0.y2 == pytest.approx(400.0 - 22.0 - 8.0)
    assert r0.h == pytest.approx(20.0)
    # Second row stacks one row_gap below the first.
    assert r1.y2 == pytest.approx(r0.y - 4.0)
    assert r1.h == pytest.approx(30.0)
    # Rows are inset by the horizontal padding and span the content width.
    assert r0.x == pytest.approx(80.0 + 8.0)
    assert r0.w == pytest.approx(100.0)


def test_layout_multi_column_cells():
    panel = make_panel([(20.0, 3)], content_width=102.0,
                       padding=8.0, col_gap=6.0)
    cells = panel.row_rects[0]
    assert len(cells) == 3
    cell_w = (102.0 - 6.0 * 2) / 3
    for i, cell in enumerate(cells):
        assert cell.w == pytest.approx(cell_w)
        assert cell.x == pytest.approx(80.0 + 8.0 + i * (cell_w + 6.0))
        assert cell.h == pytest.approx(20.0)
    # Cells exactly fill the content width.
    assert cells[-1].x2 == pytest.approx(80.0 + 8.0 + 102.0)


def test_layout_empty_rows():
    panel = make_panel([], content_width=100.0, padding=8.0, title_h=22.0)
    assert panel.row_rects == []
    assert panel.height == pytest.approx(22.0 + 8.0 + 8.0)


# ----------------------------------------------------------------------
# Bounds
# ----------------------------------------------------------------------
def test_bounds_match_anchor_and_size():
    panel = make_panel([(20.0, 1)], content_width=100.0)
    b = panel.bounds()
    assert b.x == pytest.approx(panel.x)
    assert b.y == pytest.approx(panel.y - panel.height)
    assert b.w == pytest.approx(panel.width)
    assert b.h == pytest.approx(panel.height)
    # contains() goes through bounds(): top-left anchor itself is inside.
    assert panel.contains(panel.x, panel.y)
    assert not panel.contains(panel.x - 1.0, panel.y)


# ----------------------------------------------------------------------
# Edge clamping to region
# ----------------------------------------------------------------------
def test_clamp_left_and_title_bottom():
    panel = make_panel([(20.0, 1)], content_width=100.0, x=-50.0, y=10.0)
    panel.clamp_to_region(1000.0, 800.0, margin=2.0)
    assert panel.x == pytest.approx(2.0)
    # Vertical clamp keeps the TITLE BAR reachable (top edge >=
    # title_h + margin), not the whole panel body, so the body may
    # overflow below.
    assert panel.y == pytest.approx(panel.title_h + 2.0)


def test_clamp_right_and_top():
    panel = make_panel([(20.0, 1)], content_width=100.0, x=5000.0, y=5000.0)
    panel.clamp_to_region(1000.0, 800.0, margin=2.0)
    assert panel.x == pytest.approx(1000.0 - panel.width - 2.0)
    assert panel.y == pytest.approx(800.0 - 2.0)  # top edge at region top


def test_clamp_noop_when_inside():
    panel = make_panel([(20.0, 1)], content_width=100.0, x=300.0, y=400.0)
    panel.clamp_to_region(1000.0, 800.0)
    assert panel.x == pytest.approx(300.0)
    assert panel.y == pytest.approx(400.0)


def test_clamp_tall_panel_keeps_dragged_position():
    # Regression (CCP Data OPS): a tall panel must keep the vertical
    # position it was dragged to — the body overflows below the region
    # instead of the panel snapping up to height+margin.
    panel = make_panel([(700.0, 1)], content_width=100.0, x=100.0, y=400.0)
    assert panel.height > 400.0
    panel.clamp_to_region(2000.0, 1000.0)
    assert panel.x == pytest.approx(100.0)
    assert panel.y == pytest.approx(400.0)   # not forced to panel.height


def test_clamp_oversized_panel_keeps_title_reachable():
    # Panel taller than the region: a valid title position is preserved;
    # out-of-range placements clamp so the title bar stays grabbable.
    panel = make_panel([(500.0, 1)], content_width=100.0, x=0.0, y=150.0)
    assert panel.height > 200.0
    panel.clamp_to_region(1000.0, 200.0)
    assert panel.y == pytest.approx(150.0)         # valid title pos kept
    panel.y = 5000.0
    panel.clamp_to_region(1000.0, 200.0)
    assert panel.y == pytest.approx(200.0)         # clamped to region top
    panel.y = -100.0
    panel.clamp_to_region(1000.0, 200.0)
    assert panel.y == pytest.approx(panel.title_h)  # title bar kept on-screen


def test_clamp_degenerate_region_is_noop():
    panel = make_panel([(20.0, 1)], content_width=100.0, x=-50.0, y=400.0)
    panel.clamp_to_region(0.0, 0.0)
    assert panel.x == pytest.approx(-50.0)
    assert panel.y == pytest.approx(400.0)


# ----------------------------------------------------------------------
# Hit-testing
# ----------------------------------------------------------------------
def test_hit_test_outside_returns_none():
    panel = make_panel([(20.0, 1)], content_width=100.0)
    assert panel.hit_test(panel.x - 5.0, panel.y) is None
    assert panel.hit_test(panel.x, panel.y + 5.0) is None


def test_hit_test_close_beats_title():
    panel = make_panel([(20.0, 1)], content_width=100.0)
    # Close glyph overlaps the title bar; it must resolve first.
    assert panel.hit_test(panel.close_rect.cx, panel.close_rect.cy) == \
        ("close", None)
    assert panel.hit_test(panel.title_rect.x + 2.0, panel.title_rect.cy) == \
        ("title", None)


def test_hit_test_resolves_control_cells():
    panel = make_panel([(20.0, 1), (20.0, 3)], content_width=102.0)
    r0 = panel.row_rects[0][0]
    assert panel.hit_test(r0.cx, r0.cy) == ("control", (0, 0))
    for col in range(3):
        cell = panel.row_rects[1][col]
        assert panel.hit_test(cell.cx, cell.cy) == ("control", (1, col))


def test_hit_test_padding_resolves_panel():
    panel = make_panel([(20.0, 1)], content_width=100.0, padding=8.0)
    # Point in the left padding strip: inside bounds, in no cell.
    r0 = panel.row_rects[0][0]
    assert panel.hit_test(panel.x + 2.0, r0.cy) == ("panel", None)
    # Point in the row gap between two rows.
    panel = make_panel([(20.0, 1), (20.0, 1)], content_width=100.0,
                       row_gap=4.0)
    gap_y = panel.row_rects[0][0].y - 2.0
    assert panel.hit_test(panel.row_rects[0][0].cx, gap_y) == ("panel", None)


# ----------------------------------------------------------------------
# Drag-by-titlebar
# ----------------------------------------------------------------------
def test_drag_moves_panel_by_mouse_delta():
    panel = make_panel([(20.0, 1)], content_width=100.0, x=80.0, y=400.0)
    panel.start_drag(100.0, 390.0)
    assert panel.dragging
    panel.update_drag(150.0, 350.0)
    assert panel.x == pytest.approx(130.0)
    assert panel.y == pytest.approx(360.0)
    panel.end_drag()
    assert not panel.dragging
    assert panel.x == pytest.approx(130.0)


def test_cancel_drag_restores_position():
    panel = make_panel([(20.0, 1)], content_width=100.0, x=80.0, y=400.0)
    panel.start_drag(100.0, 390.0)
    panel.update_drag(500.0, 100.0)
    panel.cancel_drag()
    assert not panel.dragging
    assert panel.x == pytest.approx(80.0)
    assert panel.y == pytest.approx(400.0)


def test_update_drag_without_start_is_noop():
    panel = make_panel([(20.0, 1)], content_width=100.0, x=80.0, y=400.0)
    panel.update_drag(500.0, 100.0)
    assert panel.x == pytest.approx(80.0)
    assert panel.y == pytest.approx(400.0)


# ----------------------------------------------------------------------
# Per-column width specs — (height, ncols, spec) row entries: fixed px
# cells (e.g. a button hugging its label) + None = flex (share the rest)
# ----------------------------------------------------------------------
def test_layout_col_spec_fixed_and_flex():
    # content 200, col_gap 6 -> avail 194; fixed 50 -> flex gets 144
    panel = make_panel([(20.0, 2, [None, 50.0])], content_width=200.0,
                       col_gap=6.0)
    cells = panel.row_rects[0]
    assert cells[0].w == pytest.approx(144.0)
    assert cells[1].w == pytest.approx(50.0)
    # cells stay adjacent with the gap between them
    assert cells[1].x == pytest.approx(cells[0].x + 144.0 + 6.0)


def test_layout_col_spec_two_flex_split_equally():
    panel = make_panel([(20.0, 2, [None, None])], content_width=200.0,
                       col_gap=6.0)
    cells = panel.row_rects[0]
    assert cells[0].w == pytest.approx(97.0)
    assert cells[1].w == pytest.approx(97.0)


def test_layout_col_spec_all_fixed_scales_to_fill():
    # all-fixed columns scale proportionally to fill the content width
    panel = make_panel([(20.0, 2, [50.0, 50.0])], content_width=206.0,
                       col_gap=6.0)
    cells = panel.row_rects[0]
    assert cells[0].w == pytest.approx(100.0)
    assert cells[1].w == pytest.approx(100.0)


def test_layout_two_tuple_rows_keep_equal_split():
    panel = make_panel([(20.0, 2)], content_width=200.0, col_gap=6.0)
    cells = panel.row_rects[0]
    assert cells[0].w == pytest.approx(97.0)
    assert cells[1].w == pytest.approx(97.0)


def test_layout_col_spec_wrong_length_falls_back_to_equal():
    panel = make_panel([(20.0, 2, [50.0])], content_width=200.0, col_gap=6.0)
    cells = panel.row_rects[0]
    assert cells[0].w == pytest.approx(97.0)
    assert cells[1].w == pytest.approx(97.0)
