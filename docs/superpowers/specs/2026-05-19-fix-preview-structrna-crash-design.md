# Fix: `StructRNA has been removed` in Theme Preview operator

## Problem

`IOPS_OT_DrawThemePreview` registers two `SpaceView3D.draw_handler_add` callbacks
bound to `self._draw_view` / `self._draw_px`. When the operator instance is
destroyed by Blender (addon reload, exception during `invoke`, area switch,
unexpected modal exit) the Python wrapper survives but the underlying
`StructRNA` is invalidated. Any attribute access on `self` then raises:

```
ReferenceError: StructRNA of type IOPS_OT_DrawThemePreview has been removed
```

`_cleanup()` only runs on the ESC / RIGHTMOUSE happy path. All other exits
(reload, crash mid-invoke, modal returning `CANCELLED` from elsewhere) leak the
handlers, and Blender keeps firing them every redraw.

## Goals

- No `ReferenceError` spam in console regardless of how the operator exits.
- Theme preview still works correctly on the happy path.
- Pattern is reusable for other operators that register draw handlers.

## Non-goals

- Refactoring the preview operator's geometry / HUD construction.
- Generalising into a base class right now (do it if/when a second operator
  needs the same guard — YAGNI).

## Design

Two layers of defence:

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
