"""Falloff fields: scene property groups, the multi-object edit-mesh domain and the stack / fit operators.

Run with an isolated user resource folder (the script refuses the real one, see ``_isolation.py``):
``BLENDER_USER_RESOURCES="$TEMP/iops_blender_res" blender --background --factory-startup --python-exit-code 1
--python <this>``.
"""

import math
import os
import sys
import traceback

import bmesh
import bpy
import numpy as np

# refuse to run against the real user resources (enable / disable write there)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _isolation import require_isolated_user_resources  # noqa: E402

require_isolated_user_resources()

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


def _modules():
    import importlib
    base = f"{ADDON}.operators.falloff"
    return (importlib.import_module(base + ".props"),
            importlib.import_module(base + ".domain"),
            importlib.import_module(base + ".fields"))


# --- fixture ------------------------------------------------------------------------------------------------------

def _grid_object(name):
    mesh = bpy.data.meshes.new(name)
    bm = bmesh.new()
    bmesh.ops.create_grid(bm, x_segments=10, y_segments=10, size=1.0)
    assert len(bm.verts) == 121, len(bm.verts)
    co = np.array([v.co[:] for v in bm.verts])
    span = co.max(axis=0) - co.min(axis=0)
    if abs(span[0] - 2.0) > 1e-5:          # rescale to exactly [-1, 1]
        k = 2.0 / span[0]
        for v in bm.verts:
            v.co.x *= k
            v.co.y *= k
        co = np.array([v.co[:] for v in bm.verts])
        span = co.max(axis=0) - co.min(axis=0)
    assert abs(span[0] - 2.0) < 1e-5 and abs(span[1] - 2.0) < 1e-5, span
    assert abs(co[:, 2]).max() < 1e-7
    bm.to_mesh(mesh)
    bm.free()
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    return obj


def _clear_objects():
    if bpy.context.object and bpy.context.object.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o)


def setup_scene():
    _clear_objects()
    a = _grid_object("A")
    b = _grid_object("B")
    b.location = (3, 0, 0)
    b.rotation_euler = (0, 0, math.radians(45))
    b.scale = (2, 1, 1)
    bpy.context.view_layer.update()
    for o in bpy.context.view_layer.objects:
        o.select_set(False)
    a.select_set(True)
    b.select_set(True)
    bpy.context.view_layer.objects.active = a
    bpy.ops.object.mode_set(mode="EDIT")
    s = bpy.context.scene.IOPS.falloff
    s.fields.clear()
    s.active_index = 0
    s.fit_signature = ""
    s.fit_mode = "PCA"
    return a, b


def bm_of(obj):
    return bmesh.from_edit_mesh(obj.data)


def select_where(obj, pred):
    bm = bm_of(obj)
    for v in bm.verts:
        v.select = bool(pred(v.co))
    bm.select_flush_mode()
    bmesh.update_edit_mesh(obj.data)


def co_bytes(obj):
    return np.array([v.co[:] for v in bm_of(obj).verts], dtype=np.float32).tobytes()


def world_co(obj):
    mw = np.array(obj.matrix_world)
    co = np.array([v.co[:] for v in bm_of(obj).verts], dtype=np.float64)
    return co @ mw[:3, :3].T + mw[:3, 3]


# --- tests --------------------------------------------------------------------------------------------------------

def test_scene_properties():
    setup_scene()
    scene = bpy.context.scene
    assert hasattr(scene.IOPS, "falloff")
    assert not hasattr(scene.IOPS, "falloff_type")
    assert len(scene.IOPS.falloff.fields) == 0


def test_domain_fallback_and_selection():
    _, domain_mod, _ = _modules()
    a, b = setup_scene()
    select_where(a, lambda co: False)
    select_where(b, lambda co: False)
    d = domain_mod.collect_domain(bpy.context)
    assert d is not None and d.selected is False and len(d.P) == 242, (d.selected, len(d.P))
    domain_mod.finish_domain(d, normals=False)

    select_where(a, lambda co: True)
    d = domain_mod.collect_domain(bpy.context)
    assert d.selected is True and len(d.P) == 121, len(d.P)
    assert len(d.entries) == 1 and d.entries[0].obj == a
    mw = np.array(a.matrix_world)
    expect = np.array([mw @ np.array([*v.co[:], 1.0]) for v in bm_of(a).verts])[:, :3]
    assert np.allclose(d.P, expect, atol=1e-6)
    assert np.allclose(np.linalg.norm(d.N, axis=1), 1.0, atol=1e-5)
    domain_mod.finish_domain(d, normals=False)


