import bpy
import os
import json
from .addon_preferences import IOPS_AddonPreferences


def _get_theme_section(prefs):
    """Full snapshot of the Theme tab for the prefs JSON: the persisted
    preset NAME (theme_preset is a dynamic enum Blender does not save
    reliably) plus EVERY writable IOPS_Theme value (colors, font sizes,
    HUD placement, animations, stats...) so manual tweaks survive
    reload/restart without depending on userpref.blend."""
    theme = getattr(prefs, "iops_theme", None)
    if theme is None:
        return {"theme_preset_name": "", "values": {}}
    # Lazy import — io_theme has no addon-internal imports, but keep the
    # dependency one-directional at module-init time.
    from ..operators.preferences.io_theme import serialize_theme
    return {
        "theme_preset_name": getattr(theme, "theme_preset_name", "") or "",
        "values": serialize_theme(theme),
    }


def _json_safe(value):
    """Enum-flag sets and bpy arrays -> JSON-friendly lists."""
    if isinstance(value, set):
        return sorted(value)
    if isinstance(value, (list, tuple)) or type(value).__name__ == "bpy_prop_array":
        return list(value)
    return value


def _slot_settings_explicit(item):
    """Only the defaults the user actually set on a grid slot (property
    is_property_set), so untouched Blender/smart defaults are not frozen
    into the JSON and keep following the descriptor definitions."""
    from ..operators.modifiers import iops_mod_defaults as defaults
    group = defaults.get_group(item, item.mod_type)
    if group is None:
        return {}
    out = {}
    for key in type(group).__annotations__:
        if group.is_property_set(key):
            out[key] = _json_safe(getattr(group, key))
    return out


