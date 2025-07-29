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
# from ..utils.functions import ShowMessageBox
from ..utils.split_areas_dict import (
    # split_areas_dict,
    split_areas_list,
    split_areas_position_list,
)

# Panels to update
panels = (IOPS_PT_VCol_Panel,)

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
        items=[("PREFS", "Preferences", ""), ("KM", "Keymaps", "")],
        default="PREFS",
    )
    # Operator text properties
    text_color: FloatVectorProperty(
        name="Color",
        subtype="COLOR_GAMMA",
        size=4,
        min=0,
        max=1,
        default=((*bpy.context.preferences.themes[0].text_editor.syntax_numbers, 0.75)),
    )

    text_color_key: FloatVectorProperty(
        name="Color key",
        subtype="COLOR_GAMMA",
        size=4,
        min=0,
        max=1,
        default=((*bpy.context.preferences.themes[0].text_editor.syntax_builtin, 0.75)),
    )

    text_size: IntProperty(
        name="Size",
        description="Modal operators text size",
        default=20,
        soft_min=1,
        soft_max=100,
    )

    text_pos_x: IntProperty(
        name="Position X",
        description="Modal operators Text pos X",
        default=60,
        soft_min=1,
        soft_max=10000,
    )

    text_pos_y: IntProperty(
        name="Position Y",
        description="Modal operators Text pos Y",
        default=60,
        soft_min=1,
        soft_max=10000,
    )

    text_shadow_color: FloatVectorProperty(
        name="Shadow",
        subtype="COLOR_GAMMA",
        size=4,
        min=0,
        max=1,
        default=(0.0, 0.0, 0.0, 1.0),
    )

    text_shadow_toggle: BoolProperty(name="ON/OFF", description="ON/Off", default=False)

    text_shadow_blur: EnumProperty(
        name="Blur",
        description="Could be 0,3,5",
        items=[
            ("0", "None", "", "", 0),
            ("3", "Mid", "", "", 3),
            ("5", "High", "", "", 5)
        ],
        default="0",
    )

    text_shadow_pos_x: IntProperty(
        name="Shadow pos X",
        description="Modal operators Text pos X",
        default=2,
        soft_min=-50,
        soft_max=50,
    )
    text_shadow_pos_y: IntProperty(
        name="Shadow pos Y",
        description="Modal operators Text pos Y",
        default=-2,
        soft_min=-50,
        soft_max=50,
    )

    # Statistics text properties
    iops_stat: BoolProperty(name="Statistics ON/OFF", description=" Shows UVmaps and Non Uniform Scale", default=True)

    text_color_stat: FloatVectorProperty(
        name="Color",
        subtype="COLOR_GAMMA",
        size=4,
        min=0,
        max=1,
        default=((*bpy.context.preferences.themes[0].text_editor.syntax_numbers, 0.75)),
    )

    text_color_key_stat: FloatVectorProperty(
        name="Color key",
        subtype="COLOR_GAMMA",
        size=4,
        min=0,
        max=1,
        default=((*bpy.context.preferences.themes[0].text_editor.syntax_builtin, 0.75)),
    )
    text_color_error_stat: FloatVectorProperty(
        name="Color error",
        subtype="COLOR_GAMMA",
        size=4,
        min=0,
        max=1,
        default=((*bpy.context.preferences.themes[0].view_3d.wire_edit, 0.7)),
    )

    text_size_stat: FloatProperty(
        name="Size",
        description="Modal operators text size",
        default=20,
        soft_min=1,
        soft_max=100,
    )

    text_pos_x_stat: IntProperty(
        name="Position X",
        description="Modal operators Text pos X",
        default=9,
        soft_min=1,
        soft_max=10000,
    )

    text_pos_y_stat: IntProperty(
        name="Position Y",
        description="Modal operators Text pos Y",
        default=220,
        soft_min=1,
        soft_max=10000,
    )

    text_shadow_color_stat: FloatVectorProperty(
        name="Shadow",
        subtype="COLOR_GAMMA",
        size=4,
        min=0,
        max=1,
        default=(0.0, 0.0, 0.0, 1.0),
    )

    text_shadow_toggle_stat: BoolProperty(name="ON/OFF", description="ON/Off", default=False)

    text_shadow_blur_stat: EnumProperty(
        name="Blur",
        description="Could be 0,3,5",
        items=[
            ("0", "None", "", "", 0),
            ("3", "Mid", "", "", 3),
            ("5", "High", "", "", 5)
        ],
        default="0",
    )

    text_shadow_pos_x_stat: IntProperty(
        name="Shadow pos X",
        description="Modal operators Text pos X",
        default=2,
        soft_min=-50,
        soft_max=50,
    )
    text_shadow_pos_y_stat: IntProperty(
        name="Shadow pos Y",
        description="Modal operators Text pos Y",
        default=-2,
        soft_min=-50,
        soft_max=50,
    )
    text_column_offset_stat: FloatProperty(
        name="Column Offset",
        description="Column Offset",
        default=30,
        min=0,
        max=10000,
    )
    text_column_width_stat: FloatProperty(
        name="Column Width",
        description="Column Width",
        default=4,
        min=0,
        max=10000,
    )

    # Cage Props
    vo_cage_color: FloatVectorProperty(
        name="Cage color",
        subtype="COLOR_GAMMA",
        size=4,
        min=0,
        max=1,
        default=Vector((*bpy.context.preferences.themes[0].view_3d.object_active, 0.25))
        - Vector((0.3, 0.3, 0.3, 0)),
    )

    vo_cage_points_color: FloatVectorProperty(
        name="Cage points color",
        subtype="COLOR_GAMMA",
        size=4,
        min=0,
        max=1,
        default=(*bpy.context.preferences.themes[0].view_3d.wire_edit, 0.7),
    )

    vo_cage_ap_color: FloatVectorProperty(
        name="Active point color",
        subtype="COLOR_GAMMA",
        size=4,
        min=0,
        max=1,
        default=Vector((*bpy.context.preferences.themes[0].view_3d.object_active, 0.5))
        - Vector((0.2, 0.2, 0.2, 0)),
    )

    vo_cage_p_size: IntProperty(
        name="Cage point size",
        description="Visual origin cage point size",
        default=2,
        soft_min=2,
        soft_max=20,
    )

    vo_cage_ap_size: IntProperty(
        name="Active point size",
        description="Visual origin active point size",
        default=4,
        soft_min=2,
        soft_max=20,
    )
    vo_cage_line_thickness: FloatProperty(
        name="Cage Line thickness",
        description="Thickness of the cage lines",
        default=0.25,
        min=0.0,
        max=1000.0,
    )
    drag_snap_line_thickness: FloatProperty(
        name="Drag Snap Line thickness",
        description="Thickness of the drag snap lines",
        default=0.25,
        min=0.0,
        max=1000.0,
    )

    align_edge_color: FloatVectorProperty(
        name="Edge color",
        subtype="COLOR_GAMMA",
        size=4,
        min=0,
        max=1,
        default=((*bpy.context.preferences.themes[0].view_3d.object_active, 0.5)),
    )
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
            ("ALT", "Alt", "", 2)
        ],
        default="SHIFT"
    )

    # Cursor Bisect Drawing Properties
    cursor_bisect_plane_color: FloatVectorProperty(
        name="Plane color",
        subtype="COLOR_GAMMA",
        size=4,
        min=0,
        max=1,
        default=(1.0, 0.0, 0.0, 0.15),
    )

    cursor_bisect_plane_outline_color: FloatVectorProperty(
        name="Plane outline color",
        subtype="COLOR_GAMMA",
        size=4,
        min=0,
        max=1,
        default=(1.0, 0.0, 0.0, 0.8),
    )

    cursor_bisect_plane_outline_thickness: FloatProperty(
        name="Plane outline thickness",
        description="Thickness of the bisect plane outline",
        default=2.0,
        min=0.1,
        max=10.0,
    )

    cursor_bisect_edge_color: FloatVectorProperty(
        name="Edge color (unlocked)",
        subtype="COLOR_GAMMA",
        size=4,
        min=0,
        max=1,
        default=(1.0, 1.0, 0.0, 1.0),
    )

    cursor_bisect_edge_locked_color: FloatVectorProperty(
        name="Edge color (locked)",
        subtype="COLOR_GAMMA",
        size=4,
        min=0,
        max=1,
        default=(1.0, 0.0, 0.0, 1.0),
    )

    cursor_bisect_edge_thickness: FloatProperty(
        name="Edge thickness (unlocked)",
        description="Thickness of the edge highlight when unlocked",
        default=4.0,
        min=0.1,
        max=20.0,
    )

    cursor_bisect_edge_locked_thickness: FloatProperty(
        name="Edge thickness (locked)",
        description="Thickness of the edge highlight when locked",
        default=8.0,
        min=0.1,
        max=20.0,
    )

    cursor_bisect_snap_color: FloatVectorProperty(
        name="Snap points color",
        subtype="COLOR_GAMMA",
        size=4,
        min=0,
        max=1,
        default=(1.0, 1.0, 0.0, 1.0),
    )

    cursor_bisect_snap_hold_color: FloatVectorProperty(
        name="Snap points color (hold)",
        subtype="COLOR_GAMMA",
        size=4,
        min=0,
        max=1,
        default=(1.0, 0.5, 0.0, 1.0),
    )

    cursor_bisect_snap_closest_color: FloatVectorProperty(
        name="Closest snap point color",
        subtype="COLOR_GAMMA",
        size=4,
        min=0,
        max=1,
        default=(0.0, 1.0, 0.0, 1.0),
    )

    cursor_bisect_snap_closest_hold_color: FloatVectorProperty(
        name="Closest snap point color (hold)",
        subtype="COLOR_GAMMA",
        size=4,
        min=0,
        max=1,
        default=(1.0, 0.2, 0.0, 1.0),
    )

    cursor_bisect_snap_size: FloatProperty(
        name="Snap point size",
        description="Size of snap points",
        default=6.0,
        min=1.0,
        max=20.0,
    )

    cursor_bisect_snap_closest_size: FloatProperty(
        name="Closest snap point size",
        description="Size of the closest snap point",
        default=9.0,
        min=1.0,
        max=20.0,
    )

    # Cut preview visual properties
    cursor_bisect_cut_preview_color: bpy.props.FloatVectorProperty(
        name="Cut Preview Color",
        description="Color for cut preview lines",
        subtype='COLOR_GAMMA',
        size=4,
        min=0.0, max=1.0,
        default=(1.0, 0.5, 0.0, 1.0)
    )

    cursor_bisect_cut_preview_thickness: bpy.props.FloatProperty(
        name="Cut Preview Thickness",
        description="Thickness of cut preview lines",
        min=1.0, max=10.0,
        default=3.0
    )

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
    # Distance text settings
    cursor_bisect_distance_text_color: FloatVectorProperty(
        name="Distance Text Color",
        subtype="COLOR_GAMMA",
        size=4,
        min=0,
        max=1,
        default=(1.0, 1.0, 0.0, 1.0), # Yellow color       
    )    
    cursor_bisect_distance_text_size:IntProperty(
        name="Distance Text Size",
        description="Size of the distance text displayed during bisect operation",
        default=12,
        min=5,
        max=100,
    )
    cursor_bisect_distance_offset_x:IntProperty(
        name="Distance Text Offset X",
        description="X offset for the distance text position",
        default=25,
        min=-1000,
        max=1000,
    )
    cursor_bisect_distance_offset_y:IntProperty(
        name="Distance Text Offset Y",
        description="Y offset for the distance text position",
        default=-25,
        min=-1000,
        max=1000,
    )


    def draw(self, context):
        layout = self.layout
        tabs_row = layout.row()
        tabs_row.prop(self, "tabs", expand=True)
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



        if self.tabs == "PREFS":
            col = column_main.column(align=False)
            box = col.box()
            col = box.column(align=True)
            col.label(text="Category:")
            col.prop(self, "category")
            # TextProps
            col = column_main.column(align=False)
            box = col.box()
            col = box.column(align=True)
            col.label(text="3D View Overlay Text Settings:")
            row = box.row(align=True)
            split = row.split(factor=0.5, align=False)
            col_text = split.column(align=True)
            col_shadow = split.column(align=True)
            row = col_text.row(align=True)
            row.prop(self, "text_color")
            row.prop(self, "text_color_key")
            row = col_text.row(align=True)
            row.prop(self, "text_size")
            row = col_text.row(align=True)
            row.prop(self, "text_pos_x")
            row.prop(self, "text_pos_y")
            # TextShadow column
            row = col_shadow.row(align=False)
            row.prop(self, "text_shadow_color")
            row.prop(self, "text_shadow_blur")
            row = col_shadow.row(align=True)
            row.prop(self, "text_shadow_toggle", toggle=True)
            row = col_shadow.row(align=True)
            row.prop(self, "text_shadow_pos_x")
            row.prop(self, "text_shadow_pos_y")
            col.separator()

            #Statistics TextProps
            col = column_main.column(align=False)
            box = col.box()
            col = box.column(align=True)
            col.label(text="3D View Overlay Statistics Text Settings:")
            col.prop(self, "iops_stat", toggle=True)
            row = box.row(align=True)
            split = row.split(factor=0.5, align=False)
            col_text = split.column(align=True)
            col_shadow = split.column(align=True)
            row = col_text.row(align=True)
            row.prop(self, "text_color_stat")
            row.prop(self, "text_color_key_stat")
            row.prop(self, "text_color_error_stat")
            row = col_text.row(align=True)
            row.prop(self, "text_size_stat")
            row.prop(self, "text_column_offset_stat")
            row.prop(self, "text_column_width_stat")
            row = col_text.row(align=True)
            row.prop(self, "text_pos_x_stat")
            row.prop(self, "text_pos_y_stat")
            # ShadowStatistics TextProps
            row = col_shadow.row(align=False)
            row.prop(self, "text_shadow_color_stat")
            row.prop(self, "text_shadow_blur_stat")
            row = col_shadow.row(align=True)
            row.prop(self, "text_shadow_toggle_stat", toggle=True)
            row = col_shadow.row(align=True)
            row.prop(self, "text_shadow_pos_x_stat")
            row.prop(self, "text_shadow_pos_y_stat")
            col.separator()

            # Align to edge
            col = column_main.column(align=False)
            box = col.box()
            col = box.column(align=True)
            col.label(text="Align to edge:")
            row = box.row(align=True)
            row.alignment = "LEFT"
            row.prop(self, "align_edge_color")
            col.separator()
            # Visual origin
            col = column_main.column(align=False)
            box = col.box()
            col = box.column(align=True)
            col.label(text="Visual origin:")
            row = box.row(align=True)
            split = row.split(factor=0.5, align=False)
            col_ap = split.column(align=True)
            col_p = split.column(align=True)
            col.separator()
            # Active point column
            col = col_p.column(align=True)
            col.label(text="Cage points:")
            col.prop(self, "vo_cage_p_size", text="Size")
            col.prop(self, "vo_cage_points_color", text="")

            # Cage points column
            col = col_ap.column(align=True)
            col.label(text="Active point:")
            col.prop(self, "vo_cage_ap_size", text="Size")
            col.prop(self, "vo_cage_ap_color", text="")

            # Cage color
            col = box.column(align=True)
            col.prop(self, "vo_cage_color")
            col.prop(self, "vo_cage_line_thickness")
            col.separator()

            # Drag snap line thickness
            col = column_main.column(align=False)
            box = col.box()
            col = box.column(align=True)
            col.label(text="Drag Snap:")
            row = col.row(align=True)
            row.prop(self, "drag_snap_line_thickness")

            # Split Pie preferences
            col = column_main.column(align=False)
            box = col.box()
            col = box.column(align=True)
            col.label(text="IOPS Split Pie Setup:")
            row = col.row(align=True)

            # TOP LEFT
            box_1 = row.box()
            col = box_1.column(align=True)
            col.prop(self, "split_area_pie_7_ui")
            col.prop(self, "split_area_pie_7_pos")
            col.prop(self, "split_area_pie_7_factor")
            row.separator()
            # TOP
            box_2 = row.box()
            col = box_2.column(align=True)
            col.prop(self, "split_area_pie_8_ui")
            col.prop(self, "split_area_pie_8_pos")
            col.prop(self, "split_area_pie_8_factor")
            row.separator()
            # TOP RIGHT
            box_3 = row.box()
            col = box_3.column(align=True)
            col.prop(self, "split_area_pie_9_ui")
            col.prop(self, "split_area_pie_9_pos")
            col.prop(self, "split_area_pie_9_factor")

            col = box.column(align=True)
            row = col.row(align=True)
            # LEFT
            box_1 = row.box()
            col = box_1.column(align=True)
            col.prop(self, "split_area_pie_4_ui")
            col.prop(self, "split_area_pie_4_pos")
            col.prop(self, "split_area_pie_4_factor")
            row.separator()
            # CENTER
            box_2 = row.box()
            col = box_2.column(align=True)
            col.label(text=" ")
            col.label(text=" ")
            col.label(text=" ")
            row.separator()
            # RIGHT
            box_3 = row.box()
            col = box_3.column(align=True)
            col.prop(self, "split_area_pie_6_ui")
            col.prop(self, "split_area_pie_6_pos")
            col.prop(self, "split_area_pie_6_factor")

            col = box.column(align=True)
            row = col.row(align=True)

            # BOTTOM LEFT
            box_1 = row.box()
            col = box_1.column(align=True)
            col.prop(self, "split_area_pie_1_ui")
            col.prop(self, "split_area_pie_1_pos")
            col.prop(self, "split_area_pie_1_factor")
            row.separator()
            # BOTTOM
            box_2 = row.box()
            col = box_2.column(align=True)
            col.prop(self, "split_area_pie_2_ui")
            col.prop(self, "split_area_pie_2_pos")
            col.prop(self, "split_area_pie_2_factor")
            row.separator()
            # BOTTOM RIGHT
            box_3 = row.box()
            col = box_3.column(align=True)
            col.prop(self, "split_area_pie_3_ui")
            col.prop(self, "split_area_pie_3_pos")
            col.prop(self, "split_area_pie_3_factor")

            # Executor
            col = column_main.column(align=False)
            box = col.box()
            col = box.column(align=True)
            col.label(text="Script Executor:")
            col.separator()
            col.separator()
            col.separator()
            col.prop(self, "executor_use_script_path_user")
            row = col.row(align=True)
            if self.executor_use_script_path_user:
                row.label(text=bpy.utils.script_path_user())
                col.prop(self, "executor_scripts_subfolder")
                if len(self.executor_scripts_subfolder) > 0:
                    self.executor_scripts_folder = os.path.join(
                        bpy.utils.script_path_user(), self.executor_scripts_subfolder
                    )
                else:
                    self.executor_scripts_folder = bpy.utils.script_path_user()
            else:
                col.prop(self, "executor_scripts_folder")
            col.separator()
            col.separator()
            col.separator()
            col.prop(self, "executor_column_count")
            col.prop(self, "executor_name_length")
            col.separator()
            # Textures to materials
            col = column_main.column(align=False)
            box = col.box()
            col = box.column(align=True)
            col.label(text="Textures to Materials:")
            col = box.column(align=True)
            col.prop(self, "texture_to_material_prefixes")
            col.prop(self, "texture_to_material_suffixes")
            col.separator()

           # Cursor Bisect preferences
            col = column_main.column(align=False)
            box = col.box()
            col = box.column(align=True)
            col.label(text="Cursor Bisect:")

            # Plane settings
            col.separator()
            col.label(text="Bisect Plane:")
            row = col.row(align=True)
            row.prop(self, "cursor_bisect_plane_color")
            row.prop(self, "cursor_bisect_plane_outline_color")
            row = col.row(align=True)
            row.prop(self, "cursor_bisect_plane_outline_thickness")

            # Edge settings
            col.separator()
            col.label(text="Edge Highlight:")
            row = col.row(align=True)
            row.prop(self, "cursor_bisect_edge_color")
            row.prop(self, "cursor_bisect_edge_locked_color")
            row = col.row(align=True)
            row.prop(self, "cursor_bisect_edge_thickness")
            row.prop(self, "cursor_bisect_edge_locked_thickness")

            # Snap point settings
            col.separator()
            col.label(text="Snap Points:")
            row = col.row(align=True)
            row.prop(self, "cursor_bisect_snap_color")
            row.prop(self, "cursor_bisect_snap_hold_color")
            row = col.row(align=True)
            row.prop(self, "cursor_bisect_snap_closest_color")
            row.prop(self, "cursor_bisect_snap_closest_hold_color")
            row = col.row(align=True)
            row.prop(self, "cursor_bisect_snap_size")
            row.prop(self, "cursor_bisect_snap_closest_size")
            row = col.row(align=True)
            row.prop(self, "cursor_bisect_edge_subdivisions")

            # Cut preview settings
            col.separator()
            col.label(text="Cut Preview:")
            row = col.row(align=True)
            row.prop(self, "cursor_bisect_cut_preview_color")
            row = col.row(align=True)
            row.prop(self, "cursor_bisect_cut_preview_thickness")

            # Face connectivity settings
            col.separator()
            col.label(text="Preview Scope:")
            row = col.row(align=True)
            row.prop(self, "cursor_bisect_face_depth")
            row.prop(self, "cursor_bisect_max_faces", text="Fallback Limit")
            # Coplanar angle
            col.separator()
            col.label(text="Coplanar Angle:")
            row = col.row(align=True)
            row.prop(self, "cursor_bisect_coplanar_angle")
            col.separator()
            # Bisect operation settings
            col.separator()
            col.label(text="Operation Settings:")
            row = col.row(align=True)
            row.prop(self, "cursor_bisect_merge_distance")
            row.prop(self, "cursor_bisect_rotation_step")
            row.prop(self, "cursor_bisect_snap_threshold")
            row.prop(self, "cursor_bisect_snap_use_modifiers")
            # Distance text settings
            col.separator()
            col.label(text="Bisect Info Text Settings:")
            row = col.row(align=True)
            row.prop(self, "cursor_bisect_distance_text_color", text="Text Color")            
            row.prop(self, "cursor_bisect_distance_text_size", text="Text Size")
            row.prop(self, "cursor_bisect_distance_offset_x", text="Offset X")
            row.prop(self, "cursor_bisect_distance_offset_y", text="Offset Y")
            col.separator()

            # Snap Combos
            col = column_main.column(align=False)
            box = col.box()
            col = box.column(align=True)
            col.label(text="Snap Combo:")
            row = box.row(align=True)
            row.alignment = "LEFT"
            row.prop(self, "snap_combo_mod")

            # Preferences
            col = column_main.column(align=False)
            box = col.box()
            col = box.column(align=True)
            col.label(text="Addon preferences")
            row = col.row(align=True)
            row.operator("iops.save_addon_preferences", text="Save preferences")
            row.operator("iops.load_addon_preferences", text="Load preferences")
            col.separator()

            # Debug
            col = column_main.column(align=False)
            box = col.box()
            col = box.column(align=True)
            col.label(text="Debug:")
            row = box.row(align=True)
            row.alignment = "LEFT"
            row.prop(self, "IOPS_DEBUG")
