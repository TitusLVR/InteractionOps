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
from typing import Sequence

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


def pca_frame(
    world_verts: np.ndarray,
    face_centroids: np.ndarray,
    face_normals: np.ndarray,
    face_areas: np.ndarray,
) -> np.ndarray:
    """Build an orthonormal frame (4x4 matrix) for a polygon selection.

    - origin: area-weighted centroid of `face_centroids`.
    - Z: normalized sum of (face_normal * face_area).
    - X: principal PCA axis of `world_verts` projected onto plane perp to Z,
         renormalized. Degenerate cases fall back to the second/third PCA axis,
         then to any vector orthogonal to Z.
    - Y: Z × X.

    Inputs are NumPy arrays in world space."""
    total_area = float(face_areas.sum())
    if total_area <= 0.0:
        origin = face_centroids.mean(axis=0) if face_centroids.size else np.zeros(3)
    else:
        origin = (face_centroids * face_areas[:, None]).sum(axis=0) / total_area

    z_raw = (face_normals * face_areas[:, None]).sum(axis=0)
    nz = np.linalg.norm(z_raw)
    if nz < 1e-9:
        z = np.array([0.0, 0.0, 1.0])
    else:
        z = z_raw / nz

    # PCA eigenvectors of centered verts (descending eigenvalue).
    if world_verts.shape[0] >= 2:
        centered = world_verts - world_verts.mean(axis=0)
        cov = (centered.T @ centered) / max(world_verts.shape[0] - 1, 1)
        eigvals, eigvecs = np.linalg.eigh(cov)        # ascending
        order = np.argsort(eigvals)[::-1]
        axes = eigvecs[:, order].T                    # rows = axes, descending λ
    else:
        axes = np.eye(3)

    x = None
    for axis in axes:
        proj = axis - np.dot(axis, z) * z
        n = np.linalg.norm(proj)
        if n >= 1e-4:
            x = proj / n
            break
    if x is None:
        # Last resort: any vector orthogonal to z.
        helper = np.array([1.0, 0.0, 0.0]) if abs(z[0]) < 0.9 else np.array([0.0, 1.0, 0.0])
        x = helper - np.dot(helper, z) * z
        x = x / np.linalg.norm(x)

    y = np.cross(z, x)

    m = np.eye(4)
    m[:3, 0] = x
    m[:3, 1] = y
    m[:3, 2] = z
    m[:3, 3] = origin
    return m
