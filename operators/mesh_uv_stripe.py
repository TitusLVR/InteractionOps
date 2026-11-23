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

Invoked, the operator lays the strips out at once with the last-used options. With
``interactive`` (bound through ``IOPS_OT_Mesh_UV_Stripe_Interactive``, "UV Stripe
(Interactive)") it is modal instead: every option has a key, and every change restores
the UVs and seams the selected faces had and lays them out again, so the UV editor
follows live; the viewport shows the four sides of every piece, straight or free,
and LMB on a side toggles that side of that piece (``side_picks``). Enter / Space
keep the result (one undo step), Esc / RMB put the snapshot back. C picks cut edges
among the cross edges of the laid-out strips: on a closed ring with no break yet the
click breaks it there (``cup_breaks``), and the ring is then laid out as one open
strip from there; elsewhere the click removes that break, marks or unmarks a cut by
hand (``manual_cuts``) or skips or restores one of Auto's tears (``skipped_cuts``).
For the pieces unfolded at their real shape, G cycles what each one is aligned to
(``shape_align``) and V picks the edge a piece is aligned to (``align_edges``).
"""

import json
from dataclasses import dataclass, field

import bmesh
import bpy
from bpy.props import BoolProperty, EnumProperty, FloatProperty, IntProperty, StringProperty
from bpy_extras import view3d_utils
from mathutils import Vector

from ..ui.draw import Role, safe_handler_add, safe_handler_remove
from ..ui.draw import primitives as draw
from ..ui.hud import HelpOverlay, HUDItem, HUDOverlay, HUDParam, HUDSection, ItemState, capture_event
from ..utils import picking, uv_stripe_auto_core, uv_stripe_core, uv_stripe_select_core
from . import uv_stripe_bridge

EPS = 1e-6
SIDES_CYCLE = [item[0] for item in uv_stripe_bridge.STRAIGHT_SIDES_ITEMS]
SIDES_NAMES = {item[0]: item[1] for item in uv_stripe_bridge.STRAIGHT_SIDES_ITEMS}
ENDS_CYCLE = [item[0] for item in uv_stripe_bridge.ENDS_ITEMS]
ENDS_NAMES = {item[0]: item[1] for item in uv_stripe_bridge.ENDS_ITEMS}
BALANCE_CYCLE = [item[0] for item in uv_stripe_bridge.BALANCE_ITEMS]
BALANCE_NAMES = {item[0]: item[1] for item in uv_stripe_bridge.BALANCE_ITEMS}
SIDE_PICK_RADIUS = 30.0     # px (times the interface scale): how near a side the cursor must be to pick it
MODE_CYCLE = ["FIT", "IN_PLACE", "ACTIVE"]
MODE_NAMES = {"FIT": "Fit 0–1", "IN_PLACE": "In Place", "ACTIVE": "Active"}
FIT_CYCLE = [item[0] for item in uv_stripe_bridge.ACTIVE_FIT_ITEMS]
FIT_NAMES = {item[0]: item[1] for item in uv_stripe_bridge.ACTIVE_FIT_ITEMS}
OFFSET_CYCLE = [item[0] for item in uv_stripe_bridge.OFFSET_ITEMS]
OFFSET_NAMES = {item[0]: item[1] for item in uv_stripe_bridge.OFFSET_ITEMS}
LIMIT_STEP, LIMIT_FINE_STEP = 0.05, 0.01
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


def _inner_cuts(island, cuts):
    """The edges of ``cuts`` that lie between two faces of the island."""
    uses = {}
    for face in island.values():
        for k, a in enumerate(face):
            e = tuple(sorted((a, face[(k + 1) % len(face)])))
            uses[e] = uses.get(e, 0) + 1
    return {e for e in cuts if uses.get(e) == 2}


# the picked edges, by object name and edge index
EDGE_PROPS = ("cup_breaks", "manual_cuts", "skipped_cuts", "align_edges")


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
    unfolded: int = 0             # pieces laid out at their real shape (no long side straight): Align applies


@dataclass
class _Side:
    """One side of a laid-out piece: whether it is laid out straight, its edges (indices, in order), the
    piece's face beside each edge (index) and the world-space segment end points, two per edge."""

    straight: bool
    edges: list
    faces: list
    points: list


def _collect_stretched(result, bm, pieces, matrix):
    """Count the laid-out faces their final UVs stretch (``uv_stripe_bridge.stretched_faces``) and keep the
    world-space segments of their edges, each edge once."""
    faces = [f for _strip, piece_faces in pieces for f in piece_faces.values()]
    stretched = uv_stripe_bridge.stretched_faces(bm, faces, matrix)
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
        if asked is not None:
            want = asked(strip)
            unfolded = shape.rails == "NONE"
            shape = uv_stripe_auto_core.Shape(shape.near, shape.far, want.end0 and not unfolded,
                                              want.end1 and not unfolded)
        result.unfolded += shape.rails == "NONE"
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
            ring_cut = bool(cut) and {v.index for v in e.verts} == cut
            between = len(set(linked)) > 1 and n == min(linked)     # each tear once
            if ring_cut or between:
                result.tears.extend(ends)


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
        default="SLANTED",
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
    balance: EnumProperty(
        name="Balance",
        description="How a strip several faces wide spreads the stretch it cannot avoid",
        items=uv_stripe_bridge.BALANCE_ITEMS,
        default="EVEN_TEXEL",
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
    # The sides clicked straight or free in the interactive mode, as JSON {object name: [[face index, edge
    # index, straight], ...]}: each sets the side holding that edge of the piece holding that face, later over
    # earlier. Kept for redo like the edges above; a new run starts from Straight Sides and Ends.
    side_picks: StringProperty(
        name="Picked Sides",
        description="The sides of the pieces clicked straight or free in the interactive mode",
        default="",
        options={"HIDDEN", "SKIP_SAVE"},
    )
    # Invoked with it the operator starts the interactive mode; without it invoke lays the strips out at once.
    interactive: BoolProperty(
        name="Interactive",
        description="Start the interactive mode, where every option has a key and the UVs follow live",
        default=False,
        options={"HIDDEN", "SKIP_SAVE"},
    )
    # Whether the interactive mode's HUD lists every option or only the main ones; remembered as last used.
    show_options: BoolProperty(
        name="More Options",
        description="List every option in the interactive mode's HUD, not only the main ones",
        default=False,
        options={"HIDDEN"},
    )

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
                manual=frozenset(), skipped=frozenset(), cross=None, bends=None, align_edges=(), side_picks=()):
        """The laid-out pieces of one island as ([(strip, faces by id)], warning); raises ValueError.

        The whole island is built and torn where Auto tears it and at the seams inside it
        that are its rungs. An island that is no strip as a whole, one with a seam inside it
        that is no rung, or one that cannot be torn at its seams, is first split at those
        seams and each part built on its own; when a part is then no strip, the island
        that could not be torn stays whole.
        An island that is a closed ring with a rung among ``breaks`` (vertex-id pairs, the
        picked breaks) is opened there as one piece instead, its seams and bends not
        tearing it (``uv_stripe_bridge.prepare_strip``). ``rings`` (a list) gets the rung
        edges of an island that is a closed ring: the edges a break can be picked on.
        The rungs among ``manual`` (vertex-id pairs, cut by hand) tear the strip, or each
        part, also on an opened ring; Auto's tears at rungs among ``skipped`` are not
        made. ``cross`` (a set) gets the rung edges of the laid-out strip or parts, the
        edges a cut can be picked on, and ``bends`` (a list) the edges Auto tore them at.
        Every piece is laid out by Straight Sides, Ends, Stretch Limit and Balance, the
        ``side_picks`` ((face id, vertex-id pair, straight)) on top, and aligned by
        ``shape_align``, "Picked Edge" on the first of ``align_edges`` (vertex-id pairs)
        that is an edge of it.
        """
        inner = _inner_cuts(island, seam_cuts)
        whole = None
        whole_marks = ((), ())

        def lay(strip, cuts=(), break_edge=None):
            """``prepare_strip`` with the hand-made cuts; (its result, (rung edges, bend tear edges))."""
            torn = []
            laid = uv_stripe_bridge.prepare_strip(
                strip, picked, self.straight_sides, self.ends, cuts, break_edge=break_edge,
                manual_cuts=uv_stripe_select_core.rungs_at(strip, manual),
                skip_cuts=uv_stripe_select_core.rungs_at(strip, skipped), bend_tears=torn,
                align=self.shape_align, align_edges=align_edges, stretch_limit=self.stretch_limit,
                balance=self.balance, side_picks=side_picks)
            return laid, ([uv_stripe_select_core.rung_edge(strip, k) for k in range(len(strip.rungs))], torn)

        def done(laid, marks):
            if cross is not None:
                cross.update(marks[0])
            if bends is not None:
                bends.extend(marks[1])
            return laid

        try:
            strip = _build(island, verts)
        except ValueError:
            strip = None
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
                    return done(whole, whole_marks)
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
            return done(whole, whole_marks)
        if not out:
            raise ValueError(failed)
        if failed:
            reasons.append(f"a part between the seams is skipped: {failed}")
        return done((out, (reasons[0] if reasons else None)), part_marks)

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
        stored_sides = _parse_sides(getattr(self, "side_picks", ""))
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
            strips, contexts, pieces, rings, cross, bends = [], [], [], [], set(), []
            active_face = bm.faces.active if self.mode == "ACTIVE" else None
            for island in uv_stripe_select_core.face_islands(ids):
                try:
                    laid, warning = self._pieces(island, verts, picked, seam_cuts, breaks, rings,
                                                 manual, skipped, cross, bends, align_edges, side_picks)
                except ValueError as exc:
                    result.skipped += 1
                    result.first_reason = result.first_reason or str(exc)
                    continue
                if warning:
                    result.warnings.append(f"UV Stripe: not split ({warning})")
                for strip, faces in laid:
                    piece_faces = list(faces.values())
                    strips.append(strip)
                    pieces.append((strip, faces))
                    contexts.append(_world_context(uv_stripe_bridge.uv_context(bm, piece_faces), piece_faces, matrix))
            edge_of = {tuple(sorted(v.index for v in e.verts)): e for f in picked.values() for e in f.edges}
            if rings:
                result.rings[obj.name] = {edge_of[key].index: n for n, ring in enumerate(rings)
                                          for key in ring if key in edge_of}
            result.cross[obj.name] = {edge_of[key].index for key in cross if key in edge_of}
            result.bend_tears[obj.name] = {edge_of[key].index for key in bends if key in edge_of}
            result.seam_tears[obj.name] = {edge_of[key].index for key in seam_cuts if key in edge_of}
            for key in sorted(skipped & cross):
                e = edge_of.get(key)
                if e is not None:
                    result.skipped_tears.extend((matrix @ e.verts[0].co, matrix @ e.verts[1].co))
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
            _collect_sides(result, obj, pieces, edge_of, matrix, lambda strip: uv_stripe_auto_core.picked_shape(
                strip, uv_stripe_auto_core.default_shape(strip, self.straight_sides, self.ends), side_picks)[0])
            _collect_stretched(result, bm, pieces, matrix)
            result.done += len(strips)
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
        if not result.done:
            self.report({"WARNING"}, f"UV Stripe: nothing laid out ({result.first_reason})")
            return {"CANCELLED"}
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

    def _relayout(self, context):
        """Restore the snapshot and lay out again with the current options."""
        self._restore_snapshot(update=False)
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
        """Per object name, the edge indices the current pick mode can pick: every cross edge of a laid-out strip
        (``_Result.cross``) for the cut edges, every edge of a laid-out piece (``_Result.align_pieces``) for the
        align edge."""
        result = getattr(self, "_result", None)
        if result is None:
            return {}
        return result.align_pieces if getattr(self, "_align_picking", False) else result.cross

    def _hover_break(self, context, event):
        """(object, edge index) of the pickable edge under the cursor, or None.

        Pickable (``_pickable``): in the last layout, a cross edge of a laid-out strip,
        open or closed, or while picking the align edge any edge of a laid-out piece; one
        of the edges of the face under the cursor, the one nearest to it on screen.
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
        edges = [e for e in bm.faces[face_index].edges if e.index in pickable]
        if not edges:
            return None
        k, _distance = picking.closest_edge_screen(context, edges, obj.matrix_world, coord)
        return None if k is None else (obj, edges[k].index)

    def _update_hover(self, context, event):
        """Keep the hovered cross edge, and its world-space end points for the preview."""
        found = self._hover_break(context, event)
        self._hover = None
        if found is not None:
            obj, index = found
            bm = bmesh.from_edit_mesh(obj.data)
            bm.edges.ensure_lookup_table()
            edge = bm.edges[index]
            self._hover = (obj, index, [obj.matrix_world @ v.co for v in edge.verts])

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
        if edge_index not in result.cross.get(name, ()):
            return None
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

    def _click_align(self, context, obj, edge_index):
        """Store edge ``edge_index`` of ``obj`` as the align edge of its piece, re-lay out; picking goes on.

        The stored edges of the same piece (of either piece, for an edge the strip is torn
        at) are replaced and Align becomes Picked Edge ("set"); the stored edge itself is
        removed again ("remove"). An edge of no laid-out piece changes nothing (None).
        Returns what was done.
        """
        result = getattr(self, "_result", None) or _Result()
        pieces = result.align_pieces.get(obj.name, {})
        own = pieces.get(edge_index)
        if not own:
            return None
        data = _parse_breaks(getattr(self, "align_edges", ""))
        indices = data.get(obj.name, [])
        if edge_index in indices:
            action, indices = "remove", [i for i in indices if i != edge_index]
        else:
            action, indices = "set", [i for i in indices if not pieces.get(i, set()) & own] + [edge_index]
            self.shape_align = "PICKED"
        data[obj.name] = indices
        self.align_edges = _dump_edges(data)
        self._relayout(context)
        return action

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

    def _align_edge_count(self):
        return sum(len(indices) for indices in _parse_breaks(getattr(self, "align_edges", "")).values())

    def _manual_cut_count(self):
        return sum(len(indices) for indices in _parse_breaks(getattr(self, "manual_cuts", "")).values())

    def _start_picking(self, context, event, align):
        """Enter the cut edge pick mode, or with ``align`` the align edge pick mode; the two never run at once."""
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
        """The modal's answer to ``event`` while picking cut edges (C) or the align edge (V): LMB changes the
        hovered edge, the mode's own key, Esc or RMB stop picking, the other mode's key switches to it."""
        if event.type == "MOUSEMOVE":
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
                click = self._click_align if align else self._click_cut
                click(context, self._hover[0], self._hover[1])
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
        for name in (*EDGE_PROPS, "side_picks"):
            self._cancel[name] = getattr(self, name, "")
        self._picking = False
        self._align_picking = False
        self._hover = None
        self._side_hover = None
        self._pick_cache = {}
        self._relayout(context)
        if not self._result.done:
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
        """Without ``interactive``, ``execute`` at once; with it, the interactive mode."""
        if not self.interactive:
            return self.execute(context)
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
        # Always: Straight Sides, Ends, Stretch Limit and More Options. Only when they apply: Align, Manual Cuts,
        # Doubled Vertices. The rows after More Options only while it is on (Tab). Every key works either way.
        self._hud.add_param(HUDParam("Straight Sides (E)", lambda: SIDES_NAMES[self.straight_sides], "enum"))
        self._hud.add_param(HUDParam("Ends (A)", lambda: ENDS_NAMES[self.ends], "enum",
                                     active_getter=lambda: self.straight_sides != "NONE"))
        self._hud.add_param(HUDParam("Stretch Limit (Wheel)", lambda: self.stretch_limit, "float", fmt="{:.2f}"))
        self._hud.add_param(HUDParam("Align (G)", lambda: ALIGN_NAMES[self.shape_align], "enum",
                                     visible_getter=self._align_applies))
        self._hud.add_param(HUDParam("Manual Cuts", self._manual_cut_count, "int",
                                     visible_getter=lambda: self._manual_cut_count() > 0))
        self._hud.add_param(HUDParam("Doubled Vertices", lambda: getattr(self, "_result", _Result()).doubles, "int",
                                     visible_getter=lambda: getattr(self, "_result", _Result()).doubles > 0))
        self._hud.add_param(HUDParam("More Options (Tab)", lambda: self.show_options, "bool"))

        def more(own=None):
            return lambda: self.show_options and (own is None or own())

        self._hud.add_param(HUDParam("Balance (B)", lambda: BALANCE_NAMES[self.balance], "enum",
                                     visible_getter=more()))
        self._hud.add_param(HUDParam("Mode (Q)", lambda: MODE_NAMES[self.mode], "enum", visible_getter=more()))
        self._hud.add_param(HUDParam("Orientation (W)", lambda: orientation_names[self.orientation], "enum",
                                     visible_getter=more()))
        self._hud.add_param(HUDParam("Fit to Active (D)", lambda: FIT_NAMES[self.active_fit], "enum",
                                     active_getter=lambda: self.mode == "ACTIVE", visible_getter=more()))
        self._hud.add_param(HUDParam("Split at Seams (S)", lambda: self.split_at_seams, "bool",
                                     visible_getter=more()))
        self._hud.add_param(HUDParam("Mark Seams (X)", lambda: self.mark_seams, "bool", visible_getter=more()))
        self._hud.add_param(HUDParam("Random Offset (Z)", lambda: OFFSET_NAMES[self.offset_axis], "enum",
                                     visible_getter=more()))
        self._hud.add_param(HUDParam("Offset Limit (Shift + Wheel)", lambda: self.offset_limit, "float",
                                     fmt="{:.2f}", active_getter=lambda: self.offset_axis != "NONE",
                                     visible_getter=more()))
        self._hud.add_param(HUDParam("Offset Seed (R)", lambda: self.offset_seed, "int",
                                     active_getter=lambda: self.offset_axis != "NONE", visible_getter=more()))
        self._hud.add_param(HUDParam("Merge Doubles (F)", lambda: self.merge_doubles, "bool", visible_getter=more()))

        def item(label, key):
            return HUDItem(label, key, ItemState.ON, default_state=ItemState.OFF, always_show=True)

        # Short and hidden until H: only what the HUD does not show already
        self._help = HelpOverlay("uv_stripe")
        self._help.add_section(HUDSection("UV Stripe", [
            item("Side straight / free", "LMB on a side"),
            item("Pick cut edges, break a ring", "C"),
            item("Pick the align edge", "V"),
            item("Confirm", "Enter / Space"),
            item("Cancel", "Esc / RMB"),
        ]))
        self._help.start_collapsed()
        self._help.bind_region(region)

    def _align_applies(self):
        """Whether Align (G, V) matters now: Straight Sides is None, or a piece is laid out at its real shape."""
        result = getattr(self, "_result", None)
        return self.straight_sides == "NONE" or bool(result is not None and result.unfolded)

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

        if getattr(self, "_picking", False) or getattr(self, "_align_picking", False):
            # picking cut edges or the align edge: LMB takes the edge before the confirm
            return self._pick_event(context, event)

        wheel = event.type in {"WHEELUPMOUSE", "WHEELDOWNMOUSE"}
        if wheel and event.shift and self.offset_axis != "NONE":
            step = LIMIT_FINE_STEP if event.ctrl else LIMIT_STEP
            step = step if event.type == "WHEELUPMOUSE" else -step
            self.offset_limit = max(round(self.offset_limit + step, 6), 0.0)
            self._relayout(context)
            return {"RUNNING_MODAL"}
        if wheel and not event.shift:
            step = STRETCH_FINE_STEP if event.ctrl else STRETCH_STEP
            step = step if event.type == "WHEELUPMOUSE" else -step
            self.stretch_limit = min(max(round(self.stretch_limit + step, 6), 1.0), 3.0)
            self._relayout(context)
            return {"RUNNING_MODAL"}
        if event.type == "MOUSEMOVE":
            self._update_side_hover(context, event)
            return {"RUNNING_MODAL"}
        if event.type in NAVIGATION or event.type.startswith("NDOF"):
            return {"PASS_THROUGH"}

        if event.value != "PRESS" and not (event.type == "LEFTMOUSE" and event.value == "DOUBLE_CLICK"):
            return {"RUNNING_MODAL"}
        if event.type == "Q":
            self.mode = MODE_CYCLE[(MODE_CYCLE.index(self.mode) + 1) % len(MODE_CYCLE)]
        elif event.type == "W":
            self.orientation = "VERTICAL" if self.orientation == "HORIZONTAL" else "HORIZONTAL"
        elif event.type == "E":
            self.straight_sides = SIDES_CYCLE[(SIDES_CYCLE.index(self.straight_sides) + 1) % len(SIDES_CYCLE)]
        elif event.type == "A":
            self.ends = ENDS_CYCLE[(ENDS_CYCLE.index(self.ends) + 1) % len(ENDS_CYCLE)]
        elif event.type == "B":
            self.balance = BALANCE_CYCLE[(BALANCE_CYCLE.index(self.balance) + 1) % len(BALANCE_CYCLE)]
        elif event.type == "LEFTMOUSE":      # a side toggles; anywhere else nothing happens (no confirm)
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
        elif event.type in {"C", "V"}:    # pick cut edges (a ring's break among them) or the align edge
            self._start_picking(context, event, event.type == "V")
            return {"RUNNING_MODAL"}
        elif event.type == "F":           # the preview is weld-aware: only the HUD and the confirm change
            self.merge_doubles = not self.merge_doubles
            return {"RUNNING_MODAL"}
        elif event.type == "TAB":         # only the HUD changes
            self.show_options = not self.show_options
            self._show_status(context)
            return {"RUNNING_MODAL"}
        elif event.type in {"RET", "NUMPAD_ENTER", "SPACE"}:
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
        self._hover = None
        self._side_hover = None
        self._pick_cache = {}

    def _status_text(self):
        """The status bar: one short line, the pick modes' own while C or V is on."""
        if getattr(self, "_picking", False):
            return "Picking cut edges · LMB cross edge: cut / uncut, break a ring · C / Esc: stop"
        if getattr(self, "_align_picking", False):
            return "Picking the align edge · LMB edge: align the piece to it / remove · V / Esc: stop"
        return "LMB side: straight/free · Tab: more · Enter: confirm · Esc: cancel"

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
            hovered = list(hover[2]) if hover is not None else []
            if side_hover is not None:
                obj, piece, name = side_hover
                record = sides.get((obj.name, piece, name))
                hovered = list(record.points) if record is not None else []
            # bottom to top: the free and the straight sides of the open pieces and the closed pieces' outlines,
            # the stretched faces' edges, the tears (each opened ring's cut and the manual cuts), the skipped tears
            # and the picked align edges in use, the side or edge under the cursor. The tears lie under the sides
            # (so a piece's end shows straight or free where the strip is torn), over them while picking cuts.
            outlines = ((free, Role.LINE), (straight, Role.PREVIEW_LINE), (outline, Role.PREVIEW_LINE))
            torn = ((tears, Role.ERROR_LINE),)
            layers = (*outlines, (stretched, Role.LOCKED_LINE), *torn) if cutting else \
                (*torn, *outlines, (stretched, Role.LOCKED_LINE))
            layers = (*layers, (skipped, Role.CLOSEST_LINE), (aligned, Role.CLOSEST_LINE), (hovered, Role.ACTIVE_LINE))
            for points, role in layers:
                if points:
                    draw.edges_world(points, role=role, context=context)
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
                pick = "Picking the align edge · V to stop"
            elif getattr(self, "_picking", False):
                pick = "Picking cut edges · C to stop"
            hud.set_header(pick, count)
            hud.draw(context, last_event)


class IOPS_OT_Mesh_UV_Stripe_Interactive(bpy.types.Operator):
    """Start UV Stripe in its interactive mode, where every option has a key and the UVs follow live"""

    bl_idname = "iops.mesh_uv_stripe_interactive"
    bl_label = "UV Stripe (Interactive)"
    is_bindable = True

    @classmethod
    def poll(cls, context):
        return IOPS_OT_Mesh_UV_Stripe.poll(context)

    def invoke(self, context, _event):
        return self.execute(context)

    def execute(self, _context):
        """Invoke ``iops.mesh_uv_stripe`` with ``interactive``: the options are its last-used ones, and what the
        interactive mode confirms becomes the last-used options of the instant call."""
        result = bpy.ops.iops.mesh_uv_stripe("INVOKE_DEFAULT", interactive=True)
        return {"CANCELLED"} if "CANCELLED" in result else {"FINISHED"}
