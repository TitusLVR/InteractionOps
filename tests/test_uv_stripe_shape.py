"""The "SHAPE" (True Shape) layout: the faces unfolded across their shared edges, each keeping its real shape, so
a strip that turns in its surface turns in UV; a strip that cannot unfold keeps one row straight and places the
rest by its real offset from it."""
import math

import pytest

from test_uv_stripe_weld import face_quality, signed_area
from uv_stripe_fixtures import DOUBLE_FACES, DOUBLE_VERTS, NGON_FACES, NGON_VERTS, exact_ngon_verts
from utils.uv_stripe_core import Strip, face_stretch, place_fit, strip_extent, strip_v_extent, stripe_uvs
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


# --- the unfold: faces laid out across their shared edges, each keeping its real shape -----------------

def assert_unfolded(strip, uv, tol=1e-3):
    """Every face keeps its real shape (stretch 1, real edge lengths), is not mirrored, and every vertex has one UV."""
    for fid, face in strip.faces.items():
        pts = [uv[(fid, v)] for v in face]
        assert face_stretch([strip.verts[v] for v in face], pts) == pytest.approx(1.0, abs=tol), fid
        assert signed_area(pts) > 0, fid
        for a, b in zip(face, face[1:] + face[:1]):
            assert math.dist(uv[(fid, a)], uv[(fid, b)]) == pytest.approx(math.dist(strip.verts[a], strip.verts[b]),
                                                                           abs=1e-9)
    seen = {}
    for (_fid, v), p in uv.items():
        seen.setdefault(v, []).append(p)
    for v, ps in seen.items():
        assert all(math.dist(p, ps[0]) < 1e-9 for p in ps), v


CHAMFER_VERTS = {0: (0.0, 0.0, 0.0), 1: (0.0, -0.0652, 0.1158), 2: (0.7355, -0.0652, 0.1158),
                 3: (0.7355, 0.0, 0.0), 4: (0.7798, 0.0392, 0.0), 5: (0.7798, -0.0267, 0.1158),
                 6: (0.7798, 0.0392, 0.0831), 7: (0.7798, 0.0122, 0.1158)}
CHAMFER_FACES = {0: (2, 3, 0, 1), 1: (3, 2, 5, 4), 2: (4, 5, 7, 6)}


def test_a_chamfer_round_a_corner_kinks_instead_of_stretching():
    # A rectangle, then a mitred parallelogram going round the corner, then an end quad: the strip turns in its
    # surface, so in UV it kinks on the shared edges and every face keeps its real shape.
    strip = strip_from_faces(CHAMFER_VERTS, CHAMFER_FACES)
    strip.layout = "SHAPE"
    uv = stripe_uvs(strip)
    assert_unfolded(strip, uv)
    for a, b in ((0, 3), (1, 2)):                          # the long rectangle's rows run along u
        assert uv[(0, a)][1] == pytest.approx(uv[(0, b)][1], abs=1e-9)
    near = [uv[(fid, v)] for (fid, v) in uv if v in strip.near]
    far = [uv[(fid, v)] for (fid, v) in uv if v in strip.far]
    assert sum(v for _u, v in near) / len(near) < sum(v for _u, v in far) / len(far)
    assert min(u for u, _v in uv.values()) == pytest.approx(0.0, abs=1e-12)
    assert min(v for _u, v in uv.values()) == pytest.approx(0.0, abs=1e-12)
    assert strip_extent(strip) == pytest.approx(max(u for u, _v in uv.values()))
    assert strip_v_extent(strip) == pytest.approx(max(v for _u, v in uv.values()))


def test_a_flat_straight_strip_maps_one_to_one():
    verts = {i: (0.5 * i, 0.0, 0.0) for i in range(5)} | {10 + i: (0.5 * i, 0.3, 0.0) for i in range(5)}
    faces = {i: (i, i + 1, 11 + i, 10 + i) for i in range(4)}
    strip = strip_from_faces(verts, faces)
    strip.layout = "SHAPE"
    uv = stripe_uvs(strip)
    assert_unfolded(strip, uv)
    for (_fid, v), (u, w) in uv.items():
        assert (u, w) == pytest.approx(verts[v][:2], abs=1e-12)


