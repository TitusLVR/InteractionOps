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
  is the middle vertex, where both rows start. An end face of more than four
  vertices (a quad whose rails or end carry extra vertices) has its cap between
  the two of its run's inner vertices with the sharpest face corners, when both
  are below ``CORNER_ANGLE``; the vertices between them are that end's sides.
  The caps split the boundary into the two rows. A single quad, or two triangles
  forming one, is the quad.
- a closed chain: a ring of faces, each sharing one edge with each of two others.
  Its two boundary loops are the rows, every shared edge is a rung.
- a quad-grid patch wider than one face: the four boundary vertices used by one
  face only are the corners; the pair of opposite sides with the larger summed
  length are the rows, the other two the ends.

A chain's shared edges are its rungs. ``bend_cut_rungs`` picks the rungs where a
built strip turns within its own surface, and ``slice_strip`` tears a built strip
at given rungs by slicing its rows, so the pieces need no rebuilding and may be of
any face size (``split_strip`` does both). A ring is cut open at one rung
(``seam_edge``, or ``Strip.seam``); ``face_islands`` can treat edges as cuts.

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
CORNER_ANGLE = math.radians(150.0)


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


def face_islands(
    faces: dict[int, tuple[int, ...]], cut_edges: frozenset | set = frozenset()
) -> list[dict[int, tuple[int, ...]]]:
    """Edge-connected components of the face set, ordered by their lowest face id.

    An edge in ``cut_edges`` (a sorted vertex-id pair) does not connect its faces.
    """
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
                if _edge(a, b) in cut_edges:
                    continue
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


