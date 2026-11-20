# UV Stripe Stretch-Free Fit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fit to Active scales every piece by one factor, defaults to Height, and UV Stripe shows the faces that are still stretched.

**Architecture:** The fit is one pure function, `utils/uv_stripe_core.fit_to_reference`, reached by UV Stripe, Inset, Edge Slide and UV Pipe through `operators/uv_stripe_bridge.apply_maps`; only its body changes. Stretch is measured by a new pure function in the core, applied to the written UVs by a bmesh helper in the bridge, and shown by the UV Stripe operator only.

**Tech Stack:** Python 3.13, Blender 5.3 (`bpy`, `bmesh`), pytest for `tests/*.py`, headless Blender for `tests/blender/*.py`.

**Spec:** `docs/superpowers/specs/2026-11-20-uv-stripe-stretch-free-fit-design.md`

## Global Constraints

- Every touched file is LF: check `git ls-files --eol <file>` before editing and keep the ending.
- Lint: `uvx ruff@0.12.0 check <files>` must pass.
- Pure tests: `python -m pytest tests -q` from the repo root.
- Headless Blender tests run through PowerShell with `BLENDER_USER_RESOURCES`, `BLENDER_USER_SCRIPTS`, `BLENDER_USER_CONFIG`, `BLENDER_USER_EXTENSIONS`, `BLENDER_USER_DATAFILES` all set to empty scratch directories (never inherit the shell's values):
  `& "C:\Program Files\Blender Foundation\Blender 5.3\blender.exe" --background --factory-startup --python-exit-code 1 --python tests/blender/<file>.py`
- No `ui/draw/theme.py`, `prefs/theme.py` or other theme change: the main checkout holds uncommitted edits to them.
- `utils/uv_match_core.py` and Visual UV are not changed.
- UI labels use full words, no abbreviations. Docs and commit messages in English. No internal paths or asset names in committed files.
- Commits: one per task on `feat/uv-stripe-uniform-fit`, `feat(uv-stripe): ...`; do not push.
- `STRETCH_TOLERANCE = 1.05`; default `active_fit = "HEIGHT"`.

## Review Focus

- A piece with a zero-size side (a degenerate strip) fitted to the reference: factor 1, no division by zero. (Task 1 test)
- A portrait stub against a landscape reference: not turned, not mirrored. (Task 1 test)
- A face with a doubled vertex or a zero-area 3D triangle: `face_stretch` skips that triangle instead of raising. (Task 2 test)
- A face collapsed in UV only: reported as stretched (`math.inf`), not as a crash. (Task 2 test)
- An object with non-uniform scale: stretch is measured against world-space positions, as the layout is. (Task 3 test)

---

### Task 1: Uniform `fit_to_reference`

**Files:**
- Modify: `utils/uv_stripe_core.py` (`fit_to_reference`, and its import of `dimension_fit` if no longer used)
- Test: `tests/test_uv_stripe_split.py:336-362`

**Interfaces:**
- Produces: `fit_to_reference(uv: dict, reference: tuple[Vec2, Vec2], mode: str = "BOTH") -> dict`, same signature as today. One factor `s` for both axes, about the piece's box centre, then the centre moves onto the reference's: `WIDTH` s = rw / tw, `HEIGHT` s = rh / th, `BOTH` s = min of the two. A piece side `<= 1e-10` contributes no factor (`BOTH` uses the other one; if none is left, s = 1). No quarter turn.

- [ ] **Step 1: Replace the two parametrized tests** (`..._without_a_turn`, `..._turns_a_transposed_piece`) with:

```python
@pytest.mark.parametrize("mode, size", [("BOTH", (2.0, 0.5)), ("WIDTH", (2.0, 0.5)), ("HEIGHT", (4.0, 1.0))])
def test_fit_to_reference_scales_both_axes_by_one_factor(mode, size):
    piece = _rect_piece(1.0, 0.25, at=(5.0, 5.0))
    out = fit_to_reference(piece, ((0.0, 0.0), (2.0, 1.0)), mode)
    (u0, v0), (u1, v1) = bbox(out)
    assert (u1 - u0, v1 - v0) == pytest.approx(size)
    assert ((u0 + u1) / 2, (v0 + v1) / 2) == pytest.approx((1.0, 0.5))
    assert _area(out) > 0


@pytest.mark.parametrize("mode, size", [("BOTH", (0.125, 0.5)), ("WIDTH", (2.0, 8.0)), ("HEIGHT", (0.125, 0.5))])
def test_fit_to_reference_never_turns_a_piece(mode, size):
    piece = _rect_piece(0.25, 1.0, at=(3.0, 3.0))           # portrait against a landscape reference
    out = fit_to_reference(piece, ((1.0, 1.0), (3.0, 1.5)), mode)
    (u0, v0), (u1, v1) = bbox(out)
    assert (u1 - u0, v1 - v0) == pytest.approx(size)
    assert ((u0 + u1) / 2, (v0 + v1) / 2) == pytest.approx((2.0, 1.25))
    assert out[(0, 1)][1] == pytest.approx(out[(0, 0)][1]) and out[(0, 1)][0] > out[(0, 0)][0]   # first edge still +u


@pytest.mark.parametrize("mode", ["BOTH", "WIDTH", "HEIGHT"])
def test_fit_to_reference_with_a_flat_piece(mode):
    piece = {(0, 0): (1.0, 2.0), (0, 1): (3.0, 2.0)}        # no height
    out = fit_to_reference(piece, ((0.0, 0.0), (4.0, 1.0)), mode)
    width = out[(0, 1)][0] - out[(0, 0)][0]
    assert width == pytest.approx(2.0 if mode == "HEIGHT" else 4.0)
    assert out[(0, 0)][1] == pytest.approx(0.5)
```

`test_fit_to_reference_keeps_the_reference` stays as it is.

- [ ] **Step 2:** `python -m pytest tests/test_uv_stripe_split.py -q` — the new tests FAIL.
- [ ] **Step 3:** Rewrite the body and docstring of `fit_to_reference` per Interfaces.
- [ ] **Step 4:** `python -m pytest tests -q` — all PASS.
- [ ] **Step 5:** Commit `feat(uv-stripe): Fit to Active scales a piece by one factor, never turns it`.

### Task 2: `face_stretch`

**Files:**
- Modify: `utils/uv_stripe_core.py`
- Test: create `tests/test_uv_stripe_stretch.py`

**Interfaces:**
- Produces: `STRETCH_TOLERANCE = 1.05` and `face_stretch(points: list[Vec3], uvs: list[Vec2]) -> float` (corners in face order, same length): the largest anisotropy over the fan triangles (0, k, k+1); 1.0 for a face with no measurable triangle.

Per triangle: with `e1 = p1 - p0`, `e2 = p2 - p0`, put the 3D triangle in its own plane as `(x1, 0)`, `(x2, y2)` (`x1 = |e1|`, `x2 = e2·e1 / x1`, `y2 = |e2 - x2·e1/x1|`). Skip the triangle when `x1 * y2 <= 1e-12 * max(x1, |e2|)**2` (degenerate in 3D). The map to UV has columns `a = d1 / x1` and `b = (d2 - x2 * a) / y2` (`d1 = q1 - q0`, `d2 = q2 - q0`). With `E = a·a`, `G = b·b`, `F = a·b`, `r = sqrt(((E - G) / 2)**2 + F**2)`: singular values squared are `(E + G) / 2 ± r`; the ratio is `sqrt(big / small)`, `math.inf` when `small <= 1e-18 * big` or `big == 0`.

- [ ] **Step 1: Write the tests**

```python
import math

import pytest

from utils.uv_stripe_core import STRETCH_TOLERANCE, face_stretch

QUAD = [(0.0, 0.0, 0.0), (2.0, 0.0, 0.0), (2.0, 0.0, 1.0), (0.0, 0.0, 1.0)]      # 2 x 1, standing in XZ


def _uv(sx=1.0, sy=1.0, shear=0.0):
    return [(x * sx + z * shear, z * sy) for x, _y, z in QUAD]


def test_tolerance():
    assert STRETCH_TOLERANCE == 1.05


def test_true_size_and_uniform_scale_are_not_stretch():
    assert face_stretch(QUAD, _uv()) == pytest.approx(1.0)
    assert face_stretch(QUAD, _uv(0.3, 0.3)) == pytest.approx(1.0)
    turned = [(-v, u) for u, v in _uv()]
    assert face_stretch(QUAD, turned) == pytest.approx(1.0)


def test_one_axis_scale_is_its_ratio():
    assert face_stretch(QUAD, _uv(sx=2.0)) == pytest.approx(2.0)
    assert face_stretch(QUAD, _uv(sy=4.0)) == pytest.approx(4.0)


def test_shear_is_stretch():
    assert face_stretch(QUAD, _uv(shear=0.5)) > STRETCH_TOLERANCE


def test_worst_triangle_of_an_ngon_counts():
    points = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (2.0, 0.0, 0.0), (2.0, 1.0, 0.0), (0.0, 1.0, 0.0)]
    uvs = [(0.0, 0.0), (1.0, 0.0), (2.0, 0.0), (2.0, 1.0), (0.0, 1.0)]
    assert face_stretch(points, uvs) == pytest.approx(1.0)            # the collinear fan triangle is skipped
    uvs[3] = (3.0, 1.0)
    assert face_stretch(points, uvs) > STRETCH_TOLERANCE


def test_degenerate_input():
    doubled = [QUAD[0], QUAD[0], QUAD[2], QUAD[3]]
    assert face_stretch(doubled, [(0.0, 0.0), (0.0, 0.0), (2.0, 1.0), (0.0, 1.0)]) == pytest.approx(1.0)
    assert face_stretch([QUAD[0]] * 4, _uv()) == 1.0
    assert face_stretch(QUAD, [(0.0, 0.0)] * 4) == math.inf
    assert face_stretch(QUAD, [(0.0, 0.0), (2.0, 0.0), (2.0, 0.0), (0.0, 0.0)]) == math.inf
```

- [ ] **Step 2:** `python -m pytest tests/test_uv_stripe_stretch.py -q` — FAIL (import error).
- [ ] **Step 3:** Implement per Interfaces, next to `bbox` in `utils/uv_stripe_core.py`.
- [ ] **Step 4:** `python -m pytest tests -q` — PASS.
- [ ] **Step 5:** Commit `feat(uv-stripe): face_stretch measures a face's UV anisotropy`.

### Task 3: Defaults, labels and the stretch display

**Files:**
- Modify: `operators/uv_stripe_bridge.py` (`ACTIVE_MODE_ITEM`, `ACTIVE_FIT_ITEMS`, the `apply_stripes` / `apply_maps` docstrings, new helper)
- Modify: `operators/mesh_uv_stripe.py` (`active_fit` default and description, `_Result`, `_lay_out`, `_report_result`, `_status_text`, `_draw_view_callback`, `_draw_callback`)
- Modify: `operators/mesh_uv_pipe.py:190-195` (`active_fit` default and description)
- Test: `tests/blender/test_uv_stripe_operator.py`, `tests/blender/test_uv_pipe_operator.py`, `tests/blender/test_inset_uv_stripe.py`, `tests/blender/test_edge_slide.py`

**Interfaces:**
- Consumes: `core.fit_to_reference` (Task 1), `core.face_stretch`, `core.STRETCH_TOLERANCE` (Task 2).
- Produces:
  - `uv_stripe_bridge.stretched_faces(bm, faces: Iterable[BMFace], matrix, tolerance: float = core.STRETCH_TOLERANCE) -> list[BMFace]`: the faces whose `face_stretch` of (world-space corner positions `matrix @ v.co`, active UV layer corners) exceeds `tolerance`; empty without a UV layer.
  - `_Result.stretched: list` (world-space segment end points of the stretched faces' edges, each edge once) and `_Result.stretched_faces: int`.

**Copy (exact):**
- `ACTIVE_FIT_ITEMS`: `("BOTH", "Width and Height", "Fit the piece inside the reference strip's bounding box, keeping its proportions")`, `("WIDTH", "Width", "Match the reference's width; the height is scaled by the same factor")`, `("HEIGHT", "Height", "Match the reference's height; the width is scaled by the same factor")`.
- `ACTIVE_MODE_ITEM` description: `"Lay the strip holding the active face out In Place, and fit every other piece to its UV bounding box without stretching it"`.
- `active_fit` description (UV Stripe: "pieces", "strip"; UV Pipe: "parts", "part"): `"How Active sizes the other pieces by the bounding box of the strip holding the active face"`.
- Report, level WARNING, when `stretched_faces`: `f"UV Stripe: {n} stretched face(s)"`.
- HUD header: `f"{done} strip(s), {n} stretched face(s)"` when n, else as today. Status bar: `f"{done} strip(s), {n} stretched | "` when n.

- [ ] **Step 1: Update and add the headless tests** in `tests/blender/test_uv_stripe_operator.py` (new tests also go in the run list at the end of the file):
  - `test_active_fits_the_other_strip_onto_the_reference`: expected patch sizes become `("BOTH", (0.15, 0.1)), ("WIDTH", (0.4, 0.8 / 3)), ("HEIGHT", (0.15, 0.1))`.
  - `test_operator_defaults`: `rna["active_fit"].default == "HEIGHT"`.
  - `test_default_active_fit_matches_the_width_only_and_leaves_a_clean_mesh_alone` renamed `test_default_active_fit_matches_the_height_and_leaves_a_clean_mesh_alone`; last assert: patch height equals the reference's height and patch width is `0.15`.
  - The `D` key cycle test (around line 638): the order from the new default is `BOTH`, `WIDTH`, `HEIGHT`.
  - New `test_active_fit_stretches_no_face`: for each of the three fits, `_two_strips()`, `_run(mode="ACTIVE", active_fit=fit, offset_axis="NONE")`, then `uv_stripe_bridge.stretched_faces(bm, selected faces, obj.matrix_world) == []`.
  - New `test_stretched_faces_are_measured_in_world_space`: `_two_strips()` with `obj.scale = (3, 1, 1)`, same run with the defaults: `stretched_faces(...) == []`; then multiply every selected face's UV `u` by 2 and assert every selected face is returned.
  - New `test_rectangles_on_a_bent_strip_reports_stretched_faces`: build, with the file's existing helpers, a one-face-wide strip that bends in its plane, run `layout="STRAIGHT", split_at_bends=False`, call the operator's `_lay_out` as the file's other `_lay_out` tests do and assert `result.stretched_faces > 0` and `len(result.stretched) % 2 == 0 and result.stretched`.
  - `tests/blender/test_uv_pipe_operator.py:247` default becomes `"HEIGHT"`; fix its `D` cycle expectation (line 1426) to the order from the new default.
- [ ] **Step 2:** Run the four headless files; the changed and new UV Stripe / UV Pipe tests FAIL. Note any Inset / Edge Slide failure caused by Task 1.
- [ ] **Step 3:** Implement: copy and defaults; `stretched_faces`; in `_lay_out`, after `finish_stripes`, measure the pieces' faces and fill `_Result`; the report, status and HUD strings; in `_draw_view_callback` draw `result.stretched` with `draw.edges_world(points, role=Role.LOCKED_LINE, context=context)` above the outline and below the tears.
- [ ] **Step 4:** Update the Inset / Edge Slide expectations that Task 1 changed (only sizes that follow from the uniform fit; anything else is a finding to report, not to paper over).
- [ ] **Step 5:** All four headless files, `python -m pytest tests -q` and `uvx ruff@0.12.0 check operators utils tests` PASS.
- [ ] **Step 6:** Commit `feat(uv-stripe): Height is the default fit; stretched faces are shown and counted`.

### Task 4: Docs

**Files:**
- Modify: `docs/operators/op_mesh_uv_stripe.md`, `docs/operators/op_mesh_uv_pipe.md`

- [ ] **Step 1:** `op_mesh_uv_stripe.md`: intro sentence (the viewport also shows stretched faces); Controls `D` row order `Height → Width and Height → Width`; **Mode** / Active (no quarter turn, fitted without stretch); **Fit to Active** rewritten for the uniform factor with Height the default, one line on trims (Height puts every piece on the reference's band at one texel density; with Orientation = Vertical use Width); a short "Stretched faces" paragraph: measured per face against its real shape, shown above 5 %, typical causes (Rectangles on a bend, a bend below Bend Angle, curved rails).
- [ ] **Step 2:** `op_mesh_uv_pipe.md`: the same Fit to Active wording and default.
- [ ] **Step 3:** Commit `docs(uv-stripe): uniform Fit to Active and stretched faces`.
