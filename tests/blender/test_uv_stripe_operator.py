"""Headless tests of the UV Stripe operator (iops.mesh_uv_stripe) on real meshes in
Edit Mode. Run from the repo root via:

    blender --background --factory-startup --python-exit-code 1 --python tests/blender/test_uv_stripe_operator.py

Not collected by pytest (tests/conftest.py ignores tests/blender).
"""
import math
import os
import sys
import traceback
from types import SimpleNamespace

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


def _cap_parts(n=6, centre=(0.0, 0.0)):
    """A disc of ``n`` triangles round a centre vertex: no rule reads it as a strip and it has no corner to pick, so
    it is refused (never cut, never waiting for help)."""
    cx, cy = centre
    points = [(cx, cy, 0.0)] + [(cx + math.cos(2 * math.pi * i / n), cy + math.sin(2 * math.pi * i / n), 0.0)
                                for i in range(n)]
    return points, [(0, 1 + i, 1 + (i + 1) % n) for i in range(n)]


def _cap(n=6, uv_size=None):
    points, faces = _cap_parts(n)
    return _object(points, faces, uv_size=uv_size)


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


def _strip_boxes(obj):
    """(u0, v0, u1, v1) of the low and the high strip of the two-strip grid."""
    out = []
    for only in (lambda c: c.y < 1.0, lambda c: c.y > 3.0):
        uvs = [uv for _c, uv in _corners(obj, only)]
        out.append((min(uv.x for uv in uvs), min(uv.y for uv in uvs), max(uv.x for uv in uvs),
                    max(uv.y for uv in uvs)))
    return out


def test_stack_centres_every_strip_on_the_middle_at_the_fit_size():
    keep = {(x, 0) for x in range(4)} | {(x, 3) for x in range(2)}
    boxes = {}
    for mode in ("FIT", "STACK"):
        obj = _grid(4, 4, keep=keep)
        _edit(obj)
        assert _run(mode=mode) == {"FINISHED"}
        boxes[mode] = _strip_boxes(obj)
        bpy.ops.object.mode_set(mode="OBJECT")
    for fit, stack in zip(boxes["FIT"], boxes["STACK"]):
        assert _close(fit[2] - fit[0], stack[2] - stack[0]) and _close(fit[3] - fit[1], stack[3] - stack[1])
        assert _close((stack[0] + stack[2]) / 2, 0.5) and _close((stack[1] + stack[3]) / 2, 0.5), stack
    obj = _grid(4, 4, keep=keep)                       # Random Offset after stacking: along the strip, U only
    _edit(obj)
    assert _run(mode="STACK", offset_axis="ALONG", offset_limit=0.25, offset_seed=3) == {"FINISHED"}
    shifted = _strip_boxes(obj)
    bpy.ops.object.mode_set(mode="OBJECT")
    assert all(_close((b[1] + b[3]) / 2, 0.5) for b in shifted)
    assert any(not _close((b[0] + b[2]) / 2, 0.5) for b in shifted), shifted


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
    # Auto tears only where no whole layout stays within the Stretch Limit: the 38 degree bend goes, the 22 degree
    # bend (a whole layout stretches 1.22 < 1.25) and the straight joints stay.
    obj = _polyline([0, 22, 0, 38])
    _edit(obj)
    assert _run(mode="FIT") == {"FINISHED"}
    seams = _seams(obj)
    assert (8, 9) in seams
    assert (4, 5) not in seams and (2, 3) not in seams and (6, 7) not in seams
    assert len(_vertex_us(obj, 8)) == 2 and len(_vertex_us(obj, 4)) == 1 and _uv_islands(obj) == 2
    obj = _polyline([22])                                    # a bend that a whole layout lays out within the limit
    _edit(obj)
    assert _run(mode="FIT") == {"FINISHED"} and _uv_islands(obj) == 1 and _worst_stretch(obj) <= 1.25
    obj = _polyline([60])                                    # one no whole layout lays out within 1.25: torn
    _edit(obj)
    assert _run(mode="FIT") == {"FINISHED"} and _uv_islands(obj) == 2 and (2, 3) in _seams(obj)
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


def test_ngon_strip_is_torn_only_as_far_as_the_stretch_limit_asks():
    # The user's three n-gons on exact geometry, with the defaults: Auto tears them into two pieces (the three
    # piece layout of the old measure is gone: the whole piece's best layout stays within the limit), every UV
    # edge its 3D length times one scale within 4 %, and no face beyond the limit by the honest measure.
    obj = _ngon_object(exact_ngon_verts())
    _edit(obj)
    stand = _OperatorStandIn(mode="FIT")
    assert stand.execute(bpy.context) == {"FINISHED"}, stand.reports
    assert stand.reports[-1] == "UV Stripe: 2 strip(s)", stand.reports
    ratios, errors = _uv_metrics(obj)
    assert max(ratios) / min(ratios) < 1.04, max(ratios) / min(ratios)       # measured 1.034
    assert max(errors) < 12.0, errors                                         # measured 10.9 degrees
    assert _worst_stretch(obj) < 1.25
    assert all(a > 0 for a in _face_areas(obj))


def test_ngon_strip_with_the_captured_coordinates_is_split_too():
    obj = _ngon_object(NGON_VERTS)
    _edit(obj)
    stand = _OperatorStandIn(mode="FIT")
    assert stand.execute(bpy.context) == {"FINISHED"} and stand.reports[-1] == "UV Stripe: 2 strip(s)", stand.reports
    ratios, errors = _uv_metrics(obj)
    assert max(ratios) / min(ratios) < 1.04 and max(errors) < 12.0      # as the exact geometry (0.001 rounding)


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
    obj = _polyline([0, 45, 0, 38])
    _edit(obj)
    assert _run(mode="FIT") == {"FINISHED"}                 # Straight Sides Both, Ends Slanted
    ratios, errors = _uv_metrics(obj)
    assert max(ratios) / min(ratios) < 1 + 1e-6 and max(errors) < 1e-4
    assert _vertex_us(obj, 8) != _vertex_us(obj, 9)         # the mitred end at the 38 degree bend keeps its slant
    assert _run(mode="FIT", ends="BOTH") == {"FINISHED"}   # upright ends stretch the mitres beyond 1.25: relaxed
    ratios, errors = _uv_metrics(obj)
    assert max(ratios) / min(ratios) < 1 + 1e-6 and max(errors) < 1e-4
    # with the limit lifted the strip's own two ends stand upright (the mitred faces stretch to do it)
    assert _run(mode="FIT", ends="BOTH", balance=1.0, stretch_limit=3.0) == {"FINISHED"}
    for i in (0, 5):
        assert _vertex_us(obj, 2 * i) == _vertex_us(obj, 2 * i + 1), i
    assert _worst_stretch(obj) > 1.25


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
        self.straight_sides, self.ends, self.balance = "BOTH", "SLANTED", 0.5
        self.side_picks = self.piece_shapes = self.island_cuts = self.corner_picks = self.seed_faces = self.guide_faces = ""
        self.offset_limit, self.offset_seed = 0.25, 0
        self.stretch_limit = 1.25
        self.cup_breaks = self.manual_cuts = self.skipped_cuts = self.align_edges = self.straight_lines = ""
        self.shape_align = "AUTO"
        self.show_options = False
        self.__dict__.update(OLD_DEFAULTS)
        self.__dict__.update(props)
        self.reports = []
        # like a real instance: its own property type at .properties.bl_rna (More Options reads the defaults)
        self.properties = SimpleNamespace(bl_rna=bpy.ops.iops.mesh_uv_stripe.get_rna_type())

    def report(self, _kinds, message):
        self.reports.append(message)

    def __getattr__(self, name):  # the operator's own methods, bound to this stand-in
        return getattr(operator, name).__get__(self)


class _KeyPress:
    """Stands in for a modal key press event."""

    def __init__(self, key, ctrl=False, alt=False, shift=False):
        self.type, self.value = key, "PRESS"
        self.ctrl, self.shift, self.alt, self.oskey = ctrl, shift, alt, False
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
    obj = _polyline([0, 45, 0, 38])
    _edit(obj)
    op = _modal_on(obj, mode="FIT")
    steps = [("A", "orientation", "VERTICAL"), ("E", "mode", "IN_PLACE"), ("Q", "straight_sides", "LONGER"),
             ("Q", "straight_sides", "SHORTER"), ("Q", "straight_sides", "NONE"), ("Q", "straight_sides", "BOTH"),
             ("W", "ends", "BOTH"), ("W", "ends", "LONGER"), ("W", "ends", "SHORTER"), ("W", "ends", "AUTO"),
             ("B", "balance", 1.0), ("B", "balance", 0.0), ("B", "balance", 0.5),
             ("E", "mode", "ACTIVE"), ("E", "mode", "STACK"), ("E", "mode", "FIT"),
             ("S", "split_at_seams", True), ("X", "mark_seams", False), ("A", "orientation", "HORIZONTAL")]
    for key, name, value in steps:
        before = _uv_state(obj)
        assert op._modal(bpy.context, _KeyPress(key)) == {"RUNNING_MODAL"}
        assert getattr(op, name) == value, (key, name, getattr(op, name))
        if key in "WA" and (key, name) != ("W", "ends"):
            assert _uv_state(obj)[0] != before[0], key          # the UVs follow at once
    op._finish(bpy.context)


def test_modal_alt_wheel_changes_the_stretch_limit_under_any_straight_sides():
    obj = _polyline([0, 45, 0, 38])
    _edit(obj)
    op = _modal_on(obj)
    for sides in ("BOTH", "LONGER", "SHORTER", "NONE"):
        op.straight_sides = sides
        op.stretch_limit = 1.25
        assert op._modal(bpy.context, _KeyPress("WHEELUPMOUSE", alt=True)) == {"RUNNING_MODAL"}, sides
        assert round(op.stretch_limit, 6) == 1.3, sides
        op._modal(bpy.context, _KeyPress("WHEELUPMOUSE", ctrl=True, alt=True))
        assert round(op.stretch_limit, 6) == 1.31, sides
        op._modal(bpy.context, _KeyPress("WHEELDOWNMOUSE", alt=True))
        op._modal(bpy.context, _KeyPress("WHEELDOWNMOUSE", alt=True))
        assert round(op.stretch_limit, 6) == 1.21, sides
    op.straight_sides = "BOTH"
    wheel = _KeyPress("WHEELUPMOUSE")
    wheel.shift = True                       # Shift + wheel is the Offset Limit, and only while Random Offset is on
    op.offset_axis = "NONE"
    limit = op.stretch_limit
    assert op._modal(bpy.context, wheel) == {"PASS_THROUGH"} and op.stretch_limit == limit   # the view pans
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
    op._modal(bpy.context, _KeyPress("WHEELUPMOUSE", ctrl=True))
    op._modal(bpy.context, _KeyPress("WHEELUPMOUSE", alt=True))
    assert op._modal(bpy.context, _KeyPress("ESC")) == {"CANCELLED"}
    assert _uv_state(obj) == before
    assert (op.mode, op.orientation, op.straight_sides, op.ends, op.balance, op.split_at_seams, op.mark_seams) == (
        "FIT", "HORIZONTAL", "BOTH", "SLANTED", 0.5, False, True)
    assert op.stretch_limit == 1.25


def test_modal_cancel_removes_a_uv_layer_it_made():
    obj = _grid(4, 1)
    _edit(obj)
    op = _modal_on(obj)
    assert bmesh.from_edit_mesh(obj.data).loops.layers.uv.active is not None
    assert op._modal(bpy.context, _KeyPress("RIGHTMOUSE")) == {"CANCELLED"}
    assert bmesh.from_edit_mesh(obj.data).loops.layers.uv.active is None


def test_modal_confirm_equals_execute():
    def made(confirm):
        obj = _polyline([0, 45, 0, 38])
        _edit(obj)
        _set_seams(obj, {(6, 7)})
        if confirm:
            op = _modal_on(obj)
            for key in ("A", "S"):
                op._modal(bpy.context, _KeyPress(key))
            op._modal(bpy.context, _KeyPress("WHEELUPMOUSE", ctrl=True))
            assert op._modal(bpy.context, _KeyPress("SPACE")) == {"FINISHED"}
            return _uv_state(obj), op.reports
        stand = _OperatorStandIn(orientation="VERTICAL", split_at_seams=True, balance=0.6)
        assert stand.execute(bpy.context) == {"FINISHED"}
        return _uv_state(obj), stand.reports

    assert made(True) == made(False)


def test_modal_nothing_to_lay_out_cancels_and_restores():
    obj = _cap(uv_size=10.0)
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


def _long_and_short():
    """In a 4 x 4 grid with UVs at xy / 10 + 0.5: a 4 x 1 strip (row 0, the active face in it) and a 2 x 1 strip
    (row 2, columns 0 - 1) selected: equally thick, the active one twice as long."""
    obj = _grid(4, 4, uv_size=10.0)
    _edit(obj, lambda c: c.y < 1.0 or (2.0 < c.y < 3.0 and c.x < 2.0))
    _set_active(obj, (1.5, 0.5))
    return obj


def test_fit_to_active_height_is_across_the_strip_and_width_along_it_in_both_orientations():
    sizes = {}
    for orientation in ("HORIZONTAL", "VERTICAL"):
        for fit in ("HEIGHT", "WIDTH"):
            obj = _long_and_short()
            assert _run(mode="ACTIVE", orientation=orientation, active_fit=fit) == {"FINISHED"}
            long, short = _size(_uv_box(obj, _low)), _size(_uv_box(obj, lambda c: 2.0 < c.y < 3.0 and c.x < 2.0))
            across = 0 if orientation == "VERTICAL" else 1          # the axis across the strips in UV
            along = 1 - across
            sizes[orientation, fit] = (tuple(round(x, 4) for x in long), tuple(round(x, 4) for x in short))
            if fit == "HEIGHT":       # equally thick: the same size across, the short one half as long
                assert _close(long[across], short[across]) and _close(short[along], long[along] / 2), sizes
            else:                     # as long as the active one: twice as thick
                assert _close(long[along], short[along]) and _close(short[across], 2 * long[across]), sizes
    print("  fit to active sizes (active, other):", sizes)


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
    assert op._modal(bpy.context, shift_wheel) == {"PASS_THROUGH"}        # no random offset: the view pans
    for expected in ("ALONG", "ACROSS", "BOTH"):
        op._modal(bpy.context, _KeyPress("Z"))
        assert op.offset_axis == expected
    moved = _uv_box(obj, _high)
    assert (moved[0] - before[0]).length > 1e-4
    op._modal(bpy.context, _KeyPress("R"))
    assert op.offset_seed == 1 and (_uv_box(obj, _high)[0] - moved[0]).length > 1e-6
    assert op._modal(bpy.context, shift_wheel) == {"RUNNING_MODAL"} and _close(op.offset_limit, 0.30)
    shift_wheel.type = "WHEELDOWNMOUSE"
    op._modal(bpy.context, shift_wheel)
    op._modal(bpy.context, shift_wheel)
    assert _close(op.offset_limit, 0.20)
    assert op._modal(bpy.context, _KeyPress("RET")) == {"FINISHED"}
    confirmed = _uv_state(obj)
    obj = _two_strips()
    stand = _OperatorStandIn(active_fit="HEIGHT", offset_axis="BOTH", offset_seed=1, offset_limit=0.2)
    assert stand.execute(bpy.context) == {"FINISHED"}
    assert _uv_state(obj) == confirmed


def test_modal_hud_and_help_list_every_key():
    from InteractionOps.operators.mesh_uv_stripe import _Result
    op = _OperatorStandIn(show_options=True)
    op._build_overlays(None)
    params = [p for section in op._hud.param_sections for p in section.params]
    assert [p.name for p in params] == [
        "Straight Sides (Q)", "Ends (W)", "Selected", "Balance (Ctrl + Wheel)", "Stretch Limit (Alt + Wheel)",
        "Seed and Guide Faces",
        "Align (G)", "Manual Cuts", "Straightened Lines", "Doubled Vertices", "More Options (Tab)", "Mode (E)",
        "Orientation (A)", "Fit to Active (D)", "Split at Seams (S)", "Mark Seams (X)", "Random Offset (Z)",
        "Offset Limit (Shift + Wheel)", "Offset Seed (R)", "Merge Doubles (F)"]
    assert [p.value_text() for p in params] == [
        "Both", "Slanted", "0", "0.50 · Least Stretch < > Even Texel", "1.25", "0", "Auto", "0", "0", "0", "✓", "Active",
        "Horizontal", "Width and Height", "✗", "✓", "None", "0.25", "0", "✗"]
    always = {"Straight Sides (Q)", "Ends (W)", "Balance (Ctrl + Wheel)", "More Options (Tab)"}
    more = {"Mode (E)", "Orientation (A)", "Fit to Active (D)", "Split at Seams (S)",
            "Mark Seams (X)", "Random Offset (Z)", "Offset Limit (Shift + Wheel)", "Offset Seed (R)",
            "Merge Doubles (F)"}
    assert _shown(op) == always | more       # no Stretch Limit, Seed and Guide Faces, Align, Cuts or Doubles yet
    op.straight_sides = "NONE"                               # Align applies to every piece; Ends do not
    assert _shown(op) == always | more | {"Align (G)"}
    active = {p.name: p.is_active() for p in params}
    assert not active["Ends (W)"] and active["Straight Sides (Q)"]
    op.straight_sides = "BOTH"
    assert "Align (G)" not in _shown(op)
    op._result = _Result(unfolded=1)                         # a piece relaxed to its real shape
    assert "Align (G)" in _shown(op)
    op._result = _Result(doubles=2)
    assert "Doubled Vertices" in _shown(op) and "Align (G)" not in _shown(op)
    assert {p.name: p.value_text() for p in params}["Doubled Vertices"] == "2"
    op._result = _Result(relaxed=1)                          # a piece Stretch Limit relaxed: its row shows
    assert "Stretch Limit (Alt + Wheel)" in _shown(op)
    op._result = _Result(balanced=2)                         # a balanced piece: the Balance row is live
    assert {p.name: p.is_active() for p in params}["Balance (Ctrl + Wheel)"]
    assert {p.name: p.value_text() for p in params}["Balance (Ctrl + Wheel)"] == "0.50 · Least Stretch < > Even Texel"
    op._result = _Result()                                   # none: the row stays, inactive, and says so
    assert not {p.name: p.is_active() for p in params}["Balance (Ctrl + Wheel)"]
    assert {p.name: p.value_text() for p in params}["Balance (Ctrl + Wheel)"] == "0.50 · no balanced piece to change"
    assert "Stretch Limit (Alt + Wheel)" not in _shown(op)
    op.seed_faces = '{"a": [1]}'
    assert "Seed and Guide Faces" in _shown(op)
    op.seed_faces = ""
    op.manual_cuts = '{"a": [1, 4], "b": [2]}'
    assert "Manual Cuts" in _shown(op)
    assert {p.name: p.value_text() for p in params}["Manual Cuts"] == "3" and op._manual_cut_count() == 3
    op.manual_cuts = ""
    assert "Straightened Lines" not in _shown(op)
    op.straight_lines = '{"a": [[0, 1, 4], [1, 7]], "b": [[1, 2]]}'
    assert "Straightened Lines" in _shown(op)
    assert {p.name: p.value_text() for p in params}["Straightened Lines"] == "3"
    op.straight_lines = ""
    active = {p.name: p.is_active() for p in params}
    assert active["Fit to Active (D)"] and not active["Offset Limit (Shift + Wheel)"]
    assert not active["Offset Seed (R)"]
    op.mode, op.offset_axis = "FIT", "BOTH"
    active = {p.name: p.is_active() for p in params}
    assert not active["Fit to Active (D)"] and active["Offset Limit (Shift + Wheel)"] and active["Offset Seed (R)"]
    assert [(section.title, [(it.label, it.key) for it in section.items]) for section in op._help.sections] == [
        ("Shape", [("Straight Sides (selected pieces, else all)", "Q"), ("Ends (selected pieces, else all)", "W"),
                   ("Balance", "Ctrl + Wheel"),
                   ("Balance, fine", "Ctrl + Shift + Wheel"),
                   ("Balance: 0, 0.5, 1", "B"), ("Stretch Limit (fine: Ctrl)", "Alt + Wheel"), ("Align", "G"),
                   ("Select a piece / clear", "LMB on a face"),
                   ("Add / remove a piece", "Shift + LMB on a face")]),
        ("Picking", [("Cut / mend a loop, break a ring, cut an island", "LMB on an edge"),
                     ("Cut / mend one edge", "Ctrl + LMB"), ("Pick lines to straighten", "V"),
                     ("Straighten a loop / one edge", "LMB / Alt + LMB"),
                     ("Corner of an island that is no strip", "LMB on its boundary"),
                     ("Seed face of an island", "Alt + LMB on a face"),
                     ("Guide face of the main run", "Shift + Alt + LMB")]),
        ("Placement", [("Mode", "E"), ("Orientation", "A"), ("Fit to Active", "D"), ("Split at Seams", "S"),
                       ("Mark Seams", "X"), ("Random Offset", "Z"), ("Offset Limit", "Shift + Wheel"),
                       ("Offset Seed", "R"), ("Merge Doubles", "F")]),
        ("General", [("More options in the HUD", "Tab"), ("Confirm", "Enter / Space"), ("Cancel", "Esc / RMB")])]
    assert op._status_text() == ("LMB face: select piece · Shift: add · LMB edge: cut / mend · Ctrl + LMB: one edge · "
                                 "Q / W: selected, else all · Enter: confirm · Esc: cancel")
    op._align_picking = True
    assert op._status_text().startswith("Picking lines to straighten")


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
    assert rna["straight_sides"].default == "BOTH" and rna["ends"].default == "AUTO"
    assert rna["balance"].default == 0.5 and (rna["balance"].hard_min, rna["balance"].hard_max) == (0.0, 1.0)
    assert round(rna["stretch_limit"].default, 6) == 1.25
    assert (rna["stretch_limit"].hard_min, rna["stretch_limit"].hard_max) == (1.0, 3.0)
    assert rna["split_at_seams"].default and rna["mark_seams"].default
    assert rna["merge_doubles"].default and rna["offset_axis"].default == "ALONG"
    for removed in ("layout", "split_at_bends", "split_angle"):
        assert removed not in rna, removed
    assert [item.identifier for item in rna["straight_sides"].enum_items] == ["BOTH", "LONGER", "SHORTER", "NONE"]
    assert [item.identifier for item in rna["ends"].enum_items] == ["AUTO", "SLANTED", "BOTH", "LONGER", "SHORTER"]
    assert [item.identifier for item in rna["offset_axis"].enum_items] == ["NONE", "ALONG", "ACROSS", "BOTH"]
    assert [item.identifier for item in rna["mode"].enum_items] == ["FIT", "IN_PLACE", "ACTIVE", "STACK"]


