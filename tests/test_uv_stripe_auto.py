"""UV Stripe's layout choice (``utils/uv_stripe_auto_core``): where a strip is torn, what must be straight on each
piece and which layout keeps it with the least measured stretch."""
import math

import pytest

from utils import uv_stripe_auto_core as auto
from utils.uv_stripe_auto_core import (
    AUTO_ANGLE, DEFAULT_STRETCH_LIMIT, END_CHOICES, EVEN_CHOICE, SIDE_NAMES, STRAIGHT_LAYOUTS, STRAIGHT_SIDES, Shape,
    apply_choice, auto_cuts, best_straight, candidates, choose_layout, default_shape, laid_shape, lay_shaped,
    layout_stretch, measure, picked_shape, piece_sides, relax_steps,
)
from utils.uv_stripe_balance_core import start_end
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


def _trapezoid():
    """Two quads widening from 1 (the end at near[0]) to 2 (the end at near[-1]); the far rail is the longer."""
    return _ladder([(0, 0, 0), (1, 0, 0), (2, 0, 0)], [(0, 1, 0), (1, 1.5, 0), (2, 2, 0)])


def _pieces(strip, cuts):
    strip.layout = "TRUE"
    return slice_strip(strip, cuts) if cuts else [strip]


def _worst(piece, choice):
    return max(measure(piece, choice)[0])


def _pos(uv):
    return {vid: p for (_fid, vid), p in uv.items()}


def test_constants():
    assert AUTO_ANGLE == pytest.approx(math.radians(0.5))
    assert STRAIGHT_LAYOUTS == ("TRUE", "STRAIGHT", "EVEN")
    assert DEFAULT_STRETCH_LIMIT == 1.25
    assert STRAIGHT_SIDES == ("BOTH", "LONGER", "SHORTER", "NONE")
    assert END_CHOICES == ("AUTO", "SLANTED", "BOTH", "LONGER", "SHORTER")
    assert SIDE_NAMES == ("near", "far", "end0", "end1")
    assert Shape() == Shape(True, True, False, False) and Shape().rails == "BOTH"
    assert [Shape(n, f).rails for n, f in ((True, False), (False, True), (False, False))] == ["NEAR", "FAR", "NONE"]


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


def test_measure_lays_the_choice_out_on_a_copy():
    strip = _l_strip()
    strip.layout = "TRUE"
    for choice in (("TRUE", "BOTH", "FREE"), ("BALANCED", "NEAR", "END"), ("SHAPE", "BOTH", "FREE")):
        stretch, folds = measure(strip, choice)
        assert strip.layout == "TRUE" and folds == 0
        applied = strip_from_faces(strip.verts, strip.faces)
        uv = apply_choice(applied, choice)
        assert (applied.layout, applied.rails, applied.ends) == choice
        assert uv == stripe_uvs(applied)
        assert stretch == pytest.approx([
            face_stretch([applied.verts[v] for v in face], [uv[(fid, v)] for v in face])
            for fid, face in applied.faces.items()])


def test_the_balanced_solve_is_skipped_when_a_straight_row_layout_is_clean(monkeypatch):
    strip = _straight_strip()
    seen = []
    real = auto.measure

    def spy(piece, choice, balance=0.5, flats=None):
        seen.append(choice[0])
        return real(piece, choice, balance, flats)
    monkeypatch.setattr(auto, "measure", spy)
    assert choose_layout(strip, Shape()) == ("TRUE", "BOTH", "FREE")
    assert seen == ["TRUE"]                                    # free ends: the one cheap layout, no balanced solve
    seen.clear()
    choose_layout(_wedge_quad(3.0), Shape(), 3.0)              # tapered: the cheap one stretches, balanced is tried
    assert "BALANCED" in seen


def test_no_upright_end_layout_competes_under_slanted_even_when_it_would_stretch_less():
    angles = [math.radians(90.0) * i / 12 for i in range(13)]     # a flat arc: Rectangles beat the true lengths
    strip = _ladder([(math.cos(a), math.sin(a), 0.0) for a in angles], [(0.9 * math.cos(a), 0.9 * math.sin(a), 0.0)
                                                                       for a in angles])
    # by design (Slanted = the real slant) the straight-row layouts with upright ends are no candidates any more
    assert [c[0] for c in candidates(strip, Shape())] == ["TRUE", "BALANCED"]
    choice = choose_layout(strip, Shape())
    assert choice[0] in ("TRUE", "BALANCED") and choice[2] == "FREE"
    assert _worst(strip, choice) <= _worst(strip, ("TRUE", "BOTH", "FREE")) + 1e-9


