import dataclasses
import math
import random

import pytest
from smart_edge_slide_fixtures import (
    _flat_band,
    asymmetric_l_ngon,
    bumped_arm,
    chain_jittered_u,
    dumbbell,
    dumbbell_hole,
    dumbbell_neck_width,
    dumbbell_room_limits,
    fanned_u,
    grid_racket,
    hole_rim,
    jittered_hole_rim,
    jittered_shoot_strip,
    jittered_u,
    jittered_u_wall,
    notch_spike,
    racket_hole,
    racket_ngon,
    shoot_bevel,
    shoot_strip,
    shoot_strip_landing_edge,
    shoot_strip_wall_end,
    square_in_grid,
    u_wall,
    xy_jittered,
)
from test_smart_edge_slide_core import end_slide, fold_box, grid_open, jittered_grid, strip2, u_in_grid, walls_meet

from utils.smart_edge_slide_core import (
    _ANCHOR_SNAP_TOL,
    EXACT_TOL,
    Angles,
    OutOfRoom,
    Slider,
    SurfacePoint,
    _band_scale,
)
from utils.smart_edge_slide_wave import _REST_HOLD, WaveSlider, _Step


def tilted(band, eps):
    # ``band`` with chain[1] nudged by ``eps`` perpendicular to the first chain edge, in the plane; the mesh is not
    # rotated, so only the faces at chain[1] change.
    (ax, ay, _), (bx, by, bz) = band.verts[band.chain[0]], band.verts[band.chain[1]]
    d = math.hypot(bx - ax, by - ay)
    verts = dict(band.verts)
    verts[band.chain[1]] = (bx - eps * (by - ay) / d, by + eps * (bx - ax) / d, bz)
    return dataclasses.replace(band, verts=verts)


def rotated(band, angle):
    # ``band`` turned by ``angle`` radians about the z axis: the same mesh, with other float noise.
    c, s = math.cos(angle), math.sin(angle)
    return dataclasses.replace(band, verts={v: (c * x - s * y, s * x + c * y, z) for v, (x, y, z) in band.verts.items()})


def jittered(band, seed, eps=1e-9):
    # ``band`` with every vertex moved by up to ``eps`` along x, y and z, seeded: noise everywhere at once.
    rnd = random.Random(seed)  # noqa: S311 - seeded test noise, not security
    return dataclasses.replace(band, verts={v: tuple(c + rnd.uniform(-eps, eps) for c in co)
                                            for v, co in sorted(band.verts.items())})


def _shots(w, exact, lim):
    # The wave's shots up to ``lim``: (slot, landing) each.
    return [e.data for e in w._wave(exact) if e.kind == "wall_end" and e.width <= lim + 1e-6]


def distance_to_chain(band, co):
    # In-plane distance of ``co`` to the chain polyline (a closed chain wraps); the fixtures here lie in z = 0.
    pts = [band.verts[v] for v in band.chain]
    pairs = list(zip(pts, pts[1:] + pts[:1])) if band.closed else list(zip(pts, pts[1:]))
    best = math.inf
    for (ax, ay, _), (bx, by, _) in pairs:
        ex, ey = bx - ax, by - ay
        t = min(1.0, max(0.0, ((co[0] - ax) * ex + (co[1] - ay) * ey) / (ex * ex + ey * ey)))
        best = min(best, math.hypot(co[0] - ax - t * ex, co[1] - ay - t * ey))
    return best


def _line_distance(band, k, co):
    # Distance of ``co`` from the line of chain edge k (the fixtures here lie in the z = 0 plane; a closed chain wraps).
    (ax, ay, _), (bx, by, _) = band.verts[band.chain[k]], band.verts[band.chain[(k + 1) % len(band.chain)]]
    return abs((bx - ax) * (co[1] - ay) - (by - ay) * (co[0] - ax)) / math.hypot(bx - ax, by - ay)


def _end_fold(w, exact):
    return next(e.width for e in w._wave(exact) if e.kind == "fold" and 0 in e.data)


def _point(cut, k):
    return cut.points[cut.anchors[k]].co


def _gaps(w, n, exact=False):
    # The widths of n even samples below the destructive limit at which the solve does not fit.
    lim = w.limit(exact=exact, destructive=True)
    bad = []
    for i in range(1, n + 1):
        try:
            w.solve(lim * i / n, exact=exact, destructive=True)
        except OutOfRoom:
            bad.append(lim * i / n)
    return bad


def test_wave_matches_slider_with_destructive_off():
    for make in (strip2, grid_open, u_in_grid, fold_box, walls_meet, u_wall, hole_rim):
        b = make()
        s, w = Slider(b), WaveSlider(b)
        for exact, collapse in ((False, False), (True, False), (False, True)):
            assert w.limit(exact=exact, collapse=collapse) == s.limit(exact=exact, collapse=collapse)


def test_wave_solves_like_slider_with_destructive_off():
    for make in (strip2, grid_open, u_in_grid, fold_box, walls_meet, u_wall, hole_rim):
        b = make()
        s, w = Slider(b), WaveSlider(b)
        for exact, collapse in ((False, False), (True, False), (False, True)):
            lim = s.limit(exact=exact, collapse=collapse)
            for width in (0.3 * lim, 0.6 * lim, 0.9 * lim):
                want = s.solve(width, exact=exact, collapse=collapse)
                got = w.solve(width, exact=exact, collapse=collapse)
                assert [p.co for p in got.points] == [p.co for p in want.points]


def test_end_segment_folds_into_the_end_in_destructive():
    # fanned_u: the bottom-left corner's group reaches the mouth's wall at width 1.875, where segment 0 folds. Collapse
    # alone stops there; destructive goes on, and the end absorbs its neighbour. (u_in_grid has no end fold before its
    # arms meet: its end wall is perpendicular to the arms. On walls_meet chain edge 1 runs along the wall past vertex
    # 4, so the start's group has no wall left to keep its distance from edge 1 on, and destructive stops there too.)
    b = fanned_u()
    w = WaveSlider(b)
    c_lim = w.limit(collapse=True)
    d_lim = w.limit(destructive=True)
    assert d_lim > c_lim + 0.1
    cut = w.solve((c_lim + d_lim) / 2, destructive=True)
    assert cut.anchors[0] == cut.anchors[1]


@pytest.mark.parametrize("exact", [False, True])
def test_end_fold_is_continuous(exact):
    # Across the end fold every new vertex moves on by O(dw): the group starts on the end's own point. That holds for
    # every vertex only because fanned_u's rails are all exact; in default mode a merge can move a vertex by its width
    # error |y - w| at once, as collapse's merges do (see test_end_group_keeps_a_nonzero_width_error_past_its_fold).
    b = fanned_u()
    w = WaveSlider(b)
    at, dw = _end_fold(w, exact), 1e-4
    lo, hi = w.solve(at - dw, exact=exact, destructive=True), w.solve(at + dw, exact=exact, destructive=True)
    assert lo.anchors[0] != lo.anchors[1] and hi.anchors[0] == hi.anchors[1]
    for k in range(len(b.chain)):
        assert math.dist(lo.points[lo.anchors[k]].co, hi.points[hi.anchors[k]].co) < 10.0 * dw


def test_end_group_is_exact_past_the_fold():
    # Past the fold the start's group keeps its distance from the chain edge its remaining segment starts on: the width,
    # less the width error frozen at the fold, which exact mode keeps within EXACT_TOL.
    b = fanned_u()
    w = WaveSlider(b)
    at, lim = _end_fold(w, True), w.limit(exact=True, destructive=True)
    for i in range(1, 21):
        width = at + (lim - at) * i / 21
        cut = w.solve(width, exact=True, destructive=True)
        j = max(k for k, a in enumerate(cut.anchors) if a == cut.anchors[0])    # the start's group is 0..j
        assert 0 < j < len(b.chain) - 1
        assert _line_distance(b, j, cut.points[cut.anchors[0]].co) == pytest.approx(width, abs=EXACT_TOL * width)


def test_end_group_keeps_its_width_error_from_the_fold():
    # walls_meet, default mode: segment 0 folds where chain[1]'s rail vertex still lags behind the start end, which lies
    # on y = 0 at distance 1 from edge 1's line y = 1. The group keeps that error, starting on the end's point. Past
    # vertex 4 its wall runs along y = 0, level with edge 1's line, so the wall ends for it at once: it shoots on along
    # that line, which leaves the band at vertex 4 (where no edge rises away from edge 1's line: the end edge 0-4 climbs
    # back toward it), and it stays on its fold point. The loop goes on till segment 2 folds into the end, whose wall
    # is y = 0 too: then nothing moves any more, the loop's final state, held from a hair below (``_REST_HOLD``, about
    # as a used-up state is). Exact mode folds both at 1, as C.
    b = walls_meet()
    w = WaveSlider(b)
    at = _end_fold(w, False)
    group = next(g for i, s, g in w._wave_of(False).groups if s == 0 and not g.stuck)
    assert group.edge == 1 and group.error == pytest.approx(at - 1.0)
    assert w._end_point(True, group, at) == pytest.approx(w._end_xy(True, at))
    assert [(e.kind, e.data) for e in w._wave(False)[:2]] == [("fold", (0,)), ("wall_end", (0, None))]
    stays = [_point(w.solve(at + d, destructive=True), 0) for d in (1e-4, 0.03, 0.07)]
    assert all(p == pytest.approx(stays[0], abs=1e-12) for p in stays)
    last = next(e.width for e in w._wave(False) if e.kind == "fold" and 2 in e.data)
    assert w.limit(destructive=True) == pytest.approx(last - _REST_HOLD, abs=1e-9) and last > at + 0.07
    assert w.limit(exact=True, destructive=True) == pytest.approx(w.limit(exact=True, collapse=True), abs=1e-5)


@pytest.mark.parametrize("seed", [1, 6, 19, 25, 37])
def test_end_group_keeps_a_nonzero_width_error_past_its_fold(seed):
    # chain_jittered_u, default mode: a fold leaves an end's group with a width error of 0.005 to 0.022, and room after
    # it. The end's point runs on from where it was, and past the fold it keeps its distance from the chain edge its
    # remaining segment starts on at the width less that error.
    b = chain_jittered_u(seed)
    w = WaveSlider(b)
    lim = w.limit(destructive=True)
    folds = [e.width for e in w._wave(False) if e.kind == "fold"]
    at, side, group = next(
        (x, side, g) for x in folds for side, g in enumerate(w._end_groups(False, x))
        if g is not None and g.width == x and abs(g.error) > 1e-3)
    end = 0 if side == 0 else len(b.chain) - 1
    room = min([x for x in folds if x > at + 1e-6] + [lim])
    assert room - at > 1e-3
    before, after = (_point(w.solve(at + d, destructive=True), end) for d in (-1e-5, 1e-5))  # across the hold
    assert math.dist(before, after) < 1e-3
    for t in (0.25, 0.5, 0.75):
        width = at + (room - at) * t
        co = _point(w.solve(width, destructive=True), end)
        assert _line_distance(b, group.edge, co) == pytest.approx(width - group.error, abs=1e-6)


