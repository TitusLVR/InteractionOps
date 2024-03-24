import bpy


def get_iops_prefs():
    prefs = bpy.context.preferences.addons['InteractionOps'].preferences
    iops_prefs = {
        "IOPS_DEBUG": {"IOPS_DEBUG": prefs.IOPS_DEBUG},
        "ALIGN_TO_EDGE": {"align_edge_color": list(prefs.align_edge_color)},
        "EXECUTOR": {
            "executor_column_count": prefs.executor_column_count,
            "executor_scripts_folder": prefs.executor_scripts_folder
            },
        "SPLIT_AREA_PIES": {
            "PIE_1": {
                    "split_area_pie_1_factor": prefs.split_area_pie_1_factor,
                    "split_area_pie_1_pos": prefs.split_area_pie_1_pos,
                    "split_area_pie_1_ui": prefs.split_area_pie_1_ui
            },
            "PIE_2": {
                    "split_area_pie_2_factor": prefs.split_area_pie_2_factor,
                    "split_area_pie_2_pos": prefs.split_area_pie_2_pos,
                    "split_area_pie_2_ui": prefs.split_area_pie_2_ui
            },
            "PIE_3": {
                    "split_area_pie_3_factor": prefs.split_area_pie_3_factor,
                    "split_area_pie_3_pos": prefs.split_area_pie_3_pos,
                    "split_area_pie_3_ui": prefs.split_area_pie_3_ui
            },
            "PIE_4": {
                    "split_area_pie_4_factor": prefs.split_area_pie_4_factor,
                    "split_area_pie_4_pos": prefs.split_area_pie_4_pos,
                    "split_area_pie_4_ui": prefs.split_area_pie_4_ui
            },
            "PIE_6": {
                    "split_area_pie_6_factor": prefs.split_area_pie_6_factor,
                    "split_area_pie_6_pos": prefs.split_area_pie_6_pos,
                    "split_area_pie_6_ui": prefs.split_area_pie_6_ui
            },
            "PIE_7": {
                    "split_area_pie_7_factor": prefs.split_area_pie_7_factor,
                    "split_area_pie_7_pos": prefs.split_area_pie_7_pos,
                    "split_area_pie_7_ui": prefs.split_area_pie_7_ui
            },
            "PIE_8": {
                    "split_area_pie_8_factor": prefs.split_area_pie_8_factor,
                    "split_area_pie_8_pos": prefs.split_area_pie_8_pos,
                    "split_area_pie_8_ui": prefs.split_area_pie_8_ui
            },
            "PIE_9": {
                    "split_area_pie_9_factor": prefs.split_area_pie_9_factor,
                    "split_area_pie_9_pos": prefs.split_area_pie_9_pos,
                    "split_area_pie_9_ui": prefs.split_area_pie_9_ui
                    }
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
        "VISUAL_ORIGIN": {
            "vo_cage_ap_color": list(prefs.vo_cage_ap_color),
            "vo_cage_ap_size": prefs.vo_cage_ap_size,
            "vo_cage_color": list(prefs.vo_cage_color),
            "vo_cage_p_size": prefs.vo_cage_p_size,
            "vo_cage_points_color": list(prefs.vo_cage_points_color)
            },
        "TEXTURE_TO_MATERIAL": {
            "texture_to_material_prefixes": prefs.texture_to_material_prefixes,
            "texture_to_material_suffixes": prefs.texture_to_material_suffixes
            },
        "SWITCH_LIST": {
            "switch_list_axis": prefs.switch_list_axis,
            "switch_list_ppoint": prefs.switch_list_ppoint,
            "switch_list_snap": prefs.switch_list_snap,
            },
        "SNAP_COMBOS": {
            "snap_combo_1": {
                "SNAP_ELEMENTS": {
                    "INCREMENT": False,
                    "VERTEX": False,
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
                    "use_snap_grid_absolute": False,
                    "use_snap_self": False,
                    "use_snap_align_rotation": False,
                    "use_snap_peel_object": False,
                    "use_snap_backface_culling": False,
                    "use_snap_selectable": False,
                    "use_snap_translate": False,
                    "use_snap_rotate": False,
                    "use_snap_scale": False,
                    "use_snap_to_same_target": False
                },
                "TRANSFORMATION": "GLOBAL"
            },
            "snap_combo_2": {
                "SNAP_ELEMENTS": {
                    "INCREMENT": False,
                    "VERTEX": False,
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
                    "use_snap_grid_absolute": False,
                    "use_snap_self": False,
                    "use_snap_align_rotation": False,
                    "use_snap_peel_object": False,
                    "use_snap_backface_culling": False,
                    "use_snap_selectable": False,
                    "use_snap_translate": False,
                    "use_snap_rotate": False,
                    "use_snap_scale": False,
                    "use_snap_to_same_target": False
                },
                "TRANSFORMATION": "GLOBAL"
            },
            "snap_combo_3": {
                "SNAP_ELEMENTS": {
                    "INCREMENT": False,
                    "VERTEX": False,
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
                    "use_snap_grid_absolute": False,
                    "use_snap_self": False,
                    "use_snap_align_rotation": False,
                    "use_snap_peel_object": False,
                    "use_snap_backface_culling": False,
                    "use_snap_selectable": False,
                    "use_snap_translate": False,
                    "use_snap_rotate": False,
                    "use_snap_scale": False,
                    "use_snap_to_same_target": False
                },
                "TRANSFORMATION": "GLOBAL"
            },
            "snap_combo_4": {
                "SNAP_ELEMENTS": {
                    "INCREMENT": False,
                    "VERTEX": False,
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
                    "use_snap_grid_absolute": False,
                    "use_snap_self": False,
                    "use_snap_align_rotation": False,
                    "use_snap_peel_object": False,
                    "use_snap_backface_culling": False,
                    "use_snap_selectable": False,
                    "use_snap_translate": False,
                    "use_snap_rotate": False,
                    "use_snap_scale": False,
                    "use_snap_to_same_target": False
                },
                "TRANSFORMATION": "GLOBAL"
            },
            "snap_combo_5": {
                "SNAP_ELEMENTS": {
                    "INCREMENT": False,
                    "VERTEX": False,
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
                    "use_snap_grid_absolute": False,
                    "use_snap_self": False,
                    "use_snap_align_rotation": False,
                    "use_snap_peel_object": False,
                    "use_snap_backface_culling": False,
                    "use_snap_selectable": False,
                    "use_snap_translate": False,
                    "use_snap_rotate": False,
                    "use_snap_scale": False,
                    "use_snap_to_same_target": False
                },
                "TRANSFORMATION": "GLOBAL"
            },
            "snap_combo_6": {
                "SNAP_ELEMENTS": {
                    "INCREMENT": False,
                    "VERTEX": False,
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
                    "use_snap_grid_absolute": False,
                    "use_snap_self": False,
                    "use_snap_align_rotation": False,
                    "use_snap_peel_object": False,
                    "use_snap_backface_culling": False,
                    "use_snap_selectable": False,
                    "use_snap_translate": False,
                    "use_snap_rotate": False,
                    "use_snap_scale": False,
                    "use_snap_to_same_target": False
                },
                "TRANSFORMATION": "GLOBAL"
            },
            "snap_combo_7": {
                "SNAP_ELEMENTS": {
                    "INCREMENT": False,
                    "VERTEX": False,
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
                    "use_snap_grid_absolute": False,
                    "use_snap_self": False,
                    "use_snap_align_rotation": False,
                    "use_snap_peel_object": False,
                    "use_snap_backface_culling": False,
                    "use_snap_selectable": False,
                    "use_snap_translate": False,
                    "use_snap_rotate": False,
                    "use_snap_scale": False,
                    "use_snap_to_same_target": False
                },
                "TRANSFORMATION": "GLOBAL"
            },
            "snap_combo_8": {
                "SNAP_ELEMENTS": {
                    "INCREMENT": False,
                    "VERTEX": False,
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
                    "use_snap_grid_absolute": False,
                    "use_snap_self": False,
                    "use_snap_align_rotation": False,
                    "use_snap_peel_object": False,
                    "use_snap_backface_culling": False,
                    "use_snap_selectable": False,
                    "use_snap_translate": False,
                    "use_snap_rotate": False,
                    "use_snap_scale": False,
                    "use_snap_to_same_target": False
                },
                "TRANSFORMATION": "GLOBAL"
            },
            },
        }

    # Update snap combos if exist in prefs
    if getattr(prefs, "snap_combos", False):
        for i in range(1, 9):
            snap_combo = prefs.snap_combos[i-1]
            iops_prefs["SNAP_COMBOS"][f"snap_combo_{i}"] = snap_combo


    return iops_prefs