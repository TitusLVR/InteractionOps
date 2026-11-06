"""Topology checks for Smart Edge Slide's destructive cuts, on real BMesh data (Blender only: bmesh, mathutils).

``tests/blender/test_smart_edge_slide.py`` holds a mesh's ``snapshot`` before a cut and asks ``problems``
what the cut broke (anti-goal 2): edges crossing without a vertex, zero-length edges, faces repeating a vertex, new
vertices off the old surface, overlapping faces. Distances are worked out in float64 with numpy. Tasks 4-7 extend it.
"""
from types import SimpleNamespace

import numpy as np
from mathutils import Vector


def snapshot(bm):
    """What the topology checks hold a cut mesh against: the mesh before the cut, its triangles in float64."""
    return SimpleNamespace(
        verts=set(bm.verts), area=sum(f.calc_area() for f in bm.faces),
        segments=np.array([[e.verts[0].co[:], e.verts[1].co[:]] for e in bm.edges]),
        tris=np.array([[lp.vert.co[:] for lp in tri] for tri in bm.calc_loop_triangles()], dtype=float))


def surface_distance(p, tris):
    """Distance from ``p`` to the nearest of ``tris`` (rows of three 3D corners), in float64.

    (BVHTree.find_nearest works in float32, which on a long sliver triangle is off by 1e-5.)
    """
    p = np.asarray(p, dtype=float)
    a, b, c = tris[:, 0], tris[:, 1], tris[:, 2]
    n = np.cross(b - a, c - a)
    nn = np.maximum(np.einsum("ij,ij->i", n, n), 1e-30)
    off = np.einsum("ij,ij->i", p - a, n)
    q = p - (off / nn)[:, None] * n                                # p dropped onto each triangle's plane
    inside = np.ones(len(tris), dtype=bool)
    for u, v in ((a, b), (b, c), (c, a)):
        inside &= np.einsum("ij,ij->i", np.cross(v - u, q - u), n) >= 0.0
    edges = np.min([point_segment_distances(p, u, v) for u, v in ((a, b), (b, c), (c, a))], axis=0)
    return float(np.min(np.where(inside, np.abs(off) / np.sqrt(nn), edges)))


def point_segment_distances(p, q0, q1):
    """Distances from point ``p`` to each segment q0[i]-q1[i] (rows of 3D points)."""
    d = q1 - q0
    t = np.clip(np.einsum("ij,ij->i", p - q0, d) / np.maximum(np.einsum("ij,ij->i", d, d), 1e-30), 0.0, 1.0)
    return np.linalg.norm(q0 + t[:, None] * d - p, axis=1)


def segment_distances(p0, p1, q0, q1):
    """Distances between segment p0-p1 and each segment q0[i]-q1[i], by closest points (rows of 3D points)."""
    d1, d2, r = p1 - p0, q1 - q0, p0 - q0
    a, e, f = d1 @ d1, np.einsum("ij,ij->i", d2, d2), np.einsum("ij,ij->i", d2, r)
    c, b = r @ d1, d2 @ d1
    denom = a * e - b * b
    with np.errstate(divide="ignore", invalid="ignore"):
        s = np.where(denom > 1e-30, np.clip((b * f - c * e) / denom, 0.0, 1.0), 0.0)
        t = np.where(e > 1e-30, (b * s + f) / e, 0.0)
        s = np.where(t < 0.0, np.clip(-c / a, 0.0, 1.0), np.where(t > 1.0, np.clip((b - c) / a, 0.0, 1.0), s))
    t = np.clip(t, 0.0, 1.0)
    return np.linalg.norm(p0 + s[:, None] * d1 - (q0 + t[:, None] * d2), axis=1)