def _wedge():
    """One flat quad whose far row rises by 1 over its length of 2: no straight-row layout lays it out clean (the
    best of them stretches it 1.65 by the honest measure, beyond the default limit)."""
    obj = _object([(0.0, 0.0, 0.0), (2.0, 0.0, 0.0), (2.0, 2.0, 0.0), (0.0, 1.0, 0.0)], [(0, 1, 2, 3)])
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
    spread = [max(v[i] for i in ring) - min(v[i] for i in ring) for ring in rings]
    assert spread[0] < 1e-4, spread                          # the outer rail runs straight along U
    assert max(spread) < 0.005, spread                       # the balanced layout lets the fold and the foot waver
    assert all(a > 0 for a in _face_areas(obj))
    assert _worst_stretch(obj) < 1.3        # honest measure: 1.263 (corner triangles count), no tear is made for it


def test_modal_wheel_changes_the_stretch_limit_under_auto():
    obj = _wedge()
    op = _modal_on(obj, mode="FIT", stretch_limit=1.25)
    assert _worst_stretch(obj) < 1.0 + 1e-4
    for _ in range(6):
        assert op._modal(bpy.context, _KeyPress("WHEELDOWNMOUSE", alt=True)) == {"RUNNING_MODAL"}
    assert op.stretch_limit == 1.05                                         # never below 1.05
    assert _worst_stretch(obj) < 1.0 + 1e-4
    for _ in range(5):
        op._modal(bpy.context, _KeyPress("WHEELUPMOUSE", alt=True))
    op._modal(bpy.context, _KeyPress("WHEELUPMOUSE", ctrl=True, alt=True))
    assert round(op.stretch_limit, 6) == 1.31
    for _ in range(40):
        op._modal(bpy.context, _KeyPress("WHEELUPMOUSE", alt=True))
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
    obj = _polyline([0, 45, 0, 38])
    _edit(obj)
    stand = _OperatorStandIn(mode="FIT", ends="BOTH")
    result = stand._lay_out(bpy.context)
    assert result.done == 3 and result.stretched_faces == 0  # torn at the bends; relaxed to the true shape
    stand = _OperatorStandIn(mode="FIT", ends="BOTH", stretch_limit=3.0, balance=1.0)    # nothing relaxes
    result = stand._lay_out(bpy.context)
    assert result.stretched_faces > 0
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


def _cap_and_strip():
    """A 4 x 1 strip at the origin and, far above it, a disc of triangles (a cap: refused)."""
    cap_points, cap_faces = _cap_parts(6, centre=(2.0, 6.0))
    points = [(float(x), float(y), 0.0) for y in (0, 1) for x in range(5)] + cap_points
    faces = [(x, x + 1, x + 6, x + 5) for x in range(4)] + [tuple(10 + i for i in f) for f in cap_faces]
    return _object(points, faces, uv_size=10.0)


def test_rejected_island_leaves_the_other():
    obj = _cap_and_strip()
    _edit(obj)
    cap_before = [uv.copy() for _c, uv in _corners(obj, lambda c: c.y > 2.0)]
    assert _run(mode="FIT") == {"FINISHED"}
    cap_after = [uv for _c, uv in _corners(obj, lambda c: c.y > 2.0)]
    assert all((a - b).length < 1e-9 for a, b in zip(cap_before, cap_after)), "rejected island was changed"
    bm = bmesh.from_edit_mesh(obj.data)
    assert not any(e.seam for e in bm.edges if all(v.co.y > 2.5 for v in e.verts)), "rejected island got seams"
    for co, uv in _corners(obj, lambda c: c.y < 2.0):
        assert _close(uv.x, co.x / 4.0) and _close(uv.y, co.y / 4.0), (co, uv)
    stand = _OperatorStandIn(mode="FIT")
    result = stand._lay_out(bpy.context)
    assert (result.done, result.skipped, result.help, result.split) == (1, 1, [], [])


def test_a_branching_island_is_cut_and_laid_out_with_the_other():
    # A T of four cells (a branch) used to be refused: it is cut at its junction, each part its own strip.
    t_shape = {(0, 0), (1, 0), (2, 0), (1, 1)}
    strip = {(x, 4) for x in range(4)}
    obj = _grid(4, 5, keep=t_shape | strip, uv_size=10.0)
    _edit(obj)
    t_before = [uv.copy() for _c, uv in _corners(obj, lambda c: c.y < 2.0)]
    stand = _OperatorStandIn(mode="FIT")
    result = stand._lay_out(bpy.context)
    assert (result.done, result.skipped, result.help) == (3, 0, [])
    assert len(result.split) == 1 and "branches" in result.split[0], result.split
    t_after = [uv for _c, uv in _corners(obj, lambda c: c.y < 2.0)]
    assert any((a - b).length > 1e-6 for a, b in zip(t_before, t_after)), "the T was not laid out"
    assert all(a > 0 for a in _face_areas(obj, lambda c: c.y < 2.0))
    assert _run(mode="FIT") == {"FINISHED"}


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
    obj = _cap()
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


# --- cup break in the modal: LMB sets, R is the seed ----------------------------------------

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


def test_lmb_cuts_in_the_normal_state_with_no_pick_mode():
    # cutting has no mode of its own: Q, the wheel and Esc keep their meaning, and LMB off a side cuts
    obj = _annulus()
    _edit(obj)
    op = _modal_on(obj, mode="FIT")
    index = _edge_index(obj, (5, 13))
    op._hover_break = lambda _context, _event: None
    assert op._modal(bpy.context, _KeyPress("LEFTMOUSE")) == {"RUNNING_MODAL"}   # over nothing: nothing, no confirm
    assert op.cup_breaks == "" and op._hover is None and op._face_hover is None
    balance = op.balance
    assert op._modal(bpy.context, _KeyPress("WHEELUPMOUSE", ctrl=True)) == {"RUNNING_MODAL"}   # Balance
    assert op.balance == round(balance + 0.1, 6)
    _click(op, obj, (5, 13))
    assert _edges(op.cup_breaks) == {obj.name: [index]}
    assert op._modal(bpy.context, _KeyPress("Q")) == {"RUNNING_MODAL"} and op.straight_sides != "BOTH"
    assert op._modal(bpy.context, _KeyPress("ESC")) == {"CANCELLED"} and op.cup_breaks == ""
    op._finish(bpy.context)


def test_set_break_relays_out():
    obj = _annulus()
    _edit(obj)
    op = _modal_on(obj, mode="FIT")
    assert (3, 11) not in _seams(obj)                        # the ring is cut at a rung of its own until it is broken
    index = _edge_index(obj, (3, 11))
    assert index in op._result.rings[obj.name]              # a ring's cross edge can be picked
    assert op._set_break(bpy.context, obj, index)
    assert _uv_islands(obj) == 1
    assert _torn_at(op, obj, (3, 11)) and _seams(obj) & _inner_edges(obj) == {(3, 11)}
    op._finish(bpy.context)


def test_lmb_sets_the_hovered_break():
    # A real cursor cannot hover headless: the hover lookup is stood in for, the event handling is the operator's.
    obj = _annulus()
    _edit(obj)
    op = _modal_on(obj, mode="FIT")
    index = _edge_index(obj, (5, 13))
    op._hover_break = lambda _context, _event: (obj, index)
    move = _KeyPress("MOUSEMOVE")
    move.value = "NOTHING"
    assert op._modal(bpy.context, move) == {"RUNNING_MODAL"} and op._hover[:2] == (obj, index)
    assert len(op._hover[2]) == 2                            # the hovered edge's end points, for the preview
    assert not op._hover[3] and op._hover[4] is None         # a new cut: drawn in the cut colour
    assert op._hover_outline                                 # with the outline of the piece it changes
    assert op._modal(bpy.context, _KeyPress("LEFTMOUSE")) == {"RUNNING_MODAL"}       # not the confirm
    assert _uv_islands(obj) == 1 and _ring_seams(obj, lambda c: True) == {(5, 13)}
    op._hover_break = lambda _context, _event: None
    laid = _uv_state(obj)
    assert op._modal(bpy.context, _KeyPress("LEFTMOUSE")) == {"RUNNING_MODAL"}       # over nothing: no confirm
    assert _uv_state(obj) == laid and op._face_hover is None and op._hover is None
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


def test_r_changes_seed_and_c_does_nothing():
    obj = _annulus()
    _edit(obj)
    op = _modal_on(obj, mode="FIT", offset_axis="ALONG")
    assert op._modal(bpy.context, _KeyPress("R")) == {"RUNNING_MODAL"} and op.offset_seed == 1
    laid = _uv_state(obj)
    assert op._modal(bpy.context, _KeyPress("C")) == {"RUNNING_MODAL"}        # no pick mode for cuts any more
    assert op.offset_seed == 1 and not op._align_picking and _uv_state(obj) == laid
    assert not hasattr(op, "_picking")
    assert op._modal(bpy.context, _KeyPress("ESC")) == {"CANCELLED"}          # Esc cancels at once
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


# --- a closed band several faces wide: cut open from loop to loop ------------------------------

def _wide_band(**kwargs):
    """``uv_stripe_fixtures.wide_band`` (2 x 24 quads round Z, a cone band) as an object in Edit Mode, all selected."""
    from uv_stripe_fixtures import wide_band
    verts, faces = wide_band(**kwargs)
    obj = _object([verts[i] for i in range(len(verts))], [faces[k] for k in sorted(faces)], name="wide_band")
    _edit(obj)
    return obj


def _band_path(k, n=24):
    return {(k, n + k), (n + k, 2 * n + k)}


def _cut_paths(n=24):
    return [_band_path(k, n) for k in range(n)]


def test_a_wide_closed_band_is_cut_open_and_laid_out_as_one_strip():
    for props in ({}, {"straight_sides": "NONE"}, {"ends": "AUTO"}, {"ends": "BOTH", "balance": 1.0}):
        obj = _wide_band()
        assert _run(mode="FIT", mark_seams=True, **props) == {"FINISHED"}, props
        assert _uv_islands(obj) == 1 and all(a > 0 for a in _face_areas(obj)), props
        assert _seams(obj) & _inner_edges(obj) in _cut_paths(), props   # one cross path, loop to loop
    # a flat washer (the user's case: rows 1.66 x apart) too
    obj = _wide_band(segments=32, radii=(0.923, 0.732, 0.555), heights=(0.0, 0.0, 0.0))
    assert _run(mode="FIT", mark_seams=True, straight_sides="BOTH", ends="AUTO") == {"FINISHED"}
    assert _uv_islands(obj) == 1 and all(a > 0 for a in _face_areas(obj))
    assert _seams(obj) & _inner_edges(obj) in _cut_paths(32)


def test_a_wide_closed_band_is_cut_along_a_seam_line_across_it():
    obj = _wide_band()
    _set_seams(obj, _band_path(7))
    assert _run(mode="FIT", split_at_seams=True, mark_seams=True) == {"FINISHED"}
    assert _uv_islands(obj) == 1 and all(a > 0 for a in _face_areas(obj))
    assert _seams(obj) & _inner_edges(obj) == _band_path(7)


def test_a_wide_closed_band_is_cut_at_its_picked_break():
    obj = _wide_band()
    assert _run(mode="FIT", mark_seams=True, cup_breaks=_cup(obj, (24 + 5, 48 + 5))) == {"FINISHED"}
    assert _uv_islands(obj) == 1 and _seams(obj) & _inner_edges(obj) == _band_path(5)


def test_lmb_on_a_wide_closed_band_adds_breaks_and_takes_back_one():
    obj = _wide_band()
    op = _modal_on(obj, mode="FIT")
    default = _seams(obj) & _inner_edges(obj)
    assert default in _cut_paths()
    index = _edge_index(obj, (24 + 5, 48 + 5))
    assert index in op._result.band_paths[obj.name]
    # the hover previews the whole cross path through the edge under the cursor
    op._hover_break = lambda _context, _event: (obj, index)
    move = _KeyPress("MOUSEMOVE")
    move.value = "NOTHING"
    assert op._modal(bpy.context, move) == {"RUNNING_MODAL"} and op._hover[:2] == (obj, index)
    assert len(op._hover[2]) == 4 and not op._hover[3]
    _click(op, obj, (24 + 5, 48 + 5))
    assert _edges(op.cup_breaks) == {obj.name: [index]}
    assert _uv_islands(obj) == 1 and _seams(obj) & _inner_edges(obj) == _band_path(5)
    assert _torn_at(op, obj, (5, 29)) and _torn_at(op, obj, (29, 53))
    other = _click(op, obj, (11, 24 + 11))                  # another cross path: a second cut, the first stays
    assert _edges(op.cup_breaks) == {obj.name: [index, other]}
    assert _uv_islands(obj) == 2 and _seams(obj) & _inner_edges(obj) == _band_path(5) | _band_path(11)
    third = _click(op, obj, (17, 24 + 17))
    assert _edges(op.cup_breaks) == {obj.name: [index, other, third]} and _uv_islands(obj) == 3
    assert all(_torn_at(op, obj, p) for k in (5, 11, 17) for p in _band_path(k))
    assert _hover_on(op, obj, (24 + 11, 48 + 11))[3]         # on a cut: the click takes it back
    _click(op, obj, (24 + 11, 48 + 11))                     # that path's break alone is taken back
    assert _edges(op.cup_breaks) == {obj.name: [index, third]} and _uv_islands(obj) == 2
    assert _seams(obj) & _inner_edges(obj) == _band_path(5) | _band_path(17)
    _click(op, obj, (5, 29))
    _click(op, obj, (41, 65))
    assert op.cup_breaks == "" and _seams(obj) & _inner_edges(obj) == default
    op._finish(bpy.context)


def test_a_picked_break_on_a_wide_band_wins_over_a_seam_line_across_it():
    obj = _wide_band()
    _set_seams(obj, _band_path(7))
    op = _modal_on(obj, mode="FIT", split_at_seams=True, mark_seams=True)
    assert _seams(obj) & _inner_edges(obj) == _band_path(7)              # cut along the seam line
    before = _uv_state(obj)
    _click(op, obj, (24 + 5, 48 + 5))
    assert _edges(op.cup_breaks) == {obj.name: [_edge_index(obj, (24 + 5, 48 + 5))]}
    assert _uv_islands(obj) == 1 and _seams(obj) & _inner_edges(obj) == _band_path(5)   # the old line cleared
    assert _uv_state(obj) != before and len(op._result.cut_lines) == 4  # the break's whole line drawn as a cut
    _click(op, obj, (24 + 5, 48 + 5))                                    # taken back: the seam line again
    assert op.cup_breaks == "" and _seams(obj) & _inner_edges(obj) == _band_path(7)
    op._finish(bpy.context)


def test_confirm_after_a_wide_band_break_equals_execute():
    def made(confirm):
        obj = _wide_band()
        brk = _cup(obj, (24 + 9, 48 + 9))
        if confirm:
            op = _modal_on(obj, mode="FIT")
            _click(op, obj, (24 + 9, 48 + 9))
            assert op._modal(bpy.context, _KeyPress("RET")) == {"FINISHED"}
            assert op.cup_breaks == brk
            return _uv_state(obj)
        stand = _OperatorStandIn(mode="FIT", cup_breaks=brk)
        assert stand.execute(bpy.context) == {"FINISHED"}
        return _uv_state(obj)

    assert made(True) == made(False)


# --- each cut island is its own strip; Auto tears a wide strip at its bends; LMB takes automatic tears back -----

def _mitred_l():
    """``uv_stripe_fixtures.mitred_l``: a flat L two faces wide with a mitred corner, in Edit Mode, all selected."""
    from uv_stripe_fixtures import mitred_l
    verts, faces = mitred_l()
    obj = _object([verts[i] for i in range(len(verts))], [faces[k] for k in sorted(faces)], name="mitred_l")
    _edit(obj)
    return obj


MITRE = {(0, 1), (1, 2)}


