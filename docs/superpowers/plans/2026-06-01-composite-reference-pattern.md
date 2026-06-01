# Composite Reference Pattern Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let any face set marked in the Object Aligner's E mode — one island, several islands, or scattered single faces — act as a single rigid reference pattern, matched as a "constellation" of connected components.

**Architecture:** Decompose the reference into connected components, find per-component candidate matches on each target with the existing pattern matcher, then assemble candidate tuples whose mutual arrangement reproduces the reference and confirm each with one global Kabsch fit. The constellation logic is pure NumPy (`utils/polygon_match.py`, unit-tested); `operators/object_aligner.py` only builds inputs and records results. Downstream stamping/draw/skip-keep code is untouched because each constellation is stored exactly like a single-island match used to be.

**Tech Stack:** Python, NumPy, bmesh/bpy (Blender addon), pytest (pure-NumPy units only).

**Reference spec:** [docs/superpowers/specs/2026-06-01-composite-reference-pattern-design.md](../specs/2026-06-01-composite-reference-pattern-design.md)

---

## File Structure

- `utils/polygon_match.py` — **add** `Candidate` dataclass, `fit_both`, `_apply_affine`, `assemble_constellations` (pure NumPy + existing kabsch helpers). This is where the new algorithm lives.
- `tests/test_polygon_match.py` — **add** unit tests for the three new functions.
- `operators/object_aligner.py` — **modify** `_commit_ref_polys` (append component build), `_search_matches` (rewrite to per-component + assemble), the `E` commit handler (weak-pattern warning), `invoke` and the `R` reset handler (init/clear new attributes).

Run tests with: `cd tests && python -m pytest -q` (rootdir is `tests/`; `conftest.py` puts the repo root on `sys.path` so `from utils.polygon_match import ...` resolves).

---

## Task 1: `fit_both` helper + `Candidate` dataclass

**Files:**
- Modify: `utils/polygon_match.py` (add after `kabsch_mirror_with_scale`, ~line 336, before the `# --- bmesh helpers ---` divider at line 338)
- Test: `tests/test_polygon_match.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_polygon_match.py`:

```python
from utils.polygon_match import fit_both


def test_fit_both_translation_not_mirror():
    tgt = REF_CLOUD + np.array([2.0, -1.0, 4.0])
    T, rmse, is_mirror = fit_both(REF_CLOUD, tgt, scale_mode="KEEP")
    assert not is_mirror
    assert rmse < 1e-6
    homog = np.hstack([REF_CLOUD, np.ones((REF_CLOUD.shape[0], 1))])
    out = (homog @ T.T)[:, :3]
    assert np.allclose(out, tgt, atol=1e-6)


def test_fit_both_detects_reflection():
    tgt = REF_CLOUD.copy()
    tgt[:, 0] = -tgt[:, 0]
    T, rmse, is_mirror = fit_both(REF_CLOUD, tgt, scale_mode="KEEP")
    assert is_mirror
    assert rmse < 1e-6
    assert np.linalg.det(T[:3, :3]) < 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd tests && python -m pytest test_polygon_match.py::test_fit_both_translation_not_mirror -v`
Expected: FAIL with `ImportError: cannot import name 'fit_both'`.

- [ ] **Step 3: Implement `Candidate` and `fit_both`**

In `utils/polygon_match.py`, insert immediately after the end of `kabsch_mirror_with_scale` (after line 335, before line 338 `# --- bmesh helpers ---`):

```python
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


def fit_both(ref_pts: np.ndarray, tgt_pts: np.ndarray,
             scale_mode: str = "KEEP") -> tuple[np.ndarray, float, bool]:
    """Fit ref_pts -> tgt_pts, returning whichever of the proper-rotation and
    reflection-allowing Procrustes fits has the lower RMSE.

    Returns (T_4x4, rmse, is_mirror). `is_mirror` is True when the reflection
    variant won."""
    T_n, rmse_n = kabsch_with_scale(ref_pts, tgt_pts, scale_mode=scale_mode)
    T_m, rmse_m = kabsch_mirror_with_scale(ref_pts, tgt_pts, scale_mode=scale_mode)
    if rmse_m < rmse_n:
        return T_m, float(rmse_m), True
    return T_n, float(rmse_n), False
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd tests && python -m pytest test_polygon_match.py -k fit_both -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add utils/polygon_match.py tests/test_polygon_match.py
git commit -m "feat(aligner): add fit_both + Candidate for constellation matching"
```

---

