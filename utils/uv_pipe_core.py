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

import math
from dataclasses import dataclass

from .uv_stripe_select_core import _edge

EPS = 1e-6


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
