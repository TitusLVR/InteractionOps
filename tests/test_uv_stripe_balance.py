"""UV Stripe's balanced layout of a strip several faces wide (``utils/uv_stripe_balance_core``), the corner rule
that builds such a patch, and Auto's choice of it."""
import math

import pytest

from utils import uv_stripe_balance_core as balance
from utils.uv_stripe_auto_core import Shape, auto_cuts, best_straight, choose_layout, layout_stretch
from utils.uv_stripe_balance_core import balanced_extent, balanced_uvs, folded_faces, is_wide, start_end
from utils.uv_stripe_core import Strip, face_stretch, lay_piece, strip_extent, strip_v_extent, stripe_uvs
from utils.uv_stripe_select_core import strip_from_faces


def _grid(cols, rows, width=1.0, height=1.0):
    """A flat grid of ``cols`` x ``rows`` quads in z = 0, wound counter-clockwise from +z; vertex (i, j) is
    i + j * (cols + 1)."""
    verts = {i + j * (cols + 1): (i * width, j * height, 0.0) for j in range(rows + 1) for i in range(cols + 1)}
    faces = {}
    for j in range(rows):
        for i in range(cols):
            a = i + j * (cols + 1)
            faces[len(faces)] = (a, a + 1, a + cols + 2, a + cols + 1)
    return verts, faces


def _l_arc(cols=8, sweep=math.pi, inner=0.8, outer=1.0, wall=0.2):
    """An arc with an L profile: a flat ledge (a ring sector from ``inner`` to ``outer`` in z = 0) and a wall
    hanging from its inner edge down to z = -``wall``. Rings: 0 the outer edge, 1 the fold, 2 the wall's foot;
    vertex (ring k, column i) is k * (cols + 1) + i. Returns (verts, faces, ring id lists)."""
    angles = [sweep * i / cols for i in range(cols + 1)]
    profile = [(outer, 0.0), (inner, 0.0), (inner, -wall)]
    verts, rings = {}, []
    for k, (r, z) in enumerate(profile):
        ids = [k * (cols + 1) + i for i in range(cols + 1)]
        for v, a in zip(ids, angles):
            verts[v] = (r * math.cos(a), r * math.sin(a), z)
        rings.append(ids)
    faces = {}
    for k in range(2):
        for i in range(cols):
            faces[len(faces)] = (rings[k][i], rings[k][i + 1], rings[k + 1][i + 1], rings[k + 1][i])
    return verts, faces, rings


def _collapsed_arc(column=3):
    """The L arc with the ledge's outer vertex at ``column + 1`` collapsed away: that column of the ledge row
    is a triangle and the next a quad spanning two outer steps."""
    verts, faces, rings = _l_arc()
    outer, fold = rings[0], rings[1]
    gone = outer[column + 1]
    faces = {fid: f for fid, f in faces.items() if gone not in f}
    faces[100] = (outer[column], fold[column + 1], fold[column])
    faces[101] = (outer[column], outer[column + 2], fold[column + 2], fold[column + 1])
    del verts[gone]
    return verts, faces, rings, gone


def _corner_cut_grid():
    """A flat 4 x 2 grid of 1 x 0.5 cells whose corner (0, 0) collapsed into (1, 0): its first cell is a
    triangle, so only three boundary vertices are used by one face."""
    verts, faces = _grid(4, 2, 1.0, 0.5)
    del verts[0]
    faces[0] = (1, 6, 5)
    return verts, faces


def _stretch(strip, uv):
    return [face_stretch([strip.verts[v] for v in face], [uv[(fid, v)] for v in face])
            for fid, face in strip.faces.items()]


def _pos(uv):
    return {vid: p for (_fid, vid), p in uv.items()}


def _spread(pos, ids, axis):
    values = [pos[v][axis] for v in ids]
    return max(values) - min(values)


def _ends(strip):
    return [strip.near[0], *strip.sides[0], strip.far[0]], [strip.near[-1], *strip.sides[1], strip.far[-1]]


@pytest.fixture(autouse=True)
def _fresh_cache():
    balance._CACHE.clear()
    yield
    balance._CACHE.clear()


