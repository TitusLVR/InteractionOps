"""Smart Edge Slide destructive mode (D): the new loop moves as a wavefront.

Stdlib only (no bpy), like ``smart_edge_slide_core``, and unit-tested the same way.

``WaveSlider`` is a ``Slider`` whose ``solve``, ``limit`` and ``snap_width`` also
take ``destructive``. Off, each returns exactly what ``Slider``'s does. On, it
implies collapse, and the loop follows the wave's events: ``_wave`` works them
out once per ``exact``, in width order, and ``_plan`` and ``_solve`` replay them
up to the width asked for.

Events (``WaveEvent``):

- ``fold``: segments whose length along their chain edge reaches 0 are dropped
  and their vertices merge, as in collapse (C). Unlike C, an open chain's end
  segments fold too, so an end absorbs the neighbours that reach it. A merged
  group without an end sits where the offset lines of its outer chain edges
  meet (``Slider._meet``). ``data``: the dropped segments.
- ``used_up``: an open piece reaches its final state, and keeps it from there
  on while the other pieces go on (``_freeze``). Pressed onto its walls, every
  segment dropped (its two ends' groups meet), it leaves only its two ends'
  points, with a break between them (``Cut.breaks``), or one point where they
  coincide. Closed into a ridge, it keeps its points joined: a fold makes a
  merged group without an end whose outer chain edges turn by half a turn or
  more (a hairpin, or past it, ``_closes``), or every interior vertex is in one
  group and the piece's two ends meet on their walls; the group then sits on
  the mean of its members' points there. ``data``: ``(split, first, last)``,
  the piece's chain vertices first..last (unwrapped, as ``_pieces`` gives them)
  and, pressed onto its walls, its vertices before ``split`` going to the start's
  point and the rest to the end's; ``split`` is None for a ridge. Once every
  piece is in its final state ``solve`` returns that, clamped past it.
- ``wall_hit``: an interior vertex of a piece, not merged, runs into a wall: an
  end wall or the band border (an edge not held by exactly two band faces). The
  loop opens there (a cut): the vertex becomes two ends that slide apart along
  the wall, the left one on the offset line of the segment before it, the right
  one on that of the segment after it, so the width stays exact. A merged group
  that holds no end cuts the same way where its point reaches a wall, at its
  first member k; the right end takes the group. A closed loop that opens once
  is one open piece. The hit width comes from the vertex's ray, traced once per
  Slider as the plan's ``_ray_fits`` traces it (a group's from its point on along
  its line, once), so ``limit`` stays a plan-level bisection. ``data``:
  ``(k, wall)``, ``wall`` the wall edge (sorted vertex ids) or the wall vertex
  reached. Hits within ``tol`` of each other cut together (``_cut``).
- ``wall_end``: a piece end's wall gives out (``_wall_out``): its end or border
  path ends, or, for an end's group, the next step does not rise from its edge's
  line (``_rises``); or the end's segment would leave the band across the wall
  step it slides on, past a wall corner that turns in toward the segment
  (``_chord_stop``). An end on the open border (an open edge, or a vertex of
  one) has landed already, and stays there. Any other shoots on (``_shoot``):
  its offset line, at the distance it has, runs on past it, away from its piece,
  across faces, and the end lands on the first edge it crosses that lies within
  the Shoot Angle (``band.angles.shoot``) of perpendicular to the line, or that
  it cannot cross (an open edge, an end wall). A vertex the line passes within
  the anchor snap of, or reaches along one of its edges, decides by itself,
  whichever side noise passes it: it is the landing where an edge there gives a
  wall, or where it lies on the open border; else the line goes on through it
  (``_landing``, ``_vertex_wall``). The landing edge, on as a rail path within
  Rail Bend, is the end's new wall, and it slides along it as along any wall,
  keeping its width error frozen, so its distance from its chain edge's line
  stays the width less that error. With nothing to land on before the line
  leaves the band (through the chain, or at once), it stays where it is for
  every greater width (``_EndGroup.stuck``). The end waits on its point till
  its segment to the landing clears that point, on the chain's side, by
  ``_CLEARANCE``. Where its neighbour keeps up with the end's line (lags by no
  more than ``tol``), that is a fixed ``_CLEARANCE`` past where its wall gave
  out, whatever the noise; where the neighbour lags behind it (default mode's
  leaning rail vertices), which would otherwise pull the segment back across
  the old wall, it is where the segment clears (``_clear_width``). An end made
  at that very width by a cut or a fold waits only where its neighbour lags. A
  waiting end is not at rest, though it stands still; a fold that takes its
  segment measures its landing's group again against the next one. Then a
  second ``wall_end`` with the same data lands it; or, where the landing's wall
  gives out first, it gives the landing up and stays, data ``(slot, None)``. A
  jump holds from its own width. ``data``: ``(slot, landing)``, the end's slot
  (see ``_Wave``) and the edge (sorted vertex ids), the vertex, or None.
- ``contact``: a reflex vertex k of a closed loop (no cut yet), not merged,
  reaches a segment j of the loop that is not its neighbour, or a vertex v of
  it (``_contacts``, in k's own development along the chain, never one of the
  whole band). The loop splits there, as Smart Inset's wavefront does: one ring
  keeps the segments from k to j, the other those from j round to k; each
  drops the other's, which merge into one group in it at the contact, where its
  outer chain edges' offset lines meet (``_touch``). A ring that encloses no
  area there (a neck or a handle whose sides met all along it) is no ring: its
  vertices stay in the groups either side, and with one ring left the loop goes
  on as that ring (a ``fold`` of the other's segments follows). With two or more
  each goes on as a wave of its own (``_Wave.parts``, ``_child``) and finishes
  by itself; a ring used up to fewer than three segments is in its final state,
  as a tree is. Contacts at one width go before a fold there, and hold, as a
  fold does, from where the two sides are the weld apart. ``data``: ``(k, j,
  v)``, v None for a touch inside segment j. Open pieces and their walls follow
  below.

Pieces. An open chain is one piece from its start end to its end end; every cut
ends one piece and starts the next (``WaveSlider._pieces``). Each end of a piece
slides along its wall the way an open chain's end does: an end the wave made at
a cut is a group (``_EndGroup``) from the start, on the wall walked from the hit
point in its own direction (``_split_walls``), and keeps the width error the
vertex had there (none on an exact rail or a miter; a rail vertex in default
mode has a lean, which each end keeps frozen, as a group keeps its error from a
fold). Its piece's segments fold into it as into an open chain's end; that
holds for an end that stays where it is, on the open border or anywhere, too.
Pieces finish one by one: a piece in its final state (``used_up``) stays there,
its points those it had at that width (``_freeze``), while the others go on;
nothing of it moves, folds, cuts or shoots on any more. A piece used up while
another goes on holds from ``_ANCHOR_SNAP_TOL`` below its last fold, as that
fold would hold: just short of it the piece's two ends lie within the snap of
their walls' shared corner. An end's group passes a wall vertex at most
``_ANCHOR_SNAP_TOL`` along the wall past it (``_group_steps``), where its trace
sits on the vertex.

An end's group (``_EndGroup``) stays on the end's wall, its path followed on
from where the fold that last grew it left it. The end chain edge's offset line
no longer bounds the loop once its segment is gone, so the group keeps its
distance from the chain edge its remaining segment starts on: the width there,
less the width error it had at that fold. That is the rule a vertex keeps past
its rail path's end. The group moves at the honest rate after the fold, and
where the slide is exact so is the group. It only goes on forward along the
wall, and only while the wall leads away from that edge's line: a wall step
that does not rise from the line (level with it, by more than ``tol`` and
``_PARALLEL_SIN`` per unit of its length, or heading back toward it) ends the
wall for the group where the step starts, and the end shoots on there
(``wall_end``). So the group starts on the fold point and never skips ahead; one
whose wall gives out where it starts stays on it till it shoots on, at once.
Each later fold that grows the group measures its error again against its next
edge; but an end that waits to jump keeps its error through a fold (``_rewait``).
A merged vertex is traced straight to its group's point where that runs
clear; otherwise the group's holder's trace stands for it
(``WaveSlider._member``).

Event widths are exact. Between the widths where a rail path bends or ends, or
an end or end group goes on to the next edge of its path, each new vertex moves
on a line (``Slider._line``, ``_end_line``, ``_group_line``), so every segment
length is linear in width.

Ties: events within ``_Surface.tol`` of each other happen together, at the
first one's width, in (width, kind order ``KINDS``, chain index) order. A fold
drops every segment that folds within ``tol`` of the first in one event, its
segments sorted by chain index, so float noise cannot reorder them. Wall hits
within ``tol`` of each other cut together, in chain order, one event each. A
fold or a cut holds a hair early, from ``tol`` below its width; a fold at an end
of an open piece (its first or last segment left goes), and so a used-up state,
from ``_ANCHOR_SNAP_TOL`` below. Just before it the vertices about to merge
already snap onto one wall edge, and the segment between them would run along
it. A wall end holds from its own width.

The wave ends once every piece is in its final state, and stops where it
cannot go on: the loop as it stands no longer fits just before a fold or a cut
(``_fold_events`` checks the same), a vertex's ray leaves the band other than
into a wall (a merged vertex, or one running into its own chain), an open
chain's end has no wall to slide along at all, a closed loop without a cut
folds a group whose outer chain edges run opposite ways (within
``_PARALLEL_SIN`` of parallel, ``_meet_wave``, so noise cannot decide) or is
left with fewer than three segments. It also ends where nothing of the loop
moves any more: every end of the pieces left stays where it is and no other
vertex is left: each piece left then keeps the points it rests on. Each of these
final states, a used-up piece, a ridge or a loop at rest, holds from the anchor
snap below the width where it comes about (a loop at rest, from ``_REST_HOLD``
below where the last end's wall gave out), so that coincident stops of different
kinds give one limit, within 1e-6, whatever the noise; and that is the limit. A
piece at rest, or closed into a ridge, that lies along the open border leaves
only its points there, with breaks between them (``_along_wall``). (Two vertices on a straight run
of the chain that only come to no length apart, without folding, go on together
instead.) Past that width the plan has no room, as in C, and the wave stops
there. ``limit`` also samples full solves below that bound, since a trace
can run into a wall the plan does not see, and ``solve`` past the limit always
holds the cut at the limit, clamped.
"""

import bisect
import copy
import math
from dataclasses import dataclass, field, replace
from typing import NamedTuple

from .smart_edge_slide_core import (
    _ANCHOR_SNAP_TOL,
    _SEGMENT_MEET_TOL,
    _SNAP_SCAN,
    EPS,
    LIMIT_ITERS,
    SNAP_ITERS,
    Cut,
    OutOfRoom,
    Placement,
    Slider,
    SurfacePoint,
    Trace,
    Vec2,
    _band_scale,
    _bisect,
    _coincide,
    _cross2,
    _dot2,
    _ekey,
    _foot,
    _len2,
    _length,
    _sub,
    _sub2,
    _xf_mirrored,
    _InconsistentDevelopmentError,
    _xf_moved,
    trace_from_vertex,
    trace_segment,
)

KINDS = ("contact", "fold", "wall_hit", "wall_end", "used_up")  # the order of events at one width
_LIMIT_SCAN = 32  # even samples of the solve over (0, the plan's bound] that ``limit`` tries
_EVENT_PROBES = (1e-7, 1e-6, 2.0 * _ANCHOR_SNAP_TOL)  # how far below each wave event ``limit`` also tries the solve
# How far below the width where the solve's own failure sets in ``limit`` also tries it: every micron up to 1e-5, then
# coarser, as far as 4e-5.
_FAILURE_PROBES = (1e-7, *(k * 1e-6 for k in range(1, 11)), 2e-5, 4e-5)
# How far apart (x band scale) the destructive solve's segment end and its partner point may lie when the segment ends in
# the face holding that point: a long segment across slivers of a surface with some 1e-5 of modelling noise develops its
# last face a few 1e-6 off the partner's own development of it, which is no miss (``_wave_segment``).
_DEV_NOISE = 1e-6
_PARALLEL_SIN = 1e-6  # a merged group's outer chain edges this close to parallel (sine) have no meet point (D)
_V_COS = 1e-3  # a fold's group whose outer chain edges' cosine is below minus this turns back on itself: a V (D)
# A V whose outer chain edges' sine is below this (about 6 degrees short of a hairpin) is a near-hairpin: its sides' meet
# point moves at over ten times the width's rate, and default mode's width errors move it as much (``_fold_points``).
_HAIRPIN_SIN = 0.1
# How far a shot end's segment must pass its old point, on the chain's side, before the end jumps: neither of its traced
# ends, each snapped by up to the anchor snap, can then bring it back to touch the point (or the wall edges there).
_CLEARANCE = 2.0 * _ANCHOR_SNAP_TOL
# How far below where the loop comes to rest its final state holds from: a quarter of the anchor snap further than a
# used-up piece's. The loop at rest lies along the wall it rests against, so just short of a snap-wide hold its points
# lie the anchor snap from that wall, where float noise snaps some onto it and not others, and its segments leave the
# band. Still within 1e-6 of a used-up stop at the same width.
_REST_HOLD = 1.25 * _ANCHOR_SNAP_TOL
# How thin, in welds, a ring a contact makes may be (its mean thickness, twice its area over its perimeter) and still not
# be one: noise scale, where merging it into the rings either side cannot be seen. Anything thicker lives on as a ring
# and collapses to its own final state.
_THIN = 4.0


def _apply(m: tuple[float, ...], p: Vec2) -> Vec2:
    """The affine map ``m`` (``WaveSlider._devs_from``) applied to ``p``."""
    a, b, c, d, e, f = m
    return a * p[0] + b * p[1] + c, d * p[0] + e * p[1] + f


def _first_root(c0: float, c1: float, c2: float, span: float) -> float | None:
    """The least x in (0, span] where c0 + c1 x + c2 x^2 comes to 0, c0 being above 0; None where it does not."""
    if abs(c2) <= 1e-15 * (abs(c1) + abs(c0)):
        return -c0 / c1 if c1 < 0.0 and -c0 / c1 <= span else None
    disc = c1 * c1 - 4.0 * c2 * c0
    if disc < 0.0:
        return None
    r = math.sqrt(disc)
    q = -0.5 * (c1 + math.copysign(r, c1))
    roots = sorted(x for x in (q / c2, c0 / q if q != 0.0 else math.inf) if 0.0 < x <= span)
    return roots[0] if roots else None


def _snapped_together(p: SurfacePoint, q: SurfacePoint) -> bool:
    """Whether two new vertices lie on one mesh edge within the anchor snap of each other: one vertex then.

    Just before a fold the two ends of the segment folding can both snap onto
    one edge; the segment between them would run along that edge, which a trace
    cannot follow (float noise sends it to either side), and it is no longer
    than the snap anyway.
    """
    if _length(_sub(p.co, q.co)) > _ANCHOR_SNAP_TOL:
        return False
    if p.kind == q.kind == "edge":
        return p.edge == q.edge
    if p.kind == "vert" and q.kind == "edge":
        return p.vert in q.edge
    if q.kind == "vert" and p.kind == "edge":
        return q.vert in p.edge
    return p.kind == q.kind == "vert" and p.vert == q.vert


@dataclass(frozen=True)
class WaveEvent:
    """At ``width`` an event of ``kind`` (one of ``KINDS``) happens; ``data`` says what (see the module docstring)."""

    width: float
    kind: str
    data: tuple


@dataclass(frozen=True)
class _EndGroup:
    """An end's merged group, from the fold at ``width`` that last grew it, or the cut that made the end.

    ``edge`` is the chain edge its remaining segment starts on: ``j`` for the
    start's group of vertices 0..j, ``i - 1`` for the end's group i..n-1 (and the
    same for the ends of a piece). A point's distance from that edge's line is its
    y in ``chain[edge]``'s wedge frame. At width w the group lies where its wall's
    path (``WaveSlider._end_steps(wall)``), followed on from ``start`` on its step
    ``step``, first reaches distance ``w - error``. ``start`` is the fold or hit
    point, in the wall's frame (``WaveSlider._wall_frame``), and ``height`` its
    distance, so ``error`` is ``width - height``. ``wall``: True for the start's
    end path, False for the end's, else the key of a cut's wall or of the wall an
    end shot on to (``WaveSlider._shoot``). ``stuck``: the end stays on ``start``:
    for every greater width where it found nothing to land on, or sits on the
    open border; else till it jumps, where ``pending`` is: (its group on the
    landing, the landing, the side of the end's line its chain lies on, the width
    it jumps at, or None where its neighbour lags behind the end's line and it
    jumps once its segment clears ``start``, ``WaveSlider._clear_width``). A
    waiting end is never at rest.
    """

    width: float
    edge: int
    error: float
    step: int
    start: Vec2
    height: float
    wall: object = True
    stuck: bool = False
    pending: object = None


class _Step(NamedTuple):
    """One edge, ``u`` to ``far``, of the path an open chain's end slides along.

    ``face`` holds it, placed by ``xf`` in the end vertex's wedge frame, where
    ``u`` and ``far`` lie at ``at_u`` and ``at_far``.
    """

    face: int
    xf: tuple
    u: int
    far: int
    at_u: Vec2
    at_far: Vec2


@dataclass
class _Wave:
    """The wave of one mode (``WaveSlider._wave_events``).

    ``since[i]`` is the width from which ``events[i]`` holds: a hair below its
    width (``WaveSlider._hold``), and never above a later event's. Past ``stop`` the
    wave has no room. ``groups`` holds (event index, slot, group) for each end's
    group a fold makes or grows, or a cut makes: slot 0 for the open chain's start,
    1 for its end, and a cut's end its wall key (``WaveSlider._pieces``).
    ``complete``: every piece reached its final state, at the last event's width.
    ``parts``: where the loop split into rings (``contact``), each ring's own
    wave, a ``WaveSlider`` started from the ring (``WaveSlider._child``); they
    take over from ``split``, the last event's ``since``, on.
    """

    events: list[WaveEvent]
    since: list[float]
    stop: float
    groups: list[tuple[int, object, _EndGroup]]
    complete: bool = False
    parts: list = field(default_factory=list)
    split: float = math.inf


class _Hit(NamedTuple):
    """Where a vertex (or a merged group's point) first leaves the band: at ``width``, ``trace`` blocked at its end.

    ``heading`` is the direction it moves in, in the frame of ``trace``; None for
    a vertex, which heads along its route's bisector.
    """

    width: float
    trace: Trace
    heading: Vec2 | None = None


