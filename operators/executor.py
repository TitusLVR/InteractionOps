import bpy
import os
from os import listdir
from os.path import isfile, join
from bpy.props import (StringProperty)

class IOPS_OT_Executor(bpy.types.Operator):
    """ Execute info operators from buffer """
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
        scripts_folder = bpy.utils.script_path_user() # TODO: Add user scripts folder 
        _files = [f for f in listdir(scripts_folder) if isfile(join(scripts_folder, f))]
        files = [os.path.join(scripts_folder, f) for f in _files]
        scripts = [script for script in files if script[-2:] == "py"]

        layout = self.layout
        col = layout.column(align=True)

        if scripts:
            col.separator()
            for script in scripts:
                name = os.path.split(script)
                col.operator("iops.executor", text=name[1], icon='FILE_SCRIPT').script = script 


class IOPS_OT_Call_MT_Executor(bpy.types.Operator):
    """Active object data(mesh) information"""
    bl_idname = "iops.call_mt_executor"
    bl_label = "IOPS Call Executor"

    def execute(self, context):
        bpy.ops.wm.call_menu(name="IOPS_MT_ExecuteList")
        return {'FINISHED'}
