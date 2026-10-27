"""Pure-logic tests for widgets/composed.py — schema validation, name
helpers, preset parsing and the flipbox row-merge. No bpy/bmesh needed:
the module defers those imports to call time."""
import importlib.util
import math
import os
import sys

import pytest

_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__),
                                      "..", "..", ".."))


def _load_composed():
    """Load widgets/composed.py with package context for relative imports.
    Ensures build_controls can import ui.widgets controls."""
    if _ROOT not in sys.path:
        sys.path.insert(0, _ROOT)

    # Simply use normal import - ui.widgets is importable without bpy
    # since ui/widgets/__init__.py guards its bpy imports
    composed_mod = importlib.import_module("widgets.composed")
    return composed_mod


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


def test_validate_prop_slider():
    wdef, errors = composed.validate_def({
        "name": "w",
        "rows": [
            {"type": "SLIDER", "prop": "space_data.shading.studiolight_rotate_z",
             "value_type": "DEGREES", "min": -180, "max": 180,
             "snap": 15, "fmt": "{:.0f}°"},
            {"type": "SLIDER", "prop": "scene.x"},                    # defaults
            {"type": "SLIDER", "prop": "scene.x", "target": "BEVEL"},  # both: drop
            {"type": "SLIDER", "prop": "scene.x", "value_type": "ENUM"},  # drop
            {"type": "SLIDER", "prop": "scene.x", "min": 1, "max": 1},    # drop
        ],
    })
    assert len(wdef["rows"]) == 2
    r = wdef["rows"][0]
    assert (r["min"], r["max"], r["snap"]) == (-180.0, 180.0, 15.0)
    assert r["value_type"] == "DEGREES" and r["fmt"] == "{:.0f}°"
    d = wdef["rows"][1]
    assert (d["min"], d["max"], d["snap"]) == (0.0, 1.0, 0.0)
    assert d["value_type"] == "FLOAT"
    assert len(errors) == 3


def test_prop_slider_is_not_edge_bound():
    rows = [{"type": "SLIDER", "prop": "scene.x", "value_type": "FLOAT",
             "min": 0, "max": 1}]
    assert composed.attribute_domains(rows) == set()


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
    assert wdef["rows"][0]["attribute"] == "bevel_weight_edge"
    assert wdef["rows"][0]["domain"] == "EDGE"
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


# ---- merge interaction with show_if ------------------------------------
def test_merge_excludes_show_if_flipboxes():
    rows = [
        {"type": "FLIPBOX", "target": "SHARP", "label": "Sharp"},
        {"type": "FLIPBOX", "target": "SEAM", "label": "Seam",
         "show_if": {"switch": "adv"}},
        {"type": "FLIPBOX", "target": "FREESTYLE", "label": "FS"},
    ]
    merged = composed.merge_flipbox_runs(rows)
    # Sharp stands alone (run broken by the show_if box), the show_if box
    # stands alone, FS stands alone — no 2+ run forms.
    assert all(not isinstance(m, list) for m in merged)
    assert len(merged) == 3


def test_merge_still_groups_plain_flipboxes():
    rows = [
        {"type": "FLIPBOX", "target": "SHARP", "label": "Sharp"},
        {"type": "FLIPBOX", "target": "SEAM", "label": "Seam"},
    ]
    merged = composed.merge_flipbox_runs(rows)
    assert len(merged) == 1 and isinstance(merged[0], list)
    assert len(merged[0]) == 2


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


# ---- show_if validation ------------------------------------------------
def test_show_if_valid_attached():
    wdef, errors = composed.validate_def({
        "name": "w",
        "rows": [
            {"type": "SECTION", "label": "Adv",
             "show_if": {"switch": "adv"}},
            {"type": "BUTTON", "label": "Go", "op": "iops.executor",
             "show_if": {"mode": "EDIT_MESH", "object_type": ["MESH"]}},
        ],
    })
    assert errors == []
    assert wdef["rows"][0]["show_if"] == {"switch": "adv"}
    assert wdef["rows"][1]["show_if"]["mode"] == ["EDIT_MESH"]
    assert wdef["rows"][1]["show_if"]["object_type"] == ["MESH"]


def test_show_if_invalid_keeps_row_reports():
    wdef, errors = composed.validate_def({
        "name": "w",
        "rows": [
            {"type": "SECTION", "label": "X", "show_if": {"selection": "x"}},
        ],
    })
    # Row survives (no show_if attached), error reported.
    assert len(wdef["rows"]) == 1
    assert "show_if" not in wdef["rows"][0]
    assert any("show_if" in e for e in errors)


def test_show_if_normalizes_mode_and_selection():
    clean, err = composed._clean_show_if(
        {"mode": "edit_mesh", "selection": "EDGES"})
    assert err is None
    assert clean == {"mode": ["EDIT_MESH"], "selection": "edges"}


def test_show_if_equals_preserved():
    clean, err = composed._clean_show_if({"switch": "n", "equals": False})
    assert err is None
    assert clean == {"switch": "n", "equals": False}


def test_validate_swatch_literal_color():
    data = {"name": "vc", "rows": [
        {"type": "SWATCH", "color": [1, 0, 0, 1], "op": "iops.x.y",
         "label": "R"}]}
    wdef, errors = composed.validate_def(data)
    assert errors == []
    r = wdef["rows"][0]
    assert r["color"] == [1.0, 0.0, 0.0, 1.0]
    assert "prop" not in r
    assert r["op"] == "iops.x.y"
    assert r["label"] == "R"


def test_validate_swatch_color_and_prop_dropped():
    data = {"name": "vc", "rows": [
        {"type": "SWATCH", "color": [1, 0, 0, 1],
         "prop": "scene.IOPS.iops_object_color", "op": "iops.x.y"}]}
    wdef, errors = composed.validate_def(data)
    assert wdef["rows"] == []
    assert errors


