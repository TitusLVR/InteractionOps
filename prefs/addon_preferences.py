from ast import In
from pydoc import text
from re import I
import bpy
import rna_keymap_ui
import os
from mathutils import Vector
from bpy.props import (
    BoolProperty,
    EnumProperty,
    FloatProperty,
    IntProperty,
    StringProperty,
    FloatVectorProperty,
)
from ..ui.iops_tm_panel import IOPS_PT_VCol_Panel
from .theme import IOPS_Theme, draw_theme_tab
# from ..utils.functions import ShowMessageBox
from ..utils.split_areas_dict import (
    # split_areas_dict,
    split_areas_list,
    split_areas_position_list,
)

# Panels to update
panels = (IOPS_PT_VCol_Panel,)


def _section(parent, prefs, prop_name, title, *, icon="NONE"):
    """Draw a collapsible section header. Returns the body column to draw
    contents into, or `None` if the section is collapsed.

    `prop_name` is the BoolProperty on `prefs` storing the open/closed state.
    """
    box = parent.box()
    row = box.row(align=True)
    is_open = getattr(prefs, prop_name)
    row.prop(prefs, prop_name,
             text="",
             icon="TRIA_DOWN" if is_open else "TRIA_RIGHT",
             emboss=False)
    row.label(text=title, icon=icon)
    if not is_open:
        return None
    body = box.column(align=True)
    return body


def update_category(self, context):
    message = "Panel Update Failed"
    try:
        for panel in panels:
            if "bl_rna" in panel.__dict__:
                bpy.utils.unregister_class(panel)

        for panel in panels:
            panel.bl_category = context.preferences.addons[
                "InteractionOps"
            ].preferences.category
            bpy.utils.register_class(panel)

    except Exception as e:
        print("\n[{}]\n{}\n\nError:\n{}".format("InteractionOps", message, e))
        pass


def update_combo(self, context):
    bpy.ops.iops.set_snap_combo()


