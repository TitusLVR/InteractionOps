"""Field Edge Slide (`iops.mesh_field_edge_slide`) through ``EXEC_DEFAULT`` (the redo / scripting path).
The modal path needs a window and is checked live.

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

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _isolation import require_isolated_user_resources  # noqa: E402

require_isolated_user_resources()

from test_falloff_ops import (bm_of, co_bytes, enable_addon, field_dict,  # noqa: E402
                              local_co, ramp, restore, set_linear, setup_scene,
                              world_co)

TOL = 1e-5


def select_edges(obj, pred):
    """Select exactly the edges whose two end points satisfy `pred(co)`."""
    bm = bm_of(obj)
    for v in bm.verts:
        v.select = False
    for e in bm.edges:
        e.select = False
    for f in bm.faces:
        f.select = False
    for e in bm.edges:
        if pred(e.verts[0].co) and pred(e.verts[1].co):
            e.select = True
            e.verts[0].select = e.verts[1].select = True
    bmesh.update_edit_mesh(obj.data)


def on_row(co):
    return abs(co.y) < 1e-6


def cylinder(name="Cyl", segments=16):
    """Open cylinder r = 1, z in [-1, 1], with a middle ring at z = 0."""
    if bpy.context.object and bpy.context.object.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o)
    bm = bmesh.new()
    ring = []
    for z in (-1.0, 0.0, 1.0):
        ring.append([bm.verts.new((math.cos(2 * math.pi * i / segments),
                                   math.sin(2 * math.pi * i / segments), z))
                     for i in range(segments)])
    for r0, r1 in zip(ring, ring[1:]):
        for i in range(segments):
            j = (i + 1) % segments
            bm.faces.new((r0[i], r0[j], r1[j], r1[i]))
    mesh = bpy.data.meshes.new(name)
    bm.to_mesh(mesh)
    bm.free()
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.mode_set(mode="EDIT")
    s = bpy.context.scene.IOPS.falloff
    s.fields.clear()
    s.use_custom_pivot = False
    return obj


# --- tests --------------------------------------------------------------------------------------------------------

def test_idname_resolves():
    bpy.ops.iops.mesh_field_edge_slide.get_rna_type()


def test_open_row_on_grid_ramps_along_field():
    a, b = setup_scene()
    select_edges(a, on_row)
    set_linear()
    w0 = world_co(a)
    r = bpy.ops.iops.mesh_field_edge_slide("EXEC_DEFAULT", factor=1.0)
    assert r == {"FINISHED"}, r
    w = world_co(a)
    row = np.abs(w0[:, 1]) < 1e-6
    dy = w[row, 1] - w0[row, 1]
    # one side for the whole row, rail length 0.2, scaled by the ramp
    assert np.all(dy >= -TOL) or np.all(dy <= TOL), dy
    assert np.allclose(np.abs(dy), 0.2 * ramp(w0[row, 0]), atol=TOL), np.abs(dy)
    assert np.allclose(w[row, 0], w0[row, 0], atol=TOL), "slid off the rails"
    assert np.allclose(w[~row], w0[~row], atol=TOL), "unselected verts moved"


def test_negative_factor_takes_the_other_side():
    a, b = setup_scene()
    select_edges(a, on_row)
    set_linear()
    snap = local_co(a)
    w0 = world_co(a)
    row = np.abs(w0[:, 1]) < 1e-6
    bpy.ops.iops.mesh_field_edge_slide("EXEC_DEFAULT", factor=1.0)
    pos = world_co(a)[row, 1]
    restore(a, snap)
    bpy.ops.iops.mesh_field_edge_slide("EXEC_DEFAULT", factor=-1.0)
    neg = world_co(a)[row, 1]
    assert np.allclose(pos, -neg, atol=TOL), (pos, neg)


def test_closed_ring_on_cylinder_slants():
    obj = cylinder()
    select_edges(obj, lambda co: abs(co.z) < 1e-6)
    set_linear()
    w0 = world_co(obj)
    assert bpy.ops.iops.mesh_field_edge_slide("EXEC_DEFAULT", factor=1.0) == {"FINISHED"}
    w = world_co(obj)
    ring = np.abs(w0[:, 2]) < 1e-6
    dz = w[ring, 2]
    assert np.all(dz >= -TOL) or np.all(dz <= TOL), dz
    assert np.allclose(np.abs(dz), ramp(w0[ring, 0]), atol=TOL), np.abs(dz)
    assert np.allclose(w[ring, :2], w0[ring, :2], atol=TOL)


def test_bidirectional_peak():
    obj = cylinder()
    select_edges(obj, lambda co: abs(co.z) < 1e-6)
    s = set_linear()
    s.type = "BIDIRECTIONAL"
    s.start, s.end = (-1.0, 0.0, 0.0), (1.0, 0.0, 0.0)
    w0 = world_co(obj)
    assert bpy.ops.iops.mesh_field_edge_slide("EXEC_DEFAULT", factor=1.0) == {"FINISHED"}
    ring = np.abs(w0[:, 2]) < 1e-6
    dz = np.abs(world_co(obj)[ring, 2])
    x = w0[ring, 0]
    assert dz[np.argmin(np.abs(x))] == max(dz), "peak not in the middle"
    assert np.all(dz[np.abs(np.abs(x) - 1.0) < 1e-6] < TOL), "ends moved"


def test_redo_from_same_mesh_is_identical_and_curve_applies():
    a, b = setup_scene()
    select_edges(a, on_row)
    set_linear()
    snap = local_co(a)
    w0 = world_co(a)
    row = np.abs(w0[:, 1]) < 1e-6
    call = dict(factor=1.0, stack=[field_dict(curve="SHARP")])
    assert bpy.ops.iops.mesh_field_edge_slide("EXEC_DEFAULT", **call) == {"FINISHED"}
    dy = np.abs(world_co(a)[row, 1] - w0[row, 1])
    assert np.allclose(dy, 0.2 * ramp(w0[row, 0]) ** 2, atol=TOL)
    first = co_bytes(a)
    restore(a, snap)
    assert bpy.ops.iops.mesh_field_edge_slide("EXEC_DEFAULT", **call) == {"FINISHED"}
    assert co_bytes(a) == first


def test_even_and_clamp():
    obj = cylinder()
    select_edges(obj, lambda co: abs(co.z) < 1e-6)
    s = bpy.context.scene.IOPS.falloff
    s.fields.clear()                       # no field: weight 1 everywhere
    snap = local_co(obj)
    ring = np.abs(world_co(obj)[:, 2]) < 1e-6
    bpy.ops.iops.mesh_field_edge_slide("EXEC_DEFAULT", factor=2.0)
    assert np.allclose(np.abs(world_co(obj)[ring, 2]), 1.0, atol=TOL), "clamp"
    restore(obj, snap)
    bpy.ops.iops.mesh_field_edge_slide("EXEC_DEFAULT", factor=2.0, use_clamp=False)
    assert np.allclose(np.abs(world_co(obj)[ring, 2]), 2.0, atol=TOL), "no clamp"
    restore(obj, snap)
    bpy.ops.iops.mesh_field_edge_slide("EXEC_DEFAULT", factor=0.5, use_even=True)
    assert np.allclose(np.abs(world_co(obj)[ring, 2]), 0.5, atol=TOL), "even"


def test_multi_object_shares_the_field():
    a, b = setup_scene()
    select_edges(a, on_row)
    select_edges(b, on_row)
    set_linear(start=(-1.0, 0.0, 0.0), end=(5.0, 0.0, 0.0))
    wa, wb = world_co(a), world_co(b)
    assert bpy.ops.iops.mesh_field_edge_slide("EXEC_DEFAULT", factor=1.0) == {"FINISHED"}
    for obj, w0 in ((a, wa), (b, wb)):
        moved = np.linalg.norm(world_co(obj) - w0, axis=1)
        assert moved.max() > 1e-3, f"{obj.name} did not slide"


def test_no_selected_edges_moves_nothing():
    a, b = setup_scene()
    bm = bm_of(a)
    for v in bm.verts:
        v.select = False
    for e in bm.edges:
        e.select = False
    bm.verts.ensure_lookup_table()
    bm.verts[0].select = True              # a lone vertex, no edge
    bmesh.update_edit_mesh(a.data)
    set_linear()
    before = co_bytes(a)
    assert bpy.ops.iops.mesh_field_edge_slide("EXEC_DEFAULT", factor=1.0) == {"FINISHED"}
    assert co_bytes(a) == before


def test_offset_wedge_from_zero_end():
    obj = cylinder()
    select_edges(obj, lambda co: abs(co.z) < 1e-6)
    set_linear()
    n0 = len(bm_of(obj).verts)
    assert bpy.ops.iops.mesh_field_offset_edge_slide("EXEC_DEFAULT", factor=0.5) == {"FINISHED"}
    bm = bm_of(obj)
    assert len(bm.verts) == n0 + 32, len(bm.verts)
    sel = [v for v in bm.verts if v.select]
    assert len(sel) == 32, "the two new loops are selected"
    co = np.array([v.co[:] for v in sel])
    # original ring still at z = 0; new loops at +-0.5 * ramp(x), one above, one below
    ring = [v for v in bm.verts if not v.select and abs(v.co.z) < 1e-6]
    assert len(ring) == 16, len(ring)
    assert np.allclose(np.abs(co[:, 2]), 0.5 * ramp(co[:, 0]), atol=TOL), np.abs(co[:, 2])
    up = co[:, 2] > 1e-6
    assert up.sum() == (co[:, 2] < -1e-6).sum(), "wedge not symmetric"


def test_offset_redo_is_identical_and_no_edges_cancels():
    obj = cylinder()
    select_edges(obj, lambda co: abs(co.z) < 1e-6)
    set_linear()
    bpy.ops.ed.undo_push(message="before")
    snap_bm = bm_of(obj).copy()
    assert bpy.ops.iops.mesh_field_offset_edge_slide("EXEC_DEFAULT", factor=1.0) == {"FINISHED"}
    first = co_bytes(obj)
    # put the mesh back and run again
    bpy.ops.object.mode_set(mode="OBJECT")
    snap_bm.to_mesh(obj.data)
    snap_bm.free()
    bpy.ops.object.mode_set(mode="EDIT")
    select_edges(obj, lambda co: abs(co.z) < 1e-6)
    assert bpy.ops.iops.mesh_field_offset_edge_slide("EXEC_DEFAULT", factor=1.0) == {"FINISHED"}
    assert co_bytes(obj) == first
    select_edges(obj, lambda co: False)
    assert bpy.ops.iops.mesh_field_offset_edge_slide("EXEC_DEFAULT", factor=1.0) == {"CANCELLED"}


TESTS = [
    test_idname_resolves,
    test_open_row_on_grid_ramps_along_field,
    test_negative_factor_takes_the_other_side,
    test_closed_ring_on_cylinder_slants,
    test_bidirectional_peak,
    test_redo_from_same_mesh_is_identical_and_curve_applies,
    test_even_and_clamp,
    test_multi_object_shares_the_field,
    test_no_selected_edges_moves_nothing,
    test_offset_wedge_from_zero_end,
    test_offset_redo_is_identical_and_no_edges_cancels,
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
