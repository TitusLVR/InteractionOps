import bpy
import os
import json

def ensure_snap_combos_prefs():
    prefs = bpy.context.preferences.addons["InteractionOps"].preferences

    for i in range(1,9):
        combo_key = f"snap_combo_{i}"
        # Check if property exists - try both ID property and regular attribute
        exists = False
        try:
            # Try checking as ID property (Blender < 5.0)
            if hasattr(prefs, 'keys'):
                exists = combo_key in prefs.keys()
            else:
                exists = hasattr(prefs, combo_key)
        except (TypeError, AttributeError):
            exists = hasattr(prefs, combo_key)
        
        if not exists:
            combo_value = {
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
            # Try to set as ID property first, fallback to setattr if not supported
            try:
                prefs[combo_key] = combo_value
            except (TypeError, AttributeError):
                # ID properties not supported, use setattr (may not work for dict values)
                try:
                    setattr(prefs, combo_key, combo_value)
                except (TypeError, AttributeError):
                    # If both fail, log a warning but continue
                    print(f"Warning: Could not set {combo_key} property. ID properties may not be supported on AddonPreferences in Blender 5.0+")

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
            # Try to set as ID property first, fallback to setattr if not supported
            try:
                prefs[snap_combo] = snap_details
            except (TypeError, AttributeError):
                # ID properties not supported, use setattr (may not work for dict values)
                try:
                    setattr(prefs, snap_combo, snap_details)
                except (TypeError, AttributeError):
                    # If both fail, log a warning but continue
                    print(f"Warning: Could not set {snap_combo} property. ID properties may not be supported on AddonPreferences in Blender 5.0+")
            break

    with open(iops_prefs_file, "w") as f:
        json.dump(iops_prefs, f, indent=4)



class IOPS_OT_SetSnapCombo(bpy.types.Operator):
    '''
    Click to set the Snap Combo
    Shift+Click to save current Snap Combo
    '''
    bl_idname = "iops.set_snap_combo"
    bl_label = "Set Snap Combo"
    bl_options = {"REGISTER", "UNDO"}

    idx: bpy.props.IntProperty()

    @classmethod
    def description(cls, context, properties):
        prefs = context.preferences.addons["InteractionOps"].preferences
        save_combo_mod = prefs.snap_combo_mod
        
        modifier_text = {
            "SHIFT": "Shift",
            "CTRL": "Ctrl", 
            "ALT": "Alt",
            "CTRL_ALT": "Ctrl + Alt",
            "SHIFT_ALT": "Shift + Alt",
            "SHIFT_CTRL": "Shift + Ctrl",
            "SHIFT_CTRL_ALT": "Shift + Ctrl + Alt"
        }.get(save_combo_mod, "Shift")
        
        return f"{modifier_text} + Click to save current Snap Combo"

    def invoke(self, context, event):
        prefs = context.preferences.addons["InteractionOps"].preferences
        save_combo_mod = prefs.snap_combo_mod

        if ((event.shift and save_combo_mod == "SHIFT") or
            (event.ctrl and save_combo_mod == "CTRL") or
            (event.alt and save_combo_mod == "ALT") or
            (event.ctrl and event.alt and save_combo_mod == "CTRL_ALT") or
            (event.shift and event.alt and save_combo_mod == "SHIFT_ALT") or
            (event.shift and event.ctrl and save_combo_mod == "SHIFT_CTRL") or
            (event.shift and event.ctrl and event.alt and save_combo_mod == "SHIFT_CTRL_ALT")):
            
            save_snap_combo(self.idx)
            self.report({"INFO"}, f"Snap Combo {self.idx} Saved.")

        else:
            tool_settings = context.scene.tool_settings
            # Get snap combo keys - try both ID property keys() and dir() for attributes
            snap_combos_prefs = []
            try:
                if hasattr(prefs, 'keys'):
                    snap_combos_prefs = [sc for sc in prefs.keys() if sc.startswith("snap_combo_")]
                else:
                    # Fallback: check dir() for attributes starting with snap_combo_
                    snap_combos_prefs = [sc for sc in dir(prefs) if sc.startswith("snap_combo_") and not sc.startswith("_")]
            except (TypeError, AttributeError):
                # Fallback: check dir() for attributes
                snap_combos_prefs = [sc for sc in dir(prefs) if sc.startswith("snap_combo_") and not sc.startswith("_")]
            
            for snap_combo in snap_combos_prefs:
                if snap_combo[-1] == str(self.idx):
                    # Try to get the property value - handle both ID property and regular attribute
                    try:
                        combo_data = prefs[snap_combo]
                    except (TypeError, AttributeError, KeyError):
                        try:
                            combo_data = getattr(prefs, snap_combo)
                        except AttributeError:
                            print(f"Warning: Could not access {snap_combo} property")
                            continue
                    
                    if not isinstance(combo_data, dict):
                        print(f"Warning: {snap_combo} is not a dictionary")
                        continue
                    
                    elements = {k for k, v in combo_data.get("SNAP_ELEMENTS", {}).items() if v}
                    tool_settings.snap_elements = elements
                    tool_settings_dict = combo_data.get("TOOL_SETTINGS", {})
                    tool_settings.transform_pivot_point                   = tool_settings_dict.get("transform_pivot_point", "ACTIVE_ELEMENT")
                    tool_settings.snap_target                             = tool_settings_dict.get("snap_target", "ACTIVE")
                    # tool_settings.use_snap_grid_absolute                  = tool_settings_dict.get("use_snap_grid_absolute", True)
                    tool_settings.use_snap_self                           = tool_settings_dict.get("use_snap_self", True)
                    tool_settings.use_snap_align_rotation                 = tool_settings_dict.get("use_snap_align_rotation", False)
                    tool_settings.use_snap_peel_object                    = tool_settings_dict.get("use_snap_peel_object", True)
                    tool_settings.use_snap_backface_culling               = tool_settings_dict.get("use_snap_backface_culling", False)
                    tool_settings.use_snap_selectable                     = tool_settings_dict.get("use_snap_selectable", False)
                    tool_settings.use_snap_translate                      = tool_settings_dict.get("use_snap_translate", False)
                    tool_settings.use_snap_rotate                         = tool_settings_dict.get("use_snap_rotate", False)
                    tool_settings.use_snap_scale                          = tool_settings_dict.get("use_snap_scale", False)
                    tool_settings.use_snap_to_same_target                 = tool_settings_dict.get("use_snap_to_same_target", False)
                    bpy.context.scene.transform_orientation_slots[0].type = combo_data.get("TRANSFORMATION", "GLOBAL")
                    break
            self.report({"INFO"}, f"Snap Combo {self.idx} Loaded.")
        return {"FINISHED"}