class IOPS_AddonPreferences(bpy.types.AddonPreferences):
    bl_idname = "InteractionOps"

    IOPS_DEBUG: BoolProperty(name="Query debug", description="ON/Off", default=False)

    category: StringProperty(
        name="Tab Name",
        description="Choose a name for the category of the panel",
        default="iOps",
        update=update_category,
    )

    # list items (identifier, name, description, icon, number,)
    # Area.type, Area.ui_type, Icon, PrefText
    tabs: bpy.props.EnumProperty(
        name="Preferences",
        items=[("PREFS", "Preferences", ""), ("KM", "Keymaps", ""), ("THEME", "Theme", "Unified UI theme")],
        default="PREFS",
    )

    iops_theme: bpy.props.PointerProperty(type=IOPS_Theme)

    # Statistics overlay toggles (the only stat-related prefs that aren't
    # cosmetic — colors / sizes / positions all live in IOPS_Theme).
    iops_stat: BoolProperty(
        name="Statistics ON/OFF",
        description="Shows UVmaps and Non Uniform Scale",
        default=True,
    )

    show_filename_stat: BoolProperty(
        name="Show Filename",
        description="Show/Hide filename in statistics",
        default=True,
    )

    # Persistent GPU widget panels (ui/widgets) — JSON blob with each
    # widget's visibility/position, read/written by ui/widgets/state.py.
    # Internal storage only, intentionally not drawn in the prefs UI.
    widgets_state: StringProperty(
        name="Widgets State",
        description="Internal: GPU widget visibility/positions (JSON)",
        default="{}",
        options={"HIDDEN"},
    )

    # --- Collapsible section toggles (UI only) ---
    show_section_general: BoolProperty(default=True)
    show_section_stats: BoolProperty(default=False)
    show_section_visual_uv: BoolProperty(default=False)
    show_section_executor: BoolProperty(default=False)
    show_section_textures: BoolProperty(default=False)
    show_section_bisect: BoolProperty(default=False)
    show_section_snap_combo: BoolProperty(default=False)
    show_section_modifier_window: BoolProperty(default=False)
    show_section_io: BoolProperty(default=False)
    show_section_debug: BoolProperty(default=False)
    show_section_pies: BoolProperty(default=False)

    # Legacy cage/snap/align color and size props removed.
    # Colors and sizes now live in IOPS_Theme (Role-based) — see prefs/theme.py.
    # 1 - BOTTOM - LEFT
    split_area_pie_1_ui: EnumProperty(
        name="",
        description="Area Types",
        items=split_areas_list,
        default="ShaderNodeTree",
    )
    split_area_pie_1_pos: EnumProperty(
        name="",
        description="Area screen position",
        items=split_areas_position_list,
        default="BOTTOM",
    )
    split_area_pie_1_factor: FloatProperty(
        name="",
        description="Split factor",
        default=0.2,
        min=0.05,
        max=1.0,
        step=0.01,
        precision=2,
    )
    # 2 - BOTTOM
    split_area_pie_2_ui: EnumProperty(
        name="", description="Area Types", items=split_areas_list, default="TIMELINE"
    )
    split_area_pie_2_pos: EnumProperty(
        name="",
        description="Area screen position",
        items=split_areas_position_list,
        default="BOTTOM",
    )
    split_area_pie_2_factor: FloatProperty(
        name="",
        description="Split factor",
        default=0.5,
        min=0.05,
        max=1.0,
        step=0.01,
        precision=2,
    )
    # 3 - BOTTOM - RIGHT
    split_area_pie_3_ui: EnumProperty(
        name="", description="Area Types", items=split_areas_list, default="PROPERTIES"
    )
    split_area_pie_3_pos: EnumProperty(
        name="",
        description="Area screen position",
        items=split_areas_position_list,
        default="RIGHT",
    )
    split_area_pie_3_factor: FloatProperty(
        name="",
        description="Split factor",
        default=0.5,
        min=0.05,
        max=1.0,
        step=0.01,
        precision=2,
    )
    # 4 - LEFT
    split_area_pie_4_ui: EnumProperty(
        name="", description="Area Types", items=split_areas_list, default="OUTLINER"
    )
    split_area_pie_4_pos: EnumProperty(
        name="",
        description="Area screen position",
        items=split_areas_position_list,
        default="LEFT",
    )
    split_area_pie_4_factor: FloatProperty(
        name="",
        description="Split factor",
        default=0.5,
        min=0.05,
        max=1.0,
        step=0.01,
        precision=2,
    )
    # 6 - RIGHT
    split_area_pie_6_ui: EnumProperty(
        name="",
        description="Area Types",
        items=split_areas_list,
        default="UV"
    )
    split_area_pie_6_pos: EnumProperty(
        name="",
        description="Area screen position",
        items=split_areas_position_list,
        default="RIGHT",
    )
    split_area_pie_6_factor: FloatProperty(
        name="",
        description="Split factor",
        default=0.5,
        min=0.05,
        max=1.0,
        step=0.01,
        precision=2,
    )
    # 7 - TOP - LEFT
    split_area_pie_7_ui: EnumProperty(
        name="",
        description="Area Types",
        items=split_areas_list,
        default='FILES',
    )
    split_area_pie_7_pos: EnumProperty(
        name="",
        description="Area screen position",
        items=split_areas_position_list,
        default="RIGHT",
    )
    split_area_pie_7_factor: FloatProperty(
        name="",
        description="Split factor",
        default=0.5,
        min=0.05,
        max=1.0,
        step=0.01,
        precision=2,
    )
    # 8 - TOP
    split_area_pie_8_ui: EnumProperty(
        name="",
        description="Area Types",
        items=split_areas_list,
        default="CONSOLE"
    )
    split_area_pie_8_pos: EnumProperty(
        name="",
        description="Area screen position",
        items=split_areas_position_list,
        default="TOP",
    )
    split_area_pie_8_factor: FloatProperty(
        name="",
        description="Split factor",
        default=0.5,
        min=0.05,
        max=1.0,
        step=0.01,
        precision=2,
    )
    # 9 - TOP - RIGHT
    split_area_pie_9_ui: EnumProperty(
        name="",
        description="Area Types",
        items=split_areas_list,
        default="TEXT_EDITOR"
    )
    split_area_pie_9_pos: EnumProperty(
        name="",
        description="Area screen position",
        items=split_areas_position_list,
        default="RIGHT",
    )
    split_area_pie_9_factor: FloatProperty(
        name="",
        description="Split factor",
        default=0.5,
        min=0.05,
        max=1.0,
        step=0.01,
        precision=2,
    )
    # Alt variants for UI types
    # 1 - BOTTOM - LEFT
    split_area_pie_1_alt_ui: EnumProperty(
        name="",
        description="Area Types (Alt)",
        items=split_areas_list,
        default="ShaderNodeTree",
    )
    # 2 - BOTTOM
    split_area_pie_2_alt_ui: EnumProperty(
        name="", description="Area Types (Alt)", items=split_areas_list, default="TIMELINE"
    )
    # 3 - BOTTOM - RIGHT
    split_area_pie_3_alt_ui: EnumProperty(
        name="", description="Area Types (Alt)", items=split_areas_list, default="PROPERTIES"
    )
    # 4 - LEFT
    split_area_pie_4_alt_ui: EnumProperty(
        name="", description="Area Types (Alt)", items=split_areas_list, default="OUTLINER"
    )
    # 6 - RIGHT
    split_area_pie_6_alt_ui: EnumProperty(
        name="",
        description="Area Types (Alt)",
        items=split_areas_list,
        default="UV"
    )
    # 7 - TOP - LEFT
    split_area_pie_7_alt_ui: EnumProperty(
        name="",
        description="Area Types (Alt)",
        items=split_areas_list,
        default='FILES',
    )
    # 8 - TOP
    split_area_pie_8_alt_ui: EnumProperty(
        name="",
        description="Area Types (Alt)",
        items=split_areas_list,
        default="CONSOLE"
    )
    # 9 - TOP - RIGHT
    split_area_pie_9_alt_ui: EnumProperty(
        name="",
        description="Area Types (Alt)",
        items=split_areas_list,
        default="TEXT_EDITOR"
    )

    executor_column_count: IntProperty(
        name="Scripts per column",
        description="Scripts per column ",
        default=20,
        min=5,
        max=1000,
    )
    executor_name_length: IntProperty(
        name="Name Length",
        description="Length of script names in executor panel",
        default=100,
        min=5,
        max=600,
    )
    executor_scripts_folder: StringProperty(
        name="Scripts Folder",
        subtype="DIR_PATH",
        default=bpy.utils.script_path_user(),
    )

    executor_scripts_subfolder: StringProperty(
        name="Scripts sub-folder",
        default="iops_exec",
    )

    executor_use_script_path_user: BoolProperty(
        name="Use user script path",
        description=r"User the scripts folder under %appdata%/blender/scripts",
        default=True
    )

    texture_to_material_prefixes: StringProperty(
        name="Prefixes",
        description="Type prefixes what you want to clean",
        default="env_",
    )
    texture_to_material_suffixes: StringProperty(
        name="Suffixes",
        description="Type suffixes what you want to clean",
        default="_df,_dfa,_mk,_emk,_nm",
    )

    snap_combo_list: EnumProperty(
        name="Snap Combo List",
        description="Snap Combo List",
        items=[
            ("1", "Snap Combo 1", "", "EVENT_A", 0),
            ("2", "Snap Combo 2", "", "EVENT_B", 1),
            ("3", "Snap Combo 3", "", "EVENT_C", 2),
            ("4", "Snap Combo 4", "", "EVENT_D", 3),
            ("5", "Snap Combo 5", "", "EVENT_E", 4),
            ("6", "Snap Combo 6", "", "EVENT_F", 5),
            ("7", "Snap Combo 7", "", "EVENT_G", 6),
            ("8", "Snap Combo 8", "", "EVENT_H", 7),
        ],
        default="1",
        update = update_combo
    )

    snap_combo_mod: EnumProperty(
        name="Save Modifier",
        description="Save snap combo preset with this modifier",
        items=[
            ("SHIFT", "Shift", "", 0),
             ("CTRL", "Ctrl", "", 1),
            ("ALT", "Alt", "", 2),
            ("CTRL_ALT", "Ctrl + Alt", "", 3),
            ("SHIFT_ALT", "Shift + Alt", "", 4),
            ("SHIFT_CTRL", "Shift + Ctrl", "", 5),
            ("SHIFT_CTRL_ALT", "Shift + Ctrl + Alt", "", 6)
        ],
        default="SHIFT"
    )

    # Visual UV Island palette (per-island identification, indexed by
    # island_id % 8). Lives here (not in IOPS_Theme) because it's a
    # Visual-UV-specific preference, not a global text/HUD theme value,
    # and is intentionally excluded from theme presets.
    island_palette_0: FloatVectorProperty(name="Island 1", subtype="COLOR", size=4,
        min=0.0, max=1.0, default=(0.40, 0.65, 1.00, 0.10))
    island_palette_1: FloatVectorProperty(name="Island 2", subtype="COLOR", size=4,
        min=0.0, max=1.0, default=(1.00, 0.50, 0.30, 0.10))
    island_palette_2: FloatVectorProperty(name="Island 3", subtype="COLOR", size=4,
        min=0.0, max=1.0, default=(0.35, 0.85, 0.45, 0.10))
    island_palette_3: FloatVectorProperty(name="Island 4", subtype="COLOR", size=4,
        min=0.0, max=1.0, default=(0.95, 0.80, 0.25, 0.10))
    island_palette_4: FloatVectorProperty(name="Island 5", subtype="COLOR", size=4,
        min=0.0, max=1.0, default=(0.70, 0.40, 0.90, 0.10))
    island_palette_5: FloatVectorProperty(name="Island 6", subtype="COLOR", size=4,
        min=0.0, max=1.0, default=(0.20, 0.80, 0.75, 0.10))
    island_palette_6: FloatVectorProperty(name="Island 7", subtype="COLOR", size=4,
        min=0.0, max=1.0, default=(0.90, 0.35, 0.60, 0.10))
    island_palette_7: FloatVectorProperty(name="Island 8", subtype="COLOR", size=4,
        min=0.0, max=1.0, default=(0.60, 0.80, 0.20, 0.10))

    # Visual UV On-Mesh Properties
    visual_uv_normal_offset: FloatProperty(
        name="Normal offset",
        description="How far to offset the overlay from the mesh surface",
        default=0.002,
        min=0.0001,
        max=0.1,
        precision=4,
    )

    # Cursor Bisect Drawing Properties — colors and sizes moved to IOPS_Theme.
    # Only operational params (face depth, subdivisions, snap threshold,
    # merge distance, rotation step, etc.) remain on AddonPreferences.

    # Face connectivity settings
    cursor_bisect_face_depth: bpy.props.IntProperty(
        name="Face Depth",
        description="Number of face connections to traverse from raycast point for cut preview (higher = more complete but slower)",
        min=1, max=20,
        default=5
    )

    # Fallback performance limit (only used when no raycast hit)
    cursor_bisect_max_faces: bpy.props.IntProperty(
        name="Max Faces Fallback",
        description="Maximum faces to process when no raycast target available (fallback only)",
        min=100, max=10000,
        default=1000
    )

    # Edge subdivision setting for snapping
    cursor_bisect_edge_subdivisions: bpy.props.IntProperty(
        name="Edge Subdivisions",
        description="Default number of subdivision points along edges for snapping (0 = vertices and center only)",
        default=1,
        min=0,
        max=100,
    )

    # Merge doubles setting for bisect operation
    cursor_bisect_merge_distance: bpy.props.FloatProperty(
        name="Merge Distance",
        description="Distance threshold for merging duplicate vertices after bisect operation",
        default=0.005,
        min=0.0,
        max=1.0,
        precision=4,
        step=0.001
    )
    # Rotation settings for bisect operation
    cursor_bisect_rotation_step: bpy.props.FloatProperty(
        name="Rotation Step",
        description="Angle step in degrees for Alt+Wheel rotation around Z-axis",
        default=45.0,
        min=1.0,
        max=180.0,
        step=500,  # 5 degrees
        precision=1
    )
    cursor_bisect_coplanar_angle: bpy.props.FloatProperty(
        name="Coplanar Angle",
        description="Angle threshold in degrees to consider faces coplanar for bisect operation",
        default=5.0,
        min=0.0,
        max=180.0,
        step=100,  # 1 degree
        precision=1
    )
    cursor_bisect_snap_threshold: bpy.props.FloatProperty(
    name="Snap Threshold (pixels)",
    description="Screen-space distance threshold for snapping in pixels",
    default=30.0,
    min=5.0,
    max=100.0,
    step=5
    )
    cursor_bisect_snap_use_modifiers: bpy.props.BoolProperty(
    name="Snap to Modified Mesh",
    description="Calculate snap points on mesh with modifiers applied (slower but more accurate)",
    default=True
    )
    
    # Window creation method
    modifier_window_method: EnumProperty(
        name="Window Creation Method",
        description="Method to use for creating modifier window",
        items=[
            ("RENDER", "Render Window", "Use render view method (allows size control)"),
            ("NEW_WINDOW", "New Window", "Use bpy.ops.wm.window_new() (standard method)")
        ],
        default="RENDER"
    )
    
    # (Distance text is now rendered through the HUD header — no separate
    # position offsets needed.)


    def draw(self, context):
        layout = self.layout
        tabs_row = layout.row(align=True)
        tabs_row.prop_enum(self, "tabs", "PREFS")
        tabs_row.operator("iops.save_addon_preferences",
                          text="", icon="FILE_TICK")
        tabs_row.operator("iops.load_addon_preferences",
                          text="", icon="FILE_FOLDER")
        tabs_row.separator()
        tabs_row.prop_enum(self, "tabs", "KM")
        tabs_row.separator()
        tabs_row.prop_enum(self, "tabs", "THEME")
        column_main = layout.column()
        if self.tabs == "KM":

            # Hotkeys
            col = column_main.column(align=False)
            box = col.box()
            col = box.column(align=True)
            col.label(text="Hotkeys:")
            row = col.row(align=True)
            row.operator("iops.save_user_hotkeys", text="Save User's Hotkeys")
            row.separator()
            row.separator()
            row.separator()
            row.operator("iops.load_user_hotkeys", text="Load User's Hotkeys")
            row.separator()
            row.separator()
            row.separator()
            row.operator("iops.load_default_hotkeys", text="Load Default Hotkeys", icon="ERROR")
            # row.separator()
            # row.separator()
            # row.separator()
            # row.operator("iops.fix_old_hotkeys", text="Fix Old Hotkeys", icon="ERROR")


            # Keymaps
            col = column_main.column(align=False)
            # Function keys
            box_functions = col.box()
            box_functions.label(text="Main:")
            col_functions = box_functions.column(align=True)
            km_functions_row = col_functions.row(align=True)
            km_functions_col = km_functions_row.column(align=True)
            # Cursor keys
            box_object = col.box()
            box_object.label(text="Cursor:")
            col_object = box_object.column(align=True)
            km_cursor_row = col_object.row(align=True)
            km_cursor_col = km_cursor_row.column(align=True)
            # ObjectMode keys
            box_object = col.box()
            box_object.label(text="Object Mode:")
            col_object = box_object.column(align=True)
            km_object_row = col_object.row(align=True)
            km_object_col = km_object_row.column(align=True)
            # Mesh/EditMode keys
            box_mesh = col.box()
            box_mesh.label(text="Mesh or EditMode:")
            col_mesh = box_mesh.column(align=True)
            km_mesh_row = col_mesh.row(align=True)
            km_mesh_col = km_mesh_row.column(align=True)
            # UV keys
            box_uv = col.box()
            box_uv.label(text="UV Editor:")
            col_uv = box_uv.column(align=True)
            km_uv_row = col_uv.row(align=True)
            km_uv_col = km_uv_row.column(align=True)
            # Panels keys
            box_panels = col.box()
            box_panels.label(text="Panels:")
            col_panels = box_panels.column(align=True)
            km_panels_row = col_panels.row(align=True)
            km_panels_col = km_panels_row.column(align=True)
            # Pie keys
            box_pie = col.box()
            box_pie.label(text="Pie Menus:")
            col_pie = box_pie.column(align=True)
            km_pie_row = col_pie.row(align=True)
            km_pie_col = km_pie_row.column(align=True)
            # Scripts keys
            box_scripts = col.box()
            box_scripts.label(text="Scripts:")
            col_scripts = box_scripts.column(align=True)
            km_scripts_row = col_scripts.row(align=True)
            km_scripts_col = km_scripts_row.column(align=True)
            # UI toggles (HUD / Help)
            box_ui = col.box()
            box_ui.label(text="UI Toggles:")
            col_ui = box_ui.column(align=True)
            km_ui_col = col_ui.row(align=True).column(align=True)
            # Other / uncategorized — catches operators whose idname matches no
            # explicit bucket above (e.g. iops.collections_*), including those
            # added via "Scan for New Operators".
            box_other = col.box()
            box_other.label(text="Other:")
            col_other = box_other.column(align=True)
            km_other_col = col_other.row(align=True).column(align=True)


            """
            kc - keyconfigs
            km - keymap
            kmi - keymap item

            """

            kc = context.window_manager.keyconfigs
            kc_user = context.window_manager.keyconfigs.user
            # IOPS keymaps
            keymaps = [
                kc_user.keymaps["Window"],
                kc_user.keymaps["Mesh"],
                kc_user.keymaps["Object Mode"],
                kc_user.keymaps["Screen Editing"],
                kc_user.keymaps["UV Editor"],
            ]


            for km in keymaps:
                for kmi in km.keymap_items:
                    if kmi.idname.startswith("iops.function_"):
                        try:
                            rna_keymap_ui.draw_kmi(
                                ["ADDON", "USER", "DEFAULT"], kc, km, kmi, km_functions_col, 0
                            )
                        except AttributeError:
                            km_functions_col.label(
                                text="No modal key maps attached to this operator ¯\_(ツ)_/¯",
                                icon="INFO",
                            )
                    elif kmi.idname.startswith("iops.cursor") or kmi.idname.startswith("iops.cursor_"):
                        try:
                            rna_keymap_ui.draw_kmi(
                                ["ADDON", "USER", "DEFAULT"], kc, km, kmi, km_cursor_col, 0
                            )
                        except AttributeError:
                            km_cursor_col.label(
                                text="No modal key maps attached to this operator ¯\_(ツ)_/¯",
                                icon="INFO",
                            )
                    elif kmi.idname.startswith("iops.mesh") or kmi.idname.startswith("iops.z_"):
                        try:
                            rna_keymap_ui.draw_kmi(
                                ["ADDON", "USER", "DEFAULT"], kc, km, kmi, km_mesh_col, 0
                            )
                        except AttributeError:
                            km_mesh_col.label(
                                text="No modal key maps attached to this operator ¯\_(ツ)_/¯",
                                icon="INFO",
                            )
                    elif kmi.idname.startswith("iops.uv"):
                        try:
                            rna_keymap_ui.draw_kmi(
                                ["ADDON", "USER", "DEFAULT"], kc, km, kmi, km_uv_col, 0
                            )
                        except AttributeError:
                            km_uv_col.label(
                                text="No modal key maps attached to this operator ¯\_(ツ)_/¯",
                                icon="INFO",
                            )
                    elif kmi.idname.startswith("iops.object"):
                        try:
                            rna_keymap_ui.draw_kmi(
                                ["ADDON", "USER", "DEFAULT"], kc, km, kmi, km_object_col, 0
                            )
                        except AttributeError:
                            km_object_col.label(
                                text="No modal key maps attached to this operator ¯\_(ツ)_/¯",
                                icon="INFO",
                            )
                    elif kmi.idname.startswith("iops.call_panel"):
                        try:
                            rna_keymap_ui.draw_kmi(
                                ["ADDON", "USER", "DEFAULT"], kc, km, kmi, km_panels_col, 0
                            )
                        except AttributeError:
                            km_panels_col.label(
                                text="No modal key maps attached to this operator ¯\_(ツ)_/¯",
                                icon="INFO",
                            )
                    elif kmi.idname.startswith("iops.call_pie"):
                        try:
                            rna_keymap_ui.draw_kmi(
                                ["ADDON", "USER", "DEFAULT"], kc, km, kmi, km_pie_col, 0
                            )
                        except AttributeError:
                            km_pie_col.label(
                                text="No modal key maps attached to this operator ¯\_(ツ)_/¯",
                                icon="INFO",
                            )
                    elif kmi.idname.startswith("iops.scripts"):
                        try:
                            rna_keymap_ui.draw_kmi(
                                ["ADDON", "USER", "DEFAULT"], kc, km, kmi, km_scripts_col, 0
                            )
                        except AttributeError:
                            km_scripts_col.label(
                                text="No modal key maps attached to this operator ¯\_(ツ)_/¯",
                                icon="INFO",
                            )
                    elif kmi.idname in {"iops.ui_help_toggle",
                                        "iops.ui_hud_params_toggle"}:
                        try:
                            rna_keymap_ui.draw_kmi(
                                ["ADDON", "USER", "DEFAULT"], kc, km, kmi, km_ui_col, 0
                            )
                        except AttributeError:
                            km_ui_col.label(
                                text="No modal key maps attached to this operator ¯\_(ツ)_/¯",
                                icon="INFO",
                            )
                    elif kmi.idname.startswith("iops.window"):
                        try:
                            rna_keymap_ui.draw_kmi(
                                ["ADDON", "USER", "DEFAULT"], kc, km, kmi, km_scripts_col, 0
                            )
                        except AttributeError:
                            km_scripts_col.label(
                                text="No modal key maps attached to this operator ¯\_(ツ)_/¯",
                                icon="INFO",
                            )
                    elif kmi.idname.startswith("iops."):
                        try:
                            rna_keymap_ui.draw_kmi(
                                ["ADDON", "USER", "DEFAULT"], kc, km, kmi, km_other_col, 0
                            )
                        except AttributeError:
                            km_other_col.label(
                                text="No modal key maps attached to this operator ¯\_(ツ)_/¯",
                                icon="INFO",
                            )



        if self.tabs == "PREFS":
            # General
            body = _section(column_main, self, "show_section_general", "General", icon="PREFERENCES")
            if body is not None:
                body.prop(self, "category")

            # Stats overlay
            body = _section(column_main, self, "show_section_stats", "Statistics Overlay", icon="INFO")
            if body is not None:
                body.prop(self, "iops_stat", toggle=True)
                body.prop(self, "show_filename_stat", toggle=True)
                body.separator()
                body.label(text="Colors, sizes and text positioning live in the Theme tab.")

            # Visual UV
            body = _section(column_main, self, "show_section_visual_uv", "Visual UV (on-mesh)", icon="UV")
            if body is not None:
                body.label(text="Point size, edge width and fill opacity live in the Theme tab.", icon="INFO")
                body.prop(self, "visual_uv_normal_offset")
                body.separator()
                body.label(text="Island palette (per-island, indexed by island_id % 8):")
                row = body.row(align=True)
                for i in range(8):
                    row.prop(self, f"island_palette_{i}", text="")

            # Cursor Bisect (operational only — colors/sizes in Theme)
            body = _section(column_main, self, "show_section_bisect", "Cursor Bisect", icon="MOD_BEVEL")
            if body is not None:
                body.label(text="Colors and sizes live in the Theme tab.", icon="INFO")
                body.separator()
                body.label(text="Preview Scope:")
                row = body.row(align=True)
                row.prop(self, "cursor_bisect_face_depth")
                row.prop(self, "cursor_bisect_max_faces", text="Fallback Limit")
                body.separator()
                body.label(text="Edge Snapping:")
                row = body.row(align=True)
                row.prop(self, "cursor_bisect_edge_subdivisions")
                row.prop(self, "cursor_bisect_snap_threshold")
                row.prop(self, "cursor_bisect_snap_use_modifiers")
                body.separator()
                body.label(text="Operation:")
                row = body.row(align=True)
                row.prop(self, "cursor_bisect_merge_distance")
                row.prop(self, "cursor_bisect_rotation_step")
                row.prop(self, "cursor_bisect_coplanar_angle")

            # Snap Combos
            body = _section(column_main, self, "show_section_snap_combo", "Snap Combo", icon="SNAP_ON")
            if body is not None:
                body.prop(self, "snap_combo_mod")

            # Modifier Window
            body = _section(column_main, self, "show_section_modifier_window", "Modifier Window", icon="WINDOW")
            if body is not None:
                row = body.row(align=True)
                row.alignment = "LEFT"
                row.prop(self, "modifier_window_method", expand=True)

            # Split Pie
            body = _section(column_main, self, "show_section_pies", "Split Pie Layout", icon="MOD_NORMALEDIT")
            if body is not None:
                row = body.row(align=True)
                for n in (7, 8, 9):
                    sub = row.box().column(align=True)
                    sub.prop(self, f"split_area_pie_{n}_ui")
                    sub.prop(self, f"split_area_pie_{n}_alt_ui")
                    sub.prop(self, f"split_area_pie_{n}_pos")
                    sub.prop(self, f"split_area_pie_{n}_factor")
                row = body.row(align=True)
                sub = row.box().column(align=True)
                sub.prop(self, "split_area_pie_4_ui")
                sub.prop(self, "split_area_pie_4_alt_ui")
                sub.prop(self, "split_area_pie_4_pos")
                sub.prop(self, "split_area_pie_4_factor")
                row.box().column(align=True).label(text=" ")
                sub = row.box().column(align=True)
                sub.prop(self, "split_area_pie_6_ui")
                sub.prop(self, "split_area_pie_6_alt_ui")
                sub.prop(self, "split_area_pie_6_pos")
                sub.prop(self, "split_area_pie_6_factor")
                row = body.row(align=True)
                for n in (1, 2, 3):
                    sub = row.box().column(align=True)
                    sub.prop(self, f"split_area_pie_{n}_ui")
                    sub.prop(self, f"split_area_pie_{n}_alt_ui")
                    sub.prop(self, f"split_area_pie_{n}_pos")
                    sub.prop(self, f"split_area_pie_{n}_factor")

            # Executor
            body = _section(column_main, self, "show_section_executor", "Script Executor", icon="SCRIPT")
            if body is not None:
                body.prop(self, "executor_use_script_path_user")
                if self.executor_use_script_path_user:
                    body.label(text=bpy.utils.script_path_user())
                    body.prop(self, "executor_scripts_subfolder")
                    if len(self.executor_scripts_subfolder) > 0:
                        self.executor_scripts_folder = os.path.join(
                            bpy.utils.script_path_user(), self.executor_scripts_subfolder
                        )
                    else:
                        self.executor_scripts_folder = bpy.utils.script_path_user()
                else:
                    body.prop(self, "executor_scripts_folder")
                body.separator()
                body.prop(self, "executor_column_count")
                body.prop(self, "executor_name_length")

            # Textures
            body = _section(column_main, self, "show_section_textures", "Textures to Materials", icon="TEXTURE")
            if body is not None:
                body.prop(self, "texture_to_material_prefixes")
                body.prop(self, "texture_to_material_suffixes")

            # Debug
            body = _section(column_main, self, "show_section_debug", "Debug", icon="CONSOLE")
            if body is not None:
                body.prop(self, "IOPS_DEBUG")

        if self.tabs == "THEME":
            draw_theme_tab(layout, self.iops_theme)
