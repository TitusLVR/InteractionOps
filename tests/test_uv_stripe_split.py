"""Tearing built strips by slicing their rows (``slice_strip`` / ``split_strip``), n-gon end caps, the
"TRUE" (no stretch) row layout and vertical placement."""
import math

import pytest

from utils.uv_stripe_core import (
    Strip, bbox, fit_to_reference, place_fit, place_in_place, random_offsets, shifted, straighten, strip_extent,
    strip_length, stripe_uvs,
)
from utils.uv_stripe_select_core import (
    bend_cut_rungs, open_ring, rung_edge, rungs_at, slice_strip, split_strip, strip_from_faces,
)

from uv_stripe_fixtures import (  # noqa: E402
    NGON_FACES, NGON_VERTS, exact_ngon_verts, flat_annulus, flat_annulus_with_triangle,
)


def corners_uv(strip, uv):
    return {fid: [uv[(fid, v)] for v in face] for fid, face in strip.faces.items()}


def edge_ratios(strip, uv):
    """UV length over 3D length of every edge of every face, per face corner order."""
    out = []
    for fid, face in strip.faces.items():
        for k, a in enumerate(face):
            b = face[(k + 1) % len(face)]
            d3 = math.dist(strip.verts[a], strip.verts[b])
            if d3 > 1e-9:
                out.append(math.dist(uv[(fid, a)], uv[(fid, b)]) / d3)
    return out


def corner_angle_errors(strip, uv):
    """|UV corner angle - 3D corner angle| in degrees over every face corner."""
    out = []
    for fid, face in strip.faces.items():
        n = len(face)
        for k, v in enumerate(face):
            p, q = face[k - 1], face[(k + 1) % n]
            a3 = _angle(strip.verts[p], strip.verts[v], strip.verts[q])
            a2 = _angle((*uv[(fid, p)], 0.0), (*uv[(fid, v)], 0.0), (*uv[(fid, q)], 0.0))
            out.append(abs(math.degrees(a3 - a2)))
    return out


def _angle(a, b, c):
    u = [a[i] - b[i] for i in range(3)]
    w = [c[i] - b[i] for i in range(3)]
    cos = sum(x * y for x, y in zip(u, w)) / (math.hypot(*u) * math.hypot(*w))
    return math.acos(max(-1.0, min(1.0, cos)))


def signed_area(pts):
    return 0.5 * sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(pts, pts[1:] + pts[:1]))


def assert_no_stretch(strip, uv, scale=1.0, tol=1e-4, angle=0.01):
    assert all(abs(r - scale) <= tol * scale for r in edge_ratios(strip, uv)), edge_ratios(strip, uv)
    assert max(corner_angle_errors(strip, uv)) < angle, corner_angle_errors(strip, uv)
    assert all(signed_area(pts) > 0 for pts in corners_uv(strip, uv).values())


# --- the n-gon strip -------------------------------------------------------------

def test_ngon_strip_builds_with_its_end_caps():
    strip = strip_from_faces(NGON_VERTS, NGON_FACES)
    ends = {frozenset((strip.near[0], strip.far[0])), frozenset((strip.near[-1], strip.far[-1]))}
    assert ends == {frozenset((115, 86)), frozenset((99, 135))}
    assert strip.sides == ([], []) and len(strip.rungs) == 2


@pytest.mark.parametrize("exact", [True, False])
def test_ngon_strip_splits_at_both_bends_without_stretch(exact):
    # On exact geometry every UV edge keeps its 3D length (1e-4) and every corner its angle (0.01 degree). The
    # captured coordinates' rounding bends their rails slightly: the straight rows then differ by up to 0.2 % and
    # 0.1 degree, the size of that rounding.
    strip = strip_from_faces(exact_ngon_verts() if exact else NGON_VERTS, NGON_FACES)
    strip.layout = "TRUE"
    assert sorted(rung_edge(strip, k) for k in bend_cut_rungs(strip, math.radians(15))) == [(40, 143), (43, 144)]
    pieces, reason = split_strip(strip, math.radians(15))
    assert reason is None and len(pieces) == 3
    assert sorted(sorted(p.faces) for p in pieces) == [[94], [104], [105]]
    for piece in pieces:
        if exact:
            assert_no_stretch(piece, stripe_uvs(piece))
        else:
            assert_no_stretch(piece, stripe_uvs(piece), tol=3e-3, angle=0.1)


