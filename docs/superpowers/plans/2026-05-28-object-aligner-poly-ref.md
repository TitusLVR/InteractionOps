# Object Aligner — Polygon Reference Mode Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend the existing `iops.object_aligner` modal operator with a polygon-reference mode (Q-toggle), allowing per-polygon-group alignment with strict Procrustes fit, optional PCA-frame force-fit (W), similarity highlighting (A), and a dynamic RMSE threshold (Alt+Wheel).

**Architecture:** Add one new pure-Python/NumPy module `utils/polygon_match.py` (with bmesh helpers for mesh-graph queries). Add two new theme roles. Extend `operators/object_aligner.py` with new modes, hotkeys, drawing branches, and a bmesh cache. The existing object-only flow remains untouched.

**Tech Stack:** Blender Python (`bpy`, `bmesh`, `mathutils`, `gpu`), NumPy, existing addon modules (`utils.alignment_fit.kabsch`, `utils.picking.raycast_from_mouse`, `ui.draw.primitives`, `ui.draw.theme`, `ui.hud`).

**Spec:** [docs/superpowers/specs/2026-05-28-object-aligner-poly-ref-design.md](../specs/2026-05-28-object-aligner-poly-ref-design.md)

**Testing note:** Pure-NumPy functions in `utils/polygon_match.py` get pytest unit tests. Bmesh helpers and operator integration are verified via `blender-mcp` smoke checks (load addon → run operator on a known scene → inspect `bpy` state and visual ghost rendering), then committed. Pytest command: `python -m pytest tests/test_polygon_match.py -v`.

---

## File Structure

- **Create:** `utils/polygon_match.py` — `signature`, `pca_ratios`, `pca_frame`, `d2_histogram`, `kabsch_with_scale`, `greedy_correspondence`, plus bmesh-dependent `face_island`, `similar_by_normal_area`, `components_in_selection`. ~280 LOC.
- **Create:** `tests/test_polygon_match.py` — pytest unit tests for the numpy-only functions.
- **Modify:** `ui/draw/theme.py` — add `GHOST_TARGET_SEL`, `GHOST_MATCH_HINT` to `Role`, `_DEFAULT_COLORS`, and the `c(...)` mapping (~3 small edits).
- **Modify:** `operators/object_aligner.py` — add modes, state fields, bmesh cache, Q/A/W hotkeys, Alt+Wheel handler, poly-picking branches in `_on_click`, two new drawing branches in `_draw_preview_3d`, ref/target commit logic, force fallback in `_compute_fit`, per-component apply path. ~250 LOC net add.

No changes to `utils/picking.py` (it already returns `face_index`).
No changes to `utils/alignment_fit.py` (we wrap `kabsch` and compute RMSE in the new module).
No changes to `__init__.py` or the pie menu (operator id unchanged).

---

## Task 1: Add theme roles

**Files:**
- Modify: `ui/draw/theme.py` (3 edits)

- [ ] **Step 1: Add Role enum entries**

Edit `ui/draw/theme.py`, the `GHOST_*` block (~line 33-39):

```python
    # Ghost / Surfaces — highlighted faces and ghost-preview wireframes.
    GHOST_EDGE = "ghost_edge"
    GHOST_DEFAULT = "ghost_default"
    GHOST_ACTIVE = "ghost_active"      # state tints for ghost fills (copied from line states)
    GHOST_CLOSEST = "ghost_closest"
    GHOST_LOCKED = "ghost_locked"
    GHOST_PREVIEW = "ghost_preview"
    GHOST_TARGET_SEL = "ghost_target_sel"   # selected target polys in poly-ref mode
    GHOST_MATCH_HINT = "ghost_match_hint"   # A-key match candidates
```

- [ ] **Step 2: Add default colors**

Edit `_DEFAULT_COLORS` block (~line 91-96), append after `GHOST_PREVIEW`:

```python
    Role.GHOST_TARGET_SEL: (*_C_AMBER, 0.70),   # warm fill — easy to distinguish from cyan ref
    Role.GHOST_MATCH_HINT: (*_C_GREEN, 0.35),   # dim green — "candidate", not yet selected
```

- [ ] **Step 3: Add theme-pref bindings**

Edit the `c(...)` mapping block (~line 287), append after `Role.GHOST_PREVIEW`:

```python
            Role.GHOST_TARGET_SEL:   c("color_target_sel_ghost", _DEFAULT_COLORS[Role.GHOST_TARGET_SEL]),
            Role.GHOST_MATCH_HINT:   c("color_match_hint_ghost", _DEFAULT_COLORS[Role.GHOST_MATCH_HINT]),
```

These prefs are not yet declared on the IOPSTheme PropertyGroup; that's fine, `c(...)` falls back to the default when the pref is missing (verify by reading `ui/draw/theme.py` around line 240 — the `c()` helper reads with a default). The roles render correctly even without prefs UI entries; theme-tab integration is out of scope for this plan.

- [ ] **Step 4: Commit**

```bash
git add ui/draw/theme.py
git commit -m "feat(theme): add GHOST_TARGET_SEL and GHOST_MATCH_HINT roles"
```

---

## Task 2: `signature` + `pca_ratios` (TDD)

**Files:**
- Create: `utils/polygon_match.py`
- Create: `tests/test_polygon_match.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_polygon_match.py`:

```python
import numpy as np
import pytest

from utils.polygon_match import signature, pca_ratios


CUBE = np.array([
    [0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [1.0, 1.0, 0.0], [0.0, 1.0, 0.0],
    [0.0, 0.0, 1.0], [1.0, 0.0, 1.0], [1.0, 1.0, 1.0], [0.0, 1.0, 1.0],
])
CUBE_FACES = [
    [0, 1, 2, 3], [4, 5, 6, 7],
    [0, 1, 5, 4], [2, 3, 7, 6],
    [1, 2, 6, 5], [0, 3, 7, 4],
]


def test_signature_basic_cube():
    sig = signature(CUBE, CUBE_FACES)
    assert sig.vert_count == 8
    assert sig.face_count == 6
    # All faces are quads.
    assert sig.face_vcount_hist == ((4, 6),)
    # bbox diag = sqrt(3) for unit cube.
    assert sig.bbox_diag == pytest.approx(np.sqrt(3.0), abs=1e-6)


def test_signature_mixed_face_sizes():
    faces = [[0, 1, 2], [0, 1, 2, 3], [0, 1, 2, 3, 4]]  # tri, quad, pent
    sig = signature(CUBE[:5], faces)
    assert sig.face_count == 3
    assert sig.face_vcount_hist == ((3, 1), (4, 1), (5, 1))


def test_pca_ratios_isotropic_cube():
    r = pca_ratios(CUBE)
    # Sum to 1.
    assert np.isclose(sum(r), 1.0, atol=1e-9)
    # All three eigenvalues equal for a cube.
    assert all(np.isclose(x, 1.0 / 3.0, atol=1e-6) for x in r)


def test_pca_ratios_flat_plane():
    # Points on z=0 plane — third eigenvalue near zero.
    pts = np.array([[0.0, 0.0, 0.0], [2.0, 0.0, 0.0], [0.0, 1.0, 0.0], [2.0, 1.0, 0.0]])
    r = pca_ratios(pts)
    assert r[0] > r[1] > r[2]
    assert r[2] < 1e-9
```

