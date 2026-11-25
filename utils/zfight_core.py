"""Z-fight detection: faces of one mesh that lie in the same plane and
overlap by area. NumPy only — no bpy, unit-testable standalone.

Works on the mesh's render triangles (loop triangles) in world space:

1. Broad phase — `candidate_pairs`: triangle pairs whose (inflated) AABBs
   overlap. A multi-level uniform grid: each triangle lives at the level
   whose cell is at least as large as its AABB, so it touches at most 2
   cells per axis there; a triangle queries its own level and every coarser
   one. Two overlapping boxes always share a cell at the coarser box's
   level, so no pair is missed at cell borders. Cell keys are hashed;
   collisions only add candidates, which the exact AABB test then drops.
2. Narrow phase — `zfight_faces`: per candidate pair of triangles from
   different polygons: parallel planes facing the SAME way
   (n_a . n_b >= cos(angle); opposite normals are faces resting against
   each other, not a conflict), each centroid within `distance` of the other's
   plane, then a separating-axis test on the six in-plane edge normals
   (the 2D test in the shared plane). The pair conflicts only when the
   penetration depth (the smallest overlap over those axes) is above a
   small epsilon scaled to the smaller triangle, so faces that merely
   share an edge or a vertex are not flagged.

Triangles are compared, not polygons, so the plane test follows the
geometry the viewport actually renders, including warped quads.

Incremental use (the overlay caches results per object and per object
pair): every flagged polygon comes from one conflicting triangle pair,
either inside one object or between two. So the result of a soup of
several objects is the union of each object's own result and, for every
pair of objects whose world AABBs come within `distance`, the
cross-objects-only result of that pair (`cross_pair_faces`). The only
soup-wide input is the zero-area floor; pass `area_floor` (from
`degenerate_floor` of the whole soup's extent) to every run and the union
is exactly the whole soup's result.
"""
from __future__ import annotations

import numpy as np

# Interior overlap needed to count as z-fighting, relative to the smaller
# triangle's size (sqrt of its area). Below it the faces only touch.
OVERLAP_EPS_REL = 1e-3

# Candidate pairs narrow-phased per batch (bounds temporary memory).
_CHUNK = 200_000

_HASH = np.array([73856093, 19349663, 83492791], dtype=np.int64)
_OFFSETS = np.array([(i, j, k) for i in (0, 1) for j in (0, 1)
                     for k in (0, 1)], dtype=np.int64)          # (8, 3)


def _cell_keys(lo_cell, hi_cell):
    """The <=8 cells covered per box: (row, cell (K, 3), hashed key).
    lo_cell/hi_cell: (N, 3) int64 with hi - lo in {0, 1} per axis."""
    cells = lo_cell[:, None, :] + _OFFSETS[None, :, :]           # (N, 8, 3)
    valid = np.all(cells <= hi_cell[:, None, :], axis=2)         # (N, 8)
    rows = np.nonzero(valid)
    c = cells[rows]
    keys = (c[:, 0] * _HASH[0]) ^ (c[:, 1] * _HASH[1]) ^ (c[:, 2] * _HASH[2])
    return rows[0], c, keys


