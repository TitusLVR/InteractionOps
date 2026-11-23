"""Headless tests of UV Stripe in Inset: the operator's execute() on real
meshes in Edit Mode, and the modal's U key, HUD and help. Run from the repo root via:

    blender --background --factory-startup --python-exit-code 1 --python tests/blender/test_inset_uv_stripe.py

No viewport is needed: every test puts its mesh in an object of its own and runs
the operator in Edit Mode.

Not collected by pytest (tests/conftest.py ignores tests/blender).
"""
import math
import os
import sys
import traceback

import bmesh
import bpy
from mathutils import Vector

ADDON = "InteractionOps"

operator = None


def enable_addon():
    global operator
    repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    repo_parent = os.path.dirname(repo_root)
    if repo_parent not in sys.path:
        sys.path.insert(0, repo_parent)
    bpy.ops.preferences.addon_enable(module=ADDON)
    assert ADDON in bpy.context.preferences.addons, "addon not enabled"
    import InteractionOps
    loaded = os.path.dirname(os.path.abspath(InteractionOps.__file__))
    assert os.path.samefile(loaded, repo_root), f"addon loaded from {loaded}"
    from InteractionOps.operators.mesh_inset import IOPS_OT_inset
    operator = IOPS_OT_inset


# --- mesh builders ---------------------------------------------------------------

def _object(points, faces, uv_size=None):
    """A mesh object made of ``faces`` over ``points``, active and in Object Mode.

    ``uv_size`` adds a UV layer with each loop's UV at its vertex's (x, y) / uv_size + 0.5.
    """
    if bpy.context.object is not None and bpy.context.object.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    for other in bpy.context.view_layer.objects:
        other.select_set(False)
    bm = bmesh.new()
    verts = [bm.verts.new(p) for p in points]
    for face in faces:
        bm.faces.new([verts[i] for i in face])
    if uv_size is not None:
        layer = bm.loops.layers.uv.new("UVMap")
        for f in bm.faces:
            for lp in f.loops:
                lp[layer].uv = lp.vert.co.xy / uv_size + Vector((0.5, 0.5))
    me = bpy.data.meshes.new("inset")
    bm.to_mesh(me)
    bm.free()
    obj = bpy.data.objects.new("inset", me)
    bpy.context.scene.collection.objects.link(obj)
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    return obj


def _plane_rect(width, height, uv=False):
    """One quad of ``width`` x ``height`` centred on the origin in the z = 0 plane."""
    w, h = width / 2.0, height / 2.0
    points = [(-w, -h, 0.0), (w, -h, 0.0), (w, h, 0.0), (-w, h, 0.0)]
    return _object(points, [(0, 1, 2, 3)], uv_size=width if uv else None)


def _plane(size, uv=False):
    """One ``size`` x ``size`` quad centred on the origin; ``uv=True`` maps it onto UV 0-1."""
    return _plane_rect(size, size, uv=uv)


def _grid(nx, ny, skip=()):
    """Flat quad grid in XY, 1 m cells from the origin, without the cells in ``skip`` ((x, y) pairs)."""
    points = [(x, y, 0.0) for y in range(ny + 1) for x in range(nx + 1)]
    row = nx + 1
    faces = [(y * row + x, y * row + x + 1, (y + 1) * row + x + 1, (y + 1) * row + x)
             for y in range(ny) for x in range(nx) if (x, y) not in skip]
    return _object(points, faces)


# --- Edit Mode and reading the result ----------------------------------------------

_BEFORE = {}  # object name -> (face keys, selection border vertex keys) when its faces were selected


def _key(co):
    return tuple(round(float(c), 6) for c in co)


def _face_key(f):
    return frozenset(_key(v.co) for v in f.verts)


def _select_all_faces(obj):
    """Enter Edit Mode in face select mode with every face selected, and note the faces as they are."""
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.context.tool_settings.mesh_select_mode = (False, False, True)
    bm = bmesh.from_edit_mesh(obj.data)
    for f in bm.faces:
        f.select_set(True)
    bm.select_flush_mode()
    bmesh.update_edit_mesh(obj.data)
    _note_selection(obj)


