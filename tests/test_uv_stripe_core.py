import pytest

from utils.uv_stripe_core import (
    Strip,
    ascending_rungs,
    place_fit,
    place_in_place,
    sharpest_rung,
    strip_length,
    stripe_uvs,
)


def signed_areas(strip, uv):
    """Each face's signed UV area, its corners taken in the face's own vertex order."""
    out = {}
    for fid, face in strip.faces.items():
        pts = [uv[(fid, vid)] for vid in face]
        out[fid] = 0.5 * sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(pts, pts[1:] + pts[:1]))
    return out


def quad_strip():      # near 0..3 on y=0, far 4..7 on y=0.25, unit columns
    v = {i: (float(i), 0.0, 0.0) for i in range(4)} | {4 + i: (float(i), 0.25, 0.0) for i in range(4)}
    f = {0: (0, 1, 5, 4), 1: (1, 2, 6, 5), 2: (2, 3, 7, 6)}
    return Strip(verts=v, faces=f, near=[0, 1, 2, 3], far=[4, 5, 6, 7],
                 rungs=[(i, i) for i in range(4)], closed=False, height=0.25)


def square_ring():     # 2x2 outer square, 0.2 inset walls
    o = [(0, 0), (2, 0), (2, 2), (0, 2)]
    i_ = [(0.2, 0.2), (1.8, 0.2), (1.8, 1.8), (0.2, 1.8)]
    v = {k: (float(x), float(y), 0.0) for k, (x, y) in enumerate(o + i_)}
    f = {0: (0, 1, 5, 4), 1: (1, 2, 6, 5), 2: (2, 3, 7, 6), 3: (3, 0, 4, 7)}
    return Strip(verts=v, faces=f, near=[0, 1, 2, 3], far=[4, 5, 6, 7],
                 rungs=[(k, k) for k in range(4)], closed=True, height=0.2)


def test_quad_strip_maps_to_itself():
    uv = stripe_uvs(quad_strip())
    assert uv[(0, 0)] == pytest.approx((0.0, 0.0)) and uv[(2, 7)] == pytest.approx((3.0, 0.25))
    assert strip_length(quad_strip()) == pytest.approx(3.0)


def test_open_strip_without_a_rung_at_its_first_vertex():
    # the first chain vertex has no anchor (a lid span at the chain start): both rows still run from
    # their first vertex, which no rung pins any more
    s = quad_strip()
    s.rungs = [(1, 1), (2, 2), (3, 3)]
    uv = stripe_uvs(s)
    assert strip_length(s) == pytest.approx(3.0)
    assert uv[(0, 0)] == pytest.approx((0.0, 0.0)) and uv[(0, 4)] == pytest.approx((0.0, 0.25))
    assert uv[(0, 1)] == pytest.approx((1.0, 0.0)) and uv[(2, 7)] == pytest.approx((3.0, 0.25))


def test_ring_unrolls_with_seam_at_first_corner():
    s = square_ring()
    assert sharpest_rung(s) == 0 and strip_length(s) == pytest.approx(7.2)
    uv = stripe_uvs(s)
    assert uv[(0, 0)] == pytest.approx((0.0, 0.0)) and uv[(0, 5)] == pytest.approx((1.8, 0.2))
    assert uv[(3, 0)] == pytest.approx((7.2, 0.0)) and uv[(3, 4)] == pytest.approx((7.2, 0.2))
    assert uv[(3, 3)] == pytest.approx((5.4, 0.0))


def test_interior_vertex_goes_to_the_middle():
    v = {0: (0.0, 0.0, 0.0), 1: (1.0, 0.0, 0.0), 2: (0.0, 1.0, 0.0), 3: (1.0, 1.0, 0.0), 4: (0.5, 0.5, 0.3)}
    f = {0: (0, 1, 4), 1: (1, 3, 4), 2: (3, 2, 4), 3: (2, 0, 4)}
    s = Strip(verts=v, faces=f, near=[0, 1], far=[2, 3], rungs=[(0, 0), (1, 1)], closed=False, height=1.0)
    uv = stripe_uvs(s)
    assert all(uv[(fi, 4)] == pytest.approx((0.5, 0.5)) for fi in f)


