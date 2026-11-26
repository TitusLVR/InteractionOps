"""POST_PIXEL drawing of the iOps material shelf: strip, tool cluster,
cells (preview, name, duplicate and user badges, active / hover marks),
scroll bar and the drag ghost. Everything goes through ui/draw primitives
and HUD text in theme roles."""
import time

import bpy
import gpu

from ...operators.materials import common, state
from ...utils import materials_shelf_core as core
from ...utils import materials_shelf_glyphs as glyphs
from ..draw import Role, draw_scope, get_theme, primitives, \
    safe_handler_add, safe_handler_remove
from ..hud import text as hud_text
from . import STATE, compute, shelf_active, shelf_region, thumbs

TOKEN = "hud_label"
_HANDLE = {"pixel": None}



def _icon(name, r, theme, color, scale):
    """Stroke glyph `name` (utils/materials_shelf_glyphs.py) into button
    `r`: hairlines of about 1 px at 1.0 UI scale, anti-aliased."""
    width = max(1.0, scale)
    inset = round(2 * scale)
    bx, by = round(r.x + inset), round(r.y + inset)
    bs = round(r.w - 2 * inset)
    lines, curves, dots = glyphs.strokes(name, segments=max(16, int(bs)))
    for poly in lines:
        primitives.polyline(glyphs.fit(poly, bx, by, bs), color=color,
                            width=width, theme=theme)
    for poly in curves:
        primitives.polyline(glyphs.fit(poly, bx, by, bs, snap=False),
                            color=color, width=width, theme=theme)
    for cx, cy, rad in dots:
        ring = glyphs.circle_points(cx, cy, rad, 12)[:-1]
        c = (bx + cx * bs, by + cy * bs)
        tris = []
        for i in range(len(ring)):
            p, q = ring[i], ring[(i + 1) % len(ring)]
            tris += [c, (bx + p[0] * bs, by + p[1] * bs),
                     (bx + q[0] * bs, by + q[1] * bs)]
        primitives.tris(tris, color=color, theme=theme)


def _blend():
    # text drawing leaves the blend state off; everything here is translucent
    gpu.state.blend_set("ALPHA")


def _frame(r, color, theme, t=1.0):
    """A crisp frame of `t` pixels, drawn as four thin rects (GPU lines of
    the theme's widths read too heavy on a UI strip)."""
    t = max(1.0, round(t))
    primitives.rect_2d(r.x, r.y, r.w, t, color=color, theme=theme)
    primitives.rect_2d(r.x, r.y + r.h - t, r.w, t, color=color, theme=theme)
    primitives.rect_2d(r.x, r.y + t, t, r.h - 2 * t, color=color, theme=theme)
    primitives.rect_2d(r.x + r.w - t, r.y + t, t, r.h - 2 * t, color=color,
                       theme=theme)


def _alpha(color, a):
    return tuple(color[:3]) + (a,)


def _mix(a, b, t):
    return tuple(a[i] * (1.0 - t) + b[i] * t for i in range(3)) + (a[3],)


def _text_in(text, r, theme, color, align="center", pad=4):
    from ..widgets.render import _truncate_middle
    if not text:
        return
    text = _truncate_middle(text, max(0, r.w - 2 * pad), theme, TOKEN)
    w, _ = hud_text.measure(text, theme=theme, size_token=TOKEN)
    cap = hud_text.measure("X", theme=theme, size_token=TOKEN)[1]
    x = r.x + (r.w - w) / 2 if align == "center" else r.x + pad
    hud_text.draw(text, int(x), int(r.y + (r.h - cap) / 2), theme=theme,
                  color=color, size_token=TOKEN)
    _blend()


def _plate(r, theme, *, on=False, hot=False, alert=False):
    """Borderless button background: a faint fill, a soft accent plate on
    hover, a slightly stronger one when on. No outlines."""
    bg = theme.hud.bg_color
    accent = theme.color_for(Role.ERROR_LINE if alert else
                             Role.HUD_ACTIVE_VALUE)
    if on:
        fill = _alpha(_mix(bg, accent, 0.45), 0.6)
    elif hot:
        fill = _alpha(_mix(bg, accent, 0.25), 0.55)
    else:
        # just enough to read as a button over any scene
        fill = _alpha(theme.color_for(Role.HUD_LABEL), 0.08)
    primitives.rect_2d(r.x, r.y, r.w, r.h, color=fill, theme=theme)


