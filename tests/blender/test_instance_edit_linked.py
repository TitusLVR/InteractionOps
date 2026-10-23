"""Headless integration test of Instance Edit on linked collections
(iops.instance_edit_start linked branch, iops.instance_edit_commit /
cancel / rollback_source). Run from the repo root via:

    blender --background --factory-startup --python-exit-code 1 --python tests/blender/test_instance_edit_linked.py

Recommended: point BLENDER_USER_SCRIPTS and BLENDER_USER_CONFIG at scratch
directories for the run; enabling the addon saves its preferences file
under the user scripts folder on quit.

The script enables the addon itself: it puts the parent of this repo on
sys.path and enables it as module "InteractionOps", so the repo folder must
be named InteractionOps. Commit spawns the merge worker through
``bpy.app.binary_path`` (this same Blender).

Every test builds its own files in a fresh directory below one run
directory (under ``$IOPS_TEST_TMP`` when set, else the system temp dir),
removed after the test; the run directory is removed at the end. Each
test points the *backup folder* preference at its own directory below the
run directory too and starts in the *Custom folder* backup location
(restored at the end), so Commit never writes into the real Blender config
folder; the next-to-source tests switch to *Next to source*, whose
``.iopsbackup`` folder lands in the test's own directory:

- ``src.blend`` (the source library): collection ``C`` (``Cube`` with
  ``CubeMesh`` + ``SharedMat`` (red), ``Child`` parented to ``Cube``,
  ``DInst`` instancing the same-file collection ``D``), collection
  ``Other`` (``OtherObj`` whose mesh also uses ``SharedMat``), collection
  ``D`` (``DCube``),
- ``lib3.blend`` (a third library, some tests only): object ``L3Obj``,
  linked into ``C``,
- with ``assets``: ``C`` asset-marked (catalog, description, author, tag,
  an asset custom property) and ``Cube`` carrying a Mesh Cache modifier
  reading ``//caches/cube.pc2``.

The editing file is a fresh empty home file (never saved) linking ``C``
with two instancers ``Inst`` and ``Inst2`` and a local Empty named
``Cube`` (so the appended copy's ``Cube`` becomes ``Cube.001``).

Commit is driven through ``commit_linked`` after the dry run its invoke
does, so the plan dialog is skipped. Prints PASS <name> / FAIL <name> plus
the traceback per test and exits with code 1 if any test failed.

Not collected by pytest (tests/conftest.py ignores tests/blender).
"""
import datetime
import json
import math
import os
import platform
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import traceback
import types

import bpy
from mathutils import Euler, Matrix, Vector

ADDON = "InteractionOps"
EPS = 1e-4
RED = (1.0, 0.0, 0.0, 1.0)
GREEN = (0.0, 1.0, 0.0, 1.0)
TAGS = ("iops_commit", "iops_commit_instance")
TMP_ROOT = os.environ.get("IOPS_TEST_TMP") or None
CUBE_LOC = (1.0, 2.0, 0.5)
CUBE_ROT = (math.radians(30), 0.0, 0.0)
CUBE_SCALE = (1.5, 1.5, 1.5)
CATALOG = "c8b7f6a4-2f27-4b7b-9c1e-1a2b3c4d5e6f"
CUBE_WORLD = Matrix.LocRotScale(Vector(CUBE_LOC), Matrix.Rotation(CUBE_ROT[0], 3, "X"), Vector(CUBE_SCALE))
# Owned set of a session on C: D and what only it uses stay linked.
EXPECTED_OWNED = {
    ("collections", "C"), ("objects", "Cube"), ("objects", "Child"), ("objects", "DInst"),
    ("meshes", "CubeMesh"), ("meshes", "ChildMesh"), ("materials", "SharedMat"),
}

# Bound by enable_addon(): the addon modules under test.
iel = active_session = get_frame = source_stat = core = None
RUN_DIR = None


def enable_addon():
    global iel, active_session, get_frame, source_stat, core
    repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    repo_parent = os.path.dirname(repo_root)
    if repo_parent not in sys.path:
        sys.path.insert(0, repo_parent)
    bpy.ops.preferences.addon_enable(module=ADDON)
    assert ADDON in bpy.context.preferences.addons, "addon not enabled"
    import InteractionOps

    # The enabled addon must be this checkout, not another install.
    loaded = os.path.dirname(os.path.abspath(InteractionOps.__file__))
    assert os.path.samefile(loaded, repo_root), "addon loaded from %s" % loaded
    from InteractionOps.operators import instance_edit_linked
    from InteractionOps.operators import instance_edit_state
    from InteractionOps.utils import instance_edit_core

    iel = instance_edit_linked
    active_session = instance_edit_state.active_session
    get_frame = instance_edit_state.get_frame
    source_stat = instance_edit_state.source_stat
    core = instance_edit_core


def addon_prefs():
    return bpy.context.preferences.addons[ADDON].preferences


# --- fixture -------------------------------------------------------------------

class Fixture:
    def __init__(self):
        self.dir = tempfile.mkdtemp(prefix="t_", dir=RUN_DIR)
        self.src = os.path.join(self.dir, "src.blend")
        self.lib3 = os.path.join(self.dir, "lib3.blend")
        self.lock = self.src + ".iops_lock"
        self.files = {"src.blend"}
        # Commit backups go here (custom folder mode), never into the
        # Blender config folder; next-to-source tests switch the mode.
        self.backups = tempfile.mkdtemp(prefix="bak_", dir=RUN_DIR)
        self.ibkp = os.path.join(self.dir, core.BACKUP_SUBFOLDER)
        prefs = addon_prefs()
        prefs.iops_instance_edit_backup_dir = self.backups
        prefs.iops_instance_edit_backup_location = "CUSTOM_FOLDER"
        prefs.iops_instance_edit_prune_only_mine = True
        prefs.iops_instance_edit_backup_count = 3


def build_source(fx, with_lib3=False, assets=False):
    """Write src.blend (and lib3.blend) into the fixture directory. Returns
    the channels of every object of C as saved."""
    bpy.ops.wm.read_homefile(use_empty=True)
    if with_lib3:
        l3 = bpy.data.objects.new("L3Obj", bpy.data.meshes.new("L3Mesh"))
        l3.location = (0.0, -2.0, 0.0)
        bpy.data.libraries.write(fx.lib3, {l3}, fake_user=True)
        fx.files.add("lib3.blend")
        bpy.ops.wm.read_homefile(use_empty=True)
    scene = bpy.context.scene
    C = bpy.data.collections.new("C")
    other = bpy.data.collections.new("Other")
    D = bpy.data.collections.new("D")
    if with_lib3:
        with bpy.data.libraries.load(fx.lib3, link=True) as (_df, dt):
            dt.objects = ["L3Obj"]
        C.objects.link(dt.objects[0])
    shared = bpy.data.materials.new("SharedMat")
    shared.diffuse_color = RED
    dmat = bpy.data.materials.new("DMat")
    cube_me = bpy.data.meshes.new("CubeMesh")
    cube_me.from_pydata([(0, 0, 0), (1, 0, 0), (0, 1, 0)], [], [(0, 1, 2)])
    cube_me.materials.append(shared)
    cube = bpy.data.objects.new("Cube", cube_me)
    cube.location = CUBE_LOC
    cube.rotation_euler = CUBE_ROT
    cube.scale = CUBE_SCALE
    child = bpy.data.objects.new("Child", bpy.data.meshes.new("ChildMesh"))
    child.parent = cube
    child.location = (0.0, 0.0, 2.0)
    child.rotation_mode = "ZXY"
    child.rotation_euler = (0.1, 0.2, 0.3)
    child.scale = (0.5, 0.75, 2.0)
    C.objects.link(cube)
    C.objects.link(child)
    if assets:
        mc = cube.modifiers.new("MC", "MESH_CACHE")
        mc.filepath = "//caches/cube.pc2"
        C.asset_mark()
        ad = C.asset_data
        ad.catalog_id = CATALOG
        ad.description = "coll desc"
        ad.author = "someone"
        ad.tags.new("tagA")
        ad["studio"] = {"lod": 2}
    o_me = bpy.data.meshes.new("OtherMesh")
    o_me.materials.append(shared)
    other.objects.link(bpy.data.objects.new("OtherObj", o_me))
    d_me = bpy.data.meshes.new("DMesh")
    d_me.materials.append(dmat)
    D.objects.link(bpy.data.objects.new("DCube", d_me))
    dinst = bpy.data.objects.new("DInst", None)
    dinst.instance_type = "COLLECTION"
    dinst.instance_collection = D
    dinst.location = (3.0, 0.0, 0.0)
    dinst.rotation_euler = (0.0, 0.0, math.radians(45))
    C.objects.link(dinst)
    for c in (C, other, D):
        scene.collection.children.link(c)
    saved = {o.name: channels(o) for o in C.all_objects}
    bpy.ops.wm.save_as_mainfile(filepath=fx.src)
    assert set(os.listdir(fx.dir)) == fx.files, os.listdir(fx.dir)
    return saved


def build_editing_file(fx):
    """Fresh empty file linking C from src.blend with instancers Inst
    (at (10,0,0), 90 deg about Z) and Inst2 (at (-10,0,0)). Returns them."""
    bpy.ops.wm.read_homefile(use_empty=True)
    scene = bpy.context.scene
    scene.collection.objects.link(bpy.data.objects.new("Cube", None))
    with bpy.data.libraries.load(fx.src, link=True) as (_df, dt):
        dt.collections = ["C"]
    C = dt.collections[0]
    assert C.library is not None
    insts = []
    for name, loc, rz in (("Inst", (10, 0, 0), 90), ("Inst2", (-10, 0, 0), 0)):
        e = bpy.data.objects.new(name, None)
        e.instance_type = "COLLECTION"
        e.instance_collection = C
        e.location = loc
        e.rotation_euler = (0, 0, math.radians(rz))
        scene.collection.objects.link(e)
        insts.append(e)
    bpy.context.view_layer.update()
    return insts


def start(fx, with_lib3=False, assets=False, prepare=None):
    """Source + editing file, then Start on Inst through the operator.
    ``prepare()`` runs in the editing file before Start. Returns (saved
    channels, Inst, Inst2, local IDs before Start)."""
    saved = build_source(fx, with_lib3, assets)
    inst, inst2 = build_editing_file(fx)
    if prepare is not None:
        prepare()
    before = local_ids()
    activate(inst)
    assert not bpy.ops.iops.instance_edit_commit.poll()
    assert not bpy.ops.iops.instance_edit_cancel.poll()
    assert bpy.ops.iops.instance_edit_start.poll()
    assert bpy.ops.iops.instance_edit_start() == {"FINISHED"}
    s = active_session(bpy.context.scene)
    assert s.kind == "LINKED", s.kind
    assert re.fullmatch(r"[0-9a-f]{32}", s.uuid), s.uuid
    assert stack_len() == 1
    assert bpy.ops.iops.instance_edit_commit.poll()
    assert bpy.ops.iops.instance_edit_cancel.poll()
    return saved, inst, inst2, before


