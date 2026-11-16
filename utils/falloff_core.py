"""Pure-numpy falloff math (no bpy) so pytest can cover it.

Weights are floats in [0, 1]: 1 = fully affected, 0 = untouched.
Every function takes and returns numpy arrays; `P` is (N, 3) world-space
coordinates, `W` is (N,).

A falloff is a stack of plain-data fields (dicts with keys type, start, end,
radii, roll, curve, invert, strength, blend, enabled). `field_weight` turns one
field into weights, `stack_weights` blends the enabled fields top to bottom.
The core never sees bpy: operators snapshot property groups into these dicts.

Shape curves and formulas follow Blender's proportional-editing table
(source/blender/editors/transform/transform_generics.cc), minus RANDOM.
"""
from __future__ import annotations

import numpy as np

FALLOFF_TYPES = ("LINEAR", "RADIAL", "ELLIPTICAL", "BIDIRECTIONAL")
BLEND_MODES = ("REPLACE", "ADD", "SUBTRACT", "MULTIPLY", "MIN", "MAX")
FIT_MODES = ("PCA", "X", "Y", "Z")
SHAPES = ("LINEAR", "SMOOTH", "SHARP", "ROOT", "SPHERE", "INVERSE_SQUARE",
          "CONSTANT")

EPS = 1e-9
MIN_SIZE = 1e-4


# ---------------------------------------------------------------- shapes

def _shape_linear(x):
    return x


def _shape_smooth(x):
    return x * x * (3.0 - 2.0 * x)


def _shape_sharp(x):
    return x * x


def _shape_root(x):
    return np.sqrt(x)


def _shape_sphere(x):
    return np.sqrt(np.clip(2.0 * x - x * x, 0.0, 1.0))


def _shape_inverse_square(x):
    return x * (2.0 - x)


def _shape_constant(x):
    return np.ones_like(x)


_SHAPE_FN = {
    "LINEAR": _shape_linear,
    "SMOOTH": _shape_smooth,
    "SHARP": _shape_sharp,
    "ROOT": _shape_root,
    "SPHERE": _shape_sphere,
    "INVERSE_SQUARE": _shape_inverse_square,
    "CONSTANT": _shape_constant,
}


def shape_curve(name: str, x: np.ndarray) -> np.ndarray:
    """Apply the named shape to raw weights. Clamps input to [0, 1].
    Raises KeyError for an unknown name."""
    fn = _SHAPE_FN[name]
    xc = np.clip(np.asarray(x, dtype=np.float64), 0.0, 1.0)
    return np.clip(fn(xc), 0.0, 1.0)


def apply_invert(w: np.ndarray) -> np.ndarray:
    return 1.0 - np.asarray(w, dtype=np.float64)



# ---------------------------------------------------------------- weights

def _axis_t(P, S, E):
    """Projection parameter of each point on S->E (0 at S, 1 at E), or None
    for a degenerate axis."""
    P = np.asarray(P, dtype=np.float64)
    S = np.asarray(S, dtype=np.float64)
    d = np.asarray(E, dtype=np.float64) - S
    L2 = float(d @ d)
    if L2 < EPS:
        return None
    return ((P - S) @ d) / L2


def weight_linear(P: np.ndarray, S, E) -> np.ndarray:
    """0 at Start, 1 at End, linear in between, clamped beyond either.
    A degenerate axis (S == E) gives full weight everywhere."""
    t = _axis_t(P, S, E)
    if t is None:
        return np.ones(np.asarray(P).shape[0], dtype=np.float64)
    return np.clip(t, 0.0, 1.0)


def weight_bidirectional(P: np.ndarray, S, E) -> np.ndarray:
    """0 at both Start and End, 1 at the midpoint. Degenerate axis -> ones."""
    t = _axis_t(P, S, E)
    if t is None:
        return np.ones(np.asarray(P).shape[0], dtype=np.float64)
    return 1.0 - np.abs(2.0 * np.clip(t, 0.0, 1.0) - 1.0)


def weight_radial(P: np.ndarray, C, r: float) -> np.ndarray:
    """1 at the centre, 0 at distance r and beyond."""
    P = np.asarray(P, dtype=np.float64)
    C = np.asarray(C, dtype=np.float64)
    dist = np.linalg.norm(P - C, axis=1)
    if r < EPS:
        return (dist < EPS).astype(np.float64)
    return 1.0 - np.clip(dist / r, 0.0, 1.0)


def ellipsoid_frame(start, end, radii2, roll: float):
    """(axes (3,3) with columns = frame axes, radii (3,)). Axis 0 runs
    start->end, axes 1 and 2 are perpendicular to it and rotated by `roll`
    radians about it; radii = (|end - start|, radii2[0], radii2[1]), each
    floored at MIN_SIZE."""
    s = np.asarray(start, dtype=np.float64)
    e = np.asarray(end, dtype=np.float64)
    d = e - s
    B = basis_from_normal(d)                     # columns X, Y, Z with Z along d
    a0, a1, a2 = B[:, 2], B[:, 0], B[:, 1]       # a0 x a1 == a2
    c, sn = np.cos(roll), np.sin(roll)
    axes = np.stack([a0, a1 * c + a2 * sn, -a1 * sn + a2 * c], axis=1)
    radii = np.maximum(
        np.array([np.linalg.norm(d), float(radii2[0]), float(radii2[1])]),
        MIN_SIZE)
    return axes, radii


