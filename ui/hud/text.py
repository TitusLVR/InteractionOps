"""Thin blf wrapper bound to the theme.

All BLF calls in the addon should route through this module so font face,
size, shadow, and color stay consistent.

Custom font is loaded once per unique `theme.font_path` and cached. Pass
`font_id=None` (the default) to use whatever the theme has configured;
pass an explicit integer to override.

Performance note: `measure()` results are cached by (text, font_id, size).
`blf.dimensions` rasterizes glyphs which is comparatively expensive,
and HUD items usually keep their text identical between frames. The
cache is bounded to keep memory in check.
"""
from __future__ import annotations
import os
import blf

from ..draw.theme import Theme, Role


# Cache: { font_path: font_id }. Blender's default font is id 0; we keep
# a sentinel for the "no custom font" case to avoid reloading every draw.
_FONT_CACHE: dict[str, int] = {"": 0}

# Cache: { (text, font_id, size_px) -> (width_px, height_px) }
_MEASURE_CACHE: dict[tuple, tuple[float, float]] = {}
_MEASURE_CACHE_MAX = 2048


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
              font_id: int | None = None,
              shadow_alpha_mul: float = 1.0) -> int:
    if font_id is None:
        font_id = _resolve_font(theme)
    blf.size(font_id, theme.text_size(size_token))
    if theme.shadow.enabled and shadow_alpha_mul > 0.0:
        blf.enable(font_id, blf.SHADOW)
        sc = theme.shadow.color
        blf.shadow(font_id, theme.shadow.blur,
                   sc[0], sc[1], sc[2], sc[3] * shadow_alpha_mul)
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
    # Fade the drop shadow alongside the glyph itself — otherwise low
    # alpha_mul leaves an opaque dark shadow trailing behind, which is
    # visible as black ghosts during fade-out animations (shockwave etc).
    font_id = configure(theme, size_token, font_id,
                        shadow_alpha_mul=alpha_mul)
    if color is not None:
        r, g, b, a = color
    else:
        r, g, b, a = theme.color_for(role)
    blf.color(font_id, r, g, b, a * alpha_mul)
    blf.position(font_id, x, y, 0)
    blf.draw(font_id, text)


def measure(text: str, *, theme: Theme, size_token: str = "normal",
            font_id: int | None = None) -> tuple[float, float]:
    """Cached `blf.dimensions(text)`. Same (text, font, size_px) returns the
    same value across the operator's lifetime without re-rasterizing glyphs.
    """
    if font_id is None:
        font_id = _resolve_font(theme)
    size_px = theme.text_size(size_token)
    key = (text, font_id, size_px)
    hit = _MEASURE_CACHE.get(key)
    if hit is not None:
        return hit
    # Cache miss — size the font and measure. `configure` would also touch
    # shadow state, but blf.dimensions doesn't depend on shadow, so we
    # skip the shadow blf calls here.
    blf.size(font_id, size_px)
    dim = blf.dimensions(font_id, text)
    if len(_MEASURE_CACHE) >= _MEASURE_CACHE_MAX:
        # Evict ~10% oldest entries (insertion order in dict).
        evict = _MEASURE_CACHE_MAX // 10
        for k in list(_MEASURE_CACHE)[:evict]:
            del _MEASURE_CACHE[k]
    _MEASURE_CACHE[key] = dim
    return dim


def invalidate_caches() -> None:
    """Drop measurement cache. Call when theme settings that affect
    glyph metrics change (font_path, text sizes)."""
    _MEASURE_CACHE.clear()
