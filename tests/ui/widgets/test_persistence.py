"""Pure-pytest tests for ui/widgets/persistence.py — per-file widget UI
state serialization. No bpy."""
from ui.widgets.persistence import (dumps_states, parse_states,
                                    DEFAULT_X, DEFAULT_Y)
import json


def test_round_trip_preserves_visible_xy_switches():
    states = {"w1": {"visible": True, "x": 10.5, "y": 20.0,
                     "anchor_area_ptr": 12345,
                     "switches": {"a": True, "b": False}},
              "w2": {"visible": False, "x": 1.0, "y": 2.0, "switches": {}}}
    out = parse_states(dumps_states(states))
    assert out["w1"]["visible"] is True
    assert out["w1"]["x"] == 10.5 and out["w1"]["y"] == 20.0
    assert out["w1"]["switches"] == {"a": True, "b": False}
    assert out["w2"]["visible"] is False


def test_dumps_strips_runtime_only_keys():
    states = {"w1": {"visible": True, "x": 1.0, "y": 2.0,
                     "anchor_area_ptr": 999, "switches": {}}}
    data = json.loads(dumps_states(states))
    assert "anchor_area_ptr" not in data["w1"]


def test_parse_resets_anchor_to_zero():
    raw = json.dumps({"w1": {"visible": True, "x": 1, "y": 2,
                             "anchor_area_ptr": 777}})
    assert parse_states(raw)["w1"]["anchor_area_ptr"] == 0


def test_parse_malformed_json_returns_empty():
    assert parse_states("not json {") == {}
    assert parse_states("") == {}
    assert parse_states(None) == {}


def test_parse_non_dict_top_level_returns_empty():
    assert parse_states("[1, 2, 3]") == {}
    assert parse_states('"str"') == {}


def test_parse_skips_non_dict_entries():
    raw = json.dumps({"good": {"visible": True}, "bad": [1, 2]})
    out = parse_states(raw)
    assert "good" in out and "bad" not in out


def test_parse_missing_keys_get_defaults():
    out = parse_states(json.dumps({"w": {}}))["w"]
    assert out["visible"] is False
    assert out["x"] == DEFAULT_X and out["y"] == DEFAULT_Y
    assert out["switches"] == {} and out["anchor_area_ptr"] == 0


def test_parse_unparseable_xy_falls_back_to_defaults():
    raw = json.dumps({"w": {"visible": True, "x": "junk", "y": None}})
    out = parse_states(raw)["w"]
    assert out["x"] == DEFAULT_X and out["y"] == DEFAULT_Y
    assert out["visible"] is True


def test_parse_coerces_switch_values_to_bool():
    raw = json.dumps({"w": {"switches": {"s1": 1, "s2": 0, "s3": "x"}}})
    out = parse_states(raw)["w"]
    assert out["switches"] == {"s1": True, "s2": False, "s3": True}


def test_parse_non_dict_switches_ignored():
    raw = json.dumps({"w": {"switches": [1, 2]}})
    assert parse_states(raw)["w"]["switches"] == {}