- [ ] **Step 2: Run tests, verify failure**

```bash
python -m pytest tests/test_polygon_match.py -v
```

Expected: `ModuleNotFoundError: No module named 'utils.polygon_match'`.

- [ ] **Step 3: Implement signature and pca_ratios**

Create `utils/polygon_match.py`:

```python
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
```

- [ ] **Step 4: Run tests, verify pass**

```bash
python -m pytest tests/test_polygon_match.py -v
```

Expected: all 4 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add utils/polygon_match.py tests/test_polygon_match.py
git commit -m "feat(polygon_match): signature + pca_ratios with tests"
```

---

## Task 3: `pca_frame` (TDD)

**Files:**
- Modify: `utils/polygon_match.py`
- Modify: `tests/test_polygon_match.py`

- [ ] **Step 1: Add failing tests**

Append to `tests/test_polygon_match.py`:

```python
from utils.polygon_match import pca_frame


def test_pca_frame_axis_aligned_quad():
    # Unit quad on z=0, centered at origin, lying flat.
    verts = np.array([
        [-1.0, -1.0, 0.0],
        [ 1.0, -1.0, 0.0],
        [ 1.0,  1.0, 0.0],
        [-1.0,  1.0, 0.0],
    ])
    face_normals = np.array([[0.0, 0.0, 1.0]])
    face_areas = np.array([4.0])
    face_centroids = np.array([[0.0, 0.0, 0.0]])
    frame = pca_frame(verts, face_centroids, face_normals, face_areas)
    # 4x4 matrix.
    assert frame.shape == (4, 4)
    # Origin at quad centroid.
    assert np.allclose(frame[:3, 3], [0.0, 0.0, 0.0], atol=1e-6)
    # Z axis matches face normal.
    assert np.allclose(frame[:3, 2], [0.0, 0.0, 1.0], atol=1e-6)
    # X and Y orthogonal to Z and to each other, unit length.
    x = frame[:3, 0]
    y = frame[:3, 1]
    assert np.isclose(np.linalg.norm(x), 1.0, atol=1e-6)
    assert np.isclose(np.linalg.norm(y), 1.0, atol=1e-6)
    assert np.isclose(np.dot(x, y), 0.0, atol=1e-6)
    assert np.isclose(np.dot(x, [0, 0, 1]), 0.0, atol=1e-6)


def test_pca_frame_translated_offset():
    # Same quad, translated.
    verts = np.array([
        [10.0, 5.0, 2.0],
        [12.0, 5.0, 2.0],
        [12.0, 7.0, 2.0],
        [10.0, 7.0, 2.0],
    ])
    face_normals = np.array([[0.0, 0.0, 1.0]])
    face_areas = np.array([4.0])
    face_centroids = np.array([[11.0, 6.0, 2.0]])
    frame = pca_frame(verts, face_centroids, face_normals, face_areas)
    assert np.allclose(frame[:3, 3], [11.0, 6.0, 2.0], atol=1e-6)
    assert np.allclose(frame[:3, 2], [0.0, 0.0, 1.0], atol=1e-6)


def test_pca_frame_degenerate_pca_falls_back():
    # All vertices collinear along Z, normal also Z → projection of principal
    # PCA axis onto plane perp-to-Z is zero. Fallback must produce a valid
    # orthonormal frame.
    verts = np.array([
        [0.0, 0.0, 0.0],
        [0.0, 0.0, 1.0],
        [0.0, 0.0, 2.0],
    ])
    face_normals = np.array([[0.0, 0.0, 1.0]])
    face_areas = np.array([1.0])
    face_centroids = np.array([[0.0, 0.0, 1.0]])
    frame = pca_frame(verts, face_centroids, face_normals, face_areas)
    x = frame[:3, 0]
    z = frame[:3, 2]
    assert np.isclose(np.linalg.norm(x), 1.0, atol=1e-6)
    assert np.isclose(np.dot(x, z), 0.0, atol=1e-6)
```

- [ ] **Step 2: Run tests, verify failure**

Expected: `ImportError: cannot import name 'pca_frame'`.

- [ ] **Step 3: Implement pca_frame**

Append to `utils/polygon_match.py`:

```python
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
```

- [ ] **Step 4: Run tests, verify pass**

Expected: all 7 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add utils/polygon_match.py tests/test_polygon_match.py
git commit -m "feat(polygon_match): pca_frame with degenerate fallback"
```

---

## Task 4: `kabsch_with_scale` + `greedy_correspondence` (TDD)

**Files:**
- Modify: `utils/polygon_match.py`
- Modify: `tests/test_polygon_match.py`

- [ ] **Step 1: Add failing tests**

Append to `tests/test_polygon_match.py`:

```python
from utils.polygon_match import kabsch_with_scale, greedy_correspondence


REF_CLOUD = np.array([
    [0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0],
    [1.0, 1.0, 0.0], [1.0, 0.0, 1.0], [0.0, 1.0, 1.0], [1.0, 1.0, 1.0],
])


def test_kabsch_with_scale_keep_translation():
    tgt = REF_CLOUD + np.array([5.0, -2.0, 3.0])
    T, rmse = kabsch_with_scale(REF_CLOUD, tgt, scale_mode="KEEP")
    # Apply T to REF_CLOUD (homogeneous) and compare.
    homog = np.hstack([REF_CLOUD, np.ones((REF_CLOUD.shape[0], 1))])
    out = (homog @ T.T)[:, :3]
    assert np.allclose(out, tgt, atol=1e-6)
    assert rmse < 1e-6


def test_kabsch_with_scale_uniform_recovers_2x():
    tgt = REF_CLOUD * 2.0
    T, rmse = kabsch_with_scale(REF_CLOUD, tgt, scale_mode="UNIFORM")
    homog = np.hstack([REF_CLOUD, np.ones((REF_CLOUD.shape[0], 1))])
    out = (homog @ T.T)[:, :3]
    assert np.allclose(out, tgt, atol=1e-6)
    assert rmse < 1e-6


def test_kabsch_rmse_nonzero_on_noise():
    rng = np.random.default_rng(42)
    tgt = REF_CLOUD + rng.normal(0.0, 0.01, REF_CLOUD.shape)
    _, rmse = kabsch_with_scale(REF_CLOUD, tgt, scale_mode="KEEP")
    assert 0.0 < rmse < 0.1


def test_greedy_correspondence_recovers_shuffled():
    # Shuffle target, verify correspondence reverses the shuffle.
    rng = np.random.default_rng(7)
    perm = rng.permutation(REF_CLOUD.shape[0])
    tgt = REF_CLOUD[perm] + np.array([3.0, 0.0, 0.0])
    corr = greedy_correspondence(REF_CLOUD, tgt)
    # corr[i] should give the index in tgt that pairs with ref[i].
    paired_tgt = tgt[corr]
    assert np.allclose(paired_tgt - np.array([3.0, 0.0, 0.0]), REF_CLOUD, atol=1e-6)
```

