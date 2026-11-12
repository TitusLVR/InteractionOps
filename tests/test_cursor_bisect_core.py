import math

from utils.cursor_bisect_core import (
    DELIMIT_TYPES, DELIMIT_LABELS, next_delimit_type, walk_island,
    normals_split, next_axis, axis_vector,
    SNAP_SOURCES, SNAP_SOURCE_LABELS, next_snap_source, oriented_extents,
    box_edges, box_wire, bounds_division_count, bounds_division_offsets,
    bounds_inset_offsets, bounds_layout, bounds_split,
)

# Faces 0-1-2-3 in a strip, edges e01, e12, e23 between neighbours;
# face 4 is disconnected.
STRIP = {0: [("e01", 1)], 1: [("e01", 0), ("e12", 2)],
         2: [("e12", 1), ("e23", 3)], 3: [("e23", 2)], 4: []}

# Three faces around one non-manifold edge "e".
FAN = {0: [("e", 1), ("e", 2)], 1: [("e", 0), ("e", 2)], 2: [("e", 0), ("e", 1)]}


def _nb(graph):
    return lambda f: graph.get(f, [])


def _never(e, a, b):
    return False


def test_walk_whole_strip_without_boundaries():
    assert walk_island(0, lambda f: True, _nb(STRIP), _never) == {0, 1, 2, 3}


def test_walk_stops_at_boundary_edge():
    assert walk_island(0, lambda f: True, _nb(STRIP), lambda e, a, b: e == "e12") == {0, 1}


def test_walk_stays_inside_candidates():
    assert walk_island(1, lambda f: f in {1, 2}, _nb(STRIP), _never) == {1, 2}


def test_walk_start_outside_candidates_is_empty():
    assert walk_island(0, lambda f: f != 0, _nb(STRIP), _never) == set()


def test_walk_non_manifold_edge_reaches_all_faces():
    assert walk_island(0, lambda f: True, _nb(FAN), _never) == {0, 1, 2}


def test_walk_pairwise_boundary_on_non_manifold_edge():
    blocked = lambda e, a, b: {a, b} == {0, 2}
    assert walk_island(0, lambda f: True, _nb(FAN), blocked) == {0, 1, 2}  # 2 reached via 1


def test_delimit_cycle_order_and_labels():
    assert DELIMIT_TYPES == ('ISLAND', 'SEAM', 'SHARP', 'UV', 'MATERIAL', 'NORMAL')
    assert next_delimit_type('NORMAL') == 'ISLAND'
    assert next_delimit_type('ISLAND') == 'SEAM'
    assert DELIMIT_LABELS['UV'] == 'UV Island'
    assert DELIMIT_LABELS['ISLAND'] == 'Mesh Island'


def test_normals_split():
    assert normals_split((0, 0, 1), (1, 0, 0), 30.0) is True
    assert normals_split((0, 0, 1), (0, 0, 1), 30.0) is False
    assert normals_split((0, 0, 1), (0, 0, 1.0000001), 0.0) is False  # dot clamp, no NaN


def test_axis_cycle_and_vectors():
    assert next_axis('X') == 'Y' and next_axis('Y') == 'Z' and next_axis('Z') == 'X'
    assert axis_vector('Z') == (0.0, 0.0, 1.0)


def test_cut_set_for_axis_drops_hovered_face_only_in_z():
    from utils.cursor_bisect_core import cut_set_for_axis
    assert cut_set_for_axis({0, 1, 2}, 'Z', 1) == {0, 2}
    assert cut_set_for_axis({0, 1, 2}, 'X', 1) == {0, 1, 2}
    assert cut_set_for_axis({0, 1, 2}, 'Z', 7) == {0, 1, 2}


def test_cached_island_reused_from_any_face_of_the_island():
    from utils.cursor_bisect_core import cached_island
    cache = (("Cube", "ISLAND", 30.0, 3), frozenset({4, 5, 6}))
    assert cached_island(cache, ("Cube", "ISLAND", 30.0, 3), 6) == {4, 5, 6}
    assert cached_island(cache, ("Cube", "ISLAND", 30.0, 3), 9) is None   # other island
    assert cached_island(cache, ("Cube", "ISLAND", 30.0, 4), 5) is None   # mesh changed
    assert cached_island(None, ("Cube", "ISLAND", 30.0, 3), 5) is None


# --- Selection Bounds snap source -------------------------------------------------

WORLD = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
_S = math.sqrt(0.5)
ROT45 = ((_S, _S, 0.0), (-_S, _S, 0.0), (0.0, 0.0, 1.0))  # frame rotated 45 deg about Z


def _close(a, b, eps=1e-9):
    return all(abs(x - y) <= eps for x, y in zip(a, b))


def _has(points, p, eps=1e-9):
    return any(_close(q, p, eps) for q in points)


def test_snap_source_cycle_and_labels():
    assert SNAP_SOURCES == ('EDGE', 'BOUNDS')
    assert next_snap_source('EDGE') == 'BOUNDS'
    assert next_snap_source('BOUNDS') == 'EDGE'
    assert next_snap_source('bogus') == 'EDGE'
    assert SNAP_SOURCE_LABELS == {'EDGE': 'Face Edge', 'BOUNDS': 'Selection Bounds'}


def test_oriented_extents_world_and_rotated():
    pts = [(0, 0, 0), (2, 1, 0), (1, 3, 1)]
    assert oriented_extents(pts, WORLD) == ((0, 0, 0), (2, 3, 1))
    assert oriented_extents([], WORLD) is None
    lo, hi = oriented_extents([(1, 1, 0), (-1, -1, 0)], ROT45)
    assert _close(lo, (-2 * _S, 0, 0)) and _close(hi, (2 * _S, 0, 0))


