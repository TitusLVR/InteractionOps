"""UV Pipe core: the seam-loop walker, ring seams, part classification and the lengthwise seam of a wall."""
import math
from collections import Counter
from math import radians

from uv_pipe_fixtures import bent_pipe, box_tube, capped_cylinder, clean_bend, open_tube, torus
from utils.uv_pipe_core import (
    Loop, Part, analyse, bend_seams, dihedrals, existing_wall_seam, loop_kind, neighbours, ring_seams, split_parts, trace_loop,
    disk_uvs, wall_candidates, wall_seam, wall_uvs,
)
from utils.uv_stripe_select_core import _edge


def _radius(p):
    return math.hypot(p[0], p[1])


def _rim_edges(verts, faces, z):
    """The edges of a capped_cylinder rim: both ends on the wall radius 1 at height z."""
    out = set()
    for face in faces.values():
        for a, b in zip(face, face[1:] + face[:1]):
            pa, pb = verts[a], verts[b]
            if all(abs(_radius(p) - 1.0) < 1e-9 and abs(p[2] - z) < 1e-9 for p in (pa, pb)):
                out.add(_edge(a, b))
    return out


def _lengthwise_edges(verts, faces):
    """Wall edges of a straight Z tube: both ends on radius 1, same angle, different height."""
    out = set()
    for face in faces.values():
        for a, b in zip(face, face[1:] + face[:1]):
            pa, pb = verts[a], verts[b]
            if (abs(_radius(pa) - 1.0) < 1e-9 and abs(_radius(pb) - 1.0) < 1e-9
                    and math.dist(pa[:2], pb[:2]) < 1e-9):
                out.add(_edge(a, b))
    return out


def _pole(faces):
    degree = Counter()
    for e in {_edge(a, b) for f in faces.values() for a, b in zip(f, f[1:] + f[:1])}:
        degree[e[0]] += 1
        degree[e[1]] += 1
    return [v for v, n in degree.items() if n > 4]


# --- Task 4: fixtures, dihedrals, loop walker ---------------------------------------------------------------------


def test_reference_a_fixture_shape():
    verts, faces = capped_cylinder()
    sizes = Counter(len(f) for f in faces.values())
    assert sizes == {4: 4 * 32 + 3 * 32, 3: 32, 32: 1}


def test_bent_pipe_fixture_has_triangles_and_a_pole():
    verts, faces = bent_pipe()
    sizes = Counter(len(f) for f in faces.values())
    assert sizes[3] == 4 and sizes[12] == 2
    poles = _pole(faces)
    assert len(poles) == 1


def test_dihedral_of_cylinder_rim_is_right_angle():
    verts, faces = capped_cylinder()
    angles = dihedrals(verts, faces)
    rims = _rim_edges(verts, faces, 0.0) | _rim_edges(verts, faces, 2.0)
    assert len(rims) == 64
    for e in rims:
        assert abs(angles[e] - math.pi / 2) < 1e-6
    lengthwise = _lengthwise_edges(verts, faces)
    assert len(lengthwise) == 4 * 32
    for e in lengthwise:
        assert abs(angles[e] - 2 * math.pi / 32) < 1e-6


def test_boundary_edges_have_no_dihedral():
    verts, faces = open_tube()
    angles = dihedrals(verts, faces)
    rim = {_edge(i, (i + 1) % 12) for i in range(12)}
    assert not rim & set(angles)


def test_rim_loop_closes():
    verts, faces = capped_cylinder()
    edge = sorted(_rim_edges(verts, faces, 0.0))[0]
    loop = trace_loop(verts, neighbours(faces), edge, radians(120))
    assert loop.closed and len(loop.verts) == 32
    assert set(loop.edges()) == _rim_edges(verts, faces, 0.0)


def test_lengthwise_loop_stops_at_the_rims():
    verts, faces = capped_cylinder()
    edge = _edge(32, 64)                   # wall rings 1 and 2, vertex 0
    loop = trace_loop(verts, neighbours(faces), edge, radians(120))
    assert not loop.closed and len(loop.verts) == 5
    assert {verts[loop.verts[0]][2], verts[loop.verts[-1]][2]} == {0.0, 2.0}
    assert all(abs(_radius(verts[v]) - 1.0) < 1e-9 for v in loop.verts)


def test_loop_stops_on_stop_verts():
    verts, faces = open_tube()
    nbrs = neighbours(faces)
    ends = frozenset(range(12)) | frozenset(range(48, 60))
    free = trace_loop(verts, nbrs, _edge(12, 24), radians(80))
    assert len(free.verts) > 5                        # at 80 degrees the loop would turn along the rim
    loop = trace_loop(verts, nbrs, _edge(12, 24), radians(80), stop_verts=ends)
    assert not loop.closed and len(loop.verts) == 5
    assert loop.verts[0] in ends and loop.verts[-1] in ends


def test_loop_over_a_right_angle_corner():
    verts = {0: (0.0, 0.0, 0.0), 1: (1.0, 0.0, 0.0), 2: (1.0, 1.0, 0.0)}
    nbrs = {0: [1], 1: [0, 2], 2: [1]}
    assert trace_loop(verts, nbrs, (0, 1), radians(120)).verts == [0, 1]
    assert trace_loop(verts, nbrs, (0, 1), radians(80)).verts == [0, 1, 2]


def test_loop_passes_a_pole():
    verts, faces = bent_pipe()
    nbrs = neighbours(faces)
    (pole,) = _pole(faces)
    assert len(nbrs[pole]) == 8
    below = min(nbrs[pole], key=lambda v: verts[v][2])   # the inner line's vertex where the bend starts
    loop = trace_loop(verts, nbrs, _edge(below, pole), radians(120))
    assert not loop.closed and pole in loop.verts
    rims = tuple(frozenset(f) for f in faces.values() if len(f) == 12)
    first, last = loop.verts[0], loop.verts[-1]
    assert (first in rims[0] and last in rims[1]) or (first in rims[1] and last in rims[0])
    assert len(loop.verts) == 7


