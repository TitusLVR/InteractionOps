"""Persistent GPU widget framework.

Clickable, persistent GPU-drawn panels in the 3D viewport (design doc:
docs/superpowers/specs/2026-06-11-gpu-widget-system-design.md).

Three runtime pieces:
1. Persistent POST_PIXEL draw handler (state.py) — active only while a
   widget is visible; draws via ui/draw primitives + ui/hud/text.
2. Transient interaction modal (events.py, iops.widget_interact) — a
   LEFTMOUSE PRESS keymap entry in the 3D View addon keymap; lives for one
   click/drag gesture, passes through when the cursor isn't on a panel.
3. Toggle operator (events.py, iops.widget_toggle, `name` prop) —
   bindable; shows the panel at the cursor / hides and persists position.

Concrete widgets subclass `Widget`, declare controls in `build()`, and are
made live with `register_widget()` (see widgets/edge_data.py).

NOTE: panel.py and controls.py are importable WITHOUT bpy (plain pytest);
this __init__ guards its bpy-dependent imports so `ui.widgets.panel` etc.
stay importable from the test harness too.
"""
from .panel import WidgetPanel, Rect
from .controls import (Control, Section, Slider, PresetRow, FlipBox,
                       ActionButton, Row, Swatch)

try:
    import bpy  # noqa: F401
    _HAS_BPY = True
except ModuleNotFoundError:
    _HAS_BPY = False


class Widget:
    """Base class for a declarative widget panel.

    Subclasses set `name` (registry key / toggle prop), `title` (title-bar
    text), `space` (area type the widget lives in), implement `build()`
    returning the control list, and `poll(context)` returning whether the
    widget is in its working context (False = grayed "out of context"
    panel where only drag/close work).
    """

    name = ""
    title = ""
    space = "VIEW_3D"

    def __init__(self):
        self.controls = list(self.build())
        self.panel = WidgetPanel(title=self.title or self.name)

    def build(self):
        return []

    def poll(self, context):
        return True

    def rows(self):
        """Top-level controls — one visual row each (Row = 1 row, N cols)."""
        return self.controls

    def control_at(self, row, col):
        """Resolve a panel hit_test ("control", (row, col)) to a control."""
        if not (0 <= row < len(self.controls)):
            return None
        ctrl = self.controls[row]
        if isinstance(ctrl, Row):
            if 0 <= col < len(ctrl.children):
                return ctrl.children[col]
            return None
        return ctrl

    def mark_dirty(self):
        """Invalidate every cached control value (selection/undo/depsgraph
        changed). Recompute happens lazily on next draw."""
        for ctrl in self.controls:
            ctrl.mark_dirty()


# ----------------------------------------------------------------------
# Registry — name -> live Widget instance
# ----------------------------------------------------------------------
_REGISTRY = {}


def register_widget(widget):
    """Register a Widget subclass (or instance). Returns the live instance.
    Re-registering the same name replaces the old instance (addon reload)."""
    inst = widget() if isinstance(widget, type) else widget
    if not inst.name:
        raise ValueError("Widget needs a non-empty `name`")
    _REGISTRY[inst.name] = inst
    return inst


def unregister_widget(name):
    _REGISTRY.pop(name, None)


def get_widget(name):
    return _REGISTRY.get(name)


def iter_widgets():
    return tuple(_REGISTRY.values())


# ----------------------------------------------------------------------
# Package wiring (bpy only). The operator classes are exported through
# `classes` for the root __init__.py classes tuple; package register()
# wires keymap + app/draw handlers and must run AFTER the classes are
# registered and after load_iops_preferences() (it reads persisted state).
# ----------------------------------------------------------------------
if _HAS_BPY:
    from . import events, state, render  # noqa: F401

    classes = events.classes

    def register():
        state.register()
        events.register_keymap()

    def unregister():
        events.unregister_keymap()
        state.unregister()
else:  # plain pytest / headless tooling without bpy
    classes = ()

    def register():
        pass

    def unregister():
        pass


__all__ = [
    "Widget", "WidgetPanel", "Rect",
    "Control", "Section", "Slider", "PresetRow", "FlipBox",
    "ActionButton", "Row", "Swatch",
    "register_widget", "unregister_widget", "get_widget", "iter_widgets",
    "classes", "register", "unregister",
]
