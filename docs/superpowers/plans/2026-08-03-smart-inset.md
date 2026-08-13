# Smart Inset Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Modal operator `iops.mesh_smart_inset` — an inset that stays correct at any thickness: walls that would self-intersect merge into clean medial-axis seams (collapse-merge), with a clamp toggle, region/individual modes, depth, and naive outset.

**Architecture:** A pure-Python 2D wavefront/straight-skeleton core (`utils/smart_inset_core.py`, no bpy — priority-queue event simulation computed once, then `playback(t)` per mouse tick) + a bmesh bridge and modal operator (`operators/mesh_smart_inset.py`) following the `mesh_straight_bevel.py` patterns (HUD overlays, numeric input, redo-panel `execute()`).

**Tech Stack:** Blender 4.x Python API (bpy, bmesh, mathutils, gpu), pure stdlib core (math, heapq), pytest for core tests, blender-mcp for integration smoke.

**Spec:** `docs/superpowers/specs/2026-08-03-smart-inset-design.md` — read it before starting any task.

## Global Constraints

- Core module `utils/smart_inset_core.py` imports **stdlib only** (math, heapq, itertools) — it must run under plain pytest without Blender (see `tests/conftest.py` for how the repo keeps bpy out of test collection).
- Core tests live flat in `tests/` (repo convention: `tests/test_smart_inset_core.py`, imported as `from utils.smart_inset_core import ...`).
- Operator follows `operators/mesh_straight_bevel.py` conventions exactly: `_purge_handles`/`safe_handler_add`, `HUDOverlay`/`HelpOverlay` from `..ui.hud`, `capture_event`, `DIGIT_TYPES` numeric parser, `bl_options = {"REGISTER", "UNDO"}`, property-driven `execute()`.
- Code and comments in English. Commit messages: conventional commits, one solid commit per task, on `master`, never push.
- Run core tests with: `python -m pytest tests/test_smart_inset_core.py -v` from repo root.
- Coordinate convention in core: outer boundary loops are CCW, hole loops are CW; inward normal of edge `a→b` is `(-(b-a).y, (b-a).x)` normalized (left of direction).

## File Structure

- `utils/smart_inset_core.py` — **create.** All skeleton math. Public API: `build_timeline(loops, weights=None) -> Timeline`; `Timeline.first_event_t`, `Timeline.max_t`, `Timeline.front_at(t)`, `Timeline.pos_at(vid, t)`, `Timeline.walls_at(t)`, `Timeline.nodes`.
- `operators/mesh_smart_inset.py` — **create.** Region extraction from bmesh, 2D projection, applying core output to bmesh, the modal operator + HUD + preview + `execute()`.
- `tests/test_smart_inset_core.py` — **create.** Pure pytest suite for the core.
- `__init__.py` — **modify.** Import + register `IOPS_OT_smart_inset` (same pattern as `IOPS_OT_straight_bevel` at `__init__.py:252` and in the classes list at `__init__.py:524`).
- `docs/operators/op_mesh_smart_inset.md` — **create.** User docs (pattern: `docs/operators/op_mesh_cursor_bisect.md`).

---

### Task 1: Core scaffolding — 2D primitives and weighted vertex velocity

**Files:**
- Create: `utils/smart_inset_core.py`
- Test: `tests/test_smart_inset_core.py`

**Interfaces:**
- Produces: `EPS`, `V2` helpers (`sub, add, mul, dot, cross, norm, normalize`), `edge_normal(a, b)`, `vertex_velocity(n_prev, n_next, w_prev, w_next) -> (vx, vy)`.
- The velocity contract used by every later task: a vertex moving with velocity `V` keeps perpendicular distance `w_i * t` from each incident edge line `i`. Solved from the 2×2 system `n_prev·V = w_prev`, `n_next·V = w_next`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_smart_inset_core.py
import math
import pytest

from utils.smart_inset_core import (
    edge_normal, vertex_velocity, EPS,
)


def test_edge_normal_points_left_of_direction():
    # edge along +X, CCW outer loop -> inward normal is +Y
    n = edge_normal((0.0, 0.0), (2.0, 0.0))
    assert n == pytest.approx((0.0, 1.0))


def test_velocity_straight_vertex():
    # collinear edges: velocity equals the shared inward normal
    n = (0.0, 1.0)
    v = vertex_velocity(n, n, 1.0, 1.0)
    assert v == pytest.approx((0.0, 1.0))


def test_velocity_right_angle():
    # square corner at origin: edges +X then +Y, normals (0,1) and (-1,0)
    v = vertex_velocity((0.0, 1.0), (-1.0, 0.0), 1.0, 1.0)
    assert v == pytest.approx((-1.0, 1.0))
    assert math.hypot(*v) == pytest.approx(math.sqrt(2.0))


def test_velocity_reflex_vertex():
    # reflex corner (270 deg interior): normals (0,1) and (1,0)
    # velocity must satisfy both plane constraints
    v = vertex_velocity((0.0, 1.0), (1.0, 0.0), 1.0, 1.0)
    assert v[0] == pytest.approx(1.0)
    assert v[1] == pytest.approx(1.0)


def test_velocity_zero_weight_slides_along_fixed_edge():
    # prev edge weight 0 (open border, use_boundary off):
    # vertex must stay ON the prev edge line while offsetting from next
    n_prev, n_next = (0.0, 1.0), (-1.0, 0.0)
    v = vertex_velocity(n_prev, n_next, 0.0, 1.0)
    assert v == pytest.approx((-1.0, 0.0))  # slides along the fixed edge


def test_velocity_spike_is_capped():
    # near-opposite normals (theta -> 0 spike): finite result, no NaN/inf
    v = vertex_velocity((0.0, 1.0), (1e-12, -1.0), 1.0, 1.0)
    assert all(math.isfinite(c) for c in v)
    assert math.hypot(*v) <= 1e6  # SPEED_CAP
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_smart_inset_core.py -v`
Expected: FAIL — `ModuleNotFoundError: utils.smart_inset_core`.

- [ ] **Step 3: Implement**

```python
# utils/smart_inset_core.py
"""Pure-Python 2D wavefront (simplified straight skeleton) for Smart Inset.

No bpy imports — unit-testable with plain pytest. Outer loops CCW,
holes CW; inward edge normal is the left normal of the edge direction.
A wavefront vertex with velocity V keeps perpendicular distance w_i*t
from each incident edge line i (weighted even offset).
"""
import math
import heapq

EPS = 1e-9
SPEED_CAP = 1e6


def sub(a, b):
    return (a[0] - b[0], a[1] - b[1])


def add(a, b):
    return (a[0] + b[0], a[1] + b[1])


def mul(a, s):
    return (a[0] * s, a[1] * s)


def dot(a, b):
    return a[0] * b[0] + a[1] * b[1]


def cross(a, b):
    return a[0] * b[1] - a[1] * b[0]


def norm(a):
    return math.hypot(a[0], a[1])


def normalize(a):
    l = norm(a)
    if l < EPS:
        return (0.0, 0.0)
    return (a[0] / l, a[1] / l)


def edge_normal(a, b):
    """Inward (left) normal of edge a->b for a CCW loop."""
    d = normalize(sub(b, a))
    return (-d[1], d[0])


