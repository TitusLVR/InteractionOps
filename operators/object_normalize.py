import bpy
import math
from mathutils import Vector
from bpy.props import BoolProperty, IntProperty


class IOPS_OT_object_normalize(bpy.types.Operator):
    """Normalize location,Rotation,Scale,Dimensions values"""

    bl_idname = "iops.object_normalize"
    bl_label = "IOPS object normalize"
    bl_options = {"REGISTER", "UNDO"}

    precision: IntProperty(
        name="Precision",
        description="Digits after point",
        default=2,
        soft_min=0,
        soft_max=10,
    )
    location: BoolProperty(
        name="Trim location", description="Trim location values", default=True
    )
    rotation: BoolProperty(
        name="Trim rotation", description="Trim rotation values", default=True
    )

    dimensions: BoolProperty(
        name="Trim dimentsion", description="Trim dimentsion values", default=True
    )

    @classmethod
    def poll(self, context):
        return (
            context.area.type == "VIEW_3D"
            and context.mode == "OBJECT"
            and len(context.view_layer.objects.selected) != 0
            and (
                context.view_layer.objects.active.type == "MESH"
                or context.view_layer.objects.active.type == "EMPTY"
            )
        )

    def execute(self, context):
        selection = context.view_layer.objects.selected
        dg = bpy.context.evaluated_depsgraph_get()
        for ob in selection:
            if self.location:
                pos_x = round(ob.location.x, self.precision)
                pos_y = round(ob.location.y, self.precision)
                pos_z = round(ob.location.z, self.precision)
                ob.location.x = pos_x
                ob.location.y = pos_y
                ob.location.z = pos_z

            if self.rotation:
                rot_x = round(math.degrees(ob.rotation_euler.x), self.precision)
                rot_y = round(math.degrees(ob.rotation_euler.y), self.precision)
                rot_z = round(math.degrees(ob.rotation_euler.z), self.precision)
                ob.rotation_euler.x = math.radians(rot_x)
                ob.rotation_euler.y = math.radians(rot_y)
                ob.rotation_euler.z = math.radians(rot_z)

            if self.dimensions:
                dim_x = round(ob.dimensions.x, self.precision)
                dim_y = round(ob.dimensions.y, self.precision)
                dim_z = round(ob.dimensions.z, self.precision)
                ob.dimensions = Vector((dim_x, dim_y, dim_z))
        dg.update()
        self.report({"INFO"}, "Object dimensions normalized")
        return {"FINISHED"}
