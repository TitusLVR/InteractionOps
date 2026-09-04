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
