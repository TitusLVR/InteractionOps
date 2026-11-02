"""Headless test of iops.object_search_rename (Search & Replace rename) on
real objects: names swapped inside the selection must not pick up .001
suffixes, an invalid regex must leave every name alone, and the .001
suffix survives unless [E] is set. Run from the repo root via:

    blender --background --factory-startup --python-exit-code 1 --python tests/blender/test_object_search_rename.py

Not collected by pytest (tests/conftest.py ignores tests/blender).
"""
import os
import sys
import traceback

import bpy

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
    assert os.path.samefile(loaded, repo_root), "addon loaded from %s" % loaded


def _scene(*names, select=None):
    """Fresh empties named `names`; `select` (default: all) are selected."""
    for ob in list(bpy.data.objects):
        bpy.data.objects.remove(ob)
    coll = bpy.context.scene.collection
    objs = []
    for n in names:
        ob = bpy.data.objects.new(n, None)
        coll.objects.link(ob)
        objs.append(ob)
    picked = names if select is None else select
    for ob in objs:
        ob.select_set(ob.name in picked)
    bpy.context.view_layer.objects.active = objs[0]
    return objs


def _names():
    return sorted(ob.name for ob in bpy.data.objects)


def test_swap_inside_selection_gets_no_suffix():
    _scene("Left", "Right")
    bpy.ops.iops.object_search_rename(search_for="Left|Right", replace_with="Right|Left")
    assert _names() == ["Left", "Right"], _names()


def test_only_selected_are_renamed():
    _scene("SM_A", "SM_B", "SM_C", select=("SM_A", "SM_B"))
    bpy.ops.iops.object_search_rename(search_for="SM_", replace_with="P_")
    assert _names() == ["P_A", "P_B", "SM_C"], _names()


def test_active_used_when_nothing_selected():
    _scene("SM_A", "SM_B", select=())
    bpy.ops.iops.object_search_rename(search_for="SM_", replace_with="")
    assert _names() == ["A", "SM_B"], _names()


def test_invalid_regex_cancels():
    _scene("abc")
    try:
        bpy.ops.iops.object_search_rename(search_for="(", use_regex=True)
    except RuntimeError:
        pass  # the operator's ERROR report is raised in background mode
    assert _names() == ["abc"], _names()


def test_suffix_kept_and_case_applied():
    _scene("rock.001", "rock.002")
    bpy.ops.iops.object_search_rename(search_for="rock", replace_with="stone", case_mode="UPPER")
    assert _names() == ["STONE.001", "STONE.002"], _names()


def test_suffix_removed_with_e_collides_into_blender_suffix():
    _scene("Cube.001", "Cube.002")
    bpy.ops.iops.object_search_rename(search_for=".00?", replace_with="", include_suffix=True)
    names = _names()
    assert names[0] == "Cube" and names[1].startswith("Cube."), names


TESTS = [
    test_swap_inside_selection_gets_no_suffix,
    test_only_selected_are_renamed,
    test_active_used_when_nothing_selected,
    test_invalid_regex_cancels,
    test_suffix_kept_and_case_applied,
    test_suffix_removed_with_e_collides_into_blender_suffix,
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
