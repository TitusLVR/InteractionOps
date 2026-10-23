import datetime
import hashlib
import os

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
                                      source_changed, commit_temp_paths, point_name,
                                      parse_point, point_user, source_hash, user_tag,
                                      backup_points, prune_backups, point_number, point_stamp,
                                      newer_blender, BACKUP_EXT, BACKUP_SIDECAR_EXT,
                                      BACKUP_SUBFOLDER)

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
    assert p.lock == "D:/lib/Props.blend.iops_lock"
    # Two runs never share a temp file; the lock is per source.
    q = commit_temp_paths("D:/lib/Props.blend", "ffff0000")
    assert {p.temp_blend, p.temp_json, p.result_json}.isdisjoint({q.temp_blend, q.temp_json, q.result_json})
    assert p.lock == q.lock
    assert set(p._fields) == {"temp_blend", "temp_json", "result_json", "lock"}


WHEN = datetime.datetime(2026, 10, 22, 9, 5, 7)


def test_backup_constants():
    assert BACKUP_EXT == ".iopsbackup" and BACKUP_SUBFOLDER == ".iopsbackup"
    assert BACKUP_SIDECAR_EXT == ".iopsbackup.json"


def test_point_name_next_to_source_and_custom():
    assert point_name("Props", "titus", WHEN) == "Props.titus.261022-090507"
    src = "D:/lib/Props.blend"
    digest = hashlib.sha1(os.path.normcase(os.path.normpath(os.path.abspath(src))).encode()).hexdigest()[:8]
    assert source_hash(src) == digest
    assert point_name("Props", "titus", WHEN, source_hash(src)) == f"Props.{digest}.titus.261022-090507"
    # Same stem in another folder: another hash; the same file spelled
    # differently hashes the same.
    assert source_hash("D:/other/Props.blend") != digest
    assert source_hash("D:/lib/sub/../Props.blend") == digest


def test_user_cut_and_sanitised():
    assert user_tag("averyveryverylongname") == "averyveryver"
    assert user_tag("john.doe") == "john_doe" and user_tag("DOM\\me x") == "DOM_me_x"
    assert user_tag("\u0442\u0438\u0442") == "___" and user_tag("") == "unknown"
    assert point_name("a", "john.doe@corp", WHEN) == "a.john_doe_cor.261022-090507"


def test_parse_point():
    assert parse_point("Props.titus.261022-090507") == ("Props", None, "titus", "261022-090507")
    assert parse_point("Props.v2.final.titus.261022-090507") == ("Props.v2.final", None, "titus", "261022-090507")
    assert parse_point("Props.v2.0a1b2c3d.titus.261022-090507") == ("Props.v2", "0a1b2c3d", "titus", "261022-090507")
    # Round trips with dotted stems and sanitised users.
    for stem, user, h in (("a.b.c", "x.y", None), ("a.b", "me", "deadbeef"), ("p", "averyveryverylongname", None)):
        parsed = parse_point(point_name(stem, user, WHEN, h))
        assert parsed == (stem, h, user_tag(user), "261022-090507"), parsed
    for bad in ("Props", "Props.titus", "Props.titus.20261022-090507", "titus.261022-090507",
                "Props.ti tus.261022-090507", "Props.toolongusername1.261022-090507"):
        assert parse_point(bad) is None, bad
    assert point_user("Props.v2.titus.261022-090507") == "titus" and point_user("nope") is None


def test_backup_points_newest_first_only_this_source():
    times = [WHEN + datetime.timedelta(seconds=s) for s in (0, 3600, 60)]
    names = [point_name("Props", u, t) for u, t in zip(("me", "bob", "me"), times)]
    listing = ([n + BACKUP_EXT for n in names] + [n + BACKUP_SIDECAR_EXT for n in names]
               + [point_name("Props.v2", "me", WHEN) + BACKUP_EXT,  # another source, dotted stem
                  point_name("Prop", "me", WHEN) + BACKUP_EXT,
                  point_name("Props_v2", "me", WHEN) + BACKUP_EXT,
                  names[0] + ".iopsbackup.part",  # a copy being written
                  point_name("Props", "me", WHEN, "0a1b2c3d") + BACKUP_EXT,  # custom-folder name
                  "Props.blend", "notes.txt", names[0] + "x" + BACKUP_EXT, names[0] + ".blend"])
    assert backup_points(listing, "Props") == [names[1], names[2], names[0]]
    assert backup_points([n + BACKUP_SIDECAR_EXT for n in names], "Props") == []
    assert backup_points(listing, "Props", ext=BACKUP_SIDECAR_EXT) == [names[1], names[2], names[0]]
    assert backup_points(listing, "Props.v2") == [point_name("Props.v2", "me", WHEN)]
    assert backup_points(listing, "Props_v2") == [point_name("Props_v2", "me", WHEN)]
    assert backup_points(listing, "Props", ext=".iopsbackup.part") == [names[0]]
    assert backup_points([], "Props") == []
    # Custom folder: only names with this source's hash.
    mine = [point_name("Props", "me", t, "0a1b2c3d") for t in times]
    other = point_name("Props", "me", WHEN, "ffffffff")
    custom = [n + BACKUP_EXT for n in mine + [other] + names]
    assert backup_points(custom, "Props", "0a1b2c3d") == [mine[1], mine[2], mine[0]]
    # A next-to-source stem ending in 8 hex is still found by its stem.
    odd = point_name("Props.deadbeef", "me", WHEN)
    assert backup_points([odd + BACKUP_EXT], "Props.deadbeef") == [odd]
    assert backup_points([odd + BACKUP_EXT], "Props") == []


