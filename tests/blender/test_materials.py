"""Headless tests of the iOps Materials panel operators: compatibility
skipping, whole-object and face assignment (Object and Edit Mode, shared
data), new material, deduplication (equivalent merged and relinked,
different kept, missing base renamed, linked skipped) and every cleanup
function. Run from the repo root with isolated user folders (see
tests/blender/_isolation.py):

    blender --background --factory-startup --python-exit-code 1 --python tests/blender/test_materials.py

Not collected by pytest (tests/conftest.py ignores tests/blender).
"""
import os
import sys
import tempfile
import traceback

import bmesh
import bpy

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _isolation import require_isolated_user_resources  # noqa: E402

ADDON = "InteractionOps"


def enable_addon():
    repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    repo_parent = os.path.dirname(repo_root)
    if repo_parent not in sys.path:
        sys.path.insert(0, repo_parent)
    bpy.ops.preferences.addon_enable(module=ADDON)
    assert ADDON in bpy.context.preferences.addons, "addon not enabled"
    import InteractionOps
    loaded = os.path.dirname(os.path.abspath(InteractionOps.__file__))
    assert os.path.samefile(loaded, repo_root), f"addon loaded from {loaded}"


# ----------------------------------------------------------------------
# fixtures
# ----------------------------------------------------------------------
def reset():
    if bpy.context.object is not None and bpy.context.object.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    for ob in list(bpy.data.objects):
        bpy.data.objects.remove(ob)
    for coll in (bpy.data.meshes, bpy.data.materials, bpy.data.cameras,
                 bpy.data.lights, bpy.data.curves):
        for idb in list(coll):
            if idb.library is None:
                coll.remove(idb)
    for lib in list(bpy.data.libraries):
        bpy.data.libraries.remove(lib)


def cube(name, data=None):
    if data is None:
        data = bpy.data.meshes.new(name)
        bm = bmesh.new()
        bmesh.ops.create_cube(bm, size=1.0)
        bm.to_mesh(data)
        bm.free()
    ob = bpy.data.objects.new(name, data)
    bpy.context.scene.collection.objects.link(ob)
    return ob


def plain(name, data=None):
    ob = bpy.data.objects.new(name, data)
    bpy.context.scene.collection.objects.link(ob)
    return ob


def mat(name, roughness=0.5):
    m = bpy.data.materials.new(name)
    assert m.name == name, m.name
    from InteractionOps.operators.materials.assign import ensure_principled
    ensure_principled(m)
    bsdf = next(n for n in m.node_tree.nodes
                if n.bl_idname == "ShaderNodeBsdfPrincipled")
    bsdf.inputs["Roughness"].default_value = roughness
    return m


def select(*objs, active=None):
    bpy.context.view_layer.update()
    for ob in bpy.context.view_layer.objects:
        ob.select_set(ob in objs)
    bpy.context.view_layer.objects.active = active or (objs[0] if objs else None)


def give_slots(ob, *mats):
    ob.data.materials.clear()
    for m in mats:
        ob.data.materials.append(m)


def face_indices(ob):
    idx = [0] * len(ob.data.polygons)
    ob.data.polygons.foreach_get("material_index", idx)
    return idx


def set_face_indices(ob, idx):
    ob.data.polygons.foreach_set("material_index", idx)
    ob.data.update()


def select_faces(ob, picked):
    sel = [i in picked for i in range(len(ob.data.polygons))]
    ob.data.polygons.foreach_set("select", sel)
    ob.data.update()


def slot_mats(ob):
    return [s.material.name if s.material else None for s in ob.material_slots]


def assign(material, mode="OBJECT"):
    return bpy.ops.iops.material_assign(material=material.name, mode=mode)


# ----------------------------------------------------------------------
# assignment
# ----------------------------------------------------------------------
def test_compatibility_skipping():
    reset()
    steel = mat("Steel")
    box = cube("Box")
    empty = plain("Empty")
    cam = plain("Cam", bpy.data.cameras.new("Cam"))
    lamp = plain("Lamp", bpy.data.lights.new("Lamp", "POINT"))
    select(box, empty, cam, lamp, active=empty)
    from InteractionOps.operators.materials.assign import assign_material
    from InteractionOps.operators.materials.common import target_objects
    res = assign_material(steel, target_objects(bpy.context))
    assert res.objects == 1, res
    assert res.skipped == {"Empty": 1, "Camera": 1, "Light": 1}, res.skipped
    assert slot_mats(box) == ["Steel"]
    # the operator reports and finishes, no exception
    assert assign(steel) == {"FINISHED"}
    # nothing compatible: single warning, cancelled, nothing raised
    select(empty, cam)
    assert assign(steel) == {"CANCELLED"}
    # faces mode skips non-mesh types too
    select(empty, lamp)
    assert assign(steel, "FACES") == {"CANCELLED"}


def test_linked_data_is_skipped():
    from InteractionOps.operators.materials.common import skip_reason
    reset()
    path = os.path.join(tempfile.gettempdir(), "iops_mat_test_lib.blend")
    data = bpy.data.meshes.new("LibMesh")
    bpy.data.libraries.write(path, {data})
    bpy.data.meshes.remove(data)
    with bpy.data.libraries.load(path, link=True) as (src, dst):
        dst.meshes = ["LibMesh"]
    ob = plain("UsesLinked", dst.meshes[0])
    assert skip_reason(ob) == "Linked"
    select(ob)
    assert assign(mat("Steel")) == {"CANCELLED"}


def test_object_assign_collapses_slots():
    reset()
    a, b, c, steel = mat("A"), mat("B"), mat("C"), mat("Steel")
    box = cube("Box")
    give_slots(box, a, b, c)
    set_face_indices(box, [0, 1, 2, 2, 1, 0])
    select(box)
    assert assign(steel) == {"FINISHED"}
    assert slot_mats(box) == ["Steel"]
    assert face_indices(box) == [0] * 6


def test_object_assign_shared_data_and_object_link():
    reset()
    a, steel = mat("A"), mat("Steel")
    first = cube("First")
    second = cube("Second", first.data)
    third = cube("Third")
    give_slots(first, a, a)
    give_slots(third, a)
    third.material_slots[0].link = "OBJECT"
    third.material_slots[0].material = a
    select(first, second, third)
    from InteractionOps.operators.materials.assign import assign_material
    res = assign_material(steel, [first, second, third])
    assert res.objects == 3 and res.skipped == {}, res
    assert slot_mats(first) == ["Steel"] and slot_mats(second) == ["Steel"]
    assert len(first.data.materials) == 1
    assert slot_mats(third) == ["Steel"], slot_mats(third)


def test_object_assign_in_edit_mode():
    reset()
    a, b, steel = mat("A"), mat("B"), mat("Steel")
    box = cube("Box")
    other = cube("Other")
    give_slots(box, a, b)
    set_face_indices(box, [1] * 6)
    give_slots(other, b)
    select(box, other)
    bpy.ops.object.mode_set(mode="EDIT")
    # only objects in edit mode are targets, both are
    assert assign(steel) == {"FINISHED"}
    bpy.ops.object.mode_set(mode="OBJECT")
    assert slot_mats(box) == ["Steel"] and slot_mats(other) == ["Steel"]
    assert face_indices(box) == [0] * 6