# --- helpers -------------------------------------------------------------------

def channels(obj):
    """Transform channels, exactly as stored (float32 values as Python floats)."""
    return (obj.rotation_mode, tuple(obj.location), tuple(obj.rotation_euler), tuple(obj.scale))


def close(a, b, eps=EPS):
    return all(abs(a[i][j] - b[i][j]) <= eps for i in range(4) for j in range(4))


def vclose(a, b, eps=EPS):
    return len(a) == len(b) and all(abs(x - y) <= eps for x, y in zip(a, b))


def same_path(a, b):
    return os.path.normcase(os.path.normpath(a)) == os.path.normcase(os.path.normpath(b))


def stack_len():
    return len(bpy.context.scene.iops_instance_edit.sessions)


def activate(obj):
    vl = bpy.context.view_layer
    for o in vl.objects:
        o.select_set(False)
    obj.select_set(True)
    vl.objects.active = obj


def top():
    """The active session, fetched fresh (collection items move on pop)."""
    return active_session(bpy.context.scene)


def owned(s, id_type, name):
    return next(r.ref for r in s.owned if r.id_type == id_type and r.source_name == name)


def owned_set(s):
    return {(r.id_type, r.source_name) for r in s.owned}


def local_ids():
    out = set()
    for a in iel._id_attrs():
        for i in getattr(bpy.data, a):
            if i.library is None:
                out.add((a, i.name))
    return out


def no_tags():
    for a in iel._id_attrs() + ["libraries"]:
        for i in getattr(bpy.data, a):
            for t in TAGS:
                assert t not in i.keys(), (a, i.name, t)


def editing_state(s):
    return {o.name: (channels(o), o.parent, tuple(tuple(r) for r in o.matrix_basis))
            for o in s.copy_collection.all_objects}


def read(path):
    with open(path, "rb") as fh:
        return fh.read()


def listing(fx):
    return set(os.listdir(fx.dir))


EXT, SIDE = ".iopsbackup", ".iopsbackup.json"


def points(fx, folder=None):
    """Names of the backup points of src.blend (both locations), newest
    first; all of them in ``folder`` (default: the custom backup folder)."""
    pts = iel.source_points(bpy.context, fx.src)
    folder = folder or fx.backups
    assert all(same_path(p.folder, folder) for p in pts), [(p.name, p.folder) for p in pts]
    return [p.name for p in pts]


def point_files(fx, point, folder=None):
    return iel.point_files(folder or fx.backups, point)


def sidecar(fx, point, folder=None):
    return iel.read_point(point_files(fx, point, folder)[1])


def backup_listing(fx, folder=None):
    folder = folder or fx.backups
    return set(os.listdir(folder)) if os.path.isdir(folder) else set()


def fake_point(fx, when, content_from=None, user=None, folder=None, sidecar_data=None):
    """A backup point of src.blend stamped ``when`` (UTC) by ``user``
    (default: the current user) in ``folder`` (default: the custom folder,
    named with the source's hash; ``fx.ibkp``: next to the source), its copy
    a copy of ``content_from`` (a file) or empty, with a sidecar (none when
    ``sidecar_data`` is False)."""
    folder = folder or fx.backups
    path_hash = None if same_path(folder, fx.ibkp) else core.source_hash(fx.src)
    name = core.point_name("src", user or iel.backup_user(), when, path_hash)
    os.makedirs(folder, exist_ok=True)
    blend, side = iel.point_files(folder, name)
    if content_from:
        shutil.copyfile(content_from, blend)
    else:
        open(blend, "wb").close()
    if sidecar_data is not False:
        data = {"source_path": fx.src, "backup_time": when.isoformat(),
                "source_stat": None, "session_uuid": None}
        data.update(sidecar_data or {})
        with open(side, "w", encoding="utf-8") as fh:
            json.dump(data, fh)
    return name


UTC = datetime.timezone.utc
CANNOT = "Cannot tell whether src.blend was modified after this backup"


def fake_session(uuid, fx):
    return types.SimpleNamespace(uuid=uuid, source_path=fx.src)


def linked(name, fx):
    """The linked collection ``name`` from src.blend (wrappers of linked IDs
    die with a library reload: always fetched fresh)."""
    found = [c for c in bpy.data.collections
             if c.name == name and c.library is not None and same_path(bpy.path.abspath(c.library.filepath), fx.src)]
    assert len(found) == 1, [(c.name, c.library) for c in bpy.data.collections]
    return found[0]


def hidden_objects():
    vl = bpy.context.view_layer
    return {o.name for o in vl.objects if o.hide_get()}


def touch(path, seconds=10):
    st = os.stat(path)
    os.utime(path, (st.st_atime, st.st_mtime + seconds))


def changed_line(fx):
    return "%s changed since Start: the merge runs on its current content" % os.path.basename(fx.src)


def dry_run(s):
    """What the Commit operator's invoke does before the dialog: returns
    (plan, source stat at the dry run)."""
    ok, lines, _w = iel.preflight(bpy.context, s)
    assert ok, lines
    with iel.busy(bpy.context, "test"):  # no window headless: a no-op
        result, stat = iel.dry_run_linked(bpy.context, s)
    assert result["ok"], result.get("error")
    assert iel.newer_source_error(result) is None
    assert not os.path.exists(s.source_path + ".iops_lock"), "dry run left its lock"
    return result["plan"], stat


def commit(s, update_shared=()):
    """Dry run, then the write the dialog's confirm triggers."""
    plan, stat = dry_run(s)
    return plan, iel.commit_linked(bpy.context, s, set(update_shared), plan, stat)


def edit_session(s):
    """Move the copy's Cube by +1 world X, turn SharedMat green, add NewObj
    inside the copy. Returns the expected source matrices of Cube and NewObj."""
    frame = Matrix(get_frame(s).tolist())
    cube = owned(s, "objects", "Cube")
    assert cube.name == "Cube.001", cube.name
    cube.location.x += 1.0
    bpy.context.view_layer.update()
    exp_cube = frame.inverted() @ cube.matrix_world
    owned(s, "materials", "SharedMat").diffuse_color = GREEN
    new = bpy.data.objects.new("NewObj", None)
    bpy.context.view_layer.active_layer_collection.collection.objects.link(new)
    assert new.users_collection[0] == s.copy_collection
    new.location = (12.0, 3.0, 1.0)
    bpy.context.view_layer.update()
    exp_new = frame.inverted() @ new.matrix_world
    return exp_cube, exp_new


def keyset(plan, name):
    return {tuple(k) for k in plan[name]}


# --- tests ---------------------------------------------------------------------

def test_start_places_copy_and_hides_only_instancer(fx):
    build_source(fx)
    inst, inst2 = build_editing_file(fx)
    scene = bpy.context.scene
    vl = bpy.context.view_layer
    n_libs = len(bpy.data.libraries)
    linked_c = linked("C", fx)
    frame = inst.matrix_world @ Matrix.Translation(-Vector(linked_c.instance_offset))
    prev_lc = vl.active_layer_collection
    activate(inst)
    assert hidden_objects() == set()
    assert bpy.ops.iops.instance_edit_start() == {"FINISHED"}

    s = top()
    assert s.kind == "LINKED" and stack_len() == 1
    copy = bpy.data.collections.get("C [edit]")
    assert copy is not None and copy.library is None
    assert copy in scene.collection.children.values()
    assert s.copy_collection == copy and s.copy_collection_name == "C [edit]"
    assert same_path(s.source_path, fx.src) and s.source_coll_name == "C"
    assert source_stat(s) == (os.path.getmtime(fx.src), os.path.getsize(fx.src)), source_stat(s)
    assert close(Matrix(get_frame(s).tolist()), frame)
    assert owned_set(s) == EXPECTED_OWNED, owned_set(s) ^ EXPECTED_OWNED
    assert len(bpy.data.libraries) == n_libs

    cube = owned(s, "objects", "Cube")
    assert cube.name == "Cube.001", cube.name
    assert cube.library is None and list(cube.users_collection) == [copy]
    assert close(cube.matrix_world, frame @ CUBE_WORLD), (cube.matrix_world, frame @ CUBE_WORLD)
    child = owned(s, "objects", "Child")
    assert child.parent == cube
    exp_child = frame @ CUBE_WORLD @ Matrix.LocRotScale(
        Vector((0, 0, 2)), Euler((0.1, 0.2, 0.3), "ZXY"), Vector((0.5, 0.75, 2.0)))
    assert close(child.matrix_world, exp_child), (child.matrix_world, exp_child)
    dinst = owned(s, "objects", "DInst")
    exp_dinst = frame @ Matrix.LocRotScale(Vector((3, 0, 0)), Matrix.Rotation(math.radians(45), 3, "Z"), None)
    assert close(dinst.matrix_world, exp_dinst)

    # Only the instancer is hidden: Inst2 keeps showing the linked data.
    assert hidden_objects() == {"Inst"}, hidden_objects()
    assert inst.hide_get() is True and inst2.hide_get() is False
    assert [r.ref for r in s.instancers] == [inst]
    # The linked collection itself is untouched.
    assert close(linked("C", fx).objects["Cube"].matrix_world, CUBE_WORLD)
    assert vl.active_layer_collection.collection == copy
    assert vl.objects.active == cube
    assert {o.name for o in vl.objects if o.select_get()} == {"Cube.001", "Child", "DInst"}

    assert bpy.ops.iops.instance_edit_cancel() == {"FINISHED"}
    assert stack_len() == 0 and hidden_objects() == set()
    assert vl.active_layer_collection == prev_lc


def test_start_unowns_nested_same_file_collection(fx):
    _saved, _inst, _inst2, before = start(fx)
    s = top()
    assert owned_set(s) == EXPECTED_OWNED, owned_set(s) ^ EXPECTED_OWNED
    assert len(s.owned) == len(EXPECTED_OWNED)
    dinst = owned(s, "objects", "DInst")
    assert dinst.library is None and dinst.instance_collection is not None
    assert dinst.instance_collection == linked("D", fx), dinst.instance_collection
    # Nothing of D arrived as a local copy; the libraries did not change.
    added = local_ids() - before
    expected_local = {("collections", "C [edit]"), ("objects", "Cube.001"), ("objects", "Child"),
                      ("objects", "DInst"), ("meshes", "CubeMesh"), ("meshes", "ChildMesh"),
                      ("materials", "SharedMat")}
    assert added == expected_local, added ^ expected_local
    assert before - local_ids() == set()
    assert [os.path.basename(bpy.path.abspath(lib.filepath)) for lib in bpy.data.libraries] == ["src.blend"]
    d_objs = {o.name for o in linked("D", fx).objects}
    assert d_objs == {"DCube"}, d_objs
    assert bpy.ops.iops.instance_edit_cancel() == {"FINISHED"}
    assert local_ids() == before, local_ids() ^ before


