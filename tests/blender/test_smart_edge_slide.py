"""Headless tests of Smart Edge Slide on real BMesh data: the bridge (chains
from the selection, band sides, wedge faces and step lids) and the operator's
execute(). Run from the repo root via:

    blender --background --factory-startup --python-exit-code 1 --python tests/blender/test_smart_edge_slide.py

No viewport is needed: the bridge tests build their own bmesh, the execute()
tests put each mesh in an object of its own and run the operator in Edit Mode.

Not collected by pytest (tests/conftest.py ignores tests/blender).
"""
import dataclasses
import math
import os
import sys
import traceback
from types import SimpleNamespace

import bmesh
import bpy
from mathutils import Matrix, Vector
from mathutils.bvhtree import BVHTree

ADDON = "InteractionOps"

bridge = None
core = None
operator = None
stripe_bridge = None


def enable_addon():
    global bridge, core, operator, stripe_bridge
    repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    repo_parent = os.path.dirname(repo_root)
    if repo_parent not in sys.path:
        sys.path.insert(0, repo_parent)
    bpy.ops.preferences.addon_enable(module=ADDON)
    assert ADDON in bpy.context.preferences.addons, "addon not enabled"
    import InteractionOps
    loaded = os.path.dirname(os.path.abspath(InteractionOps.__file__))
    assert os.path.samefile(loaded, repo_root), f"addon loaded from {loaded}"
    from InteractionOps.operators import mesh_smart_edge_slide_bridge as _bridge
    from InteractionOps.operators import uv_stripe_bridge as _stripe_bridge
    from InteractionOps.operators.mesh_smart_edge_slide import IOPS_OT_smart_edge_slide
    from InteractionOps.utils import smart_edge_slide_core as _core
    bridge = _bridge
    core = _core
    operator = IOPS_OT_smart_edge_slide
    stripe_bridge = _stripe_bridge


# --- mesh builders ---------------------------------------------------------------
# Chain vertices come first, in chain order. Faces on the side the tests cut run
# each chain edge in chain order, so that side is +1.

def _mesh(points, faces):
    bm = bmesh.new()
    verts = [bm.verts.new(p) for p in points]
    for face in faces:
        bm.faces.new([verts[i] for i in face])
    bm.verts.ensure_lookup_table()
    bm.edges.ensure_lookup_table()
    bm.faces.ensure_lookup_table()
    bm.normal_update()
    return bm


def _strip(rows=1, lift=None, uv=False, reverse=False):
    """The core's strip() (rows=1) or strip2() (rows=2): chain 0-1-2-3 along y = 0.

    ``lift=(point, dz)`` raises the vertex at ``point`` by ``dz``. ``uv=True`` adds a
    UV layer with each loop's UV at its vertex's (x, y), ``uv="half"`` at (x, y) / 2.
    ``reverse=True`` winds every face the other way, so the faces lie on the chain's -1 side.
    """
    points = [(x, r / rows, 0.0) for r in range(rows + 1) for x in range(4)]
    if lift is not None:
        where, dz = lift
        points = [(p[0], p[1], p[2] + dz) if p == where else p for p in points]
    faces = [(4 * r + x, 4 * r + x + 1, 4 * r + x + 5, 4 * r + x + 4) for r in range(rows) for x in range(3)]
    if reverse:
        faces = [face[::-1] for face in faces]
    bm = _mesh(points, faces)
    return _add_uvs(bm, 0.5 if uv == "half" else 1.0) if uv else bm


def _add_uvs(bm, scale=1.0):
    """A UV layer with each loop's UV at its vertex's (x, y) times ``scale``."""
    layer = bm.loops.layers.uv.new("UVMap")
    for face in bm.faces:
        for lp in face.loops:
            lp[layer].uv = lp.vert.co.xy * scale
    return bm


def _placed(bm, offset, angle=0.0):
    """``bm`` turned by ``angle`` degrees about z, then moved by ``offset``."""
    turn = Matrix.Rotation(math.radians(angle), 3, "Z")
    for v in bm.verts:
        v.co = turn @ v.co + Vector(offset)
    bm.normal_update()
    return bm


def _strip_plus_border_chain():
    """The strip with two chains selected: 0-1-2-3 and its open top border 4-5-6-7, which has no +1 face."""
    bm = _strip()
    _select_chain(bm, [0, 1, 2, 3])
    _select_chain(bm, [4, 5, 6, 7])
    return bm


def _ngon_diag():
    points = [(0, 0, 0), (2, 0, 0), (4, 0, 0), (4, 0.5, 0), (4, 1, 0), (0, 1, 0)]
    return _mesh(points, [(0, 1, 3, 4, 5), (1, 2, 3)])


def _sliver():
    points = [(0, 0, 0), (1, -0.1, 0), (2, 0, 0), (2, 1, 0), (0, 1, 0)]
    return _mesh(points, [(0, 1, 2), (0, 2, 3, 4)])


def _box_corner():
    points = [(0, 0, 1), (1, 0, 1), (1, 1, 1), (0, 0, 0), (1, 0, 0), (1, 1, 0)]
    return _mesh(points, [(0, 1, 4, 3), (1, 2, 5, 4)])


def _pocket(points_after=(), faces_after=()):
    """Chain 0-1-2-3 along y = 0: ceiling quads at z = 0 on x in [0, 1] and [2, 3],
    a 0.15-tall pocket on x in [1, 2] (lip, sides, top, far wall), and slanted
    faces down to y = -1, z = -1 on the other side. ``points_after`` (ids from 16)
    and ``faces_after`` extend it."""
    points = [
        (0, 0, 0), (1, 0, 0), (2, 0, 0), (3, 0, 0),                    # 0-3 chain
        (0, 2, 0), (1, 2, 0), (2, 2, 0), (3, 2, 0),                    # 4-7 ceiling far corners
        (1, 0, 0.15), (2, 0, 0.15), (1, 2, 0.15), (2, 2, 0.15),        # 8-11 pocket top corners
        (0, -1, -1), (1, -1, -1), (2, -1, -1), (3, -1, -1),            # 12-15 slanted far corners
    ]
    faces = [
        (0, 1, 5, 4), (1, 2, 9, 8), (2, 3, 7, 6),                      # ceiling, lip, ceiling
        (1, 8, 10, 5), (2, 6, 11, 9), (8, 9, 11, 10), (5, 10, 11, 6),  # pocket sides, top, far wall
        (1, 0, 12, 13), (2, 1, 13, 14), (3, 2, 14, 15),                # slanted side
    ]
    return _mesh(points + list(points_after), faces + list(faces_after))


def _pocket_with_fold():
    """The pocket with quads hanging down from y = 2 to 16-19 at (x, 2, -1), x = 0 .. 3: one of
    them past the lid's far edge 5-6, whose other face is the pocket's far wall."""
    return _pocket([(x, 2, -1) for x in range(4)], [(4, 5, 17, 16), (5, 6, 18, 17), (6, 7, 19, 18)])


def _pocket_with_tilted_run_on():
    """The pocket with faces past y = 2 at 5: edge 5-16 runs on 16.7 degrees off straight but drops out
    of the ceiling plane to 16 (1, 3, -.3); edge 5-17 stays in it but turns 21.8 degrees, to 17 (1.4, 3, 0)."""
    return _pocket([(1, 3, -0.3), (1.4, 3, 0)], [(5, 6, 17), (5, 17, 16), (4, 5, 16)])


def _pocket_with_meeting_paths():
    """The pocket with ceiling triangles past its far edge 5-6, in the ceiling plane: 16 (1.5, 3, 0),
    17 (2, 4, 0), 18 (2.5, 5, 0), 19 (3, 4, 0). The flank path from 1 runs 1-5-16-17-18 straight on
    (26.6 degrees at 5), the one from 2 runs 2-6-17-18: the two meet at 17."""
    return _pocket([(1.5, 3, 0), (2, 4, 0), (2.5, 5, 0), (3, 4, 0)], [(5, 6, 16), (16, 6, 17), (17, 19, 18)])


def _pocket_mid_row():
    """The pocket with its top split along y = 1: vertex 16 (1, 1, .15) on side 1-8-10-5, 17 (2, 1, .15)
    on side 2-6-11-9, and 18 (1.5, 1, .15) in the middle of the top."""
    bm = _pocket()
    v = list(bm.verts)
    top = bm.faces[5]
    _edge, v16 = bmesh.utils.edge_split(bm.edges.get((v[8], v[10])), v[8], 0.5)
    _edge, v17 = bmesh.utils.edge_split(bm.edges.get((v[9], v[11])), v[9], 0.5)
    bmesh.utils.face_split(top, v16, v17)
    bmesh.utils.edge_split(bm.edges.get((v16, v17)), v16, 0.5)
    bm.verts.index_update()
    bm.verts.ensure_lookup_table()
    bm.edges.ensure_lookup_table()
    bm.faces.ensure_lookup_table()
    bm.normal_update()
    return bm


def _pocket_uneven_flanks():
    """The pocket with the ceiling quad on x in [0, 1] and the pocket side wall at x = 1 split along
    y = .4: 16 (0, .4, 0), 17 (1, .4, 0) and 18 (1, .4, .15). The flank rail from chain vertex 1
    now ends at 17, the other one still at (2, 2, 0), and the pocket top, a pentagon with 18 on
    its edge, still spans y 0 .. 2."""
    bm = _pocket()
    v = list(bm.verts)
    ceiling, side = bm.faces[0], bm.faces[3]
    made = []
    for a, b, co in ((0, 4, (0, .4, 0)), (1, 5, (1, .4, 0)), (8, 10, (1, .4, .15))):
        _edge, vert = bmesh.utils.edge_split(bm.edges.get((v[a], v[b])), v[a], 0.2)
        vert.co = co
        made.append(vert)
    bmesh.utils.face_split(ceiling, made[0], made[1])
    bmesh.utils.face_split(side, made[1], made[2])
    bm.verts.index_update()
    bm.verts.ensure_lookup_table()
    bm.edges.ensure_lookup_table()
    bm.faces.ensure_lookup_table()
    bm.normal_update()
    return bm


def _ring():
    """The core's ring(): inner square chain 0-1-2-3 (closed) on [-1, 1]^2, outer square on [-2, 2]^2."""
    points = [(-1, -1, 0), (1, -1, 0), (1, 1, 0), (-1, 1, 0), (-2, -2, 0), (2, -2, 0), (2, 2, 0), (-2, 2, 0)]
    return _mesh(points, [(0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)])


def _pocket_two_edge_lip():
    """Chain 0-1-2-3-4 along y = 0: ceiling quads at z = 0 on x in [0, 1] and [3, 4], and a
    0.15-tall pocket on x in [1, 3] whose lip has two edges (vertex 2 in the middle)."""
    points = [
        (0, 0, 0), (1, 0, 0), (2, 0, 0), (3, 0, 0), (4, 0, 0),         # 0-4 chain
        (0, 2, 0), (1, 2, 0), (3, 2, 0), (4, 2, 0),                    # 5-8 ceiling far corners
        (1, 0, .15), (2, 0, .15), (3, 0, .15), (1, 2, .15), (3, 2, .15),   # 9-13 pocket top corners
    ]
    faces = [
        (0, 1, 6, 5), (1, 2, 10, 9), (2, 3, 11, 10), (3, 4, 8, 7),     # ceiling, two lips, ceiling
        (1, 9, 12, 6), (3, 7, 13, 11), (9, 10, 11, 13, 12), (6, 12, 13, 7),  # sides, top, far wall
    ]
    return _mesh(points, faces)


