"""Edge Slide bridge: from the edit mesh to core bands, and core cuts back onto it.

``utils/edge_slide_core`` knows nothing about bpy. This module turns the
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

In the destructive mode ``Relay`` passes a slide on from a row of existing edges
the new loop comes to lie on (``relay_chain``) to that row's own band.
"""

import math
from collections import Counter, deque
from dataclasses import dataclass, field, replace
from functools import cached_property
from typing import NamedTuple

import bmesh
from bmesh.types import BMEdge, BMFace, BMLoop, BMVert
from mathutils import Vector, geometry

from ..utils import edge_slide_core as core
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
INSIDE_ONE_FACE = "the loop lies inside one face; use Inset"
NO_SHARED_FACE = "consecutive new loop points share no face"
NO_CUT_EDGE = "new loop point on an edge the mesh does not have"
PIECE_FAILED = "a piece of the new loop could not be cut into its face"
CONNECTOR_FAILED = "a connecting edge could not be cut into its face"
LOOP_GAP = "the new loop has a gap"
NO_STRIP_FACES = "no faces between the chain and the new loop"
NO_STRIP_LENGTH = "the strip between the chain and the new loop has no length"
RING_NO_CHAIN = "a ring with no chain of its own has no strip"
LOOP_REVISITS = "the new loop passes through one vertex twice"
PIECE_OPEN_SIDE = "a piece of the new loop has no edge back to its chain where the loop opens"
PIECES_SHARE_FACES = "pieces of the new loop share strip faces"
PIECE_CHAIN_REVISITS = "a piece of the new loop runs along its chain onto the vertex it started from"
LOOP_CROSSES = "the new loop crosses itself, or a connecting edge leaves its face"
RING_REVERSED = "the new loop inside one face encloses nothing, or runs round it the other way"

# At an open chain's end the band keeps unfolding faces around the end vertex
# while the edge it reaches stays closer than this to the end chain edge: such an
# edge is too shallow to end the new loop on (the rail rule's own bound).
END_SHALLOW = math.pi / 2.0 - core.RAIL_MAX_DEV  # the default end_edge angle (60 degrees)
# An end edge the fan reaches only past 180 degrees from the chain edge, by more than this, lies on the other side of
# the chain's extension: it is never the end edge (``_fan``). One along the extension itself still is.
END_OWN_SIDE_TOL = 1e-3  # radians: float32 coordinates put a straight corner off 180 degrees by 1e-6 and more
LID_TOL = 1e-5
# The destructive mode's wave and trial build grow fast with the sides of a face in the band: next to a face with
# more sides than this a chain is cut as with Allow Collapse instead (``destructive_allowed``).
DESTRUCTIVE_MAX_FACE_SIDES = 48
# ``built_limit``: the most trial builds of a clamped cut, after the one at the core's limit.
BUILT_LIMIT_TRIALS = 12
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
    # (exact, tolerance): the destructive mode's limit as ``built_limit`` found it, the largest width that builds.
    built_limits: dict[tuple[bool, float], float] = field(default_factory=dict)
    # (exact, tolerance): the core's limit where ``built_limit`` lowered it, the cut there refused.
    refused: dict[tuple[bool, float], float] = field(default_factory=dict)
    # Per open end (start, end): the unfolded angle of the steepest edge its fan passed under the End Edge Angle
    # (``_fan``), at or under which the End Edge Angle would take that edge as the end edge; None without one.
    end_leans: tuple[float | None, float | None] = (None, None)

    @cached_property
    def max_face_sides(self) -> int:
        """The most sides of any face of the band, its lids and the faces under them included."""
        return max([len(loop) for loop in self.band.faces.values()]
                   + [len(f.verts) for step in self.steps for f in step.region], default=0)

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

    def weld_for(self, destructive: bool, tolerance: float) -> float:
        """The weld a cut is built with: in the destructive mode the larger of ``weld`` and the operator's Tolerance
        (as ``WaveSlider`` takes it), else ``weld``."""
        return max(self.weld, tolerance) if destructive else self.weld


@dataclass
class PieceStrip:
    """The strip one piece of an opened new loop bounds, for UV Stripe (``stripe_for``).

    ``near`` holds the piece's chain vertices in chain order, ``far`` its new
    vertices in loop order, and ``rungs`` (near index, far index) pairs.
    ``faces`` are the faces between them. ``skipped`` says why the piece forms
    no strip; its ``faces`` are then empty.

    A closed loop opened once is one piece whose chain runs from the cut vertex
    round to it again: ``near`` starts and ends on that vertex, a seam.
    ``seam_faces`` are the faces at it on the start side; the others at it are
    on the end side.
    """

    near: list[BMVert]
    far: list[BMVert]
    rungs: list[tuple[int, int]]
    faces: list[BMFace] = field(default_factory=list)
    skipped: str | None = None
    seam_faces: set[BMFace] = field(default_factory=set)


@dataclass
class Applied:
    """The new loop ``apply_cut`` built: its edges and vertices in loop order.

    ``anchors[k]`` indexes ``chain[k]``'s new vertex in ``loop_verts``; None where
    the cut has none, or where it lay on a lid and the projection replaced it.
    ``strip_faces`` are the faces between the chain and the new loop, found only
    for a complete cut. ``failures`` says what could not be built once the mesh
    was being edited: the cut is then incomplete, though every edit made is whole.

    A loop the destructive mode opened (``core.Cut.breaks``) is several pieces:
    ``pieces`` holds each piece's loop edges (one piece, ``[loop_edges]``, by
    default), ``loop_verts`` their vertices piece after piece, and
    ``piece_strips`` each piece's strip for UV Stripe. ``strip_faces`` is then
    the faces of every piece that forms a strip.
    """

    loop_edges: list[BMEdge]
    loop_verts: list[BMVert]
    anchors: list[int | None]
    strip_faces: list[BMFace] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)
    pieces: list[list[BMEdge]] = field(default_factory=list)
    piece_strips: list[PieceStrip] = field(default_factory=list)

    def __post_init__(self):
        if not self.pieces:
            self.pieces = [list(self.loop_edges)]


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
    v: BMVert, face: BMFace, came: BMVert, stop: BMVert | None, chain_edges: set,
    angles: core.Angles | None = None, lean: list | None = None,
) -> tuple[list[BMFace], bool, BMVert | None]:
    """Faces around ``v`` from ``face`` (which holds edge (v, came)), unfolding away from ``came``.

    With ``stop`` (a middle chain vertex) the fan ends at the face whose far edge
    reaches ``stop``. Without (an open chain's end) it crosses an edge only while
    the unfolded angle from the chain edge stays under ``angles.end_edge``. A chain
    edge ends it early, and so does every edge not held by exactly two visible
    faces (``_across``): the mesh border, a fin, or the edge of a hidden face.

    Returns (faces, reached, end): ``reached`` is True when a middle fan got round
    to ``stop``, False when it ended early (and always for an end fan). ``end`` is
    the far vertex of the edge an end fan stopped at once the angle reached
    ``angles.end_edge``: that end edge leaves the chain by ``angles.end_edge`` at least,
    so the end wall it starts never runs along the new loop. None when the fan
    ended any other way.

    An end edge always comes from the band's own side of the chain: one the fan
    reaches only past the chain's extension (an unfolded angle over 180 degrees)
    bounds the face on the other side. When the angle jumps there from under
    ``angles.end_edge``, the end edge is the own-side edge already crossed that
    lies closest to square-on to the chain, and the fan ends at it (no end edge
    when there is none).

    An end fan appends to ``lean`` (when given) the unfolded angle of the steepest edge it passed under
    ``angles.end_edge`` on its own side: the last one it crossed before its end edge, or the one it could not cross
    where it ends without one. ``angles.end_edge`` at or under that angle would make that edge the end edge.
    """
    faces, angle = [face], 0.0
    shallow = END_SHALLOW if angles is None else angles.end_edge
    crossed: list[tuple[float, BMVert, int]] = []  # an end fan's edges crossed: (unfolded angle, far vertex, faces)
    while True:
        far, edge = _other_edge(face, v, came)
        if stop is not None:
            if far is stop:
                return faces, True, None
        else:
            angle += _corner(face, v)
            if angle > math.pi + END_OWN_SIDE_TOL:
                if not crossed:
                    return faces, False, None
                _angle, end, count = min(crossed, key=lambda c: abs(c[0] - math.pi / 2.0))
                return faces[:count], False, end
            if angle >= shallow:
                if lean is not None and crossed:
                    lean.append(crossed[-1][0])
                return faces, False, far
            crossed.append((angle, far, len(faces)))
        nxt = None if edge in chain_edges else _across(edge, face)
        if nxt is None or nxt in faces:
            if stop is None and lean is not None and edge not in chain_edges:
                lean.append(angle)
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


