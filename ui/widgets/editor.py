"""Widget edit session runtime (Visual Widget Editor).

Owns the single active edit session and wires the pure document model
(editor_model.EditorDoc) to the live widget, the files on disk, the prefs
widget list, the sidebar and the editor keymap items.

Lifecycle:
    begin(context, name)  -> Session  (widget._editor = session; the
                                       widget draws doc.preview_rows())
    after_commit()        -> rebuild preview + debounced draft write +
                             sync the N-panel; after every doc mutation,
                             undo and redo — never on MOUSEMOVE
    save() / cancel()     -> explicit exits; both delete the draft (but
                             never an older draft still undecided)
    save_duplicate()      -> explicit exit: writes the doc as a NEW widget
                             (unique name), restores the original
    set_width(w)          -> commit of the edge-drag width gesture
    can_edit()            -> False while an older draft awaits
                             Resume/Discard: every doc-changing caller
                             refuses the edit (selection still works)
    end()                 -> implicit exit (widget closed, file load,
                             addon reload); the draft stays on disk

Drafts: `<name>.draft.json` next to the widget JSON, rewritten (debounced,
DRAFT_DELAY after the last commit) with plain file I/O on the in-memory
def; an implicit exit only flushes a pending write the same way, so it
survives the restricted bpy.context/bpy.data of addon register/unregister.

Hooks: state.hide_widget -> on_widget_hidden, composed.unregister_composed
-> on_widget_unregistered, composed.register_composed ->
on_widget_registered (re-points the session at the fresh instance), and
the state.py load_pre handler -> end().
"""
from __future__ import annotations

import json
import os
import shutil

from . import editor_model
from .panel import WidgetPanel

# Palette panel placement (left of the widget; clamped at layout).
PALETTE_W = 140.0
PALETTE_GAP = 12.0
SIDEBAR_CATEGORY = "iOps"


class Session:
    """The one active edit session. Plain data; render/events read it."""

    def __init__(self, name, doc, widget, is_new=False):
        self.name = name                # original (on-disk) widget name
        self.doc = doc                  # editor_model.EditorDoc
        self.widget = widget            # live widget instance
        self.area_ptr = 0
        self.sidebar_was_open = True
        self.is_new = is_new
        self.load_problems = []
        self.draft_available = False
        self.palette = WidgetPanel(title="Add")
        self.palette_placed = False     # default spot chosen at first layout
        # Gesture state read by render (set by the interact modal):
        # {"kind", "src", "rtype", "target", "indicator", "ghost"}
        self.drag = None
        # Resolved once at begin so writing the draft never needs the
        # (possibly restricted) prefs context.
        self.draft_file = ""
        # doc.incomplete() cached per doc revision (refreshed on every
        # rebuild/select) so the N-panel draw never validates per redraw.
        self.incomplete = []


_session = None


def active():
    return _session


# Edge-drag width commits share the N-panel Width field's merge key, so a
# run of width changes (drags or field steps) is one undo step.
WIDTH_MERGE_KEY = ("field", None, "w_width")
DUPLICATE_OFFSET = (24.0, -24.0)    # Save Duplicate: new panel vs original
DUPLICATE_TITLE_SUFFIX = " (copy)"

# Shown by the N-panel (and reported by refused edits) while an older
# draft is undecided.
DRAFT_GATE_MSG = "Resume or Discard the draft first"


def can_edit():
    """True when the active session may change its doc. The single gate
    for every doc-changing commit (gestures, editor keys, panel fields):
    while an older draft awaits Resume/Discard, write_draft is skipped,
    so an edit made now would be lost on any implicit exit — refuse it
    up front instead (selection still works)."""
    return _session is not None and not _session.draft_available


# ----------------------------------------------------------------------
# Small helpers
# ----------------------------------------------------------------------
def _composed():
    from ...widgets import composed
    return composed