def test_oriented_extents_accepts_generator():
    lo, hi = oriented_extents(((x, 0.0, 0.0) for x in range(4)), WORLD)
    assert lo == (0, 0, 0) and hi == (3, 0, 0)


def test_box_edges_full_box_has_twelve_edges():
    edges = box_edges((0, 0, 0), (1, 2, 3), WORLD)
    assert [len(edges[a]) for a in range(3)] == [4, 4, 4]
    assert len(box_wire((0, 0, 0), (1, 2, 3), WORLD)) == 12
    for start, end in edges[1]:
        assert end[1] - start[1] == 2 and start[0] == end[0] and start[2] == end[2]


def test_box_edges_flat_box_no_duplicates_or_zero_length():
    edges = box_edges((0, 0, 0), (4, 2, 0), WORLD)
    assert edges[2] == []
    assert len(edges[0]) == 2 and len(edges[1]) == 2
    wire = box_wire((0, 0, 0), (4, 2, 0), WORLD)
    assert len(wire) == 4
    assert all(math.dist(s, e) > 0 for s, e in wire)
    keys = {tuple(sorted((s, e))) for s, e in wire}
    assert len(keys) == 4


def test_box_edges_line_box():
    wire = box_wire((0, 0, 0), (5, 0, 0), WORLD)
    assert wire == [((0, 0, 0), (5, 0, 0))]


def test_division_count_mirrors_fill_rule():
    assert bounds_division_count(0, False) == 1
    assert bounds_division_count(3, False) == 3
    assert bounds_division_count(0, True) == 0
    assert bounds_division_count(2, True) == 2


def test_division_offsets():
    assert bounds_division_offsets(4.0, 3) == [1.0, 2.0, 3.0]
    assert bounds_division_offsets(4.0, 1) == [2.0]
    assert bounds_division_offsets(0.0, 3) == []
    assert bounds_division_offsets(4.0, 0) == []


def test_inset_offsets_skip_rules():
    assert bounds_inset_offsets(4.0, 1.0) == [1.0, 3.0]
    assert bounds_inset_offsets(4.0, 2.0) == [2.0]          # both ends coincide
    assert bounds_inset_offsets(4.0, 0.0) == []
    assert bounds_inset_offsets(4.0, -1.0) == []
    assert bounds_inset_offsets(4.0, 4.0) == []
    assert bounds_inset_offsets(4.0, 5.0) == []
    assert bounds_inset_offsets(0.0, 1.0) == []


def test_layout_divisions_on_every_cut_axis_edge():
    lay = bounds_layout((0, 0, 0), (4, 2, 1), WORLD, 0, 3, 0.0, False)
    assert lay['length'] == 4
    assert len(lay['divisions']) == 4 * 3 and lay['insets'] == []
    assert _has(lay['divisions'], (1, 0, 0)) and _has(lay['divisions'], (3, 2, 1))
    assert [p[0] for p in lay['positions']] == [1.0, 2.0, 3.0]
    assert len(lay['wire']) == 12


def test_layout_flat_box():
    lay = bounds_layout((0, 0, 0), (4, 2, 0), WORLD, 0, 0, 0.0, False)
    assert len(lay['divisions']) == 2                        # midpoint on both X edges
    assert _has(lay['divisions'], (2, 0, 0)) and _has(lay['divisions'], (2, 2, 0))
    assert len(lay['wire']) == 4


def test_layout_inset_replaces_fallback_midpoint():
    lay = bounds_layout((0, 0, 0), (4, 2, 0), WORLD, 0, 0, 0.5, True)
    assert lay['divisions'] == []
    assert len(lay['insets']) == 4
    assert sorted(p[0] for p in lay['positions']) == [0.5, 3.5]
    lay = bounds_layout((0, 0, 0), (4, 2, 0), WORLD, 0, 1, 0.5, True)
    assert sorted(p[0] for p in lay['positions']) == [0.5, 2.0, 3.5]
    # inset too large: skipped, the midpoint fallback comes back
    lay = bounds_layout((0, 0, 0), (4, 2, 0), WORLD, 0, 0, 9.0, True)
    assert lay['insets'] == [] and [p[0] for p in lay['positions']] == [2.0]


def test_layout_zero_cut_axis_extent_has_no_points():
    lay = bounds_layout((0, 0, 0), (4, 2, 0), WORLD, 2, 3, 0.5, True)
    assert lay['divisions'] == [] and lay['insets'] == [] and lay['positions'] == []
    assert len(lay['wire']) == 4


def test_layout_rotated_frame():
    lo, hi = oriented_extents([(1, 1, 0), (-1, -1, 0), (0, 0, 0)], ROT45)
    lay = bounds_layout(lo, hi, ROT45, 0, 1, 0.0, False)
    assert len(lay['divisions']) == 1                         # a line box: one edge
    assert _close(lay['divisions'][0], (0, 0, 0))
    assert abs(lay['length'] - 2 * math.sqrt(2)) < 1e-9


def test_bounds_split():
    length, split = bounds_split((0, 0, 0), (4, 2, 0), WORLD, 0, (1.0, 5.0, 0.0))
    assert length == 4 and split == 1
    _, split = bounds_split((0, 0, 0), (4, 2, 0), WORLD, 0, (3.5, 0.0, 0.0))
    assert split == 0.5
    _, split = bounds_split((0, 0, 0), (4, 2, 0), WORLD, 0, (-3.0, 0.0, 0.0))
    assert split == 0.0
