"""Smart Edge Slide core: pure-Python band model and wedge development.

Stdlib only (no bpy), so it runs under plain pytest.

Angle convention (used by every consumer): in the wedge of ``chain[k]`` angle 0
is the direction to ``chain[k+1]``. Angles grow through the side faces up to
``theta``, the direction to ``chain[k-1]``. At the first vertex of an open chain
``theta`` is the end edge (``Band.end_edges``, else the band border); at the
last vertex angle 0 is the end edge.

Rails continue through rows: ``rail_path`` follows a rail on, edge by edge, as
far as the next edge stays near straight on. The new vertex sits where that
path gives the balanced width. An open chain's end edges continue the same way
as end walls, which the new loop's ends slide along and no trace crosses.

Traces run straight in a development: band faces unfolded into the plane
across shared edges. Each face is laid out intrinsically (its triangles keep
their 3D edge lengths), so a development never stretches a face, and 3D points
come from barycentric coordinates on the face's own triangles.
"""

import bisect
import heapq
import math
from dataclasses import dataclass, field
from functools import partial

Vec2 = tuple[float, float]
Vec3 = tuple[float, float, float]

EPS = 1e-9
RAIL_MAX_DEV = math.radians(30.0)
EXACT_TOL = 1e-3  # relative to width
STEP_AGREE_COS = 0.8660254
STEP_DIFFER_COS = 0.5
LIMIT_ITERS = 60
SNAP_ITERS = 50


def _sub(a: Vec3, b: Vec3) -> Vec3:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _dot(a: Vec3, b: Vec3) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _length(a: Vec3) -> float:
    return math.sqrt(_dot(a, a))


def _has_edge(loop: tuple[int, ...], a: int, b: int) -> bool:
    n = len(loop)
    for i in range(n):
        p, q = loop[i], loop[(i + 1) % n]
        if (p == a and q == b) or (p == b and q == a):
            return True
    return False


@dataclass(frozen=True)
class Angles:
    """The angle tolerances of the slide, in radians; the defaults are the long-standing constants.

    ``rail_bend`` is how far a rail path may turn at a vertex and how far a
    rail may lean from the wedge's bisector. ``end_edge`` is the angle from an
    open chain's end edge at which an end fan stops. ``step_agree`` and
    ``step_differ`` bound the step-run tests of the bridge; ``shoot`` is for the
    destructive mode's shooting rays.
    """

    rail_bend: float = RAIL_MAX_DEV
    end_edge: float = math.pi / 2.0 - RAIL_MAX_DEV
    step_agree: float = math.acos(STEP_AGREE_COS)
    step_differ: float = math.acos(STEP_DIFFER_COS)
    shoot: float = math.radians(30.0)


@dataclass
class Band:
    """The faces on one side of a chain.

    ``tris`` gives a face's triangles as vertex-id triples, in any winding. A
    face listed there is laid out and mapped back to 3D on those triangles, so a
    non-planar face keeps the surface its mesh shows; any other face falls back
    to a triangulation of its own (a fan from its first vertex when convex).

    ``end_edges`` names, for an open chain, the far vertex of the end edge at
    ``chain[0]`` and at ``chain[-1]``. An end edge bounds that end's wedge and
    continues as the end wall (see ``rail_path``). None, and every closed
    chain, keeps the band border as the end of the wedge.

    An edge that more than two band faces hold (a fin standing on the surface)
    is band border: nothing unfolds or traces across it.
    """

    verts: dict[int, Vec3]
    faces: dict[int, tuple[int, ...]]
    chain: list[int]
    closed: bool
    side_faces: list[int]
    tris: dict[int, list[tuple[int, int, int]]] = field(default_factory=dict)
    end_edges: tuple[int | None, int | None] = (None, None)
    angles: Angles = field(default_factory=Angles)

    def __post_init__(self):
        n = len(self.chain)
        expected = n if self.closed else n - 1
        if len(self.side_faces) != expected:
            raise ValueError(
                f"side_faces has {len(self.side_faces)} entries, expected {expected}"
            )
        for i, f in enumerate(self.side_faces):
            a, b = self.chain[i], self.chain[(i + 1) % n]
            loop = self.faces.get(f)
            if loop is None or not _has_edge(loop, a, b):
                raise ValueError(f"side face {f} does not contain chain edge ({a}, {b})")
        if not self.closed:
            for v, far in zip((self.chain[0], self.chain[-1]), self.end_edges):
                if far is not None and not any(_has_edge(loop, v, far) for loop in self.faces.values()):
                    raise ValueError(f"end edge ({v}, {far}) is not an edge of the band")


@dataclass(frozen=True)
class Rail:
    far: int
    angle: float
    length: float
    border: bool


@dataclass
class Wedge:
    k: int
    theta: float
    faces: list[int]
    rails: list[Rail]


def _sweep(band: Band, v: int, start_face: int, start_far: int, stop_far, layout, edge_faces):
    """Walk face to face around ``v`` starting along edge (v, start_far); ``layout(f)`` lays faces out.

    Stops once a face's exit neighbour equals ``stop_far`` (when not None) or the
    band border is reached: an edge without a second band face, or one that more
    than two band faces hold (``edge_faces``, see ``_edge_faces``). Returns
    (faces, rails, theta, border_far) where
    ``rails`` are (far, cumulative_angle) of the interior edges and ``border_far``
    is the exit neighbour of the last face when the sweep ended at the border
    (else None).

    Corner angles come from the face layouts the traces develop with, so a rail
    angle is exactly where a trace finds that rail, also on non-planar faces and
    at reflex corners.
    """
    faces: list[int] = []
    rails: list[tuple[int, float]] = []
    angle = 0.0
    face, far0 = start_face, start_far
    seen = set()
    while True:
        if face in seen:
            raise ValueError("wedge sweep looped")
        seen.add(face)
        loop = band.faces[face]
        i = loop.index(v)
        n = len(loop)
        nb = (loop[i - 1], loop[(i + 1) % n])
        if far0 not in nb:
            raise ValueError(f"face {face} does not touch edge ({v}, {far0})")
        far1 = nb[0] if nb[1] == far0 else nb[1]
        faces.append(face)
        angle += _layout_corner(layout(face), v)
        if stop_far is not None and far1 == stop_far:
            return faces, rails, angle, None
        holders = edge_faces.get(_ekey(v, far1), ())
        nxt = next((f for f in holders if f != face), None) if len(holders) == 2 else None
        if nxt is None:
            if stop_far is not None:
                raise ValueError(f"wedge sweep hit the band border at vertex {v}")
            return faces, rails, angle, far1
        rails.append((far1, angle))
        face, far0 = nxt, far1


def wedge(band: Band, k: int, *, _surface: "_Surface | None" = None) -> Wedge:
    """The faces around ``chain[k]`` on the band side and the rails between them.

    At an open chain's end the sweep stops at the end edge when ``band.end_edges``
    names one, else at the band border; that edge is the wedge's border rail.
    """
    chain, n = band.chain, len(band.chain)
    v = chain[k]
    pv = band.verts
    has_out = band.closed or k < n - 1
    has_in = band.closed or k > 0
    layout = partial(_face_layout, band) if _surface is None else _surface.layout
    edge_faces = _edge_faces(band) if _surface is None else _surface.edge_faces

    def length(far: int) -> float:
        return _length(_sub(pv[far], pv[v]))

    if has_out:
        stop = chain[(k - 1) % n] if has_in else band.end_edges[0]
        faces, rails, theta, border = _sweep(band, v, band.side_faces[k], chain[(k + 1) % n], stop, layout, edge_faces)
        if not has_in and border is None:  # stopped at the end edge
            border = stop
        out = [Rail(f, a, length(f), False) for f, a in rails]
        if border is not None:
            out.append(Rail(border, theta, length(border), True))
        return Wedge(k, theta, faces, out)

    # Last vertex of an open chain: sweep from chain[k-1] to the end edge or the
    # border, then flip so that angle 0 is that edge.
    end = band.end_edges[1]
    faces, rails, theta, border = _sweep(band, v, band.side_faces[k - 1], chain[k - 1], end, layout, edge_faces)
    if border is None:
        border = end
    out = [Rail(border, 0.0, length(border), True)]
    out += [Rail(f, theta - a, length(f), False) for f, a in reversed(rails)]
    return Wedge(k, theta, faces[::-1], out)


# --- Surface traces -------------------------------------------------------------

# A rigid map from a face layout into a development, (ox, oy, ax, ay, bx, by):
# layout (x, y) lands at o + x*a + y*b. ``b`` is perp(a) for a proper rotation
# and -perp(a) for a mirrored one (the core never relies on face winding).
_Xform = tuple[float, float, float, float, float, float]

_SEGMENT_MEET_TOL = 1e-6
_ANCHOR_SNAP_TOL = 2.0 * _SEGMENT_MEET_TOL
_SNAP_SCAN = 32  # samples over (0, limit] before ``snap_width`` bisects


@dataclass(frozen=True)
class SurfacePoint:
    kind: str  # "vert", "edge" or "face"
    face: int
    co: Vec3
    vert: int | None = None
    edge: tuple[int, int] | None = None  # sorted vertex ids
    t: float = 0.0  # co == lerp(verts[edge[0]], verts[edge[1]], t)


@dataclass
class Trace:
    """A straight path in a development.

    Every crossing's ``face`` is the face the path continues in; ``end.face`` is
    the face it ends in. ``_face`` and ``_xf`` place the end face in the
    development, so a later trace can continue from ``end``.
    """

    crossings: list[SurfacePoint]
    end: SurfacePoint
    blocked: bool
    end_xy: Vec2
    _face: int = field(repr=False)
    _xf: _Xform = field(repr=False)


@dataclass
class _Layout:
    loop: tuple[int, ...]
    pts: dict[int, Vec2]  # counter-clockwise in loop order
    tris: list[tuple[int, int, int]]  # vertex ids, counter-clockwise


def _sub2(a: Vec2, b: Vec2) -> Vec2:
    return (a[0] - b[0], a[1] - b[1])


def _dot2(a: Vec2, b: Vec2) -> float:
    return a[0] * b[0] + a[1] * b[1]


def _cross2(a: Vec2, b: Vec2) -> float:
    return a[0] * b[1] - a[1] * b[0]


def _len2(a: Vec2) -> float:
    return math.hypot(a[0], a[1])


def _unit2(a: Vec2) -> Vec2:
    n = _len2(a)
    return (a[0] / n, a[1] / n)


def _ccw_angle(u: Vec2, w: Vec2) -> float:
    """Counter-clockwise angle from ``u`` to ``w`` in [0, 2*pi)."""
    a = math.atan2(_cross2(u, w), _dot2(u, w))
    return a + 2.0 * math.pi if a < 0.0 else a


def _ekey(a: int, b: int) -> tuple[int, int]:
    return (a, b) if a < b else (b, a)


def _edge_faces(band: Band) -> dict[tuple[int, int], list[int]]:
    """Band faces on each edge, keyed by sorted vertex ids."""
    out: dict[tuple[int, int], list[int]] = {}
    for f, loop in band.faces.items():
        for i in range(len(loop)):
            out.setdefault(_ekey(loop[i - 1], loop[i]), []).append(f)
    return out


