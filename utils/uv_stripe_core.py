"""UV Stripe core: unroll a strip of faces into one straight, even UV rectangle.

Pure Python (stdlib only), no bpy and no mathutils, so it runs under plain pytest.

A Strip has a near boundary (the original edge, v = 0) and a far boundary (the new
edge, v = height). Each is laid out by its own arc length, scaled to the strip length
L (the mean of the two), so columns may lean; the rungs pick a closed strip's seam
and check that the new edge runs in the order of the original one. Vertices on
neither boundary are relaxed inside with mean-value weights taken from 3D. U runs
along the loop and V across it, both in world units, so the aspect is kept.
"""

import math
from dataclasses import dataclass, field, replace

Vec3 = tuple[float, float, float]
Vec2 = tuple[float, float]

TUTTE_ITERS = 1000
TUTTE_TOL = 1e-12
TIE_TOL = 1e-9
MAX_CORNER = math.pi - 1e-6  # corner angles are capped here, so a straight corner's tan(angle / 2) stays finite


@dataclass
class Strip:
    verts: dict[int, Vec3]
    faces: dict[int, tuple[int, ...]]
    near: list[int]
    far: list[int]
    rungs: list[tuple[int, int]]
    closed: bool
    height: float
    sides: tuple[list[int], list[int]] = field(default_factory=lambda: ([], []))
    corner_far: dict[tuple[int, int], int] = field(default_factory=dict)
    # A near id that occurs twice (an open strip whose near row starts and ends on one
    # vertex, a seam) takes, at each (face id, vertex id) corner listed here, that position.
    corner_near: dict[tuple[int, int], int] = field(default_factory=dict)
    # How U is laid out along the rows: "EVEN" (each row by its own arc length, scaled to L),
    # "STRAIGHT" (between vertical posts, ``_post_u``) or "TRUE" (true lengths, ``_true_u``;
    # an open strip only, a closed one uses "EVEN").
    layout: str = "EVEN"
    # A closed strip's seam: the index into ``rungs`` it is cut at; None picks ``sharpest_rung``.
    seam: int | None = None


def _angle(a: Vec3, b: Vec3, c: Vec3) -> float:
    """Angle at b between the edges to a and c; a zero-length edge counts as straight."""
    u = [a[i] - b[i] for i in range(3)]
    w = [c[i] - b[i] for i in range(3)]
    lu = math.sqrt(sum(x * x for x in u))
    lw = math.sqrt(sum(x * x for x in w))
    if lu < TIE_TOL or lw < TIE_TOL:
        return math.pi
    cos = sum(u[i] * w[i] for i in range(3)) / (lu * lw)
    return math.acos(max(-1.0, min(1.0, cos)))


def sharpest_rung(strip: Strip) -> int:
    """Rung whose near vertex has the smallest corner angle; the lowest rung wins a tie."""
    near, verts, n = strip.near, strip.verts, len(strip.near)
    best, best_angle = 0, math.inf
    for k, (ni, _fi) in enumerate(strip.rungs):
        ang = _angle(verts[near[(ni - 1) % n]], verts[near[ni]], verts[near[(ni + 1) % n]])
        if ang < best_angle - TIE_TOL:
            best, best_angle = k, ang
    return best


def ascending_rungs(strip: Strip) -> Strip:
    """A closed strip with its near and far loops rotated so its rungs ascend along both.

    A closed cut can start its rungs mid-way round the far loop: a collapsed or
    welded seam gives far indices such as [2, 0, 1, 2]. Each rung is tried as the
    first, in near order: near is rotated to start at its near vertex and far at
    its far vertex. The first rotation whose far indices never decrease is
    returned. An open strip, one whose rungs already ascend, and one no rotation
    fixes come back as they are (``stripe_uvs`` then rejects the last).
    """
    rungs = sorted(strip.rungs)
    if not strip.closed or all(a[1] <= b[1] for a, b in zip(rungs, rungs[1:])):
        return strip
    nn, nf = len(strip.near), len(strip.far)
    for s, (n0, f0) in enumerate(rungs):
        moved = [((ni - n0) % nn, (fi - f0) % nf) for ni, fi in rungs[s:] + rungs[:s]]
        if all(a[1] <= b[1] for a, b in zip(moved, moved[1:])):
            return replace(
                strip,
                near=strip.near[n0:] + strip.near[:n0],
                far=strip.far[f0:] + strip.far[:f0],
                rungs=moved,
                corner_far={key: (i - f0) % nf for key, i in strip.corner_far.items()},
                corner_near={key: (i - n0) % nn for key, i in strip.corner_near.items()},
            )
    return strip


