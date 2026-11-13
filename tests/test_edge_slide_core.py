import math
import random

import pytest
from edge_slide_fixtures import _band, chamfer_ring, jittered_grid, ring, u_in_grid

from utils.edge_slide_core import (
    RAIL_MAX_DEV,
    STEP_AGREE_COS,
    STEP_DIFFER_COS,
    Angles,
    Band,
    OutOfRoom,
    Slider,
    SurfacePoint,
    end_paths,
    nearest_chain,
    positive_side,
    rail_path,
    trace_from_vertex,
    trace_segment,
    wedge,
)


def strip():
    pts = [(0, 0, 0), (1, 0, 0), (2, 0, 0), (3, 0, 0), (0, 1, 0), (1, 1, 0), (2, 1, 0), (3, 1, 0)]
    faces = {0: (0, 1, 5, 4), 1: (1, 2, 6, 5), 2: (2, 3, 7, 6)}
    return _band(pts, faces, [0, 1, 2, 3], [0, 1, 2])


def strip2():
    pts = [(x, 0, 0) for x in range(4)] + [(x, 0.5, 0) for x in range(4)] + [(x, 1, 0) for x in range(4)]
    faces = {
        0: (0, 1, 5, 4), 1: (1, 2, 6, 5), 2: (2, 3, 7, 6),
        3: (4, 5, 9, 8), 4: (5, 6, 10, 9), 5: (6, 7, 11, 10),
    }
    return _band(pts, faces, [0, 1, 2, 3], [0, 1, 2], end_edges=(4, 7))


def strip2_bent(deg):
    """strip2() with vertex 9 placed so that edge 5->9 turns ``deg`` degrees from edge 1->5."""
    b = strip2()
    verts = dict(b.verts)
    verts[9] = (1.0 + 0.5 * math.tan(math.radians(deg)), 1.0, 0.0)
    return Band(verts=verts, faces=b.faces, chain=b.chain, closed=False,
                side_faces=b.side_faces, end_edges=(4, 7))


def box_corner():
    pts = [(0, 0, 1), (1, 0, 1), (1, 1, 1), (0, 0, 0), (1, 0, 0), (1, 1, 0)]
    return _band(pts, {0: (3, 4, 1, 0), 1: (4, 5, 2, 1)}, [0, 1, 2], [0, 1])


def bent():
    pts = [(0, 0, 0), (1, 0, 0), (2, 0.5, 0), (0, 2, 0), (1, 2, 0), (2, 2.5, 0)]
    return _band(pts, {0: (0, 1, 4, 3), 1: (1, 2, 5, 4)}, [0, 1, 2], [0, 1])


def fan():
    pts = [(0, 0, 0), (1, 0, 0), (2, 0, 0), (0, 1, 0), (0.5, 1, 0), (1.4, 1, 0), (2, 1, 0)]
    faces = {0: (0, 1, 4, 3), 1: (1, 5, 4), 2: (1, 2, 6, 5)}
    return _band(pts, faces, [0, 1, 2], [0, 2])


def ngon_diag():
    pts = [(0, 0, 0), (2, 0, 0), (4, 0, 0), (4, 0.5, 0), (4, 1, 0), (0, 1, 0)]
    return _band(pts, {0: (0, 1, 3, 4, 5), 1: (1, 2, 3)}, [0, 1, 2], [0, 1])


def sliver():
    pts = [(0, 0, 0), (1, -0.1, 0), (2, 0, 0), (2, 1, 0), (0, 1, 0)]
    return _band(pts, {0: (0, 1, 2), 1: (0, 2, 3, 4)}, [0, 1, 2], [0, 0])


def end_slide():
    pts = [(0, 0, 0), (2, 0, 0), (2, 0.1, 0), (1, 1, 0), (0, 1, 0)]
    return _band(pts, {0: (0, 1, 2, 3, 4)}, [0, 1], [0])


def u_turn():
    a, b = 2.1414214, 0.1414214
    pts = [(0, 0, 0), (2, 0, 0), (a, b, 0), (a, 1 + b, 0), (0, 1 + b, 0)]
    return _band(pts, {0: (0, 1, 2, 3, 4)}, [0, 1, 2, 3], [0, 0, 0])


def grid_open():
    # A 4x3 grid of unit quads; the open chain (1,1)-(2,1)-(3,1) runs inside it.
    pts = [(x, y, 0) for y in range(4) for x in range(5)]
    faces = {
        y * 4 + x: (y * 5 + x, y * 5 + x + 1, (y + 1) * 5 + x + 1, (y + 1) * 5 + x)
        for y in range(3) for x in range(4)
    }
    return _band(pts, faces, [6, 7, 8], [5, 6], end_edges=(11, 13))


def fold_box():
    # A floor at z=0 and a wall at y=1, folded along the edges (3, 4) and (4, 5).
    pts = [(0, 0, 0), (1, 0, 0), (2, 0, 0), (0, 1, 0), (1, 1, 0), (2, 1, 0), (0, 1, 1), (1, 1, 1), (2, 1, 1)]
    faces = {0: (0, 1, 4, 3), 1: (1, 2, 5, 4), 2: (3, 4, 7, 6), 3: (4, 5, 8, 7)}
    return _band(pts, faces, [0, 1, 2], [0, 1], end_edges=(3, 5))


def tall_grid(rows=30):
    # An 8-wide grid of unit quads, ``rows`` high (vertex y*9+x, face y*8+x); the open chain runs
    # along the bottom border from (2,0) to (6,0), the end edges straight up.
    pts = [(x, y, 0) for y in range(rows + 1) for x in range(9)]
    faces = {y * 8 + x: (y * 9 + x, y * 9 + x + 1, (y + 1) * 9 + x + 1, (y + 1) * 9 + x)
             for y in range(rows) for x in range(8)}
    return _band(pts, faces, [2, 3, 4, 5, 6], [2, 3, 4, 5], end_edges=(11, 15))


def walls_meet():
    # The open chain (0,.3)-(1,1)-(2,1)-(2.5,0) over a strip down to the line y = 0, which the chain
    # meets at its last vertex. The start's end edge 0-4 runs back down to that line (158.6 degrees
    # off the chain); the end's end edge 3-6 runs along it, under the chain (63.4 degrees), so its
    # wall 3-6-5-4 meets the start's wall 0-4 at vertex 4. Both leave by END_SHALLOW (60) at least.
    pts = [(0, 0.3, 0), (1, 1, 0), (2, 1, 0), (2.5, 0, 0), (-0.2, 0, 0), (1, 0, 0), (1.5, 0, 0)]
    faces = {0: (0, 1, 5, 4), 1: (1, 2, 6, 5), 2: (2, 3, 6)}
    return _band(pts, faces, [0, 1, 2, 3], [0, 1, 2], end_edges=(4, 6))


def wall_grid(top_xs, joins, moved=None):
    # A 6-wide grid of unit quads, 5 rows high (vertex y*7+x, face y*6+x), the open chain along the bottom from
    # (2,0) to (4,0), the end edges straight up. Row 2 (y 2..3) is rebuilt: ``joins`` lists its faces as loops of
    # (x, y) points, the points of y = 3 at ``top_xs`` (also the columns of the rows above); ``moved`` moves points.
    pos = {(x, y): (x, y) for y in range(3) for x in range(7)}
    pos.update({(x, y): (x, y) for y in range(3, 6) for x in top_xs})
    pos.update(moved or {})
    ids = {p: i for i, p in enumerate(sorted(pos, key=lambda p: (p[1], p[0])))}
    faces = {y * 6 + x: tuple(ids[p] for p in ((x, y), (x + 1, y), (x + 1, y + 1), (x, y + 1)))
             for y in range(2) for x in range(6)}
    loops = [*joins, *(((a, y), (b, y), (b, y + 1), (a, y + 1)) for y in (3, 4) for a, b in zip(top_xs, top_xs[1:]))]
    faces.update({12 + i: tuple(ids[p] for p in loop) for i, loop in enumerate(loops)})
    verts = {ids[p]: (float(pos[p][0]), float(pos[p][1]), 0.0) for p in pos}
    return Band(verts=verts, faces=faces, chain=[ids[(2, 0)], ids[(3, 0)], ids[(4, 0)]], closed=False,
                side_faces=[2, 3], end_edges=(ids[(2, 1)], ids[(4, 1)])), ids