def test_end_side_vertex_on_the_strip_edge():
    v = {0: (0.0, 0.0, 0.0), 1: (2.0, 0.0, 0.0), 2: (0.0, 0.3, 0.0), 3: (1.7777778, 0.3, 0.0), 4: (2.0, 0.1, 0.0)}
    s = Strip(verts=v, faces={0: (0, 1, 4, 3, 2)}, near=[0, 1], far=[2, 3], rungs=[(0, 0), (1, 1)],
              closed=False, height=0.3, sides=([], [4]))
    assert stripe_uvs(s)[(0, 4)] == pytest.approx((1.8888889, 0.0751937), abs=1e-6)


def test_fit_stacks_strips():
    a, b = quad_strip(), square_ring()
    out = place_fit([stripe_uvs(a), stripe_uvs(b)], [a.height, b.height], [3.0, 7.2])
    us_a = [u for u, _v in out[0].values()]
    vs_a = [v for _u, v in out[0].values()]
    vs_b = [v for _u, v in out[1].values()]
    assert (min(us_a), max(us_a)) == pytest.approx((0.0, 1.0))
    assert max(vs_a) == pytest.approx(0.0833333, abs=1e-6)
    assert (min(vs_b), max(vs_b)) == pytest.approx((0.0933333, 0.1211111), abs=1e-6)


def test_in_place_scales_by_density_and_centres():
    out = place_in_place(stripe_uvs(quad_strip()), 3.0, 0.25, center=(0.75, 0.0625), density=0.5)
    us = [u for u, _v in out.values()]
    vs = [v for _u, v in out.values()]
    assert (min(us), max(us)) == pytest.approx((0.0, 1.5))
    assert (min(vs), max(vs)) == pytest.approx((0.0, 0.125))


def test_sharpest_rung_picks_the_acute_corner():
    s = square_ring()
    s.verts[3] = (-3.0, 2.0, 0.0)     # near corner 3 becomes about 34 degrees
    assert sharpest_rung(s) == 3


def test_repeated_far_id_needs_a_hint():
    v = {0: (0.0, 0.0, 0.0), 1: (1.0, 0.0, 0.0), 2: (2.0, 0.0, 0.0), 3: (1.0, 1.0, 0.0)}
    f = {0: (0, 1, 3), 1: (1, 2, 3)}
    s = Strip(verts=v, faces=f, near=[0, 1, 2], far=[3, 3, 3], rungs=[(0, 0), (1, 1), (2, 2)],
              closed=False, height=1.0)
    with pytest.raises(ValueError):
        stripe_uvs(s)
    s.corner_far = {(0, 3): 0, (1, 3): 2}
    uv = stripe_uvs(s)
    assert uv[(0, 3)][1] == pytest.approx(1.0)
    assert uv[(0, 3)][0] != uv[(1, 3)][0]


def test_open_strip_with_a_seam_on_its_near_row():
    # A closed chain 0-1-2 opened at 0 (Edge Slide's destructive mode: one cut, one open piece): the near row
    # starts and ends on vertex 0. Each of its corners takes the row position its face names, so the UV splits there.
    v = {0: (0.0, 0.0, 0.0), 1: (2.0, 0.0, 0.0), 2: (1.0, 2.0, 0.0),
         3: (0.0, -1.0, 0.0), 4: (3.0, -1.0, 0.0), 5: (1.0, 3.0, 0.0), 6: (-1.0, 0.0, 0.0)}
    f = {0: (0, 1, 4, 3), 1: (1, 2, 5, 4), 2: (2, 0, 6, 5)}
    s = Strip(verts=v, faces=f, near=[0, 1, 2, 0], far=[3, 4, 5, 6], rungs=[(k, k) for k in range(4)],
              closed=False, height=1.0, corner_near={(0, 0): 0, (2, 0): 3})
    length = strip_length(s)
    uv = stripe_uvs(s)
    assert uv[(0, 0)] == pytest.approx((0.0, 0.0)) and uv[(2, 0)] == pytest.approx((length, 0.0))
    assert uv[(0, 3)] == pytest.approx((0.0, 1.0)) and uv[(2, 6)] == pytest.approx((length, 1.0))