def _row_steps(strip: Strip, ids: list[int], start: int) -> list[float]:
    """Lengths of one row's edges, walked from position ``start``.

    A closed row is a loop: it is walked from ``start`` round to ``start`` again, wrapping.
    An open row is the path from its first position to its last (``start`` is 0).
    """
    n = len(ids)
    count = n if strip.closed else n - 1
    return [math.dist(strip.verts[ids[(start + j) % n]], strip.verts[ids[(start + j + 1) % n]]) for j in range(count)]


def _row_u(strip: Strip, ids: list[int], start: int, length: float) -> list[float]:
    """U of every position of one row, by the row's own arc length from ``start``, scaled to ``length``.

    The walk runs as in ``_row_steps``; an open row's last position gets ``length`` exactly.
    A repeated id keeps one u per position. A row with no length (collapsed to a point)
    spreads its positions evenly instead.
    """
    n = len(ids)
    steps = _row_steps(strip, ids, start)
    run = [0.0]
    for step in steps:
        run.append(run[-1] + step)
    total = run[-1]
    out = [0.0] * n
    for k in range(n):
        t = run[k] / total if total > 1e-12 else k / max(len(steps), 1)
        out[(start + k) % n] = length * t
    return out


def _unwrapped(strip: Strip, start: int) -> tuple[list[int], list[int]]:
    """Rung indices into near and far in strip order.

    Open strips use the rungs as given. Closed strips start at rung `start`, wrap around and
    end with the start rung again, one full loop later. Raises ValueError when either index
    list runs backward: the new edge then runs against the original one, and both rows are
    walked forward from the seam (``ascending_rungs`` rotates a closed strip whose rungs
    start mid-way round).
    """
    rn = [r[0] for r in strip.rungs]
    rf = [r[1] for r in strip.rungs]
    if not strip.closed:
        un, uf = rn, rf
    else:
        n, nn, nf = len(rn), len(strip.near), len(strip.far)
        un = [rn[(start + k) % n] + (nn if start + k >= n else 0) for k in range(n)] + [rn[start] + nn]
        uf = [rf[(start + k) % n] + (nf if start + k >= n else 0) for k in range(n)] + [rf[start] + nf]
    for ids in (un, uf):
        if any(a > b for a, b in zip(ids, ids[1:])):
            raise ValueError("the new loop does not run in the order of the chain")
    return un, uf


def strip_length(strip: Strip) -> float:
    """The strip length L: the mean of the near and far rows' lengths (whole loops when closed).

    Raises ValueError when the rungs run backward (``_unwrapped``).
    """
    _unwrapped(strip, 0)
    return (sum(_row_steps(strip, strip.near, 0)) + sum(_row_steps(strip, strip.far, 0))) / 2.0


def _post_u(strip: Strip, un: list[int], uf: list[int]) -> tuple[list[float], list[float]]:
    """U of every near and far position, laid out between vertical posts.

    Posts, in unwrapped order: the rows' start, every rung that strictly advances both
    the near and the far index over the last post, by some length on both rows, and
    lies strictly before the end on both, then the rows' end (an open strip's last
    positions; a closed strip's seam rung one loop later). A post the end does not
    advance from by some length on both rows is dropped, so the positions of a
    collapsed run (one point listed more than once) always share one u. Each span between two posts is as long as the mean of the
    two rows' arcs over it; a row position inside a span takes its share by its own
    arc length, evenly over a zero-length span. The last post is at ``strip_length``.
    """
    near, far = strip.near, strip.far
    nn, nf = len(near), len(far)
    if strip.closed:
        start, end = (un[0], uf[0]), (un[-1], uf[-1])
        cands = list(zip(un[1:-1], uf[1:-1]))
    else:
        start, end = (0, 0), (nn - 1, nf - 1)
        cands = list(zip(un, uf))
    def arcs(ids: list[int], first: int, last: int) -> dict[int, float]:
        n = len(ids)
        out, run = {first: 0.0}, 0.0
        for j in range(first, last):
            run += math.dist(strip.verts[ids[j % n]], strip.verts[ids[(j + 1) % n]])
            out[j + 1] = run
        return out

    arc_n = arcs(near, start[0], end[0])
    arc_f = arcs(far, start[1], end[1])

    def advances(p: tuple[int, int], q: tuple[int, int]) -> bool:
        return arc_n[q[0]] - arc_n[p[0]] > TIE_TOL and arc_f[q[1]] - arc_f[p[1]] > TIE_TOL

    posts = [start]
    for a, b in cands:
        if posts[-1][0] < a < end[0] and posts[-1][1] < b < end[1] and advances(posts[-1], (a, b)):
            posts.append((a, b))
    while len(posts) > 1 and not advances(posts[-1], end):
        posts.pop()
    posts.append(end)
    u_near, u_far = [0.0] * nn, [0.0] * nf
    u = 0.0
    for (a0, b0), (a1, b1) in zip(posts, posts[1:]):
        dn, df = arc_n[a1] - arc_n[a0], arc_f[b1] - arc_f[b0]
        nxt = u + (dn + df) / 2.0
        for out, arc, i0, i1, d, n in ((u_near, arc_n, a0, a1, dn, nn), (u_far, arc_f, b0, b1, df, nf)):
            for j in range(i0, i1):
                t = (arc[j] - arc[i0]) / d if d > 1e-12 else (j - i0) / (i1 - i0)
                out[j % n] = u + (nxt - u) * t
        u = nxt
    if not strip.closed:
        u_near[nn - 1] = u
        u_far[nf - 1] = u
    return u_near, u_far


