# Object Aligner Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a modal operator `iops.object_aligner` that transfers the selected "rig" of objects onto raycast-picked target objects, preserving each object's transform relative to a picked reference, using topology-aware alignment that survives baked (applied) target transforms.

**Architecture:** Two units. (1) `utils/alignment_fit.py` — a pure NumPy point-set registration solver (Kabsch / Umeyama / affine) with **no bpy import**, fully unit-tested with pytest. (2) `operators/object_aligner.py` — the modal operator, HUD/Help builders, POST_VIEW draw callbacks, raycast picking glue, duplication and collection logic; it converts NumPy↔mathutils and calls the solver. State lives on the operator instance, mirroring `operators/object_radial_array.py`.

**Tech Stack:** Blender Python (`bpy`, `mathutils`, `gpu`), NumPy (bundled with Blender), existing addon modules: `utils.picking` (`raycast_from_mouse`), `ui.draw` (`safe_handler_add/remove`, `primitives`, `draw_scope`), `ui.draw.theme` (`Role`), `ui.hud` (`HUDOverlay`, `HelpOverlay`, `HUDSection`, `HUDItem`, `HUDParam`, toggles, `capture_event`).

**Spec:** [docs/superpowers/specs/2026-05-27-object-aligner-design.md](../specs/2026-05-27-object-aligner-design.md)

**Testing note:** The solver (`utils/alignment_fit.py`) is pure NumPy and is verified with real pytest unit tests in `tests/test_alignment_fit.py`, run with any Python that has `numpy` + `pytest` (no Blender needed):
`python -m pytest tests/test_alignment_fit.py -v`
(If pytest is missing: `python -m pip install pytest numpy`.)
The operator, modal loop, picking, preview, HUD and duplication run inside Blender and cannot be pytest-tested; each operator task ends with a `blender-mcp` smoke check (load addon → run operator on a known scene → inspect `bpy` state), then a commit.

---

## File Structure

- Create: `utils/alignment_fit.py` — pure NumPy solver. Functions: `kabsch`, `umeyama`, `affine_fit`, `solve_fit`. Inputs/outputs are NumPy arrays; no bpy/mathutils import so it is unit-testable standalone. ~90 LOC.
- Create: `tests/test_alignment_fit.py` — pytest unit tests for the solver.
- Create: `tests/__init__.py` — empty, marks the tests package.
- Create: `operators/object_aligner.py` — the operator, helpers, draw callbacks, HUD/Help builders, picking/duplication glue, all in one file (~450 LOC). Mirrors `operators/object_radial_array.py`.
- Modify: `utils/picking.py` — add an `exclude=` blocklist parameter to `raycast_from_mouse` so source objects can be pierced through.
- Modify: `__init__.py` — import + register `IOPS_OT_Object_Aligner`.
- Modify: `ui/iops_pie_menu.py` — add a menu entry next to `iops.object_radial_array`.

No new theme keys. Reused roles: `Role.GHOST_DEFAULT` + `Role.GHOST_EDGE` (rig ghost preview), `Role.GHOST_ACTIVE` (reference highlight fill), `Role.GHOST_PREVIEW` (picked-target highlight fill).

---

### Task 1: Solver — Kabsch (rigid R + t)

**Files:**
- Create: `utils/alignment_fit.py`
- Create: `tests/__init__.py`
- Create: `tests/test_alignment_fit.py`

- [ ] **Step 1: Write the failing test**

Create `tests/__init__.py` (empty file).

Create `tests/test_alignment_fit.py`:

```python
import math
import numpy as np
import pytest

from utils.alignment_fit import kabsch


# A non-degenerate reference cloud (unit cube corners) reused across tests.
REF = np.array([
    [0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0],
    [1.0, 1.0, 0.0], [1.0, 0.0, 1.0], [0.0, 1.0, 1.0], [1.0, 1.0, 1.0],
])


def _rot_z(deg):
    a = math.radians(deg)
    c, s = math.cos(a), math.sin(a)
    return np.array([[c, -s, 0.0], [s, c, 0.0], [0.0, 0.0, 1.0]])


def test_kabsch_pure_translation():
    t = np.array([1.0, 2.0, 3.0])
    tgt = REF + t
    R, tt = kabsch(REF, tgt)
    assert np.allclose(R, np.eye(3), atol=1e-6)
    assert np.allclose(tt, t, atol=1e-6)


def test_kabsch_recovers_rotation():
    Rz = _rot_z(90.0)
    tgt = REF @ Rz.T
    R, tt = kabsch(REF, tgt)
    # Applying the recovered transform to REF reproduces tgt.
    recon = REF @ R.T + tt
    assert np.allclose(recon, tgt, atol=1e-6)
    assert np.isclose(np.linalg.det(R), 1.0, atol=1e-6)


def test_kabsch_no_reflection_on_mirrored_input():
    # Mirror across X; a naive SVD would return a reflection (det = -1).
    mirror = np.array([[-1.0, 0, 0], [0, 1.0, 0], [0, 0, 1.0]])
    tgt = REF @ mirror.T
    R, _ = kabsch(REF, tgt)
    assert np.isclose(np.linalg.det(R), 1.0, atol=1e-6)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_alignment_fit.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'utils.alignment_fit'` (or ImportError for `kabsch`).

- [ ] **Step 3: Write minimal implementation**