def test_faces_assign_edit_mode():
    reset()
    a, steel = mat("A"), mat("Steel")
    box = cube("Box")
    other = cube("Other")
    give_slots(box, a)
    give_slots(other, a, steel)
    select(box, other)
    bpy.ops.object.mode_set(mode="EDIT")
    for ob, picked in ((box, {0, 1}), (other, {5})):
        bm = bmesh.from_edit_mesh(ob.data)
        for f in bm.faces:
            f.select_set(False)
        for f in bm.faces:
            if f.index in picked:
                f.select_set(True)
        bmesh.update_edit_mesh(ob.data)
    assert assign(steel, "FACES") == {"FINISHED"}
    bpy.ops.object.mode_set(mode="OBJECT")
    # box: slot appended; other: existing Steel slot (1) reused
    assert slot_mats(box) == ["A", "Steel"], slot_mats(box)
    assert face_indices(box) == [1, 1, 0, 0, 0, 0], face_indices(box)
    assert slot_mats(other) == ["A", "Steel"], slot_mats(other)
    assert face_indices(other) == [0, 0, 0, 0, 0, 1], face_indices(other)


def test_faces_assign_object_mode():
    reset()
    a, steel = mat("A"), mat("Steel")
    box = cube("Box")
    give_slots(box, a)
    select(box)
    select_faces(box, set())
    # no faces selected: nothing changes
    assert assign(steel, "FACES") == {"CANCELLED"}
    assert slot_mats(box) == ["A"] and face_indices(box) == [0] * 6
    select_faces(box, {2, 3})
    assert assign(steel, "FACES") == {"FINISHED"}
    assert slot_mats(box) == ["A", "Steel"]
    assert face_indices(box) == [0, 0, 1, 1, 0, 0], face_indices(box)
    # second run reuses the slot
    select_faces(box, {0})
    assert assign(steel, "FACES") == {"FINISHED"}
    assert slot_mats(box) == ["A", "Steel"]
    assert face_indices(box)[0] == 1


def test_faces_assign_reuses_unused_empty_slot():
    reset()
    a, steel = mat("A"), mat("Steel")
    box = cube("Box")
    give_slots(box, a, None)
    select(box)
    select_faces(box, {1, 2})
    assert assign(steel, "FACES") == {"FINISHED"}
    assert slot_mats(box) == ["A", "Steel"], slot_mats(box)
    assert face_indices(box) == [0, 1, 1, 0, 0, 0]


def test_faces_assign_reuses_empty_slot_of_selected_faces():
    reset()
    a, steel = mat("A"), mat("Steel")
    box = cube("Box")
    give_slots(box, a, None)
    set_face_indices(box, [1, 1, 0, 0, 0, 0])
    select(box)
    select_faces(box, {0, 1, 2})
    assert assign(steel, "FACES") == {"FINISHED"}
    assert slot_mats(box) == ["A", "Steel"], slot_mats(box)
    assert face_indices(box) == [1, 1, 1, 0, 0, 0]


def test_faces_assign_keeps_empty_slot_of_other_faces():
    reset()
    a, steel = mat("A"), mat("Steel")
    box = cube("Box")
    give_slots(box, a, None)
    set_face_indices(box, [1, 1, 0, 0, 0, 0])
    select(box)
    select_faces(box, {2})
    assert assign(steel, "FACES") == {"FINISHED"}
    assert slot_mats(box) == ["A", None, "Steel"], slot_mats(box)
    assert face_indices(box) == [1, 1, 2, 0, 0, 0]


def test_faces_assign_reuses_empty_slot_in_edit_mode():
    reset()
    a, steel = mat("A"), mat("Steel")
    box = cube("Box")
    give_slots(box, a, None)
    select(box)
    bpy.ops.object.mode_set(mode="EDIT")
    bm = bmesh.from_edit_mesh(box.data)
    for f in bm.faces:
        f.select_set(False)
    bm.faces.ensure_lookup_table()
    bm.faces[3].select_set(True)
    bmesh.update_edit_mesh(box.data)
    assert assign(steel, "FACES") == {"FINISHED"}
    bpy.ops.object.mode_set(mode="OBJECT")
    assert slot_mats(box) == ["A", "Steel"], slot_mats(box)
    assert face_indices(box) == [0, 0, 0, 1, 0, 0]


def _empties_box():
    """slots [<empty>, A, <empty>, B] with faces on every slot."""
    reset()
    a, b = mat("A"), mat("B")
    box = cube("Box")
    give_slots(box, None, a, None, b)
    set_face_indices(box, [0, 1, 2, 3, 0, 2])
    return box


def test_remove_empty_slots_object_mode():
    box = _empties_box()
    cam = plain("Cam", bpy.data.cameras.new("Cam"))
    select(box, cam)
    from InteractionOps.operators.materials.state import empty_slot_count
    assert empty_slot_count(bpy.context) == 2
    assert bpy.ops.iops.materials_remove_empty_slots() == {"FINISHED"}
    assert slot_mats(box) == ["A", "B"], slot_mats(box)
    # faces of the removed empty slots go to slot 0
    assert face_indices(box) == [0, 0, 0, 1, 0, 0], face_indices(box)
    # the cached count follows (operators invalidate the cache)
    assert empty_slot_count(bpy.context) == 0


def test_remove_empty_slots_edit_mode_and_shared():
    box = _empties_box()
    twin = cube("Twin", box.data)
    select(box)
    bpy.ops.object.mode_set(mode="EDIT")
    assert bpy.ops.iops.materials_remove_empty_slots() == {"FINISHED"}
    bpy.ops.object.mode_set(mode="OBJECT")
    assert slot_mats(box) == ["A", "B"] == slot_mats(twin)
    assert face_indices(box) == [0, 0, 0, 1, 0, 0], face_indices(box)


def test_remove_empty_slots_scene_scope():
    box = _empties_box()
    other = cube("Other")
    give_slots(other, None)
    select()
    assert bpy.ops.iops.materials_remove_empty_slots(scope="SCENE") == {"FINISHED"}
    assert slot_mats(box) == ["A", "B"], slot_mats(box)
    assert slot_mats(other) == [], slot_mats(other)


def test_empty_slot_count_cache():
    from InteractionOps.operators.materials.state import (
        empty_slot_count, invalidate_sources)
    box = _empties_box()
    select(box)
    invalidate_sources()
    assert empty_slot_count(bpy.context) == 2
    box.data.materials.append(None)
    # cached until something invalidates it (a depsgraph update in the UI)
    assert empty_slot_count(bpy.context) == 2
    invalidate_sources()
    assert empty_slot_count(bpy.context) == 3


