import math

import numpy as np

from utils.zfight_core import candidate_pairs, zfight_faces

ANGLE = 0.5
DIST = 0.0001


def build(polys):
    """Polygons as coordinate lists -> (co, tri_verts, tri_poly). Vertices
    with equal coordinates are welded (shared), like a real mesh; each
    polygon is fan-triangulated (all test polygons are convex)."""
    index = {}
    co = []
    tris = []
    tri_poly = []

    def vid(p):
        key = tuple(round(c, 9) for c in p)
        if key not in index:
            index[key] = len(co)
            co.append(p)
        return index[key]

    for pi, poly in enumerate(polys):
        ids = [vid(p) for p in poly]
        for k in range(1, len(ids) - 1):
            tris.append((ids[0], ids[k], ids[k + 1]))
            tri_poly.append(pi)
    return (np.array(co, float), np.array(tris, np.int64),
            np.array(tri_poly, np.int64))


def flagged(polys, angle=ANGLE, dist=DIST):
    co, tv, tp = build(polys)
    return sorted(int(i) for i in zfight_faces(co, tv, tp, angle, dist))


def quad(x0, y0, x1, y1, z=0.0):
    return [(x0, y0, z), (x1, y0, z), (x1, y1, z), (x0, y1, z)]


def test_exact_duplicate_same_normal():
    q = quad(0, 0, 1, 1)
    assert flagged([q, list(q)]) == [0, 1]


def test_duplicate_flipped_normal_is_clean():
    # Faces facing each other (an object standing on another) only touch.
    q = quad(0, 0, 1, 1)
    assert flagged([q, q[::-1]]) == []


def test_partial_overlap():
    assert flagged([quad(0, 0, 1, 1), quad(0.5, 0.3, 1.5, 1.3)]) == [0, 1]


def test_flat_grid_is_clean():
    polys = [quad(i, j, i + 1, j + 1) for i in range(2) for j in range(2)]
    assert flagged(polys) == []


def test_shared_edge_only():
    assert flagged([quad(0, 0, 1, 1), quad(1, 0, 2, 1)]) == []


def test_shared_vertex_only():
    assert flagged([quad(0, 0, 1, 1), quad(1, 1, 2, 2)]) == []


def test_parallel_offset_beyond_tolerance():
    assert flagged([quad(0, 0, 1, 1), quad(0, 0, 1, 1, z=0.001)]) == []


def test_parallel_offset_within_tolerance():
    assert flagged([quad(0, 0, 1, 1), quad(0, 0, 1, 1, z=0.00005)]) == [0, 1]


def test_tilted_beyond_angle():
    # Rotate 5 degrees about the quad's centre line (x = 0.5): the planes
    # cross, but are not parallel within 0.5 degrees.
    a = math.radians(5.0)
    tilted = [(0.5 + (x - 0.5) * math.cos(a), y, (x - 0.5) * math.sin(a))
              for (x, y, _z) in quad(0, 0, 1, 1)]
    assert flagged([quad(0, 0, 1, 1), tilted]) == []


def test_tilted_within_angle():
    a = math.radians(0.2)
    tilted = [(0.5 + (x - 0.5) * math.cos(a), y, (x - 0.5) * math.sin(a))
              for (x, y, _z) in quad(0, 0, 1, 1)]
    assert flagged([quad(0, 0, 1, 1), tilted], dist=0.01) == [0, 1]


def test_folded_onto_neighbour_is_clean():
    # The neighbour across the edge x=1 rotated 180 degrees about that edge
    # lies flat on top of the first quad, sharing two vertices. Its normal
    # is opposite, so it is not a conflict.
    # Its far vertices sit 1e-7 above the first quad's so the test mesh
    # keeps them as separate vertices (the builder welds equal positions).
    a = quad(0, 0, 1, 1)
    folded = [(1, 0, 0), (0.0, 0, 1e-7), (0.0, 1, 1e-7), (1, 1, 0)]
    co, tv, tp = build([a, folded])
    assert len(co) == 6   # only the hinge edge is shared
    assert sorted(zfight_faces(co, tv, tp, ANGLE, DIST).tolist()) == []


def test_small_triangle_inside_big_ngon():
    ngon = [(math.cos(t) * 4, math.sin(t) * 4, 0.0)
            for t in np.linspace(0, 2 * math.pi, 8, endpoint=False)]
    tri = [(0.1, 0.1, 0.0), (0.4, 0.1, 0.0), (0.2, 0.3, 0.0)]
    assert flagged([ngon, tri]) == [0, 1]


