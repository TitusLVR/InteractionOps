"""Render a WidgetPanel — POST_PIXEL, ui/draw primitives + ui/hud/text only.

Sizing comes from the theme text sizes (no new size prefs); colors map to
existing theme roles per the design doc:
    panel fill            -> theme.hud.bg_color
    outline               -> Role.BBOX
    primary (fill/value)  -> Role.HUD_ACTIVE_VALUE
    secondary (labels)    -> Role.HUD_LABEL
    hint (sections, msgs) -> Role.HUD_LABEL_INACTIVE
    error (Clear button)  -> Role.HUD_STATS_ERROR / Role.ERROR_LINE
Disabled / out-of-context = secondary @ 0.35 alpha (resolved color, faded).

`compute_layout()` writes the per-control rects back onto the panel (and
slider track spans onto the Slider controls) — the interact modal hit-tests
against exactly what was drawn.
"""
from __future__ import annotations

from ..draw import primitives, draw_scope
from ..draw.theme import Role, get_theme, _srgb_encode
from ..hud import text as hud_text
from .controls import (Row, pixel_from_value, preset_cell_rects)
from .panel import Rect

# Layout constants (pixels). Heights derive from theme text sizes at
# layout time; these are paddings/insets around them.
PANEL_MIN_CONTENT_W = 180.0
DISABLED_ALPHA = 0.35
MIXED_FILL_ALPHA = 0.45
ROW_PAD_SECTION = 6.0
ROW_PAD_CONTROL = 10.0
TITLE_PAD = 10.0
SLIDER_VALUE_COL = 8.0      # gap between track and value text
BOX_INSET = 3.0             # flipbox check inset
SWATCH_INSET = 2.0          # color-fill inset inside the swatch outline
SWATCH_MIN_W = 28.0         # min swatch cell width (clickable target)
SWATCH_HEIGHT_FACTOR = 1.8  # swatch row height = factor * label height
CHECKER_COLS = 4            # transparency-checker cells across an alpha swatch
CHECKER_ROWS = 2
CHECKER_LIGHT = (0.55, 0.55, 0.55, 1.0)
CHECKER_DARK = (0.30, 0.30, 0.30, 1.0)
PRESET_GAP = 4.0
TICK_H = 4.0
MAX_TICKS = 32
CLOSE_GLYPH = "×"
OUT_OF_CONTEXT_TEXT = "Go back to Edit Mode"
MIXED_TEXT = "<mixed>"
DROPDOWN_GLYPH = "▾"
CELL_INSET = 6.0            # horizontal text inset inside dropdown/input box
EMPTY_TEXT = "—"
DROPDOWN_ITEM_H = 22.0      # height of one open-dropdown list item (px)
SCROLL_UP_GLYPH = "▲"       # clipped-items hint at the list's top edge
SCROLL_DOWN_GLYPH = "▼"     # clipped-items hint at the list's bottom edge
NO_MATCH_TEXT = "(no match)"
CARET_GLYPH = "|"
INPUT_VALUE_MAX_W = 150.0   # cap the value text's contribution to panel width;
                            # longer values are middle-truncated on display
ELLIPSIS = "…"


def _fade(color, mul):
    return (color[0], color[1], color[2], color[3] * mul)


def _col(theme, role, dim=1.0):
    return _fade(theme.color_for(role), dim)


def _outline(rect, color, theme):
    pts = [(rect.x, rect.y), (rect.x2, rect.y), (rect.x2, rect.y2),
           (rect.x, rect.y2), (rect.x, rect.y)]
    primitives.polyline(pts, color=color, width="default", theme=theme)


def _baseline_y(rect_cy, theme, size_token):
    # blf.position() places the text BASELINE at y. Center the cap-height
    # box (measured from a descender-free reference) instead of each
    # string's own bounds — otherwise descenders ("Export", "Sprite")
    # inflate the measured height and push that string visibly lower than
    # its neighbors.
    cap_h = hud_text.measure("X", theme=theme, size_token=size_token)[1]
    return int(rect_cy - cap_h * 0.5)


