"""Headless tests of UV Stripe in Smart Inset: the operator's execute() on real
meshes in Edit Mode, and the modal's U key, HUD and help. Run from the repo root via:

    blender --background --factory-startup --python-exit-code 1 --python tests/blender/test_smart_inset_uv_stripe.py

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
    from InteractionOps.operators.mesh_smart_inset import IOPS_OT_smart_inset
    operator = IOPS_OT_smart_inset


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
    me = bpy.data.meshes.new("smart_inset")
    bm.to_mesh(me)
    bm.free()
    obj = bpy.data.objects.new("smart_inset", me)
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


# --- modal stand-ins ---------------------------------------------------------------

class _OperatorStandIn:
    """Stands in for an operator instance: the operator's methods run on these props."""

    def __init__(self, **props):
        self.thickness, self.depth, self.mode = 0.05, 0.0, "REGION"
        self.use_collapse, self.use_boundary = True, True
        self.use_uv_stripe, self.uv_stripe_mode = False, "FIT"
        self.uv_stripe_layout, self.uv_stripe_orientation, self.uv_stripe_mark_seams = "TRUE", "HORIZONTAL", True
        self.uv_stripe_split_at_bends, self.uv_stripe_split_angle = True, math.radians(15)
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
    bpy.ops.iops.mesh_smart_inset('EXEC_DEFAULT', thickness=0.2, use_uv_stripe=True, uv_stripe_split_at_bends=False)
    us, vs = _wall_uv_ranges(obj)
    assert us == (0.0, 1.0) and vs == (0.0, 0.027778)
    assert _seam_vertex_has_u0_and_u1(obj)


def test_outset_square_fit():
    obj = _plane(2.0)
    _select_all_faces(obj)
    bpy.ops.iops.mesh_smart_inset('EXEC_DEFAULT', thickness=-0.2, use_uv_stripe=True, uv_stripe_split_at_bends=False)
    assert _wall_uv_ranges(obj)[1] == (0.0, 0.022727)


def test_collapsed_rectangle_still_a_rectangle():
    obj = _plane_rect(1.0, 4.0)
    _select_all_faces(obj)
    bpy.ops.iops.mesh_smart_inset('EXEC_DEFAULT', thickness=99.0, use_collapse=True, use_uv_stripe=True, uv_stripe_split_at_bends=False)
    assert _wall_uv_ranges(obj) == ((0.0, 1.0), (0.0, 0.0625))


def test_uv_stripe_off_keeps_old_behaviour():
    obj = _plane(2.0, uv=True)
    _select_all_faces(obj)
    before = _uv_bbox(obj)
    bpy.ops.iops.mesh_smart_inset('EXEC_DEFAULT', thickness=0.2)
    assert _uv_bbox(obj) == before


def test_depth_strip_height_is_the_slanted_wall():   # height hypot(0.2, 0.2) over length 7.2
    obj = _plane(2.0)
    _select_all_faces(obj)
    bpy.ops.iops.mesh_smart_inset('EXEC_DEFAULT', thickness=0.2, depth=0.2, use_uv_stripe=True, uv_stripe_split_at_bends=False)
    assert _wall_uv_ranges(obj) == ((0.0, 1.0), (0.0, 0.039284))


def test_hole_gives_two_stacked_strips():
    # 3 x 3 cells without the middle one. Outer strip: length 11.6, height 0.1, the
    # region's first loop, so at the bottom. Hole strip: length 4.4, stacked 0.01 above.
    obj = _grid(3, 3, skip={(1, 1)})
    _select_all_faces(obj)
    bpy.ops.iops.mesh_smart_inset('EXEC_DEFAULT', thickness=0.1, use_uv_stripe=True, uv_stripe_split_at_bends=False)
    assert _wall_uv_ranges(obj, inside=(0.85, 2.15)) == ((0.0, 1.0), (0.018621, 0.041348))
    outer = [uv for co, uv in _wall_corners(obj) if not all(0.85 <= c <= 2.15 for c in co[:2])]
    us, vs = [u for u, _v in outer], [v for _u, v in outer]
    assert (min(us), max(us)) == (0.0, 1.0) and (min(vs), max(vs)) == (0.0, 0.008621)


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
    op = _OperatorStandIn(thickness=0.1, use_boundary=False, use_uv_stripe=True, uv_stripe_split_at_bends=False)
    assert op._run(bpy.context) == {'FINISHED'}
    assert op.reports == [], op.reports
    assert _wall_uv_ranges(obj, inside=(0.85, 2.15)) == ((0.0, 1.0), (0.0, 0.022727))


