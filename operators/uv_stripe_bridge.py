"""UV Stripe bridge: write the straight strip layout of ``utils/uv_stripe_core`` onto a mesh.

The core lays each ``Strip`` out in UV space without bpy. This module reads what
In Place needs from the mesh before any UV changes (``uv_context``), then places
the strips and writes their UVs onto the strip faces' corners (``apply_stripes``).
UV Stripe, Inset and Edge Slide share the rest here, so they cannot
drift apart: the option items (``STRAIGHT_SIDES_ITEMS``, ``ENDS_ITEMS``,
``ORIENTATION_ITEMS``), the pieces one built strip becomes
(``prepare_strip``) and the seams that match the laid-out pieces
(``match_piece_seams``).
"""

from collections.abc import Iterable
from dataclasses import dataclass

from bmesh.types import BMFace

from ..utils import uv_stripe_auto_core as auto_core
from ..utils import uv_stripe_balance_core as balance_core
from ..utils import uv_stripe_core as core
from ..utils import uv_stripe_select_core as select_core


@dataclass
class StripeContext:
    """Where In Place puts the strips: the centre of the old UVs and the neighbours' texel density."""

    center: tuple[float, float]
    density: float


def uv_context(bm, faces: list[BMFace]) -> StripeContext | None:
    """The old UV placement of ``faces``, to be read before any UV is written.

    ``center`` is the centre of the active UV layer's bounding box over ``faces``.
    ``density`` is UV length per unit of 3D length: the sum of the UV edge lengths
    over the sum of the 3D edge lengths, taken over the edges of every face that
    shares an edge with ``faces`` but is not among them. None without a UV layer,
    without faces, or when that density is 0 (no such neighbours, or no UVs on them).
    """
    layer = bm.loops.layers.uv.active
    if layer is None or not faces:
        return None
    uvs = [lp[layer].uv for f in faces for lp in f.loops]
    us = [uv.x for uv in uvs]
    vs = [uv.y for uv in uvs]
    center = ((min(us) + max(us)) / 2.0, (min(vs) + max(vs)) / 2.0)

    inside = set(faces)
    neighbours = dict.fromkeys(g for f in faces for e in f.edges for g in e.link_faces if g not in inside)
    uv_length = length = 0.0
    for g in neighbours:
        for lp in g.loops:
            uv_length += (lp.link_loop_next[layer].uv - lp[layer].uv).length
            length += lp.edge.calc_length()
    if uv_length <= 0.0 or length <= 0.0:
        return None
    return StripeContext(center, uv_length / length)


MODE_ITEMS = [
    ("FIT", "Fit 0–1", "Stretch the strip across U 0–1, V in proportion"),
    ("IN_PLACE", "In Place", "Keep the old UV location and the neighbours' texel density"),
]
ACTIVE_MODE_ITEM = (
    "ACTIVE", "Active",
    "Lay the strip holding the active face out In Place, and fit every other piece to its UV bounding box without "
    "stretching it",
)
# Appended after Active, so the stored values of the other items keep their numbers.
STACK_MODE_ITEM = (
    "STACK", "Stack",
    "Lay every piece out as Fit 0–1 does, then center them all on the middle of 0–1, one on top of the other",
)
ACTIVE_FIT_ITEMS = [
    ("BOTH", "Width and Height", "Fit the piece inside the reference strip's bounding box, keeping its proportions"),
    ("WIDTH", "Width", "Match the reference's width, along the strip in either Orientation; the height is scaled by "
     "the same factor"),
    ("HEIGHT", "Height", "Match the reference's height, across the strip in either Orientation; the width is scaled "
     "by the same factor"),
]
ACTIVE_FALLBACK = "UV Stripe: no active face to fit to; laid out In Place"
OFFSET_ITEMS = [
    ("NONE", "None", "Leave the pieces where the mode put them"),
    ("ALONG", "Along Strip", "Shift each piece along the strip's length by a random amount; follows Orientation"),
    ("ACROSS", "Across Strip", "Shift each piece across the strip by a random amount"),
    ("BOTH", "Both", "Shift each piece along and across the strip by random amounts"),
]


