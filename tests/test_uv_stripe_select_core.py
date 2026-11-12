import math
import random

import pytest

from utils.uv_stripe_core import place_fit, strip_length, stripe_uvs
from utils.uv_stripe_select_core import bend_cuts, face_islands, split_strip, strip_from_faces

W = 10  # grid row width in vertices


def grid(cells, z=0.0):
    """Unit cells (x, y) of a flat grid, faces counter-clockwise seen from +Z, ids from position."""
    verts, faces = {}, {}
    for fid, (x, y) in enumerate(cells):
        ids = []
        for cx, cy in ((x, y), (x + 1, y), (x + 1, y + 1), (x, y + 1)):
            vid = cy * W + cx
            verts[vid] = (float(cx), float(cy), z)
            ids.append(vid)
        faces[fid] = tuple(ids)
    return verts, faces


def layout(verts, faces):
    strip = strip_from_faces(verts, faces)
    return strip, stripe_uvs(strip)


def areas(faces, uv):
    out = {}
    for fid, face in faces.items():
        pts = [uv[(fid, v)] for v in face]
        out[fid] = 0.5 * sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(pts, pts[1:] + pts[:1]))
    return out


def by_position(verts, faces, uv):
    """UVs keyed by geometry only: (the face's corner positions, the corner's position)."""
    out = {}
    for fid, face in faces.items():
        fkey = frozenset(tuple(round(c, 6) for c in verts[v]) for v in face)
        for v in face:
            out[(fkey, tuple(round(c, 6) for c in verts[v]))] = uv[(fid, v)]
    return out


def close(a, b, tol=1e-6):
    return all(abs(x - y) <= tol for x, y in zip(a, b))


def rows_only(strip, uv):
    return all(abs(v) < 1e-9 or abs(v - strip.height) < 1e-9 for (_u, v) in uv.values())


def relabel(verts, faces, seed, reverse_faces=False):
    rng = random.Random(seed)  # noqa: S311 - a seeded fixture, not security
    vids = list(verts)
    new = vids[:]
    rng.shuffle(new)
    vmap = {a: b + 1000 for a, b in zip(vids, new)}
    fids = sorted(faces)
    order = fids[::-1] if reverse_faces else rng.sample(fids, len(fids))
    fmap = {a: 500 + i for i, a in enumerate(order)}
    nverts = {vmap[v]: p for v, p in verts.items()}
    nfaces = {}
    for fid, face in faces.items():
        k = rng.randrange(len(face))
        rot = face[k:] + face[:k]
        nfaces[fmap[fid]] = tuple(vmap[v] for v in rot)
    return nverts, nfaces


# --- open chains -----------------------------------------------------------------

def test_straight_chain_is_its_own_rectangle():
    verts, faces = grid([(x, 0) for x in range(4)])
    strip, uv = layout(verts, faces)
    assert not strip.closed and strip.height == pytest.approx(1.0)
    assert strip_length(strip) == pytest.approx(4.0)
    assert rows_only(strip, uv)
    for (fid, vid), co in uv.items():
        assert close(co, verts[vid][:2])     # u = x (toward +X), v = y, every face a unit square
    assert all(a > 0 for a in areas(faces, uv).values())


def test_chain_direction_follows_the_dominant_axis():
    verts, faces = grid([(x, 0) for x in range(4)])
    flipped = {v: (-p[0], p[1], p[2]) for v, p in verts.items()}     # now runs toward -X
    faces_cw = {f: face[::-1] for f, face in faces.items()}          # keep normals up
    strip, uv = layout(flipped, faces_cw)
    for (_fid, vid), (u, _v) in uv.items():
        assert u == pytest.approx(flipped[vid][0] + 4.0)             # smallest x at u = 0


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_chain_is_independent_of_ids(seed):
    verts, faces = grid([(x, 0) for x in range(5)])
    ref = by_position(verts, faces, layout(verts, faces)[1])
    for rev in (False, True):
        nv, nf = relabel(verts, faces, seed, reverse_faces=rev)
        got = by_position(nv, nf, layout(nv, nf)[1])
        assert got.keys() == ref.keys()
        assert all(close(got[k], ref[k]) for k in ref)


