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


def kabsch_mirror_with_scale(
    ref_pts: np.ndarray,
    tgt_pts: np.ndarray,
    scale_mode: str = "KEEP",
) -> tuple[np.ndarray, float]:
    """Procrustes alignment that ALLOWS reflection (det may be -1).

    Used to detect mirrored target groups: a mirrored copy of `ref_pts` will
    yield a near-zero RMSE here even though `kabsch_with_scale` (which forces
    det=+1) reports a high residual. Same inputs/outputs as
    `kabsch_with_scale`: returns (T_4x4, rmse).

    `scale_mode` in {"KEEP", "UNIFORM", "STRETCH"} mirrors the semantics of
    `utils.alignment_fit.solve_fit`. For STRETCH (per-axis scale), the mirror
    determinant is naturally folded into the diagonal — so the dedicated
    mirror branch only applies for KEEP/UNIFORM."""
    if ref_pts.shape != tgt_pts.shape:
        raise ValueError("ref and tgt must have the same shape")
    n = ref_pts.shape[0]
    if n == 0:
        return np.eye(4), 0.0

    ref_c = ref_pts.mean(axis=0)
    tgt_c = tgt_pts.mean(axis=0)
    P = ref_pts - ref_c
    Q = tgt_pts - tgt_c

    if scale_mode == "STRETCH":
        # Affine fit per axis — already handles reflection in the diagonal.
        # Delegate to solve_fit for consistency.
        T = solve_fit(ref_pts, tgt_pts, scale_mode)
    else:
        # SVD-based Procrustes WITHOUT the det>0 fix.
        H = P.T @ Q                                  # 3x3 covariance
        U, _S, Vt = np.linalg.svd(H)
        R = (Vt.T @ U.T)                             # det may be ±1

        scale = 1.0
        if scale_mode == "UNIFORM":
            # Uniform scale recovered from the trace of (R @ H).
            num = float(np.trace(R @ H))
            den = float(np.sum(P * P))
            scale = num / den if den > 1e-12 else 1.0

        t = tgt_c - scale * R @ ref_c

        T = np.eye(4)
        T[:3, :3] = scale * R
        T[:3, 3] = t

    homog = np.hstack([ref_pts, np.ones((ref_pts.shape[0], 1))])
    transformed = (homog @ T.T)[:, :3]
    diff = transformed - tgt_pts
    rmse = float(np.sqrt(np.mean(np.sum(diff * diff, axis=1))))
    return T, rmse


@dataclass(frozen=True)
class Candidate:
    """One per-component pattern match on a target mesh.

    - faces: matched face indices in the sub-pattern's canonical order.
    - centroid: mean of `anchors` (world space) — the component's anchor point
      used for arrangement prediction.
    - anchors: (2*len(faces), 3) world-space anchor cloud for the matched faces,
      in the same order `_face_anchor_points` emits them.
    """
    faces: tuple
    centroid: np.ndarray
    anchors: np.ndarray


def _apply_affine(T: np.ndarray, pt: np.ndarray) -> np.ndarray:
    """Apply a 4x4 affine matrix to a single 3D point."""
    h = np.array([pt[0], pt[1], pt[2], 1.0])
    return (T @ h)[:3]


def _compose_srt(R: np.ndarray, cen_ref: np.ndarray, cen_tgt: np.ndarray,
                 scale: float) -> np.ndarray:
    """4x4 homogeneous matrix for tgt ≈ scale * (ref @ R.T) + t about centroids."""
    T = np.eye(4)
    T[:3, :3] = scale * R
    T[:3, 3] = cen_tgt - scale * (R @ cen_ref)
    return T


def _fit_rmse(ref: np.ndarray, tgt: np.ndarray, T: np.ndarray) -> float:
    """RMS residual after mapping `ref` through `T` and comparing to `tgt`."""
    homog = np.hstack([ref, np.ones((ref.shape[0], 1))])
    diff = (homog @ T.T)[:, :3] - tgt
    return float(np.sqrt(np.mean(np.sum(diff * diff, axis=1))))


