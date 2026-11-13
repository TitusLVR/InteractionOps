"""UV Pipe analysis: the seam-loop walker, ring seams, part classification and the lengthwise seam of a wall.

Pure Python (stdlib only), no bpy and no mathutils, so it runs under plain pytest. Meshes are the UV Stripe
dicts: ``verts`` maps vertex ids to world-space (x, y, z), ``faces`` maps face ids to vertex ids in winding order.
Edges are keys of ``uv_stripe_select_core._edge`` (the sorted vertex-id pair).

The seam loop (``trace_loop``) is traced edge by edge: at each vertex it continues along the edge that is
straightest with respect to the edge it came by, so it goes through poles, triangles and n-gons alike. Loop
Angle is the smallest angle allowed between consecutive edges (pi = straight on).

Every result is deterministic: sets are sorted wherever their order reaches the output, and ties between equal
choices go to the lower vertex id or the lower position.
"""

import heapq
import math
from dataclasses import dataclass

from .uv_stripe_select_core import _boundary_loops, _edge, face_islands, strip_from_faces

EPS = 1e-6
FLAT_TOLERANCE = math.radians(1.0)


@dataclass
class Loop:
    verts: list[int]      # vertex path in order; for a closed loop the first id is not repeated
    closed: bool

    def edges(self) -> list[tuple[int, int]]:
        """Edge keys in path order, the closing edge included when closed."""
        ids = self.verts + self.verts[:1] if self.closed else self.verts
        return [_edge(a, b) for a, b in zip(ids, ids[1:])]


def neighbours(faces: dict) -> dict[int, list[int]]:
    """Vertex id -> the ids it shares an edge with, ascending."""
    out: dict[int, set[int]] = {}
    for face in faces.values():
        n = len(face)
        for i in range(n):
            a, b = face[i], face[(i + 1) % n]
            if a == b:
                continue
            out.setdefault(a, set()).add(b)
            out.setdefault(b, set()).add(a)
    return {v: sorted(ns) for v, ns in sorted(out.items())}


def _sub(a, b):
    return tuple(x - y for x, y in zip(a, b))


def _norm(a) -> float:
    return math.sqrt(sum(x * x for x in a))


def _normal(verts: dict, face) -> tuple[float, float, float]:
    """Unit normal by Newell's method; (0, 0, 0) for a degenerate face."""
    nx = ny = nz = 0.0
    n = len(face)
    for i in range(n):
        x0, y0, z0 = verts[face[i]]
        x1, y1, z1 = verts[face[(i + 1) % n]]
        nx += (y0 - y1) * (z0 + z1)
        ny += (z0 - z1) * (x0 + x1)
        nz += (x0 - x1) * (y0 + y1)
    length = math.sqrt(nx * nx + ny * ny + nz * nz)
    if length < 1e-300:
        return (0.0, 0.0, 0.0)
    return (nx / length, ny / length, nz / length)


def _between(u, w) -> float:
    """Angle between two vectors, radians; 0 when either is zero."""
    lu, lw = _norm(u), _norm(w)
    if lu < 1e-300 or lw < 1e-300:
        return 0.0
    c = sum(a * b for a, b in zip(u, w)) / (lu * lw)
    return math.acos(max(-1.0, min(1.0, c)))


def _edge_faces(faces: dict) -> dict[tuple, list[int]]:
    out: dict[tuple, list[int]] = {}
    for fid in sorted(faces):
        face = faces[fid]
        n = len(face)
        for i in range(n):
            a, b = face[i], face[(i + 1) % n]
            if a != b:
                out.setdefault(_edge(a, b), []).append(fid)
    return out


def dihedrals(verts: dict, faces: dict) -> dict[tuple, float]:
    """Edge -> angle between its two face normals, radians, 0 = flat. Boundary edges (one face) and non-manifold
    edges (more than two) are absent."""
    normals = {fid: _normal(verts, face) for fid, face in faces.items()}
    out = {}
    for e, fs in sorted(_edge_faces(faces).items()):
        if len(fs) == 2:
            out[e] = _between(normals[fs[0]], normals[fs[1]])
    return out