- [ ] **Step 2: Run tests, verify failure**

Expected: `ImportError`.

- [ ] **Step 3: Implement both functions**

First, add this import to the top of `utils/polygon_match.py` (next to the existing `import numpy as np`):

```python
from .alignment_fit import solve_fit
```

Then append the functions to `utils/polygon_match.py`:

```python
def kabsch_with_scale(
    ref_pts: np.ndarray,
    tgt_pts: np.ndarray,
    scale_mode: str = "KEEP",
) -> tuple[np.ndarray, float]:
    """Wrap `utils.alignment_fit.solve_fit` and additionally return RMSE.

    Returns (T_4x4, rmse) where T transforms ref_pts → tgt_pts in homogeneous
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

    # Distance matrix (n is small in practice — single polys to a few hundred).
    diff = pre_aligned[:, None, :] - tgt_pts[None, :, :]
    dists = np.linalg.norm(diff, axis=2)              # n×n

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
```

- [ ] **Step 4: Run tests, verify pass**

Expected: all 11 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add utils/polygon_match.py tests/test_polygon_match.py
git commit -m "feat(polygon_match): kabsch_with_scale + greedy_correspondence"
```

---

## Task 5: `d2_histogram` (TDD)

**Files:**
- Modify: `utils/polygon_match.py`
- Modify: `tests/test_polygon_match.py`

- [ ] **Step 1: Add failing tests**

Append to `tests/test_polygon_match.py`:

```python
from utils.polygon_match import d2_histogram


def test_d2_deterministic_with_seed():
    h1 = d2_histogram(CUBE, CUBE_FACES, samples=256, bins=16, seed=0)
    h2 = d2_histogram(CUBE, CUBE_FACES, samples=256, bins=16, seed=0)
    assert np.array_equal(h1, h2)


def test_d2_translation_invariant():
    h_a = d2_histogram(CUBE, CUBE_FACES, samples=256, bins=16, seed=0)
    h_b = d2_histogram(CUBE + 10.0, CUBE_FACES, samples=256, bins=16, seed=0)
    assert np.array_equal(h_a, h_b)


def test_d2_scale_invariant_after_normalization():
    # We normalize distances by bbox diag, so the histogram should match.
    h_a = d2_histogram(CUBE, CUBE_FACES, samples=512, bins=16, seed=0)
    h_b = d2_histogram(CUBE * 5.0, CUBE_FACES, samples=512, bins=16, seed=0)
    # χ² distance ~0 between identical-shape clouds at different scales.
    chi2 = float(np.sum((h_a - h_b) ** 2 / np.maximum(h_a + h_b, 1e-9)))
    assert chi2 < 1e-6


def test_d2_distinguishes_different_shapes():
    # Cube vs. very flat slab (different aspect ratio) → distinct histograms.
    slab = CUBE.copy()
    slab[:, 2] *= 0.01
    h_cube = d2_histogram(CUBE, CUBE_FACES, samples=512, bins=16, seed=0)
    h_slab = d2_histogram(slab, CUBE_FACES, samples=512, bins=16, seed=0)
    chi2 = float(np.sum((h_cube - h_slab) ** 2 / np.maximum(h_cube + h_slab, 1e-9)))
    assert chi2 > 0.05
```

- [ ] **Step 2: Run tests, verify failure**

Expected: `ImportError`.

- [ ] **Step 3: Implement d2_histogram**

Append to `utils/polygon_match.py`:

```python
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
```

- [ ] **Step 4: Run tests, verify pass**

Expected: all 15 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add utils/polygon_match.py tests/test_polygon_match.py
git commit -m "feat(polygon_match): D2 shape distribution histogram"
```

---

## Task 6: Bmesh helpers — `face_island`, `similar_by_normal_area`, `components_in_selection`

**Files:**
- Modify: `utils/polygon_match.py`

These functions take a `bmesh.types.BMesh` (already constructed from a mesh datablock by the caller). Tests live in the operator smoke checks rather than pytest because bmesh requires Blender.

- [ ] **Step 1: Implement the three helpers**

Append to `utils/polygon_match.py`:

```python
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
```

- [ ] **Step 2: Smoke check via blender-mcp**

Run via mcp__blender__execute_blender_python (start a fresh scene with the addon loaded, then):

```python
import bpy, bmesh, sys, importlib

# Force re-import of the module if previously loaded.
mod = "InteractionOps.utils.polygon_match"
if mod in sys.modules:
    importlib.reload(sys.modules[mod])
from InteractionOps.utils import polygon_match as pm

# Create two separate cubes joined into one mesh — distinct islands.
bpy.ops.object.select_all(action="DESELECT")
bpy.ops.mesh.primitive_cube_add(location=(0, 0, 0))
a = bpy.context.object
bpy.ops.mesh.primitive_cube_add(location=(5, 0, 0))
b = bpy.context.object
a.select_set(True); b.select_set(True)
bpy.context.view_layer.objects.active = a
bpy.ops.object.join()
obj = bpy.context.object

bm = bmesh.new()
bm.from_mesh(obj.data)
bm.faces.ensure_lookup_table()

# 12 faces total, two islands of 6 each.
island0 = pm.face_island(bm, 0)
island6 = pm.face_island(bm, 6)
assert len(island0) == 6, f"island from face 0: {island0}"
assert len(island6) == 6, f"island from face 6: {island6}"
assert island0.isdisjoint(island6)

# Components on a subset that spans both islands.
sel = {0, 1, 6, 7}
comps = pm.components_in_selection(bm, sel)
assert len(comps) == 2, f"expected 2 components, got {[len(c) for c in comps]}"

# Similar — top faces of both cubes should match.
top_idx = 0  # cube tops are face 0 in default cube
similar = pm.similar_by_normal_area(bm, top_idx)
assert top_idx in similar
# Should pick up the other cube's top too (same area, same normal).
assert len(similar) >= 2, f"similar: {similar}"

bm.free()
print("OK polygon_match bmesh helpers")
```

