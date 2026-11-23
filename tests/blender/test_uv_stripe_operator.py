"""Headless tests of the UV Stripe operator (iops.mesh_uv_stripe) on real meshes in
Edit Mode. Run from the repo root via:

    blender --background --factory-startup --python-exit-code 1 --python tests/blender/test_uv_stripe_operator.py

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

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # tests/: shared fixtures
from uv_stripe_fixtures import (  # noqa: E402
    DOUBLE_FACES, DOUBLE_VERTS, NGON_FACES, NGON_VERTS, STEP_FACES, STEP_VERTS, exact_ngon_verts, flat_annulus,
    flat_annulus_with_triangle)

operator = None


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
    global operator
    from InteractionOps.operators.mesh_uv_stripe import IOPS_OT_Mesh_UV_Stripe
    operator = IOPS_OT_Mesh_UV_Stripe


# --- mesh builders ---------------------------------------------------------------

def _object(points, faces, uv_size=None, name="uv_stripe"):
    """A mesh object of ``faces`` over ``points``, active and in Object Mode.

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
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    obj = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(obj)
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    return obj


def _grid(nx, ny, keep=None, uv_size=None):
    """Flat quad grid in XY, 1 m cells from the origin; ``keep`` limits it to those (x, y) cells."""
    points = [(x, y, 0.0) for y in range(ny + 1) for x in range(nx + 1)]
    row = nx + 1
    faces = [(y * row + x, y * row + x + 1, (y + 1) * row + x + 1, (y + 1) * row + x)
             for y in range(ny) for x in range(nx) if keep is None or (x, y) in keep]
    return _object(points, faces, uv_size=uv_size)


def _edit(obj, select=lambda co: True):
    """Edit Mode in face select mode, with the faces whose centre passes ``select`` selected."""
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.context.tool_settings.mesh_select_mode = (False, False, True)
    bm = bmesh.from_edit_mesh(obj.data)
    for f in bm.faces:
        f.select_set(False)
    for f in bm.faces:
        if select(f.calc_center_median()):
            f.select_set(True)
    bm.select_flush_mode()
    bmesh.update_edit_mesh(obj.data)


def _corners(obj, only=None):
    """[(vertex position, uv)] for every corner of the selected faces (or of the faces passing ``only``)."""
    bm = bmesh.from_edit_mesh(obj.data)
    layer = bm.loops.layers.uv.active
    out = []
    for f in bm.faces:
        if (only(f.calc_center_median()) if only else f.select):
            out.extend((lp.vert.co.copy(), lp[layer].uv.copy()) for lp in f.loops)
    return out


def _face_areas(obj, only=None):
    bm = bmesh.from_edit_mesh(obj.data)
    layer = bm.loops.layers.uv.active
    out = []
    for f in bm.faces:
        if (only(f.calc_center_median()) if only else f.select):
            pts = [lp[layer].uv for lp in f.loops]
            out.append(0.5 * sum(a.x * b.y - b.x * a.y for a, b in zip(pts, pts[1:] + pts[:1])))
    return out


def _close(a, b, tol=1e-5):
    return abs(a - b) <= tol


# The defaults most tests here were written for; the operator's own defaults have their own tests.
OLD_DEFAULTS = {"active_fit": "BOTH", "straight_sides": "BOTH", "ends": "SLANTED", "split_at_seams": False,
                "merge_doubles": False, "offset_axis": "NONE"}


def _run(**props):
    return bpy.ops.iops.mesh_uv_stripe(**{**OLD_DEFAULTS, **props})


# --- tests -----------------------------------------------------------------------

def test_fit_straight_strip():
    obj = _grid(4, 1)
    _edit(obj)
    assert _run(mode="FIT") == {"FINISHED"}
    for co, uv in _corners(obj):
        assert _close(uv.x, co.x / 4.0) and _close(uv.y, co.y / 4.0), (co, uv)
    assert all(a > 0 for a in _face_areas(obj))


def test_in_place_keeps_centre_and_density():
    obj = _grid(6, 3, uv_size=10.0)      # UV = xy / 10 + 0.5: density 0.1 per metre
    middle = lambda c: 1.0 < c.y < 2.0 and 1.0 < c.x < 5.0     # noqa: E731
    _edit(obj, middle)
    before = _corners(obj)
    cu = (min(uv.x for _c, uv in before) + max(uv.x for _c, uv in before)) / 2.0
    cv = (min(uv.y for _c, uv in before) + max(uv.y for _c, uv in before)) / 2.0
    assert _run(mode="IN_PLACE") == {"FINISHED"}
    after = _corners(obj)
    us = [uv.x for _c, uv in after]
    vs = [uv.y for _c, uv in after]
    assert _close((min(us) + max(us)) / 2.0, cu) and _close((min(vs) + max(vs)) / 2.0, cv)
    assert _close(max(us) - min(us), 0.4) and _close(max(vs) - min(vs), 0.1)
    for co, uv in after:
        assert _close(uv.x, co.x / 10.0 + 0.5) and _close(uv.y, co.y / 10.0 + 0.5), (co, uv)


def test_in_place_on_a_scaled_object_keeps_density():
    obj = _grid(6, 3, uv_size=10.0)
    obj.scale = (2.0, 2.0, 2.0)          # the neighbours' density is per object unit
    _edit(obj, lambda c: 1.0 < c.y < 2.0 and 1.0 < c.x < 5.0)
    assert _run(mode="IN_PLACE") == {"FINISHED"}
    for co, uv in _corners(obj):
        assert _close(uv.x, co.x / 10.0 + 0.5) and _close(uv.y, co.y / 10.0 + 0.5), (co, uv)


def test_two_strips_stack_in_fit_with_one_density():
    obj = _grid(4, 4, keep={(x, 0) for x in range(4)} | {(x, 3) for x in range(2)})
    _edit(obj)
    assert _run(mode="FIT") == {"FINISHED"}
    low = _corners(obj, lambda c: c.y < 1.0)
    high = _corners(obj, lambda c: c.y > 3.0)
    assert all(_close(uv.x, co.x / 4.0) and 0.0 <= uv.y <= 0.25 + 1e-6 for co, uv in low)
    assert all(_close(uv.x, co.x / 4.0) for co, uv in high)        # the shorter strip keeps the density
    assert min(uv.y for _c, uv in high) > 0.25          # stacked above, not overlapping
    assert _close(max(uv.y for _c, uv in high) - min(uv.y for _c, uv in high), 0.25)


def _polyline(turns_deg, width=0.4):
    """A flat quad strip along unit segments turning by ``turns_deg``; vertex 2i left, 2i + 1 right of joint i."""
    heading, pts, dirs = 0.0, [(0.0, 0.0)], []
    for k in range(len(turns_deg) + 1):
        if k:
            heading += math.radians(turns_deg[k - 1])
        dirs.append((math.cos(heading), math.sin(heading)))
        pts.append((pts[-1][0] + dirs[-1][0], pts[-1][1] + dirs[-1][1]))
    points = []
    for i, (x, y) in enumerate(pts):
        da, db = dirs[max(i - 1, 0)], dirs[min(i, len(dirs) - 1)]
        t = math.hypot(da[0] + db[0], da[1] + db[1])
        nx, ny = -(da[1] + db[1]) / t, (da[0] + db[0]) / t
        scale = width / 2.0 / (nx * -da[1] + ny * da[0])
        points += [(x + nx * scale, y + ny * scale, 0.0), (x - nx * scale, y - ny * scale, 0.0)]
    faces = [(2 * i + 1, 2 * i + 3, 2 * i + 2, 2 * i) for i in range(len(pts) - 1)]
    return _object(points, faces)


def _vertex_us(obj, index):
    bm = bmesh.from_edit_mesh(obj.data)
    layer = bm.loops.layers.uv.active
    bm.verts.ensure_lookup_table()
    return {round(lp[layer].uv.x, 6) for lp in bm.verts[index].link_loops if lp.face.select}


def _seams(obj):
    bm = bmesh.from_edit_mesh(obj.data)
    return {tuple(sorted(v.index for v in e.verts)) for e in bm.edges if e.seam}


def _set_seams(obj, pairs):
    bm = bmesh.from_edit_mesh(obj.data)
    for e in bm.edges:
        if tuple(sorted(v.index for v in e.verts)) in pairs:
            e.seam = True
    bmesh.update_edit_mesh(obj.data)


def _middle(c):
    return 1.0 < c.y < 2.0 and 1.0 < c.x < 5.0


def test_mark_seams_match_the_pieces():
    # 6 x 3 grid, the middle row's four cells selected; an old seam outside them and one across them at x = 3.
    outside, inner = (0, 1), (10, 17)
    obj = _grid(6, 3)
    _edit(obj, _middle)
    _set_seams(obj, {outside, inner})
    assert _run(mode="FIT", mark_seams=False) == {"FINISHED"}
    assert _seams(obj) == {outside, inner}                  # Mark Seams off: no seam touched
    assert _run(mode="FIT") == {"FINISHED"}                 # laid across the inner seam: one strip, seam cleared
    bm = bmesh.from_edit_mesh(obj.data)
    outline = {tuple(sorted(v.index for v in e.verts)) for e in bm.edges
               if sum(f.select for f in e.link_faces) == 1}
    assert _seams(obj) == outline | {outside}
    assert _vertex_us(obj, 10) == {0.5}


def test_split_at_seams_tears_the_strip_and_keeps_its_seam():
    obj = _grid(4, 1)
    _edit(obj)
    _set_seams(obj, {(2, 7)})                            # the cross edge at x = 2
    assert _run(mode="FIT", split_at_seams=True) == {"FINISHED"}
    assert _vertex_us(obj, 2) == {0.0, 1.0} and _vertex_us(obj, 7) == {0.0, 1.0}
    assert (2, 7) in _seams(obj)
    assert _run(mode="FIT") == {"FINISHED"}                 # off by default: laid across it, the seam goes
    assert _vertex_us(obj, 2) == {0.5} and (2, 7) not in _seams(obj)


def _ring(n=8):
    points = [(math.cos(2 * math.pi * i / n), math.sin(2 * math.pi * i / n), z) for z in (0.0, 1.0) for i in range(n)]
    return _object(points, [(i, (i + 1) % n, n + (i + 1) % n, n + i) for i in range(n)])


def test_ring_with_one_seam_is_cut_there():
    obj = _ring()
    _edit(obj)
    _set_seams(obj, {(3, 11)})
    assert _run(mode="FIT", split_at_seams=True) == {"FINISHED"}
    assert _vertex_us(obj, 3) == {0.0, 1.0} and _vertex_us(obj, 11) == {0.0, 1.0}
    assert all(len(_vertex_us(obj, i)) == 1 for i in range(8) if i != 3)
    assert (3, 11) in _seams(obj)


def test_auto_tears_a_sharp_bend_and_keeps_a_gentle_one_whole():
    # Auto tears a bend only where that lowers the stretch: the 22 and 38 degree bends go, the straight joints stay.
    obj = _polyline([0, 22, 0, 38])
    _edit(obj)
    assert _run(mode="FIT") == {"FINISHED"}
    seams = _seams(obj)
    assert (4, 5) in seams and (8, 9) in seams
    assert (2, 3) not in seams and (6, 7) not in seams
    assert len(_vertex_us(obj, 4)) == 2 and len(_vertex_us(obj, 6)) == 1
    # an 8 degree bend costs the whole strip 3.6 % stretch only, less than a tear is worth: it is laid across
    obj = _polyline([8, 38])
    _edit(obj)
    assert _run(mode="FIT") == {"FINISHED"}
    assert (2, 3) not in _seams(obj) and (4, 5) in _seams(obj)
    assert len(_vertex_us(obj, 2)) == 1 and len(_vertex_us(obj, 4)) == 2
    assert _uv_islands(obj) == 2


def _uv_metrics(obj, only=None):
    """(UV length / 3D length of every face edge, |UV corner angle - 3D corner angle| in degrees) over the
    selected faces (or the faces passing ``only``), 3D in world space."""
    bm = bmesh.from_edit_mesh(obj.data)
    layer = bm.loops.layers.uv.active
    mw = obj.matrix_world
    ratios, errors = [], []
    for f in bm.faces:
        if not (only(f.calc_center_median()) if only else f.select):
            continue
        loops = list(f.loops)
        n = len(loops)
        for k, lp in enumerate(loops):
            nxt, prv = loops[(k + 1) % n], loops[k - 1]
            p, q, r = (mw @ x.vert.co for x in (prv, lp, nxt))
            ratios.append((nxt[layer].uv - lp[layer].uv).length / (r - q).length)
            a3 = (p - q).angle(r - q)
            a2 = (prv[layer].uv - lp[layer].uv).angle(nxt[layer].uv - lp[layer].uv)
            errors.append(abs(math.degrees(a3 - a2)))
    return ratios, errors


def _ngon_object(verts_by_id):
    ids = sorted(verts_by_id)
    at = {v: i for i, v in enumerate(ids)}
    obj = _object([verts_by_id[v] for v in ids], [tuple(at[v] for v in face) for face in NGON_FACES.values()])
    return obj


def test_ngon_strip_splits_into_stretch_free_pieces():
    # The user's three n-gons on exact geometry, with the defaults (No Stretch, Split at Bends 15 degrees): three
    # pieces, every UV edge its 3D length times one common scale, every corner angle kept.
    obj = _ngon_object(exact_ngon_verts())
    _edit(obj)
    stand = _OperatorStandIn(mode="FIT")
    assert stand.execute(bpy.context) == {"FINISHED"}, stand.reports
    assert stand.reports == ["UV Stripe: 3 strip(s)"], stand.reports
    ratios, errors = _uv_metrics(obj)
    scale = ratios[0]
    assert all(abs(r - scale) <= 1e-4 * scale for r in ratios), ratios
    assert max(errors) < 0.01, errors
    assert all(a > 0 for a in _face_areas(obj))


def test_ngon_strip_with_the_captured_coordinates_is_split_too():
    obj = _ngon_object(NGON_VERTS)
    _edit(obj)
    stand = _OperatorStandIn(mode="FIT")
    assert stand.execute(bpy.context) == {"FINISHED"} and stand.reports == ["UV Stripe: 3 strip(s)"], stand.reports
    ratios, errors = _uv_metrics(obj)
    assert max(ratios) / min(ratios) < 1.005 and max(errors) < 0.15     # the coordinates' 0.001 rounding


def test_a_requested_split_that_cannot_be_made_is_reported():
    from InteractionOps.utils import uv_stripe_select_core as select_core
    real = select_core.slice_strip

    def refuse(strip, cuts):
        raise ValueError("refused for the test")

    obj = _polyline([0, 22, 0, 38])
    _edit(obj)
    stand = _OperatorStandIn(mode="FIT")
    select_core.slice_strip = refuse
    try:
        assert stand.execute(bpy.context) == {"FINISHED"}
    finally:
        select_core.slice_strip = real
    assert "UV Stripe: not split (refused for the test)" in stand.reports, stand.reports
    assert len(_vertex_us(obj, 4)) == 1                      # laid out whole


def test_ends_slanted_keeps_the_true_size_and_ends_both_stands_every_cross_edge_vertical():
    obj = _polyline([0, 22, 0, 38])
    _edit(obj)
    assert _run(mode="FIT") == {"FINISHED"}                 # Straight Sides Both, Ends Slanted
    ratios, errors = _uv_metrics(obj)
    assert max(ratios) / min(ratios) < 1 + 1e-6 and max(errors) < 1e-4
    assert _vertex_us(obj, 8) != _vertex_us(obj, 9)         # the mitred end at the 38 degree bend keeps its slant
    assert _run(mode="FIT", ends="BOTH") == {"FINISHED"}
    for i in range(6):
        assert _vertex_us(obj, 2 * i) == _vertex_us(obj, 2 * i + 1), i


def test_vertical_orientation_turns_the_strip():
    obj = _grid(4, 1)
    _edit(obj)
    assert _run(mode="FIT", orientation="VERTICAL") == {"FINISHED"}
    for co, uv in _corners(obj):
        assert _close(uv.x, (1.0 - co.y) / 4.0) and _close(uv.y, co.x / 4.0), (co, uv)
    assert all(a > 0 for a in _face_areas(obj))
    obj = _grid(6, 3, uv_size=10.0)
    _edit(obj, _middle)
    assert _run(mode="IN_PLACE", orientation="VERTICAL") == {"FINISHED"}
    for co, uv in _corners(obj):        # the horizontal result (x, y) / 10 + 0.5 turned about the centre (0.8, 0.65)
        hu, hv = co.x / 10.0 + 0.5, co.y / 10.0 + 0.5
        assert _close(uv.x, 0.8 - (hv - 0.65)) and _close(uv.y, 0.65 + (hu - 0.8)), (co, uv)


# --- the modal ---------------------------------------------------------------------

