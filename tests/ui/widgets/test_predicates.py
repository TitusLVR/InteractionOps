"""Pure tests for ui/widgets/predicates.py — the show_if evaluator.
Loaded standalone (bpy-free): build_eval_ctx defers its bpy imports."""
import importlib.util
import os
import sys

_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__),
                                      "..", "..", ".."))


def _load_predicates():
    path = os.path.join(_ROOT, "ui", "widgets", "predicates.py")
    spec = importlib.util.spec_from_file_location("iops_test_predicates", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


pred = _load_predicates()


def _ctx(mode="OBJECT", object_type=None, switches=None,
         props=None, selections=None):
    props = props or {}
    selections = selections or {}
    return pred.EvalCtx(
        mode, object_type, switches or {},
        prop_fn=lambda p: (props[p], True) if p in props else (None, False),
        selection_fn=lambda k: bool(selections.get(k, False)),
    )


def test_none_predicate_always_true():
    assert pred.eval_show_if(None, _ctx()) is True
    assert pred.eval_show_if({}, _ctx()) is True


def test_as_set_str_and_list():
    assert pred.as_set("mesh") == {"MESH"}
    assert pred.as_set(["mesh", "Curve"]) == {"MESH", "CURVE"}


def test_mode_match_and_miss():
    assert pred.eval_show_if({"mode": "EDIT_MESH"},
                             _ctx(mode="EDIT_MESH")) is True
    assert pred.eval_show_if({"mode": ["OBJECT", "POSE"]},
                             _ctx(mode="EDIT_MESH")) is False


def test_object_type_none_object_fails():
    assert pred.eval_show_if({"object_type": "MESH"},
                             _ctx(object_type=None)) is False
    assert pred.eval_show_if({"object_type": ["MESH", "CURVE"]},
                             _ctx(object_type="CURVE")) is True


def test_selection_kind():
    assert pred.eval_show_if({"selection": "edges"},
                             _ctx(selections={"edges": True})) is True
    assert pred.eval_show_if({"selection": "edges"},
                             _ctx(selections={"edges": False})) is False


def test_prop_truthy_and_equals_and_missing():
    assert pred.eval_show_if({"prop": "scene.x"},
                             _ctx(props={"scene.x": True})) is True
    assert pred.eval_show_if({"prop": "scene.x"},
                             _ctx(props={"scene.x": False})) is False
    assert pred.eval_show_if({"prop": "scene.n", "equals": 3},
                             _ctx(props={"scene.n": 3})) is True
    assert pred.eval_show_if({"prop": "scene.n", "equals": 3},
                             _ctx(props={"scene.n": 4})) is False
    # Missing path -> False (not an error)
    assert pred.eval_show_if({"prop": "scene.gone"}, _ctx()) is False


def test_switch_truthy_and_equals():
    assert pred.eval_show_if({"switch": "adv"},
                             _ctx(switches={"adv": True})) is True
    assert pred.eval_show_if({"switch": "adv"},
                             _ctx(switches={"adv": False})) is False
    assert pred.eval_show_if({"switch": "adv", "equals": False},
                             _ctx(switches={"adv": False})) is True


def test_keys_are_anded():
    p = {"mode": "EDIT_MESH", "switch": "adv"}
    assert pred.eval_show_if(p, _ctx(mode="EDIT_MESH",
                                     switches={"adv": True})) is True
    assert pred.eval_show_if(p, _ctx(mode="EDIT_MESH",
                                     switches={"adv": False})) is False


def test_filter_controls():
    class C:
        def __init__(self, si):
            self._show_if = si
    a, b, c = C(None), C({"switch": "adv"}), C({"mode": "OBJECT"})
    out = pred.filter_controls([a, b, c],
                               _ctx(mode="OBJECT", switches={"adv": False}))
    assert out == [a, c]
