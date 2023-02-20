import bpy
import os
from os import listdir
from os.path import isfile, join
from bpy.props import (StringProperty)

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



class IOPS_OT_Executor(bpy.types.Operator):
    """ Execute python scripts from folder """
    bl_idname = "iops.executor"
    bl_label = "IOPS Executor"
    bl_options = {"REGISTER"}

    script: StringProperty(
        name="Script path",
        default="",
        )
    def execute(self, context):
        filename = self.script
        exec(compile(open(filename).read(), filename, 'exec'))        
        return {"FINISHED"}

class IOPS_MT_ExecuteList(bpy.types.Menu):
    bl_idname = "IOPS_MT_ExecuteList"
    bl_label = "Executor list"

    def draw(self, context):
        prefs = context.preferences.addons['InteractionOps'].preferences
        executor_scripts_folder = prefs.executor_scripts_folder
        executor_column_count = prefs.executor_column_count
        Letter = ""
        scripts_folder = executor_scripts_folder # TODO: Add user scripts folder 
        # scripts_folder = os.path.join(scripts_folder, "custom")
        _files = [f for f in listdir(scripts_folder) if isfile(join(scripts_folder, f))]
        files = [os.path.join(scripts_folder, f) for f in _files]
        scripts = [script for script in files if script[-2:] == "py"]

        layout = self.layout        
        row = layout.row(align=True)              
        col = row.column()
        col.separator()        
        if scripts:
            count = len(scripts)
            for count, script in enumerate(scripts, 0): # Start counting from 1
                if count % executor_column_count == 0:                                        
                    row = row.row(align=True)
                    col = row.column()
                full_name = os.path.split(script)
                name = full_name[1]
                listName = name[0].upper()
                # listName, new_name = get_prefix(name)                
                if str(listName) != Letter:
                    col.label(text=str(listName))
                    Letter = str(listName)
                col.operator("iops.executor", text=str(name), icon='FILE_SCRIPT').script = script 


class IOPS_OT_Call_MT_Executor(bpy.types.Operator):
    """Active object data(mesh) information"""
    bl_idname = "iops.call_mt_executor"
    bl_label = "IOPS Call Executor"

    def execute(self, context):
        bpy.ops.wm.call_menu(name="IOPS_MT_ExecuteList")
        return {'FINISHED'}