def test_flat_straight_strip_gets_no_cut_and_one_straight_piece():
    strip = _straight_strip()
    assert bend_cut_rungs(strip, AUTO_ANGLE) == []
    assert auto_cuts(strip) == []
    choice = choose_layout(strip, default_shape(strip))
    assert choice == ("TRUE", "BOTH", "FREE")               # first on the tie with the balanced layout
    assert _worst(strip, choice) <= STRETCH_TOLERANCE


def test_sharp_corner_is_cut_once_and_both_pieces_are_clean():
    strip = _l_strip()
    corner = _corner_rung(strip)
    assert best_straight(strip)[1] and max(best_straight(strip)[1]) > STRETCH_TOLERANCE   # whole, it stretches
    assert auto_cuts(strip) == [corner]
    pieces = _pieces(strip, [corner])
    assert len(pieces) == 2
    for piece in pieces:
        assert _worst(piece, choose_layout(piece, Shape())) <= STRETCH_TOLERANCE


def test_strip_that_only_folds_gets_no_cut():
    strip = _cylinder_strip()
    assert auto_cuts(strip) == []
    assert _worst(strip, choose_layout(strip, Shape())) <= STRETCH_TOLERANCE


def test_gentle_arc_that_stays_clean_whole_gets_no_cut():
    strip = _arc_strip()
    assert bend_cut_rungs(strip, AUTO_ANGLE)            # every rung is a candidate
    layout, stretch = best_straight(strip)
    assert max(stretch) <= STRETCH_TOLERANCE           # the premise: whole, no face stretches
    assert auto_cuts(strip) == []


def test_tapered_quad_is_relaxed_beyond_the_limit_and_both_rails_within_it():
    strip = _wedge_quad(1.0)
    both = choose_layout(strip, Shape(), 3.0)
    assert both[1] == "BOTH" and 1.25 < _worst(strip, both) < 3.0       # the premise: tapered beyond the limit
    assert relax_steps(strip, Shape())[1] == Shape(False, True)          # the far rail is the longer
    relaxed = choose_layout(strip, Shape(), 1.25)
    assert relaxed == ("BALANCED", "FAR", "FREE")                        # the first step within the limit
    assert _worst(strip, relaxed) <= 1.25
    assert choose_layout(strip, Shape(), 1.25, relax=False) == both      # never relaxed when the rails are picked


def test_relaxing_ends_at_the_unfold_and_takes_the_least_stretched_when_nothing_is_within():
    strip = _wedge_quad(0.3)
    steps = relax_steps(strip, Shape())
    assert [s.rails for s in steps] == ["BOTH", "FAR", "NONE"]
    # at limit 1.0 the piece leaves both rails: one rail free or the unfold, whichever first stays at 1.0
    assert choose_layout(strip, Shape(), 1.0)[1] != "BOTH" or choose_layout(strip, Shape(), 1.0)[0] == "SHAPE"
    assert choose_layout(strip, Shape(), 1.25)[1] == "BOTH"
    assert relax_steps(strip, Shape(True, False)) == [Shape(True, False), Shape(False, False)]
    assert relax_steps(strip, Shape(False, False)) == [Shape(False, False)]


def test_relax_steps_keep_the_ends():
    strip = _wedge_quad(1.0)
    steps = relax_steps(strip, Shape(True, True, True, False))
    assert all((s.end0, s.end1) == (True, False) for s in steps)


def test_clean_piece_stays_straight_at_limit_one():
    strip = _straight_strip()
    assert choose_layout(strip, Shape(), 1.0) == ("TRUE", "BOTH", "FREE")


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
    assert choose_layout(strip, Shape()) == EVEN_CHOICE
    assert piece_sides(strip) == {}


# --- what must be straight ------------------------------------------------------------

def test_default_shape_reads_the_settings():
    strip = _trapezoid()
    assert default_shape(strip) == Shape(True, True, False, False)
    assert default_shape(strip, "NONE", "BOTH") == Shape(False, False, True, True)
    assert default_shape(strip, "LONGER").rails == "FAR"          # the far rail runs over the widening
    assert default_shape(strip, "SHORTER").rails == "NEAR"
    assert default_shape(strip, "BOTH", "LONGER") == Shape(True, True, False, True)    # the end 2 high
    assert default_shape(strip, "BOTH", "SHORTER") == Shape(True, True, True, False)
    with pytest.raises(ValueError):
        default_shape(strip, "PICKED")
    with pytest.raises(ValueError):
        default_shape(strip, "BOTH", "STRAIGHT")


def test_ties_take_the_near_rail_and_the_end_at_u_zero():
    strip = _straight_strip()
    assert default_shape(strip, "LONGER").rails == "NEAR"
    assert default_shape(strip, "SHORTER").rails == "NEAR"
    first = start_end(strip)
    for ends in ("LONGER", "SHORTER"):
        shape = default_shape(strip, "BOTH", ends)
        assert (shape.end0, shape.end1) == (first == 0, first == 1)