def _project(pts: list[Vec3]) -> list[Vec2]:
    """Project a polygon onto its Newell plane, counter-clockwise in loop order."""
    nx = ny = nz = 0.0
    for i in range(len(pts)):
        (x0, y0, z0), (x1, y1, z1) = pts[i - 1], pts[i]
        nx += (y0 - y1) * (z0 + z1)
        ny += (z0 - z1) * (x0 + x1)
        nz += (x0 - x1) * (y0 + y1)
    nl = math.sqrt(nx * nx + ny * ny + nz * nz)
    n = (nx / nl, ny / nl, nz / nl) if nl > 0.0 else (0.0, 0.0, 1.0)
    axis = (1.0, 0.0, 0.0) if abs(n[0]) < 0.9 else (0.0, 1.0, 0.0)
    u = (n[1] * axis[2] - n[2] * axis[1], n[2] * axis[0] - n[0] * axis[2], n[0] * axis[1] - n[1] * axis[0])
    ul = _length(u)
    u = (u[0] / ul, u[1] / ul, u[2] / ul)
    w = (n[1] * u[2] - n[2] * u[1], n[2] * u[0] - n[0] * u[2], n[0] * u[1] - n[1] * u[0])
    return [(_dot(_sub(p, pts[0]), u), _dot(_sub(p, pts[0]), w)) for p in pts]


def _in_triangle(q: Vec2, a: Vec2, b: Vec2, c: Vec2) -> bool:
    return (
        _cross2(_sub2(b, a), _sub2(q, a)) >= 0.0
        and _cross2(_sub2(c, b), _sub2(q, b)) >= 0.0
        and _cross2(_sub2(a, c), _sub2(q, c)) >= 0.0
    )


def _ear_clip(p: list[Vec2]) -> list[tuple[int, int, int]]:
    """Triangulate a counter-clockwise polygon (indices into ``p``).

    A convex polygon becomes a fan from index 0, the split Blender uses for a
    convex quad.
    """
    idx = list(range(len(p)))
    tris = []
    while len(idx) > 3:
        m = len(idx)
        for j in range(1, m + 1):
            a, b, c = idx[j - 1], idx[j % m], idx[(j + 1) % m]
            if _cross2(_sub2(p[b], p[a]), _sub2(p[c], p[b])) <= 0.0:
                continue
            if any(_in_triangle(p[i], p[a], p[b], p[c]) for i in idx if i not in (a, b, c)):
                continue
            break
        else:  # degenerate polygon: clip anyway
            j = 1
            a, b, c = idx[0], idx[1], idx[2]
        tris.append((a, b, c))
        del idx[j % m]
    tris.append((idx[0], idx[1], idx[2]))
    return tris


def _apex(pa: Vec2, pb: Vec2, la: float, lb: float) -> Vec2:
    """The point at distance ``la`` from ``pa`` and ``lb`` from ``pb``, left of pa -> pb."""
    e = _sub2(pb, pa)
    d = _len2(e)
    if d == 0.0:
        return pa
    ex, ey = e[0] / d, e[1] / d
    x = (la * la - lb * lb + d * d) / (2.0 * d)
    h = math.sqrt(max(0.0, la * la - x * x))
    return (pa[0] + x * ex - h * ey, pa[1] + x * ey + h * ex)


def _oriented(tri: tuple[int, int, int], a: int, b: int) -> tuple[int, int, int] | None:
    """``tri`` turned (and reversed if need be) to run a -> b first: (a, b, third), or None without that edge."""
    for t in (tri, tri[::-1]):
        for r in range(3):
            if t[r] == a and t[(r + 1) % 3] == b:
                return (a, b, t[(r + 2) % 3])
    return None


def _given_layout(loop: tuple[int, ...], pv: dict[int, Vec3], given: list[tuple[int, int, int]]) -> _Layout | None:
    """Lay a face out on ``given`` triangles, keeping 3D edge lengths; None when they do not tile the face.

    The triangles are laid out across shared edges from one that holds a face
    edge. That one runs its face edge in loop order and each neighbour runs a
    shared edge the other way, so the layout is counter-clockwise in loop order
    whatever winding the triangles came in.
    """
    n = len(loop)
    if len(given) != n - 2 or any(len(set(t)) != 3 or not set(t) <= set(loop) for t in given):
        return None
    succ = {loop[i]: loop[(i + 1) % n] for i in range(n)}
    by_edge: dict[tuple[int, int], list[int]] = {}
    for i, t in enumerate(given):
        for j in range(3):
            by_edge.setdefault(_ekey(t[j], t[(j + 1) % 3]), []).append(i)
    seed = None
    for i, t in enumerate(given):
        for j in range(3):
            u, w = t[j], t[(j + 1) % 3]
            if succ[u] == w or succ[w] == u:  # a face edge: the seed runs it in loop order
                seed = (i, u, w) if succ[u] == w else (i, w, u)
                break
        if seed is not None:
            break
    if seed is None:
        return None

    def d3(a: int, b: int) -> float:
        return _length(_sub(pv[a], pv[b]))

    i0, a, b = seed
    t0 = _oriented(given[i0], a, b)
    pts = {a: (0.0, 0.0), b: (d3(a, b), 0.0)}
    pts[t0[2]] = _apex(pts[a], pts[b], d3(a, t0[2]), d3(b, t0[2]))
    placed = {i0: t0}
    todo = [i0]
    for i in todo:
        p, q, r = placed[i]
        for u, w in ((p, q), (q, r), (r, p)):
            for j in by_edge[_ekey(u, w)]:
                if j in placed:
                    continue
                t = _oriented(given[j], w, u)  # the neighbour runs the shared edge the other way
                x = t[2]
                if x not in pts:
                    pts[x] = _apex(pts[w], pts[u], d3(w, x), d3(u, x))
                placed[j] = t
                todo.append(j)
    if len(placed) != len(given) or len(pts) != n:
        return None
    return _Layout(loop, pts, [placed[i] for i in range(len(given))])


def _face_layout(band: Band, f: int) -> _Layout:
    """Lay face ``f`` out in 2D, triangle by triangle, keeping 3D edge lengths.

    The triangles are the face's ``band.tris`` when it has them. Otherwise they
    come from the face's Newell projection, and ears are laid out in reverse clip
    order, so each ear tip lands on an already placed diagonal.
    """
    loop = band.faces[f]
    pv = band.verts
    given = band.tris.get(f)
    if given:
        lay = _given_layout(loop, pv, given)
        if lay is not None:
            return lay
    tris = [(loop[a], loop[b], loop[c]) for a, b, c in _ear_clip(_project([pv[v] for v in loop]))]

    def d3(a: int, b: int) -> float:
        return _length(_sub(pv[a], pv[b]))

    a, b, c = tris[-1]
    pts = {a: (0.0, 0.0), b: (d3(a, b), 0.0)}
    pts[c] = _apex(pts[a], pts[b], d3(a, c), d3(b, c))
    for a, b, c in reversed(tris[:-1]):
        pts[b] = _apex(pts[c], pts[a], d3(c, b), d3(a, b))
    return _Layout(loop, pts, tris)


def _layout_corner(lay: _Layout, v: int) -> float:
    """Interior angle of the layout at vertex ``v`` (above pi at a reflex corner)."""
    loop = lay.loop
    i = loop.index(v)
    q = lay.pts[v]
    return _ccw_angle(_sub2(lay.pts[loop[(i + 1) % len(loop)]], q), _sub2(lay.pts[loop[i - 1]], q))


def _xf_apply(xf: _Xform, p: Vec2) -> Vec2:
    ox, oy, ax, ay, bx, by = xf
    return (ox + p[0] * ax + p[1] * bx, oy + p[0] * ay + p[1] * by)


def _xf_invert(xf: _Xform, q: Vec2) -> Vec2:
    ox, oy, ax, ay, bx, by = xf
    dx, dy = q[0] - ox, q[1] - oy
    return (dx * ax + dy * ay, dx * bx + dy * by)


def _xf_mirrored(xf: _Xform) -> bool:
    return xf[2] * xf[5] - xf[3] * xf[4] < 0.0


def _xf_moved(xf: _Xform, move) -> _Xform:
    """``xf`` followed by ``move``, a rigid map of the development (no mirror) given as a point function."""
    ox, oy, ax, ay, bx, by = xf
    o, a, b = move((ox, oy)), move((ox + ax, oy + ay)), move((ox + bx, oy + by))
    return (o[0], o[1], a[0] - o[0], a[1] - o[1], b[0] - o[0], b[1] - o[1])


def _xf_fit(la: Vec2, lb: Vec2, pa: Vec2, pb: Vec2, mirror: bool) -> _Xform:
    """The rigid map (mirrored when asked) taking ``la`` to ``pa`` and ``lb`` toward ``pb``."""
    s = -1.0 if mirror else 1.0
    e = (lb[0] - la[0], s * (lb[1] - la[1]))
    g = _sub2(pb, pa)
    m = _len2(e) * _len2(g)
    c, sn = (_dot2(e, g) / m, _cross2(e, g) / m) if m > 0.0 else (1.0, 0.0)
    ax, ay, bx, by = c, sn, -sn * s, c * s
    return (pa[0] - la[0] * ax - la[1] * bx, pa[1] - la[0] * ay - la[1] * by, ax, ay, bx, by)


def _foot(pa: Vec2, pb: Vec2, x: Vec2) -> tuple[float, Vec2]:
    """Parameter ``t`` along pa -> pb (clamped to the segment) and the point there nearest ``x``."""
    e = _sub2(pb, pa)
    ee = _dot2(e, e)
    t = min(1.0, max(0.0, _dot2(_sub2(x, pa), e) / ee)) if ee > 0.0 else 0.0
    return t, (pa[0] + e[0] * t, pa[1] + e[1] * t)


def _barycentric(p: Vec3, a: Vec3, b: Vec3, c: Vec3) -> Vec3 | None:
    """Weights of ``p`` projected onto the plane of triangle abc; None for a degenerate triangle."""
    v0, v1, v2 = _sub(b, a), _sub(c, a), _sub(p, a)
    d00, d01, d11 = _dot(v0, v0), _dot(v0, v1), _dot(v1, v1)
    den = d00 * d11 - d01 * d01
    if den <= 0.0:
        return None
    d20, d21 = _dot(v2, v0), _dot(v2, v1)
    wb = (d11 * d20 - d01 * d21) / den
    wc = (d00 * d21 - d01 * d20) / den
    return (1.0 - wb - wc, wb, wc)


def _band_scale(band: Band) -> float:
    pts = list(band.verts.values())
    lo = tuple(min(p[i] for p in pts) for i in range(3))
    hi = tuple(max(p[i] for p in pts) for i in range(3))
    return _length(_sub(hi, lo)) or 1.0


@dataclass
class _Spread:
    """``_Surface.nearest_frame``'s shortest-path walk out from the frame faces, as far as it has gone.

    ``near`` holds each settled face's (k, (face it was reached from, edge a, b)),
    None for a frame face itself, in the order the walk settled them; ``rank`` each
    settled face's place in that order; ``best`` the best (distance, k, way) found
    so far for the faces on the frontier ``heap``; ``placed`` each face laid out in
    its frame, which starts with the frame faces.
    """

    near: dict[int, tuple[int, tuple[int, int, int] | None]] = field(default_factory=dict)
    rank: dict[int, int] = field(default_factory=dict)
    best: dict[int, tuple[float, int, tuple[int, int, int] | None]] = field(default_factory=dict)
    heap: list[tuple[float, int, int]] = field(default_factory=list)
    placed: dict[int, _Xform] = field(default_factory=dict)
    count: int = 0  # pushes so far: equal distances settle in the order they were found


# A developed rail path: its vertex ids, their positions in the wedge frame of
# its chain vertex, and for each path edge a face holding it, placed there.
_Path = tuple[list[int], list[Vec2], list[tuple[int, _Xform]]]


