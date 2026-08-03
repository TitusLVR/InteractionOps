import math
import pytest

from utils.smart_inset_core import (
    edge_normal, vertex_velocity, EPS,
)


def test_edge_normal_points_left_of_direction():
    # edge along +X, CCW outer loop -> inward normal is +Y
    n = edge_normal((0.0, 0.0), (2.0, 0.0))
    assert n == pytest.approx((0.0, 1.0))


def test_velocity_straight_vertex():
    # collinear edges: velocity equals the shared inward normal
    n = (0.0, 1.0)
    v = vertex_velocity(n, n, 1.0, 1.0)
    assert v == pytest.approx((0.0, 1.0))


def test_velocity_right_angle():
    # square corner at origin: edges +X then +Y, normals (0,1) and (-1,0)
    v = vertex_velocity((0.0, 1.0), (-1.0, 0.0), 1.0, 1.0)
    assert v == pytest.approx((-1.0, 1.0))
    assert math.hypot(*v) == pytest.approx(math.sqrt(2.0))


def test_velocity_reflex_vertex():
    # reflex corner (270 deg interior): normals (0,1) and (1,0)
    # velocity must satisfy both plane constraints
    v = vertex_velocity((0.0, 1.0), (1.0, 0.0), 1.0, 1.0)
    assert v[0] == pytest.approx(1.0)
    assert v[1] == pytest.approx(1.0)


def test_velocity_zero_weight_slides_along_fixed_edge():
    # prev edge weight 0 (open border, use_boundary off):
    # vertex must stay ON the prev edge line while offsetting from next
    n_prev, n_next = (0.0, 1.0), (-1.0, 0.0)
    v = vertex_velocity(n_prev, n_next, 0.0, 1.0)
    assert v == pytest.approx((-1.0, 0.0))  # slides along the fixed edge


def test_velocity_spike_is_capped():
    # near-opposite normals (theta -> 0 spike): finite result, no NaN/inf
    v = vertex_velocity((0.0, 1.0), (1e-12, -1.0), 1.0, 1.0)
    assert all(math.isfinite(c) for c in v)
    assert math.hypot(*v) <= 1e6  # SPEED_CAP