def weight_elliptical(P: np.ndarray, C, axes, radii) -> np.ndarray:
    """1 at the centre C, falling to 0 on the ellipsoid surface
    (|local / radii| = 1); local coordinates are taken in `axes`."""
    P = np.asarray(P, dtype=np.float64)
    C = np.asarray(C, dtype=np.float64)
    local = (P - C) @ np.asarray(axes, dtype=np.float64)
    q = np.linalg.norm(local / np.asarray(radii, dtype=np.float64), axis=1)
    return 1.0 - np.clip(q, 0.0, 1.0)


def field_weight(P: np.ndarray, field: dict) -> np.ndarray:
    """Weights of one field: geometry -> curve -> invert."""
    ftype = field["type"]
    s = np.asarray(field["start"], dtype=np.float64)
    e = np.asarray(field["end"], dtype=np.float64)
    if ftype == "LINEAR":
        t = weight_linear(P, s, e)
    elif ftype == "BIDIRECTIONAL":
        t = weight_bidirectional(P, s, e)
    elif ftype == "RADIAL":
        t = weight_radial(P, s, max(float(np.linalg.norm(e - s)), MIN_SIZE))
    elif ftype == "ELLIPTICAL":
        axes, radii = ellipsoid_frame(s, e, field["radii"], field["roll"])
        t = weight_elliptical(P, s, axes, radii)
    else:
        raise KeyError(ftype)
    w = shape_curve(field["curve"], t)
    if field["invert"]:
        w = apply_invert(w)
    return w


def stack_weights(P: np.ndarray, stack: list) -> np.ndarray:
    """Blend the enabled fields top to bottom. No enabled field -> ones."""
    w = None
    for f in stack:
        if not f["enabled"]:
            continue
        st = float(f["strength"])
        s = st * field_weight(P, f)
        if w is None:
            w = s
        else:
            b = f["blend"]
            if b == "REPLACE":
                w = s
            elif b == "ADD":
                w = w + s
            elif b == "SUBTRACT":
                w = w - s
            elif b == "MULTIPLY":
                w = w * (1.0 - st + s)
            elif b == "MIN":
                w = np.minimum(w, s)
            elif b == "MAX":
                w = np.maximum(w, s)
            else:
                raise KeyError(b)
        w = np.clip(w, 0.0, 1.0)
    if w is None:
        return np.ones(np.asarray(P).shape[0], dtype=np.float64)
    return w


# ---------------------------------------------------------------- fits

def bbox_center(P: np.ndarray) -> np.ndarray:
    P = np.asarray(P, dtype=np.float64)
    return (P.min(axis=0) + P.max(axis=0)) * 0.5


def _axis_dir(P: np.ndarray, mode: str) -> np.ndarray:
    if mode in ("X", "Y", "Z"):
        d = np.zeros(3)
        d["XYZ".index(mode)] = 1.0
        return d
    P = np.asarray(P, dtype=np.float64)
    if P.shape[0] < 2 or float((P.max(axis=0) - P.min(axis=0)).max()) < 1e-9:
        return _axis_dir(P, "X")
    _, sv, vt = np.linalg.svd(P - P.mean(axis=0), full_matrices=False)
    if sv[0] < 1e-12:
        return _axis_dir(P, "X")
    d = vt[0]
    if d[int(np.argmax(np.abs(d)))] < 0.0:
        d = -d
    return d


# An axis along which the points spread less than this fraction of their
# largest bbox extent counts as having no extent (Fit Z on a flat selection).
DEGENERATE_EXTENT = 1e-3
# A fitted ellipsoid radius along a degenerate axis (see DEGENERATE_EXTENT)
# is floored at this fraction of the largest radius.
RADIUS_FLOOR = 0.25


def fit_axis(P: np.ndarray, mode: str):
    """(S, E) through the bbox centre along the PCA / X / Y / Z direction,
    at the extents of the points' projection onto it.

    An axis with (near) zero extent would give a zero-length field; it gets
    a usable one instead: centred on the bbox centre, as long as the
    largest bbox extent (at least MIN_SIZE)."""
    P = np.asarray(P, dtype=np.float64)
    c = bbox_center(P)
    d = _axis_dir(P, mode)
    proj = (P - c) @ d
    lo, hi = float(proj.min()), float(proj.max())
    largest = float((P.max(axis=0) - P.min(axis=0)).max())
    if hi - lo < max(MIN_SIZE, DEGENERATE_EXTENT * largest):
        half = 0.5 * max(largest, MIN_SIZE)
        return c - d * half, c + d * half
    return c + d * lo, c + d * hi


