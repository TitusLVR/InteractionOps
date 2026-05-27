"""HUDOverlay — cursor-following parameter dashboard.

Two content layers coexist:

- `title` (str) + `_header_lines` (list[str]) — always rendered when the
  overlay is visible, regardless of `params_visible`. The operator name /
  live distance info / etc. lives here.
- Sections of `HUDItem` (legacy hotkey list) AND `HUDParamSection` of
  `HUDParam` (live operator-parameter rows). Both are hidden by `/` (the
  HUD-param toggle key) but the title stays.

Operator wiring:

    self.hud = HUDOverlay("loop_cut")
    self.hud.title = "Loop cut"
    self.hud.add_param(HUDParam("Cuts", lambda: self.cuts, "int"))
    ...

    # in modal():
    if self.hud.handle_param_toggle_event(event, prefs):
        return {"RUNNING_MODAL"}

The legacy `HUDSection`/`HUDItem` API still works — used by operators that
have not yet migrated to a separate HelpOverlay.

Cursor-follow positioning auto-freezes during viewport navigation:
- explicit pin via pin_for(seconds) (used by operators for MMB/wheel)
- warp detection: any single-frame mouse jump >= WARP_PX triggers a brief
  pin so the HUD doesn't chase Blender's cursor-warp during MMB pan/rotate.

State color rules (from spec):
- ItemState.ON       → primary
- ItemState.OFF      → secondary @ alpha * 0.7
- ItemState.DISABLED → secondary @ alpha * 0.35

Key glyph is always rendered in `primary` for legibility.

Verbosity modes (applies to HUDItem sections only — HUDParam sections
always render every param):
- "compact": only items with state != default_state, plus items flagged
  always_show.
- "full": every item, laid out in two columns.

Multi-viewport safety: draw_handlers fire for every 3D viewport. Bind the
overlay to the region where the operator was invoked via `bind_region()`;
the overlay no-ops in any other region.
"""
from __future__ import annotations
import time

from ..draw.theme import Role, get_theme
from ..draw import primitives
from ..draw.state import draw_scope
from . import text as hud_text
from .items import (HUDItem, HUDSection, HUDParam, HUDParamSection,
                    ItemState)
from .layout import (compute_origin, DragState, is_inside,
                     area_for_region, region_side_insets)


# When the viewport navigates (view3d.rotate / view3d.dolly / view3d.move
# / wheel-zoom / numpad / etc.) Blender warps the cursor — locks it to
# the region centre or wraps it across screen edges — which would
# otherwise yank a cursor-following HUD all over the screen. We can't
# reliably detect those modals from our own (Blender consumes MMB
# PRESS/RELEASE before our handler sees them), so instead we watch the
# region's view_matrix and freeze the HUD whenever it changes between
# successive draws — covers every form of view nav including keyboard /
# wheel / scripted.
def _view_matrix_fingerprint(region_data) -> tuple | None:
    """Cheap fingerprint of the current view matrix. None when there's
    no region_data (e.g. POST_PIXEL in a non-3D space)."""
    if region_data is None:
        return None
    m = region_data.view_matrix
    # 16 floats is enough; rounding keeps tiny FP wobble from triggering
    # the freeze when the view is actually static.
    return tuple(round(float(v), 5)
                 for row in m for v in row)


_STATE_ALPHA = {
    ItemState.ON: 1.0,
    ItemState.OFF: 1.0,
    ItemState.DISABLED: 1.0,
}
_STATE_ROLE = {
    ItemState.ON: Role.HUD_LABEL,
    ItemState.OFF: Role.HUD_LABEL_INACTIVE,
    ItemState.DISABLED: Role.HUD_LABEL_INACTIVE,
}


