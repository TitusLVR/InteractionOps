# iOps Falloff Tools Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Three edit-mesh modal operators (`iops.mesh_falloff_move` / `_rotate` / `_scale`) that transform the selection with a Modo-style per-vertex falloff (Linear, Radial, Screen, Coplanar) switchable by hotkey inside the modal, with an Element (connected-only) toggle, weight preview, and Modo click-drag interaction.

**Architecture:** All math lives in a bpy-free numpy module `utils/falloff_core.py` covered by pytest. A mixin in `operators/falloff/common.py` owns the modal lifecycle (bmesh snapshot → numpy `P0`, weights, hotkeys, handles, HUD, drawing, undo); `operators/falloff/ops.py` holds three thin subclasses that only differ in how a mouse drag becomes an amount and how that amount is applied. Two new draw primitives (`ring_3d`, `points_colored`) go into the shared `ui/draw` layer. Last-used settings persist in `Scene.IOPS`.

**Tech Stack:** Blender 5.x Python (`bpy`, `bmesh`, `gpu`, `bpy_extras.view3d_utils`), numpy (bundled with Blender), pytest for the core module, existing iOps `ui/draw` + `ui/hud` layers.

**Spec:** `docs/superpowers/specs/2026-09-07-modo-falloff-tools-design.md` (read it first; the analysis it links is background only).

## Global Constraints