def ngon_wall(lift, moved=None):
    # wall_grid with row 2's faces over x 1..3 merged into the hexagon (1,2) (2,2) (3,2) (3,3) (2,3) (1,3), and
    # (1,2) lifted by ``lift``. The start wall comes up x = 2 to (2,2), where the hexagon's bottom edges go on: to
    # (3,2) square to the wall, and to (1,2) turned 90 - atan(lift) degrees. ``moved`` moves more points.
    quads = [((x, 2), (x + 1, 2), (x + 1, 3), (x, 3)) for x in (0, 3, 4, 5)]
    hexagon = ((1, 2), (2, 2), (3, 2), (3, 3), (2, 3), (1, 3))
    return wall_grid(range(7), [*quads, hexagon], {(1, 2): (1, 2 + lift), **(moved or {})})


def wall_row():
    # A 7 x 6 grid of unit quads (vertex y*8+x), the open chain along the bottom from (2,0) to (6,0), the end edges
    # straight up. Row 2's faces over x 1..3 are the pentagon (1,2) (2,2) (3,3) (2,3) (1,3) and the triangle (2,2)
    # (3,2) (3,3): the only edge on up from (2,2) is the diagonal to (3,3), on the column chain vertex (3,0)'s rail
    # path runs up.
    pts = [(x, y, 0) for y in range(7) for x in range(8)]
    faces = {f: (y * 8 + x, y * 8 + x + 1, (y + 1) * 8 + x + 1, (y + 1) * 8 + x)
             for f, (x, y) in enumerate((x, y) for y in range(6) for x in range(7) if not (y == 2 and x in (1, 2)))}
    faces[len(faces)] = (17, 18, 27, 26, 25)
    faces[len(faces)] = (18, 19, 27)
    return _band(pts, faces, [2, 3, 4, 5, 6], [2, 3, 4, 5], end_edges=(10, 14))


def pole_wall():
    # wall_grid with five edges at (2,2): the start wall comes up x = 2 into it, and its two edges on up lean 35.0
    # degrees left, to (1.3,3), and 36.9 degrees right, to (2.75,3). The columns above run up from x = 1.3 and 2.75.
    top = (0, 1.3, 2.75, 4, 5, 6)
    joins = [((0, 2), (1, 2), (1.3, 3), (0, 3)), ((1, 2), (2, 2), (1.3, 3)), ((2, 2), (2.75, 3), (1.3, 3)),
             ((2, 2), (3, 2), (2.75, 3)), ((3, 2), (4, 2), (4, 3), (2.75, 3)),
             ((4, 2), (5, 2), (5, 3), (4, 3)), ((5, 2), (6, 2), (6, 3), (5, 3))]
    return wall_grid(top, joins)


def strip_fin():
    # strip() with a fin 1-5-9-8 standing up to z = 1 on its rail edge 1-5, which three faces then hold.
    pts = [(0, 0, 0), (1, 0, 0), (2, 0, 0), (3, 0, 0), (0, 1, 0), (1, 1, 0), (2, 1, 0), (3, 1, 0),
           (1, 0, 1), (1, 1, 1)]
    faces = {0: (0, 1, 5, 4), 1: (1, 2, 6, 5), 2: (2, 3, 7, 6), 3: (1, 5, 9, 8)}
    return _band(pts, faces, [0, 1, 2, 3], [0, 1, 2])


def test_wedge_flat_strip_interior():
    w = wedge(strip(), 1)
    assert w.theta == pytest.approx(math.pi)
    assert w.faces == [1, 0]
    assert len(w.rails) == 1
    r = w.rails[0]
    assert (r.far, r.border) == (5, False)
    assert r.angle == pytest.approx(math.pi / 2) and r.length == pytest.approx(1.0)


def test_wedge_open_ends_carry_border_rails():
    w0, w3 = wedge(strip(), 0), wedge(strip(), 3)
    assert w0.theta == pytest.approx(math.pi / 2)
    assert w0.rails[-1].far == 4 and w0.rails[-1].border and w0.rails[-1].angle == pytest.approx(math.pi / 2)
    assert w3.theta == pytest.approx(math.pi / 2)
    assert w3.rails[0].far == 7 and w3.rails[0].border and w3.rails[0].angle == pytest.approx(0.0)


def test_wedge_box_corner_unfolds_to_straight():
    w = wedge(box_corner(), 1)
    assert w.theta == pytest.approx(math.pi)
    assert [r.far for r in w.rails] == [4]
    assert w.rails[0].angle == pytest.approx(math.pi / 2)


def test_wedge_ngon_shallow_rail():
    w = wedge(ngon_diag(), 1)
    assert w.theta == pytest.approx(math.pi)
    assert [r.far for r in w.rails] == [3]
    assert w.rails[0].angle == pytest.approx(math.atan2(0.5, 2.0))
    assert w.rails[0].length == pytest.approx(math.hypot(2.0, 0.5))


def test_wedge_fan_two_rails_sorted():
    w = wedge(fan(), 1)
    assert [r.far for r in w.rails] == [5, 4]
    assert w.rails[0].angle == pytest.approx(math.atan2(1.0, 0.4))
    assert w.rails[1].angle == pytest.approx(math.atan2(1.0, -0.5))
    assert w.faces == [2, 1, 0]


def test_wedge_sliver_has_no_rail():
    w = wedge(sliver(), 1)
    assert w.rails == []
    assert w.theta == pytest.approx(math.radians(168.5788137), abs=1e-6)


def test_band_rejects_side_face_without_its_edge():
    b = strip()
    with pytest.raises(ValueError):
        Band(verts=b.verts, faces=b.faces, chain=b.chain, closed=False, side_faces=[1, 1, 2])


def test_wedge_closed_ring_wraps_around_chain_start():
    w = wedge(ring(), 0)
    assert w.faces == [0, 3]
    assert [r.far for r in w.rails] == [4]
    assert w.theta == pytest.approx(1.5 * math.pi)  # reflex corner of the inner square


def test_remaining_fixtures_build():
    for make in (strip2, bent, end_slide, u_turn):
        assert make().chain


def test_trace_crosses_one_rail():
    tr = trace_from_vertex(strip(), 0, math.atan2(0.5, 1.5), math.hypot(1.5, 0.5))
    assert [(c.kind, c.edge) for c in tr.crossings] == [("edge", (1, 5))]
    assert tr.crossings[0].t == pytest.approx(1 / 3)
    assert tr.end.kind == "face" and tr.end.face == 1
    assert tr.end.co == pytest.approx((1.5, 0.5, 0.0))
    assert not tr.blocked


def test_trace_unfolds_across_box_corner():
    tr = trace_from_vertex(box_corner(), 0, math.atan2(0.3, 1.5), math.hypot(1.5, 0.3))
    assert tr.crossings[0].edge == (1, 4) and tr.crossings[0].t == pytest.approx(0.2)
    assert tr.crossings[0].co == pytest.approx((1.0, 0.0, 0.8))
    assert tr.end.co == pytest.approx((1.0, 0.5, 0.7))


def test_trace_blocked_at_border():
    tr = trace_from_vertex(strip(), 1, math.atan2(1.0, 0.5), 3.0)
    assert tr.blocked
    assert tr.end.kind == "edge" and tr.end.edge == (5, 6) and tr.end.t == pytest.approx(0.5)


def test_trace_ends_on_vertex():                      # Review Focus 1
    tr = trace_from_vertex(strip2(), 0, math.atan2(0.5, 1.0), math.hypot(1.0, 0.5))
    assert tr.end.kind == "vert" and tr.end.vert == 5


