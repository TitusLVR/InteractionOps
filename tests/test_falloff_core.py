import math
import numpy as np
import pytest

from utils import falloff_core as fc


# ---------------------------------------------------------------- shapes

def test_shape_names_are_stable():
    assert fc.FALLOFF_TYPES == ("LINEAR", "RADIAL", "SCREEN", "COPLANAR")
    assert fc.SHAPES == ("LINEAR", "SMOOTH", "SHARP", "ROOT", "SPHERE",
                         "INVERSE_SQUARE", "CONSTANT")


@pytest.mark.parametrize("name", fc.SHAPES)
def test_shape_endpoints(name):
    x = np.array([0.0, 1.0])
    y = fc.shape_curve(name, x)
    if name == "CONSTANT":
        assert y.tolist() == [1.0, 1.0]
    else:
        assert y[0] == pytest.approx(0.0)
        assert y[1] == pytest.approx(1.0)


@pytest.mark.parametrize("name", [s for s in fc.SHAPES if s != "CONSTANT"])
def test_shape_monotonic_and_clamped(name):
    x = np.linspace(-0.5, 1.5, 41)
    y = fc.shape_curve(name, x)
    assert np.all(np.diff(y) >= -1e-12)
    assert y.min() >= 0.0 and y.max() <= 1.0 + 1e-12


def test_shape_midpoints_match_blender_formulas():
    x = np.array([0.5])
    assert fc.shape_curve("LINEAR", x)[0] == pytest.approx(0.5)
    assert fc.shape_curve("SMOOTH", x)[0] == pytest.approx(0.5)          # 3x²-2x³
    assert fc.shape_curve("SHARP", x)[0] == pytest.approx(0.25)          # x²
    assert fc.shape_curve("ROOT", x)[0] == pytest.approx(math.sqrt(0.5))
    assert fc.shape_curve("SPHERE", x)[0] == pytest.approx(math.sqrt(0.75))  # sqrt(2x-x²)
    assert fc.shape_curve("INVERSE_SQUARE", x)[0] == pytest.approx(0.75) # x(2-x)


def test_shape_unknown_name_raises():
    with pytest.raises(KeyError):
        fc.shape_curve("BOGUS", np.array([0.5]))


def test_apply_invert():
    w = np.array([0.0, 0.25, 1.0])
    assert fc.apply_invert(w).tolist() == [1.0, 0.75, 0.0]


# ---------------------------------------------------------------- linear

def test_weight_linear_start_end_mid_beyond():
    S = np.array([0.0, 0.0, 0.0])
    E = np.array([2.0, 0.0, 0.0])
    P = np.array([[0.0, 0, 0], [2.0, 0, 0], [1.0, 5, 5], [-1.0, 0, 0], [3.0, 0, 0]])
    w = fc.weight_linear(P, S, E)
    assert w.tolist() == pytest.approx([1.0, 0.0, 0.5, 1.0, 0.0])


def test_weight_linear_degenerate_axis_is_full_weight():
    S = np.zeros(3)
    P = np.array([[1.0, 2.0, 3.0]])
    w = fc.weight_linear(P, S, S)
    assert w.tolist() == [1.0]


# ---------------------------------------------------------------- radial

def test_weight_radial_center_edge_outside():
    C = np.array([1.0, 1.0, 1.0])
    P = np.array([[1.0, 1, 1], [3.0, 1, 1], [1.0, 2, 1], [9.0, 9, 9]])
    w = fc.weight_radial(P, C, 2.0)
    assert w.tolist() == pytest.approx([1.0, 0.0, 0.5, 0.0])


def test_weight_radial_zero_radius_is_safe():
    w = fc.weight_radial(np.array([[0.0, 0, 0], [1.0, 0, 0]]), np.zeros(3), 0.0)
    assert w.tolist() == [1.0, 0.0]


# ---------------------------------------------------------------- screen

def test_weight_screen_center_edge_and_invalid_rows():
    P2 = np.array([[100.0, 100.0], [150.0, 100.0], [125.0, 100.0], [100.0, 100.0]])
    valid = np.array([True, True, True, False])
    w = fc.weight_screen(P2, np.array([100.0, 100.0]), 50.0, valid)
    assert w.tolist() == pytest.approx([1.0, 0.0, 0.5, 0.0])


def test_project_points_identity_matrix_maps_ndc_to_pixels():
    # identity "perspective": clip == world, so (0,0) → region centre,
    # (1,1) → top-right corner, w<=0 rows are invalid
    Pw = np.array([[0.0, 0.0, 0.0], [1.0, 1.0, 0.0]])
    P2, valid = fc.project_points(Pw, np.eye(4), 200, 100)
    assert P2[0].tolist() == pytest.approx([100.0, 50.0])
    assert P2[1].tolist() == pytest.approx([200.0, 100.0])
    assert valid.tolist() == [True, True]


