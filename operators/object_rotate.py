import bpy
import math
from mathutils import Matrix
from bpy.props import BoolProperty


def rotate_local(obj, angle, axis):
    """Rotate an object around its own local axis at its own origin.

    Right-multiplying matrix_basis keeps the result independent of parenting,
    parent inverse and the object's rotation mode.
    """
    obj.matrix_basis = obj.matrix_basis @ Matrix.Rotation(math.radians(angle), 4, axis)


def rotate_cursor(angle, axis):
    """Rotate the 3D cursor around its own local axis, objects untouched."""
    cursor = bpy.context.scene.cursor
    cursor.matrix = cursor.matrix @ Matrix.Rotation(math.radians(angle), 4, axis)


class IOPS_OT_object_rotate_base(bpy.types.Operator):
    """Rotate object around its local axis by a fixed step"""

    bl_options = {"REGISTER", "UNDO"}
    is_bindable = True

    axis = "Z"
    sign = 1

    per_object: BoolProperty(
        name="Per Object",
        description="Rotate every selected object (on) or only the active one (off)",
        default=True,
    )

    @classmethod
    def poll(cls, context):
        return (
            context.area.type == "VIEW_3D"
            and context.mode == "OBJECT"
            and (
                context.window_manager.IOPS_AddonProperties.iops_rotate_cursor_only
                or len(context.view_layer.objects.selected) != 0
            )
        )

    def execute(self, context):
        props = context.window_manager.IOPS_AddonProperties
        angle = props.iops_rotation_angle * self.sign
        label = f"{'+' if self.sign > 0 else '-'}{self.axis}"

        if props.iops_rotate_cursor_only:
            rotate_cursor(angle, self.axis)
            self.report({"INFO"}, f"IOPS Rotate Cursor {label}")
            return {"FINISHED"}

        if self.per_object:
            targets = list(context.view_layer.objects.selected)
        else:
            targets = [context.view_layer.objects.active]
        for obj in targets:
            if obj is not None:
                rotate_local(obj, angle, self.axis)

        self.report({"INFO"}, f"IOPS Rotate {label}")
        return {"FINISHED"}

    def draw(self, context):
        props = context.window_manager.IOPS_AddonProperties
        layout = self.layout
        col = layout.column(align=True)
        col.prop(self, "per_object")
        col.prop(props, "iops_rotation_angle")
        col.prop(props, "iops_rotate_cursor_only")


def _make(suffix, axis, sign):
    name = f"IOPS_OT_object_rotate_{suffix}"
    word = "Positive" if sign > 0 else "Negative"
    return type(
        name,
        (IOPS_OT_object_rotate_base,),
        {
            "__doc__": f"Rotate object around local {axis}-axis by the rotation angle ({word})",
            "bl_idname": f"iops.object_rotate_{suffix.lower()}",
            "bl_label": f"IOPS rotate {axis}-axis - {word}",
            "axis": axis,
            "sign": sign,
            "__annotations__": dict(IOPS_OT_object_rotate_base.__annotations__),
        },
    )


IOPS_OT_object_rotate_X = _make("X", "X", 1)
IOPS_OT_object_rotate_MX = _make("MX", "X", -1)
IOPS_OT_object_rotate_Y = _make("Y", "Y", 1)
IOPS_OT_object_rotate_MY = _make("MY", "Y", -1)
IOPS_OT_object_rotate_Z = _make("Z", "Z", 1)
IOPS_OT_object_rotate_MZ = _make("MZ", "Z", -1)