Expected: prints `OK polygon_match bmesh helpers`.

- [ ] **Step 3: Commit**

```bash
git add utils/polygon_match.py
git commit -m "feat(polygon_match): bmesh helpers — island, similar, components"
```

---

## Task 7: Operator — modes, state, bmesh cache lifecycle

**Files:**
- Modify: `operators/object_aligner.py`

- [ ] **Step 1: Add mode constants and a bmesh-cache helper**

Edit `operators/object_aligner.py` near the top constants block (after `MODE_STAMP = "STAMP"`):

```python
MODE_PICK_REF      = "PICK_REF"
MODE_STAMP         = "STAMP"
MODE_PICK_REF_POLY = "PICK_REF_POLY"      # marking ref polys; Q again commits
MODE_PICK_TGT_POLY = "PICK_TGT_POLY"      # marking target polys; Apply stamps
```

Then add this helper (placement: just below `_verts_world_np`):

```python
import bmesh


def _bmesh_for(op, obj):
    """Lazy bmesh-cache keyed by obj.original. Caller must not mutate the
    bmesh — we only read topology, normals and areas. Freed in _finish."""
    key = obj.original
    cached = op._bmesh_cache.get(key)
    if cached is not None:
        return cached
    bm = bmesh.new()
    bm.from_mesh(key.data)
    bm.faces.ensure_lookup_table()
    bm.edges.ensure_lookup_table()
    op._bmesh_cache[key] = bm
    return bm
```

- [ ] **Step 2: Initialize new state fields in `invoke`**

In `IOPS_OT_Object_Aligner.invoke`, after `self._last_event = None`, append:

```python
        # Polygon-reference mode state.
        self.ref_polys = {}                    # dict[obj_original -> set[face_idx]]
        self.target_polys = {}                 # dict[obj_original -> set[face_idx]]
        self.ref_signature = None
        self.ref_points_np = None              # Nx3 world
        self.ref_pca_ratios = None
        self.ref_d2 = None
        self.ref_frame_np = None               # 4x4 numpy
        self.ref_bbox_diag = 0.0
        self.match_hints = {}                  # dict[obj_original -> list[set[face_idx]]]
        self.show_match_hints = False
        self.force_mode = False
        self.match_rmse_threshold = 0.05
        self._bmesh_cache = {}
```

- [ ] **Step 3: Free bmesh cache in `_finish`**

In `_finish`, before the existing handler removal:

```python
        for bm in getattr(self, "_bmesh_cache", {}).values():
            try:
                bm.free()
            except (ReferenceError, RuntimeError):
                pass
        self._bmesh_cache = {}
```

- [ ] **Step 4: Smoke check**

Via blender-mcp: invoke the operator, press Esc, confirm no errors in the console and that `_bmesh_cache` accesses produce no leaks (operator finishes cleanly):

```python
import bpy
bpy.ops.iops.object_aligner('INVOKE_DEFAULT')
# (cannot interact modally headlessly — just ensure the import/registration works)
print("invoke smoke OK" if bpy.ops.iops.object_aligner.poll() else "poll FAILED")
```

For the actual modal flow, this is verified by tasks below.

- [ ] **Step 5: Commit**

```bash
git add operators/object_aligner.py
git commit -m "feat(object_aligner): mode constants + bmesh cache lifecycle"
```

---

## Task 8: Operator — Q-key transitions + ref poly picking

**Files:**
- Modify: `operators/object_aligner.py`

- [ ] **Step 1: Add poly-picking helpers**

Append after `_pick` (around line 449):

```python
    def _pick_face(self, context, event):
        """Raycast under the mouse, return (obj.original, face_index) or
        (None, -1). Excludes rig only — ref object is allowed to be re-picked
        in poly modes (per spec: ref-set may live anywhere except rig)."""
        from ..utils.picking import raycast_from_mouse
        hit, _loc, _n, face_idx, obj, _mx = raycast_from_mouse(
            context, _mouse_coord(event), exclude=set(self.source_set))
        if not hit or obj is None:
            return None, -1
        # Guard against modifier-generated face indices out of base-mesh range.
        original = obj.original
        if original.type != "MESH" or original.data is None:
            return None, -1
        if face_idx >= len(original.data.polygons):
            return None, -1
        return original, int(face_idx)

    def _toggle_face(self, store: dict, obj, face_idx: int):
        """Toggle a single face in either self.ref_polys or self.target_polys."""
        s = store.setdefault(obj, set())
        if face_idx in s:
            s.discard(face_idx)
            if not s:
                store.pop(obj, None)
        else:
            s.add(face_idx)

    def _add_island(self, store: dict, obj, face_idx: int):
        from ..utils.polygon_match import face_island
        bm = _bmesh_for(self, obj)
        store.setdefault(obj, set()).update(face_island(bm, face_idx))

    def _add_similar(self, store: dict, obj, face_idx: int):
        from ..utils.polygon_match import similar_by_normal_area
        bm = _bmesh_for(self, obj)
        store.setdefault(obj, set()).update(similar_by_normal_area(bm, face_idx))

    def _remove_island(self, store: dict, obj, face_idx: int):
        from ..utils.polygon_match import face_island
        bm = _bmesh_for(self, obj)
        island = face_island(bm, face_idx)
        s = store.get(obj)
        if s is None:
            return
        s.difference_update(island)
        if not s:
            store.pop(obj, None)
```

- [ ] **Step 2: Add Q-key transitions in `modal`**

In `modal()`, inside the `if event.value == "PRESS":` block (next to D/S/R), add:

```python
            if event.type == "Q":
                if self.mode == MODE_STAMP and self.ref_obj is not None:
                    self.mode = MODE_PICK_REF_POLY
                    return {"RUNNING_MODAL"}
                if self.mode == MODE_PICK_REF_POLY:
                    if not self.ref_polys:
                        self.report({"WARNING"}, "Ref poly set is empty")
                        return {"RUNNING_MODAL"}
                    self._commit_ref_polys(context)
                    self.mode = MODE_PICK_TGT_POLY
                    return {"RUNNING_MODAL"}
                # In MODE_PICK_TGT_POLY or MODE_PICK_REF: Q is currently a no-op.
                return {"RUNNING_MODAL"}
```

Add a stub for `_commit_ref_polys` immediately (filled out in Task 9):

```python
    def _commit_ref_polys(self, context):
        # Filled in Task 9.
        pass
```

- [ ] **Step 3: Route LMB in poly modes to picking branches**

