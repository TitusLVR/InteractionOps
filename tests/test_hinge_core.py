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


def test_flush_angle_prefer_parallel_vs_antiparallel_are_180_apart():
    # top face (+Z) about the +X-running edge, target normal +Y
    par = flush_angle((0, 0, 1), (0, 1, 0), (1, 0, 0), prefer="parallel")
    anti = flush_angle((0, 0, 1), (0, 1, 0), (1, 0, 0), prefer="antiparallel")
    assert abs(abs(par - anti) - math.pi) < 1e-9
    # parallel: rotating +Z about +X by `par` must give +Y
    c, s_ = math.cos(par), math.sin(par)
    rotated = (0.0, -s_, c)   # R_x applied to (0,0,1)
    assert rotated == pytest.approx((0.0, 1.0, 0.0), abs=1e-9)
    # default stays the shortest representative
    short = flush_angle((0, 0, 1), (0, 1, 0), (1, 0, 0))
    assert abs(short) <= abs(par) + 1e-12 and abs(short) <= abs(anti) + 1e-12
