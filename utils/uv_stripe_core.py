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
import random
from dataclasses import dataclass, field, replace


Vec3 = tuple[float, float, float]
Vec2 = tuple[float, float]

TUTTE_ITERS = 1000
TUTTE_TOL = 1e-12
TIE_TOL = 1e-9
CACHES: list[dict] = []   # every remembered result of the UV Stripe cores, for ``uv_stripe_balance_core.clear_caches``
DEFAULT_BALANCE = 0.5   # the Balance slider's default: halfway from the least stretch (0) to even texels (1)
WELD = 0.01  # points closer than this fraction of the strip height count as one point (``weld_tolerance``)
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
    # How the rows are laid out: "EVEN" (each row by its own arc length, scaled to L),
    # "STRAIGHT" (between vertical posts, ``_post_u``), "TRUE" (true lengths, ``_true_u``) or
    # "SHAPE" (the faces unfolded at their real shape, ``_shape_uv``); the last two for an open strip
    # only, a closed one uses "EVEN". "BALANCED" (``uv_stripe_balance_core.balanced_uvs``, an open strip)
    # lays it out with ``ends``, ``rails`` and ``balance`` below. The layouts are internal: the operator
    # asks for what must be straight and ``uv_stripe_auto_core`` picks the layout by measured stretch.
    layout: str = "EVEN"
    # A closed strip's seam: the index into ``rungs`` it is cut at; None picks ``sharpest_rung``.
    seam: int | None = None
    # A ring opened at a rung (``uv_stripe_select_core.open_ring``): that rung's edge, a sorted vertex-id pair.
    break_edge: tuple[int, int] | None = None
    # A closed band several faces wide cut open along a cross path (``uv_stripe_select_core``): that path's edges,
    # sorted pairs of real vertex ids. The faces on one side of the cut name its vertices by their stand-in ids
    # (``real_vertex``), so each side of the cut has vertices of its own.
    cut_path: tuple = ()
    # What "SHAPE" turns the unfold to run along +u (``_shape_direction``): "AUTO", "LONGEST" or "SHORTEST" (that
    # row edge) or "PICKED" (``align_edge``, a sorted vertex-id pair; "AUTO" when it is not in the strip).
    align: str = "AUTO"
    align_edge: tuple[int, int] | None = None
    # The "BALANCED" layout's modes (``uv_stripe_balance_core.balanced_uvs``): which ends stand upright ("FREE",
    # "BOTH", "START" for the end at u = 0, "END"), which rails are straight ("BOTH", "NEAR", "FAR") and how
    # the stretch is spread: the Balance slider, 0 the least stretch to 1 every face near its real size
    # (``uv_stripe_balance_core.balance_value``; the old names "LEAST_STRETCH" and "EVEN_TEXEL" read as 0 and 1).
    ends: str = "FREE"
    rails: str = "BOTH"
    balance: float = DEFAULT_BALANCE
    # Lines picked to be straight (V in the interactive mode), each (axis, frozenset of vertex ids): "ALONG" shares
    # one v (a horizontal line, running along the strip), "ACROSS" one u (a vertical line, across it). The balanced
    # layout keeps them (``uv_stripe_balance_core``); any other layout is taken only when it already does
    # (``uv_stripe_auto_core``).
    lines: tuple = ()


def stand_in(v: int) -> int:
    """The stand-in id of vertex ``v`` on the far side of a cut a closed band is opened along (``Strip.cut_path``):
    a negative id, so it never meets a mesh vertex index."""
    return -1 - v


def real_vertex(v: int) -> int:
    """The mesh vertex a strip's vertex id stands for: itself, or the vertex a stand-in id (``stand_in``) copies."""
    return v if v >= 0 else -1 - v


def real_pair(edge) -> tuple[int, int]:
    """A vertex-id pair with stand-in ids (``stand_in``) replaced by their vertices, sorted."""
    a, b = real_vertex(edge[0]), real_vertex(edge[1])
    return (a, b) if a < b else (b, a)


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


def weld_tolerance(strip: Strip) -> float:
    """How close two points are to count as one: ``WELD`` of the strip height (an unmerged double)."""
    return max(WELD * strip.height, TIE_TOL)


def welded_neighbour(verts: dict[int, Vec3], ring: list[int], k: int, step: int, tol: float,
                     closed: bool = True) -> int | None:
    """The first position from ``k`` going ``step`` (+1 or -1) whose point is farther than ``tol`` from
    position ``k``'s; None when there is none (an open ring's end)."""
    n, p = len(ring), verts[ring[k]]
    j = k
    for _ in range(n - 1):
        j += step
        if not closed and not 0 <= j < n:
            return None
        if math.dist(verts[ring[j % n]], p) > tol:
            return j % n
    return None


