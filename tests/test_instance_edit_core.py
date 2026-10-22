import numpy as np
import pytest
from utils.instance_edit_core import (edit_frame, moved, unmoved, to_flat, from_flat,
                                      split_roots, layer_path, split_layer_path,
                                      plan_restore, warnings, is_similarity)

def rot_z(deg):
    c, s = np.cos(np.radians(deg)), np.sin(np.radians(deg))
    return np.array([[c,-s,0,0],[s,c,0,0],[0,0,1,0],[0,0,0,1.0]])

def test_edit_frame_offset_rotation_scale():
    M = rot_z(90) @ np.diag([2,2,2,1.0]); M[:3,3] = (10, 0, 0)
    A = edit_frame(M, (1, 0, 0))
    # a collection point at the offset itself sits on the instancer origin
    assert np.allclose(A @ np.array([1,0,0,1.0]), [10,0,0,1])
    # a point one unit past the offset along X lands rotated+scaled: (10, 2, 0)
    assert np.allclose(A @ np.array([2,0,0,1.0]), [10,2,0,1])

def test_moved_unmoved_round_trip():
    A = edit_frame(rot_z(33) @ np.diag([1,3,0.5,1.0]), (0.2,-1,4))
    W = rot_z(-70); W[:3,3] = (3,4,5)
    assert np.allclose(unmoved(A, moved(A, W)), W)

def test_flat_round_trip():
    W = rot_z(10); W[:3,3] = (1,2,3)
    assert np.allclose(from_flat(to_flat(W)), W) and len(to_flat(W)) == 16

def test_split_roots_parent_outside_is_root():
    roots, children = split_roots(["a","b","c"], {"a": None, "b": "a", "c": "ext"})
    assert roots == ["a","c"] and children == ["b"]

def test_split_roots_ancestor_through_outside_is_child():
    assert split_roots(["Cube","R"], {"Cube": None, "R": "Outside", "Outside": "Cube"}) == (["Cube"], ["R"])

def test_split_roots_chain_inside():
    roots, children = split_roots(["x","y","z"], {"x": None, "y": "x", "z": "y"})
    assert roots == ["x"] and children == ["y","z"]

def test_layer_path_round_trip_with_slash_in_name():
    names = ["Scene Collection", "Props/Kit", "Asset"]
    assert split_layer_path(layer_path(names)) == names

def test_plan_restore_reports_missing():
    class R:  # mimics a PropertyGroup row
        def __init__(self, n): self.name = n
    rows = [R("a"), R("gone"), R("b")]
    keep, missing = plan_restore(rows, {"a","b"})
    assert [r.name for r in keep] == ["a","b"] and missing == ["gone"]

def test_warnings_lines():
    assert warnings([{"name":"a","has_transform_anim":False,"has_transform_constraint":False}]) == []
    out = warnings([{"name":"a","has_transform_anim":True,"has_transform_constraint":True},
                    {"name":"b","has_transform_anim":False,"has_transform_constraint":True}])
    assert out == ["Do not edit these objects or change the frame while editing:",
                   "a: animated/driven transform", "a: transform constraint",
                   "b: transform constraint"]

def test_is_similarity_uniform_scale_rotation():
    M = rot_z(37) @ np.diag([2.5, 2.5, 2.5, 1.0]); M[:3, 3] = (12345.678, -9876.5, 321)
    assert is_similarity(edit_frame(M, (1, 2, 3)))
    assert is_similarity(np.eye(4))
    # A mirror is still a similarity (negative determinant).
    assert is_similarity(rot_z(10) @ np.diag([-1.0, 1, 1, 1]))

def test_is_similarity_non_uniform_scale():
    assert not is_similarity(rot_z(90) @ np.diag([1, 3, 1, 1.0]))
    assert not is_similarity(np.diag([1, 1, 1.001, 1.0]))

