import bpy
import numpy as np
from mathutils import Vector, Matrix


class IOPS_OT_ToGridFromActive(bpy.types.Operator):
    """Locations to grid from active"""
    bl_idname = "iops.to_grid_from_active"
    bl_label = "To Grid From Active"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(self, context):
        return (context.area.type == "VIEW_3D" and
                context.mode == "OBJECT" and
                len(context.view_layer.objects.selected) != 0)

    def execute(self, context):
        C = bpy.context
        active = C.view_layer.objects.active
        origin = active.location
        objects = C.selected_objects
        mx_orig = active.matrix_world.copy()

        # Reset transforms of all
        bpy.ops.object.parent_set(type='OBJECT', keep_transform=True)
        active.matrix_world @= active.matrix_world.inverted()
        bpy.ops.object.parent_clear(type='CLEAR_KEEP_TRANSFORM')                

        # Sizes
        size_x = active.dimensions[0]
        size_y = active.dimensions[1]
        size_z = active.dimensions[2]

        o_xz = np.array([origin[0], origin[2]], dtype=np.float32)
        # Move objects to grid
        # for o in objects:
        #     p = np.array([o.location[0], o.location[2]], dtype=np.float32)
        #     p_prime = np.around((p - o_xz) / (size_x, size_z)) * (size_x, size_z) + o_xz
        #     if np.allclose(p, p_prime):
        #         print(f'Skipping p={p}, pp={p_prime}, p-pp={p-p_prime}')
        #         continue
        #     location = Vector((p_prime[0], origin[1], p_prime[1]))
        #     o.rotation_euler = (0, 0, 0)
        #     o.scale = (1, 1, 1)
        #     o.location = location
        # print("-" * 60)
        # Move objects to grid      
        for o in objects: 
            print("Location difference before:", o.location - active.location)
            p = np.array([o.location[0], o.location[2]]) 
            p_prime = np.around((p - o_xz) / (size_x, size_z)) * (size_x, size_z) + o_xz 
            if np.allclose(p, p_prime, rtol=1e-21, atol=1e-24): 
                continue 
            location = Vector((p_prime[0], origin[1], p_prime[1])) 
            o.matrix_world @= o.matrix_world.inverted() 
            o.location = location
            print("Location difference after:", o.location - active.location)

            print("----")
            print('p', p)
            print('p_prime', p_prime)

        # Restore matrix for all and clear parent    
        bpy.ops.object.parent_set(type='OBJECT', keep_transform=True)
        active.matrix_world = mx_orig   
        bpy.ops.object.parent_clear(type='CLEAR_KEEP_TRANSFORM')

        self.report({"INFO"}, "Aligned to grid from active")

        return {'FINISHED'}

