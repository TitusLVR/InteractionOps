"""Filtering behavior of Widget.rows()/control_at().

Two test layers:
- FakeWidget: a minimal stand-in that exercises the filter_controls +
  _show_if contract directly, without importing ui.widgets.
- Real-Widget tests: import the actual Widget class and verify that
  rows()/control_at() correctly index the FILTERED visible list when
  given a duck-typed fake context (mode/active_object/selected_objects).
  No monkeypatching — ui.widgets.__init__ guards all bpy imports so the
  real Widget is importable under plain pytest.
"""
import importlib.util
import os
import sys

_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__),
                                      "..", "..", ".."))


def _load(name, relpath):
    path = os.path.join(_ROOT, *relpath)
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


predicates = _load("iops_test_predicates2",
                   ("ui", "widgets", "predicates.py"))
controls = _load("iops_test_controls2", ("ui", "widgets", "controls.py"))


def _ctx(mode="OBJECT", switches=None):
    return predicates.EvalCtx(mode, None, switches or {},
                              prop_fn=lambda p: (None, False),
                              selection_fn=lambda k: False)


class FakeWidget:
    """Minimal stand-in exercising the rows()/control_at() logic copied
    behaviorally — validated against the real methods in Blender (Task 9).
    Here we test the pure filter contract the methods rely on."""
    def __init__(self, ctrls, ctx):
        self.controls = ctrls
        self._ctx = ctx

    def rows(self, context=None):
        if context is None:
            return self.controls
        return predicates.filter_controls(self.controls, self._ctx)


def test_rows_filters_by_switch():
    a = controls.Section("always")
    b = controls.Section("adv"); b._show_if = {"switch": "adv"}
    w_on = FakeWidget([a, b], _ctx(switches={"adv": True}))
    w_off = FakeWidget([a, b], _ctx(switches={"adv": False}))
    assert w_on.rows(context=object()) == [a, b]
    assert w_off.rows(context=object()) == [a]
    # No context -> unfiltered
    assert w_off.rows() == [a, b]


# ---------------------------------------------------------------------------
# Real Widget tests — import the actual class; no monkeypatching required
# ---------------------------------------------------------------------------

class _FakeCtx:
    """Duck-typed Blender context for use with Widget.rows()/control_at().
    build_eval_ctx only reads .mode, .active_object, .selected_objects."""
    mode = "OBJECT"
    active_object = None
    selected_objects = []


class _ThreeControlWidget:
    """Widget subclass with three controls pre-set at construction."""
    pass


def _make_real_widget():
    """Build a real Widget instance with three controls:
      index 0 — always-visible Section("alpha")
      index 1 — switch-gated Section("beta"), _show_if={"switch": "adv"}
      index 2 — always-visible Section("gamma")
    Returns the instance; caller sets inst.switches["adv"] as needed.

    build_eval_ctx has a deferred relative import (from ...widgets.composed)
    that fails under plain pytest (the relative path exceeds the top-level
    package boundary). We patch it in place on the already-imported module
    with a bpy-free equivalent — constructing EvalCtx directly — so the
    rest of Widget.rows()/control_at() runs unmodified.
    """
    import ui.widgets as _fw          # triggers the guarded bpy-free import
    import ui.widgets.predicates as _pred
    from ui.widgets import Widget, Section

    # Patch build_eval_ctx to avoid the deferred relative import that
    # fails under pytest (beyond-top-level relative import).
    def _patched_build_eval_ctx(context, switches):
        mode = getattr(context, "mode", "")
        obj = getattr(context, "active_object", None)
        object_type = getattr(obj, "type", None) if obj is not None else None
        return _pred.EvalCtx(
            mode, object_type, switches,
            prop_fn=lambda path: (None, False),
            selection_fn=lambda kind: (
                bool(getattr(context, "selected_objects", None))
                if kind == "objects" else False
            ),
        )

    _pred.build_eval_ctx = _patched_build_eval_ctx

    class ThreeCtrlWidget(Widget):
        name = "test_three_ctrl"

        def build(self):
            return []   # we assign controls directly after __init__

    inst = ThreeCtrlWidget()
    # Replace controls with our three-item list.
    alpha = Section("alpha")
    beta = Section("beta")
    beta._show_if = {"switch": "adv"}
    gamma = Section("gamma")
    inst.controls = [alpha, beta, gamma]
    inst.switches = {"adv": False}
    return inst, alpha, beta, gamma


