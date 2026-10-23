"""Pure tests for ui/widgets/editor_model.py — the bpy-free document model
behind the visual widget editor."""
import copy
import importlib
import os
import sys

_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__),
                                      "..", "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

em = importlib.import_module("ui.widgets.editor_model")
composed = importlib.import_module("widgets.composed")


def _wdef(rows):
    return {"version": 1, "name": "w", "title": "W", "space": "VIEW_3D",
            "switches": {}, "rows": rows}


def _btn(label="B", **kw):
    d = {"type": "BUTTON", "label": label, "op": "a.b"}
    d.update(kw)
    return d


def _spans(doc, r):
    return [c.get("span") for c in doc.wdef["rows"][r]["cells"]]


def _row(n, spans=None):
    cells = [_btn(str(i)) for i in range(n)]
    if spans:
        for c, s in zip(cells, spans):
            c["span"] = s
    return {"type": "ROW", "cells": cells}


def _fb(name, **kw):
    d = {"type": "FLIPBOX", "label": name, "switch": name}
    d.update(kw)
    return d


# ----------------------------------------------------------------------
def test_normalize_roundtrip_renders_same_structure():
    rows = [{"type": "SECTION", "label": "S"}, _fb("a"), _fb("b"),
            _fb("c", show_if={"mode": "OBJECT"}), _btn()]
    wdef = _wdef(rows)
    norm = em.normalize_for_edit(wdef)
    assert wdef["rows"] == rows  # input untouched

    def kinds(w):
        clean, _ = composed.validate_def(w)
        ctrls = composed.build_controls(clean["rows"])
        return [(c.kind, len(getattr(c, "children", []) or []))
                for c in ctrls]

    assert [c[0] for c in kinds(norm)] == ["section", "row", "flipbox",
                                           "button"]
    assert kinds(norm)[1][1] == 2
    assert kinds(norm) == kinds(wdef)
    assert norm["rows"][2]["span"] == 12


def test_new_element_defaults():
    assert em.new_element("BUTTON") == {"type": "BUTTON", "label": "Button",
                                        "op": ""}
    assert em.new_element("SPACER") == {"type": "SPACER"}
    assert em.new_element("ROW") == {"type": "ROW",
                                     "cells": [{"type": "SPACER"}]}
    assert not em.is_complete(em.new_element("BUTTON"))
    assert em.is_complete(em.new_element("SECTION"))
    assert em.is_complete(em.new_element("ROW"))
    assert em.is_complete(em.new_element("PRESETS"))


def test_insert_new_row_and_select():
    doc = em.EditorDoc(_wdef([_btn("a"), _btn("b")]))
    assert doc.insert((1, None), em.new_element("BUTTON")) == (1, None)
    assert doc.selection == (1, None)
    assert doc.wdef["rows"][1]["label"] == "Button"
    assert len(doc.wdef["rows"]) == 3 and doc.dirty and doc.can_undo


def test_insert_flipbox_top_level_gets_span_12():
    doc = em.EditorDoc(_wdef([]))
    doc.insert((0, None), em.new_element("FLIPBOX"))
    assert doc.wdef["rows"][0]["span"] == 12


def test_insert_into_plain_row_wraps():
    doc = em.EditorDoc(_wdef([_btn("a", show_if={"mode": ["OBJECT"]})]))
    assert doc.insert((0, 1), em.new_element("SECTION")) == (0, 1)
    row = doc.wdef["rows"][0]
    assert row["type"] == "ROW" and len(row["cells"]) == 2
    # show_if stays on the wrapped cell; the new element is unconditional.
    assert "show_if" not in row
    assert row["cells"][0]["show_if"] == {"mode": ["OBJECT"]}
    assert "show_if" not in row["cells"][1]
    assert all("span" not in c for c in row["cells"])


def test_insert_into_spanned_row_uses_free():
    doc = em.EditorDoc(_wdef([_row(2, [3, 6])]))
    assert doc.insert((0, 2), em.new_element("BUTTON")) == (0, 2)
    assert _spans(doc, 0) == [3, 6, 3]


