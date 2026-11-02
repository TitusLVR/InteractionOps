"""Instance Edit merge worker: writes an edited collection back into its
library file.

Standalone script for a background Blender with the SOURCE file open:

    blender --background --factory-startup --disable-autoexec <source.blend>
        --python instance_edit_merge_worker.py -- <temp.json> <plan|write> <result.json>

It never imports the addon. ``temp.json`` (written by Commit):
``{"temp_blend", "source_coll_name", "copy_coll_name",
"owned": [{"index", "id_type", "source_name"}],
"update_shared": [[id_type, source_name], ...], "expected_plan": {...} | null}``.

Both modes run the whole merge in memory (append the copy, match the tagged
IDs, replace / keep / add, membership, relink, cleanup) so they compute the
same plan; only ``write`` saves, exactly once, at the very end, and only
when the plan equals ``expected_plan`` (the dry run the user confirmed). Any
exception leaves the source file untouched: ``result.json`` gets
``ok: false`` with the traceback and the process exits 1.

Sharing propagates: an owned source ID is shared when a user is outside
``C``'s subtree or is itself shared. Appended IDs left without users are
removed and reported as ``discarded``. Per-view-layer state of ``C``'s layer
collections and object bases is recorded before and re-applied after.

Matching key: the editing file tags every owned ID with
``id["iops_commit"] = <row index>``; names are never matched. An appended
collection-instancing object may also carry ``iops_commit_instance`` = the
name of a collection of the source file it instanced through a link: an
append into the source drops such self-links silently, the worker restores
them from the tag.
"""

import json
import os
import sys
import traceback

import bpy

TAG = "iops_commit"
INSTANCE_TAG = "iops_commit_instance"
# bpy.data collections that are not appended content: Library datablocks and
# the all-IDs view.
_NOT_CONTENT = {"libraries", "all_ids"}
# Shape keys belong to their mesh / curve / lattice and travel with it; their
# names ("Key", "Key.001") say nothing about which owner they belong to, so
# they are never matched against the source.
_FOLLOW_OWNER = {"shape_keys"}
_IMAGE_SOURCES = {"FILE", "SEQUENCE", "MOVIE", "TILED"}
# Appended ID types whose file path is made relative to the source, and the
# property holding it (filepath_raw: images must not reload). Libraries are
# handled with the temp Library.
_PATH_PROPS = {"images": "filepath_raw", "sounds": "filepath", "movieclips": "filepath",
               "fonts": "filepath", "volumes": "filepath", "cache_files": "filepath",
               "texts": "filepath"}
_ASSET_FIELDS = ("catalog_id", "description", "author", "copyright", "license")
_LAYER_FLAGS = ("exclude", "hide_viewport", "holdout", "indirect_only")
_WALK_LIMIT = 200000


# mirrors utils/instance_edit_core.merge_plan
def merge_plan(owned_rows, tagged, untagged_added, existing, users_outside,
               update_shared):
    """Plan a linked write-back merge as sorted ``(id_type, name)`` lists."""
    replaced, added, kept, shared = [], [], [], []
    for row in owned_rows:
        key = (row["id_type"], row["source_name"])
        if row["index"] not in tagged:
            continue
        if key not in existing:
            added.append(key)
            continue
        is_shared = key in users_outside
        if is_shared:
            shared.append(key)
        if is_shared and key not in update_shared:
            kept.append(key)
        else:
            replaced.append(key)
    added.extend(untagged_added)
    return {"replaced": sorted(replaced), "added": sorted(added),
            "kept": sorted(kept), "shared": sorted(shared),
            "unlinked": [], "deleted": [], "discarded": []}


# mirrors utils/instance_edit_core.plans_match
PLAN_KEYS = ("replaced", "added", "kept", "unlinked", "deleted", "discarded")


def plans_match(a, b):
    """Same sets of ``(id_type, name)`` per plan list (JSON lists accepted)."""
    return all({tuple(x) for x in a[k]} == {tuple(x) for x in b[k]} for k in PLAN_KEYS)


