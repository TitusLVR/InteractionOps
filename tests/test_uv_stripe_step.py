"""Rails with a step (a jog across the rail, the strip narrowing or widening there): the end-cap choice keeps the
step in its rail, and every layout keeps every face unfolded."""
import math

import pytest

from test_uv_stripe_weld import face_quality, signed_area
from uv_stripe_fixtures import STEP_FACES, STEP_VERTS
from utils.uv_stripe_core import stripe_uvs
from utils.uv_stripe_select_core import split_strip, strip_from_faces

LAYOUTS = ["TRUE", "STRAIGHT", "EVEN", "SHAPE"]


def unfolded(strip, uv, least=1e-9):
    return all(signed_area([uv[(fid, v)] for v in face]) > least for fid, face in strip.faces.items())


# --- the user's strip ---------------------------------------------------------------------

def test_the_stepped_end_face_keeps_the_step_in_its_rail():
    strip = strip_from_faces(STEP_VERTS, STEP_FACES)
    rows = {tuple(strip.near), tuple(strip.far)}
    assert rows == {(24, 12, 13, 2), (25, 18, 19, 22, 21, 5)}
    assert strip.sides == ([], []) and strip.rungs == [(1, 1), (2, 2)]
    assert {strip.near[-1], strip.far[-1]} == {2, 5}                # the real end cap, 5-2


def test_the_stepped_face_alone_as_a_piece_and_as_a_selection():
    strip = strip_from_faces(STEP_VERTS, STEP_FACES)
    pieces, reason = split_strip(strip, math.radians(5))
    assert reason is None and [sorted(p.faces) for p in pieces] == [[0], [1], [20]]
    piece = pieces[2]
    assert {tuple(piece.near), tuple(piece.far)} == {(13, 2), (19, 22, 21, 5)}
    alone = strip_from_faces(STEP_VERTS, {20: STEP_FACES[20]})
    rows = {tuple(alone.near), tuple(alone.far)}
    assert rows in ({(13, 2), (19, 22, 21, 5)}, {(2, 13), (5, 21, 22, 19)}), rows
    assert alone.sides == ([], [])


@pytest.mark.parametrize("layout", LAYOUTS)
def test_no_face_folds_in_any_layout(layout):
    strip = strip_from_faces(STEP_VERTS, STEP_FACES)
    strip.layout = layout
    assert unfolded(strip, stripe_uvs(strip))
    pieces, _reason = split_strip(strip, math.radians(5))
    for piece in pieces:
        piece.layout = layout
        assert unfolded(piece, stripe_uvs(piece))
    alone = strip_from_faces(STEP_VERTS, {20: STEP_FACES[20]})
    alone.layout = layout
    assert unfolded(alone, stripe_uvs(alone))


def test_true_shape_keeps_the_stepped_face():
    for strip in (strip_from_faces(STEP_VERTS, {20: STEP_FACES[20]}),
                  split_strip(strip_from_faces(STEP_VERTS, STEP_FACES), math.radians(5))[0][2]):
        strip.layout = "SHAPE"
        uv = stripe_uvs(strip)
        ratios, errors = face_quality(strip, uv, 20, tol=1e-4)
        assert all(abs(r - 1.0) < 2e-3 for r in ratios), ratios          # coordinates rounded to 1e-5
        assert max(errors) < 0.1, errors


def test_no_stretch_keeps_the_far_row_straight_through_the_step():
    piece = split_strip(strip_from_faces(STEP_VERTS, STEP_FACES), math.radians(5))[0][2]
    piece.layout = "TRUE"
    uv = stripe_uvs(piece)
    stepped = piece.far if 22 in piece.far else piece.near
    at = {vid: co for (_f, vid), co in uv.items()}
    vs = {round(at[v][1], 9) for v in stepped}
    assert len(vs) == 1                                               # the stepped row is one straight line
    us = [at[v][0] for v in stepped]
    assert us == sorted(us) or us == sorted(us, reverse=True)         # 19, 22, 21, 5 in order along it
    assert abs(at[22][0] - at[21][0]) == pytest.approx(math.dist(STEP_VERTS[22], STEP_VERTS[21]), rel=0.05)


