"""UV Stripe's balanced layout of a strip several faces wide: one straight strip, the stretch spread out.

Pure Python (stdlib only), no bpy, so it runs under plain pytest.

Lengthwise the strip is straight: by default (``rails`` "BOTH") the near rail lies
on v = 0, the far rail on one shared v (the height), and every lengthwise line on
one shared v of its own. Edges are classed "along" or "across" by spreading from
the rails (along) and the ends (across) through the faces (``_classes``); the
vertices joined by along edges form a lengthwise line (``_lines``). Across the
width the layout is free: cross edges lean as the faces need, and by default
(``ends`` "FREE") the ends keep their real slant; "BOTH" stands both upright,
"START" or "END" only the end at u = 0 or the other one. A vertex lying in line
between two corners of one of its faces (a quad whose side carries an extra
vertex) stays at its place along that side (``_hanging``).

The stretch is minimised as rigid as possible (``balanced_uvs``): a rotation is
fitted to every face, then u and v are solved as two linear least-squares systems
with those rotations, again and again until the layout stops moving. Every face
weighs alike, whatever its size or number of corners: triangles, quads and larger
faces count the same. That keeps every face near its real size ("EVEN_TEXEL").
For a strip several faces wide ``balance`` "LEAST_STRETCH" goes on from there and
minimises the measured stretch itself (``_least_stretch``): a p-norm of each face's
(k + 1/k) / 2 over the averaged UV metric ``uv_stripe_core.face_stretch`` uses,
with a small isometric term holding the size, by gradient descent preconditioned
with the same matrices and never flipping a face corner; when that fails or folds
a face the "EVEN_TEXEL" result stands.
"""

import math
from dataclasses import replace

from .uv_stripe_core import TIE_TOL, Strip, Vec2, _angle, stripe_uvs

BALANCE_ITERS = 300
BALANCE_TOL = 1e-6      # the solve stops when no vertex moves by this fraction of the strip's size
HANGING_ANGLE = math.radians(1.0)    # a face corner within this of straight is a vertex hanging on a side
ENDS = ("FREE", "BOTH", "START", "END")
RAILS = ("BOTH", "NEAR", "FAR")
BALANCES = ("EVEN_TEXEL", "LEAST_STRETCH")
STRETCH_POWER = 4        # Least Stretch: the p of the p-norm of the faces' stretch
STRETCH_ITERS = 40       # Least Stretch: at most this many descent steps
STRETCH_SIZE = 0.05      # Least Stretch: the weight of the isometric term that holds the size
STRETCH_REL_TOL = 1e-7   # Least Stretch stops when a step lowers the energy by less than this fraction
_CACHE: dict = {}
_CACHE_SIZE = 512      # least recently used out: room for every piece of a run, each in a few modes


def is_wide(strip: Strip) -> bool:
    """Whether ``strip`` is several faces wide: open, with a vertex on none of its rails and ends.

    A chain one face wide (built from rungs) never has one: every vertex lies on a
    row or an end.
    """
    if strip.closed:
        return False
    rim = set(strip.near) | set(strip.far) | set(strip.sides[0]) | set(strip.sides[1])
    return any(v not in rim for face in strip.faces.values() for v in face)


def balanced_uvs(strip: Strip, ends: str = "FREE", rails: str = "BOTH",
                 balance: str = "EVEN_TEXEL") -> dict[tuple[int, int], Vec2]:
    """Map every (face id, vertex id) corner of an open strip to (u, v), laid out balanced (module docstring).

    ``ends``: "FREE" leaves both ends their slant, "BOTH" makes each end share one u,
    "START" only the end laid at u = 0 (``start_end``), "END" only the other one.
    ``rails``: "BOTH" makes the near rail, the far rail and every lengthwise line
    each share one v; "NEAR" or "FAR" keeps only that rail straight, the other rail
    and the lengthwise lines free. Cross lines are always free. ``balance``
    "EVEN_TEXEL" keeps every face near its real size; "LEAST_STRETCH" minimises the
    measured stretch (module docstring), for a strip several faces wide only (``is_wide``;
    one face wide it is "EVEN_TEXEL"). The layout starts
    from the strip's "EVEN" layout (``uv_stripe_core.stripe_uvs``) and keeps its
    direction: u grows from the end it lays at u = 0 and the near rail stays below
    the far one, never mirrored. It is shifted so its smallest u and v are 0. The
    same strip always gives the same layout. Raises ValueError for an unknown mode,
    a closed strip, a vertex repeated on its rails or shared by both, ends that
    touch, a system with no single solution, and a result that would fold a face,
    turn the strip round or give it no size.
    """
    return dict(_balanced(strip, ends, rails, balance)[0])


def balanced_extent(strip: Strip, ends: str = "FREE", rails: str = "BOTH",
                    balance: str = "EVEN_TEXEL") -> tuple[float, float]:
    """The (u, v) extent ``balanced_uvs`` lays ``strip`` out over: its length and its height. Raises as it does."""
    _uv, length, height = _balanced(strip, ends, rails, balance)
    return length, height