def _fanned_arc(column=3, at=0.4, bulge=1e-4):
    """The L arc with an extra vertex on the fold's chord in ``column``, ``at`` of the way along it and pushed
    out by ``bulge`` within the ledge (almost in line): the wall face there is a pentagon whose top carries it,
    and the ledge face above a fan of three triangles round it."""
    verts, faces, rings = _l_arc()
    outer, fold, foot = rings
    m = 99
    a, b = verts[fold[column]], verts[fold[column + 1]]
    x, y = a[0] + at * (b[0] - a[0]), a[1] + at * (b[1] - a[1])
    r = math.hypot(x, y)
    verts[m] = (x * (r + bulge) / r, y * (r + bulge) / r, a[2])
    ledge = next(fid for fid, f in faces.items() if f == (outer[column], outer[column + 1], fold[column + 1], fold[column]))
    wall = next(fid for fid, f in faces.items() if f == (fold[column], fold[column + 1], foot[column + 1], foot[column]))
    faces[wall] = (fold[column], m, fold[column + 1], foot[column + 1], foot[column])
    faces[ledge] = (outer[column], outer[column + 1], m)
    faces[200] = (outer[column + 1], fold[column + 1], m)
    faces[201] = (m, fold[column], outer[column])
    return verts, faces, rings, m, wall


def _edge_lengths_kept(strip, uv):
    for fid, face in strip.faces.items():
        for a, b in zip(face, face[1:] + face[:1]):
            if abs(math.dist(uv[(fid, a)], uv[(fid, b)]) - math.dist(strip.verts[a], strip.verts[b])) > 1e-6:
                return False
    return True


def _area(pts):
    return 0.5 * sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(pts, pts[1:] + pts[:1]))


def _no_fold(strip, uv, least=0.0):
    return all(_area([uv[(fid, v)] for v in face]) > least for fid, face in strip.faces.items())


def _segments_cross(p, q, r, s):
    def side(a, b, c):
        return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
    return side(p, q, r) * side(p, q, s) < 0.0 and side(r, s, p) * side(r, s, q) < 0.0


def _clean(pts):
    """Whether a UV polygon is a plain counter-clockwise outline: positive area and no edge crossing another."""
    n = len(pts)
    if _area(pts) <= 0.0:
        return False
    return not any(_segments_cross(pts[i], pts[(i + 1) % n], pts[j], pts[(j + 1) % n])
                   for i in range(n) for j in range(i + 2, n) if not (i == 0 and j == n - 1))


def _butterfly_arc():
    """A short, steep L arc (a wide ledge narrowing to a tight wall) with half its quads split in two: the
    unguarded solve laid one quad out crossing itself, with a positive area."""
    angles = [0.5 * i / 3 for i in range(4)]
    profile = [(1.0, 0.0), (0.05, 0.0), (0.05, -0.6)]
    verts = {k * 4 + i: (r * math.cos(a), r * math.sin(a), z) for k, (r, z) in enumerate(profile)
             for i, a in enumerate(angles)}
    faces = {0: (0, 1, 4), 1: (1, 5, 4), 2: (1, 2, 6, 5), 3: (2, 3, 7), 4: (2, 7, 6), 5: (4, 5, 8), 6: (5, 9, 8),
             7: (5, 6, 10, 9), 8: (6, 7, 11), 9: (6, 11, 10)}
    return verts, faces


def test_flat_grid_is_an_exact_rectangle():
    verts, faces = _grid(4, 2)
    strip = strip_from_faces(verts, faces)
    assert is_wide(strip)
    uv = balanced_uvs(strip)
    assert all(abs(s - 1.0) < 1e-6 for s in _stretch(strip, uv))
    assert _edge_lengths_kept(strip, uv)
    assert balanced_extent(strip) == pytest.approx((4.0, 2.0), abs=1e-6)
    pos = _pos(uv)
    assert _spread(pos, strip.near, 1) < 1e-9 and _spread(pos, strip.far, 1) < 1e-9
    assert _spread(pos, [5, 6, 7, 8, 9], 1) < 1e-9


