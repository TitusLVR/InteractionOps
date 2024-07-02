import bpy
import numpy as np
from mathutils import Vector


class IOPS_OT_ToGridFromActive(bpy.types.Operator):
    """Locations to grid from active"""

    bl_idname = "iops.object_to_grid_from_active"
    bl_label = "To Grid From Active"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(self, context):
        return (
            context.area.type == "VIEW_3D"
            and context.mode == "OBJECT"
            and len(context.view_layer.objects.selected) != 0
        )

    def execute(self, context):
        C = bpy.context
        active = C.view_layer.objects.active
        origin = active.location
        objects = C.selected_objects
        mx_orig = active.matrix_world.copy()

        # Reset transforms of all
        bpy.ops.object.parent_set(type="OBJECT", keep_transform=True)
        active.matrix_world @= active.matrix_world.inverted()
        bpy.ops.object.parent_clear(type="CLEAR_KEEP_TRANSFORM")

        # Sizes
        size_x = active.dimensions[0]
        size_y = active.dimensions[1]
        size_z = active.dimensions[2]

        # Move objects to grid
        o_xyz = np.array([origin[0], origin[1], origin[2]], dtype=np.float32)

        for o in objects:
            print("Location difference before:", o.location - active.location)

            # Extracting 3D coordinates
            p = np.array([o.location[0], o.location[1], o.location[2]])

            # Calculations for X, Y, and Z axes
            p_prime = (
                np.around((p - o_xyz) / (size_x, size_y, size_z))
                * (size_x, size_y, size_z)
                + o_xyz
            )

            # Checking for close match
            if np.allclose(p, p_prime, rtol=1e-21, atol=1e-24):
                continue

            # Setting new location
            location = Vector((p_prime[0], p_prime[1], p_prime[2]))
            o.matrix_world @= o.matrix_world.inverted()
            o.location = location

            print("----")
            print("p", p)
            print("p_prime", p_prime)

        # Restore matrix for all and clear parent
        bpy.ops.object.parent_set(type="OBJECT", keep_transform=True)
        active.matrix_world = mx_orig
        bpy.ops.object.parent_clear(type="CLEAR_KEEP_TRANSFORM")

        self.report({"INFO"}, "Aligned to grid from active")

        return {"FINISHED"}
