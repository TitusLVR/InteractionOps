"""Prefs "Widgets" tab — compose GPU widgets from the known block palette.

Source of truth is the JSON files in `presets/IOPS/widgets/` (see
widgets/composed.py). The CollectionProperty here is a UI mirror: it is
rebuilt from the files via `sync_from_files()` and every edit immediately
writes the selected widget's file back and re-registers the live widget
(`autosave_selected()`). The `_SYNC` flag stops the rebuild from
re-triggering the update callbacks.

Built-in (Python) widgets appear in the list read-only with a lock icon —
"Duplicate" turns them into an editable JSON copy.
"""
import json

import bpy
from bpy.props import (BoolProperty, CollectionProperty, EnumProperty,
                       FloatProperty, IntProperty, StringProperty)
from bpy.types import PropertyGroup, UIList

_SYNC = False

_ROW_TYPE_ITEMS = [
    ("SECTION", "Section", "Non-interactive section label"),
    ("SLIDER", "Slider", "Drag slider bound to an edge attribute"),
    ("PRESETS", "Presets", "Absolute-value preset buttons"),
    ("FLIPBOX", "Flip Box", "Checkbox bound to an edge flag (adjacent "
                            "flip boxes share one panel row)"),
    ("BUTTON", "Button", "Fires an operator"),
]
_ROW_TYPE_ICONS = {
    "SECTION": "REMOVE",
    "SLIDER": "DRIVER_DISTANCE",
    "PRESETS": "PRESET",
    "FLIPBOX": "CHECKBOX_HLT",
    "BUTTON": "PLAY",
}
_FLOAT_TARGET_ITEMS = [
    ("BEVEL", "Bevel Weight", "Edge bevel weight attribute"),
    ("CREASE", "Crease", "Edge crease attribute"),
]
_BOOL_TARGET_ITEMS = [
    ("SHARP", "Sharp", "Edge sharp flag"),
    ("SEAM", "Seam", "UV seam flag"),
    ("FREESTYLE", "Freestyle", "Freestyle edge mark"),
]
_ROLE_ITEMS = [
    ("default", "Default", "Standard button colors"),
    ("error", "Error", "Destructive action (theme error color)"),
]


def get_prefs():
    return bpy.context.preferences.addons["InteractionOps"].preferences


def _autosave(self, context):
    if not _SYNC:
        autosave_selected()


def _on_rename(self, context):
    if not _SYNC:
        rename_selected()


class IOPS_WidgetRowItem(PropertyGroup):
    type: EnumProperty(name="Type", items=_ROW_TYPE_ITEMS,
                       default="SECTION", update=_autosave)
    label: StringProperty(name="Label", default="", update=_autosave)
    target_float: EnumProperty(name="Target", items=_FLOAT_TARGET_ITEMS,
                               default="BEVEL", update=_autosave)
    target_bool: EnumProperty(name="Target", items=_BOOL_TARGET_ITEMS,
                              default="SHARP", update=_autosave)
    snap: FloatProperty(name="Snap", default=0.125, min=0.0, max=1.0,
                        precision=3,
                        description="Slider snap increment (Ctrl = smooth); "
                                    "0 disables snapping",
                        update=_autosave)
    values: StringProperty(name="Values", default="0, 0.25, 0.5, 1.0",
                           description="Comma-separated preset values (0..1)",
                           update=_autosave)
    op: StringProperty(name="Operator", default="",
                       description="Operator idname, e.g. iops.executor",
                       update=_autosave)
    op_kwargs: StringProperty(name="Arguments", default="{}",
                              description="Operator keyword arguments as "
                                          "JSON, e.g. {\"script\": \"...\"}",
                              update=_autosave)
    role: EnumProperty(name="Role", items=_ROLE_ITEMS, default="default",
                       update=_autosave)

    def summary(self):
        t = self.type
        if t == "SECTION":
            return self.label or "(section)"
        if t == "SLIDER":
            return f"Slider — {self.target_float.title()}"
        if t == "PRESETS":
            return f"Presets — {self.target_float.title()}  [{self.values}]"
        if t == "FLIPBOX":
            return f"Flip — {self.label or self.target_bool.title()}"
        return f"Button — {self.label or self.op}"


class IOPS_WidgetDefItem(PropertyGroup):
    name: StringProperty(name="Name", default="widget", update=_on_rename)
    # Previous on-disk name — lets a rename move the file and lets the
    # rename callback revert edits on built-ins.
    stored_name: StringProperty(default="", options={"HIDDEN"})
    title: StringProperty(name="Title", default="", update=_autosave)
    builtin: BoolProperty(default=False)
    rows: CollectionProperty(type=IOPS_WidgetRowItem)
    rows_index: IntProperty(default=0)