def test_start_refuses_second_session_on_same_collection(fx):
    _saved, inst, inst2, _before = start(fx)
    activate(inst2)
    assert not bpy.ops.iops.instance_edit_start.poll()
    ok, reason = iel.can_start_linked(bpy.context)
    assert (ok, reason) == (False, "'C' is already being edited"), (ok, reason)
    try:
        bpy.ops.iops.instance_edit_start()
    except RuntimeError as exc:
        assert "already being edited" in str(exc), exc
    else:
        raise AssertionError("second Start ran")
    assert stack_len() == 1
    assert [c.name for c in bpy.data.collections if c.library is None] == ["C [edit]"]
    assert inst2.hide_get() is False and inst.hide_get() is True
    assert bpy.ops.iops.instance_edit_cancel() == {"FINISHED"}
    assert stack_len() == 0


def test_cancel_removes_copy_and_restores(fx):
    _saved, inst, inst2, before = start(fx)
    src_bytes = read(fx.src)
    s = top()
    edit_session(s)
    s.copy_collection.objects.link(bpy.data.objects.new("SessionObj", bpy.data.meshes.new("SessionMesh")))
    assert bpy.ops.iops.instance_edit_cancel() == {"FINISHED"}
    assert stack_len() == 0
    assert not bpy.ops.iops.instance_edit_cancel.poll()
    assert bpy.data.collections.get("C [edit]") is None
    assert local_ids() == before, local_ids() ^ before
    vl = bpy.context.view_layer
    assert hidden_objects() == set()
    assert vl.objects.active == inst and inst.select_get() and not inst2.select_get()
    assert vl.active_layer_collection == vl.layer_collection
    assert read(fx.src) == src_bytes
    assert listing(fx) == {"src.blend"}, listing(fx)
    lc = linked("C", fx)
    assert {o.name for o in lc.objects} == {"Cube", "Child", "DInst"}
    assert close(lc.objects["Cube"].matrix_world, CUBE_WORLD)
    assert tuple(lc.objects["Cube"].data.materials[0].diffuse_color) == RED
    no_tags()


def test_commit_round_trip_untouched_is_exact(fx):
    saved, inst, _inst2, before = start(fx, with_lib3=True)
    s = top()
    # The third-library object stays linked and is hidden for the session.
    assert hidden_objects() == {"Inst", "L3Obj"}, hidden_objects()
    assert owned_set(s) == EXPECTED_OWNED, owned_set(s) ^ EXPECTED_OWNED
    _plan, result = commit(s)
    assert result["ok"], result
    assert result["lines"] == [] and result["missing"] == [], result
    assert stack_len() == 0 and hidden_objects() == set()
    assert local_ids() == before, local_ids() ^ before
    assert listing(fx) == {"src.blend", "lib3.blend"}, listing(fx)
    assert len(points(fx)) == 1, backup_listing(fx)

    bpy.ops.wm.open_mainfile(filepath=fx.src)
    C = bpy.data.collections["C"]
    assert {o.name for o in C.objects} == {"Cube", "Child", "DInst", "L3Obj"}
    now = {o.name: channels(o) for o in C.all_objects}
    assert set(now) == set(saved) == {"Cube", "Child", "DInst", "L3Obj"}, (set(now), set(saved))
    for name in saved:
        assert now[name] == saved[name], (name, now[name], saved[name])
    cube = bpy.data.objects["Cube"]
    assert bpy.data.objects["Child"].parent == cube
    l3 = bpy.data.objects["L3Obj"]
    assert l3.library is not None and same_path(bpy.path.abspath(l3.library.filepath), fx.lib3)
    mats = [m for m in bpy.data.materials if m.name.startswith("SharedMat")]
    assert [m.name for m in mats] == ["SharedMat"] and tuple(mats[0].diffuse_color) == RED
    assert cube.data.materials[0] == mats[0]
    assert bpy.data.objects["OtherObj"].data.materials[0] == mats[0]
    assert bpy.data.objects["DInst"].instance_collection == bpy.data.collections["D"]
    assert [bpy.path.basename(lib.filepath) for lib in bpy.data.libraries] == ["lib3.blend"], \
        [(lib.name, lib.filepath, [o.name for o in bpy.data.objects if o.library == lib])
         for lib in bpy.data.libraries]
    no_tags()


def test_commit_moves_and_adds(fx):
    _saved, inst, inst2, before = start(fx)
    src_bytes = read(fx.src)
    s = top()
    session_uuid = s.uuid
    exp_cube, exp_new = edit_session(s)
    plan, result = commit(s)
    assert ("materials", "SharedMat") in keyset(plan, "kept"), plan
    assert ("objects", "NewObj") in keyset(plan, "added"), plan
    assert ("objects", "Cube") in keyset(plan, "replaced"), plan
    assert result["ok"], result
    # The backup lands in the custom backup folder, named for the source
    # (stem, path hash, user, UTC stamp); nothing is left next to the source.
    assert listing(fx) == {"src.blend"}, listing(fx)
    pts = points(fx)
    user = iel.backup_user()
    assert len(pts) == 1 and re.fullmatch(
        r"src\.%s\.%s\.\d{6}-\d{6}" % (core.source_hash(fx.src), re.escape(user)), pts[0]), pts
    assert backup_listing(fx) == {pts[0] + EXT, pts[0] + SIDE}, backup_listing(fx)
    bak, _side = point_files(fx, pts[0])
    assert same_path(result["backup"], bak) and read(bak) == src_bytes, "backup is not the pre-commit source"
    side = sidecar(fx, pts[0])
    assert set(side) == {"source_path", "backup_time", "source_stat", "session_uuid", "user", "machine"}, side
    assert core.user_tag(side["user"]) == user and side["machine"] == platform.node(), side
    assert os.path.isabs(side["source_path"]) and same_path(side["source_path"], fx.src), side
    taken = datetime.datetime.fromisoformat(side["backup_time"])
    assert taken.utcoffset() == datetime.timedelta(0), side["backup_time"]
    assert abs((datetime.datetime.now(datetime.timezone.utc) - taken).total_seconds()) < 600, taken
    # The name's stamp is the backup time in UTC.
    assert core.point_stamp(pts[0]) == taken, (pts[0], taken)
    assert side["session_uuid"] == session_uuid, side
    assert tuple(side["source_stat"]) == iel.file_stat(fx.src), (side, iel.file_stat(fx.src))
    assert iel.already_committed(fake_session(session_uuid, fx))
    assert stack_len() == 0
    assert bpy.data.collections.get("C [edit]") is None
    assert local_ids() == before, local_ids() ^ before
    no_tags()
    vl = bpy.context.view_layer
    assert hidden_objects() == set()
    assert vl.objects.active == inst and inst.select_get() and not inst2.select_get()
    assert vl.active_layer_collection == vl.layer_collection
    # The reloaded linked collection shows the result.
    lc = linked("C", fx)
    assert {o.name for o in lc.objects} == {"Cube", "Child", "DInst", "NewObj"}
    assert close(lc.objects["Cube"].matrix_world, exp_cube), (lc.objects["Cube"].matrix_world, exp_cube)
    assert vclose(lc.objects["NewObj"].location, exp_new.to_translation())
    assert tuple(lc.objects["Cube"].data.materials[0].diffuse_color) == RED

    bpy.ops.wm.open_mainfile(filepath=fx.src)
    c = bpy.data.collections["C"]
    assert {o.name for o in c.objects} == {"Cube", "Child", "DInst", "NewObj"}
    cube = bpy.data.objects["Cube"]
    assert close(cube.matrix_world, exp_cube), (cube.matrix_world, exp_cube)
    assert bpy.data.objects["Child"].parent == cube
    assert vclose(bpy.data.objects["NewObj"].location, exp_new.to_translation())
    mat = bpy.data.materials["SharedMat"]
    assert tuple(mat.diffuse_color) == RED and mat.users == 2, (tuple(mat.diffuse_color), mat.users)
    assert [m.name for m in bpy.data.materials if m.name.startswith("SharedMat")] == ["SharedMat"]
    dinst = bpy.data.objects["DInst"]
    assert dinst.instance_collection == bpy.data.collections["D"] and dinst.instance_collection.library is None
    assert len(bpy.data.libraries) == 0, [lib.filepath for lib in bpy.data.libraries]


def test_commit_warns_when_source_changed(fx):
    _saved, _inst, _inst2, _before = start(fx)
    s = top()
    assert iel.preflight(bpy.context, s) == (True, [], True)
    touch(fx.src)
    assert iel.preflight(bpy.context, s) == (True, [changed_line(fx)], True)
    exp_cube, _exp_new = edit_session(s)
    # A source changed after the dry run is refused before the backup.
    plan, stat = dry_run(s)
    touch(fx.src)
    src_bytes = read(fx.src)
    result = iel.commit_linked(bpy.context, s, set(), plan, stat)
    assert not result["ok"], result
    assert result["error"] == "src.blend changed since the dry run: Commit again", result["error"]
    assert read(fx.src) == src_bytes and listing(fx) == {"src.blend"}, listing(fx)
    assert points(fx) == [], backup_listing(fx)
    assert stack_len() == 1
    # Committed after a fresh dry run: it runs and carries the warning.
    _plan, result = commit(top())
    assert result["ok"], result
    assert result["lines"] == [changed_line(fx)], result["lines"]
    assert stack_len() == 0
    assert close(linked("C", fx).objects["Cube"].matrix_world, exp_cube)


