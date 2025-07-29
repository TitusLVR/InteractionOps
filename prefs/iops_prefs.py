import bpy
from .addon_preferences import IOPS_AddonPreferences


def get_iops_prefs():
    prefs = bpy.context.preferences.addons['InteractionOps'].preferences
    snap_combo_dict = {}

    # Helper to get default from class
    def get_default(attr):
        return getattr(IOPS_AddonPreferences, attr).keywords.get('default', None)

    for i in range(1, 9):
        snap_combo_key = f"snap_combo_{i}"
        try:
            snap_combo = prefs[snap_combo_key]
            snap_combo_dict[snap_combo_key] = {
                "SNAP_ELEMENTS": {k: snap_combo["SNAP_ELEMENTS"].get(k, False) for k in [
                    "INCREMENT", "VERTEX", "EDGE", "FACE", "VOLUME", "EDGE_MIDPOINT", "EDGE_PERPENDICULAR", "FACE_PROJECT", "FACE_NEAREST"
                ]},
                "TOOL_SETTINGS": {k: snap_combo["TOOL_SETTINGS"].get(k, False) if isinstance(snap_combo["TOOL_SETTINGS"].get(k, None), bool) else snap_combo["TOOL_SETTINGS"].get(k, "") for k in [
                    "transform_pivot_point", "snap_target", "use_snap_self", "use_snap_align_rotation", "use_snap_peel_object", "use_snap_backface_culling", "use_snap_selectable", "use_snap_translate", "use_snap_rotate", "use_snap_scale", "use_snap_to_same_target"
                ]},
                "TRANSFORMATION": snap_combo.get("TRANSFORMATION", "GLOBAL")
            }
        except Exception:
            snap_combo_dict[snap_combo_key] = {
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
                f"split_area_pie_{i}_ui": safe(f"split_area_pie_{i}_ui", "VIEW_3D")
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