def fit_both(ref_pts: np.ndarray, tgt_pts: np.ndarray,
             scale_mode: str = "KEEP") -> tuple[np.ndarray, float, bool]:
    """Fit ref_pts -> tgt_pts, returning whichever of the proper-rotation and
    reflection-allowing Procrustes fits has the lower RMSE.

    Returns (T_4x4, rmse, is_mirror). `is_mirror` is True when the reflection
    variant won.

    Both orientations share one covariance SVD (H = Pᵀ·Q): the proper fit
    applies the det-correction diag(1,1,d), the mirror fit omits it. This
    matches `kabsch_with_scale` + `kabsch_mirror_with_scale` exactly while
    computing a single SVD instead of two. STRETCH (affine) folds reflection
    into the per-axis scale, so its mirror fit coincides with the proper one —
    no second solve, is_mirror is always False there."""
    ref = np.asarray(ref_pts, dtype=np.float64)
    tgt = np.asarray(tgt_pts, dtype=np.float64)
    if scale_mode == "STRETCH":
        T = solve_fit(ref, tgt, "STRETCH")
        return T, _fit_rmse(ref, tgt, T), False

    cen_ref = ref.mean(axis=0)
    cen_tgt = tgt.mean(axis=0)
    P = ref - cen_ref
    Q = tgt - cen_tgt
    H = P.T @ Q
    U, S, Vt = np.linalg.svd(H)
    VtT = Vt.T
    d = np.sign(np.linalg.det(VtT @ U.T))
    d = d if d != 0.0 else 1.0
    R_proper = VtT @ np.diag([1.0, 1.0, d]) @ U.T
    R_mirror = VtT @ U.T

    denom = float((P * P).sum())
    if scale_mode == "UNIFORM" and denom > 1e-12:
        s_proper = float(S[0] + S[1] + d * S[2]) / denom
        s_mirror = float(S.sum()) / denom
    else:
        s_proper = s_mirror = 1.0

    T_proper = _compose_srt(R_proper, cen_ref, cen_tgt, s_proper)
    T_mirror = _compose_srt(R_mirror, cen_ref, cen_tgt, s_mirror)
    rmse_n = _fit_rmse(ref, tgt, T_proper)
    rmse_m = _fit_rmse(ref, tgt, T_mirror)
    if rmse_m < rmse_n:
        return T_mirror, rmse_m, True
    return T_proper, rmse_n, False


