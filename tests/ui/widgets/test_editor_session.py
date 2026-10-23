"""Pure tests for the draft gate of ui/widgets/editor.py (no bpy: the
module defers bpy to call time and every bpy-touching helper is guarded).

Covers the final-review rulings: while an older draft is undecided no
doc-changing edit is allowed (can_edit), and neither Cancel nor Save's
end() deletes that draft."""
import importlib
import os
import sys

import pytest

_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__),
                                      "..", "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

editor = importlib.import_module("ui.widgets.editor")
em = importlib.import_module("ui.widgets.editor_model")


class _FakePanel:
    title = ""
    x = y = 0.0


class _FakeWidget:
    def __init__(self):
        self.name = "w"
        self.title = "W"
        self.switches = {}
        self.panel = _FakePanel()
        self.composed_def = {"version": 1, "name": "w", "title": "W",
                             "space": ["VIEW_3D"], "switches": {},
                             "rows": []}
        self._editor = None

    def mark_dirty(self):
        pass


@pytest.fixture
def session(tmp_path):
    widget = _FakeWidget()
    s = editor.Session("w", em.EditorDoc(widget.composed_def), widget)
    s.draft_file = str(tmp_path / "w.draft.json")
    editor._session = s
    yield s
    editor._session = None


def test_can_edit_false_without_session():
    editor._session = None
    assert editor.can_edit() is False


def test_can_edit_gated_by_undecided_draft(session):
    assert editor.can_edit() is True
    session.draft_available = True
    assert editor.can_edit() is False


def test_write_draft_never_clobbers_undecided_draft(session):
    with open(session.draft_file, "w", encoding="utf-8") as f:
        f.write("OLD")
    session.draft_available = True
    editor.write_draft()
    with open(session.draft_file, encoding="utf-8") as f:
        assert f.read() == "OLD"


def test_cancel_end_keeps_undecided_draft(session):
    with open(session.draft_file, "w", encoding="utf-8") as f:
        f.write("OLD")
    session.draft_available = True
    editor.end(keep_draft=False)
    assert editor.active() is None
    assert os.path.isfile(session.draft_file)


def test_cancel_end_removes_own_draft(session):
    editor.write_draft()
    assert os.path.isfile(session.draft_file)
    editor.end(keep_draft=False)
    assert not os.path.isfile(session.draft_file)
