"""Vector glyphs of the iOps material shelf toolbar (no bpy, pytest-covered).

Every glyph is normalised geometry in a 0..1 box, y up:
- "lines": polylines, each a list of (x, y) points (open)
- "loops": closed polylines (the first point is repeated on output)
- "circles": (cx, cy, r) outlines
- "dots": (cx, cy, r) small filled discs
Stroke-only by design (thin lines, no fills) except the dots. Tweak the
numbers here; ui/materials_shelf/draw.py only scales and strokes them.
"""
import math

GLYPHS = {
    # three lines: the Functions menu
    "functions": {
        "lines": [[(0.2, 0.3), (0.8, 0.3)],
                  [(0.2, 0.5), (0.8, 0.5)],
                  [(0.2, 0.7), (0.8, 0.7)]],
    },
    # plus: New Material
    "new": {
        "lines": [[(0.5, 0.2), (0.5, 0.8)],
                  [(0.2, 0.5), (0.8, 0.5)]],
    },
    # magnifier: Search
    "search": {
        "circles": [(0.42, 0.58, 0.26)],
        "lines": [[(0.61, 0.39), (0.84, 0.16)]],
    },
    # sphere on a ground line: Source Scene
    "src_SCENE": {
        "circles": [(0.5, 0.58, 0.26)],
        "lines": [[(0.14, 0.18), (0.86, 0.18)]],
    },
    # selection corners around a dot: Source Selected
    "src_SELECTED": {
        "lines": [[(0.2, 0.4), (0.2, 0.2), (0.4, 0.2)],
                  [(0.6, 0.2), (0.8, 0.2), (0.8, 0.4)],
                  [(0.8, 0.6), (0.8, 0.8), (0.6, 0.8)],
                  [(0.4, 0.8), (0.2, 0.8), (0.2, 0.6)]],
        "dots": [(0.5, 0.5, 0.07)],
    },
    # sheet with a folded corner: Source File
    "src_FILE": {
        "loops": [[(0.26, 0.16), (0.26, 0.84), (0.56, 0.84), (0.74, 0.66),
                   (0.74, 0.16)]],
        "lines": [[(0.56, 0.84), (0.56, 0.66), (0.74, 0.66)]],
    },
    # an empty slot (the count is drawn inside it): Empty slots
    "empty": {
        "loops": [[(0.16, 0.16), (0.16, 0.84), (0.84, 0.84), (0.84, 0.16)]],
    },
}

TOOLS = ("functions", "new", "search", "src_SCENE", "src_SELECTED",
         "src_FILE", "empty")


def circle_points(cx, cy, r, segments=24):
    """Closed polyline of a circle (first point repeated)."""
    pts = [(cx + r * math.cos(2 * math.pi * i / segments),
            cy + r * math.sin(2 * math.pi * i / segments))
           for i in range(segments)]
    return pts + [pts[0]]


def strokes(name, segments=24):
    """(lines, curves, dots) of glyph `name` in the 0..1 box: straight
    polylines (loops closed) to snap to pixels, curves (circles as closed
    polylines) to draw unsnapped, dots as (cx, cy, r)."""
    g = GLYPHS[name]
    lines = [list(p) for p in g.get("lines", ())]
    lines += [list(p) + [p[0]] for p in g.get("loops", ())]
    curves = [circle_points(*c, segments=segments)
              for c in g.get("circles", ())]
    return lines, curves, list(g.get("dots", ()))


def fit(points, x, y, size, snap=True):
    """Map 0..1 points into the square (x, y, size). With `snap`, the
    coordinates land on pixel centres so 1 px strokes stay crisp."""
    out = []
    for px, py in points:
        sx, sy = x + px * size, y + py * size
        if snap:
            sx, sy = math.floor(sx) + 0.5, math.floor(sy) + 0.5
        out.append((sx, sy))
    return out