def test_end_group_shoots_on_where_its_wall_heads_back():
    # chain_jittered_u(8), default mode: segment 0 folds where the start's wall turns back toward the line of chain edge
    # 4, the edge the group's remaining segment starts on. Going on, the group would jump 0.51 along the wall to where
    # it gets far enough again; instead the wall ends there for it and it shoots on (collapse stops at that fold). Its
    # offset line lands on edge 26-34, but its neighbour, a leaning rail vertex, lags behind that line: the segment to
    # the landing would pass the wall's last point on the chain's side, so the end waits there. The landing's wall
    # gives out at 1.679533 before the neighbour catches up: the end gives it up and stays where it slid to, and the
    # loop goes on: vertex 5 cuts at 1.705438.
    b = chain_jittered_u(8)
    w = WaveSlider(b)
    at = w.limit(collapse=True)
    assert at == pytest.approx(1.673342, abs=1e-6)
    shots = [(round(e.width, 6), e.data) for e in w._wave(False) if e.kind == "wall_end"]
    assert shots[:2] == [(round(at, 6), (0, (26, 34))), (1.679533, (0, None))]
    assert w._end_groups(False, at + 1e-4)[0].pending is not None           # waiting
    assert w.limit(destructive=True) > at + 0.03
    before, after, later = (_point(w.solve(at + d, destructive=True), 0) for d in (-1e-4, 1e-4, 0.03))
    assert math.dist(before, after) < 1e-3 and after == pytest.approx(later, abs=1e-12)  # it stays where it slid to
    assert _gaps(w, 500) == []


def test_a_level_wall_step_ends_the_wall_for_a_group():
    # A wall step that runs level with the group's edge line gives the group no distance to gain, the same as one that
    # heads back toward it: the group stays at its start till the width reaches that height, and then the wall ends for
    # it, instead of the group jumping the step's length to the next rising one. fanned_u's start group, on a made-up
    # path where a point's distance from the edge's line is its y: rising (0,1)-(.5,1.5), level to (1.5,1.5), rising.
    w = WaveSlider(fanned_u())
    group = next(g for _, side, g in w._wave_of(False).groups if side == 0)
    pts = [(0.0, 1.0), (0.5, 1.5), (1.5, 1.5), (2.0, 2.5)]
    w._steps[True] = [_Step(0, (), 0, 0, pts[i], pts[i + 1]) for i in range(3)]
    w._heights[(True, group.edge)] = [p[1] for p in pts[1:]]
    g = dataclasses.replace(group, width=1.0, error=0.0, step=0, start=pts[0], height=1.0)
    assert w._group_xy(True, g, 1.25) == pytest.approx((0.25, 1.25))
    assert w._group_xy(True, g, 1.5) == pytest.approx((0.5, 1.5))
    with pytest.raises(OutOfRoom):
        w._group_xy(True, g, 1.6)


@pytest.mark.parametrize(("seed", "jitter", "fan"), [(11, 0.35, 0.6), (76, 0.3, 0.8)])
def test_limit_probes_just_below_the_plan_bound(seed, jitter, fan):
    # On these the solve fails for a stretch just below the plan's bound, too short for the even samples to land in.
    assert _gaps(WaveSlider(jittered_u(seed, jitter, fan)), 2000) == []


def test_a_touch_at_a_bend_is_no_fold_either_way():                         # anti-goal 3
    # jittered_u(6, 0.3, 0.6): at width 0.82017 the rail paths of chain[4] and chain[5] pass through one mesh vertex,
    # where segment 4 shrinks to nothing and grows again. That touch is no fold, whichever side of the bend float
    # noise puts it on: turned by -1e-9 about z the mesh once folded segment 4 there and stopped, so the limit stays.
    b = jittered_u(6, 0.3, 0.6)
    for exact in (False, True):
        assert WaveSlider(rotated(b, -1e-9)).limit(exact=exact, destructive=True) == pytest.approx(
            WaveSlider(b).limit(exact=exact, destructive=True), abs=1e-6)


@pytest.mark.parametrize(("seed", "jitter", "fan"), [(33, 0.4, 0.6), (21, 0.3, 0.8)])
def test_destructive_plan_never_fits_again_once_it_fails(seed, jitter, fan):
    # limit() bisects the plan, which takes the plan to fit up to one width and never past it. On these segment 6 really
    # folds (shrinking) right at a stretch's start, into a group whose outer chain edges run parallel: that stops the
    # wave there. Left unfolded, it folded back and the plan failed, then fitted again once a later fold dropped it.
    w = WaveSlider(jittered_u(seed, jitter, fan))
    top = 4.0 * _band_scale(w.band)
    used = w._used_up(False)
    if used is not None:
        top = min(top, used.width)
    failed, again = False, []
    for i in range(1, 4001):
        try:
            w._plan(top * i / 4000, False, True, destructive=True)
            if failed:
                again.append(top * i / 4000)
        except OutOfRoom:
            failed = True
    assert again == []


@pytest.mark.parametrize(("seed", "jitter"), [(33, 0.4), (17, 0.2)])
def test_destructive_solve_past_the_limit_is_clamped(seed, jitter):
    # Past the limit the solve holds the cut at the limit, clamped, even where a wider width would fit again: on
    # jittered_u(33, 0.4, 0.6) the plan, on jittered_u(17, 0.2, 0.6) a trace into the jagged wall stops the slide short.
    w = WaveSlider(jittered_u(seed, jitter, 0.6))
    lim = w.limit(destructive=True)
    at = w.solve(lim, destructive=True)
    assert not at.clamped
    for over in (0.1, 0.5):
        cut = w.solve(lim + over, destructive=True)
        assert cut.clamped and cut.width == lim and [p.co for p in cut.points] == [p.co for p in at.points]


def test_cap_limit_lowers_the_destructive_limit_of_its_mode():
    # The bridge caps the limit where the cut at it cannot be built: the solve clamps at the cap, with the cut the
    # solve gives there, the snap stops there, and the other exact mode and the default mode keep their limits.
    w = WaveSlider(u_wall())
    lim, exact_lim, plain = w.limit(destructive=True), w.limit(exact=True, destructive=True), w.limit()
    cap = 0.8 * lim
    w.cap_limit(2.0 * lim)                                                # above the limit: no change
    assert w.limit(destructive=True) == lim
    w.cap_limit(cap)
    assert w.limit(destructive=True) == cap
    at = w.solve(cap, destructive=True)
    cut = w.solve(lim, destructive=True)
    assert not at.clamped and cut.clamped and cut.width == cap
    assert [p.co for p in cut.points] == [p.co for p in at.points]
    assert w.limit(exact=True, destructive=True) == exact_lim and w.limit() == plain
    free = WaveSlider(u_wall())
    beyond = free.solve(0.9 * lim, destructive=True)                     # a point the loop reaches past the cap
    target = next(p for p in beyond.points if free.snap_width(p, destructive=True) == pytest.approx(0.9 * lim, abs=1e-5))
    got = w.snap_width(target, destructive=True)
    assert got is None or got <= cap, got


def test_no_gaps_where_two_rail_paths_join():
    # jittered_u(68, 0.4): from width 1.336 the rail paths of chain[9] and chain[10] run through the same vertices, so
    # segment 9 has no length, on a straight run of the chain where the two cannot merge (their outer edges run
    # parallel). Its length of float noise once read as folding back, on and off; now the two just go on together.
    w = WaveSlider(jittered_u(68, 0.4))
    assert _gaps(w, 2000) == []
    assert w.limit(destructive=True) == pytest.approx(w.limit(collapse=True), abs=1e-5)


def test_used_up_ends_apart_leave_a_break():
    # chain_jittered_u(24, 0.25, 0.05, 0.8), default mode: the start's group keeps a width error to the last, so when the
    # last segment folds the two ends' points lie 0.012 apart. The final state is those two points, with no new edge
    # between them; it holds from the anchor snap below the used-up width, the limit, and past it.
    w = WaveSlider(chain_jittered_u(24, 0.25, 0.05, 0.8))
    used = w._used_up(False)
    lim = w.limit(destructive=True)
    assert used is not None and lim == w._wave_of(False).since[-1] and lim == pytest.approx(used.width, abs=5e-6)
    split = used.data[0]
    for width, clamped in ((lim, False), (used.width, True), (used.width + 0.5, True)):
        cut = w.solve(width, destructive=True)
        assert len(cut.points) == 2 and cut.breaks == (1,) and cut.clamped == clamped
        assert math.dist(cut.points[0].co, cut.points[1].co) == pytest.approx(0.011569, abs=1e-5)
        assert cut.anchors == [0] * split + [1] * (len(cut.anchors) - split)


@pytest.mark.parametrize("exact", [False, True])
def test_destructive_solves_just_below_every_event(exact):
    # Just before a fold the vertices about to merge lie within the anchor snap of each other, or of the wall, which
    # once left the segment between them running along a wall edge.
    w = WaveSlider(fanned_u())
    lim = w.limit(exact=exact, destructive=True)
    for e in w._wave(exact):
        for d in (1e-8, 3e-8, 1e-7, 3e-7, 1e-6, 3e-6, 1e-5):
            if 0.0 < e.width - d <= lim:
                w.solve(e.width - d, exact=exact, destructive=True)


@pytest.mark.parametrize(("jitter", "seed", "limit"), [(0.2, 17, 0.856645), (0.3, 11, 2.105830),
                                                       (0.3, 22, 1.080621), (0.3, 36, 0.950585)])
def test_rough_fanned_grids_limit_where_solve_first_fails(jitter, seed, limit):
    # On these the loop runs into its jagged wall well below where it is used up: a segment crosses the wall, or a
    # group's point lies past it. The limit is the first width that does not solve, not the used-up width.
    assert WaveSlider(jittered_u(seed, jitter, 0.6)).limit(destructive=True) == pytest.approx(limit, abs=1e-6)


