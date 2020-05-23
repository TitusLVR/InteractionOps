import bpy
import os
from ... prefs.iops_prefs_list import iops_prefs_list as iops_prefs


############################## SAVE Addon Preferences ##############################

def save_iops_preferences(iops_prefs_list):

    path = bpy.utils.script_path_user()
    folder = os.path.join(path, 'presets', "IOPS")
    iops_preferences_file = os.path.join(path, 'presets', "IOPS", "iops_preferences_user.py")

    if not os.path.exists(folder):
            os.makedirs(folder)
    with open(iops_preferences_file, 'w') as f:
        for p in iops_prefs_list:
            key = "bpy.context.preferences.addons['InteractionOps'].preferences." + p
            value = eval(key)
            if p == "executor_scripts_folder":
                value = os.path.abspath(bpy.context.preferences.addons['InteractionOps'].preferences.executor_scripts_folder)
            if type(value) is str:
                value = 'r' + '"' + value + '"'  
            if "bpy_prop_array" in str(type(value)):
                value = value[:]    
            item = key + " = " + str(value)
            f.write(item + "\n")

############################## LOAD Addon Preferences ##############################
def load_iops_preferences():
    path = bpy.utils.script_path_user()
    iops_preferences_file = os.path.join(path, 'presets', "IOPS", "iops_preferences_user.py")

    if os.path.exists(iops_preferences_file):
        with open(iops_preferences_file, 'r') as f:
            content = f.readlines()
            if content:
                for line in content:
                    exec(line) 


class IOPS_OT_SaveAddonPreferences(bpy.types.Operator):
    bl_idname = "iops.save_addon_preferences"
    bl_label = "Save Addon Preferences"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        save_iops_preferences(iops_prefs)
        print("IOPS Preferences were Saved.")
        return {"FINISHED"}

class IOPS_OT_LoadAddonPreferences(bpy.types.Operator):
    bl_idname = "iops.load_addon_preferences"
    bl_label = "Load Addon Preferences"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        load_iops_preferences()
        print("IOPS Preferences were Loaded")
        return {"FINISHED"}