def test_linked_material_assigns_without_copy():
    reset()
    path = os.path.join(tempfile.gettempdir(), "iops_mat_test_lib2.blend")
    ext = mat("External")
    bpy.data.libraries.write(path, {ext})
    bpy.data.materials.remove(ext)
    with bpy.data.libraries.load(path, link=True) as (src, dst):
        dst.materials = ["External"]
    linked = dst.materials[0]
    box = cube("Box")
    select(box)
    count = len(bpy.data.materials)
    assert bpy.ops.iops.material_assign(
        material=linked.name, library=linked.library.filepath) == {"FINISHED"}
    assert box.material_slots[0].material == linked
    assert len(bpy.data.materials) == count


def test_new_material():
    reset()
    bpy.data.materials.new("Material")
    box = cube("Box")
    select(box)
    assert bpy.ops.iops.material_new() == {"FINISHED"}
    new = bpy.data.materials.get("Material 2")
    assert new is not None, [m.name for m in bpy.data.materials]
    assert any(n.bl_idname == "ShaderNodeBsdfPrincipled"
               for n in new.node_tree.nodes)
    st = bpy.context.window_manager.iops_materials
    assert st.active_name == "Material 2"
    assert len(box.material_slots) == 0
    assert bpy.ops.iops.material_new(assign=True) == {"FINISHED"}
    assert slot_mats(box) == ["Material 3"], slot_mats(box)


# ----------------------------------------------------------------------
# deduplication
# ----------------------------------------------------------------------
def test_merge_equivalent_and_different():
    reset()
    steel = mat("Steel")
    same = steel.copy()
    assert same.name == "Steel.001"
    other = steel.copy()
    assert other.name == "Steel.002"
    bsdf = next(n for n in other.node_tree.nodes
                if n.bl_idname == "ShaderNodeBsdfPrincipled")
    bsdf.inputs["Roughness"].default_value = 0.9
    # cosmetic node change does not count
    next(iter(same.node_tree.nodes)).location.x += 100
    u1, u2, u3 = cube("U1"), cube("U2"), cube("U3")
    give_slots(u1, same)
    give_slots(u2, other)
    give_slots(u3, steel, same)
    assert bpy.ops.iops.materials_merge_duplicates() == {"FINISHED"}
    assert "Steel.001" not in bpy.data.materials
    assert "Steel.002" in bpy.data.materials
    assert slot_mats(u1) == ["Steel"]
    # the relinked repeat collapsed into the first slot
    assert slot_mats(u3) == ["Steel"]
    assert slot_mats(u2) == ["Steel.002"]
    # force merges the different one
    assert bpy.ops.iops.materials_merge_duplicates(force=True) == {"FINISHED"}
    assert "Steel.002" not in bpy.data.materials
    assert slot_mats(u2) == ["Steel"]


def test_merge_material_setting_counts():
    reset()
    steel = mat("Steel")
    dup = steel.copy()
    dup.use_backface_culling = not steel.use_backface_culling
    bpy.ops.iops.materials_merge_duplicates()
    assert dup.name in bpy.data.materials, "different settings were merged"


def test_merge_missing_base_renames():
    reset()
    first = mat("Paint.002")
    second = mat("Paint.003")
    user = cube("User")
    give_slots(user, second)
    assert bpy.ops.iops.materials_merge_duplicates() == {"FINISHED"}
    assert "Paint.003" not in bpy.data.materials
    assert first.name == "Paint", first.name
    assert slot_mats(user) == ["Paint"]


def test_merge_single_group():
    reset()
    a, b = mat("A"), mat("B")
    a.copy()
    b.copy()
    assert bpy.ops.iops.materials_merge_duplicates(base="B") == {"FINISHED"}
    assert "A.001" in bpy.data.materials and "B.001" not in bpy.data.materials


def test_merge_skips_linked():
    reset()
    path = os.path.join(tempfile.gettempdir(), "iops_mat_test_lib3.blend")
    ext = mat("Ext.001")
    bpy.data.libraries.write(path, {ext})
    bpy.data.materials.remove(ext)
    with bpy.data.libraries.load(path, link=True) as (src, dst):
        dst.materials = ["Ext.001"]
    linked = dst.materials[0]
    local = mat("Ext")
    from InteractionOps.operators.materials.dedup import merge_duplicates
    plans, skipped = merge_duplicates()
    assert skipped == 1 and plans == [], (plans, skipped)
    assert linked.name == "Ext.001" and linked.library is not None
    assert local.name == "Ext"


def _m_dup():
    """M and an equivalent copy M.001."""
    m = mat("M")
    dup = m.copy()
    assert dup.name == "M.001"
    return m, dup


def test_merge_collapses_user_case():
    # the user's scene: slots M, M, M, M.001, all faces on slot 0
    reset()
    m, dup = _m_dup()
    box = cube("Cube")
    give_slots(box, m, m, m, dup)
    select()
    assert bpy.ops.iops.materials_merge_duplicates() == {"FINISHED"}
    assert [x.name for x in bpy.data.materials] == ["M"]
    assert slot_mats(box) == ["M"], slot_mats(box)
    assert face_indices(box) == [0] * 6


def test_merge_collapse_keeps_other_slots():
    reset()
    a, b = mat("A"), mat("B")
    a_dup = a.copy()
    box = cube("Box")
    give_slots(box, a, b, a_dup)
    set_face_indices(box, [0, 1, 2, 2, 1, 0])
    select()
    bpy.ops.iops.materials_merge_duplicates()
    assert slot_mats(box) == ["A", "B"], slot_mats(box)
    assert face_indices(box) == [0, 1, 0, 0, 1, 0], face_indices(box)


def test_merge_collapse_edit_mode():
    reset()
    a, b = mat("A"), mat("B")
    a_dup = a.copy()
    box = cube("Box")
    give_slots(box, a, b, a_dup)
    set_face_indices(box, [0, 1, 2, 2, 1, 0])
    select(box)
    bpy.ops.object.mode_set(mode="EDIT")
    assert bpy.ops.iops.materials_merge_duplicates() == {"FINISHED"}
    bpy.ops.object.mode_set(mode="OBJECT")
    assert slot_mats(box) == ["A", "B"], slot_mats(box)
    assert face_indices(box) == [0, 1, 0, 0, 1, 0], face_indices(box)


def test_merge_collapse_shared_data():
    reset()
    m, dup = _m_dup()
    other = mat("Other")
    first = cube("First")
    second = cube("Second", first.data)
    give_slots(first, m, other, dup)
    set_face_indices(first, [2, 2, 1, 1, 0, 0])
    select()
    bpy.ops.iops.materials_merge_duplicates()
    assert slot_mats(first) == ["M", "Other"] == slot_mats(second)
    assert face_indices(first) == [0, 0, 1, 1, 0, 0], face_indices(first)


