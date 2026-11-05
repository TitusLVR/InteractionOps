"""Smart Edge Slide bridge: from the edit mesh to core bands, and core cuts back onto it.

``utils/smart_edge_slide_core`` knows nothing about bpy. This module turns the
selection into chains and one side of one chain into a core ``Band``:

1. chains are the connected runs of selected, visible edges, in an order that
   stays the same across redo;
2. a band holds every visible face a flood fill reaches on one side, from the
   side face of every chain edge and the wedge faces around each chain vertex,
   without crossing a chain edge. At an open chain's ends the wedge runs on past
   edges too shallow to end the new loop on; the edge it stops at is the end
   edge, which the core continues as the end wall;
3. a side face that turns away while the chain runs straight across it and its
   two neighbours agree (a pocket lip) is a *step*. The band swaps it for a
   virtual *lid* polygon that continues the neighbours' surface along both flank
   rail paths, and the step keeps the real faces under it, between those paths,
   as its region, for the cut to be projected onto. The flood leaves the region
   out: the lid stands for it.

Real faces keep their ``BMFace.index`` as band ids; lids get negative ids.

``apply_cut`` then builds a solved ``core.Cut`` into the mesh: it splits edges,
reuses vertices and edges the loop lands on, splits faces, and swaps every piece
on a lid for its projection onto the step's region (``project_step``). For UV
Stripe, ``stripe_for`` turns the faces between the chain and the new loop into a
``uv_stripe_core.Strip``.

For the modal, ``preview_layers`` draws what ``apply_cut`` would build, and
``snap_candidates`` / ``snap_target`` give the vertices Ctrl can snap the width to.
"""

import math
from collections import Counter, deque
from dataclasses import dataclass, field
from functools import cached_property
from typing import NamedTuple

import bmesh
from bmesh.types import BMEdge, BMFace, BMLoop, BMVert
from mathutils import Vector, geometry

from ..utils import smart_edge_slide_core as core
from ..utils import uv_stripe_core

BRANCHING = "branching selection"
NO_SIDE_FACE = "chain edge without a visible face on that side"
SEVERAL_SIDE_FACES = "chain edge with several faces on that side"
NO_FLANK_RAIL = "step without a flank rail"
WEDGE_INTERRUPTED = (
    "the faces round a chain vertex stop at an edge without exactly two visible faces, or an end wall cannot leave them"
)
MIXED_SECTORS = "chain vertex side faces with inconsistent normals"
STEP_GAP = "the cut across a step leaves a gap in the faces under it"
LOOSE_LOOP = "new loop does not run between two separate vertices or edges"
INSIDE_ONE_FACE = "the loop lies inside one face; use Smart Inset"
NO_SHARED_FACE = "consecutive new loop points share no face"
NO_CUT_EDGE = "new loop point on an edge the mesh does not have"
PIECE_FAILED = "a piece of the new loop could not be cut into its face"
CONNECTOR_FAILED = "a connecting edge could not be cut into its face"
LOOP_GAP = "the new loop has a gap"
NO_STRIP_FACES = "no faces between the chain and the new loop"
NO_STRIP_LENGTH = "the strip between the chain and the new loop has no length"
LOOP_REVISITS = "the new loop passes through one vertex twice"

# At an open chain's end the band keeps unfolding faces around the end vertex
# while the edge it reaches stays closer than this to the end chain edge: such an
# edge is too shallow to end the new loop on (the rail rule's own bound).
END_SHALLOW = math.pi / 2.0 - core.RAIL_MAX_DEV
# A step run's edges differ from the flanks' mean by more than acos(STEP_DIFFER_COS),
# and that mean lies within acos(STEP_AGREE_COS) / 2 of the left flank. An edge this
# close to the left flank therefore fits in no run that starts there.
_RUN_BREAK_COS = math.cos(math.acos(core.STEP_DIFFER_COS) - math.acos(core.STEP_AGREE_COS) / 2.0)
LID_TOL = 1e-5
# Modelling noise at a step grows with the step: a lip corner a little off its
# plane must neither drop the faces under the lid nor open a gap between their
# pieces. The lid-region test and ``project_step``'s matching therefore also
# allow this fraction of the lid extent (the largest distance between lid corners).
STEP_REL_TOL = 1e-4
# mathutils.Vector holds float32, whose spacing grows with the coordinates: each
# tolerance below is the larger of its floor and that many float32 steps at the
# size of the coordinates involved (see ``_tolerance``).
# A cut point this close to a vertex is that vertex, and so is a split point this
# close to the previous one on its edge: no zero-length edges. A vertex this close
# to a step's sheet lies on it.
WELD_TOL, WELD_STEPS = 1e-6, 4
# ``project_step`` matches positions this close (where the elements they lie on do
# not already match), and lets a piece run this far past either end of its span.
# The lid-region test allows as many float32 steps, over the ``LID_TOL`` floor.
PROJECT_TOL, PROJECT_STEPS = 1e-5, 8
_F32_STEP = 2.0 ** -23  # float32 spacing relative to the magnitude, at most


@dataclass
class ChainSrc:
    """A chain of selected edges; ``index`` is its place in ``collect_chains`` order (``chain_sides``)."""

    verts: list[BMVert]
    closed: bool
    index: int


@dataclass
class StepSpan:
    """A step: chain edges ``first .. last - 1`` (cyclic on a closed chain) lie under lid ``lid``.

    ``normal`` is the projection direction, the mean normal of the two flank
    faces. ``region`` is the real faces under the step (``_step_region``), sorted by index.
    ``extent`` is the largest distance between the lid's first corners (P_a .. P_b and
    the two flank rails' far vertices), which scales its tolerances.
    """

    lid: int
    first: int
    last: int
    normal: Vector
    region: list[BMFace]
    extent: float = 0.0


@dataclass
class BandBuild:
    """The band of one chain on one side: ``chain_index`` is the chain's ``ChainSrc.index``, ``side`` +1 or -1.

    ``faces`` are the band's real faces by index, ``verts`` every band vertex
    (chain, real faces and lid corners) by index. The band may span the whole
    mesh, so its lookups are worked out once per build, for every preview.
    """

    band: core.Band
    chain: list[BMVert]
    faces: dict[int, BMFace]
    steps: list[StepSpan]
    chain_index: int
    side: int
    verts: dict[int, BMVert]

    @cached_property
    def edge_faces(self) -> dict[tuple[int, int], set[int]]:
        """Band faces on each edge, keyed by sorted vertex ids."""
        return _band_edge_faces(self.band)

    @cached_property
    def vert_faces(self) -> dict[int, list[int]]:
        """Band faces at each vertex id, in band order."""
        out: dict[int, list[int]] = {}
        for f, loop in self.band.faces.items():
            for v in loop:
                out.setdefault(v, []).append(f)
        return out

    @cached_property
    def weld(self) -> float:
        """The weld tolerance at the size of the band's coordinates (see ``WELD_TOL``)."""
        return _tolerance(WELD_TOL, WELD_STEPS, self.band.verts.values())


@dataclass
class Applied:
    """The new loop ``apply_cut`` built: its edges and vertices in loop order.

    ``anchors[k]`` indexes ``chain[k]``'s new vertex in ``loop_verts``; None where
    the cut has none, or where it lay on a lid and the projection replaced it.
    ``strip_faces`` are the faces between the chain and the new loop, found only
    for a complete cut. ``failures`` says what could not be built once the mesh
    was being edited: the cut is then incomplete, though every edit made is whole.
    """

    loop_edges: list[BMEdge]
    loop_verts: list[BMVert]
    anchors: list[int | None]
    strip_faces: list[BMFace] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)