class _Surface:
    """Adjacency, face layouts, wedges, end walls and tolerances for the traces over one band.

    Built once per trace call, or once per ``Slider`` and handed to the traces
    through their private ``_surface`` argument. ``blocked`` holds the edges no
    trace or unfolding crosses: the chain edges and the end-wall edges.
    """

    def __init__(self, band: Band):
        self.band = band
        self.tol = EPS * _band_scale(band)
        self.edge_faces = _edge_faces(band)
        n = len(band.chain)
        self.chain_edges = {
            _ekey(band.chain[i], band.chain[(i + 1) % n]) for i in range(n if band.closed else n - 1)
        }
        self.max_steps = 16 + 8 * len(band.faces)
        self._layouts: dict[int, _Layout] = {}
        self._wedges: dict[int, Wedge] = {}
        self._frames: dict[int, tuple[int, int, _Xform]] = {}
        self._hops: dict[int, tuple[float, float, float]] = {}
        self._spread: _Spread | None = None
        self._centres: dict[int, Vec3] = {}
        self._vert_faces: dict[int, list[int]] | None = None
        self._paths: dict[tuple[int, int], _Path] = {}
        self._end_paths: dict[bool, _Path | None] = {}
        # The end walls develop past chain edges only: they are what the other paths stop at.
        walls: set[tuple[int, int]] = set()
        for at_start in (True, False):
            end = self.end_index(at_start)
            if end is not None:
                verts = self._paths.setdefault(end, self._develop(*end, self.chain_edges))[0]
                walls.update(_ekey(a, b) for a, b in zip(verts, verts[1:]))
        self.blocked = self.chain_edges | walls

    def end_path(self, at_start: bool) -> _Path | None:
        """The path an open chain's end slides along, in its end vertex's wedge frame; None without an end edge.

        It is the end wall, up to where the wall meets the other end's wall at a
        vertex both hold. There the end turns onto the other wall and runs along
        it, away from that vertex, to the other chain end. The two walls close the
        side off there, so past that vertex the end's own wall runs out of it.
        Walls that run on together keep the end's own. The other wall's points and
        faces come over through the chain's wedge frames (``to_frame``), as the
        segments map their partner points. A meeting vertex that the two walls
        develop to different places (the surface between them does not lie flat)
        turns nothing. Worked out once.
        """
        if at_start not in self._end_paths:
            end, other = self.end_index(at_start), self.end_index(not at_start)
            path = None if end is None else self.rail_path(*end)
            if path is not None and other is not None:
                verts, pts, holders = path
                o_verts, o_pts, o_holders = self.rail_path(*other)
                where = {v: j for j, v in enumerate(o_verts)}
                move = partial(self.to_frame, src=other[0], dst=end[0])
                for i in range(1, len(verts)):
                    j = where.get(verts[i], 0)  # 0: not on the other wall, or the other chain end
                    if j == 0 or (i + 1 < len(verts) and verts[i + 1] == o_verts[j - 1]):
                        continue
                    if _len2(_sub2(move(o_pts[j]), pts[i])) <= _SEGMENT_MEET_TOL:
                        path = (
                            verts[: i + 1] + o_verts[j - 1 :: -1],
                            pts[: i + 1] + [move(p) for p in o_pts[j - 1 :: -1]],
                            holders[:i] + [(g, _xf_moved(xg, move)) for g, xg in o_holders[j - 1 :: -1]],
                        )
                    break
            self._end_paths[at_start] = path
        return self._end_paths[at_start]

    def to_frame(self, p: Vec2, src: int, dst: int) -> Vec2:
        """Point ``p`` of ``chain[src]``'s wedge frame in ``chain[dst]``'s, hopping along the chain edges between."""
        while src > dst:
            src -= 1
            p = self.from_next(src, p)
        while src < dst:
            p = self.to_next(src, p)
            src += 1
        return p

    def end_index(self, at_start: bool) -> tuple[int, int] | None:
        """(chain index, far vertex) of an open chain's end edge at its start or end; None without one."""
        band = self.band
        far = band.end_edges[0 if at_start else 1]
        if band.closed or far is None:
            return None
        return (0 if at_start else len(band.chain) - 1), far

    def layout(self, f: int) -> _Layout:
        lay = self._layouts.get(f)
        if lay is None:
            lay = self._layouts[f] = _face_layout(self.band, f)
        return lay

    def wedge(self, k: int) -> Wedge:
        w = self._wedges.get(k)
        if w is None:
            w = self._wedges[k] = wedge(self.band, k, _surface=self)
        return w

    def dev(self, f: int, xf: _Xform) -> dict[int, Vec2]:
        return {v: _xf_apply(xf, p) for v, p in self.layout(f).pts.items()}

    def frame_face(self, k: int) -> tuple[int, int, _Xform]:
        """The side face on ``chain[k]``'s outgoing chain edge, else its incoming one.

        Returns (face, chain neighbour on that edge, the face's placement in
        ``chain[k]``'s wedge frame).
        """
        fr = self._frames.get(k)
        if fr is None:
            band = self.band
            chain, n = band.chain, len(band.chain)
            if band.closed or k < n - 1:
                f, w, phi, left = band.side_faces[k], chain[(k + 1) % n], 0.0, True
            else:  # last vertex of an open chain: chain[k-1] lies at theta, the side clockwise of it
                f, w, phi, left = band.side_faces[k - 1], chain[k - 1], self.wedge(k).theta, False
            fr = self._frames[k] = (f, w, self.place(f, chain[k], w, (0.0, 0.0), (math.cos(phi), math.sin(phi)), left))
        return fr

    def _hop(self, k: int) -> tuple[float, float, float]:
        """(edge length, cos, sin) of the map from ``chain[k+1]``'s wedge frame into ``chain[k]``'s.

        The map rotates by ``pi - theta`` of ``chain[k+1]`` and shifts by the length of
        chain edge ``k`` along +x, which puts the direction to ``chain[k]`` at angle pi.
        """
        hop = self._hops.get(k)
        if hop is None:
            chain, pv = self.band.chain, self.band.verts
            k1 = (k + 1) % len(chain)
            rot = math.pi - self.wedge(k1).theta
            hop = self._hops[k] = (_length(_sub(pv[chain[k1]], pv[chain[k]])), math.cos(rot), math.sin(rot))
        return hop

    def from_next(self, k: int, p: Vec2) -> Vec2:
        """Point ``p`` of ``chain[k+1]``'s wedge frame, in ``chain[k]``'s (chain edge ``k``'s frame)."""
        shift, c, s = self._hop(k)
        return (shift + p[0] * c - p[1] * s, p[0] * s + p[1] * c)

    def to_next(self, k: int, p: Vec2) -> Vec2:
        """Point ``p`` of ``chain[k]``'s wedge frame, in ``chain[k+1]``'s: the inverse of ``from_next``."""
        shift, c, s = self._hop(k)
        x = p[0] - shift
        return (x * c + p[1] * s, p[1] * c - x * s)

    def _centre(self, f: int) -> Vec3:
        """The mean of face ``f``'s corners."""
        c = self._centres.get(f)
        if c is None:
            pts = [self.band.verts[v] for v in self.band.faces[f]]
            c = self._centres[f] = tuple(sum(p[i] for p in pts) / len(pts) for i in range(3))
        return c

    def nearest_frame(self, f: int) -> tuple[int, _Xform] | None:
        """(k, placement) of band face ``f`` in the frame of its nearest frame face; None off every frame face.

        One shortest-path walk spreads from all the frame faces (``frame_face``)
        at once, by the distance between face centres, across the edges
        ``across`` crosses. Each face it settles belongs to the frame face it was
        reached from, so ``f`` is developed from its nearest frame face along the
        surface: locally, never round the band. k is the first chain vertex that
        face frames, and the placement maps ``f``'s layout into chain[k]'s wedge
        frame. The walk goes by distance, not by face count: across a
        triangulated band many frame faces lie the same number of faces away,
        some of them chain vertices off to the side.

        The walk runs only until ``f`` is settled and is kept, so the faces near
        the chain are walked once and a target further out only extends it. Each
        face is laid out once, from the face it was reached from. ``f`` is on no
        frame face's piece of the band when the walk runs out without it.
        """
        walk = self._settle({f})
        near, placed = walk.near, walk.placed
        if f not in near:
            return None
        if f not in placed:  # lay out the faces back to the first one placed, then forward again
            way, g = [], f
            while g not in placed:
                way.append(g)
                g = near[g][1][0]
            for g in reversed(way):
                h, a, b = near[g][1]
                placed[g] = self._beyond(h, placed[h], a, b)[1]
        return near[f][0], placed[f]

    def _settle(self, targets: set[int]) -> _Spread:
        """``nearest_frame``'s walk, run on until one of ``targets`` is settled or it runs out."""
        walk = self._spread
        if walk is None:
            walk = self._spread = _Spread()
            for k in range(len(self.band.chain)):
                g, _, xg = self.frame_face(k)
                if g not in walk.best:
                    walk.best[g] = (0.0, k, None)
                    walk.placed[g] = xg
                    walk.count += 1
                    walk.heap.append((0.0, walk.count, g))
        near, best, heap = walk.near, walk.best, walk.heap
        if any(t in near for t in targets):
            return walk
        faces, edge_faces, blocked = self.band.faces, self.edge_faces, self.blocked
        while heap:
            d, _, h = heapq.heappop(heap)
            if h in near:
                continue
            _, k, came = best[h]
            walk.rank[h] = len(near)
            near[h] = (k, came)
            here = self._centre(h)
            loop = faces[h]
            for i in range(len(loop)):
                a, b = loop[i - 1], loop[i]
                key = _ekey(a, b)
                holders = edge_faces.get(key, ())
                if key in blocked or len(holders) != 2:
                    continue
                g = holders[1] if holders[0] == h else holders[0]
                if g == h or g in near:
                    continue
                dg = d + _length(_sub(self._centre(g), here))
                if g not in best or dg < best[g][0]:
                    best[g] = (dg, k, (h, a, b))
                    walk.count += 1
                    heapq.heappush(heap, (dg, walk.count, g))
            if h in targets:
                break
        return walk

    def holders(self, sp: SurfacePoint) -> list[int]:
        """The band faces holding ``sp``, ``sp.face`` first when it is one; empty off the band.

        A vertex or edge point on another face (or on a face outside the band) is
        held by the band faces that hold its vertex or edge.
        """
        faces = self.band.faces
        if sp.kind == "vert":
            if self._vert_faces is None:  # band faces at each vertex, in band order
                self._vert_faces = {}
                for f, loop in faces.items():
                    for v in loop:
                        at = self._vert_faces.setdefault(v, [])
                        if not at or at[-1] != f:
                            at.append(f)
            out = list(self._vert_faces.get(sp.vert, []))
        elif sp.kind == "edge":
            out = list(self.edge_faces.get(_ekey(*sp.edge), []))
        else:
            out = [sp.face] if sp.face in faces else []
        return sorted(out, key=lambda f: f != sp.face)

    def layout_point(self, sp: SurfacePoint, f: int | None = None) -> tuple[int, Vec2] | None:
        """A band face holding ``sp`` and ``sp``'s position in that face's layout; None off the band.

        The face is ``f`` when given, else the first of ``holders``.
        """
        if f is None:
            holders = self.holders(sp)
            if not holders:
                return None
            f = holders[0]
        lay = self.layout(f)
        if sp.kind == "vert":
            return f, lay.pts[sp.vert]
        if sp.kind == "edge":
            (ax, ay), (bx, by) = lay.pts[sp.edge[0]], lay.pts[sp.edge[1]]
            return f, (ax + (bx - ax) * sp.t, ay + (by - ay) * sp.t)
        pv = self.band.verts
        best = None
        for tri in lay.tris:
            w = _barycentric(sp.co, *(pv[v] for v in tri))
            if w is not None and (best is None or min(w) > min(best[1])):
                best = (tri, w)
        if best is None:
            return None
        tri, w = best
        pts = [lay.pts[v] for v in tri]
        return f, (sum(w[i] * pts[i][0] for i in range(3)), sum(w[i] * pts[i][1] for i in range(3)))

    def in_frames(self, sp: SurfacePoint) -> list[Vec2 | None] | None:
        """``sp`` developed into each chain vertex's wedge frame; None off the band.

        ``sp`` is taken in the face holding it that the nearest-frame walk
        (``nearest_frame``) settles first: the one nearest a frame face. A point on
        an end wall is also held by faces beyond it, and on a closed mesh those can
        be reached the long way round. It is developed from that face into the frame
        of its nearest frame face, and on from there along the chain by the hops
        between neighbouring frames that the loop's segments take (``to_next`` and
        ``from_next``), the shorter way round a closed chain. So it stays local even
        where the band, going round, does not develop back onto itself, as on a
        cone or a cylinder. Every entry is None when no face holding ``sp`` reaches
        a frame face.
        """
        holders = self.holders(sp)
        if not holders:
            return None
        walk = self._settle(set(holders))
        f = min((g for g in holders if g in walk.near), key=walk.rank.__getitem__, default=holders[0])
        found = self.layout_point(sp, f)
        if found is None:
            return None
        f, q = found
        n = len(self.band.chain)
        near = self.nearest_frame(f)
        if near is None:
            return [None] * n
        k0, xf = near
        out: list[Vec2 | None] = [None] * n
        out[k0] = p = _xf_apply(xf, q)
        ahead = n // 2 if self.band.closed else n - 1 - k0
        for k in range(k0, k0 + ahead):
            p = self.to_next(k % n, p)
            out[(k + 1) % n] = p
        p = out[k0]
        for k in range(k0 - 1, k0 - n + ahead if self.band.closed else -1, -1):
            p = self.from_next(k % n, p)
            out[k % n] = p
        return out

    def _forward(self, f: int, a: int, b: int) -> bool:
        loop = self.layout(f).loop
        return loop[(loop.index(a) + 1) % len(loop)] == b

    def place(self, f: int, a: int, b: int, pa: Vec2, pb: Vec2, left: bool) -> _Xform:
        """Place face ``f`` with edge (a, b) at pa -> pb and its interior on the left or right."""
        lay = self.layout(f)
        return _xf_fit(lay.pts[a], lay.pts[b], pa, pb, mirror=self._forward(f, a, b) != left)

    def across(self, f: int, xf: _Xform, a: int, b: int) -> tuple[int, _Xform] | None:
        """Unfold the band face beyond edge (a, b) of face ``f``; None where the band ends or the edge is blocked."""
        if _ekey(a, b) in self.blocked:
            return None
        return self._beyond(f, xf, a, b)

    def _beyond(self, f: int, xf: _Xform, a: int, b: int) -> tuple[int, _Xform] | None:
        """Unfold the band face beyond edge (a, b) of face ``f``, blocked or not; None where the band ends.

        The band ends at an edge that no second band face holds, and at one that
        more than two band faces hold (a fin standing on the surface).
        """
        holders = self.edge_faces.get(_ekey(a, b), ())
        g = next((g for g in holders if g != f), None) if len(holders) == 2 else None
        if g is None:
            return None
        pts = self.layout(f).pts
        left = self._forward(f, a, b) != _xf_mirrored(xf)
        return g, self.place(g, a, b, _xf_apply(xf, pts[a]), _xf_apply(xf, pts[b]), not left)

    def fan(self, f: int, xf: _Xform, v: int, came: int, blocked: set) -> list[tuple[int, _Xform]]:
        """The faces around ``v``, unfolded from face ``f`` (placed by ``xf``), which holds edge (v, came).

        Walks away from (v, came) first, then across it, each way until the band
        border, an edge in ``blocked`` or a face already placed. So the faces on
        ``f``'s side of (v, came) come first.
        """
        out, seen = [(f, xf)], {f}
        loop = self.layout(f).loop
        i = loop.index(v)
        other = loop[(i + 1) % len(loop)] if loop[i - 1] == came else loop[i - 1]
        for far in (other, came):
            g, xg = f, xf
            while _ekey(v, far) not in blocked:
                nxt = self._beyond(g, xg, v, far)
                if nxt is None or nxt[0] in seen:
                    break
                g, xg = nxt
                seen.add(g)
                out.append((g, xg))
                gl = self.layout(g).loop
                j = gl.index(v)
                far = gl[(j + 1) % len(gl)] if gl[j - 1] == far else gl[j - 1]
        return out

    def rail_path(self, k: int, far: int) -> _Path:
        """The rail path of chain[k] that starts on edge (chain[k], far), developed once and kept."""
        path = self._paths.get((k, far))
        if path is None:
            path = self._paths[(k, far)] = self._develop(k, far, self.blocked)
        return path

    def _develop(self, k: int, far: int, blocked: set) -> _Path:
        """Follow edge (chain[k], far) on through rows, unfolding the faces around each vertex reached.

        At each vertex the path goes on along the edge whose developed direction
        turns least from the edge it came along, within ``band.angles.rail_bend``; never
        back to a vertex of the path. A chain vertex ends the path: the chain
        bounds the band. Unfolding stops at ``blocked`` edges. A path edge's
        holder is the first face of the walk around its start that holds it; for
        an end wall that face lies on the wedge's side of the wall.
        """
        chain = self.band.chain
        v = chain[k]
        f, came, xf = self.frame_face(k)
        hold = next((fx for fx in self.fan(f, xf, v, came, blocked) if _has_edge(self.layout(fx[0]).loop, v, far)), None)
        if hold is None:
            raise ValueError(f"edge ({v}, {far}) does not leave the wedge of chain vertex {v}")
        verts, pts, holders = [v, far], [(0.0, 0.0), self.dev(*hold)[far]], [hold]
        while verts[-1] not in chain:
            best = self._way_on((verts, pts, holders), blocked)
            if best is None or best[0] > self.band.angles.rail_bend:
                break
            verts.append(best[1])
            pts.append(best[2])
            holders.append(best[3])
        return verts, pts, holders

    def _way_on(self, path: _Path, blocked: set) -> tuple[float, int, Vec2, tuple[int, _Xform]] | None:
        """The edge on from ``path``'s last vertex that turns least from its last edge, whatever Rail Bend says:
        (turn, far vertex, its developed position, holder); None without one. Never back to a vertex of the path."""
        verts, pts, holders = path
        p, x = verts[-2], verts[-1]
        heading = _sub2(pts[-1], pts[-2])
        best, tried = None, set()
        for g, xg in self.fan(*holders[-1], x, p, blocked):
            loop = self.layout(g).loop
            i = loop.index(x)
            dev = self.dev(g, xg)
            for y in (loop[i - 1], loop[(i + 1) % len(loop)]):
                if y in tried or y in verts:
                    continue
                tried.add(y)
                d = _sub2(dev[y], dev[x])
                turn = abs(math.atan2(_cross2(heading, d), _dot2(heading, d)))
                if best is None or turn < best[0]:
                    best = (turn, y, dev[y], (g, xg))
        return best

    def path_turn(self, path: _Path, blocked: set) -> float | None:
        """How far a path that stopped would turn to go on from its last vertex: what Rail Bend must exceed for it
        to go on. None where nothing would let it: it ends on a chain vertex, or no edge leads on."""
        if path[0][-1] in self.band.chain:
            return None
        best = self._way_on(path, blocked)
        return None if best is None else best[0]

    def corner_holds(self, f: int, xf: _Xform, v: int, d: Vec2) -> bool:
        """Whether direction ``d`` leaves vertex ``v`` into face ``f``'s corner."""
        loop = self.layout(f).loop
        i = loop.index(v)
        dev = self.dev(f, xf)
        dn = _sub2(dev[loop[(i + 1) % len(loop)]], dev[v])
        dp = _sub2(dev[loop[i - 1]], dev[v])
        start, stop = (dp, dn) if _xf_mirrored(xf) else (dn, dp)
        a = _ccw_angle(start, d)
        return a <= _ccw_angle(start, stop) + EPS or a >= 2.0 * math.pi - EPS

    def around(self, f: int, xf: _Xform, v: int, d: Vec2) -> tuple[int, _Xform] | None:
        """The face around vertex ``v`` whose corner holds direction ``d``, walking both ways."""
        if self.corner_holds(f, xf, v, d):
            return f, xf
        loop = self.layout(f).loop
        i = loop.index(v)
        for far in (loop[i - 1], loop[(i + 1) % len(loop)]):
            g, xg, seen = f, xf, {f}
            while True:
                nxt = self.across(g, xg, v, far)
                if nxt is None or nxt[0] in seen:
                    break
                g, xg = nxt
                if self.corner_holds(g, xg, v, d):
                    return g, xg
                seen.add(g)
                gl = self.layout(g).loop
                j = gl.index(v)
                far = gl[(j + 1) % len(gl)] if gl[j - 1] == far else gl[j - 1]
        return None

    def border_step(self, f: int, xf: _Xform, u: int, came: int) -> tuple[int, _Xform, int] | None:
        """The band-border edge after edge (came, u) of face ``f``, around ``u`` on the band side.

        Unfolds the faces around ``u`` from ``f`` across interior edges, so the
        next border edge turns by the band-side corner angle at ``u``. Returns
        (face owning border edge (u, far), its placement, far), or None where a
        chain edge comes first: the border path ends there.
        """
        for _ in range(len(self.band.faces)):
            loop = self.layout(f).loop
            i = loop.index(u)
            far = loop[(i + 1) % len(loop)] if loop[i - 1] == came else loop[i - 1]
            if _ekey(u, far) in self.chain_edges:
                return None
            nxt = self.across(f, xf, u, far)
            if nxt is None:
                return f, xf, far
            (f, xf), came = nxt, far
        return None

    def edge_point(self, f: int, a: int, b: int, t: float) -> SurfacePoint:
        lo, hi, t = (a, b, t) if a < b else (b, a, 1.0 - t)
        p, q = self.band.verts[lo], self.band.verts[hi]
        co = (p[0] + (q[0] - p[0]) * t, p[1] + (q[1] - p[1]) * t, p[2] + (q[2] - p[2]) * t)
        return SurfacePoint("edge", f, co, edge=(lo, hi), t=t)

    def point(self, f: int, xf: _Xform, x: Vec2) -> SurfacePoint:
        """The surface point at development position ``x`` in face ``f``, snapped to its corners and edges."""
        lay = self.layout(f)
        dev = self.dev(f, xf)
        for v in lay.loop:
            if _len2(_sub2(x, dev[v])) <= self.tol:
                return SurfacePoint("vert", f, self.band.verts[v], vert=v)
        n = len(lay.loop)
        for i in range(n):
            a, b = lay.loop[i], lay.loop[(i + 1) % n]
            t, foot = _foot(dev[a], dev[b], x)
            if _len2(_sub2(x, foot)) <= self.tol:
                return self.edge_point(f, a, b, t)
        q = _xf_invert(xf, x)
        best = None
        for tri in lay.tris:
            pa, pb, pc = (lay.pts[v] for v in tri)
            den = _cross2(_sub2(pb, pa), _sub2(pc, pa))
            if den == 0.0:
                continue
            wb = _cross2(_sub2(q, pa), _sub2(pc, pa)) / den
            wc = _cross2(_sub2(pb, pa), _sub2(q, pa)) / den
            w = (1.0 - wb - wc, wb, wc)
            if best is None or min(w) > min(best[1]):
                best = (tri, w)
        if best is None:
            raise ValueError(f"face {f} is degenerate")
        tri, w = best
        pv = self.band.verts
        co = tuple(sum(w[j] * pv[tri[j]][i] for j in range(3)) for i in range(3))
        return SurfacePoint("face", f, co)

    def snap_end(self, tr: Trace) -> Trace:
        """``tr`` with its end moved onto the nearest vertex, else edge, of its face within ``_ANCHOR_SNAP_TOL``.

        Anchors snap before segments are traced, so a crossing that a segment drops
        near an anchor lies on an element the anchor already sits on.
        """
        f, x = tr._face, tr.end_xy
        loop = self.layout(f).loop
        dev = self.dev(f, tr._xf)
        v = min(loop, key=lambda v: _len2(_sub2(x, dev[v])))
        if _len2(_sub2(x, dev[v])) <= _ANCHOR_SNAP_TOL:
            pt, q = SurfacePoint("vert", f, self.band.verts[v], vert=v), dev[v]
        else:
            n = len(loop)
            feet = [(loop[i], loop[(i + 1) % n], *_foot(dev[loop[i]], dev[loop[(i + 1) % n]], x)) for i in range(n)]
            a, b, t, q = min(feet, key=lambda e: _len2(_sub2(x, e[3])))
            if _len2(_sub2(x, q)) > _ANCHOR_SNAP_TOL:
                return tr
            pt = self.edge_point(f, a, b, t)
        return Trace(tr.crossings, pt, tr.blocked, q, f, tr._xf)

    def _exit(
        self, f: int, xf: _Xform, p: Vec2, target: Vec2, skip_vert: int | None, skip_edge: tuple[int, int] | None
    ) -> tuple[float, int, int, float] | None:
        """First edge the segment p -> target leaves face ``f`` through: (s, a, b, u) or None."""
        loop = self.layout(f).loop
        dev = self.dev(f, xf)
        d = _sub2(target, p)
        dl = _len2(d)
        out_sign = 1.0 if _xf_mirrored(xf) else -1.0
        best = None
        for i in range(len(loop)):
            a, b = loop[i], loop[(i + 1) % len(loop)]
            if skip_vert in (a, b) or _ekey(a, b) == skip_edge:
                continue
            e = _sub2(dev[b], dev[a])
            el = _len2(e)
            # The interior is left of a -> b unless the placement is mirrored; an exit heads out.
            if el == 0.0 or out_sign * _cross2(e, d) <= EPS * el * dl:
                continue
            ap = _sub2(dev[a], p)
            den = _cross2(d, e)
            s, u = _cross2(ap, e) / den, _cross2(ap, d) / den
            if s * dl < -self.tol or u * el < -self.tol or (u - 1.0) * el > self.tol:
                continue
            if best is None or s < best[0]:
                best = (s, a, b, min(1.0, max(0.0, u)))
        return best

    def _leave(self, f: int, xf: _Xform, start: SurfacePoint, d: Vec2) -> tuple[int, _Xform] | None:
        """The face a path leaving ``start`` in direction ``d`` runs into."""
        if start.kind == "vert":
            return self.around(f, xf, start.vert, d)
        if start.kind == "edge":
            a, b = start.edge
            dev = self.dev(f, xf)
            e = _sub2(dev[b], dev[a])
            side = _cross2(e, d)  # > 0 heads left of a -> b
            if self._forward(f, a, b) == _xf_mirrored(xf):  # interior right of a -> b
                side = -side
            return (f, xf) if side >= -EPS * _len2(e) else self.across(f, xf, a, b)
        return f, xf

    def trace(self, f: int, xf: _Xform, start: SurfacePoint, p: Vec2, target: Vec2) -> Trace:
        """Trace straight from ``start`` (at ``p`` on face ``f``) to ``target``."""
        pv = self.band.verts
        crossings: list[SurfacePoint] = []
        if _len2(_sub2(target, p)) <= self.tol:
            return Trace(crossings, start, False, p, f, xf)
        nxt = self._leave(f, xf, start, _unit2(_sub2(target, p)))
        if nxt is None:
            return Trace(crossings, start, True, p, f, xf)
        f, xf = nxt
        skip_vert = start.vert if start.kind == "vert" else None
        skip_edge = start.edge if start.kind == "edge" else None
        for _ in range(self.max_steps):
            hit = self._exit(f, xf, p, target, skip_vert, skip_edge)
            dl = _len2(_sub2(target, p))
            if hit is None or hit[0] * dl >= dl - self.tol:
                return Trace(crossings, self.point(f, xf, target), False, target, f, xf)
            s, a, b, u = hit
            x = (p[0] + (target[0] - p[0]) * s, p[1] + (target[1] - p[1]) * s)
            dev = self.dev(f, xf)
            v = next((v for v in (a, b) if _len2(_sub2(x, dev[v])) <= self.tol), None)
            if v is None:
                nxt = self.across(f, xf, a, b)
                if nxt is None:
                    return Trace(crossings, self.edge_point(f, a, b, u), True, x, f, xf)
                f, xf = nxt
                crossings.append(self.edge_point(f, a, b, u))
                p, skip_vert, skip_edge = x, None, _ekey(a, b)
                continue
            q = dev[v]
            here = SurfacePoint("vert", f, pv[v], vert=v)
            rest = _sub2(target, q)
            if _len2(rest) <= self.tol:
                return Trace(crossings, here, False, q, f, xf)
            nxt = self.around(f, xf, v, _unit2(rest))
            if nxt is None:
                return Trace(crossings, here, True, q, f, xf)
            f, xf = nxt
            crossings.append(SurfacePoint("vert", f, pv[v], vert=v))
            p, skip_vert, skip_edge = q, v, None
        raise RuntimeError("trace did not terminate")


