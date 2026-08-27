import pytest

from utils.converge_core import (
    closest_points_on_lines,
    candidate_pairs,
    strategy_greedy,
    strategy_all,
    strategy_order,
    STRATEGIES,
    TOL,
    EPS,
    sub,
    norm,
    midpoint,
)


# ---------------------------------------------------------------------------
# closest_points_on_lines
# ---------------------------------------------------------------------------

def test_closest_points_coplanar_crossing_lines_intersect_exactly():
    # two segments in the z=0 plane crossing at (1,1,0)
    p1, p2 = closest_points_on_lines((0.0, 0.0, 0.0), (2.0, 2.0, 0.0),
                                      (0.0, 2.0, 0.0), (2.0, 0.0, 0.0))
    assert p1 == pytest.approx((1.0, 1.0, 0.0))
    assert p2 == pytest.approx((1.0, 1.0, 0.0))
    assert p1 == pytest.approx(p2)


def test_closest_points_skew_lines_known_answer():
    # line A along +X at y=0,z=0; line B along +Y at x=1,z=1 -- skew.
    p1, p2 = closest_points_on_lines((0.0, 0.0, 0.0), (2.0, 0.0, 0.0),
                                      (1.0, 0.0, 1.0), (1.0, 2.0, 1.0))
    assert p1 == pytest.approx((1.0, 0.0, 0.0))
    assert p2 == pytest.approx((1.0, 0.0, 1.0))
    assert midpoint(p1, p2) == pytest.approx((1.0, 0.0, 0.5))


def test_closest_points_parallel_lines_returns_none():
    p = closest_points_on_lines((0.0, 0.0, 0.0), (1.0, 0.0, 0.0),
                                 (0.0, 1.0, 0.0), (1.0, 1.0, 0.0))
    assert p is None


def test_closest_points_degenerate_zero_length_line_returns_none():
    # a1 == a2: direction undefined; must not crash
    p = closest_points_on_lines((0.0, 0.0, 0.0), (0.0, 0.0, 0.0),
                                 (0.0, 1.0, 0.0), (1.0, 1.0, 0.0))
    assert p is None


# ---------------------------------------------------------------------------
# candidate_pairs
# ---------------------------------------------------------------------------

def test_candidate_pairs_excludes_shared_vertex():
    edges = [
        ((0.0, 0.0, 0.0), (1.0, 0.0, 0.0)),
        ((0.0, 0.0, 0.0), (0.0, 1.0, 0.0)),  # shares (0,0,0) with edge 0
    ]
    assert candidate_pairs(edges) == []


def test_candidate_pairs_excludes_parallel():
    edges = [
        ((0.0, 0.0, 0.0), (1.0, 0.0, 0.0)),
        ((0.0, 1.0, 0.0), (1.0, 1.0, 0.0)),  # parallel to edge 0
    ]
    assert candidate_pairs(edges) == []


def test_candidate_pairs_coplanar_tolerance_in():
    # skew gap = 5e-5, within default tol (1e-4) -> qualifies
    g = 5e-5
    edges = [
        ((0.0, 0.0, 0.0), (2.0, 0.0, 0.0)),
        ((1.0, 0.0, g), (1.0, 2.0, g)),
    ]
    cands = candidate_pairs(edges)
    assert len(cands) == 1
    c = cands[0]
    assert c.i == 0 and c.j == 1
    assert c.p1 == pytest.approx((1.0, 0.0, 0.0))
    assert c.p2 == pytest.approx((1.0, 0.0, g))
    assert c.P == pytest.approx(midpoint(c.p1, c.p2))


def test_candidate_pairs_coplanar_tolerance_out():
    # skew gap = 5e-4, exceeds default tol (1e-4) -> excluded
    g = 5e-4
    edges = [
        ((0.0, 0.0, 0.0), (2.0, 0.0, 0.0)),
        ((1.0, 0.0, g), (1.0, 2.0, g)),
    ]
    assert candidate_pairs(edges) == []
    # but qualifies with a looser explicit tolerance
    cands = candidate_pairs(edges, tol=1e-3)
    assert len(cands) == 1


