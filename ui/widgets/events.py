"""Widget input — toggle operator, transient interaction modal, keymap.

Input architecture (design doc): a persistent draw handler never sees
events; instead a LEFTMOUSE PRESS keymap entry in the addon "3D View"
keymap invokes `iops.widget_interact`. Its poll is a cheap fast path
(visible widget + right area type); `invoke` does the exact bounds test
and returns PASS_THROUGH when the click isn't on a panel, so clicks
outside a widget reach Blender untouched. The modal lives for ONE
click/drag gesture — no long-running modal, zero idle cost.

Gesture rules:
- slider drag live-writes on every MOUSEMOVE (snap to control.snap;
  Ctrl held = smooth), ESC/RMB cancels restoring pre-drag values, one
  ed.undo_push on release;
- flip/preset apply on press, undo_push on release;
- action buttons fire on release inside the button;
- titlebar drag moves the panel, position persists on release;
- the title-bar Close (×) and Edit (pen) buttons highlight while held and
  act on release inside — same contract as action buttons; the pen
  enters the visual editor (editor.begin);
- edit mode (an editor session owns the widget): presses on the widget
  body / Add palette become edit gestures — add from the palette, move
  a cell/row (after MOVE_THRESHOLD px), resize at a cell's right edge.
  MOUSEMOVE only rewrites session.drag + tags a redraw; the EditorDoc is
  mutated once on release (then editor.after_commit); ESC/RMB drops it.

Controls cache plain floats/bools only; setters/getters re-acquire bmesh
per call inside the widget's value adapters — nothing bmesh-shaped is
ever stored on the operator.
"""
import bpy
from bpy.props import BoolProperty, EnumProperty, StringProperty

from . import state
from .controls import TextEditState, DropdownState


def _tag_redraw(context):
    if context.area is not None:
        context.area.tag_redraw()


def _session_here(context):
    """The active edit session when `context.area` is its area, else None."""
    from . import editor
    session = editor.active()
    if (session is None or context.area is None
            or session.area_ptr != context.area.as_pointer()):
        return None
    return session


def _row_kinds(session):
    """Per visual row: True for a ROW container (doc rows are 1:1 with the
    visual rows in edit mode)."""
    return [isinstance(r, dict) and r.get("type") == "ROW"
            for r in session.doc.wdef.get("rows", [])]


def _over_session(context, mx, my):
    """True when (mx, my) is over the session widget or its palette in the
    session's own area (WINDOW region)."""
    session = _session_here(context)
    if session is None or context.region is None \
            or context.region.type != "WINDOW":
        return False
    if session.palette.contains(mx, my):
        return True
    return session.widget.panel.contains(mx, my) and bool(
        state.get_state(session.widget.name).get("visible"))


def _over_session_sidebar(context):
    """True when the event's region is the sidebar (UI region) of the
    session's own area — where the Widget Editor panel lives."""
    return (_session_here(context) is not None
            and context.region is not None
            and context.region.type == "UI")


class IOPS_OT_widget_toggle(bpy.types.Operator):
    """Show/hide a persistent IOPS widget panel"""

    bl_idname = "iops.widget_toggle"
    bl_label = "IOPS Widget Toggle"
    bl_description = "Toggle a persistent GPU widget panel"
    bl_options = {"REGISTER"}
    # NOT is_bindable: a generic unbound entry can't carry the `name`
    # property. Instead sync_toggle_kmis() keeps one entry PER widget in
    # the addon "Window" keymap; the Widgets prefs tab draws the key
    # field per list row.

    name: StringProperty(name="Widget", description="Widget name to toggle",
                         default="")
    # When True (default), summon at the mouse cursor — natural for a
    # viewport hotkey press. The All-Widgets popup sets this False so a
    # click re-opens the widget at its remembered position instead of
    # under the popup.
    use_cursor: BoolProperty(name="At Cursor", default=True)

    def _toggle(self, context, mouse=None):
        from . import get_widget
        widget = get_widget(self.name)
        if widget is None:
            self.report({"ERROR"}, f"IOPS: unknown widget '{self.name}'")
            return {"CANCELLED"}
        st = state.get_state(widget.name)
        if st["visible"]:
            state.hide_widget(widget.name)
        else:
            # Anchor to the invoking area when it matches the widget's
            # space; otherwise fall back to the largest one.
            area = context.area
            if area is None or area.type not in widget.spaces:
                area = state.find_largest_area(widget.spaces)
                mouse = None
            if area is None:
                self.report({"ERROR"},
                            "IOPS: no matching viewport for widget")
                return {"CANCELLED"}
            if mouse is not None:
                x, y = mouse
            else:
                # Re-open at the persisted spot (or area center on first
                # ever show). Edge clamping happens at first layout.
                x, y = st["x"], st["y"]
                if x <= 0.0 and y <= 0.0:
                    x, y = area.width * 0.5, area.height * 0.5
            state.show_widget(widget.name, area=area, x=x, y=y)
        state.tag_redraw_all()
        return {"FINISHED"}

    def invoke(self, context, event):
        # Summon at the cursor when toggled from inside the viewport, but
        # only from a real WINDOW region — a popup/menu region's mouse
        # coords aren't in viewport space. use_cursor=False (the popup)
        # always re-opens at the remembered position.
        mouse = None
        if (self.use_cursor and context.area is not None
                and context.region is not None
                and context.region.type == "WINDOW"
                and context.area.type in state.SPACE_TYPES):
            mouse = (event.mouse_region_x, event.mouse_region_y)
        return self._toggle(context, mouse)

    def execute(self, context):
        return self._toggle(context, None)


