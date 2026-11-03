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
from .panel import (Rect, pen_icon, close_icon, GRID, grid_natural_content,
                    grid_cells)
from .editor_geom import HANDLE_W

# Layout constants (pixels). Heights derive from theme text sizes at
# layout time; these are paddings/insets around them.
PANEL_MIN_CONTENT_W = 180.0
DISABLED_ALPHA = 0.35
MIXED_FILL_ALPHA = 0.45
ROW_PAD_SECTION = 6.0
ROW_PAD_CONTROL = 10.0
GRID_COL_GAP = 6.0     # == WidgetPanel.layout's default col_gap
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
TITLE_BTN_INSET = 3.0       # title-bar buttons: outline inset from their cell
PEN_INSET = 6.0             # pen icon inset from the Edit cell
CLOSE_INSET = 7.0           # × strokes inset from the close cell
OUT_OF_CONTEXT_TEXT = "Go back to Edit Mode"
MIXED_TEXT = "<mixed>"
DROPDOWN_GLYPH = "▾"
CELL_INSET = 6.0            # horizontal text inset inside dropdown/input box
LABEL_INSET = 8.0           # total horizontal room kept free around a
                            # centered (button/preset/swatch) label
EMPTY_TEXT = "—"
DROPDOWN_ITEM_H = 22.0      # height of one open-dropdown list item (px)
SCROLL_UP_GLYPH = "▲"       # clipped-items hint at the list's top edge
SCROLL_DOWN_GLYPH = "▼"     # clipped-items hint at the list's bottom edge
NO_MATCH_TEXT = "(no match)"
CARET_GLYPH = "|"
INPUT_VALUE_MAX_W = 150.0   # cap the value text's contribution to panel width;
                            # longer values are middle-truncated on display
ELLIPSIS = "…"

