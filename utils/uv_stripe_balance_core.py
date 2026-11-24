"""UV Stripe's balanced layout of an open strip: one straight strip, the stretch spread out by the Balance slider.

Pure Python (stdlib only), no bpy, so it runs under plain pytest.

Lengthwise the strip is straight: by default (``rails`` "BOTH") the near rail lies
on v = 0, the far rail on one shared v (the height), and every lengthwise line on
one shared v of its own. Edges are classed "along" or "across" by spreading from
the rails (along) and the ends (across) through the faces (``_classes``); the
vertices joined by along edges form a lengthwise line (``_lines``). Across the
width the layout is free: cross edges lean as the faces need, and by default
(``ends`` "FREE") the ends keep their real slant; "BOTH" stands both upright,
"START" or "END" only the end at u = 0 or the other one. Lines picked straight by
hand (``Strip.lines``) share one v (along) or one u (across) in every mode, "NONE"
(no rail straight) included. A vertex lying in line
between two corners of one of its faces (a quad whose side carries an extra
vertex) stays at its place along that side (``_hanging``).

The rigid layout comes first (``prepare``): a rotation is fitted to every face,
then u and v are solved as two linear least-squares systems with those rotations,
again and again until the layout stops moving. Every face weighs alike, whatever
its size or number of corners. That keeps every face near its real size (Balance
1, "Even Texel"). The least-stretch layout (Balance 0) goes on from there and
minimises the measured stretch itself (``least_stretch``): a p-norm of each face's
(k + 1/k) / 2 over its fan metric (``uv_stripe_faces_core``, the one
``uv_stripe_core.face_stretch`` reports), with a small isometric term holding the
size, by L-BFGS preconditioned with the same factored matrices and never turning a
guarded triangle over. A Balance in between slides the unknowns straight from the
rigid layout to the least-stretch one (``solve``), so the slider moves stretch and
texel spread steadily and a wheel step costs no new solve; a descent that cannot
start, or a slid layout that folds a face, falls back to the rigid layout. With one
rail free the layout is never worse than with both rails straight (``_balanced``).
Every piece is prepared once and cached; in the interactive mode a piece whose
descent has not converged shows a capped warm one (``live``) until ``refine`` has
run the cold one in slices.
"""

import math
import time
from contextlib import contextmanager
from dataclasses import dataclass, field, replace

from .uv_stripe_core import CACHES, DEFAULT_BALANCE, TIE_TOL, Strip, Vec2, _angle, face_stretch, stripe_uvs
from .uv_stripe_faces_core import CORNER_MEASURE_ANGLE, corner_weights, face_fans, measured_tris, weighted
from .uv_stripe_faces_core import projected_face as _projected_face
from .uv_stripe_select_core import _surface_angle

BALANCE_ITERS = 300
BALANCE_TOL = 1e-6      # the solve stops when no vertex moves by this fraction of the strip's size
HANGING_ANGLE = math.radians(1.0)    # a face corner within this of straight is a vertex hanging on a side
ENDS = ("FREE", "BOTH", "START", "END")
RAILS = ("BOTH", "NEAR", "FAR", "NONE")
LINE_AXES = ("ALONG", "ACROSS")     # a picked line (``Strip.lines``): one shared v, or one shared u
BALANCE_NAMES = {"EVEN_TEXEL": 1.0, "LEAST_STRETCH": 0.0}   # the old Balance list, read as its slider value
STRETCH_POWER = 4        # the p of the p-norm of the faces' stretch
STRETCH_ITERS = 200      # a cold solve: at most this many descent steps
LIVE_BUDGET = 0.02       # s of least-stretch descent a live (wheel) relayout spends on one piece
STRETCH_SIZE = 0.05      # the least weight of the isometric term that holds the size
STRETCH_REL_TOL = 1e-7   # the descent stops when a step lowers the energy by less than this fraction
LBFGS_MEMORY = 5
GUARD_ANGLE = math.radians(170.0)   # a face corner wider than this is not guarded on its own (its fan is)
_CACHE: dict = {}        # prepared pieces by key (``_cache_key``): a ``Prepared`` or the ValueError it raised
_SOLVED: dict = {}       # cold solutions by (key, balance): a ``Solution`` or the ValueError it raised
_LIVE: dict = {}         # live (warm, capped) solutions by (key, balance)
_PENDING: dict = {}      # (key, balance) -> the cold solve still to run for a live result (a generator or None)
_CACHE_SIZE = 512        # least recently used out: room for every piece of a run, each in a few modes
_live_steps: int | None = None


def balance_value(balance) -> float:
    """``balance`` as a slider value from 0 (Least Stretch) to 1 (Even Texel): a number is clamped to 0..1, an
    old Balance name ("EVEN_TEXEL", "LEAST_STRETCH") reads as 1 or 0. Raises ValueError for anything else."""
    if isinstance(balance, str):
        if balance not in BALANCE_NAMES:
            raise ValueError(f"no balance {balance!r}")
        return BALANCE_NAMES[balance]
    if isinstance(balance, bool) or not isinstance(balance, (int, float)) or balance != balance:
        raise ValueError(f"no balance {balance!r}")
    return min(max(float(balance), 0.0), 1.0)


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
                 balance=DEFAULT_BALANCE) -> dict[tuple[int, int], Vec2]:
    """Map every (face id, vertex id) corner of an open strip to (u, v), laid out balanced (module docstring).

    ``ends``: "FREE" leaves both ends their slant, "BOTH" makes each end share one u,
    "START" only the end laid at u = 0 (``start_end``), "END" only the other one.
    ``rails``: "BOTH" makes the near rail, the far rail and every lengthwise line
    each share one v; "NEAR" or "FAR" keeps only that rail straight, the other rail
    and the lengthwise lines free; "NONE" keeps no rail straight (the strip at its
    real shape, held only by the lines picked on it). Cross lines are free. On top,
    every line picked on the strip (``Strip.lines``) shares one v ("ALONG") or one u
    ("ACROSS"), whatever the modes (``_with_picked``). ``balance`` (0 to 1,
    ``balance_value``) slides from the least stretch (0) to every face near its real size
    (1, the rigid layout itself), for a strip several faces wide only (``is_wide``; one face
    wide it is 1). The layout starts
    from the strip's "EVEN" layout (``uv_stripe_core.stripe_uvs``) and keeps its
    direction: u grows from the end it lays at u = 0 and the near rail stays below
    the far one, never mirrored. It is shifted so its smallest u and v are 0. The
    same strip always gives the same layout (inside ``live`` a capped warm solve may
    stand in until ``refine`` runs the cold one). Raises ValueError for an unknown mode,
    a closed strip, a vertex repeated on its rails or shared by both, ends that
    touch, a system with no single solution, and a result that would fold a face,
    turn the strip round or give it no size.
    """
    return dict(_balanced(strip, ends, rails, balance).uv)