def candidate_pairs(lo, hi):
    """Index pairs (i, j), i < j, of boxes whose AABBs overlap or touch.

    lo, hi: (N, 3) float arrays of box minima / maxima. Returns two int64
    arrays, each pair once. Vectorised; work is proportional to the number
    of nearby box pairs, not N^2."""
    lo = np.asarray(lo, np.float64)
    hi = np.asarray(hi, np.float64)
    n = len(lo)
    empty = (np.empty(0, np.int64), np.empty(0, np.int64))
    if n < 2:
        return empty
    ext = (hi - lo).max(axis=1)
    span = float((hi.max(axis=0) - lo.min(axis=0)).max())
    min_cell = max(span * 1e-9, 1e-12)
    h0 = max(float(np.median(ext)), min_cell)
    level = np.ceil(np.log2(np.maximum(ext / h0, 1.0))).astype(np.int64)
    # Float rounding in log2 can leave a box a hair larger than its cell.
    level += (ext > h0 * np.exp2(level)).astype(np.int64)
    origin = lo.min(axis=0)
    out_a = []
    out_b = []
    for lv in np.unique(level):
        # A hair above the level size: float rounding in the floor below
        # can never make a box span three cells.
        h = h0 * float(2.0 ** lv) * (1.0 + 1e-6)
        queries = np.nonzero(level <= lv)[0]
        lo_c = np.floor((lo[queries] - origin) / h).astype(np.int64)
        hi_c = np.floor((hi[queries] - origin) / h).astype(np.int64)
        # Boxes at this level or finer span at most 2 cells per axis.
        hi_c = np.minimum(hi_c, lo_c + 1)
        q_rows, q_cells, q_keys = _cell_keys(lo_c, hi_c)
        q_tri = queries[q_rows]
        is_member = level[q_tri] == lv
        e_tri = q_tri[is_member]
        e_keys = q_keys[is_member]
        order = np.argsort(e_keys, kind="stable")
        e_keys = e_keys[order]
        e_tri = e_tri[order]
        left = np.searchsorted(e_keys, q_keys, "left")
        counts = np.searchsorted(e_keys, q_keys, "right") - left
        hit = counts > 0
        if not hit.any():
            continue
        q_tri = q_tri[hit]
        q_cells = q_cells[hit]
        left = left[hit]
        counts = counts[hit]
        total = int(counts.sum())
        starts = np.repeat(np.cumsum(counts) - counts, counts)
        rows = np.repeat(np.arange(len(q_tri)), counts)
        a = q_tri[rows]
        b = e_tri[left[rows] + (np.arange(total) - starts)]
        # Same-level pairs are met from both sides: keep a < b. A finer
        # box meets a coarser one only from its own (query) side.
        keep = (a < b) | (level[a] < lv)
        a = a[keep]
        b = b[keep]
        rows = rows[keep]
        lo_a = lo[a]
        lo_b = lo[b]
        keep = np.all((lo_a <= hi[b]) & (lo_b <= hi[a]), axis=1)
        # Report each pair once: in the cell holding the low corner of the
        # two boxes' intersection (a cell both boxes cover).
        corner = np.floor((np.maximum(lo_a, lo_b) - origin) / h)
        keep &= np.all(corner.astype(np.int64) == q_cells[rows], axis=1)
        out_a.append(a[keep])
        out_b.append(b[keep])
    if not out_a:
        return empty
    a = np.concatenate(out_a)
    b = np.concatenate(out_b)
    return np.minimum(a, b), np.maximum(a, b)


def _edge_axes(tri_co, normals):
    """Per triangle: unit in-plane edge normals (T, 3 axes, xyz) and the
    triangle's own projection interval on each, (T, 3) min and max."""
    edges = np.roll(tri_co, -1, axis=1) - tri_co                 # (T, 3, 3)
    axes = np.cross(normals[:, None, :], edges)
    ln = np.linalg.norm(axes, axis=2, keepdims=True)
    ln[ln == 0.0] = 1.0
    axes /= ln
    proj = np.einsum("tkd,tvd->tkv", axes, tri_co)               # (T, 3, 3)
    return axes, proj.min(axis=2), proj.max(axis=2)


def _axis_overlap(axes, own_min, own_max, other):
    """Smallest overlap, over a triangle's three edge axes, of its own
    projection interval and another triangle's (other: (M, 3, 3) points)."""
    proj = (other[:, None, :, 0] * axes[:, :, None, 0]
            + other[:, None, :, 1] * axes[:, :, None, 1]
            + other[:, None, :, 2] * axes[:, :, None, 2])          # (M, 3, 3)
    overlap = (np.minimum(own_max, proj.max(axis=2))
               - np.maximum(own_min, proj.min(axis=2)))
    return overlap.min(axis=1)


