"""Widget runtime state: visibility / position / area anchor, persistence,
the persistent POST_PIXEL draw handler, and app handlers.

State per widget is plain data only:
    {"visible": bool, "x": float, "y": float, "anchor_area_ptr": int}
(x, y) is the panel's top-left in region pixels. `anchor_area_ptr` is the
`area.as_pointer()` of the area the widget was summoned in — NOT persisted
(pointers are meaningless across sessions/loads); when the anchor area no
longer exists the widget re-anchors to the largest matching viewport.

Persistence: visible/x/y serialize as JSON into a single StringProperty
`widgets_state` on the addon preferences. The property itself is added by
the prefs wiring (plus a WIDGETS section in `prefs/iops_prefs.py` /
`operators/preferences/io_addon_preferences.py` for the JSON prefs
round-trip); every access here is defensive so the framework degrades to
session-only state when the property is missing.

The draw handler is added only while at least one widget is visible and is
removed when the last one hides — idle cost is zero. The callback is
wrapped so an exception skips the frame (logged once per widget), never
breaking the viewport.
"""
from __future__ import annotations
import json

import bpy
from bpy.app.handlers import persistent

from ..draw import safe_handler_add, safe_handler_remove

_PREFS_ADDON_KEY = "InteractionOps"
_PREFS_PROP = "widgets_state"

# name -> {"visible", "x", "y", "anchor_area_ptr"}
_states: dict[str, dict] = {}
# space type string -> draw handler handle (one per space with a visible widget)
_draw_handles: dict[str, object] = {}
# Widgets whose draw already raised — log once, then skip silently.
_draw_error_logged: set[str] = set()
# Same once-only guard for failures OUTSIDE the per-widget draw (anchor
# resolution, layout) — the whole callback is wrapped, never the viewport.
_draw_guard_logged = False
_app_handlers_installed = False

# Space-type parameterization. Each entry: area.type -> the bpy Space
# subclass the POST_PIXEL draw handler attaches to. Keep in sync with
# widgets/composed.py WIDGET_SPACES.
SPACE_TYPES = {
    "VIEW_3D": bpy.types.SpaceView3D,
    "IMAGE_EDITOR": bpy.types.SpaceImageEditor,
}


# ----------------------------------------------------------------------
# Per-widget state
# ----------------------------------------------------------------------
def get_state(name):
    st = _states.get(name)
    if st is None:
        st = {"visible": False, "x": 80.0, "y": 400.0,
              "anchor_area_ptr": 0, "switches": {}}
        _states[name] = st
    return st


def any_visible():
    return any(st.get("visible") for st in _states.values())


def show_widget(name, area=None, x=None, y=None):
    """Make a widget visible: anchor it to `area`, place its panel at
    (x, y) top-left (edge clamping happens at first layout), start the
    draw handler, persist."""
    global _draw_guard_logged
    from . import get_widget
    st = get_state(name)
    st["visible"] = True
    if area is not None:
        st["anchor_area_ptr"] = area.as_pointer()
    if x is not None:
        st["x"] = float(x)
    if y is not None:
        st["y"] = float(y)
    widget = get_widget(name)
    if widget is not None:
        widget.panel.x = st["x"]
        widget.panel.y = st["y"]
        widget.mark_dirty()
    _draw_error_logged.discard(name)
    _draw_guard_logged = False
    ensure_draw_handler()
    save_states()


def hide_widget(name):
    """Hide a widget, persisting its current panel position. Removes the
    draw handler when nothing is left visible."""
    from . import get_widget
    st = get_state(name)
    widget = get_widget(name)
    if widget is not None:
        st["x"] = widget.panel.x
        st["y"] = widget.panel.y
    st["visible"] = False
    save_states()
    if not any_visible():
        remove_draw_handler()
    tag_redraw_all()


def store_position(name, x, y):
    """Persist a new panel position (drag finished)."""
    st = get_state(name)
    st["x"] = float(x)
    st["y"] = float(y)
    save_states()


def store_switches(name, switches):
    """Persist a widget's local switch state (a {name: bool} dict)."""
    st = get_state(name)
    st["switches"] = {str(k): bool(v) for k, v in switches.items()}
    save_states()


# ----------------------------------------------------------------------
# Anchor resolution
# ----------------------------------------------------------------------
def _area_exists(ptr, space):
    """True when the area with pointer `ptr` still exists AND is still one
    of `space` (a single space-type string or an iterable of them) — the
    user switching the anchored area to another editor counts as the
    anchor disappearing (so the widget re-anchors instead of drawing
    nowhere)."""
    if not ptr:
        return False
    spaces = {space} if isinstance(space, str) else set(space)
    for win in bpy.context.window_manager.windows:
        for area in win.screen.areas:
            if area.as_pointer() == ptr:
                return area.type in spaces
    return False


