"""Widget runtime state: visibility / position / area anchor, persistence,
the persistent POST_PIXEL draw handler, and app handlers.

State per widget is plain data only:
    {"visible": bool, "x": float, "y": float, "anchor_area_ptr": int,
     "switches": dict}
(x, y) is the panel's top-left in region pixels. `anchor_area_ptr` is the
`area.as_pointer()` of the area the widget was summoned in — NOT persisted
(pointers are meaningless across sessions/loads); when the anchor area no
longer exists the widget re-anchors to the largest matching viewport.

Persistence: visible/x/y/switches serialize as JSON into
`Scene.IOPS.widgets_ui_state` — per .blend, written ONLY during save_pre
(open/close/drag events never dirty the file) and restored wholesale at
load_post. A file with no stored record opens with all widgets closed.
Every access is defensive so the framework degrades to session-only
state when the property is missing.

The draw handler is added only while at least one widget is visible and is
removed when the last one hides — idle cost is zero. The callback is
wrapped so an exception skips the frame (logged once per widget), never
breaking the viewport.
"""
from __future__ import annotations

import bpy
from bpy.app.handlers import persistent

from ..draw import safe_handler_add, safe_handler_remove
from .persistence import dumps_states, parse_states

_SCENE_PROP = "widgets_ui_state"

# name -> {"visible", "x", "y", "anchor_area_ptr", "switches"}
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
    draw handler."""
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


def hide_widget(name):
    """Hide a widget, recording its current panel position (runtime only —
    persisted at next save). Removes the draw handler when nothing is
    left visible."""
    from . import get_widget
    st = get_state(name)
    widget = get_widget(name)
    if widget is not None:
        st["x"] = widget.panel.x
        st["y"] = widget.panel.y
    st["visible"] = False
    if not any_visible():
        remove_draw_handler()
    tag_redraw_all()


def store_position(name, x, y):
    """Record a new panel position (drag finished; runtime only — persisted at next save)."""
    st = get_state(name)
    st["x"] = float(x)
    st["y"] = float(y)


def store_switches(name, switches):
    """Record a widget's local switch state (runtime only — persisted at next save)."""
    st = get_state(name)
    st["switches"] = {str(k): bool(v) for k, v in switches.items()}


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
# Persistence (JSON in Scene.IOPS.widgets_ui_state — per .blend)
# ----------------------------------------------------------------------
def _refresh_runtime_states():
    """Pull live panel positions and switch maps into _states so a
    snapshot reflects what's on screen."""
    from . import get_widget
    for name, st in _states.items():
        widget = get_widget(name)
        if widget is None:
            continue
        st["x"] = float(widget.panel.x)
        st["y"] = float(widget.panel.y)
        if getattr(widget, "switches", None):
            st["switches"] = {str(k): bool(v)
                              for k, v in widget.switches.items()}


def save_states_to_scenes():
    """Snapshot runtime state into EVERY scene (multi-scene files stay
    consistent regardless of the active scene at load). Called from
    save_pre — the write lands inside the save, so no dirty flag — and
    from unregister (dev reload; may dirty, accepted)."""
    _refresh_runtime_states()
    raw = dumps_states(_states)
    try:
        scenes = list(bpy.data.scenes)
    except AttributeError:
        return
    for scene in scenes:
        if getattr(scene, "library", None) is not None:
            continue
        iops = getattr(scene, "IOPS", None)
        if iops is None or not hasattr(iops, _SCENE_PROP):
            continue
        try:
            setattr(iops, _SCENE_PROP, raw)
        except Exception as e:
            print("IOPS widgets: scene state save failed:", e)


