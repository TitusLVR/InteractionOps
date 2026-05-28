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

from .alignment_fit import solve_fit


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


def kabsch_with_scale(
    ref_pts: np.ndarray,
    tgt_pts: np.ndarray,
    scale_mode: str = "KEEP",
) -> tuple[np.ndarray, float]:
    """Wrap `utils.alignment_fit.solve_fit` and additionally return RMSE.

    Returns (T_4x4, rmse) where T transforms ref_pts -> tgt_pts in homogeneous
    coordinates, and rmse is the residual root-mean-square distance between
    transformed-ref and tgt after the fit. Both arrays must have the same
    length (point-to-point correspondence assumed)."""
    T = solve_fit(ref_pts, tgt_pts, scale_mode)
    homog = np.hstack([ref_pts, np.ones((ref_pts.shape[0], 1))])
    transformed = (homog @ T.T)[:, :3]
    diff = transformed - tgt_pts
    rmse = float(np.sqrt(np.mean(np.sum(diff * diff, axis=1))))
    return T, rmse


def greedy_correspondence(ref_pts: np.ndarray, tgt_pts: np.ndarray) -> np.ndarray:
    """Pair each ref point with a unique tgt point, seeded by a PCA-frame
    pre-alignment. Returns a permutation array `corr` where tgt[corr] is the
    reordered target matching ref.

    Algorithm: pre-align ref to tgt via centroid-translate + axis-match using
    PCA orientations, then for each pre-aligned ref point assign nearest unused
    tgt point greedily (sorted by distance to its nearest tgt, so unambiguous
    pairs claim first).

    Assumes len(ref_pts) == len(tgt_pts)."""
    n = ref_pts.shape[0]
    if tgt_pts.shape[0] != n:
        raise ValueError("ref and tgt must have equal length")

    # PCA pre-alignment: centroid translate + rotation that aligns PCA axes.
    ref_c = ref_pts.mean(axis=0)
    tgt_c = tgt_pts.mean(axis=0)
    ref_centered = ref_pts - ref_c
    tgt_centered = tgt_pts - tgt_c

    def _axes(pts):
        cov = (pts.T @ pts) / max(pts.shape[0] - 1, 1)
        eigvals, eigvecs = np.linalg.eigh(cov)
        order = np.argsort(eigvals)[::-1]
        return eigvecs[:, order]

    Ar = _axes(ref_centered)
    At = _axes(tgt_centered)
    R = At @ Ar.T                                     # rotates ref-axes onto tgt-axes
    if np.linalg.det(R) < 0:                          # avoid reflection
        At[:, 2] *= -1
        R = At @ Ar.T
    pre_aligned = ref_centered @ R.T + tgt_c

    # Distance matrix (n is small in practice -- single polys to a few hundred).
    diff = pre_aligned[:, None, :] - tgt_pts[None, :, :]
    dists = np.linalg.norm(diff, axis=2)              # n x n

    # Greedy: sort ref by its min distance, claim nearest unused tgt.
    order = np.argsort(dists.min(axis=1))
    used = np.zeros(n, dtype=bool)
    corr = np.full(n, -1, dtype=np.int64)
    for ri in order:
        candidates = np.argsort(dists[ri])
        for ti in candidates:
            if not used[ti]:
                corr[ri] = int(ti)
                used[ti] = True
                break
    return corr


def d2_histogram(
    world_verts: np.ndarray,
    faces: Sequence[Sequence[int]],
    samples: int = 512,
    bins: int = 32,
    seed: int = 0,
) -> np.ndarray:
    """D2 shape distribution (Osada 2002). Sample points uniformly on the
    surface (face-area-weighted), compute pairwise distances of `samples//2`
    random pairs, normalize by bbox diagonal, histogram into `bins`. Returns a
    normalized histogram (sums to 1) of shape (bins,).

    Triangulates n-gons into a fan from the first vertex (good enough for
    sampling — D2 is a statistical descriptor, exact triangulation choice
    contributes negligibly with `samples >= 256`)."""
    if world_verts.shape[0] == 0 or not faces:
        return np.zeros(bins, dtype=np.float64)

    rng = np.random.default_rng(seed)

    # Triangulate fan.
    tri_indices = []
    for f in faces:
        for i in range(1, len(f) - 1):
            tri_indices.append((f[0], f[i], f[i + 1]))
    tris = np.array(tri_indices, dtype=np.int64)
    if tris.shape[0] == 0:
        return np.zeros(bins, dtype=np.float64)

    a = world_verts[tris[:, 0]]
    b = world_verts[tris[:, 1]]
    c = world_verts[tris[:, 2]]
    areas = 0.5 * np.linalg.norm(np.cross(b - a, c - a), axis=1)
    total = float(areas.sum())
    if total <= 0.0:
        return np.zeros(bins, dtype=np.float64)
    probs = areas / total

    # Pick triangles for `samples` points, then barycentric.
    tri_choice = rng.choice(tris.shape[0], size=samples, p=probs)
    u = rng.random(samples)
    v = rng.random(samples)
    flip = u + v > 1.0
    u[flip] = 1.0 - u[flip]
    v[flip] = 1.0 - v[flip]
    w = 1.0 - u - v
    pts = (a[tri_choice] * u[:, None]
           + b[tri_choice] * v[:, None]
           + c[tri_choice] * w[:, None])

    # Pair up points randomly for distances.
    pairs = samples // 2
    idx = rng.permutation(samples)
    p1 = pts[idx[:pairs]]
    p2 = pts[idx[pairs:2 * pairs]]
    d = np.linalg.norm(p1 - p2, axis=1)

    # Normalize by bbox diag.
    mn = world_verts.min(axis=0)
    mx = world_verts.max(axis=0)
    diag = float(np.linalg.norm(mx - mn))
    if diag <= 0.0:
        return np.zeros(bins, dtype=np.float64)
    d_norm = np.clip(d / diag, 0.0, 1.0)
    hist, _ = np.histogram(d_norm, bins=bins, range=(0.0, 1.0))
    s = hist.sum()
    if s == 0:
        return np.zeros(bins, dtype=np.float64)
    return hist.astype(np.float64) / float(s)