def test_middle_vertex_reaching_the_end_wall_opens_the_loop():
    # u_wall(): the user's U case in small. The arms bend at the second vertex from each end, which stands out into the
    # side and runs into a wall (an open edge) first, at 0.439340, while the ends still slide along the mouth.
    b = u_wall()
    w = WaveSlider(b)
    assert w.limit(collapse=True) < 0.5
    cut = w.solve(0.75, destructive=True)
    assert len(cut.breaks) >= 1
    for i in cut.breaks:                                   # both sides of every break lie on a wall edge
        assert cut.points[i - 1].kind in ("edge", "vert") and cut.points[i].kind in ("edge", "vert")


def test_closed_loop_reaching_the_border_becomes_open():
    # hole_rim(): a closed diamond chain (a square turned 45 degrees) round a hole in a grid, off-centre so
    # that, sliding outward, its left corner reaches the grid's border x = 0 first, before any other vertex.
    b = hole_rim()
    w = WaveSlider(b)
    cut = w.solve(2.5, destructive=True)
    assert 0 not in cut.breaks and len(cut.breaks) == 1   # opened once, mid-way round
    assert w.limit(destructive=True) > 2.5


def test_split_ends_keep_the_width():
    b = hole_rim()
    w = WaveSlider(b)
    cut = w.solve(2.5, destructive=True)
    for i in cut.breaks:
        for p in (cut.points[i - 1], cut.points[i]):
            assert distance_to_chain(b, p.co) == pytest.approx(2.5, abs=1e-6)


def test_wall_hits_are_exact_events():
    # u_wall: c1 and c8 reach their holes at 0.75 (2 - sqrt2) (see u_wall), as exact plan-level events, in chain order at
    # the same width. At 0.75 the ends lie where the fixture's comment works them out. Every end's wall ends on a hole
    # corner, on the open border, where the end has landed: it stays (see u_wall). The middle piece closes into a ridge
    # at width 2, its final state; the outer pieces go on till each is pressed onto its walls, at 2.9 / sqrt2.
    b = u_wall()
    w = WaveSlider(b)
    hits = [e for e in w._wave(False) if e.kind == "wall_hit"]
    assert [e.data[0] for e in hits] == [1, 8]
    for e in hits:
        assert e.width == pytest.approx(0.75 * (2.0 - math.sqrt(2.0)), abs=1e-12)
    shots = [(round(e.width, 6), e.data) for e in w._wave(False) if e.kind == "wall_end"]
    assert shots == [(1.484926, ((False, 1, False), None)), (1.484926, ((False, 8, True), None)),
                     (1.500002, ((False, 1, True), None)), (1.500002, ((False, 8, False), None))]
    for width in (1.6, 1.9):
        cut = w.solve(width, destructive=True)                         # c1's ends on c and b, c8's on b' and c'
        got = [x for i in cut.breaks for p in (cut.points[i - 1], cut.points[i]) for x in p.co[:2]]
        assert got == pytest.approx([2.5, 3.6, 2.5, 3.0, 3.5, 3.0, 3.5, 3.6], abs=1e-9)
    assert w.limit(destructive=True) == w._wave_of(False).since[-1] == pytest.approx(2.9 / math.sqrt(2.0), abs=5e-6)
    cut = w.solve(0.75, destructive=True)
    i = cut.breaks[0]
    assert cut.points[i - 1].co[:2] == pytest.approx((0.4 + 0.75 * math.sqrt(2.0), 3.6), abs=1e-9)
    assert cut.points[i].co[:2] == pytest.approx((1.75, 3.0), abs=1e-9)
    assert cut.anchors[1] == i - 1                                    # the cut vertex anchors its left end


@pytest.mark.parametrize("exact", [False, True])
def test_split_ends_keep_the_vertex_width_error(exact):
    # jittered_hole_rim(1): L's rail leans off the bisector, so in default mode L reaches the border with a width error
    # (its lean, 0.136198 against edge T-L and the opposite against L-B). Each end keeps its own frozen, as an end's
    # group keeps the error it had at a fold: no jump at the cut, and the honest rate past it. Exact mode keeps it
    # within EXACT_TOL.
    b = jittered_hole_rim(1)
    w = WaveSlider(b)
    hit = next(e for e in w._wave(exact) if e.kind == "wall_hit")
    assert hit.data[0] == 3
    left, right = (next(g for _, s, g in w._wave_of(exact).groups if s == (exact, 3, ahead)) for ahead in (False, True))
    assert left.error == pytest.approx(-right.error, abs=1e-12)
    if exact:
        assert abs(left.error) <= EXACT_TOL * hit.width
    else:
        assert left.error == pytest.approx(0.136198, abs=1e-6)
    nxt = next(e.width for e in w._wave(exact) if e.width > hit.width + 1e-6)
    for t in (0.1, 0.5, 0.9):
        width = hit.width + (nxt - hit.width) * t
        cut = w.solve(width, exact=exact, destructive=True)
        i = cut.breaks[0]
        assert _line_distance(b, 2, cut.points[i - 1].co) == pytest.approx(width - left.error, abs=1e-9)
        assert _line_distance(b, 3, cut.points[i].co) == pytest.approx(width - right.error, abs=1e-9)
    lo, hi = (w.solve(hit.width + d, exact=exact, destructive=True) for d in (-1e-6, 1e-6))
    assert not lo.breaks and len(hi.breaks) == 1
    assert math.dist(_point(lo, 3), hi.points[hi.breaks[0]].co) < 1e-5     # the right end starts on L's point


@pytest.mark.parametrize("exact", [False, True])
def test_cut_ends_pass_wall_vertices(exact):
    # hole_rim: L's ends reach the border vertices (0,6) and (0,4) at w = sqrt2 (their distance from the lines of T-L and
    # L-B), and the corners' ends pass more of them from 2.828427 on. A cut end once stayed on its wall step up to the
    # anchor snap past such a vertex in width, which along this wall (at 45 degrees to the edge's line) ran its plan
    # point past the vertex by more than the snap while its trace clamped onto it: the next segment missed its partner
    # just below every one of those widths. The pieces finish one by one, the last at 9 / sqrt2 (see hole_rim).
    w = WaveSlider(hole_rim())
    for width in (1.4142152, 2.8284288):
        w.solve(width, exact=exact, destructive=True)
    assert w.limit(exact=exact, destructive=True) == pytest.approx(9.0 / math.sqrt(2.0), abs=5e-6)


def test_middle_vertex_reaching_its_end_wall_splits_along_it():
    # chain_jittered_u(6, 0.3, 0.3): bottom vertex 6 reaches the mouth's end wall (edge 35-36, on both end paths) at
    # 1.977585, before anything else stops the wave. Both ends slide along the end wall, the left one on segment 5's
    # offset line, the right one on segment 6's, at the width from each (vertex 6 is exact there): one break, up to the
    # next event (a fold at 2.108439 in exact mode, the right piece pressed onto its walls at 2.110678).
    b = chain_jittered_u(6, 0.3, 0.3)
    w = WaveSlider(b)
    path = {frozenset((s.u, s.far)) for s in w._end_steps(True)}
    for exact in (False, True):
        hit = next(e for e in w._wave(exact) if e.kind == "wall_hit")
        assert hit.data[0] == 6 and frozenset(hit.data[1]) in path
        assert hit.width == pytest.approx(1.977585, abs=1e-6)
        nxt = next(e.width for e in w._wave(exact) if e.width > hit.width + 1e-6)
        assert w.limit(exact=exact, destructive=True) > nxt > hit.width + 0.1
        for t in (0.1, 0.4, 0.7, 0.95):
            width = hit.width + (nxt - hit.width) * t
            cut = w.solve(width, exact=exact, destructive=True)
            assert len(cut.breaks) == 1
            left, right = cut.points[cut.breaks[0] - 1], cut.points[cut.breaks[0]]
            for p in (left, right):
                assert p.kind == "edge" and frozenset(p.edge) in path
            assert _line_distance(b, 5, left.co) == pytest.approx(width, abs=1e-9)
            assert _line_distance(b, 6, right.co) == pytest.approx(width, abs=1e-9)


@pytest.mark.parametrize("exact", [False, True])
def test_merged_group_reaching_a_wall_opens_the_loop(exact):
    # notch_spike: segment 1 folds at 0.724264, and the group B-C reaches the spike tip T at 1.060660 (see the fixture).
    # The cut is at the group's first member, B; the right end takes the group, on C-D's offset line.
    b = notch_spike()
    w = WaveSlider(b)
    events = [(e.kind, e.data) for e in w._wave(exact)]
    assert events[:2] == [("fold", (1,)), ("wall_hit", (1, 7))]            # 7: T, the wall vertex reached
    fold, hit = w._wave(exact)[:2]
    assert fold.width == pytest.approx(0.3 / (math.sqrt(2.0) - 1.0), abs=1e-12)
    assert hit.width == pytest.approx(1.5 / math.sqrt(2.0), abs=1e-12)
    for width in (1.1, 1.3, 1.6):
        cut = w.solve(width, exact=exact, destructive=True)
        assert len(cut.breaks) == 1
        i = cut.breaks[0]
        left, right = cut.points[i - 1], cut.points[i]
        assert left.kind == right.kind == "edge"
        assert _line_distance(b, 0, left.co) == pytest.approx(width, abs=1e-9)
        assert _line_distance(b, 2, right.co) == pytest.approx(width, abs=1e-9)
        assert cut.anchors[1] == i - 1 and cut.anchors[2] == i            # the right end holds the group B-C
    left = w.solve(1.3, exact=exact, destructive=True)
    assert left.points[left.breaks[0] - 1].co[:2] == pytest.approx((-0.084619, 1.623097), abs=1e-6)


@pytest.mark.parametrize("exact", [False, True])
def test_a_collinear_group_carries_on_along_the_normal(exact):
    # bumped_arm: segments 1 and 2 fold together at 1 / (sqrt2 - 1), and the group c1-c3, whose outer edges are
    # collinear, goes on along their shared normal, on the offset line y = w, from the fold point (2, w). Collapse (C)
    # stops at the fold; D goes on to the end walls' ends, at 6.
    b = bumped_arm()
    w = WaveSlider(b)
    at = 1.0 / (math.sqrt(2.0) - 1.0)
    fold = next(e for e in w._wave(exact) if e.kind == "fold")
    assert fold.data == (1, 2) and fold.width == pytest.approx(at, abs=1e-12)
    assert w.limit(exact=exact, collapse=True) == pytest.approx(at, abs=1e-6)
    assert w.limit(exact=exact, destructive=True) == pytest.approx(6.0, abs=1e-5)
    for width in (at + 1e-7, at + 0.1, 3.5, 5.5):
        p = _point(w.solve(width, exact=exact, destructive=True), 2)
        assert p[:2] == pytest.approx((2.0, width), abs=1e-9)
    lo, hi = (w.solve(at + d, exact=exact, destructive=True) for d in (-1e-7, 1e-7))
    for k in range(len(b.chain)):                                         # nothing jumps at the fold
        assert math.dist(_point(lo, k), _point(hi, k)) < 1e-6