def _empty_case():
    """[M, M, <empty>, M.001, Other] with faces on every slot."""
    reset()
    m, dup = _m_dup()
    other = mat("Other")
    box = cube("Box")
    give_slots(box, m, m, None, dup, other)
    set_face_indices(box, [0, 1, 2, 3, 4, 2])
    return box


def test_merge_removes_empty_slots():
    box = _empty_case()
    select()
    assert bpy.ops.iops.materials_merge_duplicates() == {"FINISHED"}
    assert slot_mats(box) == ["M", "Other"], slot_mats(box)
    assert face_indices(box) == [0, 0, 0, 0, 1, 0], face_indices(box)


def test_merge_toggles():
    # Merge off: duplicates stay, slots of the selection are still cleaned
    box = _empty_case()
    select(box)
    bpy.ops.iops.materials_merge_duplicates(merge=False)
    assert "M.001" in bpy.data.materials
    assert slot_mats(box) == ["M", "M.001", "Other"], slot_mats(box)
    assert face_indices(box) == [0, 0, 0, 1, 2, 0], face_indices(box)
    # Collapse off: repeats stay, the empty slot goes
    box = _empty_case()
    select()
    bpy.ops.iops.materials_merge_duplicates(collapse_slots=False)
    assert slot_mats(box) == ["M", "M", "M", "Other"], slot_mats(box)
    assert face_indices(box) == [0, 1, 0, 2, 3, 0], face_indices(box)
    # Remove Empty off: the empty slot stays with its faces
    box = _empty_case()
    select()
    bpy.ops.iops.materials_merge_duplicates(remove_empty=False)
    assert slot_mats(box) == ["M", None, "Other"], slot_mats(box)
    assert face_indices(box) == [0, 0, 1, 0, 2, 1], face_indices(box)
    # everything off but merge: only the datablock merge
    box = _empty_case()
    select()
    bpy.ops.iops.materials_merge_duplicates(collapse_slots=False,
                                            remove_empty=False)
    assert slot_mats(box) == ["M", "M", None, "M", "Other"], slot_mats(box)


def test_merge_skips_object_linked_slots():
    reset()
    m, dup = _m_dup()
    box = cube("Box")
    give_slots(box, m, dup)
    box.material_slots[1].link = "OBJECT"
    box.material_slots[1].material = dup
    select()
    assert bpy.ops.iops.materials_merge_duplicates() == {"FINISHED"}
    assert "M.001" not in bpy.data.materials
    assert len(box.material_slots) == 2, "object-linked slots were collapsed"


def test_merge_redo_through_undo():
    """The redo panel undoes and re-executes with new options; do the same
    by hand when the undo stack is usable headless."""
    box = _empty_case()
    select()
    # re-executing on its own result changes nothing (no hidden state)
    bpy.ops.iops.materials_merge_duplicates()
    bpy.ops.iops.materials_merge_duplicates()
    assert slot_mats(box) == ["M", "Other"]
    assert face_indices(box) == [0, 0, 0, 0, 1, 0]
    box = _empty_case()
    select()
    try:
        bpy.ops.ed.undo_push(message="before merge")
        bpy.ops.iops.materials_merge_duplicates()
        assert slot_mats(box) == ["M", "Other"]
        bpy.ops.ed.undo()
    except RuntimeError as exc:
        print("SKIP undo part:", exc)
        return
    box = bpy.data.objects["Box"]
    assert slot_mats(box) == ["M", "M", None, "M.001", "Other"], slot_mats(box)
    bpy.ops.iops.materials_merge_duplicates(remove_empty=False)
    assert slot_mats(box) == ["M", None, "Other"], slot_mats(box)


def test_panel_rows_stack():
    reset()
    steel = mat("Steel")
    steel.copy()
    steel.copy()
    mat("Wood")
    box = cube("Box")
    give_slots(box, bpy.data.materials["Steel.002"])
    from InteractionOps.ui.iops_materials_panel import panel_rows
    st = bpy.context.window_manager.iops_materials
    prefs = bpy.context.preferences.addons[ADDON].preferences
    st.source = "SCENE"
    st.search = ""
    from InteractionOps.operators.materials.state import invalidate_sources
    invalidate_sources()
    rows, _ = panel_rows(bpy.context)
    assert [(r.display, r.count, r.key[0]) for r in rows] == [("Steel", 3, "Steel")], rows
    st.source = "FILE"
    rows, _ = panel_rows(bpy.context)
    assert [r.display for r in rows] == ["Steel", "Wood"], rows
    prefs.materials_stack_duplicates = False
    try:
        rows, _ = panel_rows(bpy.context)
        assert [r.display for r in rows] == ["Steel", "Steel.001", "Steel.002", "Wood"]
    finally:
        prefs.materials_stack_duplicates = True


# ----------------------------------------------------------------------
# functions
# ----------------------------------------------------------------------
def remap(scope, pairs, **kw):
    """Build the table for `scope`, pick targets {source: target name},
    execute."""
    from InteractionOps.operators.materials.remap import build_rows
    build_rows(bpy.context, scope)
    for row in bpy.context.window_manager.iops_materials.remap_rows:
        if row.source_name in pairs:
            row.target = bpy.data.materials[pairs[row.source_name]]
    return bpy.ops.iops.materials_remap(scope=scope, **kw)


def test_remap_scopes():
    reset()
    a = mat("A")
    mat("B")
    s1, s2, s3 = cube("S1"), cube("S2"), cube("S3")
    for ob in (s1, s2, s3):
        give_slots(ob, a)
    empty = plain("Empty")
    select(s1, empty)
    assert remap("SELECTED", {"A": "B"}) == {"FINISHED"}
    assert slot_mats(s1) == ["B"] and slot_mats(s2) == ["A"]
    assert remap("SCENE", {"A": "B"}) == {"FINISHED"}
    assert slot_mats(s2) == ["B"] and slot_mats(s3) == ["B"]
    give_slots(s3, a)
    assert remap("FILE", {"A": "B"}) == {"FINISHED"}
    assert slot_mats(s3) == ["B"]
    assert "A" in bpy.data.materials, "the source must not be deleted"
    # the table is emptied after a run
    assert len(bpy.context.window_manager.iops_materials.remap_rows) == 0


def test_remap_rows_follow_scope():
    from InteractionOps.operators.materials.remap import (
        _rebuild_on_scope, build_rows)
    reset()
    a, b = mat("A"), mat("B")
    mat("Unused")
    s1, s2 = cube("S1"), cube("S2")
    give_slots(s1, a)
    give_slots(s2, b)
    select(s1)
    rows = bpy.context.window_manager.iops_materials.remap_rows
    assert build_rows(bpy.context, "SELECTED") == 1
    assert [r.source_name for r in rows] == ["A"]

    class Props:
        scope = "SCENE"
    _rebuild_on_scope(Props, bpy.context)
    assert [r.source_name for r in rows] == ["A", "B"]
    Props.scope = "FILE"
    _rebuild_on_scope(Props, bpy.context)
    assert [r.source_name for r in rows] == ["A", "B", "Unused"]


