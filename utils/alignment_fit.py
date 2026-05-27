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
