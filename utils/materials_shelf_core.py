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
ICON = 20           # toolbar icon buttons: squares of this size
ICON_GAP = 3
EDGE_H = 6
NAME_H = 16
BADGE_H = 15
BADGE_W = 26
SCROLLBAR_W = 5
MARGIN = 4
TOOLTIP_GAP = 6

THUMB_MIN, THUMB_MAX, THUMB_STEP = 40, 256, 8
DRAG_THRESHOLD = 6

DIRECTIONS = ("ROW", "COLUMN")
POSITIONS = ("LEFT", "CENTER", "RIGHT")
# toolbar order; "empty" only while there are empty slots
TOOL_NAMES = ("functions", "new", "search", "src_SCENE", "src_SELECTED",
              "src_FILE", "empty")


def contains(r, x, y):
    return r.x <= x < r.x + r.w and r.y <= y < r.y + r.h


def overlaps(a, b):
    return (a.x < b.x + b.w and b.x < a.x + a.w
            and a.y < b.y + b.h and b.y < a.y + a.h)


def clamp_thumb(px):
    return max(THUMB_MIN, min(THUMB_MAX, int(px)))


def min_height(thumb, scale=1.0, direction="ROW"):
    """Smallest shelf height for the toolbar layout: one cell row, plus the
    toolbar row above it in Row mode; in Column mode a tall column wraps,
    so one icon or one cell row is the floor."""
    s = scale
    cell = (thumb + NAME_H + GAP) * s
    frame = (EDGE_H + 2 * PAD) * s
    if direction == "COLUMN":
        return int(frame + max(ICON * s, cell))
    return int(frame + ICON * s + GAP * s + cell)


def clamp_height(h, thumb, region_h, scale=1.0, top_reserve=40,
                 direction="ROW"):
    """Shelf height within [min_height, region height - top_reserve]."""
    lo = min_height(thumb, scale, direction)
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
    "Layout", "shelf edge tools toolbar grid cells cols rows_visible "
    "content_h max_scroll scroll cell_w cell_h scale direction position")


def toolbar(names, x0, x1, top, bottom, scale=1.0, direction="ROW",
            position="RIGHT"):
    """({name: Rect}, toolbar Rect) for square icon buttons inside the box
    x0..x1 / bottom..top. Row: one row along the top, aligned left, centre
    or right. Column: from the top down along the left or right edge
    (Center counts as Right), wrapping into more columns when the box is
    not tall enough."""
    icon, gap = ICON * scale, ICON_GAP * scale
    n = len(names)
    if not n:
        return {}, Rect(x1, top, 0, 0)
    rects = {}
    if direction == "COLUMN":
        per_col = max(1, int((top - bottom + gap) // (icon + gap)))
        cols = -(-n // per_col)
        w = cols * icon + (cols - 1) * gap
        sx = x0 if position == "LEFT" else x1 - w
        for i, name in enumerate(names):
            c, r = divmod(i, per_col)
            rects[name] = Rect(sx + c * (icon + gap),
                               top - icon - r * (icon + gap), icon, icon)
        rows = min(n, per_col)
        h = rows * icon + (rows - 1) * gap
        return rects, Rect(sx, top - h, w, h)
    w = n * icon + (n - 1) * gap
    if position == "LEFT":
        sx = x0
    elif position == "CENTER":
        sx = x0 + (x1 - x0 - w) / 2
    else:
        sx = x1 - w
    sx = max(x0, sx)
    for i, name in enumerate(names):
        rects[name] = Rect(sx + i * (icon + gap), top - icon, icon, icon)
    return rects, Rect(sx, top - icon, w, icon)


def compute_layout(region_w, region_h, insets, height, thumb, count,
                   scroll=0, scale=1.0, show_empty=False, direction="ROW",
                   position="RIGHT"):
    """Layout of the shelf in a region of `region_w` x `region_h` with
    `insets` = (left, right, top, bottom) hidden under overlapping regions.
    `count` cells, `scroll` in pixels from the top of the cell grid,
    toolbar per `direction` (ROW / COLUMN) and `position` (LEFT / CENTER /
    RIGHT)."""
    s = scale
    if direction not in DIRECTIONS:
        direction = "ROW"
    if position not in POSITIONS:
        position = "RIGHT"
    left, right, top, bottom = insets
    thumb = clamp_thumb(thumb)
    usable_h = region_h - top - bottom
    h = clamp_height(height, thumb, usable_h, s, direction=direction)
    x0 = left + MARGIN * s
    x1 = region_w - right - MARGIN * s
    y0 = bottom
    shelf = Rect(x0, y0, max(0, x1 - x0), h)
    edge = Rect(x0, y0 + h - EDGE_H * s, shelf.w, EDGE_H * s)

    pad = PAD * s
    ix0, ix1 = x0 + pad, x1 - pad
    itop, ibottom = y0 + h - EDGE_H * s - pad, y0 + pad
    names = [n for n in TOOL_NAMES if n != "empty" or show_empty]
    tools, bar = toolbar(names, ix0, ix1, itop, ibottom, s, direction,
                         position)

    # cell grid: under the toolbar row, or beside the toolbar column
    sb = SCROLLBAR_W * s
    if direction == "ROW":
        gx0, gx1 = ix0, ix1 - sb
        gy0, gy1 = ibottom, bar.y - GAP * s
    elif position == "LEFT":
        gx0, gx1 = bar.x + bar.w + GAP * s, ix1 - sb
        gy0, gy1 = ibottom, itop
    else:
        gx0, gx1 = ix0, bar.x - GAP * s - sb
        gy0, gy1 = ibottom, itop
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
    return Layout(shelf, edge, tools, bar, grid, cells, cols, rows_visible,
                  content_h, max_scroll, scroll, cell_w, cell_h, s,
                  direction, position)


def tooltip_rect(anchor, w, h, region_w, region_h, gap=TOOLTIP_GAP):
    """Rect of a w x h tooltip for the button `anchor`: centred above it,
    below it when there is no room above, always inside the region."""
    x = anchor.x + anchor.w / 2 - w / 2
    y = anchor.y + anchor.h + gap
    if y + h > region_h:
        y = anchor.y - gap - h
    x = max(0.0, min(x, region_w - w))
    y = max(0.0, min(y, region_h - h))
    return Rect(x, y, w, h)


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


def resize_height(start_h, start_y, y, thumb, region_h, scale=1.0,
                  direction="ROW"):
    """Shelf height while dragging its top edge from `start_y` to `y`."""
    return clamp_height(start_h + (y - start_y), thumb, region_h, scale,
                        direction=direction)


def short_count(n):
    """Badge text for a count: 7, 42, 999, 1.2k, 15k."""
    if n < 1000:
        return str(n)
    if n < 10000:
        return f"{n / 1000:.1f}k"
    return f"{n // 1000}k"


def tooltip_text(name, source="SCENE", search="", empty=0):
    """One-line tooltip of toolbar button `name`."""
    if name == "functions":
        return "Material Functions"
    if name == "new":
        return "New Material"
    if name == "search":
        return f"Search: {search}" if search else "Search"
    if name.startswith("src_"):
        return "Source: " + name[4:].title()
    if name == "empty":
        word = "slot" if empty == 1 else "slots"
        return f"{empty} empty {word}: click to remove"
    return ""
