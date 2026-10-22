"""Instance Collection Edit In Place: edit a local collection's objects
where one of its instancer Empties stands.

Start snapshots everything it is about to touch into
``Scene.iops_instance_edit`` *before* any mutation, then makes the
source collection visible, hides every instancer that would show the
edited content twice (including instancers of ancestor collections) and
moves the collection's root objects onto the instancer through the edit
frame ``A = M_instance @ Translation(-instance_offset)``. Children are
never touched; they follow their parent.

Mutation order is fixed: layer/collection visibility, object visibility,
instancers hidden, transforms, active layer collection + selection.
"""
import bpy
import mathutils
import numpy as np

from ..utils.instance_edit_core import edit_frame, split_roots, warnings
from .assets_management import _is_collection_instance
from .instance_edit_state import (
    active_session,
    find_layer_collection,
    get_frame,
    layer_collection_by_path,
    layer_collection_path,
    push_session,
    resolve_collection,
    resolve_object,
    session_active,
    set_basis,
    set_frame,
)

_TRANSFORM_PATHS = ("location", "rotation", "scale", "delta_")


def collect_targets(coll):
    """Every object of the collection and its child collections, once, stable order."""
    return list(dict.fromkeys(coll.all_objects))


def instancers_of(scene, coll):
    """Scene objects instancing ``coll`` or any collection that contains it."""
    out = []
    for obj in scene.objects:
        if obj.instance_type != "COLLECTION":
            continue
        inst = obj.instance_collection
        if inst is None:
            continue
        if inst == coll or coll in inst.children_recursive:
            out.append(obj)
    return out


def can_start(context):
    """Global Constraints poll of Start: (ok, reason)."""
    scene = context.scene
    if scene is None:
        return False, "No scene"
    if session_active(scene):
        return False, "Instance edit in progress: Stop or Restore first"
    if context.mode != "OBJECT":
        return False, "Switch to Object Mode"
    obj = context.view_layer.objects.active if context.view_layer else None
    if not _is_collection_instance(obj):
        return False, "Active object is not a collection instance"
    coll = obj.instance_collection
    if coll.library is not None:
        return False, "Instanced collection is linked from a library"
    linked = next((o for o in coll.all_objects if o.library is not None), None)
    if linked is not None:
        return False, f"Object '{linked.name}' is linked from a library"
    return True, ""


def _in_view_layer(view_layer, obj):
    return view_layer.objects.get(obj.name) == obj


def _safe_hide_get(view_layer, obj):
    if not _in_view_layer(view_layer, obj):
        return False
    try:
        return obj.hide_get(view_layer=view_layer)
    except RuntimeError:
        return False


def _scene_ancestors(scene, coll):
    """Collections of the scene tree that contain ``coll`` (any depth),
    excluding the scene's master collection."""
    in_scene = set(scene.collection.children_recursive)
    out, frontier = [], [coll]
    while frontier:
        child = frontier.pop()
        for parent in bpy.data.collections:
            if parent in in_scene and parent not in out and child in parent.children.values():
                out.append(parent)
                frontier.append(parent)
    return out


def _layer_colls_of(root, coll):
    """Every LayerCollection of ``coll`` under ``root`` plus all their
    descendants, parents before children."""
    out = []

    def add_subtree(lc):
        out.append(lc)
        for ch in lc.children:
            add_subtree(ch)

    def walk(lc):
        if lc.collection == coll:
            add_subtree(lc)
            return
        for ch in lc.children:
            walk(ch)

    walk(root)
    return out


def _has_transform_anim(obj):
    ad = obj.animation_data
    if ad is None:
        return False
    if ad.action is not None:
        return True
    return any(d.data_path.startswith(_TRANSFORM_PATHS) for d in ad.drivers)


def write_snapshot(context, session, instancer, coll, targets, root_names, frame):
    """Record everything Start is about to change. Mutates nothing but ``session``."""
    scene = context.scene
    view_layer = context.view_layer
    root_lc = view_layer.layer_collection

    session.kind = "LOCAL"
    session.instancer = instancer
    session.instancer_name = instancer.name
    session.collection = coll
    session.collection_name = coll.name
    set_frame(session, frame)
    session.linked_to_scene = coll not in scene.collection.children_recursive
    session.prev_active_layer_path = layer_collection_path(
        root_lc, view_layer.active_layer_collection
    )

    roots = set(root_names)
    for obj in targets:
        row = session.objects.add()
        row.ref = obj
        row.name = obj.name
        row.is_root = obj.name in roots
        set_basis(row, obj.matrix_basis)
        row.hide_get = _safe_hide_get(view_layer, obj)
        row.hide_viewport = obj.hide_viewport

    for obj in instancers_of(scene, coll):
        if not _in_view_layer(view_layer, obj):
            continue  # nothing to hide in this view layer
        row = session.instancers.add()
        row.ref = obj
        row.name = obj.name
        row.hide_get = _safe_hide_get(view_layer, obj)

    # A collection Start has to link under the scene root has no layer
    # collections yet; fresh ones are visible and vanish again on unlink.
    seen_paths = set()
    for lc in _layer_colls_of(root_lc, coll):
        path = layer_collection_path(root_lc, lc)
        if not path or path in seen_paths:
            continue
        seen_paths.add(path)
        row = session.layer_colls.add()
        row.path = path
        row.exclude = lc.exclude
        row.hide_viewport = lc.hide_viewport

    colls = list(dict.fromkeys([coll, *_scene_ancestors(scene, coll), *coll.children_recursive]))
    for c in colls:
        row = session.colls.add()
        row.ref = c
        row.name = c.name
        row.hide_viewport = c.hide_viewport