def test_project_points_behind_camera_invalid():
    M = np.eye(4)
    M[3, 3] = 0.0
    M[3, 2] = 1.0            # w = z
    Pw = np.array([[0.0, 0.0, 2.0], [0.0, 0.0, -2.0]])
    P2, valid = fc.project_points(Pw, M, 200, 100)
    assert valid.tolist() == [True, False]
    assert np.isfinite(P2[0]).all()


# ---------------------------------------------------------------- coplanar

def test_weight_coplanar_faces_angle_ramp():
    n_ref = np.array([0.0, 0.0, 1.0])
    a = math.radians(10.0)
    FN = np.array([
        [0.0, 0.0, 1.0],                                  # 0° → 1
        [math.sin(a / 2), 0.0, math.cos(a / 2)],          # 5° → 0.5
        [math.sin(a), 0.0, math.cos(a)],                  # 10° → 0
        [1.0, 0.0, 0.0],                                  # 90° → 0
    ])
    w = fc.weight_coplanar_faces(FN, n_ref, a)
    assert w.tolist() == pytest.approx([1.0, 0.5, 0.0, 0.0], abs=1e-6)


def test_weight_coplanar_zero_angle_only_exact_matches():
    FN = np.array([[0.0, 0.0, 1.0], [0.001, 0.0, 0.999999]])
    w = fc.weight_coplanar_faces(FN, np.array([0.0, 0.0, 1.0]), 0.0)
    assert w[0] == pytest.approx(1.0)
    assert w[1] == pytest.approx(0.0)


def test_vertex_weights_from_faces_takes_max():
    face_rows = [[0, 1, 2], [2, 3]]
    wf = np.array([0.2, 0.9])
    w = fc.vertex_weights_from_faces(face_rows, wf, 5)
    assert w.tolist() == pytest.approx([0.2, 0.2, 0.9, 0.9, 0.0])


# ---------------------------------------------------------------- connectivity

def test_connected_mask_two_islands():
    # island A: 0-1-2, island B: 3-4
    adj = [[1], [0, 2], [1], [4], [3]]
    m = fc.connected_mask(adj, [0], 5)
    assert m.tolist() == [True, True, True, False, False]


def test_connected_mask_multiple_seeds():
    adj = [[1], [0], [3], [2], []]
    m = fc.connected_mask(adj, [0, 2], 5)
    assert m.tolist() == [True, True, True, True, False]


def test_coplanar_grow_stops_at_hard_edge():
    # faces in a strip 0-1-2-3; face 2 is tilted (wf=0) so 3 is unreachable
    face_adj = [[1], [0, 2], [1, 3], [2]]
    wf = np.array([1.0, 0.7, 0.0, 1.0])
    keep = fc.coplanar_grow(face_adj, wf, [0])
    assert keep.tolist() == [True, True, False, False]


def test_coplanar_grow_seed_kept_even_if_zero_weight():
    keep = fc.coplanar_grow([[1], [0]], np.array([0.0, 1.0]), [0])
    assert keep.tolist() == [True, True]


# ---------------------------------------------------------------- autofit

def test_bbox_center():
    P = np.array([[0.0, 0.0, 0.0], [2.0, 4.0, 6.0]])
    assert fc.bbox_center(P).tolist() == [1.0, 2.0, 3.0]


def test_autofit_linear_longest_axis():
    P = np.array([[0.0, 0.0, 0.0], [1.0, 5.0, 2.0]])
    S, E = fc.autofit_linear(P)
    assert S.tolist() == pytest.approx([0.5, 0.0, 1.0])
    assert E.tolist() == pytest.approx([0.5, 5.0, 1.0])


def test_autofit_linear_degenerate_gets_unit_x():
    P = np.array([[1.0, 1.0, 1.0]])
    S, E = fc.autofit_linear(P)
    assert S.tolist() == [1.0, 1.0, 1.0]
    assert E.tolist() == [2.0, 1.0, 1.0]


def test_autofit_radial():
    P = np.array([[0.0, 0.0, 0.0], [2.0, 0.0, 0.0]])
    C, r = fc.autofit_radial(P)
    assert C.tolist() == [1.0, 0.0, 0.0]
    assert r == pytest.approx(1.0)
    C, r = fc.autofit_radial(np.array([[3.0, 3.0, 3.0]]))
    assert r == pytest.approx(1e-4)


# ---------------------------------------------------------------- apply

P0 = np.array([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [2.0, 2.0, 2.0]])


def test_apply_move_weighted():
    W = np.array([1.0, 0.5, 0.0])
    P = fc.apply_move(P0, W, np.array([2.0, 0.0, 0.0]))
    assert P == pytest.approx(np.array([[3.0, 0, 0], [1.0, 1, 0], [2.0, 2, 2]]))


