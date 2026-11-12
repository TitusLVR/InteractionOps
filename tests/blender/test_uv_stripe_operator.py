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
from uv_stripe_fixtures import NGON_FACES, NGON_VERTS, exact_ngon_verts  # noqa: E402

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


def _run(**props):
    return bpy.ops.iops.mesh_uv_stripe(**props)


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


def test_split_at_bends_on_a_flat_bent_strip():
    obj = _polyline([0, 22, 0, 38])
    _edit(obj)
    assert _run(mode="FIT") == {"FINISHED"}                 # Split at Bends is on by default, at 15 degrees
    seams = _seams(obj)
    assert (4, 5) in seams and (8, 9) in seams
    assert (2, 3) not in seams and (6, 7) not in seams
    assert len(_vertex_us(obj, 4)) == 2 and len(_vertex_us(obj, 6)) == 1
    assert _run(mode="FIT", split_at_bends=False) == {"FINISHED"}
    assert len(_vertex_us(obj, 4)) == 1 and (4, 5) not in _seams(obj)


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
    stand = _OperatorStandIn()
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
    stand = _OperatorStandIn()
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
    stand = _OperatorStandIn()
    select_core.slice_strip = refuse
    try:
        assert stand.execute(bpy.context) == {"FINISHED"}
    finally:
        select_core.slice_strip = real
    assert "UV Stripe: not split (refused for the test)" in stand.reports, stand.reports
    assert len(_vertex_us(obj, 4)) == 1                      # laid out whole


def test_layouts():
    # No Stretch keeps the bent strip's pieces at their true size; Rectangles stands every cross edge vertical.
    obj = _polyline([0, 22, 0, 38])
    _edit(obj)
    assert _run(mode="FIT") == {"FINISHED"}
    ratios, errors = _uv_metrics(obj)
    assert max(ratios) / min(ratios) < 1 + 1e-6 and max(errors) < 1e-4
    assert _run(mode="FIT", layout="STRAIGHT", split_at_bends=False) == {"FINISHED"}
    for i in range(6):
        assert _vertex_us(obj, 2 * i) == _vertex_us(obj, 2 * i + 1), i
    assert _run(mode="FIT", layout="EVEN", split_at_bends=False) == {"FINISHED"}
    assert _vertex_us(obj, 8) != _vertex_us(obj, 9)


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
        self.mode, self.orientation, self.layout = "FIT", "HORIZONTAL", "TRUE"
        self.split_at_seams, self.split_at_bends, self.split_angle = False, True, math.radians(15)
        self.mark_seams = True
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
    op = _modal_on(obj)
    steps = [("R", "orientation", "VERTICAL"), ("M", "mode", "IN_PLACE"), ("S", "layout", "STRAIGHT"),
             ("S", "layout", "EVEN"), ("S", "layout", "TRUE"), ("M", "mode", "ACTIVE"), ("M", "mode", "FIT"),
             ("B", "split_at_bends", False), ("E", "split_at_seams", True), ("X", "mark_seams", False),
             ("R", "orientation", "HORIZONTAL")]
    for key, name, value in steps:
        before = _uv_state(obj)
        assert op._modal(bpy.context, _KeyPress(key)) == {"RUNNING_MODAL"}
        assert getattr(op, name) == value, (key, name, getattr(op, name))
        if key in "RB":
            assert _uv_state(obj)[0] != before[0], key          # the UVs follow at once
    assert len(_vertex_us(obj, 4)) == 1                        # Split at Bends off: one strip
    op._modal(bpy.context, _KeyPress("B"))
    assert len(_vertex_us(obj, 4)) == 2
    op._finish(bpy.context)


def test_modal_wheel_changes_the_bend_angle_while_splitting():
    obj = _polyline([0, 22, 0, 38])
    _edit(obj)
    op = _modal_on(obj)
    assert op._modal(bpy.context, _KeyPress("WHEELUPMOUSE")) == {"RUNNING_MODAL"}
    assert round(math.degrees(op.split_angle)) == 20
    op._modal(bpy.context, _KeyPress("WHEELUPMOUSE", ctrl=True))
    assert round(math.degrees(op.split_angle)) == 21
    assert len(_vertex_us(obj, 4)) == 2 and len(_vertex_us(obj, 8)) == 2      # 22 and 38 degrees still tear
    op._modal(bpy.context, _KeyPress("WHEELUPMOUSE", ctrl=True))
    op._modal(bpy.context, _KeyPress("WHEELUPMOUSE", ctrl=True))
    assert round(math.degrees(op.split_angle)) == 23 and len(_vertex_us(obj, 4)) == 1     # 22 no longer
    op._modal(bpy.context, _KeyPress("WHEELDOWNMOUSE"))
    assert round(math.degrees(op.split_angle)) == 18
    op._modal(bpy.context, _KeyPress("B"))
    assert op._modal(bpy.context, _KeyPress("WHEELUPMOUSE")) == {"PASS_THROUGH"}    # zooms the view instead
    assert round(math.degrees(op.split_angle)) == 18
    op._finish(bpy.context)