# mirrors utils/instance_edit_core.newer_blender
def newer_blender(source_version, running_version):
    """Whether a file saved by ``source_version`` comes from a newer Blender
    than ``running_version`` (major/minor compared, the patch ignored)."""
    if not source_version or not running_version:
        return False
    return tuple(int(v) for v in source_version[:2]) > tuple(int(v) for v in running_version[:2])


# --- ID helpers -----------------------------------------------------------------

def _id_attrs():
    """Names of the ``bpy.data`` collections that hold content IDs."""
    out = []
    for attr in dir(bpy.data):
        if attr.startswith("_") or attr in _NOT_CONTENT:
            continue
        value = getattr(bpy.data, attr, None)
        if not isinstance(value, bpy.types.bpy_prop_collection):
            continue
        prop = bpy.data.bl_rna.properties.get(attr)
        fixed = getattr(prop, "fixed_type", None)
        if fixed is None or fixed.identifier == "ID":
            continue
        cls = getattr(bpy.types, fixed.identifier, None)
        if cls is None or not issubclass(cls, bpy.types.ID):
            continue
        out.append(attr)
    return out


def _has_prop(id_, name):
    try:
        return name in id_.keys()
    except TypeError:
        return False


def _local(attr, name):
    return getattr(bpy.data, attr).get((name, None))


def _live(pairs):
    """``(attr, ID)`` pairs whose ID still exists. Checked by pointer, never
    through a possibly stale wrapper; nothing allocates IDs after the first
    removal, so a freed pointer cannot come back."""
    current = {}
    for attr in {a for a, _i in pairs}:
        current[attr] = {i.as_pointer() for i in getattr(bpy.data, attr)}
    out = []
    for attr, id_ in pairs:
        try:
            ptr = id_.as_pointer()
        except ReferenceError:  # removed through this very wrapper
            continue
        if ptr in current[attr]:
            out.append((attr, id_))
    return out


def _is_id(value):
    return isinstance(value, bpy.types.ID)


def _pointer_props(struct):
    """ID values of ``struct``'s pointer properties and ID custom props."""
    out = []
    for prop in struct.bl_rna.properties:
        if prop.type == "POINTER":
            value = getattr(struct, prop.identifier, None)
            if _is_id(value):
                out.append(value)
    try:
        out.extend(v for v in struct.values() if _is_id(v))
    except TypeError:
        pass
    return out


def _tree_refs(tree, seen_trees):
    """Images and node groups used by a node tree (embedded or not)."""
    if tree is None or tree.as_pointer() in seen_trees:
        return []
    seen_trees.add(tree.as_pointer())
    out = []
    for node in tree.nodes:
        for attr in ("image", "node_tree"):
            value = getattr(node, attr, None)
            if _is_id(value):
                out.append(value)
    return out


def _refs(id_, seen_trees):
    """IDs a subtree member uses along the paths the subtree walk follows."""
    out = []
    if isinstance(id_, bpy.types.Collection):
        out.extend(id_.children)
        out.extend(id_.objects)
        return out
    if isinstance(id_, bpy.types.Object):
        if id_.data is not None:
            out.append(id_.data)
        out.extend(s.material for s in id_.material_slots if s.material is not None)
        for mod in id_.modifiers:
            out.extend(_pointer_props(mod))
        for psys in id_.particle_systems:
            out.append(psys.settings)
        return out
    out.extend(m for m in getattr(id_, "materials", ()) or () if m is not None)
    keys = getattr(id_, "shape_keys", None)
    if _is_id(keys):
        out.append(keys)
    if isinstance(id_, bpy.types.NodeTree):
        out.extend(_tree_refs(id_, seen_trees))
    else:
        out.extend(_tree_refs(getattr(id_, "node_tree", None), seen_trees))
    return out


def subtree_ids(coll):
    """Pointers of the IDs of ``coll``'s subtree: the collection, its child
    collections, their objects and the data those use (object data,
    materials, modifier targets, particle settings, shape keys, node groups
    and images of their node trees). A bounded walk; anything it does not
    follow counts as outside, i.e. shared (conservative)."""
    seen = {coll.as_pointer()}
    stack = [coll]
    seen_trees = set()
    while stack and len(seen) < _WALK_LIMIT:
        for ref in _refs(stack.pop(), seen_trees):
            ptr = ref.as_pointer()
            if ptr not in seen:
                seen.add(ptr)
                stack.append(ref)
    return seen


