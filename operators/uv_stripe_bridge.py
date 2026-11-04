"""UV Stripe bridge: write the straight strip layout of ``utils/uv_stripe_core`` onto a mesh.

The core lays each ``Strip`` out in UV space without bpy. This module reads what
In Place needs from the mesh before any UV changes (``uv_context``), then places
the strips and writes their UVs onto the strip faces' corners (``apply_stripes``).
"""

from dataclasses import dataclass

from bmesh.types import BMFace

from ..utils import uv_stripe_core as core


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


def apply_stripes(
    bm,
    strips: list[core.Strip],
    faces: dict[int, BMFace],
    mode: str,
    contexts: list[StripeContext | None] | None = None,
) -> None:
    """Lay every strip out and write its UVs onto its faces' corners in the active UV layer.

    The mesh gets a UV layer when it has none. ``faces`` maps the strips' face ids
    to their faces; their vertex ids are ``BMVert.index``. ``contexts`` holds each
    strip's own ``uv_context``; None means none for any strip.

    ``mode`` "FIT" spans each strip across U 0-1, V in proportion, and stacks the
    strips upward in V. "IN_PLACE" scales each strip by its own context's density
    and centres it on its own context's centre; a strip without a context falls
    back to "FIT", stacked with the other such strips.

    Raises ``ValueError`` before writing anything when ``contexts`` does not hold
    one entry per strip, or when the core cannot lay a strip out.
    """
    if contexts is None:
        contexts = [None] * len(strips)
    if len(contexts) != len(strips):
        raise ValueError(f"{len(contexts)} UV contexts for {len(strips)} strips")
    maps = [core.stripe_uvs(s) for s in strips]
    lengths = [core.strip_length(s) for s in strips]
    placed: list[dict | None] = [None] * len(strips)
    fit = []
    for i, (strip, ctx) in enumerate(zip(strips, contexts)):
        if mode == "IN_PLACE" and ctx is not None:
            placed[i] = core.place_in_place(maps[i], lengths[i], strip.height, ctx.center, ctx.density)
        else:
            fit.append(i)
    stacked = core.place_fit([maps[i] for i in fit], [strips[i].height for i in fit], [lengths[i] for i in fit])
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