def start_end(strip: Strip) -> int:
    """Which end of an open strip ``balanced_uvs`` lays at u = 0, the "START" end: 0 for the end at
    ``near[0]`` (``[near[0], *sides[0], far[0]]``), 1 for the one at ``near[-1]``. Raises ValueError as
    ``uv_stripe_core.stripe_uvs`` does."""
    _start, lo, _hi = _start_layout(strip)
    return 0 if lo[0] == strip.near[0] else 1


def _start_layout(strip: Strip):
    """(each used vertex's (u, v) in the strip's "EVEN" layout, the end at u = 0, the other end); each end
    runs from its near corner over its side to its far corner."""
    near, far = strip.near, strip.far
    start_uv = stripe_uvs(replace(strip, layout="EVEN"))
    start: dict[int, Vec2] = {}
    for (_fid, vid), p in sorted(start_uv.items()):
        start.setdefault(vid, p)
    end_a = [near[0], *strip.sides[0], far[0]]
    end_b = [near[-1], *strip.sides[1], far[-1]]
    lo, hi = (end_a, end_b) if start[near[0]][0] <= start[near[-1]][0] else (end_b, end_a)
    return start, lo, hi


def face_flats(strip: Strip) -> dict[int, tuple[list[Vec2], list[float]]]:
    """Every face of ``strip`` a fold can be told on, by id: (its corners projected onto its own plane, the turn
    at each of them, ``_turns``). Left out: a face with no area or with a repeated vertex, and one so twisted
    that seen square on it crosses itself (no flat layout keeps its shape). For ``folded_faces``, so the
    layouts of one piece are checked against one projection."""
    xs = [strip.verts[v] for face in strip.faces.values() for v in face]
    size = max((max(p[c] for p in xs) - min(p[c] for p in xs) for c in range(3)), default=0.0)
    tiny = TIE_TOL * max(size, TIE_TOL)
    out = {}
    for fid, face in strip.faces.items():
        if len(set(face)) != len(face):
            continue
        flat = _projected_face(strip.verts, face, tiny)
        if flat is None or _crosses_itself(flat):
            continue
        out[fid] = (flat, _turns(flat))
    return out


def folded_faces(strip: Strip, uv: dict[tuple[int, int], Vec2], flats=None) -> int:
    """How many faces of ``strip`` its layout ``uv`` (by (face id, vertex id) corner) folds against their real
    shape (``_folds``: turned over, flattened to nothing, a reflex corner the real face does not have, or
    crossing itself), over the faces of ``face_flats`` (``flats``, computed when None)."""
    if flats is None:
        flats = face_flats(strip)
    count = 0
    for fid, (flat, turns) in flats.items():
        if _folds([uv[(fid, v)] for v in strip.faces[fid]], flat, turns):
            count += 1
    return count


def _crosses_itself(pts: list[Vec2]) -> bool:
    n = len(pts)
    return any(_crossing(pts[i], pts[(i + 1) % n], pts[j], pts[(j + 1) % n])
               for i in range(n) for j in range(i + 2, n) if not (i == 0 and j == n - 1))


def _cache_key(strip: Strip, ends: str, rails: str, balance: str):
    used = sorted({v for face in strip.faces.values() for v in face})
    return (ends, rails, balance, tuple(sorted(strip.faces.items())), tuple(strip.near), tuple(strip.far),
            tuple(strip.sides[0]), tuple(strip.sides[1]), tuple((v, tuple(strip.verts[v])) for v in used))


def _balanced(strip: Strip, ends: str, rails: str, balance: str = "EVEN_TEXEL"):
    if ends not in ENDS or rails not in RAILS or balance not in BALANCES:
        raise ValueError(f"no balanced layout with ends {ends!r}, rails {rails!r} and balance {balance!r}")
    if strip.closed:
        raise ValueError("a closed strip has no balanced layout")
    if not is_wide(strip):
        balance = "EVEN_TEXEL"       # one face wide, Least Stretch is not used
    key = _cache_key(strip, ends, rails, balance)
    if key in _CACHE:
        _CACHE[key] = _CACHE.pop(key)       # used now: to the back of the queue
    else:
        while len(_CACHE) >= _CACHE_SIZE:
            _CACHE.pop(next(iter(_CACHE)))
        try:
            _CACHE[key] = _solve(strip, ends, rails, balance)
        except ValueError as exc:
            _CACHE[key] = exc        # a failure is kept too: Auto asks again on every relayout
    found = _CACHE[key]
    if isinstance(found, ValueError):
        raise ValueError(str(found))
    return found


def _edge(a: int, b: int) -> tuple[int, int]:
    return (a, b) if a < b else (b, a)


def _face_edges(face: tuple[int, ...]) -> list[tuple[int, int]]:
    return [_edge(face[i], face[(i + 1) % len(face)]) for i in range(len(face))]


def _path_edges(path: list[int]) -> list[tuple[int, int]]:
    return [_edge(a, b) for a, b in zip(path, path[1:]) if a != b]