def _true_u(strip: Strip) -> tuple[list[float], list[float], float]:
    """U of every near and far position at the rows' true lengths, and the u extent.

    The near row runs from u = 0 by its arc length; the far row by its own, from the real
    lead of its start over the near row's start along the strip: ``far[0] - near[0]``
    projected on the start direction (the mean of the unit directions of the first near
    and the first far edge; one of them alone when the other has no length, no lead when
    neither has). The result is shifted so the smallest u is 0. A flat piece between
    straight rails is laid out without any stretch, its ends at their real slant.
    """
    verts = strip.verts

    def run(ids: list[int]) -> list[float]:
        out = [0.0]
        for a, b in zip(ids, ids[1:]):
            out.append(out[-1] + math.dist(verts[a], verts[b]))
        return out

    def unit(ids: list[int]) -> list[float]:
        for a, b in zip(ids, ids[1:]):
            d = [verts[b][i] - verts[a][i] for i in range(3)]
            n = math.sqrt(sum(c * c for c in d))
            if n > TIE_TOL:
                return [c / n for c in d]
        return [0.0, 0.0, 0.0]

    u_near, u_far = run(strip.near), run(strip.far)
    dn, df = unit(strip.near), unit(strip.far)
    d = [dn[i] + df[i] for i in range(3)]
    n = math.sqrt(sum(c * c for c in d))
    lead = 0.0
    if n > TIE_TOL:
        lead = sum((verts[strip.far[0]][i] - verts[strip.near[0]][i]) * d[i] / n for i in range(3))
    u_far = [lead + u for u in u_far]
    low = min(min(u_near), min(u_far))
    u_near = [u - low for u in u_near]
    u_far = [u - low for u in u_far]
    return u_near, u_far, max(max(u_near), max(u_far))


def strip_extent(strip: Strip) -> float:
    """The u extent ``stripe_uvs`` lays the strip out over: its true length span under "TRUE"
    (an open strip), else ``strip_length``."""
    if strip.layout == "TRUE" and not strip.closed:
        return _true_u(strip)[2]
    return strip_length(strip)


def _side_v(strip: Strip, end_ids: tuple[int, int], side: list[int]) -> dict[int, float]:
    """V of the vertices on one open end, by arc length from near to far scaled to the height."""
    path = [end_ids[0], *side, end_ids[1]]
    cum = [0.0]
    for a, b in zip(path, path[1:]):
        cum.append(cum[-1] + math.dist(strip.verts[a], strip.verts[b]))
    total = cum[-1]
    return {vid: (strip.height * c / total if total > 1e-12 else 0.0) for vid, c in zip(path[1:-1], cum[1:-1])}