def _note_selection(obj):
    """Note the faces and the selection border as they are now, for ``_wall_faces``."""
    bm = bmesh.from_edit_mesh(obj.data)
    faces = {_face_key(f) for f in bm.faces}
    rim = {_key(v.co) for e in bm.edges if sum(f.select for f in e.link_faces) == 1 for v in e.verts}
    _BEFORE[obj.name] = (faces, rim)


def _wall_faces(bm, name):
    """The wall (inset) or ring (outset) faces: new faces with a corner on the old selection border.

    The new inner faces of an inset never touch that border, and an outset keeps
    the old faces, which are not new.
    """
    faces, rim = _BEFORE[name]
    return [f for f in bm.faces if _face_key(f) not in faces and any(_key(v.co) in rim for v in f.verts)]


def _wall_corners(obj, inside=None):
    """(rounded co, rounded UV) of every corner of the wall faces.

    ``inside=(low, high)`` keeps only the faces with every vertex in that xy box.
    """
    bm = bmesh.from_edit_mesh(obj.data)
    layer = bm.loops.layers.uv.active
    out = []
    for f in _wall_faces(bm, obj.name):
        if inside is not None and not all(inside[0] <= c <= inside[1] for v in f.verts for c in v.co.xy):
            continue
        out += [(_key(lp.vert.co), _key(lp[layer].uv)) for lp in f.loops]
    assert out, "no wall faces"
    return out


def _wall_uv_ranges(obj, inside=None):
    """((u_min, u_max), (v_min, v_max)) over the wall faces' corners, rounded to 6 decimals."""
    uvs = [uv for _co, uv in _wall_corners(obj, inside)]
    us, vs = [u for u, _v in uvs], [v for _u, v in uvs]
    return (min(us), max(us)), (min(vs), max(vs))


def _seam_vertex_has_u0_and_u1(obj):
    """True when one vertex of the walls carries u = 0 on one wall face and u = 1 on another."""
    us = {}
    for co, uv in _wall_corners(obj):
        us.setdefault(co, set()).add(uv[0])
    return any({0.0, 1.0} <= found for found in us.values())


def _uv_bbox(obj):
    """((u_min, u_max), (v_min, v_max)) over every corner of the mesh, rounded."""
    bm = bmesh.from_edit_mesh(obj.data)
    layer = bm.loops.layers.uv.active
    uvs = [_key(lp[layer].uv) for f in bm.faces for lp in f.loops]
    us, vs = [u for u, _v in uvs], [v for _u, v in uvs]
    return (min(us), max(us)), (min(vs), max(vs))


# --- UV Stripe's settings, which Inset and Edge Slide follow -----------------

# The settings these tests were written for (the UV Stripe options' former own defaults here); main() sets them
# before every test, and a test changes what it needs with _stripe_settings.
STRIPE_BASELINE = {"mode": "FIT", "straight_sides": "BOTH", "ends": "SLANTED", "balance": "EVEN_TEXEL",
                   "stretch_limit": 1.25, "orientation": "HORIZONTAL", "mark_seams": True, "offset_axis": "NONE",
                   "split_at_seams": False, "merge_doubles": False, "active_fit": "BOTH"}


def _stripe_settings(**values):
    """Set UV Stripe's last-used properties, the settings Inset and Edge Slide read."""
    props = bpy.context.window_manager.operator_properties_last("iops.mesh_uv_stripe")
    for name, value in values.items():
        setattr(props, name, value)


def _take_stripe_settings(props):
    """Move ``uv_stripe_<name>`` keys (the operators' former properties) out of ``props`` into UV Stripe's settings."""
    moved = {k[len("uv_stripe_"):]: props.pop(k) for k in list(props) if k.startswith("uv_stripe_")}
    _stripe_settings(**moved)
    return props


def _inset(**props):
    return bpy.ops.iops.mesh_inset('EXEC_DEFAULT', **_take_stripe_settings(props))


# --- modal stand-ins ---------------------------------------------------------------

