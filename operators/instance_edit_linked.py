"""Instance Edit, phase 2: edit a collection linked from another .blend
where one of its instancer Empties stands, and write it back on Commit.

Start appends the collection from its source file as a local copy
(``<name> [edit]``), records every ID that arrived with it (the owned set)
and places the copy's roots on the instancer through phase 1's edit frame.
Only the instancer is hidden: other instancers keep showing the unchanged
linked data until the library is reloaded after Commit.

Commit exports the copy to a temp blend next to the source (roots moved
back to the collection's native frame and every owned ID tagged, both
undone before the export returns), runs the merge worker in plan mode,
shows the plan, then backs the source up (an ``.iopsbackup`` folder beside
it by default, or the per-user custom backup folder; several points per
source and user) and runs the worker in write mode.
The session is closed only after the worker reported success and the
library was reloaded. Every worker run happens under the source's lock file
with per-run temp names. Cancel closes the session without touching the
source. Rollback copies a chosen backup point (anyone's, from either
location) over the source; Clean Up Backups deletes old points.
"""
import datetime
import getpass
import json
import os
import platform
import re
import shutil
import stat
import subprocess
import time
import uuid
from collections import Counter, namedtuple
from contextlib import contextmanager

import bpy
import mathutils
import numpy as np

from ..utils.instance_edit_core import (
    BACKUP_EXT,
    BACKUP_PART_EXT,
    BACKUP_SIDECAR_EXT,
    BACKUP_SUBFOLDER,
    backup_points,
    commit_temp_paths,
    edit_frame,
    is_similarity,
    lock_path,
    newer_blender,
    parse_point,
    point_name,
    point_number,
    point_stamp,
    point_user,
    prune_backups,
    source_changed,
    source_hash,
    ticked_plan_problem,
    unmoved,
    user_tag,
    warnings,
)
from .assets_management import _is_collection_instance
from .instance_edit import (
    _NOT_SIMILAR,
    _ensure_object_mode,
    _has_transform_anim,
    _in_view_layer,
    _matrices_close,
    _parent_unchanged,
    _record_transform,
    _reveal_active_in_outliners,
    _safe_hide_get,
    _session_view_layer,
    _write_channels,
    collect_targets,
    restore_visibility,
    root_names_of,
)
from .instance_edit_state import (
    active_session,
    find_layer_collection,
    get_basis,
    get_frame,
    layer_collection_by_path,
    layer_collection_path,
    pop_session,
    push_session,
    session_active,
    set_basis,
    set_frame,
    set_source_stat,
    source_stat,
)
from .library.common import get_prefs, worker_creation_flags

_SUFFIX = re.compile(r"^(.*)\.\d{3,}$")
# Collections of bpy.data an append can add to but that are never owned:
# the Library datablocks it creates, and the all-IDs view.
_NOT_OWNED = {"libraries", "all_ids"}


def _norm_path(path):
    return os.path.normcase(os.path.normpath(os.path.abspath(path)))


def library_path(library):
    """Absolute path of a Library datablock's file. Indirect libraries may
    store their path relative to the library that links them."""
    path = bpy.path.abspath(library.filepath)
    if not os.path.isfile(path) and library.parent is not None:
        path = bpy.path.abspath(library.filepath, library=library.parent)
    return os.path.normpath(path)


def _id_attrs():
    """Names of the ``bpy.data`` collections that hold IDs (empty ones too),
    minus the never-owned ones."""
    out = []
    for attr in dir(bpy.data):
        if attr.startswith("_"):
            continue
        try:
            value = getattr(bpy.data, attr)
        except AttributeError:
            continue
        if not isinstance(value, bpy.types.bpy_prop_collection):
            continue
        prop = bpy.data.bl_rna.properties.get(attr)
        fixed = getattr(prop, "fixed_type", None)
        if attr in _NOT_OWNED or (fixed is not None and fixed.identifier == "ID"):
            continue  # all_ids lists every other collection's IDs again
        if len(value) and not isinstance(value[0], bpy.types.ID):
            continue
        out.append(attr)
    return out


def _id_snapshot(attrs):
    return {(attr, i.as_pointer()) for attr in attrs for i in getattr(bpy.data, attr)}


def source_name_of(name, source_names):
    """Name in the source file of an appended ID now called ``name``.

    Appending gives an ID its source name unless a LOCAL ID of that name
    already exists; then Blender adds a ``.NNN`` suffix. The suffix is
    stripped only when the stripped name is one of the source file's names
    of that ID type (``source_names``, from ``data_from``) and ``name``
    itself is not: a source name that really ends in ``.NNN`` is kept.
    """
    if name in source_names:
        return name
    m = _SUFFIX.match(name)
    if m is not None and m.group(1) in source_names:
        return m.group(1)
    return name


# An ID that arrived through the append: ``id_type`` is its ``bpy.data``
# attribute, ``source_name`` its name in the source file.
OwnedID = namedtuple("OwnedID", "id_type id source_name")


def append_collection_copy(source_path, coll_name):
    """Append collection ``coll_name`` from ``source_path`` as a local copy.

    Returns ``(collection, owned)``: ``owned`` lists an ``OwnedID`` for
    every new local ID the append created (the collection, its objects,
    data, materials, nested same-file collections, ...). IDs linked from
    third libraries stay linked and are not owned. The copy is not linked
    into any scene. Session state is not touched.
    """
    attrs = _id_attrs()
    before = _id_snapshot(attrs)
    try:
        with bpy.data.libraries.load(source_path, link=False) as (data_from, data_to):
            if coll_name not in data_from.collections:
                raise KeyError(f"Collection '{coll_name}' not found in {source_path}")
            listing = {a: set(getattr(data_from, a, ())) for a in attrs}
            data_to.collections = [coll_name]
        coll = data_to.collections[0]
        if coll is None:
            raise RuntimeError(f"Could not append '{coll_name}' from {source_path}")
    except Exception:
        # A partial load may still have created local IDs.
        _remove_ids([i for _attr, i in _new_local_ids(attrs, before)])
        raise
    return coll, [
        OwnedID(attr, i, source_name_of(i.name, listing[attr]))
        for attr, i in _new_local_ids(attrs, before)
    ]


def _new_local_ids(attrs, before):
    """``(attr, ID)`` of every local ID not in the ``before`` snapshot."""
    return [
        (attr, i)
        for attr in attrs
        for i in getattr(bpy.data, attr)
        if i.library is None and (attr, i.as_pointer()) not in before
    ]


def _find_linked_collection(source_path, name):
    key = _norm_path(source_path)
    for c in bpy.data.collections:
        lib = c.library
        if lib is not None and c.name == name and _norm_path(library_path(lib)) == key:
            return c
    return None


def _link_collection(source_path, name):
    with bpy.data.libraries.load(source_path, link=True) as (data_from, data_to):
        if name not in data_from.collections:
            raise KeyError(f"Collection '{name}' not found in {source_path}")
        data_to.collections = [name]
    coll = data_to.collections[0]
    if coll is None:
        raise RuntimeError(f"Could not link '{name}' from {source_path}")
    return coll


def _reachable(roots, ids, user_map):
    """IDs of ``ids`` (pointers) reachable from ``roots`` (pointers): an ID
    is reached when one of its users is."""
    reached = set(roots)
    changed = True
    while changed:
        changed = False
        for ptr, id_ in ids.items():
            if ptr in reached:
                continue
            if any(u.as_pointer() in reached for u in user_map.get(id_, ())):
                reached.add(ptr)
                changed = True
    return reached


def unown_nested_same_file(copy_coll, owned, source_path):
    """Point instancers of nested same-file collections back at the links.

    Every collection-instancing Empty of ``copy_coll``'s subtree whose
    collection is an owned copy (and not itself part of the subtree) is
    re-pointed at the linked collection of the same source name from
    ``source_path`` (found in ``bpy.data`` or linked on demand). Owned IDs
    reachable from those copies and no longer reachable from ``copy_coll``
    (``bpy.data.user_map``) are removed. Returns the remaining owned list.
    Session state is not touched.
    """
    by_ptr = {o.id.as_pointer(): o for o in owned}
    own_subtree = {copy_coll.as_pointer()} | {c.as_pointer() for c in copy_coll.children_recursive}
    dropped = []
    for obj in copy_coll.all_objects:
        if obj.type != "EMPTY" or obj.instance_type != "COLLECTION":
            continue
        inst = obj.instance_collection
        if inst is None:
            continue
        ptr = inst.as_pointer()
        rec = by_ptr.get(ptr)
        if rec is None or ptr in own_subtree:
            continue
        linked = _find_linked_collection(source_path, rec.source_name)
        if linked is None:
            linked = _link_collection(source_path, rec.source_name)
        obj.instance_collection = linked
        dropped.append(ptr)
    if not dropped:
        return owned

    ids = {p: o.id for p, o in by_ptr.items()}
    user_map = bpy.data.user_map(subset=list(ids.values()))
    from_dropped = _reachable(dropped, ids, user_map)
    # Users outside the owned set keep an ID too (conservative).
    external = {
        p for p, id_ in ids.items()
        if any(u.as_pointer() not in ids for u in user_map.get(id_, ()))
    }
    alive = _reachable({copy_coll.as_pointer()} | external, ids, user_map)
    dead = [p for p in from_dropped if p not in alive]
    bpy.data.batch_remove([ids[p] for p in dead])
    dead = set(dead)
    return [o for p, o in by_ptr.items() if p not in dead]


def _override_warning(coll):
    for c in bpy.data.collections:
        ov = c.override_library
        if ov is not None and ov.reference == coll:
            return [f"'{c.name}' is a library override of this collection; it may break after Commit reloads the library"]
    return []


def can_start_linked(context):
    """Start poll for an instancer of a library collection: (ok, reason)."""
    scene = context.scene
    if scene is None:
        return False, "No scene"
    if context.mode != "OBJECT":
        return False, "Switch to Object Mode"
    obj = context.view_layer.objects.active if context.view_layer else None
    if not _is_collection_instance(obj):
        return False, "Active object is not a collection instance"
    coll = obj.instance_collection
    if coll.library is None:
        return False, "Instanced collection is not linked from a library"
    path = library_path(coll.library)
    if not os.path.isfile(path):
        return False, f"Library file not found: {path}"
    sessions = scene.iops_instance_edit.sessions
    key = _norm_path(path)
    for s in sessions:
        if s.kind == "LINKED" and s.source_coll_name == coll.name and _norm_path(s.source_path) == key:
            return False, f"'{coll.name}' is already being edited"
    if len(sessions):
        top = sessions[-1]
        if top.kind == "LOCAL":
            c = top.collection
            if c is None or c.all_objects.get(obj.name) != obj:
                return False, "Instance edit in progress: Stop or Restore first"
    if not is_similarity(edit_frame(np.array(obj.matrix_world), tuple(coll.instance_offset))):
        return False, _NOT_SIMILAR
    return True, ""


def _remove_ids(ids):
    seen, out = set(), []
    for id_ in ids:
        if id_ is None:
            continue
        try:
            ptr = id_.as_pointer()
        except ReferenceError:
            continue
        if ptr not in seen:
            seen.add(ptr)
            out.append(id_)
    if out:
        bpy.data.batch_remove(out)