def test_l_bend_rows_stay_straight():
    cells = [(0, 0), (1, 0), (2, 0), (2, 1), (2, 2)]
    verts, faces = grid(cells)
    strip, uv = layout(verts, faces)
    assert rows_only(strip, uv)
    assert all(a > 0 for a in areas(faces, uv).values())
    us = [u for u, _v in uv.values()]
    assert min(us) == pytest.approx(0.0) and max(us) == pytest.approx(strip_length(strip))


def test_chain_with_triangle_ends():
    verts = {0: (-1.0, 0.5, 0.0), 9: (4.0, 0.5, 0.0)}
    for x in range(4):
        verts[1 + x] = (float(x), 0.0, 0.0)
        verts[5 + x] = (float(x), 1.0, 0.0)
    faces = {0: (0, 1, 5)}
    for x in range(3):
        faces[1 + x] = (1 + x, 2 + x, 6 + x, 5 + x)
    faces[4] = (4, 9, 8)
    strip, uv = layout(verts, faces)
    assert strip.near[0] == strip.far[0] == 0 and strip.near[-1] == strip.far[-1] == 9
    assert rows_only(strip, uv)
    assert all(a > 0 for a in areas(faces, uv).values())
    apex = {vid: u for (_f, vid), (u, _v) in uv.items() if vid in (0, 9)}
    assert apex[0] == pytest.approx(0.0) and apex[9] == pytest.approx(strip_length(strip))


def test_chain_of_triangles():
    b = {i: (float(i), 0.0, 0.0) for i in range(4)}
    t = {10 + i: (i + 0.5, 1.0, 0.0) for i in range(3)}
    verts = b | t
    faces = {0: (0, 1, 10), 1: (1, 11, 10), 2: (1, 2, 11), 3: (2, 12, 11), 4: (2, 3, 12)}
    strip, uv = layout(verts, faces)
    assert rows_only(strip, uv)
    assert all(a > 0 for a in areas(faces, uv).values())
    for seed in (4, 5):
        nv, nf = relabel(verts, faces, seed)
        got = by_position(nv, nf, layout(nv, nf)[1])
        ref = by_position(verts, faces, uv)
        assert all(close(got[k], ref[k]) for k in ref)


def test_single_quad_rows_are_the_long_edges():
    verts = {0: (0.0, 0.0, 0.0), 1: (2.0, 0.0, 0.0), 2: (2.0, 1.0, 0.0), 3: (0.0, 1.0, 0.0)}
    strip, uv = layout(verts, {7: (0, 1, 2, 3)})
    assert strip.height == pytest.approx(1.0) and strip_length(strip) == pytest.approx(2.0)
    for (_f, vid), co in uv.items():
        assert close(co, verts[vid][:2])


def test_grid_patch_two_faces_wide():
    cells = [(x, y) for y in range(2) for x in range(4)]
    verts, faces = grid(cells)
    strip, uv = layout(verts, faces)
    assert strip.height == pytest.approx(2.0) and strip_length(strip) == pytest.approx(4.0)
    for (_f, vid), co in uv.items():
        assert close(co, verts[vid][:2], 1e-5)
    nv, nf = relabel(verts, faces, 9)
    got = by_position(nv, nf, layout(nv, nf)[1])
    ref = by_position(verts, faces, uv)
    assert all(close(got[k], ref[k], 1e-5) for k in ref)


# --- closed chains ---------------------------------------------------------------

def band(n, tris=False, r=1.0):
    """A cylinder band round Z, z = 0..1, normals outward; quads or each quad split in two triangles."""
    verts, faces = {}, {}
    for i in range(n):
        a = 2 * math.pi * i / n
        verts[i] = (r * math.cos(a), r * math.sin(a), 0.0)
        verts[n + i] = (r * math.cos(a), r * math.sin(a), 1.0)
    for i in range(n):
        j = (i + 1) % n
        if tris:
            faces[2 * i] = (i, j, n + j)
            faces[2 * i + 1] = (i, n + j, n + i)
        else:
            faces[i] = (i, j, n + j, n + i)
    return verts, faces


