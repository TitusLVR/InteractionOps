"""iOps Materials panel: list / gallery of materials, click to assign.

Docked in the N-panel (iOps tab) and callable as a popup through
iops.call_panel_materials. Previews come from UILayout.icon(), the lazy
call Blender's own material lists use: a missing preview starts a
background job, nothing renders inside draw(), and only drawn rows (the
visible list rows, the current gallery page) ask for one.
"""
import bpy

from ..operators.materials import common, state
from ..utils import materials_core as core

# Row info for the UIList, filled by filter_items() and read by draw_item()
# in the same redraw: {material key: core.Row}.
_ROW_INFO = {}


_ROWS_MEMO = {"key": None, "value": None}


def panel_rows(context):
    """(rows, {key: material}) for the current search / source / stacking.
    Memoized until the next depsgraph update / undo / load or a change of
    the inputs, so draw() and the UIList filter share one computation."""
    st = state.get_state(context)
    prefs = common.addon_prefs(context)
    memo_key = (state.generation(), st.search, st.source,
                prefs.materials_stack_duplicates, len(bpy.data.materials),
                context.scene.name, context.view_layer.name)
    if _ROWS_MEMO["key"] == memo_key:
        return _ROWS_MEMO["value"]
    value = _panel_rows(context, st, prefs)
    _ROWS_MEMO.update(key=memo_key, value=value)
    return value


def _panel_rows(context, st, prefs):
    in_source = state.source_keys(context, st.source)
    by_key = {}
    entries = []
    for mat in bpy.data.materials:
        key = common.material_key(mat)
        by_key[key] = mat
        entries.append((key, mat.name, key[1],
                        in_source is None or key in in_source))
    rows = core.build_rows(entries, st.search,
                           prefs.materials_stack_duplicates)
    return rows, by_key


def _assign_button(layout, mat, text, icon_value=0, depress=False,
                   emboss=True):
    op = layout.operator("iops.material_assign", text=text,
                         icon_value=icon_value, depress=depress,
                         emboss=emboss)
    op.material, op.library = common.material_key(mat)
    return op


class IOPS_UL_Materials(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data,
                  active_propname, index=0, flt_flag=0):
        mat = item
        key = common.material_key(mat)
        row_info = _ROW_INFO.get(key)
        text = row_info.display if row_info is not None else mat.name
        # split keeps the badge and the user count at the right edge
        row = layout.split(factor=0.7, align=True)
        name = row.row(align=True)
        name.alignment = "LEFT"
        _assign_button(name, mat, text, icon_value=layout.icon(mat),
                       emboss=False)
        right = row.row(align=True)
        right.alignment = "RIGHT"
        if row_info is not None and row_info.count > 1:
            badge = f"×{row_info.count}"
            if mat.library is None:
                op = right.operator("iops.materials_merge_duplicates",
                                    text=badge, emboss=False)
                op.base = row_info.base
            else:
                right.label(text=badge)
        if mat.library is not None:
            right.label(text="", icon="LINKED")
        users = common.real_users(mat)
        # user count as Blender shows it: a small button with the number;
        # a click selects the objects using the material
        count = right.row(align=True)
        # unused materials read dimmed, not as an alarm
        count.active = users > 0
        op = count.operator("iops.materials_select_users", text=str(users),
                            icon="USER")
        op.material, op.library = key

    def draw_filter(self, context, layout):
        # search and source live in the panel itself
        pass

    def filter_items(self, context, data, propname):
        mats = getattr(data, propname)
        rows, _by_key = panel_rows(context)
        shown = {r.key: r for r in rows}
        _ROW_INFO.clear()
        flags = []
        for mat in mats:
            key = common.material_key(mat)
            row = shown.get(key)
            if row is None:
                flags.append(0)
            else:
                flags.append(self.bitflag_filter_item)
                _ROW_INFO[key] = row
        return flags, []


