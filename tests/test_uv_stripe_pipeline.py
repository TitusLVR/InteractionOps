"""UV Stripe's pipeline on synthetic meshes: the corner rule on rounded and n-gon ends, an island cut into strips
(each its own strip), the Balance slider, fan measures and the live (capped) solve."""
import math

import pytest

from utils import uv_stripe_balance_core as balance
from utils.uv_stripe_balance_core import balance_value, balanced_uvs, folded_faces
from utils.uv_stripe_core import face_stretch
from utils.uv_stripe_select_core import strip_from_faces
from utils.uv_stripe_split_core import split_island


@pytest.fixture(autouse=True)
def _fresh_cache():
    balance.clear_caches()
    yield
    balance.clear_caches()


# --- builders ---------------------------------------------------------------------------------------------

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


def _flat_arc(cols=8, sweep=math.pi / 2, inner=0.8, outer=1.0):
    """The flat quad arc one face wide: ``cols`` quads between two radii in z = 0; vertex (column j, ring k) is
    j * 2 + k (ring 0 outer, ring 1 inner)."""
    verts = {}
    for j in range(cols + 1):
        a = sweep * j / cols
        verts[2 * j] = (outer * math.cos(a), outer * math.sin(a), 0.0)
        verts[2 * j + 1] = (inner * math.cos(a), inner * math.sin(a), 0.0)
    faces = {j: (2 * j, 2 * j + 2, 2 * j + 3, 2 * j + 1) for j in range(cols)}
    return verts, faces


def _rounded_l_arc(cols=8, sweep=math.pi / 2):
    """The L arc with column ``j`` * 3 + ring ``k`` ids whose last column's ledge quad gets two extra vertices on
    its end edge and its wall quad one, bulging out along the arc tangent by 0.12 sin(pi s); each is inserted
    between its face's second and third corner (faces are (a, b, b + 1, a + 1), a = j * 3 + k, b = a + 3)."""
    angles = [sweep * j / cols for j in range(cols + 1)]
    profile = [(1.0, 0.0), (0.8, 0.0), (0.8, -0.2)]
    verts = {j * 3 + k: (r * math.cos(a), r * math.sin(a), z)
             for j, a in enumerate(angles) for k, (r, z) in enumerate(profile)}
    faces = {}
    for j in range(cols):
        for k in range(2):
            a = j * 3 + k
            faces[len(faces)] = (a, a + 3, a + 4, a + 1)
    tangent = (-math.sin(sweep), math.cos(sweep), 0.0)
    nxt = 100

    def bulge(p, q, s):
        point = [p[i] + s * (q[i] - p[i]) + tangent[i] * 0.12 * math.sin(math.pi * s) for i in range(3)]
        return tuple(point)

    for k, steps in ((0, (1 / 3, 2 / 3)), (1, (0.5,))):
        fid = (cols - 1) * 2 + k
        a, b, c, d = faces[fid]
        extra = []
        for s in steps:
            verts[nxt] = bulge(verts[b], verts[c], s)
            extra.append(nxt)
            nxt += 1
        faces[fid] = (a, b, *extra, c, d)
    return verts, faces


def _stretches(verts, faces, uv):
    return [face_stretch([verts[v] for v in face], [uv[(fid, v)] for v in face]) for fid, face in faces.items()]


def _area(pts):
    return 0.5 * sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(pts, pts[1:] + pts[:1]))


def _no_fold(strip, uv):
    return folded_faces(strip, uv) == 0 and all(_area([uv[(fid, v)] for v in f]) > 0.0 for fid, f in strip.faces.items())


def _corners(strip):
    return {strip.near[0], strip.near[-1], strip.far[0], strip.far[-1]}


# --- a. a rounded end ---------------------------------------------------------------------------------------

