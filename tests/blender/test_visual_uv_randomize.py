"""Headless test of Visual UV's Randomize (N / Shift+N / Ctrl+N): an island
is placed at random inside the first `tiles` tiles from the UV origin, so a
tall island still moves vertically when the add-on's Randomize Range allows
more than one tile. Run from the repo root via:

    blender --background --factory-startup --python-exit-code 1 --python tests/blender/test_visual_uv_randomize.py

(with every BLENDER_USER_* variable pointed at scratch directories).

Not collected by pytest (tests/conftest.py ignores tests/blender).
"""
import os
import random
import sys
import traceback

import bmesh
import bpy

ADDON = "InteractionOps"

uv_utils = None


def enable_addon():
    global uv_utils
    repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    repo_parent = os.path.dirname(repo_root)
    if repo_parent not in sys.path:
        sys.path.insert(0, repo_parent)
    bpy.ops.preferences.addon_enable(module=ADDON)
    assert ADDON in bpy.context.preferences.addons, "addon not enabled"
    import InteractionOps
    loaded = os.path.dirname(os.path.abspath(InteractionOps.__file__))
    assert os.path.samefile(loaded, repo_root), f"addon loaded from {loaded}"
    from InteractionOps.utils import uv_utils as _uv_utils
    uv_utils = _uv_utils


def _tall_island():
    """One quad whose UV island spans u 0.067-0.933, v 0.0396-0.9881 --
    the island from the bug report: only 0.05 of vertical room in one tile."""
    bm = bmesh.new()
    vs = [bm.verts.new(c) for c in ((0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0))]
    face = bm.faces.new(vs)
    uv = bm.loops.layers.uv.new("UVMap")
    for loop, co in zip(face.loops, ((0.067, 0.0396), (0.933, 0.0396),
                                     (0.933, 0.9881), (0.067, 0.9881))):
        loop[uv].uv = co
    return bm, face, uv


def _bbox(face, uv):
    us = [lp[uv].uv.x for lp in face.loops]
    vs = [lp[uv].uv.y for lp in face.loops]
    return min(us), min(vs), max(us), max(vs)


def _spread(mode, tiles, runs=60):
    """Randomize the tall island `runs` times; return the bbox mins seen and
    the largest coordinate reached."""
    bm, face, uv = _tall_island()
    random.seed(1234)
    mins_u, mins_v, top = [], [], 0.0
    lows = []
    for _ in range(runs):
        data = uv_utils.get_island_uv_data(bm, [face.index], uv)
        uv_utils.randomize_island_uv(data['loops'], uv, data['bbox_min'],
                                     data['bbox_max'], mode, tiles=tiles)
        u0, v0, u1, v1 = _bbox(face, uv)
        mins_u.append(u0)
        mins_v.append(v0)
        lows.append(min(u0, v0))
        top = max(top, u1, v1)
    bm.free()
    return mins_u, mins_v, min(lows), top


def test_vertical_randomize_uses_two_tiles():
    _mu, mins_v, low, top = _spread('V', tiles=2)
    assert low >= -1e-6 and top <= 2.0 + 1e-6, (low, top)
    assert max(mins_v) - min(mins_v) > 0.5, (min(mins_v), max(mins_v))


def test_horizontal_randomize_uses_two_tiles():
    mins_u, _mv, low, top = _spread('U', tiles=2)
    assert low >= -1e-6 and top <= 2.0 + 1e-6, (low, top)
    assert max(mins_u) - min(mins_u) > 0.5, (min(mins_u), max(mins_u))


def test_v_only_leaves_u_alone():
    mins_u, _mv, _low, _top = _spread('V', tiles=2)
    assert max(mins_u) - min(mins_u) < 1e-6


def test_one_tile_keeps_the_old_behaviour():
    _mu, mins_v, low, top = _spread('V', tiles=1)
    assert low >= -1e-6 and top <= 1.0 + 1e-6, (low, top)
    assert max(mins_v) - min(mins_v) <= 1.0 - 0.9485 + 1e-6


def test_island_larger_than_the_range_stays_put():
    bm, face, uv = _tall_island()
    for loop in face.loops:
        loop[uv].uv.y *= 3.0          # 2.8 tall: no room in two tiles
    before = _bbox(face, uv)
    data = uv_utils.get_island_uv_data(bm, [face.index], uv)
    uv_utils.randomize_island_uv(data['loops'], uv, data['bbox_min'],
                                 data['bbox_max'], 'V', tiles=2)
    after = _bbox(face, uv)
    bm.free()
    # No room on that axis: the island stays where it is.
    assert all(abs(a - b) < 1e-6 for a, b in zip(before, after)), (before, after)


def test_preference_defaults_to_two_tiles():
    prefs = bpy.context.preferences.addons[ADDON].preferences
    assert prefs.visual_uv_random_range == 2


TESTS = [
    test_vertical_randomize_uses_two_tiles,
    test_horizontal_randomize_uses_two_tiles,
    test_v_only_leaves_u_alone,
    test_one_tile_keeps_the_old_behaviour,
    test_island_larger_than_the_range_stays_put,
    test_preference_defaults_to_two_tiles,
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