def test_validate_swatch_neither_color_nor_prop_dropped():
    data = {"name": "vc", "rows": [{"type": "SWATCH", "op": "iops.x.y"}]}
    wdef, errors = composed.validate_def(data)
    assert wdef["rows"] == []
    assert errors


def test_validate_swatch_bad_color_dropped():
    data = {"name": "vc", "rows": [
        {"type": "SWATCH", "color": [1, 0, 0], "op": "iops.x.y"}]}
    wdef, errors = composed.validate_def(data)
    assert wdef["rows"] == []
    assert errors


def test_validate_swatch_show_alpha():
    data = {"name": "vc", "rows": [
        {"type": "SWATCH", "color": [0.5, 0.5, 0.5, 0], "op": "iops.x.y",
         "show_alpha": True}]}
    wdef, errors = composed.validate_def(data)
    assert errors == []
    assert wdef["rows"][0]["show_alpha"] is True


def test_validate_swatch_no_show_alpha_key_when_absent():
    data = {"name": "vc", "rows": [
        {"type": "SWATCH", "color": [1, 0, 0, 1], "op": "iops.x.y"}]}
    wdef, errors = composed.validate_def(data)
    assert "show_alpha" not in wdef["rows"][0]


# ---- switch flipbox + switches map -------------------------------------
def test_flipbox_switch_binding():
    wdef, errors = composed.validate_def({
        "name": "w",
        "rows": [{"type": "FLIPBOX", "switch": "adv", "label": "Advanced"}],
    })
    assert errors == []
    row = wdef["rows"][0]
    assert row["switch"] == "adv" and row["label"] == "Advanced"
    assert "target" not in row and "prop" not in row


def test_flipbox_requires_exactly_one_binding():
    # zero bindings
    wdef, _ = composed.validate_def(
        {"name": "w", "rows": [{"type": "FLIPBOX", "label": "x"}]})
    assert wdef["rows"] == []
    # two bindings
    wdef, _ = composed.validate_def({
        "name": "w",
        "rows": [{"type": "FLIPBOX", "switch": "a", "target": "SHARP"}]})
    assert wdef["rows"] == []


def test_switches_map_defaults():
    wdef, errors = composed.validate_def({
        "name": "w",
        "switches": {"adv": True, "bad": "yes"},
        "rows": [],
    })
    assert wdef["switches"] == {"adv": True, "bad": True}


def test_collect_switches_from_refs_and_map():
    wdef, _ = composed.validate_def({
        "name": "w",
        "switches": {"adv": True},
        "rows": [
            {"type": "FLIPBOX", "switch": "adv", "label": "Adv"},
            {"type": "SECTION", "label": "extra",
             "show_if": {"switch": "more"}},
        ],
    })
    sw = composed.collect_switches(wdef)
    assert sw == {"adv": True, "more": False}


# ---- switch adapter + build_controls predicate attach ------------------
def test_switch_adapter_get_set_and_on_change():
    store = {}
    seen = []
    ad = composed.switch_adapter(store, "adv",
                                 on_change=lambda n, v: seen.append((n, v)))
    assert ad["get"](None) == (False, False)
    ad["set"](None, True)
    assert store["adv"] is True
    assert ad["get"](None) == (True, False)
    assert seen == [("adv", True)]


def test_build_controls_attaches_show_if():
    rows = [
        {"type": "SECTION", "label": "A", "show_if": {"switch": "adv"}},
        {"type": "BUTTON", "label": "Go", "op": "iops.executor"},
    ]
    store = {}
    ctrls = composed.build_controls(rows, switch_store=store)
    assert ctrls[0]._show_if == {"switch": "adv"}
    assert ctrls[1]._show_if is None


def test_build_controls_switch_flipbox_uses_store():
    rows = [{"type": "FLIPBOX", "switch": "adv", "label": "Adv"}]
    store = {}
    ctrls = composed.build_controls(rows, switch_store=store)
    fb = ctrls[0]
    # FlipBox get/set wired to the store.
    assert fb.get(None) == (False, False)
    fb.set(None, True)
    assert store["adv"] is True


# ======================================================================
# Input controls — DROPDOWN / INPUT / BUTTONS
# ======================================================================

# ---- _coerce / _to_display (every value_type) --------------------------
def test_coerce_string():
    assert composed._coerce("STRING", 5) == "5"
    assert composed._coerce("STRING", "hi") == "hi"


def test_coerce_int():
    assert composed._coerce("INT", "3") == 3
    assert composed._coerce("INT", 4.0) == 4
    assert isinstance(composed._coerce("INT", 4.0), int)


def test_coerce_float():
    assert composed._coerce("FLOAT", "0.5") == pytest.approx(0.5)
    assert isinstance(composed._coerce("FLOAT", 2), float)


def test_coerce_enum_is_str():
    assert composed._coerce("ENUM", "SOLID") == "SOLID"


def test_coerce_radians_identity():
    assert composed._coerce("RADIANS", 1.5) == pytest.approx(1.5)
    assert composed._coerce("RADIANS", "0.25") == pytest.approx(0.25)


def test_coerce_degrees_converts_to_radians():
    # Author space (degrees) -> storage space (radians) on write.
    assert composed._coerce("DEGREES", 90) == pytest.approx(math.radians(90))
    assert composed._coerce("DEGREES", "180") == pytest.approx(math.pi)


def test_to_display_degrees_converts_to_degrees():
    # Storage space (radians) -> author space (degrees) on read.
    assert composed._to_display("DEGREES", math.radians(90)) == \
        pytest.approx(90)


def test_to_display_radians_identity():
    assert composed._to_display("RADIANS", 1.25) == pytest.approx(1.25)


def test_to_display_non_converting_types_are_identity():
    for vt in ("STRING", "INT", "FLOAT", "ENUM"):
        assert composed._to_display(vt, 42) == 42
    assert composed._to_display("STRING", "x") == "x"


