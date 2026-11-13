import math

import pytest

from utils.depth_bias import (
    DEPTH_SHRINK,
    biased_projection,
    clamp_factor,
    is_perspective,
    occlusion_passes,
    scale_alpha,
)


def perspective(fov_y=math.radians(50.0), aspect=1.5, near=0.01, far=1000.0, shift_x=0.0):
    f = 1.0 / math.tan(fov_y / 2.0)
    return [
        [f / aspect, 0.0, shift_x, 0.0],
        [0.0, f, 0.0, 0.0],
        [0.0, 0.0, (far + near) / (near - far), 2.0 * far * near / (near - far)],
        [0.0, 0.0, -1.0, 0.0],
    ]


def orthographic(width=10.0, height=6.0, near=-500.0, far=500.0, shift_x=0.0):
    return [
        [2.0 / width, 0.0, 0.0, shift_x],
        [0.0, 2.0 / height, 0.0, 0.0],
        [0.0, 0.0, -2.0 / (far - near), -(far + near) / (far - near)],
        [0.0, 0.0, 0.0, 1.0],
    ]


def ndc(matrix, point):
    x, y, z = point
    clip = [row[0] * x + row[1] * y + row[2] * z + row[3] for row in matrix]
    return tuple(c / clip[3] for c in clip[:3])


VIEW_POINTS = [(0.3, -0.2, -1.0), (2.0, 1.0, -10.0), (-40.0, 25.0, -250.0), (0.0, 0.0, -0.05)]


# --- passes and colours -------------------------------------------------------------------------------------------

def test_factor_one_is_a_single_pass_without_depth_test():
    assert occlusion_passes(1.0) == [("ALWAYS", 1.0)]
    assert occlusion_passes(3.0) == [("ALWAYS", 1.0)]


def test_factor_zero_draws_only_what_is_in_front():
    assert occlusion_passes(0.0) == [("LESS_EQUAL", 1.0)]
    assert occlusion_passes(-1.0) == [("LESS_EQUAL", 1.0)]


def test_factor_between_draws_the_hidden_part_dimmed_after_the_visible_part():
    assert occlusion_passes(0.25) == [("LESS_EQUAL", 1.0), ("GREATER", 0.25)]


def test_the_two_depth_tests_split_every_fragment_between_them():
    tests = {"LESS_EQUAL": lambda a, b: a <= b, "GREATER": lambda a, b: a > b}
    passes = occlusion_passes(0.5)
    for fragment in (0.1, 0.5, 0.9):
        for stored in (0.1, 0.5, 0.9):
            assert sum(tests[depth](fragment, stored) for depth, _f in passes) == 1


def test_scale_alpha_multiplies_only_the_alpha():
    assert scale_alpha((0.2, 0.4, 0.6, 0.8), 0.25) == pytest.approx((0.2, 0.4, 0.6, 0.2))
    assert scale_alpha((0.2, 0.4, 0.6, 0.8), 1.0) == (0.2, 0.4, 0.6, 0.8)
    assert scale_alpha((0.2, 0.4, 0.6), 0.5) == (0.2, 0.4, 0.6, 0.5)      # RGB: alpha 1
    assert scale_alpha((1.0, 1.0, 1.0, 1.0), 7.0)[3] == 1.0                # clamped
    assert scale_alpha((1.0, 1.0, 1.0, 1.0), -1.0)[3] == 0.0


def test_unreadable_factor_draws_as_in_front():
    assert clamp_factor(None) == 1.0
    assert clamp_factor(float("nan")) == 1.0
    assert clamp_factor("0.5") == 0.5


def test_factor_one_path_matches_one_plain_draw():
    color = (0.302, 0.816, 1.0, 0.9)
    passes = occlusion_passes(1.0)
    assert [(depth, scale_alpha(color, f)) for depth, f in passes] == [("ALWAYS", color)]


# --- bias ---------------------------------------------------------------------------------------------------------

def test_matrices_are_told_apart():
    assert is_perspective(perspective())
    assert not is_perspective(orthographic())


def test_perspective_bias_is_the_point_pulled_toward_the_eye():
    m = perspective()
    biased = biased_projection(m)
    for p in VIEW_POINTS:
        pulled = tuple(c * (1.0 - DEPTH_SHRINK) for c in p)
        assert ndc(biased, p) == pytest.approx(ndc(m, pulled), rel=1e-9, abs=1e-12)


@pytest.mark.parametrize("matrix", [perspective(), perspective(shift_x=0.3), orthographic(),
                                    orthographic(shift_x=0.2)])
def test_bias_leaves_the_screen_position_alone_and_moves_depth_toward_the_viewer(matrix):
    biased = biased_projection(matrix)
    for p in VIEW_POINTS:
        x0, y0, z0 = ndc(matrix, p)
        x1, y1, z1 = ndc(biased, p)
        assert (x1, y1) == pytest.approx((x0, y0), abs=1e-12)
        assert z1 < z0
    assert [row for i, row in enumerate(biased) if i != 2] == [row for i, row in enumerate(matrix) if i != 2]
    assert biased[2][:3] == matrix[2][:3]


def test_perspective_bias_is_a_fixed_fraction_of_the_distance():
    """What the bias lets through (geometry less than this far behind still counts as in front) grows with the
    distance, so it is the same size on screen at any zoom."""
    m = perspective()
    biased = biased_projection(m)
    for distance in (0.5, 5.0, 50.0, 500.0):
        z_biased = ndc(biased, (0.0, 0.0, -distance))[2]
        # the view depth whose unbiased NDC equals the biased one
        lo, hi = 0.0, distance
        for _ in range(200):
            mid = (lo + hi) / 2.0
            if ndc(m, (0.0, 0.0, -mid))[2] < z_biased:
                lo = mid
            else:
                hi = mid
        assert (distance - lo) / distance == pytest.approx(DEPTH_SHRINK, rel=1e-6)


def test_orthographic_bias_is_a_fraction_of_the_visible_width():
    m = orthographic(width=10.0)
    biased = biased_projection(m)
    offset_ndc = ndc(m, (0.0, 0.0, -3.0))[2] - ndc(biased, (0.0, 0.0, -3.0))[2]
    # NDC depth per view unit is 2 / (far - near) = 2 / 1000
    assert offset_ndc / (2.0 / 1000.0) == pytest.approx(DEPTH_SHRINK * 10.0)
    zoomed = biased_projection(orthographic(width=1.0))
    offset_zoomed = ndc(orthographic(width=1.0), (0.0, 0.0, -3.0))[2] - ndc(zoomed, (0.0, 0.0, -3.0))[2]
    assert offset_zoomed == pytest.approx(offset_ndc / 10.0)


def test_a_line_on_a_face_is_in_front_of_it_and_one_behind_it_is_not():
    """Depth-buffer view: the face's stored depth is its unbiased NDC; a line on the face passes LESS_EQUAL, a line
    a mesh's thickness behind it (well over the bias) passes GREATER, in both projections."""
    for m, behind in ((perspective(), 0.2), (orthographic(), 0.2)):
        biased = biased_projection(m)
        face = (0.5, 0.25, -4.0)
        stored = (ndc(m, face)[2] + 1.0) / 2.0
        on_face = (ndc(biased, face)[2] + 1.0) / 2.0
        back = (ndc(biased, (0.5, 0.25, -4.0 - behind))[2] + 1.0) / 2.0
        assert on_face <= stored
        assert back > stored


def test_zero_shrink_changes_nothing_and_the_input_is_not_modified():
    m = perspective()
    copy = [row[:] for row in m]
    assert biased_projection(m, 0.0) == m
    biased_projection(m)
    assert m == copy