def seam_count(uv, length):
    at = {}
    for (_f, vid), (u, _v) in uv.items():
        at.setdefault(vid, set()).add(round(u / length, 6) % 1.0 if abs(u - length) > 1e-9 else 1.0)
    return sum(1 for us in at.values() if 0.0 in us and 1.0 in us)


@pytest.mark.parametrize("tris", [False, True])
def test_closed_ring(tris):
    verts, faces = band(8, tris)
    strip, uv = layout(verts, faces)
    length = strip_length(strip)
    assert strip.closed
    assert rows_only(strip, uv)
    assert all(abs(v) < 1e-9 for (_f, vid), (_u, v) in uv.items() if verts[vid][2] == 0.0)   # lower loop is near
    us = [u for u, _v in uv.values()]
    assert min(us) == pytest.approx(0.0) and max(us) == pytest.approx(length)
    assert seam_count(uv, length) == 2           # one seam rung: its two vertices
    assert all(a > 0 for a in areas(faces, uv).values())
    for seed in (1, 2):
        nv, nf = relabel(verts, faces, seed)
        got = by_position(nv, nf, layout(nv, nf)[1])
        ref = by_position(verts, faces, uv)
        assert all(close(got[k], ref[k]) for k in ref)


def test_flat_ring_takes_the_outer_loop_as_near():
    cells = [(x, y) for x in range(3) for y in range(3) if (x, y) != (1, 1)]
    verts, faces = grid(cells)
    strip, uv = layout(verts, faces)
    assert strip.closed
    outer = {v for v, p in verts.items() if p[0] in (0.0, 3.0) or p[1] in (0.0, 3.0)}
    assert set(strip.near) == outer
    assert rows_only(strip, uv)
    assert all(a > 0 for a in areas(faces, uv).values())


# --- islands and rejections ------------------------------------------------------

def test_face_islands_split_and_order():
    verts, faces = grid([(5, 5), (0, 0), (1, 0), (6, 5)])
    islands = face_islands(faces)
    assert [sorted(i) for i in islands] == [[0, 3], [1, 2]]


@pytest.mark.parametrize("cells", [
    [(0, 0), (1, 0), (2, 0), (1, 1)],                                        # T / branching
    [(0, 0), (1, 0), (2, 0), (2, 1), (0, 1), (0, 2), (1, 2)],                # pinched at (2, 2)
])
def test_rejected_shapes(cells):
    verts, faces = grid(cells)
    with pytest.raises(ValueError, match="not a strip"):
        strip_from_faces(verts, faces)


def test_single_triangle_is_rejected():
    verts = {0: (0.0, 0.0, 0.0), 1: (1.0, 0.0, 0.0), 2: (0.0, 1.0, 0.0)}
    with pytest.raises(ValueError, match="not a strip"):
        strip_from_faces(verts, {0: (0, 1, 2)})


# --- triangulated quad strips ----------------------------------------------------

def arc_quads(n=12, r1=2.0, r2=2.4, sweep=math.pi * 0.75, straight=False):
    """A quad strip, vertices 2i inner / 2i + 1 outer: bent round Z or straight along X."""
    verts = {}
    for i in range(n + 1):
        if straight:
            verts[2 * i], verts[2 * i + 1] = (float(i), 0.0, 0.0), (float(i), 0.4, 0.0)
        else:
            a = sweep * i / n
            verts[2 * i] = (r1 * math.cos(a), r1 * math.sin(a), 0.0)
            verts[2 * i + 1] = (r2 * math.cos(a), r2 * math.sin(a), 0.0)
    quads = [(2 * i, 2 * i + 2, 2 * i + 3, 2 * i + 1) for i in range(n)]
    return verts, quads