def _step_runs(
    away: list[Vector], points: list[Vector], closed: bool, angles: core.Angles | None = None
) -> list[tuple[int, int]]:
    """Step runs as (a, b): edges a .. b-1 (mod m) are the step, edges a-1 and b its flanks.

    ``away`` holds each chain edge's away direction, ``points`` the chain vertex
    positions. A run is a step when its flanks agree, every run edge differs from
    the flanks' mean, and the chain runs straight across it: every edge from
    flank a-1 to flank b stays within ``angles.step_agree`` of the chord from
    P[a-1] to P[b+1]. Without that last test a chain turning on a flat surface
    (a stair, the border of an L-shaped region) would pass as a step.

    From each left flank only the first edge that agrees with it can close a run:
    a longer run would hold that edge, which cannot differ from the flanks'
    mean. Candidates are taken shortest first, and a candidate is dropped when its
    run overlaps a taken run or one of its flanks lies in one, so flanks are
    never steps. Shortest first keeps a lip a step even when a face further out
    also turns away and could pair with it as a flank.
    """
    a = core.Angles() if angles is None else angles
    agree, differ = math.cos(a.step_agree), math.cos(a.step_differ)
    run_break = math.cos(a.step_differ - a.step_agree / 2.0)
    m, n = len(away), len(points)
    dirs = [(points[(x + 1) % n] - points[x]).normalized() for x in range(m)]

    def straight(i: int, j: int) -> bool:
        chord = (points[(j + 1) % n] - points[i % n]).normalized()
        return all(dirs[x % m].dot(chord) >= agree for x in range(i, j + 1))

    candidates = []
    for i in range(m):
        for j in range(i + 1, i + m if closed else m):
            c = away[i].dot(away[j % m])
            if c >= agree:
                if j > i + 1 and straight(i, j):
                    mean = (away[i] + away[j % m]).normalized()
                    if all(away[x % m].dot(mean) < differ for x in range(i + 1, j)):
                        candidates.append((i, j))
                break
            if c >= run_break:
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
    start: BMVert, rail: BMEdge, center: Vector, normal: Vector, tol: float, chain: set, meets: set, chain_edges: set,
    angles: core.Angles | None = None,
) -> list[BMVert]:
    """A flank rail continued edge by edge while it stays in the lid's plane.

    The path leaves chain vertex ``start`` along ``rail``. At each vertex it takes
    the visible edge that turns least from the edge it came along, never a chain
    edge, an edge back onto the path or one to a ``chain`` vertex. It goes on along
    that edge while the turn stays within ``angles.rail_bend`` and the edge's far
    vertex lies within ``tol`` of the plane through ``center`` with ``normal``;
    otherwise it ends. Inside one plane the 3D turn is the developed one. It ends
    on the first vertex of ``meets`` it reaches (the other flank's path).
    """
    bend = core.RAIL_MAX_DEV if angles is None else angles.rail_bend
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
        if best is None or best[0] > bend or abs((best[1].co - center).dot(normal)) > tol:
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
    bm, src: ChainSrc, side: int, tris: dict[int, list[tuple[int, int, int]]] | None = None,
    angles: core.Angles | None = None,
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
    if angles is None:
        angles = core.Angles()

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
    wedges, end_edges, leans = [], [None, None], ([], [])
    for k in range(n):
        if closed or 0 < k < n - 1:
            fan, reached, _end = _fan(chain[k], side_faces[k], chain[(k + 1) % n], chain[k - 1], walls, angles)
            if reached and fan[-1] is not side_faces[k - 1]:
                return None, MIXED_SECTORS
        elif k == 0:
            fan, _reached, end_edges[0] = _fan(chain[0], side_faces[0], chain[1], None, walls, angles, leans[0])
        else:
            fan, _reached, end_edges[1] = _fan(chain[k], side_faces[k - 1], chain[k - 1], None, walls, angles, leans[1])
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
    for a, b in _step_runs(away, [v.co for v in chain], closed, angles):
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
        path_b = _lid_path(chain[b], rail_b, center, normal, tol, chain_set, set(), walls, angles)
        path_a = _lid_path(chain[a], rail_a, center, normal, tol, chain_set, set(path_b), walls, angles)
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
        end_edges=(None, None) if closed else tuple(None if v is None else v.index for v in end_edges),
        angles=angles)
    try:
        core.wedges(band)
    except ValueError:
        return None, WEDGE_INTERRUPTED
    return BandBuild(
        band=band, chain=list(chain), faces=real, steps=steps, chain_index=src.index, side=side, verts=bm_verts,
        end_leans=tuple(lean[0] if lean else None for lean in leans),
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


def _point_pieces(count: int, breaks: tuple[int, ...], closed: bool) -> list[list[int]]:
    """The indices of a cut's ``count`` points, piece by piece: the loop opens at each break (``core.Cut.breaks``).

    Without breaks the loop is one piece. A closed loop with breaks is open
    pieces: the one across the wrap, when 0 is no break, runs from the last
    break round to the first, and comes last.
    """
    bounds = [0, *sorted({b for b in breaks if 0 < b < count}), count]
    pieces = [list(range(a, b)) for a, b in zip(bounds, bounds[1:])]
    if closed and breaks and 0 not in breaks and len(pieces) > 1:
        pieces.append(pieces.pop() + pieces.pop(0))
    return pieces


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


def _holds(face: BMFace, p: Vector) -> bool:
    """Whether ``p`` lies inside the outline of ``face`` (even-odd), seen along the face normal's main axis."""
    axis = max(range(3), key=lambda i: abs(_normal(face)[i]))
    a, b = [i for i in range(3) if i != axis]
    return _inside((p[a], p[b]), [(v.co[a], v.co[b]) for v in face.verts], 0.0)


def _split_face(va: BMVert, vb: BMVert, coords: list[Vector], probe: Vector | None = None) -> list[BMVert] | None:
    """Split the face holding ``va`` and ``vb`` along va -> coords -> vb; the vertices made at ``coords``. Of several
    faces holding both, the one nearest ``probe``, else the first of ``coords``, else the middle of va-vb.

    ``bmesh.utils.face_split`` interpolates the new vertices' loop data (UVs,
    colours) and vertex data from a copy of the face it splits, then removes the
    copy; ``bmesh.utils.edge_split`` does so along the edge.

    None when no face holds both vertices or bmesh refuses the split; the face is
    then left as it was.
    """
    face = None
    if probe is not None:  # the face whose outline holds it (a tessellation of a long thin n-gon may miss it)
        face = next((f for f in va.link_faces if not f.hide and vb in f.verts and _holds(f, probe)), None)
    else:
        probe = coords[0] if coords else (va.co + vb.co) * 0.5
    face = face or _face_holding(va, vb, probe)
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

    ``point_slot[i]`` is the slot of ``cut.points[i]`` (None inside a lid).
    ``pieces`` holds the point indices of each piece of the loop, which the cut's
    breaks open (``_point_pieces``), and ``nodes`` each piece's slots in order,
    projected step points included; ``closed`` tells whether the loop closes, one
    piece that does not repeat its first slot, and ``closes`` whether each piece
    does: the whole closed loop, or a ring the destructive mode split it into
    (``core.Cut.rings``). ``runs`` are (vertex or edge slot,
    face slots between, vertex or edge slot), each one face split; a run may
    start or end on a face slot an earlier run made (an inset). ``apexes`` are
    lone points inside a face that every anchor shares, built from their
    connectors (``apply_cut``). ``connectors`` are (chain vertex or rail end,
    slot) edges to add once the loop is in. ``slot_faces`` holds the band faces
    each slot lies in, where it is known (not for points projected under a lid).
    ``inset`` is (band face id, ring slots) for an inset ring of three points
    or more, else None.
    """

    slots: list[_Slot]
    point_slot: list[int | None]
    nodes: list[list[int]]
    runs: list[tuple[int, list[int], int]]
    pieces: list[list[int]]
    closed: bool
    apexes: list[int]
    connectors: list[tuple[BMVert, int]]
    slot_faces: dict[int, frozenset[int]]
    inset: tuple[int, list[int]] | None
    closes: list[bool]


def _plan_loop(build: BandBuild, cut: core.Cut, weld: float, destructive: bool = False) -> _LoopPlan:
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
            faces = build.edge_faces.get(pt.edge, set())
            if destructive:  # within the weld of an end of its edge it is built on that vertex (``_edge_slot``)
                for v in pt.edge:
                    if math.dist(band.verts[v], pt.co) <= weld:
                        return faces | set(build.vert_faces.get(v, ()))
            return faces
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
    slot_faces = {s: frozenset(holders(pt)) for s, pt in zip(point_slot, cut.points) if s is not None}
    inset = None
    if destructive and cut.rings:
        # Two rings the loop split into touch where they split, a point inside a face each: within the weld of each
        # other they are one vertex, the two rings through it (``apply_cut`` splits a run at a vertex made already).
        piece_of = {i: k for k, piece in enumerate(_point_pieces(len(cut.points), cut.breaks, band.closed))
                    for i in piece}
        seen: list[int] = []
        for i, pt in enumerate(cut.points):
            if pt.kind != "face" or point_slot[i] is None:
                continue
            same = next((j for j in seen if piece_of[j] != piece_of[i] and cut.points[j].face == pt.face
                         and (slots[point_slot[j]].position() - slots[point_slot[i]].position()).length <= weld), None)
            if same is None:
                seen.append(i)
            else:
                point_slot[i] = point_slot[same]

    # Runs between vertex and edge points; a closed loop starts on one. A face split
    # needs two separate vertices, so the loop needs two such points at least, and
    # a run through a face must not come back to where it started. The destructive
    # mode's breaks open the loop into open pieces, and there a piece, or a loop of
    # one point, may be a lone vertex or edge point (on a wall) or an apex inside a face.
    def apart(s: int, t: int) -> bool:
        return (slots[s].position() - slots[t].position()).length > weld

    def members_of(s: int) -> list[BMVert]:  # the chain vertices anchored on slot ``s``
        return [build.chain[k] for k, a in enumerate(cut.anchors) if a is not None and point_slot[a] == s]

    whole = band.closed and not cut.breaks
    lone = destructive and (bool(cut.breaks) or len(cut.points) == 1)
    pieces = _point_pieces(len(cut.points), cut.breaks, band.closed)
    rings = set(cut.rings)
    closes = [whole or (band.closed and piece[0] in rings) for piece in pieces]
    # Per band face, the new loop's segments in it, every piece's: what a leg from a face's corner must keep clear of.
    in_face: dict[int, list[tuple[Vector, Vector]]] = {}
    own: list[list[tuple[int, tuple[Vector, Vector]]]] = []  # each piece's entries in ``in_face``
    for piece, closed in zip(pieces, closes):
        own.append([])
        for i, j in list(zip(piece, piece[1:])) + ([(piece[-1], piece[0])] if closed and len(piece) > 2 else []):
            for f in holders(cut.points[i]) & holders(cut.points[j]):
                seg = (Vector(cut.points[i].co), Vector(cut.points[j].co))
                in_face.setdefault(f, []).append(seg)
                own[-1].append((f, seg))
    nodes_of: list[list[int]] = []
    runs: list[tuple[int, list[int], int]] = []
    apexes: list[int] = []
    connectors = [
        (verts[vid], point_slot[at]) for vid, at in cut.connectors if vid in verts and point_slot[at] is not None
    ]
    legs_at: dict[int, set[BMVert]] = {}  # per band face, the corners the legs planned in it so far start from

    def plan_face(face: int, ring: list[int]) -> list[tuple[BMVert, int]] | None:
        """``_face_plan`` for the ring (slots) inside ``face``, the rings of one face planned together: every piece's
        segments, the fan edges and the legs planned already in that face are what its legs keep clear of, fan edges
        into the ring are its legs where they can be, and a corner another ring's leg took is not taken again."""
        fans = [(cv, t) for cv, t in connectors
                if face in build.vert_faces.get(cv.index, ()) and face in slot_faces.get(t, ())]
        others = list(in_face.get(face, ())) + [(cv.co.copy(), slots[t].position().copy()) for cv, t in fans]
        where = {t: g for g, t in enumerate(ring)}
        prefer = frozenset((cv, where[t]) for cv, t in fans if t in where)
        plan = _face_plan(build, face, [slots[t] for t in ring], others, prefer, frozenset(legs_at.get(face, ())))
        for v, g in plan or ():
            in_face.setdefault(face, []).append((v.co.copy(), slots[ring[g]].position().copy()))
            legs_at.setdefault(face, set()).add(v)
        return plan

    def to_apex(k: int, kept: list[int], ring: list[int], face: int) -> int:
        """The ring ``ring`` (slots) of piece ``k`` inside ``face`` that no two legs can build, merged into one apex at
        its points' centroid (the destructive answer to a ridge or ring with no room for its legs); its fan edges go to
        the apex. Raises ``LOOP_CROSSES`` where the apex has no two edges to be built from either."""
        nonlocal connectors
        s = add(_Slot(co=_ring_point(cut, kept)))
        slot_faces[s] = frozenset({face})
        for i in kept:
            point_slot[i] = s
        gone = set(ring)
        for f, seg in own[k]:  # its segments are gone: legs to the apex need not keep clear of them
            if seg in in_face.get(f, []):
                in_face[f].remove(seg)
        connectors = list(dict.fromkeys((cv, s if t in gone else t) for cv, t in connectors))
        connectors = [(cv, t) for cv, t in connectors if t != s or not _grazes(build, cv, slots[s], {face})]
        if len({cv for cv, t in connectors if t == s}) < 2:
            connectors += [(v, s) for v, _g in plan_face(face, [s]) or ()]
            if len({cv for cv, t in connectors if t == s}) < 2:
                raise ValueError(LOOP_CROSSES)
        nodes_of[-1] = [s]
        apexes.append(s)
        return s
    for k, (piece, closed) in enumerate(zip(pieces, closes)):
        kept = [i for i in piece if point_slot[i] is not None]
        if not kept:
            raise ValueError(LOOSE_LOOP)
        pairs = list(zip(kept, kept[1:]))
        if closed and len(kept) > 1:
            pairs.append((kept[-1], kept[0]))
        nodes: list[int] = []  # the piece's slots in order
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
        if not closed or not pairs:
            nodes.append(point_slot[kept[-1]])
        nodes_of.append(nodes)

        firm = [s for s in nodes if not slots[s].inside]
        if lone and len(nodes) == 1 and not firm:  # an apex, built from a face split between two of its connectors
            # A fan edge into the apex that would graze its face's border on the way (through a reflex corner) is
            # left out, as one crossing it is.
            connectors = [(cv, t) for cv, t in connectors
                          if t != nodes[0] or not _grazes(build, cv, slots[t], holders(cut.points[kept[0]]))]
            if len({cv for cv, at in connectors if at == nodes[0]}) < 2:
                # No two connectors cross nothing (an apex inside a face away from the chain): two of its face's
                # corners stand in for them (``_face_plan``).
                face = cut.points[kept[0]].face
                plan = plan_face(face, [nodes[0]])
                connectors += [(v, nodes[0]) for v, _g in plan or ()]
                if len({cv for cv, at in connectors if at == nodes[0]}) < 2:
                    raise ValueError(LOOSE_LOOP)
            apexes.append(nodes[0])
            continue
        if not firm and len({cut.points[i].face for i in kept}) == 1:  # a ring inside one face, as in an n-gon cap
            ring = _inset_ring(band, cut, weld) if destructive and whole else None
            if ring is None and destructive and closed and cut.points[kept[0]].face >= 0:
                # A ring inside a face the chain does not bound (a room's ring shrunk into one quad of it): inset into
                # that face from its own corners (``_face_inset``).
                before = {i: point_slot[i] for i in kept}
                ring_slots = _face_inset(build, cut, kept, point_slot, slots, add, slot_faces, weld)
                moved = {before[i]: point_slot[i] for i in kept if point_slot[i] != before[i]}
                connectors = list(dict.fromkeys((cv, moved.get(t, t)) for cv, t in connectors))  # welded points' fans
                nodes_of[-1] = ring_slots
                face = cut.points[kept[0]].face
                plan = plan_face(face, ring_slots)
                if plan is None:  # no legs: the ring is merged into an apex
                    to_apex(k, kept, ring_slots, face)
                    continue
                # Its legs from the corners are checked as connectors are (``_crossing``); built by the runs already.
                connectors += [(v, ring_slots[g]) for v, g in plan]
                if len(ring_slots) == 1:  # an apex: a face split through it between two corners of its face
                    apexes.append(ring_slots[0])
                else:
                    connectors = _clear_fans(build, face, plan, ring_slots, slots, connectors)
                    runs += _face_runs(build, plan, ring_slots, add, slot_faces,
                                      [slots[t].position() for t in ring_slots])
                continue
            if ring is None:
                raise ValueError(INSIDE_ONE_FACE)
            # The destructive mode insets it. Points within the weld of the one before are one, at
            # their centroid, with their anchors and connectors, and every chain vertex connects to
            # its point. One point left is an apex. Two or more: one face split from chain[0]
            # through the ring's points to chain[h], a second round the rest of the ring (none for
            # two points, whose edge the first made): a quad on each chain edge, a triangle where
            # anchors merged, round the inner face.
            groups, h = ring
            face = cut.points[0].face
            for members in groups:
                if len(members) > 1:
                    s = add(_Slot(co=_ring_point(cut, members)))
                    slot_faces[s] = frozenset({face})
                    for i in members:
                        point_slot[i] = s
            ring_slots = [point_slot[members[0]] for members in groups]
            # A ring that comes back to a place it passed (not its neighbour: those are welded above) is a walk
            # round a tree, the skeleton of a non-convex face: one slot per place, so the walk's repeats are one
            # vertex, and the tree is built as it is, one face per chain edge (``_tree_runs``).
            place: dict[int, int] = {}
            for g, s in enumerate(ring_slots):
                place[s] = next((place[t] for t in ring_slots[:g] if t in place
                                 and (slots[t].position() - slots[s].position()).length <= weld), s)
            walk = len(set(place.values())) < len(ring_slots)
            if walk:
                for i, s in enumerate(point_slot):
                    if s in place:
                        point_slot[i] = place[s]
                ring_slots = _through([place[s] for s in ring_slots], slots, weld)
            nodes_of[-1] = ring_slots
            connectors = list(dict.fromkeys(
                [(verts[vid], point_slot[at]) for vid, at in cut.connectors if vid in verts]
                + [(v, point_slot[at]) for v, at in zip(build.chain, cut.anchors)]))
            if walk and len(set(ring_slots)) > 1:
                runs += _tree_runs(build, ring_slots, connectors, add, slot_faces)
                continue
            if h is None or walk:
                apexes.append(ring_slots[0])
                continue
            count, at = len(ring_slots), {s: g for g, s in enumerate(ring_slots)}
            first = at[point_slot[cut.anchors[0]]]
            order = [ring_slots[(first + t) % count] for t in range(count)]  # from chain[0]'s point on
            mid = (at[point_slot[cut.anchors[h]]] - first) % count
            ring_at = [slots[t] for t in ring_slots]
            # A connector that would leave the face (past a reflex corner of a non-convex face) is left out; so are the
            # two cuts' legs, and the corner plan builds the ring instead (``_face_plan``).
            connectors = [(cv, t) for cv, t in connectors if t not in at or _sees(build, face, cv, at[t], ring_at)]
            if not (_sees(build, face, build.chain[0], first, ring_at)
                    and _sees(build, face, build.chain[h], at[order[mid]], ring_at)):
                plan = _face_plan(build, face, ring_at, in_face.get(face, ()))
                if plan is None:
                    raise ValueError(LOOP_CROSSES)
                connectors += [(v, ring_slots[g]) for v, g in plan]
                runs += _face_runs(build, plan, ring_slots, add, slot_faces,
                                      [slots[t].position() for t in ring_slots])
                inset = (face, ring_slots) if count >= 3 else None
                continue
            ends = add(_Slot(vert=build.chain[0])), add(_Slot(vert=build.chain[h]))
            for end in ends:
                slot_faces[end] = frozenset(build.vert_faces.get(slots[end].vert.index, ()))
            runs.append((ends[0], order[: mid + 1], ends[1]))
            # (the half round the ring's inside, as ``_face_runs`` probes)
            runs.append((order[mid], order[mid + 1:], order[0],
                         *_ring_probe([slots[t].position() for t in ring_slots])))
            inset = (face, ring_slots) if count >= 3 else None
            continue
        if not firm:
            raise ValueError(LOOSE_LOOP)
        if not any(apart(s, firm[0]) for s in firm[1:]):
            if lone and len(firm) == len(nodes):  # one vertex: a lone point, or points welded onto it
                continue
            if destructive and closed and len(firm) < len(nodes) and not any(
                    apart(t, firm[0]) for t in nodes if not slots[t].inside) and any(
                    (slots[t].position() - slots[firm[0]].position()).length > 4.0 * weld for t in nodes):
                at = nodes.index(firm[0])
                walk = nodes[at:] + nodes[:at]
                inside = [t for t in walk[1:] if slots[t].inside]
                pts = [slots[t].position() for t in walk]
                area = Vector(_newell([tuple(q) for q in pts])).length * 0.5
                span = sum((b - a).length for a, b in zip(pts, pts[1:] + pts[:1]))
                if len(inside) < 2 or 2.0 * area <= 4.0 * weld * span:
                    # A ring collapsed to a ridge from one place on an edge or vertex into a face and back (or into
                    # each face either side of that place): each tip is built as an open piece's is (``_tip_run``),
                    # from that place, the way back the same edges.
                    tips: list[list[int]] = [[]]
                    alias: dict[int, int] = {}  # a tip's point within the weld of the one before it: that one
                    for t in walk[1:]:
                        if slots[t].inside:
                            if tips[-1] and not apart(tips[-1][-1], t):
                                alias[t] = tips[-1][-1]
                            else:
                                tips[-1].append(t)
                        elif tips[-1]:
                            tips.append([])
                    # The ring runs out to each tip and back the same edges: its points on the way back are the way
                    # out's, nearest first (float noise puts a point on one way that the other lacks).
                    ridge = [walk[0]]
                    for tip in tips:
                        if tip:
                            run = _tip_run(build, slots, walk[0], tip, connectors, add, slot_faces, members_of, in_face)
                            runs.append(run)
                            out = run[1]
                            for t in tip:
                                if t not in out:
                                    alias[t] = min(out, key=lambda o, t=t: (slots[o].position()
                                                                             - slots[t].position()).length)
                            ridge += [*out, *out[-2::-1], walk[0]]
                    point_slot[:] = [alias.get(s, s) for s in point_slot]
                    connectors = list(dict.fromkeys((cv, alias.get(t, t)) for cv, t in connectors))
                    nodes_of[-1] = ridge[:-1]
                    continue
                # A ring inside one face but for one point on its border: one face split from that point through the
                # ring to a corner of the face it sees, a second round the rest of the ring back to that point.
                face = next(iter(slot_faces.get(inside[0], frozenset())), -1)
                ring_at = [slots[t] for t in walk]
                legs = [] if face < 0 or face not in build.faces else sorted(
                    (abs(g - len(walk) / 2.0), (v.co - ring_at[g].position()).length, g, v.index, v)
                    for v in build.faces[face].verts for g in range(1, len(walk))
                    if _sees(build, face, v, g, ring_at, in_face.get(face, ())))
                if not legs:
                    raise ValueError(LOOP_CROSSES)
                g, v = legs[0][2], legs[0][4]
                corner = add(_Slot(vert=v))
                slot_faces[corner] = frozenset(build.vert_faces.get(v.index, ()))
                connectors.append((v, walk[g]))
                runs += [(walk[0], walk[1:g + 1], corner), (walk[g], walk[g + 1:], walk[0])]
                continue
            if destructive and closed and all((slots[t].position() - slots[firm[0]].position()).length <= 4.0 * weld
                                              for t in nodes):
                # A ring a few welds round one vertex, just short of its apex there: that vertex (noise scale).
                for i in kept:
                    point_slot[i] = firm[0]
                nodes_of[-1] = [firm[0]]
                continue
            if destructive and not closed and len(nodes) > 2 and all(slots[s].inside for s in nodes[1:-1]):
                runs.append(_tip_run(build, slots, nodes[0], nodes[1:-1], connectors, add, slot_faces,  # a ridge's tip
                                     members_of, in_face))
                continue
            raise ValueError(LOOSE_LOOP)
        start = nodes.index(firm[0])
        order = nodes[start:] + nodes[: start + 1] if closed else nodes
        if slots[order[0]].inside or slots[order[-1]].inside:
            raise ValueError(LOOSE_LOOP)
        first, inner = order[0], []
        for s in order[1:]:
            if slots[s].inside:
                inner.append(s)
            else:
                if inner and not apart(first, s):
                    if not destructive or whole:  # a closed loop's run back to its start: refused before any edit
                        raise ValueError(LOOSE_LOOP)
                    # (A ring the loop split into may run into a spike and back, where it touched the other ring.)
                    # A ridge into the band and back (an open piece closed into a ridge whose ends meet): its tip
                    # lies inside a face. A face cannot hold a loose edge, so the tip is built by one face split from
                    # where the ridge enters the face, through the tip, on to a vertex of that face: a member's fan
                    # edge where one crosses nothing, else the face's vertex the straight way to a member chain
                    # vertex passes nearest (``_tip_run``).
                    runs.append(_tip_run(build, slots, first, inner, connectors, add, slot_faces, members_of, in_face))
                else:
                    runs.append((first, inner, s))
                first, inner = s, []
    return _LoopPlan(slots, point_slot, nodes_of, runs, pieces, whole, apexes, connectors, slot_faces, inset, closes)


def _tip_run(build: BandBuild, slots: list[_Slot], first: int, inner: list[int], connectors, add, slot_faces,
             members_of, in_face=None) -> tuple:
    """The face split that builds a ridge's tip: from ``first`` (where the ridge enters the tip's face) along ``inner``
    up to the tip (the point furthest from ``first``) and on to a vertex of that face; the way back is the same edges.

    The vertex is a member's fan edge to the tip where one crosses nothing (a connector in that face), else, of the
    face's vertices not on ``first``'s own element, the one whose way from the tip turns least from the straight way
    to a member chain vertex (the chain vertices anchored on the tip), so the second edge leans the way the tip's
    sources came from. Raises ``LOOSE_LOOP`` where the tip lies in no one real face.
    """
    start = slots[first].position()
    tip = max(range(len(inner)), key=lambda i: (slots[inner[i]].position() - start).length)
    faces = slot_faces.get(inner[tip], frozenset())
    face = next(iter(faces), -1) if len(faces) == 1 else -1
    if face < 0:
        raise ValueError(LOOSE_LOOP)
    ring = list(build.faces[face].verts)
    own = set() if slots[first].edge is None else set(slots[first].edge.verts)
    if slots[first].vert is not None:
        own.add(slots[first].vert)
    legs = [cv for cv, s in connectors if s == inner[tip] and cv in ring and cv not in own]
    at = slots[inner[tip]].position()
    toward = [m.co - at for m in members_of(inner[tip]) if (m.co - at).length > 0.0]

    def off(u: BMVert) -> tuple[float, float]:  # how far the way to ``u`` turns from the way to a member, then its length
        d = u.co - at
        if d.length == 0.0 or not toward:
            return (math.pi, d.length)
        return (min(d.angle(t) for t in toward), d.length)

    # A member's own fan edge where it crosses nothing; else the face's vertex the straight way to a member passes
    # nearest, so the tip's second edge leans the way its sources came from. Of those, one whose edge keeps clear of
    # the face's border and of what else the loop and its fan edges lay in the face (``in_face``), where one does.
    if in_face is not None:
        others = list(in_face.get(face, ())) + [(cv.co.copy(), slots[t].position().copy()) for cv, t in connectors
                                                 if face in build.vert_faces.get(cv.index, ())
                                                 and face in slot_faces.get(t, ())]
        clear = [u for u in ring if u not in own and _sees(build, face, u, 0, [slots[inner[tip]]], others)]
        legs = [u for u in legs if u in clear]
        ring = clear or ring
    v = legs[0] if legs else min((u for u in ring if u not in own), key=off)
    end = add(_Slot(vert=v))
    slot_faces[end] = frozenset(build.vert_faces.get(v.index, ()))
    if in_face is not None:  # its second edge is checked as connectors are (``_crossing``), and kept clear of
        connectors.append((v, inner[tip]))
        in_face.setdefault(face, []).append((v.co.copy(), slots[inner[tip]].position().copy()))
    return first, inner[: tip + 1], end


def _through(ring: list[int], slots: list[_Slot], weld: float) -> list[int]:
    """A tree's walk ``ring`` (closed) with every place a step of it runs straight through, within ``weld``, put on
    that step in order: where the walk goes from one branch's end to the next past a junction it does not repeat
    there (a T's bar, its stem's foot on it), the step is two tree edges, not one across the junction."""
    out = []
    for a, b in zip(ring, ring[1:] + ring[:1]):
        out.append(a)
        pa, pb = slots[a].position(), slots[b].position()
        d = pb - pa
        dd = d.dot(d)
        on = []
        for c in dict.fromkeys(ring):
            if c in (a, b) or dd == 0.0:
                continue
            t = (slots[c].position() - pa).dot(d) / dd
            if 0.0 < t < 1.0 and (pa + d * t - slots[c].position()).length <= weld:
                on.append((t, c))
        out += [c for _, c in sorted(on)]
    return out


def _tree_runs(build: BandBuild, ring: list[int], connectors, add, slot_faces) -> list[tuple]:
    """The face splits that build a tree inside one face: the walk ``ring`` round it (one slot per place) and the
    ``connectors`` from the chain vertices to its places, one face per chain edge in the end.

    Each run goes from a vertex already there (a chain vertex at first) through places not built yet to another one:
    a shortest such way through the tree and connector edges not used yet. What is left joins places already built.
    """
    edges: set[frozenset] = set()
    for a, b in zip(ring, ring[1:] + ring[:1]):
        if a != b:
            edges.add(frozenset((a, b)))
    chain_slot: dict = {}
    for cv, s in connectors:
        if cv not in chain_slot:
            chain_slot[cv] = add(_Slot(vert=cv))
            slot_faces[chain_slot[cv]] = frozenset(build.vert_faces.get(cv.index, ()))
        edges.add(frozenset((chain_slot[cv], s)))
    built = set(chain_slot.values())
    places = set(ring)
    runs: list[tuple] = []
    while places - built:
        best = None
        for s in sorted(built):
            way, prev = [s], {s: None}
            queue = [s]
            while queue:  # breadth first through places not built yet, to another vertex already there
                u = queue.pop(0)
                for e in sorted(edges, key=sorted):
                    if u not in e:
                        continue
                    (w,) = e - {u}
                    if w in prev:
                        continue
                    prev[w] = u
                    if w in built and u != s:
                        path = [w]
                        while path[-1] != s:
                            path.append(prev[path[-1]])
                        way = path[::-1]
                        queue = []
                        break
                    if w not in built:
                        queue.append(w)
            if len(way) > 2 and (best is None or len(way) < len(best)):
                best = way
        if best is None:
            raise ValueError(LOOSE_LOOP)
        runs.append((best[0], best[1:-1], best[-1]))
        built |= set(best)
        edges -= {frozenset(p) for p in zip(best, best[1:])}
    runs += [(a, [], b) for a, b in (sorted(e) for e in sorted(edges, key=sorted)) if a in places and b in places]
    return runs


def _inset_ring(band: core.Band, cut: core.Cut, weld: float) -> tuple[list[list[int]], int | None] | None:
    """The destructive mode's inset of a ring inside one face: (its points welded into groups, h), or None for none.

    The ring is an inset when the whole closed chain bounds the one face it lies
    in (a real face, not a lid), it has two points at least, and its anchors step
    round its points once, one point or none per chain edge. Neighbouring groups,
    round the ring too, are welded into one while their neighbouring points lie
    within ``weld`` of each other as the core placed them, or while the points the
    groups are built on do (``_ring_point``: a point, or a group's centroid, in
    float32). So no ring edge the inset builds is that short. The
    groups are in ring order. With one group the ring is an apex, and h is None.
    Else h is the chain index that the first face split runs to from ``chain[0]``,
    through the groups from ``chain[0]``'s to ``chain[h]``'s: the one that halves
    the ring best.
    """
    m, n, a = len(cut.points), len(band.chain), cut.anchors
    face = cut.points[0].face
    if m < 2 or face < 0 or set(band.side_faces) != {face} or None in a or len(set(a)) != m:
        return None
    steps = [(a[(k + 1) % n] - a[k]) % m for k in range(n)]
    if max(steps) > 1 or sum(steps) != m:
        return None
    groups = [[i] for i in range(m)]
    at = [_ring_point(cut, g) for g in groups]  # each group's point as the mesh will hold it (float32)

    def close(j: int) -> bool:  # groups j - 1 and j
        a, b = groups[j - 1][-1], groups[j][0]  # the neighbouring points across them
        return math.dist(at[j - 1], at[j]) <= weld or math.dist(cut.points[a].co, cut.points[b].co) <= weld

    k = 0
    while len(groups) > 1:  # a merge only changes the pairs round it
        k = next((j for j in range(max(k - 1, 0), len(groups)) if close(j)), None)
        if k is None:  # one last pass over all of them
            k = next((j for j in range(len(groups)) if close(j)), None)
            if k is None:
                break
        if k == 0:  # the last group and the first: round the ring
            groups[0] = groups.pop() + groups[0]
            at.pop()
        else:
            groups[k - 1] += groups.pop(k)
            at.pop(k)
        at[k - 1 if k else 0] = _ring_point(cut, groups[k - 1 if k else 0])
    if len(groups) == 1:
        return groups, None
    of = {i: g for g, members in enumerate(groups) for i in members}
    count, g = len(groups), [of[x] for x in a]
    return groups, min((abs((g[k] - g[0]) % count - count / 2.0), k) for k in range(1, n) if g[k] != g[0])[1]


def _grazes(build: BandBuild, cv: BMVert, slot: _Slot, faces) -> bool:
    """Whether the straight edge from chain vertex ``cv`` to ``slot`` comes within ``WELD_TOL`` of an edge of a face
    both lie in (``faces``, the slot's), but at its own ends: through a corner of the face, or along its side."""
    p, q = tuple(cv.co), tuple(slot.position())
    for f in faces:
        face = build.faces.get(f)
        if face is None or cv not in face.verts:
            continue
        for e in face.edges:
            if cv in e.verts or e is slot.edge or (slot.vert is not None and slot.vert in e.verts):
                continue
            if _segment_gap(p, q, tuple(e.verts[0].co), tuple(e.verts[1].co)) <= WELD_TOL:
                return True
    return False


def _sees(build: BandBuild, face: int, v: BMVert, g: int, ring: list[_Slot], others=()) -> bool:
    """Whether the straight edge from corner ``v`` of band face ``face`` to point ``g`` of ``ring`` (slots inside the
    face, in order round it) stays inside the face and clear of the ring: no closer than ``WELD_TOL`` to an edge of the
    face but at ``v``, nor to a ring edge but at ``g``, nor to any of ``others`` (the loop's other segments in the
    face, as point pairs, and the edges already planned from the face's corners) but where one ends on ``g``'s point,
    or on ``v`` and runs off another way, its middle inside the face."""
    p, q = tuple(v.co), tuple(ring[g].position())
    for a, b in others:
        if min((a - ring[g].position()).length, (b - ring[g].position()).length) <= WELD_TOL:
            continue
        near = (a - v.co).length <= WELD_TOL, (b - v.co).length <= WELD_TOL
        if any(near):  # from the same corner: they part there, unless one runs along the other
            far = tuple(b if near[0] else a)
            if (_segment_gap(p, q, far, far) <= WELD_TOL
                    or _segment_gap(far, p, q, q) <= WELD_TOL):
                return False
            continue
        if _segment_gap(p, q, tuple(a), tuple(b)) <= WELD_TOL:
            return False
    bmface = build.faces[face]
    for e in bmface.edges:
        if v in e.verts:
            continue
        if _segment_gap(p, q, tuple(e.verts[0].co), tuple(e.verts[1].co)) <= WELD_TOL:
            return False
    count = len(ring)
    for t in range(count if count > 2 else count - 1):
        if g in (t, (t + 1) % count):
            continue
        if _segment_gap(p, q, tuple(ring[t].position()), tuple(ring[(t + 1) % count].position())) <= WELD_TOL:
            return False
    return _gap(bmface, (v.co + ring[g].position()) * 0.5) < math.inf


def _face_plan(build: BandBuild, face: int, ring: list[_Slot], others=(), prefer=frozenset(),
               taken=frozenset()) -> list[tuple[BMVert, int]] | None:
    """Two (corner, ring point) legs to build a ring (or an apex: one point) inside band face ``face`` from, where no
    chain vertex reaches it: two corners of the face, each joined to a point of the ring it sees (``_sees``), the two
    legs apart. The first is the leg nearest the ring; the second halves the ring best, and of those takes the corner
    furthest round the face. None where no two legs see their points, or off a real face.

    A leg that is a connector already (``prefer``: (corner, ring point index) pairs) comes before any other, so the
    ring is built along the fan's own edges and no fan edge runs into the sliver between a leg and itself. A corner in
    ``taken`` (another ring's leg in this face ends there) is used only for a leg ``prefer`` holds."""
    if face < 0 or face not in build.faces:
        return None
    corners = list(build.faces[face].verts)
    count = len(ring)
    legs = sorted(((corners[c], g) not in prefer, (corners[c].co - ring[g].position()).length, c, g)
                  for c in range(len(corners)) for g in range(count)
                  if (corners[c] not in taken or (corners[c], g) in prefer)
                  and _sees(build, face, corners[c], g, ring, others))
    if not legs:
        return None
    _, _, c1, g1 = legs[0]
    p1 = (tuple(corners[c1].co), tuple(ring[g1].position()))
    best = None
    for off, _, c, g in legs:
        if c == c1 or (count > 1 and g == g1):
            continue
        if count > 1 and _segment_gap(*p1, tuple(corners[c].co), tuple(ring[g].position())) <= WELD_TOL:
            continue  # (an apex's two legs meet at it)
        key = (off, abs((g - g1) % count - count / 2.0) if count > 1 else 0.0,
               -min((c - c1) % len(corners), (c1 - c) % len(corners)))
        if best is None or key < best[0]:
            best = (key, c, g)
    if best is None:
        return None
    return [(corners[c1], g1), (corners[best[1]], best[2])]


def _clear_fans(build: BandBuild, face: int, plan, ring: list[int], slots: list[_Slot], connectors) -> list:
    """``connectors`` without the fan edges in ``face`` that the ring ``ring`` (slots) built from ``plan``'s legs
    leaves no room for: one crossing a leg, or one reaching its ring point from inside the ring (between the ring's
    edges there, the inner face's side). Such a fan edge has no face to be cut into once the ring is in."""
    legs = [(v, ring[g]) for v, g in plan]
    pts = [slots[t].position() for t in ring]
    count = len(ring)
    at = {t: g for g, t in enumerate(ring)}
    n = _normal(build.faces[face])
    u = n.orthogonal().normalized()
    w = n.cross(u)

    def ang(d: Vector) -> float:
        return math.atan2(d.dot(w), d.dot(u))

    area = Vector(_newell([tuple(p) for p in pts])).dot(n) if count > 2 else 0.0
    out = []
    for cv, t in connectors:
        if (cv, t) in legs or t not in at or face not in build.vert_faces.get(cv.index, ()):
            out.append((cv, t))
            continue
        p, q = tuple(cv.co), tuple(slots[t].position())
        if any(lv is not cv and lt != t and _segment_gap(p, q, tuple(lv.co), tuple(slots[lt].position())) <= WELD_TOL
               for lv, lt in legs):
            continue
        if count > 2 and area != 0.0:
            g = at[t]
            prev, nxt = pts[g - 1] - pts[g], pts[(g + 1) % count] - pts[g]
            if area < 0.0:
                prev, nxt = nxt, prev
            # Counter-clockwise round the ring, its inside at this point lies from the way to the next point on round
            # to the way back to the one before.
            sweep = (ang(prev) - ang(nxt)) % (2.0 * math.pi)
            turn = (ang(cv.co - pts[g]) - ang(nxt)) % (2.0 * math.pi)
            if 0.0 < turn < sweep:
                continue
        out.append((cv, t))
    return out


def _face_inset(build: BandBuild, cut: core.Cut, kept: list[int], point_slot: list[int | None], slots: list[_Slot],
                add, slot_faces, weld: float) -> list[int]:
    """The slots of a ring of ``cut``'s points ``kept``, inside one face, with neighbours within ``weld`` of each
    other welded into one slot at their centroid (their points then share it, ``point_slot``)."""
    face = cut.points[kept[0]].face
    groups: list[list[int]] = []
    for i in kept:
        if groups and (slots[point_slot[groups[-1][-1]]].position() - slots[point_slot[i]].position()).length <= weld:
            groups[-1].append(i)
        else:
            groups.append([i])
    while len(groups) > 1 and (slots[point_slot[groups[-1][-1]]].position()
                               - slots[point_slot[groups[0][0]]].position()).length <= weld:
        groups[0] = groups.pop() + groups[0]
    out = []
    for members in groups:
        if len(members) > 1:
            s = add(_Slot(co=_ring_point(cut, members)))
            slot_faces[s] = frozenset({face})
            for i in members:
                point_slot[i] = s
        out.append(point_slot[members[0]])
    return out


def _face_runs(build: BandBuild, plan, ring: list[int], add, slot_faces, at=None) -> list[tuple]:
    """The two face splits that inset ``ring`` (slots, two or more; ``at``: their positions) into its face from the
    corners of ``plan`` (``_face_plan``).

    The first runs from the first leg's corner through the ring, from its point on, to the second leg's point, and on
    to that corner; the second round the rest of the ring, inside the half that holds it (none for two points: the
    first made their edge). So the ring is an inner face, its face's two halves round it.
    """
    (v1, g1), (v2, g2) = plan
    count = len(ring)
    order = [ring[(g1 + t) % count] for t in range(count)]
    far = (g2 - g1) % count
    ends = []
    for v in (v1, v2):
        s = add(_Slot(vert=v))
        slot_faces[s] = frozenset(build.vert_faces.get(v.index, ()))
        ends.append(s)
    runs = [(ends[0], order[: far + 1], ends[1])]
    if count > 2:
        # Of the two halves, both holding the ring's points the first split made, it splits the one round the ring's
        # inside: a thin ring's closing edge runs as close to the other half's border as to its own.
        runs.append((order[far], order[far + 1:], order[0], *(_ring_probe(at) if at else [])))
    return runs


def _ring_probe(at: list[Vector]) -> list[Vector]:
    """[a point inside the ring through points ``at``]: their centroid where it lies inside, else [] (no probe)."""
    if len(at) < 3:
        return []
    mid = sum(at, Vector()) / len(at)
    n = Vector(_newell([tuple(p) for p in at]))
    if n.length == 0.0:
        return []
    axis = max(range(3), key=lambda i: abs(n[i]))
    keep = [i for i in range(3) if i != axis]
    poly = [(p[keep[0]], p[keep[1]]) for p in at]
    return [mid] if _inside((mid[keep[0]], mid[keep[1]]), poly, 0.0) else []


def _ring_point(cut: core.Cut, members: list[int]) -> Vector:
    """Where a group of an inset ring's points is built: the point, or the centroid of several (float32, as the mesh)."""
    if len(members) == 1:
        return Vector(cut.points[members[0]].co)
    return sum((Vector(cut.points[i].co) for i in members), Vector()) / len(members)


def _newell(points) -> tuple[float, float, float]:
    """The (unnormalised) Newell normal of a polygon, in double precision."""
    nx = ny = nz = 0.0
    for (x0, y0, z0), (x1, y1, z1) in zip(points, points[1:] + points[:1]):
        nx += (y0 - y1) * (z0 + z1)
        ny += (z0 - z1) * (x0 + x1)
        nz += (x0 - x1) * (y0 + y1)
    return nx, ny, nz


def _inset_reversed(build: BandBuild, plan: _LoopPlan) -> str | None:
    """``RING_REVERSED`` when an inset ring of three points or more does not run round its face the way the chain does.

    The ring runs in chain order; so does the face on the +1 side, the other way
    on the -1 side. A ring with no area (its points on a line) runs neither way.
    """
    if plan.inset is None:
        return None
    face, ring = plan.inset
    fn = _newell([tuple(v.co) for v in build.faces[face].verts])
    rn = _newell([tuple(plan.slots[s].position()) for s in ring])
    return RING_REVERSED if sum(a * b for a, b in zip(fn, rn)) * build.side <= 0.0 else None


def _segment_gap(p0, p1, q0, q1) -> float:
    """The distance between segments p0-p1 and q0-q1 (3D tuples), by their closest points, in double precision.

    The clamped closest-point search is not exactly symmetric in float, so both argument orders are taken and the
    smaller wins: the gap between two segments does not depend on which one is asked first.
    """
    return min(_segment_gap_one(p0, p1, q0, q1), _segment_gap_one(q0, q1, p0, p1))


def _segment_gap_one(p0, p1, q0, q1) -> float:
    """``_segment_gap`` with p0-p1 asked first."""
    d1 = [b - a for a, b in zip(p0, p1)]
    d2 = [b - a for a, b in zip(q0, q1)]
    r = [a - b for a, b in zip(p0, q0)]
    a, e, f = sum(x * x for x in d1), sum(x * x for x in d2), sum(x * y for x, y in zip(d2, r))
    if a <= 1e-30 and e <= 1e-30:
        return math.dist(p0, q0)
    if a <= 1e-30:
        s, t = 0.0, min(1.0, max(0.0, f / e))
    else:
        c = sum(x * y for x, y in zip(d1, r))
        if e <= 1e-30:
            s, t = min(1.0, max(0.0, -c / a)), 0.0
        else:
            b = sum(x * y for x, y in zip(d1, d2))
            denom = a * e - b * b
            s = min(1.0, max(0.0, (b * f - c * e) / denom)) if denom > 1e-30 else 0.0
            t = (b * s + f) / e
            if t < 0.0:
                s, t = min(1.0, max(0.0, -c / a)), 0.0
            elif t > 1.0:
                s, t = min(1.0, max(0.0, (b - c) / a)), 1.0
    return math.dist([x + s * y for x, y in zip(p0, d1)], [x + t * y for x, y in zip(q0, d2)])


def _crossing(build: BandBuild, plan: _LoopPlan, weld: float) -> str | None:
    """``LOOP_CROSSES`` when the plan would build crossing edges inside a band face, else None.

    Face by face (``plan.slot_faces``): no two of the new loop's segments and
    connectors may come within ``WELD_TOL`` of each other (they cross or touch)
    but at an end they share, and no connector may come that close to an edge of
    its face but at its own ends. Ends are shared when they are one vertex once
    built: the same mesh vertex, points one edge split welds together, or loop
    points joined by a run of points each within ``weld`` of the next (the
    core's sub-micron points). The core splits a loop that meets itself into
    rings, so a crossing found here is one the core missed: the cut is refused
    rather than built with crossing edges.
    """
    parent: dict[int, int] = {}

    def root(s: int) -> int:
        while parent.get(s, s) != s:
            s = parent[s]
        return s

    def join(s: int, t: int) -> None:
        parent[root(t)] = root(s)

    on_vert: dict[BMVert, int] = {}
    on_edge: dict[BMEdge, list[int]] = {}
    for nodes, closed in zip(plan.nodes, plan.closes):
        for s, t in zip(nodes, nodes[1:] + (nodes[:1] if closed and len(nodes) > 2 else [])):
            if (plan.slots[s].position() - plan.slots[t].position()).length <= weld:
                join(s, t)
        for s in nodes:
            slot = plan.slots[s]
            if slot.vert is not None:
                join(on_vert.setdefault(slot.vert, s), s)
            elif slot.edge is not None:
                for t in on_edge.setdefault(slot.edge, []):
                    if (slot.co - plan.slots[t].co).length <= weld:
                        join(t, s)
                on_edge[slot.edge].append(s)

    # Where each edge point is built: points one edge split welds share the vertex the first of them made
    # (``_split_edges``, far-to-near), so each is checked where that vertex stands.
    built: dict[int, Vector] = {}
    along: dict[BMEdge, list[int]] = {}
    for s, slot in enumerate(plan.slots):
        if slot.edge is not None:
            along.setdefault(slot.edge, []).append(s)
    for edge, ids in along.items():
        v0, v1 = edge.verts
        axis = v1.co - v0.co
        span = axis.length
        if span == 0.0:
            continue
        far, last = 1.0, None
        for t, s in sorted((((plan.slots[s].co - v0.co).dot(axis) / (span * span), s) for s in ids), reverse=True):
            if last is None or (far - t) * span > weld:
                last, far = plan.slots[s].co, t
            built[s] = last

    def end(s: int) -> tuple[object, tuple[float, ...]]:
        return root(s), tuple(built.get(s, plan.slots[s].position()))

    def vert_end(v: BMVert) -> tuple[object, tuple[float, ...]]:
        return (root(on_vert[v]) if v in on_vert else v), tuple(v.co)

    # Per face: (the new segment's ends, or None for a face edge, the connector's (vertex, slot) or None, edge).
    by_face: dict[int, list] = {}
    for nodes, closed in zip(plan.nodes, plan.closes):
        for s, t in zip(nodes, nodes[1:] + (nodes[:1] if closed and len(nodes) > 2 else [])):
            for f in plan.slot_faces.get(s, frozenset()) & plan.slot_faces.get(t, frozenset()):
                by_face.setdefault(f, []).append(((end(s), end(t)), None, None))
    for cv, s in plan.connectors:
        for f in frozenset(build.vert_faces.get(cv.index, ())) & plan.slot_faces.get(s, frozenset()):
            by_face.setdefault(f, []).append(((vert_end(cv), end(s)), (cv, plan.slots[s]), None))
    for f, items in by_face.items():
        if f >= 0 and any(leg is not None for _ends, leg, _e in items):  # a connector must stay inside its face
            items += [(((None, tuple(e.verts[0].co)), (None, tuple(e.verts[1].co))), None, e) for e in build.faces[f].edges]
        if _crossing_in(items):
            return LOOP_CROSSES
    return None


def _crossing_in(items: list) -> bool:
    """Whether two of one face's segments meet (``_crossing``): a sort and sweep along x over their bounding boxes.

    Each item is (ends, leg, edge): two (key, point) ends; for a connector,
    (its vertex, its far slot); for an edge of the face, the edge. Two new
    segments meet where they come within ``WELD_TOL`` of each other but at an end
    with the same key (and with one such end, where the far end of either lies
    that close to the other); a connector and a face edge where they do but at
    the connector's own ends; two face edges are never compared.
    """
    boxes = []
    for item in items:
        (_k0, p), (_k1, q) = item[0]
        lo = [min(a, b) - WELD_TOL for a, b in zip(p, q)]
        hi = [max(a, b) + WELD_TOL for a, b in zip(p, q)]
        boxes.append((lo, hi, item))
    boxes.sort(key=lambda box: box[0][0])
    for i, (lo, hi, (ends, leg, edge)) in enumerate(boxes):
        for lo2, hi2, (ends2, leg2, edge2) in boxes[i + 1:]:
            if lo2[0] > hi[0]:
                break
            if lo2[1] > hi[1] or lo[1] > hi2[1] or lo2[2] > hi[2] or lo[2] > hi2[2]:
                continue
            if edge is not None and edge2 is not None:
                continue
            if edge is None and edge2 is None:
                shared = [(a, b) for a in range(2) for b in range(2) if ends[a][0] == ends2[b][0]]
                if len(shared) == 1:
                    # Two edges from one vertex: they meet only there, unless one's far end lies on the other (a
                    # hairpin's arms within ``WELD_TOL``, built as edges that meet without a vertex). A far end that
                    # close to the shared one is just a short edge there, not lying along the other.
                    a, b = shared[0]
                    tol = WELD_TOL
                    at, far, far2 = ends[a][1], ends[1 - a][1], ends2[1 - b][1]
                    if ((math.dist(far, at) > 2.0 * tol and _segment_gap(far, far, *(e[1] for e in ends2)) <= tol)
                            or (math.dist(far2, at) > 2.0 * tol
                                and _segment_gap(far2, far2, *(e[1] for e in ends)) <= tol)):
                        return True
                if shared:
                    continue
            else:
                connector, e = (leg, edge2) if edge is None else (leg2, edge)
                if connector is None:  # a loop segment: it lies in its face by construction
                    continue
                cv, slot = connector
                if cv in e.verts or slot.edge == e or (slot.vert is not None and slot.vert in e.verts):
                    continue
            if _segment_gap(ends[0][1], ends[1][1], ends2[0][1], ends2[1][1]) <= WELD_TOL:
                return True
    return False


def _trial_failure(bm, build: BandBuild, cut: core.Cut, slider: core.Slider | None, tolerance: float) -> str | None:
    """The first failure ``apply_cut`` (destructive) would name building ``cut``, found on a copy of ``bm``; None when
    it would build whole. The copy keeps the elements' order, so the band's vertices and faces map across by position.

    A refusal (``ValueError``) is its failure. Any other error the build on the copy raises is one too, named with its
    type, so it never reaches the mesh itself: ``bm`` is untouched either way.
    """
    try:
        return _trial_build(bm, build, cut, slider, tolerance)
    except ValueError as exc:
        return str(exc)
    except Exception as exc:  # noqa: BLE001 - an unexpected error on the copy is a refusal, not a crash
        return f"the trial build failed ({type(exc).__name__}: {exc})"


def _trial_build(bm, build: BandBuild, cut: core.Cut, slider: core.Slider | None, tolerance: float) -> str | None:
    """``_trial_failure`` without its error handling."""
    trial = bm.copy()
    try:
        trial.verts.ensure_lookup_table()
        trial.faces.ensure_lookup_table()
        vpos = {v: i for i, v in enumerate(bm.verts)}
        fpos = {f: i for i, f in enumerate(bm.faces)}

        def vert(v: BMVert) -> BMVert:
            return trial.verts[vpos[v]]

        def face(f: BMFace) -> BMFace:
            return trial.faces[fpos[f]]

        copy = BandBuild(build.band, [vert(v) for v in build.chain], {k: face(f) for k, f in build.faces.items()},
                         [replace(s, region=[face(f) for f in s.region]) for s in build.steps], build.chain_index,
                         build.side, {k: vert(v) for k, v in build.verts.items()})
        applied = apply_cut(trial, copy, cut, slider, destructive=True, tolerance=tolerance, _trial=True)
        return applied.failures[0] if applied.failures else None
    finally:
        trial.free()


def destructive_allowed(build: BandBuild) -> bool:
    """Whether the destructive mode cuts ``build``'s chain: not next to a face with more than
    ``DESTRUCTIVE_MAX_FACE_SIDES`` sides, where its chain is cut as with Allow Collapse instead."""
    return build.max_face_sides <= DESTRUCTIVE_MAX_FACE_SIDES


def built_limit(bm, build: BandBuild, slider, exact: bool, tolerance: float) -> float:
    """The destructive mode's limit of ``build`` on ``bm``: the largest width whose cut ``apply_cut`` builds whole.

    ``slider`` is the ``WaveSlider`` over ``build.band`` made with ``tolerance``. The cut at the core's limit is
    built on a copy of the mesh (``_trial_failure``) once. Where that is refused, the width is bisected down from
    the core's limit, at most ``BUILT_LIMIT_TRIALS`` trials more, with its floor at the last width that built
    (0 to start with): it first steps down from the limit by a gap that grows eightfold per trial, since a cut
    refused only at the limit builds just below it. The slider's limit is lowered to the width found, so its
    solves clamp there and its snaps stop there. Worked out once per (``exact``, ``tolerance``) and kept on
    ``build``.
    """
    key = (exact, tolerance)
    if key in build.built_limits:  # a slider made again for the same build (a Tolerance gone back) clamps there too
        slider.cap_limit(build.built_limits[key], exact=exact)
        return build.built_limits[key]
    top = slider.limit(exact=exact, destructive=True)

    def builds(width: float) -> bool:
        try:
            cut = slider.solve(width, exact=exact, destructive=True)
        except (core.OutOfRoom, ValueError, ArithmeticError, RuntimeError):
            return False
        return not cut.points or _trial_failure(bm, build, cut, slider, tolerance) is None

    found = top
    if top > 0.0 and not builds(top):
        lo, hi, trials = 0.0, top, 0
        gap = max(build.weld_for(True, tolerance), top * 1e-6)
        while trials < BUILT_LIMIT_TRIALS and top - gap > 0.0:  # down from the limit, a growing gap at a time
            trials += 1
            if builds(top - gap):
                lo = top - gap
                break
            hi, gap = top - gap, gap * 8.0
        while trials < BUILT_LIMIT_TRIALS:  # then halving between the last width that built and the first refused
            trials += 1
            mid = 0.5 * (lo + hi)
            if builds(mid):
                lo = mid
            else:
                hi = mid
        found = lo
        slider.cap_limit(found, exact=exact)
        build.refused[key] = top
    build.built_limits[key] = found
    return found


def apply_cut(
    bm, build: BandBuild, cut: core.Cut, slider: core.Slider | None = None, destructive: bool = False,
    tolerance: float = 0.0, _trial: bool = False,
) -> Applied:
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

    ``destructive`` is set for a cut of the destructive mode (``WaveSlider``), and
    ``tolerance`` is then the operator's Tolerance the slider was made with: it
    raises the weld (``BandBuild.weld_for``). Without ``destructive`` it is ignored.
    Its breaks open the loop into pieces: no edge runs across a break, a wall
    point splits its wall edge like any edge point, and each piece gets its own
    strip (``_piece_strips``). Chain vertices merged onto one point share one new
    vertex, and each connects to it where its connector crosses nothing (the
    fan). A piece, or the whole loop, may be one point: a lone vertex or edge
    point, or an apex inside a face, made by a face split through it between two
    of its connectors' chain vertices. A ring inside the one face the closed
    chain bounds is an inset: an inner face, and a quad on each chain edge (a
    triangle where anchors merged), each face split from that face keeping its
    attributes. Its points within the weld of their neighbours are welded first
    (``_inset_ring``): one point left is an apex fan, two a ridge. Without
    ``destructive`` a loop of one point, or a ring inside one face, is refused,
    as before the mode.

    Raises ``ValueError`` before touching the mesh when the cut cannot be built,
    among others when the loop does not run between two separate vertices or
    edges. In the destructive mode that also covers what the core cannot cut
    cleanly yet: an inset ring that encloses nothing or runs round its face the
    wrong way (``RING_REVERSED``), and new edges that would cross or touch inside
    a face, or a connector that would leave its face (``LOOP_CROSSES``,
    ``_crossing``). Once editing has begun nothing is raised: whatever cannot be
    built is left out and named in ``Applied.failures``, and the cut is
    incomplete, though every edit made is whole. The destructive mode first
    builds the cut on a copy of the mesh (``_trial_failure``) and refuses it,
    before any edit, when anything would be left out: it is built whole or not
    at all. ``_trial`` marks that build on the copy.
    """
    band = build.band
    if not cut.points:
        return Applied([], [], [None] * len(cut.anchors))
    weld = build.weld_for(destructive, tolerance)
    plan = _plan_loop(build, cut, weld, destructive)
    slots, point_slot, connectors = plan.slots, plan.point_slot, plan.connectors
    if destructive:  # what the core cannot cut cleanly yet: refused before any edit
        problem = _inset_reversed(build, plan) or _crossing(build, plan, weld)
        if problem:
            raise ValueError(problem)
        if not _trial:
            # The destructive mode builds a cut whole or not at all: what a face split would refuse on the way (two
            # events within the weld of each other leave a loop no plan check sees through) is found on a copy of
            # the mesh first, and the cut refused before any edit.
            problem = _trial_failure(bm, build, cut, slider, tolerance)
            if problem:
                raise ValueError(problem)
    # An apex is made by a face split through it between its first two connectors' chain
    # vertices (``_plan_loop`` saw two at least); its other connectors then fan out to it.
    apex_ends = {s: list(dict.fromkeys(cv for cv, at in connectors if at == s))[:2] for s in plan.apexes}
    end_paths = _end_paths(build, slider)

    # Edit the mesh. From here on nothing raises: a part that cannot be built is
    # left out and named in ``failures``, and every edit already made is whole.
    made: list[BMVert | None] = [s.vert for s in slots]
    failures: list[str] = []
    halves: list[BMFace] = []  # both faces of every split, for ``_strip_faces``
    try:
        _split_edges(slots, made, weld)
        steps = list(reversed(plan.runs))
        while steps:
            a, inner, b, *probe = steps.pop()  # (a probe: a point of the face it splits, ``_face_runs``)
            # A run through a point made already (two rings' shared vertex) splits there into two.
            cut_at = next((t for t, s in enumerate(inner) if made[s] is not None), None)
            if cut_at is not None:
                steps += [(inner[cut_at], inner[cut_at + 1:], b, *probe), (a, inner[:cut_at], inner[cut_at], *probe)]
                continue
            va, vb = made[a], made[b]
            if va is vb or (not inner and bm.edges.get((va, vb)) is not None):
                if inner:  # two points welded onto one vertex: the run has no face to split
                    failures.append(PIECE_FAILED)
                continue
            fresh = _split_face(va, vb, [slots[s].co for s in inner], *probe)
            if fresh is None:
                failures.append(PIECE_FAILED)
                continue
            for s, v in zip(inner, fresh):
                made[s] = v
            halves += _faces_of_edge(va, fresh[0] if fresh else vb)
        for s, (va, vb) in apex_ends.items():
            fresh = _split_face(va, vb, [slots[s].co])
            if fresh is None:
                failures.append(PIECE_FAILED)
                continue
            made[s] = fresh[0]
            halves += _faces_of_edge(va, fresh[0])
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

    loop_verts: list[BMVert] = []  # every piece's, piece after piece
    loop_edges: list[BMEdge] = []
    pieces: list[list[BMEdge]] = []
    piece_verts: list[list[BMVert]] = []
    for nodes, closed in zip(plan.nodes, plan.closes):
        verts: list[BMVert] = []
        for s in nodes:
            v = made[s]
            if v is not None and (not verts or verts[-1] is not v):
                verts.append(v)
        if closed and len(verts) > 1 and verts[0] is verts[-1]:
            verts.pop()
        # A closed loop, or ring, also joins its last vertex to its first, unless that is the edge it already has.
        ends = verts[1:] + (verts[:1] if closed and len(verts) > 2 else [])
        found = [bm.edges.get(pair) for pair in zip(verts, ends)]
        edges = [e for e in found if e is not None]
        if len(edges) < len(found) and not failures:
            failures.append(LOOP_GAP)
        loop_verts += verts
        loop_edges += edges
        pieces.append(edges)
        piece_verts.append(verts)
    index: dict[BMVert, int] = {}
    for i, v in enumerate(loop_verts):
        index.setdefault(v, i)
    anchors = [None if a is None or point_slot[a] is None else index.get(made[point_slot[a]]) for a in cut.anchors]
    strip_faces: list[BMFace] = []
    piece_strips: list[PieceStrip] = []
    if not failures and loop_verts:  # a loop of one point (an apex) has the strip of triangles fanning into it
        if cut.breaks:
            # One strip per piece of the loop. A piece pressed onto its walls has breaks inside it (``Cut.inner``):
            # its strip runs on across them, its far row its points in order, the wall closing each gap.
            groups: list[list[int]] = []
            for i, piece in enumerate(plan.pieces):
                if groups and piece[0] in cut.inner:
                    groups[-1].append(i)
                else:
                    groups.append([i])
            if len(groups) > 1 and plan.pieces[0][0] in cut.inner:  # a closed loop: its first piece runs on its last
                groups[0] = groups.pop() + groups[0]
            gaps = list(loop_edges)
            merged_pieces, merged_verts = [], []
            for group in groups:
                merged_pieces.append([i for g in group for i in plan.pieces[g]])
                row: list[BMVert] = []
                for g in group:
                    for v in piece_verts[g]:
                        if row and row[-1] is not v and bm.edges.get((row[-1], v)) is not None:
                            gaps.append(bm.edges.get((row[-1], v)))
                        if not row or row[-1] is not v:
                            row.append(v)
                merged_verts.append(row)
            pieces = [[e for g in group for e in pieces[g]] for group in groups]
            piece_strips = _piece_strips(build, cut, plan._replace(pieces=merged_pieces), made, merged_verts,
                                         list(dict.fromkeys(gaps)), end_paths, halves)
            strip_faces = [f for part in piece_strips for f in part.faces]
        else:
            # An open end bounds the strip with its end path up to the loop's end, or with
            # the band border its loop end lies on; otherwise the strip is not bounded there.
            barrier, bounded = list(loop_edges), True
            for k, path in zip((0, -1), [] if band.closed else end_paths):
                if path and anchors[k] is not None:
                    barrier += _wall_edges(path, loop_verts[anchors[k]])
                elif anchors[k] is None or not _on_band_border(build, cut.points[cut.anchors[k]]):
                    bounded = False
            strip_faces = _strip_faces(build, barrier, halves) if bounded else []
    return Applied(
        loop_edges, loop_verts, anchors, strip_faces=strip_faces, failures=failures, pieces=pieces,
        piece_strips=piece_strips,
    )


def _piece_strips(
    build: BandBuild, cut: core.Cut, plan: _LoopPlan, made: list[BMVert | None], piece_verts: list[list[BMVert]],
    loop_edges: list[BMEdge], end_paths: list[list[BMVert]], halves: list[BMFace],
) -> list[PieceStrip]:
    """Each piece's strip, for a complete cut its breaks opened (``Applied.piece_strips``).

    A piece runs along the chain vertices anchored on its points, in chain order.
    Where it starts at a break whose right end no chain vertex anchors, the cut
    vertex (anchored on the break's left end) starts it too, its rung that right
    end. The piece's sides are, at an open chain's own end, its end path as for
    a whole loop (see ``apply_cut``), and at a break the edge from its first or
    last chain vertex to its end there: the connector the core gives each end of
    a cut. Its faces are a flood from the side faces of its own chain edges,
    walled by every piece's loop edges and sides (``_strip_faces``). A closed
    loop opened once is one piece whose chain ends on the cut vertex it starts
    from: a seam, whose faces on the start side are ``PieceStrip.seam_faces``.

    A piece forms no strip (``PieceStrip.skipped``) when it has fewer than two
    new vertices, passes a chain vertex twice other than at a seam (or its seam's
    two sides meet in one face), has no edge back to its chain at a break, holds
    an open chain end that nothing bounds (no end path, its anchor in a lid or off
    the band border), or shares strip faces with another piece.
    """
    chain, n, m = build.chain, len(build.chain), len(cut.points)
    anchors, breaks, closed = cut.anchors, set(cut.breaks), build.band.closed

    def vert_of(at: int | None) -> BMVert | None:
        return None if at is None or plan.point_slot[at] is None else made[plan.point_slot[at]]

    out: list[PieceStrip] = []
    seeds: list[set[int]] = []  # each piece's chain edges, for its flood
    walls = list(loop_edges)
    rings = set(cut.rings)
    for piece, far in zip(plan.pieces, piece_verts):
        starts_at_break, ends_at_break = piece[0] in breaks, (piece[-1] + 1) % m in breaks
        if piece[0] in rings:
            # A ring the loop split into: its strip runs along the chain vertices anchored on it (one run round the
            # chain), its far row the ring from the first one's point on to the last one's, its sides the edges from
            # those two to their points. The rest of the ring faces where it split off, no chain of its own.
            rows, far = _ring_rows(anchors, set(piece), far, vert_of)
            cut_vertex = False
        else:
            rows, cut_vertex = _piece_rows(anchors, piece, m, closed, starts_at_break)
        if starts_at_break and not cut_vertex and len(set(far)) == 1 and rows:
            # A lone point (a piece pressed onto its wall, its ends one place): the cut it starts at joins its row
            # too, so it fans from both chain vertices, as an apex does.
            k = (rows[0] - 1) % n
            if closed or rows[0] > 0:
                rows, cut_vertex = [k, *rows], True
        near = [chain[x] for x in rows]
        rungs = []
        for t, x in enumerate(rows):
            v = vert_of(piece[0] if t == 0 and cut_vertex else anchors[x])
            if v in far:
                rungs.append((t, far.index(v)))
        part = PieceStrip(near, far, rungs)
        out.append(part)
        seeds.append(set(rows[:-1]))
        seam = len(rows) > 2 and rows[0] == rows[-1]  # a closed loop opened once: its chain ends where it starts
        if piece[0] in rings and not rows:  # a small ring with no chain of its own (one run round it): no strip shape
            part.skipped = RING_NO_CHAIN
        elif not far or len(rows) < 2:  # a lone point (a wall point) fans as an apex does, along a chain edge at least
            part.skipped = NO_STRIP_LENGTH
        elif len(set(rows)) < len(rows) - seam:
            part.skipped = PIECE_CHAIN_REVISITS
        if part.skipped:
            continue
        for at_break, cv, end in ((starts_at_break, near[0], far[0]), (ends_at_break, near[-1], far[-1])):
            side = _edge(cv, end) if at_break else None
            if side is not None:
                walls.append(side)
            elif at_break and piece[0] not in rings:  # (a ring's strip stops at the other rings' chain instead)
                part.skipped = PIECE_OPEN_SIDE
        # An open chain's own end, held by its first or last piece, bounds the strip as for a whole loop.
        for at_break, k, path in ((starts_at_break, 0, end_paths[0]), (ends_at_break, n - 1, end_paths[1])):
            if closed or at_break:
                continue
            end = vert_of(anchors[k])
            if path and end is not None:
                walls += _wall_edges(path, end)
            elif end is None or not _on_band_border(build, cut.points[anchors[k]]):
                part.skipped = part.skipped or NO_STRIP_FACES
    chain_edges = {_edge(chain[i], chain[(i + 1) % n]) for i in range(n if closed else n - 1)} - {None}
    # The rings a loop split into share the region where they split, with no edge between them: their strips flood it
    # together, each face going to the ring whose flood reaches it first (``_shared_strips``).
    ringed = [(part, edges) for part, edges, piece in zip(out, seeds, plan.pieces)
              if piece[0] in rings and not part.skipped]
    shares = _shared_strips(build, walls, halves, [edges for _part, edges in ringed]) if ringed else []
    for (part, _edges), faces in zip(ringed, shares):
        part.faces = faces
    for part, edges, piece in zip(out, seeds, plan.pieces):
        if not part.skipped and piece[0] not in rings:
            part.faces = _strip_faces(build, walls, halves, edges)
            if part.near[0] is part.near[-1]:
                seam_faces = _seam_faces(part.faces, part.near, chain_edges.union(walls))
                if seam_faces is None:
                    part.skipped = PIECE_CHAIN_REVISITS
                else:
                    part.seam_faces = seam_faces
    owners: dict[BMFace, list[PieceStrip]] = {}
    for part in out:
        for f in part.faces:
            owners.setdefault(f, []).append(part)
    for parts in owners.values():
        if len(parts) > 1:
            for part in parts:
                part.skipped = PIECES_SHARE_FACES
    for part in out:
        if part.skipped:
            part.faces = []
        elif not part.faces:
            part.skipped = NO_STRIP_FACES
    return out


def _seam_faces(faces: list[BMFace], near: list[BMVert], walls: set[BMEdge]) -> set[BMFace] | None:
    """The strip faces at the seam ``near[0]`` (also ``near[-1]``) on the start side of a piece's chain.

    A fan from the face on the chain edge from the seam to ``near[1]``, round the
    seam across every edge at it that is no wall (``walls`` hold the chain, the
    loop and the pieces' sides). None when it reaches the face on the chain edge
    into the seam, from ``near[-2]``: the two sides are not apart there.
    """
    seam = near[0]
    at_seam = {f for f in faces if seam in f.verts}
    first, last = _edge(seam, near[1]), _edge(near[-2], seam)
    fan = [f for f in at_seam if first in f.edges]
    seen = set(fan)
    for f in fan:  # grows while it is walked
        for e in f.edges:
            if seam in e.verts and e not in walls:
                for g in e.link_faces:
                    if g in at_seam and g not in seen:
                        seen.add(g)
                        fan.append(g)
    return None if not fan or any(last in f.edges for f in fan) else seen


def _ring_rows(anchors: list[int | None], inside: set[int], ring: list[BMVert], vert_of) -> tuple[list[int], list]:
    """(the chain indices anchored on a ring's points, in chain order round from the first of their run, the ring's
    vertices from the first one's to the last one's): empty where they are no one run round the chain."""
    n = len(anchors)
    mine = [x for x in range(n) if anchors[x] in inside]
    if not mine or len(mine) == n:
        return [], []
    start = next((x for x in mine if anchors[x - 1] not in inside), None)
    rows = [(start + t) % n for t in range(len(mine))]
    if any(anchors[x] not in inside for x in rows):  # anchored in two runs round the chain
        return [], []
    a, b = vert_of(anchors[rows[0]]), vert_of(anchors[rows[-1]])
    if a not in ring or b not in ring:
        return [], []
    i, j = ring.index(a), ring.index(b)
    return rows, [ring[(i + t) % len(ring)] for t in range((j - i) % len(ring) + 1)]


def _piece_rows(
    anchors: list[int | None], piece: list[int], count: int, closed: bool, starts_at_break: bool
) -> tuple[list[int], bool]:
    """A piece's chain vertices as chain indices in chain order, and whether the first is the cut vertex.

    They are the chain vertices anchored on the piece's points (``count`` in
    all), with those without an anchor (inside a lid) between them. Where the
    piece starts at a break whose right end no chain vertex anchors, the cut
    vertex comes first: the last chain vertex anchored on the break's left end.
    """
    n, inside = len(anchors), set(piece)
    rows, j, cut_vertex = [], 0, False
    if starts_at_break:
        left = (piece[0] - 1) % count
        k = next((x for x in range(n) if anchors[x] == left), None)
        if k is None:
            return [], False
        for _ in range(n):  # on to the last chain vertex anchored on the left end
            if anchors[(k + 1) % n] != left:
                break
            k = (k + 1) % n
        j = k + 1
        if piece[0] not in anchors:
            rows, cut_vertex = [k], True
    for _ in range(n):
        if not (closed or j < n) or not (anchors[j % n] is None or anchors[j % n] in inside):
            break
        rows.append(j % n)
        j += 1
    while rows and anchors[rows[-1]] is None:
        rows.pop()
    return rows, cut_vertex


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


def _shared_strips(build: BandBuild, barrier: list[BMEdge], halves: list[BMFace], seeds: list[set[int]]):
    """``_strip_faces`` for several pieces at once, each flooding from its own chain edges (``seeds``, by index), all
    together a step at a time: each face goes to the first to reach it. One list of faces per piece."""
    floods = [_strip_faces(build, barrier, halves, edges, order=True) for edges in seeds]
    owner: dict[BMFace, tuple[int, int]] = {}
    for k, flood in enumerate(floods):
        for depth, face in flood:
            if face not in owner or depth < owner[face][0]:
                owner[face] = (depth, k)
    return [[face for _depth, face in flood if owner[face][1] == k] for k, flood in enumerate(floods)]


def _strip_faces(
    build: BandBuild, barrier: list[BMEdge], halves: list[BMFace], edges: set[int] | None = None, order: bool = False,
) -> list:
    """The faces between the chain and its new loop, once the cut is in.

    A flood fill from the side faces of the chain edges (``edges``, by index,
    when given: one piece's; with ``order``, each face as (its depth in the
    flood, the face)), which crosses no chain edge and no ``barrier``
    edge: the new loop's, and at an open chain's ends the end paths' up to the
    loop's ends. It only enters faces the cut could reach: the band's real
    faces, the faces under its lids and both faces of every split. The band runs
    on round an open chain's end, the end paths keep the fill from leaking into
    the faces beyond the strip's ends. Nor does it cross an edge that more than
    two visible faces hold: a fin is no strip face.
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
        if edges is None or i in edges:
            seeds += [lp.face for lp in edge.link_loops if lp.vert is start and not lp.face.hide]
    reach = {*build.faces.values(), *(f for step in build.steps for f in step.region), *halves}
    seeds = [f for f in dict.fromkeys(seeds) if f in reach]
    out, seen, queue = [], set(seeds), deque((0, f) for f in seeds)
    while queue:
        depth, face = queue.popleft()
        out.append((depth, face) if order else face)
        for e in face.edges:
            if e in walls or sum(not f.hide for f in e.link_faces) > 2:
                continue
            for nxt in e.link_faces:
                if nxt in reach and nxt not in seen:
                    seen.add(nxt)
                    queue.append((depth + 1, nxt))
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


def stripe_for(
    build: BandBuild, applied: Applied, width: float, piece: int = 0
) -> tuple[uv_stripe_core.Strip, dict[int, BMFace]]:
    """The UV Stripe strip of a complete cut, with its faces by id.

    The chain is the near boundary (v = 0) and the new loop the far one (v =
    ``width``, the width the cut was built at). Each chain vertex with an anchor
    makes a rung; the faces round a chain vertex without one (inside a lid span)
    are left to the core's interior fill. An open chain's sides are the strip's
    border from each chain end to the new loop's end, off the chain and the loop.
    A closed chain's anchors may start mid-way round the new loop (a collapsed or
    welded seam, e.g. [2, 0, 1, 2]): its near and far loops are rotated so the
    rungs ascend along both (``uv_stripe_core.ascending_rungs``).

    A loop its breaks opened gives one open strip per piece
    (``Applied.piece_strips``), ``piece`` naming which; a piece that forms none
    raises its reason. A closed loop opened once is one piece whose near row
    starts and ends on the cut vertex: the UV splits there, a seam
    (``uv_stripe_core.Strip.corner_near``).

    Ids are ``BMVert.index`` and ``BMFace.index``, which must be current. Raises
    ``ValueError`` when the strip cannot be laid out: no strip faces, no length,
    a new loop through one vertex twice, rungs no rotation puts in order, or a
    layout ``uv_stripe_core.stripe_uvs`` rejects (tried here, before any UV is
    written, so the caller can skip just this strip).
    """
    corner_near = {}
    if applied.piece_strips:
        part = applied.piece_strips[piece]
        if part.skipped:
            raise ValueError(part.skipped)
        strip_faces, near, loop, rungs, closed = part.faces, part.near, part.far, part.rungs, False
        if near[0] is near[-1]:  # a seam: its corners on the start side open the row, the others close it
            corner_near = {
                (f.index, near[0].index): 0 if f in part.seam_faces else len(near) - 1
                for f in strip_faces if near[0] in f.verts
            }
    else:
        if piece != 0:  # a loop its breaks opened, its cut failed: none of its pieces has a strip
            raise ValueError(NO_STRIP_FACES)
        strip_faces, near, loop, closed = applied.strip_faces, build.chain, applied.loop_verts, build.band.closed
        rungs = [(k, a) for k, a in enumerate(applied.anchors) if a is not None]
    faces = {f.index: f for f in strip_faces}
    if not faces:
        raise ValueError(NO_STRIP_FACES)
    if not rungs:
        raise ValueError(NO_STRIP_LENGTH)
    corner_far = {}
    if len(set(loop)) < len(loop):  # a final state that comes back to a vertex: a tree's walk, a ridge's tip
        rungs, corner_far = _revisits(near, loop, rungs, strip_faces, closed)
    sides = ([], [])
    if not closed:
        chain, n = build.chain, len(build.chain)
        chain_edges = [_edge(chain[i], chain[(i + 1) % n]) for i in range(n if build.band.closed else n - 1)]
        walls = {*applied.loop_edges, *(e for e in chain_edges if e is not None)}
        sides = tuple(
            [v.index for v in _side_path(strip_faces, a, b, walls)]
            for a, b in ((near[0], loop[0]), (near[-1], loop[-1]))
        )
    verts = {v.index: tuple(v.co) for v in (*near, *loop)}
    verts.update((v.index, tuple(v.co)) for f in faces.values() for v in f.verts)
    strip = uv_stripe_core.Strip(
        verts=verts,
        faces={i: tuple(v.index for v in f.verts) for i, f in faces.items()},
        near=[v.index for v in near],
        far=[v.index for v in loop],
        rungs=rungs,
        closed=closed,
        height=width,
        sides=sides,
        corner_near=corner_near,
        corner_far=corner_far,
    )
    strip = uv_stripe_core.ascending_rungs(strip)
    if uv_stripe_core.strip_length(strip) <= core.EPS:  # raises ValueError for rungs out of order
        raise ValueError(NO_STRIP_LENGTH)
    uv_stripe_core.stripe_uvs(strip)
    return strip, faces


def _revisits(near: list[BMVert], loop: list[BMVert], rungs: list[tuple[int, int]], faces: list[BMFace],
              closed: bool) -> tuple[list[tuple[int, int]], dict[tuple[int, int], int]]:
    """(rungs, ``corner_far``) for a far row that passes one vertex more than once.

    A final state can come back to a vertex: a tree's walk passes each junction once per branch, a ridge's tip runs
    from its wall point and back to it. Inset's collapsed insets reach UV Stripe the same way: each corner on
    such a vertex takes the occurrence its face lies at (``uv_stripe_core.Strip.corner_far``), and the strip has
    triangles where the far row folds. The rungs' far indices (each the vertex's first occurrence) are moved onto
    occurrences that ascend in chain order, trying each occurrence for the first rung (a closed strip may start
    mid-way round). A face's corner takes the occurrence nearest the far indices of the rungs on its chain vertices;
    a face with none, the occurrence whose neighbours along the row are its corners too. Raises
    ``ValueError(LOOP_REVISITS)`` where no order of occurrences ascends.
    """
    nf = len(loop)
    at: dict[BMVert, list[int]] = {}
    for i, v in enumerate(loop):
        at.setdefault(v, []).append(i)
    rungs = sorted(rungs)
    # A closed far row is walked from the first rung's occurrence round (its positions taken relative to it), so a
    # chain whose first point is the walk's last still ascends; the strip's own rotation comes after
    # (``uv_stripe_core.ascending_rungs``).
    for first in at[loop[rungs[0][1]]]:
        def rel(i: int, first: int = first) -> int:
            return (i - first) % nf if closed else i

        out, prev = [(rungs[0][0], first)], rel(first)
        for k, a in rungs[1:]:
            cand = [(rel(i), i) for i in at[loop[a]]]
            if closed and loop[a] is loop[first]:  # back on the first rung's place, a whole turn on
                cand.append((nf, first))
            nxt = min((c for c in cand if c[0] >= prev), default=None)
            if nxt is None:
                break
            out.append((k, nxt[1]))
            prev = nxt[0]
        if len(out) == len(rungs):
            break
    else:
        raise ValueError(LOOP_REVISITS)
    far_of = {near[k]: i for k, i in out}

    def gap(i: int, j: int) -> int:
        d = abs(i - j)
        return min(d, nf - d) if closed else d

    corner_far = {}
    for f in faces:
        verts = set(f.verts)
        mine = [i for v, i in far_of.items() if v in verts]
        for v in verts:
            occ = at.get(v, ())
            if len(occ) < 2:
                continue
            if mine:
                best = min(occ, key=lambda i: (min(gap(i, r) for r in mine), i))
            else:
                best = next((i for i in occ if loop[(i - 1) % nf] in verts or loop[(i + 1) % nf] in verts), occ[0])
            corner_far[(f.index, v.index)] = best
    return out, corner_far


# --- modal preview and snapping ----------------------------------------------------


def preview_layers(
    builds: list[BandBuild], cuts: list[core.Cut], destructive: bool = False, tolerance: float = 0.0
) -> tuple[list[Vector], list[Vector], bool]:
    """What ``apply_cut`` would build from each (build, cut), for the viewport, in object space.

    Returns (the loop's segments as a flat list of endpoint pairs, the new
    vertices' points, whether any cut is clamped). The loop is ``apply_cut``'s own
    plan (with ``destructive`` and ``tolerance`` as there): points inside a lid are dropped and each
    lid piece is replaced by its ``project_step`` points, and no segment runs
    across a break. Points on an existing vertex are not new vertices; a segment
    no longer than the weld tolerance joins points that share one vertex and is
    left out. A cut ``apply_cut`` would refuse (``ValueError``) draws nothing.
    """
    segs: list[Vector] = []
    points: list[Vector] = []
    for build, cut in zip(builds, cuts):
        if not cut.points:
            continue
        weld = build.weld_for(destructive, tolerance)
        try:
            plan = _plan_loop(build, cut, weld, destructive)
            if destructive:  # the pre-edit checks ``apply_cut`` makes: a refused chain is drawn as nothing
                problem = _inset_reversed(build, plan) or _crossing(build, plan, weld)
                if problem:
                    raise ValueError(problem)
        except ValueError:
            continue
        for nodes, closed in zip(plan.nodes, plan.closes):
            loop = [plan.slots[s] for s in nodes]
            cos = [slot.position().copy() for slot in loop]
            ends = cos[1:] + (cos[:1] if closed and len(cos) > 2 else [])
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


# --- relay (destructive mode) ----------------------------------------------------

# The destructive mode's relay (``Relay``): a new loop counts as lying on a chain of existing edges while each of its
# points is within this fraction of the width slid since the last relay start of a vertex of that chain (or within
# the weld, raised by the Tolerance, when larger). The width is the one the loop meets the chain at (``relay_match``).
RELAY_MATCH_FRACTION = 0.1
# Past a width where the loop lies on such a chain, the slide is tried this fraction further on, to tell an open
# loop's end that stays put there.
RELAY_PROBE_FRACTION = 0.01
# The most legs one slide has, and the most edges a straight run between two matched vertices may have.
RELAY_MAX_STAGES = 64
RELAY_RUN_EDGES = 256
_RELAY_SKIPS = (core.OutOfRoom, ValueError, ArithmeticError, RuntimeError)


@dataclass
class RelayStage:
    """One leg of a relayed slide: ``build`` and its ``slider`` slide on from ``build.chain`` once the total width
    passes ``offset``, the width at which the leg before came to lie on that chain."""

    offset: float
    build: BandBuild
    slider: object  # the leg's WaveSlider


class Relay:
    """The destructive mode's slide of one chain on one side, passed on from row to row of existing edges.

    Where the new loop comes to lie on a chain of existing edges (``relay_chain``) at a width ``w0``, and there the
    slide stops (its limit is within the match distance past ``w0``) or an open loop's end stays put past it, the slide
    carries on from that chain: its band on the side away from the chain before (``build_band``), with a slider of its
    own (``make_slider``) for the width past ``w0``. The total width adds up: the cut at a total width ``W`` past ``w0``
    is the relay chain's cut at ``W - w0``. The rows between are existing edges already, so nothing is built there.
    Relays repeat, up to ``RELAY_MAX_STAGES`` legs; a relay chain never shares a vertex with an earlier leg's chain.
    Without a relay there is the one leg, ``build`` and ``slider`` as given, and nothing changes.

    The candidates for ``w0`` are the leg's limit and, for an open chain, the widths at which its loop reaches the far
    vertex of either end edge. The legs are found once per ``exact`` and kept. ``tris`` and ``angles`` are
    ``build_band``'s; the mesh must not change while the relay is in use.
    """

    def __init__(self, bm, build: BandBuild, slider, tolerance: float, make_slider, tris=None, angles=None):
        self.bm = bm
        self.tolerance = tolerance
        self._make_slider = make_slider
        self._tris = tris
        self._angles = angles
        self._first = RelayStage(0.0, build, slider)
        self._stages: dict[bool, list[RelayStage]] = {}

    def stages(self, exact: bool) -> list[RelayStage]:
        """Every leg of the slide in order, the first one the chain's own."""
        if exact not in self._stages:
            self._stages[exact] = self._find(exact)
        return self._stages[exact]

    def stage_at(self, width: float, exact: bool) -> RelayStage:
        """The leg that cuts at the total ``width``: the last one whose offset lies below it."""
        stages = self.stages(exact)
        return next((s for s in reversed(stages[1:]) if width > s.offset), stages[0])

    def is_last(self, stage: RelayStage, exact: bool) -> bool:
        return stage is self.stages(exact)[-1]

    def _find(self, exact: bool) -> list[RelayStage]:
        stages = [self._first]
        used = set(self._first.build.chain)
        while len(stages) < RELAY_MAX_STAGES:
            nxt = self._next(stages[-1], exact, used)
            if nxt is None:
                break
            stages.append(nxt)
            used.update(nxt.build.chain)
        return stages

    def _next(self, stage: RelayStage, exact: bool, used: set) -> RelayStage | None:
        """The leg after ``stage``, or None where its slide is not relayed."""
        build, slider = stage.build, stage.slider
        try:
            top = slider.limit(exact=exact, destructive=True)
        except _RELAY_SKIPS:
            return None
        if top <= 0.0:
            return None
        ends = self._end_snaps(build, slider, exact)
        for w0 in self._candidates(ends, top):
            match = relay_match(build, self.tolerance, w0)
            try:
                cut = slider.solve(w0, exact=exact, destructive=True)
            except _RELAY_SKIPS:
                continue
            # An end past the far vertex of its end edge by w0 has shot on: what of it runs past the row is the shot.
            shot = tuple(width is not None and width < w0 for width in ends)
            verts = relay_chain(build, cut, match, shot)
            if verts is None or used.intersection(verts):
                continue
            if top - w0 > match and not self._end_stays(build, slider, cut, exact, w0, top):
                continue  # the slide goes on past this chain by itself
            leg = self._leg(build, verts)
            if leg is None:
                continue
            try:
                reach = leg[1].limit(exact=exact, destructive=True)
            except _RELAY_SKIPS:
                continue
            if reach > match:
                return RelayStage(stage.offset + w0, *leg)
        return None

    @staticmethod
    def _end_snaps(build: BandBuild, slider, exact: bool) -> tuple[float | None, float | None]:
        """Per end of the loop (start, end): the width at which it reaches the far vertex of its end edge, or None."""
        out = []
        for end in build.band.end_edges:
            v = None if end is None else build.verts.get(end)
            target = None if v is None else snap_target(build, v)
            width = None
            if target is not None:
                try:
                    width = slider.snap_width(target, exact=exact, destructive=True)
                except _RELAY_SKIPS:
                    width = None
            out.append(width)
        return out[0], out[1]

    @staticmethod
    def _candidates(ends: tuple[float | None, float | None], top: float) -> list[float]:
        """The widths up to ``top`` at which the loop may lie on a chain of existing edges, smallest first: ``top``
        and the widths ``ends`` (``_end_snaps``) at which an end reaches the far vertex of its end edge."""
        return sorted({top, *(width for width in ends if width is not None and 0.0 < width <= top)})

    def _end_stays(self, build: BandBuild, slider, cut: core.Cut, exact: bool, w0: float, top: float) -> bool:
        """Whether an end of the open loop ``cut``, at ``w0``, stays where it is a little further on."""
        if build.band.closed or not cut.anchors or cut.anchors[0] is None or cut.anchors[-1] is None:
            return False
        try:
            later = slider.solve(min(top, w0 * (1.0 + RELAY_PROBE_FRACTION)), exact=exact, destructive=True)
        except _RELAY_SKIPS:
            return False
        if later.anchors[0] is None or later.anchors[-1] is None:
            return False
        weld = build.weld_for(True, self.tolerance)
        return any((Vector(cut.points[cut.anchors[k]].co) - Vector(later.points[later.anchors[k]].co)).length <= weld
                   for k in (0, -1))

    def _leg(self, build: BandBuild, verts: list[BMVert]) -> tuple[BandBuild, object] | None:
        """The band of the relay chain ``verts`` on the side away from ``build``'s chain, and its slider."""
        src = ChainSrc(verts=list(verts), closed=build.band.closed, index=build.chain_index)
        best = None
        for side in (1, -1):
            found, _err = build_band(self.bm, src, side, self._tris, self._angles)
            if found is None or not destructive_allowed(found):
                continue
            score = _away(found, build.chain)
            if score > 0.0 and (best is None or score > best[0]):
                best = (score, found)
        if best is None:
            return None
        return best[1], self._make_slider(best[1].band)


def _away(build: BandBuild, behind: list[BMVert]) -> float:
    """How far ``build``'s side faces lie from the chain ``behind``, across its own chain: positive on the far side."""
    band, chain = build.band, build.chain
    n = len(chain)
    total = 0.0
    for i in range(n if band.closed else n - 1):
        a, b = chain[i].co, chain[(i + 1) % n].co
        mid, along = (a + b) * 0.5, (b - a).normalized()
        corners = [Vector(band.verts[v]) for v in band.faces[band.side_faces[i]]]
        out = sum(corners, Vector()) / len(corners) - mid
        back = mid - min(behind, key=lambda v: (v.co - mid).length_squared).co
        total += (out - along * out.dot(along)).dot(back - along * back.dot(along))
    return total


def relay_match(build: BandBuild, tolerance: float, w0: float) -> float:
    """How far a point of the loop at width ``w0`` may lie from the vertex of the chain it comes to lie on
    (``relay_chain``): ``RELAY_MATCH_FRACTION`` of the width at which it meets that vertex, or the weld when larger.

    A loop that stops short of a row by ``g`` meets it at ``w0 + g``, so ``g <= f (w0 + g)``: ``g <= f w0 / (1 - f)``.
    """
    fraction = RELAY_MATCH_FRACTION
    return max(build.weld_for(True, tolerance), fraction * w0 / (1.0 - fraction))


def relay_chain(build: BandBuild, cut: core.Cut, match: float,
                shot: tuple[bool, bool] = (False, False)) -> list[BMVert] | None:
    """The chain of existing edges the new loop ``cut`` of ``build`` lies on, within ``match``; None where there is none.

    Each point of the loop must lie within ``match`` of a vertex, the vertices distinct and in loop order (points on
    one vertex count once), and each two in a row joined by an edge, or by a straight run of edges whose inner
    vertices lie within ``match`` of the line between them. A loop the destructive mode opened lies on no chain. The
    chain is open or closed as ``build``'s chain is.

    ``shot`` (start, end): that end of an open loop has shot on past its end edge. Its segment may then run on past
    the chain's last vertex: the points of that one segment past the last one on a vertex are its shot, not the chain.
    The segment itself must reach the chain past its anchor.
    """
    if not cut.points or cut.breaks or cut.rings:
        return None
    closed = build.band.closed
    near = [_point_vertex(build, p, match) for p in cut.points]
    lo, hi = 0, len(near)
    if not closed and len(cut.anchors) >= 2:
        if shot[1]:
            while hi > 0 and near[hi - 1] is None:
                hi -= 1
            if hi < len(near) and (cut.anchors[-2] is None or hi - 1 <= cut.anchors[-2]):
                return None
        if shot[0]:
            while lo < hi and near[lo] is None:
                lo += 1
            if lo > 0 and (cut.anchors[1] is None or lo >= cut.anchors[1]):
                return None
    hits: list[BMVert] = []
    for v in near[lo:hi]:
        if v is None:
            return None
        if not hits or hits[-1] is not v:
            hits.append(v)
    if closed and len(hits) > 1 and hits[0] is hits[-1]:
        hits.pop()
    if len(hits) < (3 if closed else 2) or len(set(hits)) != len(hits):
        return None
    path = [hits[0]]
    for a, b in zip(hits, hits[1:] + (hits[:1] if closed else [])):
        run = _edge_run(a, b, match)
        if run is None:
            return None
        path += run[1:]
    if closed:
        path.pop()
    return path if len(set(path)) == len(path) else None


def _point_vertex(build: BandBuild, p: core.SurfacePoint, match: float) -> BMVert | None:
    """The vertex nearest the loop point ``p`` among those of the element it lies on, when within ``match``."""
    if p.kind == "vert":
        ids = [p.vert]
    elif p.kind == "edge":
        ids = list(p.edge)
    else:
        face = build.faces.get(p.face)
        ids = [] if face is None else [v.index for v in face.verts]
    co = Vector(p.co)
    best = None
    for i in ids:
        v = build.verts.get(i)
        if v is None:
            continue
        gap = (v.co - co).length
        if gap <= match and (best is None or gap < best[0]):
            best = (gap, v)
    return None if best is None else best[1]


def _edge_run(a: BMVert, b: BMVert, match: float) -> list[BMVert] | None:
    """``a``, then the vertices of a run of visible edges from ``a`` to ``b`` along the line between them, ending on
    ``b``; None where there is no such run."""
    run, cur = [a], a
    for _ in range(RELAY_RUN_EDGES):
        if cur is b:
            return run
        step = None
        for e in cur.link_edges:
            if e.hide:
                continue
            u = e.other_vert(cur)
            if u is b:
                step = (-1.0, u)
                break
            if u in run or (u.co - b.co).length >= (cur.co - b.co).length:
                continue
            at, t = geometry.intersect_point_line(u.co, a.co, b.co)
            gap = (u.co - at).length
            if 0.0 < t < 1.0 and gap <= match and (step is None or gap < step[0]):
                step = (gap, u)
        if step is None:
            return None
        run.append(step[1])
        cur = step[1]
    return None
