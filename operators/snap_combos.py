import bpy
import os
import json

def ensure_snap_combos_prefs():
    prefs = bpy.context.preferences.addons["InteractionOps"].preferences

    for i in range(1,9):
        if f"snap_combo_{i}" not in prefs.keys():
            prefs[f"snap_combo_{i}"] = {
                "SNAP_ELEMENTS": {
                    "INCREMENT": False,
                    "VERTEX": True,
                    "EDGE": False,
                    "FACE": False,
                    "VOLUME": False,
                    "EDGE_MIDPOINT": False,
                    "EDGE_PERPENDICULAR": False,
                    "FACE_PROJECT": False,
                    "FACE_NEAREST": False
                },
                "TOOL_SETTINGS": {
                    "transform_pivot_point": "ACTIVE_ELEMENT",
                    "snap_target": "ACTIVE",
                    # "use_snap_grid_absolute": True,
                    "use_snap_self": True,
                    "use_snap_align_rotation": False,
                    "use_snap_peel_object": True,
                    "use_snap_backface_culling": False,
                    "use_snap_selectable": False,
                    "use_snap_translate": False,
                    "use_snap_rotate": False,
                    "use_snap_scale": False,
                    "use_snap_to_same_target": False
                },
                "TRANSFORMATION": "GLOBAL"
            }

def save_snap_combo(idx):
    tool_settings = bpy.context.scene.tool_settings
    prefs = bpy.context.preferences.addons["InteractionOps"].preferences
    path = bpy.utils.script_path_user()
    iops_prefs_file = os.path.join(path, "presets", "IOPS", "iops_prefs_user.json")

    snap_elements_list = ['VERTEX',
                          'EDGE',
                          'FACE',
                          'VOLUME',
                          'INCREMENT',
                          'EDGE_MIDPOINT',
                          'EDGE_PERPENDICULAR',
                          'FACE_PROJECT',
                          'FACE_NEAREST'
                          ]

    with open(iops_prefs_file, "r") as f:
        iops_prefs = json.load(f)

    ensure_snap_combos_prefs()

    for snap_combo, snap_details in iops_prefs.get("SNAP_COMBOS", {}).items():
        if snap_combo[-1] == str(idx):
            snap_elements = tool_settings.snap_elements
            snap_elements_dict = {k: k in snap_elements for k in snap_elements_list}
            tool_settings_dict = {
                "transform_pivot_point": tool_settings.transform_pivot_point,
                "snap_target": tool_settings.snap_target,
                # "use_snap_grid_absolute": tool_settings.use_snap_grid_absolute,
                "use_snap_self": tool_settings.use_snap_self,
                "use_snap_align_rotation": tool_settings.use_snap_align_rotation,
                "use_snap_peel_object": tool_settings.use_snap_peel_object,
                "use_snap_backface_culling": tool_settings.use_snap_backface_culling,
                "use_snap_selectable": tool_settings.use_snap_selectable,
                "use_snap_translate": tool_settings.use_snap_translate,
                "use_snap_rotate": tool_settings.use_snap_rotate,
                "use_snap_scale": tool_settings.use_snap_scale,
                "use_snap_to_same_target": tool_settings.use_snap_to_same_target
            }
            snap_details["SNAP_ELEMENTS"] = snap_elements_dict
            snap_details["TOOL_SETTINGS"] = tool_settings_dict
            snap_details["TRANSFORMATION"] = bpy.context.scene.transform_orientation_slots[0].type
            prefs[snap_combo] = snap_details
            break

    with open(iops_prefs_file, "w") as f:
        json.dump(iops_prefs, f, indent=4)



class IOPS_OT_SetSnapCombo(bpy.types.Operator):
    '''
    Click to set the Snap Combo
    Shift+Click to save the current Snap Combo
    '''
    bl_idname = "iops.set_snap_combo"
    bl_label = "Set Snap Combo"
    bl_options = {"REGISTER", "UNDO"}

    idx: bpy.props.IntProperty()

    def invoke(self, context, event):
        prefs = context.preferences.addons["InteractionOps"].preferences
        save_combo_mod = prefs.snap_combo_mod

        if ((event.shift and save_combo_mod == "SHIFT") or
            (event.ctrl and save_combo_mod == "CTRL") or
            (event.alt and save_combo_mod == "ALT")):
            
            save_snap_combo(self.idx)
            self.report({"INFO"}, f"Snap Combo {self.idx} Saved.")

        else:
            tool_settings = context.scene.tool_settings
            snap_combos_prefs = [sc for sc in prefs.keys() if sc.startswith("snap_combo_")]
            for snap_combo in snap_combos_prefs:
                if snap_combo[-1] == str(self.idx):
                    elements = {k for k, v in prefs[snap_combo]["SNAP_ELEMENTS"].items() if v}
                    tool_settings.snap_elements = elements
                    tool_settings.transform_pivot_point                   = prefs[snap_combo]["TOOL_SETTINGS"]["transform_pivot_point"]
                    tool_settings.snap_target                             = prefs[snap_combo]["TOOL_SETTINGS"]["snap_target"]
                    # tool_settings.use_snap_grid_absolute                  = prefs[snap_combo]["TOOL_SETTINGS"]["use_snap_grid_absolute"]
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
            self.report({"INFO"}, f"Snap Combo {self.idx} Loaded.")
        return {"FINISHED"}

