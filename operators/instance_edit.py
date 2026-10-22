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

Stop keeps every edit and moves the collection's current roots back
through ``inverse(A)``; Restore rewinds every snapshot object to its
recorded ``matrix_basis``. Both then share ``restore_visibility``.
"""
import bpy
import mathutils
import numpy as np

from ..utils.instance_edit_core import (
    edit_frame,
    plan_restore,
    split_roots,
    unmoved,
    warnings,
)
from .assets_management import _is_collection_instance
from .instance_edit_state import (
    active_session,
    find_layer_collection,
    get_basis,
    get_frame,
    layer_collection_by_path,
    layer_collection_path,
    pop_session,
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


def root_names_of(targets):
    """Names of the targets no other target is an ancestor of. Parent chains
    are followed through outside objects: a target reached through an
    outside object from another target follows it."""
    parent_of = {}
    for o in targets:
        while o is not None and o.name not in parent_of:
            parent_of[o.name] = o.parent.name if o.parent is not None else None
            o = o.parent
    roots, _children = split_roots([o.name for o in targets], parent_of)
    return roots


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
    """For every LayerCollection of ``coll`` under ``root``: its ancestors
    below ``root`` (top-down), then it and all its descendants, parents
    before children. May repeat shared ancestors; callers dedupe by path."""
    out = []

    def add_subtree(lc):
        out.append(lc)
        for ch in lc.children:
            add_subtree(ch)

    def walk(lc, ancestors):
        if lc.collection == coll:
            out.extend(ancestors)
            add_subtree(lc)
            return
        for ch in lc.children:
            walk(ch, ancestors + [lc] if lc != root else ancestors)

    walk(root, [])
    return out


def _is_ancestor_layer_coll(lc, coll):
    return lc.collection != coll and coll in lc.collection.children_recursive


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
    # Ancestor layer collections are recorded too (real exclude value) since
    # their hide_viewport hides the content; only that flag gets cleared.
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
    """Mutation half of Start, driven by the snapshot. Returns
    ``(targets, instancers)``: names of target objects that could not be
    unhidden or selected (they are still moved) and of instancers that
    could not be hidden, because they are not in the view layer."""
    scene = context.scene
    view_layer = context.view_layer
    root_lc = view_layer.layer_collection
    coll = session.collection or bpy.data.collections.get(session.collection_name)
    skipped, skipped_inst = [], []

    # 1. Layer / collection visibility.
    if session.linked_to_scene and coll not in scene.collection.children_recursive:
        scene.collection.children.link(coll)
    for row in session.layer_colls:
        lc = layer_collection_by_path(root_lc, row.path)
        if lc is None:
            continue
        if not _is_ancestor_layer_coll(lc, coll):
            # An excluded ancestor is mirrored onto this exclude; clearing the
            # ancestor's own exclude would reveal every sibling as well.
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
            skipped_inst.append(obj.name)

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

    return skipped, skipped_inst


def _alive(row):
    """The row's object, or None when it was deleted. An object the user
    deleted while the snapshot pointer kept it in ``bpy.data`` is in no
    collection any more and counts as deleted too."""
    obj = resolve_object(row)
    if obj is None or len(obj.users_collection) == 0:
        return None
    return obj


def _alive_rows(rows):
    """(rows whose object is alive, names of the missing ones)."""
    rows = list(rows)
    alive = {r.name for r in rows if _alive(r) is not None}
    return plan_restore(rows, alive)


def _ensure_object_mode(context):
    if context.mode != "OBJECT" and context.active_object is not None:
        bpy.ops.object.mode_set(mode="OBJECT")


def _session_collection(session):
    return session.collection or bpy.data.collections.get(session.collection_name)


def restore_visibility(context, session):
    """Put back everything Start's visibility half changed: object and
    instancer visibility, layer collections, collections, the active layer
    collection, and the scene-root link Start added. Returns the names of
    snapshot objects and instancers that no longer exist."""
    scene = context.scene
    view_layer = context.view_layer
    root_lc = view_layer.layer_collection
    coll = _session_collection(session)

    # Objects first, while their layer collections still include them.
    rows, missing = _alive_rows(session.objects)
    for row in rows:
        obj = _alive(row)
        obj.hide_viewport = row.hide_viewport
        try:
            obj.hide_set(row.hide_get, view_layer=view_layer)
        except RuntimeError:
            pass  # not in this view layer: nothing to restore there
    inst_rows, inst_missing = _alive_rows(session.instancers)
    missing += inst_missing
    for row in inst_rows:
        try:
            _alive(row).hide_set(row.hide_get, view_layer=view_layer)
        except RuntimeError:
            pass

    # Children first: excluding a parent propagates down, and a child
    # excluded before its parent comes back excluded when the parent does.
    # Unchanged exclude flags (untouched ancestors) are not re-set.
    for row in reversed(list(session.layer_colls)):
        lc = layer_collection_by_path(root_lc, row.path)
        if lc is None:
            continue
        if lc.exclude != row.exclude:
            lc.exclude = row.exclude
        lc.hide_viewport = row.hide_viewport
    for row in session.colls:
        c = resolve_collection(row)
        if c is not None:
            c.hide_viewport = row.hide_viewport

    lc = layer_collection_by_path(root_lc, session.prev_active_layer_path)
    if lc is not None:
        view_layer.active_layer_collection = lc
    if (
        session.linked_to_scene
        and coll is not None
        and coll in scene.collection.children.values()
    ):
        scene.collection.children.unlink(coll)
    view_layer.update()
    return missing


def restore_session(context, session):
    """Restore: rewind every snapshot object to its recorded matrix_basis,
    then restore visibility and drop the session. The session is popped
    only after everything before it ran, so a failure leaves it in place."""
    _ensure_object_mode(context)
    rows, _missing = _alive_rows(session.objects)
    for row in rows:
        _alive(row).matrix_basis = get_basis(row)
    missing = restore_visibility(context, session)
    pop_session(context.scene)
    return missing


def stop_session(context, session):
    """Stop: keep every edit. Every current root of the collection goes back
    to the collection's native frame through inverse(frame); then
    visibility is restored, the session dropped and the instancer selected."""
    _ensure_object_mode(context)
    view_layer = context.view_layer
    view_layer.update()
    coll = _session_collection(session)
    missing = []
    if coll is None:
        missing.append(session.collection_name)
    else:
        frame = get_frame(session)
        targets = collect_targets(coll)
        roots = set(root_names_of(targets))
        for obj in targets:
            if obj.name in roots:
                obj.matrix_world = mathutils.Matrix(
                    unmoved(frame, np.array(obj.matrix_world)).tolist()
                )
    instancer = session.instancer or bpy.data.objects.get(session.instancer_name)
    missing += restore_visibility(context, session)
    pop_session(context.scene)

    if instancer is not None and _in_view_layer(view_layer, instancer):
        for obj in list(view_layer.objects):
            if obj.select_get(view_layer=view_layer):
                obj.select_set(False, view_layer=view_layer)
        try:
            instancer.select_set(True, view_layer=view_layer)
        except RuntimeError:
            pass
        view_layer.objects.active = instancer
    return missing


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
        root_names = root_names_of(targets)

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

        depth = len(scene.iops_instance_edit.sessions)
        mutating = False
        try:
            session = push_session(scene)
            write_snapshot(context, session, instancer, coll, targets, root_names, frame)
            mutating = True
            skipped, skipped_inst = apply_edit_state(context, active_session(scene))
        except Exception:
            if not mutating:
                # Nothing touched yet: drop the half-written session.
                if len(scene.iops_instance_edit.sessions) > depth:
                    pop_session(scene)
            else:
                # Half-applied: put the scene back from the snapshot.
                restore_session(context, active_session(scene))
            raise

        if skipped:
            self.report(
                {"WARNING"},
                "Not in the view layer (moved, not shown/selected): " + ", ".join(skipped),
            )
        if skipped_inst:
            self.report(
                {"WARNING"},
                "Instancers not in the view layer (not hidden): " + ", ".join(skipped_inst),
            )
        return {"FINISHED"}


class _SessionOperator:
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        if context.scene is None or not session_active(context.scene):
            cls.poll_message_set("No instance edit in progress")
            return False
        return True

    def _finish(self, missing):
        if missing:
            self.report({"WARNING"}, "Missing: " + ", ".join(missing))
        return {"FINISHED"}


class IOPS_OT_instance_edit_restore(_SessionOperator, bpy.types.Operator):
    bl_idname = "iops.instance_edit_restore"
    bl_label = "Restore Instance Edit"
    bl_description = (
        "Put every object of the edited collection back where it was when "
        "editing started, discarding transform edits made since; geometry, "
        "modifier and material edits stay"
    )

    def execute(self, context):
        return self._finish(restore_session(context, active_session(context.scene)))


class IOPS_OT_instance_edit_stop(_SessionOperator, bpy.types.Operator):
    """Finish editing and keep every edit, transforms included: the collection
    goes back to its own place and every instance shows the result"""

    bl_idname = "iops.instance_edit_stop"
    bl_label = "Stop Instance Edit"

    def execute(self, context):
        return self._finish(stop_session(context, active_session(context.scene)))
