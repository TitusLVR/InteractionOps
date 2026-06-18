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
from .controls import Row, pixel_from_value, preset_cell_rects
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
PRESET_GAP = 4.0
TICK_H = 4.0
MAX_TICKS = 32
CLOSE_GLYPH = "×"
OUT_OF_CONTEXT_TEXT = "Go back to Edit Mode"
MIXED_TEXT = "<mixed>"


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


# ----------------------------------------------------------------------
# Layout
# ----------------------------------------------------------------------
def _row_height(control, theme):
    label_h = theme.text_size("hud_label")
    if control.kind == "section":
        return label_h + ROW_PAD_SECTION
    if control.kind == "swatch":
        return label_h * SWATCH_HEIGHT_FACTOR + ROW_PAD_CONTROL
    return label_h + ROW_PAD_CONTROL


def _control_min_width(control, theme):
    """Content width a control needs to render without clipping."""
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
    if control.kind == "row":
        n = max(1, len(control.children))
        widest = max((_control_min_width(c, theme)
                      for c in control.children), default=0.0)
        return widest * n + 6.0 * (n - 1)
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
        for control in widget.rows():
            if isinstance(control, Row):
                height = max((_row_height(c, th) for c in control.children),
                             default=_row_height(control, th))
                rows.append((height, control.columns))
            else:
                rows.append((_row_height(control, th), 1))
        min_content = max((_control_min_width(c, th) for c in widget.rows()),
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
        # Active-press feedback: fill with the checkbox/active-value color
        # at 25% opacity while the button is held down (set by the interact
        # modal; cleared on release/cancel).
        primitives.rect_2d(rect.x, rect.y, rect.w, rect.h,
                           color=_col(theme, Role.HUD_ACTIVE_VALUE,
                                      eff * 0.25),
                           theme=theme)
    if control.role == "error":
        line_color = _col(theme, Role.ERROR_LINE, eff)
        text_color = _col(theme, Role.HUD_STATS_ERROR, eff)
    else:
        line_color = _col(theme, Role.LINE, eff)
        text_color = _col(theme, Role.HUD_LABEL, eff)
    _outline(rect, line_color, theme)
    _text_centered(control.label, rect, theme=theme, color=text_color)


def _draw_swatch(control, rect, theme, dim, context, live):
    value, _ = control.value(context) if live else control.cached()
    disabled = (value is None) or not control.enabled
    eff = dim * (DISABLED_ALPHA if disabled else 1.0)
    if value is not None:
        # subtype=COLOR props are scene-linear; encode to sRGB to match the
        # native color field. Force opaque fill so a low-alpha stored color
        # is still visible (alpha is not part of the swatch's job here).
        enc = _srgb_encode(value)
        primitives.rect_2d(rect.x + SWATCH_INSET, rect.y + SWATCH_INSET,
                           rect.w - SWATCH_INSET * 2.0, rect.h - SWATCH_INSET * 2.0,
                           color=(enc[0], enc[1], enc[2], 1.0), theme=theme)
    # Outline/label carry the disabled fade; the fill stays readable.
    _outline(rect, _col(theme, Role.LINE, eff), theme)
    if control.label:
        _text_centered(control.label, rect, theme=theme,
                       color=_col(theme, Role.HUD_LABEL, eff))


def _draw_control(control, rect, theme, dim, context, live, pressed=False):
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
            for r, control in enumerate(widget.rows()):
                cells = panel.row_rects[r]
                if isinstance(control, Row):
                    for c, child in enumerate(control.children):
                        _draw_control(child, cells[c], theme, dim,
                                      context, in_context,
                                      pressed=(press == (r, c)))
                else:
                    _draw_control(control, cells[0], theme, dim,
                                  context, in_context,
                                  pressed=(press == (r, 0)))