class _OperatorStandIn:
    """Stands in for an operator instance: the operator's methods run on these props."""

    def __init__(self, **props):
        self.thickness, self.depth, self.mode = 0.05, 0.0, "REGION"
        self.use_collapse, self.use_boundary = True, True
        self.use_uv_stripe = False
        self.select_inner, self.select_walls = True, False
        props = _take_stripe_settings(props)
        self.__dict__.update(props)
        self.reports = []

    def report(self, _kinds, message):
        self.reports.append(message)

    def __getattr__(self, name):  # the operator's own methods, bound to this stand-in
        return getattr(operator, name).__get__(self)


class _KeyPress:
    """Stands in for a modal key press event without modifiers."""

    def __init__(self, key):
        self.type, self.value = key, "PRESS"
        self.shift = self.ctrl = self.alt = self.oskey = False
        self.mouse_x = self.mouse_y = self.mouse_region_x = self.mouse_region_y = 0


# --- tests -----------------------------------------------------------------------

def test_inset_square_fit():
    obj = _plane(2.0)
    _select_all_faces(obj)
    _inset(thickness=0.2, use_uv_stripe=True)
    us, vs = _wall_uv_ranges(obj)
    # Auto tears the ring at its four corners and lays each wall out at its true shape: one Fit scale, 1 / 2
    # (the longest wall), in place of the whole ring's 1 / 7.2 strip.
    assert us == (0.0, 1.0) and vs == (0.0, 0.43)
    _assert_true_walls(obj, 0.5)


def test_outset_square_fit():
    obj = _plane(2.0)
    _select_all_faces(obj)
    _inset(thickness=-0.2, use_uv_stripe=True)
    assert _wall_uv_ranges(obj)[1] == (0.0, 0.363333)
    _assert_true_walls(obj, 1 / 2.4)


def test_select_options_pick_the_inner_faces_and_the_walls():
    # Inset: the walls are the new faces on the old border. Outset: the ring is, and the old faces are the inner ones.
    for thickness in (0.2, -0.2):
        for inner, walls in ((True, False), (False, True), (True, True), (False, False)):
            obj = _plane(2.0)
            _select_all_faces(obj)
            _inset(thickness=thickness, select_inner=inner, select_walls=walls)
            bm = bmesh.from_edit_mesh(obj.data)
            wall = set(_wall_faces(bm, obj.name))
            assert len(wall) == 4 and len(bm.faces) == 5, (len(wall), len(bm.faces))
            got = {f for f in bm.faces if f.select}
            want = (wall if walls else set()) | ((set(bm.faces) - wall) if inner else set())
            assert got == want, (thickness, inner, walls, len(got), len(want))
    obj = _plane(2.0)                                   # the defaults: the inner face alone
    _select_all_faces(obj)
    _inset(thickness=0.2)
    assert sum(f.select for f in bmesh.from_edit_mesh(obj.data).faces) == 1


def test_selected_faces_leave_the_mesh_in_face_select_mode():
    # From edge mode the inner face's edges are also the walls' edges: face mode keeps the selection to the faces.
    for inner, walls, want in ((True, False, (False, False, True)), (False, False, (False, True, False))):
        obj = _plane(2.0)
        _select_all_faces(obj)
        bpy.context.tool_settings.mesh_select_mode = (False, True, False)
        _inset(thickness=0.2, select_inner=inner, select_walls=walls)
        assert tuple(bpy.context.tool_settings.mesh_select_mode) == want, (inner, walls)
        bm = bmesh.from_edit_mesh(obj.data)
        assert set(bm.select_mode) == ({'FACE'} if want[2] else {'EDGE'}), (inner, walls)
        assert sum(f.select for f in bm.faces) == (1 if inner else 0), (inner, walls)


def test_collapsed_rectangle_still_a_rectangle():
    obj = _plane_rect(1.0, 4.0)
    _select_all_faces(obj)
    _inset(thickness=99.0, use_collapse=True, use_uv_stripe=True)
    assert _wall_uv_ranges(obj) == ((0.0, 1.0), (0.0, 0.0625))


def test_uv_stripe_off_keeps_old_behaviour():
    obj = _plane(2.0, uv=True)
    _select_all_faces(obj)
    before = _uv_bbox(obj)
    _inset(thickness=0.2)
    assert _uv_bbox(obj) == before