def _badge(r, text, theme, color, hot=False):
    bg = theme.hud.bg_color
    fill = _mix(bg, theme.color_for(Role.HUD_ACTIVE_VALUE), 0.3 if hot else 0.0)
    primitives.rect_2d(r.x, r.y, r.w, r.h,
                       color=_alpha(fill, 0.7 if hot else 0.45), theme=theme)
    _text_in(text, r, theme, color, pad=1)


def _draw_tools(context, lay, theme, hover_tool):
    st = state.get_state(context)
    label = theme.color_for(Role.HUD_LABEL)
    accent = theme.color_for(Role.HUD_ACTIVE_VALUE)
    for name, r in lay.tools.items():
        hot = name == hover_tool
        if name == "empty":
            alert = theme.color_for(Role.HUD_STATS_ERROR)
            _plate(r, theme, hot=hot, alert=True)
            _blend()
            _icon(name, r, theme, alert, lay.scale)
            n = state.empty_slot_count(context)
            _small_text(core.short_count(n), r, theme, alert, lay.scale)
            continue
        if name.startswith("src_"):
            on = st.source == name[4:]
        elif name == "search":
            on = bool(st.search)
        else:
            on = False
        _plate(r, theme, on=on, hot=hot)
        _blend()
        _icon(name, r, theme, accent if on or hot else label, lay.scale)


def _small_text(text, r, theme, color, scale):
    size = max(7, int(round(9 * scale)))
    w, _ = hud_text.measure(text, theme=theme, size_px=size)
    cap = hud_text.measure("8", theme=theme, size_px=size)[1]
    hud_text.draw(text, int(r.x + (r.w - w) / 2 + 0.5),
                  int(r.y + (r.h - cap) / 2 + 0.5), theme=theme, color=color,
                  size_px=size)
    _blend()


def _draw_tooltip(context, lay, theme, name):
    from .events import TOOLTIP_DELAY
    if time.monotonic() - STATE.get("hover_since", 0.0) < TOOLTIP_DELAY:
        return
    r = lay.tools.get(name)
    if r is None:
        return
    st = state.get_state(context)
    text = core.tooltip_text(name, st.source, st.search,
                             state.empty_slot_count(context))
    if not text:
        return
    w, _ = hud_text.measure(text, theme=theme, size_token=TOKEN)
    cap = hud_text.measure("X", theme=theme, size_token=TOKEN)[1]
    pad = 5 * lay.scale
    region = context.region
    tip = core.tooltip_rect(r, w + 2 * pad, cap + 2 * pad, region.width,
                            region.height)
    # the HUD background darkened: the plain HUD grey can equal the
    # viewport's, which leaves the tooltip without a visible plate
    plate = _mix(theme.hud.bg_color, (0.0, 0.0, 0.0, 1.0), 0.45)
    primitives.rect_2d(tip.x, tip.y, tip.w, tip.h, color=_alpha(plate, 0.92),
                       theme=theme)
    _frame(tip, _alpha(theme.color_for(Role.HUD_LABEL), 0.14), theme,
           lay.scale)
    hud_text.draw(text, int(tip.x + pad), int(tip.y + pad), theme=theme,
                  color=theme.color_for(Role.HUD_LABEL), size_token=TOKEN)
    _blend()


def _draw_cells(context, lay, rows, by_key, theme, hover):
    active = state.active_material(context)
    label = theme.color_for(Role.HUD_LABEL)
    dim = theme.color_for(Role.HUD_LABEL_INACTIVE)
    accent = theme.color_for(Role.HUD_ACTIVE_VALUE)
    hover_index, hover_kind = hover if hover else (None, None)
    thumbs.begin_draw()
    for cell in lay.cells:
        row = rows[cell.index]
        mat = by_key.get(row.key)
        if mat is None:
            continue
        t = cell.thumb
        is_hover = cell.index == hover_index
        if is_hover or mat == active:
            # a soft plate behind the preview instead of a heavy outline
            primitives.rect_2d(t.x, t.y, t.w, t.h,
                               color=_alpha(accent, 0.16 if mat == active
                                            else 0.09), theme=theme)
        tex = thumbs.texture(mat)
        _blend()
        if tex is not None:
            primitives.image_2d(tex, t.x, t.y, t.w, t.h)
        else:
            primitives.rect_2d(t.x, t.y, t.w, t.h,
                               color=_alpha(label, 0.06), theme=theme)
        if mat == active:
            _frame(t, _alpha(accent, 0.9), theme, lay.scale)
        _text_in(row.display, cell.name, theme,
                 accent if mat == active else label)
        if row.count > 1:
            _badge(cell.dup, f"×{row.count}", theme, label,
                   hot=is_hover and hover_kind == "dup")
        users = common.real_users(mat)
        _badge(cell.users, core.short_count(users), theme,
               dim if users <= 0 else label,
               hot=is_hover and hover_kind == "users")