def _l_region():
    """Three flat quads in an L (the 2 x 2 square without its +x +y quad). Chain
    0-1-2-3 runs along the notch, (2,0) -> (2,1) -> (1,1) -> (1,2): it turns 90°
    twice on a flat surface, with the region on its +1 side."""
    points = [(2, 0, 0), (2, 1, 0), (1, 1, 0), (1, 2, 0),            # 0-3 chain
              (0, 0, 0), (1, 0, 0), (0, 1, 0), (0, 2, 0)]
    return _mesh(points, [(5, 0, 1, 2), (6, 2, 3, 7), (4, 5, 2, 6)])


def _corner_grid(corner=True):
    """Flat 2 x 2 quad grid over [0, 2]^2. Chain 0-1-2 is (0,1) -> (1,1) -> (1,0); its +1
    side is the three quads away from [0,1]^2. ``corner=False`` leaves out the
    [1,2]^2 quad (face 3), so vertex 1 sits on the mesh border with the gap on +1."""
    points = [(0, 1, 0), (1, 1, 0), (1, 0, 0),                        # 0-2 chain
              (0, 0, 0), (2, 0, 0), (2, 1, 0), (0, 2, 0), (1, 2, 0), (2, 2, 0)]
    faces = [(3, 2, 1, 0), (2, 4, 5, 1), (0, 1, 7, 6)] + ([(1, 5, 8, 7)] if corner else [])
    return _mesh(points, faces)


def _flipped_half():
    """Flat quads around chain 0-1-2 along y = 0; the two quads on x in [0, 1] are wound
    the other way. Edge 0's +1 face is then below the chain and edge 1's above it."""
    points = [(0, 0, 0), (1, 0, 0), (2, 0, 0),                        # 0-2 chain
              (0, 1, 0), (1, 1, 0), (2, 1, 0), (0, -1, 0), (1, -1, 0), (2, -1, 0)]
    return _mesh(points, [(1, 2, 5, 4), (7, 8, 2, 1), (0, 3, 4, 1), (0, 1, 7, 6)])


def _fold_box():
    """The core's fold_box(): a floor y in [0, 1] at z = 0 and a wall at y = 1 up to z = 1, over x
    columns 0, 1, 2. Chain 0-1-2 runs along the floor's front edge, the floor on its +1 side."""
    points = [(0, 0, 0), (1, 0, 0), (2, 0, 0), (0, 1, 0), (1, 1, 0), (2, 1, 0), (0, 1, 1), (1, 1, 1), (2, 1, 1)]
    return _mesh(points, [(0, 1, 4, 3), (1, 2, 5, 4), (3, 4, 7, 6), (4, 5, 8, 7)])


def _grid(nx, ny):
    """Flat grid of unit quads in XY with ``nx`` x ``ny`` vertices, built as the cursor-bisect tests build
    theirs. Vertex y * nx + x, face y * (nx - 1) + x: ``_grid(5, 4)`` is the core's grid_open()."""
    points = [(x, y, 0) for y in range(ny) for x in range(nx)]
    faces = [(y * nx + x, y * nx + x + 1, (y + 1) * nx + x + 1, (y + 1) * nx + x)
             for y in range(ny - 1) for x in range(nx - 1)]
    return _mesh(points, faces)


def _cube_top_chain():
    """``bmesh.ops.create_cube(size=1.0)`` with its top front edge (y = -0.5, z = 0.5) selected; the top
    face lies on the chain's +1 side."""
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    bm.verts.ensure_lookup_table()
    bm.edges.ensure_lookup_table()
    bm.faces.ensure_lookup_table()
    bm.normal_update()
    for seq in (bm.verts, bm.edges, bm.faces):
        for elem in seq:
            elem.select = False
    edge = next(e for e in bm.edges if all(abs(v.co.y + 0.5) < 1e-6 and abs(v.co.z - 0.5) < 1e-6 for v in e.verts))
    edge.select_set(True)
    (src,), _warnings = bridge.collect_chains(bm)
    top = next(f for f in bm.faces if f.normal.z > 0.5)
    a, b = src.verts
    assert any(lp.vert is a and lp.link_loop_next.vert is b for lp in top.loops), "the top face is not on +1"
    return bm


def _strip_with_fin():
    """The core's strip2() with its quad 5-6-10-9 split at x = 1.5 (12 (1.5, .5, 0), 13 (1.5, 1, 0)) and a fin
    12-13-15-14 standing up to z = 1 on the split edge, which three faces then hold."""
    points = [(x, r / 2, 0.0) for r in range(3) for x in range(4)]
    points += [(1.5, .5, 0), (1.5, 1, 0), (1.5, .5, 1), (1.5, 1, 1)]
    faces = [(0, 1, 5, 4), (1, 2, 6, 12, 5), (2, 3, 7, 6),
             (4, 5, 9, 8), (5, 12, 13, 9), (12, 6, 10, 13), (6, 7, 11, 10), (12, 13, 15, 14)]
    return _mesh(points, faces)


def _walls_meet():
    """The core's walls_meet() with a row of quads below y = 0 (7-10 at y = -1), so the band runs on past
    the end walls along y = 0. Chain 0-1-2-3 is (0, .3), (1, 1), (2, 1), (2.5, 0); its end edges 0-4 and
    3-6 leave it at 158.6 and 63.4 degrees, and the end wall 3-6-5-4 meets the start wall 0-4 at 4."""
    points = [(0, .3, 0), (1, 1, 0), (2, 1, 0), (2.5, 0, 0), (-.2, 0, 0), (1, 0, 0), (1.5, 0, 0),
              (-.2, -1, 0), (1, -1, 0), (1.5, -1, 0), (2.5, -1, 0)]
    faces = [(0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 6), (4, 5, 8, 7), (5, 6, 9, 8), (6, 3, 10, 9)]
    return _mesh(points, faces)


def _select_chain(bm, ids):
    for a, b in zip(ids, ids[1:]):
        bm.edges.get((bm.verts[a], bm.verts[b])).select_set(True)


def _chain(bm, ids):
    return bridge.ChainSrc(verts=[bm.verts[i] for i in ids], closed=False, index=0)


# --- objects for execute() ------------------------------------------------------

_BEFORE = {}  # object name -> rounded vertex coordinates when it entered Edit Mode


def _edit_object(bm, chain):
    """``bm`` as the active mesh object in Edit Mode (edge select), with ``chain`` selected.

    ``chain=None`` keeps the builder's selection. Frees ``bm``.
    """
    if bpy.context.object is not None and bpy.context.object.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    for other in bpy.context.view_layer.objects:
        other.select_set(False)
    if chain is not None:
        for seq in (bm.verts, bm.edges, bm.faces):
            for elem in seq:
                elem.select = False
        _select_chain(bm, chain)
    me = bpy.data.meshes.new("smart_edge_slide")
    bm.to_mesh(me)
    bm.free()
    obj = bpy.data.objects.new("smart_edge_slide", me)
    bpy.context.scene.collection.objects.link(obj)
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    bpy.context.tool_settings.mesh_select_mode = (False, True, False)
    bpy.ops.object.mode_set(mode="EDIT")
    _BEFORE[obj.name] = _coords(obj)
    return obj


def _read(obj, fn):
    """``fn`` applied to the object's live edit bmesh, or to a copy of its mesh once it has left Edit Mode."""
    if obj.mode == "EDIT":
        return fn(bmesh.from_edit_mesh(obj.data))
    bm = bmesh.new()
    try:
        bm.from_mesh(obj.data)
        return fn(bm)
    finally:
        bm.free()


def _key(co):
    return tuple(round(float(c), 6) for c in co)


def _round_set(points):
    return {_key(p) for p in points}


def _coords(obj):
    return _read(obj, lambda bm: {_key(v.co) for v in bm.verts})


def _new_coords(obj):
    """Rounded coordinates of the vertices that were not there when ``obj`` entered Edit Mode."""
    return _coords(obj) - _BEFORE[obj.name]


def _counts(obj):
    return _read(obj, lambda bm: (len(bm.verts), len(bm.faces)))


def _edge_between(obj, p, q, tol=1e-5):
    p, q = Vector(p), Vector(q)

    def joined(bm):
        for e in bm.edges:
            a, b = (v.co for v in e.verts)
            if ((a - p).length <= tol and (b - q).length <= tol) or ((a - q).length <= tol and (b - p).length <= tol):
                return True
        return False

    return _read(obj, joined)


def _selected_edge_count(obj):
    return _read(obj, lambda bm: sum(e.select for e in bm.edges))


def _edge_key(p, q):
    return tuple(sorted((_key(p), _key(q))))


def _selected_edges(obj):
    return _read(obj, lambda bm: {_edge_key(*(v.co for v in e.verts)) for e in bm.edges if e.select})


def _evaluated_vertex_count(obj):
    """Vertices of the evaluated object: it only sees edit-mesh changes once update_edit_mesh tagged it."""
    ev = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
    count = len(ev.to_mesh().vertices)
    ev.to_mesh_clear()
    return count


def _validate_fixed_something(obj):
    """Leave Edit Mode and run Mesh.validate(); True when it had to fix the mesh."""
    bpy.ops.object.mode_set(mode="OBJECT")
    return obj.data.validate(verbose=True)


class _OperatorStandIn:
    """Stands in for an operator instance: execute() runs on these props and keeps its reports.

    bpy.ops does not hand reports back to Python, so a test that checks a warning calls
    execute() on this instead.
    """

    def __init__(self, **props):
        self.width, self.use_exact, self.use_collapse, self.chain_sides = 0.05, False, False, ""
        self.use_uv_stripe, self.uv_stripe_mode = False, "FIT"
        self.__dict__.update(props)
        self.reports = []

    def report(self, _kinds, message):
        self.reports.append(message)

    def __getattr__(self, name):  # the operator's own methods, bound to this stand-in
        return getattr(operator, name).__get__(self)


def _bvh_before(obj):
    """A BVH tree of the mesh as it is now (BVHTree keeps its own copy of the triangles)."""
    return _read(obj, BVHTree.FromBMesh)


def _uv_v_of_new_verts(obj):
    def values(bm):
        layer = bm.loops.layers.uv.active
        return [lp[layer].uv.y for v in bm.verts if _key(v.co) not in _BEFORE[obj.name] for lp in v.link_loops]

    found = _read(obj, values)
    assert found, "no new vertices"
    return found