def stripe_uvs(strip: Strip) -> dict[tuple[int, int], Vec2]:
    """Map every (face id, vertex id) corner of the strip to (u, v) in world units.

    The near row lies on v = 0 and the far row on v = height, each by its own arc length
    scaled to L (``strip_length``); with ``layout`` "STRAIGHT" between vertical posts
    (``_post_u``), with "TRUE" (open strips) at their true lengths (``_true_u``). A closed
    strip's rows are walked from its seam rung (``seam``, else ``sharpest_rung``). An open
    strip's end sides stand at u = 0 and u = L, or under "TRUE" on the line between that
    end's near and far corner; the u extent is ``strip_extent``. Every other vertex is
    relaxed inside (``_tutte``). A repeated near id takes its ``corner_near``
    position at each corner listed there. Raises ValueError for rungs that run backward,
    and for a repeated far id without a ``corner_far`` entry for one of its corners.
    """
    near, far = strip.near, strip.far
    if not strip.closed:
        start = 0
    elif strip.seam is not None:
        start = strip.seam
    else:
        start = sharpest_rung(strip)
    un, uf = _unwrapped(strip, start)
    length = strip_length(strip)
    # an open strip's rows run from their first vertex, which need not be on a rung
    seam_near = un[0] % len(near) if strip.closed else 0
    seam_far = uf[0] % len(far) if strip.closed else 0
    true = strip.layout == "TRUE" and not strip.closed
    if true:
        u_near, u_far, length = _true_u(strip)
    elif strip.layout == "STRAIGHT":
        u_near, u_far = _post_u(strip, un, uf)
    else:
        u_near = _row_u(strip, near, seam_near, length)
        u_far = _row_u(strip, far, seam_far, length)

    near_at = {vid: i for i, vid in enumerate(near)}
    far_at: dict[int, list[int]] = {}
    for i, vid in enumerate(far):
        far_at.setdefault(vid, []).append(i)
    side_v: dict[int, tuple[float, float]] = {}  # vertex id -> (u, v) on an open end
    if true:
        for side, ends, (u0, u1) in ((strip.sides[0], (near[0], far[0]), (u_near[0], u_far[0])),
                                     (strip.sides[1], (near[-1], far[-1]), (u_near[-1], u_far[-1]))):
            side_v.update({
                vid: (u0 + (u1 - u0) * (v / strip.height if strip.height > 1e-12 else 0.0), v)
                for vid, v in _side_v(strip, ends, side).items()
            })
    elif not strip.closed:
        for side, ends, u in ((strip.sides[0], (near[0], far[0]), 0.0), (strip.sides[1], (near[-1], far[-1]), length)):
            side_v.update({vid: (u, v) for vid, v in _side_v(strip, ends, side).items()})

    uv: dict[tuple[int, int], Vec2] = {}
    seam_corners: list[tuple[int, int]] = []
    interior: set[int] = set()
    for fid, face in strip.faces.items():
        for vid in face:
            key = (fid, vid)
            if vid in near_at:
                i = strip.corner_near.get(key, near_at[vid])
                uv[key] = (u_near[i], 0.0)
                if strip.closed and i == seam_near:
                    seam_corners.append(key)
            elif vid in far_at:
                idx = far_at[vid]
                if len(idx) > 1:
                    if key not in strip.corner_far:
                        raise ValueError(
                            f"vertex {vid} occurs {len(idx)} times on the far boundary; "
                            f"corner_far has no entry for face {fid}"
                        )
                    i = strip.corner_far[key]
                else:
                    i = idx[0]
                uv[key] = (u_far[i], strip.height)
                if strip.closed and i == seam_far:
                    seam_corners.append(key)
            elif vid in side_v:
                uv[key] = side_v[vid]
            else:
                interior.add(vid)

    # The seam rung sits at u = 0 on one side of the cut and u = L on the other: per face, the
    # end that keeps the face's other boundary corners closest (smallest span). Both rows start
    # their walk at the seam rung, so the seam column is vertical on either side, also when its
    # far vertex is shared by two rungs (a collapse node).
    for fid, vid in seam_corners:
        others = [uv[(fid, w)][0] for w in strip.faces[fid] if (fid, w) in uv and (fid, w) not in seam_corners]
        u = length if (others and max(length - o for o in others) < max(others)) else 0.0
        uv[(fid, vid)] = (u, uv[(fid, vid)][1])

    pos = _tutte(strip, interior, uv, length)
    for fid, face in strip.faces.items():
        for vid in face:
            if vid in pos:
                uv[(fid, vid)] = pos[vid]

    # Faces that run the near boundary backward (a cut on the other side of its chain) would
    # map mirrored: their corners, in the faces' own order, would wind clockwise in UV.
    if sum(_signed_area([uv[(fid, vid)] for vid in face]) for fid, face in strip.faces.items()) < 0.0:
        uv = {key: (length - u, v) for key, (u, v) in uv.items()}
    return uv