def _text_centered(text, rect, *, theme, color, size_token="hud_label"):
    w, _ = hud_text.measure(text, theme=theme, size_token=size_token)
    hud_text.draw(text, int(rect.cx - w * 0.5),
                  _baseline_y(rect.cy, theme, size_token),
                  theme=theme, color=color, size_token=size_token)


def _text_left(text, rect, x, *, theme, color, size_token="hud_label"):
    hud_text.draw(text, int(x), _baseline_y(rect.cy, theme, size_token),
                  theme=theme, color=color, size_token=size_token)


def _truncate_middle(text, max_w, theme, size_token="hud_label"):
    """Shorten `text` to fit `max_w` px with a middle ellipsis
    (`very lo…_end`), keeping both ends so a leading name and trailing
    counter stay visible. Returns `text` unchanged when it already fits."""
    def m(s):
        return hud_text.measure(s, theme=theme, size_token=size_token)[0]
    if max_w <= 0 or m(text) <= max_w:
        return text
    n = len(text)
    # Shrink the kept character count until head+…+tail fits.
    for keep in range(n - 1, 0, -1):
        head = (keep + 1) // 2
        tail = keep // 2
        cand = text[:head] + ELLIPSIS + (text[n - tail:] if tail else "")
        if m(cand) <= max_w:
            return cand
    return ELLIPSIS


# ----------------------------------------------------------------------
# Layout
# ----------------------------------------------------------------------
def _row_height(control, theme):
    label_h = theme.text_size("hud_label")
    if control.kind == "section":
        return label_h + ROW_PAD_SECTION
    if control.kind == "swatch":
        return label_h * SWATCH_HEIGHT_FACTOR + ROW_PAD_CONTROL
    # dropdown / input / buttons are single-line control-height rows.
    return label_h + ROW_PAD_CONTROL


def _control_min_width(control, theme, context=None):
    """Content width a control needs to render without clipping. `context`
    (when given) lets value-bearing controls size to their live value."""
    def tw(text, token="hud_label"):
        return hud_text.measure(text, theme=theme, size_token=token)[0]

    if control.kind == "section":
        return tw(control.label) + 8.0
    if control.kind == "slider":
        # Track minimum + widest value text the slider can show.
        value_w = max(tw(control.fmt.format(control.vmax)), tw(MIXED_TEXT))
        return 80.0 + SLIDER_VALUE_COL + value_w
    if control.kind == "presets":
        labels_w = sum(tw(control.fmt.format(v)) + 12.0
                       for v in control.values)
        return labels_w + PRESET_GAP * max(0, len(control.values) - 1)
    if control.kind == "flipbox":
        box = theme.text_size("hud_label")
        return box + 6.0 + tw(control.label)
    if control.kind == "swatch":
        return SWATCH_MIN_W
    if control.kind == "button":
        return tw(control.label) + 24.0
    if control.kind == "dropdown":
        # widest display among declared labels, LIVE items and the current
        # value + glyph + insets — the field (and the open list, which
        # reuses the field width) fits the longest name untruncated.
        labels = getattr(control, "labels", None) or {}
        names = list(labels.values()) or list(labels.keys())
        if context is not None:
            items_get = getattr(control, "items_get", None)
            if items_get is not None:
                try:
                    names = names + [d for _i, d in items_get(context)]
                except Exception:
                    pass   # provider hiccup -> size from what we have
            val = control.display(context)
            if val:
                names = names + [val]
        widest = max((tw(n) for n in names), default=0.0)
        widest = max(widest, tw(EMPTY_TEXT))
        return widest + tw(DROPDOWN_GLYPH) + CELL_INSET * 3.0
    if control.kind == "input":
        # label (left) + value region (right) + insets. The value grows the
        # panel only up to INPUT_VALUE_MAX_W; beyond that it is truncated on
        # draw, so a long string never balloons the panel.
        val_w = tw(control.display(context)) if context is not None else 0.0
        val_w = min(val_w, INPUT_VALUE_MAX_W)
        val_w = max(val_w, tw(EMPTY_TEXT))
        return tw(control.label) + val_w + CELL_INSET * 3.0
    if control.kind == "buttons":
        labels_w = sum(tw(label) + 12.0 for _v, label in control.options)
        return labels_w + PRESET_GAP * max(0, len(control.options) - 1)
    if control.kind == "row":
        # Fixed cells (buttons hug their label) contribute their own min;
        # flex cells end up equal-width, so each must fit the widest one.
        n = max(1, len(control.children))
        fixed = flex = 0.0
        widest_flex = 0.0
        n_flex = 0
        for c in control.children:
            w = _control_min_width(c, theme, context)
            if c.kind == "button":
                fixed += w
            else:
                widest_flex = max(widest_flex, w)
                n_flex += 1
        flex = widest_flex * n_flex
        return fixed + flex + 6.0 * (n - 1)
    return 0.0