def _strip_corners(obj, low=0.0, high=None):
    """(rounded co, rounded UV) of every corner of the faces with every vertex in low <= y <= high.

    By default these are the faces between a chain along y = 0 and its new loop:
    ``high=None`` takes the y of the new loop, which execute() leaves selected.
    """
    def corners(bm):
        layer = bm.loops.layers.uv.active
        top = (max(v.co.y for v in bm.verts if v.select) if high is None else high) + 1e-6
        return [(_key(lp.vert.co), _key(lp[layer].uv))
                for f in bm.faces if all(low - 1e-6 <= v.co.y <= top for v in f.verts) for lp in f.loops]

    found = _read(obj, corners)
    assert found, "no strip faces"
    return found


def _strip_corner_uvs(obj):
    """{rounded co: set of rounded UVs} over the corners of the strip faces."""
    out = {}
    for co, uv in _strip_corners(obj):
        out.setdefault(co, set()).add(uv)
    return out


def _strip_uv_ranges(obj, low=0.0, high=None):
    """((min u, max u), (min v, max v)) over the corners of the strip faces (see ``_strip_corners``), rounded."""
    uvs = [uv for _co, uv in _strip_corners(obj, low, high)]
    us, vs = [u for u, _v in uvs], [v for _u, v in uvs]
    return (min(us), max(us)), (min(vs), max(vs))


def _uv_areas(obj, keep):
    """Signed UV area of every face whose rounded vertex coordinates ``keep`` accepts, corners in the face's order."""
    def areas(bm):
        layer = bm.loops.layers.uv.active
        out = []
        for f in bm.faces:
            if keep([_key(v.co) for v in f.verts]):
                pts = [lp[layer].uv for lp in f.loops]
                out.append(0.5 * sum(a.x * b.y - b.x * a.y for a, b in zip(pts, pts[1:] + pts[:1])))
        return out

    found = _read(obj, areas)
    assert found, "no faces kept"
    return found


def _seam_ring():
    """A closed chain 0-1-2-3 (counter-clockwise) round a ring of four quads, inner quad 4-7.

    Its short left side 3 -> 0 closes the chain (the seam segment). Cut inward
    with collapse on, that segment collapses past width 0.64, and the cut's
    anchors start mid-way round the new loop ([3, 0, 1, 3] at width 0.9).
    """
    points = [(0, -0.5, 0), (10, -3, 0), (10, 3, 0), (0, 0.5, 0),
              (4, -0.3, 0), (7, -0.5, 0), (7, 0.5, 0), (4, 0.3, 0)]
    return _mesh(points, [(0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)])


def _two_strips():
    """Two strips like _strip(), the second moved to y = 5, with chains 0-1-2-3 and 8-9-10-11 selected."""
    points = [(x, y + dy, 0.0) for dy in (0.0, 5.0) for y in (0.0, 1.0) for x in range(4)]
    faces = [(o + x, o + x + 1, o + x + 5, o + x + 4) for o in (0, 8) for x in range(3)]
    bm = _mesh(points, faces)
    _select_chain(bm, [0, 1, 2, 3])
    _select_chain(bm, [8, 9, 10, 11])
    return bm


class _KeyPress:
    """Stands in for a modal key press event without modifiers."""

    def __init__(self, key):
        self.type, self.value = key, "PRESS"
        self.shift = self.ctrl = self.alt = self.oskey = False
        self.mouse_x = self.mouse_y = self.mouse_region_x = self.mouse_region_y = 0


def _run(bm_obj, **props):
    return bpy.ops.iops.mesh_smart_edge_slide('EXEC_DEFAULT', **props)


# --- the modal, driven by stand-in events -----------------------------------------

def _event(kind, x=0, y=0, value="PRESS", shift=False, ctrl=False):
    """A modal event at region pixel (x, y)."""
    return SimpleNamespace(type=kind, value=value, shift=shift, ctrl=ctrl, alt=False, oskey=False,
                           mouse_region_x=x, mouse_region_y=y, mouse_x=x, mouse_y=y)


def _move(x, y=0, shift=False, ctrl=False):
    return _event("MOUSEMOVE", x, y, value="NOTHING", shift=shift, ctrl=ctrl)


def _modal_context():
    """A context for invoke() and the modal over the active object.

    ``region_data`` is a placeholder, so invoke() takes the modal path; there is no
    region, so nothing is drawn and the snap search falls back to world distances.
    """
    ctx = bpy.context
    return SimpleNamespace(
        active_object=ctx.active_object, region=None, region_data=SimpleNamespace(), space_data=None,
        area=None, workspace=ctx.workspace, preferences=ctx.preferences,
        window_manager=SimpleNamespace(modal_handler_add=lambda _op: None))


def _invoke(x=0, **props):
    """invoke() on a stand-in operator over the active object, the mouse at region x = ``x``.

    Region pixels are object x and y times 100. ``_mouse_world`` is left to each test:
    set it to the vertex a Ctrl move should snap to.
    """
    op = _OperatorStandIn(**props)
    op._to_region = lambda _ctx, co: (co.x * 100.0, co.y * 100.0)
    ctx = _modal_context()
    assert op.invoke(ctx, _move(x)) == {'RUNNING_MODAL'}
    return op, ctx


def _keys(op, ctx, keys, x=0, y=0):
    for key in keys.split():
        assert op._modal(ctx, _event(key, x, y)) == {'RUNNING_MODAL'}, key


def _close(a, b, tol=1e-9):
    assert abs(a - b) <= tol, (a, b)


def _wire_and_two_strips():
    """Three chains, all selected: a wire edge 0-1 at y = 5 (no faces, so no band on either side)
    and the middle rows 6-7-8-9 (y = 0) and 18-19-20-21 (y = 10) of two strips of two rows, each
    with faces on both sides."""
    points = [(0.0, 5.0, 0.0), (1.0, 5.0, 0.0)]
    points += [(float(x), y + dy, 0.0) for dy in (0.0, 10.0) for y in (-1.0, 0.0, 1.0) for x in range(4)]
    faces = [(b + 4 * r + x, b + 4 * r + x + 1, b + 4 * r + x + 5, b + 4 * r + x + 4)
             for b in (2, 14) for r in range(2) for x in range(3)]
    bm = _mesh(points, faces)
    bm.edges.new((bm.verts[0], bm.verts[1]))
    for chain in ([0, 1], [6, 7, 8, 9], [18, 19, 20, 21]):
        _select_chain(bm, chain)
    return bm


def _strip_between_two_chains(mid):
    """Two rows over x in [0, 3], split at y = ``mid``: chain 0-1-2-3 along y = 0 (faces on +1) and
    chain 8-9-10-11 along y = 1 (faces on -1), both selected. The middle row 4-7 is in both bands."""
    points = [(float(x), y, 0.0) for y in (0.0, mid, 1.0) for x in range(4)]
    faces = [(4 * r + x, 4 * r + x + 1, 4 * r + x + 5, 4 * r + x + 4) for r in range(2) for x in range(3)]
    bm = _mesh(points, faces)
    _select_chain(bm, [0, 1, 2, 3])
    _select_chain(bm, [8, 9, 10, 11])
    return bm


# --- tests -----------------------------------------------------------------------

def test_collect_chains_orders_and_rejects_branching():
    bm = _strip()
    _select_chain(bm, [0, 1, 2, 3])
    chains, warns = bridge.collect_chains(bm)
    assert [[v.index for v in c.verts] for c in chains] == [[0, 1, 2, 3]] and warns == []
    bm.edges.get((bm.verts[1], bm.verts[5])).select = True       # T-junction
    chains, warns = bridge.collect_chains(bm)
    assert chains == [] and warns == ["branching selection"]


def test_collect_chains_closed_and_reversed_order():
    bm = _strip()
    _select_chain(bm, [7, 6, 2, 3])                               # open, selected from its far end
    bm.edges.get((bm.verts[2], bm.verts[3])).hide = True          # hidden edges are not part of it
    _select_chain(bm, [5, 4, 0, 1, 5])                            # closed, around face 0
    chains, warns = bridge.collect_chains(bm)
    assert [[v.index for v in c.verts] for c in chains] == [[0, 1, 5, 4], [2, 6, 7]], chains
    assert [c.closed for c in chains] == [True, False] and warns == []


def test_build_band_strip_side():
    bm = _strip()
    src = _chain(bm, [0, 1, 2, 3])
    build, err = bridge.build_band(bm, src, +1)
    assert err is None and len(build.band.side_faces) == 3 and build.steps == []
    build, err = bridge.build_band(bm, src, -1)
    assert build is None and err == "chain edge without a visible face on that side"   # Review Focus 4


def test_hidden_side_face_skips_chain():                                              # Review Focus 2
    bm = _strip()
    bm.faces[1].hide = True
    build, err = bridge.build_band(bm, _chain(bm, [0, 1, 2, 3]), +1)
    assert build is None and err == "chain edge without a visible face on that side"


def test_box_corner_has_no_step():
    bm = _box_corner()
    build, _ = bridge.build_band(bm, _chain(bm, [0, 1, 2]), +1)
    assert build.steps == []


def test_pocket_lip_becomes_lid():
    bm = _pocket()
    build, err = bridge.build_band(bm, _chain(bm, [0, 1, 2, 3]), +1)
    assert err is None and len(build.steps) == 1
    st = build.steps[0]
    assert (st.first, st.last) == (1, 2) and build.band.side_faces[1] == st.lid < 0
    assert {tuple(round(c, 3) for c in f.calc_center_median()) for f in st.region} >= {
        (1.5, 0.0, 0.075), (1.0, 1.0, 0.075), (2.0, 1.0, 0.075), (1.5, 1.0, 0.15)}
    assert tuple(round(c, 6) for c in st.normal) in {(0.0, 0.0, 1.0), (0.0, 0.0, -1.0)}


def test_build_band_takes_the_mesh_triangles():                                      # Review Focus 5
    bm = _pocket()
    build, _ = bridge.build_band(bm, _chain(bm, [0, 1, 2, 3]), +1)
    shown = {}
    for tri in bm.calc_loop_triangles():
        shown.setdefault(tri[0].face.index, []).append(tuple(lp.vert.index for lp in tri))
    assert build.band.tris == {f: shown[f] for f in build.faces}   # every real face, no lid
    assert all(f >= 0 for f in build.band.tris)


def test_bands_share_one_triangulation():   # one calc_loop_triangles per run, not one per band
    face_triangles, calls = bridge.face_triangles, []

    def counting(bm):
        calls.append(None)
        return face_triangles(bm)

    bridge.face_triangles = counting
    try:
        obj = _edit_object(_wire_and_two_strips(), chain=None)
        op = _OperatorStandIn()
        op._bm = bmesh.from_edit_mesh(obj.data)
        assert op._build_sides(op._bm) and sum(len(found) for found in op._sides) == 4
        assert len(calls) == 1, len(calls)
        calls.clear()
        _edit_object(_two_strips(), chain=None)
        assert _OperatorStandIn(width=0.25, chain_sides="++").execute(bpy.context) == {'FINISHED'}
        assert len(calls) == 2, len(calls)          # again only once the first cut changed the mesh
    finally:
        bridge.face_triangles = face_triangles


def test_l_region_border_turns_are_not_steps():
    bm = _l_region()
    build, err = bridge.build_band(bm, _chain(bm, [0, 1, 2, 3]), +1)
    assert err is None and build.steps == [], err
    assert build.band.side_faces == [0, 0, 1] and sorted(build.band.faces) == [0, 1, 2]


