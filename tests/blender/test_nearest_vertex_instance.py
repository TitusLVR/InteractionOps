"""Headless test of utils.picking.nearest_vertex_screen on a collection
instance: `scene.ray_cast` returns the instanced mesh object, whose own
`matrix_world` is its place inside the collection, so the vertices must be
placed with the hit's instance matrix. Run from the repo root via:

    blender --background --factory-startup --python-exit-code 1 --python tests/blender/test_nearest_vertex_instance.py

No viewport is needed: the region and view are stubbed with a top-down
orthographic projection.

Not collected by pytest (tests/conftest.py ignores tests/blender).
"""
import os
import sys
import traceback

import bmesh
import bpy
from mathutils import Matrix, Vector

ADDON = "InteractionOps"

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
    assert os.path.samefile(loaded, repo_root), f"addon loaded from {loaded}"
    from InteractionOps.utils import picking as _picking
    picking = _picking


# --- view stub ---------------------------------------------------------------------

WIDTH = HEIGHT = 1000
HALF_SPAN = 20.0   # the view shows world x, y in -20..20, looking down -Z


class _Region:
    width = WIDTH
    height = HEIGHT


class _RV3D:
    is_perspective = False
    perspective_matrix = Matrix((
        (1.0 / HALF_SPAN, 0.0, 0.0, 0.0),
        (0.0, 1.0 / HALF_SPAN, 0.0, 0.0),
        (0.0, 0.0, -0.001, 0.0),
        (0.0, 0.0, 0.0, 1.0),
    ))


class _Space:
    type = "VIEW_3D"
    region_3d = _RV3D()


class _Context:
    region = _Region()
    space_data = _Space()
    region_data = _RV3D()

    def __getattr__(self, name):
        return getattr(bpy.context, name)


def to_px(world):
    return (WIDTH / 2.0 * (1.0 + world[0] / HALF_SPAN),
            HEIGHT / 2.0 * (1.0 + world[1] / HALF_SPAN))


# --- scene helpers -----------------------------------------------------------------

def clear_scene():
    for coll in (bpy.data.objects, bpy.data.meshes, bpy.data.collections):
        for block in list(coll):
            coll.remove(block)


def cube_object(name, location):
    me = bpy.data.meshes.new(name)
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=2.0)
    bm.to_mesh(me)
    bm.free()
    obj = bpy.data.objects.new(name, me)
    obj.location = location
    return obj


def build_instance():
    """A cube at (1, 0, 0) inside a collection instanced by an Empty at
    (10, 0, 0): the visible cube spans x 10..12, its own matrix says 0..2."""
    clear_scene()
    coll = bpy.data.collections.new("Asset")
    cube = cube_object("AssetCube", (1.0, 0.0, 0.0))
    coll.objects.link(cube)
    empty = bpy.data.objects.new("Inst", None)
    empty.instance_type = "COLLECTION"
    empty.instance_collection = coll
    empty.location = (10.0, 0.0, 0.0)
    bpy.context.scene.collection.objects.link(empty)
    bpy.context.view_layer.update()
    return cube, empty


def cast_down(x, y):
    return picking.raycast_from_mouse(
        bpy.context, (0, 0), region=_Region(), rv3d=_RV3D(),
        ray=(Vector((x, y, 50.0)), Vector((0.0, 0.0, -1.0))))


# --- tests -------------------------------------------------------------------------

def test_instance_vertex_uses_hit_matrix():
    cube, _empty = build_instance()
    hit, _loc, _nrm, _idx, obj, matrix = cast_down(11.9, 0.9)
    assert hit and obj.original == cube, (hit, obj)
    mouse = to_px((11.9, 0.9))
    idx, co = picking.nearest_vertex_screen(_Context(), obj, mouse, matrix=matrix)
    assert idx is not None, "no vertex found on the instance"
    assert abs(co.x - 12.0) < 1e-4 and abs(co.y - 1.0) < 1e-4, tuple(co)


def test_plain_object_default_matrix():
    clear_scene()
    cube = cube_object("Plain", (-10.0, 0.0, 0.0))
    bpy.context.scene.collection.objects.link(cube)
    bpy.context.view_layer.update()
    mouse = to_px((-9.1, 0.9))
    idx, co = picking.nearest_vertex_screen(_Context(), cube, mouse)
    assert idx is not None, "no vertex found on the plain object"
    assert abs(co.x + 9.0) < 1e-4 and abs(co.y - 1.0) < 1e-4, tuple(co)


def main():
    enable_addon()
    tests = [test_instance_vertex_uses_hit_matrix, test_plain_object_default_matrix]
    failed = 0
    for t in tests:
        try:
            t()
            print("PASS", t.__name__)
        except Exception:
            failed += 1
            print("FAIL", t.__name__)
            traceback.print_exc()
    print(f"{len(tests) - failed}/{len(tests)} passed")
    if failed:
        sys.exit(1)


main()