def trace_from_vertex(
    band: Band, k: int, angle: float, length: float, *, _surface: _Surface | None = None
) -> Trace:
    """Trace from ``chain[k]`` in its wedge frame (``angle`` 0 along +x, side at +y)."""
    v = band.chain[k]
    surf = _Surface(band) if _surface is None else _surface
    f, _, xf = surf.frame_face(k)
    start = SurfacePoint("vert", f, band.verts[v], vert=v)
    return surf.trace(f, xf, start, (0.0, 0.0), (length * math.cos(angle), length * math.sin(angle)))


def rail_path(band: Band, k: int, rail: Rail, *, _surface: _Surface | None = None) -> list[tuple[int, Vec2]]:
    """The rail continued through rows: vertex ids from ``chain[k]``, each at its position in ``chain[k]``'s wedge frame.

    The first entry is ``chain[k]`` at (0, 0), the second ``rail.far``. At each
    vertex reached the path goes on along the band edge whose developed
    direction turns least from straight on, within ``band.angles.rail_bend``; never along
    a chain edge or back to a vertex of the path. It stops at the band border,
    on a chain vertex (the chain bounds the band), or where no edge qualifies.
    The faces unfold as the traces unfold them, and neither chain edges nor end
    walls are unfolded across.
    """
    surf = _Surface(band) if _surface is None else _surface
    verts, pts, _ = surf.rail_path(k, rail.far)
    return list(zip(verts, pts))


