import bpy
from bpy.types import Menu
from ..operators.mesh_nonplanar_overlay import overlay_enabled as nonplanar_overlay_enabled
from ..operators.mesh_zfight_overlay import overlay_enabled as zfight_overlay_enabled
from ..operators.mesh_hidden_faces_overlay import overlay_enabled as hidden_faces_overlay_enabled
from ..operators.object_negative_scale_overlay import overlay_enabled as negative_scale_overlay_enabled
from .iops_pie_groups import GROUP_COLUMNS, SLOTS, VERTEX_COLOR, groups_for_mode
from .iops_tm_panel import draw_vertex_paint_buttons

# Toggle operators: the button is drawn pressed while the overlay is on.
DEPRESS_STATE = {
    "iops.mesh_nonplanar_overlay": nonplanar_overlay_enabled,
    "iops.mesh_zfight_overlay": zfight_overlay_enabled,
    "iops.mesh_hidden_faces_overlay": hidden_faces_overlay_enabled,
    "iops.object_negative_scale_overlay": negative_scale_overlay_enabled,
}

# Addon preferences drawn as fields on the same row, right of the button.
BESIDE_PREF = {
    "iops.mesh_zfight_overlay": ("zfight_in_front",),
    "iops.mesh_hidden_faces_overlay": ("hidden_faces_rays", "hidden_faces_in_front"),
}
# Width of a number field and of a checkbox with its label, in UI units.
_BESIDE_PREF_WIDTH = 4.5
_BESIDE_CHECKBOX_WIDTH = 3.5

# Diagonal pie slots overlap the side columns, so the diagonal groups are
# drawn as extra columns of the top / bottom panel instead.
_PANEL_COLUMNS = {
    "LEFT": ("LEFT",),
    "RIGHT": ("RIGHT",),
    "TOP": ("TOP_LEFT", "TOP", "TOP_RIGHT", "TOP_FAR_RIGHT"),
    "BOTTOM": ("BOTTOM_LEFT", "BOTTOM", "BOTTOM_RIGHT"),
}

_VERTEX_COLOR_OPS = (
    "iops.mesh_assign_vertex_color",
    "iops.mesh_assign_vertex_color_alpha",
    "iops.mesh_vertex_paint",
    "iops.mesh_vertex_color_filter",
)
# Width of the Vertex Color column, in UI units: the color swatch and the
# palette row would otherwise stretch it to twice the other panels.
_VERTEX_COLOR_WIDTH = 9.0
# Most button rows one column of a group may have before it is split in two.
_MAX_ROWS = 8
# Half-height, in button rows, a side panel may have before it reaches the
# top and bottom panels (measured at the default pie radius).
_FREE_HALF_ROWS = 5.0


def op_polls(idname):
    """True when the operator is registered and its poll() passes now."""
    module, _, func = idname.partition(".")
    try:
        return bool(getattr(getattr(bpy.ops, module), func).poll())
    except AttributeError:
        return False


def op_if_poll(layout, idname, text=None, icon=None, depress=None, **props):
    """Draw an operator button only when its poll() passes in the current context.

    Returns the operator properties object (like layout.operator) or None
    when the button was hidden (poll failed or operator is not registered).
    `depress` is a layout argument (drawn pressed), not an operator property.
    """
    if not op_polls(idname):
        return None
    kwargs = {}
    if text is not None:
        kwargs["text"] = text
    if icon is not None:
        kwargs["icon"] = icon
    if depress is not None:
        kwargs["depress"] = depress
    btn = layout.operator(idname, **kwargs)
    for key, value in props.items():
        setattr(btn, key, value)
    return btn


def visible_rows(group):
    """Rows of a group with the entries whose operator polls now."""
    if group[1] == VERTEX_COLOR:
        return [op for op in _VERTEX_COLOR_OPS if op_polls(op)]
    rows = [[e for e in row if op_polls(e[0])] for row in group[1]]
    return [row for row in rows if row]


def _column_count(group, rows):
    """Button columns of a group: its fixed count, else two when it is over
    the row limit (a tall column runs into the neighbouring panels)."""
    count = GROUP_COLUMNS.get(group[0], 2 if len(rows) > _MAX_ROWS else 1)
    return max(1, min(count, len(rows)))


