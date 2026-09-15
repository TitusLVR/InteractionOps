"""Pure-python frame math for Three Point Rotation (no bpy / mathutils so
pytest can cover it).

A *frame* is an origin plus a right-handed orthonormal basis
(primary, secondary, tertiary). Frames are built from three points
(`frame_from_points`), from a face (`frame_from_face`) or from an object's
world matrix (`axis_frame`). `align_matrix(src, dst)` is the rigid 4x4 that
carries the source frame onto the target frame: `M = T_dst @ R @ T_src^-1`
with `R = [dst basis] @ [src basis]^T`.

Gram–Schmidt keeps the primary direction exact and projects the secondary
into its perpendicular plane — unlike two stacked Damped Track constraints,
where the second track disturbs the first.
"""
from __future__ import annotations

import math
from collections import namedtuple

EPS = 1e-9

Frame = namedtuple("Frame", "origin primary secondary tertiary")


class DegenerateFrame(ValueError):
    """Points coincide or are collinear — no unique frame."""


# --- vector helpers ------------------------------------------------------

def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _add(a, b):
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def _scale(a, s):
    return (a[0] * s, a[1] * s, a[2] * s)


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _cross(a, b):
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def _length(a):
    return math.sqrt(_dot(a, a))


def _normalized(a):
    L = _length(a)
    if L < EPS:
        raise DegenerateFrame("zero-length direction")
    return (a[0] / L, a[1] / L, a[2] / L)


def _any_perpendicular(n):
    """A unit vector perpendicular to unit `n` (stable choice)."""
    helper = (1.0, 0.0, 0.0) if abs(n[0]) < 0.9 else (0.0, 1.0, 0.0)
    return _normalized(_sub(helper, _scale(n, _dot(helper, n))))


def _orthonormal(primary_dir, secondary_dir, secondary_hint=None):
    p = _normalized(primary_dir)
    if secondary_dir is None:
        secondary_dir = secondary_hint if secondary_hint is not None else _any_perpendicular(p)
    s = _sub(secondary_dir, _scale(p, _dot(secondary_dir, p)))
    if _length(s) < EPS:
        if secondary_hint is not None and secondary_dir is secondary_hint:
            s = _any_perpendicular(p)
        else:
            raise DegenerateFrame("secondary direction is parallel to primary")
    s = _normalized(s)
    t = _cross(p, s)
    return p, s, t


# --- frame builders ------------------------------------------------------

def frame_from_points(origin, primary_pt, secondary_pt, *, secondary_hint=None):
    """Frame at `origin`, primary axis towards `primary_pt`, secondary axis
    towards `secondary_pt` projected perpendicular to the primary.

    `secondary_pt=None` (two-point aim) picks the perpendicular closest to
    `secondary_hint` (a direction), or any stable perpendicular when the
    hint is missing or parallel to the primary.
    """
    o = tuple(float(c) for c in origin)
    p_dir = _sub(primary_pt, o)
    if _length(p_dir) < EPS:
        raise DegenerateFrame("primary point coincides with origin")
    s_dir = None if secondary_pt is None else _sub(secondary_pt, o)
    if s_dir is not None and _length(s_dir) < EPS:
        raise DegenerateFrame("secondary point coincides with origin")
    p, s, t = _orthonormal(p_dir, s_dir, secondary_hint)
    return Frame(o, p, s, t)


def frame_from_face(center, normal, edge_dir):
    """Frame at a face: primary = normal, secondary = edge direction
    projected into the face plane."""
    o = tuple(float(c) for c in center)
    p, s, t = _orthonormal(normal, edge_dir)
    return Frame(o, p, s, t)


_AXIS_INDEX = {"X": 0, "Y": 1, "Z": 2}


def parse_axis(token):
    """'X' / '-Y' → (index, sign)."""
    token = token.upper()
    sign = -1.0 if token.startswith("-") else 1.0
    letter = token.lstrip("+-")
    if letter not in _AXIS_INDEX:
        raise ValueError(f"bad axis {token!r}")
    return _AXIS_INDEX[letter], sign


def axis_frame(matrix_world, primary_axis, secondary_axis, *, pivot=None):
    """Frame from an object's world matrix (4x4 nested sequence): the
    normalized local axes named by `primary_axis` / `secondary_axis`
    ('X', '-Z', ...). Scale and shear are removed by Gram–Schmidt. Origin is
    `pivot` when given, else the matrix translation."""
    m = matrix_world
    cols = [(m[0][i], m[1][i], m[2][i]) for i in range(3)]
    pi, ps = parse_axis(primary_axis)
    si, ss = parse_axis(secondary_axis)
    if pi == si:
        raise DegenerateFrame("primary and secondary use the same axis")
    p_dir = _scale(cols[pi], ps)
    s_dir = _scale(cols[si], ss)
    p, s, t = _orthonormal(p_dir, s_dir)
    o = tuple(float(c) for c in pivot) if pivot is not None else (m[0][3], m[1][3], m[2][3])
    return Frame(o, p, s, t)