def test_candidate_pairs_moving_end_picks_nearest_endpoint():
    edges = [
        ((0.0, 0.0, 0.0), (10.0, 0.0, 0.0)),   # edge 0, long
        ((9.0, -1.0, 0.0), (9.0, 1.0, 0.0)),   # edge 1, crosses edge0 at x=9
    ]
    cands = candidate_pairs(edges)
    assert len(cands) == 1
    c = cands[0]
    # p1 = (9,0,0) is nearer edge0's endpoint (10,0,0) [dist 1] than (0,0,0) [dist 9]
    assert c.moving_end_i == 1
    assert c.mvert1 == pytest.approx((10.0, 0.0, 0.0))
    # p2 = (9,0,0) is equidistant from edge1's endpoints -> ties resolve to 0
    assert c.moving_end_j == 0
    assert c.mvert2 == pytest.approx((9.0, -1.0, 0.0))


def test_candidate_pairs_skips_zero_length_edge_without_crashing():
    edges = [
        ((0.0, 0.0, 0.0), (0.0, 0.0, 0.0)),   # zero-length, index 0
        ((0.0, 0.0, 0.0), (10.0, 0.0, 0.0)),  # index 1
        ((5.0, -1.0, 0.0), (5.0, 1.0, 0.0)),  # index 2, crosses index1 at (5,0,0)
    ]
    cands = candidate_pairs(edges)
    assert len(cands) == 1
    assert (cands[0].i, cands[0].j) == (1, 2)


def test_candidate_pairs_fewer_than_two_edges_returns_empty():
    assert candidate_pairs([]) == []
    assert candidate_pairs([((0.0, 0.0, 0.0), (1.0, 0.0, 0.0))]) == []


# ---------------------------------------------------------------------------
# strategy_greedy
# ---------------------------------------------------------------------------

def test_strategy_greedy_fan_picks_nearer_pair_and_consumes_edge():
    # Edge A is a long shared edge; B crosses near one end (cheap), C crosses
    # far from that end (expensive). Both B and C individually qualify with
    # A, but B and C are parallel to each other so they never pair.
    edge_a = ((0.0, 0.0, 0.0), (10.0, 0.0, 0.0))     # index 0
    edge_b = ((1.0, -1.0, 0.0), (1.0, 1.0, 0.0))      # index 1, crosses A at x=1
    edge_c = ((5.0, -1.0, 0.0), (5.0, 1.0, 0.0))      # index 2, crosses A at x=5
    edges = [edge_a, edge_b, edge_c]
    cands = candidate_pairs(edges)
    assert {(c.i, c.j) for c in cands} == {(0, 1), (0, 2)}

    result = strategy_greedy(cands)
    assert len(result) == 1
    assert (result[0].i, result[0].j) == (0, 1)


def test_strategy_greedy_each_edge_used_at_most_once():
    edge_a = ((0.0, 0.0, 0.0), (10.0, 0.0, 0.0))
    edge_b = ((1.0, -1.0, 0.0), (1.0, 1.0, 0.0))
    edge_c = ((5.0, -1.0, 0.0), (5.0, 1.0, 0.0))
    cands = candidate_pairs([edge_a, edge_b, edge_c])
    result = strategy_greedy(cands)
    used = [idx for c in result for idx in (c.i, c.j)]
    assert len(used) == len(set(used))


# ---------------------------------------------------------------------------
# strategy_all
# ---------------------------------------------------------------------------

def test_strategy_all_deterministic_order_and_repeated_edges():
    # three lines concurrent at (2,2,0), all pairwise qualifying, no shared verts
    edge0 = ((0.0, 0.0, 0.0), (4.0, 4.0, 0.0))
    edge1 = ((0.0, 4.0, 0.0), (4.0, 0.0, 0.0))
    edge2 = ((2.0, -2.0, 0.0), (2.0, 6.0, 0.0))
    cands = candidate_pairs([edge0, edge1, edge2])
    assert {(c.i, c.j) for c in cands} == {(0, 1), (0, 2), (1, 2)}

    shuffled = list(reversed(cands))
    result = strategy_all(shuffled)
    assert [(c.i, c.j) for c in result] == [(0, 1), (0, 2), (1, 2)]

    used = [idx for c in result for idx in (c.i, c.j)]
    assert used.count(0) == 2  # edge 0 appears in two pairs -- repeats allowed