def _zigzag():
    verts = {i: (float(i), float(i % 2), 0.0) for i in range(6)}      # turns 90 degrees at every vertex
    nbrs = {i: [j for j in (i - 1, i + 1) if 0 <= j < 6] for i in range(6)}
    uv = {i: (float(i), 0.0) for i in range(6)}
    return verts, nbrs, uv


def test_uv_source_uses_uv_angles():
    verts, nbrs, uv = _zigzag()
    assert trace_loop(verts, nbrs, (0, 1), radians(120)).verts == [0, 1]
    assert trace_loop(verts, nbrs, (0, 1), radians(120), uv=uv).verts == [0, 1, 2, 3, 4, 5]


def test_uv_source_falls_back_where_a_vertex_has_no_single_uv():
    verts, nbrs, uv = _zigzag()
    del uv[4]
    # the step at 3 (from 2 toward 4) has an end without a single uv: judged on geometry, where it turns 90 degrees
    assert trace_loop(verts, nbrs, (0, 1), radians(120), uv=uv).verts == [0, 1, 2, 3]


def test_loop_edges_include_the_closing_edge():
    assert Loop([3, 1, 2], True).edges() == [(1, 3), (1, 2), (2, 3)]
    assert Loop([3, 1, 2], False).edges() == [(1, 3), (1, 2)]


# --- Task 5: ring seams and part classification -------------------------------------------------------------------


def _cylinder_parts(**kwargs):
    verts, faces = capped_cylinder(**kwargs)
    cuts = {e for loop in ring_seams(verts, faces, radians(60), radians(120)) for e in loop.edges()}
    return verts, faces, cuts


def _cap_loop(verts, faces, radius, z):
    """Edges of a cap's concentric loop at ``radius`` and height ``z``."""
    out = set()
    for face in faces.values():
        for a, b in zip(face, face[1:] + face[:1]):
            if all(abs(_radius(verts[v]) - radius) < 1e-9 and abs(verts[v][2] - z) < 1e-9 for v in (a, b)):
                out.add(_edge(a, b))
    return out


def test_cylinder_ring_seams_are_the_two_rims():
    verts, faces = capped_cylinder()
    loops = ring_seams(verts, faces, radians(60), radians(120))
    assert len(loops) == 2 and all(lp.closed and len(lp.verts) == 32 for lp in loops)
    assert {e for lp in loops for e in lp.edges()} == _rim_edges(verts, faces, 0.0) | _rim_edges(verts, faces, 2.0)


def test_low_poly_wall_edges_are_not_ring_seams():
    verts, faces = capped_cylinder(sides=8)
    assert abs(dihedrals(verts, faces)[_edge(0, 8)] - radians(45)) < 1e-9
    rims = _rim_edges(verts, faces, 0.0) | _rim_edges(verts, faces, 2.0)
    for sharp in (radians(60), radians(30)):        # at 30 the lengthwise edges are sharp too, but never close
        loops = ring_seams(verts, faces, sharp, radians(120))
        assert len(loops) == 2
        assert {e for lp in loops for e in lp.edges()} == rims


def test_bend_rings_are_not_ring_seams():
    assert ring_seams(*clean_bend(), radians(60), radians(120)) == []


def test_ring_seams_are_returned_once_and_in_a_stable_order():
    verts, faces = capped_cylinder()
    first = ring_seams(verts, faces, radians(60), radians(120))
    second = ring_seams(verts, faces, radians(60), radians(120))
    assert [lp.verts for lp in first] == [lp.verts for lp in second]
    assert len({frozenset(lp.edges()) for lp in first}) == len(first)


def test_cylinder_splits_into_six_parts():            # spec Reference A
    verts, faces, cuts = _cylinder_parts()
    parts, peel = split_parts(verts, faces, cuts)
    assert sorted(p.kind for p in parts) == ["DISK", "DISK", "RING", "RING", "RING", "WALL"]
    assert len(peel) == 3 * 32                       # the three inner cap loops
    assert peel == (_cap_loop(verts, faces, 0.671, 0.0) | _cap_loop(verts, faces, 0.493, 0.0)
                    | _cap_loop(verts, faces, 0.671, 2.0))
    assert sorted(len(p.faces) for p in parts) == [1, 32, 32, 32, 32, 128]
    assert sorted(fid for p in parts for fid in p.faces) == sorted(faces)
    wall = next(p for p in parts if p.kind == "WALL")
    assert len(wall.boundaries) == 2 and all(len(b) == 32 for b in wall.boundaries)
    for p in parts:
        if p.kind == "RING":
            assert len(p.boundaries) == 2
            lengths = [sum(math.dist(verts[a], verts[b]) for a, b in zip(lp, lp[1:] + lp[:1]))
                       for lp in p.boundaries]
            assert lengths[0] > lengths[1]                # longest first
        if p.kind == "DISK":
            assert len(p.boundaries) == 1


def test_suppressed_peel_merges_two_rings_into_a_wall():
    verts, faces, cuts = _cylinder_parts()
    between = _cap_loop(verts, faces, 0.671, 0.0)
    parts, peel = split_parts(verts, faces, cuts, suppressed=frozenset(between))
    assert sorted(p.kind for p in parts) == ["DISK", "DISK", "RING", "WALL", "WALL"]
    assert not peel & between
    assert peel == _cap_loop(verts, faces, 0.493, 0.0) | _cap_loop(verts, faces, 0.671, 2.0)
    flat_wall = next(p for p in parts if p.kind == "WALL" and len(p.faces) == 64)
    assert len(flat_wall.boundaries) == 2


def test_suppressed_peel_into_the_centre_is_a_disk():
    # removing the loop round the fan merges the inner ring and the fan: one boundary loop, so a disk
    verts, faces, cuts = _cylinder_parts()
    parts, peel = split_parts(verts, faces, cuts, suppressed=frozenset(_cap_loop(verts, faces, 0.493, 0.0)))
    assert sorted(p.kind for p in parts) == ["DISK", "DISK", "RING", "RING", "WALL"]
    assert sorted(len(p.faces) for p in parts if p.kind == "DISK") == [1, 64]