def test_insert_into_spanned_row_caps_at_four():
    doc = em.EditorDoc(_wdef([_row(2, [2, 2])]))
    doc.insert((0, 2), em.new_element("BUTTON"))
    assert _spans(doc, 0) == [2, 2, 4]


def test_insert_into_full_row_splits_neighbour():
    doc = em.EditorDoc(_wdef([_row(3, [4, 4, 4])]))
    assert doc.insert((0, 1), em.new_element("BUTTON")) == (0, 1)
    assert _spans(doc, 0) == [2, 2, 4, 4]


def test_insert_into_full_row_splits_odd_neighbour():
    doc = em.EditorDoc(_wdef([_row(2, [5, 7])]))
    doc.insert((0, 2), em.new_element("BUTTON"))  # neighbour = cell 1 (7)
    assert _spans(doc, 0) == [5, 4, 3]


def test_insert_into_full_row_of_ones_refused():
    doc = em.EditorDoc(_wdef([_row(12, [1] * 12)]))
    before = copy.deepcopy(doc.wdef)
    assert doc.insert((0, 5), em.new_element("BUTTON")) is None
    assert doc.wdef == before
    assert not doc.can_undo and not doc.dirty


def test_insert_row_into_cell_refused():
    doc = em.EditorDoc(_wdef([_row(2)]))
    assert doc.insert((0, 1), em.new_element("ROW")) is None


def test_move_within_row_and_between_rows():
    doc = em.EditorDoc(_wdef([_row(3, [2, 4, 6]), _btn("z")]))
    # within row: cell 0 -> before-removal index 3 (end); spans travel
    assert doc.move((0, 0), (0, 3)) == (0, 2)
    assert _spans(doc, 0) == [4, 6, 2]
    assert [c["label"] for c in doc.wdef["rows"][0]["cells"]] == ["1", "2",
                                                                   "0"]
    # between rows: cell 1 into row 1 (plain button -> wrapped)
    assert doc.move((0, 1), (1, 1)) == (1, 1)
    assert len(doc.wdef["rows"][0]["cells"]) == 2
    assert doc.wdef["rows"][1]["type"] == "ROW"
    assert [c["label"] for c in doc.wdef["rows"][1]["cells"]] == ["z", "2"]


def test_move_cell_to_top_level():
    doc = em.EditorDoc(_wdef([_row(2, [6, 6]), _btn("z")]))
    assert doc.move((0, 0), (2, None)) == (2, None)
    assert doc.wdef["rows"][2]["label"] == "0"
    assert "span" not in doc.wdef["rows"][2]
    assert len(doc.wdef["rows"][0]["cells"]) == 1  # single-cell ROW kept


def test_move_last_cell_out_removes_row():
    doc = em.EditorDoc(_wdef([_row(1), _btn("z")]))
    # target (2, None) is "end" before removal -> index 1 after
    assert doc.move((0, 0), (2, None)) == (1, None)
    assert [r["type"] for r in doc.wdef["rows"]] == ["BUTTON", "BUTTON"]
    assert doc.wdef["rows"][0]["label"] == "z"


def test_move_last_cell_into_other_row_removes_row():
    doc = em.EditorDoc(_wdef([_row(1), _btn("z")]))
    assert doc.move((0, 0), (1, 1)) == (0, 1)  # z's row index shifts to 0
    assert len(doc.wdef["rows"]) == 1
    assert doc.wdef["rows"][0]["type"] == "ROW"


def test_move_top_level_row_reorders():
    doc = em.EditorDoc(_wdef([_btn("a"), _btn("b"), _btn("c")]))
    assert doc.move((0, None), (3, None)) == (2, None)
    assert [r["label"] for r in doc.wdef["rows"]] == ["b", "c", "a"]