Create `utils/alignment_fit.py`:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_alignment_fit.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add utils/alignment_fit.py tests/__init__.py tests/test_alignment_fit.py
git commit -m "feat(alignment_fit): add Kabsch rigid point-set solver with tests"
```

---

### Task 2: Solver — Umeyama (rigid + uniform scale)

**Files:**
- Modify: `utils/alignment_fit.py`
- Modify: `tests/test_alignment_fit.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_alignment_fit.py`:

```python
from utils.alignment_fit import umeyama


def test_umeyama_recovers_uniform_scale():
    Rz = _rot_z(30.0)
    s = 2.5
    t = np.array([4.0, -1.0, 0.5])
    tgt = s * (REF @ Rz.T) + t
    R, tt, scale = umeyama(REF, tgt)
    recon = scale * (REF @ R.T) + tt
    assert np.allclose(recon, tgt, atol=1e-6)
    assert np.isclose(scale, s, atol=1e-6)
    assert np.isclose(np.linalg.det(R), 1.0, atol=1e-6)


def test_umeyama_unit_scale_when_rigid():
    Rz = _rot_z(45.0)
    tgt = REF @ Rz.T + np.array([1.0, 0.0, 0.0])
    _R, _t, scale = umeyama(REF, tgt)
    assert np.isclose(scale, 1.0, atol=1e-6)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_alignment_fit.py -v`
Expected: FAIL — `ImportError: cannot import name 'umeyama'`.

- [ ] **Step 3: Write minimal implementation**

Append to `utils/alignment_fit.py`:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_alignment_fit.py -v`
Expected: PASS (5 passed).

- [ ] **Step 5: Commit**

```bash
git add utils/alignment_fit.py tests/test_alignment_fit.py
git commit -m "feat(alignment_fit): add Umeyama similarity solver with tests"
```

---

### Task 3: Solver — affine fit + `solve_fit` dispatcher (4x4 output)

**Files:**
- Modify: `utils/alignment_fit.py`
- Modify: `tests/test_alignment_fit.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_alignment_fit.py`:

```python
from utils.alignment_fit import affine_fit, solve_fit


def _apply4(m4, pts):
    homog = np.hstack([pts, np.ones((pts.shape[0], 1))])
    out = homog @ m4.T
    return out[:, :3]


def test_affine_recovers_non_uniform_scale():
    a = np.diag([1.0, 2.0, 3.0])
    t = np.array([0.5, 0.0, -1.0])
    tgt = REF @ a.T + t
    m4 = affine_fit(REF, tgt)
    assert np.allclose(_apply4(m4, REF), tgt, atol=1e-6)


def test_solve_fit_uniform_is_default_path():
    Rz = _rot_z(20.0)
    tgt = 1.5 * (REF @ Rz.T) + np.array([2.0, 2.0, 2.0])
    m4 = solve_fit(REF, tgt, "UNIFORM")
    assert m4.shape == (4, 4)
    assert np.allclose(_apply4(m4, REF), tgt, atol=1e-6)


def test_solve_fit_keep_ignores_scale():
    # tgt is scaled 2x; KEEP (rigid) must NOT absorb the scale, so the
    # reconstruction will differ from tgt but the rotation stays orthonormal.
    Rz = _rot_z(10.0)
    tgt = 2.0 * (REF @ Rz.T)
    m4 = solve_fit(REF, tgt, "KEEP")
    linear = m4[:3, :3]
    # columns are unit length (no scale baked in)
    norms = np.linalg.norm(linear, axis=0)
    assert np.allclose(norms, 1.0, atol=1e-6)


def test_solve_fit_stretch_matches_affine():
    a = np.diag([2.0, 0.5, 1.0])
    tgt = REF @ a.T
    m4 = solve_fit(REF, tgt, "STRETCH")
    assert np.allclose(_apply4(m4, REF), tgt, atol=1e-6)


def test_solve_fit_rejects_bad_method():
    with pytest.raises(ValueError):
        solve_fit(REF, REF, "NOPE")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_alignment_fit.py -v`
Expected: FAIL — `ImportError: cannot import name 'affine_fit'`.

- [ ] **Step 3: Write minimal implementation**

Append to `utils/alignment_fit.py`:

```python
def affine_fit(ref: np.ndarray, tgt: np.ndarray) -> np.ndarray:
    """General affine transform (rotation + translation + non-uniform scale +
    shear), least squares. Returns a 4x4 homogeneous matrix mapping ref -> tgt.
    Requires >= 4 non-coplanar correspondences for a unique solution.
    """
    ref = np.asarray(ref, dtype=np.float64)
    tgt = np.asarray(tgt, dtype=np.float64)
    n = ref.shape[0]
    homog = np.hstack([ref, np.ones((n, 1))])          # (N, 4)
    sol, *_ = np.linalg.lstsq(homog, tgt, rcond=None)  # (4, 3): homog @ sol = tgt
    m4 = np.eye(4)
    m4[:3, :3] = sol[:3, :].T
    m4[:3, 3] = sol[3, :]
    return m4


def _compose4(r: np.ndarray, t: np.ndarray, s: float = 1.0) -> np.ndarray:
    m4 = np.eye(4)
    m4[:3, :3] = s * r
    m4[:3, 3] = t
    return m4


def solve_fit(ref: np.ndarray, tgt: np.ndarray, method: str = "UNIFORM") -> np.ndarray:
    """Dispatch to a solver by scale mode, returning a 4x4 homogeneous matrix
    that maps ref -> tgt.

    method:
        "KEEP"    -> rigid (Kabsch), preserves scale.
        "UNIFORM" -> similarity (Umeyama), rotation + uniform scale.
        "STRETCH" -> affine, allows non-uniform scale + shear.
    """
    if method == "KEEP":
        r, t = kabsch(ref, tgt)
        return _compose4(r, t, 1.0)
    if method == "UNIFORM":
        r, t, s = umeyama(ref, tgt)
        return _compose4(r, t, s)
    if method == "STRETCH":
        return affine_fit(ref, tgt)
    raise ValueError(f"Unknown fit method: {method!r}")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_alignment_fit.py -v`