class IOPS_OT_widget_interact(bpy.types.Operator):
    """One click/drag gesture on a visible widget panel"""

    bl_idname = "iops.widget_interact"
    bl_label = "IOPS Widget Interact"
    bl_options = {"REGISTER"}

    @classmethod
    def poll(cls, context):
        # Fast path only — runs for EVERY 3D-view click while a widget is
        # visible. The exact bounds test happens in invoke (poll never
        # sees the mouse position) which PASS_THROUGHs on a miss, so
        # clicks off-panel still select/transform normally.
        return (state.any_visible()
                and context.area is not None
                and context.area.type in state.SPACE_TYPES)

    # ------------------------------------------------------------------
    def invoke(self, context, event):
        if context.region is None or context.region.type != "WINDOW":
            return {"PASS_THROUGH"}
        mx, my = event.mouse_region_x, event.mouse_region_y
        session = _session_here(context)
        if session is not None and session.palette.contains(mx, my):
            return self._invoke_palette(context, session, mx, my)
        widget = state.widget_under_mouse(context.area, mx, my)
        if widget is None:
            return {"PASS_THROUGH"}

        hit = widget.panel.hit_test(mx, my)
        if hit is None:
            return {"PASS_THROUGH"}
        kind, where = hit

        self._widget = widget          # registry instance — plain python
        self._control = None
        self._session = None
        self._mode = "swallow"         # consume press+release, no action
        widget._press_cell = None      # clear any stale pressed highlight
        widget._editing = None         # (where, TextEditState) while typing
        widget._dropdown = None        # DropdownState while open

        if (session is not None and widget is session.widget
                and kind not in ("close", "edit", "title")):
            return self._invoke_edit(context, session, mx, my)

        if kind in ("close", "edit"):
            # Title-bar buttons: pressed highlight now, act on release
            # inside (see _finish_gesture). The edit rect only exists for
            # composed widgets, see render.is_editable.
            widget._press_cell = kind          # never equals a (row, col)
            self._rect = (widget.panel.close_rect if kind == "close"
                          else widget.panel.edit_rect)
            self._mode = "title_" + kind
            return self._begin_modal(context)

        if kind == "title":
            widget.panel.start_drag(mx, my)
            self._mode = "drag"
            return self._begin_modal(context)

        try:
            in_context = bool(widget.poll(context))
        except Exception:
            in_context = False

        if kind == "control" and in_context:
            control = widget.control_at(context, *where)
            # update_enabled resolves the live flag (presets/Clear go
            # inert with no selection) — never trust a stale draw.
            if control is not None and control.interactive \
                    and control.update_enabled(context):
                row, col = where
                self._where = where
                self._rect = widget.panel.row_rects[row][col]
                result = self._begin_gesture(context, event, control)
                if result is not None:
                    return result
        # Inside the panel but on nothing actionable (padding, section,
        # disabled control, out-of-context body): swallow the click so it
        # can't deselect/box-select underneath the panel.
        return self._begin_modal(context)

    def _begin_modal(self, context):
        context.window_manager.modal_handler_add(self)
        _tag_redraw(context)
        return {"RUNNING_MODAL"}

    # ------------------------------------------------------------------
    # Edit-mode gestures (visual widget editor). Press routes here when
    # the click lands on the session widget body or its Add palette.
    # MOUSEMOVE only rewrites session.drag (plain data read by render)
    # and tags a redraw; the doc is touched once, on release.
    # ------------------------------------------------------------------
    def _invoke_palette(self, context, session, mx, my):
        from .editor_geom import palette_hit, palette_items
        pal = session.palette
        self._widget = session.widget
        self._control = None
        self._session = session
        self._mode = "swallow"
        if pal.title_rect.contains(mx, my):
            pal.start_drag(mx, my)
            self._mode = "ed_pal_drag"
            return self._begin_modal(context)
        from . import editor
        rtype = palette_hit(pal.row_rects, palette_items(), mx, my)
        # Adding is a doc change: refused while a draft is undecided
        # (editor.can_edit) — the press is swallowed, no ghost appears.
        if rtype is not None and editor.can_edit():
            label = next(lbl for t, lbl in palette_items() if t == rtype)
            session.drag = {"kind": "add", "rtype": rtype, "target": None,
                            "indicator": None, "ghost": (mx, my, label)}
            self._mode = "ed_add"
        return self._begin_modal(context)

    def _invoke_edit(self, context, session, mx, my):
        from .editor_geom import edit_hit
        from . import editor
        self._session = session
        hit = edit_hit(self._widget.panel, _row_kinds(session), mx, my)
        if hit is None:
            return self._begin_modal(context)          # padding — swallow
        kind, path = hit
        if kind == "resize" and editor.can_edit():
            if self._start_resize(session, path, mx):
                editor.select(path)
                self._mode = "ed_resize"
                return self._begin_modal(context)
            kind = "cell"          # not resizable (bad path) — select it
        # "cell" / "row": select now, becomes a move after MOVE_THRESHOLD.
        editor.select(path)
        self._press_xy = (mx, my)
        self._src = path
        self._mode = "ed_press"
        return self._begin_modal(context)

    def _start_resize(self, session, path, mx):
        from .editor_model import span_bounds
        from .render import GRID_COL_GAP
        bounds = span_bounds(session.doc.wdef.get("rows", []), path)
        if bounds is None:
            return False
        r, c = path
        panel = self._widget.panel
        cells = panel.row_rects[r] if r < len(panel.row_rects) else []
        idx = c if c is not None else 0
        if idx >= len(cells):
            return False
        cell = cells[idx]
        start, span, max_span = bounds
        self._rz = {
            "path": path, "start": start, "span0": span, "max": max_span,
            "left": panel.x + panel.padding,
            "cw": panel.width - panel.padding * 2.0,
            "gap": GRID_COL_GAP, "y": cell.y, "h": cell.h,
        }
        session.drag = {"kind": "resize", "src": path, "span": span}
        self._update_resize(session, mx)
        return True

    def _update_resize(self, session, mx):
        from .editor_geom import grid_edge_x, span_from_mouse
        rz = self._rz
        span = span_from_mouse(mx, rz["left"], rz["cw"], rz["gap"],
                               rz["start"], rz["max"])
        x0 = grid_edge_x(rz["left"], rz["cw"], rz["gap"], rz["start"]) \
            + rz["gap"]
        x1 = grid_edge_x(rz["left"], rz["cw"], rz["gap"], rz["start"] + span)
        drag = session.drag
        drag["span"] = span
        drag["outline"] = (x0, rz["y"], x1 - x0, rz["h"])
        drag["indicator"] = ("vline", x1, rz["y"], rz["h"])

    def _start_move(self, session):
        from . import editor
        src = self._src
        el = session.doc.get(src)
        if el is None or not editor.can_edit():
            return False         # refused move: the press only selected
        label = el.get("label") or el.get("type", "").title() or "Item"
        rows_only = src[1] is None and el.get("type") == "ROW"
        session.drag = {"kind": "move", "src": src, "rows_only": rows_only,
                        "target": None, "indicator": None,
                        "ghost": (self._press_xy[0], self._press_xy[1],
                                  label)}
        return True

    def _update_drop(self, session, mx, my, rows_only):
        from .editor_geom import drop_target
        drag = session.drag
        hit = drop_target(session.widget.panel, _row_kinds(session), mx, my,
                          rows_only=rows_only)
        if hit is None:
            drag["target"], drag["indicator"] = None, None
        else:
            drag["target"], drag["indicator"] = hit
        _x, _y, label = drag["ghost"]
        drag["ghost"] = (mx, my, label)

    def _modal_edit_move(self, context, mx, my):
        """MOUSEMOVE for edit gestures — plain drag state + redraw only."""
        session = self._session
        mode = self._mode
        if session is None:
            return {"RUNNING_MODAL"}
        if mode == "ed_pal_drag":
            session.palette.update_drag(mx, my)
            _tag_redraw(context)
            return {"RUNNING_MODAL"}
        if mode == "ed_press":
            from .editor_geom import MOVE_THRESHOLD
            px, py = self._press_xy
            if abs(mx - px) < MOVE_THRESHOLD and abs(my - py) < MOVE_THRESHOLD:
                return {"RUNNING_MODAL"}
            if not self._start_move(session):
                self._mode = "swallow"
                return {"RUNNING_MODAL"}
            self._mode = mode = "ed_move"
        if session.drag is None:
            return {"RUNNING_MODAL"}
        if mode == "ed_add":
            self._update_drop(session, mx, my,
                              session.drag["rtype"] == "ROW")
        elif mode == "ed_move":
            self._update_drop(session, mx, my, session.drag["rows_only"])
        elif mode == "ed_resize":
            self._update_resize(session, mx)
        _tag_redraw(context)
        return {"RUNNING_MODAL"}

    def _finish_edit(self, context):
        """Release of an edit gesture: one doc mutation + after_commit()."""
        from . import editor
        from .editor_geom import is_noop_move
        from .editor_model import new_element
        session = self._session
        mode = self._mode
        drag = session.drag if session is not None else None
        if session is not None:
            session.drag = None
        if session is None or editor.active() is not session:
            _tag_redraw(context)
            return {"FINISHED"}
        changed = False
        if mode != "ed_pal_drag" and not editor.can_edit():
            mode = None          # draft undecided: never mutate the doc
        if mode == "ed_pal_drag":
            session.palette.end_drag()
            if context.region is not None:
                session.palette.clamp_to_region(context.region.width,
                                                context.region.height)
        elif mode == "ed_add" and drag and drag.get("target") is not None:
            changed = session.doc.insert(
                drag["target"], new_element(drag["rtype"])) is not None
        elif mode == "ed_move" and drag and drag.get("target") is not None:
            if not is_noop_move(drag["src"], drag["target"]):
                changed = session.doc.move(drag["src"],
                                           drag["target"]) is not None
        elif mode == "ed_resize" and drag:
            span = drag.get("span")
            if span is not None and span != self._rz["span0"]:
                changed = session.doc.set_span(self._rz["path"], span)
        if changed:
            editor.after_commit()
        _tag_redraw(context)
        return {"FINISHED"}

    def _begin_gesture(self, context, event, control):
        mx = event.mouse_region_x
        if control.kind == "slider":
            value, mixed = control.value(context)
            if value is None and not mixed:
                return None            # disabled — swallow
            self._control = control
            # Pre-drag restore data: optional per-edge snapshot from the
            # widget adapters, plus the plain pre-value fallback.
            self._pre_value = value
            self._pre_mixed = bool(mixed)
            self._snapshot = None
            if control.snapshot is not None:
                self._snapshot = control.snapshot(context)
            control.write(context,
                          control.drag_value(mx, smooth=event.ctrl))
            self._mode = "slider"
            return self._begin_modal(context)

        if control.kind == "flipbox":
            # No selection (spec: inert): no write, no undo push, and no
            # optimistic cache update faking a CHECKED box.
            value, mixed = control.value(context)
            if value is None and not mixed:
                return None            # swallow
            control.write(context, control.next_value(context))
            self._widget.mark_dirty()
            self._control = control
            self._mode = "release_undo"
            return self._begin_modal(context)

        if control.kind == "presets":
            index = control.index_at(mx, self._rect.x, self._rect.w)
            if index < 0:
                return None            # gap between buttons — swallow
            control.write(context, control.values[index])
            self._widget.mark_dirty()
            self._control = control
            self._mode = "release_undo"
            return self._begin_modal(context)

        if control.kind == "buttons":
            # Radio-button group: write the clicked option's value on
            # press (like PRESETS), one undo_push on release. Gap clicks
            # (index < 0) swallow.
            index = control.index_at(mx, self._rect.x, self._rect.w)
            if index < 0:
                return None            # gap between buttons — swallow
            control.write(context, control.options[index][0])
            self._widget.mark_dirty()
            self._control = control
            self._mode = "release_undo"
            return self._begin_modal(context)

        if control.kind == "input":
            # In-overlay text entry: seed the buffer from the live value and
            # select-all so the first keystroke replaces it (immediate focus,
            # no popup). The modal stays open until Enter/Esc/click-away.
            self._control = control
            self._edit = TextEditState(control.edit_string(context))
            self._edit.select_all()
            self._mode = "text_edit"
            self._widget._editing = (self._where, self._edit)
            return self._begin_modal(context)

        if control.kind == "dropdown":
            # In-overlay item list: opens below/above the field (whichever
            # fits), scrolls when clipped, filters as you type. Empty list
            # (no items, no labels) -> swallow.
            items = control.items(context)
            if not items:
                return None
            from . import render
            cur, _ = control.get(context)
            r = self._rect
            self._control = control
            self._dd = DropdownState(items, (r.x, r.y, r.w, r.h),
                                     context.region.height,
                                     render.DROPDOWN_ITEM_H, current=cur)
            self._mode = "dropdown_open"
            self._widget._dropdown = self._dd
            return self._begin_modal(context)

        if control.kind in ("button", "swatch"):
            # Swatch fires its operator on release-inside, exactly like a
            # button (one ed.undo_push, mark_dirty afterwards).
            self._control = control
            self._mode = "button"
            # Arm the pressed highlight (rendered only for buttons).
            self._widget._press_cell = self._where
            return self._begin_modal(context)
        return None

    # ------------------------------------------------------------------
    def modal(self, context, event):
        # Text-edit and dropdown modes own their own event handling (they
        # stay open across mouse-release, unlike the one-gesture modes).
        if self._mode == "text_edit":
            return self._modal_text(context, event)
        if self._mode == "dropdown_open":
            return self._modal_dropdown(context, event)

        mx, my = event.mouse_region_x, event.mouse_region_y
        panel = self._widget.panel

        if event.type in {"ESC", "RIGHTMOUSE"} and event.value == "PRESS":
            return self._cancel_gesture(context)

        if event.type in {"MOUSEMOVE", "INBETWEEN_MOUSEMOVE"}:
            if self._mode.startswith("ed_"):
                return self._modal_edit_move(context, mx, my)
            if self._mode == "drag":
                panel.update_drag(mx, my)
                _tag_redraw(context)
            elif self._mode == "slider":
                # Live write per move; snapping is ctrl-aware each event
                # so holding/releasing Ctrl mid-drag just works.
                self._control.write(
                    context,
                    self._control.drag_value(mx, smooth=event.ctrl))
                _tag_redraw(context)
            return {"RUNNING_MODAL"}

        if event.type == "LEFTMOUSE" and event.value == "RELEASE":
            return self._finish_gesture(context, mx, my)

        return {"RUNNING_MODAL"}

    def _finish_gesture(self, context, mx, my):
        panel = self._widget.panel
        mode = self._mode
        if mode.startswith("ed_"):
            return self._finish_edit(context)
        if mode == "drag":
            panel.end_drag()
            if context.region is not None:
                panel.clamp_to_region(context.region.width,
                                      context.region.height)
            state.store_position(self._widget.name, panel.x, panel.y)
        elif mode == "slider":
            self._undo_push()
        elif mode == "release_undo":
            self._undo_push()
        elif mode == "button":
            if self._rect.contains(mx, my):
                try:
                    self._control.execute(context)
                except Exception as e:
                    self.report({"ERROR"}, f"IOPS widget action failed: {e}")
                self._widget.mark_dirty()
                self._undo_push()
        elif mode == "title_close":
            if self._rect.contains(mx, my):
                self._widget._press_cell = None
                state.hide_widget(self._widget.name)
                return {"FINISHED"}
        elif mode == "title_edit":
            # Enter the visual editor on this widget (the N-panel's "Open
            # JSON" button still opens the raw file). Inert on the widget
            # already being edited (its pen isn't laid out anyway).
            if self._rect.contains(mx, my):
                from . import editor
                session = editor.active()
                if session is None or session.widget is not self._widget:
                    editor.begin(context, self._widget.name)
        elif mode == "edit_button":
            # Dropdown / input: pop the native editor on release-inside.
            # NO _undo_push — the native field edit pushes its own undo
            # step. No mark_dirty either: these controls read their getter
            # live each draw (the external popup never triggers mark_dirty).
            if self._rect.contains(mx, my):
                try:
                    self._control.execute(context)
                except Exception as e:
                    self.report({"ERROR"}, f"IOPS widget action failed: {e}")
        self._widget._press_cell = None
        _tag_redraw(context)
        return {"FINISHED"}

    def _cancel_gesture(self, context):
        panel = self._widget.panel
        if self._mode.startswith("ed_"):
            # Edit drags: drop the preview — the doc was never touched.
            session = self._session
            if session is not None:
                session.drag = None
                if self._mode == "ed_pal_drag":
                    session.palette.cancel_drag()
            _tag_redraw(context)
            return {"CANCELLED"}
        if self._mode == "drag":
            panel.cancel_drag()
        elif self._mode == "release_undo":
            # Flip/preset writes land on PRESS — by ESC/RMB time the mesh
            # is already modified. Record the write as its own undo step
            # (same as release) so it can never silently fold into the
            # PREVIOUS undo step (one-push-per-gesture contract).
            self._undo_push()
        elif self._mode == "slider":
            control = self._control
            if control.restore is not None and self._snapshot is not None:
                # Exact per-edge restore provided by the widget adapters.
                control.restore(context, self._snapshot)
            elif not self._pre_mixed and self._pre_value is not None:
                # Fallback: uniform pre-drag value. A mixed pre-state
                # without a snapshot hook can't be restored — leave as-is.
                control.write(context, self._pre_value)
            control.mark_dirty()
        self._widget._press_cell = None
        _tag_redraw(context)
        return {"CANCELLED"}

    def _undo_push(self):
        # ONE undo step per completed gesture — live writes during the
        # drag never spam the undo stack.
        try:
            bpy.ops.ed.undo_push(
                message=f"IOPS {self._widget.panel.title}")
        except Exception as e:
            print("IOPS widgets: undo_push failed:", e)

    # ------------------------------------------------------------------
    # In-overlay text edit (mode "text_edit")
    # ------------------------------------------------------------------
    def _modal_text(self, context, event):
        ed = self._edit
        et, ev = event.type, event.value

        if et == "ESC" and ev == "PRESS":
            return self._end_edit(context)                 # discard
        if et in {"RET", "NUMPAD_ENTER"} and ev == "PRESS":
            return self._commit_text(context)
        if et == "LEFTMOUSE" and ev == "PRESS":
            # Click inside the field keeps editing; click anywhere else
            # commits (and the click is swallowed so it can't deselect).
            return {"RUNNING_MODAL"} if self._rect.contains(
                event.mouse_region_x, event.mouse_region_y) \
                else self._commit_text(context)

        if ev == "PRESS":
            handled = True
            if et == "BACK_SPACE":
                ed.backspace()
            elif et == "DEL":
                ed.delete()
            elif et == "LEFT_ARROW":
                ed.left(extend=event.shift)
            elif et == "RIGHT_ARROW":
                ed.right(extend=event.shift)
            elif et == "HOME":
                ed.home(extend=event.shift)
            elif et == "END":
                ed.end(extend=event.shift)
            elif et == "A" and event.ctrl:
                ed.select_all()
            elif et in {"C", "X"} and event.ctrl:
                sel = ed.selected_text()
                if sel:
                    context.window_manager.clipboard = sel
                    if et == "X":
                        ed.backspace()                     # delete selection
            elif et == "V" and event.ctrl:
                ed.insert(context.window_manager.clipboard or "")
            elif event.unicode and not event.ctrl and not event.alt:
                ed.insert(event.unicode)                   # printable char
            else:
                handled = False
            if handled:
                _tag_redraw(context)
                return {"RUNNING_MODAL"}

        return {"RUNNING_MODAL"}

    def _commit_text(self, context):
        try:
            self._control.write(context, self._edit.text)
            self._undo_push()
        except (ValueError, TypeError):
            pass            # unparseable (e.g. number from text) — discard
        return self._end_edit(context)

    def _end_edit(self, context):
        self._widget._editing = None
        _tag_redraw(context)
        return {"FINISHED"}

    # ------------------------------------------------------------------
    # In-overlay dropdown list (mode "dropdown_open")
    # ------------------------------------------------------------------
    def _modal_dropdown(self, context, event):
        dd = self._dd
        mx, my = event.mouse_region_x, event.mouse_region_y
        et, ev = event.type, event.value

        if et == "ESC" and ev == "PRESS":
            if dd.filter:
                dd.clear_filter()          # first ESC clears the filter
                _tag_redraw(context)
                return {"RUNNING_MODAL"}
            return self._close_dropdown(context)

        if et in {"RET", "NUMPAD_ENTER"} and ev == "PRESS":
            picked = dd.hovered()
            if picked is not None:
                return self._dd_pick(context, picked[0])
            return {"RUNNING_MODAL"}

        if et in {"WHEELUPMOUSE", "WHEELDOWNMOUSE"} and ev == "PRESS":
            dd.scroll(1 if et == "WHEELDOWNMOUSE" else -1)
            dd.hover = dd.index_at(my)     # window moved under the mouse
            _tag_redraw(context)
            return {"RUNNING_MODAL"}

        if et in {"MOUSEMOVE", "INBETWEEN_MOUSEMOVE"}:
            dd.hover = dd.index_at(my)
            _tag_redraw(context)
            return {"RUNNING_MODAL"}

        if et == "LEFTMOUSE":
            idx = dd.index_at(my)
            if idx >= 0:
                # Pick on either the opening drag-release or a later click.
                return self._dd_pick(context, dd.filtered()[idx][0])
            if (ev == "PRESS" and not self._rect.contains(mx, my)
                    and not dd.in_list(my)):
                return self._close_dropdown(context)   # click-away cancels
            return {"RUNNING_MODAL"}                   # opening release etc.

        if ev == "PRESS":
            # Type-to-filter: printable chars append, backspace pops.
            if et == "BACK_SPACE":
                dd.backspace()
                _tag_redraw(context)
                return {"RUNNING_MODAL"}
            if event.unicode and not event.ctrl and not event.alt:
                dd.type_char(event.unicode)
                _tag_redraw(context)
                return {"RUNNING_MODAL"}

        return {"RUNNING_MODAL"}

    def _dd_pick(self, context, ident):
        self._control.write(context, ident)
        self._widget.mark_dirty()
        self._undo_push()
        return self._close_dropdown(context)

    def _close_dropdown(self, context):
        self._widget._dropdown = None
        self._dd = None
        _tag_redraw(context)
        return {"FINISHED"}