def _corner(points: dict, p: int, x: int, n: int) -> float:
    """The angle at x between its edges to p and to n, radians (pi = straight on)."""
    return _between(_sub(points[p], points[x]), _sub(points[n], points[x]))


def _step(verts, nbrs, uv, prev: int, cur: int, min_angle: float) -> int | None:
    """The neighbour of ``cur`` straightest on from the edge (prev, cur), or None when none is straight enough.

    The angle is measured in ``uv`` when cur, prev and the candidate all have a single uv there, else on verts.
    Equal angles (to 1e-9) go to the lower vertex id."""
    best, best_angle = None, -1.0
    for n in nbrs.get(cur, ()):
        if n == prev:
            continue
        space = uv if uv is not None and cur in uv and prev in uv and n in uv else verts
        a = _corner(space, prev, cur, n)
        if a > best_angle + 1e-9:
            best, best_angle = n, a
    if best is None or best_angle < min_angle - EPS:
        return None
    return best


def _closes(verts, uv, prev: int, start: int, nxt: int, min_angle: float) -> bool:
    space = uv if uv is not None and prev in uv and start in uv and nxt in uv else verts
    return _corner(space, prev, start, nxt) >= min_angle - EPS


def trace_loop(verts, nbrs, edge, min_angle, stop_verts=frozenset(), uv=None) -> Loop:
    """The seam loop through ``edge`` (a vertex-id pair), walked both ways from it.

    At each vertex the walk takes the neighbour whose edge makes the largest angle with the edge it arrived by and
    goes on only while that angle is at least ``min_angle`` (radians). A direction ends on a vertex of
    ``stop_verts`` (the loop ends on it), where no neighbour qualifies, or before a vertex already on the loop.
    The forward walk (from edge[0] through edge[1]) reaching edge[0] again closes the loop, provided the corner
    at edge[0] is straight enough too, so a closed loop is the same whichever of its edges it starts from.
    ``uv`` ({vid: (u, v)}, only vertices with one uv position) moves the angle of each step whose three vertices
    are all in it to the uv layout.
    """
    a, b = edge
    path = [a, b]
    on = {a, b}
    closed = False
    if b not in stop_verts:
        prev, cur = a, b
        while True:
            nxt = _step(verts, nbrs, uv, prev, cur, min_angle)
            if nxt is None:
                break
            if nxt == a:
                closed = _closes(verts, uv, cur, a, b, min_angle)
                break
            if nxt in on:
                break
            path.append(nxt)
            on.add(nxt)
            if nxt in stop_verts:
                break
            prev, cur = cur, nxt
    if closed:
        return Loop(path, True)
    back = []
    if a not in stop_verts:
        prev, cur = b, a
        while True:
            nxt = _step(verts, nbrs, uv, prev, cur, min_angle)
            if nxt is None or nxt in on:
                break
            back.append(nxt)
            on.add(nxt)
            if nxt in stop_verts:
                break
            prev, cur = cur, nxt
    return Loop(back[::-1] + path, False)


# --- Ring seams and parts -----------------------------------------------------------------------------------------


def ring_seams(verts, faces, sharp_angle, loop_angle) -> list[Loop]:
    """The automatic ring seams: closed loops (``trace_loop`` on geometry at ``loop_angle``) whose mean dihedral
    over their edges is at least ``sharp_angle``. Loops start only from edges whose own dihedral is at least
    ``sharp_angle``, in edge-key order; each loop is returned once. A boundary edge counts as flat in the mean."""
    angles = dihedrals(verts, faces)
    nbrs = neighbours(faces)
    taken: set = set()
    seen: set = set()
    out = []
    for e, a in angles.items():
        if a < sharp_angle - EPS or e in taken:
            continue
        loop = trace_loop(verts, nbrs, e, loop_angle)
        if not loop.closed:
            continue
        edges = loop.edges()
        key = frozenset(edges)
        if key in seen:
            continue
        seen.add(key)
        if sum(angles.get(x, 0.0) for x in edges) / len(edges) >= sharp_angle - EPS:
            out.append(loop)
            taken.update(edges)
    return out


@dataclass
class Part:
    kind: str                       # "WALL" | "RING" | "DISK" | "FREE"
    faces: dict[int, tuple]
    boundaries: list[list[int]]     # boundary vertex loops, longest first


