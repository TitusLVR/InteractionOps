import math

import pytest

from utils.planarity import (
    face_deviation_deg,
    deviation_alpha,
    ALPHA_MIN,
    ALPHA_MAX,
    FULL_ANGLE_DEG,
)


PLANAR_QUAD = [(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)]

# Planar concave L-shape ngon (all z=0). Concave corner normals are
# anti-parallel to the face normal on a planar face — deviation must be 0.
PLANAR_CONCAVE_L = [(0, 0, 0), (2, 0, 0), (2, 1, 0), (1, 1, 0), (1, 2, 0), (0, 2, 0)]


def warped_quad(h):
    return [(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, h)]


class TestFaceDeviation:
    def test_planar_quad_is_zero(self):
        assert face_deviation_deg(PLANAR_QUAD) == pytest.approx(0.0, abs=1e-9)

    def test_triangle_is_always_zero(self):
        assert face_deviation_deg([(0, 0, 0), (1, 0, 0), (0.3, 0.9, 5.0)]) == 0.0

    def test_planar_concave_ngon_is_zero(self):
        assert face_deviation_deg(PLANAR_CONCAVE_L) == pytest.approx(0.0, abs=1e-9)

    def test_warped_quad_detected(self):
        # h=0.1 lifts one corner by 10% of the edge length — clearly
        # non-planar at sub-degree thresholds, but far from FULL_ANGLE.
        dev = face_deviation_deg(warped_quad(0.1))
        assert 2.0 < dev < 15.0

    def test_deviation_monotonic_in_warp(self):
        devs = [face_deviation_deg(warped_quad(h)) for h in (0.01, 0.05, 0.1, 0.3)]
        assert devs == sorted(devs)
        assert devs[0] > 0.0

    def test_rigid_transform_invariant(self):
        # Rotate the warped quad 90° around X and translate: deviation unchanged.
        base = warped_quad(0.2)
        moved = [(x + 5.0, -z + 2.0, y - 1.0) for (x, y, z) in base]
        assert face_deviation_deg(moved) == pytest.approx(
            face_deviation_deg(base), abs=1e-6)

    def test_collinear_corner_does_not_crash(self):
        # Middle vert of the bottom edge is collinear — its corner normal is
        # undefined and must be skipped, not crash or dominate.
        coords = [(0, 0, 0), (1, 0, 0), (2, 0, 0), (2, 1, 0), (0, 1, 0)]
        assert face_deviation_deg(coords) == pytest.approx(0.0, abs=1e-9)

    def test_fully_degenerate_face_is_zero(self):
        assert face_deviation_deg([(0, 0, 0), (0, 0, 0), (0, 0, 0), (0, 0, 0)]) == 0.0


class TestDeviationAlpha:
    def test_at_threshold_is_min(self):
        assert deviation_alpha(0.5, 0.5) == pytest.approx(ALPHA_MIN)

    def test_at_full_angle_is_max(self):
        assert deviation_alpha(FULL_ANGLE_DEG, 0.5) == pytest.approx(ALPHA_MAX)

    def test_clamped_above_full_angle(self):
        assert deviation_alpha(90.0, 0.5) == pytest.approx(ALPHA_MAX)

    def test_midpoint_between_min_max(self):
        mid = (0.5 + FULL_ANGLE_DEG) / 2.0
        expected = (ALPHA_MIN + ALPHA_MAX) / 2.0
        assert deviation_alpha(mid, 0.5) == pytest.approx(expected)

    def test_threshold_above_full_angle_returns_max(self):
        # Degenerate config (threshold >= ceiling): no ramp, just max.
        assert deviation_alpha(30.0, 20.0) == pytest.approx(ALPHA_MAX)