def end_paths(band: Band, *, _surface: _Surface | None = None) -> tuple[list[int], list[int]]:
    """The vertex ids of the paths an open chain's ends slide along, at ``chain[0]`` and ``chain[-1]``.

    Each runs from its chain end out along the end wall (see ``_Surface.end_path``).
    Empty at an end without an end edge, and for a closed chain.
    """
    surf = _Surface(band) if _surface is None else _surface
    start, stop = ([] if path is None else list(path[0]) for path in (surf.end_path(True), surf.end_path(False)))
    return start, stop


def wedges(band: Band) -> list[Wedge]:
    """Every chain vertex's wedge (see ``wedge``), over one adjacency of the band.

    Raises ``ValueError`` where a wedge cannot be swept, or an end wall cannot
    leave its end vertex's wedge.
    """
    surf = _Surface(band)
    return [surf.wedge(k) for k in range(len(band.chain))]


class _InconsistentDevelopmentError(ValueError):
    """A segment trace missed its partner point: the development is not flat between them."""


def trace_segment(
    band: Band, k: int, a: Trace, b: Trace, *, _surface: _Surface | None = None, meet_tol: float = _SEGMENT_MEET_TOL
) -> Trace:
    """Trace from ``a.end`` to ``b.end`` in chain edge ``k``'s frame.

    ``a`` was traced from ``chain[k]`` and ``b`` from ``chain[k + 1]`` (wrapping on
    a closed chain). ``b``'s wedge frame maps into edge ``k``'s frame (the wedge
    frame of ``chain[k]``) by a rotation of ``pi - theta`` and a shift of the edge
    length along +x, which puts the direction to ``chain[k]`` at angle pi.

    Raises ``ValueError("inconsistent development")`` when the segment misses
    ``b.end`` by more than ``meet_tol``; a blocked segment is returned without that check. Crossings
    within that same tolerance of ``a.end`` or ``b.end`` are dropped: the end
    points stand for them.
    """
    surf = _Surface(band) if _surface is None else _surface
    seg = surf.trace(a._face, a._xf, a.end, a.end_xy, surf.from_next(k, b.end_xy))
    if not seg.blocked and _length(_sub(seg.end.co, b.end.co)) > meet_tol:
        raise _InconsistentDevelopmentError("inconsistent development")
    seg.crossings = [
        x for x in seg.crossings
        if _length(_sub(x.co, a.end.co)) > _SEGMENT_MEET_TOL and _length(_sub(x.co, b.end.co)) > _SEGMENT_MEET_TOL
    ]
    return seg


# --- Placement and solve --------------------------------------------------------


class OutOfRoom(Exception):  # noqa: N818 - public name fixed by the plan
    """A placement or segment trace left the band: the width does not fit."""


@dataclass
class Placement:
    trace: Trace
    rail: Rail | None  # the rail followed, also past its path's end; None for a miter
    width_error: float


@dataclass
class Cut:
    """The new loop of one band.

    ``points`` run in chain order (a closed loop wraps); between consecutive
    anchors they hold that segment's crossings. ``anchors[k]`` indexes
    ``chain[k]``'s new vertex in ``points``; the chain vertices of a collapsed
    segment share one index. ``connectors`` are ``(vertex id, points index)``
    edges to add: from a chain vertex to its miter, or from the last vertex of a
    rail path to the new vertex placed past it. ``width`` is the width solved;
    ``clamped`` tells whether it is below the width asked for. ``breaks`` holds
    each index ``i`` where no new edge runs from ``points[i-1]`` to ``points[i]``;
    on a closed loop 0 is the wrap edge. Only the destructive mode
    (``smart_edge_slide_wave``) sets it, and ``inner``: the breaks that lie
    inside one piece of the loop (a piece pressed onto its walls, its points
    there apart), not between two pieces, and ``rings``: the breaks that start a
    piece which closes on itself (a ring the loop split into where it touched
    itself), its last point joined to its first.
    """

    points: list[SurfacePoint]
    anchors: list[int | None]
    connectors: list[tuple[int, int]]
    width: float
    clamped: bool
    breaks: tuple[int, ...] = ()
    inner: tuple[int, ...] = ()
    rings: tuple[int, ...] = ()