# --- chains ----------------------------------------------------------------------


def collect_chains(bm) -> tuple[list[ChainSrc], list[str]]:
    """The selected, visible edges split into chains, plus a warning per skipped component.

    Components sort by their smallest vertex index. An open chain starts at its
    end vertex with the smaller index. A closed chain starts at its smallest-index
    vertex and heads to that vertex's smaller-index neighbour. A component with
    a vertex of three or more selected edges is skipped as branching.
    """
    bm.verts.index_update()
    links: dict[BMVert, list[BMVert]] = {}
    for e in bm.edges:
        if e.select and not e.hide:
            a, b = e.verts
            links.setdefault(a, []).append(b)
            links.setdefault(b, []).append(a)

    components, seen = [], set()
    for v in links:
        if v in seen:
            continue
        seen.add(v)
        comp, stack = [v], [v]
        while stack:
            for w in links[stack.pop()]:
                if w not in seen:
                    seen.add(w)
                    comp.append(w)
                    stack.append(w)
        components.append(comp)
    components.sort(key=lambda c: min(v.index for v in c))

    chains, warnings = [], []
    for comp in components:
        if any(len(links[v]) > 2 for v in comp):
            warnings.append(BRANCHING)
            continue
        ends = [v for v in comp if len(links[v]) == 1]
        start = min(ends or comp, key=lambda v: v.index)
        path, prev, cur = [start], start, min(links[start], key=lambda v: v.index)
        while cur is not start:
            path.append(cur)
            ahead = [w for w in links[cur] if w is not prev]
            if not ahead:
                break
            prev, cur = cur, ahead[0]
        chains.append(ChainSrc(verts=path, closed=not ends, index=len(chains)))
    return chains, warnings


# --- face helpers ----------------------------------------------------------------


def _normal(face: BMFace) -> Vector:
    """The face normal from its current coordinates (``BMFace.normal`` may be stale).

    The coordinates are taken relative to the face's first vertex: Newell's sums
    over float32 coordinates far from the origin would lose the face's own size.
    """
    origin = face.verts[0].co.copy()
    return geometry.normal([v.co - origin for v in face.verts])


def _loop_at(face: BMFace, v: BMVert) -> BMLoop:
    return next(lp for lp in face.loops if lp.vert is v)


def _other_edge(face: BMFace, v: BMVert, came: BMVert) -> tuple[BMVert, BMEdge]:
    """The edge of ``face`` at ``v`` other than (v, came), as (far vertex, edge)."""
    lp = _loop_at(face, v)
    if lp.link_loop_next.vert is came:
        return lp.link_loop_prev.vert, lp.link_loop_prev.edge
    return lp.link_loop_next.vert, lp.edge


def _corner(face: BMFace, v: BMVert) -> float:
    """Interior angle of ``face`` at ``v``, reflex corners included."""
    lp = _loop_at(face, v)
    a = lp.link_loop_next.vert.co - v.co
    b = lp.link_loop_prev.vert.co - v.co
    angle = math.atan2(_normal(face).dot(a.cross(b)), a.dot(b))
    return angle if angle >= 0.0 else angle + 2.0 * math.pi


def _across(edge: BMEdge, face: BMFace) -> BMFace | None:
    """The other face of an ``edge`` that exactly two visible faces hold, ``face`` one of them; else None.

    Hidden faces count as absent, so a hidden fin leaves its edge crossable.
    """
    visible = [f for f in edge.link_faces if not f.hide]
    if len(visible) != 2 or face not in visible:
        return None
    return visible[0] if visible[1] is face else visible[1]


def _fan(
    v: BMVert, face: BMFace, came: BMVert, stop: BMVert | None, chain_edges: set
) -> tuple[list[BMFace], bool, BMVert | None]:
    """Faces around ``v`` from ``face`` (which holds edge (v, came)), unfolding away from ``came``.

    With ``stop`` (a middle chain vertex) the fan ends at the face whose far edge
    reaches ``stop``. Without (an open chain's end) it crosses an edge only while
    the unfolded angle from the chain edge stays under ``END_SHALLOW``. A chain
    edge ends it early, and so does every edge not held by exactly two visible
    faces (``_across``): the mesh border, a fin, or the edge of a hidden face.

    Returns (faces, reached, end): ``reached`` is True when a middle fan got round
    to ``stop``, False when it ended early (and always for an end fan). ``end`` is
    the far vertex of the edge an end fan stopped at once the angle reached
    ``END_SHALLOW``: that end edge leaves the chain by ``END_SHALLOW`` at least,
    so the end wall it starts never runs along the new loop. None when the fan
    ended any other way.
    """
    faces, angle = [face], 0.0
    while True:
        far, edge = _other_edge(face, v, came)
        if stop is not None:
            if far is stop:
                return faces, True, None
        else:
            angle += _corner(face, v)
            if angle >= END_SHALLOW:
                return faces, False, far
        nxt = None if edge in chain_edges else _across(edge, face)
        if nxt is None or nxt in faces:
            return faces, False, None
        faces.append(nxt)
        face, came = nxt, far


def _flood(seeds: list[BMFace], walls: set, skip: set) -> list[BMFace]:
    """``seeds`` and every visible face reached from them across edges, never across ``walls`` or into ``skip``.

    It also enters every face of an edge that more than two visible faces hold,
    so the core sees them all on that edge and makes it a border (a fin standing
    on the surface stops the slide there). Each face is visited once and each of
    its edges looked at once: linear in the faces reached.
    """
    out = list(dict.fromkeys(seeds))
    seen = skip | set(out)
    for face in out:  # grows while it is walked
        for e in face.edges:
            if e in walls:
                continue
            for nxt in e.link_faces:
                if not nxt.hide and nxt not in seen:
                    seen.add(nxt)
                    out.append(nxt)
    return out


# --- steps -----------------------------------------------------------------------


def _step_runs(away: list[Vector], points: list[Vector], closed: bool) -> list[tuple[int, int]]:
    """Step runs as (a, b): edges a .. b-1 (mod m) are the step, edges a-1 and b its flanks.

    ``away`` holds each chain edge's away direction, ``points`` the chain vertex
    positions. A run is a step when its flanks agree, every run edge differs from
    the flanks' mean, and the chain runs straight across it: every edge from
    flank a-1 to flank b stays within acos(STEP_AGREE_COS) of the chord from
    P[a-1] to P[b+1]. Without that last test a chain turning on a flat surface
    (a stair, the border of an L-shaped region) would pass as a step.

    From each left flank only the first edge that agrees with it can close a run:
    a longer run would hold that edge, which cannot differ from the flanks'
    mean. Candidates are taken shortest first, and a candidate is dropped when its
    run overlaps a taken run or one of its flanks lies in one, so flanks are
    never steps. Shortest first keeps a lip a step even when a face further out
    also turns away and could pair with it as a flank.
    """
    m, n = len(away), len(points)
    dirs = [(points[(x + 1) % n] - points[x]).normalized() for x in range(m)]

    def straight(i: int, j: int) -> bool:
        chord = (points[(j + 1) % n] - points[i % n]).normalized()
        return all(dirs[x % m].dot(chord) >= core.STEP_AGREE_COS for x in range(i, j + 1))

    candidates = []
    for i in range(m):
        for j in range(i + 1, i + m if closed else m):
            c = away[i].dot(away[j % m])
            if c >= core.STEP_AGREE_COS:
                if j > i + 1 and straight(i, j):
                    mean = (away[i] + away[j % m]).normalized()
                    if all(away[x % m].dot(mean) < core.STEP_DIFFER_COS for x in range(i + 1, j)):
                        candidates.append((i, j))
                break
            if c >= _RUN_BREAK_COS:
                break
    candidates.sort(key=lambda ij: (ij[1] - ij[0], ij[0]))
    taken, runs = set(), []
    for i, j in candidates:
        run = {x % m for x in range(i + 1, j)}
        if run & taken or i % m in taken or j % m in taken:
            continue
        taken |= run
        runs.append(((i + 1) % m, j % m))
    return sorted(runs)


