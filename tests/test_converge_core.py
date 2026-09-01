import pytest

from utils.converge_core import (
    closest_points_on_lines,
    candidate_pairs,
    strategy_greedy,
    strategy_all,
    chain_ends,
    chains,
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
    # skew gap = 5e-5, within default tol (1e-4) -> miss <= 1
    g = 5e-5
    edges = [
        ((0.0, 0.0, 0.0), (2.0, 0.0, 0.0)),
        ((1.0, 0.0, g), (1.0, 2.0, g)),
    ]
    cands = candidate_pairs(edges)
    assert len(cands) == 1
    c = cands[0]
    assert c.i == 0 and c.j == 1
    assert c.miss <= 1.0
    assert c.p1 == pytest.approx((1.0, 0.0, 0.0))
    assert c.p2 == pytest.approx((1.0, 0.0, g))
    assert c.P == pytest.approx(midpoint(c.p1, c.p2))


def test_candidate_pairs_gap_never_rejects_only_scores():
    # skew gap = 5e-2: way past the gate (max(1e-4, 1e-3 * 2m) = 2e-3).
    # The pair is still GENERATED (miss > 1); rejecting outright is the
    # gate's job at strategy level, not generation level.
    g = 5e-2
    edges = [
        ((0.0, 0.0, 0.0), (2.0, 0.0, 0.0)),
        ((1.0, 0.0, g), (1.0, 2.0, g)),
    ]
    cands = candidate_pairs(edges)
    assert len(cands) == 1
    assert cands[0].miss > 1.0
    # a looser explicit tolerance brings the same pair under the gate
    cands = candidate_pairs(edges, tol=1e-1)
    assert cands[0].miss <= 1.0


def test_strategy_greedy_two_edge_selection_always_converges():
    # TinyCAD VTX parity: exactly two selected edges are an EXPLICIT pair
    # -- greedy takes the single candidate even when its gap fails the
    # gate (2m edges, 5cm apart).
    edges = [
        ((0.0, 0.0, 0.0), (2.0, 0.0, 0.0)),
        ((1.0, -1.0, 0.05), (1.0, 1.0, 0.05)),
    ]
    cands = candidate_pairs(edges)
    assert len(cands) == 1 and cands[0].miss > 1.0
    result = strategy_greedy(cands)
    assert len(result) == 1
    assert result[0].P == pytest.approx((1.0, 0.0, 0.025))


def test_strategy_greedy_gate_discriminates_with_competition():
    # 3+ edges: the gate is back on. B crosses A cleanly; C misses A by
    # 5cm. Greedy must weld only (A, B) and leave C unconsumed -- NOT
    # fall back to the failing (A, C) pair.
    edge_a = ((0.0, 0.0, 0.0), (10.0, 0.0, 0.0))
    edge_b = ((1.0, -1.0, 0.0), (1.0, 1.0, 0.0))
    edge_c = ((5.0, -1.0, 0.05), (5.0, 1.0, 0.05))   # parallel to B
    cands = candidate_pairs([edge_a, edge_b, edge_c])
    assert {(c.i, c.j) for c in cands} == {(0, 1), (0, 2)}
    by_pair = {(c.i, c.j): c for c in cands}
    assert by_pair[(0, 1)].miss <= 1.0
    assert by_pair[(0, 2)].miss > 1.0
    result = strategy_greedy(cands)
    assert [(c.i, c.j) for c in result] == [(0, 1)]


def test_candidate_pairs_meter_scale_near_coplanar_gap_qualifies():
    # Regression (coverge_bug.blend "converge_issue", freestyle-marked
    # pairs): meter-scale edges in parallel planes ~2.7e-4 apart. The old
    # absolute 1e-4 gate rejected both pairs while TinyCAD converged them.
    e0 = ((4.61834478, -2.27786684, 1.93474042),
          (5.05177879, -2.27787328, 0.79056448))
    e2 = ((5.06107378, -2.27814221, -0.76827329),
          (5.06153011, -2.27814221, 0.73419374))
    e3 = ((4.61834478, -1.24363303, 1.93474042),
          (5.05177879, -1.24363947, 0.79056448))
    e5 = ((5.06107378, -1.24390841, -0.76827329),
          (5.06153011, -1.24390841, 0.73419374))
    result = strategy_greedy(candidate_pairs([e0, e2, e3, e5]))
    assert {frozenset((c.i, c.j)) for c in result} == \
        {frozenset((0, 1)), frozenset((2, 3))}
    for c in result:
        assert c.miss <= 1.0
        assert c.P == pytest.approx(midpoint(c.p1, c.p2))


def test_candidate_pairs_short_stub_long_rail_gap_qualifies():
    # Regression (coverge_bug.blend "not_fixed", freestyle-marked pairs):
    # a 2.7cm stub against a 2.5m rail, lines ~1.95e-4 apart. Scaling the
    # relative gate by the SHORTER edge collapsed it to the absolute
    # floor and rejected the pair; the gate must scale with the longer
    # edge (angular noise displaces a line proportionally to its length).
    e1 = ((2.84493947, 2.98475146, 0.00314691),
          (2.84436774, 2.98470998, 0.03010893))
    e2 = ((2.84406638, 2.98032284, 0.03652979),
          (2.84193897, 0.63875312, 0.89197898))
    e4 = ((2.38721228, 2.90496826, -0.00332992),
          (2.38664055, 2.90492678, 0.02363211))
    e5 = ((2.38633919, 2.90053964, 0.03005296),
          (2.38421178, 0.55896986, 0.88550216))
    result = strategy_greedy(candidate_pairs([e1, e2, e4, e5]))
    assert {frozenset((c.i, c.j)) for c in result} == \
        {frozenset((0, 1)), frozenset((2, 3))}
    for c in result:
        assert c.miss <= 1.0


def test_candidate_pairs_relative_gate_never_tightens_small_scale():
    # 5mm edges with a 5e-5 gap: relative term (1e-3 * 0.005 = 5e-6) is
    # tighter than the absolute floor -- the floor must still win.
    L = 0.005
    g = 5e-5
    edges = [
        ((0.0, 0.0, 0.0), (L, 0.0, 0.0)),
        ((L / 2, -L, g), (L / 2, L, g)),
    ]
    cands = candidate_pairs(edges)
    assert len(cands) == 1
    assert cands[0].miss <= 1.0


def test_strategy_order_ignores_gap_gate_for_explicit_pairs():
    # ORDER pairs come from selection history -- the user named them, so
    # the gap gate never drops one (TinyCAD parity for explicit pairs).
    edge_a = ((0.0, 0.0, 0.0), (10.0, 0.0, 0.0))
    edge_b = ((1.0, -1.0, 0.0), (1.0, 1.0, 0.0))
    edge_c = ((5.0, -1.0, 0.05), (5.0, 1.0, 0.05))
    edge_d = ((6.0, 0.0, -1.0), (6.0, 0.0, 1.0))
    cands = candidate_pairs([edge_a, edge_b, edge_c, edge_d])
    result = strategy_order(cands, [2, 0, 1, 3])   # (C, A) then (B, D)
    assert [(c.i, c.j) for c in result] == [(0, 2), (1, 3)]


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
# strategy_all (rails + collapse)
# ---------------------------------------------------------------------------

RAIL_A = ((0.0, 2.0, 0.0), (1.0, 2.0, 0.0))    # -> P=(2,2,0) along +x
RAIL_B = ((2.0, 0.0, 0.0), (2.0, 1.0, 0.0))    # -> P along +y
LOOP = [((1.0, 2.0, 0.0), (1.5, 1.5, 0.0)),
        ((1.5, 1.5, 0.0), (2.0, 1.0, 0.0))]
P = (2.0, 2.0, 0.0)


def test_chain_ends_open_chain_any_order():
    edges = [LOOP[1], RAIL_A, RAIL_B, LOOP[0]]     # shuffled chain
    ends = chain_ends(edges)
    assert ends is not None
    assert frozenset(ends) == frozenset((1, 2))


def test_chain_ends_none_for_disconnected_closed_or_branching():
    assert chain_ends([RAIL_A, RAIL_B]) is None                 # disconnected
    sq = [((0, 0, 0), (1, 0, 0)), ((1, 0, 0), (1, 1, 0)),
          ((1, 1, 0), (0, 1, 0)), ((0, 1, 0), (0, 0, 0))]
    assert chain_ends(sq) is None                               # closed
    branch = [RAIL_A, LOOP[0], ((1.0, 2.0, 0.0), (1.0, 3.0, 0.0))]
    assert chain_ends(branch) is None                           # vert on 3 edges


def test_strategy_all_loop_rails_are_chain_ends_regardless_of_history():
    edges = [LOOP[0], RAIL_B, LOOP[1], RAIL_A]
    cands = candidate_pairs(edges)
    out = strategy_all(cands, [0, 2], edges)   # history points at loop edges
    assert frozenset((out[0].i, out[0].j)) == frozenset((1, 3))
    assert out[0].P == pytest.approx(P)
    tail = out[1:]
    assert len(tail) == 4
    assert {(c.j, c.moving_end_j) for c in tail} == {(0, 0), (0, 1), (2, 0), (2, 1)}
    for c in tail:
        assert c.i == out[0].i or c.i == out[0].j
        assert c.P == pytest.approx(P)
        assert c.p1 == pytest.approx(P)
        assert c.p2 == pytest.approx(P)


def test_strategy_all_falls_back_to_history_when_not_a_chain():
    stray = ((5.0, 5.0, 1.0), (6.0, 5.0, 1.0))
    edges = [RAIL_A, RAIL_B, stray]
    cands = candidate_pairs(edges)
    out = strategy_all(cands, [1, 1, 0], edges)  # duplicate history entry
    assert frozenset((out[0].i, out[0].j)) == frozenset((0, 1))
    assert {(c.j, c.moving_end_j) for c in out[1:]} == {(2, 0), (2, 1)}
    assert strategy_all(cands, [0], edges) == []
    assert strategy_all(cands, [], edges) == []


def test_strategy_all_multiple_loops_each_get_their_own_P():
    def shift(e, dz):
        return tuple((x, y, z + dz) for x, y, z in e)
    loop2 = [shift(e, 5.0) for e in [RAIL_A] + LOOP + [RAIL_B]]
    edges = [RAIL_A] + LOOP + [RAIL_B] + loop2
    cands = candidate_pairs(edges)
    out = strategy_all(cands, [], edges)
    ps = {tuple(round(x, 6) for x in c.P) for c in out}
    assert ps == {P, (2.0, 2.0, 5.0)}
    # 1 rail pair + 2 loop edges * 2 ends, per loop
    assert len(out) == 2 * (1 + 4)
    assert len(chains(edges)) == 2


def test_strategy_all_empty_when_rails_dont_converge():
    par = ((0.0, 3.0, 0.0), (1.0, 3.0, 0.0))     # parallel to RAIL_A
    edges = [RAIL_A, par]
    assert strategy_all(candidate_pairs(edges), [0, 1], edges) == []


# ---------------------------------------------------------------------------
# strategy_order
# ---------------------------------------------------------------------------

def test_strategy_order_pairs_by_history_and_drops_non_qualifying():
    edge0 = ((0.0, 0.0, 0.0), (10.0, 0.0, 0.0))
    edge1 = ((1.0, -1.0, 0.0), (1.0, 1.0, 0.0))       # qualifies with edge0
    edge2 = ((0.0, 0.0, 5.0), (1.0, 0.0, 5.0))         # parallel to edge0
    edge3 = ((0.0, 1.0, 5.0), (1.0, 1.0, 5.0))         # parallel to edge0 and edge2
    cands = candidate_pairs([edge0, edge1, edge2, edge3])
    # (0,1) is the only clean crossing; (1,2)/(1,3) are generated too
    # (non-parallel) but score miss > 1
    assert {(c.i, c.j) for c in cands if c.miss <= 1.0} == {(0, 1)}

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
