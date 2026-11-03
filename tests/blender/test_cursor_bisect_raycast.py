"""Headless test of utils.picking.raycast_edit_meshes: Cursor Bisect picks
faces on the edit-mode BMesh itself, so the face index it gets back is a
`bm.faces` index whatever modifiers (Triangulate, Mirror, Bevel...) are
enabled in the viewport, and hidden faces are pierced. Run from the repo
root via:

    blender --background --factory-startup --python-exit-code 1 --python tests/blender/test_cursor_bisect_raycast.py

No viewport is needed: rays are passed explicitly.

Not collected by pytest (tests/conftest.py ignores tests/blender).
"""
import os
import sys
import traceback

import bmesh
import bpy
from mathutils import Vector

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
    assert os.path.samefile(loaded, repo_root), "addon loaded from %s" % loaded
    from InteractionOps.utils import picking as _picking
    picking = _picking


# --- scene helpers -----------------------------------------------------------------

def clear_scene():
    if bpy.context.object and bpy.context.object.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    for coll in (bpy.data.objects, bpy.data.meshes):
        for block in list(coll):
            coll.remove(block)


def cube(name, location=(0, 0, 0)):
    """2 m cube of six quads centred at `location`."""
    me = bpy.data.meshes.new(name)
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=2.0)
    bm.to_mesh(me)
    bm.free()
    obj = bpy.data.objects.new(name, me)
    obj.location = location
    bpy.context.scene.collection.objects.link(obj)
    return obj


def enter_edit(*objs):
    bpy.ops.object.select_all(action='DESELECT')
    for o in objs:
        o.select_set(True)
    bpy.context.view_layer.objects.active = objs[0]
    bpy.ops.object.mode_set(mode='EDIT')
    bpy.context.view_layer.update()


def top_face_index(bm):
    bm.faces.ensure_lookup_table()
    return max(range(len(bm.faces)), key=lambda i: bm.faces[i].calc_center_median().z)


def bottom_face_index(bm):
    bm.faces.ensure_lookup_table()
    return min(range(len(bm.faces)), key=lambda i: bm.faces[i].calc_center_median().z)


def cast(objs, origin, direction, cache=None):
    return picking.raycast_edit_meshes(
        bpy.context, (0, 0), objs, ray=(Vector(origin), Vector(direction)),
        cache=cache if cache is not None else {})


DOWN = (0.0, 0.0, -1.0)


# --- tests -----------------------------------------------------------------------

def test_triangulate_on_returns_bmesh_face_index():
    clear_scene()
    obj = cube("Tri")
    obj.modifiers.new("Triangulate", 'TRIANGULATE')
    enter_edit(obj)
    bm = bmesh.from_edit_mesh(obj.data)
    # With Triangulate on, the evaluated mesh has 12 faces; scene.ray_cast
    # would hand back an index into those. We want the 6-face BMesh index.
    assert len(obj.evaluated_get(bpy.context.evaluated_depsgraph_get()).data.polygons) == 12
    result, loc, normal, face_index, hit_obj, matrix = cast([obj], (0.3, 0.2, 5.0), DOWN)
    assert result, "ray from above the cube missed"
    assert hit_obj == obj
    assert face_index == top_face_index(bm), (face_index, len(bm.faces))
    assert abs(loc.z - 1.0) < 1e-6, loc
    assert (normal - Vector((0, 0, 1))).length < 1e-6, normal


def test_mirror_half_is_not_hit():
    clear_scene()
    obj = cube("Mir")
    mod = obj.modifiers.new("Mirror", 'MIRROR')
    mod.use_mirror_merge = False
    obj.data.transform(__import__("mathutils").Matrix.Translation((2.0, 0.0, 0.0)))
    enter_edit(obj)
    # Cage spans x in [1, 3]; the mirrored copy at x in [-3, -1] is modifier output only.
    result, *_ = cast([obj], (-2.0, 0.0, 5.0), DOWN)
    assert not result, "ray hit the mirrored (modifier-only) geometry"
    result, loc, _n, face_index, _o, _m = cast([obj], (2.0, 0.0, 5.0), DOWN)
    bm = bmesh.from_edit_mesh(obj.data)
    assert result and face_index == top_face_index(bm)


def test_hidden_face_is_pierced():
    clear_scene()
    obj = cube("Hid")
    enter_edit(obj)
    bm = bmesh.from_edit_mesh(obj.data)
    top = top_face_index(bm)
    bm.faces[top].hide_set(True)
    bmesh.update_edit_mesh(obj.data)
    result, loc, _n, face_index, _o, _m = cast([obj], (0.0, 0.0, 5.0), DOWN)
    assert result, "ray should reach the bottom face through the hidden top"
    assert face_index == bottom_face_index(bm), face_index
    assert abs(loc.z + 1.0) < 1e-6, loc


def test_nearest_object_wins():
    clear_scene()
    high = cube("High", location=(0, 0, 4.0))
    low = cube("Low", location=(0, 0, 0.0))
    enter_edit(low, high)
    result, loc, _n, _f, hit_obj, _m = cast([low, high], (0.0, 0.0, 10.0), DOWN)
    assert result and hit_obj == high, hit_obj
    assert abs(loc.z - 5.0) < 1e-6, loc
    # Object matrix (location) is applied: hit is in world space.
    result, loc, _n, _f, hit_obj, _m = cast([low, high], (0.0, 0.0, 2.0), DOWN)
    assert result and hit_obj == low and abs(loc.z - 1.0) < 1e-6, (hit_obj, loc)


def test_cache_follows_topology_changes():
    clear_scene()
    obj = cube("Cache")
    enter_edit(obj)
    cache = {}
    result, *_ = cast([obj], (0.0, 0.0, 5.0), DOWN, cache)
    assert result
    bm = bmesh.from_edit_mesh(obj.data)
    bmesh.ops.delete(bm, geom=[bm.faces[top_face_index(bm)]], context='FACES')
    bmesh.update_edit_mesh(obj.data)
    picking.invalidate_edit_mesh_cache(cache, obj)
    result, loc, _n, face_index, _o, _m = cast([obj], (0.0, 0.0, 5.0), DOWN, cache)
    bm = bmesh.from_edit_mesh(obj.data)
    assert result and abs(loc.z + 1.0) < 1e-6, loc
    assert face_index == bottom_face_index(bm)


TESTS = [
    test_triangulate_on_returns_bmesh_face_index,
    test_mirror_half_is_not_hit,
    test_hidden_face_is_pierced,
    test_nearest_object_wins,
    test_cache_follows_topology_changes,
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