def welded_angle(verts: dict[int, Vec3], ring: list[int], k: int, tol: float, closed: bool = True) -> float:
    """The corner angle at position ``k`` of a vertex ring, its neighbours closer than ``tol`` skipped, so an
    unmerged double has the corner of the one point it stands for; straight (pi) without two neighbours."""
    i = welded_neighbour(verts, ring, k, -1, tol, closed)
    j = welded_neighbour(verts, ring, k, 1, tol, closed)
    if i is None or j is None:
        return math.pi
    return _angle(verts[ring[i]], verts[ring[k]], verts[ring[j]])


def sharpest_rung(strip: Strip) -> int:
    """Rung whose near vertex has the smallest corner angle (``welded_angle``); the lowest rung wins a tie."""
    near, verts = strip.near, strip.verts
    tol = weld_tolerance(strip)
    best, best_angle = 0, math.inf
    for k, (ni, _fi) in enumerate(strip.rungs):
        ang = welded_angle(verts, near, ni % len(near), tol)
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


def _posts(strip: Strip, un: list[int], uf: list[int], tol: float):
    """The posts of a strip and its rows' arc lengths: (posts, near arcs, far arcs).

    Posts, in unwrapped order: the rows' start, every rung that strictly advances both
    the near and the far index over the last post, by more than ``tol`` of length on
    both rows, and lies strictly before the end on both, then the rows' end (an open
    strip's last positions; a closed strip's seam rung one loop later). A post the end
    does not advance from by more than ``tol`` on both rows is dropped, so a collapsed
    run or an unmerged double never makes a span of its own. The arcs map unwrapped
    positions to the arc length from the start.
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
        return arc_n[q[0]] - arc_n[p[0]] > tol and arc_f[q[1]] - arc_f[p[1]] > tol

    posts = [start]
    for a, b in cands:
        if posts[-1][0] < a < end[0] and posts[-1][1] < b < end[1] and advances(posts[-1], (a, b)):
            posts.append((a, b))
    while len(posts) > 1 and not advances(posts[-1], end):
        posts.pop()
    posts.append(end)
    return posts, arc_n, arc_f


def _fill_spans(strip: Strip, posts, arc_n, arc_f, u_posts) -> tuple[list[float], list[float]]:
    """U of every row position: each post's (near u, far u) from ``u_posts``, a position inside a span by its
    own arc-length fraction between its row's two post positions (evenly over a span with no length)."""
    nn, nf = len(strip.near), len(strip.far)
    u_near, u_far = [0.0] * nn, [0.0] * nf
    for (a0, b0), (a1, b1), (n0, f0), (n1, f1) in zip(posts, posts[1:], u_posts, u_posts[1:]):
        for out, arc, i0, i1, u0, u1, n in ((u_near, arc_n, a0, a1, n0, n1, nn), (u_far, arc_f, b0, b1, f0, f1, nf)):
            d = arc[i1] - arc[i0]
            for j in range(i0, i1):
                t = (arc[j] - arc[i0]) / d if d > 1e-12 else (j - i0) / (i1 - i0)
                out[j % n] = u0 + (u1 - u0) * t
    if not strip.closed:
        u_near[nn - 1], u_far[nf - 1] = u_posts[-1]
    return u_near, u_far


def _post_u(strip: Strip, un: list[int], uf: list[int]) -> tuple[list[float], list[float]]:
    """U of every near and far position, laid out between vertical posts (``_posts``).

    Each span between two posts is as long as the mean of the two rows' arcs over it;
    a row position inside a span takes its share by its own arc length. The last post
    is at ``strip_length``.
    """
    posts, arc_n, arc_f = _posts(strip, un, uf, weld_tolerance(strip))
    u_posts, u = [(0.0, 0.0)], 0.0
    for (a0, b0), (a1, b1) in zip(posts, posts[1:]):
        u += (arc_n[a1] - arc_n[a0] + arc_f[b1] - arc_f[b0]) / 2.0
        u_posts.append((u, u))
    return _fill_spans(strip, posts, arc_n, arc_f, u_posts)


def _row_direction(verts: dict[int, Vec3], row: list[int], i: int, tol: float) -> list[list[float]]:
    """The unit directions of the row edges meeting position ``i`` (incoming, outgoing), each to the first
    point farther than ``tol``; one at a row end, none along a row with no length."""
    out = []
    for step in (-1, 1):
        j = welded_neighbour(verts, row, i, step, tol, closed=False)
        if j is None:
            continue
        a, b = (verts[row[j]], verts[row[i]]) if step < 0 else (verts[row[i]], verts[row[j]])
        d = [b[c] - a[c] for c in range(3)]
        n = math.sqrt(sum(x * x for x in d))
        out.append([x / n for x in d])
    return out