def _face_edge_keys(face) -> list[tuple]:
    n = len(face)
    return [_edge(face[i], face[(i + 1) % n]) for i in range(n) if face[i] != face[(i + 1) % n]]


def _loop_length(verts, loop: list[int], closed: bool = True) -> float:
    ids = loop + loop[:1] if closed else loop
    return sum(math.dist(verts[a], verts[b]) for a, b in zip(ids, ids[1:]))


def _boundaries(verts, faces: dict) -> list[list[int]] | None:
    """The faces' boundary loops (edges used by one of them), longest first (3D length, then lowest first id);
    None when the boundary touches itself at a vertex."""
    try:
        loops = _boundary_loops(faces, _edge_faces(faces))
    except ValueError:
        return None
    return sorted(loops, key=lambda lp: (-round(_loop_length(verts, lp), 9), lp[0]))


def _is_flat(verts, faces: dict) -> bool:
    normals = [_normal(verts, face) for face in faces.values()]
    mean = tuple(sum(n[k] for n in normals) for k in range(3))
    if _norm(mean) < 1e-12:
        return False
    return all(_between(n, mean) <= FLAT_TOLERANCE + 1e-12 for n in normals)


def _sub_faces(faces: dict, ids) -> dict:
    return {fid: faces[fid] for fid in sorted(ids)}


def _shared_edges(faces: dict, band: set, rest: set) -> set:
    """Edges used by a face of ``band`` and a face of ``rest``."""
    a = {e for fid in band for e in _face_edge_keys(faces[fid])}
    return {e for fid in rest for e in _face_edge_keys(faces[fid]) if e in a}


def _flat_rest(verts, faces: dict) -> Part | None:
    """What is left of a flat part once peeling stops: nothing, a DISK (one boundary loop) or a WALL (more)."""
    if not faces:
        return None
    loops = _boundaries(verts, faces)
    if not loops:
        return Part("FREE", faces, loops or [])
    return Part("DISK" if len(loops) == 1 else "WALL", faces, loops)


def _closed_strip(verts, faces: dict) -> bool:
    try:
        return strip_from_faces(verts, faces).closed
    except ValueError:
        return False


def _peel(verts, comp: dict, cuts, suppressed, parts: list, peel: set) -> None:
    """Peel one-face-wide closed rings off a flat part from its longest boundary inward (see ``split_parts``)."""
    work = [comp]
    while work:
        rest = work.pop(0)
        while rest:
            loops = _boundaries(verts, rest)
            if not loops:
                break
            ring = set(Loop(loops[0], True).edges())
            band = {fid for fid, face in rest.items() if any(e in ring for e in _face_edge_keys(face))}
            if not _closed_strip(verts, _sub_faces(rest, band)):
                break
            left = set(rest) - band
            inner = _shared_edges(rest, band, left)
            layers = 1
            while inner & suppressed and left:
                grow = {fid for fid in left if any(e in inner for e in _face_edge_keys(rest[fid]))}
                band |= grow
                left -= grow
                inner = _shared_edges(rest, band, left)
                layers += 1
            band_faces = _sub_faces(rest, band)
            if layers == 1:
                parts.append(Part("RING", band_faces, _boundaries(verts, band_faces) or []))
            else:
                band_loops = _boundaries(verts, band_faces)
                if not band_loops or len(band_loops) != 2:
                    break
                parts.append(Part("WALL", band_faces, band_loops))
            peel |= inner
            pieces = face_islands(_sub_faces(rest, left), cuts) if left else []
            work[:0] = pieces[1:]
            rest = pieces[0] if pieces else {}
        part = _flat_rest(verts, rest)
        if part is not None:
            parts.append(part)


