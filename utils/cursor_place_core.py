"""Pure-python math for Cursor Place (no bpy / mathutils so pytest covers it).

Given the world-space vertices of the polygon under the mouse and the ray
hit point on it, pick the snap candidate — a vertex, an edge midpoint or
the polygon centre — or the slide position, plus the reference edge that
orients the cursor. All distances are measured in 3D from the hit point:
screen-space distances fall apart as soon as a polygon vertex projects
behind a close camera, and the hit point already is "where the mouse
is" on the surface. `build_frame` then turns (normal, edge direction) plus
the user's axis letters into a right-handed 3x3 whose rows are the world
directions of the cursor's local X / Y / Z.
"""
from __future__ import annotations

import math
from collections import namedtuple

from .three_point_core import (
    EPS, DegenerateFrame, _orthonormal, _any_perpendicular, _normalized,
    _cross, _dot, _sub, _add, _scale, _length,
)

AXES = ("X", "Y", "Z")
_AXIS_INDEX = {"X": 0, "Y": 1, "Z": 2}

Pick = namedtuple("Pick", "kind index position normal edge_dir edge")


# --- 3D distances ----------------------------------------------------------

def dist2(p, q):
    d = _sub(p, q)
    return _dot(d, d)


def _segment_param(p, a, b):
    """Clamped parameter t of the point on segment a-b nearest `p`."""
    ab = _sub(b, a)
    denom = _dot(ab, ab)
    if denom <= 0.0:
        return 0.0
    t = _dot(_sub(p, a), ab) / denom
    return 0.0 if t < 0.0 else (1.0 if t > 1.0 else t)


def point_segment_dist2(p, a, b):
    """Squared distance from point `p` to segment `a`-`b`."""
    t = _segment_param(p, a, b)
    return dist2(p, _add(a, _scale(_sub(b, a), t)))


# --- picking ---------------------------------------------------------------

def _tuple3(v):
    return (float(v[0]), float(v[1]), float(v[2]))


def _mid3(a, b):
    return ((a[0] + b[0]) * 0.5, (a[1] + b[1]) * 0.5, (a[2] + b[2]) * 0.5)


def _oriented_edge_dir(a, b, hit):
    """Direction along edge a-b, pointing toward the endpoint nearer `hit`."""
    if dist2(hit, b) <= dist2(hit, a):
        return _sub(b, a)
    return _sub(a, b)


def _nearest_edge(verts, hit):
    n = len(verts)
    best_i, best_d = 0, None
    for i in range(n):
        d = point_segment_dist2(hit, verts[i], verts[(i + 1) % n])
        if best_d is None or d < best_d:
            best_i, best_d = i, d
    return best_i, best_d


def pick_element(verts, hit, *, poly_normal, poly_center):
    """Snap: nearest candidate of one polygon to the hit point.

    Candidates: every vertex, every edge midpoint, the polygon centre.
    Ties resolve vertex > edge > face. Edge i runs verts[i] -> verts[(i+1)%n].
    The normal is always the hit polygon's (the face under the mouse), also
    for a vertex — a cube corner aligned to its averaged vertex normal is
    useless as a pivot.
    """
    n = len(verts)
    best_kind, best_index, best_d = "FACE", None, dist2(hit, poly_center)
    for i in range(n):
        d = dist2(hit, verts[i])
        if d < best_d or (d == best_d and best_kind == "FACE"):
            best_kind, best_index, best_d = "VERT", i, d
    for i in range(n):
        d = dist2(hit, _mid3(verts[i], verts[(i + 1) % n]))
        if d < best_d or (d == best_d and best_kind == "FACE"):
            best_kind, best_index, best_d = "EDGE", i, d

    if best_kind == "VERT":
        i = best_index
        prev_i, next_i = (i - 1) % n, (i + 1) % n
        d_prev = point_segment_dist2(hit, verts[prev_i], verts[i])
        d_next = point_segment_dist2(hit, verts[i], verts[next_i])
        other = next_i if d_next <= d_prev else prev_i
        a = verts[i]
        return Pick("VERT", i, _tuple3(a), _tuple3(poly_normal),
                    _tuple3(_sub(verts[other], a)), (_tuple3(a), _tuple3(verts[other])))

    if best_kind == "EDGE":
        i = best_index
        j = (i + 1) % n
        a, b = verts[i], verts[j]
        return Pick("EDGE", i, _tuple3(_mid3(a, b)), _tuple3(poly_normal),
                    _tuple3(_oriented_edge_dir(a, b, hit)), (_tuple3(a), _tuple3(b)))

    i, _d = _nearest_edge(verts, hit)
    j = (i + 1) % n
    a, b = verts[i], verts[j]
    return Pick("FACE", None, _tuple3(poly_center), _tuple3(poly_normal),
                _tuple3(_oriented_edge_dir(a, b, hit)), (_tuple3(a), _tuple3(b)))


