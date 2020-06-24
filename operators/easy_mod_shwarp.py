import bpy
from bpy.props import (BoolProperty,
                       EnumProperty,
                       FloatProperty,
                       IntProperty,
                       PointerProperty,
                       StringProperty,
                       FloatVectorProperty,
                       )

class IOPS_OT_Easy_Mod_Shwarp(bpy.types.Operator):
    """Select picked curve in curve modifier"""
    bl_idname = "iops.easy_mod_shwarp"
    bl_label = "Easy Modifier - Shrinkwarp"
    bl_options = {'REGISTER', 'UNDO'}

    shwarp_offset:FloatProperty(
        name="Offset", 
        description="Offset factor", 
        default=0.0, 
        min=0.00,
        max=9999.0,
    )
    shwarp_method: EnumProperty(
        name='Mode',
        description='Mod',
        items=[
            ('NEAREST_SURFACEPOINT', 'NEAREST_SURFACEPOINT',  '', '', 0),
            ('PROJECT', 'PROJECT',  '', '', 1),
            ('NEAREST_VERTEX', 'NEAREST_VERTEX',  '', '', 2),
            ('TARGET_PROJECT', 'TARGET_PROJECT',  '', '', 3),
            ],
        default='NEAREST_VERTEX',
    )
    shwarp_use_vg: BoolProperty(
        name="Use vertex groups",
        description="Takes last one",
        default=False
    ) 
    

    @classmethod
    def poll(cls, context):
        return (context.object.type == "MESH" and 
                context.area.type == "VIEW_3D" and
                len(context.view_layer.objects.selected) >= 2)

    def execute(self, context):
        target = context.active_object
        objs = []

        for ob in context.view_layer.objects.selected:
            if ob.name != target.name and ob.type == "MESH":
                objs.append(ob) 
        
        
        if objs and target:
            print(objs)
            for ob in objs:
                if ob.modifiers:
                    if ob.modifiers[-1].type == "SHRINKWRAP":
                        mod = ob.modifiers[-1]
                        mod.show_in_editmode = True
                        mod.show_on_cage = True
                        mod.target = target 
                        mod.offset = self.shwarp_offset                        
                        mod.wrap_method = self.shwarp_method
                        if self.shwarp_use_vg:
                            mod.vertex_group = ob.vertex_groups[0].name
                else:
                    mod = ob.modifiers.new("iOps Shwarp", type='SHRINKWRAP')
                    mod.show_in_editmode = True
                    mod.show_on_cage = True
                    mod.target = target
                    mod.offset = self.shwarp_offset                    
                    mod.wrap_method = self.shwarp_method
                    if self.shwarp_use_vg:
                            mod.vertex_group = ob.vertex_groups[0].name
            
        return {'FINISHED'}
        

