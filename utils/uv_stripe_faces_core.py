"""UV Stripe's face model: every face measured on a fan of triangles round a virtual centre.

Pure Python (stdlib only), no bpy, so it runs under plain pytest, and no import of
the other UV Stripe cores, so each of them can use it.

A face of four or more corners is measured on the triangles (centre, corner k,
corner k + 1) round its virtual centre, the mean of its corners: fixed weights, so
the centre's UV is the same mean of the corners' UVs and adds no unknown. A corner
repeated right after itself is dropped first, and a fan triangle under
``FAN_SLIVER`` of the face's area is dropped too (a corner in line with its
neighbours). A triangle is its own fan. A face's stretch is the larger of its
fan's averaged metric and its worst single triangle, fan or corner (``corner_weights``):
an average alone would let one collapsed corner hide behind healthy ones. The same
triangles serve the balanced layout's energy (every triangle its own term, so the
descent cannot hide distortion in one either), its fold guard and
``uv_stripe_core.face_stretch``, and a face is measured the same whichever of its
corners comes first.
"""

import math
from dataclasses import dataclass
from functools import lru_cache

FAN_SLIVER = 1e-3       # a fan triangle under this fraction of its face's area is left out
CORNER_MEASURE_ANGLE = math.radians(150.0)   # a face corner wider than this is measured by its fan only

Vec2 = tuple[float, float]
Vec3 = tuple[float, float, float]
Weights = tuple[tuple[int, float], ...]     # a point of a face as (corner index, weight) pairs


def distinct_corners(face) -> list[int]:
    """The corner positions of ``face`` (ids or points) left after dropping every corner equal to the one
    before it (cyclically): a collapsed edge's repeated corner."""
    n = len(face)
    keep = [k for k in range(n) if face[k] != face[k - 1]] if n > 1 else list(range(n))
    return keep or [0]


def _vector_area(pts) -> float:
    sx = sy = sz = 0.0
    for a, b in zip(pts, pts[1:] + pts[:1]):
        sx += a[1] * b[2] - a[2] * b[1]
        sy += a[2] * b[0] - a[0] * b[2]
        sz += a[0] * b[1] - a[1] * b[0]
    return 0.5 * math.sqrt(sx * sx + sy * sy + sz * sz)


def _corner_angle(a, b, c) -> float:
    u = [a[i] - b[i] for i in range(3)]
    v = [c[i] - b[i] for i in range(3)]
    cross = (u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0])
    return math.atan2(math.sqrt(sum(x * x for x in cross)), sum(u[i] * v[i] for i in range(3)))


def _tri_area3(p, q, r) -> float:
    return _vector_area([p, q, r])


def fan_weights(points: list[Vec3]) -> list[tuple[Weights, Weights, Weights]]:
    """The fan triangles of a face with 3D corners ``points``, each as three points given by their weights on
    the corners (module docstring); empty for a face with no area."""
    keep = distinct_corners(points)
    if len(keep) < 3:
        return []
    if len(keep) == 3:
        return [tuple(((k, 1.0),) for k in keep)]
    pts = [points[k] for k in keep]
    area = _vector_area(pts)
    if area <= 0.0:
        return []
    n = len(keep)
    w = 1.0 / n
    centre_pt = tuple(sum(p[i] for p in pts) / n for i in range(3))
    centre: Weights = tuple((k, w) for k in keep)
    out = []
    for i in range(n):
        a, b = keep[i], keep[(i + 1) % n]
        if _tri_area3(centre_pt, points[a], points[b]) < FAN_SLIVER * area:
            continue
        out.append((centre, ((a, 1.0),), ((b, 1.0),)))
    return out


