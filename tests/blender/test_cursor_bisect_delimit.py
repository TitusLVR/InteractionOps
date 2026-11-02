"""Headless test of the Cursor Bisect delimiter on real BMesh data:
`delimited_faces` must stop at seam / sharp / material / UV-island /
normal-angle boundaries and never leave the candidate set. Run from the
repo root via:

    blender --background --factory-startup --python-exit-code 1 --python tests/blender/test_cursor_bisect_delimit.py

No scene or viewport is needed: every test builds its own bmesh.

Not collected by pytest (tests/conftest.py ignores tests/blender).
"""
import math
import os
import sys
import traceback

import bmesh
import bpy
from mathutils import Matrix, Vector

ADDON = "InteractionOps"

mcb = None


def enable_addon():
    global mcb
    repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    repo_parent = os.path.dirname(repo_root)
    if repo_parent not in sys.path:
        sys.path.insert(0, repo_parent)
    bpy.ops.preferences.addon_enable(module=ADDON)
    assert ADDON in bpy.context.preferences.addons, "addon not enabled"
    import InteractionOps
    loaded = os.path.dirname(os.path.abspath(InteractionOps.__file__))
    assert os.path.samefile(loaded, repo_root), "addon loaded from %s" % loaded
    from InteractionOps.operators import mesh_cursor_bisect as _mcb
    mcb = _mcb


# --- mesh builders ---------------------------------------------------------------

def _grid(nx, ny):
    """Flat quad grid in XY, 1 m cells. Face index = y * nx + x."""
    bm = bmesh.new()
    verts = [[bm.verts.new((x, y, 0.0)) for x in range(nx + 1)] for y in range(ny + 1)]
    for y in range(ny):
        for x in range(nx):
            bm.faces.new((verts[y][x], verts[y][x + 1], verts[y + 1][x + 1], verts[y + 1][x]))
    bm.faces.ensure_lookup_table()
    bm.edges.ensure_lookup_table()
    bm.normal_update()
    return bm


def _two_islands():
    bm = bmesh.new()
    a = [bm.verts.new(c) for c in ((0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0))]
    b = [bm.verts.new(c) for c in ((3, 0, 0), (4, 0, 0), (4, 1, 0), (3, 1, 0))]
    bm.faces.new(a)
    bm.faces.new(b)
    bm.faces.ensure_lookup_table()
    bm.normal_update()
    return bm


def _folded_strip(fold_deg):
    """Three quads in a row; the third is folded up about its shared edge."""
    bm = bmesh.new()
    rot = Matrix.Rotation(math.radians(fold_deg), 3, 'Y')
    v = [bm.verts.new((x, y, 0.0)) for x in range(3) for y in range(2)]
    # columns x=0..2 -> verts v[2x], v[2x+1]
    far = [Vector((2.0, 0.0, 0.0)) + rot @ Vector((1.0, 0.0, 0.0)),
           Vector((2.0, 1.0, 0.0)) + rot @ Vector((1.0, 0.0, 0.0))]
    f = [bm.verts.new(far[0]), bm.verts.new(far[1])]
    bm.faces.new((v[0], v[2], v[3], v[1]))
    bm.faces.new((v[2], v[4], v[5], v[3]))
    bm.faces.new((v[4], f[0], f[1], v[5]))
    bm.faces.ensure_lookup_table()
    bm.normal_update()
    return bm


def _shared_edge(bm, i, j):
    return [e for e in bm.faces[i].edges if bm.faces[j] in e.link_faces][0]


# --- tests -----------------------------------------------------------------------

def test_island_reaches_connected_only():
    bm = _two_islands()
    assert mcb.delimited_faces(bm, 0, {0, 1}, 'ISLAND', 30.0) == {0}


def test_seam_stops_walk():
    bm = _grid(3, 1)
    _shared_edge(bm, 1, 2).seam = True
    assert mcb.delimited_faces(bm, 0, {0, 1, 2}, 'SEAM', 30.0) == {0, 1}
    assert mcb.delimited_faces(bm, 0, {0, 1, 2}, 'ISLAND', 30.0) == {0, 1, 2}


def test_sharp_stops_walk():
    bm = _grid(3, 1)
    _shared_edge(bm, 0, 1).smooth = False
    assert mcb.delimited_faces(bm, 2, {0, 1, 2}, 'SHARP', 30.0) == {1, 2}


def test_material_stops_walk():
    bm = _grid(3, 1)
    bm.faces[2].material_index = 1
    assert mcb.delimited_faces(bm, 0, {0, 1, 2}, 'MATERIAL', 30.0) == {0, 1}


