"""Pure-NumPy point-set registration with known correspondence.

No bpy / mathutils import — unit-testable standalone. All functions take
Nx3 NumPy arrays of corresponding points (row i of `ref` matches row i of
`tgt`) and return transforms that map ref -> tgt.
"""
from __future__ import annotations

import numpy as np


def kabsch(ref: np.ndarray, tgt: np.ndarray):
    """Optimal rigid transform (rotation + translation), least squares.

    Returns (R, t): a 3x3 rotation (det = +1, reflections suppressed) and a
    length-3 translation such that ``tgt ≈ ref @ R.T + t``.
    """
    ref = np.asarray(ref, dtype=np.float64)
    tgt = np.asarray(tgt, dtype=np.float64)
    cen_ref = ref.mean(axis=0)
    cen_tgt = tgt.mean(axis=0)
    x = ref - cen_ref
    y = tgt - cen_tgt
    h = x.T @ y
    u, _s, vt = np.linalg.svd(h)
    d = np.sign(np.linalg.det(vt.T @ u.T))
    correction = np.diag([1.0, 1.0, d])
    r = vt.T @ correction @ u.T
    t = cen_tgt - r @ cen_ref
    return r, t


def umeyama(ref: np.ndarray, tgt: np.ndarray):
    """Optimal similarity transform (rotation + translation + uniform scale).

    Umeyama (1991). Returns (R, t, s) such that ``tgt ≈ s * (ref @ R.T) + t``.
    Reflections are suppressed (det R = +1).
    """
    ref = np.asarray(ref, dtype=np.float64)
    tgt = np.asarray(tgt, dtype=np.float64)
    n = ref.shape[0]
    cen_ref = ref.mean(axis=0)
    cen_tgt = tgt.mean(axis=0)
    x = ref - cen_ref
    y = tgt - cen_tgt
    cov = (y.T @ x) / n
    u, s_vals, vt = np.linalg.svd(cov)
    d = np.sign(np.linalg.det(u @ vt))
    correction = np.diag([1.0, 1.0, d])
    r = u @ correction @ vt
    var_ref = (x ** 2).sum() / n
    scale = float(np.trace(np.diag(s_vals) @ correction) / var_ref) if var_ref > 1e-12 else 1.0
    t = cen_tgt - scale * (r @ cen_ref)
    return r, t, scale
