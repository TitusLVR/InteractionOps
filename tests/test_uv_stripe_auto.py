"""UV Stripe's Auto layout (``utils/uv_stripe_auto_core``): where a strip is torn and how each piece is laid out,
from the measured stretch of the result."""
import math

import pytest

from utils.uv_stripe_auto_core import (
    AUTO_ANGLE, DEFAULT_STRETCH_LIMIT, STRAIGHT_LAYOUTS, auto_cuts, auto_layout, best_straight, layout_stretch,
)
from utils.uv_stripe_core import STRETCH_TOLERANCE, face_stretch, lay_piece, stripe_uvs
from utils.uv_stripe_select_core import bend_cut_rungs, rung_edge, rungs_at, slice_strip, strip_from_faces


def _ladder(near, far):
    """The open quad strip between two rows of points: near ids 0..n-1, far ids n..2n-1, faces wound
    counter-clockwise seen from +z (for rows running +x with far at +y)."""
    n = len(near)
    verts = {i: tuple(p) for i, p in enumerate(near)}
    verts.update({n + i: tuple(p) for i, p in enumerate(far)})
    faces = {i: (i, i + 1, n + i + 1, n + i) for i in range(n - 1)}
    return strip_from_faces(verts, faces)


def _straight_strip(count=6):
    return _ladder([(x, 0.0, 0.0) for x in range(count + 1)], [(x, 1.0, 0.0) for x in range(count + 1)])


def _l_strip():
    """A flat L of four quads with a mitred corner: its rung from (2, 1) to (3, 0) joins the corner of both rows."""
    outer = [(0, 0, 0), (1, 0, 0), (3, 0, 0), (3, 2, 0), (3, 3, 0)]
    inner = [(0, 1, 0), (1, 1, 0), (2, 1, 0), (2, 2, 0), (2, 3, 0)]
    return _ladder(outer, inner)


def _corner_rung(strip):
    return rungs_at(strip, [rung_edge(strip, k) for k in range(len(strip.rungs))
                            if {strip.verts[v] for v in rung_edge(strip, k)} == {(2, 1, 0), (3, 0, 0)}])[0]


def _cylinder_strip(count=6, radius=2.0):
    """An open strip wrapped half round a cylinder about z: it folds across its cross edges, never bends in its
    own surface."""
    ring = [(radius * math.cos(math.pi * i / count), radius * math.sin(math.pi * i / count)) for i in range(count + 1)]
    return _ladder([(x, y, 0.0) for x, y in ring], [(x, y, 1.0) for x, y in ring])


def _arc_strip(count=8, step=math.radians(1.0), inner=20.0, outer=21.0):
    """A flat strip bending gently in its own plane: an annulus sector of ``count`` faces, ``step`` each."""
    angles = [math.pi / 2 - step * i for i in range(count + 1)]
    near = [(outer * math.cos(a), outer * math.sin(a), 0.0) for a in angles]
    far = [(inner * math.cos(a), inner * math.sin(a), 0.0) for a in angles]
    return _ladder(near, far)


def _wedge_quad(rise):
    """One quad whose far row rises by ``rise`` over its length: its rows are not parallel."""
    return _ladder([(0.0, 0.0, 0.0), (2.0, 0.0, 0.0)], [(0.0, 1.0, 0.0), (2.0, 1.0 + rise, 0.0)])


def _pieces(strip, cuts):
    strip.layout = "TRUE"
    return slice_strip(strip, cuts) if cuts else [strip]


def _worst(piece, layout):
    return max(layout_stretch(piece, layout))


def test_constants():
    assert AUTO_ANGLE == pytest.approx(math.radians(0.5))
    assert STRAIGHT_LAYOUTS == ("TRUE", "STRAIGHT", "EVEN")
    assert DEFAULT_STRETCH_LIMIT == 1.25