class _OperatorStandIn:
    """Stands in for an operator instance: the operator's methods run on these props and keep its reports."""

    def __init__(self, **props):
        self.mode, self.orientation, self.mark_seams = "ACTIVE", "HORIZONTAL", True
        self.straight_sides, self.ends, self.balance = "BOTH", "SLANTED", "EVEN_TEXEL"
        self.side_picks = ""
        self.offset_limit, self.offset_seed = 0.25, 0
        self.stretch_limit = 1.25
        self.cup_breaks = self.manual_cuts = self.skipped_cuts = self.align_edges = ""
        self.shape_align = "AUTO"
        self.interactive = self.show_options = False
        self.__dict__.update(OLD_DEFAULTS)
        self.__dict__.update(props)
        self.reports = []

    def report(self, _kinds, message):
        self.reports.append(message)

    def __getattr__(self, name):  # the operator's own methods, bound to this stand-in
        return getattr(operator, name).__get__(self)


class _KeyPress:
    """Stands in for a modal key press event."""

    def __init__(self, key, ctrl=False):
        self.type, self.value = key, "PRESS"
        self.ctrl, self.shift, self.alt, self.oskey = ctrl, False, False, False
        self.mouse_region_x = self.mouse_region_y = self.mouse_x = self.mouse_y = 0


def _uv_state(obj):
    """Every loop's UV (rounded) of the mesh, and its seam edges, to compare states exactly."""
    bm = bmesh.from_edit_mesh(obj.data)
    layer = bm.loops.layers.uv.active
    uvs = None if layer is None else [tuple(round(c, 9) for c in lp[layer].uv) for f in bm.faces for lp in f.loops]
    return uvs, _seams(obj)


def _modal_on(obj, **props):
    op = _OperatorStandIn(**props)
    assert op._start(bpy.context), op.reports
    op._build_overlays(None)
    return op


def test_modal_keys_toggle_their_options_and_the_uvs_follow():
    obj = _polyline([0, 22, 0, 38])
    _edit(obj)
    op = _modal_on(obj, mode="FIT")
    steps = [("W", "orientation", "VERTICAL"), ("Q", "mode", "IN_PLACE"), ("E", "straight_sides", "LONGER"),
             ("E", "straight_sides", "SHORTER"), ("E", "straight_sides", "NONE"), ("E", "straight_sides", "BOTH"),
             ("A", "ends", "BOTH"), ("A", "ends", "LONGER"), ("A", "ends", "SHORTER"), ("A", "ends", "SLANTED"),
             ("B", "balance", "LEAST_STRETCH"), ("B", "balance", "EVEN_TEXEL"),
             ("Q", "mode", "ACTIVE"), ("Q", "mode", "FIT"),
             ("S", "split_at_seams", True), ("X", "mark_seams", False), ("W", "orientation", "HORIZONTAL")]
    for key, name, value in steps:
        before = _uv_state(obj)
        assert op._modal(bpy.context, _KeyPress(key)) == {"RUNNING_MODAL"}
        assert getattr(op, name) == value, (key, name, getattr(op, name))
        if key in "WA":
            assert _uv_state(obj)[0] != before[0], key          # the UVs follow at once
    op._finish(bpy.context)


def test_modal_wheel_changes_the_stretch_limit_under_any_straight_sides():
    obj = _polyline([0, 22, 0, 38])
    _edit(obj)
    op = _modal_on(obj)
    for sides in ("BOTH", "LONGER", "SHORTER", "NONE"):
        op.straight_sides = sides
        op.stretch_limit = 1.25
        assert op._modal(bpy.context, _KeyPress("WHEELUPMOUSE")) == {"RUNNING_MODAL"}, sides
        assert round(op.stretch_limit, 6) == 1.3, sides
        op._modal(bpy.context, _KeyPress("WHEELUPMOUSE", ctrl=True))
        assert round(op.stretch_limit, 6) == 1.31, sides
        op._modal(bpy.context, _KeyPress("WHEELDOWNMOUSE"))
        op._modal(bpy.context, _KeyPress("WHEELDOWNMOUSE"))
        assert round(op.stretch_limit, 6) == 1.21, sides
    assert len(_vertex_us(obj, 4)) == 2 and len(_vertex_us(obj, 8)) == 2      # Auto's tears do not follow the wheel
    op.straight_sides = "BOTH"
    wheel = _KeyPress("WHEELUPMOUSE")
    wheel.shift = True                       # Shift + wheel is the Offset Limit, and only while Random Offset is on
    op.offset_axis = "NONE"
    limit = op.stretch_limit
    assert op._modal(bpy.context, wheel) == {"PASS_THROUGH"} and op.stretch_limit == limit   # zooms/pans the view
    op._finish(bpy.context)


def test_modal_cancel_restores_uvs_seams_and_options():
    obj = _grid(6, 3, uv_size=10.0)
    _edit(obj, _middle)
    _set_seams(obj, {(0, 1), (10, 17)})
    before = _uv_state(obj)
    op = _modal_on(obj, mode="FIT")
    assert _uv_state(obj) != before                            # laid out live
    for key in ("W", "Q", "E", "A", "B", "S", "X"):
        op._modal(bpy.context, _KeyPress(key))
    op._modal(bpy.context, _KeyPress("X"))
    assert op._modal(bpy.context, _KeyPress("ESC")) == {"CANCELLED"}
    assert _uv_state(obj) == before
    assert (op.mode, op.orientation, op.straight_sides, op.ends, op.balance, op.split_at_seams, op.mark_seams) == (
        "FIT", "HORIZONTAL", "BOTH", "SLANTED", "EVEN_TEXEL", False, True)


def test_modal_cancel_removes_a_uv_layer_it_made():
    obj = _grid(4, 1)
    _edit(obj)
    op = _modal_on(obj)
    assert bmesh.from_edit_mesh(obj.data).loops.layers.uv.active is not None
    assert op._modal(bpy.context, _KeyPress("RIGHTMOUSE")) == {"CANCELLED"}
    assert bmesh.from_edit_mesh(obj.data).loops.layers.uv.active is None


def test_modal_confirm_equals_execute():
    def made(confirm):
        obj = _polyline([0, 22, 0, 38])
        _edit(obj)
        _set_seams(obj, {(6, 7)})
        if confirm:
            op = _modal_on(obj)
            for key in ("W", "S", "WHEELUPMOUSE"):
                op._modal(bpy.context, _KeyPress(key))
            assert op._modal(bpy.context, _KeyPress("SPACE")) == {"FINISHED"}
            return _uv_state(obj), op.reports
        stand = _OperatorStandIn(orientation="VERTICAL", split_at_seams=True)
        assert stand.execute(bpy.context) == {"FINISHED"}
        return _uv_state(obj), stand.reports

    assert made(True) == made(False)


def test_modal_nothing_to_lay_out_cancels_and_restores():
    obj = _grid(3, 2, keep={(0, 0), (1, 0), (2, 0), (1, 1)}, uv_size=10.0)
    _edit(obj)
    before = _uv_state(obj)
    op = _OperatorStandIn()
    assert op._start(bpy.context) is False
    assert any("nothing laid out" in r for r in op.reports), op.reports
    assert _uv_state(obj) == before


# --- Active mode and random offsets ---------------------------------------------------

def _set_active(obj, center):
    """Make the face whose centre is ``center`` (x, y) the active face."""
    bm = bmesh.from_edit_mesh(obj.data)
    bm.faces.active = min(bm.faces, key=lambda f: (f.calc_center_median().xy - Vector(center)).length)
    bmesh.update_edit_mesh(obj.data)


def _set_uvs(obj, fn):
    """Give every loop the UV ``fn(world position)``."""
    bm = bmesh.from_edit_mesh(obj.data)
    layer = bm.loops.layers.uv.active or bm.loops.layers.uv.new("UVMap")
    for f in bm.faces:
        for lp in f.loops:
            lp[layer].uv = fn(obj.matrix_world @ lp.vert.co)
    bmesh.update_edit_mesh(obj.data)


def _uv_box(obj, keep):
    """((min u, min v), (max u, max v)) over the corners of the faces whose centre passes ``keep``."""
    corners = _corners(obj, keep)
    us = [uv.x for _c, uv in corners]
    vs = [uv.y for _c, uv in corners]
    return Vector((min(us), min(vs))), Vector((max(us), max(vs)))


def _size(box):
    return box[1] - box[0]


def _low(c):
    return c.y < 1.0


def _high(c):
    return c.y > 2.0 and c.x < 3.0


def _two_strips():
    """In a 4 x 4 grid with UVs at xy / 10 + 0.5: a 4 x 1 strip (row 0) and a 3 x 2 patch (rows 2-3) selected,
    the other cells round them, the active face in the strip."""
    obj = _grid(4, 4, uv_size=10.0)
    _edit(obj, lambda c: _low(c) or _high(c))
    _set_active(obj, (1.5, 0.5))
    return obj


def test_active_fits_the_other_strip_onto_the_reference():
    obj = _two_strips()
    assert _run(mode="IN_PLACE") == {"FINISHED"}
    in_place = _corners(obj, _low)
    patch_in_place = _size(_uv_box(obj, _high))              # 0.3 x 0.2
    assert _close(patch_in_place.x, 0.3) and _close(patch_in_place.y, 0.2)
    for fit, expected in (("BOTH", (0.15, 0.1)), ("WIDTH", (0.4, 0.8 / 3)), ("HEIGHT", (0.15, 0.1))):
        obj = _two_strips()
        assert _run(mode="ACTIVE", active_fit=fit) == {"FINISHED"}
        assert all((a[1] - b[1]).length < 1e-6 for a, b in zip(_corners(obj, _low), in_place))   # the reference
        reference = _uv_box(obj, _low)
        box = _uv_box(obj, _high)
        assert _close(_size(box).x, expected[0]) and _close(_size(box).y, expected[1]), (fit, _size(box))
        assert ((box[0] + box[1]) / 2 - (reference[0] + reference[1]) / 2).length < 1e-6
        assert all(a > 0 for a in _face_areas(obj))


def test_active_follows_the_orientation():
    obj = _two_strips()
    assert _run(mode="ACTIVE", orientation="VERTICAL") == {"FINISHED"}
    reference, box = _uv_box(obj, _low), _uv_box(obj, _high)
    assert _close(_size(reference).x, 0.1) and _close(_size(reference).y, 0.4)      # the reference turned
    # the patch (0.2 x 0.3 turned) fitted inside the reference by one factor, 0.5: on its width, centred
    assert _close(_size(box).x, 0.1) and _close(_size(box).y, 0.15), _size(box)
    assert ((box[0] + box[1]) / 2 - (reference[0] + reference[1]) / 2).length < 1e-6
    assert all(a > 0 for a in _face_areas(obj))


def test_active_puts_the_other_pieces_of_a_torn_strip_on_the_active_piece():
    obj = _polyline([0, 40])                                 # torn at the bend: faces 0-1 and face 2
    _edit(obj)
    _set_uvs(obj, lambda co: co.xy * 0.1)
    _set_active(obj, (0.5, 0.0))
    assert _run(mode="ACTIVE") == {"FINISHED"}
    first = _uv_box(obj, lambda c: c.x < 1.9)
    last = _uv_box(obj, lambda c: c.x > 2.1)
    # one strip height, so the shorter piece fits inside the first at the same scale: same band, same centre
    assert abs(first[0].y - last[0].y) < 1e-6 and abs(first[1].y - last[1].y) < 1e-6
    assert ((first[0] + first[1]) / 2 - (last[0] + last[1]) / 2).length < 1e-6
    assert _size(last).x < _size(first).x


def test_active_without_an_active_face_lays_out_in_place_and_says_so():
    obj = _grid(6, 3, uv_size=10.0)
    _edit(obj, _middle)
    bm = bmesh.from_edit_mesh(obj.data)
    bm.faces.active = None
    bmesh.update_edit_mesh(obj.data)
    stand = _OperatorStandIn()                               # Active is the default
    assert stand.mode == "ACTIVE"
    assert stand.execute(bpy.context) == {"FINISHED"}
    assert stand.reports == ["UV Stripe: no active face to fit to; laid out In Place", "UV Stripe: 1 strip(s)"]
    for co, uv in _corners(obj):                             # as In Place lays it out
        assert _close(uv.x, co.x / 10.0 + 0.5) and _close(uv.y, co.y / 10.0 + 0.5), (co, uv)


def test_random_offset_moves_the_other_strip_along_u_only():
    obj = _two_strips()
    assert _run(mode="ACTIVE") == {"FINISHED"}
    still_reference, still = _uv_box(obj, _low), _uv_box(obj, _high)
    states = []
    for _ in range(2):
        obj = _two_strips()
        assert _run(mode="ACTIVE", offset_axis="ALONG", offset_limit=0.2, offset_seed=7) == {"FINISHED"}
        reference, box = _uv_box(obj, _low), _uv_box(obj, _high)
        assert (reference[0] - still_reference[0]).length < 1e-6         # the reference does not move
        assert (_size(box) - _size(still)).length < 1e-6                 # the fit is kept
        shift = box[0] - still[0]
        assert abs(shift.y) < 1e-6 and 1e-4 < abs(shift.x) <= 0.2 + 1e-6, shift
        states.append(_uv_state(obj)[0])
    assert states[0] == states[1]                            # the same seed gives the same UVs
    obj = _two_strips()
    assert _run(mode="ACTIVE", offset_axis="ALONG", offset_limit=0.2, offset_seed=8) == {"FINISHED"}
    assert _uv_state(obj)[0] != states[0]


def test_modal_fit_to_active_and_random_offset_keys():
    obj = _two_strips()
    op = _modal_on(obj, active_fit="HEIGHT")                 # the operator's default
    sizes = []
    for expected in ("BOTH", "WIDTH", "HEIGHT"):
        assert op._modal(bpy.context, _KeyPress("D")) == {"RUNNING_MODAL"} and op.active_fit == expected
        sizes.append(tuple(round(c, 6) for c in _size(_uv_box(obj, _high))))
    assert sizes == [(0.15, 0.1), (0.4, round(0.8 / 3, 6)), (0.15, 0.1)]
    before = _uv_box(obj, _high)
    shift_wheel = _KeyPress("WHEELUPMOUSE")
    shift_wheel.shift = True
    assert op._modal(bpy.context, shift_wheel) == {"PASS_THROUGH"}       # no random offset: the view pans
    for expected in ("ALONG", "ACROSS", "BOTH"):
        op._modal(bpy.context, _KeyPress("Z"))
        assert op.offset_axis == expected
    moved = _uv_box(obj, _high)
    assert (moved[0] - before[0]).length > 1e-4
    op._modal(bpy.context, _KeyPress("R"))
    assert op.offset_seed == 1 and (_uv_box(obj, _high)[0] - moved[0]).length > 1e-6
    assert op._modal(bpy.context, shift_wheel) == {"RUNNING_MODAL"} and _close(op.offset_limit, 0.30)
    shift_wheel.ctrl = True
    shift_wheel.type = "WHEELDOWNMOUSE"
    op._modal(bpy.context, shift_wheel)
    assert _close(op.offset_limit, 0.29)
    assert op._modal(bpy.context, _KeyPress("RET")) == {"FINISHED"}
    confirmed = _uv_state(obj)
    obj = _two_strips()
    stand = _OperatorStandIn(active_fit="HEIGHT", offset_axis="BOTH", offset_seed=1, offset_limit=0.29)
    assert stand.execute(bpy.context) == {"FINISHED"}
    assert _uv_state(obj) == confirmed