Expected: PASS (10 passed).

- [ ] **Step 5: Commit**

```bash
git add utils/alignment_fit.py tests/test_alignment_fit.py
git commit -m "feat(alignment_fit): add affine fit + solve_fit dispatcher with tests"
```

---

### Task 4: Add `exclude=` blocklist to the raycast helper

**Files:**
- Modify: `utils/picking.py:41-73` (`raycast_from_mouse`)

- [ ] **Step 1: Replace `raycast_from_mouse` with an exclude-aware version**

In `utils/picking.py`, replace the existing `raycast_from_mouse` function body (lines 41-73) with:

```python
def raycast_from_mouse(context, mouse_coord, *, restrict_to=None, exclude=None,
                       max_iterations: int = MAX_RAYCAST_ITERATIONS):
    """Raycast from mouse position. If `restrict_to` is provided (an iterable
    of objects), the ray pierces through anything else. If `exclude` is provided
    (an iterable of objects), the ray pierces through those objects. The ray
    repeats until it hits a permitted object or runs out of iterations.

    Returns `(result, location, normal, face_index, obj, matrix)`. On miss,
    returns `(False, None, None, None, None, None)`.
    """
    region = context.region
    rv3d = context.space_data.region_3d
    if rv3d is None:
        return (False, None, None, None, None, None)

    view_vector = region_2d_to_vector_3d(region, rv3d, mouse_coord)
    ray_origin = region_2d_to_origin_3d(region, rv3d, mouse_coord)
    depsgraph = context.evaluated_depsgraph_get()
    allowed = set(restrict_to) if restrict_to is not None else None
    blocked = set(exclude) if exclude is not None else None
    view_vec_norm = view_vector.normalized()

    current_origin = ray_origin
    for _ in range(max_iterations):
        result, location, normal, face_index, obj, matrix = context.scene.ray_cast(
            depsgraph, current_origin, view_vector)
        if not result:
            break
        permitted = (allowed is None or (obj is not None and obj in allowed))
        if blocked is not None and obj is not None and obj in blocked:
            permitted = False
        if permitted:
            return (True, location, normal, face_index, obj, matrix)
        if location is None:
            break
        current_origin = location + view_vec_norm * RAYCAST_OFFSET_DISTANCE

    return (False, None, None, None, None, None)
```

- [ ] **Step 2: Smoke-check existing callers still import cleanly (blender-mcp)**

Use the `blender-mcp` skill to run, in the addon's running Blender:

```python
import importlib
from InteractionOps.utils import picking
importlib.reload(picking)
print("raycast_from_mouse OK", picking.raycast_from_mouse.__doc__ is not None)
```

Expected: prints `raycast_from_mouse OK True`, no exception. (Existing callers pass only `restrict_to`/positional args, so the new keyword-only `exclude` is backward compatible.)

- [ ] **Step 3: Commit**

```bash
git add utils/picking.py
git commit -m "feat(picking): add exclude blocklist to raycast_from_mouse"
```

---

### Task 5: Scaffold the operator + minimal modal (invoke, HUD/Help, exit)

**Files:**
- Create: `operators/object_aligner.py`
- Modify: `__init__.py`

- [ ] **Step 1: Create the operator file**

Create `operators/object_aligner.py`:

```python
import bpy
import numpy as np
from mathutils import Matrix, Vector

from ..ui.draw import safe_handler_add, safe_handler_remove
from ..ui.draw import primitives as iops_draw
from ..ui.draw import draw_scope
from ..ui.draw.theme import Role
from ..ui.hud import (
    HUDOverlay, HelpOverlay, HUDSection, HUDItem,
    HUDParam, ItemState, capture_event,
)
from ..utils.picking import raycast_from_mouse
from ..utils.alignment_fit import solve_fit


# --- State enums ----------------------------------------------------------

MODE_PICK_REF = "PICK_REF"
MODE_STAMP    = "STAMP"

CLONE_DUP  = "DUPLICATE"
CLONE_INST = "INSTANCE"
CLONE_CYCLE = (CLONE_DUP, CLONE_INST)

SCALE_KEEP    = "KEEP"
SCALE_UNIFORM = "UNIFORM"
SCALE_STRETCH = "STRETCH"
SCALE_CYCLE   = (SCALE_UNIFORM, SCALE_KEEP, SCALE_STRETCH)
SCALE_LABELS  = {SCALE_KEEP: "Keep", SCALE_UNIFORM: "Uniform", SCALE_STRETCH: "Stretch"}

FIT_GEOMETRY = "geometry"
FIT_MATRIX   = "matrix"


def _cycle(value, options):
    i = options.index(value) if value in options else 0
    return options[(i + 1) % len(options)]


# --- HUD / Help builders ---------------------------------------------------

def _build_hud(context, op):
    hud = HUDOverlay("object_aligner")
    hud.title = "Object Aligner"
    hud.bind_region(context.region)
    hud.add_param(HUDParam("Mode", lambda: "Pick reference" if op.mode == MODE_PICK_REF else "Stamp"))
    hud.add_param(HUDParam("Reference", lambda: op.ref_name or "—",
                           visible_getter=lambda: bool(op.ref_name)))
    hud.add_param(HUDParam("Clone", lambda: op.clone_mode))
    hud.add_param(HUDParam("Scale", lambda: SCALE_LABELS.get(op.scale_mode, op.scale_mode)))
    hud.add_param(HUDParam("Fit", lambda: op.last_fit or "—",
                           visible_getter=lambda: bool(op.last_fit)))
    hud.add_param(HUDParam("Stamped", lambda: op.stamped_count, kind="int"))
    return hud


def _build_help(context):
    helpo = HelpOverlay("object_aligner")
    helpo.add_section(HUDSection("Object Aligner", [
        HUDItem("Pick reference / target", "LMB",          ItemState.ON, default_state=ItemState.OFF, always_show=True),
        HUDItem("Re-pick reference",       "R",            ItemState.ON, default_state=ItemState.OFF, always_show=True),
        HUDItem("Clone type (Duplicate/Instance)", "D",    ItemState.ON, default_state=ItemState.OFF, always_show=True),
        HUDItem("Scale (Uniform/Keep/Stretch)",    "S",    ItemState.ON, default_state=ItemState.OFF, always_show=True),
        HUDItem("Apply",                   "Enter / Space / RMB", ItemState.ON, default_state=ItemState.OFF, always_show=True),
        HUDItem("Cancel",                  "Esc",          ItemState.ON, default_state=ItemState.OFF, always_show=True),
        HUDItem("Help / HUD",              "H",            ItemState.ON, default_state=ItemState.OFF, always_show=True),
    ]))
    helpo.bind_region(context.region)
    return helpo


def _draw_callback(op, context):
    helpo = getattr(op, "_help", None)
    hud = getattr(op, "_hud", None)
    last_event = getattr(op, "_last_event", None)
    if helpo is not None:
        helpo.draw(context, last_event)
    if hud is not None:
        hud.draw(context, last_event)


# --- Operator -------------------------------------------------------------

class IOPS_OT_Object_Aligner(bpy.types.Operator):
    """Stamp the selected rig onto raycast-picked objects, preserving the
    transform relative to a picked reference (topology-aware)."""

    bl_idname = "iops.object_aligner"
    bl_label = "OBJECT: Object Aligner"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return (
            context.mode == "OBJECT"
            and context.area is not None
            and context.area.type == "VIEW_3D"
        )

    def invoke(self, context, event):
        sel = list(context.selected_objects)
        if not sel:
            self.report({"WARNING"}, "Select the rig objects to transfer")
            return {"CANCELLED"}

        self.source_objs = sel
        self.source_set = set(sel)
        self.mode = MODE_PICK_REF
        self.clone_mode = CLONE_DUP
        self.scale_mode = SCALE_UNIFORM
        self.ref_obj = None
        self.ref_name = ""
        self.ref_world_np = None        # cached Nx3 reference verts (world)
        self.hover_obj = None
        self.last_fit = ""
        self.stamped_count = 0
        self.stamped_objs = []          # everything created this session (for cancel)
        self.stamped_targets = []       # picked target objects (for highlight)
        self.created_collections = []   # sub-collections created this session (for cancel)
        self._last_event = None

        self._hud = _build_hud(context, self)
        self._help = _build_help(context)
        self._handle = safe_handler_add(
            bpy.types.SpaceView3D, _draw_callback, (self, context),
            "WINDOW", "POST_PIXEL", tick=True,
        )
        self._handle_3d = None
        # POST_VIEW handler (3D preview) added in Task 6.
        context.window_manager.modal_handler_add(self)
        context.area.tag_redraw()
        return {"RUNNING_MODAL"}

    def _finish(self, context):
        if getattr(self, "_handle", None) is not None:
            safe_handler_remove(self._handle, bpy.types.SpaceView3D, "WINDOW")
            self._handle = None
        if getattr(self, "_handle_3d", None) is not None:
            safe_handler_remove(self._handle_3d, bpy.types.SpaceView3D, "WINDOW")
            self._handle_3d = None
        if context.area is not None:
            context.area.tag_redraw()

    def modal(self, context, event):
        context.area.tag_redraw()
        self._last_event = capture_event(event, getattr(self, "_last_event", None))

        # HUD/Help drag + toggle handling (verified pattern from
        # object_radial_array.py:1262-1275 — the `handle_*_toggle` module
        # helpers have a different arity and must NOT be called as (op, event)).
        try:
            theme_prefs = context.preferences.addons["InteractionOps"].preferences.iops_theme
        except (KeyError, AttributeError):
            theme_prefs = None
        if theme_prefs is not None:
            for ov in (self._help, self._hud):
                if ov is None:
                    continue
                if ov.handle_drag_event(context, event, theme_prefs):
                    return {"RUNNING_MODAL"}
            if self._help.handle_toggle_event(event, theme_prefs):
                return {"RUNNING_MODAL"}
            if self._hud.handle_param_toggle_event(event, theme_prefs):
                return {"RUNNING_MODAL"}

        if event.type in {"ESC"} and event.value == "PRESS":
            return self._cancel(context)
        if event.type in {"RET", "NUMPAD_ENTER", "SPACE", "RIGHTMOUSE"} and event.value == "PRESS":
            self._finish(context)
            self.report({"INFO"}, f"Aligner: stamped {self.stamped_count}")
            return {"FINISHED"}

        return {"PASS_THROUGH"}

    def _cancel(self, context):
        self._finish(context)
        return {"CANCELLED"}
```

- [ ] **Step 2: Register in `__init__.py`**

In `__init__.py`, after line 180 (`from .operators.object_radial_array import IOPS_OT_Object_Radial_Array`), add:

```python
from .operators.object_aligner import IOPS_OT_Object_Aligner
```