def test_pocket_lid_replaces_pocket_faces():
    bm = _pocket()
    build, _ = bridge.build_band(bm, _chain(bm, [0, 1, 2, 3]), +1)
    band = build.band
    assert band.faces[-1] == (1, 2, 6, 5)                         # (P_a, P_b, R_b, R_a)
    assert sorted(f for f in band.faces if f >= 0) == [0, 2] == sorted(build.faces)
    assert core.wedge(band, 1).faces == [-1, 0] and core.wedge(band, 2).faces == [2, -1]


def test_pocket_region_skips_hidden_faces():                                          # Review Focus 2
    bm = _pocket()
    bm.faces[5].hide = True                                       # pocket top
    build, _ = bridge.build_band(bm, _chain(bm, [0, 1, 2, 3]), +1)
    assert [f.index for f in build.steps[0].region] == [1, 3, 4, 6]


def test_pocket_lid_bridges_hidden_side_walls():
    bm = _pocket()
    bm.faces[3].hide = bm.faces[4].hide = True                    # the fans at 1 and 2 stop at them
    build, err = bridge.build_band(bm, _chain(bm, [0, 1, 2, 3]), +1)
    assert err is None and [(s.first, s.last) for s in build.steps] == [(1, 2)], err
    assert [f.index for f in build.steps[0].region] == [1, 5, 6]


def test_hidden_corner_quad_interrupts_wedge():                                       # Review Focus 2
    bm = _corner_grid()
    bm.faces[3].hide = True
    build, err = bridge.build_band(bm, _chain(bm, [0, 1, 2]), +1)
    assert build is None and err == bridge.WEDGE_INTERRUPTED == (
        "the faces round a chain vertex stop at an edge without exactly two visible faces, or an end wall cannot leave them")
    build, err = bridge.build_band(bm, _chain(bm, [0, 1, 2]), -1)  # the inner side is whole
    assert err is None and sorted(build.band.faces) == [0]


def test_border_gap_at_chain_vertex_interrupts_wedge():
    bm = _corner_grid(corner=False)
    build, err = bridge.build_band(bm, _chain(bm, [0, 1, 2]), +1)
    assert build is None and err == bridge.WEDGE_INTERRUPTED == (
        "the faces round a chain vertex stop at an edge without exactly two visible faces, or an end wall cannot leave them")


def test_side_faces_in_different_sectors_skip_chain():
    bm = _flipped_half()
    for side in (+1, -1):
        build, err = bridge.build_band(bm, _chain(bm, [0, 1, 2]), side)
        assert build is None and err == "chain vertex side faces with inconsistent normals", (side, err)


def test_two_faces_on_one_side_skip_chain():
    bm = _strip()
    v0, v1 = bm.verts[0], bm.verts[1]
    bm.faces.new((v0, v1, bm.verts.new((1, 0, 1)), bm.verts.new((0, 0, 1))))   # also runs 0 -> 1
    bm.verts.ensure_lookup_table()
    build, err = bridge.build_band(bm, _chain(bm, [0, 1, 2, 3]), +1)
    assert build is None and err == "chain edge with several faces on that side"


def test_sliver_end_wedges_cross_the_shallow_chord():
    bm = _sliver()
    build, err = bridge.build_band(bm, _chain(bm, [0, 1, 2]), +1)
    assert err is None and build.band.side_faces == [0, 0]
    assert sorted(build.band.faces) == [0, 1]


def test_chain_end_inside_the_mesh_stops_at_its_end_walls():
    bm = _strip(rows=2)
    build, err = bridge.build_band(bm, _chain(bm, [5, 6]), +1)
    assert err is None and sorted(build.band.faces) == list(range(6))   # the flood runs round the chain's ends
    assert build.band.end_edges == (9, 10)                               # the walls up from 5 and 6 bound the cut
    cut = core.Slider(build.band).solve(0.25)
    assert _round_set(pt.co for pt in cut.points) == _round_set([(1, .75, 0), (2, .75, 0)])


def test_build_band_floods_the_side_and_names_its_end_edges():
    bm = _grid(5, 4)
    build, err = bridge.build_band(bm, _chain(bm, [6, 7, 8]), +1)
    assert err is None, err
    assert sorted(build.band.faces) == list(range(12)) and build.band.end_edges == (11, 13)   # the core's grid_open()
    for k in (0, 2):                     # each end edge leaves the chain into the side, by END_SHALLOW at least
        assert core.wedge(build.band, k).theta >= bridge.END_SHALLOW
    bm = _ring()
    build, err = bridge.build_band(bm, bridge.ChainSrc(verts=[bm.verts[i] for i in range(4)], closed=True, index=0), +1)
    assert err is None and build.band.end_edges == (None, None) and sorted(build.band.faces) == [0, 1, 2, 3]


def test_pocket_lid_follows_the_flank_rail_paths():
    bm = _pocket_uneven_flanks()
    build, err = bridge.build_band(bm, _chain(bm, [0, 1, 2, 3]), +1)
    assert err is None, err
    assert build.band.faces[-1] == (1, 2, 6, 5, 17)               # (P_a, P_b, path_b, path_a reversed): 1-17-5
    assert sorted(f.index for f in build.faces.values()) == [0, 2, 10]       # the three ceiling quads
    assert not {f.index for f in build.steps[0].region} & {0, 2, 10}         # none of them under the lid


def test_strip_faces_stop_at_the_end_walls():   # the band runs on round the chain's ends, the strip must not
    bm = _grid(5, 4)
    build, err = bridge.build_band(bm, _chain(bm, [6, 7, 8]), +1)
    assert err is None, err
    applied = bridge.apply_cut(bm, build, core.Slider(build.band).solve(1.5))
    assert not applied.failures, applied.failures
    assert len(applied.strip_faces) == 4, len(applied.strip_faces)
    assert all(1 <= v.co.x <= 3 and 1 <= v.co.y <= 2.5 for f in applied.strip_faces for v in f.verts)
    bm.free()


def test_strip_faces_need_bounded_ends():   # an open end with no end path, off the band border: no strip
    bm = _grid(5, 4)
    build, err = bridge.build_band(bm, _chain(bm, [6, 7, 8]), +1)
    assert err is None, err
    cut = core.Slider(build.band).solve(1.5)
    # As if the start had no end edge: its loop end (1, 2.5) lies inside the band, so nothing bounds the strip there.
    build.band = dataclasses.replace(build.band, end_edges=(None, 13))
    applied = bridge.apply_cut(bm, build, cut)
    assert not applied.failures and applied.strip_faces == [], len(applied.strip_faces)
    bm.free()


def test_step_region_stops_at_the_lids_far_side():   # a far side that is no mesh edge bounds the region
    bm = _pocket_uneven_flanks()
    bm.verts[5].co.z = 0.05                 # the path from 1 now ends at 17: the lid's far side 17-6 is no edge
    bm.normal_update()
    build, err = bridge.build_band(bm, _chain(bm, [0, 1, 2, 3]), +1)
    assert err is None, err
    assert build.band.faces[-1] == (1, 2, 6, 17)
    # The region keeps the lip, the lower side wall at x = 1, the side wall at x = 2 and the top: what reaches
    # short of 17-6. The ceiling quad past 17 (10) and the pocket faces wholly past 17-6 stay real faces.
    assert [f.index for f in build.steps[0].region] == [1, 3, 4, 5]
    assert {0, 2, 10} <= set(build.faces)


def test_lid_path_stops_where_the_straightest_edge_leaves_the_plane():
    bm = _pocket_with_tilted_run_on()
    build, err = bridge.build_band(bm, _chain(bm, [0, 1, 2, 3]), +1)
    assert err is None, err
    assert build.band.faces[-1] == (1, 2, 6, 5)       # not on along the in-plane edge 5-17, which turns more


def test_lid_paths_stop_where_they_meet():
    bm = _pocket_with_meeting_paths()
    build, err = bridge.build_band(bm, _chain(bm, [0, 1, 2, 3]), +1)
    assert err is None, err
    assert build.band.faces[-1] == (1, 2, 6, 17, 16, 5)   # 1-5-16 ends on 17, a vertex of the path 2-6-17-18


def test_lid_tolerance_takes_the_first_corners():   # the lid's run-on along its flank paths does not widen it
    bm = _pocket_with_meeting_paths()
    build, err = bridge.build_band(bm, _chain(bm, [0, 1, 2, 3]), +1)
    assert err is None, err
    _close(build.steps[0].extent, math.sqrt(5.0))         # the corners 1, 2, 6, 5: from (1, 0) to (2, 2)


def test_ngon_band_keeps_the_wedge_face():
    bm = _ngon_diag()
    build, err = bridge.build_band(bm, _chain(bm, [0, 1, 2]), +1)
    assert err is None and build.band.side_faces == [0, 1] and core.wedge(build.band, 1).faces == [1, 0]


def test_execute_strip():                       # new loop at exact width, selected
    obj = _edit_object(_strip(), chain=[0, 1, 2, 3])
    assert _run(obj, width=0.25, chain_sides="+") == {'FINISHED'}
    assert _new_coords(obj) == _round_set([(x, 0.25, 0.0) for x in range(4)])
    assert _selected_edge_count(obj) == 3


def test_execute_reuses_existing_mid_loop():    # Review Focus 1
    obj = _edit_object(_strip(rows=2), chain=[0, 1, 2, 3])
    v0, f0 = _counts(obj)
    assert _run(obj, width=0.5, chain_sides="+") == {'FINISHED'}
    assert _counts(obj) == (v0, f0)
    assert _selected_edges(obj) == {_edge_key((x, .5, 0), (x + 1, .5, 0)) for x in range(3)}


def test_execute_ngon_connector_and_crossing():
    obj = _edit_object(_ngon_diag(), chain=[0, 1, 2])
    _run(obj, width=0.25, chain_sides="+")
    assert _new_coords(obj) == _round_set([(0, .25, 0), (2, .25, 0), (3, .25, 0), (4, .25, 0)])
    assert _edge_between(obj, (2, 0, 0), (2, .25, 0))


def test_execute_sliver_skips_connector():
    obj = _edit_object(_sliver(), chain=[0, 1, 2])
    _run(obj, width=0.2, chain_sides="+")
    assert not _edge_between(obj, (1, -0.1, 0), (1, 0.1009975, 0))


def test_execute_pocket_wraps():
    obj = _edit_object(_pocket(), chain=[0, 1, 2, 3])
    _run(obj, width=0.5, chain_sides="+")
    assert _new_coords(obj) == _round_set([(0, .5, 0), (1, .5, 0), (1, .5, .15),
                                           (2, .5, .15), (2, .5, 0), (3, .5, 0)])


def test_execute_side_is_stored_not_viewed():   # Review Focus 3
    a = _edit_object(_pocket(), chain=[0, 1, 2, 3])
    assert _run(a, width=0.3, chain_sides="-") == {'FINISHED'}
    b = _edit_object(_pocket(), chain=[0, 1, 2, 3])
    assert _run(b, width=-0.3, chain_sides="+") == {'FINISHED'}
    assert _new_coords(a) and _new_coords(a) == _new_coords(b)
    assert all(y < 0 for _x, y, _z in _new_coords(a))