def vertex_velocity(n_prev, n_next, w_prev=1.0, w_next=1.0):
    """Solve n_prev.V = w_prev, n_next.V = w_next (2x2 linear system).

    Degenerate cases:
    - collinear same-direction normals (straight vertex): V = n * w
    - near-opposite normals (spike): bisector direction capped at SPEED_CAP
    """
    det = cross(n_prev, n_next)
    if abs(det) < EPS:
        if dot(n_prev, n_next) > 0.0:
            # straight vertex — average weights on the shared normal
            return mul(n_prev, 0.5 * (w_prev + w_next))
        # spike: bisector is ill-defined; move along the (near-)shared
        # tangent capped hard so event math stays finite
        b = normalize(add(n_prev, n_next))
        if norm(b) < EPS:
            b = normalize((-n_prev[1], n_prev[0]))
        return mul(b, SPEED_CAP)
    vx = (w_prev * n_next[1] - w_next * n_prev[1]) / det
    vy = (w_next * n_prev[0] - w_prev * n_next[0]) / det
    v = (vx, vy)
    if norm(v) > SPEED_CAP:
        v = mul(normalize(v), SPEED_CAP)
    return v
```

- [ ] **Step 4: Run tests, verify pass**

Run: `python -m pytest tests/test_smart_inset_core.py -v` — all 6 PASS.

- [ ] **Step 5: Commit**

```bash
git add utils/smart_inset_core.py tests/test_smart_inset_core.py
git commit -m "feat(smart-inset): core 2D primitives and weighted vertex velocity"
```

---

### Task 2: LAV + edge-collapse event timeline (convex loops)

**Files:**
- Modify: `utils/smart_inset_core.py`
- Test: `tests/test_smart_inset_core.py`

**Interfaces:**
- Produces:
  - `class FrontVert`: fields `vid:int, P0:(x,y), V:(x,y), birth_t:float, death_t:float(inf while alive), left_edge:int, right_edge:int, prev:int, next:int, succ_next:int|None, succ_prev:int|None`. `P0` is position at `birth_t`; position at time t is `P0 + V*(t-birth_t)`.
  - `class Node`: fields `t:float, pos:(x,y), edges:set[int]` — skeleton node born at an event; `edges` = original boundary edge ids whose walls touch this node.
  - `class Timeline`: fields `verts: dict[int, FrontVert]`, `nodes: list[Node]`, `loops0: list[list[int]]` (initial loop vert ids), `orig_pos: dict[int,(x,y)]`, `edge_count:int`, `first_event_t: float`, `max_t: float`.
  - `build_timeline(loops: list[list[(x,y)]], weights: list[list[float]]|None) -> Timeline`. Vertex ids are assigned in input order across loops; boundary edge `j` goes from global vert `j` to its loop-successor; `weights[l][i]` is the weight of the edge leaving loop-l vertex i (default 1.0).
- Event semantics this task: **edge collapse only** (adjacent front verts meet). A loop shrinking to 2 verts dies entirely (both remaining edges collapse into one node). Split events come in Task 4.

- [ ] **Step 1: Write the failing tests**

```python
# append to tests/test_smart_inset_core.py
from utils.smart_inset_core import build_timeline


SQUARE = [[(0.0, 0.0), (2.0, 0.0), (2.0, 2.0), (0.0, 2.0)]]
RECT41 = [[(0.0, 0.0), (4.0, 0.0), (4.0, 1.0), (0.0, 1.0)]]


def test_square_collapses_to_point_at_half_width():
    tl = build_timeline(SQUARE)
    assert tl.max_t == pytest.approx(1.0)
    assert tl.first_event_t == pytest.approx(1.0)
    # all four walls meet in one node at the center
    center_nodes = [n for n in tl.nodes if n.pos == pytest.approx((1.0, 1.0))]
    assert center_nodes, "expected a skeleton node at the square center"


def test_rect_collapses_to_medial_segment():
    tl = build_timeline(RECT41)
    assert tl.first_event_t == pytest.approx(0.5)
    assert tl.max_t == pytest.approx(0.5)
    node_pos = sorted(tuple(round(c, 6) for c in n.pos) for n in tl.nodes)
    assert (0.5, 0.5) in node_pos
    assert (3.5, 0.5) in node_pos


def test_vertex_positions_linear_before_first_event():
    tl = build_timeline(SQUARE)
    v = tl.verts[0]  # corner (0,0), velocity (1,1)
    t = 0.25
    pos = (v.P0[0] + v.V[0] * t, v.P0[1] + v.V[1] * t)
    assert pos == pytest.approx((0.25, 0.25))
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_smart_inset_core.py -v`
Expected: new tests FAIL with `ImportError: build_timeline`.

- [ ] **Step 3: Implement**

Append to `utils/smart_inset_core.py`:

```python
INF = float("inf")


class FrontVert:
    __slots__ = ("vid", "P0", "V", "birth_t", "death_t",
                 "left_edge", "right_edge", "prev", "next",
                 "succ_next", "succ_prev", "reflex")

    def __init__(self, vid, P0, V, birth_t, left_edge, right_edge):
        self.vid = vid
        self.P0 = P0
        self.V = V
        self.birth_t = birth_t
        self.death_t = INF
        self.left_edge = left_edge    # original edge id ending at this vert
        self.right_edge = right_edge  # original edge id starting here
        self.prev = -1
        self.next = -1
        self.succ_next = None  # vid replacing self as `next` of self.prev
        self.succ_prev = None  # vid replacing self as `prev` of self.next
        self.reflex = False

    def pos(self, t):
        dt = t - self.birth_t
        return (self.P0[0] + self.V[0] * dt, self.P0[1] + self.V[1] * dt)


class Node:
    __slots__ = ("t", "pos", "edges")

    def __init__(self, t, pos, edges):
        self.t = t
        self.pos = pos
        self.edges = set(edges)


class Timeline:
    def __init__(self):
        self.verts = {}
        self.nodes = []
        self.loops0 = []
        self.orig_pos = {}
        self.orig_edges = {}   # edge id -> (a_vid, b_vid) original endpoints
        self.edge_weight = {}
        self.edge_count = 0
        self.first_event_t = INF
        self.max_t = 0.0


def _edge_collapse_time(A, B):
    """Earliest approach time of two front verts; None if they never meet."""
    t0 = max(A.birth_t, B.birth_t)
    pa, pb = A.pos(t0), B.pos(t0)
    dp = sub(pb, pa)
    dv = sub(B.V, A.V)
    dv2 = dot(dv, dv)
    if dv2 < EPS:
        return None
    t = t0 - dot(dp, dv) / dv2
    if t < t0 - EPS:
        return None
    # verify they actually meet (relative tolerance vs distance travelled)
    pa2, pb2 = A.pos(t), B.pos(t)
    scale = max(norm(dp), 1.0)
    if norm(sub(pb2, pa2)) > 1e-5 * scale:
        return None
    return max(t, t0)


