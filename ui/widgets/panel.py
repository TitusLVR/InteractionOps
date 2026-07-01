"""WidgetPanel — pure layout math for persistent GPU widget panels.

IMPORTANT: this module must stay importable WITHOUT bpy. It is unit-tested
with plain pytest (tests/ui/widgets/). Only plain floats/ints/strings live
here — no Blender types, no theme objects. The render module resolves all
sizes from the theme and passes them in as numbers.

Coordinate space: region pixels, origin bottom-left, +y up (matches
Blender's POST_PIXEL drawing and event.mouse_region_x/y). The panel is
anchored by its TOP-LEFT corner (panel.x, panel.y) so rows can stack
downward from the title bar.
"""
from __future__ import annotations


class Rect:
    """Axis-aligned rectangle in region pixels. (x, y) is bottom-left."""

    __slots__ = ("x", "y", "w", "h")

    def __init__(self, x: float = 0.0, y: float = 0.0,
                 w: float = 0.0, h: float = 0.0):
        self.x = float(x)
        self.y = float(y)
        self.w = float(w)
        self.h = float(h)

    @property
    def x2(self) -> float:
        return self.x + self.w

    @property
    def y2(self) -> float:
        return self.y + self.h

    @property
    def cx(self) -> float:
        return self.x + self.w * 0.5

    @property
    def cy(self) -> float:
        return self.y + self.h * 0.5

    def contains(self, mx: float, my: float) -> bool:
        return (self.x <= mx <= self.x + self.w
                and self.y <= my <= self.y + self.h)

    def __repr__(self) -> str:
        return f"Rect({self.x:.1f}, {self.y:.1f}, {self.w:.1f}, {self.h:.1f})"