def _classes(strip: Strip, ends: tuple[list[int], list[int]]) -> dict[tuple[int, int], str]:
    """Every classed edge (a sorted vertex-id pair) as "along" or "across".

    The rails' edges are along and the ends' across. A face passes classes on: a
    quad's opposite edges share one; a face of more than four edges with exactly two
    across edges, not next to each other, makes its other edges along (a quad whose
    rail side carries an extra vertex). The faces are visited in id order until
    nothing changes; the first class an edge gets stays. Triangles pass nothing on.
    """
    cls: dict[tuple[int, int], str] = {}
    for e in _path_edges(strip.near) + _path_edges(strip.far):
        cls.setdefault(e, "along")
    for e in _path_edges(ends[0]) + _path_edges(ends[1]):
        cls.setdefault(e, "across")
    rings = [(fid, _face_edges(strip.faces[fid])) for fid in sorted(strip.faces)]
    changed = True
    while changed:
        changed = False
        for _fid, edges in rings:
            n = len(edges)
            if n == 4:
                for i in range(4):
                    a, b = edges[i], edges[(i + 2) % 4]
                    if a in cls and b not in cls:
                        cls[b] = cls[a]
                        changed = True
            elif n > 4:
                at = [i for i in range(n) if cls.get(edges[i]) == "across"]
                if len(at) == 2 and (at[1] - at[0]) % n not in (1, n - 1):
                    for e in edges:
                        if e not in cls:
                            cls[e] = "along"
                            changed = True
    return cls


def _find(parent: dict[int, int], v: int) -> int:
    while parent[v] != v:
        parent[v] = parent[parent[v]]
        v = parent[v]
    return v


def _lines(strip: Strip, cls: dict[tuple[int, int], str], edge_count: dict[tuple[int, int], int]) -> list[set[int]]:
    """The lengthwise lines: sets of vertices joined by inner along edges, each to share one v.

    A line that touches a rail joins it, and one that touches both is left free. A
    line is also left free when sharing that v would flatten an across edge (both its
    ends on it) or a face (all its corners on it).
    """
    parent: dict[int, int] = {}
    for (a, b), c in sorted(cls.items()):
        if c != "along" or edge_count.get((a, b), 0) != 2:
            continue
        for v in (a, b):
            parent.setdefault(v, v)
        ra, rb = _find(parent, a), _find(parent, b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)
    groups: dict[int, set[int]] = {}
    for v in sorted(parent):
        groups.setdefault(_find(parent, v), set()).add(v)
    near, far = set(strip.near), set(strip.far)
    across = [e for e, c in sorted(cls.items()) if c == "across"]
    out = []
    for root in sorted(groups):
        line = groups[root]
        on_near, on_far = bool(line & near), bool(line & far)
        if on_near and on_far:
            continue
        shared = line | (near if on_near else far if on_far else set())
        if any(a in shared and b in shared for a, b in across):
            continue
        if any(all(v in shared for v in face) for face in strip.faces.values()):
            continue
        out.append(line)
    return out


def _unknowns(order: list[int], fixed: set[int], shared: list[int], lines: list[set[int]]) -> dict[int, tuple]:
    """One coordinate's expression for every vertex of ``order``: ((unknown index, coefficient), ...), constant.

    ``fixed`` sits at 0; ``shared`` (may be empty) shares one unknown; a line touching
    either joins it, any other line shares an unknown of its own; every other vertex
    has its own. Unknowns are numbered in ``order`` (a group where its first vertex
    comes), so the matrix stays narrow.
    """
    group: dict[int, object] = dict.fromkeys(fixed, "fixed")
    group.update(dict.fromkeys(shared, "shared"))
    for k, line in enumerate(lines):
        tag = "fixed" if line & fixed else "shared" if line & set(shared) else ("line", k)
        for v in line:
            group.setdefault(v, tag)
    slot: dict[object, int] = {}
    out: dict[int, tuple] = {}
    for v in order:
        tag = group.setdefault(v, ("vertex", v))
        if tag == "fixed":
            out[v] = ((), 0.0)
            continue
        if tag not in slot:
            slot[tag] = len(slot)
        out[v] = (((slot[tag], 1.0),), 0.0)
    return out


def _hanging(strip: Strip, tiny: float) -> list[tuple[int, int, int, float]]:
    """The vertices hanging on a face's side: (vertex, side start, side end, fraction along the side).

    A face corner within ``HANGING_ANGLE`` of straight lies on a side between the
    nearest corners of that face that are not; its fraction is its distance along
    the side over the side's length. Each vertex takes the first face (by id) that
    has it so; a face with no turn at all, or one that runs through a vertex twice,
    gives none.
    """
    out, seen = [], set()
    verts = strip.verts
    for fid in sorted(strip.faces):
        face = strip.faces[fid]
        n = len(face)
        if len(set(face)) != n:
            continue
        flags = [_angle(verts[face[k - 1]], verts[face[k]], verts[face[(k + 1) % n]]) >= math.pi - HANGING_ANGLE
                 for k in range(n)]
        if all(flags):
            continue
        for k in range(n):
            if not flags[k] or face[k] in seen:
                continue
            a = k
            while flags[a % n]:
                a -= 1
            b = k
            while flags[b % n]:
                b += 1
            path = [face[i % n] for i in range(a, b + 1)]
            arcs = [0.0]
            for p, q in zip(path, path[1:]):
                arcs.append(arcs[-1] + math.dist(verts[p], verts[q]))
            if arcs[-1] <= tiny:
                continue
            seen.add(face[k])
            out.append((face[k], path[0], path[-1], arcs[k - a] / arcs[-1]))
    return out