def test_commit_failure_keeps_session(fx):
    _saved, inst, _inst2, _before = start(fx)
    s = top()
    edit_session(s)
    plan, stat = dry_run(s)
    wrong = dict(plan)
    wrong["replaced"] = []
    src_bytes = read(fx.src)
    state = editing_state(s)
    result = iel.commit_linked(bpy.context, s, set(), wrong, stat)
    assert not result["ok"], result
    assert result["error"].startswith("Merge failed, src.blend not written: "), result["error"]
    assert read(fx.src) == src_bytes, "source changed by a failed commit"
    s = top()
    assert stack_len() == 1 and s.kind == "LINKED" and s.source_coll_name == "C"
    assert bpy.data.collections.get("C [edit]") == s.copy_collection
    assert editing_state(s) == state
    no_tags()
    assert listing(fx) == {"src.blend"}, listing(fx)
    # The source was not touched: its point is removed again, so a failed
    # Commit never pushes a real point out.
    assert result["backup"] is None and backup_listing(fx) == set(), backup_listing(fx)
    assert not iel.already_committed(s), "a failed write counts as committed"
    assert hidden_objects() == {"Inst"}
    assert "NewObj" not in linked("C", fx).objects
    # The session still commits (the operator without a dialog).
    assert bpy.ops.iops.instance_edit_commit("EXEC_DEFAULT") == {"FINISHED"}
    assert stack_len() == 0
    assert "NewObj" in linked("C", fx).objects
    assert len(points(fx)) == 1, backup_listing(fx)


def test_nested_sessions_commit_inner_then_outer(fx):
    _saved, inst, _inst2, before = start(fx)
    outer = top()
    dinst = owned(outer, "objects", "DInst")
    assert dinst.instance_collection == linked("D", fx)
    # Inner LINKED session on D: same source file, another collection.
    activate(dinst)
    assert bpy.ops.iops.instance_edit_start.poll()
    assert bpy.ops.iops.instance_edit_start() == {"FINISHED"}
    assert stack_len() == 2
    inner = top()
    assert inner.kind == "LINKED" and inner.source_coll_name == "D" and same_path(inner.source_path, fx.src)
    assert inner.copy_collection_name == "D [edit]"
    assert owned_set(inner) == {("collections", "D"), ("objects", "DCube"), ("meshes", "DMesh"),
                                ("materials", "DMat")}, owned_set(inner)
    assert dinst.hide_get() is True
    # Only the top session can be committed: the poll checks the top one.
    assert bpy.ops.iops.instance_edit_commit.poll()

    frame_d = Matrix(get_frame(inner).tolist())
    dcube = owned(inner, "objects", "DCube")
    assert close(dcube.matrix_world, frame_d)
    dcube.location.z += 2.0
    bpy.context.view_layer.update()
    exp_d = frame_d.inverted() @ dcube.matrix_world
    assert vclose(exp_d.to_translation(), (0.0, 0.0, 2.0)), exp_d

    _plan, result = commit(inner)
    assert result["ok"], result
    assert result["lines"] == [], result["lines"]
    assert stack_len() == 1
    outer = top()
    assert outer.source_coll_name == "C" and bpy.data.collections.get("D [edit]") is None
    dinst = owned(outer, "objects", "DInst")
    assert dinst.hide_get() is False
    assert dinst.instance_collection == linked("D", fx)
    assert close(linked("D", fx).objects["DCube"].matrix_world, exp_d)

    exp_cube, exp_new = edit_session(outer)
    _plan, result = commit(outer)
    assert result["ok"], result
    # The inner Commit wrote the source after the outer Start.
    assert result["lines"] == [changed_line(fx)], result["lines"]
    assert stack_len() == 0 and hidden_objects() == set()
    assert local_ids() == before, local_ids() ^ before
    lc = linked("C", fx)
    assert close(lc.objects["Cube"].matrix_world, exp_cube)
    assert lc.objects["DInst"].instance_collection == linked("D", fx)

    bpy.ops.wm.open_mainfile(filepath=fx.src)
    C = bpy.data.collections["C"]
    D = bpy.data.collections["D"]
    assert {o.name for o in C.objects} == {"Cube", "Child", "DInst", "NewObj"}
    assert {o.name for o in D.objects} == {"DCube"}
    assert close(bpy.data.objects["Cube"].matrix_world, exp_cube)
    assert vclose(bpy.data.objects["NewObj"].location, exp_new.to_translation())
    assert close(bpy.data.objects["DCube"].matrix_world, exp_d), bpy.data.objects["DCube"].matrix_world
    assert bpy.data.objects["DInst"].instance_collection == D and D.library is None
    assert sorted(c.name for c in bpy.data.collections) == ["C", "D", "Other"]
    assert len(bpy.data.libraries) == 0


def test_rollback_restores_backup(fx):
    saved, _inst, _inst2, _before = start(fx)
    original = read(fx.src)
    assert not bpy.ops.iops.instance_edit_rollback_source.poll()
    s = top()
    edit_session(s)
    _plan, result = commit(s, {("materials", "SharedMat")})
    assert result["ok"], result
    assert ("materials", "SharedMat") in keyset(result["plan"], "replaced"), result["plan"]
    pts = points(fx)
    assert len(pts) == 1 and read(point_files(fx, pts[0])[0]) == original, pts
    lc = linked("C", fx)
    assert "NewObj" in lc.objects
    assert tuple(lc.objects["Cube"].data.materials[0].diffuse_color) == GREEN
    assert read(fx.src) != original

    found = iel.backup_points_for_libraries(bpy.context)
    assert [os.path.normcase(p) for p in found] == [os.path.normcase(fx.src)], found
    assert [[p.name for p in v] for v in found.values()] == [pts], found
    assert bpy.ops.iops.instance_edit_rollback_source.poll()
    assert iel.rollback_point_warning(bpy.context, fx.src, pts[0]) is None
    # A corrupt or missing sidecar: the point is still offered, with a
    # warning that its state is unknown.
    _bak, side = point_files(fx, pts[0])
    with open(side, "w", encoding="utf-8") as fh:
        fh.write("{not json")
    for _round in ("corrupt", "missing"):
        assert iel.rollback_point_warning(bpy.context, fx.src, pts[0]) == CANNOT, _round
        snap = iel.rollback_snapshot(bpy.context, fx.src)
        assert [it[0] for it in snap["items"]] == pts and snap["warnings"] == {pts[0]: CANNOT}, snap
        items = iel._point_items(types.SimpleNamespace(source_path=fx.src), bpy.context)
        assert [it[0] for it in items] == pts, items
        if _round == "corrupt":
            os.remove(side)
    # Rollback is refused while another Commit holds the source.
    with open(fx.lock, "w"):
        pass
    try:
        bpy.ops.iops.instance_edit_rollback_source(source_path=fx.src)
    except RuntimeError as exc:
        assert "another Commit is running on src.blend" in str(exc), exc
    else:
        raise AssertionError("Rollback ran while the source was locked")
    assert read(fx.src) != original and os.path.exists(fx.lock), "a refused Rollback touched the files"
    os.remove(fx.lock)
    assert bpy.ops.iops.instance_edit_rollback_source(source_path=fx.src) == {"FINISHED"}
    assert read(fx.src) == original
    assert listing(fx) == {"src.blend"}, listing(fx)
    assert points(fx) == pts and sidecar(fx, pts[0]).get("session_uuid") is None, sidecar(fx, pts[0])
    lc = linked("C", fx)
    assert {o.name for o in lc.objects} == {"Cube", "Child", "DInst"}
    assert close(lc.objects["Cube"].matrix_world, CUBE_WORLD)
    assert tuple(lc.objects["Cube"].data.materials[0].diffuse_color) == RED

    bpy.ops.wm.open_mainfile(filepath=fx.src)
    C = bpy.data.collections["C"]
    assert {o.name: channels(o) for o in C.all_objects} == saved
    assert tuple(bpy.data.materials["SharedMat"].diffuse_color) == RED


def _assign_users_datablocks():
    """In the editing file before Start: the user's own fake-user mesh and
    asset-marked material (asset_mark sets the fake user)."""
    mat = bpy.data.materials.new("MyAssetMat")
    mat.asset_mark()
    keep = bpy.data.meshes.new("KeepMesh")
    keep.use_fake_user = True
    assert mat.use_fake_user and mat.users == 1 and keep.users == 1


def _use_users_datablocks(s):
    """Assign the user's datablocks to copy objects during the session."""
    owned(s, "objects", "Cube").data.materials.append(bpy.data.materials["MyAssetMat"])
    owned(s, "objects", "Child").data = bpy.data.meshes["KeepMesh"]


def _users_datablocks_intact():
    # Local ones: after a Commit the reloaded library carries copies too.
    mat = bpy.data.materials.get(("MyAssetMat", None))
    keep = bpy.data.meshes.get(("KeepMesh", None))
    assert mat is not None and keep is not None, "the user's own datablock was removed"
    assert mat.asset_data is not None and mat.use_fake_user and mat.users == 1, (mat.users,)
    assert keep.use_fake_user and keep.users == 1, keep.users


def test_cancel_keeps_users_own_datablocks(fx):
    _saved, _inst, _inst2, before = start(fx, prepare=_assign_users_datablocks)
    s = top()
    _use_users_datablocks(s)
    # A driver reading the scene and one reading an outside control object.
    scene = bpy.context.scene
    ctl = bpy.data.objects.new("Control", None)
    scene.collection.objects.link(ctl)
    cube = owned(s, "objects", "Cube")
    for index, (kind, target) in enumerate((("SINGLE_PROP", scene), ("TRANSFORMS", ctl))):
        fc = cube.driver_add("location", index)
        var = fc.driver.variables.new()
        var.type = kind
        if kind == "SINGLE_PROP":
            var.targets[0].id_type = "SCENE"
            var.targets[0].data_path = "frame_current"
        var.targets[0].id = target
        fc.driver.expression = var.name
    before |= {("objects", "Control")}
    assert bpy.ops.iops.instance_edit_cancel() == {"FINISHED"}
    assert stack_len() == 0
    _users_datablocks_intact()
    assert [sc.name for sc in bpy.data.scenes] == [scene.name], "the driven scene was removed"
    assert "Control" in bpy.data.objects
    assert local_ids() == before, local_ids() ^ before


def test_commit_keeps_users_own_datablocks(fx):
    _saved, _inst, _inst2, before = start(fx, prepare=_assign_users_datablocks)
    s = top()
    _use_users_datablocks(s)
    plan, result = commit(s)
    assert result["ok"], result
    assert ("materials", "MyAssetMat") in keyset(plan, "added"), plan
    assert ("meshes", "KeepMesh") in keyset(plan, "added"), plan
    assert stack_len() == 0
    _users_datablocks_intact()
    assert local_ids() == before, local_ids() ^ before
    lc = linked("C", fx)
    assert lc.objects["Child"].data.name == "KeepMesh"


