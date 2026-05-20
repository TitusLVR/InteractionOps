"""Safe wrappers around `SpaceView3D.draw_handler_add` / `_remove`.

Blender's draw-handler API holds a Python callback for the lifetime of the
viewport. When that callback is a bound method of a modal operator and the
operator's StructRNA is destroyed (addon reload, abnormal modal exit,
exception during `invoke`), every redraw raises:

    ReferenceError: StructRNA of type ... has been removed

`safe_handler_add` returns a handle just like `draw_handler_add` but wraps
the callback so the first ReferenceError silently removes the handler.
`safe_handler_remove` is an idempotent version of `draw_handler_remove`.

When called with `tick=True`, `safe_handler_add` also keeps a 60 fps
window-manager timer alive for as long as at least one such handler is
registered. Modal operators use this to make the HUD's cursor-follow and
nav-recovery glide tick smoothly even when the cursor is idle — the timer
is reference-counted per window, so it's cheap and self-cleaning.
"""
from __future__ import annotations

import bpy


# (window.as_pointer()) -> [timer, refcount]
_TICKERS: dict[int, list] = {}
# handle id -> window pointer (so safe_handler_remove can release the
# right ticker without the caller passing context)
_HANDLE_WINDOW: dict[int, int] = {}


def _resolve_window(win_id: int):
    for win in bpy.context.window_manager.windows:
        if win.as_pointer() == win_id:
            return win
    return None


def _claim_ticker(window) -> None:
    if window is None:
        return
    win_id = window.as_pointer()
    entry = _TICKERS.get(win_id)
    if entry is not None:
        entry[1] += 1
        return
    try:
        timer = bpy.context.window_manager.event_timer_add(
            1.0 / 60.0, window=window)
    except Exception:
        return
    _TICKERS[win_id] = [timer, 1]


def _release_ticker(win_id: int) -> None:
    entry = _TICKERS.get(win_id)
    if entry is None:
        return
    entry[1] -= 1
    if entry[1] > 0:
        return
    try:
        bpy.context.window_manager.event_timer_remove(entry[0])
    except Exception:
        pass
    _TICKERS.pop(win_id, None)


class _SafeProxy:
    __slots__ = ("_cb", "_space", "_region", "_handle", "_dead", "_win_id")

    def __init__(self, cb, space, region):
        self._cb = cb
        self._space = space
        self._region = region
        self._handle = None
        self._dead = False
        self._win_id = 0

    def __call__(self, *args):
        if self._dead:
            return
        try:
            self._cb(*args)
        except ReferenceError:
            self._dead = True
            safe_handler_remove(self._handle, self._space, self._region)


def safe_handler_add(space_type, callback, args, region, draw_type,
                     *, tick: bool = False):
    """Drop-in replacement for `space_type.draw_handler_add`.

    `space_type` is e.g. `bpy.types.SpaceView3D`. Returns the original
    Blender handle — pass it to `safe_handler_remove`.

    Pass `tick=True` from a modal operator's invoke to claim a 60 fps
    window timer that keeps `modal()` ticking even when the cursor is
    idle. The timer is shared/refcounted per window and is released
    automatically when the matching `safe_handler_remove` runs.
    """
    proxy = _SafeProxy(callback, space_type, region)
    proxy._handle = space_type.draw_handler_add(proxy, args, region, draw_type)
    if tick:
        window = bpy.context.window
        if window is not None:
            proxy._win_id = window.as_pointer()
            _claim_ticker(window)
            _HANDLE_WINDOW[id(proxy._handle)] = proxy._win_id
    return proxy._handle


def safe_handler_remove(handle, space_type, region):
    """Drop-in replacement for `draw_handler_remove`. Safe to call twice;
    safe to call on a handle that no longer exists. Releases the
    associated tick timer if this handle claimed one."""
    if handle is None:
        return
    try:
        space_type.draw_handler_remove(handle, region)
    except (ValueError, RuntimeError, ReferenceError):
        pass
    win_id = _HANDLE_WINDOW.pop(id(handle), None)
    if win_id is not None:
        _release_ticker(win_id)