def test_modal_hud_and_help_list_every_key():
    from InteractionOps.operators.mesh_uv_stripe import _Result
    op = _OperatorStandIn(show_options=True)
    op._build_overlays(None)
    params = [p for section in op._hud.param_sections for p in section.params]
    assert [p.name for p in params] == [
        "Straight Sides (E)", "Ends (A)", "Stretch Limit (Wheel)", "Align (G)", "Manual Cuts", "Doubled Vertices",
        "More Options (Tab)", "Balance (B)", "Mode (Q)", "Orientation (W)", "Fit to Active (D)",
        "Split at Seams (S)", "Mark Seams (X)", "Random Offset (Z)", "Offset Limit (Shift + Wheel)",
        "Offset Seed (R)", "Merge Doubles (F)"]
    assert [p.value_text() for p in params] == [
        "Both", "Slanted", "1.25", "Auto", "0", "0", "✓", "Even Texel", "Active", "Horizontal", "Width and Height",
        "✗", "✓", "None", "0.25", "0", "✗"]
    always = {"Straight Sides (E)", "Ends (A)", "Stretch Limit (Wheel)", "More Options (Tab)"}
    more = {"Balance (B)", "Mode (Q)", "Orientation (W)", "Fit to Active (D)", "Split at Seams (S)",
            "Mark Seams (X)", "Random Offset (Z)", "Offset Limit (Shift + Wheel)", "Offset Seed (R)",
            "Merge Doubles (F)"}
    assert _shown(op) == always | more                       # no Align, Manual Cuts or Doubled Vertices yet
    op.straight_sides = "NONE"                               # Align applies to every piece; Ends do not
    assert _shown(op) == always | more | {"Align (G)"}
    active = {p.name: p.is_active() for p in params}
    assert not active["Ends (A)"] and active["Straight Sides (E)"]
    op.straight_sides = "BOTH"
    assert "Align (G)" not in _shown(op)
    op._result = _Result(unfolded=1)                         # a piece relaxed to its real shape
    assert "Align (G)" in _shown(op)
    op._result = _Result(doubles=2)
    assert "Doubled Vertices" in _shown(op) and "Align (G)" not in _shown(op)
    assert {p.name: p.value_text() for p in params}["Doubled Vertices"] == "2"
    op._result = _Result()
    op.manual_cuts = '{"a": [1, 4], "b": [2]}'
    assert "Manual Cuts" in _shown(op)
    assert {p.name: p.value_text() for p in params}["Manual Cuts"] == "3" and op._manual_cut_count() == 3
    op.manual_cuts = ""
    active = {p.name: p.is_active() for p in params}
    assert active["Fit to Active (D)"] and not active["Offset Limit (Shift + Wheel)"]
    assert not active["Offset Seed (R)"]
    op.mode, op.offset_axis = "FIT", "BOTH"
    active = {p.name: p.is_active() for p in params}
    assert not active["Fit to Active (D)"] and active["Offset Limit (Shift + Wheel)"] and active["Offset Seed (R)"]
    assert [(it.label, it.key) for it in op._help.sections[0].items] == [
        ("Side straight / free", "LMB on a side"), ("Pick cut edges, break a ring", "C"),
        ("Pick the align edge", "V"), ("Confirm", "Enter / Space"), ("Cancel", "Esc / RMB")]
    assert op._status_text() == "LMB side: straight/free · Tab: more · Enter: confirm · Esc: cancel"
    op._picking = True
    assert op._status_text().startswith("Picking cut edges")
    op._picking, op._align_picking = False, True
    assert op._status_text().startswith("Picking the align edge")


def test_modal_old_letters_are_free():
    obj = _grid(4, 1)
    _edit(obj)
    op = _modal_on(obj)
    before = _uv_state(obj)
    for key in ("M", "O", "U"):
        assert op._modal(bpy.context, _KeyPress(key)) == {"RUNNING_MODAL"}
    assert op._modal(bpy.context, _KeyPress("N")) == {"PASS_THROUGH"}       # the sidebar opens again
    assert _uv_state(obj) == before
    assert (op.mode, op.orientation, op.ends, op.offset_axis, op.offset_seed) == (
        "ACTIVE", "HORIZONTAL", "SLANTED", "NONE", 0)
    op._modal(bpy.context, _KeyPress("ESC"))


# --- doubled vertices ---------------------------------------------------------------

def _double_object(merged=False):
    """The strip with an unmerged double (28, 21) as a mesh; ``merged``: the same strip modelled without it."""
    verts = dict(DOUBLE_VERTS)
    faces = dict(DOUBLE_FACES)
    if merged:
        del verts[28]
        faces = {fid: tuple(dict.fromkeys(21 if v == 28 else v for v in face)) for fid, face in faces.items()}
    ids = sorted(verts)
    at = {v: i for i, v in enumerate(ids)}
    obj = _object([verts[v] for v in ids], [tuple(at[v] for v in face) for face in faces.values()])
    _edit(obj)
    return obj


def _layout_by_position(obj):
    """Every selected corner's (rounded position, rounded UV), sorted: compares layouts across topologies."""
    bm = bmesh.from_edit_mesh(obj.data)
    layer = bm.loops.layers.uv.active
    return sorted((tuple(round(c, 4) for c in lp.vert.co), tuple(round(c, 5) for c in lp[layer].uv))
                  for f in bm.faces if f.select for lp in f.loops)


def test_doubled_vertices_are_reported():
    obj = _double_object()
    stand = _OperatorStandIn(mode="FIT")
    assert stand.execute(bpy.context) == {"FINISHED"}
    assert ("UV Stripe: 1 doubled vertices in the strip; turn on Merge Doubles or use Merge by Distance"
            in stand.reports), stand.reports
    assert len(obj.data.vertices) == 14


def test_merge_doubles_merges_exactly_the_double():
    clean = _double_object(merged=True)
    stand = _OperatorStandIn(mode="FIT")
    assert stand.execute(bpy.context) == {"FINISHED"}
    expected = _layout_by_position(clean)
    obj = _double_object()
    stand = _OperatorStandIn(mode="FIT", merge_doubles=True)
    assert stand.execute(bpy.context) == {"FINISHED"}
    assert "UV Stripe: merged 1 doubled vertices" in stand.reports, stand.reports
    assert not any("doubled vertices in the strip" in r for r in stand.reports), stand.reports
    assert len(bmesh.from_edit_mesh(obj.data).verts) == 13
    assert _layout_by_position(obj) == expected


def test_modal_merge_doubles():
    obj = _double_object()
    op = _modal_on(obj, mode="FIT")
    assert op._result.doubles == 1
    assert any("1 doubled vertices" in r for r in op.reports), op.reports
    params = {p.name: p for section in op._hud.param_sections for p in section.params}
    assert params["Doubled Vertices"].value_text() == "1"
    preview = _uv_state(obj)
    assert op._modal(bpy.context, _KeyPress("F")) == {"RUNNING_MODAL"} and op.merge_doubles
    assert _uv_state(obj) == preview                         # the preview does not change the mesh
    assert op._modal(bpy.context, _KeyPress("ESC")) == {"CANCELLED"}
    assert len(bmesh.from_edit_mesh(obj.data).verts) == 14 and not op.merge_doubles
    obj = _double_object()
    op = _modal_on(obj, mode="FIT")
    op._modal(bpy.context, _KeyPress("F"))
    op.reports.clear()
    assert op._modal(bpy.context, _KeyPress("RET")) == {"FINISHED"}
    assert "UV Stripe: merged 1 doubled vertices" in op.reports, op.reports
    assert len(bmesh.from_edit_mesh(obj.data).verts) == 13
    confirmed = _layout_by_position(obj)
    obj = _double_object()
    stand = _OperatorStandIn(mode="FIT", merge_doubles=True)
    assert stand.execute(bpy.context) == {"FINISHED"}
    assert _layout_by_position(obj) == confirmed


def test_operator_defaults():
    rna = bpy.ops.iops.mesh_uv_stripe.get_rna_type().properties
    assert rna["mode"].default == "ACTIVE" and rna["active_fit"].default == "HEIGHT"
    assert rna["orientation"].default == "HORIZONTAL"
    assert rna["straight_sides"].default == "BOTH" and rna["ends"].default == "SLANTED"
    assert rna["balance"].default == "EVEN_TEXEL"
    assert round(rna["stretch_limit"].default, 6) == 1.25
    assert (rna["stretch_limit"].hard_min, rna["stretch_limit"].hard_max) == (1.0, 3.0)
    assert rna["split_at_seams"].default and rna["mark_seams"].default
    assert rna["merge_doubles"].default and rna["offset_axis"].default == "ALONG"
    for removed in ("layout", "split_at_bends", "split_angle"):
        assert removed not in rna, removed
    assert [item.identifier for item in rna["straight_sides"].enum_items] == ["BOTH", "LONGER", "SHORTER", "NONE"]
    assert [item.identifier for item in rna["ends"].enum_items] == ["SLANTED", "BOTH", "LONGER", "SHORTER"]
    assert [item.identifier for item in rna["balance"].enum_items] == ["EVEN_TEXEL", "LEAST_STRETCH"]
    assert [item.identifier for item in rna["offset_axis"].enum_items] == ["NONE", "ALONG", "ACROSS", "BOTH"]


def _wedge():
    """One flat quad whose far row rises by 3 over its length of 2: no straight-row layout lays it out clean."""
    obj = _object([(0.0, 0.0, 0.0), (2.0, 0.0, 0.0), (2.0, 4.0, 0.0), (0.0, 1.0, 0.0)], [(0, 1, 2, 3)])
    _edit(obj)
    return obj


def _worst_stretch(obj):
    from InteractionOps.utils.uv_stripe_core import face_stretch
    bm = bmesh.from_edit_mesh(obj.data)
    layer = bm.loops.layers.uv.active
    return max(face_stretch([tuple(lp.vert.co) for lp in f.loops], [tuple(lp[layer].uv) for lp in f.loops])
               for f in bm.faces if f.select)


def test_auto_lays_a_tapered_piece_out_by_the_stretch_limit():
    obj = _wedge()
    assert _run(mode="FIT", stretch_limit=3.0) == {"FINISHED"}
    straight = _worst_stretch(obj)
    assert 1.25 < straight < 3.0, straight                    # within 3.0: laid out straight
    assert _run(mode="FIT", stretch_limit=1.25) == {"FINISHED"}
    assert _worst_stretch(obj) < 1.0 + 1e-4                   # beyond 1.25: True Shape
    obj = _wedge()
    assert bpy.ops.iops.mesh_uv_stripe(mode="FIT") == {"FINISHED"}      # Auto at 1.25 by default
    assert _worst_stretch(obj) < 1.0 + 1e-4


def _l_arc_object(cols=8, inner=0.8, outer=1.0, wall=0.2):
    """An arc with an L profile over half a turn: a flat ledge from ``inner`` to ``outer`` and a wall hanging
    from its inner edge. Returns the object and its three rings of vertex indices (outer edge, fold, foot)."""
    profile = [(outer, 0.0), (inner, 0.0), (inner, -wall)]
    points, rings = [], []
    for r, z in profile:
        rings.append(list(range(len(points), len(points) + cols + 1)))
        points.extend((r * math.cos(math.pi * i / cols), r * math.sin(math.pi * i / cols), z) for i in range(cols + 1))
    faces = [(rings[k][i], rings[k][i + 1], rings[k + 1][i + 1], rings[k + 1][i]) for k in range(2) for i in range(cols)]
    return _object(points, faces), rings


def test_auto_lays_a_wide_arc_out_as_one_straight_island():
    obj, rings = _l_arc_object()
    _edit(obj)
    assert _run(mode="FIT", split_at_seams=True) == {"FINISHED"}
    bm = bmesh.from_edit_mesh(obj.data)
    layer = bm.loops.layers.uv.active
    uv_of: dict[int, set] = {}
    for f in bm.faces:
        for lp in f.loops:
            uv_of.setdefault(lp.vert.index, set()).add((round(lp[layer].uv.x, 5), round(lp[layer].uv.y, 5)))
    assert all(len(uvs) == 1 for uvs in uv_of.values()), "the arc is torn into several islands"
    v = {i: next(iter(uvs))[1] for i, uvs in uv_of.items()}
    for ring in rings:                                       # both rails and the fold line run straight along U
        assert max(v[i] for i in ring) - min(v[i] for i in ring) < 1e-4, ring
    assert all(a > 0 for a in _face_areas(obj))
    assert _worst_stretch(obj) < 1.25


def test_modal_wheel_changes_the_stretch_limit_under_auto():
    obj = _wedge()
    op = _modal_on(obj, mode="FIT", stretch_limit=1.25)
    assert _worst_stretch(obj) < 1.0 + 1e-4
    for _ in range(6):
        assert op._modal(bpy.context, _KeyPress("WHEELDOWNMOUSE")) == {"RUNNING_MODAL"}
    assert op.stretch_limit == 1.0
    for _ in range(5):
        op._modal(bpy.context, _KeyPress("WHEELUPMOUSE"))
    op._modal(bpy.context, _KeyPress("WHEELUPMOUSE", ctrl=True))
    assert round(op.stretch_limit, 6) == 1.26
    for _ in range(40):
        op._modal(bpy.context, _KeyPress("WHEELUPMOUSE"))
    assert op.stretch_limit == 3.0 and _worst_stretch(obj) > 1.25        # laid out straight again
    op._finish(bpy.context)


def test_default_active_fit_matches_the_height_and_leaves_a_clean_mesh_alone():
    obj = _two_strips()
    bm = bmesh.from_edit_mesh(obj.data)
    before = (len(bm.verts), len(bm.edges), len(bm.faces), sorted(f.index for f in bm.faces if f.select))
    assert bpy.ops.iops.mesh_uv_stripe(offset_axis="NONE") == {"FINISHED"}     # every other option at its default
    bm = bmesh.from_edit_mesh(obj.data)
    assert (len(bm.verts), len(bm.edges), len(bm.faces), sorted(f.index for f in bm.faces if f.select)) == before
    reference, box = _uv_box(obj, _low), _uv_box(obj, _high)
    assert _close(_size(box).y, _size(reference).y) and _close(_size(box).x, 0.15), _size(box)


def _selected_faces(obj):
    return [f for f in bmesh.from_edit_mesh(obj.data).faces if f.select]


def test_active_fit_stretches_no_face():
    from InteractionOps.operators import uv_stripe_bridge
    for fit in ("BOTH", "WIDTH", "HEIGHT"):
        obj = _two_strips()
        assert _run(mode="ACTIVE", active_fit=fit, offset_axis="NONE") == {"FINISHED"}
        bm = bmesh.from_edit_mesh(obj.data)
        assert uv_stripe_bridge.stretched_faces(bm, _selected_faces(obj), obj.matrix_world) == [], fit


def test_seams_split_a_strip_whose_sides_fan_round_a_corner():
    """A quad with a triangulated trapezoid folded back at each end: as one strip each side fans round one rail
    vertex, so its far row is a single point and the strip cannot be torn at the seams between the quad and its
    sides. The seams then split it by faces, and every part comes out at its true shape."""
    from InteractionOps.operators import uv_stripe_bridge
    points = [(0.0, 0.0, 0.0), (0.4, 0.0, 0.0), (0.4, 0.0, 0.125), (0.4, 0.15, 0.125),
              (0.0, 0.0, 0.125), (0.0, 0.15, 0.125), (0.0, 0.5, 0.0), (0.4, 0.5, 0.0)]
    obj = _object(points, [(4, 2, 1, 0), (5, 4, 0), (5, 0, 6), (7, 1, 3), (3, 1, 2)])
    _edit(obj)
    _set_seams(obj, {(0, 4), (1, 2)})
    for sides in ("BOTH", "NONE"):
        assert _run(mode="FIT", straight_sides=sides, split_at_seams=True) == {"FINISHED"}
        assert all(abs(a) > 1e-6 for a in _face_areas(obj)), sides       # no face collapsed onto a line
    bm = bmesh.from_edit_mesh(obj.data)                                     # True Shape: every face at its shape
    assert uv_stripe_bridge.stretched_faces(bm, _selected_faces(obj), obj.matrix_world) == []


def test_stretched_faces_are_measured_in_world_space():
    from InteractionOps.operators import uv_stripe_bridge
    obj = _two_strips()
    obj.scale = (3.0, 1.0, 1.0)
    bpy.context.view_layer.update()
    assert bpy.ops.iops.mesh_uv_stripe() == {"FINISHED"}
    bm = bmesh.from_edit_mesh(obj.data)
    assert uv_stripe_bridge.stretched_faces(bm, _selected_faces(obj), obj.matrix_world) == []
    layer = bm.loops.layers.uv.active
    selected = _selected_faces(obj)
    for f in selected:
        for lp in f.loops:
            lp[layer].uv.x *= 2.0
    assert set(uv_stripe_bridge.stretched_faces(bm, selected, obj.matrix_world)) == set(selected)


def test_ends_both_on_a_bent_strip_reports_stretched_faces():
    obj = _polyline([0, 22, 0, 38])
    _edit(obj)
    stand = _OperatorStandIn(mode="FIT", ends="BOTH")
    result = stand._lay_out(bpy.context)
    assert result.done == 3                                  # torn at the 22 and 38 degree bends
    assert result.stretched_faces == 4
    assert len(result.stretched) % 2 == 0 and result.stretched


def test_default_offset_runs_along_the_strip_in_both_orientations():
    for orientation, along in (("HORIZONTAL", 0), ("VERTICAL", 1)):
        obj = _two_strips()
        assert bpy.ops.iops.mesh_uv_stripe(orientation=orientation, offset_axis="NONE") == {"FINISHED"}
        still_reference, still = _uv_box(obj, _low), _uv_box(obj, _high)
        obj = _two_strips()
        assert bpy.ops.iops.mesh_uv_stripe(orientation=orientation) == {"FINISHED"}         # Along Strip
        reference, box = _uv_box(obj, _low), _uv_box(obj, _high)
        assert (reference[0] - still_reference[0]).length < 1e-6
        shift = box[0] - still[0]
        assert abs(shift[1 - along]) < 1e-6 and 1e-4 < abs(shift[along]) <= 0.25 + 1e-6, (orientation, shift)
        obj = _two_strips()
        assert bpy.ops.iops.mesh_uv_stripe(orientation=orientation, offset_axis="ACROSS") == {"FINISHED"}
        shift = _uv_box(obj, _high)[0] - still[0]
        assert abs(shift[along]) < 1e-6 and abs(shift[1 - along]) > 1e-4, (orientation, shift)