def apply_edit_state(context, session):
    """Mutation half of Start, driven by the snapshot. Returns the names of
    objects that could not be hidden/unhidden or selected (not in the view
    layer); they are still moved."""
    scene = context.scene
    view_layer = context.view_layer
    root_lc = view_layer.layer_collection
    coll = session.collection or bpy.data.collections.get(session.collection_name)
    skipped = []

    # 1. Layer / collection visibility.
    if session.linked_to_scene and coll not in scene.collection.children_recursive:
        scene.collection.children.link(coll)
    for row in session.layer_colls:
        lc = layer_collection_by_path(root_lc, row.path)
        if lc is None:
            continue
        lc.exclude = False
        lc.hide_viewport = False
    for row in session.colls:
        c = resolve_collection(row)
        if c is not None:
            c.hide_viewport = False

    # 2. Object visibility.
    targets = [(row, resolve_object(row)) for row in session.objects]
    for row, obj in targets:
        if obj is None:
            continue
        obj.hide_viewport = False
        try:
            obj.hide_set(False, view_layer=view_layer)
        except RuntimeError:
            skipped.append(obj.name)

    # 3. Instancers hidden.
    for row in session.instancers:
        obj = resolve_object(row)
        if obj is None:
            continue
        try:
            obj.hide_set(True, view_layer=view_layer)
        except RuntimeError:
            skipped.append(obj.name)

    # 4. Transforms: roots only, through matrix_world (honours outside parents).
    view_layer.update()
    frame = mathutils.Matrix(get_frame(session).tolist())
    roots = []
    for row, obj in targets:
        if obj is None or not row.is_root:
            continue
        obj.matrix_world = frame @ obj.matrix_world
        roots.append(obj)
    view_layer.update()

    # 5. Active layer collection + selection.
    lc = find_layer_collection(root_lc, coll)
    if lc is not None:
        view_layer.active_layer_collection = lc
    for obj in list(view_layer.objects):
        if obj.select_get(view_layer=view_layer):
            obj.select_set(False, view_layer=view_layer)
    for row, obj in targets:
        if obj is None:
            continue
        try:
            obj.select_set(True, view_layer=view_layer)
        except RuntimeError:
            if obj.name not in skipped:
                skipped.append(obj.name)
    active = next((o for o in roots if _in_view_layer(view_layer, o)), None)
    if active is not None:
        view_layer.objects.active = active

    return skipped


class IOPS_OT_instance_edit_start(bpy.types.Operator):
    """Edit the instanced collection's objects in place, at this instancer.
    Objects shared with other collections move there too until Stop/Restore"""

    bl_idname = "iops.instance_edit_start"
    bl_label = "Edit Instance"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        ok, reason = can_start(context)
        if not ok:
            cls.poll_message_set(reason)
        return ok

    def execute(self, context):
        scene = context.scene
        instancer = context.view_layer.objects.active
        coll = instancer.instance_collection

        # instance_offset lives on the Collection (Object has none).
        frame = edit_frame(np.array(instancer.matrix_world), tuple(coll.instance_offset))
        targets = collect_targets(coll)
        names = [o.name for o in targets]
        parent_of = {o.name: o.parent.name for o in targets if o.parent is not None}
        root_names, _children = split_roots(names, parent_of)

        by_name = {o.name: o for o in targets}
        lines = warnings([
            {
                "name": n,
                "has_transform_anim": _has_transform_anim(by_name[n]),
                "has_transform_constraint": len(by_name[n].constraints) > 0,
            }
            for n in root_names
        ])
        if lines:
            self.report({"WARNING"}, "\n".join(lines))

        session = push_session(scene)
        write_snapshot(context, session, instancer, coll, targets, root_names, frame)
        try:
            skipped = apply_edit_state(context, active_session(scene))
        except Exception:
            # rollback wired to restore_session in Task 4
            raise

        if skipped:
            self.report(
                {"WARNING"},
                "Not in the view layer (moved, not shown/selected): " + ", ".join(skipped),
            )
        return {"FINISHED"}