def _scene_really_uses(scene, id_):
    """Whether ``scene`` uses the object / collection ``id_`` other than
    through its view layers (bases, layer collections), which make every
    object and collection of the scene's hierarchy list the scene as a user
    in ``bpy.data.user_map``. Other ID types: always."""
    if isinstance(id_, bpy.types.Collection):
        if any(ch == id_ for ch in scene.collection.children):
            return True
        rbw = scene.rigidbody_world
        return rbw is not None and (rbw.collection == id_ or rbw.constraints == id_)
    if not isinstance(id_, bpy.types.Object):
        return True
    if scene.camera == id_ or any(o == id_ for o in scene.collection.objects):
        return True
    if any(m.camera == id_ for m in scene.timeline_markers):
        return True
    editor = scene.sequence_editor
    if editor is not None:
        strips = getattr(editor, "strips_all", None) or getattr(editor, "sequences_all", ())
        if any(getattr(s, "scene_camera", None) == id_ for s in strips):
            return True
    return False


def _outside_users(old, users, subtree):
    out = []
    for user in users:
        if user == old or user.as_pointer() in subtree:
            continue
        if isinstance(user, bpy.types.Scene) and not _scene_really_uses(user, old):
            continue
        out.append(user)
    return out


def _walk_layers(lc, path=()):
    path = path + (lc.collection.name,)
    yield path, lc
    for child in lc.children:
        yield from _walk_layers(child, path)


def record_view_state(coll):
    """Per scene / view layer state the merge would reset: the flags of every
    layer collection of ``coll`` and its child collections (keyed by the
    path of collection names from the view layer root), and the base hide
    state of the subtree's objects (keyed by object name).

    ``exclude`` of a child reads True while its parent is excluded, whether
    or not the child is excluded on its own (Blender remembers that and
    restores it when the parent is re-enabled). To read the child's own
    state, an excluded recorded layer collection is temporarily re-enabled
    (parents are walked first); ``restore_view_state`` puts it back. Bases
    are read before that, as they exist only in enabled collections."""
    colls = {coll.as_pointer()} | {c.as_pointer() for c in coll.children_recursive}
    objects = list(coll.all_objects)
    layers, bases = {}, {}
    for scene in bpy.data.scenes:
        if scene.library is not None:
            continue
        for vl in scene.view_layers:
            for obj in objects:
                try:
                    bases[(scene.name, vl.name, obj.name)] = obj.hide_get(view_layer=vl)
                except RuntimeError:
                    pass  # no base in this view layer (excluded)
            for path, lc in _walk_layers(vl.layer_collection):
                if lc.collection.as_pointer() not in colls:
                    continue
                layers[(scene.name, vl.name, path)] = {f: getattr(lc, f) for f in _LAYER_FLAGS}
                if lc.exclude:
                    lc.exclude = False  # children now show their own state
    return layers, bases


def restore_view_state(layers, bases):
    """Re-apply ``record_view_state``: bases first (excluding a layer
    collection removes its bases), then the layer collection flags,
    children first, so that excluding a parent afterwards keeps each
    child's own exclusion exactly as Blender had it."""
    for (scene_name, vl_name, obj_name), hidden in bases.items():
        scene = bpy.data.scenes.get((scene_name, None))
        vl = scene.view_layers.get(vl_name) if scene is not None else None
        obj = _local("objects", obj_name)
        if vl is None or obj is None:
            continue
        try:
            if obj.hide_get(view_layer=vl) != hidden:
                obj.hide_set(hidden, view_layer=vl)
        except RuntimeError:
            pass  # the object has no base there any more
    for scene in bpy.data.scenes:
        if scene.library is not None:
            continue
        for vl in scene.view_layers:
            for path, lc in reversed(list(_walk_layers(vl.layer_collection))):
                flags = layers.get((scene.name, vl.name, path))
                for flag, value in (flags or {}).items():
                    if getattr(lc, flag) != value:
                        setattr(lc, flag, value)