def build_timeline(loops, weights=None):
    tl = Timeline()
    # -- build initial LAV(s) -------------------------------------------
    vid = 0
    eid = 0
    for li, loop in enumerate(loops):
        n = len(loop)
        ids = list(range(vid, vid + n))
        tl.loops0.append(ids)
        for i in range(n):
            a, b = loop[i], loop[(i + 1) % n]
            w = 1.0 if weights is None else weights[li][i]
            tl.edge_weight[eid + i] = w
            tl.orig_edges[eid + i] = (ids[i], ids[(i + 1) % n])
        for i in range(n):
            p = loop[i]
            n_prev = edge_normal(loop[i - 1], p)
            n_next = edge_normal(p, loop[(i + 1) % n])
            w_prev = tl.edge_weight[eid + (i - 1) % n]
            w_next = tl.edge_weight[eid + i]
            v = FrontVert(ids[i], p, vertex_velocity(n_prev, n_next, w_prev, w_next),
                          0.0, eid + (i - 1) % n, eid + i)
            e_in = normalize(sub(p, loop[i - 1]))
            e_out = normalize(sub(loop[(i + 1) % n], p))
            v.reflex = cross(e_in, e_out) < -EPS
            tl.verts[ids[i]] = v
            tl.orig_pos[ids[i]] = p
        for i in range(n):
            tl.verts[ids[i]].prev = ids[(i - 1) % n]
            tl.verts[ids[i]].next = ids[(i + 1) % n]
        vid += n
        eid += n
    tl.edge_count = eid

    # -- event queue -----------------------------------------------------
    heap = []  # (t, seq, kind, payload)
    seq = 0

    def push_collapse(a_vid, b_vid):
        nonlocal seq
        A, B = tl.verts[a_vid], tl.verts[b_vid]
        t = _edge_collapse_time(A, B)
        if t is not None:
            heapq.heappush(heap, (t, seq, "collapse", (a_vid, b_vid)))
            seq += 1

    for v in list(tl.verts.values()):
        push_collapse(v.vid, v.next)

    next_vid = vid
    while heap:
        t, _, kind, payload = heapq.heappop(heap)
        a_vid, b_vid = payload
        A, B = tl.verts[a_vid], tl.verts[b_vid]
        # lazy invalidation: both alive and still adjacent
        if A.death_t != INF or B.death_t != INF or A.next != b_vid:
            continue
        tl.first_event_t = min(tl.first_event_t, t)
        tl.max_t = max(tl.max_t, t)
        pos = mul(add(A.pos(t), B.pos(t)), 0.5)

        if B.next == a_vid:
            # loop down to 2 verts -> whole loop dies into one node
            A.death_t = B.death_t = t
            tl.nodes.append(Node(t, pos, {A.left_edge, A.right_edge,
                                          B.left_edge, B.right_edge}))
            continue

        # merge A,B -> C
        A.death_t = B.death_t = t
        P, N = tl.verts[A.prev], tl.verts[B.next]
        n_prev = edge_normal(tl.orig_pos[tl.orig_edges[A.left_edge][0]],
                             tl.orig_pos[tl.orig_edges[A.left_edge][1]])
        n_next = edge_normal(tl.orig_pos[tl.orig_edges[B.right_edge][0]],
                             tl.orig_pos[tl.orig_edges[B.right_edge][1]])
        V = vertex_velocity(n_prev, n_next,
                            tl.edge_weight[A.left_edge],
                            tl.edge_weight[B.right_edge])
        C = FrontVert(next_vid, pos, V, t, A.left_edge, B.right_edge)
        next_vid += 1
        C.prev, C.next = P.vid, N.vid
        P.next = C.vid
        N.prev = C.vid
        A.succ_next = A.succ_prev = C.vid
        B.succ_next = B.succ_prev = C.vid
        tl.verts[C.vid] = C
        tl.nodes.append(Node(t, pos, {A.left_edge, A.right_edge, B.right_edge}))
        push_collapse(P.vid, C.vid)
        push_collapse(C.vid, N.vid)

    if tl.first_event_t is INF:
        tl.first_event_t = 0.0
    return tl
```

- [ ] **Step 4: Run tests, verify pass**

Run: `python -m pytest tests/test_smart_inset_core.py -v` — all PASS. The square case exercises simultaneous events (4 collapses at t=1.0): the lazy-invalidation loop must survive them (later stale events get skipped because verts already died).

- [ ] **Step 5: Commit**

```bash
git add utils/smart_inset_core.py tests/test_smart_inset_core.py
git commit -m "feat(smart-inset): LAV edge-collapse event timeline"
```

---

### Task 3: Playback — `front_at`, `pos_at`, `walls_at`

**Files:**
- Modify: `utils/smart_inset_core.py`
- Test: `tests/test_smart_inset_core.py`

**Interfaces:**
- Produces (methods on `Timeline`):
  - `front_at(t) -> list[list[int]]` — surviving front loops as ordered vid lists (empty list once everything died at `t >= max_t`).
  - `pos_at(vid, t) -> (x, y)` — position of a front vert clamped to its lifetime (`min(t, death_t)`).
  - `walls_at(t) -> dict[int, list[(x,y)]]` — for every original edge id `j`, the **top chain** of its wall polygon: skeleton nodes with `j in node.edges and node.t <= t` plus live front verts with `j in (v.left_edge, v.right_edge)`, all sorted by projection onto the original edge direction **descending** (so the wall face is `[orig_a, orig_b] + chain` with correct winding). Duplicate positions (within 1e-6 of each other) deduplicated.
- Consumes: Task 2's `FrontVert.succ_next/succ_prev` chains to resolve loop links at time t.

- [ ] **Step 1: Write the failing tests**

```python
# append to tests/test_smart_inset_core.py

def _perp_dist(p, a, b):
    n = edge_normal(a, b)
    return n[0] * (p[0] - a[0]) + n[1] * (p[1] - a[1])


def test_square_front_at_half():
    tl = build_timeline(SQUARE)
    loops = tl.front_at(0.5)
    assert len(loops) == 1 and len(loops[0]) == 4
    for vid in loops[0]:
        p = tl.pos_at(vid, 0.5)
        # even-offset invariant: distance to every original edge >= t,
        # to the two defining edges == t
        d = _perp_dist(p, (0.0, 0.0), (2.0, 0.0))
        assert d >= 0.5 - 1e-6


def test_square_front_empty_after_collapse():
    tl = build_timeline(SQUARE)
    assert tl.front_at(1.5) == []


def test_even_offset_invariant_square():
    tl = build_timeline(SQUARE)
    t = 0.7
    sq = SQUARE[0]
    for vid in tl.front_at(t)[0]:
        p = tl.pos_at(vid, t)
        dists = [_perp_dist(p, sq[i], sq[(i + 1) % 4]) for i in range(4)]
        assert min(dists) == pytest.approx(t, abs=1e-6)


def test_rect_walls_at_full_collapse():
    tl = build_timeline(RECT41)
    walls = tl.walls_at(0.5)
    # bottom edge (id 0, from (0,0) to (4,0)): top chain is the medial
    # segment endpoints, ordered from the b side: (3.5,.5) then (0.5,.5)
    chain = walls[0]
    assert len(chain) == 2
    assert chain[0] == pytest.approx((3.5, 0.5), abs=1e-6)
    assert chain[1] == pytest.approx((0.5, 0.5), abs=1e-6)
    # short left edge (id 3): collapses into a single node
    assert len(walls[3]) == 1
    assert walls[3][0] == pytest.approx((0.5, 0.5), abs=1e-6)


