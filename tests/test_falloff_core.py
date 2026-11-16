import math
import numpy as np
import pytest

from utils import falloff_core as fc


# ---------------------------------------------------------------- shapes

def test_shape_names_are_stable():
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


# ---------------------------------------------------------------- fields

def F(**kw):
    """A complete field dict with defaults."""
    d = dict(type="LINEAR", start=(0, 0, 0), end=(1, 0, 0), radii=(1, 1), roll=0.0,
             curve="LINEAR", invert=False, strength=1.0, blend="REPLACE", enabled=True)
    d.update(kw)
    return d


P = np.array([[0, 0, 0], [0.5, 0, 0], [1, 0, 0], [2, 0, 0], [-1, 5, 0]], float)


def test_types_and_blends_are_stable():
    assert fc.FALLOFF_TYPES == ("LINEAR", "RADIAL", "ELLIPTICAL", "BIDIRECTIONAL")
    assert fc.BLEND_MODES == ("REPLACE", "ADD", "SUBTRACT", "MULTIPLY", "MIN", "MAX")
    assert fc.FIT_MODES == ("PCA", "X", "Y", "Z")


def test_linear_zero_at_start_one_at_end():
    assert fc.weight_linear(P, (0, 0, 0), (1, 0, 0)).tolist() == pytest.approx([0, .5, 1, 1, 0])


def test_linear_degenerate_axis_is_full_weight():
    assert fc.weight_linear(P, (1, 1, 1), (1, 1, 1)).tolist() == [1] * 5


def test_bidirectional_peaks_at_midpoint():
    assert fc.weight_bidirectional(P, (0, 0, 0), (1, 0, 0)).tolist() == pytest.approx([0, 1, 0, 0, 0])


def test_weight_radial_center_edge_outside():
    C = np.array([1.0, 1.0, 1.0])
    Q = np.array([[1.0, 1, 1], [3.0, 1, 1], [1.0, 2, 1], [9.0, 9, 9]])
    assert fc.weight_radial(Q, C, 2.0).tolist() == pytest.approx([1.0, 0.0, 0.5, 0.0])


def test_weight_radial_zero_radius_is_safe():
    w = fc.weight_radial(np.array([[0.0, 0, 0], [1.0, 0, 0]]), np.zeros(3), 0.0)
    assert w.tolist() == [1.0, 0.0]


def test_elliptical_axes_are_independent():
    axes, radii = fc.ellipsoid_frame((0, 0, 0), (2, 0, 0), (1, 4), 0.0)
    assert radii.tolist() == pytest.approx([2, 1, 4])
    Q = np.array([[0, 0, 0], [1, 0, 0], [2, 0, 0]], float)
    assert fc.weight_elliptical(Q, (0, 0, 0), axes, radii).tolist() == pytest.approx([1, .5, 0])
    # a point 0.5 along axis 1 (radius 1) and one 2 along axis 2 (radius 4) both weigh 0.5
    R = np.array([axes[:, 1] * 0.5, axes[:, 2] * 2.0])
    assert fc.weight_elliptical(R, (0, 0, 0), axes, radii).tolist() == pytest.approx([.5, .5])


def test_ellipsoid_frame_is_orthonormal_and_roll_turns_perpendicular_axes():
    a0, _ = fc.ellipsoid_frame((0, 0, 0), (0, 0, 3), (1, 2), 0.0)
    a1, r1 = fc.ellipsoid_frame((0, 0, 0), (0, 0, 3), (1, 2), math.pi / 2)
    assert np.allclose(a1.T @ a1, np.eye(3), atol=1e-12)
    assert a1[:, 0].tolist() == pytest.approx([0, 0, 1])
    assert a1[:, 1].tolist() == pytest.approx(a0[:, 2].tolist(), abs=1e-12)
    assert r1.tolist() == pytest.approx([3, 1, 2])


@pytest.mark.parametrize("ftype", fc.FALLOFF_TYPES)
def test_degenerate_field_is_finite(ftype):
    w = fc.field_weight(P, F(type=ftype, start=(1, 1, 1), end=(1, 1, 1), radii=(0, 0)))
    assert np.all(np.isfinite(w)) and w.min() >= 0 and w.max() <= 1