# --- synthetic steps --------------------------------------------------------------------------

def stepped_chain(cells=3, far_steps=(), near_steps=(), double_at=None, length=1.0):
    """``cells`` faces ``length`` long along x, near rail at y = 0, far rail at y = 1 (x in cell units, scaled by
    ``length`` at the end). A far step at x = t (not an integer)
    drops the far rail by 0.2 from there on; a near step raises the near rail by 0.1. ``double_at`` (x, row)
    adds a vertex 1e-5 along the rail from that row's point at x."""
    def far_y(x):
        return 1.0 - 0.2 * sum(x >= t for t in far_steps)

    def near_y(x):
        return 0.1 * sum(x >= t for t in near_steps)

    ids, verts = {}, {}

    def vid(p):
        if p not in ids:
            ids[p] = len(ids)
            verts[ids[p]] = (p[0], p[1], 0.0)
        return ids[p]

    faces = {}
    for i in range(cells):
        x0, x1 = float(i), float(i + 1)
        near = [(x0, near_y(x0))]
        for t in sorted(near_steps):
            if x0 < t < x1:
                near += [(t, near_y(t - 1e-9)), (t, near_y(t))]
        near.append((x1, near_y(x1 - 1e-9) if any(t == x1 for t in near_steps) else near_y(x1)))
        far = [(x0, far_y(x0))]
        for t in sorted(far_steps):
            if x0 < t < x1:
                far += [(t, far_y(t - 1e-9)), (t, far_y(t))]
        far.append((x1, far_y(x1)))
        ring = [vid(p) for p in near] + [vid(p) for p in reversed(far)]
        if double_at is not None and x0 < double_at[0] < x1:
            x, row = double_at
            point = (x, near_y(x)) if row == "near" else (x, far_y(x))
            k = ring.index(ids[point])
            ids[("double",)] = len(verts)
            verts[len(verts)] = (point[0] + 1e-5, point[1], 0.0)
            ring.insert(k + 1 if row == "near" else k, ids[("double",)])
        faces[i] = tuple(ring)
    return {v: (x * length, y, z) for v, (x, y, z) in verts.items()}, faces


CASES = {
    "middle face, far step": {"far_steps": (1.5,)},
    "middle face, steps on both rails": {"far_steps": (1.5,), "near_steps": (1.3,)},
    "a step on each end face": {"far_steps": (0.5, 2.5)},
    "a single stepped face": {"cells": 1, "far_steps": (0.5,), "length": 4.0},   # a strip, not a square
    "a step and a double": {"far_steps": (1.5,), "double_at": (1.5, "far")},
}


@pytest.mark.parametrize("case", list(CASES))
@pytest.mark.parametrize("layout", LAYOUTS)
def test_synthetic_steps_never_fold(case, layout):
    verts, faces = stepped_chain(**CASES[case])
    strip = strip_from_faces(verts, faces)
    assert not strip.sides[0] and not strip.sides[1], strip.sides       # no step taken for an end cap
    strip.layout = layout
    uv = stripe_uvs(strip)
    assert unfolded(strip, uv, least=1e-6), case


@pytest.mark.parametrize("case", ["middle face, far step", "a step on each end face", "a single stepped face",
                                  "a step and a double"])
def test_true_shape_is_exact_with_steps_in_one_rail(case):
    verts, faces = stepped_chain(**CASES[case])
    strip = strip_from_faces(verts, faces)
    strip.layout = "SHAPE"
    uv = stripe_uvs(strip)
    for fid in faces:
        ratios, errors = face_quality(strip, uv, fid, tol=1e-3)
        assert all(abs(r - 1.0) < 1e-6 for r in ratios) and max(errors) < 1e-4, (case, fid, ratios, errors)
