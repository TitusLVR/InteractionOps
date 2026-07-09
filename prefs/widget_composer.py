"""Prefs "Widgets" tab — the widget list + per-widget toggle hotkeys.

Source of truth is the JSON files in `presets/IOPS/widgets/` (see
widgets/composed.py) — edited by hand (Open Folder button) or via
Import/Duplicate. The CollectionProperty here is a UI mirror rebuilt from
the files via `sync_from_files()`; renaming in the list moves the file
and re-registers the live widget. The `_SYNC` flag stops the rebuild from
re-triggering the update callbacks.

Each list row also draws the widget's toggle hotkey (the user-keyconfig
`iops.widget_toggle` entry kept in sync by ui/widgets/events.py
sync_toggle_kmis()) as a key-capture field.

All widgets are JSON-composed (loaded from the library folder); every
list row is editable.
"""
import bpy
from bpy.props import (BoolProperty, CollectionProperty, EnumProperty,
                       FloatProperty, StringProperty)
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
    # Operate on the edited item itself — the list lets any row's name be
    # edited, not just the active one.
    if not _SYNC:
        rename_item(self)


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

class IOPS_WidgetDefItem(PropertyGroup):
    name: StringProperty(name="Name", default="widget", update=_on_rename)
    # Previous on-disk name — lets a rename move the file.
    stored_name: StringProperty(default="", options={"HIDDEN"})
    title: StringProperty(name="Title", default="", update=_autosave)
    builtin: BoolProperty(default=False)
    rows: CollectionProperty(type=IOPS_WidgetRowItem)


class IOPS_UL_WidgetDefs(UIList):
    def draw_item(self, context, layout, data, item, icon, active_data,
                  active_propname, index):
        from ..ui.widgets import events
        # Two equal columns (name | hotkey) with a divider line between —
        # matches the header drawn in draw_widgets_tab.
        row = layout.row(align=False)
        name = row.row()
        name.prop(item, "name", text="", emboss=False)
        row.separator(type="LINE")
        key = row.row()
        _km, kmi = events.find_user_toggle_kmi(item.name)
        if kmi is not None:
            key.prop(kmi, "type", text="", full_event=True)
        else:
            key.label(text="—")


# ----------------------------------------------------------------------
# Collection <-> definition dict
# ----------------------------------------------------------------------
def item_to_def(item):
    """The widget's on-disk definition, re-keyed to the list item's
    current name/title. The JSON file is the source of truth — the prefs
    list no longer mirrors row contents (the in-prefs row editor was
    removed and the schema now has shapes the flat row mirror can't hold,
    e.g. ROW groups and RNA-prop flipboxes), so Duplicate/Export/autosave
    read the file rather than reconstructing from a stale mirror. Returns
    None when the file is missing/unreadable."""
    from ..widgets import composed
    src = item.stored_name or item.name
    wdef, _errors = composed.load_def(composed.widget_path(src))
    if wdef is None:
        return None
    wdef["name"] = item.name
    wdef["title"] = item.title or item.name
    return wdef


def def_to_item(item, wdef, builtin=False):
    # Only the identity fields are mirrored into the prefs list; row
    # contents live in the JSON file (see item_to_def).
    item.name = wdef["name"]
    item.stored_name = wdef["name"]
    item.title = wdef.get("title", "")
    item.builtin = builtin


# ----------------------------------------------------------------------
# Sync + autosave
# ----------------------------------------------------------------------
def sync_from_files(select=None):
    """Rebuild the prefs collection: one entry per valid definition file.
    Keeps (or sets) the selection by name."""
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
    # Every list mutation routes through here — keep the per-widget
    # toggle hotkey entries matched to the registry.
    from ..ui.widgets import events
    events.sync_toggle_kmis()


def selected_item():
    try:
        prefs = get_prefs()
    except (KeyError, AttributeError):
        return None
    if 0 <= prefs.widget_defs_index < len(prefs.widget_defs):
        return prefs.widget_defs[prefs.widget_defs_index]
    return None


def autosave_item(item):
    """Write one (editable) widget's JSON and refresh the live registered
    widget."""
    if item is None or item.builtin:
        return
    from ..widgets import composed
    wdef, _errors = composed.validate_def(item_to_def(item))
    if wdef is None:
        return
    composed.save_def(wdef)
    composed.register_composed(wdef)
    _redraw_views()