def test_commit_keeps_asset_metadata_and_relative_paths(fx):
    _saved, _inst, _inst2, _before = start(fx, assets=True)
    s = top()
    # Appending a collection that is also linked drops the asset mark.
    assert s.copy_collection.asset_data is None
    edit_session(s)
    _plan, result = commit(s)
    assert result["ok"], result
    bpy.ops.wm.open_mainfile(filepath=fx.src)
    C = bpy.data.collections["C"]
    assert {o.name for o in C.objects} == {"Cube", "Child", "DInst", "NewObj"}
    ad = C.asset_data
    assert ad is not None, "Commit removed the asset mark"
    assert ad.catalog_id == CATALOG, ad.catalog_id
    assert ad.description == "coll desc" and ad.author == "someone", (ad.description, ad.author)
    assert [t.name for t in ad.tags] == ["tagA"], [t.name for t in ad.tags]
    assert ad["studio"].to_dict() == {"lod": 2}, ad["studio"]
    path = bpy.data.objects["Cube"].modifiers["MC"].filepath
    assert path.replace("\\", "/") == "//caches/cube.pc2", path


def test_commit_refuses_already_committed_session(fx):
    _saved, _inst, _inst2, _before = start(fx)
    s = top()
    edit_session(s)
    src_bytes = read(fx.src)
    # Sidecars of several Commits of this source, one of them by this
    # session (what its Commit leaves, then an undo bringing it back).
    t0 = datetime.datetime(2026, 1, 2, 3, 4, 5)
    me, h = iel.backup_user(), core.source_hash(fx.src)
    names = [core.point_name("src", me, t0 + datetime.timedelta(minutes=m), h) for m in range(3)]
    stranger = core.point_name("src", me, t0, core.source_hash(os.path.join(fx.dir, "other", "src.blend")))

    def write_sidecars(mine_stat):
        rows = [(names[0], "1" * 32, [1.0, 2]), (names[1], s.uuid, mine_stat),
                (names[2], "2" * 32, None), (stranger, "3" * 32, [1.0, 2])]
        for name, owner, st in rows:
            with open(os.path.join(fx.backups, name + SIDE), "w", encoding="utf-8") as fh:
                json.dump({"source_path": fx.src, "backup_time": t0.isoformat(),
                           "source_stat": st, "session_uuid": owner}, fh)

    write_sidecars([1.0, 2])
    assert iel.already_committed(s)
    assert iel.preflight(bpy.context, s) == (False, [iel.ALREADY_COMMITTED], False)
    result = iel.commit_linked(bpy.context, s)
    assert not result["ok"] and result["error"] == iel.ALREADY_COMMITTED, result
    assert result["error"] == "This session was already committed; Cancel it"
    assert read(fx.src) == src_bytes and listing(fx) == {"src.blend"}, listing(fx)
    assert backup_listing(fx) == {n + SIDE for n in names + [stranger]}, backup_listing(fx)
    assert stack_len() == 1 and bpy.data.collections.get("C [edit]") == top().copy_collection
    # A sidecar of another source naming the session does not block, nor
    # one whose write never succeeded (no source_stat), nor other uuids.
    assert not iel.already_committed(fake_session("3" * 32, fx))
    assert not iel.already_committed(fake_session("2" * 32, fx))
    assert iel.already_committed(fake_session("1" * 32, fx))
    write_sidecars(None)
    assert not iel.already_committed(top())
    _plan, result = commit(top())
    assert result["ok"], result


def test_commit_refuses_while_source_locked(fx):
    _saved, _inst, _inst2, _before = start(fx)
    s = top()
    edit_session(s)
    src_bytes = read(fx.src)
    with open(fx.lock, "w") as fh:
        fh.write("{}")
    refusal = "another Commit is running on src.blend"
    try:
        iel.dry_run_linked(bpy.context, s)
    except iel.CommitRefused as exc:
        assert str(exc).startswith(refusal), exc
    else:
        raise AssertionError("dry run ran while the source was locked")
    result = iel.commit_linked(bpy.context, s)
    assert not result["ok"] and result["error"].startswith(refusal), result
    # The other Commit's lock is left alone; nothing else was written.
    assert read(fx.src) == src_bytes and listing(fx) == {"src.blend", "src.blend.iops_lock"}, listing(fx)
    assert stack_len() == 1
    # A lock older than the worker timeout is a crashed Blender's: replaced.
    old = time.time() - 3600
    os.utime(fx.lock, (old, old))
    _plan, result = commit(top())
    assert result["ok"], result
    assert listing(fx) == {"src.blend"}, listing(fx)
    assert len(points(fx)) == 1, backup_listing(fx)


def test_p4_edit_output_shown_and_must_sync_refuses(fx):
    _saved, _inst, _inst2, _before = start(fx)
    s = top()
    prefs = bpy.context.preferences.addons["InteractionOps"].preferences
    calls = []
    answer = {}
    real_run = subprocess.run

    def fake_run(cmd, *args, **kwargs):
        if cmd[:2] != ["p4", "edit"]:
            return real_run(cmd, *args, **kwargs)
        calls.append(list(cmd))
        os.chmod(fx.src, stat.S_IREAD | stat.S_IWRITE)  # p4 opened it for edit
        return subprocess.CompletedProcess(cmd, 0, answer["out"].encode(), b"")

    was_p4 = prefs.iops_instance_edit_p4
    prefs.iops_instance_edit_p4 = True
    subprocess.run = fake_run
    try:
        stale = ("//depot/src.blend#3 - opened for edit\n"
                 "... //depot/src.blend - must sync/resolve #4 before submitting\n")
        answer["out"] = stale
        os.chmod(fx.src, stat.S_IREAD)
        ok, lines, writable = iel.preflight(bpy.context, s)
        assert calls == [["p4", "edit", s.source_path]], calls
        assert not ok and not writable, lines
        assert lines[0] == "src.blend: p4 edit: ... //depot/src.blend - must sync/resolve #4 before submitting", lines
        assert "p4 edit: //depot/src.blend#3 - opened for edit" in lines[1:], lines
        os.chmod(fx.src, stat.S_IREAD)
        result = iel.commit_linked(bpy.context, s)
        assert not result["ok"] and "must sync/resolve" in result["error"], result
        assert listing(fx) == {"src.blend"} and stack_len() == 1, listing(fx)

        answer["out"] = "//depot/src.blend#4 - opened for edit\n"
        os.chmod(fx.src, stat.S_IREAD)
        assert iel.preflight(bpy.context, s) == (
            True,
            ["Checked out in Perforce: src.blend",
             "p4 edit: //depot/src.blend#4 - opened for edit"],
            True)
    finally:
        subprocess.run = real_run
        prefs.iops_instance_edit_p4 = was_p4
        os.chmod(fx.src, stat.S_IREAD | stat.S_IWRITE)
    assert bpy.ops.iops.instance_edit_cancel() == {"FINISHED"}


def test_backups_pruned_and_rollback_to_a_point(fx):
    prefs = addon_prefs()
    was_count = prefs.iops_instance_edit_backup_count
    prefs.iops_instance_edit_backup_count = 2
    try:
        _saved, inst, _inst2, _before = start(fx)
        states, uuids, cubes = [read(fx.src)], [], [Matrix(CUBE_WORLD)]
        for i in range(3):
            if i:
                activate(inst)
                assert bpy.ops.iops.instance_edit_start() == {"FINISHED"}
            s = top()
            uuids.append(s.uuid)
            owned(s, "objects", "Cube").location.x += 1.0
            bpy.context.view_layer.update()
            _plan, result = commit(s)
            assert result["ok"], result
            assert stack_len() == 0
            states.append(read(fx.src))
            cubes.append(Matrix(linked("C", fx).objects["Cube"].matrix_world))
        assert len(set(states)) == 4, "each Commit changes the source"
        # Three Commits, two points kept: the oldest (the original source)
        # was removed with its sidecar.
        pts = points(fx)
        assert len(pts) == 2, backup_listing(fx)
        assert backup_listing(fx) == {p + e for p in pts for e in (EXT, SIDE)}, backup_listing(fx)
        assert sorted(pts, reverse=True) == pts
        assert [read(point_files(fx, p)[0]) for p in pts] == [states[2], states[1]]
        assert [sidecar(fx, p)["session_uuid"] for p in pts] == [uuids[2], uuids[1]]
        assert listing(fx) == {"src.blend"}, listing(fx)
        # already_committed reads every sidecar of the source.
        assert iel.already_committed(fake_session(uuids[2], fx))
        assert iel.already_committed(fake_session(uuids[1], fx))
        assert not iel.already_committed(fake_session(uuids[0], fx)), "its point was pruned"
        assert [[p.name for p in v] for v in iel.backup_points_for_libraries(bpy.context).values()] == [pts]
        # The point enum: newest first, "<local time>  mine  [folder]".
        items = iel._point_items(types.SimpleNamespace(source_path=fx.src), bpy.context)
        assert [it[0] for it in items] == pts, items
        for it in items:
            assert re.fullmatch(r"\d{4}-\d\d-\d\d \d\d:\d\d:\d\d  mine  \[folder\]", it[1]), it
        # Only the newest point matches the source as it is now.
        assert iel.rollback_point_warning(bpy.context, fx.src, pts[0]) is None
        assert iel.rollback_point_warning(bpy.context, fx.src, pts[1]) == "src.blend was modified after this backup"

        # Rollback without a point: the newest.
        assert bpy.ops.iops.instance_edit_rollback_source(source_path=fx.src) == {"FINISHED"}
        assert read(fx.src) == states[2]
        assert close(linked("C", fx).objects["Cube"].matrix_world, cubes[2])
        assert not iel.already_committed(fake_session(uuids[2], fx))
        assert iel.already_committed(fake_session(uuids[1], fx))
        assert points(fx) == pts, "Rollback removed a point"
        # Rollback to the older point; the newer one's session is free too.
        assert bpy.ops.iops.instance_edit_rollback_source(source_path=fx.src, point=pts[1]) == {"FINISHED"}
        assert read(fx.src) == states[1]
        assert close(linked("C", fx).objects["Cube"].matrix_world, cubes[1])
        assert not any(iel.already_committed(fake_session(u, fx)) for u in uuids)
        assert points(fx) == pts and listing(fx) == {"src.blend"}, (points(fx), listing(fx))
        # A point that is not this file's is refused.
        try:
            bpy.ops.iops.instance_edit_rollback_source(source_path=fx.src, point="nope")
        except TypeError:
            pass
        else:
            raise AssertionError("an unknown point was accepted")

        # The dialog: invoke snapshots the points and preselects the newest;
        # the user picks pts[0]; a newer point appears (another Blender
        # committed) before Rollback is pressed: pts[0] is still restored.
        shift = {}

        def between(op):
            assert op.point == pts[0] and op._snapshot["items"][0][0] == pts[0]
            before = [it[0] for it in iel._point_items(op, bpy.context)]
            shift["new"] = fake_point(fx, datetime.datetime(2030, 1, 1, tzinfo=UTC),
                                      point_files(fx, pts[1])[0])
            after = [it[0] for it in iel._point_items(op, bpy.context)]
            shift["moved"] = (before.index(pts[0]), after.index(pts[0]))

        op_cls = rollback_test_operator(between)
        bpy.utils.register_class(op_cls)
        try:
            assert bpy.ops.iops.test_rollback_shift(source_path=fx.src) == {"FINISHED"}
        finally:
            bpy.utils.unregister_class(op_cls)
        assert shift["moved"] == (0, 1), shift  # a list index would have shifted
        assert read(fx.src) == states[2]
        assert close(linked("C", fx).objects["Cube"].matrix_world, cubes[2])
        assert points(fx) == [shift["new"]] + pts
        assert iel._rollback_dialog["snapshot"] is None, "the snapshot outlived the dialog"
    finally:
        prefs.iops_instance_edit_backup_count = was_count