def _narrow(tri_co, normals, areas, cents, sat, ia, ib, cos_min, distance):
    """Boolean mask over the candidate pairs (ia, ib) that z-fight."""
    na = normals[ia]
    nb = normals[ib]
    # Signed: faces that face each other (one object standing on another)
    # touch, they don't z-fight — both are hidden from the other's side.
    ok = (na * nb).sum(axis=1) >= cos_min
    d = cents[ib] - cents[ia]
    ok &= np.abs((d * na).sum(axis=1)) <= distance
    ok &= np.abs((d * nb).sum(axis=1)) <= distance
    result = np.zeros(len(ia), bool)
    sel = np.nonzero(ok)[0]
    if not len(sel):
        return result
    ia = ia[sel]
    ib = ib[sel]
    axes, amin, amax = sat
    eps = OVERLAP_EPS_REL * np.sqrt(np.minimum(areas[ia], areas[ib]))
    # Separating-axis test on the in-plane edge normals (the planes are
    # parallel within tolerance, so this is the 2D test in the shared
    # plane). Two stages: A's edges first (they separate most touching
    # neighbours), B's edges only for the survivors.
    pen = _axis_overlap(axes[ia], amin[ia], amax[ia], tri_co[ib])
    live = np.nonzero(pen > eps)[0]
    if len(live):
        ia = ia[live]
        ib = ib[live]
        pen = _axis_overlap(axes[ib], amin[ib], amax[ib], tri_co[ia])
        result[sel[live[pen > eps[live]]]] = True
    return result


def degenerate_floor(span):
    """Twice the triangle area at or below which a triangle counts as
    zero-area, for a soup whose bounding box's longest side is `span`."""
    return max(span * span * 1e-14, 1e-30)


def _cross_and_double_area(tri_co):
    cross = np.cross(tri_co[:, 1] - tri_co[:, 0], tri_co[:, 2] - tri_co[:, 0])
    return cross, np.linalg.norm(cross, axis=1)


def tri_double_areas(co, tri_verts):
    """Twice the area of each triangle (T,), computed exactly as
    `zfight_faces` does, so a caller can predict which triangles a given
    `area_floor` drops."""
    co = np.asarray(co, np.float64).reshape(-1, 3)
    tri_verts = np.asarray(tri_verts, np.int64).reshape(-1, 3)
    return _cross_and_double_area(co[tri_verts])[1]


def zfight_faces(co, tri_verts, tri_poly, angle_deg, distance, *,
                 tri_group=None, cross_only=False, area_floor=None):
    """Polygon indices that z-fight with at least one other polygon.

    co: (V, 3) world-space vertex positions.
    tri_verts: (T, 3) vertex indices of the render triangles to test
        (pass only visible ones).
    tri_poly: (T,) polygon index of each triangle.
    angle_deg: planes whose normals differ by less than this are parallel
        (same direction only; opposite normals never conflict).
    distance: max gap between the two planes.
    tri_group, cross_only: with cross_only, only triangle pairs of
        different groups (tri_group: (T,) ints, e.g. the object) count.
    area_floor: zero-area floor (`degenerate_floor`); default from the
        extent of `co`.

    Returns a sorted int64 array of unique polygon indices."""
    co = np.asarray(co, np.float64).reshape(-1, 3)
    tri_verts = np.asarray(tri_verts, np.int64).reshape(-1, 3)
    tri_poly = np.asarray(tri_poly, np.int64).ravel()
    none = np.empty(0, np.int64)
    if len(tri_verts) < 2:
        return none
    tri_co = co[tri_verts]                                       # (T, 3, 3)
    cross, dbl_area = _cross_and_double_area(tri_co)
    if area_floor is None:
        span = (float((co.max(axis=0) - co.min(axis=0)).max())
                if len(co) else 0.0)
        area_floor = degenerate_floor(span)
    # Zero-area triangles have no plane and cannot cover anything.
    good = dbl_area > area_floor
    keep = np.nonzero(good)[0]
    if len(keep) < 2:
        return none
    tri_co = tri_co[keep]
    tri_poly = tri_poly[keep]
    normals = cross[keep] / dbl_area[keep, None]
    areas = dbl_area[keep] * 0.5
    cents = tri_co.mean(axis=1)
    distance = max(float(distance), 0.0)
    pad = distance
    lo = tri_co.min(axis=1) - pad
    hi = tri_co.max(axis=1) + pad
    ia, ib = candidate_pairs(lo, hi)
    other = tri_poly[ia] != tri_poly[ib]
    if cross_only and tri_group is not None:
        group = np.asarray(tri_group).ravel()[keep]
        other &= group[ia] != group[ib]
    ia = ia[other]
    ib = ib[other]
    if not len(ia):
        return none
    cos_min = float(np.cos(np.radians(max(float(angle_deg), 0.0))))
    sat = _edge_axes(tri_co, normals)
    hits = []
    for s in range(0, len(ia), _CHUNK):
        ca = ia[s:s + _CHUNK]
        cb = ib[s:s + _CHUNK]
        m = _narrow(tri_co, normals, areas, cents, sat, ca, cb,
                    cos_min, distance)
        if m.any():
            hits.append(tri_poly[ca[m]])
            hits.append(tri_poly[cb[m]])
    if not hits:
        return none
    return np.unique(np.concatenate(hits))


