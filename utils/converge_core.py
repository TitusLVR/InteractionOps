"""Pure-Python geometry core for the Converge operator.

No bpy / mathutils / numpy imports -- unit-testable with plain pytest.
Edges are plain ``(v0, v1)`` pairs of 3-tuples of floats. Everything here is
pure: tuples in, tuples out.

Pipeline:
    candidate_pairs(edges, tol) -> [Candidate, ...]
    STRATEGIES[key](candidates, ...) -> filtered/ordered [Candidate, ...]

A later (bmesh-aware) layer resolves each ``Candidate`` into an actual vert
collapse: move ``edge[i][moving_end_i] -> p1``, ``edge[j][moving_end_j] -> p2``,
then weld the two verts together at ``P`` (bmesh ``pointmerge``).
"""
import math
from collections import namedtuple

# Coplanar tolerance: the max allowed gap between the two lines' closest
# points for a pair to qualify as an intersection.
TOL = 1e-4

# Generic numerical epsilon: parallel/colinear directions, shared-vertex
# coincidence, zero-length edges, and the closest_points_on_lines
# parallel-line degeneracy all use this same tight tolerance.
EPS = 1e-9


# ---------------------------------------------------------------------------
# vector helpers
# ---------------------------------------------------------------------------

def sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def add(a, b):
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def mul(a, s):
    return (a[0] * s, a[1] * s, a[2] * s)


def dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def cross(a, b):
    return (a[1] * b[2] - a[2] * b[1],
            a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0])


def norm(a):
    return math.sqrt(dot(a, a))


def normalize(a):
    l = norm(a)
    if l < EPS:
        return (0.0, 0.0, 0.0)
    return (a[0] / l, a[1] / l, a[2] / l)


def midpoint(a, b):
    return mul(add(a, b), 0.5)


def dist(a, b):
    return norm(sub(a, b))


# ---------------------------------------------------------------------------
# closest points between two infinite lines
# ---------------------------------------------------------------------------

def closest_points_on_lines(a1, a2, b1, b2):
    """Closest points between infinite line a1-a2 and infinite line b1-b2.

    Returns ``(p1, p2)`` with ``p1`` on line a and ``p2`` on line b -- exactly
    equal (up to float error) when the lines actually cross. Returns ``None``
    when the lines are parallel/colinear (including either being degenerate,
    zero-length) -- callers that care about a looser or tighter parallel
    tolerance should check that themselves before calling in.
    """
    d1 = sub(a2, a1)
    d2 = sub(b2, b1)
    r = sub(a1, b1)
    a = dot(d1, d1)
    e = dot(d2, d2)
    b = dot(d1, d2)
    f = dot(d2, r)
    c = dot(d1, r)
    denom = a * e - b * b
    # denom == |d1|^2 * |d2|^2 * sin^2(angle); compare relative to a*e so the
    # parallel verdict depends only on the angle, never on edge lengths
    # (an absolute cutoff falsely rejected mm-scale edges as parallel).
    if abs(denom) <= EPS * a * e:
        return None
    s = (b * f - c * e) / denom
    t = (a * f - b * c) / denom
    p1 = add(a1, mul(d1, s))
    p2 = add(b1, mul(d2, t))
    return (p1, p2)


# ---------------------------------------------------------------------------
# candidate pairs
# ---------------------------------------------------------------------------

Candidate = namedtuple("Candidate", [
    "i", "j",              # indices into the input `edges` sequence, i < j
    "P",                    # intersection point, midpoint(p1, p2)
    "p1", "p2",             # closest points on line i / line j
    "moving_end_i",         # 0 or 1: which endpoint of edges[i] moves to p1
    "moving_end_j",         # 0 or 1: which endpoint of edges[j] moves to p2
    "mvert1", "mvert2",     # the actual moving-vert coordinates (convenience)
])


def _shares_vertex(edge_a, edge_b):
    for va in edge_a:
        for vb in edge_b:
            if dist(va, vb) < EPS:
                return True
    return False