def test_auto_tears_a_wide_l_at_its_mitre_when_it_cannot_be_straight_within_the_limit():
    obj = _mitred_l()
    assert _run(mode="FIT", mark_seams=True, stretch_limit=1.25) == {"FINISHED"}
    assert _uv_islands(obj) == 2 and _seams(obj) & _inner_edges(obj) == MITRE
    assert _worst_stretch(obj) < 1.0 + 1e-4 and all(a > 0 for a in _face_areas(obj))
    # a Stretch Limit the straight L keeps (its worst face stretches 3.24): no tear
    obj = _mitred_l()
    stand = _OperatorStandIn(mode="FIT", mark_seams=True, stretch_limit=10.0)   # beyond the property's own range
    assert stand.execute(bpy.context) == {"FINISHED"}
    assert _uv_islands(obj) == 1 and not _seams(obj) & _inner_edges(obj)
    # Straight Sides None unfolds it whole: nothing to straighten, nothing torn
    obj = _mitred_l()
    assert _run(mode="FIT", mark_seams=True, straight_sides="NONE") == {"FINISHED"}
    assert _uv_islands(obj) == 1


def test_c_takes_back_and_restores_an_automatic_tear_of_a_wide_strip():
    obj = _mitred_l()
    op = _modal_on(obj, mode="FIT")
    index = _edge_index(obj, (0, 1))
    assert op._result.done == 2 and index in op._result.auto_tears[obj.name]
    assert len(op._result.auto_tears[obj.name][index]) == 2               # the whole mitre line
    assert not op._result.skipped_tears
    _click(op, obj, (0, 1))                                               # LMB on the tear: taken back
    assert _edges(op.skipped_cuts) == {obj.name: sorted(op._result.auto_skipped[obj.name][index])}
    assert op._result.done == 1 and _uv_islands(obj) == 1                 # whole again, it stretches instead
    assert len(op._result.skipped_tears) == 4                             # drawn as a skipped tear (two edges)
    assert _hover_on(op, obj, (1, 2))[3]                                  # a click there restores it
    _click(op, obj, (1, 2))
    assert op.skipped_cuts == "" and op._result.done == 2 and _uv_islands(obj) == 2
    assert op._modal(bpy.context, _KeyPress("RET")) == {"FINISHED"}


def test_c_takes_back_an_automatic_junction_cut():
    t_shape = {(0, 0), (1, 0), (2, 0), (1, 1)}
    obj = _grid(3, 2, keep=t_shape)
    _edit(obj)
    op = _modal_on(obj, mode="FIT")
    made = op._result.auto_tears.get(obj.name, {})
    assert made and op._result.done >= 2                                 # the junction cut is offered
    cut = next(iter(made.values()))
    bm = bmesh.from_edit_mesh(obj.data)
    bm.edges.ensure_lookup_table()
    pair = tuple(sorted(v.index for v in bm.edges[cut[0]].verts))
    _click(op, obj, pair)
    assert set(_edges(op.skipped_cuts)[obj.name]) == set(cut)
    assert cut[0] in op._result.auto_skipped[obj.name] and cut[0] not in op._result.auto_tears.get(obj.name, {})
    _click(op, obj, pair)                                                # restored: the same cut again
    assert op.skipped_cuts == "" and op._result.auto_tears[obj.name].get(cut[0]) == cut
    op._finish(bpy.context)


def test_a_straight_line_is_picked_on_the_piece_under_the_cursor():
    import json
    from InteractionOps.operators.uv_stripe_bridge import ShapeRules
    from InteractionOps.utils.uv_stripe_core import Strip
    # the rules keep a line with an owning face on that face's piece only
    piece = Strip(verts={}, faces={4: (1, 2, 3, 0)}, near=[], far=[], rungs=[], closed=False, height=1.0)
    rules = ShapeRules(lines=(("ALONG", frozenset({0, 1}), 4), ("ALONG", frozenset({2, 3}), 9),
                              ("ACROSS", frozenset({1, 2}))))
    assert rules.lines_in(piece) == (("ALONG", frozenset({0, 1})), ("ACROSS", frozenset({1, 2})))
    # the mitre edge lies in both arms: the face under the cursor picks the arm, and the line keeps its face
    obj = _mitred_l()
    op = _modal_on(obj, mode="FIT", straight_sides="LONGER")
    index = _edge_index(obj, (0, 1))
    arms = {id(rec): rec for rec in op._result.pick_faces[obj.name].values()}
    assert len(arms) == 2
    for rec in arms.values():
        face = min(rec["strip"].faces)
        op._hover_face = face
        assert op._record(obj.name, index) is rec
    op._hover_face = None
    op._finish(bpy.context)
    stored = json.dumps({obj.name: [[0, [5], 3, 4]]})
    from InteractionOps.operators.mesh_uv_stripe import _dump_lines, _parse_lines as parse
    assert parse(stored) == {obj.name: [("ALONG", [3, 4], 5)]}
    assert parse(_dump_lines(parse(stored))) == parse(stored)
    assert parse(json.dumps({obj.name: [[1, 7, 8]]})) == {obj.name: [("ACROSS", [7, 8], None)]}   # an older pick


def test_cup_breaks_is_no_shared_setting():
    rna = bpy.ops.iops.mesh_uv_stripe.get_rna_type().properties
    assert rna["cup_breaks"].is_hidden and rna["cup_breaks"].is_skip_save
    from InteractionOps.operators.uv_stripe_bridge import StripeSettings
    assert "cup_breaks" not in StripeSettings.__dataclass_fields__
    for name in ("manual_cuts", "skipped_cuts"):
        assert rna[name].is_hidden and rna[name].is_skip_save and name not in StripeSettings.__dataclass_fields__


# --- cut edges in the modal: LMB marks and unmarks -------------------------------------------

def _edges(text):
    import json
    return json.loads(text) if text else {}


def _click(op, obj, pair, ctrl=False):
    """LMB (Ctrl + LMB with ``ctrl``) in the normal state on edge ``pair``, off every side and corner: the cut
    through it. A real cursor cannot hover headless: the hover lookup is stood in for (no side or corner is found
    without a region), the event handling is the operator's."""
    index = _edge_index(obj, pair)
    op._hover_break = lambda _context, _event: (obj, index)
    if op._align_picking:
        assert op._modal(bpy.context, _KeyPress("V")) == {"RUNNING_MODAL"} and not op._align_picking
    assert op._modal(bpy.context, _KeyPress("LEFTMOUSE", ctrl=ctrl)) == {"RUNNING_MODAL"}
    assert not op._align_picking
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
    obj = _polyline([0, 45, 0, 38])
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
    obj = _polyline([0, 45, 0, 38])
    _edit(obj)
    before = _uv_state(obj)
    op = _modal_on(obj, mode="FIT", manual_cuts="", skipped_cuts="")
    _click(op, obj, (8, 9))
    _click(op, obj, (2, 3))
    assert op.manual_cuts != "" and op.skipped_cuts != ""
    assert op._modal(bpy.context, _KeyPress("RIGHTMOUSE")) == {"CANCELLED"}      # no pick mode to leave first
    assert _uv_state(obj) == before and op.manual_cuts == "" and op.skipped_cuts == ""


def test_confirm_after_cuts_equals_execute():
    def made(confirm):
        obj = _ring_and_strip()
        if confirm:
            op = _modal_on(obj, mode="FIT")
            _click(op, obj, (3, 11))                         # the ring's break
            _click(op, obj, (6, 14))                         # a manual cut on the broken ring
            _click(op, obj, (18, 23))                        # a manual cut on the open strip
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
        obj = _polyline([0, 45, 0, 38])
        _edit(obj)
        if confirm:
            op = _modal_on(obj, mode="FIT")
            _click(op, obj, (8, 9))
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
    obj = _polyline([0, 45, 0, 38])
    _edit(obj)
    added, removed, undo = _recording_handlers(module)
    try:
        op = _OperatorStandIn(mode="FIT")
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
        op = _OperatorStandIn(mode="FIT")
        assert op.invoke(_InvokeContext(), _KeyPress("LEFTMOUSE")) == {"RUNNING_MODAL"}
        handles = {op._handle_view, op._handle}
        module._purge_handles()
        assert set(removed) == handles and not module._ACTIVE_HANDLES
        op._modal(bpy.context, _KeyPress("ESC"))
    finally:
        undo()
        module._purge_handles()


def test_execute_lays_out_at_once_and_invoke_always_starts_the_modal():
    # UV Stripe has one entry: every invoke (a key, a menu, a pie) is the interactive mode; execute (the redo
    # panel, scripts) lays the strips out at once, the modal confirming the same UVs
    from InteractionOps.operators import mesh_uv_stripe as module
    obj = _polyline([0, 45, 0, 38])
    _edit(obj)
    added, _removed, undo = _recording_handlers(module)
    try:
        stand = _OperatorStandIn(mode="FIT")
        assert stand.execute(bpy.context) == {"FINISHED"} and not added       # no modal, nothing drawn
        assert getattr(stand, "_hud", None) is None
    finally:
        undo()
    executed = _uv_state(obj)
    obj = _polyline([0, 45, 0, 38])
    _edit(obj)
    try:
        op = _OperatorStandIn(mode="FIT")
        context = _InvokeContext()
        assert op.invoke(context, _KeyPress("LEFTMOUSE")) == {"RUNNING_MODAL"}, op.reports
        assert context.window_manager.modal == [op] and op._hud is not None
        assert op._modal(bpy.context, _KeyPress("RET")) == {"FINISHED"}
        assert _uv_state(obj) == executed
    finally:
        module._purge_handles()

def test_invoke_starts_the_modal_and_esc_restores():
    from InteractionOps.operators import mesh_uv_stripe as module
    obj = _polyline([0, 45, 0, 38])
    _edit(obj)
    before = _uv_state(obj)
    try:
        op = _OperatorStandIn(mode="FIT")
        context = _InvokeContext()
        assert op.invoke(context, _KeyPress("LEFTMOUSE")) == {"RUNNING_MODAL"}, op.reports
        assert context.window_manager.modal == [op] and op._hud is not None
        assert _uv_state(obj) != before                   # laid out live
        assert op._modal(bpy.context, _KeyPress("ESC")) == {"CANCELLED"}
        assert _uv_state(obj) == before
    finally:
        module._purge_handles()


def test_more_options_property_and_no_interactive_flag():
    rna = bpy.ops.iops.mesh_uv_stripe.get_rna_type().properties
    assert "interactive" not in rna                          # every invoke is the interactive mode
    assert rna["show_options"].name == "More Options" and not rna["show_options"].default
    assert rna["show_options"].is_hidden and not rna["show_options"].is_skip_save
    from InteractionOps.operators.uv_stripe_bridge import StripeSettings
    assert "show_options" not in StripeSettings.__dataclass_fields__


ALWAYS_ROWS = {"Straight Sides (Q)", "Ends (W)", "Balance (Ctrl + Wheel)", "More Options (Tab)"}
# The Tab rows whose option is away from its default under the test's OLD_DEFAULTS: shown with Tab off too
IN_USE_ROWS = {"Fit to Active (D)", "Split at Seams (S)", "Random Offset (Z)", "Merge Doubles (F)"}
MORE_ROWS = {"Mode (E)", "Orientation (A)", "Fit to Active (D)", "Split at Seams (S)",
             "Mark Seams (X)", "Random Offset (Z)", "Offset Limit (Shift + Wheel)", "Offset Seed (R)",
             "Merge Doubles (F)"}


def _shown(op):
    return {p.name for section in op._hud.param_sections for p in section.params if p.is_visible()}


def test_tab_toggles_more_options_and_the_hud_rows():
    obj = _polyline([0, 45, 0, 38])
    _edit(obj)
    op = _modal_on(obj)                       # Straight Sides Both: no piece unfolded, so no Align row
    assert not op.show_options
    assert _shown(op) == ALWAYS_ROWS | IN_USE_ROWS
    before = _uv_state(obj)
    assert op._modal(bpy.context, _KeyPress("TAB")) == {"RUNNING_MODAL"} and op.show_options
    assert _uv_state(obj) == before                       # only the HUD changes
    assert _shown(op) == ALWAYS_ROWS | MORE_ROWS
    op.straight_sides = "NONE"
    op._relayout(bpy.context)
    assert _shown(op) == ALWAYS_ROWS | MORE_ROWS | {"Align (G)"}      # every piece at its real shape: Align applies
    op._modal(bpy.context, _KeyPress("TAB"))
    assert not op.show_options and _shown(op) == ALWAYS_ROWS | IN_USE_ROWS | {"Align (G)"}
    op.manual_cuts = '{"a": [1]}'
    assert "Manual Cuts" in _shown(op)
    op.manual_cuts = ""
    op._modal(bpy.context, _KeyPress("ESC"))


def test_keys_of_hidden_rows_work_while_collapsed():
    obj = _polyline([0, 45, 0, 38])
    _edit(obj)
    op = _modal_on(obj, mode="FIT")
    assert not op.show_options and "Orientation (A)" not in _shown(op)
    before = _uv_state(obj)
    assert op._modal(bpy.context, _KeyPress("A")) == {"RUNNING_MODAL"}
    assert op.orientation == "VERTICAL" and _uv_state(obj)[0] != before[0]
    assert "Orientation (A)" in _shown(op)                 # away from its default: shown with Tab off
    for key in ("E", "W", "B"):
        assert op._modal(bpy.context, _KeyPress(key)) == {"RUNNING_MODAL"}
    assert (op.mode, op.ends, op.balance) == ("IN_PLACE", "BOTH", 1.0) and not op.show_options
    op._modal(bpy.context, _KeyPress("ESC"))


def test_the_interactive_entry_is_folded_into_uv_stripe():
    from InteractionOps.operators import mesh_uv_stripe as module
    from InteractionOps.utils.functions import build_bindable_defaults, keymap_name_for_idname
    from InteractionOps.utils.renamed_idnames import RENAMED_IDNAMES, migrate_key_rows, migrate_operator_call
    assert not hasattr(module, "IOPS_OT_Mesh_UV_Stripe_Interactive")
    assert "iops.mesh_uv_stripe_interactive" not in {row[0] for row in build_bindable_defaults()}
    rows = {row[0]: row for row in build_bindable_defaults()}
    assert rows["iops.mesh_uv_stripe"][1] == "NONE" and keymap_name_for_idname("iops.mesh_uv_stripe") == "Mesh"
    assert RENAMED_IDNAMES["iops.mesh_uv_stripe_interactive"] == "iops.mesh_uv_stripe"
    saved = [["iops.mesh_uv_stripe", "NONE", "PRESS", False, False, False, False],
             ["iops.mesh_uv_stripe_interactive", "U", "PRESS", True, False, False, False]]
    assert migrate_key_rows(saved) == [["iops.mesh_uv_stripe", "U", "PRESS", True, False, False, False]]
    assert migrate_operator_call("iops.mesh_uv_stripe_interactive") == "iops.mesh_uv_stripe"   # a pie slot
    from InteractionOps.ui import iops_pie_edit, iops_pie_groups
    for source in (iops_pie_edit, iops_pie_groups):
        text = open(source.__file__, encoding="utf-8").read()
        assert "mesh_uv_stripe_interactive" not in text and "UV Stripe (Interactive)" not in text, source

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
    """The polyline (to lay out with ``_shape_props``: Straight Sides None and its bends cut by hand) in three True
    Shape pieces: faces 0-1 (vertices 0-5), 2-3 (4-9), 4 (8-11); vertex 2i left, 2i + 1 right of joint i, so
    (2i, 2i + 2) is a row edge and (2i, 2i + 1) a cross edge."""
    obj = _polyline([0, 45, 0, 38])
    _edit(obj)
    return obj


def _shape_props(obj):
    """What lays ``_shape_strip`` out as three True Shape pieces: Auto no longer tears a strip whose whole True Shape
    fits, so the two bends are cut by hand."""
    return {"straight_sides": "NONE", "manual_cuts": _dump(obj, (4, 5), (8, 9))}


def _click_align(op, obj, pair):
    """LMB while picking the align edge on edge ``pair`` (the hover lookup stood in for, as in ``_click``)."""
    index = _edge_index(obj, pair)
    op._hover_break = lambda _context, _event: (obj, index)
    if not op._align_picking:
        assert op._modal(bpy.context, _KeyPress("V")) == {"RUNNING_MODAL"} and op._align_picking
    assert op._modal(bpy.context, _KeyPress("LEFTMOUSE")) == {"RUNNING_MODAL"}
    assert op._align_picking
    return index


def test_g_cycles_the_align_values():
    obj = _shape_strip()
    op = _modal_on(obj, mode="FIT")
    seen = []
    for _ in range(4):
        assert op._modal(bpy.context, _KeyPress("G")) == {"RUNNING_MODAL"}
        seen.append(op.shape_align)
    assert seen == ["LONGEST", "SHORTEST", "PICKED", "AUTO"]
    op._finish(bpy.context)


def test_v_and_lmb_store_the_align_edge_and_keep_picking():
    obj = _shape_strip()
    op = _modal_on(obj, mode="FIT", **_shape_props(obj))
    assert _uv_islands(obj) == 3
    assert _edge_index(obj, (0, 2)) in op._result.align_pieces[obj.name]       # row edges are pickable
    assert _edge_index(obj, (2, 3)) in op._result.align_pieces[obj.name]       # and cross edges
    assert not op._result.align_lines
    auto = _uv_state(obj)
    assert not _along_v(obj, (4, 5))                         # the mitred end at the 45 degree bend is slanted
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


def test_v_picking_takes_lmb_and_esc_rmb_or_v_leave_it():
    obj = _shape_strip()
    op = _modal_on(obj, mode="FIT")
    laid = _uv_state(obj)
    for leave in ("ESC", "RIGHTMOUSE", "V"):
        op._modal(bpy.context, _KeyPress("V"))
        assert op._align_picking
        assert op._modal(bpy.context, _KeyPress("C")) == {"RUNNING_MODAL"} and op._align_picking   # C: nothing
        assert op._modal(bpy.context, _KeyPress(leave)) == {"RUNNING_MODAL"} and not op._align_picking, leave
        assert _uv_state(obj) == laid
    assert op._modal(bpy.context, _KeyPress("ESC")) == {"CANCELLED"}            # out of V, Esc cancels
    op._finish(bpy.context)


def test_cancel_restores_align_and_its_edges():
    obj = _shape_strip()
    before = _uv_state(obj)
    op = _modal_on(obj, mode="FIT", straight_sides="NONE")       # V sets the align edge under None only
    op._modal(bpy.context, _KeyPress("G"))
    _click_align(op, obj, (4, 5))
    assert op.shape_align == "PICKED" and op.align_edges != "" and op.straight_lines != ""
    assert op._modal(bpy.context, _KeyPress("ESC")) == {"RUNNING_MODAL"} and not op._align_picking
    assert op._modal(bpy.context, _KeyPress("ESC")) == {"CANCELLED"}
    assert _uv_state(obj) == before and op.shape_align == "AUTO" and op.align_edges == ""
    assert op.straight_lines == ""


