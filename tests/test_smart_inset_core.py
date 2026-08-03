import math
import pytest

from utils.smart_inset_core import (
    edge_normal, vertex_velocity, EPS, norm, sub,
)


def test_edge_normal_points_left_of_direction():
    # edge along +X, CCW outer loop -> inward normal is +Y
    n = edge_normal((0.0, 0.0), (2.0, 0.0))
    assert n == pytest.approx((0.0, 1.0))


def test_velocity_straight_vertex():
    # collinear edges: velocity equals the shared inward normal
    n = (0.0, 1.0)
    v = vertex_velocity(n, n, 1.0, 1.0)
    assert v == pytest.approx((0.0, 1.0))


def test_velocity_right_angle():
    # square corner at origin: edges +X then +Y, normals (0,1) and (-1,0)
    v = vertex_velocity((0.0, 1.0), (-1.0, 0.0), 1.0, 1.0)
    assert v == pytest.approx((-1.0, 1.0))
    assert math.hypot(*v) == pytest.approx(math.sqrt(2.0))


def test_velocity_reflex_vertex():
    # reflex corner (270 deg interior): normals (0,1) and (1,0)
    # velocity must satisfy both plane constraints
    v = vertex_velocity((0.0, 1.0), (1.0, 0.0), 1.0, 1.0)
    assert v[0] == pytest.approx(1.0)
    assert v[1] == pytest.approx(1.0)


def test_velocity_zero_weight_slides_along_fixed_edge():
    # prev edge weight 0 (open border, use_boundary off):
    # vertex must stay ON the prev edge line while offsetting from next
    n_prev, n_next = (0.0, 1.0), (-1.0, 0.0)
    v = vertex_velocity(n_prev, n_next, 0.0, 1.0)
    assert v == pytest.approx((-1.0, 0.0))  # slides along the fixed edge


def test_velocity_spike_is_capped():
    # near-opposite normals (theta -> 0 spike): finite result, no NaN/inf
    v = vertex_velocity((0.0, 1.0), (1e-12, -1.0), 1.0, 1.0)
    assert all(math.isfinite(c) for c in v)
    assert math.hypot(*v) <= 1e6  # SPEED_CAP


from utils.smart_inset_core import build_timeline


SQUARE = [[(0.0, 0.0), (2.0, 0.0), (2.0, 2.0), (0.0, 2.0)]]
RECT41 = [[(0.0, 0.0), (4.0, 0.0), (4.0, 1.0), (0.0, 1.0)]]


def test_square_collapses_to_point_at_half_width():
    tl = build_timeline(SQUARE)
    assert tl.max_t == pytest.approx(1.0)
    assert tl.first_event_t == pytest.approx(1.0)
    # all four walls meet in one node at the center
    center_nodes = [n for n in tl.nodes if n.pos == pytest.approx((1.0, 1.0))]
    assert center_nodes, "expected a skeleton node at the square center"


def test_rect_collapses_to_medial_segment():
    tl = build_timeline(RECT41)
    assert tl.first_event_t == pytest.approx(0.5)
    assert tl.max_t == pytest.approx(0.5)
    node_pos = sorted(tuple(round(c, 6) for c in n.pos) for n in tl.nodes)
    assert (0.5, 0.5) in node_pos
    assert (3.5, 0.5) in node_pos


def test_vertex_positions_linear_before_first_event():
    tl = build_timeline(SQUARE)
    v = tl.verts[0]  # corner (0,0), velocity (1,1)
    t = 0.25
    pos = (v.P0[0] + v.V[0] * t, v.P0[1] + v.V[1] * t)
    assert pos == pytest.approx((0.25, 0.25))


def _perp_dist(p, a, b):
    n = edge_normal(a, b)
    return n[0] * (p[0] - a[0]) + n[1] * (p[1] - a[1])


def test_square_front_at_half():
    tl = build_timeline(SQUARE)
    loops = tl.front_at(0.5)
    assert len(loops) == 1 and len(loops[0]) == 4
    for vid in loops[0]:
        p = tl.pos_at(vid, 0.5)
        # even-offset invariant: distance to every original edge >= t,
        # to the two defining edges == t
        d = _perp_dist(p, (0.0, 0.0), (2.0, 0.0))
        assert d >= 0.5 - 1e-6


def test_square_front_empty_after_collapse():
    tl = build_timeline(SQUARE)
    assert tl.front_at(1.5) == []


