"""UV Stripe: unwrap each selected strip of faces as one straight UV strip, without stretch by default.

Every edge-connected island of selected faces becomes a ``uv_stripe_core.Strip``
(``uv_stripe_select_core.strip_from_faces``), built from world positions so the
object's scale shows in the aspect. The whole island is built first and then torn
by slicing its rows at the chosen rungs: where a tear lowers the stretch (Auto's
bend cuts) and at the seams inside it (Split at Seams). Only an island that is no
strip as a whole is split at its seams into islands built one by one. Every piece
is laid out by what must be straight on it (Straight Sides, Ends, relaxed by
Stretch Limit; ``uv_stripe_auto_core``), the layout picked by measured stretch.
The pieces are written into the active UV map through ``uv_stripe_bridge``; no
``bpy.ops.uv`` call.

Invoked (a key, a menu, a pie) the operator starts its interactive mode with the last-used options;
``execute`` (the redo panel, scripts) lays the strips out at once with the options it holds. In the
interactive mode every option has a key, and every change restores
the UVs and seams the selected faces had and lays them out again, so the UV editor
follows live; the viewport shows the four sides of every piece, straight or free,
and LMB on a side toggles that side of that piece (``side_picks``). Enter / Space
keep the result (one undo step), Esc / RMB put the snapshot back. C picks cuts: LMB
the loop across the strip through the edge under the cursor (on a strip several faces
wide the island is torn along it, ``island_cuts``), Alt + LMB that one edge. On a
strip one face wide the loop is the cross edge itself: on a closed ring with no break
yet the click breaks it there (``cup_breaks``), and the ring is then laid out as one
open strip from there; elsewhere the click removes that break, marks or unmarks a cut
by hand (``manual_cuts``) or skips or restores one of Auto's tears (``skipped_cuts``). LMB on an
automatic junction cut or on Auto's tear of a strip several faces wide (``_tear_wide``) takes it back the
same way, and restores it.
V picks lines to straighten (``straight_lines``): LMB the loop through the edge under
the cursor, Alt + LMB that one edge; a line running along the strip is laid on one
horizontal line in UV, one across it on one vertical line, under every Straight Sides
and through every shape Stretch Limit relaxes a piece to. Under Straight Sides None
the clicked edge is also the edge its piece is aligned to (``align_edges``); G cycles
what the pieces unfolded at their real shape are aligned to (``shape_align``). The
cuts and the straightened lines are drawn while the operator runs; while picking, the
loop or edge a click would change is drawn before the click.

The plain wheel zooms the view. Ctrl + Wheel drives Balance in every state (Ctrl +
Shift: fine; B jumps 0 / 0.5 / 1): a step lays out at once on a warm, capped solve
and a timer runs the cold one in slices once the wheel is still; Alt + Wheel is
Stretch Limit, Shift + Wheel Offset Limit (with Random Offset on; else the view pans).
An island no rule reads as one strip is cut automatically at its junctions and
slits (``uv_stripe_split_core``), every part its own strip; when that
fails but picked corners or a cut could help, the island waits: the interactive
mode draws its boundary and corner candidates and asks for four corners (LMB near
a boundary vertex, ``corner_picks``) or a cut (C on an inner edge, ``island_cuts``).
Alt + LMB picks an island's seed face (``seed_faces``: its start, its main run at a
branch), Shift + Alt + LMB its guide faces (``guide_faces``).
"""

import dataclasses
import json
import math
import time
from dataclasses import dataclass, field

import bmesh
import bpy
from bpy.props import BoolProperty, EnumProperty, FloatProperty, IntProperty, StringProperty
from bpy_extras import view3d_utils
from mathutils import Vector

from ..ui.draw import Role, safe_handler_add, safe_handler_remove
from ..ui.draw import primitives as draw
from ..ui.hud import HUDOverlay, HUDParam, MoreOptions, build_help, capture_event, more_options_property
from ..ui.hud.more import MORE_OPTIONS_HELP
from ..utils import (
    picking, uv_stripe_auto_core, uv_stripe_balance_core, uv_stripe_core, uv_stripe_select_core, uv_stripe_split_core,
)
from . import uv_stripe_bridge

EPS = 1e-6
SIDES_CYCLE = [item[0] for item in uv_stripe_bridge.STRAIGHT_SIDES_ITEMS]
SIDES_NAMES = {item[0]: item[1] for item in uv_stripe_bridge.STRAIGHT_SIDES_ITEMS}
ENDS_CYCLE = [item[0] for item in uv_stripe_bridge.ENDS_ITEMS]
ENDS_NAMES = {item[0]: item[1] for item in uv_stripe_bridge.ENDS_ITEMS}
BALANCE_JUMPS = (0.0, 0.5, 1.0)      # B: the slider's two ends and its middle
BALANCE_STEP, BALANCE_FINE_STEP = 0.1, 0.02
STRETCH_WHEEL_MIN = 1.05     # Alt + Wheel stops here: at 1.0 every piece would relax to its real shape
REFINE_IDLE = 0.15           # s the wheel must be still before the cold solve runs
REFINE_SLICE = 0.03          # s of cold solve per timer event
CORNER_PICK_RADIUS = 30.0    # px (times the interface scale): how near a boundary vertex the cursor must be
SIDE_PICK_RADIUS = 30.0     # px (times the interface scale): how near a side the cursor must be to pick it
MODE_CYCLE = ["FIT", "IN_PLACE", "ACTIVE"]
MODE_NAMES = {"FIT": "Fit 0–1", "IN_PLACE": "In Place", "ACTIVE": "Active"}
FIT_CYCLE = [item[0] for item in uv_stripe_bridge.ACTIVE_FIT_ITEMS]
FIT_NAMES = {item[0]: item[1] for item in uv_stripe_bridge.ACTIVE_FIT_ITEMS}
OFFSET_CYCLE = [item[0] for item in uv_stripe_bridge.OFFSET_ITEMS]
OFFSET_NAMES = {item[0]: item[1] for item in uv_stripe_bridge.OFFSET_ITEMS}
LIMIT_STEP = 0.05
STRETCH_STEP, STRETCH_FINE_STEP = 0.05, 0.01
ALIGN_ITEMS = [
    ("AUTO", "Auto", "Run the piece along its straighter row: that row's one edge longer than half the row, else "
                     "the line from the row's first to its last vertex"),
    ("LONGEST", "Longest Edge", "Run the piece along its longest edge on the near or far row"),
    ("SHORTEST", "Shortest Edge", "Run the piece along its shortest edge on the near or far row"),
    ("PICKED", "Picked Edge", "Run the piece along the edge picked on it: an edge of the near or far row runs along "
                              "the strip, any other edge across it; a piece with no picked edge uses Auto"),
]
ALIGN_CYCLE = [item[0] for item in ALIGN_ITEMS]
ALIGN_NAMES = {item[0]: item[1] for item in ALIGN_ITEMS}
PASS_KEYS = {"N", "T"}   # the sidebar and the toolbar still toggle while the modal runs
NAVIGATION = {"MIDDLEMOUSE", "WHEELUPMOUSE", "WHEELDOWNMOUSE", "TRACKPADPAN", "TRACKPADZOOM"}

_ACTIVE_HANDLES = set()

# the tears ``_tear_wide`` chose for a strip (cross paths, () for none) by ``_tear_key``: a Balance step or a
# relayout reuses them instead of trying again; forgotten with the cores' caches (``clear_caches``)
_TEARS: dict = {}
_TEARS_SIZE = 256
uv_stripe_core.CACHES.append(_TEARS)


def _purge_handles():
    """Remove any stale draw handlers left behind by a previous reload."""
    while _ACTIVE_HANDLES:
        h = _ACTIVE_HANDLES.pop()
        try:
            safe_handler_remove(h, bpy.types.SpaceView3D, "WINDOW")
        except (ValueError, RuntimeError):
            pass


def _world_context(ctx, faces, matrix):
    """``ctx`` with its density turned from object units into world units over ``faces``' edges.

    ``uv_context`` measures density against object-space lengths, while the strip is
    laid out in world units; the ratio of the two lengths over the strip's own edges
    brings an In Place strip back to the neighbours' texel density on a scaled object.
    """
    if ctx is None:
        return None
    edges = {e for f in faces for e in f.edges}
    local = sum(e.calc_length() for e in edges)
    world = sum((matrix @ e.verts[0].co - matrix @ e.verts[1].co).length for e in edges)
    if local <= 0.0 or world <= 0.0:
        return ctx
    return uv_stripe_bridge.StripeContext(ctx.center, ctx.density * local / world)


def _build(piece, verts, seam_edge=None):
    """The strip of one island (face id -> vertex ids) in world units; raises ValueError."""
    strip = uv_stripe_select_core.strip_from_faces(verts, piece, seam_edge)
    if uv_stripe_core.strip_length(strip) <= EPS:
        raise ValueError("the strip has no length")
    if strip.height <= EPS:
        raise ValueError("the strip has no width")
    return strip


def _build_with(piece, verts, seam_edge=None, corners=None, seed=None, start=None, end=None, cut=None):
    """``_build`` with picked corners, a seed face, a start face, a cut to lie on an end and the line a closed band
    several faces wide is cut open along (``strip_from_faces``)."""
    strip = uv_stripe_select_core.strip_from_faces(verts, piece, seam_edge, corners=corners, seed=seed,
                                                   start_face=start, end=end, cut=cut)
    if uv_stripe_core.strip_length(strip) <= EPS:
        raise ValueError("the strip has no length")
    if strip.height <= EPS:
        raise ValueError("the strip has no width")
    return strip


class _RealKeys(dict):
    """A table keyed by sorted vertex-id pairs that also answers for a pair naming a vertex by its stand-in id
    (``uv_stripe_core.stand_in``: a closed band cut open, ``uv_stripe_core.Strip.cut_path``), as for the pair of
    the mesh vertices it stands for."""

    def __missing__(self, key):
        real = uv_stripe_core.real_pair(key)
        if real == tuple(key):
            raise KeyError(key)
        return dict.__getitem__(self, real)

    def get(self, key, default=None):
        try:
            return self[key]
        except (KeyError, TypeError, IndexError):
            return default

    def __contains__(self, key):
        return self.get(key) is not None


class _NeedsHelpError(ValueError):
    """An island no rule reads as strips, that picked corners or a cut could: the interactive mode asks for
    them."""


def _helpable(verts, island, reason):
    """Whether picked corners or a cut could make ``island`` read as strips: its refusal is about its corners
    (it branches, or its corners are not clear) and ``uv_stripe_split_core.can_be_helped`` (a concave boundary
    vertex, or four clear corner groups). A disc or a cap, a hole, faces wound against each other: no."""
    return "corners" in str(reason) and uv_stripe_split_core.can_be_helped(verts, island)


def _inner_cuts(island, cuts):
    """The edges of ``cuts`` that lie between two faces of the island."""
    uses = {}
    for face in island.values():
        for k, a in enumerate(face):
            e = tuple(sorted((a, face[(k + 1) % len(face)])))
            uses[e] = uses.get(e, 0) + 1
    return {e for e in cuts if uses.get(e) == 2}


# the picked edges, by object name and edge index
EDGE_PROPS = ("cup_breaks", "manual_cuts", "skipped_cuts", "align_edges", "island_cuts")
# the picked vertices and faces, by object name and index, in the same JSON
INDEX_PROPS = ("corner_picks", "seed_faces", "guide_faces")


def _parse_breaks(text):
    """``cup_breaks`` (or ``manual_cuts`` / ``skipped_cuts`` / ``align_edges``) as {object name: [edge index,
    ...]}; anything malformed reads as no edge."""
    try:
        data = json.loads(text) if text else {}
    except ValueError:
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(name): [i for i in indices if isinstance(i, int) and not isinstance(i, bool)]
            for name, indices in data.items() if isinstance(indices, list)}


def _dump_edges(data):
    """{object name: [edge index, ...]} as the JSON the edge properties hold; "" when no object lists an edge."""
    data = {name: indices for name, indices in data.items() if indices}
    return json.dumps(data, sort_keys=True) if data else ""


LINE_AXIS_NAMES = ("ALONG", "ACROSS")    # a straightened line's axis as stored: 0 along the strip, 1 across it


def _parse_lines(text):
    """``straight_lines`` as {object name: [(axis, [edge index, ...], face index or None), ...]} in order, the axis
    "ALONG" (a line laid horizontal) or "ACROSS" (vertical), the face the piece it was picked on holds (a line
    is kept straight on that piece only; stored as ``[face]`` after the axis); anything malformed reads as no
    line."""
    try:
        data = json.loads(text) if text else {}
    except ValueError:
        return {}
    if not isinstance(data, dict):
        return {}

    def number(x):
        return isinstance(x, int) and not isinstance(x, bool)

    def face(line):
        tag = line[1] if len(line) > 1 else None
        return tag[0] if isinstance(tag, list) and len(tag) == 1 and number(tag[0]) else None

    out = {}
    for name, lines in data.items():
        if not isinstance(lines, list):
            continue
        out[str(name)] = [(LINE_AXIS_NAMES[line[0]], [i for i in line[1:] if number(i)], face(line)) for line in lines
                          if isinstance(line, list) and len(line) >= 2 and number(line[0]) and line[0] in (0, 1)
                          and any(number(i) for i in line[1:])]
    return out


def _dump_lines(data):
    """{object name: [(axis, [edge index, ...], face index or None), ...]} as the JSON ``straight_lines`` holds;
    "" for none."""
    data = {name: [[LINE_AXIS_NAMES.index(line[0]), *([[line[2]]] if len(line) > 2 and line[2] is not None else []),
                    *line[1]] for line in lines if line[1]]
            for name, lines in data.items()}
    data = {name: lines for name, lines in data.items() if lines}
    return json.dumps(data, sort_keys=True) if data else ""


def _parse_sides(text):
    """``side_picks`` as {object name: [(face index, edge index, straight), ...]} in order; anything malformed
    reads as no pick."""
    try:
        data = json.loads(text) if text else {}
    except ValueError:
        return {}
    if not isinstance(data, dict):
        return {}

    def number(x):
        return isinstance(x, int) and not isinstance(x, bool)

    out = {}
    for name, picks in data.items():
        if not isinstance(picks, list):
            continue
        out[str(name)] = [(p[0], p[1], bool(p[2])) for p in picks
                          if isinstance(p, list) and len(p) == 3 and number(p[0]) and number(p[1])
                          and isinstance(p[2], (bool, int))]
    return out


def _dump_sides(data):
    """{object name: [(face index, edge index, straight), ...]} as the JSON ``side_picks`` holds; "" for none."""
    data = {name: [[f, e, bool(s)] for f, e, s in picks] for name, picks in data.items() if picks}
    return json.dumps(data, sort_keys=True) if data else ""


@dataclass
class _Result:
    """What one layout pass did, over every object in Edit Mode."""

    selected: int = 0
    done: int = 0
    fitted: bool = False          # Active: some object's pieces were fitted to its active strip
    unfitted: bool = False        # Active: an object's active face was laid out, but nothing was fitted
    skipped: int = 0
    first_reason: str | None = None
    warnings: list[str] = field(default_factory=list)
    infos: list[str] = field(default_factory=list)
    doubles: int = 0              # doubled vertices found in the laid-out islands (not merged)
    merged: int = 0               # doubled vertices merged before the layout
    outline: list = field(default_factory=list)   # world-space segment end points, two per segment
    tears: list = field(default_factory=list)
    stretched: list = field(default_factory=list)  # world-space edges of the stretched faces, each edge once
    stretched_faces: int = 0      # laid-out faces whose UVs stretch them beyond the tolerance
    # per object name: {edge index: ring number} for every cross edge of a selected closed ring (a break pick)
    rings: dict = field(default_factory=dict)
    # per object name: {edge index: the edge indices of its cross path} for every cross path of a selected closed
    # band several faces wide, the lines its break can be picked on (C)
    band_paths: dict = field(default_factory=dict)
    # per object name: {edge index: the edge indices of its cross path} for every automatic tear of a wide strip
    # and every automatic junction cut made (``auto_tears``) or taken back by hand (``auto_skipped``)
    auto_tears: dict = field(default_factory=dict)
    auto_skipped: dict = field(default_factory=dict)
    # per object name, sets of edge indices: every cross edge of a laid-out strip (a cut pick), the cross edges
    # Auto tore the strips at, and the seams Split at Seams tore them at
    cross: dict = field(default_factory=dict)
    bend_tears: dict = field(default_factory=dict)
    seam_tears: dict = field(default_factory=dict)
    skipped_tears: list = field(default_factory=list)   # world-space segments of the skipped tears
    # per object name: {edge index: set of piece numbers} for every edge of a laid-out piece's faces (an align edge
    # pick); an edge the strip is torn at lies in both its pieces
    align_pieces: dict = field(default_factory=dict)
    align_lines: list = field(default_factory=list)     # world-space segments of the picked align edges in use
    # The sides of every open piece. ``sides``: (object name, piece number, side name) -> _Side; ``side_edges``:
    # per object name {edge index: [(piece number, side name), ...]} (an edge the strip is torn at ends two
    # pieces); ``piece_faces``: per object name {face index: piece number}.
    sides: dict = field(default_factory=dict)
    side_edges: dict = field(default_factory=dict)
    piece_faces: dict = field(default_factory=dict)
    unfolded: int = 0             # pieces unfolded at their real shape ("SHAPE"): Align applies
    balanced: int = 0             # pieces laid out balanced: the Balance slider applies
    relaxed: int = 0              # pieces Stretch Limit relaxed, or stretched beyond it: Stretch Limit applies
    refining: bool = False        # a balanced piece is still on its live (warm) solve
    # Islands no rule reads as strips, waiting for picked corners or a cut: each a _Help
    help: list = field(default_factory=list)
    split: list = field(default_factory=list)            # what was done to read an island, for the HUD
    # per object name: every inner edge of an island cut can be picked on that is no cross edge of a strip
    # (an island waiting for help, a strip several faces wide), and {face index: island number} of every
    # selected face (a seed face replaces the seed of its own island)
    cuttable: dict = field(default_factory=dict)
    island_of: dict = field(default_factory=dict)
    seed_points: list = field(default_factory=list)     # world-space centres of the seed faces in use
    seed_lines: list = field(default_factory=list)      # world-space outline segments of the seed faces
    guide_points: list = field(default_factory=list)
    guide_lines: list = field(default_factory=list)
    # The loop picks (C and V). ``pick_pieces``: per object name {edge index: its open piece's record,
    # ``_collect_picks``}; ``cut_loops``: per object name {edge index: the edge indices of the cut made by hand it
    # lies on, mended by LMB there}; ``help_edges``: per object name {inner edge index of an island waiting for help:
    # its island number}; ``islands``: per object name (the islands as face id -> vertex ids, the world positions,
    # {island number: the island cuts made by hand on it}). ``straight_picks`` / ``cut_picks``: per object name the
    # records ``_straight_record`` / ``_cut_loop`` worked out, kept until the next layout. World-space segments of
    # the cuts made by hand (``cut_lines``) and of the straightened lines (``straight_lines``), drawn while the
    # operator runs.
    pick_pieces: dict = field(default_factory=dict)
    pick_faces: dict = field(default_factory=dict)      # per object name {face index: its open piece's record}
    edge_index: dict = field(default_factory=dict)      # per object name ({vertex-id pair: edge index}, the reverse)
    cut_loops: dict = field(default_factory=dict)
    help_edges: dict = field(default_factory=dict)
    islands: dict = field(default_factory=dict)
    straight_picks: dict = field(default_factory=dict)
    cut_picks: dict = field(default_factory=dict)
    cut_lines: list = field(default_factory=list)
    straight_lines: list = field(default_factory=list)


