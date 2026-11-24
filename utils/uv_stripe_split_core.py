"""UV Stripe: an island that is no strip, cut into strips; each part is then laid out as its own strip.

Pure Python (stdlib only), no bpy, so it runs under plain pytest.

A *cross path* (``cross_path``) is a run of inner edges from one boundary vertex
to another, going straight on through every inner vertex it meets (one with four
edges: on through the edge that shares no face with the one it came by), the way
a loop cut runs across a strip of quads. Cutting along it splits the island in two.

``split_island`` cuts an island along the cross paths through the edges cut by
hand first; a part that is still no strip (``strip_from_faces`` refuses it: a
branch, a fork, a slit) is then cut automatically along the cross paths that
start or end at a concave boundary vertex (a junction's inner corner, a slit's
tip), the cut sets of one, two, then three paths tried in turn. Of the cut sets
that leave only strips the one with the fewest parts wins, then (with a seed face)
the one whose part holding the seed face is largest, then the one whose main part
holds the most guide faces, then the one cutting at the most concave vertices.

The parts are put in strip order (``Split.parts``): the *main* part first, the
one holding the seed face, else the most guide faces, else the most faces. When
the cuts join the parts in a row (each part cut from at most two others) the row
is followed from its end nearest the main part; otherwise (a branch) every other
part follows the main one, nearest first. Each part is its own strip (decided
2026-11-24): the pieces are placed like any strips, not joined into one.
"""

import math
from collections import defaultdict
from itertools import combinations
from dataclasses import dataclass, field

from .uv_stripe_core import Strip, Vec3
from .uv_stripe_select_core import CAP_ANGLE, _boundary_loops, _edge_faces, _surface_angle, face_islands, \
    strip_from_faces

MAX_CUT_PATHS = 12      # at most this many concave cross paths are tried as automatic cuts
MAX_CUT_SET = 3         # at most this many automatic cuts in one part
GROUP_GAP = 1.2         # the four gaps between corner groups must be this much longer than any gap inside one


def _edge(a: int, b: int) -> tuple[int, int]:
    return (a, b) if a < b else (b, a)


@dataclass
class Split:
    """An island cut into strips. ``parts`` are face sets (face id -> vertex ids) in strip order, the main part
    first; ``entries[i]`` is the set of vertex ids of the cut that joins part i to a part before it (None for
    the first part), ``exits[i]`` of the cut to the part after it in a row (None when the next part is a
    branch, or for the last); ``cuts`` every cut edge (sorted vertex-id pair); ``automatic`` whether any cut
    was made without a hand-made cut asking for it."""

    parts: list = field(default_factory=list)
    entries: list = field(default_factory=list)
    exits: list = field(default_factory=list)
    cuts: set = field(default_factory=set)
    automatic: bool = False
    auto_cuts: set = field(default_factory=set)    # the cut edges no hand-made cut asked for


def _adjacency(faces):
    edge_faces = _edge_faces(faces)
    vert_edges: dict[int, set] = defaultdict(set)
    for e in edge_faces:
        vert_edges[e[0]].add(e)
        vert_edges[e[1]].add(e)
    boundary = {v for e, fs in edge_faces.items() if len(fs) == 1 for v in e}
    return edge_faces, vert_edges, boundary


def cross_path(faces: dict[int, tuple[int, ...]], edge: tuple[int, int], adjacency=None) -> list[tuple[int, int]] | None:
    """The cross path through the inner edge ``edge`` (a vertex-id pair) of ``faces``, as sorted vertex-id pairs
    from one boundary vertex to the other; None when ``edge`` is no inner edge, or the path meets an inner
    vertex without four edges, runs into itself or along a boundary edge."""
    edge_faces, vert_edges, boundary = adjacency or _adjacency(faces)
    edge = _edge(*edge)
    if len(edge_faces.get(edge, ())) != 2:
        return None
    halves = []
    for start in edge:
        path, cur, at = [], edge, start
        seen = {edge}
        while at not in boundary:
            around = vert_edges[at]
            if len(around) != 4:
                return None
            beside = {e for fid in edge_faces[cur] for e in _face_edges_at(faces[fid], at)} - {cur}
            nxt = [e for e in around if e != cur and e not in beside]
            if len(nxt) != 1 or nxt[0] in seen or len(edge_faces[nxt[0]]) != 2:
                return None
            cur = nxt[0]
            seen.add(cur)
            path.append(cur)
            at = cur[0] if cur[1] == at else cur[1]
        halves.append((path, at))
    (a, end_a), (b, end_b) = halves
    if end_a == end_b or set(a) & set(b):
        return None
    out = a[::-1] + [edge] + b
    used = [v for e in out for v in e]
    if len(set(used)) != len(out) + 1:        # a vertex met twice
        return None
    return out


