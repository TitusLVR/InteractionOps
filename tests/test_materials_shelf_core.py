from utils.materials_shelf_core import (
    DragTracker, Rect, clamp_height, clamp_scroll, clamp_thumb,
    compute_layout, contains, hit_test, min_height, resize_height,
    scroll_step, scroll_to_index, short_count,
)

NO_INSETS = (0, 0, 0, 0)


def layout(count=20, w=1000, h=600, height=200, thumb=64, scroll=0,
           insets=NO_INSETS, scale=1.0, show_empty=False):
    return compute_layout(w, h, insets, height, thumb, count, scroll, scale,
                          show_empty)


def test_shelf_sits_at_the_bottom_inside_insets():
    lay = layout(insets=(40, 300, 30, 24))
    assert lay.shelf.y == 24
    assert lay.shelf.x == 44            # left inset + margin
    assert lay.shelf.x + lay.shelf.w == 1000 - 300 - 4
    assert lay.shelf.h == 200
    assert lay.edge.y + lay.edge.h == lay.shelf.y + lay.shelf.h


def test_cells_wrap_and_rows_follow_height():
    lay = layout(height=200, thumb=64)
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