def test_depth_strip_height_is_the_slanted_wall():   # height hypot(0.2, 0.2) over length 7.2
    obj = _plane(2.0)
    _select_all_faces(obj)
    _inset(thickness=0.2, depth=0.2, use_uv_stripe=True)
    assert _wall_uv_ranges(obj) == ((0.0, 1.0), (0.0, 0.595685))
    _assert_true_walls(obj, 0.5)       # the slanted walls, each laid out at its true size


def test_hole_gives_two_stacked_strips():
    # 3 x 3 cells without the middle one. Outer strip: length 11.6, height 0.1, the
    # region's first loop, so at the bottom. Hole strip: length 4.4, stacked 0.01 above.
    obj = _grid(3, 3, skip={(1, 1)})
    _select_all_faces(obj)
    _inset(thickness=0.1, use_uv_stripe=True)
    assert _wall_uv_ranges(obj, inside=(0.85, 2.15)) == ((0.0, 1.0), (0.173333, 0.536667))
    outer = [uv for co, uv in _wall_corners(obj) if not all(0.85 <= c <= 2.15 for c in co[:2])]
    us, vs = [u for u, _v in outer], [v for _u, v in outer]
    assert (min(us), max(us)) == (0.0, 1.0) and (min(vs), max(vs)) == (0.0, 0.163333)
    _assert_true_walls(obj, 1 / 3, inside=(0.85, 2.15), outside=True)      # the outer loop: Fit scale 1 / 3
    _assert_true_walls(obj, 1 / 1.2, inside=(0.85, 2.15))   # the hole loop is a group of its own


def test_frozen_loop_without_walls_leaves_the_others():
    # Boundary off: the outer loop is the grid's open border, frozen, so it builds no
    # walls. The hole round the unselected middle cell still gets its strip (length 4.4).
    obj = _grid(3, 3)
    _select_all_faces(obj)
    bm = bmesh.from_edit_mesh(obj.data)
    middle = {(1.0, 1.0, 0.0), (2.0, 1.0, 0.0), (2.0, 2.0, 0.0), (1.0, 2.0, 0.0)}
    next(f for f in bm.faces if _face_key(f) == middle).select_set(False)
    bmesh.update_edit_mesh(obj.data)
    _note_selection(obj)
    op = _OperatorStandIn(thickness=0.1, use_boundary=False, use_uv_stripe=True)
    assert op._run(bpy.context) == {'FINISHED'}
    assert op.reports == [], op.reports
    assert _wall_uv_ranges(obj, inside=(0.85, 2.15)) == ((0.0, 1.0), (0.0, 0.363333))
    _assert_true_walls(obj, 1 / 1.2, inside=(0.85, 2.15))


def test_individual_mode_stacks_one_strip_per_face():   # each face: length 3.6, height 0.1
    obj = _grid(2, 1)
    _select_all_faces(obj)
    _inset(thickness=0.1, mode="INDIVIDUAL", use_uv_stripe=True)
    vs = sorted({uv[1] for _co, uv in _wall_corners(obj)})
    assert vs == [0.0, 0.1, 0.11, 0.21, 0.22, 0.32, 0.33, 0.43, 0.44, 0.54, 0.55, 0.65, 0.66, 0.76, 0.77, 0.87]
    assert _wall_uv_ranges(obj) == ((0.0, 1.0), (0.0, 0.87))
    _assert_true_walls(obj, 1.0)


def test_in_place_keeps_the_old_uvs_and_density():
    # Old UVs 0-1 over the 2 x 2 plane: centre (0.5, 0.5), density 0.5 from the inner face.
    # The 7.2 x 0.2 strip is 3.6 x 0.1 in UV.
    obj = _plane(2.0, uv=True)
    _select_all_faces(obj)
    _inset(thickness=0.2, use_uv_stripe=True, uv_stripe_mode="IN_PLACE")
    assert _wall_uv_ranges(obj) == ((-0.45, 1.45), (0.0, 1.0))
    _assert_true_walls(obj, 0.5)        # the old density, each wall at its true size


def _wall_face_corners(obj):
    """Per wall face: [(rounded co, rounded UV)] of its corners."""
    bm = bmesh.from_edit_mesh(obj.data)
    layer = bm.loops.layers.uv.active
    return [[(_key(lp.vert.co), _key(lp[layer].uv)) for lp in f.loops] for f in _wall_faces(bm, obj.name)]


