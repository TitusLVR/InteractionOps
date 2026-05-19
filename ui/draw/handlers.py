"""Safe wrappers around `SpaceView3D.draw_handler_add` / `_remove`.

Blender's draw-handler API holds a Python callback for the lifetime of the
viewport. When that callback is a bound method of a modal operator and the
operator's StructRNA is destroyed (addon reload, abnormal modal exit,
exception during `invoke`), every redraw raises:

    ReferenceError: StructRNA of type ... has been removed

`safe_handler_add` returns a handle just like `draw_handler_add` but wraps
the callback so the first ReferenceError silently removes the handler.
`safe_handler_remove` is an idempotent version of `draw_handler_remove`.
"""
from __future__ import annotations


class _SafeProxy:
    __slots__ = ("_cb", "_space", "_region", "_handle", "_dead")

    def __init__(self, cb, space, region):
        self._cb = cb
        self._space = space
        self._region = region
        self._handle = None
        self._dead = False

    def __call__(self, *args):
        if self._dead:
            return
        try:
            self._cb(*args)
        except ReferenceError:
            self._dead = True
            safe_handler_remove(self._handle, self._space, self._region)


def safe_handler_add(space_type, callback, args, region, draw_type):
    """Drop-in replacement for `space_type.draw_handler_add`.

    `space_type` is e.g. `bpy.types.SpaceView3D`. Returns the original
    Blender handle — pass it to `safe_handler_remove`.
    """
    proxy = _SafeProxy(callback, space_type, region)
    proxy._handle = space_type.draw_handler_add(proxy, args, region, draw_type)
    return proxy._handle


def safe_handler_remove(handle, space_type, region):
    """Drop-in replacement for `draw_handler_remove`. Safe to call twice;
    safe to call on a handle that no longer exists."""
    if handle is None:
        return
    try:
        space_type.draw_handler_remove(handle, region)
    except (ValueError, RuntimeError, ReferenceError):
        pass
