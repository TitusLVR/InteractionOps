import bpy
import os
import json
from ...prefs.iops_prefs import get_iops_prefs
from ...utils.split_areas_dict import split_areas_dict, split_areas_position_list

# Save Addon Preferences
def save_iops_preferences():
    """Save addon preferences to JSON file with error handling"""
    try:
        iops_prefs = get_iops_prefs()
        path = bpy.utils.script_path_user()
        folder = os.path.join(path, "presets", "IOPS")
        iops_prefs_file = os.path.join(path, "presets", "IOPS", "iops_prefs_user.json")

        # Create directory if it doesn't exist
        os.makedirs(folder, exist_ok=True)

        # Write to a temporary file first, then rename (atomic operation)
        temp_file = iops_prefs_file + ".tmp"
        with open(temp_file, "w", encoding='utf-8') as f:
            json.dump(iops_prefs, f, indent=4)
        
        # Replace the old file with the new one
        if os.path.exists(iops_prefs_file):
            os.replace(temp_file, iops_prefs_file)
        else:
            os.rename(temp_file, iops_prefs_file)
        
        print(f"IOPS Preferences saved successfully to: {iops_prefs_file}")
        return True
        
    except Exception as e:
        print(f"IOPS Preferences: Error saving preferences - {e}")
        # Clean up temp file if it exists
        if os.path.exists(temp_file):
            try:
                os.remove(temp_file)
            except Exception:
                pass
        return False


def get_split_pos_ui(pos, ui):
    for p in split_areas_position_list:
        if p[0] == pos:
            pos_num = p[4]
    for key, value in split_areas_dict.items():
        if value["ui"] == ui:
            ui_num = value["num"]
    return pos_num, ui_num