def test_degrees_round_trip():
    # _to_display(_coerce(deg)) == deg, and _coerce(_to_display(rad)) == rad.
    assert composed._to_display(
        "DEGREES", composed._coerce("DEGREES", 90)) == pytest.approx(90)
    rad = math.radians(45)
    assert composed._coerce(
        "DEGREES", composed._to_display("DEGREES", rad)) == pytest.approx(rad)


# ---- rna_value_adapter against a PLAIN fake object (no bl_rna) ----------
class _Plain:
    """A bare settable holder — deliberately no bl_rna scaffolding, to prove
    the adapter never introspects RNA."""


def _fake_rename_ctx(**attrs):
    ctx = _Plain()
    ctx.scene = _Plain()
    ctx.scene.IOPS = _Plain()
    ctx.scene.IOPS.rename = _Plain()
    for k, v in attrs.items():
        setattr(ctx.scene.IOPS.rename, k, v)
    return ctx


def test_rna_value_adapter_string_get_set():
    ctx = _fake_rename_ctx(pattern="[N]_[C]")
    ad = composed.rna_value_adapter("scene.IOPS.rename.pattern", "STRING")
    assert ad["get"](ctx) == ("[N]_[C]", False)
    ad["set"](ctx, 7)                          # coerced to str on write
    assert ctx.scene.IOPS.rename.pattern == "7"


def test_rna_value_adapter_int_get_set():
    ctx = _fake_rename_ctx(counter_digits=2)
    ad = composed.rna_value_adapter("scene.IOPS.rename.counter_digits", "INT")
    assert ad["get"](ctx) == (2, False)
    ad["set"](ctx, "4")
    assert ctx.scene.IOPS.rename.counter_digits == 4


def test_rna_value_adapter_degrees_get_returns_degrees_set_stores_radians():
    # get() returns author space (degrees); set() stores radians.
    ctx = _fake_rename_ctx(angle=math.radians(90))
    ad = composed.rna_value_adapter("scene.IOPS.rename.angle", "DEGREES")
    val, mixed = ad["get"](ctx)
    assert mixed is False
    assert val == pytest.approx(90)
    ad["set"](ctx, 45)
    assert ctx.scene.IOPS.rename.angle == pytest.approx(math.radians(45))


def test_rna_value_adapter_is_mixed_always_false():
    ctx = _fake_rename_ctx(pattern="x")
    ad = composed.rna_value_adapter("scene.IOPS.rename.pattern", "STRING")
    _val, mixed = ad["get"](ctx)
    assert mixed is False


def test_rna_value_adapter_absent_path_is_disabled_and_set_noops():
    ctx = _fake_rename_ctx()        # no attribute set
    ad = composed.rna_value_adapter("scene.IOPS.rename.missing", "STRING")
    assert ad["get"](ctx) == (None, False)
    ad["set"](ctx, "v")             # must not raise
    assert not hasattr(ctx.scene.IOPS.rename, "missing")
    # Unresolvable intermediate segment.
    bad = composed.rna_value_adapter("scene.NOPE.attr", "STRING")
    assert bad["get"](ctx) == (None, False)
    bad["set"](ctx, "v")            # no-op, no raise


# ---- validate_def: DROPDOWN / INPUT / BUTTONS accept + repair ----------
def test_validate_dropdown_minimal():
    wdef, errors = composed.validate_def({"name": "w", "rows": [
        {"type": "DROPDOWN", "prop": "scene.IOPS.rename.order"}]})
    assert errors == []
    r = wdef["rows"][0]
    assert r["type"] == "DROPDOWN"
    assert r["prop"] == "scene.IOPS.rename.order"
    assert r["value_type"] == "ENUM"            # forced
    assert r["label"] == "order"                # last path segment


def test_validate_dropdown_with_label_and_labels():
    wdef, errors = composed.validate_def({"name": "w", "rows": [
        {"type": "DROPDOWN", "prop": "scene.IOPS.rename.order", "label": "Order",
         "labels": {"DISTANCE": "By Distance", "SELECTION": "By Selection"}}]})
    assert errors == []
    r = wdef["rows"][0]
    assert r["label"] == "Order"
    assert r["labels"] == {"DISTANCE": "By Distance",
                           "SELECTION": "By Selection"}


def test_validate_dropdown_missing_prop_dropped():
    wdef, errors = composed.validate_def({"name": "w", "rows": [
        {"type": "DROPDOWN", "label": "Order"}]})
    assert wdef["rows"] == []
    assert errors


def test_validate_input_defaults():
    wdef, errors = composed.validate_def({"name": "w", "rows": [
        {"type": "INPUT", "prop": "scene.IOPS.rename.pattern"}]})
    assert errors == []
    r = wdef["rows"][0]
    assert r["value_type"] == "STRING"          # default
    assert r["label"] == "pattern"              # last segment
    assert r["fmt"] == "{}"                      # default


def test_validate_input_explicit_int_and_fmt():
    wdef, errors = composed.validate_def({"name": "w", "rows": [
        {"type": "INPUT", "prop": "scene.IOPS.rename.trim_prefix",
         "value_type": "int", "label": "Prefix", "fmt": "{:d}"}]})
    assert errors == []
    r = wdef["rows"][0]
    assert r["value_type"] == "INT"             # upper-cased
    assert r["label"] == "Prefix"
    assert r["fmt"] == "{:d}"


def test_validate_input_missing_prop_dropped():
    wdef, errors = composed.validate_def({"name": "w", "rows": [
        {"type": "INPUT", "value_type": "STRING"}]})
    assert wdef["rows"] == []
    assert errors


def test_validate_input_bad_value_type_dropped():
    wdef, errors = composed.validate_def({"name": "w", "rows": [
        {"type": "INPUT", "prop": "scene.IOPS.rename.pattern",
         "value_type": "BOGUS"}]})
    assert wdef["rows"] == []
    assert errors