def _hang(exprs: dict[int, tuple], hanging) -> dict[int, tuple]:
    """``exprs`` with every hanging vertex that has an unknown of its own placed at its fraction between its
    side's ends instead (their expressions resolved first when they hang themselves). A vertex sharing its
    coordinate (a rail, a line, an end) keeps it, and a loop of hanging vertices is left as it is."""
    users: dict[int, int] = {}
    for coef, _c in exprs.values():
        for i, _x in coef:
            users[i] = users.get(i, 0) + 1
    todo = {v: (a, b, t) for v, a, b, t in hanging if len(exprs[v][0]) == 1 and users[exprs[v][0][0][0]] == 1}
    out = dict(exprs)
    while todo:
        ready = [v for v, (a, b, _t) in sorted(todo.items()) if a not in todo and b not in todo]
        if not ready:
            break
        for v in ready:
            a, b, t = todo.pop(v)
            mix: dict[int, float] = {}
            for (coef, _c), share in ((out[a], 1.0 - t), (out[b], t)):
                for i, c in coef:
                    mix[i] = mix.get(i, 0.0) + share * c
            out[v] = (tuple(sorted(mix.items())), (1.0 - t) * out[a][1] + t * out[b][1])
    keep = sorted({i for coef, _c in out.values() for i, _x in coef})
    at = {i: k for k, i in enumerate(keep)}
    return {v: (tuple((at[i], x) for i, x in coef), c) for v, (coef, c) in out.items()}


def _projected_face(verts, face: tuple[int, ...], tiny: float) -> list[Vec2] | None:
    """One face's corners projected onto its own plane (through its centroid, square to its vector area),
    counter-clockwise for its winding; None for a face with no area. A face that is not flat (a rail side
    bowed by an extra vertex) keeps its outline as seen square on, so a vertex nearly in line with its
    neighbours stays in line."""
    pts = [verts[v] for v in face]
    normal = [0.0, 0.0, 0.0]
    for a, b in zip(pts, pts[1:] + pts[:1]):
        normal = [normal[0] + a[1] * b[2] - a[2] * b[1], normal[1] + a[2] * b[0] - a[0] * b[2],
                  normal[2] + a[0] * b[1] - a[1] * b[0]]
    area = math.sqrt(sum(x * x for x in normal))
    if area <= tiny * tiny:
        return None
    n = [x / area for x in normal]
    centre = [sum(p[i] for p in pts) / len(pts) for i in range(3)]
    axis = None
    for a, b in zip(pts, pts[1:] + pts[:1]):
        d = [b[i] - a[i] for i in range(3)]
        d = [d[i] - n[i] * sum(d[j] * n[j] for j in range(3)) for i in range(3)]
        length = math.sqrt(sum(x * x for x in d))
        if length > tiny:
            axis = [x / length for x in d]
            break
    if axis is None:
        return None
    other = [n[1] * axis[2] - n[2] * axis[1], n[2] * axis[0] - n[0] * axis[2], n[0] * axis[1] - n[1] * axis[0]]
    return [(sum((p[i] - centre[i]) * axis[i] for i in range(3)), sum((p[i] - centre[i]) * other[i] for i in range(3)))
            for p in pts]


def _cholesky(rows: list[dict[int, float]]) -> tuple[list[int], list[list[float]]]:
    """The envelope Cholesky factor of a symmetric matrix given by its lower rows ({column: value}, column <=
    row): each row's first column and its entries from there to the diagonal. Raises ValueError when the
    matrix is not positive definite."""
    n = len(rows)
    first = [min(r) if r else i for i, r in enumerate(rows)]
    scale = max((r.get(i, 0.0) for i, r in enumerate(rows)), default=0.0)
    lower: list[list[float]] = []
    for i in range(n):
        fi = first[i]
        li = [0.0] * (i - fi + 1)
        for j in range(fi, i + 1):
            s = rows[i].get(j, 0.0)
            fj = first[j]
            k0 = max(fi, fj)
            if k0 < j:
                lj = lower[j] if j < i else li
                s -= sum(x * y for x, y in zip(li[k0 - fi:j - fi], lj[k0 - fj:j - fj]))
            if j < i:
                li[j - fi] = s / lower[j][-1]
            else:
                if s <= 1e-12 * max(scale, TIE_TOL):
                    raise ValueError("the balanced layout has no single solution")
                li[-1] = math.sqrt(s)
        lower.append(li)
    return first, lower


def _back_solve(first: list[int], lower: list[list[float]], b: list[float]) -> list[float]:
    n = len(b)
    y = list(b)
    for i in range(n):
        fi, li = first[i], lower[i]
        y[i] = (y[i] - sum(x * z for x, z in zip(li[:-1], y[fi:i]))) / li[-1]
    for i in range(n - 1, -1, -1):
        fi, li = first[i], lower[i]
        y[i] /= li[-1]
        xi = y[i]
        for k in range(fi, i):
            y[k] -= li[k - fi] * xi
    return y


