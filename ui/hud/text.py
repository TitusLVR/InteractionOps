"""Thin blf wrapper bound to the theme.

All BLF calls in the addon should route through this module so font face,
size, shadow, and color stay consistent.

Custom font is loaded once per unique `theme.font_path` and cached. Pass
`font_id=None` (the default) to use whatever the theme has configured;
pass an explicit integer to override.
"""
from __future__ import annotations
import os
import blf

from ..draw.theme import Theme, Role


# Cache: { font_path: font_id }. Blender's default font is id 0; we keep
# a sentinel for the "no custom font" case to avoid reloading every draw.
_FONT_CACHE: dict[str, int] = {"": 0}


def _resolve_font(theme: Theme) -> int:
    """Return a blf font_id for the theme's configured font.
    Falls back to Blender's default (0) if the path is empty or invalid."""
    path = theme.font_path or ""
    cached = _FONT_CACHE.get(path)
    if cached is not None:
        return cached
    if not path or not os.path.isfile(path):
        _FONT_CACHE[path] = 0
        return 0
    try:
        fid = blf.load(path)
    except Exception:
        fid = -1
    if fid < 0:
        _FONT_CACHE[path] = 0
        return 0
    _FONT_CACHE[path] = fid
    return fid


def configure(theme: Theme, size_token: str = "normal",
              font_id: int | None = None) -> int:
    if font_id is None:
        font_id = _resolve_font(theme)
    blf.size(font_id, theme.text_size(size_token))
    if theme.shadow.enabled:
        blf.enable(font_id, blf.SHADOW)
        sc = theme.shadow.color
        blf.shadow(font_id, theme.shadow.blur, sc[0], sc[1], sc[2], sc[3])
        blf.shadow_offset(font_id, theme.shadow.offset_x, theme.shadow.offset_y)
    else:
        blf.disable(font_id, blf.SHADOW)
    return font_id


def draw(text: str, x: int, y: int, *, theme: Theme, role: Role | None = None,
         color: tuple[float, float, float, float] | None = None,
         size_token: str = "normal", font_id: int | None = None,
         alpha_mul: float = 1.0):
    """Draw text. Exactly one of `role` or `color` must be provided.
    `color` lets callers pass a fully-resolved RGBA (e.g. axis colors
    from Blender's user_interface theme) instead of routing through
    a theme Role."""
    if color is None and role is None:
        raise ValueError("hud_text.draw requires either role= or color=")
    font_id = configure(theme, size_token, font_id)
    if color is not None:
        r, g, b, a = color
    else:
        r, g, b, a = theme.color_for(role)
    blf.color(font_id, r, g, b, a * alpha_mul)
    blf.position(font_id, x, y, 0)
    blf.draw(font_id, text)


def measure(text: str, *, theme: Theme, size_token: str = "normal",
            font_id: int | None = None):
    font_id = configure(theme, size_token, font_id)
    return blf.dimensions(font_id, text)