def test_ngon_strip_pieces_are_rectangles_under_straight():
    strip = strip_from_faces(NGON_VERTS, NGON_FACES)
    strip.layout = "STRAIGHT"
    pieces, reason = split_strip(strip, math.radians(15))
    assert reason is None and len(pieces) == 3
    for piece in pieces:
        uv = stripe_uvs(piece)
        length = strip_length(piece)
        at = {}
        for (_f, vid), co in uv.items():
            at[vid] = co
        assert all(abs(at[v][1]) < 1e-9 for v in piece.near) and all(abs(at[v][1] - piece.height) < 1e-9
                                                                       for v in piece.far)
        assert at[piece.near[0]][0] == pytest.approx(at[piece.far[0]][0])      # both ends vertical
        assert at[piece.near[-1]][0] == pytest.approx(at[piece.far[-1]][0])
        assert {round(at[piece.near[0]][0], 9), round(at[piece.near[-1]][0], 9)} == {0.0, round(length, 9)}


def test_ngon_strip_torn_at_one_shared_edge():
    strip = strip_from_faces(exact_ngon_verts(), NGON_FACES)
    strip.layout = "TRUE"
    cuts = rungs_at(strip, {(43, 144)})
    assert len(cuts) == 1
    pieces = slice_strip(strip, cuts)
    assert sorted(sorted(p.faces) for p in pieces) == [[94], [104, 105]]
    for piece in pieces:
        uv = stripe_uvs(piece)
        assert all(signed_area(pts) > 0 for pts in corners_uv(piece, uv).values())
    assert_no_stretch(next(p for p in pieces if 94 in p.faces), stripe_uvs(next(p for p in pieces if 94 in p.faces)))


# --- slicing quads and rings -----------------------------------------------------

def quad_chain(n=5):
    verts = {i: (float(i), 0.0, 0.0) for i in range(n + 1)} | {100 + i: (float(i), 1.0, 0.0) for i in range(n + 1)}
    faces = {i: (i, i + 1, 101 + i, 100 + i) for i in range(n)}
    return verts, faces


def test_slice_a_quad_chain():
    verts, faces = quad_chain()
    strip = strip_from_faces(verts, faces)
    cuts = rungs_at(strip, {(2, 102), (3, 103)})
    pieces = slice_strip(strip, cuts)
    assert [sorted(p.faces) for p in pieces] == [[0, 1], [2], [3, 4]]
    assert pieces[1].rungs == [(0, 0), (1, 1)]                      # the middle piece: its two cut rungs
    assert pieces[0].rungs[-1] == (2, 2) and pieces[2].rungs[0] == (0, 0)
    for piece in pieces:
        assert len(piece.near) == len(piece.faces) + 1 and len(piece.far) == len(piece.faces) + 1
        piece.layout = "TRUE"
        assert_no_stretch(piece, stripe_uvs(piece))


def ring(n=8):
    verts, faces = {}, {}
    for i in range(n):
        a = 2 * math.pi * i / n
        verts[i] = (math.cos(a), math.sin(a), 0.0)
        verts[n + i] = (math.cos(a), math.sin(a), 1.0)
    for i in range(n):
        j = (i + 1) % n
        faces[i] = (i, j, n + j, n + i)
    return verts, faces


def test_slice_a_ring_once_cuts_it_open_there():
    verts, faces = ring()
    strip = strip_from_faces(verts, faces)
    (piece,) = slice_strip(strip, rungs_at(strip, {(3, 11)}))
    assert piece.closed and rung_edge(piece, piece.seam) == (3, 11)
    uv = stripe_uvs(piece)
    length = strip_length(piece)
    assert {round(u, 9) for (_f, v), (u, _v) in uv.items() if v == 3} == {0.0, round(length, 9)}


def test_slice_a_ring_twice_gives_two_open_pieces():
    verts, faces = ring()
    strip = strip_from_faces(verts, faces)
    pieces = slice_strip(strip, rungs_at(strip, {(1, 9), (5, 13)}))
    assert sorted(sorted(p.faces) for p in pieces) == [[0, 5, 6, 7], [1, 2, 3, 4]]
    for piece in pieces:
        assert not piece.closed and len(piece.near) == 5
        uv = stripe_uvs(piece)
        assert all(signed_area(pts) > 0 for pts in corners_uv(piece, uv).values())


