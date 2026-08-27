"""Pure-python hinge math (no bpy) so pytest can cover it.

flush_angle: the signed rotation about `axis` that makes the plane
with normal `n_sel` coplanar with the plane with normal `n_tgt`.
Coplanar means the rotated normal is parallel OR anti-parallel to the
target normal. `prefer="parallel"` (the Hinge operator's choice) lands
the flap as the target plane's continuation, facing the same way;
`prefer="antiparallel"` folds it onto the target (lid on a box);
`prefer="shortest"` (default) takes the smaller-magnitude representative.
"""
import math

EPS = 1e-9


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _cross(a, b):
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def _norm(a):
    L = math.sqrt(_dot(a, a))
    if L < EPS:
        return None
    return (a[0] / L, a[1] / L, a[2] / L)


def _perp_to_axis(v, axis):
    d = _dot(v, axis)
    return (v[0] - d * axis[0], v[1] - d * axis[1], v[2] - d * axis[2])


def flush_angle(n_sel, n_tgt, axis, prefer="shortest"):
    axis = _norm(axis)
    if axis is None:
        return None
    a = _norm(_perp_to_axis(n_sel, axis))
    b = _norm(_perp_to_axis(n_tgt, axis))
    if a is None or b is None:
        return None
    # `ang` lands the normal parallel to the target's, `alt` anti-parallel.
    ang = math.atan2(_dot(_cross(a, b), axis), _dot(a, b))
    nb = (-b[0], -b[1], -b[2])
    alt = math.atan2(_dot(_cross(a, nb), axis), _dot(a, nb))
    if prefer == "parallel":
        return ang
    if prefer == "antiparallel":
        return alt
    return ang if abs(ang) <= abs(alt) else alt