def test_rect_walls_before_any_event_are_offset_edges():
    tl = build_timeline(RECT41)
    walls = tl.walls_at(0.25)
    chain = walls[0]
    assert len(chain) == 2
    assert all(p[1] == pytest.approx(0.25) for p in chain)
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_smart_inset_core.py -v` — FAIL with `AttributeError: front_at`.

- [ ] **Step 3: Implement**

Append methods to `Timeline`:

```python
    # ---- playback ------------------------------------------------------

    def pos_at(self, vid, t):
        v = self.verts[vid]
        return v.pos(min(t, v.death_t))

    def _alive(self, vid, t):
        v = self.verts[vid]
        return v.birth_t <= t < v.death_t

    def _resolve_next(self, vid, t):
        """Follow successor chain until a vert alive at t (or None)."""
        cur = self.verts[vid].next
        guard = 0
        while cur is not None and cur >= 0 and not self._alive(cur, t):
            cur = self.verts[cur].succ_next
            guard += 1
            if guard > len(self.verts):
                return None
        return cur if (cur is not None and cur >= 0) else None

    def front_at(self, t):
        if t >= self.max_t - EPS and self.max_t > 0.0:
            pass  # loops may still be alive if max_t is a partial death
        alive = [vid for vid, v in self.verts.items() if self._alive(vid, t)]
        seen = set()
        loops = []
        for start in alive:
            if start in seen:
                continue
            loop = []
            cur = start
            guard = 0
            while cur is not None and cur not in seen:
                seen.add(cur)
                loop.append(cur)
                cur = self._resolve_next(cur, t)
                guard += 1
                if guard > len(self.verts):
                    break
            if len(loop) >= 3 and cur == start:
                loops.append(loop)
        return loops

    def walls_at(self, t):
        walls = {}
        live_by_edge = {}
        for vid, v in self.verts.items():
            if self._alive(vid, t):
                for e in (v.left_edge, v.right_edge):
                    live_by_edge.setdefault(e, []).append(v.pos(t))
        for j in range(self.edge_count):
            a_vid, b_vid = self.orig_edges[j]
            a, b = self.orig_pos[a_vid], self.orig_pos[b_vid]
            d = normalize(sub(b, a))
            items = list(live_by_edge.get(j, []))
            for node in self.nodes:
                if j in node.edges and node.t <= t + EPS:
                    items.append(node.pos)
            # sort by projection onto edge dir, descending (b-side first)
            items.sort(key=lambda p: -dot(sub(p, a), d))
            chain = []
            for p in items:
                if chain and norm(sub(p, chain[-1])) < 1e-6:
                    continue
                chain.append(p)
            walls[j] = chain
        return walls
```

Note on `walls_at` semantics: a node stays in the chain even after `t` passes it — the wall face grows monotonically. A live vert supersedes a node at the same position via the dedup pass.

- [ ] **Step 4: Run tests, verify pass**

Run: `python -m pytest tests/test_smart_inset_core.py -v` — all PASS.

- [ ] **Step 5: Commit**

```bash
git add utils/smart_inset_core.py tests/test_smart_inset_core.py
git commit -m "feat(smart-inset): timeline playback (front loops, wall chains)"
```

---

### Task 4: Split events (reflex vertices, region splits, holes)

**Files:**
- Modify: `utils/smart_inset_core.py`
- Test: `tests/test_smart_inset_core.py`

**Interfaces:**
- Consumes: Task 2's event loop; extends it with `"split"` events. No public API change — `build_timeline` output simply becomes correct for non-convex input and holes.
- Split semantics: reflex vertex `R` hits the moving front edge descended from original edge `e` at `t = n_e·(R0 - e_a) / (w_e - n_e·V_R)` (denominator must be `> EPS`). At pop time the event is re-validated: the hit point `X = R.pos(t)` must lie within the span of a **live** front edge whose original edge is `e` (checked against that front edge's endpoint positions at `t`, with `1e-6` slack). On apply: `R` dies; two verts `R1` (edges `R.left_edge`, `e`) and `R2` (edges `e`, `R.right_edge`) are born at `X`; the LAV splits into two loops: `R1` links `R.prev … opposite_b_side`, `R2` links `opposite_a_side … R.next`. `R.succ_next = R2`, `R.succ_prev = R1` (so `_resolve_next` from `R.prev` finds `R1`... note: `succ_next` is the replacement seen from `prev`'s side — set `succ_next = R1.vid`? Careful: `_resolve_next(prev)` follows `prev.next -> R -> R.succ_next`; walking CCW from `R.prev` must continue onto `R1`, so `R.succ_next = R1.vid`; walking backwards is unused, keep `succ_prev = R2.vid`). The split vert of the opposite front edge pair: `R1.next` = the b-side front vert of `e`, `R2.prev` = the a-side front vert of `e`.
- Split candidates are computed for every reflex vertex (initial and event-born) against **all** original edges of the same region (all loops — this is what makes holes work), skipping the vertex's own incident edges.

- [ ] **Step 1: Write the failing tests**

```python
# append to tests/test_smart_inset_core.py

LSHAPE = [[(0.0, 0.0), (4.0, 0.0), (4.0, 1.0), (1.0, 1.0),
           (1.0, 3.0), (0.0, 3.0)]]  # CCW, reflex at (1,1)

SQUARE_WITH_HOLE = [
    [(0.0, 0.0), (4.0, 0.0), (4.0, 4.0), (0.0, 4.0)],          # outer CCW
    [(1.5, 1.5), (1.5, 2.5), (2.5, 2.5), (2.5, 1.5)],          # hole CW
]


def test_lshape_splits_into_two_fronts():
    tl = build_timeline(LSHAPE)
    # first events collapse the two 1-wide arms at t=0.5;
    # front at t=0.4 must still be a single loop
    assert len(tl.front_at(0.4)) == 1
    assert tl.max_t == pytest.approx(0.5, abs=1e-6)


def test_star_reflex_survives():
    # 4-point star: reflex verts trigger splits, everything dies eventually
    outer, inner = 2.0, 0.6
    pts = []
    for i in range(8):
        r = outer if i % 2 == 0 else inner
        a = math.pi * i / 4.0
        pts.append((r * math.cos(a), r * math.sin(a)))
    tl = build_timeline([pts])
    assert tl.max_t > 0.0
    assert tl.front_at(tl.max_t + 0.1) == []
    # front just before first event is one loop of 8
    t = tl.first_event_t * 0.5
    loops = tl.front_at(t)
    assert len(loops) == 1 and len(loops[0]) == 8


def test_hole_wave_meets_outer_wave():
    tl = build_timeline(SQUARE_WITH_HOLE)
    # band between hole and outer is 1.5 wide -> fronts meet at t=0.75
    assert tl.max_t == pytest.approx(0.75, abs=1e-3)
    # before that: two loops (outer shrinking, hole growing)
    loops = tl.front_at(0.3)
    assert len(loops) == 2


