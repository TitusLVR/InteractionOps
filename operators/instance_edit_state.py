"""Scene-stored session stack for Instance Collection Edit In Place."""
import bpy
import mathutils
import numpy as np

from ..utils.instance_edit_core import (
    from_flat,
    layer_path,
    split_layer_path,
    to_flat,
)

_IDENTITY_FLAT = [1.0, 0.0, 0.0, 0.0,
                  0.0, 1.0, 0.0, 0.0,
                  0.0, 0.0, 1.0, 0.0,
                  0.0, 0.0, 0.0, 1.0]


class IOPS_IE_ObjRef(bpy.types.PropertyGroup):
    ref: bpy.props.PointerProperty(type=bpy.types.Object)
    name: bpy.props.StringProperty()
    is_root: bpy.props.BoolProperty()
    # Pre-Start matrix_basis (report/debug) and, for roots, the post-Start one:
    # Stop writes the snapshot channels back when the basis is still this.
    basis: bpy.props.FloatVectorProperty(size=16, default=_IDENTITY_FLAT)
    edit_basis: bpy.props.FloatVectorProperty(size=16, default=_IDENTITY_FLAT)
    # Transform channels, written back verbatim (same float32 storage as
    # the Object, so a round trip is bit-exact).
    location: bpy.props.FloatVectorProperty(size=3)
    rotation_mode: bpy.props.StringProperty(default="XYZ")
    rotation_euler: bpy.props.FloatVectorProperty(size=3)
    rotation_quaternion: bpy.props.FloatVectorProperty(size=4, default=(1.0, 0.0, 0.0, 0.0))
    rotation_axis_angle: bpy.props.FloatVectorProperty(size=4, default=(0.0, 0.0, 1.0, 0.0))
    scale: bpy.props.FloatVectorProperty(size=3, default=(1.0, 1.0, 1.0))
    # Parent relation, restored before the channels.
    parent: bpy.props.PointerProperty(type=bpy.types.Object)
    parent_type: bpy.props.StringProperty(default="OBJECT")
    parent_bone: bpy.props.StringProperty()
    matrix_parent_inverse: bpy.props.FloatVectorProperty(size=16, default=_IDENTITY_FLAT)
    hide_get: bpy.props.BoolProperty()
    hide_viewport: bpy.props.BoolProperty()
    hide_select: bpy.props.BoolProperty()


class IOPS_IE_InstRef(bpy.types.PropertyGroup):
    ref: bpy.props.PointerProperty(type=bpy.types.Object)
    name: bpy.props.StringProperty()
    hide_get: bpy.props.BoolProperty()


class IOPS_IE_LayerRef(bpy.types.PropertyGroup):
    path: bpy.props.StringProperty()
    # Fallback when a rename mid-session broke the path.
    ref: bpy.props.PointerProperty(type=bpy.types.Collection)
    exclude: bpy.props.BoolProperty()
    hide_viewport: bpy.props.BoolProperty()


class IOPS_IE_CollRef(bpy.types.PropertyGroup):
    ref: bpy.props.PointerProperty(type=bpy.types.Collection)
    name: bpy.props.StringProperty()
    hide_viewport: bpy.props.BoolProperty()
    hide_select: bpy.props.BoolProperty()


class IOPS_IE_Session(bpy.types.PropertyGroup):
    kind: bpy.props.EnumProperty(
        items=[("LOCAL", "Local", ""), ("LINKED", "Linked", "")],
        default="LOCAL",
    )
    instancer: bpy.props.PointerProperty(type=bpy.types.Object)
    instancer_name: bpy.props.StringProperty()
    collection: bpy.props.PointerProperty(type=bpy.types.Collection)
    collection_name: bpy.props.StringProperty()
    frame: bpy.props.FloatVectorProperty(size=16, default=_IDENTITY_FLAT)
    view_layer_name: bpy.props.StringProperty()
    linked_to_scene: bpy.props.BoolProperty()
    prev_active_layer_path: bpy.props.StringProperty()
    objects: bpy.props.CollectionProperty(type=IOPS_IE_ObjRef)
    instancers: bpy.props.CollectionProperty(type=IOPS_IE_InstRef)
    layer_colls: bpy.props.CollectionProperty(type=IOPS_IE_LayerRef)
    colls: bpy.props.CollectionProperty(type=IOPS_IE_CollRef)


class IOPS_IE_Stack(bpy.types.PropertyGroup):
    sessions: bpy.props.CollectionProperty(type=IOPS_IE_Session)


# Row types first (CollectionProperty targets), then their containers.
CLASSES = (
    IOPS_IE_ObjRef,
    IOPS_IE_InstRef,
    IOPS_IE_LayerRef,
    IOPS_IE_CollRef,
    IOPS_IE_Session,
    IOPS_IE_Stack,
)


def register_props():
    bpy.types.Scene.iops_instance_edit = bpy.props.PointerProperty(
        type=IOPS_IE_Stack
    )


def unregister_props():
    try:
        del bpy.types.Scene.iops_instance_edit
    except AttributeError:
        pass


def session_active(scene):
    return len(scene.iops_instance_edit.sessions) > 0


def active_session(scene):
    sessions = scene.iops_instance_edit.sessions
    return sessions[-1] if len(sessions) else None


def push_session(scene):
    return scene.iops_instance_edit.sessions.add()


def pop_session(scene):
    sessions = scene.iops_instance_edit.sessions
    if len(sessions):
        sessions.remove(len(sessions) - 1)


def resolve_object(row):
    """The row's object, or None when it was deleted. Renames never break
    the pointer, so there is no name fallback: a name match could only be a
    different object that took the name, outside the edited collection."""
    return row.ref


def resolve_collection(row):
    """The row's collection, or None when it was deleted (no name fallback,
    see ``resolve_object``)."""
    return row.ref


def find_layer_collection(root_layer_coll, collection):
    if root_layer_coll.collection == collection:
        return root_layer_coll
    for child in root_layer_coll.children:
        found = find_layer_collection(child, collection)
        if found is not None:
            return found
    return None


def layer_collection_path(root, layer_coll):
    """Names from root down to layer_coll, joined by layer_path."""
    def walk(node, trail):
        trail = trail + [node.name]
        if node == layer_coll:
            return trail
        for child in node.children:
            found = walk(child, trail)
            if found is not None:
                return found
        return None

    names = walk(root, [])
    return layer_path(names) if names is not None else ""


def layer_collection_by_path(root, path):
    names = split_layer_path(path)
    if not names or names[0] != root.name:
        return None
    node = root
    for name in names[1:]:
        node = next((c for c in node.children if c.name == name), None)
        if node is None:
            return None
    return node


def set_frame(session, np_matrix):
    session.frame = to_flat(np_matrix)


def get_frame(session):
    return from_flat(list(session.frame))


def set_basis(row, matrix, attr="basis"):
    """Store a 4x4 matrix row-major in the 16-float property ``attr``."""
    setattr(row, attr, [v for r in matrix for v in r])


def get_basis(row, attr="basis"):
    b = list(getattr(row, attr))
    return mathutils.Matrix([b[0:4], b[4:8], b[8:12], b[12:16]])
