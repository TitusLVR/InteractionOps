"""Headless tests for the iOps Attributes panel backend, operators and UI
state on real meshes. Run from the repo root via:

    blender --background --factory-startup --python-exit-code 1 --python tests/blender/test_attribute_editor.py

Not collected by pytest (tests/conftest.py ignores tests/blender).
"""
import os
import sys
import traceback

import bpy
import bmesh

ADDON = "InteractionOps"


def enable_addon():
    repo_root = os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))))
    repo_parent = os.path.dirname(repo_root)
    if repo_parent not in sys.path:
        sys.path.insert(0, repo_parent)
    bpy.ops.preferences.addon_enable(module=ADDON)
    assert ADDON in bpy.context.preferences.addons, "addon not enabled"
    import InteractionOps
    loaded = os.path.dirname(os.path.abspath(InteractionOps.__file__))
    assert os.path.samefile(loaded, repo_root), f"addon loaded from {loaded}"


# ---------------------------------------------------------------------------
# scene helpers
# ---------------------------------------------------------------------------
def _reset():
    if bpy.context.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    for ob in list(bpy.data.objects):
        bpy.data.objects.remove(ob)
    for me in list(bpy.data.meshes):
        bpy.data.meshes.remove(me)


def _link(obj):
    bpy.context.scene.collection.objects.link(obj)
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    return obj


def _set_attr(me, name, values):
    attr = me.attributes[name]
    flat = []
    for v in values:
        if isinstance(v, (tuple, list)):
            flat.extend(v)
        else:
            flat.append(v)
    prop = "vector" if attr.data_type == "FLOAT_VECTOR" else "value"
    attr.data.foreach_set(prop, flat)


def _track_mesh(name="track", with_attrs=True):
    """6 verts on X, 5 edges, no faces. tilt=[0..50], scale=[1..6],
    vertex group marks on verts 0,1,2 with weight 0.5."""
    me = bpy.data.meshes.new(name)
    me.from_pydata([(float(i), 0.0, 0.0) for i in range(6)],
                   [(i, i + 1) for i in range(5)], [])
    obj = bpy.data.objects.new(name, me)
    if with_attrs:
        me.attributes.new("tilt", "FLOAT", "POINT")
        _set_attr(me, "tilt", [0.0, 10.0, 20.0, 30.0, 40.0, 50.0])
        me.attributes.new("scale", "FLOAT", "POINT")
        _set_attr(me, "scale", [1.0, 2.0, 3.0, 4.0, 5.0, 6.0])
        vg = obj.vertex_groups.new(name="marks")
        vg.add([0, 1, 2], 0.5, "REPLACE")
    return _link(obj)


def _quad_mesh(name="quads"):
    """Two quads sharing an edge; CORNER float attribute `c` = 0."""
    me = bpy.data.meshes.new(name)
    me.from_pydata([(0, 0, 0), (1, 0, 0), (2, 0, 0), (0, 1, 0), (1, 1, 0),
                    (2, 1, 0)], [], [(0, 1, 4, 3), (1, 2, 5, 4)])
    me.attributes.new("c", "FLOAT", "CORNER")
    obj = bpy.data.objects.new(name, me)
    return _link(obj)


def _edit():
    bpy.ops.object.mode_set(mode="EDIT")
    obj = bpy.context.edit_object
    bm = bmesh.from_edit_mesh(obj.data)
    bm.verts.ensure_lookup_table()
    bm.edges.ensure_lookup_table()
    bm.faces.ensure_lookup_table()
    return obj, bm


def _object():
    bpy.ops.object.mode_set(mode="OBJECT")


def _select(bm, domain, indices):
    seq = {"POINT": bm.verts, "EDGE": bm.edges, "FACE": bm.faces}[domain]
    for e in seq:
        e.select = False
    for e in bm.verts:
        e.select = False
    for i in indices:
        seq[i].select = True
    bm.select_flush_mode()


def _attr(me, name):
    attr = me.attributes[name]
    return [d.value for d in attr.data]


def _vec_attr(me, name):
    return [tuple(d.vector) for d in me.attributes[name].data]


def _weight(obj, vi, group="marks"):
    gi = obj.vertex_groups[group].index
    for g in obj.data.vertices[vi].groups:
        if g.group == gi:
            return g.weight
    return None


def _row(name, data_type="FLOAT", domain="POINT", kind="ATTR"):
    from InteractionOps.utils.attribute_editor_core import Row
    return Row(name, data_type, domain, kind, True)


# ---------------------------------------------------------------------------
# Task 3: backend
# ---------------------------------------------------------------------------
def test_bm_write_selected_only():
    from InteractionOps.operators import mesh_attribute_editor as mae
    _reset()
    obj = _track_mesh()
    _, bm = _edit()
    _select(bm, "POINT", [1, 2])
    row = _row("tilt")
    n = mae.bm_write(bm, row, mae.bm_selected_indices(bm, "POINT"), 45.0)
    mae.finish_edit(obj)
    _object()
    assert n == 2
    assert _attr(obj.data, "tilt") == [0.0, 45.0, 45.0, 30.0, 40.0, 50.0]


def test_write_ignores_hidden():
    from InteractionOps.operators import mesh_attribute_editor as mae
    _reset()
    obj = _track_mesh()
    _, bm = _edit()
    for v in bm.verts:
        v.select = True
    bm.verts[0].hide = True
    bm.verts[0].select = False
    idx = mae.bm_selected_indices(bm, "POINT")
    assert 0 not in idx and len(idx) == 5
    n = mae.bm_write(bm, _row("tilt"), idx, 7.0)
    mae.finish_edit(obj)
    _object()
    assert n == 5
    assert _attr(obj.data, "tilt")[0] == 0.0