def _in_context(widget, context):
    try:
        return bool(widget.poll(context))
    except Exception:
        return False


def compute_layout(context, widget, theme=None):
    """Compute row heights/content width from the theme and lay the panel
    out (clamped to the region). Returns the resolved theme. Safe to call
    from both the draw handler and the interact operator.

    Out of context the panel collapses to title bar + one message row, so
    hit rects match the collapsed draw."""
    th = theme if theme is not None else get_theme(context)
    rows = []
    if _in_context(widget, context):
        for control in widget.rows(context):
            if isinstance(control, Row):
                height = max((_row_height(c, th) for c in control.children),
                             default=_row_height(control, th))
                # Buttons hug their label (fixed cell); everything else
                # flexes over the remaining width. No buttons -> equal split.
                spec = [_control_min_width(c, th, context)
                        if c.kind == "button" else None
                        for c in control.children]
                if any(w is not None for w in spec):
                    rows.append((height, control.columns, spec))
                else:
                    rows.append((height, control.columns))
            else:
                rows.append((_row_height(control, th), 1))
        min_content = max((_control_min_width(c, th, context)
                           for c in widget.rows(context)),
                          default=0.0)
    else:
        rows.append((th.text_size("hud_label") + ROW_PAD_CONTROL, 1))
        min_content = hud_text.measure(OUT_OF_CONTEXT_TEXT, theme=th)[0] + 8.0

    title_h = th.text_size("hud_header") + TITLE_PAD
    content_w = max(
        PANEL_MIN_CONTENT_W,
        hud_text.measure(widget.panel.title, theme=th,
                         size_token="hud_header")[0] + title_h + 8.0,
        min_content,
    )
    widget.panel.layout(
        rows, content_w,
        padding=float(th.hud.bg_padding),
        title_h=title_h,
        row_gap=float(th.hud.row_spacing) + 2.0,
    )
    region = context.region
    if region is not None:
        widget.panel.clamp_to_region(region.width, region.height)
        # Re-layout at the clamped anchor so rects match the final spot.
        widget.panel.layout(rows, content_w,
                            padding=float(th.hud.bg_padding),
                            title_h=title_h,
                            row_gap=float(th.hud.row_spacing) + 2.0)
    return th


# ----------------------------------------------------------------------
# Control draws
# ----------------------------------------------------------------------
def _draw_section(control, rect, theme, dim):
    color = _col(theme, Role.HUD_LABEL_INACTIVE, dim)
    _text_left(control.label, rect, rect.x, theme=theme, color=color)