def _true_u(strip: Strip) -> tuple[list[float], list[float], float]:
    """U of every near and far position at the rows' true lengths, and the u extent (an open strip).

    The rows are resynchronised at every post (``_posts``; the start and the end are
    posts): a post's far point leads its near point by the rung's own projection on the
    strip direction there, the mean of the unit directions of the row edges meeting the
    post on both rows (points closer than ``weld_tolerance`` count as one, so an
    unmerged double does not turn the direction; one-sided at the ends; no lead when
    there is none). Post centres advance by the mean of the two rows' span lengths;
    the near post sits half the lead behind its centre, the far post half ahead, and a
    position inside a span takes its own arc-length fraction between its row's two
    posts. Across a flat span between straight rails every edge keeps its length, and
    where a span bends the error stays in that span. The result is shifted so the
    smallest u is 0.
    """
    verts, near, far = strip.verts, strip.near, strip.far
    tol = weld_tolerance(strip)
    un, uf = _unwrapped(strip, 0)
    posts, arc_n, arc_f = _posts(strip, un, uf, tol)
    u_posts, centre = [], 0.0
    for k, (a, b) in enumerate(posts):
        if k:
            a0, b0 = posts[k - 1]
            centre += (arc_n[a] - arc_n[a0] + arc_f[b] - arc_f[b0]) / 2.0
        dirs = _row_direction(verts, near, a, tol) + _row_direction(verts, far, b, tol)
        d = [sum(x[c] for x in dirs) for c in range(3)]
        n = math.sqrt(sum(x * x for x in d))
        lead = 0.0
        if n > TIE_TOL:
            lead = sum((verts[far[b]][c] - verts[near[a]][c]) * d[c] / n for c in range(3))
        u_posts.append((centre - lead / 2.0, centre + lead / 2.0))
    u_near, u_far = _fill_spans(strip, posts, arc_n, arc_f, u_posts)
    low = min(min(u_near), min(u_far))
    u_near = [u - low for u in u_near]
    u_far = [u - low for u in u_far]
    return u_near, u_far, max(max(u_near), max(u_far))


def _row_turn(verts, row: list[int], tol: float) -> float:
    """How much an open row turns in all: the sum of pi minus its welded corner angles."""
    return sum(math.pi - welded_angle(verts, row, k, tol, closed=False) for k in range(1, len(row) - 1))


def _sub(a, b) -> list[float]:
    return [a[c] - b[c] for c in range(len(a))]


def _cross(a, b) -> list[float]:
    return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]


def _flatten_face(verts: dict[int, Vec3], face: tuple[int, ...], tiny: float) -> list[Vec2] | None:
    """One face laid flat on its own, counter-clockwise for its own winding: a 2D point per corner, or None.

    A triangle fan from the first corner v0: v0 at the origin, every other corner at its real
    distance from v0, turned from the last corner farther than ``tiny`` from v0 by the real 3D
    angle between the two at v0, to the side the face's normal (its vector area) gives. So the
    fan triangles keep their shape and every polygon edge its length, also on a planar concave
    face. None for a face with no area.
    """
    pts = [verts[v] for v in face]
    normal = [0.0, 0.0, 0.0]
    for a, b in zip(pts, pts[1:] + pts[:1]):
        c = _cross(a, b)
        normal = [normal[i] + c[i] for i in range(3)]
    if math.sqrt(sum(x * x for x in normal)) <= tiny * tiny:
        return None
    p0 = pts[0]
    out: list[Vec2] = [(0.0, 0.0)]
    ref, ref_angle = None, 0.0
    for p in pts[1:]:
        w = _sub(p, p0)
        r = math.sqrt(sum(x * x for x in w))
        if r <= tiny:
            out.append((0.0, 0.0))
            continue
        if ref is None:
            angle = 0.0
        else:
            c = _cross(ref, w)
            side = sum(c[i] * normal[i] for i in range(3))
            sine = math.sqrt(sum(x * x for x in c))
            angle = ref_angle + math.atan2(sine if side >= 0.0 else -sine, sum(ref[i] * w[i] for i in range(3)))
        out.append((r * math.cos(angle), r * math.sin(angle)))
        ref, ref_angle = w, angle
    return out