def test_confirm_after_align_picks_equals_execute():
    import json

    def made(confirm):
        obj = _shape_strip()
        if confirm:
            op = _modal_on(obj, mode="FIT", **_shape_props(obj))
            _click_align(op, obj, (4, 5))
            _click_align(op, obj, (10, 11))        # upright already: a click that would change nothing does nothing
            op._modal(bpy.context, _KeyPress("V"))
            assert op._modal(bpy.context, _KeyPress("RET")) == {"FINISHED"}
            return (_uv_state(obj), op.shape_align, list(_edges(op.align_edges).values()),     # kept for redo
                    list(_parse_lines(op).values()))
        # V under None also lays each clicked edge straight: the end edges across the strip, vertical
        lines = json.dumps({obj.name: [[1, _edge_index(obj, (4, 5))]]}, sort_keys=True)
        stand = _OperatorStandIn(mode="FIT", shape_align="PICKED", align_edges=_dump(obj, (4, 5)),
                                 straight_lines=lines, **_shape_props(obj))
        assert stand.execute(bpy.context) == {"FINISHED"}
        return (_uv_state(obj), stand.shape_align, list(_edges(stand.align_edges).values()),
                list(_parse_lines(stand).values()))

    assert made(True) == made(False)
    obj = _shape_strip()
    edges = _dump(obj, (4, 5), (10, 11))
    assert bpy.ops.iops.mesh_uv_stripe(**{**OLD_DEFAULTS, "mode": "FIT", "shape_align": "PICKED",
                                        "align_edges": edges, **_shape_props(obj)}) == {"FINISHED"}
    assert _along_v(obj, (4, 5)) and _along_v(obj, (10, 11))
    for align in ("LONGEST", "SHORTEST"):                  # the modal's G and the property give the same UVs
        obj = _shape_strip()
        op = _modal_on(obj, mode="FIT", **_shape_props(obj))
        while op.shape_align != align:
            op._modal(bpy.context, _KeyPress("G"))
        assert op._modal(bpy.context, _KeyPress("SPACE")) == {"FINISHED"}
        confirmed = _uv_state(obj)
        obj = _shape_strip()
        stand = _OperatorStandIn(mode="FIT", shape_align=align, **_shape_props(obj))
        assert stand.execute(bpy.context) == {"FINISHED"}
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
    obj = _grid(4, 1)                                       # the piece set to None: unfolded at its real shape
    _edit(obj)
    op = _modal_on(obj, mode="FIT")
    _select(op, obj, 0)
    for _ in range(3):
        op._modal(bpy.context, _KeyPress("Q"))
    assert op._result.unfolded == 1 and "Align (G)" in _shown(op)
    op._modal(bpy.context, _KeyPress("ESC"))


def test_other_layouts_do_not_depend_on_align():
    # (Ends Both at the default limit relaxes every piece to its real shape, where Align applies: it takes the
    # limit lifted to show the upright layout is independent of it.)
    for ends, limit in (("SLANTED", 1.25), ("BOTH", 3.0), ("LONGER", 3.0)):
        states = []
        for align in ("AUTO", "LONGEST", "SHORTEST", "PICKED"):
            obj = _shape_strip()
            edges = _dump(obj, (2, 3), (6, 8)) if align == "PICKED" else ""
            stand = _OperatorStandIn(mode="FIT", straight_sides="BOTH", ends=ends, shape_align=align,
                                     align_edges=edges, stretch_limit=limit, manual_cuts=_dump(obj, (4, 5), (8, 9)))
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


def _select(op, obj, face, shift=False):
    """LMB (Shift + LMB with ``shift``) on face ``face`` of ``obj``, away from its edges: the face and the edge
    lookups are stood in for (no region headless), the event handling is the operator's."""
    op._face_under = lambda _context, _event: (obj, face)
    op._hover_break = lambda _context, _event: None
    assert op._modal(bpy.context, _KeyPress("LEFTMOUSE", shift=shift)) == {"RUNNING_MODAL"}


def _two_tapers():
    """Two ``_taper_strip`` strips in one object, faces 0 - 2 (vertices 0 - 7) and 3 - 5 (vertices 8 - 15), the
    second 3 m above the first, in Edit Mode, all selected."""
    row, points = 4, []
    for dy in (0.0, 3.0):
        points += [(float(x), dy, 0.0) for x in range(row)] + [(float(x), dy + 1.0 - 0.1 * x, 0.0) for x in range(row)]
    faces = [(o + i, o + i + 1, o + i + row + 1, o + i + row) for o in (0, 8) for i in range(3)]
    obj = _object(points, faces)
    _edit(obj)
    return obj


def _first(c):
    return c.y < 2.0


def _second(c):
    return c.y > 2.0


def _layout_shape(obj, only):
    """The UVs of the faces passing ``only`` up to one scale and a shift (the pieces of a run share a texel
    density, so one piece's layout scales the others): each corner's UV from the box's low corner over its width,
    rounded."""
    corners = _corners(obj, only)
    us, vs = [uv.x for _c, uv in corners], [uv.y for _c, uv in corners]
    width = max(us) - min(us)
    return [(tuple(co), round((uv.x - min(us)) / width, 6), round((uv.y - min(vs)) / width, 6)) for co, uv in corners]


def _piece(op, obj, face):
    return op._result.piece_faces[obj.name][face]


def _shapes(op):
    import json
    return json.loads(op.piece_shapes) if op.piece_shapes else {}


def test_q_and_w_on_a_selected_piece_change_only_that_piece():
    obj = _two_tapers()
    op = _modal_on(obj, mode="FIT")
    first, second = _piece(op, obj, 0), _piece(op, obj, 3)
    assert all(_side(op, obj, n, s).straight for n in (first, second) for s in ("near", "far"))
    laid_second = _layout_shape(obj, _second)
    _select(op, obj, 0)
    assert op._selected_pieces() == [(obj.name, ("piece", first))]
    assert "Selected" in _shown(op) and op._shape_text("SIDES") == "Both · 1 selected"
    assert op._modal(bpy.context, _KeyPress("Q")) == {"RUNNING_MODAL"}       # Both -> Longer Side, this piece only
    assert op.straight_sides == "BOTH" and op._shape_text("SIDES") == "Longer Side · 1 selected"
    # the far rail closes in at a slant: it is the longer one
    assert not _side(op, obj, first, "near").straight and _side(op, obj, first, "far").straight
    assert _layout_shape(obj, _second) == laid_second                        # the other piece is laid out as it was
    assert _shapes(op) == {obj.name: [["SIDES", "LONGER", [0, 1, 2]]]}
    assert op._modal(bpy.context, _KeyPress("W")) == {"RUNNING_MODAL"}       # Slanted -> Both, this piece only
    assert op.ends == "SLANTED" and _side(op, obj, first, "end0").straight and _side(op, obj, first, "end1").straight
    assert _layout_shape(obj, _second) == laid_second
    _select(op, obj, 4, shift=True)                                          # Shift: both selected
    assert [key for _name, key in op._selected_pieces()] == [("piece", first), ("piece", _piece(op, obj, 3))]
    op._modal(bpy.context, _KeyPress("Q"))                                   # both to the value after the first's
    assert op._shape_text("SIDES") == "Shorter Side · 2 selected"
    assert _side(op, obj, first, "near").straight and not _side(op, obj, first, "far").straight
    assert _side(op, obj, _piece(op, obj, 3), "near").straight and not _side(op, obj, _piece(op, obj, 3), "far").straight
    _select(op, obj, 4, shift=True)                                          # Shift again: removed
    assert op._selected_pieces() == [(obj.name, ("piece", first))]
    _select(op, obj, 1)                                                      # LMB on the only selected one: cleared
    assert op._selected_pieces() == [] and "Selected" not in _shown(op)
    _select(op, obj, 3)
    op._face_under = lambda _context, _event: None
    op._modal(bpy.context, _KeyPress("LEFTMOUSE"))                           # over nothing: cleared
    assert op._selected_pieces() == []
    # with nothing selected Q cycles the operator's own value for every piece and drops the pieces' own sides,
    # W's pieces' ends stay
    op._modal(bpy.context, _KeyPress("Q"))
    assert op.straight_sides == "LONGER" and [e[0] for e in _shapes(op)[obj.name]] == ["ENDS"]
    assert all(not _side(op, obj, n, "near").straight and _side(op, obj, n, "far").straight
               for n in (_piece(op, obj, 0), _piece(op, obj, 3)))
    op._modal(bpy.context, _KeyPress("W"))
    assert op.ends == "BOTH" and op.piece_shapes == ""
    op._finish(bpy.context)


def test_w_on_a_selected_one_face_wide_strip_stands_its_ends_upright():
    obj = _sheared_strip()
    op = _modal_on(obj, mode="FIT")
    assert not _side(op, obj, 0, "end0").straight and not _side(op, obj, 0, "end1").straight
    assert _vertex_us(obj, 3) != _vertex_us(obj, 7) and _vertex_us(obj, 0) != _vertex_us(obj, 4)   # both slanted
    slanted = _uv_state(obj)
    _select(op, obj, 1)
    op._modal(bpy.context, _KeyPress("W"))                                   # Slanted -> Both
    assert _side(op, obj, 0, "end0").straight and _side(op, obj, 0, "end1").straight
    assert _vertex_us(obj, 3) == _vertex_us(obj, 7) and _vertex_us(obj, 0) == _vertex_us(obj, 4)   # upright
    for _ in range(4):                                                       # Longer, Shorter, Upright Where Cheap
        op._modal(bpy.context, _KeyPress("W"))                               # (slanted one face wide), Slanted
    assert op._shape_text("ENDS") == "Slanted · 1 selected" and _uv_state(obj) == slanted
    op._finish(bpy.context)


def test_piece_shapes_are_kept_for_redo_and_a_fresh_run_starts_from_the_defaults():
    import json
    obj = _taper_strip()
    op = _modal_on(obj, mode="FIT")
    defaults = _uv_state(obj)
    near, far = _side(op, obj, 0, "near"), _side(op, obj, 0, "far")
    _select(op, obj, 0)
    op._modal(bpy.context, _KeyPress("Q"))
    op._modal(bpy.context, _KeyPress("Q"))                                   # Shorter Side for this piece
    chosen = _uv_state(obj)
    assert chosen != defaults
    assert op._modal(bpy.context, _KeyPress("RET")) == {"FINISHED"}
    assert _uv_state(obj) == chosen
    kept = op.piece_shapes
    assert kept and op.straight_sides == "BOTH"
    _set_uvs(obj, lambda co: co.xy * 0.37)
    stand = _OperatorStandIn(mode="FIT", piece_shapes=kept)
    assert stand.execute(bpy.context) == {"FINISHED"}
    assert _uv_state(obj) == chosen                                          # the confirmed shapes, laid out again
    _set_uvs(obj, lambda co: co.xy * 0.37)
    assert _run(mode="FIT", piece_shapes=kept) == {"FINISHED"}               # and through the operator itself
    assert _uv_state(obj) == chosen
    _set_uvs(obj, lambda co: co.xy * 0.37)
    assert _OperatorStandIn(mode="FIT").execute(bpy.context) == {"FINISHED"}
    assert _uv_state(obj) == defaults                                        # a fresh run starts without them
    _set_uvs(obj, lambda co: co.xy * 0.37)
    assert _run(mode="FIT") == {"FINISHED"} and _uv_state(obj) == defaults
    # side picks stored by an older run (a long side clicked free) still lay out as they did: the near rail free
    old = json.dumps({obj.name: [[near.faces[0], near.edges[0], False], [far.faces[0], far.edges[0], True]]})
    _set_uvs(obj, lambda co: co.xy * 0.37)
    assert _run(mode="FIT", side_picks=old) == {"FINISHED"}
    assert len({v for i in range(4) for v in _vertex_vs(obj, i)}) == 4       # the near rail follows its faces
    assert len({v for i in range(4, 8) for v in _vertex_vs(obj, i)}) == 1    # the far rail straight


def test_lmb_over_nothing_changes_nothing_and_only_enter_confirms():
    # A real cursor cannot hover headless: the face and edge lookups are stood in for, the event handling is the
    # operator's.
    obj = _taper_strip()
    op = _modal_on(obj, mode="FIT")
    laid = _uv_state(obj)
    op._face_under = lambda _context, _event: None
    op._hover_break = lambda _context, _event: None
    for _ in range(2):
        assert op._modal(bpy.context, _KeyPress("LEFTMOUSE")) == {"RUNNING_MODAL"}     # nothing under it: no confirm
    assert _uv_state(obj) == laid and op.piece_shapes == "" and op._face_hover is None and op._hover is None
    _select(op, obj, 0)
    assert op._face_hover == (obj, 0) and op._face_outline                  # kept for the preview
    assert _uv_state(obj) == laid                                            # selecting changes no UV
    assert op._modal(bpy.context, _KeyPress("RET")) == {"FINISHED"} and _uv_state(obj) == laid
    for key in ("NUMPAD_ENTER", "SPACE"):
        obj = _taper_strip()
        op = _modal_on(obj, mode="FIT")
        assert op._modal(bpy.context, _KeyPress(key)) == {"FINISHED"}, key


def test_e_and_a_keep_the_piece_shapes():
    obj = _taper_strip()
    op = _modal_on(obj, mode="FIT")
    _select(op, obj, 0)
    op._modal(bpy.context, _KeyPress("Q"))                                   # Longer Side: the near rail free
    shapes = op.piece_shapes
    for key in ("E", "E", "E", "E", "A", "A", "A", "A"):                      # a full round of each
        assert op._modal(bpy.context, _KeyPress(key)) == {"RUNNING_MODAL"}
        assert op.piece_shapes == shapes, key
        assert not _side(op, obj, 0, "near").straight, (key, op.straight_sides, op.ends)    # still free
        assert _side(op, obj, 0, "far").straight, (key, op.straight_sides, op.ends)
        assert len({v for i in range(4) for v in _vertex_vs(obj, i)}) == 4
    assert (op.straight_sides, op.ends) == ("BOTH", "SLANTED")
    op._finish(bpy.context)


def test_esc_restores_the_piece_shapes_and_the_uvs():
    obj = _taper_strip()
    before = _uv_state(obj)
    op = _modal_on(obj, mode="FIT")
    _select(op, obj, 0)
    op._modal(bpy.context, _KeyPress("Q"))
    op._modal(bpy.context, _KeyPress("Q"))
    op._modal(bpy.context, _KeyPress("E"))
    assert op.piece_shapes != "" and _uv_state(obj) != before
    assert op._modal(bpy.context, _KeyPress("ESC")) == {"CANCELLED"}
    assert op.piece_shapes == "" and op.straight_sides == "BOTH" and _uv_state(obj) == before
    # shapes the run started with come back too
    op = _modal_on(obj, mode="FIT")
    _select(op, obj, 0)
    op._modal(bpy.context, _KeyPress("Q"))
    op._modal(bpy.context, _KeyPress("Q"))
    kept = op.piece_shapes
    assert op._modal(bpy.context, _KeyPress("RET")) == {"FINISHED"}
    _set_uvs(obj, lambda co: co.xy * 0.37)
    before = _uv_state(obj)
    op = _modal_on(obj, mode="FIT", piece_shapes=kept)
    _select(op, obj, 0)
    op._modal(bpy.context, _KeyPress("W"))
    assert op.piece_shapes != kept
    assert op._modal(bpy.context, _KeyPress("RIGHTMOUSE")) == {"CANCELLED"}
    assert op.piece_shapes == kept and _uv_state(obj) == before


def test_hud_rows_follow_the_state():
    base = ALWAYS_ROWS | IN_USE_ROWS | {"Mode (E)"}         # Mode Fit and the other options in use show with Tab off
    obj = _polyline([0, 45, 0, 38])
    _edit(obj)
    op = _modal_on(obj, mode="FIT")
    assert _shown(op) == base                                          # no Align, Manual Cuts, Doubled Vertices
    for _ in range(3):
        op._modal(bpy.context, _KeyPress("Q"))                                # Both, Longer, Shorter, None
    assert op.straight_sides == "NONE" and _shown(op) == base | {"Align (G)"}
    op._modal(bpy.context, _KeyPress("Q"))
    assert op.straight_sides == "BOTH" and _shown(op) == base
    _click(op, obj, (2, 3))
    assert _shown(op) == base | {"Manual Cuts"}
    params = {p.name: p for section in op._hud.param_sections for p in section.params}
    assert params["Manual Cuts"].value_text() == "1"
    op._modal(bpy.context, _KeyPress("ESC"))
    assert op._modal(bpy.context, _KeyPress("ESC")) == {"CANCELLED"}
    obj = _grid(4, 1)                                                         # the piece's Straight Sides to None
    _edit(obj)
    op = _modal_on(obj, mode="FIT")
    assert _shown(op) == base
    _select(op, obj, 0)
    assert _shown(op) == base | {"Selected"}
    op._modal(bpy.context, _KeyPress("Q"))
    assert _shown(op) == base | {"Selected"}                           # one side free: the other is straight
    op._modal(bpy.context, _KeyPress("Q"))
    op._modal(bpy.context, _KeyPress("Q"))
    assert _shown(op) == base | {"Selected", "Align (G)"}
    op._modal(bpy.context, _KeyPress("ESC"))
    obj = _double_object()
    op = _modal_on(obj, mode="FIT")
    assert _shown(op) == base | {"Doubled Vertices"}
    op._modal(bpy.context, _KeyPress("ESC"))


def test_v_picking_shows_its_line_in_the_hud_header():
    from types import SimpleNamespace
    obj = _polyline([0, 45, 0, 38])
    _edit(obj)
    op = _modal_on(obj, mode="FIT")
    op._hud.draw = op._help.draw = lambda *_args: None                        # no GPU in the background
    context = SimpleNamespace(region_data=object())
    op._draw_callback(context)
    assert op._hud._header_lines == ["3 strip(s)"]
    op._modal(bpy.context, _KeyPress("V"))
    op._draw_callback(context)
    assert op._hud._header_lines == ["Picking lines to straighten · Alt: single edge · V to stop", "3 strip(s)"]
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
    for name in ("side_picks", "piece_shapes"):
        assert name not in StripeSettings.__dataclass_fields__
        assert rna[name].is_hidden and rna[name].is_skip_save
    assert not rna["straight_sides"].is_skip_save and not rna["ends"].is_skip_save and not rna["balance"].is_skip_save
    assert (rna["straight_sides"].default, rna["ends"].default, rna["balance"].default) == (
        "BOTH", "AUTO", 0.5)
    assert round(rna["stretch_limit"].default, 6) == 1.25
    settings = StripeSettings.from_operator(_OperatorStandIn(straight_sides="LONGER", ends="SHORTER", balance=0.0))
    assert (settings.straight_sides, settings.ends, settings.balance) == ("LONGER", "SHORTER", 0.0)


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
                                                  (1.0, 0.5, 0.0)):
        shape = {"straight_sides": sides, "ends": ends, "balance": balance}
        obj = _ngon_object(exact_ngon_verts())
        _edit(obj)
        assert _run(mode="FIT", **shape) == {"FINISHED"}, shape
        assert all(a > 0 for a in _face_areas(obj)), shape
        # the honest measure counts the corner triangles: the n-gons stretch at most two faces (the ends of a
        # layout that keeps its rails straight and does not relax), none at the real shape (Straight Sides None)
        count = _stretched_count(obj)
        assert count == 0 if sides == "NONE" else count <= 2, (shape, count)
        obj = _bent_patch()
        assert _run(mode="FIT", **shape) == {"FINISHED"}, shape
        assert all(a > 0 for a in _face_areas(obj)), shape
        count = _stretched_count(obj)
        assert _worst_stretch(obj) <= 1.25 + 1e-6, shape         # every layout is within the default limit
        if sides == "NONE" or balance == 1.0:
            assert count == 0, shape                       # the real shape (Even Texel relaxes the patch to it)
        if (sides, ends, balance) == ("BOTH", "SLANTED", 0.5):
            assert count == 18, shape                      # the defaults: some stretch left, within the limit


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