def find_largest_area(space="VIEW_3D"):
    """Largest open area among `space` (a single space-type string or an
    iterable of them) that has a WINDOW region, or None. The re-anchor
    fallback when a widget's summon area disappears."""
    spaces = {space} if isinstance(space, str) else set(space)
    best = None
    biggest = 0
    for win in bpy.context.window_manager.windows:
        for area in win.screen.areas:
            if area.type not in spaces:
                continue
            size = area.width * area.height
            if size <= biggest:
                continue
            if not any(r.type == "WINDOW" for r in area.regions):
                continue
            best = area
            biggest = size
    return best


def _resolve_anchor(widget, st, area_ptr):
    """True when `widget` should appear in the area with pointer
    `area_ptr`. Re-anchors (largest viewport) when the stored anchor area
    no longer exists — layout change or file load."""
    anchor = st.get("anchor_area_ptr", 0)
    if anchor == area_ptr:
        return True
    if _area_exists(anchor, widget.spaces):
        return False
    largest = find_largest_area(widget.spaces)
    if largest is None:
        return False
    st["anchor_area_ptr"] = largest.as_pointer()
    return st["anchor_area_ptr"] == area_ptr


def widgets_in_area(area):
    """Visible widgets anchored to `area` (with re-anchor fallback)."""
    if area is None:
        return []
    from . import get_widget
    ptr = area.as_pointer()
    found = []
    for name, st in _states.items():
        if not st.get("visible"):
            continue
        widget = get_widget(name)
        if widget is None or area.type not in widget.spaces:
            continue
        if _resolve_anchor(widget, st, ptr):
            found.append(widget)
    return found


def widget_under_mouse(area, mx, my):
    """The visible widget in `area` whose panel bounds contain (mx, my),
    or None — the interact operator's hit fast path."""
    for widget in widgets_in_area(area):
        if widget.panel.contains(mx, my):
            return widget
    return None


# ----------------------------------------------------------------------
# Persistence (JSON in prefs StringProperty `widgets_state`)
# ----------------------------------------------------------------------
def _prefs():
    try:
        return bpy.context.preferences.addons[_PREFS_ADDON_KEY].preferences
    except (KeyError, AttributeError):
        return None


def save_states():
    prefs = _prefs()
    if prefs is None or not hasattr(prefs, _PREFS_PROP):
        return
    data = {
        name: {"visible": bool(st.get("visible")),
               "x": float(st.get("x", 80.0)),
               "y": float(st.get("y", 400.0)),
               "switches": {str(k): bool(v)
                            for k, v in st.get("switches", {}).items()}}
        for name, st in _states.items()
    }
    try:
        setattr(prefs, _PREFS_PROP, json.dumps(data))
    except Exception as e:
        print("IOPS widgets: state save failed:", e)


def load_states():
    """Merge persisted visible/x/y into the runtime states. Anchors start
    unset (0) so the first draw/interaction re-anchors to the largest
    viewport. Defensive: missing/invalid prefs leave session defaults."""
    from . import get_widget
    prefs = _prefs()
    if prefs is None:
        return
    raw = getattr(prefs, _PREFS_PROP, "")
    if not raw:
        return
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        print("IOPS widgets: invalid widgets_state JSON — ignored")
        return
    if not isinstance(data, dict):
        return
    for name, entry in data.items():
        if not isinstance(entry, dict):
            continue
        st = get_state(name)
        st["visible"] = bool(entry.get("visible", False))
        try:
            st["x"] = float(entry.get("x", st["x"]))
            st["y"] = float(entry.get("y", st["y"]))
        except (TypeError, ValueError):
            pass
        sw = entry.get("switches", {})
        if isinstance(sw, dict):
            st["switches"] = {str(k): bool(v) for k, v in sw.items()}
            widget = get_widget(name)
            if widget is not None and getattr(widget, "switches", None):
                for k, v in st["switches"].items():
                    if k in widget.switches:
                        widget.switches[k] = bool(v)
        st["anchor_area_ptr"] = 0
        widget = get_widget(name)
        if widget is not None:
            widget.panel.x = st["x"]
            widget.panel.y = st["y"]


