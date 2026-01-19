import bpy
import os
import json

def get_snap_combos_file_path():
    """Get the path to the snap combos JSON file."""
    path = bpy.utils.script_path_user()
    return os.path.join(path, "presets", "IOPS", "iops_prefs_user.json")

def ensure_snap_combos_prefs():
    """Ensure the JSON file has default snap combo entries if they don't exist."""
    iops_prefs_file = get_snap_combos_file_path()
    
    try:
        # Create directory if it doesn't exist
        os.makedirs(os.path.dirname(iops_prefs_file), exist_ok=True)
        
        # Load existing preferences or create new dict
        iops_prefs = {}
        if os.path.exists(iops_prefs_file):
            try:
                with open(iops_prefs_file, "r", encoding='utf-8') as f:
                    content = f.read().strip()
                    if content:  # Only parse if file is not empty
                        iops_prefs = json.loads(content)
                    if not isinstance(iops_prefs, dict):
                        print("IOPS Snap Combos: Invalid file format, creating new preferences")
                        iops_prefs = {}
            except json.JSONDecodeError as e:
                print(f"IOPS Snap Combos: JSON decode error - {e}, creating new preferences")
                # Backup corrupted file
                backup_file = iops_prefs_file + ".backup"
                try:
                    if os.path.exists(backup_file):
                        os.remove(backup_file)
                    os.rename(iops_prefs_file, backup_file)
                    print(f"Corrupted preferences backed up to: {backup_file}")
                except Exception:
                    pass
                iops_prefs = {}
            except Exception as e:
                print(f"IOPS Snap Combos: Error reading file - {e}, creating new preferences")
                iops_prefs = {}
        
        # Ensure SNAP_COMBOS section exists
        if not isinstance(iops_prefs, dict):
            iops_prefs = {}
        if "SNAP_COMBOS" not in iops_prefs or not isinstance(iops_prefs["SNAP_COMBOS"], dict):
            iops_prefs["SNAP_COMBOS"] = {}
        
        # Ensure each snap combo has default values if missing
        default_combo = {
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
        
        modified = False
        for i in range(1, 9):
            combo_key = f"snap_combo_{i}"
            if combo_key not in iops_prefs["SNAP_COMBOS"]:
                import copy
                iops_prefs["SNAP_COMBOS"][combo_key] = copy.deepcopy(default_combo)
                modified = True
        
        # Save the updated preferences only if modifications were made
        if modified or not os.path.exists(iops_prefs_file):
            temp_file = iops_prefs_file + ".tmp"
            try:
                with open(temp_file, "w", encoding='utf-8') as f:
                    json.dump(iops_prefs, f, indent=4)
                
                if os.path.exists(iops_prefs_file):
                    os.replace(temp_file, iops_prefs_file)
                else:
                    os.rename(temp_file, iops_prefs_file)
                    
                print(f"IOPS Snap Combos: Preferences file updated at {iops_prefs_file}")
            except Exception as e:
                print(f"IOPS Snap Combos: Error saving file - {e}")
                if os.path.exists(temp_file):
                    try:
                        os.remove(temp_file)
                    except Exception:
                        pass
                raise
        
        return True
        
    except Exception as e:
        print(f"IOPS Snap Combos: Critical error in ensure_snap_combos_prefs - {e}")
        return False

def save_snap_combo(idx):
    """Save the current snap settings to the JSON file."""
    try:
        tool_settings = bpy.context.scene.tool_settings
        iops_prefs_file = get_snap_combos_file_path()

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

        # Ensure file exists with defaults
        ensure_snap_combos_prefs()

        # Load existing preferences
        try:
            with open(iops_prefs_file, "r", encoding='utf-8') as f:
                iops_prefs = json.load(f)
        except (json.JSONDecodeError, IOError, FileNotFoundError) as e:
            print(f"IOPS Snap Combos: Error loading file for save - {e}, creating new")
            iops_prefs = {}

        # Ensure SNAP_COMBOS section exists
        if not isinstance(iops_prefs, dict):
            iops_prefs = {}
        if "SNAP_COMBOS" not in iops_prefs or not isinstance(iops_prefs["SNAP_COMBOS"], dict):
            iops_prefs["SNAP_COMBOS"] = {}

        # Find the matching snap combo
        combo_key = f"snap_combo_{idx}"
        
        # Get current snap settings
        snap_elements = tool_settings.snap_elements
        snap_elements_dict = {k: k in snap_elements for k in snap_elements_list}
        tool_settings_dict = {
            "transform_pivot_point": tool_settings.transform_pivot_point,
            "snap_target": tool_settings.snap_target,
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
        
        # Update the snap combo in the JSON structure
        iops_prefs["SNAP_COMBOS"][combo_key] = {
            "SNAP_ELEMENTS": snap_elements_dict,
            "TOOL_SETTINGS": tool_settings_dict,
            "TRANSFORMATION": bpy.context.scene.transform_orientation_slots[0].type
        }

        # Save to file with atomic write
        temp_file = iops_prefs_file + ".tmp"
        with open(temp_file, "w", encoding='utf-8') as f:
            json.dump(iops_prefs, f, indent=4)
        
        if os.path.exists(iops_prefs_file):
            os.replace(temp_file, iops_prefs_file)
        else:
            os.rename(temp_file, iops_prefs_file)
        
        return True
        
    except Exception as e:
        print(f"IOPS Snap Combos: Error saving snap combo {idx} - {e}")
        # Clean up temp file if it exists
        temp_file = iops_prefs_file + ".tmp"
        if os.path.exists(temp_file):
            try:
                os.remove(temp_file)
            except Exception:
                pass
        return False



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
            # Load snap combo from JSON file
            tool_settings = context.scene.tool_settings
            iops_prefs_file = get_snap_combos_file_path()
            
            # Ensure file exists with defaults
            ensure_snap_combos_prefs()
            
            # Load preferences from JSON
            try:
                with open(iops_prefs_file, "r", encoding='utf-8') as f:
                    iops_prefs = json.load(f)
            except (IOError, json.JSONDecodeError):
                self.report({"ERROR"}, f"Could not load snap combo from {iops_prefs_file}")
                return {"CANCELLED"}
            
            # Get the snap combo data
            combo_key = f"snap_combo_{self.idx}"
            snap_combos = iops_prefs.get("SNAP_COMBOS", {})
            
            if combo_key not in snap_combos:
                self.report({"WARNING"}, f"Snap Combo {self.idx} not found. Using defaults.")
                ensure_snap_combos_prefs()
                with open(iops_prefs_file, "r", encoding='utf-8') as f:
                    iops_prefs = json.load(f)
                snap_combos = iops_prefs.get("SNAP_COMBOS", {})
            
            combo_data = snap_combos.get(combo_key, {})
            
            if not isinstance(combo_data, dict):
                self.report({"ERROR"}, f"Snap Combo {self.idx} has invalid data.")
                return {"CANCELLED"}
            
            # Apply snap elements
            elements = {k for k, v in combo_data.get("SNAP_ELEMENTS", {}).items() if v}
            tool_settings.snap_elements = elements
            
            # Apply tool settings
            tool_settings_dict = combo_data.get("TOOL_SETTINGS", {})
            tool_settings.transform_pivot_point = tool_settings_dict.get("transform_pivot_point", "ACTIVE_ELEMENT")
            tool_settings.snap_target = tool_settings_dict.get("snap_target", "ACTIVE")
            tool_settings.use_snap_self = tool_settings_dict.get("use_snap_self", True)
            tool_settings.use_snap_align_rotation = tool_settings_dict.get("use_snap_align_rotation", False)
            tool_settings.use_snap_peel_object = tool_settings_dict.get("use_snap_peel_object", True)
            tool_settings.use_snap_backface_culling = tool_settings_dict.get("use_snap_backface_culling", False)
            tool_settings.use_snap_selectable = tool_settings_dict.get("use_snap_selectable", False)
            tool_settings.use_snap_translate = tool_settings_dict.get("use_snap_translate", False)
            tool_settings.use_snap_rotate = tool_settings_dict.get("use_snap_rotate", False)
            tool_settings.use_snap_scale = tool_settings_dict.get("use_snap_scale", False)
            tool_settings.use_snap_to_same_target = tool_settings_dict.get("use_snap_to_same_target", False)
            
            # Apply transformation orientation
            bpy.context.scene.transform_orientation_slots[0].type = combo_data.get("TRANSFORMATION", "GLOBAL")
            
            self.report({"INFO"}, f"Snap Combo {self.idx} Loaded.")
        return {"FINISHED"}

