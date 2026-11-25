"""Stateless drawing primitives bound to the theme.

Sizes/widths auto-derive from the role's state:
- POINT/LINE/TEXT → "default"
- CLOSEST_* → "closest"
- ACTIVE_* → "active"
- LOCKED_* → "locked"
- PREVIEW_* → "preview"

Callers wrap calls in `draw_scope(...)` to control blend/depth state.
"""
from __future__ import annotations
import math
from collections.abc import Sequence

import gpu
import numpy as np
from gpu_extras.batch import batch_for_shader
from mathutils import Matrix, Vector

from ...utils import depth_bias
from . import shaders
from .state import draw_scope
from .theme import Role, Theme, get_theme


def _resolve_theme(theme: Theme | None, context) -> Theme:
    return theme if theme is not None else get_theme(context)


def _resolve_color(role, color, theme):
    if color is not None:
        return color
    if role is None:
        raise ValueError("primitives draw call requires role= or color=")
    return theme.color_for(role)


def line(p1, p2, *, role: Role | None = None,
         color: tuple[float, float, float, float] | None = None,
         width: str | None = None,
         theme: Theme | None = None, context=None) -> None:
    polyline([p1, p2], role=role, color=color, width=width,
             theme=theme, context=context)


def polyline(coords: Sequence, *, role: Role | None = None,
             color: tuple[float, float, float, float] | None = None,
             width: str | None = None,
             theme: Theme | None = None, context=None) -> None:
    th = _resolve_theme(theme, context)
    shader = shaders.polyline_uniform_color()
    batch = batch_for_shader(shader, "LINE_STRIP", {"pos": list(coords)})
    if width is not None:
        w = th.width(width)
    elif role is not None:
        w = th.line_width_for(role)
    else:
        w = th.width("default")
    c = _resolve_color(role, color, th)
    shader.bind()
    shader.uniform_float("color", c)
    shader.uniform_float("lineWidth", w)
    shader.uniform_float("viewportSize", gpu.state.viewport_get()[2:])
    batch.draw(shader)


def edges_3d(coord_pairs: Sequence, *, role: Role | None = None,
             color: tuple[float, float, float, float] | None = None,
             width: str | None = None,
             theme: Theme | None = None, context=None) -> None:
    """Disjoint line segments: coord_pairs is a flat list [a, b, c, d, ...]
    where (a,b), (c,d), ... are segments."""
    th = _resolve_theme(theme, context)
    shader = shaders.polyline_uniform_color()
    batch = batch_for_shader(shader, "LINES", {"pos": list(coord_pairs)})
    if width is not None:
        w = th.width(width)
    elif role is not None:
        w = th.line_width_for(role)
    else:
        w = th.width("default")
    c = _resolve_color(role, color, th)
    shader.bind()
    shader.uniform_float("color", c)
    shader.uniform_float("lineWidth", w)
    shader.uniform_float("viewportSize", gpu.state.viewport_get()[2:])
    batch.draw(shader)


def _gpu_state():
    """(blend, depth test, depth mask) now set, or None where this Blender has no getters."""
    try:
        return (gpu.state.blend_get(), gpu.state.depth_test_get(),
                gpu.state.depth_mask_get())
    except AttributeError:
        return None


def _draw_occluded(th: Theme, draw_pass, occluded_min: float = 0.0) -> None:
    """Run `draw_pass(alpha_factor)` once per occlusion pass of the theme's
    Backface Dimming (utils/depth_bias.py; hidden parts at least
    `occluded_min` opaque), under the depth-biased projection, ALPHA blend
    and no depth writes; puts back the blend / depth state the caller had."""
    passes = depth_bias.occlusion_passes(
        depth_bias.occluded_opacity(th.backface_dimming, floor=occluded_min))
    biased = Matrix(depth_bias.biased_projection(gpu.matrix.get_projection_matrix()))
    saved = _gpu_state()
    try:
        with gpu.matrix.push_pop_projection():
            gpu.matrix.load_projection_matrix(biased)
            with draw_scope(blend="ALPHA", depth=passes[0][0], depth_mask=False):
                for depth, factor in passes:
                    gpu.state.depth_test_set(depth)
                    draw_pass(factor)
    finally:
        if saved is not None:
            gpu.state.blend_set(saved[0])
            gpu.state.depth_test_set(saved[1])
            gpu.state.depth_mask_set(saved[2])