def test_true_shape_follows_a_tapering_strip():
    # A 3 x 1 strip whose far rail closes in to 0.7: No Stretch keeps one height, True Shape the real width.
    points = [(float(x), 0.0, 0.0) for x in range(4)] + [(float(x), 1.0 - 0.1 * x, 0.0) for x in range(4)]
    obj = _object(points, [(i, i + 1, i + 5, i + 4) for i in range(3)])
    _edit(obj)
    assert _run(mode="FIT", straight_sides="NONE") == {"FINISHED"}
    ratios, errors = _uv_metrics(obj)
    assert max(ratios) / min(ratios) < 1 + 1e-6 and max(errors) < 1e-4, (ratios, errors)
    assert _run(mode="FIT") == {"FINISHED"}
    ratios, _errors = _uv_metrics(obj)
    assert max(ratios) / min(ratios) > 1.01


def test_triangulated_strip_is_its_quads_rectangle():
    obj = _grid(4, 1)
    _edit(obj)
    bm = bmesh.from_edit_mesh(obj.data)
    bmesh.ops.triangulate(bm, faces=list(bm.faces), quad_method="ALTERNATE")
    for f in bm.faces:
        f.select_set(True)
    bmesh.update_edit_mesh(obj.data)
    assert len(bm.faces) == 8
    assert _run(mode="FIT") == {"FINISHED"}
    for co, uv in _corners(obj):
        assert _close(uv.x, co.x / 4.0) and _close(uv.y, co.y / 4.0), (co, uv)
    assert all(a > 0 for a in _face_areas(obj))


def test_scaled_object_follows_world_size():
    obj = _grid(4, 1)
    obj.scale = (0.5, 2.0, 1.0)          # world strip: 2 long, 2 wide
    _edit(obj)
    assert _run(mode="FIT") == {"FINISHED"}
    corners = _corners(obj)
    us = [uv.x for _c, uv in corners]
    vs = [uv.y for _c, uv in corners]
    assert _close(max(us) - min(us), 1.0) and _close(max(vs) - min(vs), 1.0)


def test_rejected_island_leaves_the_other():
    t_shape = {(0, 0), (1, 0), (2, 0), (1, 1)}
    strip = {(x, 4) for x in range(4)}
    obj = _grid(4, 5, keep=t_shape | strip, uv_size=10.0)
    _edit(obj)
    t_before = [uv.copy() for _c, uv in _corners(obj, lambda c: c.y < 2.0)]
    assert _run(mode="FIT") == {"FINISHED"}
    t_after = [uv for _c, uv in _corners(obj, lambda c: c.y < 2.0)]
    assert all((a - b).length < 1e-9 for a, b in zip(t_before, t_after)), "rejected island was changed"
    bm = bmesh.from_edit_mesh(obj.data)
    assert not any(e.seam for e in bm.edges if all(v.co.y < 2.5 for v in e.verts)), "rejected island got seams"
    for co, uv in _corners(obj, lambda c: c.y > 4.0):
        assert _close(uv.x, co.x / 4.0) and _close(uv.y, (co.y - 4.0) / 4.0), (co, uv)


def test_nothing_selected_cancels():
    obj = _grid(3, 1)
    _edit(obj, lambda c: False)
    try:
        result = _run(mode="FIT")
    except RuntimeError as exc:          # a CANCELLED operator with a WARNING report raises in background
        assert "no faces selected" in str(exc), exc
        return
    assert result == {"CANCELLED"}


def test_only_rejected_cancels():
    obj = _grid(3, 2, keep={(0, 0), (1, 0), (2, 0), (1, 1)})
    _edit(obj)
    try:
        result = _run(mode="FIT")
    except RuntimeError as exc:
        assert "nothing laid out" in str(exc), exc
        return
    assert result == {"CANCELLED"}


def test_mesh_without_uv_gets_one():
    obj = _grid(3, 1)
    assert len(obj.data.uv_layers) == 0
    _edit(obj)
    assert _run(mode="FIT") == {"FINISHED"}
    bpy.ops.object.mode_set(mode="OBJECT")
    assert len(obj.data.uv_layers) == 1


# --- cup break: a ring opened at a picked cross edge ------------------------------------

def _band(n=8, triangle=False):
    """A ring of ``n`` quads round a cylinder, unrolling without stretch (vertices 0 .. n - 1 at z = 0, n .. 2n - 1
    at z = 1, cross edge k = (k, n + k)): the picked break opens it as one strip, Auto has no bend to tear at.
    ``triangle`` splits face 0 into two triangles along (0, n + 1). Returns (vertices, faces) by id."""
    verts = {}
    for i in range(n):
        a = 2 * math.pi * i / n
        verts[i] = (math.cos(a), math.sin(a), 0.0)
        verts[n + i] = (math.cos(a), math.sin(a), 1.0)
    faces = {i: (i, (i + 1) % n, n + (i + 1) % n, n + i) for i in range(n)}
    if triangle:
        a, b, c, d = faces[0]
        faces[0], faces[n] = (a, b, c), (a, c, d)
    return verts, faces


def _annulus(n=8, triangle=False, flat=False):
    """A ring of ``n`` quads (vertices 0 .. n - 1 below, n .. 2n - 1 above, cross edge k = (k, n + k)): round a
    cylinder (``_band``), or with ``flat`` a flat annulus Auto tears at every bend; ``triangle`` splits face 0."""
    if flat:
        verts, faces = (flat_annulus_with_triangle if triangle else flat_annulus)(n)
    else:
        verts, faces = _band(n, triangle)
    return _object([verts[i] for i in range(2 * n)], [faces[k] for k in sorted(faces)])


def _edge_index(obj, pair):
    bm = bmesh.from_edit_mesh(obj.data)
    bm.edges.index_update()
    pair = tuple(sorted(pair))
    return next(e.index for e in bm.edges if tuple(sorted(v.index for v in e.verts)) == pair)


def _cup(obj, *pairs):
    import json
    return json.dumps({obj.name: [_edge_index(obj, p) for p in pairs]})


def _inner_edges(obj):
    """The edges between two selected faces, as sorted vertex-id pairs."""
    bm = bmesh.from_edit_mesh(obj.data)
    return {tuple(sorted(v.index for v in e.verts)) for e in bm.edges if sum(f.select for f in e.link_faces) == 2}


def _uv_islands(obj, only=None):
    """The number of UV islands among the selected faces (or those whose centre passes ``only``): faces joined
    where both corners of an edge agree."""
    bm = bmesh.from_edit_mesh(obj.data)
    layer = bm.loops.layers.uv.active
    faces = [f for f in bm.faces if f.select and (only is None or only(f.calc_center_median()))]
    parent = {f: f for f in faces}

    def root(f):
        while parent[f] is not f:
            f = parent[f]
        return f

    def uv_at(face, vert):
        return next(lp[layer].uv for lp in face.loops if lp.vert == vert)

    for e in bm.edges:
        linked = [f for f in e.link_faces if f in parent]
        if len(linked) == 2 and all((uv_at(linked[0], v) - uv_at(linked[1], v)).length < 1e-6 for v in e.verts):
            parent[root(linked[0])] = root(linked[1])
    return len({root(f) for f in faces})


def _rectangles(obj):
    """Whether every selected face's UVs form an axis-aligned rectangle."""
    bm = bmesh.from_edit_mesh(obj.data)
    layer = bm.loops.layers.uv.active
    for f in bm.faces:
        if not f.select:
            continue
        pts = [lp[layer].uv for lp in f.loops]
        if len(pts) != 4 or len({round(p.x, 6) for p in pts}) != 2 or len({round(p.y, 6) for p in pts}) != 2:
            return False
    return True


def test_cup_break_opens_a_ring_as_one_piece_and_auto_tears_a_flat_ring_at_every_bend():
    obj = _annulus()                                         # round a cylinder: unrolls whole, Auto has no bend to tear
    _edit(obj)
    assert _run(mode="FIT") == {"FINISHED"}
    assert _uv_islands(obj) == 1 and (3, 11) not in _seams(obj)         # the ring is cut at a rung of its own
    obj = _annulus()
    _edit(obj)
    assert _run(mode="FIT", cup_breaks=_cup(obj, (3, 11))) == {"FINISHED"}
    assert _uv_islands(obj) == 1
    assert _seams(obj) & _inner_edges(obj) == {(3, 11)}
    assert all(a > 0 for a in _face_areas(obj))
    # a flat annulus bends at every rung: Auto tears it at all eight, with or without a break
    every_rung = {(k, 8 + k) for k in range(8)}
    obj = _annulus(flat=True)
    _edit(obj)
    assert _run(mode="FIT") == {"FINISHED"}
    assert _uv_islands(obj) == 8 and _seams(obj) & _inner_edges(obj) == every_rung
    obj = _annulus(flat=True)
    _edit(obj)
    assert _run(mode="FIT", cup_breaks=_cup(obj, (3, 11))) == {"FINISHED"}
    assert _uv_islands(obj) == 8 and _seams(obj) & _inner_edges(obj) == every_rung


def test_cup_break_all_quads_is_rectangles_under_the_defaults():
    obj = _annulus()
    _edit(obj)
    assert _run(mode="FIT", cup_breaks=_cup(obj, (5, 13))) == {"FINISHED"}
    assert _uv_islands(obj) == 1 and _rectangles(obj)
    assert all(a > 0 for a in _face_areas(obj))


def test_cup_break_replaces_an_old_seam():
    obj = _annulus()
    _edit(obj)
    _set_seams(obj, {(6, 14)})
    assert _run(mode="FIT", split_at_seams=True, mark_seams=True, cup_breaks=_cup(obj, (3, 11))) == {"FINISHED"}
    assert _uv_islands(obj) == 1
    assert _seams(obj) & _inner_edges(obj) == {(3, 11)}


def test_cup_break_with_a_triangle_follows_the_ends():
    obj = _annulus(triangle=True)
    _edit(obj)
    assert _run(mode="FIT", cup_breaks=_cup(obj, (3, 11))) == {"FINISHED"}
    assert _uv_islands(obj) == 1
    assert all(a > 0 for a in _face_areas(obj))
    assert not _rectangles(obj)                              # laid out by No Stretch, not forced to Rectangles
    assert _run(mode="FIT", ends="BOTH", cup_breaks=_cup(obj, (3, 11))) == {"FINISHED"}
    assert _uv_islands(obj) == 1 and all(a > 0 for a in _face_areas(obj))


def test_cup_break_on_an_open_strip_is_ignored():
    obj = _grid(4, 1)
    _edit(obj)
    assert _run(mode="FIT") == {"FINISHED"}
    plain = _uv_state(obj)
    obj = _grid(4, 1)
    _edit(obj)
    assert _run(mode="FIT", cup_breaks=_cup(obj, (2, 7))) == {"FINISHED"}
    assert _uv_state(obj) == plain


def test_cup_break_is_taken_before_doubles_are_merged():
    # The flat ring with outer vertex 5 doubled by vertex 16 inside face 4: merging renumbers the edges after it.
    verts, faces = _band(8)
    points = [verts[i] for i in range(16)] + [(verts[5][0], verts[5][1] + 1e-5, 0.0)]
    faces[4] = (4, 5, 16, 13, 12)
    faces[5] = (16, 6, 14, 13)
    obj = _object(points, [faces[k] for k in sorted(faces)])
    _edit(obj)
    before = _edge_index(obj, (7, 15))
    stand = _OperatorStandIn(mode="FIT", merge_doubles=True,
                             cup_breaks=_cup(obj, (7, 15)))
    assert stand.execute(bpy.context) == {"FINISHED"}, stand.reports
    assert "UV Stripe: merged 1 doubled vertices" in stand.reports, stand.reports
    assert _edge_index(obj, (7, 15)) != before               # the index alone would now name another edge
    assert _uv_islands(obj) == 1
    assert _seams(obj) & _inner_edges(obj) == {(7, 15)}


# --- cup break in the modal: C picks, LMB sets, R is the seed -------------------------------

def _ring_and_strip():
    """The 8-quad band (vertices 0 - 15, below y = 2) and an open 4-quad strip at y = 3 (vertices 16 - 25),
    one mesh, all selected."""
    verts, faces = _band(8)
    points = [verts[i] for i in range(16)] + [(float(x), y, 0.0) for y in (3.0, 3.5) for x in range(5)]
    strip = [(16 + i, 17 + i, 22 + i, 21 + i) for i in range(4)]
    obj = _object(points, [faces[k] for k in sorted(faces)] + strip)
    _edit(obj)
    return obj


def _two_rings():
    """Two 8-quad bands side by side (vertices 0 - 15 at x = 0, 16 - 31 at x = 3), one mesh, all selected."""
    verts, faces = _band(8)
    points = [verts[i] for i in range(16)] + [(x + 3.0, y, z) for x, y, z in (verts[i] for i in range(16))]
    polys = [faces[k] for k in sorted(faces)]
    obj = _object(points, polys + [tuple(v + 16 for v in face) for face in polys])
    _edit(obj)
    return obj


def _ring_part(c):
    return c.y < 2.0 and c.x < 2.0


def _torn_at(op, obj, pair):
    """Whether the preview draws edge ``pair`` (vertex ids) among the tears."""
    bm = bmesh.from_edit_mesh(obj.data)
    bm.verts.ensure_lookup_table()
    ends = {tuple(round(c, 6) for c in obj.matrix_world @ bm.verts[i].co) for i in pair}
    tears = op._result.tears
    return any({tuple(round(c, 6) for c in tears[i]), tuple(round(c, 6) for c in tears[i + 1])} == ends
               for i in range(0, len(tears), 2))


def _ring_seams(obj, only=_ring_part):
    bm = bmesh.from_edit_mesh(obj.data)
    return {tuple(sorted(v.index for v in e.verts)) for e in bm.edges if e.seam
            and sum(f.select and only(f.calc_center_median()) for f in e.link_faces) == 2}


def test_c_enters_and_leaves_picking():
    obj = _annulus()
    _edit(obj)
    op = _modal_on(obj, mode="FIT")
    laid = _uv_state(obj)
    for leave in ("ESC", "RIGHTMOUSE", "C"):
        assert op._modal(bpy.context, _KeyPress("C")) == {"RUNNING_MODAL"} and op._picking
        assert op._modal(bpy.context, _KeyPress("E")) == {"RUNNING_MODAL"} and op.straight_sides == "BOTH"   # swallowed
        assert op._modal(bpy.context, _KeyPress("LEFTMOUSE")) == {"RUNNING_MODAL"} and op._picking  # no edge: stays
        assert op._modal(bpy.context, _KeyPress("WHEELUPMOUSE")) == {"PASS_THROUGH"}            # the view zooms
        assert op._modal(bpy.context, _KeyPress(leave)) == {"RUNNING_MODAL"} and not op._picking, leave
        assert _uv_state(obj) == laid and getattr(op, "cup_breaks", "") == ""
    op._finish(bpy.context)


def test_set_break_relays_out_and_keeps_picking():
    obj = _annulus()
    _edit(obj)
    op = _modal_on(obj, mode="FIT")
    assert (3, 11) not in _seams(obj)                        # the ring is cut at a rung of its own until it is broken
    index = _edge_index(obj, (3, 11))
    assert index in op._result.rings[obj.name]              # a ring's cross edge can be picked
    op._picking = True
    assert op._set_break(bpy.context, obj, index)
    assert op._picking and _uv_islands(obj) == 1             # picking goes on: more edges can be marked
    assert _torn_at(op, obj, (3, 11)) and _seams(obj) & _inner_edges(obj) == {(3, 11)}
    op._finish(bpy.context)


def test_lmb_in_picking_sets_the_hovered_break():
    # A real cursor cannot hover headless: the hover lookup is stood in for, the event handling is the operator's.
    obj = _annulus()
    _edit(obj)
    op = _modal_on(obj, mode="FIT")
    index = _edge_index(obj, (5, 13))
    op._hover_break = lambda _context, _event: (obj, index)
    op._modal(bpy.context, _KeyPress("C"))
    move = _KeyPress("MOUSEMOVE")
    move.value = "NOTHING"
    assert op._modal(bpy.context, move) == {"RUNNING_MODAL"} and op._hover[:2] == (obj, index)
    assert len(op._hover[2]) == 2                            # the hovered edge's end points, for the preview
    assert op._modal(bpy.context, _KeyPress("LEFTMOUSE")) == {"RUNNING_MODAL"}       # not the confirm
    assert op._picking and _uv_islands(obj) == 1 and _ring_seams(obj, lambda c: True) == {(5, 13)}
    assert op._modal(bpy.context, _KeyPress("C")) == {"RUNNING_MODAL"} and not op._picking
    laid = _uv_state(obj)
    assert op._modal(bpy.context, _KeyPress("LEFTMOUSE")) == {"RUNNING_MODAL"}       # outside picking: no confirm
    assert _uv_state(obj) == laid and op._side_hover is None
    assert op._modal(bpy.context, _KeyPress("RET")) == {"FINISHED"}                  # Enter confirms