def offset_axis(axis: str, vertical: bool) -> str:
    """The UV axis ("NONE", "HORIZONTAL", "VERTICAL" or "BOTH") of a Random Offset item: along the strip is
    U when the strip runs horizontally, V when it runs vertically; across is the other."""
    if axis == "ALONG":
        return "VERTICAL" if vertical else "HORIZONTAL"
    if axis == "ACROSS":
        return "HORIZONTAL" if vertical else "VERTICAL"
    return axis


STRAIGHT_SIDES_ITEMS = [
    ("BOTH", "Both",
     "Both long sides of every piece, and every line of edges running along it, straight and horizontal"),
    ("LONGER", "Longer Side", "Only the longer long side of every piece straight; the rest follows the faces"),
    ("SHORTER", "Shorter Side", "Only the shorter long side of every piece straight; the rest follows the faces"),
    ("NONE", "None", "Nothing straightened: every piece unfolded at its real shape, turned by Align"),
]
ENDS_ITEMS = [
    ("AUTO", "Upright Where Cheap",
     "On a strip several faces wide both ends stand upright while that stretches no face beyond Stretch Limit; "
     "beyond it they may keep their slant instead. A strip one face wide keeps its real slant"),
    ("SLANTED", "Slanted", "Both ends of every piece keep their real slant"),
    ("BOTH", "Both", "Both ends of every piece stand upright"),
    ("LONGER", "Longer End", "The end with the longer cross edges stands upright, the other keeps its slant"),
    ("SHORTER", "Shorter End", "The end with the shorter cross edges stands upright, the other keeps its slant"),
]
BALANCE_DESCRIPTION = (
    "How a balanced piece spreads the stretch it cannot avoid: 0 the least stretch, the texel density differing "
    "a little between faces; 1 every face near its real size (even texel density), some stretch left where its "
    "rows must differ in length; in between, the layout slides from one to the other")
ORIENTATION_ITEMS = [
    ("HORIZONTAL", "Horizontal", "The strip runs along U"),
    ("VERTICAL", "Vertical", "The strip runs along V: the horizontal layout turned 90 degrees counter-clockwise"),
]


def apply_stripes(
    bm,
    strips: list[core.Strip],
    faces: dict[int, BMFace],
    mode: str,
    contexts: list[StripeContext | None] | None = None,
    fit_groups: list[int] | None = None,
    vertical: bool = False,
    active: int | None = None,
    active_fit: str = "BOTH",
    offset: tuple[str, float, int] = ("NONE", 0.0, 0),
) -> bool:
    """Lay every strip out and write its UVs onto its faces' corners in the active UV layer.

    The mesh gets a UV layer when it has none. ``faces`` maps the strips' face ids
    to their faces; their vertex ids are ``BMVert.index``. ``contexts`` holds each
    strip's own ``uv_context``; None means none for any strip.

    ``mode`` "FIT" spans each strip across U 0-1, V in proportion, and stacks the
    strips upward in V. "IN_PLACE" scales each strip by its own context's density
    and centres it on its own context's centre; a strip without a context falls
    back to "FIT", stacked with the other such strips. ``fit_groups`` holds a group
    id per strip: the "FIT" strips of one group share one scale (1 / the group's
    longest u extent), so they keep one texel density; None gives every strip its
    own. ``vertical`` turns every strip 90 degrees counter-clockwise: Fit spans V
    0-1 and stacks to the right, In Place turns each strip about its own centre.

    ``mode`` "ACTIVE" with ``active`` (the index of the strip holding the active
    face): every strip is placed as "IN_PLACE" would place it; then every other strip
    is fitted to the active strip's UV bounding box by one scale factor for both axes,
    so it is not stretched (``uv_stripe_core.fit_to_reference`` with ``active_fit``:
    "HEIGHT" matches the size across the strip, "WIDTH" along it, in either Orientation,
    ``uv_stripe_core.fit_axis``; "BOTH" fits it inside the box). Without
    ``active``, or without a UV layer to place the active strip by, it lays out
    "IN_PLACE". Returns whether the strips were fitted to an active strip.

    ``mode`` "STACK" places every strip as "FIT" does (the same scale per group), then
    moves each one, at that size, so its UV bounding box is centred on (0.5, 0.5)
    (``uv_stripe_core.stack_shifts``): the strips lie one on top of the other.

    ``offset`` (axis, limit, seed) then shifts every strip but the active one by a
    random amount (``uv_stripe_core.random_offsets``), the same for the same seed.

    Raises ``ValueError`` before writing anything when ``contexts`` does not hold
    one entry per strip, or when the core cannot lay a strip out.
    """
    if contexts is None:
        contexts = [None] * len(strips)
    if len(contexts) != len(strips):
        raise ValueError(f"{len(contexts)} UV contexts for {len(strips)} strips")
    if fit_groups is None:
        fit_groups = list(range(len(strips)))
    if len(fit_groups) != len(strips):
        raise ValueError(f"{len(fit_groups)} fit groups for {len(strips)} strips")
    maps = [core.stripe_uvs(s) for s in strips]
    lengths = [core.strip_extent(s) for s in strips]
    heights = [core.strip_v_extent(s) for s in strips]
    return apply_maps(bm, maps, lengths, heights, faces, mode, contexts, fit_groups, vertical, active, active_fit,
                      offset)