def test_even_offset_invariant_square():
    tl = build_timeline(SQUARE)
    t = 0.7
    sq = SQUARE[0]
    for vid in tl.front_at(t)[0]:
        p = tl.pos_at(vid, t)
        dists = [_perp_dist(p, sq[i], sq[(i + 1) % 4]) for i in range(4)]
        assert min(dists) == pytest.approx(t, abs=1e-6)


def test_rect_walls_at_full_collapse():
    tl = build_timeline(RECT41)
    walls = tl.walls_at(0.5)
    # bottom edge (id 0, from (0,0) to (4,0)): top chain is the medial
    # segment endpoints, ordered from the b side: (3.5,.5) then (0.5,.5)
    chain = walls[0]
    assert len(chain) == 2
    assert chain[0] == pytest.approx((3.5, 0.5), abs=1e-6)
    assert chain[1] == pytest.approx((0.5, 0.5), abs=1e-6)
    # short left edge (id 3): collapses into a single node
    assert len(walls[3]) == 1
    assert walls[3][0] == pytest.approx((0.5, 0.5), abs=1e-6)


def test_rect_walls_before_any_event_are_offset_edges():
    tl = build_timeline(RECT41)
    walls = tl.walls_at(0.25)
    chain = walls[0]
    assert len(chain) == 2
    assert all(p[1] == pytest.approx(0.25) for p in chain)


LSHAPE = [[(0.0, 0.0), (4.0, 0.0), (4.0, 1.0), (1.0, 1.0),
           (1.0, 3.0), (0.0, 3.0)]]  # CCW, reflex at (1,1)

SQUARE_WITH_HOLE = [
    [(0.0, 0.0), (4.0, 0.0), (4.0, 4.0), (0.0, 4.0)],          # outer CCW
    [(1.5, 1.5), (1.5, 2.5), (2.5, 2.5), (2.5, 1.5)],          # hole CW
]


def test_lshape_splits_into_two_fronts():
    tl = build_timeline(LSHAPE)
    # first events collapse the two 1-wide arms at t=0.5;
    # front at t=0.4 must still be a single loop
    assert len(tl.front_at(0.4)) == 1
    assert tl.max_t == pytest.approx(0.5, abs=1e-6)


def test_star_reflex_survives():
    # 4-point star: reflex verts trigger splits, everything dies eventually
    outer, inner = 2.0, 0.6
    pts = []
    for i in range(8):
        r = outer if i % 2 == 0 else inner
        a = math.pi * i / 4.0
        pts.append((r * math.cos(a), r * math.sin(a)))
    tl = build_timeline([pts])
    assert tl.max_t > 0.0
    assert tl.front_at(tl.max_t + 0.1) == []
    # front just before first event is one loop of 8
    t = tl.first_event_t * 0.5
    loops = tl.front_at(t)
    assert len(loops) == 1 and len(loops[0]) == 8


def test_hole_wave_meets_outer_wave():
    tl = build_timeline(SQUARE_WITH_HOLE)
    # band between hole and outer is 1.5 wide -> fronts meet at t=0.75
    assert tl.max_t == pytest.approx(0.75, abs=1e-3)
    # before that: two loops (outer shrinking, hole growing)
    loops = tl.front_at(0.3)
    assert len(loops) == 2


def test_playback_positions_continuous_across_events():
    tl = build_timeline(LSHAPE)
    t_ev = tl.first_event_t
    for vid in {v for loop in tl.front_at(t_ev - 1e-4) for v in loop}:
        p_before = tl.pos_at(vid, t_ev - 1e-4)
        p_after = tl.pos_at(vid, t_ev + 1e-4)  # clamped to death pos
        assert norm(sub(p_after, p_before)) < 1e-2


# 8x4 plate with a 1x1 hole off-centre near the lower-left corner. The hole's
# outward wave reaches the outer wave at the (0,0) corner first, so the two
# LAVs *merge* into one loop -- the split event's loop-merging direction.
OFFCENTRE_HOLE = [
    [(0.0, 0.0), (8.0, 0.0), (8.0, 4.0), (0.0, 4.0)],   # outer CCW
    [(1.0, 1.0), (1.0, 2.0), (2.0, 2.0), (2.0, 1.0)],   # hole CW
]

# A 1-wide notch cut 2.5 deep into the top edge. Both notch corners are reflex
# and hit the bottom edge's front at t=0.75, splitting the single LAV into two
# independent loops -- the split event's loop-splitting direction.
NOTCH = [[(0.0, 0.0), (6.0, 0.0), (6.0, 4.0), (3.5, 4.0), (3.5, 1.5),
          (2.5, 1.5), (2.5, 4.0), (0.0, 4.0)]]


def _loop_lens(tl, t):
    return sorted(len(loop) for loop in tl.front_at(t))