def test_second_break_on_the_same_ring_replaces_the_first():
    import json
    obj = _annulus()
    _edit(obj)
    op = _modal_on(obj, mode="FIT")
    a, b = _edge_index(obj, (3, 11)), _edge_index(obj, (6, 14))
    op._set_break(bpy.context, obj, a)
    op._set_break(bpy.context, obj, b)
    assert json.loads(op.cup_breaks) == {obj.name: [b]}
    assert _uv_islands(obj) == 1 and _seams(obj) & _inner_edges(obj) == {(6, 14)}
    op._finish(bpy.context)


def test_breaks_on_two_rings_are_both_kept():
    import json
    obj = _two_rings()
    op = _modal_on(obj, mode="FIT")
    a, b = _edge_index(obj, (3, 11)), _edge_index(obj, (16 + 6, 16 + 14))
    op._set_break(bpy.context, obj, a)
    op._set_break(bpy.context, obj, b)
    assert sorted(json.loads(op.cup_breaks)[obj.name]) == sorted([a, b])
    assert _uv_islands(obj, lambda c: c.x < 1.5) == 1 and _uv_islands(obj, lambda c: c.x > 1.5) == 1
    assert _seams(obj) & _inner_edges(obj) == {(3, 11), (22, 30)}
    op._finish(bpy.context)


def test_break_survives_option_changes():
    obj = _ring_and_strip()
    op = _modal_on(obj, mode="FIT")
    open_rung = _edge_index(obj, (18, 23))
    assert open_rung not in op._result.rings.get(obj.name, {})        # an open strip's cross edge is no break
    assert open_rung in op._result.cross[obj.name]                    # but it can be picked as a cut
    assert not op._set_break(bpy.context, obj, open_rung) and getattr(op, "cup_breaks", "") == ""
    op._set_break(bpy.context, obj, _edge_index(obj, (3, 11)))
    for key in ("S", "E", "A", "E", "S"):
        op._modal(bpy.context, _KeyPress(key))
        assert _uv_islands(obj, _ring_part) == 1, key
        assert _ring_seams(obj) == {(3, 11)} and _torn_at(op, obj, (3, 11)), key
    op._finish(bpy.context)


def test_r_changes_seed_and_c_does_not():
    obj = _annulus()
    _edit(obj)
    op = _modal_on(obj, mode="FIT", offset_axis="ALONG")
    assert op._modal(bpy.context, _KeyPress("R")) == {"RUNNING_MODAL"} and op.offset_seed == 1
    op._modal(bpy.context, _KeyPress("C"))
    assert op.offset_seed == 1 and op._picking
    op._modal(bpy.context, _KeyPress("ESC"))
    op._finish(bpy.context)


def test_cancel_after_break_restores_uvs_and_seams():
    obj = _annulus()
    _edit(obj)
    _set_uvs(obj, lambda co: co.xy * 0.1)
    _set_seams(obj, {(6, 14)})
    before = _uv_state(obj)
    op = _modal_on(obj, mode="FIT", split_at_seams=True)
    op._set_break(bpy.context, obj, _edge_index(obj, (3, 11)))
    assert op.cup_breaks != ""
    assert op._modal(bpy.context, _KeyPress("RIGHTMOUSE")) == {"CANCELLED"}
    assert _uv_state(obj) == before and op.cup_breaks == ""


def test_confirm_after_break_equals_execute():
    def made(confirm):
        obj = _ring_and_strip()
        brk = _cup(obj, (3, 11))
        if confirm:
            op = _modal_on(obj, mode="FIT")
            op._set_break(bpy.context, obj, _edge_index(obj, (3, 11)))
            assert op._modal(bpy.context, _KeyPress("RET")) == {"FINISHED"}
            assert op.cup_breaks == brk                      # kept for redo
            return _uv_state(obj)
        stand = _OperatorStandIn(mode="FIT", cup_breaks=brk)
        assert stand.execute(bpy.context) == {"FINISHED"}
        return _uv_state(obj)

    assert made(True) == made(False)


def test_cup_breaks_is_no_shared_setting():
    rna = bpy.ops.iops.mesh_uv_stripe.get_rna_type().properties
    assert rna["cup_breaks"].is_hidden and rna["cup_breaks"].is_skip_save
    from InteractionOps.operators.uv_stripe_bridge import StripeSettings
    assert "cup_breaks" not in StripeSettings.__dataclass_fields__
    for name in ("manual_cuts", "skipped_cuts"):
        assert rna[name].is_hidden and rna[name].is_skip_save and name not in StripeSettings.__dataclass_fields__


# --- cut edges in the modal: C picks, LMB marks and unmarks --------------------------------

def _edges(text):
    import json
    return json.loads(text) if text else {}


def _click(op, obj, pair):
    """LMB in picking on cross edge ``pair``. A real cursor cannot hover headless: the hover lookup is stood in
    for, the event handling is the operator's. Picking stays on after the click."""
    index = _edge_index(obj, pair)
    op._hover_break = lambda _context, _event: (obj, index)
    if not op._picking:
        assert op._modal(bpy.context, _KeyPress("C")) == {"RUNNING_MODAL"} and op._picking
    assert op._modal(bpy.context, _KeyPress("LEFTMOUSE")) == {"RUNNING_MODAL"}
    assert op._picking
    return index


def test_manual_cut_tears_an_open_strip_and_a_second_click_mends_it():
    obj = _grid(4, 1)
    _edit(obj)
    op = _modal_on(obj, mode="FIT")
    assert _uv_islands(obj) == 1
    assert _edge_index(obj, (2, 7)) in op._result.cross[obj.name]      # an open strip's cross edge is pickable
    index = _click(op, obj, (2, 7))
    assert _uv_islands(obj) == 2 and _edges(op.manual_cuts) == {obj.name: [index]}
    assert _torn_at(op, obj, (2, 7)) and (2, 7) in _seams(obj)          # Mark Seams marks it like any tear
    assert op._manual_cut_count() == 1
    _click(op, obj, (1, 6))
    assert _uv_islands(obj) == 3 and len(_edges(op.manual_cuts)[obj.name]) == 2
    _click(op, obj, (2, 7))
    _click(op, obj, (1, 6))
    assert _uv_islands(obj) == 1 and op.manual_cuts == "" and op.skipped_cuts == "" and op.cup_breaks == ""
    op._finish(bpy.context)


def test_suppressing_a_bend_tear_joins_the_pieces():
    obj = _polyline([0, 22, 0, 38])
    _edit(obj)
    op = _modal_on(obj, mode="FIT")                          # Split at Bends at 15 degrees: torn at (4, 5), (8, 9)
    assert _uv_islands(obj) == 3
    index = _edge_index(obj, (8, 9))
    assert index in op._result.bend_tears[obj.name]
    _click(op, obj, (8, 9))
    assert _uv_islands(obj) == 2 and _edges(op.skipped_cuts) == {obj.name: [index]} and op.manual_cuts == ""
    assert (8, 9) not in _seams(obj) and (4, 5) in _seams(obj)
    assert op._result.skipped_tears                                # the skipped tear is drawn
    op._modal(bpy.context, _KeyPress("A"))                   # Split at Bends off: the skip stays stored
    op._modal(bpy.context, _KeyPress("A"))
    assert _uv_islands(obj) == 2
    _click(op, obj, (8, 9))                                  # restored
    assert _uv_islands(obj) == 3 and op.skipped_cuts == "" and not op._result.skipped_tears
    op._finish(bpy.context)


def test_a_seam_tear_is_not_changed_by_a_click():
    obj = _grid(4, 1)
    _edit(obj)
    _set_seams(obj, {(2, 7)})
    op = _modal_on(obj, mode="FIT", split_at_seams=True)
    assert _uv_islands(obj) == 2
    laid = _uv_state(obj)
    _click(op, obj, (2, 7))
    assert _uv_state(obj) == laid and op.manual_cuts == "" and op.skipped_cuts == ""
    op._modal(bpy.context, _KeyPress("C"))
    op._modal(bpy.context, _KeyPress("S"))                   # Split at Seams off: the edge can be cut by hand
    _click(op, obj, (2, 7))
    assert _uv_islands(obj) == 2 and op.manual_cuts != ""
    op._finish(bpy.context)


def test_a_manual_cut_tears_a_broken_ring():
    obj = _annulus()
    _edit(obj)
    op = _modal_on(obj, mode="FIT")
    brk = _click(op, obj, (3, 11))                           # the ring has no break: the click breaks it
    assert _edges(op.cup_breaks) == {obj.name: [brk]} and _uv_islands(obj) == 1 and op.manual_cuts == ""
    cut = _click(op, obj, (6, 14))                           # the ring has its break: the click cuts by hand
    assert _edges(op.manual_cuts) == {obj.name: [cut]} and _edges(op.cup_breaks) == {obj.name: [brk]}
    assert _uv_islands(obj) == 2 and _seams(obj) & _inner_edges(obj) == {(3, 11), (6, 14)}
    assert all(a > 0 for a in _face_areas(obj))
    _click(op, obj, (3, 11))                                 # the break is removed; the manual cut stays
    assert op.cup_breaks == "" and op.manual_cuts != ""
    assert _uv_islands(obj) == 1 and _seams(obj) & _inner_edges(obj) == {(6, 14)}   # closed again, cut by hand
    op._finish(bpy.context)


def test_manual_cuts_tear_the_parts_of_an_island_split_at_its_seams():
    # A T of four cells: no strip as a whole; its seam (5, 6) splits off the top cell, the row of three is a strip.
    obj = _grid(3, 2, keep={(0, 0), (1, 0), (2, 0), (1, 1)})
    _edit(obj)
    _set_seams(obj, {(5, 6)})
    op = _modal_on(obj, mode="FIT", split_at_seams=True)
    assert _uv_islands(obj) == 2
    _click(op, obj, (1, 5))
    assert _uv_islands(obj) == 3 and op.manual_cuts != ""
    _click(op, obj, (1, 5))
    assert _uv_islands(obj) == 2 and op.manual_cuts == ""
    op._finish(bpy.context)


def test_cancel_restores_the_cut_properties():
    obj = _polyline([0, 22, 0, 38])
    _edit(obj)
    before = _uv_state(obj)
    op = _modal_on(obj, mode="FIT", manual_cuts="", skipped_cuts="")
    _click(op, obj, (8, 9))
    _click(op, obj, (2, 3))
    assert op.manual_cuts != "" and op.skipped_cuts != ""
    assert op._modal(bpy.context, _KeyPress("RIGHTMOUSE")) == {"RUNNING_MODAL"} and not op._picking  # stops picking
    assert op._modal(bpy.context, _KeyPress("RIGHTMOUSE")) == {"CANCELLED"}
    assert _uv_state(obj) == before and op.manual_cuts == "" and op.skipped_cuts == ""


def test_confirm_after_cuts_equals_execute():
    def made(confirm):
        obj = _ring_and_strip()
        if confirm:
            op = _modal_on(obj, mode="FIT")
            _click(op, obj, (3, 11))                         # the ring's break
            _click(op, obj, (6, 14))                         # a manual cut on the broken ring
            _click(op, obj, (18, 23))                        # a manual cut on the open strip
            op._modal(bpy.context, _KeyPress("C"))
            assert op._modal(bpy.context, _KeyPress("RET")) == {"FINISHED"}
            kept = (op.cup_breaks, op.manual_cuts, op.skipped_cuts)          # kept for redo
            assert all(kept[:2])
            return _uv_state(obj), kept
        stand = _OperatorStandIn(mode="FIT", cup_breaks=_cup(obj, (3, 11)),
                                 manual_cuts=_dump(obj, (6, 14), (18, 23)))
        assert stand.execute(bpy.context) == {"FINISHED"}
        return _uv_state(obj), (stand.cup_breaks, stand.manual_cuts, "")

    confirmed, kept = made(True)
    executed, given = made(False)
    assert confirmed == executed
    def indices(text):                        # each run makes a new object: compare the edge indices alone
        return sorted(i for listed in _edges(text).values() for i in listed)

    assert indices(kept[0]) == indices(given[0]) and indices(kept[1]) == indices(given[1])


def test_confirm_after_a_skipped_bend_tear_equals_execute():
    def made(confirm):
        obj = _polyline([0, 22, 0, 38])
        _edit(obj)
        if confirm:
            op = _modal_on(obj, mode="FIT")
            _click(op, obj, (8, 9))
            op._modal(bpy.context, _KeyPress("C"))
            assert op._modal(bpy.context, _KeyPress("SPACE")) == {"FINISHED"}
            return _uv_state(obj), list(_edges(op.skipped_cuts).values())     # each run makes a new object
        stand = _OperatorStandIn(mode="FIT", skipped_cuts=_dump(obj, (8, 9)))
        assert stand.execute(bpy.context) == {"FINISHED"}
        return _uv_state(obj), list(_edges(stand.skipped_cuts).values())

    assert made(True) == made(False)


def _dump(obj, *pairs):
    import json
    return json.dumps({obj.name: [_edge_index(obj, p) for p in pairs]}, sort_keys=True)


def test_malformed_cut_properties_read_as_none():
    import json
    obj = _grid(4, 1)
    _edit(obj)
    assert _run(mode="FIT") == {"FINISHED"}
    plain = _uv_state(obj)
    for text in ("not json", "[1, 2]", json.dumps({obj.name: 3}), json.dumps({obj.name: ["a", True, 999, -1]})):
        assert _run(mode="FIT", manual_cuts=text, skipped_cuts=text) == {"FINISHED"}, text
        assert _uv_state(obj) == plain, text


class _WindowManager:
    """Stands in for the window manager: keeps the modal handler instead of needing a window."""

    def __init__(self):
        self.modal = []

    def modal_handler_add(self, op):
        self.modal.append(op)
        return True


class _InvokeContext:
    """``bpy.context`` with no region or area and a stand-in window manager, so ``invoke`` runs headless."""

    region = None
    area = None

    def __init__(self):
        self.window_manager = _WindowManager()

    def __getattr__(self, name):
        return getattr(bpy.context, name)


def _recording_handlers(module):
    """Wrap ``module``'s safe_handler_add / _remove so every call is recorded (and still made); returns
    (added: [(handle, callback name, draw type)], removed: [handle], undo)."""
    added, removed = [], []
    real_add, real_remove = module.safe_handler_add, module.safe_handler_remove

    def add(space, callback, args, region, draw_type, **kwargs):
        handle = real_add(space, callback, args, region, draw_type, **kwargs)
        added.append((handle, callback.__name__, draw_type))
        return handle

    def remove(handle, space, region):
        removed.append(handle)
        real_remove(handle, space, region)

    module.safe_handler_add, module.safe_handler_remove = add, remove

    def undo():
        module.safe_handler_add, module.safe_handler_remove = real_add, real_remove
    return added, removed, undo


def test_invoke_draws_the_lines_in_the_scene_and_the_hud_on_top():
    from InteractionOps.operators import mesh_uv_stripe as module
    obj = _polyline([0, 22, 0, 38])
    _edit(obj)
    added, removed, undo = _recording_handlers(module)
    try:
        op = _OperatorStandIn(mode="FIT", interactive=True)
        context = _InvokeContext()
        assert op.invoke(context, _KeyPress("LEFTMOUSE")) == {"RUNNING_MODAL"}, op.reports
        assert context.window_manager.modal == [op]
        assert [(name, kind) for _h, name, kind in added] == [
            ("_draw_view_callback", "POST_VIEW"), ("_draw_callback", "POST_PIXEL")]
        handles = {h for h, _name, _kind in added}
        assert len(handles) == 2 and {op._handle_view, op._handle} == handles
        assert handles <= module._ACTIVE_HANDLES
        assert op._result.sides and not op._result.outline    # an open piece is drawn by its four sides, not an outline
        op._draw_view_callback(bpy.context)        # no GPU in the background: the draw fails inside, never raises
        assert op._modal(bpy.context, _KeyPress("ESC")) == {"CANCELLED"}
        assert set(removed) == handles and not handles & module._ACTIVE_HANDLES
        assert op._handle is None and op._handle_view is None
        # a reload's purge removes both as well
        removed.clear()
        _edit(obj)
        op = _OperatorStandIn(mode="FIT", interactive=True)
        assert op.invoke(_InvokeContext(), _KeyPress("LEFTMOUSE")) == {"RUNNING_MODAL"}
        handles = {op._handle_view, op._handle}
        module._purge_handles()
        assert set(removed) == handles and not module._ACTIVE_HANDLES
        op._modal(bpy.context, _KeyPress("ESC"))
    finally:
        undo()
        module._purge_handles()