def balanced_extent(strip: Strip, ends: str = "FREE", rails: str = "BOTH",
                    balance=DEFAULT_BALANCE) -> tuple[float, float]:
    """The (u, v) extent ``balanced_uvs`` lays ``strip`` out over: its length and its height. Raises as it does."""
    found = _balanced(strip, ends, rails, balance)
    return found.length, found.height


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
    shape (``_folds``: turned over, flattened to nothing, a reflex corner the real face does not have, a
    fan triangle round the face's centre turned over, or crossing itself), over the faces of ``face_flats``
    (``flats``, computed when None)."""
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


def _cache_key(strip: Strip, ends: str, rails: str):
    used = sorted({v for face in strip.faces.values() for v in face})
    return (ends, rails, tuple(sorted(strip.faces.items())), tuple(strip.near), tuple(strip.far),
            tuple(strip.sides[0]), tuple(strip.sides[1]), tuple((v, tuple(strip.verts[v])) for v in used),
            line_key(strip))


def line_key(strip: Strip) -> tuple:
    """The lines picked on ``strip`` (``Strip.lines``) in a fixed order, for the caches."""
    return tuple(sorted((axis, tuple(sorted(vs))) for axis, vs in strip.lines))


def _remember(cache: dict, key, make):
    """``cache[key]``, made by ``make()`` the first time (a ValueError it raises is kept too); least recently
    used out beyond ``_CACHE_SIZE``. Raises the kept ValueError."""
    if key in cache:
        cache[key] = cache.pop(key)       # used now: to the back of the queue
    else:
        while len(cache) >= _CACHE_SIZE:
            cache.pop(next(iter(cache)))
        try:
            cache[key] = make()
        except ValueError as exc:
            cache[key] = exc        # a failure is kept too: Auto asks again on every relayout
    found = cache[key]
    if isinstance(found, ValueError):
        raise ValueError(str(found))
    return found


@dataclass
class Prepared:
    """What every balance of one piece shares (``prepare``): the strip, its ends at u = 0 and beyond, the two
    factored systems, the rigid layout (positions and unknowns), the least-stretch descent's energy and fold
    guard, why that descent cannot start (None when it can), and its result: the least-stretch unknowns once
    converged (``least``), the unknowns reached so far (``partial``) and the steps taken."""

    strip: Strip
    lo: list
    hi: list
    tiny: float
    used: list
    sys_u: object
    sys_v: object
    rigid: dict
    xu: list
    xv: list
    energy: object = None
    guard: list = field(default_factory=list)
    stuck: str | None = None
    least: tuple | None = None
    partial: tuple | None = None
    steps: int = 0
    stricter: tuple | None = None     # (ends, rails) of the stricter layout this one must never be worse than
    looser: tuple | None = None       # (ends, rails) of the same rails with free ends: a warm start once it is solved
    flats: dict | None = None         # every face a fold can be told on: (flat corners, their turns)


@dataclass
class Solution:
    """One balance of a prepared piece (``solve``): uv by (face id, vertex id) corner, its u and v extent,
    whether the least-stretch end it slides toward had converged, why the layout fell back to the rigid one
    (None when it did not) and the descent steps taken so far."""

    uv: dict
    length: float
    height: float
    converged: bool = True
    fallback: str | None = None
    steps: int = 0


def prepare(strip: Strip, ends: str = "FREE", rails: str = "BOTH") -> Prepared:
    """The part of a balanced layout every balance shares (``Prepared``), cached by the strip's topology,
    positions, ``ends`` and ``rails`` (a failure too). Raises ValueError as ``balanced_uvs`` does."""
    if ends not in ENDS or rails not in RAILS:
        raise ValueError(f"no balanced layout with ends {ends!r} and rails {rails!r}")
    if strip.closed:
        raise ValueError("a closed strip has no balanced layout")
    return _remember(_CACHE, _cache_key(strip, ends, rails), lambda: _prepare(strip, ends, rails))


def _balanced(strip: Strip, ends: str, rails: str, balance=DEFAULT_BALANCE) -> Solution:
    """The solution of ``strip`` at ``balance``; with one rail free (``rails`` "NEAR" or "FAR") the layout with
    both rails straight at the same balance stands in when it stretches its worst face less (it keeps this
    one's constraints, so a freer layout is never the worse one)."""
    if ends not in ENDS or rails not in RAILS:
        raise ValueError(f"no balanced layout with ends {ends!r}, rails {rails!r} and balance {balance!r}")
    try:
        found = _own(strip, ends, rails, balance)
    except ValueError:
        if rails == "BOTH":
            raise
        found = None
    if rails != "BOTH":
        try:
            other = _balanced(strip, ends, "BOTH", balance)
        except ValueError:
            other = None
        if found is None and other is None:
            return _own(strip, ends, rails, balance)        # raises the own reason
        if found is None or other is not None and _worst_uv(strip, other.uv) < _worst_uv(strip, found.uv) - TIE_TOL:
            return replace(other, fallback=found.fallback if found is not None else "it folds a face")
    return found


def _own(strip: Strip, ends: str, rails: str, balance=DEFAULT_BALANCE) -> Solution:
    t = balance_value(balance)
    if ends not in ENDS or rails not in RAILS:
        raise ValueError(f"no balanced layout with ends {ends!r}, rails {rails!r} and balance {balance!r}")
    if strip.closed:
        raise ValueError("a closed strip has no balanced layout")
    key = _cache_key(strip, ends, rails)
    t = round(t, 4)
    prepared = _remember(_CACHE, key, lambda: _prepare(strip, ends, rails))
    cold = (key, t) in _SOLVED or _live_steps is None or t >= 1.0
    if cold or prepared.least is not None or prepared.stuck is not None or prepared.energy is None:
        return _remember(_SOLVED, (key, t), lambda: solve(prepared, t))
    if (key, t) not in _LIVE:
        _advance(key, prepared, _live_steps, LIVE_BUDGET)
        if prepared.least is not None or prepared.stuck is not None:
            return _remember(_SOLVED, (key, t), lambda: solve(prepared, t))
        try:
            _LIVE[(key, t)] = solve(prepared, t, 0)
        except ValueError as exc:
            _LIVE[(key, t)] = exc
    found = _LIVE[(key, t)]
    if isinstance(found, ValueError):
        raise ValueError(str(found))
    return found


def _advance(key, prepared: Prepared, max_steps: int, budget: float) -> None:
    """Go on with the least-stretch descent of ``prepared`` (one generator per piece, kept in ``_PENDING``
    from its first step to its last, so it ends exactly where a plain call ends) by at most ``max_steps``
    steps and about ``budget`` seconds. A descent that ends drops the piece's live layouts."""
    found = _PENDING.get(key)
    if found is None:
        prepared.partial, prepared.steps = None, 0
        found = (prepared, _least_steps(prepared, None))
        _PENDING[key] = found
    job = found[1]
    deadline = time.perf_counter() + budget
    done = False
    try:
        for _ in range(max_steps):
            next(job)
            if time.perf_counter() >= deadline:
                break
    except StopIteration:
        done = True
    except ValueError:
        done = True
    if done or prepared.least is not None:
        _PENDING.pop(key, None)
        for live_key in [k for k in _LIVE if k[0] == key]:
            _LIVE.pop(live_key)


@contextmanager
def live(max_steps: int = STRETCH_ITERS):
    """While inside, a piece whose least-stretch end has not converged yet goes on toward it for at most
    ``max_steps`` steps and ``LIVE_BUDGET`` seconds (a small piece gets there at once: no jump later) and is
    laid out from where it got to; ``refine`` runs the same descent on to its end. A layout asked for again
    before then is the same one."""
    global _live_steps
    before = _live_steps
    _live_steps = max_steps
    try:
        yield
    finally:
        _live_steps = before


def pending() -> int:
    """How many pieces ``refine`` has still to bring to their least-stretch end."""
    return len(_PENDING)


def refine(budget: float = math.inf) -> bool:
    """Run the queued least-stretch descents (``live``) on for about ``budget`` seconds a call: each is the
    one generator its piece started with, so it ends exactly where a plain call ends. A piece whose descent
    ends drops its live layouts, so asking again gives the cold, final ones. Returns True when none is
    left."""
    deadline = time.perf_counter() + budget
    while _PENDING:
        key, (prepared, _job) = next(iter(_PENDING.items()))
        _advance(key, prepared, STRETCH_ITERS + 1, max(deadline - time.perf_counter(), 0.0))
        if time.perf_counter() >= deadline:
            return not _PENDING
    return True


def clear_caches() -> None:
    """Forget every prepared piece and solution, and every result the other UV Stripe cores remember
    (``uv_stripe_core.CACHES``: strip builds, measured candidates); for tests and a new run."""
    for cache in CACHES:
        cache.clear()
    _CACHE.clear()
    _SOLVED.clear()
    _LIVE.clear()
    _PENDING.clear()


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


def _with_picked(strip: Strip, lines: list[set[int]], picked: list[set[int]], fixed: set[int], shared,
                 crossing: list[tuple[int, int]], apart: tuple[set[int], set[int]]) -> list[set[int]]:
    """``lines`` (each to share one coordinate) with the ``picked`` lines added: a picked line that meets lines
    (or other picked lines) joins them into one. A picked line is left out when it would join ``fixed`` and
    ``shared``, or hold a vertex of both sets of ``apart`` (the two rails, or the two ends: no size left), or
    flatten a ``crossing`` edge (both its ends on it, with the rail or end it joins) or a face (all its corners
    on it)."""
    groups = [set(line) for line in lines]
    shared = set(shared)
    for line in picked:
        merged, rest = set(line), []
        for group in groups:
            if group & merged:
                merged |= group
            else:
                rest.append(group)
        on_fixed, on_shared = bool(merged & fixed), bool(merged & shared)
        if on_fixed and on_shared or merged & apart[0] and merged & apart[1]:
            continue
        whole = merged | (fixed if on_fixed else shared if on_shared else set())
        if any(a in whole and b in whole for a, b in crossing):
            continue
        if any(all(v in whole for v in face) for face in strip.faces.values()):
            continue
        groups = rest + [merged]
    return groups


def piece_lines(strip: Strip) -> list[tuple[str, list[tuple[int, int]]]]:
    """The lines of edges an open strip can have straightened (``Strip.lines``): every run of edges of one class
    (``_classes``) joined at their vertices, as (axis, its edges as sorted vertex-id pairs): "ALONG" for the
    lengthwise lines and the rails, "ACROSS" for the lines across the strip and its ends. An edge no face classes
    (a triangle's) is on none. Empty for a closed strip."""
    if strip.closed:
        return []
    ends = ([strip.near[0], *strip.sides[0], strip.far[0]], [strip.near[-1], *strip.sides[1], strip.far[-1]])
    cls = _classes(strip, ends)
    out = []
    for kind, axis in (("along", "ALONG"), ("across", "ACROSS")):
        parent: dict[int, int] = {}
        edges = [e for e, c in sorted(cls.items()) if c == kind]
        for a, b in edges:
            for v in (a, b):
                parent.setdefault(v, v)
            ra, rb = _find(parent, a), _find(parent, b)
            if ra != rb:
                parent[max(ra, rb)] = min(ra, rb)
        runs: dict[int, list] = {}
        for e in edges:
            runs.setdefault(_find(parent, e[0]), []).append(e)
        out += [(axis, runs[root]) for root in sorted(runs)]
    return out


END_LINE_TURN = math.pi - CORNER_MEASURE_ANGLE    # a turn sharper than this (a corner under 150°) breaks an end
NOTCH_TURN = math.radians(15.0)     # a notch in a rail turns both ways by more than this ...
NOTCH_SUM = math.radians(10.0)      # ... its turns add up to less than this ...
NOTCH_SPAN = 6                      # ... over at most this many edges


def _turns_along(strip: Strip, path: list[int]) -> list[float]:
    """The turn within the surface at every vertex of ``path`` (pi minus its in-surface angle,
    ``uv_stripe_select_core._surface_angle``; positive turning toward the strip), 0 at its two ends."""
    out = [0.0] * len(path)
    for i in range(1, len(path) - 1):
        out[i] = math.pi - _surface_angle(strip.verts, strip.faces, path[i])
    return out


def end_line(strip: Strip, path: list[int]) -> list[int]:
    """The end's own line on the end ``path`` (near corner over its sides to far corner): the longest run of it
    by 3D length (the first on a tie) with no inner vertex turning more than ``END_LINE_TURN`` within the surface
    (sharper than 150°, the corners ``uv_stripe_faces_core`` measures as real). An upright end stands only this
    line upright: a chamfer or a rounded corner beside it keeps its own slant. The whole path when it has no such
    corner."""
    if len(path) <= 2:
        return list(path)
    turns = _turns_along(strip, path)
    breaks = [0] + [i for i in range(1, len(path) - 1) if abs(turns[i]) > END_LINE_TURN] + [len(path) - 1]
    best = None
    for a, b in zip(breaks, breaks[1:]):
        run = path[a:b + 1]
        length = sum(math.dist(strip.verts[p], strip.verts[q]) for p, q in zip(run, run[1:]))
        if best is None or length > best[0] * (1.0 + 1e-6):
            best = (length, run)
    return best[1]


def rail_line(strip: Strip, path: list[int]) -> list[int]:
    """The rail ``path`` without its notches: an inner run from vertex a to b (at most ``NOTCH_SPAN`` edges) whose
    in-surface turns hold a left and a right turn sharper than ``NOTCH_TURN``, add up to less than ``NOTCH_SUM``
    and bring b back onto the line the rail came in on at a (within a tenth of the run); the vertices strictly
    between a and b keep their own v when the rail is straight. The whole path when it has no notch."""
    n = len(path)
    if n < 4:
        return list(path)
    verts = strip.verts
    turn = _turns_along(strip, path)
    off = set()
    a = 1
    while a < n - 1:
        found = None
        if abs(turn[a]) > NOTCH_TURN:
            heading = x = y = 0.0
            for b in range(a + 1, min(a + NOTCH_SPAN, n - 2) + 1):
                heading += turn[b - 1]
                step = math.dist(verts[path[b - 1]], verts[path[b]])
                x += step * math.cos(heading)
                y += step * math.sin(heading)
                if b == a + 1:
                    continue
                ts = turn[a:b + 1]
                if abs(sum(ts)) < NOTCH_SUM and max(ts) > NOTCH_TURN and min(ts) < -NOTCH_TURN \
                        and abs(y) < 0.1 * math.hypot(x, y):
                    found = b
                    break
        if found is None:
            a += 1
        else:
            off.update(path[a + 1:found])
            a = found
    return [v for v in path if v not in off]


FLAT_CORNER = math.radians(160.0)   # a face corner sharper than this is a real corner: no picked line runs through it


def pick_allowed(strip: Strip, axis: str, vertices) -> bool:
    """Whether a line picked straight on the open ``strip`` (``Strip.lines``: ``axis``, ``vertices``) can be kept
    without leaving the piece no layout: it holds no vertex of both rails ("ALONG") or both ends ("ACROSS"),
    and with the rail or end it touches it flattens no edge running the other way (both its ends on it), no face
    (all its corners on it) and no real corner of a face (a corner sharper than ``FLAT_CORNER`` with both its
    neighbours on it: the face would be squashed there, infinitely stretched). The refusals of ``_with_picked``
    in every mode, and more."""
    if strip.closed:
        return False
    ends = ([strip.near[0], *strip.sides[0], strip.far[0]], [strip.near[-1], *strip.sides[1], strip.far[-1]])
    line = set(vertices)
    if len(line) < 2:
        return False
    cls = _classes(strip, ends)
    if axis == "ALONG":
        a, b, kind = set(strip.near), set(strip.far), "across"
    else:
        a, b, kind = set(ends[0]), set(ends[1]), "along"
    if line & a and line & b:
        return False
    whole = line | (a if line & a else b if line & b else set())
    if any(c == kind and e[0] in whole and e[1] in whole for e, c in cls.items()):
        return False
    verts = strip.verts
    for face in strip.faces.values():
        n = len(face)
        if all(v in whole for v in face):
            return False
        for k in range(n):
            p, c, q = face[k - 1], face[k], face[(k + 1) % n]
            if p in whole and c in whole and q in whole and len({p, c, q}) == 3 \
                    and _angle(verts[p], verts[c], verts[q]) < FLAT_CORNER:
                return False
    return True


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
        self.ends = [(a, b) for _w, a, b in pairs]
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

    def fit(self, pos: dict[int, Vec2], axis: int) -> list[float]:
        """The unknowns that best reproduce coordinate ``axis`` of the positions ``pos`` (exactly, for positions
        that keep this system's constraints: a stricter layout of the same piece)."""
        return self.solve([pos[a][axis] - pos[b][axis] for a, b in self.ends])


def _prepare(strip: Strip, ends: str, rails: str) -> Prepared:
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
    cls = _classes(strip, (lo, hi))
    in_use = set(used)
    picked = {axis: [set(vs) & in_use for a, vs in strip.lines if a == axis and len(set(vs) & in_use) >= 2]
              for axis in LINE_AXES}
    # a straight rail holds its own line (``rail_line``: a notch keeps its v), an upright end its own (``end_line``:
    # a chamfer or rounded corner beside it keeps its u)
    if rails == "BOTH":
        v_fixed, v_shared, v_lines = set(rail_line(strip, near)), rail_line(strip, far), _lines(strip, cls, edge_count)
    elif rails == "NONE":
        v_fixed, v_shared, v_lines = {lo[0]}, [], []
    else:
        v_fixed, v_shared, v_lines = set(rail_line(strip, near if rails == "NEAR" else far)), [], []
    across = [e for e, c in sorted(cls.items()) if c == "across"]
    along = [e for e, c in sorted(cls.items()) if c == "along"]
    v_exprs = _unknowns(order, v_fixed, v_shared, _with_picked(strip, v_lines, picked["ALONG"], v_fixed, v_shared,
                                                               across, (set(near), set(far))))
    lo_line, hi_line = end_line(strip, lo), end_line(strip, hi)
    if ends == "BOTH":
        u_fixed, u_shared = set(lo_line), list(hi_line)
    elif ends == "START":
        u_fixed, u_shared = set(lo_line), []
    elif ends == "END":
        u_fixed, u_shared = set(hi_line), []
    else:
        u_fixed, u_shared = {lo[0]}, []
    u_exprs = _unknowns(order, u_fixed, u_shared, _with_picked(strip, [], picked["ACROSS"], u_fixed, u_shared, along,
                                                               (set(lo), set(hi))))
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
            faces.append((fid, face, 1.0 / total, local))
    if not faces:
        raise ValueError("a strip with no area has no balanced layout")

    pairs = [(w, a, b) for _fid, _face, w, local in faces for a, b, _dx, _dy in local]
    sys_u, sys_v = _System(u_exprs, pairs), _System(v_exprs, pairs)
    pos, xu, xv = _arap([(face, w, local) for _fid, face, w, local in faces], sys_u, sys_v,
                        {v: start[v] for v in used}, used, BALANCE_TOL * size)
    fids = [fid for fid, *_rest in faces]
    if rails != "BOTH":
        # one rail free: never worse than both rails straight; that layout keeps this one's constraints
        try:
            stricter = prepare(strip, ends, "BOTH")
        except ValueError:
            stricter = None
        if stricter is not None and _worst_at(strip, stricter.rigid) < _worst_at(strip, pos) - TIE_TOL:
            xu, xv = sys_u.fit(stricter.rigid, 0), sys_v.fit(stricter.rigid, 1)
            pos = {v: (sys_u.value(xu, v), sys_v.value(xv, v)) for v in used}
    prepared = Prepared(strip, lo, hi, tiny, used, sys_u, sys_v, pos, xu, xv)
    prepared.flats = {fid: (flat, _turns(flat)) for fid, face in strip.faces.items()
                      if len(set(face)) == len(face) and (flat := _projected_face(verts, face, tiny)) is not None}
    try:
        prepared.energy, prepared.guard = _descent_terms(strip, fids, sys_u, sys_v, xu, xv, tiny)
    except ValueError as exc:
        prepared.stuck = str(exc)
    prepared.stricter = (ends, "BOTH") if rails != "BOTH" else None
    prepared.looser = ("FREE", rails) if ends != "FREE" else None
    return prepared


def _worst_at(strip: Strip, pos: dict[int, Vec2]) -> float:
    """The worst face stretch (``uv_stripe_core.face_stretch``) of ``strip`` with its vertices at ``pos``."""
    return max((face_stretch([strip.verts[v] for v in face], [pos[v] for v in face])
                for face in strip.faces.values()), default=1.0)


def _worst_uv(strip: Strip, uv: dict) -> float:
    return max((face_stretch([strip.verts[v] for v in face], [uv[(fid, v)] for v in face])
                for fid, face in strip.faces.items()), default=1.0)


def solve(prepared: Prepared, balance=DEFAULT_BALANCE, max_steps: int | None = None) -> Solution:
    """``prepared`` laid out at ``balance`` (``balance_value``): the unknowns slid from the rigid layout (1) to
    the least-stretch layout (0, ``least_stretch``) in proportion, x = rigid + (1 - balance) (least - rigid),
    so every face's map moves straight from one to the other and the stretch and the texel spread move with
    the slider. The least-stretch end is brought to convergence first, or with ``max_steps`` only that many
    steps further than it got to before (``Solution.converged`` says which). A least-stretch end that cannot be
    reached, or a slid layout that folds a face, falls back to the rigid layout (``Solution.fallback`` says
    why). Raises ValueError when the rigid layout itself collapses, turns the strip round or folds a face."""
    t = balance_value(balance)
    strip, lo, hi, tiny = prepared.strip, prepared.lo, prepared.hi, prepared.tiny
    if t >= 1.0 or prepared.energy is None and prepared.stuck is None:
        uv, length, height = _finish(strip, prepared.rigid, lo, hi, tiny, prepared.flats)
        return Solution(uv, length, height)
    reason = prepared.stuck
    if reason is None:
        try:
            for _step in _least_steps(prepared, max_steps):
                pass
        except ValueError as exc:
            reason = str(exc)
    if reason is None:
        su, sv = prepared.least or prepared.partial
        k = 1.0 - t
        xu = [a + k * (b - a) for a, b in zip(prepared.xu, su)]
        xv = [a + k * (b - a) for a, b in zip(prepared.xv, sv)]
        pos = {v: (prepared.sys_u.value(xu, v), prepared.sys_v.value(xv, v)) for v in prepared.used}
        try:
            uv, length, height = _finish(strip, pos, lo, hi, tiny, prepared.flats)
            return Solution(uv, length, height, prepared.least is not None, None, prepared.steps)
        except ValueError as exc:
            reason = str(exc)
    uv, length, height = _finish(strip, prepared.rigid, lo, hi, tiny, prepared.flats)
    return Solution(uv, length, height, True, reason, prepared.steps)


def least_stretch(prepared: Prepared) -> tuple:
    """The least-stretch unknowns (u, v) of ``prepared``, brought to convergence. Raises ValueError when the
    descent cannot start (``Prepared.stuck``)."""
    if prepared.stuck is not None:
        raise ValueError(prepared.stuck)
    for _step in _least_steps(prepared, None):
        pass
    return prepared.least


def _least_start(prepared: Prepared) -> tuple:
    """Where the least-stretch descent of ``prepared`` starts: its rigid unknowns, or the least-stretch result of
    the stricter layout (``Prepared.stricter``: both rails) or of the looser one (``Prepared.looser``: free ends,
    so an upright solve starts from the free one), fitted to this one's unknowns, whichever has the lowest energy
    and turns no guarded triangle over. A cold solve brings them to convergence first; a live one takes them only
    when they have converged already."""
    start = (prepared.xu, prepared.xv)
    best = prepared.energy.evaluate(*start)[0]
    for modes in (prepared.stricter, prepared.looser):
        if modes is None:
            continue
        try:
            other = prepare(prepared.strip, *modes)
            if _live_steps is None:
                least_stretch(other)
        except ValueError:
            continue
        if other.least is None:
            continue
        su, sv = other.least
        pos = {v: (other.sys_u.value(su, v), other.sys_v.value(sv, v)) for v in other.used}
        fu, fv = prepared.sys_u.fit(pos, 0), prepared.sys_v.fit(pos, 1)
        if not all(j[0][0] * j[1][1] - j[0][1] * j[1][0] > 0.0 for j in _jacobians(prepared.guard, fu, fv)):
            continue
        energy = prepared.energy.evaluate(fu, fv)[0]
        if energy < best:
            start, best = (fu, fv), energy
    return start


def _least_steps(prepared: Prepared, max_steps: int | None):
    """The least-stretch descent of ``prepared`` from where it got to (``partial``, else the rigid unknowns),
    at most ``max_steps`` steps more (``STRETCH_ITERS`` in all when None); a generator yielding after every
    step. Sets ``partial``, ``steps`` and, once it converges or runs out of steps, ``least``. Raises
    ValueError when it cannot start."""
    if prepared.least is not None:
        return
    if prepared.stuck is not None:
        raise ValueError(prepared.stuck)
    xu, xv = prepared.partial or _least_start(prepared)
    left = STRETCH_ITERS - prepared.steps
    cap = left if max_steps is None else min(left, max_steps)
    descent = _descend(prepared, xu, xv, cap)
    try:
        while True:
            prepared.partial = next(descent)
            prepared.steps += 1
            yield
    except StopIteration as stop:
        xu, xv, done = stop.value
    except ValueError as exc:
        prepared.stuck = str(exc)
        raise
    prepared.partial = (xu, xv)
    if done or prepared.steps >= STRETCH_ITERS:
        prepared.least = (xu, xv)


def _finish(strip: Strip, pos: dict[int, Vec2], lo: list[int], hi: list[int], tiny: float, flats=None):
    """The solved positions shifted to start at (0, 0), checked: (uv by corner, length, height). Raises
    ValueError when the layout collapses, turns the strip round or folds a face (over ``flats``,
    ``face_flats``: computed when None)."""
    near, far, verts = strip.near, strip.far, strip.verts
    low_u = min(p[0] for p in pos.values())
    low_v = min(p[1] for p in pos.values())
    pos = {v: (p[0] - low_u, p[1] - low_v) for v, p in pos.items()}
    length = max(p[0] for p in pos.values())
    height = max(p[1] for p in pos.values())
    mean = [sum(pos[v][1] for v in row) / len(row) for row in (near, far)]
    if length <= tiny or height <= tiny or pos[hi[0]][0] <= pos[lo[0]][0] or mean[1] <= mean[0]:
        raise ValueError("the balanced layout collapses or turns the strip")
    if flats is None:
        flats = {fid: (flat, None) for fid, face in strip.faces.items()
                 if len(set(face)) == len(face) and (flat := _projected_face(verts, face, tiny)) is not None}
    for fid, (flat, turns) in flats.items():
        if _folds([pos[v] for v in strip.faces[fid]], flat, turns):
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


def _signed_area(pts) -> float:
    return 0.5 * sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(pts, pts[1:] + pts[:1]))


def _folds(uv: list[Vec2], flat: list[Vec2], flat_turns: list[float] | None = None) -> bool:
    """Whether a face's UV polygon folds against its own flat shape (counter-clockwise for its winding): it
    winds the other way or encloses nothing, turns back at a corner where the flat face turns forward (a
    reflex corner the real face does not have), turns over a fan triangle round its centre that the flat face
    has the right way round (``uv_stripe_faces_core``), collapses a real corner (``corner_weights``: a quad laid
    as a triangle), or crosses itself (a butterfly)."""
    n = len(uv)
    area = 0.5 * sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(uv, uv[1:] + uv[:1]))
    scale = max(math.dist(a, b) for a, b in zip(uv, uv[1:] + uv[:1]))
    if area <= 1e-12 * scale * scale:
        return True
    real_turns = _turns(flat) if flat_turns is None else flat_turns
    if any(real > 1e-6 and laid < -1e-9 for real, laid in zip(real_turns, _turns(uv))):
        return True
    if n > 3:
        fan, corners = measured_tris(tuple((p[0], p[1], 0.0) for p in flat))
        fc = (sum(p[0] for p in flat) / n, sum(p[1] for p in flat) / n)
        uc = (sum(p[0] for p in uv) / n, sum(p[1] for p in uv) / n)
        for a, b, c in fan:
            real = _signed_area([fc if a < 0 else flat[a], flat[b], flat[c]])
            if real > 1e-6 * abs(area) and _signed_area([uc if a < 0 else uv[a], uv[b], uv[c]]) < -1e-9 * scale * scale:
                return True
        for a, b, c in corners:              # a real corner of the face collapsed in UV
            if abs(_signed_area([uv[a], uv[b], uv[c]])) <= 1e-6 * abs(area):
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
    coefficient), ...), constant) of J[r][k], r 0 for u and 1 for v, k the flat axis. ``abc`` holds the
    triangle's three points, each as ((vertex id, weight), ...) (a fan's centre is a mean of corners)."""
    rows = []
    for k in range(2):
        g = (-(minv[0][k] + minv[1][k]), minv[0][k], minv[1][k])
        pair = []
        for exprs in (u_exprs, v_exprs):
            coef: dict[int, float] = {}
            const = 0.0
            for gi, point in zip(g, abc):
                for vid, share in point:
                    cv, kv = exprs[vid]
                    const += gi * share * kv
                    for i, x in cv:
                        coef[i] = coef.get(i, 0.0) + gi * share * x
            pair.append((tuple((i, c) for i, c in coef.items() if abs(c) > 1e-15), const))
        rows.append(pair)
    return _Rows(rows)


class _Rows(list):
    """A triangle's Jacobian rows (``_jacobian_rows``) with each entry also kept as (unknown indices,
    coefficients, constant), so ``_jacobians`` reads them without unpacking pairs."""

    def __init__(self, rows):
        super().__init__(rows)
        self.fast = tuple(tuple((tuple(i for i, _c in coef), tuple(c for _i, c in coef), const)
                                for coef, const in rows[k]) for k in range(2))


def _jacobians(rows_list, xu: list[float], xv: list[float], with_const: bool = True):
    """Every triangle's Jacobian (J[r][k]) at the unknowns ``xu``, ``xv``; without ``with_const`` the change of
    the Jacobians along a step (xu, xv)."""
    out = []
    for rows in rows_list:
        (iu0, cu0, ku0), (iv0, cv0, kv0) = rows.fast[0]
        (iu1, cu1, ku1), (iv1, cv1, kv1) = rows.fast[1]
        if not with_const:
            ku0 = kv0 = ku1 = kv1 = 0.0
        out.append([[ku0 + sum([c * xu[i] for i, c in zip(iu0, cu0)]), ku1 + sum([c * xu[i] for i, c in zip(iu1, cu1)])],
                    [kv0 + sum([c * xv[i] for i, c in zip(iv0, cv0)]), kv1 + sum([c * xv[i] for i, c in zip(iv1, cv1)])]])
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
    """The least-stretch energy over the unknowns: a sum over measured triangles (every fan triangle and every
    real corner triangle of every face, ``uv_stripe_faces_core``, the ones ``uv_stripe_core.face_stretch``
    measures) of weight * ((C / cref) ** p + ``STRETCH_SIZE`` D), C = tr M / (2 sqrt det M) = (k + 1/k) / 2 and D
    the symmetric Dirichlet term of the triangle's own metric M = J J^T. Each triangle is its own term, so no
    triangle can collapse behind healthy neighbours (C and D grow without bound as it does); the weights are
    each triangle's share of its face's measured area, so every face weighs alike."""

    def __init__(self, units, u_count, v_count):
        self.units = units                  # (weight, Jacobian rows) per measured triangle
        self.u_count, self.v_count = u_count, v_count
        self.cref = 1.0

    def metrics(self, xu, xv, js=None):
        if js is None:
            js = _jacobians([rows for _w, rows in self.units], xu, xv)
        return js, [(j[0][0] ** 2 + j[0][1] ** 2, j[0][0] * j[1][0] + j[0][1] * j[1][1], j[1][0] ** 2 + j[1][1] ** 2)
                    for j in js]

    def worst(self, xu, xv) -> float:
        _js, m = self.metrics(xu, xv)
        out = 1.0
        for m00, m01, m11 in m:
            det = m00 * m11 - m01 * m01
            if det <= 0.0:
                return math.inf
            out = max(out, (m00 + m11) / (2.0 * math.sqrt(det)))
        return out

    def evaluate(self, xu, xv, grad=False, js=None):
        """(energy, (u gradient, v gradient) or None); an infinite energy for a triangle that collapses. ``js``:
        the triangles' Jacobians at (``xu``, ``xv``) when known already."""
        js, m = self.metrics(xu, xv, js)
        p, cref, mu = STRETCH_POWER, self.cref, STRETCH_SIZE
        energy = 0.0
        dm = []
        for (w, _rows), (m00, m01, m11) in zip(self.units, m):
            tr, det = m00 + m11, m00 * m11 - m01 * m01
            if det <= 1e-18 * tr * tr:
                return math.inf, None
            sq = math.sqrt(det)
            conf = tr / (2.0 * sq)
            energy += w * ((conf / cref) ** p + mu * (tr + tr / det) / 4.0)
            if grad:
                g = p * (conf / cref) ** (p - 1) / cref
                d15 = det * sq
                c00 = 1.0 / (2.0 * sq) - tr * m11 / (4.0 * d15)
                c11 = 1.0 / (2.0 * sq) - tr * m00 / (4.0 * d15)
                c01 = tr * m01 / (2.0 * d15)
                e00 = (1.0 + (det - tr * m11) / (det * det)) / 4.0
                e11 = (1.0 + (det - tr * m00) / (det * det)) / 4.0
                e01 = tr * 2.0 * m01 / (det * det) / 4.0
                dm.append((w * (g * c00 + mu * e00), w * (g * c01 + mu * e01), w * (g * c11 + mu * e11)))
        if not grad:
            return energy, None
        gu, gv = [0.0] * self.u_count, [0.0] * self.v_count
        for (_w, rows), j, (a00, a01, a11) in zip(self.units, js, dm):
            for k in range(2):
                (cu, _ku), (cv, _kv) = rows[k]
                ju, jv = j[0][k], j[1][k]
                du = 2.0 * a00 * ju + a01 * jv
                dv = 2.0 * a11 * jv + a01 * ju
                for i, c in cu:
                    gu[i] += du * c
                for i, c in cv:
                    gv[i] += dv * c
        return energy, (gu, gv)