def split_parts(verts, faces, cuts, suppressed=frozenset()) -> tuple[list[Part], set]:
    """Split ``faces`` at the ``cuts`` (edge keys) into classified parts; return them and the peel seams added.

    Each edge-connected component (``face_islands``) is flat when every face normal lies within ``FLAT_TOLERANCE``
    of their mean. A flat component is peeled: the faces with an edge on its longest boundary loop, when they make
    a closed strip, are a RING and the edges between them and the rest a peel seam; peeling goes on with the rest.
    When an edge between the layer and the rest is in ``suppressed`` (a seam the user removed), the band grows
    inward a face layer at a time until no such edge is suppressed or nothing is left; a band of two or more layers
    with two boundary loops is a WALL, its inner edges a peel seam, and peeling goes on. Otherwise (the layer is no
    closed strip, or the grown band has not two boundary loops) peeling stops, and what is left is nothing, a DISK
    (one boundary loop) or a WALL (two or more). A part that is not flat is a WALL with two or more boundary loops,
    else FREE. Cut edges and mesh boundary edges both count as boundary; a boundary that touches itself at a
    vertex leaves the part FREE with no boundaries.
    """
    parts: list[Part] = []
    peel: set = set()
    for comp in face_islands(faces, cuts):
        if _is_flat(verts, comp):
            _peel(verts, comp, cuts, suppressed, parts, peel)
            continue
        loops = _boundaries(verts, comp) or []
        parts.append(Part("WALL" if len(loops) >= 2 else "FREE", comp, loops))
    return parts, peel


# --- Lengthwise seam of a wall ---------------------------------------------------------------------------------------


def loop_kind(loop: Loop, part: Part) -> str:
    """"RING" for a closed loop, "LENGTH" when its two ends lie on two different boundary loops of ``part``,
    else "INVALID"."""
    if loop.closed:
        return "RING"
    if len(loop.verts) < 2:
        return "INVALID"
    first, last = loop.verts[0], loop.verts[-1]
    at_first = [i for i, b in enumerate(part.boundaries) if first in b]
    at_last = [i for i, b in enumerate(part.boundaries) if last in b]
    return "LENGTH" if any(i != j for i in at_first for j in at_last) else "INVALID"


def _shortest(verts, loops: list[Loop]) -> Loop | None:
    """The loop of least 3D length; lengths within 1e-9 (relative) tie, and a tie goes to the loop whose vertex
    positions come first, in path order (so to the lowest start position)."""
    if not loops:
        return None
    lengths = [_loop_length(verts, lp.verts, lp.closed) for lp in loops]
    low = min(lengths)
    tied = [lp for lp, length in zip(loops, lengths) if length <= low + 1e-9 * max(1.0, low)]
    return min(tied, key=lambda lp: [tuple(verts[v]) for v in lp.verts])


def wall_candidates(verts, part: Part, loop_angle, uv=None) -> list[Loop]:
    """The lengthwise loops between the part's two longest boundary loops: one per vertex of the longest, in its
    order, duplicates removed. From each vertex every edge into the part is traced (``trace_loop``, ending on any
    boundary vertex of the part); of those reaching the second loop the shortest is kept (``_shortest``)."""
    if len(part.boundaries) < 2:
        return []
    first, second = part.boundaries[0], set(part.boundaries[1])
    on_first = set(first)
    nbrs = neighbours(part.faces)
    stops = frozenset(v for b in part.boundaries for v in b)
    out, seen = [], set()
    for v in first:
        found = []
        for w in nbrs.get(v, ()):
            if w in on_first:
                continue
            loop = trace_loop(verts, nbrs, (v, w), loop_angle, stops, uv)
            if not loop.closed and loop.verts[0] == v and loop.verts[-1] in second:
                found.append(loop)
        best = _shortest(verts, found)
        if best is not None:
            key = frozenset(best.edges())
            if key not in seen:
                seen.add(key)
                out.append(best)
    return out


def _shortest_path(verts, part: Part) -> Loop | None:
    """The shortest edge path (3D length) from the part's longest boundary loop to its second, or None."""
    first, second = part.boundaries[0], set(part.boundaries[1])
    nbrs = neighbours(part.faces)
    dist = dict.fromkeys(first, 0.0)
    came: dict[int, int] = {}
    heap = [(0.0, v) for v in sorted(first)]
    heapq.heapify(heap)
    done: set = set()
    while heap:
        d, v = heapq.heappop(heap)
        if v in done:
            continue
        done.add(v)
        if v in second:
            path = [v]
            while path[-1] in came:
                path.append(came[path[-1]])
            return Loop(path[::-1], False)
        for w in nbrs.get(v, ()):
            nd = d + math.dist(verts[v], verts[w])
            if nd < dist.get(w, math.inf):
                dist[w] = nd
                came[w] = v
                heapq.heappush(heap, (nd, w))
    return None


