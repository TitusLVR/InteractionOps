"""Pure-pytest tests for ui/widgets/controls.py — the Swatch control and the
shared operator-firing helper. No bpy: controls.py defers its only bpy touch
(_invoke_operator) to call time, so it is patched here."""
import ui.widgets.controls as controls
from ui.widgets.controls import ActionButton, Swatch


def test_action_button_execute_delegates_to_invoke_operator(monkeypatch):
    calls = []
    monkeypatch.setattr(controls, "_invoke_operator",
                        lambda op, kw: calls.append((op, kw)))
    btn = ActionButton("Apply", op="iops.object_color_apply", kwargs={"x": 1})
    btn.execute(context=None)
    assert calls == [("iops.object_color_apply", {"x": 1})]


def test_swatch_value_caches_and_refreshes_on_dirty():
    src = {"c": ((1.0, 0.0, 0.0, 1.0), False)}
    sw = Swatch(get=lambda ctx: src["c"], op="iops.x")
    assert sw.value(None) == ((1.0, 0.0, 0.0, 1.0), False)
    src["c"] = ((0.0, 1.0, 0.0, 1.0), False)
    assert sw.value(None) == ((1.0, 0.0, 0.0, 1.0), False)   # still cached
    sw.mark_dirty()
    assert sw.value(None) == ((0.0, 1.0, 0.0, 1.0), False)   # re-read


def test_swatch_disabled_sentinel_when_color_none():
    sw = Swatch(get=lambda ctx: (None, False), op="iops.x")
    assert sw.value(None) == (None, False)


def test_swatch_execute_delegates_with_kwargs(monkeypatch):
    calls = []
    monkeypatch.setattr(controls, "_invoke_operator",
                        lambda op, kw: calls.append((op, kw)))
    sw = Swatch(get=lambda ctx: ((1, 1, 1, 1), False),
                op="iops.object_color_apply_recent", kwargs={"index": 3})
    sw.execute(None)
    assert calls == [("iops.object_color_apply_recent", {"index": 3})]


def test_swatch_enabled_get_is_dirty_cached():
    flags = {"on": True}
    sw = Swatch(get=lambda ctx: ((1, 1, 1, 1), False), op="iops.x",
                enabled_get=lambda ctx: flags["on"])
    assert sw.update_enabled(None) is True
    flags["on"] = False
    assert sw.update_enabled(None) is True    # cached until mark_dirty
    sw.mark_dirty()
    assert sw.update_enabled(None) is False


def test_swatch_is_interactive_and_kind():
    sw = Swatch(get=lambda ctx: ((1, 1, 1, 1), False), op="iops.x")
    assert sw.kind == "swatch"
    assert sw.interactive is True


def test_control_has_show_if_default():
    # `controls` loaded per the file's existing pattern; use Section as
    # the simplest Control.
    s = controls.Section("x")
    assert s._show_if is None