def test_hidden_vert_is_not_in_domain():
    _, domain_mod, _ = _modules()
    a, b = setup_scene()
    select_where(a, lambda co: True)
    bm = bm_of(a)
    bm.verts.ensure_lookup_table()
    bm.verts[5].hide_set(True)
    bmesh.update_edit_mesh(a.data)
    d = domain_mod.collect_domain(bpy.context)
    assert len(d.P) == 120, len(d.P)
    assert all(not v.hide for v in d.entries[0].verts)
    domain_mod.finish_domain(d, normals=False)


def test_write_back_identity_leaves_bytes():
    _, domain_mod, _ = _modules()
    a, b = setup_scene()
    select_where(a, lambda co: True)
    select_where(b, lambda co: True)
    before = (co_bytes(a), co_bytes(b))
    d = domain_mod.collect_domain(bpy.context)
    assert len(d.entries) == 2 and len(d.P) == 242
    domain_mod.write_back(d, d.P)
    domain_mod.finish_domain(d, normals=False)
    assert (co_bytes(a), co_bytes(b)) == before


def test_write_back_moves_world_z_and_respects_rows():
    _, domain_mod, _ = _modules()
    a, b = setup_scene()
    select_where(a, lambda co: True)
    select_where(b, lambda co: True)
    wa, wb = world_co(a), world_co(b)
    ba = co_bytes(a)
    d = domain_mod.collect_domain(bpy.context)
    P = d.P + np.array([0.0, 0.0, 1.0])
    domain_mod.write_back(d, P, rows=np.arange(121, 242))
    domain_mod.finish_domain(d, normals=False)
    assert co_bytes(a) == ba, "rows not given were written"
    got = world_co(b)
    assert np.allclose(got - wb, [0, 0, 1], atol=1e-5), (got - wb)[:3]
    assert np.allclose(world_co(a), wa)


def test_field_add_and_roundtrip():
    props, _, _ = _modules()
    a, b = setup_scene()
    select_where(a, lambda co: abs(co.x) < 0.81 and abs(co.y) < 0.21)
    r = bpy.ops.iops.mesh_falloff_field_add(type="LINEAR")
    assert r == {"FINISHED"}, r
    s = bpy.context.scene.IOPS.falloff
    assert len(s.fields) == 1 and s.active_index == 0 and s.last_type == "LINEAR"
    f = props.active_field(s)
    d = np.array(f.end[:]) - np.array(f.start[:])
    assert abs(d[0]) > 4 * max(abs(d[1]), 1e-6) and abs(d[0]) > 1.5, tuple(d)
    lst = props.stack_to_list(s.fields)
    props.dict_to_field(lst[0], f)
    assert props.stack_to_list(s.fields) == lst
    props.copy_stack(s.fields, s.fields)
    assert props.stack_to_list(s.fields) == lst and s.fields[0].name == "Falloff 1"


def test_new_fields_are_named_falloff_n_and_unique():
    a, b = setup_scene()
    select_where(a, lambda co: True)
    s = bpy.context.scene.IOPS.falloff
    for t in ("LINEAR", "LINEAR", "RADIAL"):
        bpy.ops.iops.mesh_falloff_field_add(type=t)
    assert [f.name for f in s.fields] == ["Falloff 1", "Falloff 2", "Falloff 3"], [f.name for f in s.fields]
    s.active_index = 1
    bpy.ops.iops.mesh_falloff_field_remove()
    bpy.ops.iops.mesh_falloff_field_add(type="LINEAR")
    names = [f.name for f in s.fields]
    assert len(set(names)) == len(names) == 3, names
    assert all(n.startswith("Falloff ") for n in names), names
    s.fields.clear()
    assert bpy.ops.iops.mesh_falloff_fit() == {"FINISHED"}
    assert s.fields[0].name == "Falloff 1", s.fields[0].name


def test_fit_cycles_and_resets():
    props, _, _ = _modules()
    a, b = setup_scene()
    select_where(a, lambda co: abs(co.x) < 0.81 and abs(co.y) < 0.21)
    s = bpy.context.scene.IOPS.falloff
    seen = []
    for _ in range(4):
        assert bpy.ops.iops.mesh_falloff_fit() == {"FINISHED"}
        seen.append(s.fit_mode)
    assert seen == ["PCA", "X", "Y", "Z"], seen
    f = props.active_field(s)
    assert abs(f.end[2] - f.start[2]) > 0.0 and abs(f.end[0] - f.start[0]) < 1e-5   # Z fit
    select_where(a, lambda co: abs(co.x) < 0.41)
    assert bpy.ops.iops.mesh_falloff_fit() == {"FINISHED"}
    assert s.fit_mode == "PCA", s.fit_mode