def test_trace_through_vertex_is_one_crossing():      # Review Focus 1
    tr = trace_from_vertex(strip2(), 0, math.atan2(1.0, 2.0), math.hypot(2.0, 1.0))
    assert [(c.kind, c.vert) for c in tr.crossings] == [("vert", 5)]


def test_trace_on_non_planar_face_stays_on_surface():  # Review Focus 5
    b = strip()
    b.verts[4] = (0.0, 1.0, 0.05)
    # (0.3, 0.6) is on vertex 4's side of both possible quad diagonals
    tr = trace_from_vertex(b, 1, math.atan2(0.6, -0.7), math.hypot(0.7, 0.6))
    x, y, z = tr.end.co
    assert (x, y) == pytest.approx((0.3, 0.6), abs=1e-3)
    assert 0.0 < z < 0.05    # on face 0's triangles, not on a flat fit


def test_trace_segment_meets_partner():
    b = bent()
    a = trace_from_vertex(b, 1, math.radians(40.0), 0.5)    # inside face 1, off the rail
    w2 = wedge(b, 2)
    c = trace_from_vertex(b, 2, w2.theta / 2, 0.5)
    seg = trace_segment(b, 1, a, c)
    assert seg.end.co == pytest.approx(c.end.co, abs=1e-6)
    assert not seg.blocked


def test_trace_along_end_border_of_non_planar_face_stays_on_edge():  # Review Focus 5
    b = strip()
    b.verts[4] = (0.0, 1.0, 0.05)    # face 0's diagonal 0-5 splits vertex 0's corner
    tr = trace_from_vertex(b, 0, wedge(b, 0).theta, 0.5)
    assert not tr.blocked
    assert tr.end.kind == "edge" and tr.end.edge == (0, 4)
    assert tr.end.t == pytest.approx(0.5 / math.hypot(1.0, 0.05))


def _pentagon_with_tris():
    """A non-planar pentagon (vertex 3 lifted) given a triangulation that is not the core's fan from 0."""
    pts = [(0, 0, 0), (2, 0, 0), (2.5, 1.2, 0), (1, 2.2, 0.4), (-0.5, 1.2, 0)]
    b = _band(pts, {0: (0, 1, 2, 3, 4)}, [0, 1], [0])
    b.tris = {0: [(1, 2, 3), (1, 3, 4), (1, 4, 0)]}
    return b


def _triangle_distance(p, a, b, c):
    """Distance from ``p`` to triangle abc (closest point by Voronoi regions)."""

    def sub(u, v):
        return (u[0] - v[0], u[1] - v[1], u[2] - v[2])

    def dot(u, v):
        return u[0] * v[0] + u[1] * v[1] + u[2] * v[2]

    def on_segment(u, v):
        d = sub(v, u)
        t = max(0.0, min(1.0, dot(sub(p, u), d) / dot(d, d)))
        return math.dist(p, (u[0] + d[0] * t, u[1] + d[1] * t, u[2] + d[2] * t))

    ab, ac, ap, bp, cp = sub(b, a), sub(c, a), sub(p, a), sub(p, b), sub(p, c)
    d1, d2, d3, d4, d5, d6 = dot(ab, ap), dot(ac, ap), dot(ab, bp), dot(ac, bp), dot(ab, cp), dot(ac, cp)
    va, vb, vc = d3 * d6 - d5 * d4, d5 * d2 - d1 * d6, d1 * d4 - d3 * d2
    if va < 0.0 or vb < 0.0 or vc < 0.0:  # closest point on the border
        return min(on_segment(a, b), on_segment(b, c), on_segment(c, a))
    total = va + vb + vc
    q = tuple(a[i] + ab[i] * vb / total + ac[i] * vc / total for i in range(3))
    return math.dist(p, q)


def _surface_distance(b, tris, p):
    return min(_triangle_distance(p, *(b.verts[v] for v in tri)) for tri in tris)


def test_trace_lands_on_the_given_triangles():                # Review Focus 5
    b = _pentagon_with_tris()
    tr = trace_from_vertex(b, 0, wedge(b, 0).theta / 2, 1.2)
    assert tr.end.kind == "face" and not tr.blocked
    fan = [(0, 1, 2), (0, 2, 3), (0, 3, 4)]
    assert _surface_distance(b, b.tris[0], tr.end.co) < 1e-9
    assert _surface_distance(b, fan, tr.end.co) > 1e-3


def test_wedge_corner_and_trace_share_the_given_triangles():
    b = _pentagon_with_tris()
    # Vertex 0 lies in triangle (1, 4, 0) only: its corner is that triangle's 3D angle.
    u, w = b.verts[1], b.verts[4]
    corner = math.acos((u[0] * w[0] + u[1] * w[1] + u[2] * w[2]) / (math.hypot(*u) * math.hypot(*w)))
    assert wedge(b, 0).theta == pytest.approx(corner)
    tr = trace_from_vertex(b, 0, wedge(b, 0).theta, 0.5)    # along the end-border edge 0-4
    assert tr.end.kind == "edge" and tr.end.edge == (0, 4)
    assert tr.end.t == pytest.approx(0.5 / math.hypot(-0.5, 1.2))


def test_wedge_reflex_corner():
    pts = [(0, 0, 0), (1, 0, 0), (1, -1, 0), (2, -1, 0), (2, 1, 0), (0, 1, 0)]
    b = _band(pts, {0: (0, 1, 2, 3, 4, 5)}, [0, 1, 2], [0, 0])
    assert wedge(b, 1).theta == pytest.approx(1.5 * math.pi)


def test_trace_blocked_at_chain_edge():
    tr = trace_from_vertex(bent(), 0, 0.01, 3.0)
    assert tr.blocked and tr.end.edge == (1, 2)


def _lifted_strip2_traces():
    b = strip2()
    b.verts[5] = (1.0, 0.5, 0.3)    # non-flat interior vertex between the two traces
    a = trace_from_vertex(b, 1, math.radians(120.0), 0.9)
    c = trace_from_vertex(b, 2, math.radians(60.0), 0.9)
    return b, a, c


def test_trace_segment_raises_on_inconsistent_development():
    b, a, c = _lifted_strip2_traces()
    with pytest.raises(ValueError, match="inconsistent development"):
        trace_segment(b, 1, a, c)


def test_place_on_perpendicular_rail_is_exact():
    p = Slider(strip()).place(1, 0.25)
    assert p.rail.far == 5 and p.width_error == pytest.approx(0.0)
    assert p.trace.end.co == pytest.approx((1.0, 0.25, 0.0)) and p.trace.end.kind == "edge"


def test_place_bent_default_uses_rail_with_small_error():
    p = Slider(bent()).place(1, 0.2)
    assert p.rail.far == 4
    assert p.trace.end.co == pytest.approx((1.0, 0.2111456, 0.0), abs=1e-6)
    assert p.width_error == pytest.approx(0.0111456, abs=1e-6)


def test_place_bent_exact_uses_miter():
    p = Slider(bent()).place(1, 0.2, exact=True)
    assert p.rail is None
    assert p.trace.end.co == pytest.approx((0.9527864, 0.2, 0.0), abs=1e-6)


def test_place_fan_picks_rail_nearest_bisector():
    p = Slider(fan()).place(1, 0.3)
    assert p.rail.far == 5
    assert p.trace.end.co == pytest.approx((1.12, 0.3, 0.0), abs=1e-6)


def test_place_rejects_shallow_diagonal():
    p = Slider(ngon_diag()).place(1, 0.25)
    assert p.rail is None and p.trace.crossings == []
    assert p.trace.end.kind == "face" and p.trace.end.face == 0
    assert p.trace.end.co == pytest.approx((2.0, 0.25, 0.0))


def test_place_sliver_miter_crosses_chord():
    p = Slider(sliver()).place(1, 0.2)
    assert [c.edge for c in p.trace.crossings] == [(0, 2)]
    assert p.trace.end.face == 1
    assert p.trace.end.co == pytest.approx((1.0, 0.1009975, 0.0), abs=1e-6)


