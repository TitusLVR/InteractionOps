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


def _draw_occluded(th: Theme, draw_pass) -> None:
    """Run `draw_pass(alpha_factor)` once per occlusion pass of the theme's
    Backface Dimming (utils/depth_bias.py), under the depth-biased
    projection, ALPHA blend and no depth writes; puts back the blend /
    depth state the caller had."""
    passes = depth_bias.occlusion_passes(depth_bias.occluded_opacity(th.backface_dimming))
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
                width: str | None = None,
                theme: Theme | None = None, context=None) -> None:
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
    state the caller had, so it can sit inside the caller's own scope."""
    pairs = list(coord_pairs)
    if len(pairs) < 2:
        return
    th = _resolve_theme(theme, context)
    c = _resolve_color(role, color, th)
    if width is not None:
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

    _draw_occluded(th, draw_pass)


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