# --- alignment -----------------------------------------------------------

def align_matrix(src: Frame, dst: Frame):
    """Rigid 4x4 (nested tuples, row-major) mapping the source frame onto
    the target frame: origin → origin, primary → primary, secondary →
    secondary."""
    # R = B_dst @ B_src^T, with bases as column matrices.
    bs = (src.primary, src.secondary, src.tertiary)   # columns
    bd = (dst.primary, dst.secondary, dst.tertiary)
    r = [[sum(bd[k][i] * bs[k][j] for k in range(3)) for j in range(3)] for i in range(3)]
    ro = tuple(sum(r[i][j] * src.origin[j] for j in range(3)) for i in range(3))
    tr = _sub(dst.origin, ro)
    return (
        (r[0][0], r[0][1], r[0][2], tr[0]),
        (r[1][0], r[1][1], r[1][2], tr[1]),
        (r[2][0], r[2][1], r[2][2], tr[2]),
        (0.0, 0.0, 0.0, 1.0),
    )


def mat_apply(m, p):
    """Apply a 4x4 to a point."""
    return tuple(m[i][0] * p[0] + m[i][1] * p[1] + m[i][2] * p[2] + m[i][3] for i in range(3))


def rotation_angle_deg(m):
    """Rotation angle (degrees) of the 3x3 part of `m`."""
    tr = m[0][0] + m[1][1] + m[2][2]
    c = max(-1.0, min(1.0, (tr - 1.0) * 0.5))
    return math.degrees(math.acos(c))


# --- point-pair rotations (the Align / Roll steps) ------------------------

def _rodrigues(axis_unit, angle):
    """4x4 rotation about a unit axis through the origin."""
    x, y, z = axis_unit
    c, s = math.cos(angle), math.sin(angle)
    C = 1.0 - c
    return (
        (c + x * x * C,     x * y * C - z * s, x * z * C + y * s, 0.0),
        (y * x * C + z * s, c + y * y * C,     y * z * C - x * s, 0.0),
        (z * x * C - y * s, z * y * C + x * s, c + z * z * C,     0.0),
        (0.0, 0.0, 0.0, 1.0),
    )


def _about_pivot(rot, pivot):
    """T(pivot) @ rot @ T(-pivot) for a 4x4 rotation `rot`."""
    p = tuple(float(c) for c in pivot)
    rp = tuple(rot[i][0] * p[0] + rot[i][1] * p[1] + rot[i][2] * p[2] for i in range(3))
    return (
        (rot[0][0], rot[0][1], rot[0][2], p[0] - rp[0]),
        (rot[1][0], rot[1][1], rot[1][2], p[1] - rp[1]),
        (rot[2][0], rot[2][1], rot[2][2], p[2] - rp[2]),
        (0.0, 0.0, 0.0, 1.0),
    )


def rotate_ray_onto(pivot, from_pt, to_pt):
    """Minimal rotation about `pivot` that turns the ray pivot→from_pt onto
    the ray pivot→to_pt. Antiparallel rays turn 180° about a stable
    perpendicular. Returns a 4x4 (row-major nested tuples)."""
    u = _sub(from_pt, pivot)
    v = _sub(to_pt, pivot)
    if _length(u) < EPS or _length(v) < EPS:
        raise DegenerateFrame("point coincides with the pivot")
    u = _normalized(u)
    v = _normalized(v)
    axis = _cross(u, v)
    sin_a = _length(axis)
    cos_a = max(-1.0, min(1.0, _dot(u, v)))
    if sin_a < EPS:
        if cos_a > 0.0:
            return _about_pivot(_rodrigues((0.0, 0.0, 1.0), 0.0), pivot)
        return _about_pivot(_rodrigues(_any_perpendicular(u), math.pi), pivot)
    angle = math.atan2(sin_a, cos_a)
    return _about_pivot(_rodrigues(_scale(axis, 1.0 / sin_a), angle), pivot)


def roll_about_axis(pivot, axis_dir, from_pt, to_pt):
    """Rotation about the axis (pivot, axis_dir) that brings the projection
    of from_pt onto the plane ⟂ axis in line with the projection of to_pt.
    Shortest signed angle. Returns a 4x4."""
    a = _normalized(axis_dir)
    u = _sub(from_pt, pivot)
    v = _sub(to_pt, pivot)
    u = _sub(u, _scale(a, _dot(u, a)))
    v = _sub(v, _scale(a, _dot(v, a)))
    if _length(u) < EPS or _length(v) < EPS:
        raise DegenerateFrame("point lies on the roll axis")
    u = _normalized(u)
    v = _normalized(v)
    angle = math.atan2(_dot(_cross(u, v), a), _dot(u, v))
    return _about_pivot(_rodrigues(a, angle), pivot)