def _discard_copy(context, session, ids=()):
    """Undo a linked Start: unhide the instancer, remove the copy and every
    owned ID (rows and ``ids``), restore the active layer collection, pop."""
    view_layer, _fell_back = _session_view_layer(context, session)
    for row in session.instancers:
        if row.ref is None:
            continue
        try:
            row.ref.hide_set(row.hide_get, view_layer=view_layer)
        except RuntimeError:
            pass
    prev_path = session.prev_active_layer_path
    _remove_ids([session.copy_collection, *(r.ref for r in session.owned), *ids])
    lc = layer_collection_by_path(view_layer.layer_collection, prev_path)
    if lc is not None:
        view_layer.active_layer_collection = lc
    pop_session(context.scene)


def _write_owned_rows(session, owned, root_ptrs):
    for rec in owned:
        row = session.owned.add()
        row.id_type = rec.id_type
        row.source_name = rec.source_name
        row.local_name = rec.id.name
        row.ref = rec.id
        if rec.id_type == "objects":
            row.is_root = rec.id.as_pointer() in root_ptrs
            _record_transform(row, rec.id)


def start_linked(context, instancer):
    """Linked branch of Start. Returns warning lines for the report.

    Nothing is recorded until the append succeeded; a later failure before
    the session is pushed removes the appended IDs, a failure after it
    undoes the whole Start (``_discard_copy``). Either way the exception is
    re-raised."""
    scene = context.scene
    view_layer = context.view_layer
    root_lc = view_layer.layer_collection
    coll = instancer.instance_collection
    lib = coll.library
    source_path = library_path(lib)
    frame = edit_frame(np.array(instancer.matrix_world), tuple(coll.instance_offset))
    if not is_similarity(frame):
        raise ValueError(_NOT_SIMILAR)
    stat = os.stat(source_path)

    copy, owned = append_collection_copy(source_path, coll.name)
    session = None
    try:
        owned = unown_nested_same_file(copy, owned, source_path)
        copy.name = f"{coll.name} [edit]"
        scene.collection.children.link(copy)
        view_layer.update()

        # Objects linked from third libraries stay linked: they cannot be
        # moved, so they are hidden for the session instead. Roots come
        # from local objects only (a linked one may share a local name).
        everything = collect_targets(copy)
        targets = [o for o in everything if o.library is None]
        foreign = [o for o in everything if o.library is not None]
        root_names = set(root_names_of(targets))
        roots = [o for o in targets if o.name in root_names]
        lines = warnings([
            {
                "name": o.name,
                "has_transform_anim": _has_transform_anim(o),
                "has_transform_constraint": len(o.constraints) > 0,
            }
            for o in roots
        ])
        lines += _override_warning(coll)
        if foreign:
            lines.append(
                "Linked objects hidden while editing (cannot be moved): "
                + ", ".join(o.name for o in foreign)
            )
        lines += _read_only_notice(context, source_path)

        session = push_session(scene)
        session.kind = "LINKED"
        # Names this session in the backup sidecar once it committed, so an
        # undo that brings it back cannot commit it a second time.
        session.uuid = uuid.uuid4().hex
        session.instancer = instancer
        session.instancer_name = instancer.name
        # ``collection`` is the copy being edited, ``collection_name`` the
        # source collection's name (what the user opened).
        session.collection = copy
        session.collection_name = coll.name
        set_frame(session, frame)
        session.view_layer_name = view_layer.name
        # The copy is removed (not unlinked) by Cancel/Commit, so
        # restore_visibility must not unlink it.
        session.linked_to_scene = False
        session.prev_active_layer_path = layer_collection_path(
            root_lc, view_layer.active_layer_collection
        )
        session.source_path = source_path
        set_source_stat(session, stat)
        session.source_coll_name = coll.name
        session.library_name = lib.name
        session.copy_collection = copy
        session.copy_collection_name = copy.name
        _write_owned_rows(session, owned, {o.as_pointer() for o in roots})
        # The instancer and the linked objects get hidden; restore_visibility
        # brings every instancers row back.
        for obj in [instancer, *foreign]:
            row = session.instancers.add()
            row.ref = obj
            row.name = obj.name
            row.hide_get = _safe_hide_get(view_layer, obj)

        # Mutations: roots onto the instance, instancer hidden, active
        # layer collection, selection.
        A = mathutils.Matrix(frame.tolist())
        rows = {r.ref.as_pointer(): r for r in session.owned if r.is_root}
        for obj in roots:
            obj.matrix_world = A @ obj.matrix_world
            set_basis(rows[obj.as_pointer()], obj.matrix_basis, "edit_basis")
        view_layer.update()
        for obj in [instancer, *foreign]:
            obj.hide_set(True, view_layer=view_layer)
        lc = find_layer_collection(root_lc, copy)
        if lc is not None:
            view_layer.active_layer_collection = lc
        for obj in list(view_layer.objects):
            if obj.select_get(view_layer=view_layer):
                obj.select_set(False, view_layer=view_layer)
        for obj in targets:
            try:
                obj.select_set(True, view_layer=view_layer)
            except RuntimeError:
                pass  # hidden by its own flags or excluded: still moved
        if roots:
            view_layer.objects.active = roots[0]
            _reveal_active_in_outliners(context)
    except Exception:
        if session is None:
            _remove_ids([copy, *(o.id for o in owned)])
        else:
            _discard_copy(context, session, [copy, *(o.id for o in owned)])
        raise
    return lines


# --- Commit / Cancel / Rollback ------------------------------------------------

TAG = "iops_commit"
INSTANCE_TAG = "iops_commit_instance"
WORKER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "instance_edit_merge_worker.py")
_CHANNELS = ("location", "rotation_euler", "rotation_quaternion", "rotation_axis_angle", "scale")
_PLAN_LINES = (
    ("replaced", "Replaced"),
    ("added", "Added"),
    ("kept", "Kept (the source keeps its version)"),
    ("pulled", "Updated with the ticked ones"),
    ("unlinked", "Removed from the collection"),
    ("deleted", "Deleted from the source"),
)
_MAX_NAMES = 8


class CommitRefused(Exception):
    """Commit cannot export the session as it is; the message says why."""


def _source_key(session):
    return _norm_path(session.source_path)


def _is_source_library(lib, key):
    return lib is not None and _norm_path(library_path(lib)) == key


def _source_libraries(source_path):
    key = _norm_path(source_path)
    return [lib for lib in bpy.data.libraries if _is_source_library(lib, key)]


# ID types a driver may target without the copy owning them: a driver edge
# to one of them is not followed (the ID is recorded, not expanded).
_DRIVER_STOP = (bpy.types.Scene, bpy.types.World, bpy.types.Camera)


def _driver_targets(id_):
    """Pointers of the IDs ``id_``'s drivers read (its own animation data
    and that of its embedded node tree)."""
    out = set()
    owners = [id_, getattr(id_, "node_tree", None)]
    for owner in owners:
        ad = getattr(owner, "animation_data", None)
        if ad is None:
            continue
        for fc in ad.drivers:
            for var in fc.driver.variables:
                for target in var.targets:
                    if target.id is not None:
                        out.add(target.id.as_pointer())
    return out


def _copy_closure(copy):
    """``(local, linked)`` of ``_copy_closure_full``."""
    local, linked, _stopped = _copy_closure_full(copy)
    return local, linked


def _copy_closure_full(copy):
    """What ``libraries.write({copy})`` carries: ``(local, linked,
    stopped)``, the local IDs reachable from ``copy`` through ID references
    (``copy`` included), ``(linked_id, local_user)`` for every linked ID they
    reference (linked IDs are not followed) and the pointers of the local
    IDs reached through a driver only. A Scene, World or Camera reached
    through a driver only is recorded but not followed, so a driver never
    drags a whole scene into the closure."""
    deps = {}
    for id_, users in bpy.data.user_map().items():
        for user in users:
            deps.setdefault(user.as_pointer(), []).append(id_)
    local = {copy.as_pointer(): copy}
    linked = []
    stopped = set()
    frontier = [copy]
    while frontier:
        cur = frontier.pop()
        drivers = None
        for dep in deps.get(cur.as_pointer(), ()):
            if isinstance(dep, bpy.types.Library):
                continue
            if dep.library is not None:
                linked.append((dep, cur))
                continue
            ptr = dep.as_pointer()
            if ptr in local and ptr not in stopped:
                continue
            if isinstance(dep, _DRIVER_STOP):
                if drivers is None:
                    drivers = _driver_targets(cur)
                if ptr in drivers:
                    if ptr not in local:
                        local[ptr] = dep
                        stopped.add(ptr)
                    continue
            if ptr in local:  # reached by a driver before, now for real
                stopped.discard(ptr)
            else:
                local[ptr] = dep
            frontier.append(dep)
    return list(local.values()), linked, stopped


def _instances_source(obj, key):
    inst = getattr(obj, "instance_collection", None)
    return inst is not None and _is_source_library(inst.library, key)


def _refusal(local, linked, key):
    """Why the closure cannot be merged, or None: a Scene in it (a driver
    reads one; the merge would append it into the source), or a
    source-linked ID used other than as an instanced collection (the merge
    appends into the source, where links to the source itself are
    dropped)."""
    if any(isinstance(i, bpy.types.Scene) for i in local):
        return "Drivers in the copy reference a scene; remove them first"
    for dep, user in linked:
        if not _is_source_library(dep.library, key):
            continue  # a third library: stays linked
        if isinstance(user, bpy.types.Object) and user.instance_collection == dep:
            continue  # restored by the worker from INSTANCE_TAG
        return f"Make {dep.name} local first: it is linked from the source file"
    return None


def commit_refusal(session):
    """Why the session cannot be exported (no mutation), or None."""
    copy = session.copy_collection
    if copy is None:
        return f"The edit copy of '{session.source_coll_name}' was deleted: Cancel the session"
    local, linked = _copy_closure(copy)
    return _refusal(local, linked, _source_key(session))


def _strip_tags():
    """Remove both commit tags from every local ID of the file."""
    for attr in _id_attrs():
        for id_ in getattr(bpy.data, attr):
            if id_.library is not None:
                continue
            for tag in (TAG, INSTANCE_TAG):
                try:
                    if tag in id_:
                        del id_[tag]
                except TypeError:
                    break  # this ID type has no custom properties


def _snapshot_channels(obj):
    return (obj.rotation_mode, [tuple(getattr(obj, c)) for c in _CHANNELS])


def _put_channels(obj, snap):
    mode, values = snap
    if obj.rotation_mode != mode:
        obj.rotation_mode = mode
    for channel, value in zip(_CHANNELS, values):
        setattr(obj, channel, value)


def _write_temp_json(temp_json, cfg):
    with open(temp_json, "w", encoding="utf-8") as fh:
        json.dump(cfg, fh, indent=1)