def _draw_slider(control, rect, theme, dim, context, live):
    value, mixed = control.value(context) if live else control.cached()
    disabled = (value is None) or not control.enabled
    eff = dim * (DISABLED_ALPHA if disabled else 1.0)

    # Value column on the right; track gets the rest.
    value_w = max(
        hud_text.measure(control.fmt.format(control.vmax), theme=theme)[0],
        hud_text.measure(MIXED_TEXT, theme=theme)[0])
    track_x = rect.x
    track_w = max(1.0, rect.w - value_w - SLIDER_VALUE_COL)
    cy = rect.cy
    # Stored back for the interact modal's pixel->value mapping.
    control.track_x = track_x
    control.track_w = track_w

    track_color = _col(theme, Role.LINE, eff)
    fill_color = _col(theme, Role.HUD_ACTIVE_VALUE, eff)
    primitives.line((track_x, cy), (track_x + track_w, cy),
                    color=track_color, width="default", theme=theme)
    # Ticks at snap increments (skipped when they'd turn into noise).
    if control.snap > 0.0 and control.vmax > control.vmin:
        n = int(round((control.vmax - control.vmin) / control.snap))
        if 1 <= n <= MAX_TICKS:
            tick_color = _col(theme, Role.HUD_LABEL_INACTIVE, eff * 0.8)
            ticks = []
            for i in range(n + 1):
                tx = track_x + track_w * (i / n)
                ticks.extend([(tx, cy - TICK_H * 0.5),
                              (tx, cy + TICK_H * 0.5)])
            primitives.edges_3d(ticks, color=tick_color, width="default",
                                theme=theme)

    if mixed:
        # Half-tone full-width fill, no thumb.
        primitives.rect_2d(track_x, cy - 2.0, track_w, 4.0,
                           color=_fade(fill_color, MIXED_FILL_ALPHA),
                           theme=theme)
        value_text = MIXED_TEXT
    elif value is not None:
        fx = pixel_from_value(float(value), track_x, track_w,
                              control.vmin, control.vmax)
        if fx > track_x:
            primitives.rect_2d(track_x, cy - 2.0, fx - track_x, 4.0,
                               color=fill_color, theme=theme)
        primitives.points([(fx, cy)], color=fill_color,
                          size=float(theme.point_size("default")),
                          theme=theme)
        value_text = control.fmt.format(float(value))
    else:
        value_text = "—"

    tw, _ = hud_text.measure(value_text, theme=theme)
    hud_text.draw(value_text, int(rect.x2 - tw),
                  _baseline_y(cy, theme, "hud_label"),
                  theme=theme, color=fill_color)


def _draw_presets(control, rect, theme, dim):
    eff = dim * (1.0 if control.enabled else DISABLED_ALPHA)
    line_color = _col(theme, Role.LINE, eff)
    label_color = _col(theme, Role.HUD_LABEL, eff)
    for (cx, cw), value in zip(
            preset_cell_rects(rect.x, rect.w, len(control.values),
                              PRESET_GAP),
            control.values):
        cell = Rect(cx, rect.y + 1.0, cw, rect.h - 2.0)
        _outline(cell, line_color, theme)
        _text_centered(control.fmt.format(value), cell,
                       theme=theme, color=label_color)


def _draw_flipbox(control, rect, theme, dim, context, live):
    value, mixed = control.value(context) if live else control.cached()
    disabled = (value is None and not mixed) or not control.enabled
    eff = dim * (DISABLED_ALPHA if disabled else 1.0)
    box = min(rect.h - 4.0, float(theme.text_size("hud_label")) + 2.0)
    bx = rect.x
    by = rect.cy - box * 0.5
    box_rect = Rect(bx, by, box, box)
    _outline(box_rect, _col(theme, Role.LINE, eff), theme)
    fill_color = _col(theme, Role.HUD_ACTIVE_VALUE, eff)
    if mixed:
        # Diagonal half-fill: lower-left triangle of the inner box.
        x0, y0 = bx + BOX_INSET, by + BOX_INSET
        x1, y1 = bx + box - BOX_INSET, by + box - BOX_INSET
        primitives.tris([(x0, y0), (x1, y0), (x0, y1)],
                        color=_fade(fill_color, 0.8), theme=theme)
    elif value:
        primitives.rect_2d(bx + BOX_INSET, by + BOX_INSET,
                           box - BOX_INSET * 2.0, box - BOX_INSET * 2.0,
                           color=fill_color, theme=theme)
    _text_left(control.label, rect, bx + box + 6.0,
               theme=theme, color=_col(theme, Role.HUD_LABEL, eff))


