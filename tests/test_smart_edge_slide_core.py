import math
import random

import pytest

from utils.smart_edge_slide_core import (
    Band,
    OutOfRoom,
    Slider,
    SurfacePoint,
    nearest_chain,
    positive_side,
    trace_from_vertex,
    trace_segment,
    wedge,
)


def _band(pts, faces, chain, side_faces, closed=False):
    verts = {i: (float(p[0]), float(p[1]), float(p[2])) for i, p in enumerate(pts)}
    return Band(verts=verts, faces=faces, chain=chain, closed=closed, side_faces=side_faces)


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
    return _band(pts, faces, [0, 1, 2, 3], [0, 1, 2])


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


def ring():
    pts = [(-1, -1, 0), (1, -1, 0), (1, 1, 0), (-1, 1, 0), (-2, -2, 0), (2, -2, 0), (2, 2, 0), (-2, 2, 0)]
    faces = {0: (0, 1, 5, 4), 1: (1, 2, 6, 5), 2: (2, 3, 7, 6), 3: (3, 0, 4, 7)}
    return _band(pts, faces, [0, 1, 2, 3], [0, 1, 2, 3], closed=True)


def end_slide():
    pts = [(0, 0, 0), (2, 0, 0), (2, 0.1, 0), (1, 1, 0), (0, 1, 0)]
    return _band(pts, {0: (0, 1, 2, 3, 4)}, [0, 1], [0])


def u_turn():
    a, b = 2.1414214, 0.1414214
    pts = [(0, 0, 0), (2, 0, 0), (a, b, 0), (a, 1 + b, 0), (0, 1 + b, 0)]
    return _band(pts, {0: (0, 1, 2, 3, 4)}, [0, 1, 2, 3], [0, 0, 0])


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


def chamfer_ring():
    # A square with chamfered corners, the band inside; segments 1, 3, 5 and the closing 7 are chamfers.
    h, c = 2.0, 0.2
    pts = [(-h + c, -h, 0), (h - c, -h, 0), (h, -h + c, 0), (h, h - c, 0),
           (h - c, h, 0), (-h + c, h, 0), (-h, h - c, 0), (-h, -h + c, 0)]
    return _band(pts, {0: tuple(range(8))}, list(range(8)), [0] * 8, closed=True)


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
