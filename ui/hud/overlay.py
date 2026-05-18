"""HUDOverlay — composes sections and items, computes layout, draws via blf.

Cursor-follow positioning auto-freezes during viewport navigation:
- explicit pin via pin_for(seconds) (used by operators for MMB/wheel)
- warp detection: any single-frame mouse jump >= WARP_PX triggers a brief
  pin so the HUD doesn't chase Blender's cursor-warp during MMB pan/rotate.


State color rules (from spec):
- ItemState.ON       → primary
- ItemState.OFF      → secondary @ alpha * 0.7
- ItemState.DISABLED → secondary @ alpha * 0.35

Key glyph is always rendered in `primary` for legibility.

Verbosity modes:
- "compact": only items with state != default_state, plus items flagged always_show.
- "full": every item, laid out in two columns.

A single optional `header` line (e.g. live distance info) renders above the
sections, in `primary` at `title` size.

Multi-viewport safety: draw_handlers fire for every 3D viewport. Bind the
overlay to the region where the operator was invoked via `bind_region()`;
the overlay no-ops in any other region.
"""
from __future__ import annotations
import time
from typing import Iterable

from ..draw.theme import Role, get_theme
from . import text as hud_text
from .items import HUDItem, HUDSection, ItemState
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
        self.sections: list[HUDSection] = []
        self._items_by_key: dict[str, HUDItem] = {}
        self._drag = DragState()
        self._last_origin = (0, 0)
        self._last_size = (0, 0)
        self._bound_region = None
        self._header_lines: list[str] = []
        self._pin_until: float = 0.0
        self._prev_mouse: tuple[int, int] | None = None
        self.verbosity: str = verbosity  # "compact" | "full"

    # --- setup ---
    def add_section(self, section: HUDSection) -> None:
        self.sections.append(section)
        for it in section.items:
            self._items_by_key[it.key] = it

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
    def _measure(self, theme, sections) -> tuple[int, int]:
        title_h = theme.text_size("title")
        row_h = theme.text_size("normal")
        h = 0
        max_w = 0
        for line in self._header_lines:
            hw, _ = hud_text.measure(line, theme=theme, size_token="title")
            max_w = max(max_w, int(hw))
            h += title_h + theme.hud.row_spacing
        for i, sec in enumerate(sections):
            if i > 0 or self._header_lines:
                h += theme.hud.section_spacing
            if sec.title:
                tw, _ = hud_text.measure(sec.title, theme=theme,
                                         size_token="title")
                max_w = max(max_w, int(tw))
                h += title_h + theme.hud.row_spacing
            rows = self._rows_for_layout(sec.items)
            for row in rows:
                for it in row:
                    label_w, _ = hud_text.measure(
                        f"{it.key}    {it.label}",
                        theme=theme, size_token="normal")
                    max_w = max(max_w, int(label_w) * len(row))
                h += row_h + theme.hud.row_spacing
        return max_w, h

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
        if (self._bound_region is not None
                and context.region.as_pointer() != self._bound_region):
            return
        sections = self._visible_sections()
        if not sections and not self._header_lines:
            return
        theme = get_theme(context)
        region = context.region
        size = self._measure(theme, sections)
        self._last_size = size
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
        self._render(theme, origin, size, sections)

    def _render(self, theme, origin, size, sections) -> None:
        x0, y0 = origin
        _, h = size
        y = y0 + h
        title_h = theme.text_size("title")
        row_h = theme.text_size("normal")
        key_col_w = theme.hud.key_column_width
        col_gap = max(theme.hud.key_column_width, 24)

        for line in self._header_lines:
            y -= title_h
            hud_text.draw(line, x0, y, theme=theme,
                          role=Role.ACTIVE_TEXT, size_token="title")
            y -= theme.hud.row_spacing

        # estimate per-column block width (only matters for "full" 2-col mode)
        col_w = 0
        if self.verbosity == "full":
            for sec in sections:
                for it in sec.items:
                    w, _ = hud_text.measure(f"{it.key}    {it.label}",
                                            theme=theme, size_token="normal")
                    col_w = max(col_w, int(w))
            col_w += col_gap

        for i, sec in enumerate(sections):
            if i > 0 or self._header_lines:
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
