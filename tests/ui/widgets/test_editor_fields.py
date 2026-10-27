"""Pure tests for ui/widgets/editor_fields.py — the widget editor
N-panel's field layout and text formats."""
import importlib
import os
import sys

_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__),
                                      "..", "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

ef = importlib.import_module("ui.widgets.editor_fields")
composed = importlib.import_module("widgets.composed")


# -- items -------------------------------------------------------------
def test_parse_items_pairs_and_bare():
    assert ef.parse_items("A:Alpha, B ,C: ") == [["A", "Alpha"], "B", "C"]


def test_parse_items_skips_empty_ids():
    assert ef.parse_items(", :x, D") == ["D"]


def test_items_round_trip():
    items = [["A", "Alpha"], "B", ["C"]]
    assert ef.format_items(items) == "A:Alpha, B, C"
    assert ef.parse_items(ef.format_items(items)) == [["A", "Alpha"], "B",
                                                      "C"]


def test_parsed_items_validate():
    row = {"type": "BUTTONS", "prop": "a.b", "value_type": "ENUM",
           "items": ef.parse_items("X:Ex, Y")}
    clean, err = composed._clean_row(row)
    assert err is None and clean["items"] == [["X", "Ex"], "Y"]


# -- labels ------------------------------------------------------------
def test_parse_labels():
    assert ef.parse_labels("A=Alpha; B = Beta ;bad; =x") == {
        "A": "Alpha", "B": "Beta"}


def test_labels_round_trip():
    labels = {"A": "Alpha", "B": "Beta"}
    assert ef.parse_labels(ef.format_labels(labels)) == labels


def test_format_labels_non_dict():
    assert ef.format_labels(None) == ""


# -- switches ----------------------------------------------------------
def test_parse_switches():
    assert ef.parse_switches("a=1, b=0, c, d=yes, e=off, f=maybe") == {
        "a": True, "b": False, "c": True, "d": True, "e": False}


def test_switches_round_trip():
    sw = {"a": True, "b": False}
    assert ef.format_switches(sw) == "a=1, b=0"
    assert ef.parse_switches(ef.format_switches(sw)) == sw


# -- numbers / lists / kwargs -------------------------------------------
def test_parse_numbers_unclamped():
    assert ef.parse_numbers("-2, 0.5, x, 10") == [-2.0, 0.5, 10.0]


def test_format_numbers():
    assert ef.format_numbers([0, 0.25, 1.0]) == "0, 0.25, 1"


def test_parse_list_uppercases():
    assert ef.parse_list(" edit_mesh, ,Object") == ["EDIT_MESH", "OBJECT"]


def test_parse_kwargs():
    assert ef.parse_kwargs("") == ({}, None)
    assert ef.parse_kwargs('{"a": 1}') == ({"a": 1}, None)
    val, err = ef.parse_kwargs("{bad")
    assert val is None and "invalid JSON" in err
    val, err = ef.parse_kwargs("[1]")
    assert val is None and err


def test_format_kwargs():
    assert ef.format_kwargs({}) == ""
    assert ef.format_kwargs({"a": 1}) == '{"a": 1}'


# -- show_if -----------------------------------------------------------
def test_build_show_if_empty_is_none():
    assert ef.build_show_if() is None
    assert ef.build_show_if(equals="1") is None


def test_build_show_if_full():
    si = ef.build_show_if("edit_mesh, object", "mesh", "edges",
                          "scene.x", "", "true")
    assert si == {"mode": ["EDIT_MESH", "OBJECT"], "object_type": ["MESH"],
                  "selection": "edges", "prop": "scene.x", "equals": True}
    clean, err = composed._clean_show_if(si)
    assert err is None and clean == si


def test_build_show_if_equals_needs_prop_or_switch():
    assert ef.build_show_if(mode="OBJECT", equals="1") == {"mode": ["OBJECT"]}


def test_build_show_if_ignores_any_selection():
    assert ef.build_show_if(selection="ANY", switch="s") == {"switch": "s"}


def test_equals_round_trip():
    for v in ("EDIT", "1", "true", 1, True, 2.5, None):
        present, back = ef.parse_equals(ef.format_equals(v))
        assert present and back == v


