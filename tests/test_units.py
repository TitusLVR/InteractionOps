from utils.units import fixed_length_unit, format_fixed_length


def test_centimeters_not_adaptive():
    assert format_fixed_length(1.234, "METRIC", "CENTIMETERS") == "123.40 cm"


def test_scale_length_applied():
    assert format_fixed_length(1.0, "METRIC", "MILLIMETERS", scale_length=0.5) == "500.00 mm"


def test_imperial_feet():
    assert format_fixed_length(0.3048, "IMPERIAL", "FEET") == "1.00 ft"


def test_adaptive_and_none_fall_back():
    assert fixed_length_unit("METRIC", "ADAPTIVE") is None
    assert fixed_length_unit("NONE", "METERS") is None
    assert format_fixed_length(1.0, "METRIC", "ADAPTIVE") is None


# --- format_lengths: one unit per row, ADAPTIVE resolved deterministically ---

from utils.units import format_lengths


def test_row_keeps_fixed_unit():
    assert format_lengths([1.234, 0.5], "METRIC", "CENTIMETERS") == ["123.40 cm", "50.00 cm"]


def test_adaptive_uses_one_unit_from_largest_value():
    # Blender's own adaptive formatting would give "1.5 m", "50 cm", "2.3 cm"
    # (mixed units, significant-digit precision). Force one unit per row.
    assert format_lengths([1.5, 0.5, 0.0225], "METRIC", "ADAPTIVE") == ["1.50 m", "0.50 m", "0.02 m"]


def test_adaptive_small_object_in_centimeters():
    assert format_lengths([0.0225, 0.022, 0.0237], "METRIC", "ADAPTIVE") == ["2.25 cm", "2.20 cm", "2.37 cm"]


def test_adaptive_respects_scale_length():
    # 1 BU at scale_length 0.01 is one centimeter
    assert format_lengths([1.0], "METRIC", "ADAPTIVE", scale_length=0.01) == ["1.00 cm"]


def test_adaptive_imperial():
    assert format_lengths([0.3048 * 2], "IMPERIAL", "ADAPTIVE") == ["2.00 ft"]
    assert format_lengths([0.0254 * 3], "IMPERIAL", "ADAPTIVE") == ["3.00 in"]


def test_adaptive_zero_falls_to_base_unit():
    assert format_lengths([0.0, 0.0], "METRIC", "ADAPTIVE") == ["0.00 m", "0.00 m"]
    assert format_lengths([0.0], "IMPERIAL", "ADAPTIVE") == ["0.00 ft"]


def test_none_system_is_raw():
    assert format_lengths([1.234], "NONE", "METERS") == ["1.23"]
