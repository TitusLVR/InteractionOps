"""Pure-python math for Cursor Place (no bpy / mathutils so pytest covers it).

Given the vertices of the polygon under the mouse (world space + their
screen projections), pick the nearest snap candidate — a vertex, an edge
midpoint or the polygon centre — and the reference edge that orients the
cursor. `build_frame` then turns (normal, edge direction) plus the user's
axis letters into a right-handed 3x3 whose rows are the world directions
of the cursor's local X / Y / Z.
"""
from __future__ import annotations

from collections import namedtuple

from .three_point_core import (
    EPS, DegenerateFrame, _orthonormal, _any_perpendicular, _normalized,
    _cross, _sub, _add, _scale, _length,
)

AXES = ("X", "Y", "Z")
_AXIS_INDEX = {"X": 0, "Y": 1, "Z": 2}

Pick = namedtuple("Pick", "kind index position normal edge_dir edge")


# --- 2D distances ----------------------------------------------------------

def dist2(p, q):
    dx = p[0] - q[0]
    dy = p[1] - q[1]
    return dx * dx + dy * dy


def point_segment_dist2(p, a, b):
    """Squared distance from 2D point `p` to segment `a`-`b`."""
    abx, aby = b[0] - a[0], b[1] - a[1]
    denom = abx * abx + aby * aby
    if denom <= 0.0:
        return dist2(p, a)
    t = ((p[0] - a[0]) * abx + (p[1] - a[1]) * aby) / denom
    t = 0.0 if t < 0.0 else (1.0 if t > 1.0 else t)
    return dist2(p, (a[0] + abx * t, a[1] + aby * t))


# --- picking ---------------------------------------------------------------

def _tuple3(v):
    return (float(v[0]), float(v[1]), float(v[2]))


def _mid3(a, b):
    return ((a[0] + b[0]) * 0.5, (a[1] + b[1]) * 0.5, (a[2] + b[2]) * 0.5)


def _oriented_edge_dir(a3, b3, a2, b2, mouse):
    """Unit direction along edge a-b, pointing toward the endpoint whose
    screen position is nearer the mouse."""
    if dist2(mouse, b2) <= dist2(mouse, a2):
        d = _sub(b3, a3)
    else:
        d = _sub(a3, b3)
    return d


def pick_element(verts3d, verts2d, mouse, *, poly_normal, poly_center,
                 poly_center2d):
    """Nearest snap candidate of one polygon in screen space.

    Candidates: every vertex, every edge midpoint, the polygon centre.
    Ties resolve vertex > edge > face. Edge i runs verts[i] -> verts[(i+1)%n].
    The normal is always the hit polygon's (the face under the mouse), also
    for a vertex — a cube corner aligned to its averaged vertex normal is
    useless as a pivot.
    """
    n = len(verts3d)
    best_kind, best_index, best_d = "FACE", None, dist2(mouse, poly_center2d)
    for i in range(n):
        d = dist2(mouse, verts2d[i])
        if d < best_d or (d == best_d and best_kind == "FACE"):
            best_kind, best_index, best_d = "VERT", i, d
    for i in range(n):
        j = (i + 1) % n
        m2 = ((verts2d[i][0] + verts2d[j][0]) * 0.5,
              (verts2d[i][1] + verts2d[j][1]) * 0.5)
        d = dist2(mouse, m2)
        if d < best_d or (d == best_d and best_kind == "FACE"):
            best_kind, best_index, best_d = "EDGE", i, d

    if best_kind == "VERT":
        i = best_index
        prev_i, next_i = (i - 1) % n, (i + 1) % n
        d_prev = point_segment_dist2(mouse, verts2d[prev_i], verts2d[i])
        d_next = point_segment_dist2(mouse, verts2d[i], verts2d[next_i])
        other = next_i if d_next <= d_prev else prev_i
        a3 = verts3d[i]
        edge_dir = _sub(verts3d[other], a3)
        return Pick("VERT", i, _tuple3(a3), _tuple3(poly_normal),
                    _tuple3(edge_dir), (_tuple3(a3), _tuple3(verts3d[other])))

    if best_kind == "EDGE":
        i = best_index
        j = (i + 1) % n
        a3, b3 = verts3d[i], verts3d[j]
        edge_dir = _oriented_edge_dir(a3, b3, verts2d[i], verts2d[j], mouse)
        return Pick("EDGE", i, _tuple3(_mid3(a3, b3)), _tuple3(poly_normal),
                    _tuple3(edge_dir), (_tuple3(a3), _tuple3(b3)))

    # FACE: reference edge = polygon edge nearest the mouse.
    best_i, _d = _nearest_edge(verts2d, mouse)
    j = (best_i + 1) % n
    a3, b3 = verts3d[best_i], verts3d[j]
    edge_dir = _oriented_edge_dir(a3, b3, verts2d[best_i], verts2d[j], mouse)
    return Pick("FACE", None, _tuple3(poly_center), _tuple3(poly_normal),
                _tuple3(edge_dir), (_tuple3(a3), _tuple3(b3)))


def _segment_param(p, a, b):
    """Clamped parameter t of the point on 2D segment a-b nearest `p`."""
    abx, aby = b[0] - a[0], b[1] - a[1]
    denom = abx * abx + aby * aby
    if denom <= 0.0:
        return 0.0
    t = ((p[0] - a[0]) * abx + (p[1] - a[1]) * aby) / denom
    return 0.0 if t < 0.0 else (1.0 if t > 1.0 else t)


def _nearest_edge(verts2d, mouse):
    n = len(verts2d)
    best_i, best_d = 0, None
    for i in range(n):
        d = point_segment_dist2(mouse, verts2d[i], verts2d[(i + 1) % n])
        if best_d is None or d < best_d:
            best_i, best_d = i, d
    return best_i, best_d


def slide_element(verts3d, verts2d, mouse, *, hit_location, poly_normal,
                  threshold_px):
    """Slide mode (Shift held): the cursor follows the mouse continuously.

    Within `threshold_px` of a polygon edge the position is the mouse
    projected onto that edge (EDGE pick); otherwise it is the raycast hit
    point on the face (FACE pick). Normal = polygon normal; the reference
    edge is the nearest one, oriented toward the endpoint nearer the mouse.
    """
    n = len(verts3d)
    i, d2 = _nearest_edge(verts2d, mouse)
    j = (i + 1) % n
    a3, b3 = verts3d[i], verts3d[j]
    edge_dir = _oriented_edge_dir(a3, b3, verts2d[i], verts2d[j], mouse)
    edge = (_tuple3(a3), _tuple3(b3))
    if d2 <= threshold_px * threshold_px:
        t = _segment_param(mouse, verts2d[i], verts2d[j])
        pos = _add(a3, _scale(_sub(b3, a3), t))
        return Pick("EDGE", i, _tuple3(pos), _tuple3(poly_normal),
                    _tuple3(edge_dir), edge)
    return Pick("FACE", None, _tuple3(hit_location), _tuple3(poly_normal),
                _tuple3(edge_dir), edge)


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
    right-handed. A degenerate `edge_dir` falls back to any perpendicular.
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
    a = rows[(ti + 1) % 3]
    b = rows[(ti + 2) % 3]
    rows[ti] = _cross(a, b)
    return (tuple(rows[0]), tuple(rows[1]), tuple(rows[2]))