def test_fit_on_empty_stack_clears_custom_pivot():
    a, b = setup_scene()
    select_where(a, lambda co: True)
    s = bpy.context.scene.IOPS.falloff
    s.use_custom_pivot = True
    assert len(s.fields) == 0
    assert bpy.ops.iops.mesh_falloff_fit() == {"FINISHED"}
    assert len(s.fields) == 1 and s.use_custom_pivot is False


def test_stack_operators_keep_index_in_range():
    props, _, _ = _modules()
    a, b = setup_scene()
    select_where(a, lambda co: True)
    s = bpy.context.scene.IOPS.falloff
    assert props.active_field(s) is None
    for t in ("LINEAR", "RADIAL", "ELLIPTICAL"):
        bpy.ops.iops.mesh_falloff_field_add(type=t)
    assert len(s.fields) == 3 and s.active_index == 2
    assert [f.type for f in s.fields] == ["LINEAR", "RADIAL", "ELLIPTICAL"]
    assert bpy.ops.iops.mesh_falloff_field_move(direction="UP") == {"FINISHED"}
    assert s.active_index == 1 and s.fields[1].type == "ELLIPTICAL"
    assert bpy.ops.iops.mesh_falloff_field_move(direction="DOWN") == {"FINISHED"}
    assert s.active_index == 2
    assert bpy.ops.iops.mesh_falloff_field_move(direction="DOWN") == {"CANCELLED"}
    bpy.ops.iops.mesh_falloff_field_remove()
    assert len(s.fields) == 2 and 0 <= s.active_index < 2
    s.use_custom_pivot = True
    assert bpy.ops.iops.mesh_falloff_pivot_reset() == {"FINISHED"}
    assert s.use_custom_pivot is False
    s.use_custom_pivot = True
    bpy.ops.iops.mesh_falloff_clear()
    assert len(s.fields) == 0 and s.active_index == 0 and s.use_custom_pivot is False
    assert props.active_field(s) is None
    assert bpy.ops.iops.mesh_falloff_field_remove() == {"CANCELLED"}


def test_empty_mesh_has_no_domain():
    _, domain_mod, _ = _modules()
    setup_scene()
    _clear_objects()
    obj = bpy.data.objects.new("E", bpy.data.meshes.new("E"))
    bpy.context.scene.collection.objects.link(obj)
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.mode_set(mode="EDIT")
    assert domain_mod.collect_domain(bpy.context) is None
    bpy.context.scene.IOPS.falloff.fields.clear()
    assert bpy.ops.iops.mesh_falloff_fit() == {"CANCELLED"}
    assert len(bpy.context.scene.IOPS.falloff.fields) == 0


def _activate(obj):
    bpy.context.view_layer.objects.active = obj


def test_basis_local_world_cursor():
    _, domain_mod, _ = _modules()
    a, b = setup_scene()
    select_where(a, lambda co: True)
    select_where(b, lambda co: True)
    _activate(b)
    s = bpy.context.scene.IOPS.falloff
    d = domain_mod.collect_domain(bpy.context)
    c, sn = math.cos(math.radians(45)), math.sin(math.radians(45))
    s.basis = "LOCAL"
    R = domain_mod.basis_matrix(bpy.context, d)
    assert np.allclose(R, [[c, -sn, 0], [sn, c, 0], [0, 0, 1]], atol=1e-6), R
    lo, hi = d.P.min(axis=0), d.P.max(axis=0)
    assert np.allclose(domain_mod.auto_pivot(bpy.context, d), (lo + hi) / 2, atol=1e-6)
    # the active object decides the axes: A is unrotated
    _activate(a)
    assert np.allclose(domain_mod.basis_matrix(bpy.context, d), np.eye(3), atol=1e-6)
    s.basis = "WORLD"
    assert np.allclose(domain_mod.basis_matrix(bpy.context, d), np.eye(3))
    assert np.allclose(domain_mod.auto_pivot(bpy.context, d), 0.0)
    cur = bpy.context.scene.cursor
    cur.location = (1.0, 2.0, 3.0)
    cur.rotation_mode = "XYZ"
    cur.rotation_euler = (0.0, 0.0, math.radians(90))
    s.basis = "CURSOR"
    assert np.allclose(domain_mod.auto_pivot(bpy.context, d), (1, 2, 3), atol=1e-6)
    assert np.allclose(domain_mod.basis_matrix(bpy.context, d),
                       [[0, -1, 0], [1, 0, 0], [0, 0, 1]], atol=1e-6)
    domain_mod.finish_domain(d, normals=False)


