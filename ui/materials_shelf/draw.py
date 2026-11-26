"""POST_PIXEL drawing of the iOps material shelf: strip, tool cluster,
cells (preview, name, duplicate and user badges, active / hover marks),
scroll bar and the drag ghost. Everything goes through ui/draw primitives
and HUD text in theme roles."""
import bpy

from ...operators.materials import common, state
from ...utils import materials_core as mcore
from ...utils import materials_shelf_core as core
from ..draw import Role, draw_scope, get_theme, primitives, \
    safe_handler_add, safe_handler_remove
from ..hud import text as hud_text
from . import STATE, compute, shelf_active, shelf_region, thumbs

TOKEN = "hud_label"
_HANDLE = {"pixel": None}

TOOL_TEXT = {
    "new": "New", "functions": "Functions", "src_SCENE": "Scene",
    "src_SELECTED": "Selected", "src_FILE": "File", "size_down": "−",
    "size_up": "+",
}


def _outline(r, color, theme, width="default"):
    pts = [(r.x, r.y), (r.x + r.w, r.y), (r.x + r.w, r.y + r.h),
           (r.x, r.y + r.h), (r.x, r.y)]
    primitives.polyline(pts, color=color, width=width, theme=theme)


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


def _button(r, text, theme, *, on=False, hot=False, alert=False):
    bg = theme.hud.bg_color
    accent = theme.color_for(Role.HUD_ACTIVE_VALUE)
    if on or hot:
        primitives.rect_2d(r.x, r.y, r.w, r.h,
                           color=_mix(bg, accent, 0.35 if on else 0.18),
                           theme=theme)
    line = theme.color_for(Role.ERROR_LINE if alert else Role.LINE)
    _outline(r, line, theme)
    color = theme.color_for(Role.HUD_STATS_ERROR if alert else
                            (Role.HUD_ACTIVE_VALUE if on else Role.HUD_LABEL))
    _text_in(text, r, theme, color)


def _badge(r, text, theme, color, hot=False):
    bg = theme.hud.bg_color
    fill = _mix(bg, theme.color_for(Role.HUD_ACTIVE_VALUE), 0.3 if hot else 0.0)
    primitives.rect_2d(r.x, r.y, r.w, r.h, color=fill[:3] + (0.85,),
                       theme=theme)
    _text_in(text, r, theme, color, pad=1)


def _draw_tools(context, lay, theme, hover_tool):
    st = state.get_state(context)
    prefs = common.addon_prefs(context)
    for name, r in lay.tools.items():
        hot = name == hover_tool
        if name.startswith("src_"):
            _button(r, TOOL_TEXT[name], theme, on=st.source == name[4:],
                    hot=hot)
        elif name == "search":
            text = st.search or "Search"
            _button(r, text, theme, on=bool(st.search), hot=hot)
        elif name == "size_label":
            _text_in(f"{prefs.materials_shelf_thumbnail} px", r, theme,
                     theme.color_for(Role.HUD_LABEL_INACTIVE))
        elif name == "empty":
            n = state.empty_slot_count(context)
            _button(r, f"{mcore.plural(n, 'empty slot')}  Remove", theme,
                    alert=True, hot=hot)
        else:
            _button(r, TOOL_TEXT[name], theme, hot=hot)


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
        tex = thumbs.texture(mat)
        if tex is not None:
            primitives.image_2d(tex, t.x, t.y, t.w, t.h)
        else:
            primitives.rect_2d(t.x, t.y, t.w, t.h,
                               color=_mix(theme.hud.bg_color, label, 0.12),
                               theme=theme)
        is_hover = cell.index == hover_index
        if mat == active:
            _outline(t, theme.color_for(Role.ACTIVE_LINE), theme, "active")
        elif is_hover:
            _outline(t, accent, theme)
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
                       color=theme.color_for(Role.HUD_LABEL_INACTIVE),
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
    if tex is not None:
        primitives.image_2d(tex, r.x, r.y, r.w, r.h)
    _outline(r, theme.color_for(Role.ACTIVE_LINE), theme, "active")
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
        s = lay.shelf
        bg = theme.hud.bg_color
        # the theme's HUD background, at least 85 % opaque so cells stay
        # readable over the scene
        primitives.rect_2d(s.x, s.y, s.w, s.h,
                           color=bg[:3] + (max(bg[3], 0.85),), theme=theme)
        grip_w = 40 * lay.scale
        e = lay.edge
        grip_color = theme.color_for(Role.HUD_ACTIVE_VALUE if hover_tool ==
                                     "resize" else Role.HUD_LABEL_INACTIVE)
        primitives.rect_2d(e.x + (e.w - grip_w) / 2, e.y + e.h / 2 - 1,
                           grip_w, 2 * lay.scale, color=grip_color,
                           theme=theme)
        _draw_tools(context, lay, theme, hover_tool)
        if not rows:
            _text_in("No materials", lay.grid, theme,
                     theme.color_for(Role.HUD_LABEL_INACTIVE))
        _draw_cells(context, lay, rows, by_key, theme, hover_here)
        _draw_scrollbar(lay, theme)
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