def test_split_strip_reports_a_tear_it_cannot_make():
    verts, faces = quad_chain()
    strip = strip_from_faces(verts, faces)
    pieces, reason = split_strip(strip, None, extra_cuts=[1, 1, 2])
    assert len(pieces) == 3 and reason is None
    strip.height = 0.0
    pieces, reason = split_strip(strip, None, extra_cuts=[1])
    assert pieces == [strip] and reason == "a piece has no size"
    assert split_strip(strip, math.radians(15)) == ([strip], None)          # no bends: nothing to report


# --- n-gon end caps --------------------------------------------------------------

def test_subdivided_end_cap():
    # Two quads in a row whose far end edge is subdivided twice: that end face is a hexagon, its cap the
    # three-edge run between its two right-angle corners; the two vertices on it are that end's side.
    verts = {0: (0.0, 0.0, 0.0), 1: (1.0, 0.0, 0.0), 2: (2.0, 0.0, 0.0),
             3: (0.0, 1.0, 0.0), 4: (1.0, 1.0, 0.0), 5: (2.0, 1.0, 0.0),
             6: (2.0, 1.0 / 3.0, 0.0), 7: (2.0, 2.0 / 3.0, 0.0)}
    faces = {0: (0, 1, 4, 3), 1: (1, 2, 6, 7, 5, 4)}
    strip = strip_from_faces(verts, faces)
    end = 0 if strip.near[0] in (2, 5) else 1
    assert sorted(strip.sides[end]) == [6, 7]
    assert {strip.near[-1 if end else 0], strip.far[-1 if end else 0]} == {2, 5}
    strip.layout = "TRUE"
    assert_no_stretch(strip, stripe_uvs(strip))
    strip.layout = "EVEN"
    uv = stripe_uvs(strip)
    assert all(signed_area(pts) > 0 for pts in corners_uv(strip, uv).values())


def test_ngon_end_with_a_rail_vertex_keeps_the_cap_opposite():
    # A pentagon end whose rail carries an extra vertex: its corners are the two right angles at the end.
    verts = {0: (0.0, 0.0, 0.0), 1: (1.0, 0.0, 0.0), 2: (1.5, 0.0, 0.0), 3: (2.0, 0.0, 0.0),
             4: (0.0, 1.0, 0.0), 5: (1.0, 1.0, 0.0), 6: (2.0, 1.0, 0.0)}
    faces = {0: (0, 1, 5, 4), 1: (1, 2, 3, 6, 5)}
    strip = strip_from_faces(verts, faces)
    assert {strip.near[0], strip.far[0]} in ({0, 4}, {3, 6}) and strip.sides == ([], [])
    assert {strip.near[-1], strip.far[-1]} in ({0, 4}, {3, 6})


def test_pointed_pentagon_end_keeps_the_old_rule():
    # A pentagon tip whose inner corners are not both below 150 degrees: the middle-edge rule as before.
    verts = {0: (0.0, 0.0, 0.0), 1: (1.0, 0.0, 0.0), 2: (2.0, 0.2, 0.0), 3: (2.5, 0.5, 0.0),
             4: (2.0, 0.8, 0.0), 5: (1.0, 1.0, 0.0), 6: (0.0, 1.0, 0.0)}
    faces = {0: (0, 1, 5, 6), 1: (1, 2, 3, 4, 5)}
    strip = strip_from_faces(verts, faces)
    assert strip.sides == ([], [])
    tip = {strip.near[-1], strip.far[-1]} if 0 in (strip.near[0], strip.far[0]) else {strip.near[0], strip.far[0]}
    assert tip == {3} or len(tip) == 2


# --- the TRUE layout -------------------------------------------------------------

def mitred_quad():
    """A flat quad between parallel rails, its two ends slanted differently."""
    verts = {0: (0.0, 0.0, 0.0), 1: (3.0, 0.0, 0.0), 2: (2.2, 1.0, 0.0), 3: (0.5, 1.0, 0.0)}
    return Strip(verts=verts, faces={0: (0, 1, 2, 3)}, near=[0, 1], far=[3, 2], rungs=[], closed=False,
                 height=1.0, layout="TRUE")