def _draw_button(control, rect, theme, dim, pressed=False):
    eff = dim * (1.0 if control.enabled else DISABLED_ALPHA)
    if pressed:
        # Active-press feedback while the button is held (set by the
        # interact modal; cleared on release/cancel): a subtle tint = 25%
        # of the checkbox/active-value color mixed over the panel bg.
        # Pre-mixed at the panel's own alpha rather than relying on a low
        # alpha + GPU blend, which the filled-tri shader doesn't honor
        # consistently (it would otherwise render at full opacity).
        bg = theme.hud.bg_color
        hot = theme.color_for(Role.HUD_ACTIVE_VALUE)
        t = 0.25
        tint = (bg[0] * (1.0 - t) + hot[0] * t,
                bg[1] * (1.0 - t) + hot[1] * t,
                bg[2] * (1.0 - t) + hot[2] * t,
                bg[3])
        primitives.rect_2d(rect.x, rect.y, rect.w, rect.h,
                           color=tint, theme=theme)
    if control.role == "error":
        line_color = _col(theme, Role.ERROR_LINE, eff)
        text_color = _col(theme, Role.HUD_STATS_ERROR, eff)
    else:
        line_color = _col(theme, Role.LINE, eff)
        text_color = _col(theme, Role.HUD_LABEL, eff)
    _outline(rect, line_color, theme)
    _text_centered(control.label, rect, theme=theme, color=text_color)


def _draw_checker(x, y, w, h, theme):
    """Opaque transparency checker filling a swatch's inset rect (two greys).
    Drawn at full opacity so it shows through wherever the alpha fill above
    it is < 1.0 — used by show_alpha swatches to read alpha as transparency."""
    cw = w / CHECKER_COLS
    ch = h / CHECKER_ROWS
    for r in range(CHECKER_ROWS):
        for c in range(CHECKER_COLS):
            col = CHECKER_LIGHT if (r + c) % 2 == 0 else CHECKER_DARK
            primitives.rect_2d(x + c * cw, y + r * ch, cw, ch,
                               color=col, theme=theme)


def _draw_swatch(control, rect, theme, dim, context, live):
    value, _ = control.value(context) if live else control.cached()
    disabled = (value is None) or not control.enabled
    eff = dim * (DISABLED_ALPHA if disabled else 1.0)
    show_alpha = getattr(control, "show_alpha", False)
    if value is not None:
        # subtype=COLOR props are scene-linear; encode to sRGB to match the
        # native color field.
        enc = _srgb_encode(value)
        ix, iy = rect.x + SWATCH_INSET, rect.y + SWATCH_INSET
        iw, ih = rect.w - SWATCH_INSET * 2.0, rect.h - SWATCH_INSET * 2.0
        if show_alpha:
            # Checker behind, fill honoring the color's real alpha on top.
            # Alpha 0 => checker only (transparent); 1 => solid over checker.
            _draw_checker(ix, iy, iw, ih, theme)
            a = value[3]
            if a > 0.0:
                primitives.rect_2d(ix, iy, iw, ih,
                                   color=(enc[0], enc[1], enc[2], a),
                                   theme=theme)
        else:
            # Force opaque so a low-alpha stored color is still visible
            # (alpha is not part of a normal swatch's job).
            primitives.rect_2d(ix, iy, iw, ih,
                               color=(enc[0], enc[1], enc[2], 1.0), theme=theme)
    # Outline/label carry the disabled fade; the fill stays readable.
    _outline(rect, _col(theme, Role.LINE, eff), theme)
    if control.label:
        _text_centered(control.label, rect, theme=theme,
                       color=_col(theme, Role.HUD_LABEL, eff))


def _active_fill(theme):
    """Pressed-tint fill: 25% of the active-value color pre-mixed over the
    panel bg, matching `_draw_button`'s held-press feedback (the filled-tri
    shader doesn't honor a low-alpha color, so it's pre-mixed at bg alpha)."""
    bg = theme.hud.bg_color
    hot = theme.color_for(Role.HUD_ACTIVE_VALUE)
    t = 0.25
    return (bg[0] * (1.0 - t) + hot[0] * t,
            bg[1] * (1.0 - t) + hot[1] * t,
            bg[2] * (1.0 - t) + hot[2] * t,
            bg[3])


