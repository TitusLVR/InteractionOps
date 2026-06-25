"""Pure-pytest tests for ui/widgets/controls.py — the Swatch control and the
shared operator-firing helper. No bpy: controls.py defers its only bpy touch
(_invoke_operator) to call time, so it is patched here."""
import ui.widgets.controls as controls
from ui.widgets.controls import (ActionButton, Swatch, Dropdown, InputField,
                                 ButtonGroup, button_group_options,
                                 preset_index, TextEditState,
                                 dropdown_item_rects, dropdown_index_at)


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


# ----------------------------------------------------------------------
# button_group_options — normalization (number values + enum items)
# ----------------------------------------------------------------------
def test_button_group_options_number_values():
    # Number mode: value = the number, label = fmt.format(value) + unit.
    opts = button_group_options(values=[2, 3, 4], items=None,
                                fmt="{:g}", unit="")
    assert opts == [(2, "2"), (3, "3"), (4, "4")]


def test_button_group_options_number_values_with_unit():
    opts = button_group_options(values=[0, 15, 90], items=None,
                                fmt="{:g}", unit="°")
    assert opts == [(0, "0°"), (15, "15°"), (90, "90°")]


def test_button_group_options_enum_plain_identifiers():
    # Enum mode: bare identifier -> (identifier, identifier).
    opts = button_group_options(values=None,
                                items=["SOLID", "MATERIAL"],
                                fmt="{:g}", unit="")
    assert opts == [("SOLID", "SOLID"), ("MATERIAL", "MATERIAL")]


def test_button_group_options_enum_id_label_pairs():
    # Enum mode: [id, label] pair -> (id, label); bare id falls back to id.
    opts = button_group_options(
        values=None,
        items=["SOLID", ["RENDERED", "Render"], ["MATERIAL", "Mat"]],
        fmt="{:g}", unit="")
    assert opts == [("SOLID", "SOLID"),
                    ("RENDERED", "Render"),
                    ("MATERIAL", "Mat")]


# ----------------------------------------------------------------------
# ButtonGroup — construction, active_index, index_at, write
# ----------------------------------------------------------------------
def _bg(options, value, set_sink=None):
    """Build a ButtonGroup whose live getter returns (value, False)."""
    def get(_ctx):
        return (value, False)

    def st(_ctx, v):
        if set_sink is not None:
            set_sink.append(v)
    return ButtonGroup(get=get, set=st, options=options)


def test_button_group_is_interactive_and_kind():
    bg = _bg([(2, "2"), (3, "3")], value=2)
    assert bg.kind == "buttons"
    assert bg.interactive is True


def test_button_group_active_index_number_epsilon():
    # Number match uses a float epsilon (abs(a-b) <= 1e-6).
    bg = _bg([(0.0, "0"), (0.5, "0.5"), (1.0, "1")], value=0.5 + 1e-9)
    assert bg.active_index(None) == 1


def test_button_group_active_index_enum_equality():
    bg = _bg([("SOLID", "SOLID"), ("RENDERED", "Render")], value="RENDERED")
    assert bg.active_index(None) == 1


def test_button_group_active_index_no_match_is_minus_one():
    # Off-grid value -> -1 (no button forced on).
    bg = _bg([(2, "2"), (3, "3"), (4, "4")], value=7)
    assert bg.active_index(None) == -1
    # None value (disabled / unresolved) also yields no highlight.
    bg_none = _bg([(2, "2"), (3, "3")], value=None)
    assert bg_none.active_index(None) == -1


def test_button_group_active_index_read_live_each_draw():
    box = {"v": 2}
    bg = ButtonGroup(get=lambda _c: (box["v"], False), set=lambda _c, _v: None,
                     options=[(2, "2"), (3, "3"), (4, "4")])
    assert bg.active_index(None) == 0
    box["v"] = 4                       # external popup changed the prop
    assert bg.active_index(None) == 2  # re-read, not cached


def test_button_group_index_at_matches_preset_index():
    bg = _bg([(2, "2"), (3, "3"), (4, "4")], value=2)
    rect_x, rect_w = 100.0, 300.0
    n = 3
    for mx in (110.0, 205.0, 380.0, 99.0):
        assert bg.index_at(mx, rect_x, rect_w) == \
            preset_index(mx, rect_x, rect_w, n)


def test_button_group_write_delegates_to_set():
    sink = []
    bg = _bg([(2, "2"), (3, "3")], value=2, set_sink=sink)
    bg.write(None, 3)
    assert sink == [3]


def _noset(_c, _v):
    pass


# ----------------------------------------------------------------------
# Dropdown — display, items resolution, write (in-overlay editing)
# ----------------------------------------------------------------------
def test_dropdown_kind_and_interactive():
    dd = Dropdown(get=lambda _c: ("DISTANCE", False), set=_noset,
                  path="scene.IOPS.rename.order")
    assert dd.kind == "dropdown"
    assert dd.interactive is True


def test_dropdown_display_with_labels():
    dd = Dropdown(get=lambda _c: ("DISTANCE", False), set=_noset,
                  path="scene.IOPS.rename.order",
                  labels={"DISTANCE": "By Distance", "SELECTION": "By Selection"})
    assert dd.display(None) == "By Distance"


def test_dropdown_display_without_label_falls_back_to_identifier():
    dd = Dropdown(get=lambda _c: ("SELECTION", False), set=_noset,
                  path="scene.IOPS.rename.order",
                  labels={"DISTANCE": "By Distance"})
    # No label declared for SELECTION -> raw identifier.
    assert dd.display(None) == "SELECTION"


def test_dropdown_display_none_is_em_dash():
    dd = Dropdown(get=lambda _c: (None, False), set=_noset,
                  path="scene.IOPS.rename.order")
    assert dd.display(None) == "—"