CHAIN_TURN = math.radians(30.0)     # a line of edges turns by at most this at a vertex (``chain_through``)
CHAIN_AXIS = math.radians(45.0)     # and each of its edges runs within this of its axis


def _unit(p, q):
    dx, dy = q[0] - p[0], q[1] - p[1]
    n = math.hypot(dx, dy)
    return None if n <= 1e-15 else (dx / n, dy / n)


def chain_through(faces: dict[int, tuple[int, ...]], pos, edge: tuple[int, int], adjacency=None,
                  max_turn: float = CHAIN_TURN) -> tuple[str, list[tuple[int, int]]] | None:
    """The line of edges through ``edge`` of ``faces``, followed by direction through quads, triangles and n-gons
    alike: (axis, its edges as sorted vertex-id pairs in order), or None.

    ``pos`` holds every vertex's laid-out place in the strip's own frame (x along the strip, y across it). The
    axis is the one ``edge`` runs nearer to: "ALONG" (x) or "ACROSS" (y); an edge further than ``max_turn``
    from both (a diagonal) has no line. From each end the line goes on, at every vertex, with the edge that
    turns least from the one it came by, when that turn is within ``max_turn`` and the edge runs within
    ``CHAIN_AXIS`` of the axis; it stops where none does, where it meets itself, and (a line through the inside)
    at the boundary. A line starting on a boundary edge (a long side, an end) keeps to the boundary edges."""
    edge_faces, vert_edges, boundary = adjacency or _adjacency(faces)
    edge = _edge(*edge)
    if edge not in edge_faces or edge[0] not in pos or edge[1] not in pos:
        return None
    d = _unit(pos[edge[0]], pos[edge[1]])
    if d is None:
        return None
    k = 0 if abs(d[0]) >= abs(d[1]) else 1
    if math.atan2(abs(d[1 - k]), abs(d[k])) > max_turn:
        return None
    rim = len(edge_faces[edge]) == 1
    used, seen = {edge}, set(edge)
    halves = []
    for start, at in ((edge[1], edge[0]), (edge[0], edge[1])):
        path, came, cur = [], _unit(pos[start], pos[at]), at
        while came is not None:
            if not rim and cur in boundary:
                break
            best = None
            for e in vert_edges[cur]:
                if e in used or (len(edge_faces[e]) == 1) != rim:
                    continue
                nxt = e[0] if e[1] == cur else e[1]
                if nxt in seen or nxt not in pos:
                    continue
                go = _unit(pos[cur], pos[nxt])
                if go is None or math.atan2(abs(go[1 - k]), abs(go[k])) > CHAIN_AXIS:
                    continue
                turn = math.acos(max(-1.0, min(1.0, came[0] * go[0] + came[1] * go[1])))
                if turn <= max_turn and (best is None or turn < best[0]):
                    best = (turn, e, nxt, go)
            if best is None:
                break
            _turn, e, nxt, go = best
            used.add(e)
            seen.add(nxt)
            path.append(e)
            came, cur = go, nxt
        halves.append(path)
    return ("ALONG" if k == 0 else "ACROSS"), halves[0][::-1] + [edge] + halves[1]


def _face_edges_at(face: tuple[int, ...], v: int) -> list[tuple[int, int]]:
    n = len(face)
    k = face.index(v)
    return [_edge(face[k - 1], v), _edge(v, face[(k + 1) % n])]


def _path_ends(path: list[tuple[int, int]]) -> tuple[int, int]:
    count: dict[int, int] = defaultdict(int)
    for e in path:
        for v in e:
            count[v] += 1
    ends = sorted(v for v, c in count.items() if c == 1)
    return ends[0], ends[1]


