"""Pure-logic tests for widgets/uv_slots_logic.py — the name<->index
mapping behind the UV image slot enum. No bpy needed."""
import importlib
import os
import sys

_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__),
                                      "..", "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

logic = importlib.import_module("widgets.uv_slots_logic")


def test_index_of_present_name():
    assert logic.index_of_name(["", "imgA", "imgB"], "imgB") == 2


def test_index_of_absent_name_is_sentinel():
    assert logic.index_of_name(["", "imgA"], "gone") == 0


def test_index_of_empty_name_is_sentinel():
    assert logic.index_of_name(["", "imgA"], "") == 0


def test_name_at_valid_index():
    assert logic.name_at_index(["", "imgA", "imgB"], 1) == "imgA"


def test_name_at_out_of_range_is_sentinel():
    assert logic.name_at_index(["", "imgA"], 9) == logic.SENTINEL
    assert logic.name_at_index(["", "imgA"], -1) == logic.SENTINEL