def corner_weights(points: list[Vec3]) -> list[tuple[Weights, Weights, Weights]]:
    """The corner triangles (corner k - 1, corner k, corner k + 1) of a face of four or more corners with 3D
    corners ``points``, as weights like ``fan_weights``: only real corners, at most ``CORNER_MEASURE_ANGLE``
    wide (a corner nearly in line with its neighbours may be laid straight) and not under ``FAN_SLIVER`` of the
    face's area. Empty for a triangle (its fan is itself) and a face with no area."""
    keep = distinct_corners(points)
    n = len(keep)
    if n < 4:
        return []
    area = _vector_area([points[k] for k in keep])
    if area <= 0.0:
        return []
    out = []
    for i in range(n):
        a, b, c = keep[i - 1], keep[i], keep[(i + 1) % n]
        if _corner_angle(points[a], points[b], points[c]) > CORNER_MEASURE_ANGLE:
            continue
        if _tri_area3(points[a], points[b], points[c]) >= FAN_SLIVER * area:
            out.append((((a, 1.0),), ((b, 1.0),), ((c, 1.0),)))
    return out


@lru_cache(maxsize=65536)
def measured_tris(points: tuple) -> tuple[tuple, tuple]:
    """The triangles a face with corners ``points`` (a tuple of 3D points) is measured on, as corner index
    triples, -1 for the face's virtual centre: (its fan, ``fan_weights``; its real corners, ``corner_weights``).
    Remembered by the points, so measuring the same face again costs nothing."""
    fan = tuple(tuple(-1 if len(w) > 1 else w[0][0] for w in tri) for tri in fan_weights(list(points)))
    corners = tuple(tuple(w[0][0] for w in tri) for tri in corner_weights(list(points)))
    return fan, corners


def weighted(points, weights: Weights):
    """The point ``weights`` names, from the corners ``points`` (2D or 3D)."""
    dim = len(points[0])
    return tuple(sum(w * points[k][i] for k, w in weights) for i in range(dim))


@dataclass
class Fan:
    """One face's fan: its corners in its own plane (``flat``), its fan triangles as weights on its corners
    (``tris``) and its flat area."""

    flat: list
    tris: list
    area: float


def face_fans(verts, faces: dict[int, tuple[int, ...]], tiny: float) -> dict[int, Fan]:
    """Every face of ``faces`` with an area, by id: its ``Fan``. The corners are projected onto the face's own
    plane (``projected_face``); a face with no area above ``tiny`` squared is left out."""
    out = {}
    for fid, face in faces.items():
        flat = projected_face(verts, face, tiny)
        if flat is None:
            continue
        tris = fan_weights([verts[v] for v in face])
        if not tris:
            continue
        area = abs(0.5 * sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(flat, flat[1:] + flat[:1])))
        out[fid] = Fan(flat, tris, area)
    return out


def projected_face(verts, face: tuple[int, ...], tiny: float) -> list[Vec2] | None:
    """One face's corners projected onto its own plane (through its centroid, square to its vector area),
    counter-clockwise for its winding; None for a face with no area. A face that is not flat (a rail side
    bowed by an extra vertex) keeps its outline as seen square on, so a vertex nearly in line with its
    neighbours stays in line."""
    pts = [verts[v] for v in face]
    normal = [0.0, 0.0, 0.0]
    for a, b in zip(pts, pts[1:] + pts[:1]):
        normal = [normal[0] + a[1] * b[2] - a[2] * b[1], normal[1] + a[2] * b[0] - a[0] * b[2],
                  normal[2] + a[0] * b[1] - a[1] * b[0]]
    area = math.sqrt(sum(x * x for x in normal))
    if area <= tiny * tiny:
        return None
    n = [x / area for x in normal]
    centre = [sum(p[i] for p in pts) / len(pts) for i in range(3)]
    axis = None
    for a, b in zip(pts, pts[1:] + pts[:1]):
        d = [b[i] - a[i] for i in range(3)]
        d = [d[i] - n[i] * sum(d[j] * n[j] for j in range(3)) for i in range(3)]
        length = math.sqrt(sum(x * x for x in d))
        if length > tiny:
            axis = [x / length for x in d]
            break
    if axis is None:
        return None
    other = [n[1] * axis[2] - n[2] * axis[1], n[2] * axis[0] - n[0] * axis[2], n[0] * axis[1] - n[1] * axis[0]]
    return [(sum((p[i] - centre[i]) * axis[i] for i in range(3)), sum((p[i] - centre[i]) * other[i] for i in range(3)))
            for p in pts]