def copy_asset_data(old, new):
    """Give ``new`` the asset metadata of ``old`` when ``new`` has none.

    Start appends a collection that is also linked in the editing file, and
    such an append drops the asset mark of every copy; replacing the source
    original with that copy would silently un-mark the asset. Copies the
    mark, catalog, description, author, copyright, license, tags and the
    asset's own custom properties. Returns True when it copied."""
    src = old.asset_data
    if src is None or new.asset_data is not None:
        return False
    new.asset_mark()
    dst = new.asset_data
    if dst is None:
        raise RuntimeError("cannot mark %s '%s' as an asset" % (type(new).__name__, new.name))
    for field in _ASSET_FIELDS:
        setattr(dst, field, getattr(src, field))
    for tag in src.tags:
        dst.tags.new(tag.name, skip_if_exists=True)
    for key in src.keys():
        dst[key] = src[key]
    return True


def _same_type(a, b):
    if a.id_type != b.id_type or type(a).__name__ != type(b).__name__:
        raise TypeError("type mismatch: %s '%s' vs %s '%s'" % (
            type(a).__name__, a.name, type(b).__name__, b.name))


def _norm(path):
    return os.path.normcase(os.path.normpath(os.path.abspath(path)))


def _relative(path, start):
    absolute = bpy.path.abspath(path)
    try:
        return bpy.path.relpath(absolute, start=start)
    except ValueError:  # other drive: keep it absolute
        return path


# --- merge --------------------------------------------------------------------

def _load_rows(cfg, attrs):
    rows, indexes, keys = [], set(), set()
    for raw in cfg["owned"]:
        row = {"index": int(raw["index"]), "id_type": str(raw["id_type"]),
               "source_name": str(raw["source_name"])}
        if row["id_type"] not in attrs:
            raise ValueError("unknown id_type %r" % row["id_type"])
        key = (row["id_type"], row["source_name"])
        if row["index"] in indexes:
            raise ValueError("duplicate owned index %d" % row["index"])
        if key in keys and row["id_type"] not in _FOLLOW_OWNER:
            raise ValueError("duplicate owned row %r" % (key,))
        indexes.add(row["index"])
        keys.add(key)
        rows.append(row)
    return rows