def test_double_click_selects_and_cuts_like_a_press():
    obj = _taper_strip()
    op = _modal_on(obj, mode="FIT")
    op._face_under = lambda _context, _event: (obj, 0)
    op._hover_break = lambda _context, _event: None
    assert op._modal(bpy.context, _double_click()) == {"RUNNING_MODAL"}
    assert op._selected_pieces() == [(obj.name, ("piece", 0))]
    op._face_under = lambda _context, _event: None
    assert op._modal(bpy.context, _double_click()) == {"RUNNING_MODAL"}       # over nothing: cleared, no confirm
    assert op._selected_pieces() == []
    assert op._modal(bpy.context, _KeyPress("RET")) == {"FINISHED"}
    # near an edge a double click cuts like a press
    obj = _grid(4, 1)
    _edit(obj)
    op = _modal_on(obj, mode="FIT")
    index = _edge_index(obj, (2, 7))
    op._hover_break = lambda _context, _event: (obj, index)
    assert op._modal(bpy.context, _double_click()) == {"RUNNING_MODAL"}
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
    """``bpy.context`` with a region and view data (stood in for) and the edit objects, so ``_hover_break`` runs."""

    def __init__(self, obj):
        from types import SimpleNamespace
        self.region = self.region_data = object()
        self.preferences = SimpleNamespace(system=SimpleNamespace(ui_scale=1.0))   # 0 in a background Blender
        self.objects_in_mode_unique_data = [obj]

    def __getattr__(self, name):
        return getattr(bpy.context, name)


def test_lmb_cuts_only_within_the_pick_distance_of_an_edge():
    # No region headless: the raycast and the on-screen distance are stood in for, the lookup is the operator's.
    from InteractionOps.operators.mesh_uv_stripe import EDGE_PICK_RADIUS
    from InteractionOps.utils import picking
    obj = _grid(4, 1)
    _edit(obj)
    op = _modal_on(obj, mode="FIT")
    index = _edge_index(obj, (2, 7))
    face = 1                                                                 # a face beside the edge
    distance = {"px": 1.0}
    real_ray, real_closest = picking.raycast_edit_meshes, picking.closest_edge_screen

    def raycast(*_args, **_kwargs):
        return (True, None, None, face, obj)

    def closest(_context, edges, _matrix, _coord):
        k = next((i for i, e in enumerate(edges) if e.index == index), None)
        return (k, distance["px"]) if k is not None else (None, 1e9)

    picking.raycast_edit_meshes, picking.closest_edge_screen = raycast, closest
    op._face_under = lambda _context, _event: (obj, face)
    try:
        context, move = _HoverContext(obj), _KeyPress("MOUSEMOVE")
        move.value = "NOTHING"
        op._update_normal_hover(context, move)
        assert op._hover is not None and op._hover[1] == index and op._face_hover is None   # near: the cut
        distance["px"] = EDGE_PICK_RADIUS + 5.0
        op._update_normal_hover(context, move)
        assert op._hover is None and op._face_hover == (obj, face)                       # mid-face: the piece
        distance["px"] = 1.0
        shifted = _KeyPress("MOUSEMOVE", shift=True)
        op._update_normal_hover(context, shifted)
        assert op._hover is None and op._face_hover == (obj, face)                       # Shift never cuts
        op._modal(context, _KeyPress("V"))                                               # V: no pick distance
        distance["px"] = EDGE_PICK_RADIUS + 5.0
        op._update_hover(context, move)
        assert op._hover is None or op._hover[1] == index
    finally:
        picking.raycast_edit_meshes, picking.closest_edge_screen = real_ray, real_closest
    op._finish(bpy.context)


# --- Balance wheel, B, Stretch Limit wheel: the wheel works in every state ---------------------------------------

def _uv_close(a, b, tol=1e-6):
    """Whether two ``_uv_state`` UV lists agree within ``tol``."""
    return a is not None and b is not None and len(a) == len(b) and all(
        abs(x - y) <= tol for p, q in zip(a, b) for x, y in zip(p, q))


def _wide_l(cols=8):
    """The wide L patch (a ledge and the wall hanging from it, 2 faces wide, over half a turn), selected, in Edit
    Mode; its balanced piece is what the Balance wheel changes."""
    obj, rings = _l_arc_object(cols=cols)
    _edit(obj)
    return obj, rings


def _states(op):
    """The modal's states in turn: (name, enter, leave) callables; every state the wheel has to work in."""
    def pick(key):
        def enter():
            assert op._modal(bpy.context, _KeyPress(key)) == {"RUNNING_MODAL"}
        return enter

    def leave(key):
        def go():
            assert op._modal(bpy.context, _KeyPress(key)) == {"RUNNING_MODAL"}
        return go

    def help_on():
        op._help.expanded = True

    def help_off():
        op._help.expanded = False

    def nothing():
        pass

    return (("normal", nothing, nothing), ("align pick mode", pick("V"), leave("V")), ("help open", help_on, help_off))


def test_the_wheel_changes_balance_and_stretch_limit_in_every_state():
    obj, _rings = _wide_l()
    op = _modal_on(obj, mode="FIT")
    assert op._result.balanced == 1 and op.balance == 0.5
    for name, enter, leave in _states(op):
        op.balance, op.stretch_limit = 0.5, 1.25
        op._relayout(bpy.context)
        enter()
        picking = op._align_picking
        before = _uv_state(obj)
        assert op._modal(bpy.context, _KeyPress("WHEELUPMOUSE", ctrl=True)) == {"RUNNING_MODAL"}, name
        assert round(op.balance, 6) == 0.6, name
        assert _uv_state(obj)[0] != before[0], name                          # the wide strip's UVs follow at once
        fine = _KeyPress("WHEELUPMOUSE", ctrl=True, shift=True)
        assert op._modal(bpy.context, fine) == {"RUNNING_MODAL"}, name
        assert round(op.balance, 6) == 0.62, name                            # Ctrl + Shift: fine
        assert op._modal(bpy.context, _KeyPress("WHEELDOWNMOUSE", ctrl=True)) == {"RUNNING_MODAL"}, name
        assert round(op.balance, 6) == 0.52, name
        assert op._modal(bpy.context, _KeyPress("WHEELUPMOUSE", alt=True)) == {"RUNNING_MODAL"}, name
        assert round(op.stretch_limit, 6) == 1.3, name
        assert op._modal(bpy.context, _KeyPress("WHEELUPMOUSE", alt=True, ctrl=True)) == {"RUNNING_MODAL"}, name
        assert round(op.stretch_limit, 6) == 1.31, name                      # Ctrl + Alt: fine
        for _ in range(8):
            assert op._modal(bpy.context, _KeyPress("WHEELDOWNMOUSE", alt=True)) == {"RUNNING_MODAL"}, name
        assert op.stretch_limit == 1.05, name                                # never below 1.05
        assert op._align_picking == picking, name                            # the wheel leaves the state as it is
        assert op.cup_breaks == "" and op.island_cuts == "" and op.align_edges == "", name
        leave()
    assert op._modal(bpy.context, _KeyPress("ESC")) == {"CANCELLED"}
    assert (op.balance, op.stretch_limit) == (0.5, 1.25)                     # cancel gives both back


def test_the_plain_wheel_zooms_the_view_in_every_state():
    obj, _rings = _wide_l()
    op = _modal_on(obj, mode="FIT")
    for name, enter, leave in _states(op):
        enter()
        picking = op._align_picking
        before = (op.balance, op.stretch_limit, op.offset_limit, _uv_state(obj))
        for key in ("WHEELUPMOUSE", "WHEELDOWNMOUSE"):
            assert op._modal(bpy.context, _KeyPress(key)) == {"PASS_THROUGH"}, (name, key)
        assert (op.balance, op.stretch_limit, op.offset_limit, _uv_state(obj)) == before, name
        assert op._align_picking == picking, name
        leave()
    op._modal(bpy.context, _KeyPress("ESC"))


def test_the_wheel_clamps_balance_between_zero_and_one():
    obj, _rings = _wide_l()
    op = _modal_on(obj, mode="FIT")
    for _ in range(9):
        op._modal(bpy.context, _KeyPress("WHEELDOWNMOUSE", ctrl=True))
    assert op.balance == 0.0
    op._modal(bpy.context, _KeyPress("WHEELDOWNMOUSE", ctrl=True))
    assert op.balance == 0.0
    for _ in range(11):
        op._modal(bpy.context, _KeyPress("WHEELUPMOUSE", ctrl=True))
    assert op.balance == 1.0
    for _ in range(100):
        op._modal(bpy.context, _KeyPress("WHEELUPMOUSE", alt=True))
    assert op.stretch_limit == 3.0
    op._modal(bpy.context, _KeyPress("ESC"))


def test_the_balance_row_is_inactive_without_a_balanced_piece():
    obj = _grid(4, 1)                                 # a flat quad grid strip: nothing is laid out balanced
    _edit(obj)
    op = _modal_on(obj, mode="FIT")
    assert op._result.balanced == 0
    params = {p.name: p for section in op._hud.param_sections for p in section.params}
    row = params["Balance (Ctrl + Wheel)"]
    assert row.is_visible() and not row.is_active()
    assert "no balanced piece" in row.value_text(), row.value_text()
    before = _uv_state(obj)
    assert op._modal(bpy.context, _KeyPress("WHEELUPMOUSE", ctrl=True)) == {"RUNNING_MODAL"}
    assert round(op.balance, 6) == 0.6 and _uv_state(obj) == before          # the value moves, the strip does not
    assert not row.is_active() and "no balanced piece" in row.value_text()
    op._modal(bpy.context, _KeyPress("ESC"))
    obj, _rings = _wide_l()                           # a wide patch: the row is live and shows the range
    op = _modal_on(obj, mode="FIT")
    row = {p.name: p for section in op._hud.param_sections for p in section.params}["Balance (Ctrl + Wheel)"]
    assert row.is_active() and row.value_text() == "0.50 · Least Stretch < > Even Texel"
    op._modal(bpy.context, _KeyPress("ESC"))


def test_b_jumps_balance_through_zero_half_and_one():
    obj, _rings = _wide_l()
    op = _modal_on(obj, mode="FIT")
    states = {}
    for expected in (1.0, 0.0, 0.5, 1.0):
        assert op._modal(bpy.context, _KeyPress("B")) == {"RUNNING_MODAL"}
        assert op.balance == expected, (op.balance, expected)
        states[expected] = _uv_state(obj)[0]
    assert states[1.0] != states[0.0]                                         # the wide strip follows each jump
    for start, expected in ((0.3, 0.5), (0.5, 1.0), (0.7, 1.0), (1.0, 0.0), (0.0, 0.5)):
        op.balance = start                                                    # the next value above, wrapping
        op._modal(bpy.context, _KeyPress("B"))
        assert op.balance == expected, (start, op.balance)
    op._modal(bpy.context, _KeyPress("ESC"))


def test_a_wheel_step_then_enter_equals_execute_with_the_same_balance():
    def made(confirm, timer):
        obj, _rings = _wide_l()
        if confirm:
            op = _modal_on(obj, mode="FIT")
            for _ in range(3):
                op._modal(bpy.context, _KeyPress("WHEELUPMOUSE", ctrl=True))
            assert round(op.balance, 6) == 0.8
            if timer:                                  # the window timer refines once the wheel has been still
                op._wheel_time = 0.0
                for _ in range(200):
                    op._modal(bpy.context, _KeyPress("TIMER"))
                from InteractionOps.utils import uv_stripe_balance_core
                assert uv_stripe_balance_core.pending() == 0
            assert op._modal(bpy.context, _KeyPress("RET")) == {"FINISHED"}
            return _uv_state(obj)[0]
        stand = _OperatorStandIn(mode="FIT", balance=0.8)
        assert stand.execute(bpy.context) == {"FINISHED"}, stand.reports
        return _uv_state(obj)[0]

    executed = made(False, False)
    assert _uv_close(made(True, False), executed)                  # Enter refines fully before it confirms
    assert _uv_close(made(True, True), executed)                   # the timer's slices reach the same result


# --- islands that split or wait for help ------------------------------------------------------------------------

def _forked_l_ledge(stem=3, arm=5):
    """An L profile (a flat ledge of two rows and the wall hanging from its inner edge, 3 rows of faces) along x:
    the first ``stem`` columns are one block; beyond them the three rows are three arms that share no vertex (the
    ledge splits along its middle line into two arms, the wall goes on as a third) but the stem's last vertices.
    Returns the object and the row (0 outer ledge, 1 inner ledge, 2 wall) of every face."""
    profile = [(1.0, 0.0), (0.5, 0.0), (0.0, 0.0), (0.0, -0.5)]        # (y, z) of the outer edge, middle line, fold, foot
    points, at, faces, rows = [], {}, [], []

    def vert(key, x, p):
        if key not in at:
            at[key] = len(points)
            points.append((float(x), *profile[p]))
        return at[key]

    for x in range(stem):
        for r in range(3):
            faces.append(tuple(vert(("stem", x + dx, r + dr), x + dx, r + dr) for dx, dr in ((0, 0), (1, 0), (1, 1), (0, 1))))
            rows.append(r)
    for r in range(3):
        for x in range(stem, stem + arm):
            def own(xx, p, r=r):
                return vert(("stem", xx, p) if xx == stem else ("arm", r, xx, p), xx, p)
            faces.append((own(x, r), own(x + 1, r), own(x + 1, r + 1), own(x, r + 1)))
            rows.append(r)
    return _object(points, faces), rows


def _face_u_range(obj, rows, row):
    bm = bmesh.from_edit_mesh(obj.data)
    layer = bm.loops.layers.uv.active
    us = [lp[layer].uv.x for f in bm.faces if rows[f.index] == row for lp in f.loops]
    return min(us), max(us)


def test_a_forked_l_ledge_with_a_slit_is_cut_and_the_active_face_picks_the_main_arm():
    firsts = {}
    for active_y, row in ((0.75, 0), (0.0, 2)):       # an active face on the outer ledge arm, then on the wall arm
        obj, rows = _forked_l_ledge()
        _edit(obj)
        _set_active(obj, (6.5, active_y))
        bm = bmesh.from_edit_mesh(obj.data)
        assert rows[bm.faces.active.index] == row
        stand = _OperatorStandIn(mode="FIT")
        assert stand.execute(bpy.context) == {"FINISHED"}, stand.reports       # an instant call: nothing is skipped
        assert not any("skipped" in r or "need the interactive" in r for r in stand.reports), stand.reports
        assert any("branches" in r for r in stand.reports), stand.reports
        result = stand._lay_out(bpy.context)
        assert result.done >= 2 and (result.skipped, result.help) == (0, [])     # every part its own strip
        assert len(result.split) == 1 and "branches" in result.split[0], result.split
        assert len(_selected_faces(obj)) == len(rows)
        assert all(abs(a) > 1e-9 for a in _face_areas(obj)), "a face has no UVs"
        active = bmesh.from_edit_mesh(obj.data).faces.active.index
        # Fit stacks the strips upward in V in strip order: the part with the active face (the main run) first
        firsts[row] = abs(_face_v_min(obj, active) - _all_v_min(obj)) < 1e-6
    assert firsts == {0: True, 2: True}, firsts


def test_a_seed_face_chooses_the_main_arm_too():
    obj, rows = _forked_l_ledge()
    _edit(obj)
    _set_active(obj, (6.5, 0.0))                      # the active face is on the wall arm ...
    bm = bmesh.from_edit_mesh(obj.data)
    seed = next(f.index for f in bm.faces if rows[f.index] == 0 and f.calc_center_median().x > 5.0)
    stand = _OperatorStandIn(mode="FIT", seed_faces=_json_picks({obj.name: [seed]}))
    assert stand.execute(bpy.context) == {"FINISHED"}
    active = bmesh.from_edit_mesh(obj.data).faces.active.index
    assert abs(_face_v_min(obj, seed) - _all_v_min(obj)) < 1e-6      # ... but the seed's part comes first
    assert _face_v_min(obj, active) > _all_v_min(obj) + 1e-6


def _face_v_min(obj, index):
    bm = bmesh.from_edit_mesh(obj.data)
    bm.faces.ensure_lookup_table()
    layer = bm.loops.layers.uv.active
    return min(lp[layer].uv.y for lp in bm.faces[index].loops)


def _all_v_min(obj):
    bm = bmesh.from_edit_mesh(obj.data)
    layer = bm.loops.layers.uv.active
    return min(lp[layer].uv.y for f in bm.faces if f.select for lp in f.loops)


def _picks(text):
    """The JSON a pick property holds as a dict; {} for the empty string."""
    import json
    return json.loads(text) if text else {}


def _json_picks(data):
    import json
    return json.dumps(data)


def _l_straight(cols=8):
    """The wide L patch straight (rows of equal length): a ledge from y = 1 to 0.8 and a wall hanging from it,
    2 faces wide, selected, in Edit Mode. Returns the object and its three rings of vertex indices."""
    profile = [(1.0, 0.0), (0.8, 0.0), (0.8, -0.2)]
    points, rings = [], []
    for y, z in profile:
        rings.append(list(range(len(points), len(points) + cols + 1)))
        points.extend((0.4 * i, y, z) for i in range(cols + 1))
    faces = [(rings[k][i], rings[k][i + 1], rings[k + 1][i + 1], rings[k + 1][i])
             for k in range(2) for i in range(cols)]
    obj = _object(points, faces)
    _edit(obj)
    return obj, rings


def _cut_through_the_middle(obj, rings, **props):
    """A modal on the wide L with the cross edge of its ledge in the middle cut by hand; returns the operator, the
    edge index and, per part (before the cut, after it), its (u range, v range)."""
    op = _modal_on(obj, mode="FIT", **props)
    assert op._result.done == 1 and op._result.split == []
    index = _edge_index(obj, (rings[0][4], rings[1][4]))              # a cross edge of the ledge, in the middle
    assert index in op._result.cuttable[obj.name]
    assert op._click_cut(bpy.context, obj, index) == "cut"
    assert _picks(op.island_cuts) == {obj.name: [index]}
    assert op._result.done == 2                                       # two parts, each its own strip
    assert len(op._result.split) == 1 and "by hand" in op._result.split[0], op._result.split
    bm = bmesh.from_edit_mesh(obj.data)
    layer = bm.loops.layers.uv.active
    left = set(range(4)) | {8 + i for i in range(4)}          # columns 0 .. 3 of both rows of faces
    ranges = []
    for side in (True, False):
        uvs = [lp[layer].uv for f in bm.faces if f.select and (f.index in left) == side for lp in f.loops]
        ranges.append(((min(p.x for p in uvs), max(p.x for p in uvs)), (min(p.y for p in uvs), max(p.y for p in uvs))))
    assert ranges[0][1][1] <= ranges[1][1][0] + 1e-6 or ranges[1][1][1] <= ranges[0][1][0] + 1e-6, ranges  # stacked
    assert all(a > 0 for a in _face_areas(obj))
    return op, index, ranges


def test_a_cut_by_hand_through_a_wide_l_makes_two_strips():
    obj, rings = _l_straight()
    op, index, ranges = _cut_through_the_middle(obj, rings)
    for (u0, u1), _v in ranges:                                       # both halves equally long: one texel density
        assert abs(u0) < 1e-6 and abs(u1 - ranges[0][0][1]) < 1e-6, ranges
    assert op._click_cut(bpy.context, obj, index) == "uncut"          # a second click removes the cut
    assert op.island_cuts == "" and op._result.split == []
    assert op._click_cut(bpy.context, obj, index) == "cut"
    assert op._modal(bpy.context, _KeyPress("ESC")) == {"CANCELLED"}
    assert op.island_cuts == ""                                       # cancel restores the pick