def _sync_panel():
    """Task 8 hook: mirror the selection into the N-panel props."""
    try:
        from . import editor_panel
        editor_panel.sync_from_selection()
    except (ImportError, AttributeError):
        pass
    except Exception as e:
        print("IOPS widget editor: panel sync failed:", e)


def _editor_kmis(add):
    """Task 7 hook: editor keymap items exist only while editing."""
    try:
        from . import events
        fn = getattr(events, "add_editor_kmis" if add
                     else "remove_editor_kmis", None)
        if fn is not None:
            fn()
    except Exception as e:
        print("IOPS widget editor: keymap update failed:", e)


def _redraw():
    try:
        from . import state
        state.tag_redraw_all()
    except Exception:
        pass


def _find_area(ptr):
    import bpy
    if not ptr:
        return None
    try:
        windows = bpy.context.window_manager.windows
    except AttributeError:
        return None
    for win in windows:
        for area in win.screen.areas:
            if area.as_pointer() == ptr:
                return area
    return None


def _on_switch_for(widget):
    def on_switch(_name, _value):
        from . import state
        state.store_switches(widget.name, widget.switches)
        state.tag_redraw_all()
    return on_switch


def _rebuild_widget(widget, rows, title, width):
    composed = _composed()
    widget.controls = composed.build_controls(
        rows, switch_store=widget.switches,
        on_switch=_on_switch_for(widget), widget_name=widget.name)
    widget.panel.title = title or widget.name
    widget.min_content_w = width


def _remove_file(path):
    try:
        if path and os.path.isfile(path):
            os.remove(path)
    except OSError as e:
        print("IOPS widget editor: could not remove", path, "-", e)


def _load_problems(path):
    """Everything Save would lose from the file at `path`: validate_def's
    problems (invalid rows/cells/values) plus one message per unknown key
    it drops silently. Non-empty -> Save keeps a `.bak`."""
    composed = _composed()
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError) as e:
        return [f"unreadable JSON: {e}"]
    _clean, problems = composed.validate_def(data)
    return list(problems) + composed.dropped_keys(data)


def _format_path(path):
    r, c = path
    return f"row {r + 1}" if c is None else f"row {r + 1} cell {c + 1}"


# ----------------------------------------------------------------------
# Session lifecycle
# ----------------------------------------------------------------------
def begin(context, name, is_new=False):
    """Enter edit mode on composed widget `name`. Returns the Session, or
    None when the widget is unknown or not JSON-composed."""
    global _session
    from . import get_widget, state
    composed = _composed()
    widget = get_widget(name)
    if widget is None or getattr(widget, "composed_def", None) is None:
        return None
    if _session is not None:
        if _session.name == name and _session.widget is widget:
            return _session
        end()

    s = Session(name, editor_model.EditorDoc(widget.composed_def),
                widget, is_new=is_new)
    s.draft_file = composed.draft_path(name)
    path = composed.source_path(name)
    if os.path.isfile(path):
        s.load_problems = _load_problems(path)
    s.draft_available = os.path.isfile(s.draft_file)

    # Anchor area: a visible widget keeps its own anchor; otherwise the
    # invoking area when it fits, else the stored anchor / largest one.
    st = state.get_state(name)
    area = None
    if st.get("visible"):
        area = _find_area(st.get("anchor_area_ptr", 0))
        if area is not None and area.type not in widget.spaces:
            area = None
    if area is None:
        area = getattr(context, "area", None)
        if area is None or area.type not in widget.spaces:
            area = _find_area(st.get("anchor_area_ptr", 0)) \
                or state.find_largest_area(widget.spaces)
    if area is not None:
        s.area_ptr = area.as_pointer()
        if not st.get("visible"):
            x, y = st["x"], st["y"]
            if x <= 0.0 and y <= 0.0:
                x, y = area.width * 0.5, area.height * 0.5
            state.show_widget(name, area=area, x=x, y=y)
        # Sidebar for the N-panel; remember to close it again on exit.
        try:
            space = area.spaces.active
            s.sidebar_was_open = bool(space.show_region_ui)
            space.show_region_ui = True
            for region in area.regions:
                if region.type == "UI":
                    try:
                        region.active_panel_category = SIDEBAR_CATEGORY
                    except Exception:
                        pass
        except Exception as e:
            print("IOPS widget editor: sidebar open failed:", e)

    s.palette.x = widget.panel.x - PALETTE_W - PALETTE_GAP
    s.palette.y = widget.panel.y
    widget._editor = s
    _session = s
    _editor_kmis(True)
    rebuild_preview()
    _sync_panel()
    return s