def test_l_arc_is_one_straight_strip_with_less_stretch():
    verts, faces, rings = _l_arc()
    strip = strip_from_faces(verts, faces)
    assert is_wide(strip)
    assert {frozenset(strip.near), frozenset(strip.far)} == {frozenset(rings[0]), frozenset(rings[2])}
    uv = lay_piece(strip, "BALANCED")
    stretch = _stretch(strip, uv)
    assert max(stretch) < max(best_straight(strip)[1])
    upright = _stretch(strip, balanced_uvs(strip, "BOTH"))
    assert max(upright) < math.sqrt(1.0 / 0.8) + 0.03       # upright ends: the ring's own spread, no more
    pos = _pos(uv)
    assert _spread(pos, strip.near, 1) < 1e-9 and _spread(pos, strip.far, 1) < 1e-9
    assert _spread(pos, rings[1], 1) < 1e-9                         # the fold line
    assert min(p[0] for p in pos.values()) == pytest.approx(0.0, abs=1e-9)
    assert min(p[1] for p in pos.values()) == pytest.approx(0.0, abs=1e-9)
    assert _no_fold(strip, uv)
    length, height = balanced_extent(strip)
    assert strip_extent(strip) == length and strip_v_extent(strip) == height
    assert max(p[0] for p in pos.values()) == pytest.approx(length)
    assert max(p[1] for p in pos.values()) == pytest.approx(height)


def test_balanced_keeps_the_direction_of_the_strip():
    verts, faces, _rings = _l_arc()
    strip = strip_from_faces(verts, faces)
    even = _pos(lay_piece(strip, "EVEN"))
    for ends in balance.ENDS:
        for rails in ("BOTH", "NEAR", "FAR"):
            bal = _pos(balanced_uvs(strip, ends, rails))
            first, last = sorted((strip.near[0], strip.near[-1]), key=lambda v: even[v][0])
            assert bal[first][0] < bal[last][0]
            assert (sum(bal[v][1] for v in strip.near) / len(strip.near)
                    < sum(bal[v][1] for v in strip.far) / len(strip.far))


@pytest.mark.parametrize("ends", ["FREE", "BOTH", "START", "END"])
@pytest.mark.parametrize("rails", ["BOTH", "NEAR", "FAR"])
@pytest.mark.parametrize("how", ["EVEN_TEXEL", "LEAST_STRETCH"])
def test_each_mode_keeps_straight_what_it_names(ends, rails, how):
    verts, faces, rings = _l_arc()
    strip = strip_from_faces(verts, faces)
    uv = balanced_uvs(strip, ends, rails, how)
    pos = _pos(uv)
    assert _no_fold(strip, uv)
    assert max(_stretch(strip, uv)) < max(best_straight(strip)[1])
    if rails in ("BOTH", "NEAR"):
        assert _spread(pos, strip.near, 1) < 1e-9
    if rails in ("BOTH", "FAR"):
        assert _spread(pos, strip.far, 1) < 1e-9
    if rails == "BOTH":
        assert _spread(pos, rings[1], 1) < 1e-9
    first = start_end(strip)
    for k, end in enumerate(_ends(strip)):
        upright = ends == "BOTH" or (ends == "START" and k == first) or (ends == "END" and k != first)
        if upright:
            assert _spread(pos, end, 0) < 1e-9
        else:
            assert _spread(pos, end, 0) > 1e-6                     # a free end keeps its slant


def test_free_modes_do_not_force_what_they_leave_free():
    verts, faces, rings = _l_arc()
    strip = strip_from_faces(verts, faces)
    pos = _pos(balanced_uvs(strip, "FREE", "NEAR"))
    assert _spread(pos, strip.far, 1) > 1e-6 and _spread(pos, rings[1], 1) > 1e-6
    pos = _pos(balanced_uvs(strip, "FREE", "BOTH"))
    assert any(_spread(pos, end, 0) > 1e-6 for end in _ends(strip))