def apply_maps(
    bm,
    maps: list[dict],
    lengths: list[float],
    heights: list[float],
    faces: dict[int, BMFace],
    mode: str,
    contexts: list[StripeContext | None] | None = None,
    fit_groups: list[int] | None = None,
    vertical: bool = False,
    active: int | None = None,
    active_fit: str = "BOTH",
    offset: tuple[str, float, int] = ("NONE", 0.0, 0),
) -> bool:
    """Place laid-out pieces and write their UVs onto their faces' corners in the active UV layer.

    ``maps`` holds each piece's {(face id, vertex id): (u, v)} in world units, laid out
    from (0, 0) over ``lengths`` (u extent) and ``heights`` (v extent); ``faces`` maps
    every face id of the maps to its face. Placement, the vertical turn, the random
    offset, the return value and the other parameters are those of ``apply_stripes``,
    with "strip" read as "piece"; Active fits a piece by one factor, never stretching it. Raises ``ValueError`` before writing anything when
    ``contexts`` or ``fit_groups`` does not hold one entry per piece.
    """
    if contexts is None:
        contexts = [None] * len(maps)
    if len(contexts) != len(maps):
        raise ValueError(f"{len(contexts)} UV contexts for {len(maps)} pieces")
    if fit_groups is None:
        fit_groups = list(range(len(maps)))
    if len(fit_groups) != len(maps):
        raise ValueError(f"{len(fit_groups)} fit groups for {len(maps)} pieces")
    placed: list[dict | None] = [None] * len(maps)
    fitted = mode == "ACTIVE" and active is not None and bm.loops.layers.uv.active is not None
    stack = mode == "STACK"
    if stack:
        mode = "FIT"
    if mode == "ACTIVE":
        mode = "IN_PLACE"
    fit = []
    for i, ctx in enumerate(contexts):
        if mode == "IN_PLACE" and ctx is not None:
            placed[i] = core.place_in_place(maps[i], lengths[i], heights[i], ctx.center, ctx.density, vertical)
        else:
            fit.append(i)
    stacked = core.place_fit([maps[i] for i in fit], [heights[i] for i in fit], [lengths[i] for i in fit],
                             groups=[fit_groups[i] for i in fit], vertical=vertical)
    for i, uv in zip(fit, stacked):
        placed[i] = uv
    if fitted:
        reference = core.bbox(placed[active])
        fit = core.fit_axis(active_fit, vertical)       # Height across the strip, Width along it
        placed = [uv if i == active else core.fit_to_reference(uv, reference, fit)
                  for i, uv in enumerate(placed)]
    if stack:
        shifts = core.stack_shifts([core.bbox(uv) for uv in placed])
        placed = [core.shifted(uv, d) for uv, d in zip(placed, shifts)]
    axis, limit, seed = offset
    if axis != "NONE":
        shifts = core.random_offsets(len(placed), axis, limit, seed, active if fitted else None)
        placed = [core.shifted(uv, d) for uv, d in zip(placed, shifts)]

    layer = bm.loops.layers.uv.active
    if layer is None:
        layer = bm.loops.layers.uv.new("UVMap")
    for uv in placed:
        # a cut-open band names the vertices of its cut by stand-in ids on one side (``core.real_vertex``); a face
        # holds a vertex once, so its corner is still found
        uv = {(fid, core.real_vertex(vid)): co for (fid, vid), co in uv.items()}
        for fid in dict.fromkeys(fid for fid, _vid in uv):
            for lp in faces[fid].loops:
                co = uv.get((fid, lp.vert.index))
                if co is not None:
                    lp[layer].uv = co
    return fitted