def problems(bm, before, tol=1e-6):
    """Anti-goal 2 on a cut mesh, against its ``snapshot``: what is wrong with it, [] when nothing.

    No edge shorter than ``tol``; no face repeating a vertex; every new vertex within 1e-5 of the old surface; the
    faces' total area unchanged (no faces overlap or fold over); and no new edge (one that does not lie along an
    old edge) coming within ``tol`` of an edge it shares no vertex with: no crossing without a vertex.
    """
    out = []
    for seq in (bm.verts, bm.edges, bm.faces):  # the indices named below are current ones
        seq.index_update()
    edges = list(bm.edges)
    out += [f"edge {e.index} is {e.calc_length():.1e} long" for e in edges if e.calc_length() < tol]
    out += [f"face {f.index} repeats a vertex" for f in bm.faces if len(set(f.verts)) < len(f.verts)]
    for v in bm.verts:
        if v not in before.verts:
            gap = surface_distance(v.co, before.tris)
            if gap > 1e-5:
                out.append(f"new vertex {tuple(round(c, 6) for c in v.co)} lies {gap:.1e} off the surface")
    area = sum(f.calc_area() for f in bm.faces)
    if abs(area - before.area) > 1e-5 * max(1.0, before.area):
        out.append(f"the faces' area changed from {before.area:.6f} to {area:.6f}")
    seg = np.array([[e.verts[0].co[:], e.verts[1].co[:]] for e in edges])
    ids = np.array([[e.verts[0].index, e.verts[1].index] for e in edges])
    for i, (a, b) in enumerate(ids):
        if along_old(before, seg[i, 0], seg[i, 1], tol):
            continue
        apart = (ids[:, 0] != a) & (ids[:, 0] != b) & (ids[:, 1] != a) & (ids[:, 1] != b)
        near = np.nonzero(apart & (segment_distances(seg[i, 0], seg[i, 1], seg[:, 0], seg[:, 1]) <= tol))[0]
        out += [f"new edge {i} meets edge {j} without a vertex" for j in near]
    return out


def along_old(before, p, q, tol=1e-6):
    """Whether the edge p-q lies along an edge of the mesh before the cut: that edge, or a part of it."""
    q0, q1 = before.segments[:, 0], before.segments[:, 1]
    p, q = np.asarray(p, dtype=float), np.asarray(q, dtype=float)
    return bool(((point_segment_distances(p, q0, q1) <= tol) & (point_segment_distances(q, q0, q1) <= tol)).any())


def vertex_at(bm, co, tol=1e-5):
    co = Vector(co)
    return next((v for v in bm.verts if (v.co - co).length <= tol), None)


def distance_to_segment(p, a, b):
    t = max(0.0, min(1.0, (p - a).dot(b - a) / max((b - a).length_squared, 1e-30)))
    return (a + (b - a) * t - p).length


def edge_across_a_break(bm, cut, before):
    """The breaks of ``cut`` whose two points a new edge joins in ``bm``.

    Points welded onto one vertex are fine, and so is the part of a wall edge both points split (``along_old``), and an
    edge the loop has between two neighbouring points elsewhere: two rings that touch share a vertex, and the edge the
    one ring has from it is no edge across the break before the other.
    """
    n = len(cut.points)
    breaks = set(cut.breaks)
    ring_end = {}  # each ring's last point: its edge on to its first
    starts = sorted(breaks)
    for k, s in enumerate(starts):
        if s in getattr(cut, "rings", ()):
            ring_end[(starts[k + 1] if k + 1 < len(starts) else n) - 1] = s
    joined = set()
    for j in range(n):
        nxt = ring_end.get(j, j + 1 if j + 1 < n and j + 1 not in breaks else None)
        if nxt is not None:
            a, b = vertex_at(bm, cut.points[j].co), vertex_at(bm, cut.points[nxt].co)
            if a is not None and b is not None:
                joined.add(frozenset((a, b)))
    out = []
    for i in cut.breaks:
        a, b = (vertex_at(bm, cut.points[j].co) for j in ((i - 1) % len(cut.points), i))
        if a is not None and b is not None and a is not b and bm.edges.get((a, b)) is not None:
            if not along_old(before, a.co, b.co) and frozenset((a, b)) not in joined:
                out.append(i)
    return out
