import pytest

from utils.vert_fuse_core import (
    project_point_on_segment,
    fuse_candidates,
    merge_at_project,
    merge_at_vert,
    merge_at_mid,
    MERGE_POSITIONS,
    TOL,
)
from utils.converge_core import EPS, midpoint


# ---------------------------------------------------------------------------
# project_point_on_segment
# ---------------------------------------------------------------------------

def test_project_basic_interior():
    t, proj = project_point_on_segment((0.5, 1.0, 0.0),
                                       (0.0, 0.0, 0.0), (1.0, 0.0, 0.0))
    assert t == pytest.approx(0.5)
    assert proj == pytest.approx((0.5, 0.0, 0.0))


def test_project_t_is_unclamped_beyond_endpoints():
    # p past b: t > 1 and proj lies beyond b on the infinite line -- the
    # param is NOT clamped; callers enforce the interior rule themselves.
    t, proj = project_point_on_segment((3.0, 2.0, 0.0),
                                       (0.0, 0.0, 0.0), (2.0, 0.0, 0.0))
    assert t == pytest.approx(1.5)
    assert proj == pytest.approx((3.0, 0.0, 0.0))
    # p before a: t < 0
    t, proj = project_point_on_segment((-1.0, 0.5, 0.0),
                                       (0.0, 0.0, 0.0), (2.0, 0.0, 0.0))
    assert t == pytest.approx(-0.5)
    assert proj == pytest.approx((-1.0, 0.0, 0.0))


def test_project_degenerate_segment_returns_none():
    assert project_point_on_segment((1.0, 1.0, 1.0),
                                    (0.0, 0.0, 0.0), (0.0, 0.0, 0.0)) is None


def test_project_point_on_line_gives_zero_offset():
    t, proj = project_point_on_segment((0.25, 0.0, 0.0),
                                       (0.0, 0.0, 0.0), (1.0, 0.0, 0.0))
    assert t == pytest.approx(0.25)
    assert proj == pytest.approx((0.25, 0.0, 0.0))


# ---------------------------------------------------------------------------
# fuse_candidates: basic hit / miss
# ---------------------------------------------------------------------------

def test_fuse_basic_t_junction_hit():
    # vert hovers 5e-4 above the middle of the target edge -- inside TOL
    verts = [(0.5, 5e-4, 0.0)]
    edges = [((0.0, 0.0, 0.0), (1.0, 0.0, 0.0))]
    cands = fuse_candidates(verts, edges)
    assert len(cands) == 1
    c = cands[0]
    assert c.vert_index == 0
    assert c.edge_index == 0
    assert c.t == pytest.approx(0.5)
    assert c.proj == pytest.approx((0.5, 0.0, 0.0))
    assert c.dist == pytest.approx(5e-4)


def test_fuse_miss_beyond_tolerance():
    verts = [(0.5, 5e-3, 0.0)]  # 5x the default TOL
    edges = [((0.0, 0.0, 0.0), (1.0, 0.0, 0.0))]
    assert fuse_candidates(verts, edges) == []
    # qualifies again with an explicit looser tolerance
    assert len(fuse_candidates(verts, edges, tol=1e-2)) == 1


# ---------------------------------------------------------------------------
# fuse_candidates: exclusion rules
# ---------------------------------------------------------------------------

def test_fuse_endpoint_coincident_vert_excluded():
    # vert sits exactly on an edge endpoint: merge-by-distance territory,
    # never a fuse candidate
    verts = [(0.0, 0.0, 0.0)]
    edges = [((0.0, 0.0, 0.0), (1.0, 0.0, 0.0))]
    assert fuse_candidates(verts, edges) == []


def test_fuse_vert_near_endpoint_but_within_eps_of_it_excluded():
    # vert within EPS of an endpoint counts as coincident
    verts = [(1e-10, 0.0, 0.0)]
    edges = [((0.0, 0.0, 0.0), (1.0, 0.0, 0.0))]
    assert fuse_candidates(verts, edges) == []


def test_fuse_projection_at_endpoint_excluded():
    # vert straight above endpoint a: proj == a exactly (t == 0), not interior
    verts = [(0.0, 5e-4, 0.0)]
    edges = [((0.0, 0.0, 0.0), (1.0, 0.0, 0.0))]
    assert fuse_candidates(verts, edges) == []


def test_fuse_projection_near_endpoint_within_eps_excluded():
    # proj lands 1e-10 inside the segment -- closer than EPS to endpoint a,
    # so the interior rule rejects it
    verts = [(1e-10, 5e-4, 0.0)]
    edges = [((0.0, 0.0, 0.0), (1.0, 0.0, 0.0))]
    assert fuse_candidates(verts, edges) == []


def test_fuse_projection_beyond_endpoint_excluded():
    # proj falls outside the segment (t > 1): never a candidate even
    # though the perpendicular distance alone would qualify
    verts = [(1.5, 5e-4, 0.0)]
    edges = [((0.0, 0.0, 0.0), (1.0, 0.0, 0.0))]
    assert fuse_candidates(verts, edges) == []