def test_solve_ring_closed():
    cut = Slider(ring()).solve(0.5)
    assert [pt.co for pt in cut.points] == [pytest.approx(c) for c in
        [(-1.5, -1.5, 0.0), (1.5, -1.5, 0.0), (1.5, 1.5, 0.0), (-1.5, 1.5, 0.0)]]
    assert cut.anchors == [0, 1, 2, 3] and cut.connectors == [] and not cut.clamped


def test_solve_keeps_points_along_an_existing_edge():
    # Ring whose corner rails sit 30.96 degrees off the bisector, so every anchor is a
    # miter landing on a far edge: the loop runs along edges (4, 5) and (6, 7).
    pts = [(-1, -1, 0), (1, -1, 0), (1, 1, 0), (-1, 1, 0),
           (-3, -1.5, 0), (3, -1.5, 0), (3, 1.5, 0), (-3, 1.5, 0)]
    faces = {0: (0, 1, 5, 4), 1: (1, 2, 6, 5), 2: (2, 3, 7, 6), 3: (3, 0, 4, 7)}
    cut = Slider(_band(pts, faces, [0, 1, 2, 3], [0, 1, 2, 3], closed=True)).solve(0.5)
    assert [pt.co for pt in cut.points] == [pytest.approx(c) for c in
        [(-1.5, -1.5, 0.0), (1.5, -1.5, 0.0), (1.5, -1.125, 0.0), (1.5, 1.125, 0.0),
         (1.5, 1.5, 0.0), (-1.5, 1.5, 0.0), (-1.5, 1.125, 0.0), (-1.5, -1.125, 0.0)]]
    assert [(pt.edge, pt.t) for pt in cut.points[:2]] == [((4, 5), pytest.approx(0.25)),
                                                          ((4, 5), pytest.approx(0.75))]
    assert cut.anchors == [0, 1, 4, 5]
    assert cut.connectors == [(0, 0), (1, 1), (2, 4), (3, 5)]


def test_solve_tiny_width_is_empty():
    cut = Slider(ring()).solve(0.0)
    assert cut.points == [] and cut.anchors == [None] * 4


def test_place_out_of_room():
    with pytest.raises(OutOfRoom):
        Slider(strip()).place(1, 1.5)       # past the end of the 1.0 rail
    with pytest.raises(OutOfRoom):
        Slider(ngon_diag()).place(1, 1.5)   # the miter leaves the band


@pytest.mark.parametrize("angle, length", [(90.0, 0.8), (92.0, 0.75)])
def test_segment_drops_crossings_at_its_ends(angle, length):
    # The lift leaves a development mismatch under the meet tolerance. Without the rule,
    # 90 / 0.8 crosses (5, 9) 9e-9 from the start, and 92 / 0.75 crosses (6, 10), the
    # partner anchor's own edge, 5.4e-7 before it.
    b = strip2()
    b.verts[5] = (1.0, 0.5, 3e-4)
    s = Slider(b)
    a = s._trace(1, math.radians(angle), length)
    c = s._trace(2, math.radians(90.0), 0.75)
    seg = s._segment(1, a, c)
    for x in seg.crossings:
        assert math.dist(x.co, a.end.co) > 1e-6 and math.dist(x.co, c.end.co) > 1e-6
    assert [x.edge for x in seg.crossings] == ([] if angle == 90.0 else [(5, 9)])
    if angle == 90.0:
        # The anchor 9e-9 off (5, 9) snaps onto it, so the loop keeps a point on (5, 9)
        # and does not jump from face 3 into face 4.
        assert a.end.kind == "edge" and a.end.edge == (5, 9)
        assert (5, 9) in [p.edge for p in [a.end, *seg.crossings, c.end]]


def test_segment_inconsistent_development_is_out_of_room():
    b, a, c = _lifted_strip2_traces()
    with pytest.raises(OutOfRoom):
        Slider(b)._segment(1, a, c)


def _cos(cut): return [pt.co for pt in cut.points]


def test_solve_strip_open():
    cut = Slider(strip()).solve(0.25)
    assert _cos(cut) == [pytest.approx((x, 0.25, 0.0)) for x in (0.0, 1.0, 2.0, 3.0)]
    assert cut.anchors == [0, 1, 2, 3] and cut.connectors == []


def test_solve_ngon_diagonal_crossing_and_connector():
    cut = Slider(ngon_diag()).solve(0.25)
    assert _cos(cut) == [pytest.approx(c) for c in
        [(0.0, 0.25, 0.0), (2.0, 0.25, 0.0), (3.0, 0.25, 0.0), (4.0, 0.25, 0.0)]]
    assert [pt.kind for pt in cut.points] == ["edge", "face", "edge", "edge"]
    assert cut.points[2].edge == (1, 3) and cut.points[2].t == pytest.approx(0.5)
    assert cut.anchors == [0, 1, 3]
    assert cut.connectors == [(1, 1)]


def test_solve_sliver_skips_connector_that_crosses_chord():
    cut = Slider(sliver()).solve(0.2)
    assert _cos(cut) == [pytest.approx(c, abs=1e-6) for c in
        [(0.0, 0.2009975, 0.0), (1.0, 0.1009975, 0.0), (2.0, 0.2009975, 0.0)]]
    assert cut.connectors == []


def test_end_slides_past_short_end_edge():
    cut = Slider(end_slide()).solve(0.3)
    end = cut.points[-1]
    assert end.kind == "edge" and end.edge == (2, 3)
    assert end.t == pytest.approx(0.2222222, abs=1e-6)
    assert end.co == pytest.approx((1.7777778, 0.3, 0.0), abs=1e-6)


def test_end_on_short_end_edge():
    end = Slider(end_slide()).solve(0.05).points[-1]
    assert end.edge == (1, 2) and end.t == pytest.approx(0.5)


def test_bent_default_and_exact():
    d = Slider(bent()).solve(0.2)
    assert _cos(d) == [pytest.approx(c, abs=1e-6) for c in
        [(0.0, 0.2, 0.0), (1.0, 0.2111456, 0.0), (2.0, 0.7236068, 0.0)]]
    e = Slider(bent()).solve(0.2, exact=True)
    assert _cos(e) == [pytest.approx(c, abs=1e-6) for c in
        [(0.0, 0.2, 0.0), (0.9527864, 0.2, 0.0), (1.0, 0.2236068, 0.0), (2.0, 0.7236068, 0.0)]]


def test_start_end_slides_past_short_end_edge():
    b = end_slide()    # run backwards: the short end edge (1, 2) is now at the start
    cut = Slider(Band(verts=b.verts, faces=b.faces, chain=[1, 0], closed=False, side_faces=[0])).solve(0.3)
    start = cut.points[0]
    assert start.kind == "edge" and start.edge == (2, 3)
    assert start.t == pytest.approx(0.2222222, abs=1e-6)
    assert cut.points[-1].co == pytest.approx((0.0, 0.3, 0.0))
    assert cut.anchors == [0, 1]


def test_end_border_path_crosses_interior_edge():
    s = Slider(strip2())    # the end rails are 0.5 long; the path goes on in the second row
    start, end = s._end(True, 0.75), s._end(False, 0.75)
    assert (start.end.kind, start.end.edge) == ("edge", (4, 8)) and start.end.t == pytest.approx(0.5)
    assert start.end.co == pytest.approx((0.0, 0.75, 0.0)) and start.end_xy == pytest.approx((0.0, 0.75))
    assert (end.end.kind, end.end.edge) == ("edge", (7, 11)) and end.end.t == pytest.approx(0.5)
    assert end.end.co == pytest.approx((3.0, 0.75, 0.0)) and end.end_xy == pytest.approx((0.75, 0.0))
    at_vertex = s._end(True, 0.5)    # Review Focus 1: the offset line runs through vertex 4
    assert (at_vertex.end.kind, at_vertex.end.vert) == ("vert", 4)


def test_end_out_of_room_when_border_path_ends():
    s = Slider(end_slide())
    with pytest.raises(OutOfRoom):
        s._end(False, 1.5)    # taller than the face: the path reaches the other end
    cut = s.solve(1.5)        # solve clamps to the limit instead of raising
    assert cut.clamped and cut.width == pytest.approx(1.0, abs=1e-5)