def test_a_straight_run_folding_together_goes_on():
    # jittered_u(30, 0.4): at 1.301662 segment 1 folds on the straight left arm, where the outer chain edges 0 and 2 are
    # collinear. That group once stopped the wave there in D (and still stops C); now it goes on along the arm's normal,
    # continuously, and the wave runs on: past 2.345398, where the end's wall ends (it shoots on, and so does the start
    # at 2.358772), till the arms' offset lines x = 1 + w and x = 6 - w meet at 2.5, where the loop closes into a ridge,
    # its final state, from the anchor snap below (the same under the tilt test's perturbations).
    b = jittered_u(30, 0.4)
    w = WaveSlider(b)
    at = 1.3016615886
    for exact in (False, True):
        assert w.limit(exact=exact, destructive=True) == pytest.approx(2.5 - _ANCHOR_SNAP_TOL, abs=1e-9)
        assert not w.solve(1.3017, exact=exact, destructive=True).clamped
        lo, hi = (w.solve(at + d, exact=exact, destructive=True) for d in (-1e-7, 1e-7))
        for k in range(len(b.chain)):
            assert math.dist(_point(lo, k), _point(hi, k)) < 1e-5


def test_end_segment_cutting_a_wall_corner_shoots_on():
    # chain_jittered_u(30, 0.3, 0.3), default mode: at 0.551572 the start end passes its wall's vertex 36, where the wall
    # turns in toward segment 0 (which runs nearly along it, 5.0e-2 against 5.3e-2 per unit). Past it segment 0 would
    # cut the corner, up to 1.3e-4 outside the band, till 0.5627: the wall is no use to the end from there, and it
    # shoots on. Its offset line runs on just under the next wall step 36-37, out of the band at once: it stays on 36.
    # Collapse (C) stops at the wall's end, 0.756467, with the solve failing on [0.551572, 0.562712]; D goes past both,
    # with no gap. Exact mode has no lean there: its start slides on to the wall's end at 0.756467 and stays there,
    # finding nothing to land on.
    w = WaveSlider(chain_jittered_u(30, 0.3, 0.3))
    shot = next(e for e in w._wave(False) if e.kind == "wall_end")
    assert shot.width == pytest.approx(0.551572, abs=1e-6) and shot.data == (0, None)
    assert w.solve(0.7, destructive=True).points[0].vert == 36
    assert w.limit(destructive=True) > w.limit(collapse=True) + 0.2       # 0.985814
    assert _gaps(w, 2000) == []
    shot = next(e for e in w._wave(True) if e.kind == "wall_end")
    assert shot.width == pytest.approx(0.756467, abs=1e-6) and shot.data == (0, None)
    assert w.limit(exact=True, destructive=True) > 0.756467 + 0.1          # 0.901131
    assert _gaps(w, 400, exact=True) == []


def _break_legs(cut):
    # Per break: (the chain vertices joined to its left end, those joined to its right end).
    out = []
    for i in cut.breaks:
        left = (i - 1) % len(cut.points)
        out.append(({v for v, at in cut.connectors if at == left}, {v for v, at in cut.connectors if at == i}))
    return out


@pytest.mark.parametrize("exact", [False, True])
def test_both_ends_of_a_cut_connect_to_the_cut_vertex(exact):
    # Each piece of an opened loop closes its own strip: both ends of a cut connect to the cut vertex, where the
    # straight leg there crosses nothing (the connectors' rule). u_wall (0.47): c1 and c8 have cut at their holes since
    # 0.439340; each end still lies on hole side a-d (resp. its mirror), which c1 sees straight across face 0.
    # hole_rim (1.0): L has cut on the border x = 0 since 0.707107, and its ends lie on the border edges (0,4)-(0,5)
    # and (0,5)-(0,6), in the two quads at L (up to sqrt2, where they reach (0,4) and (0,6)).
    for b, width, cut_vertices in ((u_wall(), 0.47, [1, 8]), (hole_rim(), 1.0, [3])):
        cut = WaveSlider(b).solve(width, exact=exact, destructive=True)
        assert _break_legs(cut) == [({b.chain[k]}, {b.chain[k]}) for k in cut_vertices]


@pytest.mark.parametrize("exact", [False, True])
def test_a_leg_that_would_cross_an_edge_is_left_out(exact):
    # u_wall past 0.5: c1's right end has slid past hole corner a onto a-b, so the leg there runs through a; past
    # 0.636396 its left end has passed d onto d-c, and the leg crosses a-d. notch_spike: B's leg to the right end, on
    # the spike's right side T-R, would cross the notch; that end keeps the connector from C, the group member it holds.
    b = u_wall()
    w = WaveSlider(b)
    assert _break_legs(w.solve(0.55, exact=exact, destructive=True)) == [({b.chain[1]}, set()), (set(), {b.chain[8]})]
    assert _break_legs(w.solve(0.75, exact=exact, destructive=True)) == [(set(), set()), (set(), set())]
    b = notch_spike()
    for width in (1.1, 1.4, 2.0):
        cut = WaveSlider(b).solve(width, exact=exact, destructive=True)
        assert _break_legs(cut) == [({b.chain[1]}, {b.chain[2]})]


def test_end_shoots_on_to_a_perpendicular_edge():
    # shoot_strip(): the start's end wall is one edge long; past it every onward edge turns 90 degrees, and the offset
    # line crosses a vertical edge 1.5 further on. (Today's clamp is the wall's end, 1, by the anchor snap: 1.000002.)
    b = shoot_strip()
    w = WaveSlider(b)
    assert w.limit() == pytest.approx(1.0, abs=1e-5)                 # today's clamp at the wall's end
    cut = w.solve(1.5, destructive=True)
    assert cut.points[0].kind == "edge" and cut.points[0].edge == shoot_strip_landing_edge()


def test_shoot_angle_decides_which_edge_is_perpendicular_enough():
    b = shoot_strip(slant_deg=40.0)                                 # the first crossed edge leans 40 off perpendicular
    b.angles = Angles(shoot=math.radians(30))
    first = WaveSlider(b).solve(1.5, destructive=True).points[0].edge
    b.angles = Angles(shoot=math.radians(45))
    assert WaveSlider(b).solve(1.5, destructive=True).points[0].edge != first


def test_end_with_nothing_to_land_on_stays_on_its_wall_vertex():
    b = shoot_strip(no_landing=True)
    cut = WaveSlider(b).solve(1.5, destructive=True)
    assert cut.points[0].kind == "vert" and cut.points[0].vert == shoot_strip_wall_end()


@pytest.mark.parametrize("exact", [False, True])
def test_a_shot_end_jumps_at_one_width_and_keeps_the_width(exact):
    # shoot_strip: the start's wall ends at v at 1 (and the snap, 1.000002): it shoots on along y = 1 to (-1.5, 1) on
    # b1-t1 (``wall_end``, data (slot 0, the landing edge)). Its neighbour c1 keeps up with that line: it waits on v
    # till twice the snap past where its wall gave out (w = 1.000004), where its segment, on y = w from c1's point to
    # the landing, clears v by that, and jumps there, in one event with the same data; from there it lies on y = w,
    # the width from the chain.
    b = shoot_strip()
    w = WaveSlider(b)
    shot, jump = (e for e in w._wave(exact) if e.kind == "wall_end" and e.width < 2.0)
    assert shot.data == jump.data == (0, shoot_strip_landing_edge())
    assert shot.width == pytest.approx(1.000002, abs=1e-9) and jump.width == pytest.approx(1.000004, abs=1e-9)
    lo, hi = (w.solve(jump.width + d, exact=exact, destructive=True) for d in (-1e-7, 1e-7))
    assert lo.points[0].kind == "vert" and lo.points[0].vert == shoot_strip_wall_end()
    assert hi.points[0].edge == shoot_strip_landing_edge() and hi.points[0].co[:2] == pytest.approx((-1.5, 1.0), abs=1e-5)
    for width in (1.1, 1.5, 2.5, 2.9):
        p = w.solve(width, exact=exact, destructive=True).points[0]
        assert p.edge == shoot_strip_landing_edge() and p.co[:2] == pytest.approx((-1.5, width), abs=1e-9)


def test_an_end_left_on_its_wall_vertex_lets_the_loop_go_on():
    # shoot_strip(no_landing=True): the start stays on v, while the rest of the loop goes on up to F1's top at 3 (the
    # inner vertices cut there, and the end's wall ends there too): nothing clamps it at 1.
    b = shoot_strip(no_landing=True)
    w = WaveSlider(b)
    assert w.limit(destructive=True) > 2.9
    assert next(e for e in w._wave(False) if e.kind == "wall_end").data == (0, None)
    for width in (1.2, 2.0, 2.9):
        cut = w.solve(width, destructive=True)
        assert not cut.clamped and cut.points[0].vert == shoot_strip_wall_end()
        assert _point(cut, 1)[:2] == pytest.approx((1.0, width), abs=1e-9)


def test_a_line_through_a_vertex_lands_on_it():
    # shoot_bevel: the start's offset line y = 1 runs on along v-w and through w exactly, where the rung w-tw rises
    # perpendicular to it. The end lands on the vertex w, at every 1e-9 tilt or turn of the mesh too (the line then
    # passes w within the anchor snap), and slides up w-tw.
    b = shoot_bevel()
    others = [tilted(b, 1e-9), tilted(b, -1e-9), rotated(b, 1e-9), rotated(b, -1e-9)]
    for other in [b, *others, *(jittered(b, seed) for seed in range(20))]:  # and 1e-9 of noise on every vertex
        w = WaveSlider(other)
        shot = next(e for e in w._wave(False) if e.kind == "wall_end")
        assert shot.data == (0, 8)                                     # landed on the vertex w
        assert w.solve(1.5, destructive=True).points[0].edge == (8, 9)  # sliding up w-tw


