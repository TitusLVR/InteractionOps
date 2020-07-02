import bpy
from mathutils import Vector
from bpy.props import (BoolProperty,
                       EnumProperty,
                       FloatProperty,
                       IntProperty,
                       PointerProperty,
                       StringProperty,
                       FloatVectorProperty,
                       )
                    

class IOPS_OT_Drop_It(bpy.types.Operator):
    """Drop objects to surface"""
    bl_idname = "iops.drop_it"
    bl_label = "Drop It!"
    bl_options = {'REGISTER', 'UNDO'}

    
    drop_it_direction_x:FloatProperty(
        name="X", 
        description="Direction X", 
        default=0.0, 
        min=-1,
        max=1,
    )
    drop_it_direction_y:FloatProperty(
        name="Y", 
        description="Direction Y", 
        default=0.0, 
        min=-1,
        max=1,
    )
    drop_it_direction_z:FloatProperty(
        name="Z", 
        description="Direction Z", 
        default=-1.0, 
        min=-1,
        max=1,
    )

    drop_it_offset_x:FloatProperty(
        name="X", 
        description="Offset X", 
        default=0.0, 
        min=-1000000,
        max=1000000,
    )
    drop_it_offset_y:FloatProperty(
        name="Y", 
        description="Offset Y", 
        default=0.0, 
        min=-1000000,
        max=1000000,
    )
    drop_it_offset_z:FloatProperty(
        name="Z", 
        description="Offset Z", 
        default=0.0, 
        min=-1000000,
        max=1000000,
    )
    
    drop_it_align_to_surf: BoolProperty(
        name="Align",
        description="Align to surface",
        default=True
    )

    drop_it_track: EnumProperty(
        name='Track',
        description='Track axis',
        items=[
            ('X', 'X',  '', '', 0),
            ('Y', 'Y',  '', '', 1),
            ('Z', 'Z',  '', '', 2),
            ('-X', '-X',  '', '', 3),
            ('-Y', '-Y',  '', '', 4),
            ('-Z', '-Z',  '', '', 5),
            ],
        default='Z',
    )
    drop_it_up: EnumProperty(
        name='Up',
        description='Up axis',
        items=[
            ('X', 'X',  '', '', 0),
            ('Y', 'Y',  '', '', 1),
            ('Z', 'Z',  '', '', 2),
            ],
        default='Y',
    )

    @classmethod
    def poll(cls, context):
        return (context.area.type == "VIEW_3D")

    def execute(self, context):
        selected_objs = [o.name for o in bpy.context.view_layer.objects.selected]
        track_axis = self.drop_it_track        
        up_axis = self.drop_it_up
        direction = Vector((self.drop_it_direction_x, self.drop_it_direction_y, self.drop_it_direction_z))
      
        for ob in selected_objs:
            obj = bpy.context.scene.objects[ob]
            obj_origin = obj.location
            obj.hide_set(True)
            view_layer = bpy.context.view_layer
            result, location, normal, __, __, __ = bpy.context.scene.ray_cast(view_layer, obj_origin, direction, distance=1.70141e+38)
            if result:                
                obj.hide_set(False)
                obj.location = (location[0] + self.drop_it_offset_x, location[1] + self.drop_it_offset_y, location[2] + self.drop_it_offset_z) 
                if  self.drop_it_align_to_surf:          
                    obj.rotation_euler = normal.to_track_quat(track_axis, up_axis).to_euler()
                self.report ({'INFO'}, "DropIt! - DONE!")
            else:
                obj.hide_set(False)
                self.report ({'ERROR'}, "DropIt! - Raycast failed!" + ob)
        return {'FINISHED'}

    def draw(self, context):
        layout = self.layout
        col = layout.column(align=True)
        col.label(text="Direction:")
        col.prop(self, "drop_it_direction_x")
        col.prop(self, "drop_it_direction_y")
        col.prop(self, "drop_it_direction_z") 
        col.separator()       
        col.label(text="Offset:")
        col.prop(self, "drop_it_offset_x")
        col.prop(self, "drop_it_offset_y")
        col.prop(self, "drop_it_offset_z") 
        col.separator() 
        col.label(text="Align:")
        col.prop(self, "drop_it_align_to_surf")
        if self.drop_it_align_to_surf:
            row = col.row()
            row.prop(self, "drop_it_track")
            row.prop(self, "drop_it_up")