def test_fuse_zero_length_edge_skipped():
    verts = [(0.5, 5e-4, 0.0)]
    edges = [
        ((0.5, 0.0, 0.0), (0.5, 0.0, 0.0)),   # zero-length, index 0
        ((0.0, 0.0, 0.0), (1.0, 0.0, 0.0)),   # index 1, the real target
    ]
    cands = fuse_candidates(verts, edges)
    assert len(cands) == 1
    assert cands[0].edge_index == 1


def test_fuse_exclude_map_respected():
    verts = [(0.5, 5e-4, 0.0)]
    edges = [((0.0, 0.0, 0.0), (1.0, 0.0, 0.0))]
    # the edge is topologically linked to the vert -> never a target
    assert fuse_candidates(verts, edges, exclude={0: {0}}) == []
    # exclusion is per-vert: an empty set for this vert changes nothing
    assert len(fuse_candidates(verts, edges, exclude={0: set()})) == 1
    # exclusion for a different vert index changes nothing either
    assert len(fuse_candidates(verts, edges, exclude={1: {0}})) == 1


# ---------------------------------------------------------------------------
# fuse_candidates: nearest edge wins, determinism
# ---------------------------------------------------------------------------

def test_fuse_nearest_edge_wins():
    verts = [(0.5, 0.0, 0.0)]
    edges = [
        ((0.0, 8e-4, 0.0), (1.0, 8e-4, 0.0)),   # index 0, dist 8e-4
        ((0.0, 2e-4, 0.0), (1.0, 2e-4, 0.0)),   # index 1, dist 2e-4 -- nearer
    ]
    cands = fuse_candidates(verts, edges)
    assert len(cands) == 1
    assert cands[0].edge_index == 1
    assert cands[0].dist == pytest.approx(2e-4)


def test_fuse_tie_break_lowest_edge_index():
    verts = [(0.5, 0.0, 0.0)]
    edges = [
        ((0.0, 5e-4, 0.0), (1.0, 5e-4, 0.0)),    # index 0, dist 5e-4
        ((0.0, -5e-4, 0.0), (1.0, -5e-4, 0.0)),  # index 1, same dist
    ]
    cands = fuse_candidates(verts, edges)
    assert len(cands) == 1
    assert cands[0].edge_index == 0


def test_fuse_one_candidate_per_vert_ordered_by_vert_index():
    edges = [((0.0, 0.0, 0.0), (1.0, 0.0, 0.0))]
    # verts listed in scrambled geometric order; output is by vert_index
    verts = [
        (0.8, 5e-4, 0.0),   # vert 0
        (0.2, 5e-4, 0.0),   # vert 1
        (0.5, 5e-3, 0.0),   # vert 2 -- misses (beyond TOL)
        (0.4, 5e-4, 0.0),   # vert 3
    ]
    cands = fuse_candidates(verts, edges)
    assert [c.vert_index for c in cands] == [0, 1, 3]
    assert all(c.edge_index == 0 for c in cands)


def test_fuse_fully_3d_off_plane_candidate():
    # target edge runs diagonally through space; vert offset off-axis in
    # all three components. Nothing here lives in a coordinate plane.
    edges = [((1.0, 2.0, 3.0), (3.0, 4.0, 7.0))]
    mid = (2.0, 3.0, 5.0)
    # edge direction (2,2,4); (2,-4,1) is orthogonal to it (4-8+4 = 0),
    # |(2,-4,1)| = sqrt(21) -- offset the mid-point by 6e-4 along it
    k = 6e-4 / 21 ** 0.5
    verts = [(mid[0] + 2 * k, mid[1] - 4 * k, mid[2] + k)]
    cands = fuse_candidates(verts, edges)
    assert len(cands) == 1
    c = cands[0]
    assert c.t == pytest.approx(0.5)
    assert c.proj == pytest.approx(mid)
    assert c.dist == pytest.approx(6e-4)


def test_fuse_dist_exactly_tol_qualifies():
    # the spec is dist <= tol: a gap of exactly tol is a hit. Clean
    # binary-exact numbers so the comparison really is equality.
    verts = [(0.5, 0.5, 0.0)]
    edges = [((0.0, 0.0, 0.0), (1.0, 0.0, 0.0))]
    cands = fuse_candidates(verts, edges, tol=0.5)
    assert len(cands) == 1
    assert cands[0].dist == pytest.approx(0.5)


def test_fuse_excluded_nearest_falls_back_to_next_edge():
    # nearest edge is excluded for this vert -> the candidate falls back
    # to the next-nearest qualifying edge instead of vanishing
    verts = [(0.5, 0.0, 0.0)]
    edges = [
        ((0.0, 2e-4, 0.0), (1.0, 2e-4, 0.0)),   # index 0, nearest -- excluded
        ((0.0, 8e-4, 0.0), (1.0, 8e-4, 0.0)),   # index 1, farther
    ]
    cands = fuse_candidates(verts, edges, exclude={0: {0}})
    assert len(cands) == 1
    assert cands[0].edge_index == 1
    assert cands[0].dist == pytest.approx(8e-4)