def test_move_row_container_only_to_row_targets():
    doc = em.EditorDoc(_wdef([_row(2), _btn("z")]))
    before = copy.deepcopy(doc.wdef)
    assert doc.move((0, None), (1, 0)) is None
    assert doc.wdef == before and not doc.can_undo
    assert doc.move((0, None), (2, None)) == (1, None)
    assert doc.wdef["rows"][1]["type"] == "ROW"


def test_set_span_clamps_and_assigns_defaults():
    doc = em.EditorDoc(_wdef([_row(3)]))
    assert doc.set_span((0, 0), 8)
    assert _spans(doc, 0) == [4, 4, 4]
    assert doc.set_span((0, 1), 2)
    assert _spans(doc, 0) == [4, 2, 4]
    assert doc.set_span((0, 0), 6)
    assert _spans(doc, 0) == [6, 2, 4]
    assert doc.set_span((0, 0), 12)
    assert _spans(doc, 0) == [6, 2, 4]


def test_set_span_noop_not_recorded():
    doc = em.EditorDoc(_wdef([_row(2, [6, 6])]))
    assert doc.set_span((0, 0), 6)   # valid, nothing to change
    assert doc.set_span((0, 0), 9)   # clamps to 6, unchanged
    assert not doc.can_undo and not doc.dirty
    assert not doc.set_span((7, 0), 3)


def test_set_span_min_one():
    doc = em.EditorDoc(_wdef([_row(2, [6, 6])]))
    doc.set_span((0, 0), 0)
    assert _spans(doc, 0) == [1, 6]


def test_set_span_top_level_and_row_container():
    doc = em.EditorDoc(_wdef([_btn("a"), _row(2)]))
    assert doc.set_span((0, None), 5)
    assert doc.wdef["rows"][0]["span"] == 5
    assert doc.set_span((0, None), 99)
    assert doc.wdef["rows"][0]["span"] == 12
    assert doc.set_span((1, None), 4) is False  # ROW containers: no span


def test_five_cell_default_spans():
    doc = em.EditorDoc(_wdef([_row(5)]))
    doc.set_span((0, 0), 3)
    assert _spans(doc, 0) == [3, 3, 2, 2, 2]


def test_delete_cell_and_row():
    doc = em.EditorDoc(_wdef([_row(2), _btn("z")]))
    assert doc.delete((0, 0))
    assert len(doc.wdef["rows"][0]["cells"]) == 1
    assert doc.delete((0, 0))  # last cell -> row removed
    assert [r["type"] for r in doc.wdef["rows"]] == ["BUTTON"]
    assert doc.selection is None
    assert not doc.delete((5, None))


def test_delete_last_row_leaves_empty_rows():
    doc = em.EditorDoc(_wdef([_btn("a")]))
    assert doc.delete((0, None))
    assert doc.wdef["rows"] == []
    assert composed.validate_def(doc.wdef)[0]["rows"] == []


def test_undo_redo_and_refused_commit_not_recorded():
    doc = em.EditorDoc(_wdef([_btn("a")]))
    assert not doc.can_undo and not doc.can_redo
    assert doc.commit(lambda w: False) is False
    assert not doc.can_undo
    doc.insert((1, None), em.new_element("BUTTON"))
    assert doc.can_undo and not doc.can_redo
    doc.selection = (1, None)
    assert doc.undo()
    assert len(doc.wdef["rows"]) == 1
    assert doc.selection is None  # path no longer resolves
    assert doc.can_redo and doc.redo()
    assert len(doc.wdef["rows"]) == 2
    assert not doc.redo()
    doc.undo()
    doc.insert((0, None), em.new_element("SECTION"))
    assert not doc.can_redo  # new commit clears redo


def test_undo_keeps_resolving_selection():
    doc = em.EditorDoc(_wdef([_btn("a"), _btn("b")]))
    doc.set_field((0, None), "label", "x")
    doc.selection = (0, None)
    doc.undo()
    assert doc.selection == (0, None)