def export_copy(context, session, paths, update_shared=(), expected_plan=None):
    """Write the copy to ``paths.temp_blend`` and the merge config to
    ``paths.temp_json`` (``commit_temp_paths`` of this run, next to the
    source).

    Roots go back to the collection's native frame for the write: a root
    whose parent relation is unchanged and whose basis is still the
    post-Start one gets its recorded channels, every other one moves
    through ``inverse(A)``. Owned IDs are tagged with their row index and
    collection instancers of source collections with the collection's name.
    Afterwards, whatever happened, the tags are stripped from every ID and
    every root gets its exact pre-export channels back. Raises
    ``CommitRefused`` (nothing touched) when the copy cannot be merged."""
    _ensure_object_mode(context)
    copy = session.copy_collection
    if copy is None:
        raise CommitRefused(f"The edit copy of '{session.source_coll_name}' was deleted: Cancel the session")
    key = _source_key(session)
    local, linked = _copy_closure(copy)
    refused = _refusal(local, linked, key)
    if refused:
        raise CommitRefused(refused)
    temp_blend, temp_json = paths.temp_blend, paths.temp_json

    view_layer, _fell_back = _session_view_layer(context, session)
    view_layer.update()
    frame = get_frame(session)
    targets = [o for o in collect_targets(copy) if o.library is None]
    root_names = set(root_names_of(targets))
    roots = [o for o in targets if o.name in root_names]
    rows = {
        r.ref.as_pointer(): r
        for r in session.owned
        if r.id_type == "objects" and r.is_root and r.ref is not None
    }
    saved = [(obj, _snapshot_channels(obj)) for obj in roots]
    # Every matrix is computed before any is written.
    untouched, moves = [], []
    for obj in roots:
        row = rows.get(obj.as_pointer())
        if (
            row is not None
            and _parent_unchanged(obj, row)
            and _matrices_close(obj.matrix_basis, get_basis(row, "edit_basis"))
        ):
            untouched.append((obj, row))
        else:
            world = unmoved(frame, np.array(obj.matrix_world))
            moves.append((obj, mathutils.Matrix(world.tolist())))

    try:
        _strip_tags()  # leftovers of an interrupted export are never reused
        for obj, row in untouched:
            _write_channels(obj, row)
        for obj, world in moves:
            obj.matrix_world = world
        for index, row in enumerate(session.owned):
            if row.ref is not None:
                row.ref[TAG] = index
        for id_ in local:
            if isinstance(id_, bpy.types.Object) and _instances_source(id_, key):
                id_[INSTANCE_TAG] = id_.instance_collection.name
        view_layer.update()
        for path in (temp_blend, temp_json):
            if os.path.exists(path):
                os.remove(path)
        # RELATIVE: relative paths (caches, texts, third libraries) are
        # rebased onto the temp blend's folder, the source's own.
        bpy.data.libraries.write(temp_blend, {copy}, path_remap="RELATIVE", fake_user=False)
        _write_temp_json(temp_json, {
            "temp_blend": temp_blend,
            "source_coll_name": session.source_coll_name,
            "copy_coll_name": copy.name,
            "owned": [
                {"index": i, "id_type": r.id_type, "source_name": r.source_name}
                for i, r in enumerate(session.owned)
            ],
            "update_shared": [list(k) for k in sorted(update_shared)],
            "expected_plan": expected_plan,
        })
    finally:
        _strip_tags()
        for obj, snap in saved:
            _put_channels(obj, snap)
        view_layer.update()


def _run_id():
    return uuid.uuid4().hex[:8]


def _remove_temp_files(paths):
    for path in (paths.temp_blend, paths.temp_json, paths.result_json):
        try:
            os.remove(path)
        except OSError:
            pass  # missing, or locked: the next run uses other names


def _sweep_leftovers(source_path):
    """Remove temp files of earlier runs on ``source_path`` (a Blender that
    crashed mid-Commit). Only called while holding the source's lock, so no
    other run can be using them."""
    folder, base = os.path.split(source_path)
    pattern = re.compile(
        re.escape(os.path.splitext(base)[0]) + r"\.iops_commit-[0-9a-f]{8}\.(blend|json|result\.json|tmp)$",
        re.IGNORECASE,
    )
    try:
        names = os.listdir(folder)
    except OSError:
        return
    for name in names:
        if pattern.match(name):
            try:
                os.remove(os.path.join(folder, name))
            except OSError:
                pass


class SourceLock:
    """``<source>.iops_lock``, created with ``O_EXCL``: one Commit (or
    Rollback) at a time per source file, across Blender instances. A lock
    file older than ``stale_after`` seconds is the leftover of a crashed
    Blender and is replaced. ``touch`` renews it around every worker run
    (each run is killed after the worker timeout), so a live Commit's lock
    never looks stale. Raises ``CommitRefused`` when it is held."""

    def __init__(self, source_path, stale_after):
        self.path = lock_path(source_path)
        self.name = os.path.basename(source_path)
        self.stale_after = stale_after
        self.held = False

    def acquire(self):
        for attempt in range(3):
            try:
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                try:
                    age = time.time() - os.path.getmtime(self.path)
                except OSError:
                    continue  # released meanwhile: try again
                if age <= self.stale_after or attempt:
                    break
                try:
                    os.remove(self.path)
                except OSError:
                    break
                continue
            except OSError as exc:
                raise CommitRefused(f"Cannot create the lock file {self.path}: {exc}") from exc
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump({"pid": os.getpid(), "time": time.time(), "file": bpy.data.filepath}, fh)
            self.held = True
            return self
        raise CommitRefused(f"another Commit is running on {self.name} (lock file {self.path})")

    def touch(self):
        if self.held:
            try:
                os.utime(self.path)
            except OSError:
                pass

    def release(self):
        if self.held:
            self.held = False
            try:
                os.remove(self.path)
            except OSError:
                pass

    def __enter__(self):
        return self.acquire()

    def __exit__(self, *_exc):
        self.release()


def _tail(text, lines=12):
    return "\n".join(text.strip().splitlines()[-lines:])


def run_worker(source_path, temp_json, mode, result_json, timeout, lock=None):
    """Run the merge worker on ``source_path``; returns its parsed result,
    or ``{"ok": False, "error": ...}`` when it failed, timed out or left no
    readable result. ``lock`` (a held ``SourceLock``) is renewed before and
    after the run."""
    if lock is not None:
        lock.touch()
    try:
        os.remove(result_json)
    except FileNotFoundError:
        pass
    except OSError as exc:
        return {"ok": False, "error": f"Cannot replace the worker result {result_json}: {exc}"}
    cmd = [
        bpy.app.binary_path, "--background", "--factory-startup", "--disable-autoexec",
        source_path, "--python", WORKER, "--", temp_json, mode, result_json,
    ]
    try:
        done = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            creationflags=worker_creation_flags(),
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"Merge worker timed out after {timeout} s"}
    except OSError as exc:
        return {"ok": False, "error": f"Could not start the merge worker: {exc}"}
    finally:
        if lock is not None:
            lock.touch()
    output = (done.stdout or b"").decode("utf-8", "replace")
    try:
        with open(result_json, encoding="utf-8") as fh:
            result = json.load(fh)
    except (OSError, ValueError):
        result = None
    finally:
        try:
            os.remove(result_json)
        except OSError:
            pass
    if not isinstance(result, dict):
        return {"ok": False, "error": f"Merge worker left no result (exit {done.returncode}):\n{_tail(output)}"}
    if done.returncode != 0 or not result.get("ok"):
        result["ok"] = False
        result["error"] = result.get("error") or f"Merge worker exited with {done.returncode}:\n{_tail(output)}"
    return result


_EXC_LINE = re.compile(r"^[A-Za-z_][\w.]*(Error|Exception|Exit)\b")


def _error_line(result):
    """The exception line of the worker's error (its last line when there
    is none), for a report."""
    lines = [ln for ln in str(result.get("error") or "unknown error").strip().splitlines() if ln.strip()]
    exc = [ln for ln in lines if _EXC_LINE.match(ln)]
    return (exc or lines or ["unknown error"])[-1]


def _worker_timeout(context):
    prefs = get_prefs(context)
    return getattr(prefs, "iops_instance_edit_worker_timeout", 300) if prefs is not None else 300


def _read_only(path):
    if not os.access(path, os.W_OK):
        return True
    attrs = getattr(os.stat(path), "st_file_attributes", 0)
    return bool(attrs & getattr(stat, "FILE_ATTRIBUTE_READONLY", 0))


# A 'p4 edit' answer that makes writing the file wrong even when it is now
# writable: the workspace copy is stale or not Perforce's at all.
_P4_REFUSE = re.compile(r"must sync|must resolve|not on client|no such file", re.IGNORECASE)


def _p4_edit(path):
    """Output (stdout and stderr) of ``p4 edit <path>``."""
    try:
        done = subprocess.run(
            ["p4", "edit", path],
            cwd=os.path.dirname(path),
            timeout=30,
            capture_output=True,
            creationflags=worker_creation_flags(),
            check=False,
        )
        return ((done.stdout or b"") + b"\n" + (done.stderr or b"")).decode("utf-8", "replace")
    except subprocess.TimeoutExpired as exc:
        return str(exc)
    except OSError as exc:
        return f"P4_NOT_FOUND: {exc}"


def _p4_auto(context):
    prefs = get_prefs(context)
    return prefs is not None and getattr(prefs, "iops_instance_edit_p4", True)


def _read_only_notice(context, path):
    """One line for Start when the source is read-only: it is checked out
    in Perforce automatically on Commit (preference on) or the user has to
    check it out first (preference off). Empty when writable."""
    if not os.path.isfile(path) or not _read_only(path):
        return []
    name = os.path.basename(path)
    if _p4_auto(context):
        return [f"{name} is read-only: it will be checked out in Perforce (p4 edit) on Commit"]
    return [f"{name} is read-only: check it out before Commit (Perforce auto checkout is off)"]


def ensure_writable(context, path):
    """``(writable, reason, lines)``. A read-only file gets one ``p4 edit``
    automatically (the *Perforce checkout* preference, on by default); the
    read-only bit is never cleared. ``lines`` is what to tell the user: a
    "Checked out in Perforce" line on success plus the ``p4 edit`` output.
    An answer saying the file must be synced / resolved or is not in the
    client refuses, with that line as the reason."""
    name = os.path.basename(path)
    if not _read_only(path):
        return True, "", []
    if not _p4_auto(context):
        return False, f"{name} is read-only: check it out first (Perforce auto checkout is off in the preferences)", []
    out = _p4_edit(path)
    lines = [f"p4 edit: {ln.strip()}" for ln in out.splitlines() if ln.strip()]
    if _p4_missing(out):
        return False, f"{name} is read-only and 'p4' was not found on PATH: check the file out by hand", lines
    bad = next((ln for ln in lines if _P4_REFUSE.search(ln)), None)
    if bad is not None:
        return False, f"{name}: {bad}", lines
    if not _read_only(path):
        return True, "", [f"Checked out in Perforce: {name}"] + lines
    return False, f"{name} is still read-only after 'p4 edit': {_tail(out, 3) or 'no output'}", lines


def _p4_missing(out):
    """Whether ``_p4_edit`` could not start ``p4`` at all."""
    return out.startswith("P4_NOT_FOUND")