class WaveSlider(Slider):
    """A ``Slider`` that also solves in destructive mode; see the module docstring.

    ``tolerance`` is the operator's Tolerance: the destructive mode's weld is the larger of it and the automatic one
    (``_weld``). The bridge must build the cut with the same value (``apply_cut``'s ``tolerance``). Without
    ``destructive`` nothing uses it.
    """

    def __init__(self, band, tolerance: float = 0.0):
        if not tolerance >= 0.0:
            raise ValueError(f"tolerance must be 0 or more, not {tolerance!r}")
        super().__init__(band)
        self._waves: dict[bool, _Wave] = {}
        self._wave_limits: dict[bool, float] = {}
        self._bends: dict[bool, list[float]] = {}
        self._steps: dict[object, list[_Step]] = {}
        self._heights: dict[tuple, list[float]] = {}  # (wall, edge): far ends' distances; (wall, edge, "gain"): gains
        self._walls: dict[object, tuple[int, bool]] = {}  # a cut's wall key: (its chain vertex, ahead)
        self._hits: dict[tuple, _Hit | None] = {}
        self._turns: dict[tuple[int, int], tuple[float, float]] = {}  # (i, j): sine, cosine of chain edges i-1, j
        # Per mode, each merged group with (nearly) parallel outer chain edges: (fold width, fold point, normal) in its
        # first member's frame (``_meet_wave``).
        self._parallels: dict[bool, dict[tuple[int, int], tuple[float, Vec2, Vec2]]] = {False: {}, True: {}}
        self._scale = _band_scale(band)
        self._fan_reach: dict[int, float] = {}  # chain vertex k: how far its own faces reach from it (``_cut_connector``)
        # (k, ahead): the maps of the wedge frames h hops from chain[k] into chain[k]'s, developed along the chain
        # (``_devs_from``).
        self._devs: dict[tuple[int, bool], list[tuple[float, ...]]] = {}
        # Per mode, each group a contact made, or a sharp V's fold held by its arms: (its width, its point there in its
        # first member's frame). Below that width, in the hold just short of it, the group stays on that point; past a
        # contact, in a solve, while its meet point lies beyond it (``_meet_wave``).
        self._touched: dict[bool, dict[tuple[int, int], tuple[float, Vec2]]] = {False: {}, True: {}}
        # Per mode, each V a fold made whose sides' meet point lay more than the weld from its fold point: that offset,
        # in its first member's frame, which its meet point carries from then on (``_fold_points``).
        self._shifts: dict[bool, dict[tuple[int, int], Vec2]] = {False: {}, True: {}}
        self._solving = False  # set while ``_planned`` lays out a cut (``_meet_wave``)
        self._open: set[int] | None = None  # the vertices of the open border (``_open_verts``)
        # Per mode, each piece in its final state, by its first chain vertex mod n: its points as ``_piece_xy`` gives
        # them per vertex first..last (``_freeze``).
        self._frozen: dict[bool, dict[int, list[Vec2]]] = {False: {}, True: {}}
        # The weld the bridge builds with (``mesh_smart_edge_slide_bridge._tolerance``: 1e-6, or 4 float32 steps at the
        # band's largest coordinate): in D, points no further apart are one, and no cut carries a segment that short.
        # A Tolerance above it raises it: every hold, snap, thinness and contact test of the wave uses this one value.
        self._weld = max(1e-6, 4.0 * 2.0 ** -23 * max((abs(c) for p in band.verts.values() for c in p), default=0.0),
                         tolerance)
        # Per mode, where this wave starts: (width, the segments dropped there). Only a ring the loop split into
        # (``_child``) starts anywhere but at width 0 with nothing dropped.
        self._start: dict[bool, tuple[float, tuple[bool, ...]]] = {}
        self._part = False  # a ring the loop split into: it reaches its own final state, as a piece does
        # Per ``exact``: of the edges an end shot on past found nothing to land on crossed, the least turn of one from
        # perpendicular to its line, what the Shoot Angle must exceed to land there. Only the operator's hint reads it.
        self.shoot_misses: dict[bool, float] = {}
        self._shoot_miss: float | None = None  # ``_landing``'s, for the shot under way

    # --- Public API ---------------------------------------------------------------

    def solve(self, width: float, *, exact: bool = False, collapse: bool = False, destructive: bool = False) -> Cut:
        """``Slider.solve``; with ``destructive`` the wave's loop, clamped to its limit.

        Past the limit it is always the cut at the limit (the used-up state when
        the loop is used up there), ``clamped``: also where a wider width would
        fit again, past a stretch the solve does not get through. Below it a
        width that does not fit raises ``OutOfRoom``; there is no width to clamp to.
        """
        if not destructive:
            return super().solve(width, exact=exact, collapse=collapse)
        limit = self.limit(exact=exact, destructive=True)
        if width <= limit:
            return self._solve(width, exact, True, destructive=True)
        cut = self._solve(limit, exact, True, destructive=True)
        cut.clamped = True
        return cut

    def limit(self, *, exact: bool = False, collapse: bool = False, destructive: bool = False) -> float:
        """``Slider.limit``; with ``destructive`` where every piece is in its final state, or the largest width that
        fits before it.

        Every piece's final state holds from the anchor snap below the width it
        comes about at, and the last one's is the limit. The trace-free plan is
        bisected first, from there when the wave reaches it, as ``Slider.limit``
        does: what it rejects the solve rejects too. Below that bound the solve
        is tried on samples (``_solved_limit``). Worked out once per ``exact``.
        """
        if not destructive:
            return super().limit(exact=exact, collapse=collapse)
        if exact not in self._wave_limits:
            top = 4.0 * self._scale
            if self._used_up(exact) is not None:
                top = min(top, self._final_since(exact))
            planned = _bisect(top, lambda w: self._plan(w, exact, True, destructive=True))
            self._wave_limits[exact] = self._solved_limit(exact, planned)
        return self._wave_limits[exact]

    def cap_limit(self, width: float, *, exact: bool = False) -> None:
        """Lower the destructive limit of ``exact`` to ``width`` when it is below it.

        The bridge calls it where the cut at the limit cannot be built (``built_limit``): ``solve`` then clamps there,
        and ``snap_width`` and ``limit`` stop there, so what the preview shows is what confirming builds.
        """
        limit = self.limit(exact=exact, destructive=True)
        self._wave_limits[exact] = min(limit, max(width, 0.0))

    def _solved_limit(self, exact: bool, top: float) -> float:
        """The largest width up to ``top`` below which the solve fits at every sample: ``top`` when all of them do.

        The samples are ``_LIMIT_SCAN`` even widths and, below each wave event and
        below ``top``, the widths ``_EVENT_PROBES`` short of it, where a fold or
        the plan's own failure is close. The
        plan's failures last once they start, but a trace can run into a wall
        that bends, for a stretch the plan does not see, and come clear again
        past it. So the first sample that does not solve counts, bisected down
        from the sample before it; and since such a failure may come and go just
        below where it sets in for good, the widths ``_FAILURE_PROBES`` short of
        that are tried too, bisected down the same way from the first that fails.
        """

        def fits(width: float) -> bool:
            try:
                self._solve(width, exact, True, destructive=True)
            except OutOfRoom:
                return False
            return True

        def down(lo: float, hi: float) -> float:
            for _ in range(LIMIT_ITERS):
                mid = 0.5 * (lo + hi)
                if fits(mid):
                    lo = mid
                else:
                    hi = mid
            return lo

        probes = {top * i / _LIMIT_SCAN for i in range(1, _LIMIT_SCAN + 1)}
        probes.update(x - d for x in [top, *self._event_widths(exact)] for d in _EVENT_PROBES)
        good = [0.0]  # the widths seen to fit, in order
        for x in sorted(p for p in probes if 0.0 < p <= top):
            if fits(x):
                good.append(x)
                continue
            lo = down(good[-1], x)
            while True:  # a window just below where the failure sets in
                below = sorted(y for y in (lo - d for d in _FAILURE_PROBES) if y > 0.0)
                bad = next((y for y in below if not fits(y)), None)
                if bad is None:
                    return lo
                lo = down(max([g for g in good if g < bad] + [y for y in below if y < bad]), bad)
        return good[-1]

    def snap_width(
        self, target: SurfacePoint, *, exact: bool = False, collapse: bool = False, destructive: bool = False
    ) -> float | None:
        """``Slider.snap_width``; with ``destructive`` over the wave's plan up to its limit, event interval by interval.

        Between two of the wave's events (``_Wave.since``) the loop's state holds
        (its drops, cuts, ends and pieces in their final states), so its plan, and
        the target's offset from it (``_wave_offset``), is continuous in width;
        across an event it may jump. So the offset is taken at ``_SNAP_SCAN`` even
        widths and at both bounds of every event interval, each with that interval's
        state, and bisected within the interval that holds the first one at or past
        the target, with that interval's state throughout: past merges, cuts and
        landings alike. A target the loop jumps onto or past at an event is reached
        at that event's width; one within the anchor snap beyond the loop at the
        limit, at the limit, where the solve snaps onto it (final states hold from
        the snap below where they come about). A width where the plan has no room
        counts as a gap below the limit (None), as for ``Slider``, but at an
        interval's upper bound, where the next event takes over.
        """
        if not destructive:
            return super().snap_width(target, exact=exact, collapse=collapse)
        got = self._wave_snap(target, exact)
        if got is None and target.kind == "vert" and self._used_up(exact) is not None:
            # A vertex the final state lies on (a loop come to rest on it, pressed onto its wall) is reached at the
            # limit, whatever the offset says of the lone points there.
            top = self.limit(exact=exact, destructive=True)
            try:
                cut = self._solve(top, exact, True, destructive=True)
            except OutOfRoom:
                return None
            if any(p.kind == "vert" and p.vert == target.vert for p in cut.points):
                return top
        return got

    def _wave_snap(self, target: SurfacePoint, exact: bool) -> float | None:
        """``snap_width`` in destructive mode, by the offset alone (see ``snap_width``)."""
        spots = self._surf.in_frames(target)
        if spots is None:
            return None
        n, tol = len(self.band.chain), self._surf.tol

        def offset(width: float, lo: float) -> tuple[float, float]:  # with the state of the interval from ``lo`` on
            return self._offset_at(spots, width, lo, exact)

        try:
            chain = self._pieces((), exact)
            if self._wave_offset(spots, [(0.0, 0.0)] * n, {}, [False] * (n if self.band.closed else n - 1),
                                 chain)[0] <= 0.0:
                return None
            top = self.limit(exact=exact, destructive=True)
            if top <= 0.0:
                return None
            since = self._since_all(exact)
            even = [top * i / _SNAP_SCAN for i in range(1, _SNAP_SCAN + 1)]
            bounds = sorted({0.0, top, *(x for x in since if 0.0 < x < top)})
            for lo, hi in zip(bounds, bounds[1:]):
                xs = [lo, *(x for x in even if lo < x < hi), hi]
                for i, x in enumerate(xs):
                    if x == 0.0:
                        continue
                    try:
                        off, near = offset(x, lo)
                    except OutOfRoom:
                        if i == len(xs) - 1:  # where the next event takes over
                            continue
                        raise
                    if off > tol:
                        if x == top and near <= _ANCHOR_SNAP_TOL:
                            return top
                        continue
                    if i == 0:  # the event at ``lo`` took the loop onto or past the target
                        return lo
                    a, b = xs[i - 1], x
                    for _ in range(SNAP_ITERS):
                        mid = 0.5 * (a + b)
                        if offset(mid, lo)[0] > 0.0:
                            a = mid
                        else:
                            b = mid
                    return 0.5 * (a + b)
            off, near = offset(top, top)  # a final state that holds from the limit on
            if off <= tol or near <= _ANCHOR_SNAP_TOL:
                return top
        except OutOfRoom:  # a gap below the limit
            return None
        return None

    def _offset_at(self, spots: list[Vec2 | None], width: float, lo: float, exact: bool) -> tuple[float, float]:
        """``_wave_offset`` at ``width`` with the state the wave holds from ``lo`` on; past a split, of the ring nearest
        the target."""
        wave = self._wave_of(exact)
        if wave.parts and lo >= wave.split:
            return min((p._offset_at(spots, width, lo, exact) for p in wave.parts), key=lambda r: r[1])
        xy, alt, dropped, _, _, pieces, _ = self._planned(width, exact, bisect.bisect_right(wave.since, lo))
        return self._wave_offset(spots, xy, alt, dropped, pieces)

    def _wave_offset(self, spots: list[Vec2 | None], xy: list[Vec2], alt: dict[int, Vec2], dropped: list[bool],
                     pieces) -> tuple[float, float]:
        """(``Slider._offset`` of the wave's loop, the target's distance from it): segment k starts on ``alt[k]`` at a
        cut (see ``_piece_xy``).

        Where the target lies nearest a piece's end, past its segment, the end
        slides along its wall at its distance from that segment's chain edge's line:
        the target is beyond it while it lies further from that line (its y in the
        edge's frame), whichever way the segment leans to the wall. Where it lies
        as near two segments, on the extension of one of them past their shared
        point (a corner the side wraps round), it is beyond the loop when it is
        beyond either.
        """
        n, tol = len(xy), self._surf.tol
        ends = set()  # (segment, at its start): where a piece's end lies on its first or last segment left
        for first, last, _, _ in pieces:
            left = [t % n for t in range(first, last) if not dropped[t % n]]
            if left:
                ends |= {(left[0], True), (left[-1], False)}
        near = []
        for k in range(len(dropped)):
            p = spots[k]
            if p is None or dropped[k]:
                continue
            a, b = alt.get(k, xy[k]), self._surf.from_next(k, xy[(k + 1) % n])
            t, q = _foot(a, b, p)
            if (k, True) in ends and t == 0.0:
                off = p[1] - a[1]
            elif (k, False) in ends and t == 1.0:
                off = p[1] - b[1]
            else:
                e = _sub2(b, a)
                el = _len2(e)
                off = _cross2(e, _sub2(p, a)) / el if el > EPS else p[1] - a[1]
            near.append((_len2(_sub2(p, q)), off))
        if not near:
            return -math.inf, math.inf
        d = min(x for x, _ in near)
        return max(off for x, off in near if x <= d + tol), d

    # --- The wave -----------------------------------------------------------------

    def _wave_of(self, exact: bool) -> _Wave:
        """The wave (see the module docstring), worked out once per ``exact``."""
        if exact not in self._waves:
            self._waves[exact] = self._wave_events(exact)
        return self._waves[exact]

    def _wave(self, exact: bool) -> list[WaveEvent]:
        """The wave's events in width order."""
        return self._wave_of(exact).events

    def _stop(self, exact: bool) -> float:
        """The width past which the wave has no room; inf when it never stops."""
        return self._wave_of(exact).stop

    def _used_up(self, exact: bool) -> WaveEvent | None:
        """The ``used_up`` event that puts the wave's last piece in its final state, None when it has none."""
        wave = self._wave_of(exact)
        if not wave.complete:
            return None
        if wave.parts:  # the ring that reaches its final state last
            return max((p._used_up(exact) for p in wave.parts), key=lambda ev: ev.width)
        return wave.events[-1]

    def _final_since(self, exact: bool) -> float:
        """The width the wave's last final state holds from: past a split, its rings' last."""
        wave = self._wave_of(exact)
        return max(p._final_since(exact) for p in wave.parts) if wave.parts else wave.since[-1]

    def _event_widths(self, exact: bool) -> list[float]:
        """The widths of the wave's events, its rings' too past a split."""
        wave = self._wave_of(exact)
        return [e.width for e in wave.events] + [x for p in wave.parts for x in p._event_widths(exact)]

    def _since_all(self, exact: bool) -> list[float]:
        """``_Wave.since`` of the wave and, past a split, of its rings, in order."""
        wave = self._wave_of(exact)
        return sorted(wave.since + [x for p in wave.parts for x in p._since_all(exact)])

    def _child(self, exact: bool, width: float, mask: list[bool]) -> "WaveSlider":
        """A ring the loop splits into at ``width``: a wave of its own, started there with the segments ``mask`` drops
        (every one not in the ring). It shares this slider's surface and its caches of fixed geometry; its events,
        final states and limit are its own, and so are its records of groups a contact made or that run parallel
        (``_touched``, ``_parallels``): it starts with this wave's, and what it notes from there on is its own, so no
        ring is handed another's point for a group of the same chain vertices."""
        child = copy.copy(self)
        child._waves, child._wave_limits = {}, {}
        child._frozen = {False: {}, True: {}}
        child._touched = {key: dict(made) for key, made in self._touched.items()}
        child._shifts = {key: dict(made) for key, made in self._shifts.items()}
        child._parallels = {key: dict(made) for key, made in self._parallels.items()}
        child._start = {exact: (width, tuple(mask))}
        child._part = True
        return child

    def _homes(self, exact: bool) -> list[int]:
        """Past a split, the ring each chain vertex anchors on, by index in ``_Wave.parts``: the one it is a vertex of,
        not merged, where it was split off; else the one whose group holds it with the fewest members (the first of
        those)."""
        parts = self._wave_of(exact).parts
        n = len(self.band.chain)
        masks = [p._start[exact][1] for p in parts]
        out = []
        for k in range(n):
            live = [i for i, m in enumerate(masks) if not m[k - 1] and not m[k]]
            if live:
                out.append(live[0])
                continue
            sizes = []
            for m in masks:
                s, e = k, k
                while m[(s - 1) % n] and k - s < n:
                    s -= 1
                while m[e % n] and e - k < n:
                    e += 1
                sizes.append(min(e - s + 1, n))
            out.append(min(range(len(masks)), key=lambda i: (sizes[i], i)))
        return out

    def _state(self, exact: bool, width: float, count: int | None = None):
        """(how many of the wave's events hold at ``width``, the segments dropped by then, the cuts, the ends' groups,
        the pieces in their final states).

        The ends' groups are keyed by slot (see ``_Wave``); an open chain's ends
        start without one (None). The pieces in their final states map a piece's
        first chain vertex mod n to (the width it reached that state at, its
        ``used_up`` data). ``count`` instead takes the first ``count`` events.
        """
        wave = self._wave_of(exact)
        if count is None:
            count = bisect.bisect_right(wave.since, width)
        n = len(self.band.chain)
        start = self._start.get(exact)
        dropped = [False] * (n if self.band.closed else n - 1) if start is None else list(start[1])
        cuts: list[int] = []
        done: dict[int, tuple[float, tuple]] = {}
        for ev in wave.events[:count]:
            if ev.kind == "fold":
                for k in ev.data:
                    dropped[k] = True
            elif ev.kind == "wall_hit":
                cuts.append(ev.data[0])
            elif ev.kind == "used_up":
                done[ev.data[1] % n] = (ev.width, ev.data)
        ends: dict = {} if self.band.closed else {0: None, 1: None}
        for i, slot, group in wave.groups:
            if i < count:
                ends[slot] = group
        return count, dropped, tuple(sorted(cuts)), ends, done

    def _end_groups(self, exact: bool, width: float) -> tuple[_EndGroup | None, _EndGroup | None]:
        """The open chain's start's and end's groups at ``width`` (None for an end without one), as the wave left them.

        Nothing in the add-on calls it: the unit tests read the end groups through it.
        """
        ends = self._state(exact, width)[3]
        return ends.get(0), ends.get(1)

    # --- Pieces --------------------------------------------------------------------

    def _pieces(self, cuts: tuple[int, ...], exact: bool) -> list[tuple[int, int, object, object]]:
        """The open pieces of the loop: (first, last, start slot, end slot); none for a closed loop without a cut.

        A piece runs over chain vertices first..last, unwrapped (``last`` may pass
        n on a closed chain; take indices mod n), its start end standing for
        ``first`` and its end end for ``last``. A cut at k ends one piece at k and
        starts the next there: its ends' slots are the walls ``(exact, k, False)``
        and ``(exact, k, True)``. An open chain's own ends are slots 0 and 1.
        """
        n = len(self.band.chain)
        if self.band.closed:
            out = []
            for i, c in enumerate(cuts):
                d = cuts[i + 1] if i + 1 < len(cuts) else cuts[0] + n
                out.append((c, d, (exact, c, True), (exact, d % n, False)))
            return out
        bounds = [0, *cuts, n - 1]
        last = len(bounds) - 2
        return [
            (a, b, 0 if i == 0 else (exact, a, True), 1 if i == last else (exact, b, False))
            for i, (a, b) in enumerate(zip(bounds, bounds[1:]))
        ]

    @staticmethod
    def _slot_wall(slot) -> object:
        """The wall key of an end's slot: an open chain's own ends slide along end paths True and False."""
        return {0: True, 1: False}.get(slot, slot)

    def _wall_frame(self, wall) -> tuple[int, bool]:
        """(the chain vertex whose wedge frame ``wall``'s path lies in, whether its end starts a piece)."""
        if isinstance(wall, bool):
            return (0, True) if wall else (len(self.band.chain) - 1, False)
        return self._walls[wall]

    def _carry(self, p: Vec2, src: int, dst: int, ahead: bool) -> Vec2:
        """Point ``p`` of ``chain[src]``'s wedge frame in ``chain[dst]``'s, hopping ahead or back along the chain."""
        surf, n = self._surf, len(self.band.chain)
        k = src
        while k != dst:
            if ahead:
                p, k = surf.to_next(k, p), (k + 1) % n
            else:
                k = (k - 1) % n
                p = surf.from_next(k, p)
        return p

    def _piece_runs(self, piece, dropped: list[bool]) -> list[tuple[int, int]]:
        """The merged groups of a piece as (s, e), unwrapped: its segments s..e-1 are dropped."""
        first, last = piece[0], piece[1]
        n = len(self.band.chain)
        out, t = [], first
        while t < last:
            if dropped[t % n]:
                s = t
                while t < last and dropped[t % n]:
                    t += 1
                out.append((s, t))
            else:
                t += 1
        return out

    def _merges(self, k: int, dropped: list[bool], width: float, pieces) -> bool:
        """Whether segment ``k`` can fold at ``width``: an end holds the group it would join, or the group has a point.

        A group without an end sits where its outer chain edges' offset lines
        meet (``_meet``); edges that run parallel give it none.
        """
        trial = list(dropped)
        trial[k] = True
        n = len(self.band.chain)
        if not pieces:  # a closed loop
            for i, j in self._groups(trial):
                if (k - i) % n < (j - i) % n:  # segment k is one of i..j-1
                    return self._has_meet(i, j, width)
            return True
        for piece in pieces:
            first, last = piece[0], piece[1]
            for s, e in self._piece_runs(piece, trial):
                if (k - s) % n < e - s:  # segment k is one of s..e-1
                    if s == first or e == last:
                        return True
                    return self._has_meet(s % n, e % n, width)
        return True

    def _hold(self, segs: tuple[int, ...], dropped: list[bool], pieces) -> float:
        """How far below its width a fold of ``segs`` holds, ``dropped`` being the segments gone before it.

        ``_ANCHOR_SNAP_TOL`` for one at an end of an open piece, which drops its
        first or last segment left: just before it the vertices it merges snap
        onto one wall edge already. ``tol`` for any other.
        """
        n = len(self.band.chain)
        for first, last, _, _ in pieces:
            left = [t % n for t in range(first, last) if not dropped[t % n]]
            if left and (left[0] in segs or left[-1] in segs):
                return _ANCHOR_SNAP_TOL
        return self._surf.tol

    def _arms_hold(self, exact: bool, now: float, last: float, speed: float, segs, dropped, cuts, ends, done) -> float:
        """How far below ``now`` a closed loop's fold of ``segs`` (closing at ``speed``) holds by its arms: where its
        new group turns back on itself (a sharp V), from where the segment between the V's arms is ``_THIN`` welds
        long, at most: a hold is noise scale, never more, so every cut keeps its width honest (the spec). A V's arms
        closer than that farther from the fold (a near-hairpin's) are not held: that is a closing for the zip or a
        contact, not a hold. Never from before half the stretch since the last event, nor from where the loop past the
        fold has no layout (halved until it has); 0.0 where no group turns back."""
        n = len(self.band.chain)
        after = list(dropped)
        for k in segs:
            after[k] = True
        if after.count(False) < 3:  # the loop's last fold: its apex or ridge holds as such (``_THIN`` welds)
            return 0.0
        want, vs = 0.0, []
        for i, j in self._groups(after):
            if any((k - i) % n < (j - i) % n for k in segs):
                sine, cosine = self._turn(i, j)
                # A V turning back past a square corner by more than noise (a square corner's group is no V: noise must
                # not decide it), not a hairpin within noise of one (that closes, ``_zip``).
                if cosine < -_V_COS and abs(sine) > _PARALLEL_SIN:
                    want = _THIN * self._weld / speed  # (no 1/|sine|: the hold stays at noise scale)
                    vs.append((i, j))
        hold = min(want, 0.5 * (now - last))
        if hold <= self._weld / speed:
            return 0.0
        # In that hold a V's group stays on its point at the fold, as a contact's does short of it (``_meet_wave``):
        # its sides' meet point short of the fold lies far out beyond the V's tip, the sharper the further.
        made = self._touched[exact]
        added = []
        for i, j in vs:
            if (i, j) in made:
                continue
            try:
                made[(i, j)] = (now, self._meet_free(i, j, now, exact))
            except OutOfRoom:  # a hairpin: no point (the fold closes it, ``_closes``)
                continue
            added.append((i, j))
        while hold > self._weld / speed:
            # The loop past the fold, at the hold's start and half way to it, laid out with no segment folding back
            # (as ``_planned`` checks every solve).
            if all(self._lays_out(now - h, exact, after, cuts, ends, done) for h in (hold, 0.5 * hold)):
                return hold
            hold *= 0.5
        for key in added:
            del made[key]
        return 0.0

    def _fold_points(self, exact: bool, now: float, segs, before, cuts, ends, done) -> None:
        """Record, for each near-hairpin V (``_HAIRPIN_SIN``) a closed loop's fold of ``segs`` at ``now`` makes, its
        fold point's offset from its sides' meet point there, where that is more than the weld: the V carries it from
        then on (``_meet_free``), so it moves on from its fold point, along its meet point's line, with no jump.

        Its fold point is the mean of its members' points just before the fold
        (``before`` the drops). A V's outer chain edges run nearly opposite
        ways, so their offset lines meet at a point that default mode's width
        errors on them fling far along the V (grid_racket jittered(7, 0.03):
        1.9 back from the fold, across the room's ring); it keeps the error it
        had at the fold instead, as a group whose edges run parallel does
        (``_note_parallels``) and an end's group does. The wave's own layouts
        and the solve both take it, so its folds are found where the solve puts
        its points. Where the meet point lies within the weld of the fold point
        nothing is recorded.

        Exact mode records it too: its members' points can lie off the V's
        meet point at the fold where an earlier group held still (a contact's,
        just before), by as much as 0.9 (grid_racket jittered(7, 0.03)). This is
        the bounded near-hairpin exception to keeping every point on its offset
        lines: the error it carries off those lines is about |offset|·|sine|,
        under a tenth of the offset (``_HAIRPIN_SIN``), where the jump it
        replaces was the whole offset.
        """
        n = len(self.band.chain)
        after = list(before)
        for k in segs:
            after[k] = True
        if after.count(False) < 3:
            return
        made, pre = self._shifts[exact], None
        for i, j in self._groups(after):
            if (i, j) in made or (i, j) in self._touched[exact] or not any((k - i) % n < (j - i) % n for k in segs):
                continue
            sine, cosine = self._turn(i, j)
            if cosine >= -_V_COS or not _PARALLEL_SIN < abs(sine) < _HAIRPIN_SIN:
                continue
            try:
                meet = self._meet_free(i, j, now, exact)
                if pre is None:
                    pre = self._layout(now, exact, before, cuts, ends, done)[0]
            except OutOfRoom:
                continue
            pts = [self._carry(pre[(i + t) % n], (i + t) % n, i, False) for t in range((j - i) % n + 1)]
            p = (sum(x for x, _ in pts) / len(pts), sum(y for _, y in pts) / len(pts))
            if _len2(_sub2(meet, p)) > self._weld:
                made[(i, j)] = _sub2(p, meet)

    def _lays_out(self, width: float, exact: bool, dropped, cuts, ends, done) -> bool:
        """Whether the loop with these drops has a layout at ``width`` in which no segment left folds back."""
        try:
            xy, alt, _ = self._layout(width, exact, dropped, cuts, ends, done)
        except OutOfRoom:
            return False
        return all(dropped[k] or self._seg_len(k, xy, alt) >= -self._surf.tol for k in range(len(dropped)))

    def _wave_events(self, exact: bool) -> _Wave:
        """The wave: its events, when each holds from, where it stops, and the end groups its folds and cuts make.

        Works stretch by stretch, between the widths where a vertex's line bends
        (``_bend_widths``, and the end groups' ``_group_bends``). On a stretch every
        segment length is linear in width, so the first fold on it is exact. Its
        segments are dropped together with every one folding within ``tol`` of it,
        and the rest are worked out again. A free vertex's wall hit (``_hit``) is
        a fixed width; the first one, unless a fold comes first or within ``tol``,
        cuts the loop there (``_split``). Before each fold or cut the loop as it
        stands must still fit just short of it, and after it as it then stands.

        Where a stretch starts, a segment already folded back is dropped there,
        and so is one within ``tol`` of no length that does not grow again (a
        tolerant fold): its rate there is float noise, which cannot time it. A
        fold that lands within ``tol`` of a stretch's end is left to the next
        stretch's start, where that rule tells it from a touch, a segment that
        reaches no length at the bend and grows again past it: float noise picks
        the side of the bend it lands on. A tolerant fold of a segment that holds
        still is skipped where its group would have no point (``_merges``).

        A piece in its final state (``done``) takes no further part: its points
        stay as ``_freeze`` left them, and only the pieces still going on (``live``)
        fold, cut, shoot on or bend a stretch.
        """
        band, surf = self.band, self._surf
        n, closed = len(band.chain), band.closed
        m = n if closed else n - 1
        tol = surf.tol
        bends = self._bend_widths(exact)
        cap = 4.0 * self._scale
        events: list[WaveEvent] = []
        holds: list[float] = []
        log: list[tuple[int, object, _EndGroup]] = []
        ends: dict = {} if closed else {0: None, 1: None}
        cuts: tuple[int, ...] = ()
        group_bends: list[float] = []
        start = self._start.get(exact)  # a ring the loop split into starts where it did (``_child``)
        dropped, now, last = ([False] * m, 0.0, 0.0) if start is None else (list(start[1]), start[0], start[0])
        rest = now  # the widest width an event has come about at: where the loop comes to rest, if it does
        done: frozenset[int] = frozenset()  # the pieces in their final states, by first chain vertex mod n
        self._frozen[exact] = {}

        def wave(stop: float, complete: bool = False) -> _Wave:
            since = [ev.width - hold for ev, hold in zip(events, holds)]
            for i in range(len(since) - 2, -1, -1):
                since[i] = min(since[i], since[i + 1])
            return _Wave(events, since, stop, log, complete)

        def going(pieces) -> list:
            return [p for p in pieces if p[0] % n not in done]

        def bends_of(live, ends: dict) -> list[float]:
            return self._all_group_bends({s: ends[s] for p in live for s in (p[2], p[3])})

        def shoot(shots) -> None:  # a shot holds from its own width: below it the line has not passed the end yet
            nonlocal rest
            for slot, group, landing, at in shots:
                events.append(WaveEvent(now, "wall_end", (slot, landing)))
                holds.append(0.0)
                log.append((len(events) - 1, slot, group))
                rest = max(rest, at)

        skipped: set = set()  # contacts at ``skipped_at`` that made no ring: the folds there take them
        skipped_at = now
        while True:
            pieces = self._pieces(cuts, exact)
            live = going(pieces)
            try:  # an end whose wall gave out by now (where a step bends) shoots on
                grown, shots = self._shots(exact, now, live, ends, dropped, cuts, done=done)
                if shots:
                    self._layout(now, exact, dropped, cuts, grown, done)
            except OutOfRoom:
                return wave(now)
            if shots:
                shoot(shots)
                ends, last = grown, now
                group_bends = bends_of(live, ends)
            nxt = min(
                next((h for h in bends if h > now + tol), math.inf),
                next((h for h in group_bends if h > now + tol), math.inf),
            )
            mid = now + 1.0 if nxt == math.inf else 0.5 * (now + nxt)
            w1 = now + 1.0
            try:
                lines = self._wave_lines(exact, mid, pieces, ends, done)
                at0 = self._wave_xy(lines, pieces, dropped, now, exact, done)
                at1 = self._wave_xy(lines, pieces, dropped, w1, exact, done)
            except OutOfRoom:  # an end without a wall to slide along at all
                return wave(now)
            waiting = any(ends[s] is not None and ends[s].pending is not None for p in live for s in (p[2], p[3]))
            if pieces and at0 == at1 and not waiting:
                # Nothing of the loop moves any more: every end stays where it is. Each piece left is in its final
                # state, the points it rests on (not a hair short of them, where float noise would snap some onto the
                # wall they rest against and not others), held about as a used-up one is, from ``_REST_HOLD`` below
                # where the loop came to rest (an end's wall that holds a hair past its last vertex gives out there):
                # so stops of either kind that coincide give one limit, within 1e-6. An end that waits to jump is not
                # at rest, though it stands still: its landing moves on.
                # One width for all of it: the event's, the points frozen and the traces ``_solve`` takes. From ``rest``
                # on nothing moves, so the layout there is the one at ``now``. The shots of this stretch may carry a
                # width up to a snap above ``rest`` (where a wall that holds a hair past its last vertex gives out);
                # they stay before these events, and ``since`` is non-decreasing all the same (``wave``).
                try:
                    xy, alt, _ = self._layout(rest, exact, dropped, cuts, ends, done)
                except OutOfRoom:
                    return wave(rest - _REST_HOLD)
                for piece in live:
                    self._frozen[exact][piece[0] % n] = self._freeze(piece, None, xy, alt, dropped)
                    events.append(WaveEvent(rest, "used_up", (None, piece[0], piece[1])))
                    holds.append(_REST_HOLD)
                return wave(math.inf, True)
            still = {t % n for p in pieces if p[0] % n in done for t in range(p[0], p[1])}  # in their final states
            folds = []
            lens: dict[int, tuple[float, float]] = {}  # each segment left: (its length at ``now``, its rate)
            for k in range(m):
                if not dropped[k] and k not in still:
                    l0 = self._seg_len(k, *at0)
                    rate = self._seg_len(k, *at1) - l0
                    lens[k] = (l0, rate)
                    if l0 <= tol and rate <= tol:
                        # Folded to nothing where this stretch starts and not growing again: it folds here (its fold
                        # landed a float step past the stretch before, and a rate of float noise cannot time it). One
                        # still shrinking always folds, and stops the wave below if its group has no point. One that
                        # holds still only where its group has a point: two vertices on a straight run of the chain
                        # whose rail paths join go on together, at no length apart.
                        if rate < -tol or self._merges(k, dropped, now, live):
                            folds.append((now, k))
                    elif rate < 0.0:
                        folds.append((max(now, now - l0 / rate), k))
                    elif l0 < -tol:  # already folded where this stretch starts
                        folds.append((now, k))
            hits = []
            for k, j in self._free(live, dropped):
                h = self._hit(k, exact) if j == k else self._meet_hit(k, j, exact, now)
                if h is not None and h.width >= now - tol:
                    hits.append((max(now, h.width), k, j, h))
            at_fold = min(folds)[0] if folds else math.inf
            at_hit = min(hits)[0] if hits else math.inf
            at_end, end_slot = self._chord_stop(mid, now, live, dropped, ends, at0, at1)
            at_jump, jump_slot = math.inf, None  # a waiting end's segment clears its point: it lands
            for piece in live:
                for slot, ahead in ((piece[2], True), (piece[3], False)):
                    group = ends[slot]
                    if group is None or group.pending is None:
                        continue
                    due = group.pending[3]
                    if self._wall_out(slot, group.pending[0]) <= now + tol:  # its landing gave out first
                        x = now
                    elif due is not None:  # its neighbour keeps up: it jumps where it was due to
                        x = max(now, due)
                    else:
                        x = self._clear_width(now, mid, piece, ahead, group, dropped, at0, at1)
                    if x < at_jump:
                        at_jump, jump_slot = x, slot
            # A reflex vertex of a closed loop reaching a part of the loop that is not its neighbour (``_contacts``).
            if now != skipped_at:
                skipped.clear()
                skipped_at = now
            contacts = (self._contacts(now, min(nxt, cap), dropped, at0, at1, skipped, at_fold)
                        if not pieces and not done else [])
            at_contact = contacts[0][0] if contacts else math.inf
            at = min(at_fold, at_hit, at_end, at_jump, at_contact)
            # Nothing happens before the next bend. A fold within tol of it is left to the next stretch's start, which
            # tells it from a touch: on either side of a bend float noise decides, and the segment may grow again past it.
            if at > min(nxt, cap) - tol:
                if nxt > cap:
                    return wave(math.inf)
                now = nxt
                continue
            if at_contact <= min(at_fold, at_hit, at_end, at_jump) + tol:  # before a fold at the same width
                now = at_contact
                try:
                    xy_now = self._wave_xy(lines, pieces, dropped, now, exact, done)[0]
                except OutOfRoom:
                    return wave(now)
                made = self._touch(exact, now, dropped, [c[1:4] for c in contacts], xy_now)
                if made is None:  # every ring it would make encloses nothing: the folds there take it
                    skipped.update(c[1:4] for c in contacts)
                    skipped_at = now
                    continue
                rings, chords = made
                # A contact holds, as a fold does, from where the two sides are no further apart than the weld (just
                # short of it a cut would weld them into a loop run into the branch and back), but never from before
                # half the stretch since the last event.
                speed = max(c[4] for c in contacts)
                hold = min(max(tol, self._weld / speed if speed > 0.0 else 0.0), max(tol, 0.5 * (now - last)))
                for chord in chords:
                    events.append(WaveEvent(now, "contact", chord))
                    holds.append(hold)
                if len(rings) == 1:  # the other side of the contact encloses nothing: it merges into this ring
                    segs = tuple(k for k in range(m) if rings[0][k] and not dropped[k])
                    dropped = list(rings[0])
                    try:
                        self._layout(now, exact, dropped, cuts, ends, done)
                    except OutOfRoom:
                        return wave(now)
                    events.append(WaveEvent(now, "fold", segs))
                    holds.append(hold)
                    last, rest = now, max(rest, now)
                    continue
                # The loop splits into rings, each a wave of its own from here on (``_child``).
                parts = [self._child(exact, now, ring) for ring in rings]
                out = wave(min(part._stop(exact) for part in parts),
                           all(part._wave_of(exact).complete for part in parts))
                out.parts, out.split = parts, out.since[-1]
                return out
            if at_jump < min(at_fold, at_hit, at_end) - tol:
                now = at_jump
                landed, landing, _, _ = ends[jump_slot].pending
                landed = replace(landed, width=now)  # its group holds from the jump
                if self._wall_out(jump_slot, landed) <= now + tol:  # it gives the landing up, and stays
                    landed, landing = replace(ends[jump_slot], pending=None), None
                grown = {**ends, jump_slot: landed}
                try:
                    self._layout(now, exact, dropped, cuts, grown, done)
                except OutOfRoom:
                    return wave(now)
                shoot([(jump_slot, landed, landing, now)])
                ends, last = grown, now
                group_bends = bends_of(live, ends)
                continue
            if at_end < min(at_fold, at_hit) - tol:  # an end's segment would leave the band past a wall corner
                now = at_end
                try:  # the wall is no use to the end from here: it shoots on
                    grown, shots = self._shots(exact, now, live, ends, dropped, cuts, force=end_slot, done=done)
                    self._layout(now, exact, dropped, cuts, grown, done)
                except OutOfRoom:
                    return wave(now)
                shoot(shots)
                ends, last = grown, now
                group_bends = bends_of(live, ends)
                continue
            if at_hit < at_fold - tol:  # a vertex reaches a wall: the loop opens there
                now = at_hit
                batch = sorted((k, j, h) for w, k, j, h in hits if w <= at_hit + tol)  # together, in chain order
                opened = self._cut(exact, now, max(now - 2.0 * tol, 0.5 * (last + now)), batch, dropped, cuts, ends, done)
                if opened is None:
                    return wave(now)
                cuts, ends, made = opened
                for event, made_ends, shots in made:
                    events.append(event)
                    holds.append(tol)
                    log += [(len(events) - 1, slot, g) for slot, g in made_ends]
                    shoot(shots)
                last, rest = now, max(rest, now)
                group_bends = bends_of(going(self._pieces(cuts, exact)), ends)
                continue
            start, now = now, at_fold
            segs = {k for w, k in folds if w <= now + tol}
            # Points within the weld of each other past this fold are one: a segment left no longer than the weld
            # and not growing joins the fold, whichever side of it float noise put its own (bumped_arm turned 1e-9 once
            # folded c1 5.4e-8 after its neighbours, beside their group).
            weld = self._weld
            segs |= {k for k, (l0, rate) in lens.items() if rate <= tol and l0 + (now - start) * rate <= weld
                     and (rate < -tol or self._merges(k, dropped, now, live))}
            segs = tuple(sorted(segs))
            # A fold holds from where its segments are no longer than the weld, so no cut short of it carries one.
            speed = min((-lens[k][1] for k in segs if k in lens and lens[k][1] < -tol), default=0.0)
            hold = max(self._hold(segs, dropped, live), weld / speed if speed > 0.0 else 0.0)
            hold = min(hold, max(0.5 * (now - last), self._hold(segs, dropped, live)))
            if events and events[-1].width >= now - tol:  # set off by the event at this width: held with it
                hold = max(hold, holds[-1] - (now - events[-1].width))
            short = max(now - 2.0 * hold, 0.5 * (last + now))
            try:  # the loop as it stands, just short of where the fold takes over (collapse's schedule checks too)
                self._layout(short, exact, dropped, cuts, ends, done)
            except OutOfRoom:
                return wave(now)
            before = list(dropped)
            for k in segs:
                dropped[k] = True
            # A closed loop left with fewer than three segments: the stop stands for the fold, so no plan drops every
            # segment. A ring the loop split into (``_part``) is used up there instead: its final state, as a tree's.
            few = dropped.count(False) < 3
            tree = None
            if not pieces and (few or any(self._closes(i, j) for i, j in self._groups(dropped))):
                # A closed loop whose fold makes a group that closes (its sides meet, a hairpin) has nothing left
                # inside that group: the loop is its skeleton tree there, a walk round it whose points repeat where
                # it comes back. Its final state, as the fold leaves it: each group on its members' mean (key 0). So is
                # a loop left with fewer than three segments (an apex, or a ridge).
                pre = None
                for x in (now, now - tol, short):
                    try:
                        pre = self._layout(x, exact, before, cuts, ends, done)[0]
                        break
                    except OutOfRoom:
                        continue
                if pre is None:
                    return wave(now)
                tree = self._tree_points(pre, dropped)
                # A tree only where nothing is left to shrink: the walk encloses no area. A branch that closes while
                # the rest of the loop still encloses some (a racket's handle, an L's narrow arm) merges into the rest
                # as a contact there would merge it (``_zip``), whatever order the two come in, and the rest goes on.
                if not few and abs(self._ring_area(tree)) > tol * self._scale:
                    segs = tuple(sorted({*segs, *self._zip(exact, now, dropped, pre)}))
                    few = dropped.count(False) < 3
                    tree = self._tree_points(pre, dropped) if few else None
            if tree is not None:
                self._frozen[exact][0] = tree
                events += [WaveEvent(now, "fold", segs), WaveEvent(now, "used_up", (None, 0, n))]
                # An apex or a ridge holds from where the loop's last sides are ``_THIN`` welds apart: thinner than
                # that, just short of it, a ring is noise round it.
                thin = _THIN * weld / speed if few and speed > 0.0 else 0.0  # (a tree's sides meet at its fold)
                holds += [hold, max(_ANCHOR_SNAP_TOL, hold, min(thin, max(0.5 * (now - last), tol)))]
                return wave(math.inf, True)
            if not pieces:  # a V the fold leaves starts from its fold point (``_fold_points``)
                self._fold_points(exact, now, segs, before, cuts, ends, done)
            if not pieces and speed > 0.0:  # (a closed loop that goes on: a tree's fold holds as above)
                hold = max(hold, self._arms_hold(exact, now, last, speed, segs, before, cuts, ends, done))
            # The pieces this fold puts in their final states: pressed onto their walls (every segment dropped), or
            # closed into a ridge. Each keeps its points from here on, as they lie at the fold (``_freeze``).
            finished = []
            for piece in live:
                if all(dropped[t % n] for t in range(piece[0], piece[1])):
                    finished.append((piece, next(t for t in range(piece[0], piece[1]) if not before[t % n]) + 1))
                elif self._closes_ridge(piece, dropped) or self._ends_meet(piece, now, dropped, ends):
                    finished.append((piece, None))
            if finished:
                pre = None
                for x in (now, now - tol, short):  # the loop just before the fold (an end may lie a float step past
                    try:                            # its path's top at ``now``)
                        pre = self._layout(x, exact, before, cuts, ends, done)
                        break
                    except OutOfRoom:
                        continue
                if pre is None:
                    return wave(now)
                for piece, split in finished:
                    self._frozen[exact][piece[0] % n] = self._freeze(piece, split, pre[0], pre[1], dropped)
                done = done | {piece[0] % n for piece, _ in finished}
                live = going(pieces)
            grown = ends
            try:
                if live or not pieces:
                    self._note_parallels(exact, now, before, dropped, cuts, ends, live, done)
                if live:
                    grown = dict(ends)
                    for piece in live:
                        for slot, ahead in ((piece[2], True), (piece[3], False)):
                            grown[slot] = self._regroup(slot, ends[slot], piece, ahead, dropped, now)
                # A group whose wall heads back, or runs level, from its fold point on shoots on at once; held from
                # the fold's own width, while the fold holds a hair early, with the group on its fold point.
                shot_ends, shots = self._shots(exact, now, live, grown, dropped, cuts, done=done)
                self._layout(now, exact, dropped, cuts, shot_ends, done)
            except OutOfRoom:
                return wave(now)
            events.append(WaveEvent(now, "fold", segs))
            holds.append(hold)
            last, rest = now, max(rest, now)
            changed = [(slot, g) for slot, g in grown.items() if g is not ends.get(slot)]
            log += [(len(events) - 1, slot, g) for slot, g in changed]
            shoot(shots)
            # Used up, or a ridge: from the snap below its width, as its last fold, at an end, holds (and just short of
            # a ridge's fold the sides about to close lie within the weld of each other).
            for piece, split in finished:
                events.append(WaveEvent(now, "used_up", (split, piece[0], piece[1])))
                holds.append(max(_ANCHOR_SNAP_TOL, hold))  # never later than the fold that put it there
            if pieces and not live:  # every piece is in its final state
                return wave(math.inf, True)
            if changed or shots:
                ends = shot_ends
                group_bends = bends_of(live, ends)

    def _tree_points(self, pre: list[Vec2], dropped: list[bool]) -> list[Vec2]:
        """A closed loop's points ``pre`` (just before a fold) with each group of ``dropped`` on its members' mean."""
        n = len(self.band.chain)
        xy = list(pre)
        for i, j in self._groups(dropped) if not all(dropped) else [(0, None)]:
            members = list(range(n)) if j is None else [(i + t) % n for t in range((j - i) % n + 1)]
            pts = [self._carry(pre[k], k, i, False) for k in members]
            p = (sum(x for x, _ in pts) / len(pts), sum(y for _, y in pts) / len(pts))
            for k in members:
                xy[k] = self._carry(p, i, k, True)
        return xy

    def _ring_area(self, xy: list[Vec2]) -> float:
        """The signed area of a closed loop's points, each carried into ``chain[0]``'s frame."""
        n = len(self.band.chain)
        ring = [self._carry(xy[k], k, 0, False) for k in range(n)]
        return 0.5 * sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(ring, ring[1:] + ring[:1]))

    def _zip(self, exact: bool, now: float, dropped: list[bool], pre: list[Vec2]) -> list[int]:
        """Merge a closed loop's closing branch into the rest at ``now``: the segments it drops (``dropped`` is updated).

        A group that closes (``_closes``) has its outer chain edges' offset lines
        through its point, the two running opposite ways: its two outer segments
        lie on one line, along each other, the loop folded back over itself
        there. The shorter of them goes too, its far vertex into the group, as
        a contact of that vertex with the other one would merge it; and again,
        while the group closes, so the branch zips up as far as its sides lie
        on each other, to where they part (a room's walls). ``pre``: the loop's
        points just before the fold. The group it leaves, where its outer edges
        run parallel the same way, is recorded on the mean of its two end
        members' points there, its mouth (``_meet_wave``).
        """
        n = len(self.band.chain)
        added: list[int] = []
        for _ in range(n):
            if dropped.count(False) < 3:
                break
            closing = next(((i, j) for i, j in self._groups(dropped) if self._closes(i, j)), None)
            if closing is None:
                break
            i, j = closing
            a = (i - 1) % n
            la = _len2(_sub2(self._surf.from_next(a, pre[i]), pre[a]))
            lb = _len2(_sub2(self._surf.from_next(j, pre[(j + 1) % n]), pre[j]))
            k = a if la <= lb else j
            dropped[k] = True
            added.append(k)
        made = self._parallels[exact]
        for i, j in self._groups(dropped) if not all(dropped) else []:
            if not any((t - i) % n < (j - i) % n for t in added):
                continue
            sine, cosine = self._turn(i, j)
            if (i, j) in made or abs(sine) > _PARALLEL_SIN or cosine <= 0.0:
                continue
            q = self._carry(pre[j], j, i, False)
            made[(i, j)] = (now, (0.5 * (pre[i][0] + q[0]), 0.5 * (pre[i][1] + q[1])), self._parallel_normal(i, j))
        return added

    def _devs_from(self, k: int, ahead: bool) -> list[tuple[float, ...]]:
        """For h = 0..n, the map of the wedge frame h hops from ``chain[k]`` (ahead along the chain, or back) into
        ``chain[k]``'s, developed hop by hop along the chain between: (a, b, c, d, e, f) takes (x, y) to
        (ax + by + c, dx + ey + f). Worked out once per vertex and way."""
        key = (k, ahead)
        if key not in self._devs:
            surf, n = self._surf, len(self.band.chain)
            maps = [(1.0, 0.0, 0.0, 0.0, 1.0, 0.0)]
            t = k
            for _ in range(n):
                nxt = (t + 1) % n if ahead else (t - 1) % n
                if ahead:
                    hop = [surf.from_next(t, q) for q in ((0.0, 0.0), (1.0, 0.0), (0.0, 1.0))]
                else:
                    hop = [surf.to_next(nxt, q) for q in ((0.0, 0.0), (1.0, 0.0), (0.0, 1.0))]
                (ox, oy), (ux, uy), (vx, vy) = hop
                ha, hb, hc, hd, he, hf = ux - ox, vx - ox, ox, uy - oy, vy - oy, oy
                a, b, c, d, e, f = maps[-1]
                maps.append((a * ha + b * hd, a * hb + b * he, a * hc + b * hf + c,
                             d * ha + e * hd, d * hb + e * he, d * hc + e * hf + f))
                t = nxt
            self._devs[key] = maps
        return self._devs[key]

    def _contacts(self, now: float, top: float, dropped: list[bool], at0, at1, skipped,
                  fold: float = math.inf) -> list[tuple]:
        """The first contacts on this stretch, from ``now`` up to ``top``: (width, k, j, v, rate) for each vertex k
        of a closed loop (not merged) that reaches segment j, not its neighbour, at ``width``; v is None inside the
        segment, else the vertex of it k reaches (within the weld of it), and ``rate`` how fast the gap between them
        closes there. Every contact within ``tol`` of the first, in (k, j) order; none for a loop of fewer than four
        segments.

        A reflex vertex (its wedge's ``theta`` above pi by more than ``_PARALLEL_SIN``, so a straight vertex is never
        reflex by float noise, nor taken for one that is not: its side's neighbours reach as far) splits the loop as
        Smart Inset's does. One that is not reflex reaches a part of the loop
        that is not its neighbour only where the loop's sides close on each other: a sliver ring whose long sides meet
        a hair before its short ends fold (the jittered dumbbells' small rooms). For it the loop's vertices either side
        are its neighbours with their groups whole, so reaching one of those is a fold, not a contact; and it counts
        only short of ``fold`` (the stretch's first fold) by more than the weld: where a loop shrinks to its apex every
        vertex reaches every side at once, and that is the fold's (its root, a double one, is found a few 1e-9 early).

        Each is found in k's own development (``_devs_from``): j's ends carried into ``chain[k]``'s wedge frame hop
        by hop along the chain the shorter way between, never round the whole band, which is not flat in general.
        ``at0`` and ``at1`` are the loop's positions at ``now`` and ``now + 1``, so each point moves on a line between
        and the side of segment j that k lies on (a cross product) is quadratic in width. k reaches j where that
        side, ahead of j (where the band lies, in its frame), comes to nothing, its foot on the segment. ``skipped``:
        contacts that made no ring at ``now`` (``_touch``).
        """
        surf, n = self._surf, len(self.band.chain)
        tol, weld = surf.tol, self._weld
        if dropped.count(False) < 4:
            return []
        xy0, xy1 = at0[0], at1[0]
        span = top - now
        found = []
        for k in range(n):
            if dropped[k - 1] or dropped[k]:
                continue
            near = {k, (k - 1) % n, (k + 1) % n}
            theta = surf.wedge(k).theta
            reflex = theta > math.pi + _PARALLEL_SIN
            if not reflex and theta >= math.pi - _PARALLEL_SIN:  # straight: its side's neighbours reach as far
                continue
            if not reflex:
                # Not reflex: it reaches a part of the loop that is not its neighbour only where the loop's sides close
                # on each other (a sliver ring's long sides, a hair before its short ends fold). Its neighbours are
                # the loop's vertices either side of it, their groups whole: reaching one of those is a fold.
                t = (k - 1) % n
                while dropped[(t - 1) % n] and len(near) < n:
                    t = (t - 1) % n
                    near.add(t)
                t = (k + 1) % n
                while dropped[t] and len(near) < n:
                    t = (t + 1) % n
                    near.add(t)
            k0, k1 = xy0[k], xy1[k]
            for j in range(n):
                if dropped[j] or j == k or j == (k - 1) % n:
                    continue
                fwd, back = (j - k) % n, (k - j - 1) % n
                if fwd <= back:
                    maps = self._devs_from(k, True)
                    mp, mq = maps[fwd], maps[fwd + 1]
                else:
                    maps = self._devs_from(k, False)
                    mp, mq = maps[back + 1], maps[back]
                p0, q0 = _apply(mp, xy0[j]), _apply(mq, xy0[(j + 1) % n])
                p1, q1 = _apply(mp, xy1[j]), _apply(mq, xy1[(j + 1) % n])
                e0, d0 = _sub2(q0, p0), _sub2(k0, p0)
                de, dd = _sub2(_sub2(q1, p1), e0), _sub2(_sub2(k1, p1), d0)
                el = _len2(e0)
                if el <= tol:
                    continue
                c0 = _cross2(e0, d0)
                c1 = _cross2(e0, dd) + _cross2(de, d0)
                c2 = _cross2(de, dd)
                if c0 < -tol * el:  # behind the segment: swept already, or on its far side
                    continue
                if c0 <= tol * el:
                    x = 0.0 if c1 < 0.0 or (c1 == 0.0 and c2 < 0.0) else None
                else:
                    x = _first_root(c0, c1, c2, span)
                if x is None or x > span:
                    continue
                e = (e0[0] + x * de[0], e0[1] + x * de[1])
                d = (d0[0] + x * dd[0], d0[1] + x * dd[1])
                length = _len2(e)
                if length <= tol:
                    continue
                along = _dot2(d, e) / length  # how far along the segment its foot lies
                if along < -weld or along > length + weld:
                    continue
                v = None if weld < along < length - weld else (j if along <= weld else (j + 1) % n)
                if v is not None and v in near:  # its own neighbour: a fold, not a contact
                    continue
                if (k, j, v) not in skipped and (reflex or now + x < fold - weld):
                    found.append((now + x, k, j, v, -(c1 + 2.0 * c2 * x) / length))
        if not found:
            return []
        first = min(w for w, *_ in found)
        return sorted(c for c in found if c[0] <= first + tol)

    def _touch(self, exact: bool, now: float, dropped: list[bool], chords, xy: list[Vec2]):
        """The rings the closed loop (``dropped``) splits into at ``now`` where it touches itself: (the rings' masks,
        the chords (k, j, v) that split it); None when no ring with area is left but the loop itself.

        A contact of vertex k with segment j (or with its vertex v) splits the
        ring that holds both, as Smart Inset's split does: one ring keeps the
        segments from k on to j (to v's segment before it), the other those from
        j (from v) on round to k's before it. Each drops the other's, which merge
        into one group in it at the contact, where its outer chain edges' offset
        lines meet; segment j, touched inside, goes on in both. Chords taken in
        order, each in the ring that then holds k and j. A ring that encloses no
        area to speak of (its mean thickness, twice its area over its perimeter,
        within ``_THIN`` welds: a neck or a handle whose sides met all along) is not a
        ring: its vertices stay merged into the groups of the rings either side.
        A new group whose outer chain edges run parallel, the same way, gets its
        point there recorded, to carry on from (``_meet_wave``). ``xy``: the
        loop's points at ``now``.
        """
        n = len(self.band.chain)
        rings, applied = [list(dropped)], []
        for k, j, v in chords:
            r = next((i for i, ring in enumerate(rings) if not ring[k - 1] and not ring[k] and not ring[j]), None)
            if r is None:
                continue
            ring = rings[r]
            upto, back_from = (j, j) if v is None else ((v - 1) % n, v)
            a = [ring[t] or (t - k) % n > (upto - k) % n for t in range(n)]
            b = [ring[t] or (t - back_from) % n > (k - 1 - back_from) % n for t in range(n)]
            rings[r:r + 1] = [a, b]
            applied.append((k, j, v))
        if not applied:
            return None
        touched = {k for k, _, _ in applied} | {v for _, _, v in applied if v is not None}
        old = set(self._groups(dropped))

        def point(i: int, e: int) -> Vec2:  # a group's point at ``now``, in chain[i]'s frame: where its touch is
            if i in touched or e not in touched:
                return xy[i]
            return self._carry(xy[e], e, i, False)

        kept = []
        for ring in rings:
            live = [t for t in range(n) if not ring[t]]
            if len(live) < 3:
                continue
            corners = []
            for t in live:
                if not ring[t - 1]:
                    corners.append(self._carry(xy[t], t, live[0], False))
                else:
                    i = t
                    while ring[(i - 1) % n]:
                        i = (i - 1) % n
                    corners.append(self._carry(point(i, t), i, live[0], False))
            area = 0.5 * sum(p[0] * q[1] - q[0] * p[1] for p, q in zip(corners, corners[1:] + corners[:1]))
            perimeter = sum(_len2(_sub2(q, p)) for p, q in zip(corners, corners[1:] + corners[:1]))
            if 2.0 * abs(area) > _THIN * self._weld * perimeter:
                kept.append(ring)
        if not kept or kept == [list(dropped)]:
            return None
        made = self._parallels[exact]
        for ring in kept:
            for i, e in self._groups(ring):
                if (i, e) in old:
                    continue
                self._touched[exact].setdefault((i, e), (now, point(i, e)))
                sine, cosine = self._turn(i, e)
                if (i, e) in made or abs(sine) > _PARALLEL_SIN or cosine <= 0.0:
                    continue
                made[(i, e)] = (now, point(i, e), self._parallel_normal(i, e))
        return kept, applied

    def _parallel_normal(self, i: int, j: int) -> Vec2:
        """The unit mean of the side normals of chain edges i-1 and j, in ``chain[i]``'s frame: the way a group i..j
        whose outer edges run parallel moves (``_note_parallels``)."""
        theta = self._surf.wedge(i).theta
        o, u = self._carry((0.0, 0.0), j, i, False), self._carry((0.0, 1.0), j, i, False)  # edge j's normal
        nx, ny = math.sin(theta) + u[0] - o[0], -math.cos(theta) + u[1] - o[1]
        nl = math.hypot(nx, ny)
        return nx / nl, ny / nl

    def _cut(self, exact: bool, now: float, short: float, batch, dropped, cuts, ends: dict, done=frozenset()):
        """The wall cuts at ``now`` of ``batch``, (k, j, hit) for each vertex k or group k..j, in chain order.

        Returns (the cuts and ends after them, and per cut: its event, its two new
        ends as (slot, group), and the shots of those whose wall heads back or runs
        level from the hit point on, as ``_shots`` gives them). The batch cuts
        together: a vertex that reaches its wall at the same width (within
        ``tol``) does not count against the loop as it stands after an earlier one.
        None where the wave stops there instead: the loop as it stands does not
        fit at ``short``, just below the cuts; a wall runs into the chain
        (``_split``); or the opened loop does not fit at ``now``. ``done``: the
        pieces in their final states (see ``_wave_events``), which no cut touches.
        """
        n = len(self.band.chain)
        try:
            self._layout(short, exact, dropped, cuts, ends, done)
        except OutOfRoom:
            return None
        out = []
        for k, j, hit in batch:
            made = self._split(k, j, exact, hit)
            if made is None:  # it reached its own chain, or a wall that runs into the chain
                return None
            wall, left, right = made
            ends = {**ends, left.wall: left, right.wall: right}
            cuts = tuple(sorted((*cuts, k)))
            try:
                pieces = [p for p in self._pieces(cuts, exact) if p[0] % n not in done]
                ends, shots = self._shots(exact, now, pieces, ends, dropped, cuts, only=(left.wall, right.wall),
                                          done=done)
            except OutOfRoom:
                return None
            out.append((WaveEvent(now, "wall_hit", (k, wall)), ((left.wall, left), (right.wall, right)), shots))
        try:
            self._layout(now, exact, dropped, cuts, ends, done)
        except OutOfRoom:
            return None
        return cuts, ends, out

    def _all_group_bends(self, ends: dict) -> list[float]:
        """The widths past which any end's group, or the group a waiting end jumps to, goes on to the next edge of
        its wall."""
        groups = [g for g in ends.values() if g is not None]
        groups += [g.pending[0] for g in groups if g.pending is not None]
        return sorted(h for g in groups for h in self._group_bends(g.wall, g))

    def _wave_lines(self, exact: bool, mid: float, pieces, ends: dict, done=frozenset()) -> list:
        """(a, d) for each vertex of each piece (one row for a closed loop): it lies at a + w * d on the stretch.

        A piece's ends follow their group when they have one, else their end or
        border path; merged vertices are moved onto their group's point after. A
        piece in its final state (``done``) has no row (None): it stays put.
        """
        n = len(self.band.chain)
        if not pieces:
            return [[self._line(k, exact, mid) for k in range(n)]]
        rows = []
        for first, last, start, end in pieces:
            if first % n in done:
                rows.append(None)
                continue
            row = [self._slot_line(start, ends[start], mid)]
            row += [self._line(t % n, exact, mid) for t in range(first + 1, last)]
            row.append(self._slot_line(end, ends[end], mid))
            rows.append(row)
        return rows

    def _wave_xy(self, lines, pieces, dropped: list[bool], width: float, exact: bool, done=frozenset()):
        """The positions ``lines`` give at ``width``, merged groups on their points (see ``_layout``)."""
        base = [None if row is None else [(a[0] + width * d[0], a[1] + width * d[1]) for a, d in row] for row in lines]
        if not pieces:
            return self._merge_wave(base[0], dropped, width, exact), {}
        return self._piece_xy(pieces, base, dropped, width, exact, done)

    def _free(self, pieces, dropped: list[bool]) -> list[tuple[int, int]]:
        """Where a wall can cut the loop: (k, j) for each vertex k inside a piece (or a closed loop) that is not
        merged (j = k), and each merged group k..j that holds no end.

        Segment j starts at vertex j, so after a cut the right end's chain edge is j.
        """
        n = len(self.band.chain)
        if not pieces:
            free = [(k, k) for k in range(n) if not dropped[k - 1] and not dropped[k]]
            return free + self._groups(dropped)
        free = [(t % n, t % n) for first, last, _, _ in pieces for t in range(first + 1, last)
                if not dropped[(t - 1) % n] and not dropped[t % n]]
        return free + [(s % n, e % n) for piece in pieces for s, e in self._piece_runs(piece, dropped)
                       if s != piece[0] and e != piece[1]]

    def _chord_stop(self, mid: float, now: float, pieces, dropped: list[bool], ends: dict, at0, at1):
        """(the first width from ``now`` on this stretch at which an end's segment heads out across its wall step,
        that end's slot).

        ``at0`` and ``at1`` are the positions at ``now`` and ``now + 1``, so each
        segment is linear in width between. The band lies on one side of the wall
        step an end slides on: right of the step's direction for an end that starts
        a piece, left for one that ends it (in the wedge frames, whose angles grow
        into the side). The end's segment must leave it into that side. Once the
        end passes a wall corner that turns in toward the segment, the segment
        would cut across the corner, outside the band: there the end shoots on
        instead. (inf, None) when no end does; an end that stays put has no step.
        """
        surf, n = self._surf, len(self.band.chain)
        best, which = math.inf, None
        for first, last, start, end in pieces:
            left = [t for t in range(first, last) if not dropped[t % n]]
            if not left:
                continue
            for slot, ahead in ((start, True), (end, False)):
                k = (left[0] if ahead else left[-1]) % n  # the end's segment
                group = ends[slot]
                if group is not None and group.stuck:
                    continue
                wall = self._wall_of(slot, group)
                try:
                    i = self._end_step(wall, mid) if group is None else self._group_hit(wall, group, mid)[0]
                except OutOfRoom:
                    continue
                step = self._end_steps(wall)[i]
                src, fwd = self._wall_frame(wall)
                e = _sub2(self._carry(step.at_far, src, k, fwd), self._carry(step.at_u, src, k, fwd))
                el = _len2(e)
                if el == 0.0:
                    continue
                g = []
                for xy, alt in (at0, at1):
                    a, b = alt.get(k, xy[k]), surf.from_next(k, xy[(k + 1) % n])
                    chord = _sub2(b, a) if ahead else _sub2(a, b)  # from the end toward its neighbour
                    g.append((-1.0 if ahead else 1.0) * _cross2(e, chord) / el)  # > 0: into the band
                g0, g1 = g
                if g0 < -surf.tol:
                    at = now
                elif g1 < g0:
                    at = now + (g0 + surf.tol) / (g0 - g1)
                else:
                    continue
                if at < best:
                    best, which = at, slot
        return best, which

    def _bend_widths(self, exact: bool) -> list[float]:
        """The widths where a vertex's line bends: its rail path bends or ends, or an end turns onto its next edge."""
        if exact not in self._bends:
            band = self.band
            n = len(band.chain)
            inner = range(n) if band.closed else range(1, n - 1)
            out = {h for k in inner for h in self._aim(k, exact).hs[1:]}
            if not band.closed:
                for at_start in (True, False):
                    out.update(self._end_bends(at_start))
            self._bends[exact] = sorted(out)
        return self._bends[exact]

    def _turn(self, i: int, j: int) -> tuple[float, float]:
        """(sine, cosine) between the directions of chain edges i-1 and j, the outer edges of the group i..j."""
        key = (i, j)
        if key not in self._turns:
            surf, n = self._surf, len(self.band.chain)
            theta = surf.wedge(i).theta
            p, q, k = (0.0, 0.0), (1.0, 0.0), j  # edge j's direction, carried into chain[i]'s frame
            while k != i:
                k = (k - 1) % n
                p, q = surf.from_next(k, p), surf.from_next(k, q)
            dx, dy = q[0] - p[0], q[1] - p[1]
            # Edge i-1 runs from chain[i-1], at angle theta, to chain[i] at the origin; (sin, -cos) is its side normal.
            c, s = math.cos(theta), math.sin(theta)
            self._turns[key] = (s * dx - c * dy, -(c * dx + s * dy))
        return self._turns[key]

    def _has_meet(self, i: int, j: int, width: float) -> bool:
        """Whether the outer chain edges of the group i..j cross (``Slider._meet``); within ``_PARALLEL_SIN`` of
        parallel they do not, whatever the noise."""
        if abs(self._turn(i, j)[0]) <= _PARALLEL_SIN:
            return False
        try:
            self._meet(i, j, width)
        except OutOfRoom:
            return False
        return True

    def _meet_wave(self, i: int, j: int, width: float, exact: bool) -> Vec2:
        """The point of the merged group i..j (no end) at ``width``, in ``chain[i]``'s frame.

        Where its outer chain edges i-1 and j cross, ``Slider._meet``'s point:
        on both offset lines. ``Slider._meet`` calls the edges parallel only
        within ``EPS``, so float noise in an edge's direction once decided between
        no point and one flung far along the edges (a 1e-9 tilt moved
        jittered_u(30, 0.4)'s limit by 1.04). Here edges within ``_PARALLEL_SIN``
        of parallel do not cross, whatever the noise:

        - pointing the same way (a straight run, where a notch, or two of its
          vertices, folded together) the group carries on from its fold point
          along the edges' shared normal (``_note_parallels``): on their shared
          offset line in exact mode, keeping the error it had at the fold in
          default mode, as an end's group does. Continuous at the fold.
        - pointing opposite ways (a hairpin) it has no point: the wave stops.

        A group a contact made stays on the contact point below the contact's
        width, in the hold just short of it, rather than run on back past it
        across the other ring (``_touch``). Past the contact it stays there too
        while its meet point still lies beyond it, where its sides would meet
        across the other ring (a thin spike's tip, whose sides close at a hair
        past the touch, comes back at many times the width's rate): until the
        meet point, coming back along its line, passes the contact point.

        Collapse (C) keeps ``Slider._meet``.
        """
        touched = self._touched[exact].get((i, j))
        if touched is not None:
            at, point = touched
            if width < at:
                return point
            if not self._solving:  # (the wave's own layouts keep its points' lines: its folds are found on them)
                return self._meet_free(i, j, width, exact)
            m0 = self._meet_free(i, j, at, exact)
            v = _sub2(self._meet_free(i, j, at + 1.0, exact), m0)
            vv = v[0] * v[0] + v[1] * v[1]
            if vv > 0.0 and width - at < (_sub2(point, m0)[0] * v[0] + _sub2(point, m0)[1] * v[1]) / vv:
                return point
        return self._meet_free(i, j, width, exact)

    def _meet_free(self, i: int, j: int, width: float, exact: bool) -> Vec2:
        """``_meet_wave`` with no contact held: where the group's outer edges' offset lines meet, or its parallel run;
        a V's carrying the offset it had from its fold point (``_fold_points``)."""
        sine, cosine = self._turn(i, j)
        if abs(sine) > _PARALLEL_SIN:
            shift = self._shifts[exact].get((i, j))
            m = self._meet(i, j, width)
            return m if shift is None else (m[0] + shift[0], m[1] + shift[1])
        record = self._parallels[exact].get((i, j)) if cosine > 0.0 else None
        if record is None:
            raise OutOfRoom(f"the chain edges around vertex {self.band.chain[i]} run (nearly) parallel")
        at, (px, py), (nx, ny) = record
        return (px + (width - at) * nx, py + (width - at) * ny)

    def _closes(self, i: int, j: int) -> bool:
        """Whether the outer chain edges of the merged group i..j turn by half a turn or more: a hairpin (opposite ways,
        within ``_PARALLEL_SIN`` of parallel) or past it.

        Such a group's sides have closed onto each other. Within ``_PARALLEL_SIN``
        of a hairpin its edges have no meet point (``_meet_wave``); past one their
        meet point runs back over the group's own members, into ground the loop
        has swept already, and on into the chain.
        """
        sine, cosine = self._turn(i, j)
        return cosine <= 0.0 and sine <= _PARALLEL_SIN

    def _closes_ridge(self, piece, dropped: list[bool]) -> bool:
        """Whether a merged group of the open ``piece`` that holds no end closes (``_closes``): the piece closes into a
        ridge there, its final state."""
        n = len(self.band.chain)
        return any(self._closes(s % n, e % n) for s, e in self._piece_runs(piece, dropped)
                   if s != piece[0] and e != piece[1])

    def _freeze(self, piece, split: int | None, xy: list[Vec2], alt: dict[int, Vec2], dropped: list[bool]):
        """The final points of ``piece``, per vertex first..last as ``_piece_xy`` gives them, from its points ``xy`` and
        ``alt`` just before the fold that put it in its final state; ``dropped`` after that fold.

        Pressed onto its walls (``split``), its vertices before ``split`` lie on its
        start's point and the rest on its end's. Closed into a ridge (``split``
        None), each merged group lies on one point: a group that holds an end on
        that end's point, any other on the mean of its members' points, where its
        sides have just met (default mode's rails leave them a width error apart).
        """
        first, last = piece[0], piece[1]
        n = len(self.band.chain)
        row = [alt.get(first % n, xy[first % n])] + [xy[t % n] for t in range(first + 1, last + 1)]
        if split is not None:
            return [self._carry(row[0], first % n, t % n, True) if t < split else
                    self._carry(row[-1], last % n, t % n, False) for t in range(first, last + 1)]
        for s, e in self._piece_runs(piece, dropped):
            if s == first:
                p = row[0]
            elif e == last:
                p = self._carry(row[-1], last % n, s % n, False)
            else:
                pts = [self._carry(row[t - first], t % n, s % n, False) for t in range(s, e + 1)]
                p = (sum(x for x, _ in pts) / len(pts), sum(y for _, y in pts) / len(pts))
            for t in range(s, e + 1):
                row[t - first] = self._carry(p, s % n, t % n, True)
        return row

    def _note_parallels(self, exact: bool, width: float, before: list[bool], dropped: list[bool], cuts, ends, pieces,
                        done=frozenset()):
        """Record each group a fold at ``width`` makes whose outer chain edges run (nearly) parallel, the same way.

        Its point there is the mean of its members' points just before the fold
        (``before`` the drops: they meet there, up to the width errors of default
        mode's rails), and it moves on along the mean of the two edges' side
        normals (``_meet_wave``). ``pieces``: the pieces still going on (all of
        them but those in ``done``).
        """
        n = len(self.band.chain)
        if pieces:
            runs = [(s % n, e % n) for piece in pieces for s, e in self._piece_runs(piece, dropped)
                    if s != piece[0] and e != piece[1]]
        else:
            runs = self._groups(dropped)
        made, pre = self._parallels[exact], None
        for i, j in runs:
            sine, cosine = self._turn(i, j)
            if (i, j) in made or abs(sine) > _PARALLEL_SIN or cosine <= 0.0:
                continue
            if pre is None:
                pre = self._layout(width, exact, before, cuts, ends, done)
            xy, alt = pre[0], pre[1]
            members = [(i + t) % n for t in range((j - i) % n + 1)]
            pts = [self._carry(alt.get(k, xy[k]), k, i, False) for k in members]
            p = (sum(x for x, _ in pts) / len(pts), sum(y for _, y in pts) / len(pts))
            made[(i, j)] = (width, p, self._parallel_normal(i, j))

    def _ends_meet(self, piece, width: float, dropped: list[bool], ends: dict) -> bool:
        """Whether every interior vertex of the open ``piece`` is in one group and its two ends meet at ``width``.

        The two end segments then run from the ends' shared point to the group
        and back, one on the other: the piece closes into a ridge, from that
        point to the group's. ``ends``: the ends' groups by slot.
        """
        first, last, start, end = piece
        n = len(self.band.chain)
        if last - first < 2 or self._piece_runs(piece, dropped) != [(first + 1, last - 1)]:
            return False
        try:
            a = self._end_point(self._wall_of(start, ends[start]), ends[start], width)
            b = self._carry(self._end_point(self._wall_of(end, ends[end]), ends[end], width), last % n, first % n,
                            False)
        except OutOfRoom:
            return False
        return _len2(_sub2(a, b)) <= _SEGMENT_MEET_TOL

    # --- Ends and their groups ------------------------------------------------------

    def _end_normal(self, at_start: bool) -> Vec2:
        """Unit normal of the end chain edge toward the side, in the end vertex's wedge frame (as ``_border_hit``)."""
        if at_start:
            return (0.0, 1.0)
        theta = self._surf.wedge(len(self.band.chain) - 1).theta
        return (math.sin(theta), -math.cos(theta))

    def _end_steps(self, wall) -> list[_Step]:
        """The edges of the path an end slides along, in its wall's frame (``_wall_frame``); worked out once.

        An open chain's end (``wall`` True for its start, False for its end) slides
        along its end path when it has an end edge, else along the border path,
        walked as ``_border_hit`` walks it. A cut's wall is walked from the hit
        point when the cut is made (``_split``).
        """
        if wall not in self._steps:
            surf = self._surf
            out: list[_Step] = []
            path = surf.end_path(wall)
            if path is not None:
                verts, pts, holders = path
                for i in range(len(verts) - 1):
                    out.append(_Step(*holders[i], verts[i], verts[i + 1], pts[i], pts[i + 1]))
            else:
                k = 0 if wall else len(self.band.chain) - 1
                u = self.band.chain[k]
                f, came, xf = surf.frame_face(k)
                for _ in range(len(surf.edge_faces)):
                    step = surf.border_step(f, xf, u, came)
                    if step is None:
                        break
                    f, xf, far = step
                    dev = surf.dev(f, xf)
                    out.append(_Step(f, xf, u, far, dev[u], dev[far]))
                    u, came = far, u
            self._steps[wall] = out
        return self._steps[wall]

    def _end_bends(self, at_start: bool) -> list[float]:
        """The widths past which ``_border_hit`` takes the next edge of the end's path: one per path vertex."""
        nx, ny = self._end_normal(at_start)
        return [nx * s.at_far[0] + ny * s.at_far[1] + _ANCHOR_SNAP_TOL for s in self._end_steps(at_start)]

    def _end_step(self, at_start: bool, width: float) -> int:
        """The index of the path edge ``_border_hit`` takes at ``width``: the first whose far end is past the line."""
        nx, ny = self._end_normal(at_start)
        steps = self._end_steps(at_start)
        return next(
            (i for i, s in enumerate(steps) if nx * s.at_far[0] + ny * s.at_far[1] - width >= -_ANCHOR_SNAP_TOL),
            len(steps) - 1,
        )

    def _end_line(self, at_start: bool, width: float) -> tuple[Vec2, Vec2]:
        """(a, d): the end lies at a + w * d (``_end_xy``, wedge frame) for w on the stretch of widths around ``width``."""
        f, xf, u, far, _, _ = self._border_hit(at_start, width)
        dev = self._surf.dev(f, xf)
        (px, py), (qx, qy) = dev[u], dev[far]
        nx, ny = self._end_normal(at_start)
        gp, gq = nx * px + ny * py, nx * qx + ny * qy
        if gp == gq:
            return (px, py), (0.0, 0.0)
        c = 1.0 / (gp - gq)  # _end_xy: p + (q - p) * (gp - w) * c
        ex, ey = qx - px, qy - py
        return (px + ex * gp * c, py + ey * gp * c), (-ex * c, -ey * c)

    def _path_heights(self, wall, edge: int) -> list[float]:
        """Each wall step's far point's distance from chain edge ``edge``'s line (its y in that edge's frame)."""
        key = (wall, edge)
        if key not in self._heights:
            src, ahead = self._wall_frame(wall)
            self._heights[key] = [self._carry(s.at_far, src, edge, ahead)[1] for s in self._end_steps(wall)]
        return self._heights[key]

    def _regroup(self, slot, group: _EndGroup | None, piece, ahead: bool, dropped: list[bool], width: float):
        """A piece end's group once the segments in ``dropped`` are gone at ``width``: ``group`` itself unless it grew.

        ``ahead``: the end starts ``piece`` (its group is first..edge), else it
        ends it (edge+1..last). An open chain's end has no group (None) till a
        fold first grows one; a cut's ends have one from the cut.
        """
        first, last = piece[0], piece[1]
        n = len(self.band.chain)
        if not dropped[(first if ahead else last - 1) % n]:
            return group
        left = [t for t in range(first, last) if not dropped[t % n]]
        edge = (left[0] if ahead else left[-1]) % n
        if group is not None and (group.edge == edge or group.stuck):  # an end that stays put stays, grown or not
            return group if group.edge == edge or group.pending is None else self._rewait(group, ahead, edge, width)
        wall = self._wall_of(slot, group)
        if group is None:
            start, step = self._end_xy(wall, width), self._end_step(wall, width)
        else:
            start, step = self._group_xy(wall, group, width), self._group_hit(wall, group, width)[0]
        return self._grown(wall, width, edge, start, step)

    def _rewait(self, group: _EndGroup, ahead: bool, edge: int, width: float) -> _EndGroup:
        """A waiting end (``group``) whose remaining segment starts on chain edge ``edge`` from the fold at ``width``
        on.

        It keeps the width error it had where its wall gave out: it waits on, for
        the same landing and as long, with its group there put on the landing wall
        at the width less that error from ``edge``'s line (``_on_wall``), and its
        side of the end's line is that edge's. Where the landing wall does not reach
        that distance, the landing is no use to it any more: it waits no longer and
        stays on its point, a group whose wall gives out there once the width less
        its error reaches the point's distance, and shoots on again then
        (``_shots``), along ``edge``'s line. A landing on the open border, where the
        end stays, stays as it is.
        """
        landed, landing, _, due = group.pending
        src = self._wall_frame(group.wall)[0]
        d, normal = self._edge_axes(edge, src, ahead)
        height = self._carry(group.start, src, edge, ahead)[1]
        if not landed.stuck:
            moved = self._on_wall(landed.wall, edge, group.error, width)
            if moved is None:
                return _EndGroup(width, edge, group.error, 0, group.start, height, group.wall)
            landed = moved
        pending = (landed, landing, math.copysign(1.0, _cross2(d, normal)), due)
        return replace(group, edge=edge, height=height, pending=pending)

    def _on_wall(self, wall, edge: int, error: float, width: float) -> _EndGroup | None:
        """The group on ``wall`` at ``width``, measured against chain edge ``edge``, keeping width error ``error``: where
        the wall, from its first point on along the steps that rise from ``edge``'s line (``_group_hit``), first
        reaches the distance ``width - error`` from it. None where it does not: it starts beyond that distance, or
        gives out short of it."""
        steps = self._end_steps(wall)
        src, ahead = self._wall_frame(wall)
        start = steps[0].at_u
        h0 = self._carry(start, src, edge, ahead)[1]
        if h0 > width - error + self._surf.tol:
            return None
        g = _EndGroup(width, edge, error, 0, start, h0, wall)
        try:
            x, step = self._group_xy(wall, g, width), self._group_hit(wall, g, width)[0]
        except OutOfRoom:
            return None
        if self._group_out(wall, g)[0] < width - self._surf.tol:
            return None
        return self._grown(wall, width, edge, x, step)

    def _grown(self, wall, width: float, edge: int, start: Vec2, step: int) -> _EndGroup:
        """The group of an end on ``wall`` from ``start``, on its step ``step``, measured against chain edge ``edge``.

        A start within the anchor snap of its step's far end lies on that vertex: the group goes on from the next
        step, whichever side of the vertex noise put the start (a cut whose hit lands a hair short of a wall vertex).
        """
        steps = self._end_steps(wall)
        while step + 1 < len(steps) and _len2(_sub2(start, steps[step].at_far)) <= _ANCHOR_SNAP_TOL:
            step += 1  # on the step's far end already: go on from the next one
        src, ahead = self._wall_frame(wall)
        height = self._carry(start, src, edge, ahead)[1]
        return _EndGroup(width, edge, width - height, step, start, height, wall)

    def _group_hit(self, wall, group: _EndGroup, width: float) -> tuple[int, Vec2, float]:
        """(step, its start, the start's distance): the wall edge on which ``group`` lies at ``width``.

        The group goes on along the path step by step from its own, which starts
        at its fold point, up to the first whose far end reaches the distance
        ``width - error``. A step that does not rise from the edge's line
        (``_rises``: level with it, or heading back toward it) ends the wall for
        the group where it starts: going on would skip ahead along the wall to
        where it gets far enough again. So does the path's end. Past that the end
        shoots on (``_group_out``). A group that stays put (``stuck``) stays on
        its start.
        """
        if group.stuck:
            return group.step, group.start, group.height
        heights = self._path_heights(wall, group.edge)
        target = width - group.error
        for i, start, ya, past in self._group_steps(wall, group):
            if not self._rises(wall, group.edge, i, start, ya):
                if i == group.step and target <= ya + self._surf.tol:  # gives out where it starts: there till it shoots
                    return i, start, ya
                break
            if heights[i] >= target - past:
                return i, start, ya
        raise OutOfRoom(f"an end's group runs out of wall at width {width:.6f}")

    def _rises(self, wall, edge: int, i: int, start: Vec2, ya: float) -> bool:
        """Whether step ``i`` of ``wall`` rises from chain edge ``edge``'s line, from ``start`` (at distance ``ya``) on.

        It must gain more than ``tol`` in distance, and more than ``_PARALLEL_SIN``
        per unit of its length: a step that runs level with the line is level
        whatever the float noise, which would otherwise send the end racing along
        it at a rate of one over the noise.
        """
        rise = self._path_heights(wall, edge)[i] - ya
        return rise > self._surf.tol and rise > _PARALLEL_SIN * _len2(_sub2(self._end_steps(wall)[i].at_far, start))

    def _group_steps(self, wall, group: _EndGroup):
        """(i, its start, the start's distance, how far past its far end's distance the group stays on it) per step.

        A group takes the next step only once the width needs more than the far
        end's distance by ``_ANCHOR_SNAP_TOL`` times the step's gain in distance per
        unit of its length, so its point runs at most ``_ANCHOR_SNAP_TOL`` along the
        wall past the far vertex, where its trace snaps onto that vertex. A step
        that gains no distance gets no such slack.
        """
        steps, heights = self._end_steps(wall), self._path_heights(wall, group.edge)
        gains = self._path_gains(wall, group.edge)
        start, ya = group.start, group.height
        for i in range(group.step, len(steps)):
            if i > group.step:
                start, ya = steps[i].at_u, heights[i - 1]
            yield i, start, ya, _ANCHOR_SNAP_TOL * min(1.0, max(0.0, gains[i]))

    def _path_gains(self, wall, edge: int) -> list[float]:
        """Each wall step's gain in distance from chain edge ``edge``'s line per unit of its length, over the whole step.

        Taken over the whole step, not from a group's start on it, which can lie
        on the step's far end, where float noise would decide it.
        """
        key = (wall, edge, "gain")
        if key not in self._heights:
            src, ahead = self._wall_frame(wall)
            out = []
            for s in self._end_steps(wall):
                run = _len2(_sub2(s.at_far, s.at_u))
                rise = self._carry(s.at_far, src, edge, ahead)[1] - self._carry(s.at_u, src, edge, ahead)[1]
                out.append(rise / run if run > 0.0 else 0.0)
            self._heights[key] = out
        return self._heights[key]

    def _group_line(self, wall, group: _EndGroup, width: float) -> tuple[Vec2, Vec2]:
        """(a, d): the group lies at a + w * d (its wall's frame) for w on the stretch around ``width``."""
        i, (ax, ay), ya = self._group_hit(wall, group, width)
        if group.stuck or not self._rises(wall, group.edge, i, (ax, ay), ya):  # it stays where it is (``_group_hit``)
            return (ax, ay), (0.0, 0.0)
        qx, qy = self._end_steps(wall)[i].at_far
        yq = self._path_heights(wall, group.edge)[i]
        if abs(ya - yq) <= self._surf.tol:  # a step along the edge's line: no distance to gain on it
            return (ax, ay), (0.0, 0.0)
        c = 1.0 / (ya - yq)  # a + (q - a) * (ya - (w - error)) * c
        ex, ey = qx - ax, qy - ay
        s = (ya + group.error) * c
        return (ax + ex * s, ay + ey * s), (-ex * c, -ey * c)

    def _group_xy(self, wall, group: _EndGroup, width: float) -> Vec2:
        """The group's point at ``width``, in its wall's frame."""
        (ax, ay), (dx, dy) = self._group_line(wall, group, width)
        return (ax + width * dx, ay + width * dy)

    def _group_bends(self, wall, group: _EndGroup) -> list[float]:
        """The widths past which ``group`` goes on to the next edge of its path; none for one that stays put."""
        if group.stuck:
            return []
        heights = self._path_heights(wall, group.edge)
        return [heights[i] + group.error + past for i, _, _, past in self._group_steps(wall, group)]

    def _wall_of(self, slot, group: _EndGroup | None) -> object:
        """The wall a piece end slides along: its group's, else its slot's (an open chain's end path, True or False)."""
        return self._slot_wall(slot) if group is None else group.wall

    def _end_point(self, wall, group: _EndGroup | None, width: float) -> Vec2:
        """An end's new vertex at ``width``, in its wall's frame: its group's point, else ``_end_xy``."""
        return self._end_xy(wall, width) if group is None else self._group_xy(wall, group, width)

    def _slot_line(self, slot, group: _EndGroup | None, width: float) -> tuple[Vec2, Vec2]:
        """(a, d): a piece end lies at a + w * d (its wall's frame) on the stretch around ``width``."""
        wall = self._wall_of(slot, group)
        return self._end_line(wall, width) if group is None else self._group_line(wall, group, width)

    def _end_trace(self, wall, group: _EndGroup | None, width: float) -> Trace:
        """An end's new vertex at ``width`` as a trace in its wall's frame, snapped as ``_end`` snaps (``_step_trace``)."""
        if group is None:
            return self._end(wall, width)
        return self._step_trace(wall, self._group_hit(wall, group, width)[0], self._group_xy(wall, group, width))

    def _step_trace(self, wall, i: int, x: Vec2) -> Trace:
        """The point ``x`` (its wall's frame) on step ``i`` of ``wall`` as a trace, snapped as ``_end`` snaps.

        A group's point may lie a hair past its step's far vertex, by at most
        ``_ANCHOR_SNAP_TOL`` along the wall (``_group_steps``): the end then sits on
        that vertex, as ``_end`` puts an end whose line runs that close to it.
        """
        f, xf, u, far, pu, pq = self._end_steps(wall)[i]
        e = _sub2(pq, pu)
        ee = _dot2(e, e)
        t = _dot2(_sub2(x, pu), e) / ee if ee > 0.0 else 0.0
        if not 0.0 <= t <= 1.0:  # past a wall vertex: on it
            t = min(1.0, max(0.0, t))
            x = pq if t == 1.0 else pu
        return self._surf.snap_end(Trace([], self._surf.edge_point(f, u, far, t), False, x, f, xf))

    # --- Ends shooting on --------------------------------------------------------------

    def _group_out(self, wall, group: _EndGroup) -> tuple[float, int, Vec2]:
        """(the width past which ``group``'s wall gives out, the step it ends on, where on it), as ``_group_hit`` reads
        the wall.

        ``_group_hit`` takes the group on up to the first step that does not rise
        from its edge's line (``_rises``), or to the path's end: past the last
        rising step's far end (and that step's slack past it), the wall gives
        out, there. A group that starts on a step that does not rise gives out at
        once, on its start (the width is its own).
        """
        heights, steps = self._path_heights(wall, group.edge), self._end_steps(wall)
        best = (group.height, group.step, group.start)
        for i, start, ya, past in self._group_steps(wall, group):
            if not self._rises(wall, group.edge, i, start, ya):
                break
            best = (heights[i] + past, i, steps[i].at_far)
        return best[0] + group.error, best[1], best[2]

    def _wall_out(self, slot, group: _EndGroup | None) -> float:
        """The width past which a piece end's wall gives out; inf for an end that stays put.

        An open chain's end without a group slides on its end or border path as
        ``_border_hit`` reads it, up to the highest far end of the path, and the
        anchor snap. One with no path at all, or one that never leaves the chain's
        line, is left as it was: the wave stops at once (inf here).
        """
        if group is not None:
            return math.inf if group.stuck else self._group_out(group.wall, group)[0]
        bends = self._end_bends(self._slot_wall(slot))
        top = max(bends, default=-math.inf)
        return top if top > self._surf.tol else math.inf

    def _shots(self, exact: bool, now: float, pieces, ends: dict, dropped: list[bool], cuts, force=None,
               only=None, done=frozenset()) -> tuple[dict, list]:
        """(the ends after every piece end whose wall gives out by ``now`` shot on, the shots as (slot, group,
        landing, out)).

        ``dropped`` and ``cuts``: the loop as it stands at ``now``. ``force``: the slot of an end that shoots on now whatever its wall does
        (``_chord_stop``). ``only``: the slots that may shoot (all of them when
        None). A landing wall that gives out at once shoots on again, further along
        the same line. ``out`` is the width at which the end's wall gave out where
        it is (``_shoot``). ``pieces``: the pieces still going on; ``done``: those
        in their final states, which stay put (see ``_wave_events``).
        """
        out, shots, tol = dict(ends), [], self._surf.tol
        for _ in range(len(self._surf.edge_faces) + 4):
            todo = None
            for piece in pieces:
                for slot, ahead in ((piece[2], True), (piece[3], False)):
                    if only is not None and slot not in only:
                        continue
                    forced = slot == force and not any(s == slot for s, *_ in shots)
                    if forced or self._wall_out(slot, out[slot]) <= now + tol:
                        todo = (slot, piece, ahead, forced)
                        break
                if todo is not None:
                    break
            if todo is None:
                return out, shots
            slot, piece, ahead, forced = todo
            group, landing, at = self._shoot(exact, now, slot, piece, ahead, out, dropped, cuts, forced, done)
            out[slot] = group
            shots.append((slot, group, landing, at))
        raise OutOfRoom(f"an end keeps shooting on at width {now:.6f}")

    def _shoot(self, exact: bool, now: float, slot, piece, ahead: bool, ends: dict, dropped: list[bool], cuts,
               forced: bool, done=frozenset()):
        """The end in ``slot`` (starting ``piece`` when ``ahead``) shot on at ``now``: (its group from here, its
        landing, the width its wall gave out at).

        The end starts where its wall gave out (``_group_out``, or the end path's
        top for an open chain's end without a group), or where it is at ``now``
        when ``forced``; that width is where its wall's last vertex, or the end's
        point, lies at its distance (``now`` for a forced one: a wall that holds a
        hair past its top gives out a hair before ``now``). An end that lies on an
        open edge or a vertex of the open border has landed already: it stays
        where it is, as does one on the chain. Else its offset line, parallel to
        ``edge`` (the chain edge its remaining segment starts on) at the distance
        the end has, runs on through its point, away from its piece
        (``_landing``). The landing wall becomes the end's wall: a new group on it,
        from the landing point, keeps the end's width error frozen, so the end
        keeps its distance from that edge's line at the width less that error. The
        landing is an edge, a vertex or None: with nothing to land on the group
        stays put on the end's point. The end does not jump there at once: at the
        shot its segment, from its neighbour to the landing point, passes the end's
        point by a hair, which the traced ends' snap can undo. It waits on its point
        (``_EndGroup.pending``), structurally: where its neighbour keeps up with the
        end's line (lags behind it by no more than ``tol``), till ``_CLEARANCE``
        past where its wall gave out, where the segment along the line clears the
        point by that; where the neighbour lags behind (default mode's leaning rail
        vertices), which would pull the segment back across the old wall, till the
        segment clears the point by ``_CLEARANCE`` (``_clear_width``). An end made
        at this very width, by a cut or a fold, has slid along no wall yet, and the
        loop round it is still being made: it lands at once unless its neighbour
        lags.
        """
        n = len(self.band.chain)
        group = ends[slot]
        wall = self._wall_of(slot, group)
        src = self._wall_frame(wall)[0]
        steps = self._end_steps(wall)
        if group is None:
            edge, error = (0 if wall else n - 2), 0.0
            if forced:
                i, tr = self._end_step(wall, now), self._end(wall, now)
            else:  # on the path's highest far vertex, where ``_border_hit`` gives out
                bends = self._end_bends(wall)
                i = bends.index(max(bends))
                tr = self._step_trace(wall, i, steps[i].at_far)
        else:
            edge, error = group.edge, group.error
            if forced:
                i, x = self._group_hit(wall, group, now)[0], self._group_xy(wall, group, now)
            else:
                _, i, x = self._group_out(wall, group)
            tr = self._step_trace(wall, i, x)
        at = now if forced else min(now, self._carry(tr.end_xy, src, edge, ahead)[1] + error)
        d, normal = self._edge_axes(edge, src, ahead)
        try:
            point = self._end_point(wall, group, now)
        except OutOfRoom:  # an end on its path's top may lie a float step past it at ``now``
            point = tr.end_xy
        key = ("shot", exact, slot, len(self._walls))
        self._walls[key] = (src, ahead)
        start = tr.end
        stays = self._on_open(start) or (start.kind == "vert" and start.vert in self.band.chain)
        land = None if stays else self._landing(tr, d, normal, ahead, point)
        if land is None and not stays and self._shoot_miss is not None:
            self.shoot_misses[exact] = min(self.shoot_misses.get(exact, math.inf), self._shoot_miss)
        if land is None:
            self._steps[key] = [steps[i]]
            x = tr.end_xy
            return _EndGroup(now, edge, error, 0, x, self._carry(x, src, edge, ahead)[1], key, stuck=True), None, at
        self._steps[key], x, landing, stuck = land
        landed = _EndGroup(now, edge, error, 0, x, self._carry(x, src, edge, ahead)[1], key, stuck=stuck)
        seg = None if stuck else self._end_segment(exact, now, piece, ahead, src, dropped, cuts, {**ends, slot: landed},
                                                   done)
        if seg is None:
            return landed, landing, at
        # Whether the neighbour lags behind the end's line: the end's point, carried on to that line (from the wall's
        # end, past which the width ran on by ``now - at``), lies beyond the segment to the landing, away from the
        # chain, by more than ``tol``. Kept up with, the segment runs along the line, and noise alone puts the point a
        # hair to either side of it.
        side = math.copysign(1.0, _cross2(d, normal))
        on_line = (tr.end_xy[0] + (now - at) * normal[0], tr.end_xy[1] + (now - at) * normal[1])
        lags = not self._clears(seg[0], seg[1], on_line, side, -self._surf.tol)
        if not lags and group is not None and group.width >= now:  # made right here, by a cut or a fold
            return landed, landing, at
        wait = ("shot", exact, slot, len(self._walls))
        self._walls[wait], self._steps[wait] = (src, ahead), [steps[i]]
        x = tr.end_xy
        height = self._carry(x, src, edge, ahead)[1]
        pending = (landed, landing, side, None if lags else at + _CLEARANCE)
        return _EndGroup(now, edge, error, 0, x, height, wait, stuck=True, pending=pending), landing, at

    def _edge_axes(self, edge: int, src: int, ahead: bool) -> tuple[Vec2, Vec2]:
        """(the way on past a piece end, away from its piece, along chain edge ``edge``; the edge's side normal, toward
        greater distance from its line): unit vectors in ``chain[src]``'s frame, ``ahead`` as for the end's wall."""
        o = self._carry((0.0, 0.0), edge, src, not ahead)
        along = _sub2(self._carry((1.0, 0.0), edge, src, not ahead), o)
        normal = _sub2(self._carry((0.0, 1.0), edge, src, not ahead), o)
        return ((-along[0], -along[1]) if ahead else along), normal

    def _clears(self, end: Vec2, neighbour: Vec2, point: Vec2, side: float, by: float) -> bool:
        """Whether the segment from ``neighbour`` to ``end`` passes ``point`` on the chain's side of it by ``by`` (``side``:
        the sign of the end's line's direction across to the side, away from the chain)."""
        t = _sub2(end, neighbour)
        tl = _len2(t)
        return tl == 0.0 or -side * _cross2(t, _sub2(point, neighbour)) >= by * tl

    def _end_segment(self, exact: bool, now: float, piece, ahead: bool, src: int, dropped: list[bool], cuts,
                     ends: dict, done=frozenset()) -> tuple[Vec2, Vec2] | None:
        """(the end's point, its neighbour's) on the end's segment at ``now``, in ``chain[src]``'s frame; None when the
        loop does not lay out there."""
        for at in (now, now - self._surf.tol):  # an end on its path's top may lie a float step past it at ``now``
            try:
                xy, alt, _ = self._layout(at, exact, dropped, cuts, ends, done)
                break
            except OutOfRoom:
                continue
        else:
            return None
        return self._segment_ends(piece, ahead, src, dropped, xy, alt)

    def _segment_ends(self, piece, ahead: bool, src: int, dropped: list[bool], xy, alt) -> tuple[Vec2, Vec2] | None:
        """(a piece end's point, its neighbour's on the end's segment) of the positions ``xy`` and ``alt``, in
        ``chain[src]``'s frame; None for a piece with no segment left."""
        n = len(self.band.chain)
        first, last = piece[0], piece[1]
        left = [t for t in range(first, last) if not dropped[t % n]]
        if not left:
            return None
        if ahead:
            k = (left[0] + 1) % n
            return alt.get(first % n, xy[first % n]), self._carry(xy[k], k, src, False)
        k = left[-1] % n
        return xy[last % n], self._carry(alt.get(k, xy[k]), k, src, True)

    def _clear_width(self, now: float, mid: float, piece, ahead: bool, group: _EndGroup, dropped: list[bool], at0,
                     at1) -> float:
        """The first width from ``now`` on this stretch at which a waiting end's segment clears its point (see
        ``_EndGroup``) by ``_CLEARANCE``, which the segment's traced ends cannot undo: its group on the landing moves
        on its line there, and its neighbour on the line ``at0`` and ``at1`` (the positions at ``now`` and ``now + 1``)
        give, so the segment's side of the point is a quadratic in the width. inf when it does not clear on the
        stretch's lines."""
        landed, _, side, _ = group.pending
        src = self._wall_frame(group.wall)[0]
        (ax, ay), (dx, dy) = self._group_line(landed.wall, landed, mid)
        e0, e1 = (self._segment_ends(piece, ahead, src, dropped, *at) for at in (at0, at1))
        if e0 is None or e1 is None:
            return math.inf
        n0, n1 = e0[1], e1[1]
        span = _len2(_sub2((ax + now * dx, ay + now * dy), n0))  # the segment's length now, for the clearance

        def q(w: float) -> float:
            g = (ax + w * dx, ay + w * dy)
            nb = (n0[0] + (w - now) * (n1[0] - n0[0]), n0[1] + (w - now) * (n1[1] - n0[1]))
            return -side * _cross2(_sub2(g, nb), _sub2(group.start, nb)) - _CLEARANCE * span

        q0, q1, q2 = q(now), q(now + 1.0), q(now + 2.0)
        if q0 >= 0.0:
            return now
        a = 0.5 * (q2 - 2.0 * q1 + q0)
        b = q1 - q0 - a
        if abs(a) <= 1e-15 * (abs(b) + abs(q0)):
            return now - q0 / b if b > 0.0 else math.inf
        disc = b * b - 4.0 * a * q0
        if disc < 0.0:
            return math.inf
        r = math.sqrt(disc)
        roots = sorted(x for x in ((-b - r) / (2.0 * a), (-b + r) / (2.0 * a)) if x >= 0.0)
        return now + roots[0] if roots else math.inf

    def _along_wall(self, k: int, p: SurfacePoint, q: SurfacePoint, a: Vec2, b: Vec2) -> bool:
        """Whether segment ``k``, from ``p`` at ``a`` to ``q`` at ``b`` (each in its own vertex's wedge frame), runs along
        the open border: both its ends lie on it, and so does its middle, where a straight trace from ``chain[k]``
        ends on the border, or is stopped by it."""
        if not (self._on_open(p) and self._on_open(q)):
            return False
        b = self._surf.from_next(k, b)
        try:
            tr = self._straight(k, (0.5 * (a[0] + b[0]), 0.5 * (a[1] + b[1]))).trace
        except OutOfRoom:
            return True
        return self._on_open(tr.end)

    def _along_open(self, p: SurfacePoint, q: SurfacePoint) -> bool:
        """Whether ``p`` and ``q`` lie on one open edge (one band face holds it): a segment between them runs along it."""

        def edges(sp: SurfacePoint) -> set:
            if sp.kind == "edge":
                return {sp.edge} if self._on_open(sp) else set()
            if sp.kind == "vert" and sp.vert in self._open_verts():
                return {e for e, fs in self._surf.edge_faces.items() if len(fs) == 1 and sp.vert in e}
            return set()

        return bool(edges(p) & edges(q))

    def _open_verts(self) -> set[int]:
        """The vertices of the open border: on an edge that one band face holds."""
        if self._open is None:
            self._open = {v for e, fs in self._surf.edge_faces.items() if len(fs) == 1 for v in e}
        return self._open

    def _on_open(self, sp: SurfacePoint) -> bool:
        """Whether ``sp`` lies on the open border: on an edge one band face holds, or on a vertex of one."""
        if sp.kind == "edge":
            return len(self._surf.edge_faces.get(sp.edge, ())) == 1
        return sp.kind == "vert" and sp.vert in self._open_verts()

    def _landing(self, tr: Trace, d: Vec2, normal: Vec2, ahead: bool, point: Vec2):
        """Where the line from ``tr``'s end along ``d``, through ``point``, lands: (its wall as steps, the landing point,
        the landing, whether the end stays there), or None.

        The line runs across faces, in ``tr``'s development, up to the first edge
        it crosses whose direction lies within the Shoot Angle
        (``band.angles.shoot``) of perpendicular to it, or that it cannot cross
        (an open edge, an end wall, a fin): the landing is that edge (sorted
        vertex ids), and the end lands where the line crosses it. The wall runs
        from there to its vertex further from the chain edge's line (along
        ``normal``) and on as a rail path (``_rail_on``).

        Where the line passes within the anchor snap of a vertex, on either side
        as noise has it, the vertex decides: the end lands on it where an edge
        there gives a wall (``_vertex_wall``); else on a vertex of the open border
        it has landed, and stays there; else the line goes on through the vertex
        itself. Where it leaves a vertex (the end's own one too) along an edge
        there, within the snap, it follows that edge to its far vertex, which
        decides in turn. None where the line leaves the band first: through the
        chain, at a vertex it cannot get past, or at the end itself.
        """
        surf = self._surf
        f, xf, start, p = tr._face, tr._xf, tr.end, tr.end_xy
        chain = set(self.band.chain)
        reach = 4.0 * self._scale
        cos_shoot = math.cos(self.band.angles.shoot)
        self._shoot_miss = None
        target = (point[0] + reach * d[0], point[1] + reach * d[1])  # ``point`` lies within the snap of ``p``
        skip_vert, skip_edge, reached = None, None, None
        if start.kind == "edge":
            a, b = start.edge
            dev = surf.dev(f, xf)
            far = b if _dot2(_sub2(dev[b], dev[a]), d) > 0.0 else a
            if abs(_cross2(_sub2(dev[far], p), d)) <= _ANCHOR_SNAP_TOL:  # along its own edge, to its far vertex
                reached = far
            else:
                skip_edge = start.edge
        elif start.kind == "vert":
            skip_vert = start.vert
            nxt = self._along_edge(f, xf, start.vert, d)
            if nxt is not None:
                (f, xf), reached = nxt
        if reached is None:
            nxt = surf._leave(f, xf, start, d)
            if nxt is None:
                return None
            f, xf = nxt
        for _ in range(surf.max_steps):
            if reached is not None:  # on a vertex the line has reached
                v, reached = reached, None
                dev = surf.dev(f, xf)
                if v in chain:
                    return None
                steps = self._vertex_wall(f, xf, v, d, normal, ahead)
                if steps is not None:
                    return steps, dev[v], v, False
                if v in self._open_verts():  # landed on the open border: it stays there
                    return [self._open_step(f, xf, v)], dev[v], v, True
                p = dev[v]
                target = (p[0] + reach * d[0], p[1] + reach * d[1])
                nxt = self._along_edge(f, xf, v, d)
                if nxt is not None:
                    (f, xf), reached = nxt
                    continue
                nxt = surf.around(f, xf, v, d)  # on through the vertex itself, whichever side noise passed it
                if nxt is None:
                    return None
                (f, xf), skip_vert, skip_edge = nxt, v, None
            hit = surf._exit(f, xf, p, target, skip_vert, skip_edge)
            if hit is None or hit[0] >= 1.0:
                return None
            s, a, b, _ = hit
            x = (p[0] + (target[0] - p[0]) * s, p[1] + (target[1] - p[1]) * s)
            dev = surf.dev(f, xf)
            v = min((a, b), key=lambda u: _len2(_sub2(x, dev[u])))
            if _len2(_sub2(x, dev[v])) <= _ANCHOR_SNAP_TOL:
                reached = v
                continue
            if _ekey(a, b) in surf.chain_edges:
                return None
            beyond = surf.across(f, xf, a, b)
            e = _sub2(dev[b], dev[a])
            square = abs(_cross2(e, d))  # |e| x the cosine of e's turn from perpendicular to the line
            if beyond is not None and square < cos_shoot * _len2(e) and _len2(e) > 0.0:
                near = math.acos(min(1.0, square / _len2(e)))
                self._shoot_miss = near if self._shoot_miss is None else min(self._shoot_miss, near)
            if beyond is None or square >= cos_shoot * _len2(e):
                lo, hi = (a, b) if _dot2(e, normal) > 0.0 else (b, a)
                return self._rail_on(f, xf, lo, hi), x, _ekey(a, b), False
            (f, xf), p, skip_vert, skip_edge = beyond, x, None, _ekey(a, b)
        return None

    def _along_edge(self, f: int, xf: tuple, v: int, d: Vec2):
        """((face, placement) holding the edge at vertex ``v`` that the line from ``v`` along ``d`` runs along, within
        the anchor snap at its far vertex, and that far vertex), or None: the nearest such edge, ties to the lower id."""
        surf = self._surf
        loop = surf.layout(f).loop
        best = None
        for g, xg in surf.fan(f, xf, v, loop[loop.index(v) - 1], surf.blocked):
            gl = surf.layout(g).loop
            i = gl.index(v)
            dev = surf.dev(g, xg)
            for y in (gl[i - 1], gl[(i + 1) % len(gl)]):
                r = _sub2(dev[y], dev[v])
                off = abs(_cross2(r, d))
                if _dot2(r, d) > 0.0 and off <= _ANCHOR_SNAP_TOL and (best is None or (off, y) < best[0]):
                    best = ((off, y), (g, xg))
        return None if best is None else (best[1], best[0][1])

    def _open_step(self, f: int, xf: tuple, v: int) -> _Step:
        """An open-border edge at vertex ``v``, from ``v``, as a wall step: where an end that stays on ``v`` lies."""
        surf = self._surf
        loop = surf.layout(f).loop
        for g, xg in surf.fan(f, xf, v, loop[loop.index(v) - 1], surf.blocked):
            gl = surf.layout(g).loop
            i = gl.index(v)
            dev = surf.dev(g, xg)
            for y in sorted((gl[i - 1], gl[(i + 1) % len(gl)])):
                if len(surf.edge_faces.get(_ekey(v, y), ())) == 1:
                    return _Step(g, xg, v, y, dev[v], dev[y])
        y = loop[(loop.index(v) + 1) % len(loop)]
        dev = surf.dev(f, xf)
        return _Step(f, xf, v, y, dev[v], dev[y])

    def _vertex_wall(self, f: int, xf: tuple, v: int, d: Vec2, normal: Vec2, ahead: bool) -> list[_Step] | None:
        """The wall of an end landing on vertex ``v``, which its line passes within the snap of; None: it goes on.

        Noise passes ``v`` on either side, so every band edge at ``v`` counts (not
        only the ones this line crossed): one the line could land on (within the
        Shoot Angle of perpendicular to ``d``, or one it cannot cross) gives a
        wall. Rising from ``v`` (away from the chain edge's line, along
        ``normal``) it is the wall's first edge; falling, the end would slide up it
        onto ``v`` and on as a rail path, so the first edge is the one at ``v`` that
        goes on straightest from it, within Rail Bend, if that rises. Of these the
        steepest rising first edge wins (ties: the lower vertex id); none: the
        line goes on.
        """
        surf = self._surf
        loop = surf.layout(f).loop
        fan = surf.fan(f, xf, v, loop[loop.index(v) - 1], surf.blocked)
        at: dict[int, list[tuple[int, tuple, Vec2]]] = {}  # each neighbour y of v: the fan's faces holding (v, y)
        for g, xg in fan:
            gl = surf.layout(g).loop
            i = gl.index(v)
            dev = surf.dev(g, xg)
            for y in (gl[i - 1], gl[(i + 1) % len(gl)]):
                at.setdefault(y, []).append((g, xg, _sub2(dev[y], dev[v])))
        cos_shoot, bend = math.cos(self.band.angles.shoot), self.band.angles.rail_bend
        best = None
        for y in sorted(at):
            g, xg, r = at[y][0]
            rl = _len2(r)
            if rl == 0.0 or _ekey(v, y) in surf.chain_edges:
                continue
            uncrossable = _ekey(v, y) in surf.blocked or surf._beyond(g, xg, v, y) is None
            if not (uncrossable or abs(_cross2(r, d)) >= cos_shoot * rl):
                continue
            first = y
            if _dot2(r, normal) <= _PARALLEL_SIN * rl:  # falling: on from v, straight on from y
                turns = [(abs(math.atan2(_cross2(r, q), -_dot2(r, q))), z) for z, ((_, _, q), *_) in at.items()
                         if z != y and _len2(q) > 0.0]
                turn, first = min(turns, default=(math.inf, None))
                if turn > bend:
                    continue
            q = at[first][0][2]
            rise = _dot2(q, normal) / _len2(q)
            if rise > _PARALLEL_SIN and (best is None or rise > best[0]):
                best = (rise, first)
        if best is None:
            return None
        y = best[1]
        g, xg, _ = next((h for h in at[y] if (surf._forward(h[0], v, y) != _xf_mirrored(h[1])) != ahead), at[y][0])
        return self._rail_on(g, xg, v, y)

    def _rail_on(self, f: int, xf: tuple, u: int, far: int) -> list[_Step]:
        """The wall from edge (u, far) of face ``f`` on: on through ``far`` as a rail path, as ``_Surface.rail_path``
        follows one (straight on within Rail Bend, never back to a vertex of the path, up to the chain)."""
        surf = self._surf
        chain = set(self.band.chain)
        dev = surf.dev(f, xf)
        verts, pts, holders = [u, far], [dev[u], dev[far]], [(f, xf)]
        while verts[-1] not in chain:
            p, x = verts[-2], verts[-1]
            heading = _sub2(pts[-1], pts[-2])
            best, tried = None, set()
            for g, xg in surf.fan(*holders[-1], x, p, surf.blocked):
                loop = surf.layout(g).loop
                i = loop.index(x)
                dg = surf.dev(g, xg)
                for y in (loop[i - 1], loop[(i + 1) % len(loop)]):
                    if y in tried or y in verts:
                        continue
                    tried.add(y)
                    q = _sub2(dg[y], dg[x])
                    turn = abs(math.atan2(_cross2(heading, q), _dot2(heading, q)))
                    if turn <= self.band.angles.rail_bend and (best is None or turn < best[0]):
                        best = (turn, y, dg[y], (g, xg))
            if best is None:
                break
            verts.append(best[1])
            pts.append(best[2])
            holders.append(best[3])
        return [_Step(*holders[i], verts[i], verts[i + 1], pts[i], pts[i + 1]) for i in range(len(verts) - 1)]

    # --- Wall hits -------------------------------------------------------------------

    def _hit(self, k: int, exact: bool) -> _Hit | None:
        """Where ``chain[k]``'s new vertex runs out of the band, as long as it is not merged; None if it never does.

        The route's ray is traced out as ``_ray_fits`` traces it (once per
        Slider): the vertex fits up to where that trace is blocked, at the width
        ``hs[ray] + run * sin(half)``. None also where the rail path itself is
        blocked before its end.
        """
        key = (k, exact)
        if key not in self._hits:
            route = self._aim(k, exact)
            reach = 4.0 * self._scale / math.sin(route.half)
            if route.ray == 0:
                tr, leg = trace_from_vertex(self.band, k, route.half, reach, _surface=self._surf), 0
            else:
                tr, _, leg = self._walk(k, route, route.ray, route.along(reach))
            hit = None
            if tr.blocked and leg == route.ray:
                run = _len2(_sub2(tr.end_xy, route.pts[route.ray]))
                hit = _Hit(route.hs[route.ray] + run * math.sin(route.half), tr)
            self._hits[key] = hit
        return self._hits[key]

    def _meet_hit(self, i: int, j: int, exact: bool, width: float) -> _Hit | None:
        """Where the point of the merged group i..j, which holds no end, runs out of the band; None if it never does.

        The point moves on a line (``_meet``, linear in width). It is traced
        straight from ``chain[i]`` to where it is at ``width``, when the group is
        first seen, and on along that line; None when that first trace does not
        reach it. Worked out once per group.

        A fold group is a convex corner of the loop (a segment shrinks only while
        its ends' side angles sum below 360 degrees), and a convex corner moves
        into the wedge between its own two segments: they reach a wall no later
        than its point does. A hit on a group opens the loop as a vertex's does,
        and the wave goes on: it does not stop it. But unless a wall vertex lies
        on the corner's bisector (``notch_spike``), the segments beside the point
        cross the wall first, which the solve's traces find there, or ``_cut``'s
        check, which then stops the wave at the hit.
        """
        key = (i, j, exact)
        if key not in self._hits:
            hit = None
            try:
                p = self._meet_wave(i, j, width, exact)
                q = self._meet_wave(i, j, width + 1.0, exact)
                tr = self._straight(i, p).trace
            except OutOfRoom:
                tr = None
            d = (0.0, 0.0) if tr is None else _sub2(q, p)
            dl = _len2(d)
            if dl > 0.0:
                reach = 4.0 * self._scale / dl
                ray = self._surf.trace(tr._face, tr._xf, tr.end, tr.end_xy, (p[0] + reach * d[0], p[1] + reach * d[1]))
                if ray.blocked:
                    hit = _Hit(width + _len2(_sub2(ray.end_xy, p)) / dl, ray, (d[0] / dl, d[1] / dl))
            self._hits[key] = hit
        return self._hits[key]

    def _wall_walk(self, f: int, xf: tuple, u: int, far: int) -> list[_Step]:
        """The wall from edge (u, far) of face ``f`` on, toward ``far``: its edges as ``border_step`` walks them.

        It ends where the chain comes first, or once it comes back round to its
        first edge (the rim of a hole).
        """
        surf = self._surf
        dev = surf.dev(f, xf)
        out = [_Step(f, xf, u, far, dev[u], dev[far])]
        for _ in range(len(surf.edge_faces)):
            step = surf.border_step(f, xf, far, u)
            if step is None:
                break
            f, xf, nxt = step
            u, far = far, nxt
            if (u, far) == (out[0].u, out[0].far):
                break
            dev = surf.dev(f, xf)
            out.append(_Step(f, xf, u, far, dev[u], dev[far]))
        return out

    def _split(self, k: int, j: int, exact: bool, hit: _Hit | None) -> tuple[object, _EndGroup, _EndGroup] | None:
        """The cut where ``chain[k]``, or the group k..j, reaches its wall: (the wall edge or vertex, left, right end).

        The wall runs both ways from the hit point; the left end takes the way
        counter-clockwise of the heading (toward ``chain[k-1]`` in the wedge
        frame), on segment k-1's offset line, the right end the other way, on
        segment j's. Each starts on the hit point, so each keeps the width error
        the vertex had there against its own chain edge: none on an exact route,
        nor at a group's point. A group's members go with the right end, whose
        group they are from the cut on. None where the vertex reaches its own
        chain, or one way along the wall runs into the chain at once.
        """
        if hit is None:
            return None
        surf, n = self._surf, len(self.band.chain)
        tr = hit.trace
        f, xf, x = tr._face, tr._xf, tr.end_xy
        if tr.end.kind == "edge":
            wall = tr.end.edge
            if wall in surf.chain_edges:
                return None
            a, b = wall
            ways = [self._wall_walk(f, xf, a, b), self._wall_walk(f, xf, b, a)]
        elif tr.end.kind == "vert" and tr.end.vert not in self.band.chain:
            wall = v = tr.end.vert
            loop = surf.layout(f).loop
            i = loop.index(v)
            ways = []
            for came in (loop[(i + 1) % len(loop)], loop[i - 1]):
                step = surf.border_step(f, xf, v, came)
                if step is None:
                    return None
                ways.append(self._wall_walk(step[0], step[1], v, step[2]))
        else:
            return None
        if ways[0][0].far == ways[1][0].far:  # both ways took one wall edge: no wall on one side
            return None
        if hit.heading is None:
            half = self._aim(k, exact).half
            d = (math.cos(half), math.sin(half))
        else:
            d = hit.heading

        def turn(steps: list[_Step]) -> float:
            u = _sub2(steps[0].at_far, x)
            if _len2(u) <= surf.tol:
                u = _sub2(steps[0].at_far, steps[0].at_u)
            return _cross2(d, u) / _len2(u)

        left_steps, right_steps = sorted(ways, key=turn, reverse=True)
        out = []
        for ahead, steps in ((False, left_steps), (True, right_steps)):
            key = (exact, k, ahead)
            self._walls[key] = (k, ahead)
            self._steps[key] = steps
            out.append(self._grown(key, hit.width, j if ahead else (k - 1) % n, x, 0))
        return wall, out[0], out[1]

    # --- Positions -----------------------------------------------------------------

    def _groups(self, dropped: list[bool]) -> list[tuple[int, int]]:
        """Merged vertex groups as (first, last) chain indices (``Slider._runs``); on an open chain none wraps.

        A group of an open chain may hold an end: one starting at 0, or ending
        at the last vertex.
        """
        if self.band.closed:
            return self._runs(dropped)
        out, k, m = [], 0, len(dropped)
        while k < m:
            if dropped[k]:
                i = k
                while k < m and dropped[k]:
                    k += 1
                out.append((i, k))
            else:
                k += 1
        return out

    def _merge_wave(self, base: list[Vec2], dropped: list[bool], width: float, exact: bool) -> list[Vec2]:
        """``base`` with each merged group moved onto its point, in every member's frame.

        A group with an end takes that end's point from ``base``; any other
        meets where its outer chain edges' offset lines do (``_meet``).
        """
        surf = self._surf
        n, closed = len(base), self.band.closed
        xy = list(base)
        for i, j in self._groups(dropped):
            if not closed and j == n - 1:  # the end's group, back from the end
                p, k = base[j], j
                while k != i:
                    k -= 1
                    p = xy[k] = surf.from_next(k, p)
                continue
            p, k = (base[0] if not closed and i == 0 else self._meet_wave(i, j, width, exact)), i
            xy[k] = p
            while k != j:
                p, k = surf.to_next(k, p), (k + 1) % n
                xy[k] = p
        return xy

    def _piece_xy(self, pieces, base, dropped: list[bool], width: float, exact: bool, done=frozenset()):
        """The pieces' points, each merged group moved onto its point (as ``_merge_wave``), chain-indexed.

        ``base[i]`` holds piece i's points for its vertices first..last, its two
        ends' points at either end; a piece in its final state (``done``) takes the
        points ``_freeze`` left it instead. Returns (xy, alt): ``xy[k]`` is
        ``chain[k]``'s point as the end of segment k-1 and ``alt[k]``, at a cut,
        its point as the start of segment k (the right end, while ``xy[k]`` holds
        the left one).
        """
        surf, n = self._surf, len(self.band.chain)
        xy: list[Vec2] = [(0.0, 0.0)] * n
        alt: dict[int, Vec2] = {}
        for (first, last, start, _), row in zip(pieces, base):
            if first % n in done:
                pts = self._frozen[exact][first % n]
            else:
                pts = list(row)
                for s, e in self._piece_runs((first, last), dropped):
                    if e == last:  # the end's group, back from the end
                        p, k = pts[e - first], e
                        while k != s:
                            k -= 1
                            p = pts[k - first] = surf.from_next(k % n, p)
                        continue
                    p, k = (pts[0] if s == first else self._meet_wave(s % n, e % n, width, exact)), s
                    pts[k - first] = p
                    while k != e:
                        p, k = surf.to_next(k % n, p), k + 1
                        pts[k - first] = p
            if isinstance(start, tuple):
                alt[first % n] = pts[0]
            else:
                xy[first % n] = pts[0]
            for t in range(first + 1, last + 1):
                xy[t % n] = pts[t - first]
        return xy, alt

    def _seg_len(self, k: int, xy: list[Vec2], alt: dict[int, Vec2]) -> float:
        """``_seg_length`` of segment ``k``, which starts on ``alt[k]`` at a cut."""
        return self._surf.from_next(k, xy[(k + 1) % len(xy)])[0] - alt.get(k, xy[k])[0]

    def _layout(self, width: float, exact: bool, dropped: list[bool], cuts: tuple[int, ...], ends: dict,
                done=frozenset()):
        """(xy, alt, pieces): the loop's points at ``width`` with these drops, cuts and ends (see ``_piece_xy``).

        Each piece's ends sit on their points, its other vertices on their routes
        or their groups' points; a piece in its final state (``done``, by its first
        chain vertex mod n) on the points it keeps (``_freeze``). Raises
        ``OutOfRoom`` where the ray of a vertex that is not merged leaves the band,
        or an end's wall gives out.
        """
        n = len(self.band.chain)
        pieces = self._pieces(cuts, exact)
        if not pieces:  # a closed loop; in its final state (a tree, key 0) its points stay put
            if 0 in done:
                return list(self._frozen[exact][0]), {}, pieces
            base = [(0.0, 0.0) if dropped[k - 1] or dropped[k] else self._at(k, width, exact)[2] for k in range(n)]
            return self._merge_wave(base, dropped, width, exact), {}, pieces
        rows = []
        for first, last, start, end in pieces:
            if first % n in done:
                rows.append(None)
                continue
            row = [self._end_point(self._wall_of(start, ends[start]), ends[start], width)]
            for t in range(first + 1, last):
                k = t % n
                row.append((0.0, 0.0) if dropped[(t - 1) % n] or dropped[k] else self._at(k, width, exact)[2])
            row.append(self._end_point(self._wall_of(end, ends[end]), ends[end], width))
            rows.append(row)
        return (*self._piece_xy(pieces, rows, dropped, width, exact, done), pieces)

    def _planned(self, width: float, exact: bool, count: int | None = None):
        """(xy, alt, dropped, cuts, ends, pieces, done) of the wave at ``width`` (``_plan``); ``done`` as ``_state``
        gives it. ``count``: take the first ``count`` events instead of those holding at ``width``."""
        n = len(self.band.chain)
        _, dropped, cuts, ends, done = self._state(exact, width, count)
        stop = self._stop(exact)
        if width >= stop:
            raise OutOfRoom(f"the wave runs out of room at width {stop:.6f}")
        self._solving = True
        try:
            xy, alt, pieces = self._layout(width, exact, dropped, cuts, ends, frozenset(done))
        finally:
            self._solving = False
        still = {t % n for p in pieces if p[0] % n in done for t in range(p[0], p[1])}  # in their final states
        if not pieces and done:  # a closed loop's tree
            still = set(range(len(dropped)))
        for k in range(len(dropped)):  # the wave folds a segment within tol of nothing, so only past that is it
            if not dropped[k] and k not in still and self._seg_len(k, xy, alt) < -self._surf.tol:  # folding back
                raise OutOfRoom(f"segment {k} folds back at width {width:.6f}")
        return xy, alt, dropped, cuts, ends, pieces, done

    def _plan(
        self, width: float, exact: bool, collapse: bool, destructive: bool = False
    ) -> tuple[list[Vec2], list[bool]]:
        """``Slider._plan``; with ``destructive`` the wave's segments are dropped, and pieces keep their final states.

        The events holding at ``width`` (``_state``) set the drops, the cuts, the
        ends' groups and the pieces in their final states. Raises ``OutOfRoom``
        past the wave's stop, where a vertex's ray leaves the band, a wall or
        border path ends or an end's group runs out of wall, or where a segment
        still folds back. At a cut ``xy`` holds the left end (see ``_piece_xy``).
        """
        if not destructive:
            return super()._plan(width, exact, collapse)
        wave = self._wave_of(exact)
        if width >= wave.split:
            # Every ring the loop split into must fit (each raises where it does not); the points returned are the
            # first ring's only: past a split, ``limit``'s bisection is the one caller, and it reads only whether the
            # plan raises. ``_solve`` stitches the rings' points.
            return [p._plan(width, exact, True, destructive=True) for p in wave.parts][0]
        xy, _, dropped = self._planned(width, exact)[:3]
        return xy, dropped

    # --- Solve ---------------------------------------------------------------------

    def _straight(self, k: int, p: Vec2) -> Placement:
        """``chain[k]`` traced straight to ``p``, its group's point in its wedge frame."""
        return Placement(self._trace(k, math.atan2(p[1], p[0]), math.hypot(p[0], p[1])), None, 0.0)

    def _holder(self, members: list[int], xy: list[Vec2], places: list, ends: list) -> int:
        """The member of a merged group without an end whose trace stands for the group's point, put in ``ends``.

        The first member whose straight trace to the point runs clear of the
        band's border and walls. (A group that holds an end has that end's trace.)
        """
        for k in members:
            try:
                places[k] = self._straight(k, xy[k])
            except OutOfRoom:
                continue
            ends[k] = places[k].trace
            return k
        raise OutOfRoom(f"no vertex of the group at vertex {self.band.chain[members[0]]} reaches its point")

    def _along(self, way: list[int]):
        """The map of wedge frames from ``chain[way[0]]``'s to ``chain[way[-1]]``'s, hop by hop along ``way``."""
        surf, n = self._surf, len(self.band.chain)

        def move(p: Vec2) -> Vec2:
            for a, b in zip(way, way[1:]):
                p = surf.to_next(a, p) if b == (a + 1) % n else surf.from_next(b, p)
            return p

        return move

    def _member(self, k: int, way: list[int], trace: Trace, p: Vec2) -> tuple[Trace, Placement | None]:
        """A merged vertex's trace to its group's point, and its placement for a connector (None for none).

        ``trace`` is the group holder's, ``way`` the chain indices from the
        holder to ``k`` and ``p`` the point in ``chain[k]``'s wedge frame. The
        straight trace from ``chain[k]`` is kept where it runs clear to the point.
        Near a wall that bends it can leave the band; the holder's trace,
        carried into ``chain[k]``'s frame, then stands for the vertex, and it
        gets no connector.
        """
        try:
            place = self._straight(k, p)
            if _length(_sub(place.trace.end.co, trace.end.co)) <= _SEGMENT_MEET_TOL:
                return place.trace, place
        except OutOfRoom:
            pass
        move = self._along(way)
        return Trace([], trace.end, False, move(trace.end_xy), trace._face, _xf_moved(trace._xf, move)), None

    def _solve(self, width: float, exact: bool, collapse: bool, destructive: bool = False) -> Cut:
        """``Slider._solve``; with ``destructive`` the wave's loop at ``width``, its pieces in their final states as such.

        At a cut the vertex has two points: the left end's, which its anchor
        indexes, and after a break (``Cut.breaks``) the right end's. A closed loop
        starts on a vertex that is not cut where it can, so its breaks lie inside
        the points; one cut at every such vertex leaves the break on the wrap (0).
        Each end of a cut also connects to the cut vertex (``_cut_connector``),
        so every piece closes its own strip. A piece in its final state is traced
        at the width it reached it at: pressed onto its walls, its vertices before
        the split on its start's point and the rest on its end's, with a break
        between the two unless they coincide; closed into a ridge, its points as
        they lie, joined. Every other chain vertex of it connects to its point where
        the straight way there runs clear and crosses nothing (``_member``).
        """
        if not destructive:
            return super()._solve(width, exact, collapse)
        n, closed = len(self.band.chain), self.band.closed
        if width <= _ANCHOR_SNAP_TOL:  # anchors this close would snap onto the chain itself
            return Cut([], [None] * n, [], 0.0, False)
        if width >= self._wave_of(exact).split:
            return self._solve_parts(width, exact)
        xy, alt, dropped, cuts, ends, pieces, done = self._planned(width, exact)
        places: list[Placement | None] = [None] * n
        at_width = [width] * n  # the width each vertex is placed at: a piece in its final state's own
        ends_in: list[Trace | None] = [None] * n  # each vertex's trace, ending segment k-1
        ends_out: dict[int, Trace] = {}  # a cut's right end, starting segment k
        runs: list[tuple[list[int], int | None, Trace | None]] = []  # members, the end holding the group, its trace
        apart: dict[int, Trace] = {}  # where a piece pressed onto its walls splits: its end's trace, past a break
        if not pieces:  # a closed loop; its tree (``done``) is traced at the width it closed at
            pw = done[0][0] if done else width
            for k in range(n):
                at_width[k] = pw
                if not (dropped[k - 1] or dropped[k]):
                    places[k] = self.place(k, pw, exact=exact)
                    ends_in[k] = places[k].trace
            runs = [([(i + t) % n for t in range((j - i) % n + 1)], None, None) for i, j in self._groups(dropped)]
            if all(dropped):  # a ring used up to one point
                runs = [(list(range(n)), None, None)]
        for first, last, start, end in pieces:
            final = done.get(first % n)
            pw = width if final is None else final[0]
            head = self._end_trace(self._wall_of(start, ends[start]), ends[start], pw)
            tail = self._end_trace(self._wall_of(end, ends[end]), ends[end], pw)
            if isinstance(start, tuple):
                ends_out[first % n] = head
            else:
                ends_in[first % n] = head
            ends_in[last % n] = tail
            for t in range(first + 1, last):
                k = t % n
                at_width[k] = pw
                if not (dropped[(t - 1) % n] or dropped[k]):
                    places[k] = self.place(k, pw, exact=exact)
                    ends_in[k] = places[k].trace
            split = None if final is None else final[1][0]
            if split is not None:  # pressed onto its walls: the start's point, then the end's
                runs.append(([t % n for t in range(first, split)], 0, head))
                runs.append(([t % n for t in range(split, last + 1)], last - split, tail))
                if not _coincide(head.end, tail.end) and _length(_sub(head.end.co, tail.end.co)) > _SEGMENT_MEET_TOL:
                    apart[split % n] = tail
                continue
            for s, e in self._piece_runs((first, last), dropped):
                members = [t % n for t in range(s, e + 1)]
                if s == first:
                    runs.append((members, 0, head))
                elif e == last:
                    runs.append((members, len(members) - 1, tail))
                else:
                    runs.append((members, None, None))
        spots = [None if tr is None else tr.end for tr in ends_in]  # each vertex's new point
        out_spots = {k: tr.end for k, tr in ends_out.items()}
        for members, at, trace in runs:
            if at is None:
                at = members.index(self._holder(members, xy, places, ends_in))
                trace = ends_in[members[at]]
            for t, k in enumerate(members):
                if t != at:
                    way = members[at : t + 1] if t > at else members[t : at + 1][::-1]
                    ends_in[k], places[k] = self._member(k, way, trace, xy[k])
                    spots[k] = trace.end
                elif trace is ends_out.get(k):
                    out_spots[k] = trace.end
                else:
                    spots[k] = trace.end

        points: list[SurfacePoint] = []
        anchors: list[int | None] = [None] * n
        breaks: list[int] = []
        out_at: dict[int, int] = {}  # a cut's right end's index in points

        pending: list[bool] = [False]  # a break goes before the next point appended (a cut shared its end point)

        def same(p: SurfacePoint, q: SurfacePoint) -> bool:  # one place, whatever kinds the two points have
            return _coincide(p, q) or _length(_sub(p.co, q.co)) <= _ANCHOR_SNAP_TOL

        inner: list[int] = []  # the breaks inside one piece (``Cut.inner``)

        def put(pt: SurfacePoint, broken: bool, within: bool = False) -> int:
            if broken or pending[0]:
                breaks.append(len(points))
                if within and not pending[0]:
                    inner.append(len(points))
                pending[0] = False
            points.append(pt)
            return len(points) - 1

        def add(pt: SurfacePoint) -> int:
            # Points within the weld of the one before are one: no segment of the cut is that short.
            if not points or not (_coincide(points[-1], pt) or _length(_sub(points[-1].co, pt.co)) <= self._weld):
                return put(pt, False)
            # The two are one point on the element that joins the most faces: a mesh vertex the loop passes within the
            # weld of (two crossings on edges that meet there) or holds already, else an edge point over a face point.
            q, rank = points[-1], {"vert": 2, "edge": 1}
            shared = set(pt.edge or ()) & set(q.edge or ()) if pt.kind == q.kind == "edge" and pt.edge != q.edge else ()
            v = next(iter(shared), None)
            if v is not None and all(_length(_sub(self.band.verts[v], p.co)) <= 2.0 * self._weld for p in (q, pt)):
                points[-1] = SurfacePoint(kind="vert", face=pt.face, co=self.band.verts[v], vert=v)
            elif rank.get(pt.kind, 0) > rank.get(q.kind, 0):
                points[-1] = pt
            return len(points) - 1

        def head_of(k: int) -> Trace:
            return ends_out.get(k, ends_in[k])

        # A piece in its final state, not pressed onto its walls (closed into a ridge, or at rest), keeps its points
        # joined but where a segment of it runs along the open border (``_along_wall``), or two of its points lie on
        # one open edge: it is pressed onto that wall there, and leaves the points with a break between them, not an
        # edge along the wall (whose trace float noise would send either side of the border).
        resting = {t % n for p in pieces if p[0] % n in done and done[p[0] % n][1][0] is None for t in range(p[0], p[1])}

        def add_on(pt: SurfacePoint, k: int, along: bool = False) -> int:
            if k in resting and points and same(points[-1], pt):  # one place: one point, not two across a break
                return len(points) - 1
            if along or k in resting and points and self._along_open(points[-1], pt):
                return put(pt, True, True)
            return add(pt)

        # Segments of pieces in their final states: where a cut between two of them leaves its two ends on one place,
        # that place is one point, and the break goes before the next.
        finished = {t % n for p in pieces if p[0] % n in done for t in range(p[0], p[1])}

        cut_at = set(cuts)
        # A closed loop starts on a vertex that begins its group, so no group wraps past the end; on a cut, where
        # every segment is dropped.
        start = 0
        if closed:
            start = next((k for k in range(n) if not dropped[k - 1] and k not in cut_at), None)
            if start is None:
                start = next((k for k in range(n) if not dropped[k - 1]), min(cut_at, default=0))
        anchors[start] = add(head_of(start).end)
        if start in cut_at:
            out_at[start] = anchors[start]
        open_loop = not closed or bool(cuts)
        for i in range(len(dropped)):
            k = (start + i) % n
            k1 = (k + 1) % n
            if k1 in apart:  # a piece pressed onto its walls: no edge on to its end's point
                anchors[k1] = len(points) - 1 if same(points[-1], apart[k1].end) else put(apart[k1].end, True, True)
            elif dropped[k] or (open_loop and _snapped_together(out_spots.get(k, spots[k]), spots[k1])):
                anchors[k1] = out_at.get(k, anchors[k])
            else:
                along = k in resting and self._along_wall(k, head_of(k).end, spots[k1], alt.get(k, xy[k]), xy[k1])
                for pt in [] if along else self._wave_segment(k, head_of(k), ends_in[k1]).crossings:
                    add_on(pt, k)
                if k1 != start or k1 in cut_at:  # a closed loop's last segment ends on the start anchor
                    anchors[k1] = add_on(spots[k1], k, along)
            if k1 in cut_at and k1 != start:  # the loop opens here: no edge on to the right end
                if k in finished and k1 in finished and same(points[-1], out_spots[k1]):
                    out_at[k1], pending[0] = len(points) - 1, True
                else:
                    out_at[k1] = put(out_spots[k1], True)
        if closed and start in cut_at:
            breaks.insert(0, 0)
        # The last segment of a closed loop ends on the first anchor; drop a tail repeating it.
        while closed and not cuts and len(points) > 1 and (
                _coincide(points[-1], points[0]) or _length(_sub(points[-1].co, points[0].co)) <= self._weld):
            last = len(points) - 1
            points.pop()
            anchors = [0 if i == last else i for i in anchors]

        connectors = []
        for x in sorted(set(at_width), reverse=True):  # rails take their leg at the width they are placed at
            connectors += self._connectors([p if w == x else None for p, w in zip(places, at_width)], anchors, x, exact)
        for k in sorted(cut_at, key=lambda c: out_at[c]):
            for at, p in ((anchors[k], xy[k]), (out_at[k], alt[k])):
                leg = self._cut_connector(k, p, points[at])
                if leg and (self.band.chain[k], at) not in connectors:
                    connectors.append((self.band.chain[k], at))
        return Cut(points, anchors, connectors, width, False, tuple(breaks), tuple(inner))

    def _wave_segment(self, k: int, a: Trace, b: Trace) -> Trace:
        """``Slider._segment`` for the destructive solve: a segment that ends in a face holding ``b``'s end meets it
        within the development noise (``_DEV_NOISE`` x band scale) or the weld, whichever is larger.

        Unfolded along the segment, the faces of a surface that is not quite flat (modelling noise of some 1e-5) land
        a hair off where ``b``'s own trace unfolded them, more so across slivers: a segment ending right on its partner
        in the plane then misses it in 3D by a few 1e-6, past ``_SEGMENT_MEET_TOL``. A real miss ends elsewhere.
        """
        surf = self._surf
        loose = max(_SEGMENT_MEET_TOL, self._weld, _DEV_NOISE * self._scale)
        try:
            seg = trace_segment(self.band, k, a, b, _surface=surf, meet_tol=loose)
        except _InconsistentDevelopmentError as exc:
            raise OutOfRoom(f"segment {k} misses its partner point") from exc
        if seg.blocked:
            raise OutOfRoom(f"segment {k} leaves the band")
        if _length(_sub(seg.end.co, b.end.co)) > _SEGMENT_MEET_TOL and not self._face_holds(seg._face, b.end):
            raise OutOfRoom(f"segment {k} misses its partner point")
        return seg

    def _face_holds(self, f: int, sp: SurfacePoint) -> bool:
        """Whether face ``f`` holds surface point ``sp``: it is in ``f``, or on an edge or vertex of it."""
        loop = self._surf.layout(f).loop
        if sp.kind == "vert":
            return sp.vert in loop
        if sp.kind == "edge":
            return all(v in loop for v in sp.edge)
        return sp.face == f

    def _solve_parts(self, width: float, exact: bool) -> Cut:
        """The cut past a split: each ring's own cut, one after the other in chain order, a break before each.

        A ring that closes on itself starts at its break (``Cut.rings``). Each
        chain vertex anchors on its ring (``_homes``), and keeps that ring's
        connectors; a connector from off the chain (a rail's end) goes with the
        point it reaches.
        """
        parts = self._wave_of(exact).parts
        n = len(self.band.chain)
        homes = self._homes(exact)
        index = {v: k for k, v in enumerate(self.band.chain)}
        cuts = [p._solve(width, exact, True, destructive=True) for p in parts]
        order = sorted(range(len(parts)), key=lambda i: min((k for k in range(n) if homes[k] == i), default=n))
        points: list[SurfacePoint] = []
        anchors: list[int | None] = [None] * n
        connectors: list[tuple[int, int]] = []
        breaks: set[int] = set()
        inner: list[int] = []
        rings: list[int] = []
        for i in order:
            cut, off = cuts[i], len(points)
            if not cut.points:
                continue
            mine = [k for k in range(n) if homes[k] == i]
            used = {cut.anchors[k] for k in mine if cut.anchors[k] is not None}
            breaks.add(off)
            breaks.update(off + b for b in cut.breaks)
            inner += [off + b for b in cut.inner]
            rings += [off + b for b in cut.rings] if cut.breaks else [off]
            points += cut.points
            for k in mine:
                anchors[k] = None if cut.anchors[k] is None else off + cut.anchors[k]
            for vid, at in cut.connectors:
                k = index.get(vid)
                if (k is None and at in used) or (k is not None and homes[k] == i):
                    connectors.append((vid, off + at))
        return Cut(points, anchors, connectors, width, False, tuple(sorted(breaks)), tuple(inner), tuple(rings))

    def _cut_connector(self, k: int, p: Vec2, end: SurfacePoint) -> bool:
        """Whether cut vertex ``chain[k]`` connects to one of its ends: ``end``, at ``p`` in its wedge frame.

        Both ends of a cut connect to the cut vertex where the straight leg there
        crosses nothing and runs clear onto the end (the ``_connectors`` rule for
        a miter), so the two pieces either side of the break each close their own
        strip. A leg that would cross an edge, or leave the band on the way, is
        left out; so is one longer than any of ``chain[k]``'s own faces reaches
        from it, which must cross an edge, without tracing it.
        """
        if k not in self._fan_reach:
            surf, v = self._surf, self.band.chain[k]
            self._fan_reach[k] = max(
                (_len2(_sub2(q, lay.pts[v])) for f, loop in self.band.faces.items() if v in loop
                 for lay in (surf.layout(f),) for q in lay.pts.values()), default=0.0)
        if _len2(p) > self._fan_reach[k] + self._surf.tol:
            return False
        try:
            trace = self._straight(k, p).trace
        except OutOfRoom:
            return False
        return not trace.blocked and not trace.crossings and _length(_sub(trace.end.co, end.co)) <= _SEGMENT_MEET_TOL