def test_an_end_on_the_open_border_stays():
    # An end whose point lies on an open edge, or a vertex of the open border, has landed: where its wall gives out it
    # stays, whatever its line would cross. jittered_shoot_strip(0): chain[3] cuts on the open top edge 7-9 at 2.975846;
    # its right end's wall runs level there, and it once shot on along that same edge, across the piece beside it.
    # jittered_shoot_strip(1): the start's second wall, b1-t1, ends at t1, on the open top; it once shot on into F2,
    # and its segment then passed through t1, out of the band: D stopped right there, at 2.701916.
    w = WaveSlider(jittered_shoot_strip(0))
    lim = w.limit(destructive=True)
    assert [d for d in _shots(w, False, lim) if d[0] == (False, 3, True)] == [((False, 3, True), None)]
    w = WaveSlider(jittered_shoot_strip(1))
    lim = w.limit(destructive=True)
    assert [d for d in _shots(w, False, lim) if d[0] == 0] == [(0, (8, 9)), (0, (8, 9)), (0, None)]  # waits, jumps
    assert lim > 2.701916 + 0.05


@pytest.mark.parametrize(("seed", "exact"), [(1, False), (31, False), (15, True), (1, True)])
def test_a_landing_keeps_the_end_width_error(seed, exact):
    # chain_jittered_u(seed, 0.3, 0.3): an end that lands keeps the width error it had where its wall gave out: in
    # default mode it lies on the line at the width less that error from its chain edge's, as an end's group does past
    # a fold; exact mode keeps it within EXACT_TOL. Shooting along a segment's rising extension once added up to 0.88.
    # A fold while it waits keeps that error too (seed 1, default mode; see test_a_fold_keeps_a_waiting_end_landing).
    w = WaveSlider(chain_jittered_u(seed, 0.3, 0.3))
    lim = w.limit(exact=exact, destructive=True)
    last, landed = {}, 0
    for i, slot, g in w._wave_of(exact).groups:
        e = w._wave(exact)[i]
        if e.kind == "wall_end" and e.data[0] == slot and e.data[1] is not None and g.width <= lim:
            landed += 1
            before = last[slot].error if slot in last else 0.0
            assert g.error == pytest.approx(before, abs=2e-6)
            if exact:
                assert abs(g.error) <= EXACT_TOL * g.width
        last[slot] = g
    assert landed


@pytest.mark.parametrize(("make", "jump", "limit"), [(lambda: jittered_u(30, 0.3, 0.6), 2.704604, 3.817265),
                                                     (lambda: chain_jittered_u(15, 0.3, 0.3), 2.788518, 3.901493)])
def test_a_waiting_end_is_never_at_rest(make, jump, limit):                  # anti-goal 4
    # Both at about 2.7: the end ending the chain shoots on to edge 36-44 while every other end stays put already, and
    # waits for its neighbour, a leaning rail vertex, to let its segment clear its point. Nothing of the loop moves
    # meanwhile, but the end is not at rest: its landing moves on, and the segment clears at ``jump``. The wave once
    # stopped right at the shot (2.656541, 2.716940), as if the loop had come to rest.
    w = WaveSlider(make())
    for exact in (False, True):
        shot, landed = (e for e in w._wave(exact) if e.kind == "wall_end" and e.data == (1, (36, 44)))
        assert landed.width == pytest.approx(jump, abs=1e-6) and landed.width > shot.width + 0.04
        assert w.limit(exact=exact, destructive=True) == pytest.approx(limit, abs=1e-6)
        assert _gaps(w, 200, exact) == []


def test_a_fold_keeps_a_waiting_end_landing():
    # chain_jittered_u(1, 0.3, 0.3), default mode: the start shoots on to edge 34-42 at 1.689027 with no width error
    # (e0 = 0) and waits on vertex 35 for its neighbour, a leaning rail vertex. At 1.704061 segment 4 folds into it: its
    # remaining segment starts on chain edge 5 now. It waits on for the same landing and keeps e0: its group there lies
    # at the width less e0 from edge 5's line, which comes level with vertex 35 (1.719095 from that line) at 1.719095,
    # and the segment clears 35 twice the snap past it: it jumps at 1.719099. From there it lies at the width from edge
    # 5's line. It once dropped the landing at the fold and stood on 35 to the limit, 1.29 short of its width; and once
    # measured its error again at the fold, -0.1335 (7.8% of the width).
    b = chain_jittered_u(1, 0.3, 0.3)
    w = WaveSlider(b)
    shots = [(round(e.width, 6), e.data) for e in w._wave(False) if e.kind == "wall_end" and e.data[0] == 0]
    assert shots[:2] == [(1.689027, (0, (34, 42))), (1.719099, (0, (34, 42)))]
    fold = next(e.width for e in w._wave(False) if e.kind == "fold" and e.data == (4,))
    assert fold == pytest.approx(1.704061, abs=1e-6)
    for width in (1.7, 1.705, 1.719):                                        # waiting, across the fold
        assert w.solve(width, destructive=True).points[0].vert == 35
    for width in (1.72, 1.9, 2.2, 2.5, 2.8):
        group = w._end_groups(False, width)[0]
        assert group.edge == 5 and not group.stuck and group.error == pytest.approx(0.0, abs=2e-6)
        assert _line_distance(b, 5, _point(w.solve(width, destructive=True), 0)) == pytest.approx(width, abs=1e-6)
    assert w.limit(destructive=True) == pytest.approx(3.078043, abs=1e-6)
    assert _gaps(w, 300) == []


@pytest.mark.parametrize("make", [shoot_strip, lambda: shoot_strip(slant_deg=40.0), lambda: jittered_grid(14),
                                  lambda: jittered_grid(26)])
def test_a_jump_ignores_a_1e9_jitter(make):                                   # anti-goal 3
    # Where the neighbour keeps up with the end's line, the end jumps twice the snap past where its wall gave out: a
    # width the mesh gives, which 1e-9 of noise moves by no more than that. It once jumped where its segment cleared its
    # point by that much, which these ends' segments do at about the shot already: noise decided whether the end
    # jumped at the shot or 2e-6 later, on its old vertex or a whole edge away meanwhile.
    b = make()
    w = WaveSlider(b)
    lim = w.limit(destructive=True)
    want = [(e.width, e.data) for e in w._wave(False) if e.kind == "wall_end" and e.width <= lim]
    for seed in (7000, 7001):
        got = [(e.width, e.data) for e in WaveSlider(jittered(b, seed))._wave(False) if e.kind == "wall_end"]
        assert [d for _, d in got[:len(want)]] == [d for _, d in want]
        assert all(abs(x - y) <= 1e-6 for (x, _), (y, _) in zip(got, want))


def test_destructive_is_empty_at_tiny_widths_and_without_end_edges():       # Review Focus 5
    assert WaveSlider(u_in_grid()).solve(1e-9, destructive=True).points == []
    WaveSlider(end_slide()).solve(0.3, destructive=True)                      # no end edges: no exception


# --- Final states, piece by piece ---------------------------------------------------------------------------------


def vertex_point(band, v):
    # Mesh vertex ``v`` of ``band`` as a surface point, held by the first face (by id) that has it.
    return SurfacePoint(kind="vert", face=next(f for f, loop in sorted(band.faces.items()) if v in loop),
                        co=band.verts[v], vert=v)


def _runs(cut):
    # The cut's points piece by piece, split at its breaks: [(x, y), ...] per run.
    bounds = [0, *(i for i in cut.breaks if i), len(cut.points)]
    return [[p.co[:2] for p in cut.points[a:b]] for a, b in zip(bounds, bounds[1:])]


def test_closed_square_collapses_to_an_apex():
    b = square_in_grid()                     # closed 2x2 square chain, side inward, in a 6x6 grid of quads
    w = WaveSlider(b)
    # The apex is the loop's final state (used up, the wave complete), held from below its fold at 1 by where the sides
    # are 4 welds apart (they close at 2 per unit of width): 1 - 2 welds.
    assert w._used_up(False) is not None and w._wave_of(False).complete
    assert w.limit(destructive=True) == pytest.approx(1.0 - 2.0 * w._weld, abs=1e-9)
    cut = w.solve(5.0, destructive=True)
    assert cut.clamped and len(set(cut.anchors)) == 1 and len(cut.points) == 1


def test_open_piece_pressed_onto_its_wall_leaves_wall_points_only():
    # u_wall past its limit, 2.9 / sqrt2 (see u_wall), is three pieces. c0's and c8's are pressed onto their walls:
    # each leaves its own end's point on the mouth, (2.9, 4) and (3.1, 4), and the hole corner its other end stays on,
    # c and c', with a break between them. The middle one closed into a ridge at 2 and keeps it, joined: b - (3, 2) -
    # b', c2..c7 on (3, 2). Breaks fall only between points pressed onto a wall. It finished first: at 2.03 it is in
    # its final state while c0's start still slides along the mouth, at (sqrt2 w, 4).
    b = u_wall()
    w = WaveSlider(b)
    cut = w.solve(w.limit(destructive=True) + 1.0, destructive=True)
    assert cut.clamped
    assert _runs(cut) == [[pytest.approx((2.9, 4.0), abs=1e-9)], [pytest.approx((2.5, 3.6), abs=1e-9)],
                          [pytest.approx(p, abs=1e-9) for p in ((2.5, 3.0), (3.0, 2.0), (3.5, 3.0))],
                          [pytest.approx((3.5, 3.6), abs=1e-9)], [pytest.approx((3.1, 4.0), abs=1e-9)]]
    assert all(cut.points[i].kind in ("edge", "vert") for i in (0, 1, 2, 4, 5, 6))   # on the walls
    assert cut.anchors == [0, 1, 3, 3, 3, 3, 3, 3, 4, 6]
    runs = _runs(w.solve(2.03, destructive=True))
    assert runs[1] == [pytest.approx(p, abs=1e-9) for p in ((2.5, 3.0), (3.0, 2.0), (3.5, 3.0))]
    assert runs[0][0] == pytest.approx((math.sqrt(2.0) * 2.03, 4.0), abs=1e-9)


def test_pieces_finish_one_by_one():
    b = dumbbell()                           # closed chain round two 4x4 rooms joined by a 1-wide neck; it splits
    w = WaveSlider(b)                        # at the neck first, then the small room's piece collapses first
    small, big = dumbbell_room_limits()
    # The big room's apex holds from where its sides are 4 welds apart (4 float32 steps at 12, 5.7e-6, each), below
    # its last fold.
    assert 0.0 < big - w.limit(destructive=True) <= 4.0 * w._weld + 1e-12
    cut = w.solve((small + big) / 2, destructive=True)
    assert not cut.clamped


@pytest.mark.parametrize(("make", "v", "width"), [
    (fanned_u, 36, 2.0),                                  # past merges
    (hole_rim, 25, math.sqrt(2.0)),                       # past a cut
    (shoot_strip, 9, 3.0 - _REST_HOLD)])                  # past a landing
