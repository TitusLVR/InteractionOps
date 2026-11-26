"""iOps material shelf: a strip along the bottom of the 3D Viewport drawn
by the addon in the iOps theme, with the Materials panel's rows and tools.

Shown when Preferences > iOps > Materials > Interface is Shelf. Pieces:
- draw.py       POST_PIXEL draw handler: strip, tools, cells, drag ghost
- thumbs.py     GPU textures from material previews (lazy, cached)
- highlight.py  POST_VIEW draw handler: faces of the hovered material and
                the drop target while dragging
- events.py     input: addon "3D View" keymap entries (LMB / RMB press,
                wheel, mouse move) call iops.material_shelf_event, whose
                invoke hit-tests and PASS_THROUGHs outside the shelf; a
                press inside starts a modal that lives for one gesture
                (click, drag-and-drop, resize) — the widget framework's
                input contract (ui/widgets/events.py), no long-running modal

Layout and hit-testing are pure (utils/materials_shelf_core.py); the rows
come from the panel's panel_rows() and shared state, so panel and shelf
never diverge.
"""
import bpy

from ...operators.materials import common
from ...utils import materials_shelf_core as core

# session state, not saved: shelf visibility (one switch for every 3D
# View), scroll per area, hover and drag
STATE = {
    "visible": True,
    "scroll": {},        # area pointer -> scroll px
    "hover": None,       # (area pointer, cell index, hit kind)
    "hover_key": None,   # material key of the hovered cell
    "hover_since": 0.0,  # time the hover target last changed
    "drag": None,        # dict while a cell is dragged
}

def mode_ok(context):
    mode = context.mode
    return mode == "OBJECT" or mode.startswith("EDIT")


def shelf_enabled(context=None):
    try:
        prefs = common.addon_prefs(context)
    except (KeyError, AttributeError):
        return False
    return prefs.materials_ui_mode == "IOPS_SHELF"


def shelf_active(context):
    return STATE["visible"] and shelf_enabled(context) and mode_ok(context)


def shelf_region(area):
    """The WINDOW region the shelf lives in: the only one, or in quad view
    the bottom-right one (the camera / user view of the 2 x 2 split)."""
    best = None
    for region in area.regions:
        if region.type != "WINDOW":
            continue
        if best is None or (region.x, -region.y) > (best.x, -best.y):
            best = region
    return best


def ui_scale(context):
    return context.preferences.system.ui_scale or 1.0


_SIDE = {"TOOLS": "LEFT", "UI": "RIGHT", "HEADER": None, "TOOL_HEADER": None,
         "ASSET_SHELF": "BOTTOM", "ASSET_SHELF_HEADER": "BOTTOM"}


def region_insets(context, area, region):
    """(left, right, top, bottom) px of `region` hidden under other regions
    of the area (toolbar, sidebar, headers, asset shelf) that overlap it,
    from their actual rectangles: correct with Region Overlap on or off
    and for each region of a quad view."""
    left = right = top = bottom = 0.0
    rx0, ry0 = region.x, region.y
    rx1, ry1 = rx0 + region.width, ry0 + region.height
    for reg in area.regions:
        if reg == region or reg.type not in _SIDE:
            continue
        if reg.width <= 1 or reg.height <= 1:
            continue        # hidden
        x0, y0 = reg.x, reg.y
        x1, y1 = x0 + reg.width, y0 + reg.height
        if x1 <= rx0 or x0 >= rx1 or y1 <= ry0 or y0 >= ry1:
            continue        # no overlap
        side = _SIDE[reg.type] or reg.alignment
        if side == "LEFT":
            left = max(left, float(x1 - rx0))
        elif side == "RIGHT":
            right = max(right, float(rx1 - x0))
        elif side == "TOP":
            top = max(top, float(ry1 - y0))
        elif side == "BOTTOM":
            bottom = max(bottom, float(y1 - ry0))
    return (left, right, top, bottom)


def compute(context, area, region, show_empty=None):
    """(layout, rows, by_key) of the shelf in `region` now."""
    from ..iops_materials_panel import panel_rows
    from ...operators.materials import state
    prefs = common.addon_prefs(context)
    rows, by_key = panel_rows(context)
    if show_empty is None:
        show_empty = state.empty_slot_count(context) > 0
    key = area.as_pointer()
    lay = core.compute_layout(
        region.width, region.height, region_insets(context, area, region),
        # the height pref is in pixels at 1.0 resolution scale
        prefs.materials_shelf_height * ui_scale(context),
        prefs.materials_shelf_thumbnail,
        len(rows), STATE["scroll"].get(key, 0), ui_scale(context),
        show_empty, prefs.materials_shelf_tools_direction,
        prefs.materials_shelf_tools_position)
    STATE["scroll"][key] = lay.scroll
    return lay, rows, by_key


def tag_redraw_all(context=None):
    wm = bpy.context.window_manager
    if wm is None:
        return
    for window in wm.windows:
        screen = window.screen
        if screen is None:
            continue
        for area in screen.areas:
            if area.type == "VIEW_3D":
                area.tag_redraw()


def toggle_visible(context):
    STATE["visible"] = not STATE["visible"]
    STATE["hover"] = STATE["hover_key"] = None
    tag_redraw_all(context)
    return STATE["visible"]


def register():
    from . import draw, events, highlight, thumbs
    draw.register()
    highlight.register()
    thumbs.register()
    events.register_keymap()


def unregister():
    from . import draw, events, highlight, thumbs
    events.unregister_keymap()
    thumbs.unregister()
    highlight.unregister()
    draw.unregister()
    STATE.update(scroll={}, hover=None, hover_key=None, drag=None)


def classes():
    from . import events
    return events.CLASSES