def test_a_cut_by_hand_through_a_wide_l_arc_gives_two_stacked_strips():
    # the arc's halves are two strips stacked in V at one texel density, at every Balance
    for balance in (0.0, 0.5, 1.0):
        obj, rings = _wide_l(cols=8)
        op, _index, ranges = _cut_through_the_middle(obj, rings, balance=balance)
        assert all(abs(u0) < 1e-6 for (u0, _u1), _v in ranges), (balance, ranges)
        op._modal(bpy.context, _KeyPress("ESC"))


def _chamfered_and_strip():
    """A 12 x 4 patch whose four corner cells are triangles (vertices 0 .. 64, the chamfered corners' own vertices
    unused): its boundary has eight corner candidates in four tight pairs, no concave vertex, so no rule reads it
    as a strip and it cannot be cut automatically, yet its four corner groups are clear: it waits for picked
    corners. Far below it a 4 x 1 strip (vertices 65 ..). Returns the object and the four corners of the patch
    as a strip (the inner vertex of each chamfer)."""
    cols, rows = 12, 4
    points = [(float(x), float(y), 0.0) for y in range(rows + 1) for x in range(cols + 1)]
    faces = []
    for y in range(rows):
        for x in range(cols):
            a, b, c, d = y * 13 + x, y * 13 + x + 1, (y + 1) * 13 + x + 1, (y + 1) * 13 + x
            corner = {(0, 0): (b, c, d), (cols - 1, 0): (a, c, d), (cols - 1, rows - 1): (a, b, d),
                      (0, rows - 1): (a, b, c)}
            faces.append(corner.get((x, y), (a, b, c, d)))
    points += [(float(x), -3.0 + y, 0.0) for y in range(2) for x in range(5)]
    faces += [(65 + x, 66 + x, 71 + x, 70 + x) for x in range(4)]
    return _object(points, faces), (1, 11, 63, 53)


def _help_island_qualifies(obj):
    """Whether the chamfered island of ``_chamfered_and_strip`` is one ``_helpable`` accepts and ``split_island``
    refuses (both cores called directly), with the reason it is refused for."""
    from InteractionOps.operators.mesh_uv_stripe import _helpable
    from InteractionOps.utils import uv_stripe_select_core, uv_stripe_split_core
    bm = bmesh.from_edit_mesh(obj.data)
    verts = {v.index: tuple(obj.matrix_world @ v.co) for f in bm.faces if f.select for v in f.verts}
    island = {f.index: tuple(v.index for v in f.verts) for f in bm.faces if f.select and f.index < 48}
    try:
        uv_stripe_select_core.strip_from_faces(verts, island)
    except ValueError as exc:
        reason = exc
    else:
        return False, "it reads as a strip"
    try:
        uv_stripe_split_core.split_island(verts, island, (), None, ())
    except ValueError:
        return _helpable(verts, island, reason), str(reason)
    return False, "it can be cut automatically"


def test_an_island_waiting_for_help_reports_asks_for_corners_and_lays_out_with_four():
    import json
    obj, corners = _chamfered_and_strip()
    _edit(obj)
    qualifies, reason = _help_island_qualifies(obj)
    assert qualifies, f"the test mesh no longer qualifies as an island waiting for help: {reason}"
    # an instant call lays the strip out and reports the island
    stand = _OperatorStandIn(mode="FIT")
    assert stand.execute(bpy.context) == {"FINISHED"}, stand.reports
    warning = [r for r in stand.reports if "need the interactive mode" in r]
    assert len(warning) == 1 and warning[0].startswith("UV Stripe: 1 island(s) need the interactive mode to pick "
                                                       "corners or cuts ("), stand.reports
    for co, uv in _corners(obj, lambda c: c.y < 0.0):             # the other island in the selection
        assert _close(uv.x, co.x / 4.0) and _close(uv.y, (co.y + 3.0) / 4.0), (co, uv)
    assert all(uv.length < 1e-9 for _co, uv in _corners(obj, lambda c: c.y > 0.0)), "the island was written to"
    # the modal starts with the island waiting for help
    _edit(obj)
    op = _OperatorStandIn(mode="FIT")
    assert op._start(bpy.context), op.reports
    op._build_overlays(None)
    assert len(op._result.help) == 1 and op._result.done == 1
    item = op._result.help[0]
    assert item.obj == obj.name and len(item.faces) == 48 and not item.picked
    op._hud.draw = op._help.draw = lambda *_args: None
    from types import SimpleNamespace
    op._draw_callback(SimpleNamespace(region_data=object()))
    assert op._hud._notes == [("Island 1 is no strip: Click four corners, or click an edge to cut the island into "
                               "strips", True)], op._hud._notes
    assert op._status_text().startswith("LMB boundary vertex: corner")
    for k, vertex in enumerate(corners):
        assert vertex in op._result.help[0].loop
        assert op._click_corner(bpy.context, obj.name, vertex) == "add"
        picked = json.loads(op.corner_picks)[obj.name]
        assert picked == list(corners[:k + 1])
        if k < 3:                                             # three corners are still no strip
            assert len(op._result.help) == 1 and len(op._result.help[0].picked) == k + 1
            op._draw_callback(SimpleNamespace(region_data=object()))
            assert op._hud._notes[0][0].startswith(f"Island 1 is no strip: Click {3 - k} more corner(s)"), op._hud._notes
    assert op._result.help == [] and op._result.done == 2          # the four corners lay the island out
    assert op._hud is not None
    assert all(a > 0 for a in _face_areas(obj, lambda c: c.y > 0.0))
    op._draw_callback(SimpleNamespace(region_data=object()))
    assert op._hud._notes == [("An island is read with the picked corners", False)], op._hud._notes
    assert json.loads(op.corner_picks) == {obj.name: list(corners)}
    confirmed = _uv_state(obj)
    assert op._modal(bpy.context, _KeyPress("RET")) == {"FINISHED"}
    assert _uv_state(obj) == confirmed
    # the picks are kept for the redo: execute with them lays the same UVs out, no warning
    obj, corners = _chamfered_and_strip()
    _edit(obj)
    redo = _OperatorStandIn(mode="FIT", corner_picks=json.dumps({obj.name: list(corners)}))
    assert redo.execute(bpy.context) == {"FINISHED"} and not any("interactive" in r for r in redo.reports)
    assert _uv_state(obj) == confirmed


def test_corner_clicks_through_the_modal_events_toggle_and_cancel_restores():
    import json
    obj, corners = _chamfered_and_strip()
    _edit(obj)
    op = _modal_on(obj, mode="FIT")
    target = {"vertex": corners[0]}
    op._hover_corner = lambda _context, _event: (obj.name, target["vertex"])      # a real cursor cannot hover headless
    assert op._modal(bpy.context, _KeyPress("LEFTMOUSE")) == {"RUNNING_MODAL"}
    assert json.loads(op.corner_picks) == {obj.name: [corners[0]]}
    assert op._modal(bpy.context, _KeyPress("LEFTMOUSE")) == {"RUNNING_MODAL"}          # again: the corner goes
    assert _picks(op.corner_picks).get(obj.name) in (None, [])
    target["vertex"] = 0                                                                # not on the island's boundary
    assert op._modal(bpy.context, _KeyPress("LEFTMOUSE")) == {"RUNNING_MODAL"}
    assert _picks(op.corner_picks).get(obj.name) in (None, [])
    for vertex in corners:
        target["vertex"] = vertex
        op._modal(bpy.context, _KeyPress("LEFTMOUSE"))
    assert op._result.help == []
    assert op._click_corner(bpy.context, obj.name, 2) is None                           # a fifth pick is refused
    assert op._modal(bpy.context, _KeyPress("ESC")) == {"CANCELLED"}
    assert op.corner_picks == ""


def test_a_disc_alone_still_cancels_the_modal():
    obj = _cap()
    _edit(obj)
    result = _OperatorStandIn(mode="FIT")._lay_out(bpy.context)
    assert (result.done, result.skipped, result.help) == (0, 1, [])         # refused, not waiting for help
    assert result.first_reason.startswith("not a strip"), result.first_reason
    op = _OperatorStandIn(mode="FIT")
    assert op._start(bpy.context) is False
    assert any("nothing laid out" in r for r in op.reports), op.reports
    try:
        assert _run(mode="FIT") == {"CANCELLED"}
    except RuntimeError as exc:
        assert "nothing laid out" in str(exc), exc


def test_a_disc_beside_an_island_waiting_for_help_is_skipped_while_the_modal_starts():
    obj, corners = _chamfered_and_strip()
    points, faces = _cap_parts(6, centre=(10.0, 10.0))
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    ids = [bm.verts.new(p) for p in points]
    for face in faces:
        bm.faces.new([ids[i] for i in face])
    bm.to_mesh(obj.data)
    bm.free()
    _edit(obj)
    op = _modal_on(obj, mode="FIT")
    assert len(op._result.help) == 1 and op._result.done == 1 and op._result.skipped == 1
    assert op._modal(bpy.context, _KeyPress("ESC")) == {"CANCELLED"}


# --- seed and guide faces ---------------------------------------------------------------------------------------

def _two_separate_strips():
    """Two 4 x 1 strips apart (faces 0 .. 3 at y = 0 .. 1, faces 4 .. 7 at y = 3 .. 4), all selected."""
    points = [(float(x), float(y), 0.0) for y in (0, 1, 3, 4) for x in range(5)]
    faces = [(5 * r + x, 5 * r + x + 1, 5 * r + x + 6, 5 * r + x + 5) for r in (0, 2) for x in range(4)]
    obj = _object(points, faces)
    _edit(obj)
    return obj


def test_alt_lmb_sets_one_seed_face_per_island_and_shift_alt_toggles_guide_faces():
    import json
    obj = _two_separate_strips()
    op = _modal_on(obj, mode="FIT")
    assert "Seed and Guide Faces" not in _shown(op)
    assert op._click_face(bpy.context, obj, 1, False) == "seed"
    assert json.loads(op.seed_faces) == {obj.name: [1]}
    assert "Seed and Guide Faces" in _shown(op)
    assert op._click_face(bpy.context, obj, 3, False) == "seed"            # a second seed in the island replaces it
    assert json.loads(op.seed_faces) == {obj.name: [3]}
    assert op._click_face(bpy.context, obj, 5, False) == "seed"            # the other island keeps its own
    assert json.loads(op.seed_faces) == {obj.name: [3, 5]}
    assert op._click_face(bpy.context, obj, 5, False) == "unseed"          # again on the seed removes it
    assert json.loads(op.seed_faces) == {obj.name: [3]}
    assert op._guide_count() == 1
    assert op._click_face(bpy.context, obj, 0, True) == "guide"
    assert op._click_face(bpy.context, obj, 3, True) == "guide"            # guide faces add up, also in one island
    assert json.loads(op.guide_faces) == {obj.name: [0, 3]}
    assert op._guide_count() == 3
    params = {p.name: p for section in op._hud.param_sections for p in section.params}
    assert params["Seed and Guide Faces"].value_text() == "3"
    assert op._click_face(bpy.context, obj, 0, True) == "unguide"
    assert json.loads(op.guide_faces) == {obj.name: [3]}
    # a seed face on an end of a strip starts it
    bm = bmesh.from_edit_mesh(obj.data)
    layer = bm.loops.layers.uv.active
    bm.faces.ensure_lookup_table()
    mean_u = lambda i: sum(lp[layer].uv.x for lp in bm.faces[i].loops) / 4.0     # noqa: E731
    assert mean_u(3) < mean_u(2) < mean_u(1) < mean_u(0)                  # the seed on an end face starts the strip
    assert mean_u(4) < mean_u(5) < mean_u(6) < mean_u(7)                  # the other island has no seed: unchanged
    assert op._modal(bpy.context, _KeyPress("ESC")) == {"CANCELLED"}
    assert op.seed_faces == "" and op.guide_faces == ""                    # cancel restores both picks


def test_alt_lmb_and_shift_alt_lmb_events_seed_and_guide_the_face_under_the_cursor():
    import json
    obj = _two_separate_strips()
    op = _modal_on(obj, mode="FIT")
    under = {"face": 6}
    op._face_under = lambda _context, _event: (obj, under["face"])          # a real cursor cannot hover headless
    assert op._modal(bpy.context, _KeyPress("LEFTMOUSE", alt=True)) == {"RUNNING_MODAL"}
    assert json.loads(op.seed_faces) == {obj.name: [6]}
    assert op._modal(bpy.context, _KeyPress("LEFTMOUSE", alt=True, shift=True)) == {"RUNNING_MODAL"}
    assert json.loads(op.guide_faces) == {obj.name: [6]} and json.loads(op.seed_faces) == {obj.name: [6]}
    assert op._modal(bpy.context, _KeyPress("LEFTMOUSE", alt=True, shift=True)) == {"RUNNING_MODAL"}
    assert op.guide_faces == ""                                             # again: the guide face goes
    op._face_under = lambda _context, _event: None                         # no face under the cursor: nothing
    seeds = op.seed_faces
    assert op._modal(bpy.context, _KeyPress("LEFTMOUSE", alt=True)) == {"RUNNING_MODAL"} and op.seed_faces == seeds
    assert op._modal(bpy.context, _KeyPress("LEFTMOUSE")) == {"RUNNING_MODAL"}     # a plain click on a face: nothing
    assert op.seed_faces == seeds
    op._modal(bpy.context, _KeyPress("ESC"))
    assert op.seed_faces == "" and op.guide_faces == ""


# --- round 2: Auto does not tear what lays out whole, hand cuts make no extra parts, discs are refused -----------

def _bent_arc(cols=8, inner=0.8, outer=1.0):
    """A flat one-face-wide arc of ``cols`` quads over a quarter turn."""
    points = [(r * math.cos(math.pi / 2 * i / cols), r * math.sin(math.pi / 2 * i / cols), 0.0)
              for r in (inner, outer) for i in range(cols + 1)]
    obj = _object(points, [(i, i + 1, cols + 2 + i, cols + 1 + i) for i in range(cols)])
    _edit(obj)
    return obj


def test_a_bent_arc_that_lays_out_whole_within_the_limit_is_not_torn():
    obj = _bent_arc()
    assert _run(mode="FIT") == {"FINISHED"}
    assert _uv_islands(obj) == 1 and not any(len(_vertex_us(obj, v)) > 1 for v in range(18))
    assert _worst_stretch(obj) <= 1.25, _worst_stretch(obj)
    assert all(a > 0 for a in _face_areas(obj))
    obj, _rings = _wide_l(cols=8)                    # the ledge and the wall of an arc (2 faces wide)
    assert _run(mode="FIT") == {"FINISHED"} and _uv_islands(obj) == 1
    assert _worst_stretch(obj) < 1.3                 # 1.263 by the honest measure: wide strips are balanced, not torn


def test_a_lengthwise_hand_cut_makes_two_parts_and_no_more():
    import json
    def flat():                                      # a flat 2-wide strip: the edge between its rows, mid-way
        obj = _grid(8, 2)
        _edit(obj)
        return obj, (12, 13)

    def arc():                                       # the arc: the fold line (the edge between ledge and wall)
        obj, rings = _wide_l(cols=8)
        return obj, (rings[1][3], rings[1][4])

    for build in (flat, arc):
        obj, pair = build()
        index = _edge_index(obj, pair)
        op = _modal_on(obj, mode="FIT")
        assert index in op._result.cuttable[obj.name]
        assert op._click_cut(bpy.context, obj, index) == "cut"
        assert json.loads(op.island_cuts) == {obj.name: [index]}
        # two parts, each its own strip; a half one face wide round the arc is torn at its bends like any strip
        done = op._result.done
        assert (done == 2 if build is flat else done >= 2) and len(op._result.split) == 1, (build.__name__, done,
                                                                                            op._result.split)
        assert "into 2 strips" in op._result.split[0], op._result.split     # no Auto tears inside the halves
        assert all(a > 0 for a in _face_areas(obj)) and _worst_stretch(obj) <= 1.3
        # each half keeps its own rails: it runs along U, never turned across (its v span far below its u span)
        bm = bmesh.from_edit_mesh(obj.data)
        layer = bm.loops.layers.uv.active
        us = [lp[layer].uv.x for f in bm.faces if f.select for lp in f.loops]
        vs = [lp[layer].uv.y for f in bm.faces if f.select for lp in f.loops]
        assert max(vs) - min(vs) < 0.5 * (max(us) - min(us)), (max(us) - min(us), max(vs) - min(vs))
        assert op._modal(bpy.context, _KeyPress("ESC")) == {"CANCELLED"}


def test_a_cross_cut_near_an_end_keeps_the_short_part_along_the_strip():
    # 24 columns over half a turn: a column is far shorter than the strip is wide, so the one-column part cut off
    # near an end would read across the strip; it takes its cut as an end and keeps the band's height
    import json
    obj, rings = _wide_l(cols=24)
    index = _edge_index(obj, (rings[0][1], rings[1][1]))            # the ledge's cross edge after column 0
    op = _modal_on(obj, mode="FIT")
    assert op._click_cut(bpy.context, obj, index) == "cut"
    assert json.loads(op.island_cuts) == {obj.name: [index]}
    assert "into 2 strips" in op._result.split[0], op._result.split
    bm = bmesh.from_edit_mesh(obj.data)
    layer = bm.loops.layers.uv.active
    first = {f.index for f in bm.faces if f.select and any(v.index in (rings[0][0], rings[2][0]) for v in f.verts)}
    spans = {}
    for side in (True, False):
        vs = [lp[layer].uv.y for f in bm.faces if f.select and (f.index in first) == side for lp in f.loops]
        spans[side] = max(vs) - min(vs)
    assert abs(spans[True] - spans[False]) <= 0.1 * spans[False], spans      # one band, the short part not turned
    assert op._modal(bpy.context, _KeyPress("ESC")) == {"CANCELLED"}


def _disc_with_ring(n=8):
    """An n-gon face of ``n`` vertices ringed by ``n`` quads: 9 faces, a disc (one boundary, no corner at all)."""
    inner = [(math.cos(2 * math.pi * i / n), math.sin(2 * math.pi * i / n), 0.0) for i in range(n)]
    outer = [(2 * x, 2 * y, 0.0) for x, y, _z in inner]
    faces = [tuple(range(n))] + [(i, (i + 1) % n, n + (i + 1) % n, n + i) for i in range(n)]
    return _object(inner + outer, faces)


def test_a_disc_of_a_ring_of_quads_round_an_ngon_is_refused():
    obj = _disc_with_ring()
    _edit(obj)
    assert len(_selected_faces(obj)) == 9
    result = _OperatorStandIn(mode="FIT")._lay_out(bpy.context)
    assert (result.done, result.skipped, result.help) == (0, 1, [])
    op = _OperatorStandIn(mode="FIT")
    assert op._start(bpy.context) is False                     # the modal does not start
    assert any("nothing laid out" in r for r in op.reports), op.reports
    stand = _OperatorStandIn(mode="FIT")
    assert stand.execute(bpy.context) == {"CANCELLED"}         # an instant call reports it skipped
    assert any("nothing laid out (not a strip" in r for r in stand.reports), stand.reports
    assert not any("interactive" in r for r in stand.reports)


# --- cuts and V by loop: LMB the loop (Ctrl / Alt + LMB one edge); V straightens ----------------------------

def _pick(op, obj, pair, align=False, single=False):
    """LMB on edge ``pair``: a cut in the normal state, with ``align`` a line to straighten (V); ``single`` the
    one edge (Ctrl + LMB for a cut, Alt + LMB for a line). The hover lookup stood in for, as in ``_click``; V
    picking stays on."""
    if not align:
        return _click(op, obj, pair, ctrl=single)
    index = _edge_index(obj, pair)
    op._hover_break = lambda _context, _event: (obj, index)
    if not op._align_picking:
        assert op._modal(bpy.context, _KeyPress("V")) == {"RUNNING_MODAL"}
    assert op._modal(bpy.context, _KeyPress("LEFTMOUSE", alt=single)) == {"RUNNING_MODAL"}
    assert op._align_picking
    return index