def test_invoke_without_interactive_lays_out_at_once():
    from InteractionOps.operators import mesh_uv_stripe as module
    obj = _polyline([0, 22, 0, 38])
    _edit(obj)
    stand = _OperatorStandIn(mode="FIT")
    assert stand.execute(bpy.context) == {"FINISHED"}
    executed = _uv_state(obj), stand.reports
    obj = _polyline([0, 22, 0, 38])
    _edit(obj)
    added, _removed, undo = _recording_handlers(module)
    try:
        op = _OperatorStandIn(mode="FIT")
        context = _InvokeContext()
        assert op.invoke(context, _KeyPress("LEFTMOUSE")) == {"FINISHED"}, op.reports
        assert context.window_manager.modal == [] and not added       # no modal, nothing drawn
        assert getattr(op, "_hud", None) is None
    finally:
        undo()
    assert (_uv_state(obj), op.reports) == executed


def test_invoke_with_interactive_starts_the_modal():
    from InteractionOps.operators import mesh_uv_stripe as module
    obj = _polyline([0, 22, 0, 38])
    _edit(obj)
    before = _uv_state(obj)
    try:
        op = _OperatorStandIn(mode="FIT", interactive=True)
        context = _InvokeContext()
        assert op.invoke(context, _KeyPress("LEFTMOUSE")) == {"RUNNING_MODAL"}, op.reports
        assert context.window_manager.modal == [op] and op._hud is not None
        assert _uv_state(obj) != before                   # laid out live
        assert op._modal(bpy.context, _KeyPress("ESC")) == {"CANCELLED"}
        assert _uv_state(obj) == before
    finally:
        module._purge_handles()


def test_interactive_and_more_options_properties():
    rna = bpy.ops.iops.mesh_uv_stripe.get_rna_type().properties
    assert rna["interactive"].name == "Interactive" and not rna["interactive"].default
    assert rna["interactive"].is_hidden and rna["interactive"].is_skip_save
    assert rna["show_options"].name == "More Options" and not rna["show_options"].default
    assert rna["show_options"].is_hidden and not rna["show_options"].is_skip_save
    from InteractionOps.operators.uv_stripe_bridge import StripeSettings
    for name in ("interactive", "show_options"):
        assert name not in StripeSettings.__dataclass_fields__


ALWAYS_ROWS = {"Straight Sides (E)", "Ends (A)", "Stretch Limit (Wheel)", "More Options (Tab)"}
MORE_ROWS = {"Balance (B)", "Mode (Q)", "Orientation (W)", "Fit to Active (D)", "Split at Seams (S)",
             "Mark Seams (X)", "Random Offset (Z)", "Offset Limit (Shift + Wheel)", "Offset Seed (R)",
             "Merge Doubles (F)"}


def _shown(op):
    return {p.name for section in op._hud.param_sections for p in section.params if p.is_visible()}


def test_tab_toggles_more_options_and_the_hud_rows():
    obj = _polyline([0, 22, 0, 38])
    _edit(obj)
    op = _modal_on(obj)                       # Straight Sides Both: no piece unfolded, so no Align row
    assert not op.show_options
    assert _shown(op) == ALWAYS_ROWS
    before = _uv_state(obj)
    assert op._modal(bpy.context, _KeyPress("TAB")) == {"RUNNING_MODAL"} and op.show_options
    assert _uv_state(obj) == before                       # only the HUD changes
    assert _shown(op) == ALWAYS_ROWS | MORE_ROWS
    op.straight_sides = "NONE"
    op._relayout(bpy.context)
    assert _shown(op) == ALWAYS_ROWS | MORE_ROWS | {"Align (G)"}      # every piece at its real shape: Align applies
    op._modal(bpy.context, _KeyPress("TAB"))
    assert not op.show_options and _shown(op) == ALWAYS_ROWS | {"Align (G)"}
    op.manual_cuts = '{"a": [1]}'
    assert "Manual Cuts" in _shown(op)
    op.manual_cuts = ""
    op._modal(bpy.context, _KeyPress("ESC"))


def test_keys_of_hidden_rows_work_while_collapsed():
    obj = _polyline([0, 22, 0, 38])
    _edit(obj)
    op = _modal_on(obj, mode="FIT")
    assert not op.show_options and "Orientation (W)" not in _shown(op)
    before = _uv_state(obj)
    assert op._modal(bpy.context, _KeyPress("W")) == {"RUNNING_MODAL"}
    assert op.orientation == "VERTICAL" and _uv_state(obj)[0] != before[0]
    for key in ("Q", "A", "B"):
        assert op._modal(bpy.context, _KeyPress(key)) == {"RUNNING_MODAL"}
    assert (op.mode, op.ends, op.balance) == ("IN_PLACE", "BOTH", "LEAST_STRETCH") and not op.show_options
    op._modal(bpy.context, _KeyPress("ESC"))


class _BpyWithOps:
    """``bpy`` with its ``ops`` replaced: a background Blender runs a Python INVOKE_DEFAULT call as EXEC, so the
    call UV Stripe (Interactive) makes is caught and run on a stand-in instead."""

    def __init__(self, ops):
        self.ops = ops

    def __getattr__(self, name):
        return getattr(bpy, name)


def test_interactive_operator_registers_and_starts_the_modal():
    from types import SimpleNamespace

    from InteractionOps.operators import mesh_uv_stripe as module
    from InteractionOps.utils.functions import build_bindable_defaults, keymap_name_for_idname
    rna = bpy.ops.iops.mesh_uv_stripe_interactive.get_rna_type()
    assert rna.name == "UV Stripe (Interactive)"
    assert module.IOPS_OT_Mesh_UV_Stripe_Interactive.is_bindable
    rows = {row[0]: row for row in build_bindable_defaults()}
    assert rows["iops.mesh_uv_stripe_interactive"][1] == "NONE" and rows["iops.mesh_uv_stripe"][1] == "NONE"
    assert keymap_name_for_idname("iops.mesh_uv_stripe_interactive") == "Mesh"
    obj = _polyline([0, 22, 0, 38])
    _edit(obj)
    assert bpy.ops.iops.mesh_uv_stripe_interactive.poll()
    calls, started = [], []
    context = _InvokeContext()

    def mesh_uv_stripe(exec_context, **props):
        calls.append((exec_context, props))
        op = _OperatorStandIn(mode="FIT", **props)
        started.append(op)
        return op.invoke(context, _KeyPress("LEFTMOUSE"))

    module.bpy = _BpyWithOps(SimpleNamespace(iops=SimpleNamespace(mesh_uv_stripe=mesh_uv_stripe)))
    try:
        assert module.IOPS_OT_Mesh_UV_Stripe_Interactive.execute(None, bpy.context) == {"FINISHED"}
        assert calls == [("INVOKE_DEFAULT", {"interactive": True})]
        assert context.window_manager.modal == started and started[0]._hud is not None
        assert started[0]._modal(bpy.context, _KeyPress("ESC")) == {"CANCELLED"}
        module.bpy = _BpyWithOps(SimpleNamespace(iops=SimpleNamespace(mesh_uv_stripe=lambda *a, **k: {"CANCELLED"})))
        assert module.IOPS_OT_Mesh_UV_Stripe_Interactive.execute(None, bpy.context) == {"CANCELLED"}
    finally:
        module.bpy = bpy
        module._purge_handles()
    bpy.ops.object.mode_set(mode="OBJECT")
    assert not bpy.ops.iops.mesh_uv_stripe_interactive.poll()


def _operator_defaults():
    """Every plain property of UV Stripe at its default (the stand-in otherwise holds ``OLD_DEFAULTS``)."""
    out = {}
    for prop in bpy.ops.iops.mesh_uv_stripe.get_rna_type().properties:
        if prop.identifier == "rna_type" or prop.type not in {"BOOLEAN", "ENUM", "FLOAT", "INT"}:
            continue
        if getattr(prop, "is_array", False) or (prop.type == "ENUM" and prop.is_enum_flag):
            continue
        out[prop.identifier] = prop.default
    return out


def _step_object(active=None):
    """The strip with a stepped end face, its seams 12-18 and 13-19 marked; ``active``: that face id made active."""
    ids = sorted(STEP_VERTS)
    at = {v: i for i, v in enumerate(ids)}
    order = list(STEP_FACES)
    obj = _object([STEP_VERTS[v] for v in ids], [tuple(at[v] for v in STEP_FACES[f]) for f in order])
    _edit(obj)
    _set_seams(obj, {tuple(sorted((at[12], at[18]))), tuple(sorted((at[13], at[19])))})
    bm = bmesh.from_edit_mesh(obj.data)
    bm.faces.ensure_lookup_table()
    bm.faces.active = bm.faces[order.index(active)] if active is not None else None
    bmesh.update_edit_mesh(obj.data)
    return obj


def test_the_stepped_strip_with_the_users_defaults():
    # Active, Fit to Active Width, Auto, Split at Seams and at Bends (5 degrees), Mark Seams, Random Offset
    # along the strip, Merge Doubles: nothing raises, nothing folds, through execute and the modal alike.
    defaults = _operator_defaults()
    assert defaults["mode"] == "ACTIVE" and defaults["straight_sides"] == "BOTH" and defaults["split_at_seams"]
    for active in (None, 20):
        obj = _step_object(active)
        assert bpy.ops.iops.mesh_uv_stripe() == {"FINISHED"}
        assert all(a > 1e-9 for a in _face_areas(obj)), _face_areas(obj)
        obj = _step_object(active)
        stand = _OperatorStandIn(**defaults)
        assert stand.execute(bpy.context) == {"FINISHED"}, stand.reports
        assert all(a > 1e-9 for a in _face_areas(obj))
        obj = _step_object(active)
        op = _modal_on(obj, **defaults)
        for key in ("E", "E", "E", "E", "E", "Q", "Q", "Q", "W", "D", "A", "A", "S", "S"):
            assert op._modal(bpy.context, _KeyPress(key)) == {"RUNNING_MODAL"}, key
            assert all(a > 1e-9 for a in _face_areas(obj)), (key, op.straight_sides, op.mode)
        assert op._modal(bpy.context, _KeyPress("RET")) == {"FINISHED"}, op.reports
    for sides in ("BOTH", "LONGER", "SHORTER", "NONE"):
        for ends in ("SLANTED", "BOTH", "LONGER", "SHORTER"):
            obj = _step_object(20)
            assert bpy.ops.iops.mesh_uv_stripe(straight_sides=sides, ends=ends) == {"FINISHED"}
            assert all(a > 1e-9 for a in _face_areas(obj)), (sides, ends, _face_areas(obj))


# --- aligning True Shape: G cycles Align, V picks the edge a piece runs along --------------------------

def _edge_uvs(obj, pair):
    """The two UVs of edge ``pair`` in the first selected face holding it."""
    bm = bmesh.from_edit_mesh(obj.data)
    layer = bm.loops.layers.uv.active
    bm.verts.ensure_lookup_table()
    for f in bm.faces:
        if not f.select:
            continue
        at = {lp.vert.index: lp[layer].uv.copy() for lp in f.loops}
        if pair[0] in at and pair[1] in at:
            return at[pair[0]], at[pair[1]]
    raise AssertionError(f"no selected face holds {pair}")


def _along_u(obj, pair):
    a, b = _edge_uvs(obj, pair)
    return abs(a.y - b.y) < 1e-6 and abs(a.x - b.x) > 1e-4


def _along_v(obj, pair):
    a, b = _edge_uvs(obj, pair)
    return abs(a.x - b.x) < 1e-6 and abs(a.y - b.y) > 1e-4


def _shape_strip():
    """The polyline torn at its bends into three True Shape pieces: faces 0-1 (vertices 0-5), 2-3 (4-9), 4
    (8-11); vertex 2i left, 2i + 1 right of joint i, so (2i, 2i + 2) is a row edge and (2i, 2i + 1) a cross edge."""
    obj = _polyline([0, 22, 0, 38])
    _edit(obj)
    return obj


def _click_align(op, obj, pair):
    """LMB while picking the align edge on edge ``pair`` (the hover lookup stood in for, as in ``_click``)."""
    index = _edge_index(obj, pair)
    op._hover_break = lambda _context, _event: (obj, index)
    if not op._align_picking:
        assert op._modal(bpy.context, _KeyPress("V")) == {"RUNNING_MODAL"} and op._align_picking
    assert op._modal(bpy.context, _KeyPress("LEFTMOUSE")) == {"RUNNING_MODAL"}
    assert op._align_picking and not op._picking
    return index


def test_g_cycles_the_align_values():
    obj = _shape_strip()
    op = _modal_on(obj, mode="FIT", straight_sides="NONE")
    seen = []
    for _ in range(4):
        assert op._modal(bpy.context, _KeyPress("G")) == {"RUNNING_MODAL"}
        seen.append(op.shape_align)
    assert seen == ["LONGEST", "SHORTEST", "PICKED", "AUTO"]
    op._finish(bpy.context)


def test_v_and_lmb_store_the_align_edge_and_keep_picking():
    obj = _shape_strip()
    op = _modal_on(obj, mode="FIT", straight_sides="NONE")
    assert _uv_islands(obj) == 3
    assert _edge_index(obj, (0, 2)) in op._result.align_pieces[obj.name]       # row edges are pickable
    assert _edge_index(obj, (2, 3)) in op._result.align_pieces[obj.name]       # and cross edges
    assert not op._result.align_lines
    auto = _uv_state(obj)
    assert not _along_v(obj, (4, 5))                         # the mitred end at the 22 degree bend is slanted
    tear = _click_align(op, obj, (4, 5))                     # the tear edge lies in both its pieces
    assert op.shape_align == "PICKED" and _edges(op.align_edges) == {obj.name: [tear]}
    assert _uv_state(obj) != auto and op._result.align_lines                    # the UVs follow; drawn while used
    for only in (lambda c: c.x < 2.0, lambda c: 2.0 < c.x and c.y < 1.0):      # stood up on both sides of it
        a, b = (next(uv for co, uv in _corners(obj, only) if co.xy == obj.data.vertices[v].co.xy) for v in (4, 5))
        assert abs(a.x - b.x) < 1e-6, (a, b)
    assert op._align_edge_count() == 1
    row = _click_align(op, obj, (0, 2))                      # piece 0: replaces the tear edge it shared
    assert _edges(op.align_edges) == {obj.name: [row]} and _along_u(obj, (0, 2))
    end = _click_align(op, obj, (8, 9))                      # the 38 degree tear: pieces 1 and 2, both kept
    assert _edges(op.align_edges) == {obj.name: [row, end]}
    assert _along_u(obj, (0, 2)) and _along_v(obj, (8, 9)) and _uv_islands(obj) == 3
    _click_align(op, obj, (0, 2))                            # clicked again: removed
    assert _edges(op.align_edges) == {obj.name: [end]} and op.shape_align == "PICKED"
    assert op._modal(bpy.context, _KeyPress("V")) == {"RUNNING_MODAL"} and not op._align_picking
    op._finish(bpy.context)


def test_the_two_pick_modes_are_exclusive():
    obj = _shape_strip()
    op = _modal_on(obj, mode="FIT", straight_sides="NONE")
    op._modal(bpy.context, _KeyPress("C"))
    assert op._picking and not op._align_picking
    op._modal(bpy.context, _KeyPress("V"))
    assert op._align_picking and not op._picking
    op._modal(bpy.context, _KeyPress("C"))
    assert op._picking and not op._align_picking
    op._modal(bpy.context, _KeyPress("ESC"))
    assert not op._picking and not op._align_picking
    op._modal(bpy.context, _KeyPress("V"))
    assert op._modal(bpy.context, _KeyPress("RIGHTMOUSE")) == {"RUNNING_MODAL"} and not op._align_picking
    op._finish(bpy.context)


def test_cancel_restores_align_and_its_edges():
    obj = _shape_strip()
    before = _uv_state(obj)
    op = _modal_on(obj, mode="FIT", straight_sides="NONE")
    op._modal(bpy.context, _KeyPress("G"))
    _click_align(op, obj, (2, 3))
    assert op.shape_align == "PICKED" and op.align_edges != ""
    assert op._modal(bpy.context, _KeyPress("ESC")) == {"RUNNING_MODAL"} and not op._align_picking
    assert op._modal(bpy.context, _KeyPress("ESC")) == {"CANCELLED"}
    assert _uv_state(obj) == before and op.shape_align == "AUTO" and op.align_edges == ""


