"""Pure math for the UV Align pie (no bpy / mathutils).

Everything works on plain tuples so it can be unit-tested outside Blender:

* point mode   -- `point_line_target`: where selected UVs collapse to.
* island mode  -- `island_offsets`: rigid translation per island bbox.
* world up     -- `world_up_angle`: rotation that makes world +Z read as
                  UV +V on an island, from its 3D/UV triangles.
* follow active -- `uv_frame` + `transport_up`: the active face's UV "up"
                  carried over the 3D surface onto another island, then fed
                  to `world_up_angle` as that island's up vector.
"""
import math

DIRECTIONS = ("N", "S", "W", "E", "CENTER_X", "CENTER_Y", "WORLD_UP",
              "FOLLOW_ACTIVE")

#: Islands whose surface barely "sees" world up (horizontal faces) are left
#: alone: |up projected onto the surface|, area-averaged, below this.
WORLD_UP_MIN_RATIO = 0.01


# --------------------------------------------------------------- point mode

def point_line_target(direction, uvs):
    """Line all selected UVs collapse onto.

    Returns ``(axis, value)`` where axis 0 means "set u = value" (a vertical
    line) and 1 means "set v = value" (a horizontal line), or None when
    ``uvs`` is empty or the direction is not a line alignment.
    """
    uvs = list(uvs)
    if not uvs:
        return None
    us = [p[0] for p in uvs]
    vs = [p[1] for p in uvs]
    if direction == "N":
        return 1, max(vs)
    if direction == "S":
        return 1, min(vs)
    if direction == "W":
        return 0, min(us)
    if direction == "E":
        return 0, max(us)
    if direction == "CENTER_X":
        return 0, sum(us) / len(us)
    if direction == "CENTER_Y":
        return 1, sum(vs) / len(vs)
    return None


# -------------------------------------------------------------- island mode

def bbox_of(uvs):
    """(min_u, min_v, max_u, max_v) of an iterable of (u, v)."""
    uvs = list(uvs)
    us = [p[0] for p in uvs]
    vs = [p[1] for p in uvs]
    return min(us), min(vs), max(us), max(vs)


def bbox_center(bb):
    return (bb[0] + bb[2]) * 0.5, (bb[1] + bb[3]) * 0.5


def island_offsets(direction, bboxes):
    """Per-island (du, dv) translation for a bbox alignment.

    ``bboxes`` is a list of (min_u, min_v, max_u, max_v). N/S/W/E make the
    island's bbox side flush with the extreme side among all islands;
    CENTER_X/CENTER_Y give every bbox centre the mean centre u / v.
    """
    bboxes = list(bboxes)
    if not bboxes:
        return []
    if direction == "N":
        t = max(b[3] for b in bboxes)
        return [(0.0, t - b[3]) for b in bboxes]
    if direction == "S":
        t = min(b[1] for b in bboxes)
        return [(0.0, t - b[1]) for b in bboxes]
    if direction == "W":
        t = min(b[0] for b in bboxes)
        return [(t - b[0], 0.0) for b in bboxes]
    if direction == "E":
        t = max(b[2] for b in bboxes)
        return [(t - b[2], 0.0) for b in bboxes]
    centers = [bbox_center(b) for b in bboxes]
    if direction == "CENTER_X":
        t = sum(c[0] for c in centers) / len(centers)
        return [(t - c[0], 0.0) for c in centers]
    if direction == "CENTER_Y":
        t = sum(c[1] for c in centers) / len(centers)
        return [(0.0, t - c[1]) for c in centers]
    raise ValueError(f"not an island alignment: {direction!r}")


# ----------------------------------------------------------------- world up

def _sub(a, b):
    return tuple(x - y for x, y in zip(a, b))


def _dot(a, b):
    return sum(x * y for x, y in zip(a, b))


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1],
            a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0])