# ----------------------------------------------------------------------
# Keymap — programmatic LEFTMOUSE entry, kept OUT of keys_default and
# excluded from save_hotkeys (NEVER_SAVE) so the user hotkey save/load
# flow can't serialize it (the saved tuple would drop any=True and route
# it into the "Window" keymap). The global unregister_keymaps() sweep
# still removes it (idname starts with "iops."), so the load-hotkeys
# operators detach it first via unregister_keymap() and re-add it via
# register_keymap() after their re-registration.
# ----------------------------------------------------------------------
_keymap_items = []


def _ensure_interact_kmi(kc, keymap_name, space_type):
    """Add the LEFTMOUSE PRESS any=True -> iops.widget_interact entry to
    `keymap_name` if it isn't there already. any=True: fires with every
    modifier so Ctrl (smooth slider drag) reaches the modal; off-panel
    clicks PASS_THROUGH."""
    km = kc.keymaps.new(keymap_name, space_type=space_type)
    for kmi in km.keymap_items:
        if kmi.idname == IOPS_OT_widget_interact.bl_idname:
            return
    kmi = km.keymap_items.new(IOPS_OT_widget_interact.bl_idname,
                              "LEFTMOUSE", "PRESS", any=True)
    _keymap_items.append((km, kmi))


# Keymaps that legitimately host the interact entry (name -> space_type).
_INTERACT_KEYMAPS = (
    ("3D View", "VIEW_3D"),
    ("Image", "IMAGE_EDITOR"),
)