## Task 2: `assemble_constellations` pure function

**Files:**
- Modify: `utils/polygon_match.py` (add after `fit_both`)
- Test: `tests/test_polygon_match.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_polygon_match.py`:

```python
from utils.polygon_match import Candidate, assemble_constellations


def _rigid(pts, R, t):
    return pts @ np.asarray(R).T + np.asarray(t)


# Two reference components, each 2 faces -> 4 anchors.
REF_C0 = np.array([
    [0.0, 0.0, 0.0], [0.0, 0.0, 0.5],
    [1.0, 0.0, 0.0], [1.0, 0.0, 0.5],
])
REF_C1 = np.array([
    [3.0, 0.0, 0.0], [3.0, 0.0, 0.5],
    [4.0, 0.0, 0.0], [4.0, 0.0, 0.5],
])


def _ref_inputs():
    anchors = [REF_C0, REF_C1]
    cents = [REF_C0.mean(axis=0), REF_C1.mean(axis=0)]
    fc = [2, 2]
    return anchors, cents, fc


def test_assemble_single_component_passthrough():
    t = np.array([5.0, 1.0, -2.0])
    cand = Candidate((10, 11), (REF_C0 + t).mean(axis=0), REF_C0 + t)
    res = assemble_constellations(
        [REF_C0], [REF_C0.mean(axis=0)], [2], 0, [[cand]],
        scale_mode="KEEP", pos_tol=0.1, fit_rmse_rel=0.05, bbox_diag=4.0)
    assert len(res) == 1
    assert res[0]["order"] == (10, 11)
    assert res[0]["faces"] == frozenset((10, 11))
    assert not res[0]["mirror"]


def test_assemble_two_components_correct():
    anchors, cents, fc = _ref_inputs()
    t = np.array([10.0, 0.0, 0.0])
    c0 = Candidate((1, 2), (REF_C0 + t).mean(axis=0), REF_C0 + t)
    c1 = Candidate((3, 4), (REF_C1 + t).mean(axis=0), REF_C1 + t)
    res = assemble_constellations(
        anchors, cents, fc, 0, [[c0], [c1]],
        scale_mode="KEEP", pos_tol=0.1, fit_rmse_rel=0.05, bbox_diag=4.0)
    assert len(res) == 1
    assert res[0]["faces"] == frozenset((1, 2, 3, 4))
    assert res[0]["order"] == (1, 2, 3, 4)
    assert not res[0]["mirror"]


def test_assemble_rejects_wrong_arrangement():
    anchors, cents, fc = _ref_inputs()
    t = np.array([10.0, 0.0, 0.0])
    c0 = Candidate((1, 2), (REF_C0 + t).mean(axis=0), REF_C0 + t)
    bad = REF_C1 + t + np.array([0.0, 0.0, 20.0])  # far from predicted slot
    c1 = Candidate((3, 4), bad.mean(axis=0), bad)
    res = assemble_constellations(
        anchors, cents, fc, 0, [[c0], [c1]],
        scale_mode="KEEP", pos_tol=0.1, fit_rmse_rel=0.05, bbox_diag=4.0)
    assert res == []


def test_assemble_detects_mirror():
    anchors, cents, fc = _ref_inputs()

    def mirror(pts):
        m = pts.copy()
        m[:, 0] = -m[:, 0]
        return m

    c0 = Candidate((1, 2), mirror(REF_C0).mean(axis=0), mirror(REF_C0))
    c1 = Candidate((3, 4), mirror(REF_C1).mean(axis=0), mirror(REF_C1))
    res = assemble_constellations(
        anchors, cents, fc, 0, [[c0], [c1]],
        scale_mode="KEEP", pos_tol=0.5, fit_rmse_rel=0.05, bbox_diag=4.0)
    assert len(res) == 1
    assert res[0]["mirror"]


def test_assemble_degenerate_anchor_pairwise_seed():
    # comp0 is a single face: its 2 anchors lie on the Z axis through origin,
    # so a 90-deg rotation about Z is invisible to a comp0-only fit. The
    # pairwise seed with comp1 (off-axis) must recover it.
    ref_c0_single = np.array([[0.0, 0.0, 0.0], [0.0, 0.0, 0.5]])
    anchors = [ref_c0_single, REF_C1]
    cents = [ref_c0_single.mean(axis=0), REF_C1.mean(axis=0)]
    fc = [1, 2]
    theta = np.pi / 2.0
    R = np.array([[np.cos(theta), -np.sin(theta), 0.0],
                  [np.sin(theta), np.cos(theta), 0.0],
                  [0.0, 0.0, 1.0]])
    t = np.array([7.0, 3.0, 0.0])
    c0 = Candidate((1,), _rigid(ref_c0_single, R, t).mean(axis=0),
                   _rigid(ref_c0_single, R, t))
    c1 = Candidate((3, 4), _rigid(REF_C1, R, t).mean(axis=0),
                   _rigid(REF_C1, R, t))
    res = assemble_constellations(
        anchors, cents, fc, 0, [[c0], [c1]],
        scale_mode="KEEP", pos_tol=0.1, fit_rmse_rel=0.05, bbox_diag=4.0)
    assert len(res) == 1
    assert res[0]["faces"] == frozenset((1, 3, 4))
    assert res[0]["order"] == (1, 3, 4)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd tests && python -m pytest test_polygon_match.py -k assemble -v`