def test_validate_buttons_number_presets():
    wdef, errors = composed.validate_def({"name": "w", "rows": [
        {"type": "BUTTONS", "prop": "scene.IOPS.rename.counter_digits",
         "value_type": "INT", "values": [2, 3, 4]}]})
    assert errors == []
    r = wdef["rows"][0]
    assert r["type"] == "BUTTONS"
    assert r["value_type"] == "INT"
    # values coerced to floats and NOT clamped to [0,1] (counters exceed 1).
    assert r["values"] == [2.0, 3.0, 4.0]


def test_validate_buttons_angle_degrees_not_clamped():
    wdef, errors = composed.validate_def({"name": "w", "rows": [
        {"type": "BUTTONS", "prop": "object.data.angle",
         "value_type": "DEGREES", "values": [0, 15, 45, 60, 90, 180]}]})
    assert errors == []
    r = wdef["rows"][0]
    assert r["value_type"] == "DEGREES"
    assert r["values"] == [0.0, 15.0, 45.0, 60.0, 90.0, 180.0]


def test_validate_buttons_enum_items():
    wdef, errors = composed.validate_def({"name": "w", "rows": [
        {"type": "BUTTONS", "prop": "space_data.shading.type",
         "value_type": "ENUM",
         "items": ["SOLID", "MATERIAL", ["RENDERED", "Render"]]}]})
    assert errors == []
    r = wdef["rows"][0]
    assert r["value_type"] == "ENUM"
    assert r["items"] == ["SOLID", "MATERIAL", ["RENDERED", "Render"]]


def test_validate_buttons_enum_without_items_dropped():
    wdef, errors = composed.validate_def({"name": "w", "rows": [
        {"type": "BUTTONS", "prop": "space_data.shading.type",
         "value_type": "ENUM"}]})
    assert wdef["rows"] == []
    assert errors


def test_validate_buttons_number_without_values_dropped():
    wdef, errors = composed.validate_def({"name": "w", "rows": [
        {"type": "BUTTONS", "prop": "scene.IOPS.rename.counter_digits",
         "value_type": "INT", "values": []}]})
    assert wdef["rows"] == []
    assert errors


def test_validate_buttons_missing_prop_dropped():
    wdef, errors = composed.validate_def({"name": "w", "rows": [
        {"type": "BUTTONS", "value_type": "INT", "values": [2, 3]}]})
    assert wdef["rows"] == []
    assert errors


# ---- build_controls produces the right kinds, threads metadata --------
def test_build_controls_input_kind_and_path_not_edge_bound():
    rows = [{"type": "INPUT", "prop": "scene.IOPS.rename.pattern",
             "value_type": "STRING", "label": "Pattern", "fmt": "{}"}]
    ctrls = composed.build_controls(rows)
    assert composed.attribute_domains(rows) == set()
    c = ctrls[0]
    assert c.kind == "input"
    assert c.path == "scene.IOPS.rename.pattern"
    assert c.label == "Pattern"


def test_build_controls_dropdown_kind_threads_labels():
    labels = {"DISTANCE": "By Distance", "SELECTION": "By Selection"}
    rows = [{"type": "DROPDOWN", "prop": "scene.IOPS.rename.order",
             "value_type": "ENUM", "label": "Order", "labels": labels}]
    ctrls = composed.build_controls(rows)
    c = ctrls[0]
    assert c.kind == "dropdown"
    assert c.path == "scene.IOPS.rename.order"
    assert c.labels == labels


def test_build_controls_buttons_number_kind_and_options():
    rows = [{"type": "BUTTONS", "prop": "scene.IOPS.rename.counter_digits",
             "value_type": "INT", "values": [2.0, 3.0, 4.0]}]
    ctrls = composed.build_controls(rows)
    c = ctrls[0]
    assert c.kind == "buttons"
    # Number-mode options: (value, label) pairs threaded from values.
    assert [v for v, _label in c.options] == [2.0, 3.0, 4.0]


def test_build_controls_buttons_enum_kind_and_options():
    rows = [{"type": "BUTTONS", "prop": "space_data.shading.type",
             "value_type": "ENUM",
             "items": ["SOLID", ["RENDERED", "Render"]]}]
    ctrls = composed.build_controls(rows)
    c = ctrls[0]
    assert c.kind == "buttons"
    assert c.options == [("SOLID", "SOLID"), ("RENDERED", "Render")]


def test_build_controls_input_value_type_threaded_via_adapter():
    # A DEGREES INPUT must read degrees from a radian-stored prop, proving
    # build_controls wired rna_value_adapter(prop, value_type) into get.
    rows = [{"type": "INPUT", "prop": "scene.IOPS.rename.angle",
             "value_type": "DEGREES", "label": "Angle", "fmt": "{:g}"}]
    ctrls = composed.build_controls(rows)
    c = ctrls[0]
    ctx = _fake_rename_ctx(angle=math.radians(90))
    val, mixed = c.get(ctx)
    assert mixed is False
    assert val == pytest.approx(90)


def test_build_controls_new_rows_not_edge_bound():
    rows = [
        {"type": "DROPDOWN", "prop": "scene.IOPS.rename.order",
         "value_type": "ENUM", "label": "Order"},
        {"type": "INPUT", "prop": "scene.IOPS.rename.pattern",
         "value_type": "STRING", "label": "Pattern", "fmt": "{}"},
        {"type": "BUTTONS", "prop": "scene.IOPS.rename.counter_digits",
         "value_type": "INT", "values": [2.0, 3.0]},
    ]
    assert composed.attribute_domains(rows) == set()


def test_build_swatch_literal_color_constant_getter():
    data = {"name": "vc", "rows": [
        {"type": "SWATCH", "color": [1, 0, 0, 1], "op": "iops.x.y",
         "label": "R", "show_alpha": True}]}
    clean, errors = composed.validate_def(data)
    assert errors == []
    ctrls = composed.build_controls(clean["rows"])
    sw = ctrls[0]
    assert sw.kind == "swatch"
    assert sw.show_alpha is True
    value, mixed = sw.get(None)          # constant getter, context ignored
    assert value == (1.0, 0.0, 0.0, 1.0)
    assert mixed is False