def test_prune_backups_keeps_newest():
    pts = [point_name("Props", "me", WHEN + datetime.timedelta(minutes=m)) for m in (5, 4, 3, 2, 1)]
    assert prune_backups(pts, 3) == pts[3:]
    assert prune_backups(list(reversed(pts)), 2) == pts[2:]
    assert prune_backups(pts, 5) == [] and prune_backups(pts, 50) == []
    assert prune_backups(pts, 1) == pts[1:]
    assert prune_backups([], 3) == []


def test_prune_backups_never_deletes_the_point_just_written():
    pts = [point_name("Props", "me", WHEN + datetime.timedelta(minutes=m)) for m in (5, 4, 3)]
    # A clock set back: the point just written sorts oldest.
    just = point_name("Props", "me", WHEN)
    assert prune_backups(pts + [just], 1, protect=just) == pts
    assert prune_backups(pts + [just], 2, protect=just) == pts[1:]
    assert prune_backups(pts + [just], 4, protect=just) == []
    assert prune_backups(pts, 1, protect=pts[0]) == pts[1:]
    assert prune_backups(pts, 1, protect="gone") == pts[1:]


def test_prune_backups_only_mine():
    t = [WHEN + datetime.timedelta(minutes=m) for m in range(6)]
    mine = [point_name("Props", "me", t[i]) for i in (5, 3, 1)]
    theirs = [point_name("Props", "bob", t[i]) for i in (4, 2, 0)]
    everything = mine + theirs
    # Counting only my points: keep 2 of mine, never touch bob's.
    assert prune_backups(everything, 2, mine=set(mine)) == [mine[2]]
    assert prune_backups(everything, 2, mine=lambda p: point_user(p) == "me") == [mine[2]]
    assert prune_backups(everything, 3, mine=set(mine)) == []
    # Counting all: the oldest of everyone go.
    assert prune_backups(everything, 2) == [mine[1], theirs[1], mine[2], theirs[2]]
    # protect counts as one of mine, even when it sorts oldest.
    just = point_name("Props", "me", WHEN - datetime.timedelta(days=1))
    assert prune_backups(everything + [just], 1, protect=just, mine=set(mine) | {just}) == mine
    assert prune_backups(everything + [just], 2, protect=just, mine=lambda p: point_user(p) == "me") == mine[1:]


def test_backup_names_are_utc():
    plus2 = datetime.timezone(datetime.timedelta(hours=2))
    local = datetime.datetime(2026, 3, 29, 3, 30, 0, tzinfo=plus2)
    assert point_name("P", "me", local).endswith(".260329-013000")
    assert point_name("P", "me", local) == point_name("P", "me", local.astimezone(datetime.timezone.utc))
    # Naive datetimes are taken as UTC.
    assert point_name("P", "me", datetime.datetime(2026, 3, 29, 1, 30)) == point_name("P", "me", local)
    # Across a DST change (CEST -> CET), a later moment never sorts earlier.
    before = datetime.datetime(2026, 10, 25, 2, 59, tzinfo=plus2)
    after = datetime.datetime(2026, 10, 25, 2, 1, tzinfo=datetime.timezone(datetime.timedelta(hours=1)))
    assert after > before and point_name("P", "me", after) > point_name("P", "me", before)


def test_point_number_stable_and_ordered():
    utc = datetime.timezone.utc
    a = point_name("Props", "me", datetime.datetime(2020, 1, 1, 0, 0, 7, tzinfo=utc))
    b = point_name("Props", "me", datetime.datetime(2026, 10, 22, 9, 5, 7, tzinfo=utc))
    assert point_number(a) == 7
    assert point_number(b) > point_number(a)
    assert point_number(b) == point_number(point_name("Props", "bob", datetime.datetime(2026, 10, 22, 9, 5, 7), "0a1b2c3d"))
    assert point_stamp(b) == datetime.datetime(2026, 10, 22, 9, 5, 7, tzinfo=utc)
    # The two-digit year is 20yy, also past 2068 (where %y would wrap).
    late = point_name("P", "me", datetime.datetime(2075, 1, 1, tzinfo=utc))
    assert point_stamp(late).year == 2075 and point_number(late) > point_number(b)
    assert point_number("Props-nostamp") == 0 and point_stamp("Props-nostamp") is None
    assert point_stamp("P.me.261399-000000") is None


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
