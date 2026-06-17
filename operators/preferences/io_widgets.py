"""Widgets tab operators — manage composed-widget definition files.

Storage: `bpy.utils.script_path_user()/presets/IOPS/widgets/*.json`
(see widgets/composed.py for the schema and runtime registration).
All list/row mutations route back through widget_composer's sync/autosave
so the prefs collection, the JSON files, and the live widget registry
never disagree.
"""
import os

import bpy
from bpy.props import StringProperty
from bpy_extras.io_utils import ExportHelper, ImportHelper

from ...prefs import widget_composer
from ...widgets import composed


def _taken_names():
    prefs = widget_composer.get_prefs()
    taken = {it.name for it in prefs.widget_defs}
    return taken


class IOPS_OT_WidgetDefAdd(bpy.types.Operator):
    bl_idname = "iops.widget_def_add"
    bl_label = "New Widget"
    bl_description = "Create a new empty widget definition"
    bl_options = {"REGISTER"}

    def execute(self, context):
        name = composed.unique_name("my_widget", _taken_names())
        wdef, _ = composed.validate_def(
            {"name": name, "title": name.replace("_", " ").title(),
             "rows": [{"type": "SECTION", "label": "Section"}]})
        composed.save_def(wdef)
        composed.register_composed(wdef)
        widget_composer.sync_from_files(select=name)
        return {"FINISHED"}


class IOPS_OT_WidgetDefDuplicate(bpy.types.Operator):
    bl_idname = "iops.widget_def_duplicate"
    bl_label = "Duplicate Widget"
    bl_description = ("Duplicate the selected widget into an editable "
                      "copy (the way to customize a built-in)")
    bl_options = {"REGISTER"}

    @classmethod
    def poll(cls, context):
        return widget_composer.selected_item() is not None

    def execute(self, context):
        item = widget_composer.selected_item()
        src = widget_composer.item_to_def(item)
        if src is None:
            self.report({"ERROR"}, "Nothing to duplicate")
            return {"CANCELLED"}
        wdef, _ = composed.validate_def(dict(src))
        wdef["name"] = composed.unique_name(wdef["name"], _taken_names())
        composed.save_def(wdef)
        composed.register_composed(wdef)
        widget_composer.sync_from_files(select=wdef["name"])
        return {"FINISHED"}


class IOPS_OT_WidgetDefRemove(bpy.types.Operator):
    bl_idname = "iops.widget_def_remove"
    bl_label = "Delete Widget"
    bl_description = "Delete the selected widget definition file"
    bl_options = {"REGISTER"}

    @classmethod
    def poll(cls, context):
        item = widget_composer.selected_item()
        return item is not None and not item.builtin

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        item = widget_composer.selected_item()
        name = item.name
        from ...ui.widgets import state
        state.hide_widget(name)
        composed.unregister_composed(name)
        composed.delete_def(name)
        widget_composer.sync_from_files()
        self.report({"INFO"}, f"Deleted widget '{name}'")
        return {"FINISHED"}


class IOPS_OT_WidgetDefImport(bpy.types.Operator, ImportHelper):
    bl_idname = "iops.widget_def_import"
    bl_label = "Import Widget"
    bl_description = "Import a widget definition .json into the widgets folder"
    bl_options = {"REGISTER"}

    filename_ext = ".json"
    filter_glob: StringProperty(default="*.json", options={"HIDDEN"})

    def execute(self, context):
        wdef, errors = composed.load_def(self.filepath)
        if wdef is None:
            self.report({"ERROR"}, f"Invalid widget file: {'; '.join(errors)}")
            return {"CANCELLED"}
        if errors:
            self.report({"WARNING"},
                        f"Imported with dropped rows: {'; '.join(errors)}")
        wdef["name"] = composed.unique_name(wdef["name"], _taken_names())
        composed.save_def(wdef)
        composed.register_composed(wdef)
        widget_composer.sync_from_files(select=wdef["name"])
        return {"FINISHED"}


class IOPS_OT_WidgetDefExport(bpy.types.Operator, ExportHelper):
    bl_idname = "iops.widget_def_export"
    bl_label = "Export Widget"
    bl_description = "Export the selected widget definition to a .json file"
    bl_options = {"REGISTER"}

    filename_ext = ".json"
    filter_glob: StringProperty(default="*.json", options={"HIDDEN"})

    @classmethod
    def poll(cls, context):
        return widget_composer.selected_item() is not None

    def invoke(self, context, event):
        item = widget_composer.selected_item()
        if item is not None:
            self.filepath = item.name + ".json"
        return super().invoke(context, event)

    def execute(self, context):
        import json
        item = widget_composer.selected_item()
        wdef, _ = composed.validate_def(widget_composer.item_to_def(item))
        if wdef is None:
            self.report({"ERROR"}, "Nothing to export")
            return {"CANCELLED"}
        with open(self.filepath, "w", encoding="utf-8") as f:
            json.dump(wdef, f, indent=2)
        self.report({"INFO"}, f"Exported to {self.filepath}")
        return {"FINISHED"}


class IOPS_OT_WidgetsOpenFolder(bpy.types.Operator):
    bl_idname = "iops.widgets_open_folder"
    bl_label = "Open Widgets Folder"
    bl_description = "Open the widget definitions folder in your OS file manager"
    bl_options = {"REGISTER"}

    def execute(self, context):
        folder = composed.widgets_folder()
        os.makedirs(folder, exist_ok=True)
        bpy.ops.wm.path_open(filepath=folder)
        return {"FINISHED"}


classes = (
    IOPS_OT_WidgetDefAdd,
    IOPS_OT_WidgetDefDuplicate,
    IOPS_OT_WidgetDefRemove,
    IOPS_OT_WidgetDefImport,
    IOPS_OT_WidgetDefExport,
    IOPS_OT_WidgetsOpenFolder,
)
