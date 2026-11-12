"""UV Stripe selection: turn selected faces into ``uv_stripe_core.Strip``s.

Pure Python (stdlib only), no bpy and no mathutils, so it runs under plain pytest.

The selection is split into edge-connected islands (``face_islands``); each island
must be one of three shapes (``strip_from_faces``), tried in this order:

- an open chain: faces in a row, each sharing one edge with the next. Each end
  face's cap is the middle of its boundary edges, read from the edge it shares:
  the opposite edge of a quad. With an even number of boundary edges (a triangle)
  the cap is one of the two middle edges: the one at the end vertex where the
  boundary turns more sharply (the row runs straight on at the other), when the
  two turns differ by more than ``CAP_ANGLE``; otherwise (a pointed tip) the cap
  is the middle vertex, where both rows start. The caps split the boundary into
  the two rows. A single quad, or two triangles forming one, is the quad.
- a closed chain: a ring of faces, each sharing one edge with each of two others.
  Its two boundary loops are the rows, every shared edge is a rung.
- a quad-grid patch wider than one face: the four boundary vertices used by one
  face only are the corners; the pair of opposite sides with the larger summed
  length are the rows, the other two the ends.

Direction rule, so the layout depends on the geometry only, not on vertex or face
ids: an open strip's U runs toward the positive direction of the dominant world
axis (largest absolute component, ties X, then Y, then Z) of the vector from one
end's centroid to the other's: the end with the smaller coordinate on that axis
sits at u = 0. A closed strip's near row (v = 0) is the loop whose centroid is
lower along the dominant axis of the vector between the two loop centroids; when
the centroids coincide (a flat ring) it is the longer loop. The closed strip's
loops start at the rung whose vertices come first by (x, y, z), so equal seam
candidates resolve the same way every time. Faces keep their own winding: the
core turns the strip so that they stay counter-clockwise in UV.
"""

import math
from collections import Counter, defaultdict

from .uv_stripe_core import Strip, Vec3, _angle, ascending_rungs, strip_length, stripe_uvs

TOL = 1e-9
CAP_ANGLE = math.radians(15.0)


def _edge(a: int, b: int) -> tuple[int, int]:
    return (a, b) if a < b else (b, a)


def _face_edges(face: tuple[int, ...]) -> list[tuple[int, int]]:
    """The face's edges as (a, b) in its winding order."""
    return [(face[i], face[(i + 1) % len(face)]) for i in range(len(face))]


def _edge_faces(faces: dict[int, tuple[int, ...]]) -> dict[tuple[int, int], list[int]]:
    out: dict[tuple[int, int], list[int]] = defaultdict(list)
    for fid in sorted(faces):
        for a, b in _face_edges(faces[fid]):
            out[_edge(a, b)].append(fid)
    return out


def face_islands(faces: dict[int, tuple[int, ...]]) -> list[dict[int, tuple[int, ...]]]:
    """Edge-connected components of the face set, ordered by their lowest face id."""
    edge_faces = _edge_faces(faces)
    seen: set[int] = set()
    out = []
    for start in sorted(faces):
        if start in seen:
            continue
        seen.add(start)
        todo, comp = [start], []
        while todo:
            fid = todo.pop()
            comp.append(fid)
            for a, b in _face_edges(faces[fid]):
                for other in edge_faces[_edge(a, b)]:
                    if other not in seen:
                        seen.add(other)
                        todo.append(other)
        out.append({fid: faces[fid] for fid in sorted(comp)})
    return out


def _key(p: Vec3) -> tuple[float, float, float]:
    return (round(p[0], 6), round(p[1], 6), round(p[2], 6))


def _centroid(verts: dict[int, Vec3], ids: list[int]) -> Vec3:
    n = len(ids)
    return (
        sum(verts[i][0] for i in ids) / n,
        sum(verts[i][1] for i in ids) / n,
        sum(verts[i][2] for i in ids) / n,
    )


def _dominant_axis(d: Vec3) -> int:
    """The axis of d's largest absolute component; a tie goes to X, then Y, then Z."""
    best = 0
    for i in (1, 2):
        if abs(d[i]) > abs(d[best]) + TOL:
            best = i
    return best


def _comes_first(a: Vec3, b: Vec3) -> bool | None:
    """Whether a is lower than b along the dominant axis of b - a, then by (x, y, z); None when equal."""
    d = (b[0] - a[0], b[1] - a[1], b[2] - a[2])
    axis = _dominant_axis(d)
    if abs(d[axis]) > TOL:
        return d[axis] > 0.0
    return None


def _length(verts: dict[int, Vec3], path: list[int], closed: bool = False) -> float:
    ids = path + path[:1] if closed else path
    return sum(math.dist(verts[a], verts[b]) for a, b in zip(ids, ids[1:]))