def test_true_layout_keeps_a_mitred_quad():
    s = mitred_quad()
    uv = stripe_uvs(s)
    assert_no_stretch(s, uv, tol=1e-6)
    assert strip_extent(s) == pytest.approx(3.0)
    assert min(u for u, _v in uv.values()) == pytest.approx(0.0)


def test_true_layout_keeps_a_rail_ngon_and_its_sides():
    verts = {0: (0.0, 0.0, 0.0), 1: (1.0, 0.0, 0.0), 2: (2.5, 0.0, 0.0), 3: (2.0, 1.0, 0.0),
             4: (0.7, 1.0, 0.0), 5: (0.35, 0.5, 0.0), 6: (2.25, 0.5, 0.0)}
    s = Strip(verts=verts, faces={0: (0, 1, 2, 6, 3, 4, 5)}, near=[0, 1, 2], far=[4, 3], rungs=[], closed=False,
              height=1.0, sides=([5], [6]), layout="TRUE")
    uv = stripe_uvs(s)
    edges = edge_ratios(s, uv)
    assert all(abs(r - 1.0) < 1e-6 for r in edges), edges
    # side vertices lie on the straight line between their end's corners, where they are in 3D
    assert uv[(0, 6)] == pytest.approx((2.25 + 0.0, 0.5))


def test_true_layout_flips_mirrored_faces_back():
    s = mitred_quad()
    s.faces = {0: (3, 2, 1, 0)}
    uv = stripe_uvs(s)
    assert signed_area([uv[(0, v)] for v in s.faces[0]]) > 0
    assert all(abs(r - 1.0) < 1e-6 for r in edge_ratios(s, uv))
    assert min(u for u, _v in uv.values()) == pytest.approx(0.0)


def test_true_layout_on_a_closed_strip_is_even():
    verts, faces = ring()
    strip = strip_from_faces(verts, faces)
    even = stripe_uvs(strip)
    strip.layout = "TRUE"
    assert stripe_uvs(strip) == even and strip_extent(strip) == strip_length(strip)


def test_fit_uses_the_true_extents():
    a, b = mitred_quad(), mitred_quad()
    b.verts = {k: (x * 2.0, y * 2.0, z) for k, (x, y, z) in b.verts.items()}
    b.height = 2.0
    maps = [stripe_uvs(a), stripe_uvs(b)]
    extents = [strip_extent(a), strip_extent(b)]
    assert extents == pytest.approx([3.0, 6.0])
    out = place_fit(maps, [a.height, b.height], extents, groups=[0, 0])
    assert max(u for u, _v in out[1].values()) == pytest.approx(1.0)
    assert max(u for u, _v in out[0].values()) == pytest.approx(0.5)


# --- vertical placement ----------------------------------------------------------

def test_vertical_fit_is_a_rotation():
    a = mitred_quad()
    uv = stripe_uvs(a)
    flat = place_fit([uv], [a.height], [strip_extent(a)])[0]
    up = place_fit([uv], [a.height], [strip_extent(a)], vertical=True)[0]
    face = a.faces[0]
    assert signed_area([up[(0, v)] for v in face]) == pytest.approx(signed_area([flat[(0, v)] for v in face]))
    for k in range(4):
        p, q = (0, face[k]), (0, face[(k + 1) % 4])
        assert math.dist(up[p], up[q]) == pytest.approx(math.dist(flat[p], flat[q]))
    assert min(v for _u, v in up.values()) == pytest.approx(0.0) and max(v for _u, v in up.values()) == pytest.approx(1.0)
    assert min(u for u, _v in up.values()) == pytest.approx(0.0)


def test_vertical_fit_stacks_to_the_right():
    a = mitred_quad()
    uv = stripe_uvs(a)
    out = place_fit([uv, uv], [1.0, 1.0], [3.0, 3.0], vertical=True)
    assert max(u for u, _v in out[0].values()) == pytest.approx(1.0 / 3.0)
    assert min(u for u, _v in out[1].values()) == pytest.approx(1.0 / 3.0 + 0.01)


def test_vertical_in_place_turns_about_the_centre():
    a = mitred_quad()
    uv = stripe_uvs(a)
    flat = place_in_place(uv, 3.0, 1.0, (0.5, 0.5), 0.1)
    up = place_in_place(uv, 3.0, 1.0, (0.5, 0.5), 0.1, vertical=True)
    for key, (u, v) in flat.items():
        assert up[key] == pytest.approx((0.5 - (v - 0.5), 0.5 + (u - 0.5)))
    face = a.faces[0]
    assert signed_area([up[(0, v)] for v in face]) == pytest.approx(signed_area([flat[(0, v)] for v in face]))