def edges_world(coord_pairs: Sequence, *, role: Role | None = None,
                color: tuple[float, float, float, float] | None = None,
                width: str | float | None = None,
                theme: Theme | None = None, context=None,
                occluded_min: float = 0.0) -> None:
    """Disjoint world-space segments (flat [a, b, c, d, ...] as in
    `edges_3d`) for a POST_VIEW handler, tested against the scene's
    depth: the parts in front are drawn in the colour as is, the parts
    geometry hides with the alpha times 1 - the theme's
    `backface_dimming`.

    The points are pulled toward the viewer by a projection-matrix depth
    bias (utils/depth_bias.py) so lines lying on mesh edges do not
    z-fight with their faces; both passes use the same biased depth, so
    each fragment is drawn exactly once. With `backface_dimming` 0 this
    is one draw with no depth test. Sets ALPHA blend and no depth writes
    itself (inside `draw_scope`) and then puts back the blend / depth
    state the caller had, so it can sit inside the caller's own scope.
    `width` is a theme width token or a width in pixels. `occluded_min`
    keeps the hidden parts at least that opaque whatever the theme says,
    for drawing that must stay readable through geometry."""
    pairs = list(coord_pairs)
    if len(pairs) < 2:
        return
    th = _resolve_theme(theme, context)
    c = _resolve_color(role, color, th)
    if isinstance(width, (int, float)):
        w = float(width)
    elif width is not None:
        w = th.width(width)
    elif role is not None:
        w = th.line_width_for(role)
    else:
        w = th.width("default")
    shader = shaders.polyline_uniform_color()
    batch = batch_for_shader(shader, "LINES", {"pos": pairs})

    def draw_pass(factor):
        shader.bind()
        shader.uniform_float("color", depth_bias.scale_alpha(c, factor))
        shader.uniform_float("lineWidth", w)
        shader.uniform_float("viewportSize", gpu.state.viewport_get()[2:])
        batch.draw(shader)

    _draw_occluded(th, draw_pass, occluded_min)


def points_world(coords: Sequence, *, role: Role | None = None,
                 color: tuple[float, float, float, float] | None = None,
                 size: str | float | int | None = None,
                 ring_role: Role | None = None,
                 theme: Theme | None = None, context=None) -> None:
    """World-space points (`points` discs) for a POST_VIEW handler, with
    the same depth bias and passes as `edges_world`: hidden points get
    their fill and ring alpha times 1 - the theme's `backface_dimming`."""
    coords = list(coords)
    if not coords:
        return
    th = _resolve_theme(theme, context)
    fill = _resolve_color(role, color, th)
    ring = th.color_for(ring_role if ring_role is not None else Role.POINT_OUTLINE)
    px = _point_px(th, role, size)
    shader = shaders.point_disc()
    batch = batch_for_shader(shader, "POINTS", {"pos": coords})

    def draw_pass(factor):
        shader.bind()
        shader.uniform_float("color", depth_bias.scale_alpha(fill, factor))
        shader.uniform_float("ringColor", depth_bias.scale_alpha(ring, factor))
        shader.uniform_float("pointSize", px)
        gpu.state.point_size_set(px)
        batch.draw(shader)

    _draw_occluded(th, draw_pass)


def _point_px(th: Theme, role, size) -> float:
    if isinstance(size, (int, float)):
        return float(size)
    if size is not None:
        return th.point_size(size)
    if role is not None:
        return th.point_size_for(role)
    return th.point_size("default")

def points(coords: Sequence, *, role: Role | None = None,
           color: tuple[float, float, float, float] | None = None,
           size: str | float | int | None = None,
           ring_role: Role | None = None,
           theme: Theme | None = None, context=None) -> None:
    th = _resolve_theme(theme, context)
    shader = shaders.point_disc()
    batch = batch_for_shader(shader, "POINTS", {"pos": list(coords)})
    fill = _resolve_color(role, color, th)
    ring = th.color_for(ring_role if ring_role is not None else Role.POINT_OUTLINE)
    px = _point_px(th, role, size)
    shader.bind()
    shader.uniform_float("color", fill)
    shader.uniform_float("ringColor", ring)
    shader.uniform_float("pointSize", px)
    gpu.state.point_size_set(px)
    batch.draw(shader)


def tris(coords: Sequence, *, role: Role | None = None,
         color: tuple[float, float, float, float] | None = None,
         theme: Theme | None = None, context=None) -> None:
    th = _resolve_theme(theme, context)
    shader = shaders.uniform_color()
    batch = batch_for_shader(shader, "TRIS", {"pos": list(coords)})
    c = _resolve_color(role, color, th)
    shader.bind()
    shader.uniform_float("color", c)
    batch.draw(shader)


def rect_2d(x: float, y: float, w: float, h: float, *,
            role: Role | None = None,
            color: tuple[float, float, float, float] | None = None,
            theme: Theme | None = None, context=None) -> None:
    coords = [(x, y), (x + w, y), (x + w, y + h),
              (x, y), (x + w, y + h), (x, y + h)]
    tris(coords, role=role, color=color, theme=theme, context=context)