def test_bent_pipe_is_one_wall_and_two_disks():       # spec Reference B
    verts, faces = bent_pipe()
    cuts = {e for loop in ring_seams(verts, faces, radians(60), radians(120)) for e in loop.edges()}
    parts, peel = split_parts(verts, faces, cuts)
    assert sorted(p.kind for p in parts) == ["DISK", "DISK", "WALL"]
    assert peel == set()
    wall = next(p for p in parts if p.kind == "WALL")
    assert len(wall.faces) == len(faces) - 2 and len(wall.boundaries) == 2


def test_uncut_closed_and_open_surfaces():
    parts, _ = split_parts(*torus(), set())
    assert [p.kind for p in parts] == ["FREE"] and parts[0].boundaries == []
    parts, _ = split_parts(*open_tube(), set())
    assert [p.kind for p in parts] == ["WALL"] and len(parts[0].boundaries) == 2


# --- Task 6: lengthwise seam of a wall ------------------------------------------------------------------------------


def _only_wall(verts, faces, cuts=frozenset()):
    parts, _ = split_parts(verts, faces, cuts)
    walls = [p for p in parts if p.kind == "WALL"]
    assert len(walls) == 1
    return walls[0]


def _path_length(verts, loop):
    ids = loop.verts + loop.verts[:1] if loop.closed else loop.verts
    return sum(math.dist(verts[a], verts[b]) for a, b in zip(ids, ids[1:]))


def _is_path(faces, loop):
    edges = {_edge(a, b) for f in faces.values() for a, b in zip(f, f[1:] + f[:1])}
    return all(e in edges for e in loop.edges())


def test_straight_tube_has_one_candidate_per_side():
    verts, faces = open_tube(12)
    part = _only_wall(verts, faces)
    candidates = wall_candidates(verts, part, radians(120))
    assert len(candidates) == 12
    assert all(len(c.verts) == 5 and loop_kind(c, part) == "LENGTH" for c in candidates)
    assert [c.verts[0] for c in candidates] == part.boundaries[0]          # ordered round the longest loop
    assert len({frozenset(c.edges()) for c in candidates}) == 12


def test_wall_seam_takes_the_inside_of_the_bend():    # spec: shortest loop
    verts, faces = clean_bend()
    part = _only_wall(verts, faces)
    candidates = wall_candidates(verts, part, radians(120))
    assert len(candidates) == 12
    seam, fallback = wall_seam(verts, part, radians(120))
    assert fallback is False and loop_kind(seam, part) == "LENGTH"
    lengths = [_path_length(verts, c) for c in candidates]
    assert abs(_path_length(verts, seam) - min(lengths)) < 1e-12
    assert _path_length(verts, seam) < max(lengths) - 1.0
    assert all(v % 12 == 0 for v in seam.verts)      # every ring's vertex 0: the inside of the bend


def test_wall_seam_is_deterministic_on_ties():
    verts, faces = open_tube(12)
    part = _only_wall(verts, faces)
    seam, fallback = wall_seam(verts, part, radians(120))
    assert fallback is False
    starts = [verts[c.verts[0]] for c in wall_candidates(verts, part, radians(120))]
    assert verts[seam.verts[0]] == min(starts)
    assert wall_seam(verts, part, radians(120))[0].verts == seam.verts


def test_wall_seam_goes_through_the_pole():           # spec Reference B
    verts, faces = bent_pipe()
    cuts = {e for loop in ring_seams(verts, faces, radians(60), radians(120)) for e in loop.edges()}
    part = _only_wall(verts, faces, cuts)
    seam, fallback = wall_seam(verts, part, radians(120))
    assert fallback is False and loop_kind(seam, part) == "LENGTH"
    (pole,) = _pole(faces)
    assert pole in seam.verts
    rims = [set(f) for f in faces.values() if len(f) == 12]
    ends = {seam.verts[0], seam.verts[-1]}
    assert all(len(ends & rim) == 1 for rim in rims)


def test_wall_seam_falls_back_to_shortest_path():
    verts, faces = open_tube()
    assert len(wall_candidates(verts, _only_wall(verts, faces), radians(179))) == 12   # straight columns pass
    verts, faces = open_tube(twist=radians(5))       # every odd ring turned 5 degrees: the columns zigzag
    part = _only_wall(verts, faces)
    assert wall_candidates(verts, part, radians(179)) == []
    seam, fallback = wall_seam(verts, part, radians(179))
    assert fallback is True and seam is not None and not seam.closed
    assert loop_kind(seam, part) == "LENGTH" and _is_path(faces, seam)
    assert len(seam.verts) == 5                       # one edge per row is the shortest way across


def test_wall_seam_without_two_ends_is_none():
    verts, faces = torus()
    parts, _ = split_parts(verts, faces, set())
    assert wall_candidates(verts, parts[0], radians(120)) == []
    assert wall_seam(verts, parts[0], radians(120)) == (None, True)


def test_loop_kind():
    verts, faces = capped_cylinder()
    cuts = {e for loop in ring_seams(verts, faces, radians(60), radians(120)) for e in loop.edges()}
    part = next(p for p in split_parts(verts, faces, cuts)[0] if p.kind == "WALL")
    rim = Loop(list(range(32)), True)
    assert loop_kind(rim, part) == "RING"
    length = wall_candidates(verts, part, radians(120))[0]
    assert loop_kind(length, part) == "LENGTH"
    assert loop_kind(Loop(length.verts[:3], False), part) == "INVALID"      # ends mid-wall
    assert loop_kind(Loop([0, 1, 2], False), part) == "INVALID"             # both ends on one rim