# Edit mode (visual widget editor)
EDIT_TAG = "EDITING"
EDIT_TAG_GAP = 8.0          # gap between the tag and the title-bar buttons
EDIT_GRID_ALPHA = 0.25      # faint 12-step grid ticks under every row
EDIT_SPACER_ALPHA = 0.6     # dashed spacer outline
EDIT_SPACER_FILL = 0.12     # faint spacer fill (pre-mixed over the bg)
DASH_LEN = 4.0
DASH_GAP = 3.0
HIDDEN_GLYPH_W = 10.0       # "hidden" diamond-with-slash at a cell's right
EDGE_GRIP_H = 24.0          # panel right-edge (width) grip length, mid-height
PALETTE_TITLE = "Add"
PALETTE_GAP = 8.0           # gap between the palette and the edited panel
GHOST_PAD = 6.0


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
    counter stay visible. Returns `text` unchanged when it already fits,
    "" when not even the ellipsis fits (a cell narrower than any text).
    The one truncation rule for every label drawn inside a cell: grid
    cells keep their 12-step share even when narrower than their content
    (auto-fit width), so labels shorten instead of overflowing."""
    def m(s):
        return hud_text.measure(s, theme=theme, size_token=size_token)[0]
    if not text or m(text) <= max_w:
        return text
    if max_w < m(ELLIPSIS):
        return ""
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
def _row_height(control, theme, top_level=True):
    label_h = theme.text_size("hud_label")
    if control.kind == "spacer":
        # `height` only applies to top-level SPACER rows; cell stand-ins
        # share their row's height.
        h = getattr(control, "height", None)
        if top_level and h:
            return float(h)
        return label_h + ROW_PAD_CONTROL
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
        spans = _row_spans(control)
        if spans is not None:
            mins = [_control_min_width(c, theme, context)
                    for c in control.children]
            # Auto-fit: cells side by side at their natural widths; the
            # grid share they get may be narrower (labels truncate).
            return grid_natural_content(mins, GRID_COL_GAP)
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


def _row_spans(row):
    """Per-cell grid spans of a Row, or None for a legacy (hug/equal) row.
    A grid row has any child `_span`; unspanned stragglers share evenly."""
    kids = row.children
    if not any(getattr(c, "_span", None) is not None for c in kids):
        return None
    dflt = max(1, GRID // max(1, len(kids)))
    return [int(getattr(c, "_span", None) or dflt) for c in kids]


def _is_editing(widget):
    return getattr(widget, "_editor", None) is not None


def _poll(widget, context):
    """widget.poll guarded — a raising poll counts as out of context."""
    try:
        return bool(widget.poll(context))
    except Exception:
        return False


def _in_context(widget, context):
    if _is_editing(widget):
        return True    # edit mode shows every row regardless of poll
    return _poll(widget, context)


def _layout_rows(context, widget, th):
    """(rows spec for WidgetPanel.layout, auto-fit min content width of
    the rows). A top-level control with span < GRID contributes just its
    own natural min - it truncates inside its grid share."""
    rows = []
    if not _in_context(widget, context):
        rows.append((th.text_size("hud_label") + ROW_PAD_CONTROL, 1))
        return rows, hud_text.measure(OUT_OF_CONTEXT_TEXT, theme=th)[0] + 8.0
    controls = widget.rows(context)
    for control in controls:
        if isinstance(control, Row):
            height = max((_row_height(c, th, top_level=False)
                          for c in control.children),
                         default=_row_height(control, th))
            spans = _row_spans(control)
            if spans is not None:
                rows.append((height, control.columns, {"spans": spans}))
                continue
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
            sp = getattr(control, "_span", None)
            if sp is not None and sp < GRID:
                rows.append((_row_height(control, th), 1,
                             {"spans": [sp]}))
            else:
                rows.append((_row_height(control, th), 1))
    min_content = max((_control_min_width(c, th, context)
                       for c in controls), default=0.0)
    return rows, min_content


def _title_metrics(widget, th, editing=None):
    """(title_h, edit_w, content width the title bar needs). `editing`
    None = the widget's current state; False = as drawn outside edit mode
    (pen cell, no EDITING tag)."""
    title_h = th.text_size("hud_header") + TITLE_PAD
    # Edit button only for widgets with a JSON source on disk (composed);
    # Python-defined widgets have nothing to open.
    # No Edit button while editing: the EDITING tag takes its place.
    if editing is None:
        editing = _is_editing(widget)
    edit_w = title_h if (is_editable(widget) and not editing) else 0.0
    tag_w = (hud_text.measure(EDIT_TAG, theme=th)[0] + EDIT_TAG_GAP
             if editing else 0.0)
    need = (hud_text.measure(widget.panel.title, theme=th,
                             size_token="hud_header")[0]
            + title_h + edit_w + tag_w + 8.0)
    return title_h, edit_w, need


def content_min_width(context, widget, theme=None, saved=False):
    """Auto-fit content width of `widget`: the widest row's natural width
    and the title bar's needs, IGNORING the `width` floor and
    PANEL_MIN_CONTENT_W. Same rows/title rules as compute_layout.

    `saved=True` measures the title bar as it is drawn OUTSIDE edit mode
    (pen cell, no EDITING tag) — the lower bound of the edge drag, so the
    narrowest stored width is not inflated by the edit-only tag (edit
    mode may still render wider while editing)."""
    th = theme if theme is not None else get_theme(context)
    _rows, min_content = _layout_rows(context, widget, th)
    title = _title_metrics(widget, th, editing=False if saved else None)
    return max(title[2], min_content)


def _width_drag(widget):
    """Preview content width of an edge drag on this widget, or None."""
    session = getattr(widget, "_editor", None)
    drag = getattr(session, "drag", None) if session is not None else None
    if drag and drag.get("kind") == "width":
        return drag.get("width")
    return None


def compute_layout(context, widget, theme=None):
    """Compute row heights/content width from the theme and lay the panel
    out (clamped to the region). Returns the resolved theme. Safe to call
    from both the draw handler and the interact operator.

    Content width = max(floor, title needs, widest row's natural width);
    floor = the def's `width` if set, else PANEL_MIN_CONTENT_W. While the
    right edge is dragged in edit mode the preview width replaces the
    floor (no doc commit until release).

    Out of context the panel collapses to title bar + one message row, so
    hit rects match the collapsed draw."""
    th = theme if theme is not None else get_theme(context)
    rows, min_content = _layout_rows(context, widget, th)
    title_h, edit_w, title_need = _title_metrics(widget, th)
    floor_w = _width_drag(widget)
    if floor_w is None:
        floor_w = (getattr(widget, "min_content_w", None)
                   or PANEL_MIN_CONTENT_W)
    content_w = max(float(floor_w), title_need, min_content)
    layout_kw = dict(padding=float(th.hud.bg_padding), title_h=title_h,
                     row_gap=float(th.hud.row_spacing) + 2.0, edit_w=edit_w,
                     col_gap=GRID_COL_GAP)
    widget.panel.layout(rows, content_w, **layout_kw)
    region = context.region
    if region is not None:
        widget.panel.clamp_to_region(region.width, region.height,
                                     insets=region_insets(context))
        # Re-layout at the clamped anchor so rects match the final spot.
        widget.panel.layout(rows, content_w, **layout_kw)
    return th


def region_insets(context):
    """(left, right, top, bottom) pixels of the WINDOW region hidden under
    overlapping regions: with Region Overlap on, the sidebar (N-panel),
    the toolbar and the headers are drawn over the window region, so a
    panel clamped to the bare region size can sit under them."""
    area = getattr(context, "area", None)
    region = getattr(context, "region", None)
    if area is None or region is None or region.type != "WINDOW":
        return (0.0, 0.0, 0.0, 0.0)
    try:
        if not context.preferences.system.use_region_overlap:
            return (0.0, 0.0, 0.0, 0.0)
        space = area.spaces.active
    except (AttributeError, ReferenceError):
        return (0.0, 0.0, 0.0, 0.0)
    left = right = top = bottom = 0.0
    for reg in area.regions:
        try:
            if reg.type == "UI" and getattr(space, "show_region_ui", False):
                right = max(right, float(reg.width))
            elif reg.type == "TOOLS" and getattr(space, "show_region_toolbar", False):
                left = max(left, float(reg.width))
            elif reg.type == "HEADER" and getattr(space, "show_region_header", True):
                if reg.alignment == "BOTTOM":
                    bottom += float(reg.height)
                else:
                    top += float(reg.height)
            elif reg.type == "TOOL_HEADER" and getattr(space, "show_region_tool_header", True):
                if reg.alignment == "BOTTOM":
                    bottom += float(reg.height)
                else:
                    top += float(reg.height)
        except (AttributeError, ReferenceError):
            continue
    # Headers only overlap the window region when the region spans the
    # whole area; a window region shorter than the area already excludes them.
    if region.height + 1 < area.height:
        top = bottom = 0.0
    return (left, right, top, bottom)


def is_editable(widget):
    """True when the widget was built from a JSON definition (composed) —
    the only kind the title-bar Edit button can open in an editor."""
    return getattr(widget, "composed_def", None) is not None


# ----------------------------------------------------------------------
# Control draws
# ----------------------------------------------------------------------
def _draw_section(control, rect, theme, dim):
    color = _col(theme, Role.HUD_LABEL_INACTIVE, dim)
    _text_left(_truncate_middle(control.label, rect.w, theme), rect, rect.x,
               theme=theme, color=color)


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

    value_text = _truncate_middle(value_text, rect.w, theme)
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
        _text_centered(_truncate_middle(control.fmt.format(value),
                                        cell.w - LABEL_INSET, theme),
                       cell, theme=theme, color=label_color)


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
    _text_left(_truncate_middle(control.label, rect.x2 - (bx + box + 6.0),
                                theme),
               rect, bx + box + 6.0,
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
    _text_centered(_truncate_middle(control.label, rect.w - LABEL_INSET,
                                    theme),
                   rect, theme=theme, color=text_color)


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
        _text_centered(_truncate_middle(control.label,
                                        rect.w - LABEL_INSET, theme),
                       rect, theme=theme,
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
    shown = EMPTY_TEXT if value_text is None else value_text
    # Narrow cell: the label gives up room down to half the field, the
    # value gets the rest; both middle-truncate so neither overruns.
    room = rect.w - CELL_INSET * 3.0
    label = control.label or ""
    label_w, _ = hud_text.measure(label, theme=theme)
    value_w, _ = hud_text.measure(shown, theme=theme)
    if label_w + value_w > room:
        label = _truncate_middle(label, max(room - value_w, room * 0.5),
                                 theme)
        label_w, _ = hud_text.measure(label, theme=theme)
    _text_left(label, rect, rect.x + CELL_INSET,
               theme=theme, color=_col(theme, Role.HUD_LABEL, eff))
    # Value region = field minus the label and both insets; middle-truncate
    # so a long value never overruns the label / panel edge.
    avail = room - label_w
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
        _text_centered(_truncate_middle(label, cell.w - LABEL_INSET, theme),
                       cell, theme=theme, color=label_color)


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
def _draw_title_button(rect, theme, dim, pressed):
    """Shared chrome for title-bar buttons (Edit, Close): outlined square
    cell, tinted fill while held (set by the interact modal, cleared on
    release/cancel — same as action buttons). Returns the icon ink color.
    No hover state: that would need a MOUSEMOVE handler running for every
    mouse move in the editor."""
    btn = Rect(rect.x + TITLE_BTN_INSET, rect.y + TITLE_BTN_INSET,
               rect.w - TITLE_BTN_INSET * 2.0, rect.h - TITLE_BTN_INSET * 2.0)
    if pressed:
        primitives.rect_2d(btn.x, btn.y, btn.w, btn.h,
                           color=_active_fill(theme), theme=theme)
    _outline(btn, _col(theme, Role.BBOX, dim), theme)
    return _col(theme, Role.HUD_ACTIVE_VALUE if pressed else Role.HUD_LABEL,
                dim)


def _draw_edit_button(rect, theme, dim, pressed):
    """Title-bar Edit button: vector pen icon."""
    ink = _draw_title_button(rect, theme, dim, pressed)
    geo = pen_icon(rect, inset=PEN_INSET)
    primitives.tris(geo["tris"], color=ink, theme=theme)
    primitives.line(*geo["cap"], color=ink, width="default", theme=theme)


def _draw_close_button(rect, theme, dim, pressed):
    """Title-bar Close button: vector × (two diagonal strokes)."""
    ink = _draw_title_button(rect, theme, dim, pressed)
    for p1, p2 in close_icon(rect, inset=CLOSE_INSET):
        primitives.line(p1, p2, color=ink, width="default", theme=theme)


def _draw_chrome(panel, theme, dim, press=None, *, close=True, tag=None):
    b = panel.bounds()
    # Panel fill — the unified HUD background color (already sRGB-encoded
    # by get_theme), drawn even when the HUD bg toggle is off: an
    # interactive panel needs a readable hit surface.
    primitives.rect_2d(b.x, b.y, b.w, b.h,
                       color=theme.hud.bg_color, theme=theme)
    _outline(b, _col(theme, Role.BBOX, dim), theme)
    # Title bar: header text, separator, [Edit] and Close buttons.
    tr = panel.title_rect
    _text_left(panel.title, tr, tr.x + 8.0, theme=theme,
               color=_col(theme, Role.HUD_HEADER, dim),
               size_token="hud_header")
    primitives.line((tr.x, tr.y), (tr.x2, tr.y),
                    color=_col(theme, Role.BBOX, dim),
                    width="default", theme=theme)
    if tag:
        tw, _ = hud_text.measure(tag, theme=theme)
        _text_left(tag, tr, panel.edit_rect.x - EDIT_TAG_GAP - tw,
                   theme=theme, color=_col(theme, Role.HUD_ACTIVE_VALUE, 1.0))
    if close:
        _draw_close_button(panel.close_rect, theme, dim, press == "close")
    if panel.edit_rect.w > 0.0:
        _draw_edit_button(panel.edit_rect, theme, dim, press == "edit")


def _hidden(control, ectx):
    """True when the control's show_if is false in the current context."""
    from .predicates import eval_show_if
    return not eval_show_if(getattr(control, "_show_if", None), ectx)


def _tint(theme, role, t):
    """`role` color at strength `t` pre-mixed over the panel bg (the
    filled-tri shader doesn't honor low alphas reliably, see _active_fill)."""
    bg = theme.hud.bg_color
    hot = theme.color_for(role)
    return (bg[0] * (1.0 - t) + hot[0] * t,
            bg[1] * (1.0 - t) + hot[1] * t,
            bg[2] * (1.0 - t) + hot[2] * t,
            bg[3])


def _dashed_rect(rect, color, theme):
    """Rect outline as short dashes (one batched edges call)."""
    segs = []
    corners = ((rect.x, rect.y), (rect.x2, rect.y), (rect.x2, rect.y2),
               (rect.x, rect.y2), (rect.x, rect.y))
    step = DASH_LEN + DASH_GAP
    for (x0, y0), (x1, y1) in zip(corners, corners[1:]):
        length = abs(x1 - x0) + abs(y1 - y0)
        if length <= 0.0:
            continue
        ux, uy = (x1 - x0) / length, (y1 - y0) / length
        d = 0.0
        while d < length:
            e = min(d + DASH_LEN, length)
            segs.extend([(x0 + ux * d, y0 + uy * d),
                         (x0 + ux * e, y0 + uy * e)])
            d += step
    if segs:
        primitives.edges_3d(segs, color=color, width="default", theme=theme)


def _draw_hidden_glyph(rect, theme):
    """Small diamond with a slash at the cell's right: this control is
    hidden (show_if false) in the current context."""
    w = HIDDEN_GLYPH_W
    cx, cy = rect.x2 - w, rect.cy
    ink = _col(theme, Role.HUD_LABEL_INACTIVE, 1.0)
    hw, hh = w * 0.5, w * 0.35
    primitives.polyline([(cx - hw, cy), (cx, cy + hh), (cx + hw, cy),
                         (cx, cy - hh), (cx - hw, cy)],
                        color=ink, width="default", theme=theme)
    primitives.line((cx - hw, cy - hh), (cx + hw, cy + hh),
                    color=ink, width="default", theme=theme)


def _draw_edit_cell(control, rect, theme, hidden):
    """Edit-mode extras on one cell: spacer outline + placeholder text,
    hidden glyph."""
    if control.kind == "spacer":
        primitives.rect_2d(rect.x, rect.y, rect.w, rect.h,
                           color=_tint(theme, Role.HUD_LABEL_INACTIVE,
                                       EDIT_SPACER_FILL), theme=theme)
        _dashed_rect(rect, _col(theme, Role.HUD_LABEL_INACTIVE,
                                EDIT_SPACER_ALPHA), theme)
        label = getattr(control, "placeholder", "")
        if label:
            _text_centered(_truncate_middle(label, rect.w - LABEL_INSET,
                                            theme),
                           rect, theme=theme,
                           color=_col(theme, Role.HUD_STATS_ERROR, 1.0))
    if hidden:
        _draw_hidden_glyph(rect, theme)


def _edit_selection_rects(panel, controls, path):
    """(outline Rect, grip cell Rect | None) for the selected Path, or
    (None, None) when it doesn't resolve onto the current layout."""
    if path is None:
        return None, None
    r, c = path
    if not (0 <= r < len(panel.row_rects) and r < len(controls)):
        return None, None
    cells = panel.row_rects[r]
    if not cells:
        return None, None
    is_row = isinstance(controls[r], Row)
    if c is None:
        x0, x1 = cells[0].x, cells[-1].x2
        outline = Rect(x0, cells[0].y, x1 - x0, cells[0].h)
        return outline, (None if is_row else cells[0])
    if not (0 <= c < len(cells)):
        return None, None
    return cells[c], cells[c]


def _polyline_rect(rect, color, theme):
    pts = [(rect.x, rect.y), (rect.x2, rect.y), (rect.x2, rect.y2),
           (rect.x, rect.y2), (rect.x, rect.y)]
    primitives.polyline(pts, color=color, width="active", theme=theme)


def _draw_edit_overlays(panel, controls, theme, session):
    """Grid ticks, selection outline + resize grip, drop indicator."""
    # 12 faint grid ticks per row (batched into one call).
    cw = panel.width - panel.padding * 2.0
    cols = grid_cells([1] * GRID, cw, GRID_COL_GAP)
    ticks = []
    for cells in panel.row_rects:
        if not cells:
            continue
        y = cells[0].y
        for dx, _w in cols:
            x = panel.x + panel.padding + dx
            ticks.extend([(x, y), (x, y + TICK_H)])
    if ticks:
        primitives.edges_3d(ticks, color=_col(theme, Role.HUD_LABEL_INACTIVE,
                                              EDIT_GRID_ALPHA),
                            width="default", theme=theme)

    active = _col(theme, Role.HUD_ACTIVE_VALUE, 1.0)
    outline, grip = _edit_selection_rects(panel, controls,
                                          session.doc.selection)
    if outline is not None:
        _polyline_rect(outline, active, theme)
    if grip is not None:
        primitives.rect_2d(grip.x2 - HANDLE_W * 0.5, grip.y, HANDLE_W, grip.h,
                           color=active, theme=theme)

    # Panel right edge: short width grip mid-body (drag sets `width`),
    # or a full-height line while the edge is being dragged.
    drag = session.drag
    ex = panel.x + panel.width
    body_top = panel.y - panel.title_h
    body_bot = panel.y - panel.height
    if drag and drag.get("kind") == "width":
        primitives.line((ex, body_bot), (ex, body_top), color=active,
                        width="active", theme=theme)
    else:
        gh = min(EDGE_GRIP_H, max(0.0, body_top - body_bot))
        gy = (body_top + body_bot - gh) * 0.5
        primitives.rect_2d(ex - HANDLE_W * 0.5, gy, HANDLE_W, gh,
                           color=active, theme=theme)

    # Resize preview: the cell outline at the snapped span (events sets
    # drag["outline"] alongside drag["span"]).
    pre = drag.get("outline") if drag else None
    if pre:
        _polyline_rect(Rect(*pre), active, theme)
    ind = drag.get("indicator") if drag else None
    if ind:
        if ind[0] == "hline":
            _, x, y, w = ind
            p1, p2 = (x, y), (x + w, y)
        else:
            _, x, y, h = ind
            p1, p2 = (x, y), (x, y + h)
        primitives.line(p1, p2, color=active, width="active", theme=theme)


def draw_widget(context, widget):
    """Draw one widget panel into the current POST_PIXEL region. Resolves
    the theme per frame, lays out (storing hit rects on the panel), and
    renders chrome + controls. Out of context (widget.poll False): panel
    collapses to title bar + the hint message; only drag/close/edit
    active. While an edit session owns the widget every row is drawn, with
    show_if-hidden controls dimmed, plus the editor overlays."""
    theme = compute_layout(context, widget)
    panel = widget.panel
    in_context = _in_context(widget, context)
    dim = 1.0 if in_context else DISABLED_ALPHA
    session = getattr(widget, "_editor", None)
    editing = session is not None
    # Edit mode lays out every row regardless of poll, but controls read
    # live values only when the widget's own context is valid (an edge-
    # bound slider in Sculpt/Paint would otherwise hit bmesh.from_edit_mesh
    # and mute the widget); out of it they draw their cached value.
    live = _poll(widget, context) if editing else in_context

    with hud_text.isolated(theme):
        with draw_scope(blend="ALPHA"):
            press = getattr(widget, "_press_cell", None)
            _draw_chrome(panel, theme, dim, press=press,
                         tag=EDIT_TAG if editing else None)
            if not in_context:
                _text_centered(OUT_OF_CONTEXT_TEXT, panel.row_rects[0][0],
                               theme=theme,
                               color=_col(theme, Role.HUD_LABEL_INACTIVE,
                                          1.0))
                return
            editing_state = getattr(widget, "_editing", None)
            edit_where = editing_state[0] if editing_state else None
            edit_state = editing_state[1] if editing_state else None
            ectx = None
            if editing:
                from .predicates import build_eval_ctx
                ectx = build_eval_ctx(context,
                                      getattr(widget, "switches", None) or {})
            controls = widget.rows(context)
            for r, control in enumerate(controls):
                cells = panel.row_rects[r]
                row_hidden = editing and _hidden(control, ectx)
                if isinstance(control, Row):
                    for c, child in enumerate(control.children):
                        hid = row_hidden or (editing
                                             and _hidden(child, ectx))
                        _draw_control(child, cells[c], theme,
                                      dim * (DISABLED_ALPHA if hid else 1.0),
                                      context, live,
                                      pressed=(press == (r, c)),
                                      edit=(edit_state
                                            if edit_where == (r, c) else None))
                        if editing:
                            _draw_edit_cell(child, cells[c], theme, hid)
                else:
                    _draw_control(control, cells[0], theme,
                                  dim * (DISABLED_ALPHA if row_hidden else 1.0),
                                  context, live,
                                  pressed=(press == (r, 0)),
                                  edit=(edit_state
                                        if edit_where == (r, 0) else None))
                    if editing:
                        _draw_edit_cell(control, cells[0], theme, row_hidden)
            if editing:
                _polyline_rect(panel.bounds(),
                               _col(theme, Role.HUD_ACTIVE_VALUE, 1.0), theme)
                _draw_edit_overlays(panel, controls, theme, session)
            # Open dropdown list draws last so it sits on top of the panel.
            dd = getattr(widget, "_dropdown", None)
            if dd is not None:
                _draw_dropdown_list(dd, theme)


# ----------------------------------------------------------------------
# Add palette (edit mode)
# ----------------------------------------------------------------------
def compute_palette_layout(context, session, theme=None):
    """Lay out `session.palette` with exactly one visual row per
    `editor_geom.palette_items()` entry (headers included), so hit tests can
    zip rects with items. Default position: left of the edited widget at the
    same top y, clamped to the region; placed once (a later user move
    sticks). No Edit/Close buttons. Returns the resolved theme."""
    from .editor import PALETTE_W
    from .editor_geom import palette_items
    th = theme if theme is not None else get_theme(context)
    items = palette_items()
    label_h = th.text_size("hud_label")
    rows = [((label_h + ROW_PAD_CONTROL) if rtype
             else (label_h + ROW_PAD_SECTION), 1) for rtype, _l in items]
    title_h = th.text_size("hud_header") + TITLE_PAD
    widest = max((hud_text.measure(lbl, theme=th)[0] + 24.0
                  for rtype, lbl in items if rtype), default=0.0)
    content_w = max(
        widest, PALETTE_W - 16.0,
        hud_text.measure(PALETTE_TITLE, theme=th,
                         size_token="hud_header")[0] + 16.0)
    pal = session.palette
    pal.title = PALETTE_TITLE
    layout_kw = dict(padding=float(th.hud.bg_padding), title_h=title_h,
                     row_gap=float(th.hud.row_spacing) + 2.0, edit_w=0.0,
                     col_gap=GRID_COL_GAP)
    wp = session.widget.panel
    if not session.palette_placed and wp.width > 0.0:
        pal.x = wp.x - (content_w + layout_kw["padding"] * 2.0) - PALETTE_GAP
        pal.y = wp.y
        session.palette_placed = True
    pal.layout(rows, content_w, **layout_kw)
    region = context.region
    if region is not None:
        pal.clamp_to_region(region.width, region.height,
                            insets=region_insets(context))
        pal.layout(rows, content_w, **layout_kw)
    pal.close_rect = Rect()   # no close glyph: never hit-testable
    return th


def _draw_drag_ghost(drag, theme):
    ghost = drag.get("ghost") if drag else None
    if not ghost:
        return
    x, y, label = ghost
    w, _ = hud_text.measure(label, theme=theme)
    h = float(theme.text_size("hud_label")) + ROW_PAD_CONTROL
    box = Rect(x + 12.0, y - h - 4.0, w + GHOST_PAD * 2.0, h)
    primitives.rect_2d(box.x, box.y, box.w, box.h,
                       color=theme.hud.bg_color, theme=theme)
    active = _col(theme, Role.HUD_ACTIVE_VALUE, 1.0)
    _outline(box, active, theme)
    _text_centered(label, box, theme=theme, color=active)


def draw_palette(context, session):
    """Draw the floating "Add" palette (and the drag ghost on top) for the
    edit session. Call after the widgets so it sits above them."""
    from .editor_geom import palette_items
    theme = compute_palette_layout(context, session)
    pal = session.palette
    with hud_text.isolated(theme):
        with draw_scope(blend="ALPHA"):
            _draw_chrome(pal, theme, 1.0, close=False)
            line = _col(theme, Role.LINE, 1.0)
            label = _col(theme, Role.HUD_LABEL, 1.0)
            hint = _col(theme, Role.HUD_LABEL_INACTIVE, 1.0)
            for (rtype, text), cells in zip(palette_items(), pal.row_rects):
                rect = cells[0]
                if not rtype:
                    _text_left(text, rect, rect.x, theme=theme, color=hint)
                else:
                    _outline(rect, line, theme)
                    _text_centered(text, rect, theme=theme, color=label)
            _draw_drag_ghost(session.drag, theme)