def triangulate(quads, pattern):
    """Split each quad (p0, p1, p2, p3) along p0-p2 ("a"), p1-p3 ("b") or alternating ("alt")."""
    faces = {}
    for i, (p0, p1, p2, p3) in enumerate(quads):
        diag = pattern if pattern != "alt" else "ab"[i % 2]
        if diag == "a":
            faces[2 * i], faces[2 * i + 1] = (p0, p1, p2), (p0, p2, p3)
        else:
            faces[2 * i], faces[2 * i + 1] = (p0, p1, p3), (p1, p2, p3)
    return faces


def per_vertex(uv):
    out = {}
    for (_f, vid), co in uv.items():
        assert vid not in out or close(out[vid], co), "an open strip vertex has two UVs"
        out[vid] = co
    return out


@pytest.mark.parametrize("straight", [True, False])
@pytest.mark.parametrize("pattern", ["a", "b", "alt"])
def test_triangulated_strip_matches_its_quads(straight, pattern):
    verts, quads = arc_quads(straight=straight)
    ref = per_vertex(layout(verts, dict(enumerate(quads)))[1])
    faces = triangulate(quads, pattern)
    strip, uv = layout(verts, faces)
    got = per_vertex(uv)
    assert got.keys() == ref.keys()
    assert all(close(got[v], ref[v], 1e-6) for v in ref), {v: (got[v], ref[v]) for v in ref if not close(got[v], ref[v])}
    assert all(a > 0 for a in areas(faces, uv).values())


@pytest.mark.parametrize("pattern", ["a", "b", "alt"])
def test_triangulated_strip_is_independent_of_ids(pattern):
    verts, quads = arc_quads()
    faces = triangulate(quads, pattern)
    ref = by_position(verts, faces, layout(verts, faces)[1])
    for seed in (1, 2, 3):
        nv, nf = relabel(verts, faces, seed)
        got = by_position(nv, nf, layout(nv, nf)[1])
        assert all(close(got[k], ref[k]) for k in ref)


@pytest.mark.parametrize("diag", ["a", "b"])
def test_two_triangles_make_the_quad_rectangle(diag):
    verts = {0: (0.0, 0.0, 0.0), 1: (2.0, 0.0, 0.0), 2: (2.0, 1.0, 0.0), 3: (0.0, 1.0, 0.0)}
    faces = triangulate([(0, 1, 2, 3)], diag)
    strip, uv = layout(verts, faces)
    assert strip.height == pytest.approx(1.0) and strip_length(strip) == pytest.approx(2.0)
    for (_f, vid), co in uv.items():
        assert close(co, verts[vid][:2])


def test_pointed_tip_keeps_the_apex():
    verts = {0: (-1.0, 0.5, 0.0), 1: (0.0, 0.0, 0.0), 2: (1.0, 0.0, 0.0), 3: (0.0, 1.0, 0.0), 4: (1.0, 1.0, 0.0)}
    faces = {0: (0, 1, 3), 1: (1, 2, 4, 3)}
    strip = strip_from_faces(verts, faces)
    assert strip.near[0] == strip.far[0] == 0 or strip.near[-1] == strip.far[-1] == 0


# --- straight cross edges, seams, splits -----------------------------------------

def polyline_strip(turns_deg, width=0.4, seg=1.0):
    """A flat quad strip along a polyline of unit segments turning by ``turns_deg`` at its inner joints.

    Vertex 2i is on the left of joint i, 2i + 1 on the right (mitred), faces wound counter-clockwise.
    """
    heading, pts, dirs = 0.0, [(0.0, 0.0)], []
    for k in range(len(turns_deg) + 1):
        if k:
            heading += math.radians(turns_deg[k - 1])
        dirs.append((math.cos(heading), math.sin(heading)))
        pts.append((pts[-1][0] + seg * dirs[-1][0], pts[-1][1] + seg * dirs[-1][1]))
    verts = {}
    for i, (x, y) in enumerate(pts):
        da, db = dirs[max(i - 1, 0)], dirs[min(i, len(dirs) - 1)]
        tx, ty = da[0] + db[0], da[1] + db[1]
        t = math.hypot(tx, ty)
        tx, ty = tx / t, ty / t
        nx, ny = -ty, tx
        scale = width / 2.0 / (nx * -da[1] + ny * da[0])     # mitre: offset lines stay width / 2 away
        verts[2 * i] = (x + nx * scale, y + ny * scale, 0.0)
        verts[2 * i + 1] = (x - nx * scale, y - ny * scale, 0.0)
    quads = [(2 * i + 1, 2 * i + 3, 2 * i + 2, 2 * i) for i in range(len(pts) - 1)]
    return verts, quads


