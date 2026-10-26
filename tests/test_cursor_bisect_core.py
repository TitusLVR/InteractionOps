from utils.cursor_bisect_core import (
    DELIMIT_TYPES, DELIMIT_LABELS, next_delimit_type, walk_island,
    normals_split, next_axis, axis_vector,
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