def test_playback_positions_continuous_across_events():
    tl = build_timeline(LSHAPE)
    t_ev = tl.first_event_t
    for vid in {v for loop in tl.front_at(t_ev - 1e-4) for v in loop}:
        p_before = tl.pos_at(vid, t_ev - 1e-4)
        p_after = tl.pos_at(vid, t_ev + 1e-4)  # clamped to death pos
        assert norm(sub(p_after, p_before)) < 1e-2
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_smart_inset_core.py -v`
Expected: hole/star tests FAIL (fronts never meet — `max_t` wrong / infinite loop guard trips). L-shape may pass by luck of pure collapses; that is fine — the hole test is the forcing one.

- [ ] **Step 3: Implement**

Rework the event loop in `build_timeline` (keep Task 2 behavior intact for convex inputs):

```python
    def push_splits(r_vid):
        nonlocal seq
        R = tl.verts[r_vid]
        if not R.reflex:
            return
        for e in range(tl.edge_count):
            if e in (R.left_edge, R.right_edge):
                continue
            ea_vid, eb_vid = tl.orig_edges[e]
            ea, eb = tl.orig_pos[ea_vid], tl.orig_pos[eb_vid]
            n_e = edge_normal(ea, eb)
            denom = tl.edge_weight[e] - dot(n_e, R.V)
            if denom < EPS:
                continue
            d0 = dot(n_e, sub(R.pos(R.birth_t), ea)) - tl.edge_weight[e] * R.birth_t
            t = R.birth_t + d0 / denom
            if t <= R.birth_t + EPS:
                continue
            heapq.heappush(heap, (t, seq, "split", (r_vid, e)))
            seq += 1
```

Split validation + application inside the pop loop:

```python
        if kind == "split":
            r_vid, e = payload
            R = tl.verts[r_vid]
            if R.death_t != INF:
                continue
            X = R.pos(t)
            # find the live front edge descended from original edge e
            # that spans X at time t
            host = None
            for vid2, v2 in tl.verts.items():
                if v2.death_t != INF or v2.right_edge != e:
                    continue
                w = tl.verts[v2.next]
                pa, pb = v2.pos(t), w.pos(t)
                seg = sub(pb, pa)
                L2 = dot(seg, seg)
                if L2 < EPS:
                    continue
                u = dot(sub(X, pa), seg) / L2
                off = norm(sub(X, add(pa, mul(seg, u))))
                if -1e-6 <= u <= 1.0 + 1e-6 and off < 1e-4 * max(1.0, norm(seg)):
                    host = (v2, w)
                    break
            if host is None:
                continue  # stale event
            EA, EB = host
            if EA.vid in (R.prev, R.next) or EB.vid in (R.prev, R.next):
                continue  # became adjacent -> collapse handles it
            tl.first_event_t = min(tl.first_event_t, t)
            tl.max_t = max(tl.max_t, t)
            R.death_t = t
            n_l = edge_normal(*(tl.orig_pos[i] for i in tl.orig_edges[R.left_edge]))
            n_r = edge_normal(*(tl.orig_pos[i] for i in tl.orig_edges[R.right_edge]))
            n_e = edge_normal(*(tl.orig_pos[i] for i in tl.orig_edges[e]))
            R1 = FrontVert(next_vid, X,
                           vertex_velocity(n_l, n_e, tl.edge_weight[R.left_edge],
                                           tl.edge_weight[e]),
                           t, R.left_edge, e)
            R2 = FrontVert(next_vid + 1, X,
                           vertex_velocity(n_e, n_r, tl.edge_weight[e],
                                           tl.edge_weight[R.right_edge]),
                           t, e, R.right_edge)
            next_vid += 2
            # loop 1: ... R.prev -> R1 -> EB ...   loop 2: ... EA -> R2 -> R.next ...
            P, N = tl.verts[R.prev], tl.verts[R.next]
            R1.prev, R1.next = P.vid, EB.vid
            R2.prev, R2.next = EA.vid, N.vid
            P.next = R1.vid
            EB.prev = R1.vid
            EA.next = R2.vid
            N.prev = R2.vid
            R.succ_next = R1.vid
            R.succ_prev = R2.vid
            tl.verts[R1.vid] = R1
            tl.verts[R2.vid] = R2
            tl.nodes.append(Node(t, X, {R.left_edge, R.right_edge, e}))
            for nv in (R1, R2):
                e_in = normalize(sub(nv.pos(t + 1.0), X))  # velocity dir proxy
                nv.reflex = False  # split children start convex
                push_collapse(nv.prev, nv.vid)
                push_collapse(nv.vid, nv.next)
            continue
```

Also: call `push_splits(v.vid)` for every initial reflex vert before the loop; after a collapse merge creates `C`, set `C.reflex` from its edge pair (same cross-product test as in setup, using original edge directions) and call `push_splits(C.vid)` when reflex. The 2-vert loop-death branch and the collapse branch from Task 2 stay unchanged.

- [ ] **Step 4: Run tests, verify pass**

Run: `python -m pytest tests/test_smart_inset_core.py -v` — all PASS, including Tasks 1–3 regressions.

- [ ] **Step 5: Commit**

```bash
git add utils/smart_inset_core.py tests/test_smart_inset_core.py
git commit -m "feat(smart-inset): split events for reflex verts and holes"
```

---

### Task 5: Robustness — degenerate input sanitation and clamp helper

**Files:**
- Modify: `utils/smart_inset_core.py`
- Test: `tests/test_smart_inset_core.py`

**Interfaces:**
- Produces: `sanitize_loops(loops, weights=None, min_edge=1e-6) -> (loops, weights)` — drops zero-length edges (merging their endpoints) and collinear duplicate points; raises `ValueError("degenerate loop")` if a loop ends up with < 3 verts. `build_timeline` calls it internally.
- Clamp contract for the operator: clamp thickness = `timeline.first_event_t` (already produced by Task 2; this task just locks it with a test).

- [ ] **Step 1: Write the failing tests**

```python
# append to tests/test_smart_inset_core.py
from utils.smart_inset_core import sanitize_loops


def test_sanitize_drops_zero_edges():
    loops, _ = sanitize_loops([[(0, 0), (0, 0), (2, 0), (2, 2), (0, 2)]])
    assert len(loops[0]) == 4


def test_sanitize_rejects_degenerate_loop():
    with pytest.raises(ValueError):
        sanitize_loops([[(0, 0), (1, 0), (1e-9, 1e-10)]], min_edge=1e-3)


def test_timeline_survives_duplicate_points():
    tl = build_timeline([[(0, 0), (2, 0), (2, 0), (2, 2), (0, 2)]])
    assert tl.max_t == pytest.approx(1.0)


def test_clamp_equals_first_event():
    tl = build_timeline(RECT41)
    assert tl.first_event_t == pytest.approx(0.5)
    # clamp contract: front at first_event_t*0.999 is intact (4 verts)
    loops = tl.front_at(tl.first_event_t * 0.999)
    assert len(loops) == 1 and len(loops[0]) == 4