class _System:
    """One coordinate's least-squares system: every vertex as a linear expression of the unknowns, and the
    factored normal matrix of the pair terms."""

    def __init__(self, exprs: dict[int, tuple], pairs):
        self.exprs = exprs
        self.count = 1 + max((i for coef, _c in exprs.values() for i, _x in coef), default=-1)
        rows: list[dict[int, float]] = [{} for _ in range(self.count)]
        self.terms = []      # (weight, ((unknown, coefficient), ...), constant) per pair: the pair's a - b
        for w, a, b in pairs:
            coef: dict[int, float] = {}
            for v, sign in ((a, 1.0), (b, -1.0)):
                for i, x in exprs[v][0]:
                    coef[i] = coef.get(i, 0.0) + sign * x
            coef = {k: c for k, c in coef.items() if abs(c) > 1e-15}
            self.terms.append((w, tuple(coef.items()), exprs[a][1] - exprs[b][1]))
            for i, ci in coef.items():
                for j, cj in coef.items():
                    if j <= i:
                        rows[i][j] = rows[i].get(j, 0.0) + w * ci * cj
        self.first, self.lower = _cholesky(rows)

    def solve(self, targets: list[float]) -> list[float]:
        """The unknowns that best give every pair term (a - b) its target, in pair order."""
        b = [0.0] * self.count
        for (w, coef, const), t in zip(self.terms, targets):
            r = t - const
            for i, c in coef:
                b[i] += w * c * r
        return _back_solve(self.first, self.lower, b)

    def value(self, x: list[float], v: int) -> float:
        coef, const = self.exprs[v]
        return const + sum(c * x[i] for i, c in coef)


def _solve(strip: Strip, ends: str, rails: str, balance: str = "EVEN_TEXEL"):
    near, far = strip.near, strip.far
    if len(set(near)) != len(near) or len(set(far)) != len(far) or set(near) & set(far):
        raise ValueError("a strip with a repeated rail vertex has no balanced layout")
    if strip.corner_near or strip.corner_far:
        raise ValueError("a strip with a repeated rail vertex has no balanced layout")
    start, lo, hi = _start_layout(strip)
    if set(lo) & set(hi):
        raise ValueError("a strip whose ends touch has no balanced layout")

    verts = strip.verts
    used = sorted({v for face in strip.faces.values() for v in face})
    size = max(max(abs(start[v][0]) for v in used), max(abs(start[v][1]) for v in used), TIE_TOL)
    tiny = TIE_TOL * size
    edge_count: dict[tuple[int, int], int] = {}
    for face in strip.faces.values():
        for e in _face_edges(face):
            edge_count[e] = edge_count.get(e, 0) + 1
    order = sorted(used, key=lambda v: (start[v][0], start[v][1], v))
    if rails == "BOTH":
        v_exprs = _unknowns(order, set(near), far, _lines(strip, _classes(strip, (lo, hi)), edge_count))
    else:
        v_exprs = _unknowns(order, set(near if rails == "NEAR" else far), [], [])
    if ends == "BOTH":
        u_exprs = _unknowns(order, set(lo), hi, [])
    elif ends == "START":
        u_exprs = _unknowns(order, set(lo), [], [])
    elif ends == "END":
        u_exprs = _unknowns(order, set(hi), [], [])
    else:
        u_exprs = _unknowns(order, {lo[0]}, [], [])
    hanging = _hanging(strip, tiny)
    u_exprs, v_exprs = _hang(u_exprs, hanging), _hang(v_exprs, hanging)

    faces = []
    for fid in sorted(strip.faces):
        face = strip.faces[fid]
        flat = _projected_face(verts, face, tiny)
        if flat is None:
            continue
        local = []
        for i in range(len(face)):
            for j in range(i + 1, len(face)):
                if face[i] != face[j]:
                    local.append((face[i], face[j], flat[i][0] - flat[j][0], flat[i][1] - flat[j][1]))
        total = sum(dx * dx + dy * dy for _a, _b, dx, dy in local)
        if total > tiny * tiny:
            faces.append((face, 1.0 / total, local))
    if not faces:
        raise ValueError("a strip with no area has no balanced layout")

    pairs = [(w, a, b) for _face, w, local in faces for a, b, _dx, _dy in local]
    sys_u, sys_v = _System(u_exprs, pairs), _System(v_exprs, pairs)
    pos, xu, xv = _arap(faces, sys_u, sys_v, {v: start[v] for v in used}, used, BALANCE_TOL * size)
    if balance == "LEAST_STRETCH":
        try:
            least = _least_stretch(verts, faces, sys_u, sys_v, xu, xv, used, tiny)
            return _finish(strip, least, lo, hi, tiny)
        except ValueError:
            pass                     # the failure fallback: the Even Texel layout below
    return _finish(strip, pos, lo, hi, tiny)


