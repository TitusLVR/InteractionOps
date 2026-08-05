import math
import pytest

from utils.hinge_core import flush_angle


def test_quarter_turn_about_x():
    # plane normal +Z, target normal +Y, axis +X: rotating +Z by -90deg
    # about +X gives +Y
    a = flush_angle((0, 0, 1), (0, 1, 0), (1, 0, 0))
    assert a == pytest.approx(-math.pi / 2)


def test_already_flush_is_zero():
    assert flush_angle((0, 0, 1), (0, 0, 1), (1, 0, 0)) == pytest.approx(0.0)


def test_antiparallel_target_is_zero():
    # planes already coplanar even though normals oppose
    assert flush_angle((0, 0, 1), (0, 0, -1), (1, 0, 0)) == pytest.approx(0.0)


def test_picks_smaller_magnitude_solution():
    # +Z to a normal 135deg away about +X: direct solution is +135deg but
    # the anti-parallel representative is -45deg — must pick -45deg
    s = math.sin(math.radians(135))
    c = math.cos(math.radians(135))
    a = flush_angle((0, 0, 1), (0, -s, c), (1, 0, 0))
    assert a == pytest.approx(-math.radians(45))


def test_picks_smaller_magnitude_solution_opposite():
    # +Z to the opposite normal (135deg but other quadrant): direct solution
    # is -135deg but the anti-parallel representative is +45deg — pick +45deg
    s = math.sin(math.radians(135))
    c = math.cos(math.radians(135))
    a = flush_angle((0, 0, 1), (0, s, c), (1, 0, 0))
    assert a == pytest.approx(math.radians(45))


def test_axis_parallel_normal_returns_none():
    assert flush_angle((1, 0, 0), (0, 0, 1), (1, 0, 0)) is None
    assert flush_angle((0, 0, 1), (1, 0, 0), (1, 0, 0)) is None


def test_unnormalized_inputs():
    a = flush_angle((0, 0, 7), (0, 3, 0), (2, 0, 0))
    assert a == pytest.approx(-math.pi / 2)
