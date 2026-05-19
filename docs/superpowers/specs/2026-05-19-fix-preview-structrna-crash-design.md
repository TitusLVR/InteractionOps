# Fix: `StructRNA has been removed` — addon-wide draw-handler safeguard

## Problem

`IOPS_OT_DrawThemePreview` registers two `SpaceView3D.draw_handler_add` callbacks
bound to `self._draw_view` / `self._draw_px`. When the operator instance is
destroyed by Blender (addon reload, exception during `invoke`, area switch,
unexpected modal exit) the Python wrapper survives but the underlying
`StructRNA` is invalidated. Any attribute access on `self` then raises:

```
ReferenceError: StructRNA of type IOPS_OT_DrawThemePreview has been removed
```

This is **not specific to the preview operator** — every modal operator in
the addon registers draw handlers bound to `self` (20 files, ~40 registration
sites). Every one of them can spam the console on abnormal exit. We fix them
all in one pass.

`_cleanup()` only runs on the happy path. All other exits (reload, crash
mid-invoke, modal returning `CANCELLED` from a place that forgot cleanup)
leak the handlers, and Blender keeps firing them every redraw.

## Goals

- No `ReferenceError` spam in console regardless of how any operator exits.
- All current modal operators benefit (preview + 19 others).
- One central helper, so future operators get safety by default.
- Happy paths unchanged.

## Non-goals

- Refactoring operators' internals beyond the registration call.
- Removing handler leaks on abnormal exit (silent no-op is enough; the next
  reload cleans them up).

## Design

### Central helper

`ui/draw/handlers.py`:

```python
def safe_handler_add(space_type, callback, args, region, draw_type):
    """Drop-in for `space_type.draw_handler_add` that swallows
    `ReferenceError` raised when the owning operator's StructRNA has been
    destroyed. On first occurrence the handler removes itself so Blender
    stops calling it. Returns the original handle for symmetry with
    `draw_handler_add` (use `safe_handler_remove` to remove)."""

def safe_handler_remove(handle, space_type, region):
    """Drop-in for `draw_handler_remove` that swallows ValueError /
    RuntimeError / ReferenceError so cleanup is idempotent."""
```

Implementation uses a small callable proxy that holds the original
callback + its own handle, so on `ReferenceError` it can call
`safe_handler_remove` on itself.

### Migration

Every operator that today does:

```python
self._handle = bpy.types.SpaceView3D.draw_handler_add(
    self.draw_cb, args, 'WINDOW', 'POST_PIXEL')
```

becomes:

```python
from ..ui.draw import safe_handler_add, safe_handler_remove
self._handle = safe_handler_add(
    bpy.types.SpaceView3D, self.draw_cb, args, 'WINDOW', 'POST_PIXEL')
```

and removal becomes `safe_handler_remove(self._handle, ..., 'WINDOW')`.

### Preview operator specifically

The theme-preview operator gets an extra layer: it stores its draw state in
a plain dict (`{"dead": False, "hud": ..., "edges": ...}`) and the draw
handlers receive that dict, not `self`. This way even if the operator dies
mid-invoke before the safeguard wires up, the handlers degrade to a no-op
read of `state["dead"]`.

Two layers of defence overall:

**1. Self-guard inside each draw callback.** Wrap the body in a small helper
that swallows `ReferenceError` and removes the handler on first sight of a
dead `self`. The handler is the only thing keeping the closure alive — once
it is removed Blender stops calling it and the wrapper is GC'd.

```python
def _draw_view(self, context):
    try:
        edges, preview, snaps, closest = (
            self.edges, self.preview, self.snaps, self.closest,
        )
    except ReferenceError:
        _safe_remove(getattr(self, "_h_view", None), "WINDOW")
        return
    with draw_scope(blend="ALPHA", depth="ALWAYS"):
        draw.edges_3d(edges,   role=Role.LOCKED_LINE)
        ...
```

`_safe_remove` is a module-level helper that calls
`SpaceView3D.draw_handler_remove` in a `try/except (ValueError, RuntimeError,
ReferenceError)` — Blender raises if the handler is already gone.

**2. Make `_cleanup` idempotent and exception-safe.** Wrap each
`draw_handler_remove` call individually; null out the attribute after success
so a second call is a no-op. Call `_cleanup` from a `try/finally` around the
`invoke` setup so a failure between `draw_handler_add` and
`modal_handler_add` doesn't leak handlers.

## Verification

- Manual: open Theme tab, click "Preview Theme", ESC → no errors. Repeat
  with addon disable/enable while preview is active → no spam in console.
- Manual: forcibly reload the addon (`F3 → Reload Scripts`) while preview is
  active → console clean within one frame.

## Risk

Tiny. Localised to one operator. Catches only `ReferenceError` so legitimate
bugs surface normally.