Replace the existing `if event.type == "LEFTMOUSE" and event.value == "PRESS":` block in `modal`:

```python
        if event.type == "LEFTMOUSE" and event.value == "PRESS":
            if self.mode in (MODE_PICK_REF_POLY, MODE_PICK_TGT_POLY):
                obj, face_idx = self._pick_face(context, event)
                if obj is None:
                    return {"RUNNING_MODAL"}
                store = self.ref_polys if self.mode == MODE_PICK_REF_POLY else self.target_polys
                if event.alt:
                    if face_idx in store.get(obj, set()):
                        self._toggle_face(store, obj, face_idx)
                    else:
                        self._remove_island(store, obj, face_idx)
                elif event.shift:
                    self._add_island(store, obj, face_idx)
                elif event.ctrl:
                    self._add_similar(store, obj, face_idx)
                else:
                    self._toggle_face(store, obj, face_idx)
                return {"RUNNING_MODAL"}
            # Object-mode click branch (existing behavior).
            return self._on_click(context, event)
```

- [ ] **Step 4: Add drawing of marked ref polys**

In `_draw_preview_3d`, modify the "Reference highlight" block to suppress whole-object highlight when `op.ref_polys` is non-empty, and add a new block to draw marked ref polys:

Replace this:
```python
    # Reference highlight — active surface fill, polygons only.
    if op.ref_obj is not None:
        try:
            tris = _mesh_tris_world(op.ref_obj)
        except ReferenceError:
            tris = []
        if tris:
            tris = _bias_toward_view(tris, rv3d)
            with draw_scope(blend="ALPHA", depth="LESS_EQUAL",
                            face_culling="NONE", depth_mask=False):
                iops_draw.tris(tris, role=Role.GHOST_ACTIVE, context=context)
```

With:
```python
    # Reference highlight — whole-object fill (only when no ref polys marked).
    if op.ref_obj is not None and not op.ref_polys:
        try:
            tris = _mesh_tris_world(op.ref_obj)
        except ReferenceError:
            tris = []
        if tris:
            tris = _bias_toward_view(tris, rv3d)
            with draw_scope(blend="ALPHA", depth="LESS_EQUAL",
                            face_culling="NONE", depth_mask=False):
                iops_draw.tris(tris, role=Role.GHOST_ACTIVE, context=context)

    # Marked ref polys — fill (replaces whole-object highlight when present).
    if op.ref_polys:
        tris = _selected_face_tris_world(op.ref_polys)
        if tris:
            tris = _bias_toward_view(tris, rv3d)
            with draw_scope(blend="ALPHA", depth="LESS_EQUAL",
                            face_culling="NONE", depth_mask=False):
                iops_draw.tris(tris, role=Role.GHOST_ACTIVE, context=context)

    # Marked target polys (current edit set).
    if op.target_polys:
        tris = _selected_face_tris_world(op.target_polys)
        if tris:
            tris = _bias_toward_view(tris, rv3d)
            with draw_scope(blend="ALPHA", depth="LESS_EQUAL",
                            face_culling="NONE", depth_mask=False):
                iops_draw.tris(tris, role=Role.GHOST_TARGET_SEL, context=context)
```

Add a new module-level helper near `_mesh_tris_world`:

```python
def _selected_face_tris_world(store: dict) -> list:
    """Flat list of world-space triangle verts for the faces stored in
    `store` (dict[obj_original -> set[face_idx]]). Fan-triangulates n-gons."""
    out = []
    for obj, face_idx_set in store.items():
        try:
            if obj.type != "MESH" or obj.data is None:
                continue
            mesh = obj.data
            mw = obj.matrix_world
            for fi in face_idx_set:
                if fi < 0 or fi >= len(mesh.polygons):
                    continue
                poly = mesh.polygons[fi]
                vs = [mw @ mesh.vertices[poly.vertices[i]].co
                      for i in range(len(poly.vertices))]
                for i in range(1, len(vs) - 1):
                    out.extend([vs[0], vs[i], vs[i + 1]])
        except ReferenceError:
            continue
    return out
```

- [ ] **Step 5: Smoke check via blender-mcp**

Create a scene with a rig (suzanne), a ref object, and a target object. Manually invoke the operator and walk through Q-press, LMB clicks, Shift+LMB. (This smoke check is necessarily interactive — record observations in the commit message: "ref polys mark and fill amber/cyan; island shift-pick covers full island".)

- [ ] **Step 6: Commit**

```bash
git add operators/object_aligner.py
git commit -m "feat(object_aligner): Q-toggle ref-poly marking + drawing"
```

---

## Task 9: Operator — ref commit (cache signature, points, frame, descriptors)

**Files:**
- Modify: `operators/object_aligner.py`

- [ ] **Step 1: Implement `_commit_ref_polys`**

Replace the stub from Task 8:

```python
    def _commit_ref_polys(self, context):
        """Snapshot all derived data for the ref poly set at commit time so
        target-side matching is cheap during mouse-move."""
        from ..utils import polygon_match as pm

        verts_all, faces_all = [], []
        face_centroids, face_normals, face_areas = [], [], []
        for obj, face_idx_set in self.ref_polys.items():
            mesh = obj.data
            mw_np = np.array(obj.matrix_world)
            # Per-object vertex pool deduplicated only by polygon — D2/PCA take
            # the union, so duplication of shared verts across faces is fine.
            local_index = {}
            for fi in face_idx_set:
                poly = mesh.polygons[fi]
                f_local = []
                for vi in poly.vertices:
                    if vi not in local_index:
                        co = mesh.vertices[vi].co
                        h = np.array([co.x, co.y, co.z, 1.0]) @ mw_np.T
                        local_index[vi] = len(verts_all)
                        verts_all.append(h[:3])
                    f_local.append(local_index[vi])
                faces_all.append(f_local)
                # Face centroid (mean of world verts in this face).
                ws = np.array([verts_all[i] for i in f_local])
                face_centroids.append(ws.mean(axis=0))
                # Face normal in world (poly.normal rotated by mw 3x3 rotation).
                n_local = np.array([poly.normal.x, poly.normal.y, poly.normal.z])
                n_world = mw_np[:3, :3] @ n_local
                nrm = np.linalg.norm(n_world)
                face_normals.append(n_world / nrm if nrm > 0 else np.array([0.0, 0.0, 1.0]))
                face_areas.append(float(poly.area))

        self.ref_points_np = np.asarray(verts_all, dtype=np.float64)
        sig = pm.signature(self.ref_points_np, faces_all)
        self.ref_signature = sig
        self.ref_bbox_diag = sig.bbox_diag
        self.ref_pca_ratios = pm.pca_ratios(self.ref_points_np)
        self.ref_d2 = pm.d2_histogram(self.ref_points_np, faces_all)
        self.ref_frame_np = pm.pca_frame(
            self.ref_points_np,
            np.asarray(face_centroids),
            np.asarray(face_normals),
            np.asarray(face_areas),
        )
```