def _on_rect_border(co, w, h):
    return abs(abs(co[0]) - w / 2.0) < 1e-6 or abs(abs(co[1]) - h / 2.0) < 1e-6


def _corner_us(obj, w, h):
    """(set of u at the original border's vertices, set of u at the new contour's), over the wall faces."""
    near, far = set(), set()
    for co, uv in _wall_corners(obj):
        (near if _on_rect_border(co, w, h) else far).add(uv[0])
    return near, far


def _walls_by_piece(bm, name):
    """The wall faces of ``bm`` (the edit mesh, kept alive by the caller) grouped into UV pieces: faces joined
    across an edge that is no seam, as UV Stripe's seams say where its pieces end."""
    walls = set(_wall_faces(bm, name))
    pieces, seen = [], set()
    for first in walls:
        if first in seen:
            continue
        piece, todo = set(), [first]
        while todo:
            f = todo.pop()
            if f in piece:
                continue
            piece.add(f)
            todo += [g for e in f.edges if not e.seam for g in e.link_faces if g in walls and g not in piece]
        seen |= piece
        pieces.append(piece)
    return pieces


def _assert_true_walls(obj, scale, inside=None, outside=False):
    """Every wall face laid out at its true shape: each UV edge is its 3D length times ``scale``, every corner
    keeps its angle (``_wall_metrics`` says which faces)."""
    metrics = _wall_metrics(obj, inside, outside)
    assert metrics, "no wall faces"
    for ratios, errors in metrics:
        assert all(abs(r - scale) < 1e-4 for r in ratios), (scale, ratios)
        assert max(errors) < 1e-4, errors


def _wall_metrics(obj, inside=None, outside=False):
    """Per wall face: (UV length / 3D length of each edge, |UV corner angle - 3D corner angle| in degrees).

    ``inside=(low, high)`` keeps only the faces with every vertex in that xy box, with ``outside`` only those
    that have not.
    """
    bm = bmesh.from_edit_mesh(obj.data)
    layer = bm.loops.layers.uv.active
    out = []
    for f in _wall_faces(bm, obj.name):
        if inside is not None and all(inside[0] <= c <= inside[1] for v in f.verts for c in v.co.xy) == outside:
            continue
        loops = list(f.loops)
        n = len(loops)
        ratios, errors = [], []
        for k, lp in enumerate(loops):
            nxt, prv = loops[(k + 1) % n], loops[k - 1]
            ratios.append((nxt[layer].uv - lp[layer].uv).length / (nxt.vert.co - lp.vert.co).length)
            a3 = (prv.vert.co - lp.vert.co).angle(nxt.vert.co - lp.vert.co)
            a2 = (prv[layer].uv - lp[layer].uv).angle(nxt[layer].uv - lp[layer].uv)
            errors.append(abs(math.degrees(a3 - a2)))
        out.append((ratios, errors))
    return out


def test_ends_stand_the_walls_cross_edges_vertical():
    # 4 x 1 rectangle inset by 0.2: each wall ends in a 45 degree mitre. Ends Slanted (the default) keeps the
    # slant, so the border and the contour put their corners at different u. Ends Both stands every cross edge
    # upright, which shears a mitred wall far beyond the stretch limit, so it takes the limit lifted.
    obj = _plane_rect(4.0, 1.0)
    _select_all_faces(obj)
    _stripe_settings(stretch_limit=100.0)
    _inset(thickness=0.2, use_uv_stripe=True)
    near, far = _corner_us(obj, 4.0, 1.0)
    assert near != far
    assert _wall_uv_ranges(obj) == ((0.0, 1.0), (0.0, 0.23))
    obj = _plane_rect(4.0, 1.0)
    _select_all_faces(obj)
    _stripe_settings(ends="BOTH", stretch_limit=100.0)
    _inset(thickness=0.2, use_uv_stripe=True)
    near, far = _corner_us(obj, 4.0, 1.0)
    assert near == far and len(near) == 3, (near, far)
    assert _wall_uv_ranges(obj) == ((0.0, 1.0), (0.0, 0.240526))
    for corners in _wall_face_corners(obj):         # a wall's cross edges: border corner and contour corner share u
        by_u = {}
        for co, uv in corners:
            by_u.setdefault(uv[0], []).append(_on_rect_border(co, 4.0, 1.0))
        assert all(sorted(kinds) == [False, True] for kinds in by_u.values()), corners
    obj = _plane_rect(4.0, 1.0)
    _select_all_faces(obj)
    _stripe_settings(ends="BOTH", stretch_limit=1.25)    # at the default limit the mitres relax it to the true shape
    _inset(thickness=0.2, use_uv_stripe=True)
    assert _wall_uv_ranges(obj) == ((0.0, 1.0), (0.0, 0.23))
    _assert_true_walls(obj, 0.25)