Expected: FAIL with `ImportError: cannot import name 'assemble_constellations'`.

- [ ] **Step 3: Implement `assemble_constellations`**

In `utils/polygon_match.py`, insert immediately after `fit_both` (still before the `# --- bmesh helpers ---` divider):

```python
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
    candidate that passes the global rmse gate."""
    C = len(ref_comp_anchors)
    if C == 0 or anchor_idx >= len(cand_pool):
        return []
    ref_global = np.vstack(ref_comp_anchors)
    bbox = bbox_diag if bbox_diag > 1e-9 else 1.0
    other = [j for j in range(C) if j != anchor_idx]
    results: list[dict] = []
    seen: set[frozenset] = set()

    for ca in cand_pool[anchor_idx]:
        # Hypothesis transform(s) from the anchor candidate.
        if ref_comp_facecount[anchor_idx] >= 2 or not other:
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
                pred = _apply_affine(T_hyp, ref_comp_centroids[j])
                best = None
                best_d = pos_tol
                for cand in cand_pool[j]:
                    if used & set(cand.faces):
                        continue
                    d = float(np.linalg.norm(cand.centroid - pred))
                    if d <= best_d:
                        best_d = d
                        best = cand
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
    return results
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd tests && python -m pytest test_polygon_match.py -k assemble -v`
Expected: 5 passed.

- [ ] **Step 5: Run the whole suite (regression guard)**

Run: `cd tests && python -m pytest -q`
Expected: all passed (33 total: 28 existing + 2 fit_both + ... confirm count grows, none fail).

- [ ] **Step 6: Commit**

```bash
git add utils/polygon_match.py tests/test_polygon_match.py
git commit -m "feat(aligner): add assemble_constellations constellation matcher"
```

---

## Task 3: Build component data in `_commit_ref_polys`

**Files:**
- Modify: `operators/object_aligner.py:950-991` (`_commit_ref_polys` — append after the existing body)

