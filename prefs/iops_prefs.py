import bpy
import os
import json
from .addon_preferences import IOPS_AddonPreferences


def get_iops_prefs():
    prefs = bpy.context.preferences.addons['InteractionOps'].preferences
    snap_combo_dict = {}

    # Helper to get default from class
    def get_default(attr):
        return getattr(IOPS_AddonPreferences, attr).keywords.get('default', None)

    # Default snap combo structure
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

    # Load snap combos from JSON file (Blender 5.0 compatible)
    path = bpy.utils.script_path_user()
    iops_prefs_file = os.path.join(path, "presets", "IOPS", "iops_prefs_user.json")
    
    snap_combos_from_json = {}
    if os.path.exists(iops_prefs_file):
        try:
            with open(iops_prefs_file, "r", encoding='utf-8') as f:
                content = f.read().strip()
                if content:  # Only parse if file is not empty
                    iops_prefs = json.loads(content)
                    if isinstance(iops_prefs, dict):
                        snap_combos_from_json = iops_prefs.get("SNAP_COMBOS", {})
                        if not isinstance(snap_combos_from_json, dict):
                            snap_combos_from_json = {}
                    else:
                        snap_combos_from_json = {}
        except (json.JSONDecodeError, IOError, UnicodeDecodeError, Exception) as e:
            print(f"IOPS Prefs: Error loading snap combos from JSON - {e}")
            snap_combos_from_json = {}

    for i in range(1, 9):
        snap_combo_key = f"snap_combo_{i}"
        
        # Try to get from JSON file first
        if snap_combo_key in snap_combos_from_json:
            snap_combo = snap_combos_from_json[snap_combo_key]
            if isinstance(snap_combo, dict):
                try:
                    # Get SNAP_ELEMENTS with proper defaults
                    snap_elements_data = snap_combo.get("SNAP_ELEMENTS", {})
                    if not isinstance(snap_elements_data, dict):
                        snap_elements_data = {}
                    
                    snap_elements = {k: snap_elements_data.get(k, default_combo["SNAP_ELEMENTS"].get(k, False)) 
                                    for k in default_combo["SNAP_ELEMENTS"].keys()}
                    
                    # Get TOOL_SETTINGS with proper defaults
                    tool_settings_data = snap_combo.get("TOOL_SETTINGS", {})
                    if not isinstance(tool_settings_data, dict):
                        tool_settings_data = {}
                    
                    tool_settings = {}
                    for k, default_value in default_combo["TOOL_SETTINGS"].items():
                        value = tool_settings_data.get(k, default_value)
                        # Validate type matches default
                        if type(value) != type(default_value):
                            value = default_value
                        tool_settings[k] = value
                    
                    # Get TRANSFORMATION with validation
                    transformation = snap_combo.get("TRANSFORMATION", "GLOBAL")
                    if not isinstance(transformation, str):
                        transformation = "GLOBAL"
                    
                    snap_combo_dict[snap_combo_key] = {
                        "SNAP_ELEMENTS": snap_elements,
                        "TOOL_SETTINGS": tool_settings,
                        "TRANSFORMATION": transformation
                    }
                    continue
                except Exception as e:
                    print(f"IOPS Prefs: Error parsing snap combo {snap_combo_key} - {e}, using defaults")
        
        # Fallback to default if not found in JSON or error occurred
        import copy
        snap_combo_dict[snap_combo_key] = copy.deepcopy(default_combo)

    # Helper for safe getattr with fallback to class default
    def safe(attr, default=None):
        return getattr(prefs, attr, get_default(attr) if default is None else default)

    # Helper for safe list conversion
    def safelist(attr, default=None):
        return list(getattr(prefs, attr, get_default(attr) if default is None else default))

    iops_prefs = {
        "IOPS_DEBUG": {"IOPS_DEBUG": safe("IOPS_DEBUG", False)},
        "ALIGN_TO_EDGE": {"align_edge_color": safelist("align_edge_color", (1.0, 1.0, 1.0, 1.0))},
        "EXECUTOR": {
            "executor_column_count": safe("executor_column_count", 20),
            "executor_scripts_folder": safe("executor_scripts_folder", bpy.utils.script_path_user()),
            "executor_name_length": safe("executor_name_length", 100),
            "executor_use_script_path_user": safe("executor_use_script_path_user", True),
            "executor_scripts_subfolder": safe("executor_scripts_subfolder", "iops_exec"),
        },
        "SPLIT_AREA_PIES": {
            f"PIE_{i}": {
                f"split_area_pie_{i}_factor": safe(f"split_area_pie_{i}_factor", 0.5),
                f"split_area_pie_{i}_pos": safe(f"split_area_pie_{i}_pos", "BOTTOM"),
                f"split_area_pie_{i}_ui": safe(f"split_area_pie_{i}_ui", "VIEW_3D"),
                f"split_area_pie_{i}_alt_ui": safe(f"split_area_pie_{i}_alt_ui", "VIEW_3D")
            } for i in range(1, 10) if i != 5
        },
        "UI_TEXT": {
            "text_color": safelist("text_color", (1.0, 1.0, 1.0, 1.0)),
            "text_color_key": safelist("text_color_key", (1.0, 1.0, 1.0, 1.0)),
            "text_pos_x": safe("text_pos_x", 60),
            "text_pos_y": safe("text_pos_y", 60),
            "text_shadow_color": safelist("text_shadow_color", (0.0, 0.0, 0.0, 1.0)),
            "text_shadow_pos_x": safe("text_shadow_pos_x", 2),
            "text_shadow_pos_y": safe("text_shadow_pos_y", -2),
            "text_shadow_toggle": safe("text_shadow_toggle", False),
            "text_size": safe("text_size", 20)
        },
        "UI_TEXT_STAT": {
            "iops_stat": safe("iops_stat", True),
            "show_filename_stat": safe("show_filename_stat", True),
            "text_color_stat": safelist("text_color_stat", (1.0, 1.0, 1.0, 1.0)),
            "text_color_key_stat": safelist("text_color_key_stat", (1.0, 1.0, 1.0, 1.0)),
            "text_color_error_stat": safelist("text_color_error_stat", (1.0, 0.0, 0.0, 1.0)),
            "text_pos_x_stat": safe("text_pos_x_stat", 9),
            "text_pos_y_stat": safe("text_pos_y_stat", 220),
            "text_shadow_color_stat": safelist("text_shadow_color_stat", (0.0, 0.0, 0.0, 1.0)),
            "text_shadow_pos_x_stat": safe("text_shadow_pos_x_stat", 2),
            "text_shadow_pos_y_stat": safe("text_shadow_pos_y_stat", -2),
            "text_shadow_toggle_stat": safe("text_shadow_toggle_stat", False),
            "text_size_stat": safe("text_size_stat", 20),
            "text_column_offset_stat": safe("text_column_offset_stat", 30),
            "text_column_width_stat": safe("text_column_width_stat", 4)
        },
        "VISUAL_ORIGIN": {
            "vo_cage_ap_color": safelist("vo_cage_ap_color", (1.0, 1.0, 1.0, 1.0)),
            "vo_cage_ap_size": safe("vo_cage_ap_size", 4),
            "vo_cage_color": safelist("vo_cage_color", (1.0, 1.0, 1.0, 1.0)),
            "vo_cage_p_size": safe("vo_cage_p_size", 2),
            "vo_cage_points_color": safelist("vo_cage_points_color", (1.0, 1.0, 1.0, 1.0)),
            "vo_cage_line_thickness": safe("vo_cage_line_thickness", 0.25)
        },
        "TEXTURE_TO_MATERIAL": {
            "texture_to_material_prefixes": safe("texture_to_material_prefixes", "env_"),
            "texture_to_material_suffixes": safe("texture_to_material_suffixes", "_df,_dfa,_mk,_emk,_nm")
        },
        "SNAP_COMBOS": {
            f"snap_combo_{i}": snap_combo_dict[f"snap_combo_{i}"] for i in range(1, 9)
        },
        "DRAG_SNAP": {
            "drag_snap_line_thickness": safe("drag_snap_line_thickness", 0.25)
        },
        "MODIFIER_WINDOW": {
            "modifier_window_method": safe("modifier_window_method", "RENDER")
        },
        "CURSOR_BISECT": {
            "cursor_bisect_plane_color": safelist("cursor_bisect_plane_color", (1.0, 0.0, 0.0, 0.15)),
            "cursor_bisect_plane_outline_color": safelist("cursor_bisect_plane_outline_color", (1.0, 0.0, 0.0, 0.8)),
            "cursor_bisect_plane_outline_thickness": safe("cursor_bisect_plane_outline_thickness", 2.0),
            "cursor_bisect_edge_color": safelist("cursor_bisect_edge_color", (1.0, 1.0, 0.0, 1.0)),
            "cursor_bisect_edge_locked_color": safelist("cursor_bisect_edge_locked_color", (1.0, 0.0, 0.0, 1.0)),
            "cursor_bisect_edge_thickness": safe("cursor_bisect_edge_thickness", 4.0),
            "cursor_bisect_edge_locked_thickness": safe("cursor_bisect_edge_locked_thickness", 8.0),
            "cursor_bisect_snap_color": safelist("cursor_bisect_snap_color", (1.0, 1.0, 0.0, 1.0)),
            "cursor_bisect_snap_hold_color": safelist("cursor_bisect_snap_hold_color", (1.0, 0.5, 0.0, 1.0)),
            "cursor_bisect_snap_closest_color": safelist("cursor_bisect_snap_closest_color", (0.0, 1.0, 0.0, 1.0)),
            "cursor_bisect_snap_closest_hold_color": safelist("cursor_bisect_snap_closest_hold_color", (1.0, 0.2, 0.0, 1.0)),
            "cursor_bisect_snap_size": safe("cursor_bisect_snap_size", 6.0),
            "cursor_bisect_snap_closest_size": safe("cursor_bisect_snap_closest_size", 9.0),
            "cursor_bisect_edge_subdivisions": safe("cursor_bisect_edge_subdivisions", 1),
            "cursor_bisect_cut_preview_color": safelist("cursor_bisect_cut_preview_color", (1.0, 0.5, 0.0, 1.0)),
            "cursor_bisect_cut_preview_thickness": safe("cursor_bisect_cut_preview_thickness", 3.0),
            "cursor_bisect_face_depth": safe("cursor_bisect_face_depth", 5),
            "cursor_bisect_max_faces": safe("cursor_bisect_max_faces", 1000),
            "cursor_bisect_merge_distance": safe("cursor_bisect_merge_distance", 0.005),
            "cursor_bisect_rotation_step": safe("cursor_bisect_rotation_step", 45.0),
            "cursor_bisect_distance_text_color": safelist("cursor_bisect_distance_text_color", (1.0, 1.0, 0.0, 1.0)),
            "cursor_bisect_distance_text_size": safe("cursor_bisect_distance_text_size", 12.0),
            "cursor_bisect_distance_offset_x": safe("cursor_bisect_distance_offset_x", -25),
            "cursor_bisect_distance_offset_y": safe("cursor_bisect_distance_offset_y", 25),
        },
    }

    return iops_prefs