def test_unknown_mode_is_refused():
    verts, faces, _rings = _l_arc()
    strip = strip_from_faces(verts, faces)
    with pytest.raises(ValueError):
        balanced_uvs(strip, "SLANTED")
    with pytest.raises(ValueError):
        balanced_uvs(strip, "STRAIGHT")                 # the old name of "BOTH"
    with pytest.raises(ValueError):
        balanced_uvs(strip, rails="NONE")
    with pytest.raises(ValueError):
        balanced_uvs(strip, balance="ARAP")


def test_collapsed_arc_is_laid_out_without_a_fold():
    verts, faces, rings, gone = _collapsed_arc()
    strip = strip_from_faces(verts, faces)
    uv = balanced_uvs(strip)
    assert _no_fold(strip, uv, 1e-9)
    assert all(s < 2.0 for s in _stretch(strip, uv))
    pos = _pos(uv)
    assert _spread(pos, rings[1], 1) < 1e-9                         # the fold, bounded by the wall's quads
    assert _spread(pos, [v for v in rings[0] if v != gone], 1) < 1e-9


def test_a_vertex_in_line_on_a_side_stays_in_line():
    verts, faces, rings, m, wall = _fanned_arc()
    strip = strip_from_faces(verts, faces)
    uv = balanced_uvs(strip)
    assert _no_fold(strip, uv)
    pos = _pos(uv)
    assert _spread(pos, rings[1] + [m], 1) < 1e-9                   # the fold runs on through the pentagon
    stretch = dict(zip(strip.faces, _stretch(strip, uv)))
    assert stretch[wall] < 1.1
    side = (rings[1][3], rings[1][4])                               # m keeps its fraction along the side
    before = math.dist(strip.verts[side[0]], strip.verts[m])
    real = before / (before + math.dist(strip.verts[m], strip.verts[side[1]]))
    laid = (pos[m][0] - pos[side[0]][0]) / (pos[side[1]][0] - pos[side[0]][0])
    assert laid == pytest.approx(real, abs=1e-9)
    assert max(stretch.values()) < max(best_straight(strip)[1])


def test_patch_with_a_corner_lost_to_a_collapsed_vertex_is_a_strip():
    verts, faces = _corner_cut_grid()
    strip = strip_from_faces(verts, faces)
    assert not strip.closed
    corners = {strip.near[0], strip.near[-1], strip.far[0], strip.far[-1]}
    assert corners == {5, 10, 4, 14}
    assert _no_fold(strip, balanced_uvs(strip), 1e-9)


def test_balanced_is_deterministic():
    verts, faces, _rings, _gone = _collapsed_arc()
    first = balanced_uvs(strip_from_faces(verts, faces))
    balance._CACHE.clear()
    assert balanced_uvs(strip_from_faces(verts, faces)) == first


def test_balanced_refuses_a_closed_strip():
    n = 8
    verts = {i: (math.cos(2 * math.pi * i / n), math.sin(2 * math.pi * i / n), 0.0) for i in range(n)}
    verts.update({n + i: (0.8 * math.cos(2 * math.pi * i / n), 0.8 * math.sin(2 * math.pi * i / n), 0.0)
                  for i in range(n)})
    ring = strip_from_faces(verts, {i: (i, (i + 1) % n, n + (i + 1) % n, n + i) for i in range(n)})
    assert ring.closed and not is_wide(ring)
    with pytest.raises(ValueError):
        balanced_uvs(ring)


def test_one_face_wide_strips_are_not_wide():
    verts, faces = _grid(5, 1)
    strip = strip_from_faces(verts, faces)
    assert not is_wide(strip)
    assert choose_layout(strip, Shape(), 1.25) == ("TRUE", "BOTH", "FREE")
    single = strip_from_faces(*_grid(1, 1))
    assert not is_wide(single)


def test_auto_takes_balanced_for_the_arc_and_never_tears_it():
    verts, faces, _rings = _l_arc()
    strip = strip_from_faces(verts, faces)
    assert choose_layout(strip, Shape(), 1.25) == ("BALANCED", "BOTH", "BOTH")   # free ends: upright ones stretch least
    assert choose_layout(strip, Shape(), 10.0) == ("BALANCED", "BOTH", "BOTH")   # within any limit
    assert auto_cuts(strip) == []
    assert max(layout_stretch(strip, "BALANCED")) < max(best_straight(strip)[1])