def register_keymap():
    """Single registration at addon register (guarded — re-running is a
    no-op, matching the register_ui_toggle_keymaps pattern)."""
    kc = bpy.context.window_manager.keyconfigs.addon
    if kc is None:
        return
    legit = {name for name, _ in _INTERACT_KEYMAPS}
    # Hotkey files saved before iops.widget_interact was excluded from
    # save_hotkeys may have re-created the entry in other addon keymaps
    # ("Window", without any=True) — sweep those strays first so the user
    # never ends up with a duplicate global LMB binding.
    for other in kc.keymaps:
        if other.name in legit:
            continue
        stray = [kmi for kmi in other.keymap_items
                 if kmi.idname == IOPS_OT_widget_interact.bl_idname]
        for kmi in stray:
            other.keymap_items.remove(kmi)
    for name, space_type in _INTERACT_KEYMAPS:
        _ensure_interact_kmi(kc, name, space_type)
    print("IOPS Widget keymap registered")


def unregister_keymap():
    """Remove ONLY the entries this module added. Idempotent."""
    for km, kmi in _keymap_items:
        try:
            km.keymap_items.remove(kmi)
        except (ReferenceError, RuntimeError):
            pass
    _keymap_items.clear()


# ----------------------------------------------------------------------
# Per-widget toggle hotkeys — one iops.widget_toggle entry per registered
# widget in the addon "Window" keymap, created unbound (type NONE) for
# the user to assign from the Widgets prefs tab. These are excluded from
# the user hotkey save/load flow (NEVER_SAVE): the saved tuple format
# can't carry the `name` operator property, so a round-trip would
# collapse every widget binding into nameless duplicates. The global
# unregister_keymaps() sweep removes them (idname starts with "iops."),
# so the load-hotkeys operators call sync_toggle_kmis() after their
# re-registration — same contract as register_keymap() above.
# ----------------------------------------------------------------------
def _toggle_keymap():
    wm = getattr(bpy.context, "window_manager", None)
    if wm is None or wm.keyconfigs.addon is None:
        return None
    return wm.keyconfigs.addon.keymaps.new("Window")


