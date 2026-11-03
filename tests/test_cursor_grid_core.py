"""Cursor Place adaptive grid + floor grid snap: pure math."""
import math

from utils.cursor_place_core import (
    grid_nodes, auto_grid_step, nearest_grid_node, grid_lines,
    floor_level, snap_to_step,
)

SQ = [(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)]
N = (0, 0, 1)


def _approx(a, b, tol=1e-6):
    return all(abs(x - y) < tol for x, y in zip(a, b))


def _xy(nodes):
    return {(round(p[0], 6), round(p[1], 6)) for p in nodes}


def test_auto_step_is_a_quarter_of_the_shortest_edge():
    assert math.isclose(auto_grid_step(SQ), 0.25)
    rect = [(0, 0, 0), (2, 0, 0), (2, 1, 0), (0, 1, 0)]
    assert math.isclose(auto_grid_step(rect), 0.25)


def test_grid_nodes_unit_square_half_step():
    nodes, step, frame, bounds = grid_nodes(SQ, N, 0.5)
    assert math.isclose(step, 0.5)
    assert len(nodes) == 9
    assert _xy(nodes) == {(i * 0.5, j * 0.5) for i in range(3) for j in range(3)}
    origin, u, v = frame
    assert _approx(origin, (0, 0, 0)) and _approx(u, (1, 0, 0)) and _approx(v, (0, 1, 0))
    assert _approx(bounds, (0, 1, 0, 1))


def test_grid_nodes_triangle_excludes_outside():
    tri = [(0, 0, 0), (1, 0, 0), (0, 1, 0)]
    nodes, _step, _frame, _b = grid_nodes(tri, N, 0.5)
    assert _xy(nodes) == {(0, 0), (0.5, 0), (1, 0), (0, 0.5), (0.5, 0.5), (0, 1)}


def test_grid_nodes_step_doubles_until_under_the_cap():
    _nodes, step, _frame, _b = grid_nodes(SQ, N, 0.01, max_nodes=40)
    assert math.isclose(step, 0.32)                 # 0.01 · 2^5: 4×4 nodes


def test_grid_nodes_follow_the_polygon_plane():
    wall = [(0, 0, 0), (1, 0, 0), (1, 0, 1), (0, 0, 1)]
    nodes, _s, (origin, u, v), _b = grid_nodes(wall, (0, -1, 0), 0.5)
    assert len(nodes) == 9 and all(abs(p[1]) < 1e-9 for p in nodes)
    assert _approx(u, (1, 0, 0)) and _approx(v, (0, 0, 1))


def test_nearest_grid_node():
    nodes, _s, _f, _b = grid_nodes(SQ, N, 0.5)
    assert _approx(nearest_grid_node(nodes, (0.4, 0.6, 0)), (0.5, 0.5, 0))
    assert nearest_grid_node([], (0, 0, 0)) is None


def test_grid_lines_cover_the_bounds():
    _n, step, frame, bounds = grid_nodes(SQ, N, 0.5)
    lines = grid_lines(frame, step, bounds)
    assert len(lines) == 6                          # 3 along u + 3 along v
    assert all(len(seg) == 2 and len(seg[0]) == 3 for seg in lines)
    assert any(_approx(a, (0.5, 0, 0)) and _approx(b, (0.5, 1, 0)) for a, b in lines)


def test_floor_level_finest_level_at_least_min_px():
    assert math.isclose(floor_level(1.0, 50.0, 16, 10), 1.0)
    assert math.isclose(floor_level(1.0, 500.0, 16, 10), 0.1)
    assert math.isclose(floor_level(1.0, 5.0, 16, 10), 10.0)
    assert math.isclose(floor_level(2.0, 50.0, 16, 10), 2.0)


def test_snap_to_step_rounds_the_given_axes_only():
    assert _approx(snap_to_step((0.26, -0.74, 3.0), 0.5, axes=(0, 1)), (0.5, -0.5, 3.0))
    assert _approx(snap_to_step((0.26, -0.74, 3.1), 0.5), (0.5, -0.5, 3.0))