def test_snap_reaches_a_vertex_past_a_merge(make, v, width):                 # Review Focus 2
    # fanned_u: vertex 36 is the grid's (4, 4), fanned to (4, 3.28); the right arm x = 6 is not fanned, and its offset
    # line x = 6 - w reaches x = 4 at 2: past the folds from 0.454545 on and past C's limit, the end fold at 1.875.
    # hole_rim: vertex 25 is (1, 3). L cuts on the border at 1 / sqrt2; its right end slides down x = 0 on L-B's offset
    # line x + y = 6 - sqrt2 w, which at sqrt2 runs through (1, 3), from (0, 4) to B's point (2, 2). shoot_strip: vertex
    # 9 is t1 (-1.5, 3); the start lands on b1-t1 past 1.000004 and slides up it on y = w onto t1 at 3, where the loop
    # comes to rest on it, its final state, held from a hair below (``_REST_HOLD``): the limit. The snap once bisected
    # over the whole range, across cuts and jumps, and missed the last two.
    b = make()
    w = WaveSlider(b)
    target = vertex_point(b, v)
    got = w.snap_width(target, destructive=True)
    assert got is not None and got > w.limit(collapse=True) and got == pytest.approx(width, abs=1e-6)
    assert any(p.kind == "vert" and p.vert == target.vert for p in w.solve(got, destructive=True).points)


def _l_ngon():
    # One L-shaped face, its outline the closed chain, the side inward: (0,0) (4,0) (4,1) (1,1) (1,3) (0,3), arms 1 wide.
    # Each corner runs in along its bisector; at 1/2 the arms' sides meet on their midlines y = 1/2 and x = 1/2: the
    # ends' groups (4,0)-(4,1) and (1,3)-(0,3) close (their outer edges run opposite ways), (0,0) and the reflex (1,1)
    # meet at the knee (1/2, 1/2). The skeleton tree is (7/2, 1/2) - (1/2, 1/2) - (1/2, 5/2).
    pts = {"a": (0, 0), "b": (4, 0), "c": (4, 1), "d": (1, 1), "e": (1, 3), "f": (0, 3)}
    return _flat_band(pts, [tuple(pts)], list(pts), [0] * 6, closed=True)


def test_a_non_convex_ring_ends_as_its_skeleton_tree():
    # The closed loop's final state is the walk round its tree (the Q3 ruling), knee repeated: held from the anchor
    # snap below 1/2, so the thin L just short of it, whose sides lie a few 1e-6 apart, is not the cut there.
    w = WaveSlider(_l_ngon())
    used = w._used_up(False)
    assert used is not None and used.data[0] is None and used.width == pytest.approx(0.5, abs=1e-12)
    lim = w.limit(destructive=True)
    assert lim == pytest.approx(0.5 - _ANCHOR_SNAP_TOL, abs=1e-12)
    for width in (lim, lim + 1.0):
        cut = w.solve(width, destructive=True)
        assert [p.co[:2] for p in cut.points] == [pytest.approx(p, abs=1e-12) for p in
                                                  ((0.5, 0.5), (3.5, 0.5), (0.5, 0.5), (0.5, 2.5))]
        assert cut.anchors == [0, 1, 1, 2, 3, 3] and cut.clamped == (width > lim)


def _ngon_band(pts):
    keys = [chr(97 + i) for i in range(len(pts))]
    return _flat_band(dict(zip(keys, pts)), [tuple(keys)], keys, [0] * len(pts), closed=True)


@pytest.mark.parametrize(("make", "room"), [
    # Arms 1 and 3 wide: the reflex corner (3, 1) runs in to (3 - w, 1 - w) and reaches the bottom's offset line y = w
    # at 1/2, at (2.5, 0.5), as the narrow arm's sides meet all along it. The arm encloses nothing there: it merges
    # into the 3 x 3 room's ring, a group at the meet of the bottom and x = 3 - w, and the room goes on to its inradius.
    (lambda: _ngon_band([(0, 0), (6, 0), (6, 1), (3, 1), (3, 3), (0, 3)]), 1.5),
    # A racket, one face: the handle's corners (4, 1.5) and (4, 2.5) meet at (3.5, 2) at 1/2, as the handle's sides
    # do; the handle merges into the 4 x 4 room's ring (a group on x = 4 - w, its outer edges parallel), which goes on.
    (lambda: _ngon_band([(0, 0), (4, 0), (4, 1.5), (7, 1.5), (7, 2.5), (4, 2.5), (4, 4), (0, 4)]), 2.0),
    (grid_racket, 1.5)])                                     # the same on unit quads: a 3 x 3 room, x and y in [1, 4]
def test_a_branch_closing_leaves_its_room_going_on(make, room):          # carry 5
    # The branch is that branch's final state while the enclosing ring goes on to its own collapse: the room's
    # inradius. It once stopped the wave at 1/2 (the loop then ran back across itself there).
    w = WaveSlider(make())
    for exact in (False, True):
        touch = [e for e in w._wave(exact) if e.kind == "contact"]
        assert touch and touch[0].width == pytest.approx(0.5, abs=1e-9)
        lim = w.limit(exact=exact, destructive=True)
        assert 0.0 < room - lim <= 4.0 * w._weld + 1e-12  # its apex holds from where its sides are 4 welds apart
        for width in (0.75 * lim, lim, lim + 1.0):
            cut = w.solve(width, exact=exact, destructive=True)
            assert cut.clamped == (width > lim) and not cut.breaks and None not in cut.anchors


@pytest.mark.parametrize(("make", "seed", "amplitude", "room"), [
    (racket_ngon, 15, 5e-4, 2.0),        # the handle's tip folds first and closes; no contact ever comes
    (grid_racket, 0, 0.03, 1.5),         # a ring split off at 1.0076 stopped where it started
    (grid_racket, 16, 0.03, 1.5),
    (dumbbell, 4, 0.03, 3.0),            # stopped at 2.0068 (seed 7, the same class, trimmed for time)
    (asymmetric_l_ngon, 0, 0.03, 1.5)])
def test_a_jittered_branch_never_stops_the_wave(make, seed, amplitude, room):            # anti-goal 4
    # Every vertex moved by up to ``amplitude``: whichever comes first, the branch's closing fold or the room's contact
    # across its mouth, the branch merges into the room's ring (a fold closing its group zips the branch up, as the
    # contact would merge it), and the room goes on to its own collapse, within the jitter of its inradius. No hidden
    # stop: the wave completes.
    b = xy_jittered(make(), seed, amplitude)
    for exact in (False, True):
        w = WaveSlider(b)
        assert w.limit(exact=exact, destructive=True) > room - 4.0 * amplitude - 1e-3, exact
        assert w._wave_of(exact).complete, exact


@pytest.mark.parametrize(("make", "room"), [(dumbbell_hole, 2.0), (racket_hole, 1.0)])
def test_a_ring_reaching_a_hole_is_cut_and_finishes(make, room):
    # A ring the loop split into (or the room past its handle) reaches a hole's open border: it is cut there, as any
    # closed loop is, and its pieces are pressed onto the hole's walls. The wave completes; no width below fails.
    b = make()
    for exact in (False, True):
        w = WaveSlider(b)
        lim = w.limit(exact=exact, destructive=True)
        assert w._wave_of(exact).complete and lim == pytest.approx(room, abs=1e-5)
        for i in range(1, 81):
            w.solve(lim * i / 80, exact=exact, destructive=True)


def test_dumbbell_splits_at_the_neck():
    b = dumbbell()
    w = WaveSlider(b)
    neck = dumbbell_neck_width()                                 # 0.5: half the neck's width, derived in the fixture
    assert len(w.solve(neck - 0.01, destructive=True).breaks) == 0
    after = w.solve(neck + 0.01, destructive=True)
    assert len(after.breaks) == 2                                # two closed pieces: one break each


def test_dumbbell_rings_shrink_each_to_its_apex():
    # Past the neck each room's ring shrinks as a square does: the small one to an apex at its centre (2, 3) at 2, and
    # it keeps it while the big one goes on to its own at (9, 3) at 3. Every chain vertex anchors on one ring, and both
    # rings close on themselves (``Cut.rings``). Both modes agree: every chain vertex is a miter or a straight one.
    b = dumbbell()
    small, big = dumbbell_room_limits()
    for exact in (False, True):
        w = WaveSlider(b)
        wave = w._wave_of(exact)
        assert len(wave.parts) == 2 and wave.complete
        assert [e.kind for e in wave.events] == ["contact", "contact"]
        cut = w.solve((small + big) / 2, exact=exact, destructive=True)
        assert cut.rings == cut.breaks and len(cut.breaks) == 2 and None not in cut.anchors
        apex = cut.points[:cut.breaks[1]]
        assert len(apex) == 1 and apex[0].co[:2] == pytest.approx((2.0, 3.0), abs=1e-6)
        cut = w.solve(big + 1.0, exact=exact, destructive=True)
        assert cut.clamped and len(cut.points) == 2
        assert [p.co[:2] for p in cut.points] == [pytest.approx((2.0, 3.0), abs=1e-6), pytest.approx((9.0, 3.0), abs=1e-6)]


def test_rings_keep_their_own_contact_records():
    # Each ring the loop splits into starts with the loop's records of the groups a contact made, or that run parallel,
    # and keeps what it notes from there on to itself: no ring is handed another's point for a group of the same chain
    # vertices (they were one dict, shared by the loop and every ring).
    w = WaveSlider(dumbbell())
    for exact in (False, True):
        w.limit(exact=exact, destructive=True)
        rings = w._wave_of(exact).parts
        assert len(rings) == 2
        for records in ("_touched", "_parallels"):
            mine = [getattr(s, records)[exact] for s in (w, *rings)]
            assert len({id(r) for r in mine}) == 3, records
            assert all(set(getattr(w, records)[exact]) <= set(r) for r in mine[1:]), records


@pytest.mark.parametrize(("make", "seed", "amplitude"), [
    (asymmetric_l_ngon, 1, 5e-4), (racket_ngon, 13, 5e-4), (racket_ngon, 15, 5e-3), (racket_ngon, 3, 5e-4)])