def test_clean_spaces_defaults_to_view3d():
    assert composed.clean_spaces(None) == ["VIEW_3D"]
    assert composed.clean_spaces("") == ["VIEW_3D"]


def test_clean_spaces_accepts_string():
    assert composed.clean_spaces("IMAGE_EDITOR") == ["IMAGE_EDITOR"]


def test_clean_spaces_accepts_list():
    assert composed.clean_spaces(["VIEW_3D", "IMAGE_EDITOR"]) == \
        ["VIEW_3D", "IMAGE_EDITOR"]


def test_clean_spaces_drops_invalid_and_dedupes():
    assert composed.clean_spaces(["VIEW_3D", "BOGUS", "VIEW_3D"]) == ["VIEW_3D"]


def test_clean_spaces_all_invalid_falls_back():
    assert composed.clean_spaces(["NOPE"]) == ["VIEW_3D"]


def test_validate_def_space_list():
    clean, errors = composed.validate_def({
        "name": "x", "space": ["VIEW_3D", "IMAGE_EDITOR"],
        "rows": [],
    })
    assert clean["space"] == ["VIEW_3D", "IMAGE_EDITOR"]


def test_validate_def_space_string_normalized_to_list():
    clean, _ = composed.validate_def({"name": "x", "rows": []})
    assert clean["space"] == ["VIEW_3D"]


# ----------------------------------------------------------------------
# DROPDOWN live item providers (items_from) — for dynamic lists that
# bl_rna enum_items can't expose (e.g. bpy.data.images).
# ----------------------------------------------------------------------
def test_validate_def_dropdown_items_from():
    clean, errors = composed.validate_def({"name": "d", "rows": [
        {"type": "DROPDOWN", "prop": "window_manager.foo",
         "items_from": "myprov"}]})
    assert errors == []
    assert clean["rows"][0]["items_from"] == "myprov"


def test_build_dropdown_uses_registered_items_provider():
    items = [("", "— none —"), ("a", "a")]
    composed.register_dropdown_items("test_prov", lambda ctx: list(items))
    try:
        rows = [{"type": "DROPDOWN", "prop": "window_manager.foo",
                 "value_type": "ENUM", "items_from": "test_prov", "labels": {}}]
        dd = composed.build_controls(rows)[0]
        assert dd.items_get(None) == items
    finally:
        composed.unregister_dropdown_items("test_prov")


def test_build_dropdown_unregistered_provider_falls_back_to_enum():
    # items_from naming a provider that isn't registered -> fall back to the
    # rna_enum_items reader (which yields [] for an unresolvable path).
    rows = [{"type": "DROPDOWN", "prop": "window_manager.foo",
             "value_type": "ENUM", "items_from": "nope", "labels": {}}]
    dd = composed.build_controls(rows)[0]

    class _Ctx:
        pass

    assert dd.items_get(_Ctx()) == []


# ----------------------------------------------------------------------
# `data` binding (scene store)
# ----------------------------------------------------------------------
@pytest.mark.parametrize("row", [
    {"type": "FLIPBOX", "data": "flag", "label": "Flag"},
    {"type": "DROPDOWN", "data": "slot_0", "items_from": "uv_images"},
    {"type": "INPUT", "data": "note", "value_type": "STRING"},
    {"type": "BUTTONS", "data": "level", "value_type": "INT",
     "values": [1, 2, 3]},
])
def test_data_binding_accepted(row):
    out, err = composed._clean_row_body(row)
    assert err is None
    assert out["data"] == row["data"]
    assert "prop" not in out


@pytest.mark.parametrize("row", [
    {"type": "FLIPBOX", "data": "flag", "prop": "scene.x"},
    {"type": "FLIPBOX", "data": "flag", "switch": "s"},
    {"type": "FLIPBOX", "data": "flag", "target": "SHARP"},
    {"type": "DROPDOWN", "data": "slot_0", "prop": "scene.x"},
    {"type": "INPUT", "data": "note", "prop": "scene.x"},
    {"type": "BUTTONS", "data": "level", "prop": "scene.x",
     "values": [1]},
])
def test_data_plus_other_binding_rejected(row):
    out, err = composed._clean_row_body(row)
    assert out is None


@pytest.mark.parametrize("row", [
    {"type": "FLIPBOX", "data": "  "},
    {"type": "DROPDOWN", "data": ""},
    {"type": "INPUT", "data": " "},
    {"type": "BUTTONS", "data": "", "values": [1]},
])
def test_blank_data_rejected(row):
    out, err = composed._clean_row_body(row)
    assert out is None


def test_data_label_defaults_to_key():
    out, _ = composed._clean_row_body({"type": "INPUT", "data": "note"})
    assert out["label"] == "note"
    out, _ = composed._clean_row_body({"type": "FLIPBOX", "data": "flag"})
    assert out["label"] == "flag"
    out, _ = composed._clean_row_body(
        {"type": "DROPDOWN", "data": "slot_0"})
    assert out["label"] == "slot_0"


def test_data_dropdown_keeps_forced_enum_and_items_from():
    out, err = composed._clean_row_body(
        {"type": "DROPDOWN", "data": "slot_0", "items_from": "uv_images"})
    assert err is None
    assert out["value_type"] == "ENUM"
    assert out["items_from"] == "uv_images"


def test_prop_rows_unchanged():
    out, err = composed._clean_row_body(
        {"type": "INPUT", "prop": "scene.IOPS.rename.new_name"})
    assert err is None
    assert out["prop"] == "scene.IOPS.rename.new_name"
    assert "data" not in out


# ----------------------------------------------------------------------
# build_controls with `data` rows (scene-store routing)
# ----------------------------------------------------------------------
from tests.ui.widgets.test_scene_store import FakeContext