def _nearest_end(edge, p):
    """Index (0 or 1) of the endpoint of `edge` nearest to `p`."""
    return 0 if dist(edge[0], p) <= dist(edge[1], p) else 1


def candidate_pairs(edges, tol=TOL):
    """All qualifying unordered pairs of ``edges``.

    ``edges`` is a sequence of ``(v0, v1)`` 3-tuple pairs. Excludes pairs that
    share a vertex, pairs whose lines are parallel/colinear, and pairs whose
    lines' closest points are farther apart than ``tol``. Zero-length edges
    are skipped entirely (never produce a candidate). Result is ordered by
    ascending ``(i, j)``.
    """
    n = len(edges)
    out = []
    for i in range(n):
        edge_i = edges[i]
        d_i = sub(edge_i[1], edge_i[0])
        if norm(d_i) < EPS:
            continue  # degenerate edge
        nd_i = normalize(d_i)
        for j in range(i + 1, n):
            edge_j = edges[j]
            d_j = sub(edge_j[1], edge_j[0])
            if norm(d_j) < EPS:
                continue  # degenerate edge
            if _shares_vertex(edge_i, edge_j):
                continue
            nd_j = normalize(d_j)
            if norm(cross(nd_i, nd_j)) <= EPS:
                continue  # parallel/colinear

            res = closest_points_on_lines(edge_i[0], edge_i[1], edge_j[0], edge_j[1])
            if res is None:
                continue
            p1, p2 = res
            if dist(p1, p2) > tol:
                continue  # not coplanar within tolerance

            P = midpoint(p1, p2)
            me_i = _nearest_end(edge_i, p1)
            me_j = _nearest_end(edge_j, p2)
            out.append(Candidate(i, j, P, p1, p2, me_i, me_j,
                                  edge_i[me_i], edge_j[me_j]))
    return out


# ---------------------------------------------------------------------------
# strategies
# ---------------------------------------------------------------------------

def _pair_cost(c):
    """Total distance the two moving verts travel to reach the merge point."""
    return dist(c.mvert1, c.P) + dist(c.mvert2, c.P)


def strategy_greedy(candidates):
    """Nearest-sum first; each edge index consumed at most once."""
    ordered = sorted(candidates, key=_pair_cost)
    used = set()
    out = []
    for c in ordered:
        if c.i in used or c.j in used:
            continue
        out.append(c)
        used.add(c.i)
        used.add(c.j)
    return out


def strategy_all(candidates):
    """Every candidate pair, deterministic order by edge-index pair.

    Edges may appear in multiple pairs -- no consumption tracking.
    """
    return sorted(candidates, key=lambda c: (c.i, c.j))


def strategy_order(candidates, history):
    """Pair consecutive selection-history entries, dropping non-qualifiers.

    ``history`` is a flat list of edge indices in selection order:
    ``(history[0], history[1])``, ``(history[2], history[3])``, ... . A
    trailing unpaired entry (odd-length history) is dropped. A history pair
    with no matching candidate (didn't qualify, or wasn't even considered) is
    dropped rather than raising. Empty history returns an empty list.
    """
    lookup = {}
    for c in candidates:
        lookup[frozenset((c.i, c.j))] = c
    out = []
    for k in range(0, len(history) - 1, 2):
        h0, h1 = history[k], history[k + 1]
        if h0 == h1:
            continue
        c = lookup.get(frozenset((h0, h1)))
        if c is not None:
            out.append(c)
    return out


# ---------------------------------------------------------------------------
# apex: one point every edge line converges on
# ---------------------------------------------------------------------------

# Relative tolerance for an edge to count as part of the bundle: its line
# may miss the apex by this fraction of the mean edge length. Looser than
# TOL on purpose -- hand-modelled fans rarely meet in a mathematical point.
APEX_TOL_REL = 0.01


