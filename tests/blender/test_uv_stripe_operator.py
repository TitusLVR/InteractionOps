"""Headless tests of the UV Stripe operator (iops.mesh_uv_stripe) on real meshes in
Edit Mode. Run from the repo root via:

    blender --background --factory-startup --python-exit-code 1 --python tests/blender/test_uv_stripe_operator.py

Not collected by pytest (tests/conftest.py ignores tests/blender).
"""
import os
import sys
import traceback

import bmesh
import bpy
from mathutils import Vector

ADDON = "InteractionOps"


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


def test_two_strips_stack_in_fit():
    obj = _grid(4, 4, keep={(x, 0) for x in range(4)} | {(x, 3) for x in range(2)})
    _edit(obj)
    assert _run(mode="FIT") == {"FINISHED"}
    low = _corners(obj, lambda c: c.y < 1.0)
    high = _corners(obj, lambda c: c.y > 3.0)
    assert all(_close(uv.x, co.x / 4.0) and 0.0 <= uv.y <= 0.25 + 1e-6 for co, uv in low)
    assert all(_close(uv.x, co.x / 2.0) for co, uv in high)
    assert min(uv.y for _c, uv in high) > 0.25          # stacked above, not overlapping
    assert _close(max(uv.y for _c, uv in high) - min(uv.y for _c, uv in high), 0.5)


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
    test_two_strips_stack_in_fit,
    test_triangulated_strip_is_its_quads_rectangle,
    test_scaled_object_follows_world_size,
    test_rejected_island_leaves_the_other,
    test_nothing_selected_cancels,
    test_only_rejected_cancels,
    test_mesh_without_uv_gets_one,
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