def assemble_constellations(
    ref_comp_anchors: Sequence[np.ndarray],
    ref_comp_centroids: Sequence[np.ndarray],
    ref_comp_facecount: Sequence[int],
    anchor_idx: int,
    cand_pool: Sequence[Sequence["Candidate"]],
    *,
    scale_mode: str = "KEEP",
    pos_tol: float,
    fit_rmse_rel: float,
    bbox_diag: float,
) -> list[dict]:
    """Assemble whole-constellation matches from per-component candidates.

    - ref_comp_anchors: list (len C) of (Ki, 3) reference anchor clouds, one per
      connected component, in the chosen component order.
    - ref_comp_centroids: list (len C) of (3,) reference component centroids
      (each = mean of that component's anchor cloud).
    - ref_comp_facecount: list (len C) of face counts per component.
    - anchor_idx: index of the component that seeds the hypothesis transform.
    - cand_pool: list (len C); cand_pool[j] is the list of Candidate for
      component j on a single target object.
    - pos_tol: max world-space distance between a predicted component centroid
      and a candidate centroid for that candidate to be accepted.
    - fit_rmse_rel: max (global_rmse / bbox_diag) for an assembly to survive.
    - bbox_diag: reference bbox diagonal (rmse normalizer).

    Returns a list of dicts {"order": tuple[int], "faces": frozenset[int],
    "mirror": bool, "rmse": float}, one per distinct assembled constellation
    (deduplicated by face set). For C == 1 this reduces to one entry per
    candidate that passes the global rmse gate.

    When the anchor component is a single face and C > 1, hypothesis seeding is
    O(|anchor candidates| * |next-component candidates|) fit_both calls —
    bounded in practice by the upstream candidate cap."""
    C = len(ref_comp_anchors)
    if C == 0 or anchor_idx >= len(cand_pool) or len(cand_pool) < C:
        return []
    ref_global = np.vstack(ref_comp_anchors)
    bbox = bbox_diag if bbox_diag > 1e-9 else 1.0
    other = [j for j in range(C) if j != anchor_idx]
    results: list[dict] = []
    seen: set[frozenset] = set()

    # Precompute per-component candidate centroids (M,3) and face sets once so
    # the inner nearest-candidate search is a single vectorized squared-distance
    # pass instead of a Python np.linalg.norm per candidate pair.
    comp_centroids = [
        (np.array([c.centroid for c in cand_pool[j]], dtype=np.float64)
         if cand_pool[j] else np.empty((0, 3), dtype=np.float64))
        for j in range(C)
    ]
    comp_facesets = [[set(c.faces) for c in cand_pool[j]] for j in range(C)]
    pos_tol_sq = pos_tol * pos_tol

    for ca in cand_pool[anchor_idx]:
        # Hypothesis transform(s) from the anchor candidate.
        if ref_comp_facecount[anchor_idx] >= 2 or not other:
            if ca.anchors.shape != ref_comp_anchors[anchor_idx].shape:
                continue
            T0, _r, _m = fit_both(ref_comp_anchors[anchor_idx], ca.anchors,
                                  scale_mode)
            hypotheses = [T0]
        else:
            # Degenerate anchor (single face fixes no in-plane rotation): seed
            # jointly with each candidate of the next-most-distinctive component.
            j0 = other[0]
            ref_seed = np.vstack([ref_comp_anchors[anchor_idx],
                                  ref_comp_anchors[j0]])
            hypotheses = []
            for cb in cand_pool[j0]:
                tgt_seed = np.vstack([ca.anchors, cb.anchors])
                if tgt_seed.shape != ref_seed.shape:
                    continue
                T0, _r, _m = fit_both(ref_seed, tgt_seed, scale_mode)
                hypotheses.append(T0)

        for T_hyp in hypotheses:
            chosen = {anchor_idx: ca}
            used = set(ca.faces)
            ok = True
            for j in other:
                cents = comp_centroids[j]
                if cents.shape[0] == 0:
                    ok = False
                    break
                pred = _apply_affine(T_hyp, ref_comp_centroids[j])
                diff = cents - pred
                d2 = np.einsum("ij,ij->i", diff, diff)
                facesets = comp_facesets[j]
                idx = int(np.argmin(d2))
                if d2[idx] <= pos_tol_sq and used.isdisjoint(facesets[idx]):
                    best = cand_pool[j][idx]
                else:
                    # Nearest is out of range or its faces overlap an already
                    # used component; scan ascending for the first valid one.
                    best = None
                    for k in np.argsort(d2):
                        k = int(k)
                        if d2[k] > pos_tol_sq:
                            break
                        if used.isdisjoint(facesets[k]):
                            best = cand_pool[j][k]
                            break
                    if best is None:
                        ok = False
                        break
                chosen[j] = best
                used.update(best.faces)
            if not ok:
                continue
            tgt_global = np.vstack([chosen[i].anchors for i in range(C)])
            if tgt_global.shape != ref_global.shape:
                continue
            _T, rmse, is_mirror = fit_both(ref_global, tgt_global, scale_mode)
            if rmse / bbox > fit_rmse_rel:
                continue
            order = tuple(f for i in range(C) for f in chosen[i].faces)
            key = frozenset(order)
            if key in seen:
                continue
            seen.add(key)
            results.append({"order": order, "faces": key,
                            "mirror": is_mirror, "rmse": rmse})

    # Keep face-disjoint matches, best fit first: a target face belongs to at
    # most one stamped constellation. This drops spurious overlapping matches —
    # e.g. a twisted-correspondence mirror duplicate of a proper match (sharing
    # most of its faces) that would otherwise stamp an extra flipped clone over
    # the correct one. Genuinely separate instances share no faces and survive.
    results.sort(key=lambda r: r["rmse"])
    selected: list[dict] = []
    used_faces: set[int] = set()
    for r in results:
        if r["faces"] & used_faces:
            continue
        selected.append(r)
        used_faces |= r["faces"]
    return selected


