"""HelpOverlay — corner-anchored hotkey legend with collapse/animation.

Pinned to a configurable screen corner with offset. Two states:

- expanded   → renders the full section/item list.
- collapsed  → renders just `prefs.help_hint_text` (default "Press H for help").

Toggle key: `prefs.help_toggle_key` (default "H"). Animation between
states: `prefs.help_anim_preset` ∈ {none, fade, slide-fade} over
`prefs.help_anim_duration` seconds.

Animation runs off the operator's per-frame `tag_redraw()` — no timer.
Operators already redraw every frame; if one ever stops, the animation
stops mid-frame but the overlay still ends up in its target state on the
next event.
"""
from __future__ import annotations
import time

from ..draw.theme import Role, get_theme
from . import text as hud_text
from .items import HUDItem, HUDSection, ItemState


_STATE_ROLE = {
    ItemState.ON: Role.HUD_LABEL_ON,
    ItemState.OFF: Role.HUD_LABEL_OFF,
    ItemState.DISABLED: Role.HUD_LABEL_DISABLED,
}


def _ease_out(t: float) -> float:
    # cubic ease-out — fast start, soft landing
    t = max(0.0, min(1.0, t))
    return 1.0 - (1.0 - t) ** 3


class HelpOverlay:
    def __init__(self, operator_name: str):
        self.operator_name = operator_name
        self.sections: list[HUDSection] = []
        self.visible: bool = True
        self.expanded: bool = True
        # Animation: alpha 0..1 + horizontal slide offset (px). Updated on
        # every draw based on transition timestamps.
        self._anim_from_expanded: bool = True
        self._anim_to_expanded: bool = True
        self._anim_start: float = 0.0
        self._bound_region = None

    # --- setup ---
    def add_section(self, section: HUDSection) -> None:
        self.sections.append(section)

    def bind_region(self, region) -> None:
        self._bound_region = region.as_pointer() if region is not None else None

    # --- visibility / toggle ---
    def toggle_expanded(self, now: float | None = None) -> bool:
        now = now if now is not None else time.perf_counter()
        if self._anim_to_expanded != self.expanded:
            # mid-flight toggle — restart from current target
            pass
        self._anim_from_expanded = self.expanded
        self.expanded = not self.expanded
        self._anim_to_expanded = self.expanded
        self._anim_start = now
        return self.expanded

    def handle_toggle_event(self, event, prefs) -> bool:
        if event.value != "PRESS":
            return False
        key = getattr(prefs, "help_toggle_key", "H")
        if event.type != key:
            return False
        if event.shift or event.ctrl or event.alt or event.oskey:
            return False
        self.toggle_expanded()
        return True

    # --- animation ---
    def _anim_progress(self, theme, prefs) -> float:
        preset = getattr(prefs, "help_anim_preset", "fade")
        if preset == "none":
            return 1.0
        dur = max(0.001, float(getattr(prefs, "help_anim_duration", 0.18)))
        elapsed = time.perf_counter() - self._anim_start
        return _ease_out(elapsed / dur)

    # --- corner layout ---
    @staticmethod
    def _corner_origin(corner: str, region, size, offset_x, offset_y,
                       slide_dx: int):
        cw, ch = size
        rw, rh = region.width, region.height
        if corner == "top_left":
            return (offset_x + slide_dx, rh - offset_y - ch)
        if corner == "top_right":
            return (rw - cw - offset_x - slide_dx, rh - offset_y - ch)
        if corner == "bottom_left":
            return (offset_x + slide_dx, offset_y)
        if corner == "bottom_right":
            return (rw - cw - offset_x - slide_dx, offset_y)
        return (offset_x + slide_dx, rh - offset_y - ch)

    # --- measurement ---
    def _measure_expanded(self, theme):
        title_h = theme.text_size("title")
        row_h = theme.text_size("normal")
        gap = theme.hud.key_label_spacing
        h = 0
        max_w = 0
        widest_key = 0
        for sec in self.sections:
            for it in sec.items:
                kw, _ = hud_text.measure(it.key, theme=theme,
                                         size_token="normal")
                widest_key = max(widest_key, int(kw))
        key_col_w = widest_key + gap
        for i, sec in enumerate(self.sections):
            if i > 0:
                h += theme.hud.section_spacing
            if sec.title:
                tw, _ = hud_text.measure(sec.title, theme=theme,
                                         size_token="title")
                max_w = max(max_w, int(tw))
                h += title_h + theme.hud.row_spacing
            for it in sec.items:
                lw, _ = hud_text.measure(it.label, theme=theme,
                                         size_token="normal")
                max_w = max(max_w, key_col_w + int(lw))
                h += row_h + theme.hud.row_spacing
        return max_w, h, key_col_w

    def _measure_collapsed(self, theme, prefs):
        hint = self._hint_text(prefs)
        w, _ = hud_text.measure(hint, theme=theme, size_token="normal")
        return int(w), theme.text_size("normal")

    def _hint_text(self, prefs) -> str:
        tpl = getattr(prefs, "help_hint_text", "Press {key} for help")
        key = getattr(prefs, "help_toggle_key", "H")
        try:
            return tpl.format(key=key)
        except (KeyError, IndexError, ValueError):
            return tpl

    # --- draw ---
    def draw(self, context, event=None) -> None:
        if not self.visible:
            return
        if (self._bound_region is not None
                and context.region.as_pointer() != self._bound_region):
            return
        try:
            prefs = context.preferences.addons["InteractionOps"].preferences
            theme_prefs = prefs.iops_theme
        except (KeyError, AttributeError):
            return
        theme = get_theme(context)
        region = context.region

        preset = getattr(theme_prefs, "help_anim_preset", "fade")
        progress = self._anim_progress(theme, theme_prefs)
        # When `from` != `to`, we're animating. Otherwise progress=1 (steady).
        animating = self._anim_from_expanded != self._anim_to_expanded
        if not animating:
            progress = 1.0

        # Pick which content to draw — and at what alpha.
        # Cross-fade: 0..0.5 fades out the previous, 0.5..1.0 fades in the new.
        if animating and preset != "none" and progress < 1.0:
            if progress < 0.5:
                show_expanded = self._anim_from_expanded
                local = progress / 0.5
                alpha = 1.0 - local
            else:
                show_expanded = self._anim_to_expanded
                local = (progress - 0.5) / 0.5
                alpha = local
        else:
            show_expanded = self.expanded
            alpha = 1.0

        if show_expanded and self.sections:
            w, h, key_col_w = self._measure_expanded(theme)
        else:
            w, h = self._measure_collapsed(theme, theme_prefs)
            key_col_w = 0
        if w <= 0:
            return

        corner = getattr(theme_prefs, "help_corner", "top_left")
        offx = int(getattr(theme_prefs, "help_offset_x", 12))
        offy = int(getattr(theme_prefs, "help_offset_y", 12))
        slide = 0
        if preset == "slide-fade" and animating and progress < 1.0:
            # Slide 12px on the anchored side; ease alongside alpha.
            slide_amount = 12
            slide = int(slide_amount * (1.0 - _ease_out(progress)))

        origin = self._corner_origin(
            corner, region, (w, h), offx, offy, slide)
        self._render(theme, origin, (w, h), key_col_w,
                     show_expanded, theme_prefs, alpha)

    def _render(self, theme, origin, size, key_col_w, show_expanded,
                prefs, alpha) -> None:
        x0, y0 = origin
        _, h = size
        y = y0 + h
        title_h = theme.text_size("title")
        row_h = theme.text_size("normal")

        if not show_expanded:
            y -= row_h
            hud_text.draw(self._hint_text(prefs), x0, y, theme=theme,
                          role=Role.HUD_LABEL_OFF, size_token="normal",
                          alpha_mul=alpha)
            return

        for i, sec in enumerate(self.sections):
            if i > 0:
                y -= theme.hud.section_spacing
            if sec.title:
                y -= title_h
                hud_text.draw(sec.title, x0, y, theme=theme,
                              role=Role.ACTIVE_TEXT, size_token="title",
                              alpha_mul=alpha)
                y -= theme.hud.row_spacing
            for it in sec.items:
                y -= row_h
                hud_text.draw(it.key, x0, y, theme=theme,
                              role=Role.HUD_KEY, size_token="normal",
                              alpha_mul=alpha)
                label_role = _STATE_ROLE[it.state]
                hud_text.draw(it.label, x0 + key_col_w, y, theme=theme,
                              role=label_role, size_token="normal",
                              alpha_mul=alpha)
                y -= theme.hud.row_spacing