def test_build_controls_data_input_roundtrip():
    rows, errors = composed.validate_def({
        "name": "demo_w",
        "rows": [{"type": "INPUT", "data": "note",
                  "value_type": "STRING"}],
    })
    assert not errors
    controls = composed.build_controls(rows["rows"], widget_name="demo_w")
    assert len(controls) == 1
    ctrl = controls[0]
    ctx = FakeContext()
    assert ctrl.get(ctx) == ("", False)            # unset -> default, enabled
    ctrl.set(ctx, "hello")
    assert ctrl.get(ctx) == ("hello", False)
    # scoped to the widget's own block
    block = ctx.scene.IOPS.widget_data.get("demo_w")
    assert block.entries.get("note").value == "hello"


def test_build_controls_data_flipbox_bool():
    rows, _ = composed.validate_def({
        "name": "demo_w",
        "rows": [{"type": "FLIPBOX", "data": "flag", "label": "Flag"}],
    })
    controls = composed.build_controls(rows["rows"], widget_name="demo_w")
    ctx = FakeContext()
    ctrl = controls[0]
    assert ctrl.get(ctx) == (False, False)
    ctrl.set(ctx, True)
    assert ctrl.get(ctx) == (True, False)
    assert ctx.scene.IOPS.widget_data.get("demo_w") \
              .entries.get("flag").value == "1"


def test_build_controls_data_dropdown_uses_provider_and_empty_fallback():
    composed.register_dropdown_items(
        "test_items", lambda context: [("A", "Option A"), ("B", "Option B")])
    try:
        rows, _ = composed.validate_def({
            "name": "demo_w",
            "rows": [
                {"type": "DROPDOWN", "data": "slot", "items_from": "test_items"},
                {"type": "DROPDOWN", "data": "bare"},   # no items_from
            ],
        })
        controls = composed.build_controls(rows["rows"],
                                           widget_name="demo_w")
        ctx = FakeContext()
        assert controls[0].items_get(ctx) == [("A", "Option A"),
                                              ("B", "Option B")]
        assert controls[1].items_get(ctx) == []        # empty fallback
        controls[0].set(ctx, "B")
        assert controls[0].get(ctx) == ("B", False)
    finally:
        composed.unregister_dropdown_items("test_items")


def test_build_controls_data_buttons():
    rows, _ = composed.validate_def({
        "name": "demo_w",
        "rows": [{"type": "BUTTONS", "data": "level", "value_type": "INT",
                  "values": [1, 2, 3]}],
    })
    controls = composed.build_controls(rows["rows"], widget_name="demo_w")
    ctx = FakeContext()
    controls[0].set(ctx, 2)
    assert controls[0].get(ctx) == (2, False)


def test_data_rows_do_not_bind_edges():
    rows, _ = composed.validate_def({
        "name": "demo_w",
        "rows": [{"type": "INPUT", "data": "note"}],
    })
    assert composed.attribute_domains(rows["rows"]) == set()


# ----------------------------------------------------------------------
# width override
# ----------------------------------------------------------------------
def test_width_override_validation():
    base = {"name": "w", "rows": []}
    clean, errors = composed.validate_def(dict(base, width=150))
    assert clean["width"] == 150.0 and not errors
    clean, errors = composed.validate_def(dict(base, width="120"))
    assert clean["width"] == 120.0 and not errors
    clean, errors = composed.validate_def(base)
    assert "width" not in clean
    clean, errors = composed.validate_def(dict(base, width=10))
    assert "width" not in clean and any("width" in e for e in errors)
    clean, errors = composed.validate_def(dict(base, width="wide"))
    assert "width" not in clean and any("width" in e for e in errors)


def test_spacer_row_validates():
    d, errs = composed.validate_def({"name": "w", "rows": [
        {"type": "SPACER"}, {"type": "SPACER", "span": 3, "height": 12}]})
    assert errs == []
    assert d["rows"][0] == {"type": "SPACER"}
    assert d["rows"][1] == {"type": "SPACER", "span": 3, "height": 12.0}


def test_span_out_of_range_dropped_row_kept():
    d, errs = composed.validate_def({"name": "w", "rows": [
        {"type": "SECTION", "label": "A", "span": 13}]})
    assert "span" not in d["rows"][0] and errs


def test_row_spans_normalized_all_or_nothing():
    d, _ = composed.validate_def({"name": "w", "rows": [{"type": "ROW", "cells": [
        {"type": "SPACER", "span": 3},
        {"type": "BUTTON", "op": "a.b"},
        {"type": "SPACER", "span": 3}]}]})
    assert [c["span"] for c in d["rows"][0]["cells"]] == [3, 6, 3]


def test_normalize_spans():
    assert composed.normalize_spans([None, None]) is None
    assert composed.normalize_spans([4, None, None]) == [4, 4, 4]
    assert composed.normalize_spans([10, 10]) == [10, 2]
    assert composed.normalize_spans([12, None]) == [11, 1]


def test_cell_show_if_kept():
    d, errs = composed.validate_def({"name": "w", "rows": [{"type": "ROW", "cells": [
        {"type": "BUTTON", "op": "a.b", "show_if": {"mode": "OBJECT"}}]}]})
    assert d["rows"][0]["cells"][0]["show_if"] == {"mode": ["OBJECT"]}


def test_spanned_flipboxes_not_merged():
    rows = [{"type": "FLIPBOX", "switch": "a", "span": 12},
            {"type": "FLIPBOX", "switch": "b", "span": 12}]
    assert composed.merge_flipbox_runs(rows) == rows


def test_list_widget_files_skips_drafts(tmp_path, monkeypatch):
    for fn in ("a.json", "a.draft.json", "b.json.bak"):
        (tmp_path / fn).write_text("{}")
    monkeypatch.setattr(composed, "widgets_folder", lambda: str(tmp_path))
    monkeypatch.setattr(composed, "BUNDLED_FOLDER", str(tmp_path / "none"))
    assert composed.list_widget_files() == ["a.json"]