def test_limits_rail_length_and_ring():
    assert Slider(strip()).limit() == pytest.approx(1.0, abs=1e-6)
    assert Slider(ring()).limit() == pytest.approx(1.0, abs=1e-6)


def test_u_turn_clamps_at_shrink_event():
    s = Slider(u_turn())
    assert s.limit() == pytest.approx(0.2414214, abs=1e-6)
    cut = s.solve(0.3)
    assert cut.clamped and cut.width == pytest.approx(0.2414214, abs=1e-6)


def test_u_turn_collapse_drops_short_segment():
    s = Slider(u_turn())
    assert s.limit(collapse=True) == pytest.approx(1.1414214, abs=1e-6)
    cut = s.solve(0.3, collapse=True)
    assert [pt.co for pt in cut.points] == [pytest.approx(c, abs=1e-6) for c in
        [(0.0, 0.3, 0.0), (1.8414214, 0.3, 0.0), (1.8414214, 1.1414214, 0.0)]]
    assert cut.anchors == [0, 1, 1, 2] and not cut.clamped


def test_snap_to_border_vertex():
    sp = SurfacePoint(kind="vert", face=0, co=(2.0, 0.1, 0.0), vert=2)
    assert Slider(end_slide()).snap_width(sp) == pytest.approx(0.1, abs=1e-6)


def test_snap_on_rail_default_and_exact():
    sp = SurfacePoint(kind="edge", face=0, co=(1.0, 0.3, 0.0), edge=(1, 4), t=0.15)
    s = Slider(bent())
    assert s.snap_width(sp) == pytest.approx(0.2841641, abs=1e-6)
    assert s.snap_width(sp, exact=True) == pytest.approx(0.2683282, abs=1e-6)


def test_closed_collapse_group_wraps_past_chain_start():
    s = Slider(chamfer_ring())
    assert s.limit() == pytest.approx(0.3414214, abs=1e-6)
    cut = s.solve(0.5, collapse=True)
    assert _cos(cut) == [pytest.approx(p) for p in
        [(1.5, -1.5, 0.0), (1.5, 1.5, 0.0), (-1.5, 1.5, 0.0), (-1.5, -1.5, 0.0)]]
    assert cut.anchors == [3, 0, 0, 1, 1, 2, 2, 3] and not cut.clamped


def test_collapse_schedule_is_worked_out_once():
    s = Slider(u_turn())
    for w in (0.3, 0.6, 1.0):
        x = 2.1414214 - w
        cut = s.solve(w, collapse=True)
        assert _cos(cut) == [pytest.approx(c, abs=1e-6) for c in [(0.0, w, 0.0), (x, w, 0.0), (x, 1.1414214, 0.0)]]
        assert cut.anchors == [0, 1, 1, 2]
    events = s._schedule(False)
    assert events == [(pytest.approx(0.2414214, abs=1e-6), [1])]
    assert s._schedule(False) is events

    r = Slider(chamfer_ring())
    for w in (0.5, 1.0):
        h = 2.0 - w
        cut = r.solve(w, collapse=True)
        assert _cos(cut) == [pytest.approx(c) for c in [(h, -h, 0.0), (h, h, 0.0), (-h, h, 0.0), (-h, -h, 0.0)]]
        assert cut.anchors == [3, 0, 0, 1, 1, 2, 2, 3]
    assert r._schedule(False) == [(pytest.approx(0.3414214, abs=1e-6), [1, 3, 5, 7]), (pytest.approx(2.0), None)]


def test_snap_past_a_fold_needs_collapse():
    sp = SurfacePoint(kind="face", face=0, co=(1.8414214, 0.7, 0.0))    # on edge 2's offset line at width 0.3
    s = Slider(u_turn())
    assert s.snap_width(sp) is None    # the loop stops at the 0.2414214 fold
    assert s.snap_width(sp, collapse=True) == pytest.approx(0.3, abs=1e-6)


def test_collapse_snap_takes_the_first_crossing():
    # Near its collapse limit this loop shrinks to a point whose segments are too short
    # to sign the offset (it reads positive there again); the first crossing still counts.
    rnd = random.Random(1)  # noqa: S311 - a seeded fixture, not security
    pts =[(2.0 * math.cos(a), math.sin(a), 0.0) for a in sorted(rnd.uniform(0.0, 2.0 * math.pi) for _ in range(64))]
    s = Slider(_band(pts, {0: tuple(range(64))}, list(range(64)), [0] * 64, closed=True))
    target = (0.3, 0.1)
    w = s.snap_width(SurfacePoint(kind="face", face=0, co=(*target, 0.0)), collapse=True)
    loop = [p.co[:2] for p in s.solve(w, collapse=True).points]
    gap = min(
        math.dist(target, (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t))
        for a, b in zip(loop, loop[1:] + loop[:1])
        for t in [max(0.0, min(1.0, ((target[0] - a[0]) * (b[0] - a[0]) + (target[1] - a[1]) * (b[1] - a[1]))
                                / ((b[0] - a[0]) ** 2 + (b[1] - a[1]) ** 2)))]
    )
    assert gap < 1e-6


def test_snap_to_mid_loop_vertex_named_with_any_face():    # Review Focus 1
    sp = SurfacePoint(kind="vert", face=99, co=(1.0, 0.5, 0.0), vert=5)    # 99: not a band face
    assert Slider(strip2()).snap_width(sp) == pytest.approx(0.5, abs=1e-6)


def test_snap_outside_band_is_none():
    sp = SurfacePoint(kind="face", face=0, co=(0.5, -0.5, 0.0))
    assert Slider(strip()).snap_width(sp) is None


def test_positive_side_open_is_screen_right():
    chain = [(0.0, 0.0), (0.0, 10.0)]
    assert positive_side(chain, (5.0, 5.0), (-5.0, 5.0), False) == 1
    assert positive_side(chain, (-5.0, 5.0), (5.0, 5.0), False) == -1
    assert positive_side(chain, None, (5.0, 5.0), False) == -1


def test_positive_side_closed_is_inside():
    sq = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)]
    assert positive_side(sq, (5.0, 5.0), (20.0, 5.0), True) == 1
    assert positive_side(sq, (20.0, 5.0), (5.0, 5.0), True) == -1
    assert positive_side(sq, (20.0, 5.0), (30.0, 5.0), True) == 1


def test_nearest_chain():
    a = [(0.0, 0.0), (10.0, 0.0)]
    b = [(0.0, 5.0), (10.0, 5.0)]
    assert nearest_chain([a, b], [False, False], (3.0, 4.0)) == 1


def test_rail_path_continues_through_rows():
    path = rail_path(strip2(), 1, wedge(strip2(), 1).rails[0])
    assert [v for v, _xy in path] == [1, 5, 9]
    # wedge frame of chain[1]: angle 0 = outgoing chain edge (+x), the side at +y
    assert path[1][1] == pytest.approx((0.0, 0.5)) and path[2][1] == pytest.approx((0.0, 1.0))


def test_solve_passes_the_existing_mid_loop():
    s = Slider(strip2())
    assert s.limit() == pytest.approx(1.0, abs=1e-6)
    cut = s.solve(0.7)
    assert [pt.co for pt in cut.points] == [pytest.approx((x, 0.7, 0.0)) for x in (0.0, 1.0, 2.0, 3.0)]
    assert cut.points[1].edge == (5, 9) and cut.points[1].t == pytest.approx(0.4)


def test_open_chain_in_a_grid_stays_between_its_end_walls():
    s = Slider(grid_open())
    assert s.limit() == pytest.approx(2.0, abs=1e-6)
    cut = s.solve(1.5)
    assert [pt.co for pt in cut.points] == [pytest.approx((x, 2.5, 0.0)) for x in (1.0, 2.0, 3.0)]
    assert [pt.edge for pt in cut.points] == [(11, 16), (12, 17), (13, 18)]