def straighten(strip: Strip) -> bool:
    """Set the strip's ``layout`` to "STRAIGHT" unless that lays it out worse than "EVEN".

    Worse: more faces fold (their corners, in their own order, wind clockwise in UV),
    or the faces no longer tile the same area (a tear or an overlap). Returns whether
    the strip was straightened; a strip that is not keeps "EVEN". Raises ValueError as
    ``stripe_uvs`` does.
    """
    def measure(uv) -> tuple[int, float]:
        areas = [_signed_area([uv[(fid, vid)] for vid in face]) for fid, face in strip.faces.items()]
        return sum(a < -TIE_TOL for a in areas), sum(areas)

    strip.layout = "EVEN"
    folds, area = measure(stripe_uvs(strip))
    strip.layout = "STRAIGHT"
    new_folds, new_area = measure(stripe_uvs(strip))
    if new_folds > folds or abs(new_area - area) > 1e-6 * max(abs(area), TIE_TOL):
        strip.layout = "EVEN"
    return strip.layout == "STRAIGHT"


def _signed_area(pts: list[Vec2]) -> float:
    """Signed area of a polygon, positive when it winds counter-clockwise."""
    return 0.5 * sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(pts, pts[1:] + pts[:1]))


def _mean_value_terms(strip: Strip, interior: set[int]) -> dict[int, list[tuple[float, int, int]]]:
    """Each interior vertex's (weight, neighbour, face) terms, with mean-value weights from 3D.

    Every face round an interior vertex i gives each of its two edges at i the term
    tan(a / 2) / |p_j - p_i|, a being the face's corner angle at i. Summed over the two
    faces of edge ij this is the mean-value weight (tan(alpha / 2) + tan(beta / 2)) / |p_j - p_i|.
    The terms stay per face, because a boundary neighbour (a seam or repeated far vertex)
    can have a different UV in each face. A straight corner is capped at ``MAX_CORNER``
    and a zero-length edge at ``TIE_TOL``; a vertex whose terms all weigh nothing (only
    zero-angle corners) takes uniform weights.
    """
    verts = strip.verts
    terms: dict[int, list[tuple[float, int, int]]] = {p: [] for p in interior}
    for fid, face in strip.faces.items():
        n = len(face)
        for k, p in enumerate(face):
            if p not in interior:
                continue
            prev, nxt = face[k - 1], face[(k + 1) % n]
            half = math.tan(min(_angle(verts[prev], verts[p], verts[nxt]), MAX_CORNER) / 2.0)
            for q in (prev, nxt):
                terms[p].append((half / max(math.dist(verts[p], verts[q]), TIE_TOL), q, fid))
    for p, ts in terms.items():
        if sum(w for w, _q, _fid in ts) <= 0.0:
            terms[p] = [(1.0, q, fid) for _w, q, fid in ts]
    return terms


def _tutte(strip: Strip, interior: set[int], uv: dict[tuple[int, int], Vec2], length: float) -> dict[int, Vec2]:
    """Mean-value Tutte embedding of the interior vertices inside the fixed boundary.

    Gauss-Seidel with the weights of ``_mean_value_terms``, until no vertex moves by
    ``TUTTE_TOL * length`` or more, or ``TUTTE_ITERS`` sweeps.
    """
    if not interior:
        return {}
    terms = _mean_value_terms(strip, interior)
    cu = sum(p[0] for p in uv.values()) / len(uv)
    cv = sum(p[1] for p in uv.values()) / len(uv)
    pos = dict.fromkeys(interior, (cu, cv))
    order = sorted(interior)
    for _ in range(TUTTE_ITERS):
        biggest = 0.0
        for p in order:
            su = sv = sw = 0.0
            for w, q, fid in terms[p]:
                qu, qv = pos[q] if q in interior else uv[(fid, q)]
                su += w * qu
                sv += w * qv
                sw += w
            new = (su / sw, sv / sw)
            biggest = max(biggest, abs(new[0] - pos[p][0]), abs(new[1] - pos[p][1]))
            pos[p] = new
        if biggest < TUTTE_TOL * length:
            break
    return pos


