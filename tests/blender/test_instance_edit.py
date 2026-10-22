"""Headless integration test of Instance Collection Edit In Place
(iops.instance_edit_start / stop / restore). Run from the repo root via:

    blender --background --factory-startup --python-exit-code 1 --python tests/blender/test_instance_edit.py

The script enables the addon itself: it puts the parent of this repo on
sys.path and enables it as module "InteractionOps", so the repo folder must
be named InteractionOps. No BLENDER_USER_SCRIPTS setup is needed, but
pointing BLENDER_USER_SCRIPTS and BLENDER_USER_CONFIG at scratch directories
is recommended: enabling the addon saves its preferences file under the user
scripts folder on quit.

Each test_* function starts from a fresh empty home file. Nothing is saved
except the tiny library .blend the linked-object test writes to a temporary
directory (removed afterwards). Prints PASS <name> / FAIL <name> plus the
traceback per test and exits with code 1 if any test failed.

Not collected by pytest (tests/conftest.py ignores tests/blender).
"""
import math
import os
import sys
import tempfile
import traceback
from types import SimpleNamespace

import bpy
from mathutils import Matrix, Vector

ADDON = "InteractionOps"
EPS = 1e-5


# Bound by enable_addon(): the addon modules under test.
ie = edit_frame = unmoved = None


def enable_addon():
    global ie, edit_frame, unmoved
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
    from InteractionOps.operators import instance_edit
    from InteractionOps.utils import instance_edit_core

    ie = instance_edit
    edit_frame = instance_edit_core.edit_frame
    unmoved = instance_edit_core.unmoved


# --- helpers -----------------------------------------------------------------

def to_matrix(m):
    return Matrix([[float(v) for v in row] for row in m])


def assert_matrix_close(a, b, what="", eps=EPS):
    for i in range(4):
        for j in range(4):
            if abs(a[i][j] - b[i][j]) > eps:
                raise AssertionError(
                    "%s: matrices differ at [%d][%d]\n%s\n!=\n%s" % (what, i, j, a, b)
                )


def assert_vector_close(a, b, what="", eps=EPS):
    if (Vector(a) - Vector(b)).length > eps:
        raise AssertionError("%s: %s != %s" % (what, tuple(a), tuple(b)))


def stack_len():
    return len(bpy.context.scene.iops_instance_edit.sessions)


def select_only(objs, active):
    vl = bpy.context.view_layer
    for o in list(vl.objects):
        o.select_set(False)
    for o in objs:
        o.select_set(True)
    vl.objects.active = active


def run_op(name, active=None, select=None):
    """Select ``select`` (default: [active]) and make ``active`` active when
    it is given, then run iops.<name>. Returns the operator result set."""
    if active is not None:
        select_only(select if select is not None else [active], active)
    return getattr(bpy.ops.iops, name)()


def mesh_obj(name, coll, loc=(0, 0, 0)):
    ob = bpy.data.objects.new(name, bpy.data.meshes.new(name))
    ob.location = loc
    coll.objects.link(ob)
    return ob


def lc_asset():
    return bpy.context.view_layer.layer_collection.children["Asset"]