def test_modal_cancel_restores_uvs_seams_and_options():
    obj = _grid(6, 3, uv_size=10.0)
    _edit(obj, _middle)
    _set_seams(obj, {(0, 1), (10, 17)})
    before = _uv_state(obj)
    op = _modal_on(obj)
    assert _uv_state(obj) != before                            # laid out live
    for key in ("R", "M", "S", "E", "X", "B"):
        op._modal(bpy.context, _KeyPress(key))
    op._modal(bpy.context, _KeyPress("X"))
    assert op._modal(bpy.context, _KeyPress("ESC")) == {"CANCELLED"}
    assert _uv_state(obj) == before
    assert (op.mode, op.orientation, op.layout, op.split_at_seams, op.split_at_bends, op.mark_seams) == (
        "FIT", "HORIZONTAL", "TRUE", False, True, True)


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
            for key in ("R", "E", "WHEELUPMOUSE"):
                op._modal(bpy.context, _KeyPress(key))
            assert op._modal(bpy.context, _KeyPress("SPACE")) == {"FINISHED"}
            return _uv_state(obj), op.reports
        stand = _OperatorStandIn(orientation="VERTICAL", split_at_seams=True, split_angle=math.radians(20))
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


# --- Active mode -------------------------------------------------------------------

def _set_uvs(obj, fn):
    """Give every loop the UV ``fn(world position)``."""
    bm = bmesh.from_edit_mesh(obj.data)
    layer = bm.loops.layers.uv.active or bm.loops.layers.uv.new("UVMap")
    for f in bm.faces:
        for lp in f.loops:
            lp[layer].uv = fn(obj.matrix_world @ lp.vert.co)
    bmesh.update_edit_mesh(obj.data)


def _set_active(obj, center):
    """Make the face whose centre is ``center`` (x, y) the active face."""
    bm = bmesh.from_edit_mesh(obj.data)
    bm.faces.active = min(bm.faces, key=lambda f: (f.calc_center_median().xy - Vector(center)).length)
    bmesh.update_edit_mesh(obj.data)


def _loop_uvs(obj):
    bm = bmesh.from_edit_mesh(obj.data)
    layer = bm.loops.layers.uv.active
    return {(round(lp.vert.co.x, 4), round(lp.vert.co.y, 4), f.index): lp[layer].uv.copy()
            for f in bm.faces if f.select for lp in f.loops}


def test_active_keeps_the_active_face_and_continues_from_it():
    # UVs turned a quarter from the mesh and scaled by 0.1: (u, v) = (-y, x) / 10. The strip follows the active face.
    for rotate in (False, True):
        obj = _grid(4, 1)
        _edit(obj)
        uv_of = (lambda co: Vector((-co.y / 10.0, co.x / 10.0))) if rotate else (lambda co: co.xy / 10.0 + Vector((0.5, 0.5)))
        _set_uvs(obj, uv_of)
        _set_active(obj, (1.5, 0.5))
        assert _run(mode="ACTIVE", orientation="VERTICAL") == {"FINISHED"}     # orientation does not apply
        for co, uv in _corners(obj):
            assert (uv - uv_of(co)).length < 1e-5, (rotate, co, uv, uv_of(co))


def test_active_gives_every_piece_one_scale_and_turn_at_its_old_centre():
    obj = _polyline([0, 40])                               # torn at the bend: two pieces
    _edit(obj)
    _set_uvs(obj, lambda co: co.xy * 0.1)
    bm = bmesh.from_edit_mesh(obj.data)
    layer = bm.loops.layers.uv.active
    pieces = {"first": [f for f in bm.faces if f.index < 2], "last": [f for f in bm.faces if f.index == 2]}

    def bbox_centre(faces):
        us = [lp[layer].uv.x for f in faces for lp in f.loops]
        vs = [lp[layer].uv.y for f in faces for lp in f.loops]
        return Vector(((min(us) + max(us)) / 2.0, (min(vs) + max(vs)) / 2.0))

    old_centre = bbox_centre(pieces["last"])
    bm.faces.active = pieces["first"][0]
    bmesh.update_edit_mesh(obj.data)
    assert _run(mode="ACTIVE") == {"FINISHED"}
    bm = bmesh.from_edit_mesh(obj.data)
    layer = bm.loops.layers.uv.active
    ratios, errors = _uv_metrics(obj)
    assert all(abs(r - 0.1) < 1e-5 for r in ratios) and max(errors) < 1e-3, (ratios, errors)
    last = [f for f in bm.faces if f.index == 2]
    assert (bbox_centre(last) - old_centre).length < 1e-6
    bm.faces.ensure_lookup_table()
    first = bm.faces[0]
    for lp in first.loops:                                  # the active face stays on its old corners
        assert (lp[layer].uv - (obj.matrix_world @ lp.vert.co).xy * 0.1).length < 1e-5