def test_is_similarity_shear():
    S = np.eye(4); S[0, 1] = 0.5
    assert not is_similarity(S)
    # Rotation under a non-uniformly scaled parent: sheared.
    assert not is_similarity(np.diag([1, 2, 1, 1.0]) @ rot_z(30))

def test_is_similarity_zero_scale():
    assert not is_similarity(np.diag([0, 0, 0, 1.0]))
    assert not is_similarity(np.diag([1, 1, 0, 1.0]))
    assert not is_similarity(np.diag([1e-4, 1e-4, 1e-4, 1.0]))  # |det| 1e-12


from utils.instance_edit_core import (OwnedRow, merge_plan, plans_match,
                                      source_changed, commit_temp_paths, backup_paths,
                                      newer_blender)

ROWS = [OwnedRow(0, "objects", "Cube", "Cube"), OwnedRow(1, "materials", "SharedMat", "SharedMat.001"),
        OwnedRow(2, "meshes", "NewMeshFromSrc", "NewMeshFromSrc")]
TAGGED = {0: ("objects", "Cube.001"), 1: ("materials", "SharedMat.002"), 2: ("meshes", "NewMeshFromSrc")}
EXISTING = {("objects", "Cube"), ("materials", "SharedMat"), ("objects", "Lamp")}
OUTSIDE = {("materials", "SharedMat")}

def test_merge_plan_exclusive_replaced_shared_kept_by_default():
    p = merge_plan(ROWS, TAGGED, [], EXISTING, OUTSIDE, set())
    assert p["replaced"] == [("objects", "Cube")]
    assert p["kept"] == [("materials", "SharedMat")]
    assert p["shared"] == [("materials", "SharedMat")]
    assert p["added"] == [("meshes", "NewMeshFromSrc")]

def test_merge_plan_ticked_shared_is_replaced():
    p = merge_plan(ROWS, TAGGED, [], EXISTING, OUTSIDE, {("materials", "SharedMat")})
    assert ("materials", "SharedMat") in p["replaced"] and p["kept"] == []

def test_merge_plan_user_name_collision_is_added():
    p = merge_plan(ROWS, TAGGED, [("objects", "Lamp.001")], EXISTING, OUTSIDE, set())
    assert ("objects", "Lamp.001") in p["added"] and ("objects", "Lamp") not in p["replaced"]

def test_plans_match_ignores_order_compares_membership():
    a = merge_plan(ROWS, TAGGED, [], EXISTING, OUTSIDE, set()); b = dict(a)
    b["replaced"] = list(reversed(a["replaced"]))
    assert plans_match(a, b)
    assert plans_match(a, {k: [list(x) for x in v] for k, v in b.items()})  # JSON lists
    for key in ("unlinked", "deleted", "discarded"):
        c = dict(a); c[key] = [("objects", "x")]
        assert not plans_match(a, c), key

def test_source_changed():
    assert not source_changed((100.0, 5), (100.0004, 5))
    assert source_changed((100.0, 5), (100.0, 6)) and source_changed((100.0, 5), (101.0, 5))

def test_commit_temp_paths():
    p = commit_temp_paths("D:/lib/Props.blend", "1a2b3c4d")
    assert p.temp_blend.endswith("Props.iops_commit-1a2b3c4d.blend")
    assert p.temp_json.endswith("Props.iops_commit-1a2b3c4d.json")
    assert p.result_json.endswith("Props.iops_commit-1a2b3c4d.result.json")
    # The backup has no .blend extension: asset libraries never index it.
    assert p.backup == "D:/lib/Props.blend.iops_bak" and not p.backup.endswith(".blend")
    assert p.sidecar == "D:/lib/Props.blend.iops_bak.json"
    assert p.lock == "D:/lib/Props.blend.iops_lock"
    assert backup_paths("D:/lib/Props.blend") == (p.backup, p.sidecar)
    # Two runs never share a temp file; backup, sidecar and lock are per source.
    q = commit_temp_paths("D:/lib/Props.blend", "ffff0000")
    assert {p.temp_blend, p.temp_json, p.result_json}.isdisjoint({q.temp_blend, q.temp_json, q.result_json})
    assert (p.backup, p.sidecar, p.lock) == (q.backup, q.sidecar, q.lock)