class IOPS_UL_WidgetDefs(UIList):
    def draw_item(self, context, layout, data, item, icon, active_data,
                  active_propname, index):
        row = layout.row(align=True)
        if item.builtin:
            row.label(text=item.name, icon="LOCKED")
        else:
            row.prop(item, "name", text="", emboss=False)


class IOPS_UL_WidgetRows(UIList):
    def draw_item(self, context, layout, data, item, icon, active_data,
                  active_propname, index):
        layout.label(text=item.summary(),
                     icon=_ROW_TYPE_ICONS.get(item.type, "DOT"))


# ----------------------------------------------------------------------
# Collection <-> definition dict
# ----------------------------------------------------------------------
def row_item_to_def(item):
    t = item.type
    if t == "SECTION":
        return {"type": t, "label": item.label}
    if t == "SLIDER":
        return {"type": t, "target": item.target_float, "snap": item.snap}
    if t == "PRESETS":
        from ..widgets.composed import parse_values
        return {"type": t, "target": item.target_float,
                "values": parse_values(item.values)}
    if t == "FLIPBOX":
        return {"type": t, "target": item.target_bool, "label": item.label}
    try:
        kwargs = json.loads(item.op_kwargs or "{}")
    except ValueError:
        kwargs = {}
    return {"type": t, "label": item.label, "op": item.op,
            "op_kwargs": kwargs if isinstance(kwargs, dict) else {},
            "role": item.role}


def item_to_def(item):
    from ..widgets.composed import SCHEMA_VERSION
    return {
        "version": SCHEMA_VERSION,
        "name": item.name,
        "title": item.title or item.name,
        "space": "VIEW_3D",
        "rows": [row_item_to_def(r) for r in item.rows],
    }


def def_to_item(item, wdef, builtin=False):
    item.name = wdef["name"]
    item.stored_name = wdef["name"]
    item.title = wdef.get("title", "")
    item.builtin = builtin
    item.rows.clear()
    for row in wdef.get("rows", []):
        r = item.rows.add()
        r.type = row["type"]
        t = row["type"]
        if t == "SECTION":
            r.label = row.get("label", "")
        elif t in ("SLIDER", "PRESETS"):
            r.target_float = row.get("target", "BEVEL")
            if t == "SLIDER":
                r.snap = float(row.get("snap", 0.125))
            else:
                r.values = ", ".join(f"{v:g}" for v in row.get("values", []))
        elif t == "FLIPBOX":
            r.target_bool = row.get("target", "SHARP")
            r.label = row.get("label", "")
        else:
            r.label = row.get("label", "")
            r.op = row.get("op", "")
            r.op_kwargs = json.dumps(row.get("op_kwargs", {}))
            r.role = row.get("role", "default")


# ----------------------------------------------------------------------
# Sync + autosave
# ----------------------------------------------------------------------
def builtin_defs():
    """Definition mirrors of the Python widgets (currently edge_data) —
    used for the read-only list entries, Duplicate and Export."""
    from ..widgets.composed import EDGE_DATA_DEF
    return {"edge_data": EDGE_DATA_DEF}


def sync_from_files(select=None):
    """Rebuild the prefs collection: built-ins first, then one entry per
    valid definition file. Keeps (or sets) the selection by name."""
    global _SYNC
    import os
    from ..widgets import composed
    try:
        prefs = get_prefs()
    except (KeyError, AttributeError):
        return
    keep = select
    if keep is None and 0 <= prefs.widget_defs_index < len(prefs.widget_defs):
        keep = prefs.widget_defs[prefs.widget_defs_index].name
    _SYNC = True
    try:
        prefs.widget_defs.clear()
        for wdef in builtin_defs().values():
            item = prefs.widget_defs.add()
            def_to_item(item, wdef, builtin=True)
        for fn in composed.list_widget_files():
            path = os.path.join(composed.widgets_folder(), fn)
            wdef, _errors = composed.load_def(path)
            if wdef is None:
                continue
            item = prefs.widget_defs.add()
            def_to_item(item, wdef)
        idx = next((i for i, it in enumerate(prefs.widget_defs)
                    if it.name == keep), 0)
        prefs.widget_defs_index = idx
    finally:
        _SYNC = False


def selected_item():
    try:
        prefs = get_prefs()
    except (KeyError, AttributeError):
        return None
    if 0 <= prefs.widget_defs_index < len(prefs.widget_defs):
        return prefs.widget_defs[prefs.widget_defs_index]
    return None