class IOPS_OT_MaterialsGalleryPage(bpy.types.Operator):
    """Show the next or previous page of the gallery"""

    bl_idname = "iops.materials_gallery_page"
    bl_label = "Gallery Page"
    bl_options = {"INTERNAL"}

    delta: bpy.props.IntProperty(default=1)

    def execute(self, context):
        st = state.get_state(context)
        st.gallery_page = max(0, st.gallery_page + self.delta)
        common.tag_redraw(context)
        return {"FINISHED"}


def _width_units(panel, context):
    if panel.is_popover or context.region is None:
        return float(common.popup_width_units(context))
    scale = context.preferences.system.ui_scale or 1.0
    return context.region.width / (20.0 * scale)


def draw_gallery(panel, context, layout, rows, by_key):
    prefs = common.addon_prefs(context)
    st = state.get_state(context)
    size = prefs.materials_thumbnail_size
    columns = core.gallery_columns(_width_units(panel, context), size)
    per_page = columns * prefs.materials_gallery_rows
    start, stop, page, pages = core.page_slice(len(rows), per_page,
                                               st.gallery_page)
    active = state.active_material(context)
    grid = layout.grid_flow(row_major=True, columns=columns,
                            even_columns=True, even_rows=True, align=False)
    for row in rows[start:stop]:
        mat = by_key[row.key]
        cell = grid.column(align=True)
        cell.template_icon(icon_value=layout.icon(mat), scale=size)
        line = cell.row(align=True)
        _assign_button(line, mat, row.display, depress=(mat == active))
        if row.count > 1:
            # its own button, as in the list: merges the family
            badge = f"×{row.count}"
            if mat.library is None:
                line.operator("iops.materials_merge_duplicates",
                              text=badge).base = row.base
            else:
                line.label(text=badge)
    if pages > 1:
        nav = layout.row(align=True)
        sub = nav.row(align=True)
        sub.enabled = page > 0
        sub.operator("iops.materials_gallery_page", text="",
                     icon="TRIA_LEFT").delta = page - 1 - st.gallery_page
        nav.label(text=f"{page + 1} / {pages}")
        sub = nav.row(align=True)
        sub.enabled = page < pages - 1
        sub.operator("iops.materials_gallery_page", text="",
                     icon="TRIA_RIGHT").delta = page + 1 - st.gallery_page


class IOPS_MT_materials_functions(bpy.types.Menu):
    bl_label = "Material Functions"
    bl_idname = "IOPS_MT_materials_functions"

    def draw(self, context):
        layout = self.layout
        if ui_mode(context) == "IOPS_SHELF":
            # the shelf has no size buttons: here, or Ctrl+wheel over it
            layout.prop(common.addon_prefs(context),
                        "materials_shelf_thumbnail")
            layout.separator()
        layout.operator_context = "INVOKE_DEFAULT"
        layout.operator("iops.materials_merge_duplicates",
                        icon="AUTOMERGE_OFF")
        layout.separator()
        layout.operator("iops.materials_remap", text="Remap Materials...",
                        icon="UV_SYNC_SELECT")
        layout.operator("iops.materials_copy_from_active",
                        icon="COPYDOWN")
        layout.operator("iops.materials_select_users",
                        icon="RESTRICT_SELECT_OFF")
        layout.separator()
        layout.operator("iops.materials_remove_unused_slots",
                        icon="REMOVE")
        layout.operator("iops.materials_remove_empty_slots",
                        text="Remove Empty Slots (Selected)",
                        icon="REMOVE").scope = "SELECTED"
        layout.operator("iops.materials_remove_empty_slots",
                        text="Remove Empty Slots (Scene)",
                        icon="REMOVE").scope = "SCENE"
        layout.operator("iops.materials_clear",
                        text="Clear All Materials (Selected)",
                        icon="X").scope = "SELECTED"
        layout.operator("iops.materials_clear",
                        text="Clear All Materials (Scene)...",
                        icon="X").scope = "SCENE"
        layout.operator("iops.materials_delete_unused",
                        text="Delete Unused Materials...", icon="TRASH")
        layout.separator()
        layout.operator("iops.materials_mark_asset", icon="ASSET_MANAGER")
        layout.operator("iops.materials_clear_asset", icon="X")