def lean(uv, pairs):
    vals = per_vertex(uv)
    return max(abs(vals[a][0] - vals[b][0]) for a, b in pairs)


@pytest.mark.parametrize("pattern", [None, "a", "b", "alt"])
def test_straight_rungs_make_cross_edges_vertical(pattern):
    verts, quads = polyline_strip([0, 22, 0, 38])
    faces = dict(enumerate(quads)) if pattern is None else triangulate(quads, pattern)
    strip = strip_from_faces(verts, faces)
    cross = [(2 * i, 2 * i + 1) for i in range(6)]
    assert lean(stripe_uvs(strip), cross) > 0.05          # arc-length rows lean at the bends
    strip.layout = "STRAIGHT"
    uv = stripe_uvs(strip)
    assert lean(uv, cross) < 1e-9
    us = [u for u, _v in uv.values()]
    assert min(us) == pytest.approx(0.0) and max(us) == pytest.approx(strip_length(strip))
    assert all(a > 0 for a in areas(faces, uv).values())


def test_straight_rungs_on_a_quad_chain_give_rectangles():
    verts, quads = polyline_strip([0, 22, 0, 38])
    faces = dict(enumerate(quads))
    strip = strip_from_faces(verts, faces)
    strip.layout = "STRAIGHT"
    uv = stripe_uvs(strip)
    for fid, face in faces.items():
        us = sorted({round(uv[(fid, v)][0], 9) for v in face})
        vs = sorted({round(uv[(fid, v)][1], 9) for v in face})
        assert len(us) == 2 and len(vs) == 2              # an axis-aligned rectangle


def test_straight_rungs_equal_the_old_layout_when_rows_agree():
    verts, faces = grid([(x, 0) for x in range(4)])
    strip = strip_from_faces(verts, faces)
    old = stripe_uvs(strip)
    strip.layout = "STRAIGHT"
    new = stripe_uvs(strip)
    assert all(close(old[k], new[k], 1e-12) for k in old)


def jittered_band(n=8):
    """A band round Z whose top ring is unevenly spaced, so arc-length rows lean."""
    verts, faces = {}, {}
    for i in range(n):
        a = 2 * math.pi * i / n
        b = a + (0.25 if i % 2 else -0.1)
        verts[i] = (math.cos(a), math.sin(a), 0.0)
        verts[n + i] = (math.cos(b), math.sin(b), 1.0)
    for i in range(n):
        j = (i + 1) % n
        faces[i] = (i, j, n + j, n + i)
    return verts, faces


def test_closed_ring_straight_rungs_and_seam():
    verts, faces = jittered_band()
    cross = [(i, 8 + i) for i in range(8)]
    strip = strip_from_faces(verts, faces)

    def u_sets(uv, digits):
        at = {}
        for (_f, vid), (u, _v) in uv.items():
            at.setdefault(vid, set()).add(round(u, digits))
        return at

    at = u_sets(stripe_uvs(strip), 2)
    assert any(at[a] != at[b] for a, b in cross)          # arc-length rows lean
    strip.layout = "STRAIGHT"
    at = u_sets(stripe_uvs(strip), 9)
    for a, b in cross:
        assert at[a] == at[b]                              # every rung vertical, the seam rung on both ends
    for seam in [(3, 11), (11, 3), (6, 14)]:
        s = strip_from_faces(verts, faces, seam_edge=seam)
        assert s.seam == 0
        uv = stripe_uvs(s)
        length = strip_length(s)
        for v in seam:
            us = {round(u, 9) for (_f, vid), (u, _v) in uv.items() if vid == v}
            assert us == {0.0, round(length, 9)}