# --- bmesh helpers --------------------------------------------------------
#
# These read mesh topology from a bmesh.types.BMesh constructed by the caller
# via `bm = bmesh.new(); bm.from_mesh(obj.data); bm.faces.ensure_lookup_table()`
# and freed via `bm.free()` when no longer needed. No mutation of the bmesh
# occurs here.
import math


def face_island(bm, seed_face_index: int) -> set[int]:
    """BFS expansion from `seed_face_index` across shared edges. Terminates at
    mesh boundary edges (single-face) and at non-manifold edges (>2 faces).
    Returns the set of face indices in the same connected island."""
    seed = bm.faces[seed_face_index]
    visited = {seed.index}
    stack = [seed]
    while stack:
        face = stack.pop()
        for edge in face.edges:
            if len(edge.link_faces) != 2:
                continue
            for nbr in edge.link_faces:
                if nbr.index in visited:
                    continue
                visited.add(nbr.index)
                stack.append(nbr)
    return visited


def similar_by_normal_area(
    bm,
    seed_face_index: int,
    angle_tol_deg: float = 5.0,
    area_tol: float = 0.10,
) -> set[int]:
    """Return indices of faces on the same bmesh whose normal is within
    `angle_tol_deg` of the seed face's normal AND whose area is within
    `area_tol` fractional difference of the seed face's area."""
    seed = bm.faces[seed_face_index]
    seed_n = seed.normal.copy()
    seed_a = float(seed.calc_area())
    cos_tol = math.cos(math.radians(angle_tol_deg))
    out = set()
    for f in bm.faces:
        if f.normal.dot(seed_n) < cos_tol:
            continue
        a = float(f.calc_area())
        if seed_a <= 0.0:
            if a > 0.0:
                continue
        elif abs(a - seed_a) / seed_a > area_tol:
            continue
        out.add(f.index)
    return out


def build_face_pattern(bm, face_indices: Sequence[int]) -> dict:
    """Build a subgraph-matching pattern from a face selection on `bm`.

    Returns a dict with:
      - faces: list of face indices in BFS-canonical order (root first).
      - adj: list[list[int]] — adjacency among the pattern faces, by position
        in `faces`. (i, j) ∈ adj iff the corresponding bm faces share an edge.
      - vcounts: list[int] — vertex count per pattern face.
      - areas: list[float] — area per pattern face.
    """
    sel = set(face_indices)
    if not sel:
        return {"faces": [], "adj": [], "vcounts": [], "areas": []}
    # BFS so the root is the largest face (most distinctive for seeding).
    seed = max(sel, key=lambda fi: bm.faces[fi].calc_area())
    order: list[int] = [seed]
    seen = {seed}
    head = 0
    while head < len(order):
        fi = order[head]
        head += 1
        for edge in bm.faces[fi].edges:
            for nbr in edge.link_faces:
                if nbr.index in sel and nbr.index not in seen:
                    seen.add(nbr.index)
                    order.append(nbr.index)
    pos_of = {fi: i for i, fi in enumerate(order)}
    adj: list[list[int]] = [[] for _ in order]
    for i, fi in enumerate(order):
        for edge in bm.faces[fi].edges:
            for nbr in edge.link_faces:
                j = pos_of.get(nbr.index)
                if j is not None and j != i and j not in adj[i]:
                    adj[i].append(j)
    vcounts = [len(bm.faces[fi].verts) for fi in order]
    areas = [float(bm.faces[fi].calc_area()) for fi in order]
    return {"faces": order, "adj": adj, "vcounts": vcounts, "areas": areas}