def concave_paths(verts, faces) -> list[tuple[float, list[tuple[int, int]]]]:
    """The cross paths of ``faces`` with an end at a concave boundary vertex (its angle within the surface over
    half a turn, ``uv_stripe_select_core._surface_angle``), as (how concave both ends are together, path),
    the most concave first, at most ``MAX_CUT_PATHS``; each path once."""
    adjacency = _adjacency(faces)
    edge_faces, _vert_edges, boundary = adjacency
    concave = {v: max(0.0, _surface_angle(verts, faces, v) - math.pi) for v in boundary}
    seen, out = set(), []
    for e in sorted(edge_faces):
        if len(edge_faces[e]) != 2:
            continue
        path = cross_path(faces, e, adjacency)
        if path is None:
            continue
        key = frozenset(path)
        if key in seen:
            continue
        seen.add(key)
        a, b = _path_ends(path)
        score = concave[a] + concave[b]
        if score > 1e-6:
            out.append((score, path))
    out.sort(key=lambda x: (-round(x[0], 9), sorted(x[1])))
    return out[:MAX_CUT_PATHS]


BEND_TEAR_ANGLE = CAP_ANGLE     # a wide strip may be torn across where a rail turns within the surface by this


def bend_paths(strip: Strip, angle: float = BEND_TEAR_ANGLE) -> list[list[tuple[int, int]]]:
    """Where a strip several faces wide bends within its surface: its cross paths (``cross_path``) from one rail
    to the other with an end at a rail vertex (not a corner) that turns within the surface
    (``uv_stripe_select_core._surface_angle``) by more than ``angle``, either way. The sharpest bend first,
    then by edges; each path once. Empty for a closed strip."""
    if strip.closed:
        return []
    faces, verts = strip.faces, strip.verts
    adjacency = _adjacency(faces)
    edge_faces = adjacency[0]
    corners = {strip.near[0], strip.near[-1], strip.far[0], strip.far[-1]}
    near, far = set(strip.near) - corners, set(strip.far) - corners
    turn = {}
    for v in near | far:
        turn[v] = abs(math.pi - _surface_angle(verts, faces, v))
    seen, out = set(), []
    for v in sorted(v for v in turn if turn[v] > angle):
        for e in sorted(e for e in edge_faces if v in e and len(edge_faces[e]) == 2):
            path = cross_path(faces, e, adjacency)
            if path is None or frozenset(path) in seen:
                continue
            a, b = _path_ends(path)
            if not (a in near and b in far or a in far and b in near):
                continue
            seen.add(frozenset(path))
            out.append((max(turn[a], turn[b]), path))
    out.sort(key=lambda x: (-round(x[0], 9), sorted(x[1])))
    return [path for _score, path in out]


def _reads(verts, part, seed) -> bool:
    try:
        strip_from_faces(verts, part, seed=seed if seed in part else None)
    except ValueError:
        return False
    return True


def _cut(faces, edges) -> list[dict]:
    return face_islands(faces, frozenset(edges))


def _resolve(verts, part, seed, guides, skip=frozenset()) -> tuple[list[dict], set] | None:
    """The best automatic cut of ``part`` (module docstring): (its parts, the cut edges), or None. A cross path
    holding an edge of ``skip`` (an automatic cut taken back by hand) is never cut."""
    paths = [(score, path) for score, path in concave_paths(verts, part) if not set(path) & skip]
    for size in range(1, min(MAX_CUT_SET, len(paths)) + 1):
        best = None
        for combo in combinations(range(len(paths)), size):
            edges = {e for k in combo for e in paths[k][1]}
            parts = _cut(part, edges)
            if len(parts) < 2 or not all(_reads(verts, p, seed) for p in parts):
                continue
            seeded = max((len(p) for p in parts if seed in p), default=0)
            main = _main(parts, seed, guides)
            key = (len(parts), -seeded, -len(set(guides) & set(parts[main])),
                   -round(sum(paths[k][0] for k in combo), 9), sorted(edges))
            if best is None or key < best[0]:
                best = (key, parts, edges)
        if best is not None:
            return best[1], best[2]
    return None


def _main(parts, seed, guides) -> int:
    """The main part's index: the one holding ``seed``, else the most ``guides``, else the most faces, then the
    lowest face id."""
    for i, p in enumerate(parts):
        if seed is not None and seed in p:
            return i
    gs = set(guides)
    return min(range(len(parts)), key=lambda i: (-len(gs & set(parts[i])), -len(parts[i]), min(parts[i])))