def build_scene():
    """Fresh empty file with: collection Asset (excluded) holding Cube,
    Child (parent Cube) and Child2 (parent Ext, outside Asset); child
    collection Sub (excluded) holding Sphere; Asset.instance_offset (1,0,0);
    instancers A at (10,0,0) rotated 90 deg about Z and B at (0,10,0); Ext in
    the scene collection. A is selected and active."""
    bpy.ops.wm.read_homefile(use_empty=True)
    scene = bpy.context.scene
    vl = bpy.context.view_layer

    asset = bpy.data.collections.new("Asset")
    scene.collection.children.link(asset)
    sub = bpy.data.collections.new("Sub")
    asset.children.link(sub)
    asset.instance_offset = (1, 0, 0)

    cube = mesh_obj("Cube", asset)
    child = mesh_obj("Child", asset, (0, 0, 2))
    child.parent = cube
    sphere = mesh_obj("Sphere", sub, (0, 3, 0))

    ext = bpy.data.objects.new("Ext", None)
    ext.location = (-4, 2, 1)
    ext.rotation_euler = (0, 0, math.radians(30))
    scene.collection.objects.link(ext)
    child2 = mesh_obj("Child2", asset, (1, 1, 0))
    child2.parent = ext

    def instancer(name, loc, rot_z=0.0):
        e = bpy.data.objects.new(name, None)
        e.instance_type = "COLLECTION"
        e.instance_collection = asset
        e.location = loc
        e.rotation_euler = (0, 0, rot_z)
        scene.collection.objects.link(e)
        return e

    A = instancer("A", (10, 0, 0), math.radians(90))
    B = instancer("B", (0, 10, 0))
    vl.update()

    lca = vl.layer_collection.children["Asset"]
    lca.children["Sub"].exclude = True
    lca.exclude = True
    vl.update()
    select_only([A], A)

    return dict(scene=scene, vl=vl, asset=asset, sub=sub, cube=cube, child=child,
                child2=child2, sphere=sphere, ext=ext, A=A, B=B)


def expected_frame(s):
    return to_matrix(edit_frame(s["A"].matrix_world, s["asset"].instance_offset))


def channels(o):
    """Everything Stop/Restore write back, as plain values compared with ==
    (bit-exact, no tolerance)."""
    return (
        tuple(o.location),
        o.rotation_mode,
        tuple(o.rotation_euler),
        tuple(o.rotation_quaternion),
        tuple(o.rotation_axis_angle),
        tuple(o.scale),
        o.parent,
        o.parent_type,
        o.parent_bone,
        tuple(tuple(r) for r in o.matrix_parent_inverse),
    )


def run_capturing(op_name):
    """Run iops.<op_name> and return (result, names it reported missing).
    _finish(missing) is where the operator turns those names into
    self.report("Missing: ..."); self.report itself cannot be wrapped (RNA
    functions win attribute lookup on a registered operator instance)."""
    cls = {
        "instance_edit_stop": ie.IOPS_OT_instance_edit_stop,
        "instance_edit_restore": ie.IOPS_OT_instance_edit_restore,
    }[op_name]
    reported = []
    orig_finish = cls._finish

    def capture(self, missing):
        reported.extend(missing)
        return orig_finish(self, missing)

    cls._finish = capture
    try:
        res = run_op(op_name)
    finally:
        del cls._finish
    assert cls._finish is orig_finish
    return res, reported


# --- tests -------------------------------------------------------------------

def test_start_places_roots():
    s = build_scene()
    cube, child, child2, sphere = s["cube"], s["child"], s["child2"], s["sphere"]
    frame = expected_frame(s)
    world = {o.name: o.matrix_world.copy() for o in (cube, child, child2, sphere)}
    child_basis = child.matrix_basis.copy()

    assert run_op("instance_edit_start", s["A"]) == {"FINISHED"}
    s["vl"].update()

    # Offset (1,0,0) rotated 90 deg about Z, then the instancer's (10,0,0).
    assert_vector_close(frame.translation, (10, -1, 0), "frame translation")
    for root in (cube, sphere, child2):
        assert_matrix_close(root.matrix_world, frame @ world[root.name], root.name + " world")
    assert_matrix_close(child.matrix_basis, child_basis, "Child basis")
    assert_matrix_close(child.matrix_world, frame @ world["Child"], "Child world")
    assert stack_len() == 1
    assert run_op("instance_edit_stop") == {"FINISHED"}