def test_defaults_tear_a_frame_into_four_equal_pieces():
    # Auto tears the 4 x 1 frame at every one of its four corners, so it gives four one-face pieces, each laid out
    # at its true size with one Fit scale (1 / 4, the longest wall): every UV edge is its 3D length over 4 and every
    # corner keeps its angle. The tears are symmetric: the two long walls' UV boxes are equal, the two short walls'
    # too, and the border lies on the bottom of each piece's UV box.
    obj = _plane_rect(4.0, 1.0)
    _select_all_faces(obj)
    _inset(thickness=0.2, use_uv_stripe=True)
    _assert_true_walls(obj, 0.25)
    bm = bmesh.from_edit_mesh(obj.data)
    pieces = _walls_by_piece(bm, obj.name)
    assert sorted(len(piece) for piece in pieces) == [1, 1, 1, 1]
    layer = bm.loops.layers.uv.active
    sizes = []
    for piece in pieces:
        corners = [(_key(lp.vert.co), _key(lp[layer].uv)) for f in piece for lp in f.loops]
        us, vs = [uv[0] for _co, uv in corners], [uv[1] for _co, uv in corners]
        sizes.append((round(max(us) - min(us), 6), round(max(vs) - min(vs), 6)))
        assert all(uv[1] == min(vs) for co, uv in corners if _on_rect_border(co, 4.0, 1.0)), corners
        assert all(uv[1] > min(vs) for co, uv in corners if not _on_rect_border(co, 4.0, 1.0)), corners
    assert sorted(sizes) == [(0.25, 0.05), (0.25, 0.05), (1.0, 0.05), (1.0, 0.05)], sizes
    walls = set(_wall_faces(bm, obj.name))
    assert all(e.seam for f in walls for e in f.edges)         # every wall edge: outline or a corner's tear


def test_mark_seams_match_the_walls():
    obj = _plane_rect(4.0, 1.0)
    _select_all_faces(obj)
    _inset(thickness=0.2, use_uv_stripe=True, uv_stripe_mark_seams=False)
    assert not any(e.seam for e in bmesh.from_edit_mesh(obj.data).edges)
    obj = _plane_rect(4.0, 1.0)
    _select_all_faces(obj)
    _inset(thickness=0.2, use_uv_stripe=True,
           uv_stripe_mark_seams=True)            # the settings persist: set back what the first run turned off
    bm = bmesh.from_edit_mesh(obj.data)
    walls = set(_wall_faces(bm, obj.name))
    outline = {e for f in walls for e in f.edges if sum(g in walls for g in e.link_faces) == 1}
    seams = {e for e in bm.edges if e.seam}
    assert outline <= seams and len(outline) == 8
    cuts = seams - outline                                  # the walls' UV cuts: one at each of the four corners
    assert len(cuts) == 4
    layer = bm.loops.layers.uv.active
    for cut in cuts:
        assert sum(_on_rect_border(_key(v.co), 4.0, 1.0) for v in cut.verts) == 1
    for e in {e for f in walls for e in f.edges} - outline:     # a side edge is a seam exactly where its walls' UVs part
        a, b = e.link_faces
        parts = any(_key(la[layer].uv) != _key(lb[layer].uv)
                    for la in a.loops for lb in b.loops if la.vert is lb.vert and la.vert in e.verts)
        assert parts == (e in cuts), (_key(e.verts[0].co), _key(e.verts[1].co), parts)


