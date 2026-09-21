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


def test_both_matches_bbox_exactly():
    sx, sy = dimension_scale(1.0, 4.0, 2.0, 0.5, 'BOTH')
    assert sx == pytest.approx(2.0)
    assert sy == pytest.approx(0.125)


def test_fit_default_rotates_then_matches_both_axes():
    # Vertical bar 0.045x1.0 onto horizontal strip 0.3x0.0188:
    # turned it is 1.0x0.045, so x shrinks to 0.3 and y to 0.0188.
    from utils.uv_match_core import dimension_fit
    rot, sx, sy = dimension_fit(0.045, 1.0, 0.3, 0.0188)
    assert rot is True
    assert sx == pytest.approx(0.3)
    assert sy == pytest.approx(0.0188 / 0.045)


def test_degenerate_target_is_left_alone():
    assert dimension_scale(0.0, 0.0, 2.0, 0.5, 'UNIFORM') == (1.0, 1.0)
    assert dimension_scale(0.0, 4.0, 2.0, 0.5, 'WIDTH') == (1.0, 1.0)
    assert dimension_scale(1.0, 0.0, 2.0, 0.5, 'HEIGHT') == (1.0, 1.0)


from utils.uv_match_core import dimension_fit


def test_fit_rotates_transposed_strip():
    # Vertical bar onto a horizontal strip: rotate first, then match.
    rot, sx, sy = dimension_fit(0.045, 1.0, 0.3, 0.0188, 'UNIFORM')
    assert rot is True
    assert sx == sy == pytest.approx(0.3)


def test_fit_keeps_orientation_when_aspects_agree():
    rot, sx, sy = dimension_fit(0.5, 2.0, 0.25, 4.0, 'UNIFORM')
    assert rot is False
    assert sx == sy == pytest.approx(2.0)


def test_fit_width_only_after_rotation_uses_rotated_width():
    # After a 90 degree turn the bar is 1.0 wide, 0.045 tall.
    rot, sx, sy = dimension_fit(0.045, 1.0, 0.3, 0.0188, 'WIDTH')
    assert rot is True
    assert sx == pytest.approx(0.3)
    assert sy == 1.0


def test_fit_square_never_rotates():
    rot, sx, sy = dimension_fit(1.0, 1.0, 0.3, 0.0188, 'UNIFORM')
    assert rot is False
    assert sx == sy == pytest.approx(0.3)