def _inside(p: tuple[float, float], poly: list[tuple[float, float]], tol: float) -> bool:
    """``p`` inside the polygon (even-odd) or within ``tol`` of its boundary."""
    inside = False
    for i in range(len(poly)):
        (x0, y0), (x1, y1) = poly[i - 1], poly[i]
        dx, dy = x1 - x0, y1 - y0
        seg = dx * dx + dy * dy
        t = 0.0 if seg == 0.0 else max(0.0, min(1.0, ((p[0] - x0) * dx + (p[1] - y0) * dy) / seg))
        if math.hypot(p[0] - x0 - t * dx, p[1] - y0 - t * dy) <= tol:
            return True
        if (y0 > p[1]) != (y1 > p[1]) and p[0] < x0 + (p[1] - y0) * dx / dy:
            inside = not inside
    return inside


def _lid_path(
    start: BMVert, rail: BMEdge, center: Vector, normal: Vector, tol: float, chain: set, meets: set, chain_edges: set
) -> list[BMVert]:
    """A flank rail continued edge by edge while it stays in the lid's plane.

    The path leaves chain vertex ``start`` along ``rail``. At each vertex it takes
    the visible edge that turns least from the edge it came along, never a chain
    edge, an edge back onto the path or one to a ``chain`` vertex. It goes on along
    that edge while the turn stays within ``core.RAIL_MAX_DEV`` and the edge's far
    vertex lies within ``tol`` of the plane through ``center`` with ``normal``;
    otherwise it ends. Inside one plane the 3D turn is the developed one. It ends
    on the first vertex of ``meets`` it reaches (the other flank's path).
    """
    path = [start, rail.other_vert(start)]
    on_path = set(path)
    while path[-1] not in meets:
        x = path[-1]
        heading = x.co - path[-2].co
        best = None
        for e in x.link_edges:
            if e.hide or e in chain_edges or all(f.hide for f in e.link_faces):
                continue
            y = e.other_vert(x)
            if y in on_path or y in chain:
                continue
            turn = heading.angle(y.co - x.co, None)
            if turn is not None and (best is None or turn < best[0]):
                best = (turn, y)
        if best is None or best[0] > core.RAIL_MAX_DEV or abs((best[1].co - center).dot(normal)) > tol:
            break
        path.append(best[1])
        on_path.add(best[1])
    return path


def _step_region(
    seeds: list[BMFace], walls: set, tops: list[BMVert], corners: list[BMVert], away: Vector, normal: Vector,
    depth: float, tol: float, far: tuple[BMVert, BMVert] | None = None,
) -> list[BMFace]:
    """Visible faces flooded from ``seeds`` without crossing ``walls`` that lie under the step.

    ``tops`` are the step's chain points P_a .. P_b, ``corners`` the lid polygon.
    Seen along ``normal``, a face is kept when it overlaps the strip between P_a
    and P_b along the chain chord (a vertex lies in it within ``tol``, or the
    face spans it), no vertex lies further back across the chord, against
    ``away``, than the furthest-back chain point by more than ``tol``, and every
    vertex lies within ``depth`` of the lid plane (through the corners' mean).
    The flood only spreads from kept faces. ``walls`` hold the chain and every
    lid side that is a mesh edge: both flank paths and, where it is one, the
    lid's far edge, so the faces behind it stay real faces of the band.

    ``far`` is the lid's far side, from the end of the path at P_b to the end of
    the path at P_a, where no mesh edge joins them. A face then also needs a
    vertex short of that side, by more than ``tol``. Where the flank paths
    differ in length the far side cuts across the faces under the step, and
    ``project_step`` keeps only the pieces between the cut's own ends.
    Positions are taken relative to the corners' mean, so float32 coordinates
    far from the origin keep the lid's own precision.
    """
    center = sum((p.co for p in corners), Vector()) / len(corners)
    chord = tops[-1].co - tops[0].co
    u = (chord - normal * chord.dot(normal)).normalized()
    w = normal.cross(u)
    if w.dot(away) < 0.0:
        w.negate()
    lo, hi = (tops[0].co - center).dot(u), (tops[-1].co - center).dot(u)
    back = min((p.co - center).dot(w) for p in tops) - tol

    def flat(co: Vector) -> Vector:  # seen along the normal, in the lid's (u, w) frame
        d = co - center
        return Vector((d.dot(u), d.dot(w)))

    # The far side as (a point on it, its unit normal away from the chain), seen along the normal.
    far_side = None
    if far is not None:
        fb, fa = flat(far[0].co), flat(far[1].co)
        if (fa - fb).length > tol:
            out = (fa - fb).orthogonal().normalized()
            if out.dot(sum((flat(p.co) for p in tops), Vector((0.0, 0.0))) / len(tops) - fb) > 0.0:
                out.negate()
            far_side = (fb, out)

    def under_step(face: BMFace) -> bool:
        along = []
        for v in face.verts:
            d = v.co - center
            if abs(d.dot(normal)) > depth or d.dot(w) < back:
                return False
            along.append(d.dot(u))
        if far_side is not None and min(far_side[1].dot(flat(v.co) - far_side[0]) for v in face.verts) >= -tol:
            return False  # nothing of the face lies short of the lid's far side
        return max(along) >= lo - tol and min(along) <= hi + tol

    region, seen, queue = [], set(seeds), deque(seeds)
    while queue:
        face = queue.popleft()
        if face.hide or not under_step(face):
            continue
        region.append(face)
        for e in face.edges:
            if e in walls:
                continue
            for nxt in e.link_faces:
                if nxt not in seen:
                    seen.add(nxt)
                    queue.append(nxt)
    return sorted(region, key=lambda f: f.index)


# --- bands -----------------------------------------------------------------------


def face_triangles(bm) -> dict[int, list[tuple[int, int, int]]]:
    """The triangles the mesh shows, as vertex-index triples, by face index.

    One ``calc_loop_triangles`` over the whole mesh: compute it once per run for
    every ``build_band``, and again after an edit, which changes the faces and
    their indices.
    """
    bm.verts.index_update()
    bm.faces.index_update()
    out: dict[int, list[tuple[int, int, int]]] = {}
    for tri in bm.calc_loop_triangles():
        out.setdefault(tri[0].face.index, []).append(tuple(lp.vert.index for lp in tri))
    return out


