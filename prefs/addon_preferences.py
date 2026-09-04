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
from .widget_composer import IOPS_WidgetDefItem, draw_widgets_tab
from ..operators.modifiers import iops_mod_defaults
from ..operators.modifiers import iops_mod_presets
from ..operators.modifiers.iops_mod_list import (
    IOPS_ModGridItem,
    type_label,
)
from ..operators.modifiers.iops_mod_registry import (
    type_icon as mod_type_icon,
)
from ..operators.modifiers.iops_mod_sort import (
    IOPS_ModSortItem,
    draw_sort_order,
)
from ..ui.iops_pie_shading import (
    SHADING_PIE_SLOTS,
    shading_type_list,
    shading_light_list,
    shading_color_type_list,
    shading_render_pass_list,
)
from ..ui.iops_pie_edit import (
    EDIT_PIE_CONTEXTS,
    EDIT_PIE_SLOTS,
    edit_pie_content_list,
)
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
        items=[("PREFS", "Preferences", ""), ("KM", "Keymaps", ""), ("WIDGETS", "Widgets", "GPU widget composer"), ("THEME", "Theme", "Unified UI theme")],
        default="PREFS",
    )

    iops_theme: bpy.props.PointerProperty(type=IOPS_Theme)

    # Widgets tab — UI mirror of presets/IOPS/widgets/*.json (the files
    # are the source of truth; see prefs/widget_composer.py)
    widget_defs: bpy.props.CollectionProperty(type=IOPS_WidgetDefItem)
    widget_defs_index: bpy.props.IntProperty(default=0)

    # Widget library folder (executor-parity). Source folder for the
    # JSON widgets the popup lists and the loader registers.
    widgets_use_script_path_user: BoolProperty(
        name="Use user script path",
        description="Resolve the widgets folder under the user scripts path",
        default=True,
    )
    widgets_subfolder: StringProperty(
        name="Widgets sub-folder",
        default="presets/IOPS/widgets",
    )
    widgets_folder: StringProperty(
        name="Widgets Folder",
        subtype="DIR_PATH",
        default=bpy.utils.script_path_user(),
    )

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

    iops_ss_header: BoolProperty(
        name="Selection Sets in 3D View Header",
        description="Show the Selection Sets dropdown and buttons in the 3D View header",
        default=True,
    )

    show_filename_full_path: BoolProperty(
        name="Full Path",
        description="Show the full .blend file path instead of just the filename",
        default=False,
    )

    show_dimensions_stat: BoolProperty(
        name="Dimensions",
        description="Show active object dimensions in scene units",
        default=True,
    )

    show_instances_stat: BoolProperty(
        name="Instances",
        description="Warn when the active object's data is shared by other objects",
        default=False,
    )

    show_modifiers_stat: BoolProperty(
        name="Modifiers",
        description="Show modifier count and warn on viewport/render visibility mismatch",
        default=False,
    )

    show_material_stat: BoolProperty(
        name="Material",
        description="Show active material name, slot usage and empty-slot warnings",
        default=False,
    )

    show_material_users_stat: BoolProperty(
        name="Material Users",
        description="Append the active material's user count when it is shared",
        default=False,
    )

    show_parent_stat: BoolProperty(
        name="Parent / Constraints",
        description="Show parent name and constraint count of the active object",
        default=False,
    )

    show_units_stat: BoolProperty(
        name="Units Warning",
        description="Warn when the scene unit scale is not 1.0",
        default=False,
    )

    show_view_position_stat: BoolProperty(
        name="Position / Distance",
        description="Show active object world position and distance to the viewpoint",
        default=False,
    )

    # --- Collapsible section toggles (UI only) ---
    show_section_general: BoolProperty(default=True)
    show_section_stats: BoolProperty(default=False)
    show_section_visual_uv: BoolProperty(default=False)
    show_section_executor: BoolProperty(default=False)
    show_section_textures: BoolProperty(default=False)
    show_section_bisect: BoolProperty(default=False)
    show_section_nonplanar: BoolProperty(default=False)
    show_section_snap_combo: BoolProperty(default=False)
    show_section_modifier_window: BoolProperty(default=False)
    show_section_io: BoolProperty(default=False)
    show_section_debug: BoolProperty(default=False)
    show_section_pies: BoolProperty(default=False)
    show_section_shading_pie: BoolProperty(default=False)
    show_section_edit_pie: BoolProperty(default=False)
    show_section_edit_pie_object: BoolProperty(default=True)
    show_section_edit_pie_edit: BoolProperty(default=False)
    show_section_edit_pie_uv: BoolProperty(default=False)
    show_section_modifiers_panel: BoolProperty(default=False)
    show_section_mirror_rotate: BoolProperty(default=False)

    # --- Mirror Rotate operator: modal start-up defaults ---------------------
    # Values mirror the constants in operators/object_mirror_rotate.py.
    mirror_rotate_method: EnumProperty(
        name="Method",
        items=[("MIRROR", "Mirror", "True reflection across the plane"),
               ("ROTATE180", "Rotate 180°", "Rigid half-turn around the axis"),
               ("REFLECT", "Reflect", "Mirror reproduced by a proper rotation per "
                "object — mirrored placement and orientation, scale stays positive")],
        default="MIRROR",
    )
    mirror_rotate_apply_mirror: BoolProperty(
        name="Apply transforms (Mirror)",
        description="Default Apply-transforms state while the Mirror method "
                    "is active: bake rotation/scale into the mesh and flip "
                    "normals on the reflection",
        default=True,
    )
    mirror_rotate_apply_rotate: BoolProperty(
        name="Apply transforms (Rotate 180°)",
        description="Default Apply-transforms state while the Rotate 180° or "
                    "Reflect method is active (the turns are rigid, so baking "
                    "is normally unnecessary)",
        default=False,
    )
    mirror_rotate_pivot: EnumProperty(
        name="Pivot",
        items=[("CURSOR", "Cursor", ""),
               ("ACTIVE", "Active", ""),
               ("PICK", "Picked object", "Start in pick mode — click an object/empty")],
        default="CURSOR",
    )
    mirror_rotate_orientation: EnumProperty(
        name="Orientation",
        items=[("GLOBAL", "Global", ""),
               ("PIVOT", "Pivot frame", "Cursor / active / picked object axes")],
        default="GLOBAL",
    )
    mirror_rotate_axis: EnumProperty(
        name="Axis",
        items=[("X", "X", ""), ("Y", "Y", ""), ("Z", "Z", "")],
        default="X",
    )
    mirror_rotate_clone: EnumProperty(
        name="Clone type",
        items=[("DUPLICATE", "Duplicate", ""),
               ("INSTANCE", "Instance", ""),
               ("IN_PLACE", "In place", "Transform the sources themselves")],
        default="DUPLICATE",
    )

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

    # Non-Planar Faces Overlay (iops.mesh_nonplanar_overlay)
    nonplanar_angle: bpy.props.FloatProperty(
        name="Non-Planar Angle",
        description="Faces whose corners deviate from the face plane by more "
                    "than this angle (degrees) are highlighted by the "
                    "Non-Planar Faces Overlay",
        default=0.5,
        min=0.001,
        max=90.0,
        step=10,  # 0.1 degree
        precision=2,
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

    # iOps Modifiers panel (grid)
    modifiers_grid_columns: IntProperty(
        name="Grid Columns",
        description="Number of icon columns in the iOps Modifiers "
                    "panel grid",
        default=6, min=1, max=12,
    )
    modifiers_grid_items: bpy.props.CollectionProperty(type=IOPS_ModGridItem)
    modifiers_grid_index: IntProperty(default=0)
    # Sort Modifier Stacks order: rules (type + optional names) pinned to
    # the top / bottom of a stack, in order (see iops_mod_sort.draw_sort_order)
    mod_sort_head: bpy.props.CollectionProperty(type=IOPS_ModSortItem)
    mod_sort_head_index: IntProperty(default=0)
    mod_sort_tail: bpy.props.CollectionProperty(type=IOPS_ModSortItem)
    mod_sort_tail_index: IntProperty(default=0)
    mod_sort_seeded: BoolProperty(default=False)
    modifiers_show_stack: BoolProperty(
        name="Show Stack List",
        description="Show the active object's modifier stack under the grid",
        default=True,
    )

    # (Distance text is now rendered through the HUD header — no separate
    # position offsets needed.)

    # IOPS Library (ported asset-library workflow)
    library_master_file: StringProperty(
        name="Master Library File",
        description="Single Blender file that stores all published library assets",
        subtype="FILE_PATH",
        default="",
    )
    library_preview_size: IntProperty(
        name="Preview Size",
        description="Size of square asset previews in the library popup",
        default=5,
        min=3,
        max=32,
    )
    library_shader_group: StringProperty(
        name="Shader Group",
        description="Local shader node group to publish into the master library",
        default="",
    )
    show_section_library: BoolProperty(default=False)

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
        tabs_row.prop_enum(self, "tabs", "WIDGETS")
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
            # Library keys
            box_library = col.box()
            box_library.label(text="Library:")
            col_library = box_library.column(align=True)
            km_library_col = col_library.row(align=True).column(align=True)
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
                kc_user.keymaps["3D View"],
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
                                text="No modal key maps attached to this operator ¯\\_(ツ)_/¯",
                                icon="INFO",
                            )
                    elif kmi.idname.startswith("iops.cursor") or kmi.idname.startswith("iops.cursor_"):
                        try:
                            rna_keymap_ui.draw_kmi(
                                ["ADDON", "USER", "DEFAULT"], kc, km, kmi, km_cursor_col, 0
                            )
                        except AttributeError:
                            km_cursor_col.label(
                                text="No modal key maps attached to this operator ¯\\_(ツ)_/¯",
                                icon="INFO",
                            )
                    elif kmi.idname.startswith("iops.mesh") or kmi.idname.startswith("iops.z_"):
                        try:
                            rna_keymap_ui.draw_kmi(
                                ["ADDON", "USER", "DEFAULT"], kc, km, kmi, km_mesh_col, 0
                            )
                        except AttributeError:
                            km_mesh_col.label(
                                text="No modal key maps attached to this operator ¯\\_(ツ)_/¯",
                                icon="INFO",
                            )
                    elif kmi.idname.startswith("iops.uv"):
                        try:
                            rna_keymap_ui.draw_kmi(
                                ["ADDON", "USER", "DEFAULT"], kc, km, kmi, km_uv_col, 0
                            )
                        except AttributeError:
                            km_uv_col.label(
                                text="No modal key maps attached to this operator ¯\\_(ツ)_/¯",
                                icon="INFO",
                            )
                    elif kmi.idname.startswith("iops.object"):
                        try:
                            rna_keymap_ui.draw_kmi(
                                ["ADDON", "USER", "DEFAULT"], kc, km, kmi, km_object_col, 0
                            )
                        except AttributeError:
                            km_object_col.label(
                                text="No modal key maps attached to this operator ¯\\_(ツ)_/¯",
                                icon="INFO",
                            )
                    elif kmi.idname.startswith("iops.call_panel"):
                        try:
                            rna_keymap_ui.draw_kmi(
                                ["ADDON", "USER", "DEFAULT"], kc, km, kmi, km_panels_col, 0
                            )
                        except AttributeError:
                            km_panels_col.label(
                                text="No modal key maps attached to this operator ¯\\_(ツ)_/¯",
                                icon="INFO",
                            )
                    elif kmi.idname.startswith("iops.call_pie"):
                        try:
                            rna_keymap_ui.draw_kmi(
                                ["ADDON", "USER", "DEFAULT"], kc, km, kmi, km_pie_col, 0
                            )
                        except AttributeError:
                            km_pie_col.label(
                                text="No modal key maps attached to this operator ¯\\_(ツ)_/¯",
                                icon="INFO",
                            )
                    elif kmi.idname.startswith("iops.scripts"):
                        try:
                            rna_keymap_ui.draw_kmi(
                                ["ADDON", "USER", "DEFAULT"], kc, km, kmi, km_scripts_col, 0
                            )
                        except AttributeError:
                            km_scripts_col.label(
                                text="No modal key maps attached to this operator ¯\\_(ツ)_/¯",
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
                                text="No modal key maps attached to this operator ¯\\_(ツ)_/¯",
                                icon="INFO",
                            )
                    elif kmi.idname.startswith("iops.window"):
                        try:
                            rna_keymap_ui.draw_kmi(
                                ["ADDON", "USER", "DEFAULT"], kc, km, kmi, km_scripts_col, 0
                            )
                        except AttributeError:
                            km_scripts_col.label(
                                text="No modal key maps attached to this operator ¯\\_(ツ)_/¯",
                                icon="INFO",
                            )
                    elif kmi.idname in {"iops.widget_toggle", "iops.widget_interact"}:
                        # Per-widget toggle entries — drawn as key fields
                        # in the Widgets tab list, not here. Also swallows
                        # the programmatic, owner-managed widget_interact
                        # LEFTMOUSE binding (ui/widgets/events.py), which is
                        # NEVER_SAVE and must not surface as an editable
                        # "Other" keymap entry.
                        pass
                    elif kmi.idname.startswith("iops.library"):
                        try:
                            rna_keymap_ui.draw_kmi(
                                ["ADDON", "USER", "DEFAULT"], kc, km, kmi, km_library_col, 0
                            )
                        except AttributeError:
                            pass
                    elif kmi.idname.startswith("iops."):
                        try:
                            rna_keymap_ui.draw_kmi(
                                ["ADDON", "USER", "DEFAULT"], kc, km, kmi, km_other_col, 0
                            )
                        except AttributeError:
                            km_other_col.label(
                                text="No modal key maps attached to this operator ¯\\_(ツ)_/¯",
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
                body.prop(self, "iops_ss_header", toggle=True)
                row = body.row(align=True)
                row.prop(self, "show_filename_stat", toggle=True)
                sub = row.row(align=True)
                sub.enabled = self.show_filename_stat
                sub.prop(self, "show_filename_full_path", toggle=True)
                grid = body.grid_flow(columns=2, align=True)
                grid.prop(self, "show_dimensions_stat", toggle=True)
                grid.prop(self, "show_view_position_stat", toggle=True)
                grid.prop(self, "show_material_stat", toggle=True)
                grid.prop(self, "show_material_users_stat", toggle=True)
                grid.prop(self, "show_modifiers_stat", toggle=True)
                grid.prop(self, "show_instances_stat", toggle=True)
                grid.prop(self, "show_parent_stat", toggle=True)
                grid.prop(self, "show_units_stat", toggle=True)
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

            # Non-Planar Faces Overlay
            body = _section(column_main, self, "show_section_nonplanar",
                            "Non-Planar Overlay", icon="MOD_TRIANGULATE")
            if body is not None:
                body.prop(self, "nonplanar_angle")

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

            # iOps Modifiers panel
            body = _section(column_main, self, "show_section_modifiers_panel",
                            "Modifiers Panel", icon="MODIFIER")
            if body is not None:
                row = body.row(align=True)
                row.prop(self, "modifiers_grid_columns")
                row.prop(self, "modifiers_show_stack", toggle=True)
                body.separator()
                body.label(text="Grid preview (click a button to select):")
                row = body.row()
                grid = row.grid_flow(row_major=True,
                                     columns=self.modifiers_grid_columns,
                                     even_columns=True, align=True)
                for i, it in enumerate(self.modifiers_grid_items):
                    op = grid.operator(
                        "iops.mod_grid_list_action", text="",
                        icon=mod_type_icon(it.mod_type),
                        depress=(i == self.modifiers_grid_index))
                    op.action = "SELECT"
                    op.index = i
                # the panel always ends the grid with the Add Modifier
                # menu button — mirror it here, decorative only
                tail = grid.column(align=True)
                tail.enabled = False
                tail.operator("wm.call_menu", text="", icon="ADD")
                side = row.column(align=True)
                side.menu("IOPS_MT_ModGridAdd", text="", icon="ADD")
                side.operator("iops.mod_grid_list_action", text="",
                              icon="REMOVE").action = "REMOVE"
                side.separator()
                side.operator("iops.mod_grid_list_action", text="",
                              icon="TRIA_UP").action = "UP"
                side.operator("iops.mod_grid_list_action", text="",
                              icon="TRIA_DOWN").action = "DOWN"
                side.separator()
                side.operator("iops.mod_grid_list_action", text="",
                              icon="FILE_REFRESH").action = "RESET"

                items = self.modifiers_grid_items
                idx = self.modifiers_grid_index
                if 0 <= idx < len(items):
                    item = items[idx]
                    mod_type = item.mod_type
                    box = body.box()
                    group = iops_mod_presets.slot_group(item)
                    row = box.row()
                    row.label(text=f"Slot {idx + 1}: {type_label(mod_type)}",
                              icon=mod_type_icon(mod_type))
                    row.prop(item, "label", text="", placeholder="Label")
                    header = box.row()
                    header.label(text="Default settings:", icon="PRESET")
                    if group is not None:
                        header.operator("iops.mod_grid_list_action",
                                        text="Reset",
                                        icon="LOOP_BACK"
                                        ).action = "CLEAR_PRESET"
                        col = box.column()
                        col.use_property_split = True
                        col.use_property_decorate = False
                        iops_mod_defaults.draw_props(
                            col, group, type(group).__annotations__)
                    else:
                        box.label(text="No editable parameters "
                                       "(Blender defaults apply)",
                                  icon="INFO")

                body.separator()
                draw_sort_order(body, self)

            # Mirror Rotate defaults
            body = _section(column_main, self, "show_section_mirror_rotate",
                            "Mirror Rotate", icon="MOD_MIRROR")
            if body is not None:
                col = body.column()
                col.use_property_split = True
                col.use_property_decorate = False
                col.prop(self, "mirror_rotate_method")
                col.prop(self, "mirror_rotate_apply_mirror")
                col.prop(self, "mirror_rotate_apply_rotate")
                col.separator()
                col.prop(self, "mirror_rotate_pivot")
                col.prop(self, "mirror_rotate_orientation")
                col.prop(self, "mirror_rotate_axis")
                col.prop(self, "mirror_rotate_clone")

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

            # Shading Pie
            body = _section(column_main, self, "show_section_shading_pie", "Shading Pie Layout", icon="SHADING_RENDERED")
            if body is not None:
                def draw_shading_slot(parent, n):
                    sub = parent.box().column(align=True)
                    sub.prop(self, f"shading_pie_{n}_enable", text=f"Slot {n}", toggle=True)
                    if not getattr(self, f"shading_pie_{n}_enable"):
                        return
                    sub.prop(self, f"shading_pie_{n}_name", text="")
                    sub.prop(self, f"shading_pie_{n}_type", text="")
                    s_type = getattr(self, f"shading_pie_{n}_type")
                    if s_type == "SOLID":
                        sub.prop(self, f"shading_pie_{n}_light", text="")
                        sub.prop(self, f"shading_pie_{n}_color_type", text="")
                        if getattr(self, f"shading_pie_{n}_color_type") == "SINGLE":
                            sub.prop(self, f"shading_pie_{n}_single_color", text="")
                    else:
                        sub.prop(self, f"shading_pie_{n}_render_pass", text="")
                        sub.prop(self, f"shading_pie_{n}_scene_world")

                row = body.row(align=True)
                for n in (7, 8, 9):
                    draw_shading_slot(row, n)
                row = body.row(align=True)
                draw_shading_slot(row, 4)
                row.box().column(align=True).label(text=" ")
                draw_shading_slot(row, 6)
                row = body.row(align=True)
                for n in (1, 2, 3):
                    draw_shading_slot(row, n)

            # Edit Pie
            body = _section(column_main, self, "show_section_edit_pie", "Edit Pie Layout", icon="EDITMODE_HLT")
            if body is not None:
                body.label(text="Diagonal slots only; F1/F2/F3/ESC cardinals are fixed.", icon="INFO")

                def draw_edit_pie_slot(parent, ctx, slot):
                    sub = parent.box().column(align=True)
                    sub.label(text=slot.upper())
                    sub.prop(self, f"edit_pie_{ctx}_{slot}_content", text="")
                    content = getattr(self, f"edit_pie_{ctx}_{slot}_content")
                    if content == "CUSTOM":
                        crow = sub.row(align=True)
                        crow.prop(self, f"edit_pie_{ctx}_{slot}_custom", text="", placeholder="uv.pin(clear=False)")
                        op = crow.operator("iops.edit_pie_operator_search", text="", icon="VIEWZOOM")
                        op.ctx = ctx
                        op.slot = slot
                    if content not in ("DEFAULT", "EMPTY"):
                        sub.prop(self, f"edit_pie_{ctx}_{slot}_label", text="", placeholder="custom label")

                for ctx_key, ctx_title, ctx_toggle, ctx_icon in (
                    ("object", "Object Mode", "show_section_edit_pie_object", "OBJECT_DATA"),
                    ("edit", "Edit Mode", "show_section_edit_pie_edit", "EDITMODE_HLT"),
                    ("uv", "UV Edit", "show_section_edit_pie_uv", "UV"),
                ):
                    ctx_body = _section(body, self, ctx_toggle, ctx_title, icon=ctx_icon)
                    if ctx_body is None:
                        continue
                    row = ctx_body.row(align=True)
                    draw_edit_pie_slot(row, ctx_key, "nw")
                    draw_edit_pie_slot(row, ctx_key, "ne")
                    row = ctx_body.row(align=True)
                    draw_edit_pie_slot(row, ctx_key, "sw")
                    draw_edit_pie_slot(row, ctx_key, "se")

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

            # Library
            body = _section(column_main, self, "show_section_library", "Library", icon="ASSET_MANAGER")
            if body is not None:
                body.prop(self, "library_master_file")
                row = body.row(align=True)
                row.operator("iops.library_find_master", text="Find Master", icon="VIEWZOOM")
                row.operator("iops.library_refresh", text="Refresh Library", icon="FILE_REFRESH")
                operator = body.operator("iops.library_remove_asset", text="Clean Unlinked Assets", icon="TRASH")
                operator.mode = "CLEAN_UNLINKED"
                body.prop(self, "library_preview_size", slider=True)

            # Debug
            body = _section(column_main, self, "show_section_debug", "Debug", icon="CONSOLE")
            if body is not None:
                body.prop(self, "IOPS_DEBUG")

        if self.tabs == "WIDGETS":
            draw_widgets_tab(column_main, context, self)

        if self.tabs == "THEME":
            draw_theme_tab(layout, self.iops_theme)


# One PointerProperty per generated modifier-defaults group. Must run
# before the class registers (root __init__ registers the groups first).
iops_mod_defaults.inject_pointer_props(IOPS_AddonPreferences)


# Shading Pie slots — 8 identical prop sets, injected like the modifier
# defaults above. Per-slot defaults: (type, light, color_type, render_pass).
SHADING_PIE_SLOT_DEFAULTS = {
    1: ("SOLID", "STUDIO", "RANDOM", "COMBINED"),
    2: ("SOLID", "STUDIO", "MATERIAL", "COMBINED"),
    3: ("SOLID", "STUDIO", "SINGLE", "COMBINED"),
    4: ("SOLID", "MATCAP", "MATERIAL", "COMBINED"),
    6: ("MATERIAL", "STUDIO", "MATERIAL", "COMBINED"),
    7: ("SOLID", "FLAT", "TEXTURE", "COMBINED"),
    8: ("RENDERED", "STUDIO", "MATERIAL", "COMBINED"),
    9: ("SOLID", "FLAT", "VERTEX", "COMBINED"),
}

for _n in SHADING_PIE_SLOTS:
    _type, _light, _color, _pass = SHADING_PIE_SLOT_DEFAULTS[_n]
    IOPS_AddonPreferences.__annotations__.update({
        f"shading_pie_{_n}_enable": BoolProperty(
            name="Enable", description="Show this slot in the Shading pie", default=True),
        f"shading_pie_{_n}_name": StringProperty(
            name="", description="Custom slot label (empty = auto label)", default=""),
        f"shading_pie_{_n}_type": EnumProperty(
            name="", description="Viewport shading type",
            items=shading_type_list, default=_type),
        f"shading_pie_{_n}_light": EnumProperty(
            name="", description="Lighting (Solid mode)",
            items=shading_light_list, default=_light),
        f"shading_pie_{_n}_color_type": EnumProperty(
            name="", description="Color type (Solid mode)",
            items=shading_color_type_list, default=_color),
        f"shading_pie_{_n}_single_color": FloatVectorProperty(
            name="", description="Single color (Solid mode)",
            subtype="COLOR", size=3, min=0.0, max=1.0, default=(0.8, 0.8, 0.8)),
        f"shading_pie_{_n}_render_pass": EnumProperty(
            name="", description="Render pass (Material/Rendered mode)",
            items=shading_render_pass_list, default=_pass),
        f"shading_pie_{_n}_scene_world": BoolProperty(
            name="Scene World", description="Use scene world (Material/Rendered mode)",
            default=False),
    })


# Edit Pie diagonal slots — one config per context (Object / Edit / UV),
# injected the same way. Cardinals (F1/F2/F3/ESC) are not customizable.
for _ctx in EDIT_PIE_CONTEXTS:
    for _slot in EDIT_PIE_SLOTS:
        IOPS_AddonPreferences.__annotations__.update({
            f"edit_pie_{_ctx}_{_slot}_content": EnumProperty(
                name="", description="Slot content",
                items=edit_pie_content_list, default="DEFAULT"),
            f"edit_pie_{_ctx}_{_slot}_custom": StringProperty(
                name="", description="Operator idname, optionally with "
                "params in call syntax, e.g. uv.pin(clear=False)",
                default=""),
            f"edit_pie_{_ctx}_{_slot}_label": StringProperty(
                name="", description="Custom button label (empty = operator label)",
                default=""),
        })