def merge(cfg):
    """Run the merge in the open source file; return the plan dict."""
    attrs = _id_attrs()
    source_dir = os.path.dirname(bpy.data.filepath)
    rows = _load_rows(cfg, attrs)
    by_index = {r["index"]: r for r in rows}
    ruled = [r for r in rows if r["id_type"] not in _FOLLOW_OWNER]
    update_shared = {(str(t), str(n)) for t, n in cfg.get("update_shared") or ()}
    root_key = ("collections", cfg["source_coll_name"])

    # 1. The target collection, its parents and its subtree.
    coll = _local("collections", cfg["source_coll_name"])
    if coll is None:
        raise KeyError("no local collection '%s' in the source" % cfg["source_coll_name"])
    parent_colls = [c for c in bpy.data.collections if any(ch == coll for ch in c.children)]
    parent_scenes = [s for s in bpy.data.scenes if any(ch == coll for ch in s.collection.children)]
    subtree = subtree_ids(coll)
    old_objects = [(o.as_pointer(), o.name) for o in coll.all_objects]
    old_colls = [(c.as_pointer(), c.name) for c in coll.children_recursive]

    # Source originals of the owned rows and their users outside the subtree.
    olds = {}
    for row in ruled:
        old = _local(row["id_type"], row["source_name"])
        if old is not None:
            olds[(row["id_type"], row["source_name"])] = old
    if olds.get(root_key) != coll:
        raise ValueError("owned rows do not include the collection '%s'" % root_key[1])
    # Shared: a user outside the subtree, or a user that is itself shared
    # (to a fixed point: the mesh of a kept object is kept too).
    user_map = bpy.data.user_map(subset=list(olds.values()))
    shared_by = {}
    for key, old in olds.items():
        if key == root_key:
            continue  # the edited collection itself is never shared
        outside = _outside_users(old, user_map.get(old, ()), subtree)
        if outside:
            shared_by[key] = outside
    direct_shared = set(shared_by)
    changed = True
    while changed:
        changed = False
        shared_ptrs = {olds[k].as_pointer() for k in shared_by}
        for key, old in olds.items():
            if key == root_key or key in shared_by:
                continue
            via = [u for u in user_map.get(old, ()) if u.as_pointer() in shared_ptrs]
            if via:
                shared_by[key] = via
                changed = True
    users_outside = set(shared_by)
    shared_users = {"%s:%s" % k: sorted({u.name for u in v}) for k, v in shared_by.items()}
    # A ticked ID pulls the dependencies shared only through it: an ID shared
    # by propagation alone is updated once every shared ID using it is
    # (to a fixed point). An ID with a direct outside user needs its own tick.
    shared_key_of = {olds[k].as_pointer(): k for k in shared_by}
    sources = {}
    for key in shared_by:
        if key in direct_shared:
            continue
        old = olds[key]
        sources[key] = {shared_key_of[u.as_pointer()] for u in user_map.get(old, ())
                        if u != old and u.as_pointer() in shared_key_of}
    effective_update = set(update_shared)
    changed = True
    while changed:
        changed = False
        for key, srcs in sources.items():
            if key not in effective_update and srcs and srcs <= effective_update:
                effective_update.add(key)
                changed = True
    # Empty collection instancers of the source may legitimately stay empty.
    empty_instancers = {key for key, old in olds.items()
                        if key[0] == "objects" and old.instance_collection is None}
    view_state = record_view_state(coll)

    # 2. Append the copy.
    temp_blend = cfg["temp_blend"]
    if not os.path.isfile(temp_blend):
        raise FileNotFoundError(temp_blend)
    before = {(a, i.as_pointer()) for a in attrs for i in getattr(bpy.data, a)}
    libs_before = {lib.as_pointer() for lib in bpy.data.libraries}
    with bpy.data.libraries.load(temp_blend, link=False) as (data_from, data_to):
        if cfg["copy_coll_name"] not in data_from.collections:
            raise KeyError("no collection '%s' in %s" % (cfg["copy_coll_name"], temp_blend))
        data_to.collections = [cfg["copy_coll_name"]]
    new_coll = data_to.collections[0]
    if new_coll is None:
        raise RuntimeError("could not append '%s'" % cfg["copy_coll_name"])
    appended = [(a, i) for a in attrs for i in getattr(bpy.data, a)
                if i.library is None and (a, i.as_pointer()) not in before]

    # 3. Matching pass: tags -> rows.
    tagged, untagged = {}, []
    for attr, id_ in appended:
        if not _has_prop(id_, TAG):
            untagged.append((attr, id_))
            continue
        index = int(id_[TAG])
        del id_[TAG]
        row = by_index.get(index)
        if row is None:
            raise ValueError("%s '%s' carries unknown row index %d" % (attr, id_.name, index))
        if row["id_type"] != attr:
            raise TypeError("row %d is %s but the tagged ID is in %s" % (index, row["id_type"], attr))
        if index in tagged:
            raise ValueError("row index %d tagged twice" % index)
        tagged[index] = (attr, id_)
    root_row = next(r for r in ruled if (r["id_type"], r["source_name"]) == root_key)
    if tagged.get(root_row["index"], (None, None))[1] != new_coll:
        raise ValueError("the appended copy is not the tagged collection row")

    for attr, id_ in appended:
        if attr == "objects" and _has_prop(id_, INSTANCE_TAG):
            name = str(id_[INSTANCE_TAG])
            del id_[INSTANCE_TAG]
            if id_.instance_collection is None:
                target = _local("collections", name)
                if target is None or (("collections", target.as_pointer()) not in before):
                    raise KeyError("'%s' instances '%s', not a collection of the source"
                                   % (id_.name, name))
                id_.instance_collection = target
    # An append into the source drops links to the source itself; any
    # collection instancer left empty lost its collection that way, unless
    # it is the copy of a source instancer that was empty already.
    row_key_of = {id_.as_pointer(): (a, by_index[i]["source_name"])
                  for i, (a, id_) in tagged.items()}
    lost = sorted(i.name for a, i in appended if a == "objects"
                  and i.instance_type == "COLLECTION" and i.instance_collection is None
                  and row_key_of.get(i.as_pointer()) not in empty_instancers)
    if lost:
        raise RuntimeError("collection instancers without a collection after the append "
                           "(links to the source itself, not restorable): %s; not saving"
                           % ", ".join(lost))

    plan = merge_plan(ruled, {i: (a, id_.name) for i, (a, id_) in tagged.items()}, [],
                      set(olds), users_outside, effective_update)
    replaced, kept, added = set(plan["replaced"]), set(plan["kept"]), set(plan["added"])
    plan["pulled"] = sorted(k for k in effective_update - update_shared if k in replaced)
    if root_key not in replaced:
        raise ValueError("the collection '%s' would not be replaced" % root_key[1])

    renames = []
    for row in ruled:
        if row["index"] not in tagged:
            continue
        attr, new = tagged[row["index"]]
        key = (attr, row["source_name"])
        if key in replaced:
            old = olds[key]
            _same_type(old, new)
            copy_asset_data(old, new)  # before the remap: old is removed
            old.user_remap(new)
            getattr(bpy.data, attr).remove(old)
            renames.append((new, row["source_name"]))
        elif key in kept:
            old = olds[key]
            _same_type(old, new)
            new.user_remap(old)
            getattr(bpy.data, attr).remove(new)
        elif key in added:
            renames.append((new, row["source_name"]))
        else:
            raise RuntimeError("row %r has no plan entry" % (key,))
    # Two steps so a not-yet-renamed copy never holds another row's name.
    for n, (new, _name) in enumerate(renames):
        new.name = "iops_commit_rename_%d" % n
    for new, name in renames:
        new.name = name
        if new.name != name:
            raise RuntimeError("cannot name %s '%s': the name is taken" % (type(new).__name__, name))

    # 5. Membership.
    new_colls = {new_coll.as_pointer()} | {c.as_pointer() for c in new_coll.children_recursive}
    new_objects = {o.as_pointer() for o in new_coll.all_objects}
    unlinked, deleted = [], []
    for attr, old_set, now_set in (("collections", old_colls, new_colls),
                                   ("objects", old_objects, new_objects)):
        current = {i.as_pointer(): i for i in getattr(bpy.data, attr)}
        for ptr, _name in old_set:
            id_ = current.get(ptr)
            if id_ is None or ptr in now_set:
                continue
            unlinked.append((attr, id_.name))
            if id_.users == 0:
                deleted.append((attr, id_.name))
                getattr(bpy.data, attr).remove(id_)
    plan["unlinked"] = sorted(unlinked)
    plan["deleted"] = sorted(deleted)

    # 6. Relink under the recorded parents (the remap normally did it).
    for parent in parent_colls:
        if not any(ch == new_coll for ch in parent.children):
            parent.children.link(new_coll)
    for scene in parent_scenes:
        if not any(ch == new_coll for ch in scene.collection.children):
            scene.collection.children.link(new_coll)

    # Appended IDs left without users (e.g. objects added inside a kept
    # shared child collection) are reported and removed, never dropped
    # silently; their own dependencies follow.
    discarded = []
    while True:
        zero = [(a, i) for a, i in _live(appended) if i.users == 0]
        if not zero:
            break
        discarded.extend((a, i.name) for a, i in zero if a not in _FOLLOW_OWNER)
        bpy.data.batch_remove([i for _a, i in zero])
    plan["discarded"] = sorted(discarded)
    # Untagged appended IDs: created during the session, kept with their names.
    gone = set(discarded)
    plan["added"] = sorted([k for k in plan["added"] if k not in gone]
                           + [(a, i.name) for a, i in _live(untagged) if a not in _FOLLOW_OWNER])

    restore_view_state(*view_state)

    # 4. Drop the temp blend's Library; new third libraries go relative.
    temp_key = _norm(temp_blend)
    for lib in [lib for lib in bpy.data.libraries if lib.as_pointer() not in libs_before]:
        if _norm(bpy.path.abspath(lib.filepath)) == temp_key:
            if len(lib.users_id):
                raise RuntimeError("IDs still linked from the temp blend: %s"
                                   % ", ".join(i.name for i in lib.users_id))
            bpy.data.libraries.remove(lib)
        else:
            lib.filepath = _relative(lib.filepath, source_dir)

    # 7. Relative paths on appended IDs only; pre-existing ones untouched.
    for attr, id_ in _live(appended):
        prop = _PATH_PROPS.get(attr)
        if prop is None or (attr == "images" and id_.source not in _IMAGE_SOURCES):
            continue
        path = getattr(id_, prop)
        if path and not path.startswith(("//", "<")):
            setattr(id_, prop, _relative(path, source_dir))

    for attr in attrs + ["libraries"]:
        for id_ in getattr(bpy.data, attr):
            if _has_prop(id_, TAG) or _has_prop(id_, INSTANCE_TAG):
                raise RuntimeError("%s '%s' still carries a commit tag" % (attr, id_.name))
    for lib in bpy.data.libraries:
        if _norm(bpy.path.abspath(lib.filepath)) == temp_key:
            raise RuntimeError("the temp blend is still a library of the source")

    plan["shared_users"] = shared_users
    return plan


