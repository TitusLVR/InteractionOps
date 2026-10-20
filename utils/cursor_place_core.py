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