@dataclass
class _Guide:
    """What was picked to read the islands of one object with: corners (vertex ids), cut edges (sorted
    vertex-id pairs), seed faces and guide faces (face ids)."""

    corners: list = field(default_factory=list)
    cuts: set = field(default_factory=set)
    seeds: list = field(default_factory=list)
    guides: list = field(default_factory=list)


@dataclass
class _Help:
    """An island waiting for help: its object, its face indices, its boundary as world-space segments, the
    corner candidates and the corners picked so far (vertex index -> world point), and why it was refused."""

    obj: str
    faces: set
    outline: list
    candidates: dict
    picked: dict
    reason: str
    loop: dict = field(default_factory=dict)       # every boundary vertex (index -> world point): a corner pick

    def prompt(self) -> str:
        if len(self.picked) >= 4:
            return "These corners make no strip: click a picked corner to remove it, or C on an edge to cut"
        if self.picked:
            return f"Click {4 - len(self.picked)} more corner(s), or C on an edge to cut the island"
        return "Click four corners, or C on an edge to cut the island into strips"


@dataclass
class _Side:
    """One side of a laid-out piece: whether it is laid out straight, its edges (indices, in order), the
    piece's face beside each edge (index) and the world-space segment end points, two per edge."""

    straight: bool
    edges: list
    faces: list
    points: list


def _collect_stretched(result, bm, pieces, matrix):
    """Count the laid-out faces their final UVs stretch and keep the world-space segments of their edges, each
    edge once. An open piece (its stretch does not change with a turn, a shift or one scale) takes its stretch from the measure its layout was chosen by
    (``uv_stripe_auto_core.measure``, remembered); any other face is measured on its final UVs
    (``uv_stripe_bridge.stretched_faces``)."""
    stretched, measure_now = [], []
    for n, (strip, piece_faces) in enumerate(pieces):
        known = None
        if not strip.closed:
            try:
                known = uv_stripe_auto_core.measure(strip, (strip.layout, strip.rails, strip.ends), strip.balance)[0]
            except ValueError:
                known = None
        if known is None:
            measure_now += list(piece_faces.values())
            continue
        stretched += [piece_faces[fid] for fid, s in zip(strip.faces, known)
                      if s > uv_stripe_core.STRETCH_TOLERANCE and fid in piece_faces]
    stretched += uv_stripe_bridge.stretched_faces(bm, measure_now, matrix)
    result.stretched_faces += len(stretched)
    for e in dict.fromkeys(e for f in stretched for e in f.edges):
        result.stretched.extend((matrix @ e.verts[0].co, matrix @ e.verts[1].co))


def _doubles_warning(count):
    return (f"UV Stripe: {count} doubled vertices in the strip; turn on Merge Doubles or use Merge by Distance")


def _collect_sides(result, obj, pieces, edge_of, matrix, asked=None):
    """Every open piece's four sides (``uv_stripe_auto_core.piece_sides``) into ``result.sides``, ``side_edges``
    and ``piece_faces``; counts the pieces unfolded at their real shape. A long side is straight as the piece
    is laid out (``uv_stripe_auto_core.laid_shape``: Stretch Limit may have relaxed it). An end is straight as
    asked (``asked(strip)``, the settings and the picked sides; the laid-out shape without it): a free end is
    not forced, though the layout that stretches least may stand it upright all the same. With no long side
    straight both ends are free."""
    edges = result.side_edges.setdefault(obj.name, {})
    owners = result.piece_faces.setdefault(obj.name, {})
    for n, (strip, faces) in enumerate(pieces):
        for f in faces.values():
            owners[f.index] = n
        sides = uv_stripe_auto_core.piece_sides(strip)
        if not sides:
            continue
        shape = uv_stripe_auto_core.laid_shape(strip)
        result.balanced += strip.layout == "BALANCED"
        if asked is not None:
            want = asked(strip)
            result.relaxed += shape.rails != want.rails
            unfolded = shape.rails == "NONE"
            shape = uv_stripe_auto_core.Shape(shape.near, shape.far, want.end0 and not unfolded,
                                              want.end1 and not unfolded)
        result.unfolded += strip.layout == "SHAPE"    # Align turns only the unfold (a balanced piece is not turned)
        for name, side in sides.items():
            record = _Side(getattr(shape, name), [], [], [])
            for pair, fid in side:
                e = edge_of.get(pair)
                if e is None:
                    continue
                record.edges.append(e.index)
                record.faces.append(fid)
                record.points.extend((matrix @ e.verts[0].co, matrix @ e.verts[1].co))
                edges.setdefault(e.index, []).append((n, name))
            if record.edges:
                result.sides[(obj.name, n, name)] = record


def _pieces_worst(pieces) -> float:
    """The worst face stretch of laid-out (strip, faces by id) pieces, by the measure their layout was chosen by
    (``uv_stripe_auto_core.measure``, remembered)."""
    worst = 1.0
    for strip, _faces in pieces:
        if strip.closed:
            continue
        try:
            stretch = uv_stripe_auto_core.measure(strip, (strip.layout, strip.rails, strip.ends), strip.balance)[0]
        except ValueError:
            return float("inf")
        worst = max([worst, *stretch])
    return worst


def _inner_edges(faces, edge_of):
    """The edges (``edge_of``: sorted vertex-id pair -> BMEdge) shared by two of ``faces`` (id -> vertex ids)."""
    uses = {}
    for face in faces.values():
        for k, a in enumerate(face):
            key = tuple(sorted((a, face[(k + 1) % len(face)])))
            uses[key] = uses.get(key, 0) + 1
    return [edge_of[key] for key, n in uses.items() if n == 2 and key in edge_of]


def _collect_guides(result, bm, guide, matrix):
    """The world-space centres and outlines of the seed and guide faces in use, for the preview."""
    bm.faces.ensure_lookup_table()
    for ids, points, lines in ((guide.seeds, result.seed_points, result.seed_lines),
                               (guide.guides, result.guide_points, result.guide_lines)):
        for fid in ids:
            if not 0 <= fid < len(bm.faces):
                continue
            f = bm.faces[fid]
            points.append(matrix @ f.calc_center_median())
            for e in f.edges:
                lines.extend((matrix @ e.verts[0].co, matrix @ e.verts[1].co))


def _collect_preview(result, pieces, matrix):
    """World-space segments of every closed piece's outline (an open piece's outline is its sides,
    ``_collect_sides``), and of the edges the strip is torn at."""
    piece_of = {}
    for n, (_strip, faces) in enumerate(pieces):
        for f in faces.values():
            piece_of[f] = n
    for n, (strip, faces) in enumerate(pieces):
        inside = set(faces.values())
        cut = set()
        if strip.break_edge is not None:
            cut = set(strip.break_edge)
        elif strip.closed and strip.rungs:
            k = strip.seam if strip.seam is not None else uv_stripe_core.sharpest_rung(strip)
            ni, fi = strip.rungs[k]
            cut = {strip.near[ni % len(strip.near)], strip.far[fi % len(strip.far)]}
        for e in {e for f in inside for e in f.edges}:
            linked = [piece_of[g] for g in e.link_faces if g in piece_of]
            ends = (matrix @ e.verts[0].co, matrix @ e.verts[1].co)
            if strip.closed and linked.count(n) == 1:
                result.outline.extend(ends)
            key = tuple(sorted(v.index for v in e.verts))
            ring_cut = bool(cut) and set(key) == cut or key in strip.cut_path
            between = len(set(linked)) > 1 and n == min(linked)     # each tear once
            if ring_cut or between:
                result.tears.extend(ends)


PICK_LINE_TOL = 1e-5     # a line whose UVs spread by less than this of its piece's UV size is straight already


def _collect_picks(result, bm, obj, pieces, edge_of, vertical, island_of):
    """What C and V can pick on the laid-out ``pieces`` of ``obj``, kept for ``_straight_record`` and ``_cut_loop``
    to work out on demand (only for the edges the cursor meets, so a relayout costs nothing more): per edge of an
    open piece (an edge in two pieces, a tear, takes the first) the piece's record in ``result.pick_pieces``: its
    strip, every vertex's place in the strip's own frame from its UVs as written (x along the strip, y across;
    ``vertical``, Orientation Vertical, swaps the UV axes), the tolerance a straight line keeps, its island number
    in ``island_of`` and whether it is several faces wide."""
    layer = bm.loops.layers.uv.active
    if layer is None:
        return
    records = result.pick_pieces.setdefault(obj.name, {})
    along_k = 0 if vertical else 1          # the UV coordinate a line along the strip shares
    index_of = _RealKeys((key, e.index) for key, e in edge_of.items())
    by_face = result.pick_faces.setdefault(obj.name, {})
    for strip, faces in pieces:
        if strip.closed:
            continue
        pos = {}
        for f in faces.values():
            for lp in f.loops:
                if lp.vert.index not in pos:
                    uv = lp[layer].uv
                    pos[lp.vert.index] = (uv[1 - along_k], uv[along_k])
        if not pos:
            continue
        size = max(max(p[0] for p in pos.values()) - min(p[0] for p in pos.values()),
                   max(p[1] for p in pos.values()) - min(p[1] for p in pos.values()), 1e-12)
        record = {"strip": strip, "pos": pos, "tol": PICK_LINE_TOL * size, "index_of": index_of,
                  "island": next((island_of.get(fid) for fid in strip.faces), None),
                  "wide": uv_stripe_balance_core.is_wide(strip), "adjacency": None}
        for fid, face in strip.faces.items():
            by_face[fid] = record
            for a, b in zip(face, face[1:] + face[:1]):
                index = index_of.get((min(a, b), max(a, b)))
                if index is not None:
                    records.setdefault(index, record)       # the first piece; the face under the cursor decides


def _spread_in(pos, vertices, k) -> float:
    values = [pos[v][k] for v in vertices if v in pos]
    return max(values) - min(values) if values else 0.0