def _draw_scrollbar(lay, theme):
    if lay.max_scroll <= 0:
        return
    g = lay.grid
    total = lay.content_h
    h = max(8 * lay.scale, g.h * g.h / total)
    y = g.y + g.h - h - (g.h - h) * (lay.scroll / lay.max_scroll)
    x = g.x + g.w + 1 * lay.scale
    primitives.rect_2d(x, y, core.SCROLLBAR_W * lay.scale * 0.6, h,
                       color=_alpha(
                           theme.color_for(Role.HUD_LABEL_INACTIVE), 0.6),
                       theme=theme)


def _draw_ghost(context, theme):
    drag = STATE["drag"]
    if not drag or not drag.get("active"):
        return
    region = context.region
    x = drag["x"] - region.x
    y = drag["y"] - region.y
    if not (0 <= x < region.width and 0 <= y < region.height):
        return
    size = 48 * (context.preferences.system.ui_scale or 1.0)
    mat = common.find_material(*drag["key"])
    r = core.Rect(x + 12, y - size - 12, size, size)
    tex = thumbs.texture(mat) if mat is not None else None
    _blend()
    if tex is not None:
        primitives.image_2d(tex, r.x, r.y, r.w, r.h)
    else:
        _frame(r, _alpha(theme.color_for(Role.HUD_ACTIVE_VALUE), 0.9), theme)
    if mat is not None:
        hint = mat.name + ("  (face)" if drag.get("alt") else "")
        _text_in(hint, core.Rect(r.x, r.y - 18, 240, 16), theme,
                 theme.color_for(Role.HUD_LABEL), align="left", pad=0)


def _draw_pixel():
    context = bpy.context
    area = context.area
    region = context.region
    if area is None or region is None or not shelf_active(context):
        return
    if shelf_region(area) != region:
        return
    theme = get_theme(context)
    try:
        lay, rows, by_key = compute(context, area, region)
    except (KeyError, AttributeError, ReferenceError):
        return
    hover = STATE["hover"]
    hover_here = None
    hover_tool = None
    if hover is not None and hover[0] == area.as_pointer():
        if hover[2] == "tool":
            hover_tool = hover[1]
        else:
            hover_here = (hover[1], hover[2])
    with draw_scope(blend="ALPHA"):
        # the strip itself is transparent: previews, names and buttons
        # float over the viewport
        grip_w = 40 * lay.scale
        e = lay.edge
        grip_color = theme.color_for(Role.HUD_ACTIVE_VALUE if hover_tool ==
                                     "resize" else Role.HUD_LABEL_INACTIVE)
        primitives.rect_2d(e.x + (e.w - grip_w) / 2, e.y + e.h / 2,
                           grip_w, max(1.0, round(lay.scale)),
                           color=_alpha(grip_color, 0.8), theme=theme)
        _draw_tools(context, lay, theme, hover_tool)
        if not rows:
            _text_in("No materials", lay.grid, theme,
                     theme.color_for(Role.HUD_LABEL_INACTIVE))
        _draw_cells(context, lay, rows, by_key, theme, hover_here)
        _draw_scrollbar(lay, theme)
        if hover_tool not in (None, "resize") and not STATE["drag"]:
            _draw_tooltip(context, lay, theme, hover_tool)
        _draw_ghost(context, theme)


def register():
    if _HANDLE["pixel"] is None:
        _HANDLE["pixel"] = safe_handler_add(
            bpy.types.SpaceView3D, _draw_pixel, (), "WINDOW", "POST_PIXEL")


def unregister():
    if _HANDLE["pixel"] is not None:
        safe_handler_remove(_HANDLE["pixel"], bpy.types.SpaceView3D, "WINDOW")
        _HANDLE["pixel"] = None


def handler_installed():
    return _HANDLE["pixel"] is not None
