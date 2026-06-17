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


# ----------------------------------------------------------------------
# RNA path resolver + bool adapter
# ----------------------------------------------------------------------
class _Obj:
    pass


def _fake_context():
    ctx = _Obj()
    ctx.scene = _Obj()
    ctx.scene.CCP = _Obj()
    ctx.scene.CCP.flag = True
    return ctx


def test_resolve_rna_owner_walks_path():
    ctx = _fake_context()
    owner, attr = composed.resolve_rna_owner(ctx, "scene.CCP.flag")
    assert owner is ctx.scene.CCP and attr == "flag"


def test_resolve_rna_owner_missing_returns_none():
    ctx = _fake_context()
    owner, attr = composed.resolve_rna_owner(ctx, "scene.NOPE.flag")
    assert owner is None and attr is None


def test_rna_bool_adapter_get_set():
    ctx = _fake_context()
    ad = composed.rna_bool_adapter("scene.CCP.flag")
    assert ad["get"](ctx) == (True, False)
    ad["set"](ctx, False)
    assert ctx.scene.CCP.flag is False
    # Missing path -> disabled sentinel, set is a no-op (no raise)
    bad = composed.rna_bool_adapter("scene.NOPE.flag")
    assert bad["get"](ctx) == (None, False)
    bad["set"](ctx, True)


# ----------------------------------------------------------------------
# FLIPBOX prop + ROW
# ----------------------------------------------------------------------
def test_validate_flipbox_prop():
    wdef, errors = composed.validate_def({
        "name": "w",
        "rows": [
            {"type": "FLIPBOX", "prop": "scene.CCP.red_export_opaqueAreas",
             "label": "Opaque"},
            {"type": "FLIPBOX", "prop": "scene.CCP.x"},   # label defaults
        ],
    })
    assert errors == []
    assert wdef["rows"][0]["prop"] == "scene.CCP.red_export_opaqueAreas"
    assert wdef["rows"][0]["label"] == "Opaque"
    assert wdef["rows"][1]["label"] == "x"   # last path segment


def test_validate_flipbox_needs_exactly_one_of_prop_target():
    wdef, errors = composed.validate_def({
        "name": "w",
        "rows": [
            {"type": "FLIPBOX"},                                   # neither
            {"type": "FLIPBOX", "prop": "scene.x", "target": "SEAM"},  # both
        ],
    })
    assert wdef["rows"] == []
    assert len(errors) == 2


def test_validate_row_grouping():
    wdef, errors = composed.validate_def({
        "name": "w",
        "rows": [
            {"type": "ROW", "cells": [
                {"type": "FLIPBOX", "prop": "scene.CCP.x", "label": "X"},
                {"type": "BUTTON", "label": "Export", "op": "ccp.do"},
            ]},
            {"type": "ROW", "cells": []},                  # empty -> drop
            {"type": "ROW", "cells": [{"type": "NOPE"}]},  # all bad -> drop
        ],
    })
    assert len(wdef["rows"]) == 1
    row = wdef["rows"][0]
    assert row["type"] == "ROW" and len(row["cells"]) == 2
    assert row["cells"][0]["type"] == "FLIPBOX"
    assert row["cells"][1]["type"] == "BUTTON"
    assert len(errors) >= 2


def test_validate_row_rejects_nested_row():
    wdef, errors = composed.validate_def({
        "name": "w",
        "rows": [{"type": "ROW", "cells": [
            {"type": "ROW", "cells": [{"type": "SECTION", "label": "x"}]},
        ]}],
    })
    assert wdef["rows"] == []   # only cell was a nested ROW -> dropped -> empty
    assert errors


# ----------------------------------------------------------------------
# SWATCH row type + rna_color_adapter
# ----------------------------------------------------------------------
def test_validate_swatch_minimal():
    data = {"name": "oc", "rows": [
        {"type": "SWATCH", "prop": "scene.IOPS.iops_object_color",
         "op": "iops.object_color_apply"}]}
    wdef, errors = composed.validate_def(data)
    assert errors == []
    assert wdef["rows"][0] == {
        "type": "SWATCH", "prop": "scene.IOPS.iops_object_color",
        "op": "iops.object_color_apply", "label": "", "op_kwargs": {}}


def test_validate_swatch_with_kwargs_and_label():
    data = {"name": "oc", "rows": [
        {"type": "SWATCH", "prop": "scene.IOPS.iops_object_color_recent_0",
         "op": "iops.object_color_apply_recent",
         "op_kwargs": {"index": 0}, "label": "1"}]}
    wdef, errors = composed.validate_def(data)
    assert errors == []
    r = wdef["rows"][0]
    assert r["op_kwargs"] == {"index": 0}
    assert r["label"] == "1"


def test_validate_swatch_missing_prop_dropped():
    data = {"name": "oc", "rows": [{"type": "SWATCH", "op": "iops.x"}]}
    wdef, errors = composed.validate_def(data)
    assert wdef["rows"] == []
    assert errors


def test_validate_swatch_bad_op_dropped():
    data = {"name": "oc", "rows": [
        {"type": "SWATCH", "prop": "scene.IOPS.iops_object_color",
         "op": "nodothere"}]}
    wdef, errors = composed.validate_def(data)
    assert wdef["rows"] == []
    assert errors


def test_validate_swatch_inside_row_cells():
    data = {"name": "oc", "rows": [{"type": "ROW", "cells": [
        {"type": "SWATCH", "prop": "scene.IOPS.iops_object_color_recent_0",
         "op": "iops.object_color_apply_recent", "op_kwargs": {"index": 0}},
        {"type": "SWATCH", "prop": "scene.IOPS.iops_object_color_recent_1",
         "op": "iops.object_color_apply_recent", "op_kwargs": {"index": 1}},
    ]}]}
    wdef, errors = composed.validate_def(data)
    assert errors == []
    cells = wdef["rows"][0]["cells"]
    assert len(cells) == 2
    assert cells[0]["op_kwargs"] == {"index": 0}
    assert cells[1]["prop"].endswith("recent_1")


def test_rna_color_adapter_reads_tuple():
    ad = composed.rna_color_adapter("scene.IOPS.iops_object_color")

    class _P: pass
    class _S: pass
    class _C: pass
    p = _P(); p.iops_object_color = (0.1, 0.2, 0.3, 1.0)
    s = _S(); s.IOPS = p
    c = _C(); c.scene = s
    assert ad["get"](c) == ((0.1, 0.2, 0.3, 1.0), False)


def test_rna_color_adapter_absent_is_disabled_sentinel():
    ad = composed.rna_color_adapter("scene.IOPS.iops_object_color")

    class _C: pass
    c = _C(); c.scene = None
    assert ad["get"](c) == (None, False)