def test_existing_wall_seam_is_found():
    verts, faces = open_tube()
    part = _only_wall(verts, faces)
    column = [0, 12, 24, 36, 48]
    edges = {_edge(a, b) for a, b in zip(column, column[1:])}
    seam = existing_wall_seam(part, edges)
    assert seam is not None and not seam.closed
    assert set(seam.edges()) == edges and seam.verts in (column, column[::-1])
    assert existing_wall_seam(part, edges - {_edge(24, 36)}) is None
    assert existing_wall_seam(part, edges | {_edge(13, 25)}) is None     # a second piece: not one path


def test_existing_seam_cut_by_split_at_seams_is_still_found():
    # with Split at Seams on the old seam is a cut too: its faces stay one part, the seam edges inside it
    verts, faces = open_tube()
    column = [0, 12, 24, 36, 48]
    edges = {_edge(a, b) for a, b in zip(column, column[1:])}
    part = _only_wall(verts, faces, edges)
    seam = existing_wall_seam(part, edges)
    assert seam is not None and set(seam.edges()) == edges


def test_bend_seams_cut_a_right_angle_bend_once_at_45():   # spec acceptance
    verts, faces = clean_bend(bend_rings=4)
    part = _only_wall(verts, faces)
    seam, _ = wall_seam(verts, part, radians(120))
    rings = bend_seams(verts, part, seam, radians(45), radians(120))
    assert len(rings) == 1 and rings[0].closed and len(rings[0].verts) == 12
    centre = [sum(verts[v][k] for v in rings[0].verts) / 12 for k in range(3)]
    middle = (2.0 - 2.0 * math.cos(radians(45)), 0.0, 2.0 * math.sin(radians(45)))   # the bend's middle ring
    assert math.dist(centre, middle) < 1e-9
    assert bend_seams(verts, part, seam, radians(120), radians(120)) == []


def test_bend_seams_on_a_straight_tube_is_empty():
    verts, faces = open_tube()
    part = _only_wall(verts, faces)
    seam, _ = wall_seam(verts, part, radians(120))
    assert bend_seams(verts, part, seam, radians(45), radians(120)) == []
    assert bend_seams(verts, part, seam, radians(1), radians(120)) == []


# --- Task 7: analysis and the seam state model --------------------------------------------------------------------

A120, S60 = radians(120), radians(60)


def _column(i, sides=12, rows=4):
    ids = [k * sides + i for k in range(rows + 1)]
    return {_edge(a, b) for a, b in zip(ids, ids[1:])}


def _kinds(result):
    return sorted(p.kind for p in result.parts)


def test_reference_a():
    verts, faces = capped_cylinder()
    result = analyse(verts, faces, loop_angle=A120, sharp_angle=S60)
    assert _kinds(result) == ["DISK", "DISK", "RING", "RING", "RING", "WALL"]
    (wall,) = [i for i, p in enumerate(result.parts) if p.kind == "WALL"]
    assert list(result.seams) == [wall] and len(result.seams[wall].edges()) == 4
    assert result.warnings == [] and result.fallback == set() and result.breaks == {}
    rims = _rim_edges(verts, faces, 0.0) | _rim_edges(verts, faces, 2.0)
    assert len(result.cuts) == 64 + 96 and rims <= result.cuts


def test_reference_b():
    verts, faces = bent_pipe()
    result = analyse(verts, faces, loop_angle=A120, sharp_angle=S60)
    assert _kinds(result) == ["DISK", "DISK", "WALL"]
    (wall,) = [i for i, p in enumerate(result.parts) if p.kind == "WALL"]
    (pole,) = _pole(faces)
    assert pole in result.seams[wall].verts
    assert result.fallback == set() and result.warnings == []


def test_removed_rim_is_not_found_again():
    verts, faces = capped_cylinder()
    rim = _rim_edges(verts, faces, 0.0)
    result = analyse(verts, faces, loop_angle=A120, sharp_angle=S60, removed=frozenset(rim))
    assert not rim & result.cuts
    merged = [p for p in result.parts if any(f in p.faces for f in (0, 128))]   # a wall face and a bottom ring face
    assert len(merged) == 1
    assert sorted(f for p in result.parts for f in p.faces) == sorted(faces)


def test_added_ring_cuts_a_wall_in_two():
    verts, faces = open_tube()
    middle = {_edge(24 + i, 24 + (i + 1) % 12) for i in range(12)}
    result = analyse(verts, faces, loop_angle=A120, sharp_angle=S60, added=frozenset(middle))
    assert _kinds(result) == ["WALL", "WALL"]
    assert middle <= result.cuts
    assert sorted(result.seams) == [0, 1]
    assert all(len(s.verts) == 3 and loop_kind(s, result.parts[i]) == "LENGTH" for i, s in result.seams.items())


def test_picked_seam_replaces_the_automatic_one():
    verts, faces = open_tube()
    auto = analyse(verts, faces, loop_angle=A120, sharp_angle=S60)
    assert set(auto.seams[0].edges()) == _column(6)      # the lowest start, x = -1
    picked = analyse(verts, faces, loop_angle=A120, sharp_angle=S60, picked=(tuple(sorted(_column(9))),))
    assert set(picked.seams[0].edges()) == _column(9)
    later = analyse(verts, faces, loop_angle=A120, sharp_angle=S60,
                    picked=(tuple(sorted(_column(3))), tuple(sorted(_column(9)))))
    assert set(later.seams[0].edges()) == _column(9)                   # later picks beat earlier
    broken = analyse(verts, faces, loop_angle=A120, sharp_angle=S60, picked=(tuple(sorted(_column(9)))[:2],))
    assert set(broken.seams[0].edges()) == set(auto.seams[0].edges())  # a pick that joins no two ends is ignored