def slide_element(verts, hit, *, poly_normal, threshold):
    """Slide: the cursor follows the hit point continuously.

    Within `threshold` (world units) of a polygon edge the position is the
    hit point projected onto that edge (EDGE pick); otherwise it is the hit
    point itself (FACE pick). Normal = polygon normal; the reference edge
    is the nearest one, oriented toward the endpoint nearer the hit.
    """
    n = len(verts)
    i, d2 = _nearest_edge(verts, hit)
    j = (i + 1) % n
    a, b = verts[i], verts[j]
    edge_dir = _oriented_edge_dir(a, b, hit)
    edge = (_tuple3(a), _tuple3(b))
    if d2 <= threshold * threshold:
        t = _segment_param(hit, a, b)
        pos = _add(a, _scale(_sub(b, a), t))
        return Pick("EDGE", i, _tuple3(pos), _tuple3(poly_normal),
                    _tuple3(edge_dir), edge)
    return Pick("FACE", None, _tuple3(hit), _tuple3(poly_normal),
                _tuple3(edge_dir), edge)


def aim_edge_dir(position, normal, target):
    """Edge direction aimed from `position` at `target`, projected into the
    plane perpendicular to `normal`. None when `target` is missing or sits
    on the normal line (nothing to aim at)."""
    if target is None:
        return None
    nrm = _normalized(normal)
    d = _sub(target, position)
    d = _sub(d, _scale(nrm, _dot(d, nrm)))
    if _length(d) < 1e-9:
        return None
    return _tuple3(_normalized(d))


# --- axis letters ----------------------------------------------------------

def other_axis(a, b):
    """The letter that is neither `a` nor `b`."""
    for ax in AXES:
        if ax != a and ax != b:
            return ax
    raise ValueError((a, b))


def set_normal_axis(normal_axis, edge_axis, new):
    """Assign `new` as the normal axis; on collision the edge axis takes
    the letter the normal axis gave up."""
    if new == normal_axis:
        return normal_axis, edge_axis
    if new == edge_axis:
        return new, normal_axis
    return new, edge_axis


def cycle_edge_axis(normal_axis, edge_axis):
    """The other letter not used by the normal axis."""
    return other_axis(normal_axis, edge_axis)


# --- frame -----------------------------------------------------------------

def build_frame(normal, edge_dir, normal_axis, edge_axis, *, flip=False):
    """Rows = world directions of the cursor's local X, Y, Z. det = +1.

    `normal_axis` row is the (unit) normal, negated when `flip`; `edge_axis`
    row is `edge_dir` projected perpendicular to the normal; the remaining
    row is whichever sign of their cross product makes the frame
    right-handed. A degenerate `edge_dir` (or normal) falls back.
    """
    if _length(normal) < EPS:
        normal = (0.0, 0.0, 1.0)
    nrm = _normalized(normal)
    if flip:
        nrm = _scale(nrm, -1.0)
    try:
        p, s, _t = _orthonormal(nrm, edge_dir)
    except (DegenerateFrame, ZeroDivisionError):
        p = nrm
        s = _any_perpendicular(p)
    rows = [None, None, None]
    ni, ei = _AXIS_INDEX[normal_axis], _AXIS_INDEX[edge_axis]
    rows[ni] = p
    rows[ei] = s
    ti = 3 - ni - ei
    # Right-handed: row[(k+1)%3] x row[(k+2)%3] == row[k] for every k.
    rows[ti] = _cross(rows[(ti + 1) % 3], rows[(ti + 2) % 3])
    return (tuple(rows[0]), tuple(rows[1]), tuple(rows[2]))


# --- adaptive grid (G with Ctrl) --------------------------------------------
#
# A planar grid on the polygon under the mouse: origin at its first vertex,
# U along its first edge, V = normal × U. Only the nodes inside the polygon
# (boundary included) are snap candidates; the step is a scene property,
# 0 meaning "a quarter of the polygon's shortest edge".

GRID_MAX_NODES = 4096


def auto_grid_step(verts):
    """Default step: a quarter of the polygon's shortest edge (1.0 for a
    degenerate polygon)."""
    n = len(verts)
    shortest = min(_length(_sub(verts[(i + 1) % n], verts[i])) for i in range(n))
    return shortest / 4.0 if shortest > EPS else 1.0


def _grid_frame(verts, poly_normal):
    try:
        nrm = _normalized(poly_normal)
    except DegenerateFrame:
        nrm = (0.0, 0.0, 1.0)
    e = _sub(verts[1], verts[0])
    u = _sub(e, _scale(nrm, _dot(e, nrm)))
    try:
        u = _normalized(u)
    except DegenerateFrame:
        u = _any_perpendicular(nrm)
    v = _cross(nrm, u)
    return _tuple3(verts[0]), _tuple3(u), _tuple3(v)