def test_candidates_keep_what_the_shape_asks():
    strip = _trapezoid()
    assert candidates(strip, Shape()) == [             # free ends keep their slant: no upright layout competes
        ("TRUE", "BOTH", "FREE"), ("BALANCED", "BOTH", "FREE")]
    assert candidates(strip, Shape(True, True, True, True)) == [
        ("STRAIGHT", "BOTH", "BOTH"), ("EVEN", "BOTH", "BOTH"), ("BALANCED", "BOTH", "BOTH")]
    first = start_end(strip)
    start, end = ("end0", "end1") if first == 0 else ("end1", "end0")
    assert candidates(strip, Shape(True, True, **{start: True})) == [("BALANCED", "BOTH", "START")]
    assert candidates(strip, Shape(True, True, **{end: True})) == [("BALANCED", "BOTH", "END")]
    assert candidates(strip, Shape(False, True, True, True)) == [("BALANCED", "FAR", "BOTH")]
    assert candidates(strip, Shape(True, False)) == [("BALANCED", "NEAR", "FREE")]
    assert candidates(strip, Shape(False, False, True, True)) == [("SHAPE", "BOTH", "FREE")]


def test_one_face_wide_ends_one_by_one_stand_their_cross_edge_upright():
    strip = _trapezoid()
    first = start_end(strip)
    ends = ([strip.near[0], strip.far[0]], [strip.near[-1], strip.far[-1]])
    for straight in (0, 1):
        shape = Shape(True, True, straight == 0, straight == 1)
        choice = choose_layout(strip, shape, relax=False)
        assert choice[0] == "BALANCED" and choice[2] == ("START" if straight == first else "END")
        uv = apply_choice(strip, choice)
        pos = _pos(uv)
        upright, slanted = ends[straight], ends[1 - straight]
        assert pos[upright[0]][0] == pytest.approx(pos[upright[1]][0], abs=1e-9)
        assert abs(pos[slanted[0]][0] - pos[slanted[1]][0]) > 1e-3
        assert laid_shape(strip) == shape
        assert abs(pos[strip.near[0]][1] - pos[strip.near[-1]][1]) < 1e-9     # both rails still straight
        assert abs(pos[strip.far[0]][1] - pos[strip.far[-1]][1]) < 1e-9


def test_laid_shape_reads_the_layout():
    strip = _trapezoid()
    for choice, shape in ((("TRUE", "BOTH", "FREE"), Shape()), (("EVEN", "BOTH", "BOTH"), Shape(True, True, True, True)),
                          (("STRAIGHT", "BOTH", "BOTH"), Shape(True, True, True, True)),
                          (("SHAPE", "BOTH", "FREE"), Shape(False, False)),
                          (("BALANCED", "NEAR", "BOTH"), Shape(True, False, True, True)),
                          (("BALANCED", "FAR", "FREE"), Shape(False, True))):
        apply_choice(strip, choice)
        assert laid_shape(strip) == shape, choice


def test_piece_sides_are_its_rails_and_ends_with_their_faces():
    strip = _ladder([(0, 0, 0), (1, 0, 0), (2, 0, 0)], [(0, 1, 0), (1, 1, 0), (2, 1, 0)])
    sides = piece_sides(strip)
    assert set(sides) == set(SIDE_NAMES)
    edges = {name: {e for e, _f in side} for name, side in sides.items()}
    assert {frozenset(edges["near"]), frozenset(edges["far"])} == {frozenset({(0, 1), (1, 2)}),
                                                                   frozenset({(3, 4), (4, 5)})}
    assert {frozenset(edges["end0"]), frozenset(edges["end1"])} == {frozenset({(0, 3)}), frozenset({(2, 5)})}
    for side in sides.values():
        for edge, fid in side:
            face = strip.faces[fid]
            assert any({a, b} == set(edge) for a, b in zip(face, face[1:] + face[:1]))


def test_picks_set_sides_of_their_own_piece_later_over_earlier():
    strip = _trapezoid()
    sides = piece_sides(strip)
    near_edge, near_face = sides["near"][0]
    end_edge, end_face = sides["end1"][0]
    shape, rails = picked_shape(strip, Shape(), [(near_face, near_edge, False)])
    assert shape == Shape(False, True) and rails
    shape, rails = picked_shape(strip, Shape(), [(end_face, end_edge, True)])
    assert shape == Shape(True, True, False, True) and not rails
    shape, _rails = picked_shape(strip, Shape(), [(near_face, near_edge, False), (near_face, near_edge, True)])
    assert shape == Shape()
    assert picked_shape(strip, Shape(), [(999, near_edge, False)]) == (Shape(), False)     # another piece's face
    assert picked_shape(strip, Shape(), [(near_face, (0, 4), False)]) == (Shape(), False)  # no side edge