def split_island(verts: dict[int, Vec3], faces: dict[int, tuple[int, ...]], cuts=(), seed: int | None = None,
                 guides=(), skip=()) -> Split:
    """``faces`` (one island) cut into strips (module docstring). ``cuts`` are edges (vertex-id pairs) cut by
    hand: each cuts along its cross path, or alone when it has none. No automatic cut runs along a cross path
    holding an edge of ``skip`` (automatic cuts taken back by hand). Raises ValueError("not a strip: ...")
    when some part cannot be cut into strips, with the reason of the first such part."""
    skip = frozenset(_edge(*e) for e in skip)
    adjacency = _adjacency(faces)
    edges: set = set()
    for e in cuts:
        e = _edge(*e)
        if len(adjacency[0].get(e, ())) != 2:
            continue
        edges.update(cross_path(faces, e, adjacency) or [e])
    automatic = False
    auto: set = set()
    parts = []
    for part in _cut(faces, edges):
        if _reads(verts, part, seed):
            parts.append(part)
            continue
        found = _resolve(verts, part, seed, guides, skip)
        if found is None:
            try:
                strip_from_faces(verts, part, seed=seed if seed in part else None)
            except ValueError as exc:
                raise ValueError(str(exc)) from None
            raise ValueError("not a strip: it cannot be cut into strips")
        parts.extend(found[0])
        edges |= found[1]
        auto |= found[1]
        automatic = True
    out = _order(verts, faces, parts, edges, seed, guides, automatic)
    out.auto_cuts = auto
    return out


def _order(verts, faces, parts, edges, seed, guides, automatic) -> Split:
    owner = {fid: i for i, p in enumerate(parts) for fid in p}
    edge_faces = _edge_faces(faces)
    links: dict[tuple[int, int], set] = defaultdict(set)
    for e in edges:
        fs = edge_faces.get(e, [])
        if len(fs) == 2 and owner[fs[0]] != owner[fs[1]]:
            a, b = sorted((owner[fs[0]], owner[fs[1]]))
            links[(a, b)].update(e)
    nbrs: dict[int, set] = defaultdict(set)
    for a, b in links:
        nbrs[a].add(b)
        nbrs[b].add(a)
    main = _main(parts, seed, guides)
    row = all(len(nbrs[i]) <= 2 for i in range(len(parts))) and len(links) == len(parts) - 1
    order: list[int] = []
    if row and len(parts) > 1:
        ends = [i for i in range(len(parts)) if len(nbrs[i]) <= 1]
        start = ends[0] if main in (ends[0],) else ends[1] if main == ends[1] else _nearer_end(ends, main, nbrs)
        prev, cur = None, start
        while cur is not None:
            order.append(cur)
            nxt = [n for n in sorted(nbrs[cur]) if n != prev]
            prev, cur = cur, (nxt[0] if nxt else None)
    else:
        order = [main]
        todo = [main]
        while todo:
            cur = todo.pop(0)
            for n in sorted(nbrs[cur], key=lambda i: min(parts[i])):
                if n not in order:
                    order.append(n)
                    todo.append(n)
        order += [i for i in sorted(range(len(parts)), key=lambda i: min(parts[i])) if i not in order]
    out = Split(cuts=set(edges), automatic=automatic)
    for k, i in enumerate(order):
        out.parts.append(parts[i])
        entry = None
        for j in order[:k]:
            key = (min(i, j), max(i, j))
            if key in links:
                entry = frozenset(links[key])
                break
        out.entries.append(entry)
        nxt = order[k + 1] if k + 1 < len(order) else None
        out.exits.append(frozenset(links[(min(i, nxt), max(i, nxt))]) if row and nxt is not None else None)
    return out


def _nearer_end(ends, main, nbrs) -> int:
    """The end of a row of parts fewer steps from ``main``; the first end on a tie."""
    def steps(start):
        dist, todo = {start: 0}, [start]
        while todo:
            cur = todo.pop(0)
            for n in nbrs[cur]:
                if n not in dist:
                    dist[n] = dist[cur] + 1
                    todo.append(n)
        return dist.get(main, 0)
    return min(ends, key=lambda e: (steps(e), e))


def _end_lists(strip: Strip) -> tuple[list[int], list[int]]:
    return ([strip.near[0], *strip.sides[0], strip.far[0]], [strip.near[-1], *strip.sides[1], strip.far[-1]])


def _end_holding(strip: Strip, cut) -> int | None:
    """Which end of the open ``strip`` (0 at ``near[0]``, 1 at ``near[-1]``) holds two or more of the vertex ids
    ``cut``; None when neither does (a cut along a rail) or the strip is closed."""
    if cut is None or strip.closed:
        return None
    hits = [len(set(end) & set(cut)) for end in _end_lists(strip)]
    if max(hits) < 2 or hits[0] == hits[1]:
        return None
    return 0 if hits[0] > hits[1] else 1


