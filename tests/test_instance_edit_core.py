import numpy as np
import pytest
from utils.instance_edit_core import (edit_frame, moved, unmoved, to_flat, from_flat,
                                      split_roots, layer_path, split_layer_path,
                                      plan_restore, warnings)

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
