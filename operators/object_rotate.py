import bpy
import bmesh
import math
from mathutils import Matrix, Vector
from bpy.props import BoolProperty

AXIS_INDEX = {"X": 0, "Y": 1, "Z": 2}


def world_axis(context, space, axis, obj_world=None):
    """Unit vector of the requested axis in world space."""
    i = AXIS_INDEX[axis]
    if space == "GLOBAL":
        v = Vector((0.0, 0.0, 0.0))
        v[i] = 1.0
        return v
    if space == "CURSOR":
        return context.scene.cursor.matrix.to_3x3().col[i].normalized()
    if space == "VIEW":
        rv3d = context.region_data or context.space_data.region_3d
        return rv3d.view_matrix.inverted().to_3x3().col[i].normalized()
    # LOCAL
    return obj_world.to_3x3().col[i].normalized()


def snap_euler(euler, step):
    """Round every channel of an Euler to the nearest multiple of step (degrees)."""
    if step <= 0.0:
        return euler
    s = math.radians(step)
    for k in range(3):
        euler[k] = round(euler[k] / s) * s
    return euler


def snap_rotation(obj, step):
    mode = obj.rotation_mode
    if mode == "QUATERNION":
        e = snap_euler(obj.rotation_quaternion.to_euler("XYZ"), step)
        obj.rotation_quaternion = e.to_quaternion()
    elif mode == "AXIS_ANGLE":
        aa = obj.rotation_axis_angle
        q = Matrix.Rotation(aa[0], 3, Vector(aa[1:])).to_quaternion()
        e = snap_euler(q.to_euler("XYZ"), step)
        ax, ang = e.to_quaternion().to_axis_angle()
        obj.rotation_axis_angle = (ang, *ax)
    else:
        obj.rotation_euler = snap_euler(obj.rotation_euler.copy(), step)


def is_locked(obj, space, axis):
    if space == "LOCAL":
        return obj.lock_rotation[AXIS_INDEX[axis]]
    return any(obj.lock_rotation)


def rotate_object(context, obj, angle, axis, space):
    """Rotate an object around its own origin, axis taken in the given space."""
    if space == "LOCAL":
        # Right-multiplying matrix_basis keeps the result independent of
        # parenting, parent inverse and the object's rotation mode.
        obj.matrix_basis = obj.matrix_basis @ Matrix.Rotation(math.radians(angle), 4, axis)
        return
    w = obj.matrix_world
    ax = world_axis(context, space, axis)
    pivot = w.translation.copy()
    r = Matrix.Translation(pivot) @ Matrix.Rotation(math.radians(angle), 4, ax) @ Matrix.Translation(-pivot)
    obj.matrix_world = r @ w


def rotate_cursor(context, angle, axis, space):
    """Rotate the 3D cursor in place, axis taken in the given space."""
    cursor = context.scene.cursor
    if space in ("LOCAL", "CURSOR"):
        cursor.matrix = cursor.matrix @ Matrix.Rotation(math.radians(angle), 4, axis)
        return
    ax = world_axis(context, space, axis)
    pivot = cursor.location.copy()
    r = Matrix.Translation(pivot) @ Matrix.Rotation(math.radians(angle), 4, ax) @ Matrix.Translation(-pivot)
    cursor.matrix = r @ cursor.matrix


def edit_pivot(context, obj, bm, verts):
    """Pivot in object local space, following the viewport pivot point setting."""
    pivot_mode = context.scene.tool_settings.transform_pivot_point
    if pivot_mode == "CURSOR":
        return obj.matrix_world.inverted() @ context.scene.cursor.location
    if pivot_mode == "ACTIVE_ELEMENT":
        active = bm.select_history.active
        if active is not None:
            if isinstance(active, bmesh.types.BMVert):
                return active.co.copy()
            return sum((v.co for v in active.verts), Vector()) / len(active.verts)
    return sum((v.co for v in verts), Vector()) / len(verts)