# --- Active: fitting the other pieces to the reference's bounding box ---------------

def _rect_piece(w, h, at=(0.0, 0.0)):
    """A placed piece: one quad face 0 with corners (0..3) spanning w x h from ``at``, counter-clockwise."""
    x, y = at
    return {(0, 0): (x, y), (0, 1): (x + w, y), (0, 2): (x + w, y + h), (0, 3): (x, y + h)}


def _area(uv):
    return signed_area([uv[(0, k)] for k in range(4)])


@pytest.mark.parametrize("mode, size", [("BOTH", (2.0, 0.5)), ("WIDTH", (2.0, 0.25)), ("HEIGHT", (1.0, 0.5))])
def test_fit_to_reference_without_a_turn(mode, size):
    piece = _rect_piece(1.0, 0.25, at=(5.0, 5.0))           # landscape, as the reference
    reference = ((0.0, 0.0), (2.0, 0.5))
    out = fit_to_reference(piece, reference, mode)
    (u0, v0), (u1, v1) = bbox(out)
    assert (u1 - u0, v1 - v0) == pytest.approx(size)
    assert ((u0 + u1) / 2, (v0 + v1) / 2) == pytest.approx((1.0, 0.25))     # centred on the reference
    assert _area(out) > 0


@pytest.mark.parametrize("mode, size", [("BOTH", (2.0, 0.5)), ("WIDTH", (2.0, 0.25)), ("HEIGHT", (1.0, 0.5))])
def test_fit_to_reference_turns_a_transposed_piece(mode, size):
    piece = _rect_piece(0.25, 1.0, at=(3.0, 3.0))           # portrait against a landscape reference: turned
    reference = ((1.0, 1.0), (3.0, 1.5))
    out = fit_to_reference(piece, reference, mode)
    (u0, v0), (u1, v1) = bbox(out)
    assert (u1 - u0, v1 - v0) == pytest.approx(size)        # width / height measured after the turn
    assert ((u0 + u1) / 2, (v0 + v1) / 2) == pytest.approx((2.0, 1.25))
    assert _area(out) > 0                                    # a rotation, never a mirror
    # turned a quarter counter-clockwise: the first edge, along +u before, now runs along +v
    assert out[(0, 1)][0] == pytest.approx(out[(0, 0)][0]) and out[(0, 1)][1] > out[(0, 0)][1]


def test_fit_to_reference_keeps_the_reference():
    reference_piece = _rect_piece(2.0, 0.5)
    assert fit_to_reference(reference_piece, bbox(reference_piece)) == pytest.approx(reference_piece)


# --- random offsets -----------------------------------------------------------------

def test_random_offsets_are_deterministic_and_bounded():
    a = random_offsets(20, "BOTH", 0.25, seed=3)
    assert a == random_offsets(20, "BOTH", 0.25, seed=3)
    assert a != random_offsets(20, "BOTH", 0.25, seed=4)
    assert all(abs(du) <= 0.25 and abs(dv) <= 0.25 for du, dv in a)
    assert any(abs(du) > 0.1 for du, _dv in a)


def test_random_offsets_move_only_the_chosen_axis_and_keep_the_reference():
    both = random_offsets(6, "BOTH", 0.5, seed=1)
    horizontal = random_offsets(6, "HORIZONTAL", 0.5, seed=1)
    vertical = random_offsets(6, "VERTICAL", 0.5, seed=1)
    assert horizontal == [(du, 0.0) for du, _dv in both]
    assert vertical == [(0.0, dv) for _du, dv in both]
    kept = random_offsets(6, "BOTH", 0.5, seed=1, keep=2)
    assert kept[2] == (0.0, 0.0) and kept[:2] + kept[3:] == both[:2] + both[3:]
    assert random_offsets(3, "NONE", 0.5, seed=1) == [(0.0, 0.0)] * 3
    assert shifted(_rect_piece(1.0, 1.0), (0.5, -0.25))[(0, 2)] == pytest.approx((1.5, 0.75))


# --- opening a ring at a rung -------------------------------------------------------