- [ ] **Step 2: Smoke check**

Via blender-mcp, after marking some ref polys and pressing Q:

```python
op = bpy.context.window_manager.operators[-1]  # not directly accessible; use a probe attached during dev
# Instead, attach a print to _commit_ref_polys temporarily; verify in console:
# - ref_signature has expected vert/face counts
# - ref_bbox_diag > 0
# - ref_frame_np is 4x4
```

(For interactive verification: temporarily add `print(self.ref_signature)` at end of `_commit_ref_polys` and confirm output, then remove before commit.)

- [ ] **Step 3: Commit**

```bash
git add operators/object_aligner.py
git commit -m "feat(object_aligner): commit ref polys — cache shape descriptors"
```

---

## Task 10: Operator — A-key match search + hint drawing

**Files:**
- Modify: `operators/object_aligner.py`

- [ ] **Step 1: Add match-search method**

Append to the operator class:

```python
    def _search_matches(self, context):
        """Loose-tier similarity scan over all non-rig objects in the scene.
        Populates self.match_hints[obj] with lists of face-index sets, one per
        candidate component. Used only for visual hints — does not auto-select."""
        from ..utils import polygon_match as pm
        self.match_hints = {}
        if self.ref_signature is None:
            return
        loose_ratio_tol = 0.10           # L1 distance on PCA ratios
        loose_d2_chi2 = 0.05             # χ² threshold
        for obj in context.scene.objects:
            if obj in self.source_set or obj.type != "MESH" or obj.data is None:
                continue
            original = obj.original
            try:
                bm = _bmesh_for(self, original)
            except (RuntimeError, ReferenceError):
                continue
            # Build candidate components: connected components of the full mesh.
            all_face_set = {f.index for f in bm.faces}
            comps = pm.components_in_selection(bm, all_face_set)
            mw_np = np.array(obj.matrix_world)
            kept = []
            for comp in comps:
                verts_world, faces_local = self._extract_component_verts(
                    original, comp, mw_np)
                if verts_world.shape[0] == 0:
                    continue
                sig = pm.signature(verts_world, faces_local)
                # Strict match disqualifies as merely "hint" — skip (already in hand on apply).
                # Loose tier: PCA ratios distance + D2 χ².
                ratios = pm.pca_ratios(verts_world)
                ratio_dist = sum(abs(a - b) for a, b in zip(ratios, self.ref_pca_ratios))
                if ratio_dist > loose_ratio_tol:
                    continue
                d2 = pm.d2_histogram(verts_world, faces_local)
                chi2 = float(np.sum((d2 - self.ref_d2) ** 2 / np.maximum(d2 + self.ref_d2, 1e-9)))
                if chi2 > loose_d2_chi2:
                    continue
                kept.append(comp)
            if kept:
                self.match_hints[original] = kept

    def _extract_component_verts(self, obj, face_idx_set, mw_np):
        """Helper: world-space verts (Nx3) and local face index lists for the
        union of the given face set on `obj`. Returns (verts, faces)."""
        mesh = obj.data
        local_index = {}
        verts = []
        faces = []
        for fi in face_idx_set:
            if fi < 0 or fi >= len(mesh.polygons):
                continue
            poly = mesh.polygons[fi]
            f_local = []
            for vi in poly.vertices:
                if vi not in local_index:
                    co = mesh.vertices[vi].co
                    h = np.array([co.x, co.y, co.z, 1.0]) @ mw_np.T
                    local_index[vi] = len(verts)
                    verts.append(h[:3])
                f_local.append(local_index[vi])
            faces.append(f_local)
        return np.asarray(verts, dtype=np.float64) if verts else np.zeros((0, 3)), faces
```

- [ ] **Step 2: Wire A-key in `modal`**

In the `if event.value == "PRESS":` block:

```python
            if event.type == "A":
                if self.mode != MODE_PICK_TGT_POLY or self.ref_signature is None:
                    return {"RUNNING_MODAL"}
                if self.show_match_hints:
                    self.show_match_hints = False
                    self.match_hints = {}
                else:
                    self._search_matches(context)
                    self.show_match_hints = True
                return {"RUNNING_MODAL"}
```

- [ ] **Step 3: Draw match hints**

In `_draw_preview_3d`, after the target-polys block (added in Task 8), add:

```python
    # Match hints — A-key candidates.
    if op.show_match_hints and op.match_hints:
        hint_store = {obj: set().union(*comps) for obj, comps in op.match_hints.items()}
        tris = _selected_face_tris_world(hint_store)
        if tris:
            tris = _bias_toward_view(tris, rv3d)
            with draw_scope(blend="ALPHA", depth="LESS_EQUAL",
                            face_culling="NONE", depth_mask=False):
                iops_draw.tris(tris, role=Role.GHOST_MATCH_HINT, context=context)
```

- [ ] **Step 4: Smoke check**

In a scene with the ref poly set committed, press A and confirm a green dim overlay appears on geometry that's "shape-similar" to ref. Re-press A and the overlay disappears.

- [ ] **Step 5: Commit**

```bash
git add operators/object_aligner.py
git commit -m "feat(object_aligner): A-key match-hint search and overlay"
```

---

## Task 11: Operator — W-key force toggle + Alt+Wheel RMSE adjust

**Files:**
- Modify: `operators/object_aligner.py`

- [ ] **Step 1: Add W and Alt+Wheel branches in `modal`**

In the `if event.value == "PRESS":` block:

```python
            if event.type == "W":
                if self.mode == MODE_PICK_TGT_POLY:
                    self.force_mode = not self.force_mode
                return {"RUNNING_MODAL"}
```

For Alt+Wheel, the press-event check above is for `event.value == "PRESS"`. Wheel events arrive as `WHEELUPMOUSE` / `WHEELDOWNMOUSE` with value `"PRESS"`. Place this branch alongside:

```python
            if event.alt and event.type in {"WHEELUPMOUSE", "WHEELDOWNMOUSE"}:
                if self.mode != MODE_PICK_TGT_POLY:
                    return {"PASS_THROUGH"}
                step = 0.005
                if event.type == "WHEELUPMOUSE":
                    self.match_rmse_threshold = min(0.5, self.match_rmse_threshold + step)
                else:
                    self.match_rmse_threshold = max(0.001, self.match_rmse_threshold - step)
                return {"RUNNING_MODAL"}
```

- [ ] **Step 2: Smoke check**

