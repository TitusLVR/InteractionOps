"""Headless test of the Cursor Bisect "Selection Bounds" snap source on real
BMesh data: world points of the cut set, the oriented box in a rotated cut
frame, side divisions / inset offsets / fill positions, the degenerate flat
box, and the operator's cut-set point cache across Edit Mode objects. Run
from the repo root via:

    blender --background --factory-startup --python-exit-code 1 --python tests/blender/test_cursor_bisect_bounds.py

No viewport is needed. The operator methods run on a plain stand-in object
that borrows them from the operator class (an Operator instance can only be
made by Blender during invoke).

Not collected by pytest (tests/conftest.py ignores tests/blender).
"""
import math
import os
import sys
import traceback

import bmesh
import bpy
from mathutils import Matrix, Quaternion, Vector

ADDON = "InteractionOps"

mcb = None
core = None


def enable_addon():
    global mcb, core
    repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    repo_parent = os.path.dirname(repo_root)
    if repo_parent not in sys.path:
        sys.path.insert(0, repo_parent)
    bpy.ops.preferences.addon_enable(module=ADDON)
    assert ADDON in bpy.context.preferences.addons, "addon not enabled"
    import InteractionOps
    loaded = os.path.dirname(os.path.abspath(InteractionOps.__file__))
    assert os.path.samefile(loaded, repo_root), f"addon loaded from {loaded}"
    from InteractionOps.operators import mesh_cursor_bisect as _mcb
    from InteractionOps.utils import cursor_bisect_core as _core
    mcb = _mcb
    core = _core


# --- helpers ---------------------------------------------------------------------

def _grid(nx, ny):
    """Flat quad grid in XY, 1 m cells. Face index = y * nx + x."""
    bm = bmesh.new()
    verts = [[bm.verts.new((x, y, 0.0)) for x in range(nx + 1)] for y in range(ny + 1)]
    for y in range(ny):
        for x in range(nx):
            bm.faces.new((verts[y][x], verts[y][x + 1], verts[y + 1][x + 1], verts[y + 1][x]))
    bm.faces.ensure_lookup_table()
    bm.normal_update()
    return bm


def _close(a, b, eps=1e-6):
    return all(abs(x - y) <= eps for x, y in zip(a, b))


def _proj(p, axis):
    return p[0] * axis[0] + p[1] * axis[1] + p[2] * axis[2]


ROT30 = Quaternion((0.0, 0.0, 1.0), math.radians(30.0))


def clear_scene():
    if bpy.context.object and bpy.context.object.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    for coll in (bpy.data.objects, bpy.data.meshes):
        for block in list(coll):
            coll.remove(block)


def grid_object(name, nx, ny, matrix=None, selected_faces=()):
    me = bpy.data.meshes.new(name)
    bm = _grid(nx, ny)
    for i in selected_faces:
        bm.faces[i].select_set(True)
    bm.to_mesh(me)
    bm.free()
    obj = bpy.data.objects.new(name, me)
    if matrix is not None:
        obj.matrix_world = matrix
    bpy.context.scene.collection.objects.link(obj)
    return obj


def enter_edit(*objs):
    bpy.ops.object.select_all(action='DESELECT')
    for o in objs:
        o.select_set(True)
    bpy.context.view_layer.objects.active = objs[0]
    bpy.ops.object.mode_set(mode='EDIT')
    bpy.context.view_layer.update()


def stand_in(**state):
    """Plain object carrying the operator's methods and default state."""
    op_cls = mcb.IOPS_OT_Mesh_Cursor_Bisect

    class Op:
        pass
    for k, v in vars(op_cls).items():
        if not k.startswith('__'):
            setattr(Op, k, v)
    op = Op()
    op.report = lambda *a, **k: None
    defaults = {
        'snap_source': 'BOUNDS', 'hold_snap_points': False, 'lock_orientation': True,
        'locked_rotation': ROT30, 'normal_axis': 'X', 'edge_subdivisions': 0,
        'inset_active': False, 'inset_distance_bu': 0.1, 'delimit_active': False,
        'delimit_type': 'ISLAND', 'hover_valid': False, 'hit_obj': None,
        'hit_face_index': -1, '_mesh_version': 1, '_island_cache': None,
        '_bounds_layout': None, '_bounds_layout_key': None,
        '_bounds_points_cache': None, 'snapping_enabled': True,
    }
    defaults.update(state)
    for k, v in defaults.items():
        setattr(op, k, v)
    return op


# --- tests: module-level helpers ---------------------------------------------------

def test_cut_set_world_points_of_sub_grid_under_object_transform():
    bm = _grid(4, 3)
    mw = Matrix.Translation((10.0, 0.0, 2.0)) @ Matrix.Rotation(math.radians(90.0), 4, 'Z')
    pts = mcb.cut_set_world_points(bm, mw, {0, 1, 5, 99})  # 99: out of range, skipped
    # faces 0, 1 (row 0, x 0..2) and 5 (row 1, x 1..2): 3 + 3 + 2 unique verts
    assert len(pts) == 8, len(pts)
    expected = {(10.0 - y, x, 2.0) for (x, y) in
                ((0, 0), (1, 0), (2, 0), (0, 1), (1, 1), (2, 1), (1, 2), (2, 2))}
    for p in pts:
        assert any(_close(p, e) for e in expected), p