def test_restore_external_parent():
    s = build_scene()
    child2, ext = s["child2"], s["ext"]
    before = child2.matrix_basis.copy()
    ext_world = ext.matrix_world.copy()
    ext_basis = ext.matrix_basis.copy()

    assert run_op("instance_edit_start", s["A"]) == {"FINISHED"}
    child2.location += Vector((0, 0, 3))
    s["vl"].update()
    assert run_op("instance_edit_restore") == {"FINISHED"}
    s["vl"].update()

    assert_matrix_close(child2.matrix_basis, before, "Child2 basis")
    assert child2.parent == ext
    assert_matrix_close(ext.matrix_basis, ext_basis, "Ext basis")
    assert_matrix_close(ext.matrix_world, ext_world, "Ext world")
    assert stack_len() == 0


def test_start_unexcludes_descendants():
    s = build_scene()
    sphere = s["sphere"]
    frame = expected_frame(s)
    sphere_world = sphere.matrix_world.copy()
    assert lc_asset().exclude and lc_asset().children["Sub"].exclude
    assert not sphere.visible_get()

    assert run_op("instance_edit_start", s["A"]) == {"FINISHED"}
    s["vl"].update()
    assert not lc_asset().exclude and not lc_asset().children["Sub"].exclude
    assert sphere.visible_get(), "Sphere not visible after Start"
    assert_matrix_close(sphere.matrix_world, frame @ sphere_world, "Sphere world")

    assert run_op("instance_edit_stop") == {"FINISHED"}
    assert lc_asset().exclude, "Asset not excluded after Stop"
    assert lc_asset().children["Sub"].exclude, "Sub not excluded after Stop"
    assert stack_len() == 0


def test_stop_keeps_edits_and_new_objects():
    s = build_scene()
    vl, asset, A, B = s["vl"], s["asset"], s["A"], s["B"]
    cube, child, sphere = s["cube"], s["child"], s["sphere"]
    frame = expected_frame(s)
    pre_basis = {o.name: o.matrix_basis.copy() for o in (child, sphere)}

    assert run_op("instance_edit_start", A) == {"FINISHED"}
    assert vl.active_layer_collection.collection == asset
    cube.location.x += 1  # Cube has no parent: +1 along world X
    new = mesh_obj("NewCube", vl.active_layer_collection.collection, (3, 4, 5))
    vl.update()
    cube_world = cube.matrix_world.copy()
    new_world = new.matrix_world.copy()
    assert list(new.users_collection) == [asset], "new object not in Asset"

    assert run_op("instance_edit_stop") == {"FINISHED"}
    vl.update()

    expected_cube = to_matrix(unmoved(frame, cube_world))
    assert_vector_close(expected_cube.translation, (0, -1, 0), "expected Cube translation")
    assert_matrix_close(cube.matrix_basis, expected_cube, "Cube basis keeps the edit")
    assert_matrix_close(new.matrix_world, frame.inverted() @ new_world, "NewCube world")
    assert list(new.users_collection) == [asset], "NewCube left Asset"
    for o in (child, sphere):
        assert_matrix_close(o.matrix_basis, pre_basis[o.name], o.name + " basis")
    assert not A.hide_get() and not B.hide_get()
    assert lc_asset().exclude and lc_asset().children["Sub"].exclude
    assert stack_len() == 0
    assert vl.objects.active == A and A.select_get()
    assert vl.active_layer_collection == vl.layer_collection


def test_stop_after_instancer_deleted():
    s = build_scene()
    B = s["B"]
    assert run_op("instance_edit_start", s["A"]) == {"FINISHED"}
    assert B.hide_get()
    bpy.data.objects.remove(s["A"])
    assert run_op("instance_edit_stop") == {"FINISHED"}
    assert stack_len() == 0
    assert not B.hide_get(), "B still hidden after Stop"
    assert B.visible_get()
    assert lc_asset().exclude