@dataclass(frozen=True)
class _Route:
    """How one chain vertex's new vertex moves with width, in that vertex's wedge frame.

    With a ``rail`` it runs along the developed rail path ``pts`` (from (0, 0)),
    ``hs`` holding the balanced width at each point, strictly increasing. Past
    ``hs[-1]`` it runs out along the bisector (angle ``half``, theta / 2) on a ray
    from ``pts[ray]``, the path's last point. ``ray`` is 0, the chain vertex
    itself, for a miter: without a rail. ``lean . Q`` is (d_out - d_in) / 2 at a
    point Q, so its size is the width error there. It is constant along the ray,
    since ``lean`` is normal to the bisector.
    """

    rail: Rail | None
    pts: tuple[Vec2, ...]
    hs: tuple[float, ...]
    lean: Vec2
    half: float
    ray: int

    def leg(self, width: float) -> int:
        """The rail path edge the new vertex lies on at ``width``, or -1 past the path, on the ray."""
        hs = self.hs
        if self.rail is None or width > hs[-1]:
            return -1
        return bisect.bisect_left(hs, width, 1) - 1  # the first edge whose far end reaches ``width``

    def run(self, width: float) -> float:
        """How far along the ray the new vertex lies at ``width``: the balanced width grows by sin(half) per unit."""
        return (width - self.hs[self.ray]) / math.sin(self.half)

    def along(self, s: float) -> Vec2:
        """The point ``s`` along the ray."""
        x, y = self.pts[self.ray]
        return (x + s * math.cos(self.half), y + s * math.sin(self.half))


def _coincide(p: SurfacePoint, q: SurfacePoint) -> bool:
    """Whether two consecutive loop points are one new vertex (same position).

    Two points on one edge at different ``t`` stay apart: a loop running along
    part of an existing edge keeps both ends, and the cut reuses that edge piece.
    """
    if p.kind == q.kind == "vert" and p.vert == q.vert:
        return True
    if p.kind == q.kind == "edge" and p.edge == q.edge and abs(p.t - q.t) <= EPS:
        return True
    return _length(_sub(p.co, q.co)) <= EPS


def _bisect(hi: float, attempt) -> float:
    """The largest width in [0, hi] at which ``attempt(width)`` raises no ``OutOfRoom``.

    ``hi`` itself when it fits, else ``LIMIT_ITERS`` halvings, assuming widths fit
    up to one bound and not past it.
    """
    try:
        attempt(hi)
        return hi
    except OutOfRoom:
        pass
    lo = 0.0
    for _ in range(LIMIT_ITERS):
        mid = 0.5 * (lo + hi)
        try:
            attempt(mid)
            lo = mid
        except OutOfRoom:
            hi = mid
    return lo