# ---------------------------------------------------------------------------
# fuse_candidates: island filtering
# ---------------------------------------------------------------------------

def test_fuse_island_same_kept_cross_skipped():
    # two verts, one edge each within TOL -- but vert 1's only edge lives
    # in a different island, so only vert 0 gets a candidate
    verts = [
        (0.5, 5e-4, 0.0),    # vert 0, island 0
        (0.5, 1.0005, 0.0),  # vert 1, island 1
    ]
    edges = [
        ((0.0, 0.0, 0.0), (1.0, 0.0, 0.0)),  # index 0, island 0
        ((0.0, 1.0, 0.0), (1.0, 1.0, 0.0)),  # index 1, island 0 -- cross for vert 1
    ]
    cands = fuse_candidates(verts, edges,
                            vert_islands=[0, 1], edge_islands=[0, 0])
    assert len(cands) == 1
    assert cands[0].vert_index == 0
    assert cands[0].edge_index == 0


def test_fuse_cross_island_nearer_edge_does_not_shadow():
    # the nearer edge is cross-island: filtering happens BEFORE
    # nearest-edge selection, so the candidate falls back to the farther
    # same-island edge instead of vanishing
    verts = [(0.5, 0.0, 0.0)]
    edges = [
        ((0.0, 2e-4, 0.0), (1.0, 2e-4, 0.0)),   # index 0, nearer -- island 1
        ((0.0, 8e-4, 0.0), (1.0, 8e-4, 0.0)),   # index 1, farther -- island 0
    ]
    cands = fuse_candidates(verts, edges,
                            vert_islands=[0], edge_islands=[1, 0])
    assert len(cands) == 1
    assert cands[0].edge_index == 1
    assert cands[0].dist == pytest.approx(8e-4)


def test_fuse_islands_partial_means_no_filtering():
    # filtering needs BOTH sequences: either one alone is ignored and the
    # cross-island nearer edge wins as if no islands were given
    verts = [(0.5, 0.0, 0.0)]
    edges = [
        ((0.0, 2e-4, 0.0), (1.0, 2e-4, 0.0)),   # index 0, nearer
        ((0.0, 8e-4, 0.0), (1.0, 8e-4, 0.0)),   # index 1, farther
    ]
    only_verts = fuse_candidates(verts, edges, vert_islands=[0])
    only_edges = fuse_candidates(verts, edges, edge_islands=[1, 0])
    for cands in (only_verts, only_edges):
        assert len(cands) == 1
        assert cands[0].edge_index == 0
        assert cands[0].dist == pytest.approx(2e-4)


def test_fuse_islands_and_exclude_compose():
    # both filters apply: index 0 is cross-island, index 1 is excluded,
    # so the candidate lands on index 2 -- the farthest qualifying edge
    verts = [(0.5, 0.0, 0.0)]
    edges = [
        ((0.0, 2e-4, 0.0), (1.0, 2e-4, 0.0)),   # index 0 -- island 1
        ((0.0, 5e-4, 0.0), (1.0, 5e-4, 0.0)),   # index 1 -- excluded
        ((0.0, 8e-4, 0.0), (1.0, 8e-4, 0.0)),   # index 2 -- the target
    ]
    cands = fuse_candidates(verts, edges, exclude={0: {1}},
                            vert_islands=[0], edge_islands=[1, 0, 0])
    assert len(cands) == 1
    assert cands[0].edge_index == 2
    assert cands[0].dist == pytest.approx(8e-4)


# ---------------------------------------------------------------------------
# MERGE_POSITIONS
# ---------------------------------------------------------------------------

def test_merge_positions_registry_ordered():
    keys = [key for key, _fn in MERGE_POSITIONS]
    assert keys == ["PROJECT", "VERT", "MID"]
    fn_by_key = dict(MERGE_POSITIONS)
    assert fn_by_key["PROJECT"] is merge_at_project
    assert fn_by_key["VERT"] is merge_at_vert
    assert fn_by_key["MID"] is merge_at_mid


def test_merge_positions_functions():
    vert_co = (0.5, 1.0, 0.0)
    proj = (0.5, 0.0, 0.0)
    assert merge_at_project(vert_co, proj) == pytest.approx(proj)
    assert merge_at_vert(vert_co, proj) == pytest.approx(vert_co)
    assert merge_at_mid(vert_co, proj) == pytest.approx(midpoint(vert_co, proj))


# ---------------------------------------------------------------------------
# module constants sanity
# ---------------------------------------------------------------------------

def test_module_constants():
    # fuse gaps are visible-scale: TOL is looser than converge's 1e-4
    assert TOL == pytest.approx(1e-3)
    assert EPS == pytest.approx(1e-9)
