import math

import numpy as np
import pytest

from utils.obb_core import (
    oriented_bbox, box_corners_local, dominant_normals, pca_axes,
    DegenerateCloud,
)


def _rot(ax, ay, az):
    cx, sx = math.cos(ax), math.sin(ax)
    cy, sy = math.cos(ay), math.sin(ay)
    cz, sz = math.cos(az), math.sin(az)
    rx = np.array([[1, 0, 0], [0, cx, -sx], [0, sx, cx]])
    ry = np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]])
    rz = np.array([[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]])
    return rz @ ry @ rx


def _box_mesh(dims, rot, offset=(0, 0, 0)):
    """Vertices, face normals and areas of a box dims=(dx,dy,dz) rotated
    by `rot` and shifted by `offset`."""
    dx, dy, dz = dims
    corners = np.array([[sx * dx / 2, sy * dy / 2, sz * dz / 2]
                        for sx in (-1, 1) for sy in (-1, 1) for sz in (-1, 1)])
    verts = corners @ rot.T + np.asarray(offset)
    normals = np.array([[1, 0, 0], [-1, 0, 0], [0, 1, 0],
                        [0, -1, 0], [0, 0, 1], [0, 0, -1]], dtype=float) @ rot.T
    areas = np.array([dy * dz, dy * dz, dx * dz, dx * dz, dx * dy, dx * dy], dtype=float)
    return verts, normals, areas


def _assert_orthonormal(axes):
    assert np.allclose(axes.T @ axes, np.eye(3), atol=1e-9)
    assert np.linalg.det(axes) > 0


def _assert_box_fits(box, dims, verts):
    _assert_orthonormal(box.axes)
    ext = sorted(box.maxs - box.mins)
    assert np.allclose(ext, sorted(dims), atol=1e-6)
    local = verts @ box.axes
    assert np.all(local >= box.mins - 1e-9)
    assert np.all(local <= box.maxs + 1e-9)


def test_axis_aligned_box_keeps_world_axes():
    verts, n, a = _box_mesh((2, 1, 0.5), np.eye(3))
    box = oriented_bbox(verts, n, a)
    assert np.allclose(box.axes, np.eye(3), atol=1e-9)
    assert np.allclose(box.mins, (-1, -0.5, -0.25))
    assert np.allclose(box.maxs, (1, 0.5, 0.25))


def test_rotated_cube_is_found_by_face_normals():
    # The degenerate PCA case: a cube's covariance is isotropic.
    rot = _rot(0.4, -0.7, 1.1)
    verts, n, a = _box_mesh((1, 1, 1), rot, offset=(3, -2, 5))
    box = oriented_bbox(verts, n, a)
    _assert_box_fits(box, (1, 1, 1), verts)
    vol = float(np.prod(box.maxs - box.mins))
    assert math.isclose(vol, 1.0, abs_tol=1e-6)


def test_rotated_cube_without_normals_falls_back_to_pca_without_crashing():
    rot = _rot(0.4, -0.7, 1.1)
    verts, _, _ = _box_mesh((1, 1, 1), rot)
    box = oriented_bbox(verts)
    _assert_orthonormal(box.axes)
    local = verts @ box.axes
    assert np.all(local >= box.mins - 1e-9) and np.all(local <= box.maxs + 1e-9)


def test_rotated_slab_recovers_dims():
    rot = _rot(1.2, 0.3, -2.0)
    verts, n, a = _box_mesh((4, 2, 0.1), rot)
    box = oriented_bbox(verts, n, a)
    _assert_box_fits(box, (4, 2, 0.1), verts)


def test_elongated_cloud_pca_only():
    # No normals: PCA alone should align with the long axis of a rotated
    # rectangular cloud (distinct extents -> non-degenerate covariance).
    rng = np.random.default_rng(0)
    cloud = rng.uniform(-1, 1, (500, 3)) * np.array([5, 1, 0.2])
    rot = _rot(0.3, 0.9, -0.5)
    verts = cloud @ rot.T
    box = oriented_bbox(verts)
    # columns are ordered by world-axis affinity, so look for the long
    # direction among all three
    best = max(abs(np.dot(box.axes[:, i], rot[:, 0])) for i in range(3))
    assert best > 0.99


def test_axes_canonical_signs_point_positive():
    rot = _rot(0.1, 0.05, -0.1)  # small tilt: each axis close to a world axis
    verts, n, a = _box_mesh((1, 2, 3), rot)
    box = oriented_bbox(verts, n, a)
    for i in range(3):
        k = int(np.argmax(np.abs(box.axes[:, i])))
        assert box.axes[k, i] > 0


def test_dominant_normals_merges_same_direction_and_orders_by_area():
    normals = [(0, 0, 1), (0, 0, -1), (1, 0, 0), (0, 0, 1.0001)]
    areas = [1, 1, 5, 1]
    doms = dominant_normals(normals, areas)
    assert len(doms) == 2
    assert np.allclose(doms[0], (1, 0, 0))
    assert abs(abs(doms[1][2]) - 1) < 1e-6


def test_pca_axes_orthonormal_right_handed():
    rng = np.random.default_rng(1)
    pts = rng.normal(size=(50, 3)) * np.array([3, 2, 1])
    _assert_orthonormal(pca_axes(pts))


def test_degenerate_cloud_raises():
    with pytest.raises(DegenerateCloud):
        oriented_bbox([(1, 1, 1), (1, 1, 1)])
    with pytest.raises(DegenerateCloud):
        oriented_bbox([(1, 1, 1)])


def test_box_corners_local_matches_blender_bound_box_order():
    c = box_corners_local((0, 0, 0), (1, 2, 3))
    assert c[0] == (0, 0, 0)
    assert c[1] == (0, 0, 3)
    assert c[2] == (0, 2, 3)
    assert c[3] == (0, 2, 0)
    assert c[4] == (1, 0, 0)
    assert c[6] == (1, 2, 3)