def _hover_on(op, obj, pair, single=False):
    """The hover the operator keeps over edge ``pair`` (None when a click there would change nothing); ``single``
    holds the key for the one edge (Alt while picking lines, Ctrl while cutting)."""
    index = _edge_index(obj, pair)
    op._hover_break = lambda _context, _event: (obj, index)
    move = _KeyPress("MOUSEMOVE", alt=single and op._align_picking, ctrl=single and not op._align_picking)
    move.value = "NOTHING"
    assert op._modal(bpy.context, move) == {"RUNNING_MODAL"}
    return op._hover


def _arc_band(n=12, radii=(1.0, 1.25, 1.5, 1.75), sweep=90.0):
    """A flat band round an arc, ``len(radii) - 1`` faces wide: vertex i * rows + r at angle i and radius r. Its
    rails (the inner and the outer arc) differ in length, so with one straight rail (Longer Side) the lines between
    the rails sag."""
    rows = len(radii)
    points = [(rad * math.cos(math.radians(sweep) * i / n), rad * math.sin(math.radians(sweep) * i / n), 0.0)
              for i in range(n + 1) for rad in radii]
    faces = [(i * rows + r, (i + 1) * rows + r, (i + 1) * rows + r + 1, i * rows + r + 1)
             for i in range(n) for r in range(rows - 1)]
    obj = _object(points, faces)
    _edit(obj)
    return obj, rows


def _spread(obj, vertices, axis):
    """How far the UVs of ``vertices`` spread in u (axis 0) or v (axis 1), over every selected corner."""
    bm = bmesh.from_edit_mesh(obj.data)
    layer = bm.loops.layers.uv.active
    values = [lp[layer].uv[axis] for f in bm.faces if f.select for lp in f.loops if lp.vert.index in vertices]
    return max(values) - min(values)


def test_lmb_cuts_a_cross_loop_of_a_wide_strip_and_a_second_click_mends_it():
    obj = _grid(4, 3)
    _edit(obj)
    op = _modal_on(obj, mode="FIT")
    loop = [(2, 7), (7, 12), (12, 17)]                       # across the strip at x = 2, rail to rail
    hover = _hover_on(op, obj, (7, 12))                      # the normal state previews the cut
    assert hover[:2] == (obj, _edge_index(obj, (7, 12))) and len(hover[2]) == 6 and not hover[3]   # the whole loop
    along = _hover_on(op, obj, (6, 7))                       # along the strip: the loop from end to end
    assert along is not None and len(along[2]) == 8 and not along[3]
    _pick(op, obj, (7, 12))
    assert sorted(_edges(op.island_cuts)[obj.name]) == sorted(_edge_index(obj, p) for p in loop)
    assert "into 2 strips" in op._result.split[0], op._result.split
    assert all(_torn_at(op, obj, p) for p in loop)           # drawn as a tear
    assert len(op._result.cut_lines) == 6                    # and as a cut made by hand
    assert _seams(obj) & _inner_edges(obj) == set(loop)
    assert _hover_on(op, obj, (2, 7))[3]                      # on the cut: a click takes it back
    _pick(op, obj, (2, 7))                                   # any edge of the cut mends it
    assert op.island_cuts == "" and not op._result.split and not op._result.cut_lines
    assert not _seams(obj) & _inner_edges(obj)
    op._finish(bpy.context)


def test_ctrl_lmb_cuts_one_edge():
    obj = _grid(4, 3)
    _edit(obj)
    op = _modal_on(obj, mode="FIT")
    index = _pick(op, obj, (7, 12), single=True)
    assert _edges(op.island_cuts) == {obj.name: [index]}     # the one edge, cut along its cross path
    assert "into 2 strips" in op._result.split[0], op._result.split
    _pick(op, obj, (7, 12), single=True)
    assert op.island_cuts == ""
    obj = _grid(4, 1)                                        # one face wide: LMB and Ctrl + LMB cut the cross edge
    _edit(obj)
    op = _modal_on(obj, mode="FIT")
    index = _pick(op, obj, (2, 7), single=True)
    assert _edges(op.manual_cuts) == {obj.name: [index]} and _uv_islands(obj) == 2
    _pick(op, obj, (2, 7))
    assert op.manual_cuts == "" and _uv_islands(obj) == 1
    op._finish(bpy.context)


def test_v_straightens_a_lengthwise_loop_and_a_cross_loop_under_longer_side():
    obj, rows = _arc_band()
    op = _modal_on(obj, mode="FIT", straight_sides="LONGER")
    middle = {i * rows + 1 for i in range(13)}                # the line beside the inner rail, end to end
    across = {3 * rows + r for r in range(rows)}             # the line across the band at column 3
    assert _spread(obj, middle, 1) > 1e-3 and _spread(obj, across, 0) > 1e-4
    _pick(op, obj, (5, 9), align=True)                      # LMB: the whole lengthwise line
    assert _spread(obj, middle, 1) < 1e-6, _spread(obj, middle, 1)
    assert [axis for axis, _e in _parse_lines(op)[obj.name]] == ["ALONG"]
    assert len(_parse_lines(op)[obj.name][0][1]) == 12 and op._straight_line_count() == 1
    assert len(op._result.straight_lines) == 24              # drawn while the operator runs
    _pick(op, obj, (13, 14), align=True)                     # a cross edge of column 3: the line across the band
    assert _spread(obj, across, 0) < 1e-6 and _spread(obj, middle, 1) < 1e-6
    assert [axis for axis, _e in _parse_lines(op)[obj.name]] == ["ALONG", "ACROSS"]
    assert _hover_on(op, obj, (12, 13), single=True)[3]          # an edge of a picked line: a click takes it back
    _pick(op, obj, (12, 13), align=True)                     # clicked again: the line is free again
    assert [axis for axis, _e in _parse_lines(op)[obj.name]] == ["ALONG"] and _spread(obj, across, 0) > 1e-4
    _pick(op, obj, (9, 13), align=True)
    assert op.straight_lines == "" and _spread(obj, middle, 1) > 1e-3 and not op._result.straight_lines
    op._finish(bpy.context)


def test_alt_lmb_in_v_straightens_one_edge():
    obj, rows = _arc_band()
    op = _modal_on(obj, mode="FIT", straight_sides="LONGER")
    assert _spread(obj, {5, 9}, 1) > 1e-4
    index = _pick(op, obj, (5, 9), align=True, single=True)     # an edge along the band: laid horizontal
    assert _parse_lines(op) == {obj.name: [("ALONG", [index])]} and _spread(obj, {5, 9}, 1) < 1e-6
    assert _spread(obj, {i * rows + 1 for i in range(13)}, 1) > 1e-4    # the rest of its line stays free
    op._finish(bpy.context)


def test_a_hover_that_would_change_nothing_is_not_drawn():
    obj = _grid(4, 3)
    _edit(obj)
    op = _modal_on(obj, mode="FIT")                          # Both on a flat patch: every line straight already
    op._modal(bpy.context, _KeyPress("V"))
    for pair in ((6, 7), (7, 12), (0, 1), (0, 5)):
        assert _hover_on(op, obj, pair) is None and _hover_on(op, obj, pair, single=True) is None, pair
        _pick(op, obj, pair, align=True)
        assert op.straight_lines == "", pair
    op._finish(bpy.context)


def test_v_straightens_the_middle_line_of_a_band_with_one_straight_rail():
    # A synthetic band with one straight rail (Longer Side): the middle lines sag. A V pick of a middle line lays it
    # straight and the rail stays straight; a hover is judged on the layout laid out.
    import time
    obj, rows = _arc_band(n=24, sweep=120.0)                          # 72 faces
    op = _modal_on(obj, mode="FIT", straight_sides="LONGER")    # one straight rail: the middle lines sag
    middle = {i * rows + 2 for i in range(25)}
    before = (_spread(obj, middle, 1), _worst_stretch(obj))
    assert before[0] > 1e-3
    op._modal(bpy.context, _KeyPress("V"))
    rails = [(0, rows), (rows - 1, 2 * rows - 1)]           # the first edge of the inner and of the outer rail
    hovers = [_hover_on(op, obj, pair) for pair in rails]
    assert sum(h is None for h in hovers) == 1, hovers        # the rail kept straight: nothing to change
    _pick(op, obj, (2, 2 + rows), align=True)
    op._refine(bpy.context, float("inf"))
    after = (_spread(obj, middle, 1), _worst_stretch(obj))
    assert after[0] < 1e-6, after
    print(f"  middle line v spread {before[0]:.2e} -> {after[0]:.2e}, worst stretch {before[1]:.3f} -> {after[1]:.3f}")
    steps = []
    for _step in range(4):                                   # Ctrl + Wheel with the picked line: the warm solve
        start = time.perf_counter()
        assert op._modal(bpy.context, _KeyPress("WHEELDOWNMOUSE", ctrl=True)) == {"RUNNING_MODAL"}
        steps.append(time.perf_counter() - start)
        assert _spread(obj, middle, 1) < 1e-6
    print("  Ctrl + Wheel steps with a picked line: " + ", ".join(f"{s:.3f}s" for s in steps))
    assert max(steps) < 0.5, steps
    op._finish(bpy.context)


def test_picks_survive_the_redo_and_confirm_equals_execute():
    def made(confirm):
        obj, rows = _arc_band()
        if confirm:
            op = _modal_on(obj, mode="FIT", straight_sides="LONGER")
            _pick(op, obj, (5, 9), align=True)
            _pick(op, obj, (13, 14), align=True)
            _pick(op, obj, (25, 26))                             # and a cut across the band at column 6
            assert op._modal(bpy.context, _KeyPress("RET")) == {"FINISHED"}, op.reports
            return _uv_state(obj), _edges(op.straight_lines), _edges(op.island_cuts)      # kept for redo
        named = [json.dumps({obj.name: picks}, sort_keys=True) for picks in (lines, cuts)]   # this object's name
        stand = _OperatorStandIn(mode="FIT", straight_sides="LONGER", straight_lines=named[0], island_cuts=named[1])
        assert stand.execute(bpy.context) == {"FINISHED"}
        return _uv_state(obj), _edges(stand.straight_lines), _edges(stand.island_cuts)

    import json
    confirmed = made(True)
    (lines,), (cuts,) = confirmed[1].values(), confirmed[2].values()
    assert lines and cuts
    executed = made(False)
    assert executed[0] == confirmed[0]
    assert list(executed[1].values()) == [lines] and list(executed[2].values()) == [cuts]
    rna = bpy.ops.iops.mesh_uv_stripe.get_rna_type().properties
    assert rna["straight_lines"].is_hidden and rna["straight_lines"].is_skip_save   # a new run starts empty


def _mixed_band(**kwargs):
    """``uv_stripe_fixtures.mixed_band`` as an object in Edit Mode, every face selected."""
    from uv_stripe_fixtures import mixed_band
    verts, faces = mixed_band(**kwargs)
    obj = _object([verts[i] for i in range(len(verts))], [faces[k] for k in sorted(faces)])
    _edit(obj)
    return obj


def test_one_lmb_straightens_a_line_through_triangles_and_ngons():
    obj = _mixed_band(sweep=90.0)
    op = _modal_on(obj, mode="FIT", straight_sides="LONGER")   # one straight rail
    middle = {i * 4 + 1 for i in range(13)}                   # through two triangles and a hexagon
    assert _spread(obj, middle, 1) > 1e-3
    op._modal(bpy.context, _KeyPress("V"))
    hover = _hover_on(op, obj, (21, 25))
    assert hover is not None and len(hover[2]) == 24          # the whole line lights up, all 12 edges
    _pick(op, obj, (21, 25), align=True)
    assert _spread(obj, middle, 1) < 1e-6 and len(_parse_lines(op)[obj.name][0][1]) == 12
    assert any(side.straight for (_n, _p, name), side in op._result.sides.items() if name in ("near", "far"))
    op._finish(bpy.context)


def test_lmb_offers_only_full_cuts_that_lay_out():
    obj = _mixed_band(sweep=90.0)                            # with a triangle fan on a rail near the end
    op = _modal_on(obj, mode="FIT")
    offered = {}
    for index in range(len(obj.data.edges)):
        target = op._pick_target(obj.name, index)
        if target is not None:
            offered.setdefault(tuple(sorted(target[0])), index)
    assert any(len(loop) == 3 for loop in offered), offered                # across: side to side
    assert any(len(loop) > 3 for loop in offered), offered                 # and along the strip, end to end
    bm = bmesh.from_edit_mesh(obj.data)
    bm.edges.ensure_lookup_table()
    pairs = {loop: tuple(sorted(v.index for v in bm.edges[index].verts)) for loop, index in offered.items()}
    for loop, pair in pairs.items():
        _pick(op, obj, pair)
        assert op._result.done == 2 and not op._result.help, (loop, op._result.first_reason)
        assert len(op._result.cut_lines) == 2 * len(loop) and "into 2 strips" in op._result.split[0], loop
        _pick(op, obj, pair)
        assert op.island_cuts == "", loop
    op._finish(bpy.context)


def test_a_v_pick_never_loosens_the_rails():
    obj = _mixed_band(sweep=90.0)
    op = _modal_on(obj, mode="FIT", straight_sides="LONGER")
    near = [name for (_o, _n, name), side in op._result.sides.items() if name in ("near", "far") and side.straight]
    assert len(near) == 1 and op._result.unfolded == 0        # one straight rail
    op._modal(bpy.context, _KeyPress("V"))
    for pair in ((13, 14), (29, 30)):                        # lines across the band
        _pick(op, obj, pair, align=True)
        kept = [name for (_o, _n, name), side in op._result.sides.items()
                if name in ("near", "far") and side.straight]
        assert near[0] in kept and op._result.unfolded == 0, (pair, kept)
        assert not op._align_applies()                       # a balanced piece: no Align row
    op._finish(bpy.context)


def test_a_pick_the_layout_cannot_keep_is_not_offered_nor_stored():
    obj = _mixed_band(rounded_end=True)
    op = _modal_on(obj, mode="FIT")
    op._modal(bpy.context, _KeyPress("V"))
    for pair in ((1, 2), (0, 1)):                            # the bulging end: two real corners on it
        assert _hover_on(op, obj, pair) is None, pair
        _pick(op, obj, pair, align=True)
        assert op.straight_lines == "", pair
    op._finish(bpy.context)


def test_removing_the_last_align_line_under_none_restores_align():
    obj = _shape_strip()
    op = _modal_on(obj, mode="FIT", **_shape_props(obj))
    assert op.shape_align == "AUTO"
    _click_align(op, obj, (4, 5))
    assert op.shape_align == "PICKED" and op.align_edges
    _click_align(op, obj, (4, 5))                            # the line and its align edge go: Align as it was
    assert op.straight_lines == "" and op.align_edges == "" and op.shape_align == "AUTO"
    op._finish(bpy.context)


def test_the_default_stands_a_wide_trim_strips_end_lines_upright():
    # A synthetic stand-in for a user's trim piece: wide, tapering, a chamfered corner and a notch in a rail. The
    # default Ends (Upright Where Cheap) stands each end's own line upright, the chamfer and the notch keep their
    # shape, both rails stay straight; Slanted keeps the slant; a strip one face wide keeps its slant either way.
    from uv_stripe_fixtures import trim_strip
    verts, faces = trim_strip()
    for ends in ("AUTO", "SLANTED"):
        obj = _object([verts[i] for i in range(len(verts))], [faces[k] for k in sorted(faces)])
        _edit(obj)
        assert bpy.ops.iops.mesh_uv_stripe(mode="FIT", ends=ends, split_at_seams=False, offset_axis="NONE") \
            == {"FINISHED"}
        upright = [_spread(obj, line, 0) for line in ({9, 18, 27}, {8, 17, 26, 35})]
        if ends == "AUTO":
            assert max(upright) < 1e-6, upright
            assert _spread(obj, {0, 9}, 0) > 0.05                         # the chamfer keeps its slant
            assert _spread(obj, set(range(9)), 1) < 1e-6                  # the near rail straight
            assert _spread(obj, {27, 28, 29, 32, 33, 34, 35}, 1) < 1e-6   # the far rail straight but its notch
            assert _spread(obj, {27, 30}, 1) > 0.01                       # which keeps its depth
            assert _worst_stretch(obj) < 1.25
        else:
            assert min(upright) > 1e-3, upright
    obj = _polyline([0, 20, 0])                                          # one face wide: the slant either way
    _edit(obj)
    assert _run(mode="FIT", ends="AUTO") == {"FINISHED"}
    auto = _uv_state(obj)
    assert _run(mode="FIT", ends="SLANTED") == {"FINISHED"}
    assert _uv_state(obj) == auto


def test_old_last_used_slanted_ends_migrate_once_to_upright_where_cheap():
    from InteractionOps.operators.uv_stripe_bridge import SETTINGS_VERSION, StripeSettings
    wm = bpy.context.window_manager
    last = wm.operator_properties_last("iops.mesh_uv_stripe")
    try:
        last.ends = "SLANTED"                                # stored by an older version: no settings version
        last.property_unset("settings_version")
        assert StripeSettings.from_last(bpy.context).ends == "AUTO"      # Inset and Edge Slide read it so
        assert last.ends == "AUTO" and last.is_property_set("settings_version")
        assert last.settings_version == SETTINGS_VERSION
        last.ends = "SLANTED"                                # a later explicit choice of Slanted sticks
        assert StripeSettings.from_last(bpy.context).ends == "SLANTED"
        last.property_unset("settings_version")
        last.ends = "BOTH"                                   # any other old value stays as it was
        assert StripeSettings.from_last(bpy.context).ends == "BOTH" and last.settings_version == SETTINGS_VERSION
        # invoke (a key, the menu) runs the same migration on the operator's own properties, filled from the last-used
        # ones; a script call in the background neither fills nor stores last-used values, so it is not run here
    finally:
        last = wm.operator_properties_last("iops.mesh_uv_stripe")
        last.ends = "AUTO"


def _parse_lines(op):
    """The straight lines ``op`` holds as {object name: [(axis, edge indices)]}, without the face of the piece each
    was picked on."""
    from InteractionOps.operators.mesh_uv_stripe import _parse_lines as parse
    return {name: [(axis, edges) for axis, edges, _face in lines] for name, lines in parse(op.straight_lines).items()}


# --- cuts add up on every piece kind; what a click changes is shown before it ----------------------------------

def _cut_state(op):
    return {prop: _edges(getattr(op, prop)) for prop in ("manual_cuts", "island_cuts", "cup_breaks")
            if getattr(op, prop)}


def _points(points):
    return {tuple(round(c, 6) for c in p) for p in points}


def _cut_edges(op):
    return {i for listed in _cut_state(op).values() for indices in listed.values() for i in indices}