def test_end_paths_run_up_the_end_walls():
    assert end_paths(grid_open()) == ([6, 11, 16], [8, 13, 18])
    assert end_paths(u_in_grid()) == ([33, 34, 35, 36, 37, 38], [38, 37, 36, 35, 34, 33])   # walls run on together
    assert end_paths(ring()) == ([], [])


def test_end_turns_onto_the_other_wall_where_the_walls_meet():
    b = walls_meet()
    # Each end's path turns at 4 onto the other end's wall and runs on along it to the other chain end.
    assert end_paths(b) == ([0, 4, 5, 6, 3], [3, 6, 5, 4, 0])
    s = Slider(b)
    assert s.solve(0.1).points[0].edge == (0, 4)               # short of 4, 0.16 / sqrt(1.49) from edge 0's line
    start = s.solve(0.5).points[0]
    assert start.kind == "edge" and start.edge == (4, 5)       # past 4, on the other wall
    assert start.co == pytest.approx(((0.5 * math.sqrt(1.49) - 0.3) / 0.7, 0.0, 0.0))
    # Past 4 the slide runs on until segment 0 folds: along chain edge 0 the start, at x = (sqrt(1.49) w - .3) / .7
    # on y = 0, overtakes vertex 1's new vertex (1, 1 - w / h1) on its rail, h1 the balanced width at 5.
    h1 = (1.0 + 1.0 / math.sqrt(1.49)) / 2.0
    assert s.limit() == pytest.approx((1.7 + 0.3 / 0.7) / (math.sqrt(1.49) / 0.7 + 0.7 / h1), abs=1e-6)


def _grid_points(ids, verts):
    names = {i: p for p, i in ids.items()}
    return [names[v] for v in verts]


def test_end_wall_ends_at_a_pole():
    # An end wall goes on like a rail path, within RAIL_MAX_DEV of straight on. At the pole (2,2) the start wall's
    # two edges on up turn 35.0 and 36.9 degrees: the wall ends there, and the slide clamps where the start's offset
    # line y = w leaves it, at width 2 (and the end's snap tolerance past it).
    b, ids = pole_wall()
    assert _grid_points(ids, end_paths(b)[0]) == [(2, 0), (2, 1), (2, 2)]
    s = Slider(b)
    assert s.limit() == pytest.approx(2.0, abs=1e-5)
    cut = s.solve(2.5)
    assert cut.clamped and cut.width == pytest.approx(2.0, abs=1e-5)


def test_end_wall_ends_at_an_ngon():
    # The start wall reaches the hexagon at (2,2), where its edges on turn 63.4 degrees (to (1,2.5), lifted) or 90
    # (to (3,2), and to (1,2) not lifted): past RAIL_MAX_DEV either way, so the wall ends at (2,2), and so does the
    # slide, at width 2.
    for lift in (0.5, 0.0):
        b, ids = ngon_wall(lift)
        assert _grid_points(ids, end_paths(b)[0]) == [(2, 0), (2, 1), (2, 2)]
        assert Slider(b).limit() == pytest.approx(2.0, abs=1e-5)


def test_end_wall_ends_the_same_on_a_chain_tilted_by_a_hair():
    # ngon_wall(0) with chain vertex (3,0) a hair low: the start's chain edge tilts by 1e-9. The wall still ends at
    # (2,2), and the limit stays.
    level = Slider(ngon_wall(0.0)[0]).limit()
    b, ids = ngon_wall(0.0, {(3, 0): (3, -1e-9)})
    assert _grid_points(ids, end_paths(b)[0]) == [(2, 0), (2, 1), (2, 2)]
    assert Slider(b).limit() == pytest.approx(level, abs=1e-6)


def test_end_wall_short_of_a_rail_path_column_limits_exactly():
    # wall_row's start wall comes up x = 2 to (2,2), where its only edge on, the diagonal to (3,3), turns 45
    # degrees: the wall ends there, short of chain vertex (3,0)'s rail path up x = 3, and the slide clamps at width 2.
    # Every width up to the limit solves.
    b = wall_row()
    assert end_paths(b)[0] == [2, 10, 18]
    s = Slider(b)
    limit = s.limit()
    assert limit == pytest.approx(2.0, abs=1e-5)
    for i in range(1, 101):
        s.solve(limit * i / 100)
    assert not s.solve(0.99 * limit).clamped


def test_end_wall_ends_where_a_jittered_grid_turns_past_the_rail_rule():
    # On this grid the start wall's second edge, on up from (2,1), turns 31 degrees: the wall ends at vertex 13, and
    # the slide clamps where the start's offset line (the chain runs along y = 0) leaves it, at 13's height.
    b = jittered_grid(1)
    assert end_paths(b) == ([2, 13], [8 + 11 * y for y in range(9)])
    assert Slider(b).limit() == pytest.approx(b.verts[13][1], abs=1e-5)


def test_edge_held_by_three_faces_is_a_border():
    b = strip_fin()
    with pytest.raises(ValueError):
        wedge(b, 1)                     # the sweep round 1 stops at 1-5: the wedge does not get round
    tr = trace_from_vertex(b, 0, math.atan2(0.5, 1.5), math.hypot(0.5, 1.5))   # toward (1.5, .5)
    assert tr.blocked and tr.end.edge == (1, 5)
    assert tr.end.co == pytest.approx((1.0, 1.0 / 3.0, 0.0))


def test_trace_is_blocked_by_an_end_wall():
    tr = trace_from_vertex(grid_open(), 1, math.atan2(1.0, -1.5), math.hypot(1.5, 1.0))
    assert tr.blocked and tr.end.edge == (6, 11)
    assert tr.end.co == pytest.approx((1.0, 1.0 + 2.0 / 3.0, 0.0), abs=1e-6)


def test_slide_crosses_a_fold_onto_the_wall():
    s = Slider(fold_box())
    assert s.limit() == pytest.approx(2.0, abs=1e-6)
    cut = s.solve(1.4)
    assert [pt.co for pt in cut.points] == [pytest.approx((x, 1.0, 0.4)) for x in (0.0, 1.0, 2.0)]


def test_rail_path_bend_falls_back_to_a_miter():
    b = strip2()
    verts = dict(b.verts)
    verts[9] = (1.8, 1.0, 0.0)          # edge 5→9 now leans 58° off straight-on: the path stops at 5
    b = Band(verts=verts, faces=b.faces, chain=b.chain, closed=False,
             side_faces=b.side_faces, end_edges=(4, 7))
    cut = Slider(b).solve(0.7)
    assert [pt.co for pt in cut.points] == [pytest.approx(c, abs=1e-6) for c in
        [(0.0, 0.7, 0.0), (1.0, 0.7, 0.0), (1.32, 0.7, 0.0), (2.0, 0.7, 0.0), (3.0, 0.7, 0.0)]]
    assert cut.points[1].kind == "face"                          # miter inside face 3
    assert cut.points[2].edge == (5, 9) and cut.points[2].t == pytest.approx(0.4)


def test_past_the_rail_path_end_connects_to_its_last_vertex():
    b = strip2()
    verts = dict(b.verts)
    verts[9] = (1.8, 1.0, 0.0)          # the rail path of chain vertex 1 ends at 5
    b = Band(verts=verts, faces=b.faces, chain=b.chain, closed=False,
             side_faces=b.side_faces, end_edges=(4, 7))
    cut = Slider(b).solve(0.7)
    assert cut.connectors == [(5, 1)]                            # 5 -> (1, .7) crosses nothing
    # Exact too: 1 -> 5 holds the width exactly (the chain is straight), so the vertex goes on from 5 as well.
    assert Slider(b).solve(0.7, exact=True).connectors == [(5, 1)]


def test_snap_to_end_wall_vertex_unfolds_on_the_chain_side():
    b = grid_open()
    sp = SurfacePoint(kind="vert", face=0, co=b.verts[11], vert=11)    # vertex 11 is on the start wall
    assert Slider(b).snap_width(sp) == pytest.approx(1.0, abs=1e-6)