def rebuild_preview():
    """Rebuild the live widget's controls from the doc (placeholders for
    incomplete elements). Commit/undo/redo only — never MOUSEMOVE."""
    s = _session
    if s is None:
        return
    s.incomplete = s.doc.incomplete()
    wdef = s.doc.wdef
    _rebuild_widget(s.widget, s.doc.preview_rows(),
                    wdef.get("title") or s.name, wdef.get("width"))
    s.widget.mark_dirty()
    _redraw()


def write_draft():
    """Atomic plain-JSON dump of the in-memory def. No bpy access.
    Skipped while an older draft awaits Resume/Discard (never clobber
    it before the user has chosen)."""
    s = _session
    if s is None or not s.draft_file or s.draft_available:
        return
    try:
        os.makedirs(os.path.dirname(s.draft_file), exist_ok=True)
        tmp = s.draft_file + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(s.doc.wdef, f, indent=2)
        os.replace(tmp, s.draft_file)
    except (OSError, TypeError, ValueError) as e:
        print("IOPS widget editor: draft write failed:", e)


# Draft writes are debounced: a dragged N-panel number commits on every
# mouse step, so after_commit only (re-)arms a one-shot timer and the
# file is written once the edits pause. end() flushes it; save()/cancel()
# drop it (they delete the draft anyway).
DRAFT_DELAY = 0.3
_draft_pending = False


def _draft_timer():
    global _draft_pending
    _draft_pending = False
    write_draft()
    return None


def _cancel_draft_timer():
    global _draft_pending
    _draft_pending = False
    try:
        import bpy
        if bpy.app.timers.is_registered(_draft_timer):
            bpy.app.timers.unregister(_draft_timer)
    except Exception:
        pass


def schedule_draft():
    """(Re-)arm the debounced draft write; replaces a pending one."""
    global _draft_pending
    try:
        import bpy
        timers = bpy.app.timers
    except (ImportError, AttributeError):
        write_draft()
        return
    _cancel_draft_timer()
    try:
        timers.register(_draft_timer, first_interval=DRAFT_DELAY)
        _draft_pending = True
    except Exception:
        write_draft()


def draft_pending():
    return _draft_pending


def flush_draft():
    """Write a pending debounced draft now (no-op when none pending)."""
    if _draft_pending:
        _cancel_draft_timer()
        write_draft()


def after_commit():
    if _session is None:
        return
    rebuild_preview()
    schedule_draft()
    _sync_panel()


def select(path):
    """Change the selection (no commit, no draft write)."""
    s = _session
    if s is None:
        return
    s.doc.selection = path
    s.incomplete = s.doc.incomplete()
    _sync_panel()
    _redraw()


def set_width(width):
    """Commit the edge-drag width (rounded, >= composed.MIN_WIDGET_WIDTH —
    validate_def rejects less). Returns True when the doc changed."""
    s = _session
    if s is None or not can_edit():
        return False
    composed = _composed()
    w = int(round(max(float(composed.MIN_WIDGET_WIDTH), float(width))))
    changed = s.doc.set_widget_field("width", w, merge_key=WIDTH_MERGE_KEY)
    if changed:
        after_commit()
    return bool(changed)