def test_dropdown_items_prefers_declared_labels():
    dd = Dropdown(get=lambda _c: ("A", False), set=_noset, path="x",
                  items_get=lambda _c: [("A", "live-A")],
                  labels={"A": "Label A", "B": "Label B"})
    # Declared labels win and define the selectable list (in order).
    assert dd.items(None) == [("A", "Label A"), ("B", "Label B")]


def test_dropdown_items_falls_back_to_items_get():
    dd = Dropdown(get=lambda _c: ("A", False), set=_noset, path="x",
                  items_get=lambda _c: [("A", "Apple"), ("B", "Banana")])
    assert dd.items(None) == [("A", "Apple"), ("B", "Banana")]
    # display uses the live item name when no labels declared
    assert dd.display(None) == "Apple"


def test_dropdown_items_empty_without_source():
    dd = Dropdown(get=lambda _c: ("A", False), set=_noset, path="x")
    assert dd.items(None) == []


def test_dropdown_write_delegates_to_set():
    sink = []
    dd = Dropdown(get=lambda _c: ("A", False),
                  set=lambda _c, v: sink.append(v), path="x")
    dd.write(None, "B")
    assert sink == ["B"]


# ----------------------------------------------------------------------
# InputField — display, edit_string seed, write (in-overlay editing)
# ----------------------------------------------------------------------
def test_input_field_kind_and_interactive():
    inp = InputField(get=lambda _c: ("foo", False), set=_noset,
                     path="scene.IOPS.rename.pattern")
    assert inp.kind == "input"
    assert inp.interactive is True


def test_input_field_display_string_value():
    inp = InputField(get=lambda _c: ("[N]_[C]", False), set=_noset,
                     path="scene.IOPS.rename.pattern", fmt="{}")
    assert inp.display(None) == "[N]_[C]"


def test_input_field_display_number_via_fmt():
    inp = InputField(get=lambda _c: (90.0, False), set=_noset,
                     path="object.data.angle", fmt="{:g}")
    assert inp.display(None) == "90"


def test_input_field_display_none_is_em_dash():
    inp = InputField(get=lambda _c: (None, False), set=_noset,
                     path="scene.IOPS.rename.pattern")
    assert inp.display(None) == "—"


def test_input_field_edit_string_seed():
    inp = InputField(get=lambda _c: (90.0, False), set=_noset,
                     path="x", fmt="{:g}")
    assert inp.edit_string(None) == "90"        # number -> formatted text
    none = InputField(get=lambda _c: (None, False), set=_noset, path="x")
    assert none.edit_string(None) == ""         # None -> empty buffer


def test_input_field_write_delegates_to_set():
    sink = []
    inp = InputField(get=lambda _c: ("x", False),
                     set=lambda _c, t: sink.append(t), path="x")
    inp.write(None, "hello")
    assert sink == ["hello"]


# ----------------------------------------------------------------------
# TextEditState — caret + selection editing (pure)
# ----------------------------------------------------------------------
def test_text_edit_insert_at_caret():
    s = TextEditState("ace")
    s.caret = 1
    s.anchor = 1
    s.insert("b")
    assert s.text == "abce" and s.caret == 2


def test_text_edit_backspace_and_delete():
    s = TextEditState("abc")        # caret at end (3)
    s.backspace()
    assert s.text == "ab" and s.caret == 2
    s.home()
    s.delete()
    assert s.text == "b" and s.caret == 0


def test_text_edit_caret_movement_clamps():
    s = TextEditState("ab")
    s.home(); assert s.caret == 0
    s.left(); assert s.caret == 0          # clamps at 0
    s.end(); assert s.caret == 2
    s.right(); assert s.caret == 2         # clamps at len


def test_text_edit_select_all_then_type_replaces():
    s = TextEditState("old")
    s.select_all()
    assert s.has_sel and s.sel_range() == (0, 3)
    s.insert("new")
    assert s.text == "new" and not s.has_sel


def test_text_edit_shift_extends_selection():
    s = TextEditState("abcd")          # caret 4
    s.left(extend=True)
    s.left(extend=True)
    assert s.sel_range() == (2, 4) and s.selected_text() == "cd"
    s.backspace()                       # deletes the selection
    assert s.text == "ab"


def test_text_edit_paste_replaces_selection():
    s = TextEditState("abc")
    s.select_all()
    s.insert("XY")                      # paste path = insert (replaces sel)
    assert s.text == "XY"


# ----------------------------------------------------------------------
# Open-dropdown geometry (shared by render + events)
# ----------------------------------------------------------------------
def test_dropdown_item_rects_stack_downward():
    rects = dropdown_item_rects(10.0, 100.0, 50.0, 20.0, 3)
    # item 0 directly below the field's bottom edge (y=100), going down
    assert rects[0] == (10.0, 80.0, 50.0, 20.0)
    assert rects[1] == (10.0, 60.0, 50.0, 20.0)
    assert rects[2] == (10.0, 40.0, 50.0, 20.0)


def test_dropdown_index_at_hits_and_misses():
    # 3 items of height 20 below y=100 -> spans y in [40,100]
    assert dropdown_index_at(90.0, 10.0, 100.0, 50.0, 20.0, 3) == 0
    assert dropdown_index_at(70.0, 10.0, 100.0, 50.0, 20.0, 3) == 1
    assert dropdown_index_at(45.0, 10.0, 100.0, 50.0, 20.0, 3) == 2
    assert dropdown_index_at(120.0, 10.0, 100.0, 50.0, 20.0, 3) == -1  # above
    assert dropdown_index_at(10.0, 10.0, 100.0, 50.0, 20.0, 3) == -1   # below