def test_corner_write_all_loops():
    from InteractionOps.operators import mesh_attribute_editor as mae
    _reset()
    obj = _quad_mesh()
    _, bm = _edit()
    _select(bm, "FACE", [0])
    row = _row("c", "FLOAT", "CORNER")
    idx = mae.bm_selected_indices(bm, "CORNER")
    assert idx == [0]
    mae.bm_write(bm, row, idx, 1.0)
    assert mae.bm_read(bm, row, 0) == 1.0
    mae.finish_edit(obj)
    _object()
    me = obj.data
    vals = _attr(me, "c")
    f0 = me.polygons[0]
    f1 = me.polygons[1]
    assert all(vals[i] == 1.0 for i in range(f0.loop_start,
                                            f0.loop_start + f0.loop_total))
    assert all(vals[i] == 0.0 for i in range(f1.loop_start,
                                            f1.loop_start + f1.loop_total))


def test_vgroup_write_adds_vertex():
    from InteractionOps.operators import mesh_attribute_editor as mae
    _reset()
    obj = _track_mesh()
    gi = mae.vgroup_index(obj, "marks")
    _, bm = _edit()
    row = _row("marks", "VGROUP", "POINT", "VGROUP")
    assert mae.bm_read(bm, row, 3, group_index=gi) == 0.0
    assert mae.bm_read(bm, row, 1, group_index=gi) == 0.5
    mae.bm_write(bm, row, [3], 0.7, group_index=gi)
    mae.finish_edit(obj)
    _object()
    assert abs(_weight(obj, 3) - 0.7) < 1e-6


def test_write_skips_meshes_without_attr():
    from InteractionOps.operators import mesh_attribute_editor as mae
    _reset()
    other = _track_mesh("other", with_attrs=False)
    obj = _track_mesh()
    other.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")
    pairs = mae.edit_meshes(bpy.context)
    assert len(pairs) == 2
    row = _row("tilt")
    for o, bm in pairs:
        layer = mae.bm_layer(bm, row)
        if layer is None:
            assert o is other
            continue
        for v in bm.verts:
            v.select = True
        mae.bm_write(bm, row, mae.bm_selected_indices(bm, "POINT"), 3.0)
        mae.finish_edit(o)
    _object()
    assert "tilt" not in other.data.attributes
    assert _attr(obj.data, "tilt") == [3.0] * 6


def test_snapshot_in_edit_mode_reads_edit_state():
    from InteractionOps.operators import mesh_attribute_editor as mae
    _reset()
    obj = _track_mesh()
    obj.location = (0.0, 0.0, 5.0)
    obj.data.attributes.new("ew", "FLOAT", "EDGE")
    _, bm = _edit()
    layer = bm.verts.layers.float["tilt"]
    bm.verts[0][layer] = 99.0
    _select(bm, "POINT", [2])
    pos, vals, sel, hid = mae.snapshot(obj, "tilt", "POINT")
    assert pos.shape == (6, 3)
    assert abs(pos[1][2] - 5.0) < 1e-6 and abs(pos[1][0] - 1.0) < 1e-6
    assert vals[0] == 99.0 and vals[5] == 50.0
    assert list(sel) == [False, False, True, False, False, False]
    assert not hid.any()
    # edge domain: midpoints
    assert mae.snapshot(obj, "tilt", "EDGE") is None   # domain mismatch
    epos, evals, _, _ = mae.snapshot(obj, "ew", "EDGE")
    assert epos.shape == (5, 3) and abs(epos[0][0] - 0.5) < 1e-6
    _object()
    # vertex group snapshot
    _, w, _, _ = mae.snapshot(obj, "marks", "POINT", kind="VGROUP")
    assert list(w) == [0.5, 0.5, 0.5, 0.0, 0.0, 0.0]
    assert mae.snapshot(bpy.data.objects.new("e", None), "x", "POINT") is None


def test_mesh_write_all_object_mode():
    from InteractionOps.operators import mesh_attribute_editor as mae
    _reset()
    obj = _track_mesh()
    me = obj.data
    mae.mesh_write_all(me, "tilt", 5.0)
    assert _attr(me, "tilt") == [5.0] * 6
    assert mae.mesh_read_all(me, "tilt") == [5.0] * 6
    me.attributes.new("v", "FLOAT_VECTOR", "POINT")
    mae.mesh_write_all(me, "v", (1.0, 2.0, 3.0))
    assert _vec_attr(me, "v") == [(1.0, 2.0, 3.0)] * 6
    assert mae.mesh_read_all(me, "v")[0] == (1.0, 2.0, 3.0)
    me.attributes.new("b", "BOOLEAN", "EDGE")
    mae.mesh_write_all(me, "b", True)
    assert mae.mesh_read_all(me, "b") == [True] * 5


# ---------------------------------------------------------------------------
# Task 4: operators
# ---------------------------------------------------------------------------
def test_set_value_edit_mode_and_undo():
    _reset()
    obj = _track_mesh()
    # background mode starts with the undo system disabled
    bpy.ops.ed.undo_push(message="init")
    _, bm = _edit()
    _select(bm, "POINT", [1, 2])
    bmesh.update_edit_mesh(obj.data)
    bpy.ops.ed.undo_push(message="select")
    ret = bpy.ops.iops.attr_set_value(row_name="tilt", row_kind="ATTR",
                                      value_float=45.0)
    assert ret == {"FINISHED"}
    bm = bmesh.from_edit_mesh(obj.data)
    layer = bm.verts.layers.float["tilt"]
    assert [v[layer] for v in bm.verts] == [0.0, 45.0, 45.0, 30.0, 40.0, 50.0]
    assert "UNDO" in bpy.types.IOPS_OT_attr_set_value.bl_options
    bpy.ops.ed.undo()
    # background-mode undo may collapse edit-mode steps into the memfile
    # step and leave Edit Mode; either way the write must be reverted.
    if bpy.context.mode == "EDIT_MESH":
        bm = bmesh.from_edit_mesh(obj.data)
        layer = bm.verts.layers.float["tilt"]
        assert [v[layer] for v in bm.verts] == [0.0, 10.0, 20.0, 30.0, 40.0,
                                                50.0]
        _object()
    obj = bpy.data.objects["track"]
    assert _attr(obj.data, "tilt") == [0.0, 10.0, 20.0, 30.0, 40.0, 50.0]