def test_collapsed_far_segment_is_one_point_on_the_far_row():
    v = {i: (float(i), 0.0, 0.0) for i in range(4)} | {4: (0.0, 1.0, 0.0), 5: (1.5, 1.0, 0.0), 6: (3.0, 1.0, 0.0)}
    f = {0: (0, 1, 5, 4), 1: (1, 2, 5), 2: (2, 3, 6, 5)}
    s = Strip(verts=v, faces=f, near=[0, 1, 2, 3], far=[4, 5, 6], rungs=[(0, 0), (1, 1), (2, 1), (3, 2)],
              closed=False, height=1.0)
    uv = stripe_uvs(s)
    # L = (near 3 + far 3) / 2 = 3: the far vertex shared by rungs 1 and 2 sits at its own arc length 1.5
    assert strip_length(s) == pytest.approx(3.0)
    assert all(uv[(fi, 5)][0] == pytest.approx(1.5) for fi in f)


def test_ring_with_seam_at_a_later_rung():
    s = square_ring()
    s.verts[3] = (-3.0, 2.0, 0.0)
    assert sharpest_rung(s) == 3
    length = strip_length(s)
    uv = stripe_uvs(s)
    # face 3 (3, 0, 4, 7) opens the strip, face 2 (2, 3, 7, 6) closes it
    assert uv[(3, 3)][0] == pytest.approx(0.0) and uv[(3, 7)][0] == pytest.approx(0.0)
    assert uv[(2, 3)][0] == pytest.approx(length) and uv[(2, 7)][0] == pytest.approx(length)
    assert uv[(3, 0)][0] > 0.0 and uv[(2, 2)][0] < length
    assert all(0.0 <= u <= length + 1e-9 for u, _v in uv.values())


def test_closed_collapsed_inset_with_repeated_far_ids():
    # 4 x 1 rectangle inset by 0.5: the far contour collapses to the segment A-B
    v = {0: (0.0, 0.0, 0.0), 1: (4.0, 0.0, 0.0), 2: (4.0, 1.0, 0.0), 3: (0.0, 1.0, 0.0),
         4: (0.5, 0.5, 0.0), 5: (3.5, 0.5, 0.0)}
    f = {0: (0, 1, 5, 4), 1: (1, 2, 5), 2: (2, 3, 4, 5), 3: (3, 0, 4)}
    hints = {(0, 4): 0, (0, 5): 1, (1, 5): 1, (2, 5): 2, (2, 4): 3, (3, 4): 3}
    s = Strip(verts=v, faces=f, near=[0, 1, 2, 3], far=[4, 5, 5, 4], rungs=[(k, k) for k in range(4)],
              closed=True, height=0.5, corner_far=hints)
    assert strip_length(s) == pytest.approx(8.0)
    uv = stripe_uvs(s)
    us = [u for u, _v in uv.values()]
    vs = [v_ for _u, v_ in uv.values()]
    assert (min(us), max(us)) == pytest.approx((0.0, 8.0))
    assert (min(vs), max(vs)) == pytest.approx((0.0, 0.5))
    # L = (near 4 + 1 + 4 + 1 = 10, far 3 + 0 + 3 + 0 = 6) / 2 = 8, seam at rung 0: near u = s * 0.8
    # (0, 3.2, 4.0, 7.2) and each far occurrence u = s * 8 / 6 (0, 4, 4, 8)
    assert uv[(0, 4)] == pytest.approx((0.0, 0.5)) and uv[(3, 0)] == pytest.approx((8.0, 0.0))
    assert uv[(3, 4)] == pytest.approx((8.0, 0.5)) and uv[(2, 5)] == pytest.approx((4.0, 0.5))
    assert uv[(1, 5)] == pytest.approx((4.0, 0.5)) and uv[(0, 1)] == pytest.approx((3.2, 0.0))