def test_execute_border_chain_skipped_others_cut():   # Review Focus 4
    obj = _edit_object(_strip_plus_border_chain(), chain=None)   # two selected chains
    assert _run(obj, width=0.25, chain_sides="++") == {'FINISHED'}
    assert len(_new_coords(obj)) == 4


def test_execute_non_planar_on_surface():       # Review Focus 5
    obj = _edit_object(_strip(lift=((0, 1, 0), 0.05)), chain=[0, 1, 2, 3])
    bvh = _bvh_before(obj)
    _run(obj, width=0.25, chain_sides="+")
    assert max(bvh.find_nearest(Vector(c))[3] for c in _new_coords(obj)) < 1e-6


def test_execute_interpolates_uvs():
    obj = _edit_object(_strip(uv=True), chain=[0, 1, 2, 3])
    _run(obj, width=0.25, chain_sides="+")
    assert all(abs(v - 0.25) < 1e-6 for v in _uv_v_of_new_verts(obj))


def test_execute_interpolates_uvs_at_face_points():   # face_split interpolates the vertex at (2, .25)
    obj = _edit_object(_add_uvs(_ngon_diag()), chain=[0, 1, 2])
    _run(obj, width=0.25, chain_sides="+")
    assert all(abs(v - 0.25) < 1e-6 for v in _uv_v_of_new_verts(obj))


def test_execute_two_edge_lip_projects_rail_to_rail():   # the middle lip vertex's anchor lies in the lid
    obj = _edit_object(_pocket_two_edge_lip(), chain=[0, 1, 2, 3, 4])
    assert _run(obj, width=0.5, chain_sides="+") == {'FINISHED'}
    assert _new_coords(obj) == _round_set([(0, .5, 0), (1, .5, 0), (1, .5, .15),
                                           (3, .5, .15), (3, .5, 0), (4, .5, 0)])
    assert _selected_edge_count(obj) == 5


def test_execute_pocket_far_from_origin():   # float32 coordinates near 1000 must not open gaps in the step cut
    for angle in (0.0, 30.0):                   # turned, the sheet's crossings are inexact in float32
        obj = _edit_object(_placed(_pocket(), (1000, 1000, 0), angle), chain=[0, 1, 2, 3])
        assert _run(obj, width=0.5, chain_sides="+") == {'FINISHED'}, angle
        assert len(_new_coords(obj)) == 6, angle


def test_execute_pocket_wraps_with_a_jittered_lip_corner():   # modelling noise at a step must not open a gap
    clean = _edit_object(_pocket(), chain=[0, 1, 2, 3])
    assert _run(clean, width=0.5, chain_sides="+") == {'FINISHED'}
    count = len(_new_coords(clean))
    # Off the lip's plane toward the pocket, the lid drops the faces under it (lid-region
    # tolerance); along the chain, the pieces under it miss each other (gap tolerance).
    for jitter in ((0.0, 4e-5, 0.0), (4e-5, 0.0, 0.0)):
        bm = _pocket()
        bm.verts[1].co += Vector(jitter)        # the lip corner
        obj = _edit_object(bm, chain=[0, 1, 2, 3])
        assert _run(obj, width=0.5, chain_sides="+") == {'FINISHED'}, jitter
        assert len(_new_coords(obj)) == count == 6, jitter


def test_execute_tilted_small_pocket_far_from_origin():   # the lid-region test must allow float32 steps
    # A 0.2 x 0.4 lid tilted about X and Y near (1000, 700, 400): its float32 coordinates are
    # about 6e-5 apart, more than the lid's own relative tolerance.
    for ax, ay in ((30.0, 20.0), (60.0, 50.0)):
        turn = Matrix.Rotation(math.radians(ay), 3, "Y") @ Matrix.Rotation(math.radians(ax), 3, "X")
        bm = _pocket()
        for v in bm.verts:
            v.co = turn @ (v.co * 0.2) + Vector((1000.0, 700.0, 400.0))
        bm.normal_update()
        obj = _edit_object(bm, chain=[0, 1, 2, 3])
        op = _OperatorStandIn(width=0.1, chain_sides="+")
        assert op.execute(bpy.context) == {'FINISHED'}, (ax, ay, op.reports)
        assert not op.reports, (ax, ay, op.reports)
        assert len(_new_coords(obj)) == 6, (ax, ay, _new_coords(obj))


def test_execute_pocket_with_uneven_flank_rails():   # a skewed lid must not drop the pocket faces past its far side
    bm = _pocket_uneven_flanks()
    build, err = bridge.build_band(bm, _chain(bm, [0, 1, 2, 3]), +1)
    assert err is None, err
    _close(core.Slider(build.band).limit(), 2.0, 1e-6)          # the lid runs on along the short flank's path
    obj = _edit_object(bm, chain=[0, 1, 2, 3])
    op = _OperatorStandIn(width=0.3, chain_sides="+")
    assert op.execute(bpy.context) == {'FINISHED'}, op.reports
    assert not op.reports, op.reports
    assert _new_coords(obj) >= _round_set([(1, .3, .15), (2, .3, .15)]), _new_coords(obj)


def test_execute_strip_passes_existing_mid_loop():
    obj = _edit_object(_strip(rows=2), chain=[0, 1, 2, 3])
    assert _run(obj, width=0.75, chain_sides="+") == {'FINISHED'}
    assert _new_coords(obj) == _round_set([(x, 0.75, 0.0) for x in range(4)])


def test_execute_pocket_beyond_the_short_flank():
    obj = _edit_object(_pocket_uneven_flanks(), chain=[0, 1, 2, 3])
    assert _run(obj, width=1.0, chain_sides="+") == {'FINISHED'}
    assert {(1.0, 1.0, 0.15), (2.0, 1.0, 0.15), (0.0, 1.0, 0.0), (3.0, 1.0, 0.0)} <= _new_coords(obj)


def test_execute_crosses_a_fold():
    obj = _edit_object(_fold_box(), chain=[0, 1, 2])
    assert _run(obj, width=1.4, chain_sides="+") == {'FINISHED'}
    assert _new_coords(obj) == _round_set([(x, 1.0, 0.4) for x in range(3)])


def test_execute_open_chain_keeps_inside_its_end_walls():
    obj = _edit_object(_grid(5, 4), chain=[6, 7, 8])
    assert _run(obj, width=1.5, chain_sides="+") == {'FINISHED'}
    assert _new_coords(obj) == _round_set([(x, 2.5, 0.0) for x in (1, 2, 3)])


def test_execute_wraps_onto_the_far_side_of_a_cube():
    obj = _edit_object(_cube_top_chain(), chain=None)   # 1×1×1 cube, top front edge selected
    assert _run(obj, width=1.5, chain_sides="+") == {'FINISHED'}
    assert _new_coords(obj) == _round_set([(-0.5, 0.5, 0.0), (0.5, 0.5, 0.0)])


def test_execute_connects_past_the_rail_path_end():
    # Vertex 9 moved sideways: edge 5 -> 9 leans 58 degrees off straight on, so the rail path of chain
    # vertex 1 ends at 5 and its new vertex goes on along the bisector to (1, .7), inside face 4-5-9-8.
    # A connecting edge from 5 keeps the strip in quads past the existing loop.
    bm = _strip(rows=2)
    bm.verts[9].co = (1.8, 1.0, 0.0)
    bm.normal_update()
    obj = _edit_object(bm, chain=[0, 1, 2, 3])
    assert _run(obj, width=0.7, chain_sides="+") == {'FINISHED'}
    assert _new_coords(obj) == _round_set([(0, .7, 0), (1, .7, 0), (1.32, .7, 0), (2, .7, 0), (3, .7, 0)])
    assert _edge_between(obj, (1, .5, 0), (1, .7, 0))


def test_execute_pocket_runs_on_past_the_lids_far_edge():   # the trace goes on over the far edge 5-6
    bm = _pocket_with_fold()
    build, err = bridge.build_band(bm, _chain(bm, [0, 1, 2, 3]), +1)
    assert err is None, err
    _close(core.Slider(build.band).limit(), 3.0, 1e-6)     # 2 across the ceiling and the lid, 1 down the fold
    obj = _edit_object(bm, chain=[0, 1, 2, 3])
    assert _run(obj, width=2.5, chain_sides="+") == {'FINISHED'}
    assert _round_set([(x, 2, -0.5) for x in range(4)]) <= _new_coords(obj), _new_coords(obj)


def test_slide_stops_at_a_fin():   # an edge three band faces hold is a border, as before the band ran on
    bm = _strip_with_fin()
    build, err = bridge.build_band(bm, _chain(bm, [0, 1, 2, 3]), +1)
    assert err is None, err
    # Past 0.5 the loop would cross the fin's edge 12-13; up to 2e-6 past it the anchors still snap onto 5 and 6.
    _close(core.Slider(build.band).limit(), 0.5, 1e-5)


def test_hidden_fin_is_no_border():   # hidden faces count as absent: the end fans cross the edge a hidden fin stands on
    bm = _sliver()
    v0, v2 = bm.verts[0], bm.verts[2]
    fin = [bm.verts.new((0, 0, 1)), bm.verts.new((2, 0, 1))]
    bm.faces.new((v0, v2, fin[1], fin[0])).hide = True
    bm.verts.ensure_lookup_table()
    bm.faces.ensure_lookup_table()
    build, err = bridge.build_band(bm, _chain(bm, [0, 1, 2]), +1)
    assert err is None, err
    assert sorted(build.band.faces) == [0, 1] and build.band.end_edges == (4, 3)


def test_strip_faces_skip_a_fin_inside_the_strip():   # the loop passes over the fin's edge 5-6; the fin is no strip face
    bm = _strip(rows=2)
    v5, v6 = bm.verts[5], bm.verts[6]
    fin = [bm.verts.new((1, .5, 1)), bm.verts.new((2, .5, 1))]
    bm.faces.new((v5, v6, fin[1], fin[0]))
    bm.verts.ensure_lookup_table()
    bm.faces.ensure_lookup_table()
    bm.normal_update()
    build, err = bridge.build_band(bm, _chain(bm, [0, 1, 2, 3]), +1)
    assert err is None, err
    applied = bridge.apply_cut(bm, build, core.Slider(build.band).solve(0.75))
    assert not applied.failures, applied.failures
    assert len(applied.strip_faces) == 6 and all(v.co.z == 0.0 for f in applied.strip_faces for v in f.verts)
    bm.free()


