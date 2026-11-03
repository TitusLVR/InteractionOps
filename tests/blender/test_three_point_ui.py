"""Three Point Rotation UI contract: default align mode and the HUD step
checklist. Run headless:
    blender --background --factory-startup --python tests/blender/test_three_point_ui.py
with BLENDER_USER_SCRIPTS pointing at a scripts dir whose addons/ contains
this repo as 'InteractionOps'."""
import sys
import traceback
from types import SimpleNamespace

import bpy

ADDON = "InteractionOps"


def enable_addon():
    if ADDON not in bpy.context.preferences.addons:
        bpy.ops.preferences.addon_enable(module=ADDON)


def _tpr():
    return sys.modules[f"{ADDON}.operators.object_three_point_rotation"]


def test_default_align_mode_is_normals_plus_edge():
    tpr = _tpr()
    ns = SimpleNamespace()
    tpr.IOPS_OT_ThreePointRotation._reset(ns)
    assert ns.rot_mode == tpr.ROT_EDGE
    assert ns.step == tpr.STEP_MOVE


def test_checklist_move_step_edge_mode():
    tpr = _tpr()
    rows = tpr.checklist(tpr.STEP_MOVE, tpr.ROT_EDGE, src_picked=False)
    keys = [k for k, _l, _s in rows]
    assert keys == ["1", "2", "3", "4"]             # apply is always last
    assert [s for _k, _l, s in rows] == ["now", "todo", "todo", "todo"]
    assert "your object" in rows[0][1] and "A" in rows[0][1]
    assert "target" in rows[1][1] and "A′" in rows[1][1]
    assert "normals" in rows[2][1] and "edge" in rows[2][1]
    rows = tpr.checklist(tpr.STEP_MOVE, tpr.ROT_EDGE, src_picked=True)
    assert [s for _k, _l, s in rows] == ["done", "now", "todo", "todo"]


def test_checklist_points_mode_lists_six_picks():
    tpr = _tpr()
    rows = tpr.checklist(tpr.STEP_ROLL, tpr.ROT_POINTS, src_picked=True)
    assert [k for k, _l, _s in rows] == ["1", "2", "3", "4", "5", "6", "7"]
    assert [s for _k, _l, s in rows] == ["done"] * 5 + ["now", "todo"]
    assert "ghost" in rows[2][1]            # B is picked on the ghost
    assert "C′" in rows[5][1]
    rows = tpr.checklist(tpr.STEP_ALIGN, tpr.ROT_NORMAL, src_picked=False)
    assert [k for k, _l, _s in rows] == ["1", "2", "3", "4"]
    assert [s for _k, _l, s in rows] == ["done", "done", "now", "todo"]


def test_checklist_done_offers_apply():
    tpr = _tpr()
    rows = tpr.checklist(tpr.STEP_DONE, tpr.ROT_EDGE, src_picked=False)
    assert [s for _k, _l, s in rows] == ["done", "done", "done", "now"]
    assert "Space" in rows[-1][1]


def test_drawing_uses_theme_roles_only():
    tpr = _tpr()
    assert not hasattr(tpr, "_fade"), "hard-coded alphas are back"


TESTS = [
    test_default_align_mode_is_normals_plus_edge,
    test_checklist_move_step_edge_mode,
    test_checklist_points_mode_lists_six_picks,
    test_checklist_done_offers_apply,
    test_drawing_uses_theme_roles_only,
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
    print(f"OK {len(TESTS)} tests" if not failed
          else f"{len(TESTS) - failed}/{len(TESTS)} passed")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