def test_rotation_axes_are_matrix_columns():
    axes = mcb.rotation_axes(ROT30)
    m = ROT30.to_matrix()
    for i in range(3):
        assert _close(axes[i], tuple(m.col[i])), (i, axes[i])
    assert _close(axes[0], (math.cos(math.radians(30)), math.sin(math.radians(30)), 0.0))


def test_numpy_and_core_extents_agree():
    import numpy as np
    bm = _grid(3, 2)
    pts = mcb.cut_set_world_points(bm, Matrix.Identity(4), set(range(6)))
    axes = mcb.rotation_axes(ROT30)
    a = mcb.points_extents(np.asarray(pts, dtype=np.float64), axes)
    b = core.oriented_extents(pts, axes)
    assert _close(a[0], b[0]) and _close(a[1], b[1]), (a, b)
    assert mcb.points_extents(np.zeros((0, 3)), axes) is None


def test_sub_grid_bounds_in_rotated_frame():
    bm = _grid(4, 4)
    # 2x2 block of faces in the middle: x, y in [1, 3]
    faces = {5, 6, 9, 10}
    pts = mcb.cut_set_world_points(bm, Matrix.Identity(4), faces)
    lay = mcb.selection_bounds_layout(pts, ROT30, 'X', 2, 0.0, False)
    ax = lay['axes'][0]
    projs = [_proj(p, ax) for p in pts]
    assert abs(lay['length'] - (max(projs) - min(projs))) < 1e-6
    assert len(lay['wire']) == 4                         # flat in Z: a rectangle
    assert len(lay['divisions']) == 2 * 2                # 2 divisions on 2 X-parallel edges
    pos = sorted(_proj(p, ax) for p in lay['positions'])
    lo = min(projs)
    assert _close(pos, (lo + lay['length'] / 3, lo + 2 * lay['length'] / 3)), pos
    # every division lies on the box: its projection on the other axes is lo or hi
    ay = lay['axes'][1]
    ylo, yhi = lay['lo'][1], lay['hi'][1]
    for p in lay['divisions']:
        d = _proj(p, ay)
        assert abs(d - ylo) < 1e-6 or abs(d - yhi) < 1e-6, d


def test_flat_box_wire_has_no_zero_length_or_duplicate_edges():
    bm = _grid(3, 2)
    pts = mcb.cut_set_world_points(bm, Matrix.Identity(4), set(range(6)))
    lay = mcb.selection_bounds_layout(pts, Quaternion(), 'Y', 0, 0.0, False)
    wire = lay['wire']
    assert len(wire) == 4, len(wire)
    assert all((Vector(a) - Vector(b)).length > 1e-6 for a, b in wire)
    keys = {tuple(sorted((tuple(round(c, 6) for c in a), tuple(round(c, 6) for c in b))))
            for a, b in wire}
    assert len(keys) == 4
    assert lay['length'] == 2.0
    assert sorted(lay['divisions']) == [(0.0, 1.0, 0.0), (3.0, 1.0, 0.0)]
    # cut axis Z has zero extent on a flat grid: no points, wire still drawn
    lay = mcb.selection_bounds_layout(pts, Quaternion(), 'Z', 3, 0.5, True)
    assert lay['divisions'] == [] and lay['insets'] == [] and lay['positions'] == []
    assert len(lay['wire']) == 4


def test_inset_skip_rules_on_bounds():
    bm = _grid(4, 1)
    pts = mcb.cut_set_world_points(bm, Matrix.Identity(4), set(range(4)))
    ident = Quaternion()
    lay = mcb.selection_bounds_layout(pts, ident, 'X', 0, 1.0, True)
    assert lay['divisions'] == []                        # inset replaces the midpoint
    assert sorted(p[0] for p in lay['positions']) == [1.0, 3.0]
    assert len(lay['insets']) == 4
    lay = mcb.selection_bounds_layout(pts, ident, 'X', 0, 2.0, True)
    assert [p[0] for p in lay['positions']] == [2.0]     # both ends coincide
    lay = mcb.selection_bounds_layout(pts, ident, 'X', 0, 4.0, True)
    assert lay['insets'] == [] and [p[0] for p in lay['positions']] == [2.0]
    lay = mcb.selection_bounds_layout(pts, ident, 'X', 0, 0.0, True)
    assert lay['insets'] == [] and [p[0] for p in lay['positions']] == [2.0]
    lay = mcb.selection_bounds_layout(pts, ident, 'X', 1, 1.0, True)
    assert sorted(p[0] for p in lay['positions']) == [1.0, 2.0, 3.0]


# --- tests: operator cache across Edit Mode objects ----------------------------------