def test_confirm_after_align_picks_equals_execute():
    def made(confirm):
        obj = _shape_strip()
        if confirm:
            op = _modal_on(obj, mode="FIT", straight_sides="NONE")
            _click_align(op, obj, (4, 5))
            _click_align(op, obj, (10, 11))
            op._modal(bpy.context, _KeyPress("V"))
            assert op._modal(bpy.context, _KeyPress("RET")) == {"FINISHED"}
            return _uv_state(obj), op.shape_align, list(_edges(op.align_edges).values())   # kept for redo
        stand = _OperatorStandIn(mode="FIT", straight_sides="NONE", shape_align="PICKED",
                                 align_edges=_dump(obj, (4, 5), (10, 11)))
        assert stand.execute(bpy.context) == {"FINISHED"}
        return _uv_state(obj), stand.shape_align, list(_edges(stand.align_edges).values())

    assert made(True) == made(False)
    obj = _shape_strip()
    edges = _dump(obj, (4, 5), (10, 11))
    assert bpy.ops.iops.mesh_uv_stripe(**{**OLD_DEFAULTS, "mode": "FIT", "straight_sides": "NONE", "shape_align": "PICKED",
                                        "align_edges": edges}) == {"FINISHED"}
    assert _along_v(obj, (4, 5)) and _along_v(obj, (10, 11))
    for align in ("LONGEST", "SHORTEST"):                  # the modal's G and the property give the same UVs
        obj = _shape_strip()
        op = _modal_on(obj, mode="FIT", straight_sides="NONE")
        while op.shape_align != align:
            op._modal(bpy.context, _KeyPress("G"))
        assert op._modal(bpy.context, _KeyPress("SPACE")) == {"FINISHED"}
        confirmed = _uv_state(obj)
        obj = _shape_strip()
        assert _OperatorStandIn(mode="FIT", straight_sides="NONE", shape_align=align).execute(bpy.context) == {"FINISHED"}
        assert _uv_state(obj) == confirmed, align


def test_align_row_shows_only_where_a_piece_is_unfolded_at_its_real_shape():
    op = _OperatorStandIn()
    op._build_overlays(None)
    params = {p.name: p for section in op._hud.param_sections for p in section.params}
    assert not params["Align (G)"].is_visible()
    assert not any(name.startswith(("Pick Align", "Pick Cut")) for name in params)     # the header says it
    op.straight_sides = "NONE"
    assert params["Align (G)"].is_visible() and params["Align (G)"].value_text() == "Auto"
    op.shape_align = "SHORTEST"
    assert params["Align (G)"].value_text() == "Shortest Edge"
    op.straight_sides = "BOTH"
    assert not params["Align (G)"].is_visible()
    obj = _grid(4, 1)                                       # a rectangle: laid out straight, nothing unfolded
    _edit(obj)
    op = _modal_on(obj, mode="FIT")
    assert op._result.unfolded == 0 and "Align (G)" not in _shown(op)
    op._modal(bpy.context, _KeyPress("ESC"))
    obj = _grid(4, 1)                                       # both long sides clicked free: unfolded at its real shape
    _edit(obj)
    op = _modal_on(obj, mode="FIT")
    op._click_side(bpy.context, obj, 0, "near")
    op._click_side(bpy.context, obj, 0, "far")
    assert op._result.unfolded == 1 and "Align (G)" in _shown(op)
    op._modal(bpy.context, _KeyPress("ESC"))


def test_other_layouts_do_not_depend_on_align():
    for ends in ("SLANTED", "BOTH", "LONGER"):
        states = []
        for align in ("AUTO", "LONGEST", "SHORTEST", "PICKED"):
            obj = _shape_strip()
            edges = _dump(obj, (2, 3), (6, 8)) if align == "PICKED" else ""
            stand = _OperatorStandIn(mode="FIT", straight_sides="BOTH", ends=ends, shape_align=align, align_edges=edges)
            assert stand.execute(bpy.context) == {"FINISHED"}
            states.append(_uv_state(obj))
        assert all(state == states[0] for state in states), ends


def test_align_is_no_shared_setting():
    from InteractionOps.operators.uv_stripe_bridge import StripeSettings
    rna = bpy.ops.iops.mesh_uv_stripe.get_rna_type().properties
    assert rna["align_edges"].is_hidden and rna["align_edges"].is_skip_save
    assert not rna["shape_align"].is_skip_save and rna["shape_align"].default == "AUTO"
    assert [item.identifier for item in rna["shape_align"].enum_items] == ["AUTO", "LONGEST", "SHORTEST", "PICKED"]
    assert [item.name for item in rna["shape_align"].enum_items] == [
        "Auto", "Longest Edge", "Shortest Edge", "Picked Edge"]
    for name in ("shape_align", "align_edges"):
        assert name not in StripeSettings.__dataclass_fields__


# --- sides: LMB on a side makes it straight or free; Straight Sides, Ends and Balance -------------------

def _vertex_vs(obj, index):
    bm = bmesh.from_edit_mesh(obj.data)
    layer = bm.loops.layers.uv.active
    bm.verts.ensure_lookup_table()
    return {round(lp[layer].uv.y, 6) for lp in bm.verts[index].link_loops if lp.face.select}


def _taper_strip(faces=3, taper=0.1):
    """A strip of ``faces`` quads whose far rail closes in by ``taper`` per face: the defaults lay it out with both
    long sides straight. Vertices 0 .. ``faces`` on the near rail, ``faces`` + 1 .. 2 * ``faces`` + 1 on the far one."""
    row = faces + 1
    points = [(float(x), 0.0, 0.0) for x in range(row)] + [(float(x), 1.0 - taper * x, 0.0) for x in range(row)]
    obj = _object(points, [(i, i + 1, i + row + 1, i + row) for i in range(faces)])
    _edit(obj)
    return obj


def _sheared_strip(faces=3, shear=0.2):
    """A strip of ``faces`` quads sheared by ``shear``: both ends slanted, in the defaults' layout as in the faces."""
    row = faces + 1
    points = [(float(x), 0.0, 0.0) for x in range(row)] + [(float(x) + shear, 1.0, 0.0) for x in range(row)]
    obj = _object(points, [(i, i + 1, i + row + 1, i + row) for i in range(faces)])
    _edit(obj)
    return obj


def _side(op, obj, piece, name):
    return op._result.sides[(obj.name, piece, name)]


def test_click_on_a_long_side_makes_it_free_and_the_layout_follows():
    import json
    obj = _taper_strip()
    op = _modal_on(obj, mode="FIT")
    near, far = _side(op, obj, 0, "near"), _side(op, obj, 0, "far")
    assert near.straight and far.straight
    laid = _uv_state(obj)
    assert len({v for i in range(4) for v in _vertex_vs(obj, i)}) == 1       # both rails on one v each
    assert len({v for i in range(4, 8) for v in _vertex_vs(obj, i)}) == 1
    assert op._click_side(bpy.context, obj, 0, "near") is False
    near, far = _side(op, obj, 0, "near"), _side(op, obj, 0, "far")
    assert not near.straight and far.straight
    assert len({v for i in range(4) for v in _vertex_vs(obj, i)}) == 4       # the near rail follows its faces
    assert len({v for i in range(4, 8) for v in _vertex_vs(obj, i)}) == 1    # the far rail is still straight
    assert json.loads(op.side_picks) == {
        obj.name: [[near.faces[0], near.edges[0], False], [far.faces[0], far.edges[0], True]]}   # both long sides
    assert op._click_side(bpy.context, obj, 0, "near") is True
    assert json.loads(op.side_picks) == {
        obj.name: [[near.faces[0], near.edges[0], True], [far.faces[0], far.edges[0], True]]}
    assert _side(op, obj, 0, "near").straight and _uv_state(obj) == laid
    op._finish(bpy.context)


def test_clicking_an_end_of_a_one_face_wide_strip_stands_it_upright():
    obj = _sheared_strip()
    op = _modal_on(obj, mode="FIT")
    assert not _side(op, obj, 0, "end0").straight and not _side(op, obj, 0, "end1").straight
    assert _vertex_us(obj, 3) != _vertex_us(obj, 7) and _vertex_us(obj, 0) != _vertex_us(obj, 4)   # both slanted
    slanted = _uv_state(obj)
    assert op._click_side(bpy.context, obj, 0, "end1") is True
    assert _side(op, obj, 0, "end1").straight and not _side(op, obj, 0, "end0").straight
    assert _vertex_us(obj, 3) == _vertex_us(obj, 7) == {1.0}                 # the end's cross edge is vertical
    assert _vertex_us(obj, 0) != _vertex_us(obj, 4)                           # the other end keeps its slant
    assert _side(op, obj, 0, "near").straight and _side(op, obj, 0, "far").straight
    assert op._click_side(bpy.context, obj, 0, "end1") is False               # clicked again: slanted again
    assert _uv_state(obj) == slanted
    op._finish(bpy.context)


def test_side_picks_are_kept_for_redo_and_a_fresh_run_starts_from_the_defaults():
    obj = _taper_strip()
    op = _modal_on(obj, mode="FIT")
    defaults = _uv_state(obj)
    op._click_side(bpy.context, obj, 0, "near")
    clicked = _uv_state(obj)
    assert clicked != defaults
    assert op._modal(bpy.context, _KeyPress("RET")) == {"FINISHED"}
    assert _uv_state(obj) == clicked
    kept = op.side_picks
    assert kept
    _set_uvs(obj, lambda co: co.xy * 0.37)
    stand = _OperatorStandIn(mode="FIT", side_picks=kept)
    assert stand.execute(bpy.context) == {"FINISHED"}
    assert _uv_state(obj) == clicked                                          # the confirmed picks, laid out again
    _set_uvs(obj, lambda co: co.xy * 0.37)
    assert _run(mode="FIT", side_picks=kept) == {"FINISHED"}                  # and through the operator itself
    assert _uv_state(obj) == clicked
    _set_uvs(obj, lambda co: co.xy * 0.37)
    assert _OperatorStandIn(mode="FIT").execute(bpy.context) == {"FINISHED"}
    assert _uv_state(obj) == defaults                                         # a fresh run starts without them
    _set_uvs(obj, lambda co: co.xy * 0.37)
    assert _run(mode="FIT") == {"FINISHED"} and _uv_state(obj) == defaults


def test_lmb_off_a_side_changes_nothing_and_only_enter_confirms():
    # A real cursor cannot hover headless: the side lookup is stood in for, the event handling is the operator's.
    obj = _taper_strip()
    op = _modal_on(obj, mode="FIT")
    laid = _uv_state(obj)
    for _ in range(2):
        assert op._modal(bpy.context, _KeyPress("LEFTMOUSE")) == {"RUNNING_MODAL"}     # no side near: not the confirm
    assert _uv_state(obj) == laid and op.side_picks == "" and op._side_hover is None
    op._hover_side = lambda _context, _event: (obj, 0, "near")
    assert op._modal(bpy.context, _KeyPress("LEFTMOUSE")) == {"RUNNING_MODAL"}
    assert op.side_picks != "" and not _side(op, obj, 0, "near").straight and _uv_state(obj) != laid
    assert op._side_hover == (obj, 0, "near")                                           # kept for the preview
    clicked = _uv_state(obj)
    op._hover_side = lambda _context, _event: None
    assert op._modal(bpy.context, _KeyPress("LEFTMOUSE")) == {"RUNNING_MODAL"} and _uv_state(obj) == clicked
    assert op._modal(bpy.context, _KeyPress("RET")) == {"FINISHED"} and _uv_state(obj) == clicked
    for key in ("NUMPAD_ENTER", "SPACE"):
        obj = _taper_strip()
        op = _modal_on(obj, mode="FIT")
        assert op._modal(bpy.context, _KeyPress(key)) == {"FINISHED"}, key


def test_e_and_a_keep_the_clicked_sides():
    obj = _taper_strip()
    op = _modal_on(obj, mode="FIT")
    op._click_side(bpy.context, obj, 0, "near")
    picks = op.side_picks
    for key in ("E", "E", "E", "E", "A", "A", "A", "A"):                      # a full round of each
        assert op._modal(bpy.context, _KeyPress(key)) == {"RUNNING_MODAL"}
        assert op.side_picks == picks, key
        assert not _side(op, obj, 0, "near").straight, (key, op.straight_sides, op.ends)    # still free
        assert _side(op, obj, 0, "far").straight, (key, op.straight_sides, op.ends)
        assert len({v for i in range(4) for v in _vertex_vs(obj, i)}) == 4
    assert (op.straight_sides, op.ends) == ("BOTH", "SLANTED")
    op._finish(bpy.context)


def test_esc_after_clicks_restores_the_side_picks_and_the_uvs():
    obj = _taper_strip()
    before = _uv_state(obj)
    op = _modal_on(obj, mode="FIT")
    op._click_side(bpy.context, obj, 0, "near")
    op._modal(bpy.context, _KeyPress("E"))
    assert op.side_picks != "" and _uv_state(obj) != before
    assert op._modal(bpy.context, _KeyPress("ESC")) == {"CANCELLED"}
    assert op.side_picks == "" and op.straight_sides == "BOTH" and _uv_state(obj) == before
    # picks the run started with come back too
    op = _modal_on(obj, mode="FIT")
    op._click_side(bpy.context, obj, 0, "near")
    kept = op.side_picks
    assert op._modal(bpy.context, _KeyPress("RET")) == {"FINISHED"}
    _set_uvs(obj, lambda co: co.xy * 0.37)
    before = _uv_state(obj)
    op = _modal_on(obj, mode="FIT", side_picks=kept)
    op._click_side(bpy.context, obj, 0, "far")
    assert op.side_picks != kept
    assert op._modal(bpy.context, _KeyPress("RIGHTMOUSE")) == {"CANCELLED"}
    assert op.side_picks == kept and _uv_state(obj) == before


def test_hud_rows_follow_the_state():
    obj = _polyline([0, 22, 0, 38])
    _edit(obj)
    op = _modal_on(obj, mode="FIT")
    assert _shown(op) == ALWAYS_ROWS                                          # no Align, Manual Cuts, Doubled Vertices
    for _ in range(3):
        op._modal(bpy.context, _KeyPress("E"))                                # Both, Longer, Shorter, None
    assert op.straight_sides == "NONE" and _shown(op) == ALWAYS_ROWS | {"Align (G)"}
    op._modal(bpy.context, _KeyPress("E"))
    assert op.straight_sides == "BOTH" and _shown(op) == ALWAYS_ROWS
    _click(op, obj, (2, 3))
    assert _shown(op) == ALWAYS_ROWS | {"Manual Cuts"}
    params = {p.name: p for section in op._hud.param_sections for p in section.params}
    assert params["Manual Cuts"].value_text() == "1"
    op._modal(bpy.context, _KeyPress("ESC"))
    assert op._modal(bpy.context, _KeyPress("ESC")) == {"CANCELLED"}
    obj = _grid(4, 1)                                                         # both long sides clicked free
    _edit(obj)
    op = _modal_on(obj, mode="FIT")
    assert _shown(op) == ALWAYS_ROWS
    op._click_side(bpy.context, obj, 0, "near")
    assert _shown(op) == ALWAYS_ROWS                                          # one side free: the other is straight
    op._click_side(bpy.context, obj, 0, "far")
    assert _shown(op) == ALWAYS_ROWS | {"Align (G)"}
    op._modal(bpy.context, _KeyPress("ESC"))
    obj = _double_object()
    op = _modal_on(obj, mode="FIT")
    assert _shown(op) == ALWAYS_ROWS | {"Doubled Vertices"}
    op._modal(bpy.context, _KeyPress("ESC"))


def test_the_pick_modes_show_their_line_in_the_hud_header():
    from types import SimpleNamespace
    obj = _polyline([0, 22, 0, 38])
    _edit(obj)
    op = _modal_on(obj, mode="FIT")
    op._hud.draw = op._help.draw = lambda *_args: None                        # no GPU in the background
    context = SimpleNamespace(region_data=object())
    op._draw_callback(context)
    assert op._hud._header_lines == ["3 strip(s)"]
    op._modal(bpy.context, _KeyPress("C"))
    op._draw_callback(context)
    assert op._hud._header_lines == ["Picking cut edges · C to stop", "3 strip(s)"]
    op._modal(bpy.context, _KeyPress("V"))
    op._draw_callback(context)
    assert op._hud._header_lines == ["Picking the align edge · V to stop", "3 strip(s)"]
    op._modal(bpy.context, _KeyPress("ESC"))
    op._draw_callback(context)
    assert op._hud._header_lines == ["3 strip(s)"]
    op._modal(bpy.context, _KeyPress("ESC"))


def test_help_starts_collapsed():
    op = _OperatorStandIn()
    op._build_overlays(None)
    assert op._help.expanded is False
    obj = _grid(4, 1)
    _edit(obj)
    op = _modal_on(obj, mode="FIT")
    assert op._help.expanded is False
    op._modal(bpy.context, _KeyPress("ESC"))


