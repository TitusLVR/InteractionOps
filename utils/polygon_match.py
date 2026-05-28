"""Polygon-group shape descriptors and geometric helpers for the object
aligner's polygon-reference mode.

The numpy-only functions (signature, pca_ratios, pca_frame, d2_histogram,
kabsch_with_scale, greedy_correspondence) carry no bpy dependency and are
unit-tested with pytest. The bmesh-dependent helpers (face_island,
similar_by_normal_area, components_in_selection) live below the
`# --- bmesh helpers ---` divider and run inside Blender only.
"""
from __future__ import annotations

from dataclasses import dataclass
from collections import Counter
from typing import Iterable, Sequence

import numpy as np


@dataclass(frozen=True)
class Signature:
    """Strict-tier shape fingerprint for a polygon selection.

    `face_vcount_hist` is a sorted tuple of (vertex_count, frequency) pairs so
    equality compares as multisets regardless of insertion order.
    """
    vert_count: int
    face_count: int
    face_vcount_hist: tuple[tuple[int, int], ...]
    bbox_diag: float


def signature(world_verts: np.ndarray, faces: Sequence[Sequence[int]]) -> Signature:
    """Compute a shape signature from world-space vertices and face index lists.

    `world_verts` is Nx3. `faces` is a sequence of vertex-index sequences (each
    may be of any length >= 3)."""
    counts = Counter(len(f) for f in faces)
    hist = tuple(sorted(counts.items()))
    if world_verts.size == 0:
        diag = 0.0
    else:
        mn = world_verts.min(axis=0)
        mx = world_verts.max(axis=0)
        diag = float(np.linalg.norm(mx - mn))
    return Signature(
        vert_count=int(world_verts.shape[0]),
        face_count=len(faces),
        face_vcount_hist=hist,
        bbox_diag=diag,
    )


def pca_ratios(world_verts: np.ndarray) -> tuple[float, float, float]:
    """Normalized eigenvalues (sorted descending, sum=1) of the centered point
    cloud's covariance matrix. Invariant under translation and rotation.

    For degenerate clouds (<3 points or co-linear) returns a triple that sums
    to 1 with zeros for the absent axes."""
    if world_verts.shape[0] < 2:
        return (1.0, 0.0, 0.0)
    centered = world_verts - world_verts.mean(axis=0)
    cov = (centered.T @ centered) / max(world_verts.shape[0] - 1, 1)
    # Symmetric matrix → eigh.
    eigvals = np.linalg.eigvalsh(cov)
    eigvals = np.clip(eigvals, 0.0, None)            # numerical floor
    eigvals = np.sort(eigvals)[::-1]
    s = float(eigvals.sum())
    if s <= 0.0:
        return (1.0, 0.0, 0.0)
    r = eigvals / s
    return (float(r[0]), float(r[1]), float(r[2]))