def test_picked_loop_on_a_ring_sets_its_break():
    verts, faces = capped_cylinder()
    # the top ring's cross edge at vertex 0, picked as part of a lengthwise loop that also runs down the wall
    rim0 = 4 * 32
    inner = next(v for v, p in verts.items() if abs(p[0] - 0.671) < 1e-9 and abs(p[1]) < 1e-9 and p[2] == 2.0)
    cross = _edge(rim0, inner)
    loop = tuple(sorted(_column(0, 32, 4))) + (cross,)
    result = analyse(verts, faces, loop_angle=A120, sharp_angle=S60, picked=(loop,))
    rings = [i for i, p in enumerate(result.parts) if p.kind == "RING" and cross in
             {_edge(a, b) for f in p.faces.values() for a, b in zip(f, f[1:] + f[:1])}]
    assert len(rings) == 1 and result.breaks == {rings[0]: cross}


def test_split_at_bends():
    verts, faces = clean_bend()
    off = analyse(verts, faces, loop_angle=A120, sharp_angle=S60)
    assert _kinds(off) == ["WALL"]
    on = analyse(verts, faces, loop_angle=A120, sharp_angle=S60, bend_angle=radians(45))
    assert _kinds(on) == ["WALL", "WALL"] and sorted(on.seams) == [0, 1]
    assert len(on.cuts) == 12 and on.warnings == []
    removed = analyse(verts, faces, loop_angle=A120, sharp_angle=S60, bend_angle=radians(45),
                      removed=frozenset(on.cuts))
    assert _kinds(removed) == ["WALL"]                                   # a removed bend seam is not found again


def test_existing_seam_is_kept():
    verts, faces = open_tube()
    result = analyse(verts, faces, loop_angle=A120, sharp_angle=S60, existing=frozenset(_column(5)))
    assert _kinds(result) == ["WALL"]
    assert set(result.seams[0].edges()) == _column(5) and result.fallback == set()


def test_box_tube_is_free_with_a_warning():           # Review Focus 1
    verts, faces = box_tube()
    result = analyse(verts, faces, loop_angle=A120, sharp_angle=S60)
    assert _kinds(result) == ["FREE"] and len(result.warnings) == 1
    low = analyse(verts, faces, loop_angle=radians(80), sharp_angle=S60)
    assert sorted(f for p in low.parts for f in p.faces) == sorted(faces)


def test_open_tube_is_one_wall():                     # Review Focus 2
    verts, faces = open_tube()
    result = analyse(verts, faces, loop_angle=A120, sharp_angle=S60)
    assert _kinds(result) == ["WALL"] and result.warnings == [] and result.fallback == set()
    assert loop_kind(result.seams[0], result.parts[0]) == "LENGTH" and result.cuts == set()


def test_torus_is_free_with_a_warning():              # Review Focus 3
    result = analyse(*torus(), loop_angle=A120, sharp_angle=S60)
    assert _kinds(result) == ["FREE"] and len(result.warnings) == 1 and result.seams == {}
    assert str(12 * 8) in result.warnings[0]


def test_fallback_wall_is_reported():
    verts, faces = open_tube(twist=radians(5))
    result = analyse(verts, faces, loop_angle=radians(179), sharp_angle=S60)
    assert _kinds(result) == ["WALL"] and result.fallback == {0} and 0 in result.seams


def test_analysis_is_deterministic():
    for mesh, bend in ((capped_cylinder(), None), (bent_pipe(), None), (clean_bend(), radians(45))):
        runs = [analyse(*mesh, loop_angle=A120, sharp_angle=S60, bend_angle=bend) for _ in range(2)]
        assert runs[0].cuts == runs[1].cuts
        assert {i: s.verts for i, s in runs[0].seams.items()} == {i: s.verts for i, s in runs[1].seams.items()}
        assert [sorted(p.faces) for p in runs[0].parts] == [sorted(p.faces) for p in runs[1].parts]


# --- Seam Side: the automatic wall seam on the bottom, top or a side ----------------------------------------------

DOWN, UP, LEFT, RIGHT = (0.0, 0.0, -1.0), (0.0, 0.0, 1.0), (-1.0, 0.0, 0.0), (1.0, 0.0, 0.0)


def _lying(mesh):
    """The mesh turned 90 degrees round X, (x, y, z) -> (x, -z, y): open_tube's axis then runs along world Y and
    ring vertex i sits at x = cos(a), z = sin(a). The turn is proper, so the faces still face out."""
    verts, faces = mesh
    return {v: (p[0], -p[2], p[1]) for v, p in verts.items()}, faces