def test_lay_shaped_puts_the_picks_on_the_settings_and_keeps_a_picked_rail():
    strip = _wedge_quad(3.0)
    sides = piece_sides(strip)
    edge, fid = sides["near"][0]
    assert lay_shaped(strip, "BOTH", "SLANTED", 1.05) == ("BALANCED", "FAR", "FREE")    # relaxed
    picks = [(fid, edge, True), (sides["far"][0][1], sides["far"][0][0], True)]
    choice = lay_shaped(strip, "BOTH", "SLANTED", 1.05, picks=picks)
    assert choice[1] == "BOTH" and strip.layout == choice[0]                           # picked: not relaxed
    assert laid_shape(strip).rails == "BOTH"


def test_a_layout_that_folds_loses_to_one_that_does_not(monkeypatch):
    strip = _straight_strip()
    real = auto.measure

    def folding(piece, choice, balance=0.5, flats=None):
        stretch, folds = real(piece, choice, balance, flats)
        return stretch, (1 if choice[0] in ("TRUE", "STRAIGHT", "EVEN") else folds)
    monkeypatch.setattr(auto, "measure", folding)
    assert choose_layout(strip, Shape()) == ("BALANCED", "BOTH", "FREE")


def test_when_every_candidate_folds_a_straight_row_layout_that_does_not_is_taken(monkeypatch):
    strip = _straight_strip()
    real = auto.measure

    def folding(piece, choice, balance=0.5, flats=None):
        stretch, folds = real(piece, choice, balance, flats)
        return stretch, (folds if choice[0] in ("STRAIGHT", "EVEN") else 2)
    monkeypatch.setattr(auto, "measure", folding)
    first = start_end(strip)
    one_end = Shape(True, True, first == 0, first == 1)                  # only balanced keeps it, and it folds
    assert candidates(strip, one_end) == [("BALANCED", "BOTH", "START")]
    assert choose_layout(strip, one_end) == ("STRAIGHT", "BOTH", "BOTH")
    # under free ends only "TRUE" is tried as the fallback (by design): it folds here too, so the unfold stays
    assert choose_layout(strip, Shape(False, False), relax=False) == ("SHAPE", "BOTH", "FREE")
    monkeypatch.setattr(auto, "measure", lambda piece, choice, balance=0.5, flats=None: (
        real(piece, choice, balance, flats)[0], 0 if choice[0] == "TRUE" else 2))
    assert choose_layout(strip, Shape(False, False), relax=False) == ("TRUE", "BOTH", "FREE")


def test_nothing_that_lays_out_falls_back_to_even_rows(monkeypatch):
    strip = _straight_strip()

    def refuse(*_args, **_kwargs):
        raise ValueError("no")
    monkeypatch.setattr(auto, "measure", refuse)
    assert choose_layout(strip, Shape()) == EVEN_CHOICE


def _frame(outer, inset=0.2, z=0.0):
    """A closed ring of quads inset from the polygon ``outer`` (counter-clockwise): outer vertex i, inner n + i."""
    n = len(outer)
    cx, cy = sum(p[0] for p in outer) / n, sum(p[1] for p in outer) / n
    verts = {}
    for i, (x, y) in enumerate(outer):
        verts[i] = (x, y, 0.0)
        verts[n + i] = (x + (inset if x < cx else -inset), y + (inset if y < cy else -inset), z)
    return strip_from_faces(verts, {i: (i, (i + 1) % n, n + (i + 1) % n, n + i) for i in range(n)})


@pytest.mark.parametrize("z", [0.0, 0.2])
def test_a_rectangular_frame_tears_at_all_four_corners(z):
    strip = _frame([(0, 0), (4, 0), (4, 1), (0, 1)], z=z)
    assert strip.closed
    cuts = auto_cuts(replace_layout(strip))
    assert cuts == [0, 1, 2, 3]                          # one corner alone cannot be torn, all four can
    pieces = slice_strip(replace_layout(strip), cuts)
    assert sorted(len(p.faces) for p in pieces) == [1, 1, 1, 1]
    for piece in pieces:
        assert _worst(piece, choose_layout(piece, Shape())) <= STRETCH_TOLERANCE


def test_a_frame_with_longer_sides_tears_symmetrically():
    outer = [(x, 0) for x in range(5)] + [(4 - x, 1) for x in range(5)]
    strip = _frame(outer)
    pieces = slice_strip(replace_layout(strip), auto_cuts(replace_layout(strip)))
    assert sorted(len(p.faces) for p in pieces) == [1, 1, 4, 4]


def replace_layout(strip):
    strip.layout = "TRUE"
    return strip