def _finish(strip: Strip, pos: dict[int, Vec2], lo: list[int], hi: list[int], tiny: float):
    """The solved positions shifted to start at (0, 0), checked: (uv by corner, length, height). Raises
    ValueError when the layout collapses, turns the strip round or folds a face."""
    near, far, verts = strip.near, strip.far, strip.verts
    low_u = min(p[0] for p in pos.values())
    low_v = min(p[1] for p in pos.values())
    pos = {v: (p[0] - low_u, p[1] - low_v) for v, p in pos.items()}
    length = max(p[0] for p in pos.values())
    height = max(p[1] for p in pos.values())
    mean = [sum(pos[v][1] for v in row) / len(row) for row in (near, far)]
    if length <= tiny or height <= tiny or pos[hi[0]][0] <= pos[lo[0]][0] or mean[1] <= mean[0]:
        raise ValueError("the balanced layout collapses or turns the strip")
    for face in strip.faces.values():
        flat = _projected_face(verts, face, tiny)
        if flat is not None and len(set(face)) == len(face) and _folds([pos[v] for v in face], flat):
            raise ValueError("the balanced layout folds a face")
    uv = {(fid, vid): pos[vid] for fid, face in strip.faces.items() for vid in face}
    return uv, length, height


def _turns(pts: list[Vec2]) -> list[float]:
    """The sine of the turn at every corner of a polygon: positive turning left (counter-clockwise), 0 at a
    corner whose edge has no length."""
    n = len(pts)
    out = []
    for k in range(n):
        a, b, c = pts[k - 1], pts[k], pts[(k + 1) % n]
        e = (b[0] - a[0], b[1] - a[1])
        f = (c[0] - b[0], c[1] - b[1])
        lengths = math.hypot(*e) * math.hypot(*f)
        out.append((e[0] * f[1] - e[1] * f[0]) / lengths if lengths > 0.0 else 0.0)
    return out


def _crossing(p, q, r, s) -> bool:
    """Whether the segments pq and rs cross at a point inside both."""
    def side(a, b, c):
        return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
    d1, d2, d3, d4 = side(p, q, r), side(p, q, s), side(r, s, p), side(r, s, q)
    return d1 * d2 < 0.0 and d3 * d4 < 0.0


def _folds(uv: list[Vec2], flat: list[Vec2], flat_turns: list[float] | None = None) -> bool:
    """Whether a face's UV polygon folds against its own flat shape (counter-clockwise for its winding): it
    winds the other way or encloses nothing, turns back at a corner where the flat face turns forward (a
    reflex corner the real face does not have), or crosses itself (a butterfly)."""
    n = len(uv)
    area = 0.5 * sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(uv, uv[1:] + uv[:1]))
    scale = max(math.dist(a, b) for a, b in zip(uv, uv[1:] + uv[:1]))
    if area <= 1e-12 * scale * scale:
        return True
    real_turns = _turns(flat) if flat_turns is None else flat_turns
    if any(real > 1e-6 and laid < -1e-9 for real, laid in zip(real_turns, _turns(uv))):
        return True
    for i in range(n):
        for j in range(i + 2, n):
            if i == 0 and j == n - 1:
                continue
            if _crossing(uv[i], uv[(i + 1) % n], uv[j], uv[(j + 1) % n]):
                return True
    return False


def _arap(faces, sys_u, sys_v, pos: dict[int, Vec2], used: list[int], tol: float):
    """Local/global iterations from ``pos``: a rotation fitted to every face, then u and v solved with them,
    until no vertex moves by ``tol`` or ``BALANCE_ITERS`` rounds. Returns (positions, u unknowns, v unknowns)."""
    xu: list[float] = [0.0] * sys_u.count
    xv: list[float] = [0.0] * sys_v.count
    for _ in range(BALANCE_ITERS):
        tu, tv = [], []
        for _face, _w, local in faces:
            dot = crs = 0.0
            for a, b, dx, dy in local:
                ex, ey = pos[a][0] - pos[b][0], pos[a][1] - pos[b][1]
                dot += ex * dx + ey * dy
                crs += ey * dx - ex * dy
            norm = math.hypot(dot, crs)
            c, s = (dot / norm, crs / norm) if norm > 0.0 else (1.0, 0.0)
            for _a, _b, dx, dy in local:
                tu.append(c * dx - s * dy)
                tv.append(s * dx + c * dy)
        xu, xv = sys_u.solve(tu), sys_v.solve(tv)
        new = {v: (sys_u.value(xu, v), sys_v.value(xv, v)) for v in used}
        moved = max(max(abs(new[v][0] - pos[v][0]), abs(new[v][1] - pos[v][1])) for v in used)
        pos = new
        if moved < tol:
            break
    return pos, xu, xv


def _inverse_frame(pa: Vec2, pb: Vec2, pc: Vec2):
    """(twice the area, the inverse of the 2 x 2 matrix of the edges a->b, a->c) of a flat triangle, or None
    when it has no area to speak of."""
    m00, m01, m10, m11 = pb[0] - pa[0], pc[0] - pa[0], pb[1] - pa[1], pc[1] - pa[1]
    det = m00 * m11 - m01 * m10
    if det <= 1e-12 * (abs(m00) + abs(m01) + abs(m10) + abs(m11)) ** 2:
        return None
    return det, ((m11 / det, -m01 / det), (-m10 / det, m00 / det))