def wall_seam(verts, part: Part, loop_angle, uv=None) -> tuple[Loop | None, bool]:
    """The automatic lengthwise seam of a wall and whether it is a fallback.

    The shortest of ``wall_candidates`` by 3D length, ties to the lowest start position. With no candidate, the
    shortest edge path between the two longest boundary loops, with fallback True; (None, True) when there is none.
    """
    best = _shortest(verts, wall_candidates(verts, part, loop_angle, uv))
    if best is not None:
        return best, False
    if len(part.boundaries) < 2:
        return None, True
    return _shortest_path(verts, part), True


def existing_wall_seam(part: Part, seam_edges) -> Loop | None:
    """The seam already on the mesh as the wall's lengthwise seam: the ``seam_edges`` inside the part (used by two
    of its faces) when they form one open path whose ends lie on two different boundary loops; else None. The path
    starts at the end on the longer boundary loop."""
    edge_faces = _edge_faces(part.faces)
    inside = sorted(e for e in set(seam_edges) if len(edge_faces.get(e, ())) == 2)
    if not inside:
        return None
    adj: dict[int, list[int]] = {}
    for a, b in inside:
        adj.setdefault(a, []).append(b)
        adj.setdefault(b, []).append(a)
    if any(len(n) > 2 for n in adj.values()):
        return None
    ends = sorted(v for v, n in adj.items() if len(n) == 1)
    if len(ends) != 2:
        return None

    def first_loop(v):
        return min((i for i, b in enumerate(part.boundaries) if v in b), default=len(part.boundaries))

    start = min(ends, key=lambda v: (first_loop(v), v))
    path, prev = [start], None
    while True:
        nxt = [w for w in adj[path[-1]] if w != prev]
        if not nxt:
            break
        prev = path[-1]
        path.append(nxt[0])
    if len(path) != len(inside) + 1:
        return None
    loop = Loop(path, False)
    return loop if loop_kind(loop, part) == "LENGTH" else None


def _centroid(verts, ids) -> tuple[float, float, float]:
    n = len(ids)
    return tuple(sum(verts[v][k] for v in ids) / n for k in range(3))


def bend_seams(verts, part: Part, seam: Loop, bend_angle, loop_angle) -> list[Loop]:
    """Ring seams where the wall bends (Split at Bends).

    At each interior vertex of ``seam``, in order, the closed loop (``trace_loop`` at ``loop_angle``) through an
    edge off the seam is that vertex's ring; a vertex with no closed loop through it has none (a messy bend gets no
    cut there). The tube's direction is the difference of consecutive centroids of the seam's start boundary loop,
    the rings and its end boundary loop; the turn between directions is summed ring by ring, and the ring where the
    sum reaches ``bend_angle`` is returned, after which the sum restarts."""
    nbrs = neighbours(part.faces)
    rings: list[Loop] = []
    seen: set = set()
    for k in range(1, len(seam.verts) - 1):
        v = seam.verts[k]
        along = (seam.verts[k - 1], seam.verts[k + 1])
        for w in nbrs.get(v, ()):
            if w in along:
                continue
            loop = trace_loop(verts, nbrs, (v, w), loop_angle)
            if loop.closed:
                key = frozenset(loop.edges())
                if key not in seen:
                    seen.add(key)
                    rings.append(loop)
                break
    if not rings:
        return []
    def end_point(v):
        loop = next((b for b in part.boundaries if v in b), None)
        return [] if loop is None else [(_centroid(verts, loop), None)]

    points = end_point(seam.verts[0]) + [(_centroid(verts, r.verts), r) for r in rings] + end_point(seam.verts[-1])
    out, total = [], 0.0
    for i in range(1, len(points) - 1):
        ring = points[i][1]
        if ring is None:
            continue
        before = _sub(points[i][0], points[i - 1][0])
        after = _sub(points[i + 1][0], points[i][0])
        total += _between(before, after)
        if total >= bend_angle - EPS:
            out.append(ring)
            total = 0.0
    return out
