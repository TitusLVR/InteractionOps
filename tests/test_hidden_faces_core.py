import numpy as np

from utils.hidden_faces_core import (hemisphere_directions, hidden_faces,
                                     sample_points)

RAYS = 64


def build(polys):
    """Polygons as coordinate lists -> (co, tri_verts, tri_poly, normals).
    Vertices with equal coordinates are welded; each polygon is
    fan-triangulated and its normal follows the winding (counter-clockwise
    seen from the front)."""
    index = {}
    co = []
    tris = []
    tri_poly = []
    normals = []

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
        p = np.array(poly, float)
        n = np.zeros(3)
        for k in range(len(p)):   # Newell normal
            a, b = p[k], p[(k + 1) % len(p)]
            n += np.cross(a, b)
        ln = np.linalg.norm(n)
        normals.append(n / ln if ln > 0 else n)
    return (np.array(co, float), np.array(tris, np.int64),
            np.array(tri_poly, np.int64), np.array(normals, float))


def brute_caster(co, tris):
    """Moller-Trumbore against every triangle -> (cast, winding) callables
    with the signatures hidden_faces expects. Hits at the same distance
    (a ray through a shared edge) count once."""
    v0 = co[tris[:, 0]]
    e1 = co[tris[:, 1]] - v0
    e2 = co[tris[:, 2]] - v0
    tri_n = np.cross(e1, e2)

    def hits(origin, direction):
        o = np.asarray(origin, float)
        d = np.asarray(direction, float)
        p = np.cross(d, e2)
        det = (e1 * p).sum(axis=1)
        ok = np.abs(det) > 1e-14
        inv = np.zeros_like(det)
        inv[ok] = 1.0 / det[ok]
        s = o - v0
        u = (s * p).sum(axis=1) * inv
        q = np.cross(s, e1)
        v = (q * d).sum(axis=1) * inv
        t = (q * e2).sum(axis=1) * inv
        hit = ok & (u >= 0) & (v >= 0) & (u + v <= 1) & (t > 1e-9)
        return t, hit, d

    def cast(origin, direction, distance=None):
        t, hit, _d = hits(origin, direction)
        if distance is not None:
            hit &= t <= distance
        return bool(hit.any())

    def winding(origin, direction):
        t, hit, d = hits(origin, direction)
        idx = np.nonzero(hit)[0]
        _u, first = np.unique(np.round(t[idx], 9), return_index=True)
        idx = idx[first]
        back = (tri_n[idx] @ d) > 0
        return int(back.sum() - (~back).sum())

    return cast, winding


def box(lo, hi, inward=False, skip=()):
    """Axis-aligned box quads, normals outward (inward=True flips them).
    skip: face names to leave out ('-x', '+x', '-y', '+y', '-z', '+z')."""
    x0, y0, z0 = lo
    x1, y1, z1 = hi
    faces = {
        "-x": [(x0, y0, z0), (x0, y0, z1), (x0, y1, z1), (x0, y1, z0)],
        "+x": [(x1, y0, z0), (x1, y1, z0), (x1, y1, z1), (x1, y0, z1)],
        "-y": [(x0, y0, z0), (x1, y0, z0), (x1, y0, z1), (x0, y0, z1)],
        "+y": [(x0, y1, z0), (x0, y1, z1), (x1, y1, z1), (x1, y1, z0)],
        "-z": [(x0, y0, z0), (x0, y1, z0), (x1, y1, z0), (x1, y0, z0)],
        "+z": [(x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)],
    }
    out = []
    for name, quad in faces.items():
        if name in skip:
            continue
        out.append(quad[::-1] if inward else quad)
    return out


def flagged(polys, rays=RAYS, use_winding=True):
    co, tv, tp, nrm = build(polys)
    cast, winding = brute_caster(co, tv)
    if not use_winding:
        winding = None
    return [int(i) for i in hidden_faces(co, tv, tp, nrm, rays, cast,
                                         winding=winding)]


def test_box_normals_point_outward():
    co, tv, tp, nrm = build(box((-1, -1, -1), (1, 1, 1)))
    for pi in range(6):
        center = co[tv[tp == pi]].reshape(-1, 3).mean(axis=0)
        assert np.dot(center, nrm[pi]) > 0


def test_closed_cube_nothing_hidden():
    assert flagged(box((-1, -1, -1), (1, 1, 1))) == []


def test_internal_quad_hidden_both_orientations():
    quad = [(-0.5, -0.5, 0), (0.5, -0.5, 0), (0.5, 0.5, 0), (-0.5, 0.5, 0)]
    up = box((-1, -1, -1), (1, 1, 1)) + [quad]
    down = box((-1, -1, -1), (1, 1, 1)) + [quad[::-1]]
    assert flagged(up) == [6]
    assert flagged(down) == [6]