def _compressed(path):
    with open(path, "rb") as fh:
        return not fh.read(7).startswith(b"BLENDER")


def _args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    if len(argv) != 3 or argv[1] not in ("plan", "write"):
        raise SystemExit("usage: ... -- <temp.json> <plan|write> <result.json>")
    return argv


def _stat(path):
    st = os.stat(path)
    return (st.st_mtime_ns, st.st_size)


def main():
    temp_json, mode, result_json = _args()
    result = {"ok": False, "mode": mode, "plan": None,
              "source_blender_version": list(bpy.data.version), "error": None}
    try:
        source = bpy.data.filepath
        if not source:
            raise RuntimeError("no source file is open")
        loaded_stat = _stat(source)  # right after Blender loaded it
        with open(temp_json, encoding="utf-8") as fh:
            cfg = json.load(fh)
        compressed = _compressed(source)
        plan = merge(cfg)
        result["plan"] = plan
        if mode == "write":
            expected = cfg.get("expected_plan")
            if not expected:
                raise ValueError("write mode needs the confirmed expected_plan")
            if not plans_match(plan, expected):
                raise ValueError("plan differs from the confirmed dry run:\n%s\n!=\n%s"
                                 % (json.dumps(plan, sort_keys=True), json.dumps(expected, sort_keys=True)))
            if newer_blender(bpy.data.version, bpy.app.version_file):
                raise RuntimeError("the source was saved by Blender %s, newer than this %s: "
                                   "saving would down-version it; not saving"
                                   % (".".join(map(str, bpy.data.version[:2])),
                                      ".".join(map(str, bpy.app.version_file[:2]))))
            # Another process may have written the source while the merge ran.
            if _stat(source) != loaded_stat:
                raise RuntimeError("the source changed on disk while the merge ran; not saving")
            bpy.context.preferences.filepaths.save_version = 0
            done = bpy.ops.wm.save_mainfile(filepath=source, compress=compressed)
            if "FINISHED" not in done:
                raise RuntimeError("save_mainfile returned %s" % sorted(done))
        result["ok"] = True
    except Exception:
        result["ok"] = False
        result["error"] = traceback.format_exc()
    try:
        with open(result_json, "w", encoding="utf-8") as fh:
            json.dump(result, fh, indent=1)
    except OSError:
        traceback.print_exc()
        result["ok"] = False
    print("IOPS_MERGE_WORKER %s ok=%s" % (mode, result["ok"]))
    if result["error"]:
        print(result["error"])
    sys.stdout.flush()
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