def test_spike_triangle_no_nan():
    # extremely acute triangle
    tl = build_timeline([[(0.0, 0.0), (10.0, 0.0), (10.0, 0.05)]])
    assert math.isfinite(tl.max_t)
    for n in tl.nodes:
        assert all(math.isfinite(c) for c in n.pos)
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_smart_inset_core.py -v` — FAIL on `sanitize_loops` import.

- [ ] **Step 3: Implement**

```python
def sanitize_loops(loops, weights=None, min_edge=1e-6):
    out_loops, out_weights = [], []
    for li, loop in enumerate(loops):
        w = list(weights[li]) if weights is not None else [1.0] * len(loop)
        pts, ws = [], []
        for i, p in enumerate(loop):
            if pts and norm(sub(p, pts[-1])) < min_edge:
                continue
            pts.append(tuple(p))
            ws.append(w[i])
        if len(pts) > 1 and norm(sub(pts[0], pts[-1])) < min_edge:
            pts.pop()
            ws.pop()
        if len(pts) < 3:
            raise ValueError("degenerate loop")
        out_loops.append(pts)
        out_weights.append(ws)
    return out_loops, out_weights
```

First line of `build_timeline` becomes: `loops, weights = sanitize_loops(loops, weights)`.

- [ ] **Step 4: Run tests, verify pass**

Run: `python -m pytest tests/test_smart_inset_core.py -v` — all PASS.

- [ ] **Step 5: Commit**

```bash
git add utils/smart_inset_core.py tests/test_smart_inset_core.py
git commit -m "feat(smart-inset): input sanitation and clamp contract"
```

---

### Task 6: Bridge — region extraction, 2D projection, `execute()` operator + registration

**Files:**
- Create: `operators/mesh_smart_inset.py`
- Modify: `__init__.py` (import near line 252, classes list near line 524)

**Interfaces:**
- Produces:
  - `class IOPS_OT_smart_inset(bpy.types.Operator)`, `bl_idname = "iops.mesh_smart_inset"`, props: `thickness: FloatProperty(subtype='DISTANCE', default=0.05)`, `depth: FloatProperty(default=0.0)`, `mode: EnumProperty(items=[('REGION',...),('INDIVIDUAL',...)], default='REGION')`, `use_collapse: BoolProperty(default=True)`, `use_boundary: BoolProperty(default=True)`, `bl_options = {"REGISTER", "UNDO"}`.
  - `collect_regions(bm, mode) -> list[Region]` where `Region` is a dataclass-like holder: `faces: list[BMFace]`, `loops3d: list[list[BMVert]]` (boundary loops, region on the left), `plane_origin: Vector`, `basis: (Vector, Vector, Vector)` (u, v, normal from area-weighted average), `weights: list[list[float]]`.
  - `region_to_2d(region) -> list[list[(x,y)]]` / `lift_to_3d(region, (x,y)) -> Vector` + BVH pull: `region.bvh = BVHTree.FromPolygons(...)`, `surface_snap(region, co3d) -> Vector`.
  - `apply_inset(bm, region, timeline, t, depth, use_collapse) -> None` — mutates bm: deletes region faces, creates wall faces (`[a, b] + walls_at chain`, lifted + snapped), fills each surviving front loop with an ngon, translates new verts by `depth * normal`. Skeleton-node verts deduplicated across walls via a `pos-rounded -> BMVert` dict (round to 6 decimals).
  - Effective thickness: `t_eff = min(thickness, timeline.first_event_t)` when `use_collapse` is False, `min(thickness, timeline.max_t)` when True.
- Boundary-loop extraction: boundary edges = region edges with exactly one linked face inside the region. Walk loops keeping the region on the left (orient by checking the inside face's loop direction). Open mesh borders get weight `0.0` when `use_boundary` is False, else `1.0`. If a loop walk fails (non-manifold junction), skip the region and `self.report({'WARNING'}, ...)`.
- `execute()` runs the full pipeline from props (no modal). Negative `thickness` in this task = no-op guard clamped to 0 (outset arrives in Task 10).
- Interior fill in this task = ngon(s) of the surviving front loops (interior-topology preservation is Task 11).

- [ ] **Step 1: Write the operator + bridge code**

Key skeleton (full file follows straight_bevel conventions — module docstring, `EPS`, imports of core via `from ..utils import smart_inset_core as core`):

```python
def collect_regions(bm, mode):
    sel = [f for f in bm.faces if f.select]
    if mode == 'INDIVIDUAL':
        groups = [[f] for f in sel]
    else:
        groups, seen = [], set()
        for f in sel:
            if f in seen:
                continue
            stack, comp = [f], []
            seen.add(f)
            while stack:
                cur = stack.pop()
                comp.append(cur)
                for e in cur.edges:
                    for lf in e.link_faces:
                        if lf.select and lf not in seen:
                            seen.add(lf)
                            stack.append(lf)
            groups.append(comp)
    return [_build_region(bm, g) for g in groups]


def _build_region(bm, faces):
    fset = set(faces)
    boundary = {}
    for f in faces:
        for loop in f.loops:
            e = loop.edge
            inside = sum(1 for lf in e.link_faces if lf in fset)
            if inside == 1:
                # oriented as the inside face walks it: region on the left
                boundary[(loop.vert, loop.link_loop_next.vert)] = e
    loops3d = []
    nxt = {a: b for (a, b) in boundary}
    while nxt:
        a, b = next(iter(nxt.items()))
        loop = [a]
        del nxt[a]
        while b in nxt and b is not loop[0]:
            loop.append(b)
            b2 = nxt[b]
            del nxt[b]
            b = b2
        if b is not loop[0]:
            raise RegionError("open/non-manifold boundary")
        loops3d.append(loop)
    ...  # plane fit (area-weighted normal + centroid), basis, weights, BVH
```

`apply_inset` essentials:

```python
def apply_inset(bm, region, tl, t, depth, use_collapse):
    t_eff = min(t, tl.max_t if use_collapse else tl.first_event_t)
    made = {}

    def bmvert(p2d):
        key = (round(p2d[0], 6), round(p2d[1], 6))
        v = made.get(key)
        if v is None:
            co = surface_snap(region, lift_to_3d(region, p2d))
            v = bm.verts.new(co)
            made[key] = v
        return v

    walls = tl.walls_at(t_eff)
    for j in range(tl.edge_count):
        a3, b3 = region.edge_orig_verts[j]      # original BMVerts of edge j
        chain = [bmvert(p) for p in walls[j]]
        poly = [a3, b3] + chain
        poly = [v for i, v in enumerate(poly) if v not in poly[:i]]
        if len(poly) >= 3:
            bm.faces.new(poly)
    for loop in tl.front_at(t_eff):
        verts = [bmvert(tl.pos_at(vid, t_eff)) for vid in loop]
        if len(verts) >= 3:
            bm.faces.new(verts)
    if abs(depth) > 1e-9:
        n = region.basis[2]
        for v in made.values():
            v.co += n * depth
    bmesh.ops.delete(bm, geom=region.faces, context='FACES')
    bm.normal_update()