def test_a_fold_holds_only_at_noise_scale(make, seed, amplitude):
    # The width stays honest: a fold takes over a hair short of its width, never more than ``_THIN`` welds at the
    # rate its segments close. A near-hairpin's V held by its arms (1 / sine) once parked its group on its fold point
    # from a quarter of the width short of it, its arm tips 0.2 off their offsets. Every fold, the rings' too, holds
    # from at most 1e-4 short of its width on these jittered contact bands (as before the arms hold).
    w = WaveSlider(xy_jittered(make(), seed, amplitude))
    todo = [w]
    while todo:
        s = todo.pop()
        wave = s._wave_of(True)
        for e, since in zip(wave.events, wave.since):
            if e.kind == "fold":
                assert e.width - since <= 1e-4, (e.width, e.width - since)
        todo += wave.parts


def _crossing_pieces(cut, weld):
    """Pairs of the cut's segments (each piece's, a ring's closing one too) that cross, in the plane, away from their
    ends (within ``weld`` of an end of the other they touch where the bridge welds them)."""
    segs = []
    for piece, ring in _pieces_of(cut):
        pts = [cut.points[i].co[:2] for i in piece]
        pairs = list(zip(pts, pts[1:])) + ([(pts[-1], pts[0])] if ring and len(pts) > 2 else [])
        segs += [(p, q) for p, q in pairs if math.dist(p, q) > weld]

    def side(a, b, c):
        return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])

    out = 0
    for i in range(len(segs)):
        for j in range(i + 1, len(segs)):
            (p, q), (r, s) = segs[i], segs[j]
            if min(math.dist(x, y) for x in (p, q) for y in (r, s)) <= weld:
                continue
            d1, d2, d3, d4 = side(p, q, r), side(p, q, s), side(r, s, p), side(r, s, q)
            if d1 * d2 < 0.0 and d3 * d4 < 0.0:
                out += 1
    return out


def _pieces_of(cut):
    """(point indices, closes on itself) of each piece of a closed loop's cut."""
    n = len(cut.points)
    if not cut.breaks:
        return [(list(range(n)), True)]
    br = sorted(cut.breaks)
    out = [(list(range(a, b)), a in cut.rings) for a, b in zip(br, br[1:])]
    return out + [(list(range(br[-1], n)) + list(range(br[0])), br[-1] in cut.rings)]


def test_a_spike_past_its_contact_stays_on_it():
    # The jittered dumbbell's loop touches itself across the neck with a thin spike: just past the contact the spike's
    # sides would meet a hair beyond the touch, across the other ring, and that meet point comes back at many times the
    # width's rate. The spike's group stays on the contact point until its meet point has come back past it, so no
    # cut just past the split crosses the other ring (it did by 1.8e-4, refused by the bridge).
    w = WaveSlider(xy_jittered(dumbbell(), 2, 0.03))
    todo, contacts = [w], []
    while todo:
        s = todo.pop()
        contacts += [e.width for e in s._wave_of(False).events if e.kind == "contact"]
        todo += s._wave_of(False).parts
    assert contacts
    for c in contacts:
        for d in (0.0, 1e-6):
            assert _crossing_pieces(w.solve(c + d, destructive=True), w._weld) == 0, (c, d)


def _fold_widths(w, exact):
    """The widths of the folds of the wave and of every ring it splits into."""
    todo, out = [w], []
    while todo:
        s = todo.pop()
        out += [e.width for e in s._wave_of(exact).events if e.kind == "fold"]
        todo += s._wave_of(exact).parts
    return sorted(out)


@pytest.mark.parametrize(("seed", "exact", "near"), [(7, False, 0.5038), (1, False, 1.9601), (1, True, 1.9601),
                                                     (7, False, 1.9674), (7, True, 1.9674)])
def test_no_cut_round_a_fold_crosses_itself(seed, exact, near):
    # grid_racket jittered(7, 0.03), default mode: the handle's ring folds at 0.50382 into a near-hairpin V whose sides'
    # meet point, with default mode's width errors on them, lay 1.9 back from the fold, across the room's ring: the V
    # leapt there at the fold. It starts from its fold point and stays there until its meet point comes back past it.
    # The jittered dumbbells' small rings end as slivers whose long sides close on each other a hair before their
    # short ends fold (seeds 1 and 7, 1e-5 short of the fold): a vertex that is not reflex reaches the far side, a
    # contact, and the sliver splits there as any loop does.
    w = WaveSlider(grid_racket() if near < 1.0 else dumbbell())
    w = WaveSlider(xy_jittered(w.band, seed, 0.03))
    folds = [f for f in _fold_widths(w, exact) if abs(f - near) < 2e-4]
    assert folds
    for f in folds:
        for d in (-1e-4, -1e-5, -1e-6, 0.0, 1e-6, 1e-5, 1e-4):
            cut = w._solve(f + d, exact, True, destructive=True)
            assert _crossing_pieces(cut, w._weld) == 0, (f, d)


def _shift_keys(w, exact):
    """The near-hairpin V's of the wave and its rings whose fold offset is carried (``_fold_points``)."""
    todo, out = [w], set()
    w._wave_of(exact)
    while todo:
        s = todo.pop()
        out |= set(s._shifts[exact])
        todo += s._wave_of(exact).parts
    return out


@pytest.mark.parametrize(("make", "seed"), [(grid_racket, 7), (dumbbell, 5), (dumbbell, 1)])
@pytest.mark.parametrize("tilt", [1e-9, -1e-9])
def test_a_tilt_does_not_change_which_vs_are_near_hairpins(make, seed, tilt):
    # Anti-goal 3 for the near-hairpin exception: a 1e-9 tilt of the chain's second vertex leaves the same V's carrying
    # their fold offsets, in both modes (``_HAIRPIN_SIN`` is far from these V's sines, and noise does not decide it).
    band = xy_jittered(make(), seed, 0.03)
    (ax, ay, _), (bx, by, bz) = band.verts[band.chain[0]], band.verts[band.chain[1]]
    d = math.hypot(bx - ax, by - ay)
    verts = dict(band.verts)
    verts[band.chain[1]] = (bx - tilt * (by - ay) / d, by + tilt * (bx - ax) / d, bz)
    tilted = dataclasses.replace(band, verts=verts)
    for exact in (False, True):
        keys = _shift_keys(WaveSlider(band), exact)
        assert _shift_keys(WaveSlider(tilted), exact) == keys
        if make is grid_racket:
            assert keys


@pytest.mark.parametrize("make", [lambda: chain_jittered_u(24, 0.25, 0.05, 0.8), lambda: jittered_u(30, 0.4),
                                  lambda: jittered_u(12, 0.4), lambda: chain_jittered_u(1), fanned_u, bumped_arm])
def test_no_cut_carries_a_segment_within_the_weld(make):
    # In D the core takes the bridge's weld (1e-6, or 4 float32 steps at the band's largest coordinate) as the distance
    # at which points are one (Q1): a fold holds from where its segments are that short, a segment that short past a
    # fold joins it, and the solve keeps no two neighbouring points that close. Checked just below every fold, where
    # cuts once carried edges of 2e-7 to 9e-7.
    b = make()
    w = WaveSlider(b)
    weld = max(1e-6, 4.0 * 2.0 ** -23 * max(abs(c) for p in b.verts.values() for c in p))
    for exact in (False, True):
        lim = w.limit(exact=exact, destructive=True)
        folds = [e.width for e in w._wave(exact) if e.kind == "fold"]
        for width in (x - d for x in folds for d in (3e-7, 1e-7, 1e-8, 3e-6)):
            if not 0.0 < width <= lim:
                continue
            cut = w.solve(width, exact=exact, destructive=True)
            gaps = [math.dist(cut.points[i - 1].co, cut.points[i].co) for i in range(1, len(cut.points))
                    if i not in cut.breaks]
            assert min(gaps, default=1.0) > weld, (exact, width, min(gaps))


def test_a_final_state_holds_each_place_once():
    # Where pieces at rest leave lone wall points, a cut's two ends, or a crossing and an end of another kind, on one
    # place are one point: no break between two copies of it (jittered_grid's top border; it once held 51 places twice).
    for seed in (0, 8):
        w = WaveSlider(jittered_grid(seed))
        cut = w.solve(w.limit(destructive=True) + 1.0, destructive=True)
        assert all(math.dist(cut.points[i - 1].co, cut.points[i].co) > _ANCHOR_SNAP_TOL for i in cut.breaks if i)
        assert len({tuple(round(c, 5) for c in p.co) for p in cut.points}) == len(cut.points)


@pytest.mark.parametrize(("seed", "v"), [(0, 9), (1, 7), (2, 7)])
def test_snap_reaches_a_vertex_of_the_final_state(seed, v):
    # jittered_shoot_strip(seed): the loop comes to rest with an end on vertex ``v``; the offset there, between lone
    # wall points, says nothing, but the final state holds the vertex: it is reached at the limit.
    b = jittered_shoot_strip(seed)
    for exact in (False, True):
        w = WaveSlider(b)
        assert w.snap_width(vertex_point(b, v), exact=exact, destructive=True) == w.limit(exact=exact, destructive=True)


@pytest.mark.parametrize("seed", [22, 36])
def test_a_hairpin_ridge_is_its_pieces_final_state(seed):
    # jittered_u(seed, 0.4) keeps u_in_grid's chain: its arms' offset lines x = 1 + w and x = 6 - w meet at 2.5, where
    # the U's bottom groups, on y = 1 + w, meet at (3.5, 3.5). Their outer edges, the arms, run opposite ways (a
    # hairpin): the piece closes into a ridge from there up to its two ends, on the jittered mouth at x = 3.5. That is
    # its final state, joined, held from the anchor snap below: not a copy of the loop a hair before it (two points 0
    # apart at (3.5, 3.5)). It once stopped the wave there.
    w = WaveSlider(jittered_u(seed, 0.4))
    used = w._used_up(False)
    assert used.data == (None, 0, 11) and used.width == pytest.approx(2.5, abs=1e-9)
    assert w.limit(destructive=True) == pytest.approx(2.5 - _ANCHOR_SNAP_TOL, abs=1e-9)
    cut = w.solve(3.0, destructive=True)
    assert cut.clamped and cut.breaks == () and len(cut.points) == 3
    start, ridge, end = (p.co[:2] for p in cut.points)
    assert ridge == pytest.approx((3.5, 3.5), abs=1e-9)
    assert start[0] == pytest.approx(3.5, abs=1e-9) and end[0] == pytest.approx(3.5, abs=1e-9)
    assert set(cut.anchors[2:10]) == {1}


@pytest.mark.parametrize(("seed", "exact", "fold"), [(30, True, 0.866131), (20, False, 1.615109), (20, True, 1.642966),
                                                     (31, True, 1.650188)])