def _draw_dropdown(control, rect, theme, dim, context, pressed=False):
    # Always in-context (RNA-bound): read the getter live each draw.
    text = control.display(context)
    disabled = text is None or text == EMPTY_TEXT
    eff = dim * (DISABLED_ALPHA if disabled else 1.0)
    line_color = _col(theme, Role.LINE, eff)
    label_color = _col(theme, Role.HUD_LABEL, eff)
    glyph_color = _col(theme, Role.HUD_ACTIVE_VALUE, eff)
    if pressed:
        primitives.rect_2d(rect.x, rect.y, rect.w, rect.h,
                           color=_active_fill(theme), theme=theme)
    _outline(rect, line_color, theme)
    gw, _ = hud_text.measure(DROPDOWN_GLYPH, theme=theme)
    # Value region = field minus the glyph and insets; middle-truncate so a
    # long value (e.g. an image name) never overruns the glyph / panel edge.
    shown = EMPTY_TEXT if text is None else text
    shown = _truncate_middle(shown, rect.w - CELL_INSET * 3.0 - gw, theme)
    _text_left(shown, rect, rect.x + CELL_INSET,
               theme=theme, color=label_color)
    _text_left(DROPDOWN_GLYPH, rect, rect.x2 - CELL_INSET - gw,
               theme=theme, color=glyph_color)


def _draw_input(control, rect, theme, dim, context, pressed=False, edit=None):
    label_color = _col(theme, Role.HUD_LABEL, dim)
    value_color = _col(theme, Role.HUD_ACTIVE_VALUE, dim)
    if edit is not None:
        # Focused edit: active outline + live buffer with selection + caret,
        # drawn left-aligned just past the label so caret math is simple.
        _outline(rect, _col(theme, Role.HUD_ACTIVE_VALUE, dim), theme)
        _text_left(control.label, rect, rect.x + CELL_INSET,
                   theme=theme, color=label_color)
        lw, _ = hud_text.measure((control.label or "") + "  ", theme=theme)
        bx = rect.x + CELL_INSET + lw
        buf = edit.text
        ch = float(theme.text_size("hud_label"))
        if edit.has_sel:
            a, b = edit.sel_range()
            ax = bx + hud_text.measure(buf[:a], theme=theme)[0]
            sw = hud_text.measure(buf[a:b], theme=theme)[0]
            primitives.rect_2d(ax, rect.cy - ch * 0.5, max(1.0, sw), ch,
                               color=_active_fill(theme), theme=theme)
        _text_left(buf, rect, bx, theme=theme, color=value_color)
        cx = bx + hud_text.measure(buf[:edit.caret], theme=theme)[0]
        _text_left(CARET_GLYPH, rect, cx - 1.0, theme=theme, color=value_color)
        return

    value_text = control.display(context)
    disabled = value_text is None or value_text == EMPTY_TEXT
    eff = dim * (DISABLED_ALPHA if disabled else 1.0)
    line_color = _col(theme, Role.LINE, eff)
    if pressed:
        primitives.rect_2d(rect.x, rect.y, rect.w, rect.h,
                           color=_active_fill(theme), theme=theme)
    _outline(rect, line_color, theme)
    _text_left(control.label, rect, rect.x + CELL_INSET,
               theme=theme, color=_col(theme, Role.HUD_LABEL, eff))
    shown = EMPTY_TEXT if value_text is None else value_text
    # Value region = field minus the label and both insets; middle-truncate
    # so a long value never overruns the label / panel edge.
    label_w, _ = hud_text.measure(control.label, theme=theme)
    avail = rect.w - CELL_INSET * 3.0 - label_w
    shown = _truncate_middle(shown, avail, theme)
    vw, _ = hud_text.measure(shown, theme=theme)
    _text_left(shown, rect, rect.x2 - CELL_INSET - vw,
               theme=theme, color=_col(theme, Role.HUD_ACTIVE_VALUE, eff))


