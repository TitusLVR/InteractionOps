import math
import random

import pytest

from utils.uv_stripe_core import strip_length, stripe_uvs
from utils.uv_stripe_select_core import face_islands, strip_from_faces

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