def strip_from_faces(
    verts: dict[int, Vec3],
    faces: dict[int, tuple[int, ...]],
    seam_edge: tuple[int, int] | None = None,
    near: set[int] | None = None,
) -> Strip:
    """The Strip of one edge-connected island of faces.

    ``faces`` maps face ids to their vertex ids in winding order; ``verts`` holds at
    least their positions. Raises ValueError("not a strip: ...") when the island is
    none of the three shapes in the module docstring, or its faces are wound against
    each other. The result follows the direction rule of the module docstring.
    A closed ring is cut at ``seam_edge`` (a vertex-id pair) when that is one of its
    shared edges (``Strip.seam``); otherwise ``seam_edge`` is ignored. An open chain's
    rungs are its shared edges in chain order. ``near`` (vertex ids) overrides the
    direction rule: the row holding more of them becomes the near row (v = 0); on a
    tie the direction rule decides.
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
        return _grid_strip(verts, faces, loops[0], list(face), near)
    if m == 2 and len(loops) == 1 and len(loops[0]) == 4:
        return _grid_strip(verts, faces, loops[0], list(loops[0]), near)
    if degree[1] == 2 and degree[2] == m - 2:
        if len(loops) != 1:
            raise ValueError("not a strip: the chain of faces has a hole")
        return _open_chain(verts, faces, edge_faces, nbrs, loops[0], near)
    if degree[2] == m and m >= 3:
        if len(loops) != 2:
            raise ValueError("not a strip: the ring of faces has one boundary (twisted or pinched)")
        return _closed_chain(verts, faces, edge_faces, nbrs, loops, seam_edge, near)
    if len(loops) != 1:
        raise ValueError("not a strip: the selection has a hole")
    uses = Counter(v for face in faces.values() for v in face)
    corners = [v for v in loops[0] if uses[v] == 1]
    if len(corners) != 4:
        raise ValueError(f"not a strip: the selection branches ({len(corners)} corners, a strip has 4)")
    return _grid_strip(verts, faces, loops[0], corners, near)


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


def _cap(verts, loop: list[int], owner: list[int], fid: int, face: tuple[int, ...]) -> tuple[int, int]:
    """Loop positions of the ends of an end face's cap, in loop order: one edge, a run, or a vertex (twice).

    ``owner[i]`` is the face of the loop edge from position i to i + 1. The end face's
    edges must be one run of the loop. A face of more than four vertices: the cap runs
    between the two inner vertices of that run with the smallest face corner angles,
    when both are below ``CORNER_ANGLE``. Otherwise an odd run's cap is its middle edge,
    and an even run's cap is the middle edge at the run's middle-adjacent vertex with
    the smaller boundary angle (the sharper turn), when the two angles differ by more
    than ``CAP_ANGLE``; else it is the middle vertex.
    """
    n = len(loop)
    starts = [i for i in range(n) if owner[i] == fid and owner[i - 1] != fid]
    if len(starts) != 1:
        raise ValueError("not a strip: an end face's boundary is split")
    s = starts[0]
    k = 0
    while owner[(s + k) % n] == fid:
        k += 1
    if len(face) > 4 and k >= 3:
        m = len(face)

        def corner(v: int) -> float:
            i = face.index(v)
            return _angle(verts[face[i - 1]], verts[v], verts[face[(i + 1) % m]])

        inner = sorted(range(1, k), key=lambda t: (corner(loop[(s + t) % n]), t))[:2]
        if all(corner(loop[(s + t) % n]) < CORNER_ANGLE for t in inner):
            t0, t1 = sorted(inner)
            return (s + t0) % n, (s + t1) % n
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


def _open_chain(verts, faces, edge_faces, nbrs, loop, near_ids=None) -> Strip:
    ends = sorted(fid for fid, n in nbrs.items() if len(n) == 1)
    order = _chain_order(nbrs, ends[0])
    n = len(loop)
    owner = [edge_faces[_edge(loop[i], loop[(i + 1) % n])][0] for i in range(n)]
    a0, a1 = _cap(verts, loop, owner, order[0], faces[order[0]])
    b0, b1 = _cap(verts, loop, owner, order[-1], faces[order[-1]])
    near = _walk(loop, a1, b0)
    far = _walk(loop, b1, a0)[::-1]
    sides = (_walk(loop, a0, a1)[1:-1][::-1], _walk(loop, b0, b1)[1:-1]) if a0 != a1 or b0 != b1 else ([], [])
    strip = Strip(verts=verts, faces=dict(faces), near=near, far=far, rungs=_chain_rungs(faces, order, near, far),
                  closed=False, height=0.0, sides=sides)
    strip.height = _mean_width(strip)
    return _orient_open(strip, near_ids)


def _chain_rungs(faces, order, near, far) -> list[tuple[int, int]]:
    """(near index, far index) of each shared edge in chain order; none when they do not ascend on both rows.

    A shared edge with no end on one of the rows (a fan's edge at a pointed tip) is left out.
    """
    near_at = {v: i for i, v in enumerate(near)}
    far_at = {v: i for i, v in enumerate(far)}
    rungs = []
    for f, g in zip(order, order[1:]):
        x, y = _shared_edge(faces, f, g)
        if x in near_at and y in far_at:
            rungs.append((near_at[x], far_at[y]))
        elif y in near_at and x in far_at:
            rungs.append((near_at[y], far_at[x]))
    if any(a[0] > b[0] or a[1] > b[1] for a, b in zip(rungs, rungs[1:])):
        return []
    return rungs


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


def _grid_strip(verts, faces, loop, corners, near_ids=None) -> Strip:
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
    return _orient_open(strip, near_ids)


def _held(ids: set[int] | None, row: list[int]) -> int:
    return sum(v in ids for v in set(row)) if ids else 0


def _orient_open(strip: Strip, near_ids: set[int] | None = None) -> Strip:
    """Swap an open strip's rows when its end with the smaller dominant-axis coordinate would not sit at u = 0.

    With ``near_ids`` the row holding more of them is made the near row instead (a tie
    falls back to the direction rule).
    """
    held_near, held_far = _held(near_ids, strip.near), _held(near_ids, strip.far)
    if held_near != held_far:
        return _swap_rows(strip) if held_far > held_near else strip
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
    return _swap_rows(strip)


def _swap_rows(strip: Strip) -> Strip:
    """An open strip turned round: near and far swap, the sides and rungs follow."""
    strip.near, strip.far = strip.far, strip.near
    strip.sides = (strip.sides[0][::-1], strip.sides[1][::-1])
    strip.rungs = [(f, n) for n, f in strip.rungs]
    return strip


def _closed_chain(verts, faces, edge_faces, nbrs, loops, seam_edge=None, near_ids=None) -> Strip:
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
    held = [_held(near_ids, lp) for lp in loops]
    if held[0] != held[1]:
        near_i = 0 if held[0] > held[1] else 1
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
    if seam_edge is not None and _edge(*seam_edge) in rungs3d:
        c = rungs3d.index(_edge(*seam_edge))

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
    if seam_edge is not None and _edge(*seam_edge) in rungs3d:
        strip.seam = 0     # the rows start at the seam rung
    return strip


def _deficits(strip: Strip) -> dict[int, float]:
    """Each vertex's sum of the strip faces' corner angles at it, minus pi."""
    sums: dict[int, float] = defaultdict(float)
    for face in strip.faces.values():
        n = len(face)
        for k, v in enumerate(face):
            sums[v] += _angle(strip.verts[face[k - 1]], strip.verts[v], strip.verts[face[(k + 1) % n]])
    return {v: a - math.pi for v, a in sums.items()}


def _row_cycle(row: list[int]) -> int:
    """A closed row's number of positions round the loop: one less when it lists its first vertex again last."""
    return len(row) - 1 if len(row) > 1 and row[-1] == row[0] else len(row)


def bend_cut_rungs(strip: Strip, angle: float) -> list[int]:
    """The rungs (indices into ``strip.rungs``) to tear a built strip at, by its bends.

    The turn is measured in the surface: a rail vertex's deficit is the sum of the
    strip faces' corner angles at it minus pi, so a fold across the cross edges (a
    strip wrapped round a cylinder) turns 0 and a strip bending in its own plane
    turns by its bend. Walking the rungs in order, each end not yet counted adds
    (far deficit - near deficit) / 2 (an open strip's end corners never count). A rung
    that advances both rows over the last such rung, an open strip's start being the
    first (a post: a cross edge, not a fan or a triangulation's diagonal), is cut
    when the turn so far exceeds ``angle`` in size, and the turn restarts at 0
    there. A closed strip with a single cut gets none.
    """
    if not strip.rungs:
        return []
    deficit = _deficits(strip)
    near, far = strip.near, strip.far
    # an open strip's row ends are its end corners, not bends; its start is the first post
    counted: set[int] = set() if strip.closed else {near[0], near[-1], far[0], far[-1]}
    turn = 0.0
    last = (-1, -1) if strip.closed else (0, 0)
    cuts = []
    for k, (i, j) in enumerate(strip.rungs):
        a, b = near[i % len(near)], far[j % len(far)]
        for v, sign in ((b, 1.0), (a, -1.0)):
            if v not in counted:
                counted.add(v)
                turn += sign * deficit.get(v, 0.0) / 2.0
        if i > last[0] and j > last[1]:
            last = (i, j)
            if abs(turn) > angle:
                cuts.append(k)
                turn = 0.0
    if strip.closed and len(cuts) == 1:
        return []
    return cuts


def bend_cuts(verts: dict[int, Vec3], faces: dict[int, tuple[int, ...]], angle: float) -> set[tuple[int, int]]:
    """The cross edges (sorted vertex-id pairs) to tear an island at by its bends (``bend_cut_rungs``).

    The island is built with ``strip_from_faces``; anything that is not a chain gets
    no cuts. Never raises.
    """
    try:
        strip = strip_from_faces(verts, faces)
    except ValueError:
        return set()
    return {rung_edge(strip, k) for k in bend_cut_rungs(strip, angle)}


def rung_edge(strip: Strip, k: int) -> tuple[int, int]:
    """The sorted vertex-id pair of rung ``k``."""
    i, j = strip.rungs[k]
    return _edge(strip.near[i % len(strip.near)], strip.far[j % len(strip.far)])


def rungs_at(strip: Strip, edges) -> list[int]:
    """The rungs (indices) whose vertex pair is one of ``edges`` (sorted vertex-id pairs)."""
    edges = set(edges)
    return [k for k in range(len(strip.rungs)) if rung_edge(strip, k) in edges]


def slice_strip(strip: Strip, cuts: list[int]) -> list[Strip]:
    """A built strip torn at the given rungs (indices into ``strip.rungs``), as pieces in row order.

    The rows are sliced between consecutive cut rungs; each piece is an open strip with
    those slices as its rows, the rungs between them re-indexed, the same orientation
    and ``layout``, and the strip's height ("TRUE": its own area over its length, the
    true width). Every face goes to the piece whose row slices hold all its row corners
    (faces joined by an edge that is no cut stay together). An open strip's end sides
    stay with its first and last piece. A closed strip with one cut is that strip cut
    open there (``Strip.seam``); with more, the pieces run between consecutive cuts,
    the last one wrapping round. Raises ValueError when a cut leaves a piece without a
    row, a face fits no piece or more than one, or a piece cannot be laid out.
    """
    cuts = sorted(set(cuts))
    if not cuts:
        return [strip]
    if strip.closed and len(cuts) == 1:
        return [_cut_open(strip, cuts[0])]
    near, far, rungs = strip.near, strip.far, strip.rungs
    if strip.closed:
        nn, nf = _row_cycle(near), _row_cycle(far)
        bounds = [rungs[k] for k in cuts]
        bounds = [(i % nn, j % nf) for i, j in bounds]
        spans = []
        for t, (a, b) in enumerate(bounds):
            c, d = bounds[(t + 1) % len(bounds)]
            spans.append((a, a + (c - a) % nn, b, b + (d - b) % nf))
    else:
        nn, nf = len(near), len(far)
        bounds = [(0, 0)] + [rungs[k] for k in cuts] + [(nn - 1, nf - 1)]
        spans = [(a, c, b, d) for (a, b), (c, d) in zip(bounds, bounds[1:])]
    if any(a1 <= a0 or b1 <= b0 for a0, a1, b0, b1 in spans):
        raise ValueError("a tear leaves a piece without a row")

    def within(p: int, lo: int, hi: int, n: int) -> bool:
        return (p - lo) % n <= hi - lo if strip.closed else lo <= p <= hi

    near_at = {v: i for i, v in enumerate(near)}
    far_at: dict[int, list[int]] = defaultdict(list)
    for i, v in enumerate(far):
        far_at[v].append(i)
    cut_edges = {rung_edge(strip, k) for k in cuts}
    fits: dict[int, set[int]] = {}
    for fid, face in strip.faces.items():
        ok = set(range(len(spans)))
        for v in face:
            if v in near_at:
                p = strip.corner_near.get((fid, v), near_at[v])
                ok &= {t for t, (a0, a1, _b0, _b1) in enumerate(spans) if within(p, a0, a1, nn)}
            elif v in far_at:
                ps = [strip.corner_far[(fid, v)]] if (fid, v) in strip.corner_far else far_at[v]
                ok &= {t for t, (_a0, _a1, b0, b1) in enumerate(spans) if any(within(p, b0, b1, nf) for p in ps)}
        fits[fid] = ok
    pieces_faces: list[dict[int, tuple[int, ...]]] = [{} for _ in spans]
    for island in face_islands(strip.faces, frozenset(cut_edges)):
        ok = set.intersection(*(fits[fid] for fid in island))
        if len(ok) != 1:
            raise ValueError("a face lies across a tear")
        pieces_faces[ok.pop()].update(island)
    out = []
    for t, (a0, a1, b0, b1) in enumerate(spans):
        faces = pieces_faces[t]
        if not faces:
            raise ValueError("a tear leaves a piece without faces")
        piece_rungs = []
        for i, j in rungs:
            for wrap_i in (0, nn) if strip.closed else (0,):
                for wrap_j in (0, nf) if strip.closed else (0,):
                    ii, jj = i % nn + wrap_i if strip.closed else i, j % nf + wrap_j if strip.closed else j
                    if a0 <= ii <= a1 and b0 <= jj <= b1:
                        piece_rungs.append((ii - a0, jj - b0))
        piece_rungs = sorted(set(piece_rungs))
        if any(x[1] > y[1] for x, y in zip(piece_rungs, piece_rungs[1:])):
            piece_rungs = []
        corner_near = {}
        for key, p in strip.corner_near.items():
            if key[0] in faces:
                q = (p - a0) % nn if strip.closed else p - a0
                if not 0 <= q <= a1 - a0:
                    raise ValueError("a seam corner lies outside its piece")
                corner_near[key] = q
        corner_far = {}
        for key, p in strip.corner_far.items():
            if key[0] in faces:
                q = (p - b0) % nf if strip.closed else p - b0
                if not 0 <= q <= b1 - b0:
                    raise ValueError("a collapsed corner lies outside its piece")
                corner_far[key] = q
        piece_near = [near[(a0 + x) % nn] for x in range(a1 - a0 + 1)] if strip.closed else near[a0:a1 + 1]
        piece_far = [far[(b0 + x) % nf] for x in range(b1 - b0 + 1)] if strip.closed else far[b0:b1 + 1]
        sides = (strip.sides[0] if not strip.closed and t == 0 else [],
                 strip.sides[1] if not strip.closed and t == len(spans) - 1 else [])
        piece = Strip(verts=strip.verts, faces=faces, near=piece_near, far=piece_far, rungs=piece_rungs,
                      closed=False, height=strip.height, sides=sides, corner_far=corner_far,
                      corner_near=corner_near, layout=strip.layout)
        if strip.layout == "TRUE":
            width = _mean_width(piece)
            if width > TOL:
                piece.height = width
        if strip_length(piece) <= TOL or piece.height <= TOL:
            raise ValueError("a piece has no size")
        stripe_uvs(piece)
        out.append(piece)
    return out


def _cut_open(strip: Strip, k: int) -> Strip:
    """A closed strip with its seam at rung ``k``; raises ValueError when that layout fails."""
    piece = Strip(**{**strip.__dict__, "seam": k})
    stripe_uvs(piece)
    return piece


def split_strip(strip: Strip, angle: float, extra_cuts=()) -> tuple[list[Strip], str | None]:
    """A built strip torn at its bends (``bend_cut_rungs``) and at ``extra_cuts`` (rung indices).

    Returns the pieces (``slice_strip``) and None, or, when there are cuts but the
    strip cannot be torn there, the strip whole and the reason. ``angle`` None: no
    bend cuts. Never raises ValueError.
    """
    try:
        cuts = set(extra_cuts)
        if angle is not None:
            cuts |= set(bend_cut_rungs(strip, angle))
    except ValueError as exc:
        return [strip], str(exc)
    if not cuts:
        return [strip], None
    try:
        return slice_strip(strip, sorted(cuts)), None
    except ValueError as exc:
        return [strip], str(exc)