def test_remap_chain_and_swap():
    reset()
    a, b, c = mat("A"), mat("B"), mat("C")
    oa, ob_, oc = cube("OA"), cube("OB"), cube("OC")
    give_slots(oa, a)
    give_slots(ob_, b)
    give_slots(oc, c)
    select()
    # chain: simultaneous, A -> B and B -> C does not turn A into C
    assert remap("SCENE", {"A": "B", "B": "C"}) == {"FINISHED"}
    assert slot_mats(oa) == ["B"] and slot_mats(ob_) == ["C"]
    # swap
    assert remap("SCENE", {"B": "C", "C": "B"}) == {"FINISHED"}
    assert slot_mats(oa) == ["C"] and slot_mats(ob_) == ["B"]
    assert slot_mats(oc) == ["B"]
    # swap in File scope too
    give_slots(oa, a)
    give_slots(ob_, b)
    assert remap("FILE", {"A": "B", "B": "A"}) == {"FINISHED"}
    assert slot_mats(oa) == ["B"] and slot_mats(ob_) == ["A"]


def test_remap_shared_data_once():
    reset()
    a = mat("A")
    mat("B")
    first = cube("First")
    second = cube("Second", first.data)
    give_slots(first, a)
    select()
    # a swap applied twice on shared data would undo itself
    assert remap("SCENE", {"A": "B", "B": "A"}) == {"FINISHED"}
    assert slot_mats(first) == ["B"] == slot_mats(second)


def test_remap_skips_incompatible_and_linked():
    reset()
    path = os.path.join(tempfile.gettempdir(), "iops_mat_test_lib5.blend")
    ext = mat("Ext")
    bpy.data.libraries.write(path, {ext})
    bpy.data.materials.remove(ext)
    with bpy.data.libraries.load(path, link=True) as (src, dst):
        dst.materials = ["Ext"]
    linked = dst.materials[0]
    mat("B")
    box = cube("Box")
    give_slots(box, linked)
    empty = plain("Empty")
    select(box, empty)
    # File scope: a linked source is skipped and counted
    assert remap("FILE", {"Ext": "B"}) == {"FINISHED"}
    assert box.material_slots[0].material == linked
    # Selected scope: its local users switch; the Empty is skipped
    assert remap("SELECTED", {"Ext": "B"}) == {"FINISHED"}
    assert slot_mats(box) == ["B"]


def test_remap_collapse_option():
    reset()
    a, b = mat("A"), mat("B")
    box = cube("Box")
    give_slots(box, a, b, None)
    set_face_indices(box, [0, 1, 2, 0, 1, 2])
    select(box)
    assert remap("SELECTED", {"A": "B"}, collapse_slots=False) == {"FINISHED"}
    assert slot_mats(box) == ["B", "B", None]
    give_slots(box, a, b, None)     # clear() zeroes the face indices
    set_face_indices(box, [0, 1, 2, 0, 1, 2])
    assert remap("SELECTED", {"A": "B"}) == {"FINISHED"}
    assert slot_mats(box) == ["B", None], slot_mats(box)
    assert face_indices(box) == [0, 0, 1, 0, 0, 1], face_indices(box)
    give_slots(box, a, b, None)
    assert remap("SELECTED", {"A": "B"}, remove_empty=True) == {"FINISHED"}
    assert slot_mats(box) == ["B"], slot_mats(box)


def test_remap_nothing_to_do():
    reset()
    a = mat("A")
    box = cube("Box")
    give_slots(box, a)
    select(box)
    # rows but no target picked
    assert remap("SELECTED", {}) == {"CANCELLED"}
    # no rows at all
    bpy.context.window_manager.iops_materials.remap_rows.clear()
    assert bpy.ops.iops.materials_remap(scope="SELECTED") == {"CANCELLED"}


def test_copy_from_active():
    reset()
    a, b = mat("A"), mat("B")
    src, dst = cube("Src"), cube("Dst")
    give_slots(src, a, b)
    give_slots(dst, b)
    empty = plain("Empty")
    select(src, dst, empty, active=src)
    assert bpy.ops.iops.materials_copy_from_active() == {"FINISHED"}
    assert slot_mats(dst) == ["A", "B"]
    select(empty, active=empty)
    assert bpy.ops.iops.materials_copy_from_active() == {"CANCELLED"}


def test_select_users():
    reset()
    a, b = mat("A"), mat("B")
    u1, u2, other = cube("U1"), cube("U2"), cube("Other")
    give_slots(u1, a)
    give_slots(u2, b, a)
    give_slots(other, b)
    select(other)
    bpy.context.window_manager.iops_materials.active_name = "A"
    bpy.context.window_manager.iops_materials.active_library = ""
    assert bpy.ops.iops.materials_select_users() == {"FINISHED"}
    picked = sorted(o.name for o in bpy.context.view_layer.objects if o.select_get())
    assert picked == ["U1", "U2"], picked


def test_remove_unused_slots_object_mode():
    reset()
    a, b, c = mat("A"), mat("B"), mat("C")
    box = cube("Box")
    give_slots(box, a, b, c)
    box.data.materials.append(None)
    set_face_indices(box, [0, 0, 2, 2, 0, 2])
    empty = plain("Empty")
    select(box, empty)
    assert bpy.ops.iops.materials_remove_unused_slots() == {"FINISHED"}
    assert slot_mats(box) == ["A", "C"], slot_mats(box)
    assert face_indices(box) == [0, 0, 1, 1, 0, 1], face_indices(box)


def test_remove_unused_slots_edit_mode():
    reset()
    a, b, c = mat("A"), mat("B"), mat("C")
    box = cube("Box")
    give_slots(box, a, b, c)
    set_face_indices(box, [2] * 6)
    select(box)
    bpy.ops.object.mode_set(mode="EDIT")
    assert bpy.ops.iops.materials_remove_unused_slots() == {"FINISHED"}
    bpy.ops.object.mode_set(mode="OBJECT")
    assert slot_mats(box) == ["C"], slot_mats(box)
    assert face_indices(box) == [0] * 6, face_indices(box)


def test_clear_selected_and_scene():
    reset()
    a = mat("A")
    s1, s2 = cube("S1"), cube("S2")
    give_slots(s1, a)
    give_slots(s2, a)
    cam = plain("Cam", bpy.data.cameras.new("Cam"))
    select(s1, cam)
    assert bpy.ops.iops.materials_clear(scope="SELECTED") == {"FINISHED"}
    assert slot_mats(s1) == [] and slot_mats(s2) == ["A"]
    # execute() skips the confirmation popup of invoke()
    assert bpy.ops.iops.materials_clear(scope="SCENE") == {"FINISHED"}
    assert slot_mats(s2) == []


