import bpy
from bpy.props import BoolProperty, FloatProperty, EnumProperty
import math
import mathutils

# Cursor Rotate Operator
class IOPS_OT_Cursor_Rotate(bpy.types.Operator):
    """Rotate cursor around X or Y or Z axis"""
    bl_idname = "iops.cursor_rotate"
    bl_label = "Cursor Rotate"
    bl_options = {"REGISTER", "UNDO"}

    reverse: BoolProperty(
        name="reverse", description="Reverse rotation", default=False
    )
    angle: FloatProperty(
        name="angle", description="Rotation angle", default=90
    )
    rotation_axis: EnumProperty(
        name="Axis",
        description="Rotation axis",
        items=[
            ("X", "X", "", "", 0),
            ("Y", "Y", "", "", 1),
            ("Z", "Z", "", "", 2),
        ],
        default="X",
    )

    @classmethod
    def poll(cls, context):
        return context.area.type == "VIEW_3D"

    def execute(self, context):
        cursor = bpy.context.scene.cursor
        mx = cursor.matrix
        # rotate cursor using maxtrix
        match self.rotation_axis:
            case 'X':
                if self.reverse:
                    cursor.matrix = mx @ mathutils.Matrix.Rotation(math.radians(-self.angle), 4, 'X')
                else:
                    cursor.matrix = mx @ mathutils.Matrix.Rotation(math.radians(self.angle), 4, 'X')
            case 'Y':
                if self.reverse:
                    cursor.matrix = mx @ mathutils.Matrix.Rotation(math.radians(-self.angle), 4, 'Y')
                else:
                    cursor.matrix = mx @ mathutils.Matrix.Rotation(math.radians(self.angle), 4, 'Y')
            case 'Z':
                if self.reverse:
                    cursor.matrix = mx @ mathutils.Matrix.Rotation(math.radians(-self.angle), 4, 'Z')
                else:
                    cursor.matrix = mx @ mathutils.Matrix.Rotation(math.radians(self.angle), 4, 'Z')
        # Report
        self.report({'INFO'}, f'Cursor rotated {self.angle} around {self.rotation_axis} axis')
        return {'FINISHED'}





