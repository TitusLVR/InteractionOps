"""The "SHAPE" (True Shape) layout: one row straight at its true length, everything else at its real offset from
it, so the real width is followed and a flat strip with one straight rail maps one to one."""
import math

import pytest

from test_uv_stripe_weld import face_quality, signed_area
from uv_stripe_fixtures import DOUBLE_FACES, DOUBLE_VERTS, NGON_FACES, NGON_VERTS, exact_ngon_verts
from utils.uv_stripe_core import Strip, place_fit, strip_extent, strip_v_extent, stripe_uvs
from utils.uv_stripe_select_core import split_strip, strip_from_faces


@pytest.mark.parametrize("data", ["double", "ngon", "exact ngon"])
@pytest.mark.parametrize("angle", [15.0, 5.0])
def test_user_strips_map_one_to_one(data, angle):
    # Every edge longer than the doubles keeps its 3D length (to the coordinates' 1e-4 rounding) and every corner
    # its angle, also where the width tapers.
    verts, faces = {"double": (DOUBLE_VERTS, DOUBLE_FACES), "ngon": (NGON_VERTS, NGON_FACES),
                    "exact ngon": (exact_ngon_verts(), NGON_FACES)}[data]
    strip = strip_from_faces(verts, faces)
    strip.layout = "SHAPE"
    pieces, reason = split_strip(strip, math.radians(angle))
    assert reason is None and len(pieces) == 3
    for piece in pieces:
        uv = stripe_uvs(piece)
        for fid in piece.faces:
            ratios, errors = face_quality(piece, uv, fid)
            assert all(abs(r - 1.0) < 1e-3 for r in ratios), (fid, ratios)
            assert max(errors) < 0.1, (fid, errors)
            assert signed_area([uv[(fid, v)] for v in piece.faces[fid]]) > 0


def tapering():
    """A 3 x 1 strip along x whose far rail closes in from width 1 to 0.7, with a kink-free straight near rail."""
    verts = {i: (float(i), 0.0, 0.0) for i in range(4)} | {10 + i: (float(i), 1.0 - 0.1 * i, 0.0) for i in range(4)}
    faces = {i: (i, i + 1, 11 + i, 10 + i) for i in range(3)}
    return verts, faces


def test_a_tapering_strip_is_exact_and_its_near_row_straight():
    verts, faces = tapering()
    strip = strip_from_faces(verts, faces)
    strip.layout = "SHAPE"
    uv = stripe_uvs(strip)
    for fid in faces:
        ratios, errors = face_quality(strip, uv, fid)
        assert all(abs(r - 1.0) < 1e-9 for r in ratios) and max(errors) < 1e-7, (fid, ratios, errors)
    near = [uv[(fid, v)] for (fid, v) in uv if v in strip.near]
    assert all(abs(v) < 1e-12 for _u, v in near)
    assert strip_v_extent(strip) == pytest.approx(1.0) and strip_extent(strip) == pytest.approx(3.0)
    strip.layout = "TRUE"
    ratios, _errors = face_quality(strip, stripe_uvs(strip), 2)
    assert max(abs(r - 1.0) for r in ratios) > 0.01           # one height cannot follow the taper


def test_the_straighter_row_is_the_straight_one():
    # The near rail kinks by 4 degrees, the far rail is straight: the far row is kept straight (on top) instead.
    verts = {0: (0.0, 0.0, 0.0), 1: (1.0, 0.0, 0.0), 2: (2.0, math.tan(math.radians(4.0)), 0.0),
             10: (0.0, 1.0, 0.0), 11: (1.0, 1.0, 0.0), 12: (2.0, 1.0, 0.0)}
    s = Strip(verts=verts, faces={0: (0, 1, 11, 10), 1: (1, 2, 12, 11)}, near=[0, 1, 2], far=[10, 11, 12],
              rungs=[(1, 1)], closed=False, height=1.0, layout="SHAPE")
    uv = stripe_uvs(s)
    far_v = {round(uv[key][1], 12) for key in uv if key[1] in s.far}
    assert len(far_v) == 1 and far_v.pop() == pytest.approx(strip_v_extent(s))
    for fid in s.faces:
        ratios, errors = face_quality(s, uv, fid)
        assert all(abs(r - 1.0) < 1e-9 for r in ratios) and max(errors) < 1e-7


def test_true_shape_flips_mirrored_faces_back():
    verts, faces = tapering()
    strip = strip_from_faces(verts, faces)
    strip.layout = "SHAPE"
    strip.faces = {fid: face[::-1] for fid, face in strip.faces.items()}
    uv = stripe_uvs(strip)
    for fid, face in strip.faces.items():
        assert signed_area([uv[(fid, v)] for v in face]) > 0
        ratios, _errors = face_quality(strip, uv, fid)
        assert all(abs(r - 1.0) < 1e-9 for r in ratios)


def test_fit_of_true_shape_pieces_uses_their_real_extents():
    verts, faces = tapering()
    a = strip_from_faces(verts, faces)
    a.layout = "SHAPE"
    b = strip_from_faces({k: (2 * x, 2 * y, z) for k, (x, y, z) in verts.items()}, faces)
    b.layout = "SHAPE"
    maps = [stripe_uvs(a), stripe_uvs(b)]
    heights = [strip_v_extent(a), strip_v_extent(b)]
    lengths = [strip_extent(a), strip_extent(b)]
    assert heights == pytest.approx([1.0, 2.0]) and lengths == pytest.approx([3.0, 6.0])
    out = place_fit(maps, heights, lengths, groups=[0, 0])
    assert max(v for _u, v in out[0].values()) == pytest.approx(1.0 / 6.0)
    assert min(v for _u, v in out[1].values()) == pytest.approx(1.0 / 6.0 + 0.01)
    assert max(u for u, _v in out[1].values()) == pytest.approx(1.0)