def test_bounds_span_every_edit_object_and_cache_follows_mesh_version():
    clear_scene()
    a = grid_object("BoundsA", 2, 2, selected_faces=(0,))           # only face 0: [0,1]^2
    b = grid_object("BoundsB", 1, 1, matrix=Matrix.Translation((5.0, 3.0, 1.0)))  # nothing selected
    enter_edit(a, b)
    op = stand_in(locked_rotation=Quaternion(), edge_subdivisions=1)
    ctx = bpy.context
    lay = op._bounds_layout_for(ctx)
    assert lay is not None
    assert _close(lay['lo'], (0.0, 0.0, 0.0)) and _close(lay['hi'], (6.0, 4.0, 1.0)), (lay['lo'], lay['hi'])
    assert len(lay['wire']) == 12
    assert len(lay['divisions']) == 4 and len(op.get_fill_cut_positions(ctx)) == 1
    # Same inputs: layout and point cache are reused, not rebuilt.
    cache = op._bounds_points_cache
    assert op._bounds_layout_for(ctx) is lay and op._bounds_points_cache is cache
    # A rotation change re-projects the cached points only.
    op.locked_rotation = ROT30
    lay30 = op._bounds_layout_for(ctx)
    assert lay30 is not lay and op._bounds_points_cache is cache
    # Selection change (bumps _mesh_version in the modal): point cache rebuilt.
    bm = bmesh.from_edit_mesh(a.data)
    bm.faces.ensure_lookup_table()
    bm.faces[3].select = True
    op._mesh_version += 1
    op.locked_rotation = Quaternion()
    lay2 = op._bounds_layout_for(ctx)
    assert op._bounds_points_cache is not cache
    assert _close(lay2['lo'], (0.0, 0.0, 0.0)) and _close(lay2['hi'], (6.0, 4.0, 1.0))
    # Hold freezes the layout whatever changes.
    op.hold_snap_points = True
    op.edge_subdivisions = 5
    assert op._bounds_layout_for(ctx) is lay2
    op.hold_snap_points = False
    assert len(op._bounds_layout_for(ctx)['positions']) == 5


def test_bounds_follow_delimiter_island():
    clear_scene()
    a = grid_object("IslandA", 3, 1)
    b = grid_object("IslandB", 1, 1, matrix=Matrix.Translation((10.0, 0.0, 0.0)))
    enter_edit(a, b)
    bm = bmesh.from_edit_mesh(a.data)
    bm.faces.ensure_lookup_table()
    seam = [e for e in bm.faces[1].edges if bm.faces[2] in e.link_faces][0]
    seam.seam = True
    op = stand_in(locked_rotation=Quaternion(), delimit_active=True, delimit_type='SEAM',
                  hover_valid=True, hit_obj=a, hit_face_index=0)
    lay = op._bounds_layout_for(bpy.context)
    assert _close(lay['lo'], (0.0, 0.0, 0.0)) and _close(lay['hi'], (2.0, 1.0, 0.0)), (lay['lo'], lay['hi'])
    cache = op._bounds_points_cache
    op.hit_face_index = 1                               # same island: no rebuild
    op._bounds_layout_for(bpy.context)
    assert op._bounds_points_cache is cache
    op.hit_face_index = 2                               # other side of the seam
    lay = op._bounds_layout_for(bpy.context)
    assert op._bounds_points_cache is not cache
    assert _close(lay['lo'], (2.0, 0.0, 0.0)) and _close(lay['hi'], (3.0, 1.0, 0.0)), (lay['lo'], lay['hi'])


def test_bounds_split_distances_and_snap_points_local_to_hit_object():
    clear_scene()
    a = grid_object("SplitA", 4, 1, matrix=Matrix.Translation((0.0, 0.0, 2.0)))
    enter_edit(a)
    op = stand_in(locked_rotation=Quaternion(), hit_obj=a, hit_face_index=0, hover_valid=True)
    ctx = bpy.context
    ctx.scene.cursor.location = (1.0, 0.5, 2.0)
    ctx.scene.unit_settings.system = 'NONE'
    op.find_closest_snap_point = lambda *a, **k: None   # needs a 3D viewport
    op._update_bounds_snapping(ctx, ctx.scene.cursor.location)
    assert [k for k, _ in op.snap_points] == ['bounds', 'bounds']
    world = sorted(tuple(a.matrix_world @ p) for _, p in op.snap_points)
    assert _close(world[0], (2.0, 0.0, 2.0)) and _close(world[1], (2.0, 1.0, 2.0)), world
    info = op._bounds_split_distances(ctx)
    assert info['label'] == 'Bounds' and abs(info['total'] - 4.0) < 1e-6 and abs(info['split'] - 1.0) < 1e-6, info
    op.snapping_enabled = False
    op._update_bounds_snapping(ctx, ctx.scene.cursor.location)
    assert op.snap_points == [] and op._bounds_layout is not None


TESTS = [
    test_cut_set_world_points_of_sub_grid_under_object_transform,
    test_rotation_axes_are_matrix_columns,
    test_numpy_and_core_extents_agree,
    test_sub_grid_bounds_in_rotated_frame,
    test_flat_box_wire_has_no_zero_length_or_duplicate_edges,
    test_inset_skip_rules_on_bounds,
    test_bounds_span_every_edit_object_and_cache_follows_mesh_version,
    test_bounds_follow_delimiter_island,
    test_bounds_split_distances_and_snap_points_local_to_hit_object,
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
