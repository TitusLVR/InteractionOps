"""HUDOverlay — composes sections and items, computes layout, draws via blf.

State color rules (from spec):
- ItemState.ON       → primary
- ItemState.OFF      → secondary @ alpha * 0.7
- ItemState.DISABLED → secondary @ alpha * 0.35

Key glyph is always rendered in `primary` for legibility.
"""
from __future__ import annotations
from typing import Iterable

from ..draw.theme import Role, get_theme
from . import text as hud_text
from .items import HUDItem, HUDSection, ItemState
from .layout import (compute_origin, DragState, is_inside)


_STATE_ALPHA = {
    ItemState.ON: 1.0,
    ItemState.OFF: 0.7,
    ItemState.DISABLED: 0.35,
}
_STATE_ROLE = {
    ItemState.ON: Role.PRIMARY,
    ItemState.OFF: Role.SECONDARY,
    ItemState.DISABLED: Role.SECONDARY,
}


class HUDOverlay:
    def __init__(self, operator_name: str):
        self.operator_name = operator_name
        self.sections: list[HUDSection] = []
        self._items_by_key: dict[str, HUDItem] = {}
        self._drag = DragState()
        self._last_origin = (0, 0)
        self._last_size = (0, 0)

    def add_section(self, section: HUDSection) -> None:
        self.sections.append(section)
        for it in section.items:
            self._items_by_key[it.key] = it

    def set_state(self, key: str, state: ItemState | str) -> None:
        if key not in self._items_by_key:
            return
        if isinstance(state, str):
            state = ItemState(state)
        self._items_by_key[key].state = state

    def _measure(self, theme) -> tuple[int, int]:
        max_w = 0
        h = 0
        title_h = theme.text_size("title")
        row_h = theme.text_size("normal")
        for i, sec in enumerate(self.sections):
            if i > 0:
                h += theme.hud.section_spacing
            if sec.title:
                tw, _ = hud_text.measure(sec.title, theme=theme,
                                         size_token="title")
                max_w = max(max_w, int(tw))
                h += title_h + theme.hud.row_spacing
            for it in sec.items:
                row = f"{it.key}    {it.label}"
                rw, _ = hud_text.measure(row, theme=theme,
                                         size_token="normal")
                max_w = max(max_w, int(rw))
                h += row_h + theme.hud.row_spacing
        return max_w, h

    def draw(self, context, event=None) -> None:
        if not self.sections:
            return
        theme = get_theme(context)
        region = context.region
        size = self._measure(theme)
        self._last_size = size
        mouse = (0, 0)
        if event is not None:
            mouse = (event.mouse_region_x, event.mouse_region_y)
        if self._drag.active and event is not None:
            new = self._drag.update(mouse)
            free = (int(new[0]), int(new[1]))
        else:
            free = (theme.hud.free_x, theme.hud.free_y)
        origin = compute_origin(
            theme.hud.mode, region=region, mouse=mouse,
            content_size=size, padding=theme.hud.padding,
            offset=(theme.hud.offset_x, theme.hud.offset_y), free=free)
        self._last_origin = origin
        self._render(theme, origin, size)

    def _render(self, theme, origin, size) -> None:
        x0, y0 = origin
        _, h = size
        y = y0 + h
        title_h = theme.text_size("title")
        row_h = theme.text_size("normal")
        key_col_w = theme.hud.key_column_width
        for i, sec in enumerate(self.sections):
            if i > 0:
                y -= theme.hud.section_spacing
            if sec.title:
                y -= title_h
                hud_text.draw(sec.title, x0, y, theme=theme,
                              role=Role.PRIMARY, size_token="title")
                y -= theme.hud.row_spacing
            for it in sec.items:
                y -= row_h
                hud_text.draw(it.key, x0, y, theme=theme,
                              role=Role.PRIMARY, size_token="normal")
                label_role = _STATE_ROLE[it.state]
                label_alpha = _STATE_ALPHA[it.state]
                hud_text.draw(it.label, x0 + key_col_w, y, theme=theme,
                              role=label_role, size_token="normal",
                              alpha_mul=label_alpha)
                y -= theme.hud.row_spacing

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