def test_a_group_turning_past_a_hairpin_closes_into_a_ridge(seed, exact, fold):
    # chain_jittered_u(seed, 0.3, 0.3): at ``fold`` a fold makes a group whose outer chain edges turn by more than half
    # a turn. Its edges' meet point runs back over the group's own members, into ground the loop has swept already,
    # and on into the chain, where its cut was refused and the wave stopped (0.901131, 2.382587, 2.479289, 2.247211).
    # The group's sides have closed onto each other at the fold: the piece closes into a ridge there, its final state.
    # (C's loop past such a fold is folded over itself: its two ends pass each other on the mouth, and its area turns
    # negative.)
    w = WaveSlider(chain_jittered_u(seed, 0.3, 0.3))
    used = w._used_up(exact)
    assert used is not None and used.data[0] is None and used.width == pytest.approx(fold, abs=1e-6)
    assert w.limit(exact=exact, destructive=True) == pytest.approx(used.width - _ANCHOR_SNAP_TOL, abs=1e-9)
    assert not any(e.kind == "wall_hit" for e in w._wave(exact))
    assert _gaps(w, 200, exact) == []


@pytest.mark.parametrize("make", [lambda: jittered_grid(0), lambda: jittered_grid(8), u_wall, hole_rim,
                                  lambda: jittered_u(22, 0.4), lambda: jittered_hole_rim(1),
                                  bumped_arm,                      # c1 within the weld of its group past the fold
                                  dumbbell, grid_racket])          # where the loop touches itself
def test_final_state_ignores_per_vertex_jitter(make):                        # anti-goal 3
    # The final cut is one whatever order float noise puts simultaneous events in: jittered_grid's whole straight chain
    # reaches its parallel top border at once, at 8. Where the loop comes to rest, each piece keeps the points it rests
    # on, and leaves those it rests on along an open edge with breaks between them. It once was the loop a hair short
    # of the border, whose points noise snapped onto the border or not, 2e-6 apart.
    b = make()
    for exact in (False, True):
        w = WaveSlider(b)
        want = w.solve(w.limit(exact=exact, destructive=True) + 1.0, exact=exact, destructive=True)
        for seed in (7000, 7001):
            w = WaveSlider(jittered(b, seed))
            got = w.solve(w.limit(exact=exact, destructive=True) + 1.0, exact=exact, destructive=True)
            assert (len(got.points), got.breaks, got.anchors) == (len(want.points), want.breaks, want.anchors)
            assert max(math.dist(p.co, q.co) for p, q in zip(got.points, want.points)) <= 1e-6


# (grids, modes) per family. Exact mode only differs from default where the chain bends (chain_jittered_u): elsewhere
# every rail is exact, so default mode alone covers it.
SWEEP = {
    "jittered_grid": (lambda: [jittered_grid(seed) for seed in range(40)], (False,)),
    "jittered_u": (lambda: [jittered_u(seed) for seed in range(30)], (False,)),                 # their corners fold
    "fanned_0.15": (lambda: [jittered_u(seed, 0.15, 0.6) for seed in range(30)], (False,)),    # and the ends absorb them
    "fanned_0.3": (lambda: [jittered_u(seed, 0.3, 0.6) for seed in range(30)], (False,)),
    "chain_jittered": (lambda: [chain_jittered_u(seed) for seed in range(20)], (False, True)),
    "u_wall": (lambda: [jittered_u_wall(seed) for seed in range(12)], (False,)),               # the arms' vertices cut
    "hole_rim": (lambda: [jittered_hole_rim(seed) for seed in range(12)], (False, True)),     # every corner cuts
    "shoot_strip": (lambda: [jittered_shoot_strip(seed) for seed in range(12)], (False,)),  # the start shoots on
}


@pytest.mark.parametrize("family", list(SWEEP))
def test_destructive_never_fails_below_its_limit(family):                    # anti-goal 1
    grids, modes = SWEEP[family]
    for b in grids():
        w = WaveSlider(b)
        for exact in modes:
            lim = w.limit(exact=exact, destructive=True)
            widths = {lim * i / 20 for i in range(1, 21)}
            widths |= {e.width + d for e in w._wave(exact) for d in (-3e-6, -3e-7, 3e-7)}   # around every event
            bends = {x for _, _, g in w._wave_of(exact).groups for x in w._group_bends(g.wall, g) if g.width < x <= lim}
            widths |= {x + d for x in bends for d in (-5e-7, 3e-7)}           # where an end's group passes a wall vertex
            for width in sorted(widths):
                if 0.0 < width <= lim:
                    w.solve(width, exact=exact, destructive=True)              # must not raise


@pytest.mark.parametrize("make", [u_in_grid, *(lambda s=s: jittered_u(s, 0.3, 0.6) for s in (6, 11, 22, 36)),
                                  u_wall, hole_rim, lambda: jittered_hole_rim(1), lambda: jittered_u_wall(5),
                                  lambda: jittered_hole_rim(22), lambda: jittered_hole_rim(34), notch_spike,
                                  lambda: jittered_u(30, 0.4), shoot_strip, lambda: shoot_strip(slant_deg=40.0),
                                  lambda: shoot_strip(no_landing=True), shoot_bevel, lambda: jittered_shoot_strip(3),
                                  lambda: chain_jittered_u(30, 0.3, 0.3), lambda: chain_jittered_u(8),
                                  lambda: jittered_grid(1)])
def test_destructive_limit_ignores_a_1e9_tilt(make):                         # anti-goal 3
    # A 1e-9 nudge of chain[1], a 1e-9 turn of the whole mesh about z, either way, and 1e-9 of noise on every vertex
    # along x, y and z: the limit stays, and so does every shot below it, where it lands.
    b = make()
    for exact in (False, True):
        w = WaveSlider(b)
        lim = w.limit(exact=exact, destructive=True)
        shots = _shots(w, exact, lim)
        for other in (tilted(b, 1e-9), tilted(b, -1e-9), rotated(b, 1e-9), rotated(b, -1e-9), jittered(b, 1),
                      jittered(b, 2)):
            w = WaveSlider(other)
            assert w.limit(exact=exact, destructive=True) == pytest.approx(lim, abs=1e-6)
            assert _shots(w, exact, lim) == shots


# --- Tolerance (D only): the weld raised by hand -------------------------------------

TOLERANCE_BANDS = [u_wall, hole_rim, square_in_grid, dumbbell, grid_racket, lambda: jittered_u(30, 0.4),
                   lambda: xy_jittered(grid_racket(), 7, 5e-4)]


def _d_record(w, exact):
    """The D limit, events and cuts at 8 even widths and just past the limit, as reprs."""
    lim = w.limit(exact=exact, destructive=True)
    cuts = [w.solve(lim * i / 8, exact=exact, destructive=True) for i in range(1, 9)]
    cuts.append(w.solve(lim + 0.5, exact=exact, destructive=True))
    return repr(lim), repr(w._wave(exact)), [(repr([p.co for p in c.points]), c.anchors, c.connectors, c.breaks)
                                             for c in cuts]


@pytest.mark.parametrize("make", [u_wall, hole_rim, square_in_grid, grid_racket])
def test_tolerance_zero_is_the_automatic_weld(make):
    # Tolerance 0 (the default) keeps the weld the mesh size gives, and every D result with it, bit for bit.
    b = make()
    auto, zero = WaveSlider(b), WaveSlider(b, tolerance=0.0)
    assert zero._weld == auto._weld == max(1e-6, 4.0 * 2.0 ** -23 * max(abs(c) for p in b.verts.values() for c in p))
    assert _d_record(zero, False) == _d_record(auto, False)


def test_tolerance_raises_the_weld_never_lowers_it():
    b = u_wall()
    auto = WaveSlider(b)._weld
    assert WaveSlider(b, tolerance=1e-3)._weld == 1e-3
    assert WaveSlider(b, tolerance=auto / 2.0)._weld == auto
    with pytest.raises(ValueError):
        WaveSlider(b, tolerance=-1e-3)


@pytest.mark.parametrize("make", [u_in_grid, u_wall, hole_rim, lambda: jittered_u(30, 0.4), shoot_strip])
def test_tolerance_is_ignored_with_destructive_off(make):
    b = make()
    plain, tol = WaveSlider(b), WaveSlider(b, tolerance=1e-3)
    for kw in ({}, {"collapse": True}, {"exact": True}):
        lim = plain.limit(**kw)
        assert repr(tol.limit(**kw)) == repr(lim)
        for i in range(1, 9):
            a, c = plain.solve(lim * i / 8, **kw), tol.solve(lim * i / 8, **kw)
            assert repr([p.co for p in a.points]) == repr([p.co for p in c.points]) and a.anchors == c.anchors


@pytest.mark.parametrize("make", TOLERANCE_BANDS)
def test_tolerance_moves_the_limit_by_its_own_order(make):
    # A raised weld holds folds and contacts from where the sides are that far apart (a few welds over the fold's
    # speed): the limit moves by no more than the order of the tolerance (4 of it at most on these), and no D solve
    # fails below it.
    b = make()
    lim = WaveSlider(b).limit(destructive=True)
    w = WaveSlider(b, tolerance=1e-3)
    moved = w.limit(destructive=True)
    assert abs(moved - lim) <= 5.0 * 1e-3, (lim, moved)
    for i in range(1, 9):
        w.solve(moved * i / 8, destructive=True)                                # must not raise


def test_destructive_segment_meets_its_partner_within_development_noise():
    # A long segment across slivers of a surface with 1e-5 of modelling noise develops its last face a few 1e-6 off where its
    # partner's own trace did: on a user mesh the D solve failed for a stretch below its limit ("segment 0 misses its
    # partner point", 4e-6 off). Ending in the face that holds the partner point, within the noise, it meets it; the
    # default mode keeps its exact test, and a segment ending in another face still misses.
    b = strip2()
    w = WaveSlider(b)
    a, c = w.place(1, 0.25).trace, w.place(2, 0.25).trace
    off = dataclasses.replace(c, end=dataclasses.replace(c.end, co=(c.end.co[0] + 3e-6, *c.end.co[1:])))
    assert w._wave_segment(1, a, off).end.co == w._segment(1, a, c).end.co
    with pytest.raises(OutOfRoom):
        w._segment(1, a, off)
    for co in ((2.5, 0.75, 0.0), off.end.co):  # far off; or as near, but in a face the segment does not end in
        elsewhere = dataclasses.replace(c, end=dataclasses.replace(c.end, kind="face", face=5, co=co))
        with pytest.raises(OutOfRoom):
            w._wave_segment(1, a, elsewhere)
