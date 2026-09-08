import math
import pytest

from utils.uv_stitch_core import stitch_transform, apply_similarity


# Source: unit quad [0,1]x[0,1] with edge on its right side (1,0)->(1,1).
SRC_A, SRC_B = (1.0, 0.0), (1.0, 1.0)
SRC_C = (0.5, 0.5)
SRC_QUAD = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]

# Target: quad [2,4]x[0,2] with edge on its left side (2,0)->(2,2),
# twice the source edge length.
DST_A, DST_B = (2.0, 0.0), (2.0, 2.0)
DST_C = (3.0, 1.0)


def _close(p, q, tol=1e-6):
    return abs(p[0] - q[0]) < tol and abs(p[1] - q[1]) < tol


def _apply_all(pts, xf):
    return [apply_similarity(p, xf) for p in pts]


def test_endpoints_coincide_after_stitch():
    xf = stitch_transform(SRC_A, SRC_B, DST_A, DST_B, SRC_C, DST_C)
    a, b = apply_similarity(SRC_A, xf), apply_similarity(SRC_B, xf)
    assert (_close(a, DST_A) and _close(b, DST_B)) or \
           (_close(a, DST_B) and _close(b, DST_A))


def test_uniform_scale_matches_edge_length():
    xf = stitch_transform(SRC_A, SRC_B, DST_A, DST_B, SRC_C, DST_C)
    q = _apply_all(SRC_QUAD, xf)
    # Opposite (free) edge of the source quad must also be length 2.
    d = math.dist(q[0], q[3])
    assert abs(d - 2.0) < 1e-6
    # Right angles preserved: it is still a square.
    assert abs(math.dist(q[0], q[1]) - 2.0) < 1e-6


def test_source_lands_on_free_side_of_target():
    xf = stitch_transform(SRC_A, SRC_B, DST_A, DST_B, SRC_C, DST_C)
    c = apply_similarity(SRC_C, xf)
    # Target interior is at x > 2, so the source must land at x < 2.
    assert c[0] < 2.0 - 1e-6


def test_same_side_flag_overlaps_target():
    xf = stitch_transform(SRC_A, SRC_B, DST_A, DST_B, SRC_C, DST_C,
                          same_side=True)
    c = apply_similarity(SRC_C, xf)
    assert c[0] > 2.0 + 1e-6
    a, b = apply_similarity(SRC_A, xf), apply_similarity(SRC_B, xf)
    assert (_close(a, DST_A) and _close(b, DST_B)) or \
           (_close(a, DST_B) and _close(b, DST_A))


def test_rotated_target_edge():
    # Target edge at 45 degrees, target interior above-left of it.
    da, db = (0.0, 0.0), (1.0, 1.0)
    dc = (0.0, 1.0)
    xf = stitch_transform(SRC_A, SRC_B, da, db, SRC_C, dc)
    a, b = apply_similarity(SRC_A, xf), apply_similarity(SRC_B, xf)
    assert (_close(a, da) and _close(b, db)) or \
           (_close(a, db) and _close(b, da))
    c = apply_similarity(SRC_C, xf)
    # Free side of the line y = x is below-right: y < x.
    assert c[1] < c[0] - 1e-6


def test_degenerate_source_edge_returns_none():
    assert stitch_transform((0, 0), (0, 0), DST_A, DST_B, SRC_C, DST_C) is None


def test_degenerate_target_edge_returns_none():
    assert stitch_transform(SRC_A, SRC_B, (0, 0), (0, 0), SRC_C, DST_C) is None


def test_target_centroid_on_edge_line_falls_back_to_direct_pairing():
    # Target centroid lies exactly on the edge line: no side info.
    xf = stitch_transform(SRC_A, SRC_B, DST_A, DST_B, SRC_C, (2.0, 1.0))
    assert _close(apply_similarity(SRC_A, xf), DST_A)
    assert _close(apply_similarity(SRC_B, xf), DST_B)


def test_identity_when_edges_already_match():
    xf = stitch_transform(SRC_A, SRC_B, SRC_A, SRC_B, SRC_C, (1.5, 0.5))
    for p in SRC_QUAD:
        assert _close(apply_similarity(p, xf), p)