def test_only_the_conflicting_faces_are_flagged():
    polys = [quad(i, j, i + 1, j + 1) for i in range(3) for j in range(3)]
    polys.append(quad(1, 1, 2, 2))   # duplicate of the centre quad
    assert flagged(polys) == [4, 9]


def test_world_offset_and_scale():
    # Far from the origin and tiny: tolerances must not break.
    base = 1000.0
    s = 0.01
    q = [(base + x * s, base + y * s, base) for (x, y, _z) in quad(0, 0, 1, 1)]
    nb = [(base + 1 * s + x * s, base + y * s, base)
          for (x, y, _z) in quad(0, 0, 1, 1)]
    assert flagged([q, nb]) == []
    assert flagged([q, list(q)]) == [0, 1]
    assert flagged([q, q[::-1]]) == []


def test_degenerate_input():
    co = np.zeros((3, 3))
    assert len(zfight_faces(co, np.array([[0, 1, 2]]), np.array([0]),
                            ANGLE, DIST)) == 0
    assert len(zfight_faces(co, np.empty((0, 3), int), np.empty(0, int),
                            ANGLE, DIST)) == 0


class TestCandidatePairs:
    @staticmethod
    def brute(lo, hi):
        n = len(lo)
        out = set()
        for i in range(n):
            for j in range(i + 1, n):
                if np.all(lo[i] <= hi[j]) and np.all(lo[j] <= hi[i]):
                    out.add((i, j))
        return out

    def test_matches_brute_force_mixed_sizes(self):
        rng = np.random.default_rng(7)
        n = 400
        lo = rng.uniform(0, 10, (n, 3))
        # Mostly small boxes, a few large ones spanning many cells.
        size = rng.uniform(0.05, 0.6, (n, 3))
        size[:15] *= 12.0
        hi = lo + size
        i, j = candidate_pairs(lo, hi)
        assert set(zip(i.tolist(), j.tolist())) == self.brute(lo, hi)

    def test_boxes_touching_at_cell_borders(self):
        # Unit boxes on an integer lattice touch exactly on cell borders.
        lo = np.array([(x, y, 0.0) for x in range(4) for y in range(4)])
        hi = lo + 1.0
        i, j = candidate_pairs(lo, hi)
        assert set(zip(i.tolist(), j.tolist())) == self.brute(lo, hi)

    def test_flat_boxes(self):
        rng = np.random.default_rng(3)
        lo = rng.uniform(0, 5, (300, 3))
        lo[:, 2] = 0.0
        hi = lo + rng.uniform(0.1, 0.8, (300, 3))
        hi[:, 2] = 0.0
        i, j = candidate_pairs(lo, hi)
        assert set(zip(i.tolist(), j.tolist())) == self.brute(lo, hi)


def _soup(*objects):
    """Concatenate separate 'objects' (each from build()) into one soup
    with vertex offsets and globally unique polygon ids, like the overlay
    does for several Blender objects."""
    cos, tris, polys = [], [], []
    v_off = p_off = 0
    for co, tv, tp in objects:
        cos.append(co)
        tris.append(tv + v_off)
        polys.append(tp + p_off)
        v_off += len(co)
        p_off += int(tp.max()) + 1
    return np.concatenate(cos), np.concatenate(tris), np.concatenate(polys)


def test_two_objects_coincident():
    a = build([quad(0, 0, 1, 1), quad(1, 0, 2, 1)])
    b = build([quad(1, 0, 2, 1)])   # same plane and facing as a's second quad
    co, tv, tp = _soup(a, b)
    assert sorted(zfight_faces(co, tv, tp, ANGLE, DIST).tolist()) == [1, 2]


def test_two_objects_resting_on_each_other():
    # One object standing on another: the faces coincide but face each
    # other, so nothing flickers.
    a = build([quad(0, 0, 1, 1), quad(1, 0, 2, 1)])
    b = build([quad(1, 0, 2, 1)[::-1]])
    co, tv, tp = _soup(a, b)
    assert sorted(zfight_faces(co, tv, tp, ANGLE, DIST).tolist()) == []


def test_two_objects_touching_along_an_edge():
    a = build([quad(0, 0, 1, 1)])
    b = build([quad(1, 0, 2, 1)])   # separate vertices on the shared edge
    co, tv, tp = _soup(a, b)
    assert len(co) == 8
    assert len(zfight_faces(co, tv, tp, ANGLE, DIST)) == 0
