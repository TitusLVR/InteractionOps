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
from typing import Sequence

import gpu
from gpu_extras.batch import batch_for_shader

from . import shaders
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
    if isinstance(size, (int, float)):
        px = float(size)
    elif size is not None:
        px = th.point_size(size)
    elif role is not None:
        px = th.point_size_for(role)
    else:
        px = th.point_size("default")
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