def test_restore_after_object_deleted():
    s = build_scene()
    cube = s["cube"]
    pre = cube.matrix_basis.copy()
    assert run_op("instance_edit_start", s["A"]) == {"FINISHED"}
    session = s["scene"].iops_instance_edit.sessions[-1]
    assert "Sphere" in [r.name for r in session.objects]
    bpy.data.objects.remove(s["sphere"])
    cube.location.x += 2

    res, reported = run_capturing("instance_edit_restore")

    assert res == {"FINISHED"}
    assert stack_len() == 0
    assert "Sphere" in reported, "report does not mention Sphere: %r" % reported
    assert_matrix_close(cube.matrix_basis, pre, "Cube basis")
    assert not s["A"].hide_get() and lc_asset().exclude


def test_header_draw_with_session_no_selection():
    s = build_scene()
    vl = s["vl"]
    assert run_op("instance_edit_start", s["A"]) == {"FINISHED"}
    for o in list(vl.objects):
        o.select_set(False)
    bpy.context.view_layer.objects.active = None
    assert bpy.context.view_layer.objects.active is None
    assert ie.IOPS_OT_instance_edit_restore.poll(bpy.context) is True
    assert ie.IOPS_OT_instance_edit_stop.poll(bpy.context) is True
    assert bpy.ops.iops.instance_edit_stop() == {"FINISHED"}
    assert stack_len() == 0


def test_poll_refuses_linked_and_nested_session():
    s = build_scene()
    A, asset = s["A"], s["asset"]

    # Session present: Start refuses even with the instancer active.
    assert ie.can_start(bpy.context)[0] is True
    assert run_op("instance_edit_start", A) == {"FINISHED"}
    select_only([A], A)
    ok, reason = ie.can_start(bpy.context)
    assert ok is False and "in progress" in reason, reason
    assert not bpy.ops.iops.instance_edit_start.poll()
    assert run_op("instance_edit_restore") == {"FINISHED"}
    select_only([A], A)
    assert ie.can_start(bpy.context)[0] is True

    # An object linked from a library inside Asset: Start refuses.
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        path = os.path.join(tmp, "iops_instance_edit_lib.blend")
        src = bpy.data.objects.new("LibObj", bpy.data.meshes.new("LibObj"))
        bpy.data.libraries.write(path, {src})
        bpy.data.objects.remove(src)
        with bpy.data.libraries.load(path, link=True) as (_data_from, data_to):
            data_to.objects = ["LibObj"]
        linked = data_to.objects[0]
        assert linked is not None and linked.library is not None
        asset.objects.link(linked)
        select_only([A], A)
        ok, reason = ie.can_start(bpy.context)
        assert ok is False and "LibObj" in reason, reason
        assert not bpy.ops.iops.instance_edit_start.poll()
        assert stack_len() == 0
        # Drop the library link before the temp file goes away.
        bpy.ops.wm.read_homefile(use_empty=True)


def test_stop_round_trip_is_exact():
    s = build_scene()
    vl, A, cube = s["vl"], s["A"], s["cube"]
    cube.location = (1.1, 2.2, 3.3)
    cube.rotation_euler = [math.radians(v) for v in (170, -60, 400)]
    cube.scale = (-1, 1, 1)
    A.rotation_euler = [math.radians(v) for v in (20, -35, 110)]
    A.scale = (2, 2, 2)
    vl.update()
    objs = [s[k] for k in ("cube", "child", "child2", "sphere")]
    before = {o.name: channels(o) for o in objs}

    for cycle in range(3):
        assert run_op("instance_edit_start", A) == {"FINISHED"}
        vl.update()
        assert channels(cube) != before["Cube"], "Start did not move Cube"
        assert run_op("instance_edit_stop") == {"FINISHED"}
        vl.update()
        for o in objs:
            assert channels(o) == before[o.name], "cycle %d %s: %r != %r" % (
                cycle, o.name, channels(o), before[o.name])
    assert stack_len() == 0