def rollback_test_operator(between):
    """Rollback with invoke's work (snapshot, newest own point preselected), then
    ``between(op)`` where the dialog would be shown, then execute. Done in
    execute: headless there is no event, so Blender never calls invoke.
    Not a subclass: unregistering a subclass strips the inherited
    callbacks (poll) from the real operator class."""
    real = iel.IOPS_OT_instance_edit_rollback_source

    class IOPS_OT_test_rollback_shift(bpy.types.Operator):
        bl_idname = "iops.test_rollback_shift"
        bl_label = "Test Rollback Shift"
        source_path: bpy.props.StringProperty()
        point: bpy.props.EnumProperty(items=iel._point_items, options={"SKIP_SAVE"})
        prepare = real.prepare
        _execute = real._execute

        def execute(self, context):
            assert self.prepare(context) is not None
            between(self)
            return real.execute(self, context)

    return IOPS_OT_test_rollback_shift


def test_prune_keeps_the_point_just_written(fx):
    prefs = addon_prefs()
    was_count = prefs.iops_instance_edit_backup_count
    prefs.iops_instance_edit_backup_count = 1
    try:
        _saved, _inst, _inst2, _before = start(fx)
        src_bytes = read(fx.src)
        # A point stamped later than now (a clock set back since): the
        # point Commit writes sorts oldest, and must survive the pruning.
        future = fake_point(fx, datetime.datetime(2030, 6, 1, tzinfo=UTC))
        edit_session(top())
        _plan, result = commit(top())
        assert result["ok"], result
        pts = points(fx)
        assert len(pts) == 1 and pts[0] != future, pts
        bak, _side = point_files(fx, pts[0])
        assert same_path(result["backup"], bak) and read(bak) == src_bytes
        assert backup_listing(fx) == {pts[0] + EXT, pts[0] + SIDE}, backup_listing(fx)
    finally:
        prefs.iops_instance_edit_backup_count = was_count


def test_commit_refuses_unusable_backup_folder(fx):
    _saved, _inst, _inst2, _before = start(fx)
    edit_session(top())
    src_bytes = read(fx.src)
    prefs = addon_prefs()
    expect = "Could not back up src.blend: "
    blocker = os.path.join(fx.backups, "not_a_folder")
    open(blocker, "w").close()

    def refused(patch_name=None, replacement=None):
        plan, stat = dry_run(top())
        owner = iel.shutil if patch_name == "copy2" else iel
        real = getattr(owner, patch_name) if patch_name else None
        if patch_name:
            setattr(owner, patch_name, replacement)
        try:
            result = iel.commit_linked(bpy.context, top(), set(), plan, stat)
        finally:
            if patch_name:
                setattr(owner, patch_name, real)
        assert not result["ok"] and result["error"].startswith(expect), result
        assert read(fx.src) == src_bytes, "the source was written without a backup"
        assert listing(fx) == {"src.blend"} and stack_len() == 1, listing(fx)
        assert backup_listing(fx) == {"not_a_folder"}, backup_listing(fx)

    try:
        # The folder cannot be created (a file is in the way).
        prefs.iops_instance_edit_backup_dir = blocker
        refused()
        prefs.iops_instance_edit_backup_dir = fx.backups

        # A read-only folder: the copy is refused.
        def deny(src, dst, *args, **kwargs):
            raise PermissionError(13, "Access is denied", dst)
        refused("copy2", deny)

        # The sidecar cannot be written: the copy is removed again.
        def full(path, data):
            raise OSError(28, "No space left on device", path)
        refused("_write_point_json", full)

        # A relative folder preference is ignored, with a line saying so.
        prefs.iops_instance_edit_backup_dir = "//backups"
        ok, lines, _w = iel.preflight(bpy.context, top())
        assert ok and lines == [iel.backup_dir_problem(bpy.context)], lines
        prefs.iops_instance_edit_backup_dir = fx.backups
        _plan, result = commit(top())
        assert result["ok"], result
        assert len(points(fx)) == 1, backup_listing(fx)
    finally:
        prefs.iops_instance_edit_backup_dir = fx.backups


def test_backup_dir_default_and_pref():
    prefs = addon_prefs()
    was = prefs.iops_instance_edit_backup_dir
    try:
        prefs.iops_instance_edit_backup_dir = ""
        expected = os.path.join(bpy.utils.user_resource("CONFIG"), "iops", "instance_edit_backups")
        assert same_path(iel.backup_dir(bpy.context, create=False), expected)
        assert iel.backup_dir_problem(bpy.context) is None
        prefs.iops_instance_edit_backup_dir = RUN_DIR
        assert same_path(iel.backup_dir(bpy.context, create=False), RUN_DIR)
        assert iel.backup_dir_problem(bpy.context) is None
        # Relative values are ignored (with a problem line), never resolved
        # against whichever file is open.
        for rel in ("//backups", "rel/backups"):
            prefs.iops_instance_edit_backup_dir = rel
            assert same_path(iel.backup_dir(bpy.context, create=False), expected), rel
            problem = iel.backup_dir_problem(bpy.context)
            assert problem and "not an absolute path" in problem and rel in problem, problem
        made = os.path.join(RUN_DIR, "made", "here")
        prefs.iops_instance_edit_backup_dir = made
        assert not os.path.exists(made)
        assert iel.backup_points_for_libraries(bpy.context) == {} and not os.path.exists(made)
        assert same_path(iel.backup_dir(bpy.context), made) and os.path.isdir(made)
    finally:
        prefs.iops_instance_edit_backup_dir = was


# --- backup location next to the source, other users' points, cleanup --------

OTHER = "colleague"


def next_to_source(fx):
    addon_prefs().iops_instance_edit_backup_location = "NEXT_TO_SOURCE"
    assert OTHER != iel.backup_user()


def bump_cube(inst):
    activate(inst)
    assert bpy.ops.iops.instance_edit_start() == {"FINISHED"}
    owned(top(), "objects", "Cube").location.x += 1.0
    bpy.context.view_layer.update()


def test_next_to_source_commit_and_per_user_prune(fx):
    prefs = addon_prefs()
    next_to_source(fx)
    prefs.iops_instance_edit_backup_count = 2
    _saved, inst, _inst2, _before = start(fx)
    src_bytes = read(fx.src)
    session_uuid = top().uuid
    edit_session(top())
    # While the Commit runs only its temp files, its lock and the backup
    # folder appear beside the source.
    seen = []
    real_run = iel.run_worker

    def spy(*args, **kwargs):
        seen.append(listing(fx))
        return real_run(*args, **kwargs)

    copies = []
    real_copy2 = iel.shutil.copy2

    def copy_spy(src, dst, *args, **kwargs):
        copies.append(os.path.basename(dst))
        assert iel.source_points(bpy.context, fx.src) == [], "a half copy is listed"
        out = real_copy2(src, dst, *args, **kwargs)
        assert iel.source_points(bpy.context, fx.src) == [], "a .part copy is listed"
        return out

    iel.run_worker = spy
    iel.shutil.copy2 = copy_spy
    try:
        _plan, result = commit(top())
    finally:
        iel.run_worker = real_run
        iel.shutil.copy2 = real_copy2
    assert len(copies) == 1 and copies[0].endswith(".iopsbackup.part"), copies
    assert result["ok"], result
    allowed = re.compile(
        r"src\.iops_commit-[0-9a-f]{8}\.(blend|json|result\.json)|src\.blend\.iops_lock|src\.blend|\.iopsbackup")
    assert len(seen) >= 2 and all(allowed.fullmatch(n) for names in seen for n in names), seen
    assert any("src.blend.iops_lock" in names for names in seen), seen
    assert listing(fx) == {"src.blend", ".iopsbackup"}, listing(fx)
    assert backup_listing(fx) == set(), "the custom folder was used in next-to-source mode"
    user = iel.backup_user()
    pts = points(fx, fx.ibkp)
    assert len(pts) == 1 and re.fullmatch(r"src\.%s\.\d{6}-\d{6}" % re.escape(user), pts[0]), pts
    assert backup_listing(fx, fx.ibkp) == {pts[0] + EXT, pts[0] + SIDE}, backup_listing(fx, fx.ibkp)
    assert same_path(result["backup"], point_files(fx, pts[0], fx.ibkp)[0]) and read(result["backup"]) == src_bytes
    side = sidecar(fx, pts[0], fx.ibkp)
    assert core.user_tag(side["user"]) == user and side["machine"] == platform.node(), side
    assert side["session_uuid"] == session_uuid and tuple(side["source_stat"]) == iel.file_stat(fx.src), side
    assert iel.already_committed(fake_session(session_uuid, fx))

    # A colleague's points and two older points of mine in the same folder.
    t = datetime.datetime(2025, 1, 1, tzinfo=UTC)
    theirs = [fake_point(fx, t + datetime.timedelta(days=d), fx.src, user=OTHER, folder=fx.ibkp) for d in range(3)]
    old_own = [fake_point(fx, t + datetime.timedelta(days=10 + d), fx.src, folder=fx.ibkp) for d in range(2)]
    stale_part = core.point_name("src", user, t)  # a crashed Commit's copy
    fresh_part = core.point_name("src", user, datetime.datetime.now(UTC))  # being written now
    for name in (stale_part, fresh_part):
        open(iel.part_path(fx.ibkp, name), "wb").close()
    bump_cube(inst)
    _plan, result = commit(top())
    assert result["ok"], result
    # The limit (2) counts only my points: the two Commits stay, my older
    # points go, every one of the colleague's points stays whole.
    pts = points(fx, fx.ibkp)
    own = [p for p in pts if core.point_user(p) == user]
    assert len(own) == 2, pts
    assert not set(own) & set(old_own) and set(pts) == set(own) | set(theirs), pts
    assert all(os.path.exists(f) for p in theirs for f in point_files(fx, p, fx.ibkp)), backup_listing(fx, fx.ibkp)
    assert not any(os.path.exists(f) for p in old_own for f in point_files(fx, p, fx.ibkp))
    assert not os.path.exists(iel.part_path(fx.ibkp, stale_part)), "stale .part not swept"
    assert os.path.exists(iel.part_path(fx.ibkp, fresh_part)), "a fresh .part was removed"
    os.remove(iel.part_path(fx.ibkp, fresh_part))

    # Off: the limit counts every point of the source, so the colleague's
    # (older) points go too; the protected point always stays.
    prefs.iops_instance_edit_prune_only_mine = False
    removed = iel.prune_points(bpy.context, fx.src, protect=own[1])
    assert set(removed) == set(theirs), removed
    assert points(fx, fx.ibkp) == own
    assert backup_listing(fx, fx.ibkp) == {p + e for p in own for e in (EXT, SIDE)}, backup_listing(fx, fx.ibkp)