def _ring_extreme_seam(verts, seam, axis, pick):
    """Every seam vertex has the ``pick`` (min or max) of coordinate ``axis`` among its open_tube ring."""
    for v in seam.verts:
        ring = [w for w in verts if w // 12 == v // 12]
        assert abs(verts[v][axis] - pick(verts[w][axis] for w in ring)) < 1e-6, (v, verts[v])


def test_seam_side_puts_the_seam_on_that_side():
    verts, faces = _lying(open_tube(12, 4))
    part = _only_wall(verts, faces)
    for side, axis, pick in ((DOWN, 2, min), (UP, 2, max), (LEFT, 0, min), (RIGHT, 0, max)):
        seam, fallback = wall_seam(verts, part, A120, side=side)
        assert fallback is False and loop_kind(seam, part) == "LENGTH" and len(seam.verts) == 5
        _ring_extreme_seam(verts, seam, axis, pick)


def test_seam_side_none_is_the_shortest_as_before():
    verts, faces = _lying(open_tube(12, 4))
    part = _only_wall(verts, faces)
    seam, fallback = wall_seam(verts, part, A120, side=None)
    assert fallback is False and set(seam.edges()) == _column(6)       # the lowest start position, x = -1
    assert seam.verts == wall_seam(verts, part, A120)[0].verts


def test_seam_side_along_the_axis_ties_to_the_shortest():
    verts, faces = _lying(open_tube(12, 4))
    part = _only_wall(verts, faces)
    for side in ((0.0, 1.0, 0.0), (0.0, -1.0, 0.0)):                    # every column faces it equally
        assert wall_seam(verts, part, A120, side=side)[0].verts == wall_seam(verts, part, A120)[0].verts


def test_seam_side_on_a_bent_pipe():
    verts, faces = bent_pipe()
    rims = [set(f) for f in faces.values() if len(f) == 12]
    for side in (DOWN, UP, LEFT, RIGHT, (0.0, 1.0, 0.0)):
        result = analyse(verts, faces, loop_angle=A120, sharp_angle=S60, seam_side=side)
        (wall,) = [i for i, p in enumerate(result.parts) if p.kind == "WALL"]
        seam = result.seams[wall]
        assert result.fallback == set() and loop_kind(seam, result.parts[wall]) == "LENGTH"
        assert _is_path(faces, seam)
        assert all(len({seam.verts[0], seam.verts[-1]} & rim) == 1 for rim in rims)
    # +Y is the side of the tube: the seam runs along its y = +1 line, the bend included
    side = analyse(verts, faces, loop_angle=A120, sharp_angle=S60, seam_side=(0.0, 1.0, 0.0))
    (wall,) = [i for i, p in enumerate(side.parts) if p.kind == "WALL"]
    assert all(abs(verts[v][1] - 1.0) < 1e-6 for v in side.seams[wall].verts)


def test_seam_side_through_analyse():
    verts, faces = _lying(open_tube(12, 4))
    down = analyse(verts, faces, loop_angle=A120, sharp_angle=S60, seam_side=DOWN)
    assert set(down.seams[0].edges()) == _column(9)                    # ring vertex 9 sits at z = -1
    again = analyse(verts, faces, loop_angle=A120, sharp_angle=S60, seam_side=DOWN)
    assert down.seams[0].verts == again.seams[0].verts
    picked = analyse(verts, faces, loop_angle=A120, sharp_angle=S60, seam_side=DOWN,
                     picked=(tuple(sorted(_column(3))),))
    assert set(picked.seams[0].edges()) == _column(3)                   # a picked loop wins over the side
    existing = analyse(verts, faces, loop_angle=A120, sharp_angle=S60, seam_side=DOWN, existing=frozenset(_column(5)))
    assert set(existing.seams[0].edges()) == _column(5)                 # so does an existing seam
    none = analyse(verts, faces, loop_angle=A120, sharp_angle=S60, seam_side=None)
    assert set(none.seams[0].edges()) == _column(6)


# --- Hard-surface pass: parts that are no tube, cut at sharp edges or the Hard Edge Angle -------------------------

H30 = radians(30)


def _all_edges(faces):
    return {_edge(a, b) for f in faces.values() for a, b in zip(f, f[1:] + f[:1])}


def _covers_once(result, faces):
    ids = sorted(fid for p in result.parts for fid in p.faces)
    assert ids == sorted(faces), (len(ids), len(faces))


def _summary(result):
    return ([p.kind for p in result.parts], [sorted(p.faces) for p in result.parts], result.cuts,
            {i: s.verts for i, s in result.seams.items()}, result.breaks, result.fallback, result.warnings)


def test_hard_pass_cuts_a_box_into_flat_faces():
    verts, faces = box_tube()
    result = analyse(verts, faces, loop_angle=A120, sharp_angle=S60, hard_angle=H30)
    assert _kinds(result) == ["DISK"] * 6 and result.warnings == []
    _covers_once(result, faces)
    right = {e for e, a in dihedrals(verts, faces).items() if abs(a - math.pi / 2) < 1e-6}
    assert len(right) == 16 and right <= result.cuts     # 8 rim edges, 4 corners of two rows each
    assert sorted(len(p.faces) for p in result.parts) == [1, 1, 2, 2, 2, 2]
    off = analyse(verts, faces, loop_angle=A120, sharp_angle=S60)
    assert _kinds(off) == ["FREE"] and len(off.warnings) == 1 and off.cuts == set()


def test_hard_pass_off_is_the_previous_result():
    for mesh in (box_tube(), capped_cylinder(), bent_pipe(), torus()):
        a = analyse(*mesh, loop_angle=A120, sharp_angle=S60)
        b = analyse(*mesh, loop_angle=A120, sharp_angle=S60, hard_angle=None, sharp=frozenset(_all_edges(mesh[1])))
        assert _summary(a) == _summary(b)


def test_sharp_edges_win_over_the_angle():
    verts, faces = box_tube()
    rims = {e for e, a in dihedrals(verts, faces).items()
            if abs(a - math.pi / 2) < 1e-6 and abs(verts[e[0]][2] - verts[e[1]][2]) < 1e-9}
    assert len(rims) == 8                              # the cap outlines; the 4 vertical corners stay uncut
    result = analyse(verts, faces, loop_angle=A120, sharp_angle=S60, hard_angle=H30, sharp=frozenset(rims))
    assert _kinds(result) == ["DISK", "DISK", "FREE"]
    _covers_once(result, faces)
    free = next(p for p in result.parts if p.kind == "FREE")
    assert len(free.faces) == 8                        # the four sides in one band, not flat
    assert rims <= result.cuts and not (result.cuts - rims)
    assert len(result.warnings) == 1 and "8 faces" in result.warnings[0]


def test_tubes_are_untouched_by_the_hard_pass():
    # every wall edge sharp, and the 12-sided bent pipe's 30-degree lengthwise edges reach the angle: still no change
    for mesh in (capped_cylinder(), bent_pipe(), clean_bend()):
        sharp = frozenset(_all_edges(mesh[1]))
        a = analyse(*mesh, loop_angle=A120, sharp_angle=S60)
        b = analyse(*mesh, loop_angle=A120, sharp_angle=S60, hard_angle=H30, sharp=sharp)
        c = analyse(*mesh, loop_angle=A120, sharp_angle=S60, hard_angle=H30)
        assert _summary(a) == _summary(b) == _summary(c)


def _with_box():
    """A capped cylinder and, beside it, a box tube with its ids moved past the cylinder's."""
    verts, faces = capped_cylinder()
    bverts, bfaces = box_tube()
    vo, fo = max(verts) + 1, max(faces) + 1
    verts = {**verts, **{v + vo: (p[0] + 5.0, p[1], p[2]) for v, p in bverts.items()}}
    faces = {**faces, **{f + fo: tuple(v + vo for v in face) for f, face in bfaces.items()}}
    return verts, faces, set(range(fo, fo + len(bfaces)))


def test_tube_and_box_in_one_mesh():
    verts, faces, box = _with_box()
    alone = analyse(*capped_cylinder(), loop_angle=A120, sharp_angle=S60)
    both = analyse(verts, faces, loop_angle=A120, sharp_angle=S60, hard_angle=H30)
    _covers_once(both, faces)
    tube = [p for p in both.parts if not set(p.faces) & box]
    pieces = [p for p in both.parts if set(p.faces) <= box]
    assert len(tube) + len(pieces) == len(both.parts)
    assert [(p.kind, sorted(p.faces)) for p in tube] == [(p.kind, sorted(p.faces)) for p in alone.parts]
    assert [p.kind for p in pieces] == ["DISK"] * 6 and both.warnings == []
    assert alone.cuts <= both.cuts
    (wall,) = [i for i, p in enumerate(both.parts) if p.kind == "WALL"]
    (alone_wall,) = [i for i, p in enumerate(alone.parts) if p.kind == "WALL"]
    assert list(both.seams) == [wall] and both.seams[wall].verts == alone.seams[alone_wall].verts
    assert loop_kind(both.seams[wall], both.parts[wall]) == "LENGTH"
    # a ring break picked on the cylinder stays keyed to its ring
    rim0 = 4 * 32
    inner = next(v for v, p in verts.items() if abs(p[0] - 0.671) < 1e-9 and abs(p[1]) < 1e-9 and p[2] == 2.0)
    cross = _edge(rim0, inner)
    picked = analyse(verts, faces, loop_angle=A120, sharp_angle=S60, hard_angle=H30, picked=((cross,),))
    (ring,) = picked.breaks
    assert picked.parts[ring].kind == "RING" and cross in _all_edges(picked.parts[ring].faces)


def test_hard_pass_never_cuts_a_removed_seam():
    verts, faces = capped_cylinder()
    rim = frozenset(_rim_edges(verts, faces, 0.0))
    result = analyse(verts, faces, loop_angle=A120, sharp_angle=S60, removed=rim, hard_angle=H30)
    assert not rim & result.cuts
    _covers_once(result, faces)
    sharp = analyse(verts, faces, loop_angle=A120, sharp_angle=S60, removed=rim, hard_angle=H30, sharp=rim)
    assert not rim & sharp.cuts


def test_torus_with_the_hard_pass():
    verts, faces = torus()
    result = analyse(verts, faces, loop_angle=A120, sharp_angle=S60, hard_angle=H30)
    _covers_once(result, faces)
    flat = analyse(verts, faces, loop_angle=A120, sharp_angle=S60, hard_angle=math.pi)   # nothing reaches 180
    assert _kinds(flat) == ["FREE"] and len(flat.warnings) == 1


def _box_with_a_framed_top():
    """A closed 3 x 3 x 1 box whose top is a 3 x 3 grid of unit quads with the middle one missing (a frame round a
    hole) and whose sides are hexagons: one FREE part, cut at its 90-degree edges into six flat pieces, the top one
    with two boundary loops."""
    verts = {y * 4 + x: (float(x), float(y), 1.0) for y in range(4) for x in range(4)}
    verts.update({16: (0.0, 0.0, 0.0), 17: (3.0, 0.0, 0.0), 18: (3.0, 3.0, 0.0), 19: (0.0, 3.0, 0.0)})
    faces = {}
    for y in range(3):
        for x in range(3):
            if (x, y) != (1, 1):
                a = y * 4 + x
                faces[len(faces)] = (a, a + 1, a + 5, a + 4)
    for face in ((16, 17, 3, 2, 1, 0), (17, 18, 15, 11, 7, 3), (18, 19, 12, 13, 14, 15), (19, 16, 0, 4, 8, 12),
                 (16, 19, 18, 17)):
        faces[len(faces)] = face
    return verts, faces


def test_flat_piece_with_a_hole_is_a_disk_at_real_size():
    verts, faces = _box_with_a_framed_top()
    assert _kinds(analyse(verts, faces, loop_angle=A120, sharp_angle=S60)) == ["FREE"]
    result = analyse(verts, faces, loop_angle=A120, sharp_angle=S60, hard_angle=H30)
    _covers_once(result, faces)
    assert _kinds(result) == ["DISK"] * 6 and result.warnings == []
    frame = next(p for p in result.parts if len(p.faces) == 8)
    assert len(frame.boundaries) == 2
    uv = disk_uvs(verts, frame)
    for fid, face in frame.faces.items():
        assert _area([uv[(fid, v)] for v in face]) > 0.0, fid
    total = sum(_area([uv[(fid, v)] for v in face]) for fid, face in frame.faces.items())
    assert abs(total - 8.0) < 1e-9
    again = analyse(verts, faces, loop_angle=A120, sharp_angle=S60, hard_angle=H30)
    assert _summary(result) == _summary(again)


def test_disk_uvs_on_a_flat_quad():
    verts = {0: (0.0, 0.0, 1.0), 1: (2.0, 0.0, 1.0), 2: (2.0, 3.0, 1.0), 3: (0.0, 3.0, 1.0)}
    for face in ((0, 1, 2, 3), (3, 2, 1, 0)):          # facing +Z and -Z
        part = Part("DISK", {0: face}, [list(face)])
        uv = disk_uvs(verts, part)
        assert abs(_area([uv[(0, v)] for v in face]) - 6.0) < 1e-9


# --- Task 8: wall and disk layouts --------------------------------------------------------------------------------


def _area(pts):
    return 0.5 * sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(pts, pts[1:] + pts[:1]))