```

`execute()` glues it: `bmesh.from_edit_mesh`, `collect_regions`, per region `core.build_timeline(region_to_2d(region), region.weights)`, `apply_inset`, `bmesh.update_edit_mesh(me, loop_triangles=True, destructive=True)`. Wrap `bm.faces.new` in try/except `ValueError` (face exists) — skip duplicates. Wrap region build in try/except `RegionError` → report + continue.

Registration in `__init__.py`: `from .operators.mesh_smart_inset import IOPS_OT_smart_inset` next to the straight-bevel import, class appended to the register list.

- [ ] **Step 2: Smoke-test via blender-mcp**

Use the `blender-mcp` skill / `mcp__blender__execute_blender_python`. Script:

```python
import bpy, bmesh
bpy.ops.mesh.primitive_plane_add(size=2)
obj = bpy.context.active_object
bpy.ops.object.mode_set(mode='EDIT')
bpy.ops.mesh.select_all(action='SELECT')
r = bpy.ops.iops.mesh_smart_inset(thickness=0.3)
bm = bmesh.from_edit_mesh(obj.data)
print(r, len(bm.verts), len(bm.faces))  # plane: 8 verts, 5 faces
```

Expected: `{'FINISHED'}`, 8 verts / 5 faces (4 walls + 1 inner ngon). Then rerun with `thickness=5.0` (past collapse): plane collapses to a point → 5 verts, 4 triangle walls, no inner face, **no errors**. Also test a 4×1 stretched plane at `thickness=5.0`: medial segment → 6 verts, walls only.

- [ ] **Step 3: Fix until smoke passes, run core tests too**

Run: `python -m pytest tests/test_smart_inset_core.py -v` — still all PASS (bridge must not touch core).

- [ ] **Step 4: Commit**

```bash
git add operators/mesh_smart_inset.py __init__.py
git commit -m "feat(smart-inset): bmesh bridge and execute() operator"
```

---

### Task 7: Modal skeleton — invoke, mouse thickness, HUD, confirm/cancel

**Files:**
- Modify: `operators/mesh_smart_inset.py`

**Interfaces:**
- Consumes: Task 6's `collect_regions` / timelines / `apply_inset`.
- Produces: working modal: `invoke` builds regions + timelines once, caches `self._regions` (list of `(region, timeline)`), sets `self._pixel_to_t` sensitivity from average region size (pattern: `mesh_straight_bevel.py:281-283` — quarter of average boundary-edge length per 100 px); `modal` maps `event.mouse_region_x` delta to thickness, LMB/Enter confirm (apply + `{'FINISHED'}`), RMB/Esc cancel (no mesh change, `{'CANCELLED'}`), `H` toggles HUD/help via `handle_hud_toggle`/`handle_help_toggle`.
- Preview during modal: **do not** mutate bmesh per tick. Draw with the handler only (Task 9 adds proper GPU preview; this task draws just the front loops as lines using `ui.draw.primitives`).
- HUD: `HUDOverlay("smart_inset")`, title "Smart Inset", params Thickness (float getter), Depth, Mode, Collapse — the exact `HUDParam` pattern of `mesh_straight_bevel.py:344-352`. `HelpOverlay` section with the key table from the spec.
- Lifecycle safety: module-level `_ACTIVE_HANDLES` + `_purge_handles()` copied from `mesh_straight_bevel.py:20-31`; `modal` body wrapped in try/except that removes the handler and re-raises.

- [ ] **Step 1: Implement invoke/modal following straight_bevel structure**

`invoke` outline (mirror `mesh_straight_bevel.py:262-375`): bmesh from edit mesh, `collect_regions`, build timelines (`core.build_timeline`), bail with WARNING if no valid region; sensitivity; `_purge_handles()`; HUD + help setup; `safe_handler_add(... POST_PIXEL, tick=True)`; `status_text_set`; `modal_handler_add`.

`modal` outline: `tag_redraw`; `capture_event`; on `MOUSEMOVE`: `self.thickness = self._initial + (event.mouse_region_x - self._mouse_start_x) * self._pixel_to_t` (Shift held → ×0.1 of delta since Shift press, same accumulation trick as straight_bevel); on `LEFTMOUSE/RET`: call `self.execute(context)` equivalent apply path, cleanup, `{'FINISHED'}`; on `RIGHTMOUSE/ESC`: cleanup, `{'CANCELLED'}`; `H` → HUD toggles; pass-through `MIDDLEMOUSE`/wheel for navigation.

Draw callback: for each `(region, tl)`, `t_eff` as in Task 6; for each front loop, polyline of `surface_snap(lift_to_3d(...))` positions projected via `view3d_utils.location_3d_to_region_2d`, drawn with `draw` primitives themed via `get_theme()`.

- [ ] **Step 2: Interactive smoke via blender-mcp**

Modal operators can't be driven interactively over MCP — test the pieces instead: run `invoke`-path helpers directly (build regions + timelines on a test mesh, call the thickness→apply path with fixed values) and verify HUD classes construct without exceptions. Manual check by the user comes after Task 9 (preview).

- [ ] **Step 3: Commit**

```bash
git add operators/mesh_smart_inset.py
git commit -m "feat(smart-inset): modal skeleton with HUD and mouse thickness"
```

---

### Task 8: Modal input — numeric entry, Ctrl depth, I/C/B toggles

**Files:**
- Modify: `operators/mesh_smart_inset.py`

**Interfaces:**
- Consumes: Task 7's modal loop.
- Produces:
  - Numeric input: copy the `DIGIT_TYPES` table + input-string parser from `mesh_straight_bevel.py:33-39` and its modal digit handling: digits/`.`/`-`/`BACK_SPACE` build `self._input_str`; non-empty string overrides mouse thickness (`float(self._input_str)` guarded by try/except ValueError); minus sign toggles sign.
  - `Ctrl` held: mouse X controls `self.depth` instead of thickness (store separate anchor `self._mouse_depth_anchor` on Ctrl press; restore thickness anchor on release).
  - `I`: toggles `self.mode` REGION↔INDIVIDUAL — rebuild regions + timelines in place (same code path as invoke; if rebuild fails, report and keep previous mode).
  - `C`: toggles `self.use_collapse` (affects `t_eff` only — no rebuild).
  - `B`: toggles `self.use_boundary` — rebuild (weights change).
  - HUD params already read these via getters (Task 7), so the HUD updates for free; add `HUDParam("Mode (I)", ...)`, `"Collapse (C)"`, `"Boundary (B)"` entries if not present.
- Clamp behavior: when `use_collapse` is False and requested thickness exceeds `min(first_event_t)` across regions, displayed thickness freezes at the cap (per-region `t_eff` already caps; the HUD shows the capped value).

- [ ] **Step 1: Implement all four input paths** (each is a small `elif` block in `modal`, mirroring straight_bevel's handling).

- [ ] **Step 2: MCP piece-test**

Drive the operator's internal state machine directly (instantiate, feed synthetic state): set `_input_str = "0.35"`, assert effective thickness 0.35; toggle mode with a two-region selection, assert `_regions` length changes between REGION (1 island → 1) and INDIVIDUAL (n faces → n).

- [ ] **Step 3: Commit**

```bash
git add operators/mesh_smart_inset.py
git commit -m "feat(smart-inset): numeric input, depth, mode/collapse/boundary toggles"
```

---

### Task 9: GPU preview — front contour, seam highlight, clamp feedback

**Files:**
- Modify: `operators/mesh_smart_inset.py`

**Interfaces:**
- Consumes: Task 7's draw callback; `Timeline.nodes` (positions + `t`).
- Produces, in the POST_PIXEL callback:
  - Front loops drawn as closed polylines (theme `Role` used by straight_bevel preview).
  - Medial seams: skeleton nodes with `node.t <= t_eff` connected wall-top chains — draw `walls_at(t_eff)` chain segments whose both endpoints are node positions (i.e. already-collapsed sections) in a second theme colour, so the user sees where collapse happened.
  - Clamp feedback: when `use_collapse` is False and the requested thickness > cap, draw the contour in the theme's warning/active colour (same colour-switch pattern straight_bevel uses for its active states). Remember `ui/hud` colors must go through sRGB conversion if fed from COLOR props (see memory note: `from_scene_linear_to_srgb`).
- Depth is included in preview: lifted positions get `+ normal * depth` before projection to 2D screen space.

- [ ] **Step 1: Implement the three draw layers.**
- [ ] **Step 2: User does a manual visual pass in Blender** (this is the first fully drivable build: mouse, keys, preview). Fix reported issues.
- [ ] **Step 3: Commit**

```bash
git add operators/mesh_smart_inset.py
git commit -m "feat(smart-inset): GPU preview with seam and clamp feedback"
```

---

### Task 10: Naive outset (negative thickness)

**Files:**
- Modify: `operators/mesh_smart_inset.py`

**Interfaces:**
- Consumes: Task 6's apply pipeline.
- Produces: `thickness < 0` routes to `_apply_outset(bm, region, t)` — no skeleton: each boundary vertex is displaced **outward** by `vertex_velocity(n_prev, n_next) * |t|` in the region plane (negated normals), new outer contour + wall quads between original boundary and outer contour, original region faces kept untouched. Mirrors native outset behavior; no collapse handling by design (spec non-goal).
- Modal: mouse continues smoothly through zero; preview draws the outset contour with the same front-loop layer.

- [ ] **Step 1: Implement `_apply_outset` + preview branch.**
- [ ] **Step 2: MCP smoke:** plane, `thickness=-0.3` → 8 verts, 5 faces, outer ring outside the original bounds.
- [ ] **Step 3: Commit**

```bash
git add operators/mesh_smart_inset.py
git commit -m "feat(smart-inset): naive outset for negative thickness"
```

---

### Task 11: Interior topology preservation

**Files:**
- Modify: `operators/mesh_smart_inset.py`
- Test: `tests/test_smart_inset_core.py` (helper), MCP for the bmesh part

**Interfaces:**
- Consumes: `Timeline.front_at/pos_at`, region 2D projection.
- Produces: `apply_inset` upgrade — instead of unconditional ngon fill:
  1. Compute 2D distance-to-boundary for every **interior** vertex of the region (min perpendicular/endpoint distance to boundary loops — add core helper `boundary_distance(loops, p) -> float` with 3 unit tests: center of square = 1.0, on boundary = 0.0, near corner uses endpoint distance).
  2. Interior verts with `dist > t_eff + eps` survive as-is; faces whose verts all survive are kept.
  3. Faces crossed by the front: clipped — walk each face's edge cycle; edges crossing the iso-level `dist == t_eff` get a crossing point (binary search on the piecewise-linear min-distance along the edge, 20 iterations); the kept polygon = surviving verts + crossing points; crossing points are also **inserted into the front loop ngon** (they lie on the offset curve within 1e-4) so the fill ngon and clipped faces share verts (match by rounded 2D key, the Task 6 `made` dict).
  4. Front-loop fill ngons now use the loop verts **plus** inserted crossing points ordered along the loop (sort by distance along the loop polyline).
- Fallback: if clipping a region raises or produces a degenerate polygon, log via `self.report({'WARNING'}, "interior clip failed, ngon fill used")` and fall back to Task 6's plain ngon fill for that region. Never crash.

- [ ] **Step 1: Write core `boundary_distance` tests + implementation** (pytest).
- [ ] **Step 2: Implement clip in apply_inset.**
- [ ] **Step 3: MCP verification:** 4×4-face grid plane, select all, `thickness=0.2` — the 4 inner verts (dist 0.5) must survive at their original positions; face count = 4 walls-side... verify: inner 2×2 faces intact, ring faces clipped, no doubled verts (`bmesh.ops.find_doubles` returns empty at dist 1e-5).
- [ ] **Step 4: Run full pytest suite** — PASS.
- [ ] **Step 5: Commit**

```bash
git add utils/smart_inset_core.py operators/mesh_smart_inset.py tests/test_smart_inset_core.py
git commit -m "feat(smart-inset): preserve interior topology via front clipping"
```

---

### Task 12: Integration smoke suite + docs + registration polish

**Files:**
- Create: `docs/operators/op_mesh_smart_inset.md`
- Modify: `utils/functions.py` (legacy-idname map only if pie/hotkey integration is added — otherwise skip)

**Interfaces:**
- Consumes: everything.
- Produces: a written MCP smoke checklist executed in live Blender, and user docs.

- [ ] **Step 1: Run the full MCP smoke matrix** (one `execute_blender_python` script, asserts inline, prints PASS/FAIL per case):
  - plane `t=0.3` (basic), plane `t=99` (full collapse, no self-intersection: `bmesh.ops.find_doubles` empty, `mathutils.bvhtree` self-overlap check returns no non-adjacent pairs),
  - stretched plane 4×1 `t=99` (medial segment),
  - L-shaped ngon (split),
  - grid 4×4 select-all REGION `t=0.2` (interior preserved) and INDIVIDUAL `t=0.2` (16 independent insets),
  - plane with `use_boundary=False` on an open border,
  - `t=-0.3` outset,
  - `depth=0.5` (verify translation along normal),
  - non-planar: subdivided+randomized plane, `t=0.3` — result verts lie on/near original surface (BVH distance < 5% of size).
- [ ] **Step 2: Fix anything the matrix catches; rerun until green.**
- [ ] **Step 3: Write `docs/operators/op_mesh_smart_inset.md`** — follow `docs/operators/op_mesh_cursor_bisect.md` structure: what it does, key table (from spec UX section), collapse vs clamp explanation with the medial-axis wording, outset/depth notes, limitations (naive outset, approximate on strongly curved surfaces).
- [ ] **Step 4: Run pytest suite one final time** — PASS.
- [ ] **Step 5: Commit**

```bash
git add docs/operators/op_mesh_smart_inset.md
git commit -m "feat(smart-inset): integration smoke matrix and user docs"
```

---

## Self-Review Notes

- **Spec coverage:** collapse-merge core (Tasks 2–4), clamp (5, 8), region/individual (6, 8), depth (8, 9), outset naive (10), boundary toggle/weights (1, 6, 8), non-planarity via plane projection + BVH snap (6), HUD/preview/numeric input (7–9), interior preservation (11), error handling (5, 6, 11), pytest + MCP testing (throughout, 12). Docs (12).
- **Known risk:** Task 4 split events are the algorithmically hardest part; the lazy-invalidation queue plus pop-time span validation is the standard Felkel approach. If the hole test proves unstable, an acceptable v1 degradation is treating each loop's `first_event_t` as the region cap when a hole is present (clamp-only for holed regions) — surface this to the user if reached, do not silently ship it.
- **Type consistency check:** `build_timeline(loops, weights)`, `Timeline.{first_event_t,max_t,front_at,pos_at,walls_at,nodes,edge_count,orig_edges,orig_pos}`, `vertex_velocity(n_prev,n_next,w_prev,w_next)`, `sanitize_loops(loops,weights,min_edge)` — used consistently across Tasks 2–11.