def stretched_faces(bm, faces: Iterable[BMFace], matrix, tolerance: float = core.STRETCH_TOLERANCE) -> list[BMFace]:
    """The ``faces`` whose active-layer UVs stretch them beyond ``tolerance`` (``uv_stripe_core.face_stretch``).

    Each face is measured against its world-space shape (``matrix @ v.co``, as the
    layout is built), so an object's non-uniform scale is not stretch. Empty without
    a UV layer.
    """
    layer = bm.loops.layers.uv.active
    if layer is None:
        return []
    out = []
    for f in faces:
        points = [tuple(matrix @ lp.vert.co) for lp in f.loops]
        uvs = [tuple(lp[layer].uv) for lp in f.loops]
        if core.face_stretch(points, uvs) > tolerance:
            out.append(f)
    return out


@dataclass(frozen=True)
class ShapeRules:
    """How every piece is laid out: what must be straight (``straight_sides``, ``ends``; ``STRAIGHT_SIDES_ITEMS``,
    ``ENDS_ITEMS``), the ``stretch_limit`` that relaxes it, the ``balance`` of a balanced piece (0 to 1,
    ``uv_stripe_balance_core.balance_value``), the sides picked by hand (``picks``: (face id, sorted vertex-id pair, straight), see
    ``uv_stripe_auto_core.picked_shape``) and what a piece unfolded at its real shape runs along (``align``,
    ``align_edges``: vertex-id pairs, ``uv_stripe_core.lay_piece``), the lines picked straight (``lines``:
    (axis, vertex ids), ``uv_stripe_core.Strip.lines``) and the values set for some pieces alone (``overrides``:
    (kind, value, face ids), kind "SIDES" a Straight Sides value or "ENDS" an Ends value, for every piece holding
    one of those faces, later over earlier; relaxed by ``stretch_limit`` like the values set for all)."""

    straight_sides: str = "BOTH"
    ends: str = "SLANTED"
    stretch_limit: float = auto_core.DEFAULT_STRETCH_LIMIT
    balance: float = core.DEFAULT_BALANCE
    picks: tuple = ()
    align: str = "AUTO"
    align_edges: tuple = ()
    lines: tuple = ()
    overrides: tuple = ()

    def values(self, piece: core.Strip) -> tuple[str, str]:
        """(Straight Sides, Ends) for ``piece``: the last of ``overrides`` of each kind holding a face of it, else
        the values set for all."""
        sides, ends = self.straight_sides, self.ends
        for kind, value, faces in self.overrides:
            if not faces.isdisjoint(piece.faces):
                if kind == "SIDES":
                    sides = value
                elif kind == "ENDS":
                    ends = value
        return sides, ends

    def shape(self, piece: core.Strip):
        """What must be straight on ``piece`` by these rules: the settings (``values``), the picked sides on top
        (``uv_stripe_auto_core.picked_shape``)."""
        sides, ends = self.values(piece)
        return auto_core.picked_shape(piece, auto_core.default_shape(piece, sides, ends), self.picks)[0]

    def lines_in(self, piece: core.Strip) -> tuple:
        """The picked lines as ``piece`` holds them: a line picked on a piece (with the id of a face of it, a
        third item) only on the piece holding that face; each cut down to the piece's own vertices, kept when two
        or more are left."""
        used = {v for face in piece.faces.values() for v in face}
        out = []
        for line in self.lines:
            axis, vertices = line[0], line[1]
            owner = line[2] if len(line) > 2 else None
            if owner is not None and owner not in piece.faces:
                continue
            kept = frozenset(vertices) & used
            if len(kept) >= 2:
                out.append((axis, kept))
        return tuple(out)

    def lay(self, piece: core.Strip) -> None:
        """Lay ``piece`` out by these rules (``uv_stripe_auto_core.lay_shaped``), the picked lines it holds kept
        straight. Raises ValueError as it does."""
        piece.lines = self.lines_in(piece)
        sides, ends = self.values(piece)
        auto_core.lay_shaped(piece, sides, ends, self.stretch_limit, self.balance, self.picks, self.align,
                             self.align_edges)