- Blender 5.x API only: no `bgl`, no `gpu.types.GPUShader(vert, frag)`; wide lines via `POLYLINE_UNIFORM_COLOR` (already wrapped in `ui/draw/shaders.py`).
- `utils/falloff_core.py` and `tests/test_falloff_core.py` must not import `bpy`, `bmesh`, or `mathutils`. numpy only.
- Run pytest from `tests/`: `cd D:/git/InteractionOps/tests && python -m pytest test_falloff_core.py -v` (Python 3.11 at `C:\Users\cvitk\AppData\Local\Programs\Python\Python311\python.exe`; numpy 2.4 installed).
- Operator idnames must start with `iops.mesh_` (keymap routing in `utils/functions.py:680` sends them to the Mesh keymap). Set `is_bindable = True`, no `keys_default` entry.
- `bl_options = {"REGISTER"}` and a manual `bpy.ops.ed.undo_push(...)` after the final `update_edit_mesh` on confirm only. Never push mid-modal.
- `_finish()` must null every bmesh reference (`self.bm`, `self.obj`, vert lists) — redo-stack dealloc crash guard (`operators/mesh_shear.py:2001-2005`).
- All blf text drawing goes through `ui/hud/text.py`; wrap HUD draws in `text.isolated(theme)`.
- Draw handlers via `safe_handler_add` / `safe_handler_remove` from `ui/draw`.
- Plain wheel passes through (viewport zoom). Shift+Wheel adjusts the falloff scalar; Ctrl+Shift+Wheel is the fine step.
- Coplanar default angle 5°, Screen default radius 150 px.
- Commit messages: Conventional Commits, no mention of CCP or any employer. End each with `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`.
- Do NOT create git worktrees; work on a branch `falloff-tools` in the main checkout (`git checkout -b falloff-tools` before Task 1).
- Live-Blender checks (Task 8) must first verify `bpy.data.filepath` is a scratch/test file (empty string or under `V:\temp_blends\` or `B:\test\`). Anything else → report BLOCKED, do not touch the session.
- ruff config `ruff.toml` applies: run `ruff check <files>` before each commit.

---

## File map

| File | Responsibility |
|---|---|
| `utils/falloff_core.py` (new) | Constants, shape curves, weight functions, projection, BFS masks, autofit, apply_move/rotate/scale. numpy only. |
| `tests/test_falloff_core.py` (new) | pytest for every function above. |
| `ui/draw/shaders.py` (modify) | add `point_flat_color()` cached builtin. |
| `ui/draw/primitives.py` (modify) | add `ring_3d(...)`, `points_colored(...)`. |
| `prefs/addon_properties.py` (modify) | seven `Scene.IOPS` falloff props. |
| `operators/falloff/__init__.py` (new, empty) | package marker. |
| `operators/falloff/common.py` (new) | `FalloffToolMixin`: state, weights, HUD, hotkeys, handles, drawing, finish. |
| `operators/falloff/ops.py` (new) | `IOPS_OT_mesh_falloff_move / _rotate / _scale`. |
| `__init__.py` (modify) | import + register the three classes. |
| `docs/operators/op_mesh_falloff_tools.md` (new), `mkdocs.yml` (modify) | user docs + nav. |

---

### Task 1: falloff_core — shape curves and distance-based weights

**Files:**
- Create: `utils/falloff_core.py`
- Test: `tests/test_falloff_core.py`

**Interfaces:**
- Produces:
  - `FALLOFF_TYPES = ("LINEAR", "RADIAL", "SCREEN", "COPLANAR")`
  - `SHAPES = ("LINEAR", "SMOOTH", "SHARP", "ROOT", "SPHERE", "INVERSE_SQUARE", "CONSTANT")`
  - `shape_curve(name: str, x: np.ndarray) -> np.ndarray` (clamps x to [0,1] first)
  - `apply_invert(w: np.ndarray) -> np.ndarray`
  - `weight_linear(P: (N,3), S: (3,), E: (3,)) -> (N,)` — 1 at S, 0 at E, clamped
  - `weight_radial(P: (N,3), C: (3,), r: float) -> (N,)`
  - `weight_screen(P2: (N,2), center2: (2,), r_px: float, valid: (N,) bool | None) -> (N,)`
  - `project_points(Pw: (N,3), persp: (4,4), width: int, height: int) -> tuple[(N,2), (N,) bool]` — world → region pixels using a world-to-clip matrix; `valid` False where clip w ≤ 0

- [ ] **Step 1: Create the test file with the failing tests**

```python
# tests/test_falloff_core.py
import math
import numpy as np
import pytest

from utils import falloff_core as fc


# ---------------------------------------------------------------- shapes

def test_shape_names_are_stable():
    assert fc.FALLOFF_TYPES == ("LINEAR", "RADIAL", "SCREEN", "COPLANAR")
    assert fc.SHAPES == ("LINEAR", "SMOOTH", "SHARP", "ROOT", "SPHERE",
                         "INVERSE_SQUARE", "CONSTANT")


@pytest.mark.parametrize("name", fc.SHAPES)
def test_shape_endpoints(name):
    x = np.array([0.0, 1.0])
    y = fc.shape_curve(name, x)
    if name == "CONSTANT":
        assert y.tolist() == [1.0, 1.0]
    else:
        assert y[0] == pytest.approx(0.0)
        assert y[1] == pytest.approx(1.0)


@pytest.mark.parametrize("name", [s for s in fc.SHAPES if s != "CONSTANT"])
def test_shape_monotonic_and_clamped(name):
    x = np.linspace(-0.5, 1.5, 41)
    y = fc.shape_curve(name, x)
    assert np.all(np.diff(y) >= -1e-12)
    assert y.min() >= 0.0 and y.max() <= 1.0 + 1e-12


def test_shape_midpoints_match_blender_formulas():
    x = np.array([0.5])
    assert fc.shape_curve("LINEAR", x)[0] == pytest.approx(0.5)
    assert fc.shape_curve("SMOOTH", x)[0] == pytest.approx(0.5)          # 3x²-2x³
    assert fc.shape_curve("SHARP", x)[0] == pytest.approx(0.25)          # x²
    assert fc.shape_curve("ROOT", x)[0] == pytest.approx(math.sqrt(0.5))
    assert fc.shape_curve("SPHERE", x)[0] == pytest.approx(math.sqrt(0.75))  # sqrt(2x-x²)
    assert fc.shape_curve("INVERSE_SQUARE", x)[0] == pytest.approx(0.75) # x(2-x)


def test_shape_unknown_name_raises():
    with pytest.raises(KeyError):
        fc.shape_curve("BOGUS", np.array([0.5]))


def test_apply_invert():
    w = np.array([0.0, 0.25, 1.0])
    assert fc.apply_invert(w).tolist() == [1.0, 0.75, 0.0]


# ---------------------------------------------------------------- linear

def test_weight_linear_start_end_mid_beyond():
    S = np.array([0.0, 0.0, 0.0])
    E = np.array([2.0, 0.0, 0.0])
    P = np.array([[0.0, 0, 0], [2.0, 0, 0], [1.0, 5, 5], [-1.0, 0, 0], [3.0, 0, 0]])
    w = fc.weight_linear(P, S, E)
    assert w.tolist() == pytest.approx([1.0, 0.0, 0.5, 1.0, 0.0])


def test_weight_linear_degenerate_axis_is_full_weight():
    S = np.zeros(3)
    P = np.array([[1.0, 2.0, 3.0]])
    w = fc.weight_linear(P, S, S)
    assert w.tolist() == [1.0]


# ---------------------------------------------------------------- radial

def test_weight_radial_center_edge_outside():
    C = np.array([1.0, 1.0, 1.0])
    P = np.array([[1.0, 1, 1], [3.0, 1, 1], [1.0, 2, 1], [9.0, 9, 9]])
    w = fc.weight_radial(P, C, 2.0)
    assert w.tolist() == pytest.approx([1.0, 0.0, 0.5, 0.0])


def test_weight_radial_zero_radius_is_safe():
    w = fc.weight_radial(np.array([[0.0, 0, 0], [1.0, 0, 0]]), np.zeros(3), 0.0)
    assert w.tolist() == [1.0, 0.0]


# ---------------------------------------------------------------- screen

def test_weight_screen_center_edge_and_invalid_rows():
    P2 = np.array([[100.0, 100.0], [150.0, 100.0], [125.0, 100.0], [100.0, 100.0]])
    valid = np.array([True, True, True, False])
    w = fc.weight_screen(P2, np.array([100.0, 100.0]), 50.0, valid)
    assert w.tolist() == pytest.approx([1.0, 0.0, 0.5, 0.0])


def test_project_points_identity_matrix_maps_ndc_to_pixels():
    # identity "perspective": clip == world, so (0,0) → region centre,
    # (1,1) → top-right corner, w<=0 rows are invalid
    Pw = np.array([[0.0, 0.0, 0.0], [1.0, 1.0, 0.0]])
    P2, valid = fc.project_points(Pw, np.eye(4), 200, 100)
    assert P2[0].tolist() == pytest.approx([100.0, 50.0])
    assert P2[1].tolist() == pytest.approx([200.0, 100.0])
    assert valid.tolist() == [True, True]


def test_project_points_behind_camera_invalid():
    M = np.eye(4)
    M[3, 3] = 0.0
    M[3, 2] = 1.0            # w = z
    Pw = np.array([[0.0, 0.0, 2.0], [0.0, 0.0, -2.0]])
    P2, valid = fc.project_points(Pw, M, 200, 100)
    assert valid.tolist() == [True, False]
    assert np.isfinite(P2[0]).all()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd D:/git/InteractionOps/tests && python -m pytest test_falloff_core.py -v`
Expected: collection error `ModuleNotFoundError: No module named 'utils.falloff_core'`.

- [ ] **Step 3: Write the implementation**

```python
# utils/falloff_core.py
"""Pure-numpy falloff math (no bpy) so pytest can cover it.

Weights are floats in [0, 1]: 1 = fully affected, 0 = untouched.
Every function takes and returns numpy arrays; `P` is (N, 3) object-space
coordinates, `W` is (N,).

Shape curves and formulas follow Blender's proportional-editing table
(source/blender/editors/transform/transform_generics.cc), minus RANDOM.
"""
from __future__ import annotations

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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd D:/git/InteractionOps/tests && python -m pytest test_falloff_core.py -v`
Expected: all PASS (24 tests).

- [ ] **Step 5: Lint and commit**

```bash
cd D:/git/InteractionOps && ruff check utils/falloff_core.py tests/test_falloff_core.py
git add utils/falloff_core.py tests/test_falloff_core.py
git commit -m "feat(falloff): core shape curves and distance weights

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 2: falloff_core — coplanar weights, connectivity masks, autofit

**Files:**
- Modify: `utils/falloff_core.py` (append)
- Test: `tests/test_falloff_core.py` (append)

**Interfaces:**
- Consumes: nothing beyond Task 1.
- Produces:
  - `weight_coplanar_faces(FN: (F,3), n_ref: (3,), angle_rad: float) -> (F,)` — `1 − angle/angle_rad`, clamped
  - `vertex_weights_from_faces(face_rows: list[list[int]], wf: (F,), n_verts: int) -> (N,)` — max over incident faces, 0 for verts with no face
  - `connected_mask(adj: list[list[int]], seeds: iterable[int], n: int) -> (N,) bool` — BFS over vertex adjacency
  - `coplanar_grow(face_adj: list[list[int]], wf: (F,), seed_faces: iterable[int]) -> (F,) bool` — BFS over faces, stepping only onto faces with `wf > 0`; seeds always included
  - `bbox_center(P: (K,3)) -> (3,)`
  - `autofit_linear(P: (K,3)) -> (S (3,), E (3,))` — along the longest bbox axis; degenerate extent → `E = S + (1,0,0)`
  - `autofit_radial(P: (K,3)) -> (C (3,), r: float)` — `r = max(half diagonal, 1e-4)`

- [ ] **Step 1: Append the failing tests**

```python
# tests/test_falloff_core.py (append)

# ---------------------------------------------------------------- coplanar

def test_weight_coplanar_faces_angle_ramp():
    n_ref = np.array([0.0, 0.0, 1.0])
    a = math.radians(10.0)
    FN = np.array([
        [0.0, 0.0, 1.0],                                  # 0° → 1
        [math.sin(a / 2), 0.0, math.cos(a / 2)],          # 5° → 0.5
        [math.sin(a), 0.0, math.cos(a)],                  # 10° → 0
        [1.0, 0.0, 0.0],                                  # 90° → 0
    ])
    w = fc.weight_coplanar_faces(FN, n_ref, a)
    assert w.tolist() == pytest.approx([1.0, 0.5, 0.0, 0.0], abs=1e-6)


def test_weight_coplanar_zero_angle_only_exact_matches():
    FN = np.array([[0.0, 0.0, 1.0], [0.001, 0.0, 0.999999]])
    w = fc.weight_coplanar_faces(FN, np.array([0.0, 0.0, 1.0]), 0.0)
    assert w[0] == pytest.approx(1.0)
    assert w[1] == pytest.approx(0.0)


def test_vertex_weights_from_faces_takes_max():
    face_rows = [[0, 1, 2], [2, 3]]
    wf = np.array([0.2, 0.9])
    w = fc.vertex_weights_from_faces(face_rows, wf, 5)
    assert w.tolist() == pytest.approx([0.2, 0.2, 0.9, 0.9, 0.0])


# ---------------------------------------------------------------- connectivity

def test_connected_mask_two_islands():
    # island A: 0-1-2, island B: 3-4
    adj = [[1], [0, 2], [1], [4], [3]]
    m = fc.connected_mask(adj, [0], 5)
    assert m.tolist() == [True, True, True, False, False]


def test_connected_mask_multiple_seeds():
    adj = [[1], [0], [3], [2], []]
    m = fc.connected_mask(adj, [0, 2], 5)
    assert m.tolist() == [True, True, True, True, False]


def test_coplanar_grow_stops_at_hard_edge():
    # faces in a strip 0-1-2-3; face 2 is tilted (wf=0) so 3 is unreachable
    face_adj = [[1], [0, 2], [1, 3], [2]]
    wf = np.array([1.0, 0.7, 0.0, 1.0])
    keep = fc.coplanar_grow(face_adj, wf, [0])
    assert keep.tolist() == [True, True, False, False]


def test_coplanar_grow_seed_kept_even_if_zero_weight():
    keep = fc.coplanar_grow([[1], [0]], np.array([0.0, 1.0]), [0])
    assert keep.tolist() == [True, True]


# ---------------------------------------------------------------- autofit

def test_bbox_center():
    P = np.array([[0.0, 0.0, 0.0], [2.0, 4.0, 6.0]])
    assert fc.bbox_center(P).tolist() == [1.0, 2.0, 3.0]


def test_autofit_linear_longest_axis():
    P = np.array([[0.0, 0.0, 0.0], [1.0, 5.0, 2.0]])
    S, E = fc.autofit_linear(P)
    assert S.tolist() == pytest.approx([0.5, 0.0, 1.0])
    assert E.tolist() == pytest.approx([0.5, 5.0, 1.0])


def test_autofit_linear_degenerate_gets_unit_x():
    P = np.array([[1.0, 1.0, 1.0]])
    S, E = fc.autofit_linear(P)
    assert S.tolist() == [1.0, 1.0, 1.0]
    assert E.tolist() == [2.0, 1.0, 1.0]


def test_autofit_radial():
    P = np.array([[0.0, 0.0, 0.0], [2.0, 0.0, 0.0]])
    C, r = fc.autofit_radial(P)
    assert C.tolist() == [1.0, 0.0, 0.0]
    assert r == pytest.approx(1.0)
    C, r = fc.autofit_radial(np.array([[3.0, 3.0, 3.0]]))
    assert r == pytest.approx(1e-4)
```

- [ ] **Step 2: Run to verify the new tests fail**

Run: `cd D:/git/InteractionOps/tests && python -m pytest test_falloff_core.py -v`
Expected: the 11 new tests FAIL with `AttributeError: module 'utils.falloff_core' has no attribute ...`; Task 1 tests still pass.

- [ ] **Step 3: Append the implementation**

```python
# utils/falloff_core.py (append)
from collections import deque  # noqa: E402  (keep at top of file in practice)


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
```

Move `from collections import deque` up to the imports block at the top of the file (next to `import numpy as np`) rather than leaving it mid-file.

- [ ] **Step 4: Run the tests**

Run: `cd D:/git/InteractionOps/tests && python -m pytest test_falloff_core.py -v`
Expected: 35 PASS.

- [ ] **Step 5: Lint and commit**

```bash
cd D:/git/InteractionOps && ruff check utils/falloff_core.py tests/test_falloff_core.py
git add utils/falloff_core.py tests/test_falloff_core.py
git commit -m "feat(falloff): coplanar weights, connectivity masks, autofit

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 3: falloff_core — weighted move / rotate / scale

**Files:**
- Modify: `utils/falloff_core.py` (append)
- Test: `tests/test_falloff_core.py` (append)

**Interfaces:**
- Produces:
  - `apply_move(P0: (N,3), W: (N,), delta: (3,)) -> (N,3)`
  - `apply_rotate(P0: (N,3), W: (N,), pivot: (3,), axis: (3,), angle: float) -> (N,3)` — per-vertex angle `W·angle`, Rodrigues; axis normalised inside; zero axis → returns `P0.copy()`
  - `apply_scale(P0: (N,3), W: (N,), pivot: (3,), s: float | (3,)) -> (N,3)` — `pivot + (1 + W (s − 1)) (P0 − pivot)`, `s` scalar or per-axis

- [ ] **Step 1: Append the failing tests**

```python
# tests/test_falloff_core.py (append)

# ---------------------------------------------------------------- apply

P0 = np.array([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [2.0, 2.0, 2.0]])


def test_apply_move_weighted():
    W = np.array([1.0, 0.5, 0.0])
    P = fc.apply_move(P0, W, np.array([2.0, 0.0, 0.0]))
    assert P.tolist() == pytest.approx([[3.0, 0, 0], [1.0, 1, 0], [2.0, 2, 2]])


def test_apply_rotate_full_weight_is_rigid():
    W = np.ones(3)
    P = fc.apply_rotate(P0, W, np.zeros(3), np.array([0.0, 0.0, 1.0]), math.pi / 2)
    assert P[0].tolist() == pytest.approx([0.0, 1.0, 0.0], abs=1e-9)
    assert P[1].tolist() == pytest.approx([-1.0, 0.0, 0.0], abs=1e-9)
    assert P[2].tolist() == pytest.approx([-2.0, 2.0, 2.0], abs=1e-9)


def test_apply_rotate_half_weight_is_half_angle():
    W = np.array([0.5, 0.0, 0.0])
    P = fc.apply_rotate(P0, W, np.zeros(3), np.array([0.0, 0.0, 1.0]), math.pi / 2)
    s = math.sqrt(0.5)
    assert P[0].tolist() == pytest.approx([s, s, 0.0], abs=1e-9)
    assert P[1].tolist() == pytest.approx(P0[1].tolist())


def test_apply_rotate_about_offset_pivot_and_unnormalised_axis():
    W = np.ones(1)
    P = fc.apply_rotate(np.array([[2.0, 0.0, 0.0]]), W, np.array([1.0, 0.0, 0.0]),
                        np.array([0.0, 0.0, 5.0]), math.pi)
    assert P[0].tolist() == pytest.approx([0.0, 0.0, 0.0], abs=1e-9)


def test_apply_rotate_zero_axis_is_identity():
    P = fc.apply_rotate(P0, np.ones(3), np.zeros(3), np.zeros(3), 1.0)
    assert P.tolist() == P0.tolist()


def test_apply_scale_uniform_weighted():
    W = np.array([1.0, 0.5, 0.0])
    P = fc.apply_scale(P0, W, np.zeros(3), 3.0)
    assert P.tolist() == pytest.approx([[3.0, 0, 0], [0.0, 2.0, 0], [2.0, 2, 2]])


def test_apply_scale_per_axis_about_pivot():
    W = np.ones(1)
    P = fc.apply_scale(np.array([[2.0, 2.0, 2.0]]), W, np.array([1.0, 1.0, 1.0]),
                       np.array([2.0, 1.0, 0.0]))
    assert P[0].tolist() == pytest.approx([3.0, 2.0, 1.0])


def test_apply_functions_do_not_mutate_input():
    P0c = P0.copy()
    fc.apply_move(P0, np.ones(3), np.ones(3))
    fc.apply_rotate(P0, np.ones(3), np.zeros(3), np.array([0.0, 0.0, 1.0]), 1.0)
    fc.apply_scale(P0, np.ones(3), np.zeros(3), 2.0)
    assert P0.tolist() == P0c.tolist()
```

- [ ] **Step 2: Run to verify the new tests fail**

Run: `cd D:/git/InteractionOps/tests && python -m pytest test_falloff_core.py -v -k apply`
Expected: FAIL with `AttributeError ... apply_move`.

- [ ] **Step 3: Append the implementation**

```python
# utils/falloff_core.py (append)

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


def apply_scale(P0: np.ndarray, W: np.ndarray, pivot, s) -> np.ndarray:
    """pivot + (1 + W (s - 1)) (P0 - pivot); `s` scalar or per-axis (3,)."""
    P0 = np.asarray(P0, dtype=np.float64)
    W = np.asarray(W, dtype=np.float64)[:, None]
    C = np.asarray(pivot, dtype=np.float64)
    sv = np.asarray(s, dtype=np.float64)
    if sv.ndim == 0:
        sv = np.full(3, float(sv))
    return C + (1.0 + W * (sv - 1.0)) * (P0 - C)
```

- [ ] **Step 4: Run all core tests**

Run: `cd D:/git/InteractionOps/tests && python -m pytest test_falloff_core.py -v`
Expected: 43 PASS.

- [ ] **Step 5: Lint and commit**

```bash
cd D:/git/InteractionOps && ruff check utils/falloff_core.py tests/test_falloff_core.py
git add utils/falloff_core.py tests/test_falloff_core.py
git commit -m "feat(falloff): weighted move, rotate, scale

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 4: draw primitives — `ring_3d` and `points_colored`

**Files:**
- Modify: `ui/draw/shaders.py` (add cached builtin after `polyline_uniform_color`)
- Modify: `ui/draw/primitives.py` (append two functions)

**Interfaces:**
- Produces:
  - `shaders.point_flat_color()` — cached `gpu.shader.from_builtin("POINT_FLAT_COLOR")`
  - `primitives.ring_3d(center, normal, radius, *, role=None, color=None, width=None, segments=64, theme=None, context=None)` — closed polyline in the plane ⟂ `normal`; coordinates in whatever space the current `gpu.matrix` expects (world for POST_VIEW)
  - `primitives.points_colored(coords, colors, *, size=6.0)` — one RGBA per point

No pytest (needs `gpu`); verified live in Task 8.

- [ ] **Step 1: Add the shader accessor**

In `ui/draw/shaders.py`, after `polyline_uniform_color()`:

```python
def point_flat_color():
    """Builtin per-vertex-colour points. Uniform: float `size`. Caller
    also sets gpu.state.point_size_set(size) for drivers that ignore
    the uniform."""
    s = _cache.get("POINT_FLAT_COLOR")
    if s is None:
        s = gpu.shader.from_builtin("POINT_FLAT_COLOR")
        _cache["POINT_FLAT_COLOR"] = s
    return s
```

Update the module docstring's "Three shaders" list to mention `POINT_FLAT_COLOR — builtin, per-vertex colour points (weight previews)`.

- [ ] **Step 2: Add the primitives**

Append to `ui/draw/primitives.py` (add `import math` and `from mathutils import Vector` to the imports):

```python
def ring_3d(center, normal, radius: float, *, role: Role | None = None,
            color: tuple[float, float, float, float] | None = None,
            width: str | None = None, segments: int = 64,
            theme: Theme | None = None, context=None) -> None:
    """Closed circle of `radius` around `center` in the plane
    perpendicular to `normal`. Coordinates are in the space the current
    gpu.matrix stack expects (world space inside a POST_VIEW handler)."""
    n = Vector(normal)
    if n.length_squared < 1e-18:
        return
    n.normalize()
    u = n.orthogonal().normalized()
    v = n.cross(u)
    c = Vector(center)
    pts = []
    step = 2.0 * math.pi / max(3, int(segments))
    for i in range(max(3, int(segments))):
        a = i * step
        pts.append(c + (u * math.cos(a) + v * math.sin(a)) * radius)
    pts.append(pts[0])
    polyline(pts, role=role, color=color, width=width, theme=theme,
             context=context)


def points_colored(coords: Sequence, colors: Sequence, *,
                   size: float = 6.0) -> None:
    """Per-point RGBA colours (weight previews). `colors` is one 4-tuple
    per coord."""
    if not coords:
        return
    shader = shaders.point_flat_color()
    batch = batch_for_shader(shader, "POINTS",
                             {"pos": list(coords), "color": list(colors)})
    shader.bind()
    shader.uniform_float("size", float(size))
    gpu.state.point_size_set(float(size))
    batch.draw(shader)
```

- [ ] **Step 3: Static check**

Run: `cd D:/git/InteractionOps && ruff check ui/draw/primitives.py ui/draw/shaders.py && python -c "import ast,sys; [ast.parse(open(f,encoding='utf-8').read()) for f in ['ui/draw/primitives.py','ui/draw/shaders.py']]; print('syntax ok')"`
Expected: no ruff findings, `syntax ok`.

- [ ] **Step 4: Commit**

```bash
git add ui/draw/primitives.py ui/draw/shaders.py
git commit -m "feat(draw): ring_3d and points_colored primitives

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 5: Scene.IOPS falloff properties

**Files:**
- Modify: `prefs/addon_properties.py` — inside `class IOPS_SceneProperties(PropertyGroup)` (starts line 370), after the "Smart Shear persistent parameters" block (~line 547)

**Interfaces:**
- Consumes: `FALLOFF_TYPES`, `SHAPES` from `utils/falloff_core.py`.
- Produces on `context.scene.IOPS`: `falloff_type` (enum of FALLOFF_TYPES, default `RADIAL`), `falloff_shape` (enum of SHAPES, default `SMOOTH`), `falloff_invert` (bool False), `falloff_connected` (bool False), `falloff_preview` (bool False), `falloff_screen_radius_px` (int 150, min 5, max 4000), `falloff_coplanar_angle` (float radians, default 5°, min 0, max 90°, subtype ANGLE).

- [ ] **Step 1: Add the import**

Near the top of `prefs/addon_properties.py` (after the `bpy.props` import block):

```python
from ..utils.falloff_core import FALLOFF_TYPES, SHAPES
```

- [ ] **Step 2: Add the properties**

After the `shear_extrude_last_distance` line inside `IOPS_SceneProperties`:

```python
    # Falloff tools (iops.mesh_falloff_move / _rotate / _scale) — last-used
    falloff_type: EnumProperty(
        name="Falloff Type",
        items=[(t, t.title(), "") for t in FALLOFF_TYPES],
        default="RADIAL",
    )
    falloff_shape: EnumProperty(
        name="Falloff Shape",
        items=[(s, s.replace("_", " ").title(), "") for s in SHAPES],
        default="SMOOTH",
    )
    falloff_invert: BoolProperty(name="Invert Falloff", default=False)
    falloff_connected: BoolProperty(name="Connected Only (Element)", default=False)
    falloff_preview: BoolProperty(name="Show Weights", default=False)
    falloff_screen_radius_px: IntProperty(name="Screen Radius (px)", default=150, min=5, max=4000)
    falloff_coplanar_angle: FloatProperty(
        name="Coplanar Angle", default=0.0872665, min=0.0, max=1.5707963,
        subtype="ANGLE",
    )
```

Check `EnumProperty`, `BoolProperty`, `IntProperty`, `FloatProperty` are already in the `from bpy.props import (...)` list at the top of the file (they are used by the existing cursor_bisect block; add any missing one).

- [ ] **Step 3: Static check**

Run: `cd D:/git/InteractionOps && ruff check prefs/addon_properties.py`
Expected: clean.

- [ ] **Step 4: Commit**

```bash
git add prefs/addon_properties.py
git commit -m "feat(falloff): persist last-used falloff settings in Scene.IOPS

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 6: `FalloffToolMixin` — lifecycle, weights, hotkeys, handles, drawing

**Files:**
- Create: `operators/falloff/__init__.py` (empty file)
- Create: `operators/falloff/common.py`

**Interfaces:**
- Consumes: everything in `utils/falloff_core.py`; `ui/draw` (`primitives`, `Role`, `draw_scope`, `safe_handler_add/remove`, `get_theme`); `ui/hud` (`HUDOverlay`, `HelpOverlay`, `HUDSection`, `HUDItem`, `HUDParam`, `ItemState`, `capture_event`); `ui/hud/text.isolated`; `operators/mesh_shear.DIGIT_TYPES`.
- Produces `class FalloffToolMixin` with:
  - class attrs subclasses override: `tool_label: str`, `undo_message: str`, `amount_label: str`, `amount_fmt: str`
  - subclass hooks (all must be implemented by the operator):
    - `_drag_begin(self, context, event) -> None` — record press-time data
    - `_drag_amount(self, context, event)` — current amount from the mouse (any type)
    - `_amount_from_number(self, value: float)` — typed number → amount
    - `_apply_amount(self, amount) -> np.ndarray` — `(N,3)` from `self._P0`, `self._W`
    - `_amount_text(self, amount) -> str`
  - shared state the hooks may read: `self._P0` (N,3), `self._W` (N,), `self._pivot` (3,), `self._axis` in `{None,"X","Y","Z"}`, `self._mouse_xy`, `self._drag` (dict with `"start": (x, y)` or None), `self.obj`, `self._mw` (matrix_world copy at invoke), `self._mw_inv3` (3x3 inverse for world→object vectors), `self._rv3d` (the invoking viewport's `RegionView3D`)
  - shared helpers: `_view_axis_object(self, rv3d) -> Vector`, `_axis_vector_object(self) -> Vector | None`, `_pivot_region_2d(self, context) -> Vector | None`, `_mouse_to_plane_object(self, context, xy) -> Vector | None` (mouse → world point on the view plane through the pivot → object space), `_snap(self, value, step)`
  - lifecycle: `invoke`, `modal`, `cancel`, `_finish`

- [ ] **Step 1: Create the package marker**

Create `operators/falloff/__init__.py` as an empty file (0 bytes; matches `operators/library/__init__.py`).

- [ ] **Step 2: Write `operators/falloff/common.py`**

```python
"""Shared modal machinery for the iOps Falloff tools
(iops.mesh_falloff_move / _rotate / _scale).

Modo-style: the falloff is drawn first, LMB on a handle edits it, LMB
anywhere else drags the transform, release bakes and the tool stays live.
All weights and transforms are numpy over the *visible* verts of the
active edit mesh (utils/falloff_core.py); only rows with weight > 0 are
written back to bmesh each tick.

Hotkeys inside the modal: L/R/S/C falloff type, E connected-only toggle,
F shape cycle, I invert, A auto-size, V weight preview, X/Y/Z axis
constraint, Shift+Wheel falloff scalar (Ctrl+Shift fine), digits numeric
amount, Enter/Space confirm, Esc/RMB cancel.
"""
from __future__ import annotations

import math

import bpy
import bmesh
import numpy as np
from bpy_extras import view3d_utils
from mathutils import Vector

from ...ui.draw import primitives as draw_prim, Role, draw_scope
from ...ui.draw import safe_handler_add, safe_handler_remove
from ...ui.draw.theme import get_theme
from ...ui.hud import (HUDOverlay, HelpOverlay, HUDSection, HUDItem,
                       HUDParam, ItemState, capture_event)
from ...ui.hud import text as hud_text
from ...utils import falloff_core as fc
from ..mesh_shear import DIGIT_TYPES

HANDLE_PX = 14.0
TYPE_KEYS = {"L": "LINEAR", "R": "RADIAL", "S": "SCREEN", "C": "COPLANAR"}
TYPE_LABELS = {"LINEAR": "Linear", "RADIAL": "Radial", "SCREEN": "Screen",
               "COPLANAR": "Coplanar"}
PREVIEW_LOW = (0.35, 0.10, 0.60, 1.0)    # purple = no influence
PREVIEW_HIGH = (1.00, 0.90, 0.20, 1.0)   # yellow = full influence


class FalloffToolMixin:
    tool_label = "Falloff"
    undo_message = "Falloff"
    amount_label = "Amount"
    amount_fmt = "{:.3f}"

    bl_options = {"REGISTER"}
    is_bindable = True

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.type == "MESH" and obj.mode == "EDIT"

    # ------------------------------------------------------------------
    # Subclass hooks (documented in the plan's Interfaces block)
    # ------------------------------------------------------------------

    def _drag_begin(self, context, event):
        raise NotImplementedError

    def _drag_amount(self, context, event):
        raise NotImplementedError

    def _amount_from_number(self, value):
        raise NotImplementedError

    def _apply_amount(self, amount):
        raise NotImplementedError

    def _amount_text(self, amount):
        return self.amount_fmt.format(amount)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def invoke(self, context, event):
        obj = context.active_object
        self.obj = obj
        self._mw = obj.matrix_world.copy()
        self._mw_inv3 = self._mw.inverted().to_3x3()
        self._rv3d = context.region_data
        if self._rv3d is None:
            self.report({"WARNING"}, f"{self.tool_label}: run from a 3D viewport")
            return {"CANCELLED"}
        self.bm = bmesh.from_edit_mesh(obj.data)
        self.bm.verts.ensure_lookup_table()
        self.bm.faces.ensure_lookup_table()
        self.bm.normal_update()

        if not self._build_affected():
            self.report({"WARNING"}, f"{self.tool_label}: mesh has no visible vertices")
            return {"CANCELLED"}

        props = context.scene.IOPS
        self._ftype = props.falloff_type
        self._shape = props.falloff_shape
        self._invert = props.falloff_invert
        self._connected = props.falloff_connected
        self._preview = props.falloff_preview
        self._screen_px = float(props.falloff_screen_radius_px)
        self._coplanar_angle = float(props.falloff_coplanar_angle)
        if self._ftype == "COPLANAR" and not self._coplanar_available():
            self._ftype = "RADIAL"

        self._S = None
        self._E = None
        self._C = None
        self._r = 1.0
        self._autofit()

        self._W = None
        self._drag = None
        self._current_amount = None
        self._axis = None
        self.input_str = ""
        self._baked = False
        self._hotspots = []
        self._hover_idx = None
        self._handle_drag = None
        self._screen_center = None
        self._mouse_xy = (event.mouse_region_x, event.mouse_region_y)
        self._adj = None
        self._face_data = None

        self._build_hud(context)
        self._last_event = capture_event(event, None)
        self._handle = safe_handler_add(
            bpy.types.SpaceView3D, self._draw_pixel, (context,),
            "WINDOW", "POST_PIXEL", tick=True)
        self._handle_3d = safe_handler_add(
            bpy.types.SpaceView3D, self._draw_view, (context,),
            "WINDOW", "POST_VIEW", tick=False)
        context.workspace.status_text_set(self._status_text())
        context.window_manager.modal_handler_add(self)
        if context.area:
            context.area.tag_redraw()
        return {"RUNNING_MODAL"}

    def _build_affected(self):
        verts = [v for v in self.bm.verts if not v.hide]
        if not verts:
            return False
        self._verts = verts
        self._row_of = {v.index: i for i, v in enumerate(verts)}
        n = len(verts)
        self._P_invoke = np.array([v.co[:] for v in verts], dtype=np.float64)
        self._P0 = self._P_invoke.copy()
        sel = np.array([v.select for v in verts], dtype=bool)
        if not sel.any():
            sel = np.ones(n, dtype=bool)
        self._sel_mask = sel
        self._pivot = fc.bbox_center(self._P0[sel])
        return True

    def _coplanar_available(self):
        return any(f.select for f in self.bm.faces) or any(e.select for e in self.bm.edges)

    def _finish(self, context):
        for attr in ("_handle", "_handle_3d"):
            h = getattr(self, attr, None)
            if h is not None:
                safe_handler_remove(h, bpy.types.SpaceView3D, "WINDOW")
                setattr(self, attr, None)
        context.workspace.status_text_set(None)
        if context.area:
            context.area.tag_redraw()
        # Drop every bmesh reference: Blender keeps finished operator
        # instances in the redo stack and a stale wrapper crashes in
        # bpy_bmesh_dealloc during undo (see mesh_shear._finish).
        self.bm = None
        self.obj = None
        self._verts = []
        self._row_of = {}
        self._adj = None
        self._face_data = None
        self._P0 = None
        self._P_invoke = None
        self._W = None
        self._hotspots = []

    def cancel(self, context):
        self._finish(context)

    # ------------------------------------------------------------------
    # Falloff geometry
    # ------------------------------------------------------------------

    def _autofit(self):
        Psel = self._P0[self._sel_mask]
        if self._ftype == "LINEAR":
            self._S, self._E = fc.autofit_linear(Psel)
        elif self._ftype == "RADIAL":
            self._C, self._r = fc.autofit_radial(Psel)
        self._W = None

    def _set_type(self, ftype):
        if ftype == self._ftype:
            return
        if ftype == "COPLANAR" and not self._coplanar_available():
            self.report({"INFO"}, "Coplanar needs a face or edge selection")
            return
        self._ftype = ftype
        self._autofit()

    def _scalar_step(self, direction, fine):
        """Shift+Wheel: grow/shrink the active falloff's scalar."""
        f = (1.02 if fine else 1.10) if direction > 0 else (1 / 1.02 if fine else 1 / 1.10)
        if self._ftype == "RADIAL":
            self._r = max(1e-4, self._r * f)
        elif self._ftype == "LINEAR":
            self._E = self._S + (self._E - self._S) * f
        elif self._ftype == "SCREEN":
            step = 2.0 if fine else 10.0
            self._screen_px = max(5.0, self._screen_px + step * direction)
        elif self._ftype == "COPLANAR":
            step = math.radians(0.1 if fine else 1.0)
            self._coplanar_angle = min(math.pi / 2, max(0.0, self._coplanar_angle + step * direction))
        self._W = None

    # ------------------------------------------------------------------
    # Weights
    # ------------------------------------------------------------------

    def _ensure_adjacency(self):
        if self._adj is not None:
            return
        row_of = self._row_of
        adj = [[] for _ in self._verts]
        for e in self.bm.edges:
            a, b = e.verts
            ra = row_of.get(a.index)
            rb = row_of.get(b.index)
            if ra is None or rb is None:
                continue
            adj[ra].append(rb)
            adj[rb].append(ra)
        self._adj = adj

    def _ensure_face_data(self):
        """Face normals, face→rows, face adjacency, coplanar reference
        normal and seed faces. Normals come from the live bmesh, so call
        bm.normal_update() before invalidating this (done on bake)."""
        if self._face_data is not None:
            return
        row_of = self._row_of
        faces = [f for f in self.bm.faces if not f.hide]
        fidx = {f.index: i for i, f in enumerate(faces)}
        FN = np.array([f.normal[:] for f in faces], dtype=np.float64) if faces else np.zeros((0, 3))
        face_rows = [[row_of[v.index] for v in f.verts if v.index in row_of] for f in faces]
        face_adj = [[] for _ in faces]
        for e in self.bm.edges:
            lf = [fidx[f.index] for f in e.link_faces if f.index in fidx]
            for i in range(len(lf)):
                for j in range(i + 1, len(lf)):
                    face_adj[lf[i]].append(lf[j])
                    face_adj[lf[j]].append(lf[i])
        sel_faces = [fidx[f.index] for f in faces if f.select]
        if sel_faces:
            n_ref = FN[sel_faces].sum(axis=0)
        else:
            seeds = set()
            for e in self.bm.edges:
                if e.select:
                    for f in e.link_faces:
                        if f.index in fidx:
                            seeds.add(fidx[f.index])
            sel_faces = sorted(seeds)
            n_ref = FN[sel_faces].sum(axis=0) if sel_faces else np.zeros(3)
        self._face_data = (FN, face_rows, face_adj, n_ref, sel_faces)

    def _ensure_weights(self, context):
        if self._W is not None:
            return
        P0 = self._P0
        n = P0.shape[0]
        if self._ftype == "LINEAR":
            w = fc.weight_linear(P0, self._S, self._E)
        elif self._ftype == "RADIAL":
            w = fc.weight_radial(P0, self._C, self._r)
        elif self._ftype == "SCREEN":
            region = context.region
            rv3d = context.region_data
            Pw = P0 @ np.asarray(self._mw.to_3x3()).T + np.asarray(self._mw.translation)
            P2, valid = fc.project_points(Pw, np.asarray(rv3d.perspective_matrix),
                                          region.width, region.height)
            center = self._screen_center if self._screen_center is not None else self._mouse_xy
            w = fc.weight_screen(P2, np.asarray(center, dtype=np.float64), self._screen_px, valid)
        else:  # COPLANAR
            self._ensure_face_data()
            FN, face_rows, face_adj, n_ref, seed_faces = self._face_data
            wf = fc.weight_coplanar_faces(FN, n_ref, self._coplanar_angle)
            if self._connected:
                keep = fc.coplanar_grow(face_adj, wf, seed_faces)
                wf = np.where(keep, wf, 0.0)
            w = fc.vertex_weights_from_faces(face_rows, wf, n)
            w[self._sel_mask] = 1.0
        w = fc.shape_curve(self._shape, w)
        if self._invert:
            w = fc.apply_invert(w)
        if self._ftype != "COPLANAR":
            w = np.where(self._sel_mask, w, 0.0)
            if self._connected:
                self._ensure_adjacency()
                seeds = np.nonzero(self._sel_mask)[0]
                if self._sel_mask.all():
                    seeds = seeds[:1]  # nothing selected: keep the first island only
                keep = fc.connected_mask(self._adj, seeds, n)
                w = np.where(keep, w, 0.0)
        self._W = w

    # ------------------------------------------------------------------
    # Mesh write-back
    # ------------------------------------------------------------------

    def _write(self, P, rows=None):
        if rows is None:
            rows = np.nonzero(self._W > 0.0)[0] if self._W is not None else np.arange(P.shape[0])
        verts = self._verts
        Pl = P.tolist()
        for i in rows.tolist():
            verts[i].co = Pl[i]
        bmesh.update_edit_mesh(self.obj.data, loop_triangles=False, destructive=False)

    def _bake(self, P):
        self._P0 = P.copy()
        self._baked = True
        self.bm.normal_update()
        self._face_data = None
        self._W = None

    # ------------------------------------------------------------------
    # View helpers for subclasses
    # ------------------------------------------------------------------

    def _view_axis_object(self, rv3d):
        world = rv3d.view_rotation @ Vector((0.0, 0.0, 1.0))
        v = self._mw_inv3 @ world
        return v.normalized() if v.length_squared > 1e-18 else Vector((0.0, 0.0, 1.0))

    def _axis_vector_object(self):
        if self._axis is None:
            return None
        return {"X": Vector((1.0, 0.0, 0.0)), "Y": Vector((0.0, 1.0, 0.0)),
                "Z": Vector((0.0, 0.0, 1.0))}[self._axis]

    def _pivot_world(self):
        return self._mw @ Vector(self._pivot.tolist())

    def _pivot_region_2d(self, context):
        return view3d_utils.location_3d_to_region_2d(
            context.region, context.region_data, self._pivot_world())

    def _mouse_to_plane_object(self, context, xy, depth_world=None):
        """Region px → point on the view plane through `depth_world`
        (default: the pivot), returned in object space."""
        if depth_world is None:
            depth_world = self._pivot_world()
        p = view3d_utils.region_2d_to_location_3d(
            context.region, context.region_data, xy, depth_world)
        if p is None:
            return None
        return self._mw.inverted() @ p

    @staticmethod
    def _snap(value, step):
        return round(value / step) * step

    # ------------------------------------------------------------------
    # Modal
    # ------------------------------------------------------------------

    def modal(self, context, event):
        try:
            return self._modal(context, event)
        except ReferenceError:
            self._finish(context)
            self.report({"WARNING"}, f"{self.tool_label}: bmesh data became invalid — cancelled")
            return {"CANCELLED"}
        except Exception:
            self._finish(context)
            raise

    def _modal(self, context, event):
        if context.area:
            context.area.tag_redraw()
        self._last_event = capture_event(event, getattr(self, "_last_event", None))
        try:
            theme_prefs = context.preferences.addons["InteractionOps"].preferences.iops_theme
        except (KeyError, AttributeError):
            theme_prefs = None
        if theme_prefs is not None:
            if self._help.handle_drag_event(context, event, theme_prefs):
                return {"RUNNING_MODAL"}
            if self._hud.handle_drag_event(context, event, theme_prefs):
                return {"RUNNING_MODAL"}
            if self._help.handle_toggle_event(event, theme_prefs):
                return {"RUNNING_MODAL"}
            if self._hud.handle_param_toggle_event(event, theme_prefs):
                return {"RUNNING_MODAL"}

        et = event.type
        if et in {"WHEELUPMOUSE", "WHEELDOWNMOUSE"}:
            if event.shift:
                self._scalar_step(1 if et == "WHEELUPMOUSE" else -1, event.ctrl)
                if self._drag is not None:
                    self._ensure_weights(context)
                    self._live_apply(context, event)
                context.workspace.status_text_set(self._status_text())
                return {"RUNNING_MODAL"}
            return {"PASS_THROUGH"}
        if et == "MIDDLEMOUSE" or et.startswith("NDOF") or et.startswith("TRACKPAD"):
            return {"PASS_THROUGH"}

        if et == "MOUSEMOVE":
            self._mouse_xy = (event.mouse_region_x, event.mouse_region_y)
            if self._handle_drag is not None:
                self._drag_handle(context)
            elif self._drag is not None:
                self._live_apply(context, event)
            elif self._ftype == "SCREEN" and self._preview:
                self._W = None
            return {"RUNNING_MODAL"}

        if et == "LEFTMOUSE":
            if event.value == "PRESS":
                self._mouse_xy = (event.mouse_region_x, event.mouse_region_y)
                self._update_hover()
                if self._hover_idx is not None:
                    self._handle_drag = self._hotspots[self._hover_idx]["kind"]
                    return {"RUNNING_MODAL"}
                if self._ftype == "SCREEN":
                    self._screen_center = self._mouse_xy
                    self._W = None
                self._ensure_weights(context)
                self._drag = {"start": self._mouse_xy}
                self._current_amount = None
                self._drag_begin(context, event)
                return {"RUNNING_MODAL"}
            if event.value == "RELEASE":
                if self._handle_drag is not None:
                    self._handle_drag = None
                    return {"RUNNING_MODAL"}
                if self._drag is not None:
                    if self._current_amount is not None:
                        self._bake(self._apply_amount(self._current_amount))
                    self._drag = None
                    self._current_amount = None
                    context.workspace.status_text_set(self._status_text())
                return {"RUNNING_MODAL"}

        if event.value != "PRESS":
            return {"RUNNING_MODAL"}

        if et in DIGIT_TYPES:
            self.input_str += DIGIT_TYPES[et]
        elif et in {"PERIOD", "NUMPAD_PERIOD"}:
            if "." not in self.input_str:
                self.input_str += "."
        elif et in {"MINUS", "NUMPAD_MINUS"}:
            self.input_str = self.input_str[1:] if self.input_str.startswith("-") else "-" + self.input_str
        elif et == "BACK_SPACE":
            self.input_str = self.input_str[:-1]
        elif et in TYPE_KEYS and self._drag is None:
            self._set_type(TYPE_KEYS[et])
        elif et == "E":
            self._connected = not self._connected
            self._W = None
        elif et == "F":
            i = fc.SHAPES.index(self._shape)
            self._shape = fc.SHAPES[(i + 1) % len(fc.SHAPES)]
            self._W = None
        elif et == "I":
            self._invert = not self._invert
            self._W = None
        elif et == "A":
            self._autofit()
        elif et == "V":
            self._preview = not self._preview
        elif et in {"X", "Y", "Z"}:
            self._axis = None if self._axis == et else et
            if self._drag is not None:
                self._live_apply(context, event)
        elif et in {"RET", "NUMPAD_ENTER", "SPACE"}:
            return self._confirm(context)
        elif et in {"ESC", "RIGHTMOUSE"}:
            return self._cancel_all(context)
        if self._drag is not None and et not in {"RET", "NUMPAD_ENTER", "SPACE"}:
            self._ensure_weights(context)
            self._live_apply(context, event)
        context.workspace.status_text_set(self._status_text())
        return {"RUNNING_MODAL"}

    def _live_apply(self, context, event):
        amount = self._drag_amount(context, event)
        self._current_amount = amount
        self._write(self._apply_amount(amount))

    def _confirm(self, context):
        if self.input_str:
            try:
                value = float(self.input_str)
            except ValueError:
                value = None
            if value is not None:
                self._ensure_weights(context)
                amount = self._amount_from_number(value)
                P = self._apply_amount(amount)
                self._write(P)
                self._bake(P)
            self.input_str = ""
        if self._drag is not None and self._current_amount is not None:
            self._bake(self._apply_amount(self._current_amount))
        self._drag = None
        if not self._baked:
            self._save_props(context)
            self._finish(context)
            return {"CANCELLED"}
        self.bm.normal_update()
        bmesh.update_edit_mesh(self.obj.data, loop_triangles=False, destructive=False)
        self._save_props(context)
        bpy.ops.ed.undo_push(message=self.undo_message)
        self._finish(context)
        return {"FINISHED"}

    def _cancel_all(self, context):
        if self._baked or self._drag is not None:
            self._W = None
            self._write(self._P_invoke, rows=np.arange(self._P_invoke.shape[0]))
            self.bm.normal_update()
            bmesh.update_edit_mesh(self.obj.data, loop_triangles=False, destructive=False)
        self._save_props(context)
        self._finish(context)
        return {"CANCELLED"}

    def _save_props(self, context):
        props = context.scene.IOPS
        props.falloff_type = self._ftype
        props.falloff_shape = self._shape
        props.falloff_invert = self._invert
        props.falloff_connected = self._connected
        props.falloff_preview = self._preview
        props.falloff_screen_radius_px = int(round(self._screen_px))
        props.falloff_coplanar_angle = self._coplanar_angle

    # ------------------------------------------------------------------
    # Handles
    # ------------------------------------------------------------------

    def _update_hover(self):
        mx, my = self._mouse_xy
        best = (None, HANDLE_PX * HANDLE_PX)
        for i, h in enumerate(self._hotspots):
            rp = h.get("region_pt")
            if rp is None:
                continue
            dx, dy = rp[0] - mx, rp[1] - my
            d2 = dx * dx + dy * dy
            if d2 < best[1]:
                best = (i, d2)
        self._hover_idx = best[0]

    def _drag_handle(self, context):
        kind = self._handle_drag
        if kind in {"S", "E", "C"}:
            cur = {"S": self._S, "E": self._E, "C": self._C}[kind]
            depth = self._mw @ Vector(cur.tolist())
            p = self._mouse_to_plane_object(context, self._mouse_xy, depth)
            if p is None:
                return
            arr = np.array(p[:], dtype=np.float64)
            if kind == "S":
                self._S = arr
            elif kind == "E":
                self._E = arr
            else:
                self._C = arr
        elif kind == "R":
            depth = self._mw @ Vector(self._C.tolist())
            p = self._mouse_to_plane_object(context, self._mouse_xy, depth)
            if p is None:
                return
            d = np.array(p[:], dtype=np.float64) - self._C
            self._r = max(1e-4, float(np.linalg.norm(d)))
        self._W = None

    def _ring_handle_point_object(self, rv3d):
        """Point on the radial ring at the view's right, in object space."""
        right_w = rv3d.view_rotation @ Vector((1.0, 0.0, 0.0))
        right_o = (self._mw_inv3 @ right_w)
        if right_o.length_squared < 1e-18:
            right_o = Vector((1.0, 0.0, 0.0))
        right_o.normalize()
        return Vector(self._C.tolist()) + right_o * self._r

    # ------------------------------------------------------------------
    # HUD
    # ------------------------------------------------------------------

    def _build_hud(self, context):
        self._hud = HUDOverlay(f"mesh_falloff_{self.tool_label.lower()}")
        self._hud.title = f"Falloff {self.tool_label}"
        self._hud.bind_region(context.region)
        self._items = {
            "LINEAR": HUDItem("Linear", "L"),
            "RADIAL": HUDItem("Radial", "R"),
            "SCREEN": HUDItem("Screen", "S"),
            "COPLANAR": HUDItem("Coplanar", "C"),
            "E": HUDItem("Element (connected only)", "E"),
            "I": HUDItem("Invert", "I"),
            "V": HUDItem("Show weights", "V"),
        }
        self._hud.add_section(HUDSection("Falloff", [
            self._items["LINEAR"], self._items["RADIAL"], self._items["SCREEN"],
            self._items["COPLANAR"], self._items["E"], self._items["I"],
            self._items["V"],
        ]))
        self._hud.add_param(HUDParam("Shape", lambda: self._shape.replace("_", " ").title(), "str"))
        self._hud.add_param(HUDParam("Radius", lambda: self._r, "float", fmt="{:.4f}",
                                     visible_getter=lambda: self._ftype == "RADIAL"))
        self._hud.add_param(HUDParam("Length", lambda: float(np.linalg.norm(self._E - self._S)), "float",
                                     fmt="{:.4f}", visible_getter=lambda: self._ftype == "LINEAR"))
        self._hud.add_param(HUDParam("Radius px", lambda: self._screen_px, "int",
                                     visible_getter=lambda: self._ftype == "SCREEN"))
        self._hud.add_param(HUDParam("Angle", lambda: math.degrees(self._coplanar_angle), "float",
                                     fmt="{:.1f}°", visible_getter=lambda: self._ftype == "COPLANAR"))
        self._hud.add_param(HUDParam("Axis", lambda: self._axis or "—", "str"))
        self._hud.add_param(HUDParam(self.amount_label, self._hud_amount, "str"))
        self._hud.add_param(HUDParam("Typing", lambda: self.input_str, "str",
                                     visible_getter=lambda: bool(self.input_str)))

        self._help = HelpOverlay(f"mesh_falloff_{self.tool_label.lower()}")
        self._help.add_section(HUDSection(f"Falloff {self.tool_label}", [
            HUDItem("Drag = transform, drag handle = edit falloff", "LMB", ItemState.ON, always_show=True),
            HUDItem("Falloff type", "L / R / S / C", ItemState.ON, always_show=True),
            HUDItem("Element: connected only", "E", ItemState.ON, always_show=True),
            HUDItem("Cycle shape", "F", ItemState.ON, always_show=True),
            HUDItem("Invert", "I", ItemState.ON, always_show=True),
            HUDItem("Auto-size to selection", "A", ItemState.ON, always_show=True),
            HUDItem("Show weights", "V", ItemState.ON, always_show=True),
            HUDItem("Axis constraint", "X / Y / Z", ItemState.ON, always_show=True),
            HUDItem("Falloff size (fine: +Ctrl)", "Shift+Wheel", ItemState.ON, always_show=True),
            HUDItem("Precise / Snap", "Shift / Ctrl", ItemState.ON, always_show=True),
            HUDItem("Type amount", "0-9 . -", ItemState.ON, always_show=True),
            HUDItem("Confirm", "Enter / Space", ItemState.ON, always_show=True),
            HUDItem("Cancel", "Esc / RMB", ItemState.ON, always_show=True),
        ]))
        self._help.bind_region(context.region)

    def _hud_amount(self):
        if self._current_amount is None:
            return "—"
        return self._amount_text(self._current_amount)

    def _sync_hud_states(self):
        for t in fc.FALLOFF_TYPES:
            it = self._items[t]
            if t == "COPLANAR" and not self._coplanar_available():
                it.state = ItemState.DISABLED
            else:
                it.state = ItemState.ON if self._ftype == t else ItemState.OFF
        self._items["E"].state = ItemState.ON if self._connected else ItemState.OFF
        self._items["I"].state = ItemState.ON if self._invert else ItemState.OFF
        self._items["V"].state = ItemState.ON if self._preview else ItemState.OFF

    def _status_text(self):
        typed = f" | typing: {self.input_str}" if self.input_str else ""
        return (f"Falloff {self.tool_label}: {TYPE_LABELS[self._ftype]} / "
                f"{self._shape.title()}{' / inverted' if self._invert else ''}"
                f"{' / connected' if self._connected else ''}{typed} | "
                "[LMB drag] transform | [L/R/S/C] type | [E] element | [F] shape | "
                "[I] invert | [A] fit | [V] weights | [Shift+Wheel] size | "
                "[Enter] confirm | [Esc] cancel")

    # ------------------------------------------------------------------
    # Drawing
    # ------------------------------------------------------------------

    def _guard_draw(self):
        try:
            _ = self.obj.matrix_world
            return True
        except (ReferenceError, AttributeError):
            for attr in ("_handle", "_handle_3d"):
                h = getattr(self, attr, None)
                if h is not None:
                    try:
                        safe_handler_remove(h, bpy.types.SpaceView3D, "WINDOW")
                    except (ValueError, RuntimeError, ReferenceError):
                        pass
                    setattr(self, attr, None)
            return False

    def _draw_view(self, context):
        if context.region_data is None or not self._guard_draw():
            return
        if self._P0 is None:
            return
        theme = get_theme(context)
        mw = self._mw
        with draw_scope(blend="ALPHA", depth="NONE"):
            if self._ftype == "LINEAR":
                S = mw @ Vector(self._S.tolist())
                E = mw @ Vector(self._E.tolist())
                draw_prim.line(S, E, role=Role.ACTIVE_LINE, context=context, theme=theme)
                d = (E - S)
                if d.length_squared > 1e-18:
                    tick = d.normalized().orthogonal().normalized() * (d.length * 0.08)
                    draw_prim.edges_3d([S - tick, S + tick, E - tick, E + tick],
                                       role=Role.LINE, context=context, theme=theme)
            elif self._ftype == "RADIAL":
                C = mw @ Vector(self._C.tolist())
                for axis in (Vector((1, 0, 0)), Vector((0, 1, 0)), Vector((0, 0, 1))):
                    n = (mw.to_3x3() @ axis)
                    draw_prim.ring_3d(C, n, self._r * mw.to_scale().x, role=Role.PREVIEW_LINE,
                                      context=context, theme=theme)
            draw_prim.points([self._pivot_world()], role=Role.PIVOT, context=context, theme=theme)
            if self._preview:
                self._ensure_weights(context)
                W = self._W
                rows = np.nonzero(W > 0.0)[0]
                if rows.size:
                    Pw = self._P0[rows] @ np.asarray(mw.to_3x3()).T + np.asarray(mw.translation)
                    lo = np.asarray(PREVIEW_LOW)
                    hi = np.asarray(PREVIEW_HIGH)
                    cols = lo + (hi - lo) * W[rows][:, None]
                    draw_prim.points_colored(Pw.tolist(), cols.tolist(),
                                             size=theme.point_size("default"))

    def _draw_pixel(self, context):
        region = context.region
        rv3d = context.region_data
        if rv3d is None or not self._guard_draw():
            return
        if self._P0 is None:
            return
        theme = get_theme(context)
        mw = self._mw

        def s2d(co_obj):
            return view3d_utils.location_3d_to_region_2d(region, rv3d, mw @ Vector(co_obj.tolist()))

        self._hotspots = []
        if self._ftype == "LINEAR":
            for kind, co in (("S", self._S), ("E", self._E)):
                p = s2d(co)
                if p is not None:
                    self._hotspots.append({"kind": kind, "region_pt": (p.x, p.y)})
        elif self._ftype == "RADIAL":
            p = s2d(self._C)
            if p is not None:
                self._hotspots.append({"kind": "C", "region_pt": (p.x, p.y)})
            rp = view3d_utils.location_3d_to_region_2d(
                region, rv3d, mw @ self._ring_handle_point_object(rv3d))
            if rp is not None:
                self._hotspots.append({"kind": "R", "region_pt": (rp.x, rp.y)})
        if self._handle_drag is None:
            self._update_hover()

        with draw_scope(blend="ALPHA"):
            if self._ftype == "SCREEN":
                c = self._screen_center if self._screen_center is not None else self._mouse_xy
                pts = [(c[0] + self._screen_px * math.cos(a), c[1] + self._screen_px * math.sin(a))
                       for a in np.linspace(0.0, 2.0 * math.pi, 65)]
                draw_prim.polyline(pts, role=Role.PREVIEW_LINE, context=context, theme=theme)
            pts = [h["region_pt"] for h in self._hotspots]
            if pts:
                draw_prim.points(pts, role=Role.HANDLE, context=context, theme=theme)
            if self._hover_idx is not None and self._hover_idx < len(self._hotspots):
                draw_prim.points([self._hotspots[self._hover_idx]["region_pt"]],
                                 role=Role.HANDLE_HOVER, context=context, theme=theme)

        self._sync_hud_states()
        with hud_text.isolated(theme):
            self._help.draw(context, self._last_event)
            self._hud.draw(context, self._last_event)
```

- [ ] **Step 3: Static checks**

Run:
```bash
cd D:/git/InteractionOps && ruff check operators/falloff/common.py && python -c "import ast; ast.parse(open('operators/falloff/common.py',encoding='utf-8').read()); print('syntax ok')"
```
Expected: clean, `syntax ok`. Fix any ruff findings (unused imports etc.) before moving on.

- [ ] **Step 4: Commit**

```bash
git add operators/falloff/__init__.py operators/falloff/common.py
git commit -m "feat(falloff): shared modal mixin for falloff tools

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 7: The three operators + registration

**Files:**
- Create: `operators/falloff/ops.py`
- Modify: `__init__.py` — imports block near line 322 (after `from .operators.mesh_hinge import IOPS_OT_mesh_hinge`) and the `classes` tuple near line 656 (after `IOPS_OT_mesh_hinge,`)

**Interfaces:**
- Consumes: `FalloffToolMixin` and its hooks/helpers from Task 6; `fc.apply_move/apply_rotate/apply_scale`.
- Produces: `IOPS_OT_mesh_falloff_move` (`iops.mesh_falloff_move`), `IOPS_OT_mesh_falloff_rotate` (`iops.mesh_falloff_rotate`), `IOPS_OT_mesh_falloff_scale` (`iops.mesh_falloff_scale`).

Amount semantics:
- Move: amount = object-space `np.ndarray (3,)` delta. Mouse: view-plane delta through the pivot; Shift ×0.1; Ctrl snaps each component to 0.1; axis constraint projects onto the axis. Numeric: distance along the axis constraint (object X when none).
- Rotate: amount = radians. Mouse: `atan2` around the projected pivot, unwrapped across ±π; Shift ×0.1; Ctrl snaps to 5°. Axis: view axis, or X/Y/Z object axis. Numeric: degrees.
- Scale: amount = `np.ndarray (3,)` per-axis factors. Mouse: `dist(mouse, pivot2d) / dist(start, pivot2d)`, Shift → `1 + (s−1)·0.1`, Ctrl snaps to 0.1; axis constraint puts `s` on that axis and 1 elsewhere. Numeric: factor.

- [ ] **Step 1: Write `operators/falloff/ops.py`**

```python
"""iOps Falloff tools: Move / Rotate / Scale the selection with a
Modo-style per-vertex falloff. All shared behaviour lives in
FalloffToolMixin; these classes only turn a mouse drag into an amount
and an amount into new coordinates."""
from __future__ import annotations

import math

import bpy
import numpy as np
from mathutils import Vector

from ...utils import falloff_core as fc
from .common import FalloffToolMixin


class IOPS_OT_mesh_falloff_move(FalloffToolMixin, bpy.types.Operator):
    bl_idname = "iops.mesh_falloff_move"
    bl_label = "iOps Falloff Move"
    bl_description = ("Move the selection with a falloff (Linear / Radial / "
                      "Screen / Coplanar). Drag to move, drag handles to edit "
                      "the falloff")
    tool_label = "Move"
    undo_message = "Falloff Move"
    amount_label = "Offset"

    def _drag_begin(self, context, event):
        self._start_obj = self._mouse_to_plane_object(context, self._drag["start"])

    def _drag_amount(self, context, event):
        if self._start_obj is None:
            return np.zeros(3)
        cur = self._mouse_to_plane_object(context, (event.mouse_region_x, event.mouse_region_y))
        if cur is None:
            return np.zeros(3)
        d = cur - self._start_obj
        if event.shift:
            d *= 0.1
        ax = self._axis_vector_object()
        if ax is not None:
            d = ax * d.dot(ax)
        if event.ctrl:
            d = Vector([self._snap(c, 0.1) for c in d])
        return np.array(d[:], dtype=np.float64)

    def _amount_from_number(self, value):
        ax = self._axis_vector_object() or Vector((1.0, 0.0, 0.0))
        return np.array((ax * value)[:], dtype=np.float64)

    def _apply_amount(self, amount):
        return fc.apply_move(self._P0, self._W, amount)

    def _amount_text(self, amount):
        return "({:.3f}, {:.3f}, {:.3f})".format(*amount.tolist())


class IOPS_OT_mesh_falloff_rotate(FalloffToolMixin, bpy.types.Operator):
    bl_idname = "iops.mesh_falloff_rotate"
    bl_label = "iOps Falloff Rotate"
    bl_description = ("Rotate the selection with a falloff (Linear / Radial / "
                      "Screen / Coplanar). Drag around the pivot to rotate; "
                      "X/Y/Z set the axis (view axis by default)")
    tool_label = "Rotate"
    undo_message = "Falloff Rotate"
    amount_label = "Angle"

    def _mouse_angle(self, context, xy):
        p2 = self._pivot_region_2d(context)
        if p2 is None:
            return 0.0
        return math.atan2(xy[1] - p2.y, xy[0] - p2.x)

    def _drag_begin(self, context, event):
        self._start_angle = self._mouse_angle(context, self._drag["start"])
        self._prev_angle = self._start_angle
        self._accum = 0.0

    def _drag_amount(self, context, event):
        a = self._mouse_angle(context, (event.mouse_region_x, event.mouse_region_y))
        d = a - self._prev_angle
        while d > math.pi:
            d -= 2.0 * math.pi
        while d < -math.pi:
            d += 2.0 * math.pi
        self._prev_angle = a
        self._accum += d
        theta = self._accum
        if event.shift:
            theta *= 0.1
        if event.ctrl:
            theta = self._snap(theta, math.radians(5.0))
        return self._signed_for_axis(context, theta)

    def _signed_for_axis(self, context, theta):
        """Counter-clockwise on screen is positive about an axis pointing
        at the viewer; flip when the chosen object axis points away."""
        ax = self._axis_vector_object()
        if ax is None:
            return theta
        view = self._view_axis_object(self._rv3d)
        return theta if ax.dot(view) >= 0.0 else -theta

    def _rotation_axis(self):
        ax = self._axis_vector_object()
        return ax if ax is not None else self._view_axis_object(self._rv3d)

    def _amount_from_number(self, value):
        return math.radians(value)

    def _apply_amount(self, amount):
        axis = self._rotation_axis()
        return fc.apply_rotate(self._P0, self._W, self._pivot,
                               np.array(axis[:], dtype=np.float64), amount)

    def _amount_text(self, amount):
        return f"{math.degrees(amount):.2f}°"


class IOPS_OT_mesh_falloff_scale(FalloffToolMixin, bpy.types.Operator):
    bl_idname = "iops.mesh_falloff_scale"
    bl_label = "iOps Falloff Scale"
    bl_description = ("Scale the selection about its centre with a falloff "
                      "(Linear / Radial / Screen / Coplanar). Drag away from "
                      "the pivot to grow; X/Y/Z constrain to one axis")
    tool_label = "Scale"
    undo_message = "Falloff Scale"
    amount_label = "Scale"

    def _drag_begin(self, context, event):
        p2 = self._pivot_region_2d(context)
        sx, sy = self._drag["start"]
        self._start_dist = max(1.0, math.hypot(sx - p2.x, sy - p2.y)) if p2 is not None else 1.0

    def _drag_amount(self, context, event):
        p2 = self._pivot_region_2d(context)
        if p2 is None:
            return np.ones(3)
        d = math.hypot(event.mouse_region_x - p2.x, event.mouse_region_y - p2.y)
        s = d / self._start_dist
        if event.shift:
            s = 1.0 + (s - 1.0) * 0.1
        if event.ctrl:
            s = max(0.0, self._snap(s, 0.1))
        return self._vector_for_axis(s)

    def _vector_for_axis(self, s):
        if self._axis is None:
            return np.full(3, float(s))
        v = np.ones(3)
        v["XYZ".index(self._axis)] = float(s)
        return v

    def _amount_from_number(self, value):
        return self._vector_for_axis(value)

    def _apply_amount(self, amount):
        return fc.apply_scale(self._P0, self._W, self._pivot, amount)

    def _amount_text(self, amount):
        a = amount.tolist()
        if abs(a[0] - a[1]) < 1e-9 and abs(a[1] - a[2]) < 1e-9:
            return f"{a[0]:.3f}"
        return "({:.3f}, {:.3f}, {:.3f})".format(*a)


classes = (
    IOPS_OT_mesh_falloff_move,
    IOPS_OT_mesh_falloff_rotate,
    IOPS_OT_mesh_falloff_scale,
)
```

- [ ] **Step 2: Register in `__init__.py`**

After the line `from .operators.mesh_hinge import IOPS_OT_mesh_hinge` add:

```python
from .operators.falloff.ops import (IOPS_OT_mesh_falloff_move,
                                    IOPS_OT_mesh_falloff_rotate,
                                    IOPS_OT_mesh_falloff_scale)
```

In the `classes` tuple, after `IOPS_OT_mesh_hinge,` add:

```python
    IOPS_OT_mesh_falloff_move,
    IOPS_OT_mesh_falloff_rotate,
    IOPS_OT_mesh_falloff_scale,
```

- [ ] **Step 3: Static checks + smoke registration script**

Run: `cd D:/git/InteractionOps && ruff check operators/falloff/ops.py __init__.py`

Then extend `tests/smoke_register.py`: find the operator-name list it asserts with `hasattr(bpy.ops.iops, op_name)` and add `"mesh_falloff_move", "mesh_falloff_rotate", "mesh_falloff_scale"`. Run it headless (Blender at `V:\SteamLibrary\steamapps\common\Blender\blender.exe`; the script's header documents the `BLENDER_USER_SCRIPTS` junction requirement — `B:\scripts` already has `addons\InteractionOps` as a symlink to the repo, so use `BLENDER_USER_SCRIPTS=B:\scripts`):

```powershell
$env:BLENDER_USER_SCRIPTS = "B:\scripts"
& "V:\SteamLibrary\steamapps\common\Blender\blender.exe" --background --factory-startup --python D:\git\InteractionOps\tests\smoke_register.py 2>&1 | Select-String "SMOKE_OK|Error|Traceback|AssertionError"
```
Expected: `SMOKE_OK`. If the harness path convention differs, read the docstring at the top of `tests/smoke_register.py` and follow it.

- [ ] **Step 4: Commit**

```bash
git add operators/falloff/ops.py __init__.py tests/smoke_register.py
git commit -m "feat(falloff): iops.mesh_falloff_move / _rotate / _scale operators

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 8: Live Blender verification and fixes

**Files:**
- Possibly modify: `operators/falloff/common.py`, `operators/falloff/ops.py`, `ui/draw/primitives.py` (bug fixes only)

**Preconditions (hard gate):** via `mcp__blender__execute_blender_code`, print `bpy.data.filepath`. Continue only if it is `""` or starts with `V:\temp_blends\` or `B:\test\`. Otherwise report **BLOCKED** and stop. Reload the addon through blinker (TCP 9902, send `reload`, expect `ok (N modules)`), then verify `"InteractionOps.operators.falloff.ops" in sys.modules`. If blinker is not listening → BLOCKED (never `addon_utils.disable/enable` in a session you did not create).

- [ ] **Step 1: Build fixtures**

Run in Blender:

```python
import bpy, bmesh
scene = bpy.context.scene
for name in ("fo_plane", "fo_islands"):
    o = bpy.data.objects.get(name)
    if o: bpy.data.objects.remove(o, do_unlink=True)
# subdivided plane, centre vert selected
bpy.ops.mesh.primitive_grid_add(x_subdivisions=20, y_subdivisions=20, size=4)
plane = bpy.context.active_object; plane.name = "fo_plane"
bpy.ops.object.mode_set(mode="EDIT")
bm = bmesh.from_edit_mesh(plane.data)
for v in bm.verts: v.select = v.co.length < 0.15
bm.select_flush_mode(); bmesh.update_edit_mesh(plane.data)
bpy.ops.object.mode_set(mode="OBJECT")
# two islands: cube + offset cube in one mesh, one top face of cube A selected
bpy.ops.mesh.primitive_cube_add(location=(6, 0, 0)); a = bpy.context.active_object
bpy.ops.mesh.primitive_cube_add(location=(9, 0, 0)); b = bpy.context.active_object
a.select_set(True); b.select_set(True); bpy.context.view_layer.objects.active = a
bpy.ops.object.join(); a.name = "fo_islands"
bpy.ops.object.mode_set(mode="EDIT")
bm = bmesh.from_edit_mesh(a.data)
for f in bm.faces: f.select = (f.normal.z > 0.9 and f.calc_center_median().x < 7.5)
bm.select_flush_mode(); bmesh.update_edit_mesh(a.data)
bpy.ops.object.mode_set(mode="OBJECT")
print("fixtures ok")
```

- [ ] **Step 2: Non-interactive weight checks**

Modal operators cannot be driven headlessly, so exercise the mixin's weight path directly:

```python
import bpy, bmesh, numpy as np
from InteractionOps.operators.falloff.ops import IOPS_OT_mesh_falloff_move
from InteractionOps.utils import falloff_core as fc
obj = bpy.data.objects["fo_plane"]
bpy.context.view_layer.objects.active = obj; obj.select_set(True)
bpy.ops.object.mode_set(mode="EDIT")
op = IOPS_OT_mesh_falloff_move.__new__(IOPS_OT_mesh_falloff_move)
op.obj = obj; op._mw = obj.matrix_world.copy(); op._mw_inv3 = op._mw.inverted().to_3x3()
op.bm = bmesh.from_edit_mesh(obj.data); op.bm.verts.ensure_lookup_table(); op.bm.faces.ensure_lookup_table()
assert op._build_affected()
op._ftype = "RADIAL"; op._shape = "SMOOTH"; op._invert = False; op._connected = False
op._screen_px = 150.0; op._coplanar_angle = 0.087; op._adj = None; op._face_data = None
op._S = op._E = op._C = None; op._r = 1.0; op._W = None; op._screen_center = None; op._mouse_xy = (0, 0)
op._autofit()
op._ensure_weights(bpy.context)
W = op._W
print("selected rows weight 1:", np.allclose(W[op._sel_mask], 1.0))
print("unselected rows zero (only selection affected):", np.all(W[~op._sel_mask] == 0.0))
# Coplanar on the flat plane: every face is coplanar → all verts weighted
op._ftype = "COPLANAR"; op._W = None; op._face_data = None
op._ensure_weights(bpy.context)
print("coplanar covers whole plane:", np.all(op._W > 0.999))
# Linear
op._ftype = "LINEAR"; op._W = None; op._autofit(); op._ensure_weights(bpy.context)
print("linear weights in [0,1]:", op._W.min() >= 0 and op._W.max() <= 1)
bpy.ops.object.mode_set(mode="OBJECT")
```
Expected: three `True` lines plus the linear range line `True`. Any exception → fix in `common.py`, blinker-reload, re-run.

- [ ] **Step 3: Interactive checks (user-driven, report results)**

Ask the user to run, on `fo_plane` in Edit Mode with the centre selected, each operator via F3 search ("iOps Falloff Move/Rotate/Scale") and confirm:
1. Radial rings + pivot appear; LMB drag away from handles moves/rotates/scales the selection with a smooth bump; release keeps the tool live; second drag continues from the baked state.
2. L switches to Linear with two end handles; dragging an end handle moves it; A refits.
3. S switches to Screen; the 2D ring follows the mouse press point; Shift+Wheel changes its px radius.
4. C on `fo_islands` (top face selected): with E off, the coplanar top face of the second island is affected too; with E on only the first island's top face region grows.
5. V shows purple→yellow dots; I inverts them.
6. Esc after two drags restores exactly (compare visually or via a vert-position dump before/after).
7. Enter after a drag: Ctrl+Z once undoes the whole tool session; Ctrl+Z again undoes the fixture step; Ctrl+Shift+Z redoes without crashing.
8. Plain wheel zooms the viewport while the tool is live.

Record any failures and fix them; commit fixes as `fix(falloff): <what>`.

- [ ] **Step 4: Remove fixtures**

```python
import bpy
for name in ("fo_plane", "fo_islands"):
    o = bpy.data.objects.get(name)
    if o: bpy.data.objects.remove(o, do_unlink=True)
```

---

### Task 9: User docs, mkdocs nav, memory, squash

**Files:**
- Create: `docs/operators/op_mesh_falloff_tools.md`
- Modify: `mkdocs.yml` (nav `Mesh — Editing`, after `Hinge`)
- Modify: `docs/superpowers/STATUS.md` (add rows for the spec and this plan)

- [ ] **Step 1: Write the doc page**

```markdown
# Falloff Move / Rotate / Scale

Modo-style soft transforms: every vertex of the selection moves, rotates or scales by a weight from a falloff you can see and edit in the viewport. Three operators share one interaction: `iops.mesh_falloff_move`, `iops.mesh_falloff_rotate`, `iops.mesh_falloff_scale`. Edit Mesh mode.

**Hotkey:** Not bound by default — assign keys in *Preferences › iOps › Keymaps* (bucket *Other*), or run them from operator search.

## Falloffs
| Key | Falloff | Weight |
| --- | --- | --- |
| <kbd>L</kbd> | Linear | 1 at the Start handle, 0 at the End handle |
| <kbd>R</kbd> | Radial | 1 at the centre, 0 at the ring |
| <kbd>S</kbd> | Screen | 1 under the mouse, 0 at the pixel radius (Soft Drag) |
| <kbd>C</kbd> | Coplanar | 1 on faces parallel to the selection, 0 past the angle; grows outside the selection. Needs a face or edge selection |
| <kbd>E</kbd> | Element toggle | Only geometry connected to the selection is affected |

## Controls
| Key | Action |
| --- | --- |
| <kbd>LMB</kbd> drag | Transform (release bakes, tool stays live) |
| <kbd>LMB</kbd> on a handle | Move the falloff centre / ends / radius ring |
| <kbd>F</kbd> | Cycle shape: Linear, Smooth, Sharp, Root, Sphere, Inverse Square, Constant |
| <kbd>I</kbd> | Invert weights |
| <kbd>A</kbd> | Auto-size the falloff to the selection |
| <kbd>V</kbd> | Show weights (purple = none, yellow = full) |
| <kbd>X</kbd> / <kbd>Y</kbd> / <kbd>Z</kbd> | Constrain move/scale axis or set the rotation axis (view axis by default) |
| <kbd>Shift</kbd>+<kbd>Wheel</kbd> | Falloff size (radius / length / pixels / angle); add <kbd>Ctrl</kbd> for fine steps |
| <kbd>Shift</kbd> / <kbd>Ctrl</kbd> while dragging | Precise / snap |
| <kbd>0</kbd>–<kbd>9</kbd>, <kbd>.</kbd>, <kbd>-</kbd> | Type an amount (units, degrees or factor); <kbd>Enter</kbd> applies |
| <kbd>MMB</kbd> / <kbd>Wheel</kbd> | Navigate |
| <kbd>H</kbd> | Help legend |
| <kbd>Enter</kbd> / <kbd>Space</kbd> | Confirm (one undo step) |
| <kbd>Esc</kbd> / <kbd>RMB</kbd> | Cancel every drag of this session |

## Tips
- Nothing selected = the whole mesh is affected.
- Last-used type, shape, invert, element, preview, pixel radius and coplanar angle persist per scene.
- Coplanar with Element on behaves like a region grow that stops at hard edges.
```

- [ ] **Step 2: Add to mkdocs nav**

In `mkdocs.yml`, after the line `          - Hinge: operators/op_mesh_hinge.md` insert:

```yaml
          - Falloff Move / Rotate / Scale: operators/op_mesh_falloff_tools.md
```

Run: `cd D:/git/InteractionOps && python -m mkdocs build --strict -q && echo BUILD_OK` (if mkdocs is not installed: `pip install -r requirements-docs.txt`).
Expected: `BUILD_OK`.

- [ ] **Step 3: STATUS.md rows**

Append to the Specs table:

```markdown
| 2026-09-07 | [modo-falloff-analysis](specs/2026-09-07-modo-falloff-analysis.md) | ✅ | Research-only doc feeding the falloff tools design. |
| 2026-09-07 | [modo-falloff-tools-design](specs/2026-09-07-modo-falloff-tools-design.md) | ✅ | `operators/falloff/`, `utils/falloff_core.py`, `tests/test_falloff_core.py`. |
```

Append to the Plans table:

```markdown
| 2026-09-07 | [modo-falloff-tools](plans/2026-09-07-modo-falloff-tools.md) | ✅ executed |
```

- [ ] **Step 4: Commit docs**

```bash
git add docs/operators/op_mesh_falloff_tools.md mkdocs.yml docs/superpowers/STATUS.md
git commit -m "docs(falloff): user page, nav entry, status rows

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

- [ ] **Step 5: Squash the feature into one commit**

The repo rule is one feature = one commit. From branch `falloff-tools`:

```bash
cd D:/git/InteractionOps
git log --oneline master..HEAD          # review the task commits
git reset --soft master
git commit -m "feat(falloff): Modo-style falloff Move / Rotate / Scale tools

Three edit-mesh modals (iops.mesh_falloff_move / _rotate / _scale) that
weight every vertex by a Linear, Radial, Screen or Coplanar falloff,
switchable by hotkey with in-viewport handles, an Element (connected
only) toggle, weight preview, Shift+Wheel sizing and numeric input.
Math is numpy in utils/falloff_core.py (pytest-covered); new ring_3d
and points_colored draw primitives; last-used settings in Scene.IOPS.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
git log --oneline -3
```

Do not merge or push; report the branch name and commit hash to the user.