def test_execute_end_turns_onto_the_other_wall():   # the bridge twin of the core's walls_meet()
    obj = _edit_object(_walls_meet(), chain=[0, 1, 2, 3])
    assert _run(obj, width=0.5, chain_sides="+") == {'FINISHED'}
    h1 = (1.0 + 1.0 / math.sqrt(1.49)) / 2.0         # balanced width at 5, down the rail of 1
    h2 = (1.0 + 1.0 / math.sqrt(1.25)) / 2.0         # balanced width at 6, down the rail of 2
    expected = [
        ((0.5 * math.sqrt(1.49) - 0.3) / 0.7, 0.0, 0.0),   # the start, on 4-5: past the meeting vertex 4
        (1.0, 1.0 - 0.5 / h1, 0.0),
        (2.0 - 0.25 / h2, 1.0 - 0.5 / h2, 0.0),
        (2.5 - 0.5 * math.sqrt(1.25), 0.0, 0.0),           # the end, on 3-6
    ]
    found = sorted(_new_coords(obj))
    assert len(found) == 4 and all(math.dist(p, q) < 1e-5 for p, q in zip(expected, found)), found
    bm = _walls_meet()
    build, err = bridge.build_band(bm, _chain(bm, [0, 1, 2, 3]), +1)
    assert err is None and build.band.end_edges == (4, 6), err
    applied = bridge.apply_cut(bm, build, core.Slider(build.band).solve(0.5))
    assert not applied.failures, applied.failures
    assert len(applied.strip_faces) == 3                  # above the walls along y = 0, not the row below
    assert all(v.co.y >= -1e-6 for f in applied.strip_faces for v in f.verts)
    bm.free()


def test_execute_reports_an_incomplete_cut():   # a failure once editing began still finishes the edit
    obj = _edit_object(_strip(), chain=[0, 1, 2, 3])
    split, calls = bridge._split_face, []

    def fail_second_piece(va, vb, coords):
        calls.append(None)
        return None if len(calls) == 2 else split(va, vb, coords)

    op = _OperatorStandIn(width=0.25, chain_sides="+")
    bridge._split_face = fail_second_piece
    try:
        result = op.execute(bpy.context)
    finally:
        bridge._split_face = split
    assert result == {'FINISHED'}
    assert any(r.startswith("Smart Edge Slide: chain cut incomplete (") for r in op.reports), op.reports
    assert _evaluated_vertex_count(obj) == 12                      # update_edit_mesh ran
    assert _selected_edges(obj) == {_edge_key((0, .25, 0), (1, .25, 0)), _edge_key((2, .25, 0), (3, .25, 0))}
    assert not _validate_fixed_something(obj)


def _failing_second_solve(error):
    """A stand-in for ``core.Slider.solve`` that raises ``error`` on its second call."""
    solve, calls = core.Slider.solve, []

    def solve_or_fail(slider, width, **kwargs):
        calls.append(None)
        if len(calls) == 2:
            raise error
        return solve(slider, width, **kwargs)

    return solve, solve_or_fail


def test_execute_keeps_the_first_cut_when_a_later_chain_raises():   # the update contract holds for any error
    first_cut = _round_set([(x, 0.25, 0.0) for x in range(4)])
    obj = _edit_object(_two_strips(), chain=None)
    solve, failing = _failing_second_solve(RuntimeError("trace did not terminate"))
    op = _OperatorStandIn(width=0.25, chain_sides="++")
    core.Slider.solve = failing
    try:
        result = op.execute(bpy.context)
    finally:
        core.Slider.solve = solve
    assert result == {'FINISHED'}, op.reports
    assert "Smart Edge Slide: chain skipped (trace did not terminate)" in op.reports, op.reports
    assert _new_coords(obj) == first_cut
    assert _evaluated_vertex_count(obj) == 20                      # update_edit_mesh ran
    assert not _validate_fixed_something(obj)

    # An error no chain skip covers still escapes, but only after the mesh update.
    obj = _edit_object(_two_strips(), chain=None)
    solve, failing = _failing_second_solve(KeyError("unexpected"))
    core.Slider.solve = failing
    try:
        _OperatorStandIn(width=0.25, chain_sides="++").execute(bpy.context)
        raise AssertionError("the KeyError was swallowed")
    except KeyError:
        pass
    finally:
        core.Slider.solve = solve
    assert _evaluated_vertex_count(obj) == 20 and _new_coords(obj) == first_cut


def test_preview_skips_a_chain_whose_solve_raises():
    obj = _edit_object(_two_strips(), chain=None)
    op = _OperatorStandIn(width=0.25, chain_sides="++", _preview_key=None)
    op._bm = bmesh.from_edit_mesh(obj.data)
    assert op._build_sides(op._bm)
    solve, failing = _failing_second_solve(ZeroDivisionError("float division by zero"))
    core.Slider.solve = failing
    try:
        op._rebuild_preview()
    finally:
        core.Slider.solve = solve
    assert {_key(p)[1] for p in op._preview_segs} == {0.25}         # the first chain only


def test_execute_loop_inside_one_face_is_skipped():   # no vertex or edge to start a face split from
    obj = _edit_object(_mesh([(0, 0, 0), (2, 0, 0), (2, 2, 0), (0, 2, 0)], [(0, 1, 2, 3)]), chain=[0, 1, 2, 3, 0])
    before = _counts(obj)
    op = _OperatorStandIn(width=0.25, chain_sides="+")
    assert op.execute(bpy.context) == {'CANCELLED'}
    assert "Smart Edge Slide: chain skipped (the loop lies inside one face; use Smart Inset)" in op.reports, op.reports
    assert _counts(obj) == before


def test_preview_layers_match_apply():
    bm = _pocket()
    src = _chain(bm, [0, 1, 2, 3])
    build, _ = bridge.build_band(bm, src, +1)
    cut = core.Slider(build.band).solve(0.5)
    segs, pts, clamped = bridge.preview_layers([build], [cut])
    assert not clamped and len(segs) == 2 * 5
    assert _round_set(pts) >= _round_set([(1, .5, .15), (2, .5, .15)])


def test_preview_layers_close_a_ring():           # a closed loop also draws its last-to-first segment
    bm = _ring()
    build, _ = bridge.build_band(bm, bridge.ChainSrc(verts=[bm.verts[i] for i in range(4)], closed=True, index=0), +1)
    segs, pts, clamped = bridge.preview_layers([build], [core.Slider(build.band).solve(0.5)])
    assert not clamped and len(segs) == 2 * 4
    assert _round_set(pts) == _round_set([(-1.5, -1.5, 0), (1.5, -1.5, 0), (1.5, 1.5, 0), (-1.5, 1.5, 0)])


def test_snap_candidates_cover_band_and_step_region():
    bm = _pocket()
    build, _ = bridge.build_band(bm, _chain(bm, [0, 1, 2, 3]), +1)
    cos = _round_set([v.co for v, _c, _s in bridge.snap_candidates([build])])
    assert (1.0, 0.0, 0.15) in cos and (0.0, 2.0, 0.0) in cos


def test_snap_to_a_vertex_under_a_lid():          # it stands for its projection onto the lid
    bm = _pocket_mid_row()
    build, _ = bridge.build_band(bm, _chain(bm, [0, 1, 2, 3]), +1)
    mid = next(v for v in bm.verts if _key(v.co) == (1.5, 1.0, 0.15))
    assert (mid, 0, 1) in bridge.snap_candidates([build])
    target = bridge.snap_target(build, mid)
    assert target.kind == "face" and target.face == build.steps[0].lid and _key(target.co) == (1.5, 1.0, 0.0)
    assert abs(core.Slider(build.band).snap_width(target) - 1.0) < 1e-6
    corner = bridge.snap_target(build, bm.verts[4])               # a band vertex is itself
    assert corner.kind == "vert" and corner.vert == 4


def test_modal_invoke_path_smoke():
    """What invoke builds and the modal then uses: both sides' bands and Sliders, the preview,
    the Ctrl snap width and the HUD and help overlays. Headless there is no viewport region, so
    the view-based side choice, the draw callback and the event loop itself are not run."""
    region = None if bpy.app.background else bpy.context.region
    obj = _edit_object(_pocket(), chain=[0, 1, 2, 3])
    op = _OperatorStandIn(width=0.5, chain_sides="+", _preview_key=None, _input_str="")
    op._bm = bmesh.from_edit_mesh(obj.data)    # held as invoke holds it: freeing it frees its elements
    assert op._build_sides(op._bm)
    assert [sorted(found) for found in op._sides] == [[-1, 1]]     # the pocket side and the slanted side
    op._rebuild_preview()
    assert len(op._preview_segs) == 2 * 5 and not op._clamped
    op.width = -0.5                                                # the slanted side
    op._rebuild_preview()
    assert op._preview_segs and all(p.y < 0 for p in op._preview_segs)

    op._build_overlays(region)
    assert op._hud.title == "Smart Edge Slide"
    params = [p for section in op._hud.param_sections for p in section.params]
    assert [p.name for p in params] == ["Width", "Exact Width (E)", "Allow Collapse (C)", "UV Stripe (U)", "Clamped"]
    assert all(p.value_text() != "?" for p in params)              # every getter runs
    assert [(it.label, it.key) for it in op._help.sections[0].items] == [
        ("Adjust width", "Mouse / Type"), ("Snap to vertex", "Ctrl"), ("Exact width", "E"),
        ("Allow collapse", "C"), ("UV Stripe", "U"), ("Flip chain side", "F"),
        ("Confirm", "LMB / Enter"), ("Cancel", "Esc / RMB"), ("Help / Toggle HUD", "H")]
    assert op._status_text().startswith("Smart Edge Slide: width = -0.5000")

    strip = _edit_object(_strip(rows=2), chain=[0, 1, 2, 3])
    op = _OperatorStandIn(chain_sides="+")
    op._bm = bmesh.from_edit_mesh(strip.data)
    assert op._build_sides(op._bm)
    op._prepare_snap()
    k = next(k for k, (_kind, co) in enumerate(op._snap_points) if _key(co) == (1.0, 0.5, 0.0))
    assert abs(op._snap_width(k) - 0.5) < 1e-6
    op.chain_sides = "-"                                           # a positive width now cuts the other side
    assert abs(op._snap_width(k) + 0.5) < 1e-6


def test_modal_u_toggles_uv_stripe_and_cancel_restores():
    obj = _edit_object(_strip(), chain=[0, 1, 2, 3])
    op = _OperatorStandIn(chain_sides="+", use_uv_stripe=False, _preview_key=None, _input_str="")
    op._bm = bmesh.from_edit_mesh(obj.data)
    assert op._build_sides(op._bm)
    op._build_overlays(None if bpy.app.background else bpy.context.region)
    # The cancel snapshot invoke() takes; invoke() itself needs a viewport.
    op._cancel_width, op._cancel_use_exact, op._cancel_use_collapse = op.width, op.use_exact, op.use_collapse
    op._cancel_use_uv_stripe, op._cancel_chain_sides = op.use_uv_stripe, op.chain_sides
    assert op._modal(bpy.context, _KeyPress("U")) == {'RUNNING_MODAL'} and op.use_uv_stripe is True
    assert "UV stripe = on (U)" in op._status_text()
    assert op._modal(bpy.context, _KeyPress("ESC")) == {'CANCELLED'} and op.use_uv_stripe is False