def _inside_2d(p, poly, tol):
    """Even-odd test with a tolerance band so boundary nodes count."""
    x, y = p
    n = len(poly)
    inside = False
    for i in range(n):
        ax, ay = poly[i]
        bx, by = poly[(i + 1) % n]
        # distance to the edge
        dx, dy = bx - ax, by - ay
        L2 = dx * dx + dy * dy
        t = 0.0 if L2 <= 0.0 else max(0.0, min(1.0, ((x - ax) * dx + (y - ay) * dy) / L2))
        ex, ey = ax + dx * t - x, ay + dy * t - y
        if ex * ex + ey * ey <= tol * tol:
            return True
        if (ay > y) != (by > y):
            xi = ax + (y - ay) * dx / dy
            if x < xi:
                inside = not inside
    return inside


def grid_nodes(verts, poly_normal, step, *, max_nodes=GRID_MAX_NODES):
    """Nodes of the polygon grid. Returns (nodes, step, frame, bounds):
    the 3D nodes inside the polygon, the effective step (doubled until the
    polygon's bounding box holds at most `max_nodes` nodes), the frame
    (origin, u, v) and the uv bounds (umin, umax, vmin, vmax)."""
    origin, u, v = _grid_frame(verts, poly_normal)
    uv = [(_dot(_sub(p, origin), u), _dot(_sub(p, origin), v)) for p in verts]
    umin, umax = min(q[0] for q in uv), max(q[0] for q in uv)
    vmin, vmax = min(q[1] for q in uv), max(q[1] for q in uv)
    if step <= EPS:
        step = auto_grid_step(verts)
    extent = max(umax - umin, vmax - vmin, EPS)
    tol = 1e-6 * max(1.0, extent)

    def _range(lo, hi, st):
        i0 = math.ceil(lo / st - 1e-9)
        i1 = math.floor(hi / st + 1e-9)
        return i0, i1

    while True:
        iu0, iu1 = _range(umin, umax, step)
        iv0, iv1 = _range(vmin, vmax, step)
        if (iu1 - iu0 + 1) * (iv1 - iv0 + 1) <= max_nodes:
            break
        step *= 2.0
    nodes = []
    for i in range(iu0, iu1 + 1):
        for j in range(iv0, iv1 + 1):
            pu, pv = i * step, j * step
            if _inside_2d((pu, pv), uv, tol):
                nodes.append(_tuple3(_add(origin, _add(_scale(u, pu), _scale(v, pv)))))
    return nodes, step, (origin, u, v), (umin, umax, vmin, vmax)


def nearest_grid_node(nodes, hit):
    best, best_d = None, None
    for p in nodes:
        d = dist2(hit, p)
        if best_d is None or d < best_d:
            best, best_d = p, d
    return best


def grid_lines(frame, step, bounds):
    """Segments (a, b) of the grid across the polygon's uv bounds, for the
    preview: one line per step along u and along v."""
    origin, u, v = frame
    umin, umax, vmin, vmax = bounds
    iu0, iu1 = math.ceil(umin / step - 1e-9), math.floor(umax / step + 1e-9)
    iv0, iv1 = math.ceil(vmin / step - 1e-9), math.floor(vmax / step + 1e-9)

    def at(pu, pv):
        return _tuple3(_add(origin, _add(_scale(u, pu), _scale(v, pv))))

    lines = []
    for i in range(iu0, iu1 + 1):
        lines.append((at(i * step, vmin), at(i * step, vmax)))
    for j in range(iv0, iv1 + 1):
        lines.append((at(umin, j * step), at(umax, j * step)))
    return lines


# --- floor grid snap (Ctrl over empty space) --------------------------------

def floor_level(base, px_per_unit, min_px, subdivisions=10):
    """Step of the finest floor-grid level (base · subdivisions^k) whose
    on-screen spacing is at least `min_px` pixels."""
    sub = float(subdivisions) if subdivisions and subdivisions > 1 else 10.0
    step = float(base) if base > 0.0 else 1.0
    if px_per_unit <= 0.0:
        return step
    for _ in range(12):                 # coarser until it is readable
        if step * px_per_unit >= min_px:
            break
        step *= sub
    for _ in range(12):                 # finer while it stays readable
        if step / sub * px_per_unit < min_px:
            break
        step /= sub
    return step


def snap_to_step(point, step, axes=(0, 1, 2)):
    out = list(point)
    for i in axes:
        out[i] = round(point[i] / step) * step
    return _tuple3(out)