def triangle_uv_direction(p, t, d):
    """Map a 3D direction into UV space through one triangle.

    ``p`` = three 3D points, ``t`` = their three UVs, ``d`` = 3D direction.
    The triangle defines a linear map J (the UV Jacobian) from its plane to
    UV with J(e1) = t1 - t0, J(e2) = t2 - t0. ``d`` is projected onto the
    plane and pushed through J.

    Returns ``(uv_dir, proj_len, area)``: the UV image of the projected
    direction (not normalised), the length of ``d`` projected onto the
    plane, and the triangle's 3D area. ``None`` for degenerate triangles.
    """
    e1 = _sub(p[1], p[0])
    e2 = _sub(p[2], p[0])
    n = _cross(e1, e2)
    nn = _dot(n, n)
    if nn < 1e-20:
        return None
    area = 0.5 * math.sqrt(nn)
    # Project d onto the plane.
    k = _dot(d, n) / nn
    dt = tuple(di - k * ni for di, ni in zip(d, n))
    proj_len = math.sqrt(_dot(dt, dt))
    # dt = a*e1 + b*e2 -> solve the 2x2 Gram system.
    g11, g12, g22 = _dot(e1, e1), _dot(e1, e2), _dot(e2, e2)
    det = g11 * g22 - g12 * g12
    if abs(det) < 1e-20:
        return None
    r1, r2 = _dot(dt, e1), _dot(dt, e2)
    a = (r1 * g22 - r2 * g12) / det
    b = (r2 * g11 - r1 * g12) / det
    f1 = _sub(t[1], t[0])
    f2 = _sub(t[2], t[0])
    uv = (a * f1[0] + b * f2[0], a * f1[1] + b * f2[1])
    return uv, proj_len, area


def world_up_direction(tris, up=(0.0, 0.0, 1.0), aspect=1.0):
    """Area-weighted UV direction of world ``up`` over an island.

    ``tris`` is an iterable of ``(points3d, uvs)`` triangles in world space.
    ``aspect`` = image width / height; u is scaled by it so the direction is
    measured in (square) pixel space.

    Each triangle contributes its unit UV direction weighted by
    ``area * |up projected on the triangle|`` -- steep faces dominate, flat
    (horizontal) ones contribute nothing. Returns ``(direction, ratio)``
    where ratio = |sum| / total area in [0, 1] (0 for a fully horizontal or
    self-cancelling island). ``direction`` is None when nothing contributes.
    """
    su = sv = 0.0
    total_area = 0.0
    for p, t in tris:
        ts = tuple((uv[0] * aspect, uv[1]) for uv in t)
        res = triangle_uv_direction(p, ts, up)
        if res is None:
            continue
        uv, proj_len, area = res
        total_area += area
        ln = math.hypot(uv[0], uv[1])
        if ln < 1e-12:
            continue
        w = area * proj_len / ln
        su += uv[0] * w
        sv += uv[1] * w
    if total_area <= 0.0:
        return None, 0.0
    length = math.hypot(su, sv)
    if length < 1e-12:
        return None, 0.0
    return (su / length, sv / length), length / total_area


def world_up_angle(tris, up=(0.0, 0.0, 1.0), aspect=1.0,
                   min_ratio=WORLD_UP_MIN_RATIO):
    """Counter-clockwise rotation (radians, in aspect-corrected UV space)
    that turns the island's world-up direction into +V, or None when the
    island faces up/down and has no meaningful up direction."""
    direction, ratio = world_up_direction(tris, up, aspect)
    if direction is None or ratio < min_ratio:
        return None
    return math.pi * 0.5 - math.atan2(direction[1], direction[0])


def rotate_uv(uv, center, angle, aspect=1.0):
    """Rotate ``uv`` about ``center`` by ``angle`` in aspect-corrected space
    (u scaled by ``aspect`` before rotating, unscaled after) so the island
    keeps its on-screen shape on non-square images."""
    c, s = math.cos(angle), math.sin(angle)
    x = (uv[0] - center[0]) * aspect
    y = uv[1] - center[1]
    rx = c * x - s * y
    ry = s * x + c * y
    return center[0] + rx / aspect, center[1] + ry


# ------------------------------------------------------------ follow active

#: Normals closer than this (dot) to opposite use the fixed half-turn.
ANTI_PARALLEL_DOT = -0.999
#: Normals closer than this (dot) count as parallel: no rotation.
PARALLEL_DOT = 1.0 - 1e-9


def _norm(v):
    ln = math.sqrt(_dot(v, v))
    if ln < 1e-12:
        return None
    return tuple(x / ln for x in v)


def surface_normal(tris):
    """Area-weighted unit normal of ``(points3d, uvs)`` triangles (winding
    order as given), or None when they cancel out / are degenerate."""
    s = (0.0, 0.0, 0.0)
    for p, _t in tris:
        n = _cross(_sub(p[1], p[0]), _sub(p[2], p[0]))
        s = (s[0] + n[0], s[1] + n[1], s[2] + n[2])
    return _norm(s)