class IOPS_OT_Mesh_UV_Stripe(bpy.types.Operator):
    """Unwrap each selected strip of faces as one straight UV strip, without stretch"""

    bl_idname = "iops.mesh_uv_stripe"
    bl_label = "UV Stripe"
    bl_options = {"REGISTER", "UNDO"}
    is_bindable = True

    mode: EnumProperty(
        name="Mode",
        items=[*uv_stripe_bridge.MODE_ITEMS, uv_stripe_bridge.ACTIVE_MODE_ITEM],
        default="ACTIVE",
    )
    active_fit: EnumProperty(
        name="Fit to Active",
        description="How Active sizes the other pieces by the bounding box of the strip holding the active face",
        items=uv_stripe_bridge.ACTIVE_FIT_ITEMS,
        default="HEIGHT",
    )
    orientation: EnumProperty(
        name="Orientation",
        description="Whether the strip runs along U or along V",
        items=uv_stripe_bridge.ORIENTATION_ITEMS,
        default="HORIZONTAL",
    )
    straight_sides: EnumProperty(
        name="Straight Sides",
        description="Which long sides of every piece are laid out straight and horizontal",
        items=uv_stripe_bridge.STRAIGHT_SIDES_ITEMS,
        default="BOTH",
    )
    ends: EnumProperty(
        name="Ends",
        description="Which ends of every piece stand upright; not used while no long side is straight",
        items=uv_stripe_bridge.ENDS_ITEMS,
        default="AUTO",
    )
    stretch_limit: FloatProperty(
        name="Stretch Limit",
        description=(
            "A piece whose worst face stretches more than this is relaxed one step at a time: both long sides "
            "straight, the longer one only, none; it stops at the first step within the limit, else at the least "
            "stretched. A piece whose long sides were clicked is not relaxed"
        ),
        default=uv_stripe_auto_core.DEFAULT_STRETCH_LIMIT,
        min=1.0,
        max=3.0,
        step=5,
        precision=2,
    )
    balance: FloatProperty(
        name="Balance",
        description=uv_stripe_bridge.BALANCE_DESCRIPTION,
        default=uv_stripe_core.DEFAULT_BALANCE,
        min=0.0,
        max=1.0,
        step=10,
        precision=2,
    )
    split_at_seams: BoolProperty(
        name="Split at Seams",
        description=(
            "Tear the strip at edges already marked as seams between two selected faces; "
            "off, the strip is laid out across them (Mark Seams then clears them)"
        ),
        default=True,
    )
    mark_seams: BoolProperty(
        name="Mark Seams",
        description=(
            "Make the seams match the laid-out UV pieces: mark every piece's outline and clear the seams "
            "inside a piece"
        ),
        default=True,
    )

    offset_axis: EnumProperty(
        name="Random Offset",
        description="Shift the laid-out pieces by random amounts, so stacked strips show different parts of the texture",
        items=uv_stripe_bridge.OFFSET_ITEMS,
        default="ALONG",
    )
    offset_limit: FloatProperty(
        name="Offset Limit",
        description="Largest random shift, in UV units; each piece moves by a random amount between minus and plus this",
        default=0.25,
        min=0.0,
        soft_max=1.0,
        step=1,
        precision=3,
    )
    offset_seed: IntProperty(
        name="Offset Seed",
        description="Change to get another random arrangement",
        default=0,
        min=0,
    )

    shape_align: EnumProperty(
        name="Align",
        description="What each piece unfolded at its real shape (no long side straight) runs along",
        items=ALIGN_ITEMS,
        default="AUTO",
    )
    merge_doubles: BoolProperty(
        name="Merge Doubles",
        description="Merge the doubled vertices found in the strip before laying it out",
        default=True,
    )
    # The rings' picked break edges, as JSON {object name: [edge index, ...]}: kept for redo, never saved as a
    # last-used value and no StripeSettings field, so Inset and Edge Slide never see it.
    cup_breaks: StringProperty(
        name="Ring Breaks",
        description="The cross edges the selected rings are opened at, picked in the interactive mode",
        default="",
        options={"HIDDEN", "SKIP_SAVE"},
    )
    # The cut edges marked by hand and the tears of Auto skipped by hand, in the same JSON and kept the same way.
    manual_cuts: StringProperty(
        name="Manual Cuts",
        description="The cross edges the strips are torn at by hand, picked in the interactive mode",
        default="",
        options={"HIDDEN", "SKIP_SAVE"},
    )
    skipped_cuts: StringProperty(
        name="Skipped Tears",
        description="The cross edges Auto no longer tears the strips at, picked in the interactive mode",
        default="",
        options={"HIDDEN", "SKIP_SAVE"},
    )
    # The edges the pieces unfolded at their real shape are aligned to, in the same JSON and kept the same way;
    # each piece takes the first one that is an edge of its faces.
    align_edges: StringProperty(
        name="Align Edges",
        description="The edges the pieces unfolded at their real shape are aligned to, picked in the interactive mode",
        default="",
        options={"HIDDEN", "SKIP_SAVE"},
    )
    # The lines straightened in the interactive mode, as JSON {object name: [[axis, edge index, ...], ...]} (axis 0:
    # along the strip, laid horizontal; 1: across it, laid vertical): kept for redo like the edges above, dropped on
    # a new run.
    straight_lines: StringProperty(
        name="Straightened Lines",
        description="The lines of edges laid straight in UV, picked in the interactive mode",
        default="",
        options={"HIDDEN", "SKIP_SAVE"},
    )
    # The sides clicked straight or free in the interactive mode, as JSON {object name: [[face index, edge
    # index, straight], ...]}: each sets the side holding that edge of the piece holding that face, later over
    # earlier. Kept for redo like the edges above; a new run starts from Straight Sides and Ends.
    side_picks: StringProperty(
        name="Picked Sides",
        description="The sides of the pieces clicked straight or free in the interactive mode",
        default="",
        options={"HIDDEN", "SKIP_SAVE"},
    )
    # The cross edges an island is cut at by hand (each cuts along its cross path) and the corners, seed faces
    # and guide faces picked in the interactive mode, as JSON {object name: [index, ...]}: kept for redo like
    # the edges above, dropped on a new run.
    island_cuts: StringProperty(
        name="Island Cuts",
        description="The edges an island is cut into strips at, picked in the interactive mode",
        default="",
        options={"HIDDEN", "SKIP_SAVE"},
    )
    corner_picks: StringProperty(
        name="Picked Corners",
        description="The corners clicked on islands that read as no strip, in the interactive mode",
        default="",
        options={"HIDDEN", "SKIP_SAVE"},
    )
    seed_faces: StringProperty(
        name="Seed Faces",
        description="The face each island is read from (its start, its main run at a branch), picked with Alt + LMB",
        default="",
        options={"HIDDEN", "SKIP_SAVE"},
    )
    guide_faces: StringProperty(
        name="Guide Faces",
        description="Faces of the main run at a branch, picked with Shift + Alt + LMB",
        default="",
        options={"HIDDEN", "SKIP_SAVE"},
    )
    # Which settings layout the stored values follow (``uv_stripe_bridge.SETTINGS_VERSION``): last-used values stored
    # before it was set are migrated once on invoke (``uv_stripe_bridge.migrate_settings``: old default Slanted ends
    # become Upright Where Cheap); remembered as last used like the settings themselves.
    settings_version: IntProperty(
        name="Settings Version",
        description="Which version of UV Stripe's settings the stored values follow",
        default=0,
        options={"HIDDEN"},
    )
    # Whether the interactive mode's HUD lists every option or only the main ones; remembered as last used.
    show_options: more_options_property()

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.type == "MESH" and obj.mode == "EDIT"

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        layout.prop(self, "mode")
        row = layout.row()
        row.active = self.mode == "ACTIVE"   # greyed out: only Active fits to the active strip
        row.prop(self, "active_fit")
        layout.prop(self, "orientation")
        layout.prop(self, "straight_sides")
        row = layout.row()
        row.active = self.straight_sides != "NONE"     # greyed out: the ends follow the faces under None
        row.prop(self, "ends")
        layout.prop(self, "stretch_limit")
        layout.prop(self, "shape_align")      # pieces relaxed to their real shape use it under any Straight Sides
        layout.prop(self, "balance")
        layout.prop(self, "split_at_seams")
        layout.prop(self, "mark_seams")
        layout.prop(self, "offset_axis")
        col = layout.column()
        col.active = self.offset_axis != "NONE"   # greyed out: no random offset
        col.prop(self, "offset_limit")
        col.prop(self, "offset_seed")
        layout.prop(self, "merge_doubles")

    # ------------------------------------------------------------------
    # Layout
    # ------------------------------------------------------------------

    def _pieces(self, island, verts, picked, seam_cuts, breaks=frozenset(), rings=None,
                manual=frozenset(), skipped=frozenset(), cross=None, bends=None, align_edges=(), side_picks=(),
                guide=None, bands=None):
        """The laid-out pieces of one island as ([(strip, faces by id)], warning, note); raises ValueError,
        ``_NeedsHelpError`` for an island picked corners or a cut could make strips of.

        ``guide`` (``_Guide``) holds what was picked to read islands with: the island's picked corners (four
        make it a patch with those corners), its cut edges (it is cut along their cross paths,
        ``uv_stripe_split_core.split_island``), its seed face (the start of its strip; at a branch, the main
        run) and its guide faces. An island no rule reads as one strip is cut automatically at its junctions
        and slits when it can be; every part of a cut island is its own strip, and ``note`` says what was done.

        The whole island is built and torn where Auto tears it and at the seams inside it
        that are its rungs. An island that is no strip as a whole, one with a seam inside it
        that is no rung, or one that cannot be torn at its seams, is first split at those
        seams and each part built on its own; when a part is then no strip, the island
        that could not be torn stays whole.
        An island that is a closed ring with a rung among ``breaks`` (vertex-id pairs, the
        picked breaks) is opened there as one piece instead, its seams and bends not
        tearing it (``uv_stripe_bridge.prepare_strip``). ``rings`` (a list) gets the rung
        edges of an island that is a closed ring: the edges a break can be picked on.
        A closed band several faces wide is cut open from one boundary loop to the other: along the cross path
        through its picked break (an edge among ``breaks`` on one of its cross paths), else along the seams
        inside it when they are one line from loop to loop (Split at Seams), else along its wall seam as UV Pipe
        picks it (``uv_stripe_select_core.strip_from_faces``); ``bands`` (a list) gets its cross paths (each a
        list of vertex-id pairs), the lines a break can be picked on, and ``rings`` all their edges.
        The rungs among ``manual`` (vertex-id pairs, cut by hand) tear the strip, or each
        part, also on an opened ring; Auto's tears at rungs among ``skipped`` are not
        made. ``cross`` (a set) gets the rung edges of the laid-out strip or parts, the
        edges a cut can be picked on, and ``bends`` (a list) the edges Auto tore them at.
        Every piece is laid out by Straight Sides, Ends, Stretch Limit and Balance, the
        ``side_picks`` ((face id, vertex-id pair, straight)) on top, and aligned by
        ``shape_align``, "Picked Edge" on the first of ``align_edges`` (vertex-id pairs)
        that is an edge of it.
        """
        guide = guide or _Guide()
        corners = [v for v in guide.corners if any(v in face for face in island.values())]
        seed = next((f for f in guide.seeds if f in island), None)
        guides = [f for f in guide.guides if f in island]
        hand_cuts = _inner_cuts(island, guide.cuts)
        if corners or hand_cuts:
            return self._guided(island, verts, picked, corners, hand_cuts, seed, guides, lay_args=(
                manual, skipped, cross, bends, align_edges, side_picks))
        inner = _inner_cuts(island, seam_cuts)
        whole = None
        whole_marks = ((), ())

        def lay(strip, cuts=(), break_edge=None):
            return self._lay_strip(strip, picked, cuts, break_edge, manual, skipped, align_edges, side_picks)

        def done(laid, marks):
            if cross is not None:
                cross.update(marks[0])
            if bends is not None:
                bends.extend(marks[1])
            return laid

        try:
            strip = _build_with(island, verts, start=seed)
        except ValueError as exc:
            strip = None
            refusal = exc
        if strip is not None and strip.cut_path:
            strip, inner = self._band(island, verts, seed, strip, inner, breaks, rings, bands)
        if strip is None and not inner:
            return self._auto_split(island, verts, picked, refusal, seed, guides, (
                manual, skipped, cross, bends, align_edges, side_picks))
        if strip is not None:
            cuts = uv_stripe_select_core.rungs_at(strip, inner)
            picked_break = None
            if strip.closed:
                if rings is not None:
                    rings.append([uv_stripe_select_core.rung_edge(strip, k) for k in range(len(strip.rungs))])
                at = uv_stripe_select_core.rungs_at(strip, breaks)
                if at:
                    picked_break = uv_stripe_select_core.rung_edge(strip, at[0])
            if picked_break is not None or len(cuts) == len(inner):
                whole, whole_marks = lay(strip, cuts, picked_break)
                # a strip that could not be torn at its seams (a side fanning round one rail vertex has no
                # row of its own) is split at them by faces instead, below; failing that it stays whole
                if whole[1] is None or picked_break is not None or not inner:
                    return (*done(whole, whole_marks), None)
        if not inner:
            _build(island, verts)          # raises the island's own reason
        out, reasons, failed = [], [], None
        part_marks = ([], [])
        for part in uv_stripe_select_core.face_islands(island, frozenset(inner)):
            left = _inner_cuts(part, inner)
            seam_edge = next(iter(left)) if len(left) == 1 else None
            try:
                (pieces, reason), marks = lay(_build(part, verts, seam_edge))
            except ValueError as exc:      # one part that is no strip leaves the others
                failed = failed or str(exc)
                continue
            out += pieces
            part_marks[0].extend(marks[0])
            part_marks[1].extend(marks[1])
            if reason:
                reasons.append(reason)
        if whole is not None and (failed or not out):
            return (*done(whole, whole_marks), None)
        if not out:
            raise ValueError(failed)
        if failed:
            reasons.append(f"a part between the seams is skipped: {failed}")
        return (*done((out, (reasons[0] if reasons else None)), part_marks), None)

    def _band(self, island, verts, seed, strip, inner, breaks, rings, bands):
        """A closed band several faces wide (``strip``: cut open at its default line) cut open where it should be,
        as ``_pieces`` says: (the strip, the seams inside it still to tear it at)."""
        paths = uv_stripe_select_core.band_cut_paths(island)
        if bands is not None:
            bands.append(paths)
        if rings is not None:
            rings.append([e for path in paths for e in path])
        picked = next((path for path in paths if set(path) & set(breaks)), None)
        if picked is not None:      # the picked break wins over a seam line across the band: that line is not cut
            on_paths = {e for path in paths for e in path}
            return _build_with(island, verts, start=seed, cut=picked), {e for e in inner if e not in on_paths}
        if inner:
            try:
                along = _build_with(island, verts, start=seed, cut=sorted(inner))
            except ValueError:
                along = None
            if along is not None and set(along.cut_path) == set(inner):
                return along, set()
        return strip, inner

    def _lay_strip(self, strip, picked, cuts=(), break_edge=None, manual=frozenset(), skipped=frozenset(),
                   align_edges=(), side_picks=(), tear=True):
        """``prepare_strip`` with the hand-made cuts and the lines picked straight on the object being laid out
        (``_picked_lines``, set by ``_lay_out``); (its result, (rung edges, bend tear edges)). A strip several
        faces wide that its layout strains (``_strained``) is torn where it bends within its surface first
        (``_tear_wide``, with ``tear``); a strip whose tears are decided already (``_TEARS``: a Balance step, a
        relayout) is laid out torn at once, without laying it out whole first."""
        args = (picked, manual, skipped, align_edges, side_picks)
        if tear and not cuts and break_edge is None:
            key = self._tear_key(strip, skipped, side_picks)
            kept = _TEARS.get(key) if key is not None else None
            if kept:
                torn = self._torn(strip, kept, *args)
                if torn is not None:
                    self._hold_tears(strip, kept, skipped)
                    return torn
        laid, marks = self._lay_strip_once(strip, picked, cuts, break_edge, manual, skipped, align_edges, side_picks)
        if tear and not cuts and break_edge is None:
            torn = self._tear_wide(strip, laid, *args)
            if torn is not None:
                laid, marks = torn
        return laid, marks

    def _strained(self, pieces, side_picks=()):
        """Whether a laid-out piece of ``pieces`` (strip, faces) is not laid out as asked: Stretch Limit relaxed
        a rail it was asked to keep straight, or a face stretches beyond Stretch Limit."""
        for strip, _faces in pieces:
            if strip.closed:
                continue
            try:
                want = uv_stripe_auto_core.picked_shape(
                    strip, uv_stripe_auto_core.default_shape(strip, self.straight_sides, self.ends), side_picks)[0]
            except ValueError:
                return True
            if uv_stripe_auto_core.laid_shape(strip).rails != want.rails:
                return True
        return _pieces_worst(pieces) > self.stretch_limit + 1e-6

    def _tear_key(self, strip, skipped, side_picks):
        """What decides the tears of ``strip`` (``_tear_wide``): the strip with its vertex positions, the settings
        that change them and the picks on it; not Balance, so a Balance step reuses the decision. None for a strip never torn so."""
        if strip.closed or self.straight_sides == "NONE":
            return None
        edges = {(min(a, b), max(a, b)) for face in strip.faces.values() for a, b in zip(face, face[1:] + face[:1])}
        used = sorted({v for face in strip.faces.values() for v in face})
        return (tuple(sorted(strip.faces.items())), tuple((v, tuple(strip.verts[v])) for v in used), tuple(strip.near), tuple(strip.far), tuple(strip.sides[0]),
                tuple(strip.sides[1]), self.straight_sides, self.ends, round(self.stretch_limit, 9),
                frozenset(e for e in skipped if e in edges), tuple(side_picks),
                tuple(sorted((line[0], tuple(sorted(line[1])), *line[2:]) for line in getattr(self, "_picked_lines", ()))))

    def _hold_tears(self, strip, kept, skipped):
        """Offer the tears of ``strip`` to the interactive mode (``_auto_paths``): those made (``kept``) and the
        bends taken back by hand (a cross path holding an edge of ``skipped``)."""
        held = getattr(self, "_auto_paths", None)
        if held is None:
            return
        for path in uv_stripe_split_core.bend_paths(strip):
            if set(path) & set(skipped):
                held.append((path, False))
        held.extend((path, True) for path in kept)

    def _tear_parts(self, strip, chosen):
        """The parts of ``strip`` torn along the cross paths ``chosen``, each built with its tears as its ends
        (``uv_stripe_split_core.along_cuts``); None when a part is no strip or nothing is torn off."""
        edges = frozenset(e for p in chosen for e in p)
        parts = uv_stripe_select_core.face_islands(strip.faces, edges)
        if len(parts) < 2:
            return None
        out = []
        for part in parts:
            inside = {v for face in part.values() for v in face}
            sets = [frozenset(v for e in p for v in e) for p in chosen if {v for e in p for v in e} <= inside]
            try:
                piece = _build_with(part, strip.verts)
                corners = uv_stripe_split_core.along_cuts(strip.verts, part, piece, sets) if sets else None
                if corners is not None:
                    piece = _build_with(part, strip.verts, corners=corners, end=frozenset().union(*sets))
            except ValueError:
                return None
            out.append(piece)
        return out

    def _torn(self, strip, chosen, picked, manual, skipped, align_edges, side_picks):
        """``strip`` torn along ``chosen`` and every part laid out (``_lay_strip`` without tearing again):
        ((pieces, reason), (rung edges, bend tear edges)), or None when it cannot be torn there."""
        parts = self._tear_parts(strip, chosen)
        if parts is None:
            return None
        out, reasons, marks = [], [], ([], [])
        for piece in parts:
            try:
                (pieces, reason), part_marks = self._lay_strip(piece, picked, (), None, manual, skipped, align_edges,
                                                               side_picks, tear=False)
            except ValueError:
                return None
            out += pieces
            marks[0].extend(part_marks[0])
            marks[1].extend(part_marks[1])
            if reason:
                reasons.append(reason)
        return (out, reasons[0] if reasons else None), marks

    def _fits(self, parts) -> bool:
        """Whether every torn part (built strips) lays out straight within Stretch Limit by the cheap straight-row
        layouts (``uv_stripe_auto_core.best_straight``: "TRUE" with free ends, the straight ones with ends
        upright); no balanced solve is run for it."""
        layouts = ("TRUE",) if self.ends in ("SLANTED", "AUTO") else uv_stripe_auto_core.STRAIGHT_LAYOUTS
        for piece in parts:
            best = uv_stripe_auto_core.best_straight(dataclasses.replace(piece, lines=()), layouts)
            if best is None or max(best[1], default=1.0) > self.stretch_limit + 1e-6:
                return False
        return True

    def _tear_wide(self, strip, laid, picked, manual, skipped, align_edges, side_picks):
        """``strip`` (several faces wide) torn across where it bends within its surface
        (``uv_stripe_split_core.bend_paths``), when its own layout (``laid``) is strained (``_strained``): tearing
        comes before stretching, and stretching before the bent shape. The bends whose cross path holds an edge
        of ``skipped`` (taken back by hand) are not torn. Every bend that leaves parts that are strips is torn
        (all at once when that works, else one by one); when the parts then do not lay out straight within
        Stretch Limit by the cheap straight-row layouts (``_fits``) the strip is not torn at all (it stretches
        instead). Otherwise a tear is mended again while the parts still fit without it, so the strip is torn
        into as few pieces as keep it within Stretch Limit. Only the tears chosen are laid out in full. The
        decision is kept (``_TEARS``, ``_tear_key``) so a Balance step or a relayout does not try again. Each part
        keeps its tears as its ends. Returns ((pieces, reason), (rung edges, bend tear edges) of the parts), or
        None when nothing is torn. The bends torn and those taken back by hand go to ``_auto_paths``."""
        key = self._tear_key(strip, skipped, side_picks)
        if key is None or not uv_stripe_balance_core.is_wide(strip):
            return None
        torn = None
        if key in _TEARS:
            kept = _TEARS[key]
        else:
            if not self._strained(laid[0], side_picks):
                return None            # not remembered: a Balance step may strain it, and then it is tried
            kept = self._choose_tears(strip, skipped)
            if kept:                   # the cheap layouts said the parts fit: the real layout must agree
                torn = self._torn(strip, kept, picked, manual, skipped, align_edges, side_picks)
                if torn is None or self._strained(torn[0][0], side_picks):
                    kept, torn = (), None
            while len(_TEARS) >= _TEARS_SIZE:
                _TEARS.pop(next(iter(_TEARS)))
            _TEARS[key] = kept
        self._hold_tears(strip, kept, skipped)
        if not kept:
            return None
        return torn or self._torn(strip, kept, picked, manual, skipped, align_edges, side_picks)

    def _choose_tears(self, strip, skipped):
        """The bends ``_tear_wide`` tears ``strip`` at (cross paths), or () for none."""
        active = [path for path in uv_stripe_split_core.bend_paths(strip) if not set(path) & set(skipped)]
        if not active:
            return ()
        kept = list(active)
        if self._tear_parts(strip, kept) is None:
            kept = []
            for path in active:
                if self._tear_parts(strip, kept + [path]) is not None:
                    kept.append(path)
        parts = self._tear_parts(strip, kept) if kept else None
        if parts is None or not self._fits(parts):
            return ()
        changed = True
        while changed and len(kept) > 1:
            changed = False
            for path in list(kept):
                rest = [p for p in kept if p is not path]
                parts = self._tear_parts(strip, rest)
                if parts is not None and self._fits(parts):
                    kept = rest
                    changed = True
                    break
        return tuple(kept)

    def _lay_strip_once(self, strip, picked, cuts=(), break_edge=None, manual=frozenset(), skipped=frozenset(),
                        align_edges=(), side_picks=()):
        """``prepare_strip`` on ``strip`` as ``_lay_strip`` calls it, without the tears of a wide strip."""
        torn = []
        lines = getattr(self, "_picked_lines", ())
        if strip.cut_path:       # a line along a cut-open band holds the stand-ins of its vertices on the cut too
            lines = tuple((line[0], line[1] | {uv_stripe_core.stand_in(v) for v in line[1]} if line[0] == "ALONG"
                           else line[1], *line[2:]) for line in lines)
        laid = uv_stripe_bridge.prepare_strip(
            strip, picked, self.straight_sides, self.ends, cuts, break_edge=break_edge,
            manual_cuts=uv_stripe_select_core.rungs_at(strip, manual),
            skip_cuts=uv_stripe_select_core.rungs_at(strip, skipped), bend_tears=torn,
            align=self.shape_align, align_edges=align_edges, stretch_limit=self.stretch_limit,
            balance=self.balance, side_picks=side_picks, lines=lines)
        return laid, ([uv_stripe_select_core.rung_edge(strip, k) for k in range(len(strip.rungs))], torn)

    def _lay_split(self, split, verts, picked, seed, lay_args, island=None):
        """The parts of ``split`` (``uv_stripe_split_core.Split``) built and laid out in strip order, the main
        part from ``seed``: ([(strip, faces by id)], warning), each piece its own strip. A part with a cut on one of its rails is read
        with its cuts as its ends instead (``uv_stripe_split_core.along_cuts``: a part cut off across the strip
        near an end) when the cut runs across the strip the whole ``island`` reads as (rail to rail), or runs
        from a rail to an end and that reading stretches its worst face less; a cut along the strip (end to end)
        leaves each part its own rails. Raises ValueError when a part is no strip."""
        manual, skipped, cross, bends, align_edges, side_picks = lay_args
        out, reasons = [], []
        whole = None
        if island is not None:
            try:
                whole = _build_with(island, verts)
            except ValueError:
                whole = None

        def runs(cut) -> str:
            """How a cut runs on the whole strip: "across" (from its near rail to its far rail), "along" (from
            one end to the other) or "other" (a rail to an end; or the island reads as no strip)."""
            if whole is None or whole.closed:
                return "other"
            cut = set(cut)
            if cut & set(whole.near) and cut & set(whole.far):
                return "across"
            if cut & {whole.near[0], *whole.sides[0], whole.far[0]} and cut & {whole.near[-1], *whole.sides[1],
                                                                               whole.far[-1]}:
                return "along"
            return "other"

        for k, part in enumerate(split.parts):
            start = seed if seed in part else None
            strip = _build_with(part, verts, start=start)
            cuts = [c for c in (split.entries[k], split.exits[k]) if c and runs(c) != "along"]
            always = any(runs(c) == "across" for c in cuts)
            corners = uv_stripe_split_core.along_cuts(verts, part, strip, cuts) if cuts else None
            (pieces, reason), marks = self._lay_strip(strip, picked, (), None, manual, skipped, align_edges,
                                                      side_picks)
            if corners is not None:          # a part read across the strip: its cuts become its ends ...
                try:
                    turned = _build_with(part, verts, corners=corners, start=start, end=frozenset().union(*cuts))
                    other = self._lay_strip(turned, picked, (), None, manual, skipped, align_edges, side_picks)
                except ValueError:
                    other = None
                # ... always for a cut across the strip, else when that stretches its worst face less
                if other is not None and (always or _pieces_worst(other[0][0]) < _pieces_worst(pieces) - 1e-6):
                    (pieces, reason), marks = other
            if cross is not None:
                cross.update(marks[0])
            if bends is not None:
                bends.extend(marks[1])
            if reason:
                reasons.append(reason)
            out.extend(pieces)
        return out, (reasons[0] if reasons else None)

    def _auto_split(self, island, verts, picked, refusal, seed, guides, lay_args):
        """An island no rule reads as one strip: cut automatically at its junctions and slits
        (``uv_stripe_split_core.split_island``, the seed face or the mesh's active face picking the main run)
        and each part laid out as its own strip; raises ``_NeedsHelpError`` when it cannot be and picked corners or a cut could
        help, else the island's own reason."""
        active = getattr(self, "_active_face", None)
        main = seed if seed is not None else (active if active in island else None)
        skipped = lay_args[1]
        try:
            split = uv_stripe_split_core.split_island(verts, island, (), main, guides, skip=skipped)
            laid = self._lay_split(split, verts, picked, main, lay_args, island)
        except ValueError as exc:
            self._note_junctions(verts, island, None, skipped)
            if _helpable(verts, island, refusal):
                raise _NeedsHelpError(str(refusal)) from exc
            raise ValueError(str(refusal)) from exc
        self._note_junctions(verts, island, split, skipped)
        note = f"an island that branches is cut at {len(split.parts) - 1} junction(s) into {len(split.parts)} strips"
        return laid[0], laid[1], note

    def _note_junctions(self, verts, island, split, skipped):
        """Offer the automatic junction cuts of ``island`` to the interactive mode (``_auto_paths``): the cross
        paths ``split`` cut automatically, and the concave cross paths taken back by hand (an edge in ``skipped``),
        so a click mends the one and restores the other."""
        held = getattr(self, "_auto_paths", None)
        if held is None:
            return
        auto = set(split.auto_cuts) if split is not None else set()
        for _score, path in uv_stripe_split_core.concave_paths(verts, island):
            if set(path) & set(skipped):
                held.append((path, False))
            elif set(path) <= auto:
                held.append((path, True))

    def _guided(self, island, verts, picked, corners, hand_cuts, seed, guides, lay_args):
        """An island read with what was picked on it: four picked corners make it one patch with them; cut
        edges cut it along their cross paths (automatic cuts added where a part is still no strip), each part
        laid out as its own strip. Raises ``_NeedsHelpError`` while that is not enough."""
        manual, skipped, cross, bends, align_edges, side_picks = lay_args
        if hand_cuts:
            try:
                split = uv_stripe_split_core.split_island(verts, island, hand_cuts, seed, guides, skip=skipped)
                laid = self._lay_split(split, verts, picked, seed, lay_args, island)
            except ValueError as exc:
                self._note_junctions(verts, island, None, skipped)
                raise _NeedsHelpError(str(exc)) from exc
            self._note_junctions(verts, island, split, skipped)
            note = (f"an island is cut by hand into {len(split.parts)} strips" if len(split.parts) > 1 else
                    "a picked cut runs along no line of edges across the island: it does not cut it")
            return laid[0], laid[1], note
        if len(corners) != 4:
            raise _NeedsHelpError(f"{len(corners)} of four corners picked")
        try:
            strip = _build_with(island, verts, corners=corners, start=seed)
            (pieces, reason), marks = self._lay_strip(strip, picked, (), None, manual, skipped, align_edges,
                                                      side_picks)
        except ValueError as exc:
            raise _NeedsHelpError(str(exc)) from exc
        if cross is not None:
            cross.update(marks[0])
        if bends is not None:
            bends.extend(marks[1])
        return pieces, reason, "an island is read with the picked corners"

    def _collect_help(self, result, obj, island, verts, edge_of, guide, reason):
        """Record an island waiting for help (``_Help``): its boundary, its corner candidates and picked corners
        in world space, and its inner edges as cut picks."""
        loop, candidates = uv_stripe_split_core.boundary_corners(verts, island)
        outline = []
        for a, b in zip(loop, loop[1:] + loop[:1]):
            outline.extend((Vector(verts[a]), Vector(verts[b])))
        on_loop = set(loop)
        picked = {v: Vector(verts[v]) for v in guide.corners if v in on_loop}
        shown = {v: Vector(verts[v]) for v in candidates if v not in picked}
        result.help.append(_Help(obj.name, set(island), outline, shown, picked, reason,
                                 {v: Vector(verts[v]) for v in loop}))
        inner = _inner_edges(island, edge_of)
        result.cuttable.setdefault(obj.name, set()).update(e.index for e in inner)
        number = result.island_of.get(obj.name, {}).get(next(iter(island)))
        help_edges = result.help_edges.setdefault(obj.name, {})
        for e in inner:          # LMB cuts along the edge's cross path (``_cut_loop``)
            help_edges.setdefault(e.index, number)
        result.first_reason = result.first_reason or reason

    def _merge_doubles(self, bm, obj, merge):
        """Count the doubled vertices of the selected islands (``uv_stripe_select_core.doubled_vertices``, at
        each island's own tolerance) and, with ``merge``, weld exactly those into their partners; the count."""
        bm.verts.index_update()
        bm.verts.ensure_lookup_table()
        picked = [f for f in bm.faces if f.select and not f.hide]
        bm.faces.index_update()
        ids = {f.index: tuple(v.index for v in f.verts) for f in picked}
        verts = {v.index: tuple(obj.matrix_world @ v.co) for f in picked for v in f.verts}
        targets = {}
        for island in uv_stripe_select_core.face_islands(ids):
            tol = uv_stripe_select_core.island_tolerance(verts, island)
            targets.update(uv_stripe_select_core.doubled_vertices(verts, island, tol))
        if merge and targets:
            kept = {v for f in picked for v in f.verts if v.index not in targets}
            bmesh.ops.weld_verts(bm, targetmap={bm.verts[v]: bm.verts[to] for v, to in targets.items()})
            for f in bm.faces:        # welding can drop the selection of the faces it rebuilds
                if not f.hide and all(v in kept for v in f.verts):
                    f.select_set(True)
        return len(targets)

    def _lay_out(self, context, merge=False):
        """Lay out every selected strip of every mesh in Edit Mode; returns a ``_Result``.

        ``merge`` first welds the doubled vertices of the selection (Merge Doubles: execute and confirm only,
        never the modal's preview, which does not change the mesh).
        """
        result = _Result()
        stored = {name: _parse_breaks(getattr(self, name, "")) for name in EDGE_PROPS}
        stored_index = {name: _parse_breaks(getattr(self, name, "")) for name in INDEX_PROPS}
        stored_sides = _parse_sides(getattr(self, "side_picks", ""))
        stored_lines = _parse_lines(getattr(self, "straight_lines", ""))
        for obj in context.objects_in_mode_unique_data:
            if obj.type != "MESH":
                continue
            me = obj.data
            bm = bmesh.from_edit_mesh(me)
            # the picked edges are named by index: take hold of the edges before a weld renumbers them
            bm.edges.index_update()
            bm.edges.ensure_lookup_table()
            bm.faces.index_update()
            bm.faces.ensure_lookup_table()
            held = {name: [bm.edges[i] for i in data.get(obj.name, ()) if 0 <= i < len(bm.edges)]
                    for name, data in stored.items()}
            held_sides = [(bm.faces[f], bm.edges[e], straight) for f, e, straight in stored_sides.get(obj.name, ())
                          if 0 <= f < len(bm.faces) and 0 <= e < len(bm.edges)]
            bm.verts.ensure_lookup_table()
            held_corners = [bm.verts[i] for i in stored_index["corner_picks"].get(obj.name, ())
                            if 0 <= i < len(bm.verts)]
            held_faces = {name: [bm.faces[i] for i in stored_index[name].get(obj.name, ()) if 0 <= i < len(bm.faces)]
                          for name in ("seed_faces", "guide_faces")}
            held_lines = [(axis, [bm.edges[i] for i in indices if 0 <= i < len(bm.edges)],
                           bm.faces[face] if face is not None and 0 <= face < len(bm.faces) else None)
                          for axis, indices, face in stored_lines.get(obj.name, ())]
            found = self._merge_doubles(bm, obj, merge)
            if merge:
                result.merged += found
            else:
                result.doubles += found
            bm.verts.index_update()
            bm.edges.index_update()
            bm.faces.index_update()
            pairs = {name: list(dict.fromkeys(tuple(sorted(v.index for v in e.verts)) for e in edges if e.is_valid))
                     for name, edges in held.items()}
            breaks, manual, skipped = (set(pairs[name]) for name in ("cup_breaks", "manual_cuts", "skipped_cuts"))
            align_edges = pairs["align_edges"]          # in order: a piece takes the first one in it
            side_picks = [(f.index, tuple(sorted(v.index for v in e.verts)), straight)
                          for f, e, straight in held_sides if f.is_valid and e.is_valid]
            lines = [(axis, frozenset(v.index for e in edges if e.is_valid for v in e.verts),
                      face.index if face is not None and face.is_valid else None)
                     for axis, edges, face in held_lines]
            self._picked_lines = tuple(line for line in lines if len(line[1]) >= 2)
            guide = _Guide([v.index for v in held_corners if v.is_valid], set(pairs["island_cuts"]),
                           [f.index for f in held_faces["seed_faces"] if f.is_valid],
                           [f.index for f in held_faces["guide_faces"] if f.is_valid])
            picked = {f.index: f for f in bm.faces if f.select and not f.hide}
            if not picked:
                continue
            result.selected += 1
            ids = {fid: tuple(v.index for v in f.verts) for fid, f in picked.items()}
            matrix = obj.matrix_world
            verts = {v.index: tuple(matrix @ v.co) for f in picked.values() for v in f.verts}
            seam_cuts = set()
            if self.split_at_seams:
                seam_cuts = {
                    tuple(sorted(v.index for v in e.verts))
                    for f in picked.values()
                    for e in f.edges
                    if e.seam and sum(g.index in picked for g in e.link_faces) == 2
                }
            strips, contexts, pieces, rings, cross, bends, bands = [], [], [], [], set(), [], []
            active_face = bm.faces.active if self.mode == "ACTIVE" else None
            mesh_active = bm.faces.active
            self._active_face = mesh_active.index if mesh_active is not None and mesh_active.index in picked else None
            self._auto_paths = []      # (path, torn) of every automatic tear offered, for C (``_tear_wide``)
            island_of = result.island_of.setdefault(obj.name, {})
            cuttable = result.cuttable.setdefault(obj.name, set())
            cuttable.update(e.index for e in held["island_cuts"] if e.is_valid)     # a cut made can be undone
            edge_of = _RealKeys((tuple(sorted(v.index for v in e.verts)), e) for f in picked.values() for e in f.edges)
            islands = uv_stripe_select_core.face_islands(ids)
            for number, island in enumerate(islands):
                for fid in island:
                    island_of[fid] = number
                try:
                    laid, warning, note = self._pieces(island, verts, picked, seam_cuts, breaks, rings, manual,
                                                             skipped, cross, bends, align_edges, side_picks, guide,
                                                             bands)
                except _NeedsHelpError as exc:
                    self._collect_help(result, obj, island, verts, edge_of, guide, str(exc))
                    continue
                except ValueError as exc:
                    result.skipped += 1
                    result.first_reason = result.first_reason or str(exc)
                    continue
                if warning:
                    result.warnings.append(f"UV Stripe: not split ({warning})")
                if note:
                    result.split.append(note)
                for strip, _faces in laid:
                    if uv_stripe_balance_core.is_wide(strip) and not strip.closed:
                        cuttable.update(e.index for e in _inner_edges(strip.faces, edge_of))
                for strip, faces in laid:
                    piece_faces = list(faces.values())
                    strips.append(strip)
                    pieces.append((strip, faces))
                    contexts.append(_world_context(uv_stripe_bridge.uv_context(bm, piece_faces), piece_faces, matrix))
            if rings:
                result.rings[obj.name] = {edge_of[key].index: n for n, ring in enumerate(rings)
                                          for key in ring if key in edge_of}
            band_paths = result.band_paths.setdefault(obj.name, {})
            for paths in bands:        # LMB on any edge of a band's cross path moves its break there
                for path in paths:
                    indices = tuple(edge_of[key].index for key in path if key in edge_of)
                    for i in indices:
                        band_paths[i] = indices
            result.cross[obj.name] = {edge_of[key].index for key in cross if key in edge_of}
            result.bend_tears[obj.name] = {edge_of[key].index for key in bends if key in edge_of}
            result.seam_tears[obj.name] = {edge_of[key].index for key in seam_cuts if key in edge_of}
            for key in sorted(skipped & cross):
                e = edge_of.get(key)
                if e is not None:
                    result.skipped_tears.extend((matrix @ e.verts[0].co, matrix @ e.verts[1].co))
            # the automatic tears of wide strips and the automatic junction cuts: LMB (C) takes one back or
            # restores it; a taken-back one is drawn as a skipped tear
            made, undone = result.auto_tears.setdefault(obj.name, {}), result.auto_skipped.setdefault(obj.name, {})
            drawn = set()
            for path, active in self._auto_paths:
                indices = tuple(edge_of[key].index for key in path if key in edge_of)
                if not indices:
                    continue
                for i in indices:
                    (made if active else undone)[i] = indices
                if not active and indices not in drawn:
                    drawn.add(indices)
                    for key in path:
                        e = edge_of.get(key)
                        if e is not None:
                            result.skipped_tears.extend((matrix @ e.verts[0].co, matrix @ e.verts[1].co))
            for i in set(made) & set(undone):          # offered both ways (one part torn, another not): torn wins
                undone.pop(i)
            # the cuts made by hand and the straightened lines, drawn also on an object whose islands all wait for
            # help; the islands and their cuts kept for the cut loops C offers (``_cut_loop``)
            ring_edges = {key for ring in rings for key in ring}
            band_edges = {key for paths in bands for path in paths for key in path}
            hand = [key for key in sorted((manual & cross) | (breaks & (ring_edges - band_edges))) if key in edge_of]
            for strip, _faces in pieces:          # a band's picked break: the whole line it is cut open along
                if strip.cut_path and set(strip.cut_path) & breaks:
                    hand += [key for key in strip.cut_path if key in edge_of]
            loops = result.cut_loops.setdefault(obj.name, {})
            island_cuts = {}
            for key in sorted(guide.cuts):          # an island cut: along its cross path, as ``split_island`` cuts
                e = edge_of.get(key)
                owner = next((island_of.get(f.index) for f in e.link_faces if f.index in island_of), None) \
                    if e is not None else None
                if owner is None:
                    continue
                island_cuts.setdefault(owner, set()).add(key)
                path = [p for p in (uv_stripe_split_core.cross_path(islands[owner], key) or [key]) if p in edge_of]
                hand += path
                for p in path:           # LMB on any edge of a cut mends the whole cut
                    loops[edge_of[p].index] = tuple(edge_of[q].index for q in path)
            result.islands[obj.name] = (islands, verts, island_cuts)
            index_of = _RealKeys((key, e.index) for key, e in edge_of.items())
            result.edge_index[obj.name] = (index_of, {i: key for key, i in index_of.items()})
            for key in dict.fromkeys(hand):
                e = edge_of[key]
                result.cut_lines.extend((matrix @ e.verts[0].co, matrix @ e.verts[1].co))
            for _axis, edges, _face in held_lines:
                for e in edges:
                    if e.is_valid and tuple(sorted(v.index for v in e.verts)) in edge_of:
                        result.straight_lines.extend((matrix @ e.verts[0].co, matrix @ e.verts[1].co))
            if not strips:
                continue
            owners = result.align_pieces.setdefault(obj.name, {})   # a tear edge lies in both its pieces
            for n, (_strip, faces) in enumerate(pieces):
                for e in {e for f in faces.values() for e in f.edges}:
                    owners.setdefault(e.index, set()).add(n)
            aligned = {edge_of.get(strip.align_edge) for strip, _faces in pieces
                       if strip.align_edge is not None and strip.layout == "SHAPE" and not strip.closed}
            for e in sorted((e for e in aligned if e is not None), key=lambda e: e.index):
                result.align_lines.extend((matrix @ e.verts[0].co, matrix @ e.verts[1].co))
            holds_active = any(active_face is not None and faces.get(active_face.index) is active_face
                               for _s, faces in pieces)
            fitted = uv_stripe_bridge.finish_stripes(
                bm, pieces, contexts, [0] * len(strips), uv_stripe_bridge.StripeSettings.from_operator(self))
            result.fitted |= fitted
            result.unfitted |= holds_active and not fitted
            _collect_preview(result, pieces, matrix)
            def asked(strip):
                want = uv_stripe_auto_core.picked_shape(
                    strip, uv_stripe_auto_core.default_shape(strip, self.straight_sides, self.ends), side_picks)[0]
                if self.ends == "AUTO" and not uv_stripe_auto_core.ends_picked(strip, side_picks):
                    laid = uv_stripe_auto_core.laid_shape(strip)     # upright where cheap: the ends as laid out
                    want = uv_stripe_auto_core.Shape(want.near, want.far, laid.end0, laid.end1)
                return want

            _collect_sides(result, obj, pieces, edge_of, matrix, asked)
            _collect_stretched(result, bm, pieces, matrix)
            _collect_guides(result, bm, guide, matrix)
            _collect_picks(result, bm, obj, pieces, edge_of, self.orientation == "VERTICAL", island_of)
            result.done += len(strips)
        result.refining = uv_stripe_balance_core.pending() > 0
        if self.mode == "ACTIVE" and result.done and (result.unfitted or not result.fitted):
            result.infos.append(uv_stripe_bridge.ACTIVE_FALLBACK)
        if result.merged:
            result.infos.append(f"UV Stripe: merged {result.merged} doubled vertices")
        if result.doubles:
            result.warnings.append(_doubles_warning(result.doubles))
        return result

    def _report_result(self, result):
        """Report as execute does; returns the operator's result set."""
        if not result.selected:
            self.report({"WARNING"}, "UV Stripe: no faces selected")
            return {"CANCELLED"}
        if result.help:
            self.report({"WARNING"}, f"UV Stripe: {len(result.help)} island(s) need the interactive mode to pick "
                                     f"corners or cuts ({result.help[0].reason})")
        if not result.done:
            self.report({"WARNING"}, f"UV Stripe: nothing laid out ({result.first_reason})")
            return {"CANCELLED"}
        for message in dict.fromkeys(result.split):
            self.report({"INFO"}, f"UV Stripe: {message}")
        for message in dict.fromkeys(result.infos):
            self.report({"INFO"}, message)
        for message in dict.fromkeys(result.warnings):
            self.report({"WARNING"}, message)
        if result.stretched_faces:
            self.report({"WARNING"}, f"UV Stripe: {result.stretched_faces} stretched face(s)")
        if result.skipped:
            self.report({"WARNING"}, f"UV Stripe: {result.done} strip(s), {result.skipped} skipped "
                                     f"({result.first_reason})")
        else:
            self.report({"INFO"}, f"UV Stripe: {result.done} strip(s)")
        return {"FINISHED"}

    def execute(self, context):
        result = self._lay_out(context, merge=self.merge_doubles)
        if result.done:
            for obj in context.objects_in_mode_unique_data:
                if obj.type == "MESH":
                    bmesh.update_edit_mesh(obj.data)
        return self._report_result(result)

    # ------------------------------------------------------------------
    # Snapshot: what the modal restores before every layout and on cancel
    # ------------------------------------------------------------------

    def _take_snapshot(self, context):
        """Per mesh: whether it had a UV layer, the selected faces' loop UVs and their edges' seam flags."""
        self._snapshot = []
        for obj in context.objects_in_mode_unique_data:
            if obj.type != "MESH":
                continue
            bm = bmesh.from_edit_mesh(obj.data)
            bm.faces.index_update()
            bm.edges.index_update()
            layer = bm.loops.layers.uv.active
            faces = [f for f in bm.faces if f.select and not f.hide]
            uvs = {}
            if layer is not None:
                uvs = {(f.index, k): tuple(lp[layer].uv) for f in faces for k, lp in enumerate(f.loops)}
            seams = {e.index: e.seam for f in faces for e in f.edges}
            self._snapshot.append((obj.data, layer is not None, uvs, seams))

    def _restore_snapshot(self, update=True):
        """Put the snapshot back: UVs, seams, and no UV layer where there was none."""
        for me, had_layer, uvs, seams in getattr(self, "_snapshot", []):
            bm = bmesh.from_edit_mesh(me)
            bm.faces.ensure_lookup_table()
            bm.edges.ensure_lookup_table()
            layer = bm.loops.layers.uv.active
            if not had_layer:
                if layer is not None:
                    bm.loops.layers.uv.remove(layer)
            elif layer is not None:
                for (fi, k), co in uvs.items():
                    bm.faces[fi].loops[k][layer].uv = co
            for ei, seam in seams.items():
                bm.edges[ei].seam = seam
            if update:
                bmesh.update_edit_mesh(me)

    def _relayout(self, context, live=False):
        """Restore the snapshot and lay out again with the current options; ``live`` (a wheel step) lets a
        balanced piece show its warm, capped solve (``uv_stripe_balance_core.live``) until ``_refine`` runs the
        cold one."""
        self._restore_snapshot(update=False)
        if live:
            with uv_stripe_balance_core.live():
                self._result = self._lay_out(context)
        else:
            self._result = self._lay_out(context)
        for me, *_rest in self._snapshot:
            bmesh.update_edit_mesh(me)
        if getattr(context, "area", None):
            context.area.tag_redraw()
        try:
            context.workspace.status_text_set(self._status_text())
        except AttributeError:
            pass

    # ------------------------------------------------------------------
    # Cut edges: pick the cross edges a strip is torn at, a closed ring's break among them (C)
    # ------------------------------------------------------------------

    def _pickable(self):
        """Per object name, the edge indices the current pick mode may pick (``_pick_target`` says which of them a
        click would change something at): for the cuts every cross edge of a laid-out strip (``_Result.cross``),
        every edge an island can be cut at (``_Result.cuttable``) and every edge of a cut loop
        (``_Result.cut_loops``); for the straightened lines every edge of a laid-out open piece
        (``_Result.straight_picks``)."""
        result = getattr(self, "_result", None)
        if result is None:
            return {}
        if getattr(self, "_align_picking", False):
            return {name: set(table) for name, table in result.pick_pieces.items()}
        names = set(result.cross) | set(result.cuttable) | set(result.cut_loops) | set(result.pick_pieces) \
            | set(result.band_paths) | set(result.auto_tears) | set(result.auto_skipped)
        return {name: set(result.cross.get(name, ())) | set(result.cuttable.get(name, ()))
                | set(result.cut_loops.get(name, ())) | set(result.pick_pieces.get(name, ()))
                | set(result.band_paths.get(name, ())) | set(result.auto_tears.get(name, ()))
                | set(result.auto_skipped.get(name, ())) for name in names}

    def _record(self, name, index):
        """The open piece's record (``_collect_picks``) edge ``index`` of object ``name`` is picked on: the piece
        holding the face under the cursor (``_hover_face``) when it has the edge (an edge a strip is torn at lies
        in two pieces), else the first piece holding it; None for an edge of no open piece."""
        result = getattr(self, "_result", None)
        if result is None:
            return None
        record = result.pick_pieces.get(name, {}).get(index)
        face = getattr(self, "_hover_face", None)
        under = result.pick_faces.get(name, {}).get(face) if face is not None else None
        if under is not None and under is not record:
            keys = result.edge_index.get(name, ({}, {}))[1]
            key = keys.get(index)
            if key is not None and any(uv_stripe_core.real_pair((a, b)) == key for f in under["strip"].faces.values()
                                       for a, b in zip(f, f[1:] + f[:1])):
                return under
        return record

    def _straight_record(self, name, index):
        """What V would straighten at edge ``index`` of object ``name``, worked out on demand from its piece's
        record (``_collect_picks``) and kept until the next layout: {"loop": (axis, edge indices, straight already,
        can be kept) or None, "edge": (axis, straight already, can be kept)}, or None for an edge of no open piece.
        The loop is the whole long side or end the edge lies on, else the line of edges through it, followed by
        direction through any face (``uv_stripe_split_core.chain_through``; None for a diagonal); the edge alone
        runs along or across by its direction. Whether a
        line can be kept: ``uv_stripe_balance_core.pick_allowed``."""
        result = getattr(self, "_result", None)
        if result is None:
            return None
        cache = result.straight_picks.setdefault(name, {})
        record = self._record(name, index)
        slot = (index, id(record))
        if slot in cache:
            return cache[slot]
        if record is None:
            cache[slot] = None
            return None
        strip, pos, tol, index_of = record["strip"], record["pos"], record["tol"], record["index_of"]
        if record["adjacency"] is None:
            record["adjacency"] = uv_stripe_split_core._adjacency(strip.faces)
        key = result.edge_index.get(name, ({}, {}))[1].get(index)
        found = {"loop": None, "edge": None}
        if key is not None and key[0] in pos and key[1] in pos:
            a, b = pos[key[0]], pos[key[1]]
            axis = "ALONG" if abs(a[0] - b[0]) >= abs(a[1] - b[1]) else "ACROSS"
            k = 1 if axis == "ALONG" else 0
            found["edge"] = (axis, abs(a[k] - b[k]) <= tol,
                             uv_stripe_balance_core.pick_allowed(strip, axis, key))
            chain = None
            for axis_, path in (("ALONG", strip.near), ("ALONG", strip.far),
                                ("ACROSS", [strip.near[0], *strip.sides[0], strip.far[0]]),
                                ("ACROSS", [strip.near[-1], *strip.sides[1], strip.far[-1]])):
                pairs = [(min(p, q), max(p, q)) for p, q in zip(path, path[1:]) if p != q]
                if key in pairs:             # a long side or an end: the whole side, however it bends
                    chain = (axis_, pairs)
                    break
            if chain is None:
                chain = uv_stripe_split_core.chain_through(strip.faces, self._chain_frame(strip) or pos, key,
                                                           record["adjacency"])
            if chain is not None:
                axis, pairs = chain
                indices = tuple(index_of[p] for p in pairs if p in index_of)
                vertices = {v for p in pairs for v in p}
                k = 1 if axis == "ALONG" else 0
                found["loop"] = (axis, indices, _spread_in(pos, vertices, k) <= tol,
                                 uv_stripe_balance_core.pick_allowed(strip, axis, vertices))
        cache[slot] = found
        return found

    def _chain_frame(self, strip):
        """Where the lines of ``strip`` are followed (``uv_stripe_split_core.chain_through``): its vertices in its
        "EVEN" layout (both long sides straight, ends upright, the inside relaxed), where a line along the strip
        runs along u and one across it along v however the strip bends or is laid out now. Kept for the run (the
        mesh does not change while the operator runs); None when the strip cannot be laid out so."""
        frames = getattr(self, "_frames", None)
        if frames is None:
            frames = self._frames = {}
        key = (tuple(sorted(strip.faces.items())), tuple(strip.near), tuple(strip.far), tuple(strip.sides[0]),
               tuple(strip.sides[1]))
        if key not in frames:
            try:
                uv = uv_stripe_core.stripe_uvs(dataclasses.replace(strip, layout="EVEN", lines=()))
                frames[key] = {vid: p for (_fid, vid), p in uv.items()}
            except ValueError:
                frames[key] = None
        return frames[key]

    def _cut_loop(self, name, index):
        """The cut LMB makes at edge ``index`` of object ``name`` while picking cuts, worked out on demand and kept
        until the next layout: the edge indices of the cross path through it (``uv_stripe_split_core.cross_path``),
        or None when there is none to offer. On a strip several faces wide the path must run from one long side to
        the other; on an island waiting for help any path (or the edge alone) is taken. Either way it is offered
        only when the island, cut there with the cuts already made, still reads as strips
        (``uv_stripe_split_core.split_island``; on a wide strip without any automatic cut), so a click never leaves
        the island without a layout."""
        result = getattr(self, "_result", None)
        if result is None:
            return None
        cache = result.cut_picks.setdefault(name, {})
        record = self._record(name, index)
        slot = (index, id(record))
        if slot in cache:
            return cache[slot]
        cache[slot] = None
        islands, verts, made = result.islands.get(name, ([], {}, {}))
        number = result.help_edges.get(name, {}).get(index)
        helping = number is not None
        if not helping and (record is None or not record["wide"]):
            return None
        index_of, keys = result.edge_index.get(name, ({}, {}))
        if not helping:
            number = record["island"]
        if number is None or not 0 <= number < len(islands):
            return None
        island = islands[number]
        key = keys.get(index)
        if key is None:
            return None
        if helping:
            path = uv_stripe_split_core.cross_path(island, key) or [key]
        else:
            strip = record["strip"]
            if record["adjacency"] is None:
                record["adjacency"] = uv_stripe_split_core._adjacency(strip.faces)
            path = uv_stripe_split_core.cross_path(strip.faces, key, record["adjacency"])
            if path is None:
                return None
            ends = uv_stripe_split_core._path_ends(path)
            near, far = set(strip.near), set(strip.far)
            if not (ends[0] in near and ends[1] in far or ends[0] in far and ends[1] in near):
                return None
        try:
            if helping:
                uv_stripe_split_core.split_island(verts, island, set(made.get(number, ())) | set(path))
            else:     # the piece it lies on, cut there, must still read as strips without an automatic cut
                split = uv_stripe_split_core.split_island(record["strip"].verts, dict(record["strip"].faces),
                                                          set(path))
                if split.automatic:
                    return None
        except ValueError:
            return None
        cache[slot] = tuple(index_of[p] for p in path if p in index_of)
        return cache[slot]

    def _pick_target(self, name, index):
        """What a click on edge ``index`` of object ``name`` acts on in the current pick mode: (the edge indices,
        whether the click takes a pick back, the axis of a line to straighten or None), or None when it would
        change nothing.

        Cutting (C): LMB mends the cut made by hand the edge lies on (``_Result.cut_loops``), else cuts the cross
        path through it (``_cut_loop``; on a strip one face wide the cross edge itself); Alt + LMB the one edge (a
        seam tear is left alone either way). Straightening (V): a picked line holding the edge is taken back; else
        LMB the line of edges through it, Alt + LMB the edge itself (``_straight_record``), None when it is laid
        straight that way already, when it could not be kept (``uv_stripe_balance_core.pick_allowed``) or when a
        click on it was refused before (``_refused``)."""
        result = getattr(self, "_result", None)
        if result is None:
            return None
        alt = getattr(self, "_alt", False)
        if getattr(self, "_align_picking", False):
            record = self._record(name, index)
            own = set(record["strip"].faces) if record is not None else set()
            held = [i for _axis, line, face in _parse_lines(getattr(self, "straight_lines", "")).get(name, ())
                    if index in line and (face is None or face in own or not own) for i in line]
            if held:
                return tuple(dict.fromkeys(held)), True, None
            found = self._straight_record(name, index)
            if found is None:
                return None
            if alt:
                edge = found.get("edge")
                if edge is None:
                    return None
                loop = (edge[0], (index,), edge[1], edge[2])
            else:
                loop = found.get("loop")
                if loop is None:             # an edge on no line (a diagonal): for Alt + LMB only
                    return None
            axis, edges, straight, allowed = loop
            if straight or not allowed or (name, axis, tuple(sorted(edges))) in getattr(self, "_refused", set()):
                return None
            return tuple(edges), False, axis
        if index in result.seam_tears.get(name, ()):
            return None
        band_path = result.band_paths.get(name, {}).get(index)
        if not alt and band_path is not None:     # a closed band: its break moves to the cross path, or is taken back
            breaks = set(_parse_breaks(getattr(self, "cup_breaks", "")).get(name, ()))
            return band_path, bool(breaks & set(band_path)), None
        auto = result.auto_tears.get(name, {}).get(index)
        if not alt and auto is not None:          # an automatic tear or junction cut: LMB takes it back
            return auto, False, None
        auto = result.auto_skipped.get(name, {}).get(index)
        if not alt and auto is not None:          # one taken back: LMB restores it
            return auto, True, None
        stored ={name_: set(indices) for name_, indices in _parse_breaks(getattr(self, "island_cuts", "")).items()}
        loop = result.cut_loops.get(name, {}).get(index)
        if not alt and loop is not None:
            return tuple(loop), bool(stored.get(name, set()) & set(loop)), None
        if not alt and index not in result.cross.get(name, ()):
            loop = self._cut_loop(name, index)
            return None if loop is None else (loop, False, None)   # LMB takes loops; none here: Alt + LMB
        if index not in result.cross.get(name, ()) and index not in result.cuttable.get(name, ()) \
                and index not in stored.get(name, ()):
            return None              # the edges ``_click_cut`` acts on
        made = set()
        for prop in ("cup_breaks", "manual_cuts", "skipped_cuts", "island_cuts"):
            made |= set(_parse_breaks(getattr(self, prop, "")).get(name, ()))
        return (index,), index in made, None

    def _hover_break(self, context, event):
        """(object, edge index) of the edge under the cursor a click would change something at, or None.

        One of the edges of the face under the cursor that the pick mode may pick (``_pickable``)
        and a click would change something at (``_pick_target``), the one nearest to it on screen.
        """
        region = getattr(context, "region", None)
        rv3d = getattr(context, "region_data", None)
        table = self._pickable()
        if region is None or rv3d is None or not table:
            return None
        objects = [o for o in context.objects_in_mode_unique_data if o.type == "MESH" and table.get(o.name)]
        if not objects:
            return None
        coord = (event.mouse_region_x, event.mouse_region_y)
        hit = picking.raycast_edit_meshes(context, coord, objects, cache=getattr(self, "_pick_cache", None),
                                          region=region, rv3d=rv3d)
        if not hit[0]:
            return None
        face_index, obj = hit[3], hit[4]
        pickable = table.get(obj.name, ())
        bm = bmesh.from_edit_mesh(obj.data)
        bm.faces.ensure_lookup_table()
        if not 0 <= face_index < len(bm.faces):
            return None
        self._hover_face = face_index      # the piece a pick acts on, where an edge lies in two (``_record``)
        edges = [e for e in bm.faces[face_index].edges
                 if e.index in pickable and self._pick_target(obj.name, e.index) is not None]
        if not edges:
            return None
        k, _distance = picking.closest_edge_screen(context, edges, obj.matrix_world, coord)
        return None if k is None else (obj, edges[k].index)

    def _update_hover(self, context, event):
        """Keep what a click would act on (``_pick_target``) under the cursor: (object, edge index, the world-space
        end points of the loop or edge, whether the click takes a pick back), or None when a click would change
        nothing there. Alt (one edge, not the loop) is read from ``event``."""
        self._alt = bool(getattr(event, "alt", False))
        found = self._hover_break(context, event)
        self._hover = None
        if found is None:
            return
        obj, index = found
        target = self._pick_target(obj.name, index)
        if target is None:
            return
        bm = bmesh.from_edit_mesh(obj.data)
        bm.edges.ensure_lookup_table()
        points = []
        for i in target[0]:
            if 0 <= i < len(bm.edges):
                points.extend(obj.matrix_world @ v.co for v in bm.edges[i].verts)
        self._hover = (obj, index, points, target[1])

    def _set_break(self, context, obj, edge_index):
        """Break the ring holding cross edge ``edge_index`` of ``obj`` there and re-lay out; picking goes on.

        Any break already stored for the same ring is replaced. An edge that is no cross
        edge of a selected closed ring changes nothing; returns whether the break was set.
        """
        rings = getattr(self, "_result", _Result()).rings.get(obj.name, {})
        ring = rings.get(edge_index)
        if ring is None:
            return False
        breaks = _parse_breaks(getattr(self, "cup_breaks", ""))
        kept = [i for i in breaks.get(obj.name, []) if rings.get(i) != ring]
        breaks[obj.name] = kept + [edge_index]
        self.cup_breaks = _dump_edges(breaks)
        self._relayout(context)
        return True

    def _click_cut(self, context, obj, edge_index):
        """Change what tears the strip at cross edge ``edge_index`` of ``obj``, re-lay out; picking goes on.

        By the edge's state, first match: on a closed ring with no break yet the ring is
        broken there ("break"); the ring's break is removed ("unbreak"); a cut marked by
        hand is removed ("unmark"); a skipped tear is restored ("restore"); a seam
        tear is left alone (None); a tear of Auto is skipped ("skip"); any other edge is cut
        by hand ("mark"). An edge that is no cross edge of a laid-out strip changes
        nothing (None). Returns what was done.
        """
        result = getattr(self, "_result", None) or _Result()
        name = obj.name
        island_cuts = _parse_breaks(getattr(self, "island_cuts", ""))
        if edge_index not in result.cross.get(name, ()) or edge_index in island_cuts.get(name, []):
            if edge_index not in result.cuttable.get(name, ()) and edge_index not in island_cuts.get(name, []):
                return None
            data = island_cuts
            indices = data.get(name, [])
            action = "uncut" if edge_index in indices else "cut"
            data[name] = [i for i in indices if i != edge_index] if action == "uncut" else indices + [edge_index]
            self.island_cuts = _dump_edges(data)
            self._relayout(context)
            return action
        rings = result.rings.get(name, {})
        ring = rings.get(edge_index)
        data = {prop: _parse_breaks(getattr(self, prop, "")) for prop in EDGE_PROPS}
        breaks = data["cup_breaks"].get(name, [])
        manual = data["manual_cuts"].get(name, [])
        skipped = data["skipped_cuts"].get(name, [])
        if ring is not None and not any(rings.get(i) == ring for i in breaks):
            self._set_break(context, obj, edge_index)
            return "break"
        if edge_index in breaks:
            prop, action, indices = "cup_breaks", "unbreak", [i for i in breaks if i != edge_index]
        elif edge_index in manual:
            prop, action, indices = "manual_cuts", "unmark", [i for i in manual if i != edge_index]
        elif edge_index in skipped:
            prop, action, indices = "skipped_cuts", "restore", [i for i in skipped if i != edge_index]
        elif edge_index in result.seam_tears.get(name, ()):
            return None
        elif edge_index in result.bend_tears.get(name, ()):
            prop, action, indices = "skipped_cuts", "skip", skipped + [edge_index]
        else:
            prop, action, indices = "manual_cuts", "mark", manual + [edge_index]
        data[prop][name] = indices
        setattr(self, prop, _dump_edges(data[prop]))
        self._relayout(context)
        return action

    def _click_cut_loop(self, context, obj, edge_index):
        """LMB while picking cuts on edge ``edge_index`` of ``obj``: the loop through it (``_pick_target``) cut or
        mended as a whole, re-lay out; picking goes on. On a strip one face wide (and for Alt + LMB) it is the
        one edge, ``_click_cut``. A loop across a wide strip or an island is stored as an island cut
        (``island_cuts``): every edge of it, "cut"; a loop holding a stored cut edge is mended, every stored edge
        of it dropped, "uncut". Returns what was done, None when nothing changed."""
        target = self._pick_target(obj.name, edge_index)
        if target is None:
            return None
        loop, mends, _axis = target
        result = getattr(self, "_result", None) or _Result()
        if not getattr(self, "_alt", False) and edge_index in result.band_paths.get(obj.name, {}):
            if not mends:
                return "break" if self._set_break(context, obj, edge_index) else None
            breaks = _parse_breaks(getattr(self, "cup_breaks", ""))
            breaks[obj.name] = [i for i in breaks.get(obj.name, []) if i not in loop]
            self.cup_breaks = _dump_edges(breaks)
            self._relayout(context)
            return "unbreak"
        if not getattr(self, "_alt", False) and (edge_index in result.auto_tears.get(obj.name, {})
                                                 or edge_index in result.auto_skipped.get(obj.name, {})):
            data = _parse_breaks(getattr(self, "skipped_cuts", ""))
            indices = data.get(obj.name, [])
            if mends:
                action, indices = "restore", [i for i in indices if i not in loop]
            else:
                action, indices = "skip", indices + [i for i in loop if i not in indices]
            data[obj.name] = indices
            self.skipped_cuts = _dump_edges(data)
            self._relayout(context)
            return action
        if getattr(self, "_alt", False) or (edge_index in result.cross.get(obj.name, ())
                                            and edge_index not in result.cut_loops.get(obj.name, {})):
            return self._click_cut(context, obj, edge_index)
        data = _parse_breaks(getattr(self, "island_cuts", ""))
        indices = data.get(obj.name, [])
        if mends:
            action, indices = "uncut", [i for i in indices if i not in loop]
        else:
            action, indices = "cut", indices + [i for i in loop if i not in indices]
        data[obj.name] = indices
        self.island_cuts = _dump_edges(data)
        self._relayout(context)
        return action

    def _set_align_edge(self, name, edge_index, remove=False):
        """Store edge ``edge_index`` of object ``name`` as the align edge of its piece: the stored edges of the
        same piece (of either piece, for an edge the strip is torn at) are replaced and Align becomes Picked Edge;
        with ``remove`` the stored edge is dropped instead. An edge of no laid-out piece changes nothing."""
        result = getattr(self, "_result", None) or _Result()
        pieces = result.align_pieces.get(name, {})
        data = _parse_breaks(getattr(self, "align_edges", ""))
        indices = data.get(name, [])
        if remove:
            indices = [i for i in indices if i != edge_index]
        else:
            own = pieces.get(edge_index)
            if not own:
                return
            indices = [i for i in indices if not pieces.get(i, set()) & own and i != edge_index] + [edge_index]
            self.shape_align = "PICKED"
        data[name] = indices
        self.align_edges = _dump_edges(data)

    def _click_straight(self, context, obj, edge_index):
        """LMB while picking lines to straighten on edge ``edge_index`` of ``obj`` (``_pick_target``), re-lay out
        on the live solve (``_refine`` runs the cold one); picking goes on. A picked line holding the edge is taken
        back ("remove"); else the loop through the edge (Alt: the edge alone) is stored to be laid straight
        ("straighten"): along the strip on one horizontal line, across it on one vertical line. Under Straight
        Sides None the edge is also stored as its piece's align edge, and dropped with its line; when the last
        picked align edge goes, Align goes back to what it was before V set it. A new line the layout then does not
        keep straight, or keeps only by squashing a face (infinite stretch), is taken back at once and not offered
        again (``_refused``): no pick is stored that the layout ignores. Returns what was done, None when nothing
        changed (a line laid straight already, or such a refused line)."""
        target = self._pick_target(obj.name, edge_index)
        if target is None:
            return None
        edges, remove, axis = target
        name = obj.name
        before = {prop: getattr(self, prop) for prop in ("straight_lines", "align_edges", "shape_align")}
        align_before = getattr(self, "_align_before", None)
        data = _parse_lines(getattr(self, "straight_lines", ""))
        lines = data.get(name, [])
        record = self._record(name, edge_index)
        own = set(record["strip"].faces) if record is not None else set()

        def mine(line):
            return edge_index in line[1] and (line[2] is None or line[2] in own or not own)

        if remove:
            gone = [line[1] for line in lines if mine(line)]
            data[name] = [line for line in lines if not mine(line)]
            for i in {i for indices in gone for i in indices}:
                if i in _parse_breaks(getattr(self, "align_edges", "")).get(name, ()):
                    self._set_align_edge(name, i, remove=True)
            if not _parse_breaks(getattr(self, "align_edges", "")) and align_before is not None:
                self.shape_align, self._align_before = align_before, None
            action = "remove"
        else:
            face = getattr(self, "_hover_face", None)
            if record is not None and face not in record["strip"].faces:
                face = min(f for f in record["strip"].faces if f >= 0) if record["strip"].faces else None
            data[name] = lines + [(axis, list(edges), face)]
            if self.straight_sides == "NONE":
                if not _parse_breaks(getattr(self, "align_edges", "")) and align_before is None:
                    self._align_before = self.shape_align
                self._set_align_edge(name, edge_index)
            action = "straighten"
        self.straight_lines = _dump_lines(data)
        self._wheel_time = time.monotonic()
        self._relayout(context, live=True)
        self._ensure_timer(context)
        if not remove and not self._line_kept(name, edge_index, axis, edges):
            for prop, value in before.items():
                setattr(self, prop, value)
            self._align_before = align_before
            self._refused = getattr(self, "_refused", set()) | {(name, axis, tuple(sorted(edges)))}
            self._relayout(context, live=True)
            return None
        return action

    def _line_kept(self, name, edge_index, axis, edges):
        """Whether the last layout keeps the line ``edges`` (edge indices, ``axis``) of object ``name`` straight on
        the piece holding edge ``edge_index`` without squashing any of its faces (every face's stretch finite)."""
        result = getattr(self, "_result", None)
        record = self._record(name, edge_index) if result is not None else None
        if record is None:
            return False
        keys = result.edge_index.get(name, ({}, {}))[1]
        vertices = {v for i in edges if i in keys for v in keys[i]}
        pos, strip = record["pos"], record["strip"]
        if _spread_in(pos, vertices, 1 if axis == "ALONG" else 0) > record["tol"]:
            return False
        for face in strip.faces.values():
            if any(v not in pos for v in face):
                continue
            stretch = uv_stripe_core.face_stretch([strip.verts[v] for v in face], [pos[v] for v in face])
            if not math.isfinite(stretch):
                return False
        return True

    def _straight_line_count(self):
        return sum(len(lines) for lines in _parse_lines(getattr(self, "straight_lines", "")).values())

    # ------------------------------------------------------------------
    # Sides: LMB on a side of a piece makes it straight or free
    # ------------------------------------------------------------------

    def _hover_side(self, context, event):
        """(object, piece number, side name) of the side under the cursor, or None.

        The face under the cursor names the piece: the side edge of that face nearest to the
        cursor on screen. Off the faces (or when that face has no side edge), the side edge
        nearest to the cursor among all pieces that is in sight (``_edge_visible``); on an edge
        where the strip is torn, the piece whose face is under the cursor. Either way only within
        ``SIDE_PICK_RADIUS`` pixels (times the interface scale) of the cursor.
        """
        result = getattr(self, "_result", None)
        region = getattr(context, "region", None)
        rv3d = getattr(context, "region_data", None)
        if result is None or region is None or rv3d is None or not result.sides:
            return None
        objects = [o for o in context.objects_in_mode_unique_data if o.type == "MESH" and result.side_edges.get(o.name)]
        if not objects:
            return None
        try:
            scale = float(context.preferences.system.ui_scale)
        except (AttributeError, TypeError, ValueError):
            scale = 1.0
        radius = SIDE_PICK_RADIUS * (scale if scale > 0.0 else 1.0)     # 0 without a window (background)
        coord = (event.mouse_region_x, event.mouse_region_y)
        hit = picking.raycast_edit_meshes(context, coord, objects, cache=getattr(self, "_pick_cache", None),
                                          region=region, rv3d=rv3d)
        if hit[0]:
            obj, face_index = hit[4], hit[3]
            table = result.side_edges.get(obj.name, {})
            piece = result.piece_faces.get(obj.name, {}).get(face_index)
            bm = bmesh.from_edit_mesh(obj.data)
            bm.faces.ensure_lookup_table()
            if piece is not None and 0 <= face_index < len(bm.faces):
                edges = [e for e in bm.faces[face_index].edges
                         if any(n == piece for n, _name in table.get(e.index, ()))]
                k, distance = picking.closest_edge_screen(context, edges, obj.matrix_world, coord)
                if k is not None and distance <= radius:
                    name = next(name for n, name in table[edges[k].index] if n == piece)
                    return obj, piece, name
        under = None                 # (object name, piece) of the face under the cursor, if any
        if hit[0]:
            under = (hit[4].name, result.piece_faces.get(hit[4].name, {}).get(hit[3]))
        near = []
        for obj in objects:
            table = result.side_edges[obj.name]
            bm = bmesh.from_edit_mesh(obj.data)
            bm.edges.ensure_lookup_table()
            for i in table:
                if not 0 <= i < len(bm.edges):
                    continue
                edge = bm.edges[i]
                _k, distance = picking.closest_edge_screen(context, [edge], obj.matrix_world, coord)
                if distance <= radius:
                    near.append((distance, i, obj, edge))
        near.sort(key=lambda item: (item[0], item[1]))
        for _distance, i, obj, edge in near:
            if not self._edge_visible(context, region, rv3d, objects, obj, edge, coord):
                continue
            entries = result.side_edges[obj.name][i]
            own = [entry for entry in entries if under is not None and (obj.name, entry[0]) == under]
            piece, name = (own or entries)[0]     # a tear edge: the piece whose face is under the cursor
            return obj, piece, name
        return None

    def _edge_visible(self, context, region, rv3d, objects, obj, edge, coord):
        """Whether the point of ``edge`` nearest to the cursor on screen is in sight: the edit meshes, raycast
        as the operator picks (``picking.raycast_edit_meshes``) along the view ray through that point, hit
        nothing in front of it."""
        matrix = obj.matrix_world
        a, b = matrix @ edge.verts[0].co, matrix @ edge.verts[1].co
        sa = view3d_utils.location_3d_to_region_2d(region, rv3d, a)
        sb = view3d_utils.location_3d_to_region_2d(region, rv3d, b)
        if sa is None or sb is None:
            return False
        d = sb - sa
        t = 0.0 if d.length_squared == 0.0 else max(0.0, min(1.0, (Vector(coord) - sa).dot(d) / d.length_squared))
        point = a.lerp(b, t)
        pixel = view3d_utils.location_3d_to_region_2d(region, rv3d, point)
        if pixel is None:
            return False
        origin = view3d_utils.region_2d_to_origin_3d(region, rv3d, pixel)
        reach = (point - origin).length
        hit = picking.raycast_edit_meshes(context, pixel, objects, cache=getattr(self, "_pick_cache", None),
                                          region=region, rv3d=rv3d)
        return not hit[0] or (hit[1] - origin).length >= reach - (1e-3 * reach + 1e-5)

    def _update_side_hover(self, context, event):
        """Keep the side under the cursor (``_hover_side``) for the preview and the click."""
        self._side_hover = self._hover_side(context, event)

    def _click_side(self, context, obj, piece, name):
        """Toggle side ``name`` (``uv_stripe_auto_core.SIDE_NAMES``) of piece ``piece`` of ``obj`` and lay out
        again: a long side straight / free, an end upright / slanted. Both sides of the pair (the two long
        sides, or the two ends) are stored as they are laid out now, the clicked one turned over, so the
        piece keeps the other one as shown; the pair's earlier picks on that piece are replaced. Returns the
        side's new state, or None when there is no such side."""
        result = getattr(self, "_result", None) or _Result()
        key = (obj.name, piece, name)
        side = result.sides.get(key)
        if side is None:
            return None
        pair = ("near", "far") if name in ("near", "far") else ("end0", "end1")
        data = _parse_sides(getattr(self, "side_picks", ""))
        picks = data.get(obj.name, [])
        faces = {f for f, n in result.piece_faces.get(obj.name, {}).items() if n == piece}
        mine = set()
        for other in pair:
            record = result.sides.get((obj.name, piece, other))
            if record is not None:
                mine.update(record.edges)
        picks = [p for p in picks if not (p[0] in faces and p[1] in mine)]
        for other in pair:
            record = result.sides.get((obj.name, piece, other))
            if record is None:
                continue
            straight = (not record.straight) if other == name else record.straight
            picks.append((record.faces[0], record.edges[0], straight))
        data[obj.name] = picks
        self.side_picks = _dump_sides(data)
        self._relayout(context)
        return not side.straight

    def _hover_corner(self, context, event):
        """(object name, vertex index) of the boundary vertex of an island waiting for help nearest to the cursor
        on screen, within ``CORNER_PICK_RADIUS`` pixels (times the interface scale), or None."""
        result = getattr(self, "_result", None)
        region = getattr(context, "region", None)
        rv3d = getattr(context, "region_data", None)
        if result is None or not result.help or region is None or rv3d is None:
            return None
        try:
            scale = float(context.preferences.system.ui_scale)
        except (AttributeError, TypeError, ValueError):
            scale = 1.0
        radius = CORNER_PICK_RADIUS * (scale if scale > 0.0 else 1.0)
        coord = Vector((event.mouse_region_x, event.mouse_region_y))
        best = None
        for item in result.help:
            for v, point in item.loop.items():
                pixel = view3d_utils.location_3d_to_region_2d(region, rv3d, point)
                if pixel is None:
                    continue
                d = (pixel - coord).length
                if d <= radius and (best is None or d < best[0]):
                    best = (d, item.obj, v)
        return None if best is None else (best[1], best[2])

    def _click_corner(self, context, name, vertex):
        """Pick or unpick ``vertex`` of object ``name`` as a corner of the island waiting for help that holds it,
        and lay out again; at most four corners an island (a fifth replaces none: it is refused). Returns
        "add", "remove" or None."""
        result = getattr(self, "_result", None) or _Result()
        item = next((h for h in result.help if h.obj == name and vertex in h.loop), None)
        if item is None:
            return None
        data = _parse_breaks(getattr(self, "corner_picks", ""))
        indices = data.get(name, [])
        if vertex in indices:
            action, indices = "remove", [i for i in indices if i != vertex]
        elif len(item.picked) >= 4:
            return None
        else:
            action, indices = "add", indices + [vertex]
        data[name] = indices
        self.corner_picks = _dump_edges(data)
        self._relayout(context)
        return action

    def _face_under(self, context, event):
        """(object, face index) of the selected face under the cursor, or None."""
        region = getattr(context, "region", None)
        rv3d = getattr(context, "region_data", None)
        result = getattr(self, "_result", None)
        if region is None or rv3d is None or result is None:
            return None
        objects = [o for o in context.objects_in_mode_unique_data if o.type == "MESH" and result.island_of.get(o.name)]
        if not objects:
            return None
        hit = picking.raycast_edit_meshes(context, (event.mouse_region_x, event.mouse_region_y), objects,
                                          cache=getattr(self, "_pick_cache", None), region=region, rv3d=rv3d)
        if not hit[0] or hit[3] not in result.island_of.get(hit[4].name, {}):
            return None
        return hit[4], hit[3]

    def _click_face(self, context, obj, face_index, guide):
        """Alt + LMB: make ``face_index`` the seed face of its island (replacing that island's seed; again on the
        seed removes it). Shift + Alt + LMB (``guide``): add the face to, or remove it from, the guide faces.
        Lays out again; returns "seed", "unseed", "guide" or "unguide"."""
        result = getattr(self, "_result", None) or _Result()
        islands = result.island_of.get(obj.name, {})
        prop = "guide_faces" if guide else "seed_faces"
        data = _parse_breaks(getattr(self, prop, ""))
        indices = data.get(obj.name, [])
        if face_index in indices:
            action, indices = ("unguide" if guide else "unseed"), [i for i in indices if i != face_index]
        elif guide:
            action, indices = "guide", indices + [face_index]
        else:
            own = islands.get(face_index)
            action, indices = "seed", [i for i in indices if islands.get(i) != own] + [face_index]
        data[obj.name] = indices
        setattr(self, prop, _dump_edges(data))
        self._relayout(context)
        return action

    def _guide_count(self):
        return sum(len(_parse_breaks(getattr(self, prop, "")).get(name, []))
                   for prop in ("seed_faces", "guide_faces") for name in _parse_breaks(getattr(self, prop, "")))

    def _wheel(self, context, event):
        """A wheel step: Alt: Stretch Limit (Ctrl + Alt: fine), Ctrl: Balance (Ctrl + Shift: fine), Shift:
        Offset Limit while Random Offset is on. Every step lays out again at once, a balanced piece on its warm
        solve; ``_refine`` swaps in the cold one. Returns whether the step was taken: the plain wheel (and
        Shift + Wheel with Random Offset off) is left to the view, to zoom or pan."""
        up = event.type == "WHEELUPMOUSE"
        if event.alt:
            step = STRETCH_FINE_STEP if event.ctrl else STRETCH_STEP
            value = self.stretch_limit + (step if up else -step)
            self.stretch_limit = min(max(round(value, 6), STRETCH_WHEEL_MIN), 3.0)
            self._relayout(context)
        elif event.ctrl:
            step = BALANCE_FINE_STEP if event.shift else BALANCE_STEP
            self.balance = min(max(round(self.balance + (step if up else -step), 6), 0.0), 1.0)
            self._wheel_time = time.monotonic()
            self._relayout(context, live=True)
            self._ensure_timer(context)
        elif event.shift:
            if self.offset_axis == "NONE":
                return False
            self.offset_limit = max(round(self.offset_limit + (LIMIT_STEP if up else -LIMIT_STEP), 6), 0.0)
            self._relayout(context)
        else:
            return False
        return True

    def _ensure_timer(self, context):
        if getattr(self, "_timer", None) is None and getattr(context, "window", None) is not None:
            self._timer = context.window_manager.event_timer_add(0.05, window=context.window)

    def _drop_timer(self, context):
        timer = getattr(self, "_timer", None)
        if timer is not None:
            try:
                context.window_manager.event_timer_remove(timer)
            except (ReferenceError, ValueError, AttributeError):
                pass
        self._timer = None

    def _refine(self, context, budget=REFINE_SLICE):
        """Run the cold solves the live wheel steps left for about ``budget`` seconds once the wheel has been
        still for ``REFINE_IDLE``; when they are all done lay out again with them. Returns whether it did."""
        if not uv_stripe_balance_core.pending():
            return False
        if budget != float("inf") and time.monotonic() - getattr(self, "_wheel_time", 0.0) < REFINE_IDLE:
            return False
        if uv_stripe_balance_core.refine(budget):
            self._relayout(context)
            return True
        return False

    def _balance_text(self):
        result = getattr(self, "_result", None)
        if result is not None and not result.balanced:
            return f"{self.balance:.2f} · no balanced piece to change"
        return f"{self.balance:.2f} · Least Stretch < > Even Texel"

    def _align_edge_count(self):
        return sum(len(indices) for indices in _parse_breaks(getattr(self, "align_edges", "")).values())

    def _manual_cut_count(self):
        return sum(len(indices) for indices in _parse_breaks(getattr(self, "manual_cuts", "")).values())

    def _start_picking(self, context, event, align):
        """Enter the cut pick mode (C), or with ``align`` the pick mode of the lines to straighten (V); the two never
        run at once."""
        self._picking = not align
        self._align_picking = align
        self._side_hover = None
        self._update_hover(context, event)
        self._show_status(context)

    def _stop_picking(self, context):
        self._picking = False
        self._align_picking = False
        self._hover = None
        self._show_status(context)

    def _pick_event(self, context, event):
        """The modal's answer to ``event`` while picking cuts (C) or lines to straighten (V): LMB changes the
        hovered loop, Alt + LMB the hovered edge (pressing or letting go of Alt redraws the hover), the mode's own
        key, Esc or RMB stop picking, the other mode's key switches to it."""
        if event.type == "MOUSEMOVE" or event.type in {"LEFT_ALT", "RIGHT_ALT"}:
            self._update_hover(context, event)
            return {"RUNNING_MODAL"}
        if event.type in NAVIGATION or event.type.startswith("NDOF"):
            return {"PASS_THROUGH"}
        if event.value != "PRESS" and not (event.type == "LEFTMOUSE" and event.value == "DOUBLE_CLICK"):
            return {"RUNNING_MODAL"}
        align = getattr(self, "_align_picking", False)
        own, other = ("V", "C") if align else ("C", "V")
        if event.type == "LEFTMOUSE":
            self._update_hover(context, event)
            if self._hover is not None:
                click = self._click_straight if align else self._click_cut_loop
                click(context, self._hover[0], self._hover[1])
                self._update_hover(context, event)
        elif event.type in {"RIGHTMOUSE", "ESC", own}:
            self._stop_picking(context)
        elif event.type == other:
            self._start_picking(context, event, not align)
        return {"RUNNING_MODAL"}

    def _show_status(self, context):
        try:
            context.workspace.status_text_set(self._status_text())
        except AttributeError:
            pass

    # ------------------------------------------------------------------
    # Modal
    # ------------------------------------------------------------------

    def _start(self, context):
        """Snapshot and first layout; False (reported, restored) when nothing can be laid out."""
        self._take_snapshot(context)
        self._cancel = {name: getattr(self, name) for name in (
            "mode", "active_fit", "orientation", "straight_sides", "ends", "stretch_limit", "balance",
            "split_at_seams", "mark_seams", "offset_axis", "offset_limit", "offset_seed", "merge_doubles",
            "shape_align")}
        self._timer = None
        self._wheel_time = 0.0
        for name in (*EDGE_PROPS, *INDEX_PROPS, "side_picks", "straight_lines"):
            self._cancel[name] = getattr(self, name, "")
        self._picking = False
        self._align_picking = False
        self._alt = False
        self._refused = set()          # (object name, axis, edge indices) of the lines a click could not keep
        self._align_before = None      # Align before V under None set it to Picked Edge
        self._hover = None
        self._side_hover = None
        self._pick_cache = {}
        self._relayout(context)
        if not self._result.done and not self._result.help:
            self._restore_snapshot()
            self._report_result(self._result)
            return False
        if self._result.doubles:
            if self.merge_doubles:
                self.report({"INFO"}, f"UV Stripe: {self._result.doubles} doubled vertices, merged on confirm")
            else:
                self.report({"WARNING"}, _doubles_warning(self._result.doubles))
        return True

    def invoke(self, context, event):
        """The interactive mode, on every invoke (``execute`` serves the redo panel and scripts). Last-used values
        stored by an older version are migrated first (``uv_stripe_bridge.migrate_settings``)."""
        if isinstance(self, bpy.types.Operator):
            uv_stripe_bridge.migrate_settings(self.properties)
            self.settings_version = uv_stripe_bridge.SETTINGS_VERSION
        _purge_handles()
        self._handle = self._handle_view = None
        if not self._start(context):
            return {"CANCELLED"}
        self._build_overlays(context.region)
        self._last_event = capture_event(event, getattr(self, "_last_event", None))
        self._add_handlers(context)
        context.workspace.status_text_set(self._status_text())
        context.window_manager.modal_handler_add(self)
        if context.area:
            context.area.tag_redraw()
        return {"RUNNING_MODAL"}

    def _build_overlays(self, region):
        self._hud = HUDOverlay("uv_stripe")
        self._hud.title = "UV Stripe"
        self._hud.bind_region(region)
        orientation_names = {item[0]: item[1] for item in uv_stripe_bridge.ORIENTATION_ITEMS}
        # Always: Straight Sides, Ends, Balance and More Options. Only when they apply: Stretch Limit, Seed and Guide
        # Faces, Align, Manual Cuts, Straightened Lines, Doubled Vertices. The rows after More Options while it is on
        # (Tab), or while their option is away from its default. Every key works either way.
        self._hud.add_param(HUDParam("Straight Sides (Q)", lambda: SIDES_NAMES[self.straight_sides], "enum"))
        self._hud.add_param(HUDParam("Ends (W)", lambda: ENDS_NAMES[self.ends], "enum",
                                     active_getter=lambda: self.straight_sides != "NONE"))
        self._hud.add_param(HUDParam("Balance (Ctrl + Wheel)", self._balance_text, "str",
                                     active_getter=lambda: getattr(self, "_result", _Result()).balanced > 0))
        self._hud.add_param(HUDParam("Stretch Limit (Alt + Wheel)", lambda: self.stretch_limit, "float", fmt="{:.2f}",
                                     visible_getter=lambda: getattr(self, "_result", _Result()).relaxed > 0))
        self._hud.add_param(HUDParam("Seed and Guide Faces", self._guide_count, "int",
                                     visible_getter=lambda: self._guide_count() > 0))
        self._hud.add_param(HUDParam("Align (G)", lambda: ALIGN_NAMES[self.shape_align], "enum",
                                     visible_getter=self._align_applies))
        self._hud.add_param(HUDParam("Manual Cuts", self._manual_cut_count, "int",
                                     visible_getter=lambda: self._manual_cut_count() > 0))
        self._hud.add_param(HUDParam("Straightened Lines", self._straight_line_count, "int",
                                     visible_getter=lambda: self._straight_line_count() > 0))
        self._hud.add_param(HUDParam("Doubled Vertices", lambda: getattr(self, "_result", _Result()).doubles, "int",
                                     visible_getter=lambda: getattr(self, "_result", _Result()).doubles > 0))
        more = self._more = MoreOptions(self)
        self._hud.add_param(more.row())

        def tab(name, getter, kind, *props, fmt=None, active_getter=None):
            # a More Options row: shown under Tab, and with Tab off while its option is away from the default
            self._hud.add_param(HUDParam(name, getter, kind, fmt=fmt, active_getter=active_getter,
                                         visible_getter=more.when(also=more.changed(*props))))

        # Balance is a slider on Ctrl + Wheel with its own row above (always shown); the placement options sit under
        # More Options, a row also shown with Tab off while its option is away from the default (``MoreOptions``)
        tab("Mode (E)", lambda: MODE_NAMES[self.mode], "enum", "mode")
        tab("Orientation (A)", lambda: orientation_names[self.orientation], "enum", "orientation")
        tab("Fit to Active (D)", lambda: FIT_NAMES[self.active_fit], "enum", "active_fit",
            active_getter=lambda: self.mode == "ACTIVE")
        tab("Split at Seams (S)", lambda: self.split_at_seams, "bool", "split_at_seams")
        tab("Mark Seams (X)", lambda: self.mark_seams, "bool", "mark_seams")
        tab("Random Offset (Z)", lambda: OFFSET_NAMES[self.offset_axis], "enum", "offset_axis")
        tab("Offset Limit (Shift + Wheel)", lambda: self.offset_limit, "float", "offset_limit", fmt="{:.2f}",
            active_getter=lambda: self.offset_axis != "NONE")
        tab("Offset Seed (R)", lambda: self.offset_seed, "int", "offset_seed",
            active_getter=lambda: self.offset_axis != "NONE")
        tab("Merge Doubles (F)", lambda: self.merge_doubles, "bool", "merge_doubles")

        # Every key, hidden until H (the HUD shows only what applies now)
        self._help = build_help("uv_stripe", [
            ("Shape", [
                ("Straight Sides", "Q"),
                ("Ends", "W"),
                ("Balance", "Ctrl + Wheel"),
                ("Balance, fine", "Ctrl + Shift + Wheel"),
                ("Balance: 0, 0.5, 1", "B"),
                ("Stretch Limit (fine: Ctrl)", "Alt + Wheel"),
                ("Align", "G"),
                ("Side straight / free", "LMB on a side"),
            ]),
            ("Picking", [
                ("Pick cuts, break a ring, cut an island", "C"),
                ("Cut a loop / one edge", "LMB / Alt + LMB"),
                ("Pick lines to straighten", "V"),
                ("Straighten a loop / one edge", "LMB / Alt + LMB"),
                ("Corner of an island that is no strip", "LMB on its boundary"),
                ("Seed face of an island", "Alt + LMB on a face"),
                ("Guide face of the main run", "Shift + Alt + LMB"),
            ]),
            ("Placement", [
                ("Mode", "E"),
                ("Orientation", "A"),
                ("Fit to Active", "D"),
                ("Split at Seams", "S"),
                ("Mark Seams", "X"),
                ("Random Offset", "Z"),
                ("Offset Limit", "Shift + Wheel"),
                ("Offset Seed", "R"),
                ("Merge Doubles", "F"),
            ]),
            ("General", [
                MORE_OPTIONS_HELP,
                ("Confirm", "Enter / Space"),
                ("Cancel", "Esc / RMB"),
            ]),
        ], region)

    def _align_applies(self):
        """Whether Align (G) matters now: a piece is laid out unfolded at its real shape (a balanced piece, kept by
        straightened lines, is not turned by it), or Straight Sides is None before anything is laid out."""
        result = getattr(self, "_result", None)
        if result is not None and result.unfolded:
            return True
        return self.straight_sides == "NONE" and (result is None or not result.done)

    def modal(self, context, event):
        try:
            return self._modal(context, event)
        except ReferenceError:
            # bmesh data invalidated mid-modal (undo, addon reload): tear the handler down.
            self._finish(context)
            self.report({"WARNING"}, "UV Stripe: mesh data became invalid — cancelled")
            return {"CANCELLED"}
        except Exception:
            self._finish(context)
            raise

    def _modal(self, context, event):
        if getattr(context, "area", None):
            context.area.tag_redraw()
        self._last_event = capture_event(event, getattr(self, "_last_event", None))

        try:
            theme_prefs = context.preferences.addons["InteractionOps"].preferences.iops_theme
        except (KeyError, AttributeError):
            theme_prefs = None
        if theme_prefs is not None:
            helpo = getattr(self, "_help", None)
            hud = getattr(self, "_hud", None)
            if helpo is not None and helpo.handle_drag_event(context, event, theme_prefs):
                return {"RUNNING_MODAL"}
            if hud is not None and hud.handle_drag_event(context, event, theme_prefs):
                return {"RUNNING_MODAL"}
            if helpo is not None and helpo.handle_toggle_event(event, theme_prefs):   # H
                return {"RUNNING_MODAL"}
            if hud is not None and hud.handle_param_toggle_event(event, theme_prefs):
                return {"RUNNING_MODAL"}

        if event.type == "TIMER":
            self._refine(context)
            return {"PASS_THROUGH"}
        if event.type in {"WHEELUPMOUSE", "WHEELDOWNMOUSE"}:      # in every state, the pick modes too
            # the plain wheel zooms the view; a modifier wheel steps an option
            return {"RUNNING_MODAL"} if self._wheel(context, event) else {"PASS_THROUGH"}
        if getattr(self, "_picking", False) or getattr(self, "_align_picking", False):
            # picking cuts or lines to straighten: LMB takes the loop (Alt: the edge) before the confirm
            return self._pick_event(context, event)

        if event.type == "MOUSEMOVE":
            self._update_side_hover(context, event)
            return {"RUNNING_MODAL"}
        if event.type in NAVIGATION or event.type.startswith("NDOF"):
            return {"PASS_THROUGH"}

        if event.value != "PRESS" and not (event.type == "LEFTMOUSE" and event.value == "DOUBLE_CLICK"):
            return {"RUNNING_MODAL"}
        if self._more.handle(event):      # Tab: only the HUD changes
            self._show_status(context)
            return {"RUNNING_MODAL"}
        if event.type == "E":
            self.mode = MODE_CYCLE[(MODE_CYCLE.index(self.mode) + 1) % len(MODE_CYCLE)]
        elif event.type == "A":
            self.orientation = "VERTICAL" if self.orientation == "HORIZONTAL" else "HORIZONTAL"
        elif event.type == "Q":
            self.straight_sides = SIDES_CYCLE[(SIDES_CYCLE.index(self.straight_sides) + 1) % len(SIDES_CYCLE)]
        elif event.type == "W":
            self.ends = ENDS_CYCLE[(ENDS_CYCLE.index(self.ends) + 1) % len(ENDS_CYCLE)]
        elif event.type == "B":
            self.balance = next((b for b in BALANCE_JUMPS if b > self.balance + 1e-9), BALANCE_JUMPS[0])
        elif event.type == "LEFTMOUSE" and event.alt:      # a seed face, with Shift a guide face
            found = self._face_under(context, event)
            if found is not None:
                self._click_face(context, found[0], found[1], event.shift)
            return {"RUNNING_MODAL"}
        elif event.type == "LEFTMOUSE":      # a corner, a side; anywhere else nothing happens (no confirm)
            corner = self._hover_corner(context, event)
            if corner is not None:
                self._click_corner(context, *corner)
                return {"RUNNING_MODAL"}
            self._update_side_hover(context, event)
            hover = getattr(self, "_side_hover", None)
            if hover is not None:
                self._click_side(context, *hover)
                self._update_side_hover(context, event)
            return {"RUNNING_MODAL"}
        elif event.type == "S":
            self.split_at_seams = not self.split_at_seams
        elif event.type == "D":
            self.active_fit = FIT_CYCLE[(FIT_CYCLE.index(self.active_fit) + 1) % len(FIT_CYCLE)]
        elif event.type == "Z":
            self.offset_axis = OFFSET_CYCLE[(OFFSET_CYCLE.index(self.offset_axis) + 1) % len(OFFSET_CYCLE)]
        elif event.type == "X":
            self.mark_seams = not self.mark_seams
        elif event.type == "R":
            self.offset_seed += 1
        elif event.type == "G":
            self.shape_align = ALIGN_CYCLE[(ALIGN_CYCLE.index(self.shape_align) + 1) % len(ALIGN_CYCLE)]
        elif event.type in {"C", "V"}:    # pick cuts (a ring's break among them) or lines to straighten
            self._start_picking(context, event, event.type == "V")
            return {"RUNNING_MODAL"}
        elif event.type == "F":           # the preview is weld-aware: only the HUD and the confirm change
            self.merge_doubles = not self.merge_doubles
            return {"RUNNING_MODAL"}
        elif event.type in {"RET", "NUMPAD_ENTER", "SPACE"}:
            if uv_stripe_balance_core.pending():         # the confirmed UVs are the cold ones
                self._refine(context, float("inf"))
            result = self._result
            if self.merge_doubles and result.doubles:
                # restore the snapshot first (by index, before the topology changes), then merge and lay out
                self._restore_snapshot(update=False)
                result = self._lay_out(context, merge=True)
                for me, *_rest in self._snapshot:
                    bmesh.update_edit_mesh(me)
            self._finish(context)
            return self._report_result(result)
        elif event.type in {"RIGHTMOUSE", "ESC"}:
            for name, value in self._cancel.items():
                setattr(self, name, value)
            self._restore_snapshot()
            self._finish(context)
            return {"CANCELLED"}
        elif event.type in PASS_KEYS:
            return {"PASS_THROUGH"}
        else:
            return {"RUNNING_MODAL"}
        self._relayout(context)
        return {"RUNNING_MODAL"}

    def _add_handlers(self, context):
        """The two draw handlers: the lines in the scene (POST_VIEW, tested against its depth) and the HUD and
        help on top (POST_PIXEL); both tracked for the purge on reload."""
        self._handle_view = safe_handler_add(
            bpy.types.SpaceView3D, self._draw_view_callback, (context,), "WINDOW", "POST_VIEW")
        _ACTIVE_HANDLES.add(self._handle_view)
        self._handle = safe_handler_add(
            bpy.types.SpaceView3D, self._draw_callback, (context,), "WINDOW", "POST_PIXEL", tick=True)
        _ACTIVE_HANDLES.add(self._handle)

    def _remove_handlers(self):
        for name in ("_handle_view", "_handle"):
            h = getattr(self, name, None)
            if h is None:
                continue
            _ACTIVE_HANDLES.discard(h)
            try:
                safe_handler_remove(h, bpy.types.SpaceView3D, "WINDOW")
            except (ValueError, RuntimeError):
                pass
            setattr(self, name, None)

    def _finish(self, context):
        self._remove_handlers()
        self._drop_timer(context)
        try:
            context.workspace.status_text_set(None)
        except AttributeError:
            pass
        if getattr(context, "area", None):
            context.area.tag_redraw()
        # Finished operator instances stay alive in the redo stack: drop every mesh reference.
        self._snapshot = []
        self._hud = None
        self._help = None
        self._picking = False
        self._align_picking = False
        self._alt = False
        self._hover = None
        self._side_hover = None
        self._pick_cache = {}
        self._picked_lines = ()

    def _status_text(self):
        """The status bar: one short line, the pick modes' own while C or V is on."""
        if getattr(self, "_picking", False):
            return "Picking cut loops · LMB loop: cut / mend, break a ring · Alt + LMB: single edge · C / Esc: stop"
        if getattr(self, "_align_picking", False):
            return "Picking lines to straighten · LMB loop: straighten / free · Alt + LMB: single edge · V / Esc: stop"
        result = getattr(self, "_result", None)
        if result is not None and result.help:
            return "LMB boundary vertex: corner · C: cut an island · Ctrl + Wheel: balance · Enter: confirm · Esc: cancel"
        return "LMB side: straight/free · Ctrl + Wheel: balance · Tab: more · Enter: confirm · Esc: cancel"

    def _draw_view_callback(self, context):
        """POST_VIEW: the world-space lines, dimmed where geometry hides them (``draw.edges_world``)."""
        result = getattr(self, "_result", None)
        cutting = getattr(self, "_picking", False)
        picking = cutting or getattr(self, "_align_picking", False)
        hover = getattr(self, "_hover", None) if picking else None
        side_hover = None if picking else getattr(self, "_side_hover", None)
        try:
            sides = dict(result.sides) if result is not None else {}
            straight = [p for side in sides.values() if side.straight for p in side.points]
            free = [p for side in sides.values() if not side.straight for p in side.points]
            outline = list(result.outline) if result is not None else []          # the closed pieces
            stretched = list(result.stretched) if result is not None else []
            tears = list(result.tears) if result is not None else []   # the picked breaks and cuts are among them
            skipped = list(result.skipped_tears) if result is not None else []
            aligned = list(result.align_lines) if result is not None else []
            cut = list(result.cut_lines) if result is not None else []
            straightened = list(result.straight_lines) if result is not None else []
            hovered = list(hover[2]) if hover is not None else []
            # what a click on the hover does: a new cut drawn as the cuts are, a new straight line as those are, a
            # pick taken back in the highlight colour
            hover_role = Role.ACTIVE_LINE
            if hover is not None:
                hover_role = Role.CLOSEST_LINE if hover[3] else Role.PREVIEW_LINE if cutting else Role.ACTIVE_LINE
            if side_hover is not None:
                obj, piece, name = side_hover
                record = sides.get((obj.name, piece, name))
                hovered = list(record.points) if record is not None else []
            # bottom to top: the free and the straight sides of the open pieces and the closed pieces' outlines,
            # the stretched faces' edges, the tears (Auto's in the error colour, the cuts made by hand in the
            # preview colour over them), the straightened lines, the skipped tears and the picked align edges in
            # use, the loop, edge or side under the cursor. The tears lie under the sides (so a piece's end shows
            # straight or free where the strip is torn), over them while picking cuts.
            outlines = ((free, Role.LINE), (straight, Role.PREVIEW_LINE), (outline, Role.PREVIEW_LINE))
            torn = ((tears, Role.ERROR_LINE), (cut, Role.PREVIEW_LINE))
            layers = (*outlines, (stretched, Role.LOCKED_LINE), *torn) if cutting else \
                (*torn, *outlines, (stretched, Role.LOCKED_LINE))
            helps = list(result.help) if result is not None else []
            outline_help = [p for item in helps for p in item.outline]
            seeds = list(result.seed_lines) if result is not None else []
            guides = list(result.guide_lines) if result is not None else []
            layers = (*layers, (straightened, Role.ACTIVE_LINE), (skipped, Role.CLOSEST_LINE),
                      (aligned, Role.CLOSEST_LINE), (outline_help, Role.ERROR_LINE),
                      (guides, Role.GHOST_EDGE), (seeds, Role.HANDLE), (hovered, hover_role))
            for points, role in layers:
                if points:
                    draw.edges_world(points, role=role, context=context)
            for points, role in (([p for item in helps for p in item.candidates.values()], Role.POINT),
                                 ([p for item in helps for p in item.picked.values()], Role.ACTIVE_POINT),
                                 (list(result.guide_points) if result is not None else [], Role.LOCKED_POINT),
                                 (list(result.seed_points) if result is not None else [], Role.ACTIVE_POINT)):
                if points:
                    draw.points_world(points, role=role, context=context)
        except Exception:   # a draw handler must never raise: it would repeat every frame
            pass

    def _draw_callback(self, context):
        """POST_PIXEL: the HUD and the help."""
        if context.region_data is None:
            return
        result = getattr(self, "_result", None)
        hud = getattr(self, "_hud", None)
        helpo = getattr(self, "_help", None)
        last_event = getattr(self, "_last_event", None)
        if helpo is not None:
            helpo.draw(context, last_event)
        if hud is not None:
            done = result.done if result is not None else 0
            stretched = result.stretched_faces if result is not None else 0
            count = f"{done} strip(s), {stretched} stretched face(s)" if stretched else f"{done} strip(s)"
            pick = None
            if getattr(self, "_align_picking", False):
                pick = "Picking lines to straighten · Alt: single edge · V to stop"
            elif getattr(self, "_picking", False):
                pick = "Picking cut loops · Alt: single edge · C to stop"
            hud.set_header(pick, count)
            notes = []
            if result is not None:
                if result.refining:
                    notes.append(("Refining...", False))
                for k, item in enumerate(result.help):
                    notes.append((f"Island {k + 1} is no strip: {item.prompt()}", True))
                for message in dict.fromkeys(result.split):
                    notes.append((message[0].upper() + message[1:], False))
            hud.set_notes(*notes)
            hud.draw(context, last_event)
