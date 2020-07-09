import bpy
from bpy.props import (BoolProperty,
                       EnumProperty,
                       FloatProperty,
                       IntProperty,
                       PointerProperty,
                       StringProperty,
                       FloatVectorProperty,
                       )
                    

class IOPS_OT_KitBash_Grid(bpy.types.Operator):
    """Perfect for KitBashing. Set selected objects to grid."""
    bl_idname = "iops.kitbash_grid"
    bl_label = "Grid!"
    bl_options = {'REGISTER', 'UNDO'}

    
    kitBash_grid_distance: FloatProperty(
        name="Distance",
        description="Distance between objects",
        default=1.0,
        soft_min=0.0,
        soft_max=1000.0
        )

    kitBash_grid_count: IntProperty(
        name="Count",
        description="Count",
        default=5,
        min=1,
        max=100
        )

    kitBash_use_cursor: BoolProperty( 
        name="Use Cursor",
        description="Use Cursor as starting point",
        default=True
        )

    kitBash_apply_location: BoolProperty( 
        name="Apply Location",
        description="Apply Location",
        default=False
        )
    kitBash_apply_rotation: BoolProperty( 
        name="Apply Rotation",
        description="Apply Rotation",
        default=False
        )
    kitBash_apply_scale: BoolProperty( 
        name="Apply Scale",
        description="Apply Scale",
        default=False
        )
    
    kitBash_clear_location: BoolProperty( 
        name="Clear Location",
        description="Clear Location",
        default=False
        )
    kitBash_clear_rotation: BoolProperty( 
        name="Clear Rotation",
        description="Clear Rotation",
        default=False
        )
    kitBash_clear_scale: BoolProperty( 
        name="Clear Scale",
        description="Clear Scale",
        default=False
        )



    @classmethod
    def poll(cls, context):
        return (context.area.type == "VIEW_3D")

    def execute(self, context):
        # Apply
        if self.kitBash_apply_location or self.kitBash_apply_rotation or self.kitBash_apply_scale:
            bpy.ops.object.transform_apply(location=self.kitBash_apply_location, rotation=self.kitBash_apply_rotation, scale=self.kitBash_apply_scale)
        
        # Reset
        if self.kitBash_clear_location:
            bpy.ops.object.location_clear(clear_delta=False)
        if self.kitBash_clear_rotation:
            bpy.ops.object.rotation_clear(clear_delta=False)
        if self.kitBash_clear_scale:
            bpy.ops.object.scale_clear(clear_delta=False)

        # use cursor
        if self.kitBash_use_cursor:             
            for o in bpy.context.selected_objects:
                o.location = bpy.context.scene.cursor.location
        else:
            for o in bpy.context.selected_objects:
                o.location = (0,0,0)
        
        # do shit
        x = 0
        y = 0        
        dist = self.kitBash_grid_distance
        count = self.kitBash_grid_count       

        for o in bpy.context.selected_objects:
            dx = dist * x
            dy = dist * y        
            if x < count - 1:                
                o.location[0] += dx
                o.location[1] += dy
                x += 1 
                print ("X:", x)
            elif y <= count:
                x = 0
                y += 1
                o.location[0] += dx
                o.location[1] += dy
                print ("Y:", y)
            elif y > count:
                x = 0
                y += 1                
                o.location[0] += dx
                o.location[1] += dy
                print ("Y>:", y)

            

        self.report ({'INFO'}, "Grid! - DONE!")
        return {'FINISHED'}

    def draw(self, context):
        layout = self.layout
        col = layout.column(align=True)        
        col.label(text="Transform:")
        
        split = layout.split()        
        col = split.column()
        col.prop(self, "kitBash_apply_location")
        col.prop(self, "kitBash_apply_rotation")
        col.prop(self, "kitBash_apply_scale")

        # Second column, aligned
        col = split.column(align=True)
        col.prop(self, "kitBash_clear_location")
        col.prop(self, "kitBash_clear_rotation")
        col.prop(self, "kitBash_clear_scale")        
        
        col = layout.column(align=True)
        col.label(text="Grid:")
        col.prop(self, "kitBash_use_cursor")
        col.prop(self, "kitBash_grid_count")
        col.prop(self, "kitBash_grid_distance")
        

