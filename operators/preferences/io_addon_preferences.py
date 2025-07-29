import bpy
import os
import json
from ...prefs.iops_prefs import get_iops_prefs
from ...utils.split_areas_dict import split_areas_dict, split_areas_position_list

# Save Addon Preferences
def save_iops_preferences():
    iops_prefs = get_iops_prefs()
    path = bpy.utils.script_path_user()
    folder = os.path.join(path, "presets", "IOPS")
    iops_prefs_file = os.path.join(path, "presets", "IOPS", "iops_prefs_user.json")

    if not os.path.exists(folder):
        os.makedirs(folder)

    with open(iops_prefs_file, "w") as f:
        json.dump(iops_prefs, f, indent=4)


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
    try:
        iops_prefs_file = os.path.join(path, "presets", "IOPS", "iops_prefs_user.json")
        with open(iops_prefs_file, "r") as f:
            iops_prefs = json.load(f)
            for key, value in iops_prefs.items():
                match key:
                    case "IOPS_DEBUG":
                        prefs.IOPS_DEBUG = value["IOPS_DEBUG"]
                    case "ALIGN_TO_EDGE":
                        prefs.align_edge_color = value["align_edge_color"]
                    case "EXECUTOR":
                        prefs.executor_scripts_folder = value["executor_scripts_folder"]
                        prefs.executor_column_count = value["executor_column_count"]
                        # Handle old typo in JSON key
                        try:
                            prefs.executor_name_length = value["executor_name_length"]
                        except KeyError:
                            # Fallback to old typo key
                            try:
                                prefs.executor_name_length = value["executor_name_lenght"]
                            except KeyError:
                                # Use default value if neither key exists
                                prefs.executor_name_length = 10  # Default value
                        prefs.executor_use_script_path_user = value["executor_use_script_path_user"]
                        prefs.executor_scripts_subfolder = value["executor_scripts_subfolder"]
                    case "SPLIT_AREA_PIES":
                        for pie in value:
                            pie_num = pie[-1]
                            pos, ui = get_split_pos_ui(
                                value[pie][f"split_area_pie_{pie_num}_pos"],
                                value[pie][f"split_area_pie_{pie_num}_ui"],
                            )
                            prefs[f"split_area_pie_{pie_num}_factor"] = value[pie][
                                f"split_area_pie_{pie_num}_factor"
                            ]
                            prefs[f"split_area_pie_{pie_num}_pos"] = pos
                            prefs[f"split_area_pie_{pie_num}_ui"] = ui
                    case "UI_TEXT":
                        prefs.text_color = value["text_color"]
                        prefs.text_color_key = value["text_color_key"]
                        prefs.text_pos_x = value["text_pos_x"]
                        prefs.text_pos_y = value["text_pos_y"]
                        prefs.text_shadow_color = value["text_shadow_color"]
                        prefs.text_shadow_pos_x = value["text_shadow_pos_x"]
                        prefs.text_shadow_pos_y = value["text_shadow_pos_y"]
                        prefs.text_shadow_toggle = value["text_shadow_toggle"]
                        prefs.text_size = value["text_size"]
                    case "CURSOR_BISECT":
                        prefs.cursor_bisect_plane_color = value["cursor_bisect_plane_color"]
                        prefs.cursor_bisect_plane_outline_color = value["cursor_bisect_plane_outline_color"]
                        prefs.cursor_bisect_plane_outline_thickness = value["cursor_bisect_plane_outline_thickness"]
                        prefs.cursor_bisect_edge_color = value["cursor_bisect_edge_color"]
                        prefs.cursor_bisect_edge_locked_color = value["cursor_bisect_edge_locked_color"]
                        prefs.cursor_bisect_edge_thickness = value["cursor_bisect_edge_thickness"]
                        prefs.cursor_bisect_edge_locked_thickness = value["cursor_bisect_edge_locked_thickness"]
                        prefs.cursor_bisect_snap_color = value["cursor_bisect_snap_color"]
                        prefs.cursor_bisect_snap_hold_color = value["cursor_bisect_snap_hold_color"]
                        prefs.cursor_bisect_snap_closest_color = value["cursor_bisect_snap_closest_color"]
                        prefs.cursor_bisect_snap_closest_hold_color = value["cursor_bisect_snap_closest_hold_color"]
                        prefs.cursor_bisect_snap_size = value["cursor_bisect_snap_size"]
                        prefs.cursor_bisect_snap_closest_size = value["cursor_bisect_snap_closest_size"]
                        prefs.cursor_bisect_edge_subdivisions = value["cursor_bisect_edge_subdivisions"]
                        prefs.cursor_bisect_cut_preview_color = value["cursor_bisect_cut_preview_color"]
                        prefs.cursor_bisect_cut_preview_thickness = value["cursor_bisect_cut_preview_thickness"]
                        prefs.cursor_bisect_face_depth = value["cursor_bisect_face_depth"]
                        prefs.cursor_bisect_max_faces = value["cursor_bisect_max_faces"]
                        prefs.cursor_bisect_merge_distance = value["cursor_bisect_merge_distance"]
                        prefs.cursor_bisect_rotation_step = value["cursor_bisect_rotation_step"]
                        prefs.cursor_bisect_distance_text_color = value["cursor_bisect_distance_text_color"]
                        prefs.cursor_bisect_distance_text_size = value["cursor_bisect_distance_text_size"]
                        prefs.cursor_bisect_distance_offset_x = value["cursor_bisect_distance_offset_x"]
                        prefs.cursor_bisect_distance_offset_y = value["cursor_bisect_distance_offset_y"]
                    case "UI_TEXT_STAT":
                        prefs.iops_stat = value["iops_stat"]
                        prefs.text_color_stat = value["text_color_stat"]
                        prefs.text_color_key_stat = value["text_color_key_stat"]
                        prefs.text_color_error_stat = value["text_color_error_stat"]
                        prefs.text_pos_x_stat = value["text_pos_x_stat"]
                        prefs.text_pos_y_stat = value["text_pos_y_stat"]
                        prefs.text_shadow_color_stat = value["text_shadow_color_stat"]
                        prefs.text_shadow_pos_x_stat = value["text_shadow_pos_x_stat"]
                        prefs.text_shadow_pos_y_stat = value["text_shadow_pos_y_stat"]
                        prefs.text_shadow_toggle_stat = value["text_shadow_toggle_stat"]
                        prefs.text_size_stat = value["text_size_stat"]
                        prefs.text_column_offset_stat = value["text_column_offset_stat"]
                        prefs.text_column_width_stat = value["text_column_width_stat"]
                    case "VISUAL_ORIGIN":
                        prefs.vo_cage_ap_color = value["vo_cage_ap_color"]
                        prefs.vo_cage_ap_size = value["vo_cage_ap_size"]
                        prefs.vo_cage_color = value["vo_cage_color"]
                        prefs.vo_cage_p_size = value["vo_cage_p_size"]
                        prefs.vo_cage_points_color = value["vo_cage_points_color"]
                        prefs.vo_cage_line_thickness = value["vo_cage_line_thickness"]
                    case "TEXTURE_TO_MATERIAL":
                        prefs.texture_to_material_prefixes = value[
                            "texture_to_material_prefixes"
                        ]
                        prefs.texture_to_material_suffixes = value[
                            "texture_to_material_suffixes"
                        ]
                    case "SNAP_COMBOS":
                        for i in range(1, 9):
                            prefs[f"snap_combo_{i}"] = value[f"snap_combo_{i}"]
                    case "DRAG_SNAP":
                        prefs.drag_snap_line_thickness = value["drag_snap_line_thickness"]
                    case _:
                        print(
                            "IOPS Prefs: No entry for " + key,
                        )

    except FileNotFoundError:
        save_iops_preferences()
        print("IOPS Preferences file was not found. A new one was created at:", iops_prefs_file)
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