Confirm via console probe (add `print(self.match_rmse_threshold)` temporarily) that Alt+Wheel adjusts the value within `[0.001, 0.5]` in 0.005 steps.

- [ ] **Step 3: Commit**

```bash
git add operators/object_aligner.py
git commit -m "feat(object_aligner): W force-mode toggle + Alt+Wheel RMSE threshold"
```

---

## Task 12: Operator — HUD and Help updates

**Files:**
- Modify: `operators/object_aligner.py`

- [ ] **Step 1: Extend `_build_hud`**

Replace the body of `_build_hud`:

```python
def _build_hud(context, op):
    hud = HUDOverlay("object_aligner")
    hud.title = "Object Aligner"
    hud.bind_region(context.region)

    def _mode_label():
        return {
            MODE_PICK_REF: "Pick reference",
            MODE_STAMP: "Stamp",
            MODE_PICK_REF_POLY: "Pick ref polys",
            MODE_PICK_TGT_POLY: "Pick target polys",
        }.get(op.mode, op.mode)

    hud.add_param(HUDParam("Mode", _mode_label))
    hud.add_param(HUDParam("Reference", lambda: op.ref_name or "—",
                           visible_getter=lambda: bool(op.ref_name)))
    hud.add_param(HUDParam("Ref polys",
                           lambda: sum(len(s) for s in op.ref_polys.values()),
                           kind="int",
                           visible_getter=lambda: bool(op.ref_polys)))
    hud.add_param(HUDParam("Target polys",
                           lambda: sum(len(s) for s in op.target_polys.values()),
                           kind="int",
                           visible_getter=lambda: bool(op.target_polys)))
    hud.add_param(HUDParam("Match ε",
                           lambda: op.match_rmse_threshold,
                           kind="float", fmt="{:.3f}",
                           visible_getter=lambda: op.mode == MODE_PICK_TGT_POLY))
    hud.add_param(HUDParam("Force fit",
                           lambda: "on" if op.force_mode else "off",
                           visible_getter=lambda: op.mode == MODE_PICK_TGT_POLY))
    hud.add_param(HUDParam("Clone", lambda: op.clone_mode))
    hud.add_param(HUDParam("Scale", lambda: SCALE_LABELS.get(op.scale_mode, op.scale_mode)))
    hud.add_param(HUDParam("Fit", lambda: op.last_fit or "—",
                           visible_getter=lambda: bool(op.last_fit)))
    hud.add_param(HUDParam("Stamped", lambda: op.stamped_count, kind="int"))
    return hud
```

- [ ] **Step 2: Extend `_build_help`**

Replace the `helpo.add_section(...)` content:

```python
    helpo.add_section(HUDSection("Object Aligner", [
        HUDItem("Pick reference / target", "LMB",          ItemState.ON, default_state=ItemState.OFF, always_show=True),
        HUDItem("Re-pick reference",       "R",            ItemState.ON, default_state=ItemState.OFF, always_show=True),
        HUDItem("Toggle ref-poly mode",    "Q",            ItemState.ON, default_state=ItemState.OFF, always_show=True),
        HUDItem("Add linked island",       "Shift+LMB",    ItemState.ON, default_state=ItemState.OFF, always_show=True),
        HUDItem("Add similar (normal/area)", "Ctrl+LMB",   ItemState.ON, default_state=ItemState.OFF, always_show=True),
        HUDItem("Remove polygon / island", "Alt+LMB",      ItemState.ON, default_state=ItemState.OFF, always_show=True),
        HUDItem("Toggle match hints",      "A",            ItemState.ON, default_state=ItemState.OFF, always_show=True),
        HUDItem("Toggle force fit",        "W",            ItemState.ON, default_state=ItemState.OFF, always_show=True),
        HUDItem("Adjust match threshold",  "Alt+Wheel",    ItemState.ON, default_state=ItemState.OFF, always_show=True),
        HUDItem("Clone type (Duplicate/Instance)", "D",    ItemState.ON, default_state=ItemState.OFF, always_show=True),
        HUDItem("Scale (Uniform/Keep/Stretch)",    "S",    ItemState.ON, default_state=ItemState.OFF, always_show=True),
        HUDItem("Apply",                   "Enter / Space / RMB", ItemState.ON, default_state=ItemState.OFF, always_show=True),
        HUDItem("Cancel",                  "Esc",          ItemState.ON, default_state=ItemState.OFF, always_show=True),
        HUDItem("Help / HUD",              "H",            ItemState.ON, default_state=ItemState.OFF, always_show=True),
    ]))
```

- [ ] **Step 3: Smoke check**

Invoke the operator and toggle H. Confirm the help panel shows the new entries and HUD shows Mode/Ref polys/Target polys/Match ε/Force fit fields as appropriate.

- [ ] **Step 4: Commit**

```bash
git add operators/object_aligner.py
git commit -m "feat(object_aligner): HUD and Help for poly-ref mode"
```

---

## Task 13: Operator — Apply integration (per-component strict/force fit)

**Files:**
- Modify: `operators/object_aligner.py`

- [ ] **Step 1: Add a poly-aware fit dispatcher**

Append:

```python
    def _compute_fit_poly_strict(self, target_obj, component_face_idx_set):
        """Attempt Procrustes fit of ref points → component points. Returns
        (T_matrix, rmse, ok) where ok=True iff the strict-tier criteria all
        passed and RMSE/diag < self.match_rmse_threshold."""
        from ..utils import polygon_match as pm

        mw_np = np.array(target_obj.matrix_world)
        tgt_verts, tgt_faces = self._extract_component_verts(
            target_obj, component_face_idx_set, mw_np)
        tgt_sig = pm.signature(tgt_verts, tgt_faces)
        ref_sig = self.ref_signature
        if (tgt_sig.vert_count != ref_sig.vert_count
                or tgt_sig.face_count != ref_sig.face_count
                or tgt_sig.face_vcount_hist != ref_sig.face_vcount_hist):
            return None, float("inf"), False
        corr = pm.greedy_correspondence(self.ref_points_np, tgt_verts)
        tgt_reordered = tgt_verts[corr]
        T_np, rmse = pm.kabsch_with_scale(
            self.ref_points_np, tgt_reordered, scale_mode=self.scale_mode)
        denom = ref_sig.bbox_diag if ref_sig.bbox_diag > 1e-9 else 1.0
        ok = (rmse / denom) < self.match_rmse_threshold
        return _np_to_matrix(T_np), rmse, ok

    def _compute_fit_poly_force(self, target_obj, component_face_idx_set):
        """PCA-frame fit: T = frame_target · frame_ref⁻¹."""
        from ..utils import polygon_match as pm

        mw_np = np.array(target_obj.matrix_world)
        mesh = target_obj.data
        face_centroids, face_normals, face_areas = [], [], []
        verts_world, _ = self._extract_component_verts(
            target_obj, component_face_idx_set, mw_np)
        for fi in component_face_idx_set:
            if fi < 0 or fi >= len(mesh.polygons):
                continue
            poly = mesh.polygons[fi]
            n_local = np.array([poly.normal.x, poly.normal.y, poly.normal.z])
            n_world = mw_np[:3, :3] @ n_local
            nrm = np.linalg.norm(n_world)
            face_normals.append(n_world / nrm if nrm > 0 else np.array([0.0, 0.0, 1.0]))
            face_areas.append(float(poly.area))
            ws_centroid = np.array([0.0, 0.0, 0.0])
            for vi in poly.vertices:
                co = mesh.vertices[vi].co
                h = np.array([co.x, co.y, co.z, 1.0]) @ mw_np.T
                ws_centroid += h[:3]
            ws_centroid /= len(poly.vertices)
            face_centroids.append(ws_centroid)
        tgt_frame = pm.pca_frame(
            verts_world,
            np.asarray(face_centroids),
            np.asarray(face_normals),
            np.asarray(face_areas),
        )
        T_np = tgt_frame @ np.linalg.inv(self.ref_frame_np)
        return _np_to_matrix(T_np)
```