def load_states_from_scene():
    """Replace runtime states WHOLESALE from the stored scene snapshot.
    Missing property / empty / invalid → all widgets closed (the
    per-file record is the only source of truth). Anchors come back 0
    so the first draw re-anchors to the largest viewport."""
    from . import get_widget, iter_widgets
    # Read via bpy.data, NOT bpy.context: context is restricted during ANY
    # addon registration (including live re-enable, where no load_post
    # follows to repair an empty restore). Every non-linked scene carries
    # the same snapshot, so the first one is authoritative. bpy.data is
    # restricted only during startup registration — degrading to "" there
    # is fine because startup always fires load_post afterwards.
    raw = ""
    try:
        scene = next((s for s in bpy.data.scenes
                      if getattr(s, "library", None) is None), None)
    except AttributeError:
        scene = None
    if scene is not None:
        iops = getattr(scene, "IOPS", None)
        raw = getattr(iops, _SCENE_PROP, "") if iops is not None else ""
    _states.clear()
    _states.update(parse_states(raw))
    # Live widget objects survive the load — reset every widget's switches
    # to its defaults IN PLACE (identity must be preserved: controls close
    # over this dict via switch_store=inst.switches) before applying any
    # stored values on top. Widgets with no stored entry thereby return to
    # defaults instead of keeping the previous file's values.
    for widget in iter_widgets():
        defaults = getattr(widget, "default_switches", None)
        if defaults is not None:
            widget.switches.clear()
            widget.switches.update(defaults)
    for name, st in _states.items():
        widget = get_widget(name)
        if widget is None:
            continue
        widget.panel.x = st["x"]
        widget.panel.y = st["y"]
        if getattr(widget, "switches", None):
            for k, v in st["switches"].items():
                if k in widget.switches:
                    widget.switches[k] = bool(v)


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
    # Restore this file's widget set. Area pointers are invalid after a
    # load — parse_states returns anchors as 0, so the next draw
    # re-anchors to the largest viewport.
    global _draw_guard_logged
    _draw_error_logged.clear()
    _draw_guard_logged = False
    load_states_from_scene()
    mark_all_dirty()
    if any_visible():
        ensure_draw_handler()
    else:
        remove_draw_handler()
    tag_redraw_all()


@persistent
def _on_save_pre(_dummy):
    save_states_to_scenes()


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
    ("save_pre", _on_save_pre),
    ("depsgraph_update_post", _on_depsgraph_update),
    ("undo_post", _on_undo_redo),
    ("redo_post", _on_undo_redo),
)


def _deferred_restore():
    """One-shot bpy.app.timers callback scheduled by register().

    Registration runs under Blender's restricted context AND restricted
    data — even for a live re-enable — so the scene read must wait for
    the first main-loop tick. By then the whole addon (composed widgets
    included) is registered and bpy.data is real. Returning None
    unregisters the timer."""
    load_states_from_scene()
    mark_all_dirty()
    if any_visible():
        ensure_draw_handler()
    else:
        remove_draw_handler()
    tag_redraw_all()
    return None


def register():
    """Install app handlers and defer this file's widget-state restore to
    a one-shot bpy.app.timers callback. (Registration — including a live
    mid-session re-enable — sees restricted context AND restricted data,
    so no synchronous scene read can work here; the restore runs once the
    first main-loop tick makes bpy.data real again.)"""
    global _app_handlers_installed
    if not _app_handlers_installed:
        for slot, fn in _APP_HANDLER_SLOTS:
            handler_list = getattr(bpy.app.handlers, slot)
            if fn not in handler_list:
                handler_list.append(fn)
        _app_handlers_installed = True
    if not bpy.app.timers.is_registered(_deferred_restore):
        bpy.app.timers.register(_deferred_restore, first_interval=0.0)


def unregister():
    """Persist state and remove ONLY our own handlers. Idempotent."""
    global _app_handlers_installed
    # If the deferred restore never fired (enable → immediate disable),
    # _states is still empty — persisting it would clobber the real
    # snapshot in the scenes. Skip the write in that case.
    restore_pending = False
    try:
        restore_pending = bpy.app.timers.is_registered(_deferred_restore)
        if restore_pending:
            bpy.app.timers.unregister(_deferred_restore)
    except Exception:
        pass
    if not restore_pending:
        save_states_to_scenes()
    remove_draw_handler()
    for slot, fn in _APP_HANDLER_SLOTS:
        handler_list = getattr(bpy.app.handlers, slot)
        if fn in handler_list:
            handler_list.remove(fn)
    _app_handlers_installed = False