def test_set_value_nothing_selected_cancels():
    _reset()
    obj = _track_mesh()
    _, bm = _edit()
    _select(bm, "POINT", [])
    ret = bpy.ops.iops.attr_set_value(row_name="tilt", row_kind="ATTR",
                                      value_float=45.0)
    assert ret == {"CANCELLED"}
    _object()
    assert _attr(obj.data, "tilt")[1] == 10.0


def test_set_value_object_mode_sets_all():
    _reset()
    obj = _track_mesh()
    bpy.ops.iops.attr_set_value(row_name="tilt", row_kind="ATTR",
                                value_float=45.0)
    assert _attr(obj.data, "tilt") == [45.0] * 6
    bpy.ops.iops.attr_set_value(row_name="marks", row_kind="VGROUP",
                                value_float=0.25)
    assert all(abs(_weight(obj, i) - 0.25) < 1e-6 for i in range(6))


def test_fill_unselected_reset():
    _reset()
    obj = _track_mesh()
    _, bm = _edit()
    _select(bm, "POINT", [0])
    bpy.ops.iops.attr_fill(row_name="scale", row_kind="ATTR",
                           target="UNSELECTED", reset=True)
    _object()
    assert _attr(obj.data, "scale") == [1.0, 0.0, 0.0, 0.0, 0.0, 0.0]
    _edit()
    bpy.ops.iops.attr_fill(row_name="scale", row_kind="ATTR", target="ALL",
                           value_float=2.0)
    _object()
    assert _attr(obj.data, "scale") == [2.0] * 6


def test_new_duplicate_remove():
    _reset()
    obj = _track_mesh()
    me = obj.data
    bpy.ops.iops.attr_new(name="tilt", data_type="FLOAT", domain="POINT",
                          value_float=3.0)
    assert "tilt.001" in me.attributes
    assert _attr(me, "tilt.001") == [3.0] * 6
    assert me.attributes.active.name == "tilt.001"
    bpy.ops.iops.attr_duplicate(row_name="tilt", row_kind="ATTR")
    assert _attr(me, "tilt.copy") == [0.0, 10.0, 20.0, 30.0, 40.0, 50.0]
    bpy.ops.iops.attr_remove(row_name="tilt.copy", row_kind="ATTR")
    assert "tilt.copy" not in me.attributes
    # edit mode: new + duplicate through bmesh layers
    _edit()
    bpy.ops.iops.attr_new(name="e", data_type="INT", domain="EDGE")
    bpy.ops.iops.attr_duplicate(row_name="tilt", row_kind="ATTR")
    bpy.ops.iops.attr_remove(row_name="marks", row_kind="VGROUP")
    _object()
    assert me.attributes["e"].domain == "EDGE"
    assert _attr(me, "tilt.copy") == [0.0, 10.0, 20.0, 30.0, 40.0, 50.0]
    assert "marks" not in obj.vertex_groups


def test_convert_object_mode():
    _reset()
    obj = _track_mesh()
    bpy.ops.iops.attr_convert(row_name="tilt", row_kind="ATTR",
                              data_type="INT", domain="POINT")
    assert obj.data.attributes["tilt"].data_type == "INT"
    assert _attr(obj.data, "tilt") == [0, 10, 20, 30, 40, 50]


TESTS_TASK4 = [
    test_set_value_edit_mode_and_undo,
    test_set_value_nothing_selected_cancels,
    test_set_value_object_mode_sets_all,
    test_fill_unselected_reset,
    test_new_duplicate_remove,
    test_convert_object_mode,
]


# ---------------------------------------------------------------------------
# Task 5: UI state (mirror, cache, value fields)
# ---------------------------------------------------------------------------
def _ap():
    import time
    from InteractionOps.ui import iops_attribute_panel as ap
    ap._LAST_DRAW = time.monotonic()      # pretend the panel is visible
    return ap


def _mirror_names():
    return [it.name for it in bpy.context.window_manager.iops_attr.mirror]


def _set_active_row(name):
    st = bpy.context.window_manager.iops_attr
    st.index = _mirror_names().index(name)


def test_mirror_lists_rows_and_syncs_active():
    ap = _ap()
    _reset()
    obj = _track_mesh()
    ap.rebuild_mirror(bpy.context, force=True)
    assert _mirror_names() == ["scale", "tilt", "marks"]
    _set_active_row("scale")
    assert obj.data.attributes.active.name == "scale"
    _set_active_row("marks")
    assert obj.vertex_groups.active.name == "marks"
    it = bpy.context.window_manager.iops_attr.mirror[1]
    assert (it.data_type, it.domain, it.kind, it.editable) \
        == ("FLOAT", "POINT", "ATTR", True)
    assert it.count == 6


def test_mirror_clamps_after_remove():
    ap = _ap()
    _reset()
    obj = _track_mesh()
    ap.rebuild_mirror(bpy.context, force=True)
    st = bpy.context.window_manager.iops_attr
    _set_active_row("marks")
    obj.vertex_groups.remove(obj.vertex_groups["marks"])
    obj.data.attributes.remove(obj.data.attributes["tilt"])
    ap.rebuild_mirror(bpy.context, force=True)
    assert _mirror_names() == ["scale"]
    assert 0 <= st.index < len(st.mirror)