def test_history_limit():
    doc = em.EditorDoc(_wdef([_btn("a")]), history_limit=3)
    for i in range(6):
        doc.set_field((0, None), "label", f"v{i}")
    n = 0
    while doc.undo():
        n += 1
    assert n == 3


def test_commit_exception_restores_and_raises():
    doc = em.EditorDoc(_wdef([_btn("a")]))

    def boom(w):
        w["rows"].clear()
        raise RuntimeError("x")

    try:
        doc.commit(boom)
    except RuntimeError:
        pass
    assert len(doc.wdef["rows"]) == 1 and not doc.can_undo


def test_set_field_and_delete_key():
    doc = em.EditorDoc(_wdef([_row(2)]))
    assert doc.set_field((0, 1), "label", "Hi")
    assert doc.get((0, 1))["label"] == "Hi"
    assert not doc.set_field((0, 1), "label", "Hi")
    assert doc.set_field((0, 1), "label", None)
    assert "label" not in doc.get((0, 1))
    assert not doc.set_field((0, 1), "type", "SLIDER")
    assert not doc.set_field((9, None), "label", "x")


def test_set_widget_field():
    doc = em.EditorDoc(_wdef([]))
    assert doc.set_widget_field("title", "New")
    assert doc.wdef["title"] == "New"
    assert doc.set_widget_field("width", 200.0)
    assert doc.set_widget_field("width", None)
    assert "width" not in doc.wdef
    assert not doc.set_widget_field("rows", [])
    assert not doc.set_widget_field("name", None)


def test_preview_rows_placeholder_keeps_mapping():
    doc = em.EditorDoc(_wdef([
        {"type": "SECTION", "label": "S"},
        {"type": "BUTTON", "label": "B", "op": ""},
        {"type": "ROW", "cells": [_btn("ok"),
                                  {"type": "BUTTON", "label": "x", "op": ""}]},
    ]))
    pv = doc.preview_rows()
    assert len(pv) == len(doc.wdef["rows"])
    assert pv[0] == {"type": "SECTION", "label": "S"}
    assert pv[1]["type"] == "SPACER" and pv[1]["_placeholder"] == "Button"
    assert pv[1].get("span") is None
    assert pv[2]["cells"][0]["type"] == "BUTTON"
    assert pv[2]["cells"][1]["type"] == "SPACER"
    assert pv[2]["cells"][1]["_placeholder"] == "Button"
    # builds into controls; placeholder reaches Spacer
    ctrls = composed.build_controls(pv)
    assert ctrls[1].kind == "spacer" and ctrls[1].placeholder == "Button"
    assert ctrls[2].children[1].placeholder == "Button"


def test_preview_rows_keep_spans_for_placeholders():
    doc = em.EditorDoc(_wdef([
        {"type": "BUTTON", "label": "B", "op": "", "span": 5}]))
    assert doc.preview_rows()[0]["span"] == 5


def test_incomplete_lists_paths():
    doc = em.EditorDoc(_wdef([
        {"type": "SECTION", "label": "S"},
        {"type": "BUTTON", "label": "B", "op": ""},
        {"type": "ROW", "cells": [_btn("ok"),
                                  {"type": "BUTTON", "label": "x", "op": ""}]},
    ]))
    assert doc.incomplete() == [(1, None), (2, 1)]


def test_resume_is_undoable():
    doc = em.EditorDoc(_wdef([_btn("a")]))
    pre = copy.deepcopy(doc.wdef)
    draft = _wdef([_btn("x"), _fb("f1"), _fb("f2")])
    assert doc.replace_all(draft)
    assert len(doc.wdef["rows"]) == 2  # flipboxes normalized into a ROW
    assert doc.wdef["rows"][1]["type"] == "ROW"
    assert doc.undo()
    assert doc.wdef == pre


def test_resolve_save_name_collision():
    assert em.resolve_save_name("b", "a", {"a", "b"}) == "b_2"
    assert em.resolve_save_name("c", "a", {"a", "b"}) == "c"