def test_field_weight_applies_curve_then_invert():
    w = fc.field_weight(P, F(curve="SHARP", invert=True))
    assert w.tolist() == pytest.approx([1, .75, 0, 0, 1])


A = F()                                   # weights [0, .5, 1, 1, 0]
B = F(start=(1, 0, 0), end=(0, 0, 0))     # weights [1, .5, 0, 0, 1]


@pytest.mark.parametrize("blend,expected", [
    ("REPLACE", [1, .5, 0, 0, 1]), ("ADD", [1, 1, 1, 1, 1]), ("SUBTRACT", [0, 0, 1, 1, 0]),
    ("MULTIPLY", [0, .25, 0, 0, 0]), ("MIN", [0, .5, 0, 0, 0]), ("MAX", [1, .5, 1, 1, 1])])
def test_stack_blend_modes(blend, expected):
    assert fc.stack_weights(P, [A, dict(B, blend=blend)]).tolist() == pytest.approx(expected)


def test_stack_strength_scales_contribution():
    assert fc.stack_weights(P, [A, dict(B, blend="ADD", strength=0.5)]
                            ).tolist() == pytest.approx([.5, .75, 1, 1, .5])
    assert fc.stack_weights(P, [A, dict(B, blend="MULTIPLY", strength=0.0)]
                            ).tolist() == pytest.approx([0, .5, 1, 1, 0])


def test_stack_first_enabled_field_replaces_regardless_of_blend():
    assert fc.stack_weights(P, [dict(A, blend="SUBTRACT")]).tolist() == pytest.approx([0, .5, 1, 1, 0])


def test_stack_skips_disabled_fields():
    stack = [dict(B, enabled=False), dict(A, blend="SUBTRACT")]
    assert fc.stack_weights(P, stack).tolist() == pytest.approx([0, .5, 1, 1, 0])


def test_stack_empty_or_all_disabled_is_ones():
    assert fc.stack_weights(P, []).tolist() == [1] * 5
    assert fc.stack_weights(P, [dict(A, enabled=False)]).tolist() == [1] * 5


# ---------------------------------------------------------------- fits

def test_fit_pca_follows_long_direction():
    t = np.linspace(-3, 3, 50)
    cloud = np.stack([t, t, 0.01 * np.sin(t)], 1)
    S, E = fc.fit_axis(cloud, "PCA")
    d = (E - S) / np.linalg.norm(E - S)
    assert d.tolist() == pytest.approx([2 ** -.5, 2 ** -.5, 0], abs=1e-2)
    assert np.linalg.norm(E - S) == pytest.approx(6 * 2 ** .5, rel=1e-2)


def test_fit_axis_aligned_uses_bbox_extents():
    box = np.array([[0, 0, 0], [4, 2, 1]], float)
    S, E = fc.fit_axis(box, "Y")
    assert S.tolist() == pytest.approx([2, 0, .5]) and E.tolist() == pytest.approx([2, 2, .5])


def test_fit_pca_single_point_falls_back():
    S, E = fc.fit_axis(np.zeros((1, 3)), "PCA")
    assert np.all(np.isfinite(S)) and np.all(np.isfinite(E))
    assert np.linalg.norm(E - S) >= fc.MIN_SIZE * 0.99


def test_fit_axis_with_no_extent_gets_the_largest_bbox_extent():
    # flat selection, Fit Z: centred on the bbox centre, along Z, as long as
    # the largest extent (4), not a zero-length field
    flat = np.array([[0, 0, 0], [4, 2, 0], [1, 1, 0]], float)
    S, E = fc.fit_axis(flat, "Z")
    assert S.tolist() == pytest.approx([2, 1, -2])
    assert E.tolist() == pytest.approx([2, 1, 2])


def test_fit_axis_with_near_zero_extent_is_also_resized():
    flat = np.array([[0, 0, 0], [4, 2, 1e-7]], float)
    S, E = fc.fit_axis(flat, "Z")
    assert np.linalg.norm(E - S) == pytest.approx(4.0)
    assert (0.5 * (S + E)).tolist() == pytest.approx([2, 1, 0.5e-7])