ALREADY_COMMITTED = "This session was already committed; Cancel it"


def already_committed(session):
    """Whether a backup sidecar of the session's source names this session
    with a successful write (``source_stat`` set): it was committed, and an
    undo brought it back. Every sidecar of the source in both backup
    locations (next to the source and the custom folder) is read."""
    if not session.uuid:
        return False
    for point in source_points(None, session.source_path, ext=BACKUP_SIDECAR_EXT):
        side = read_point(point.sidecar)
        if side.get("session_uuid") == session.uuid and side.get("source_stat") is not None:
            return True
    return False


def preflight(context, session):
    """``(ok, lines, writable)`` before Commit touches anything: the source
    exists and this session was not committed already (else not ok), a
    warning line when it changed since Start, and the writable check (with
    ``p4 edit``, whose output joins ``lines``; not ok when still read-only
    or when Perforce says the file must be synced / resolved). In the
    custom-folder location mode, a *backup folder* preference that is not
    an absolute path adds a line (it is ignored)."""
    path = session.source_path
    if not os.path.isfile(path):
        return False, [f"Source file not found: {path}"], False
    if already_committed(session):
        return False, [ALREADY_COMMITTED], False
    lines = []
    st = os.stat(path)
    if source_changed(source_stat(session), (st.st_mtime, st.st_size)):
        lines.append(
            f"{os.path.basename(path)} changed since Start: the merge runs on its current content"
        )
    problem = backup_dir_problem(context) if location_mode(context) == "CUSTOM_FOLDER" else None
    if problem:
        lines.append(problem)
    writable, reason, p4_lines = ensure_writable(context, path)
    if not writable:
        return False, [reason] + p4_lines, False
    return True, lines + p4_lines, True


def newer_source_error(result):
    """The refusal when the worker reported a source saved by a newer
    Blender than this one, else None."""
    version = result.get("source_blender_version")
    if not newer_blender(version, bpy.app.version_file):
        return None
    src = ".".join(str(v) for v in version[:2])
    run = ".".join(str(v) for v in bpy.app.version_file[:2])
    return (
        f"The source was saved by Blender {src}, newer than this {run}: "
        "Commit would down-version it. Commit from Blender " + src + " or newer"
    )


def _version_line(result):
    version = result.get("source_blender_version")
    if not version or tuple(version) >= tuple(bpy.app.version_file):
        return []
    old = ".".join(str(v) for v in version)
    new = ".".join(str(v) for v in bpy.app.version_file)
    return [f"Source was saved by Blender {old}: Commit saves it in the {new} format"]


def _set_expected(temp_json, plan):
    with open(temp_json, encoding="utf-8") as fh:
        cfg = json.load(fh)
    cfg["expected_plan"] = plan
    _write_temp_json(temp_json, cfg)


def _session_refs(session):
    """How often each ID (by pointer) is referenced by the session's own
    pointer properties: those count as users."""
    ids = [session.instancer, session.collection, session.copy_collection]
    for rows in (session.owned, session.instancers, session.objects, session.colls, session.layer_colls):
        ids += [r.ref for r in rows]
    return Counter(i.as_pointer() for i in ids if i is not None)


def _collection_parents(coll):
    out = [c for c in bpy.data.collections if any(ch == coll for ch in c.children)]
    out += [s.collection for s in bpy.data.scenes if any(ch == coll for ch in s.collection.children)]
    return out


def _remove_copy(session):
    """Remove the copy collection and what only the session brought.

    First the copy, its owned child collections used nowhere else and its
    owned objects in no other collection. Then, to a fixed point, the IDs of
    the copy's closure left without users (the session's own pointers do not
    count): an owned ID (the append's) also when only its fake user is left,
    as that came from the source; any other local ID only without a fake
    user. So the user's own datablocks (fake-user or asset-marked materials,
    meshes, ...) assigned during the session are never removed, whether they
    existed before Start or not. IDs a driver only reads are never
    candidates."""
    copy = session.copy_collection
    owned = {r.ref.as_pointer() for r in session.owned if r.ref is not None}
    candidates = set(owned)
    first = []
    if copy is not None:
        local, _linked, stopped = _copy_closure_full(copy)
        candidates |= {i.as_pointer() for i in local if i.as_pointer() not in stopped}
        candidates.add(copy.as_pointer())
        colls = [copy]
        coll_ptrs = {copy.as_pointer()}
        # children_recursive lists parents before their children.
        for c in copy.children_recursive:
            if (
                c.library is None
                and c.as_pointer() in owned
                and all(p.as_pointer() in coll_ptrs for p in _collection_parents(c))
            ):
                colls.append(c)
                coll_ptrs.add(c.as_pointer())
        objs = [
            o for o in copy.all_objects
            if o.library is None
            and o.as_pointer() in owned
            and all(c.as_pointer() in coll_ptrs for c in o.users_collection)
        ]
        first = colls + objs
    refs = _session_refs(session)
    if first:
        bpy.data.batch_remove(first)
    attrs = _id_attrs()
    while True:
        # Fresh wrappers every round: never touch one of a removed ID.
        dead = []
        for attr in attrs:
            for id_ in getattr(bpy.data, attr):
                ptr = id_.as_pointer()
                if ptr not in candidates or id_.library is not None:
                    continue
                if ptr in owned:
                    left = id_.users - refs[ptr] - (1 if id_.use_fake_user else 0)
                elif id_.use_fake_user:
                    continue  # the user's own datablock: never removed
                else:
                    left = id_.users - refs[ptr]
                if left <= 0:
                    dead.append(id_)
        if not dead:
            break
        candidates -= {i.as_pointer() for i in dead}
        bpy.data.batch_remove(dead)


def _select_instancer(context, view_layer, instancer):
    if instancer is None or not _in_view_layer(view_layer, instancer):
        return
    for obj in list(view_layer.objects):
        if obj is not None and obj.select_get(view_layer=view_layer):
            obj.select_set(False, view_layer=view_layer)
    try:
        instancer.select_set(True, view_layer=view_layer)
    except RuntimeError:
        pass
    view_layer.objects.active = instancer
    if view_layer == context.view_layer:
        _reveal_active_in_outliners(context)


def finish_linked(context, session):
    """Close a linked session in the editing file: visibility back first
    (instancer, hidden linked objects, active layer collection), then the
    copy and its IDs removed, the session popped and the instancer
    selected. Returns names that could not be found."""
    view_layer, _fell_back = _session_view_layer(context, session)
    instancer = session.instancer
    missing = restore_visibility(context, session)
    _remove_copy(session)
    view_layer.update()
    pop_session(context.scene)
    _select_instancer(context, view_layer, instancer)
    return list(dict.fromkeys(missing))


def cancel_linked(context, session):
    """Cancel: close the session without touching the source file."""
    _ensure_object_mode(context)
    return finish_linked(context, session)


def _reload_source(session):
    """Reload the session's Library and every other one of the same file.
    Returns the number reloaded."""
    libs = _source_libraries(session.source_path)
    named = bpy.data.libraries.get(session.library_name)
    if named is not None and named not in libs:
        libs.append(named)
    for lib in libs:
        lib.reload()
    return len(libs)


def file_stat(path):
    """``(mtime, size)`` of ``path``, or None when it cannot be read."""
    try:
        st = os.stat(path)
    except OSError:
        return None
    return (st.st_mtime, st.st_size)


def _stat_differs(a, b):
    return a is None or b is None or source_changed(a, b)


def _default_backup_dir():
    return os.path.join(bpy.utils.user_resource("CONFIG"), "iops", "instance_edit_backups")


def _backup_dir_pref(context=None):
    prefs = get_prefs(context)
    return (getattr(prefs, "iops_instance_edit_backup_dir", "") or "").strip() if prefs is not None else ""


def _absolute_folder(folder):
    """Whether ``folder`` is a usable absolute path: not Blender's ``//``
    relative prefix (which Windows would read as a UNC path; a UNC folder
    is written with backslashes) and, on Windows, with a drive or share."""
    if not folder or folder.startswith("//") or not os.path.isabs(folder):
        return False
    return os.name != "nt" or bool(os.path.splitdrive(folder)[0])


def backup_dir_problem(context=None):
    """Why the *backup folder* preference is not used, or None: only an
    absolute path is (a ``//`` path would follow whichever file is open)."""
    folder = _backup_dir_pref(context)
    if folder and not _absolute_folder(folder):
        return (
            f"Instance Edit backup folder '{folder}' is not an absolute path: ignored, "
            f"backups go to {os.path.normpath(_default_backup_dir())}"
        )
    return None


def backup_dir(context=None, create=True):
    """The custom backup folder: the *backup folder* preference when it is
    an absolute path, else (empty, or relative: see ``backup_dir_problem``)
    ``<Blender user config>/iops/instance_edit_backups``. Created when
    ``create`` (raises OSError when that fails); listings pass False and
    treat a missing folder as empty."""
    folder = _backup_dir_pref(context)
    if not _absolute_folder(folder):
        folder = _default_backup_dir()
    folder = os.path.normpath(folder)
    if create:
        os.makedirs(folder, exist_ok=True)
    return folder


LOCATIONS = ("NEXT_TO_SOURCE", "CUSTOM_FOLDER")
# How the Rollback list names a point's location.
LOCATION_TAGS = {"NEXT_TO_SOURCE": BACKUP_SUBFOLDER, "CUSTOM_FOLDER": "folder"}


def location_mode(context=None):
    """The *backup location* preference: ``NEXT_TO_SOURCE`` (default) or
    ``CUSTOM_FOLDER``."""
    prefs = get_prefs(context)
    mode = getattr(prefs, "iops_instance_edit_backup_location", LOCATIONS[0]) if prefs is not None else LOCATIONS[0]
    return mode if mode in LOCATIONS else LOCATIONS[0]


def next_to_source_dir(source_path):
    """``<folder of the source>/.iopsbackup``."""
    return os.path.join(os.path.dirname(os.path.normpath(os.path.abspath(source_path))), BACKUP_SUBFOLDER)


def backup_location_for(context, source_path, mode=None):
    """``(folder, path_hash)`` where Commit backs ``source_path`` up in
    location ``mode`` (default: the preference): next to the source, the
    ``.iopsbackup`` subfolder and no hash in the names; the custom folder
    (``backup_dir``) with the source's path hash in the names. Never
    creates the folder."""
    mode = mode or location_mode(context)
    if mode == "CUSTOM_FOLDER":
        return backup_dir(context, create=False), source_hash(source_path)
    return next_to_source_dir(source_path), None


def _locations(context, source_path):
    """``[(mode, folder, path_hash)]``: the current location mode first,
    then the other one (points stay reachable after switching modes)."""
    current = location_mode(context)
    modes = [current] + [m for m in LOCATIONS if m != current]
    return [(mode,) + backup_location_for(context, source_path, mode) for mode in modes]


def backup_user():
    """The OS user name as backup names carry it (``user_tag``)."""
    return user_tag(_os_user())


def _os_user():
    try:
        return getpass.getuser()
    except Exception:  # no user name in the environment / password database
        return ""