def end(keep_draft=True):
    """Leave edit mode without saving (implicit exit). The draft written
    by the last commit stays on disk unless keep_draft is False — and an
    older draft still awaiting Resume/Discard is never deleted (this
    session never wrote it)."""
    global _session
    s = _session
    if s is None:
        return
    if keep_draft:
        flush_draft()        # needs _session: the draft must be current
    else:
        _cancel_draft_timer()
    _session = None          # first: hooks fired below must not re-enter
    if not keep_draft and not s.draft_available:
        _remove_file(s.draft_file)
    widget = s.widget
    try:
        widget._editor = None
        wdef = widget.composed_def
        _rebuild_widget(widget, wdef["rows"], widget.title or widget.name,
                        wdef.get("width"))
        widget.mark_dirty()
    except Exception as e:
        print("IOPS widget editor: widget restore failed:", e)
    if not s.sidebar_was_open:
        try:
            area = _find_area(s.area_ptr)
            if area is not None:
                area.spaces.active.show_region_ui = False
        except Exception:
            pass
    _editor_kmis(False)
    _redraw()


def on_widget_hidden(name):
    if _session is not None and _session.name == name:
        end()


def on_widget_unregistered(name):
    if _session is not None and _session.name == name:
        end()


def on_widget_registered(widget):
    """register_composed made a FRESH instance for the session widget —
    re-point the session (the old instance's _editor flag is gone)."""
    s = _session
    if s is None or s.name != widget.name or s.widget is widget:
        return
    try:
        s.widget._editor = None
    except Exception:
        pass
    s.widget = widget
    widget._editor = s
    rebuild_preview()


# ----------------------------------------------------------------------
# Drafts
# ----------------------------------------------------------------------
def discard_draft():
    s = _session
    if s is None:
        return
    _remove_file(s.draft_file)
    s.draft_available = False
    _redraw()


def resume_draft():
    """Load the draft into the doc (one undoable step). The draft file is
    kept until Save/Cancel."""
    s = _session
    if s is None or not os.path.isfile(s.draft_file):
        return False
    try:
        with open(s.draft_file, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError) as e:
        print("IOPS widget editor: draft unreadable:", e)
        return False
    if not isinstance(data, dict) or not s.doc.replace_all(data):
        return False
    s.draft_available = False
    after_commit()
    return True


# ----------------------------------------------------------------------
# Explicit exits
# ----------------------------------------------------------------------
def _taken_names():
    from . import iter_widgets
    composed = _composed()
    names = {fn[:-len(".json")] for fn in composed.list_widget_files()}
    names.update(w.name for w in iter_widgets())
    return names


def _validated(s):
    """(clean_def, None) for the session doc, or (None, refusal message)
    when an element is incomplete or validate_def reports errors — the
    refusals shared by save() and save_duplicate()."""
    composed = _composed()
    bad = s.doc.incomplete()
    s.incomplete = bad
    if bad:
        return None, ("Incomplete elements: "
                      + ", ".join(_format_path(p) for p in bad))
    clean, errors = composed.validate_def(s.doc.wdef)
    if clean is None or errors:
        return None, "Invalid widget: " + "; ".join(errors or ["no name"])
    return clean, None


def _exit_session(s):
    """End `s` after a successful write: drop the debounced draft write,
    leave edit mode and delete this session's draft (an undecided older
    draft stays offered). Returns (x, y, visible, area) of the panel as
    it was being edited."""
    from . import state
    x, y = s.widget.panel.x, s.widget.panel.y
    visible = bool(state.get_state(s.name).get("visible"))
    area = _find_area(s.area_ptr)
    _cancel_draft_timer()    # the draft is deleted below anyway
    end()
    if not s.draft_available:
        _remove_file(s.draft_file)
    return x, y, visible, area