class WidgetPanel:
    """Vertical row-stack panel: title bar + close glyph + N control rows.

    `layout()` consumes a list of (row_height_px, n_columns) tuples and a
    content width, and produces per-cell `Rect`s in `row_rects` — one list
    of Rects per row (Row controls split the content width equally among
    their children). Those rects are the single source of truth for both
    rendering and hit-testing, so the two can never disagree.
    """

    def __init__(self, title: str = "", x: float = 80.0, y: float = 400.0):
        self.title = title
        # Top-left anchor, region pixels.
        self.x = float(x)
        self.y = float(y)
        # Computed by layout().
        self.width = 0.0
        self.height = 0.0
        self.padding = 8.0
        self.title_h = 22.0
        self.title_rect = Rect()
        self.close_rect = Rect()
        self.row_rects: list[list[Rect]] = []
        # Drag-by-titlebar state.
        self.dragging = False
        self._drag_dx = 0.0
        self._drag_dy = 0.0
        self._drag_orig = (0.0, 0.0)

    # ------------------------------------------------------------------
    # Layout
    # ------------------------------------------------------------------
    def layout(self, rows, content_width: float, *,
               padding: float = 8.0, title_h: float = 22.0,
               row_gap: float = 4.0, col_gap: float = 6.0) -> "WidgetPanel":
        """Compute panel size and all per-cell rects from the top-left anchor.

        `rows` — sequence of (height_px, n_columns) or
        (height_px, n_columns, col_spec); one entry per visual row.
        n_columns > 1 splits the content width equally (Row controls)
        unless `col_spec` is given: a list of per-column widths where a
        float is a FIXED pixel width (a button hugging its label) and
        None is FLEX (shares the remaining width equally). All-fixed
        specs scale proportionally to fill; a spec whose length doesn't
        match n_columns falls back to the equal split.
        """
        rows = list(rows)
        self.padding = float(padding)
        self.title_h = float(title_h)
        self.width = float(content_width) + padding * 2.0
        inner_h = sum(entry[0] for entry in rows)
        if rows:
            inner_h += row_gap * (len(rows) - 1)
        self.height = title_h + padding + inner_h + padding

        top = self.y
        left = self.x
        self.title_rect = Rect(left, top - title_h, self.width, title_h)
        # Close glyph: square cell flush with the right end of the title bar.
        self.close_rect = Rect(left + self.width - title_h, top - title_h,
                               title_h, title_h)
        cy = top - title_h - padding
        self.row_rects = []
        for entry in rows:
            height, ncols = entry[0], entry[1]
            spec = entry[2] if len(entry) > 2 else None
            cy -= height
            n = max(1, int(ncols))
            avail = content_width - col_gap * (n - 1)
            if spec is not None and len(spec) == n:
                fixed = sum(w for w in spec if w is not None)
                nflex = sum(1 for w in spec if w is None)
                if nflex:
                    flex_w = max(0.0, avail - fixed) / nflex
                    widths = [w if w is not None else flex_w for w in spec]
                else:
                    # All fixed: scale proportionally to fill the row.
                    scale = avail / fixed if fixed > 0 else 0.0
                    widths = [w * scale for w in spec]
            else:
                widths = [avail / n] * n
            cells = []
            cx = left + padding
            for w in widths:
                cells.append(Rect(cx, cy, w, height))
                cx += w + col_gap
            self.row_rects.append(cells)
            cy -= row_gap
        return self

    def bounds(self) -> Rect:
        return Rect(self.x, self.y - self.height, self.width, self.height)

    def contains(self, mx: float, my: float) -> bool:
        return self.bounds().contains(mx, my)

    def clamp_to_region(self, region_w: float, region_h: float,
                        margin: float = 0.0) -> None:
        """Keep the panel reachable inside the region.

        Horizontally the whole panel is kept on-screen. Vertically only
        the TITLE BAR is kept reachable (top edge within
        [title_h + margin, region_h - margin]); a tall body is allowed to
        overflow below the region. Forcing the entire body on-screen
        would pin tall panels (e.g. CCP Data OPS) to a fixed band and
        fight the user's drag placement."""
        if self.width <= 0.0 or region_w <= 0.0 or region_h <= 0.0:
            return
        max_x = region_w - self.width - margin
        self.x = min(max(self.x, margin), max(margin, max_x))
        # y is the TOP edge; the title bar spans [y - title_h, y].
        top_max = region_h - margin           # title top <= region top
        top_min = min(self.title_h + margin, top_max)   # title stays on-screen
        self.y = min(max(self.y, top_min), top_max)

    # ------------------------------------------------------------------
    # Hit-testing
    # ------------------------------------------------------------------
    def hit_test(self, mx: float, my: float):
        """Resolve a point against the last computed layout.

        Returns one of:
            ("close",   None)        — close glyph
            ("title",   None)        — title bar (drag handle)
            ("control", (row, col))  — a control cell
            ("panel",   None)        — inside bounds, on padding/gaps
            None                     — outside the panel entirely
        """
        if not self.contains(mx, my):
            return None
        if self.close_rect.contains(mx, my):
            return ("close", None)
        if self.title_rect.contains(mx, my):
            return ("title", None)
        for r, cells in enumerate(self.row_rects):
            for c, rect in enumerate(cells):
                if rect.contains(mx, my):
                    return ("control", (r, c))
        return ("panel", None)

    # ------------------------------------------------------------------
    # Drag-by-titlebar
    # ------------------------------------------------------------------
    def start_drag(self, mx: float, my: float) -> None:
        self.dragging = True
        self._drag_dx = mx - self.x
        self._drag_dy = my - self.y
        self._drag_orig = (self.x, self.y)

    def update_drag(self, mx: float, my: float) -> None:
        if not self.dragging:
            return
        self.x = mx - self._drag_dx
        self.y = my - self._drag_dy

    def end_drag(self) -> None:
        self.dragging = False

    def cancel_drag(self) -> None:
        """Abort the drag and restore the pre-drag position."""
        if self.dragging:
            self.x, self.y = self._drag_orig
        self.dragging = False
