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


INF = float("inf")


class FrontVert:
    __slots__ = ("vid", "P0", "V", "birth_t", "death_t",
                 "left_edge", "right_edge", "prev", "next",
                 "succ_next", "succ_prev", "reflex", "birth_parent")

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
        # For a merge-created vert: the vid that occupied this vert's slot
        # (as seen from the `prev` side) before it was born. Needed because
        # a still-alive predecessor's `.next` is mutated to point at this
        # vert immediately when it is created, even for query times before
        # its birth_t -- see Timeline._resolve_next.
        self.birth_parent = None

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

    # ---- playback -------------------------------------------------------

    def pos_at(self, vid, t):
        v = self.verts[vid]
        return v.pos(min(t, v.death_t))

    def _alive(self, vid, t):
        v = self.verts[vid]
        return v.birth_t <= t < v.death_t

    def _resolve_next(self, vid, t):
        """Follow the chain until a vert alive at t (or None).

        A live vert's `.next` is mutated in place the instant its neighbour
        merges away, even for query times before the merge-created vert's
        birth_t. So a `.next` target can be either already-dead (jump
        forward via succ_next, Task 2's mechanism) or not-yet-born (jump
        backward via birth_parent to the vert it is replacing).
        """
        cur = self.verts[vid].next
        guard = 0
        while cur is not None and cur >= 0:
            v = self.verts[cur]
            if t < v.birth_t:
                cur = v.birth_parent
            elif t >= v.death_t:
                cur = v.succ_next
            else:
                return cur
            guard += 1
            if guard > len(self.verts):
                return None
        return None

    def front_at(self, t):
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


def _orig_edge_endpoints(tl, e):
    a_vid, b_vid = tl.orig_edges[e]
    return tl.orig_pos[a_vid], tl.orig_pos[b_vid]


def _orig_edge_normal(tl, e):
    a, b = _orig_edge_endpoints(tl, e)
    return edge_normal(a, b)


def _orig_edge_dir(tl, e):
    a, b = _orig_edge_endpoints(tl, e)
    return normalize(sub(b, a))