def test_individual_mode_stacks_one_strip_per_face():   # each face: length 3.6, height 0.1
    obj = _grid(2, 1)
    _select_all_faces(obj)
    bpy.ops.iops.mesh_smart_inset('EXEC_DEFAULT', thickness=0.1, mode="INDIVIDUAL", use_uv_stripe=True, uv_stripe_split_at_bends=False)
    vs = sorted({uv[1] for _co, uv in _wall_corners(obj)})
    assert vs == [0.0, 0.027778, 0.037778, 0.065556]
    assert _wall_uv_ranges(obj)[0] == (0.0, 1.0)


def test_in_place_keeps_the_old_uvs_and_density():
    # Old UVs 0-1 over the 2 x 2 plane: centre (0.5, 0.5), density 0.5 from the inner face.
    # The 7.2 x 0.2 strip is 3.6 x 0.1 in UV.
    obj = _plane(2.0, uv=True)
    _select_all_faces(obj)
    bpy.ops.iops.mesh_smart_inset('EXEC_DEFAULT', thickness=0.2, use_uv_stripe=True, uv_stripe_mode="IN_PLACE", uv_stripe_split_at_bends=False)
    assert _wall_uv_ranges(obj) == ((-1.3, 2.3), (0.45, 0.55))


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


def _wall_metrics(obj):
    """Per wall face: (UV length / 3D length of each edge, |UV corner angle - 3D corner angle| in degrees)."""
    bm = bmesh.from_edit_mesh(obj.data)
    layer = bm.loops.layers.uv.active
    out = []
    for f in _wall_faces(bm, obj.name):
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


def test_straighten_stands_the_walls_cross_edges_vertical():
    # 4 x 1 rectangle inset by 0.2, laid out whole: the border (10 long) and the new contour (8.4) put their corners
    # at different fractions of their lengths, so even rows lean; Rectangles stands every corner's wall edge vertical.
    obj = _plane_rect(4.0, 1.0)
    _select_all_faces(obj)
    bpy.ops.iops.mesh_smart_inset('EXEC_DEFAULT', thickness=0.2, use_uv_stripe=True, uv_stripe_layout="EVEN",
                                  uv_stripe_split_at_bends=False)
    near, far = _corner_us(obj, 4.0, 1.0)
    assert near != far
    obj = _plane_rect(4.0, 1.0)
    _select_all_faces(obj)
    bpy.ops.iops.mesh_smart_inset('EXEC_DEFAULT', thickness=0.2, use_uv_stripe=True, uv_stripe_layout="STRAIGHT",
                                  uv_stripe_split_at_bends=False)
    near, far = _corner_us(obj, 4.0, 1.0)
    assert near == far and len(near) == 5, (near, far)      # 4 corners, the seam corner at 0 and 1
    assert _wall_uv_ranges(obj) == ((0.0, 1.0), (0.0, 0.021739))     # 0.2 over L 9.2


