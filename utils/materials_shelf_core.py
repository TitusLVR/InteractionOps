"""Pure layout / hit-testing / scroll / drag logic of the iOps material
shelf (the strip the addon draws along the bottom of the 3D Viewport).
No bpy: pytest-covered. Pixels in region space, y up (Blender's region
coordinates). The bpy side lives in ui/materials_shelf/.
"""
from collections import namedtuple

Rect = namedtuple("Rect", "x y w h")

# base sizes in pixels at 1.0 resolution scale
PAD = 6
GAP = 6
ROW_H = 20
TOOL_W = 170
EDGE_H = 6
NAME_H = 16
BADGE_H = 15
BADGE_W = 26
SCROLLBAR_W = 5
MARGIN = 4

THUMB_MIN, THUMB_MAX, THUMB_STEP = 40, 256, 8
TOOL_ROWS = 3
DRAG_THRESHOLD = 6


def contains(r, x, y):
    return r.x <= x < r.x + r.w and r.y <= y < r.y + r.h


def clamp_thumb(px):
    return max(THUMB_MIN, min(THUMB_MAX, int(px)))


def min_height(thumb, scale=1.0):
    """Smallest shelf height: the tool cluster or one cell row."""
    tools = TOOL_ROWS * ROW_H * scale + 2 * PAD * scale + EDGE_H * scale
    cell = thumb * scale + NAME_H * scale + GAP * scale + 2 * PAD * scale \
        + EDGE_H * scale
    return int(max(tools, cell))


def clamp_height(h, thumb, region_h, scale=1.0, top_reserve=40):
    """Shelf height within [min_height, region height - top_reserve]."""
    lo = min_height(thumb, scale)
    hi = max(lo, int(region_h - top_reserve * scale))
    return max(lo, min(hi, int(h)))


