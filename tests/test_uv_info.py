from utils.uv_info import uv_rect_bounds, format_uv_rect


def test_bounds_normalizes_drag_direction():
    # corner order reversed must give same min/max
    a = uv_rect_bounds((0.8, 0.1), (0.2, 0.7))
    b = uv_rect_bounds((0.2, 0.7), (0.8, 0.1))
    assert a == b
    uv_min, uv_max, size = a
    assert uv_min == (0.2, 0.1)
    assert uv_max == (0.8, 0.7)
    assert round(size[0], 6) == 0.6
    assert round(size[1], 6) == 0.6


def test_format_rounds_to_six_decimals():
    s = format_uv_rect((0.1234567, 0.2), (0.8, 0.9), (0.6765433, 0.7))
    assert s == "min: (0.123457, 0.200000) max: (0.800000, 0.900000) size: (0.676543, 0.700000)"


def test_format_respects_ndigits():
    s = format_uv_rect((0.12345, 0.2), (0.8, 0.9), (0.67655, 0.7), ndigits=3)
    assert s == "min: (0.123, 0.200) max: (0.800, 0.900) size: (0.677, 0.700)"