def test_auto_keeps_the_straight_layout_where_balanced_is_no_better():
    verts, faces = _grid(4, 2)
    strip = strip_from_faces(verts, faces)
    assert choose_layout(strip, Shape(), 1.25) == ("TRUE", "BOTH", "FREE")


def test_stripe_uvs_dispatches_balanced():
    verts, faces, _rings = _l_arc()
    strip = strip_from_faces(verts, faces)
    strip.layout = "BALANCED"
    assert stripe_uvs(strip) == balanced_uvs(strip)


def test_the_solve_has_converged():
    verts, faces, _rings, _gone = _collapsed_arc()
    strip = strip_from_faces(verts, faces)
    uv = balanced_uvs(strip)
    balance._CACHE.clear()
    iters, tol = balance.BALANCE_ITERS, balance.BALANCE_TOL
    balance.BALANCE_ITERS, balance.BALANCE_TOL = 5000, 1e-12
    try:
        settled = balanced_uvs(strip)
    finally:
        balance.BALANCE_ITERS, balance.BALANCE_TOL = iters, tol
    assert max(math.dist(uv[k], settled[k]) for k in uv) < 1e-4


_PENTAGON = [(math.cos(math.pi / 2 + 2 * math.pi * k / 5), math.sin(math.pi / 2 + 2 * math.pi * k / 5)) for k in range(5)]
_PENTAGRAM = [_PENTAGON[2 * k % 5] for k in range(5)]


@pytest.mark.parametrize(("points", "flat", "folds"), [
    ([(0, 0), (1, 0), (1, 1), (0, 1)], [(0, 0), (1, 0), (1, 1), (0, 1)], False),
    ([(0, 0), (1, 0), (0, 1), (1, 1)], [(0, 0), (1, 0), (1, 1), (0, 1)], True),           # a butterfly
    ([(0, 0), (0, 1), (1, 1), (1, 0)], [(0, 0), (1, 0), (1, 1), (0, 1)], True),           # clockwise
    ([(0, 0), (2, 0), (0.5, 0.5), (0, 2)], [(0, 0), (2, 0), (2, 2), (0, 2)], True),       # a reflex corner
    ([(0, 0), (2, 0), (0.5, 0.5), (0, 2)], [(0, 0), (2, 0), (0.5, 0.5), (0, 2)], False),  # reflex in 3D too
    ([(0, 0), (1, 0), (2, 0), (2, 1), (0, 1)], [(0, 0), (1, 0), (2, 0), (2, 1), (0, 1)], False),
    ([(0, 0), (1, 0), (2, 0), (1, 0)], [(0, 0), (1, 0), (1, 1), (0, 1)], True),           # flattened to a line
    (_PENTAGRAM, _PENTAGON, True),                    # turns left at every corner, yet crosses itself
])
def test_fold_check(points, flat, folds):
    assert balance._folds([tuple(map(float, p)) for p in points], [tuple(map(float, p)) for p in flat]) is folds


def test_a_layout_that_would_fold_a_face_is_refused_and_auto_falls_back():
    verts, faces = _butterfly_arc()
    strip = strip_from_faces(verts, faces)
    assert is_wide(strip)
    for ends in balance.ENDS:
        for rails in ("BOTH", "NEAR", "FAR"):
            try:
                uv = balanced_uvs(strip, ends, rails)
            except ValueError:
                continue
            assert all(_clean([uv[(fid, v)] for v in face]) for fid, face in strip.faces.items()), (ends, rails)
    with pytest.raises(ValueError, match="folds"):
        balanced_uvs(strip)
    assert choose_layout(strip, Shape(), 10.0) == ("TRUE", "BOTH", "FREE")   # the straight layout, unrelaxed


def test_auto_takes_the_straight_layout_when_balanced_raises(monkeypatch):
    verts, faces, _rings = _l_arc()
    strip = strip_from_faces(verts, faces)
    calls = []

    def refuse(*args):
        calls.append(args)
        raise ValueError("no")
    monkeypatch.setattr(balance, "_solve", refuse)
    assert choose_layout(strip, Shape(), 10.0)[0] == best_straight(strip)[0]
    assert len(calls) == 2                                  # free ends and upright ends, one solve each
    for _ in range(3):
        with pytest.raises(ValueError):
            balanced_uvs(strip, "BOTH")
    assert len(calls) == 2                                  # the failure is kept like a result