def test_cache_reads_active_vertex_and_mixed():
    ap = _ap()
    _reset()
    _track_mesh()
    ap.rebuild_mirror(bpy.context, force=True)
    _set_active_row("tilt")
    _, bm = _edit()
    _select(bm, "POINT", [1, 2])
    bm.select_history.add(bm.verts[2])
    ap.refresh_cache(bpy.context, force=True)
    c = ap._CACHE["rows"]["tilt"]
    assert c["value"] == 20.0 and c["mixed"] == 2 and c["first"] is False
    assert c["selected"] == 2 and c["index"] == 2
    # only the active row is cached; no active history → first selected
    assert "scale" not in ap._CACHE["rows"]
    bm.select_history.clear()
    _set_active_row("scale")
    ap.refresh_cache(bpy.context, force=True)
    c = ap._CACHE["rows"]["scale"]
    assert c["value"] == 2.0 and c["first"] is True and c["index"] == 1
    assert ap._index_text(c, True) == "1  (2 selected)"
    _select(bm, "POINT", [])
    ap.refresh_cache(bpy.context, force=True)
    c = ap._CACHE["rows"]["scale"]
    assert c["index"] is None
    assert ap._index_text(c, True) == "none"
    _object()


def test_cache_keeps_data_during_modal():
    ap = _ap()
    _reset()
    _track_mesh()
    ap.rebuild_mirror(bpy.context, force=True)
    _set_active_row("tilt")
    _, bm = _edit()
    _select(bm, "POINT", [1])
    ap.refresh_cache(bpy.context, force=True)
    assert ap._CACHE["rows"]["tilt"]["value"] == 10.0
    _select(bm, "POINT", [3])
    saved = ap._modal_running
    ap._modal_running = lambda ctx: True
    try:
        ap.refresh_cache(bpy.context, force=True)
    finally:
        ap._modal_running = saved
    assert ap._CACHE["rows"]["tilt"]["value"] == 10.0   # untouched
    ap.refresh_cache(bpy.context, force=True)
    assert ap._CACHE["rows"]["tilt"]["value"] == 30.0
    _object()


def test_value_setter_writes_selection():
    ap = _ap()
    _reset()
    obj = _track_mesh()
    ap.rebuild_mirror(bpy.context, force=True)
    _, bm = _edit()
    _select(bm, "POINT", [1, 2])
    ap.refresh_cache(bpy.context, force=True)
    item = bpy.context.window_manager.iops_attr.mirror["tilt"]
    item.value_float = 45.0
    assert item.value_float == 45.0
    assert ap._CACHE["rows"]["tilt"]["mixed"] == 1
    _object()
    assert _attr(obj.data, "tilt") == [0.0, 45.0, 45.0, 30.0, 40.0, 50.0]


def test_setter_pushes_one_undo_step():
    ap = _ap()
    _reset()
    obj = _track_mesh()
    bpy.ops.ed.undo_push(message="init")
    ap.rebuild_mirror(bpy.context, force=True)
    item = bpy.context.window_manager.iops_attr.mirror["tilt"]
    item.value_float = 44.0      # object mode: writes every vertex
    item.value_float = 45.0
    item.value_float = 46.0
    assert _attr(obj.data, "tilt") == [46.0] * 6
    assert ap._undo_push_now() > 0.0         # too early: re-armed
    ap._UNDO_DEADLINE = 0.0                  # 0.3 s have passed
    assert ap._undo_push_now() is None       # timer fires → one push
    bpy.ops.ed.undo()
    obj = bpy.data.objects["track"]
    assert _attr(obj.data, "tilt") == [0.0, 10.0, 20.0, 30.0, 40.0, 50.0]


def test_rename_through_mirror():
    ap = _ap()
    _reset()
    obj = _track_mesh()
    ap.rebuild_mirror(bpy.context, force=True)
    bpy.context.window_manager.iops_attr.mirror["tilt"].name = "lean"
    assert obj.data.attributes.get("lean") is not None
    assert obj.data.attributes.get("tilt") is None
    bpy.context.window_manager.iops_attr.mirror["marks"].name = "dots"
    assert obj.vertex_groups.get("dots") is not None
    # clash with an existing name gets a suffix
    bpy.context.window_manager.iops_attr.mirror["scale"].name = "lean"
    assert obj.data.attributes.get("lean.001") is not None


TESTS_TASK5 = [
    test_mirror_lists_rows_and_syncs_active,
    test_mirror_clamps_after_remove,
    test_cache_reads_active_vertex_and_mixed,
    test_cache_keeps_data_during_modal,
    test_value_setter_writes_selection,
    test_setter_pushes_one_undo_step,
    test_rename_through_mirror,
]


# ---------------------------------------------------------------------------
# Task 6: tools
# ---------------------------------------------------------------------------
def _select_all(bm):
    for v in bm.verts:
        v.select = True
    bm.select_flush(True)


def test_gradient_along_chain():
    _reset()
    obj = _track_mesh()
    _, bm = _edit()
    _select_all(bm)
    ret = bpy.ops.iops.attr_gradient(row_name="tilt", row_kind="ATTR",
                                     use_typed=True, value_start=0.0,
                                     value_end=100.0)
    assert ret == {"FINISHED"}
    _object()
    assert _attr(obj.data, "tilt") == [0.0, 20.0, 40.0, 60.0, 80.0, 100.0]
    # ends from the chain itself: reversed values stay monotonic
    _set_attr(obj.data, "tilt", [5.0, 0.0, 0.0, 0.0, 0.0, 15.0])
    _, bm = _edit()
    _select_all(bm)
    bpy.ops.iops.attr_gradient(row_name="tilt", row_kind="ATTR",
                               use_typed=False)
    _object()
    assert _attr(obj.data, "tilt") == [5.0, 7.0, 9.0, 11.0, 13.0, 15.0]


