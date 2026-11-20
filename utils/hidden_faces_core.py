"""Hidden-face detection: polygons that cannot be seen from outside the
model. NumPy only, no bpy: unit-testable standalone. Ray casting is
injected, so the overlay passes a BVHTree and the tests a brute-force one:

    cast(origin, direction, distance=None) -> bool
        True when the ray hits any geometry within `distance` (default
        unlimited), either side of the hit face.
    winding(origin, direction) -> int
        Over EVERY hit along the whole ray: back-side hits minus front-side
        hits (a face's front is the side its normal points to). For closed
        meshes that is the number of solids the origin is inside.

A polygon is hidden when, from its front (normal) side, no straight line
reaches the outside: every ray from a set of sample points on it, over a
set of directions in the hemisphere around its normal, hits something.
One ray that escapes makes it visible.

Sample points: per render triangle of the polygon, its centroid and three
points near its corners (CORNER_WEIGHT toward the corner), each lifted off
the surface by `eps` along the normal. Directions: per sample point the
normal, then `rays - 1` directions uniform in SOLID ANGLE over the
hemisphere, down to a fraction of a degree above the surface, so narrow
grazing openings are sampled. They come from one low-discrepancy sequence
shared out between the sample points of a face: every prefix is spread
over the hemisphere, and the points together cover it `points x rays`
times as densely as one point.

Cost: most faces are visible and should cost one ray, the few candidates
get the full budget.

1. Pass 1: one ray per polygon, from the centroid of its largest
   triangle straight along the normal. Clears every face that looks into
   open space (all faces of a convex shape).
2. Pass 2: the same point, the first CHEAP_RAYS directions.
3. Confirm: polygons still blocked. Every sample point gets all `rays`
   directions, early exit on the first escape. Only polygons that survive
   it are reported.

Inside a solid (what keeps faces buried in other objects cheap): before
spending its budget, a sample point is tested with `winding` along
WINDING_RAYS directions. When every one says it is inside a closed solid,
every ray from it would hit, so it counts as blocked. Another sample point
of the same face that such a point reaches by a clear straight segment is
inside the same solid too. A pocket in a solid model is outside the solid
(winding 0), so its faces always get the full budget.
"""
from __future__ import annotations

import math

import numpy as np

# Corner sample point = CORNER_WEIGHT * corner + the rest split between
# the triangle's other two corners.
CORNER_WEIGHT = 0.8

# Directions (the normal included) of pass 2.
CHEAP_RAYS = 16

# Directions that must all report "inside a solid" for a sample point to
# count as enclosed (several, so one ray through a hole in a mesh that is
# not closed does not decide it).
WINDING_RAYS = 2

# R2 sequence steps (1 / plastic number, its square).
_PLASTIC = 1.324717957244746
_R2_A = 1.0 / _PLASTIC
_R2_B = 1.0 / (_PLASTIC * _PLASTIC)


def hemisphere_directions(count, offset=0, stride=1):
    """(count, 3) unit directions in a local frame with +Z as the normal:
    the normal first, then `count - 1` directions uniform in solid angle
    over the open hemisphere (cos(theta) uniform).

    The directions are terms offset, offset + stride, offset + 2 * stride,
    ... of one R2 low-discrepancy sequence (plastic-number Kronecker
    lattice) in (cos(theta), azimuth): every prefix is spread over the
    hemisphere, and the `stride` sample points of one face, each taking
    its own offset, together form one evenly spread set `stride` times as
    dense."""
    count = max(int(count), 1)
    out = np.empty((count, 3), np.float64)
    out[0] = (0.0, 0.0, 1.0)
    rest = count - 1
    if rest:
        j = offset + stride * np.arange(rest, dtype=np.float64)
        u = np.mod(0.5 + j * _R2_A, 1.0)
        v = np.mod(0.5 + j * _R2_B, 1.0)
        # The most grazing ray stays a hair above the surface.
        z = np.clip(1.0 - u, 1e-3, 1.0)
        r = np.sqrt(np.maximum(0.0, 1.0 - z * z))
        phi = 2.0 * np.pi * v
        out[1:, 0] = r * np.cos(phi)
        out[1:, 1] = r * np.sin(phi)
        out[1:, 2] = z
    return out