def test_active_without_an_active_face_falls_back_to_in_place():
    obj = _grid(6, 3, uv_size=10.0)
    _edit(obj, _middle)
    bm = bmesh.from_edit_mesh(obj.data)
    bm.faces.active = None
    bmesh.update_edit_mesh(obj.data)
    stand = _OperatorStandIn(mode="ACTIVE")
    assert stand.execute(bpy.context) == {"FINISHED"}
    assert stand.reports == ["UV Stripe: Active needs an active face in the selection with UVs; laid out In Place",
                             "UV Stripe: 1 strip(s)"], stand.reports
    for co, uv in _corners(obj):                             # as In Place lays it out
        assert _close(uv.x, co.x / 10.0 + 0.5) and _close(uv.y, co.y / 10.0 + 0.5), (co, uv)


def test_modal_mode_cycles_and_active_anchors_to_the_original_uvs():
    obj = _grid(4, 1)
    _edit(obj)
    _set_uvs(obj, lambda co: Vector((-co.y / 10.0, co.x / 10.0)))
    _set_active(obj, (1.5, 0.5))
    before = _loop_uvs(obj)
    op = _modal_on(obj)
    assert op.mode == "FIT"
    op._modal(bpy.context, _KeyPress("M"))
    assert op.mode == "IN_PLACE"
    op._modal(bpy.context, _KeyPress("M"))
    assert op.mode == "ACTIVE"
    for key in ("S", "R", "S", "S"):                         # several layouts in between: still the snapshot's UVs
        op._modal(bpy.context, _KeyPress(key))
    after = _loop_uvs(obj)
    assert all((after[k] - before[k]).length < 1e-5 for k in before)
    op._modal(bpy.context, _KeyPress("M"))
    assert op.mode == "FIT"
    op._modal(bpy.context, _KeyPress("ESC"))


def test_modal_hud_and_help_list_every_key():
    op = _OperatorStandIn()
    op._build_overlays(None)
    params = [p for section in op._hud.param_sections for p in section.params]
    assert [p.name for p in params] == [
        "Orientation (R)", "Mode (M)", "Layout (S)", "Split at Seams (E)", "Split at Bends (B)",
        "Bend Angle (Wheel)", "Mark Seams (X)"]
    assert [p.value_text() for p in params] == ["Horizontal", "Fit 0–1", "No Stretch", "✗", "✓", "15°", "✓"]
    assert params[0].is_active()
    op.mode = "ACTIVE"                                      # the direction then comes from the active face
    assert params[1].value_text() == "Active" and not params[0].is_active()
    assert "orientation = from the active face (R)" in op._status_text()
    op.mode = "FIT"
    assert [(it.label, it.key) for it in op._help.sections[0].items] == [
        ("Orientation", "R"), ("Mode", "M"), ("Layout", "S"), ("Split at seams", "E"), ("Split at bends", "B"),
        ("Bend angle", "Wheel / Ctrl + Wheel"), ("Mark seams", "X"), ("Confirm", "LMB / Enter / Space"),
        ("Cancel", "Esc / RMB"), ("Help / Toggle HUD", "H")]
    assert "layout = no stretch (S)" in op._status_text()


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


TESTS = [
    test_fit_straight_strip,
    test_in_place_keeps_centre_and_density,
    test_in_place_on_a_scaled_object_keeps_density,
    test_two_strips_stack_in_fit_with_one_density,
    test_mark_seams_match_the_pieces,
    test_split_at_seams_tears_the_strip_and_keeps_its_seam,
    test_ring_with_one_seam_is_cut_there,
    test_split_at_bends_on_a_flat_bent_strip,
    test_ngon_strip_splits_into_stretch_free_pieces,
    test_ngon_strip_with_the_captured_coordinates_is_split_too,
    test_a_requested_split_that_cannot_be_made_is_reported,
    test_layouts,
    test_vertical_orientation_turns_the_strip,
    test_triangulated_strip_is_its_quads_rectangle,
    test_scaled_object_follows_world_size,
    test_rejected_island_leaves_the_other,
    test_nothing_selected_cancels,
    test_only_rejected_cancels,
    test_mesh_without_uv_gets_one,
    test_modal_keys_toggle_their_options_and_the_uvs_follow,
    test_modal_wheel_changes_the_bend_angle_while_splitting,
    test_modal_cancel_restores_uvs_seams_and_options,
    test_modal_cancel_removes_a_uv_layer_it_made,
    test_modal_confirm_equals_execute,
    test_modal_nothing_to_lay_out_cancels_and_restores,
    test_modal_hud_and_help_list_every_key,
    test_active_keeps_the_active_face_and_continues_from_it,
    test_active_gives_every_piece_one_scale_and_turn_at_its_old_centre,
    test_active_without_an_active_face_falls_back_to_in_place,
    test_modal_mode_cycles_and_active_anchors_to_the_original_uvs,
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
