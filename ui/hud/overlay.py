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
    if self.hud.handle_toggle_event(event, prefs):  # kill-switch (old API)
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
from . import text as hud_text
from .items import (HUDItem, HUDSection, HUDParam, HUDParamSection,
                    ItemState)
from .layout import (compute_origin, DragState, is_inside)


# Cursor-warp detection: Blender warps the cursor across screen edges
# during MMB navigation (jumps of hundreds of pixels in a single frame).
# Threshold must be high enough that *normal* fast mouse movement doesn't
# trip it — at 60–144Hz a flick spans 30–80 px/frame; warps are 400+ px.
_WARP_PX = 250
_WARP_PIN_SEC = 0.08


_STATE_ALPHA = {
    ItemState.ON: 1.0,
    ItemState.OFF: 1.0,
    ItemState.DISABLED: 1.0,
}
_STATE_ROLE = {
    ItemState.ON: Role.HUD_LABEL_ON,
    ItemState.OFF: Role.HUD_LABEL_OFF,
    ItemState.DISABLED: Role.HUD_LABEL_DISABLED,
}


class HUDOverlay:
    def __init__(self, operator_name: str, verbosity: str = "compact"):
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
        self._prev_mouse: tuple[int, int] | None = None
        self.verbosity: str = verbosity  # "compact" | "full"
        self.visible: bool = True
        self.params_visible: bool = True

    # --- visibility ---
    def toggle_visibility(self) -> bool:
        self.visible = not self.visible
        return self.visible

    def toggle_params_visible(self) -> bool:
        self.params_visible = not self.params_visible
        return self.params_visible

    def handle_toggle_event(self, event, prefs) -> bool:
        """Kill-switch toggle (whole HUD on/off). Default key from
        `prefs.hud_toggle_key` (default "H")."""
        if event.value != "PRESS":
            return False
        key = getattr(prefs, "hud_toggle_key", "H")
        if event.type != key:
            return False
        if event.shift or event.ctrl or event.alt or event.oskey:
            return False
        self.toggle_visibility()
        return True

    def handle_param_toggle_event(self, event, prefs) -> bool:
        """Params-only toggle (title stays visible). Default key from
        `prefs.hud_param_toggle_key` (default "SLASH")."""
        if event.value != "PRESS":
            return False
        key = getattr(prefs, "hud_param_toggle_key", "SLASH")
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

    def toggle_verbosity(self) -> str:
        self.verbosity = "full" if self.verbosity == "compact" else "compact"
        return self.verbosity

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
        if self.verbosity == "full":
            return self.sections
        out: list[HUDSection] = []
        for sec in self.sections:
            items = [it for it in sec.items if it.always_show or it.is_modified()]
            if items:
                out.append(HUDSection(sec.title, items))
        return out

    # --- measurement ---
    def _measure(self, theme, sections, param_sections, draw_params: bool):
        """Return (size_w, size_h, key_col_w, param_name_col_w).

        `key_col_w` aligns labels in HUDItem sections.
        `param_name_col_w` aligns values in HUDParam sections.
        """
        title_h = theme.text_size("title")
        row_h = theme.text_size("normal")
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
            hw, _ = hud_text.measure(line, theme=theme, size_token="title")
            max_w = max(max_w, int(hw))
            h += title_h + theme.hud.row_spacing

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
                                         size_token="normal")
                widest_key = max(widest_key, int(kw))
        key_col_w = widest_key + gap
        for sec in sections:
            rows = self._rows_for_layout(sec.items)
            for row in rows:
                row_w = 0
                for it in row:
                    lw, _ = hud_text.measure(it.label, theme=theme,
                                             size_token="normal")
                    row_w += key_col_w + int(lw)
                max_w = max(max_w, row_w)
                h += row_h + theme.hud.row_spacing

        # Param sections.
        # Measure widest param name across all visible params for alignment.
        for sec in param_sections:
            for p in sec.params:
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
                vw, _ = hud_text.measure(p.value_text(), theme=theme,
                                         size_token="normal")
                row_w = param_name_col_w + int(vw)
                max_w = max(max_w, row_w)
                h += row_h + theme.hud.row_spacing

        return max_w, h, key_col_w, param_name_col_w

    def _rows_for_layout(self, items: list[HUDItem]) -> list[list[HUDItem]]:
        """Pair items into rows: 1 col in compact, 2 cols in full."""
        if self.verbosity == "compact":
            return [[it] for it in items]
        rows: list[list[HUDItem]] = []
        half = (len(items) + 1) // 2
        left = items[:half]
        right = items[half:]
        for i in range(half):
            row = [left[i]]
            if i < len(right):
                row.append(right[i])
            rows.append(row)
        return rows

    # --- draw ---
    def draw(self, context, event=None) -> None:
        if not self.visible:
            return
        if (self._bound_region is not None
                and context.region.as_pointer() != self._bound_region):
            return
        sections = self._visible_sections() if self.params_visible else []
        param_sections = (self.param_sections
                          if self.params_visible else [])
        if (not sections and not param_sections and not self._header_lines
                and not self.title):
            return
        theme = get_theme(context)
        region = context.region
        w, h, key_col_w, param_name_col_w = self._measure(
            theme, sections, param_sections, self.params_visible)
        size = (w, h)
        self._last_size = size
        self._last_key_col_w = key_col_w
        self._last_param_name_col_w = param_name_col_w
        mouse = (0, 0)
        if event is not None:
            mouse = (event.mouse_x - region.x, event.mouse_y - region.y)
            # Warp detection: if the cursor jumped a lot since last draw,
            # Blender is probably warping it for MMB navigation. Pin briefly.
            if self._prev_mouse is not None:
                dx = mouse[0] - self._prev_mouse[0]
                dy = mouse[1] - self._prev_mouse[1]
                if abs(dx) >= _WARP_PX or abs(dy) >= _WARP_PX:
                    self.pin_for(_WARP_PIN_SEC)
            self._prev_mouse = mouse
        if self._drag.active and event is not None:
            new = self._drag.update(mouse)
            free = (int(new[0]), int(new[1]))
        else:
            free = (theme.hud.free_x, theme.hud.free_y)
        if self._pinned and self._last_origin != (0, 0):
            origin = self._last_origin
        else:
            origin = compute_origin(
                theme.hud.mode, region=region, mouse=mouse,
                content_size=size, padding=theme.hud.padding,
                offset=(theme.hud.offset_x, theme.hud.offset_y), free=free)
            self._last_origin = origin
        self._render(theme, origin, size, sections, param_sections)

    def _render(self, theme, origin, size, sections, param_sections) -> None:
        x0, y0 = origin
        _, h = size
        y = y0 + h
        title_h = theme.text_size("title")
        row_h = theme.text_size("normal")
        key_col_w = getattr(self, "_last_key_col_w", 0)
        param_name_col_w = getattr(self, "_last_param_name_col_w", 0)

        # Operator title — always visible when overlay is visible.
        if self.title:
            y -= title_h
            hud_text.draw(self.title, x0, y, theme=theme,
                          role=Role.ACTIVE_TEXT, size_token="title")
            y -= theme.hud.row_spacing

        for line in self._header_lines:
            y -= title_h
            hud_text.draw(line, x0, y, theme=theme,
                          role=Role.ACTIVE_TEXT, size_token="title")
            y -= theme.hud.row_spacing

        # For "full" two-column mode, total column block width is the
        # key column + the widest label across all visible items.
        col_w = key_col_w
        if self.verbosity == "full":
            widest_label = 0
            for sec in sections:
                for it in sec.items:
                    lw, _ = hud_text.measure(it.label, theme=theme,
                                             size_token="normal")
                    widest_label = max(widest_label, int(lw))
            col_w = key_col_w + widest_label + theme.hud.key_label_spacing

        for i, sec in enumerate(sections):
            if i > 0 or self._header_lines or self.title:
                y -= theme.hud.section_spacing
            if sec.title:
                y -= title_h
                hud_text.draw(sec.title, x0, y, theme=theme,
                              role=Role.ACTIVE_TEXT, size_token="title")
                y -= theme.hud.row_spacing
            for row in self._rows_for_layout(sec.items):
                y -= row_h
                for col_idx, it in enumerate(row):
                    col_x = x0 + col_idx * col_w
                    hud_text.draw(it.key, col_x, y, theme=theme,
                                  role=Role.HUD_KEY, size_token="normal")
                    label_role = _STATE_ROLE[it.state]
                    label_alpha = _STATE_ALPHA[it.state]
                    hud_text.draw(it.label, col_x + key_col_w, y, theme=theme,
                                  role=label_role, size_token="normal",
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
                              role=Role.ACTIVE_TEXT, size_token="title")
                y -= theme.hud.row_spacing
            for p in sec.params:
                y -= row_h
                active = p.is_active()
                name_role = Role.HUD_LABEL_ON if active else Role.HUD_LABEL_DISABLED
                value_role = Role.HUD_KEY if active else Role.HUD_LABEL_DISABLED
                hud_text.draw(p.name + ":", x0, y, theme=theme,
                              role=name_role, size_token="normal")
                hud_text.draw(p.value_text(), x0 + param_name_col_w, y,
                              theme=theme, role=value_role,
                              size_token="normal")
                y -= theme.hud.row_spacing

    # --- drag (free-mode) ---
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