def test_a_rounded_l_arc_end_is_read_and_laid_out_without_a_fold():
    verts, faces = _rounded_l_arc()
    assert sum(1 for v in {v for f in faces.values() for v in f}
               if sum(v in f for f in faces.values()) == 1) == 7        # boundary vertices used by one face
    strip = strip_from_faces(verts, faces)
    assert len(strip.faces) == len(faces)
    assert _corners(strip) == {0, 2, 24, 26}                          # the rounded end's two extremes, the far end's two
    for t in (0.0, 0.5, 1.0):
        uv = balanced_uvs(strip, "FREE", "BOTH", t)
        assert folded_faces(strip, uv) == 0
        assert len(uv) == sum(len(f) for f in faces.values())


# --- b. the corner rule on a 3 x 6 grid ---------------------------------------------------------------------

COLS, ROWS = 6, 3


def _vid(i, j):
    return i + j * 100


def _cells(cells, width=1.0, height=1.0):
    """A flat patch of the unit cells ``cells`` ((i, j) pairs) in z = 0, one quad each, counter-clockwise from +z;
    vertex (i, j) has the id i + 100 j; the face of cell (i, j) has the id i + 100 j too."""
    verts, faces = {}, {}
    for i, j in sorted(cells, key=lambda c: (c[1], c[0])):
        quad = (_vid(i, j), _vid(i + 1, j), _vid(i + 1, j + 1), _vid(i, j + 1))
        for v in quad:
            verts[v] = ((v % 100) * width, (v // 100) * height, 0.0)
        faces[_vid(i, j)] = quad
    return verts, faces


def _grid_3x6():
    return _cells({(i, j) for i in range(COLS) for j in range(ROWS)})


def _split_edge(verts, faces, fid, a, b, at=0.5):
    """An extra vertex in line on the edge a -> b of face ``fid``, between those two corners."""
    face = faces[fid]
    k = face.index(a)
    assert face[(k + 1) % len(face)] == b
    m = max(verts) + 1
    verts[m] = tuple(verts[a][n] + at * (verts[b][n] - verts[a][n]) for n in range(3))
    faces[fid] = (*face[:k + 1], m, *face[k + 1:]) if k + 1 < len(face) else (*face, m)
    return m


def _union(faces, fids, new_id):
    """The faces ``fids`` (edge-connected, one boundary loop) replaced by one n-gon: the directed edges that no
    other of them runs back along, chained."""
    edges = {}
    for fid in fids:
        face = faces.pop(fid)
        for a, b in zip(face, face[1:] + face[:1]):
            edges[(a, b)] = True
    edges = {(a, b): True for (a, b) in edges if (b, a) not in edges}
    nxt = {a: b for a, b in edges}  # noqa: C416
    start = min(nxt)
    loop = [start]
    while nxt[loop[-1]] != start:
        loop.append(nxt[loop[-1]])
    faces[new_id] = tuple(loop)
    return faces[new_id]


TRUE_CORNERS = {_vid(0, 0), _vid(COLS, 0), _vid(0, ROWS), _vid(COLS, ROWS)}


def _check_corner_case(verts, faces):
    strip = strip_from_faces(verts, faces)
    assert _corners(strip) == TRUE_CORNERS
    assert len(strip.faces) == len(faces)
    for t in (0.0, 0.5, 1.0):
        assert _no_fold(strip, balanced_uvs(strip, "FREE", "BOTH", t))
    return strip


@pytest.mark.parametrize("corner", [(0, 0), (COLS - 1, 0), (0, ROWS - 1), (COLS - 1, ROWS - 1)])
def test_a_corner_quad_with_an_extra_vertex_in_line_on_its_rail_edge(corner):
    verts, faces = _grid_3x6()
    i, j = corner
    fid = _vid(i, j)
    quad = faces[fid]
    a, b = (quad[0], quad[1]) if j == 0 else (quad[2], quad[3])      # its boundary edge along the long side
    _split_edge(verts, faces, fid, a, b)
    _check_corner_case(verts, faces)


@pytest.mark.parametrize("corner", [(0, 0), (COLS - 1, 0), (0, ROWS - 1), (COLS - 1, ROWS - 1)])
def test_a_corner_quad_with_an_extra_vertex_in_line_on_its_end_edge(corner):
    verts, faces = _grid_3x6()
    i, j = corner
    fid = _vid(i, j)
    quad = faces[fid]
    a, b = (quad[3], quad[0]) if i == 0 else (quad[1], quad[2])      # its boundary edge along the short side
    _split_edge(verts, faces, fid, a, b)
    _check_corner_case(verts, faces)


@pytest.mark.parametrize("rows", [(0, 1, 2), (0, 1), (1, 2)])
def test_one_ngon_spanning_the_end(rows):
    verts, faces = _grid_3x6()
    _union(faces, [_vid(COLS - 1, j) for j in rows], 999)           # 8-gon over all three rows, else a 6-gon
    if len(rows) == 3:
        assert len(faces[999]) == 8
    _check_corner_case(verts, faces)


def test_a_hexagon_inside_two_quads_merged():
    verts, faces = _grid_3x6()
    _union(faces, [_vid(2, 1), _vid(3, 1)], 999)
    assert len(faces[999]) == 6
    _check_corner_case(verts, faces)


def _plus():
    """A centre block of 2 x 2 cells with four arms 3 cells long: left and right ones 2 wide, the lower 2 wide, the
    upper 1 wide."""
    cells = {(i, j) for i in range(3, 5) for j in range(3, 5)}
    cells |= {(i, j) for i in range(3) for j in range(3, 5)} | {(i, j) for i in range(5, 8) for j in range(3, 5)}
    cells |= {(i, j) for i in range(3, 5) for j in range(3)} | {(3, j) for j in range(5, 8)}
    return _cells(cells)


def _t_shape():
    """A bar 8 cells long and 2 wide with a stem 2 wide and 3 long hanging from its middle."""
    cells = {(i, j) for i in range(8) for j in range(3, 5)} | {(i, j) for i in range(3, 5) for j in range(3)}
    return _cells(cells)


@pytest.mark.parametrize("make", [_plus, _t_shape])
def test_a_plus_and_a_t_shaped_patch_are_no_strips(make):
    verts, faces = make()
    with pytest.raises(ValueError, match="corners"):
        strip_from_faces(verts, faces)


# --- c. a forked L ledge with a slit ------------------------------------------------------------------------

FORK_COLS, FORK_AT = 8, 4


def _forked_l(wall_apart=False):
    """An L strip along x: a ledge two faces across (rings 0, 1, 2 at y = 0, 0.5, 1 in z = 0) and a wall hanging
    from its far edge (ring 3 at z = -0.4); vertex (ring k, column x) is 100 k + x. From column ``FORK_AT`` on
    the ledge splits along its middle ring into two arms that are not joined: the upper arm's copies of the
    ring's vertices are 1000 + x (the same positions, so the slit runs between two vertices at each place). With
    ``wall_apart`` the wall splits off its ledge too (copies 2000 + x). Faces: lower arm x, upper arm 100 + x,
    wall 200 + x."""
    profile = [(0.0, 0.0), (0.5, 0.0), (1.0, 0.0), (1.0, -0.4)]
    verts = {100 * k + x: (float(x), y, z) for k, (y, z) in enumerate(profile) for x in range(FORK_COLS + 1)}

    def upper(x):
        return 1000 + x if x > FORK_AT else 100 + x

    def wall(x):
        return 2000 + x if wall_apart and x > FORK_AT else 200 + x

    for x in range(FORK_AT + 1, FORK_COLS + 1):
        verts[1000 + x] = verts[100 + x]
        if wall_apart:
            verts[2000 + x] = verts[200 + x]
    faces = {}
    for x in range(FORK_COLS):
        faces[x] = (x, x + 1, 101 + x, 100 + x)
        faces[100 + x] = (upper(x), upper(x + 1), 201 + x, 200 + x)
        faces[200 + x] = (wall(x), wall(x + 1), 301 + x, 300 + x)
    return verts, faces


LOWER = set(range(FORK_COLS))
UPPER = {100 + x for x in range(FORK_COLS)}
WALL = {200 + x for x in range(FORK_COLS)}


def test_a_forked_l_ledge_is_refused_as_a_strip_and_cut_automatically_into_strips():
    verts, faces = _forked_l()
    with pytest.raises(ValueError, match="not a strip"):
        strip_from_faces(verts, faces)
    split = split_island(verts, faces)
    assert split.automatic and len(split.parts) == 2
    assert sorted(fid for part in split.parts for fid in part) == sorted(faces)
    assert {frozenset(part) for part in split.parts} == {frozenset(LOWER), frozenset(UPPER | WALL)}
    for part in split.parts:
        strip_from_faces(verts, part)                       # each part is a strip


@pytest.mark.parametrize(("seed", "main"), [(3, LOWER), (FORK_COLS - 1, LOWER), (100 + 6, UPPER | WALL),
                                            (100 + 1, UPPER | WALL), (200 + 6, UPPER | WALL)])
def test_the_seed_face_picks_the_main_part_of_a_forked_ledge(seed, main):
    verts, faces = _forked_l()
    split = split_island(verts, faces, seed=seed)
    assert set(split.parts[0]) == main and seed in split.parts[0]
    assert split.entries[0] is None and split.entries[1] is not None
    for part in split.parts:
        strip_from_faces(verts, part, seed=seed if seed in part else None)


def test_a_ledge_and_a_wall_that_both_split_off_make_three_arms():
    verts, faces = _forked_l(wall_apart=True)
    with pytest.raises(ValueError, match="not a strip"):
        strip_from_faces(verts, faces)
    split = split_island(verts, faces, seed=3)
    assert split.automatic and len(split.parts) == 3
    assert {frozenset(part) for part in split.parts} == {frozenset(LOWER), frozenset(UPPER), frozenset(WALL)}
    assert set(split.parts[0]) == LOWER                     # the seed's arm leads
    for part in split.parts:
        strip_from_faces(verts, part)


# --- d. a hand-made cut, each part laid out -----------------------------------------------------------------

def _laid(verts, part):
    strip = strip_from_faces(verts, part)
    uv = balanced_uvs(strip, "BOTH", "BOTH", 0.5)
    length, height = balance.balanced_extent(strip, "BOTH", "BOTH", 0.5)
    return strip, uv, length, height


def test_an_automatic_junction_cut_taken_back_is_not_cut_again():
    # a T of four cells: cut automatically at its junction; that cut skipped, another one is taken or none
    verts = {y * 4 + x: (float(x), float(y), 0.0) for y in range(3) for x in range(4)}
    cells = [(0, 0), (1, 0), (2, 0), (1, 1)]
    faces = {k: (y * 4 + x, y * 4 + x + 1, (y + 1) * 4 + x + 1, (y + 1) * 4 + x) for k, (x, y) in enumerate(cells)}
    split = split_island(verts, faces)
    assert split.automatic and split.auto_cuts and split.auto_cuts == split.cuts
    try:
        again = split_island(verts, faces, skip=split.auto_cuts)
    except ValueError:
        return                                              # no other cut: the island cannot be read
    assert not set(again.auto_cuts) & set(split.auto_cuts)
    hand = split_island(verts, faces, cuts=sorted(split.auto_cuts))
    assert not hand.automatic and hand.auto_cuts == set()   # a hand-made cut is no automatic one


def test_an_l_arc_cut_across_the_middle_is_two_parts_each_its_own_strip():
    # each cut part is laid out as its own strip (decided 2026-11-24): no part is joined to another
    verts, faces, rings = _l_arc()
    split = split_island(verts, faces, cuts=[(rings[0][4], rings[1][4])])
    assert not split.automatic and len(split.parts) == 2
    assert split.entries[0] is None and split.entries[1] is not None
    assert split.exits[0] is not None and split.exits[1] is None
    cut = {rings[k][4] for k in range(3)}
    assert set(split.entries[1]) == cut == set(split.exits[0])
    for part in split.parts:
        strip, uv, length, height = _laid(verts, part)
        assert {k[0] for k in uv} == set(part)
        assert min(p[0] for p in uv.values()) == pytest.approx(0.0, abs=1e-9)
        for fid, face in part.items():
            assert _area([uv[(fid, v)] for v in face]) > 0.0


# --- e. the slider ------------------------------------------------------------------------------------------

def _moved(a, b):
    return max(math.dist(a[k], b[k]) for k in a)


@pytest.mark.parametrize("make", [lambda: _flat_arc(), lambda: _l_arc()[:2]])
def test_the_slider_gives_a_different_layout_at_every_stop(make):
    verts, faces = make()
    strip = strip_from_faces(verts, faces)
    uvs = {t: balanced_uvs(strip, "FREE", "BOTH", t) for t in (0.0, 0.5, 1.0)}
    for a, b in ((0.0, 0.5), (0.5, 1.0), (0.0, 1.0)):
        assert _moved(uvs[a], uvs[b]) > 1e-6, (a, b)


@pytest.mark.parametrize("rails", ["NEAR", "FAR"])
@pytest.mark.parametrize("t", [0.0, 0.5, 1.0])
def test_one_free_rail_is_never_worse_than_both_rails_straight(rails, t):
    verts, faces = _flat_arc()
    strip = strip_from_faces(verts, faces)
    both = max(_stretches(strip.verts, strip.faces, balanced_uvs(strip, "FREE", "BOTH", t)))
    one = max(_stretches(strip.verts, strip.faces, balanced_uvs(strip, "FREE", rails, t)))
    assert one <= both + 1e-9
    # (the old bound "below 1.011 at 0" held under the averaged measure; the honest one, every corner triangle
    # counted, finds this arc's straight near rail costs about 1.17 whatever the far rail does)


# --- f. fans ------------------------------------------------------------------------------------------------

def _bent(p):
    """A non-affine map of the plane."""
    return (p[0] + 0.2 * p[1] * p[1], p[1] + 0.1 * p[0] * p[0])


def _rotations(items):
    return [items[k:] + items[:k] for k in range(len(items))]


@pytest.mark.parametrize("points", [
    [(0.0, 0.0, 0.0), (2.0, 0.1, 0.0), (1.7, 1.3, 0.0), (-0.2, 1.0, 0.0)],
    [(math.cos(a), 0.7 * math.sin(a), 0.0) for a in (0.0, 1.0, 2.2, 3.1, 4.4, 5.3)],
    [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (2.0, 0.1, 0.0), (2.2, 1.2, 0.0), (1.0, 1.0, 0.0), (-0.1, 0.9, 0.0)],
], ids=["quad", "hexagon", "hexagon with a vertex in line"])
def test_face_stretch_does_not_depend_on_which_corner_comes_first(points):
    uvs = [_bent(p) for p in points]
    first = face_stretch(points, uvs)
    assert first > 1.0 + 1e-6                                   # the map really stretches it
    for pts, uv in zip(_rotations(points), _rotations(uvs)):
        assert face_stretch(pts, uv) == pytest.approx(first, abs=1e-9)


def test_a_quad_with_a_collapsed_edge_is_measured_as_the_triangle():
    tri = [(0.0, 0.0, 0.0), (2.0, 0.1, 0.0), (1.7, 1.3, 0.0)]
    uv = [_bent(p) for p in tri]
    expect = face_stretch(tri, uv)
    assert expect > 1.0 + 1e-6
    for k in range(3):
        quad = tri[:k + 1] + [tri[k]] + tri[k + 1:]            # corner k repeated: an edge of length 0
        quad_uv = uv[:k + 1] + [uv[k]] + uv[k + 1:]
        assert face_stretch(quad, quad_uv) == pytest.approx(expect, abs=1e-9)


def test_a_strip_with_an_ngon_is_laid_out_the_same_whichever_corner_of_it_comes_first():
    layouts = []
    for turn in range(6):
        verts, faces = _grid_3x6()
        _union(faces, [_vid(2, 1), _vid(3, 1)], 999)
        faces[999] = tuple(_rotations(list(faces[999]))[turn])
        balance.clear_caches()
        strip = strip_from_faces(verts, faces)
        layouts.append(balanced_uvs(strip, "FREE", "BOTH", 0.3))
    for other in layouts[1:]:
        assert other.keys() == layouts[0].keys()
        assert _moved(other, layouts[0]) < 1e-9


# --- g. balance_value ---------------------------------------------------------------------------------------

@pytest.mark.parametrize(("given", "value"), [(0.3, 0.3), (-1, 0.0), (2, 1.0), ("EVEN_TEXEL", 1.0),
                                              ("LEAST_STRETCH", 0.0), (0, 0.0), (1, 1.0)])
def test_balance_value_reads_numbers_and_the_old_names(given, value):
    assert balance_value(given) == value


@pytest.mark.parametrize("given", ["ARAP", True, None, float("nan")])
def test_balance_value_refuses_anything_else(given):
    with pytest.raises(ValueError):
        balance_value(given)


# --- h. live mode -------------------------------------------------------------------------------------------

def test_a_live_solve_is_capped_and_refined_to_the_cold_one():
    verts, faces, _rings = _l_arc()
    strip = strip_from_faces(verts, faces)
    with balance.live(2):
        live = balanced_uvs(strip, "FREE", "BOTH", 0.3)
        assert folded_faces(strip, live) == 0
        assert balance.pending() >= 1
    while not balance.refine(0.0005):         # in slices: one uninterrupted descent kept between calls
        pass
    assert balance.pending() == 0
    refined = balanced_uvs(strip, "FREE", "BOTH", 0.3)
    balance.clear_caches()
    cold = balanced_uvs(strip, "FREE", "BOTH", 0.3)
    assert refined.keys() == cold.keys() and _moved(refined, cold) < 1e-9     # the confirmed UVs are the cold ones


# --- validation round: the honest measure, disc refusal, tears within the limit, cut parts along the strip ---

def test_a_quad_laid_as_a_triangle_is_fully_stretched():
    square = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (1.0, 1.0, 0.0), (0.0, 1.0, 0.0)]
    assert face_stretch(square, [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]) == pytest.approx(1.0)
    as_triangle = [(0.0, 0.0), (0.5, 0.0), (1.0, 0.0), (0.5, 1.0)]       # three corners on one line
    assert face_stretch(square, as_triangle) == math.inf
    nearly = [(0.0, 0.0), (1.0, 0.0), (1.0, 0.004), (0.0, 1.0)]          # one UV edge collapsed to 0.004
    assert face_stretch(square, nearly) > 100.0


def test_the_fold_guard_refuses_a_collapsed_real_corner():
    flat = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]
    assert balance._folds([(0.0, 0.0), (0.5, 0.0), (1.0, 0.0), (0.5, 1.0)], flat)
    assert not balance._folds([(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)], flat)