def test_layout_stretch_measures_the_applied_layout_and_leaves_the_piece():
    strip = _l_strip()
    strip.layout = "TRUE"
    for layout in ("TRUE", "STRAIGHT", "EVEN", "SHAPE"):
        measured = layout_stretch(strip, layout)
        assert strip.layout == "TRUE"
        applied = strip_from_faces(strip.verts, strip.faces)
        uv = lay_piece(applied, layout)
        assert uv == stripe_uvs(applied)                # the piece keeps the layout it was laid out by
        assert measured == pytest.approx([
            face_stretch([applied.verts[v] for v in face], [uv[(fid, v)] for v in face])
            for fid, face in applied.faces.items()])


def test_flat_straight_strip_gets_no_cut_and_one_straight_piece():
    strip = _straight_strip()
    assert bend_cut_rungs(strip, AUTO_ANGLE) == []
    assert auto_cuts(strip) == []
    assert auto_layout(strip, DEFAULT_STRETCH_LIMIT) in STRAIGHT_LAYOUTS
    assert _worst(strip, auto_layout(strip, DEFAULT_STRETCH_LIMIT)) <= STRETCH_TOLERANCE


def test_sharp_corner_is_cut_once_and_both_pieces_are_clean():
    strip = _l_strip()
    corner = _corner_rung(strip)
    assert best_straight(strip)[1] and max(best_straight(strip)[1]) > STRETCH_TOLERANCE   # whole, it stretches
    assert auto_cuts(strip) == [corner]
    pieces = _pieces(strip, [corner])
    assert len(pieces) == 2
    for piece in pieces:
        assert _worst(piece, auto_layout(piece, DEFAULT_STRETCH_LIMIT)) <= STRETCH_TOLERANCE


def test_strip_that_only_folds_gets_no_cut():
    strip = _cylinder_strip()
    assert auto_cuts(strip) == []
    assert _worst(strip, auto_layout(strip, DEFAULT_STRETCH_LIMIT)) <= STRETCH_TOLERANCE


def test_gentle_arc_that_stays_clean_whole_gets_no_cut():
    strip = _arc_strip()
    assert bend_cut_rungs(strip, AUTO_ANGLE)            # every rung is a candidate
    layout, stretch = best_straight(strip)
    assert max(stretch) <= STRETCH_TOLERANCE           # the premise: whole, no face stretches
    assert auto_cuts(strip) == []


def test_tapered_quad_is_true_shape_beyond_the_limit_and_straight_within_it():
    strip = _wedge_quad(3.0)
    straight = max(best_straight(strip)[1])
    assert 1.25 < straight < 3.0                       # the premise: tapered beyond 1.25, within 3.0
    assert _worst(strip, "SHAPE") < straight
    assert auto_layout(strip, 1.0) == "SHAPE"
    assert auto_layout(strip, 1.25) == "SHAPE"
    assert auto_layout(strip, 3.0) in STRAIGHT_LAYOUTS


def test_clean_piece_stays_straight_at_limit_one():
    strip = _straight_strip()
    assert auto_layout(strip, 1.0) in STRAIGHT_LAYOUTS


def test_forced_cut_is_made_and_never_returned():
    strip = _l_strip()
    corner = _corner_rung(strip)
    first = 0 if corner != 0 else len(strip.rungs) - 1
    assert auto_cuts(strip, forced_cuts=[first]) == [corner]
    assert auto_cuts(strip, forced_cuts=[corner]) == []


def test_forced_cut_on_a_gentle_arc_leaves_no_bend_cut():
    strip = _arc_strip()
    assert auto_cuts(strip, forced_cuts=[3]) == []


def test_skipped_candidate_is_not_cut():
    strip = _l_strip()
    assert auto_cuts(strip, skip_cuts=[_corner_rung(strip)]) == []


def test_closed_piece_keeps_even_rows():
    strip = _straight_strip()
    strip.closed = True
    assert auto_layout(strip, DEFAULT_STRETCH_LIMIT) == "EVEN"
