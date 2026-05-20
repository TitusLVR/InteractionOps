"""HelpOverlay — corner-anchored hotkey legend with collapse/animation.

Pinned to a configurable screen corner with offset. Two states:

- expanded   → renders the full section/item list.
- collapsed  → renders just `prefs.help_hint_text` (default "Press H for help").

Toggle key: configured via the `iops.ui_help_toggle` keymap item
(default "H", editable in the Keymaps tab). Animation between
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


def _ease_in_out(t: float) -> float:
    # cubic ease in-out — smooth ramp on both ends
    t = max(0.0, min(1.0, t))
    if t < 0.5:
        return 4.0 * t * t * t
    p = 2.0 * t - 2.0
    return 0.5 * p * p * p + 1.0


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


class HelpOverlay:
    def __init__(self, operator_name: str):
        self.operator_name = operator_name
        self.sections: list[HUDSection] = []
        self._items_by_key: dict[str, HUDItem] = {}
        self.visible: bool = True
        self.expanded: bool = True
        # Animation: alpha 0..1 + horizontal slide offset (px). Updated on
        # every draw based on transition timestamps.
        self._anim_from_expanded: bool = True
        self._anim_to_expanded: bool = True
        self._anim_start: float = 0.0
        self._anim_duration: float = 0.18
        self._anim_timer_active: bool = False
        self._bound_region = None

    # --- setup ---
    def add_section(self, section: HUDSection) -> None:
        self.sections.append(section)
        for it in section.items:
            self._items_by_key[it.key] = it

    def set_state(self, key: str, state) -> None:
        """Update the state of an item by its key. No-op if missing."""
        it = self._items_by_key.get(key)
        if it is None:
            return
        if isinstance(state, str):
            state = ItemState(state)
        it.state = state

    def bind_region(self, region) -> None:
        self._bound_region = region.as_pointer() if region is not None else None

    def _find_bound_region(self):
        """Resolve the live region object for `_bound_region`. Lets us use
        the actual 3D viewport's width/height even when `context.region`
        is None or pointing at the prefs region."""
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

    # --- visibility / toggle ---
    def toggle_expanded(self, now: float | None = None,
                        duration: float | None = None) -> bool:
        now = now if now is not None else time.perf_counter()
        if self._anim_to_expanded != self.expanded:
            # mid-flight toggle — restart from current target
            pass
        self._anim_from_expanded = self.expanded
        self.expanded = not self.expanded
        self._anim_to_expanded = self.expanded
        self._anim_start = now
        if duration is not None:
            self._anim_duration = max(0.001, float(duration))
        self._start_anim_timer()
        return self.expanded

    def _start_anim_timer(self) -> None:
        """Drive per-frame redraws while the toggle animation is running.

        Operators only `tag_redraw` on incoming events (mouse move, key);
        without this timer the eased progress would freeze whenever the
        cursor is still. We piggy-back on `bpy.app.timers` so every
        HelpOverlay self-paces regardless of the host operator's loop.
        """
        if self._anim_timer_active:
            return
        if self._bound_region is None:
            return
        import bpy
        self._anim_timer_active = True
        bpy.app.timers.register(self._anim_tick)

    def _anim_tick(self):
        # End condition: animation finished (progress would clamp to 1).
        elapsed = time.perf_counter() - self._anim_start
        rgn = self._find_bound_region()
        if rgn is not None:
            rgn.tag_redraw()
        if elapsed >= self._anim_duration:
            self._anim_timer_active = False
            return None
        return 1.0 / 60.0

    def handle_toggle_event(self, event, prefs) -> bool:
        if event.value != "PRESS":
            return False
        from ...utils.functions import get_ui_toggle_key
        key = get_ui_toggle_key("iops.ui_help_toggle", "H")
        if event.type != key:
            return False
        if event.shift or event.ctrl or event.alt or event.oskey:
            return False
        dur = self._effective_duration(prefs)
        self.toggle_expanded(duration=dur)
        return True

    # --- animation ---
    @staticmethod
    def _effective_duration(prefs) -> float:
        """Per-preset duration: wave has its own knob (defaults longer so
        the letter-by-letter reveal is readable); everything else uses
        the shared `help_anim_duration`."""
        preset = getattr(prefs, "help_anim_preset", "fade")
        if preset == "wave":
            return float(getattr(prefs, "help_anim_wave_duration", 2.0))
        return float(getattr(prefs, "help_anim_duration", 0.18))

    def _anim_progress(self, theme, prefs) -> float:
        preset = getattr(prefs, "help_anim_preset", "fade")
        if preset == "none":
            return 1.0
        dur = max(0.001, self._effective_duration(prefs))
        elapsed = time.perf_counter() - self._anim_start
        return _ease_out(elapsed / dur)

    # --- corner layout ---
    @staticmethod
    def _corner_origin(corner: str, region, size, offset_x, offset_y,
                       slide: int):
        """`slide` is signed displacement *away* from the anchored edge,
        applied along the axis that the anchor pins (horizontal for
        left/right anchors, vertical for top/bottom-center anchors)."""
        cw, ch = size
        rw, rh = region.width, region.height
        cx = (rw - cw) // 2
        cy = (rh - ch) // 2
        if corner == "top_left":
            return (offset_x + slide, rh - offset_y - ch)
        if corner == "top_right":
            return (rw - cw - offset_x - slide, rh - offset_y - ch)
        if corner == "bottom_left":
            return (offset_x + slide, offset_y)
        if corner == "bottom_right":
            return (rw - cw - offset_x - slide, offset_y)
        # For centered positions, the offset on the centered axis acts as
        # a signed shift from the geometric center (positive = right/up).
        if corner == "top_center":
            return (cx + offset_x, rh - offset_y - ch + slide)
        if corner == "bottom_center":
            return (cx + offset_x, offset_y + slide)
        if corner == "left_center":
            return (offset_x + slide, cy + offset_y)
        if corner == "right_center":
            return (rw - cw - offset_x - slide, cy + offset_y)
        return (offset_x + slide, rh - offset_y - ch)

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
                                         size_token="hud_key")
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
                                         size_token="hud_label")
                max_w = max(max_w, key_col_w + int(lw))
                h += row_h + theme.hud.row_spacing
        return max_w, h, key_col_w

    def _measure_collapsed(self, theme, prefs):
        hint = self._hint_text(prefs)
        w, _ = hud_text.measure(hint, theme=theme, size_token="normal")
        return int(w), theme.text_size("normal")

    def _hint_text(self, prefs) -> str:
        from ...utils.functions import get_ui_toggle_key
        tpl = getattr(prefs, "help_hint_text", "Press {key} for help")
        key = get_ui_toggle_key("iops.ui_help_toggle", "H")
        try:
            return tpl.format(key=key)
        except (KeyError, IndexError, ValueError):
            return tpl

    # --- draw ---
    def draw(self, context, event=None) -> None:
        if not self.visible:
            return
        if self._bound_region is not None:
            cur = getattr(context, "region", None)
            if cur is None or cur.as_pointer() != self._bound_region:
                return
        try:
            prefs = context.preferences.addons["InteractionOps"].preferences
            theme_prefs = prefs.iops_theme
        except (KeyError, AttributeError):
            return
        theme = get_theme(context)
        region = self._find_bound_region() or context.region
        if region is None:
            return

        preset = getattr(theme_prefs, "help_anim_preset", "fade")
        progress = self._anim_progress(theme, theme_prefs)
        animating = self._anim_from_expanded != self._anim_to_expanded
        if not animating:
            progress = 1.0

        # Default per-frame state: show the *destination* immediately,
        # let the preset modulate alpha / per-char timing / flash.
        show_expanded = self._anim_to_expanded if animating else self.expanded
        alpha = 1.0
        wave_progress: float | None = None
        flash_boost = 0.0

        if animating and preset != "none" and progress < 1.0:
            if preset == "fade":
                # Smooth cross-fade with eased ramp on both halves so
                # the swap at midpoint is less abrupt.
                if progress < 0.5:
                    show_expanded = self._anim_from_expanded
                    alpha = 1.0 - _ease_in_out(progress / 0.5)
                else:
                    show_expanded = self._anim_to_expanded
                    alpha = _ease_in_out((progress - 0.5) / 0.5)
            elif preset == "slide-fade":
                # Wipe: phase 1 (0..0.5) slides the OUTgoing state toward
                # the anchored edge while fading it out. Phase 2 (0.5..1)
                # slides the INcoming state in from the anchored edge while
                # fading it in. No content swap mid-frame — at progress=0.5
                # the outgoing piece is fully transparent and fully past
                # the anchor offset, so the swap is invisible.
                if progress < 0.5:
                    show_expanded = self._anim_from_expanded
                    eased = _ease_in_out(progress / 0.5)
                    alpha = 1.0 - eased
                else:
                    show_expanded = self._anim_to_expanded
                    eased = _ease_in_out((progress - 0.5) / 0.5)
                    alpha = eased
            elif preset == "wave":
                show_expanded = self._anim_to_expanded
                wave_progress = _ease_out(progress)
                alpha = 1.0
            elif preset == "shockwave":
                # New content fades in underneath; the outgoing content is
                # drawn on top with each letter flying radially outward.
                # That second pass is rendered separately, below.
                show_expanded = self._anim_to_expanded
                alpha = _ease_out(min(1.0, progress * 1.4))

        if show_expanded and self.sections:
            w, h, key_col_w = self._measure_expanded(theme)
        else:
            w, h = self._measure_collapsed(theme, theme_prefs)
            key_col_w = 0
        if w <= 0:
            return

        corner = getattr(theme_prefs, "help_corner", "left_center")
        offx = int(getattr(theme_prefs, "help_offset_x", 12))
        offy = int(getattr(theme_prefs, "help_offset_y", 12))
        slide = 0
        if preset == "slide-fade" and animating and progress < 1.0:
            slide_amount = int(getattr(theme_prefs, "help_anim_slide_amount", 28))
            if progress < 0.5:
                # Phase 1: outgoing slides toward the anchored edge.
                eased = _ease_in_out(progress / 0.5)
                slide = -int(slide_amount * eased)
            else:
                # Phase 2: incoming slides in from the anchored edge.
                eased = _ease_in_out((progress - 0.5) / 0.5)
                slide = int(slide_amount * (1.0 - eased))

        origin = self._corner_origin(
            corner, region, (w, h), offx, offy, slide)
        self._render(theme, origin, (w, h), key_col_w,
                     show_expanded, theme_prefs, alpha,
                     wave_progress=wave_progress, flash_boost=flash_boost)

        # Shockwave: second pass — outgoing content laid out at *its* own
        # box origin, each letter pushed radially outward from the box
        # centre, alpha decaying with progress².
        if (preset == "shockwave" and animating and progress < 1.0):
            out_expanded = self._anim_from_expanded
            if out_expanded and self.sections:
                ow, oh, okey = self._measure_expanded(theme)
            else:
                ow, oh = self._measure_collapsed(theme, theme_prefs)
                okey = 0
            if ow > 0:
                o_origin = self._corner_origin(
                    corner, region, (ow, oh), offx, offy, 0)
                radius = int(getattr(theme_prefs,
                                     "help_anim_shockwave_radius", 160))
                shock_state = {
                    "cx": o_origin[0] + ow / 2,
                    "cy": o_origin[1] + oh / 2,
                    "distance": radius * _ease_out(progress),
                    "alpha_factor": (1.0 - progress) ** 2,
                }
                self._render(theme, o_origin, (ow, oh), okey,
                             out_expanded, theme_prefs, 1.0,
                             shock_state=shock_state)

    def _collect_strings(self, prefs, show_expanded):
        """Return the list of text strings rendered when `show_expanded`,
        in draw order. Used to size the per-character wave stagger so the
        full reveal completes within `progress=1`."""
        if not show_expanded:
            return [self._hint_text(prefs)]
        out = []
        for sec in self.sections:
            if sec.title:
                out.append(sec.title)
            for it in sec.items:
                out.append(it.key)
                out.append(it.label)
        return out

    def _draw_text(self, text, x, y, *, theme, role, size_token, alpha_mul,
                   wave_state, flash_boost, shock_state=None):
        """Draw text, applying the active animation preset.

        - `wave_state`: None for plain draw; otherwise a dict with
          `progress`, `stagger`, `fade_window`, and a mutable `index` —
          each character drawn here advances `index['v']`.
        - `shock_state`: when set, each character is offset radially from
          (`cx`, `cy`) by `distance` px and rendered at `alpha_factor`
          times `alpha_mul` — used by the "shockwave" preset.
        - `flash_boost`: 0..1 — when > 0, a copy of the text is drawn on
          top in HUD_KEY (highlight) color at that opacity for a bright
          pulse on toggle.
        """
        if shock_state is not None:
            cx = shock_state["cx"]
            cy = shock_state["cy"]
            dist = shock_state["distance"]
            a_factor = shock_state["alpha_factor"]
            row_h = theme.text_size(size_token)
            cur_x = x
            import math
            for ch in text:
                w, _ = hud_text.measure(ch, theme=theme,
                                        size_token=size_token)
                # Char visual centre — y is baseline, lift by half-height.
                px = cur_x + w * 0.5
                py = y + row_h * 0.5
                dx = px - cx
                dy = py - cy
                length = math.hypot(dx, dy)
                if length < 1e-3:
                    # Char sits on centre — pick an outward direction so
                    # it still participates in the wave (random-ish via
                    # index parity is overkill; just send it upward).
                    nx, ny = 0.0, 1.0
                else:
                    nx = dx / length
                    ny = dy / length
                ox = int(nx * dist)
                oy = int(ny * dist)
                if a_factor > 0.0:
                    hud_text.draw(ch, cur_x + ox, y + oy, theme=theme,
                                  role=role, size_token=size_token,
                                  alpha_mul=alpha_mul * a_factor)
                cur_x += int(w)
            return
        if wave_state is None:
            hud_text.draw(text, x, y, theme=theme, role=role,
                          size_token=size_token, alpha_mul=alpha_mul)
        else:
            cur_x = x
            prog = wave_state["progress"]
            stagger = wave_state["stagger"]
            window = wave_state["fade_window"]
            spread = wave_state["spread"]
            idx_holder = wave_state["index"]
            for ch in text:
                i = idx_holder["v"]
                idx_holder["v"] = i + 1
                local_raw = (prog - i * stagger) / max(1e-6, window)
                local = _clamp01(local_raw)
                ch_alpha = local
                # Letters fly in toward final position from `spread` pixels
                # to the right (anchored edge side) — eased so they land
                # softly. local_eased == 1 → no offset.
                local_eased = _ease_out(local)
                dx = int(spread * (1.0 - local_eased))
                if ch_alpha > 0.0:
                    hud_text.draw(ch, cur_x + dx, y, theme=theme, role=role,
                                  size_token=size_token,
                                  alpha_mul=alpha_mul * ch_alpha)
                w, _ = hud_text.measure(ch, theme=theme,
                                        size_token=size_token)
                cur_x += int(w)

        if flash_boost > 0.0:
            hud_text.draw(text, x, y, theme=theme, role=Role.HUD_KEY,
                          size_token=size_token, alpha_mul=flash_boost)

    def _render(self, theme, origin, size, key_col_w, show_expanded,
                prefs, alpha, *, wave_progress=None,
                flash_boost: float = 0.0, shock_state=None) -> None:
        x0, y0 = origin
        _, h = size
        y = y0 + h
        title_h = theme.text_size("title")
        row_h = theme.text_size("normal")

        # If wave is active, set up a shared char-index counter and a
        # stagger sized so every visible character lands by progress=1.
        wave_state = None
        if wave_progress is not None:
            total_chars = sum(len(s) for s in
                              self._collect_strings(prefs, show_expanded))
            total_chars = max(1, total_chars)
            fade_window = float(getattr(prefs, "help_anim_wave_fade_window", 0.45))
            stagger_scale = float(getattr(prefs, "help_anim_wave_stagger_scale", 2.0))
            spread = int(getattr(prefs, "help_anim_wave_spread", 64))
            # Even spread so the last letter finishes within [0,1]. Multiply
            # by stagger_scale to let the user exaggerate the per-letter
            # delay (letters then trail more visibly behind one another).
            base_stagger = (1.0 - fade_window) / total_chars
            stagger = max(0.0, base_stagger * stagger_scale)
            wave_state = {
                "progress": _clamp01(wave_progress),
                "stagger": stagger,
                "fade_window": fade_window,
                "spread": spread,
                "index": {"v": 0},
            }

        if not show_expanded:
            y -= row_h
            self._draw_text(self._hint_text(prefs), x0, y, theme=theme,
                            role=Role.HUD_LABEL_OFF, size_token="normal",
                            alpha_mul=alpha, wave_state=wave_state,
                            flash_boost=flash_boost, shock_state=shock_state)
            return

        for i, sec in enumerate(self.sections):
            if i > 0:
                y -= theme.hud.section_spacing
            if sec.title:
                y -= title_h
                self._draw_text(sec.title, x0, y, theme=theme,
                                role=Role.ACTIVE_TEXT, size_token="title",
                                alpha_mul=alpha, wave_state=wave_state,
                                flash_boost=flash_boost, shock_state=shock_state)
                y -= theme.hud.row_spacing
            for it in sec.items:
                y -= row_h
                self._draw_text(it.key, x0, y, theme=theme,
                                role=Role.HUD_KEY, size_token="hud_key",
                                alpha_mul=alpha, wave_state=wave_state,
                                flash_boost=flash_boost, shock_state=shock_state)
                label_role = _STATE_ROLE[it.state]
                self._draw_text(it.label, x0 + key_col_w, y, theme=theme,
                                role=label_role, size_token="hud_label",
                                alpha_mul=alpha, wave_state=wave_state,
                                flash_boost=flash_boost, shock_state=shock_state)
                y -= theme.hud.row_spacing