def test_delete_unused():
    reset()
    used, unused, fake = mat("Used"), mat("Unused"), mat("FakeOnly")
    fake.use_fake_user = True
    box = cube("Box")
    give_slots(box, used)
    path = os.path.join(tempfile.gettempdir(), "iops_mat_test_lib4.blend")
    ext = mat("LinkedUnused")
    bpy.data.libraries.write(path, {ext})
    bpy.data.materials.remove(ext)
    with bpy.data.libraries.load(path, link=True) as (src, dst):
        dst.materials = ["LinkedUnused"]
    assert unused.users == 0
    assert bpy.ops.iops.materials_delete_unused() == {"FINISHED"}
    names = sorted(m.name for m in bpy.data.materials)
    assert names == ["LinkedUnused", "Used"], names


# ----------------------------------------------------------------------
# stage 2: asset shelf
# ----------------------------------------------------------------------
_ASSET_DIR = {}


def asset_library():
    """(folder, .blend path) of a temp asset library holding the material
    assets LibSteel and LibWood; built once per run."""
    if "path" in _ASSET_DIR:
        return _ASSET_DIR["folder"], _ASSET_DIR["path"]
    folder = tempfile.mkdtemp(prefix="iops_mat_assets_")
    path = os.path.join(folder, "materials.blend")
    mats = set()
    for name, rough in (("LibSteel", 0.2), ("LibWood", 0.8)):
        m = mat(name, rough)
        m.asset_mark()
        mats.add(m)
    bpy.data.libraries.write(path, mats)
    for m in mats:
        bpy.data.materials.remove(m)
    _ASSET_DIR.update(folder=folder, path=path)
    return folder, path


def prefs():
    return bpy.context.preferences.addons[ADDON].preferences


def assign_asset(path, name, **kw):
    return bpy.ops.iops.material_assign_asset(library_file=path,
                                              asset_name=name, **kw)


def test_library_add_is_idempotent():
    folder, _path = asset_library()
    libs = bpy.context.preferences.filepaths.asset_libraries
    count = len(libs)
    assert bpy.ops.iops.materials_library_add(directory=folder) == {"FINISHED"}
    assert len(libs) == count + 1
    name = prefs().materials_library
    lib = libs.get(name)
    assert lib is not None and name == os.path.basename(folder), name
    # same folder again, spelled differently: no second registration
    prefs().materials_library = ""
    assert bpy.ops.iops.materials_library_add(
        directory=folder.upper() + os.sep) == {"FINISHED"}
    assert len(libs) == count + 1
    assert prefs().materials_library == name


def test_append_reuse():
    _folder, path = asset_library()
    reset()
    prefs().materials_import_method = "APPEND_REUSE"
    mat("LibWood", 0.3)     # unrelated local material with the asset's name
    box = cube("Box")
    select(box)
    assert assign_asset(path, "LibSteel") == {"FINISHED"}
    assert slot_mats(box) == ["LibSteel"]
    count = len(bpy.data.materials)
    assert assign_asset(path, "LibSteel") == {"FINISHED"}
    assert len(bpy.data.materials) == count, "second import added a datablock"
    # name taken locally: first import gets .001, the next one reuses it
    assert assign_asset(path, "LibWood") == {"FINISHED"}
    imported = box.material_slots[0].material
    assert imported.name == "LibWood.001" and imported.library is None
    assert imported.asset_data is None, "appended copy kept its asset mark"
    count = len(bpy.data.materials)
    assert assign_asset(path, "LibWood") == {"FINISHED"}
    assert len(bpy.data.materials) == count
    assert box.material_slots[0].material == imported


def test_link():
    _folder, path = asset_library()
    reset()
    prefs().materials_import_method = "LINK"
    try:
        box = cube("Box")
        select(box)
        assert assign_asset(path, "LibSteel") == {"FINISHED"}
        linked = box.material_slots[0].material
        assert linked.library is not None and linked.name == "LibSteel"
        count = len(bpy.data.materials)
        assert assign_asset(path, "LibSteel", mode="FACES") in (
            {"FINISHED"}, {"CANCELLED"})
        assert len(bpy.data.materials) == count
    finally:
        prefs().materials_import_method = "APPEND_REUSE"


def test_missing_library_warns():
    reset()
    box = cube("Box")
    select(box)
    missing = os.path.join(tempfile.gettempdir(), "iops_no_such_lib.blend")
    assert assign_asset(missing, "LibSteel") == {"CANCELLED"}
    _folder, path = asset_library()
    assert assign_asset(path, "NotThere") == {"CANCELLED"}
    assert len(box.material_slots) == 0


def test_only_active_imports_without_assigning():
    _folder, path = asset_library()
    reset()
    box = cube("Box")
    select(box)
    assert assign_asset(path, "LibSteel", only_active=True) == {"FINISHED"}
    assert len(box.material_slots) == 0
    st = bpy.context.window_manager.iops_materials
    assert st.active_name == "LibSteel"


def test_current_file_asset():
    reset()
    local = mat("Local")
    local.asset_mark()
    box = cube("Box")
    select(box)
    count = len(bpy.data.materials)
    assert bpy.ops.iops.material_assign_asset(asset_name="Local") == {"FINISHED"}
    assert slot_mats(box) == ["Local"] and len(bpy.data.materials) == count


def test_mark_and_clear_asset():
    reset()
    m = mat("Paint")
    st = bpy.context.window_manager.iops_materials
    st.active_name, st.active_library = "Paint", ""
    assert bpy.ops.iops.materials_mark_asset() == {"FINISHED"}
    assert m.asset_data is not None
    assert bpy.ops.iops.materials_clear_asset() == {"FINISHED"}
    assert m.asset_data is None


def test_panel_and_shelf_polls():
    panel = bpy.types.IOPS_PT_Materials_Panel
    from InteractionOps.ui.iops_materials_shelf import IOPS_AST_materials
    try:
        prefs().materials_ui_mode = "LIBRARY_SHELF"
        assert not panel.poll(bpy.context)
        assert IOPS_AST_materials.poll(bpy.context)
        prefs().materials_ui_mode = "PANEL"
        assert panel.poll(bpy.context)
        assert not IOPS_AST_materials.poll(bpy.context)
    finally:
        prefs().materials_ui_mode = "PANEL"


class _FakeAsset:
    def __init__(self, id_type, path, local=None):
        self.id_type, self.full_library_path, self.local_id = id_type, path, local
        self.name = "X"


def test_shelf_asset_poll_library_filter():
    from InteractionOps.ui.iops_materials_shelf import IOPS_AST_materials
    folder, path = asset_library()
    bpy.ops.iops.materials_library_add(directory=folder)
    name = prefs().materials_library
    other = os.path.join(tempfile.gettempdir(), "elsewhere", "x.blend")
    poll = IOPS_AST_materials.asset_poll
    try:
        assert poll(_FakeAsset("MATERIAL", path))
        assert not poll(_FakeAsset("MATERIAL", other))
        assert poll(_FakeAsset("MATERIAL", "", local=object()))
        assert not poll(_FakeAsset("OBJECT", path))
        prefs().materials_library = ""
        assert poll(_FakeAsset("MATERIAL", other))
    finally:
        prefs().materials_library = name


