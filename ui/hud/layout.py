from __future__ import annotations
from typing import Tuple


def compute_origin(mode: str, *, region, mouse: Tuple[int, int],
                   content_size: Tuple[int, int], padding: int,
                   offset: Tuple[int, int],
                   free: Tuple[int, int]) -> Tuple[int, int]:
    """Return (x, y) bottom-left origin of the HUD block in region coords."""
    cw, ch = content_size
    rw, rh = region.width, region.height
    mx, my = mouse
    ox, oy = offset

    if mode == "top_left":
        return padding, rh - padding - ch
    if mode == "top_right":
        return rw - cw - padding, rh - padding - ch
    if mode == "bottom_left":
        return padding, padding
    if mode == "bottom_right":
        return rw - cw - padding, padding
    if mode == "free":
        return clamp_to_region(free[0], free[1], (cw, ch), region, padding)
    # cursor
    x = mx + ox
    y = my + oy - ch  # offset_y is negative by default → HUD above-right of cursor
    return clamp_to_region(x, y, (cw, ch), region, padding)


def clamp_to_region(x: int, y: int, content_size, region, padding: int):
    cw, ch = content_size
    x = max(padding, min(int(x), region.width - cw - padding))
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