def find_pattern_matches(bm, pattern: dict, *, area_tol: float = 0.20,
                         max_matches: int = 512,
                         allow_overlap: bool = False) -> list[list[int]]:
    """Find subsets of `bm.faces` whose induced subgraph is isomorphic to the
    pattern's face-adjacency, with matching vertex counts and per-face areas
    (within `area_tol` relative). Matches are translation/rotation invariant
    by construction.

    DFS with backtracking from every plausible root candidate. By default
    matches are disjoint (a face used in one match isn't re-used by another).
    Setting `allow_overlap` lets matches share faces — caller is responsible
    for deduplicating, but it recovers matches that would have been blocked
    by an earlier overlapping match.
    """
    pat_faces = pattern["faces"]
    if not pat_faces:
        return []
    pat_adj = pattern["adj"]
    pat_vcounts = pattern["vcounts"]
    pat_areas = pattern["areas"]
    n = len(pat_faces)

    # Cache (calc_area, len(verts)) per bmesh face to avoid recomputing during
    # candidate filtering — calc_area() walks the n-gon's verts each call.
    face_areas = {f.index: float(f.calc_area()) for f in bm.faces}
    face_vcounts = {f.index: len(f.verts) for f in bm.faces}

    def _attrs_ok(pi: int, fi: int) -> bool:
        if face_vcounts[fi] != pat_vcounts[pi]:
            return False
        ref_area = pat_areas[pi]
        if ref_area <= 0.0:
            return face_areas[fi] <= 0.0
        return abs(face_areas[fi] - ref_area) / ref_area <= area_tol

    # Root candidates: any face with matching vcount/area to pattern face 0.
    roots = [f for f in bm.faces if _attrs_ok(0, f.index)]

    matches: list[list[int]] = []
    seen: set[frozenset[int]] = set()
    locked: set[int] = set()

    def _try_match(root_face) -> list[int] | None:
        mapping: dict[int, int] = {0: root_face.index}
        used: set[int] = {root_face.index}

        def _solve(pi: int) -> bool:
            if pi >= n:
                return True
            anchor = None
            for q in pat_adj[pi]:
                if q in mapping:
                    anchor = q
                    break
            if anchor is None:
                return False
            anchor_face = bm.faces[mapping[anchor]]
            candidates = []
            for edge in anchor_face.edges:
                for tf in edge.link_faces:
                    if tf is anchor_face:
                        continue
                    if tf.index in used:
                        continue
                    if not allow_overlap and tf.index in locked:
                        continue
                    if not _attrs_ok(pi, tf.index):
                        continue
                    candidates.append(tf)
            for tf in candidates:
                ok = True
                for q in pat_adj[pi]:
                    if q not in mapping or q == anchor:
                        continue
                    qf = bm.faces[mapping[q]]
                    if not any(tf in e.link_faces for e in qf.edges):
                        ok = False
                        break
                if not ok:
                    continue
                mapping[pi] = tf.index
                used.add(tf.index)
                if _solve(pi + 1):
                    return True
                used.discard(tf.index)
                mapping.pop(pi, None)
            return False

        if _solve(1):
            return [mapping[i] for i in range(n)]
        return None

    for root in roots:
        if len(matches) >= max_matches:
            break
        if not allow_overlap and root.index in locked:
            continue
        m = _try_match(root)
        if m is None:
            continue
        key = frozenset(m)
        if key in seen:
            continue
        seen.add(key)
        matches.append(m)
        if not allow_overlap:
            locked.update(m)
    return matches


def components_in_selection(bm, face_indices: set[int]) -> list[set[int]]:
    """Connected components within a subset of faces. Two faces are connected
    iff they share an edge AND both belong to `face_indices`. Returns a list
    of disjoint face-index sets."""
    remaining = set(face_indices)
    components = []
    while remaining:
        seed_idx = next(iter(remaining))
        comp = {seed_idx}
        stack = [bm.faces[seed_idx]]
        remaining.discard(seed_idx)
        while stack:
            face = stack.pop()
            for edge in face.edges:
                for nbr in edge.link_faces:
                    if nbr.index in remaining:
                        remaining.discard(nbr.index)
                        comp.add(nbr.index)
                        stack.append(nbr)
        components.append(comp)
    return components