def _draw_buttons(control, rect, theme, dim, context):
    eff = dim * (1.0 if control.enabled else DISABLED_ALPHA)
    line_color = _col(theme, Role.LINE, eff)
    label_color = _col(theme, Role.HUD_LABEL, eff)
    active = control.active_index(context)
    fill = _active_fill(theme)
    for i, ((cx, cw), (_value, label)) in enumerate(zip(
            preset_cell_rects(rect.x, rect.w, len(control.options),
                              PRESET_GAP),
            control.options)):
        cell = Rect(cx, rect.y + 1.0, cw, rect.h - 2.0)
        if i == active:
            primitives.rect_2d(cell.x, cell.y, cell.w, cell.h,
                               color=fill, theme=theme)
        _outline(cell, line_color, theme)
        _text_centered(label, cell, theme=theme, color=label_color)


def _draw_control(control, rect, theme, dim, context, live, pressed=False,
                  edit=None):
    # Live enabled resolution (dirty-cached): presets/Clear gray out and
    # go inert with no selection (spec) — only touched while in context,
    # out-of-context draws keep the last cached flag.
    if live:
        control.update_enabled(context)
    kind = control.kind
    if kind == "section":
        _draw_section(control, rect, theme, dim)
    elif kind == "slider":
        _draw_slider(control, rect, theme, dim, context, live)
    elif kind == "presets":
        _draw_presets(control, rect, theme, dim)
    elif kind == "flipbox":
        _draw_flipbox(control, rect, theme, dim, context, live)
    elif kind == "button":
        _draw_button(control, rect, theme, dim, pressed)
    elif kind == "swatch":
        _draw_swatch(control, rect, theme, dim, context, live)
    elif kind == "dropdown":
        _draw_dropdown(control, rect, theme, dim, context, pressed)
    elif kind == "input":
        _draw_input(control, rect, theme, dim, context, pressed, edit)
    elif kind == "buttons":
        _draw_buttons(control, rect, theme, dim, context)


def _draw_dropdown_list(dd, theme):
    """Draw an open dropdown (a controls.DropdownState) on top of the
    panel: the visible window of filtered items, ▲/▼ hints when the list
    is clipped, and the typed filter over the field cell. Geometry comes
    from dd.rects(), the same source events hit-tests against, so draw
    and pick can never disagree."""
    window = dd.window()
    rects = dd.rects()
    bg = theme.hud.bg_color
    line_color = _col(theme, Role.BBOX, 1.0)
    label_color = _col(theme, Role.HUD_LABEL, 1.0)
    hint_color = _col(theme, Role.HUD_LABEL_INACTIVE, 1.0)
    fill = _active_fill(theme)

    if not window:
        # Filter matched nothing: one dimmed placeholder cell.
        x, y, w, h = rects[0]
        cell = Rect(x, y, w, h)
        primitives.rect_2d(x, y, w, h, color=bg, theme=theme)
        _outline(cell, line_color, theme)
        _text_left(NO_MATCH_TEXT, cell, x + CELL_INSET,
                   theme=theme, color=hint_color)
    else:
        for i, ((x, y, w, h), (_ident, disp)) in enumerate(
                zip(rects, window)):
            cell = Rect(x, y, w, h)
            primitives.rect_2d(x, y, w, h, color=bg, theme=theme)
            if dd.offset + i == dd.hover:
                primitives.rect_2d(x, y, w, h, color=fill, theme=theme)
            _outline(cell, line_color, theme)
            disp = _truncate_middle(disp, w - CELL_INSET * 3.0
                                    - hud_text.measure(SCROLL_UP_GLYPH,
                                                       theme=theme)[0],
                                    theme)
            _text_left(disp, cell, x + CELL_INSET,
                       theme=theme, color=label_color)
        # Clip hints: rects[0] is the visually topmost cell in BOTH
        # orientations (reading order is preserved when flipped), so
        # "more before the window" is always the top edge.
        if dd.clipped_above():
            x, y, w, h = rects[0]
            gw, _ = hud_text.measure(SCROLL_UP_GLYPH, theme=theme)
            _text_left(SCROLL_UP_GLYPH, Rect(x, y, w, h),
                       x + w - CELL_INSET - gw,
                       theme=theme, color=hint_color)
        if dd.clipped_below():
            x, y, w, h = rects[-1]
            gw, _ = hud_text.measure(SCROLL_DOWN_GLYPH, theme=theme)
            _text_left(SCROLL_DOWN_GLYPH, Rect(x, y, w, h),
                       x + w - CELL_INSET - gw,
                       theme=theme, color=hint_color)

    if dd.filter:
        # Typed filter replaces the field's value text while open (with a
        # trailing underscore as a caret hint), in the active-value color
        # so it reads as "editing".
        x, y, w, h = dd.field
        cell = Rect(x, y, w, h)
        active = _col(theme, Role.HUD_ACTIVE_VALUE, 1.0)
        primitives.rect_2d(x, y, w, h, color=bg, theme=theme)
        _outline(cell, active, theme)
        shown = _truncate_middle(dd.filter + "_", w - CELL_INSET * 2.0,
                                 theme)
        _text_left(shown, cell, x + CELL_INSET, theme=theme, color=active)


