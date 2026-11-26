from utils import materials_shelf_glyphs as glyphs
from utils.materials_shelf_core import (
    ICON, TOOL_NAMES, DragTracker, Rect, clamp_height, clamp_scroll,
    clamp_thumb, compute_layout, contains, hit_test, min_height, overlaps,
    resize_height, scroll_step, scroll_to_index, short_count, tooltip_rect,
    tooltip_text,
)

NO_INSETS = (0, 0, 0, 0)


def layout(count=20, w=1000, h=600, height=200, thumb=64, scroll=0,
           insets=NO_INSETS, scale=1.0, show_empty=False, direction="ROW",
           position="RIGHT"):
    return compute_layout(w, h, insets, height, thumb, count, scroll, scale,
                          show_empty, direction, position)


def test_shelf_sits_at_the_bottom_inside_insets():
    lay = layout(insets=(40, 300, 30, 24))
    assert lay.shelf.y == 24
    assert lay.shelf.x == 44            # left inset + margin
    assert lay.shelf.x + lay.shelf.w == 1000 - 300 - 4
    assert lay.shelf.h == 200
    assert lay.edge.y + lay.edge.h == lay.shelf.y + lay.shelf.h


def test_cells_wrap_and_rows_follow_height():
    lay = layout(height=260, thumb=64)
    # cell 70 x 86; grid width 1000-8 margins - tools - pads
    assert lay.cols == int(lay.grid.w // 70)
    assert lay.rows_visible == int(lay.grid.h // 86)
    first, second = lay.cells[0], lay.cells[1]
    assert second.rect.x - first.rect.x == 70
    assert first.rect.y == second.rect.y
    row2 = lay.cells[lay.cols]
    assert first.rect.y - row2.rect.y == 86
    taller = layout(height=400, thumb=64)
    assert taller.rows_visible > lay.rows_visible


def test_wrap_on_resize():
    wide = layout(w=1400)
    narrow = layout(w=700)
    assert wide.cols > narrow.cols
    assert narrow.content_h > wide.content_h


def test_only_visible_cells_are_laid_out_and_scroll_clamps():
    lay = layout(count=200, height=200)
    assert len(lay.cells) == lay.cols * lay.rows_visible
    assert lay.max_scroll > 0 and lay.max_scroll % lay.cell_h == 0
    # every laid-out cell fits the grid completely
    g = lay.grid
    assert all(c.rect.y >= g.y and c.rect.y + c.rect.h <= g.y + g.h + 1e-6
               for c in lay.cells)
    # a scroll between rows snaps to a whole row
    mid = layout(count=200, height=200, scroll=lay.cell_h * 1.4)
    assert mid.scroll == lay.cell_h
    assert mid.cells[0].index == lay.cols
    far = layout(count=200, height=200, scroll=10 ** 6)
    assert far.scroll == far.max_scroll
    assert far.cells[-1].index == 199
    assert layout(count=200, scroll=-50).scroll == 0
    few = layout(count=3)
    assert few.max_scroll == 0 and len(few.cells) == 3


def test_hit_test_kinds():
    lay = layout(count=5, show_empty=True)
    c = lay.cells[0]
    assert hit_test(lay, 5, lay.shelf.y + lay.shelf.h + 10) == ("outside", None)
    assert hit_test(lay, c.rect.x + 1, lay.edge.y + 1) == ("resize", None)
    new = lay.tools["new"]
    assert hit_test(lay, new.x + 2, new.y + 2) == ("tool", "new")
    empty = lay.tools["empty"]
    assert hit_test(lay, empty.x + 2, empty.y + 2) == ("tool", "empty")
    mid = (c.thumb.x + c.thumb.w / 2, c.thumb.y + c.thumb.h / 2)
    assert hit_test(lay, *mid) == ("cell", 0)
    assert hit_test(lay, c.dup.x + 1, c.dup.y + 1) == ("cell", 0)
    assert hit_test(lay, c.dup.x + 1, c.dup.y + 1,
                    has_dup=lambda i: True) == ("dup", 0)
    assert hit_test(lay, c.users.x + 1, c.users.y + 1) == ("users", 0)
    # inside the grid but past the last cell
    g = lay.grid
    assert hit_test(lay, g.x + g.w - 2, g.y + 2) == ("shelf", None)


def test_empty_chip_only_when_asked():
    assert "empty" not in layout().tools
    assert "empty" in layout(show_empty=True).tools


def test_heights_and_thumbs_clamp():
    assert clamp_thumb(10) == 40 and clamp_thumb(999) == 256
    lo = min_height(64)
    assert clamp_height(10, 64, 600) == lo
    assert clamp_height(5000, 64, 600) == 560
    assert resize_height(200, 100, 150, 64, 600) == 250
    assert resize_height(200, 100, -900, 64, 600) == lo
    # a shelf taller than the region shrinks to fit
    assert layout(height=5000, h=300).shelf.h == 260


def test_scale_grows_everything():
    a = layout(scale=1.0)
    b = layout(scale=2.0)
    assert b.cell_w == 2 * a.cell_w and b.tools["new"].h == 2 * a.tools["new"].h


def test_scroll_helpers():
    lay = layout(count=200, height=200)
    assert scroll_step(lay, 1) == lay.cell_h
    assert scroll_step(lay, -1) == 0
    assert clamp_scroll(50, 100, 80) == 20
    assert clamp_scroll(50, 60, 80) == 0
    # rows of 10: 10 rows, 3 fit -> at most 7 rows down
    assert clamp_scroll(1000, 100, 35, 10) == 70
    assert clamp_scroll(26, 100, 35, 10) == 30
    s = scroll_to_index(lay, 199)
    assert s == lay.max_scroll
    assert scroll_to_index(lay, 0) == 0


def test_drag_tracker():
    d = DragTracker(100, 100)
    assert not d.update(103, 104)
    assert d.update(110, 100)
    assert d.update(100, 100)          # stays a drag once started


def test_contains_and_short_count():
    r = Rect(0, 0, 10, 10)
    assert contains(r, 0, 0) and not contains(r, 10, 5)
    assert short_count(7) == "7" and short_count(1234) == "1.2k"
    assert short_count(15000) == "15k"


# ----------------------------------------------------------------------
# icon toolbar: direction x position
# ----------------------------------------------------------------------
COMBOS = [(d, p) for d in ("ROW", "COLUMN") for p in ("LEFT", "CENTER", "RIGHT")]


def _all_inside(lay):
    s = lay.shelf
    return all(r.x >= s.x and r.x + r.w <= s.x + s.w + 1e-6 and r.y >= s.y
               and r.y + r.h <= s.y + s.h + 1e-6 for r in lay.tools.values())


def test_every_layout_keeps_tools_inside_and_apart_from_cells():
    for direction, position in COMBOS:
        for show_empty in (False, True):
            lay = layout(count=40, height=260, direction=direction,
                         position=position, show_empty=show_empty)
            n = 7 if show_empty else 6
            assert len(lay.tools) == n, (direction, position)
            assert all(r.w == ICON and r.h == ICON for r in lay.tools.values())
            assert _all_inside(lay), (direction, position)
            # toolbar and grid never overlap; no cell touches a tool
            assert not overlaps(lay.toolbar, lay.grid), (direction, position)
            for cell in lay.cells:
                for r in lay.tools.values():
                    assert not overlaps(cell.rect, r), (direction, position)
            # buttons do not overlap each other
            rs = list(lay.tools.values())
            assert not any(overlaps(a, b) for i, a in enumerate(rs)
                           for b in rs[i + 1:])


def test_row_toolbar_sits_at_the_top_and_aligns():
    right = layout(direction="ROW", position="RIGHT")
    left = layout(direction="ROW", position="LEFT")
    center = layout(direction="ROW", position="CENTER")
    for lay in (right, left, center):
        bar = lay.toolbar
        assert bar.h == ICON
        # top of the shelf, under the resize edge
        assert bar.y + bar.h <= lay.edge.y
        assert bar.y + bar.h > lay.edge.y - 3 * ICON
        # the cells use the full width under it
        assert lay.grid.y + lay.grid.h <= bar.y
        assert lay.grid.x == lay.shelf.x + 6
    s = right.shelf
    assert abs((right.toolbar.x + right.toolbar.w) - (s.x + s.w - 6)) < 1e-6
    assert abs(left.toolbar.x - (s.x + 6)) < 1e-6
    mid = center.toolbar.x + center.toolbar.w / 2
    assert abs(mid - (s.x + s.w / 2)) < 1e-6
    # the default order runs left to right
    xs = [right.tools[n].x for n in TOOL_NAMES if n in right.tools]
    assert xs == sorted(xs)


def test_column_toolbar_runs_down_an_edge_center_is_right():
    left = layout(direction="COLUMN", position="LEFT", height=260)
    right = layout(direction="COLUMN", position="RIGHT", height=260)
    center = layout(direction="COLUMN", position="CENTER", height=260)
    assert center.toolbar == right.toolbar
    assert left.toolbar.w == ICON and right.toolbar.w == ICON
    assert left.grid.x >= left.toolbar.x + left.toolbar.w
    assert right.grid.x + right.grid.w <= right.toolbar.x
    ys = [left.tools[n].y for n in TOOL_NAMES if n in left.tools]
    assert ys == sorted(ys, reverse=True)
    # the grid uses the full height in Column mode
    assert left.grid.h > layout(direction="ROW", height=260).grid.h


def test_column_wraps_when_the_shelf_is_short():
    lay = layout(direction="COLUMN", position="LEFT", height=10,
                 show_empty=True)
    xs = sorted({r.x for r in lay.tools.values()})
    assert len(xs) >= 2, "a short shelf must wrap the column"
    assert lay.toolbar.w == len(xs) * ICON + (len(xs) - 1) * 3
    assert _all_inside(lay)
    assert lay.grid.x >= lay.toolbar.x + lay.toolbar.w


def test_min_height_follows_the_layout():
    row = min_height(64, 1.0, "ROW")
    col = min_height(64, 1.0, "COLUMN")
    assert row == col + ICON + 6
    assert layout(height=10, direction="ROW").shelf.h == row
    assert layout(height=10, direction="COLUMN").shelf.h == col
    # one full cell row always fits
    lay = layout(height=10, direction="ROW", count=5)
    assert lay.rows_visible == 1 and len(lay.cells) == 5
    assert resize_height(100, 0, -500, 64, 600, 1.0, "COLUMN") == col


def test_unknown_layout_values_fall_back():
    lay = layout(direction="DIAGONAL", position="UP")
    assert lay.direction == "ROW" and lay.position == "RIGHT"


def test_tooltip_rect_stays_inside_the_region():
    anchor = Rect(980, 150, 20, 20)
    r = tooltip_rect(anchor, 160, 20, 1000, 600)
    assert r.x + r.w <= 1000 and r.y == 176
    top = tooltip_rect(Rect(10, 590, 20, 20), 160, 20, 1000, 600)
    assert top.y + top.h <= 600 and top.y < 590 and top.x == 0


def test_tooltip_text():
    assert tooltip_text("functions") == "Material Functions"
    assert tooltip_text("new") == "New Material"
    assert tooltip_text("search") == "Search"
    assert tooltip_text("search", search="steel") == "Search: steel"
    assert tooltip_text("src_SELECTED") == "Source: Selected"
    assert tooltip_text("empty", empty=1) == "1 empty slot: click to remove"
    assert tooltip_text("empty", empty=3) == "3 empty slots: click to remove"


# ----------------------------------------------------------------------
# glyph data
# ----------------------------------------------------------------------
def test_every_tool_has_a_glyph_inside_the_unit_box():
    assert set(TOOL_NAMES) == set(glyphs.GLYPHS) == set(glyphs.TOOLS)
    for name in TOOL_NAMES:
        lines, curves, dots = glyphs.strokes(name)
        assert lines or curves, name
        for poly in lines + curves:
            assert len(poly) >= 2
            for x, y in poly:
                assert -1e-9 <= x <= 1 + 1e-9 and -1e-9 <= y <= 1 + 1e-9, name
        for cx, cy, r in dots:
            assert 0 <= cx - r and cx + r <= 1 and 0 <= cy - r and cy + r <= 1


def test_loops_close_and_fit_snaps_to_pixel_centres():
    lines, curves, _ = glyphs.strokes("src_FILE")
    assert lines[-1][0] == lines[-1][-1] or lines[0][0] == lines[0][-1]
    assert curves == []
    pts = glyphs.fit([(0.0, 0.0), (1.0, 1.0), (0.5, 0.5)], 10, 20, 20)
    assert pts == [(10.5, 20.5), (30.5, 40.5), (20.5, 30.5)]
    raw = glyphs.fit([(0.5, 0.5)], 10, 20, 20, snap=False)
    assert raw == [(20.0, 30.0)]


def test_glyphs_differ():
    shapes = {name: repr(glyphs.GLYPHS[name]) for name in glyphs.TOOLS}
    assert len(set(shapes.values())) == len(shapes)