def test_bundled_widgets_listed_and_overridable(tmp_path, monkeypatch):
    user, bundled = tmp_path / "user", tmp_path / "bundled"
    user.mkdir()
    bundled.mkdir()
    for fn in ("shipped.json", "both.json"):
        (bundled / fn).write_text("{}")
    for fn in ("mine.json", "both.json"):
        (user / fn).write_text("{}")
    monkeypatch.setattr(composed, "widgets_folder", lambda: str(user))
    monkeypatch.setattr(composed, "BUNDLED_FOLDER", str(bundled))
    assert composed.list_widget_files() == ["both.json", "mine.json",
                                            "shipped.json"]
    assert composed.source_path("shipped") == str(bundled / "shipped.json")
    assert composed.source_path("both") == str(user / "both.json")
    assert composed.widget_path("shipped") == str(user / "shipped.json")
    assert composed.is_builtin("shipped")
    assert not composed.is_builtin("both") and composed.has_bundled("both")
    assert not composed.is_builtin("mine")
    assert not composed.delete_def("shipped")      # bundled never deleted
    assert (bundled / "shipped.json").exists()


def test_shipped_widgets_validate_cleanly():
    import json
    files = sorted(f for f in os.listdir(composed.BUNDLED_FOLDER)
                   if f.endswith(".json"))
    assert "edge_data.json" in files
    for fn in files:
        with open(os.path.join(composed.BUNDLED_FOLDER, fn),
                  encoding="utf-8") as f:
            data = json.load(f)
        clean, errors = composed.validate_def(data)
        assert clean is not None and errors == [], fn
        assert composed.dropped_keys(data) == [], fn
        cells = [c for r in data.get("rows", [])
                 for c in [r] + list(r.get("cells", []))]
        assert not any("target" in c for c in cells), fn  # no legacy ids


def test_build_controls_spacer_and_span():
    ctrls = composed.build_controls([
        {"type": "SPACER", "span": 4},
        {"type": "ROW", "cells": [{"type": "SECTION", "label": "x", "span": 6,
                                   "show_if": {"mode": "OBJECT"}},
                                  {"type": "SPACER", "span": 6}]}])
    assert ctrls[0].kind == "spacer" and ctrls[0]._span == 4
    cell = ctrls[1].children[0]
    assert cell._span == 6 and cell._show_if == {"mode": "OBJECT"}


def test_cell_span_out_of_range_reported_cell_kept():
    d, errs = composed.validate_def({"name": "w", "rows": [{"type": "ROW", "cells": [
        {"type": "BUTTON", "op": "a.b", "span": 13}]}]})
    cell = d["rows"][0]["cells"][0]
    assert "span" not in cell and any("cell 0" in e and "span" in e for e in errs)


def test_dropped_cell_reported():
    d, errs = composed.validate_def({"name": "w", "rows": [{"type": "ROW", "cells": [
        {"type": "BUTTON", "op": "a.b"}, {"type": "NOPE"}]}]})
    assert len(d["rows"][0]["cells"]) == 1
    assert any("cell 1" in e for e in errs)


# ----------------------------------------------------------------------
# dropped_keys — unknown keys validate_def drops silently (editor .bak)
# ----------------------------------------------------------------------
def test_dropped_keys_clean_def_is_empty():
    data = {"name": "w", "title": "T", "space": ["VIEW_3D"], "width": 200,
            "switches": {"a": True}, "version": 1, "rows": [
                {"type": "button", "op": "a.b", "label": "B",
                 "op_kwargs": {}, "role": "error", "span": 6,
                 "show_if": {"mode": "OBJECT"}},
                {"type": "ROW", "cells": [
                    {"type": "SWATCH", "color": [1, 0, 0, 1], "op": "a.b",
                     "show_alpha": False}]},
                {"type": "SPACER", "height": 8}]}
    assert composed.dropped_keys(data) == []


def test_dropped_keys_top_row_cell_and_show_if():
    data = {"name": "w", "author": "me", "rows": [
        {"type": "BUTTON", "op": "a.b", "tooltip": "x",
         "show_if": {"mode": "OBJECT", "when": 1}},
        {"type": "ROW", "color": "red", "cells": [
            {"type": "SECTION", "label": "L", "op": "a.b"}]}]}
    msgs = composed.dropped_keys(data)
    assert len(msgs) == 5
    assert any("'author'" in m for m in msgs)
    assert any(m.startswith("row 0:") and "'tooltip'" in m for m in msgs)
    assert any(m.startswith("row 0:") and "show_if key 'when'" in m
               for m in msgs)
    assert any(m.startswith("row 1:") and "'color'" in m for m in msgs)
    assert any(m.startswith("row 1 cell 0:") and "'op'" in m for m in msgs)


def test_dropped_keys_skips_values_validate_def_reports():
    # Bad width / span / show_if values are reported by validate_def
    # itself; dropped rows and cells too — no duplicate messages.
    data = {"name": "w", "width": "wide", "rows": [
        {"type": "BUTTON", "op": "a.b", "span": 99, "show_if": 5},
        {"type": "NOPE", "junk": 1},
        {"type": "ROW", "cells": [{"type": "NOPE", "junk": 1},
                                  {"type": "BUTTON", "op": "a.b"}]}]}
    assert composed.dropped_keys(data) == []
    _clean, errs = composed.validate_def(data)
    assert errs                                  # reported there instead


def test_dropped_keys_not_a_def():
    assert composed.dropped_keys([]) == []
    assert composed.dropped_keys({"rows": []}) == []     # no name