def build_band(
    bm, src: ChainSrc, side: int, tris: dict[int, list[tuple[int, int, int]]] | None = None
) -> tuple[BandBuild | None, str | None]:
    """The band of ``src`` on ``side``, or (None, reason) when the chain cannot be cut there.

    ``side=+1`` takes the faces that run each chain edge in chain order
    (``loop.vert is a and loop.link_loop_next.vert is b``), ``side=-1`` the
    others. Hidden faces never join the band. ``tris`` is ``face_triangles(bm)``
    for the mesh as it is now; without it the band computes its own.

    The band is a flood from the side and wedge faces across every edge but the
    chain's, once per call and linear in the faces reached. It leaves out the
    faces a lid stands for. Round an open chain's end it may reach the other
    side: the end walls keep the traces off it. The end edges are where the end
    wedges stop (see ``_fan``); an end whose wedge ends at the border first, or
    a closed chain, has none. The reasons are:

    - ``NO_SIDE_FACE`` and ``SEVERAL_SIDE_FACES`` for a chain edge;
    - ``MIXED_SECTORS`` when a chain vertex's two side faces lie on different
      sides of the chain around it (inconsistent winding);
    - ``NO_FLANK_RAIL`` when a flank rail ends on the chain, or both rails end on
      one vertex, so there is no lid polygon;
    - ``WEDGE_INTERRUPTED`` when the finished band cannot develop a chain
      vertex's wedge, or an end wall cannot leave its end vertex's wedge
      (``core.wedges`` raises).
    """
    bm.verts.index_update()
    bm.faces.index_update()
    bm.faces.ensure_lookup_table()
    chain, closed = src.verts, src.closed
    n = len(chain)
    m = n if closed else n - 1

    chain_edges, side_faces = [], []
    for i in range(m):
        a, b = chain[i], chain[(i + 1) % n]
        edge = bm.edges.get((a, b))
        start = a if side > 0 else b
        faces = [] if edge is None else [lp.face for lp in edge.link_loops if lp.vert is start and not lp.face.hide]
        if not faces:
            return None, NO_SIDE_FACE
        if len(faces) > 1:  # a non-manifold edge, or neighbours with flipped winding
            return None, SEVERAL_SIDE_FACES
        chain_edges.append(edge)
        side_faces.append(faces[0])
    walls = set(chain_edges)

    # Wedge faces per chain vertex, in the core's sweep order: from the outgoing
    # side face round to the incoming one (an open chain's ends: to the band border).
    # A middle fan that gets round must end on the incoming side face; a fan that
    # ends early is judged once the lids are in, since a lid may bridge the gap.
    wedges, end_edges = [], [None, None]
    for k in range(n):
        if closed or 0 < k < n - 1:
            fan, reached, _end = _fan(chain[k], side_faces[k], chain[(k + 1) % n], chain[k - 1], walls)
            if reached and fan[-1] is not side_faces[k - 1]:
                return None, MIXED_SECTORS
        elif k == 0:
            fan, _reached, end_edges[0] = _fan(chain[0], side_faces[0], chain[1], None, walls)
        else:
            fan, _reached, end_edges[1] = _fan(chain[k], side_faces[k - 1], chain[k - 1], None, walls)
        wedges.append(fan)

    away = [
        _normal(f).cross((chain[(i + 1) % n].co - chain[i].co) * side).normalized()
        for i, f in enumerate(side_faces)
    ]
    chain_set = set(chain)
    side_ids = [f.index for f in side_faces]
    lids: dict[int, tuple[int, ...]] = {}
    lid_verts: list[BMVert] = []
    replaced: set[BMFace] = set()
    steps = []
    for a, b in _step_runs(away, [v.co for v in chain], closed):
        span = list(range(a, b if b > a else b + n))              # step edges, unwrapped
        tops = [chain[x % n] for x in span] + [chain[b]]         # P_a .. P_b
        flank_a, flank_b = side_faces[a - 1], side_faces[b]
        r_a, rail_a = _other_edge(flank_a, chain[a], chain[a - 1])
        r_b, rail_b = _other_edge(flank_b, chain[b], chain[(b + 1) % n])
        if r_a in chain_set or r_b in chain_set or r_a is r_b:
            return None, NO_FLANK_RAIL

        n_a, n_b = _normal(flank_a), _normal(flank_b)
        # A projection direction has no sign: never let opposed flank normals cancel.
        normal = (n_a + n_b if n_a.dot(n_b) >= 0.0 else n_a - n_b).normalized()
        # The lid runs on along both flank rail paths while they stay in the plane of its first
        # corners. Its tolerances keep to those corners: the run-on makes the lid longer, not coarser.
        first = tops + [r_b, r_a]
        center = sum((p.co for p in first), Vector()) / len(first)
        extent = max((p.co - q.co).length for p in first for q in first)
        tol = max(_tolerance(LID_TOL, PROJECT_STEPS, [p.co for p in first]), STEP_REL_TOL * extent)
        path_b = _lid_path(chain[b], rail_b, center, normal, tol, chain_set, set(), walls)
        path_a = _lid_path(chain[a], rail_a, center, normal, tol, chain_set, set(path_b), walls)
        if path_a[-1] in path_b:  # the paths meet: the lid closes on that vertex, held by path a
            path_b = path_b[: path_b.index(path_a[-1])]
        corners = tops + path_b[1:] + path_a[:0:-1]              # (P_a .. P_b, path_b .., .. path_a)
        lid = -(len(steps) + 1)
        lids[lid] = tuple(v.index for v in corners)
        lid_verts += corners
        for x in span:
            side_ids[x % n] = lid

        # The lid covers the step's side faces and every wedge face between the flank rails.
        seeds = [side_faces[x % n] for x in span]
        seeds += [f for f in wedges[a] if f is not flank_a]
        seeds += [f for x in span[1:] for f in wedges[x % n]]
        seeds += [f for f in wedges[b] if f is not flank_b]
        seeds = list(dict.fromkeys(seeds))
        replaced.update(seeds)

        # The step may reach as deep under the lid as the lid reaches along its flanks.
        depth = 2.0 * max((path_a[-1].co - chain[a].co).length, (path_b[-1].co - chain[b].co).length)
        tol = max(_tolerance(LID_TOL, PROJECT_STEPS, [p.co for p in corners]), STEP_REL_TOL * extent)
        sides = {_edge(p, q) for p, q in zip(corners, corners[1:] + corners[:1])} - {None}
        far = None if _edge(path_b[-1], path_a[-1]) is not None else (path_b[-1], path_a[-1])
        region = _step_region(seeds, walls | sides, tops, corners, away[a - 1] + away[b], normal, depth, tol, far)
        steps.append(StepSpan(lid, a, b, normal, region, extent))

    # Every face reachable on the side, but the ones a lid stands for. The side and
    # wedge faces seed it, so a flank face the region's overlap test also caught stays.
    skip = replaced.union(*(step.region for step in steps))
    seeds = [f for f in side_faces + [f for fan in wedges for f in fan] if f not in replaced]
    real = {f.index: f for f in _flood(seeds, walls, skip)}
    bm_verts = {v.index: v for v in chain}
    bm_verts.update((v.index, v) for f in real.values() for v in f.verts)
    bm_verts.update((v.index, v) for v in lid_verts)
    faces = {i: tuple(v.index for v in f.verts) for i, f in real.items()}
    faces.update(lids)
    # Real faces keep the triangles the mesh shows (Review Focus 5); lids fall back to the core's own.
    if tris is None:
        tris = face_triangles(bm)
    band = core.Band(
        verts={i: tuple(v.co) for i, v in bm_verts.items()}, faces=faces, chain=[v.index for v in chain],
        closed=closed, side_faces=side_ids, tris={f: tris[f] for f in real if f in tris},
        end_edges=(None, None) if closed else tuple(None if v is None else v.index for v in end_edges))
    try:
        core.wedges(band)
    except ValueError:
        return None, WEDGE_INTERRUPTED
    return BandBuild(
        band=band, chain=list(chain), faces=real, steps=steps, chain_index=src.index, side=side, verts=bm_verts
    ), None


