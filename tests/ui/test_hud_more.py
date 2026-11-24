"""Pure-pytest tests for ui/hud/more.py: the More Options (Tab) switch and the help items. No bpy: the module is
loaded through a bare package so ui/hud/__init__.py (which draws through gpu) is never imported."""
import importlib
import os
import sys
import types

_HUD_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "ui", "hud")
_pkg = types.ModuleType("_iops_hud_bare")
_pkg.__path__ = [_HUD_DIR]
sys.modules.setdefault("_iops_hud_bare", _pkg)
more = importlib.import_module("_iops_hud_bare.more")
items = importlib.import_module("_iops_hud_bare.items")


class _Op:
    def __init__(self, **kw):
        self.show_options = False
        self.seed = 0
        self.__dict__.update(kw)


class _Event:
    def __init__(self, type_, value="PRESS", ctrl=False, alt=False, shift=False, oskey=False):
        self.type, self.value = type_, value
        self.ctrl, self.alt, self.shift, self.oskey = ctrl, alt, shift, oskey


def test_row_reads_the_switch():
    op = _Op()
    m = more.MoreOptions(op)
    row = m.row()
    assert row.name == "More Options (Tab)" == more.MORE_OPTIONS_LABEL
    assert row.value_text() == "✗"
    op.show_options = True
    assert row.value_text() == "✓"
    assert row.is_visible()


def test_when_shows_with_the_switch_only():
    op = _Op()
    vis = more.MoreOptions(op).when()
    assert not vis()
    op.show_options = True
    assert vis()


def test_when_also_shows_a_row_in_use_with_the_switch_off():
    op = _Op()
    vis = more.MoreOptions(op).when(also=lambda: op.seed != 0)
    assert not vis()
    op.seed = 3
    assert vis()
    op.show_options = True
    op.seed = 0
    assert vis()


def test_when_own_hides_the_row_either_way():
    op = _Op(show_options=True, seed=2)
    applies = {"v": False}
    vis = more.MoreOptions(op).when(own=lambda: applies["v"], also=lambda: op.seed != 0)
    assert not vis()
    applies["v"] = True
    assert vis()
    op.show_options, op.seed = False, 0
    assert not vis()


def test_when_is_a_visible_getter_on_a_param():
    op = _Op()
    m = more.MoreOptions(op)
    p = items.HUDParam("Seed (R)", lambda: op.seed, "int", visible_getter=m.when(also=lambda: op.seed != 0))
    assert not p.is_visible()
    m.toggle()
    assert p.is_visible()


def test_handle_toggles_on_a_tab_press():
    op = _Op()
    m = more.MoreOptions(op)
    assert m.handle(_Event("TAB"))
    assert op.show_options is True
    assert m.handle(_Event("TAB", shift=True))
    assert op.show_options is False


def test_handle_ignores_other_events():
    op = _Op()
    m = more.MoreOptions(op)
    for ev in (_Event("TAB", "RELEASE"), _Event("A"), _Event("TAB", ctrl=True), _Event("TAB", alt=True),
               _Event("TAB", oskey=True), _Event("MOUSEMOVE", "NOTHING")):
        assert not m.handle(ev)
    assert op.show_options is False


def test_other_attribute_name():
    op = _Op(more_rows=False)
    m = more.MoreOptions(op, attr="more_rows")
    m.handle(_Event("TAB"))
    assert op.more_rows is True and op.show_options is False


def test_help_item_is_always_shown_and_never_modified():
    it = more.help_item("Confirm", "Enter")
    assert (it.label, it.key, it.always_show) == ("Confirm", "Enter", True)
    assert it.state is items.ItemState.ON and it.default_state is items.ItemState.OFF


def test_help_sections_accepts_pairs_and_items():
    sec = items.HUDSection("Given", [more.help_item("A", "a")])
    out = more.help_sections([("Keys", [("Mode", "Q"), more.help_item("Seed", "R")]), sec])
    assert [s.title for s in out] == ["Keys", "Given"]
    assert [(it.label, it.key) for it in out[0].items] == [("Mode", "Q"), ("Seed", "R")]
    assert all(it.always_show for it in out[0].items)
    assert out[1] is sec


def test_help_keys_lists_every_key():
    class _Help:
        sections = more.help_sections([("A", [("x", "Q"), ("y", "W")]), ("B", [("z", "Tab")])])
    assert more.help_keys(_Help) == ["Q", "W", "Tab"]


class _Prop:
    def __init__(self, default, flag=False, array=0):
        self.default = default
        self.is_enum_flag = flag
        self.default_flag = default if flag else set()
        self.is_array = array > 0
        self.array_length = array
        self.default_array = default if array else ()


class _Rna:     # what op.properties.bl_rna of a real operator offers
    properties = {"mode": _Prop("ACTIVE"), "seed": _Prop(0), "axes": _Prop({"X"}, flag=True),
                  "color": _Prop((1.0, 0.0), array=2)}


def test_changed_compares_with_the_rna_defaults():
    op = _Op(mode="ACTIVE", axes={"X"}, color=[1.0, 0.0], properties=types.SimpleNamespace(bl_rna=_Rna))
    m = more.MoreOptions(op)
    assert not m.changed("mode", "seed", "axes", "color")()
    op.mode = "FIT"
    assert m.changed("mode")() and not m.changed("seed")()
    op.mode, op.axes = "ACTIVE", {"X", "Y"}
    assert m.changed("axes")()
    op.axes, op.color = {"X"}, [0.5, 0.0]
    assert m.changed("color")()
    assert not m.changed("unknown")()


def test_changed_as_also_shows_a_tab_row():
    op = _Op(mode="ACTIVE", properties=types.SimpleNamespace(bl_rna=_Rna))
    m = more.MoreOptions(op)
    vis = m.when(also=m.changed("mode"))
    assert not vis()
    op.mode = "FIT"
    assert vis()


def test_changed_ignores_bl_rna_of_the_instance():
    # A real operator instance's own bl_rna lists only the base Operator fields: changed() must not use it.
    op = _Op(mode="FIT", bl_rna=_Rna)
    assert not more.MoreOptions(op).changed("mode")()
