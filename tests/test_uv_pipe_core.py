"""UV Pipe core: the seam-loop walker, ring seams, part classification and the lengthwise seam of a wall."""
import math
from collections import Counter
from math import radians

from uv_pipe_fixtures import bent_pipe, capped_cylinder, open_tube
from utils.uv_pipe_core import Loop, dihedrals, neighbours, trace_loop
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