def test_defaults_give_four_stretch_free_pieces():
    # No Stretch and Split at Bends by default: every corner turns the walls by 90 degrees, so each wall is a piece
    # of its own, laid out at its true size with one Fit scale (1 / 4, the longest wall): every UV edge is its 3D
    # length over 4 and every corner keeps its angle; the border lies on each piece's v = 0.
    obj = _plane_rect(4.0, 1.0)
    _select_all_faces(obj)
    bpy.ops.iops.mesh_smart_inset('EXEC_DEFAULT', thickness=0.2, use_uv_stripe=True)
    metrics = _wall_metrics(obj)
    assert len(metrics) == 4
    for ratios, errors in metrics:
        assert all(abs(r - 0.25) < 1e-6 for r in ratios), ratios
        assert max(errors) < 1e-4, errors
    for corners in _wall_face_corners(obj):
        vs = [uv[1] for _co, uv in corners]
        assert all(uv[1] == min(vs) for co, uv in corners if _on_rect_border(co, 4.0, 1.0)), corners
        assert all(uv[1] > min(vs) for co, uv in corners if not _on_rect_border(co, 4.0, 1.0)), corners
    bm = bmesh.from_edit_mesh(obj.data)
    walls = set(_wall_faces(bm, obj.name))
    seams = {e for e in bm.edges if e.seam}
    assert seams == {e for f in walls for e in f.edges}       # every wall edge: outline or tear


def test_mark_seams_match_the_walls():
    obj = _plane_rect(4.0, 1.0)
    _select_all_faces(obj)
    bpy.ops.iops.mesh_smart_inset('EXEC_DEFAULT', thickness=0.2, use_uv_stripe=True, uv_stripe_mark_seams=False)
    assert not any(e.seam for e in bmesh.from_edit_mesh(obj.data).edges)
    obj = _plane_rect(4.0, 1.0)
    _select_all_faces(obj)
    bpy.ops.iops.mesh_smart_inset('EXEC_DEFAULT', thickness=0.2, use_uv_stripe=True,
                                  uv_stripe_split_at_bends=False)
    bm = bmesh.from_edit_mesh(obj.data)
    walls = set(_wall_faces(bm, obj.name))
    outline = {e for f in walls for e in f.edges if sum(g in walls for g in e.link_faces) == 1}
    seams = {e for e in bm.edges if e.seam}
    assert outline <= seams and len(outline) == 8
    (cut,) = seams - outline                                # the ring's UV cut: one wall side edge
    assert sum(_on_rect_border(_key(v.co), 4.0, 1.0) for v in cut.verts) == 1
    us = {round(lp[bm.loops.layers.uv.active].uv.x, 6) for v in cut.verts for lp in v.link_loops
          if lp.face in walls}
    assert us == {0.0, 1.0}


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
    assert op.reports == ["Smart Inset: UV Stripe not split (refused for the test)"], op.reports
    assert _wall_uv_ranges(obj) == ((0.0, 1.0), (0.0, 0.021739))
    assert _seam_vertex_has_u0_and_u1(obj)


def test_vertical_orientation():
    obj = _plane(2.0)
    _select_all_faces(obj)
    bpy.ops.iops.mesh_smart_inset('EXEC_DEFAULT', thickness=0.2, use_uv_stripe=True, uv_stripe_split_at_bends=False,
                                  uv_stripe_orientation="VERTICAL")
    assert _wall_uv_ranges(obj) == ((0.0, 0.027778), (0.0, 1.0))


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
    test_uv_stripe_off_keeps_old_behaviour,
    test_depth_strip_height_is_the_slanted_wall,
    test_hole_gives_two_stacked_strips,
    test_frozen_loop_without_walls_leaves_the_others,
    test_individual_mode_stacks_one_strip_per_face,
    test_in_place_keeps_the_old_uvs_and_density,
    test_straighten_stands_the_walls_cross_edges_vertical,
    test_defaults_give_four_stretch_free_pieces,
    test_mark_seams_match_the_walls,
    test_a_split_that_cannot_be_made_is_reported_and_the_loop_stays_whole,
    test_vertical_orientation,
    test_modal_hud_and_help_list_uv_stripe,
    test_modal_u_toggles_uv_stripe_and_cancel_restores,
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
