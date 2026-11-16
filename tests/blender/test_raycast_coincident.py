"""Headless test of utils.picking.raycast_from_mouse piercing a rejected
object whose surface coincides with a permitted one: the permitted surface
must still be hit, not skipped by the step past the rejected hit. Run from
the repo root via:

    blender --background --factory-startup --python-exit-code 1 --python tests/blender/test_raycast_coincident.py

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
    for coll in (bpy.data.objects, bpy.data.meshes):
        for block in list(coll):
            coll.remove(block)


def cube(name, *, size=2.0, location=(0, 0, 0), scale=(1, 1, 1)):
    me = bpy.data.meshes.new(name)
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=size)
    bm.to_mesh(me)
    bm.free()
    obj = bpy.data.objects.new(name, me)
    obj.location = location
    obj.scale = scale
    bpy.context.scene.collection.objects.link(obj)
    return obj


class _Stub:
    """Stands in for the region / rv3d the function only checks for None
    when a ray is passed explicitly."""


def cast(origin, direction, **kwargs):
    bpy.context.view_layer.update()
    return picking.raycast_from_mouse(
        bpy.context, (0, 0), region=_Stub(), rv3d=_Stub(),
        ray=(Vector(origin), Vector(direction)), **kwargs)


DOWN = (0.0, 0.0, -1.0)
UP = Vector((0.0, 0.0, 1.0))


def assert_top_hit(hit, expect_obj):
    result, loc, normal, face_index, obj, matrix = hit
    assert result, "the coincident permitted surface was skipped"
    assert obj.original == expect_obj, obj
    assert abs(loc.z - 1.0) < 1e-5, loc
    assert (normal - UP).length < 1e-5, normal
    mesh = obj.evaluated_get(bpy.context.evaluated_depsgraph_get()).data
    poly = mesh.polygons[face_index]
    assert (matrix.to_3x3() @ poly.normal).normalized().dot(UP) > 0.999, face_index
    assert all(abs(matrix[i][j] - expect_obj.matrix_world[i][j]) < 1e-6
               for i in range(4) for j in range(4)), matrix


# --- tests -----------------------------------------------------------------------

def test_excluded_coincident_object_does_not_hide_the_other():
    clear_scene()
    a = cube("A")
    b = cube("B")
    # Whichever of the two the scene ray returns first, the other one must
    # be reachable when the first is excluded.
    assert_top_hit(cast((0.3, 0.2, 5.0), DOWN, exclude=[a]), b)
    assert_top_hit(cast((0.3, 0.2, 5.0), DOWN, exclude=[b]), a)


def test_restrict_to_coincident_object():
    clear_scene()
    a = cube("A")
    b = cube("B")
    assert_top_hit(cast((0.3, 0.2, 5.0), DOWN, restrict_to=[a]), a)
    assert_top_hit(cast((0.3, 0.2, 5.0), DOWN, restrict_to=[b]), b)


def test_coincident_object_with_scale():
    clear_scene()
    a = cube("A")
    b = cube("B", size=0.5, scale=(4.0, 4.0, 4.0))   # the same 2 m cube in world space
    assert_top_hit(cast((0.3, 0.2, 5.0), DOWN, exclude=[a]), b)
    assert_top_hit(cast((0.3, 0.2, 5.0), DOWN, exclude=[b]), a)


def test_owner_cache_keeps_working():
    clear_scene()
    a = cube("A")
    b = cube("B")
    cache = {}
    for _ in range(3):
        assert_top_hit(cast((0.3, 0.2, 5.0), DOWN, exclude=[a], owner_cache=cache), b)
        assert_top_hit(cast((0.3, 0.2, 5.0), DOWN, restrict_to=[a], owner_cache=cache), a)


def test_hidden_coincident_object_is_not_hit():
    clear_scene()
    a = cube("A")
    b = cube("B")
    b.hide_set(True)
    result, *_ = cast((0.3, 0.2, 5.0), DOWN, exclude=[a])
    assert not result, "a hidden object was hit through the coincident check"


def test_separate_surfaces_still_pierce_in_order():
    clear_scene()
    high = cube("High", location=(0, 0, 4.0))
    low = cube("Low")
    result, loc, _n, _f, obj, _m = cast((0.0, 0.0, 10.0), DOWN, exclude=[high])
    assert result and obj.original == low and abs(loc.z - 1.0) < 1e-5, (obj, loc)
    result, loc, _n, _f, obj, _m = cast((0.0, 0.0, 10.0), DOWN)
    assert result and obj.original == high and abs(loc.z - 5.0) < 1e-5, (obj, loc)
    result, *_ = cast((0.0, 0.0, 10.0), DOWN, exclude=[high, low])
    assert not result


TESTS = [
    test_excluded_coincident_object_does_not_hide_the_other,
    test_restrict_to_coincident_object,
    test_coincident_object_with_scale,
    test_owner_cache_keeps_working,
    test_hidden_coincident_object_is_not_hit,
    test_separate_surfaces_still_pierce_in_order,
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
