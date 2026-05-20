"""Snapshot of `bpy.types.Event` for safe use in draw handlers.

Blender invalidates the live event object once `modal()` returns, so
reading `event.mouse_x` from a POST_PIXEL handler that fires later
returns garbage (we've seen 1e6+). Modal operators copy the few fields
the HUD reads into one of these each tick and pass the snapshot to
`hud.draw()` / `help.draw()` instead of the live event.
"""

__all__ = ["EventSnapshot", "capture_event"]


class EventSnapshot:
    __slots__ = ("mouse_x", "mouse_y", "mouse_region_x", "mouse_region_y",
                 "shift", "ctrl", "alt", "oskey", "type", "value")

    def __init__(self):
        self.mouse_x = 0
        self.mouse_y = 0
        self.mouse_region_x = 0
        self.mouse_region_y = 0
        self.shift = False
        self.ctrl = False
        self.alt = False
        self.oskey = False
        self.type = ""
        self.value = ""

    def update(self, event, *, modal_window=None, target_window=None,
               region=None):
        """Copy event fields. When the modal runs in a different window
        than the target viewport (e.g. invoked from a popup), translate
        coords through screen space into the target window/region."""
        if (modal_window is not None and target_window is not None
                and region is not None):
            screen_x = modal_window.x + event.mouse_x
            screen_y = modal_window.y + event.mouse_y
            tx = screen_x - target_window.x
            ty = screen_y - target_window.y
            self.mouse_x = tx
            self.mouse_y = ty
            self.mouse_region_x = tx - region.x
            self.mouse_region_y = ty - region.y
        else:
            self.mouse_x = event.mouse_x
            self.mouse_y = event.mouse_y
            self.mouse_region_x = event.mouse_region_x
            self.mouse_region_y = event.mouse_region_y
        self.shift = bool(event.shift)
        self.ctrl = bool(event.ctrl)
        self.alt = bool(event.alt)
        self.oskey = bool(event.oskey)
        self.type = event.type
        self.value = event.value


def capture_event(event, prev=None, **kwargs):
    """Return an EventSnapshot updated from `event`. Reuses `prev` if
    given (so modal operators can keep one snapshot instance per session
    instead of allocating each tick)."""
    snap = prev if isinstance(prev, EventSnapshot) else EventSnapshot()
    snap.update(event, **kwargs)
    return snap
