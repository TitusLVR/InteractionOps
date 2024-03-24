import bpy
import os
import json


def save_snap_combo(idx):
    tool_settings = bpy.context.scene.tool_settings
    prefs = bpy.context.preferences.addons["InteractionOps"].preferences
    path = bpy.utils.script_path_user()
    iops_prefs_file = os.path.join(path, "presets", "IOPS", "iops_prefs_user.json")

    with open(iops_prefs_file, "r") as f:
        iops_prefs = json.load(f)

    with open(iops_prefs_file, "w") as f:
        for key, value in iops_prefs.items():
            if key == "SNAP_COMBOS":
                for snap_combo in value:
                    if snap_combo[-1] == str(idx):
                        for k, v in value[snap_combo]["SNAP_ELEMENTS"].items():
                            value[snap_combo]["SNAP_ELEMENTS"][k] = k in tool_settings.snap_elements
                        value[snap_combo]         ["TOOL_SETTINGS"]["transform_pivot_point"]     = tool_settings.transform_pivot_point
                        prefs[f'snap_combo_{idx}']["TOOL_SETTINGS"]["transform_pivot_point"]     = tool_settings.transform_pivot_point
                        value[snap_combo]         ["TOOL_SETTINGS"]["snap_target"]               = tool_settings.snap_target
                        prefs[f'snap_combo_{idx}']["TOOL_SETTINGS"]["snap_target"]               = tool_settings.snap_target
                        value[snap_combo]         ["TOOL_SETTINGS"]["use_snap_grid_absolute"]    = tool_settings.use_snap_grid_absolute
                        prefs[f'snap_combo_{idx}']["TOOL_SETTINGS"]["use_snap_grid_absolute"]    = tool_settings.use_snap_grid_absolute
                        value[snap_combo]         ["TOOL_SETTINGS"]["use_snap_self"]             = tool_settings.use_snap_self
                        prefs[f'snap_combo_{idx}']["TOOL_SETTINGS"]["use_snap_self"]             = tool_settings.use_snap_self
                        value[snap_combo]         ["TOOL_SETTINGS"]["use_snap_align_rotation"]   = tool_settings.use_snap_align_rotation
                        prefs[f'snap_combo_{idx}']["TOOL_SETTINGS"]["use_snap_align_rotation"]   = tool_settings.use_snap_align_rotation
                        value[snap_combo]         ["TOOL_SETTINGS"]["use_snap_peel_object"]      = tool_settings.use_snap_peel_object
                        prefs[f'snap_combo_{idx}']["TOOL_SETTINGS"]["use_snap_peel_object"]      = tool_settings.use_snap_peel_object
                        value[snap_combo]         ["TOOL_SETTINGS"]["use_snap_backface_culling"] = tool_settings.use_snap_backface_culling
                        prefs[f'snap_combo_{idx}']["TOOL_SETTINGS"]["use_snap_backface_culling"] = tool_settings.use_snap_backface_culling
                        value[snap_combo]         ["TOOL_SETTINGS"]["use_snap_selectable"]       = tool_settings.use_snap_selectable
                        prefs[f'snap_combo_{idx}']["TOOL_SETTINGS"]["use_snap_selectable"]       = tool_settings.use_snap_selectable
                        value[snap_combo]         ["TOOL_SETTINGS"]["use_snap_translate"]        = tool_settings.use_snap_translate
                        prefs[f'snap_combo_{idx}']["TOOL_SETTINGS"]["use_snap_translate"]        = tool_settings.use_snap_translate
                        value[snap_combo]         ["TOOL_SETTINGS"]["use_snap_rotate"]           = tool_settings.use_snap_rotate
                        prefs[f'snap_combo_{idx}']["TOOL_SETTINGS"]["use_snap_rotate"]           = tool_settings.use_snap_rotate
                        value[snap_combo]         ["TOOL_SETTINGS"]["use_snap_scale"]            = tool_settings.use_snap_scale
                        prefs[f'snap_combo_{idx}']["TOOL_SETTINGS"]["use_snap_scale"]            = tool_settings.use_snap_scale
                        value[snap_combo]         ["TOOL_SETTINGS"]["use_snap_to_same_target"]   = tool_settings.use_snap_to_same_target
                        prefs[f'snap_combo_{idx}']["TOOL_SETTINGS"]["use_snap_to_same_target"]   = tool_settings.use_snap_to_same_target
                        value[snap_combo]         ["TRANSFORMATION"]          = bpy.context.scene.transform_orientation_slots[0].type
                        prefs[f'snap_combo_{idx}']["TRANSFORMATION"] = bpy.context.scene.transform_orientation_slots[0].type
                        break
        json.dump(iops_prefs, f, indent=4)


class IOPS_OT_SetSnapCombo(bpy.types.Operator):
    '''IOPS Set Snap combo'''
    bl_idname = "iops.set_snap_combo"
    bl_label = "Set Snap Combo "
    bl_options = {"REGISTER", "UNDO"}

    idx: bpy.props.IntProperty()

    def invoke(self, context, event):
        prefs = context.preferences.addons["InteractionOps"].preferences

        if event.shift:
            save_snap_combo(self.idx)
            self.report({"INFO"}, f"Snapping Combo {self.idx} Saved.")

        else:
            tool_settings = context.scene.tool_settings
            snap_combos_prefs = [sc for sc in prefs.keys() if sc.startswith("snap_combo_")]
            for snap_combo in snap_combos_prefs:
                if snap_combo[-1] == str(self.idx):
                    elements = {k for k, v in prefs[snap_combo]["SNAP_ELEMENTS"].items() if v}
                    tool_settings.snap_elements = elements
                    tool_settings.transform_pivot_point                   = prefs[snap_combo]["TOOL_SETTINGS"]["transform_pivot_point"]
                    tool_settings.snap_target                             = prefs[snap_combo]["TOOL_SETTINGS"]["snap_target"]
                    tool_settings.use_snap_grid_absolute                  = prefs[snap_combo]["TOOL_SETTINGS"]["use_snap_grid_absolute"]
                    tool_settings.use_snap_self                           = prefs[snap_combo]["TOOL_SETTINGS"]["use_snap_self"]
                    tool_settings.use_snap_align_rotation                 = prefs[snap_combo]["TOOL_SETTINGS"]["use_snap_align_rotation"]
                    tool_settings.use_snap_peel_object                    = prefs[snap_combo]["TOOL_SETTINGS"]["use_snap_peel_object"]
                    tool_settings.use_snap_backface_culling               = prefs[snap_combo]["TOOL_SETTINGS"]["use_snap_backface_culling"]
                    tool_settings.use_snap_selectable                     = prefs[snap_combo]["TOOL_SETTINGS"]["use_snap_selectable"]
                    tool_settings.use_snap_translate                      = prefs[snap_combo]["TOOL_SETTINGS"]["use_snap_translate"]
                    tool_settings.use_snap_rotate                         = prefs[snap_combo]["TOOL_SETTINGS"]["use_snap_rotate"]
                    tool_settings.use_snap_scale                          = prefs[snap_combo]["TOOL_SETTINGS"]["use_snap_scale"]
                    tool_settings.use_snap_to_same_target                 = prefs[snap_combo]["TOOL_SETTINGS"]["use_snap_to_same_target"]
                    bpy.context.scene.transform_orientation_slots[0].type = prefs[snap_combo]["TRANSFORMATION"]
                    break
            self.report({"INFO"}, f"Snapping Combo {self.idx} Loaded.")
        return {"FINISHED"}