def _boundary_loops(faces: dict[int, tuple[int, ...]], edge_faces) -> list[list[int]]:
    """The island's boundary loops, each in its faces' winding order, from its lowest vertex id.

    Raises ValueError for a vertex where the boundary meets itself (a pinch).
    """
    nxt: dict[int, list[int]] = defaultdict(list)
    incoming: Counter = Counter()
    for fid in faces:
        for a, b in _face_edges(faces[fid]):
            if len(edge_faces[_edge(a, b)]) == 1:
                nxt[a].append(b)
                incoming[b] += 1
    for v, out in nxt.items():
        if len(out) != 1 or incoming[v] != 1:
            raise ValueError("not a strip: the selection touches itself at a vertex")
    loops = []
    left = set(nxt)
    while left:
        start = min(left)
        loop, v = [], start
        while True:
            loop.append(v)
            left.discard(v)
            v = nxt[v][0]
            if v == start:
                break
            if v not in left:
                raise ValueError("not a strip: the selection touches itself at a vertex")
        loops.append(loop)
    return loops


def strip_from_faces(verts: dict[int, Vec3], faces: dict[int, tuple[int, ...]]) -> Strip:
    """The Strip of one edge-connected island of faces.

    ``faces`` maps face ids to their vertex ids in winding order; ``verts`` holds at
    least their positions. Raises ValueError("not a strip: ...") when the island is
    none of the three shapes in the module docstring, or its faces are wound against
    each other. The result follows the direction rule of the module docstring.
    """
    if not faces:
        raise ValueError("not a strip: no faces")
    edge_faces = _edge_faces(faces)
    for e, fs in edge_faces.items():
        if len(fs) > 2:
            raise ValueError("not a strip: an edge is shared by more than two faces")
        if len(fs) == 2:
            a, b = e
            dirs = [(a, b) in _face_edges(faces[f]) for f in fs]
            if dirs[0] == dirs[1]:
                raise ValueError("not a strip: the faces' normals do not agree")
    used = {v for face in faces.values() for v in face}
    verts = {v: tuple(verts[v]) for v in used}
    loops = _boundary_loops(faces, edge_faces)

    pairs: Counter = Counter()
    for fs in edge_faces.values():
        if len(fs) == 2:
            pairs[(fs[0], fs[1])] += 1
    if any(n > 1 for n in pairs.values()):
        raise ValueError("not a strip: two faces share more than one edge")
    nbrs: dict[int, list[int]] = {fid: [] for fid in faces}
    for a, b in pairs:
        nbrs[a].append(b)
        nbrs[b].append(a)
    degree = Counter(len(n) for n in nbrs.values())
    m = len(faces)

    if m == 1:
        (face,) = faces.values()
        if len(face) != 4:
            raise ValueError("not a strip: a single face must be a quad")
        return _grid_strip(verts, faces, loops[0], list(face))
    if m == 2 and len(loops) == 1 and len(loops[0]) == 4:
        return _grid_strip(verts, faces, loops[0], list(loops[0]))
    if degree[1] == 2 and degree[2] == m - 2:
        if len(loops) != 1:
            raise ValueError("not a strip: the chain of faces has a hole")
        return _open_chain(verts, faces, edge_faces, nbrs, loops[0])
    if degree[2] == m and m >= 3:
        if len(loops) != 2:
            raise ValueError("not a strip: the ring of faces has one boundary (twisted or pinched)")
        return _closed_chain(verts, faces, edge_faces, nbrs, loops)
    if len(loops) != 1:
        raise ValueError("not a strip: the selection has a hole")
    uses = Counter(v for face in faces.values() for v in face)
    corners = [v for v in loops[0] if uses[v] == 1]
    if len(corners) != 4:
        raise ValueError(f"not a strip: the selection branches ({len(corners)} corners, a strip has 4)")
    return _grid_strip(verts, faces, loops[0], corners)


def _chain_order(nbrs: dict[int, list[int]], start: int) -> list[int]:
    order, prev, cur = [start], None, start
    while True:
        nexts = sorted(n for n in nbrs[cur] if n != prev)
        if not nexts or nexts[0] == start:
            return order
        prev, cur = cur, nexts[0]
        order.append(cur)


def _shared_edge(faces, a: int, b: int) -> tuple[int, int]:
    ea = {_edge(*e) for e in _face_edges(faces[a])}
    (e,) = [_edge(*x) for x in _face_edges(faces[b]) if _edge(*x) in ea]
    return e


