"""Pure-Python geometry core for the Converge operator.

No bpy / mathutils / numpy imports -- unit-testable with plain pytest.
Edges are plain ``(v0, v1)`` pairs of 3-tuples of floats. Everything here is
pure: tuples in, tuples out.

Pipeline:
    candidate_pairs(edges, tol) -> [Candidate, ...]
    STRATEGIES[key](candidates, ...) -> filtered/ordered [Candidate, ...]

``strategy_all`` needs the raw ``edges`` and selection ``history`` on top of
the candidates; ``strategy_order`` needs ``history``.

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


def _vert_key(p):
    """Hashable key for a coordinate; verts closer than EPS share a key."""
    q = 1.0 / EPS
    return (round(p[0] * q), round(p[1] * q), round(p[2] * q))


def chains(edges):
    """Split ``edges`` into connected components and return, for every
    component that is one open chain (every vert on <=2 edges, exactly
    two verts on 1 edge, no cycle), ``(first, last, members)`` -- the two
    end edge indices in walk order and all member indices. Components
    that are single edges, closed rings, or branching are skipped."""
    adj = {}
    for i, e in enumerate(edges):
        if dist(e[0], e[1]) < EPS:
            continue
        for p in e:
            adj.setdefault(_vert_key(p), []).append(i)
    edge_keys = {}
    for i, e in enumerate(edges):
        edge_keys[i] = (_vert_key(e[0]), _vert_key(e[1]))

    # connected components over edges
    seen = set()
    out = []
    for start in range(len(edges)):
        if start in seen or start not in edge_keys:
            continue
        if dist(edges[start][0], edges[start][1]) < EPS:
            continue
        comp = set()
        stack = [start]
        while stack:
            i = stack.pop()
            if i in comp:
                continue
            comp.add(i)
            for k in edge_keys[i]:
                stack.extend(j for j in adj[k] if j not in comp)
        seen |= comp
        if len(comp) < 2:
            continue
        # open chain test inside the component
        ends = []
        ok = True
        keys = set()
        for i in comp:
            keys.update(edge_keys[i])
        for k in keys:
            deg = len(adj[k])
            if deg > 2:
                ok = False
                break
            if deg == 1:
                ends.append(k)
        if not ok or len(ends) != 2:
            continue
        # walk end -> end
        key = ends[0]
        prev = None
        first = adj[key][0]
        last = first
        walked = 0
        while True:
            nxt = [i for i in adj[key] if i != prev]
            if not nxt:
                break
            i = nxt[0]
            walked += 1
            last = i
            k0, k1 = edge_keys[i]
            key = k1 if k0 == key else k0
            prev = i
        if walked != len(comp):
            continue
        out.append((first, last, sorted(comp)))
    return out


def chain_ends(edges):
    """``(first, last)`` when ALL of ``edges`` form one open chain, else None."""
    found = chains(edges)
    if len(found) == 1 and len(found[0][2]) == len(edges):
        return found[0][0], found[0][1]
    return None


def _collapse_group(candidates, edges, r0, r1, members):
    """Candidates collapsing ``members`` (minus the rails) into the rails'
    P. None when the rails don't converge."""
    rail_pair = next((c for c in candidates
                      if frozenset((c.i, c.j)) == frozenset((r0, r1))), None)
    if rail_pair is None:
        return None
    P = rail_pair.P
    if rail_pair.i == r0:
        r0_end = rail_pair.moving_end_i
    else:
        r0_end = rail_pair.moving_end_j
    r0_mvert = edges[r0][r0_end]
    out = [rail_pair]
    for k in members:
        if k == r0 or k == r1:
            continue
        e = edges[k]
        if dist(e[0], e[1]) < EPS:
            continue
        for end in (0, 1):
            out.append(Candidate(r0, k, P, P, P, r0_end, end,
                                 r0_mvert, e[end]))
    return out


def strategy_all(candidates, history, edges):
    """Collapse each loop into its rails' convergence point.

    Every open chain in the selection (see ``chains``) is a loop whose
    rails are its first and last edges; its interior edges have BOTH
    ends sent to that loop's ``P``. Loops whose rails don't converge are
    skipped. When the selection holds no chains at all, the first two
    distinct selection-history entries are the rails and every other
    selected edge collapses into their ``P``. Expressed as Candidate
    chains sharing ``P = p1 = p2`` so the pairwise apply path (move +
    weld, alias-chained) collapses each group into one vert. Empty when
    no rails can be determined or none converge.
    """
    out = []
    found = chains(edges)
    for first, last, members in found:
        group = _collapse_group(candidates, edges, first, last, members)
        if group:
            out.extend(group)
    if out or found:
        return out
    rails = []
    for h in history:
        if h not in rails:
            rails.append(h)
        if len(rails) == 2:
            break
    if len(rails) < 2:
        return []
    group = _collapse_group(candidates, edges, rails[0], rails[1],
                            range(len(edges)))
    return group or []


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


# Ordered registry: adding a strategy later = adding one function + one entry.
STRATEGIES = [
    ("GREEDY", strategy_greedy),
    ("ALL", strategy_all),
    ("ORDER", strategy_order),
]
