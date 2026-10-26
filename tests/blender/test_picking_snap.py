"""Headless test of utils.picking.closest_snap_point: the snap tolerance must
follow the on-screen pixel size at the hit depth, not the object's scale, so
snapping behaves the same on a 1 cm mesh and a 10 km mesh. Run from the repo
root via:

    blender --background --factory-startup --python-exit-code 1 --python tests/blender/test_picking_snap.py

No viewport is needed: the region / region_3d are SimpleNamespace stand-ins
carrying an orthographic view with a known world-per-pixel ratio.

Not collected by pytest (tests/conftest.py ignores tests/blender).
"""
import os
import sys
import traceback
from types import SimpleNamespace

import bpy
from mathutils import Matrix, Vector

ADDON = "InteractionOps"
REGION_PX = 1000

picking = None


def enable_addon():
    global picking
    repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    repo_parent = os.path.dirname(repo_root)
    if repo_parent not in sys.path:
        sys.path.insert(0, repo_parent)
    bpy.ops.preferences.addon_enable(module=ADDON)
    assert ADDON in bpy.context.preferences.addons, "addon not enabled"
    import InteractionOps
    loaded = os.path.dirname(os.path.abspath(InteractionOps.__file__))
    assert os.path.samefile(loaded, repo_root), "addon loaded from %s" % loaded
    from InteractionOps.utils import picking as _picking
    picking = _picking


# --- fake viewport -------------------------------------------------------------

def ortho_context(view_width_world):
    """Top-down orthographic view: REGION_PX px span `view_width_world`
    metres, so one pixel is `view_width_world / REGION_PX` metres."""
    s = 2.0 / view_width_world
    window = Matrix(((s, 0, 0, 0), (0, s, 0, 0), (0, 0, -1e-4, 0), (0, 0, 0, 1)))
    view = Matrix.Identity(4)
    rv3d = SimpleNamespace(window_matrix=window, view_matrix=view,
                           perspective_matrix=window @ view, is_perspective=False)
    region = SimpleNamespace(width=REGION_PX, height=REGION_PX)
    return SimpleNamespace(region=region, space_data=SimpleNamespace(region_3d=rv3d))


def screen_of(ctx, world):
    from bpy_extras.view3d_utils import location_3d_to_region_2d
    return location_3d_to_region_2d(ctx.region, ctx.space_data.region_3d, world)


def square_points(side):
    """Snap points of a square face of `side` metres centred at origin."""
    h = side / 2.0
    pts = [("vertex", Vector((x, y, 0.0))) for x, y in
           ((-h, -h), (h, -h), (h, h), (-h, h))]
    pts.append(("center", Vector((0.0, 0.0, 0.0))))
    return pts


def snap_near_vertex(side, obj_matrix, *, px_off, view_width):
    """Mouse `px_off` px right of the world-space vertex (+h, +h); ray hit
    exactly under the mouse. Returns the snap result kind or None."""
    ctx = ortho_context(view_width)
    m_per_px = view_width / REGION_PX
    vertex_world = obj_matrix @ Vector((side / 2.0, side / 2.0, 0.0))
    hit_world = vertex_world + Vector((px_off * m_per_px, 0.0, 0.0))
    mouse = screen_of(ctx, hit_world)
    res = picking.closest_snap_point(ctx, square_points(side), obj_matrix,
                                     (mouse[0], mouse[1]), hit_world,
                                     screen_threshold_px=30.0)
    return None if res is None else res[0]


# --- tests -------------------------------------------------------------------

def test_pixel_size_is_exact():
    ctx = ortho_context(2000.0)
    px = picking.px_world_at(ctx.region, ctx.space_data.region_3d, Vector((0, 0, 0)))
    assert abs(px - 2.0) < 1e-6, px  # float32 matrices


def test_giant_mesh_snaps_within_pixel_threshold():
    # 1000 m face, 2 m per pixel, mouse 10 px from the vertex (20 m).
    assert snap_near_vertex(1000.0, Matrix.Identity(4), px_off=10, view_width=2000.0) == "vertex"


def test_tiny_mesh_snaps_within_pixel_threshold():
    # 1 cm face, 20 µm per pixel, mouse 10 px from the vertex.
    assert snap_near_vertex(0.01, Matrix.Identity(4), px_off=10, view_width=0.02) == "vertex"


def test_giant_mesh_rejects_beyond_pixel_threshold():
    assert snap_near_vertex(1000.0, Matrix.Identity(4), px_off=60, view_width=2000.0) is None


def test_tiny_mesh_rejects_beyond_pixel_threshold():
    assert snap_near_vertex(0.01, Matrix.Identity(4), px_off=60, view_width=0.02) is None


def test_object_scale_does_not_change_tolerance():
    # Same 1000 m world-size face expressed as a 10 m mesh scaled 100x.
    scaled = Matrix.Diagonal((100.0, 100.0, 100.0, 1.0))
    assert snap_near_vertex(10.0, scaled, px_off=10, view_width=2000.0) == "vertex"
    assert snap_near_vertex(10.0, scaled, px_off=60, view_width=2000.0) is None


def test_world_fallback_scales_with_geometry():
    # No region_3d: pure-world fallback. Tolerance must follow the face size.
    ctx = SimpleNamespace(region=None, space_data=SimpleNamespace(region_3d=None))
    pts = square_points(1000.0)
    near = Vector((500.0, 500.0, 0.0)) + Vector((20.0, 0.0, 0.0))
    res = picking.closest_snap_point(ctx, pts, Matrix.Identity(4), (0, 0), near)
    assert res is not None and res[0] == "vertex", res
    far = Vector((500.0, 500.0, 0.0)) + Vector((400.0, 0.0, 0.0))
    res = picking.closest_snap_point(ctx, pts, Matrix.Identity(4), (0, 0), far)
    assert res is None, res


TESTS = [
    test_pixel_size_is_exact,
    test_giant_mesh_snaps_within_pixel_threshold,
    test_tiny_mesh_snaps_within_pixel_threshold,
    test_giant_mesh_rejects_beyond_pixel_threshold,
    test_tiny_mesh_rejects_beyond_pixel_threshold,
    test_object_scale_does_not_change_tolerance,
    test_world_fallback_scales_with_geometry,
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
