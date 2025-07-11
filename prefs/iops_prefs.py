import bpy


def get_iops_prefs():
    prefs = bpy.context.preferences.addons['InteractionOps'].preferences
    snap_combo_dict = {}

    for i in range(1, 9):
        try:
            snap_combo_key = f"snap_combo_{i}"
            snap_combo_dict[snap_combo_key] = {
                "SNAP_ELEMENTS": {k: prefs[snap_combo_key]["SNAP_ELEMENTS"][k] for k in prefs[snap_combo_key]["SNAP_ELEMENTS"] if prefs[snap_combo_key]["SNAP_ELEMENTS"][k]},
                "TOOL_SETTINGS": {k: prefs[snap_combo_key]["TOOL_SETTINGS"][k] for k in prefs[snap_combo_key]["TOOL_SETTINGS"]},
                "TRANSFORMATION": prefs[snap_combo_key]["TRANSFORMATION"]
            }
        except KeyError:
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

    iops_prefs = {
        "IOPS_DEBUG": {"IOPS_DEBUG": prefs.IOPS_DEBUG},
        "ALIGN_TO_EDGE": {"align_edge_color": list(prefs.align_edge_color)},
        "EXECUTOR": {
            "executor_column_count": prefs.executor_column_count,
            "executor_scripts_folder": prefs.executor_scripts_folder,
            "executor_name_length": prefs.executor_name_length,
            "executor_use_script_path_user": prefs.executor_use_script_path_user,
            "executor_scripts_subfolder": prefs.executor_scripts_subfolder,
            },
    "SPLIT_AREA_PIES": {
        f"PIE_{i}": {
            f"split_area_pie_{i}_factor": getattr(prefs, f"split_area_pie_{i}_factor"),
            f"split_area_pie_{i}_pos": getattr(prefs, f"split_area_pie_{i}_pos"),
            f"split_area_pie_{i}_ui": getattr(prefs, f"split_area_pie_{i}_ui")
        } for i in range(1, 10) if i != 5 # Exclude non-existing pie 5
    },
        "UI_TEXT": {
            "text_color": list(prefs.text_color),
            "text_color_key": list(prefs.text_color_key),
            "text_pos_x": prefs.text_pos_x,
            "text_pos_y": prefs.text_pos_y,
            "text_shadow_color": list(prefs.text_shadow_color),
            "text_shadow_pos_x": prefs.text_shadow_pos_x,
            "text_shadow_pos_y": prefs.text_shadow_pos_y,
            "text_shadow_toggle": prefs.text_shadow_toggle,
            "text_size": prefs.text_size
            },
        "UI_TEXT_STAT": {
            "iops_stat" : prefs.iops_stat,
            "text_color_stat": list(prefs.text_color_stat),
            "text_color_key_stat": list(prefs.text_color_key_stat),
            "text_color_error_stat": list(prefs.text_color_error_stat),
            "text_pos_x_stat": prefs.text_pos_x_stat,
            "text_pos_y_stat": prefs.text_pos_y_stat,
            "text_shadow_color_stat": list(prefs.text_shadow_color_stat),
            "text_shadow_pos_x_stat": prefs.text_shadow_pos_x_stat,
            "text_shadow_pos_y_stat": prefs.text_shadow_pos_y_stat,
            "text_shadow_toggle_stat": prefs.text_shadow_toggle_stat,
            "text_size_stat": prefs.text_size_stat,
            "text_column_offset_stat": prefs.text_column_offset_stat,
            "text_column_width_stat": prefs.text_column_width_stat
            },
        "VISUAL_ORIGIN": {
            "vo_cage_ap_color": list(prefs.vo_cage_ap_color),
            "vo_cage_ap_size": prefs.vo_cage_ap_size,
            "vo_cage_color": list(prefs.vo_cage_color),
            "vo_cage_p_size": prefs.vo_cage_p_size,
            "vo_cage_points_color": list(prefs.vo_cage_points_color),
            "vo_cage_line_thickness": prefs.vo_cage_line_thickness
            },
        "TEXTURE_TO_MATERIAL": {
            "texture_to_material_prefixes": prefs.texture_to_material_prefixes,
            "texture_to_material_suffixes": prefs.texture_to_material_suffixes
            },
        "SNAP_COMBOS": {
            "snap_combo_1": snap_combo_dict["snap_combo_1"],
            "snap_combo_2": snap_combo_dict["snap_combo_2"],
            "snap_combo_3": snap_combo_dict["snap_combo_3"],
            "snap_combo_4": snap_combo_dict["snap_combo_4"],
            "snap_combo_5": snap_combo_dict["snap_combo_5"],
            "snap_combo_6": snap_combo_dict["snap_combo_6"],
            "snap_combo_7": snap_combo_dict["snap_combo_7"],
            "snap_combo_8": snap_combo_dict["snap_combo_8"]
            },
        "DRAG_SNAP": {
            "drag_snap_line_thickness": prefs.drag_snap_line_thickness
            },
        "CURSOR_BISECT": {
            "cursor_bisect_plane_color": list(prefs.cursor_bisect_plane_color),
            "cursor_bisect_plane_outline_color": list(prefs.cursor_bisect_plane_outline_color),
            "cursor_bisect_plane_outline_thickness": prefs.cursor_bisect_plane_outline_thickness,
            "cursor_bisect_edge_color": list(prefs.cursor_bisect_edge_color),
            "cursor_bisect_edge_locked_color": list(prefs.cursor_bisect_edge_locked_color),
            "cursor_bisect_edge_thickness": prefs.cursor_bisect_edge_thickness,
            "cursor_bisect_edge_locked_thickness": prefs.cursor_bisect_edge_locked_thickness,
            "cursor_bisect_snap_color": list(prefs.cursor_bisect_snap_color),
            "cursor_bisect_snap_hold_color": list(prefs.cursor_bisect_snap_hold_color),
            "cursor_bisect_snap_closest_color": list(prefs.cursor_bisect_snap_closest_color),
            "cursor_bisect_snap_closest_hold_color": list(prefs.cursor_bisect_snap_closest_hold_color),
            "cursor_bisect_snap_size": prefs.cursor_bisect_snap_size,
            "cursor_bisect_snap_closest_size": prefs.cursor_bisect_snap_closest_size,
            },
        }

    # # Update snap combos if exist in prefs
    # if getattr(prefs, "snap_combos", False):
    #     for i in range(1, 9):
    #         snap_combo = prefs.snap_combos[i-1]
    #         iops_prefs[f"snap_combo_{i}"] = snap_combo

    return iops_prefs