"""``face_stretch``: a face's UV anisotropy against its real shape, and the stretch tolerance."""
import math

import pytest

from utils.uv_stripe_core import STRETCH_TOLERANCE, face_stretch

QUAD = [(0.0, 0.0, 0.0), (2.0, 0.0, 0.0), (2.0, 0.0, 1.0), (0.0, 0.0, 1.0)]      # 2 x 1, standing in XZ


def _uv(sx=1.0, sy=1.0, shear=0.0):
    return [(x * sx + z * shear, z * sy) for x, _y, z in QUAD]


def test_tolerance():
    assert STRETCH_TOLERANCE == 1.05


def test_true_size_and_uniform_scale_are_not_stretch():
    assert face_stretch(QUAD, _uv()) == pytest.approx(1.0)
    assert face_stretch(QUAD, _uv(0.3, 0.3)) == pytest.approx(1.0)
    turned = [(-v, u) for u, v in _uv()]
    assert face_stretch(QUAD, turned) == pytest.approx(1.0)


def test_one_axis_scale_is_its_ratio():
    assert face_stretch(QUAD, _uv(sx=2.0)) == pytest.approx(2.0)
    assert face_stretch(QUAD, _uv(sy=4.0)) == pytest.approx(4.0)


def test_shear_is_stretch():
    assert face_stretch(QUAD, _uv(shear=0.5)) > STRETCH_TOLERANCE


def test_worst_triangle_of_an_ngon_counts():
    points = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (2.0, 0.0, 0.0), (2.0, 1.0, 0.0), (0.0, 1.0, 0.0)]
    uvs = [(0.0, 0.0), (1.0, 0.0), (2.0, 0.0), (2.0, 1.0), (0.0, 1.0)]
    assert face_stretch(points, uvs) == pytest.approx(1.0)            # the collinear fan triangle is skipped
    uvs[3] = (3.0, 1.0)
    assert face_stretch(points, uvs) > STRETCH_TOLERANCE


def test_degenerate_input():
    doubled = [QUAD[0], QUAD[0], QUAD[2], QUAD[3]]
    assert face_stretch(doubled, [(0.0, 0.0), (0.0, 0.0), (2.0, 1.0), (0.0, 1.0)]) == pytest.approx(1.0)
    assert face_stretch([QUAD[0]] * 4, _uv()) == 1.0
    assert face_stretch(QUAD, [(0.0, 0.0)] * 4) == math.inf
    assert face_stretch(QUAD, [(0.0, 0.0), (2.0, 0.0), (2.0, 0.0), (0.0, 0.0)]) == math.inf


def test_a_sliver_fan_triangle_does_not_decide_alone():
    # An n-gon whose rail corner is bent by 0.1 degree in 3D (rounded or single-precision coordinates) while the
    # layout keeps that rail straight: the sliver triangle is collapsed in UV, the face as a whole is not stretched.
    points = [(0.0, 0.0, 0.0), (1.0, 0.002, 0.0), (2.0, 0.0, 0.0), (2.0, 1.0, 0.0), (0.0, 1.0, 0.0)]
    uvs = [(0.0, 0.0), (1.0, 0.0), (2.0, 0.0), (2.0, 1.0), (0.0, 1.0)]
    assert face_stretch(points, uvs) < STRETCH_TOLERANCE


TRAPEZOID = {0: (0.0, 0.0, 0.0), 1: (0.0, 0.0, 0.125), 2: (0.0, 0.15, 0.125), 3: (0.0, 0.5, 0.0)}   # one slanted end


@pytest.mark.parametrize("faces", [{0: (0, 1, 2, 3)}, {0: (2, 1, 0), 1: (2, 0, 3)}])
@pytest.mark.parametrize("layout", ["TRUE", "SHAPE"])
def test_a_slanted_end_does_not_set_the_height(faces, layout):
    from utils.uv_stripe_core import stripe_uvs
    from utils.uv_stripe_select_core import strip_from_faces

    strip = strip_from_faces(TRAPEZOID, faces)
    assert strip.height == pytest.approx(0.125)       # its real width, not the mean of its two ends' lengths
    strip.layout = layout
    uv = stripe_uvs(strip)
    for fid, face in faces.items():
        assert face_stretch([TRAPEZOID[v] for v in face], [uv[(fid, v)] for v in face]) == pytest.approx(1.0)