def _jacobian_rows(abc, minv, u_exprs, v_exprs):
    """A flat triangle's 3D -> UV Jacobian as linear expressions of the unknowns: rows[k][r] is (((unknown,
    coefficient), ...), constant) of J[r][k], r 0 for u and 1 for v, k the flat axis."""
    rows = []
    for k in range(2):
        g = (-(minv[0][k] + minv[1][k]), minv[0][k], minv[1][k])
        pair = []
        for exprs in (u_exprs, v_exprs):
            coef: dict[int, float] = {}
            const = 0.0
            for gi, vid in zip(g, abc):
                cv, kv = exprs[vid]
                const += gi * kv
                for i, x in cv:
                    coef[i] = coef.get(i, 0.0) + gi * x
            pair.append((tuple((i, c) for i, c in coef.items() if abs(c) > 1e-15), const))
        rows.append(pair)
    return rows


def _jacobians(rows_list, xu: list[float], xv: list[float], with_const: bool = True):
    """Every triangle's Jacobian (J[r][k]) at the unknowns ``xu``, ``xv``; without ``with_const`` the change of
    the Jacobians along a step (xu, xv)."""
    out = []
    for rows in rows_list:
        j = [[0.0, 0.0], [0.0, 0.0]]
        for k in range(2):
            for r, x in ((0, xu), (1, xv)):
                coef, const = rows[k][r]
                j[r][k] = (const if with_const else 0.0) + sum(c * x[i] for i, c in coef)
        out.append(j)
    return out


def _max_step(js, djs) -> float:
    """The largest t keeping every triangle's det(J + t dJ) positive (infinite when no triangle turns over)."""
    t = math.inf
    for j, dj in zip(js, djs):
        a = dj[0][0] * dj[1][1] - dj[0][1] * dj[1][0]
        b = j[0][0] * dj[1][1] + dj[0][0] * j[1][1] - j[0][1] * dj[1][0] - dj[0][1] * j[1][0]
        c = j[0][0] * j[1][1] - j[0][1] * j[1][0]
        roots = []
        if abs(a) < 1e-14 * max(abs(b), abs(c), 1e-300):
            if b < 0.0:
                roots.append(-c / b)
        else:
            disc = b * b - 4.0 * a * c
            if disc >= 0.0:
                q = -0.5 * (b + math.copysign(math.sqrt(disc), b))
                for r in (q / a, c / q if q != 0.0 else math.inf):
                    if r > 0.0:
                        roots.append(r)
        if roots:
            t = min(t, min(roots))
    return t


class _StretchEnergy:
    """Least Stretch's energy over the unknowns: sum over the faces of (C / cref) ** p plus ``STRETCH_SIZE``
    times the metric symmetric Dirichlet term, C = tr M / (2 sqrt det M) = (k + 1/k) / 2 of the face's UV
    metric M (its fan triangles from corner 0, weighed by their area, as ``uv_stripe_core.face_stretch``)."""

    def __init__(self, fan, face_count, u_count, v_count):
        self.fan = fan                      # (face index, weight, Jacobian rows) per fan triangle
        self.area = [0.0] * face_count
        for fi, w, _rows in fan:
            self.area[fi] += w
        self.u_count, self.v_count = u_count, v_count
        self.cref = 1.0

    def metrics(self, xu, xv):
        js = _jacobians([rows for _fi, _w, rows in self.fan], xu, xv)
        m = [[0.0, 0.0, 0.0] for _ in self.area]
        for (fi, w, _rows), j in zip(self.fan, js):
            mf = m[fi]
            mf[0] += w * (j[0][0] ** 2 + j[0][1] ** 2)
            mf[1] += w * (j[0][0] * j[1][0] + j[0][1] * j[1][1])
            mf[2] += w * (j[1][0] ** 2 + j[1][1] ** 2)
        return js, m

    def worst(self, xu, xv) -> float:
        _js, m = self.metrics(xu, xv)
        out = 1.0
        for i, (m00, m01, m11) in enumerate(m):
            if self.area[i] <= 0.0:
                continue
            det = m00 * m11 - m01 * m01
            if det <= 0.0:
                return math.inf
            out = max(out, (m00 + m11) / (2.0 * math.sqrt(det)))
        return out

    def evaluate(self, xu, xv, grad=False):
        """(energy, (u gradient, v gradient) or None); an infinite energy for a face whose metric collapses."""
        js, m = self.metrics(xu, xv)
        p, cref, mu = STRETCH_POWER, self.cref, STRETCH_SIZE
        energy = 0.0
        dm = []
        for fi, (m00, m01, m11) in enumerate(m):
            area = self.area[fi]
            if area <= 0.0:
                dm.append((0.0, 0.0, 0.0))
                continue
            tr, det = m00 + m11, m00 * m11 - m01 * m01
            if det <= 1e-18 * tr * tr:
                return math.inf, None
            sq = math.sqrt(det)
            conf = tr / (2.0 * sq)
            energy += (conf / cref) ** p + mu * (tr / area + area * tr / det) / 4.0
            if grad:
                g = p * (conf / cref) ** (p - 1) / cref
                d15 = det * sq
                c00 = 1.0 / (2.0 * sq) - tr * m11 / (4.0 * d15)
                c11 = 1.0 / (2.0 * sq) - tr * m00 / (4.0 * d15)
                c01 = tr * m01 / (2.0 * d15)
                e00 = (1.0 / area + area * (det - tr * m11) / (det * det)) / 4.0
                e11 = (1.0 / area + area * (det - tr * m00) / (det * det)) / 4.0
                e01 = area * tr * 2.0 * m01 / (det * det) / 4.0
                dm.append((g * c00 + mu * e00, g * c01 + mu * e01, g * c11 + mu * e11))
        if not grad:
            return energy, None
        gu, gv = [0.0] * self.u_count, [0.0] * self.v_count
        for (fi, w, rows), j in zip(self.fan, js):
            a00, a01, a11 = dm[fi]
            for k in range(2):
                (cu, _ku), (cv, _kv) = rows[k]
                ju, jv = j[0][k], j[1][k]
                du = w * (2.0 * a00 * ju + a01 * jv)
                dv = w * (2.0 * a11 * jv + a01 * ju)
                for i, c in cu:
                    gu[i] += du * c
                for i, c in cv:
                    gv[i] += dv * c
        return energy, (gu, gv)


