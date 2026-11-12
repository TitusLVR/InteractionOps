"""Unmerged doubles (points closer than the weld tolerance count as one) and the local "TRUE" layout, which
resynchronises its rows at every post so an error stays in its own span."""
import math

import pytest

from test_uv_stripe_select_core import polyline_strip
from uv_stripe_fixtures import DOUBLE_FACES, DOUBLE_VERTS
from utils.uv_stripe_core import stripe_uvs, welded_neighbour
from utils.uv_stripe_select_core import (
    bend_cut_rungs, doubled_vertices, island_tolerance, rung_edge, split_strip, strip_from_faces,
)


def _angle(a, b, c):
    u = [a[i] - b[i] for i in range(len(a))]
    w = [c[i] - b[i] for i in range(len(c))]
    cos = sum(x * y for x, y in zip(u, w)) / (math.hypot(*u) * math.hypot(*w))
    return math.acos(max(-1.0, min(1.0, cos)))


def face_quality(strip, uv, fid, tol=1e-3):
    """(UV length / 3D length of the face's edges longer than ``tol``, |UV - 3D| corner angles in degrees at its
    points, doubles taken as one point)."""
    ring = list(strip.faces[fid])
    ratios, errors = [], []
    for k, a in enumerate(ring):
        b = ring[(k + 1) % len(ring)]
        d3 = math.dist(strip.verts[a], strip.verts[b])
        if d3 > tol:
            ratios.append(math.dist(uv[(fid, a)], uv[(fid, b)]) / d3)
        if math.dist(strip.verts[ring[k - 1]], strip.verts[a]) <= tol:
            continue                                         # the second of a double: its point is counted once
        i = welded_neighbour(strip.verts, ring, k, -1, tol)
        j = welded_neighbour(strip.verts, ring, k, 1, tol)
        a3 = _angle(strip.verts[ring[i]], strip.verts[a], strip.verts[ring[j]])
        a2 = _angle(uv[(fid, ring[i])], uv[(fid, a)], uv[(fid, ring[j])])
        errors.append(abs(math.degrees(a3 - a2)))
    return ratios, errors


def signed_area(pts):
    return 0.5 * sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(pts, pts[1:] + pts[:1]))


# --- the strip with a double ----------------------------------------------------------

def test_the_double_is_found():
    tol = island_tolerance(DOUBLE_VERTS, DOUBLE_FACES)
    assert doubled_vertices(DOUBLE_VERTS, DOUBLE_FACES, tol) == {28: 21}


def test_both_bends_are_cut_through_the_double():
    strip = strip_from_faces(DOUBLE_VERTS, DOUBLE_FACES)
    assert strip.rungs == [(1, 1), (2, 2), (3, 4), (5, 5)]
    assert sorted(rung_edge(strip, k) for k in bend_cut_rungs(strip, math.radians(15))) == [(24, 92), (28, 89)]
    strip.layout = "TRUE"
    pieces, reason = split_strip(strip, math.radians(15))
    assert reason is None and [sorted(p.faces) for p in pieces] == [[67, 144], [65], [64, 77]]


def test_the_double_strip_pieces_keep_their_rows_and_corners():
    # The rails keep their length to the coordinates' rounding (3e-4). Across the strip the real width varies
    # (0.195 to 0.206 inside the first piece), which one straight far row at one height cannot follow: cross
    # edges stay within that variation (4 %) and corner angles within 0.7 degree. The rectangle 65 stays one.
    strip = strip_from_faces(DOUBLE_VERTS, DOUBLE_FACES)
    strip.layout = "TRUE"
    pieces, _reason = split_strip(strip, math.radians(15))
    for piece in pieces:
        uv = stripe_uvs(piece)
        rows = {frozenset(e) for row in (piece.near, piece.far) for e in zip(row, row[1:])}
        for fid, face in piece.faces.items():
            ratios, errors = face_quality(piece, uv, fid)
            assert all(abs(r - 1.0) < 0.045 for r in ratios), (fid, ratios)
            assert max(errors) < 0.7, (fid, errors)
            assert signed_area([uv[(fid, v)] for v in face]) > 0
            for k, a in enumerate(face):
                b = face[(k + 1) % len(face)]
                d3 = math.dist(piece.verts[a], piece.verts[b])
                if frozenset((a, b)) in rows and d3 > 1e-3:
                    assert abs(math.dist(uv[(fid, a)], uv[(fid, b)]) / d3 - 1.0) < 1e-3, (fid, a, b)
    (rect,) = [p for p in pieces if 65 in p.faces]
    uv = stripe_uvs(rect)
    ring = [28, 89, 92, 24]                                  # face 65 without the double's second vertex
    for k in range(4):
        corner = _angle(uv[(65, ring[k - 1])], uv[(65, ring[k])], uv[(65, ring[(k + 1) % 4])])
        assert abs(math.degrees(corner) - 90.0) < 0.2, (ring[k], math.degrees(corner))
    assert uv[(65, 21)] == pytest.approx(uv[(65, 28)], abs=1e-3)