def _unfold(strip: Strip) -> dict[int, Vec2] | None:
    """The strip's faces unfolded across their shared edges: vertex id -> 2D point, or None.

    Every face is flattened on its own (``_flatten_face``); from the first face in
    ``strip.faces`` order the faces are walked breadth-first over shared edges, each face
    reached across an edge turned and moved (never mirrored or scaled) so that edge's two
    vertices land on their placed points. Faces keep their own counter-clockwise winding. None
    when a vertex would take two positions (an interior vertex of a doubly curved patch, a
    row that starts and ends on one vertex), when a row repeats an id, and for a face with no
    area or a shared edge with no length.
    """
    if (len(set(strip.near)) != len(strip.near) or len(set(strip.far)) != len(strip.far)
            or strip.corner_near or strip.corner_far or not strip.faces):
        return None
    verts = strip.verts
    xs = [verts[v] for v in {v for face in strip.faces.values() for v in face}]
    size = math.sqrt(sum((max(p[c] for p in xs) - min(p[c] for p in xs)) ** 2 for c in range(3)))
    tiny = max(1e-9 * size, 1e-15)
    tol = max(1e-6 * size, 1e-12)
    flat = {}
    for fid, face in strip.faces.items():
        f = _flatten_face(verts, face, tiny)
        if f is None:
            return None
        flat[fid] = dict(zip(face, f))
    edge_faces: dict[tuple[int, int], list[int]] = {}
    for fid, face in strip.faces.items():
        for a, b in zip(face, face[1:] + face[:1]):
            edge_faces.setdefault((min(a, b), max(a, b)), []).append(fid)

    first = next(iter(strip.faces))
    pos: dict[int, Vec2] = dict(flat[first])
    done, queue = {first}, [first]
    while queue:
        fid = queue.pop(0)
        face = strip.faces[fid]
        for a, b in zip(face, face[1:] + face[:1]):
            for other in edge_faces[(min(a, b), max(a, b))]:
                if other in done:
                    continue
                local = flat[other]
                ring = strip.faces[other]
                if ring[(ring.index(a) + 1) % len(ring)] == b:
                    # the neighbour runs the shared edge the same way: it winds against this face (a flipped
                    # normal), so its own flattening is mirrored to keep it on the other side of the edge
                    local = {v: (x, -y) for v, (x, y) in local.items()}
                    flat[other] = local
                pa, pb, la, lb = pos[a], pos[b], local[a], local[b]
                d_glob, d_loc = _sub(pb, pa), _sub(lb, la)
                if math.hypot(*d_glob) <= tiny or math.hypot(*d_loc) <= tiny:
                    return None
                turn = math.atan2(d_glob[1], d_glob[0]) - math.atan2(d_loc[1], d_loc[0])
                cs, sn = math.cos(turn), math.sin(turn)
                for v, (x, y) in local.items():
                    x, y = x - la[0], y - la[1]
                    p = (pa[0] + cs * x - sn * y, pa[1] + sn * x + cs * y)
                    if v in pos:
                        if math.dist(p, pos[v]) > tol:
                            return None
                    else:
                        pos[v] = p
                done.add(other)
                queue.append(other)
    if len(done) != len(strip.faces):
        return None
    return pos


def _welded_edges(verts: dict[int, Vec3], row: list[int], tol: float) -> list[tuple[int, int]]:
    """(start, end) positions of an open row's welded edges: each from a position to the first one farther than
    ``tol`` from it, so an unmerged double makes no edge of its own."""
    out = []
    i = 0
    while i < len(row) - 1:
        j = welded_neighbour(verts, row, i, 1, tol, closed=False)
        if j is None:
            break
        out.append((i, j))
        i = j
    return out


def align_edge_in(strip: Strip, edges) -> tuple[int, int] | None:
    """The first of ``edges`` (vertex-id pairs) that is an edge of one of the strip's faces, sorted; None when
    there is none. A strip torn into pieces gives each piece its own picked align edge this way."""
    own = {tuple(sorted((a, b))) for face in strip.faces.values() for a, b in zip(face, face[1:] + face[:1])}
    for edge in edges:
        key = tuple(sorted(edge))
        if key in own:
            return key
    return None


def _auto_direction(strip: Strip, pos: dict[int, Vec2], tol: float) -> list[float]:
    """The "AUTO" direction of an unfold: the straighter row's (the near row on a tie; ``_row_turn``) one welded
    edge longer than half the row, else its chord from first to last position."""
    verts = strip.verts
    on_far = _row_turn(verts, strip.far, tol) < _row_turn(verts, strip.near, tol) - 1e-9
    base = strip.far if on_far else strip.near
    welded = _welded_edges(verts, base, tol)
    row_length = sum(math.dist(verts[base[a]], verts[base[b]]) for a, b in welded)
    direction = _sub(pos[base[-1]], pos[base[0]])
    for a, b in welded:
        if math.dist(verts[base[a]], verts[base[b]]) > row_length / 2.0:
            direction = _sub(pos[base[b]], pos[base[a]])
    return direction