def test_apply_rotate_full_weight_is_rigid():
    W = np.ones(3)
    P = fc.apply_rotate(P0, W, np.zeros(3), np.array([0.0, 0.0, 1.0]), math.pi / 2)
    assert P[0].tolist() == pytest.approx([0.0, 1.0, 0.0], abs=1e-9)
    assert P[1].tolist() == pytest.approx([-1.0, 0.0, 0.0], abs=1e-9)
    assert P[2].tolist() == pytest.approx([-2.0, 2.0, 2.0], abs=1e-9)


def test_apply_rotate_half_weight_is_half_angle():
    W = np.array([0.5, 0.0, 0.0])
    P = fc.apply_rotate(P0, W, np.zeros(3), np.array([0.0, 0.0, 1.0]), math.pi / 2)
    s = math.sqrt(0.5)
    assert P[0].tolist() == pytest.approx([s, s, 0.0], abs=1e-9)
    assert P[1].tolist() == pytest.approx(P0[1].tolist())


def test_apply_rotate_about_offset_pivot_and_unnormalised_axis():
    W = np.ones(1)
    P = fc.apply_rotate(np.array([[2.0, 0.0, 0.0]]), W, np.array([1.0, 0.0, 0.0]),
                        np.array([0.0, 0.0, 5.0]), math.pi)
    assert P[0].tolist() == pytest.approx([0.0, 0.0, 0.0], abs=1e-9)


def test_apply_rotate_zero_axis_is_identity():
    P = fc.apply_rotate(P0, np.ones(3), np.zeros(3), np.zeros(3), 1.0)
    assert P.tolist() == P0.tolist()


def test_apply_scale_uniform_weighted():
    W = np.array([1.0, 0.5, 0.0])
    P = fc.apply_scale(P0, W, np.zeros(3), 3.0)
    assert P == pytest.approx(np.array([[3.0, 0, 0], [0.0, 2.0, 0], [2.0, 2, 2]]))


def test_apply_scale_per_axis_about_pivot():
    W = np.ones(1)
    P = fc.apply_scale(np.array([[2.0, 2.0, 2.0]]), W, np.array([1.0, 1.0, 1.0]),
                       np.array([2.0, 1.0, 0.0]))
    assert P[0].tolist() == pytest.approx([3.0, 2.0, 1.0])


def test_apply_functions_do_not_mutate_input():
    P0c = P0.copy()
    fc.apply_move(P0, np.ones(3), np.ones(3))
    fc.apply_rotate(P0, np.ones(3), np.zeros(3), np.array([0.0, 0.0, 1.0]), 1.0)
    fc.apply_scale(P0, np.ones(3), np.zeros(3), 2.0)
    assert P0.tolist() == P0c.tolist()


# ---------------------------------------------------------------- basis

def test_apply_scale_with_rotated_basis_scales_along_basis_axis():
    # basis X = object +Y: scaling basis-X by 3 must scale the object Y coordinate
    R = np.array([[0.0, -1.0, 0.0],
                  [1.0, 0.0, 0.0],
                  [0.0, 0.0, 1.0]])           # columns: X=(0,1,0), Y=(-1,0,0), Z=(0,0,1)
    P = fc.apply_scale(np.array([[1.0, 2.0, 5.0]]), np.ones(1), np.zeros(3),
                       np.array([3.0, 1.0, 1.0]), basis=R)
    assert P[0].tolist() == pytest.approx([1.0, 6.0, 5.0])


def test_apply_scale_identity_basis_matches_no_basis():
    a = fc.apply_scale(P0, np.array([1.0, 0.5, 0.0]), np.ones(3), np.array([2.0, 0.5, 1.0]))
    b = fc.apply_scale(P0, np.array([1.0, 0.5, 0.0]), np.ones(3), np.array([2.0, 0.5, 1.0]),
                       basis=np.eye(3))
    assert np.allclose(a, b)


def test_basis_from_normal_is_orthonormal_with_z_along_normal():
    R = fc.basis_from_normal([0.0, 3.0, 4.0], tangent=[1.0, 0.0, 0.0])
    assert np.allclose(R.T @ R, np.eye(3), atol=1e-12)
    assert R[:, 2].tolist() == pytest.approx([0.0, 0.6, 0.8])
    assert R[:, 0].tolist() == pytest.approx([1.0, 0.0, 0.0])
    assert np.cross(R[:, 0], R[:, 1]).tolist() == pytest.approx(R[:, 2].tolist())


def test_basis_from_normal_parallel_tangent_and_zero_normal():
    R = fc.basis_from_normal([0.0, 0.0, 1.0], tangent=[0.0, 0.0, 5.0])
    assert np.allclose(R.T @ R, np.eye(3), atol=1e-12)
    assert R[:, 2].tolist() == pytest.approx([0.0, 0.0, 1.0])
    assert fc.basis_from_normal([0.0, 0.0, 0.0]).tolist() == np.eye(3).tolist()
