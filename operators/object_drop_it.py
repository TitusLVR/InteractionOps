import bpy
from mathutils import Vector, Matrix
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
    
    drop_it_alg: EnumProperty(
        name='Method',
        description='Methods: TrackTo and Project',
        items=[
            ('A', 'TrackTo',  '', '', 0),
            ('B', 'Project',  '', '', 1),            
            ],
        default='B',
        )
    use_local_z: BoolProperty(
        name="Use Local Z",
        description="Object local Z axis as direction",
        default=True
    )





    @classmethod
    def poll(cls, context):
        return (context.area.type == "VIEW_3D")

    def execute(self, context):                
        selected_objs = [o.name for o in bpy.context.view_layer.objects.selected]
        
        if self.drop_it_alg == 'A':
            track_axis = self.drop_it_track        
            up_axis = self.drop_it_up
            if track_axis != up_axis:
                for ob in selected_objs:
                    obj = bpy.context.scene.objects[ob]
                    
                    if self.use_local_z:
                        z_axis = Vector((0, 0, -1))
                        direction = (obj.matrix_world.to_3x3() @ z_axis).normalized()                   
                    else:
                        direction = Vector((self.drop_it_direction_x, self.drop_it_direction_y, self.drop_it_direction_z))

                    obj_origin = obj.location
                    scale = obj.scale.copy()
                    
                    obj.hide_set(True)
                    view_layer = bpy.context.view_layer
                    
                    if bpy.app.version[1] > 90:
                        result, location, normal, __, __, __ = bpy.context.scene.ray_cast(view_layer.depsgraph, obj_origin, direction, distance=1.70141e+38)
                    else:
                        result, location, normal, __, __, __ = bpy.context.scene.ray_cast(view_layer, obj_origin, direction, distance=1.70141e+38)

                    if result:                
                        obj.hide_set(False)
                                                            
                        if self.drop_it_align_to_surf:                                  
                            mx_pos = Matrix.Translation((location))
                            mx_rot = normal.to_track_quat(track_axis, up_axis).to_matrix().to_4x4() 
                            obj.matrix_world = mx_pos @ mx_rot
                        else:
                            mx_rot = obj.rotation_euler.to_matrix().to_4x4()
                            obj.matrix_world = Matrix.Translation((location)) @ mx_rot                            
                                        
                        vec = Matrix.Translation((self.drop_it_offset_x, self.drop_it_offset_y, self.drop_it_offset_z))
                        obj.matrix_world @= vec                           
                        obj.scale = scale                    
                        
                    else:
                        obj.hide_set(False)
                        self.report ({'ERROR'}, "DropIt! - Raycast failed!" + ob)
                        return {'FINISHED'}
                        
                for ob in selected_objs:
                    bpy.context.scene.objects[ob].select_set(True)
                self.report ({'INFO'}, "DropIt! - DONE!")
            else:
                self.report ({'ERROR'}, "Track and Up axis must be different!!!")
                return {'FINISHED'}
            
        else:   
            for ob in selected_objs:
                obj = bpy.context.scene.objects[ob]
                scale = obj.scale.copy()
                obj_origin = obj.location
                view_layer = bpy.context.view_layer
                if self.use_local_z:
                    z_axis = Vector((0, 0, -1))
                    direction = (obj.matrix_world.to_3x3() @ z_axis).normalized()                  
                else:
                    direction = Vector((self.drop_it_direction_x, self.drop_it_direction_y, self.drop_it_direction_z))
                
                # Construct helper
                loc2_offset = obj.dimensions[0]/100
                obj.hide_set(True)

                if bpy.app.version[1] > 90:
                    result, location, normal,_ ,_ ,_= bpy.context.scene.ray_cast(view_layer.depsgraph, obj_origin, direction, distance=1.70141e+38)
                    result2, location2, normal2,_ ,_ ,_= bpy.context.scene.ray_cast(view_layer.depsgraph, obj_origin + Vector((loc2_offset, 0, 0)) @ obj.matrix_world.inverted(), direction, distance=1.70141e+38)
                else:
                    result, location, normal,_ ,_ ,_= bpy.context.scene.ray_cast(view_layer, obj_origin, direction, distance=1.70141e+38)
                    result2, location2, normal2,_ ,_ ,_= bpy.context.scene.ray_cast(view_layer, obj_origin + Vector((loc2_offset, 0, 0)) @ obj.matrix_world.inverted(), direction, distance=1.70141e+38)

                if result and result2:                    
                    obj.hide_set(False)
                    # Vectors
                    n = normal.normalized()
                    t = (location2 - location).normalized()
                    c = n.cross(t).normalized()

                    mx_new = Matrix((t, c, n)).transposed().to_4x4()                   
                    mx_new.translation = location
                    # mx_new @= vec
                    obj.matrix_world = mx_new
                    vec = Matrix.Translation((self.drop_it_offset_x, self.drop_it_offset_y, self.drop_it_offset_z))
                    obj.matrix_world @= vec
                    obj.scale = scale
                else:
                    obj.hide_set(False)
                    self.report ({'ERROR'}, "DropIt! - Raycast failed!" + ob)
                    return {'FINISHED'}
        
            for ob in selected_objs:
                bpy.context.scene.objects[ob].select_set(True)
            self.report ({'INFO'}, "DropIt! - DONE!")
        return {'FINISHED'}

    def draw(self, context):
        layout = self.layout
        col = layout.column(align=True)
        col.label(text="Direction:")
        col.prop(self, "drop_it_alg")
        col.prop(self, "use_local_z")
        col.label(text="Direction:")
        if self.use_local_z:
            col.label(text="Object Z-Axis")
        else:    
            col.prop(self, "drop_it_direction_x")
            col.prop(self, "drop_it_direction_y")
            col.prop(self, "drop_it_direction_z") 
        col.separator()       
        col.label(text="Offset:")
        col.prop(self, "drop_it_offset_x")
        col.prop(self, "drop_it_offset_y")
        col.prop(self, "drop_it_offset_z") 
        col.separator()
        if self.drop_it_alg == 'A':            
            col.label(text="Align:")
            col.prop(self, "drop_it_align_to_surf")
            if self.drop_it_align_to_surf:
                row = col.row()
                row.prop(self, "drop_it_track")
                row.prop(self, "drop_it_up")
        else:
            col.label(text="Align:Disabled")
        


