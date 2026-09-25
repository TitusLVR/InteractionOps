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


def _external_editor_command(context, filepath):
    """Build the argv for the user's external text editor, or None when
    no editor is configured (Preferences > File Paths > Applications >
    Text Editor). Mirrors Blender's own `$filepath` template handling
    (`_bl_text_utils.external_editor`); `$line`/`$column` resolve to 1
    so an editor preset written for "jump to file at point" still works.
    An empty Arguments field falls back to passing just the file path."""
    import shlex
    from string import Template

    paths = context.preferences.filepaths
    editor = (getattr(paths, "text_editor", "") or "").strip()
    if not editor:
        return None
    args_fmt = (getattr(paths, "text_editor_args", "") or "").strip()
    if not args_fmt:
        return [editor, filepath]
    if "$filepath" not in args_fmt:
        args_fmt += " $filepath"
    template_vars = {"filepath": filepath, "line": 1, "column": 1,
                     "line0": 0, "column0": 0}
    argv = [editor]
    # posix=True like Blender: quotes around "$filepath" are stripped
    # here, and the path is substituted AFTER splitting so its backslashes
    # survive intact.
    for arg in shlex.split(args_fmt):
        argv.append(Template(arg).safe_substitute(**template_vars))
    return argv


class IOPS_OT_WidgetEdit(bpy.types.Operator):
    bl_idname = "iops.widget_edit"
    bl_label = "Edit Widget"
    bl_description = ("Open this widget's JSON definition in your text "
                      "editor (Preferences > File Paths > Applications > "
                      "Text Editor; the OS default app when unset)")
    bl_options = {"REGISTER", "INTERNAL"}

    name: StringProperty(name="Widget", default="")

    def execute(self, context):
        import subprocess

        if not self.name:
            self.report({"ERROR"}, "No widget name given")
            return {"CANCELLED"}
        path = composed.widget_path(self.name)
        if not os.path.isfile(path):
            self.report({"ERROR"},
                        f"Widget '{self.name}' has no JSON file at {path}")
            return {"CANCELLED"}

        argv = _external_editor_command(context, path)
        if argv is None:
            # No editor configured: let the OS pick the .json handler.
            bpy.ops.wm.path_open(filepath=path)
            return {"FINISHED"}
        try:
            # Popen (not run): never block Blender on an editor that
            # stays in the foreground until closed.
            subprocess.Popen(argv, close_fds=True)
        except OSError as ex:
            self.report({"ERROR"},
                        f"Could not launch text editor {argv[0]!r}: {ex}")
            return {"CANCELLED"}
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
    IOPS_OT_WidgetEdit,
    IOPS_OT_WidgetsOpenFolder,
)