# Load Addon Preferences
def load_iops_preferences():
    prefs = bpy.context.preferences.addons["InteractionOps"].preferences
    path = bpy.utils.script_path_user()
    iops_prefs_file = os.path.join(path, "presets", "IOPS", "iops_prefs_user.json")
    
    # Get default preferences structure for fallback
    default_prefs = get_iops_prefs()
    
    try:
        # Check if file exists
        if not os.path.exists(iops_prefs_file):
            print("IOPS Preferences file not found. Creating new one with defaults at:", iops_prefs_file)
            save_iops_preferences()
            return
        
        # Try to load and parse JSON
        try:
            with open(iops_prefs_file, "r", encoding='utf-8') as f:
                iops_prefs = json.load(f)
        except json.JSONDecodeError as e:
            print(f"IOPS Preferences: JSON decode error - {e}. Using defaults and creating backup.")
            # Backup corrupted file
            backup_file = iops_prefs_file + ".backup"
            try:
                os.rename(iops_prefs_file, backup_file)
                print(f"Corrupted preferences backed up to: {backup_file}")
            except Exception:
                pass
            save_iops_preferences()
            return
        except Exception as e:
            print(f"IOPS Preferences: Error reading file - {e}. Using defaults.")
            save_iops_preferences()
            return
        
        # Validate that iops_prefs is a dictionary
        if not isinstance(iops_prefs, dict):
            print("IOPS Preferences: Invalid file format. Using defaults.")
            save_iops_preferences()
            return
        
        # Safe get helper with default fallback
        def safe_get(data, key, default=None):
            """Safely get value from dict with default fallback"""
            try:
                return data.get(key, default)
            except (AttributeError, KeyError):
                return default
        
        # Process each preference section with error handling
        for key, value in iops_prefs.items():
            try:
                match key:
                    case "IOPS_DEBUG":
                        if isinstance(value, dict):
                            prefs.IOPS_DEBUG = safe_get(value, "IOPS_DEBUG", 
                                default_prefs.get("IOPS_DEBUG", {}).get("IOPS_DEBUG", False))
                    
                    case "ALIGN_TO_EDGE":
                        if isinstance(value, dict):
                            prefs.align_edge_color = safe_get(value, "align_edge_color",
                                default_prefs.get("ALIGN_TO_EDGE", {}).get("align_edge_color", (1.0, 1.0, 1.0, 1.0)))
                    
                    case "EXECUTOR":
                        if isinstance(value, dict):
                            defaults = default_prefs.get("EXECUTOR", {})
                            prefs.executor_scripts_folder = safe_get(value, "executor_scripts_folder",
                                defaults.get("executor_scripts_folder", bpy.utils.script_path_user()))
                            prefs.executor_column_count = safe_get(value, "executor_column_count",
                                defaults.get("executor_column_count", 20))
                            # Handle old typo in JSON key
                            prefs.executor_name_length = safe_get(value, "executor_name_length",
                                safe_get(value, "executor_name_lenght", defaults.get("executor_name_length", 100)))
                            prefs.executor_use_script_path_user = safe_get(value, "executor_use_script_path_user",
                                defaults.get("executor_use_script_path_user", True))
                            prefs.executor_scripts_subfolder = safe_get(value, "executor_scripts_subfolder",
                                defaults.get("executor_scripts_subfolder", "iops_exec"))
                    
                    case "SPLIT_AREA_PIES":
                        if isinstance(value, dict):
                            defaults = default_prefs.get("SPLIT_AREA_PIES", {})
                            for pie in value:
                                try:
                                    pie_num = pie[-1]
                                    pie_data = safe_get(value, pie, {})
                                    if not isinstance(pie_data, dict):
                                        continue
                                    
                                    # Get default values for this pie
                                    pie_defaults = defaults.get(pie, {})
                                    
                                    # Get the raw values from JSON
                                    pos_raw = safe_get(pie_data, f"split_area_pie_{pie_num}_pos",
                                        pie_defaults.get(f"split_area_pie_{pie_num}_pos", "BOTTOM"))
                                    ui_raw = safe_get(pie_data, f"split_area_pie_{pie_num}_ui",
                                        pie_defaults.get(f"split_area_pie_{pie_num}_ui", "VIEW_3D"))
                                    
                                    # Convert old numeric format to string enum format if needed
                                    if isinstance(pos_raw, int):
                                        for p in split_areas_position_list:
                                            if p[4] == pos_raw:
                                                pos = p[0]
                                                break
                                        else:
                                            pos = "BOTTOM"
                                    else:
                                        pos = pos_raw
                                    
                                    if isinstance(ui_raw, int):
                                        for split_key, val in split_areas_dict.items():
                                            if val["num"] == ui_raw:
                                                ui = val["ui"]
                                                break
                                        else:
                                            ui = "VIEW_3D"
                                    else:
                                        ui = ui_raw
                                    
                                    setattr(prefs, f"split_area_pie_{pie_num}_factor",
                                        safe_get(pie_data, f"split_area_pie_{pie_num}_factor",
                                        pie_defaults.get(f"split_area_pie_{pie_num}_factor", 0.5)))
                                    setattr(prefs, f"split_area_pie_{pie_num}_pos", pos)
                                    setattr(prefs, f"split_area_pie_{pie_num}_ui", ui)
                                    
                                    # Handle alt_ui if it exists
                                    if f"split_area_pie_{pie_num}_alt_ui" in pie_data:
                                        alt_ui_raw = safe_get(pie_data, f"split_area_pie_{pie_num}_alt_ui",
                                            pie_defaults.get(f"split_area_pie_{pie_num}_alt_ui", "VIEW_3D"))
                                        if isinstance(alt_ui_raw, int):
                                            for split_key, val in split_areas_dict.items():
                                                if val["num"] == alt_ui_raw:
                                                    alt_ui = val["ui"]
                                                    break
                                            else:
                                                alt_ui = "VIEW_3D"
                                        else:
                                            alt_ui = alt_ui_raw
                                        setattr(prefs, f"split_area_pie_{pie_num}_alt_ui", alt_ui)
                                except Exception as e:
                                    print(f"IOPS Prefs: Error loading split area pie {pie} - {e}")
                                    continue
                    
                    case "UI_TEXT":
                        if isinstance(value, dict):
                            defaults = default_prefs.get("UI_TEXT", {})
                            prefs.text_color = safe_get(value, "text_color", defaults.get("text_color", (1.0, 1.0, 1.0, 1.0)))
                            prefs.text_color_key = safe_get(value, "text_color_key", defaults.get("text_color_key", (1.0, 1.0, 1.0, 1.0)))
                            prefs.text_pos_x = safe_get(value, "text_pos_x", defaults.get("text_pos_x", 60))
                            prefs.text_pos_y = safe_get(value, "text_pos_y", defaults.get("text_pos_y", 60))
                            prefs.text_shadow_color = safe_get(value, "text_shadow_color", defaults.get("text_shadow_color", (0.0, 0.0, 0.0, 1.0)))
                            prefs.text_shadow_pos_x = safe_get(value, "text_shadow_pos_x", defaults.get("text_shadow_pos_x", 2))
                            prefs.text_shadow_pos_y = safe_get(value, "text_shadow_pos_y", defaults.get("text_shadow_pos_y", -2))
                            prefs.text_shadow_toggle = safe_get(value, "text_shadow_toggle", defaults.get("text_shadow_toggle", False))
                            prefs.text_size = safe_get(value, "text_size", defaults.get("text_size", 20))
                    
                    case "CURSOR_BISECT":
                        if isinstance(value, dict):
                            defaults = default_prefs.get("CURSOR_BISECT", {})
                            prefs.cursor_bisect_plane_color = safe_get(value, "cursor_bisect_plane_color", defaults.get("cursor_bisect_plane_color", (1.0, 0.0, 0.0, 0.15)))
                            prefs.cursor_bisect_plane_outline_color = safe_get(value, "cursor_bisect_plane_outline_color", defaults.get("cursor_bisect_plane_outline_color", (1.0, 0.0, 0.0, 0.8)))
                            prefs.cursor_bisect_plane_outline_thickness = safe_get(value, "cursor_bisect_plane_outline_thickness", defaults.get("cursor_bisect_plane_outline_thickness", 2.0))
                            prefs.cursor_bisect_edge_color = safe_get(value, "cursor_bisect_edge_color", defaults.get("cursor_bisect_edge_color", (1.0, 1.0, 0.0, 1.0)))
                            prefs.cursor_bisect_edge_locked_color = safe_get(value, "cursor_bisect_edge_locked_color", defaults.get("cursor_bisect_edge_locked_color", (1.0, 0.0, 0.0, 1.0)))
                            prefs.cursor_bisect_edge_thickness = safe_get(value, "cursor_bisect_edge_thickness", defaults.get("cursor_bisect_edge_thickness", 4.0))
                            prefs.cursor_bisect_edge_locked_thickness = safe_get(value, "cursor_bisect_edge_locked_thickness", defaults.get("cursor_bisect_edge_locked_thickness", 8.0))
                            prefs.cursor_bisect_snap_color = safe_get(value, "cursor_bisect_snap_color", defaults.get("cursor_bisect_snap_color", (1.0, 1.0, 0.0, 1.0)))
                            prefs.cursor_bisect_snap_hold_color = safe_get(value, "cursor_bisect_snap_hold_color", defaults.get("cursor_bisect_snap_hold_color", (1.0, 0.5, 0.0, 1.0)))
                            prefs.cursor_bisect_snap_closest_color = safe_get(value, "cursor_bisect_snap_closest_color", defaults.get("cursor_bisect_snap_closest_color", (0.0, 1.0, 0.0, 1.0)))
                            prefs.cursor_bisect_snap_closest_hold_color = safe_get(value, "cursor_bisect_snap_closest_hold_color", defaults.get("cursor_bisect_snap_closest_hold_color", (1.0, 0.2, 0.0, 1.0)))
                            prefs.cursor_bisect_snap_size = safe_get(value, "cursor_bisect_snap_size", defaults.get("cursor_bisect_snap_size", 6.0))
                            prefs.cursor_bisect_snap_closest_size = safe_get(value, "cursor_bisect_snap_closest_size", defaults.get("cursor_bisect_snap_closest_size", 9.0))
                            prefs.cursor_bisect_edge_subdivisions = safe_get(value, "cursor_bisect_edge_subdivisions", defaults.get("cursor_bisect_edge_subdivisions", 1))
                            prefs.cursor_bisect_cut_preview_color = safe_get(value, "cursor_bisect_cut_preview_color", defaults.get("cursor_bisect_cut_preview_color", (1.0, 0.5, 0.0, 1.0)))
                            prefs.cursor_bisect_cut_preview_thickness = safe_get(value, "cursor_bisect_cut_preview_thickness", defaults.get("cursor_bisect_cut_preview_thickness", 3.0))
                            prefs.cursor_bisect_face_depth = safe_get(value, "cursor_bisect_face_depth", defaults.get("cursor_bisect_face_depth", 5))
                            prefs.cursor_bisect_max_faces = safe_get(value, "cursor_bisect_max_faces", defaults.get("cursor_bisect_max_faces", 1000))
                            prefs.cursor_bisect_merge_distance = safe_get(value, "cursor_bisect_merge_distance", defaults.get("cursor_bisect_merge_distance", 0.005))
                            prefs.cursor_bisect_rotation_step = safe_get(value, "cursor_bisect_rotation_step", defaults.get("cursor_bisect_rotation_step", 45.0))
                            prefs.cursor_bisect_distance_text_color = safe_get(value, "cursor_bisect_distance_text_color", defaults.get("cursor_bisect_distance_text_color", (1.0, 1.0, 0.0, 1.0)))
                            prefs.cursor_bisect_distance_text_size = safe_get(value, "cursor_bisect_distance_text_size", defaults.get("cursor_bisect_distance_text_size", 12.0))
                            prefs.cursor_bisect_distance_offset_x = safe_get(value, "cursor_bisect_distance_offset_x", defaults.get("cursor_bisect_distance_offset_x", -25))
                            prefs.cursor_bisect_distance_offset_y = safe_get(value, "cursor_bisect_distance_offset_y", defaults.get("cursor_bisect_distance_offset_y", 25))
                    
                    case "UI_TEXT_STAT":
                        if isinstance(value, dict):
                            defaults = default_prefs.get("UI_TEXT_STAT", {})
                            prefs.iops_stat = safe_get(value, "iops_stat", defaults.get("iops_stat", True))
                            prefs.show_filename_stat = safe_get(value, "show_filename_stat", defaults.get("show_filename_stat", True))
                            prefs.text_color_stat = safe_get(value, "text_color_stat", defaults.get("text_color_stat", (1.0, 1.0, 1.0, 1.0)))
                            prefs.text_color_key_stat = safe_get(value, "text_color_key_stat", defaults.get("text_color_key_stat", (1.0, 1.0, 1.0, 1.0)))
                            prefs.text_color_error_stat = safe_get(value, "text_color_error_stat", defaults.get("text_color_error_stat", (1.0, 0.0, 0.0, 1.0)))
                            prefs.text_pos_x_stat = safe_get(value, "text_pos_x_stat", defaults.get("text_pos_x_stat", 9))
                            prefs.text_pos_y_stat = safe_get(value, "text_pos_y_stat", defaults.get("text_pos_y_stat", 220))
                            prefs.text_shadow_color_stat = safe_get(value, "text_shadow_color_stat", defaults.get("text_shadow_color_stat", (0.0, 0.0, 0.0, 1.0)))
                            prefs.text_shadow_pos_x_stat = safe_get(value, "text_shadow_pos_x_stat", defaults.get("text_shadow_pos_x_stat", 2))
                            prefs.text_shadow_pos_y_stat = safe_get(value, "text_shadow_pos_y_stat", defaults.get("text_shadow_pos_y_stat", -2))
                            prefs.text_shadow_toggle_stat = safe_get(value, "text_shadow_toggle_stat", defaults.get("text_shadow_toggle_stat", False))
                            prefs.text_size_stat = safe_get(value, "text_size_stat", defaults.get("text_size_stat", 20))
                            prefs.text_column_offset_stat = safe_get(value, "text_column_offset_stat", defaults.get("text_column_offset_stat", 30))
                            prefs.text_column_width_stat = safe_get(value, "text_column_width_stat", defaults.get("text_column_width_stat", 4))
                    
                    case "VISUAL_ORIGIN":
                        if isinstance(value, dict):
                            defaults = default_prefs.get("VISUAL_ORIGIN", {})
                            prefs.vo_cage_ap_color = safe_get(value, "vo_cage_ap_color", defaults.get("vo_cage_ap_color", (1.0, 1.0, 1.0, 1.0)))
                            prefs.vo_cage_ap_size = safe_get(value, "vo_cage_ap_size", defaults.get("vo_cage_ap_size", 4))
                            prefs.vo_cage_color = safe_get(value, "vo_cage_color", defaults.get("vo_cage_color", (1.0, 1.0, 1.0, 1.0)))
                            prefs.vo_cage_p_size = safe_get(value, "vo_cage_p_size", defaults.get("vo_cage_p_size", 2))
                            prefs.vo_cage_points_color = safe_get(value, "vo_cage_points_color", defaults.get("vo_cage_points_color", (1.0, 1.0, 1.0, 1.0)))
                            prefs.vo_cage_line_thickness = safe_get(value, "vo_cage_line_thickness", defaults.get("vo_cage_line_thickness", 0.25))
                    
                    case "TEXTURE_TO_MATERIAL":
                        if isinstance(value, dict):
                            defaults = default_prefs.get("TEXTURE_TO_MATERIAL", {})
                            prefs.texture_to_material_prefixes = safe_get(value, "texture_to_material_prefixes",
                                defaults.get("texture_to_material_prefixes", "env_"))
                            prefs.texture_to_material_suffixes = safe_get(value, "texture_to_material_suffixes",
                                defaults.get("texture_to_material_suffixes", "_df,_dfa,_mk,_emk,_nm"))
                    
                    case "SNAP_COMBOS":
                        # In Blender 5.0, snap combos are stored in JSON file only
                        # No need to set ID properties - they're read directly from JSON
                        # This case is kept for compatibility but snap combos are handled
                        # directly in snap_combos.py via JSON file
                        pass
                    
                    case "DRAG_SNAP":
                        if isinstance(value, dict):
                            defaults = default_prefs.get("DRAG_SNAP", {})
                            prefs.drag_snap_line_thickness = safe_get(value, "drag_snap_line_thickness",
                                defaults.get("drag_snap_line_thickness", 0.25))
                    
                    case "MODIFIER_WINDOW":
                        if isinstance(value, dict):
                            defaults = default_prefs.get("MODIFIER_WINDOW", {})
                            prefs.modifier_window_method = safe_get(value, "modifier_window_method",
                                defaults.get("modifier_window_method", "RENDER"))
                    
                    case _:
                        print(f"IOPS Prefs: No entry for {key}")
            
            except Exception as e:
                print(f"IOPS Prefs: Error processing section '{key}' - {e}")
                continue
        
        # Save the preferences to ensure any missing attributes are filled with defaults
        print("IOPS Preferences loaded successfully.")
        
    except Exception as e:
        print(f"IOPS Preferences: Unexpected error - {e}. Creating new preferences file.")
        save_iops_preferences()
        return


class IOPS_OT_SaveAddonPreferences(bpy.types.Operator):
    bl_idname = "iops.save_addon_preferences"
    bl_label = "Save Addon Preferences"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        save_iops_preferences()
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
