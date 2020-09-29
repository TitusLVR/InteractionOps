import bpy
from bpy.types import Menu
from .. utils.functions import *


class IOPS_MT_Pie_Menu(Menu):
    # bl_idname = "iops.pie_menu"
    bl_label = "IOPS_MT_Pie_Menu"

    def draw(self, context):
        forgottentools, _, _, _ = get_addon("Forgotten Tools")
        optiloops, _, _, _ = get_addon("Optiloops")

        layout = self.layout
        pie = layout.menu_pie()

        # 4 - LEFT
        # pie.separator()
        # pie.operator("wm.call_menu_pie", text = "Some Other Pie 0", icon = "RIGHTARROW_THIN").name="Pie_menu"
        col = layout.menu_pie()
        box = col.column(align=True).box().column()
        box.label(text="IOPS")
        col = box.column(align=True)
        col.operator('iops.materials_from_textures', text='Materials from Textures')
        col.operator('iops.easy_mod_array_caps', text="Easy Modifier - Array Caps")
        col.operator('iops.easy_mod_array_curve', text="Easy Modifier - Array Curve")
        col.operator('iops.easy_mod_curve', text="Easy Modifier - Curve")
        col.operator('iops.easy_mod_shwarp', text="Easy Modifier - SHWARP")
        col.operator('iops.quick_snap', text="Quick Snap")
        col.operator('iops.drop_it', text="Drop It!")
        col.operator('iops.kitbash_grid', text="Grid")

        # 6 - RIGHT
        # pie.separator()

        other = pie.row()
        gap = other.column()
        gap.separator()
        gap.scale_y = 7
        other_menu = other.box().column()
        other_menu.scale_y = 1
        other_menu.label(text="BMax")
        other_menu.operator('bmax.export', icon='EXPORT', text="Send to Maya/3dsmax")
        other_menu.operator('bmax.import', icon='IMPORT', text="Get from Maya/3dsmax")
        other_menu = other.box().column()
        other_menu.label(text="BMoI")
        other_menu.operator('bmoi3d.export', icon='EXPORT', text="Send to MoI3D")
        other_menu.operator('bmoi3d.import', icon='IMPORT', text="Get from MoI3D")

        # 2 - BOTTOM
        wm = context.window_manager
        prefs = context.preferences.addons['B2RUVL'].preferences
        uvl = prefs.uvlayout_enable
        ruv = prefs.rizomuv_enable
        uvl_path = prefs.uvlayout_app_path
        ruv_path = prefs.rizomuv_app_path

        col = layout.menu_pie()
        box = col.column(align=True).box().column()
        box.label(text="B2RUVL")
        col_top = box.column(align=True)
        row = col_top.row(align=True)
        col_left = row.column(align=True)
        col_right = row.column(align=True)
        col_left.prop(wm.B2RUVL_PanelProperties, "uvMap_mode", text="")
        col_right.prop(wm.B2RUVL_PanelProperties, "uvMap")
        col_uvl = col_top.column(align=True)
        col_uvl.enabled = uvl is not False and len(uvl_path) != 0
        col_uvl.operator('b2ruvl.send_to_uvlayout')
        col_ruv = col_top.column(align=True)
        col_ruv.enabled = ruv is not False and len(ruv_path) != 0
        col_ruv.operator('b2ruvl.send_to_rizomuv')

        # 8 - TOP
        if forgottentools and context.mode == 'EDIT_MESH':
            other = pie.column()
            gap = other.column()
            gap.separator()
            gap.scale_y = 7
            other_menu = other.box().column()
            other_menu.scale_y=1
            other_menu.label(text="ForgottenTools")
            other_menu.operator('forgotten.mesh_dice_faces')
            other_menu.operator('forgotten.mesh_hinge')
            other_menu.operator('mesh.forgotten_separate_duplicate')
            other_menu.operator("wm.call_panel", text = "Selection Sets", icon = "SELECT_SET").name='FORGOTTEN_PT_SelectionSetsPanel'
        else:
            pie.separator()

        # 7 - TOP - LEFT
        pie.separator()
        # 9 - TOP - RIGHT        
        if optiloops and context.mode == 'EDIT_MESH':            
            pie.operator('mesh.optiloops')
            #pie.separator()

        # 1 - BOTTOM - LEFT
        pie.separator()

        # 3 - BOTTOM - RIGHT
        pie.separator()


class IOPS_OT_Call_Pie_Menu(bpy.types.Operator):
    """IOPS Pie"""
    bl_idname = "iops.call_pie_menu"
    bl_label = "IOPS Pie Menu"    

    def execute(self, context):        
        bpy.ops.wm.call_menu_pie(name="IOPS_MT_Pie_Menu")         
        return {'FINISHED'}