def autosave_selected():
    """Write the selected (editable) widget's JSON and refresh the live
    registered widget. Called from every row/title update callback —
    edits only ever happen on the selected entry."""
    item = selected_item()
    if item is None or item.builtin:
        return
    from ..widgets import composed
    wdef, _errors = composed.validate_def(item_to_def(item))
    if wdef is None:
        return
    composed.save_def(wdef)
    composed.register_composed(wdef)
    _redraw_views()


def rename_selected():
    """Sanitize + unique-ify the new name, move the definition file, and
    re-register under the new name. Built-ins revert silently."""
    global _SYNC
    item = selected_item()
    if item is None:
        return
    from ..widgets import composed
    if item.builtin:
        _SYNC = True
        try:
            item.name = item.stored_name
        finally:
            _SYNC = False
        return
    prefs = get_prefs()
    taken = {it.name for it in prefs.widget_defs if it != item}
    taken.update(builtin_defs())
    new = composed.unique_name(
        composed.sanitize_name(item.name) or "widget", taken)
    old = item.stored_name
    if new != item.name:
        _SYNC = True
        try:
            item.name = new
        finally:
            _SYNC = False
    if old and old != new:
        from ..ui.widgets import state
        state.hide_widget(old)
        composed.unregister_composed(old)
        composed.delete_def(old)
    item.stored_name = new
    autosave_selected()


def _redraw_views():
    wm = getattr(bpy.context, "window_manager", None)
    if wm is None:
        return
    for window in wm.windows:
        for area in window.screen.areas:
            if area.type == "VIEW_3D":
                area.tag_redraw()


# ----------------------------------------------------------------------
# Tab draw (called from addon_preferences.draw)
# ----------------------------------------------------------------------
def draw_widgets_tab(layout, context, prefs):
    main = layout.row()

    # Left: widget list + manage column
    left = main.column()
    left.label(text="Widgets")
    row = left.row()
    row.template_list("IOPS_UL_WidgetDefs", "", prefs, "widget_defs",
                      prefs, "widget_defs_index", rows=6)
    ops = row.column(align=True)
    ops.operator("iops.widget_def_add", text="", icon="ADD")
    ops.operator("iops.widget_def_duplicate", text="", icon="DUPLICATE")
    ops.operator("iops.widget_def_remove", text="", icon="REMOVE")
    ops.separator()
    ops.operator("iops.widget_def_import", text="", icon="IMPORT")
    ops.operator("iops.widget_def_export", text="", icon="EXPORT")
    ops.separator()
    ops.operator("iops.widgets_open_folder", text="", icon="FILE_FOLDER")

    item = selected_item()
    if item is None:
        return

    # Right: selected widget editor
    right = main.column()
    if item.builtin:
        box = right.box()
        box.label(text="Built-in widget — Duplicate to edit", icon="LOCKED")
        box.label(text=f'Summon: iops.widget_toggle(name="{item.name}")',
                  icon="INFO")
        return

    right.prop(item, "title")
    right.label(text="Rows")
    row = right.row()
    row.template_list("IOPS_UL_WidgetRows", "", item, "rows",
                      item, "rows_index", rows=8)
    ops = row.column(align=True)
    ops.operator_menu_enum("iops.widget_row_add", "type", text="",
                           icon="ADD")
    ops.operator("iops.widget_row_remove", text="", icon="REMOVE")
    ops.separator()
    ops.operator("iops.widget_row_move", text="",
                 icon="TRIA_UP").direction = "UP"
    ops.operator("iops.widget_row_move", text="",
                 icon="TRIA_DOWN").direction = "DOWN"

    if not (0 <= item.rows_index < len(item.rows)):
        return
    sel = item.rows[item.rows_index]
    box = right.box()
    box.prop(sel, "type")
    t = sel.type
    if t == "SECTION":
        box.prop(sel, "label")
    elif t == "SLIDER":
        box.prop(sel, "target_float")
        box.prop(sel, "snap")
    elif t == "PRESETS":
        box.prop(sel, "target_float")
        box.prop(sel, "values")
    elif t == "FLIPBOX":
        box.prop(sel, "target_bool")
        box.prop(sel, "label")
    elif t == "BUTTON":
        box.prop(sel, "label")
        box.prop(sel, "op")
        box.prop(sel, "op_kwargs")
        box.prop(sel, "role")
    right.label(text=f'Summon: iops.widget_toggle(name="{item.name}")',
                icon="INFO")


classes = (
    IOPS_WidgetRowItem,
    IOPS_WidgetDefItem,
    IOPS_UL_WidgetDefs,
    IOPS_UL_WidgetRows,
)