def test_seam_edge_that_is_not_a_rung_is_ignored():
    verts, faces = band(8)
    assert strip_from_faces(verts, faces, seam_edge=(0, 1)).seam is None


def test_open_chain_rungs_ascend_after_the_swap():
    verts, faces = grid([(x, 0) for x in range(4)])
    flipped = {v: (-p[0], p[1], p[2]) for v, p in verts.items()}
    for vs, fs in ((verts, faces), (flipped, {f: face[::-1] for f, face in faces.items()})):
        strip = strip_from_faces(vs, fs)
        assert len(strip.rungs) == 3
        assert all(a[0] < b[0] and a[1] < b[1] for a, b in zip(strip.rungs, strip.rungs[1:]))
        for i, j in strip.rungs:
            assert vs[strip.near[i]][0] == vs[strip.far[j]][0]      # each rung is a cross edge


def test_face_islands_with_cut_edges():
    verts, faces = grid([(x, 0) for x in range(4)])
    islands = face_islands(faces, frozenset({(2, W + 2)}))
    assert [sorted(i) for i in islands] == [[0, 1], [2, 3]]


def test_bend_cuts_at_sharp_bends():
    verts, quads = polyline_strip([0, 22, 0, 38])
    faces = dict(enumerate(quads))
    assert bend_cuts(verts, faces, math.radians(15)) == {(4, 5), (8, 9)}
    assert bend_cuts(verts, faces, math.radians(30)) == {(8, 9)}


def test_bend_cuts_l_bend_once():
    verts, faces = grid([(0, 0), (1, 0), (2, 0), (2, 1), (2, 2)])
    assert len(bend_cuts(verts, faces, math.radians(15))) == 1


def test_bend_cuts_ignore_folds_round_a_cylinder():
    verts, faces = band(16)
    part = {f: faces[f] for f in range(8)}               # half a band: folds across its cross edges only
    assert bend_cuts(verts, part, math.radians(5)) == set()


def test_bend_cuts_on_a_gradual_arc_are_periodic():
    verts, quads = arc_quads()                           # 12 steps of 11.25 degrees
    cuts = bend_cuts(verts, dict(enumerate(quads)), math.radians(15))
    assert cuts == {(2 * i, 2 * i + 1) for i in (2, 4, 6, 8, 10)}


def test_bend_cuts_ring_with_one_cut_gets_none():
    verts, faces = {}, {}
    for i in range(8):
        a = 2 * math.pi * i / 8
        verts[i] = (2 * math.cos(a), 2 * math.sin(a), 0.0)
        verts[8 + i] = (math.cos(a), math.sin(a), 0.0)
    for i in range(8):
        j = (i + 1) % 8
        faces[i] = (i, j, 8 + j, 8 + i)
    assert bend_cuts(verts, faces, math.radians(300)) == set()
    assert len(bend_cuts(verts, faces, math.radians(100))) == 2


def test_bend_cuts_of_a_non_chain_are_empty():
    verts, faces = grid([(x, y) for y in range(2) for x in range(4)])
    assert bend_cuts(verts, faces, math.radians(1)) == set()
    verts, faces = grid([(0, 0), (1, 0), (2, 0), (1, 1)])
    assert bend_cuts(verts, faces, math.radians(1)) == set()


def test_place_fit_groups_share_one_scale():
    maps = [{(0, 0): (4.0, 1.0)}, {(1, 1): (2.0, 1.0)}, {(2, 2): (1.0, 1.0)}]
    heights, lengths = [1.0, 1.0, 1.0], [4.0, 2.0, 1.0]
    out = place_fit(maps, heights, lengths, groups=[0, 0, 0])
    assert out[0][(0, 0)] == pytest.approx((1.0, 0.25))
    assert out[1][(1, 1)] == pytest.approx((0.5, 0.25 + 0.25 + 0.01))
    out = place_fit(maps, heights, lengths, groups=[0, 1, 1])     # strips 1 and 2 share 1 / 2
    assert out[1][(1, 1)] == pytest.approx((1.0, 0.25 + 0.01 + 0.5))
    assert out[2][(2, 2)] == pytest.approx((0.5, 0.25 + 0.01 + 0.5 + 0.01 + 0.5))
    assert place_fit(maps, heights, lengths) == place_fit(maps, heights, lengths, groups=[0, 1, 2])
    out = place_fit(maps, heights, lengths)
    assert out[1][(1, 1)] == pytest.approx((1.0, 0.5 + 0.25 + 0.01))


