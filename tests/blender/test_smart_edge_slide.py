"""Headless tests of Smart Edge Slide on real BMesh data: the bridge (chains
from the selection, band sides, wedge faces and step lids) and the operator's
execute(). Run from the repo root via:

    blender --background --factory-startup --python-exit-code 1 --python tests/blender/test_smart_edge_slide.py

No viewport is needed: the bridge tests build their own bmesh, the execute()
tests put each mesh in an object of its own and run the operator in Edit Mode.
The destructive mode's tests build the pure-Python band fixtures
(tests/smart_edge_slide_fixtures.py) as meshes and apply WaveSlider cuts.

Not collected by pytest (tests/conftest.py ignores tests/blender).
"""
import dataclasses
import importlib
import math
import os
import struct
import sys
import time
import traceback
from types import SimpleNamespace

import bmesh
import bpy
from mathutils import Matrix, Vector
from mathutils.bvhtree import BVHTree

if os.path.dirname(os.path.abspath(__file__)) not in sys.path:   # the helper module beside this script
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import smart_edge_slide_topology as topology

ADDON = "InteractionOps"

bridge = None
core = None
operator = None
stripe_bridge = None
wave = None
fixtures = None


def enable_addon():
    global bridge, core, operator, stripe_bridge, wave, fixtures
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
    from InteractionOps.utils import smart_edge_slide_wave as _wave
    bridge = _bridge
    core = _core
    operator = IOPS_OT_smart_edge_slide
    stripe_bridge = _stripe_bridge
    wave = _wave
    fixtures = _import_fixtures(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _import_fixtures(tests_dir):
    """tests/smart_edge_slide_fixtures.py, the pure-Python band fixtures, built on the add-on's own core.

    pytest runs them from the repo root, where they import ``utils.smart_edge_slide_core``. Here ``utils`` and
    its loaded modules are aliased to the add-on's own ``InteractionOps.utils``, so the fixtures build the
    add-on's ``Band``: one class identity, and the core is never loaded twice.
    """
    package = importlib.import_module(f"{ADDON}.utils")
    assert sys.modules.setdefault("utils", package) is package, "another top-level utils module is loaded"
    for name, module in list(sys.modules.items()):
        if name.startswith(f"{ADDON}.utils."):
            sys.modules.setdefault(name[len(ADDON) + 1:], module)
    if tests_dir not in sys.path:
        sys.path.insert(0, tests_dir)
    return importlib.import_module("smart_edge_slide_fixtures")


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


def _shallow_end():
    """Chain 0-1-2-3 along y = 0 whose start end edge 0-4 leaves it at 45 degrees.

    Vertex 4 is (1, 1): the edge 0->4 is (1, 1), atan2(1, 1) = 45 degrees off the chain edge (+x). Face 0 is the
    parallelogram 0, 1, 5, 4 with 5 = (2, 1), so the edge 0-4 is mesh border and the start fan ends there with no
    end edge until ``end_edge`` drops under 45. The far end is a right angle: face 2 is the triangle 2, 3, 6 with
    6 = (3, 1), whose edge 3-6 leaves the chain at 90 degrees, past any ``end_edge``."""
    points = [(0, 0, 0), (1, 0, 0), (2, 0, 0), (3, 0, 0), (1, 1, 0), (2, 1, 0), (3, 1, 0)]
    return _mesh(points, [(0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 6)])


def _bent_rows(deg):
    """The core's strip2_bent(deg): strip2 with vertex 9 placed so the rail path 1-5-9 bends ``deg`` degrees at 5."""
    points = [(x, r / 2, 0.0) for r in range(3) for x in range(4)]
    points[9] = (1.0 + 0.5 * math.tan(math.radians(deg)), 1.0, 0.0)
    faces = [(4 * r + x, 4 * r + x + 1, 4 * r + x + 5, 4 * r + x + 4) for r in range(2) for x in range(3)]
    return _mesh(points, faces)


def _one_face(points):
    """One flat n-gon over ``points`` (x, y), counter-clockwise: the band of the closed chain round it, side +1."""
    return _mesh([(x, y, 0.0) for x, y in points], [tuple(range(len(points)))])


def _l_ngon():
    """An L-shaped hexagon with arms 1 wide: inset by 0.5 (its D limit) its ring is the arms' midlines, no area."""
    return _one_face([(0, 0), (4, 0), (4, 1), (1, 1), (1, 3), (0, 3)])


def _u_ngon():
    """A U-shaped octagon with arms 1 wide, its D limit 0.5 like the L's."""
    return _one_face([(0, 0), (3, 0), (3, 1), (1, 1), (1, 2), (3, 2), (3, 3), (0, 3)])


def _octagon():
    """A regular octagon of radius 2: every miter meets at the centre, at 2 cos(pi / 8) = 1.847759."""
    return _one_face([(2 * math.cos(math.pi * i / 4), 2 * math.sin(math.pi * i / 4)) for i in range(8)])


def _cylinder_cap(tilt=0.37):
    """An 8-sided open cylinder of radius 2, height 2, turned by ``tilt`` radians; chain 8-15 runs round its cap
    (face 8), which lies on the chain's +1 side. Tilted, the cap's miters miss each other at the limit by 4.2e-8."""
    turn = Matrix.Rotation(tilt, 3, Vector((1.0, 0.4, 0.2)).normalized())
    points = [tuple(turn @ Vector((2 * math.cos(math.pi * i / 4), 2 * math.sin(math.pi * i / 4), z)))
              for z in (0.0, 2.0) for i in range(8)]
    faces = [(i, (i + 1) % 8, 8 + (i + 1) % 8, 8 + i) for i in range(8)] + [tuple(range(8, 16))]
    return _mesh(points, faces)


def _ring_build(bm, chain):
    """The BandBuild of the closed ``chain`` (vertex indices) on its +1 side."""
    src = bridge.ChainSrc(verts=[bm.verts[i] for i in chain], closed=True, index=0)
    build, err = bridge.build_band(bm, src, 1)
    assert build is not None, err
    return build


def _band_mesh(band):
    """A core fixture band (``smart_edge_slide_fixtures``) as a bmesh: its vertex i and face f at index i and f."""
    ids, fids = sorted(band.verts), sorted(band.faces)
    assert ids == list(range(len(ids))) and fids == list(range(len(fids))), "fixture ids are not 0 .. n-1"
    return _mesh([band.verts[i] for i in ids], [band.faces[f] for f in fids])


def _fixture_build(band, side, prepare=None):
    """(bmesh, BandBuild) of a core fixture band, its chain cut on ``side``; ``prepare(bm)`` runs before the build.

    The bridge's band holds the fixture's faces it reaches on that side (all of them, but where the chain walls
    some off) and its side faces; its end edges are the bridge's own pick.
    """
    bm = _band_mesh(band)
    if prepare is not None:
        prepare(bm)
    src = bridge.ChainSrc(verts=[bm.verts[i] for i in band.chain], closed=band.closed, index=0)
    build, err = bridge.build_band(bm, src, side)
    assert build is not None, err
    assert all(band.faces[f] == loop for f, loop in build.band.faces.items())
    assert build.band.side_faces == band.side_faces
    return bm, build


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
        self.use_uv_stripe, self.uv_stripe_mode, self.use_destructive = False, "FIT", False
        self.use_auto_adjust = False
        self.rail_bend, self.end_edge_angle = math.radians(30), math.radians(60)
        self.step_agreement, self.step_difference, self.shoot_angle = math.radians(30), math.radians(60), math.radians(30)
        self.tolerance = 0.0
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


def test_end_edge_angle_admits_a_shallower_end_edge():
    bm = _shallow_end()
    build, err = bridge.build_band(bm, _chain(bm, [0, 1, 2, 3]), +1)
    assert err is None and build.band.end_edges[0] is None
    build, err = bridge.build_band(bm, _chain(bm, [0, 1, 2, 3]), +1, angles=core.Angles(end_edge=math.radians(40)))
    assert err is None and build.band.end_edges[0] == 4 and build.band.angles.end_edge == math.radians(40)
    bm.free()


def _coplanar_ngon_end():
    """Chain 0-1 (3 long, along +x) between a coplanar 5-gon on side +1 and a 5-gon on side -1.

    The own-side 5-gon 0, 1, 2, 3, 4 leaves end vertex 1 along 1-2, 40 degrees off the chain: shallower than the
    default End Edge Angle (60). The face across 1-2, the quad 1, 5, 6, 2, unfolds past the chain's extension: its
    other edge at 1, 1-5, goes to (4, -0.5) and also bounds the other side's 5-gon 1, 0, 7, 8, 5."""
    lean = math.radians(40.0)
    points = [(0, 0, 0), (3, 0, 0), (3 - math.cos(lean), math.sin(lean), 0), (1.5, 1.2, 0), (0, 1, 0),
              (4, -0.5, 0), (4, 1, 0), (0, -1, 0), (3, -1, 0)]
    return _mesh(points, [(0, 1, 2, 3, 4), (1, 5, 6, 2), (1, 0, 7, 8, 5)])


def test_end_edge_never_comes_from_the_other_side():
    bm = _coplanar_ngon_end()
    build, err = bridge.build_band(bm, _chain(bm, [0, 1]), +1)
    # 1-5 lies past the chain's extension (the other side's face): the end edge is the own-side 1-2 instead.
    assert err is None and build.band.end_edges == (4, 2), build.band.end_edges
    slider = wave.WaveSlider(build.band)
    assert slider.limit() > 0.5 and slider.limit(destructive=True) > 0.5, (slider.limit(), slider.limit(destructive=True))
    bm.free()


def test_angle_props_reach_execute():
    def new(**props):
        obj = _edit_object(_bent_rows(20.0), chain=[0, 1, 2, 3])
        assert _run(obj, width=0.75, chain_sides="+", **props) == {'FINISHED'}
        return _new_coords(obj)
    assert new() != new(rail_bend=math.radians(10))


def _f32(x):
    return struct.unpack("f", struct.pack("f", x))[0]


def test_angles_at_the_defaults_are_exactly_the_core_defaults():   # Blender stores props as float32
    names = ("rail_bend", "end_edge_angle", "step_agreement", "step_difference", "shoot_angle")
    stand = _OperatorStandIn(**{n: _f32(getattr(_OperatorStandIn(), n)) for n in names})
    assert stand._angles() == core.Angles()


def test_step_agreement_stays_under_step_difference():
    stand = _OperatorStandIn(step_agreement=math.radians(50), step_difference=math.radians(40))
    assert stand._angles().step_agree == math.radians(40) - math.radians(1)


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
    assert [p.name for p in params] == [
        "Width", "Exact Width (E)", "Allow Collapse (C)", "Destructive (D)", "Auto Adjust (Q)", "UV Stripe (U)",
        "Clamped"]                                                  # the angles and Tolerance: redo panel only
    assert all(p.value_text() != "?" for p in params)              # every getter runs
    assert [(it.label, it.key) for it in op._help.sections[0].items] == [
        ("Adjust width", "Mouse / Type"), ("Snap to vertex", "Ctrl"), ("Exact width", "E"),
        ("Allow collapse", "C"), ("Destructive", "D"), ("Auto adjust", "Q"), ("UV Stripe", "U"),
        ("Flip chain side", "F"),
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
    op._cancel_use_destructive, op._cancel_use_auto_adjust = op.use_destructive, op.use_auto_adjust
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


def test_modal_cursor_wrap_never_jumps_the_width():
    _edit_object(_strip(), chain=[0, 1, 2, 3])
    op, ctx = _invoke(x=900, width=0.05)
    warps = []
    ctx.region = SimpleNamespace(x=0, y=0, width=1000, height=500)
    ctx.window = SimpleNamespace(cursor_warp=lambda x, y: warps.append((x, y)))
    op._modal(ctx, _move(999))                           # reaches the right edge: warped to the left
    _close(op.width, 0.05 + 99 * op._pixel_to_width)
    assert warps == [(2, 0)]
    held = op.width
    op._modal(ctx, _move(999))                           # a move reported from before the warp: ignored
    _close(op.width, held)
    op._modal(ctx, _move(12))                            # the drag goes on from the warped position
    _close(op.width, held + 10 * op._pixel_to_width)
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


def test_a_new_launch_starts_at_width_zero():
    # The width is not remembered (SKIP_SAVE): a new launch starts at 0, while the toggles, the angles and Tolerance
    # come back as last used. Blender hands a new launch the last run's props but the SKIP_SAVE ones, which start at
    # their defaults; that is what the second invoke gets here. Redo still re-runs from the operator's own props.
    rna = bpy.ops.iops.mesh_smart_edge_slide.get_rna_type().properties
    assert rna["width"].default == 0.0 and rna["width"].is_skip_save
    kept = ("use_exact", "use_collapse", "use_destructive", "use_uv_stripe", "uv_stripe_mode", "rail_bend",
            "end_edge_angle", "step_agreement", "step_difference", "shoot_angle", "tolerance")
    assert not any(rna[name].is_skip_save for name in kept)
    obj = _edit_object(_strip(), chain=[0, 1, 2, 3])
    first, ctx = _invoke(x=0, width=rna["width"].default, tolerance=1e-3)
    assert first.width == 0.0
    _keys(first, ctx, "E PERIOD TWO FIVE")
    assert first._modal(ctx, _event("RET")) == {'FINISHED'} and not first.reports, first.reports
    assert _new_coords(obj) and first.width == 0.25
    last = {name: (rna[name].default if rna[name].is_skip_save else getattr(first, name)) for name in ("width", *kept)}
    _edit_object(_strip(), chain=[0, 1, 2, 3])
    second, ctx = _invoke(x=0, **last)
    assert (second.width, second._initial_width) == (0.0, 0.0)
    assert (second.use_exact, second.tolerance) == (True, 1e-3)
    assert second._modal(ctx, _event("ESC")) == {'CANCELLED'} and second.width == 0.0


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


# --- destructive mode (D): WaveSlider cuts built by the bridge ----------------------

def _d_cut_problems(band, side, slider, cut, tolerance=0.0):
    """What is wrong with ``cut``, a destructive cut ``slider`` solved on ``band``, built into a fresh mesh of it.

    In the destructive mode ``apply_cut`` refuses nothing below the limit (anti-goal 1): a refusal, a part it could
    not build, an edge across a break, loop edges missing from the pieces and every topology problem
    (``topology.problems``) are named. ``tolerance`` is the Tolerance prop ``slider`` was made with.
    """
    bm, build = _fixture_build(band, side)
    try:
        before = topology.snapshot(bm)
        try:
            extra = {"tolerance": tolerance} if tolerance else {}
            applied = bridge.apply_cut(bm, build, cut, slider, destructive=True, **extra)
        except ValueError as exc:
            return [f"refused: {exc}"]
        out = [f"incomplete: {msg}" for msg in applied.failures]
        out += [f"an edge across break {i}" for i in topology.edge_across_a_break(bm, cut, before)]
        if set(applied.loop_edges) != {e for piece in applied.pieces for e in piece}:
            out.append("the pieces do not hold the loop edges")
        return out + topology.problems(bm, before)
    finally:
        bm.free()


def _d_band(make, side, tolerance=0.0):
    """(band, its WaveSlider as the bridge builds the band) of a fixture; ``tolerance`` is the Tolerance prop's."""
    band = make()
    bm, build = _fixture_build(band, side)
    bm.free()
    return band, wave.WaveSlider(build.band, **({"tolerance": tolerance} if tolerance else {}))


# (name, builder, side, exact) of every band the destructive topology test cuts; Tasks 4-7 append theirs.
D_BANDS = [
    ("fanned_u", lambda: fixtures.fanned_u(), 1, False),
    *((f"jittered_u({s}, 0.3, 0.6)", lambda s=s: fixtures.jittered_u(s, 0.3, 0.6), 1, False) for s in (6, 11, 22, 30)),
    ("jittered_u(30, 0.4)", lambda: fixtures.jittered_u(30, 0.4), 1, False),
    ("u_in_grid", lambda: fixtures.u_in_grid(), 1, False),                     # a ridge into a quad and back
    *((f"jittered_u({s}, 0.4)", lambda s=s: fixtures.jittered_u(s, 0.4), 1, False) for s in (0, 22)),
    *((f"chain_jittered_u({s})", lambda s=s: fixtures.chain_jittered_u(s), 1, x)
      for s in (1, 7) for x in (False, True)),
    ("chain_jittered_u(6, 0.3, 0.3)", lambda: fixtures.chain_jittered_u(6, 0.3, 0.3), 1, False),
    ("chain_jittered_u(24, 0.25, 0.05, 0.8)", lambda: fixtures.chain_jittered_u(24, 0.25, 0.05, 0.8), 1, False),
    ("u_wall", lambda: fixtures.u_wall(), 1, False),
    *((f"jittered_u_wall({s})", lambda s=s: fixtures.jittered_u_wall(s), 1, False) for s in (1, 5)),
    ("hole_rim", lambda: fixtures.hole_rim(), -1, False),
    ("hole_rim, exact", lambda: fixtures.hole_rim(), -1, True),
    *((f"jittered_hole_rim({s})", lambda s=s: fixtures.jittered_hole_rim(s), -1, x)
      for s in (1, 22) for x in (False, True)),
    ("notch_spike", lambda: fixtures.notch_spike(), 1, False),
    ("bumped_arm", lambda: fixtures.bumped_arm(), 1, False),
    ("ring", lambda: fixtures.ring(), 1, False),
    ("chamfer_ring", lambda: fixtures.chamfer_ring(), 1, False),
    ("square_in_grid", lambda: fixtures.square_in_grid(), 1, False),
    *((f"jittered_grid({s})", lambda s=s: fixtures.jittered_grid(s), 1, False) for s in (0, 1)),
    ("shoot_strip", lambda: fixtures.shoot_strip(), 1, False),                 # the start shoots on to an edge
    ("shoot_strip(slant 40)", lambda: fixtures.shoot_strip(slant_deg=40.0), 1, False),
    ("shoot_strip(no landing)", lambda: fixtures.shoot_strip(no_landing=True), 1, False),
    ("shoot_bevel", lambda: fixtures.shoot_bevel(), 1, False),                 # onto a vertex
    ("jittered_shoot_strip(3)", lambda: fixtures.jittered_shoot_strip(3), 1, False),
    ("dumbbell", lambda: fixtures.dumbbell(), 1, False),                       # it splits into two rings
    ("grid_racket", lambda: fixtures.grid_racket(), 1, False),                 # its handle merges into the room
    ("grid_racket, exact", lambda: fixtures.grid_racket(), 1, True),
    ("dumbbell_hole", lambda: fixtures.dumbbell_hole(), 1, False),             # a ring cut by a hole's border
    ("racket_hole", lambda: fixtures.racket_hole(), 1, False),
    # Jittered contacts (every vertex moved, the chain's too): the branch's fold or the room's contact comes first.
    *((f"racket_ngon jittered({s}, {a})", lambda s=s, a=a: fixtures.xy_jittered(fixtures.racket_ngon(), s, a), 1, False)
      for s, a in ((15, 5e-4), (3, 0.03))),
    *((f"grid_racket jittered({s}, {a})", lambda s=s, a=a: fixtures.xy_jittered(fixtures.grid_racket(), s, a), 1, False)
      for s, a in ((0, 5e-4), (1, 0.03))),
    *((f"dumbbell jittered({s}, {a})", lambda s=s, a=a: fixtures.xy_jittered(fixtures.dumbbell(), s, a), 1, False)
      for s, a in ((4, 0.03),)),
    # 6a fix round 2: rings and ridges sharing a face (planned together, a ridge with no room for its legs merged into
    # an apex), a spike just past its contact, a sharp V's fold, rings touching where they split.
    *((f"grid_racket jittered({s}, {a})", lambda s=s, a=a: fixtures.xy_jittered(fixtures.grid_racket(), s, a), 1, False)
      for s, a in ((0, 0.03), (6, 0.03), (7, 5e-4))),
    *((f"asymmetric_l_ngon jittered({s}, {a})",
       lambda s=s, a=a: fixtures.xy_jittered(fixtures.asymmetric_l_ngon(), s, a), 1, False)
      for s, a in ((6, 5e-4), (1, 5e-4), (5, 0.03))),
    *((f"dumbbell jittered({s}, {a})", lambda s=s, a=a: fixtures.xy_jittered(fixtures.dumbbell(), s, a), 1, False)
      for s, a in ((2, 0.03), (0, 5e-4), (6, 5e-4))),
    *((f"racket_ngon jittered({s}, {a})", lambda s=s, a=a: fixtures.xy_jittered(fixtures.racket_ngon(), s, a), 1, False)
      for s, a in ((2, 0.03), (7, 0.03), (5, 0.03))),
]

# Refusals still left within 1e-6 of a ring event (a contact or fold) on the jittered contact bands, per band: the
# noise-scale class Task 6a fix round 2 leaves (rings touching right at a split, a V at a near-hairpin fold). Refused
# before any edit, never built invalid; the counts make progress visible.
D_KNOWN_NEAR_EVENTS: dict[str, int] = {
    # a second contact on the fold at 1.0000047; and 3 within 1e-6 short of the handle ring's fold at 0.5000788, where
    # its V now keeps its fold point (6b-1)
    "grid_racket jittered(7, 0.0005)": 7,
    "dumbbell jittered(0, 0.0005)": 5,      # the same at 1.0002778: built with edges meeting before round 2
}


def _all_events(w, exact):
    """The wave's events, and past a split its rings' (``_Wave.parts``), in width order."""
    out, todo = [], [w]
    while todo:
        s = todo.pop()
        wave_ = s._wave_of(exact)
        out += wave_.events
        todo += wave_.parts
    return sorted(out, key=lambda e: e.width)


def _d_widths(events, lim):
    """The widths the destructive topology test cuts at, below ``lim``, given the wave's ``events`` (``_all_events``)."""
    shots = {e.width + d for e in events if e.kind == "wall_end" for d in (0.0, 1e-9, 1e-6)}  # at a jump
    # Just below every fold, where the segments about to go are a few 1e-7 long: within the weld, they are gone.
    folds = {e.width - d for e in events if e.kind == "fold" for d in (3e-7, 1e-7, 1e-8)}
    return [lim * k / 5.0 for k in range(1, 6)] + [lim - 1e-6] + sorted(x for x in shots | folds if 0.0 < x <= lim)


def test_apply_destructive_keeps_topology_valid():                                     # anti-goal 2
    problems, known, near = [], set(), {}
    for name, make, side, exact in D_BANDS:
        band, w = _d_band(make, side)
        lim = w.limit(exact=exact, destructive=True)
        events = _all_events(w, exact)  # the rings' too, past a split
        widths = _d_widths(events, lim)
        rings = [e.width for e in events if e.kind in ("contact", "fold")] if "jittered(" in name else []
        for width in widths:
            cut = w.solve(width, exact=exact, destructive=True)
            found = _d_cut_problems(band, side, w, cut)
            if found == [f"refused: {bridge.LOOP_CROSSES}"] and name == "chain_jittered_u(24, 0.25, 0.05, 0.8)":
                known.add(round(width, 7))
                continue
            if (len(found) == 1 and found[0].startswith("refused") and width < lim
                    and any(abs(width - x) <= 1e-6 for x in rings)):
                near[name] = near.get(name, 0) + 1
                continue
            problems += [f"{name} at {width:.7f}: {p}" for p in found]
    assert not problems, "\n".join(problems)
    assert near == D_KNOWN_NEAR_EVENTS, near
    # chain_jittered_u(24, 0.25, 0.05, 0.8) folds its loop back across itself near two folds (non-neighbouring segments
    # within the weld of each other, not a short segment): the self-crossing Task 6 splits. Refused before any edit.
    assert known <= {0.1060059, 2.0812515}, known


D_TOLERANCE = 1e-3  # a Tolerance well above the bands' noise (5e-4 of jitter) and well below their feature size


def test_tolerance_builds_the_near_event_refusals():
    # The refusals D_KNOWN_NEAR_EVENTS lists, within 1e-6 of a ring event at the automatic weld, build with a raised
    # Tolerance: at the very widths refused, and at the topology test's widths round the raised slider's own events.
    for name, make, side, exact in D_BANDS:
        if name not in D_KNOWN_NEAR_EVENTS:
            continue
        band, w = _d_band(make, side)
        lim = w.limit(exact=exact, destructive=True)
        refused = [x for x in _d_widths(_all_events(w, exact), lim)
                   if _d_cut_problems(band, side, w, w.solve(x, exact=exact, destructive=True))]
        assert len(refused) == D_KNOWN_NEAR_EVENTS[name], (name, refused)
        band, w = _d_band(make, side, D_TOLERANCE)
        lim = w.limit(exact=exact, destructive=True)
        problems = []
        for width in refused + _d_widths(_all_events(w, exact), lim):
            cut = w.solve(width, exact=exact, destructive=True)
            problems += [f"{width:.9f}: {p}" for p in _d_cut_problems(band, side, w, cut, D_TOLERANCE)]
        assert not problems, (name, problems)


def test_tolerance_prop():
    prop = bpy.ops.iops.mesh_smart_edge_slide.get_rna_type().properties["tolerance"]
    assert (prop.name, prop.subtype, prop.default, prop.hard_min) == ("Tolerance", 'DISTANCE', 0.0, 0.0)
    assert _OperatorStandIn().tolerance == prop.default


def test_tolerance_reaches_execute():
    # Just short of the handle's near-hairpin fold of grid_racket jittered(7, 5e-4), a Tolerance of 1e-3 welds what
    # the automatic weld keeps apart: the redo panel's prop reaches the cut.
    make = lambda: fixtures.xy_jittered(fixtures.grid_racket(), 7, 5e-4)  # noqa: E731
    outcomes = []
    for tolerance in (0.0, D_TOLERANCE):
        band = make()
        obj = _edit_object(_band_mesh(band), chain=band.chain + [band.chain[0]])
        op = _OperatorStandIn(width=0.500078719, chain_sides="-", use_destructive=True, tolerance=tolerance)
        assert op.execute(bpy.context) == {'FINISHED'} and not op.reports, op.reports
        outcomes.append(_new_coords(obj))
    assert outcomes[0] and outcomes[1] and outcomes[0] != outcomes[1]


def test_tolerance_is_ignored_with_destructive_off():
    # Without Destructive the Tolerance changes nothing: the same mesh from apply_cut, and from execute.
    band = fixtures.u_wall()
    for collapse in (False, True):
        states = []
        for tolerance in (0.0, D_TOLERANCE):
            bm, build = _fixture_build(band, 1)
            s = wave.WaveSlider(build.band, tolerance=tolerance)
            cut = s.solve(0.6, collapse=collapse)
            bridge.apply_cut(bm, build, cut, s, tolerance=tolerance)
            states.append(sorted(tuple(v.co) for v in bm.verts))
            bm.free()
        assert states[0] == states[1]
    states = []
    for tolerance in (0.0, D_TOLERANCE):
        obj = _edit_object(_band_mesh(band), chain=band.chain)
        op = _OperatorStandIn(width=0.6, chain_sides="+", use_collapse=True, tolerance=tolerance)
        assert op.execute(bpy.context) == {'FINISHED'}, op.reports
        states.append((_coords(obj), _all_edges(obj)))
    assert states[0] == states[1]


def _ngon(pts):
    """One flat face with outline ``pts``, its closed chain, built with the side inward (a BandBuild, its bmesh)."""
    bm = _mesh([(x, y, 0.0) for x, y in pts], [tuple(range(len(pts)))])
    build, err = bridge.build_band(bm, bridge.ChainSrc(verts=list(bm.verts), closed=True, index=0), 1)
    assert build is not None, err
    return bm, build


NGONS = [  # (name, outline): arms 1 wide, so each ends as its skeleton tree at 1/2 (see the core's L test)
    ("L", [(0, 0), (4, 0), (4, 1), (1, 1), (1, 3), (0, 3)]),
    ("U", [(0, 0), (3, 0), (3, 1), (1, 1), (1, 2), (3, 2), (3, 3), (0, 3)]),
    ("T", [(0, 0), (5, 0), (5, 1), (3, 1), (3, 3), (2, 3), (2, 1), (0, 1)]),   # the stem's foot on the bar: a junction
]


def test_apply_destructive_builds_a_non_convex_rings_tree():
    # A ring inside one non-convex face ends as the walk round its skeleton tree, its knee or junction repeated. The
    # bridge welds the repeats and builds the tree, one face per chain edge. Just short of the limit the thin ring is an
    # inset, and past it the tree holds. Both were refused (the ring runs round nothing, or crosses itself).
    problems = []
    for name, pts in NGONS:
        bm, build = _ngon(pts)
        w = wave.WaveSlider(build.band)
        bm.free()
        lim = w.limit(destructive=True)
        for width in (lim - 1e-6, lim - 3e-7, lim, lim + 0.25):
            cut = w.solve(width, destructive=True)
            bm, build = _ngon(pts)
            before = topology.snapshot(bm)
            try:
                applied = bridge.apply_cut(bm, build, cut, w, destructive=True)
                problems += [f"{name} at {width:.7f}: {p}" for p in list(applied.failures) + topology.problems(bm, before)]
                if width >= lim:
                    assert len(bm.faces) == len(pts), (name, len(bm.faces))         # one face per chain edge
            except ValueError as exc:
                problems.append(f"{name} at {width:.7f}: refused: {exc}")
            bm.free()
    assert not problems, "\n".join(problems)


def test_apply_destructive_builds_a_ridge_tip():
    # u_in_grid at its limit: the loop closed into a ridge from the mouth's (3.5, 4) down to (3.5, 3.5), inside a quad,
    # with no connector that crosses nothing. The tip is built by one face split from where the ridge enters that
    # quad, through the tip, to the quad's vertex nearest it: a new vertex at (3.5, 3.5) with two edges.
    band, w = _d_band(fixtures.u_in_grid, 1)
    cut = w.solve(w.limit(destructive=True) + 0.1, destructive=True)
    assert cut.clamped and len(cut.points) == 3 and cut.points[1].kind == "face"
    assert _d_cut_problems(band, 1, w, cut) == []
    bm, build = _fixture_build(band, 1)
    bridge.apply_cut(bm, build, cut, w, destructive=True)
    tip = topology.vertex_at(bm, (3.5, 3.5, 0.0))
    assert tip is not None and len(tip.link_edges) == 2
    bm.free()


def _final_strip_spreads(bm, build, cut, slider):
    """Apply ``cut`` (D) and lay out every piece's UV strip: per piece, the largest V error of its near corners (off
    v = 0) and far corners (off v = height), or the reason it was skipped."""
    applied = bridge.apply_cut(bm, build, cut, slider, destructive=True)
    assert not applied.failures, applied.failures
    bm.verts.index_update()
    bm.faces.index_update()
    out = []
    for piece in range(len(applied.pieces)):
        try:
            strip, _faces = bridge.stripe_for(build, applied, cut.width, piece)
        except ValueError as exc:
            out.append(str(exc))
            continue
        uv = bridge.uv_stripe_core.stripe_uvs(strip)
        near, far = set(strip.near), set(strip.far)
        out.append(max([abs(v) for (_f, vid), (_u, v) in uv.items() if vid in near and vid not in far]
                       + [abs(v - strip.height) for (_f, vid), (_u, v) in uv.items() if vid in far]))
    return out


def test_uv_stripe_lays_out_final_states():
    # Each final state gets one straight strip (V within 1e-6 of 0 on the chain, of the width on the new loop), its
    # triangles where vertices merged, as UV Stripe lays out Smart Inset's collapsed insets (``corner_far``):
    # - square_in_grid past 1: the apex, the four triangles fanning into it;
    # - the L n-gon past 1/2: the walk round its tree, its knee twice on the far row;
    # - u_in_grid past 2.5: the ridge into a quad and back, its mouth point twice on the far row, its tip in between;
    # - u_wall past 2.9 / sqrt2: one strip per piece, as below the limit (no jump across it): its three pieces, two
    #   pressed onto their walls (their points apart, a break inside each) and the ridge, each skipped as just below
    #   the limit, for the reason it gives there: no edge back to its chain where a cut opened it (c1's and c8's legs
    #   to their cut ends cross the holes' sides).
    # Every rotation of the L, U and T n-gons' chains lays out their trees too (a walk that wraps round its seam).
    for name, make in (("square apex", fixtures.square_in_grid), ("u_in_grid tip", fixtures.u_in_grid)):
        band, w = _d_band(make, 1)
        cut = w.solve(w.limit(destructive=True) + 0.25, destructive=True)
        assert cut.clamped, name
        bm, build = _fixture_build(band, 1)
        spreads = _final_strip_spreads(bm, build, cut, w)
        bm.free()
        assert len(spreads) == 1 and isinstance(spreads[0], float) and spreads[0] <= 1e-6, (name, spreads)
    band, w = _d_band(fixtures.u_wall, 1)
    lim = w.limit(destructive=True)
    outcomes = []
    for width in (lim - 0.01, lim + 0.25):
        bm, build = _fixture_build(band, 1)
        outcomes.append(_final_strip_spreads(bm, build, w.solve(width, destructive=True), w))
        bm.free()
    assert outcomes[0] == outcomes[1] == [bridge.PIECE_OPEN_SIDE] * 3, outcomes
    for name, pts in NGONS:
        for r in range(len(pts)):
            turned = pts[r:] + pts[:r]
            bm, build = _ngon(turned)
            w = wave.WaveSlider(build.band)
            cut = w.solve(w.limit(destructive=True) + 0.25, destructive=True)
            spreads = _final_strip_spreads(bm, build, cut, w)
            bm.free()
            assert len(spreads) == 1 and isinstance(spreads[0], float) and spreads[0] <= 1e-6, (name, r, spreads)


def test_apply_destructive_builds_a_room_past_its_closed_branch():                      # carry 5
    # A branch one unit wide (the racket's handle, the asymmetric L's narrow arm) closes at 1/2, where the room's reflex
    # corner touches the loop across it: the branch merges into the room's ring, which goes on to the room's own
    # collapse (3 x 3 rooms: 1.5; the one-face racket's 4 x 4 room: 2). Each cut builds valid topology, just either side
    # of the touch, below, at and past the limit. The grid racket was refused, or built with a gap, from 1/2 on.
    def cases():
        band, w = _d_band(fixtures.grid_racket, 1)
        yield "grid racket", (lambda: _fixture_build(band, 1)), w
        for name, pts in (("asymmetric L", [(0, 0), (6, 0), (6, 1), (3, 1), (3, 3), (0, 3)]),
                          ("racket", [(0, 0), (4, 0), (4, 1.5), (7, 1.5), (7, 2.5), (4, 2.5), (4, 4), (0, 4)])):
            bm, build = _ngon(pts)
            w = wave.WaveSlider(build.band)
            bm.free()
            yield name, (lambda pts=pts: _ngon(pts)), w

    for name, make, w in cases():
        for exact in (False, True):
            lim = w.limit(exact=exact, destructive=True)
            assert lim > 1.4, (name, exact, lim)
            dense = [0.5 + (lim - 0.5) * k / 40 for k in range(1, 40)]  # the room's ring all the way (Important 1)
            for width in (0.5 - 1e-6, 0.5 + 1e-6, *dense, lim - 1e-6, lim - 3e-7, lim, lim + 0.25):
                bm, build = make()
                outcome = _built_or_refused(bm, build, w.solve(width, exact=exact, destructive=True), w)
                bm.free()
                assert outcome == "built", (name, exact, width, outcome)


def test_apply_destructive_builds_both_rings_of_a_split_loop():
    # The dumbbell's loop touches itself across the neck at 1/2 and goes on as two rings, one per room: both are built,
    # each a closed loop of its own (two pieces, no edge between them). At 2.5 the small room is its apex, (2, 3), a grid
    # vertex already, so that piece has no edge, and the big room's ring goes on round (9, 3).
    band, w = _d_band(fixtures.dumbbell, 1)
    for width, apex in ((0.75, False), (2.5, True)):
        cut = w.solve(width, destructive=True)
        bm, build = _fixture_build(band, 1)
        before = topology.snapshot(bm)
        applied = bridge.apply_cut(bm, build, cut, w, destructive=True)
        assert not applied.failures and topology.problems(bm, before) == [], (width, applied.failures)
        assert len(applied.pieces) == 2, (width, len(applied.pieces))
        rings = [p for p in applied.pieces if p]
        assert all(_closes_on_itself(p) for p in rings), width
        assert len(rings) == (1 if apex else 2), (width, len(rings))
        if apex:
            assert cut.points[0].kind == "vert" and cut.points[0].co[:2] == (2.0, 3.0)
        bm.free()


def test_uv_stripe_lays_out_each_ring_of_a_split_loop():
    # A split loop gives one strip per piece: each ring of the dumbbell lays out straight, from just past the split to
    # past the limit (the small room's apex fans), the two sharing the neck's region where they split off, each face of
    # it going to the ring whose strip reaches it first.
    band, w = _d_band(fixtures.dumbbell, 1)
    for width in (0.75, 1.2, 2.5, w.limit(destructive=True) + 0.5):
        cut = w.solve(width, destructive=True)
        bm, build = _fixture_build(band, 1)
        spreads = _final_strip_spreads(bm, build, cut, w)
        bm.free()
        assert len(spreads) == 2 and all(isinstance(x, float) and x <= 1e-6 for x in spreads), (width, spreads)


def test_uv_stripe_names_a_ring_with_no_chain_of_its_own():
    # A jittered dumbbell splits into three rings or more, and a small one has no chain vertex anchored on it: no strip
    # shape (the spec), skipped as such, not as a strip with no length.
    band, w = _d_band(lambda: fixtures.xy_jittered(fixtures.dumbbell(), 2, 0.03), 1)
    lim = w.limit(destructive=True)
    reasons = set()
    for width in (0.75, 0.625 * lim, lim + 0.5):
        cut = w.solve(width, destructive=True)
        bm, build = _fixture_build(band, 1)
        reasons |= {x for x in _final_strip_spreads(bm, build, cut, w) if isinstance(x, str)}
        bm.free()
    assert bridge.RING_NO_CHAIN in reasons and bridge.NO_STRIP_LENGTH not in reasons, reasons


def test_apply_destructive_builds_rings_sharing_a_face():                                # C3 (6a fix round 2)
    # The jittered grid racket ends as three rings, two of them ridges inside one quad each; the asymmetric L's room a
    # thin ring beside an apex. Each ring's legs from its face's corners are planned with every other ring's segments,
    # legs and fan edges in that face, a fan edge into the ring before any other corner: built, at and past the limit
    # too (refused, or left with a fan edge cut into no face, before).
    for make in (lambda: fixtures.xy_jittered(fixtures.grid_racket(), 0, 0.03),
                 lambda: fixtures.xy_jittered(fixtures.asymmetric_l_ngon(), 6, 5e-4)):
        band, w = _d_band(make, 1)
        for exact in (False, True):
            lim = w.limit(exact=exact, destructive=True)
            for width in (0.75 * lim, lim - 1e-6, lim, lim + 0.25):
                assert _d_cut_problems(band, 1, w, w.solve(width, exact=exact, destructive=True)) == [], (exact, width)


def test_apply_destructive_drops_only_a_lone_apexs_grazing_fan_edge():                 # Important 4 (6a fix round 1)
    # A fan edge into a lone apex that grazes its face's border (through a reflex corner) is left out; any other cut is
    # built or refused as before the drop: these five, on loops crossing themselves (Task 6b), were built invalid when
    # every grazing connector was dropped, and are refused before any edit again.
    for seed, exact, width in ((0, False, 0.13360492894340517), (8, False, 0.24474816432258262),
                               (8, True, 0.20269466579852824), (8, True, 0.20269556579852824),
                               (8, True, 0.24585237465280743)):
        band, w = _d_band(lambda s=seed: fixtures.chain_jittered_u(s, 0.3, 0.3), 1)
        bm, build = _fixture_build(band, 1)
        outcome = _built_or_refused(bm, build, w.solve(width, exact=exact, destructive=True), w)
        bm.free()
        assert outcome == "built" or outcome.startswith("refused"), (seed, exact, width, outcome)


def _closes_on_itself(edges):
    """Whether the edges form one closed loop: every vertex on two of them."""
    count = {}
    for e in edges:
        for v in e.verts:
            count[v] = count.get(v, 0) + 1
    return bool(edges) and set(count.values()) == {2}


def test_segment_gap_is_symmetric():
    # The gap between two segments does not depend on which is asked first (Task 8 review).
    rnd = __import__("random").Random(5)
    for _ in range(2000):
        p0, p1, q0, q1 = ([rnd.uniform(-1, 1) for _ in range(3)] for _ in range(4))
        assert bridge._segment_gap(p0, p1, q0, q1) == bridge._segment_gap(q0, q1, p0, p1)


def test_apply_destructive_builds_a_shot_end_on_its_landing():
    # Past the start's wall's end (1.000002) the end shot on and slides up its landing: on shoot_strip the edge b1-t1
    # (x = -1.5), on shoot_bevel the rung w-tw from the vertex w it landed on. At 1.5 its new vertex splits that edge at
    # (-1.5, 1.5); its loop edge runs to c1's across F1 (shoot_strip, crossing nothing) or across v-tw (shoot_bevel).
    for make, crossings in ((fixtures.shoot_strip, 0), (fixtures.shoot_bevel, 1)):
        band, w = _d_band(make, 1)
        cut = w.solve(1.5, destructive=True)
        assert not cut.clamped and cut.points[0].kind == "edge" and cut.points[0].edge == (8, 9)
        assert cut.anchors[1] == 1 + crossings and _d_cut_problems(band, 1, w, cut) == []
        bm, build = _fixture_build(band, 1)
        before = topology.snapshot(bm)
        applied = bridge.apply_cut(bm, build, cut, w, destructive=True)
        assert not applied.failures, applied.failures
        v = topology.vertex_at(bm, (-1.5, 1.5, 0.0))
        assert v is not None and v not in before.verts and len(v.link_edges) == 3   # on b1-t1 (w-tw), and the loop
        assert any(v in e.verts for e in applied.loop_edges)
        bm.free()


def test_apply_destructive_in_the_last_micron_below_a_limit():
    # jittered_u(30, 0.3, 0.6): within ~1e-6 below its D limit, neighbouring cut points once shared no face.
    band, w = _d_band(lambda: fixtures.jittered_u(30, 0.3, 0.6), 1)
    lim = w.limit(destructive=True)
    problems = []
    for d in (1e-6, 7e-7, 5e-7, 3e-7, 2e-7, 1e-7, 5e-8, 3e-8, 1e-8, 0.0):
        problems += [f"{lim - d:.9f}: {p}" for p in _d_cut_problems(band, 1, w, w.solve(lim - d, destructive=True))]
    assert not problems, "\n".join(problems)


def test_apply_destructive_u_wall_opens_on_the_wall():
    # u_wall past its wall hit (0.439340): c1 and c8 have cut at their holes, three pieces. No new edge joins the two
    # points of a break, and each lies on a hole side, a wall edge of the original mesh, which it splits. (At 0.47 both
    # of c1's ends still lie on hole side a-d: the part of a-d between them is the wall, no loop edge.)
    band, w = _d_band(lambda: fixtures.u_wall(), 1)
    for width in (0.47, 0.75):
        cut = w.solve(width, destructive=True)
        assert len(cut.breaks) == 2, cut.breaks
        bm, build = _fixture_build(band, 1)
        before = topology.snapshot(bm)
        walls = [(e.verts[0].co.copy(), e.verts[1].co.copy()) for e in bm.edges if len(e.link_faces) == 1]
        applied = bridge.apply_cut(bm, build, cut, w, destructive=True)
        assert not applied.failures and len(applied.pieces) == 3
        assert set(applied.loop_edges) == {e for piece in applied.pieces for e in piece}
        assert topology.edge_across_a_break(bm, cut, before) == []
        for i in cut.breaks:
            ends = [topology.vertex_at(bm, cut.points[j].co) for j in (i - 1, i)]
            assert None not in ends and not any(set(e.verts) == set(ends) for e in applied.loop_edges)
            for v in ends:
                assert v not in before.verts and any(topology.distance_to_segment(v.co, a, b) <= 1e-6 for a, b in walls)
        bm.free()


def _apex_fan(bm, build, cut, centre):
    """Build ``cut``, an apex at ``centre`` every anchor shares, and check its fan: one new vertex there, joined to
    every chain vertex, with only triangles round it."""
    before = topology.snapshot(bm)
    count = len(bm.verts)
    applied = bridge.apply_cut(bm, build, cut, destructive=True)
    assert not applied.failures, applied.failures
    assert len(bm.verts) == count + 1
    apex = topology.vertex_at(bm, centre)
    assert apex is not None and apex not in before.verts
    assert {e.other_vert(apex) for e in apex.link_edges} == set(build.chain)
    assert len(apex.link_faces) == len(build.chain) and all(len(f.verts) == 3 for f in apex.link_faces)
    assert topology.problems(bm, before) == []


def test_apply_destructive_square_apex_fans():
    # square_in_grid past its limit (1.0): its four miters meet at the centre (3, 3) of the one band face, the apex.
    band, w = _d_band(lambda: fixtures.square_in_grid(), 1)
    cut = w.solve(w.limit(destructive=True) + 1.0, destructive=True)
    assert cut.clamped and len(cut.points) == 1 and set(cut.anchors) == {0} and cut.breaks == ()
    bm, build = _fixture_build(band, 1)
    _apex_fan(bm, build, cut, (3.0, 3.0, 0.0))
    bm.free()


def test_apply_builds_the_apex_contract_cut():
    # The apex as Task 5's used-up final state must give it (the "Contract for Task 5"): one point inside the band face,
    # every anchor on it, no breaks, and a connector from every chain vertex whose straight leg crosses nothing. D off
    # keeps refusing a loop of one point inside a face, as master does (core.Slider gives this very cut at 1.0).
    band = fixtures.square_in_grid()
    bm, build = _fixture_build(band, 1)
    point = core.SurfacePoint(kind="face", face=4, co=(3.0, 3.0, 0.0))
    cut = core.Cut([point], [0] * 4, [(v, 0) for v in band.chain], 1.0, True, ())
    count = len(bm.verts), len(bm.faces)
    try:
        bridge.apply_cut(bm, build, cut)
        raise AssertionError("D off built a loop of one point")
    except ValueError as exc:
        assert str(exc) == bridge.INSIDE_ONE_FACE, exc
    assert (len(bm.verts), len(bm.faces)) == count
    assert bridge.preview_layers([build], [cut]) == ([], [], True)
    _apex_fan(bm, build, cut, (3.0, 3.0, 0.0))
    bm.free()


def test_apply_destructive_merged_anchors_fan():
    # Merges D has today: fanned_u's start end absorbs chain vertices 1-5 by 2.0 (end folds from 1.875 on; in its grid
    # every leg to the end crosses an edge, so no fan), notch_spike's B and C fold into one group (0.724264), and
    # bumped_arm's c1-c3 into a collinear one (2.414214), both in one face: their members fan out to it. Each merged
    # anchor is one new vertex, and every connector the cut names is an edge from its chain vertex to it.
    for make, width, fans in ((lambda: fixtures.fanned_u(), 2.0, False), (lambda: fixtures.notch_spike(), 0.9, True),
                              (lambda: fixtures.bumped_arm(), 3.5, True)):
        band, w = _d_band(make, 1)
        cut = w.solve(width, destructive=True)
        shared = [a for a in set(cut.anchors) if cut.anchors.count(a) > 1]
        assert shared and not cut.breaks, (width, cut.anchors)
        bm, build = _fixture_build(band, 1)
        chain = {v.index: v for v in build.chain}
        applied = bridge.apply_cut(bm, build, cut, w, destructive=True)
        assert not applied.failures, applied.failures
        for a in shared:
            assert sum((v.co - Vector(cut.points[a].co)).length <= 1e-5 for v in bm.verts) == 1
        assert any(at in shared for _vid, at in cut.connectors) == fans, cut.connectors
        for vid, at in cut.connectors:
            vert = topology.vertex_at(bm, cut.points[at].co)
            assert vert is not None and bm.edges.get((chain[vid], vert)) is not None, (vid, at)
        bm.free()


def test_preview_draws_no_line_across_a_break():
    band, w = _d_band(lambda: fixtures.u_wall(), 1)
    cut = w.solve(0.75, destructive=True)
    bm, build = _fixture_build(band, 1)
    segs, _pts, _clamped = bridge.preview_layers([build], [cut], destructive=True)
    pairs = {(_key(p), _key(q)) for p, q in zip(segs[::2], segs[1::2])}
    for i in cut.breaks:
        a, b = (_key(cut.points[j].co) for j in (i - 1, i))
        assert (a, b) not in pairs and (b, a) not in pairs
    assert len(segs) == 2 * (len(cut.points) - 3)   # three pieces: each point joined to the next, but across a break
    bm.free()


def test_uv_stripe_one_strip_per_piece():
    # u_wall past its hit gives 3 pieces. At 0.47 both ends of each cut connect to the cut vertex, so every piece closes
    # its own strip, straight in UV: its near and far rows each lie on one line of constant V. At 0.75 the cut vertices'
    # legs cross the holes' sides (a-d, or through corner a): no piece separates, and each is skipped with the reason.
    band, w = _d_band(lambda: fixtures.u_wall(), 1)
    for width, strips_expected in ((0.47, 3), (0.75, 0)):
        cut = w.solve(width, destructive=True)
        bm, build = _fixture_build(band, 1)
        applied = bridge.apply_cut(bm, build, cut, w, destructive=True)
        bm.verts.index_update()
        bm.faces.index_update()
        assert len(applied.pieces) == 3
        strips, faces, skipped = [], {}, []
        for piece in range(len(applied.pieces)):
            try:
                strip, piece_faces = bridge.stripe_for(build, applied, cut.width, piece)
            except ValueError as exc:
                skipped.append(str(exc))
                continue
            strips.append(strip)
            faces.update(piece_faces)
        assert len(strips) == strips_expected, skipped
        assert skipped == [bridge.PIECE_OPEN_SIDE] * (3 - strips_expected), skipped
        if strips:
            stripe_bridge.apply_stripes(bm, strips, faces, "FIT")
            assert max(_row_v_spreads(bm, strips, faces)) <= 1e-6
        bm.free()


def _row_v_spreads(bm, strips, faces):
    """The V spread of each strip's near row and far row in the active UV layer, after ``apply_stripes``."""
    layer = bm.loops.layers.uv.active
    out = []
    for strip in strips:
        for row in (strip.near, strip.far):
            vs = [lp[layer].uv.y for fid in strip.faces for lp in faces[fid].loops if lp.vert.index in row]
            assert vs, row
            out.append(max(vs) - min(vs))
    return out


def test_uv_stripe_closed_loop_opened_once_has_a_seam():
    # hole_rim at 1.0: L has cut on the border (since 0.707107), and the closed loop is one open piece. Its chain runs
    # from L round to L, so the strip's near row starts and ends on L: a seam, where L's corners on the start side take
    # U = 0 and those on the end side U = 1 (Fit). One straight strip.
    band, w = _d_band(lambda: fixtures.hole_rim(), -1)
    cut = w.solve(1.0, destructive=True)
    assert len(cut.breaks) == 1
    bm, build = _fixture_build(band, -1)
    seam = build.chain[3]                                            # L
    applied = bridge.apply_cut(bm, build, cut, w, destructive=True)
    bm.verts.index_update()
    bm.faces.index_update()
    assert len(applied.pieces) == 1
    strip, faces = bridge.stripe_for(build, applied, cut.width, 0)
    assert strip.near[0] == strip.near[-1] == seam.index and len(set(strip.near)) == len(strip.near) - 1
    stripe_bridge.apply_stripes(bm, [strip], faces, "FIT")
    assert max(_row_v_spreads(bm, [strip], faces)) <= 1e-6
    layer = bm.loops.layers.uv.active
    us = {round(lp[layer].uv.x, 6) for fid in strip.faces for lp in faces[fid].loops if lp.vert is seam}
    assert us == {0.0, 1.0}, us
    bm.free()


def test_apply_destructive_ring_inside_one_face_is_an_inset():
    # square_in_grid below its limit: the loop is a ring inside the one band face (face 4). D builds it as an inset:
    # the face is replaced by one inner quad and a ring quad on each chain edge, all with the face's attributes. D off
    # keeps refusing it, as master does. chamfer_ring: the ring has triangles where the chamfers' anchors merged.
    def mark(bm):  # face 4, the band: a material, smooth shading and an attribute of its own
        tag = bm.faces.layers.int.new("tag")
        bm.faces.ensure_lookup_table()
        bm.faces[4].material_index, bm.faces[4].smooth, bm.faces[4][tag] = 1, True, 7

    band, w = _d_band(lambda: fixtures.square_in_grid(), 1)
    for width in (0.25, 0.5, 0.999):
        cut = w.solve(width, destructive=True)
        bm, build = _fixture_build(band, 1, mark)
        tag = bm.faces.layers.int["tag"]
        before = topology.snapshot(bm)
        count = (len(bm.verts), len(bm.faces))
        try:
            bridge.apply_cut(bm, build, cut, w)
            raise AssertionError("D off built a ring inside one face")
        except ValueError as exc:
            assert str(exc) == bridge.INSIDE_ONE_FACE, exc
        assert (len(bm.verts), len(bm.faces)) == count
        assert bridge.preview_layers([build], [cut]) == ([], [], False)
        segs, pts, _clamped = bridge.preview_layers([build], [cut], destructive=True)
        assert len(segs) == 2 * 4 and len(pts) == 4
        applied = bridge.apply_cut(bm, build, cut, w, destructive=True)
        assert not applied.failures and len(applied.loop_edges) == 4
        assert topology.problems(bm, before) == []
        inside = [f for f in bm.faces if all(2.0 - 1e-6 <= c <= 4.0 + 1e-6 for v in f.verts for c in v.co.xy)]
        new = set(applied.loop_verts)
        assert sorted(len(f.verts) for f in inside) == [4] * 5
        assert sum(set(f.verts) == new for f in inside) == 1               # the inner quad
        assert all(len(set(f.verts) & set(build.chain)) == 2 for f in inside if set(f.verts) != new)
        assert all((f.material_index, f.smooth, f[tag]) == (1, True, 7) for f in inside)
        assert all(f.normal.z > 0.0 for f in inside)
        bm.verts.index_update()
        bm.faces.index_update()
        bridge.stripe_for(build, applied, cut.width)                         # the ring is one closed strip
        bm.free()
    band, w = _d_band(lambda: fixtures.chamfer_ring(), 1)
    lim = w.limit(destructive=True)
    for width in (lim * 0.1, lim * 0.4, lim * 0.7, lim - 1e-3):
        cut = w.solve(width, destructive=True)
        bm, build = _fixture_build(band, 1)
        assert bridge.preview_layers([build], [cut], destructive=True)[0], width
        bm.free()
        assert _d_cut_problems(band, 1, w, cut) == [], width


def _mesh_state(bm):
    """The mesh's vertex coordinates and faces (as vertex index tuples), to tell an untouched mesh."""
    bm.verts.index_update()
    return [tuple(v.co) for v in bm.verts], sorted(tuple(v.index for v in f.verts) for f in bm.faces)


def _built_or_refused(bm, build, cut, slider):
    """Apply ``cut`` (D) and say what came of it: "built", only when the topology is valid and no new edge is as
    short as the weld, or "refused: why", only when ``apply_cut`` raised before editing and the mesh is untouched."""
    before, state = topology.snapshot(bm), _mesh_state(bm)
    try:
        applied = bridge.apply_cut(bm, build, cut, slider, destructive=True)
    except ValueError as exc:
        assert _mesh_state(bm) == state
        return f"refused: {exc}"
    assert not applied.failures, applied.failures
    assert topology.problems(bm, before) == [], topology.problems(bm, before)
    shortest = min((e.calc_length() for e in bm.edges if not all(v in before.verts for v in e.verts)), default=1.0)
    assert shortest > build.weld, (shortest, build.weld)
    return "built"


def test_apply_destructive_inset_never_builds_invalid_topology():
    # One-face rings round their limits. At the limit and past it the L and U n-gons end as the walk round their
    # skeleton trees, on their arms' midlines: built as the tree, one face per chain edge (Task 5b; they were refused
    # as rings enclosing nothing). Just below it the core holds the tree already (the anchor snap below its fold), not
    # the sliver of a ring whose corners lay 8.5e-7 apart. The tilted cylinder cap's two points lie 4.2e-8 apart at the
    # limit: welded, they are the apex. Just below the limit the core's last ring is sub-micron: welded, it is the apex
    # too (the flat octagon, square_in_grid, chamfer_ring).
    for make, chain, outcomes in ((_l_ngon, range(6), {-3e-7: "built", 0.0: "built", 0.25: "built"}),
                                  (_u_ngon, range(8), {0.0: "built", 0.25: "built"}),
                                  (_cylinder_cap, range(8, 16), {0.0: "built", 0.25: "built"}),
                                  (_octagon, range(8), {-1e-6: "built"})):
        bm = make()
        w = wave.WaveSlider(_ring_build(bm, list(chain)).band)
        bm.free()
        lim = w.limit(destructive=True)
        for d, expected in outcomes.items():
            bm = make()
            outcome = _built_or_refused(bm, _ring_build(bm, list(chain)), w.solve(lim + d, destructive=True), w)
            assert outcome == expected, (make.__name__, d, outcome)
            bm.free()
    for make in (lambda: fixtures.square_in_grid(), lambda: fixtures.chamfer_ring()):
        band, w = _d_band(make, 1)
        lim = w.limit(destructive=True)
        for d in (1e-6, 3e-7, 1e-7, 1e-8):
            cut = w.solve(lim - d, destructive=True)
            assert _d_cut_problems(band, 1, w, cut) == [], (d, len(cut.points))
            bm, build = _fixture_build(band, 1)
            assert _built_or_refused(bm, build, cut, w) == "built", d
            bm.free()
    # square_in_grid at 1 - 1e-6: the ring's sides would be 2.0e-6 in double, but 1.907e-6 (the weld) between the float32
    # points the mesh holds. The apex is the loop's final state (used up, Task 6a fix round 1) from the snap below its
    # fold at 1 on, so the cut there is the apex itself: one new vertex, never four edges as short as the weld.
    band, w = _d_band(lambda: fixtures.square_in_grid(), 1)
    bm, build = _fixture_build(band, 1)
    count = len(bm.verts)
    assert _built_or_refused(bm, build, w.solve(1.0 - 1e-6, destructive=True), w) == "built"
    assert len(bm.verts) == count + 1
    bm.free()


def test_apply_destructive_reports_a_loop_crossing_itself():
    # chain_jittered_u(24, 0.25, 0.05, 0.8) at 0.936565: the core's loop crosses itself (segments 3-4 and 5-6),
    # where a part of it runs into another (Task 6 splits it there). The bridge refuses the cut before it edits
    # anything (the core is to split there instead: Task 6), as it refuses any cut it cannot build: the operator then
    # skips the chain with the reason and keeps its selection.
    band, w = _d_band(lambda: fixtures.chain_jittered_u(24, 0.25, 0.05, 0.8), 1)
    cut = w.solve(0.936565, destructive=True)
    bm, build = _fixture_build(band, 1)
    assert _built_or_refused(bm, build, cut, w) == "refused: " + bridge.LOOP_CROSSES
    bm.free()


def test_apply_destructive_builds_whole_or_refuses_before_any_edit():                  # 6a fix round 3
    # A face split that fails on the way (as where a second contact lands within 1e-6 of a fold) leaves no partial
    # build: the destructive mode builds the cut on a copy first and refuses it before touching the mesh.
    band, w = _d_band(lambda: fixtures.u_wall(), 1)
    cut = w.solve(0.47, destructive=True)
    bm, build = _fixture_build(band, 1)
    counts = (len(bm.verts), len(bm.edges), len(bm.faces))
    split, calls = bridge._split_face, []

    def fail_second(va, vb, coords, *probe):
        calls.append(None)
        return None if len(calls) == 2 else split(va, vb, coords, *probe)

    bridge._split_face = fail_second
    try:
        bridge.apply_cut(bm, build, cut, w, destructive=True)
        raise AssertionError("a cut with a failing face split was built")
    except ValueError as exc:
        assert str(exc) == bridge.PIECE_FAILED, exc
    finally:
        bridge._split_face = split
    assert (len(bm.verts), len(bm.edges), len(bm.faces)) == counts
    bm.free()


def test_stripe_for_a_failed_cut_with_breaks_raises():
    # u_wall at 0.47 with its second face split failing: the cut is incomplete, so no piece has a strip; asking for any
    # piece raises the strip's ValueError (Task 9 catches it), never an AssertionError. (The trial build on a copy,
    # which refuses such a cut before any edit, is bypassed: this is the failure it did not foresee.)
    band, w = _d_band(lambda: fixtures.u_wall(), 1)
    cut = w.solve(0.47, destructive=True)
    bm, build = _fixture_build(band, 1)
    split, trial, calls = bridge._split_face, bridge._trial_failure, []

    def fail_second(va, vb, coords, *probe):
        calls.append(None)
        return None if len(calls) == 2 else split(va, vb, coords, *probe)

    bridge._split_face = fail_second
    bridge._trial_failure = lambda *args: None
    try:
        applied = bridge.apply_cut(bm, build, cut, w, destructive=True)
    finally:
        bridge._split_face, bridge._trial_failure = split, trial
    assert applied.failures and len(applied.pieces) == 3 and not applied.piece_strips
    bm.verts.index_update()
    bm.faces.index_update()
    for piece in range(3):
        try:
            bridge.stripe_for(build, applied, cut.width, piece)
            raise AssertionError(f"piece {piece} of a failed cut has a strip")
        except ValueError as exc:
            assert str(exc) == bridge.NO_STRIP_FACES, exc
    bm.free()


# --- destructive mode (D) in the operator --------------------------------------------

def _bands_mesh(*placed):
    """One mesh of the fixture bands ``(band, dx)``, each moved ``dx`` along x, all their chains selected.

    Returns (bmesh, [each chain's vertex ids]); the vertex and face ids of a band follow the previous one's.
    """
    points, faces, chains = [], [], []
    for band, dx in placed:
        base = len(points)
        ids, fids = sorted(band.verts), sorted(band.faces)
        assert ids == list(range(len(ids))) and fids == list(range(len(fids)))
        points += [(band.verts[i][0] + dx, band.verts[i][1], band.verts[i][2]) for i in ids]
        faces += [tuple(base + i for i in band.faces[f]) for f in fids]
        chains.append([base + i for i in band.chain] + ([base + band.chain[0]] if band.closed else []))
    bm = _mesh(points, faces)
    for chain in chains:
        _select_chain(bm, chain)
    return bm, chains


def _all_edges(obj):
    return _read(obj, lambda bm: {_edge_key(*(v.co for v in e.verts)) for e in bm.edges})


def test_d_toggles_destructive_and_restores_collapse():   # Review Focus 4
    band = fixtures.u_in_grid()
    _edit_object(_band_mesh(band), chain=band.chain)
    width = 1.2 * core.Slider(_fixture_build(band, 1)[1].band).limit()   # past the plain limit
    op, ctx = _invoke(x=0, width=width, chain_sides="+")
    op.chain_sides = "+"
    op._rebuild_preview()
    assert op.use_collapse is False and op.use_destructive is False
    _keys(op, ctx, "C")
    assert op.use_collapse is True
    collapsed = [_key(p) for p in op._preview_segs]
    _keys(op, ctx, "D")
    assert op.use_destructive is True and op.use_collapse is True
    _keys(op, ctx, "C")                                               # does nothing while D is on
    assert op.use_collapse is True and op.use_destructive is True
    _keys(op, ctx, "D")
    assert op.use_destructive is False and op.use_collapse is True
    assert [_key(p) for p in op._preview_segs] == collapsed
    build, _slider = op._sides[0][1]
    segs, _points, clamped = bridge.preview_layers([build], [core.Slider(build.band).solve(width, collapse=True)])
    assert [_key(p) for p in op._preview_segs] == [_key(p) for p in segs] and op._clamped == clamped
    op._finish(ctx)


def test_d_off_gives_collapse_back_as_it_was():
    _edit_object(_strip(), chain=[0, 1, 2, 3])
    op, ctx = _invoke(x=0, width=0.25)
    _keys(op, ctx, "D D")
    assert op.use_destructive is False and op.use_collapse is False
    _keys(op, ctx, "D C D")                                           # C while D is on changes nothing
    assert op.use_collapse is False
    op._finish(ctx)


def test_modal_d_hud_help_status_and_cancel():
    _edit_object(_strip(), chain=[0, 1, 2, 3])
    op, ctx = _invoke(x=0, width=0.25)
    params = {p.name: p for section in op._hud.param_sections for p in section.params}
    assert list(params)[:6] == [
        "Width", "Exact Width (E)", "Allow Collapse (C)", "Destructive (D)", "Auto Adjust (Q)", "UV Stripe (U)"]
    legend = [(it.label, it.key) for it in op._help.sections[0].items]
    assert legend.index(("Destructive", "D")) == legend.index(("Allow collapse", "C")) + 1
    assert "destructive = off (D)" in op._status_text()
    assert params["Destructive (D)"].value_text() == "✗" and params["Allow Collapse (C)"].is_active()
    _keys(op, ctx, "D")
    assert "destructive = on (D)" in op._status_text()
    assert "allow collapse = on (C)" in op._status_text()            # as the HUD shows it, though C is off
    assert params["Destructive (D)"].value_text() == "✓"
    assert params["Allow Collapse (C)"].value_text() == "✓" and not params["Allow Collapse (C)"].is_active()
    _keys(op, ctx, "D")
    assert "allow collapse = off (C)" in op._status_text()           # C's own value comes back
    _keys(op, ctx, "D")
    assert op._modal(ctx, _event("ESC")) == {'CANCELLED'}
    assert op.use_destructive is False                               # the invoke snapshot, not the toggle's start


def _worst_limit_ms(op, exact):
    """The slowest ``limit(destructive=True)`` over every side of every chain, in ms: cached once its wave is paid."""
    worst = 0.0
    for found in op._sides:
        for _build, slider in found.values():
            start = time.perf_counter()
            slider.limit(exact=exact, destructive=True)
            worst = max(worst, (time.perf_counter() - start) * 1000.0)
    return worst


def test_modal_d_pays_the_first_wave_of_every_side_when_switched_on():
    # Both sides of the chain are warm after D on, after invoke with D on and after E with D on, so no later mouse
    # move (through width 0, onto the other side) pays a wave. A fresh wave is 300+ ms on this mesh.
    chain = list(range(50 * 100 + 25, 50 * 100 + 76))
    _edit_object(_grid(100, 100), chain=chain)
    op, ctx = _invoke(x=0, width=0.05)
    assert sorted(op._sides[0]) == [-1, 1]
    _keys(op, ctx, "D")
    assert _worst_limit_ms(op, False) < 20.0
    _keys(op, ctx, "E")                                                # a new exact mode: its waves are paid here
    assert _worst_limit_ms(op, True) < 20.0
    op._finish(ctx)
    _edit_object(_grid(100, 100), chain=chain)
    op, ctx = _invoke(x=0, width=0.05, use_destructive=True)           # D on at invoke: paid there
    assert _worst_limit_ms(op, False) < 20.0
    op._finish(ctx)


def test_per_chain_limits_in_destructive():   # Review Focus 1
    # square_in_grid has a D limit of 1.0 (its apex is built past it), u_wall 1.4849256547: at 1.2 only the square
    # reports clamped, and both chains are cut.
    wall, square = fixtures.u_wall(), fixtures.square_in_grid()
    bm, chains = _bands_mesh((wall, 0.0), (square, 20.0))
    obj = _edit_object(bm, chain=None)
    op, ctx = _invoke(x=0, width=1.2, chain_sides="++", use_destructive=True)
    op.chain_sides = "++"
    clamped = {}
    for i, found in enumerate(op._sides):
        build, slider = found[op._side(i)]
        clamped[build.band.chain[0]] = slider.solve(1.2, destructive=True).clamped
    assert len(clamped) == 2, clamped
    assert clamped == {0: False, len(wall.verts) + 5: True}, clamped   # per chain, not per cut
    op._rebuild_preview()
    clamped_param = next(p for sec in op._hud.param_sections for p in sec.params if p.name == "Clamped")
    assert op._clamped is True and clamped_param.value_text() == "✓"       # the square's, shown
    op._finish(ctx)
    _edit_object(_bands_mesh((fixtures.u_wall(), 0.0))[0], chain=None)
    op, ctx = _invoke(x=0, width=1.2, chain_sides="+", use_destructive=True)
    op.chain_sides = "+"
    op._rebuild_preview()
    clamped_param = next(p for sec in op._hud.param_sections for p in sec.params if p.name == "Clamped")
    assert op._preview_segs and op._clamped is False and clamped_param.value_text() == "✗"   # u_wall alone: not
    op._finish(ctx)
    obj = _edit_object(*_bands_mesh((wall, 0.0), (square, 20.0))[:1], chain=None)
    run = _OperatorStandIn(width=1.2, chain_sides="++", use_destructive=True)
    assert run.execute(bpy.context) == {'FINISHED'} and not run.reports, run.reports
    new = _new_coords(obj)
    assert any(co[0] < 7.0 for co in new) and any(co[0] > 20.0 for co in new)   # u_wall's cut and the square's apex
    assert (23.0, 3.0, 0.0) in new                                    # the apex, the centre of the square's one face


# --- relay (D): a slide passed on from row to row of existing edges --------------------------------------------------


def _ladder_rows(band, rows=(1, 2, 3), n=4):
    """The vertex ids of ``zigzag_ladder``'s rows ``rows``, each in order."""
    return [[r * (n + 1) + i for i in range(n + 1)] for r in rows]


def test_relay_passes_the_rows_of_a_zigzag_ladder():
    # zigzag_ladder: the default mode stops at row 1 (width 1), D holds the ends there. Relayed, D passes the baton to
    # rows 1, 2 and 3, at widths 1, 2 and 3, and stops at the top row at 4; with a row 5% off parallel, close to that.
    for tilt, tol in ((0.0, 1e-4), (0.05, 0.02)):
        band = fixtures.zigzag_ladder(tilt=tilt)
        bm, build = _fixture_build(band, +1)
        slider = wave.WaveSlider(build.band)
        assert abs(slider.limit() - 1.0) < 1e-4, slider.limit()
        for exact in (False, True):
            relay = bridge.Relay(bm, build, slider, 0.0, wave.WaveSlider)
            stages = relay.stages(exact)
            assert len(stages) == 4, [s.offset for s in stages]
            assert [[v.index for v in s.build.chain] for s in stages[1:]] == _ladder_rows(band)
            assert all(abs(s.offset - k) < tol for k, s in enumerate(stages)), [s.offset for s in stages]
            total = stages[-1].offset + stages[-1].slider.limit(exact=exact, destructive=True)
            assert abs(total - 4.0) < tol, total
            for width in (0.5, 1.5, 2.5, 3.5):                      # a straight row at y = width, from its own leg
                stage = relay.stage_at(width, exact)
                assert stage is stages[int(width)]
                cut = stage.slider.solve(width - stage.offset, exact=exact, destructive=True)
                assert len(cut.points) == 5 and not cut.clamped
                assert all(abs(p.co[1] - width) <= (1e-4 if tilt == 0.0 else 0.05) for p in cut.points), cut.points
        bm.free()


def test_relay_leaves_a_slide_that_goes_on_by_itself():
    # No relay, D unchanged: a grid row (the loop lies on each row it passes, its ends moving on), shoot_strip (an end
    # shot on), u_wall and square_in_grid keep their one leg.
    for band in (fixtures.jittered_grid(0, jitter=0.0), fixtures.shoot_strip(), fixtures.u_wall(),
                 fixtures.square_in_grid()):
        bm, build = _fixture_build(band, +1)
        slider = wave.WaveSlider(build.band)
        for exact in (False, True):
            stages = bridge.Relay(bm, build, slider, 0.0, wave.WaveSlider).stages(exact)
            assert len(stages) == 1 and stages[0].slider is slider and stages[0].offset == 0.0
        bm.free()



def test_relay_match_is_taken_at_the_width_the_loop_meets_the_row():
    # zigzag_ladder at 0.914: each point lies 0.0962 down its rung (1.118 long) from row 1, more than a tenth of 0.914
    # but within a tenth of the width it meets the row at. The match takes that width: the loop lies on row 1.
    band = fixtures.zigzag_ladder()
    bm, build = _fixture_build(band, +1)
    slider = wave.WaveSlider(build.band)
    w0 = 0.914
    cut = slider.solve(w0, destructive=True)
    gap = max(min((Vector(p.co) - bm.verts[v].co).length for v in _ladder_rows(band, rows=(1,))[0]) for p in cut.points)
    assert bridge.RELAY_MATCH_FRACTION * w0 < gap <= bridge.relay_match(build, 0.0, w0), gap
    assert bridge.relay_chain(build, cut, bridge.RELAY_MATCH_FRACTION * w0) is None      # at the stopped width: short
    found = bridge.relay_chain(build, cut, bridge.relay_match(build, 0.0, w0))
    assert [v.index for v in found] == _ladder_rows(band, rows=(1,))[0], found
    bm.free()


def test_relay_chain_drops_a_shot_end_past_the_row():
    # The loop on row 1 of zigzag_ladder, its end (start) running on past the row's last (first) vertex, as an end
    # that shot on past its end edge does: with that end shot, the part past the row is the shot and the loop lies on
    # the row. Unshot, or with the tail reaching back to the segment's anchor, it lies on no row.
    band = fixtures.zigzag_ladder()
    bm, build = _fixture_build(band, +1)
    cut = wave.WaveSlider(build.band).solve(1.0, destructive=True)
    row = _ladder_rows(band, rows=(1,))[0]
    assert len(cut.points) == 5 and cut.anchors == [0, 1, 2, 3, 4], cut
    m = bridge.relay_match(build, 0.0, 1.0)

    def past(x, face):
        return core.SurfacePoint(kind="face", face=face, co=(x, 1.0, 0.0))

    end = dataclasses.replace(cut, points=[*cut.points, past(5.2, 7), past(5.8, 7)], anchors=[0, 1, 2, 3, 6])
    start = dataclasses.replace(cut, points=[past(-0.6, 4), *cut.points], anchors=[0, 2, 3, 4, 5])
    assert bridge.relay_chain(build, end, m) is None and bridge.relay_chain(build, start, m) is None
    assert [v.index for v in bridge.relay_chain(build, end, m, (False, True))] == row
    assert [v.index for v in bridge.relay_chain(build, start, m, (True, False))] == row
    assert bridge.relay_chain(build, end, m, (True, False)) is None                  # the other end shot: not this one
    short = dataclasses.replace(end, points=[*cut.points[:4], past(5.2, 7)], anchors=[0, 1, 2, 3, 4])
    assert bridge.relay_chain(build, short, m, (False, True)) is None                # the segment never reaches the row
    bm.free()


def test_relay_knows_when_an_end_has_shot_past_its_end_edge():
    # shoot_strip: the start's end wall ends at v, which the loop's start reaches at width 1, and shoots on past it.
    band = fixtures.shoot_strip()
    bm, build = _fixture_build(band, +1)
    ends = bridge.Relay._end_snaps(build, wave.WaveSlider(build.band), False)
    assert ends[0] is not None and abs(ends[0] - 1.0) < 1e-4, ends
    assert bridge.Relay._candidates(ends, 3.0) == sorted({3.0, *(w for w in ends if w is not None and 0 < w <= 3)})
    bm.free()

def test_execute_destructive_cuts_past_the_relays():
    # The cut at 3.5 is row 3's at 0.5: five new vertices on its rungs, nothing between the chain and row 3, valid
    # topology, and the new loop selected. With D off it stops at row 1, as before.
    for tilt in (0.0, 0.05):
        band = fixtures.zigzag_ladder(tilt=tilt)
        obj = _edit_object(_band_mesh(band), chain=band.chain)
        run = _OperatorStandIn(width=3.5, chain_sides="+", use_destructive=True)
        assert run.execute(bpy.context) == {'FINISHED'} and not run.reports, run.reports
        new = _new_coords(obj)
        assert len(new) == 5 and _counts(obj) == (30, 20), (new, _counts(obj))
        assert all(3.5 - 1e-5 <= co[1] <= 3.5 + (1e-5 if tilt == 0.0 else 0.05) for co in new), new
        selected = _selected_edges(obj)
        assert len(selected) == 4 and {p for e in selected for p in e} == new, selected
        assert not _validate_fixed_something(obj)
    band = fixtures.zigzag_ladder()
    obj = _edit_object(_band_mesh(band), chain=band.chain)
    run = _OperatorStandIn(width=3.5, chain_sides="+")
    run.execute(bpy.context)
    assert all(co[1] <= 1.0 + 1e-5 for co in _new_coords(obj)), _new_coords(obj)


def test_modal_destructive_relays_preview_clamp_and_snap():
    # The preview and Clamped follow the total width, and Ctrl snaps onto a vertex past the relays: row 3's (2.5, 3),
    # at width 3, which the first leg's own slide (its ends held on row 1) would reach at another width.
    band = fixtures.zigzag_ladder()
    _edit_object(_band_mesh(band), chain=band.chain)
    op, ctx = _invoke(x=0, width=2.5, use_destructive=True)
    op.chain_sides = "+"
    op._rebuild_preview()
    assert op._preview_segs and {round(p.y, 5) for p in op._preview_segs} == {2.5} and not op._clamped
    op.width = 3.9
    op._rebuild_preview()
    assert {round(p.y, 4) for p in op._preview_segs} == {3.9} and not op._clamped
    op.width = 4.5                                                     # past the last leg's limit, 4: clamped
    op._rebuild_preview()
    assert op._clamped
    op._mouse_world = lambda _ctx, _mouse: Vector((2.5, 3.0, 0.0))
    assert op._modal(ctx, _move(1, ctrl=True)) == {'RUNNING_MODAL'}
    assert op._snap_co is not None and abs(op.width - 3.0) < 1e-4, op.width
    op._finish(ctx)


def test_modal_move_budget_destructive():
    # A 100 x 100 grid, a chain of 50 edges, D on. After the toggle no mouse move pays a wave: every ``limit()`` a move
    # makes is a cached answer (under 5 ms). And every move (the drag through width 0 onto the other side, a first
    # Ctrl snap onto a vertex of the other band, 20 width changes) stays under a loose ceiling that catches gross
    # regressions: the 30 ms goal is read off the printed numbers, as wall-clock spikes on a busy machine are not bugs.
    chain = list(range(50 * 100 + 25, 50 * 100 + 76))
    limit, limit_ms = wave.WaveSlider.limit, []

    def timed_limit(self, *args, **kwargs):
        began = time.perf_counter()
        try:
            return limit(self, *args, **kwargs)
        finally:
            limit_ms.append((time.perf_counter() - began) * 1000.0)

    def timed(op, ctx, event):
        began = time.perf_counter()
        assert op._modal(ctx, event) == {'RUNNING_MODAL'}
        return (time.perf_counter() - began) * 1000.0

    obj = _edit_object(_grid(100, 100), chain=chain)
    op, ctx = _invoke(x=0, width=0.05)
    op.chain_sides = "+"
    start = time.perf_counter()
    _keys(op, ctx, "D")
    toggle = (time.perf_counter() - start) * 1000.0
    wave.WaveSlider.limit = timed_limit
    try:
        crossing = [timed(op, ctx, _move(x)) for x in (20, 0, -20, -40)]  # width 0.1 -> 0 -> -0.1: through 0
        assert op.width < 0.0
        times = [timed(op, ctx, _move(40 * k)) for k in range(1, 21)]
        assert op._preview_segs and abs(op.width - 2.05) < 1e-6
        op._finish(ctx)

        wave.WaveSlider.limit = limit                                      # the second toggle pays its waves
        _edit_object(_grid(100, 100), chain=chain)
        op, ctx = _invoke(x=0, width=0.05)
        op.chain_sides = "+"
        _keys(op, ctx, "D")
        wave.WaveSlider.limit = timed_limit
        op._mouse_world = lambda _ctx, _mouse: Vector((40.0, 49.0, 0.0))  # a vertex of the band on the other side
        snap = timed(op, ctx, _move(1, ctrl=True))
        assert op._snap_co is not None and op.width < 0.0                 # it reached it: negative, the other side
        op._finish(ctx)
    finally:
        wave.WaveSlider.limit = limit
    print(f"      D toggle {toggle:.0f} ms; first Ctrl snap onto the other band {snap:.1f} ms; through width 0 (ms): "
          + " ".join(f"{t:.1f}" for t in crossing) + "; moves ms: " + " ".join(f"{t:.1f}" for t in times)
          + f" (max {max(times):.1f}, mean {sum(times) / len(times):.1f}); "
          + f"{len(limit_ms)} limit() calls, slowest {max(limit_ms):.2f} ms")
    assert limit_ms and max(limit_ms) < 5.0, limit_ms                    # every one from the cache
    assert max([snap, *crossing, *times]) <= 250.0, (snap, crossing, times)
    assert obj.name


def test_redo_from_props_matches_the_confirmed_destructive_cut():
    # The confirmed cut is the redo's: execute() from the same props gives the same vertices and edges, past a wall hit
    # (u_wall), into an apex (square_in_grid) and on a fanned U.
    for make, width in ((lambda: fixtures.u_wall(), 0.75), (lambda: fixtures.square_in_grid(), 1.2),
                        (lambda: fixtures.fanned_u(), 0.6)):
        outcomes = []
        for _ in range(2):
            band = make()
            obj = _edit_object(_band_mesh(band), chain=band.chain + ([band.chain[0]] if band.closed else []))
            op = _OperatorStandIn(width=width, chain_sides="+", use_destructive=True)
            assert op.execute(bpy.context) == {'FINISHED'}, op.reports
            outcomes.append((_coords(obj), _all_edges(obj), _selected_edges(obj)))
        assert outcomes[0] == outcomes[1] and len(outcomes[0][0]) > len(band.verts)


def _loop_pieces(obj):
    """The selected edges of ``obj`` as connected pieces: a list of sets of rounded vertex coordinates."""
    pieces = []
    for p, q in _selected_edges(obj):
        joined = [piece for piece in pieces if p in piece or q in piece]
        merged = {p, q}.union(*joined)
        pieces = [piece for piece in pieces if piece not in joined] + [merged]
    return pieces


def test_execute_destructive_u_wall_opens_the_loop():
    # u_wall at 0.75 (past its wall hit at 0.439340): two breaks, three pieces. No edge runs across a break, each
    # end of a break is a new vertex on a hole's side, and the three pieces are the selected loop.
    band, w = _d_band(lambda: fixtures.u_wall(), 1)
    cut = w.solve(0.75, destructive=True)
    assert len(cut.breaks) == 2
    obj = _edit_object(_band_mesh(band), chain=band.chain)
    op = _OperatorStandIn(width=0.75, chain_sides="+", use_destructive=True)
    assert op.execute(bpy.context) == {'FINISHED'} and not op.reports, op.reports
    for i in cut.breaks:
        ends = [tuple(cut.points[j].co) for j in (i - 1, i)]
        assert all(_key(co) in _coords(obj) for co in ends), ends
        assert not _edge_between(obj, *ends), f"an edge across break {i}"
    pieces = _loop_pieces(obj)
    assert len(pieces) == 3, [len(piece) for piece in pieces]
    for i in cut.breaks:                       # a break's two ends belong to two different pieces
        ends = [_key(cut.points[j].co) for j in (i - 1, i)]
        assert not any(ends[0] in piece and ends[1] in piece for piece in pieces)


def test_execute_skips_a_refused_chain_and_cuts_the_other():
    # chain_jittered_u(24, 0.25, 0.05, 0.8) at 0.936565 refuses before any edit (the loop crosses itself): the chain is
    # skipped with the reason, nothing is cut or selected for it, and the clean chain beside it is cut.
    crossing, clean = fixtures.chain_jittered_u(24, 0.25, 0.05, 0.8), fixtures.fanned_u()
    bm, chains = _bands_mesh((crossing, 0.0), (clean, 30.0))
    obj = _edit_object(bm, chain=None)
    count_left = _read(obj, lambda b: sum(v.co.x < 15.0 for v in b.verts))
    op = _OperatorStandIn(width=0.936565, chain_sides="++", use_destructive=True)
    assert op.execute(bpy.context) == {'FINISHED'}
    assert op.reports == [f"Smart Edge Slide: chain skipped ({bridge.LOOP_CROSSES})"], op.reports
    assert _read(obj, lambda b: sum(v.co.x < 15.0 for v in b.verts)) == count_left        # nothing cut there
    picked = _selected_edges(obj)
    assert picked and all(min(p[0][0], p[1][0]) > 15.0 for p in picked)                    # only the clean chain's loop


def test_execute_destructive_uv_stripe_per_piece():
    # u_wall at 0.47: three pieces, each its own strip; at 0.75 no piece separates, and each is skipped with the reason.
    for width, skipped in ((0.47, 0), (0.75, 3)):
        band = fixtures.u_wall()
        obj = _edit_object(_band_mesh(band), chain=band.chain)
        op = _OperatorStandIn(width=width, chain_sides="+", use_destructive=True, use_uv_stripe=True)
        assert op.execute(bpy.context) == {'FINISHED'}
        warnings = [r for r in op.reports if "UV Stripe skipped" in r]
        assert warnings == [f"Smart Edge Slide: UV Stripe skipped ({bridge.PIECE_OPEN_SIDE})"] * skipped, op.reports
        assert len(op.reports) == skipped, op.reports
        assert _read(obj, lambda bm: bool(bm.loops.layers.uv)) == (skipped == 0)


def test_modal_ctrl_snap_in_d_reaches_what_only_d_reaches():
    # u_wall's hole corner d (1.3, 3.6) is reached by the destructive loop at 0.636397 (the plain loop stops at 0.439340,
    # before it). The snap asks the mode it is in, and its cached answer is per mode.
    band = fixtures.u_wall()
    _edit_object(_band_mesh(band), chain=band.chain)
    op, ctx = _invoke(x=0, width=0.05, chain_sides="+", use_collapse=True)
    op.chain_sides = "+"
    k = next(k for k, (_kind, co) in enumerate(op._snap_points) if _key(co) == (1.3, 3.6, 0.0))
    plain = op._snap_width(k)
    assert plain is None or abs(plain - 0.636397) > 1e-3, plain
    op.use_destructive = True
    width = op._snap_width(k)
    assert width is not None and abs(width - 0.636397) < 1e-5, width
    op.use_destructive = False                                         # the cache is per mode
    assert op._snap_width(k) == plain
    op._finish(ctx)


def test_modal_preview_in_d_shows_the_apex():
    # square_in_grid at 1.2: its D limit is 1.0 (clamped there), where the loop is the apex at the centre (3, 3).
    # The plain mode refuses a ring inside one face: nothing is drawn.
    band = fixtures.square_in_grid()
    _edit_object(_band_mesh(band), chain=band.chain + [band.chain[0]])
    op, ctx = _invoke(x=0, width=1.2, chain_sides="+", use_destructive=True)
    op.chain_sides = "+"
    op._rebuild_preview()
    inward = [_key(p) for p in op._preview_points]
    if (3.0, 3.0, 0.0) not in inward:
        op.chain_sides = "-"
        op._rebuild_preview()
        inward = [_key(p) for p in op._preview_points]
    assert (3.0, 3.0, 0.0) in inward and op._clamped, inward
    op._finish(ctx)


def test_modal_preview_leaves_out_a_chain_confirm_refuses():
    # chain_jittered_u(24, .25, .05, .8) at 0.936565: the cut's loop crosses itself, which apply_cut refuses before
    # any edit. The preview draws nothing for it, as it draws nothing for a cut master refuses, and the confirm skips
    # the chain with the reason. A clean chain beside it is drawn and cut.
    crossing, clean = fixtures.chain_jittered_u(24, 0.25, 0.05, 0.8), fixtures.fanned_u()
    bm, _chains = _bands_mesh((crossing, 0.0), (clean, 30.0))
    obj = _edit_object(bm, chain=None)
    op, ctx = _invoke(x=0, width=0.936565, chain_sides="++", use_destructive=True)
    op.chain_sides = "++"
    op._rebuild_preview()
    assert op._preview_segs and all(p.x > 15.0 for p in op._preview_segs)   # only the clean chain
    op._finish(ctx)
    run = _OperatorStandIn(width=0.936565, chain_sides="++", use_destructive=True)
    assert run.execute(bpy.context) == {'FINISHED'}
    assert run.reports == [f"Smart Edge Slide: chain skipped ({bridge.LOOP_CROSSES})"], run.reports
    assert obj.name


def test_preview_layers_draw_nothing_for_a_reversed_ring():
    # A ring inside one face that runs round it the other way (the octagon's inset mirrored in its centre line y = 0,
    # its points in the same order) is refused before any edit (RING_REVERSED), and the preview draws nothing for it,
    # by its own check: with the crossing check blind it is still left out. The L and U n-gons' trees at and past their
    # limits, once refused as rings enclosing nothing, are built and drawn (Task 5b).
    bm = _octagon()
    build = _ring_build(bm, list(range(8)))
    w = wave.WaveSlider(build.band)
    cut = w.solve(0.5 * w.limit(destructive=True), destructive=True)
    mirrored = [dataclasses.replace(p, co=(p.co[0], -p.co[1], p.co[2])) for p in cut.points]
    reverse = dataclasses.replace(cut, points=mirrored, connectors=[])
    assert _built_or_refused(bm, build, reverse, w) == "refused: " + bridge.RING_REVERSED
    assert bridge.preview_layers([build], [reverse], destructive=True)[:2] == ([], [])
    crossing = bridge._crossing
    try:
        bridge._crossing = lambda *_args: None
        assert bridge.preview_layers([build], [reverse], destructive=True)[:2] == ([], []), "reversed ring"
    finally:
        bridge._crossing = crossing
    bm.free()
    for make, chain in ((_l_ngon, range(6)), (_u_ngon, range(8))):
        bm = make()
        build = _ring_build(bm, list(chain))
        w = wave.WaveSlider(build.band)
        for d in (0.0, 0.25):
            cut = w.solve(w.limit(destructive=True) + d, destructive=True)
            assert bridge.preview_layers([build], [cut], destructive=True)[0], (make.__name__, d)
        bm.free()


def test_preview_layers_draw_nothing_for_a_refused_destructive_cut():
    band, w = _d_band(lambda: fixtures.chain_jittered_u(24, 0.25, 0.05, 0.8), 1)
    cut = w.solve(0.936565, destructive=True)
    bm, build = _fixture_build(band, 1)
    assert _built_or_refused(bm, build, cut, w) == "refused: " + bridge.LOOP_CROSSES
    assert bridge.preview_layers([build], [cut], destructive=True)[:2] == ([], [])
    bm.free()


def test_execute_destructive_in_place_stripes_use_each_pieces_own_uvs():
    # u_wall at 0.47, three pieces, planar UVs. In Place centres each strip on its own faces' old UVs: three strips, at
    # three places, each the centre of its own faces' bounding box (not of all the pieces' faces together).
    band = fixtures.u_wall()
    bm = _band_mesh(band)
    _add_uvs(bm)
    _edit_object(bm, chain=band.chain)
    seen = []
    apply_stripes = stripe_bridge.apply_stripes

    def spy(bm_, strips, faces, mode, contexts=None):
        # Each strip's faces' bounding box centre in x and y, read before the stripe moves anything.
        boxes = []
        for strip in strips:
            xs = [v.co.x for fid in strip.faces for v in faces[fid].verts]
            ys = [v.co.y for fid in strip.faces for v in faces[fid].verts]
            boxes.append(((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2))
        seen.append((boxes, contexts))
        return apply_stripes(bm_, strips, faces, mode, contexts)

    stripe_bridge.apply_stripes = spy
    try:
        op = _OperatorStandIn(width=0.47, chain_sides="+", use_destructive=True, use_uv_stripe=True,
                              uv_stripe_mode="IN_PLACE")
        assert op.execute(bpy.context) == {'FINISHED'} and not op.reports, op.reports
    finally:
        stripe_bridge.apply_stripes = apply_stripes
    boxes, contexts = seen[0]
    assert len(boxes) == 3 and len(contexts) == 3 and None not in contexts
    for box, context in zip(boxes, contexts):
        assert abs(context.center[0] - box[0]) < 1e-6 and abs(context.center[1] - box[1]) < 1e-6, (context.center, box)
    centers = {(round(c.center[0], 3), round(c.center[1], 3)) for c in contexts}
    assert len(centers) == 3, centers


def _capped_cylinder(sides):
    """A capped cylinder of radius 1 and height 2 with ``sides`` sides, its top ring (z = 1) selected."""
    bm = bmesh.new()
    bmesh.ops.create_cone(bm, cap_ends=True, cap_tris=False, segments=sides, radius1=1.0, radius2=1.0, depth=2.0)
    for e in bm.edges:
        e.select = all(abs(v.co.z - 1.0) < 1e-5 for v in e.verts)
    return bm


NGON_WARNING = "Smart Edge Slide: Destructive is off for a chain next to a face with more than 48 sides"


def _same_points(points, coords, tol=1e-5):
    """Whether ``points`` (the preview's) and ``coords`` (new vertex coordinates) are the same points, within ``tol``."""
    coords = [Vector(co) for co in coords]
    return len(points) == len(coords) and all(min((Vector(p) - q).length for q in coords) < tol for p in points)


def test_destructive_is_off_next_to_a_face_with_more_than_48_sides():
    # The top ring of a 64-sided capped cylinder: both its bands hold a 64-sided cap. With D on the chain is cut as with
    # Allow Collapse, with one warning, and D costs nothing: toggling it and confirming took about 2.7 s and 1.6 s.
    # The 32-sided cylinder keeps D.
    obj = _edit_object(_capped_cylinder(64), chain=None)
    op, ctx = _invoke(x=0, width=0.3)
    start = time.perf_counter()
    _keys(op, ctx, "D")
    toggle = time.perf_counter() - start
    builds = [build for found in op._sides for build, _slider in found.values()]
    assert len(builds) == 2 and all(build.max_face_sides == 64 and not op._destructive_for(build) for build in builds)
    drawn = [Vector(p) for p in op._preview_points]
    sides = op.chain_sides
    start = time.perf_counter()
    assert op._modal(ctx, _event("RET")) == {'FINISHED'}
    confirm = time.perf_counter() - start
    assert op.reports == [NGON_WARNING], op.reports
    assert toggle < 1.0 and confirm < 1.0, (toggle, confirm)
    cut = _new_coords(obj)
    assert drawn and _same_points(drawn, cut)
    obj = _edit_object(_capped_cylinder(64), chain=None)
    collapse = _OperatorStandIn(width=0.3, chain_sides=sides, use_collapse=True)
    assert collapse.execute(bpy.context) == {'FINISHED'} and not collapse.reports, collapse.reports
    assert _new_coords(obj) == cut                                     # the cut Allow Collapse makes
    _edit_object(_capped_cylinder(32), chain=None)
    op, ctx = _invoke(x=0, width=0.3, use_destructive=True)
    builds = [build for found in op._sides for build, _slider in found.values()]
    assert len(builds) == 2 and all(build.max_face_sides == 32 and op._destructive_for(build) for build in builds)
    op._finish(ctx)


def test_destructive_limit_is_the_largest_width_that_builds():
    # square_in_grid, D limit 1.0, with every trial build of a cut wider than 0.8 refused: once the width reaches the
    # limit, the chain's limit drops to the largest width that builds (bisected, at most 12 trials after the one at
    # the limit), once per chain and side. The preview clamps there and confirm builds what it drew; a width below
    # the limit pays no trial.
    band = fixtures.square_in_grid()
    obj = _edit_object(_band_mesh(band), chain=band.chain + [band.chain[0]])
    trial, widths = bridge._trial_failure, []

    def refuse_wide(bm, build, cut, slider, tolerance):
        widths.append(cut.width)
        return "refused" if cut.width > 0.8 else trial(bm, build, cut, slider, tolerance)

    bridge._trial_failure = refuse_wide
    try:
        op, ctx = _invoke(x=0, width=0.5, chain_sides="+", use_destructive=True)
        op.chain_sides = "+"
        op._preview_key = None
        op._rebuild_preview()
        assert not widths, widths
        build, slider = op._sides[0][op._side(0)]
        assert abs(slider.limit(destructive=True) - 1.0) < 1e-3, slider.limit(destructive=True)
        op.width = 1.2
        op._rebuild_preview()
        limit = slider.limit(destructive=True)
        assert 0.75 < limit <= 0.8 and build.built_limits == {(False, 0.0): limit}, (limit, build.built_limits)
        assert op._clamped and 2 <= len(widths) <= 13, widths
        trials = len(widths)
        op.width = 1.3
        op._rebuild_preview()
        assert len(widths) == trials and op._clamped
        drawn = [Vector(p) for p in op._preview_points]
        assert drawn
        assert op._modal(ctx, _event("RET")) == {'FINISHED'}
        assert not op.reports, op.reports
    finally:
        bridge._trial_failure = trial
    assert _same_points(drawn, _new_coords(obj)), (drawn, _new_coords(obj))


def test_execute_destructive_selects_a_lone_points_vertex():
    # square_in_grid at 1.2 in D: the loop is the apex at the square's centre, a piece with no loop edge. Its vertex is
    # selected, as the loop's edges are.
    band = fixtures.square_in_grid()
    obj = _edit_object(_band_mesh(band), chain=band.chain + [band.chain[0]])
    op = _OperatorStandIn(width=1.2, chain_sides="+", use_destructive=True)
    assert op.execute(bpy.context) == {'FINISHED'} and not op.reports, op.reports
    picked = _read(obj, lambda bm: [_key(v.co) for v in bm.verts if v.select])
    assert picked == [(3.0, 3.0, 0.0)] and not _selected_edges(obj), picked


def test_destructive_turns_an_unexpected_error_into_a_skip():
    # In D an error no refusal names skips the chain with a warning that names its type. Raised in the trial build it
    # never reaches the mesh; raised once the build itself began editing, the edits made get their update and the
    # operator finishes. UV Stripe in D skips a strip the same way.
    def broken(*_args):
        raise TypeError("broken split")

    band = fixtures.u_wall()
    obj = _edit_object(_band_mesh(band), chain=band.chain)
    before = _counts(obj)
    split = bridge._split_face
    bridge._split_face = broken
    try:
        op = _OperatorStandIn(width=0.47, chain_sides="+", use_destructive=True)
        assert op.execute(bpy.context) == {'CANCELLED'}
    finally:
        bridge._split_face = split
    assert op.reports[0] == "Smart Edge Slide: chain skipped (the trial build failed (TypeError: broken split))", \
        op.reports
    assert _counts(obj) == before

    obj = _edit_object(_band_mesh(fixtures.u_wall()), chain=band.chain)
    trial, calls = bridge._trial_failure, []

    def fail_second(va, vb, coords, *probe):
        calls.append(None)
        if len(calls) == 2:
            raise TypeError("broken split")
        return split(va, vb, coords, *probe)

    bridge._split_face, bridge._trial_failure = fail_second, (lambda *_args: None)
    try:
        op = _OperatorStandIn(width=0.47, chain_sides="+", use_destructive=True)
        assert op.execute(bpy.context) == {'FINISHED'}
    finally:
        bridge._split_face, bridge._trial_failure = split, trial
    assert op.reports == ["Smart Edge Slide: chain skipped (TypeError: broken split)"], op.reports
    assert _counts(obj) != before

    _edit_object(_band_mesh(fixtures.u_wall()), chain=band.chain)
    stripe_for = bridge.stripe_for

    def broken_strip(*_args):
        raise KeyError("broken strip")

    bridge.stripe_for = broken_strip
    try:
        op = _OperatorStandIn(width=0.47, chain_sides="+", use_destructive=True, use_uv_stripe=True)
        assert op.execute(bpy.context) == {'FINISHED'}
    finally:
        bridge.stripe_for = stripe_for
    assert op.reports == ["Smart Edge Slide: UV Stripe skipped (KeyError: 'broken strip')"] * 3, op.reports


class _PanelLayout:
    """Stands in for the redo panel's layout: records each property drawn with whether its row is active."""

    def __init__(self, drawn):
        self.drawn, self.active = drawn, True
        self.use_property_split = self.use_property_decorate = False

    def prop(self, _owner, name):
        self.drawn[name] = self.active

    def row(self):
        return _PanelLayout(self.drawn)

    def label(self, text):
        pass

    def panel(self, _idname, default_closed=False):
        return _PanelLayout(self.drawn), _PanelLayout(self.drawn)


def test_redo_panel_greys_what_the_mode_does_not_use():
    # Allow Collapse is greyed while D is on (D implies it, as the HUD shows); Tolerance and Shoot Angle while D is off.
    for destructive in (False, True):
        drawn = {}
        op = _OperatorStandIn(use_destructive=destructive)
        op.layout = _PanelLayout(drawn)
        op.draw(bpy.context)
        assert drawn["use_collapse"] is not destructive, drawn
        assert drawn["tolerance"] is destructive and drawn["shoot_angle"] is destructive, drawn
        assert all(drawn[name] for name in ("width", "use_exact", "use_destructive", "use_auto_adjust", "rail_bend")), drawn
        names = list(drawn)
        assert names.index("use_auto_adjust") == names.index("use_destructive") + 1, names   # next to Destructive


# --- why a slide stops ------------------------------------------------------------------

def _wheel(up=True, alt=False, shift=False, ctrl=False):
    """A wheel click with modifiers."""
    return SimpleNamespace(type="WHEELUPMOUSE" if up else "WHEELDOWNMOUSE", value="PRESS", shift=shift, ctrl=ctrl,
                           alt=alt, oskey=False, mouse_region_x=0, mouse_region_y=0, mouse_x=0, mouse_y=0)


def _degrees_of(op, name):
    return round(math.degrees(getattr(op, name)), 4)


def _shallow_end_wall():
    """Chain 0-1-2-3 along y = 0 (side +1 at +y) whose start fan passes an edge leaning 40 degrees before its end edge.

    At vertex 0 the triangle 0, 1, A ends on edge 0-A at 40 degrees, under the default End Edge Angle (60), so the fan
    crosses it into the triangle 0, A, B, whose edge 0-B (70 degrees, half a unit long) is the end edge. Its wall turns
    39 degrees at B onto the border B-A, past the Rail Bend, so it ends at height 0.47 and the slide stops there. With
    the End Edge Angle at 40 the end edge is 0-A, whose wall rises to A at height 1.286, as high as the rest goes."""
    lean, high = math.radians(40.0), 2.0 * math.sin(math.radians(40.0))
    a = (high / math.tan(lean), high, 0.0)
    b = (0.5 * math.cos(math.radians(70.0)), 0.5 * math.sin(math.radians(70.0)), 0.0)
    points = [(0, 0, 0), (1, 0, 0), (2, 0, 0), (3, 0, 0), a, b, (2, high, 0), (3, high, 0)]
    return _mesh(points, [(0, 1, 4), (0, 4, 5), (1, 2, 6, 4), (2, 3, 7, 6)])


def test_stop_hint_names_end_edge_angle_and_the_measured_lean():
    _edit_object(_shallow_end_wall(), chain=[0, 1, 2, 3])
    op, ctx = _invoke(x=0, width=1.0)
    op.chain_sides = "+"
    op._rebuild_preview()
    op._update_hints()                                                 # the HUD's draw works them out
    assert op._clamped and len(op._hints) == 1
    text, error = op._hints[0]
    assert error and "End Edge Angle" in text and "40°" in text and "vertex 0" in text, text
    assert "Wheel" not in text, text                                   # no key turns it in the modal
    reason = text.rsplit(": ", 1)[0]                                   # with Auto Adjust off the HUD offers Q
    assert op._hint_notes() == [(f"{reason}: press Q to let it adjust", True)], op._hint_notes()
    op.use_auto_adjust = True
    assert op._hint_notes() == op._hints
    op.use_auto_adjust = False
    hint_key = op._hint_key
    op.width = 1.5                                                     # still clamped: the hint is not worked out again
    op._rebuild_preview()
    op._update_hints()
    assert op._hint_key is hint_key
    op.width = 0.25                                                    # not clamped: no hint
    op._rebuild_preview()
    op._update_hints()
    assert op._hints == []
    op._finish(ctx)


def test_stop_hint_at_an_open_edge_is_plain():
    _edit_object(_strip(), chain=[0, 1, 2, 3])
    for destructive in (False, True):
        op, ctx = _invoke(x=0, width=5.0, use_destructive=destructive)
        op.chain_sides = "+"
        op._rebuild_preview()
        op._update_hints()
        assert op._clamped and op._hints == [("Stopped at an open edge", False)], op._hints
        op._finish(ctx)



# --- Auto Adjust (Q) -----------------------------------------------------------------

def _drag_shallow_end_wall(width, **props):
    """The modal over ``_shallow_end_wall`` on side +1, dragged from 0 to ``width`` (400 px per unit)."""
    _edit_object(_shallow_end_wall(), chain=[0, 1, 2, 3])
    op, ctx = _invoke(x=0, width=0.0, **props)
    op.chain_sides = "+"
    assert abs(op._pixel_to_width - 0.0025) < 1e-12, op._pixel_to_width
    op._modal(ctx, _move(int(round(width / 0.0025))))
    return op, ctx


def test_modal_q_toggles_auto_adjust_and_cancel_restores():
    _edit_object(_strip(), chain=[0, 1, 2, 3])
    op, ctx = _invoke(x=0, width=0.25)
    params = {p.name: p for section in op._hud.param_sections for p in section.params}
    assert op.use_auto_adjust is False and params["Auto Adjust (Q)"].value_text() == "✗"
    assert "auto adjust = off (Q)" in op._status_text()
    _keys(op, ctx, "Q")
    assert op.use_auto_adjust is True and params["Auto Adjust (Q)"].value_text() == "✓"
    assert "auto adjust = on (Q)" in op._status_text()
    assert op._modal(ctx, _event("ESC")) == {'CANCELLED'}
    assert op.use_auto_adjust is False
    op, ctx = _invoke(x=0, width=0.25, use_auto_adjust=True)
    _keys(op, ctx, "Q")
    assert op._modal(ctx, _event("ESC")) == {'CANCELLED'} and op.use_auto_adjust is True


def test_auto_adjust_lowers_end_edge_angle_and_the_slide_goes_further():
    # End Edge Angle stops the slide at 0.47 (the hint names 40 degrees). With Auto Adjust the drag past it lowers the
    # angle by itself and the loop reaches the width; without it nothing changes and the loop stays clamped.
    op, ctx = _drag_shallow_end_wall(1.0)
    op._update_hints()                                                 # the HUD's draw works them out
    assert op._clamped and _degrees_of(op, "end_edge_angle") == 60.0
    assert op._hint_changes and op._hint_changes[0][2] == {"end_edge_angle": math.radians(40.0)}, op._hint_changes
    op._finish(ctx)

    op, ctx = _drag_shallow_end_wall(1.0, use_auto_adjust=True)
    assert _degrees_of(op, "end_edge_angle") == 40.0 and not op._clamped
    assert abs(op.width - 1.0) < 1e-9 and op._auto_counts == {(0, 1): 1}
    assert op._preview_segs and max(abs(p.y - 1.0) for p in op._preview_segs) < 1e-4, op._preview_segs
    assert "auto adjust: End Edge Angle 40°" in op._status_text()
    # Past the new limit (1.286, as high as the rest goes) nothing more helps: it stays clamped, and the next moves
    # work nothing out again.
    op._modal(ctx, _move(800))
    assert op._clamped and _degrees_of(op, "end_edge_angle") == 40.0 and op._auto_counts == {(0, 1): 1}
    hint_key = op._hint_key
    op._modal(ctx, _move(810))
    assert op._hint_key is hint_key
    op._finish(ctx)


def test_auto_adjust_stops_after_eight_changes_and_at_range_ends():
    _edit_object(_strip(), chain=[0, 1, 2, 3])

    def drag(change, **props):
        """The strip dragged to width 5 (clamped at its open edge), every note naming ``change(op)``."""
        op, ctx = _invoke(x=0, width=0.0, use_auto_adjust=True, **props)
        op.chain_sides = "+"
        op._stop_hint = lambda *_stop: ("Stopped", True, change(op))
        op._modal(ctx, _move(2000))
        assert op._clamped
        return op, ctx

    one = math.radians(1.0)
    op, ctx = drag(lambda op: {"rail_bend": op.rail_bend + one})
    assert _degrees_of(op, "rail_bend") == 38.0 and op._auto_counts == {(0, 1): 8}
    op._modal(ctx, _move(2100))                                        # still clamped: no ninth change
    op._modal(ctx, _move(0))
    op._modal(ctx, _move(2000))                                        # clamped again in the same drag
    assert _degrees_of(op, "rail_bend") == 38.0
    op._finish(ctx)

    op, ctx = drag(lambda op: {"rail_bend": op.rail_bend + one}, rail_bend=math.radians(87.0))
    assert _degrees_of(op, "rail_bend") == 89.0 and op._auto_counts == {(0, 1): 2}   # the prop's range ends at 89
    op._finish(ctx)
    op, ctx = drag(lambda op: {"end_edge_angle": op.end_edge_angle - one}, end_edge_angle=math.radians(3.0))
    assert _degrees_of(op, "end_edge_angle") == 1.0 and op._auto_counts == {(0, 1): 2}
    op._finish(ctx)

    # Tolerance goes up to 1% of the band's size (the strip's diagonal) and no further.
    size = math.hypot(3.0, 1.0)
    op, ctx = drag(lambda op: {"tolerance": max(op.tolerance, 0.004 * size) * 2.0}, use_destructive=True)
    assert abs(op.tolerance - 0.008 * size) < 1e-9 and op._auto_counts == {(0, 1): 1}, op.tolerance
    assert op._sides[0][1][1]._weld == op.tolerance                    # the Sliders were made again with it
    op._finish(ctx)


def test_execute_after_an_auto_adjusted_drag_is_the_redo_of_its_props():
    # Execute takes the props as Auto Adjust left them and adjusts nothing itself: a redo from them cuts the same.
    op, ctx = _drag_shallow_end_wall(1.0, use_auto_adjust=True)
    assert _degrees_of(op, "end_edge_angle") == 40.0
    assert op._modal(ctx, _event("RET")) == {'FINISHED'}, op.reports
    obj = bpy.context.active_object
    confirmed = (_coords(obj), _all_edges(obj), _selected_edges(obj))
    props = {name: getattr(op, name) for name in (
        "width", "use_exact", "use_collapse", "use_destructive", "use_auto_adjust", "chain_sides", "rail_bend",
        "end_edge_angle", "step_agreement", "step_difference", "shoot_angle", "tolerance")}

    obj = _edit_object(_shallow_end_wall(), chain=[0, 1, 2, 3])
    redo = _OperatorStandIn(**props)
    assert redo.execute(bpy.context) == {'FINISHED'}, redo.reports
    assert (_coords(obj), _all_edges(obj), _selected_edges(obj)) == confirmed
    assert redo.end_edge_angle == props["end_edge_angle"]              # execute changed nothing
    assert any(abs(y - 1.0) < 1e-4 for _x, y, _z in confirmed[0])     # the loop at the width, past the old limit

    obj = _edit_object(_shallow_end_wall(), chain=[0, 1, 2, 3])        # the default angle cuts lower
    plain = _OperatorStandIn(**{**props, "end_edge_angle": math.radians(60.0)})
    assert plain.execute(bpy.context) == {'FINISHED'}, plain.reports
    assert _coords(obj) != confirmed[0]




def test_modal_wheel_only_navigates():
    # The angles and Tolerance have no key in the modal: any wheel, with any modifier, passes through to the view and
    # changes nothing; A and T do nothing either.
    _edit_object(_strip(), chain=[0, 1, 2, 3])
    op, ctx = _invoke(x=0, width=0.25)
    names = ("rail_bend", "end_edge_angle", "step_agreement", "step_difference", "shoot_angle", "tolerance")
    before = {name: getattr(op, name) for name in names}
    for up in (True, False):
        for mods in ({}, {"alt": True}, {"shift": True}, {"ctrl": True}, {"alt": True, "ctrl": True}):
            assert op._modal(ctx, _wheel(up, **mods)) == {'PASS_THROUGH'}, mods
    _keys(op, ctx, "A T")
    assert {name: getattr(op, name) for name in names} == before
    assert "Wheel" not in op._status_text() and "[A]" not in op._status_text()
    op._finish(ctx)


def test_modal_cancel_restores_what_auto_adjust_changed():
    op, ctx = _drag_shallow_end_wall(1.0, use_auto_adjust=True)
    assert _degrees_of(op, "end_edge_angle") == 40.0
    assert op._modal(ctx, _event("ESC")) == {'CANCELLED'}
    assert _degrees_of(op, "end_edge_angle") == 60.0

def test_auto_adjust_shows_its_change_in_the_hud():
    # A redraw is asked for at once and a plain HUD line names the change, for AUTO_NOTE_SECONDS. Past the new limit
    # no setting helps: the line says so. Auto Adjust off: no line.
    _edit_object(_shallow_end_wall(), chain=[0, 1, 2, 3])
    op, ctx = _invoke(x=0, width=0.0, use_auto_adjust=True)
    op.chain_sides = "+"
    redraws = []                                                       # the angle as each redraw is asked for
    ctx.area = SimpleNamespace(tag_redraw=lambda: redraws.append(_degrees_of(op, "end_edge_angle")))
    op._modal(ctx, _move(400))                                         # width 1.0, past the 0.47 the 60 degrees stop at
    assert redraws[-1] == 40.0, redraws                                # a redraw asked for after the change
    assert op._auto_notes() == [("Auto Adjust: lowered End Edge Angle to 40°", False)], op._auto_notes()
    op._modal(ctx, _move(800))                                         # clamped past 1.286: nothing more to change
    assert op._auto_notes() == [("Auto Adjust: lowered End Edge Angle to 40°", False)]   # still within its seconds
    op._auto_note = (op._auto_note[0], time.perf_counter() - 1.0)
    assert op._auto_notes() == [(sys.modules[operator.__module__].AUTO_NO_HELP, False)], op._auto_notes()
    _keys(op, ctx, "Q")
    assert op._auto_notes() == []
    op._finish(ctx)

TESTS = [
    test_collect_chains_orders_and_rejects_branching,
    test_collect_chains_closed_and_reversed_order,
    test_build_band_strip_side,
    test_end_edge_angle_admits_a_shallower_end_edge,
    test_end_edge_never_comes_from_the_other_side,
    test_angle_props_reach_execute,
    test_angles_at_the_defaults_are_exactly_the_core_defaults,
    test_step_agreement_stays_under_step_difference,
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
    test_modal_cursor_wrap_never_jumps_the_width,
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
    test_apply_destructive_u_wall_opens_on_the_wall,
    test_apply_destructive_square_apex_fans,
    test_apply_builds_the_apex_contract_cut,
    test_apply_destructive_merged_anchors_fan,
    test_apply_destructive_keeps_topology_valid,
    test_apply_destructive_builds_a_shot_end_on_its_landing,
    test_apply_destructive_in_the_last_micron_below_a_limit,
    test_preview_draws_no_line_across_a_break,
    test_uv_stripe_one_strip_per_piece,
    test_uv_stripe_closed_loop_opened_once_has_a_seam,
    test_apply_destructive_ring_inside_one_face_is_an_inset,
    test_apply_destructive_inset_never_builds_invalid_topology,
    test_apply_destructive_reports_a_loop_crossing_itself,
    test_apply_destructive_builds_whole_or_refuses_before_any_edit,
    test_stripe_for_a_failed_cut_with_breaks_raises,
    test_d_toggles_destructive_and_restores_collapse,
    test_d_off_gives_collapse_back_as_it_was,
    test_modal_d_hud_help_status_and_cancel,
    test_modal_d_pays_the_first_wave_of_every_side_when_switched_on,
    test_per_chain_limits_in_destructive,
    test_modal_move_budget_destructive,
    test_redo_from_props_matches_the_confirmed_destructive_cut,
    test_execute_destructive_u_wall_opens_the_loop,
    test_execute_skips_a_refused_chain_and_cuts_the_other,
    test_execute_destructive_uv_stripe_per_piece,
    test_modal_ctrl_snap_in_d_reaches_what_only_d_reaches,
    test_modal_preview_in_d_shows_the_apex,
    test_modal_preview_leaves_out_a_chain_confirm_refuses,
    test_preview_layers_draw_nothing_for_a_refused_destructive_cut,
    test_preview_layers_draw_nothing_for_a_reversed_ring,
    test_apply_destructive_builds_a_non_convex_rings_tree,
    test_apply_destructive_builds_a_ridge_tip,
    test_segment_gap_is_symmetric,
    test_uv_stripe_lays_out_final_states,
    test_apply_destructive_builds_a_room_past_its_closed_branch,
    test_apply_destructive_builds_both_rings_of_a_split_loop,
    test_uv_stripe_lays_out_each_ring_of_a_split_loop,
    test_uv_stripe_names_a_ring_with_no_chain_of_its_own,
    test_apply_destructive_builds_rings_sharing_a_face,
    test_apply_destructive_drops_only_a_lone_apexs_grazing_fan_edge,
    test_execute_destructive_in_place_stripes_use_each_pieces_own_uvs,
    test_tolerance_builds_the_near_event_refusals,
    test_tolerance_prop,
    test_tolerance_reaches_execute,
    test_tolerance_is_ignored_with_destructive_off,
    test_a_new_launch_starts_at_width_zero,
    test_destructive_is_off_next_to_a_face_with_more_than_48_sides,
    test_destructive_limit_is_the_largest_width_that_builds,
    test_execute_destructive_selects_a_lone_points_vertex,
    test_destructive_turns_an_unexpected_error_into_a_skip,
    test_redo_panel_greys_what_the_mode_does_not_use,
    test_relay_passes_the_rows_of_a_zigzag_ladder,
    test_relay_leaves_a_slide_that_goes_on_by_itself,
    test_execute_destructive_cuts_past_the_relays,
    test_modal_destructive_relays_preview_clamp_and_snap,
    test_stop_hint_names_end_edge_angle_and_the_measured_lean,
    test_stop_hint_at_an_open_edge_is_plain,
    test_modal_q_toggles_auto_adjust_and_cancel_restores,
    test_auto_adjust_lowers_end_edge_angle_and_the_slide_goes_further,
    test_auto_adjust_stops_after_eight_changes_and_at_range_ends,
    test_execute_after_an_auto_adjusted_drag_is_the_redo_of_its_props,
    test_auto_adjust_shows_its_change_in_the_hud,
    test_modal_wheel_only_navigates,
    test_modal_cancel_restores_what_auto_adjust_changed,
    test_relay_match_is_taken_at_the_width_the_loop_meets_the_row,
    test_relay_chain_drops_a_shot_end_past_the_row,
    test_relay_knows_when_an_end_has_shot_past_its_end_edge,
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