def fit_field(P: np.ndarray, ftype: str, mode: str) -> dict:
    """Geometry keys (start, end, radii, roll) fitted to the points."""
    P = np.asarray(P, dtype=np.float64)
    if ftype in ("LINEAR", "BIDIRECTIONAL"):
        S, E = fit_axis(P, mode)
        return dict(start=S, end=E, radii=(1.0, 1.0), roll=0.0)
    c = bbox_center(P)
    d = _axis_dir(P, mode)
    if ftype == "RADIAL":
        half_diag = max(0.5 * float(np.linalg.norm(P.max(axis=0) - P.min(axis=0))),
                        MIN_SIZE)
        return dict(start=c, end=c + d * half_diag, radii=(1.0, 1.0), roll=0.0)
    if ftype == "ELLIPTICAL":
        axes, _ = ellipsoid_frame(c, c + d, (1.0, 1.0), 0.0)
        proj = (P - c) @ axes
        ext = proj.max(axis=0) - proj.min(axis=0)
        half = np.maximum(0.5 * ext, MIN_SIZE)
        # a flat selection must not collapse the ellipsoid to a disc: only the
        # axes with (near) zero extent get the floor, as in fit_axis
        degenerate = ext < max(MIN_SIZE, DEGENERATE_EXTENT * float(ext.max()))
        half = np.where(degenerate,
                        np.maximum(half, RADIUS_FLOOR * float(half.max())), half)
        return dict(start=c, end=c + d * half[0],
                    radii=(float(half[1]), float(half[2])), roll=0.0)
    raise KeyError(ftype)


def apply_normal_offset(P0: np.ndarray, W: np.ndarray, N: np.ndarray, d: float) -> np.ndarray:
    """P0 + W * d * N (move each point along its normal by a weighted amount)."""
    P0 = np.asarray(P0, dtype=np.float64)
    W = np.asarray(W, dtype=np.float64)[:, None]
    return P0 + W * float(d) * np.asarray(N, dtype=np.float64)


# ---------------------------------------------------------------- apply

def apply_move(P0: np.ndarray, W: np.ndarray, delta) -> np.ndarray:
    P0 = np.asarray(P0, dtype=np.float64)
    W = np.asarray(W, dtype=np.float64)[:, None]
    d = np.asarray(delta, dtype=np.float64)
    return P0 + W * d


def apply_rotate(P0: np.ndarray, W: np.ndarray, pivot, axis, angle: float) -> np.ndarray:
    """Rotate each vertex about `axis` through `pivot` by `W_i * angle`
    (Rodrigues). A zero-length axis returns a copy of P0."""
    P0 = np.asarray(P0, dtype=np.float64)
    W = np.asarray(W, dtype=np.float64)
    C = np.asarray(pivot, dtype=np.float64)
    k = np.asarray(axis, dtype=np.float64)
    kl = np.linalg.norm(k)
    if kl < EPS:
        return P0.copy()
    k = k / kl
    v = P0 - C
    th = W * float(angle)
    c = np.cos(th)[:, None]
    s = np.sin(th)[:, None]
    kxv = np.cross(k, v)
    kdv = (v @ k)[:, None]
    return C + v * c + kxv * s + k * kdv * (1.0 - c)


def apply_scale(P0: np.ndarray, W: np.ndarray, pivot, s, basis=None) -> np.ndarray:
    """pivot + (1 + W (s - 1)) (P0 - pivot); `s` scalar or per-axis (3,).
    `basis` (3,3, orthonormal columns = axes in P0's space) makes a per-axis
    `s` act along those axes instead of the coordinate axes."""
    P0 = np.asarray(P0, dtype=np.float64)
    W = np.asarray(W, dtype=np.float64)[:, None]
    C = np.asarray(pivot, dtype=np.float64)
    sv = np.asarray(s, dtype=np.float64)
    if sv.ndim == 0:
        sv = np.full(3, float(sv))
    v = P0 - C
    if basis is None:
        return C + (1.0 + W * (sv - 1.0)) * v
    R = np.asarray(basis, dtype=np.float64)
    vb = v @ R                       # coordinates in the basis (columns = axes)
    vb = (1.0 + W * (sv - 1.0)) * vb
    return C + vb @ R.T


def basis_from_normal(normal, tangent=None) -> np.ndarray:
    """Orthonormal (3,3) with columns X, Y, Z where Z = normalised `normal`,
    X = `tangent` made perpendicular to Z (an arbitrary perpendicular when
    `tangent` is None or parallel), Y = Z × X. Identity for a zero normal."""
    n = np.asarray(normal, dtype=np.float64)
    nl = np.linalg.norm(n)
    if nl < EPS:
        return np.eye(3)
    z = n / nl
    x = None
    if tangent is not None:
        t = np.asarray(tangent, dtype=np.float64)
        t = t - z * float(t @ z)
        if np.linalg.norm(t) > 1e-6:
            x = t / np.linalg.norm(t)
    if x is None:
        helper = np.array([1.0, 0.0, 0.0]) if abs(z[0]) < 0.9 else np.array([0.0, 1.0, 0.0])
        x = np.cross(helper, z)
        x = x / np.linalg.norm(x)
    y = np.cross(z, x)
    return np.stack([x, y, z], axis=1)