def test_start_refuses_non_uniform_scale():
    s = build_scene()
    A = s["A"]
    A.scale = (1, 3, 1)
    s["vl"].update()
    select_only([A], A)
    ok, reason = ie.can_start(bpy.context)
    assert ok is False, reason
    assert reason == "Instance is non-uniformly scaled or sheared; edit a uniformly scaled instance", reason
    assert not bpy.ops.iops.instance_edit_start.poll()

    # Uniform again: allowed.
    A.scale = (3, 3, 3)
    s["vl"].update()
    assert ie.can_start(bpy.context)[0] is True


def test_start_refuses_zero_scale():
    s = build_scene()
    A = s["A"]
    A.scale = (0, 0, 0)
    s["vl"].update()
    select_only([A], A)
    ok, reason = ie.can_start(bpy.context)
    assert ok is False
    assert reason == "Instance is non-uniformly scaled or sheared; edit a uniformly scaled instance", reason
    assert not bpy.ops.iops.instance_edit_start.poll()
    assert stack_len() == 0


def test_restore_after_reparent():
    s = build_scene()
    vl, cube, child = s["vl"], s["cube"], s["child"]
    cube2 = mesh_obj("Cube2", s["asset"], (5, 0, 0))
    vl.update()
    world = {o.name: o.matrix_world.copy() for o in (cube, child)}
    before = {o.name: channels(o) for o in (cube, child, cube2)}

    assert run_op("instance_edit_start", s["A"]) == {"FINISHED"}
    vl.update()
    # Ctrl+P (Object, keep transform): Cube under Cube2.
    cube.parent = cube2
    cube.matrix_parent_inverse = cube2.matrix_world.inverted()
    # Alt+P (clear, keep transform): Child off Cube.
    child_world = child.matrix_world.copy()
    child.parent = None
    child.matrix_world = child_world
    vl.update()
    assert run_op("instance_edit_restore") == {"FINISHED"}
    vl.update()

    assert cube.parent is None and child.parent == cube
    for o in (cube, child, cube2):
        assert channels(o) == before[o.name], "%s: %r != %r" % (o.name, channels(o), before[o.name])
    for o in (cube, child):
        assert_matrix_close(o.matrix_world, world[o.name], o.name + " world")
    assert stack_len() == 0


def test_restore_ignores_object_that_took_the_name():
    s = build_scene()
    vl = s["vl"]
    outsider = mesh_obj("Outsider", s["scene"].collection, (50, 50, 50))
    vl.update()
    out_before = channels(outsider)
    out_world = outsider.matrix_world.copy()

    assert run_op("instance_edit_start", s["A"]) == {"FINISHED"}
    bpy.data.objects.remove(s["cube"])
    outsider.name = "Cube"
    assert outsider.name == "Cube"
    res, reported = run_capturing("instance_edit_restore")
    vl.update()

    assert res == {"FINISHED"} and stack_len() == 0
    assert "Cube" in reported, reported
    assert channels(outsider) == out_before, "outside object was touched"
    assert_matrix_close(outsider.matrix_world, out_world, "outside object world")
    assert not outsider.hide_get() and not outsider.hide_select


def test_stop_after_collection_deleted():
    s = build_scene()
    scene, vl, asset, sub, A, B = s["scene"], s["vl"], s["asset"], s["sub"], s["A"], s["B"]
    cube, child, child2, sphere = s["cube"], s["child"], s["child2"], s["sphere"]
    frame = expected_frame(s)
    before = {o.name: channels(o) for o in (child, child2, sphere)}

    assert run_op("instance_edit_start", A) == {"FINISHED"}
    cube.location.x += 1
    vl.update()
    cube_world = cube.matrix_world.copy()
    # Outliner Delete: the content moves up to the parent, the collection goes.
    for o in list(asset.objects):
        scene.collection.objects.link(o)
    scene.collection.children.link(sub)
    bpy.data.collections.remove(asset)
    vl.update()

    res, reported = run_capturing("instance_edit_stop")
    vl.update()

    assert res == {"FINISHED"} and stack_len() == 0
    assert reported.count("Asset") == 1, reported
    # The edit is kept and Cube is back in the collection's native frame.
    assert_matrix_close(cube.matrix_world, frame.inverted() @ cube_world, "Cube world")
    for o in (child, child2, sphere):
        assert channels(o) == before[o.name], "%s: %r != %r" % (o.name, channels(o), before[o.name])
    assert not A.hide_get() and not B.hide_get()