def _cap(verts, loop: list[int], owner: list[int], fid: int) -> tuple[int, int]:
    """Loop positions of an end face's cap: a boundary edge (two positions) or vertex (one, twice).

    ``owner[i]`` is the face of the loop edge from position i to i + 1. The end face's
    edges must be one run of the loop. An odd run's cap is its middle edge. An even
    run's cap is the middle edge at the run's middle-adjacent vertex with the smaller
    boundary angle (the sharper turn), when the two angles differ by more than
    ``CAP_ANGLE``; else it is the middle vertex.
    """
    n = len(loop)
    starts = [i for i in range(n) if owner[i] == fid and owner[i - 1] != fid]
    if len(starts) != 1:
        raise ValueError("not a strip: an end face's boundary is split")
    s = starts[0]
    k = 0
    while owner[(s + k) % n] == fid:
        k += 1
    if k % 2:
        return (s + (k - 1) // 2) % n, (s + (k + 1) // 2) % n
    mid = s + k // 2

    def turn(q: int) -> float:
        return _angle(verts[loop[(q - 1) % n]], verts[loop[q % n]], verts[loop[(q + 1) % n]])

    before, after = turn(mid - 1), turn(mid + 1)
    if abs(before - after) <= CAP_ANGLE:
        return mid % n, mid % n
    if before < after:
        return (mid - 1) % n, mid % n
    return mid % n, (mid + 1) % n


def _walk(loop: list[int], i: int, j: int) -> list[int]:
    """Loop vertices from position i forward to position j, both included."""
    n = len(loop)
    out = [loop[i]]
    while i != j:
        i = (i + 1) % n
        out.append(loop[i])
    return out


def _open_chain(verts, faces, edge_faces, nbrs, loop) -> Strip:
    ends = sorted(fid for fid, n in nbrs.items() if len(n) == 1)
    order = _chain_order(nbrs, ends[0])
    n = len(loop)
    owner = [edge_faces[_edge(loop[i], loop[(i + 1) % n])][0] for i in range(n)]
    a0, a1 = _cap(verts, loop, owner, order[0])
    b0, b1 = _cap(verts, loop, owner, order[-1])
    near = _walk(loop, a1, b0)
    far = _walk(loop, b1, a0)[::-1]
    strip = Strip(verts=verts, faces=dict(faces), near=near, far=far, rungs=[], closed=False, height=0.0)
    strip.height = _mean_width(strip)
    return _orient_open(strip)


def _area(verts, face: tuple[int, ...]) -> float:
    """Area of a face from its vector area (exact for planar faces)."""
    sx = sy = sz = 0.0
    for a, b in zip(face, face[1:] + face[:1]):
        p, q = verts[a], verts[b]
        sx += p[1] * q[2] - p[2] * q[1]
        sy += p[2] * q[0] - p[0] * q[2]
        sz += p[0] * q[1] - p[1] * q[0]
    return 0.5 * math.sqrt(sx * sx + sy * sy + sz * sz)


def _mean_width(strip: Strip) -> float:
    """A chain's height: its area over its length, so a triangulated strip gets the height of its quads."""
    length = strip_length(strip)
    if length <= TOL:
        return 0.0
    return sum(_area(strip.verts, face) for face in strip.faces.values()) / length


def _grid_strip(verts, faces, loop, corners) -> Strip:
    """An open strip from a boundary loop and its four corners (in any order)."""
    pos = sorted(loop.index(c) for c in corners)
    segs = [_walk(loop, pos[i], pos[(i + 1) % 4]) for i in range(4)]

    def pairing(r: int):
        rows = (segs[r], segs[r + 2])
        total = _length(verts, rows[0]) + _length(verts, rows[1])
        d = [b - a for a, b in zip(_centroid(verts, segs[(r + 3) % 4]), _centroid(verts, segs[r + 1]))]
        first = min(range(4), key=lambda i: _key(verts[loop[pos[i]]]))
        # the row from the first corner, to its other end's position
        row_end = next(s[-1] if s[0] == loop[pos[first]] else s[0] for s in rows if loop[pos[first]] in (s[0], s[-1]))
        return total, tuple(round(abs(c), 9) for c in d), _key(verts[row_end])

    p0, p1 = pairing(0), pairing(1)
    if abs(p0[0] - p1[0]) > TOL * max(p0[0], p1[0], 1.0):
        r = 0 if p0[0] > p1[0] else 1
    elif p0[1] != p1[1]:
        r = 0 if p0[1] > p1[1] else 1
    else:
        r = 0 if p0[2] <= p1[2] else 1
    segs = segs[r:] + segs[:r]
    near = segs[0]
    far = segs[2][::-1]
    sides = (segs[3][::-1][1:-1], segs[1][1:-1])
    height = (_length(verts, segs[1]) + _length(verts, segs[3])) / 2.0
    strip = Strip(verts=verts, faces=dict(faces), near=near, far=far, rungs=[], closed=False,
                  height=height, sides=sides)
    return _orient_open(strip)


def _orient_open(strip: Strip) -> Strip:
    """Swap an open strip's rows when its end with the smaller dominant-axis coordinate would not sit at u = 0."""
    end_a = [strip.near[0], *strip.sides[0], strip.far[0]]
    end_b = [strip.near[-1], *strip.sides[1], strip.far[-1]]
    ca, cb = _centroid(strip.verts, end_a), _centroid(strip.verts, end_b)
    a_first = _comes_first(ca, cb)
    if a_first is None:
        a_first = _key(ca) <= _key(cb)
    uv = stripe_uvs(strip)
    u_a = next(u for (_fid, vid), (u, _v) in uv.items() if vid == strip.near[0])
    a_at_zero = u_a < strip_length(strip) / 2.0
    if a_at_zero == a_first:
        return strip
    strip.near, strip.far = strip.far, strip.near
    strip.sides = (strip.sides[0][::-1], strip.sides[1][::-1])
    return strip


def _closed_chain(verts, faces, edge_faces, nbrs, loops) -> Strip:
    order = _chain_order(nbrs, min(faces))
    m = len(order)
    rungs3d = [_shared_edge(faces, order[i], order[(i + 1) % m]) for i in range(m)]
    # rung i lies between face order[i] and order[i + 1]; face order[i] lies between rungs i - 1 and i

    sets = [set(lp) for lp in loops]
    lens = [_length(verts, lp, closed=True) for lp in loops]
    cents = [_centroid(verts, lp) for lp in loops]
    first = _comes_first(cents[0], cents[1])
    if first is None:
        first = lens[0] >= lens[1] if abs(lens[0] - lens[1]) > TOL else _key(cents[0]) <= _key(cents[1])
    near_i = 0 if first else 1
    loops = [loops[near_i], loops[1 - near_i]]
    sets = [sets[near_i], sets[1 - near_i]]

    ends = []   # per rung: (near vertex, far vertex)
    for a, b in rungs3d:
        if a in sets[0] and b in sets[1]:
            ends.append((a, b))
        elif b in sets[0] and a in sets[1]:
            ends.append((b, a))
        else:
            raise ValueError("not a strip: a shared edge does not cross from one boundary to the other")

    # orient each loop so the rungs advance along it with the chain
    for side in (0, 1):
        loop = loops[side]
        at = {v: i for i, v in enumerate(loop)}
        for i in range(m):
            face = order[(i + 1) % m]          # between rung i and rung i + 1
            p = at[ends[i][side]]
            if ends[i][side] == ends[(i + 1) % m][side]:
                continue
            fwd = _edge(loop[p], loop[(p + 1) % len(loop)])
            if fwd not in {_edge(*e) for e in _face_edges(faces[face])}:
                loops[side] = loop[::-1]
            break

    pos = [[{v: i for i, v in enumerate(loops[s])}[ends[i][s]] for i in range(m)] for s in (0, 1)]
    cands = [i for i in range(m) if pos[0][i] != pos[0][i - 1] and pos[1][i] != pos[1][i - 1]]
    c = min(cands or range(m), key=lambda i: (_key(verts[ends[i][0]]), _key(verts[ends[i][1]])))

    rows, corner = [], [{}, {}]
    idx = [[0] * m, [0] * m]
    for s in (0, 1):
        n = len(loops[s])
        row = loops[s][pos[s][c]:] + loops[s][:pos[s][c]]
        idx[s] = [(pos[s][(c + k) % m] - pos[s][c]) % n for k in range(m)]
        if pos[s][c - 1] == pos[s][c]:
            # the rung before the start shares its vertex: list that vertex again at the end
            row = row + row[:1]
            k = m - 1
            while k > 0 and idx[s][k] == 0:
                idx[s][k] = n
                k -= 1
            v = row[0]
            for k in range(m):
                fid = order[(c + k + 1) % m]   # between rung list k and k + 1
                if v in faces[fid]:
                    corner[s][(fid, v)] = n if k == m - 1 or idx[s][k + 1] == n else 0
        if any(x > y for x, y in zip(idx[s], idx[s][1:])):
            raise ValueError("not a strip: the ring's boundaries do not follow its faces")
        rows.append(row)

    rungs = list(zip(idx[0], idx[1]))
    strip = Strip(verts=verts, faces=dict(faces), near=rows[0], far=rows[1], rungs=rungs, closed=True,
                  height=0.0, corner_near=corner[0], corner_far=corner[1])
    strip = ascending_rungs(strip)
    strip.height = _mean_width(strip)
    return strip