def test_basis_local_pivot_of_b_alone():
    _, domain_mod, _ = _modules()
    a, b = setup_scene()
    select_where(b, lambda co: True)
    _activate(b)
    bpy.context.scene.IOPS.falloff.basis = "LOCAL"
    d = domain_mod.collect_domain(bpy.context)
    assert np.allclose(domain_mod.auto_pivot(bpy.context, d), (3, 0, 0), atol=1e-5)
    domain_mod.finish_domain(d, normals=False)


def test_basis_normal_active_face_on_transformed_object():
    _, domain_mod, _ = _modules()
    a, b = setup_scene()
    _activate(b)
    select_where(a, lambda co: False)
    select_where(b, lambda co: False)
    bm = bm_of(b)
    bm.select_history.clear()
    face = next(f for f in bm.faces
                if abs(f.calc_center_median().x - 0.9) < 1e-4
                and abs(f.calc_center_median().y - 0.9) < 1e-4)
    for v in face.verts:
        v.select = True
    bm.select_flush_mode()
    bm.faces.active = face
    sign = 1.0 if face.normal.z > 0 else -1.0
    a_, b_ = face.edges[0].verts
    mw = np.array(b.matrix_world)
    wa = mw[:3, :3] @ np.array(a_.co[:]) + mw[:3, 3]
    wb = mw[:3, :3] @ np.array(b_.co[:]) + mw[:3, 3]
    bpy.context.scene.IOPS.falloff.basis = "NORMAL"
    d = domain_mod.collect_domain(bpy.context)
    assert len(d.P) == 4
    piv = domain_mod.auto_pivot(bpy.context, d)
    c, sn = math.cos(math.radians(45)), math.sin(math.radians(45))
    expect = np.array([3 + 1.8 * c - 0.9 * sn, 1.8 * sn + 0.9 * c, 0.0])
    assert np.allclose(piv, expect, atol=1e-5), (piv, expect)
    R = domain_mod.basis_matrix(bpy.context, d)
    assert np.allclose(R[:, 2], [0, 0, sign], atol=1e-5), R
    t = (wb - wa) / np.linalg.norm(wb - wa)
    assert np.allclose(R[:, 0], t, atol=1e-5), (R[:, 0], t)
    assert np.allclose(R.T @ R, np.eye(3), atol=1e-6)
    domain_mod.finish_domain(d, normals=False)


def test_selection_signature():
    _, domain_mod, _ = _modules()
    a, b = setup_scene()
    select_where(a, lambda co: abs(co.x) < 0.81)
    d1 = domain_mod.collect_domain(bpy.context)
    d2 = domain_mod.collect_domain(bpy.context)
    s1 = domain_mod.selection_signature(d1)
    assert s1 == domain_mod.selection_signature(d2)
    domain_mod.finish_domain(d1, normals=False)
    domain_mod.finish_domain(d2, normals=False)
    select_where(a, lambda co: abs(co.x) < 0.61)
    d3 = domain_mod.collect_domain(bpy.context)
    assert domain_mod.selection_signature(d3) != s1
    domain_mod.finish_domain(d3, normals=False)
    assert domain_mod.selection_signature(None) == "0"


TESTS = [
    test_scene_properties,
    test_domain_fallback_and_selection,
    test_hidden_vert_is_not_in_domain,
    test_write_back_identity_leaves_bytes,
    test_write_back_moves_world_z_and_respects_rows,
    test_field_add_and_roundtrip,
    test_new_fields_are_named_falloff_n_and_unique,
    test_fit_cycles_and_resets,
    test_fit_on_empty_stack_clears_custom_pivot,
    test_stack_operators_keep_index_in_range,
    test_empty_mesh_has_no_domain,
    test_basis_local_world_cursor,
    test_basis_local_pivot_of_b_alone,
    test_basis_normal_active_face_on_transformed_object,
    test_selection_signature,
]


def main():
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