def test_gradient_rejects_branch():
    _reset()
    obj = _quad_mesh()
    obj.data.attributes.new("w", "FLOAT", "POINT")
    _, bm = _edit()
    _select_all(bm)
    ret = bpy.ops.iops.attr_gradient(row_name="w", row_kind="ATTR",
                                     use_typed=True, value_start=0.0,
                                     value_end=1.0)
    assert ret == {"CANCELLED"}
    _object()


def test_math_remap_on_selection():
    _reset()
    obj = _track_mesh()
    _, bm = _edit()
    _select(bm, "POINT", [0, 1, 2])
    bpy.ops.iops.attr_math(row_name="tilt", row_kind="ATTR", op="REMAP",
                           a=0.0, b=1.0)
    _object()
    assert _attr(obj.data, "tilt") == [0.0, 0.5, 1.0, 30.0, 40.0, 50.0]
    bpy.ops.iops.attr_math(row_name="scale", row_kind="ATTR", op="ADD",
                           a=1.0)
    assert _attr(obj.data, "scale") == [2.0, 3.0, 4.0, 5.0, 6.0, 7.0]


def test_smooth_path():
    _reset()
    obj = _track_mesh()
    _set_attr(obj.data, "tilt", [0.0, 10.0, 0.0, 10.0, 0.0, 10.0])
    _, bm = _edit()
    _select_all(bm)
    bpy.ops.iops.attr_smooth(row_name="tilt", row_kind="ATTR",
                             iterations=1, factor=1.0)
    _object()
    t = _attr(obj.data, "tilt")
    assert t[1] == 0.0 and t[0] == 10.0 and t[2] == 10.0


def test_randomize_seeded():
    _reset()
    obj = _track_mesh()
    bpy.ops.iops.attr_randomize(row_name="tilt", row_kind="ATTR", lo=0.0,
                                hi=1.0, seed=3)
    a = _attr(obj.data, "tilt")
    assert all(0.0 <= v <= 1.0 for v in a) and len(set(a)) > 1
    bpy.ops.iops.attr_randomize(row_name="tilt", row_kind="ATTR", lo=0.0,
                                hi=1.0, seed=3)
    assert _attr(obj.data, "tilt") == a


def test_copy_swap_and_coerce():
    _reset()
    obj = _track_mesh()
    me = obj.data
    bpy.ops.iops.attr_copy(row_name="tilt", row_kind="ATTR",
                           target_name="scale", swap=True)
    assert _attr(me, "tilt") == [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]
    assert _attr(me, "scale") == [0.0, 10.0, 20.0, 30.0, 40.0, 50.0]
    me.attributes.new("id", "INT", "POINT")
    bpy.ops.iops.attr_copy(row_name="tilt", row_kind="ATTR",
                           target_name="id")
    assert _attr(me, "id") == [1, 2, 3, 4, 5, 6]
    me.attributes.new("s", "STRING", "POINT")
    ret = bpy.ops.iops.attr_copy(row_name="tilt", row_kind="ATTR",
                                 target_name="s")
    assert ret == {"CANCELLED"}


def test_vgroup_roundtrip():
    _reset()
    obj = _track_mesh()
    me = obj.data
    bpy.ops.iops.attr_from_vgroup(group_name="marks")
    # "marks" itself is taken by the vertex group (shared namespace)
    assert me.attributes["marks.attr"].domain == "POINT"
    assert _attr(me, "marks.attr") == [0.5, 0.5, 0.5, 0.0, 0.0, 0.0]
    bpy.ops.iops.attr_to_vgroup(row_name="tilt", row_kind="ATTR",
                                group_name="w")
    assert [_weight(obj, i, "w") for i in range(6)] \
        == [0.0, 1.0, 1.0, 1.0, 1.0, 1.0]


def test_select_by_value():
    _reset()
    obj = _track_mesh()
    _, bm = _edit()
    _select(bm, "POINT", [])
    bpy.ops.iops.attr_select_by_value(row_name="tilt", row_kind="ATTR",
                                      op="GREATER", value=25.0)
    bm = bmesh.from_edit_mesh(obj.data)
    assert {v.index for v in bm.verts if v.select} == {3, 4, 5}
    _select(bm, "POINT", [1])
    bm.select_history.add(bm.verts[1])
    bpy.ops.iops.attr_select_by_value(row_name="tilt", row_kind="ATTR",
                                      op="ACTIVE", extend=False)
    bm = bmesh.from_edit_mesh(obj.data)
    assert {v.index for v in bm.verts if v.select} == {1}
    bpy.ops.iops.attr_select_by_value(row_name="tilt", row_kind="ATTR",
                                      op="RANGE", value=15.0, hi=35.0,
                                      extend=True)
    bm = bmesh.from_edit_mesh(obj.data)
    assert {v.index for v in bm.verts if v.select} == {1, 2, 3}
    _object()


def test_gradient_edge_domain_and_int_rounding():
    _reset()
    obj = _track_mesh()
    me = obj.data
    me.attributes.new("ew", "FLOAT", "EDGE")
    me.attributes.new("id", "INT", "POINT")
    _, bm = _edit()
    _select_all(bm)
    bpy.ops.iops.attr_gradient(row_name="ew", row_kind="ATTR",
                               use_typed=True, value_start=0.0,
                               value_end=1.0)
    bpy.ops.iops.attr_gradient(row_name="id", row_kind="ATTR",
                               use_typed=True, value_start=0.0,
                               value_end=10.0)
    _object()
    assert _attr(me, "ew") == [0.0, 0.25, 0.5, 0.75, 1.0]
    assert _attr(me, "id") == [0, 2, 4, 6, 8, 10]


