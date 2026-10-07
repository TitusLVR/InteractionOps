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


def test_keep_scale_preserves_edge_length():
    xf = stitch_transform(SRC_A, SRC_B, DST_A, DST_B, SRC_C, DST_C,
                          keep_scale=True)
    assert abs(xf['scale'] - 1.0) < 1e-9
    q = _apply_all(SRC_QUAD, xf)
    assert abs(math.dist(q[0], q[1]) - 1.0) < 1e-6


def test_keep_scale_centers_edge_on_target_midpoint():
    xf = stitch_transform(SRC_A, SRC_B, DST_A, DST_B, SRC_C, DST_C,
                          keep_scale=True)
    a, b = apply_similarity(SRC_A, xf), apply_similarity(SRC_B, xf)
    mid = ((a[0] + b[0]) * 0.5, (a[1] + b[1]) * 0.5)
    assert _close(mid, (2.0, 1.0))
    # Still collinear with the target edge (x == 2) and on its free side.
    assert abs(a[0] - 2.0) < 1e-6 and abs(b[0] - 2.0) < 1e-6
    assert apply_similarity(SRC_C, xf)[0] < 2.0 - 1e-6


def test_keep_scale_same_side_flag():
    xf = stitch_transform(SRC_A, SRC_B, DST_A, DST_B, SRC_C, DST_C,
                          keep_scale=True, same_side=True)
    assert apply_similarity(SRC_C, xf)[0] > 2.0 + 1e-6


def test_align_rotation_matches_direction():
    from utils.uv_stitch_core import align_rotation
    # Source edge along +x, target along +y: rotate by +90 degrees.
    assert abs(align_rotation((0, 0), (1, 0), (0, 0), (0, 1)) - math.pi / 2) < 1e-9


def test_align_rotation_takes_the_shorter_of_the_two_parallels():
    from utils.uv_stitch_core import align_rotation
    # Target along -x is parallel to +x: no rotation, not 180 degrees.
    assert abs(align_rotation((0, 0), (1, 0), (0, 0), (-1, 0))) < 1e-9
    # 100 degrees away -> the other parallel is 80 degrees away.
    a = math.radians(100)
    r = align_rotation((0, 0), (1, 0), (0, 0), (math.cos(a), math.sin(a)))
    assert abs(r + math.radians(80)) < 1e-9


def test_align_rotation_flip_adds_half_turn():
    from utils.uv_stitch_core import align_rotation
    r = align_rotation((0, 0), (1, 0), (0, 0), (0, 1), flip=True)
    assert abs(abs(r) - math.pi / 2) < 1e-9 and r < 0


def test_align_rotation_degenerate_returns_none():
    from utils.uv_stitch_core import align_rotation
    assert align_rotation((0, 0), (0, 0), (0, 0), (0, 1)) is None
    assert align_rotation((0, 0), (1, 0), (2, 2), (2, 2)) is None


def test_reflect_point_across_line():
    from utils.uv_stitch_core import reflect_point
    # Reflect across the x axis.
    assert _close(reflect_point((1.0, 2.0), (0.0, 0.0), (5.0, 0.0)), (1.0, -2.0))
    # Point on the line stays put.
    assert _close(reflect_point((3.0, 0.0), (0.0, 0.0), (5.0, 0.0)), (3.0, 0.0))
    # Diagonal line y = x swaps coordinates.
    assert _close(reflect_point((1.0, 0.0), (0.0, 0.0), (1.0, 1.0)), (0.0, 1.0))


def test_reflect_point_degenerate_line_is_identity():
    from utils.uv_stitch_core import reflect_point
    assert _close(reflect_point((1.0, 2.0), (3.0, 3.0), (3.0, 3.0)), (1.0, 2.0))


def test_signed_area_sign_follows_winding():
    from utils.uv_stitch_core import signed_area
    ccw = [(0, 0), (1, 0), (1, 1), (0, 1)]
    assert signed_area(ccw) > 0
    assert signed_area(list(reversed(ccw))) < 0
    assert signed_area([(0, 0), (1, 1)]) == 0.0


def test_src_length_override_scales_by_path_length():
    # A bent chain: end-to-end 1.0, path length 2.0, fitted into the
    # target edge of length 2.0 -> scale 1 (not 2), start lands on the
    # target and the end-to-end span covers half of it.
    xf = stitch_transform(SRC_A, SRC_B, DST_A, DST_B, SRC_C, DST_C,
                          src_length=2.0)
    assert abs(xf['scale'] - 1.0) < 1e-9
    a, b = apply_similarity(SRC_A, xf), apply_similarity(SRC_B, xf)
    assert _close(a, DST_A) or _close(a, DST_B)
    assert abs(math.dist(a, b) - 1.0) < 1e-9