def clamp_scroll(scroll, content_h, view_h, row_h=None):
    """Scroll in [0, content - view]; with `row_h`, in whole rows so the
    top row always starts at the top of the grid."""
    if row_h:
        rows_total = int(round(content_h / row_h))
        rows_view = max(1, int(view_h // row_h))
        max_rows = max(0, rows_total - rows_view)
        return int(max(0, min(round(scroll / row_h), max_rows)) * row_h)
    return max(0, min(int(scroll), max(0, int(content_h - view_h))))


Cell = namedtuple("Cell", "index rect thumb name dup users")
Layout = namedtuple(
    "Layout", "shelf edge tools grid cells cols rows_visible content_h "
    "max_scroll scroll cell_w cell_h scale")

TOOL_NAMES = ("new", "functions", "src_SCENE", "src_SELECTED", "src_FILE",
              "search", "empty")


def compute_layout(region_w, region_h, insets, height, thumb, count,
                   scroll=0, scale=1.0, show_empty=False):
    """Layout of the shelf in a region of `region_w` x `region_h` with
    `insets` = (left, right, top, bottom) hidden under overlapping regions.
    `count` cells, `scroll` in pixels from the top of the cell grid."""
    s = scale
    left, right, top, bottom = insets
    thumb = clamp_thumb(thumb)
    usable_h = region_h - top - bottom
    h = clamp_height(height, thumb, usable_h, s)
    x0 = left + MARGIN * s
    x1 = region_w - right - MARGIN * s
    y0 = bottom
    shelf = Rect(x0, y0, max(0, x1 - x0), h)
    edge = Rect(x0, y0 + h - EDGE_H * s, shelf.w, EDGE_H * s)

    # tool cluster, rows from the top
    pad, row_h, tool_w = PAD * s, ROW_H * s, TOOL_W * s
    tx = x0 + pad
    top_y = y0 + h - EDGE_H * s - pad

    def row_rect(i):
        return Rect(tx, top_y - row_h * (i + 1), tool_w, row_h - 2 * s)

    def split(r, n, k, span=1):
        w = r.w / n
        return Rect(r.x + w * k, r.y, w * span - 2 * s, r.h)

    tools = {}
    # row 0: menu and new as square icon buttons, search takes the rest;
    # row 1: the source as one segmented control; row 2: empty-slot notice
    r0, r1, r2 = (row_rect(i) for i in range(TOOL_ROWS))
    sq = r0.h
    tools["functions"] = Rect(r0.x, r0.y, sq, r0.h)
    tools["new"] = Rect(r0.x + sq + 2 * s, r0.y, sq, r0.h)
    sx = r0.x + 2 * (sq + 2 * s)
    tools["search"] = Rect(sx, r0.y, r0.x + r0.w - 2 * s - sx, r0.h)
    for k, src in enumerate(("SCENE", "SELECTED", "FILE")):
        tools["src_" + src] = split(r1, 3, k)
    if show_empty:
        tools["empty"] = Rect(r2.x, r2.y, r2.w - 2 * s, r2.h)
    tools = {k: r for k, r in tools.items() if r.y >= y0 + pad * 0.5}

    # cell grid
    gx0 = tx + tool_w + GAP * s
    gx1 = x1 - pad - SCROLLBAR_W * s
    gy0 = y0 + pad
    gy1 = y0 + h - EDGE_H * s - pad
    grid = Rect(gx0, gy0, max(0, gx1 - gx0), max(0, gy1 - gy0))
    cell_w = thumb * s + GAP * s
    cell_h = thumb * s + NAME_H * s + GAP * s
    cols = max(1, int(grid.w // cell_w)) if grid.w > 0 else 1
    rows_visible = max(1, int(grid.h // cell_h)) if grid.h > 0 else 1
    total_rows = -(-count // cols) if count else 0
    content_h = total_rows * cell_h
    # whole rows: only rows that fit completely are laid out
    scroll = clamp_scroll(scroll, content_h, grid.h, cell_h)
    max_scroll = max(0, total_rows - rows_visible) * cell_h
    first_row = int(round(scroll / cell_h)) if cell_h else 0

    cells = []
    start = first_row * cols
    stop = min(count, (first_row + rows_visible) * cols)
    for i in range(start, stop):
        r, c = divmod(i, cols)
        cx = gx0 + c * cell_w
        ctop = gy1 - (r - first_row) * cell_h
        rect = Rect(cx, ctop - cell_h, cell_w, cell_h)
        g = GAP * s / 2
        thumb_r = Rect(cx + g, ctop - g - thumb * s, thumb * s, thumb * s)
        name_r = Rect(cx + g, thumb_r.y - NAME_H * s, thumb * s, NAME_H * s)
        bw, bh = BADGE_W * s, BADGE_H * s
        dup_r = Rect(thumb_r.x, thumb_r.y + thumb_r.h - bh, bw, bh)
        users_r = Rect(thumb_r.x + thumb_r.w - bw, thumb_r.y + thumb_r.h - bh,
                       bw, bh)
        cells.append(Cell(i, rect, thumb_r, name_r, dup_r, users_r))
    return Layout(shelf, edge, tools, grid, cells, cols, rows_visible,
                  content_h, max_scroll, scroll, cell_w, cell_h, s)


def hit_test(layout, x, y, has_dup=lambda i: False):
    """("outside", None) | ("resize", None) | ("tool", name) |
    ("dup", index) | ("users", index) | ("cell", index) | ("shelf", None).
    `has_dup(index)` tells whether a cell shows a duplicate badge."""
    if not contains(layout.shelf, x, y):
        return ("outside", None)
    if contains(layout.edge, x, y):
        return ("resize", None)
    for name, r in layout.tools.items():
        if contains(r, x, y):
            return ("tool", name)
    if contains(layout.grid, x, y):
        for cell in layout.cells:
            if not contains(cell.rect, x, y):
                continue
            if has_dup(cell.index) and contains(cell.dup, x, y):
                return ("dup", cell.index)
            if contains(cell.users, x, y):
                return ("users", cell.index)
            return ("cell", cell.index)
    return ("shelf", None)


def scroll_step(layout, direction):
    """New scroll after one wheel step (+1 down / -1 up): one cell row."""
    return clamp_scroll(layout.scroll + direction * layout.cell_h,
                        layout.content_h, layout.grid.h, layout.cell_h)


def scroll_to_index(layout, index):
    """Scroll that shows cell `index` (unchanged when it is visible)."""
    row = index // max(1, layout.cols)
    first = int(round(layout.scroll / layout.cell_h))
    if row < first:
        first = row
    elif row >= first + layout.rows_visible:
        first = row - layout.rows_visible + 1
    return clamp_scroll(first * layout.cell_h, layout.content_h,
                        layout.grid.h, layout.cell_h)


class DragTracker:
    """Press -> click or drag: becomes a drag once the cursor moved more
    than `threshold` px from the press point."""

    def __init__(self, x, y, threshold=DRAG_THRESHOLD):
        self.x0, self.y0 = x, y
        self.threshold = threshold
        self.dragging = False

    def update(self, x, y):
        if not self.dragging:
            dx, dy = x - self.x0, y - self.y0
            self.dragging = dx * dx + dy * dy > self.threshold ** 2
        return self.dragging


def resize_height(start_h, start_y, y, thumb, region_h, scale=1.0):
    """Shelf height while dragging its top edge from `start_y` to `y`."""
    return clamp_height(start_h + (y - start_y), thumb, region_h, scale)


def short_count(n):
    """Badge text for a count: 7, 42, 999, 1.2k, 15k."""
    if n < 1000:
        return str(n)
    if n < 10000:
        return f"{n / 1000:.1f}k"
    return f"{n // 1000}k"