def test_a_split_that_cannot_be_made_is_reported_and_the_loop_stays_whole():
    from InteractionOps.utils import uv_stripe_select_core as select_core
    real = select_core.slice_strip

    def refuse(strip, cuts):
        raise ValueError("refused for the test")

    obj = _plane_rect(4.0, 1.0)
    _select_all_faces(obj)
    op = _OperatorStandIn(thickness=0.2, use_uv_stripe=True)
    select_core.slice_strip = refuse
    try:
        assert op._run(bpy.context) == {'FINISHED'}
    finally:
        select_core.slice_strip = real
    assert op.reports == ["Inset: UV Stripe not split (refused for the test)"], op.reports
    assert _wall_uv_ranges(obj) == ((0.0, 1.0), (0.0, 0.021739))
    assert _seam_vertex_has_u0_and_u1(obj)


def test_vertical_orientation():
    obj = _plane(2.0)
    _select_all_faces(obj)
    _inset(thickness=0.2, use_uv_stripe=True,
                                  uv_stripe_orientation="VERTICAL")
    assert _wall_uv_ranges(obj) == ((0.0, 0.43), (0.0, 1.0))
    _assert_true_walls(obj, 0.5)


def test_never_run_uv_stripe_gives_its_defaults():
    from InteractionOps.operators.uv_stripe_bridge import StripeSettings
    rna = bpy.ops.iops.mesh_uv_stripe.get_rna_type().properties
    expected = StripeSettings(**{name: rna[name].default for name in StripeSettings.__dataclass_fields__})
    assert FRESH_SETTINGS == expected, (FRESH_SETTINGS, expected)


def test_uv_stripe_settings_drive_the_inset():
    # Straight Sides, Ends and the Stretch Limit come from UV Stripe. With the limit lifted so that nothing
    # relaxes: the defaults keep both rails of each piece straight and its ends slanted; Ends Both stands the
    # ends upright; Straight Sides Longer keeps one rail; Straight Sides None unfolds every piece at its true
    # shape. Mark Seams off leaves the seams alone.
    for settings, v_max, true_shape in (({}, 0.23, True), ({"ends": "BOTH"}, 0.240526, False),
                                        ({"ends": "LONGER"}, 0.235077, False),
                                        ({"straight_sides": "LONGER"}, 0.23, True)):
        obj = _plane_rect(4.0, 1.0)
        _select_all_faces(obj)
        _stripe_settings(**STRIPE_BASELINE)               # the settings persist: back to the baseline first
        _stripe_settings(stretch_limit=100.0, **settings)
        _inset(thickness=0.2, use_uv_stripe=True)
        assert _wall_uv_ranges(obj) == ((0.0, 1.0), (0.0, v_max)), (settings, _wall_uv_ranges(obj))
        assert (max(max(errors) for _ratios, errors in _wall_metrics(obj)) < 1e-4) == true_shape, settings
    obj = _plane_rect(4.0, 1.0)
    _select_all_faces(obj)
    _stripe_settings(**STRIPE_BASELINE)
    _stripe_settings(straight_sides="NONE", stretch_limit=100.0)
    _inset(thickness=0.2, use_uv_stripe=True)
    assert _wall_uv_ranges(obj) == ((0.0, 1.0), (0.0, 0.23))
    _assert_true_walls(obj, 0.25)
    obj = _plane_rect(4.0, 1.0)
    _select_all_faces(obj)
    _stripe_settings(**STRIPE_BASELINE)
    _stripe_settings(straight_sides="BOTH", ends="BOTH")      # at the default limit the mitres relax it to true shape
    _inset(thickness=0.2, use_uv_stripe=True)
    assert _wall_uv_ranges(obj) == ((0.0, 1.0), (0.0, 0.23))
    _assert_true_walls(obj, 0.25)
    obj = _plane_rect(4.0, 1.0)
    _select_all_faces(obj)
    _stripe_settings(mark_seams=False)
    _inset(thickness=0.2, use_uv_stripe=True)
    assert not any(e.seam for e in bmesh.from_edit_mesh(obj.data).edges)


