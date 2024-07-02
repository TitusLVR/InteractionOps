import bpy
import os
from os import listdir
from os.path import isfile, join
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


def get_executor_column_width(is_filtered):
    max_lenght = 0
    if is_filtered:
        scripts = bpy.context.scene.IOPS["filtered_executor_scripts"]
    else:
        scripts = bpy.context.scene.IOPS["executor_scripts"]

    for script in scripts:
        full_name = os.path.split(script)
        name = os.path.splitext(full_name[1])[0]
        if len(name) > max_lenght:
            max_lenght = len(name)
    return max_lenght


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
        addon_prop = context.window_manager.IOPS_AddonProperties
        Letter = ""

        if "filtered_executor_scripts" in bpy.context.scene.IOPS.keys():
            layout = self.layout
            layout.ui_units_x = get_executor_column_width(True) * 1.75
            column_amount = int(len(bpy.context.scene.IOPS["filtered_executor_scripts"]) / prefs.executor_column_count)
            column_flow = layout.column_flow(columns=column_amount, align=False)
            column_flow.prop(addon_prop, "iops_exec_filter", text="", icon="VIEWZOOM")
            scripts = bpy.context.scene.IOPS["filtered_executor_scripts"]
            if scripts:
                for script in scripts:  # Start counting from 1
                    full_name = os.path.split(script)
                    name = os.path.splitext(full_name[1])[0]
                    listName = name[0].upper()
                    column_flow.operator("iops.executor", text=name, icon="FILE_SCRIPT").script = script            
        else:
            layout = self.layout
            layout.ui_units_x = get_executor_column_width(False) * 1.75
            column_amount = int(len(bpy.context.scene.IOPS["executor_scripts"]) / prefs.executor_column_count)
            column_flow = layout.column_flow(columns=column_amount, align=False)
            column_flow.prop(addon_prop, "iops_exec_filter", text="", icon="VIEWZOOM")
            scripts = bpy.context.scene.IOPS["executor_scripts"]
            if scripts:
                for script in scripts:  # Start counting from 1
                    full_name = os.path.split(script)
                    name = os.path.splitext(full_name[1])[0]
                    listName = name[0].upper()
                    # listName, new_name = get_prefix(name)
                    if str(listName) != Letter:
                        column_flow.label(text=str(listName))
                        Letter = str(listName)
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
        if "filtered_executor_scripts" in bpy.context.scene.IOPS.keys():
            del bpy.context.scene.IOPS["filtered_executor_scripts"]
        prefs = context.preferences.addons["InteractionOps"].preferences
        executor_scripts_folder = prefs.executor_scripts_folder
        scripts_folder = executor_scripts_folder  # TODO: Add user scripts folder
        # scripts_folder = os.path.join(scripts_folder, "custom")
        _files = [f for f in listdir(scripts_folder) if isfile(join(scripts_folder, f))]
        files = [os.path.join(scripts_folder, f) for f in _files]
        scripts = [script for script in files if script[-2:] == "py"]
        bpy.context.scene["IOPS"]["executor_scripts"] = scripts
        bpy.ops.wm.call_panel(name="IOPS_PT_ExecuteList")
        return {"FINISHED"}
