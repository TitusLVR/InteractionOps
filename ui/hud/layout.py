from __future__ import annotations
from typing import Tuple, Optional


def region_side_insets(area) -> Tuple[int, int]:
    """Return (left, right) pixel widths of TOOLS / UI side regions in
    `area`, accounting for whether they are actually open (Blender uses
    width=1 as the collapsed sentinel)."""
    if area is None:
        return (0, 0)
    left = right = 0
    for r in area.regions:
        if r.width <= 1:
            continue
        if r.type == "TOOLS":
            left = max(left, r.width)
        elif r.type == "UI":
            right = max(right, r.width)
    return (left, right)


def area_for_region(region) -> Optional[object]:
    """Walk windows to find the area containing this region. Returns None
    if not found."""
    if region is None:
        return None
    import bpy
    target = region.as_pointer()
    for win in bpy.context.window_manager.windows:
        for area in win.screen.areas:
            for r in area.regions:
                if r.as_pointer() == target:
                    return area
    return None


def compute_origin(mode: str, *, region, mouse: Tuple[int, int],
                   content_size: Tuple[int, int], padding: int,
                   offset: Tuple[int, int],
                   free: Tuple[int, int],
                   anchor_offset: Tuple[int, int] = (0, 0),
                   side_insets: Tuple[int, int] = (0, 0)) -> Tuple[int, int]:
    """Return (x, y) bottom-left origin of the HUD block in region coords.

    `side_insets` is (left, right) pixel widths of the toolbar / N-panel
    side regions that overlay the WINDOW region; anchor and center modes
    respect them so the HUD stays inside the visible viewport.
    """
    cw, ch = content_size
    rw, rh = region.width, region.height
    mx, my = mouse
    ox, oy = offset
    ax, ay = anchor_offset
    li, ri = side_insets

    if mode == "free":
        return clamp_to_region(free[0], free[1], (cw, ch), region, padding,
                               side_insets=side_insets)
    if mode == "cursor":
        x = mx + ox
        y = my + oy - ch  # offset_y is negative by default → HUD above-right of cursor
        return clamp_to_region(x, y, (cw, ch), region, padding)

    # Anchor modes: positive ax → right, positive ay → up.
    avail_w = rw - li - ri
    left_x = li + padding
    right_x = rw - ri - cw - padding
    center_x = li + (avail_w - cw) // 2
    bottom_y = padding
    top_y = rh - padding - ch
    center_y = (rh - ch) // 2

    anchors = {
        "top_left":      (left_x,   top_y),
        "top_center":    (center_x, top_y),
        "top_right":     (right_x,  top_y),
        "left_center":   (left_x,   center_y),
        "center":        (center_x, center_y),
        "right_center":  (right_x,  center_y),
        "bottom_left":   (left_x,   bottom_y),
        "bottom_center": (center_x, bottom_y),
        "bottom_right":  (right_x,  bottom_y),
    }
    base = anchors.get(mode)
    if base is None:
        # Unknown mode → fall back to cursor.
        x = mx + ox
        y = my + oy - ch
        return clamp_to_region(x, y, (cw, ch), region, padding)
    return clamp_to_region(base[0] + ax, base[1] + ay,
                           (cw, ch), region, padding,
                           side_insets=side_insets)


def clamp_to_region(x: int, y: int, content_size, region, padding: int,
                    *, side_insets: Tuple[int, int] = (0, 0)):
    cw, ch = content_size
    li, ri = side_insets
    x = max(li + padding,
            min(int(x), region.width - ri - cw - padding))
    y = max(padding, min(int(y), region.height - ch - padding))
    return x, y


class DragState:
    """Tracks a free-mode drag in progress."""
    def __init__(self):
        self.active = False
        self.grab_dx = 0
        self.grab_dy = 0

    def begin(self, mouse_xy, hud_origin):
        self.active = True
        self.grab_dx = mouse_xy[0] - hud_origin[0]
        self.grab_dy = mouse_xy[1] - hud_origin[1]

    def update(self, mouse_xy):
        return (mouse_xy[0] - self.grab_dx,
                mouse_xy[1] - self.grab_dy)

    def end(self):
        self.active = False


def is_inside(x: int, y: int, origin, size) -> bool:
    return (origin[0] <= x <= origin[0] + size[0] and
            origin[1] <= y <= origin[1] + size[1])