def _shape_direction(strip: Strip, pos: dict[int, Vec2], tol: float) -> list[float]:
    """The unfold direction that is turned to +u, by ``strip.align``.

    "LONGEST" / "SHORTEST": the longest / shortest welded row edge by real length, over
    the near row and then the far row (never a cross edge), in row order; the first one on
    a tie. "PICKED": ``align_edge`` when both its vertices are in the unfold: an edge of
    the near or far row (its two ids next to each other there) in row order, any other
    edge (a cross edge, an end side, a diagonal) turned a quarter, so it is laid along v.
    Anything else, a picked edge outside the strip, and a direction with no length (an
    edge shorter than ``tol``) give "AUTO" (``_auto_direction``).
    """
    verts, align = strip.verts, strip.align
    direction = None
    if align in ("LONGEST", "SHORTEST"):
        best = None
        for row in (strip.near, strip.far):
            for a, b in _welded_edges(verts, row, tol):
                length = math.dist(verts[row[a]], verts[row[b]])
                if (best is None or (align == "LONGEST" and length > best[0] + TIE_TOL)
                        or (align == "SHORTEST" and length < best[0] - TIE_TOL)):
                    best = (length, row[a], row[b])
        if best is not None:
            direction = _sub(pos[best[2]], pos[best[1]])
    elif align == "PICKED" and strip.align_edge is not None and all(v in pos for v in strip.align_edge):
        pair = set(strip.align_edge)
        for row in (strip.near, strip.far):
            for a, b in zip(row, row[1:]):
                if {a, b} == pair:
                    direction = _sub(pos[b], pos[a])
                    break
            if direction is not None:
                break
        else:
            a, b = strip.align_edge
            x, y = _sub(pos[b], pos[a])
            direction = [y, -x]
        if math.dist(verts[strip.align_edge[0]], verts[strip.align_edge[1]]) <= tol:
            direction = None
    if direction is None or math.hypot(*direction) <= TIE_TOL:
        return _auto_direction(strip, pos, tol)
    return direction


def _shape_uv(strip: Strip):
    """The true-shape layout of an open strip: (near (u, v), far (u, v), sides' (u, v), u extent, v extent).

    The faces are unfolded across their shared edges (``_unfold``), each keeping its real
    shape, so a strip that turns in its surface turns in UV, as Unwrap lays it out. The
    unfold is turned so the strip runs along +u, the direction chosen by ``strip.align``
    (``_shape_direction``; "AUTO": the straighter row's one welded edge longer than half
    the row, else its chord); then turned by 180 degrees when the near row lies above the
    far row. It is never mirrored. Shifted so the smallest u and v are 0; the sides hold
    every vertex on neither row (end sides and inner vertices). A strip that cannot
    unfold, or whose direction has no length, takes ``_shape_uv_projected``, which
    ignores ``align``.
    """
    pos = _unfold(strip)
    if pos is None:
        return _shape_uv_projected(strip)
    direction = _shape_direction(strip, pos, weld_tolerance(strip))
    if math.hypot(*direction) <= TIE_TOL:
        return _shape_uv_projected(strip)
    turn = -math.atan2(direction[1], direction[0])
    cs, sn = math.cos(turn), math.sin(turn)
    pos = {v: (cs * x - sn * y, sn * x + cs * y) for v, (x, y) in pos.items()}
    if (sum(pos[v][1] for v in strip.near) / len(strip.near)
            > sum(pos[v][1] for v in strip.far) / len(strip.far)):
        pos = {v: (-x, -y) for v, (x, y) in pos.items()}
    low_u = min(u for u, _v in pos.values())
    low_v = min(v for _u, v in pos.values())
    pos = {k: (u - low_u, v - low_v) for k, (u, v) in pos.items()}
    rows = set(strip.near) | set(strip.far)
    near_uv = [pos[v] for v in strip.near]
    far_uv = [pos[v] for v in strip.far]
    sides = {v: p for v, p in pos.items() if v not in rows}
    return near_uv, far_uv, sides, max(u for u, _v in pos.values()), max(v for _u, v in pos.values())