# --- step projection -------------------------------------------------------------

def _tolerance(floor: float, steps: int, points) -> float:
    """``floor``, or ``steps`` float32 steps at the largest coordinate of ``points``, whichever is larger."""
    return max(floor, steps * _F32_STEP * max(abs(c) for p in points for c in p))


class _Event(NamedTuple):
    """A boundary point of a face section.

    ``on`` is the element it lies on: the vertex where the sheet meets one, else
    the edge it crosses. ``edge`` is that edge, or for a vertex the loop edge leaving it.
    """

    co: Vector
    edge: BMEdge
    on: BMVert | BMEdge


class _Sheet:
    """The plane through ``origin`` with unit ``normal``, cut through faces one at a time.

    Vertex distances and edge crossings are worked out once each, the crossing
    from the edge's first vertex: two faces sharing an edge get the very same
    point, whatever direction their loops run it in.
    """

    def __init__(self, origin: Vector, normal: Vector, tol: float):
        self.origin, self.normal, self.tol = origin, normal, tol
        self._dist: dict[BMVert, float] = {}
        self._cross: dict[BMEdge, Vector] = {}

    def dist(self, v: BMVert) -> float:
        d = self._dist.get(v)
        if d is None:
            d = self._dist[v] = (v.co - self.origin).dot(self.normal)
        return d

    def side(self, v: BMVert) -> int:
        d = self.dist(v)
        return 0 if abs(d) <= self.tol else (1 if d > 0.0 else -1)

    def crossing(self, e: BMEdge) -> Vector:
        co = self._cross.get(e)
        if co is None:
            v0, v1 = e.verts
            d0, d1 = self.dist(v0), self.dist(v1)
            co = self._cross[e] = v0.co.lerp(v1.co, d0 / (d0 - d1))
        return co

    def section(self, face: BMFace) -> list[tuple[_Event, _Event]]:
        """The pieces of ``face`` on the sheet.

        The boundary points, sorted along the sheet's line through the face, pair
        up into pieces: a pair is kept when it runs along one of the face's edges
        or its midpoint lies inside the face (a concave face can give several pieces).
        """
        face_normal = _normal(face)
        line = self.normal.cross(face_normal)
        if line.length <= core.EPS:  # the face lies parallel to the sheet
            return []
        loops = list(face.loops)
        sides = [self.side(lp.vert) for lp in loops]
        events: list[_Event] = []
        for i, lp in enumerate(loops):
            if sides[i] == 0:
                events.append(_Event(lp.vert.co.copy(), lp.edge, lp.vert))
            elif sides[i] * sides[(i + 1) % len(loops)] < 0:
                events.append(_Event(self.crossing(lp.edge), lp.edge, lp.edge))
        events.sort(key=lambda ev: ev.co.dot(line))

        u = face_normal.orthogonal().normalized()
        w = face_normal.cross(u)
        poly = [(v.co.dot(u), v.co.dot(w)) for v in face.verts]
        pieces = []
        for p, q in zip(events, events[1:]):
            if (q.co - p.co).length <= self.tol:
                continue
            # Two vertex points whose loop edges meet run along that face edge.
            vertices = isinstance(p.on, BMVert) and isinstance(q.on, BMVert)
            along_edge = vertices and (q.on in p.edge.verts or p.on in q.edge.verts)
            mid = (p.co + q.co) * 0.5
            if along_edge or _inside((mid.dot(u), mid.dot(w)), poly, 0.0):
                pieces.append((p, q))
        return pieces


def project_step(
    span: StepSpan, a: Vector, b: Vector, a_on: BMVert | BMEdge | None = None, b_on: BMVert | BMEdge | None = None
) -> list[tuple[Vector, BMEdge | None, BMFace]] | None:
    """The cut from ``a`` to ``b`` across a step, laid on the real faces under its lid.

    The sheet is the plane through ``a`` and ``b`` that holds ``span.normal``. Its
    pieces through the ``span.region`` faces whose projection onto ``b - a`` lies
    in [0, |b - a|] are chained from ``a`` to ``b``; where several pieces start at
    one point, the one heading furthest toward ``b`` goes first.

    Points match when they lie on the same vertex or edge (``a_on`` and ``b_on``
    give the ones ``a`` and ``b`` lie on, when known), else within the largest of
    ``PROJECT_TOL``, ``PROJECT_STEPS`` float32 steps and ``STEP_REL_TOL`` of the
    lid extent. Pieces meet exactly at shared edges and vertices.

    Each entry is (point, the edge it lies on, the face the next piece lies in).
    A point on a vertex gives one of that vertex's edges; the last entry, ``b``,
    gives the face its piece lies in. None when the pieces leave a gap, or when
    ``b - a`` runs along the normal.
    """
    tol = max(_tolerance(PROJECT_TOL, PROJECT_STEPS, (a, b)), STEP_REL_TOL * span.extent)
    ab = b - a
    length = ab.length
    across = ab.cross(span.normal)
    if length <= tol or across.length <= core.EPS * length:
        return None
    ahead = ab / length
    sheet = _Sheet(a, across.normalized(), _tolerance(WELD_TOL, WELD_STEPS, (a, b)))
    pieces = [
        (p, q, face)
        for face in span.region
        for p, q in sheet.section(face)
        if all(-tol <= (x.co - a).dot(ahead) <= length + tol for x in (p, q))
    ]

    def meets(x: _Event, here: _Event) -> bool:
        return (here.on is not None and x.on is here.on) or (x.co - here.co).length <= tol

    path, here, used = [], _Event(a, None, a_on), set()
    while not ((b_on is not None and here.on is b_on) or (here.co - b).length <= tol):
        best = None
        for i, (p, q, face) in enumerate(pieces):
            if i in used:
                continue
            for x, y in ((p, q), (q, p)):
                gain = (y.co - a).dot(ahead)
                if meets(x, here) and (best is None or gain > best[0]):
                    best = (gain, i, x, y, face)
        if best is None:
            return None
        _, i, x, here, face = best
        used.add(i)
        path.append((x.co if path else a, x.edge, face))
    path.append((b, here.edge, face))
    return path


# --- applying a cut ----------------------------------------------------------------


@dataclass
class _Slot:
    """A vertex of the new loop to be: an existing vertex, a point on an edge, or a point inside a face."""

    vert: BMVert | None = None
    edge: BMEdge | None = None
    co: Vector | None = None

    @property
    def inside(self) -> bool:
        return self.vert is None and self.edge is None

    def element(self) -> BMVert | BMEdge | None:
        """The vertex or edge the slot lies on; None inside a face."""
        return self.vert if self.vert is not None else self.edge

    def position(self) -> Vector:
        return self.vert.co if self.vert is not None else self.co


def _edge_slot(edge: BMEdge, co: Vector, weld: float) -> _Slot:
    """The slot for point ``co`` on ``edge``: an end vertex within ``weld`` of it is reused."""
    for v in edge.verts:
        if (v.co - co).length <= weld:
            return _Slot(vert=v)
    return _Slot(edge=edge, co=co)