# ----------------------------------------------------------------------
# Panel draw
# ----------------------------------------------------------------------
def _draw_chrome(panel, theme, dim):
    b = panel.bounds()
    # Panel fill — the unified HUD background color (already sRGB-encoded
    # by get_theme), drawn even when the HUD bg toggle is off: an
    # interactive panel needs a readable hit surface.
    primitives.rect_2d(b.x, b.y, b.w, b.h,
                       color=theme.hud.bg_color, theme=theme)
    _outline(b, _col(theme, Role.BBOX, dim), theme)
    # Title bar: header text, separator, close glyph.
    tr = panel.title_rect
    _text_left(panel.title, tr, tr.x + 8.0, theme=theme,
               color=_col(theme, Role.HUD_HEADER, dim),
               size_token="hud_header")
    primitives.line((tr.x, tr.y), (tr.x2, tr.y),
                    color=_col(theme, Role.BBOX, dim),
                    width="default", theme=theme)
    _text_centered(CLOSE_GLYPH, panel.close_rect, theme=theme,
                   color=_col(theme, Role.HUD_LABEL, dim),
                   size_token="hud_header")


def draw_widget(context, widget):
    """Draw one widget panel into the current POST_PIXEL region. Resolves
    the theme per frame, lays out (storing hit rects on the panel), and
    renders chrome + controls. Out of context (widget.poll False): panel
    collapses to title bar + the hint message; only drag/close active."""
    theme = compute_layout(context, widget)
    panel = widget.panel
    in_context = _in_context(widget, context)
    dim = 1.0 if in_context else DISABLED_ALPHA

    with hud_text.isolated(theme):
        with draw_scope(blend="ALPHA"):
            _draw_chrome(panel, theme, dim)
            if not in_context:
                _text_centered(OUT_OF_CONTEXT_TEXT, panel.row_rects[0][0],
                               theme=theme,
                               color=_col(theme, Role.HUD_LABEL_INACTIVE,
                                          1.0))
                return
            press = getattr(widget, "_press_cell", None)
            editing = getattr(widget, "_editing", None)
            edit_where = editing[0] if editing else None
            edit_state = editing[1] if editing else None
            for r, control in enumerate(widget.rows(context)):
                cells = panel.row_rects[r]
                if isinstance(control, Row):
                    for c, child in enumerate(control.children):
                        _draw_control(child, cells[c], theme, dim,
                                      context, in_context,
                                      pressed=(press == (r, c)),
                                      edit=(edit_state
                                            if edit_where == (r, c) else None))
                else:
                    _draw_control(control, cells[0], theme, dim,
                                  context, in_context,
                                  pressed=(press == (r, 0)),
                                  edit=(edit_state
                                        if edit_where == (r, 0) else None))
            # Open dropdown list draws last so it sits on top of the panel.
            dd = getattr(widget, "_dropdown", None)
            if dd is not None:
                _draw_dropdown_list(dd, theme)