def test_tool_supports_matrix():
    from InteractionOps.operators import mesh_attribute_editor as mae
    bool_row = _row("b", "BOOLEAN", "POINT")
    vec_row = _row("v", "FLOAT_VECTOR", "POINT")
    face_row = _row("f", "FLOAT", "FACE")
    str_row = _row("s", "STRING", "POINT")
    assert isinstance(mae.tool_supports("SMOOTH", bool_row), str)
    assert mae.tool_supports("MATH", vec_row) is None
    assert isinstance(mae.tool_supports("GRADIENT", face_row), str)
    assert isinstance(mae.tool_supports("MATH", str_row), str)
    assert mae.tool_supports("GRADIENT", _row("e", "FLOAT", "EDGE")) is None
    assert mae.tool_supports("SELECT", bool_row) is None


TESTS_TASK6 = [
    test_gradient_along_chain,
    test_gradient_rejects_branch,
    test_math_remap_on_selection,
    test_smooth_path,
    test_randomize_seeded,
    test_copy_swap_and_coerce,
    test_vgroup_roundtrip,
    test_select_by_value,
    test_gradient_edge_domain_and_int_rounding,
    test_tool_supports_matrix,
]


# ---------------------------------------------------------------------------
# Task 7: viewport preview (collection only; no GPU in background mode)
# ---------------------------------------------------------------------------
def _prefs():
    return bpy.context.preferences.addons[ADDON].preferences


def _modes(*on):
    """Switch the preview checkboxes: labels / greyscale / colour / heatmap."""
    st = bpy.context.window_manager.iops_attr
    for key in ("labels", "greyscale", "colour", "heatmap"):
        setattr(st, f"preview_{key}", key.upper() in on)


def _preview(name):
    """Preview `name`: the preview follows the active UIList row."""
    ap = _ap()
    ap.rebuild_mirror(bpy.context, force=True)
    st = bpy.context.window_manager.iops_attr
    st.preview = True
    _set_active_row(name)
    ap.sync_preview(bpy.context)


def test_preview_collect_values_and_range():
    ap = _ap()
    _reset()
    _track_mesh()
    ap.rebuild_mirror(bpy.context, force=True)
    st = bpy.context.window_manager.iops_attr
    _modes("HEATMAP")
    _preview("tilt")
    assert ap.preview_on() and ap.preview_row_name() == "tilt"
    ap.preview_collect(bpy.context)
    g = ap._PREVIEW["geom"]
    assert g["scalar"].tolist() == [0.0, 10.0, 20.0, 30.0, 40.0, 50.0]
    assert ap._PREVIEW["range"] == (0.0, 50.0)
    assert len(g["colors"]) == 6
    assert [round(c, 3) for c in g["colors"][0][:3]] == [0.0, 0.0, 1.0]
    assert [round(c, 3) for c in g["colors"][-1][:3]] == [1.0, 0.0, 0.0]
    assert g["fill"] is not None and g["fill"][0] == "POINTS"
    assert g["labels"] is None                      # heatmap: no text
    # toggle off → nothing drawn; back on with another row → switch
    st.preview = False
    assert not ap.preview_on() and ap._PREVIEW["geom"] is None
    _preview("marks")
    assert ap.preview_row_name() == "marks"
    ap.preview_collect(bpy.context)
    assert ap._PREVIEW["geom"]["scalar"].tolist() == [0.5, 0.5, 0.5, 0.0, 0.0,
                                                      0.0]
    ap.disable_preview()


def test_labels_skip_hidden():
    ap = _ap()
    _reset()
    obj = _track_mesh()
    ap.rebuild_mirror(bpy.context, force=True)
    st = bpy.context.window_manager.iops_attr
    _modes("LABELS")
    st.preview_decimals = 1
    _, bm = _edit()
    bm.verts[0].hide = True
    _select(bm, "POINT", [2])
    bmesh.update_edit_mesh(obj.data)
    _preview("tilt")
    ap.preview_collect(bpy.context)
    g = ap._PREVIEW["geom"]
    assert len(g["pos"]) == 5 and len(g["labels"]) == 5
    assert g["labels"][0] == "10.0"
    assert g["sel"].tolist() == [False, True, False, False, False]
    assert g["fill"] is None                        # labels: no fill batch
    ap.disable_preview()
    _object()


def test_preview_fill_geometry_faces_and_edges():
    ap = _ap()
    _reset()
    obj = _quad_mesh()
    me = obj.data
    me.attributes.new("fw", "FLOAT", "FACE")
    _set_attr(me, "fw", [0.0, 1.0])
    me.attributes.new("ew", "FLOAT", "EDGE")
    ap.rebuild_mirror(bpy.context, force=True)
    _modes("HEATMAP")
    _preview("fw")
    ap.preview_collect(bpy.context)
    kind, pos, col = ap._PREVIEW["geom"]["fill"]
    assert kind == "TRIS" and len(pos) == 12 and len(col) == 12   # 2 quads
    _preview("ew")
    ap.preview_collect(bpy.context)
    kind, pos, col = ap._PREVIEW["geom"]["fill"]
    assert kind == "LINES" and len(pos) == 14                      # 7 edges
    # corner domain in edit mode reads the bmesh path
    _edit()
    _preview("c")
    ap.preview_collect(bpy.context)
    kind, pos, col = ap._PREVIEW["geom"]["fill"]
    assert kind == "TRIS" and len(pos) == 12
    ap.disable_preview()
    _object()


