"""Window-free logic of Visual UV (operators/mesh_visual_uv.py): the pivot
picked by clicking a gizmo point, the click-or-drag decision on a gizmo
point, and the UV Editor mode's view mapping, gizmo handles and island
picking. Pure Python (tuples, no bpy / mathutils), so the pytest suite
imports it directly.
"""

# Pivot modes: the island's bounding-box centre, the UV cursor, or one of
# the nine gizmo points (PIVOT_ANCHOR, the point's name kept separately).
PIVOT_CENTER = 'CENTER'
PIVOT_CURSOR = 'CURSOR'
PIVOT_ANCHOR = 'ANCHOR'

HANDLE_CORNERS = ('BL', 'BR', 'TL', 'TR')
HANDLE_MIDS = ('B', 'T', 'L', 'R')
# '_C' is the centre's key in the gizmo handle dict; the centre handle is
# hovered as 'CENTER'.
CENTER_KEY = '_C'
CENTER_HANDLE = 'CENTER'
GIZMO_POINTS = HANDLE_CORNERS + HANDLE_MIDS + (CENTER_KEY,)

GIZMO_POINT_LABELS = {
    'BL': "Bottom Left Corner",
    'BR': "Bottom Right Corner",
    'TL': "Top Left Corner",
    'TR': "Top Right Corner",
    'B': "Bottom Side",
    'T': "Top Side",
    'L': "Left Side",
    'R': "Right Side",
    CENTER_KEY: "Center",
}

PIVOT_LABELS = {PIVOT_CENTER: "Center", PIVOT_CURSOR: "Cursor"}


def anchor_uv(bbox_min, bbox_max, name):
    """UV position of gizmo point `name` on the bounding box (corners,
    side midpoints; any other name is the centre)."""
    x0, y0 = bbox_min[0], bbox_min[1]
    x1, y1 = bbox_max[0], bbox_max[1]
    cx, cy = (x0 + x1) * 0.5, (y0 + y1) * 0.5
    return {
        'BL': (x0, y0), 'BR': (x1, y0), 'TL': (x0, y1), 'TR': (x1, y1),
        'B': (cx, y0), 'T': (cx, y1), 'L': (x0, cy), 'R': (x1, cy),
    }.get(name, (cx, cy))


def pivot_label(mode, anchor=None):
    """HUD text of the pivot: "Center", "Cursor" or the picked point's
    full name ("Top Left Corner", "Left Side", ...)."""
    if mode == PIVOT_ANCHOR and anchor in GIZMO_POINT_LABELS:
        return GIZMO_POINT_LABELS[anchor]
    return PIVOT_LABELS.get(mode, str(mode).title())


def next_pivot(mode, anchor=None):
    """P: Center -> Cursor -> Anchor -> Center. Anchor is in the cycle
    only once a gizmo point was picked."""
    modes = [PIVOT_CENTER, PIVOT_CURSOR]
    if anchor:
        modes.append(PIVOT_ANCHOR)
    i = modes.index(mode) if mode in modes else -1
    return modes[(i + 1) % len(modes)]


def pivot_after_click(handle, mode, anchor):
    """(mode, anchor) after a click (press and release without a drag)
    on gizmo point `handle`. The centre point returns to the Center
    pivot and keeps the last picked anchor for P; any other point
    becomes the Anchor pivot."""
    if handle in (CENTER_HANDLE, CENTER_KEY):
        return PIVOT_CENTER, anchor
    if handle in GIZMO_POINT_LABELS:
        return PIVOT_ANCHOR, handle
    return mode, anchor


def is_drag(press, current, threshold):
    """True once the mouse moved further than `threshold` pixels from
    where the button went down (Blender's drag threshold rule)."""
    dx = current[0] - press[0]
    dy = current[1] - press[1]
    return dx * dx + dy * dy > threshold * threshold


