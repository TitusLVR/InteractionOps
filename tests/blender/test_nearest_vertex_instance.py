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
    view_matrix = Matrix.Identity(4)      # looking down -Z
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


def test_instance_vertex_from_modifier():
    """A vertex that only the Mirror modifier creates is still found: the
    vertices come from the evaluated mesh, not from the object's own data."""
    cube, _empty = build_instance()
    # geometry at local x 0..2 around an origin at the collection's origin,
    # so the mirror copy (x -2..0) is new geometry
    cube.location = (0.0, 0.0, 0.0)
    for v in cube.data.vertices:
        v.co.x += 1.0
    mod = cube.modifiers.new("Mirror", "MIRROR")
    mod.use_axis = (True, False, False)
    bpy.context.view_layer.update()
    # the mirrored cube spans local x -2..0, so world x 8..10
    hit, _loc, _nrm, _idx, obj, matrix = cast_down(8.1, 0.9)
    assert hit and obj.original == cube, (hit, obj)
    mouse = to_px((8.1, 0.9))
    idx, co = picking.nearest_vertex_screen(_Context(), obj, mouse, matrix=matrix)
    assert idx is not None, "no vertex found on the mirrored half"
    assert abs(co.x - 8.0) < 1e-4 and abs(co.y - 1.0) < 1e-4, tuple(co)


def plane(name, x0, x1, y0, y1, z):
    me = bpy.data.meshes.new(name)
    me.from_pydata([(x0, y0, z), (x1, y0, z), (x1, y1, z), (x0, y1, z)], [], [(0, 1, 2, 3)])
    obj = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(obj)
    return obj


def test_scene_vertex_of_neighbour_at_a_seam():
    """The mouse is over a big plane whose own vertices are far away; a
    vertex of a collection instance next to it is within the threshold and
    must be picked, although the ray under the mouse hits the plane."""
    cube, _empty = build_instance()            # instance cube spans x 10..12, y -1..1, z -1..1
    plane("Floor", -10.0, 9.95, -10.0, 10.0, 0.0)
    bpy.context.view_layer.update()
    mouse = to_px((9.9, 0.95))                 # over the floor, 0.1 from the cube's corner (10, 1)
    cache = picking.build_vertex_snap_cache(_Context())
    co = picking.nearest_vertex_scene(_Context(), mouse, cache=cache)[0]
    assert co is not None, "the instance's corner was not picked"
    assert abs(co.x - 10.0) < 1e-4 and abs(co.y - 1.0) < 1e-4 and abs(co.z - 1.0) < 1e-4, tuple(co)


def test_scene_vertex_hidden_under_a_surface_is_skipped():
    """A vertex covered by a surface in front of it is not picked, even when
    it is the closest one on screen; the visible one behind the threshold
    ordering is taken instead."""
    clear_scene()
    lid = plane("Lid", -5.0, 5.0, -5.0, 5.0, 2.0)
    hidden = cube_object("Hidden", (0.0, 0.0, 0.0))        # top corners at z = 1, under the lid
    bpy.context.scene.collection.objects.link(hidden)
    bpy.context.view_layer.update()
    mouse = to_px((1.05, 1.05))                # on screen right next to Hidden's corner (1, 1)
    cache = picking.build_vertex_snap_cache(_Context())
    co = picking.nearest_vertex_scene(_Context(), mouse, cache=cache)[0]
    assert co is None, ("a covered vertex was picked", tuple(co))
    # the lid's own corner is visible
    mouse = to_px((4.9, 4.9))
    co = picking.nearest_vertex_scene(_Context(), mouse, cache=cache)[0]
    assert co is not None and abs(co.x - 5.0) < 1e-4 and abs(co.z - 2.0) < 1e-4, co
    assert lid.name == "Lid"


def test_scene_vertex_from_modifier_on_instance():
    cube, _empty = build_instance()
    cube.location = (0.0, 0.0, 0.0)
    for v in cube.data.vertices:
        v.co.x += 1.0
    mod = cube.modifiers.new("Mirror", "MIRROR")
    mod.use_axis = (True, False, False)
    bpy.context.view_layer.update()
    mouse = to_px((8.05, 0.95))               # mirrored corner (8, 1, 1)
    cache = picking.build_vertex_snap_cache(_Context())
    co = picking.nearest_vertex_scene(_Context(), mouse, cache=cache)[0]
    assert co is not None and abs(co.x - 8.0) < 1e-4 and abs(co.y - 1.0) < 1e-4, co


def test_scene_edge_point_on_instance():
    """Shift mode: the point of the edge under the mouse, on an instance."""
    build_instance()                          # cube x 10..12, y -1..1, z -1..1
    cache = picking.build_vertex_snap_cache(_Context())
    co, seg = picking.nearest_element_scene(_Context(), to_px((11.3, 1.05)), cache=cache, element="EDGE")
    assert co is not None, "no edge point"
    assert abs(co.x - 11.3) < 1e-3 and abs(co.y - 1.0) < 1e-4 and abs(co.z - 1.0) < 1e-4, tuple(co)
    assert seg is not None and {round(seg[0].x, 3), round(seg[1].x, 3)} == {10.0, 12.0}, seg


def test_scene_edge_middle_on_instance():
    """Alt mode: the middle of the edge under the mouse."""
    build_instance()
    cache = picking.build_vertex_snap_cache(_Context())
    co, _seg = picking.nearest_element_scene(_Context(), to_px((10.4, 1.05)), cache=cache,
                                             element="EDGE_MIDDLE")
    assert co is not None, "no edge middle"
    assert abs(co.x - 11.0) < 1e-4 and abs(co.y - 1.0) < 1e-4 and abs(co.z - 1.0) < 1e-4, tuple(co)


def test_face_center_on_instance():
    """Ctrl mode: the centre of the face under the mouse, on an instance."""
    build_instance()
    co, outline = picking.face_center_under_mouse(_Context(), to_px((10.4, 0.5)), region=_Region(),
                                                  rv3d=_RV3D())
    assert co is not None, "no face"
    assert abs(co.x - 11.0) < 1e-4 and abs(co.y) < 1e-4 and abs(co.z - 1.0) < 1e-4, tuple(co)
    assert len(outline) == 4


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
    tests = [test_instance_vertex_uses_hit_matrix, test_instance_vertex_from_modifier,
             test_plain_object_default_matrix, test_scene_vertex_of_neighbour_at_a_seam,
             test_scene_vertex_hidden_under_a_surface_is_skipped,
             test_scene_vertex_from_modifier_on_instance, test_scene_edge_point_on_instance,
             test_scene_edge_middle_on_instance, test_face_center_on_instance]
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
