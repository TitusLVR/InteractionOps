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
        default='NEAREST_SURFACEPOINT',
    )
    shwarp_use_vg: BoolProperty(
        name="Use vertex groups",
        description="Takes last one",
        default=False
    )

    stack_location: EnumProperty(
        name='Mod location in stack',
        description='Where to put SWARP modifier?',
        items=[
            ('First', 'First',  '', '', 0),
            ('Last', 'Last',  '', '', 1),
            ('Default', 'Default',  '', '', 2)
            ],
        default='Default',
    )
    

    @classmethod
    def poll(cls, context):
        return (context.object.type == "MESH" and 
                context.area.type == "VIEW_3D" and
                len(context.view_layer.objects.selected) >= 2)

    def execute(self, context):
        target = context.active_object
        ctx = bpy.context.copy()
        objs = []

        for ob in context.view_layer.objects.selected:
            if ob.name != target.name and ob.type == "MESH":
                objs.append(ob) 
        
        
        if objs and target:
            #print(objs)
            for ob in objs:

                ctx['object'] = ob
                ctx['active_object'] = ob
                ctx['selected_objects'] = [ob]
                ctx['selected_editable_objects'] = [ob]

                if 'iOps Shwarp' in ob.modifiers.keys():
                    mod = ob.modifiers['iOps Shwarp']
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
                    
                    count = len(ob.modifiers)

                    if self.stack_location == 'First':
                        while count > 0:
                            bpy.ops.object.modifier_move_up(ctx, modifier="iOps Shwarp")
                            count -= 1
                    elif self.stack_location == 'Last':    
                        while count > 0:
                            bpy.ops.object.modifier_move_down(ctx, modifier="iOps Shwarp")
                            count -= 1
                    else: continue

                # if ob.modifiers:
                #     if ob.modifiers[-1].type == "SHRINKWRAP":
                #         mod = ob.modifiers[-1]
                #         mod.show_in_editmode = True
                #         mod.show_on_cage = True
                #         mod.target = target 
                #         mod.offset = self.shwarp_offset                        
                #         mod.wrap_method = self.shwarp_method
                #         if self.shwarp_use_vg:
                #             mod.vertex_group = ob.vertex_groups[0].name
                # else:
                #     mod = ob.modifiers.new("iOps Shwarp", type='SHRINKWRAP')
                #     mod.show_in_editmode = True
                #     mod.show_on_cage = True
                #     mod.target = target
                #     mod.offset = self.shwarp_offset                    
                #     mod.wrap_method = self.shwarp_method
                #     if self.shwarp_use_vg:
                #             mod.vertex_group = ob.vertex_groups[0].name
            
        return {'FINISHED'}
        