def test_modal_mouse_then_typing_then_mouse():   # clearing the typed value hands the width back without a jump
    _edit_object(_strip(), chain=[0, 1, 2, 3])
    op, ctx = _invoke(x=0, width=0.05)
    _close(op._pixel_to_width, 0.0025)                   # a quarter of the unit chain edges per 100 px
    op._modal(ctx, _move(40))
    _close(op.width, 0.15)
    _keys(op, ctx, "PERIOD TWO", x=40)
    assert op._input_str == ".2" and op.width == 0.2
    op._modal(ctx, _move(80))                            # typed input holds the width
    assert op.width == 0.2
    _keys(op, ctx, "BACK_SPACE", x=80)
    assert op._input_str == "." and op.width == 0.2
    _keys(op, ctx, "BACK_SPACE", x=80)
    assert op._input_str == "" and op.width == 0.2
    op._modal(ctx, _move(100))                           # the drag goes on from the typed value
    _close(op.width, 0.25)
    assert {_key(p)[1] for p in op._preview_segs} == {0.25}
    op._finish(ctx)


def test_modal_shift_precision_hands_over_without_jumps():
    _edit_object(_strip(), chain=[0, 1, 2, 3])
    op, ctx = _invoke(x=0, width=0.05)
    op._modal(ctx, _move(40))
    _close(op.width, 0.15)
    op._modal(ctx, _move(40, shift=True))                # Shift anchors where it is pressed
    _close(op.width, 0.15)
    op._modal(ctx, _move(140, shift=True))               # a tenth of the speed
    _close(op.width, 0.175)
    op._modal(ctx, _move(140))                           # releasing Shift keeps the value
    _close(op.width, 0.175)
    op._modal(ctx, _move(180))                           # full speed from there
    _close(op.width, 0.275)
    op._finish(ctx)

    # Shift released without a move keeps its anchor; typing and clearing must drop it.
    for typed, clear in (("PERIOD THREE", "BACK_SPACE BACK_SPACE"), ("MINUS", "MINUS")):
        op, ctx = _invoke(x=0, width=0.05)
        op._modal(ctx, _move(0, shift=True))
        op._modal(ctx, _move(100, shift=True))
        _close(op.width, 0.075)
        assert op._modal(ctx, _event("LEFT_SHIFT", 100, value="RELEASE")) == {'RUNNING_MODAL'}
        _keys(op, ctx, typed, x=100)
        op._modal(ctx, _move(300))                       # typing holds the width while the mouse moves on
        _keys(op, ctx, clear, x=300)
        assert op._input_str == "", typed
        held = op.width                                  # 0.3 typed, or 0.075 when only "-" was typed
        op._modal(ctx, _move(300, shift=True))           # Shift again: a new anchor, not the old one
        _close(op.width, held)
        op._modal(ctx, _move(400, shift=True))
        _close(op.width, held + 0.025)
        op._finish(ctx)


def test_modal_ctrl_snap_and_release_reanchors():
    _edit_object(_strip(rows=2), chain=[0, 1, 2, 3])
    op, ctx = _invoke(x=0, width=0.05)
    op._mouse_world = lambda _ctx, _mouse: Vector((1.0, 0.5, 0.0))     # the cursor on a mid-row vertex
    op._modal(ctx, _move(40))
    _close(op.width, 0.15)
    op._modal(ctx, _move(60, ctrl=True))
    _close(op.width, 0.5)
    assert op._snapping and _key(op._snap_co) == (1.0, 0.5, 0.0)
    op._modal(ctx, _move(90, ctrl=True))                 # the snap holds while Ctrl is down
    _close(op.width, 0.5)
    op._modal(ctx, _move(90))                            # Ctrl released: the snapped width stays
    _close(op.width, 0.5)
    assert not op._snapping and op._snap_co is None
    op._modal(ctx, _move(130))                           # and the drag goes on from there
    _close(op.width, 0.6)
    op._finish(ctx)


def test_modal_ctrl_snap_measures_against_the_nearest_chain():
    _edit_object(_strip_between_two_chains(0.7), chain=None)
    op, ctx = _invoke(x=0, width=0.05)
    assert op.chain_sides == "+-"                        # the upper chain's faces lie on its -1 side
    op._mouse_world = lambda _ctx, _mouse: Vector((1.0, 0.7, 0.0))     # 0.7 above one chain, 0.3 below the other
    op._modal(ctx, _move(100, 70, ctrl=True))
    _close(op.width, 0.3, 1e-6)                          # the upper chain is nearer on screen
    op._to_region = lambda _ctx, co: (co.x * 100.0, co.y * co.y * 100.0)   # a view that squeezes the lower half
    op._modal(ctx, _move(100, 49, ctrl=True))
    _close(op.width, 0.7, 1e-6)                          # now the lower chain is nearer on screen
    op._finish(ctx)


def _top_view(lo=-2.0, hi=22.0, size=1200):
    """A stand-in top-down orthographic view: object x and y in [lo, hi] fill a ``size`` pixel square region.

    Returns (context for invoke() and the modal, object point -> region pixel).
    """
    s = 2.0 / (hi - lo)
    pm = Matrix(((s, 0, 0, -1.0 - s * lo), (0, s, 0, -1.0 - s * lo), (0, 0, -0.01, 0), (0, 0, 0, 1)))
    rv3d = SimpleNamespace(perspective_matrix=pm, window_matrix=pm, is_perspective=False, view_matrix=Matrix())
    region = SimpleNamespace(width=size, height=size, x=0, y=0, as_pointer=lambda: 0)
    ctx = _modal_context()
    ctx.region, ctx.region_data, ctx.space_data = region, rv3d, SimpleNamespace(region_3d=rv3d)

    def to_px(co):
        return round(size * (co[0] - lo) / (hi - lo)), round(size * (co[1] - lo) / (hi - lo))

    return ctx, to_px


def test_modal_ctrl_snap_ranks_only_the_vertices_near_the_cursor():
    # Every band vertex is a snap candidate. With a view, the screen ranking runs over the few in its reach,
    # and picks what the ranking over all of them picks.
    from InteractionOps.utils import picking
    obj = _edit_object(_grid(21, 21), chain=[10 * 21 + x for x in range(5, 16)])
    ctx, to_px = _top_view()
    op = _OperatorStandIn(width=0.05)
    assert op.invoke(ctx, _move(0)) == {'RUNNING_MODAL'}
    assert len(op._snap_points) == 21 * 21 - 11                     # both bands flood the whole grid
    ranked, rank = [], picking.closest_snap_point
    picking.closest_snap_point = lambda c, points, *a, **kw: (ranked.append(len(points)), rank(c, points, *a, **kw))[1]
    try:
        # 50 pixels a unit: (14.5, 11.1) lies halfway between (14, 11) and (15, 11); (3.5, 3.5) is out of every
        # vertex's reach.
        for at, width in (((7.3, 13.2), 3.0), ((12.0, 16.0), 6.0), ((9.8, 4.3), -6.0), ((14.5, 11.1), 1.0),
                          ((3.5, 3.5), None)):
            hit = Vector((*at, 0.0))
            op._mouse_world = lambda _ctx, _mouse, hit=hit: hit
            mouse = to_px(at)
            op._modal(ctx, _move(*mouse, ctrl=True))
            want = rank(ctx, op._snap_points, obj.matrix_world, mouse, hit)
            if width is None:
                assert want is None and op._snap_co is None, at
            else:
                assert want is not None and op._snap_co is want[1], at
                _close(op.width, width, 1e-6)
    finally:
        picking.closest_snap_point = rank
        op._finish(ctx)
    assert len(ranked) == 5 and max(ranked) < 20, ranked


def test_modal_f_flips_the_nearest_chain():   # chain indices skip the chain without a band
    _edit_object(_wire_and_two_strips(), chain=None)
    op, ctx = _invoke(x=0, width=0.25)
    assert [sorted(found) for found in op._sides] == [[], [-1, 1], [-1, 1]] and op.chain_sides == "+++"
    _keys(op, ctx, "F", x=150, y=1000)                   # on the chain at y = 10
    assert op.chain_sides == "++-"
    assert {_key(p)[1] for p in op._preview_segs} == {0.25, 9.75}
    _keys(op, ctx, "F", x=150, y=20)                     # near the chain at y = 0
    assert op.chain_sides == "+--"
    assert {_key(p)[1] for p in op._preview_segs} == {-0.25, 9.75}
    op._finish(ctx)


def test_modal_f_keeps_a_one_sided_chain():
    _edit_object(_strip(), chain=[0, 1, 2, 3])           # faces on the +1 side only
    op, ctx = _invoke(x=0, width=0.25)
    assert op.chain_sides == "+" and op._preview_segs
    _keys(op, ctx, "F", x=150, y=0)
    assert op.chain_sides == "+" and op._preview_segs    # not flipped onto the side without faces
    assert "faces on one side only" in op._status_text()
    _keys(op, ctx, "E", x=150, y=0)                      # the next key clears the hint
    assert "faces on one side only" not in op._status_text()
    op._finish(ctx)


def test_modal_esc_restores_every_prop():
    obj = _edit_object(_wire_and_two_strips(), chain=None)
    before = _counts(obj)
    op, ctx = _invoke(x=0, width=0.05, chain_sides="")
    op._modal(ctx, _move(80))
    _keys(op, ctx, "E C U", x=80)
    _keys(op, ctx, "F", x=150, y=1000)
    props = (op.width, op.use_exact, op.use_collapse, op.use_uv_stripe, op.chain_sides)
    assert props[1:] == (True, True, True, "++-") and abs(props[0] - 0.25) < 1e-9, props
    assert op._modal(ctx, _event("ESC", 150, 1000)) == {'CANCELLED'}
    assert (op.width, op.use_exact, op.use_collapse, op.use_uv_stripe, op.chain_sides) == (
        0.05, False, False, False, "")
    assert op._handle is None and op._sides == [] and op._bm is None
    assert _counts(obj) == before


def test_modal_enter_confirms_through_execute():
    obj = _edit_object(_strip(), chain=[0, 1, 2, 3])
    op, ctx = _invoke(x=0, width=0.05)
    _keys(op, ctx, "PERIOD TWO FIVE")
    assert op._modal(ctx, _event("RET")) == {'FINISHED'}
    assert op._handle is None and op._bm is None and not op.reports
    assert _new_coords(obj) == _round_set([(x, 0.25, 0.0) for x in range(4)])
    assert _selected_edge_count(obj) == 3


def test_uv_stripe_fit_strip():
    obj = _edit_object(_strip(uv=True), chain=[0, 1, 2, 3])
    _run(obj, width=0.25, chain_sides="+", use_uv_stripe=True)
    uvs = _strip_corner_uvs(obj)                 # {(rounded co): set of uv} for strip faces
    assert uvs[(0.0, 0.0, 0.0)] == {(0.0, 0.0)} and uvs[(3.0, 0.25, 0.0)] == {(1.0, 0.083333)}


def test_uv_stripe_fit_pocket_is_a_rectangle():
    obj = _edit_object(_pocket(), chain=[0, 1, 2, 3])
    _run(obj, width=0.5, chain_sides="+", use_uv_stripe=True)
    us, vs = _strip_uv_ranges(obj)
    assert us == (0.0, 1.0) and vs == (0.0, 0.15873)