def _shape_uv_projected(strip: Strip):
    """The projected true-shape layout, for a strip ``_unfold`` cannot lay out; the tuple of ``_shape_uv``.

    One row, the straighter of the two (the near row on a tie), is the straight line
    of its true arc length (an unmerged double, closer than ``weld_tolerance``, sits on
    its partner's point). Every vertex of the other row and of the end sides is placed
    by its own real offset from that row: on the base edge it is nearest to, u = that
    edge's start u plus the offset along the edge, the offset across it is its distance
    from the base row. The near row lies at v = distance below the far row's base when
    the far row is the base, else the far row at v = distance above the near row; v
    runs from 0. A flat strip with one straight rail is mapped one to one, its width
    followed wherever it changes; a bend of the base rail only affects the vertices
    placed against the edges meeting at it. Shifted so the smallest u is 0. None when
    the base row has no length.
    """
    verts = strip.verts
    tol = weld_tolerance(strip)
    on_far = _row_turn(verts, strip.far, tol) < _row_turn(verts, strip.near, tol) - 1e-9
    base, other = (strip.far, strip.near) if on_far else (strip.near, strip.far)
    u_base = [0.0]
    for a, b in zip(base, base[1:]):
        u_base.append(u_base[-1] + math.dist(verts[a], verts[b]))
    edges = []                              # (start position, unit direction, end point) of the welded base edges
    i = 0
    while i < len(base) - 1:
        j = welded_neighbour(verts, base, i, 1, tol, closed=False)
        if j is None:
            break
        a, b = verts[base[i]], verts[base[j]]
        d = [b[c] - a[c] for c in range(3)]
        n = math.sqrt(sum(x * x for x in d))
        edges.append((i, [x / n for x in d], b))
        i = j
    if not edges:
        return None

    def place(p, near_edges=edges):
        best = None
        for i, e, b in near_edges:
            a = verts[base[i]]
            w = [p[c] - a[c] for c in range(3)]
            along = sum(w[c] * e[c] for c in range(3))
            t = min(max(along, 0.0), math.dist(a, b))
            gap = math.dist(p, [a[c] + e[c] * t for c in range(3)])
            across = math.sqrt(max(sum(x * x for x in w) - along * along, 0.0))
            if best is None or gap < best[0] - TIE_TOL:
                best = (gap, u_base[i] + along, across)
        return best[1], best[2]

    base_uv = [(u, 0.0) for u in u_base]
    other_uv = [place(verts[v]) for v in other]
    if len(other) > 1 and other[0] == other[-1] and len(edges) > 1:
        # A row that starts and ends on one vertex (an opened ring): the base row's first and last edges meet
        # at the break, so a position is placed against the edges of its own half (its end: that end's edge).
        last = len(other) - 1
        for k, v in enumerate(other):
            if k == 0 or k == last:
                own = edges[:1] if k == 0 else edges[-1:]
            else:
                own = edges[:-1] if 2 * k < last else edges[1:]
            other_uv[k] = place(verts[v], own)
    sides = {v: place(verts[v]) for side in strip.sides for v in side}
    top = max([v for _u, v in other_uv] + [v for _u, v in sides.values()])
    if on_far:                              # the far row is the straight one: it lies on top, the near row below
        base_uv = [(u, top) for u, _v in base_uv]
        other_uv = [(u, top - v) for u, v in other_uv]
        sides = {k: (u, top - v) for k, (u, v) in sides.items()}
    near_uv, far_uv = (other_uv, base_uv) if on_far else (base_uv, other_uv)
    low = min(u for u, _v in near_uv + far_uv + list(sides.values()))
    near_uv = [(u - low, v) for u, v in near_uv]
    far_uv = [(u - low, v) for u, v in far_uv]
    sides = {k: (u - low, v) for k, (u, v) in sides.items()}
    extent = max(u for u, _v in near_uv + far_uv + list(sides.values()))
    return near_uv, far_uv, sides, extent, top


def strip_extent(strip: Strip) -> float:
    """The u extent ``stripe_uvs`` lays the strip out over: its true length span under "TRUE" or "SHAPE"
    (an open strip), its balanced length under "BALANCED" (an open strip), else ``strip_length``."""
    if not strip.closed and strip.layout == "BALANCED":
        from .uv_stripe_balance_core import balanced_extent
        return balanced_extent(strip, strip.ends, strip.rails, strip.balance)[0]
    if not strip.closed and strip.layout == "SHAPE":
        shape = _shape_uv(strip)
        if shape is not None:
            return shape[3]
    if not strip.closed and strip.layout in ("TRUE", "SHAPE"):
        return _true_u(strip)[2]
    return strip_length(strip)