def test_small_cube_inside_big_cube():
    polys = box((-2, -2, -2), (2, 2, 2)) + box((-0.5, -0.5, -0.5),
                                               (0.5, 0.5, 0.5))
    assert flagged(polys) == list(range(6, 12))
    assert flagged(polys, use_winding=False) == list(range(6, 12))


def test_open_box_face_inside_visible():
    open_box = box((-1, -1, -1), (1, 1, 1), skip=("+z",))
    floor = [(-0.5, -0.5, -0.5), (0.5, -0.5, -0.5), (0.5, 0.5, -0.5),
             (-0.5, 0.5, -0.5)]
    assert flagged(open_box + [floor]) == []


def test_open_box_sideways_face_visible_through_opening():
    # Faces +X, the opening is above it: only tilted rays escape (pass 2).
    open_box = box((-1, -1, -1), (1, 1, 1), skip=("+z",))
    wall = [(0, -0.3, -0.8), (0, 0.3, -0.8), (0, 0.3, -0.2), (0, -0.3, -0.2)]
    assert flagged(open_box + [wall]) == []


def test_face_half_outside_box_not_flagged():
    quad = [(0, -0.5, 0), (2, -0.5, 0), (2, 0.5, 0), (0, 0.5, 0)]
    assert flagged(box((-1, -1, -1), (1, 1, 1)) + [quad]) == []


def test_degenerate_input():
    co = np.zeros((3, 3))
    cast, _winding = brute_caster(co, np.array([[0, 1, 2]]))
    assert len(hidden_faces(co, np.array([[0, 1, 2]]), np.array([0]),
                            np.zeros((1, 3)), RAYS, cast)) == 0
    assert len(hidden_faces(np.empty((0, 3)), np.empty((0, 3), int),
                            np.empty(0, int), np.empty((0, 3)), RAYS,
                            cast)) == 0


def test_zero_normal_inside_cube_never_flagged():
    polys = box((-1, -1, -1), (1, 1, 1)) + [
        [(0, 0, 0), (0.5, 0, 0), (0.5, 0.5, 0), (0, 0.5, 0)]]
    co, tv, tp, nrm = build(polys)
    nrm[6] = 0.0
    cast, _winding = brute_caster(co, tv)
    assert hidden_faces(co, tv, tp, nrm, RAYS, cast).tolist() == []


def test_test_mask_limits_reported_faces():
    polys = box((-2, -2, -2), (2, 2, 2)) + box((-0.5, -0.5, -0.5),
                                               (0.5, 0.5, 0.5))
    co, tv, tp, nrm = build(polys)
    mask = np.zeros(12, bool)
    mask[6] = True
    cast, _winding = brute_caster(co, tv)
    assert hidden_faces(co, tv, tp, nrm, RAYS, cast, test=mask).tolist() == [6]


def test_visible_faces_cost_one_ray():
    calls = [0]
    co, tv, tp, nrm = build(box((-1, -1, -1), (1, 1, 1)))
    inner, _winding = brute_caster(co, tv)

    def cast(o, d, distance=None):
        calls[0] += 1
        return inner(o, d, distance)
    hidden_faces(co, tv, tp, nrm, RAYS, cast)
    assert calls[0] == 6


def test_hemisphere_directions():
    d = hemisphere_directions(64)
    assert d.shape == (64, 3)
    assert d[0].tolist() == [0.0, 0.0, 1.0]
    assert np.allclose(np.linalg.norm(d, axis=1), 1.0)
    assert (d[:, 2] > 0).all()
    # Any prefix is spread out: the first 8 rays cover every quadrant.
    quad = {(x > 0, y > 0) for x, y in d[1:9, :2]}
    assert len(quad) == 4
    assert hemisphere_directions(1).shape == (1, 3)


def test_sample_points_inside_triangle():
    tri = np.array([[[0, 0, 0], [1, 0, 0], [0, 1, 0]]], float)
    pts = sample_points(tri)[0]
    assert np.allclose(pts[0], [1 / 3, 1 / 3, 0])
    assert np.allclose(pts[1], [0.1, 0.1, 0])
    assert np.allclose(pts[2], [0.8, 0.1, 0])