def test_hide_select_cleared_and_restored():
    s = build_scene()
    asset, sub, cube = s["asset"], s["sub"], s["cube"]
    targets = [s[k] for k in ("cube", "child", "child2", "sphere")]
    asset.hide_select = True
    sub.hide_select = True
    cube.hide_select = True

    assert run_op("instance_edit_start", s["A"]) == {"FINISHED"}
    s["vl"].update()
    assert not asset.hide_select and not sub.hide_select and not cube.hide_select
    for o in targets:
        assert o.select_get(), o.name + " not selected after Start"

    assert run_op("instance_edit_stop") == {"FINISHED"}
    assert asset.hide_select and sub.hide_select and cube.hide_select
    assert not s["child"].hide_select


def test_hidden_ancestor_layer_collection():
    bpy.ops.wm.read_homefile(use_empty=True)
    scene = bpy.context.scene
    vl = bpy.context.view_layer
    parent = bpy.data.collections.new("Parent")
    scene.collection.children.link(parent)
    asset = bpy.data.collections.new("Asset")
    parent.children.link(asset)
    cube = mesh_obj("Cube", asset)
    inst = bpy.data.objects.new("Inst", None)
    inst.instance_type = "COLLECTION"
    inst.instance_collection = asset
    inst.location = (10, 0, 0)
    scene.collection.objects.link(inst)
    vl.update()
    vl.layer_collection.children["Parent"].hide_viewport = True
    vl.update()
    assert not cube.visible_get()

    assert run_op("instance_edit_start", inst) == {"FINISHED"}
    vl.update()
    assert cube.visible_get(), "Cube not visible after Start"

    assert run_op("instance_edit_stop") == {"FINISHED"}
    assert vl.layer_collection.children["Parent"].hide_viewport
    assert not inst.hide_get()
    assert stack_len() == 0


def test_stop_on_recorded_view_layer():
    s = build_scene()
    scene, vl1, A, B = s["scene"], s["vl"], s["A"], s["B"]
    vl2 = scene.view_layers.new("VL2")
    vl2_asset = vl2.layer_collection.children["Asset"]
    vl2_asset.exclude = False
    A.hide_set(True, view_layer=vl2)
    vl2_state = (vl2_asset.exclude, vl2_asset.hide_viewport,
                 A.hide_get(view_layer=vl2), B.hide_get(view_layer=vl2))
    assert vl2_state == (False, False, True, False)

    assert run_op("instance_edit_start", A) == {"FINISHED"}
    with bpy.context.temp_override(view_layer=vl2):
        assert bpy.context.view_layer == vl2
        assert bpy.ops.iops.instance_edit_stop() == {"FINISHED"}
    assert stack_len() == 0

    lca = vl1.layer_collection.children["Asset"]
    assert lca.exclude and lca.children["Sub"].exclude, "first view layer not restored"
    assert not A.hide_get(view_layer=vl1) and not B.hide_get(view_layer=vl1)
    vl2_asset = vl2.layer_collection.children["Asset"]
    assert (vl2_asset.exclude, vl2_asset.hide_viewport,
            A.hide_get(view_layer=vl2), B.hide_get(view_layer=vl2)) == vl2_state, "VL2 touched"


class _StubRow:
    def __init__(self, log):
        self.log = log
        self.alert = False

    def operator(self, idname, **_kw):
        self.log.append(idname)