def test_show_if_fields_inverse():
    si = {"mode": ["OBJECT"], "switch": "s", "equals": "1"}
    f = ef.show_if_fields(si)
    assert f["si_mode"] == "OBJECT" and f["si_equals"] == '"1"'
    assert ef.build_show_if(f["si_mode"], f["si_object_type"],
                            f["si_selection"], f["si_prop"],
                            f["si_switch"], f["si_equals"]) == si


# -- bindings / fields ---------------------------------------------------
def test_binding_of():
    assert ef.binding_of({"type": "SLIDER", "attribute": "a"}) == \
        "ATTRIBUTE"
    assert ef.binding_of({"type": "SLIDER", "prop": "a.b"}) == "PROP"
    assert ef.binding_of({"type": "FLIPBOX", "switch": ""}) == "SWITCH"
    assert ef.binding_of({"type": "SWATCH", "color": [1, 1, 1, 1]}) == \
        "COLOR"
    assert ef.binding_of({"type": "BUTTON"}) == ""


def test_apply_binding_drops_other_keys():
    el = {"type": "FLIPBOX", "label": "L", "switch": "s"}
    assert ef.apply_binding(el, "PROP", "a.b")
    assert el == {"type": "FLIPBOX", "label": "L", "prop": "a.b"}
    assert not ef.apply_binding(el, "PROP", "a.b")
    assert not ef.apply_binding(el, "COLOR", [1, 1, 1, 1])


def test_apply_binding_swatch_color():
    el = {"type": "SWATCH", "prop": "a.c", "op": "x.y"}
    assert ef.apply_binding(el, "COLOR", [1.0, 0.0, 0.0, 1.0])
    assert el == {"type": "SWATCH", "op": "x.y", "color": [1.0, 0, 0, 1.0]}


def test_fields_for_types():
    assert ef.fields_for({"type": "BUTTON"}) == ["label", "op", "op_kwargs",
                                                 "role"]
    assert ef.fields_for({"type": "SLIDER", "attribute": "a"}) == [
        "binding", "attribute", "domain", "value_type", "min", "max",
        "snap", "fmt"]
    assert "min" in ef.fields_for({"type": "SLIDER", "prop": "a.b"})
    assert ef.fields_for({"type": "BUTTONS", "prop": "a",
                          "value_type": "ENUM"})[-1] == "items"
    assert "values" in ef.fields_for({"type": "BUTTONS", "prop": "a"})
    assert ef.fields_for({"type": "FLIPBOX", "data": "k"})[2] == "data"
    assert "color" in ef.fields_for({"type": "SWATCH", "color": [0] * 4})
    assert "prop" in ef.fields_for({"type": "SWATCH", "prop": "a"})
    assert ef.fields_for({"type": "ROW", "cells": []}) == []


def test_value_types():
    assert "STRING" not in ef.value_types_for("SLIDER")
    assert ef.value_types_for("INPUT") == composed.VALUE_TYPES
    assert ef.value_types_for("BUTTON") == ()


def test_span_rules():
    assert ef.span_min(True, "BUTTON") == 0
    assert ef.span_min(True, "FLIPBOX") == 1
    assert ef.span_min(False, "BUTTON") == 1
    assert not ef.has_span(True, "ROW")
    assert ef.has_span(False, "BUTTON")


def test_presets_bindings_and_fields():
    assert ef.bindings_for("PRESETS") == ("ATTRIBUTE", "PROP", "DATA")
    assert ef.fields_for({"type": "PRESETS", "attribute": "a"}) == [
        "binding", "attribute", "domain", "value_type", "values", "fmt"]
    assert ef.fields_for({"type": "PRESETS", "prop": "a.b"}) == [
        "binding", "prop", "value_type", "values", "fmt"]
    assert ef.fields_for({"type": "PRESETS", "data": "k"}) == [
        "binding", "data", "value_type", "values", "fmt"]
    assert "ENUM" not in ef.value_types_for("PRESETS")
    el = {"type": "PRESETS", "attribute": "a", "domain": "FACE",
          "values": [0, 1]}
    assert ef.apply_binding(el, "PROP", "a.b")
    assert el == {"type": "PRESETS", "prop": "a.b", "values": [0, 1]}
    assert ef.apply_binding(el, "ATTRIBUTE", "w")
    assert el == {"type": "PRESETS", "attribute": "w", "domain": "EDGE",
                  "values": [0, 1]}