def _analysed_wall(verts, faces):
    result = analyse(verts, faces, loop_angle=A120, sharp_angle=S60)
    (i,) = [k for k, p in enumerate(result.parts) if p.kind == "WALL"]
    return result.parts[i], result.seams[i]


def _closed_length(verts, ids):
    return sum(math.dist(verts[a], verts[b]) for a, b in zip(ids, ids[1:] + ids[:1]))


def _assert_straight_perimeter(verts, part, seam, uv):
    ends = [b for b in part.boundaries if seam.verts[0] in b or seam.verts[-1] in b]
    width = sum(_closed_length(verts, b) for b in ends) / 2.0
    height = _path_length(verts, seam)
    on_seam = set(seam.verts)
    for (fid, vid), (u, v) in uv.items():
        if vid in on_seam:
            assert min(abs(u), abs(u - width)) < 1e-9
        if any(vid in b for b in ends):
            assert min(abs(v), abs(v - height)) < 1e-9
    us = [u for u, _v in uv.values()]
    vs = [v for _u, v in uv.values()]
    assert min(us) > -1e-9 and max(us) < width + 1e-9 and min(vs) > -1e-9 and max(vs) < height + 1e-9
    return width, height


def _assert_no_flip(part, uv):
    for fid, face in part.faces.items():
        assert _area([uv[(fid, v)] for v in face]) > 0.0, fid


