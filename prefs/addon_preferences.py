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
        )


class IOPS_AddonPreferences(bpy.types.AddonPreferences):
    bl_idname = "InteractionOps"
    
    def draw(self, context):
        layout = self.layout      

        # Keymaps
        box = layout.box()
        box.label(text='Keymaps:')
        try:
            mainRow = box.row(align=True)
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