def test_end_walls_stop_at_the_chain_and_collapse_runs_until_the_arms_meet():
    b = u_in_grid()
    # The wall across the mouth ends on the far chain end (38) instead of running on past it.
    assert [v for v, _xy in rail_path(b, 0, wedge(b, 0).rails[-1])] == [33, 34, 35, 36, 37, 38]
    s = Slider(b)
    assert s.limit() == pytest.approx(1.0, abs=1e-6)                   # the corner segments fold
    assert s.limit(collapse=True) == pytest.approx(2.5, abs=1e-6)      # the arms meet
    cut = s.solve(2.0, collapse=True)
    assert [pt.co for pt in cut.points] == [pytest.approx(c) for c in
        [(3.0, 4.0, 0.0), (3.0, 3.0, 0.0), (4.0, 3.0, 0.0), (4.0, 4.0, 0.0)]]


def test_collapse_past_a_rail_path_end_folds_where_its_ray_runs():
    # u_in_grid with (3,2) moved to (3.3,2): the rail path of chain vertex 5, (3,1), ends there (the edge on turns
    # 33.4 degrees), so past width 1 its new vertex goes on straight up from (3.3,2), at (3.3, 1 + w). The left
    # corner's group, merged on (1 + w, 1 + w) from width 1, folds segment 4 onto it at 2.3, not at 2.0, where a
    # ray up from (3,1) itself would be.
    b = u_in_grid()
    b.verts[19] = (3.3, 2.0, 0.0)
    s = Slider(b)
    assert [w for w, segs in s._schedule(False) if segs and 4 in segs] == [pytest.approx(2.3)]
    cut = s.solve(2.1, collapse=True)
    assert cut.points[cut.anchors[5]].co == pytest.approx((3.3, 3.1, 0.0))
    assert cut.points[cut.anchors[4]].co == pytest.approx((3.1, 3.1, 0.0))


def test_limit_on_a_tall_grid_is_exact_and_takes_few_solves(monkeypatch):
    s = Slider(tall_grid(30))
    solves = []
    solve = s._solve
    monkeypatch.setattr(s, "_solve", lambda *a: (solves.append(a), solve(*a))[1])
    assert s.limit() == pytest.approx(30.0, abs=1e-9)
    assert len(solves) <= 2    # the trace-free plan finds the bound; full solves only confirm it


def test_snap_to_a_vertex_at_the_limit():
    # strip2's first row with the bridge's triangles: vertex 5 lies on the border the limit stops at,
    # and the loop's offset from it there is +2e-16 of float noise, not a sign change.
    b2 = strip2()
    b = _band([b2.verts[i] for i in range(8)], {0: (0, 1, 5, 4), 1: (1, 2, 6, 5), 2: (2, 3, 7, 6)},
              [0, 1, 2, 3], [0, 1, 2])
    b.tris = {0: [(0, 1, 5), (0, 5, 4)], 1: [(1, 2, 6), (1, 6, 5)], 2: [(2, 3, 7), (2, 7, 6)]}
    s = Slider(b)
    assert s.limit() == pytest.approx(0.5, abs=1e-9)
    assert s.snap_width(SurfacePoint(kind="vert", face=0, co=b.verts[5], vert=5)) == pytest.approx(0.5, abs=1e-9)


@pytest.mark.parametrize("exact", [False, True])
def test_slide_runs_on_past_the_rail_path_without_a_jump(exact):
    b = strip2()
    verts = dict(b.verts)
    verts[5] = (1.25, 0.5, 0.0)    # rail 1->5 leans 26.6 degrees; edge 5->9 turns 53 degrees: the path ends at 5
    s = Slider(Band(verts=verts, faces=b.faces, chain=b.chain, closed=False, side_faces=b.side_faces,
                    end_edges=(4, 7)))
    # Both modes go on from 5 along the bisector, straight up: 1e-4 more width moves the vertex 1e-4.
    at_end, past = s.place(1, 0.5, exact=exact), s.place(1, 0.5001, exact=exact)
    assert at_end.trace.end.co == pytest.approx((1.25, 0.5, 0.0))
    assert past.trace.end.co == pytest.approx((1.25, 0.5001, 0.0))
    assert math.dist(at_end.trace.end.co, past.trace.end.co) == pytest.approx(1e-4, rel=1e-6)
    assert past.width_error == pytest.approx(at_end.width_error)    # the ray runs along the bisector


def _vert_point(band, v):
    return SurfacePoint(kind="vert", face=-1, co=band.verts[v], vert=v)    # -1: named with no face


def _strip2_runs_on_past_its_path():
    # strip2() with vertex 5 at (1.25, .5): chain vertex 1's rail path ends at 5, so its vertex runs on along the ray.
    b = strip2()
    verts = dict(b.verts)
    verts[5] = (1.25, 0.5, 0.0)
    return Band(verts=verts, faces=b.faces, chain=b.chain, closed=False, side_faces=b.side_faces, end_edges=(4, 7))


def frustum(flip=True, n=8, taper=0.1, rows=5, twist=0.0):
    # A closed chain round the bottom ring of a frustum: ring j has radius 3 - taper j at height 0.3 j, vertex
    # j*n + i; quad (a, b, c, d) of ring j is split as (a, b, c) + (a, c, d), or (a, b, d) + (b, c, d) without
    # ``flip``, faces 2 (j*n + i) and 2 (j*n + i) + 1. Round the ring the band does not develop back onto itself.
    # Each ring turns ``twist`` of a chain edge's angle further than the one below.
    verts = {j * n + i: ((3.0 - taper * j) * math.cos(2.0 * math.pi * (i + twist * j) / n),
                         (3.0 - taper * j) * math.sin(2.0 * math.pi * (i + twist * j) / n), 0.3 * j)
             for j in range(rows + 1) for i in range(n)}
    faces = {}
    for j in range(rows):
        for i in range(n):
            a, b, c, d = j * n + i, j * n + (i + 1) % n, (j + 1) * n + (i + 1) % n, (j + 1) * n + i
            faces[2 * (j * n + i)], faces[2 * (j * n + i) + 1] = ((a, b, c), (a, c, d)) if flip else ((a, b, d), (b, c, d))
    return Band(verts=verts, faces=faces, chain=list(range(n)), closed=True, side_faces=[2 * i for i in range(n)])


def _loop_gap(cut, p):
    """Distance from ``p`` to the closed polyline through ``cut``'s points, in 3D."""
    pts = [pt.co for pt in cut.points]
    best = math.inf
    for a, b in zip(pts, pts[1:] + pts[:1]):
        ab = [b[i] - a[i] for i in range(3)]
        l2 = sum(c * c for c in ab)
        t = 0.0 if l2 == 0.0 else max(0.0, min(1.0, sum((p[i] - a[i]) * ab[i] for i in range(3)) / l2))
        best = min(best, math.dist(p, [a[i] + t * ab[i] for i in range(3)]))
    return best


def test_snap_on_a_closed_frustum_reaches_every_vertex():
    # Round a closed chain on a frustum the band does not develop back onto itself. Each target is developed into
    # the frame nearest it, so the loop at its snapped width runs through it, wherever it lies round the ring. On
    # the steep 7-sided one, many frame faces lie as many triangles away from a top vertex as the nearest one.
    for flip, n, taper in ((True, 8, 0.1), (False, 8, 0.1), (True, 7, 0.2)):
        b = frustum(flip, n, taper)
        s = Slider(b)
        for v in sorted(set(b.verts) - set(b.chain)):
            w = s.snap_width(_vert_point(b, v))
            assert w is not None, (flip, n, v)
            assert _loop_gap(s.solve(w), b.verts[v]) < 1e-6, (flip, n, v, w)