def sync_toggle_kmis():
    """Reconcile the addon keymap with the widget registry: ensure one
    toggle entry per live widget, drop entries for widgets that no longer
    exist and nameless strays (saved by pre-per-widget hotkey files)."""
    from . import iter_widgets
    km = _toggle_keymap()
    if km is None:
        return
    names = {w.name for w in iter_widgets()}
    seen = set()
    for kmi in tuple(km.keymap_items):
        if kmi.idname != IOPS_OT_widget_toggle.bl_idname:
            continue
        wname = kmi.properties.name
        if wname in names and wname not in seen:
            seen.add(wname)
        else:
            km.keymap_items.remove(kmi)
    for wname in sorted(names - seen):
        kmi = km.keymap_items.new(IOPS_OT_widget_toggle.bl_idname,
                                  "NONE", "PRESS")
        kmi.properties.name = wname
    # User-keyconfig orphans: a user-MODIFIED copy survives its addon
    # entry's removal (Blender keeps the diff), leaving a binding that
    # toggles a widget that no longer exists — sweep those too.
    ukm = _user_toggle_keymap()
    if ukm is not None:
        for kmi in tuple(ukm.keymap_items):
            if (kmi.idname == IOPS_OT_widget_toggle.bl_idname
                    and kmi.properties.name not in names):
                ukm.keymap_items.remove(kmi)
    bpy.context.window_manager.keyconfigs.update()