def test_preview_disables_on_non_mesh():
    ap = _ap()
    _reset()
    _track_mesh()
    ap.rebuild_mirror(bpy.context, force=True)
    _preview("tilt")
    assert ap.preview_on()
    empty = bpy.data.objects.new("e", None)
    bpy.context.scene.collection.objects.link(empty)
    bpy.context.view_layer.objects.active = empty
    ap.preview_collect(bpy.context)
    assert not ap.preview_on()
    # attribute removed while previewing → off as well
    obj = bpy.data.objects["track"]
    bpy.context.view_layer.objects.active = obj
    _preview("tilt")
    obj.data.attributes.remove(obj.data.attributes["tilt"])
    ap.preview_collect(bpy.context)
    assert not ap.preview_on()


def test_preview_too_many_flag():
    ap = _ap()
    _reset()
    me = bpy.data.meshes.new("grid")
    me.from_pydata([(i * 0.1, 0.0, 0.0) for i in range(200)], [], [])
    me.attributes.new("w", "FLOAT", "POINT")
    obj = bpy.data.objects.new("grid", me)
    _link(obj)
    ap.rebuild_mirror(bpy.context, force=True)
    _modes("LABELS")
    old = _prefs().attr_preview_max_labels
    _prefs().attr_preview_max_labels = 100
    try:
        _preview("w")
        ap.preview_collect(bpy.context)
        assert ap._PREVIEW["too_many"] is True
        assert ap._PREVIEW["geom"]["labels"] is None
    finally:
        _prefs().attr_preview_max_labels = old
        ap.disable_preview()


def test_preview_follows_active_row_and_toggle():
    ap = _ap()
    _reset()
    _track_mesh()
    ap.rebuild_mirror(bpy.context, force=True)
    st = bpy.context.window_manager.iops_attr
    assert st.preview is True                   # on by default
    assert not hasattr(bpy.types, "IOPS_OT_attr_preview")
    _set_active_row("tilt")                     # index update → preview
    assert ap.preview_row_name() == "tilt"
    assert ap._PREVIEW["geom"] is not None
    _set_active_row("marks")
    assert ap.preview_row_name() == "marks"
    st.preview = False
    assert not ap.preview_on() and ap._PREVIEW["geom"] is None
    _set_active_row("tilt")
    assert not ap.preview_on()
    st.preview = True
    assert ap.preview_row_name() == "tilt"
    ap.sync_preview(bpy.context)                # no change → still tilt
    assert ap.preview_row_name() == "tilt"


def test_preview_modes_combine():
    ap = _ap()
    _reset()
    _track_mesh()
    st = bpy.context.window_manager.iops_attr
    for key in ("labels", "greyscale", "colour", "heatmap"):
        prop = st.bl_rna.properties[f"preview_{key}"]
        assert prop.type == "BOOLEAN"
    assert st.preview_labels and not st.preview_heatmap    # default
    _modes("LABELS", "HEATMAP")
    _preview("tilt")
    g = ap._PREVIEW["geom"]
    assert g["labels"] is not None and g["fill"] is not None
    assert g["fill_mode"] == "HEATMAP"
    _modes("HEATMAP")
    ap.preview_collect(bpy.context)
    assert ap._PREVIEW["geom"]["labels"] is None
    _modes("GREYSCALE")                     # float attr: no colour fills
    ap.preview_collect(bpy.context)
    assert ap._PREVIEW["geom"]["fill_mode"] is None
    _modes()
    ap.preview_collect(bpy.context)
    g = ap._PREVIEW["geom"]
    assert g["labels"] is None and g["fill"] is None
    _modes("LABELS")


def test_preview_text_size_in_pixels():
    from InteractionOps.ui.hud import text as hud_text
    from InteractionOps.ui.draw import get_theme
    st = bpy.context.window_manager.iops_attr
    prop = st.bl_rna.properties["preview_text_size"]
    assert prop.type == "INT" and prop.default == 13
    theme = get_theme(bpy.context)
    small = hud_text.measure("12.5", theme=theme, size_px=10)
    large = hud_text.measure("12.5", theme=theme, size_px=20)
    assert large[0] > small[0] * 1.5


TESTS_TASK7 = [
    test_preview_follows_active_row_and_toggle,
    test_preview_modes_combine,
    test_preview_text_size_in_pixels,
    test_preview_collect_values_and_range,
    test_labels_skip_hidden,
    test_preview_fill_geometry_faces_and_edges,
    test_preview_disables_on_non_mesh,
    test_preview_too_many_flag,
]


# ---------------------------------------------------------------------------
# Final review fixes
# ---------------------------------------------------------------------------
def _line_mesh(name, n):
    me = bpy.data.meshes.new(name)
    me.from_pydata([(i * 0.01, 0.0, 0.0) for i in range(n)],
                   [(i, i + 1) for i in range(n - 1)], [])
    me.attributes.new("w", "FLOAT", "POINT")
    _set_attr(me, "w", [i * 0.001 for i in range(n)])
    return _link(bpy.data.objects.new(name, me))