In the classes tuple, after `IOPS_OT_Object_Radial_Array,` (line 388), add:

```python
    IOPS_OT_Object_Aligner,
```

- [ ] **Step 3: Smoke-check (blender-mcp)**

Reload the addon and run the operator on a scene with at least one selected object, then immediately cancel via the API path is not possible (modal needs events), so just verify registration + invoke guard:

```python
import bpy
# With nothing selected -> CANCELLED + warning.
bpy.ops.object.select_all(action='DESELECT')
res = bpy.ops.iops.object_aligner('INVOKE_DEFAULT')
print("no-sel result:", res)   # expect {'CANCELLED'}
```

Expected: prints `no-sel result: {'CANCELLED'}` and the operator class is found (no `RuntimeError: Operator iops.object_aligner not found`). If a 3D viewport context is required, run from the viewport via the MCP skill's operator-run helper instead.

- [ ] **Step 4: Commit**

```bash
git add operators/object_aligner.py __init__.py
git commit -m "feat(object_aligner): scaffold modal operator with HUD/Help"
```

---

### Task 6: Reference picking + reference highlight (fill only)

**Files:**
- Modify: `operators/object_aligner.py`

- [ ] **Step 1: Add mouse coord + mesh-geom helpers and a POST_VIEW draw**

In `operators/object_aligner.py`, add these module-level helpers (after `_cycle`):

```python
def _mouse_coord(event):
    return (event.mouse_region_x, event.mouse_region_y)


def _mesh_tris_world(obj):
    """World-space triangle vertices for an object's mesh, or [] if not a mesh.
    Used to fill-highlight a picked object's polygons (no edges)."""
    if obj is None or obj.type != "MESH" or obj.data is None:
        return []
    mesh = obj.data
    if not mesh.loop_triangles:
        try:
            mesh.calc_loop_triangles()
        except RuntimeError:
            return []
    mw = obj.matrix_world
    verts = [mw @ v.co for v in mesh.vertices]
    loops = mesh.loops
    out = []
    for lt in mesh.loop_triangles:
        out.append(verts[loops[lt.loops[0]].vertex_index])
        out.append(verts[loops[lt.loops[1]].vertex_index])
        out.append(verts[loops[lt.loops[2]].vertex_index])
    return out


def _verts_world_np(obj):
    """Nx3 NumPy array of an object's mesh vertices in world space."""
    mesh = obj.data
    mw = obj.matrix_world
    co = np.empty(len(mesh.vertices) * 3, dtype=np.float64)
    mesh.vertices.foreach_get("co", co)
    co = co.reshape(-1, 3)
    mat = np.array(mw)                      # 4x4
    homog = np.hstack([co, np.ones((co.shape[0], 1))])
    world = homog @ mat.T
    return world[:, :3]


def _draw_preview_3d(op, context):
    """POST_VIEW: highlight reference + picked targets (fill only), and the
    rig ghost at the hovered target (added in Task 7)."""
    # Reference highlight — active surface fill, polygons only.
    if op.ref_obj is not None:
        try:
            tris = _mesh_tris_world(op.ref_obj)
        except ReferenceError:
            tris = []
        if tris:
            with draw_scope(blend="ALPHA", depth="LESS_EQUAL",
                            face_culling="NONE", depth_mask=False):
                iops_draw.tris(tris, role=Role.GHOST_ACTIVE, context=context)
    # Picked targets — result-preview surface fill, polygons only.
    for tgt in op.stamped_targets:
        try:
            tris = _mesh_tris_world(tgt)
        except ReferenceError:
            continue
        if tris:
            with draw_scope(blend="ALPHA", depth="LESS_EQUAL",
                            face_culling="NONE", depth_mask=False):
                iops_draw.tris(tris, role=Role.GHOST_PREVIEW, context=context)
```

- [ ] **Step 2: Register the POST_VIEW handler in `invoke`**

In `invoke`, replace the comment line `# POST_VIEW handler (3D preview) added in Task 6.` with:

```python
        self._handle_3d = safe_handler_add(
            bpy.types.SpaceView3D, _draw_preview_3d, (self, context),
            "WINDOW", "POST_VIEW", tick=False,
        )
```

`_finish` (written in Task 5) already removes both `self._handle` and `self._handle_3d`, so no change to `_finish` is needed here.

- [ ] **Step 3: Handle the reference-pick click in `modal`**

In `modal`, replace the final `return {"PASS_THROUGH"}` with:

```python
        if event.type == "MOUSEMOVE":
            self._update_hover(context, event)
            return {"RUNNING_MODAL"}

        if event.type == "LEFTMOUSE" and event.value == "PRESS":
            return self._on_click(context, event)

        return {"PASS_THROUGH"}
```

Add these methods to the class:

```python
    def _pick(self, context, event):
        """Raycast under the mouse, excluding the rig (and reference when
        stamping). Returns the ORIGINAL hit object or None.

        `scene.ray_cast` yields the depsgraph-evaluated object; we return
        `obj.original` so (a) duplication copies the base datablock rather than
        an evaluated/flattened mesh, (b) geometry-fit reads base-mesh verts, and
        (c) membership in the exclude set (which holds originals) matches."""
        exclude = set(self.source_set)
        if self.mode == MODE_STAMP and self.ref_obj is not None:
            exclude.add(self.ref_obj)
        hit, _loc, _n, _fi, obj, _mx = raycast_from_mouse(
            context, _mouse_coord(event), exclude=exclude)
        return obj.original if (hit and obj is not None) else None

    def _update_hover(self, context, event):
        self.hover_obj = self._pick(context, event)

    def _on_click(self, context, event):
        obj = self._pick(context, event)
        if obj is None:
            return {"RUNNING_MODAL"}
        if self.mode == MODE_PICK_REF:
            self.ref_obj = obj
            self.ref_name = obj.name
            self.ref_world_np = _verts_world_np(obj) if obj.type == "MESH" else None
            self.mode = MODE_STAMP
            return {"RUNNING_MODAL"}
        # MODE_STAMP handled in Task 7.
        return {"RUNNING_MODAL"}
```