def rotate_edit_mesh(context, obj, angle, axis, space):
    """Rotate the selected vertices of an edit-mode mesh. Returns vertex count."""
    bm = bmesh.from_edit_mesh(obj.data)
    verts = [v for v in bm.verts if v.select]
    if not verts:
        return 0
    m3 = obj.matrix_world.to_3x3()
    ax_world = world_axis(context, space, axis, obj.matrix_world)
    # World-space rotation expressed in object space; exact even with
    # non-uniform scale (gives the matching affine transform).
    r_local = m3.inverted() @ Matrix.Rotation(math.radians(angle), 3, ax_world) @ m3
    pivot = edit_pivot(context, obj, bm, verts)
    for v in verts:
        v.co = pivot + r_local @ (v.co - pivot)
    bmesh.update_edit_mesh(obj.data)
    obj.data.update_tag()
    return len(verts)


def _parents(obj):
    p = obj.parent
    while p is not None:
        yield p
        p = p.parent


class IOPS_OT_object_rotate_base(bpy.types.Operator):
    """Rotate object around an axis by a fixed step"""

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
        if context.area is None or context.area.type != "VIEW_3D":
            return False
        if context.mode not in ("OBJECT", "EDIT_MESH"):
            return False
        if context.window_manager.IOPS_AddonProperties.iops_rotate_cursor_only:
            return True
        if context.mode == "EDIT_MESH":
            return True
        return len(context.view_layer.objects.selected) != 0

    def execute(self, context):
        props = context.window_manager.IOPS_AddonProperties
        angle = props.iops_rotation_angle * self.sign
        space = props.iops_rotate_space
        label = f"{'+' if self.sign > 0 else '-'}{self.axis} ({space.title()})"

        if props.iops_rotate_cursor_only:
            if props.iops_rotate_snap:
                context.scene.cursor.rotation_euler = snap_euler(
                    context.scene.cursor.matrix.to_euler("XYZ"), props.iops_rotation_angle
                )
            rotate_cursor(context, angle, self.axis, space)
            self.report({"INFO"}, f"IOPS Rotate Cursor {label}")
            return {"FINISHED"}

        if context.mode == "EDIT_MESH":
            count = 0
            for obj in context.objects_in_mode_unique_data:
                count += rotate_edit_mesh(context, obj, angle, self.axis, space)
            if count == 0:
                self.report({"WARNING"}, "Nothing selected")
                return {"CANCELLED"}
            self.report({"INFO"}, f"IOPS Rotate {label}: {count} verts")
            return {"FINISHED"}

        if self.per_object:
            targets = list(context.view_layer.objects.selected)
        else:
            targets = [context.view_layer.objects.active]
        targets = [o for o in targets if o is not None]
        if props.iops_rotate_skip_children:
            selected = set(targets)
            targets = [o for o in targets if not any(p in selected for p in _parents(o))]
        skipped = []
        if props.iops_rotate_respect_locks:
            skipped = [o for o in targets if is_locked(o, space, self.axis)]
            targets = [o for o in targets if o not in skipped]

        for obj in targets:
            if props.iops_rotate_snap:
                snap_rotation(obj, props.iops_rotation_angle)
            rotate_object(context, obj, angle, self.axis, space)

        msg = f"IOPS Rotate {label}"
        if skipped:
            msg += f", {len(skipped)} locked skipped"
        self.report({"INFO"}, msg)
        return {"FINISHED"}

    def draw(self, context):
        props = context.window_manager.IOPS_AddonProperties
        layout = self.layout
        col = layout.column(align=True)
        col.prop(props, "iops_rotate_space")
        col.prop(props, "iops_rotation_angle")
        col.separator()
        row = col.row(align=True)
        row.prop(self, "per_object")
        row.prop(props, "iops_rotate_skip_children")
        row = col.row(align=True)
        row.prop(props, "iops_rotate_snap")
        row.prop(props, "iops_rotate_respect_locks")
        col.prop(props, "iops_rotate_cursor_only")


def _make(suffix, axis, sign):
    name = f"IOPS_OT_object_rotate_{suffix}"
    word = "Positive" if sign > 0 else "Negative"
    return type(
        name,
        (IOPS_OT_object_rotate_base,),
        {
            "__doc__": f"Rotate object around {axis}-axis by the rotation angle ({word})",
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