def point_owner(side):
    """The raw OS user name a sidecar records, or None (no sidecar, an old
    or damaged one)."""
    user = side.get("user") if isinstance(side, dict) else None
    return user if isinstance(user, str) and user else None


def is_mine(name, folder=None, side=None):
    """Whether the point ``name`` was taken by the current OS user: the raw
    ``user`` its sidecar records (``side``, or read from ``folder``),
    case-folded, against the raw OS user name. Only without a usable
    sidecar does the user tag the name carries decide (case ignored), so
    two people whose names reduce to one tag (``____``, a shared 12-char
    prefix) stay apart wherever their sidecars exist."""
    if side is None and folder is not None:
        side = read_point(point_files(folder, name)[1])
    owner = point_owner(side)
    if owner is not None:
        return owner.casefold() == _os_user().casefold()
    return (point_user(name) or "").lower() == backup_user().lower()


def _prune_only_mine(context=None):
    prefs = get_prefs(context)
    return bool(getattr(prefs, "iops_instance_edit_prune_only_mine", True)) if prefs is not None else True


def _backup_count(context=None):
    prefs = get_prefs(context)
    count = getattr(prefs, "iops_instance_edit_backup_count", 3) if prefs is not None else 3
    return max(1, int(count))


def _listing(folder):
    try:
        return os.listdir(folder)
    except OSError:
        return []


def point_files(folder, point):
    """``(copy, sidecar)`` of the backup point ``point`` (a name) in ``folder``."""
    base = os.path.join(folder, point)
    return base + BACKUP_EXT, base + BACKUP_SIDECAR_EXT


class BackupPoint(namedtuple("BackupPoint", "name folder kind")):
    """One backup point: its name (no extension), the folder it lies in and
    the location mode of that folder (``NEXT_TO_SOURCE`` / ``CUSTOM_FOLDER``)."""

    __slots__ = ()

    @property
    def blend(self):
        return point_files(self.folder, self.name)[0]

    @property
    def sidecar(self):
        return point_files(self.folder, self.name)[1]

    @property
    def user(self):
        return point_user(self.name)


def _stem(source_path):
    return os.path.splitext(os.path.basename(source_path))[0]


def _stamp_key(point):
    return (point.name.rsplit(".", 1)[-1], point.name)


def source_points(context, source_path, ext=BACKUP_EXT, listings=None):
    """Every backup point of ``source_path`` in both locations, every
    user's, newest first, as ``BackupPoint``. ``ext=BACKUP_SIDECAR_EXT``
    lists sidecars instead. ``listings`` (folder -> names) shares folder
    listings between calls."""
    stem = _stem(source_path)
    out, seen = [], set()
    for mode, folder, path_hash in _locations(context, source_path):
        if listings is None:
            names = _listing(folder)
        else:
            names = listings.get(folder)
            if names is None:
                names = listings[folder] = _listing(folder)
        for name in backup_points(names, stem, path_hash, ext=ext):
            key = (_norm_path(folder), name)
            if key not in seen:
                seen.add(key)
                out.append(BackupPoint(name, folder, mode))
    out.sort(key=_stamp_key, reverse=True)
    return out


def read_point(json_path):
    """A backup point's sidecar: ``source_path`` (absolute), ``backup_time``
    (ISO, UTC), ``source_stat`` (the source's ``(mtime, size)`` after the
    Commit that took the point wrote it; None until that write succeeded),
    ``session_uuid`` (the committing session), ``user`` and ``machine``.
    Empty when unreadable."""
    try:
        with open(json_path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_point_json(json_path, data):
    with open(json_path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=1)


def update_point(json_path, **values):
    """Merge ``values`` into a sidecar. Returns False when it could not be
    written (callers that cannot go on without it check)."""
    data = read_point(json_path)
    data.update(values)
    try:
        _write_point_json(json_path, data)
    except OSError:
        return False
    return True


def _remove_point(blend, side):
    """Remove a point's copy, then its sidecar. True when the copy is gone
    (a locked copy keeps the point whole)."""
    try:
        os.remove(blend)
    except FileNotFoundError:
        pass
    except OSError:
        return False
    try:
        os.remove(side)
    except OSError:
        pass
    return True


def _drop_empty_subfolder(folder):
    """Remove ``folder`` when it is an empty ``.iopsbackup`` folder (left by
    a Commit whose only point was removed again)."""
    if os.path.basename(os.path.normpath(folder)) == BACKUP_SUBFOLDER:
        try:
            os.rmdir(folder)
        except OSError:
            pass  # not empty, or in use: keep it


def part_path(folder, point):
    """``<point>.iopsbackup.part``: the copy of ``point`` while it is written."""
    return os.path.join(folder, point + BACKUP_PART_EXT)


def _part_stale_after(context=None):
    """Seconds after which a ``.part`` copy is a crashed Commit's leftover
    (its stamp is when the copy started)."""
    return max(3600, _worker_timeout(context))


def _stale_part(name, context=None, now=None):
    when = point_stamp(name)
    now = now or datetime.datetime.now(datetime.timezone.utc)
    return when is not None and (now - when).total_seconds() > _part_stale_after(context)


def write_backup(context, source_path, session_uuid):
    """Copy ``source_path`` into its backup location (the *backup location*
    preference: the ``.iopsbackup`` folder beside it, created here, or the
    custom folder) as a new backup point ``<stem>[.<hash>].<user>.<stamp>
    .iopsbackup`` and write its sidecar (``source_stat`` None until the
    write succeeds; ``user`` the raw OS user name, ``machine``). The copy
    is written as ``<point>.iopsbackup.part`` (never listed as a point) and
    moved into place with ``os.replace``, so no listing ever sees a half
    copy. Returns ``(copy, sidecar)``. The stamp is UTC; a name taken in the
    same second moves on by a second, so points never overwrite each other.
    Raises OSError when the folder cannot be created or the copy or the
    sidecar cannot be written (nothing is left behind then): the Commit is
    refused before the source is touched. Pruning to the *backups per file*
    preference is ``prune_points``, run after the write succeeded."""
    folder, path_hash = backup_location_for(context, source_path)
    os.makedirs(folder, exist_ok=True)
    os_user = _os_user()
    stem = _stem(source_path)
    now = datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0)
    when = now
    while True:
        name = point_name(stem, os_user, when, path_hash)
        blend, side = point_files(folder, name)
        part = part_path(folder, name)
        if not any(os.path.exists(p) for p in (blend, side, part)):
            break
        when += datetime.timedelta(seconds=1)
    try:
        shutil.copy2(source_path, part)
        os.replace(part, blend)
        _write_point_json(side, {
            "source_path": os.path.normpath(os.path.abspath(source_path)),
            "backup_time": now.isoformat(timespec="seconds"),
            "source_stat": None,
            "session_uuid": session_uuid,
            "user": os_user,
            "machine": platform.node(),
        })
    except OSError:
        try:
            os.remove(part)
        except OSError:
            pass
        _remove_point(blend, side)
        _drop_empty_subfolder(folder)
        raise
    invalidate_points_cache()
    return blend, side


def prune_points(context, source_path, protect=None):
    """Remove the oldest backup points of ``source_path`` in its current
    backup location beyond the *backups per file* preference, never
    ``protect`` (the point just written). With *prune only my backups* on,
    only the current user's points (``is_mine``: by the sidecar's raw user)
    are counted and removed; other users' points are never touched.
    Sidecars of the source left without their copy go too, and ``.part``
    copies older than ``_part_stale_after`` (only the current user's, with
    the preference on). Returns the names whose copy was actually removed."""
    folder, path_hash = backup_location_for(context, source_path)
    stem = _stem(source_path)
    listing = _listing(folder)
    names = backup_points(listing, stem, path_hash)
    mine = (lambda n: is_mine(n, folder)) if _prune_only_mine(context) else None
    removed = []
    for name in prune_backups(names, _backup_count(context), protect, mine):
        if _remove_point(*point_files(folder, name)):
            removed.append(name)
    leftovers = [point_files(folder, n)[1]
                 for n in set(backup_points(listing, stem, path_hash, ext=BACKUP_SIDECAR_EXT)) - set(names)
                 if mine is None or mine(n)]
    leftovers += [part_path(folder, n) for n in backup_points(listing, stem, path_hash, ext=BACKUP_PART_EXT)
                  if _stale_part(n, context) and (mine is None or mine(n))]
    for path in leftovers:
        try:
            os.remove(path)
        except OSError:
            pass
    invalidate_points_cache()
    return removed


CleanupPlan = namedtuple("CleanupPlan", "points files bytes groups")


def cleanup_candidates(context, scope, older_than_days, only_mine, source_path="", not_after=None):
    """What Clean Up Backups deletes: a ``CleanupPlan`` of the points
    (``(folder, name)``, sorted), their files (copy before sidecar, then a
    stale ``.part`` copy; a sidecar or a stale ``.part`` without its copy
    counts as a point too), the bytes they take and ``groups``: ``[(source
    path or None, files)]``, the files per library (whose lock Clean Up
    takes) for ``LIBRARIES``, one ``None`` group for the custom folder.
    ``scope`` ``LIBRARIES``: both backup locations of every library of the
    file (only ``source_path`` when given); ``CUSTOM_FOLDER``: every point
    in the custom folder (only ``source_path``'s when given). Only names in
    the point grammar are ever candidates. ``older_than_days`` > 0 keeps
    points whose UTC stamp is not older than that; ``only_mine`` keeps
    other users' points (``is_mine``); ``not_after`` (aware UTC) keeps
    points stamped after it (taken after the dialog opened)."""
    now = datetime.datetime.now(datetime.timezone.utc)
    cutoff = now - datetime.timedelta(days=older_than_days) if older_than_days > 0 else None

    def wanted(folder, name):
        when = point_stamp(name)
        if when is None:
            return False
        if cutoff is not None and when >= cutoff:
            return False
        if not_after is not None and when > not_after:
            return False
        return not only_mine or is_mine(name, folder)

    found = {}  # (folder, name) -> source path or None

    def add(folder, names, source=None):
        for name in names:
            if (folder, name) not in found and wanted(folder, name):
                found[(folder, name)] = source

    exts = (BACKUP_EXT, BACKUP_SIDECAR_EXT, BACKUP_PART_EXT)
    if scope == "CUSTOM_FOLDER":
        folder = backup_dir(context, create=False)
        listing = _listing(folder)
        if source_path:
            path = os.path.normpath(bpy.path.abspath(source_path))
            stem, path_hash = _stem(path), source_hash(path)
            for ext in exts:
                add(folder, backup_points(listing, stem, path_hash, ext=ext))
        else:
            for entry in listing:
                for ext in (BACKUP_SIDECAR_EXT, BACKUP_PART_EXT, BACKUP_EXT):
                    if entry.lower().endswith(ext) and len(entry) > len(ext):
                        base = entry[:-len(ext)]
                        if parse_point(base) is not None:
                            add(folder, [base])
                        break
    else:
        if source_path:
            sources = [os.path.normpath(bpy.path.abspath(source_path))]
        else:
            sources, keys = [], set()
            for lib in bpy.data.libraries:
                path = library_path(lib)
                if _norm_path(path) not in keys:
                    keys.add(_norm_path(path))
                    sources.append(path)
        listings = {}
        for path in sources:
            for ext in exts:
                for point in source_points(context, path, ext=ext, listings=listings):
                    add(point.folder, [point.name], path)
    points, files, size, groups = [], [], 0, {}
    for folder, name in sorted(found):
        paths = list(point_files(folder, name))
        if _stale_part(name, context, now):
            paths.append(part_path(folder, name))
        present = []
        for path in paths:
            try:
                size += os.path.getsize(path)
            except OSError:
                continue  # missing part of the set
            present.append(path)
        if present:  # a fresh .part alone is a Commit at work, not a point
            points.append((folder, name))
            files += present
            groups.setdefault(found[(folder, name)], []).extend(present)
    return CleanupPlan(points, files, size, list(groups.items()))