def ui_mode(context):
    try:
        return common.addon_prefs(context).materials_ui_mode
    except (KeyError, AttributeError):
        return "PANEL"


class IOPS_PT_Materials_Panel(bpy.types.Panel):
    """Materials: click to assign, Alt+click for selected faces"""

    bl_label = "Materials"
    bl_idname = "IOPS_PT_Materials_Panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "iOps"
    bl_options = {"DEFAULT_CLOSED"}
    # popup width (wm.call_panel) until draw() applies the Popup Width
    # pref; the docked N-panel ignores both
    bl_ui_units_x = 12

    @classmethod
    def poll(cls, context):
        # Interface = Shelf: the asset shelf replaces the panel
        return ui_mode(context) == "PANEL"

    def draw(self, context):
        layout = self.layout
        st = state.get_state(context)
        prefs = common.addon_prefs(context)

        # popup header: the wm.call_panel popup has no header of its own
        if self.is_popover:
            layout.ui_units_x = common.popup_width_units(context)
            row = layout.row(align=True)
            row.scale_y = 0.5
            row.label(text=self.bl_label, icon="MATERIAL")
            grip = row.row(align=True)
            grip.alignment = "RIGHT"
            grip.label(text="", icon="GRIP")
            layout.separator(factor=0.3)

        row = layout.row()
        left = row.row(align=False)
        left.operator("iops.material_new", text="New", icon="ADD")
        # its own button: glued to New it read as a dropdown of New
        left.menu("IOPS_MT_materials_functions", text="",
                  icon="COLLAPSEMENU")
        right = row.row(align=True)
        right.alignment = "RIGHT"
        right.prop(st, "view", expand=True, icon_only=True)

        col = layout.column(align=True)
        col.prop(st, "search", text="", icon="VIEWZOOM")
        col.row(align=True).prop(st, "source", expand=True)

        # only when relevant: empty slots on the assignment targets
        empty = state.empty_slot_count(context)
        if empty:
            row = layout.row(align=True)
            row.alert = True
            row.label(text=core.plural(empty, "empty slot"), icon="ERROR")
            row.operator("iops.materials_remove_empty_slots",
                         text="Remove").scope = "SELECTED"

        if st.view == "GALLERY":
            rows, by_key = panel_rows(context)
            if not rows:
                layout.label(text="No materials", icon="INFO")
                return
            draw_gallery(self, context, layout, rows, by_key)
            return
        # the list is as tall as its rows, List Rows is the maximum
        visible = len(panel_rows(context)[0])
        layout.template_list("IOPS_UL_Materials", "", bpy.data, "materials",
                             st, "active_index",
                             rows=core.list_rows(visible,
                                                 prefs.materials_list_rows),
                             maxrows=prefs.materials_list_rows)


class IOPS_OT_Call_Materials_Panel(bpy.types.Operator):
    """Open the iOps Materials panel as a popup, or with Interface set to
    Shelf, show / hide the asset shelf of this 3D Viewport"""

    bl_idname = "iops.call_panel_materials"
    is_bindable = True
    bl_label = "IOPS Materials panel"

    @classmethod
    def poll(cls, context):
        return context.area is not None and context.area.type == "VIEW_3D"

    def execute(self, context):
        mode = ui_mode(context)
        if mode == "IOPS_SHELF":
            from .materials_shelf import toggle_visible
            toggle_visible(context)
            return {"FINISHED"}
        if mode == "LIBRARY_SHELF":
            space = context.space_data
            space.show_region_asset_shelf = not space.show_region_asset_shelf
            return {"FINISHED"}
        bpy.ops.wm.call_panel(name="IOPS_PT_Materials_Panel", keep_open=True)
        return {"FINISHED"}


UI_CLASSES = (
    IOPS_UL_Materials,
    IOPS_OT_MaterialsGalleryPage,
    IOPS_MT_materials_functions,
    IOPS_PT_Materials_Panel,
    IOPS_OT_Call_Materials_Panel,
)