def test_a_triangle_fan_strip_unfolds():
    # Triangles whose shared edges fan about alternate rails, bent in 3D along a crease and a twist.
    verts = {0: (0.0, 0.0, 0.0), 1: (1.0, 0.0, 0.0), 2: (2.0, 0.0, 0.3), 3: (3.0, 0.2, 0.9),
             10: (0.0, 1.0, 0.0), 11: (1.0, 1.0, 0.1), 12: (2.0, 1.1, 0.5), 13: (3.0, 1.0, 1.4)}
    faces = {0: (0, 1, 10), 1: (1, 11, 10), 2: (1, 2, 11), 3: (2, 12, 11), 4: (2, 3, 12), 5: (3, 13, 12)}
    strip = strip_from_faces(verts, faces)
    strip.layout = "SHAPE"
    assert_unfolded(strip, stripe_uvs(strip))


def test_a_concave_ngon_strip_unfolds():
    # A planar concave hexagon (its far rail dips in), then a quad folded up out of its plane.
    verts = {0: (0.0, 0.0, 0.0), 1: (1.0, 0.0, 0.0), 2: (2.0, 0.0, 0.0), 3: (2.0, 1.0, 0.0), 4: (1.0, 0.4, 0.0),
             5: (0.0, 1.0, 0.0), 6: (3.0, 0.0, 0.7), 7: (3.0, 1.0, 0.7)}
    faces = {0: (0, 1, 2, 3, 4, 5), 1: (2, 6, 7, 3)}
    strip = strip_from_faces(verts, faces)
    strip.layout = "SHAPE"
    assert_unfolded(strip, stripe_uvs(strip))


def curved_grid():
    """A 3 x 2 quad grid over a doubly curved bowl: its inner vertices cannot unfold to one position each."""
    verts, faces = {}, {}
    for y in range(3):
        for x in range(4):
            verts[y * 10 + x] = (float(x), float(y), 0.3 * ((x - 1.5) ** 2 + (y - 1.0) ** 2))
    for y in range(2):
        for x in range(3):
            faces[y * 3 + x] = (y * 10 + x, y * 10 + x + 1, (y + 1) * 10 + x + 1, (y + 1) * 10 + x)
    return verts, faces


def cylinder(n=8):
    verts, faces = {}, {}
    for i in range(n):
        a = 2 * math.pi * i / n
        verts[i] = (math.cos(a), math.sin(a), 0.0)
        verts[n + i] = (math.cos(a), math.sin(a), 1.0)
    for i in range(n):
        faces[i] = (i, (i + 1) % n, n + (i + 1) % n, n + i)
    return verts, faces


@pytest.mark.parametrize("case", ["curved grid", "opened ring"])
def test_a_strip_that_cannot_unfold_keeps_the_projected_layout(case):
    from utils.uv_stripe_core import _shape_uv, _shape_uv_projected, _unfold
    from utils.uv_stripe_select_core import open_ring

    if case == "curved grid":
        strip = strip_from_faces(*curved_grid())
    else:
        strip = open_ring(strip_from_faces(*cylinder()), 0)
    strip.layout = "SHAPE"
    assert _unfold(strip) is None
    assert _shape_uv(strip) == _shape_uv_projected(strip)


def test_a_face_with_a_flipped_normal_unfolds_beside_its_neighbour():
    from utils.uv_stripe_core import _unfold

    verts = {0: (0.0, 0.0, 0.0), 1: (1.0, 0.0, 0.0), 2: (2.0, 0.0, 0.0),
             3: (0.0, 0.0, 1.0), 4: (1.0, 0.0, 1.0), 5: (2.0, 0.0, 1.0)}
    faces = {0: (0, 1, 4, 3), 1: (1, 4, 5, 2)}                 # the second face winds the other way
    pos = _unfold(Strip(verts=verts, faces=faces, near=[0, 1, 2], far=[3, 4, 5], rungs=[(1, 1)], closed=False,
                        height=1.0, sides=([], [])))
    assert pos is not None
    assert math.dist(pos[0], pos[2]) == pytest.approx(2.0)     # side by side, not folded back onto the first
    for face in faces.values():
        assert face_stretch([verts[v] for v in face], [pos[v] for v in face]) == pytest.approx(1.0)