def autosave_selected():
    autosave_item(selected_item())


def rename_item(item):
    """Sanitize + unique-ify the new name, move the definition file, and
    re-register under the new name."""
    global _SYNC
    if item is None:
        return
    from ..widgets import composed
    prefs = get_prefs()
    taken = {it.name for it in prefs.widget_defs if it != item}
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
        from ..ui.widgets import state, events
        # Move the definition on disk: load the old file, re-key, save it
        # under the new name, then drop the old widget + file. The JSON
        # file is the source of truth (the prefs list mirrors only name/
        # title), so we never reconstruct rows from the list.
        wdef, _errors = composed.load_def(composed.widget_path(old))
        if wdef is not None:
            wdef["name"] = new
            wdef["title"] = wdef.get("title", new)
            composed.save_def(wdef)
            composed.register_composed(wdef)
        state.hide_widget(old)
        composed.unregister_composed(old)
        composed.delete_def(old)
        # Re-point the toggle hotkey entry so the assigned key follows
        # the rename instead of resetting to unbound.
        events.rename_toggle_kmi(old, new)
    item.stored_name = new


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
    # Widgets library folder (executor-parity).
    box = layout.box()
    box.label(text="Widgets Folder:", icon="FILE_FOLDER")
    box.prop(prefs, "widgets_use_script_path_user")
    if prefs.widgets_use_script_path_user:
        import bpy
        box.label(text=bpy.utils.script_path_user())
        box.prop(prefs, "widgets_subfolder")
    else:
        box.prop(prefs, "widgets_folder")
    # Popup operator + its hotkey (bindable op in the addon "Window"
    # keymap). Draw the user-keyconfig entry so a rebind persists in
    # userpref.blend, same as the per-widget toggle fields.
    kc = context.window_manager.keyconfigs.user
    km = kc.keymaps.get("Window") if kc is not None else None
    kmi = None
    if km is not None:
        kmi = next((k for k in km.keymap_items
                    if k.idname == "iops.scripts_call_widgets_panel"), None)
    box.separator()
    # One row, two equal columns + divider — mirrors the widget-list rows
    # below (name | hotkey), so the popup reads as the "all widgets" entry
    # with its own toggle key.
    row = box.row(align=False)
    btn = row.row()
    btn.operator("iops.scripts_call_widgets_panel",
                 text="All Widgets Panel", icon="MENU_PANEL")
    row.separator(type="LINE")
    key = row.row()
    if kmi is not None:
        key.prop(kmi, "type", text="", full_event=True)
    else:
        key.label(text="—")

    layout.separator(type="LINE")
    col = layout.column()
    col.label(text="Widget Library:")
    # Column header — two equal columns with a divider, mirroring the
    # list rows (IOPS_UL_WidgetDefs.draw_item).
    head = col.row(align=False)
    h_name = head.row()
    h_name.label(text="Widget")
    head.separator(type="LINE")
    h_key = head.row()
    h_key.label(text="Toggle Hotkey")
    # List + a divider + the (square, icon-only) manage buttons. The
    # template_list is a direct child of the row so it expands and the
    # button column shrinks to icon width.
    body = col.row(align=False)
    body.template_list("IOPS_UL_WidgetDefs", "", prefs, "widget_defs",
                       prefs, "widget_defs_index", rows=8)
    body.separator(type="LINE")
    ops = body.column(align=True)
    ops.operator("iops.widget_def_add", text="", icon="ADD")
    ops.operator("iops.widget_def_duplicate", text="", icon="DUPLICATE")
    ops.operator("iops.widget_def_remove", text="", icon="REMOVE")
    ops.separator()
    ops.operator("iops.widget_def_import", text="", icon="IMPORT")
    ops.operator("iops.widget_def_export", text="", icon="EXPORT")
    ops.separator()
    ops.operator("iops.widgets_open_folder", text="", icon="FILE_FOLDER")

    layout.separator(type="LINE")
    row = layout.row()
    row.operator("iops.purge_widget_data",
                 text="Purge Widgets Data (this scene)", icon="TRASH")


classes = (
    IOPS_WidgetRowItem,
    IOPS_WidgetDefItem,
    IOPS_UL_WidgetDefs,
)
