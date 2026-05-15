"""Thin blf wrapper bound to the theme.

All BLF calls in the addon should route through this module so font size,
shadow, and color stay consistent.
"""
from __future__ import annotations
import blf

from ..draw.theme import Theme, Role


def configure(theme: Theme, size_token: str = "normal", font_id: int = 0):
    blf.size(font_id, theme.text_size(size_token))
    if theme.shadow.enabled:
        blf.enable(font_id, blf.SHADOW)
        sc = theme.shadow.color
        blf.shadow(font_id, theme.shadow.blur, sc[0], sc[1], sc[2], sc[3])
        blf.shadow_offset(font_id, theme.shadow.offset_x, theme.shadow.offset_y)
    else:
        blf.disable(font_id, blf.SHADOW)


def draw(text: str, x: int, y: int, *, theme: Theme, role: Role,
         size_token: str = "normal", font_id: int = 0, alpha_mul: float = 1.0):
    configure(theme, size_token, font_id)
    r, g, b, a = theme.color_for(role)
    blf.color(font_id, r, g, b, a * alpha_mul)
    blf.position(font_id, x, y, 0)
    blf.draw(font_id, text)


def measure(text: str, *, theme: Theme, size_token: str = "normal",
            font_id: int = 0):
    configure(theme, size_token, font_id)
    return blf.dimensions(font_id, text)