def test_cylinder_wall_is_a_true_size_rectangle():    # spec acceptance
    verts, faces = capped_cylinder()
    part, seam = _analysed_wall(verts, faces)
    uv, quads = wall_uvs(verts, part, seam)
    assert quads is False
    assert set(uv) == {(fid, v) for fid, face in part.faces.items() for v in face}
    us = [u for u, _v in uv.values()]
    vs = [v for _u, v in uv.values()]
    perimeter = 32 * 2.0 * math.sin(math.pi / 32)
    assert abs((max(us) - min(us)) - perimeter) < 1e-6 * perimeter
    assert abs((max(vs) - min(vs)) - 2.0) < 1e-6 * 2.0
    _assert_no_flip(part, uv)


def test_wall_perimeter_is_straight():
    verts, faces = bent_pipe()
    part, seam = _analysed_wall(verts, faces)
    uv, _ = wall_uvs(verts, part, seam)
    _assert_straight_perimeter(verts, part, seam, uv)
    # both sides of the seam are used: every seam vertex has a corner at u = 0 and one at u = W
    width = sum(_closed_length(verts, b) for b in part.boundaries[:2]) / 2.0
    for vid in seam.verts:
        us = {round(u / width) for (fid, w), (u, _v) in uv.items() if w == vid}
        assert us == {0, 1}


def test_wall_has_no_flipped_face():
    for mesh in (bent_pipe(), clean_bend()):
        part, seam = _analysed_wall(*mesh)
        uv, _ = wall_uvs(mesh[0], part, seam)
        _assert_no_flip(part, uv)


def test_pole_triangles_take_the_side_they_lie_on():
    # the triangles beside the pole touch the seam at the pole only; their pole corner must sit on their side
    verts, faces = bent_pipe()
    part, seam = _analysed_wall(verts, faces)
    uv, _ = wall_uvs(verts, part, seam)
    (pole,) = _pole(faces)
    width = sum(_closed_length(verts, b) for b in part.boundaries[:2]) / 2.0
    for fid, face in part.faces.items():
        if pole in face and len(face) == 3:
            others = [uv[(fid, v)][0] for v in face if v != pole]
            u = uv[(fid, pole)][0]
            assert all(abs(o - u) < width / 2 for o in others)


def test_quads_layout_makes_every_face_a_rectangle():
    verts, faces = open_tube()
    part, seam = _analysed_wall(verts, faces)
    uv, quads = wall_uvs(verts, part, seam, quads=True)
    assert quads is True
    for fid, face in part.faces.items():
        pts = [uv[(fid, v)] for v in face]
        assert len({round(u, 9) for u, _v in pts}) == 2 and len({round(v, 9) for _u, v in pts}) == 2
    _assert_no_flip(part, uv)
    _assert_straight_perimeter(verts, part, seam, uv)


def test_quads_layout_on_a_clean_bend():
    verts, faces = clean_bend()
    part, seam = _analysed_wall(verts, faces)
    uv, quads = wall_uvs(verts, part, seam, quads=True)
    assert quads is True
    _assert_no_flip(part, uv)


def test_quads_layout_falls_back_on_triangles():
    verts, faces = bent_pipe()
    part, seam = _analysed_wall(verts, faces)
    uv, quads = wall_uvs(verts, part, seam, quads=True)
    assert quads is False
    _assert_straight_perimeter(verts, part, seam, uv)


def test_wall_with_a_hole_keeps_the_hole_inside():
    verts, faces = open_tube()
    hole = faces.pop(12 + 3)                          # row 1, between columns 3 and 4
    part, seam = _analysed_wall(verts, faces)
    assert len(part.boundaries) == 3
    uv, _ = wall_uvs(verts, part, seam)
    width, height = _assert_straight_perimeter(verts, part, seam, uv)
    for (fid, vid), (u, v) in uv.items():
        if vid in hole:
            assert 1e-6 < u < width - 1e-6 and 1e-6 < v < height - 1e-6
    _assert_no_flip(part, uv)


def test_disk_keeps_real_size():
    verts, faces = capped_cylinder()
    result = analyse(verts, faces, loop_angle=A120, sharp_angle=S60)
    disks = sorted((p for p in result.parts if p.kind == "DISK"), key=lambda p: len(p.faces))
    for part, radius in zip(disks, (0.671, 0.493)):       # the top 32-gon, then the bottom fan
        uv = disk_uvs(verts, part)
        assert set(uv) == {(fid, v) for fid, face in part.faces.items() for v in face}
        us = [u for u, _v in uv.values()]
        vs = [v for _u, v in uv.values()]
        assert abs((max(us) - min(us)) - 2 * radius) < 1e-6
        assert abs((max(vs) - min(vs)) - 2 * radius) < 1e-6
        _assert_no_flip(part, uv)