def strip_v_extent(strip: Strip) -> float:
    """The v extent ``stripe_uvs`` lays the strip out over: under "SHAPE" (an open strip) the largest real
    distance of the far row from the near row, under "BALANCED" (an open strip) its balanced height, else
    ``strip.height``."""
    if not strip.closed and strip.layout == "BALANCED":
        from .uv_stripe_balance_core import balanced_extent
        return balanced_extent(strip, strip.ends, strip.rails, strip.balance)[1]
    if not strip.closed and strip.layout == "SHAPE":
        shape = _shape_uv(strip)
        if shape is not None:
            return shape[4]
    return strip.height


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
    (``_post_u``), with "TRUE" (open strips) at their true lengths (``_true_u``). With "SHAPE"
    (open strips) every vertex takes its place in ``_shape_uv``, the faces unfolded at their
    real shape, rows and ends included, and nothing is relaxed. A closed
    strip's rows are walked from its seam rung (``seam``, else ``sharpest_rung``). An open
    strip's end sides stand at u = 0 and u = L, or under "TRUE" on the line between that
    end's near and far corner; the u extent is ``strip_extent``. Every other vertex is
    relaxed inside (``_tutte``). A repeated near id takes its ``corner_near``
    position at each corner listed there. Raises ValueError for rungs that run backward,
    and for a repeated far id without a ``corner_far`` entry for one of its corners.

    "BALANCED" (open strips) is ``uv_stripe_balance_core.balanced_uvs`` with the strip's
    ``ends``, ``rails`` and ``balance``, and raises as it does.
    """
    if strip.layout == "BALANCED" and not strip.closed:
        from .uv_stripe_balance_core import balanced_uvs
        return balanced_uvs(strip, strip.ends, strip.rails, strip.balance)
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
    shape = _shape_uv(strip) if strip.layout == "SHAPE" and not strip.closed else None
    true = strip.layout in ("TRUE", "SHAPE") and not strip.closed and shape is None
    v_near, v_far = [0.0] * len(near), [strip.height] * len(far)
    if shape is not None:
        near_uv, far_uv, shape_sides, length, _top = shape
        u_near, v_near = [u for u, _v in near_uv], [v for _u, v in near_uv]
        u_far, v_far = [u for u, _v in far_uv], [v for _u, v in far_uv]
    elif true:
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
    if shape is not None:
        side_v.update(shape_sides)
    elif true:
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
                uv[key] = (u_near[i], v_near[i])
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
                uv[key] = (u_far[i], v_far[i])
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


def lay_piece(piece: Strip, layout: str, align: str = "AUTO", align_edges=()) -> dict[tuple[int, int], Vec2]:
    """Set ``piece`` up to be laid out under ``layout`` and return its ``stripe_uvs``.

    "STRAIGHT" goes through ``straighten`` (which keeps "EVEN" where it would fold a
    face); every other layout, "BALANCED" among them, is set as itself. The piece aligns by ``align`` (True
    Shape only), "PICKED" on the first of ``align_edges`` (vertex-id pairs) that is an
    edge of its own faces (``align_edge_in``). Raises ValueError as ``stripe_uvs`` does.
    """
    piece.align = align
    piece.align_edge = align_edge_in(piece, align_edges) if align == "PICKED" else None
    if layout == "STRAIGHT":
        straighten(piece)
    else:
        piece.layout = layout
    return stripe_uvs(piece)


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


def bbox(uv: dict) -> tuple[Vec2, Vec2]:
    """(min corner, max corner) of a placed strip's UVs."""
    us = [p[0] for p in uv.values()]
    vs = [p[1] for p in uv.values()]
    return (min(us), min(vs)), (max(us), max(vs))


STRETCH_TOLERANCE = 1.05   # a face whose UVs stretch it more than 5 % on one axis is "stretched"


def _triangle_metric(p0: Vec3, p1: Vec3, p2: Vec3, q0: Vec2, q1: Vec2, q2: Vec2) -> tuple[float, float, float] | None:
    """Twice the 3D area times the UV-side metric ``J J^T`` of one triangle's 3D -> UV map, as (E, F, G).

    ``J`` maps the triangle laid flat in its own plane onto its UVs; ``J J^T`` lives in UV
    space, so it adds up over the triangles of a face. None for a triangle degenerate in 3D.
    """
    e1 = (p1[0] - p0[0], p1[1] - p0[1], p1[2] - p0[2])
    e2 = (p2[0] - p0[0], p2[1] - p0[1], p2[2] - p0[2])
    x1 = math.sqrt(e1[0] * e1[0] + e1[1] * e1[1] + e1[2] * e1[2])
    l2 = math.sqrt(e2[0] * e2[0] + e2[1] * e2[1] + e2[2] * e2[2])
    if x1 <= 0.0:
        return None
    x2 = (e2[0] * e1[0] + e2[1] * e1[1] + e2[2] * e1[2]) / x1
    k = x2 / x1
    y2 = math.sqrt(sum((e2[i] - k * e1[i]) ** 2 for i in range(3)))
    if x1 * y2 <= 1e-12 * max(x1, l2) ** 2:
        return None
    d1 = (q1[0] - q0[0], q1[1] - q0[1])
    d2 = (q2[0] - q0[0], q2[1] - q0[1])
    a = (d1[0] / x1, d1[1] / x1)
    b = ((d2[0] - x2 * a[0]) / y2, (d2[1] - x2 * a[1]) / y2)
    w = x1 * y2
    return (w * (a[0] * a[0] + b[0] * b[0]), w * (a[0] * a[1] + b[0] * b[1]), w * (a[1] * a[1] + b[1] * b[1]))


def _ratio(e: float, f: float, g: float) -> float:
    """The larger over the smaller singular value of a map with UV-side metric (e, f, g); ``math.inf`` when it
    collapses."""
    r = math.sqrt(((e - g) / 2.0) ** 2 + f * f)
    big = (e + g) / 2.0 + r
    small = (e + g) / 2.0 - r
    if big <= 0.0 or small <= 1e-18 * big:
        return math.inf
    return math.sqrt(big / small)