@pytest.mark.parametrize("squash", ["collinear", "zero row"])
def test_degenerate_patches_raise(squash):
    verts, faces, rings = _l_arc()
    if squash == "collinear":
        verts = {v: (p[0], 0.0, 0.0) for v, p in verts.items()}
    else:
        verts.update({f: verts[o] for o, f in zip(rings[0], rings[1])})
    strip = strip_from_faces(verts, faces)
    with pytest.raises(ValueError):
        balanced_uvs(strip)


def _disc(n, centre_fan=False):
    verts = {i: (math.cos(2 * math.pi * i / n), math.sin(2 * math.pi * i / n), 0.0) for i in range(n)}
    verts.update({n + i: (0.5 * math.cos(2 * math.pi * i / n), 0.5 * math.sin(2 * math.pi * i / n), 0.0)
                  for i in range(n)})
    faces = {i: (i, (i + 1) % n, n + (i + 1) % n, n + i) for i in range(n)}
    if centre_fan:
        verts[99] = (0.0, 0.0, 0.0)
        faces.update({100 + i: (n + i, n + (i + 1) % n, 99) for i in range(n)})
    else:
        faces[n] = tuple(n + i for i in range(n))
    return verts, faces


@pytest.mark.parametrize("make", [
    *(lambda n=n: _disc(n) for n in range(4, 12)),
    *(lambda n=n: _disc(n, centre_fan=True) for n in (4, 6, 8)),
    lambda: ({0: (0, 0, 0), 1: (1, -0.4, 0), 2: (2, 0, 0), 3: (0.5, 1, 0), 4: (1.5, 1, 0), 5: (1, 2, 0)},
             {0: (0, 1, 3), 1: (1, 4, 3), 2: (1, 2, 4), 3: (3, 4, 5)}),                 # a triangle, one side kinked
])
def test_discs_caps_and_kinked_triangles_are_no_strips(make):
    verts, faces = make()
    with pytest.raises(ValueError, match="corners"):
        strip_from_faces(verts, faces)


def test_a_lost_corner_must_stand_out():
    verts, faces = _corner_cut_grid()
    verts[2] = (2.0, -0.6, 0.0)          # a kink in the rail nearly as sharp as the lost corner: no clear corner
    with pytest.raises(ValueError, match="corners"):
        strip_from_faces(verts, faces)


def test_start_end_names_the_end_laid_at_u_zero():
    verts, faces, _rings = _l_arc()
    strip = strip_from_faces(verts, faces)
    first = start_end(strip)
    pos = _pos(balanced_uvs(strip))
    ends = _ends(strip)
    assert min(pos[v][0] for v in ends[first]) == pytest.approx(0.0, abs=1e-9)
    assert min(pos[v][0] for v in ends[first]) < min(pos[v][0] for v in ends[1 - first])


@pytest.mark.parametrize("make", [lambda: _l_arc()[:2], lambda: _collapsed_arc()[:2], lambda: _fanned_arc()[:2]])
@pytest.mark.parametrize("ends", ["FREE", "BOTH"])
def test_least_stretch_stretches_less_and_keeps_the_strip_straight(make, ends):
    verts, faces = make()
    strip = strip_from_faces(verts, faces)
    even = balanced_uvs(strip, ends, "BOTH", "EVEN_TEXEL")
    least = balanced_uvs(strip, ends, "BOTH", "LEAST_STRETCH")
    assert max(_stretch(strip, least)) < max(_stretch(strip, even)) - 1e-3
    assert _no_fold(strip, least, 1e-12) and folded_faces(strip, least) == 0
    pos = _pos(least)
    assert _spread(pos, strip.near, 1) < 1e-9 and _spread(pos, strip.far, 1) < 1e-9
    if ends == "BOTH":
        assert all(_spread(pos, end, 0) < 1e-9 for end in _ends(strip))
    length, height = balanced_extent(strip, ends, "BOTH", "LEAST_STRETCH")
    assert max(p[0] for p in pos.values()) == pytest.approx(length)
    assert max(p[1] for p in pos.values()) == pytest.approx(height)