def run_cleanup(context, plan):
    """Delete exactly ``plan.files``, library by library under that
    library's lock (a library whose lock is held, or cannot be taken, is
    skipped whole). Returns ``(deleted, freed bytes, failed, skipped,
    refusals)``; a file that cannot be deleted is counted, never raised."""
    deleted = freed = failed = skipped = 0
    refusals = []
    timeout = _worker_timeout(context)
    for source, files in plan.groups:
        lock = None
        if source:
            try:
                lock = SourceLock(source, timeout).acquire()
            except CommitRefused as exc:
                skipped += len(files)
                refusals.append(str(exc))
                continue
        try:
            for path in files:
                try:
                    size = os.path.getsize(path)
                    os.remove(path)
                except OSError:
                    failed += 1
                    continue
                deleted += 1
                freed += size
        finally:
            if lock is not None:
                lock.release()
    invalidate_points_cache()
    return deleted, freed, failed, skipped, refusals


def _membership_extras(confirmed, planned):
    """``unlinked`` / ``deleted`` entries of ``planned`` the confirmed dry
    run did not have (a ticked child collection changes membership)."""
    extra = []
    for key in ("unlinked", "deleted"):
        before = {tuple(x) for x in confirmed.get(key) or ()}
        extra += [f"{key} {n}" for t, n in (tuple(x) for x in planned.get(key) or ()) if (t, n) not in before]
    return extra


def commit_linked(context, session, update_shared=(), expected_plan=None, dry_run_stat=None):
    """Write the session back into its source file and close it.

    ``expected_plan`` is the dry run the user confirmed (computed with
    nothing ticked) and ``dry_run_stat`` the source's ``(mtime, size)`` when
    it ran; ``update_shared`` the ticked shared ``(id_type, source_name)``
    keys. With ticks, a plan pass with the ticks runs first and must differ
    from the confirmed one only by them. Without ``expected_plan``
    (scripted use, ``EXEC_DEFAULT``) a fresh dry run counts as confirmed.
    A source that changed since the dry run is refused before the backup.
    The source is backed up right before the write; the worker saves only
    at its very end. The session is closed only after the write succeeded
    and the library was reloaded; a cleanup failure after that is reported
    in ``lines`` (``ok`` stays True: the source is written). Returns
    ``{"ok", "error", "plan", "backup", "lines", "missing"}``.

    Everything from the export to the write runs under the source's lock
    file (another Commit on the same source is refused) with temp files
    named for this run. A source saved by a newer Blender is refused (the
    worker refuses to save it too)."""
    update_shared = {tuple(k) for k in update_shared}
    out = {"ok": False, "error": None, "plan": None, "backup": None, "lines": [], "missing": []}
    path = session.source_path
    name = os.path.basename(path)
    ok, lines, _writable = preflight(context, session)
    out["lines"] = lines
    if not ok:
        out["error"] = lines[0]
        return out
    timeout = _worker_timeout(context)
    paths = commit_temp_paths(path, _run_id())
    temp_json, result_json = paths.temp_json, paths.result_json
    backup = None
    lock = SourceLock(path, timeout)
    try:
        lock.acquire()
    except CommitRefused as exc:
        out["error"] = str(exc)
        return out
    try:
        _sweep_leftovers(path)
        try:
            export_copy(context, session, paths, update_shared, expected_plan)
        except CommitRefused as exc:
            out["error"] = str(exc)
            return out
        planned = None
        if expected_plan is None or update_shared:
            if expected_plan is None:
                dry_run_stat = file_stat(path)
            planned = run_worker(path, temp_json, "plan", result_json, timeout, lock)
            if not planned.get("ok"):
                print(planned.get("error"))
                out["error"] = "Dry run failed: " + _error_line(planned)
                return out
            newer = newer_source_error(planned)
            if newer:
                out["error"] = newer
                return out
            if expected_plan is not None:
                problem = ticked_plan_problem(expected_plan, planned["plan"], update_shared)
                if problem:
                    out["error"] = f"The merge changed since the dry run ({problem}): Commit again"
                    return out
            _set_expected(temp_json, planned["plan"])
        before = file_stat(path)
        if dry_run_stat is not None and _stat_differs(tuple(dry_run_stat), before):
            out["error"] = f"{name} changed since the dry run: Commit again"
            return out
        # Backed up only once nothing can refuse any more: a refused Commit
        # must not overwrite the backup of the previous one.
        try:
            backup, sidecar = write_backup(context, path, session.uuid)
        except OSError as exc:
            out["error"] = f"Could not back up {name}: {exc}"
            return out
        out["backup"] = backup
        written = run_worker(path, temp_json, "write", result_json, timeout, lock)
        if not written.get("ok"):
            print(written.get("error"))
            if _stat_differs(before, file_stat(path)):
                # The point stays (its source_stat unknown): it is the way back.
                out["error"] = (
                    f"Merge failed, but the worker may have written {name}; check it "
                    f"before committing again (backup: {backup}): " + _error_line(written)
                )
            else:
                # The source is untouched: this point is a copy of it and
                # must not push a real one out of the backups per file.
                _remove_point(backup, sidecar)
                _drop_empty_subfolder(os.path.dirname(backup))
                invalidate_points_cache()
                out["backup"] = None
                out["error"] = f"Merge failed, {name} not written: " + _error_line(written)
            return out
        out["plan"] = written.get("plan")
        if not update_point(sidecar, source_stat=file_stat(path)):
            out["lines"].append(
                f"Could not record this Commit in {sidecar}: an undo that brings the "
                "session back is not recognised as committed"
            )
        # Only after a successful write, and never the point just written
        # (a clock set back would sort it oldest).
        prune_points(context, path, protect=os.path.basename(backup)[:-len(BACKUP_EXT)])
        if planned is not None and expected_plan is not None:
            extra = _membership_extras(expected_plan, out["plan"] or {})
            if extra:
                out["lines"].append("Also changed by the ticked datablocks: " + ", ".join(extra))
    finally:
        _remove_temp_files(paths)
        lock.release()
    try:
        if not _reload_source(session):
            out["lines"].append(f"No library of {name} found to reload")
    except (RuntimeError, ReferenceError) as exc:
        out["error"] = (
            f"{name} was written (backup: {backup}) but reloading it failed: {exc}. "
            "Reload the library, then Cancel the session"
        )
        return out
    out["ok"] = True
    try:
        out["missing"] = finish_linked(context, session)
    except Exception as exc:  # the source is written: never re-raise
        print(f"Instance edit cleanup failed: {exc!r}")
        out["lines"].append(f"{name} written; cleanup failed ({exc}): Cancel the session")
    return out


def dry_run_linked(context, session):
    """Commit's dry run (what the operator's invoke runs before the
    dialog): export the copy and run the worker in plan mode, under the
    source's lock, temp files removed afterwards. Returns ``(result,
    stat)``: the worker's result and the source's ``(mtime, size)`` when the
    dry run started. Raises ``CommitRefused`` when the copy cannot be
    exported or another Commit holds the source."""
    path = session.source_path
    timeout = _worker_timeout(context)
    paths = commit_temp_paths(path, _run_id())
    with SourceLock(path, timeout) as lock:
        _sweep_leftovers(path)
        try:
            export_copy(context, session, paths)
            stat = file_stat(path)
            result = run_worker(path, paths.temp_json, "plan", paths.result_json, timeout, lock)
        finally:
            _remove_temp_files(paths)
    return result, stat


@contextmanager
def busy(context, text):
    """Wait cursor and a status bar text while a worker blocks the UI."""
    window = getattr(context, "window", None)
    workspace = getattr(context, "workspace", None)
    if window is not None:
        window.cursor_set("WAIT")
    if workspace is not None:
        workspace.status_text_set(text)
    if window is not None:
        try:  # show the status text before the UI blocks
            bpy.ops.wm.redraw_timer(type="DRAW_WIN_SWAP", iterations=1)
        except RuntimeError:
            pass
    try:
        yield
    finally:
        if window is not None:
            window.cursor_set("DEFAULT")
        if workspace is not None:
            workspace.status_text_set(None)


# Header buttons and Rollback's poll run on every redraw: the folder listings
# are cached for _POINTS_TTL seconds per (location mode, custom folder,
# library paths) and dropped whenever Commit, Rollback or Clean Up changes a
# backup folder or a source.
_POINTS_TTL = 2.0
_points_cache = {"key": None, "time": float("-inf"), "value": {}}


def invalidate_points_cache():
    _points_cache["key"] = None


def cached_backup_points_for_libraries(context=None):
    """``backup_points_for_libraries`` through the throttled cache."""
    key = (location_mode(context), backup_dir(context, create=False),
           tuple(lib.filepath for lib in bpy.data.libraries))
    now = time.monotonic()
    if _points_cache["key"] != key or now - _points_cache["time"] >= _POINTS_TTL:
        _points_cache.update(key=key, time=now, value=backup_points_for_libraries(context))
    return _points_cache["value"]


def backup_points_for_libraries(context=None):
    """``{source path: [BackupPoint, newest first]}`` for every library of
    the file with a backup point in either location (each folder listed
    once)."""
    out, seen, listings = {}, set(), {}
    for lib in bpy.data.libraries:
        path = library_path(lib)
        key = _norm_path(path)
        if key in seen:
            continue
        seen.add(key)
        points = source_points(context, path, listings=listings)
        if points:
            out[path] = points
    return out


def _type_label(id_type):
    prop = bpy.data.bl_rna.properties.get(id_type)
    fixed = getattr(prop, "fixed_type", None)
    return fixed.name if fixed is not None else id_type


def _names(items):
    names = [str(item[1]) for item in items]
    text = ", ".join(names[:_MAX_NAMES])
    if len(names) > _MAX_NAMES:
        text += f" (+{len(names) - _MAX_NAMES} more, full list in the system console)"
    return text


def _print_plan_if_truncated(title, plan):
    """The dialog shows at most ``_MAX_NAMES`` names per line: print the
    whole plan to the system console when any line is cut."""
    keys = [k for k, _label in _PLAN_LINES] + ["discarded", "shared"]
    if any(len(plan.get(k) or ()) > _MAX_NAMES for k in keys):
        print(f"--- {title}: full merge plan ---")
        for key in keys:
            items = plan.get(key) or []
            if items:
                print(f"{key} ({len(items)}):")
                for id_type, id_name in items:
                    print(f"    {id_type}: {id_name}")