def test_strip_wound_the_other_way_is_not_mirrored():
    # faces whose loops run the near boundary backward: a cut on the other side of its chain
    for s in (quad_strip(), square_ring()):
        assert all(a > 0.0 for a in signed_areas(s, stripe_uvs(s)).values())
        length = strip_length(s)
        s.faces = {fid: tuple(reversed(face)) for fid, face in s.faces.items()}
        uv = stripe_uvs(s)
        assert all(a > 0.0 for a in signed_areas(s, uv).values()), signed_areas(s, uv)
        assert all(-1e-9 <= u <= length + 1e-9 and -1e-9 <= v <= s.height + 1e-9 for u, v in uv.values())


def test_rungs_running_backward_are_rejected():
    s = quad_strip()
    s.rungs = [(0, 0), (1, 2), (2, 1), (3, 3)]
    with pytest.raises(ValueError):
        strip_length(s)
    with pytest.raises(ValueError):
        stripe_uvs(s)


def collapsed_seam_ring():
    """A 2 x 2 square loop whose new loop has 3 vertices: the seam segment near 3 -> near 0 collapsed.

    Its anchors start mid-way round the far loop, [2, 0, 1, 2], as a closed cut gives them.
    """
    v = {0: (0.0, 0.0, 0.0), 1: (2.0, 0.0, 0.0), 2: (2.0, 2.0, 0.0), 3: (0.0, 2.0, 0.0),
         4: (1.5, 0.5, 0.0), 5: (1.5, 1.5, 0.0), 6: (0.5, 1.0, 0.0)}
    f = {0: (0, 1, 4, 6), 1: (1, 2, 5, 4), 2: (2, 3, 6, 5), 3: (3, 0, 6)}
    return Strip(verts=v, faces=f, near=[0, 1, 2, 3], far=[4, 5, 6],
                 rungs=[(0, 2), (1, 0), (2, 1), (3, 2)], closed=True, height=0.5)


def test_closed_rungs_starting_mid_loop_rotate_to_ascend():
    s = collapsed_seam_ring()
    with pytest.raises(ValueError):
        strip_length(s)
    fixed = ascending_rungs(s)
    assert fixed.near == [1, 2, 3, 0] and fixed.far == [4, 5, 6]
    assert fixed.rungs == [(0, 0), (1, 1), (2, 2), (3, 2)]
    uv = stripe_uvs(fixed)
    assert all(a > 0.0 for a in signed_areas(fixed, uv).values()), signed_areas(fixed, uv)
    assert all(uv[(fid, 6)][1] == pytest.approx(0.5) for fid in (0, 2, 3))


def test_ascending_rungs_keeps_a_strip_that_already_ascends():
    for s in (quad_strip(), square_ring()):
        assert ascending_rungs(s) is s
    s = square_ring()
    s.verts[3] = (-3.0, 2.0, 0.0)            # a unique sharpest corner, so the seam stays put
    expected = stripe_uvs(s)
    s.far = [5, 6, 7, 4]
    s.rungs = [(0, 3), (1, 0), (2, 1), (3, 2)]   # the same rungs with far listed from vertex 5
    uv = stripe_uvs(ascending_rungs(s))
    assert all(uv[key] == pytest.approx(expected[key]) for key in expected)


def test_closed_collapsed_inset_seam_on_a_collapse_node():
    # 4 x 1 rectangle fully collapsed to the ridge A-B, in the form Inset's stripe_for builds:
    # far lists each ridge vertex once and the rungs share them, so the seam far vertex is shared
    v = {0: (0.0, 0.0, 0.0), 1: (4.0, 0.0, 0.0), 2: (4.0, 1.0, 0.0), 3: (0.0, 1.0, 0.0),
         10: (0.5, 0.5, 0.0), 11: (3.5, 0.5, 0.0)}
    f = {100: (0, 1, 11, 10), 101: (1, 2, 11), 102: (2, 3, 10, 11), 103: (3, 0, 10)}
    s = ascending_rungs(Strip(verts=v, faces=f, near=[0, 1, 2, 3], far=[10, 11],
                              rungs=[(0, 0), (1, 1), (2, 1), (3, 0)], closed=True, height=0.5))
    length = strip_length(s)
    uv = stripe_uvs(s)
    # the unrolled faces tile the whole rectangle: no notch at the seam
    assert sum(abs(a) for a in signed_areas(s, uv).values()) == pytest.approx(length * s.height)
    # both seam columns are vertical: the seam's near and far corners share one u on each side
    near_seam, far_seam = s.near[s.rungs[0][0]], s.far[s.rungs[0][1]]
    for fid, face in f.items():
        if near_seam in face and far_seam in face:
            assert uv[(fid, near_seam)][0] == pytest.approx(uv[(fid, far_seam)][0]), fid
    seam_us = {round(uv[(fid, far_seam)][0], 9) for fid, face in f.items() if far_seam in face}
    assert seam_us == {0.0, round(length, 9)}