# ----------------------------------------------------------------------
# Draw handler
# ----------------------------------------------------------------------
def _draw_widgets(space):
    """POST_PIXEL callback. Pulls bpy.context per frame (a persistent
    handler runs for every viewport); draws only widgets anchored to the
    area currently being drawn. The WHOLE body is exception-wrapped (the
    per-widget guard plus an outer guard around anchor resolution/layout):
    any failure skips the frame — logged once — and never breaks the
    viewport."""
    global _draw_guard_logged
    try:
        ctx = bpy.context
        area = ctx.area
        region = ctx.region
        if area is None or area.type != space:
            return
        if region is None or region.type != "WINDOW":
            return
        from . import render
        for widget in widgets_in_area(area):
            try:
                render.draw_widget(ctx, widget)
            except Exception:
                if widget.name not in _draw_error_logged:
                    _draw_error_logged.add(widget.name)
                    import traceback
                    traceback.print_exc()
                    print(f"IOPS widgets: draw failed for '{widget.name}'"
                          " — frame skipped (further errors muted until"
                          " re-shown)")
    except Exception:
        if not _draw_guard_logged:
            _draw_guard_logged = True
            import traceback
            traceback.print_exc()
            print("IOPS widgets: draw handler failed — frame skipped"
                  " (further errors muted)")


def ensure_draw_handler():
    """Add the POST_PIXEL handler(s) for every space that has a visible
    widget. Idempotent — single handler per space type."""
    from . import get_widget
    needed = set()
    for name, st in _states.items():
        if not st.get("visible"):
            continue
        widget = get_widget(name)
        if widget is None:
            continue
        for sp in widget.spaces:
            if sp in SPACE_TYPES:
                needed.add(sp)
    for space in needed:
        if space in _draw_handles:
            continue
        _draw_handles[space] = safe_handler_add(
            SPACE_TYPES[space], _draw_widgets, (space,),
            "WINDOW", "POST_PIXEL",
        )


def remove_draw_handler():
    for space, handle in list(_draw_handles.items()):
        safe_handler_remove(handle, SPACE_TYPES[space], "WINDOW")
        del _draw_handles[space]


def tag_redraw_all():
    try:
        wm = bpy.context.window_manager
    except AttributeError:
        return
    for win in wm.windows:
        for area in win.screen.areas:
            if area.type in SPACE_TYPES:
                area.tag_redraw()


# ----------------------------------------------------------------------
# App handlers (the addon's first bpy.app.handlers users)
# ----------------------------------------------------------------------
def mark_all_dirty():
    from . import iter_widgets
    for widget in iter_widgets():
        widget.mark_dirty()


@persistent
def _on_load_post(_dummy):
    # Area pointers are invalid after a file load — drop anchors so the
    # next draw re-anchors to the largest viewport, and re-ensure the
    # draw handler in case it was lost with the old wm state.
    global _draw_guard_logged
    for st in _states.values():
        st["anchor_area_ptr"] = 0
    _draw_error_logged.clear()
    _draw_guard_logged = False
    mark_all_dirty()
    if any_visible():
        ensure_draw_handler()


@persistent
def _on_depsgraph_update(*_args):
    # Selection / mesh edits invalidate cached (value, mixed) pairs.
    # Cheap: a flag flip per control; recompute is lazy at next draw.
    # @persistent: Blender drops undecorated app handlers on file load —
    # without it the dirty triggers die after the first File > Open.
    if any_visible():
        mark_all_dirty()


@persistent
def _on_undo_redo(*_args):
    if any_visible():
        mark_all_dirty()
        tag_redraw_all()


_APP_HANDLER_SLOTS = (
    ("load_post", _on_load_post),
    ("depsgraph_update_post", _on_depsgraph_update),
    ("undo_post", _on_undo_redo),
    ("redo_post", _on_undo_redo),
)


def register():
    """Install app handlers, load persisted state, start drawing if a
    widget was left visible. Call AFTER load_iops_preferences()."""
    global _app_handlers_installed
    if not _app_handlers_installed:
        for slot, fn in _APP_HANDLER_SLOTS:
            handler_list = getattr(bpy.app.handlers, slot)
            if fn not in handler_list:
                handler_list.append(fn)
        _app_handlers_installed = True
    load_states()
    if any_visible():
        ensure_draw_handler()


def unregister():
    """Persist state and remove ONLY our own handlers. Idempotent."""
    global _app_handlers_installed
    save_states()
    remove_draw_handler()
    for slot, fn in _APP_HANDLER_SLOTS:
        handler_list = getattr(bpy.app.handlers, slot)
        if fn in handler_list:
            handler_list.remove(fn)
    _app_handlers_installed = False