def _auto_split(strip: core.Strip, cuts, skip_cuts, bend_tears, rules: ShapeRules) -> tuple[list[core.Strip], str | None]:
    """``strip`` torn at ``cuts`` (rung indices) and at its ``uv_stripe_auto_core.auto_cuts`` (but those among
    ``skip_cuts``), each piece laid out by ``rules``. When it cannot be torn there it stays one piece and the
    reason is returned; ``bend_tears`` (a list) gets the vertex-id pairs of the auto cuts it was torn at.
    Raises ValueError as ``uv_stripe_core.stripe_uvs`` does."""
    strip.layout = "TRUE"
    strip.align, strip.align_edge = rules.align, None
    strip.lines = rules.lines_in(strip)
    cuts = sorted(set(cuts))
    # free ends (Slanted, and Upright Where Cheap on a strip one face wide: Auto never tears a wide one)
    layouts = ("TRUE",) if rules.values(strip)[1] in ("SLANTED", "AUTO") else auto_core.STRAIGHT_LAYOUTS
    if not cuts and auto_core.fits_whole(strip, rules.shape(strip), rules.stretch_limit, rules.balance):
        kept = []          # one layout the piece will be laid out with already keeps it within the limit
    else:
        kept = auto_core.auto_cuts(strip, cuts, skip_cuts, layouts, rules.stretch_limit)
    pieces, reason = [strip], None
    if cuts or kept:
        pieces, reason = select_core.split_strip(strip, None, sorted(set(cuts) | set(kept)))
        if reason is None and bend_tears is not None:
            bend_tears.extend(select_core.rung_edge(strip, k) for k in kept)
    for piece in pieces:
        rules.lay(piece)
    return pieces, reason


def _opened_ring(strip: core.Strip, break_edge, cut_edges=(), skip_edges=(), bend_tears=None,
                 rules: ShapeRules = ShapeRules()) -> tuple[list[core.Strip], str | None]:
    """``strip`` (closed) opened at the rung ``break_edge`` and laid out as ``_auto_split`` does: torn at those
    of ``cut_edges`` (vertex-id pairs) that are its rungs and at its own auto cuts, the rungs among
    ``skip_edges`` (vertex-id pairs) left out of them and ``bend_tears`` getting the auto cuts made. When it
    cannot be torn there it stays one piece and the reason is returned. Raises ValueError when ``break_edge``
    is no rung of it, or as ``uv_stripe_select_core.open_ring`` and ``uv_stripe_core.stripe_uvs`` do."""
    at = select_core.rungs_at(strip, [tuple(sorted(break_edge))])
    if not at:
        raise ValueError("the picked edge is not a cross edge of the ring")
    opened = select_core.open_ring(strip, at[0])
    return _auto_split(opened, select_core.rungs_at(opened, cut_edges), select_core.rungs_at(opened, skip_edges),
                       bend_tears, rules)