def triangle_uv_frame(p, t):
    """3D directions that one triangle maps onto UV +u and +v.

    Inverts the triangle's UV Jacobian: with e = 3D edges and f = UV edges,
    returns ``(T_u, T_v)`` such that J(T_u) = (1, 0) and J(T_v) = (0, 1),
    both in the triangle's plane and unnormalised, or None when either the
    3D or the UV triangle is degenerate.
    """
    e1 = _sub(p[1], p[0])
    e2 = _sub(p[2], p[0])
    f1 = _sub(t[1], t[0])
    f2 = _sub(t[2], t[0])
    det = f1[0] * f2[1] - f2[0] * f1[1]
    if abs(det) < 1e-20 or _dot(_cross(e1, e2), _cross(e1, e2)) < 1e-20:
        return None
    # [f1 f2] (a, b)^T = target  ->  T = a*e1 + b*e2
    tu = tuple((f2[1] * x - f1[1] * y) / det for x, y in zip(e1, e2))
    tv = tuple((-f2[0] * x + f1[0] * y) / det for x, y in zip(e1, e2))
    return tu, tv


def uv_frame(tris, aspect=1.0):
    """UV frame of a face: ``(T_u, T_v, n)`` as unit 3D vectors.

    T_u / T_v are the world directions that read as UV +u / +v (u measured
    in pixel space via ``aspect``), area-weighted over the triangles (each
    triangle's vectors normalised first, so texel density does not bias
    the mix); n is the area-weighted normal. None when degenerate.
    """
    su = (0.0, 0.0, 0.0)
    sv = (0.0, 0.0, 0.0)
    for p, t in tris:
        ts = tuple((uv[0] * aspect, uv[1]) for uv in t)
        fr = triangle_uv_frame(p, ts)
        if fr is None:
            continue
        cr = _cross(_sub(p[1], p[0]), _sub(p[2], p[0]))
        area = 0.5 * math.sqrt(_dot(cr, cr))
        tu, tv = _norm(fr[0]), _norm(fr[1])
        if tu is None or tv is None:
            continue
        su = tuple(a + area * b for a, b in zip(su, tu))
        sv = tuple(a + area * b for a, b in zip(sv, tv))
    n = surface_normal(tris)
    tu, tv = _norm(su), _norm(sv)
    if n is None or tu is None or tv is None:
        return None
    return tu, tv, n


def rotate_axis_angle(v, axis, angle):
    """Rodrigues: rotate ``v`` about unit ``axis`` by ``angle`` radians."""
    c, s = math.cos(angle), math.sin(angle)
    kxv = _cross(axis, v)
    kdv = _dot(axis, v)
    return tuple(v[i] * c + kxv[i] * s + axis[i] * kdv * (1.0 - c)
                 for i in range(3))


def rotate_between(v, n_from, n_to, half_turn_axis):
    """Apply the minimal rotation taking unit ``n_from`` onto unit ``n_to``
    to ``v``.

    Parallel normals -> ``v`` unchanged. Anti-parallel (dot below
    `ANTI_PARALLEL_DOT`) has no unique minimal rotation, so a half turn
    about ``half_turn_axis`` (projected into the ``n_from`` plane) is used
    instead.
    """
    c = max(-1.0, min(1.0, _dot(n_from, n_to)))
    if c >= PARALLEL_DOT:
        return tuple(v)
    if c < ANTI_PARALLEL_DOT:
        k = _dot(half_turn_axis, n_from)
        axis = _norm(tuple(a - k * b for a, b in zip(half_turn_axis, n_from)))
        if axis is None:
            return tuple(v)
        return rotate_axis_angle(v, axis, math.pi)
    axis = _norm(_cross(n_from, n_to))
    if axis is None:
        return tuple(v)
    return rotate_axis_angle(v, axis, math.acos(c))


def transport_up(frame, n_target):
    """Active face's UV "up" (T_v) carried onto a surface with normal
    ``n_target``, as if the two were connected (unfolded) on the model.

    Anti-parallel targets turn around the vertical (T_v) axis, so "up"
    stays up -- walking around a box rather than flipping over its top.
    ``n_target`` None (e.g. a closed island whose normals cancel) leaves
    the direction as is.
    """
    _tu, tv, n = frame
    if n_target is None:
        return tv
    return rotate_between(tv, n, n_target, tv)


def follow_active_angle(frame, tris, aspect=1.0, min_ratio=WORLD_UP_MIN_RATIO):
    """Rotation (radians, aspect-corrected UV space) that makes an island
    follow the active face ``frame`` (see `uv_frame`), or None when the
    transported direction does not project onto the island."""
    up = transport_up(frame, surface_normal(tris))
    return world_up_angle(tris, up=up, aspect=aspect, min_ratio=min_ratio)
