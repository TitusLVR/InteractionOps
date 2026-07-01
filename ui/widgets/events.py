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
- titlebar drag moves the panel, position persists on release.

Controls cache plain floats/bools only; setters/getters re-acquire bmesh
per call inside the widget's value adapters — nothing bmesh-shaped is
ever stored on the operator.
"""
import bpy
from bpy.props import BoolProperty, StringProperty

from . import state
from .controls import TextEditState, dropdown_index_at


def _tag_redraw(context):
    if context.area is not None:
        context.area.tag_redraw()


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
        widget = state.widget_under_mouse(context.area, mx, my)
        if widget is None:
            return {"PASS_THROUGH"}

        hit = widget.panel.hit_test(mx, my)
        if hit is None:
            return {"PASS_THROUGH"}
        kind, where = hit

        self._widget = widget          # registry instance — plain python
        self._control = None
        self._mode = "swallow"         # consume press+release, no action
        widget._press_cell = None      # clear any stale pressed highlight
        widget._editing = None         # (where, TextEditState) while typing
        widget._dropdown = None        # (where, items, hover) while open

        if kind == "close":
            state.hide_widget(widget.name)
            return {"FINISHED"}

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
            # In-overlay item list: opens below the field, click/drag-release
            # to pick (no popup). Empty list (no items, no labels) -> swallow.
            items = control.items(context)
            if not items:
                return None
            cur, _ = control.get(context)
            hover = next((i for i, (ident, _d) in enumerate(items)
                          if ident == cur), 0)
            self._control = control
            self._dd_items = items
            self._dd_field = self._rect
            self._mode = "dropdown_open"
            self._widget._dropdown = (self._where, items, hover)
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
    def _dd_index_at(self, mx, my):
        from . import render
        r = self._dd_field
        return dropdown_index_at(my, r.x, r.y, r.w, render.DROPDOWN_ITEM_H,
                                 len(self._dd_items))

    def _modal_dropdown(self, context, event):
        mx, my = event.mouse_region_x, event.mouse_region_y
        et, ev = event.type, event.value

        if et == "ESC" and ev == "PRESS":
            return self._close_dropdown(context)

        if et in {"MOUSEMOVE", "INBETWEEN_MOUSEMOVE"}:
            idx = self._dd_index_at(mx, my)
            where, items, _hover = self._widget._dropdown
            self._widget._dropdown = (where, items, idx)
            _tag_redraw(context)
            return {"RUNNING_MODAL"}

        if et == "LEFTMOUSE":
            idx = self._dd_index_at(mx, my)
            if idx >= 0:
                # Pick on either the opening drag-release or a later click.
                self._control.write(context, self._dd_items[idx][0])
                self._widget.mark_dirty()
                self._undo_push()
                return self._close_dropdown(context)
            if ev == "PRESS" and not self._rect.contains(mx, my):
                return self._close_dropdown(context)   # click-away cancels
            return {"RUNNING_MODAL"}                   # opening release etc.

        return {"RUNNING_MODAL"}

    def _close_dropdown(self, context):
        self._widget._dropdown = None
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


classes = (IOPS_OT_widget_toggle, IOPS_OT_widget_interact)
