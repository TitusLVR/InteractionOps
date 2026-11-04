"""UV Stripe core: unroll a strip of faces into one straight, even UV rectangle.

Pure Python (stdlib only), no bpy and no mathutils, so it runs under plain pytest.

A Strip has a near boundary (the original edge, v = 0) and a far boundary (the new
edge, v = height), joined by rungs where the columns line up. U runs along the loop
and V across it, both in world units, so the aspect is kept (no stretching).
"""

import math
from dataclasses import dataclass, field, replace

Vec3 = tuple[float, float, float]
Vec2 = tuple[float, float]

TUTTE_ITERS = 1000
TUTTE_TOL = 1e-12
TIE_TOL = 1e-9


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
            )
    return strip


def _path_len(strip: Strip, ids: list[int], a: int, b: int) -> float:
    """Length of the path ids[a] .. ids[b] (indices may run past the end of a closed loop)."""
    n = len(ids)
    return sum(math.dist(strip.verts[ids[j % n]], strip.verts[ids[(j + 1) % n]]) for j in range(a, b))


def _unwrapped(strip: Strip, start: int) -> tuple[list[int], list[int]]:
    """Rung indices into near and far in strip order.

    Open strips use the rungs as given. Closed strips start at rung `start`, wrap around and
    end with the start rung again, one full loop later. Raises ValueError when either index
    list runs backward: the layout measures every path between rungs forward
    (``ascending_rungs`` rotates a closed strip whose rungs start mid-way round).
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


def _rung_u(strip: Strip, un: list[int], uf: list[int]) -> list[float]:
    """Cumulative mid-line length at each rung."""
    out = [0.0]
    for k in range(len(un) - 1):
        ln = _path_len(strip, strip.near, un[k], un[k + 1])
        lf = _path_len(strip, strip.far, uf[k], uf[k + 1])
        out.append(out[-1] + (ln + lf) / 2.0)
    return out


def strip_length(strip: Strip) -> float:
    un, uf = _unwrapped(strip, 0)
    return _rung_u(strip, un, uf)[-1]


def _side_u(strip: Strip, ids: list[int], ridx: list[int], ru: list[float]) -> list[float]:
    """U of every vertex of one boundary, by arc length between the rung values.

    Indices before the first rung or after the last one (open strips) take the end rung's u.
    """
    n = len(ids)
    out = [ru[0]] * n
    for i in range(ridx[-1] + 1, n):
        out[i] = ru[-1]
    for k in range(len(ridx) - 1):
        a, b = ridx[k], ridx[k + 1]
        total = _path_len(strip, ids, a, b)
        run = 0.0
        # a closed loop's final rung is the seam copy of the first one: it stays out of the table
        top = b if strip.closed and k == len(ridx) - 2 else b + 1
        for j in range(a, top):
            if j > a:
                run += math.dist(strip.verts[ids[(j - 1) % n]], strip.verts[ids[j % n]])
            t = run / total if total > 1e-12 else 0.0
            out[j % n] = ru[k] + (ru[k + 1] - ru[k]) * t
    # a vertex shared by consecutive rungs (collapsed segment) sits at the mean of their u
    shared: dict[int, list[float]] = {}
    for k in range(len(ridx) - 1 if strip.closed else len(ridx)):
        shared.setdefault(ridx[k] % n, []).append(ru[k])
    for i, us in shared.items():
        if len(us) > 1:
            out[i] = sum(us) / len(us)
    return out


def _side_v(strip: Strip, end_ids: tuple[int, int], side: list[int]) -> dict[int, float]:
    """V of the vertices on one open end, by arc length from near to far scaled to the height."""
    path = [end_ids[0], *side, end_ids[1]]
    cum = [0.0]
    for a, b in zip(path, path[1:]):
        cum.append(cum[-1] + math.dist(strip.verts[a], strip.verts[b]))
    total = cum[-1]
    return {vid: (strip.height * c / total if total > 1e-12 else 0.0) for vid, c in zip(path[1:-1], cum[1:-1])}


def stripe_uvs(strip: Strip) -> dict[tuple[int, int], Vec2]:
    """Map every (face id, vertex id) corner of the strip to (u, v) in world units."""
    near, far = strip.near, strip.far
    start = sharpest_rung(strip) if strip.closed else 0
    un, uf = _unwrapped(strip, start)
    ru = _rung_u(strip, un, uf)
    length = ru[-1]
    u_near = _side_u(strip, near, un, ru)
    u_far = _side_u(strip, far, uf, ru)
    seam_near = un[0] % len(near)
    seam_far = uf[0] % len(far)

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
                i = near_at[vid]
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
    # end that keeps the face's other boundary corners closest (smallest span). Both ends are
    # set outright: a seam vertex shared by two rungs (a collapse node) holds their mean u.
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


def _tutte(strip: Strip, interior: set[int], uv: dict[tuple[int, int], Vec2], length: float) -> dict[int, Vec2]:
    """Uniform-weight Tutte embedding of the interior vertices inside the fixed boundary."""
    if not interior:
        return {}
    nbrs: dict[int, dict[int, int]] = {p: {} for p in interior}  # vertex -> neighbour -> face
    for fid, face in strip.faces.items():
        for a, b in zip(face, face[1:] + face[:1]):
            if a in interior:
                nbrs[a].setdefault(b, fid)
            if b in interior:
                nbrs[b].setdefault(a, fid)
    cu = sum(p[0] for p in uv.values()) / len(uv)
    cv = sum(p[1] for p in uv.values()) / len(uv)
    pos = dict.fromkeys(interior, (cu, cv))
    order = sorted(interior)
    for _ in range(TUTTE_ITERS):
        biggest = 0.0
        for p in order:
            su = sv = 0.0
            for q, fid in nbrs[p].items():
                qu, qv = pos[q] if q in interior else uv[(fid, q)]
                su += qu
                sv += qv
            new = (su / len(nbrs[p]), sv / len(nbrs[p]))
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