def test_shape_settings_are_shared_and_side_picks_are_not():
    from InteractionOps.operators.uv_stripe_bridge import StripeSettings
    rna = bpy.ops.iops.mesh_uv_stripe.get_rna_type().properties
    for name in ("straight_sides", "ends", "balance", "stretch_limit"):
        assert name in StripeSettings.__dataclass_fields__, name
    assert "side_picks" not in StripeSettings.__dataclass_fields__
    assert rna["side_picks"].is_hidden and rna["side_picks"].is_skip_save
    assert not rna["straight_sides"].is_skip_save and not rna["ends"].is_skip_save and not rna["balance"].is_skip_save
    assert (rna["straight_sides"].default, rna["ends"].default, rna["balance"].default) == (
        "BOTH", "SLANTED", "EVEN_TEXEL")
    assert round(rna["stretch_limit"].default, 6) == 1.25
    settings = StripeSettings.from_operator(_OperatorStandIn(straight_sides="LONGER", ends="SHORTER",
                                                             balance="LEAST_STRETCH"))
    assert (settings.straight_sides, settings.ends, settings.balance) == ("LONGER", "SHORTER", "LEAST_STRETCH")


def _bent_patch(cols=6, rows=3):
    """A ``cols`` x ``rows`` patch of quads bent over an arc (a flat annulus sector: its rows differ in length)."""
    points = [((2.0 + 0.5 * y) * math.cos(0.2 * x), (2.0 + 0.5 * y) * math.sin(0.2 * x), 0.0)
              for y in range(rows + 1) for x in range(cols + 1)]
    row = cols + 1
    faces = [(y * row + x, y * row + x + 1, (y + 1) * row + x + 1, (y + 1) * row + x)
             for y in range(rows) for x in range(cols)]
    obj = _object(points, faces)
    _edit(obj)
    return obj


def _stretched_count(obj):
    from InteractionOps.operators import uv_stripe_bridge
    bm = bmesh.from_edit_mesh(obj.data)
    return len(uv_stripe_bridge.stretched_faces(bm, _selected_faces(obj), obj.matrix_world))


def test_every_shape_combination_finishes_on_the_bent_ngons_and_a_wide_patch():
    import itertools
    for sides, ends, balance in itertools.product(("BOTH", "LONGER", "SHORTER", "NONE"),
                                                  ("SLANTED", "BOTH", "LONGER", "SHORTER"),
                                                  ("EVEN_TEXEL", "LEAST_STRETCH")):
        shape = {"straight_sides": sides, "ends": ends, "balance": balance}
        obj = _ngon_object(exact_ngon_verts())
        _edit(obj)
        assert _run(mode="FIT", **shape) == {"FINISHED"}, shape
        assert all(a > 0 for a in _face_areas(obj)), shape
        # the ends stand upright on the n-gons only by stretching two faces; nothing else stretches them
        assert _stretched_count(obj) == (0 if ends == "SLANTED" or sides == "NONE" else 2), shape
        obj = _bent_patch()
        assert _run(mode="FIT", **shape) == {"FINISHED"}, shape
        assert all(a > 0 for a in _face_areas(obj)), shape
        count = _stretched_count(obj)
        if sides == "NONE" or balance == "LEAST_STRETCH":
            assert count == 0, shape                       # the real shape, or the least stretch the patch allows
        if (sides, ends, balance) == ("BOTH", "SLANTED", "EVEN_TEXEL"):
            assert count == 6, shape                       # the defaults: even texel density, some stretch left


def test_old_last_used_values_of_the_removed_properties_are_ignored():
    from InteractionOps.operators.uv_stripe_bridge import StripeSettings
    obj = _grid(4, 1)
    _edit(obj)
    assert _run(mode="FIT") == {"FINISHED"}
    props = bpy.context.window_manager.operator_properties_last("iops.mesh_uv_stripe")
    baseline = StripeSettings.from_last(bpy.context)
    written = []
    try:
        for name, value in (("layout", 1), ("split_angle", 0.3), ("split_at_bends", True)):
            props[name] = value
            written.append(name)
        assert written == ["layout", "split_angle", "split_at_bends"]
        assert StripeSettings.from_last(bpy.context) == baseline
        obj = _grid(4, 1)
        _edit(obj)
        assert bpy.ops.iops.mesh_uv_stripe() == {"FINISHED"}                  # the bare call, with the stale values
        obj = _grid(4, 1)
        _edit(obj)
        assert _run(mode="FIT") == {"FINISHED"}
        for co, uv in _corners(obj):
            assert _close(uv.x, co.x / 4.0) and _close(uv.y, co.y / 4.0), (co, uv)
        assert StripeSettings.from_last(bpy.context) == baseline
    finally:
        for name in written:
            try:
                del props[name]
            except (KeyError, TypeError):
                pass


def _double_click(key="LEFTMOUSE"):
    event = _KeyPress(key)
    event.value = "DOUBLE_CLICK"
    return event


def test_double_click_on_a_side_toggles_it_like_a_press():
    obj = _taper_strip()
    op = _modal_on(obj, mode="FIT")
    laid = _uv_state(obj)
    op._hover_side = lambda _context, _event: (obj, 0, "near")
    assert op._modal(bpy.context, _double_click()) == {"RUNNING_MODAL"}
    assert not _side(op, obj, 0, "near").straight and op.side_picks != ""
    pressed = _uv_state(obj)
    assert pressed != laid
    assert op._modal(bpy.context, _double_click()) == {"RUNNING_MODAL"}
    assert _side(op, obj, 0, "near").straight and _uv_state(obj) == laid
    op._hover_side = lambda _context, _event: None
    assert op._modal(bpy.context, _double_click()) == {"RUNNING_MODAL"}       # off a side: nothing, no confirm
    assert _uv_state(obj) == laid
    assert op._modal(bpy.context, _KeyPress("RET")) == {"FINISHED"}
    # in the cut pick mode a double click picks like a press
    obj = _grid(4, 1)
    _edit(obj)
    op = _modal_on(obj, mode="FIT")
    index = _edge_index(obj, (2, 7))
    op._hover_break = lambda _context, _event: (obj, index)
    assert op._modal(bpy.context, _KeyPress("C")) == {"RUNNING_MODAL"} and op._picking
    assert op._modal(bpy.context, _double_click()) == {"RUNNING_MODAL"} and op._picking
    assert _uv_islands(obj) == 2 and _edges(op.manual_cuts) == {obj.name: [index]}
    op._finish(bpy.context)


def test_a_rectangular_frame_is_four_islands_of_one_face():
    outer = [(0.0, 0.0), (4.0, 0.0), (4.0, 2.0), (0.0, 2.0)]
    inner = [(0.2, 0.2), (3.8, 0.2), (3.8, 1.8), (0.2, 1.8)]
    obj = _object([(x, y, 0.0) for x, y in outer + inner], [(k, (k + 1) % 4, 4 + (k + 1) % 4, 4 + k) for k in range(4)])
    _edit(obj)
    assert _run(mode="FIT") == {"FINISHED"}
    assert _uv_islands(obj) == 4
    assert _seams(obj) & _inner_edges(obj) == {(k, 4 + k) for k in range(4)}      # every corner edge
    bm = bmesh.from_edit_mesh(obj.data)
    layer = bm.loops.layers.uv.active
    sizes = []
    for f in bm.faces:
        pts = [lp[layer].uv for lp in f.loops]
        sizes.append((max(p.x for p in pts) - min(p.x for p in pts), max(p.y for p in pts) - min(p.y for p in pts)))
    assert all(a > 0 for a in _face_areas(obj))
    assert _close(sizes[0][0], sizes[2][0]) and _close(sizes[0][1], sizes[2][1])   # the two long pieces
    assert _close(sizes[1][0], sizes[3][0]) and _close(sizes[1][1], sizes[3][1])   # the two short ones
    assert sizes[0][0] > sizes[1][0]


class _HoverContext:
    """``bpy.context`` with a region and view data (stood in for) and the edit objects, so ``_hover_side`` runs."""

    def __init__(self, obj):
        from types import SimpleNamespace
        self.region = self.region_data = object()
        self.preferences = SimpleNamespace(system=SimpleNamespace(ui_scale=1.0))   # 0 in a background Blender
        self.objects_in_mode_unique_data = [obj]

    def __getattr__(self, name):
        return getattr(bpy.context, name)


def test_hover_side_prefers_the_piece_under_the_cursor_and_skips_hidden_edges():
    # No region headless: the raycast and the on-screen distances are stood in for, the lookup is the operator's.
    from InteractionOps.utils import picking
    obj = _polyline([0, 22])
    _edit(obj)
    op = _modal_on(obj, mode="FIT")
    result = op._result
    tear = _edge_index(obj, (4, 5))
    entries = result.side_edges[obj.name][tear]
    assert sorted(piece for piece, _name in entries) == [0, 1]                 # the tear ends both pieces
    face_of = {n: next(f for f, piece in result.piece_faces[obj.name].items() if piece == n) for n in (0, 1)}
    near = {}                                                                  # on-screen distance by edge index
    hit = {"on": False, "face": 0}
    real_ray, real_closest = picking.raycast_edit_meshes, picking.closest_edge_screen

    def raycast(*_args, **_kwargs):
        return (hit["on"], None, None, hit["face"], obj)

    def closest(_context, edges, _matrix, _coord):
        if not edges:
            return None, 1e9
        if len(edges) > 1:                       # the face under the cursor: none of its edges is near
            return 0, 1e9
        k = min(range(len(edges)), key=lambda i: near.get(edges[i].index, 1e9))
        return k, near.get(edges[k].index, 1e9)

    picking.raycast_edit_meshes, picking.closest_edge_screen = raycast, closest
    try:
        context, event = _HoverContext(obj), _KeyPress("MOUSEMOVE")
        op._edge_visible = lambda *_args: True
        near[tear] = 1.0
        assert op._hover_side(context, event)[1] == min(piece for piece, _name in entries)   # nothing under it
        for under in (0, 1):                                                   # a face of piece 0 / piece 1 under it
            hit.update(on=True, face=face_of[under])
            found = op._hover_side(context, event)       # the tear edge is the only one near: the face's piece wins
            assert found is not None and found[1] == under, (under, found)
        # a nearer edge hidden behind geometry is skipped for a farther visible one
        hit["on"] = False
        near.clear()
        hidden, visible = _edge_index(obj, (0, 2)), _edge_index(obj, (2, 4))
        near.update({hidden: 1.0, visible: 5.0})
        assert op._hover_side(context, event)[2] == result.side_edges[obj.name][hidden][0][1]
        op._edge_visible = lambda _context, _region, _rv3d, _objects, _obj, edge, _coord: edge.index != hidden
        found = op._hover_side(context, event)
        assert found == (obj, *result.side_edges[obj.name][visible][0])
        near[visible] = 1e9                                                    # beyond the pick radius: nothing
        assert op._hover_side(context, event) is None
    finally:
        picking.raycast_edit_meshes, picking.closest_edge_screen = real_ray, real_closest
    op._finish(bpy.context)


TESTS = [
    test_fit_straight_strip,
    test_in_place_keeps_centre_and_density,
    test_in_place_on_a_scaled_object_keeps_density,
    test_two_strips_stack_in_fit_with_one_density,
    test_mark_seams_match_the_pieces,
    test_split_at_seams_tears_the_strip_and_keeps_its_seam,
    test_ring_with_one_seam_is_cut_there,
    test_auto_tears_a_sharp_bend_and_keeps_a_gentle_one_whole,
    test_ngon_strip_splits_into_stretch_free_pieces,
    test_ngon_strip_with_the_captured_coordinates_is_split_too,
    test_a_requested_split_that_cannot_be_made_is_reported,
    test_ends_slanted_keeps_the_true_size_and_ends_both_stands_every_cross_edge_vertical,
    test_auto_lays_a_tapered_piece_out_by_the_stretch_limit,
    test_auto_lays_a_wide_arc_out_as_one_straight_island,
    test_modal_wheel_changes_the_stretch_limit_under_auto,
    test_vertical_orientation_turns_the_strip,
    test_triangulated_strip_is_its_quads_rectangle,
    test_scaled_object_follows_world_size,
    test_rejected_island_leaves_the_other,
    test_nothing_selected_cancels,
    test_only_rejected_cancels,
    test_mesh_without_uv_gets_one,
    test_modal_keys_toggle_their_options_and_the_uvs_follow,
    test_modal_wheel_changes_the_stretch_limit_under_any_straight_sides,
    test_modal_cancel_restores_uvs_seams_and_options,
    test_modal_cancel_removes_a_uv_layer_it_made,
    test_modal_confirm_equals_execute,
    test_modal_nothing_to_lay_out_cancels_and_restores,
    test_modal_hud_and_help_list_every_key,
    test_modal_old_letters_are_free,
    test_doubled_vertices_are_reported,
    test_merge_doubles_merges_exactly_the_double,
    test_modal_merge_doubles,
    test_operator_defaults,
    test_default_active_fit_matches_the_height_and_leaves_a_clean_mesh_alone,
    test_active_fit_stretches_no_face,
    test_seams_split_a_strip_whose_sides_fan_round_a_corner,
    test_stretched_faces_are_measured_in_world_space,
    test_ends_both_on_a_bent_strip_reports_stretched_faces,
    test_default_offset_runs_along_the_strip_in_both_orientations,
    test_true_shape_follows_a_tapering_strip,
    test_active_fits_the_other_strip_onto_the_reference,
    test_active_follows_the_orientation,
    test_active_puts_the_other_pieces_of_a_torn_strip_on_the_active_piece,
    test_active_without_an_active_face_lays_out_in_place_and_says_so,
    test_random_offset_moves_the_other_strip_along_u_only,
    test_modal_fit_to_active_and_random_offset_keys,
    test_cup_break_opens_a_ring_as_one_piece_and_auto_tears_a_flat_ring_at_every_bend,
    test_cup_break_all_quads_is_rectangles_under_the_defaults,
    test_cup_break_replaces_an_old_seam,
    test_cup_break_with_a_triangle_follows_the_ends,
    test_cup_break_on_an_open_strip_is_ignored,
    test_cup_break_is_taken_before_doubles_are_merged,
    test_c_enters_and_leaves_picking,
    test_set_break_relays_out_and_keeps_picking,
    test_lmb_in_picking_sets_the_hovered_break,
    test_second_break_on_the_same_ring_replaces_the_first,
    test_breaks_on_two_rings_are_both_kept,
    test_break_survives_option_changes,
    test_r_changes_seed_and_c_does_not,
    test_cancel_after_break_restores_uvs_and_seams,
    test_confirm_after_break_equals_execute,
    test_cup_breaks_is_no_shared_setting,
    test_manual_cut_tears_an_open_strip_and_a_second_click_mends_it,
    test_suppressing_a_bend_tear_joins_the_pieces,
    test_a_seam_tear_is_not_changed_by_a_click,
    test_a_manual_cut_tears_a_broken_ring,
    test_manual_cuts_tear_the_parts_of_an_island_split_at_its_seams,
    test_cancel_restores_the_cut_properties,
    test_confirm_after_cuts_equals_execute,
    test_confirm_after_a_skipped_bend_tear_equals_execute,
    test_malformed_cut_properties_read_as_none,
    test_invoke_draws_the_lines_in_the_scene_and_the_hud_on_top,
    test_invoke_without_interactive_lays_out_at_once,
    test_invoke_with_interactive_starts_the_modal,
    test_interactive_and_more_options_properties,
    test_tab_toggles_more_options_and_the_hud_rows,
    test_keys_of_hidden_rows_work_while_collapsed,
    test_interactive_operator_registers_and_starts_the_modal,
    test_the_stepped_strip_with_the_users_defaults,
    test_g_cycles_the_align_values,
    test_v_and_lmb_store_the_align_edge_and_keep_picking,
    test_the_two_pick_modes_are_exclusive,
    test_cancel_restores_align_and_its_edges,
    test_confirm_after_align_picks_equals_execute,
    test_align_row_shows_only_where_a_piece_is_unfolded_at_its_real_shape,
    test_other_layouts_do_not_depend_on_align,
    test_align_is_no_shared_setting,
    test_click_on_a_long_side_makes_it_free_and_the_layout_follows,
    test_clicking_an_end_of_a_one_face_wide_strip_stands_it_upright,
    test_side_picks_are_kept_for_redo_and_a_fresh_run_starts_from_the_defaults,
    test_lmb_off_a_side_changes_nothing_and_only_enter_confirms,
    test_e_and_a_keep_the_clicked_sides,
    test_esc_after_clicks_restores_the_side_picks_and_the_uvs,
    test_hud_rows_follow_the_state,
    test_the_pick_modes_show_their_line_in_the_hud_header,
    test_help_starts_collapsed,
    test_shape_settings_are_shared_and_side_picks_are_not,
    test_every_shape_combination_finishes_on_the_bent_ngons_and_a_wide_patch,
    test_old_last_used_values_of_the_removed_properties_are_ignored,
    test_double_click_on_a_side_toggles_it_like_a_press,
    test_a_rectangular_frame_is_four_islands_of_one_face,
    test_hover_side_prefers_the_piece_under_the_cursor_and_skips_hidden_edges,
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