def test_rollback_lists_everyones_points(fx):
    next_to_source(fx)
    _saved, _inst, _inst2, _before = start(fx)
    original = read(fx.src)
    edit_session(top())
    _plan, result = commit(top())
    assert result["ok"], result
    state1 = read(fx.src)
    mine = points(fx, fx.ibkp)
    assert len(mine) == 1 and read(point_files(fx, mine[0], fx.ibkp)[0]) == original
    # A colleague's newer point (the source as it is now) next to the
    # source, and a point of mine left in the custom folder (taken before
    # the location mode was switched).
    theirs = fake_point(fx, datetime.datetime(2030, 1, 1, tzinfo=UTC), fx.src, user=OTHER, folder=fx.ibkp,
                        sidecar_data={"user": "Col League"})
    custom = fake_point(fx, datetime.datetime(2024, 1, 1, tzinfo=UTC), point_files(fx, mine[0], fx.ibkp)[0])
    pts = iel.source_points(bpy.context, fx.src)
    assert [p.name for p in pts] == [theirs, mine[0], custom], pts
    assert [p.kind for p in pts] == ["NEXT_TO_SOURCE", "NEXT_TO_SOURCE", "CUSTOM_FOLDER"], pts
    found = iel.backup_points_for_libraries(bpy.context)
    assert [os.path.normcase(p) for p in found] == [os.path.normcase(fx.src)], found
    assert bpy.ops.iops.instance_edit_rollback_source.poll()

    snap = iel.rollback_snapshot(bpy.context, fx.src)
    assert snap["default"] == mine[0], snap["default"]
    labels = [it[1] for it in snap["items"]]
    assert [it[0] for it in snap["items"]] == [theirs, mine[0], custom], snap["items"]
    assert labels[0].endswith("  Col League  [.iopsbackup]"), labels  # the raw sidecar user
    assert labels[1].endswith("  mine  [.iopsbackup]") and labels[2].endswith("  mine  [folder]"), labels
    assert re.match(r"\d{4}-\d\d-\d\d \d\d:\d\d:\d\d  ", labels[0]), labels
    assert len({it[3] for it in snap["items"]}) == 3
    # Two points of one second (two users): distinct enum numbers.
    same = [core.point_name("src", u, datetime.datetime(2030, 1, 1, tzinfo=UTC)) for u in ("a", "b")]
    assert len(set(iel.point_numbers(same).values())) == 2
    # The open dialog's numbers stay fixed: a point of the same second as
    # mine[0] that appears meanwhile (and would sort first) is numbered
    # around them, so the stored choice still maps to mine[0].
    numbers = {it[0]: it[3] for it in snap["items"]}
    stamp = core.point_stamp(mine[0])
    intruder = fake_point(fx, stamp, fx.src, user="aaa", folder=fx.ibkp)
    assert iel.point_numbers([intruder, mine[0]])[intruder] == numbers[mine[0]], "no collision to test"
    iel._rollback_dialog["snapshot"] = snap
    try:
        now_items = {it[0]: it[3] for it in iel._point_items(types.SimpleNamespace(source_path=fx.src), bpy.context)}
    finally:
        iel._rollback_dialog["snapshot"] = None
    assert all(now_items[n] == v for n, v in numbers.items()), (numbers, now_items)
    assert now_items[intruder] not in numbers.values(), now_items
    iel._remove_point(*point_files(fx, intruder, fx.ibkp))
    # A missing sidecar: still listed, the user taken from the file name.
    os.remove(point_files(fx, theirs, fx.ibkp)[1])
    snap = iel.rollback_snapshot(bpy.context, fx.src)
    assert [it[0] for it in snap["items"]] == [theirs, mine[0], custom], snap["items"]
    assert snap["items"][0][1].endswith("  %s  [.iopsbackup]" % OTHER), snap["items"][0]
    assert snap["warnings"][theirs] == CANNOT, snap["warnings"]

    # The dialog preselects my newest point, not the colleague's newer one.
    chosen = {}

    def between(op):
        chosen["point"] = op.point

    op_cls = rollback_test_operator(between)
    bpy.utils.register_class(op_cls)
    try:
        assert bpy.ops.iops.test_rollback_shift(source_path=fx.src) == {"FINISHED"}
    finally:
        bpy.utils.unregister_class(op_cls)
    assert chosen["point"] == mine[0] and read(fx.src) == original, chosen
    # The colleague's point, chosen explicitly.
    assert bpy.ops.iops.instance_edit_rollback_source(source_path=fx.src, point=theirs) == {"FINISHED"}
    assert read(fx.src) == state1
    assert "NewObj" in linked("C", fx).objects
    # Without a point: my newest again.
    assert bpy.ops.iops.instance_edit_rollback_source(source_path=fx.src) == {"FINISHED"}
    assert read(fx.src) == original
    # The point in the other location.
    assert bpy.ops.iops.instance_edit_rollback_source(source_path=fx.src, point=theirs) == {"FINISHED"}
    assert bpy.ops.iops.instance_edit_rollback_source(source_path=fx.src, point=custom) == {"FINISHED"}
    assert read(fx.src) == original
    assert "NewObj" not in linked("C", fx).objects
    assert listing(fx) == {"src.blend", ".iopsbackup"}, listing(fx)
    assert [p.name for p in iel.source_points(bpy.context, fx.src)] == [theirs, mine[0], custom]


def test_cleanup_backups(fx):
    next_to_source(fx)
    build_source(fx)
    build_editing_file(fx)
    # Saved next to the source, so "//src.blend" names the source.
    bpy.ops.wm.save_as_mainfile(filepath=os.path.join(fx.dir, "edit.blend"))
    me = iel.backup_user()
    now = datetime.datetime.now(UTC).replace(microsecond=0)
    old, recent = now - datetime.timedelta(days=60), now - datetime.timedelta(days=1)
    own_old = fake_point(fx, old, fx.src, folder=fx.ibkp)
    own_recent = fake_point(fx, recent, fx.src, folder=fx.ibkp)
    their_old = fake_point(fx, old, fx.src, user=OTHER, folder=fx.ibkp, sidecar_data={"user": OTHER})
    custom_old = fake_point(fx, old, fx.src)
    # A sidecar whose copy is gone counts as a point; so does a stale .part
    # copy (a crashed Commit's), never a fresh one (a Commit writing now).
    orphan = fake_point(fx, old - datetime.timedelta(minutes=5), folder=fx.ibkp)
    os.remove(point_files(fx, orphan, fx.ibkp)[0])
    stale_part = core.point_name("src", me, old - datetime.timedelta(minutes=9))
    fresh_part = core.point_name("src", me, now)
    for name in (stale_part, fresh_part):
        shutil.copyfile(fx.src, iel.part_path(fx.ibkp, name))
    # Another source's point in the custom folder, and files that are no
    # backup points (some with the backup extensions).
    stranger = core.point_name("zzz", me, old, "0a1b2c3d")
    for path in iel.point_files(fx.backups, stranger):
        shutil.copyfile(fx.src, path)
    junk = ("notes.txt", "notes.iopsbackup", "src.iopsbackup", "x.y.iopsbackup.json",
            "src.%s.2601-01.iopsbackup" % me)
    for folder in (fx.backups, fx.ibkp):
        for name in junk:
            open(os.path.join(folder, name), "w").close()

    def plan(scope="LIBRARIES", days=30, only_mine=True, source="", not_after=None):
        return iel.cleanup_candidates(bpy.context, scope, days, only_mine, source, not_after)

    def names(pl):
        return sorted(n for _f, n in pl.points)

    mine_old = sorted([own_old, custom_old, orphan, stale_part])
    assert names(plan()) == mine_old, names(plan())
    assert names(plan(only_mine=False)) == sorted(mine_old + [their_old])
    assert names(plan(days=0)) == sorted(mine_old + [own_recent])  # a fresh .part is no candidate
    assert names(plan(days=0, only_mine=False)) == sorted(mine_old + [own_recent, their_old])
    # Points taken after the dialog opened are never candidates.
    assert names(plan(days=0, not_after=recent - datetime.timedelta(hours=1))) == mine_old
    assert names(plan(source=fx.src)) == mine_old
    assert names(plan(source="//src.blend")) == mine_old
    assert names(plan(source=os.path.join(fx.dir, "nope.blend"))) == []
    assert names(plan("CUSTOM_FOLDER")) == sorted([custom_old, stranger])
    assert names(plan("CUSTOM_FOLDER", source=fx.src)) == [custom_old]
    assert names(plan("CUSTOM_FOLDER", source="//src.blend")) == [custom_old]
    dry = plan()
    expected = {own_old + EXT, own_old + SIDE, custom_old + EXT, custom_old + SIDE, orphan + SIDE,
                stale_part + ".iopsbackup.part"}
    assert {os.path.basename(f) for f in dry.files} == expected, dry.files
    assert dry.bytes == sum(os.path.getsize(f) for f in dry.files), dry
    assert [same_path(src, fx.src) for src, _files in dry.groups] == [True], dry.groups

    # The source is locked (a Commit runs): its files are skipped, whole.
    with open(fx.lock, "w"):
        pass
    assert iel.run_cleanup(bpy.context, dry)[:4] == (0, 0, 0, len(dry.files))
    assert all(os.path.exists(f) for f in dry.files)
    os.remove(fx.lock)
    # The confirmed plan is deleted exactly: a matching point that appears
    # after it was taken stays.
    late = fake_point(fx, old + datetime.timedelta(minutes=1), fx.src, folder=fx.ibkp)
    before_ibkp, before_custom = backup_listing(fx, fx.ibkp), backup_listing(fx)
    deleted, freed, failed, skipped, _refusals = iel.run_cleanup(bpy.context, dry)
    assert (deleted, freed, failed, skipped) == (len(dry.files), dry.bytes, 0, 0)
    gone = {os.path.basename(f) for f in dry.files}
    assert backup_listing(fx, fx.ibkp) == before_ibkp - gone, backup_listing(fx, fx.ibkp)
    assert backup_listing(fx) == before_custom - gone, backup_listing(fx)
    assert os.path.exists(point_files(fx, late, fx.ibkp)[0]) and not os.path.exists(fx.lock)
    # Through the operator (scripted, so it plans itself).
    assert bpy.ops.iops.instance_edit_backups_cleanup(scope="LIBRARIES", older_than_days=30, only_mine=True) == {"FINISHED"}
    assert not os.path.exists(point_files(fx, late, fx.ibkp)[0])
    # only_mine not given: the prune preference decides (off: everyone's).
    addon_prefs().iops_instance_edit_prune_only_mine = False
    assert bpy.ops.iops.instance_edit_backups_cleanup(older_than_days=30) == {"FINISHED"}
    keep = {own_recent + EXT, own_recent + SIDE, fresh_part + ".iopsbackup.part"} | set(junk)
    assert backup_listing(fx, fx.ibkp) == keep, backup_listing(fx, fx.ibkp)
    # The whole custom folder, every age: the other source's point goes,
    # files outside the point grammar stay.
    assert names(plan("CUSTOM_FOLDER", days=0, only_mine=False)) == [stranger]
    assert bpy.ops.iops.instance_edit_backups_cleanup(scope="CUSTOM_FOLDER", older_than_days=0, only_mine=False) == {"FINISHED"}
    assert backup_listing(fx) == set(junk), backup_listing(fx)
    assert backup_listing(fx, fx.ibkp) == keep
    assert listing(fx) == {"src.blend", "edit.blend", ".iopsbackup"}, listing(fx)


