import math
import pytest

from utils.three_point_core import (
    frame_from_points, frame_from_face, align_matrix, axis_frame,
    mat_apply, DegenerateFrame,
)


def _approx_vec(a, b, tol=1e-6):
    return all(abs(x - y) < tol for x, y in zip(a, b))


def _col(m, i):
    return (m[0][i], m[1][i], m[2][i])


# --- frame_from_points ---------------------------------------------------

def test_points_frame_primary_exact_secondary_projected():
    # primary along +X, secondary given off-axis: must be projected to +Y
    f = frame_from_points((0, 0, 0), (2, 0, 0), (1, 3, 0))
    assert _approx_vec(f.origin, (0, 0, 0))
    assert _approx_vec(f.primary, (1, 0, 0))
    assert _approx_vec(f.secondary, (0, 1, 0))
    assert _approx_vec(f.tertiary, (0, 0, 1))


def test_points_frame_is_right_handed_orthonormal():
    f = frame_from_points((1, 2, 3), (4, 0, -1), (-2, 5, 0))
    for v in (f.primary, f.secondary, f.tertiary):
        assert math.isclose(sum(c * c for c in v), 1.0, abs_tol=1e-9)
    assert abs(sum(a * b for a, b in zip(f.primary, f.secondary))) < 1e-9
    assert abs(sum(a * b for a, b in zip(f.primary, f.tertiary))) < 1e-9
    # tertiary = primary x secondary
    p, s = f.primary, f.secondary
    cross = (p[1] * s[2] - p[2] * s[1], p[2] * s[0] - p[0] * s[2], p[0] * s[1] - p[1] * s[0])
    assert _approx_vec(f.tertiary, cross)


def test_points_frame_degenerate_collinear():
    with pytest.raises(DegenerateFrame):
        frame_from_points((0, 0, 0), (1, 0, 0), (2, 0, 0))


def test_points_frame_degenerate_coincident():
    with pytest.raises(DegenerateFrame):
        frame_from_points((0, 0, 0), (0, 0, 0), (0, 1, 0))


def test_points_frame_two_point_picks_stable_secondary():
    # secondary=None → any perpendicular; must still be orthonormal
    f = frame_from_points((0, 0, 0), (0, 0, 5), None)
    assert _approx_vec(f.primary, (0, 0, 1))
    assert abs(sum(a * b for a, b in zip(f.primary, f.secondary))) < 1e-9


def test_points_frame_two_point_uses_hint():
    # hint: keep the secondary as close as possible to +Y
    f = frame_from_points((0, 0, 0), (0, 0, 5), None, secondary_hint=(0.1, 1, 0.3))
    assert _approx_vec(f.secondary, (0.0995037, 0.9950372, 0.0), tol=1e-6)


# --- frame_from_face ------------------------------------------------------

def test_face_frame_normal_is_primary_edge_projected():
    f = frame_from_face((0, 0, 0), (0, 0, 2), (1, 0, 0.5))
    assert _approx_vec(f.primary, (0, 0, 1))
    assert _approx_vec(f.secondary, (1, 0, 0))


# --- align_matrix --------------------------------------------------------

def test_align_identity_when_frames_equal():
    f = frame_from_points((1, 1, 1), (2, 1, 1), (1, 2, 1))
    m = align_matrix(f, f)
    for i in range(4):
        for j in range(4):
            assert math.isclose(m[i][j], 1.0 if i == j else 0.0, abs_tol=1e-9)


def test_align_maps_source_frame_onto_target():
    src = frame_from_points((0, 0, 0), (1, 0, 0), (0, 1, 0))
    dst = frame_from_points((5, 0, 0), (5, 3, 0), (5, 0, 7))   # X->Y, Y->Z
    m = align_matrix(src, dst)
    assert _approx_vec(mat_apply(m, src.origin), dst.origin)
    assert _approx_vec(mat_apply(m, (1, 0, 0)), (5, 1, 0))     # +X -> +Y
    assert _approx_vec(mat_apply(m, (0, 1, 0)), (5, 0, 1))     # +Y -> +Z
    assert _approx_vec(mat_apply(m, (0, 0, 1)), (6, 0, 0))     # +Z -> +X


def test_align_is_rigid():
    src = frame_from_points((0, 0, 0), (1, 0, 0), (0, 1, 0))
    dst = frame_from_points((2, -1, 4), (3, 2, 0), (-1, 1, 1))
    m = align_matrix(src, dst)
    r = [[m[i][j] for j in range(3)] for i in range(3)]
    det = (r[0][0] * (r[1][1] * r[2][2] - r[1][2] * r[2][1])
           - r[0][1] * (r[1][0] * r[2][2] - r[1][2] * r[2][0])
           + r[0][2] * (r[1][0] * r[2][1] - r[1][1] * r[2][0]))
    assert math.isclose(det, 1.0, abs_tol=1e-9)


# --- axis_frame ----------------------------------------------------------

def test_axis_frame_from_object_matrix():
    # object rotated 90deg about Z: local X = world Y, local Y = world -X
    mw = [[0, -1, 0, 3], [1, 0, 0, 4], [0, 0, 1, 5], [0, 0, 0, 1]]
    f = axis_frame(mw, "Z", "Y", pivot=None)
    assert _approx_vec(f.origin, (3, 4, 5))
    assert _approx_vec(f.primary, (0, 0, 1))
    assert _approx_vec(f.secondary, (-1, 0, 0))


def test_axis_frame_negative_axis_and_pivot():
    mw = [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]]
    f = axis_frame(mw, "-Z", "X", pivot=(1, 2, 3))
    assert _approx_vec(f.origin, (1, 2, 3))
    assert _approx_vec(f.primary, (0, 0, -1))
    assert _approx_vec(f.secondary, (1, 0, 0))


def test_axis_frame_ignores_scale():
    mw = [[2, 0, 0, 0], [0, 3, 0, 0], [0, 0, 4, 0], [0, 0, 0, 1]]
    f = axis_frame(mw, "X", "Y", pivot=None)
    assert _approx_vec(f.primary, (1, 0, 0))
    assert _approx_vec(f.secondary, (0, 1, 0))


def test_axis_frame_rejects_same_axis():
    mw = [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]]
    with pytest.raises(DegenerateFrame):
        axis_frame(mw, "Z", "-Z", pivot=None)