def test_shelf_preview_size_follows_pref():
    from InteractionOps.ui.iops_materials_shelf import IOPS_AST_materials
    old = prefs().materials_thumbnail_size
    try:
        prefs().materials_thumbnail_size = 6
        assert IOPS_AST_materials.bl_default_preview_size == 120
        assert hasattr(bpy.types, "IOPS_AST_materials"), "shelf unregistered"
    finally:
        prefs().materials_thumbnail_size = old


def test_prefs_json_roundtrip():
    from InteractionOps.operators.preferences.io_addon_preferences import (
        load_iops_preferences, save_iops_preferences)
    prefs = bpy.context.preferences.addons[ADDON].preferences
    saved = {"materials_thumbnail_size": 7, "materials_list_rows": 13,
             "materials_gallery_rows": 5, "materials_stack_duplicates": False,
             "materials_default_view": "GALLERY",
             "materials_ui_mode": "LIBRARY_SHELF", "materials_import_method": "LINK",
             "materials_library": "Some Library",
             "materials_popup_width": 14,
             "materials_shelf_height": 230, "materials_shelf_thumbnail": 96,
             "materials_highlight_hover": False,
             "materials_shelf_tools_direction": "COLUMN",
             "materials_shelf_tools_position": "LEFT"}
    original = {k: getattr(prefs, k) for k in saved}
    try:
        for k, v in saved.items():
            setattr(prefs, k, v)
        save_iops_preferences()
        for k, v in original.items():
            setattr(prefs, k, v)
        load_iops_preferences()
        loaded = {k: getattr(prefs, k) for k in saved}
        assert loaded == saved, loaded
    finally:
        for k, v in original.items():
            setattr(prefs, k, v)
        save_iops_preferences()


# ----------------------------------------------------------------------
# stage 2b: iOps material shelf
# ----------------------------------------------------------------------
def test_ui_mode_polls():
    from InteractionOps.ui.iops_materials_shelf import IOPS_AST_materials
    from InteractionOps.ui.materials_shelf import STATE, shelf_active
    panel = bpy.types.IOPS_PT_Materials_Panel
    reset()
    try:
        STATE["visible"] = True
        prefs().materials_ui_mode = "IOPS_SHELF"
        assert shelf_active(bpy.context)
        assert not panel.poll(bpy.context)
        assert not IOPS_AST_materials.poll(bpy.context)
        STATE["visible"] = False
        assert not shelf_active(bpy.context)
        STATE["visible"] = True
        prefs().materials_ui_mode = "LIBRARY_SHELF"
        assert IOPS_AST_materials.poll(bpy.context)
        assert not shelf_active(bpy.context) and not panel.poll(bpy.context)
        prefs().materials_ui_mode = "PANEL"
        assert panel.poll(bpy.context)
        assert not shelf_active(bpy.context)
        assert not IOPS_AST_materials.poll(bpy.context)
    finally:
        prefs().materials_ui_mode = "PANEL"


def test_ui_mode_migration():
    import json
    from InteractionOps.operators.preferences.io_addon_preferences import (
        load_iops_preferences, save_iops_preferences)
    prefs().materials_ui_mode = "PANEL"
    save_iops_preferences()
    path = os.path.join(bpy.utils.script_path_user(), "presets", "IOPS",
                        "iops_prefs_user.json")
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    # what a file saved before the iOps shelf existed says
    data["MATERIALS_PANEL"]["materials_ui_mode"] = "SHELF"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f)
    try:
        load_iops_preferences()
        assert prefs().materials_ui_mode == "LIBRARY_SHELF", \
            prefs().materials_ui_mode
        # Blender stores its own copy of the prefs by enum value: 1 stays
        # the asset shelf
        items = prefs().bl_rna.properties["materials_ui_mode"].enum_items
        assert items["LIBRARY_SHELF"].value == 1
        assert items["PANEL"].value == 0 and items["IOPS_SHELF"].value == 2
    finally:
        prefs().materials_ui_mode = "PANEL"
        save_iops_preferences()


def test_assign_face_engine():
    from InteractionOps.operators.materials.assign import assign_face
    reset()
    a, steel = mat("A"), mat("Steel")
    box = cube("Box")
    give_slots(box, a)
    select()
    assert assign_face(box, 3, steel) is None
    assert slot_mats(box) == ["A", "Steel"]
    assert face_indices(box) == [0, 0, 0, 1, 0, 0]
    assert assign_face(box, 4, steel) is None
    assert slot_mats(box) == ["A", "Steel"]
    assert face_indices(box) == [0, 0, 0, 1, 1, 0]
    assert assign_face(box, 99, steel) == "no face"
    # an empty slot no other face uses is reused
    other = cube("Other")
    give_slots(other, a, None)
    assert assign_face(other, 2, steel) is None
    assert slot_mats(other) == ["A", "Steel"], slot_mats(other)
    assert face_indices(other) == [0, 0, 1, 0, 0, 0]
    # an empty slot other faces sit on is not
    third = cube("Third")
    give_slots(third, a, None)
    set_face_indices(third, [1, 1, 0, 0, 0, 0])
    assert assign_face(third, 2, steel) is None
    assert slot_mats(third) == ["A", None, "Steel"], slot_mats(third)
    assert assign_face(plain("Empty"), 0, steel) == "Empty"


def test_assign_face_edit_mode_and_drop_operator():
    from InteractionOps.operators.materials.assign import assign_face
    reset()
    a, steel = mat("A"), mat("Steel")
    box = cube("Box")
    give_slots(box, a)
    select(box)
    bpy.ops.object.mode_set(mode="EDIT")
    assert assign_face(box, 5, steel) is None
    bpy.ops.object.mode_set(mode="OBJECT")
    assert face_indices(box) == [0, 0, 0, 0, 0, 1]
    # the drop operator: an unselected object, whole object, and one face
    other = cube("Other")
    give_slots(other, a, a)
    select(box)
    assert bpy.ops.iops.material_assign_drop(
        material="Steel", object="Other", face=-1) == {"FINISHED"}
    assert slot_mats(other) == ["Steel"]
    assert bpy.ops.iops.material_assign_drop(
        material="A", object="Other", face=1) == {"FINISHED"}
    assert slot_mats(other) == ["Steel", "A"]
    assert face_indices(other) == [0, 1, 0, 0, 0, 0]
    plain("Empty")
    assert bpy.ops.iops.material_assign_drop(
        material="A", object="Empty", face=-1) == {"CANCELLED"}