def fill_shared_rows(wm, plan):
    """One unticked ``wm.iops_ie_shared`` row per shared ID of ``plan``."""
    rows = wm.iops_ie_shared
    rows.clear()
    users = plan.get("shared_users") or {}
    for id_type, source_name in plan.get("shared") or ():
        row = rows.add()
        row.id_type = id_type
        row.source_name = source_name
        row.users = ", ".join(users.get(f"{id_type}:{source_name}", ()))
        row.update = False


class _LinkedSessionOperator:
    @classmethod
    def poll(cls, context):
        scene = getattr(context, "scene", None)
        if scene is None or not session_active(scene):
            cls.poll_message_set("No instance edit in progress")
            return False
        if active_session(scene).kind != "LINKED":
            inner = any(s.kind == "LINKED" for s in scene.iops_instance_edit.sessions)
            cls.poll_message_set(
                "Close the inner session first" if inner else "No linked-library instance edit in progress"
            )
            return False
        return True


class IOPS_OT_instance_edit_commit(_LinkedSessionOperator, bpy.types.Operator):
    """Invoke runs the dry run and shows the plan; execute writes. Called
    with EXEC_DEFAULT (no dialog) it writes with nothing ticked after an
    internal dry run."""

    bl_idname = "iops.instance_edit_commit"
    bl_label = "Commit Instance Edit"
    bl_description = (
        "Write the edited collection back into its source file after a dry run "
        "you confirm. The write cannot be undone with Ctrl+Z: the source is "
        "backed up first and Rollback restores it. Run without the dialog "
        "(scripts), it writes with no shared datablock ticked"
    )
    # No UNDO (the source write cannot be undone) and no REGISTER: an
    # undo step or a redo of this operator must never replay a write.
    bl_options = set()

    def invoke(self, context, event):
        session = active_session(context.scene)
        _ensure_object_mode(context)
        refused = commit_refusal(session)
        if refused:
            self.report({"ERROR"}, refused)
            return {"CANCELLED"}
        ok, lines, _writable = preflight(context, session)
        if not ok:
            for line in lines[1:]:
                self.report({"WARNING"}, line)
            self.report({"ERROR"}, lines[0])
            return {"CANCELLED"}
        path = session.source_path
        name = os.path.basename(path)
        try:
            with busy(context, f"Instance Edit: dry run on {name}..."):
                result, dry_run_stat = dry_run_linked(context, session)
        except CommitRefused as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        if not result.get("ok"):
            print(result.get("error"))
            self.report({"ERROR"}, "Dry run failed: " + _error_line(result))
            return {"CANCELLED"}
        newer = newer_source_error(result)
        if newer:
            self.report({"ERROR"}, newer)
            return {"CANCELLED"}
        plan = result["plan"]
        title = f"Commit {session.source_coll_name} to {name}"
        _print_plan_if_truncated(title, plan)
        fill_shared_rows(context.window_manager, plan)
        self._plan_json = json.dumps(plan)
        self._dry_run_stat = dry_run_stat
        self._lines = lines + _version_line(result)
        return context.window_manager.invoke_props_dialog(
            self,
            width=560,
            title=title,
            confirm_text="Write",
        )

    def draw(self, context):
        layout = self.layout
        plan_json = getattr(self, "_plan_json", None)
        plan = json.loads(plan_json) if plan_json else {}
        col = layout.column(align=True)
        for line in getattr(self, "_lines", ()):
            col.label(text=line, icon="ERROR")
        for key, label in _PLAN_LINES:
            items = plan.get(key) or []
            if items:
                col.label(text=f"{label} ({len(items)}): {_names(items)}")
        discarded = plan.get("discarded") or []
        if discarded:
            row = col.row()
            row.alert = True
            row.label(
                text=f"Discarded, nothing would use them ({len(discarded)}): {_names(discarded)}",
                icon="TRASH",
            )
        rows = context.window_manager.iops_ie_shared
        if len(rows):
            box = layout.box()
            box.label(text="Also used outside this collection; tick to overwrite the source's version:")
            for item in rows:
                row = box.row()
                row.prop(item, "update", text=f"{_type_label(item.id_type)} {item.source_name}")
                row.label(text=f"used by {item.users}" if item.users else "")
            box.label(text="Datablocks used only by other shared ones are updated with the ticked ones.")

    def execute(self, context):
        session = active_session(context.scene)
        plan_json = getattr(self, "_plan_json", None)
        expected = json.loads(plan_json) if plan_json else None
        wm = context.window_manager
        # Ticks only mean something next to the dry run they were made on.
        ticked = {(r.id_type, r.source_name) for r in wm.iops_ie_shared if r.update} if expected else set()
        with busy(context, f"Instance Edit: merging into {os.path.basename(session.source_path)}..."):
            result = commit_linked(
                context, session, ticked, expected, getattr(self, "_dry_run_stat", None) if expected else None
            )
        wm.iops_ie_shared.clear()
        if not result["ok"]:
            self.report({"ERROR"}, result["error"])
            return {"CANCELLED"}
        for line in result["lines"]:
            self.report({"WARNING"}, line)
        if result["missing"]:
            self.report({"WARNING"}, "Missing: " + ", ".join(result["missing"]))
        self.report({"INFO"}, f"Committed. Backup: {result['backup']}")
        return {"FINISHED"}


class IOPS_OT_instance_edit_cancel(_LinkedSessionOperator, bpy.types.Operator):
    bl_idname = "iops.instance_edit_cancel"
    bl_label = "Cancel Instance Edit"
    bl_description = (
        "Discard the edit copy of the linked collection and every change made "
        "to it; the source file is not touched"
    )
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        missing = cancel_linked(context, active_session(context.scene))
        if missing:
            self.report({"WARNING"}, "Missing: " + ", ".join(missing))
        return {"FINISHED"}


def replace_from_backup(backup, path):
    """Copy ``backup`` over ``path`` through a temp file next to ``path``
    (``<stem>.iops_commit-<run id>.tmp``: same volume, so ``os.replace`` is
    atomic) and ``os.replace``: ``path`` is either the old file or the whole
    backup, never half-written."""
    tmp = os.path.splitext(commit_temp_paths(path, _run_id()).temp_blend)[0] + ".tmp"
    try:
        shutil.copyfile(backup, tmp)
        os.replace(tmp, path)
    except OSError:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def point_time(point):
    """Display time of a backup point (a name), local time, from the UTC
    stamp its name ends with (no sidecar read)."""
    when = point_stamp(point)
    if when is None:
        return "an unknown time"
    return when.astimezone().strftime("%Y-%m-%d %H:%M:%S")


def find_point(context, source_path, name):
    """The ``BackupPoint`` of ``source_path`` named ``name`` (either
    location), or None."""
    return next((p for p in source_points(context, source_path) if p.name == name), None)


def rollback_point_warning(context, source_path, point):
    """The warning line for rolling ``source_path`` back to ``point`` (a
    ``BackupPoint`` or a name): ``"<name> was modified after this backup"``
    when the source's ``(mtime, size)`` differs from the one the point's
    sidecar recorded after its Commit wrote the source, ``"cannot tell
    whether <name> was modified after this backup"`` when nothing usable
    was recorded (missing or corrupt sidecar, a write that failed after the
    worker may have written), else None."""
    if not point:
        return None
    name = os.path.basename(source_path)
    if isinstance(point, str):
        point = find_point(context, source_path, point)
    recorded = read_point(point.sidecar).get("source_stat") if point is not None else None
    try:
        recorded = (float(recorded[0]), int(recorded[1]))
    except (TypeError, ValueError, IndexError, KeyError):
        return f"Cannot tell whether {name} was modified after this backup"
    if _stat_differs(recorded, file_stat(source_path)):
        return f"{name} was modified after this backup"
    return None


def _rollback_path(context, source_path):
    """The library file Rollback acts on: ``source_path``, or the only
    library of the file with backup points when it is empty."""
    path = source_path
    if not path:
        paths = list(backup_points_for_libraries(context))
        if len(paths) != 1:
            return None
        path = paths[0]
    return os.path.normpath(bpy.path.abspath(path))


def default_point(points, mine=None):
    """The point Rollback preselects (and restores when none is named):
    the newest of the current user's (``mine``: name -> bool, else
    ``is_mine`` per point), else the newest."""
    def own(p):
        return mine[p.name] if mine is not None and p.name in mine else is_mine(p.name, p.folder)
    return next((p for p in points if own(p)), points[0] if points else None)


def point_numbers(names, fixed=None):
    """``{name: enum number}`` for ``names``. ``fixed`` (name -> number,
    the numbers the open dialog's snapshot handed out) is kept as is, so a
    stored choice never maps to another point; every other point gets its
    ``point_number`` (stamp seconds), moved on by one past any number in use
    (two points of one second, from two users or locations)."""
    wanted = set(names)
    out = {n: v for n, v in (fixed or {}).items() if n in wanted}
    used = set(out.values())
    for name in sorted((n for n in names if n not in out), key=lambda n: (point_number(n), n)):
        number = point_number(name)
        while number in used:
            number += 1
        used.add(number)
        out[name] = number
    return out


def point_label(point, who=None, mine=None):
    """``"<local time>  <mine | user>  [<.iopsbackup | folder>]"``; ``who``
    is the raw user the sidecar records, else the tag in the name."""
    if mine is None:
        mine = is_mine(point.name, point.folder)
    if mine:
        who = "mine"
    elif not who:
        side_user = point_owner(read_point(point.sidecar))
        who = side_user or point.user or "?"
    return f"{point_time(point.name)}  {who}  [{LOCATION_TAGS.get(point.kind, point.kind)}]"


def _point_items_for(points, labels, fixed=None):
    numbers = point_numbers([p.name for p in points], fixed)
    items = [(p.name, labels.get(p.name) or point_label(p), p.blend, numbers[p.name]) for p in points]
    items.sort(key=lambda it: it[3], reverse=True)
    return items


def rollback_snapshot(context, path):
    """What Rollback's dialog shows, taken once at invoke: ``{"key",
    "points", "labels", "items", "warnings", "default"}`` with every point
    of the source in both locations (newest first), their labels ("mine"
    for the current user's by ``is_mine``, else the raw user the sidecar
    records, else the tag in the name), the enum items (their numbers stay
    fixed while the dialog is open), the warning line per point and the
    preselected point (the newest own, else the newest). The dialog's draw
    and the enum's items read it instead of the folders and the sidecars."""
    points = source_points(context, path)
    labels, mine = {}, {}
    for p in points:
        side = read_point(p.sidecar)
        mine[p.name] = is_mine(p.name, side=side)
        labels[p.name] = point_label(p, point_owner(side) or p.user, mine[p.name])
    default = default_point(points, mine)
    return {
        "key": _norm_path(path),
        "points": points,
        "labels": labels,
        "items": _point_items_for(points, labels),
        "warnings": {p.name: rollback_point_warning(context, path, p) for p in points},
        "default": default.name if default is not None else None,
    }


# The snapshot of the open Rollback dialog (the enum items callback gets no
# operator instance to read it from). Blender also needs the item strings
# to outlive the callback.
_rollback_dialog = {"snapshot": None, "items": []}