def _octagon_disc():
    n = 8
    verts = {i: (math.cos(2 * math.pi * i / n), math.sin(2 * math.pi * i / n), 0.0) for i in range(n)}
    verts.update({n + i: (0.5 * math.cos(2 * math.pi * i / n), 0.5 * math.sin(2 * math.pi * i / n), 0.0)
                  for i in range(n)})
    faces = {i: (i, (i + 1) % n, n + (i + 1) % n, n + i) for i in range(n)}
    faces[n] = tuple(n + i for i in range(n))
    return verts, faces


def test_a_disc_cannot_be_helped_and_a_branch_can():
    from utils.uv_stripe_split_core import can_be_helped
    verts, faces = _octagon_disc()
    assert not can_be_helped(verts, faces)
    verts, faces = _forked_l()[:2]
    assert can_be_helped(verts, faces)


def test_tears_keep_every_face_within_the_limit_with_as_few_pieces_as_that_allows():
    from dataclasses import replace

    from utils.uv_stripe_auto_core import auto_cuts
    verts, faces = _flat_arc(cols=8, sweep=math.pi)
    strip = replace(strip_from_faces(verts, faces), layout="TRUE")
    strict = auto_cuts(strip, (), (), ("TRUE",))
    loose = auto_cuts(strip, (), (), ("TRUE",), 1.25)
    assert len(loose) <= len(strict)
    assert set(loose) <= set(range(len(strip.rungs)))