# Two raw OS user names that reduce to one backup-name tag ("____").
IVAN = "".join(map(chr, (0x418, 0x432, 0x430, 0x43D)))
PETR = "".join(map(chr, (0x41F, 0x451, 0x442, 0x440)))


def test_same_tag_users_kept_apart(fx):
    next_to_source(fx)
    prefs = addon_prefs()
    prefs.iops_instance_edit_backup_count = 1
    build_source(fx)
    build_editing_file(fx)
    real_user = iel._os_user
    iel._os_user = lambda: IVAN
    try:
        assert iel.backup_user() == core.user_tag(PETR) == "____"
        t = datetime.datetime(2025, 1, 1, tzinfo=UTC)

        def at(hours, user, side_user):
            data = False if side_user is False else {"user": side_user}
            return fake_point(fx, t + datetime.timedelta(hours=hours), fx.src, user=user, folder=fx.ibkp,
                              sidecar_data=data)

        # The sidecar's user decides (case-folded); a point without a
        # sidecar falls back to the tag in its name.
        ivan = [at(1, IVAN, IVAN), at(3, IVAN, IVAN.upper())]
        petr = [at(2, PETR, PETR), at(4, PETR, PETR)]
        bare = at(0, IVAN, False)
        assert [iel.is_mine(n, fx.ibkp) for n in ivan + petr + [bare]] == [True, True, False, False, True]

        snap = iel.rollback_snapshot(bpy.context, fx.src)
        assert snap["default"] == ivan[1], snap["default"]  # not Petr's newer point
        labels = {it[0]: it[1] for it in snap["items"]}
        assert labels[ivan[1]].endswith("  mine  [.iopsbackup]"), labels
        assert labels[petr[1]].endswith("  %s  [.iopsbackup]" % PETR), labels
        plan = iel.cleanup_candidates(bpy.context, "LIBRARIES", 0, True)
        assert sorted(n for _f, n in plan.points) == sorted(ivan + [bare]), plan.points

        # Petr sees his own points as his, Ivan's labelled with Ivan's name.
        iel._os_user = lambda: PETR
        snap = iel.rollback_snapshot(bpy.context, fx.src)
        assert snap["default"] == petr[1], snap["default"]
        labels = {it[0]: it[1] for it in snap["items"]}
        assert labels[petr[1]].endswith("  mine  [.iopsbackup]"), labels
        assert labels[ivan[0]].endswith("  %s  [.iopsbackup]" % IVAN), labels
        plan = iel.cleanup_candidates(bpy.context, "LIBRARIES", 0, True)
        assert sorted(n for _f, n in plan.points) == sorted(petr + [bare]), plan.points
        # Pruning to one point counts only Petr's (the bare point's tag is
        # his too): Ivan's points stay whole.
        removed = iel.prune_points(bpy.context, fx.src, protect=petr[1])
        assert sorted(removed) == sorted([petr[0], bare]), removed
        iel._os_user = lambda: IVAN
        removed = iel.prune_points(bpy.context, fx.src, protect=ivan[1])
        assert removed == [ivan[0]], removed
        assert points(fx, fx.ibkp) == [petr[1], ivan[1]]
        assert all(os.path.exists(f) for n in (petr[1], ivan[1]) for f in point_files(fx, n, fx.ibkp))
    finally:
        iel._os_user = real_user


def test_next_to_source_folder_not_creatable(fx):
    next_to_source(fx)
    _saved, _inst, _inst2, _before = start(fx)
    edit_session(top())
    src_bytes = read(fx.src)
    plan, stat = dry_run(top())
    real = os.makedirs

    def deny(path, *args, **kwargs):
        if os.path.basename(os.path.normpath(path)) == core.BACKUP_SUBFOLDER:
            raise PermissionError(13, "Access is denied", path)
        return real(path, *args, **kwargs)

    iel.os.makedirs = deny
    try:
        result = iel.commit_linked(bpy.context, top(), set(), plan, stat)
    finally:
        iel.os.makedirs = real
    assert not result["ok"] and result["error"].startswith("Could not back up src.blend: "), result
    assert read(fx.src) == src_bytes, "the source was written without a backup"
    assert listing(fx) == {"src.blend"} and stack_len() == 1, listing(fx)
    assert iel.source_points(bpy.context, fx.src) == [] and backup_listing(fx) == set()
    # A merge that fails without touching the source removes its point and
    # the .iopsbackup folder it created.
    plan, stat = dry_run(top())
    wrong = dict(plan)
    wrong["replaced"] = []
    result = iel.commit_linked(bpy.context, top(), set(), wrong, stat)
    assert not result["ok"] and result["error"].startswith("Merge failed, src.blend not written: "), result
    assert read(fx.src) == src_bytes and listing(fx) == {"src.blend"}, listing(fx)
    _plan, result = commit(top())
    assert result["ok"], result
    assert listing(fx) == {"src.blend", ".iopsbackup"} and len(points(fx, fx.ibkp)) == 1, listing(fx)


def test_newer_source_is_refused():
    assert iel.newer_source_error({"source_blender_version": list(bpy.app.version_file)}) is None
    assert iel.newer_source_error({}) is None
    major, minor = bpy.app.version_file[:2]
    older = iel.newer_source_error({"source_blender_version": [major, max(minor - 1, 0), 0]})
    assert older is None, older
    error = iel.newer_source_error({"source_blender_version": [major, minor + 1, 0]})
    assert error and "newer than this" in error and "down-version" in error, error


TESTS = [
    test_start_places_copy_and_hides_only_instancer,
    test_start_unowns_nested_same_file_collection,
    test_start_refuses_second_session_on_same_collection,
    test_cancel_removes_copy_and_restores,
    test_commit_round_trip_untouched_is_exact,
    test_commit_moves_and_adds,
    test_commit_warns_when_source_changed,
    test_commit_failure_keeps_session,
    test_nested_sessions_commit_inner_then_outer,
    test_rollback_restores_backup,
    test_backups_pruned_and_rollback_to_a_point,
    test_prune_keeps_the_point_just_written,
    test_commit_refuses_unusable_backup_folder,
    test_cancel_keeps_users_own_datablocks,
    test_commit_keeps_users_own_datablocks,
    test_commit_keeps_asset_metadata_and_relative_paths,
    test_commit_refuses_already_committed_session,
    test_commit_refuses_while_source_locked,
    test_p4_edit_output_shown_and_must_sync_refuses,
    test_next_to_source_commit_and_per_user_prune,
    test_rollback_lists_everyones_points,
    test_cleanup_backups,
    test_same_tag_users_kept_apart,
    test_next_to_source_folder_not_creatable,
]


PLAIN_TESTS = [test_newer_source_is_refused, test_backup_dir_default_and_pref]


def run_tests():
    failed = []
    for fn in PLAIN_TESTS:
        try:
            fn()
        except Exception:
            failed.append(fn.__name__)
            print("FAIL %s" % fn.__name__)
            traceback.print_exc()
        else:
            print("PASS %s" % fn.__name__)
    for fn in TESTS:
        fx = Fixture()
        try:
            fn(fx)
        except Exception:
            failed.append(fn.__name__)
            print("FAIL %s" % fn.__name__)
            traceback.print_exc()
        else:
            print("PASS %s" % fn.__name__)
        finally:
            # Drop every reference to the fixture files before removing them.
            bpy.ops.wm.read_homefile(use_empty=True)
            shutil.rmtree(fx.dir, ignore_errors=True)
    print("%d passed, %d failed" % (len(TESTS) + len(PLAIN_TESTS) - len(failed), len(failed)))
    return failed


def main():
    global RUN_DIR
    # Blender exits 0 on an uncaught exception in --python, so a failure to
    # enable the addon must exit 1 explicitly too.
    try:
        enable_addon()
    except Exception:
        print("FAIL enable_addon")
        traceback.print_exc()
        sys.stdout.flush()
        sys.exit(1)
    RUN_DIR = tempfile.mkdtemp(prefix="iops_linked_", dir=TMP_ROOT)
    prefs = addon_prefs()
    kept = ("iops_instance_edit_backup_dir", "iops_instance_edit_backup_location",
            "iops_instance_edit_prune_only_mine", "iops_instance_edit_backup_count")
    was = {name: getattr(prefs, name) for name in kept}
    try:
        failed = run_tests()
    except Exception:
        traceback.print_exc()
        failed = ["run_tests"]
    finally:
        for name, value in was.items():
            setattr(prefs, name, value)
        shutil.rmtree(RUN_DIR, ignore_errors=True)
    if os.path.exists(RUN_DIR):
        print("FAIL cleanup: %s not removed" % RUN_DIR)
        failed.append("cleanup")
    sys.stdout.flush()
    if failed:
        sys.exit(1)


main()