class ViewMapping:
    """Affine map between UV (View2D view) coordinates and region pixels:
    x = ox + u * sx, y = oy + v * sy. Built from float samples of the
    view (View2D.region_to_view), not from the integer view_to_region,
    so the transform maths stay exact."""

    __slots__ = ('ox', 'oy', 'sx', 'sy')

    def __init__(self, ox, oy, sx, sy):
        self.ox, self.oy, self.sx, self.sy = ox, oy, sx, sy

    @classmethod
    def from_region_to_view(cls, region_to_view, width, height):
        """Fit from a region_to_view(x, y) -> (u, v) callable sampled at
        the region's origin and its far corner."""
        w = max(float(width), 1.0)
        h = max(float(height), 1.0)
        u0, v0 = region_to_view(0.0, 0.0)
        u1, v1 = region_to_view(w, h)
        du = u1 - u0
        dv = v1 - v0
        sx = w / du if abs(du) > 1e-12 else 1.0
        sy = h / dv if abs(dv) > 1e-12 else 1.0
        return cls(-u0 * sx, -v0 * sy, sx, sy)

    def to_region(self, u, v):
        return (self.ox + u * self.sx, self.oy + v * self.sy)

    def to_view(self, x, y):
        return ((x - self.ox) / self.sx, (y - self.oy) / self.sy)

    def delta_to_view(self, dx, dy):
        """A pixel offset as a UV offset."""
        return (dx / self.sx, dy / self.sy)


def uv_mode_handles(bbox_min, bbox_max, to_region, pad=14.0,
                    rot_offset=28.0):
    """Gizmo of the UV Editor mode: the island's UV bounding box mapped
    to the region, padded by `pad` pixels, with the same keys as the 3D
    gizmo ('BL'..'R', '_C', '_ROT' as (x, y) tuples). '_u_dir' / '_v_dir'
    are the region vectors of the bbox width and height (UV u along
    region x, v along y), present when longer than a pixel. In the UV
    Editor the box always lies straight, so no fit is needed."""
    x0, y0 = to_region(bbox_min[0], bbox_min[1])
    x1, y1 = to_region(bbox_max[0], bbox_max[1])
    xmin, xmax = min(x0, x1) - pad, max(x0, x1) + pad
    ymin, ymax = min(y0, y1) - pad, max(y0, y1) + pad
    cx, cy = (xmin + xmax) * 0.5, (ymin + ymax) * 0.5
    result = {
        'BL': (xmin, ymin), 'BR': (xmax, ymin),
        'TL': (xmin, ymax), 'TR': (xmax, ymax),
        'B': (cx, ymin), 'T': (cx, ymax),
        'L': (xmin, cy), 'R': (xmax, cy),
        CENTER_KEY: (cx, cy),
        '_ROT': (cx, ymax + rot_offset),
    }
    uv_w = max(bbox_max[0] - bbox_min[0], 1e-8)
    uv_h = max(bbox_max[1] - bbox_min[1], 1e-8)
    ox, oy = to_region(0.0, 0.0)
    ux, uy = to_region(uv_w, 0.0)
    vx, vy = to_region(0.0, uv_h)
    u_dir = (ux - ox, uy - oy)
    v_dir = (vx - ox, vy - oy)
    if (u_dir[0] ** 2 + u_dir[1] ** 2 > 1.0
            and v_dir[0] ** 2 + v_dir[1] ** 2 > 1.0):
        result['_u_dir'] = u_dir
        result['_v_dir'] = v_dir
    return result


def point_in_triangle(p, a, b, c, eps=1e-9):
    """True when 2D point p lies inside or on triangle (a, b, c), either
    winding (UV faces of a mirrored island wind clockwise)."""
    d1 = (p[0] - b[0]) * (a[1] - b[1]) - (a[0] - b[0]) * (p[1] - b[1])
    d2 = (p[0] - c[0]) * (b[1] - c[1]) - (b[0] - c[0]) * (p[1] - c[1])
    d3 = (p[0] - a[0]) * (c[1] - a[1]) - (c[0] - a[0]) * (p[1] - a[1])
    has_neg = d1 < -eps or d2 < -eps or d3 < -eps
    has_pos = d1 > eps or d2 > eps or d3 > eps
    return not (has_neg and has_pos)


def fan_triangles(polygon):
    """Fan triangulation of a UV polygon [(u, v), ...] (faces are
    triangulated the same way for the island fills)."""
    return [(polygon[0], polygon[i], polygon[i + 1])
            for i in range(1, len(polygon) - 1)]


def face_at_uv(face_polygons, uv):
    """Index of the first face whose UV polygon holds `uv`, or -1.
    `face_polygons` is [(face index, [(u, v), ...]), ...]; a bounding
    box test skips most faces before the triangle test."""
    u, v = uv[0], uv[1]
    for fi, poly in face_polygons:
        if len(poly) < 3:
            continue
        us = [p[0] for p in poly]
        vs = [p[1] for p in poly]
        if u < min(us) or u > max(us) or v < min(vs) or v > max(vs):
            continue
        for a, b, c in fan_triangles(poly):
            if point_in_triangle((u, v), a, b, c):
                return fi
    return -1