def _is_reflex(tl, left_edge, right_edge):
    """Convexity of a front vertex from its two original edge directions.

    Same test as the initial-LAV setup (cross of incoming/outgoing edge
    direction), but expressed in terms of edge ids so it also works for
    event-born vertices, whose incident original edges are no longer
    consecutive in the input loop.
    """
    return cross(_orig_edge_dir(tl, left_edge),
                 _orig_edge_dir(tl, right_edge)) < -EPS


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

    def push_splits(r_vid):
        """Queue split candidates of reflex vert `r_vid` against every edge.

        A reflex vertex R can hit the moving front descended from *any*
        original edge of the region -- including edges of a different input
        loop, which is exactly how a hole's outward wave meets the outer
        wave. Only R's own two incident edges are skipped.

        Timing: the front line of edge e at time t is
        {X : dot(n_e, X - ea) == w_e * t}. With R(t) = P0 + V*(t - birth_t),
        the signed gap
            gap(t) = dot(n_e, R(t) - ea) - w_e * t
        is affine in t with slope -(w_e - dot(n_e, V)) = -denom, so
            gap(t) = d0 - denom * (t - birth_t),
            d0 = gap(birth_t) = dot(n_e, P0 - ea) - w_e * birth_t.
        The hit is at t = birth_t + d0 / denom, and only exists in the
        future when the gap is currently positive (d0 > 0) and closing
        (denom > 0).
        """
        nonlocal seq
        R = tl.verts[r_vid]
        if not R.reflex or R.death_t != INF:
            return
        P0 = R.pos(R.birth_t)
        for e in range(tl.edge_count):
            if e in (R.left_edge, R.right_edge):
                continue
            ea = _orig_edge_endpoints(tl, e)[0]
            n_e = _orig_edge_normal(tl, e)
            w_e = tl.edge_weight[e]
            denom = w_e - dot(n_e, R.V)
            if denom < EPS:
                continue
            d0 = dot(n_e, sub(P0, ea)) - w_e * R.birth_t
            if d0 <= EPS:
                continue
            t_hit = R.birth_t + d0 / denom
            if t_hit <= R.birth_t + EPS:
                continue
            heapq.heappush(heap, (t_hit, seq, "split", (r_vid, e)))
            seq += 1

    def find_host_edge(R, e, t, X):
        """Live front edge descended from original edge `e` spanning X at t."""
        for vid2, v2 in tl.verts.items():
            if v2.death_t != INF or v2.birth_t > t + EPS:
                continue
            if v2.right_edge != e or vid2 == R.vid:
                continue
            if v2.next is None or v2.next < 0:
                continue
            w = tl.verts[v2.next]
            if w.death_t != INF or w.vid == R.vid:
                continue
            pa, pb = v2.pos(t), w.pos(t)
            seg = sub(pb, pa)
            L2 = dot(seg, seg)
            if L2 < EPS:
                continue
            u = dot(sub(X, pa), seg) / L2
            off = norm(sub(X, add(pa, mul(seg, u))))
            if -1e-6 <= u <= 1.0 + 1e-6 and off < 1e-4 * max(1.0, norm(seg)):
                return v2, w
        return None

    for v in list(tl.verts.values()):
        push_collapse(v.vid, v.next)
    for v in list(tl.verts.values()):
        push_splits(v.vid)

    next_vid = vid
    # Safety valve: every event kills at least one vertex, and each event
    # creates at most two, so the count is bounded in theory; the cap only
    # protects against pathological float feedback loops.
    budget = 64 * (len(tl.verts) + tl.edge_count) ** 2 + 1000
    while heap:
        budget -= 1
        if budget <= 0:
            break
        t, _, kind, payload = heapq.heappop(heap)

        if kind == "split":
            r_vid, e = payload
            R = tl.verts[r_vid]
            if R.death_t != INF:
                continue
            X = R.pos(t)
            host = find_host_edge(R, e, t, X)
            if host is None:
                continue  # stale event: that piece of e's front is gone
            EA, EB = host
            tl.first_event_t = min(tl.first_event_t, t)
            tl.max_t = max(tl.max_t, t)
            R.death_t = t
            P, N = tl.verts[R.prev], tl.verts[R.next]
            n_l = _orig_edge_normal(tl, R.left_edge)
            n_r = _orig_edge_normal(tl, R.right_edge)
            n_e = _orig_edge_normal(tl, e)
            R1 = FrontVert(next_vid, X,
                           vertex_velocity(n_l, n_e,
                                           tl.edge_weight[R.left_edge],
                                           tl.edge_weight[e]),
                           t, R.left_edge, e)
            R2 = FrontVert(next_vid + 1, X,
                           vertex_velocity(n_e, n_r,
                                           tl.edge_weight[e],
                                           tl.edge_weight[R.right_edge]),
                           t, e, R.right_edge)
            next_vid += 2
            # birth_parent == "whoever occupied my slot, seen from my prev".
            # P.next was R; EA.next was EB.
            R1.birth_parent = R.vid
            R2.birth_parent = EB.vid
            R1.reflex = _is_reflex(tl, R.left_edge, e)
            R2.reflex = _is_reflex(tl, e, R.right_edge)
            # loop 1: ... P -> R1 -> EB ...   loop 2: ... EA -> R2 -> N ...
            R1.prev, R1.next = P.vid, EB.vid
            R2.prev, R2.next = EA.vid, N.vid
            P.next = R1.vid
            EB.prev = R1.vid
            EA.next = R2.vid
            N.prev = R2.vid
            # walking CCW from P must continue onto R1; the backwards
            # direction (unused by playback) resolves onto R2
            R.succ_next = R1.vid
            R.succ_prev = R2.vid
            tl.verts[R1.vid] = R1
            tl.verts[R2.vid] = R2
            tl.nodes.append(Node(t, X, {R.left_edge, R.right_edge, e}))
            for nv in (R1, R2):
                if nv.next == nv.prev:
                    # The new loop has only two vertices, and both are the
                    # intersection of the *same* pair of moving edge lines,
                    # so they are already coincident at X: the loop has zero
                    # extent and dies immediately (same terminal-bigon
                    # handling as the collapse path).
                    peer = tl.verts[nv.next]
                    nv.death_t = t
                    if peer.death_t == INF:
                        peer.death_t = t
                    tl.nodes.append(Node(t, X, {nv.left_edge, nv.right_edge,
                                                peer.left_edge,
                                                peer.right_edge}))
                    continue
                push_collapse(nv.prev, nv.vid)
                push_collapse(nv.vid, nv.next)
                push_splits(nv.vid)
            continue

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
        C.birth_parent = A.vid
        C.reflex = _is_reflex(tl, A.left_edge, B.right_edge)
        next_vid += 1
        C.prev, C.next = P.vid, N.vid
        P.next = C.vid
        N.prev = C.vid
        A.succ_next = A.succ_prev = C.vid
        B.succ_next = B.succ_prev = C.vid
        tl.verts[C.vid] = C
        tl.nodes.append(Node(t, pos, {A.left_edge, A.right_edge, B.right_edge}))

        if P.vid == N.vid:
            # P and C are now mutual sole neighbours: the LAV has reached a
            # 2-vertex degenerate state as a *result* of this merge (rather
            # than by directly processing an edge event with B.next==a_vid).
            # This happens e.g. when two opposite short edges of an
            # elongated rect collapse simultaneously, leaving a pinched
            # ridge between two already-recorded nodes. C's velocity here
            # comes from two anti-parallel constraint normals (the
            # spike/bisector branch of vertex_velocity), which is only a
            # capped placeholder, not a meaningful direction -- computing a
            # further collapse from it would inject spurious high-speed
            # motion and a bogus extra node. Freeze both verts instead of
            # queuing another collapse event.
            C.death_t = t
            P.death_t = t
            continue
        push_collapse(P.vid, C.vid)
        push_collapse(C.vid, N.vid)
        push_splits(C.vid)

    if tl.first_event_t is INF:
        tl.first_event_t = 0.0
    return tl