def _side_overreach(groups):
    """Button rows by which the taller side panel reaches past the free
    space next to the top / bottom panels; those are padded away by it."""
    tallest = 0
    for key in ("LEFT", "RIGHT"):
        group = groups.get(key)
        if group is None or group[1] == VERTEX_COLOR:
            continue
        rows = visible_rows(group)
        if rows:
            tallest = max(tallest, -(-len(rows) // _column_count(group, rows)))
    return max(0.0, (tallest + 1) / 2 - _FREE_HALF_ROWS)


def _pad(col, rows):
    """Blank spacer, `rows` button rows tall."""
    if rows > 0:
        spacer = col.column()
        spacer.scale_y = rows
        spacer.label(text="")


def draw_group(col, group):
    """Title and buttons of one group into `col`; hidden buttons are skipped."""
    col.label(text=group[0])
    rows = visible_rows(group)
    count = _column_count(group, rows)
    if count > 1:
        per = -(-len(rows) // count)
        split = col.row(align=True)
        parts = [(split.column(align=True), rows[i:i + per])
                 for i in range(0, len(rows), per)]
    else:
        parts = [(col, rows)]
    for target, part in parts:
        for row in part:
            for cell, (idname, text, props) in zip(_even_cells(target, len(row)), row):
                state = DEPRESS_STATE.get(idname)
                names = BESIDE_PREF.get(idname, ())
                target_line = cell.row(align=True) if names else cell
                btn = op_if_poll(target_line, idname, text=text,
                                 depress=state() if state else None, **props)
                if btn is not None:
                    for name in names:
                        _draw_beside_pref(target_line, name)


def _draw_beside_pref(line, name):
    """Addon preference `name` as a narrow field at the end of `line`: a
    checkbox with its label for a bool, a number field otherwise."""
    addon = bpy.context.preferences.addons.get("InteractionOps")
    prefs = getattr(addon, "preferences", None)
    if prefs is None or not hasattr(prefs, name):
        return
    is_bool = isinstance(getattr(prefs, name), bool)
    field = line.row(align=True)
    field.ui_units_x = _BESIDE_CHECKBOX_WIDTH if is_bool else _BESIDE_PREF_WIDTH
    field.prop(prefs, name)


def _even_cells(layout, count):
    """`count` equal-width cells side by side. A plain row sizes buttons by
    their text, so two-button rows would not line up into columns."""
    if count <= 1:
        return [layout]
    cells = []
    rest = layout
    for remaining in range(count, 1, -1):
        split = rest.split(factor=1.0 / remaining, align=True)
        cells.append(split.column(align=True))
        rest = split.column(align=True)
    cells.append(rest)
    return cells


def draw_vertex_color(col, context):
    """Vertex Color group: set color / alpha, the paint brush, Blur / Sharpen.
    Parts whose operator does not poll are hidden."""
    col.ui_units_x = _VERTEX_COLOR_WIDTH
    col.label(text="Vertex Color")
    if op_polls("iops.mesh_assign_vertex_color"):
        col.prop(context.scene.IOPS, "iops_vertex_color", text="")
        row = col.row(align=True)
        op_if_poll(row, "iops.mesh_assign_vertex_color", text="Set Color")
        op_if_poll(row, "iops.mesh_assign_vertex_color_alpha", text="Set Alpha")
        row = col.row(align=True)
        op_if_poll(row, "iops.mesh_assign_vertex_color", text="White", fill_color_white=True)
        op_if_poll(row, "iops.mesh_assign_vertex_color", text="Grey", fill_color_grey=True)
        op_if_poll(row, "iops.mesh_assign_vertex_color", text="Black", fill_color_black=True)
    else:
        op_if_poll(col, "iops.mesh_assign_vertex_color_alpha", text="Set Alpha")
    if op_polls("iops.mesh_vertex_paint"):
        draw_vertex_paint_buttons(col)
    row = col.row(align=True)
    op_if_poll(row, "iops.mesh_vertex_color_filter", text="Blur", mode="BLUR")
    op_if_poll(row, "iops.mesh_vertex_color_filter", text="Sharpen", mode="SHARPEN")


def draw_panel(pie, context, groups, pad_above=0.0, pad_below=0.0):
    """One pie slot: a box with a column per group that has something to
    show. With nothing to show the slot gets pie.separator() and False is
    returned, so the slots after it keep their place. The pads move the
    panel away from the pie center."""
    shown = [g for g in groups if g is not None and visible_rows(g)]
    if not shown:
        pie.separator()
        return False
    outer = pie.column()
    _pad(outer, pad_above)
    row = outer.box().row()
    _pad(outer, pad_below)
    for group in shown:
        col = row.column(align=True)
        if group[1] == VERTEX_COLOR:
            draw_vertex_color(col, context)
        else:
            draw_group(col, group)
    return True


class IOPS_MT_Pie_Menu(Menu):
    # bl_idname = "iops.pie_menu"
    bl_label = "IOPS Pie"

    def draw(self, context):
        pie = self.layout.menu_pie()
        groups = groups_for_mode(context.mode)
        # Every slot is emitted, in Blender's fill order, so an empty panel
        # never shifts the ones after it.
        reach = _side_overreach(groups)
        for slot in SLOTS:
            columns = _PANEL_COLUMNS.get(slot)
            if columns is None:
                pie.separator()
                continue
            pads = {}
            if slot == "TOP":
                pads["pad_below"] = reach
            elif slot == "BOTTOM":
                pads["pad_above"] = reach
            draw_panel(pie, context, [groups.get(key) for key in columns], **pads)


class IOPS_OT_Call_Pie_Menu(bpy.types.Operator):
    """IOPS Pie"""

    bl_idname = "iops.call_pie_menu"
    is_bindable = True
    bl_label = "IOPS Pie Menu"

    def execute(self, context):
        bpy.ops.wm.call_menu_pie(name="IOPS_MT_Pie_Menu")
        return {"FINISHED"}