def test_dense_mesh_cache_and_select_are_fast():
    import time
    ap = _ap()
    _reset()
    _line_mesh("dense", 20000)
    ap.rebuild_mirror(bpy.context, force=True)
    _set_active_row("w")
    _, bm = _edit()
    _select_all(bm)
    t0 = time.perf_counter()
    ap.refresh_cache(bpy.context, force=True)
    dt_cache = time.perf_counter() - t0
    assert ap._CACHE["rows"]["w"]["selected"] == 20000
    t0 = time.perf_counter()
    bpy.ops.iops.attr_select_by_value(row_name="w", row_kind="ATTR",
                                      op="GREATER", value=10.0)
    dt_select = time.perf_counter() - t0
    t0 = time.perf_counter()
    _select_all(bm)
    bpy.ops.iops.attr_math(row_name="w", row_kind="ATTR", op="ADD", a=1.0)
    dt_math = time.perf_counter() - t0
    _object()
    assert dt_cache < 1.0 and dt_select < 1.0 and dt_math < 1.0, \
        (dt_cache, dt_select, dt_math)


def test_cache_refresh_is_dirty_driven():
    ap = _ap()
    _reset()
    _track_mesh()
    ap.rebuild_mirror(bpy.context, force=True)
    _set_active_row("tilt")
    _, bm = _edit()
    _select(bm, "POINT", [1])
    ap._CACHE["dirty"] = True
    ap.refresh_cache(bpy.context)
    assert ap._CACHE["rows"]["tilt"]["value"] == 10.0
    calls = []
    orig = ap.mae.bm_selected_indices

    def counting(*args, **kw):
        calls.append(1)
        return orig(*args, **kw)
    ap.mae.bm_selected_indices = counting
    try:
        ap.refresh_cache(bpy.context)           # clean: no bmesh walk
        assert calls == []
        ap._CACHE["dirty"] = True
        ap.refresh_cache(bpy.context)           # dirty: walks once per row
        assert calls
    finally:
        ap.mae.bm_selected_indices = orig
    _object()


def test_preview_empty_mesh_colour_attribute():
    ap = _ap()
    _reset()
    me = bpy.data.meshes.new("empty")
    me.attributes.new("col", "FLOAT_COLOR", "POINT")
    me.attributes.new("fcol", "BYTE_COLOR", "CORNER")
    _link(bpy.data.objects.new("empty", me))
    st = bpy.context.window_manager.iops_attr
    st.show_builtin = True                      # colour attrs are built-in
    try:
        for mode, name in (("COLOUR", "col"), ("GREYSCALE", "fcol"),
                           ("HEATMAP", "col"), ("LABELS", "col")):
            _modes(mode)
            _preview(name)
            ap.preview_collect(bpy.context)     # must not raise
            assert ap.preview_on()
            ap.disable_preview()
    finally:
        st.show_builtin = False


def test_object_mode_cache_shows_first_and_mixed():
    ap = _ap()
    _reset()
    obj = _track_mesh()
    ap.rebuild_mirror(bpy.context, force=True)
    _set_active_row("tilt")
    ap.refresh_cache(bpy.context, force=True)
    c = ap._CACHE["rows"]["tilt"]
    assert c["value"] == 0.0 and c["mixed"] == 6 and c["first"] is True
    assert c["index"] is None and c["selected"] == 6
    assert ap._index_text(c, False) == "all  (6)"
    item = bpy.context.window_manager.iops_attr.mirror["tilt"]
    assert item.value_float == 0.0
    _set_attr(obj.data, "tilt", [7.0] * 6)
    ap._CACHE["dirty"] = True
    ap.refresh_cache(bpy.context)
    assert item.value_float == 7.0 and ap._CACHE["rows"]["tilt"]["mixed"] == 1
    _set_active_row("marks")
    ap.refresh_cache(bpy.context, force=True)
    assert ap._CACHE["rows"]["marks"]["value"] == 0.5


def test_draw_requests_rebuild_through_timer():
    ap = _ap()
    _reset()
    obj = _track_mesh()
    ap.rebuild_mirror(bpy.context, force=True)
    assert _mirror_names() == ["scale", "tilt", "marks"]
    obj.data.attributes.new("extra", "FLOAT", "POINT")
    assert ap.mirror_stale(bpy.context) is True
    ap.request_rebuild()
    assert bpy.app.timers.is_registered(ap._rebuild_timer)
    assert ap._rebuild_timer() is None
    assert "extra" in _mirror_names()
    assert ap.mirror_stale(bpy.context) is False


def test_vgroup_math_object_mode_keeps_membership():
    _reset()
    obj = _track_mesh()
    bpy.ops.iops.attr_math(row_name="marks", row_kind="VGROUP",
                           op="MULTIPLY", a=2.0)
    assert [_weight(obj, i) for i in range(6)] \
        == [1.0, 1.0, 1.0, None, None, None]


def test_remove_builtin_cancels():
    _reset()
    obj = _track_mesh()
    ret = bpy.ops.iops.attr_remove(row_name="position", row_kind="ATTR")
    assert ret == {"CANCELLED"}
    assert "position" in obj.data.attributes


TESTS_TASK9 = [
    test_dense_mesh_cache_and_select_are_fast,
    test_cache_refresh_is_dirty_driven,
    test_preview_empty_mesh_colour_attribute,
    test_object_mode_cache_shows_first_and_mixed,
    test_draw_requests_rebuild_through_timer,
    test_vgroup_math_object_mode_keeps_membership,
    test_remove_builtin_cancels,
]


TESTS = [
    test_bm_write_selected_only,
    test_write_ignores_hidden,
    test_corner_write_all_loops,
    test_vgroup_write_adds_vertex,
    test_write_skips_meshes_without_attr,
    test_snapshot_in_edit_mode_reads_edit_state,
    test_mesh_write_all_object_mode,
]
TESTS += TESTS_TASK9
TESTS += TESTS_TASK7
TESTS += TESTS_TASK6
TESTS += TESTS_TASK5
TESTS += TESTS_TASK4


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
    print(f"OK {len(TESTS)} tests" if not failed
          else f"{len(TESTS) - failed}/{len(TESTS)} passed")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