# --- near rows, splitting a built strip ------------------------------------------

def test_near_ids_pick_the_near_row():
    verts, faces = grid([(x, 0) for x in range(4)])
    top = {v for v, p in verts.items() if p[1] == 1.0}
    strip = strip_from_faces(verts, faces, near=top)
    assert set(strip.near) == top
    assert all(a[0] <= b[0] and a[1] <= b[1] for a, b in zip(strip.rungs, strip.rungs[1:]))
    uv = stripe_uvs(strip)
    assert all(abs(v) < 1e-9 for (_f, vid), (_u, v) in uv.items() if vid in top)
    assert all(a > 0 for a in areas(faces, uv).values())
    bottom = {v for v, p in verts.items() if p[1] == 0.0}
    assert set(strip_from_faces(verts, faces, near=bottom).near) == bottom
    assert strip_from_faces(verts, faces, near=set()).near == strip_from_faces(verts, faces).near


def test_near_ids_pick_a_rings_near_loop():
    verts, faces = band(8)
    top = set(range(8, 16))
    assert set(strip_from_faces(verts, faces, near=top).near) == top
    assert set(strip_from_faces(verts, faces).near) == set(range(8))


def test_split_strip_keeps_the_near_row_and_height():
    verts, quads = polyline_strip([0, 22, 0, 38])
    faces = dict(enumerate(quads))
    whole = strip_from_faces(verts, faces, near={1, 3, 5, 7, 9, 11})    # the right-hand rail
    whole.height = 0.5
    whole.layout = "STRAIGHT"
    pieces, reason = split_strip(whole, math.radians(15))
    assert reason is None and [sorted(p.faces) for p in pieces] == [[0, 1], [2, 3], [4]]
    for piece in pieces:
        assert set(piece.near) <= {1, 3, 5, 7, 9, 11} and piece.height == 0.5 and piece.layout == "STRAIGHT"
        uv = stripe_uvs(piece)
        assert all(abs(v) < 1e-9 for (_f, vid), (_u, v) in uv.items() if vid % 2)
        assert all(a > 0 for a in areas(piece.faces, uv).values())


def test_split_strip_without_cuts_or_with_a_failing_piece_returns_the_strip():
    verts, quads = polyline_strip([0, 5, 0, 5])
    strip = strip_from_faces(verts, dict(enumerate(quads)))
    assert split_strip(strip, math.radians(15)) == ([strip], None)
    verts, quads = polyline_strip([0, 22, 0, 38])
    strip = strip_from_faces(verts, dict(enumerate(quads)))
    strip.height = 0.0                                  # every piece then has no size: reported
    assert split_strip(strip, math.radians(15)) == ([strip], "a piece has no size")
    grid_strip = strip_from_faces(*grid([(x, y) for y in range(2) for x in range(4)]))
    assert split_strip(grid_strip, math.radians(1)) == ([grid_strip], None)


@pytest.mark.parametrize("pattern", ["a", "b", "alt"])
def test_bend_cuts_on_a_triangulated_strip_land_on_its_quads_rungs(pattern):
    verts, quads = polyline_strip([0, 22, 0, 38])
    faces = triangulate(quads, pattern)
    assert bend_cuts(verts, faces, math.radians(15)) == {(4, 5), (8, 9)}
    strip = strip_from_faces(verts, faces)
    strip.layout = "TRUE"
    pieces, reason = split_strip(strip, math.radians(15))
    assert reason is None and len(pieces) == 3
    for piece in pieces:
        uv = stripe_uvs(piece)
        assert all(a > 0 for a in areas(piece.faces, uv).values())
