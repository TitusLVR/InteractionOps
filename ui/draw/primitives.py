"""Stateless drawing primitives bound to the theme.

Each function:
1. Resolves the requested role to RGBA via the theme.
2. Selects the correct cached shader.
3. Builds a one-shot GPUBatch and draws it.

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


def line(p1, p2, *, role: Role, width: str = "normal",
         theme: Theme | None = None, context=None) -> None:
    polyline([p1, p2], role=role, width=width, theme=theme, context=context)


def polyline(coords: Sequence, *, role: Role, width: str = "normal",
             theme: Theme | None = None, context=None) -> None:
    th = _resolve_theme(theme, context)
    shader = shaders.polyline_uniform_color()
    batch = batch_for_shader(shader, "LINE_STRIP", {"pos": list(coords)})
    shader.bind()
    shader.uniform_float("color", th.color_for(role))
    shader.uniform_float("lineWidth", th.width(width))
    shader.uniform_float("viewportSize", gpu.state.viewport_get()[2:])
    batch.draw(shader)


def edges_3d(coord_pairs: Sequence, *, role: Role, width: str = "normal",
             theme: Theme | None = None, context=None) -> None:
    """Disjoint line segments: coord_pairs is a flat list [a, b, c, d, ...]
    where (a,b), (c,d), ... are segments."""
    th = _resolve_theme(theme, context)
    shader = shaders.polyline_uniform_color()
    batch = batch_for_shader(shader, "LINES", {"pos": list(coord_pairs)})
    shader.bind()
    shader.uniform_float("color", th.color_for(role))
    shader.uniform_float("lineWidth", th.width(width))
    shader.uniform_float("viewportSize", gpu.state.viewport_get()[2:])
    batch.draw(shader)


def points(coords: Sequence, *, role: Role, size: str = "normal",
           ring_role: Role | None = None,
           theme: Theme | None = None, context=None) -> None:
    th = _resolve_theme(theme, context)
    shader = shaders.point_disc()
    batch = batch_for_shader(shader, "POINTS", {"pos": list(coords)})
    fill = th.color_for(role)
    ring = th.color_for(ring_role) if ring_role is not None else (
        max(1.0 - fill[0], 0.0), max(1.0 - fill[1], 0.0),
        max(1.0 - fill[2], 0.0), fill[3])
    px = th.point_size(size)
    shader.bind()
    shader.uniform_float("color", fill)
    shader.uniform_float("ringColor", ring)
    shader.uniform_float("pointSize", px)
    gpu.state.point_size_set(px)
    batch.draw(shader)


def tris(coords: Sequence, *, role: Role,
         theme: Theme | None = None, context=None) -> None:
    th = _resolve_theme(theme, context)
    shader = shaders.uniform_color()
    batch = batch_for_shader(shader, "TRIS", {"pos": list(coords)})
    shader.bind()
    shader.uniform_float("color", th.color_for(role))
    batch.draw(shader)


def rect_2d(x: float, y: float, w: float, h: float, *, role: Role,
            theme: Theme | None = None, context=None) -> None:
    coords = [(x, y), (x + w, y), (x + w, y + h),
              (x, y), (x + w, y + h), (x, y + h)]
    tris(coords, role=role, theme=theme, context=context)