def rename_toggle_kmi(old, new):
    """Carry a widget's binding across a rename (keeps the assigned key
    instead of resetting to unbound). Must patch BOTH keyconfigs: a
    user-modified copy holds its own properties snapshot, so renaming
    only the addon entry would orphan the user's binding."""
    ukm = _user_toggle_keymap()
    for km in (_toggle_keymap(), ukm):
        if km is None:
            continue
        for kmi in km.keymap_items:
            if (kmi.idname == IOPS_OT_widget_toggle.bl_idname
                    and kmi.properties.name == old):
                kmi.properties.name = new
    bpy.context.window_manager.keyconfigs.update()


def _user_toggle_keymap():
    wm = getattr(bpy.context, "window_manager", None)
    if wm is None or wm.keyconfigs.user is None:
        return None
    return wm.keyconfigs.user.keymaps.get("Window")


def find_user_toggle_kmi(name):
    """(keymap, kmi) for a widget's toggle entry in the USER keyconfig —
    the editable mirror the prefs UI draws so user rebinds persist in
    userpref.blend. Returns (None, None) when absent."""
    wm = getattr(bpy.context, "window_manager", None)
    if wm is None or wm.keyconfigs.user is None:
        return None, None
    km = wm.keyconfigs.user.keymaps.get("Window")
    if km is None:
        return None, None
    for kmi in km.keymap_items:
        if (kmi.idname == IOPS_OT_widget_toggle.bl_idname
                and kmi.properties.name == name):
            return km, kmi
    return None, None