def face_stretch(points: list[Vec3], uvs: list[Vec2]) -> float:
    """How anisotropically a face's UVs map its real shape: 1.0 is no stretch.

    ``points`` and ``uvs`` are the face's corners in order. Every fan triangle round the
    face's virtual centre (``uv_stripe_faces_core.fan_weights``: a triangle is its own fan,
    a larger face the triangles from the mean of its corners to each of its edges, slivers
    left out) gives the UV-side metric of its 3D -> UV map. The face's stretch is the
    larger of the ratio of the larger to the smaller singular value of their mean
    weighted by 3D area, and that ratio of its worst single triangle, fan or corner
    (``uv_stripe_faces_core.corner_weights``, slivers left out): a uniform scale or a turn
    does not count, the same face measures the same whichever corner comes first, and a
    corner or an edge collapsed in UV is stretch however healthy the rest of the face is
    (a triangle collapsed in UV gives ``math.inf``). A triangle degenerate in 3D is
    skipped; a face with no measurable triangle gives 1.0.
    """
    from .uv_stripe_faces_core import measured_tris

    fan, corners = measured_tris(tuple(tuple(p) for p in points))
    n = len(points)
    pc = tuple(sum(p[i] for p in points) / n for i in range(3))
    qc = (sum(q[0] for q in uvs) / n, sum(q[1] for q in uvs) / n)
    e = f = g = 0.0
    worst = 1.0
    measured = False
    for tris, average in ((fan, True), (corners, False)):
        for a, b, c in tris:
            metric = _triangle_metric(pc if a < 0 else points[a], points[b], points[c],
                                      qc if a < 0 else uvs[a], uvs[b], uvs[c])
            if metric is None:
                continue
            measured = True
            worst = max(worst, _ratio(*metric))
            if average:
                e, f, g = e + metric[0], f + metric[1], g + metric[2]
    if not measured:
        return 1.0
    return max(worst, _ratio(e, f, g) if e + g > 0.0 else 1.0)


def fit_to_reference(uv: dict, reference: tuple[Vec2, Vec2], mode: str = "BOTH") -> dict:
    """A placed strip fitted onto a reference bounding box by one scale factor, never stretched or turned.

    The factor scales both axes about the strip's bounding-box centre: "WIDTH" matches the
    reference's width, "HEIGHT" its height, "BOTH" takes the smaller of the two so the strip
    fits inside the reference box. A strip side of zero size gives no factor ("BOTH" uses the
    other one; with none left the factor is 1). Then the box centre is moved onto the
    reference's. Every piece of a run is laid out by the same Orientation, so it is not turned.
    """
    (u0, v0), (u1, v1) = bbox(uv)
    (r0, s0), (r1, s1) = reference
    tw, th = u1 - u0, v1 - v0
    factors = []
    if mode in {"BOTH", "WIDTH"} and tw > 1e-10:
        factors.append((r1 - r0) / tw)
    if mode in {"BOTH", "HEIGHT"} and th > 1e-10:
        factors.append((s1 - s0) / th)
    scale = min(factors) if factors else 1.0
    cu, cv = (u0 + u1) / 2.0, (v0 + v1) / 2.0
    ru, rv = (r0 + r1) / 2.0, (s0 + s1) / 2.0
    return {key: (ru + (u - cu) * scale, rv + (v - cv) * scale) for key, (u, v) in uv.items()}


def random_offsets(count: int, axis: str, limit: float, seed: int, keep: int | None = None) -> list[Vec2]:
    """One random (du, dv) shift per placed piece, in the pieces' order; the same seed gives the same shifts.

    ``axis`` "NONE", "HORIZONTAL" (u only), "VERTICAL" (v only) or "BOTH". Each shift is
    uniform in [-limit, +limit] on each chosen axis. Every piece draws its pair whatever
    the axis and ``keep``, so a piece's shift does not depend on those; the piece
    ``keep`` (the Active reference) is not moved.
    """
    rng = random.Random(seed)  # noqa: S311 - a seeded layout offset, not security
    out = []
    for i in range(count):
        du, dv = rng.uniform(-limit, limit), rng.uniform(-limit, limit)
        if i == keep or axis == "NONE":
            du = dv = 0.0
        out.append((du if axis in ("HORIZONTAL", "BOTH") else 0.0, dv if axis in ("VERTICAL", "BOTH") else 0.0))
    return out


def shifted(uv: dict, offset: Vec2) -> dict:
    """A placed strip moved by ``offset``."""
    du, dv = offset
    return {k: (u + du, v + dv) for k, (u, v) in uv.items()}


def stack_shifts(boxes: list[tuple[Vec2, Vec2]], point: Vec2 = (0.5, 0.5)) -> list[Vec2]:
    """One (du, dv) per piece that moves its UV bounding box ``((u0, v0), (u1, v1))`` so its centre lands on
    ``point``: the Stack mode puts every piece's centre on the middle of 0-1, the pieces one on top of the other."""
    return [(point[0] - (lo[0] + hi[0]) / 2, point[1] - (lo[1] + hi[1]) / 2) for lo, hi in boxes]