def _least_stretch(verts, faces, sys_u, sys_v, xu, xv, used, tiny) -> dict[int, Vec2]:
    """Least Stretch from the Even Texel unknowns ``xu``, ``xv``: ``STRETCH_ITERS`` descent steps at most on
    ``_StretchEnergy`` (p = ``STRETCH_POWER``), each preconditioned with the solve's own factored matrices,
    no longer than keeps every convex face corner from turning over, shortened until the energy drops enough
    (Armijo). Returns the positions; raises ValueError when it cannot start (a corner already turned over, a
    collapsed face)."""
    u_exprs, v_exprs = sys_u.exprs, sys_v.exprs
    fan, corners = [], []
    for fi, (face, _w, _local) in enumerate(faces):
        flat = _projected_face(verts, face, tiny)
        if flat is None:
            continue
        for k in range(1, len(face) - 1):
            frame = _inverse_frame(flat[0], flat[k], flat[k + 1])
            if frame is not None:
                fan.append((fi, frame[0], _jacobian_rows((face[0], face[k], face[k + 1]), frame[1], u_exprs, v_exprs)))
        area = 0.5 * sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(flat, flat[1:] + flat[:1]))
        n = len(face)
        for ia, ib, ic in ([(0, 1, 2)] if n == 3 else [((k - 1) % n, k, (k + 1) % n) for k in range(n)]):
            frame = _inverse_frame(flat[ia], flat[ib], flat[ic])
            if frame is None or frame[0] <= 1e-3 * area:     # a hanging or reflex corner is no triangle of its own
                continue
            corners.append(_jacobian_rows((face[ia], face[ib], face[ic]), frame[1], u_exprs, v_exprs))
    if not fan:
        raise ValueError("no face to measure")
    energy = _StretchEnergy(fan, len(faces), sys_u.count, sys_v.count)
    if any(j[0][0] * j[1][1] - j[0][1] * j[1][0] <= 0.0 for j in _jacobians(corners, xu, xv)):
        raise ValueError("the Even Texel layout already turns a corner over")
    energy.cref = energy.worst(xu, xv)
    if not math.isfinite(energy.cref):
        raise ValueError("the Even Texel layout collapses a face")
    e, grad = energy.evaluate(xu, xv, grad=True)
    if not math.isfinite(e):
        raise ValueError("the Even Texel layout collapses a face")
    t = 1.0
    for _ in range(STRETCH_ITERS):
        du = [-a for a in _back_solve(sys_u.first, sys_u.lower, grad[0])]
        dv = [-a for a in _back_solve(sys_v.first, sys_v.lower, grad[1])]
        slope = sum(a * b for a, b in zip(grad[0], du)) + sum(a * b for a, b in zip(grad[1], dv))
        if slope >= 0.0:
            break
        js = _jacobians(corners, xu, xv)
        djs = _jacobians(corners, du, dv, with_const=False)
        t = min(2.0 * t, 0.8 * _max_step(js, djs))
        accepted = None
        for _half in range(50):
            nu = [a + t * b for a, b in zip(xu, du)]
            nv = [a + t * b for a, b in zip(xv, dv)]
            en, _g = energy.evaluate(nu, nv)
            if en <= e + 1e-4 * t * slope:
                accepted = (nu, nv, en)
                break
            t *= 0.5
        if accepted is None:
            break
        nu, nv, en = accepted
        rel = (e - en) / max(abs(e), 1e-300)
        xu, xv = nu, nv
        e, grad = energy.evaluate(xu, xv, grad=True)
        if grad is None or rel < STRETCH_REL_TOL:
            break
    return {v: (sys_u.value(xu, v), sys_v.value(xv, v)) for v in used}