# ----------------------------------------------------------------------
# Editor hotkeys — exist only while an edit session is active (added by
# editor.begin, removed by editor.end): zero idle cost otherwise. Over the
# edited widget / its palette they act on the EditorDoc; anywhere else the
# operator PASS_THROUGHs so Ctrl+Z / X keep their normal meaning.
# Excluded from save_hotkeys (NEVER_SAVE).
# ----------------------------------------------------------------------
class IOPS_OT_widget_editor_key(bpy.types.Operator):
    """Undo/redo/delete inside the visual widget editor"""

    bl_idname = "iops.widget_editor_key"
    bl_label = "IOPS Widget Editor Key"
    bl_options = {"INTERNAL"}

    action: EnumProperty(
        name="Action",
        items=(("UNDO", "Undo", "Undo the last widget edit"),
               ("REDO", "Redo", "Redo the last undone widget edit"),
               ("DELETE", "Delete", "Delete the selected element")),
        default="UNDO")

    @classmethod
    def poll(cls, context):
        from . import editor
        return editor.active() is not None

    @staticmethod
    def run(action):
        """Apply `action` to the active session's doc. Returns True when
        the doc changed (after_commit already called)."""
        from . import editor
        session = editor.active()
        if session is None or not editor.can_edit():
            return False         # no session, or a draft is undecided
        doc = session.doc
        if action == "UNDO":
            changed = doc.undo()
        elif action == "REDO":
            changed = doc.redo()
        elif action == "DELETE":
            changed = (doc.selection is not None
                       and doc.delete(doc.selection))
        else:
            changed = False
        if changed:
            editor.after_commit()
        return changed

    def invoke(self, context, event):
        if not (_over_session(context, event.mouse_region_x,
                              event.mouse_region_y)
                or (self.action in ("UNDO", "REDO")
                    and _over_session_sidebar(context))):
            return {"PASS_THROUGH"}
        # Over the editor the key is always consumed (even with nothing to
        # undo/delete) so it never falls through to the mesh/scene below.
        from . import editor
        if not editor.can_edit():
            self.report({"WARNING"}, editor.DRAFT_GATE_MSG)
            return {"FINISHED"}
        self.run(self.action)
        return {"FINISHED"}