def prepare_strip(
    strip: core.Strip, faces: dict[int, BMFace], straight_sides: str = "BOTH", ends: str = "SLANTED",
    extra_cuts=(), break_edge: tuple[int, int] | None = None, manual_cuts=(), skip_cuts=(), bend_tears=None,
    align: str = "AUTO", align_edges=(), stretch_limit: float = auto_core.DEFAULT_STRETCH_LIMIT,
    balance: float = core.DEFAULT_BALANCE, side_picks=(), lines=(), overrides=(),
) -> tuple[list[tuple[core.Strip, dict[int, BMFace]]], str | None]:
    """The final pieces of one built strip, with their faces by id, and why a requested tear was not made.

    The strip is torn at ``extra_cuts`` and ``manual_cuts`` (rung indices: seams and
    cuts marked by hand) and at its ``uv_stripe_auto_core.auto_cuts``, the bend cuts
    among ``skip_cuts`` left out; ``bend_tears`` (a list) gets the vertex-id pairs of
    the auto cuts made. When there are cuts but the strip cannot be torn there, it
    stays whole and the reason is returned for a warning. Every open piece is then
    laid out by what must be straight on it (``ShapeRules.lay``): ``straight_sides``
    and ``ends`` (``STRAIGHT_SIDES_ITEMS``, ``ENDS_ITEMS``), the sides picked on it
    by hand on top (``side_picks``: (face id, sorted vertex-id pair, straight), in
    order), relaxed while its worst face stretches beyond ``stretch_limit`` unless a
    long side was picked, ``balance`` for a balanced piece; a closed piece
    keeps "EVEN". Raises ValueError as ``uv_stripe_core.stripe_uvs`` does.

    ``break_edge`` (a vertex-id pair) is a ring's picked break: when ``strip`` is
    closed and that pair is one of its rungs, the ring is opened there
    (``uv_stripe_select_core.open_ring``) and goes through the same steps as an open
    strip, torn at ``manual_cuts`` and its own auto cuts but not at ``extra_cuts``.
    When the ring cannot be opened there it is laid out as without ``break_edge`` and
    the reason is returned. On an open strip ``break_edge`` is ignored.

    ``align`` (``uv_stripe_core.Strip.align``) tells each piece unfolded at its real
    shape what to run along; each piece aligns on its own, "PICKED" on the first of
    ``align_edges`` (vertex-id pairs) that is an edge of its faces, "AUTO" when none is.

    ``lines`` ((axis, vertex ids[, the id of a face of the piece it was picked on]), ``uv_stripe_core.Strip.lines``)
    are the lines picked straight (``ShapeRules.lines_in``): every piece
    keeps those of its vertices on one shared v ("ALONG") or u ("ACROSS") through every shape Stretch Limit
    relaxes it to.

    ``overrides`` ((kind, value, face ids), ``ShapeRules.overrides``) set Straight Sides or Ends for the pieces
    holding those faces alone.
    """
    rules = ShapeRules(straight_sides, ends, stretch_limit, balance, tuple(side_picks), align, tuple(align_edges),
                       tuple((line[0], frozenset(line[1]), *line[2:]) for line in lines),
                       tuple((kind, value, frozenset(faces)) for kind, value, faces in overrides))
    broken = None
    if break_edge is not None and strip.closed:
        cut_edges = [select_core.rung_edge(strip, k) for k in manual_cuts]
        skip_edges = [select_core.rung_edge(strip, k) for k in skip_cuts]
        try:
            opened, reason = _opened_ring(strip, break_edge, cut_edges, skip_edges, bend_tears, rules)
        except ValueError as exc:
            broken = f"the ring cannot be opened at the picked edge: {exc}"
        else:
            return [(piece, {fid: faces[fid] for fid in piece.faces}) for piece in opened], reason
    pieces, reason = _auto_split(strip, set(extra_cuts) | set(manual_cuts), skip_cuts, bend_tears, rules)
    return [(piece, {fid: faces[fid] for fid in piece.faces}) for piece in pieces], broken or reason


def match_piece_seams(pieces) -> None:
    """Make the seams of the laid-out (strip, faces by id) pieces say where their UV islands end.

    Marked: every edge with one face in its piece, a closed strip's cut rung (the
    seam ``uv_stripe_core.stripe_uvs`` opens it at) and an opened ring's
    ``break_edge``, when that rung is an edge of its faces, and the line a closed band
    several faces wide is cut open along (``Strip.cut_path``). Cleared: every other edge
    with both its faces in one piece, so a seam the strip was laid across goes. Edges
    outside the pieces are not touched.
    """
    pieces = list(pieces)
    marked, cleared = set(), set()
    for strip, faces in pieces:
        inside = set(faces.values())
        edges = {e for f in inside for e in f.edges}
        cut = set()
        if strip.break_edge is not None:
            cut = set(strip.break_edge)
        elif strip.closed and strip.rungs:
            k = strip.seam if strip.seam is not None else core.sharpest_rung(strip)
            ni, fi = strip.rungs[k]
            cut = {strip.near[ni % len(strip.near)], strip.far[fi % len(strip.far)]}
        along = set(strip.cut_path)
        for e in edges:
            inner = sum(g in inside for g in e.link_faces)
            key = tuple(sorted(v.index for v in e.verts))
            if inner == 1 or (cut and set(key) == cut) or key in along:
                marked.add(e)
            elif inner >= 2:
                cleared.add(e)
    for e in cleared - marked:
        e.seam = False
    for e in marked:
        e.seam = True