- [ ] **Step 4: Smoke-check (blender-mcp)**

Load the addon, make a scene with a selected rig object and a separate reference cube. Invoke the operator from the viewport (via the MCP operator-run helper), move the mouse over the reference cube, click. Verify:

```python
# After picking, inspect the running operator is not trivially testable from
# the API; instead verify the helpers in isolation:
import numpy as np
from InteractionOps.operators import object_aligner as oa
import bpy
cube = bpy.data.objects["Cube"]
tris = oa._mesh_tris_world(cube)
print("tris count:", len(tris))                 # 12 tris * 3 = 36 verts for a cube
arr = oa._verts_world_np(cube)
print("verts np shape:", arr.shape)             # (8, 3)
```

Expected: `tris count: 36`, `verts np shape: (8, 3)`. Visually, picking a reference in the viewport tints it with the theme's active ghost colour (polygons only).

- [ ] **Step 5: Commit**

```bash
git add operators/object_aligner.py
git commit -m "feat(object_aligner): reference picking + fill-only highlight"
```

---

### Task 7: Compute the fit, stamp duplicates, collection + clone type

**Files:**
- Modify: `operators/object_aligner.py`

- [ ] **Step 1: Add the fit-transform + stamping helpers**

In `operators/object_aligner.py`, add these module-level helpers:

```python
def _np_to_matrix(m4):
    """Convert a 4x4 NumPy array to a mathutils.Matrix (row-major)."""
    return Matrix([[float(m4[i][j]) for j in range(4)] for i in range(4)])


def _compute_fit(op, target):
    """Return (T_matrix, fit_kind). geometry fit when topology matches the
    reference; matrix fit otherwise."""
    ref = op.ref_obj
    same_topo = (
        op.ref_world_np is not None
        and target.type == "MESH"
        and len(target.data.vertices) == op.ref_world_np.shape[0]
    )
    if same_topo:
        tgt_np = _verts_world_np(target)
        t_np = solve_fit(op.ref_world_np, tgt_np, op.scale_mode)
        return _np_to_matrix(t_np), FIT_GEOMETRY
    # Matrix fallback: T = M_target @ M_ref^-1
    try:
        t = target.matrix_world @ ref.matrix_world.inverted()
    except (ReferenceError, ValueError):
        t = Matrix.Identity(4)
    return t, FIT_MATRIX


def _target_subcollection(op, source_obj, target):
    """Sub-collection inside the source object's collection, named
    `<source_collection>_<target_name>`. Created on first use, reused after.
    Newly created collections are tracked on `op.created_collections` so cancel
    can clean up empties."""
    parent = source_obj.users_collection[0] if source_obj.users_collection else bpy.context.scene.collection
    name = f"{parent.name}_{target.name}"
    sub = parent.children.get(name)
    if sub is None:
        sub = bpy.data.collections.get(name)
        if sub is None:
            sub = bpy.data.collections.new(name)
            op.created_collections.append(sub)
        if name not in parent.children:
            parent.children.link(sub)
    return sub


def _duplicate_obj(src, world_matrix, collection, linked):
    """Copy one object (+ its child hierarchy, preserving matrix_local) into
    `collection`. Root placed at `world_matrix`. Returns the list of new objs."""
    new_root = src.copy()
    if not linked and src.type == "MESH" and src.data and src.data.library is None:
        new_root.data = src.data.copy()
    new_root.parent = None
    collection.objects.link(new_root)
    new_root.matrix_world = world_matrix
    created = [new_root]

    def _dup_children(obj, new_parent):
        for child in obj.children:
            new_ob = child.copy()
            if not linked and child.type == "MESH" and child.data and child.data.library is None:
                new_ob.data = child.data.copy()
            new_ob.parent = new_parent
            new_ob.matrix_local = child.matrix_local.copy()
            collection.objects.link(new_ob)
            created.append(new_ob)
            _dup_children(child, new_ob)

    _dup_children(src, new_root)
    return created
```

- [ ] **Step 2: Implement the stamp on target click**

In `_on_click`, replace the line `# MODE_STAMP handled in Task 7.` and the following `return {"RUNNING_MODAL"}` with:

```python
        # MODE_STAMP: stamp the rig onto the picked target. Only iterate
        # top-level roots (objects whose parent is not itself selected) — child
        # subtrees are duplicated recursively by _duplicate_obj, so iterating
        # every selected object would double-stamp parented rigs.
        t_matrix, fit_kind = _compute_fit(self, obj)
        self.last_fit = fit_kind
        linked = (self.clone_mode == CLONE_INST)
        roots = [o for o in self.source_objs if o.parent not in self.source_set]
        for src in roots:
            sub = _target_subcollection(self, src, obj)
            world_matrix = t_matrix @ src.matrix_world
            created = _duplicate_obj(src, world_matrix, sub, linked)
            self.stamped_objs.extend(created)
        self.stamped_targets.append(obj)
        self.stamped_count += 1
        return {"RUNNING_MODAL"}
```

- [ ] **Step 3: Implement cancel cleanup**