def test_normal_angle_stops_walk():
    bm = _folded_strip(fold_deg=90.0)
    assert mcb.delimited_faces(bm, 0, {0, 1, 2}, 'NORMAL', 30.0) == {0, 1}
    assert mcb.delimited_faces(bm, 0, {0, 1, 2}, 'NORMAL', 120.0) == {0, 1, 2}


def test_uv_island_boundary_stops_walk():
    bm = _grid(2, 1)
    uv = bm.loops.layers.uv.new("UVMap")
    for f in bm.faces:
        for l in f.loops:
            l[uv].uv = (l.vert.co.x, l.vert.co.y)
    for l in bm.faces[1].loops:
        l[uv].uv = (l[uv].uv.x + 5.0, l[uv].uv.y)   # face 1 moved to its own UV island
    assert mcb.delimited_faces(bm, 0, {0, 1}, 'UV', 30.0) == {0}


def test_uv_without_layer_is_island():
    bm = _grid(2, 1)
    assert mcb.delimited_faces(bm, 0, {0, 1}, 'UV', 30.0) == {0, 1}


def test_candidates_filter_walk():
    bm = _grid(3, 1)
    assert mcb.delimited_faces(bm, 1, {1, 2}, 'ISLAND', 30.0) == {1, 2}
    assert mcb.delimited_faces(bm, 0, {1, 2}, 'ISLAND', 30.0) == set()


def test_delimited_faces_out_of_range_is_empty():
    bm = _grid(2, 1)
    assert mcb.delimited_faces(bm, 7, {0, 1}, 'ISLAND', 30.0) == set()
    assert mcb.delimited_faces(bm, -1, {0, 1}, 'ISLAND', 30.0) == set()


def test_delimited_faces_hidden_start_is_empty():
    bm = _grid(2, 1)
    bm.faces[0].hide = True
    vis = lambda f: not f.hide
    assert mcb.delimited_faces(bm, 0, {0, 1}, 'ISLAND', 30.0, is_visible=vis) == set()
    assert mcb.delimited_faces(bm, 1, {0, 1}, 'ISLAND', 30.0, is_visible=vis) == {1}


def test_stamp_cut_layer_survives_bisect():
    bm = _grid(3, 1)
    layer = mcb.stamp_cut_layer(bm, {0, 1})
    geom = [f for f in bm.faces if f[layer] == 1]
    geom = list({v for f in geom for v in f.verts} | {e for f in geom for e in f.edges} | set(geom))
    bmesh.ops.bisect_plane(bm, geom=geom, plane_co=(0.5, 0.0, 0.0), plane_no=(1.0, 0.0, 0.0), dist=1e-4)
    bm.faces.ensure_lookup_table()
    stamped = [f for f in bm.faces if f[layer] == 1]
    untouched = [f for f in bm.faces if f[layer] == 0]
    assert len(bm.faces) == 4, len(bm.faces)
    assert len(stamped) == 3 and all(max(v.co.x for v in f.verts) <= 2.0 + 1e-6 for f in stamped)
    assert len(untouched) == 1 and len(untouched[0].verts) == 4


def test_world_align_rotations_for_z():
    for world_axis, expected in (('X', (1, 0, 0)), ('Y', (0, 1, 0)), ('Z', (0, 0, 1))):
        m = mcb.world_align_rotation('Z', world_axis)
        got = m @ Vector((0.0, 0.0, 1.0))
        assert (got - Vector(expected)).length < 1e-6, (world_axis, got)
    # X / Y normal axes keep their existing mapping: the cursor's chosen axis
    # lands on the world axis up to sign (a plane normal's sign is irrelevant).
    def along(m, src, dst):
        return abs(abs((m @ Vector(src)).dot(Vector(dst))) - 1.0) < 1e-6
    assert along(mcb.world_align_rotation('X', 'Y'), (1, 0, 0), (0, 1, 0))
    assert along(mcb.world_align_rotation('Y', 'Z'), (0, 1, 0), (0, 0, 1))


def _cube():
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=2.0)
    bm.faces.ensure_lookup_table()
    bm.normal_update()
    return bm


def test_face_straddles_plane():
    bm = _cube()
    eps = 1e-4
    top = Vector((0, 0, 1)); up = Vector((0, 0, 1))
    # plane through the top face: nothing straddles (top lies in it, sides only touch it)
    assert not any(mcb.face_straddles_plane(f, top, up, eps) for f in bm.faces)
    # plane through the middle: the four side faces straddle, top / bottom do not
    mid = Vector((0, 0, 0))
    straddling = [f for f in bm.faces if mcb.face_straddles_plane(f, mid, up, eps)]
    assert len(straddling) == 4 and all(abs(f.normal.z) < 1e-6 for f in straddling)