def ring_3d(center, normal, radius: float, *, role: Role | None = None,
            color: tuple[float, float, float, float] | None = None,
            width: str | None = None, segments: int = 64,
            theme: Theme | None = None, context=None) -> None:
    """Closed circle of `radius` around `center` in the plane
    perpendicular to `normal`. Coordinates are in the space the current
    gpu.matrix stack expects (world space inside a POST_VIEW handler)."""
    n = Vector(normal)
    if n.length_squared < 1e-18:
        return
    n.normalize()
    u = n.orthogonal().normalized()
    v = n.cross(u)
    c = Vector(center)
    pts = []
    step = 2.0 * math.pi / max(3, int(segments))
    for i in range(max(3, int(segments))):
        a = i * step
        pts.append(c + (u * math.cos(a) + v * math.sin(a)) * radius)
    pts.append(pts[0])
    polyline(pts, role=role, color=color, width=width, theme=theme,
             context=context)


def points_colored(coords: Sequence, colors: Sequence, *,
                   size: float = 6.0) -> None:
    """Per-point RGBA colours (weight previews). `colors` is one 4-tuple
    per coord."""
    if not coords:
        return
    shader = shaders.point_flat_color()
    batch = batch_for_shader(shader, "POINTS",
                             {"pos": list(coords), "color": list(colors)})
    shader.bind()
    shader.uniform_float("size", float(size))
    gpu.state.point_size_set(float(size))
    batch.draw(shader)


def occlusion_factors(th: Theme, occluded_min: float = 0.0) -> list:
    """The alpha factors of the occlusion passes `_draw_occluded` runs for
    this theme (what a per-vertex-colour batch has to be built for)."""
    passes = depth_bias.occlusion_passes(
        depth_bias.occluded_opacity(th.backface_dimming, floor=occluded_min))
    return [factor for _, factor in passes]


def _scaled_colors(colors, factor) -> np.ndarray:
    """(N, 4) float32 RGBA with the alpha times `factor` (clamped 0..1)."""
    cols = np.array(colors, dtype=np.float32).reshape(-1, 4)
    cols[:, 3] *= depth_bias.clamp_factor(factor)
    return cols


def points_colored_batches(coords, colors, factors) -> dict:
    """{alpha factor: POINTS batch} of per-point RGBA colours, one per
    occlusion pass (`occlusion_factors`), for `draw_points_colored_world`.
    `coords` / `colors` may be numpy arrays; nothing is converted to Python
    tuples. Callers that keep the batches must drop them on unregister."""
    pos = np.ascontiguousarray(coords, dtype=np.float32).reshape(-1, 3)
    shader = shaders.point_flat_color()
    return {f: batch_for_shader(shader, "POINTS",
                                {"pos": pos, "color": _scaled_colors(colors, f)})
            for f in factors}


def draw_points_colored_world(batches: dict, *, size: float = 6.0,
                              theme: Theme | None = None, context=None) -> None:
    """Draw batches from `points_colored_batches` with the depth bias and
    occlusion passes of `points_world`. A pass whose factor has no batch
    (the theme changed since they were built) is skipped."""
    if not batches:
        return
    th = _resolve_theme(theme, context)
    shader = shaders.point_flat_color()

    def draw_pass(factor):
        batch = batches.get(factor)
        if batch is None:
            return
        shader.bind()
        shader.uniform_float("size", float(size))
        gpu.state.point_size_set(float(size))
        batch.draw(shader)

    _draw_occluded(th, draw_pass)


def points_colored_world(coords: Sequence, colors: Sequence, *,
                         size: float = 6.0, theme: Theme | None = None,
                         context=None) -> None:
    """`points_colored` for a POST_VIEW handler, with the depth bias and
    occlusion passes of `points_world`: hidden points get their alpha
    times 1 - the theme's `backface_dimming`."""
    if len(coords) == 0:
        return
    th = _resolve_theme(theme, context)
    batches = points_colored_batches(coords, colors, occlusion_factors(th))
    draw_points_colored_world(batches, size=size, theme=th)


def edges_colored_world(coord_pairs, colors, *, width: float,
                        theme: Theme | None = None, context=None,
                        occluded_min: float = 0.0) -> None:
    """`edges_world` with one RGBA per point of `coord_pairs` (flat
    [a, b, c, d, ...]; give both points of a segment the same colour for a
    flat-coloured segment): one batch per occlusion pass for the whole
    set instead of one draw per colour."""
    if len(coord_pairs) < 2:
        return
    th = _resolve_theme(theme, context)
    pos = np.ascontiguousarray(coord_pairs, dtype=np.float32).reshape(-1, 3)
    shader = shaders.polyline_flat_color()
    w = float(width)

    def draw_pass(factor):
        batch = batch_for_shader(shader, "LINES",
                                 {"pos": pos, "color": _scaled_colors(colors, factor)})
        shader.bind()
        shader.uniform_float("lineWidth", w)
        shader.uniform_float("viewportSize", gpu.state.viewport_get()[2:])
        batch.draw(shader)

    _draw_occluded(th, draw_pass, occluded_min)