class HUDOverlay:
    def __init__(self, operator_name: str, verbosity: str | None = None):
        # `verbosity` kwarg kept for back-compat with old callers — ignored.
        self.operator_name = operator_name
        self.title: str | None = None
        self.sections: list[HUDSection] = []
        self.param_sections: list[HUDParamSection] = []
        self._items_by_key: dict[str, HUDItem] = {}
        self._drag = DragState()
        self._last_origin = (0, 0)
        self._last_size = (0, 0)
        self._bound_region = None
        self._header_lines: list[str] = []
        self._pin_until: float = 0.0
        # Last frame's view-matrix fingerprint — when this frame's
        # fingerprint differs the viewport is navigating and the HUD
        # origin is held instead of recomputed.
        self._last_view_fp: tuple | None = None
        # Smoothed display origin — only diverges from the ideal origin
        # during the recovery glide after a nav-freeze. Outside recovery
        # the HUD tracks the cursor exactly, so normal mouse movement
        # is never lagged.
        self._smooth_origin: tuple[float, float] | None = None
        # True between the end of a nav-freeze and the moment the smooth
        # origin actually reaches the live target — the only window
        # where `hud_smoothing` applies.
        self._recovering: bool = False
        self._was_nav_frozen: bool = False
        self.visible: bool = True
        self.params_visible: bool = True
        # Optional per-overlay positioning override. When set, takes
        # precedence over theme.hud.mode — used by callers (e.g. theme
        # preview launched from prefs) where cursor-follow doesn't work
        # because the modal event coordinates are in a different window
        # than the bound viewport region.
        self.mode_override: str | None = None

    # --- visibility ---
    def toggle_visibility(self) -> bool:
        self.visible = not self.visible
        return self.visible

    def toggle_params_visible(self) -> bool:
        self.params_visible = not self.params_visible
        return self.params_visible

    def handle_param_toggle_event(self, event, prefs) -> bool:
        """Params-only toggle (title stays visible). Key comes from the
        `iops.ui_hud_params_toggle` keymap item (default "SLASH"),
        configurable in the addon's Keymaps tab."""
        if event.value != "PRESS":
            return False
        from ...utils.functions import get_ui_toggle_key
        key = get_ui_toggle_key("iops.ui_hud_params_toggle", "SLASH")
        if event.type != key:
            return False
        if event.shift or event.ctrl or event.alt or event.oskey:
            return False
        self.toggle_params_visible()
        return True

    # --- setup ---
    def add_section(self, section: HUDSection) -> None:
        self.sections.append(section)
        for it in section.items:
            self._items_by_key[it.key] = it

    def add_param(self, param: HUDParam, *, title: str = "") -> None:
        """Append a HUDParam. If `title` is given and no matching section
        exists, create one; otherwise append to the last param section
        (creating an untitled one on demand)."""
        if title:
            for sec in self.param_sections:
                if sec.title == title:
                    sec.params.append(param)
                    return
            self.param_sections.append(HUDParamSection(title, [param]))
            return
        if not self.param_sections:
            self.param_sections.append(HUDParamSection("", []))
        self.param_sections[-1].params.append(param)

    def add_param_section(self, section: HUDParamSection) -> None:
        self.param_sections.append(section)

    def bind_region(self, region) -> None:
        """Restrict drawing to one region (the one the operator was invoked in).

        We store the C-pointer because Blender wraps the same region struct in
        a fresh Python object on every access, so identity (`is`) checks fail.
        """
        self._bound_region = region.as_pointer() if region is not None else None

    def _find_bound_region(self):
        """Look up the live region object matching `_bound_region` pointer.
        Always finds the 3D viewport we bound at invoke-time — never the
        prefs region — so measurements stay correct even if `context.region`
        points elsewhere."""
        if self._bound_region is None:
            return None
        import bpy
        for win in bpy.context.window_manager.windows:
            for area in win.screen.areas:
                if area.type != "VIEW_3D":
                    continue
                for rgn in area.regions:
                    if rgn.as_pointer() == self._bound_region:
                        return rgn
        return None

    def set_state(self, key: str, state: ItemState | str) -> None:
        if key not in self._items_by_key:
            return
        if isinstance(state, str):
            state = ItemState(state)
        self._items_by_key[key].state = state

    def set_header(self, *lines: str | None) -> None:
        """Set 0+ header lines rendered above the section list, in primary
        at title size. Falsy entries are skipped."""
        self._header_lines = [ln for ln in lines if ln]

    def pin_for(self, seconds: float) -> None:
        """Freeze the HUD origin for at least `seconds` more from now.
        Calls are rolling: each call extends the pin window if it lands
        further in the future than the current deadline."""
        new_deadline = time.perf_counter() + max(0.0, seconds)
        if new_deadline > self._pin_until:
            self._pin_until = new_deadline

    @property
    def _pinned(self) -> bool:
        return time.perf_counter() < self._pin_until

    # --- visible item selection ---
    def _visible_sections(self) -> list[HUDSection]:
        # Compact-only: only items in non-default state, plus always_show.
        out: list[HUDSection] = []
        for sec in self.sections:
            items = [it for it in sec.items if it.always_show or it.is_modified()]
            if items:
                out.append(HUDSection(sec.title, items))
        return out

    # --- measurement ---
    def _measure(self, theme, sections, param_sections, draw_params: bool):
        # Single row pitch from max(key, label) — see _render.
        """Return (size_w, size_h, key_col_w, param_name_col_w).

        `key_col_w` aligns labels in HUDItem sections.
        `param_name_col_w` aligns values in HUDParam sections.
        """
        title_h = theme.text_size("hud_header")
        row_h = max(theme.text_size("hud_key"),
                    theme.text_size("hud_label"))
        gap = theme.hud.key_label_spacing
        h = 0
        max_w = 0
        widest_key = 0
        widest_param_name = 0

        # Title row (operator name).
        if self.title:
            tw, _ = hud_text.measure(self.title, theme=theme, size_token="title")
            max_w = max(max_w, int(tw))
            h += title_h + theme.hud.row_spacing

        for line in self._header_lines:
            hw, _ = hud_text.measure(line, theme=theme, size_token="hud_label")
            max_w = max(max_w, int(hw))
            h += row_h + theme.hud.row_spacing

        if not draw_params:
            return max_w, h, 0, 0

        # Sections (HUDItem).
        for i, sec in enumerate(sections):
            if i > 0 or self._header_lines or self.title:
                h += theme.hud.section_spacing
            if sec.title:
                tw, _ = hud_text.measure(sec.title, theme=theme,
                                         size_token="title")
                max_w = max(max_w, int(tw))
                h += title_h + theme.hud.row_spacing
            for it in sec.items:
                kw, _ = hud_text.measure(it.key, theme=theme,
                                         size_token="hud_key")
                widest_key = max(widest_key, int(kw))
        key_col_w = widest_key + gap
        for sec in sections:
            rows = self._rows_for_layout(sec.items)
            for row in rows:
                row_w = 0
                for it in row:
                    lw, _ = hud_text.measure(it.label, theme=theme,
                                             size_token="hud_label")
                    row_w += key_col_w + int(lw)
                max_w = max(max_w, row_w)
                h += row_h + theme.hud.row_spacing

        # Param sections.
        # Measure widest param name across all visible params for alignment.
        for sec in param_sections:
            for p in sec.params:
                if not p.is_visible():
                    continue
                nw, _ = hud_text.measure(p.name + ":", theme=theme,
                                         size_token="normal")
                widest_param_name = max(widest_param_name, int(nw))
        param_name_col_w = widest_param_name + gap

        for i, sec in enumerate(param_sections):
            if (i > 0 or self._header_lines or self.title
                    or sections):
                h += theme.hud.section_spacing
            if sec.title:
                tw, _ = hud_text.measure(sec.title, theme=theme,
                                         size_token="title")
                max_w = max(max_w, int(tw))
                h += title_h + theme.hud.row_spacing
            for p in sec.params:
                if not p.is_visible():
                    continue
                vw, _ = hud_text.measure(p.value_text(), theme=theme,
                                         size_token="normal")
                row_w = param_name_col_w + int(vw)
                max_w = max(max_w, row_w)
                h += row_h + theme.hud.row_spacing

        return max_w, h, key_col_w, param_name_col_w

    def _rows_for_layout(self, items: list[HUDItem]) -> list[list[HUDItem]]:
        return [[it] for it in items]

    # --- draw ---
    def draw(self, context, event=None) -> None:
        if not self.visible:
            return
        # Only draw in the region we were bound to. When invoked from the
        # prefs popup, `context.region` can be None or point at the prefs
        # region during draw — so do the gate by comparing pointers.
        if self._bound_region is not None:
            cur = getattr(context, "region", None)
            if cur is None or cur.as_pointer() != self._bound_region:
                return
        sections = self._visible_sections() if self.params_visible else []
        param_sections = (self.param_sections
                          if self.params_visible else [])
        if (not sections and not param_sections and not self._header_lines
                and not self.title):
            return
        theme = get_theme(context)
        # Use the live bound 3D-viewport region for measurements (its width
        # and height — never the prefs region's). Falls back to context if
        # not bound.
        region = self._find_bound_region() or context.region
        if region is None:
            return
        w, h, key_col_w, param_name_col_w = self._measure(
            theme, sections, param_sections, self.params_visible)
        size = (w, h)
        self._last_size = size
        self._last_key_col_w = key_col_w
        self._last_param_name_col_w = param_name_col_w
        mouse = (0, 0)
        if event is not None:
            mouse = (event.mouse_x - region.x, event.mouse_y - region.y)
        # View-matrix change detection. The fingerprint changes any time
        # the viewport is being navigated; we freeze only while the
        # matrix is actively differing between successive draws — the
        # moment it settles, the HUD picks up the cursor again.
        fp = _view_matrix_fingerprint(getattr(context, "region_data", None))
        nav_frozen = (fp is not None and self._last_view_fp is not None
                      and fp != self._last_view_fp)
        if fp is not None:
            self._last_view_fp = fp
        if self._drag.active and event is not None:
            new = self._drag.update(mouse)
            free = (int(new[0]), int(new[1]))
        else:
            free = (theme.hud.free_x, theme.hud.free_y)
        held = ((self._pinned or nav_frozen)
                and self._last_origin != (0, 0))
        if held:
            # Held in place during nav / external pins. Snap smooth_origin
            # to the held position so when the freeze ends we start the
            # glide from exactly where the HUD was, not from a stale lerp.
            target = self._last_origin
            self._smooth_origin = (float(target[0]), float(target[1]))
            origin = target
            self._recovering = False
        else:
            mode = self.mode_override or theme.hud.mode
            insets = region_side_insets(area_for_region(region))
            target = compute_origin(
                mode, region=region, mouse=mouse,
                content_size=size, padding=theme.hud.padding,
                offset=(theme.hud.offset_x, theme.hud.offset_y),
                anchor_offset=(theme.hud.anchor_offset_x,
                               theme.hud.anchor_offset_y),
                free=free, side_insets=insets)
            # Freeze just ended → enter recovery glide. Smooth_origin is
            # already pinned to the pre-freeze origin from the held
            # branch above, so the lerp interpolates from there to the
            # live target.
            if self._was_nav_frozen and not nav_frozen:
                self._recovering = True
            if self._smooth_origin is None or not self._recovering:
                # Normal cursor-follow: no smoothing, snap exactly. This
                # makes mouse movement instant — `hud_smoothing` only
                # affects the post-freeze return.
                sx, sy = float(target[0]), float(target[1])
                self._recovering = False
            else:
                alpha = max(0.0, min(1.0, 1.0 - theme.hud.smoothing))
                if alpha >= 1.0:
                    sx, sy = float(target[0]), float(target[1])
                    self._recovering = False
                else:
                    sx = self._smooth_origin[0] + (target[0] - self._smooth_origin[0]) * alpha
                    sy = self._smooth_origin[1] + (target[1] - self._smooth_origin[1]) * alpha
                    if abs(target[0] - sx) < 0.5 and abs(target[1] - sy) < 0.5:
                        sx, sy = float(target[0]), float(target[1])
                        self._recovering = False
            self._smooth_origin = (sx, sy)
            origin = (int(sx), int(sy))
            self._last_origin = origin
        self._was_nav_frozen = nav_frozen
        self._render(theme, origin, size, sections, param_sections)

    def _render(self, theme, origin, size, sections, param_sections) -> None:
        x0, y0 = origin
        w, h = size
        if theme.hud.bg_enabled and w > 0 and h > 0:
            pad = theme.hud.bg_padding
            with draw_scope(blend="ALPHA"):
                primitives.rect_2d(x0 - pad, y0 - pad,
                                   w + 2 * pad, h + 2 * pad,
                                   color=theme.hud.bg_color, theme=theme)
        y = y0 + h
        # Header rows use the Header size; body rows track max(Key, Label).
        title_h = theme.text_size("hud_header")
        row_h = max(theme.text_size("hud_key"),
                    theme.text_size("hud_label"))
        key_col_w = getattr(self, "_last_key_col_w", 0)
        param_name_col_w = getattr(self, "_last_param_name_col_w", 0)

        # Operator title — always visible when overlay is visible.
        if self.title:
            y -= title_h
            hud_text.draw(self.title, x0, y, theme=theme,
                          role=Role.HUD_HEADER, size_token="hud_header")
            y -= theme.hud.row_spacing

        # Header lines are live state ("Distance: 1.23m"). Split on the
        # first colon so the label half reads as neutral text and the
        # value half pops in the Active Value color. Lines without a
        # colon render entirely as Label.
        for line in self._header_lines:
            y -= row_h
            label_part, sep, value_part = line.partition(":")
            if sep and value_part:
                lbl = label_part + sep
                hud_text.draw(lbl, x0, y, theme=theme,
                              role=Role.HUD_LABEL, size_token="hud_label")
                lw, _ = hud_text.measure(lbl, theme=theme,
                                         size_token="hud_label")
                hud_text.draw(value_part, x0 + int(lw), y, theme=theme,
                              role=Role.HUD_ACTIVE_VALUE,
                              size_token="hud_label")
            else:
                hud_text.draw(line, x0, y, theme=theme,
                              role=Role.HUD_LABEL, size_token="hud_label")
            y -= theme.hud.row_spacing

        col_w = key_col_w

        for i, sec in enumerate(sections):
            if i > 0 or self._header_lines or self.title:
                y -= theme.hud.section_spacing
            if sec.title:
                y -= title_h
                hud_text.draw(sec.title, x0, y, theme=theme,
                              role=Role.HUD_HEADER, size_token="hud_header")
                y -= theme.hud.row_spacing
            for row in self._rows_for_layout(sec.items):
                y -= row_h
                for col_idx, it in enumerate(row):
                    col_x = x0 + col_idx * col_w
                    hud_text.draw(it.key, col_x, y, theme=theme,
                                  role=Role.HUD_KEY, size_token="hud_key")
                    label_role = _STATE_ROLE[it.state]
                    label_alpha = _STATE_ALPHA[it.state]
                    hud_text.draw(it.label, col_x + key_col_w, y, theme=theme,
                                  role=label_role, size_token="hud_label",
                                  alpha_mul=label_alpha)
                y -= theme.hud.row_spacing

        # Param sections.
        prev_block = bool(self.title or self._header_lines or sections)
        for i, sec in enumerate(param_sections):
            if i > 0 or prev_block:
                y -= theme.hud.section_spacing
            if sec.title:
                y -= title_h
                hud_text.draw(sec.title, x0, y, theme=theme,
                              role=Role.HUD_HEADER, size_token="hud_header")
                y -= theme.hud.row_spacing
            for p in sec.params:
                if not p.is_visible():
                    continue
                y -= row_h
                active = p.is_active()
                name_role = Role.HUD_LABEL if active else Role.HUD_LABEL_INACTIVE
                value_role = Role.HUD_ACTIVE_VALUE if active else Role.HUD_LABEL_INACTIVE
                hud_text.draw(p.name + ":", x0, y, theme=theme,
                              role=name_role, size_token="normal")
                hud_text.draw(p.value_text(), x0 + param_name_col_w, y,
                              theme=theme, role=value_role,
                              size_token="normal")
                y -= theme.hud.row_spacing

    # --- drag (Shift+Ctrl+Alt+LMB → switch to Free + Position X/Y) ---
    def handle_drag_event(self, context, event, theme_prefs) -> bool:
        """Drag the HUD around with Shift+Ctrl+Alt + LMB. Cursor-mode is
        switched to Free at drag start so the HUD stops chasing the
        mouse. The new position is written into Position X/Y on every
        move (and confirmed on release). Returns True if the event was
        consumed."""
        all_mods = bool(event.shift and event.ctrl and event.alt)
        region = self._find_bound_region() or context.region
        if region is None:
            return False
        mxy = (event.mouse_x - region.x, event.mouse_y - region.y)
        if (all_mods and event.type == 'LEFTMOUSE'
                and event.value == 'PRESS'
                and not self._drag.active):
            # Anchor at mouse so HUD jumps to the click point. Switch to
            # Free immediately so the cursor-follow path stops fighting
            # the drag updates this frame.
            target_origin = (mxy[0], mxy[1] - max(1, self._last_size[1]))
            self._last_origin = target_origin
            self._drag.begin(mxy, target_origin)
            try:
                theme_prefs.hud_mode = "free"
                theme_prefs.hud_free_x = int(target_origin[0])
                theme_prefs.hud_free_y = int(target_origin[1])
            except AttributeError:
                pass
            return True
        if self._drag.active:
            if event.type == 'MOUSEMOVE':
                new = self._drag.update(mxy)
                try:
                    theme_prefs.hud_free_x = int(new[0])
                    theme_prefs.hud_free_y = int(new[1])
                except AttributeError:
                    pass
                return True
            if event.type == 'LEFTMOUSE' and event.value == 'RELEASE':
                self._drag.end()
                try:
                    theme_prefs.hud_mode = "free"
                    theme_prefs.hud_free_x = int(self._last_origin[0])
                    theme_prefs.hud_free_y = int(self._last_origin[1])
                except AttributeError:
                    pass
                return True
        return False

    # --- legacy drag entry points (kept for compatibility) ---
    def try_begin_drag(self, mouse_xy) -> bool:
        if is_inside(mouse_xy[0], mouse_xy[1],
                     self._last_origin, self._last_size):
            self._drag.begin(mouse_xy, self._last_origin)
            return True
        return False

    def end_drag(self, context) -> None:
        if not self._drag.active:
            return
        self._drag.end()
        try:
            prefs = context.preferences.addons["InteractionOps"].preferences
            prefs.iops_theme.hud_free_x = int(self._last_origin[0])
            prefs.iops_theme.hud_free_y = int(self._last_origin[1])
        except (KeyError, AttributeError):
            pass
