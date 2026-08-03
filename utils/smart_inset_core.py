"""Pure-Python 2D wavefront (simplified straight skeleton) for Smart Inset.

No bpy imports — unit-testable with plain pytest. Outer loops CCW,
holes CW; inward edge normal is the left normal of the edge direction.
A wavefront vertex with velocity V keeps perpendicular distance w_i*t
from each incident edge line i (weighted even offset).
"""
import math
import heapq

EPS = 1e-9
SPEED_CAP = 1e6


def sub(a, b):
    return (a[0] - b[0], a[1] - b[1])


def add(a, b):
    return (a[0] + b[0], a[1] + b[1])


def mul(a, s):
    return (a[0] * s, a[1] * s)


def dot(a, b):
    return a[0] * b[0] + a[1] * b[1]


def cross(a, b):
    return a[0] * b[1] - a[1] * b[0]


def norm(a):
    return math.hypot(a[0], a[1])


def normalize(a):
    l = norm(a)
    if l < EPS:
        return (0.0, 0.0)
    return (a[0] / l, a[1] / l)


def edge_normal(a, b):
    """Inward (left) normal of edge a->b for a CCW loop."""
    d = normalize(sub(b, a))
    return (-d[1], d[0])


def vertex_velocity(n_prev, n_next, w_prev=1.0, w_next=1.0):
    """Solve n_prev.V = w_prev, n_next.V = w_next (2x2 linear system).

    Degenerate cases:
    - collinear same-direction normals (straight vertex): V = n * w
    - near-opposite normals (spike): bisector direction capped at SPEED_CAP
    """
    det = cross(n_prev, n_next)
    if abs(det) < EPS:
        if dot(n_prev, n_next) > 0.0:
            # straight vertex — average weights on the shared normal
            return mul(n_prev, 0.5 * (w_prev + w_next))
        # spike: bisector is ill-defined; move along the (near-)shared
        # tangent capped hard so event math stays finite
        b = normalize(add(n_prev, n_next))
        if norm(b) < EPS:
            b = normalize((-n_prev[1], n_prev[0]))
        return mul(b, SPEED_CAP)
    vx = (w_prev * n_next[1] - w_next * n_prev[1]) / det
    vy = (w_next * n_prev[0] - w_prev * n_next[0]) / det
    v = (vx, vy)
    if norm(v) > SPEED_CAP:
        v = mul(normalize(v), SPEED_CAP)
    return v