def _frames(normals):
    """Orthonormal tangent and bitangent for each unit normal (P, 3)."""
    helper = np.zeros_like(normals)
    use_x = np.abs(normals[:, 0]) < 0.9
    helper[use_x, 0] = 1.0
    helper[~use_x, 1] = 1.0
    t = np.cross(helper, normals)
    t /= np.linalg.norm(t, axis=1, keepdims=True)
    b = np.cross(normals, t)
    return t, b


def sample_points(tri_co):
    """(T, 3, 3) triangle corners -> (T, 4, 3): centroid, then one point
    near each corner."""
    side = (1.0 - CORNER_WEIGHT) * 0.5
    out = np.empty((len(tri_co), 4, 3), np.float64)
    out[:, 0] = tri_co.mean(axis=1)
    for k in range(3):
        out[:, k + 1] = (CORNER_WEIGHT * tri_co[:, k]
                         + side * tri_co[:, (k + 1) % 3]
                         + side * tri_co[:, (k + 2) % 3])
    return out


def _point_blocked(cast, origin, dirs):
    """True when every ray of `dirs` from `origin` hits (early exit)."""
    for d in dirs:
        if not cast(origin, d):
            return False
    return True


def _inside_solid(winding, origin, dirs):
    """True when every direction says `origin` is inside a closed solid."""
    if winding is None:
        return False
    for d in dirs:
        if winding(origin, d) < 1:
            return False
    return True