def _solve3(m, b):
    """Solve the 3x3 system ``m @ x = b`` by Cramer's rule. None if singular."""
    (a, bb, c), (d, e, f), (g, h, i) = m
    det = a * (e * i - f * h) - bb * (d * i - f * g) + c * (d * h - e * g)
    if abs(det) < EPS:
        return None

    def rep(col):
        mm = [list(r) for r in m]
        for r in range(3):
            mm[r][col] = b[r]
        (a, bb, c), (d, e, f), (g, h, i) = mm
        return a * (e * i - f * h) - bb * (d * i - f * g) + c * (d * h - e * g)

    return (rep(0) / det, rep(1) / det, rep(2) / det)


def _line_point_dist(a, d, p):
    """Distance from point ``p`` to the line through ``a`` with unit dir ``d``."""
    w = sub(p, a)
    along = dot(w, d)
    return norm(sub(w, mul(d, along)))


def least_squares_lines_point(edges):
    """Point minimising the summed squared distance to every edge's infinite
    line. None for fewer than two non-degenerate, non-parallel lines."""
    m = [[0.0] * 3 for _ in range(3)]
    b = [0.0] * 3
    used = 0
    for e in edges:
        d = normalize(sub(e[1], e[0]))
        if norm(d) < EPS:
            continue
        used += 1
        # (I - d d^T) accumulates; rhs gets (I - d d^T) a
        for r in range(3):
            for c in range(3):
                m[r][c] += (1.0 if r == c else 0.0) - d[r] * d[c]
        a_perp = sub(e[0], mul(d, dot(e[0], d)))
        for r in range(3):
            b[r] += a_perp[r]
    if used < 2:
        return None
    return _solve3(m, b)


def apex_point(edges, tol_rel=APEX_TOL_REL):
    """Find the bundle apex among ``edges``.

    Iteratively fits the least-squares point, drops the edge whose line
    misses it worst while that miss exceeds ``tol_rel * mean_edge_length``,
    and refits. Returns ``(apex, member_indices)`` or ``None`` when fewer
    than two edges remain in the bundle.
    """
    members = [i for i, e in enumerate(edges) if norm(sub(e[1], e[0])) >= EPS]
    if len(members) < 2:
        return None
    mean_len = sum(norm(sub(edges[i][1], edges[i][0])) for i in members) / len(members)
    tol = tol_rel * mean_len
    while len(members) >= 2:
        apex = least_squares_lines_point([edges[i] for i in members])
        if apex is None:
            return None
        worst_i, worst_d = None, -1.0
        for i in members:
            e = edges[i]
            d = _line_point_dist(e[0], normalize(sub(e[1], e[0])), apex)
            if d > worst_d:
                worst_i, worst_d = i, d
        if worst_d <= tol:
            return apex, members
        members.remove(worst_i)
    return None


def strategy_apex(edges, tol_rel=APEX_TOL_REL):
    """Every bundle edge's nearest end goes to the single apex.

    Expressed as a chain of Candidates ``(m0, m1), (m0, m2), ...`` that all
    share ``P = p1 = p2 = apex`` so the pairwise apply path (move + weld,
    alias-chained) collapses the whole bundle into one vert. Empty when no
    bundle exists.
    """
    found = apex_point(edges, tol_rel)
    if found is None:
        return []
    apex, members = found
    ends = {i: _nearest_end(edges[i], apex) for i in members}
    first = members[0]
    out = []
    for j in members[1:]:
        out.append(Candidate(first, j, apex, apex, apex,
                             ends[first], ends[j],
                             edges[first][ends[first]], edges[j][ends[j]]))
    return out


# Ordered registry: adding a strategy later = adding one function + one entry.
# GREEDY/ALL take (candidates); ORDER takes (candidates, history); APEX takes
# the raw (edges) -- it is a fit over all lines, not a pair filter.
STRATEGIES = [
    ("GREEDY", strategy_greedy),
    ("ALL", strategy_all),
    ("ORDER", strategy_order),
    ("APEX", strategy_apex),
]
