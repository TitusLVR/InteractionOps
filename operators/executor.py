import os
from os import listdir
from os.path import isfile, join
import bpy
from bpy.props import StringProperty


def get_prefix(name):
    if "_" in name:
        split = name.split("_")
        prefix = split[0]
        if prefix == prefix.upper():
            split.pop(0)
            new_name = "_".join(split)
            return prefix, new_name
        else:
            return prefix[0].upper(), name
    else:
        return name[0].upper(), name


def get_executor_column_width(scripts):
    max_lenght = 0
    executor_name_length = bpy.context.preferences.addons["InteractionOps"].preferences.executor_name_length
    prefs = bpy.context.preferences.addons["InteractionOps"].preferences
    
    for script in scripts:
        full_name = os.path.split(script)
        name = os.path.splitext(full_name[1])[0]
        if len(name) > max_lenght:
            max_lenght = len(name) + executor_name_length

    min_width = executor_name_length
    column_count = max(1, int(len(scripts) / prefs.executor_column_count))
    return max(min_width, max_lenght)


class IOPS_OT_Executor(bpy.types.Operator):
    """Execute python scripts from folder"""

    bl_idname = "iops.executor"
    bl_label = "IOPS Executor"
    bl_options = {"REGISTER"}

    script: StringProperty(
        name="Script path",
        default="",
    )

    def execute(self, context):
        filename = self.script
        exec(compile(open(filename).read(), filename, "exec"))
        return {"FINISHED"}


class IOPS_PT_ExecuteList(bpy.types.Panel):
    bl_idname = "IOPS_PT_ExecuteList"
    bl_label = "Executor list"
    bl_space_type = "VIEW_3D"
    bl_region_type = "WINDOW"

    def draw(self, context):
        prefs = context.preferences.addons["InteractionOps"].preferences
        props = context.window_manager.IOPS_AddonProperties
        letter = ""
        iops = getattr(context.scene, "IOPS", None)
        if iops is None:
            layout = self.layout
            layout.label(text="IOPS scene data not available")
            return
        scripts = [item.path for item in iops.executor_scripts]
        global_column_amount = max(1, int(len(scripts) / prefs.executor_column_count))

        layout = self.layout
        # Use filtered scripts when filter is active
        filter_text = props.iops_exec_filter if hasattr(props, "iops_exec_filter") else ""
        if filter_text:
            scripts = [item.path for item in iops.filtered_executor_scripts]
        column_amount = max(1, int(len(scripts) / prefs.executor_column_count))
        layout.ui_units_x = get_executor_column_width(scripts) / (global_column_amount / column_amount)
        column_flow = layout.column_flow(columns=column_amount, align=False)
        column_flow.prop(props, "iops_exec_filter", text="", icon="VIEWZOOM")
        if scripts:
            for script in scripts:  # Start counting from 1
                full_name = os.path.split(script)
                name = os.path.splitext(full_name[1])[0]
                list_name = name[0].upper()
                if str(list_name) != letter:
                    column_flow.label(text=str(list_name))
                    letter = str(list_name)
                column_flow.operator(
                    "iops.executor", text=name, icon="FILE_SCRIPT"
                ).script = script


class IOPS_OT_Call_MT_Executor(bpy.types.Operator):
    """Active object data(mesh) information"""

    bl_idname = "iops.scripts_call_mt_executor"
    bl_label = "IOPS Call Executor"

    def execute(self, context):
        addon_prop = context.window_manager.IOPS_AddonProperties
        addon_prop.iops_exec_filter = ""
        iops = getattr(context.scene, "IOPS", None)
        if iops is None:
            return {"CANCELLED"}
        iops.filtered_executor_scripts.clear()
        prefs = context.preferences.addons["InteractionOps"].preferences
        executor_scripts_folder = prefs.executor_scripts_folder
        scripts_folder = executor_scripts_folder  # TODO: Add user scripts folder
        # scripts_folder = os.path.join(scripts_folder, "custom")
        _files = [f for f in listdir(scripts_folder) if isfile(join(scripts_folder, f))]
        files = [os.path.join(scripts_folder, f) for f in _files]
        scripts = [script for script in files if script[-2:] == "py"]
        iops.executor_scripts.clear()
        for path in scripts:
            item = iops.executor_scripts.add()
            item.path = path
        bpy.ops.wm.call_panel(name="IOPS_PT_ExecuteList")
        return {"FINISHED"}