def _two_islands_touching():
    """Two quads whose shared-position vertices are NOT connected (x = 1)."""
    bm = bmesh.new()
    a = [bm.verts.new(c) for c in ((0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0))]
    b = [bm.verts.new(c) for c in ((1, 0, 0), (2, 0, 0), (2, 1, 0), (1, 1, 0))]
    bm.faces.new(a); bm.faces.new(b)
    bm.faces.ensure_lookup_table()
    return bm


def test_merge_doubles_restricted_to_cut_faces_keeps_islands_apart():
    bm = _two_islands_touching()
    layer = mcb.stamp_cut_layer(bm, {0})
    mcb.merge_cut_doubles(bm, layer, 0.005, restrict=True)
    assert len(bm.verts) == 8, len(bm.verts)
    bm = _two_islands_touching()
    layer = mcb.stamp_cut_layer(bm, {0})
    mcb.merge_cut_doubles(bm, layer, 0.005, restrict=False)
    assert len(bm.verts) == 6, len(bm.verts)


def _cut_once(bm, x, vis):
    """One execute()-style cut: snapshot, stamp, bisect, restore, clean up."""
    OP = mcb.IOPS_OT_Mesh_Cursor_Bisect
    mcb.drop_scratch_layers(bm)
    sel = OP._snapshot_face_selection(bm, vis)
    cut = mcb.stamp_cut_layer(bm, {f.index for f in bm.faces})
    assert sel.name == mcb.SEL_LAYER_NAME and cut.name == mcb.CUT_LAYER_NAME, (sel.name, cut.name)
    geom = [f for f in bm.faces if f[cut] == 1]
    geom = list({v for f in geom for v in f.verts} | {e for f in geom for e in f.edges} | set(geom))
    bmesh.ops.bisect_plane(bm, geom=geom, plane_co=(x, 0.0, 0.0), plane_no=(1.0, 0.0, 0.0), dist=1e-4)
    bm.faces.ensure_lookup_table()
    OP._restore_face_selection(bm, sel, vis)
    mcb.drop_scratch_layers(bm)


def test_scratch_layers_cleared_and_selection_kept_across_cuts():
    """Regression: the second scratch layer used to be removed through a handle
    whose index had already shifted, so it stayed on the mesh and the next cut
    aliased both handles onto it (RuntimeError 'layer has become invalid')."""
    bm = _grid(3, 1)
    vis = lambda f: not f.hide
    bm.faces[0].select = True
    for x in (0.5, 1.5, 2.5):
        _cut_once(bm, x, vis)
        assert bm.faces.layers.int.keys() == [], bm.faces.layers.int.keys()
    selected = [f for f in bm.faces if f.select]
    assert len(bm.faces) == 6, len(bm.faces)
    assert len(selected) == 2 and all(max(v.co.x for v in f.verts) <= 1.0 + 1e-6 for f in selected)


def test_stale_scratch_layer_does_not_alias_handles():
    bm = _grid(2, 1)
    vis = lambda f: not f.hide
    bm.faces.layers.int.new(mcb.CUT_LAYER_NAME)  # left behind by a failed run
    bm.faces[1].select = True
    _cut_once(bm, 0.5, vis)
    assert bm.faces.layers.int.keys() == []
    selected = [f for f in bm.faces if f.select]
    assert len(selected) == 1 and min(v.co.x for v in selected[0].verts) >= 1.0 - 1e-6


TESTS = [
    test_face_straddles_plane,
    test_merge_doubles_restricted_to_cut_faces_keeps_islands_apart,
    test_world_align_rotations_for_z,
    test_stamp_cut_layer_survives_bisect,
    test_scratch_layers_cleared_and_selection_kept_across_cuts,
    test_stale_scratch_layer_does_not_alias_handles,
    test_island_reaches_connected_only,
    test_seam_stops_walk,
    test_sharp_stops_walk,
    test_material_stops_walk,
    test_normal_angle_stops_walk,
    test_uv_island_boundary_stops_walk,
    test_uv_without_layer_is_island,
    test_candidates_filter_walk,
    test_delimited_faces_out_of_range_is_empty,
    test_delimited_faces_hidden_start_is_empty,
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
    print("%d/%d passed" % (len(TESTS) - failed, len(TESTS)))
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