def test_merge_doubles_never_touches_the_inset():
    counts = []
    for merge in (False, True):
        obj = _plane_rect(4.0, 1.0)
        _select_all_faces(obj)
        _stripe_settings(merge_doubles=merge)
        _inset(thickness=0.2, use_uv_stripe=True)
        bm = bmesh.from_edit_mesh(obj.data)
        counts.append((len(bm.verts), len(bm.edges), len(bm.faces)))
    assert counts[0] == counts[1]


def test_active_mode_lays_the_walls_out_in_place_without_a_report():
    obj = _plane(2.0, uv=True)
    _select_all_faces(obj)
    op = _OperatorStandIn(thickness=0.2, use_uv_stripe=True, uv_stripe_mode="ACTIVE")
    assert op._run(bpy.context) == {'FINISHED'}
    assert op.reports == [], op.reports
    assert _wall_uv_ranges(obj) == ((-0.45, 1.45), (0.0, 1.0))          # the In Place result


def test_modal_hud_and_help_list_uv_stripe():
    op = _OperatorStandIn()
    op._build_overlays(None if bpy.app.background else bpy.context.region)
    params = [p for section in op._hud.param_sections for p in section.params]
    assert [p.name for p in params] == [
        "Thickness", "Depth", "Mode (I)", "Collapse (C)", "Boundary (B)", "UV Stripe (U)"]
    assert [(it.label, it.key) for it in op._help.sections[0].items] == [
        ("Adjust thickness", "Mouse / Type"), ("Depth", "Ctrl + Mouse"), ("Mode", "I"),
        ("Collapse", "C"), ("Boundary", "B"), ("UV Stripe", "U"),
        ("Confirm", "LMB / Enter"), ("Cancel", "Esc / RMB"), ("Help / Toggle HUD", "H")]


def test_modal_u_toggles_uv_stripe_and_cancel_restores():
    op = _OperatorStandIn(_input_str="", _preview_key=None)
    op._build_overlays(None if bpy.app.background else bpy.context.region)
    # The cancel snapshot invoke() takes; invoke() itself needs a viewport.
    op._cancel_thickness, op._cancel_depth, op._cancel_mode = op.thickness, op.depth, op.mode
    op._cancel_use_collapse, op._cancel_use_boundary = op.use_collapse, op.use_boundary
    op._cancel_use_uv_stripe = op.use_uv_stripe
    assert op._modal(bpy.context, _KeyPress("U")) == {'RUNNING_MODAL'} and op.use_uv_stripe is True
    assert "UV stripe = on (U)" in op._status_text()
    assert op._modal(bpy.context, _KeyPress("ESC")) == {'CANCELLED'} and op.use_uv_stripe is False


TESTS = [
    test_inset_square_fit,
    test_outset_square_fit,
    test_collapsed_rectangle_still_a_rectangle,
    test_select_options_pick_the_inner_faces_and_the_walls,
    test_selected_faces_leave_the_mesh_in_face_select_mode,
    test_uv_stripe_off_keeps_old_behaviour,
    test_depth_strip_height_is_the_slanted_wall,
    test_hole_gives_two_stacked_strips,
    test_frozen_loop_without_walls_leaves_the_others,
    test_individual_mode_stacks_one_strip_per_face,
    test_in_place_keeps_the_old_uvs_and_density,
    test_ends_stand_the_walls_cross_edges_vertical,
    test_defaults_tear_a_frame_into_four_equal_pieces,
    test_mark_seams_match_the_walls,
    test_a_split_that_cannot_be_made_is_reported_and_the_loop_stays_whole,
    test_vertical_orientation,
    test_never_run_uv_stripe_gives_its_defaults,
    test_uv_stripe_settings_drive_the_inset,
    test_merge_doubles_never_touches_the_inset,
    test_active_mode_lays_the_walls_out_in_place_without_a_report,
    test_modal_hud_and_help_list_uv_stripe,
    test_modal_u_toggles_uv_stripe_and_cancel_restores,
]


FRESH_SETTINGS = None


def main():
    global FRESH_SETTINGS
    enable_addon()
    from InteractionOps.operators.uv_stripe_bridge import StripeSettings
    FRESH_SETTINGS = StripeSettings.from_last(bpy.context)       # UV Stripe has not run in this session
    failed = 0
    for test in TESTS:
        try:
            _stripe_settings(**STRIPE_BASELINE)
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