class _StubLayout:
    def __init__(self):
        self.log = []

    def separator(self):
        self.log.append("|")

    def row(self, align=False):
        return _StubRow(self.log)


def _draw_header(mode):
    from InteractionOps.ui.iops_instance_edit_header import draw_iops_instance_edit_header

    layout = _StubLayout()
    ctx = SimpleNamespace(scene=bpy.context.scene, mode=mode, preferences=bpy.context.preferences)
    draw_iops_instance_edit_header(SimpleNamespace(layout=layout), ctx)
    return layout.log


def test_header_pair_in_every_mode():
    s = build_scene()
    prefs = bpy.context.preferences.addons[ADDON].preferences
    pref_before = prefs.iops_instance_edit_header
    pair = ["|", "iops.instance_edit_stop", "iops.instance_edit_restore"]
    modes = ("OBJECT", "EDIT_MESH", "EDIT_CURVE", "SCULPT", "PAINT_WEIGHT", "POSE")
    try:
        prefs.iops_instance_edit_header = True
        assert _draw_header("OBJECT") == ["|", "iops.instance_edit_start"]
        assert _draw_header("EDIT_MESH") == ["|", "iops.instance_edit_start"]
        assert _draw_header("SCULPT") == [], "idle button or stray separator outside Object/Edit Mode"
        prefs.iops_instance_edit_header = False
        assert _draw_header("OBJECT") == [], "stray separator with the button turned off"

        assert run_op("instance_edit_start", s["A"]) == {"FINISHED"}
        for pref in (False, True):
            prefs.iops_instance_edit_header = pref
            for mode in modes:
                assert _draw_header(mode) == pair, (mode, pref, _draw_header(mode))
        assert run_op("instance_edit_stop") == {"FINISHED"}
    finally:
        prefs.iops_instance_edit_header = pref_before


def test_session_ops_require_local_kind():
    s = build_scene()
    assert run_op("instance_edit_start", s["A"]) == {"FINISHED"}
    session = s["scene"].iops_instance_edit.sessions[-1]
    session.kind = "LINKED"
    assert not bpy.ops.iops.instance_edit_stop.poll()
    assert not bpy.ops.iops.instance_edit_restore.poll()
    session.kind = "LOCAL"
    assert bpy.ops.iops.instance_edit_stop.poll()
    assert run_op("instance_edit_stop") == {"FINISHED"}


TESTS = [
    test_start_places_roots,
    test_restore_external_parent,
    test_start_unexcludes_descendants,
    test_stop_keeps_edits_and_new_objects,
    test_stop_after_instancer_deleted,
    test_restore_after_object_deleted,
    test_header_draw_with_session_no_selection,
    test_poll_refuses_linked_and_nested_session,
    test_stop_round_trip_is_exact,
    test_start_refuses_non_uniform_scale,
    test_start_refuses_zero_scale,
    test_restore_after_reparent,
    test_restore_ignores_object_that_took_the_name,
    test_stop_after_collection_deleted,
    test_hide_select_cleared_and_restored,
    test_hidden_ancestor_layer_collection,
    test_stop_on_recorded_view_layer,
    test_header_pair_in_every_mode,
    test_session_ops_require_local_kind,
]


def main():
    # Blender exits 0 on an uncaught exception in --python, so a failure to
    # enable the addon must exit 1 explicitly too.
    try:
        enable_addon()
    except Exception:
        print("FAIL enable_addon")
        traceback.print_exc()
        sys.stdout.flush()
        sys.exit(1)
    failed = []
    for fn in TESTS:
        try:
            fn()
        except Exception:
            failed.append(fn.__name__)
            print("FAIL %s" % fn.__name__)
            traceback.print_exc()
        else:
            print("PASS %s" % fn.__name__)
    print("%d passed, %d failed" % (len(TESTS) - len(failed), len(failed)))
    sys.stdout.flush()
    if failed:
        sys.exit(1)


main()
