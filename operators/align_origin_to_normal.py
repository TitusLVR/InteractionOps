import bpy
from bpy.props import (
    FloatVectorProperty
)
import bmesh
from mathutils import Matrix


class IOPS_OT_AlignOriginToNormal(bpy.types.Operator):
    """Align object to selected face"""

    bl_idname = "iops.mesh_align_origin_to_normal"
    bl_label = "MESH: Align origin to face normal"
    bl_options = {"REGISTER", "UNDO"}

    loc: FloatVectorProperty()
    orig_mx = []

    @classmethod
    def poll(self, context):
        return (
            context.area.type == "VIEW_3D"
            and context.mode == "EDIT_MESH"
            and len(context.view_layer.objects.selected) != 0
            and context.view_layer.objects.active.type == "MESH"
        )

    def align_origin_to_normal(self):

        bpy.ops.view3d.snap_cursor_to_selected()
        bpy.ops.object.mode_set(mode="OBJECT")
        bpy.ops.object.origin_set(type="ORIGIN_CURSOR")
        bpy.ops.object.mode_set(mode="EDIT")

        obj = bpy.context.view_layer.objects.active
        mx = obj.matrix_world.copy()
        loc = mx.to_translation()  # Store location
        scale = mx.to_scale()  # Store scale
        polymesh = obj.data
        bm = bmesh.from_edit_mesh(polymesh)
        face = bm.faces.active

        # Return face tangent based on longest edge.
        tangent = face.calc_tangent_edge()

        # Build vectors for new matrix
        n = face.normal
        t = tangent
        c = n.cross(t)

        # Assemble new matrix
        mx_new = Matrix((t * -1.0, c * -1.0, n)).transposed().to_4x4()

        # New matrix rotation part
        new_rot = mx_new.to_euler()

        # Apply new matrix
        obj.matrix_world = mx_new.inverted()
        obj.location = loc
        obj.scale = scale

        bpy.ops.object.mode_set(mode="OBJECT")
        bpy.ops.object.transform_apply(
            location=False, rotation=True, scale=False, properties=False
        )
        obj.rotation_euler = new_rot

    def execute(self, context):
        if context.object and context.area.type == "VIEW_3D":
            # Apply transform so it works multiple times
            bpy.ops.object.mode_set(mode="OBJECT")
            bpy.ops.object.transform_apply(
                location=False, rotation=True, scale=False, properties=False
            )
            bpy.ops.object.mode_set(mode="EDIT")

            # Initialize axis and assign starting values for object's location
            self.axis_rotate = "Z"
            self.flip = True
            self.edge_idx = 0
            self.counter = 0
            self.align_origin_to_normal()

            return {"FINISHED"}

        else:
            self.report({"WARNING"}, "No active object, could not finish")
            return {"FINISHED"}