def pocket(lid=False):
    """A face (polygon 0) on the ceiling of a flat tunnel, facing down into
    it. The tunnel is lined with faces pointing into it, like a pocket in a
    solid model. Its only opening is a slit at the far end, between a lip
    hanging from the ceiling and the floor: only grazing directions, a few
    degrees below the face plane, escape. lid=True closes the opening."""
    h, length, w, lip = 0.16, 1.6, 2.0, 0.09
    y0, y1 = -w / 2, w / 2
    polys = [
        [(0, y0, 0), (0, y1, 0), (1, y1, 0), (1, y0, 0)],                # face
        [(1, y0, 0), (1, y1, 0), (length, y1, 0), (length, y0, 0)],      # ceiling
        [(0, y0, -h), (length, y0, -h), (length, y1, -h), (0, y1, -h)],  # floor
        [(0, y0, 0), (0, y0, -h), (0, y1, -h), (0, y1, 0)],              # back
        [(0, y0, 0), (length, y0, 0), (length, y0, -h), (0, y0, -h)],    # side
        [(0, y1, 0), (0, y1, -h), (length, y1, -h), (length, y1, 0)],    # side
    ]
    bottom = -h if lid else -lip
    polys.append([(length, y0, 0), (length, y1, 0), (length, y1, bottom),
                  (length, y0, bottom)])                         # lip or lid
    return polys


def _escaping(polys, point, count=20000):
    """Fraction of uniform random hemisphere rays (below the face) that
    escape from `point`, and their elevation range in degrees."""
    co, tv, _tp, _nrm = build(polys)
    cast, _winding = brute_caster(co, tv)
    rng = np.random.default_rng(0)
    z = rng.uniform(0, 1, count)
    phi = rng.uniform(0, 2 * np.pi, count)
    r = np.sqrt(1 - z * z)
    dirs = np.stack([r * np.cos(phi), r * np.sin(phi), -z], axis=1)
    esc = [z[i] for i in range(count)
           if not cast(point, dirs[i].tolist())]
    return len(esc) / count, np.degrees(np.arcsin(esc))


def _default_rays():
    import ast
    import os
    src = open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "prefs", "addon_preferences.py"),
        encoding="utf-8").read()
    block = src[src.index("hidden_faces_rays:"):]
    block = block[:block.index(")\n") + 1]
    tree = ast.parse("f" + block[block.index("("):])
    return next(k.value.value for k in tree.body[0].value.keywords
                if k.arg == "default")


def test_pocket_opening_is_narrow_and_grazing():
    fraction, elevation = _escaping(pocket(), [0.5, 0.0, -1e-5])
    assert 0.005 < fraction < 0.03
    assert elevation.min() > 2.0 and elevation.max() < 10.0


def test_pocket_face_visible_with_default_rays():
    assert 0 not in flagged(pocket(), rays=_default_rays())


def test_pocket_face_visible_in_any_orientation():
    rng = np.random.default_rng(7)
    rays = _default_rays()
    for _ in range(8):
        q, _r = np.linalg.qr(rng.normal(size=(3, 3)))
        if np.linalg.det(q) < 0:
            q[:, 0] *= -1.0     # a rotation, not a mirror
        polys = [[tuple(q @ np.array(p, float)) for p in poly]
                 for poly in pocket()]
        assert 0 not in flagged(polys, rays=rays)


def test_closed_pocket_face_hidden():
    assert 0 in flagged(pocket(lid=True), rays=_default_rays())


def test_buried_faces_cheap_with_winding():
    # Small cube pushed half into a bigger one: its buried faces are found
    # through the inside-a-solid test, without the full ray budget.
    polys = box((-1, -1, -1), (1, 1, 1)) + box((0.5, -0.3, -0.3),
                                               (1.5, 0.3, 0.3))
    co, tv, tp, nrm = build(polys)
    cast, winding = brute_caster(co, tv)
    calls = [0]

    def counting(o, d, distance=None):
        calls[0] += 1
        return cast(o, d, distance)
    with_w = hidden_faces(co, tv, tp, nrm, 256, counting, winding=winding)
    cheap_calls = calls[0]
    calls[0] = 0
    without = hidden_faces(co, tv, tp, nrm, 256, counting)
    # -x face of the small cube is fully inside the big one.
    assert 6 in with_w.tolist()
    assert with_w.tolist() == without.tolist()
    assert cheap_calls * 4 < calls[0]


def test_inside_out_shell_is_not_a_solid():
    # Normals pointing inward (a closed room): winding says "outside", so
    # everything gets the full ray budget; the walls and the quad inside
    # all face the closed interior and are hidden.
    quad = [(-0.5, -0.5, 0), (0.5, -0.5, 0), (0.5, 0.5, 0), (-0.5, 0.5, 0)]
    polys = box((-1, -1, -1), (1, 1, 1), inward=True) + [quad]
    assert flagged(polys) == list(range(7))