def test_least_stretch_holds_the_size():
    verts, faces, _rings = _l_arc()
    strip = strip_from_faces(verts, faces)
    even = balanced_extent(strip, "FREE", "BOTH", "EVEN_TEXEL")
    least = balanced_extent(strip, "FREE", "BOTH", "LEAST_STRETCH")
    assert least[0] == pytest.approx(even[0], rel=0.1) and least[1] == pytest.approx(even[1], rel=0.1)


def test_least_stretch_falls_back_to_even_texel_when_it_fails(monkeypatch):
    verts, faces, _rings = _l_arc()
    strip = strip_from_faces(verts, faces)
    even = balanced_uvs(strip, "FREE", "BOTH", "EVEN_TEXEL")

    def refuse(*_args):
        raise ValueError("no")
    monkeypatch.setattr(balance, "_least_stretch", refuse)
    assert balanced_uvs(strip, "FREE", "BOTH", "LEAST_STRETCH") == even


def test_least_stretch_that_folds_a_face_falls_back_to_even_texel(monkeypatch):
    verts, faces, _rings = _l_arc()
    strip = strip_from_faces(verts, faces)
    even = balanced_uvs(strip, "FREE", "BOTH", "EVEN_TEXEL")
    real = balance._least_stretch

    def fold(*args):
        pos = real(*args)
        face = strip.faces[0]
        a, b = face[0], face[2]
        pos[a], pos[b] = pos[b], pos[a]          # two opposite corners swapped: that quad crosses itself
        return pos
    monkeypatch.setattr(balance, "_least_stretch", fold)
    assert balanced_uvs(strip, "FREE", "BOTH", "LEAST_STRETCH") == even


def test_least_stretch_is_for_wide_strips_only():
    verts, faces = _grid(5, 1, 1.0, 0.5)
    verts = {v: (x, y + 0.1 * x * x, 0.0) for v, (x, y, _z) in verts.items()}     # a bent strip one face wide
    strip = strip_from_faces(verts, faces)
    assert not is_wide(strip)
    assert balanced_uvs(strip, "FREE", "BOTH", "LEAST_STRETCH") == balanced_uvs(strip, "FREE", "BOTH", "EVEN_TEXEL")


def test_least_stretch_is_deterministic():
    verts, faces, _rings, _gone = _collapsed_arc()
    first = balanced_uvs(strip_from_faces(verts, faces), "FREE", "BOTH", "LEAST_STRETCH")
    balance._CACHE.clear()
    assert balanced_uvs(strip_from_faces(verts, faces), "FREE", "BOTH", "LEAST_STRETCH") == first


def test_folded_faces_counts_turned_and_crossed_faces_but_not_twisted_ones():
    verts, faces = _grid(2, 1)
    strip = strip_from_faces(verts, faces)
    uv = {(fid, v): (verts[v][0], verts[v][1]) for fid, face in faces.items() for v in face}
    assert folded_faces(strip, uv) == 0
    turned = dict(uv)
    for v in faces[0]:
        turned[(0, v)] = (-verts[v][0], verts[v][1])          # mirrored: winds the other way
    assert folded_faces(strip, turned) == 1
    a, b = faces[1][0], faces[1][1]
    crossed = dict(uv)
    crossed[(1, a)], crossed[(1, b)] = uv[(1, b)], uv[(1, a)]  # a butterfly
    assert folded_faces(strip, crossed) == 1
    bow = Strip({0: (0.0, 0.0, 0.0), 1: (2.0, 0.0, 0.0), 2: (0.0, 1.0, 0.0), 3: (1.0, 1.0, 0.0)},
                {0: (0, 1, 2, 3)}, [0, 1], [3, 2], [], False, 1.0)        # a face that crosses itself seen square on
    flat = {(0, v): (p[0], p[1]) for v, p in bow.verts.items()}
    assert folded_faces(bow, flat) == 0                         # no flat layout keeps it: not counted
