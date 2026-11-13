"""Depth bias and pass plan for lines drawn over a mesh. Pure Python, no bpy / gpu / mathutils.

Used by ``ui.draw.primitives.edges_world``: lines that lie on mesh edges are drawn twice with the scene's depth
buffer, once where they are in front (``LESS_EQUAL``) and once where geometry hides them (``GREATER``) at a lower
alpha. Two things make that work:

* The bias. A line on an edge has the same depth as the faces around it, so without a bias it would z-fight with
  them. ``biased_projection`` moves every point toward the viewer by changing only the depth row of the projection
  matrix: x, y and w stay as they are, so nothing moves on screen and the line width stays in pixels.

  - Perspective: the result is exactly the projection of the point scaled toward the eye by ``1 - shrink`` in view
    space (the clip-space depth bias of the Non-Planar overlay's shader, done in the matrix instead). The pull is a
    fixed fraction of the point's distance, so it holds at any zoom and scene scale; what it lets through is
    geometry thinner than ``shrink`` times its distance, which is a few pixels on screen.
  - Orthographic: the same fraction of the visible width, as a constant depth offset (depth is linear there).

* The passes. Both passes use the same biased depth, and ``LESS_EQUAL`` / ``GREATER`` split every fragment
  between them, so each fragment is drawn once: a line merely lying on its own faces is in front, never also in the
  dim pass. At a factor of 1 one pass with no depth test draws the same picture.
"""
from __future__ import annotations

from collections.abc import Sequence

# Fraction of the view distance (perspective) or of the visible width (orthographic) that a line is pulled toward
# the viewer. The Non-Planar overlay pulls its fills by the same 0.5%.
DEPTH_SHRINK = 0.005


def clamp_factor(factor) -> float:
    """``factor`` as a float in 0..1 (anything unreadable is 1: drawn as in front)."""
    try:
        f = float(factor)
    except (TypeError, ValueError):
        return 1.0
    if f != f:          # NaN
        return 1.0
    return min(max(f, 0.0), 1.0)


def scale_alpha(color: Sequence[float], factor) -> tuple[float, float, float, float]:
    """``color`` (RGB or RGBA) with its alpha multiplied by ``factor`` (clamped to 0..1)."""
    r, g, b = float(color[0]), float(color[1]), float(color[2])
    a = float(color[3]) if len(color) > 3 else 1.0
    return (r, g, b, a * clamp_factor(factor))


def occlusion_passes(factor) -> list[tuple[str, float]]:
    """The draw passes for an occluded-alpha ``factor``, bottom to top, as (depth test, alpha factor).

    1 (or more): one pass with no depth test, the colour as is. 0 (or less): only the visible pass, so hidden
    parts are not drawn. Between: the visible pass at full alpha and the hidden pass at ``factor``."""
    f = clamp_factor(factor)
    if f >= 1.0:
        return [("ALWAYS", 1.0)]
    passes = [("LESS_EQUAL", 1.0)]
    if f > 0.0:
        passes.append(("GREATER", f))
    return passes


def is_perspective(matrix: Sequence[Sequence[float]]) -> bool:
    """Whether the 4 x 4 projection ``matrix`` (rows) is a perspective one (its w row does not end in 1)."""
    return abs(float(matrix[3][3])) < 0.5


def biased_projection(matrix: Sequence[Sequence[float]], shrink: float = DEPTH_SHRINK) -> list[list[float]]:
    """A copy of the 4 x 4 projection ``matrix`` (rows, OpenGL convention, camera looking down -z) whose depth
    pulls every point toward the viewer; only the depth row changes.

    Perspective: depth row [.., c, d] becomes [.., c, d / (1 - shrink)], which is the projection of the view-space
    point scaled by ``1 - shrink`` toward the eye, divided through by that scale (so x, y, w are unchanged).
    Orthographic: the point's view z moves by ``shrink`` times the visible width (2 / |m00|)."""
    rows = [[float(v) for v in row] for row in matrix]
    s = min(max(float(shrink), 0.0), 0.5)
    if s == 0.0:
        return rows
    if is_perspective(rows):
        rows[2][3] = rows[2][3] / (1.0 - s)
    else:
        sx = abs(rows[0][0])
        width = 2.0 / sx if sx > 0.0 else 0.0
        rows[2][3] += rows[2][2] * s * width
    return rows