# --- synthetic exact shapes -------------------------------------------------------------

def chain(n=3, double=None):
    """n unit quads along x, near row y = 0 (ids 0..n), far row y = 1 (ids 10..10+n). ``double``: add vertex 99
    that far from 12 along the far rail, inside face 2."""
    verts = {i: (float(i), 0.0, 0.0) for i in range(n + 1)} | {10 + i: (float(i), 1.0, 0.0) for i in range(n + 1)}
    faces = {i: (i, i + 1, 11 + i, 10 + i) for i in range(n)}
    if double is not None:
        verts[99] = (2.0 + double, 1.0, 0.0)
        faces[2] = (2, 3, 13, 99, 12)
    return verts, faces


@pytest.mark.parametrize("gap", [0.0, 1e-4])
@pytest.mark.parametrize("layout", ["TRUE", "STRAIGHT", "EVEN"])
def test_a_doubled_rail_vertex_lays_out_as_without_it(gap, layout):
    clean_verts, clean_faces = chain()
    clean = strip_from_faces(clean_verts, clean_faces)
    clean.layout = layout
    ref = stripe_uvs(clean)
    verts, faces = chain(double=gap)
    strip = strip_from_faces(verts, faces)
    strip.layout = layout
    uv = stripe_uvs(strip)
    for (fid, v), co in uv.items():
        target = ref[(fid, 12 if v == 99 else v)]
        assert co == pytest.approx(target, abs=2e-4), (layout, fid, v, co, target)
    for fid, face in faces.items():
        assert signed_area([uv[(fid, v)] for v in face]) > -1e-12


def test_a_bend_below_the_angle_stays_in_the_faces_touching_it():
    verts, quads = polyline_strip([0, 0, 8, 0, 0])            # an 8 degree turn at joint 3 (vertices 6, 7)
    faces = dict(enumerate(quads))
    strip = strip_from_faces(verts, faces)
    strip.layout = "TRUE"
    pieces, reason = split_strip(strip, math.radians(15))
    assert reason is None and pieces == [strip]               # not torn
    uv = stripe_uvs(strip)
    for fid, face in faces.items():
        ratios, errors = face_quality(strip, uv, fid)
        touching = 6 in face or 7 in face
        exact = all(abs(r - 1.0) < 1e-9 for r in ratios) and max(errors) < 1e-6
        assert exact != touching, (fid, ratios, errors)


def test_a_bent_ngon_does_not_distort_its_neighbours():
    verts, quads = polyline_strip([0, 8, 0])                  # joints 1..3; 8 degrees at joint 2
    q0, q1, q2, q3 = quads
    hexagon = (3, 5, 7, 6, 4, 2)                               # quads 1 and 2 as one face round the bend
    assert set(hexagon) == set(q1) | set(q2)
    faces = {0: q0, 1: hexagon, 3: q3}
    strip = strip_from_faces(verts, faces)
    strip.layout = "TRUE"
    uv = stripe_uvs(strip)
    for fid in (0, 3):
        ratios, errors = face_quality(strip, uv, fid)
        assert all(abs(r - 1.0) < 1e-9 for r in ratios) and max(errors) < 1e-6, (fid, ratios, errors)
    ratios, _errors = face_quality(strip, uv, 1)
    assert max(abs(r - 1.0) for r in ratios) > 1e-4                     # the bend is absorbed inside the n-gon