def hidden_faces(co, tri_verts, tri_poly, poly_normals, rays, cast,
                 winding=None, test=None, eps=None, cheap=CHEAP_RAYS):
    """Polygon indices that are hidden from outside.

    co: (V, 3) world-space vertex positions (the occluders and the tested
        faces share this soup).
    tri_verts: (T, 3) vertex indices of the render triangles.
    tri_poly: (T,) polygon index of each triangle.
    poly_normals: (P, 3) polygon normals (any length; zero = degenerate,
        never reported).
    rays: directions per sample point in the confirm pass, the normal
        included.
    cast: callable (origin, direction, distance=None) -> bool hit.
        Origins and directions are 3-float lists.
    winding: optional callable (origin, direction) -> back minus front
        hits along the whole ray; without it there is no inside-a-solid
        shortcut (same idea, slower on buried faces).
    test: optional (P,) bool mask of polygons to test (others still occlude
        through `cast`, they are just not reported).
    eps: lift of the ray origins off the surface; default
        max(1e-6, 1e-5 * bounding-box diagonal).
    cheap: directions of pass 2.

    Returns a sorted int64 array of unique polygon indices."""
    none = np.empty(0, np.int64)
    co = np.asarray(co, np.float64).reshape(-1, 3)
    tri_verts = np.asarray(tri_verts, np.int64).reshape(-1, 3)
    tri_poly = np.asarray(tri_poly, np.int64).ravel()
    normals = np.asarray(poly_normals, np.float64).reshape(-1, 3)
    n_poly = len(normals)
    if not len(tri_verts) or not n_poly or not len(co):
        return none
    rays = max(int(rays), 1)
    cheap = max(1, min(int(cheap), rays))
    diag = float(np.linalg.norm(co.max(axis=0) - co.min(axis=0)))
    if eps is None:
        eps = max(1e-6, 1e-5 * diag)
    nlen = np.linalg.norm(normals, axis=1)
    poly_ok = nlen > 1e-12
    if test is not None:
        poly_ok &= np.asarray(test, bool).ravel()[:n_poly]
    tri_co = co[tri_verts]                                       # (T, 3, 3)
    dbl = np.linalg.norm(np.cross(tri_co[:, 1] - tri_co[:, 0],
                                  tri_co[:, 2] - tri_co[:, 0]), axis=1)
    tri_ok = (dbl > max(diag * diag * 1e-14, 1e-30))
    tri_ok &= (tri_poly >= 0) & (tri_poly < n_poly)
    tri_ok[tri_ok] &= poly_ok[tri_poly[tri_ok]]
    keep = np.nonzero(tri_ok)[0]
    if not len(keep):
        return none
    tri_co = tri_co[keep]
    tri_poly = tri_poly[keep]
    dbl = dbl[keep]
    # Triangles grouped by polygon, largest first inside each group.
    order = np.lexsort((-dbl, tri_poly))
    sorted_poly = tri_poly[order]
    group_start = np.nonzero(np.r_[True, sorted_poly[1:] != sorted_poly[:-1]])[0]
    group_end = np.r_[group_start[1:], len(order)]
    polys = sorted_poly[group_start]                             # (P',)
    unit_n = normals[polys] / nlen[polys, None]
    samples = sample_points(tri_co)                              # (T', 4, 3)
    lift = unit_n * eps

    # Pass 1: largest triangle's centroid along the normal.
    origin0 = samples[order[group_start], 0] + lift
    hit1 = np.fromiter(
        (cast(o, d) for o, d in zip(origin0.tolist(), unit_n.tolist())),
        bool, len(polys))
    rest = np.nonzero(hit1)[0]
    if not len(rest):
        return none

    # Direction tables per (sample points of the face, sample point).
    n_samples = 4 * (group_end - group_start)
    tables = {}

    def table(stride, k):
        local = tables.get((stride, k))
        if local is None:
            local = tables[(stride, k)] = hemisphere_directions(
                max(rays, WINDING_RAYS), k, stride)
        return local

    # Pass 2: the same point, the first `cheap` directions.
    still = []
    if cheap > 1:
        for stride in np.unique(n_samples[rest]).tolist():
            grp = rest[n_samples[rest] == stride]
            loc = table(stride, 0)[1:cheap]
            t, b = _frames(unit_n[grp])
            dirs = (loc[None, :, 0, None] * t[:, None, :]
                    + loc[None, :, 1, None] * b[:, None, :]
                    + loc[None, :, 2, None] * unit_n[grp][:, None, :])
            for i, o, ds in zip(grp.tolist(), origin0[grp].tolist(),
                                dirs.tolist()):
                if _point_blocked(cast, o, ds):
                    still.append(i)
    else:
        still = rest.tolist()
    if not still:
        return none

    # Confirm: every sample point, the full budget.
    still = np.asarray(sorted(still), np.int64)
    t, b = _frames(unit_n[still])
    bases = np.stack((t, b, unit_n[still]), axis=1)              # (C, 3, 3)
    hidden = []
    for i, basis in zip(still.tolist(), bases):
        stride = int(n_samples[i])
        tris = order[group_start[i]:group_end[i]]
        pts = (samples[tris] + lift[i]).reshape(-1, 3).tolist()
        o0 = pts[0]
        world0 = (table(stride, 0) @ basis).tolist()
        # Centroid: inside a solid, else the rest of its directions.
        inside0 = _inside_solid(winding, o0, world0[:WINDING_RAYS])
        if not inside0 and not _point_blocked(cast, o0, world0[cheap:rays]):
            continue
        visible = False
        for k in range(1, len(pts)):
            oq = pts[k]
            if inside0:
                seg = (oq[0] - o0[0], oq[1] - o0[1], oq[2] - o0[2])
                dist = math.sqrt(seg[0] ** 2 + seg[1] ** 2 + seg[2] ** 2)
                if dist <= eps or not cast(
                        o0, [seg[0] / dist, seg[1] / dist, seg[2] / dist],
                        dist):
                    continue      # inside the same solid
            ds = (table(stride, k) @ basis).tolist()
            if _inside_solid(winding, oq, ds[:WINDING_RAYS]):
                continue
            if not _point_blocked(cast, oq, ds[:rays]):
                visible = True
                break
        if not visible:
            hidden.append(int(polys[i]))
    return np.asarray(sorted(hidden), np.int64)