def uvs_by_face(uv):
    """Each face's corner UVs in its winding order (``stripe_uvs`` lists a face's corners in that order)."""
    out = {}
    for (fid, _vid), co in uv.items():
        out.setdefault(fid, []).append(co)
    return out


def is_axis_aligned_rectangle(pts, tol=1e-9):
    if len(pts) != 4 or abs(signed_area(pts)) <= tol:
        return False
    edges = [(b[0] - a[0], b[1] - a[1]) for a, b in zip(pts, pts[1:] + pts[:1])]
    flat = [abs(dv) <= tol for _du, dv in edges]
    upright = [abs(du) <= tol for du, _dv in edges]
    return all(f != u for f, u in zip(flat, upright)) and flat[0] == flat[2] != flat[1] == flat[3]


def test_open_ring_is_open_and_keeps_every_face():
    strip = strip_from_faces(*flat_annulus(8))
    opened = open_ring(strip, 3)
    assert opened.closed is False
    assert opened.break_edge == rung_edge(strip, 3)
    assert set(opened.faces) == set(strip.faces)
    assert opened.near[0] == opened.near[-1] and opened.far[0] == opened.far[-1]


def _covers_every_corner(strip, uv):
    return set(uv) == {(fid, vid) for fid, face in strip.faces.items() for vid in face}


def test_opened_ring_true_layout_matches_open_strip_rules():
    opened = open_ring(strip_from_faces(*flat_annulus(8, outer=1.0, inner=0.5)), 0)
    opened.layout = "TRUE"
    uv = stripe_uvs(opened)
    assert _covers_every_corner(opened, uv)
    assert all(signed_area(f) > 0 for f in uvs_by_face(uv).values())
    us = [u for u, _v in uv.values()]
    assert max(us) - min(us) == pytest.approx(strip_extent(opened), rel=1e-9)
    for vid in (opened.near[0], opened.far[0]):            # the row's start and end copies of the break vertex
        assert len({round(u, 9) for (_f, v), (u, _v) in uv.items() if v == vid}) == 2


@pytest.mark.parametrize("rung", [0, 5])
def test_opened_ring_shape_layout_does_not_fold(rung):
    opened = open_ring(strip_from_faces(*flat_annulus(8)), rung)
    opened.layout = "SHAPE"
    uv = stripe_uvs(opened)
    assert _covers_every_corner(opened, uv)
    assert all(signed_area(f) > 0 for f in uvs_by_face(uv).values())


def test_opened_ring_straightens_to_rectangles():
    opened = open_ring(strip_from_faces(*flat_annulus(8)), 0)
    assert straighten(opened) is True
    for face_uvs in uvs_by_face(stripe_uvs(opened)).values():
        assert is_axis_aligned_rectangle(face_uvs)


def test_opened_ring_faces_are_not_flipped():
    opened = open_ring(strip_from_faces(*flat_annulus(8)), 5)
    assert all(signed_area(f) > 0 for f in uvs_by_face(stripe_uvs(opened)).values())


@pytest.mark.parametrize("layout", ["EVEN", "STRAIGHT", "TRUE", "SHAPE"])
@pytest.mark.parametrize("rung", range(9))
def test_opened_ring_with_a_triangle_lays_out_in_every_layout(layout, rung):
    strip = strip_from_faces(*flat_annulus_with_triangle(8))
    opened = open_ring(strip, rung)
    assert opened.break_edge == rung_edge(strip, rung) and opened.seam is None
    assert opened.height == strip.height and opened.sides == ([], [])
    opened.layout = layout
    uv = stripe_uvs(opened)
    assert all(signed_area(f) > 0 for f in uvs_by_face(uv).values())
    # the break edge's two vertices stand at both ends of the strip (vertical ends: "EVEN" and "STRAIGHT")
    for vid in opened.break_edge if layout in ("EVEN", "STRAIGHT") else ():
        assert {round(u, 6) for (_f, v), (u, _v) in uv.items() if v == vid} == {0.0, round(strip_extent(opened), 6)}


def test_open_ring_keeps_the_closed_strip():
    strip = strip_from_faces(*flat_annulus(8))
    before = (list(strip.near), list(strip.far), list(strip.rungs), dict(strip.corner_near), dict(strip.corner_far))
    open_ring(strip, 2)
    assert strip.closed and (strip.near, strip.far, strip.rungs, strip.corner_near, strip.corner_far) == before