Replace `_cancel` with:

```python
    def _cancel(self, context):
        for ob in reversed(self.stamped_objs):
            try:
                bpy.data.objects.remove(ob, do_unlink=True)
            except (ReferenceError, RuntimeError):
                pass
        self.stamped_objs = []
        # Remove sub-collections we created this session if they are now empty.
        for coll in self.created_collections:
            try:
                if not coll.objects and not coll.children:
                    bpy.data.collections.remove(coll)
            except (ReferenceError, RuntimeError):
                pass
        self.created_collections = []
        self._finish(context)
        self.report({"INFO"}, "Aligner: cancelled")
        return {"CANCELLED"}
```

- [ ] **Step 4: Smoke-check (blender-mcp)**

Build a scene: a "rig" object (e.g. a small cube `Rig`) selected; a reference object `Ref` (a cube) and a baked-transform target `Tgt` (a cube rotated 45° then Object > Apply > Rotation, so its matrix_world is identity but verts are rotated). Run the operator: pick `Ref`, then click `Tgt`. Inspect:

```python
import bpy, math
from mathutils import Vector
# Verify a stamped copy exists in the expected sub-collection and is rotated
# to match the baked target (geometry fit), not the identity matrix fit.
ref = bpy.data.objects["Ref"]
tgt = bpy.data.objects["Tgt"]
rig = bpy.data.objects["Rig"]
# After running the operator interactively and confirming:
subs = [c.name for c in rig.users_collection[0].children]
print("subcollections:", subs)       # expect one like "<col>_Tgt"
```

Expected: a sub-collection named `<rig_collection>_Tgt` exists, contains a copy of `Rig`, and the copy's orientation follows the baked target (visually aligned to the rotated `Tgt`, not axis-aligned). Switching clone type to Instance (`D`) and stamping shares mesh data (`copy.data is rig.data`).

- [ ] **Step 5: Commit**

```bash
git add operators/object_aligner.py
git commit -m "feat(object_aligner): topology-aware fit + stamp with collections"
```

---

### Task 8: Key handling — clone type (D), scale (S), re-pick reference (R)

**Files:**
- Modify: `operators/object_aligner.py`

- [ ] **Step 1: Add key handlers in `modal`**

In `modal`, insert before the `if event.type == "MOUSEMOVE":` block:

```python
        if event.value == "PRESS":
            if event.type == "D":
                self.clone_mode = _cycle(self.clone_mode, CLONE_CYCLE)
                return {"RUNNING_MODAL"}
            if event.type == "S":
                self.scale_mode = _cycle(self.scale_mode, SCALE_CYCLE)
                return {"RUNNING_MODAL"}
            if event.type == "R":
                self.mode = MODE_PICK_REF
                return {"RUNNING_MODAL"}
```

- [ ] **Step 2: Smoke-check (blender-mcp)**

Run the operator interactively. Press `D` and confirm the HUD `Clone` row toggles `DUPLICATE` ↔ `INSTANCE`. Press `S` and confirm `Scale` cycles `Uniform → Keep → Stretch → Uniform`. After picking a reference and stamping, press `R` and confirm the HUD `Mode` row returns to `Pick reference` and the next click re-assigns the reference (HUD `Reference` name changes).

Expected: HUD rows update live; `R` returns to pick-reference mode without losing already-stamped objects.

- [ ] **Step 3: Commit**

```bash
git add operators/object_aligner.py
git commit -m "feat(object_aligner): D/S/R key handling for clone, scale, re-pick"
```

---

### Task 9: Rig ghost preview at hovered target (fill + edges)

**Files:**
- Modify: `operators/object_aligner.py`

- [ ] **Step 1: Add ghost-edge geometry helper**

In `operators/object_aligner.py`, add:

```python
def _mesh_edges_world(obj, world_matrix):
    """Flat list of world-space edge endpoints for `obj.data` transformed by
    `world_matrix`. [] if not a mesh."""
    if obj is None or obj.type != "MESH" or obj.data is None:
        return []
    mesh = obj.data
    verts = [world_matrix @ v.co for v in mesh.vertices]
    out = []
    for e in mesh.edges:
        out.append(verts[e.vertices[0]])
        out.append(verts[e.vertices[1]])
    return out


def _mesh_tris_world_at(obj, world_matrix):
    """Like _mesh_tris_world but with an explicit placement matrix."""
    if obj is None or obj.type != "MESH" or obj.data is None:
        return []
    mesh = obj.data
    if not mesh.loop_triangles:
        try:
            mesh.calc_loop_triangles()
        except RuntimeError:
            return []
    verts = [world_matrix @ v.co for v in mesh.vertices]
    loops = mesh.loops
    out = []
    for lt in mesh.loop_triangles:
        out.append(verts[loops[lt.loops[0]].vertex_index])
        out.append(verts[loops[lt.loops[1]].vertex_index])
        out.append(verts[loops[lt.loops[2]].vertex_index])
    return out
```

- [ ] **Step 2: Draw the ghost in `_draw_preview_3d`**

At the end of `_draw_preview_3d`, append:

```python
    # Rig ghost at the hovered target (fill + edges).
    if op.mode == MODE_STAMP and op.hover_obj is not None and op.ref_obj is not None \
            and op.hover_obj not in op.source_set and op.hover_obj is not op.ref_obj:
        try:
            t_matrix, fit_kind = _compute_fit(op, op.hover_obj)
        except (ReferenceError, ValueError):
            t_matrix, fit_kind = None, ""
        if t_matrix is not None:
            op.last_fit = fit_kind
            ghost_tris = []
            ghost_edges = []
            for src in op.source_objs:
                try:
                    placement = t_matrix @ src.matrix_world
                except (ReferenceError, ValueError):
                    continue
                ghost_tris.extend(_mesh_tris_world_at(src, placement))
                ghost_edges.extend(_mesh_edges_world(src, placement))
            if ghost_tris:
                with draw_scope(blend="NONE", depth="LESS_EQUAL",
                                face_culling="BACK", depth_mask=True,
                                color_mask=(False, False, False, False)):
                    iops_draw.tris(ghost_tris, role=Role.GHOST_DEFAULT, context=context)
                with draw_scope(blend="ALPHA", depth="EQUAL",
                                face_culling="BACK", depth_mask=False):
                    iops_draw.tris(ghost_tris, role=Role.GHOST_DEFAULT, context=context)
            if ghost_edges:
                with draw_scope(blend="ALPHA", depth="LESS_EQUAL"):
                    iops_draw.edges_3d(ghost_edges, role=Role.GHOST_EDGE, context=context)
```

- [ ] **Step 3: Smoke-check (blender-mcp)**

Run interactively: pick a reference, then hover (without clicking) over a target. A translucent ghost of the rig appears at the position/orientation it would be stamped, with `GHOST_DEFAULT` fill and `GHOST_EDGE` wires. The HUD `Fit` row shows `geometry` for same-topology targets and `matrix` for different-topology targets. Clicking still stamps as in Task 7.

Expected: live ghost tracks the hovered target; no ghost when hovering the rig itself or the reference.

- [ ] **Step 4: Commit**

```bash
git add operators/object_aligner.py
git commit -m "feat(object_aligner): live rig ghost preview at hovered target"
```

---

### Task 10: Pie-menu entry + final verification

**Files:**
- Modify: `ui/iops_pie_menu.py:44` (`IOPS_MT_Pie_Menu`)

- [ ] **Step 1: Add the menu entry**

In `ui/iops_pie_menu.py`, in the `IOPS_MT_Pie_Menu` class, immediately after line 44
(`col.operator("iops.object_replace", text="Object Replace")`) and before the
`iops.object_radial_array` line, add:

```python
        col.operator("iops.object_aligner", text="Object Aligner")
```

- [ ] **Step 2: Run the full pytest suite**

Run: `python -m pytest tests/test_alignment_fit.py -v`
Expected: PASS (10 passed) — confirms the solver is intact after all edits.

- [ ] **Step 3: End-to-end smoke-check (blender-mcp)**

Scene: one rig collection with a `Rig` object selected; a `Ref` cube; three target cubes — `T_plain` (untouched), `T_baked` (rotated+scaled then Apply Transform), `T_other` (a cylinder, different topology). Run the operator from the pie menu:
- Pick `Ref`.
- Stamp `T_plain` → copy lands matching its transform (HUD `Fit: geometry`).
- Stamp `T_baked` → copy follows the baked orientation/scale (HUD `Fit: geometry`).
- Stamp `T_other` → copy placed via matrix fallback (HUD `Fit: matrix`).
- Press `D` to Instance, stamp again → shared mesh data.
- Press `Esc` → all stamped objects this session are removed; the scene returns to its pre-run state.
- Re-run, stamp, press `Enter` → objects persist, sub-collections `<rig_col>_<target>` exist.

```python
import bpy
print([c.name for c in bpy.data.collections])   # inspect created sub-collections
```

Expected: behaviour above holds; Esc fully reverts the session; Enter keeps results.

- [ ] **Step 4: Commit**

```bash
git add ui/iops_pie_menu.py
git commit -m "feat(object_aligner): add pie-menu entry"
```

---

## Self-Review Notes

- **Spec coverage:** core math (Tasks 1-3), matrix/geometry auto-fit (Task 7 `_compute_fit`), interactive flow incl. re-pick (Tasks 5,6,8), clone type D / scale S (Task 8), sub-collection naming (Task 7 `_target_subcollection`), source exclusion in raycast (Task 4 + Task 6 `_pick`), reference fill-only highlight + target fill-only highlight (Task 6), rig ghost fill+edges (Task 9), HUD/Help (Task 5), cancel reverts session (Task 7 `_cancel`), registration + pie menu (Tasks 5,10). All spec sections map to a task.
- **Out of scope (per spec):** REPLACE clone type, Horn/RANSAC/3-point solve methods, redo-panel stored matrices — intentionally absent.
- **Type/name consistency:** `solve_fit(ref, tgt, method)` defined in Task 3 is called with `op.scale_mode` (values `KEEP`/`UNIFORM`/`STRETCH` from `SCALE_CYCLE`) in Task 7 — matches. `_compute_fit` returns `(Matrix, fit_kind)` used consistently in Tasks 7 and 9. `_verts_world_np` (Task 6) reused by `_compute_fit` (Task 7).
- **Handler signatures verified** against `operators/object_radial_array.py:1239-1247` / `2013-2018` and `ui/draw/handlers.py`: `safe_handler_add(bpy.types.SpaceView3D, callback, (self, context), "WINDOW", draw_type, tick=...)` returns a handle; `safe_handler_remove(handle, bpy.types.SpaceView3D, "WINDOW")`. The plan uses exactly this pattern.
- **Primitive signatures verified**: `iops_draw.tris(coords, *, role=, context=)`, `edges_3d(coord_pairs, *, role=, context=)`, `draw_scope(blend=, depth=, face_culling=, depth_mask=, color_mask=)` — all match `ui/draw/primitives.py` and `ui/draw/state.py`.