def _descent_terms(strip: Strip, fids: list[int], sys_u, sys_v, xu, xv, tiny):
    """(the energy, ``_StretchEnergy``, its cref set from the rigid unknowns ``xu``, ``xv``; the fold guard: the
    Jacobian rows of every fan triangle and every convex face corner) of the faces ``fids``. A measured
    triangle that a straight line lays flat in every layout (three corners on one line) is left out of both.
    Raises ValueError when the descent cannot start: no face to measure, a guarded or measured triangle
    already turned over or collapsed."""
    u_exprs, v_exprs = sys_u.exprs, sys_v.exprs
    verts = strip.verts
    fans = face_fans(verts, {fid: strip.faces[fid] for fid in fids}, tiny)
    units, guard, at = [], [], []

    def flat_by_a_line(ids) -> bool:
        return any(len({exprs[v] for v in ids}) == 1 for exprs in (u_exprs, v_exprs))

    for fid in fids:
        face = strip.faces[fid]
        fan_face = fans.get(fid)
        if fan_face is None:
            continue
        flat = fan_face.flat
        mine = []
        measured = list(fan_face.tris) + corner_weights([verts[v] for v in face])
        first = len(guard)
        for k, tri in enumerate(measured):
            pts = [weighted(flat, w) for w in tri]
            frame = _inverse_frame(*pts)
            if frame is None:
                continue
            points = [tuple((face[i], x) for i, x in w) for w in tri]
            if k >= len(fan_face.tris) and flat_by_a_line([pt[0][0] for pt in points]):
                continue
            rows = _jacobian_rows(points, frame[1], u_exprs, v_exprs)
            mine.append((frame[0], rows))
            guard.append(rows)
        total = sum(a for a, _rows in mine)
        units += [(a / total, rows) for a, rows in mine]
        at += range(first, len(guard))
        n = len(face)
        if len(set(face)) != n:
            continue
        for ia, ib, ic in ([] if n == 3 else [((k - 1) % n, k, (k + 1) % n) for k in range(n)]):
            frame = _inverse_frame(flat[ia], flat[ib], flat[ic])
            if frame is None or _flat_angle(flat[ia], flat[ib], flat[ic]) > GUARD_ANGLE:
                continue                # a reflex corner, or one nearly in line (a straight line may run on through it)
            if flat_by_a_line([face[ia], face[ib], face[ic]]):
                continue                # three corners on one straight line: laid flat by it, whatever the layout
            guard.append(_jacobian_rows([((face[ia], 1.0),), ((face[ib], 1.0),), ((face[ic], 1.0),)], frame[1],
                                        u_exprs, v_exprs))
    if not units:
        raise ValueError("no face to measure")
    energy = _StretchEnergy(units, sys_u.count, sys_v.count)
    energy.at = at                    # each measured triangle's place among the guarded ones
    if any(j[0][0] * j[1][1] - j[0][1] * j[1][0] <= 0.0 for j in _jacobians(guard, xu, xv)):
        raise ValueError("the rigid layout already turns a face over")
    energy.cref = energy.worst(xu, xv)
    if not math.isfinite(energy.cref):
        raise ValueError("the rigid layout collapses a face")
    return energy, guard