SETTINGS_VERSION = 1    # 1: Ends gained "Upright Where Cheap" ("AUTO") as the default (2026-11-24)


def migrate_settings(props) -> bool:
    """Bring UV Stripe properties stored before ``SETTINGS_VERSION`` up to date, once: properties with no
    ``settings_version`` set were stored under the old default Ends = Slanted, which becomes "AUTO" (the new
    default); every other value stays. ``props`` is an operator's properties (or the last-used ones,
    ``operator_properties_last``); the version is set on them, so a later explicit Slanted sticks. Returns
    whether anything was changed."""
    try:
        if props.is_property_set("settings_version"):
            return False
    except (AttributeError, TypeError):
        return False
    changed = getattr(props, "ends", None) == "SLANTED"
    if changed:
        props.ends = "AUTO"
    props.settings_version = SETTINGS_VERSION
    return changed


@dataclass
class StripeSettings:
    """UV Stripe's settings: one set for UV Stripe, Inset and Edge Slide.

    ``from_operator`` reads a UV Stripe operator (or anything with its properties);
    ``from_last`` reads UV Stripe's last-used properties, its defaults when it never ran.
    """

    mode: str
    active_fit: str
    orientation: str
    straight_sides: str
    ends: str
    stretch_limit: float
    balance: float
    split_at_seams: bool
    mark_seams: bool
    offset_axis: str
    offset_limit: float
    offset_seed: int
    merge_doubles: bool

    @classmethod
    def from_operator(cls, op) -> "StripeSettings":
        """The settings ``op`` holds; a Balance held as one of the old names ("EVEN_TEXEL", "LEAST_STRETCH")
        reads as its slider value, anything unreadable as the default."""
        values = {name: getattr(op, name) for name in cls.__dataclass_fields__}
        try:
            values["balance"] = balance_core.balance_value(values["balance"])
        except ValueError:
            values["balance"] = core.DEFAULT_BALANCE
        return cls(**values)

    @classmethod
    def from_last(cls, context) -> "StripeSettings":
        """UV Stripe's last-used settings, stored ones older than ``SETTINGS_VERSION`` migrated first
        (``migrate_settings``)."""
        props = context.window_manager.operator_properties_last("iops.mesh_uv_stripe")
        migrate_settings(props)
        return cls.from_operator(props)

    def shape_kwargs(self) -> dict:
        """The keywords of ``prepare_strip`` these settings give (Inset and Edge Slide: no picked sides)."""
        return {"straight_sides": self.straight_sides, "ends": self.ends, "stretch_limit": self.stretch_limit,
                "balance": self.balance}


def finish_stripes(bm, pieces, contexts, groups, settings: StripeSettings) -> bool:
    """Place the prepared (strip, faces by id) pieces and set their seams, as ``settings`` say; the one
    placement step of UV Stripe, Inset and Edge Slide. Every piece is its own strip, also the parts of an island
    cut into strips: Fit stacks them like any strips.

    ``contexts`` holds each piece's ``uv_context`` and ``groups`` its Fit group. In
    Active mode the reference is the piece holding the mesh's active face (In Place
    without one; the caller decides whether to say so). The placement is
    ``apply_stripes`` (mode, Fit to Active, Orientation, Random Offset along or across
    the strip), the seams ``match_piece_seams`` with Mark Seams. Returns whether the
    pieces were fitted to an active one. Raises ValueError as ``apply_stripes`` does.
    """
    faces = {}
    for _strip, piece_faces in pieces:
        faces.update(piece_faces)
    active_face = bm.faces.active if settings.mode == "ACTIVE" else None
    active = next((i for i, (_s, piece_faces) in enumerate(pieces)
                   if active_face is not None and piece_faces.get(active_face.index) is active_face), None)
    vertical = settings.orientation == "VERTICAL"
    fitted = apply_stripes(
        bm, [strip for strip, _faces in pieces], faces, settings.mode, contexts, fit_groups=groups,
        vertical=vertical, active=active, active_fit=settings.active_fit,
        offset=(offset_axis(settings.offset_axis, vertical), settings.offset_limit, settings.offset_seed))
    if settings.mark_seams:
        match_piece_seams(pieces)
    return fitted