def save():
    """Validate, write and re-register the widget, then end the session.
    Returns (ok, message)."""
    s = _session
    if s is None:
        return False, "No active widget edit session"
    composed = _composed()
    from . import state
    from . import events
    clean, err = _validated(s)
    if err:
        return False, err
    old = s.name
    new = editor_model.resolve_save_name(clean["name"], old, _taken_names())
    clean["name"] = new

    # Disk writes first: on failure the session (and draft) stay intact.
    try:
        src = composed.widget_path(old)
        bak = src + ".bak"
        if s.load_problems and os.path.isfile(src) \
                and not os.path.exists(bak):
            shutil.copy2(src, bak)
        composed.save_def(clean)
    except OSError as e:
        return False, f"Save failed: {e}"

    x, y, visible, area = _exit_session(s)
    state.store_position(old, x, y)
    if new != old:
        state.store_position(new, x, y)
        composed.register_composed(clean)
        state.hide_widget(old)
        composed.delete_def(old)
        composed.drop_or_restore(old)   # an overridden built-in returns
        events.rename_toggle_kmi(old, new)
        if visible:
            state.show_widget(new, area=area, x=x, y=y)
    else:
        composed.register_composed(clean)
        if visible:
            state.show_widget(new, area=area, x=x, y=y)
    _sync_prefs(new)
    _redraw()
    return True, f"Saved widget '{new}'"


def save_duplicate():
    """Write the edited doc as a NEW widget (unique name from the Name in
    the doc, title + " (copy)") and show it offset from the original; the
    original file is never touched (no .bak either) and the original
    widget goes back to its on-disk definition, like cancel(). A
    never-saved New Widget has no real original: its blank placeholder is
    removed the way cancel() does. Ends the session. Returns
    (ok, message)."""
    s = _session
    if s is None:
        return False, "No active widget edit session"
    composed = _composed()
    from . import state
    clean, err = _validated(s)
    if err:
        return False, err
    old = s.name
    new = composed.unique_name(clean["name"], _taken_names())
    clean["name"] = new
    clean["title"] = (clean.get("title") or old) + DUPLICATE_TITLE_SUFFIX
    path = composed.widget_path(new)
    if path == composed.widget_path(old) or os.path.exists(path):
        return False, f"Save Duplicate failed: '{new}' already exists"
    try:
        composed.save_def(clean)
    except OSError as e:
        return False, f"Save Duplicate failed: {e}"

    x, y, visible, area = _exit_session(s)
    if s.is_new:
        state.hide_widget(old)
        composed.unregister_composed(old)
        composed.delete_def(old)
    else:
        state.store_position(old, x, y)
        composed.register_composed(s.doc.original)
        if visible:
            state.show_widget(old, area=area, x=x, y=y)
    nx, ny = x + DUPLICATE_OFFSET[0], y + DUPLICATE_OFFSET[1]
    state.store_position(new, nx, ny)
    composed.register_composed(clean)
    if area is None:
        try:
            area = state.find_largest_area(clean.get("space") or "VIEW_3D")
        except Exception:
            area = None
    state.show_widget(new, area=area, x=nx, y=ny)
    _sync_prefs(new)
    _redraw()
    return True, f"Saved duplicate widget '{new}'"


def cancel():
    """Drop all edits (and the draft). A never-saved New Widget is
    removed entirely."""
    s = _session
    if s is None:
        return False
    composed = _composed()
    from . import state
    name = s.name
    x, y = s.widget.panel.x, s.widget.panel.y
    end(keep_draft=False)
    if s.is_new:
        state.hide_widget(name)
        composed.unregister_composed(name)
        composed.delete_def(name)
        _sync_prefs(None)
    else:
        state.store_position(name, x, y)
        composed.register_composed(s.doc.original)
    _redraw()
    return True


def _sync_prefs(select):
    try:
        from ...prefs import widget_composer
        widget_composer.sync_from_files(select=select)
    except Exception as e:
        print("IOPS widget editor: prefs sync failed:", e)


# ----------------------------------------------------------------------
# Package wiring (the load_pre handler lives in state._APP_HANDLER_SLOTS)
# ----------------------------------------------------------------------
def register():
    pass


def unregister():
    # end() flushes a pending debounced draft write first.
    end()
    _cancel_draft_timer()
