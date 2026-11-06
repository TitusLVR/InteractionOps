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
    scaled to L (``strip_length``); a closed strip's rows are walked from its seam rung
    (``sharpest_rung``). An open strip's end sides stand at u = 0 and u = L. Every other
    vertex is relaxed inside (``_tutte``). A repeated near id takes its ``corner_near``
    position at each corner listed there. Raises ValueError for rungs that run backward,
    and for a repeated far id without a ``corner_far`` entry for one of its corners.
    """
    near, far = strip.near, strip.far
    start = sharpest_rung(strip) if strip.closed else 0
    un, uf = _unwrapped(strip, start)
    length = strip_length(strip)
    # an open strip's rows run from their first vertex, which need not be on a rung
    seam_near = un[0] % len(near) if strip.closed else 0
    seam_far = uf[0] % len(far) if strip.closed else 0
    u_near = _row_u(strip, near, seam_near, length)
    u_far = _row_u(strip, far, seam_far, length)

    near_at = {vid: i for i, vid in enumerate(near)}
    far_at: dict[int, list[int]] = {}
    for i, vid in enumerate(far):
        far_at.setdefault(vid, []).append(i)
    side_v: dict[int, tuple[float, float]] = {}  # vertex id -> (u, v) on an open end
    if not strip.closed:
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


def place_fit(maps: list[dict], heights: list[float], lengths: list[float], gap: float = 0.01) -> list[dict]:
    """Scale every strip to u in 0..1 (v by the same factor) and stack them upward with a gap."""
    out = []
    base = 0.0
    for uv, height, length in zip(maps, heights, lengths):
        s = 1.0 / length
        out.append({k: (u * s, v * s + base) for k, (u, v) in uv.items()})
        base += height * s + gap
    return out


def place_in_place(uv: dict, length: float, height: float, center: Vec2, density: float) -> dict:
    """Scale by the texel density and centre the strip's rectangle on `center`."""
    ou = center[0] - length * density / 2.0
    ov = center[1] - height * density / 2.0
    return {k: (u * density + ou, v * density + ov) for k, (u, v) in uv.items()}