def test_a_strip_one_layout_keeps_within_the_limit_fits_whole():
    from utils.uv_stripe_auto_core import Shape, fits_whole
    verts, faces = _flat_arc(cols=8, sweep=math.radians(20))       # a gentle arc
    strip = strip_from_faces(verts, faces)
    assert fits_whole(strip, Shape(), 1.25, 0.5)
    verts, faces = _flat_arc(cols=8, sweep=math.radians(270))      # a tight one: straight it stretches
    strip = strip_from_faces(verts, faces)
    assert not fits_whole(strip, Shape(), 1.05, 0.5)


def test_a_part_cut_off_near_an_end_runs_along_the_strip():
    from utils.uv_stripe_split_core import along_cuts
    verts, faces, _rings = _l_arc(cols=8)
    inner = [(1 * 9 + 1, 2 * 9 + 1)]           # the fold vertex of column 1 to the wall foot: cuts column 0 off
    split = split_island(verts, faces, inner)
    assert len(split.parts) == 2
    for k, part in enumerate(split.parts):
        strip = strip_from_faces(verts, part)
        corners = along_cuts(verts, part, strip, (split.entries[k], split.exits[k]))
        cuts = [c for c in (split.entries[k], split.exits[k]) if c]
        if corners is not None:
            strip = strip_from_faces(verts, part, corners=corners, end=frozenset().union(*cuts))
        ends = ({strip.near[0], *strip.sides[0], strip.far[0]}, {strip.near[-1], *strip.sides[1], strip.far[-1]})
        assert any(len(set(c) & end) >= 2 for c in cuts for end in ends), k