def _get_modifiers_panel_section(prefs):
    """iOps Modifiers panel state: grid geometry, the user-built slot list
    (type + label + explicitly set defaults) and the sort-order rules.
    Blender persists all of this in userpref.blend too; mirroring it here
    lets the JSON carry the whole panel setup between machines."""
    grid = []
    for item in getattr(prefs, "modifiers_grid_items", ()):
        grid.append({
            "mod_type": item.mod_type,
            "label": item.label,
            "settings": _slot_settings_explicit(item),
        })

    def _rules(band):
        return [{"mod_type": it.mod_type, "names": it.names}
                for it in getattr(prefs, band, ())]

    return {
        "modifiers_grid_columns": getattr(prefs, "modifiers_grid_columns", 6),
        "modifiers_show_stack": getattr(prefs, "modifiers_show_stack", True),
        "grid": grid,
        "sort_head": _rules("mod_sort_head"),
        "sort_tail": _rules("mod_sort_tail"),
        "mod_sort_seeded": getattr(prefs, "mod_sort_seeded", False),
    }


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
        "GENERAL": {
            "category": safe("category", "iOps"),
        },
        "EXECUTOR": {
            "executor_column_count": safe("executor_column_count", 20),
            "executor_scripts_folder": safe("executor_scripts_folder", bpy.utils.script_path_user()),
            "executor_name_length": safe("executor_name_length", 100),
            "executor_use_script_path_user": safe("executor_use_script_path_user", True),
            "executor_scripts_subfolder": safe("executor_scripts_subfolder", "iops_exec"),
        },
        "WIDGETS_FOLDER": {
            "widgets_use_script_path_user": safe("widgets_use_script_path_user", True),
            "widgets_subfolder": safe("widgets_subfolder", "presets/IOPS/widgets"),
            "widgets_folder": safe("widgets_folder", bpy.utils.script_path_user()),
        },
        "LIBRARY": {
            "library_master_file": safe("library_master_file", ""),
            "library_preview_size": safe("library_preview_size", 5),
            "library_shader_group": safe("library_shader_group", ""),
        },
        "SPLIT_AREA_PIES": {
            f"PIE_{i}": {
                f"split_area_pie_{i}_factor": safe(f"split_area_pie_{i}_factor", 0.5),
                f"split_area_pie_{i}_pos": safe(f"split_area_pie_{i}_pos", "BOTTOM"),
                f"split_area_pie_{i}_ui": safe(f"split_area_pie_{i}_ui", "VIEW_3D"),
                f"split_area_pie_{i}_alt_ui": safe(f"split_area_pie_{i}_alt_ui", "VIEW_3D")
            } for i in range(1, 10) if i != 5
        },
        "SHADING_PIES": {
            f"PIE_{i}": {
                f"shading_pie_{i}_enable": safe(f"shading_pie_{i}_enable", True),
                f"shading_pie_{i}_name": safe(f"shading_pie_{i}_name", ""),
                f"shading_pie_{i}_type": safe(f"shading_pie_{i}_type", "SOLID"),
                f"shading_pie_{i}_light": safe(f"shading_pie_{i}_light", "STUDIO"),
                f"shading_pie_{i}_color_type": safe(f"shading_pie_{i}_color_type", "MATERIAL"),
                f"shading_pie_{i}_single_color": safelist(f"shading_pie_{i}_single_color", (0.8, 0.8, 0.8)),
                f"shading_pie_{i}_render_pass": safe(f"shading_pie_{i}_render_pass", "COMBINED"),
                f"shading_pie_{i}_scene_world": safe(f"shading_pie_{i}_scene_world", False),
            } for i in range(1, 10) if i != 5
        },
        "EDIT_PIES": {
            ctx.upper(): {
                key: safe(key, default)
                for slot in ("nw", "ne", "sw", "se")
                for key, default in (
                    (f"edit_pie_{ctx}_{slot}_content", "DEFAULT"),
                    (f"edit_pie_{ctx}_{slot}_custom", ""),
                    (f"edit_pie_{ctx}_{slot}_label", ""),
                )
            } for ctx in ("object", "edit", "uv")
        },
        "UI_TEXT_STAT": {
            "iops_stat": safe("iops_stat", True),
            "show_filename_stat": safe("show_filename_stat", True),
            "iops_ss_header": safe("iops_ss_header", True),
            "show_filename_full_path": safe("show_filename_full_path", False),
            "show_dimensions_stat": safe("show_dimensions_stat", True),
            "show_instances_stat": safe("show_instances_stat", False),
            "show_modifiers_stat": safe("show_modifiers_stat", False),
            "show_material_stat": safe("show_material_stat", False),
            "show_material_users_stat": safe("show_material_users_stat", False),
            "show_material_max_rows": safe("show_material_max_rows", 8),
            "show_parent_stat": safe("show_parent_stat", False),
            "show_units_stat": safe("show_units_stat", False),
            "show_view_position_stat": safe("show_view_position_stat", False),
        },
        "TEXTURE_TO_MATERIAL": {
            "texture_to_material_prefixes": safe("texture_to_material_prefixes", "env_"),
            "texture_to_material_suffixes": safe("texture_to_material_suffixes", "_df,_dfa,_mk,_emk,_nm")
        },
        "SNAP_COMBOS": {
            f"snap_combo_{i}": snap_combo_dict[f"snap_combo_{i}"] for i in range(1, 9)
        },
        "MODIFIER_WINDOW": {
            "modifier_window_method": safe("modifier_window_method", "RENDER")
        },
        "MODIFIERS_PANEL": _get_modifiers_panel_section(prefs),
        "VISUAL_UV": {
            "visual_uv_normal_offset": safe("visual_uv_normal_offset", 0.002),
            **{
                f"island_palette_{i}": safelist(
                    f"island_palette_{i}", (0.5, 0.5, 0.5, 0.1))
                for i in range(8)
            },
        },
        "MIRROR_ROTATE": {
            "mirror_rotate_method": safe("mirror_rotate_method", "MIRROR"),
            "mirror_rotate_apply_mirror": safe("mirror_rotate_apply_mirror", True),
            "mirror_rotate_apply_rotate": safe("mirror_rotate_apply_rotate", False),
            "mirror_rotate_pivot": safe("mirror_rotate_pivot", "CURSOR"),
            "mirror_rotate_orientation": safe("mirror_rotate_orientation", "GLOBAL"),
            "mirror_rotate_axis": safe("mirror_rotate_axis", "X"),
            "mirror_rotate_clone": safe("mirror_rotate_clone", "DUPLICATE"),
        },
        "THEME": _get_theme_section(prefs),
        "CURSOR_BISECT": {
            "cursor_bisect_edge_subdivisions": safe("cursor_bisect_edge_subdivisions", 1),
            "cursor_bisect_face_depth": safe("cursor_bisect_face_depth", 5),
            "cursor_bisect_max_faces": safe("cursor_bisect_max_faces", 1000),
            "cursor_bisect_merge_distance": safe("cursor_bisect_merge_distance", 0.005),
            "cursor_bisect_rotation_step": safe("cursor_bisect_rotation_step", 45.0),
            "cursor_bisect_coplanar_angle": safe("cursor_bisect_coplanar_angle", 5.0),
            "cursor_bisect_snap_threshold": safe("cursor_bisect_snap_threshold", 30.0),
            "cursor_bisect_snap_use_modifiers": safe("cursor_bisect_snap_use_modifiers", True),
        },
        "NONPLANAR_OVERLAY": {
            "nonplanar_angle": safe("nonplanar_angle", 0.5),
        },
    }

    return iops_prefs