def test_lmb_cuts_add_up_on_every_piece_kind_and_a_click_takes_back_one():
    def grid(nx, ny):
        def build():
            obj = _grid(nx, ny)
            _edit(obj)
            return obj
        return build

    def ring():
        obj = _annulus()
        _edit(obj)
        return obj

    def wide_l():
        return _wide_l(cols=8)[0]

    def tee():
        obj = _grid(3, 2, keep={(0, 0), (1, 0), (2, 0), (1, 1)})
        _edit(obj)
        return obj

    # (piece kind, builder, the loops cut one after the other, islands after each, the loop clicked again (on
    # another edge of it where it has more), islands after it); a closed ring's first cut opens it (one island),
    # every further cut adds an island
    cases = [
        ("open strip one face wide", grid(6, 1), [(2, 9), (3, 10), (4, 11)], [2, 3, 4], (3, 10), 3),
        ("open strip several faces wide", grid(8, 3), [(2, 11), (4, 13), (6, 15)], [2, 3, 4], (13, 22), 3),
        ("closed ring one face wide", ring, [(3, 11), (5, 13), (7, 15)], [1, 2, 3], (5, 13), 2),
        ("closed band several faces wide", _wide_band, [(5, 29), (11, 35), (17, 41)], [1, 2, 3], (35, 59), 2),
        ("wide arc", wide_l, [(2, 11), (4, 13), (6, 15)], [2, 3, 4], (4, 13), 3),
        ("island cut at its junction", tee, [(1, 5), (2, 6)], [3, 4], (1, 5), 3),
    ]
    for kind, build, loops, counts, again, after in cases:
        obj = build()
        op = _modal_on(obj, mode="FIT")
        for pair, count in zip(loops, counts):
            assert not _hover_on(op, obj, pair)[3], (kind, pair)            # a new cut, not a take-back
            before = _cut_edges(op)
            _click(op, obj, pair)
            assert _uv_islands(obj) == count and before < _cut_edges(op), (kind, pair, _cut_state(op))
        made = _cut_edges(op)
        assert all(_hover_on(op, obj, pair)[3] for pair in loops), kind      # every cut: a click takes it back
        taken = _points(_hover_on(op, obj, again)[2])
        _click(op, obj, again)
        assert _uv_islands(obj) == after and _cut_edges(op) < made, (kind, _cut_state(op))
        for pair in loops:                                                  # the others stay cut
            hover = _hover_on(op, obj, pair)
            assert hover[3] != (_points(hover[2]) == taken), (kind, pair)
        op._finish(bpy.context)


def test_near_an_edge_lmb_cuts_away_from_it_selects_and_the_hover_shows_what_it_acts_on():
    from InteractionOps.ui.draw import Role
    obj = _taper_strip()
    op = _modal_on(obj, mode="FIT")
    cross = min(op._result.cross[obj.name])
    op._face_under = lambda _context, _event: (obj, 0)
    op._hover_break = lambda _context, _event: None                         # away from the edges: the piece
    move = _KeyPress("MOUSEMOVE")
    move.value = "NOTHING"
    op._modal(bpy.context, move)
    assert op._face_hover == (obj, 0) and op._hover is None and op._face_outline
    kinds = [(role, kind) for _points, role, kind in op._view_layers() if kind != "line"]
    assert kinds == [(Role.ACTIVE_LINE, "piece")], kinds
    laid = _uv_state(obj)
    op._modal(bpy.context, _KeyPress("LEFTMOUSE"))                          # selected, nothing cut
    assert op._selected_pieces() and op.manual_cuts == "" and op.island_cuts == "" and _uv_state(obj) == laid
    kinds = [(role, kind) for _points, role, kind in op._view_layers() if kind != "line"]
    assert kinds == [(Role.ACTIVE_LINE, "selected"), (Role.ACTIVE_LINE, "piece")], kinds
    op._hover_break = lambda _context, _event: (obj, cross)                 # near an edge: the cut under it
    op._modal(bpy.context, move)
    assert op._face_hover is None and op._hover is not None and op._hover_outline
    kinds = [(role, kind) for _points, role, kind in op._view_layers() if kind != "line"]
    assert kinds == [(Role.ACTIVE_LINE, "selected"), (Role.ACTIVE_LINE, "piece"), (Role.PREVIEW_LINE, "hover")]
    op._modal(bpy.context, _KeyPress("LEFTMOUSE", shift=True))              # Shift never cuts: it toggles
    assert op.manual_cuts == "" and op._selected_pieces() == []
    op._modal(bpy.context, _KeyPress("LEFTMOUSE"))
    assert op.manual_cuts != ""
    op._modal(bpy.context, move)
    kinds = [(role, kind) for _points, role, kind in op._view_layers() if kind != "line"]
    assert kinds[-1] == (Role.LOCKED_LINE, "hover"), kinds                  # a click there takes the cut back
    op._hover_break = lambda _context, _event: None                         # over nothing: no highlight at all
    op._face_under = lambda _context, _event: None
    op._modal(bpy.context, move)
    assert [kind for _p, _r, kind in op._view_layers() if kind != "line"] == []
    op._finish(bpy.context)


def test_the_lines_are_drawn_in_the_colours_of_what_they_are():
    from InteractionOps.ui.draw import Role
    obj, _rows = _arc_band()
    op = _modal_on(obj, mode="FIT", straight_sides="LONGER")
    _pick(op, obj, (21, 25), align=True)                                    # a line straightened
    _click(op, obj, (25, 26))                                               # and a cut
    roles = {}
    for points, role, kind in op._view_layers():
        roles.setdefault(role, []).append((kind, len(points)))
    assert op._result.straight_lines and ("line", len(op._result.straight_lines)) in roles[Role.ERROR_LINE]
    assert op._result.cut_lines and ("line", len(op._result.cut_lines)) in roles[Role.PREVIEW_LINE]
    assert ("line", len(op._result.tears)) in roles[Role.PREVIEW_LINE]       # the tears are cuts too
    op._modal(bpy.context, _KeyPress("V"))
    hover = _hover_on(op, obj, (9, 10))                                     # a line across to straighten
    assert hover is not None and hover[4] is not None
    assert [role for _p, role, kind in op._view_layers() if kind == "hover"] == [Role.ERROR_LINE]
    op._finish(bpy.context)


def test_a_line_the_layout_cannot_keep_is_refused_with_a_warning():
    from InteractionOps.operators.mesh_uv_stripe import REFUSED_LINE
    obj, _rows = _arc_band()
    op = _modal_on(obj, mode="FIT", straight_sides="LONGER")
    op._line_kept = lambda *_args: False                                    # stands in for a fold or a squash
    _pick(op, obj, (21, 25), align=True)
    assert op.straight_lines == "" and REFUSED_LINE in op.reports, op.reports
    assert _hover_on(op, obj, (21, 25)) is None                             # not offered again
    op._finish(bpy.context)


def test_the_view_draws_the_hover_wide_and_the_selection_opaque():
    # no GPU in the background: the primitives are stood in for, everything up to them runs as in the viewport
    from types import SimpleNamespace

    from InteractionOps.operators import mesh_uv_stripe as module
    from InteractionOps.ui.draw import Role, get_theme
    obj = _grid(4, 1)
    _edit(obj)
    op = _modal_on(obj, mode="FIT")
    _hover_on(op, obj, (2, 7))
    calls = []

    def edges_world(points, role=None, color=None, width=None, theme=None, context=None):
        th = theme if theme is not None else get_theme(context)
        calls.append((role, color, th.width(width) if width else th.line_width_for(role)))

    real = module.draw
    module.draw = SimpleNamespace(edges_world=edges_world, points_world=lambda *_a, **_k: None)
    try:
        op._draw_view_callback(bpy.context)
    finally:
        module.draw = real
    theme = get_theme(bpy.context)
    hover = calls[-1]
    assert hover[0] is None and hover[1][:3] == theme.color_for(Role.PREVIEW_LINE)[:3] and hover[1][3] >= 0.9
    assert hover[2] == theme.line_width_for(Role.PREVIEW_LINE)             # the theme's own width, not widened
    piece = calls[-2]
    assert piece[1][:3] == theme.color_for(Role.ACTIVE_LINE)[:3] and piece[1][3] >= 0.9
    assert piece[2] == theme.width("default")
    assert max(width for _role, _c, width in calls) <= max(theme.line_widths.values())    # nothing widened
    op._finish(bpy.context)


def _fan_band():
    """``uv_stripe_fixtures.fan_band`` (three rows round an arc, the outer one a fan of quads and triangles with one
    pentagon) as an object in Edit Mode, every face selected; returns it and its edges across the strip at every
    inner column (from the inner rail out) as vertex-id pairs."""
    from uv_stripe_fixtures import fan_band
    verts, faces = fan_band()
    obj = _object([verts[i] for i in range(len(verts))], [faces[k] for k in sorted(faces)])
    _edit(obj)
    n = 8
    across = {i: [(i, 9 + i), (9 + i, 18 + i), (18 + i, 27 + 2 * i)] for i in range(1, n)}
    return obj, across


def test_a_cut_loop_runs_through_triangles_and_ngons_from_rail_to_rail():
    obj, across = _fan_band()
    op = _modal_on(obj, mode="FIT")
    offered, missing = 0, []
    for i, pairs in across.items():
        loop = {_edge_index(obj, p) for p in pairs}
        for pair in pairs:
            hover = _hover_on(op, obj, pair)
            if hover is not None and op._pick_target(obj.name, hover[1])[0] and \
                    set(op._pick_target(obj.name, hover[1])[0]) == loop:
                offered += 1
            else:
                missing.append(pair)
    print(f"  fan band: {offered} of {offered + len(missing)} edges across offer the rail-to-rail loop")
    assert not missing, missing                                            # every edge across, also by the fan
    for pair in ((10, 11), (19, 20)):                                      # lengthwise: a loop along the strip
        hover = _hover_on(op, obj, pair)
        assert hover is not None and len(hover[2]) == 2 * 8, (pair, hover and len(hover[2]))
    assert _hover_on(op, obj, (31, 32)) is None                            # a rail edge is no cut
    _click(op, obj, across[2][2])                                          # cut on its fan edge
    _click(op, obj, across[6][0])                                          # cut on its inner-rail edge
    assert _uv_islands(obj) == 3 and op._result.done == 3, (op._result.done, op._result.split)
    assert set(_edges(op.island_cuts)[obj.name]) == {_edge_index(obj, p) for p in across[2] + across[6]}
    assert all(_torn_at(op, obj, p) for p in across[2] + across[6])
    assert all(_hover_on(op, obj, p)[3] for p in across[2])                # any edge of a cut takes it back
    _click(op, obj, across[2][1])                                          # the whole cut, the other stays
    assert _uv_islands(obj) == 2 and set(_edges(op.island_cuts)[obj.name]) == {_edge_index(obj, p)
                                                                              for p in across[6]}
    op._finish(bpy.context)



def test_a_cut_made_after_a_piece_shape_keeps_it_on_the_pieces_holding_its_faces():
    obj = _grid(6, 2)
    _edit(obj)
    op = _modal_on(obj, mode="FIT")
    _select(op, obj, 0)
    for _ in range(3):
        op._modal(bpy.context, _KeyPress("Q"))                              # None for this piece: unfolded
    assert op._result.unfolded == 1 and op._shape_text("SIDES") == "None · 1 selected"
    _click(op, obj, (3, 10))                                                # a cut across: two pieces
    assert op._result.done == 2 and op._result.unfolded == 2               # both hold faces the shape was set on
    assert op.straight_sides == "BOTH" and op._shape_text("SIDES") == "None · 1 selected"
    op._finish(bpy.context)


def test_confirm_after_piece_shapes_equals_execute():
    def made(confirm, kept=""):
        obj = _two_tapers()
        if confirm:
            op = _modal_on(obj, mode="FIT")
            _select(op, obj, 0)
            op._modal(bpy.context, _KeyPress("Q"))
            op._modal(bpy.context, _KeyPress("W"))
            assert op._modal(bpy.context, _KeyPress("RET")) == {"FINISHED"}
            return _uv_state(obj), op.piece_shapes
        stand = _OperatorStandIn(mode="FIT", piece_shapes=_rename(kept, obj.name))
        assert stand.execute(bpy.context) == {"FINISHED"}
        return _uv_state(obj), stand.piece_shapes

    confirmed, kept = made(True)
    executed, _given = made(False, kept)
    assert confirmed == executed


def _rename(text, name):
    """``piece_shapes`` (JSON) with its one object's entry under ``name``."""
    import json
    data = json.loads(text)
    return json.dumps({name: next(iter(data.values()))})


TESTS = [
    test_a_cut_made_after_a_piece_shape_keeps_it_on_the_pieces_holding_its_faces,
    test_confirm_after_piece_shapes_equals_execute,
    test_a_cut_loop_runs_through_triangles_and_ngons_from_rail_to_rail,
    test_the_view_draws_the_hover_wide_and_the_selection_opaque,
    test_lmb_cuts_add_up_on_every_piece_kind_and_a_click_takes_back_one,
    test_near_an_edge_lmb_cuts_away_from_it_selects_and_the_hover_shows_what_it_acts_on,
    test_the_lines_are_drawn_in_the_colours_of_what_they_are,
    test_a_line_the_layout_cannot_keep_is_refused_with_a_warning,
    test_fit_straight_strip,
    test_in_place_keeps_centre_and_density,
    test_in_place_on_a_scaled_object_keeps_density,
    test_two_strips_stack_in_fit_with_one_density,
    test_stack_centres_every_strip_on_the_middle_at_the_fit_size,
    test_mark_seams_match_the_pieces,
    test_split_at_seams_tears_the_strip_and_keeps_its_seam,
    test_ring_with_one_seam_is_cut_there,
    test_auto_tears_a_sharp_bend_and_keeps_a_gentle_one_whole,
    test_ngon_strip_is_torn_only_as_far_as_the_stretch_limit_asks,
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
    test_a_branching_island_is_cut_and_laid_out_with_the_other,
    test_nothing_selected_cancels,
    test_only_rejected_cancels,
    test_mesh_without_uv_gets_one,
    test_modal_keys_toggle_their_options_and_the_uvs_follow,
    test_modal_alt_wheel_changes_the_stretch_limit_under_any_straight_sides,
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
    test_fit_to_active_height_is_across_the_strip_and_width_along_it_in_both_orientations,
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
    test_lmb_cuts_in_the_normal_state_with_no_pick_mode,
    test_set_break_relays_out,
    test_lmb_sets_the_hovered_break,
    test_second_break_on_the_same_ring_replaces_the_first,
    test_breaks_on_two_rings_are_both_kept,
    test_break_survives_option_changes,
    test_r_changes_seed_and_c_does_nothing,
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
    test_execute_lays_out_at_once_and_invoke_always_starts_the_modal,
    test_invoke_starts_the_modal_and_esc_restores,
    test_more_options_property_and_no_interactive_flag,
    test_tab_toggles_more_options_and_the_hud_rows,
    test_keys_of_hidden_rows_work_while_collapsed,
    test_the_interactive_entry_is_folded_into_uv_stripe,
    test_the_stepped_strip_with_the_users_defaults,
    test_g_cycles_the_align_values,
    test_v_and_lmb_store_the_align_edge_and_keep_picking,
    test_v_picking_takes_lmb_and_esc_rmb_or_v_leave_it,
    test_cancel_restores_align_and_its_edges,
    test_confirm_after_align_picks_equals_execute,
    test_align_row_shows_only_where_a_piece_is_unfolded_at_its_real_shape,
    test_other_layouts_do_not_depend_on_align,
    test_align_is_no_shared_setting,
    test_q_and_w_on_a_selected_piece_change_only_that_piece,
    test_w_on_a_selected_one_face_wide_strip_stands_its_ends_upright,
    test_piece_shapes_are_kept_for_redo_and_a_fresh_run_starts_from_the_defaults,
    test_lmb_over_nothing_changes_nothing_and_only_enter_confirms,
    test_e_and_a_keep_the_piece_shapes,
    test_esc_restores_the_piece_shapes_and_the_uvs,
    test_hud_rows_follow_the_state,
    test_v_picking_shows_its_line_in_the_hud_header,
    test_help_starts_collapsed,
    test_shape_settings_are_shared_and_side_picks_are_not,
    test_every_shape_combination_finishes_on_the_bent_ngons_and_a_wide_patch,
    test_old_last_used_values_of_the_removed_properties_are_ignored,
    test_double_click_selects_and_cuts_like_a_press,
    test_a_rectangular_frame_is_four_islands_of_one_face,
    test_lmb_cuts_only_within_the_pick_distance_of_an_edge,
    test_the_wheel_changes_balance_and_stretch_limit_in_every_state,
    test_the_plain_wheel_zooms_the_view_in_every_state,
    test_the_wheel_clamps_balance_between_zero_and_one,
    test_the_balance_row_is_inactive_without_a_balanced_piece,
    test_b_jumps_balance_through_zero_half_and_one,
    test_a_wheel_step_then_enter_equals_execute_with_the_same_balance,
    test_a_forked_l_ledge_with_a_slit_is_cut_and_the_active_face_picks_the_main_arm,
    test_a_seed_face_chooses_the_main_arm_too,
    test_a_cut_by_hand_through_a_wide_l_makes_two_strips,
    test_a_cut_by_hand_through_a_wide_l_arc_gives_two_stacked_strips,
    test_an_island_waiting_for_help_reports_asks_for_corners_and_lays_out_with_four,
    test_corner_clicks_through_the_modal_events_toggle_and_cancel_restores,
    test_a_disc_alone_still_cancels_the_modal,
    test_a_disc_beside_an_island_waiting_for_help_is_skipped_while_the_modal_starts,
    test_alt_lmb_sets_one_seed_face_per_island_and_shift_alt_toggles_guide_faces,
    test_alt_lmb_and_shift_alt_lmb_events_seed_and_guide_the_face_under_the_cursor,
    test_a_bent_arc_that_lays_out_whole_within_the_limit_is_not_torn,
    test_a_lengthwise_hand_cut_makes_two_parts_and_no_more,
    test_a_cross_cut_near_an_end_keeps_the_short_part_along_the_strip,
    test_a_disc_of_a_ring_of_quads_round_an_ngon_is_refused,
    test_lmb_cuts_a_cross_loop_of_a_wide_strip_and_a_second_click_mends_it,
    test_ctrl_lmb_cuts_one_edge,
    test_v_straightens_a_lengthwise_loop_and_a_cross_loop_under_longer_side,
    test_alt_lmb_in_v_straightens_one_edge,
    test_a_hover_that_would_change_nothing_is_not_drawn,
    test_v_straightens_the_middle_line_of_a_band_with_one_straight_rail,
    test_picks_survive_the_redo_and_confirm_equals_execute,
    test_one_lmb_straightens_a_line_through_triangles_and_ngons,
    test_lmb_offers_only_full_cuts_that_lay_out,
    test_a_v_pick_never_loosens_the_rails,
    test_a_pick_the_layout_cannot_keep_is_not_offered_nor_stored,
    test_removing_the_last_align_line_under_none_restores_align,
    test_the_default_stands_a_wide_trim_strips_end_lines_upright,
    test_old_last_used_slanted_ends_migrate_once_to_upright_where_cheap,
    test_a_wide_closed_band_is_cut_open_and_laid_out_as_one_strip,
    test_a_wide_closed_band_is_cut_along_a_seam_line_across_it,
    test_a_wide_closed_band_is_cut_at_its_picked_break,
    test_lmb_on_a_wide_closed_band_adds_breaks_and_takes_back_one,
    test_confirm_after_a_wide_band_break_equals_execute,
    test_a_picked_break_on_a_wide_band_wins_over_a_seam_line_across_it,
    test_auto_tears_a_wide_l_at_its_mitre_when_it_cannot_be_straight_within_the_limit,
    test_c_takes_back_and_restores_an_automatic_tear_of_a_wide_strip,
    test_c_takes_back_an_automatic_junction_cut,
    test_a_straight_line_is_picked_on_the_piece_under_the_cursor,
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