def boundary_corners(verts, faces) -> tuple[list[int], list[int]]:
    """For the help shown on an island that is no strip: (its boundary loop's vertex ids in order, the
    candidates for its corners among them: the vertices turning within the surface by more than
    ``CAP_ANGLE``, convex). Empty lists for an island with no single boundary loop."""
    try:
        loops = _boundary_loops(faces, _edge_faces(faces))
    except ValueError:
        return [], []
    if len(loops) != 1:
        return [], []
    loop = loops[0]
    return loop, [v for v in loop if math.pi - _surface_angle(verts, faces, v) > CAP_ANGLE]


def can_be_helped(verts, faces) -> bool:
    """Whether picked corners or a cut could make the island ``faces`` read as strips, for an island no rule
    reads: it has one boundary loop and either a concave boundary vertex (a branch, a fork, a slit: a cut can
    split it there) or exactly four clear corner groups (the convex boundary vertices turning by more than
    ``CAP_ANGLE``, split at the four longest boundary gaps between them, which must each be longer than every
    other gap by ``GROUP_GAP`` (1.2 times), each group turning by a quarter turn give or take ``CAP_ANGLE`` * 3:
    a patch whose corners only tie, a chamfered rectangle whose sides are longer than its chamfers; one whose
    short sides are no longer than its chamfers reads as an octagon, refused). A disc or a cap (its turn
    spread evenly round it, or no corner at all) cannot be helped."""
    loop, candidates = boundary_corners(verts, faces)
    if not loop or not candidates:
        return False
    turn = {v: math.pi - _surface_angle(verts, faces, v) for v in loop}
    if any(turn[v] < -CAP_ANGLE for v in loop):
        return True
    n = len(loop)
    at = {v: i for i, v in enumerate(loop)}
    arc = [0.0]
    for i in range(n):
        arc.append(arc[-1] + math.dist(verts[loop[i]], verts[loop[(i + 1) % n]]))
    m = len(candidates)
    gaps = []
    for k in range(m):
        i, j = at[candidates[k]], at[candidates[(k + 1) % m]]
        gaps.append(arc[j] - arc[i] if j > i else arc[n] - arc[i] + arc[j])
    if m < 4:
        return False
    order = sorted(range(m), key=lambda k: -gaps[k])
    if m > 4 and gaps[order[3]] <= GROUP_GAP * gaps[order[4]]:
        return False                       # no four gaps stand out: the turn is spread evenly (a disc)
    starts = sorted((k + 1) % m for k in order[:4])        # a group starts after one of the four longest gaps
    for g, k in enumerate(starts):
        end = starts[(g + 1) % 4]
        total, c = 0.0, k
        while True:
            total += turn[candidates[c]]
            c = (c + 1) % m
            if c == end:
                break
        if abs(total - math.pi / 2) > 3 * CAP_ANGLE:
            return False
    return True


def along_cuts(verts, part, strip: Strip, cuts) -> list[int] | None:
    """Four corners that make the cut part ``part`` (built as ``strip``) run along the strip it was cut from:
    the cuts (vertex-id sets, ``Split.entries`` / ``exits``) become its ends. None when ``strip`` already has
    a cut on an end, has no cut, or no such corners are found: each cut must lie along the part's one boundary
    loop, its two ends the corners, and with one cut the part's two corners off it the other two. Build it with
    these corners and ``end`` = the cuts (``strip_from_faces``), so the cuts are its ends even when it is wider
    than it is long."""
    cuts = [frozenset(c) for c in cuts if c]
    if not cuts or strip.closed or any(_end_holding(strip, c) is not None for c in cuts):
        return None
    try:
        loops = _boundary_loops(part, _edge_faces(part))
    except ValueError:
        return None
    if len(loops) != 1:
        return None
    loop = loops[0]
    n = len(loop)
    corners: list[int] = []
    for cut in cuts:
        ends = [loop[i] for i in range(n) if loop[i] in cut and (loop[i - 1] in cut) != (loop[(i + 1) % n] in cut)]
        if len(ends) != 2:
            return None
        corners += ends
    if len(cuts) == 1:
        others = [c for c in (strip.near[0], strip.near[-1], strip.far[0], strip.far[-1]) if c not in cuts[0]]
        if len(set(others)) != 2:
            return None
        corners += others
    corners = list(dict.fromkeys(corners))
    return corners if len(corners) == 4 else None