def test_a_chamfered_rectangle_with_sides_longer_than_its_chamfers_gets_help():
    from utils.uv_stripe_split_core import can_be_helped

    def chamfered(nx, ny):
        idx = lambda i, j: j * (nx + 1) + i     # noqa: E731
        verts = {idx(i, j): (float(i), float(j), 0.0) for j in range(ny + 1) for i in range(nx + 1)}
        faces = {}
        for j in range(ny):
            for i in range(nx):
                a, b, c, d = idx(i, j), idx(i + 1, j), idx(i + 1, j + 1), idx(i, j + 1)
                corner = {(0, 0): (b, c, d), (nx - 1, 0): (a, c, d), (nx - 1, ny - 1): (a, b, d), (0, ny - 1): (a, b, c)}
                faces[len(faces)] = corner.get((i, j), (a, b, c, d))
        used = {v for f in faces.values() for v in f}
        return {v: verts[v] for v in used}, faces

    assert can_be_helped(*chamfered(4, 4)) and can_be_helped(*chamfered(12, 4))
    assert not can_be_helped(*_octagon_disc())


# --- hand cuts: a line of cut edges is cut as it is, a lone edge along its cross path -------------------------

def _grid(cols, rows):
    verts = {y * (cols + 1) + x: (float(x), float(y), 0.0) for y in range(rows + 1) for x in range(cols + 1)}
    faces = {y * cols + x: (y * (cols + 1) + x, y * (cols + 1) + x + 1, (y + 1) * (cols + 1) + x + 1,
                            (y + 1) * (cols + 1) + x) for y in range(rows) for x in range(cols)}
    return verts, faces


def test_a_lone_hand_cut_edge_cuts_along_its_cross_path_and_a_line_of_them_as_it_is():
    verts, faces = _grid(8, 3)                     # vertex (x, y) is y * 9 + x
    lone = split_island(verts, faces, [(13, 22)])  # one edge across at x = 4: its whole cross path is cut
    assert len(lone.parts) == 2
    # a lengthwise line between rows 1 and 2 from x = 4 to the far end, its end on a cut across at x = 4: the line
    # is cut as given (it does not run on to the near end), so it splits only the part beyond the cut across
    across = [(4, 13), (13, 22), (22, 31)]
    along = [(22, 23), (23, 24), (24, 25), (25, 26)]
    split = split_island(verts, faces, across + along)
    assert len(split.parts) == 3, [sorted(p) for p in split.parts]
    sizes = sorted(len(p) for p in split.parts)
    assert sizes == [4, 8, 12], sizes
