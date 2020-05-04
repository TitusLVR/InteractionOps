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
            ('NEAREST_VERTEX', 'NEAREST_VERTEX',  '', '', 0),
            ],
        default='NEAREST_VERTEX',
    )
    

    @classmethod
    def poll(cls, context):
        return (context.object.type == "MESH" and 
                context.area.type == "VIEW_3D" and
                len(context.view_layer.objects.selected) >= 2)

    def execute(self, context):
        obj = context.active_object
        targets = []

        for ob in context.view_layer.objects.selected:
            if ob.name != obj.name and ob.type == "MESH":
                targets.append(ob) 
        
        if obj and targets:
            bpy.ops.object.select_all(action='DESELECT')
            dupes = [] 
            for ob in targets:
                newObj = ob.copy()
                newObj.data = ob.data.copy()
                newObj.animation_data_clear()
                newObj.name = ob.name + "__SHWARPS"
                newObj.use_fake_user = True
                bpy.context.scene.collection.objects.link(newObj)
                dupes.append(newObj)
            
            bpy.ops.object.select_all(action='DESELECT')
            
            for dupe in dupes:
                dupe.select_set(True)
                bpy.context.view_layer.objects.active = dupe
            bpy.ops.object.join()

            target_obj = bpy.context.view_layer.objects.active

            if obj.modifiers:
                if obj.modifiers[-1].type == "SHRINKWRAP":
                    mod.show_in_editmode = True
                    mod.show_on_cage = True
                    mod = obj.modifiers[-1]
                    mod.target = target_obj
                    mod.warp_method = 'NEAREST_VERTEX'
                    mod.vertex_group = obj.vertex_groups[0]
            else:
                mod = obj.modifiers.new("iOps Shwarp", type='SHRINKWRAP')
                mod.show_in_editmode = True
                mod.show_on_cage = True
                mod.vertex_group = obj.vertex_groups[0].name
                mod.target = target_obj
                mod.wrap_method = 'NEAREST_VERTEX'
            bpy.context.scene.collection.objects.unlink(target_obj)
            
        return {'FINISHED'}
        