def test_real_widget_rows_filtered_by_switch():
    """rows() returns only controls whose show_if passes."""
    inst, alpha, _beta, gamma = _make_real_widget()
    fake_ctx = _FakeCtx()

    # adv=False: beta is hidden
    visible = inst.rows(fake_ctx)
    assert visible == [alpha, gamma], f"Expected [alpha, gamma], got {visible}"

    # adv=True: all three visible
    inst.switches["adv"] = True
    visible_all = inst.rows(fake_ctx)
    assert visible_all == [alpha, _beta, gamma]


def test_real_widget_control_at_indexes_filtered_list():
    """control_at(ctx, row, col) indexes the FILTERED list, not raw controls.

    Key assertion: with adv=False the visible list is [alpha, gamma].
    control_at(ctx, 1, 0) must return gamma (index 1 of filtered list),
    NOT beta (index 1 of the raw controls list)."""
    inst, alpha, beta, gamma = _make_real_widget()
    fake_ctx = _FakeCtx()

    # adv=False: visible = [alpha, gamma]
    assert inst.control_at(fake_ctx, 0, 0) is alpha
    assert inst.control_at(fake_ctx, 1, 0) is gamma   # not beta!
    assert inst.control_at(fake_ctx, 2, 0) is None    # out of range

    # adv=True: visible = [alpha, beta, gamma]
    inst.switches["adv"] = True
    assert inst.control_at(fake_ctx, 0, 0) is alpha
    assert inst.control_at(fake_ctx, 1, 0) is beta    # now beta is at index 1
    assert inst.control_at(fake_ctx, 2, 0) is gamma


def test_widget_spaces_from_string():
    from ui.widgets import Widget
    class W(Widget):
        name = "w_str"
        space = "VIEW_3D"
    assert W().spaces == frozenset({"VIEW_3D"})


def test_widget_spaces_from_list():
    from ui.widgets import Widget
    class W(Widget):
        name = "w_list"
        space = ["VIEW_3D", "IMAGE_EDITOR"]
    assert W().spaces == frozenset({"VIEW_3D", "IMAGE_EDITOR"})


# ---------------------------------------------------------------------------
# Row cell visibility (grid rows keep slots, legacy rows collapse)
# ---------------------------------------------------------------------------
def _row_widget(children):
    from ui.widgets import Row
    inst, *_ = _make_real_widget()
    row = Row(children)
    inst.controls = [row]
    inst.switches = {"adv": False}
    return inst, row


def _btn(label, span=None, hidden=False):
    from ui.widgets import ActionButton
    b = ActionButton(label, "iops.x")
    b._span = span
    if hidden:
        b._show_if = {"switch": "adv"}
    return b


def test_hidden_cell_in_grid_row_keeps_slot():
    a, b, c = _btn("a", 4), _btn("b", 4, hidden=True), _btn("c", 4)
    inst, _row = _row_widget([a, b, c])
    (view,) = inst.rows(_FakeCtx())
    assert len(view.children) == 3
    assert view.children[0] is a and view.children[2] is c
    st = view.children[1]
    assert st.kind == "spacer" and st._span == 4


def test_hidden_cell_in_legacy_row_collapses():
    a, b, c = _btn("a"), _btn("b", hidden=True), _btn("c")
    inst, _row = _row_widget([a, b, c])
    (view,) = inst.rows(_FakeCtx())
    assert view.children == [a, c]


def test_all_cells_hidden_drops_row():
    inst, _row = _row_widget([_btn("a", 6, hidden=True),
                              _btn("b", 6, hidden=True)])
    assert inst.rows(_FakeCtx()) == []


def test_row_without_cell_show_if_returned_as_is():
    inst, row = _row_widget([_btn("a", 6), _btn("b", 6)])
    assert inst.rows(_FakeCtx()) == [row]
    assert inst.rows(_FakeCtx())[0] is row


def test_row_view_carries_row_attrs_and_source():
    a, b = _btn("a", 6), _btn("b", 6, hidden=True)
    inst, row = _row_widget([a, b])
    row._show_if = {"mode": ["OBJECT"]}
    row._span = 12
    (view,) = inst.rows(_FakeCtx())
    assert view is not row and view._source is row
    assert view._show_if == row._show_if and view._span == 12


def test_control_at_resolves_through_row_view():
    a, b, c = _btn("a", 4), _btn("b", 4, hidden=True), _btn("c", 4)
    inst, _row = _row_widget([a, b, c])
    ctx = _FakeCtx()
    assert inst.control_at(ctx, 0, 0) is a      # original, not a stand-in
    assert inst.control_at(ctx, 0, 2) is c
    assert inst.control_at(ctx, 0, 1).kind == "spacer"
    inst.switches["adv"] = True
    assert inst.control_at(ctx, 0, 1) is b