- [ ] **Step 2: Build pending stamps on Apply**

Add a new method:

```python
    def _enqueue_target_poly_stamps(self, context):
        """Decompose self.target_polys per-object into connected components,
        compute a fit for each, append to self.pending. Returns (matched,
        forced, skipped) counts for reporting."""
        from ..utils import polygon_match as pm

        matched = forced = skipped = 0
        for obj, face_idx_set in self.target_polys.items():
            try:
                bm = _bmesh_for(self, obj)
            except (RuntimeError, ReferenceError):
                skipped += 1
                continue
            comps = pm.components_in_selection(bm, face_idx_set)
            for comp in comps:
                T_strict, _rmse, ok = self._compute_fit_poly_strict(obj, comp)
                if ok:
                    self.pending.append({
                        "target": obj,
                        "matrix": T_strict,
                        "linked": self.clone_mode == CLONE_INST,
                    })
                    self.last_fit = "poly-strict"
                    self.stamped_count += 1
                    matched += 1
                    continue
                if self.force_mode:
                    T_force = self._compute_fit_poly_force(obj, comp)
                    self.pending.append({
                        "target": obj,
                        "matrix": T_force,
                        "linked": self.clone_mode == CLONE_INST,
                    })
                    self.last_fit = "poly-force"
                    self.stamped_count += 1
                    forced += 1
                else:
                    skipped += 1
        return matched, forced, skipped
```

- [ ] **Step 3: Route Apply through the new path when poly mode is active**

Replace the Apply block in `modal`:

```python
        if event.type in {"RET", "NUMPAD_ENTER", "SPACE", "RIGHTMOUSE"} and event.value == "PRESS":
            if self.mode == MODE_PICK_TGT_POLY:
                m, f, s = self._enqueue_target_poly_stamps(context)
                self._realize_pending(context)
                self._finish(context)
                self.report({"INFO"},
                            f"Aligner: stamped {m} match + {f} forced ({s} skipped)")
                return {"FINISHED"}
            self._realize_pending(context)
            self._finish(context)
            self.report({"INFO"}, f"Aligner: stamped {self.stamped_count}")
            return {"FINISHED"}
```

- [ ] **Step 4: Smoke check end-to-end**

Via blender-mcp, build a scene with:
- A rig (1 cube named "Rig").
- A reference object (a cube named "Ref") with one face marked.
- Two target objects: "TgtA" — identical topology to ref; "TgtB" — different topology (different face shape).

Walk through:
1. Select rig, invoke operator.
2. Pick Ref via LMB.
3. Press Q, click the same face on Ref → marked.
4. Press Q to commit.
5. Click the corresponding face on TgtA → highlight amber.
6. Click a face on TgtB → highlight amber.
7. Press Enter.

Expected:
- One rig is stamped onto TgtA (Procrustes fit).
- TgtB skipped (report says "0 forced, 1 skipped").

Then repeat with `W` enabled before Apply → TgtB also gets stamped via PCA-frame.

- [ ] **Step 5: Commit**

```bash
git add operators/object_aligner.py
git commit -m "feat(object_aligner): apply poly-ref stamps — strict+force fit"
```

---

## Task 14: Final integration smoke test + edge cases

**Files:** none — pure verification.

- [ ] **Step 1: Empty ref-set guard**

Smoke: enter `MODE_PICK_REF_POLY`, immediately press Q without marking. Expect: report `"Ref poly set is empty"`, mode stays in PICK_REF_POLY.

- [ ] **Step 2: Cancel cleanliness**

Smoke: invoke → Q → mark polys → Esc. Expect: no leftover objects, no leftover collections, no exceptions in console. Confirm bmesh cache empties:

```python
op_state = "(verified via temp print in _finish)"
```

- [ ] **Step 3: Multi-object target selection**

Smoke: mark target polys on two different objects, both with topology matching ref. Apply. Expect: rig stamped at both component frames.

- [ ] **Step 4: Match-hint search performance**

Smoke: build a scene with ~5 cubes + an icosphere (200 faces) + a torus (576 faces). Press A. Confirm response is sub-second (informally — the algorithm is O(faces) per object with cheap descriptors). Document timing in commit message.

- [ ] **Step 5: Modifier safety**

Smoke: add a Mirror modifier to a target object. Apply ray-pick on the mirrored side. Confirm the `face_idx >= len(polygons)` guard prevents crashes (operator should ignore the click, no exception).

- [ ] **Step 6: Run pytest one final time**

```bash
python -m pytest tests/test_polygon_match.py -v
```

Expected: all 15 tests still PASS.

- [ ] **Step 7: Commit the final smoke-test notes**

If any tweaks were needed during smoke, commit them; otherwise this step is a no-op.

```bash
git status
# If nothing to commit, skip. Otherwise:
git add operators/object_aligner.py
git commit -m "fix(object_aligner): smoke-test corrections"
```

---

## Deferred (out of scope for this plan)

The spec describes a **hovered-component RMSE preview** in the HUD: when the user mouses over a face that belongs to a component inside `op.target_polys` or `op.match_hints`, the per-component RMSE is computed and shown next to the threshold value. This is intentionally deferred — it adds complexity (per-component cache, hover-component identification per mouse-move) and the core feature is usable without it. The user can already dial the threshold via Alt+Wheel and observe stamp/skip behavior at Apply time. File a follow-up if it turns out to be needed in practice.