def _band_edge_faces(band: core.Band) -> dict[tuple[int, int], set[int]]:
    """Band faces on each edge, keyed by sorted vertex ids."""
    out: dict[tuple[int, int], set[int]] = {}
    for f, loop in band.faces.items():
        for i in range(len(loop)):
            a, b = loop[i - 1], loop[i]
            out.setdefault((a, b) if a < b else (b, a), set()).add(f)
    return out


def _split_edges(slots: list[_Slot], made: list[BMVert | None], weld: float) -> None:
    """Split each edge at its slots' points into ``made``; points within ``weld`` of each other share a vertex.

    Points go far-to-near from the edge's first vertex: each split leaves the near
    part as the returned edge, so the next factor is taken on that part.
    """
    on_edge: dict[BMEdge, list[int]] = {}
    for i, slot in enumerate(slots):
        if slot.edge is not None:
            on_edge.setdefault(slot.edge, []).append(i)
    for edge, ids in on_edge.items():
        v0, v1 = edge.verts
        axis = v1.co - v0.co
        span = axis.length
        params = sorted((((slots[i].co - v0.co).dot(axis) / (span * span), i) for i in ids), reverse=True)
        part, far, last = edge, 1.0, None
        for t, i in params:
            if last is None or (far - t) * span > weld:
                part, last = bmesh.utils.edge_split(part, v0, t / far)
                last.co = slots[i].co
                far = t
            made[i] = last


def _gap(face: BMFace, p: Vector) -> float:
    """Distance from ``p`` to the face's triangles it projects into; inf when it projects into none."""
    pts = [v.co for v in face.verts]
    best = math.inf
    for i, j, k in geometry.tessellate_polygon([pts]):
        hit = geometry.intersect_point_tri(p, pts[i], pts[j], pts[k])
        if hit is not None:
            best = min(best, (hit - p).length)
    return best


def _face_holding(va: BMVert, vb: BMVert, probe: Vector) -> BMFace | None:
    """The visible face holding both vertices; of several, the one nearest ``probe``, a point of the piece."""
    faces = [f for f in va.link_faces if not f.hide and vb in f.verts]
    if len(faces) < 2:
        return faces[0] if faces else None
    return min(faces, key=lambda f: _gap(f, probe))


def _split_face(va: BMVert, vb: BMVert, coords: list[Vector]) -> list[BMVert] | None:
    """Split the face holding ``va`` and ``vb`` along va -> coords -> vb; the vertices made at ``coords``.

    ``bmesh.utils.face_split`` interpolates the new vertices' loop data (UVs,
    colours) and vertex data from a copy of the face it splits, then removes the
    copy; ``bmesh.utils.edge_split`` does so along the edge.

    None when no face holds both vertices or bmesh refuses the split; the face is
    then left as it was.
    """
    face = _face_holding(va, vb, coords[0] if coords else (va.co + vb.co) * 0.5)
    if face is None:
        return None
    before = set(face.verts)
    try:
        new_face, _ = bmesh.utils.face_split(face, va, vb, coords=coords)
    except ValueError:
        return None
    fresh = [v for v in new_face.verts if v not in before]
    return [min(fresh, key=lambda v: (v.co - c).length_squared) for c in coords]


def _edge(va: BMVert, vb: BMVert) -> BMEdge | None:
    """The edge joining ``va`` and ``vb``, or None."""
    return next((e for e in va.link_edges if vb in e.verts), None)


class _LoopPlan(NamedTuple):
    """The new loop of one cut, before any edit.

    ``point_slot[i]`` is the slot of ``cut.points[i]`` (None inside a lid);
    ``nodes`` lists the loop's slots in order, projected step points included (a
    closed loop does not repeat its first); ``runs`` are (vertex or edge slot,
    face slots between, vertex or edge slot), each one face split.
    """

    slots: list[_Slot]
    point_slot: list[int | None]
    nodes: list[int]
    runs: list[tuple[int, list[int], int]]


def _plan_loop(build: BandBuild, cut: core.Cut, weld: float) -> _LoopPlan:
    """Lay ``cut`` (with points) onto the mesh elements it lands on, as ``apply_cut`` builds it.

    Raises ``ValueError`` when the cut cannot be built (see ``apply_cut``).
    """
    band = build.band
    verts = build.verts
    steps = {s.lid: s for s in build.steps}

    def holders(pt: core.SurfacePoint) -> set[int]:
        if pt.kind == "vert":
            return set(build.vert_faces.get(pt.vert, ()))
        if pt.kind == "edge":
            return build.edge_faces.get(pt.edge, set())
        return {pt.face}

    slots: list[_Slot] = []

    def add(slot: _Slot) -> int:
        slots.append(slot)
        return len(slots) - 1

    point_slot: list[int | None] = []  # None for a point inside a lid: it is not on the mesh
    for pt in cut.points:
        if pt.kind == "vert":
            point_slot.append(add(_Slot(vert=verts[pt.vert])))
        elif pt.kind == "edge":
            edge = _edge(verts[pt.edge[0]], verts[pt.edge[1]])
            if edge is None:
                raise ValueError(NO_CUT_EDGE)
            point_slot.append(add(_edge_slot(edge, Vector(pt.co), weld)))
        else:
            point_slot.append(add(_Slot(co=Vector(pt.co))) if pt.face >= 0 else None)

    kept = [i for i, s in enumerate(point_slot) if s is not None]
    if not kept:
        raise ValueError(LOOSE_LOOP)
    pairs = list(zip(kept, kept[1:]))
    if band.closed and len(kept) > 1:
        pairs.append((kept[-1], kept[0]))
    nodes: list[int] = []  # the loop's slots in order
    for i, j in pairs:
        nodes.append(point_slot[i])
        common = holders(cut.points[i]) & holders(cut.points[j])
        if not common:
            raise ValueError(NO_SHARED_FACE)
        if all(f < 0 for f in common):
            si, sj = slots[point_slot[i]], slots[point_slot[j]]
            path = project_step(steps[min(common)], si.position(), sj.position(), si.element(), sj.element())
            if path is None:
                raise ValueError(STEP_GAP)
            nodes += [add(_Slot(co=co) if e is None else _edge_slot(e, co, weld)) for co, e, _face in path[1:-1]]
    if not band.closed or not pairs:
        nodes.append(point_slot[kept[-1]])

    # Runs between vertex and edge points; a closed loop starts on one. A face split
    # needs two separate vertices, so the loop needs two such points at least, and
    # a run through a face must not come back to where it started.
    def apart(s: int, t: int) -> bool:
        return (slots[s].position() - slots[t].position()).length > weld

    firm = [s for s in nodes if not slots[s].inside]
    if not firm and len({cut.points[i].face for i in kept}) == 1:  # a ring inside one face, as in an n-gon cap
        raise ValueError(INSIDE_ONE_FACE)
    if not firm or not any(apart(s, firm[0]) for s in firm[1:]):
        raise ValueError(LOOSE_LOOP)
    start = nodes.index(firm[0])
    order = nodes[start:] + nodes[: start + 1] if band.closed else nodes
    if slots[order[0]].inside or slots[order[-1]].inside:
        raise ValueError(LOOSE_LOOP)
    runs, first, inner = [], order[0], []
    for s in order[1:]:
        if slots[s].inside:
            inner.append(s)
        else:
            if inner and not apart(first, s):
                raise ValueError(LOOSE_LOOP)
            runs.append((first, inner, s))
            first, inner = s, []
    return _LoopPlan(slots, point_slot, nodes, runs)


