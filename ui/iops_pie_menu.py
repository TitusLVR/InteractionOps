import bpy
from bpy.types import Menu
from .. functions.functions import *

#class Submenu(Menu):
#    bl_label = 'Some Submenu'    
#    def draw(self, context):
#        layout = self.layout
#        layout.label(text = "Some Submenu")
#        layout.separator()        
#        layout.operator("mesh.looptools_bridge", text="Bridge")
#        layout.operator("mesh.looptools_circle", text ="Circle")
#        layout.operator("mesh.looptools_curve", text="Curve")
#        layout.operator("mesh.looptools_flatten", text="Flatten")
#        layout.operator("mesh.looptools_gstretch", text="GStrech")
#        layout.operator("mesh.looptools_bridge", text="Loft")
#        layout.operator("mesh.looptools_relax", text="Relax")
#        layout.operator("mesh.looptools_space", text="Space")
       

class IOPS_MT_iops_pie_menu(Menu):
    #bl_idname = "iops.pie_menu"
    bl_label = "IOPS_MT_iops_pie_menu"
    def draw(self, context):
        forgottentools, _, _, _ = get_addon("Forgotten Tools")
        optiloops, _, _, _ = get_addon("Optiloops")

        layout = self.layout
        pie = layout.menu_pie()
        
        # 4 - LEFT
        # pie.separator()        
        #pie.operator("wm.call_menu_pie", text = "Some Other Pie 0", icon = "RIGHTARROW_THIN").name="Pie_menu"
        menu = other = pie.column()
        gap = other.column()
        #gap.separator()
        gap.scale_y = 0.5
        loop_tools = other.box().column()        
        split = loop_tools.split()
        split_l = split.column()
        split_l.label(text = "Loop")
        split_l.scale_y=0.8
        split_l.operator("mesh.looptools_bridge", text="Bridge")
        split_l.operator("mesh.looptools_circle", text ="Circle")
        split_l.operator("mesh.looptools_curve", text="Curve")
        split_l.operator("mesh.looptools_flatten", text="Flatten")
        split_l.operator("mesh.looptools_gstretch", text="GStrech")
        split_l.operator("mesh.looptools_bridge", text="Loft")
        split_l.operator("mesh.looptools_relax", text="Relax")
        split_l.operator("mesh.looptools_space", text="Space")        
        
        split_r = split.column()
        split_r.label(text = "Mesh")
        split_r.scale_y=0.8
        split_r.operator("mesh.remove_doubles")
        split_r.operator("mesh.dissolve_limited")
        split_r.operator("mesh.flip_normals")        
        #split_r.operator("mesh.tris_convert_to_quads")
        #split_r.operator('mesh.vertex_chamfer', text="Vertex Chamfer")
        #split_r.operator("mesh.bevel", text="Bevel Vertices").vertex_only = True
        split_r.operator('mesh.offset_edges', text="Offset Edges")
        split_r.operator('mesh.fillet_plus', text="Fillet Edges")
        split_r.operator("mesh.face_inset_fillet", text="Face Inset Fillet")
        #split_r.operator("mesh.extrude_reshape", text="Push/Pull Faces")
        split_r.operator("object.mextrude", text="Multi Extrude")
        split_r.operator('mesh.split_solidify', text="Split Solidify")
        
        # 6 - RIGHT
        # pie.separator()

        other = pie.column()
        gap = other.column()
        gap.separator()
        gap.scale_y = 7
        other_menu = other.box().column()
        other_menu.scale_y=1
        other_menu.label(text="BMax")
        other_menu.operator('bmax.export', icon='EXPORT',text = "Send to 3dsmax")
        other_menu.operator('bmax.import',icon='IMPORT', text="Get from 3dsmax")
        
        
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
            # other = pie.column()
            # gap = other.column()
            # gap.separator()
            # gap.scale_y = 12
            # other_menu = other.box().column()
            # other_menu.scale_y=1
            # other_menu.label(text="Optiloops")
            pie.operator('mesh.optiloops') 
        else:
            pie.separator()

        # 1 - BOTTOM - LEFT
        pie.separator()

        # 3 - BOTTOM - RIGHT
        pie.separator()

      
        #pie.operator("mesh.primitive_cube_add", text = "2", icon = "BLENDER")
        #pie.operator("mesh.primitive_cube_add", text = "3", icon = "BLENDER")
        #pie.operator("mesh.primitive_cube_add", text = "4", icon = "BLENDER")
        #pie.operator("mesh.primitive_cube_add", text = "5", icon = "BLENDER")
        #pie.operator("mesh.primitive_cube_add", text = "6", icon = "BLENDER")
        #pie.operator("mesh.primitive_cube_add", text = "7", icon = "BLENDER")
#        pie.separator()
#        pie.separator()
#        other = pie.column()
#        gap = other.column()
#        gap.separator()
#        gap.scale_y = 7
#        other_menu = other.box().column()
#        other_menu.scale_y=1
#        other_menu.operator("mesh.primitive_cube_add", text = "Some Menu Operator",icon = "BLENDER")
#        other_menu.operator("mesh.primitive_cube_add", text = "Some Menu Operator",icon = "BLENDER") 
#        other_menu.menu('Submenu', icon='RIGHTARROW_THIN',  text='Some Submenu...')


#def register():
#    #bpy.utils.register_class(Submenu)
#    bpy.utils.register_class(Pie_menu)

#def unregister():
#    #bpy.utils.unregister_class(Submenu)
#    bpy.utils.unregister_class(Pie_menu)

#if __name__ == "__main__":
#    register()

#    bpy.ops.wm.call_menu_pie(name="Pie_menu")