# ---------------------------------------------------------------------------
# strategy_order
# ---------------------------------------------------------------------------

def test_strategy_order_pairs_by_history_and_drops_non_qualifying():
    edge0 = ((0.0, 0.0, 0.0), (10.0, 0.0, 0.0))
    edge1 = ((1.0, -1.0, 0.0), (1.0, 1.0, 0.0))       # qualifies with edge0
    edge2 = ((0.0, 0.0, 5.0), (1.0, 0.0, 5.0))         # parallel to edge0
    edge3 = ((0.0, 1.0, 5.0), (1.0, 1.0, 5.0))         # parallel to edge0 and edge2
    cands = candidate_pairs([edge0, edge1, edge2, edge3])
    assert {(c.i, c.j) for c in cands} == {(0, 1)}

    result = strategy_order(cands, [0, 1, 2, 3])
    assert len(result) == 1
    assert (result[0].i, result[0].j) == (0, 1)


def test_strategy_order_empty_history_returns_empty():
    edge0 = ((0.0, 0.0, 0.0), (10.0, 0.0, 0.0))
    edge1 = ((1.0, -1.0, 0.0), (1.0, 1.0, 0.0))
    cands = candidate_pairs([edge0, edge1])
    assert strategy_order(cands, []) == []


def test_strategy_order_odd_trailing_entry_dropped():
    edge0 = ((0.0, 0.0, 0.0), (10.0, 0.0, 0.0))
    edge1 = ((1.0, -1.0, 0.0), (1.0, 1.0, 0.0))
    cands = candidate_pairs([edge0, edge1])
    # trailing "2" has no partner and must not raise or be paired
    result = strategy_order(cands, [0, 1, 2])
    assert len(result) == 1
    assert (result[0].i, result[0].j) == (0, 1)


# ---------------------------------------------------------------------------
# STRATEGIES registry
# ---------------------------------------------------------------------------

def test_strategies_registry_ordered_and_contains_all_three():
    keys = [key for key, _fn in STRATEGIES]
    assert keys == ["GREEDY", "ALL", "ORDER"]
    fn_by_key = dict(STRATEGIES)
    assert fn_by_key["GREEDY"] is strategy_greedy
    assert fn_by_key["ALL"] is strategy_all
    assert fn_by_key["ORDER"] is strategy_order


# ---------------------------------------------------------------------------
# module constants sanity
# ---------------------------------------------------------------------------

def test_module_constants():
    assert TOL == pytest.approx(1e-4)
    assert EPS == pytest.approx(1e-9)
    assert norm(sub((3.0, 4.0, 0.0), (0.0, 0.0, 0.0))) == pytest.approx(5.0)


def test_closest_points_small_scale_not_parallel():
    # perpendicular 5mm edges: scale must not affect the parallel verdict
    for L in (0.005, 0.001, 1e-4):
        r = closest_points_on_lines(
            (0.0, 0.0, 0.0), (L, 0.0, 0.0),
            (2 * L, L, 0.0), (2 * L, 2 * L, 0.0))
        assert r is not None, f"falsely parallel at L={L}"
        p1, p2 = r
        assert p1 == pytest.approx((2 * L, 0.0, 0.0))
        assert p2 == pytest.approx((2 * L, 0.0, 0.0))


def test_candidate_pairs_small_scale():
    L = 0.005
    e1 = ((0.0, 0.0, 0.0), (L, 0.0, 0.0))
    e2 = ((2 * L, L, 0.0), (2 * L, 2 * L, 0.0))
    cands = candidate_pairs([e1, e2])
    assert len(cands) == 1
    assert cands[0].P == pytest.approx((2 * L, 0.0, 0.0))


def test_closest_points_still_parallel_when_parallel():
    # genuinely parallel small edges must still return None
    L = 0.005
    assert closest_points_on_lines(
        (0.0, 0.0, 0.0), (L, 0.0, 0.0),
        (0.0, L, 0.0), (L, L, 0.0)) is None