def test_fit_axis_single_point_length_is_floored_at_min_size():
    S, E = fc.fit_axis(np.array([[1.0, 2.0, 3.0]]), "Y")
    assert np.linalg.norm(E - S) == pytest.approx(fc.MIN_SIZE)
    assert (0.5 * (S + E)).tolist() == pytest.approx([1, 2, 3])


def test_fit_elliptical_on_flat_selection_floors_radii_at_quarter_of_largest():
    t = np.linspace(-2, 2, 9)
    flat = np.array([[x, y, 0.0] for x in t for y in t * 0.5])   # 4 x 2 x 0
    e = fc.fit_field(flat, "ELLIPTICAL", "X")
    primary = np.linalg.norm(np.asarray(e["end"]) - np.asarray(e["start"]))
    assert primary == pytest.approx(2.0)
    assert sorted(e["radii"]) == pytest.approx([0.5, 1.0])     # 0 -> 25 % of 2


def test_fit_elliptical_floors_the_primary_radius_too():
    t = np.linspace(-2, 2, 9)
    flat = np.array([[x, y, 0.0] for x in t for y in t])        # 4 x 4 x 0
    e = fc.fit_field(flat, "ELLIPTICAL", "Z")
    primary = np.linalg.norm(np.asarray(e["end"]) - np.asarray(e["start"]))
    assert primary == pytest.approx(0.5)
    assert sorted(e["radii"]) == pytest.approx([2.0, 2.0])


def test_fit_elliptical_floor_spares_a_thin_but_real_axis():
    # 10 x 1 x 0 strip, Fit X: the 1-wide axis keeps its own radius 0.5; only
    # the zero-extent axis is floored (25 % of 5)
    t = np.linspace(-5, 5, 11)
    strip = np.array([[x, y, 0.0] for x in t for y in (-0.5, 0.0, 0.5)])
    e = fc.fit_field(strip, "ELLIPTICAL", "X")
    primary = np.linalg.norm(np.asarray(e["end"]) - np.asarray(e["start"]))
    assert primary == pytest.approx(5.0)
    assert sorted(e["radii"]) == pytest.approx([0.5, 1.25])


def test_fit_elliptical_no_degenerate_axis_is_not_floored():
    box = np.array([[0, 0, 0], [10, 1, 1]], float)
    e = fc.fit_field(box, "ELLIPTICAL", "X")
    assert sorted(e["radii"]) == pytest.approx([0.5, 0.5])


def test_fit_field_radial_and_elliptical():
    box = np.array([[0, 0, 0], [4, 2, 2]], float)
    r = fc.fit_field(box, "RADIAL", "X")
    assert np.asarray(r["start"]).tolist() == pytest.approx([2, 1, 1])
    assert np.linalg.norm(np.asarray(r["end"]) - np.asarray(r["start"])) == pytest.approx(24 ** .5 / 2)
    e = fc.fit_field(box, "ELLIPTICAL", "X")
    assert np.asarray(e["end"]).tolist() == pytest.approx([4, 1, 1])
    assert sorted(e["radii"]) == pytest.approx([1, 1])
    assert e["roll"] == 0.0


def test_fit_field_linear_matches_fit_axis():
    box = np.array([[0, 0, 0], [4, 2, 1]], float)
    f = fc.fit_field(box, "BIDIRECTIONAL", "X")
    assert np.asarray(f["start"]).tolist() == pytest.approx([0, 1, .5])
    assert np.asarray(f["end"]).tolist() == pytest.approx([4, 1, .5])


def test_normal_offset():
    N = np.array([[0, 0, 1], [0, 0, 1]], float)
    P0 = np.zeros((2, 3))
    assert fc.apply_normal_offset(P0, np.array([1, .5]), N, 2.0)[:, 2].tolist() == pytest.approx([2, 1])


# ---------------------------------------------------------------- bbox

def test_bbox_center():
    Q = np.array([[0.0, 0.0, 0.0], [2.0, 4.0, 6.0]])
    assert fc.bbox_center(Q).tolist() == [1.0, 2.0, 3.0]


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