# (keymap name, space_type, key group) -> hosts the editor keys.
# "3D View"/"Image" are the WINDOW region's own keymaps (all keys). The
# mode / tool keymaps below come BEFORE them in the region handler list
# and bind X/DEL to a destructive op, so DELETE is mirrored there or it
# would never reach us and the scene data under the widget would be
# deleted instead (names verified against the 5.x default keyconfig;
# "Font" mirrors DEL only — X there is text input). The "* Generic"
# keymaps also serve the sidebar (UI region): undo/redo there acts on
# the widget doc while the mouse is over the Widget Editor sidebar.
_EDITOR_KEYMAPS = (
    ("3D View", "VIEW_3D", "ALL"),
    ("Image", "IMAGE_EDITOR", "ALL"),
    ("3D View Generic", "VIEW_3D", "UNDO"),
    ("Image Generic", "IMAGE_EDITOR", "UNDO"),
    ("Object Mode", "EMPTY", "DELETE"),
    ("Mesh", "EMPTY", "DELETE"),
    ("Curve", "EMPTY", "DELETE"),
    ("Curves", "EMPTY", "DELETE"),
    ("Armature", "EMPTY", "DELETE"),
    ("Metaball", "EMPTY", "DELETE"),
    ("Grease Pencil Edit Mode", "EMPTY", "DELETE"),
    ("Particle", "EMPTY", "DELETE"),
    ("Point Cloud", "EMPTY", "DELETE"),
    ("Paint Curve", "EMPTY", "DELETE"),
    ("Mask Editing", "EMPTY", "DELETE"),
    ("3D View Tool: Measure", "VIEW_3D", "DELETE"),
    ("Font", "EMPTY", "DEL"),
)
# (action, type, ctrl, shift, key groups that include it)
_EDITOR_KEYS = (
    ("UNDO", "Z", True, False, ("ALL", "UNDO")),
    ("REDO", "Z", True, True, ("ALL", "UNDO")),
    ("DELETE", "X", False, False, ("ALL", "DELETE")),
    ("DELETE", "DEL", False, False, ("ALL", "DELETE", "DEL")),
)
_editor_kmis = []


def add_editor_kmis():
    """Add the editor hotkeys (idempotent). Called by editor.begin."""
    if _editor_kmis:
        return
    wm = getattr(bpy.context, "window_manager", None)
    kc = wm.keyconfigs.addon if wm is not None else None
    if kc is None:
        return
    for km_name, space_type, group in _EDITOR_KEYMAPS:
        km = kc.keymaps.new(km_name, space_type=space_type)
        for action, key, ctrl, shift, groups in _EDITOR_KEYS:
            if group not in groups:
                continue
            kmi = km.keymap_items.new(IOPS_OT_widget_editor_key.bl_idname,
                                      key, "PRESS", ctrl=ctrl, shift=shift)
            kmi.properties.action = action
            _editor_kmis.append((km, kmi))
    wm.keyconfigs.update()


def remove_editor_kmis():
    """Remove ONLY the entries add_editor_kmis made. Idempotent; called by
    editor.end (also on addon unregister via editor.unregister)."""
    for km, kmi in _editor_kmis:
        try:
            km.keymap_items.remove(kmi)
        except (ReferenceError, RuntimeError):
            pass
    _editor_kmis.clear()
    try:
        bpy.context.window_manager.keyconfigs.update()
    except Exception:
        pass


classes = (IOPS_OT_widget_toggle, IOPS_OT_widget_interact,
           IOPS_OT_widget_editor_key)
