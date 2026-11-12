"""UV Stripe bridge: write the straight strip layout of ``utils/uv_stripe_core`` onto a mesh.

The core lays each ``Strip`` out in UV space without bpy. This module reads what
In Place needs from the mesh before any UV changes (``uv_context``), then places
the strips and writes their UVs onto the strip faces' corners (``apply_stripes``).
UV Stripe, Smart Inset and Smart Edge Slide share the rest here, so they cannot
drift apart: the option items (``LAYOUT_ITEMS``, ``ORIENTATION_ITEMS``), the
pieces one built strip becomes (``prepare_strip``) and the seams that match the
laid-out pieces (``match_piece_seams``).
"""

from dataclasses import dataclass

from bmesh.types import BMFace

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
    "Keep the active face where it is in UV: the strip takes its place, size and direction from the active "
    "face's current UVs",
)
ACTIVE_FALLBACK = "UV Stripe: Active needs an active face in the selection with UVs; laid out In Place"
LAYOUT_ITEMS = [
    ("TRUE", "No Stretch",
     "Keep every row at its true length; the ends of the strip and of its pieces keep their real slant"),
    ("STRAIGHT", "Rectangles",
     "Stand every cross edge vertical so each quad becomes a rectangle; stretches where the strip bends"),
    ("EVEN", "Even Rows", "Lay each row out by its own length, scaled to the strip's mean length"),
]
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
    active: tuple[int, int] | None = None,
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

    ``mode`` "ACTIVE" with ``active`` (strip index, face id): the active face's old
    UVs, read before anything is written, give one scale and one quarter turn
    (``uv_stripe_core.active_anchor``); its strip keeps that face on its old corners
    and every other strip takes the same scale and turn, centred on its own old UV
    centre (``place_active``); ``vertical`` does not apply. Without a usable anchor
    (no ``active``, no UV layer, a face with no size in UV) it lays out "IN_PLACE".
    Returns whether the strips were anchored on the active face.

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
    placed: list[dict | None] = [None] * len(strips)
    anchor = None
    if mode == "ACTIVE":
        anchor = _active_anchor(bm, strips, faces, maps, active)
        mode = "IN_PLACE" if anchor is None else mode
    fit = []
    for i, (strip, ctx) in enumerate(zip(strips, contexts)):
        if anchor is not None:
            if i == active[0]:
                placed[i] = core.place_active(maps[i], anchor)
                continue
            center = _uv_center(bm, [faces[fid] for fid in strip.faces])
            if center is not None:
                placed[i] = core.place_active(maps[i], anchor, (lengths[i] / 2.0, strip.height / 2.0), center)
                continue
            fit.append(i)
        elif mode == "IN_PLACE" and ctx is not None:
            placed[i] = core.place_in_place(maps[i], lengths[i], strip.height, ctx.center, ctx.density, vertical)
        else:
            fit.append(i)
    stacked = core.place_fit([maps[i] for i in fit], [strips[i].height for i in fit], [lengths[i] for i in fit],
                             groups=[fit_groups[i] for i in fit], vertical=vertical)
    for i, uv in zip(fit, stacked):
        placed[i] = uv

    layer = bm.loops.layers.uv.active
    if layer is None:
        layer = bm.loops.layers.uv.new("UVMap")
    for strip, uv in zip(strips, placed):
        for fid in strip.faces:
            for lp in faces[fid].loops:
                co = uv.get((fid, lp.vert.index))
                if co is not None:
                    lp[layer].uv = co
    return anchor is not None


def _uv_center(bm, faces: list[BMFace]) -> tuple[float, float] | None:
    """The centre of the active UV layer's bounding box over ``faces``; None without a layer."""
    layer = bm.loops.layers.uv.active
    if layer is None or not faces:
        return None
    uvs = [lp[layer].uv for f in faces for lp in f.loops]
    us = [uv.x for uv in uvs]
    vs = [uv.y for uv in uvs]
    return (min(us) + max(us)) / 2.0, (min(vs) + max(vs)) / 2.0


def _active_anchor(bm, strips, faces, maps, active):
    """The active face's ``uv_stripe_core.active_anchor`` from its old UVs; None when it has none to give."""
    layer = bm.loops.layers.uv.active
    if active is None or layer is None:
        return None
    index, fid = active
    loops = list(faces[fid].loops)
    new = [maps[index][(fid, lp.vert.index)] for lp in loops]
    old = [tuple(lp[layer].uv) for lp in loops]
    try:
        return core.active_anchor(new, old)
    except ValueError:
        return None


def prepare_strip(
    strip: core.Strip, faces: dict[int, BMFace], layout: str, split_angle: float | None, extra_cuts=()
) -> tuple[list[tuple[core.Strip, dict[int, BMFace]]], str | None]:
    """The final pieces of one built strip, with their faces by id, and why a requested tear was not made.

    ``split_angle`` (None: no split) tears the strip at its bends, and ``extra_cuts``
    (rung indices) at those rungs too (``uv_stripe_select_core.split_strip``): when
    there are cuts but the strip cannot be torn there, it stays whole and the reason
    is returned for a warning. ``layout`` ("TRUE", "STRAIGHT" or "EVEN", see
    ``LAYOUT_ITEMS``) is set on every piece; "STRAIGHT" goes through
    ``uv_stripe_core.straighten``, which keeps "EVEN" for a piece where it would fold
    a face. Raises ValueError as ``uv_stripe_core.stripe_uvs`` does.
    """
    strip.layout = "TRUE" if layout == "TRUE" else "EVEN"
    if split_angle is None and not extra_cuts:
        pieces, reason = [strip], None
    else:
        pieces, reason = select_core.split_strip(strip, split_angle, extra_cuts)
    for piece in pieces:
        if layout == "STRAIGHT":
            core.straighten(piece)
        else:
            core.stripe_uvs(piece)
    return [(piece, {fid: faces[fid] for fid in piece.faces}) for piece in pieces], reason


def match_piece_seams(pieces) -> None:
    """Make the seams of the laid-out (strip, faces by id) pieces say where their UV islands end.

    Marked: every edge with one face in its piece, and a closed strip's cut rung (the
    seam ``uv_stripe_core.stripe_uvs`` opens it at) when that rung is an edge of its
    faces. Cleared: every other edge with both its faces in one piece, so a seam the
    strip was laid across goes. Edges outside the pieces are not touched.
    """
    pieces = list(pieces)
    marked, cleared = set(), set()
    for strip, faces in pieces:
        inside = set(faces.values())
        edges = {e for f in inside for e in f.edges}
        cut = set()
        if strip.closed and strip.rungs:
            k = strip.seam if strip.seam is not None else core.sharpest_rung(strip)
            ni, fi = strip.rungs[k]
            cut = {strip.near[ni % len(strip.near)], strip.far[fi % len(strip.far)]}
        for e in edges:
            inner = sum(g in inside for g in e.link_faces)
            if inner == 1 or (cut and {v.index for v in e.verts} == cut):
                marked.add(e)
            elif inner >= 2:
                cleared.add(e)
    for e in cleared - marked:
        e.seam = False
    for e in marked:
        e.seam = True
