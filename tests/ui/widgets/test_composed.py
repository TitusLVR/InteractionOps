"""Pure-logic tests for widgets/composed.py — schema validation, name
helpers, preset parsing and the flipbox row-merge. No bpy/bmesh needed:
the module defers those imports to call time."""
import importlib.util
import os
import sys

_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__),
                                      "..", "..", ".."))


def _load_composed():
    """Load widgets/composed.py standalone — importing the widgets package
    would pull in the addon root (bpy)."""
    path = os.path.join(_ROOT, "widgets", "composed.py")
    spec = importlib.util.spec_from_file_location("iops_test_composed", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


composed = _load_composed()


# ----------------------------------------------------------------------
# sanitize / unique / parse_values
# ----------------------------------------------------------------------
def test_sanitize_strips_and_replaces():
    assert composed.sanitize_name('  my<bad>:name  ') == "my_bad__name"
    assert composed.sanitize_name("ok_name") == "ok_name"


def test_unique_name():
    taken = {"w", "w_2"}
    assert composed.unique_name("w", taken) == "w_3"
    assert composed.unique_name("fresh", taken) == "fresh"


def test_parse_values():
    assert composed.parse_values("0, 0.25, 0.5, 1.0") == [0, 0.25, 0.5, 1.0]
    assert composed.parse_values(" 0.9 ,bad, 2.0,,-1") == [0.9, 1.0, 0.0]
    assert composed.parse_values("") == []


# ----------------------------------------------------------------------
# validate_def
# ----------------------------------------------------------------------
def test_validate_rejects_non_dict_and_unnamed():
    wdef, errors = composed.validate_def([])
    assert wdef is None and errors
    wdef, errors = composed.validate_def({"rows": []})
    assert wdef is None and errors


def test_validate_full_edge_data_def_is_clean():
    wdef, errors = composed.validate_def(composed.EDGE_DATA_DEF)
    assert errors == []
    assert wdef["name"] == "edge_data"
    assert len(wdef["rows"]) == len(composed.EDGE_DATA_DEF["rows"])


def test_validate_drops_bad_rows_keeps_good():
    wdef, errors = composed.validate_def({
        "name": "w",
        "rows": [
            {"type": "SLIDER", "target": "BEVEL"},
            {"type": "SLIDER", "target": "SHARP"},      # bool target: drop
            {"type": "NOPE"},                            # unknown: drop
            {"type": "PRESETS", "target": "CREASE", "values": ["x"]},  # drop
            {"type": "BUTTON", "op": "noidname"},        # no dot: drop
            {"type": "FLIPBOX", "target": "SEAM"},
            "not a dict",                                # drop
        ],
    })
    assert len(wdef["rows"]) == 2
    assert wdef["rows"][0]["type"] == "SLIDER"
    assert wdef["rows"][1]["type"] == "FLIPBOX"
    assert wdef["rows"][1]["label"] == "Seam"   # label defaulted from target
    assert len(errors) == 5


def test_validate_normalizes_values_and_defaults():
    wdef, _ = composed.validate_def({
        "name": "w",
        "rows": [
            {"type": "SLIDER", "target": "bevel", "snap": "bogus"},
            {"type": "PRESETS", "target": "CREASE",
             "values": [0, "0.5", 2.0, None]},
            {"type": "BUTTON", "op": "iops.executor", "role": "fancy"},
        ],
    })
    assert wdef["rows"][0]["target"] == "BEVEL"
    assert wdef["rows"][0]["snap"] == 0.125
    assert wdef["rows"][1]["values"] == [0.0, 0.5, 1.0]   # clamped, Nones out
    assert wdef["rows"][2]["role"] == "default"


# ----------------------------------------------------------------------
# merge_flipbox_runs
# ----------------------------------------------------------------------
def _r(t):
    return {"type": t}


def test_merge_groups_adjacent_flipboxes():
    rows = [_r("SECTION"), _r("FLIPBOX"), _r("FLIPBOX"), _r("FLIPBOX"),
            _r("BUTTON")]
    merged = composed.merge_flipbox_runs(rows)
    assert len(merged) == 3
    assert isinstance(merged[1], list) and len(merged[1]) == 3


def test_merge_single_flipbox_stays_single():
    rows = [_r("FLIPBOX"), _r("SECTION"), _r("FLIPBOX")]
    merged = composed.merge_flipbox_runs(rows)
    assert all(not isinstance(m, list) for m in merged)
    assert len(merged) == 3


def test_merge_trailing_run():
    rows = [_r("SECTION"), _r("FLIPBOX"), _r("FLIPBOX")]
    merged = composed.merge_flipbox_runs(rows)
    assert isinstance(merged[-1], list) and len(merged[-1]) == 2