class Slider:
    """Places the new loop of one band at a given width.

    Keeps one surface (adjacency, face layouts, wedges, each face's way to its
    nearest frame face) for every trace it runs, and caches the placement rule
    per vertex, the traces along each rail path and the limits, so the band must
    not change while the Slider is in use.

    Positions before tracing are worked out in development frames: each chain
    vertex's wedge frame (``chain[k]`` at the origin, angle 0 toward ``chain[k+1]``,
    the side at +y), which is also chain edge ``k``'s frame.
    """

    def __init__(self, band: Band):
        self.band = band
        self._surf = _Surface(band)
        self._aims: dict[tuple[int, bool], _Route] = {}
        self._legs: dict[int, list[Trace]] = {}
        self._rays: dict[tuple[int, int], tuple[float, float]] = {}
        self._limits: dict[tuple[bool, bool], float] = {}
        self._schedules: dict[bool, list[tuple[float, list[int] | None]]] = {}

    def end_paths(self) -> tuple[list[int], list[int]]:
        """``end_paths`` of the band, over this Slider's surface: the paths its open ends slid along."""
        return end_paths(self.band, _surface=self._surf)

    def end_wall_stop(self, at_start: bool) -> tuple[int | None, float | None]:
        """(the vertex the end wall at the start or end ends at, how far it would turn to go on past it:
        ``_Surface.path_turn``). (None, None) without an end wall of its own; the turn None where nothing would let it
        go on."""
        surf = self._surf
        end = surf.end_index(at_start)
        path = None if end is None else surf.end_path(at_start)
        if path is None or path[0] != surf.rail_path(*end)[0]:  # turned onto the other wall: it ends on the chain
            return None, None
        return path[0][-1], surf.path_turn(path, surf.chain_edges)

    def rail_stop(self, k: int) -> tuple[int | None, float | None]:
        """(the vertex ``chain[k]``'s rail path ends at, what Rail Bend must exceed for its new vertex to follow a
        rail further): without a rail, the chain vertex itself and the smallest lean of a rail from the bisector; with
        one, how far its path would turn to go on past its end. The turn is None where no rail would do, or the vertex
        leaves its rail path before that end."""
        surf = self._surf
        route = self._aim(k, False)
        wd = surf.wedge(k)
        if route.rail is None:
            leans = [abs(r.angle - wd.theta / 2.0) for r in wd.rails if not r.border]
            return self.band.chain[k], min(leans, default=None)
        path = surf.rail_path(k, route.rail.far)
        if len(route.pts) < len(path[1]):
            return path[0][len(route.pts) - 1], None
        return path[0][-1], surf.path_turn(path, surf.blocked)

    def _trace(self, k: int, angle: float, length: float) -> Trace:
        """An anchor trace from ``chain[k]``, its end snapped onto nearby mesh elements."""
        tr = trace_from_vertex(self.band, k, angle, length, _surface=self._surf)
        if tr.blocked:
            raise OutOfRoom(f"vertex {self.band.chain[k]} has no room at angle {angle:.6f}")
        return self._surf.snap_end(tr)

    def _segment(self, k: int, a: Trace, b: Trace) -> Trace:
        try:
            seg = trace_segment(self.band, k, a, b, _surface=self._surf)
        except _InconsistentDevelopmentError as exc:
            raise OutOfRoom(f"segment {k} misses its partner point") from exc
        if seg.blocked:
            raise OutOfRoom(f"segment {k} leaves the band")
        return seg

    def _aim(self, k: int, exact: bool) -> _Route:
        """How ``chain[k]``'s new vertex moves with width: along the rail nearest the bisector, else the miter.

        The rail path is developed once per Slider. A point Q of it lies at the
        balanced width ``(d_out + d_in) / 2``, d_out and d_in being Q's distances to
        the outgoing and incoming chain edge lines. That is linear in Q, so each
        path edge covers a range of widths. The path is used while that width
        grows along it, and with ``exact`` only up to its last point whose width
        error stays within ``EXACT_TOL``.

        Past the path the vertex goes on along the bisector from the path's last
        point, in both modes, so it never jumps. The width error stays at its
        value there, which exact mode keeps within ``EXACT_TOL``. Without a usable
        rail edge the vertex is a miter at every width.
        """
        route = self._aims.get((k, exact))
        if route is None:
            surf = self._surf
            wd = surf.wedge(k)
            theta = wd.theta
            rail = min(
                (r for r in wd.rails if not r.border and abs(r.angle - theta / 2.0) <= surf.band.angles.rail_bend),
                key=lambda r: abs(r.angle - theta / 2.0),
                default=None,
            )
            # d_out = Q.y and d_in = Q.x sin(theta) - Q.y cos(theta), so both are linear in Q.
            gain = (0.5 * math.sin(theta), 0.5 * (1.0 - math.cos(theta)))  # (d_out + d_in) / 2 = gain . Q
            lean = (-0.5 * math.sin(theta), 0.5 * (1.0 + math.cos(theta)))  # (d_out - d_in) / 2 = lean . Q
            pts, hs = [(0.0, 0.0)], [0.0]
            if rail is not None:
                for q in surf.rail_path(k, rail.far)[1][1:]:
                    h = _dot2(gain, q)
                    if h <= hs[-1] + surf.tol or (exact and abs(_dot2(lean, q)) > EXACT_TOL * h):
                        break
                    pts.append(q)
                    hs.append(h)
            ray = len(pts) - 1
            route = _Route(rail if len(pts) > 1 else None, tuple(pts), tuple(hs), lean, theta / 2.0, ray)
            self._aims[(k, exact)] = route
        return route

    def _at(self, k: int, width: float, exact: bool) -> tuple[_Route, int, Vec2]:
        """``chain[k]``'s new vertex at ``width``: (route, rail path edge it lies on or -1 on the ray, position).

        A point on the ray must fit on the band (see ``_ray_fits``), else ``OutOfRoom``.
        """
        route = self._aim(k, exact)
        i = route.leg(width)
        if i >= 0:
            hs = route.hs
            (ax, ay), (bx, by) = route.pts[i], route.pts[i + 1]
            s = (width - hs[i]) / (hs[i + 1] - hs[i])
            return route, i, (ax + (bx - ax) * s, ay + (by - ay) * s)
        s = route.run(width)
        if not self._ray_fits(k, route, s):
            raise OutOfRoom(f"vertex {self.band.chain[k]} has no room {s:.6f} along its bisector")
        return route, -1, route.along(s)

    def _ray_fits(self, k: int, route: _Route, s: float) -> bool:
        """Whether the point ``s`` along ``chain[k]``'s ray (see ``_Route``) can be traced on the band.

        The ray is traced once per Slider, 4 x band diagonal / sin(half) out:
        past where the widest width ``limit`` tries puts the vertex. When the ray
        starts at the path's end, the trace runs along the path first. A trace to any point
        short of where that one is blocked runs the same way and stays clear.
        So the plan needs no further trace for this ray, and the bound it
        accepts holds for the solve's own traces without a tolerance.
        """
        key = (k, route.ray)
        reach, stop = self._rays.get(key, (-math.inf, math.inf))
        if s > reach and stop == math.inf:  # not traced this far out yet
            reach = max(s, 4.0 * _band_scale(self.band) / math.sin(route.half))
            if route.ray == 0:
                tr, leg = trace_from_vertex(self.band, k, route.half, reach, _surface=self._surf), 0
            else:
                tr, _, leg = self._walk(k, route, route.ray, route.along(reach))
            if tr.blocked:  # on the ray, or (-inf) already on the path that leads to it
                stop = _len2(_sub2(tr.end_xy, route.pts[route.ray])) if leg == route.ray else -math.inf
            self._rays[key] = (reach, stop)
        return s <= stop

    def place(self, k: int, width: float, *, exact: bool = False) -> Placement:
        """Place ``chain[k]``'s new vertex: on the rail path nearest the bisector, else on the miter.

        On a rail the anchor is where the path gives the balanced width, traced
        along the path. Past the path's end it goes on along the bisector from
        there, keeping the width error it had at the path's end.
        """
        route, i, q = self._at(k, width, exact)
        if i >= 0:
            return Placement(self._follow(k, route, i, q), route.rail, abs(_dot2(route.lean, q)))
        if route.ray == 0:  # the miter
            return Placement(self._trace(k, route.half, route.run(width)), None, 0.0)
        error = abs(_dot2(route.lean, route.pts[route.ray]))
        return Placement(self._follow(k, route, route.ray, q), route.rail, error)

    def _path_legs(self, k: int, route: _Route, m: int) -> list[Trace]:
        """The traces from ``chain[k]`` along its rail path, leg i ending at ``route.pts[i + 1]``.

        Holds the first ``m`` legs at least, unless one of them is blocked: the
        legs stop after a blocked one. Each leg runs on from where the one before
        ended, as ``_walk`` traces it. Every width past a path point walks the
        same legs up to it, so each is traced once per Slider and kept. Both modes
        share them: exact mode's path points are the first of the default mode's
        (see ``_aim``).
        """
        legs = self._legs.setdefault(k, [])
        surf = self._surf
        while len(legs) < m and not (legs and legs[-1].blocked):
            x, y = route.pts[len(legs) + 1]
            if legs:
                tr = legs[-1]
                legs.append(surf.trace(tr._face, tr._xf, tr.end, tr.end_xy, (x, y)))
            else:
                legs.append(trace_from_vertex(self.band, k, math.atan2(y, x), math.hypot(x, y), _surface=surf))
        return legs

    def _walk(self, k: int, route: _Route, m: int, last: Vec2) -> tuple[Trace, list[SurfacePoint], int]:
        """Trace from ``chain[k]`` along its rail path to ``route.pts[m]``, then on to ``last`` (wedge frame).

        Stops at a blocked leg. The legs along the path come from ``_path_legs``.
        Returns (the last leg traced, the crossings so far with each path point
        reached, that leg's index: ``m`` for the leg to ``last``).
        """
        if m == 0:
            x, y = last
            tr = trace_from_vertex(self.band, k, math.atan2(y, x), math.hypot(x, y), _surface=self._surf)
            return tr, list(tr.crossings), 0
        legs = self._path_legs(k, route, m)
        crossings = list(legs[0].crossings)
        for i in range(1, m + 1):
            tr = legs[i - 1]
            if tr.blocked:
                return tr, crossings, i - 1
            crossings.append(tr.end)
            if i < m:
                crossings += legs[i].crossings
        tr = self._surf.trace(tr._face, tr._xf, tr.end, tr.end_xy, last)
        crossings += tr.crossings
        return tr, crossings, m

    def _follow(self, k: int, route: _Route, m: int, last: Vec2) -> Trace:
        """An anchor trace from ``chain[k]`` along its rail path to ``route.pts[m]`` and on to ``last``.

        Snapped as ``_trace`` snaps; straight to ``last`` when ``m`` is 0.
        """
        if m == 0:
            x, y = last
            return self._trace(k, math.atan2(y, x), math.hypot(x, y))
        tr, crossings, _ = self._walk(k, route, m, last)
        if tr.blocked:
            raise OutOfRoom(f"vertex {self.band.chain[k]} has no room along its rail path")
        return self._surf.snap_end(Trace(crossings, tr.end, False, tr.end_xy, tr._face, tr._xf))

    def _border_hit(self, at_start: bool, width: float) -> tuple[int, _Xform, int, int, float, float]:
        """Where the end chain edge's offset line at ``width`` meets the end vertex's end path or border path.

        The end path is the rail path of the band's end edge, turned onto the
        other end's wall where the two walls meet (``_Surface.end_path``), so
        ``limit`` bounds the same path the solve slides along. Without an end
        edge the border path stands in: the wedge's border rail, then the
        band-border edges after it. Either is developed into the end vertex's
        wedge frame and the first edge hit wins. Returns (face, placement, u,
        far, s, gq): the line crosses edge (u, far) of that face at parameter
        ``s`` from ``u``, and ``far`` lies ``gq >= -_ANCHOR_SNAP_TOL`` past the line
        (so ``s`` may run a hair past 1).
        """
        surf = self._surf
        k = 0 if at_start else len(self.band.chain) - 1
        u = self.band.chain[k]
        f, came, xf = surf.frame_face(k)
        # (nx, ny): unit normal of the end chain edge toward the side, so n.p - width is
        # the signed distance of p past the offset line.
        if at_start:  # the chain edge runs along +x, the side at +y
            nx, ny = 0.0, 1.0
        else:  # the chain edge runs at theta, the side clockwise of it
            theta = surf.wedge(k).theta
            nx, ny = math.sin(theta), -math.cos(theta)
        path = surf.end_path(at_start)
        if path is not None:
            verts, pts, holders = path
            for i in range(len(verts) - 1):
                p, q = pts[i], pts[i + 1]
                gq = nx * q[0] + ny * q[1] - width
                if gq >= -_ANCHOR_SNAP_TOL:
                    gp = nx * p[0] + ny * p[1] - width
                    return *holders[i], verts[i], verts[i + 1], (gp / (gp - gq) if gp != gq else 0.0), gq
            raise OutOfRoom(f"the end wall at vertex {u} ends before width {width:.6f}")
        for _ in range(len(surf.edge_faces)):
            step = surf.border_step(f, xf, u, came)
            if step is None:
                break
            f, xf, far = step
            dev = surf.dev(f, xf)
            p, q = dev[u], dev[far]
            gq = nx * q[0] + ny * q[1] - width
            if gq >= -_ANCHOR_SNAP_TOL:
                gp = nx * p[0] + ny * p[1] - width
                return f, xf, u, far, (gp / (gp - gq) if gp != gq else 0.0), gq
            u, came = far, u
        raise OutOfRoom(f"the border path from vertex {self.band.chain[k]} ends before width {width:.6f}")

    def _end(self, at_start: bool, width: float) -> Trace:
        """An open chain's end point at ``width``, as a trace from the end vertex in its wedge frame."""
        surf = self._surf
        f, xf, u, far, s, gq = self._border_hit(at_start, width)
        dev = surf.dev(f, xf)
        if gq <= _ANCHOR_SNAP_TOL:  # the offset line runs through the border vertex
            pt, x = SurfacePoint("vert", f, self.band.verts[far], vert=far), dev[far]
        else:
            (px, py), (qx, qy) = dev[u], dev[far]
            pt, x = surf.edge_point(f, u, far, s), (px + (qx - px) * s, py + (qy - py) * s)
        return surf.snap_end(Trace([], pt, False, x, f, xf))

    def _end_xy(self, at_start: bool, width: float) -> Vec2:
        """The end point at ``width`` in the end vertex's wedge frame, before any snapping."""
        f, xf, u, far, s, _ = self._border_hit(at_start, width)
        dev = self._surf.dev(f, xf)
        (px, py), (qx, qy) = dev[u], dev[far]
        return (px + (qx - px) * s, py + (qy - py) * s)

    def solve(self, width: float, *, exact: bool = False, collapse: bool = False) -> Cut:
        """The new loop at ``width``, clamped to ``limit``.

        ``width`` itself is tried first, so the limit is only searched for once a
        width does not fit. ``collapse`` drops segments that fold back instead of
        stopping at them.
        """
        try:
            return self._solve(width, exact, collapse)
        except OutOfRoom:
            limit = self.limit(exact=exact, collapse=collapse)
            if width <= limit:  # a gap below the limit: there is no width to clamp to
                raise
            cut = self._solve(limit, exact, collapse)
            cut.clamped = width > limit + EPS
            return cut

    def limit(self, *, exact: bool = False, collapse: bool = False) -> float:
        """The largest width that fits, by bisection on [0, 4 x band bbox diagonal]; cached.

        The trace-free plan is bisected first: whatever it rejects, ``solve`` rejects
        too, so full solves only confirm or refine below that bound.
        """
        key = (exact, collapse)
        if key not in self._limits:
            planned = _bisect(4.0 * _band_scale(self.band), lambda w: self._plan(w, exact, collapse))
            self._limits[key] = _bisect(planned, lambda w: self._solve(w, exact, collapse))
        return self._limits[key]

    def snap_width(self, target: SurfacePoint, *, exact: bool = False, collapse: bool = False) -> float | None:
        """The width in (0, limit] at which the new loop reaches ``target``, or None.

        Bisects the signed in-surface offset of ``target`` from the loop, positive
        while ``target`` lies beyond it, between the last of ``_SNAP_SCAN`` even
        samples still positive and the first that is not. The loop never comes
        back over a target it passed, but a loop collapsing to a point near the
        limit has segments too short to give the offset a sign, so the first
        change counts, not the one at the limit. An offset within the surface
        tolerance counts as reached: a target exactly where the limit stops the
        loop is off it by float noise of either sign. None when the offset does
        not get there: ``target`` is off the band, behind the chain or out of
        reach. ``collapse`` reaches past folds as ``solve`` does. At width 0 the
        loop is the chain itself, so the offset there needs no plan: a target
        behind the chain costs no rail path, and the limit is only looked for once
        ``target`` lies beyond the chain.
        """
        spots = self._surf.in_frames(target)
        if spots is None:
            return None

        def offset(width: float) -> float:
            return self._offset(spots, *self._plan(width, exact, collapse))

        n = len(self.band.chain)
        lo = 0.0
        try:
            if self._offset(spots, [(0.0, 0.0)] * n, [False] * (n if self.band.closed else n - 1)) <= 0.0:
                return None
            top = self.limit(exact=exact, collapse=collapse)
            if top <= 0.0:
                return None
            for i in range(1, _SNAP_SCAN + 1):
                hi = top * i / _SNAP_SCAN
                if offset(hi) <= self._surf.tol:
                    break
                lo = hi
            else:
                return None
            for _ in range(SNAP_ITERS):
                mid = 0.5 * (lo + hi)
                if offset(mid) > 0.0:
                    lo = mid
                else:
                    hi = mid
        except OutOfRoom:  # a gap below the limit
            return None
        return 0.5 * (lo + hi)

    def _offset(self, spots: list[Vec2 | None], xy: list[Vec2], dropped: list[bool]) -> float:
        """Signed offset of a target from the loop planned as ``xy`` and ``dropped`` (``_plan``), positive beyond it.

        ``spots`` holds the target in each chain vertex's wedge frame. The offset is
        taken from the loop segment nearest the target, in its chain edge's frame,
        from the vertex positions before tracing; dropped segments have no length
        and are skipped. -inf when no segment's frame reaches the target.
        """
        n = len(xy)
        best = None
        for k in range(len(dropped)):
            p = spots[k]
            if p is None or dropped[k]:
                continue
            a, b = xy[k], self._surf.from_next(k, xy[(k + 1) % n])
            d = _len2(_sub2(p, _foot(a, b, p)[1]))
            if best is None or d < best[0]:
                best = (d, a, b, p)
        if best is None:
            return -math.inf
        _, a, b, p = best
        e = _sub2(b, a)
        el = _len2(e)
        return _cross2(e, _sub2(p, a)) / el if el > EPS else p[1] - a[1]

    def _plan(self, width: float, exact: bool, collapse: bool) -> tuple[list[Vec2], list[bool]]:
        """The new vertices at ``width``, each in its chain vertex's wedge frame, and the dropped segments.

        Works without traces, but for one per vertex ray, made once per Slider
        (``_ray_fits``). With ``collapse`` the segments the fold schedule drops by
        ``width`` are dropped. Raises ``OutOfRoom`` when a vertex's ray leaves the
        band, an end wall or border path ends, the schedule stops, or a segment
        still folds back (its length along its chain edge reaches 0).
        """
        dropped = [False] * (len(self.band.chain) if self.band.closed else len(self.band.chain) - 1)
        if collapse:
            for at, segs in self._schedule(exact):
                if segs is None and at <= width:
                    raise OutOfRoom(f"the collapsing loop runs out of room at width {at:.6f}")
                if segs is None or at > width + self._surf.tol:  # a drop holds a hair early
                    break
                for k in segs:
                    dropped[k] = True
        xy = self._positions(width, exact, dropped)
        for k in range(len(dropped)):
            if not dropped[k] and self._seg_length(k, xy) <= 0.0:
                raise OutOfRoom(f"segment {k} folds back at width {width:.6f}")
        return xy, dropped

    def _positions(self, width: float, exact: bool, dropped: list[bool]) -> list[Vec2]:
        """Each new vertex at ``width`` in its chain vertex's wedge frame, merged groups on their shared point.

        Raises ``OutOfRoom`` when the ray of a vertex that is not merged leaves the
        band, or an end wall or border path ends.
        """
        n, closed = len(self.band.chain), self.band.closed
        base: list[Vec2] = []
        for k in range(n):
            if not closed and k in (0, n - 1):  # the end points slide along the end walls
                base.append(self._end_xy(k == 0, width))
            elif dropped[k - 1] or dropped[k]:  # replaced by its group's shared point
                base.append((0.0, 0.0))
            else:
                base.append(self._at(k, width, exact)[2])
        return self._merge(base, dropped, width)

    def _schedule(self, exact: bool) -> list[tuple[float, list[int] | None]]:
        """The collapse events (see ``_fold_events``), worked out once per ``exact``."""
        if exact not in self._schedules:
            self._schedules[exact] = self._fold_events(exact)
        return self._schedules[exact]

    def _fold_events(self, exact: bool) -> list[tuple[float, list[int] | None]]:
        """The collapse events in width order: (width, segments dropped there).

        A segment folds back when its length along its chain edge reaches 0. For
        one set of drops every droppable segment's length is linear in width
        between the widths where a rail path bends or ends (its ends are interior
        or merged vertices), so each fold width is exact. The first segment to
        fold is dropped, with any folding at that same width, and the rest are
        worked out again. Segments None stop the schedule: past that width the
        collapse has no room. That happens when fewer than three segments of a
        closed loop are left, or when before the next drop an open chain's end
        segment folds (collapse never drops it), a vertex's ray leaves the band or
        an end wall or border path ends. A segment already folded where a stretch
        starts is dropped there.
        """
        band, surf = self.band, self._surf
        n, closed = len(band.chain), band.closed
        m = n if closed else n - 1
        inner = range(n) if closed else range(1, n - 1)  # the open ends never merge
        bends = sorted({h for k in inner for h in self._aim(k, exact).hs[1:]})
        cap = 4.0 * _band_scale(band)
        events: list[tuple[float, list[int] | None]] = []
        dropped, now = [False] * m, 0.0
        while True:
            nxt = next((h for h in bends if h > now + surf.tol), math.inf)
            lines = [((0.0, 0.0), (0.0, 0.0))] * n
            for k in inner:
                lines[k] = self._line(k, exact, now + 1.0 if nxt == math.inf else 0.5 * (now + nxt))
            w1 = now + 1.0
            try:
                xy0 = self._merge([(a[0] + now * d[0], a[1] + now * d[1]) for a, d in lines], dropped, now)
                xy1 = self._merge([(a[0] + w1 * d[0], a[1] + w1 * d[1]) for a, d in lines], dropped, w1)
            except OutOfRoom:  # a merged group's outer chain edges run parallel: it has no shared point
                events.append((now, None))
                return events
            folds = []
            for k in range(m) if closed else range(1, m - 1):
                if not dropped[k]:
                    l0 = self._seg_length(k, xy0)
                    rate = self._seg_length(k, xy1) - l0
                    if rate < 0.0:
                        folds.append((max(now, now - l0 / rate), k))
                    elif l0 < -surf.tol:  # already folded where this stretch starts
                        folds.append((now, k))
            at = min(folds)[0] if folds else math.inf
            if at > min(nxt, cap):  # nothing folds before the next bend
                if nxt > cap:
                    return events
                now = nxt
                continue
            now = at
            try:
                xy = self._positions(now, exact, dropped)
                if not closed and min(self._seg_length(0, xy), self._seg_length(m - 1, xy)) <= 0.0:
                    raise OutOfRoom("an end segment folds back")
            except OutOfRoom:
                events.append((now, None))
                return events
            segs = [k for at, k in folds if at <= now + surf.tol]
            for k in segs:
                dropped[k] = True
            if closed and dropped.count(False) < 3:
                events.append((now, None))
                return events
            events.append((now, segs))

    def _line(self, k: int, exact: bool, width: float) -> tuple[Vec2, Vec2]:
        """(a, d): ``chain[k]``'s new vertex lies at a + w * d for w on the stretch of widths around ``width``.

        The stretch runs between the widths where the vertex's rail path bends or
        ends; past its end the ray's line holds.
        """
        route = self._aim(k, exact)
        hs, pts = route.hs, route.pts
        i = route.leg(width)
        if i >= 0:
            (px, py), (qx, qy) = pts[i], pts[i + 1]
            dh = hs[i + 1] - hs[i]
            dx, dy = (qx - px) / dh, (qy - py) / dh
            return (px - hs[i] * dx, py - hs[i] * dy), (dx, dy)
        s = 1.0 / math.sin(route.half)
        dx, dy = s * math.cos(route.half), s * math.sin(route.half)
        (px, py), h = pts[route.ray], hs[route.ray]
        return (px - h * dx, py - h * dy), (dx, dy)

    def _seg_length(self, k: int, xy: list[Vec2]) -> float:
        """Length of segment ``k`` along chain edge ``k``, in that edge's frame (<= 0 once it folds)."""
        return self._surf.from_next(k, xy[(k + 1) % len(xy)])[0] - xy[k][0]

    def _runs(self, dropped: list[bool]) -> list[tuple[int, int]]:
        """Merged vertex groups as (first, last) chain indices: segments first .. last-1 are dropped."""
        n, m = len(self.band.chain), len(dropped)
        runs = []
        for i in range(m):
            if dropped[i] and not dropped[i - 1]:
                j = i
                while dropped[j % m]:
                    j += 1
                runs.append((i, j % n))
        return runs

    def _merge(self, base: list[Vec2], dropped: list[bool], width: float) -> list[Vec2]:
        """``base`` with each merged group moved onto its shared point, expressed in every member's frame."""
        xy = list(base)
        n = len(xy)
        for i, j in self._runs(dropped):
            p, k = self._meet(i, j, width), i
            xy[k] = p
            while k != j:
                p, k = self._surf.to_next(k, p), (k + 1) % n
                xy[k] = p
        return xy

    def _meet(self, i: int, j: int, width: float) -> Vec2:
        """Where the offset lines of chain edges i-1 and j meet, in ``chain[i]``'s wedge frame."""
        surf, n = self._surf, len(self.band.chain)
        theta = surf.wedge(i).theta
        nx, ny = math.sin(theta), -math.cos(theta)  # edge i-1's offset line is n.p == width
        p, q, k = (0.0, width), (1.0, width), j  # edge j's offset line, in chain[j]'s frame
        while k != i:
            k = (k - 1) % n
            p, q = surf.from_next(k, p), surf.from_next(k, q)
        dx, dy = q[0] - p[0], q[1] - p[1]
        den = nx * dx + ny * dy
        if abs(den) <= EPS:
            raise OutOfRoom(f"the chain edges around vertex {self.band.chain[i]} run parallel")
        s = (width - nx * p[0] - ny * p[1]) / den
        return (p[0] + s * dx, p[1] + s * dy)

    def _solve(self, width: float, exact: bool, collapse: bool) -> Cut:
        """The new loop at ``width`` without clamping; raises ``OutOfRoom`` when it does not fit."""
        band = self.band
        chain, n, closed = band.chain, len(band.chain), band.closed
        if width <= _ANCHOR_SNAP_TOL:  # anchors this close would snap onto the chain itself
            return Cut([], [None] * n, [], 0.0, False)
        xy, dropped = self._plan(width, exact, collapse)
        places: list[Placement | None] = [None] * n
        ends: list[Trace] = []
        for k in range(n):
            if not closed and k in (0, n - 1):
                ends.append(self._end(k == 0, width))
                continue
            if dropped[k - 1] or dropped[k]:  # a merged vertex: trace straight to the shared point
                x, y = xy[k]
                places[k] = Placement(self._trace(k, math.atan2(y, x), math.hypot(x, y)), None, 0.0)
            else:
                places[k] = self.place(k, width, exact=exact)
            ends.append(places[k].trace)
        for i, j in self._runs(dropped):
            k = i
            while k != j:
                k = (k + 1) % n
                if _length(_sub(ends[k].end.co, ends[i].end.co)) > _SEGMENT_MEET_TOL:
                    raise OutOfRoom(f"vertices {chain[i]} and {chain[k]} miss their shared point")

        points: list[SurfacePoint] = []
        anchors: list[int | None] = [None] * n

        def add(pt: SurfacePoint) -> int:
            if not points or not _coincide(points[-1], pt):
                points.append(pt)
            return len(points) - 1

        # A closed loop starts on a vertex that begins its group, so no group wraps past the end.
        start = next(k for k in range(n) if not dropped[k - 1]) if closed else 0
        anchors[start] = add(ends[start].end)
        for i in range(len(dropped)):
            k = (start + i) % n
            k1 = (k + 1) % n
            if dropped[k]:
                anchors[k1] = anchors[k]
                continue
            for pt in self._segment(k, ends[k], ends[k1]).crossings:
                add(pt)
            if k1 != start:  # a closed loop's last segment ends on the start anchor
                anchors[k1] = add(ends[k1].end)
        # The last segment of a closed loop ends on the first anchor; drop a tail repeating it.
        while closed and len(points) > 1 and _coincide(points[-1], points[0]):
            last = len(points) - 1
            points.pop()
            anchors = [0 if i == last else i for i in anchors]

        return Cut(points, anchors, self._connectors(places, anchors, width, exact), width, False)

    def _connectors(
        self, places: list[Placement | None], anchors: list[int | None], width: float, exact: bool
    ) -> list[tuple[int, int]]:
        """The connecting edges of a cut: each straight last leg of a placement that crosses nothing.

        A miter runs straight from its chain vertex. A vertex placed past its rail
        path's end runs straight on from the path's last vertex; its trace passed
        that vertex just before the last leg, so the leg crossed nothing when that
        vertex is the trace's last crossing.
        """
        out = []
        for k, p in enumerate(places):
            if p is None or p.trace.blocked:
                continue
            if p.rail is None:
                if not p.trace.crossings:
                    out.append((self.band.chain[k], anchors[k]))
                continue
            route = self._aim(k, exact)
            if route.ray > 0 and route.leg(width) < 0:
                last = self._surf.rail_path(k, route.rail.far)[0][route.ray]
                x = p.trace.crossings[-1] if p.trace.crossings else None
                if x is not None and x.kind == "vert" and x.vert == last:
                    out.append((last, anchors[k]))
        return out


