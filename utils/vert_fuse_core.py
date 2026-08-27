"""Pure-Python geometry core for the Vert Fuse operator.

No bpy / mathutils / numpy imports -- unit-testable with plain pytest.
Verts are 3-tuples of floats, edges are plain ``(v0, v1)`` pairs of
3-tuples. Everything here is pure: tuples in, tuples out.

Pipeline:
    fuse_candidates(verts, edges, tol, exclude) -> [Candidate, ...]
    MERGE_POSITIONS[key](vert_co, proj) -> merge coordinate

A later (bmesh-aware) layer resolves each ``Candidate`` into an actual
edge split + pointmerge: split ``edges[edge_index]`` at ``t``, then weld
``verts[vert_index]`` with the new split vert at the chosen merge
position.
"""
from collections import namedtuple

from .converge_core import EPS, sub, dot, dist, midpoint, add, mul

# Fuse tolerance: the max allowed gap between a vert and its projection
# on the target edge. Looser than converge's 1e-4 -- T-junction gaps are
# visible-scale modelling slop, not float noise.
TOL = 1e-3


# ---------------------------------------------------------------------------
# projection
# ---------------------------------------------------------------------------

def project_point_on_segment(p, a, b):
    """Project ``p`` onto the infinite line through segment ``a``-``b``.

    Returns ``(t, proj)`` where ``t`` is the UNCLAMPED line parameter
    (``proj = a + t * (b - a)``; ``t`` in [0, 1] means the foot lies on
    the segment) and ``proj`` the point at that unclamped ``t``. Callers
    enforce their own on-segment / interior rule from ``t``.

    Returns ``None`` for a degenerate (zero-length) segment.
    """
    d = sub(b, a)
    dd = dot(d, d)
    if dd < EPS * EPS:
        return None
    t = dot(sub(p, a), d) / dd
    return t, add(a, mul(d, t))


# ---------------------------------------------------------------------------
# candidates
# ---------------------------------------------------------------------------

Candidate = namedtuple("Candidate", [
    "vert_index",   # index into the input `verts` sequence
    "edge_index",   # index into the input `edges` sequence
    "t",            # line parameter of proj on edges[edge_index] (in (0, 1))
    "proj",         # projection point on the edge (3-tuple)
    "dist",         # gap between the vert and proj
])


def fuse_candidates(verts, edges, tol=TOL, exclude=None,
                    vert_islands=None, edge_islands=None):
    """One fuse candidate per vert: its nearest qualifying target edge.

    ``verts`` is a sequence of 3-tuples (the candidate moving verts);
    ``edges`` a sequence of ``(v0, v1)`` 3-tuple pairs; ``exclude`` an
    optional dict ``vert_index -> set(edge_indices)`` of edges that are
    topologically linked to that vert (a vert never fuses into its own
    edges -- the bmesh layer supplies this).

    ``vert_islands`` / ``edge_islands`` are optional island-id sequences
    parallel to ``verts`` / ``edges``. When BOTH are given, an edge whose
    island differs from the vert's is skipped -- and skipped BEFORE the
    nearest-edge pick, so a cross-island nearer edge never shadows a
    same-island farther one (the candidate falls back to it instead).
    With either sequence missing there is no island filtering at all: a
    lone half of the pair carries no per-pair information.

    An edge qualifies for a vert when: it is not excluded and not
    zero-length; neither endpoint coincides with the vert (closer than
    ``EPS`` -- endpoint-to-endpoint is merge-by-distance territory, not
    this op); the projection lands strictly in the segment INTERIOR
    (``0 < t < 1`` and farther than ``EPS`` from each endpoint); and the
    vert-to-projection gap is at most ``tol``.

    Each vert takes its single nearest qualifying edge (min dist,
    ties broken by lowest edge index). Output is ordered by ascending
    ``vert_index``.
    """
    exclude = exclude or {}
    filter_islands = vert_islands is not None and edge_islands is not None
    out = []
    for vi, p in enumerate(verts):
        excluded = exclude.get(vi, ())
        best = None
        for ei, (a, b) in enumerate(edges):
            if ei in excluded:
                continue
            if filter_islands and vert_islands[vi] != edge_islands[ei]:
                continue
            if dist(p, a) < EPS or dist(p, b) < EPS:
                continue  # endpoint-coincident vert
            res = project_point_on_segment(p, a, b)
            if res is None:
                continue  # zero-length edge
            t, proj = res
            if t <= 0.0 or t >= 1.0:
                continue  # foot outside the segment
            if dist(proj, a) <= EPS or dist(proj, b) <= EPS:
                continue  # interior rule: strictly between endpoints
            d = dist(p, proj)
            if d > tol:
                continue
            # tuple compare: min dist first, then lowest edge index
            if best is None or (d, ei) < (best.dist, best.edge_index):
                best = Candidate(vi, ei, t, proj, d)
        if best is not None:
            out.append(best)
    return out


# ---------------------------------------------------------------------------
# merge positions
# ---------------------------------------------------------------------------

def merge_at_project(vert_co, proj):
    """Merge at the projection point -- the target edge stays straight."""
    return proj


def merge_at_vert(vert_co, proj):
    """Merge at the vert's own position -- the target edge bends to it."""
    return vert_co


def merge_at_mid(vert_co, proj):
    """Merge halfway -- both the vert and the edge give a little."""
    return midpoint(vert_co, proj)


# Ordered registry: adding a position later = adding one function + one entry.
MERGE_POSITIONS = [
    ("PROJECT", merge_at_project),
    ("VERT", merge_at_vert),
    ("MID", merge_at_mid),
]