def test_validate_presets_prop_and_data_bindings():
    wdef, errors = composed.validate_def({"name": "w", "rows": [
        {"type": "PRESETS", "prop": "object.data.angle",
         "value_type": "DEGREES", "values": [0, 45, 90], "fmt": "{:g}°"},
        {"type": "PRESETS", "data": "count", "value_type": "INT",
         "values": [2, 4, 8]},
        {"type": "PRESETS", "prop": "a.b", "values": [-1, 2.5]}]})
    assert errors == []
    p, d, f = wdef["rows"]
    assert p["prop"] == "object.data.angle" and "target" not in p
    assert p["value_type"] == "DEGREES" and p["fmt"] == "{:g}°"
    assert p["values"] == [0.0, 45.0, 90.0]  # not clamped to [0, 1]
    assert d["data"] == "count" and d["value_type"] == "INT"
    assert f["value_type"] == "FLOAT" and f["values"] == [-1.0, 2.5]


def test_validate_presets_binding_rules():
    wdef, errors = composed.validate_def({"name": "w", "rows": [
        {"type": "PRESETS", "target": "BEVEL", "prop": "a.b",
         "values": [0]},
        {"type": "PRESETS", "values": [0]},
        {"type": "PRESETS", "prop": "a.b", "value_type": "ENUM",
         "values": [0]},
        {"type": "PRESETS", "target": "BEVEL", "values": [-1, 2]}]})
    assert len(errors) == 3
    # legacy target converts to an attribute and still clamps to [0, 1]
    assert wdef["rows"] == [{"type": "PRESETS",
                             "attribute": "bevel_weight_edge",
                             "domain": "EDGE", "value_type": "FLOAT",
                             "values": [0.0, 1.0]}]


def test_build_controls_presets_prop_writes_via_adapter():
    rows = [{"type": "PRESETS", "prop": "scene.IOPS.rename.angle",
             "value_type": "DEGREES", "values": [0.0, 90.0],
             "fmt": "{:g}°"}]
    c = composed.build_controls(rows)[0]
    assert c.kind == "presets" and c.fmt == "{:g}°"
    ctx = _fake_rename_ctx(angle=0.0)
    c.write(ctx, c.values[1])
    assert math.isclose(ctx.scene.IOPS.rename.angle, math.radians(90))


def test_legacy_targets_convert_to_attributes():
    wdef, errors = composed.validate_def({"name": "w", "rows": [
        {"type": "SLIDER", "target": "CREASE"},
        {"type": "FLIPBOX", "target": "SEAM"},
        {"type": "FLIPBOX", "target": "SHARP", "label": "S"},
        {"type": "FLIPBOX", "target": "FREESTYLE"},
        {"type": "FLIPBOX", "target": "BEVEL"},             # float: drop
        {"type": "SLIDER", "target": "BEVEL",
         "attribute": "x"}]})                               # both: drop
    assert len(errors) == 2
    sl, seam, sharp, fs = wdef["rows"]
    assert sl == {"type": "SLIDER", "attribute": "crease_edge",
                  "domain": "EDGE", "value_type": "FLOAT", "min": 0.0,
                  "max": 1.0, "fmt": "{:.3f}", "snap": 0.125}
    assert (seam["attribute"], seam["label"]) == ("uv_seam", "Seam")
    assert (sharp["attribute"], sharp["label"]) == ("sharp_edge", "S")
    assert fs["attribute"] == "freestyle_edge"
    assert composed.dropped_keys({"name": "w", "rows": [
        {"type": "FLIPBOX", "target": "SEAM"}]}) == []


def test_validate_attribute_bindings():
    wdef, errors = composed.validate_def({"name": "w", "rows": [
        {"type": "SLIDER", "attribute": "my_w", "domain": "point",
         "min": -2, "max": 2},
        {"type": "PRESETS", "attribute": "lvl", "domain": "FACE",
         "value_type": "INT", "values": [1, 2, 3]},
        {"type": "FLIPBOX", "attribute": "flag_f", "domain": "FACE"},
        {"type": "FLIPBOX", "attribute": "x", "domain": "CORNER"},  # drop
        {"type": "SLIDER", "attribute": ".select_vert"},          # drop
        {"type": "PRESETS", "attribute": "position", "values": [0]},  # drop
        {"type": "SLIDER", "attribute": "a", "prop": "b.c"}]})    # drop
    assert len(errors) == 4
    sl, pr, fb = wdef["rows"]
    assert (sl["attribute"], sl["domain"]) == ("my_w", "POINT")
    assert (sl["min"], sl["max"], sl["snap"]) == (-2.0, 2.0, 0.0)
    assert pr["value_type"] == "INT" and pr["values"] == [1.0, 2.0, 3.0]
    assert (fb["domain"], fb["label"]) == ("FACE", "flag_f")
    assert composed.attribute_domains(
        wdef["rows"] + [{"type": "ROW", "cells": [
            {"type": "FLIPBOX", "attribute": "q", "domain": "EDGE"}]}]) \
        == {"POINT", "FACE", "EDGE"}


def test_edge_data_def_is_attribute_bound():
    wdef, errors = composed.validate_def(composed.EDGE_DATA_DEF)
    assert errors == []
    assert all("target" not in r for r in wdef["rows"])
    assert composed.attribute_domains(wdef["rows"]) == {"EDGE"}


def test_shipped_widget_scripts_exist():
    import json
    scripts = os.path.join(composed.BUNDLED_FOLDER, "scripts")
    used = set()
    for fn in os.listdir(composed.BUNDLED_FOLDER):
        if not fn.endswith(".json"):
            continue
        with open(os.path.join(composed.BUNDLED_FOLDER, fn),
                  encoding="utf-8") as f:
            data = json.load(f)
        for r in data.get("rows", []):
            for c in [r] + list(r.get("cells", [])):
                kw = c.get("op_kwargs") or {}
                if c.get("op") == "iops.executor":
                    # bare names only: shipped widgets never point at a
                    # user's own script folder
                    assert os.path.basename(kw["script"]) == kw["script"]
                    used.add(kw["script"])
    assert used and all(os.path.isfile(os.path.join(scripts, s))
                        for s in used)
    assert used == set(os.listdir(scripts)) - {"__pycache__"}