This appends to the existing method. Do NOT remove the existing signature/frame computation — `self.ref_frame_np` is still used by `_compute_fit_poly_force` ([object_aligner.py:1211](../../../operators/object_aligner.py#L1211)).

- [ ] **Step 1: Append component build to `_commit_ref_polys`**

The method currently ends at line 991 with the `self.ref_frame_np = pm.pca_frame(...)` assignment. Insert the following block at the end of the method body (same indentation as the existing statements, inside the method):

```python
        # --- Composite pattern: decompose the selection into connected
        # components so a multi-island / scattered selection becomes one rigid
        # constellation. (A single island degenerates to one component, i.e.
        # the original single-pattern behavior.)
        ref_obj = next(iter(self.ref_polys), None)
        self.ref_sub_patterns = []
        self.ref_comp_anchors = []
        self.ref_comp_centroids = []
        self.ref_comp_facecount = []
        self.ref_anchor_component = 0
        self.ref_pattern_weak = False
        if ref_obj is None:
            return
        try:
            ref_bm = _bmesh_for(self, ref_obj)
        except (RuntimeError, ReferenceError):
            return
        components = pm.components_in_selection(ref_bm, set(self.ref_polys[ref_obj]))
        sub_patterns = [pm.build_face_pattern(ref_bm, comp) for comp in components]
        sub_patterns = [p for p in sub_patterns if p["faces"]]
        # Most distinctive component first: descending face count, then area.
        sub_patterns.sort(key=lambda p: (-len(p["faces"]), -sum(p["areas"])))
        self.ref_sub_patterns = sub_patterns
        if not sub_patterns:
            return

        # Constant anchor offset from the mean sqrt-area over ALL pattern faces
        # (kept identical in spirit to the previous single-pattern offset, but
        # spanning every component).
        all_areas = [a for p in sub_patterns for a in p["areas"]]
        mean_sqrt_area = float(np.mean([np.sqrt(max(a, 1e-12)) for a in all_areas]))
        self.ref_anchor_offset = max(0.5 * mean_sqrt_area, 1e-6)

        # Per-component anchors + global anchor cloud (in component order).
        global_faces = []
        for p in sub_patterns:
            anchors = self._face_anchor_points(ref_obj, p["faces"])
            self.ref_comp_anchors.append(anchors)
            self.ref_comp_centroids.append(
                anchors.mean(axis=0) if anchors.size else np.zeros(3))
            self.ref_comp_facecount.append(len(p["faces"]))
            global_faces.extend(p["faces"])
        self.ref_pattern_anchors = self._face_anchor_points(ref_obj, global_faces)
        self.ref_anchor_component = 0
        # Weak pattern: anchor component is a single face -> matching relies
        # almost entirely on inter-component arrangement and is less reliable.
        self.ref_pattern_weak = self.ref_comp_facecount[0] < 2
```

Note: `self.ref_anchor_offset` and `self.ref_pattern_anchors` set here replace the values previously computed in `_search_matches` (removed in Task 4). `_face_anchor_points` reads `self.ref_anchor_offset`, so it is set before the anchor loop above — order matters, keep it as written.

- [ ] **Step 2: Verify the module imports cleanly**

Run: `cd tests && python -m pytest -q`
Expected: still all passing (this file isn't imported by pytest, but a syntax error would not surface here; the real check is Step 3). Also run a syntax compile:

Run: `python -c "import ast; ast.parse(open(r'b:/scripts/addons/InteractionOps/operators/object_aligner.py', encoding='utf-8').read())"`
Expected: no output (parses cleanly).

- [ ] **Step 3: Commit**

```bash
git add operators/object_aligner.py
git commit -m "feat(aligner): decompose ref selection into constellation components"
```

---

## Task 4: Rewrite `_search_matches` to use the constellation matcher

**Files:**
- Modify: `operators/object_aligner.py:993-1107` (replace the whole `_search_matches` method body)

- [ ] **Step 1: Replace `_search_matches`**

Replace the entire method (from its `def _search_matches(self, context):` line and docstring through the final `if n_kept > 0: return` at line 1107) with:

```python
    def _search_matches(self, context):
        """Per-component candidate search + constellation assembly. For each
        scan object, find candidates for every reference sub-pattern, then
        assemble candidate tuples whose mutual arrangement reproduces the ref
        constellation (validated by a single global Kabsch fit). Populates
        self.match_hints / match_orders / match_mirrors with ONE entry per
        assembled constellation — same shape downstream code already expects."""
        from ..utils import polygon_match as pm
        self.match_hints = {}
        self.match_orders = {}
        self.match_mirrors = {}
        if not getattr(self, "ref_sub_patterns", None) or not self.ref_polys:
            return
        ref_obj = next(iter(self.ref_polys))
        ref_all_faces = frozenset().union(
            *[set(p["faces"]) for p in self.ref_sub_patterns])

        sv = getattr(context, "space_data", None)
        viewport = sv if (sv is not None and sv.type == "VIEW_3D") else None
        ref_bbox_diag = self.ref_bbox_diag if self.ref_bbox_diag > 1e-9 else 1.0

        scan_objs = set(self.target_objs)
        if ref_obj is not None:
            scan_objs.add(ref_obj)

        # Two-tier escalation: tier 0 tight, tier 1 wider area/rmse/position
        # tolerances. pos_tol is a fraction of the ref bbox diagonal.
        tier_specs = [
            {"area_tol": 0.20, "fit_rmse": 0.05, "pos_tol": 0.10},
            {"area_tol": 0.35, "fit_rmse": 0.15, "pos_tol": 0.20},
        ]
        for tier_idx, spec in enumerate(tier_specs):
            self.match_hints = {}
            self.match_orders = {}
            self.match_mirrors = {}
            pos_tol = spec["pos_tol"] * ref_bbox_diag
            n_objs = n_kept = n_mirror = 0
            for obj in scan_objs:
                if obj in self.source_set or obj.type != "MESH" or obj.data is None:
                    continue
                if not obj.visible_get(viewport=viewport):
                    continue
                n_objs += 1
                original = obj.original
                try:
                    bm = _bmesh_for(self, original)
                except (RuntimeError, ReferenceError):
                    continue
                # Per-component candidate pool on this object.
                cand_pool = []
                for p in self.ref_sub_patterns:
                    expected = 2 * len(p["faces"])
                    cands = []
                    raw = pm.find_pattern_matches(
                        bm, p, area_tol=spec["area_tol"], allow_overlap=True)
                    for match in raw:
                        anchors = self._face_anchor_points(original, match)
                        if anchors.shape[0] != expected:
                            continue
                        cands.append(pm.Candidate(
                            tuple(match), anchors.mean(axis=0), anchors))
                    cand_pool.append(cands)
                assemblies = pm.assemble_constellations(
                    self.ref_comp_anchors, self.ref_comp_centroids,
                    self.ref_comp_facecount, self.ref_anchor_component,
                    cand_pool, scale_mode=self.scale_mode, pos_tol=pos_tol,
                    fit_rmse_rel=spec["fit_rmse"], bbox_diag=ref_bbox_diag)
                for asm in assemblies:
                    # Skip the assembly that IS the ref selection itself.
                    if original is ref_obj and asm["faces"] == ref_all_faces:
                        continue
                    self.match_hints.setdefault(original, []).append(asm["faces"])
                    self.match_orders.setdefault(original, []).append(asm["order"])
                    self.match_mirrors.setdefault(original, []).append(asm["mirror"])
                    n_kept += 1
                    if asm["mirror"]:
                        n_mirror += 1
            print(f"[aligner] search tier {tier_idx} (area={spec['area_tol']} "
                  f"fit_rmse={spec['fit_rmse']} pos_tol={spec['pos_tol']}): "
                  f"components={len(self.ref_sub_patterns)} objs={n_objs} "
                  f"kept={n_kept} (mirror={n_mirror}) hints={len(self.match_hints)}")
            if n_kept > 0:
                return
```

Note: `match_hints[obj]` stays a list of `frozenset` (each = one constellation), `match_orders[obj]` a list of `tuple` (global face order), `match_mirrors[obj]` a list of `bool` — exactly what `_seed_hint_fits`, `_enqueue_target_poly_stamps`, `_toggle_hint_component`, and the draw code already consume. No downstream change needed.

- [ ] **Step 2: Verify syntax**

Run: `python -c "import ast; ast.parse(open(r'b:/scripts/addons/InteractionOps/operators/object_aligner.py', encoding='utf-8').read())"`
Expected: no output.

- [ ] **Step 3: Commit**

```bash
git add operators/object_aligner.py
git commit -m "feat(aligner): match composite patterns via constellation assembly"
```

---

## Task 5: Init/clear new attributes + weak-pattern warning

**Files:**
- Modify: `operators/object_aligner.py:621-638` (`invoke` state init)
- Modify: `operators/object_aligner.py:755-776` (`R` reset handler)
- Modify: `operators/object_aligner.py:737-752` (`E` commit handler — warning)

- [ ] **Step 1: Initialize new attributes in `invoke`**

In `invoke`, find the polygon-reference state block (lines 621-638). After the line `self.ref_pattern_anchors = None` (line 633), add:

```python
        self.ref_sub_patterns = []
        self.ref_comp_anchors = []
        self.ref_comp_centroids = []
        self.ref_comp_facecount = []
        self.ref_anchor_component = 0
        self.ref_pattern_weak = False
```

- [ ] **Step 2: Clear them in the `R` reset handler**

In the `R` key handler (lines 755-776), after the line `self.ref_pattern_anchors = None` (line 772), add:

```python
                self.ref_sub_patterns = []
                self.ref_comp_anchors = []
                self.ref_comp_centroids = []
                self.ref_comp_facecount = []
                self.ref_anchor_component = 0
                self.ref_pattern_weak = False
```

- [ ] **Step 3: Add the weak-pattern warning to the `E` commit branch**

In the `E` handler's commit branch (lines 737-752), the code currently is:

```python
                if self.mode == MODE_PICK_REF_POLY:
                    if not self.ref_polys:
                        self.report({"WARNING"}, "Ref poly set is empty")
                        return {"RUNNING_MODAL"}
                    self._commit_ref_polys(context)
                    self._search_matches(context)
```

Insert the warning right after `self._commit_ref_polys(context)` and before `self._search_matches(context)`:

```python
                    self._commit_ref_polys(context)
                    if getattr(self, "ref_pattern_weak", False):
                        self.report(
                            {"WARNING"},
                            "Weak pattern: mark at least one island of 2+ faces "
                            "for reliable matching")
                    self._search_matches(context)
```

- [ ] **Step 4: Verify syntax**

Run: `python -c "import ast; ast.parse(open(r'b:/scripts/addons/InteractionOps/operators/object_aligner.py', encoding='utf-8').read())"`
Expected: no output.

- [ ] **Step 5: Commit**

```bash
git add operators/object_aligner.py
git commit -m "feat(aligner): init/reset constellation state + weak-pattern warning"
```

---

## Task 6: Live verification in Blender

**Files:** none (manual / blender-mcp verification)

- [ ] **Step 1: Reload the addon in the running Blender**

Use the blender-mcp skill to reload the `InteractionOps` modules so the edited operator is live.

- [ ] **Step 2: Build a test scene**

Create a reference mesh with two clearly separated face islands forming a recognizable arrangement (e.g. two raised square pads a fixed distance apart), plus one or more target objects that contain the same two-pad arrangement in different positions/orientations, and at least one mirrored copy.

- [ ] **Step 3: Run the aligner workflow**

Select a rig object, invoke `iops.object_aligner`. Q (pick ref), W (optionally add targets), E (mark faces on BOTH islands of the ref), E again to commit + search.

Expected:
- The console prints `[aligner] search tier 0 ... components=2 ... kept=N`.
- Each found two-pad arrangement is highlighted as ONE toggleable constellation; clicking any face of it toggles the whole group.
- Mirrored arrangements are found and flagged (one rig copy each).
- Enter stamps one rig copy per kept constellation.

- [ ] **Step 4: Regression — single island**

Repeat with a single connected island marked as the reference. Expected: behavior identical to before this feature (matches found as today).

- [ ] **Step 5: Weak-pattern path**

Mark only scattered single faces (no island of 2+ faces). Expected: a header warning "Weak pattern: mark at least one island of 2+ faces for reliable matching", and matching still attempts via pairwise seeding.

- [ ] **Step 6: Final full test run + commit any fixes**

Run: `cd tests && python -m pytest -q`
Expected: all passed. Commit any fixes discovered during live verification.

---

## Self-Review

**Spec coverage:**
- "Any marked set = one rigid pattern" → Task 3 (component decomposition + global anchors), Task 4 (assembly). ✓
- "One matched constellation → one rig copy" → Task 4 records one entry per assembly; downstream `_enqueue_target_poly_stamps` stamps one per entry (unchanged). ✓
- "Mutual arrangement is part of the signature" → `assemble_constellations` predict + `pos_tol` + global rmse gate (Task 2). ✓
- "Mirror is a whole-constellation property" → `fit_both` on the global cloud returns the constellation mirror flag (Task 2, Task 4). ✓
- "Pairwise seed for degenerate single-face anchor" → Task 2 degenerate branch + `test_assemble_degenerate_anchor_pairwise_seed`. ✓
- "Weak-pattern warning" → Task 3 sets `ref_pattern_weak`, Task 5 reports it. ✓
- "Two-tier escalation extended with pos_tol" → Task 4 `tier_specs`. ✓
- "Backward compatible for single island (k=1)" → `assemble_constellations` C==1 path + `test_assemble_single_component_passthrough` + Task 6 Step 4. ✓
- "Downstream unchanged" → match_* stored in the existing list-of-frozenset / list-of-tuple / list-of-bool shape (Task 4 note). ✓

**Placeholder scan:** No TBD/TODO; every code step shows complete code; every command has expected output. ✓

**Type consistency:** `Candidate(faces: tuple, centroid: np.ndarray, anchors: np.ndarray)` constructed identically in Task 4 and tests. `assemble_constellations(...)` signature identical across definition (Task 2) and call site (Task 4): positional `ref_comp_anchors, ref_comp_centroids, ref_comp_facecount, anchor_idx, cand_pool` + keyword `scale_mode, pos_tol, fit_rmse_rel, bbox_diag`. `fit_both` returns `(T, rmse, is_mirror)` everywhere. Attribute names (`ref_sub_patterns`, `ref_comp_anchors`, `ref_comp_centroids`, `ref_comp_facecount`, `ref_anchor_component`, `ref_pattern_weak`, `ref_pattern_anchors`, `ref_anchor_offset`, `ref_bbox_diag`) consistent across Tasks 3-5. ✓