def test_uv_stripe_in_place():
    obj = _edit_object(_strip(uv="half"), chain=[0, 1, 2, 3])   # u = x/2, v = y/2
    _run(obj, width=0.25, chain_sides="+", use_uv_stripe=True, uv_stripe_mode="IN_PLACE")
    us, vs = _strip_uv_ranges(obj)
    assert us == (0.0, 1.5) and vs == (0.0, 0.125)


def test_uv_stripe_creates_missing_layer():
    obj = _edit_object(_strip(), chain=[0, 1, 2, 3])            # no UV layer
    _run(obj, width=0.25, chain_sides="+", use_uv_stripe=True)
    assert len(obj.data.uv_layers) == 1


def test_uv_stripe_in_place_without_uvs_fits():   # no old UVs to place by: Fit 0-1 instead
    obj = _edit_object(_strip(), chain=[0, 1, 2, 3])
    _run(obj, width=0.25, chain_sides="+", use_uv_stripe=True, uv_stripe_mode="IN_PLACE")
    assert _strip_uv_ranges(obj) == ((0.0, 1.0), (0.0, 0.083333))


def test_uv_stripe_fit_stacks_chains():           # one strip per chain, stacked upward with a 0.01 gap
    obj = _edit_object(_two_strips(), chain=None)
    assert _run(obj, width=0.25, chain_sides="++", use_uv_stripe=True) == {'FINISHED'}
    assert _strip_uv_ranges(obj, 0.0, 0.25) == ((0.0, 1.0), (0.0, 0.083333))
    assert _strip_uv_ranges(obj, 5.0, 5.25) == ((0.0, 1.0), (0.093333, 0.176667))


def test_uv_stripe_in_place_keeps_each_strip_in_its_own_place():   # one UV context per strip
    def strip_ranges(use_uv_stripe):
        obj = _edit_object(_add_uvs(_two_strips(), 0.5), chain=None)   # u = x/2, v = y/2
        assert _run(obj, width=0.25, chain_sides="++", use_uv_stripe=use_uv_stripe,
                    uv_stripe_mode="IN_PLACE") == {'FINISHED'}
        return [_strip_uv_ranges(obj, low, low + 0.25) for low in (0.0, 5.0)]

    def centre(ranges):
        (u0, u1), (v0, v1) = ranges
        return (u0 + u1) / 2.0, (v0 + v1) / 2.0

    before, after = strip_ranges(False), strip_ranges(True)   # without UV Stripe: the cut's own UVs
    for old, new in zip(before, after):
        assert all(abs(a - b) <= 1e-5 for a, b in zip(centre(old), centre(new))), (old, new)
    (au, av), (bu, bv) = after
    assert av[1] < bv[0] or bv[1] < av[0] or au[1] < bu[0] or bu[1] < au[0], after   # no overlap


def test_uv_stripe_other_side_is_not_mirrored():   # the "-" side's faces run the chain backward
    obj = _edit_object(_strip(reverse=True), chain=[0, 1, 2, 3])
    assert _run(obj, width=0.25, chain_sides="-", use_uv_stripe=True) == {'FINISHED'}
    areas = _uv_areas(obj, lambda cos: all(-1e-6 <= y <= 0.25 + 1e-6 for _x, y, _z in cos))
    assert len(areas) == 3 and all(a > 0.0 for a in areas), areas
    assert _strip_uv_ranges(obj) == ((0.0, 1.0), (0.0, 0.083333))


def test_uv_stripe_closed_seam_collapse():   # anchors [3, 0, 1, 3]: the rungs start mid-way round the loop
    obj = _edit_object(_add_uvs(_seam_ring()), chain=[0, 1, 2, 3, 0])
    op = _OperatorStandIn(width=0.9, chain_sides="+", use_collapse=True, use_uv_stripe=True)
    assert op.execute(bpy.context) == {'FINISHED'}
    assert not any("UV Stripe skipped" in r for r in op.reports), op.reports
    inner = _round_set([(4, -0.3, 0), (7, -0.5, 0), (7, 0.5, 0), (4, 0.3, 0)])
    areas = _uv_areas(obj, lambda cos: not inner & set(cos))     # the faces between the chain and the new loop
    assert len(areas) >= 4 and all(a > 0.0 for a in areas), areas
    uvs = _read(obj, lambda bm: [lp[bm.loops.layers.uv.active].uv.copy() for f in bm.faces
                                 if not inner & {_key(v.co) for v in f.verts} for lp in f.loops])
    assert min(uv.x for uv in uvs) > -1e-6 and max(uv.x for uv in uvs) < 1.0 + 1e-6
    assert min(uv.y for uv in uvs) > -1e-6


def test_uv_stripe_skips_a_strip_its_layout_rejects():   # stripe_for tries the layout before any UV is written
    obj = _edit_object(_two_strips(), chain=None)
    stripe_uvs = bridge.uv_stripe_core.stripe_uvs

    def reject_first_strip(strip):
        if 0 in strip.near:
            raise ValueError("layout rejected")
        return stripe_uvs(strip)

    op = _OperatorStandIn(width=0.25, chain_sides="++", use_uv_stripe=True)
    bridge.uv_stripe_core.stripe_uvs = reject_first_strip
    try:
        result = op.execute(bpy.context)
    finally:
        bridge.uv_stripe_core.stripe_uvs = stripe_uvs
    assert result == {'FINISHED'}
    assert "Smart Edge Slide: UV Stripe skipped (layout rejected)" in op.reports, op.reports
    assert _strip_uv_ranges(obj, 5.0, 5.25) == ((0.0, 1.0), (0.0, 0.083333))   # the other strip, fitted alone


def test_apply_stripes_without_contexts_fits():   # Smart Inset calls it Fit-only
    bm = _strip()
    build, _ = bridge.build_band(bm, _chain(bm, [0, 1, 2, 3]), +1)
    applied = bridge.apply_cut(bm, build, core.Slider(build.band).solve(0.25))
    bm.verts.index_update()
    bm.faces.index_update()
    strip, faces = bridge.stripe_for(build, applied, 0.25)
    try:
        stripe_bridge.apply_stripes(bm, [strip], faces, "IN_PLACE", contexts=[])
        raise AssertionError("a contexts list of the wrong length was accepted")
    except ValueError:
        pass
    assert not bm.loops.layers.uv                                  # refused before writing anything
    stripe_bridge.apply_stripes(bm, [strip], faces, "IN_PLACE")    # no contexts: every strip fits 0-1
    layer = bm.loops.layers.uv.active
    us = [lp[layer].uv.x for f in applied.strip_faces for lp in f.loops]
    assert (round(min(us), 6), round(max(us), 6)) == (0.0, 1.0)
    bm.free()


TESTS = [
    test_collect_chains_orders_and_rejects_branching,
    test_collect_chains_closed_and_reversed_order,
    test_build_band_strip_side,
    test_hidden_side_face_skips_chain,
    test_box_corner_has_no_step,
    test_pocket_lip_becomes_lid,
    test_build_band_takes_the_mesh_triangles,
    test_bands_share_one_triangulation,
    test_l_region_border_turns_are_not_steps,
    test_pocket_lid_replaces_pocket_faces,
    test_pocket_region_skips_hidden_faces,
    test_pocket_lid_bridges_hidden_side_walls,
    test_hidden_corner_quad_interrupts_wedge,
    test_border_gap_at_chain_vertex_interrupts_wedge,
    test_side_faces_in_different_sectors_skip_chain,
    test_two_faces_on_one_side_skip_chain,
    test_sliver_end_wedges_cross_the_shallow_chord,
    test_chain_end_inside_the_mesh_stops_at_its_end_walls,
    test_build_band_floods_the_side_and_names_its_end_edges,
    test_pocket_lid_follows_the_flank_rail_paths,
    test_strip_faces_stop_at_the_end_walls,
    test_strip_faces_need_bounded_ends,
    test_step_region_stops_at_the_lids_far_side,
    test_lid_path_stops_where_the_straightest_edge_leaves_the_plane,
    test_lid_paths_stop_where_they_meet,
    test_lid_tolerance_takes_the_first_corners,
    test_ngon_band_keeps_the_wedge_face,
    test_execute_strip,
    test_execute_reuses_existing_mid_loop,
    test_execute_ngon_connector_and_crossing,
    test_execute_sliver_skips_connector,
    test_execute_pocket_wraps,
    test_execute_side_is_stored_not_viewed,
    test_execute_border_chain_skipped_others_cut,
    test_execute_non_planar_on_surface,
    test_execute_interpolates_uvs,
    test_execute_interpolates_uvs_at_face_points,
    test_execute_two_edge_lip_projects_rail_to_rail,
    test_execute_pocket_far_from_origin,
    test_execute_pocket_wraps_with_a_jittered_lip_corner,
    test_execute_tilted_small_pocket_far_from_origin,
    test_execute_pocket_with_uneven_flank_rails,
    test_execute_strip_passes_existing_mid_loop,
    test_execute_pocket_beyond_the_short_flank,
    test_execute_crosses_a_fold,
    test_execute_open_chain_keeps_inside_its_end_walls,
    test_execute_wraps_onto_the_far_side_of_a_cube,
    test_execute_connects_past_the_rail_path_end,
    test_execute_pocket_runs_on_past_the_lids_far_edge,
    test_slide_stops_at_a_fin,
    test_hidden_fin_is_no_border,
    test_strip_faces_skip_a_fin_inside_the_strip,
    test_execute_end_turns_onto_the_other_wall,
    test_execute_reports_an_incomplete_cut,
    test_execute_keeps_the_first_cut_when_a_later_chain_raises,
    test_preview_skips_a_chain_whose_solve_raises,
    test_execute_loop_inside_one_face_is_skipped,
    test_preview_layers_match_apply,
    test_preview_layers_close_a_ring,
    test_snap_candidates_cover_band_and_step_region,
    test_snap_to_a_vertex_under_a_lid,
    test_modal_invoke_path_smoke,
    test_modal_u_toggles_uv_stripe_and_cancel_restores,
    test_modal_mouse_then_typing_then_mouse,
    test_modal_shift_precision_hands_over_without_jumps,
    test_modal_ctrl_snap_and_release_reanchors,
    test_modal_ctrl_snap_measures_against_the_nearest_chain,
    test_modal_ctrl_snap_ranks_only_the_vertices_near_the_cursor,
    test_modal_f_flips_the_nearest_chain,
    test_modal_f_keeps_a_one_sided_chain,
    test_modal_esc_restores_every_prop,
    test_modal_enter_confirms_through_execute,
    test_uv_stripe_fit_strip,
    test_uv_stripe_fit_pocket_is_a_rectangle,
    test_uv_stripe_in_place,
    test_uv_stripe_creates_missing_layer,
    test_uv_stripe_in_place_without_uvs_fits,
    test_uv_stripe_fit_stacks_chains,
    test_uv_stripe_in_place_keeps_each_strip_in_its_own_place,
    test_uv_stripe_other_side_is_not_mirrored,
    test_uv_stripe_closed_seam_collapse,
    test_uv_stripe_skips_a_strip_its_layout_rejects,
    test_apply_stripes_without_contexts_fits,
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