def apply_cut(bm, build: BandBuild, cut: core.Cut, slider: core.Slider | None = None) -> Applied:
    """Build ``cut`` into the mesh; the band must be unchanged since ``build_band``.

    ``slider`` is the ``core.Slider`` over ``build.band`` that solved ``cut``, when
    there is one: the end paths come from its surface instead of a new one.

    Vertex points reuse their vertex. Edge points split their edge, several on one
    edge far-to-near. Each run of the loop from one vertex or edge point to the
    next splits the face that holds it, with the face points between as interior
    coordinates; where the run's ends are already joined by an edge, that edge
    is the run. Points inside a lid are dropped, and a run whose ends share only a
    lid becomes its projection onto the step's region (``project_step``), one face
    split per projected piece. Connectors (from a chain vertex, or from where a
    rail path ends) split the face holding both of their vertices once the loop
    is in. A complete cut also gets its strip faces (``_strip_faces``), none when
    an open end has nothing to bound the strip: no end path, and its loop end not
    on the band border (UV Stripe then skips the strip).

    Raises ``ValueError`` before touching the mesh when the cut cannot be built,
    among others when the loop does not run between two separate vertices or
    edges. Once editing has begun nothing is raised: whatever cannot be built is
    left out and named in ``Applied.failures``.
    """
    band = build.band
    if not cut.points:
        return Applied([], [], [None] * len(cut.anchors))
    weld = build.weld
    slots, point_slot, nodes, runs = _plan_loop(build, cut, weld)
    connectors = [
        (build.verts[vid], point_slot[idx])
        for vid, idx in cut.connectors
        if vid in build.verts and point_slot[idx] is not None
    ]
    end_paths = _end_paths(build, slider)

    # Edit the mesh. From here on nothing raises: a part that cannot be built is
    # left out and named in ``failures``, and every edit already made is whole.
    made: list[BMVert | None] = [s.vert for s in slots]
    failures: list[str] = []
    halves: list[BMFace] = []  # both faces of every split, for ``_strip_faces``
    try:
        _split_edges(slots, made, weld)
        for a, inner, b in runs:
            va, vb = made[a], made[b]
            if va is vb or (not inner and bm.edges.get((va, vb)) is not None):
                if inner:  # two points welded onto one vertex: the run has no face to split
                    failures.append(PIECE_FAILED)
                continue
            fresh = _split_face(va, vb, [slots[s].co for s in inner])
            if fresh is None:
                failures.append(PIECE_FAILED)
                continue
            for s, v in zip(inner, fresh):
                made[s] = v
            halves += _faces_of_edge(va, fresh[0] if fresh else vb)
        for cv, s in connectors:
            pv = made[s]
            if pv is None or pv is cv or bm.edges.get((cv, pv)) is not None:
                continue
            if _split_face(cv, pv, []) is None:
                failures.append(CONNECTOR_FAILED)
            else:
                halves += _faces_of_edge(cv, pv)
    except (ValueError, ReferenceError) as exc:  # bmesh refused an edit; the ones before it stand
        failures.append(str(exc))

    loop_verts: list[BMVert] = []
    for s in nodes:
        v = made[s]
        if v is not None and (not loop_verts or loop_verts[-1] is not v):
            loop_verts.append(v)
    if band.closed and len(loop_verts) > 1 and loop_verts[0] is loop_verts[-1]:
        loop_verts.pop()
    # A closed loop also joins its last vertex to its first, unless that is the edge it already has.
    ends = loop_verts[1:] + (loop_verts[:1] if band.closed and len(loop_verts) > 2 else [])
    found = [bm.edges.get(pair) for pair in zip(loop_verts, ends)]
    loop_edges = [e for e in found if e is not None]
    if len(loop_edges) < len(found) and not failures:
        failures.append(LOOP_GAP)
    index: dict[BMVert, int] = {}
    for i, v in enumerate(loop_verts):
        index.setdefault(v, i)
    anchors = [None if a is None or point_slot[a] is None else index.get(made[point_slot[a]]) for a in cut.anchors]
    strip_faces = []
    if not failures:
        # An open end bounds the strip with its end path up to the loop's end, or with
        # the band border its loop end lies on; otherwise the strip is not bounded there.
        barrier, bounded = list(loop_edges), True
        for k, path in zip((0, -1), [] if band.closed else end_paths):
            if path and anchors[k] is not None:
                barrier += _wall_edges(path, loop_verts[anchors[k]])
            elif anchors[k] is None or not _on_band_border(build, cut.points[cut.anchors[k]]):
                bounded = False
        strip_faces = _strip_faces(build, barrier, halves) if bounded else []
    return Applied(loop_edges, loop_verts, anchors, strip_faces=strip_faces, failures=failures)


def _on_band_border(build: BandBuild, pt: core.SurfacePoint) -> bool:
    """Whether ``pt`` lies on the band's border: on an edge that one band face holds, or more than two."""
    if pt.kind == "edge":
        return len(build.edge_faces.get(pt.edge, ())) != 2
    if pt.kind == "vert":
        for f in build.vert_faces.get(pt.vert, ()):
            loop = build.band.faces[f]
            i = loop.index(pt.vert)
            for w in (loop[i - 1], loop[(i + 1) % len(loop)]):
                if len(build.edge_faces.get((min(pt.vert, w), max(pt.vert, w)), ())) != 2:
                    return True
    return False


def _faces_of_edge(va: BMVert, vb: BMVert) -> list[BMFace]:
    """The faces of the edge joining ``va`` and ``vb``; none without such an edge."""
    edge = _edge(va, vb)
    return [] if edge is None else list(edge.link_faces)


def _end_paths(build: BandBuild, slider: core.Slider | None = None) -> list[list[BMVert]]:
    """The vertices of the paths an open chain's start and end slide along (``core.end_paths``).

    Each runs from its chain end out along the end wall; empty without one. Taken
    before the cut is built, while the band's vertex ids still name the mesh's
    vertices; from ``slider``'s surface when given.
    """
    if build.band.closed or build.band.end_edges == (None, None):
        return [[], []]
    paths = core.end_paths(build.band) if slider is None else slider.end_paths()
    return [[build.verts[i] for i in path] for path in paths]


def _wall_edges(wall: list[BMVert], end: BMVert) -> list[BMEdge]:
    """The edges along ``wall``, an end path, from the chain end to the new loop's ``end``, once the cut is in.

    The loop's end lies on the path: on a path vertex, or where it split a path
    edge, which then leads on to ``end`` instead of to the next path vertex.
    """
    out, here = [], wall[0]
    for nxt in wall[1:]:
        if here is end:
            break
        edge = _edge(here, nxt)
        if edge is None:
            edge = _edge(here, end)
            if edge is not None:
                out.append(edge)
            break
        out.append(edge)
        here = nxt
    return out