def _point_items(self, context):
    """Items of the point enum: the invoke snapshot's items (their numbers
    fixed) when it is for this source, plus any point that appeared since,
    numbered around them (so a script call after a dismissed dialog still
    finds it); else the folders. Values are the points' stable numbers,
    never list positions."""
    path = _rollback_path(context, self.source_path)
    items = []
    if path is not None:
        snap = _rollback_dialog["snapshot"]
        ours = snap is not None and snap["key"] == _norm_path(path)
        points = list(snap["points"]) if ours else []
        known = {p.name for p in points}
        points += [p for p in source_points(context, path) if p.name not in known]
        fixed = {it[0]: it[3] for it in snap["items"]} if ours else None
        items = _point_items_for(points, snap["labels"] if ours else {}, fixed)
    _rollback_dialog["items"] = items
    return items


class IOPS_OT_instance_edit_rollback_source(bpy.types.Operator):
    bl_idname = "iops.instance_edit_rollback_source"
    bl_label = "Rollback Source"
    bl_description = (
        "Copy a backup point taken by Commit (yours or a colleague's) over the "
        "source file and reload it (cannot be undone with Ctrl+Z)"
    )
    # Never replayed by undo/redo: it overwrites a file.
    bl_options = set()

    # Declared before ``point``: its items are the points of this file.
    source_path: bpy.props.StringProperty(
        name="Source",
        description="Library file to restore from one of its Commit backups",
    )
    point: bpy.props.EnumProperty(
        name="Backup",
        description="Backup point to restore (newest first); not set = your newest (else the newest)",
        items=_point_items,
        options={"SKIP_SAVE"},
    )

    @classmethod
    def poll(cls, context):
        # Operator properties are not available in poll: the path and the
        # point are checked in execute. Cached: poll runs on every redraw.
        if not cached_backup_points_for_libraries(context):
            cls.poll_message_set("No Commit backup exists for a library of this file")
            return False
        return True

    @classmethod
    def description(cls, context, properties):
        if properties.source_path:
            return (
                f"Restore {os.path.basename(properties.source_path)} from one of the backups "
                "taken by Commit (choose the point) and reload it (cannot be undone with Ctrl+Z)"
            )
        return cls.bl_description

    def prepare(self, context):
        """Invoke's work before the dialog: snapshot the points and preselect
        the newest own one (else the newest). Returns the source path, or
        None when there is nothing to choose from."""
        _rollback_dialog["snapshot"] = None
        path = _rollback_path(context, self.source_path)
        if path is None:
            return None
        snap = rollback_snapshot(context, path)
        if not snap["items"]:
            return None
        self._snapshot = snap
        _rollback_dialog["snapshot"] = snap
        self.point = snap["default"]
        return path

    def invoke(self, context, event):
        path = self.prepare(context)
        if path is None:
            return self.execute(context)  # reports why
        return context.window_manager.invoke_props_dialog(
            self, width=560, title=f"Rollback {os.path.basename(path)}", confirm_text="Rollback",
        )

    def cancel(self, context):
        _rollback_dialog["snapshot"] = None

    def draw(self, context):
        layout = self.layout
        snap = getattr(self, "_snapshot", None) or _rollback_dialog["snapshot"]
        path = _rollback_path(context, self.source_path)
        if path is None or snap is None:
            return
        name = os.path.basename(path)
        layout.label(text=path, icon="FILE_BLEND")
        layout.prop(self, "point", text="")
        warning = snap["warnings"].get(self.point)
        if warning:
            layout.label(text=warning, icon="ERROR")
        layout.label(text=f"Everything saved to {name} since then is replaced.", icon="INFO")
        op = layout.operator(IOPS_OT_instance_edit_backups_cleanup.bl_idname,
                             text="Clean Up Backups\u2026", icon="TRASH")
        op.scope = "LIBRARIES"
        op.source_path = path

    def execute(self, context):
        try:
            return self._execute(context)
        finally:
            _rollback_dialog["snapshot"] = None

    def _execute(self, context):
        path = _rollback_path(context, self.source_path)
        if path is None:
            self.report({"ERROR"}, "Name the library file to roll back")
            return {"CANCELLED"}
        points = source_points(context, path)
        if not points:
            self.report({"ERROR"}, f"No Commit backup for {os.path.basename(path)}")
            return {"CANCELLED"}
        # Not set: the newest own point (else the newest). Set: the
        # identifier the stored number maps to, which survives points
        # appearing or going while the dialog is open.
        name = self.point if self.properties.is_property_set("point") else default_point(points).name
        by_name = {p.name: p for p in points}
        if name not in by_name:
            self.report({"ERROR"}, f"Backup point {name or '?'} of {os.path.basename(path)} no longer exists")
            return {"CANCELLED"}
        point = by_name[name]
        if os.path.isfile(path):
            writable, reason, p4_lines = ensure_writable(context, path)
            for line in p4_lines:
                self.report({"WARNING"}, line)
            if not writable:
                self.report({"ERROR"}, reason)
                return {"CANCELLED"}
        try:
            with SourceLock(path, _worker_timeout(context)):
                _sweep_leftovers(path)
                replace_from_backup(point.blend, path)
        except CommitRefused as exc:
            self.report({"ERROR"}, f"Rollback refused: {exc}")
            return {"CANCELLED"}
        except OSError as exc:
            self.report({"ERROR"}, f"Rollback failed, {os.path.basename(path)} not changed: {exc}")
            return {"CANCELLED"}
        finally:
            invalidate_points_cache()
        # The source is the one from before the Commit that took this point:
        # that session, and those of every newer point (anyone's), may commit
        # anew. Caveat: rolling forward again (to a newer point) does not
        # restore the uuids cleared here, so a session revived by undo after
        # a roll-back-then-forward is not recognised as committed any more.
        update_point(point.sidecar, source_stat=file_stat(path), session_uuid=None)
        for newer in points[:points.index(point)]:
            update_point(newer.sidecar, session_uuid=None)
        libs = _source_libraries(path)
        failed = []
        for lib in libs:
            try:
                lib.reload()
            except (RuntimeError, ReferenceError) as exc:
                failed.append(f"{lib.name}: {exc}")
        if failed:
            self.report({"WARNING"}, "Restored, but reloading failed (reload by hand): " + "; ".join(failed))
        self.report(
            {"INFO"},
            f"Restored {os.path.basename(path)} from {point.blend} ({point_time(point.name)}); "
            f"{len(libs) - len(failed)} library datablock(s) reloaded",
        )
        return {"FINISHED"}


def _megabytes(size):
    return size / (1024 * 1024)


# The open Clean Up dialog: when it opened (UTC; later points are never
# candidates) and the plan it shows for its current settings. Execute
# deletes exactly that plan's files.
_cleanup_dialog = {"open": False, "opened": None, "key": None, "plan": None}


def _close_cleanup_dialog():
    _cleanup_dialog.update(open=False, opened=None, key=None, plan=None)


class IOPS_OT_instance_edit_backups_cleanup(bpy.types.Operator):
    bl_idname = "iops.instance_edit_backups_cleanup"
    bl_label = "Clean Up Backups"
    bl_description = (
        "Delete old Instance Edit Commit backup points (copy and sidecar) of this "
        "file's libraries or of the whole custom backup folder (cannot be undone)"
    )
    # Never replayed by undo/redo: it deletes files.
    bl_options = set()

    scope: bpy.props.EnumProperty(
        name="Scope",
        items=[
            ("LIBRARIES", "Libraries of this file", ""),
            ("CUSTOM_FOLDER", "Whole custom folder", ""),
        ],
        default="LIBRARIES",
    )
    older_than_days: bpy.props.IntProperty(
        name="Older Than (days)",
        description="Only points older than this many days are deleted; 0 = all",
        default=30,
        min=0,
    )
    only_mine: bpy.props.BoolProperty(
        name="Only My Backups",
        description="Only your own points are deleted, never other users'; "
                    "not set = the Prune Only My Backups preference",
        default=True,
        options={"SKIP_SAVE"},
    )
    source_path: bpy.props.StringProperty(
        name="Source",
        description="Only this library file's points (empty = every library / the whole folder)",
        options={"SKIP_SAVE"},
    )

    def _defaults(self, context):
        if not self.properties.is_property_set("only_mine"):
            self.only_mine = _prune_only_mine(context)

    def _key(self):
        return (self.scope, self.older_than_days, self.only_mine, self.source_path)

    def plan(self, context, not_after=None):
        return cleanup_candidates(context, self.scope, self.older_than_days, self.only_mine,
                                  self.source_path, not_after)

    def _shown_plan(self, context):
        """The open dialog's plan, recomputed only when its settings change
        (never for points taken after the dialog opened)."""
        key = self._key()
        if _cleanup_dialog["key"] != key or _cleanup_dialog["plan"] is None:
            _cleanup_dialog.update(key=key, plan=self.plan(context, _cleanup_dialog["opened"]))
        return _cleanup_dialog["plan"]

    def invoke(self, context, event):
        self._defaults(context)
        _close_cleanup_dialog()
        _cleanup_dialog.update(open=True, opened=datetime.datetime.now(datetime.timezone.utc))
        self._shown_plan(context)
        return context.window_manager.invoke_props_dialog(
            self, width=460, title="Clean Up Backups", confirm_text="Delete",
        )

    def cancel(self, context):
        _close_cleanup_dialog()

    def draw(self, context):
        layout = self.layout
        col = layout.column()
        col.use_property_split = True
        col.use_property_decorate = False
        if self.source_path:
            col.label(text=f"Only backups of {os.path.basename(self.source_path)}", icon="FILE_BLEND")
        col.prop(self, "scope")
        col.prop(self, "older_than_days")
        col.prop(self, "only_mine")
        if not _cleanup_dialog["open"]:
            return
        plan = self._shown_plan(context)
        layout.label(
            text=f"{len(plan.points)} backup point(s), {len(plan.files)} file(s), "
                 f"{_megabytes(plan.bytes):.1f} MB will be deleted",
            icon="TRASH" if plan.points else "INFO",
        )

    def execute(self, context):
        self._defaults(context)
        try:
            if _cleanup_dialog["open"]:
                plan = self._shown_plan(context)  # exactly what the dialog showed
            else:  # scripted: nothing taken from now on
                plan = self.plan(context, datetime.datetime.now(datetime.timezone.utc))
            deleted, freed, failed, skipped, refusals = run_cleanup(context, plan)
        finally:
            _close_cleanup_dialog()
        for line in dict.fromkeys(refusals):
            self.report({"WARNING"}, f"Skipped: {line}")
        problems = []
        if failed:
            problems.append(f"{failed} file(s) could not be deleted")
        if skipped:
            problems.append(f"{skipped} file(s) skipped (library locked)")
        self.report(
            {"WARNING"} if problems else {"INFO"},
            f"Deleted {deleted} file(s) of {len(plan.points)} backup point(s) ({_megabytes(freed):.1f} MB)"
            + ("; " + "; ".join(problems) if problems else ""),
        )
        return {"FINISHED"}