def test_drop_on_selected_face_takes_the_selection():
    import bmesh
    reset()
    a = mat("A")
    mat("Steel")
    mat("Red")
    box = cube("Box")
    give_slots(box, a)
    select(box)
    bpy.ops.object.mode_set(mode="EDIT")
    bm = bmesh.from_edit_mesh(box.data)
    bm.faces.ensure_lookup_table()
    for f in bm.faces:
        f.select = f.index in (0, 1, 2)
    bmesh.update_edit_mesh(box.data)
    # a selected face: the three selected faces get it
    assert bpy.ops.iops.material_assign_drop(
        material="Steel", object="Box", face=1) == {"FINISHED"}
    # an unselected face: only that face
    assert bpy.ops.iops.material_assign_drop(
        material="Red", object="Box", face=5) == {"FINISHED"}
    bpy.ops.object.mode_set(mode="OBJECT")
    assert slot_mats(box) == ["A", "Steel", "Red"]
    assert face_indices(box) == [1, 1, 1, 0, 0, 2]
    # Object Mode keeps the single face even when the stored selection
    # holds it (the selection is not visible there)
    assert bpy.ops.iops.material_assign_drop(
        material="Red", object="Box", face=0) == {"FINISHED"}
    assert face_indices(box) == [2, 1, 1, 0, 0, 2]


def test_highlight_collect():
    from InteractionOps.ui.materials_shelf import highlight
    reset()
    a, b = mat("A"), mat("B")
    one, two = cube("One"), cube("Two")
    two.location.x = 3
    give_slots(one, a, b)
    set_face_indices(one, [0, 0, 1, 1, 1, 1])
    give_slots(two, a)
    select()
    bpy.context.view_layer.update()
    geom, tris, capped = highlight.collect(bpy.context, a)
    # 2 quads of One + 6 quads of Two, 2 triangles each
    assert tris == 16 and len(geom) == 48 and not capped, (tris, capped)
    assert geom[:, 0].max() > 2.0, "world transform not applied"
    geom, tris, capped = highlight.collect(bpy.context, a, max_tris=5)
    assert tris == 5 and capped
    # the cache is keyed by material + depsgraph generation
    highlight.set_hover(bpy.context, a)
    assert highlight.cache_info()["tris"] == 16
    highlight.set_hover(bpy.context, None)
    assert highlight.cache_info()["key"] is None


def test_highlight_cost_heavy_mesh():
    """Timing probe (printed): hover highlight on a 640 x 640 quad grid
    (819k triangles) with one material; the collection stops at the cap."""
    import time
    from InteractionOps.ui.materials_shelf import highlight
    reset()
    a = mat("A")
    me = bpy.data.meshes.new("Heavy")
    bm = bmesh.new()
    bmesh.ops.create_grid(bm, x_segments=640, y_segments=640, size=10)
    bm.to_mesh(me)
    bm.free()
    heavy = cube("Heavy", me)
    give_slots(heavy, a)
    select()
    bpy.context.view_layer.update()
    t0 = time.perf_counter()
    geom, tris, capped = highlight.collect(bpy.context, a)
    ms = (time.perf_counter() - t0) * 1000
    print(f"MEASURE highlight collect: {len(me.polygons)} faces, "
          f"{tris} triangles kept (cap {highlight.MAX_TRIS}), {ms:.1f} ms")
    assert capped and tris == highlight.MAX_TRIS


def test_shelf_unregister_is_clean():
    """Disable the add-on: the shelf's draw handlers, keymap entries,
    timer and textures are gone; enable it again afterwards."""
    from InteractionOps.ui.materials_shelf import draw, events, highlight, thumbs
    assert draw.handler_installed() and highlight.handler_installed()
    assert events.keymap_item_count() == 5
    kc = bpy.context.window_manager.keyconfigs.addon
    km = kc.keymaps["3D View"]
    assert sum(k.idname == "iops.material_shelf_event"
               for k in km.keymap_items) == 5
    bpy.ops.preferences.addon_disable(module=ADDON)
    assert not draw.handler_installed() and not highlight.handler_installed()
    assert events.keymap_item_count() == 0
    assert not thumbs.timer_registered()
    assert thumbs.texture_count() == 0
    assert not any(k.idname == "iops.material_shelf_event"
                   for k in km.keymap_items)
    assert thumbs._on_load not in bpy.app.handlers.load_post
    assert not bpy.app.timers.is_registered(events._tooltip_redraw)
    bpy.ops.preferences.addon_enable(module=ADDON)
    from InteractionOps.ui.materials_shelf import draw as draw2
    assert draw2.handler_installed()


TESTS = [
    test_prefs_json_roundtrip,
    test_ui_mode_polls,
    test_ui_mode_migration,
    test_assign_face_engine,
    test_assign_face_edit_mode_and_drop_operator,
    test_drop_on_selected_face_takes_the_selection,
    test_highlight_collect,
    test_highlight_cost_heavy_mesh,
    test_library_add_is_idempotent,
    test_append_reuse,
    test_link,
    test_missing_library_warns,
    test_only_active_imports_without_assigning,
    test_current_file_asset,
    test_mark_and_clear_asset,
    test_panel_and_shelf_polls,
    test_shelf_asset_poll_library_filter,
    test_shelf_preview_size_follows_pref,
    test_compatibility_skipping,
    test_linked_data_is_skipped,
    test_object_assign_collapses_slots,
    test_object_assign_shared_data_and_object_link,
    test_object_assign_in_edit_mode,
    test_faces_assign_edit_mode,
    test_faces_assign_object_mode,
    test_faces_assign_reuses_unused_empty_slot,
    test_faces_assign_reuses_empty_slot_of_selected_faces,
    test_faces_assign_keeps_empty_slot_of_other_faces,
    test_faces_assign_reuses_empty_slot_in_edit_mode,
    test_remove_empty_slots_object_mode,
    test_remove_empty_slots_edit_mode_and_shared,
    test_remove_empty_slots_scene_scope,
    test_empty_slot_count_cache,
    test_linked_material_assigns_without_copy,
    test_new_material,
    test_merge_equivalent_and_different,
    test_merge_material_setting_counts,
    test_merge_missing_base_renames,
    test_merge_single_group,
    test_merge_skips_linked,
    test_merge_collapses_user_case,
    test_merge_collapse_keeps_other_slots,
    test_merge_collapse_edit_mode,
    test_merge_collapse_shared_data,
    test_merge_removes_empty_slots,
    test_merge_toggles,
    test_merge_skips_object_linked_slots,
    test_merge_redo_through_undo,
    test_panel_rows_stack,
    test_remap_scopes,
    test_remap_rows_follow_scope,
    test_remap_chain_and_swap,
    test_remap_shared_data_once,
    test_remap_skips_incompatible_and_linked,
    test_remap_collapse_option,
    test_remap_nothing_to_do,
    test_copy_from_active,
    test_select_users,
    test_remove_unused_slots_object_mode,
    test_remove_unused_slots_edit_mode,
    test_clear_selected_and_scene,
    test_delete_unused,
    test_shelf_unregister_is_clean,
]


def main():
    require_isolated_user_resources()
    enable_addon()
    failed = 0
    for test in TESTS:
        try:
            test()
            print("PASS", test.__name__)
        except Exception:
            failed += 1
            print("FAIL", test.__name__)
            traceback.print_exc()
    print(f"{len(TESTS) - failed}/{len(TESTS)} passed")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