def test_uneven_edges_spread_uniformly():
    # L-corner strip: near is the outer corner (arms 2 + 2), far is the inner corner (arms 1.8 + 1.6)
    v = {0: (0.0, 0.0, 0.0), 1: (2.0, 0.0, 0.0), 2: (2.0, 2.0, 0.0),
         3: (0.0, 0.2, 0.0), 4: (1.8, 0.2, 0.0), 5: (1.8, 1.8, 0.0)}
    f = {0: (0, 1, 4, 3), 1: (1, 2, 5, 4)}
    s = Strip(verts=v, faces=f, near=[0, 1, 2], far=[3, 4, 5], rungs=[(0, 0), (1, 1), (2, 2)],
              closed=False, height=0.2)
    uv = stripe_uvs(s)
    L = (4.0 + 3.4) / 2                                           # 3.7
    assert uv[(0, 1)] == pytest.approx((2.0 * L / 4.0, 0.0))     # near row by its own arc length: 1.85
    assert uv[(0, 4)] == pytest.approx((1.8 * L / 3.4, 0.2))     # far row by its own arc length: 1.9588
    assert uv[(0, 1)][0] != pytest.approx(uv[(0, 4)][0])         # the column leans
    assert uv[(1, 2)][0] == pytest.approx(L) and uv[(1, 5)][0] == pytest.approx(L)


def test_interior_relax_keeps_faces_unflipped():
    # pocket-like strip: a raised interior pair between near and far
    v = {0: (0.0, 0.0, 0.0), 1: (2.0, 0.0, 0.0), 2: (0.0, 1.0, 0.0), 3: (2.0, 1.0, 0.0),
         4: (0.5, 0.3, 0.2), 5: (1.5, 0.3, 0.2)}
    f = {0: (0, 1, 5, 4), 1: (1, 3, 5), 2: (3, 2, 4, 5), 3: (2, 0, 4)}
    s = Strip(verts=v, faces=f, near=[0, 1], far=[2, 3], rungs=[(0, 0), (1, 1)], closed=False, height=1.0)
    uv = stripe_uvs(s)
    for fid, ids in f.items():
        pts = [uv[(fid, i)] for i in ids]
        area = sum(pts[i][0] * pts[(i + 1) % len(pts)][1] - pts[(i + 1) % len(pts)][0] * pts[i][1]
                   for i in range(len(pts)))
        assert area > 0.0
    assert 0.0 < uv[(0, 4)][0] < uv[(0, 5)][0] < 2.0


def test_flat_interior_keeps_its_place():
    # the pocket strip above laid flat: its boundary maps to its own (x, y), and mean-value weights
    # reproduce a flat fan exactly, so the interior pair keeps its (x, y) (uniform weights give v = 0.5)
    v = {0: (0.0, 0.0, 0.0), 1: (2.0, 0.0, 0.0), 2: (0.0, 1.0, 0.0), 3: (2.0, 1.0, 0.0),
         4: (0.5, 0.3, 0.0), 5: (1.5, 0.3, 0.0)}
    f = {0: (0, 1, 5, 4), 1: (1, 3, 5), 2: (3, 2, 4, 5), 3: (2, 0, 4)}
    s = Strip(verts=v, faces=f, near=[0, 1], far=[2, 3], rungs=[(0, 0), (1, 1)], closed=False, height=1.0)
    uv = stripe_uvs(s)
    assert all(uv[(fid, 4)] == pytest.approx((0.5, 0.3)) for fid in (0, 2, 3))
    assert all(uv[(fid, 5)] == pytest.approx((1.5, 0.3)) for fid in (0, 1, 2))
