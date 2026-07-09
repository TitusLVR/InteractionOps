"""Face planarity measurement. Pure Python — no bpy/mathutils/numpy imports,
unit-testable standalone.

A face's deviation is the max angle between any corner's plane (the triangle
`v_prev, v, v_next`) and the face's Newell best-fit normal. Concave corners
on a planar face produce anti-parallel corner normals, so per-corner angles
fold to `min(a, 180 - a)`.
"""
from __future__ import annotations

import math
from typing import Optional, Sequence

Vec3 = Sequence[float]

# Overlay alpha ramp: faint at the threshold, fully saturated at
# FULL_ANGLE_DEG deviation. Fixed constants (not prefs) so the visual read
# stays consistent across meshes regardless of the threshold setting.
ALPHA_MIN = 0.15
ALPHA_MAX = 0.6
FULL_ANGLE_DEG = 15.0

_EPS = 1e-12


def _sub(a: Vec3, b: Vec3):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _cross(a: Vec3, b: Vec3):
    return (a[1] * b[2] - a[2] * b[1],
            a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0])


def _dot(a: Vec3, b: Vec3) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _normalized(a: Vec3) -> Optional[tuple]:
    length = math.sqrt(_dot(a, a))
    if length < _EPS:
        return None
    return (a[0] / length, a[1] / length, a[2] / length)


def newell_normal(coords: Sequence[Vec3]) -> Optional[tuple]:
    """Unit best-fit normal of a (possibly non-planar) polygon, or None if
    the polygon is degenerate (zero area)."""
    nx = ny = nz = 0.0
    count = len(coords)
    for i in range(count):
        x0, y0, z0 = coords[i]
        x1, y1, z1 = coords[(i + 1) % count]
        nx += (y0 - y1) * (z0 + z1)
        ny += (z0 - z1) * (x0 + x1)
        nz += (x0 - x1) * (y0 + y1)
    return _normalized((nx, ny, nz))


def face_deviation_deg(coords: Sequence[Vec3]) -> float:
    """Max angular deviation (degrees) of any corner plane from the face
    plane. 0.0 for triangles and degenerate faces (never highlighted)."""
    count = len(coords)
    if count <= 3:
        return 0.0
    face_n = newell_normal(coords)
    if face_n is None:
        return 0.0
    worst = 0.0
    for i in range(count):
        v_prev = coords[i - 1]
        v = coords[i]
        v_next = coords[(i + 1) % count]
        corner_n = _normalized(_cross(_sub(v, v_prev), _sub(v_next, v)))
        if corner_n is None:
            continue  # collinear corner — no plane to compare
        cos_a = max(-1.0, min(1.0, _dot(corner_n, face_n)))
        angle = math.degrees(math.acos(cos_a))
        # Concave corners are anti-parallel on planar faces.
        angle = min(angle, 180.0 - angle)
        if angle > worst:
            worst = angle
    return worst


def deviation_alpha(dev_deg: float, threshold_deg: float) -> float:
    """Fill alpha for a non-planar face: ALPHA_MIN at the threshold,
    ramping linearly to ALPHA_MAX at FULL_ANGLE_DEG, clamped."""
    if threshold_deg >= FULL_ANGLE_DEG:
        return ALPHA_MAX
    t = (dev_deg - threshold_deg) / (FULL_ANGLE_DEG - threshold_deg)
    t = max(0.0, min(1.0, t))
    return ALPHA_MIN + (ALPHA_MAX - ALPHA_MIN) * t
