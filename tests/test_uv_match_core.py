import pytest

from utils.uv_match_core import dimension_scale


def test_uniform_matches_long_sides():
    # Target is a 1x4 vertical strip, reference a 2x0.5 horizontal strip.
    sx, sy = dimension_scale(1.0, 4.0, 2.0, 0.5, 'UNIFORM')
    assert sx == sy == pytest.approx(0.5)


def test_uniform_same_orientation():
    sx, sy = dimension_scale(1.0, 1.0, 3.0, 3.0, 'UNIFORM')
    assert sx == sy == pytest.approx(3.0)


def test_width_only():
    sx, sy = dimension_scale(1.0, 4.0, 2.0, 0.5, 'WIDTH')
    assert sx == pytest.approx(2.0)
    assert sy == 1.0


def test_height_only():
    sx, sy = dimension_scale(1.0, 4.0, 2.0, 0.5, 'HEIGHT')
    assert sx == 1.0
    assert sy == pytest.approx(0.125)


def test_degenerate_target_is_left_alone():
    assert dimension_scale(0.0, 0.0, 2.0, 0.5, 'UNIFORM') == (1.0, 1.0)
    assert dimension_scale(0.0, 4.0, 2.0, 0.5, 'WIDTH') == (1.0, 1.0)
    assert dimension_scale(1.0, 0.0, 2.0, 0.5, 'HEIGHT') == (1.0, 1.0)