@pytest.mark.parametrize("run_id", ["", None, "../x", "a.b"])
def test_commit_temp_paths_rejects_bad_run_id(run_id):
    with pytest.raises(ValueError):
        commit_temp_paths("D:/lib/Props.blend", run_id)


@pytest.mark.parametrize("source, running, newer", [
    ((5, 3, 1), (5, 2, 45), True),
    ((6, 0, 0), (5, 2, 45), True),
    ((5, 2, 99), (5, 2, 45), False),   # file subversion / patch ignored
    ((5, 2, 0), (5, 2, 45), False),
    ((4, 5, 7), (5, 2, 45), False),    # older: upgraded on save, warned only
    ([5, 3, 0], [5, 2, 0], True),      # JSON lists
    (None, (5, 2, 0), False),
    ((), (5, 2, 0), False),
])
def test_newer_blender(source, running, newer):
    assert newer_blender(source, running) is newer


def test_merge_plan_tagged_missing_original_added_with_source_name():
    rows = [OwnedRow(3, "meshes", "New", "New.001")]
    p = merge_plan(rows, {3: ("meshes", "New.002")}, [], set(), set(), set())
    assert ("meshes", "New") in p["added"] and ("meshes", "New.002") not in p["added"]


from utils.instance_edit_core import ticked_plan_problem


def _plan(**kw):
    p = {k: [] for k in ("replaced", "added", "kept", "shared", "unlinked", "deleted", "discarded")}
    p.update({k: [list(x) for x in v] for k, v in kw.items()})
    return p


MAT, MESH, OBJ, COLL = ("materials", "M"), ("meshes", "BothMesh"), ("objects", "Both"), ("collections", "D")


def test_ticked_plan_accepts_kept_to_replaced_with_pulled_dependency():
    confirmed = _plan(replaced=[("objects", "Cube")], kept=[MAT, MESH, OBJ], shared=[MAT, MESH, OBJ])
    ticked = _plan(replaced=[("objects", "Cube"), MESH, OBJ], kept=[MAT], shared=[MAT, MESH, OBJ])
    assert ticked_plan_problem(confirmed, ticked, {OBJ}) is None


def test_ticked_plan_accepts_rescued_discarded_and_membership_changes():
    x = ("objects", "XNew")
    confirmed = _plan(kept=[COLL], shared=[COLL], discarded=[x])
    ticked = _plan(replaced=[COLL], shared=[COLL], added=[x], unlinked=[("objects", "Old")])
    assert ticked_plan_problem(confirmed, ticked, {COLL}) is None


def test_ticked_plan_rejects_other_changes():
    confirmed = _plan(replaced=[("objects", "Cube")], kept=[MAT], shared=[MAT])
    # Ticked ID not replaced.
    assert ticked_plan_problem(confirmed, confirmed, {MAT})
    # Shared set changed (the source changed meanwhile).
    assert ticked_plan_problem(confirmed, _plan(replaced=[("objects", "Cube"), MAT], shared=[MAT, MESH]), {MAT})
    # Something replaced before is not any more.
    assert ticked_plan_problem(confirmed, _plan(replaced=[MAT], shared=[MAT]), {MAT})
    # A new added ID that was not discarded before.
    assert ticked_plan_problem(
        confirmed, _plan(replaced=[("objects", "Cube"), MAT], shared=[MAT], added=[("objects", "Z")]), {MAT})
    # An unticked kept ID may stay kept.
    two = _plan(kept=[MAT, MESH], shared=[MAT, MESH])
    assert ticked_plan_problem(two, _plan(replaced=[MAT], kept=[MESH], shared=[MAT, MESH]), {MAT}) is None