def triangle_boxes(co, tri_verts):
    """(lo, hi): per-triangle AABB minima and maxima, (T, 3) each."""
    tri_co = np.asarray(co, np.float64)[np.asarray(tri_verts, np.int64)]
    return tri_co.min(axis=1), tri_co.max(axis=1)


def _near_box(tri_lo, tri_hi, lo, hi, pad):
    """Triangles whose AABB, grown by `pad`, touches the box lo..hi grown
    by `pad`: a superset of those that can pair with a triangle inside
    that box (the box contains the other triangles' AABBs)."""
    return np.all((tri_lo - pad <= hi + pad) & (lo - pad <= tri_hi + pad),
                  axis=1)


def _compact(co, tri_verts):
    """Only the vertices the triangles use, triangles re-indexed."""
    used, inv = np.unique(tri_verts, return_inverse=True)
    return co[used], inv.reshape(-1, 3)


def cross_pair_faces(co_a, tv_a, tp_a, co_b, tv_b, tp_b, angle_deg,
                     distance, area_floor, box_a=None, box_b=None):
    """(hits_a, hits_b): polygons of object A and of object B, in their own
    indices, that z-fight with a polygon of the OTHER object. Conflicts
    inside one object are not reported (that is `zfight_faces` on the
    object alone).

    co_*, tv_*, tp_*: each object's world-space vertices, triangles to
    test and their polygon indices, as for `zfight_faces`.
    area_floor: the zero-area floor of the whole soup the pair belongs to.
    box_*: optional `triangle_boxes` of the object (saves recomputing)."""
    none = np.empty(0, np.int64)
    co_a = np.asarray(co_a, np.float64).reshape(-1, 3)
    co_b = np.asarray(co_b, np.float64).reshape(-1, 3)
    tv_a = np.asarray(tv_a, np.int64).reshape(-1, 3)
    tv_b = np.asarray(tv_b, np.int64).reshape(-1, 3)
    tp_a = np.asarray(tp_a, np.int64).ravel()
    tp_b = np.asarray(tp_b, np.int64).ravel()
    if not len(tv_a) or not len(tv_b):
        return none, none
    lo_a, hi_a = box_a if box_a is not None else triangle_boxes(co_a, tv_a)
    lo_b, hi_b = box_b if box_b is not None else triangle_boxes(co_b, tv_b)
    pad = max(float(distance), 0.0)
    # Only triangles near the other object can be in a cross pair.
    sel_a = np.nonzero(_near_box(lo_a, hi_a, lo_b.min(axis=0),
                                 hi_b.max(axis=0), pad))[0]
    sel_b = np.nonzero(_near_box(lo_b, hi_b, lo_a.min(axis=0),
                                 hi_a.max(axis=0), pad))[0]
    if not len(sel_a) or not len(sel_b):
        return none, none
    ca, ta = _compact(co_a, tv_a[sel_a])
    cb, tb = _compact(co_b, tv_b[sel_b])
    pa = tp_a[sel_a]
    off = int(pa.max()) + 1
    hits = zfight_faces(np.concatenate((ca, cb)),
                        np.concatenate((ta, tb + len(ca))),
                        np.concatenate((pa, tp_b[sel_b] + off)),
                        angle_deg, distance,
                        tri_group=np.repeat((0, 1), (len(sel_a), len(sel_b))),
                        cross_only=True, area_floor=area_floor)
    return hits[hits < off], hits[hits >= off] - off