def _strip_faces(build: BandBuild, barrier: list[BMEdge], halves: list[BMFace]) -> list[BMFace]:
    """The faces between the chain and its new loop, once the cut is in.

    A flood fill from the side faces of the chain edges, which crosses no chain
    edge and no ``barrier`` edge: the new loop's, and at an open chain's ends the
    end paths' up to the loop's ends. It only enters faces the cut could reach:
    the band's real faces, the faces under its lids and both faces of every
    split. The band runs on round an open chain's end, the end paths keep the
    fill from leaking into the faces beyond the strip's ends. Nor does it cross an
    edge that more than two visible faces hold: a fin is no strip face.
    """
    chain, n = build.chain, len(build.chain)
    walls, seeds = set(barrier), []
    for i in range(n if build.band.closed else n - 1):
        a, b = chain[i], chain[(i + 1) % n]
        edge = _edge(a, b)
        if edge is None:
            continue
        walls.add(edge)
        start = a if build.side > 0 else b
        seeds += [lp.face for lp in edge.link_loops if lp.vert is start and not lp.face.hide]
    reach = {*build.faces.values(), *(f for step in build.steps for f in step.region), *halves}
    seeds = [f for f in dict.fromkeys(seeds) if f in reach]
    out, seen, queue = [], set(seeds), deque(seeds)
    while queue:
        face = queue.popleft()
        out.append(face)
        for e in face.edges:
            if e in walls or sum(not f.hide for f in e.link_faces) > 2:
                continue
            for nxt in e.link_faces:
                if nxt in reach and nxt not in seen:
                    seen.add(nxt)
                    queue.append(nxt)
    return out


def _side_path(faces: list[BMFace], start: BMVert, end: BMVert, walls: set[BMEdge]) -> list[BMVert]:
    """The vertices strictly between ``start`` and ``end`` along the border of ``faces``, off ``walls``.

    Empty when ``start`` is ``end``, or when the border does not lead from one to
    the other in a single path.
    """
    count = Counter(e for f in faces for e in f.edges)
    border = {e for e, c in count.items() if c == 1 and e not in walls}
    between, came, here = [], None, start
    while here is not end:
        ahead = [e for e in here.link_edges if e in border and e is not came]
        if len(ahead) != 1 or len(between) >= len(border):
            return []
        came = ahead[0]
        here = came.other_vert(here)
        if here is not end:
            between.append(here)
    return between


def stripe_for(build: BandBuild, applied: Applied, width: float) -> tuple[uv_stripe_core.Strip, dict[int, BMFace]]:
    """The UV Stripe strip of a complete cut, with its faces by id.

    The chain is the near boundary (v = 0) and the new loop the far one (v =
    ``width``, the width the cut was built at). Each chain vertex with an anchor
    makes a rung; the faces round a chain vertex without one (inside a lid span)
    are left to the core's interior fill. An open chain's sides are the strip's
    border from each chain end to the new loop's end, off the chain and the loop.
    A closed chain's anchors may start mid-way round the new loop (a collapsed or
    welded seam, e.g. [2, 0, 1, 2]): its near and far loops are rotated so the
    rungs ascend along both (``uv_stripe_core.ascending_rungs``).

    Ids are ``BMVert.index`` and ``BMFace.index``, which must be current. Raises
    ``ValueError`` when the strip cannot be laid out: no strip faces, no length,
    a new loop through one vertex twice, rungs no rotation puts in order, or a
    layout ``uv_stripe_core.stripe_uvs`` rejects (tried here, before any UV is
    written, so the caller can skip just this strip).
    """
    faces = {f.index: f for f in applied.strip_faces}
    if not faces:
        raise ValueError(NO_STRIP_FACES)
    rungs = [(k, a) for k, a in enumerate(applied.anchors) if a is not None]
    if not rungs:
        raise ValueError(NO_STRIP_LENGTH)
    if len(set(applied.loop_verts)) < len(applied.loop_verts):
        raise ValueError(LOOP_REVISITS)
    chain, loop, closed = build.chain, applied.loop_verts, build.band.closed
    sides = ([], [])
    if not closed:
        chain_edges = [_edge(a, b) for a, b in zip(chain, chain[1:])]
        walls = {*applied.loop_edges, *(e for e in chain_edges if e is not None)}
        sides = tuple(
            [v.index for v in _side_path(applied.strip_faces, a, b, walls)]
            for a, b in ((chain[0], loop[0]), (chain[-1], loop[-1]))
        )
    verts = {v.index: tuple(v.co) for v in (*chain, *loop)}
    verts.update((v.index, tuple(v.co)) for f in faces.values() for v in f.verts)
    strip = uv_stripe_core.Strip(
        verts=verts,
        faces={i: tuple(v.index for v in f.verts) for i, f in faces.items()},
        near=[v.index for v in chain],
        far=[v.index for v in loop],
        rungs=rungs,
        closed=closed,
        height=width,
        sides=sides,
    )
    strip = uv_stripe_core.ascending_rungs(strip)
    if uv_stripe_core.strip_length(strip) <= core.EPS:  # raises ValueError for rungs out of order
        raise ValueError(NO_STRIP_LENGTH)
    uv_stripe_core.stripe_uvs(strip)
    return strip, faces


# --- modal preview and snapping ----------------------------------------------------


def preview_layers(builds: list[BandBuild], cuts: list[core.Cut]) -> tuple[list[Vector], list[Vector], bool]:
    """What ``apply_cut`` would build from each (build, cut), for the viewport, in object space.

    Returns (the loop's segments as a flat list of endpoint pairs, the new
    vertices' points, whether any cut is clamped). The loop is ``apply_cut``'s own
    plan: points inside a lid are dropped and each lid piece is replaced by its
    ``project_step`` points. Points on an existing vertex are not new vertices; a
    segment no longer than the weld tolerance joins points that share one vertex
    and is left out. A cut ``apply_cut`` would refuse (``ValueError``) draws nothing.
    """
    segs: list[Vector] = []
    points: list[Vector] = []
    for build, cut in zip(builds, cuts):
        if not cut.points:
            continue
        weld = build.weld
        try:
            plan = _plan_loop(build, cut, weld)
        except ValueError:
            continue
        loop = [plan.slots[s] for s in plan.nodes]
        cos = [slot.position().copy() for slot in loop]
        ends = cos[1:] + (cos[:1] if build.band.closed and len(cos) > 2 else [])
        for p, q in zip(cos, ends):
            if (q - p).length > weld:
                segs += [p, q]
        points += [slot.co.copy() for slot in loop if slot.vert is None]
    return segs, points, any(cut.clamped for cut in cuts)


def snap_candidates(builds: list[BandBuild]) -> list[tuple[BMVert, int, int]]:
    """The vertices the new loop can be snapped to, as (vertex, chain index, side), once per build.

    These are the vertices of the band's real faces, whose edges also make up the
    end walls an open chain's ends slide along, and of the faces under its lids.
    Chain vertices are left out: the loop reaches them only at width 0.
    """
    out = []
    for build in builds:
        seen = set(build.chain)
        for face in [*build.faces.values(), *(f for step in build.steps for f in step.region)]:
            for v in face.verts:
                if v not in seen:
                    seen.add(v)
                    out.append((v, build.chain_index, build.side))
    return out


def snap_target(build: BandBuild, v: BMVert) -> core.SurfacePoint | None:
    """The point of ``build``'s band that the new loop must reach to pass through ``v``.

    A vertex of a band face is itself. A vertex only under a lid stands for its
    projection along the step's normal onto the lid: a cut through that point is
    projected onto the step's faces through ``v``. None for any other vertex.
    """
    band = build.band
    holder = next(iter(build.vert_faces.get(v.index, ())), None)
    if holder is not None:
        return core.SurfacePoint(kind="vert", face=holder, co=tuple(v.co), vert=v.index)
    for step in build.steps:
        if any(v in f.verts for f in step.region):
            corners = [Vector(band.verts[i]) for i in band.faces[step.lid]]
            center = sum(corners, Vector()) / len(corners)
            hit = geometry.intersect_line_plane(v.co, v.co + step.normal, center, geometry.normal(corners))
            if hit is not None:
                return core.SurfacePoint(kind="face", face=step.lid, co=tuple(hit))
    return None
