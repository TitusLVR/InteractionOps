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


# --- aligning True Shape: what the unfolded piece runs along -------------------------------------------

def bent_flat():
    """A flat strip in the xy plane that turns by 45 degrees in its own surface: near row edges 2 and 1.414, far
    row edges 1.8 and 1.14."""
    verts = {0: (0.0, 0.0, 0.0), 1: (2.0, 0.0, 0.0), 2: (3.0, 1.0, 0.0),
             10: (0.0, 0.5, 0.0), 11: (1.8, 0.5, 0.0), 12: (2.5, 1.4, 0.0)}
    faces = {0: (0, 1, 11, 10), 1: (1, 2, 12, 11)}
    return verts, faces


def shaped(verts, faces, align="AUTO", align_edge=None):
    strip = strip_from_faces(verts, faces)
    strip.layout = "SHAPE"
    strip.align = align
    strip.align_edge = None if align_edge is None else tuple(sorted(align_edge))
    return strip


def row_edges(strip):
    """Every row edge as (length, (a, b)) in row order: near row first, then far row."""
    return [(math.dist(strip.verts[a], strip.verts[b]), (a, b))
            for row in (strip.near, strip.far) for a, b in zip(row, row[1:])]


def uv_of(uv, vid):
    return next(p for (_fid, v), p in uv.items() if v == vid)


def assert_along_u(uv, edge):
    a, b = (uv_of(uv, v) for v in edge)
    assert a[1] == pytest.approx(b[1], abs=1e-9), edge
    assert abs(a[0] - b[0]) > 1e-6, edge


def assert_along_v(uv, edge):
    a, b = (uv_of(uv, v) for v in edge)
    assert a[0] == pytest.approx(b[0], abs=1e-9), edge
    assert abs(a[1] - b[1]) > 1e-6, edge


def assert_near_below_far(strip, uv):
    near = [uv_of(uv, v) for v in strip.near]
    far = [uv_of(uv, v) for v in strip.far]
    assert sum(v for _u, v in near) / len(near) < sum(v for _u, v in far) / len(far)
    assert min(u for u, _v in uv.values()) == pytest.approx(0.0, abs=1e-12)
    assert min(v for _u, v in uv.values()) == pytest.approx(0.0, abs=1e-12)


SHAPES = {"chamfer": (CHAMFER_VERTS, CHAMFER_FACES), "bent": bent_flat()}


@pytest.mark.parametrize("shape", list(SHAPES))
def test_auto_align_is_the_default_layout(shape):
    verts, faces = SHAPES[shape]
    plain = strip_from_faces(verts, faces)
    plain.layout = "SHAPE"
    assert plain.align == "AUTO" and plain.align_edge is None
    assert stripe_uvs(shaped(verts, faces, "AUTO")) == stripe_uvs(plain)


@pytest.mark.parametrize("shape", list(SHAPES))
@pytest.mark.parametrize("align", ["LONGEST", "SHORTEST"])
def test_longest_and_shortest_put_that_row_edge_along_u(shape, align):
    verts, faces = SHAPES[shape]
    strip = shaped(verts, faces, align)
    edges = row_edges(strip)
    pick = max if align == "LONGEST" else min
    best = pick(length for length, _e in edges)
    edge = next(e for length, e in edges if length == best)      # the first one on a tie, near row before far
    uv = stripe_uvs(strip)
    assert_unfolded(strip, uv)
    assert_along_u(uv, edge)
    assert_near_below_far(strip, uv)
    assert strip_extent(strip) == pytest.approx(max(u for u, _v in uv.values()))
    assert strip_v_extent(strip) == pytest.approx(max(v for _u, v in uv.values()))


def test_the_chamfer_aligns_to_its_known_edges():
    longest = stripe_uvs(shaped(CHAMFER_VERTS, CHAMFER_FACES, "LONGEST"))
    assert_along_u(longest, (1, 2))                               # ties with (0, 3): the near row's comes first
    shortest = stripe_uvs(shaped(CHAMFER_VERTS, CHAMFER_FACES, "SHORTEST"))
    assert_along_u(shortest, (5, 7))
    assert uv_of(shortest, 1)[1] != pytest.approx(uv_of(shortest, 2)[1], abs=1e-6)


def test_the_bent_strip_aligns_its_shortest_edge_on_the_far_row():
    strip = shaped(*bent_flat(), "SHORTEST")
    assert {11, 12} <= set(strip.far)
    uv = stripe_uvs(strip)
    assert_along_u(uv, (11, 12))
    assert_unfolded(strip, uv)


@pytest.mark.parametrize("shape", list(SHAPES))
def test_a_picked_row_edge_runs_along_u_and_a_picked_cross_edge_along_v(shape):
    verts, faces = SHAPES[shape]
    probe = strip_from_faces(verts, faces)
    row_edge = (probe.far[-2], probe.far[-1])
    ni, fi = probe.rungs[0] if probe.rungs else (1, 1)
    cross = (probe.near[ni], probe.far[fi])
    end_side = (probe.near[-1], probe.far[-1])
    strip = shaped(verts, faces, "PICKED", row_edge)
    uv = stripe_uvs(strip)
    assert_unfolded(strip, uv)
    assert_along_u(uv, row_edge)
    assert_near_below_far(strip, uv)
    for edge in (cross, end_side):
        strip = shaped(verts, faces, "PICKED", edge)
        uv = stripe_uvs(strip)
        assert_unfolded(strip, uv)
        assert_along_v(uv, edge)
        assert_near_below_far(strip, uv)


@pytest.mark.parametrize("shape", list(SHAPES))
def test_a_picked_edge_outside_the_piece_lays_out_as_auto(shape):
    verts, faces = SHAPES[shape]
    auto = stripe_uvs(shaped(verts, faces, "AUTO"))
    assert stripe_uvs(shaped(verts, faces, "PICKED", (900, 901))) == auto
    assert stripe_uvs(shaped(verts, faces, "PICKED", None)) == auto


def test_align_is_ignored_by_the_other_layouts():
    verts, faces = bent_flat()
    for layout in ("EVEN", "TRUE", "STRAIGHT"):
        plain = strip_from_faces(verts, faces)
        plain.layout = layout
        strip = shaped(verts, faces, "SHORTEST")
        strip.layout = layout
        assert stripe_uvs(strip) == stripe_uvs(plain)


def test_split_pieces_align_on_their_own_edges():
    from utils.uv_stripe_core import align_edge_in

    verts, faces = bent_flat()
    strip = shaped(verts, faces, "LONGEST")
    pieces, reason = split_strip(strip, None, [0])
    assert reason is None and len(pieces) == 2
    for piece in pieces:
        assert piece.align == "LONGEST" and piece.layout == "SHAPE"
        edges = row_edges(piece)
        best = max(length for length, _e in edges)
        uv = stripe_uvs(piece)
        assert_along_u(uv, next(e for length, e in edges if length == best))
        assert_unfolded(piece, uv)
        assert_near_below_far(piece, uv)
    # picked edges: each piece takes the first stored edge that lies in it, the others stay automatic
    stored = [(2, 12), (10, 11), (0, 10)]
    strip = shaped(verts, faces, "PICKED")
    pieces, _reason = split_strip(strip, None, [0])
    chosen = [align_edge_in(piece, stored) for piece in pieces]
    assert chosen == [(10, 11), (2, 12)]
    for piece, edge in zip(pieces, chosen):
        piece.align_edge = edge
    assert_along_u(stripe_uvs(pieces[0]), (10, 11))
    assert_along_v(stripe_uvs(pieces[1]), (2, 12))
    assert align_edge_in(pieces[0], [(2, 12)]) is None
