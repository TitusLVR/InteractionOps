"""Headless test of the Instance Edit merge worker
(operators/instance_edit_merge_worker.py). Run from the repo root via:

    blender --background --factory-startup --python-exit-code 1 --python tests/blender/test_instance_edit_merge_worker.py

Recommended: point BLENDER_USER_SCRIPTS and BLENDER_USER_CONFIG at scratch
directories for the run, so nothing touches your Blender user folders.

Enables nothing: the worker is a standalone script, spawned here through
``bpy.app.binary_path`` exactly like the Commit operator runs it. Every test
builds its own fixture in a fresh temp directory (under ``$IOPS_TEST_TMP``
when set, else the system temp dir) and removes it afterwards:

- ``third.blend``: object ``Rock`` (a third library),
- ``source.blend`` (saved compressed): collection ``C`` (``Cube`` with
  ``CubeMesh`` + ``SharedMat``, ``Inst`` instancing the same-file
  collection ``N``), collection ``Other`` (``Lamp`` with ``LampMesh`` using
  ``SharedMat``), an unrelated image ``SrcTex`` with an absolute path,
- ``source.iops_commit-0123abcd.blend``: what Commit exports for a session on ``C``:
  the appended copy ``C [edit]`` with one ``CubeMesh`` vertex moved,
  ``SharedMat`` turned green, a new object ``Lamp`` (own mesh, material and
  image ``NewTex``), ``Rock`` linked from ``third.blend``, ``Inst``
  re-pointed at the linked ``N`` (as Start does for nested same-file
  collections), every owned ID tagged ``iops_commit = <row index>``.

With ``assets``: ``C`` and ``SharedMat`` are asset-marked in the source
(catalog, description, author, copyright, license, tags, an asset custom
property) and the editing file links ``C`` before appending it, as Start
does, which drops the copies' asset marks; ``Cube`` also carries a text
``Notes`` (absolute file path) through a custom property.

Prints PASS <name> / FAIL <name> plus the traceback per test and exits with
code 1 if any test failed. Not collected by pytest (tests/conftest.py
ignores tests/blender).
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import traceback

import bpy

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
WORKER = os.path.join(REPO, "operators", "instance_edit_merge_worker.py")
TMP_ROOT = os.environ.get("IOPS_TEST_TMP") or None
TAG = "iops_commit"
INSTANCE_TAG = "iops_commit_instance"
CATALOG = "c8b7f6a4-2f27-4b7b-9c1e-1a2b3c4d5e6f"
RED = (1.0, 0.0, 0.0, 1.0)
GREEN = (0.0, 1.0, 0.0, 1.0)
EPS = 1e-5


# --- fixture -------------------------------------------------------------------

def _tri_mesh(name):
    me = bpy.data.meshes.new(name)
    me.from_pydata([(0, 0, 0), (1, 0, 0), (0, 1, 0)], [], [(0, 1, 2)])
    return me


def _write_png(path):
    img = bpy.data.images.new(os.path.basename(path), 2, 2)
    img.filepath_raw = path
    img.file_format = "PNG"
    img.save()
    bpy.data.images.remove(img)


def _id_attrs():
    out = []
    for attr in dir(bpy.data):
        if attr.startswith("_") or attr in ("libraries", "all_ids"):
            continue
        value = getattr(bpy.data, attr, None)
        if not isinstance(value, bpy.types.bpy_prop_collection):
            continue
        prop = bpy.data.bl_rna.properties.get(attr)
        fixed = getattr(prop, "fixed_type", None)
        if fixed is None or fixed.identifier == "ID":
            continue
        if not issubclass(getattr(bpy.types, fixed.identifier, object), bpy.types.ID):
            continue
        out.append(attr)
    return out


def _local_ids():
    return [(a, i) for a in _id_attrs() for i in getattr(bpy.data, a) if i.library is None]


class Fixture:
    pass


def _mark(id_, description):
    id_.asset_mark()
    ad = id_.asset_data
    ad.catalog_id = CATALOG
    ad.description = description
    ad.author = "someone"
    ad.copyright = "(c) studio"
    ad.license = "CC0"
    ad.tags.new("tagA")
    ad.tags.new("tagB")
    ad["studio"] = {"lod": 2}


def assert_asset(id_, description):
    ad = id_.asset_data
    assert ad is not None, "%s lost its asset mark" % id_.name
    assert (ad.catalog_id, ad.description, ad.author, ad.copyright, ad.license) == (
        CATALOG, description, "someone", "(c) studio", "CC0"), (
        ad.catalog_id, ad.description, ad.author, ad.copyright, ad.license)
    assert sorted(t.name for t in ad.tags) == ["tagA", "tagB"], [t.name for t in ad.tags]
    assert ad["studio"].to_dict() == {"lod": 2}, ad["studio"]


def build_fixture(tag_instance=True, extras=False, view_layers=False, shared_child=False,
                  dup_instancer=False, empty_instancer=False, assets=False):
    fx = Fixture()
    fx.dir = tempfile.mkdtemp(prefix="iops_merge_", dir=TMP_ROOT)
    fx.source = os.path.join(fx.dir, "source.blend")
    fx.third = os.path.join(fx.dir, "third.blend")
    fx.temp_blend = os.path.join(fx.dir, "source.iops_commit-0123abcd.blend")
    fx.temp_json = os.path.join(fx.dir, "source.iops_commit-0123abcd.json")
    fx.result = os.path.join(fx.dir, "result.json")
    os.makedirs(os.path.join(fx.dir, "tex"))
    fx.src_png = os.path.join(fx.dir, "tex", "src.png")
    fx.new_png = os.path.join(fx.dir, "tex", "new.png")

    # third library
    bpy.ops.wm.read_homefile(use_empty=True)
    _write_png(fx.src_png)
    _write_png(fx.new_png)
    rock = bpy.data.objects.new("Rock", _tri_mesh("RockMesh"))
    bpy.context.scene.collection.objects.link(rock)
    bpy.ops.wm.save_as_mainfile(filepath=fx.third)

    # source
    bpy.ops.wm.read_homefile(use_empty=True)
    scene = bpy.context.scene
    mat = bpy.data.materials.new("SharedMat")
    mat.diffuse_color = RED
    cube_me = _tri_mesh("CubeMesh")
    cube_me.materials.append(mat)
    c = bpy.data.collections.new("C")
    scene.collection.children.link(c)
    c.objects.link(bpy.data.objects.new("Cube", cube_me))
    n = bpy.data.collections.new("N")
    n.objects.link(bpy.data.objects.new("NObj", None))
    inst = bpy.data.objects.new("Inst", None)
    inst.instance_type = "COLLECTION"
    inst.instance_collection = n
    c.objects.link(inst)
    lamp_me = _tri_mesh("LampMesh")
    lamp_me.materials.append(mat)
    other = bpy.data.collections.new("Other")
    scene.collection.children.link(other)
    other.objects.link(bpy.data.objects.new("Lamp", lamp_me))
    if extras:
        # Extra: only in C; Pair: in C and Other. The session deletes both.
        c.objects.link(bpy.data.objects.new("Extra", None))
        pair = bpy.data.objects.new("Pair", None)
        c.objects.link(pair)
        other.objects.link(pair)
    if shared_child:
        # D: child of C and of Other; Both: in C and Other with its own mesh.
        d = bpy.data.collections.new("D")
        c.children.link(d)
        other.children.link(d)
        d.objects.link(bpy.data.objects.new("DObj", None))
        both = bpy.data.objects.new("Both", _tri_mesh("BothMesh"))
        both.data.materials.append(mat)  # SharedMat: also a direct outside user (LampMesh)
        c.objects.link(both)
        other.objects.link(both)
    if empty_instancer:
        empty = bpy.data.objects.new("EmptyInst", None)
        empty.instance_type = "COLLECTION"
        c.objects.link(empty)
    if view_layers:
        sub = bpy.data.collections.new("Sub")
        c.children.link(sub)
        sub.objects.link(bpy.data.objects.new("SubObj", None))
        c.children.link(bpy.data.collections.new("Sub2"))
        bpy.data.scenes.new("S2").collection.children.link(c)
        vl1 = scene.view_layers[0]
        vl2 = scene.view_layers.new("VL2")
        # VL2: Sub excluded on its own, then C excluded (Sub2 only through C).
        vl2.layer_collection.children["C"].children["Sub"].exclude = True
        vl2.layer_collection.children["C"].exclude = True
        vl1.layer_collection.children["C"].hide_viewport = True
        vl1.layer_collection.children["C"].children["Sub"].holdout = True
        vl1.layer_collection.children["C"].children["Sub"].indirect_only = True
        bpy.data.objects["Cube"].hide_set(True, view_layer=vl1)
    if assets:
        _mark(c, "coll desc")
        _mark(mat, "mat desc")
    src_tex = bpy.data.images.load(fx.src_png)
    src_tex.name = "SrcTex"
    src_tex.use_fake_user = True
    fx.src_tex_path = src_tex.filepath_raw
    bpy.ops.wm.save_as_mainfile(filepath=fx.source, compress=True, relative_remap=False)

    # editing file: Start's append, the session's edits, Commit's export
    bpy.ops.wm.read_homefile(use_empty=True)
    scene = bpy.context.scene
    if assets:
        with bpy.data.libraries.load(fx.source, link=True) as (data_from, data_to):
            data_to.collections = ["C"]
    before = {(a, i.as_pointer()) for a, i in _local_ids()}
    with bpy.data.libraries.load(fx.source, link=False) as (data_from, data_to):
        data_to.collections = ["C"]
    copy = data_to.collections[0]
    if assets:
        assert copy.asset_data is None and bpy.data.materials[("SharedMat", None)].asset_data is None, \
            "the append kept the asset marks: the fixture no longer reproduces the defect"
        # Name lookups below mean the local copies: drop the linked ones.
        bpy.data.libraries.remove(next(lib for lib in bpy.data.libraries))
    owned = [(a, i, i.name) for a, i in _local_ids() if (a, i.as_pointer()) not in before]
    # Start 3b: the nested same-file collection goes back to the link.
    with bpy.data.libraries.load(fx.source, link=True) as (data_from, data_to):
        data_to.collections = ["N"]
    linked_n = data_to.collections[0]
    inst = bpy.data.objects["Inst"]
    n_copy = inst.instance_collection
    inst.instance_collection = linked_n
    dropped = {n_copy.as_pointer(), bpy.data.objects["NObj"].as_pointer()}
    owned = [o for o in owned if o[1].as_pointer() not in dropped]
    bpy.data.objects.remove(bpy.data.objects["NObj"])
    bpy.data.collections.remove(n_copy)
    if extras:
        gone = {bpy.data.objects[n].as_pointer() for n in ("Extra", "Pair")}
        owned = [o for o in owned if o[1].as_pointer() not in gone]
        bpy.data.objects.remove(bpy.data.objects["Extra"])
        bpy.data.objects.remove(bpy.data.objects["Pair"])
    if shared_child:
        bpy.data.collections["D"].objects.link(bpy.data.objects.new("XNew", None))
        bpy.data.meshes["BothMesh"].vertices[0].co.x += 5.0
    if dup_instancer:
        # A Shift+D duplicate made during the session: no tags at all.
        dup = inst.copy()
        dup.name = "InstDup"
        copy.objects.link(dup)
    copy.name = "C [edit]"
    scene.collection.children.link(copy)

    bpy.data.meshes["CubeMesh"].vertices[0].co.x += 1.0
    bpy.data.materials["SharedMat"].diffuse_color = GREEN
    new_me = _tri_mesh("LampNewMesh")
    new_mat = bpy.data.materials.new("LampNewMat")
    if new_mat.node_tree is None:
        new_mat.use_nodes = True
    node = new_mat.node_tree.nodes.new("ShaderNodeTexImage")
    node.image = bpy.data.images.load(fx.new_png)
    node.image.name = "NewTex"
    new_me.materials.append(new_mat)
    copy.objects.link(bpy.data.objects.new("Lamp", new_me))
    with bpy.data.libraries.load(fx.third, link=True) as (data_from, data_to):
        data_to.objects = ["Rock"]
    copy.objects.link(data_to.objects[0])
    if assets:
        notes = bpy.data.texts.new("Notes")
        notes.write("notes")
        notes.filepath = os.path.join(fx.dir, "notes.txt")
        bpy.data.objects[("Cube", None)]["notes"] = notes

    fx.rows = []
    for index, (attr, id_, source_name) in enumerate(owned):
        id_[TAG] = index
        fx.rows.append({"index": index, "id_type": attr, "source_name": source_name})
    if tag_instance:
        inst[INSTANCE_TAG] = "N"
    # As Commit exports. With assets every path is absolute instead, so the
    # worker's own relativising of appended paths is what gets tested.
    bpy.data.libraries.write(fx.temp_blend, {copy}, path_remap="ABSOLUTE" if assets else "RELATIVE",
                             fake_user=False)
    bpy.ops.wm.read_homefile(use_empty=True)
    return fx


def cleanup(fx):
    bpy.ops.wm.read_homefile(use_empty=True)
    shutil.rmtree(fx.dir, ignore_errors=True)


def run_worker(fx, mode, update_shared=(), expected_plan=None):
    with open(fx.temp_json, "w", encoding="utf-8") as fh:
        json.dump({
            "temp_blend": fx.temp_blend,
            "source_coll_name": "C",
            "copy_coll_name": "C [edit]",
            "owned": fx.rows,
            "update_shared": [list(k) for k in update_shared],
            "expected_plan": expected_plan,
        }, fh)
    if os.path.exists(fx.result):
        os.remove(fx.result)
    cmd = [bpy.app.binary_path, "--background", "--factory-startup", "--disable-autoexec",
           fx.source, "--python", WORKER, "--", fx.temp_json, mode, fx.result]
    done = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=300)
    result = {}
    if os.path.exists(fx.result):
        with open(fx.result, encoding="utf-8") as fh:
            result = json.load(fh)
    fx.last_output = done.stdout.decode("utf-8", "replace")
    return done.returncode, result


def file_state(path):
    with open(path, "rb") as fh:
        data = fh.read()
    return data, os.path.getmtime(path)


def check_ok(fx, code, result):
    if code != 0 or not result.get("ok"):
        raise AssertionError("worker failed (exit %s): %s\n%s" % (
            code, result.get("error"), fx.last_output[-4000:]))


def keys(plan, name):
    return {tuple(k) for k in plan[name]}


def reopen(fx):
    bpy.ops.wm.open_mainfile(filepath=fx.source)


def no_tags_anywhere():
    attrs = _id_attrs() + ["libraries"]
    for attr in attrs:
        for i in getattr(bpy.data, attr):
            assert TAG not in i.keys() and INSTANCE_TAG not in i.keys(), "tag left on %s" % i.name


def assert_color(mat, rgba):
    assert all(abs(a - b) < EPS for a, b in zip(mat.diffuse_color, rgba)), tuple(mat.diffuse_color)


def plan_then_write(fx, update_shared=()):
    code, planned = run_worker(fx, "plan", update_shared)
    check_ok(fx, code, planned)
    code, written = run_worker(fx, "write", update_shared, planned["plan"])
    check_ok(fx, code, written)
    assert written["plan"] == planned["plan"], (planned["plan"], written["plan"])
    return planned["plan"]


# --- tests ---------------------------------------------------------------------

def test_worker_plan_mode_writes_nothing():
    fx = build_fixture()
    try:
        before = file_state(fx.source)
        code, result = run_worker(fx, "plan")
        check_ok(fx, code, result)
        plan = result["plan"]
        assert {("objects", "Cube"), ("meshes", "CubeMesh"), ("collections", "C"),
                ("objects", "Inst")} <= keys(plan, "replaced"), plan
        assert keys(plan, "kept") == {("materials", "SharedMat")}, plan
        assert keys(plan, "shared") == {("materials", "SharedMat")}, plan
        assert ("objects", "Lamp.001") in keys(plan, "added"), plan
        assert ("objects", "Lamp") not in keys(plan, "replaced"), plan
        assert "LampMesh" in plan["shared_users"]["materials:SharedMat"], plan
        assert result["source_blender_version"] == list(bpy.app.version_file), result
        assert file_state(fx.source) == before, "plan mode changed the source"
        assert not os.path.exists(fx.source + "1"), "plan mode wrote a .blend1"
        code, again = run_worker(fx, "plan")
        check_ok(fx, code, again)
        assert again["plan"] == plan, "plan is not deterministic"
    finally:
        cleanup(fx)


def test_worker_write_replaces_and_keeps():
    fx = build_fixture()
    try:
        plan_then_write(fx)
        assert not os.path.exists(fx.source + "1"), "write left a .blend1"
        with open(fx.source, "rb") as fh:
            assert not fh.read(7).startswith(b"BLENDER"), "compression dropped"
        reopen(fx)
        assert tuple(bpy.data.version) == tuple(bpy.app.version_file), bpy.data.version
        cube = bpy.data.objects["Cube"]
        assert cube.data.name == "CubeMesh"
        assert abs(cube.data.vertices[0].co.x - 1.0) < EPS, cube.data.vertices[0].co
        assert_color(bpy.data.materials["SharedMat"], RED)
        c = bpy.data.collections["C"]
        assert c.library is None
        assert any(ch == c for ch in bpy.context.scene.collection.children), "C unlinked from scene"
        assert {o.name for o in c.objects} == {"Cube", "Inst", "Lamp.001", "Rock"}, [o.name for o in c.objects]
        assert "C [edit]" not in bpy.data.collections
        lamp = bpy.data.objects["Lamp"]
        assert lamp.data.name == "LampMesh" and [x.name for x in lamp.users_collection] == ["Other"]
        assert bpy.data.objects["Lamp.001"].data.name == "LampNewMesh"
        inst = bpy.data.objects["Inst"]
        assert inst.instance_collection == bpy.data.collections["N"], inst.instance_collection
        assert inst.instance_collection.library is None
        rock = bpy.data.objects["Rock"]
        assert rock.library is not None and rock.library.filepath == "//third.blend", rock.library.filepath
        libs = [lib.filepath for lib in bpy.data.libraries]
        assert libs == ["//third.blend"], libs
        assert bpy.data.images["NewTex"].filepath_raw.replace("\\", "/") == "//tex/new.png", \
            bpy.data.images["NewTex"].filepath_raw
        assert bpy.data.images["SrcTex"].filepath_raw == fx.src_tex_path, bpy.data.images["SrcTex"].filepath_raw
        no_tags_anywhere()
    finally:
        cleanup(fx)


def test_worker_shared_kept_relinks():
    fx = build_fixture()
    try:
        plan_then_write(fx)
        reopen(fx)
        mats = [m for m in bpy.data.materials if m.name.startswith("SharedMat")]
        assert [m.name for m in mats] == ["SharedMat"], [m.name for m in mats]
        mat = mats[0]
        assert bpy.data.objects["Cube"].data.materials[0] == mat
        assert bpy.data.objects["Lamp"].data.materials[0] == mat
        assert mat.users == 2, mat.users
        assert_color(mat, RED)
    finally:
        cleanup(fx)


def test_worker_ticked_shared_is_replaced():
    fx = build_fixture()
    try:
        plan = plan_then_write(fx, [("materials", "SharedMat")])
        assert ("materials", "SharedMat") in keys(plan, "replaced") and plan["kept"] == [], plan
        reopen(fx)
        mats = [m for m in bpy.data.materials if m.name.startswith("SharedMat")]
        assert [m.name for m in mats] == ["SharedMat"], [m.name for m in mats]
        assert_color(mats[0], GREEN)
        assert bpy.data.objects["Lamp"].data.materials[0] == mats[0]
        assert bpy.data.objects["Cube"].data.materials[0] == mats[0]
    finally:
        cleanup(fx)


def test_worker_user_collision_keeps_foreign_id():
    fx = build_fixture()
    try:
        plan = plan_then_write(fx, [("materials", "SharedMat")])
        assert ("objects", "Lamp.001") in keys(plan, "added")
        assert all(k[1] not in ("Lamp", "LampMesh") for k in keys(plan, "replaced")), plan
        reopen(fx)
        lamp = bpy.data.objects["Lamp"]
        assert lamp.data.name == "LampMesh", lamp.data.name
        assert [tuple(v.co) for v in lamp.data.vertices] == [(0, 0, 0), (1, 0, 0), (0, 1, 0)]
        assert [x.name for x in lamp.users_collection] == ["Other"]
        new = bpy.data.objects["Lamp.001"]
        assert new.data.name == "LampNewMesh"
        assert [x.name for x in new.users_collection] == ["C"]
    finally:
        cleanup(fx)


def test_worker_exception_leaves_source_untouched():
    fx = build_fixture()
    try:
        before = file_state(fx.source)
        code, planned = run_worker(fx, "plan")
        check_ok(fx, code, planned)
        wrong = dict(planned["plan"])
        wrong["replaced"] = []
        code, result = run_worker(fx, "write", (), wrong)
        assert code == 1, code
        assert result.get("ok") is False and result.get("error"), result
        assert file_state(fx.source) == before, "failed write changed the source"
        assert not os.path.exists(fx.source + "1")
        code, result = run_worker(fx, "write", (), None)
        assert code == 1 and result.get("ok") is False, "write without expected_plan must fail"
        assert file_state(fx.source) == before
    finally:
        cleanup(fx)


def test_worker_lost_instance_collection_fails():
    # Without the restore tag the self-linked collection is silently dropped
    # by the append; the worker must refuse instead of saving the loss.
    fx = build_fixture(tag_instance=False)
    try:
        before = file_state(fx.source)
        code, result = run_worker(fx, "plan")
        assert code == 1 and result.get("ok") is False, result
        assert "Inst" in result["error"], result["error"]
        assert file_state(fx.source) == before
    finally:
        cleanup(fx)


def test_worker_removed_objects_unlinked_or_deleted():
    fx = build_fixture(extras=True)
    try:
        plan = plan_then_write(fx)
        assert keys(plan, "unlinked") == {("objects", "Extra"), ("objects", "Pair")}, plan
        assert keys(plan, "deleted") == {("objects", "Extra")}, plan
        reopen(fx)
        assert "Extra" not in bpy.data.objects
        assert [x.name for x in bpy.data.objects["Pair"].users_collection] == ["Other"]
        assert {o.name for o in bpy.data.collections["C"].objects} == {"Cube", "Inst", "Lamp.001", "Rock"}
    finally:
        cleanup(fx)


def test_worker_view_layer_state_preserved():
    fx = build_fixture(view_layers=True)
    try:
        plan_then_write(fx)
        reopen(fx)
        scene = bpy.data.scenes["Scene"]
        vl1, vl2 = scene.view_layers[0], scene.view_layers["VL2"]
        lc1, lc2 = vl1.layer_collection.children["C"], vl2.layer_collection.children["C"]
        assert lc2.exclude and not lc1.exclude
        assert lc1.hide_viewport and not lc2.hide_viewport
        sub1 = lc1.children["Sub"]
        assert sub1.holdout and sub1.indirect_only and not sub1.exclude and not sub1.hide_viewport
        assert not lc2.children["Sub"].holdout
        assert bpy.data.objects["Cube"].hide_get(view_layer=vl1)
        assert not bpy.data.objects["Lamp.001"].hide_get(view_layer=vl1)
        s2 = bpy.data.scenes["S2"]
        assert any(ch == bpy.data.collections["C"] for ch in s2.collection.children), "C left S2"
        lc_s2 = s2.view_layers[0].layer_collection.children["C"]
        assert not (lc_s2.exclude or lc_s2.hide_viewport or lc_s2.holdout or lc_s2.indirect_only)
        assert not bpy.data.objects["Cube"].hide_get(view_layer=s2.view_layers[0])
        # Each child's own exclusion survives: re-enabling C in VL2 keeps Sub
        # excluded and brings Sub2 back, as in the original file.
        assert lc2.children["Sub"].exclude and lc2.children["Sub2"].exclude
        lc2.exclude = False
        assert lc2.children["Sub"].exclude, "Sub's own exclusion was lost"
        assert not lc2.children["Sub2"].exclude, "Sub2 became excluded on its own"
    finally:
        cleanup(fx)


def test_worker_empty_instancer_round_trips():
    fx = build_fixture(empty_instancer=True)
    try:
        plan = plan_then_write(fx)
        assert ("objects", "EmptyInst") in keys(plan, "replaced"), plan
        reopen(fx)
        empty = bpy.data.objects["EmptyInst"]
        assert empty.instance_type == "COLLECTION" and empty.instance_collection is None
        assert [x.name for x in empty.users_collection] == ["C"]
    finally:
        cleanup(fx)


def test_worker_ticked_shared_pulls_dependencies():
    fx = build_fixture(shared_child=True)
    try:
        plan = plan_then_write(fx, [("objects", "Both")])
        assert {("objects", "Both"), ("meshes", "BothMesh")} <= keys(plan, "replaced"), plan
        assert plan["pulled"] == [["meshes", "BothMesh"]], plan["pulled"]
        assert ("materials", "SharedMat") in keys(plan, "kept"), plan
        assert {("collections", "D"), ("objects", "DObj")} <= keys(plan, "kept"), plan
        reopen(fx)
        both = bpy.data.objects["Both"]
        assert both.data.name == "BothMesh" and abs(both.data.vertices[0].co.x - 5.0) < EPS
        assert {x.name for x in both.users_collection} == {"C", "Other"}
        assert [m.name for m in bpy.data.meshes if m.name.startswith("BothMesh")] == ["BothMesh"]
        mats = [m for m in bpy.data.materials if m.name.startswith("SharedMat")]
        assert [m.name for m in mats] == ["SharedMat"] and both.data.materials[0] == mats[0]
        assert_color(mats[0], RED)
    finally:
        cleanup(fx)


def test_worker_discarded_reported():
    fx = build_fixture(shared_child=True)
    try:
        plan = plan_then_write(fx)
        assert {("collections", "D"), ("objects", "DObj")} <= keys(plan, "kept"), plan
        assert ("objects", "XNew") in keys(plan, "discarded"), plan
        assert all(k[1] != "XNew" for k in keys(plan, "added")), plan
        reopen(fx)
        assert "XNew" not in bpy.data.objects
        d = bpy.data.collections["D"]
        assert [o.name for o in d.objects] == ["DObj"]
        assert {p.name for p in bpy.data.collections if any(ch == d for ch in p.children)} == {"C", "Other"}
    finally:
        cleanup(fx)


def test_worker_shared_propagates_to_dependencies():
    fx = build_fixture(shared_child=True)
    try:
        plan = plan_then_write(fx)
        assert {("objects", "Both"), ("meshes", "BothMesh")} <= keys(plan, "kept"), plan
        assert "Both" in plan["shared_users"]["meshes:BothMesh"], plan["shared_users"]
        reopen(fx)
        both = bpy.data.objects["Both"]
        assert both.data.name == "BothMesh" and abs(both.data.vertices[0].co.x) < EPS, both.data.vertices[0].co
        assert {x.name for x in both.users_collection} == {"C", "Other"}
        assert [m.name for m in bpy.data.meshes if m.name.startswith("BothMesh")] == ["BothMesh"]
    finally:
        cleanup(fx)


def test_worker_untagged_instancer_duplicate_fails():
    fx = build_fixture(dup_instancer=True)
    try:
        before = file_state(fx.source)
        code, result = run_worker(fx, "plan")
        assert code == 1 and result.get("ok") is False, result
        assert "InstDup" in result["error"], result["error"]
        assert file_state(fx.source) == before
    finally:
        cleanup(fx)


def test_worker_keeps_asset_metadata():
    fx = build_fixture(assets=True)
    try:
        plan = plan_then_write(fx, [("materials", "SharedMat")])
        assert {("collections", "C"), ("materials", "SharedMat")} <= keys(plan, "replaced"), plan
        assert ("texts", "Notes") in keys(plan, "added"), plan
        reopen(fx)
        c = bpy.data.collections["C"]
        assert {o.name for o in c.objects} == {"Cube", "Inst", "Lamp.001", "Rock"}
        assert_asset(c, "coll desc")
        mat = bpy.data.materials["SharedMat"]
        assert bpy.data.objects["Cube"].data.materials[0] == mat
        assert_color(mat, GREEN)
        assert_asset(mat, "mat desc")
        assert [m.name for m in bpy.data.materials if m.name.startswith("SharedMat")] == ["SharedMat"]
        # The appended text's absolute path is made relative to the source.
        notes = bpy.data.objects["Cube"]["notes"]
        assert notes.name == "Notes" and notes.filepath.replace("\\", "/") == "//notes.txt", notes.filepath
        no_tags_anywhere()
    finally:
        cleanup(fx)


TESTS = [
    test_worker_plan_mode_writes_nothing,
    test_worker_write_replaces_and_keeps,
    test_worker_shared_kept_relinks,
    test_worker_ticked_shared_is_replaced,
    test_worker_user_collision_keeps_foreign_id,
    test_worker_exception_leaves_source_untouched,
    test_worker_lost_instance_collection_fails,
    test_worker_removed_objects_unlinked_or_deleted,
    test_worker_view_layer_state_preserved,
    test_worker_discarded_reported,
    test_worker_shared_propagates_to_dependencies,
    test_worker_untagged_instancer_duplicate_fails,
    test_worker_empty_instancer_round_trips,
    test_worker_ticked_shared_pulls_dependencies,
    test_worker_keeps_asset_metadata,
]


def main():
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