def test_resolve_save_name_unchanged():
    assert em.resolve_save_name("a", "a", {"a", "b"}) == "a"
    assert em.resolve_save_name("  ", "a", {"a", "b"}) == "a"


def test_span_bounds_plain_and_row_cells():
    rows = [
        {"type": "BUTTON", "label": "a", "op": "x", "span": 6},
        _btn("b"),
        {"type": "ROW", "cells": [_btn("c"), _btn("d"), _btn("e")]},
        {"type": "ROW", "cells": [dict(_btn("f"), span=3),
                                  dict(_btn("g"), span=5)]},
    ]
    assert em.span_bounds(rows, (0, None)) == (0, 6, 12)
    assert em.span_bounds(rows, (1, None)) == (0, 12, 12)
    assert em.span_bounds(rows, (2, None)) is None      # ROW container
    assert em.span_bounds(rows, (2, 1)) == (4, 4, 4)    # default 4/4/4
    assert em.span_bounds(rows, (3, 0)) == (0, 3, 7)
    assert em.span_bounds(rows, (3, 1)) == (3, 5, 9)
    assert em.span_bounds(rows, (9, None)) is None


def test_span_bounds_matches_set_span_clamp():
    doc = em.EditorDoc(_wdef([
        {"type": "ROW", "cells": [dict(_btn("f"), span=3),
                                  dict(_btn("g"), span=5)]}]))
    start, _span, mx = em.span_bounds(doc.wdef["rows"], (0, 1))
    assert doc.set_span((0, 1), 12)
    assert doc.wdef["rows"][0]["cells"][1]["span"] == mx


# -- merge_key coalescing (dragged N-panel numbers) ---------------------
def _drag_doc():
    return em.EditorDoc(_wdef([{"type": "SPACER", "height": 4.0},
                               _btn("a")]))


def test_merge_same_key_is_one_undo_step():
    doc = _drag_doc()
    original = copy.deepcopy(doc.wdef)
    key = ("field", (0, None), "height")
    for h in (5.0, 6.0, 7.0):
        assert doc.set_field((0, None), "height", h, merge_key=key)
    assert doc.wdef["rows"][0]["height"] == 7.0
    assert doc.undo()
    assert doc.wdef == original
    assert not doc.can_undo


def test_merge_broken_by_other_key():
    doc = _drag_doc()
    key = ("field", (0, None), "height")
    doc.set_field((0, None), "height", 5.0, merge_key=key)
    doc.set_field((1, None), "label", "x")
    doc.set_field((0, None), "height", 6.0, merge_key=key)
    assert doc.undo()
    assert doc.wdef["rows"][0]["height"] == 5.0
    assert doc.undo()
    assert doc.wdef["rows"][1]["label"] == "a"
    assert doc.undo()
    assert doc.wdef["rows"][0]["height"] == 4.0
    assert not doc.can_undo


def test_merge_broken_by_different_merge_key():
    doc = _drag_doc()
    doc.set_field((0, None), "height", 5.0, merge_key=("a",))
    doc.set_field((0, None), "height", 6.0, merge_key=("b",))
    assert doc.undo()
    assert doc.wdef["rows"][0]["height"] == 5.0


def test_undo_then_same_key_starts_new_step():
    doc = _drag_doc()
    key = ("field", (0, None), "height")
    doc.set_field((0, None), "height", 5.0, merge_key=key)
    doc.set_field((0, None), "height", 6.0, merge_key=key)
    assert doc.undo()                       # back to 4.0
    doc.set_field((0, None), "height", 8.0, merge_key=key)
    assert not doc.can_redo
    assert doc.undo()
    assert doc.wdef["rows"][0]["height"] == 4.0
    assert not doc.can_undo


def test_merge_key_on_set_span():
    doc = _drag_doc()
    key = ("field", (1, None), "span")
    for sp in (3, 4, 5):
        assert doc.set_span((1, None), sp, merge_key=key)
    assert doc.wdef["rows"][1]["span"] == 5
    assert doc.undo()
    assert "span" not in doc.wdef["rows"][1]
