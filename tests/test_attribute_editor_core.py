from utils.attribute_editor_core import TYPES, Row, list_rows, format_value


def test_type_table_edit_support():
    assert TYPES["FLOAT"].bm_layer == "float"
    assert TYPES["BYTE_COLOR"].bm_layer == "color"
    assert TYPES["INT8"].bm_layer is None
    assert TYPES["FLOAT2"].bm_layer is None
    assert TYPES["VGROUP"].bm_layer == "deform"
    assert "HEATMAP" in TYPES["FLOAT_VECTOR"].preview
    assert "COLOUR" in TYPES["FLOAT_COLOR"].preview


def test_list_rows_filters_hidden_builtin_and_orders():
    attrs = [(".select_vert", "BOOLEAN", "POINT"), ("tilt", "FLOAT", "POINT"),
             ("sharp_edge", "BOOLEAN", "EDGE"), ("bw", "FLOAT", "EDGE"),
             ("UVMap", "FLOAT2", "CORNER"), ("Col", "BYTE_COLOR", "CORNER"),
             ("id", "INT", "FACE"), ("q", "QUATERNION", "POINT")]
    rows = list_rows(attrs, ["marks"], uv_names=("UVMap",),
                     color_names=("Col",))
    assert [r.name for r in rows] == ["q", "tilt", "bw", "id", "marks"]
    assert rows[0].editable is False and rows[1].editable is True
    assert rows[-1] == Row("marks", "VGROUP", "POINT", "VGROUP", True)
    attrs.append((".iops_ss_V_bolts", "INT", "POINT"))
    rows = list_rows(attrs, [], show_hidden=True, show_builtin=True,
                     show_vgroups=False)
    names = [r.name for r in rows]
    assert ".select_vert" in names
    assert ".iops_ss_V_bolts" not in names
    assert "sharp_edge" in names and "UVMap" in names


def test_list_rows_object_mode_everything_editable_but_string():
    rows = list_rows([("a", "INT8", "POINT"), ("s", "STRING", "POINT")], [],
                     edit_mode=False)
    assert [r.editable for r in rows] == [True, False]


def test_format_value():
    assert format_value(45.0, "FLOAT") == "45.00"
    assert format_value(45.0, "FLOAT", decimals=0) == "45"
    assert format_value((1.0, 2.5, 0.0), "FLOAT_VECTOR", decimals=1) \
        == "1.0 2.5 0.0"
    assert format_value(True, "BOOLEAN") == "1"
    assert format_value(7, "INT") == "7"


# ---------------------------------------------------------------------------
# Task 2: value maths, chains, predicates, heatmap
# ---------------------------------------------------------------------------
import pytest  # noqa: E402

from utils.attribute_editor_core import (  # noqa: E402
    default_value, coerce, mixed_count, math_op, randomize, smooth,
    order_chain, gradient, select_predicate, heat_color, luminance,
    scalar_for_preview)


def test_coerce_scalars_and_vectors():
    assert coerce(2.7, "FLOAT", "INT") == 2
    assert coerce(True, "BOOLEAN", "FLOAT") == 1.0
    assert coerce((1.0, 2.0, 3.0), "FLOAT_VECTOR", "FLOAT", component=2) == 3.0
    assert coerce(0.5, "FLOAT", "FLOAT_COLOR") == (0.5, 0.5, 0.5, 1.0)
    assert coerce("x", "STRING", "FLOAT") is None


def test_mixed_count():
    assert mixed_count([1.0, 1.0000001, 2.0]) == 2
    assert mixed_count([(1, 2, 3), (1, 2, 3)]) == 1


def test_math_ops():
    assert math_op([1.0, 2.0], "ADD", a=1.0) == [2.0, 3.0]
    assert math_op([1.0, 2.0], "MULTIPLY", a=2.0) == [2.0, 4.0]
    assert math_op([-1.0, 5.0], "CLAMP", a=0.0, b=1.0) == [0.0, 1.0]
    assert math_op([0.25], "INVERT") == [0.75]
    assert math_op([True], "INVERT") == [False]
    assert math_op([10.0, 20.0, 30.0], "REMAP", a=0.0, b=1.0) == [0.0, 0.5, 1.0]
    assert math_op([5.0, 5.0], "REMAP", a=2.0, b=3.0) == [2.0, 2.0]
    assert math_op([1.26], "ROUND", a=1) == [1.3]
    assert math_op([(1.0, 2.0, 3.0)], "MULTIPLY", a=2.0) == [(2.0, 4.0, 6.0)]


def test_randomize_is_seeded_and_bounded():
    a = randomize(5, 0.0, 10.0, 7, "FLOAT")
    b = randomize(5, 0.0, 10.0, 7, "FLOAT")
    assert a == b and all(0.0 <= v <= 10.0 for v in a)
    assert all(isinstance(v, int) for v in randomize(3, 1, 3, 1, "INT"))


def test_smooth_moves_toward_neighbour_mean():
    out = smooth([0.0, 10.0, 0.0], [[1], [0, 2], [1]], iterations=1,
                 factor=0.5)
    assert out[1] == pytest.approx(5.0) and out[0] == pytest.approx(5.0)
    assert smooth([3.0], [[]], iterations=3) == [3.0]


def test_order_chain_path_loop_and_branch():
    assert order_chain([5, 2, 9], [(2, 5), (9, 2)]) in ([5, 2, 9], [9, 2, 5])
    loop = order_chain([1, 2, 3], [(1, 2), (2, 3), (3, 1)])
    assert loop[0] == 1 and sorted(loop) == [1, 2, 3]
    assert order_chain([1, 2, 3, 4], [(1, 2), (2, 3), (2, 4)]) is None
    assert order_chain([1, 2, 3, 4], [(1, 2), (3, 4)]) is None
    assert order_chain([1], []) is None


def test_gradient():
    assert gradient(3, 0.0, 10.0) == [0.0, 5.0, 10.0]
    assert gradient(3, 0.0, 10.0, "EASE_IN_OUT") == [0.0, 5.0, 10.0]
    assert gradient(5, 0.0, 1.0, "EASE_IN_OUT")[1] == pytest.approx(0.15625)
    assert gradient(1, 2.0, 9.0) == [2.0]
    assert gradient(2, (0.0, 0.0, 0.0), (1.0, 2.0, 3.0)) \
        == [(0.0, 0.0, 0.0), (1.0, 2.0, 3.0)]


def test_select_predicate():
    assert select_predicate("EQUAL", 45.0, tol=0.01)(45.005)
    assert not select_predicate("EQUAL", 45.0)(46.0)
    assert select_predicate("RANGE", 1.0, hi=2.0)(1.5)
    assert not select_predicate("RANGE", 1.0, hi=2.0)(2.5)
    assert select_predicate("GREATER", 1.0)((0.0, 2.0, 0.0))


def test_heatmap_and_luminance():
    assert heat_color(0.0) == (0, 0, 1) and heat_color(1.0) == (1, 0, 0)
    assert heat_color(0.5) == (0, 1, 0)
    assert heat_color(0.125) == pytest.approx((0, 0.5, 1))
    assert luminance((1, 1, 1, 1)) == pytest.approx(1.0)
    assert scalar_for_preview((3.0, 4.0, 0.0), "FLOAT_VECTOR") == 5.0
    assert default_value("FLOAT_COLOR") == (0.0, 0.0, 0.0, 1.0)
