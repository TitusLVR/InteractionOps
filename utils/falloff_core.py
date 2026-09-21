"""Pure-numpy falloff math (no bpy) so pytest can cover it.

Weights are floats in [0, 1]: 1 = fully affected, 0 = untouched.
Every function takes and returns numpy arrays; `P` is (N, 3) object-space
coordinates, `W` is (N,).

Shape curves and formulas follow Blender's proportional-editing table
(source/blender/editors/transform/transform_generics.cc), minus RANDOM.
"""
from __future__ import annotations

from collections import deque

import numpy as np

FALLOFF_TYPES = ("LINEAR", "RADIAL", "SCREEN", "COPLANAR")
SHAPES = ("LINEAR", "SMOOTH", "SHARP", "ROOT", "SPHERE", "INVERSE_SQUARE",
          "CONSTANT")

EPS = 1e-9


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

def weight_linear(P: np.ndarray, S, E) -> np.ndarray:
    """1 at Start, 0 at End, linear in between, clamped beyond either.
    A degenerate axis (S == E) gives full weight everywhere."""
    P = np.asarray(P, dtype=np.float64)
    S = np.asarray(S, dtype=np.float64)
    E = np.asarray(E, dtype=np.float64)
    d = E - S
    L2 = float(d @ d)
    if L2 < EPS:
        return np.ones(P.shape[0], dtype=np.float64)
    t = ((P - S) @ d) / L2
    return 1.0 - np.clip(t, 0.0, 1.0)


def weight_radial(P: np.ndarray, C, r: float) -> np.ndarray:
    """1 at the centre, 0 at distance r and beyond."""
    P = np.asarray(P, dtype=np.float64)
    C = np.asarray(C, dtype=np.float64)
    dist = np.linalg.norm(P - C, axis=1)
    if r < EPS:
        return (dist < EPS).astype(np.float64)
    return 1.0 - np.clip(dist / r, 0.0, 1.0)


def weight_screen(P2: np.ndarray, center2, r_px: float,
                  valid: np.ndarray | None = None) -> np.ndarray:
    """Screen-space disc. `P2` are region pixel coords; rows where `valid`
    is False (behind the camera) get 0."""
    P2 = np.asarray(P2, dtype=np.float64)
    c = np.asarray(center2, dtype=np.float64)
    dist = np.linalg.norm(P2 - c, axis=1)
    if r_px < EPS:
        w = (dist < EPS).astype(np.float64)
    else:
        w = 1.0 - np.clip(dist / r_px, 0.0, 1.0)
    if valid is not None:
        w = np.where(np.asarray(valid, dtype=bool), w, 0.0)
    return w


def project_points(Pw: np.ndarray, persp: np.ndarray, width: int,
                   height: int) -> tuple[np.ndarray, np.ndarray]:
    """World → region pixels through a 4x4 world-to-clip matrix (Blender's
    `rv3d.perspective_matrix`). Returns (P2 (N,2), valid (N,)). Rows with
    clip w <= 0 are invalid; their pixel coords are set to 0 (finite)."""
    Pw = np.asarray(Pw, dtype=np.float64)
    M = np.asarray(persp, dtype=np.float64)
    n = Pw.shape[0]
    Ph = np.concatenate([Pw, np.ones((n, 1))], axis=1)
    clip = Ph @ M.T
    w = clip[:, 3]
    valid = w > EPS
    w_safe = np.where(valid, w, 1.0)
    ndc = clip[:, :2] / w_safe[:, None]
    px = np.empty((n, 2), dtype=np.float64)
    px[:, 0] = (ndc[:, 0] + 1.0) * 0.5 * float(width)
    px[:, 1] = (ndc[:, 1] + 1.0) * 0.5 * float(height)
    px[~valid] = 0.0
    return px, valid


# ---------------------------------------------------------------- coplanar

def weight_coplanar_faces(FN: np.ndarray, n_ref, angle_rad: float) -> np.ndarray:
    """Per-face weight from the angle between each face normal and n_ref:
    1 when parallel, 0 at `angle_rad` and beyond. angle_rad == 0 keeps only
    exact (within 1e-6 rad) matches."""
    FN = np.asarray(FN, dtype=np.float64)
    n = np.asarray(n_ref, dtype=np.float64)
    nl = np.linalg.norm(n)
    if nl < EPS:
        return np.zeros(FN.shape[0], dtype=np.float64)
    n = n / nl
    fl = np.linalg.norm(FN, axis=1)
    fl = np.where(fl < EPS, 1.0, fl)
    cosang = np.clip((FN @ n) / fl, -1.0, 1.0)
    ang = np.arccos(cosang)
    if angle_rad < 1e-9:
        return (ang < 1e-6).astype(np.float64)
    return 1.0 - np.clip(ang / angle_rad, 0.0, 1.0)


def vertex_weights_from_faces(face_rows, wf: np.ndarray, n_verts: int) -> np.ndarray:
    """Vertex weight = max weight of its incident faces (0 if none)."""
    wf = np.asarray(wf, dtype=np.float64)
    out = np.zeros(n_verts, dtype=np.float64)
    for fi, rows in enumerate(face_rows):
        w = wf[fi]
        if w <= 0.0:
            continue
        for r in rows:
            if w > out[r]:
                out[r] = w
    return out


# ---------------------------------------------------------------- connectivity

def connected_mask(adj, seeds, n: int) -> np.ndarray:
    """BFS over vertex adjacency from `seeds`; True for every reached row."""
    mask = np.zeros(n, dtype=bool)
    q = deque()
    for s in seeds:
        if not mask[s]:
            mask[s] = True
            q.append(s)
    while q:
        u = q.popleft()
        for v in adj[u]:
            if not mask[v]:
                mask[v] = True
                q.append(v)
    return mask


def coplanar_grow(face_adj, wf: np.ndarray, seed_faces) -> np.ndarray:
    """BFS over face adjacency from `seed_faces`, stepping only onto faces
    with wf > 0. Seeds are always kept."""
    wf = np.asarray(wf, dtype=np.float64)
    keep = np.zeros(wf.shape[0], dtype=bool)
    q = deque()
    for s in seed_faces:
        if not keep[s]:
            keep[s] = True
            q.append(s)
    while q:
        u = q.popleft()
        for f in face_adj[u]:
            if not keep[f] and wf[f] > 0.0:
                keep[f] = True
                q.append(f)
    return keep


# ---------------------------------------------------------------- autofit

def bbox_center(P: np.ndarray) -> np.ndarray:
    P = np.asarray(P, dtype=np.float64)
    return (P.min(axis=0) + P.max(axis=0)) * 0.5


def autofit_linear(P: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Start/End along the longest bbox axis through the bbox centre.
    Degenerate extent → E = S + (1, 0, 0)."""
    P = np.asarray(P, dtype=np.float64)
    mn = P.min(axis=0)
    mx = P.max(axis=0)
    ext = mx - mn
    axis = int(np.argmax(ext))
    c = (mn + mx) * 0.5
    S = c.copy()
    E = c.copy()
    if ext[axis] < 1e-6:
        E[0] += 1.0
        return S, E
    S[axis] = mn[axis]
    E[axis] = mx[axis]
    return S, E


def autofit_radial(P: np.ndarray) -> tuple[np.ndarray, float]:
    P = np.asarray(P, dtype=np.float64)
    mn = P.min(axis=0)
    mx = P.max(axis=0)
    r = 0.5 * float(np.linalg.norm(mx - mn))
    return (mn + mx) * 0.5, max(r, 1e-4)


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