# --- Screen-side helpers --------------------------------------------------------


def _inside(p: Vec2, poly: list[Vec2]) -> bool:
    """Even-odd test of ``p`` against the closed polygon ``poly``."""
    inside = False
    for i in range(len(poly)):
        (x0, y0), (x1, y1) = poly[i - 1], poly[i]
        if (y0 > p[1]) != (y1 > p[1]) and p[0] < x0 + (p[1] - y0) * (x1 - x0) / (y1 - y0):
            inside = not inside
    return inside


def positive_side(chain_xy: list[Vec2], plus_xy: Vec2 | None, minus_xy: Vec2 | None, closed: bool) -> int:
    """Which band side (+1 or -1) a positive width slides into, judged on screen.

    ``plus_xy`` and ``minus_xy`` are the projected band centroids of the two sides
    (None for a side without a band). An open chain takes the side with the larger
    screen x, a closed chain the side inside its projected polygon. A missing side
    gives the other one; when neither side wins, +1.
    """
    if plus_xy is None or minus_xy is None:
        return -1 if plus_xy is None and minus_xy is not None else 1
    if closed:
        return -1 if _inside(minus_xy, chain_xy) and not _inside(plus_xy, chain_xy) else 1
    return -1 if minus_xy[0] > plus_xy[0] else 1


def nearest_chain(chains_xy: list[list[Vec2]], closed: list[bool], mouse: Vec2) -> int:
    """Index of the projected chain nearest ``mouse``; a closed chain includes its closing edge."""

    def distance(i: int) -> float:
        pts = chains_xy[i]
        if len(pts) == 1:
            return _len2(_sub2(mouse, pts[0]))
        edges = range(len(pts) if closed[i] else len(pts) - 1)
        return min(_len2(_sub2(mouse, _foot(pts[j], pts[(j + 1) % len(pts)], mouse)[1])) for j in edges)

    return min(range(len(chains_xy)), key=distance)
