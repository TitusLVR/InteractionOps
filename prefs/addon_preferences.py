import bpy
from bpy.types import (        
        Operator,
        Menu,
        Panel,
        PropertyGroup,
        AddonPreferences,
        )
from bpy.props import (
        BoolProperty,
        EnumProperty,
        FloatProperty,
        IntProperty,
        PointerProperty,
        StringProperty,
        FloatVectorProperty,
        )


class IOPS_AddonPreferences(bpy.types.AddonPreferences):
    bl_idname = "InteractionOps"

    text_color : FloatVectorProperty(
        name = "Color", 
        subtype = 'COLOR',
        size = 4,
        min = 0,
        max = 1,  
        default = (0.25,0.25,0.25,0.5),        
        )
    text_size : IntProperty (
        name="Size",
        description="Modal operators text size",
        default=12,
        soft_min=1,
        soft_max=1000
        )
    text_pos_x : IntProperty (
        name="Position X",
        description="Modal operators Text pos X",
        default=12,
        soft_min=1,
        soft_max=1000
        )
    text_pos_y : IntProperty (
        name="Position Y",
        description="Modal operators Text pos Y",
        default=12,
        soft_min=1,
        soft_max=1000
        )    
    vo_cage_color : FloatVectorProperty(
        name = "Cage color", 
        subtype = 'COLOR',
        size = 4,
        min = 0,
        max = 1, 
        default = (0.573, 0.323, 0.15, 1),        
        )
    vo_cage_points_color : FloatVectorProperty(
        name = "Cage points color", 
        subtype = 'COLOR',
        size = 4,
        min = 0,
        max = 1,  
        default = (0.873, 0.623, 0.15, 1),       
        )
    vo_cage_ap_color : FloatVectorProperty(
        name = "Active point color", 
        subtype = 'COLOR',
        size = 4,
        min = 0,
        max = 1,  
        default = (1, 0, 0, 1),        
        )
    align_edge_color : FloatVectorProperty(
        name = "Edge color", 
        subtype = 'COLOR',
        size = 4,
        min = 0,
        max = 1, 
        default = (0, 1, 0, 1),        
        )    
    align_point_color : FloatVectorProperty(
        name = "Point color", 
        subtype = 'COLOR',
        size = 4,
        min = 0,
        max = 1, 
        default = (0, 1, 0, 1),        
        )



    def draw(self, context):
        layout = self.layout 
        col = layout.column()
        row = col.row(align=True)
        # we don't want to put anything else on this row other than the 'split' item
        split = row.split(factor = 0.65, align=False)
        box_kmp = split.box()
        box_ui = split.box() 
        # Keymaps
       
        box_kmp.label(text='Keymaps:')
        try:
            mainRow = box_kmp.row(align=True)
            mainRow.alignment = 'LEFT'            

            colLabels = mainRow.column(align=True)
            colLabels.alignment = 'RIGHT'

            colKeys = mainRow.column(align=True)
            colKeys.alignment = 'EXPAND'

            keymap = context.window_manager.keyconfigs.user.keymaps["Window"]
            colKeys.context_pointer_set("keymap", keymap) # For the 'wm.keyitem_restore' operator.

            for item in reversed(keymap.keymap_items):
                if item.idname.startswith('iops.'):
                    op = eval("bpy.ops."+ item.idname + ".get_rna_type()")                    
                    colLabels.label(text = op.name)
                    subRow = colKeys.row()
                    subRow.alignment = 'LEFT'
                    subRow.prop(item, 'type', text='', full_event=True)
                    subRow.prop(item, 'shift')
                    subRow.prop(item, 'ctrl')
                    subRow.prop(item, 'alt')
                    if item.is_user_modified:
                        subRow.operator('preferences.keyitem_restore', text='', icon='BACK').item_id = item.id

        except:
            layout.label(text='No keymaps found.', icon='ERROR')
        box_ui.label(text='UI Tweaks:')        
        col = box_ui.column(align=True)
        box = box_ui.box()
        col = box.column(align=True)
        col.label(text="Text settings:")
        col.prop(self, "text_color")
        col = box.column(align=True)
        col.prop(self, "text_size")
        col = box.column(align=True)
        col.prop(self, "text_pos_x")
        col.prop(self, "text_pos_y")
        box = box_ui.box()
        col = box.column(align=True)        
        col.label(text="Align to edge:")
        col.prop(self, "align_edge_color") 
        box = box_ui.box()
        col = box.column(align=True)        
        col.label(text="Visual origin:")
        col.prop(self, "vo_cage_color")
        col.prop(self, "vo_cage_points_color")
        col.prop(self, "vo_cage_ap_color")



