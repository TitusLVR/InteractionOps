from cgitb import text
import bpy
import rna_keymap_ui
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
from ..utils.functions import ShowMessageBox
from ..utils.split_areas_dict import (
    split_areas_dict,
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

    text_size_stat: IntProperty(
        name="Size",
        description="Modal operators text size",
        default=20,
        soft_min=1,
        soft_max=100,
    )

    text_pos_x_stat: IntProperty(
        name="Position X",
        description="Modal operators Text pos X",
        default=60,
        soft_min=1,
        soft_max=10000,
    )

    text_pos_y_stat: IntProperty(
        name="Position Y",
        description="Modal operators Text pos Y",
        default=60,
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
    executor_scripts_folder: StringProperty(
        name="Scripts Folder",
        subtype="DIR_PATH",
        default=bpy.utils.script_path_user(),
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
            col = box.column(align=True)
            col.prop(self, "executor_scripts_folder")
            col.prop(self, "executor_column_count")
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