def test_snap_on_a_closed_chain_reaches_back_along_it():
    # A target is developed into the frame of its nearest frame face and hopped from there both ways round a
    # closed chain, back as well as ahead. On the twisted frustum vertex 10 lies on frame face 0, (0, 1, 10), but a
    # 0.4 chain edge back, over segment 9: it is reached one hop back.
    b = frustum(flip=False, n=10, taper=0.15, twist=-0.4)
    s = Slider(b)
    w = s.snap_width(_vert_point(b, 10))
    assert w is not None
    assert _loop_gap(s.solve(w), b.verts[10]) < 1e-6
    # On the chamfered square every point of its one face is developed in chain vertex 0's frame. A point in front
    # of chamfer 5 is reached three hops back, the last frame filled going back: it lies 0.4 / sqrt(2) inward of
    # the chamfer's line x - y = -3.8.
    assert Slider(chamfer_ring()).snap_width(SurfacePoint(kind="face", face=0, co=(-1.7, 1.7, 0.0))) == \
        pytest.approx(0.4 / math.sqrt(2.0), abs=1e-9)


def test_snaps_on_one_slider_match_fresh_sliders():
    # The Slider keeps each target's development from one target to the next: each still snaps as on a fresh Slider.
    for band in (grid_open(), fold_box(), walls_meet(), u_in_grid(), ring(), frustum()):
        shared = Slider(band)
        for v in sorted(set(band.verts) - set(band.chain)):
            assert shared.snap_width(_vert_point(band, v)) == Slider(band).snap_width(_vert_point(band, v)), v
    b = grid_open()
    s = Slider(b)
    assert s.snap_width(_vert_point(b, 12)) == pytest.approx(1.0, abs=1e-9)    # (2, 2)
    assert s.snap_width(_vert_point(b, 17)) == pytest.approx(2.0, abs=1e-9)    # (2, 3), at the limit
    assert s.snap_width(_vert_point(b, 16)) == pytest.approx(2.0, abs=1e-9)    # (1, 3), on the start wall
    assert s.snap_width(_vert_point(b, 0)) is None                             # (0, 0), round the chain's end
    b = fold_box()
    assert Slider(b).snap_width(_vert_point(b, 7)) == pytest.approx(2.0, abs=1e-9)   # (1, 1, 1), up the wall


def test_snap_targets_develop_only_their_way_to_the_chain(monkeypatch):
    # A target is developed from its nearest frame face, laying out only the faces on the way, each once: the
    # band is never unfolded whole.
    b = tall_grid(30)
    surf = Slider(b)._surf
    placed = []
    beyond = surf._beyond
    monkeypatch.setattr(surf, "_beyond", lambda *a: (placed.append(a), beyond(*a))[1])
    # (3, 5) is held first by the face in row 4 of column 2. (2, 27) is held first by a face left of the start
    # wall, which no frame face reaches, then by the one in row 26 of column 2: rows 1 to 4 of that column are
    # laid out already. The second (3, 5) is the first one again.
    for (x, y), steps in (((3, 5), 4), ((5, 12), 11), ((2, 27), 22), ((3, 5), 0)):
        placed.clear()
        spots = surf.in_frames(_vert_point(b, 9 * y + x))
        assert len(placed) == steps, (x, y, len(placed))
        assert spots[0] == pytest.approx((x - 2.0, y)) and spots[1] == pytest.approx((x - 3.0, y)), (x, y)


def cube(order):
    # A unit cube, its faces numbered in ``order``; the open chain is the top front edge 4-5, all six faces are
    # in the band and the end edges run back along the top. The end walls run on down the back, 4-7-3-0 and
    # 5-6-2-1, so the side and bottom faces are reached only the long way round: over the back, the bottom and
    # the front.
    pts = [(-.5, -.5, -.5), (.5, -.5, -.5), (.5, .5, -.5), (-.5, .5, -.5),
           (-.5, -.5, .5), (.5, -.5, .5), (.5, .5, .5), (-.5, .5, .5)]
    loops = {"top": (4, 5, 6, 7), "right": (5, 1, 2, 6), "back": (6, 2, 3, 7), "left": (7, 3, 0, 4),
             "bottom": (0, 3, 2, 1), "front": (0, 1, 5, 4)}
    return _band(pts, {i: loops[name] for i, name in enumerate(order)}, [4, 5], [order.index("top")],
                 end_edges=(7, 6))


def test_snap_target_is_developed_in_its_face_nearest_the_chain():
    # A corner at the bottom back is held by the back face, one face from the chain, and by a side face, which
    # the walk reaches only round the bottom and the front. It is developed in the back face, whichever comes
    # first in the band: the loop reaches it at width 2 (over the top and down the back), not 3.
    for order in (("top", "right", "back", "left", "bottom", "front"),
                  ("top", "left", "back", "right", "front", "bottom")):
        b = cube(order)
        s = Slider(b)
        widths = [s.snap_width(_vert_point(b, v)) for v in (7, 6, 3, 2, 0, 1)]
        assert widths == [pytest.approx(w, abs=1e-9) for w in (1.0, 1.0, 2.0, 2.0, 3.0, 3.0)], order


def test_snap_behind_the_chain_develops_no_rail_path(monkeypatch):
    # At width 0 the loop is the chain itself: a target the loop never reaches is told apart there, without
    # developing a rail path or tracing a ray.
    b = grid_open()
    s = Slider(b)
    aimed = []
    aim = s._aim
    monkeypatch.setattr(s, "_aim", lambda *a: (aimed.append(a), aim(*a))[1])
    assert s.snap_width(_vert_point(b, 0)) is None    # (0, 0), round the chain's end
    assert s.snap_width(_vert_point(b, 2)) is None    # (2, 0), behind the chain
    assert aimed == []


def test_solves_on_one_slider_match_fresh_sliders():
    # A Slider keeps the traces along each rail path from one width to the next: each still solves as a fresh one.
    for band, widths in ((tall_grid(30), (20.5, 3.25, 29.0, 20.25)), (strip2(), (0.7, 0.3, 0.95)),
                         (fold_box(), (1.4, 0.5, 1.9)), (_strip2_runs_on_past_its_path(), (0.7, 0.3, 0.5001))):
        shared = Slider(band)
        for w in widths:
            for exact in (False, True):
                a, b = shared.solve(w, exact=exact), Slider(band).solve(w, exact=exact)
                assert (a.points, a.anchors, a.connectors, a.width, a.clamped) == \
                    (b.points, b.anchors, b.connectors, b.width, b.clamped), (w, exact)


def test_solves_trace_each_rail_path_leg_once(monkeypatch):
    # Every width past a rail path point walks the same legs up to it, so a Slider traces each leg once.
    b = tall_grid(30)
    s = Slider(b)
    assert [pt.co for pt in s.solve(20.5).points] == [pytest.approx((x, 20.5, 0.0)) for x in range(2, 7)]
    traced = []
    trace = s._surf.trace
    monkeypatch.setattr(s._surf, "trace", lambda *a: (traced.append(a), trace(*a))[1])
    assert [pt.co for pt in s.solve(20.25).points] == [pytest.approx((x, 20.25, 0.0)) for x in range(2, 7)]
    assert len(traced) == 3 + 4    # the last leg of each of the 3 interior vertices, and the 4 segments


def test_angles_default_to_the_old_constants():
    a = Angles()
    assert a.rail_bend == RAIL_MAX_DEV
    assert a.end_edge == math.pi / 2.0 - RAIL_MAX_DEV    # the bridge's END_SHALLOW, to the last bit
    # the old cosines are written to 16 digits, so the round trip through acos is 1 ULP off
    assert abs(math.cos(a.step_agree) - STEP_AGREE_COS) < 1e-15
    assert abs(math.cos(a.step_differ) - STEP_DIFFER_COS) < 1e-15
    assert a.shoot == pytest.approx(math.radians(30))


def test_rail_bend_bounds_how_far_a_rail_path_turns():
    # strip2 with vertex 9 moved so the rail path at vertex 1 bends 20 degrees at vertex 5.
    band = strip2_bent(20.0)
    assert rail_path(band, 1, wedge(band, 1).rails[0])[-1][0] == 9    # 20 deg is within the default 30
    band.angles = Angles(rail_bend=math.radians(10))
    assert rail_path(band, 1, wedge(band, 1).rails[0])[-1][0] == 5    # 20 deg is past 10: the path ends at 5