def test_offcentre_hole_front_merges_into_single_loop():
    tl = build_timeline(OFFCENTRE_HOLE)
    # before the split: outer loop + hole loop, 4 verts each
    assert len(tl.front_at(0.4)) == 2
    assert _loop_lens(tl, 0.4) == [4, 4]
    # hole corner (1,1) travels at (-1,-1) and meets the bottom/left fronts
    # at (0.5,0.5) -> t=0.5; the two loops become one loop of 6
    assert tl.first_event_t == pytest.approx(0.5, abs=1e-6)
    assert len(tl.front_at(0.5)) == 1
    assert _loop_lens(tl, 0.5) == [6]
    assert _loop_lens(tl, 0.7) == [6]
    # everything finally collapses onto the 8x4 plate's medial axis at t=2
    assert tl.max_t == pytest.approx(2.0, abs=1e-6)
    assert tl.front_at(2.0 + 1e-6) == []


def test_notch_splits_front_into_two_loops():
    tl = build_timeline(NOTCH)
    # before the split: one loop of 8
    assert len(tl.front_at(0.7)) == 1
    assert _loop_lens(tl, 0.7) == [8]
    # both notch corners sit 1.5 above the bottom edge and close at rate 2
    assert tl.first_event_t == pytest.approx(0.75, abs=1e-6)
    # region is cut in two: 4 verts each side of the notch wall
    assert len(tl.front_at(0.75)) == 2
    assert _loop_lens(tl, 0.75) == [4, 4]
    assert _loop_lens(tl, 1.2) == [4, 4]
    # each 2.5-wide half collapses onto its own medial segment at t=1.25
    assert tl.max_t == pytest.approx(1.25, abs=1e-6)
    assert tl.front_at(1.25 + 1e-6) == []


def test_timeline_not_truncated_for_normal_input():
    for loops in (SQUARE, RECT41, LSHAPE, SQUARE_WITH_HOLE, OFFCENTRE_HOLE,
                  NOTCH):
        assert build_timeline(loops).truncated is False


from utils.smart_inset_core import sanitize_loops


def test_sanitize_drops_zero_edges():
    loops, _ = sanitize_loops([[(0, 0), (0, 0), (2, 0), (2, 2), (0, 2)]])
    assert len(loops[0]) == 4


def test_sanitize_rejects_degenerate_loop():
    with pytest.raises(ValueError):
        sanitize_loops([[(0, 0), (1, 0), (1e-9, 1e-10)]], min_edge=1e-3)


def test_timeline_survives_duplicate_points():
    tl = build_timeline([[(0, 0), (2, 0), (2, 0), (2, 2), (0, 2)]])
    assert tl.max_t == pytest.approx(1.0)


def test_clamp_equals_first_event():
    tl = build_timeline(RECT41)
    assert tl.first_event_t == pytest.approx(0.5)
    # clamp contract: front at first_event_t*0.999 is intact (4 verts)
    loops = tl.front_at(tl.first_event_t * 0.999)
    assert len(loops) == 1 and len(loops[0]) == 4


def test_spike_triangle_no_nan():
    # extremely acute triangle
    tl = build_timeline([[(0.0, 0.0), (10.0, 0.0), (10.0, 0.05)]])
    assert math.isfinite(tl.max_t)
    for n in tl.nodes:
        assert all(math.isfinite(c) for c in n.pos)


def test_sanitize_carries_dropped_points_weight_when_kept_edge_degenerate():
    # p0==p1 (degenerate edge index 0, weight 9.0); the surviving edge
    # p0->p2 must take the DROPPED point's outgoing weight w[1] = 1.0,
    # not the stale weight recorded for the kept point.
    loops, ws = sanitize_loops(
        [[(0, 0), (0, 0), (2, 0), (2, 2), (0, 2)]],
        weights=[[9.0, 1.0, 1.0, 1.0, 1.0]],
    )
    assert len(loops[0]) == 4
    assert ws[0] == [1.0, 1.0, 1.0, 1.0]


def test_sanitize_carries_dropped_points_weight_when_dropped_edge_differs():
    # p1==p0 (degenerate edge index 1, weight 5.0, belongs to the dropped
    # point p1). Surviving edge p0->p2 must take w[1] = 5.0.
    loops, ws = sanitize_loops(
        [[(0, 0), (0, 0), (2, 0), (2, 2), (0, 2)]],
        weights=[[1.0, 5.0, 1.0, 1.0, 1.0]],
    )
    assert len(loops[0]) == 4
    assert ws[0] == [5.0, 1.0, 1.0, 1.0]