def _flat_angle(a: Vec2, b: Vec2, c: Vec2) -> float:
    """The angle at ``b`` between ``b -> a`` and ``b -> c``."""
    ux, uy, vx, vy = a[0] - b[0], a[1] - b[1], c[0] - b[0], c[1] - b[1]
    return math.atan2(abs(ux * vy - uy * vx), ux * vx + uy * vy)


def _precondition(prepared: Prepared, gu, gv):
    """The gradient (``gu``, ``gv``) through the inverse of the rigid layout's factored matrices."""
    sys_u, sys_v = prepared.sys_u, prepared.sys_v
    return _back_solve(sys_u.first, sys_u.lower, gu), _back_solve(sys_v.first, sys_v.lower, gv)


def _dot(a, b) -> float:
    return sum(x * y for x, y in zip(a[0], b[0])) + sum(x * y for x, y in zip(a[1], b[1]))


def _descend(prepared: Prepared, xu, xv, max_steps: int):
    """L-BFGS (memory ``LBFGS_MEMORY``) on the least-stretch energy (``_StretchEnergy``) from the unknowns ``xu``, ``xv``,
    preconditioned with the rigid layout's factored matrices; each step no longer than keeps every guarded
    triangle from turning over and shortened until the energy drops enough (Armijo). A generator: it yields
    after every step and returns (u unknowns, v unknowns, converged). Raises ValueError when it cannot start
    (a collapsed face)."""
    energy = prepared.energy
    guard = prepared.guard
    e, grad = energy.evaluate(xu, xv, grad=True)
    if grad is None or not math.isfinite(e):
        raise ValueError("the start of the descent collapses a face")
    memory: list = []
    for _ in range(max_steps):
        # two-loop recursion, the preconditioner as the initial inverse Hessian
        q = (list(grad[0]), list(grad[1]))
        alphas = []
        for s, y, rho in reversed(memory):
            a = rho * _dot(s, q)
            alphas.append(a)
            q = ([x - a * z for x, z in zip(q[0], y[0])], [x - a * z for x, z in zip(q[1], y[1])])
        r = _precondition(prepared, *q)
        if memory:
            s, y, _rho = memory[-1]
            hy = _precondition(prepared, *y)
            gamma = _dot(s, y) / max(_dot(y, hy), 1e-300)
            r = ([x * gamma for x in r[0]], [x * gamma for x in r[1]])
        for (s, y, rho), a in zip(memory, reversed(alphas)):
            b = rho * _dot(y, r)
            r = ([x + (a - b) * z for x, z in zip(r[0], s[0])], [x + (a - b) * z for x, z in zip(r[1], s[1])])
        du, dv = [-x for x in r[0]], [-x for x in r[1]]
        slope = _dot(grad, (du, dv))
        if slope >= 0.0:
            memory = []
            du, dv = [-x for x in _precondition(prepared, *grad)[0]], [-x for x in _precondition(prepared, *grad)[1]]
            slope = _dot(grad, (du, dv))
            if slope >= 0.0:
                return xu, xv, True
        js = _jacobians(guard, xu, xv)
        djs = _jacobians(guard, du, dv, with_const=False)
        step = min(1.0, 0.8 * _max_step(js, djs))
        accepted = None
        here = [js[i] for i in energy.at]
        along = [djs[i] for i in energy.at]

        def at_step(t):          # the Jacobians are linear in the unknowns: no new expressions to evaluate
            return [[[a[0][0] + t * b[0][0], a[0][1] + t * b[0][1]], [a[1][0] + t * b[1][0], a[1][1] + t * b[1][1]]]
                    for a, b in zip(here, along)]

        for _half in range(50):
            nu = [a + step * b for a, b in zip(xu, du)]
            nv = [a + step * b for a, b in zip(xv, dv)]
            trial = at_step(step)
            en, _g = energy.evaluate(nu, nv, js=trial)
            if en <= e + 1e-4 * step * slope:
                accepted = (nu, nv, en, trial)
                break
            step *= 0.5
        if accepted is None:
            return xu, xv, True
        nu, nv, en, trial = accepted
        rel = (e - en) / max(abs(e), 1e-300)
        en2, g2 = energy.evaluate(nu, nv, grad=True, js=trial)
        if g2 is None:
            return xu, xv, True
        s = ([a - b for a, b in zip(nu, xu)], [a - b for a, b in zip(nv, xv)])
        y = ([a - b for a, b in zip(g2[0], grad[0])], [a - b for a, b in zip(g2[1], grad[1])])
        sy = _dot(s, y)
        if sy > 1e-12 * math.sqrt(_dot(s, s) * _dot(y, y)):
            memory.append((s, y, 1.0 / sy))
            if len(memory) > LBFGS_MEMORY:
                memory.pop(0)
        xu, xv, e, grad = nu, nv, en2, g2
        yield xu, xv
        if rel < STRETCH_REL_TOL:
            return xu, xv, True
    return xu, xv, False