def place_fit(
    maps: list[dict], heights: list[float], lengths: list[float], gap: float = 0.01,
    groups: list[int] | None = None, vertical: bool = False,
) -> list[dict]:
    """Scale every strip to u in 0..1 (v by the same factor) and stack them upward with a gap.

    ``lengths`` are the strips' u extents (``strip_extent``). ``groups`` gives each strip a
    group id: the strips of one group share one scale, 1 / the group's longest length, so
    they keep one texel density (the longest spans u 0..1, the others less). None puts
    every strip in a group of its own. ``vertical`` turns each strip 90 degrees counter-
    clockwise, so its length runs along v 0..1, and stacks the strips to the right.
    """
    if groups is None:
        groups = list(range(len(maps)))
    longest: dict[int, float] = {}
    for g, length in zip(groups, lengths):
        longest[g] = max(longest.get(g, 0.0), length)
    out = []
    base = 0.0
    for uv, height, g in zip(maps, heights, groups):
        s = 1.0 / longest[g]
        if vertical:
            out.append({k: (base + (height - v) * s, u * s) for k, (u, v) in uv.items()})
        else:
            out.append({k: (u * s, v * s + base) for k, (u, v) in uv.items()})
        base += height * s + gap
    return out


def place_in_place(
    uv: dict, length: float, height: float, center: Vec2, density: float, vertical: bool = False
) -> dict:
    """Scale by the texel density and centre the strip's rectangle on `center`; ``vertical``
    turns it 90 degrees counter-clockwise about that centre."""
    ou = center[0] - length * density / 2.0
    ov = center[1] - height * density / 2.0
    out = {k: (u * density + ou, v * density + ov) for k, (u, v) in uv.items()}
    if vertical:
        cu, cv = center
        out = {k: (cu - (v - cv), cv + (u - cu)) for k, (u, v) in out.items()}
    return out


def _quarter_turn(p: Vec2, k: int) -> Vec2:
    """``p`` turned by k times 90 degrees counter-clockwise."""
    x, y = p
    for _ in range(k % 4):
        x, y = -y, x
    return (x, y)


def active_anchor(new: list[Vec2], old: list[Vec2]) -> tuple[float, int, Vec2, Vec2]:
    """How a laid-out face maps onto its old UVs: (scale, quarter turns, new centroid, old centroid).

    ``new`` and ``old`` are the face's corners in its own order, laid out and as they
    were. The scale is the old perimeter over the new one; the turn is the multiple of
    90 degrees (counter-clockwise, never a mirror) that puts the scaled corners, centroid
    on centroid, nearest the old ones (least squares; a tie takes the smaller turn).
    Raises ValueError when either perimeter is zero.
    """
    def perimeter(pts):
        return sum(math.dist(a, b) for a, b in zip(pts, pts[1:] + pts[:1]))

    p_new, p_old = perimeter(new), perimeter(old)
    if p_new <= TIE_TOL or p_old <= TIE_TOL:
        raise ValueError("the active face has no size in UV")
    scale = p_old / p_new
    cn = (sum(p[0] for p in new) / len(new), sum(p[1] for p in new) / len(new))
    co = (sum(p[0] for p in old) / len(old), sum(p[1] for p in old) / len(old))

    def error(k):
        total = 0.0
        for a, b in zip(new, old):
            t = _quarter_turn((a[0] - cn[0], a[1] - cn[1]), k)
            total += (co[0] + scale * t[0] - b[0]) ** 2 + (co[1] + scale * t[1] - b[1]) ** 2
        return total

    errors = [error(k) for k in range(4)]
    best = min(errors)
    turn = next(k for k in range(4) if errors[k] <= best + 1e-12 * max(1.0, best))
    return scale, turn, cn, co


def place_active(
    uv: dict, anchor: tuple[float, int, Vec2, Vec2], pivot: Vec2 | None = None, center: Vec2 | None = None
) -> dict:
    """Scale and turn a strip's layout by ``anchor`` (``active_anchor``).

    Without ``pivot``/``center`` the anchor's own centroids are matched, so the active
    face lands on its old corners. With them, ``pivot`` (a layout point, such as the
    strip rectangle's centre) is put on ``center`` (such as the strip's old UV centre).
    """
    scale, turn, cn, co = anchor
    if pivot is not None and center is not None:
        cn, co = pivot, center
    out = {}
    for key, (u, v) in uv.items():
        t = _quarter_turn((u - cn[0], v - cn[1]), turn)
        out[key] = (co[0] + scale * t[0], co[1] + scale * t[1])
    return out
