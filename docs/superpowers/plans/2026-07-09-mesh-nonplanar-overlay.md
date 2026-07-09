# Non-Planar Faces Overlay Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Sticky edit-mesh overlay that highlights non-planar faces with deviation-scaled alpha in real time; highlight drops per-face as faces become planar.

**Architecture:** Pure-math planarity module in `utils/` (pytest-tested, no bpy). Non-modal toggle operator owns module-level state: one POST_VIEW handler drawing a cached `SMOOTH_COLOR` GPU batch, one POST_PIXEL handler drawing a `Non-Planar: N` label, and `bpy.app.handlers` hooks that only set a dirty flag. Rebuild is lazy inside the draw callback.

**Tech Stack:** Blender 5.1 Python addon (`bpy`, `bmesh`, `gpu`, `mathutils`), existing iOps unified draw system (`ui/draw`: `safe_handler_add`, `draw_scope`, `get_theme`, `Role`), `ui/hud/text` for the label, pytest for pure math.

**Spec:** `docs/superpowers/specs/2026-07-09-mesh-nonplanar-overlay-design.md`

## Global Constraints

- Addon module name is `InteractionOps`; prefs are read via `context.preferences.addons["InteractionOps"].preferences`.
- Repo is public — commit messages must never mention CCP or internal project names.
- Commit style: conventional commits (`feat(...)`, `docs(...)`, `test(...)`) ending with `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.
- `unregister()` cleanup must touch ONLY this addon's handlers (established iOps rule).
- pytest runs from `tests/` dir: `cd tests && python -m pytest <file> -v` (rootdir must stay at `tests/`, see `tests/pytest.ini`).
- Blender for headless runs: `V:\SteamLibrary\steamapps\common\Blender\blender.exe` (5.1, Steam). Do NOT pass `--factory-startup` (the addon must load from userprefs).
- Threshold pref: `nonplanar_angle`, degrees, default `0.5`.
- Alpha ramp constants: `ALPHA_MIN = 0.15`, `ALPHA_MAX = 0.6`, `FULL_ANGLE_DEG = 15.0` (fixed, not prefs).

---

### Task 1: Pure planarity math (`utils/planarity.py`)

**Files:**
- Create: `utils/planarity.py`
- Test: `tests/test_planarity.py`

**Interfaces:**
- Consumes: nothing (pure Python, `math` only — NO bpy/mathutils/numpy imports; module must import outside Blender).
- Produces:
  - `face_deviation_deg(coords: Sequence[tuple[float, float, float]]) -> float` — max angular deviation (degrees) of any corner plane from the face's Newell best-fit normal. Returns `0.0` for triangles and degenerate faces.
  - `deviation_alpha(dev_deg: float, threshold_deg: float) -> float` — overlay fill alpha for a face, linear ramp `ALPHA_MIN`→`ALPHA_MAX` over `[threshold_deg, FULL_ANGLE_DEG]`, clamped.
  - Constants `ALPHA_MIN`, `ALPHA_MAX`, `FULL_ANGLE_DEG`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_planarity.py`:

```python
import math

import pytest

from utils.planarity import (
    face_deviation_deg,
    deviation_alpha,
    ALPHA_MIN,
    ALPHA_MAX,
    FULL_ANGLE_DEG,
)


PLANAR_QUAD = [(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)]

# Planar concave L-shape ngon (all z=0). Concave corner normals are
# anti-parallel to the face normal on a planar face — deviation must be 0.
PLANAR_CONCAVE_L = [(0, 0, 0), (2, 0, 0), (2, 1, 0), (1, 1, 0), (1, 2, 0), (0, 2, 0)]


def warped_quad(h):
    return [(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, h)]


class TestFaceDeviation:
    def test_planar_quad_is_zero(self):
        assert face_deviation_deg(PLANAR_QUAD) == pytest.approx(0.0, abs=1e-9)

    def test_triangle_is_always_zero(self):
        assert face_deviation_deg([(0, 0, 0), (1, 0, 0), (0.3, 0.9, 5.0)]) == 0.0

    def test_planar_concave_ngon_is_zero(self):
        assert face_deviation_deg(PLANAR_CONCAVE_L) == pytest.approx(0.0, abs=1e-9)

    def test_warped_quad_detected(self):
        # h=0.1 lifts one corner by 10% of the edge length — clearly
        # non-planar at sub-degree thresholds, but far from FULL_ANGLE.
        dev = face_deviation_deg(warped_quad(0.1))
        assert 2.0 < dev < 15.0

    def test_deviation_monotonic_in_warp(self):
        devs = [face_deviation_deg(warped_quad(h)) for h in (0.01, 0.05, 0.1, 0.3)]
        assert devs == sorted(devs)
        assert devs[0] > 0.0

    def test_rigid_transform_invariant(self):
        # Rotate the warped quad 90° around X and translate: deviation unchanged.
        base = warped_quad(0.2)
        moved = [(x + 5.0, -z + 2.0, y - 1.0) for (x, y, z) in base]
        assert face_deviation_deg(moved) == pytest.approx(
            face_deviation_deg(base), abs=1e-6)

    def test_collinear_corner_does_not_crash(self):
        # Middle vert of the bottom edge is collinear — its corner normal is
        # undefined and must be skipped, not crash or dominate.
        coords = [(0, 0, 0), (1, 0, 0), (2, 0, 0), (2, 1, 0), (0, 1, 0)]
        assert face_deviation_deg(coords) == pytest.approx(0.0, abs=1e-9)

    def test_fully_degenerate_face_is_zero(self):
        assert face_deviation_deg([(0, 0, 0), (0, 0, 0), (0, 0, 0), (0, 0, 0)]) == 0.0


class TestDeviationAlpha:
    def test_at_threshold_is_min(self):
        assert deviation_alpha(0.5, 0.5) == pytest.approx(ALPHA_MIN)

    def test_at_full_angle_is_max(self):
        assert deviation_alpha(FULL_ANGLE_DEG, 0.5) == pytest.approx(ALPHA_MAX)

    def test_clamped_above_full_angle(self):
        assert deviation_alpha(90.0, 0.5) == pytest.approx(ALPHA_MAX)

    def test_midpoint_between_min_max(self):
        mid = (0.5 + FULL_ANGLE_DEG) / 2.0
        expected = (ALPHA_MIN + ALPHA_MAX) / 2.0
        assert deviation_alpha(mid, 0.5) == pytest.approx(expected)

    def test_threshold_above_full_angle_returns_max(self):
        # Degenerate config (threshold >= ceiling): no ramp, just max.
        assert deviation_alpha(30.0, 20.0) == pytest.approx(ALPHA_MAX)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd D:/git/InteractionOps/tests && python -m pytest test_planarity.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'utils.planarity'`

- [ ] **Step 3: Write the implementation**

Create `utils/planarity.py`:

```python
"""Face planarity measurement. Pure Python — no bpy/mathutils/numpy imports,
unit-testable standalone.

A face's deviation is the max angle between any corner's plane (the triangle
`v_prev, v, v_next`) and the face's Newell best-fit normal. Concave corners
on a planar face produce anti-parallel corner normals, so per-corner angles
fold to `min(a, 180 - a)`.
"""
from __future__ import annotations

import math
from typing import Optional, Sequence

Vec3 = Sequence[float]

# Overlay alpha ramp: faint at the threshold, fully saturated at
# FULL_ANGLE_DEG deviation. Fixed constants (not prefs) so the visual read
# stays consistent across meshes regardless of the threshold setting.
ALPHA_MIN = 0.15
ALPHA_MAX = 0.6
FULL_ANGLE_DEG = 15.0

_EPS = 1e-12


def _sub(a: Vec3, b: Vec3):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _cross(a: Vec3, b: Vec3):
    return (a[1] * b[2] - a[2] * b[1],
            a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0])


def _dot(a: Vec3, b: Vec3) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _normalized(a: Vec3) -> Optional[tuple]:
    length = math.sqrt(_dot(a, a))
    if length < _EPS:
        return None
    return (a[0] / length, a[1] / length, a[2] / length)


def newell_normal(coords: Sequence[Vec3]) -> Optional[tuple]:
    """Unit best-fit normal of a (possibly non-planar) polygon, or None if
    the polygon is degenerate (zero area)."""
    nx = ny = nz = 0.0
    count = len(coords)
    for i in range(count):
        x0, y0, z0 = coords[i]
        x1, y1, z1 = coords[(i + 1) % count]
        nx += (y0 - y1) * (z0 + z1)
        ny += (z0 - z1) * (x0 + x1)
        nz += (x0 - x1) * (y0 + y1)
    return _normalized((nx, ny, nz))


def face_deviation_deg(coords: Sequence[Vec3]) -> float:
    """Max angular deviation (degrees) of any corner plane from the face
    plane. 0.0 for triangles and degenerate faces (never highlighted)."""
    count = len(coords)
    if count <= 3:
        return 0.0
    face_n = newell_normal(coords)
    if face_n is None:
        return 0.0
    worst = 0.0
    for i in range(count):
        v_prev = coords[i - 1]
        v = coords[i]
        v_next = coords[(i + 1) % count]
        corner_n = _normalized(_cross(_sub(v, v_prev), _sub(v_next, v)))
        if corner_n is None:
            continue  # collinear corner — no plane to compare
        cos_a = max(-1.0, min(1.0, _dot(corner_n, face_n)))
        angle = math.degrees(math.acos(cos_a))
        # Concave corners are anti-parallel on planar faces.
        angle = min(angle, 180.0 - angle)
        if angle > worst:
            worst = angle
    return worst


def deviation_alpha(dev_deg: float, threshold_deg: float) -> float:
    """Fill alpha for a non-planar face: ALPHA_MIN at the threshold,
    ramping linearly to ALPHA_MAX at FULL_ANGLE_DEG, clamped."""
    if threshold_deg >= FULL_ANGLE_DEG:
        return ALPHA_MAX
    t = (dev_deg - threshold_deg) / (FULL_ANGLE_DEG - threshold_deg)
    t = max(0.0, min(1.0, t))
    return ALPHA_MIN + (ALPHA_MAX - ALPHA_MIN) * t
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd D:/git/InteractionOps/tests && python -m pytest test_planarity.py -v`
Expected: 13 PASSED

- [ ] **Step 5: Run the whole pure-math suite (no regressions)**

Run: `cd D:/git/InteractionOps/tests && python -m pytest -v`
Expected: all PASS (pre-existing: test_alignment_fit, test_polygon_match, test_uv_info, ui tests)

- [ ] **Step 6: Commit**

```bash
git add utils/planarity.py tests/test_planarity.py
git commit -m "feat(planarity): pure-math face planarity deviation + alpha ramp"
```

---

### Task 2: Preferences plumbing (`nonplanar_angle`)

**Files:**
- Modify: `prefs/addon_preferences.py` (property near `cursor_bisect_coplanar_angle` ~line 581; `show_section_nonplanar` BoolProperty near line 194; UI section after Cursor Bisect ~line 906)
- Modify: `prefs/iops_prefs.py` (save dict, after the `"CURSOR_BISECT"` section ~line 198)
- Modify: `operators/preferences/io_addon_preferences.py` (load `match` case, after `case "CURSOR_BISECT":` ~line 220)

**Interfaces:**
- Consumes: existing `_section()` helper in `prefs/addon_preferences.py`, `safe()` helper in `get_iops_prefs()`, `safe_get()` in the loader.
- Produces: `prefs.nonplanar_angle: float` (degrees, default 0.5) — read by Task 3 via `bpy.context.preferences.addons["InteractionOps"].preferences.nonplanar_angle`.

- [ ] **Step 1: Add the property**

In `prefs/addon_preferences.py`, directly after the `cursor_bisect_snap_use_modifiers` property (~line 594), add:

```python
    # Non-Planar Faces Overlay (iops.mesh_nonplanar_overlay)
    nonplanar_angle: bpy.props.FloatProperty(
        name="Non-Planar Angle",
        description="Faces whose corners deviate from the face plane by more "
                    "than this angle (degrees) are highlighted by the "
                    "Non-Planar Faces Overlay",
        default=0.5,
        min=0.001,
        max=90.0,
        step=10,  # 0.1 degree
        precision=2,
    )
```

- [ ] **Step 2: Add the section-open BoolProperty**

In the same file, in the `show_section_*` block (after `show_section_bisect: BoolProperty(default=False)`, ~line 194), add:

```python
    show_section_nonplanar: BoolProperty(default=False)
```

- [ ] **Step 3: Add the UI section**

In the same file's `draw()`, directly after the Cursor Bisect section body (after the `row.prop(self, "cursor_bisect_coplanar_angle")` line, ~line 906), add:

```python
            # Non-Planar Faces Overlay
            body = _section(column_main, self, "show_section_nonplanar",
                            "Non-Planar Overlay", icon="MOD_TRIANGULATE")
            if body is not None:
                body.prop(self, "nonplanar_angle")
```

- [ ] **Step 4: Add the save entry**

In `prefs/iops_prefs.py`, inside the returned dict, after the `"CURSOR_BISECT": {...}` section (~line 198), add:

```python
        "NONPLANAR_OVERLAY": {
            "nonplanar_angle": safe("nonplanar_angle", 0.5),
        },
```

- [ ] **Step 5: Add the load case**

In `operators/preferences/io_addon_preferences.py`, after the full `case "CURSOR_BISECT":` block (~line 220), add:

```python
                    case "NONPLANAR_OVERLAY":
                        if isinstance(value, dict):
                            defaults = default_prefs.get("NONPLANAR_OVERLAY", {})
                            if hasattr(prefs, "nonplanar_angle"):
                                prefs.nonplanar_angle = safe_get(
                                    value, "nonplanar_angle",
                                    defaults.get("nonplanar_angle", 0.5))
```

- [ ] **Step 6: Syntax check**

Run: `python -m py_compile D:/git/InteractionOps/prefs/addon_preferences.py D:/git/InteractionOps/prefs/iops_prefs.py D:/git/InteractionOps/operators/preferences/io_addon_preferences.py`
Expected: exit 0, no output. (Full registration is verified in Task 4's headless smoke run.)

- [ ] **Step 7: Commit**

```bash
git add prefs/addon_preferences.py prefs/iops_prefs.py operators/preferences/io_addon_preferences.py
git commit -m "feat(prefs): nonplanar_angle threshold pref + save/load + UI section"
```

---

### Task 3: Overlay operator module

**Files:**
- Create: `operators/mesh_nonplanar_overlay.py`

**Interfaces:**
- Consumes:
  - `utils.planarity.face_deviation_deg(coords) -> float`, `deviation_alpha(dev, thr) -> float` (Task 1)
  - `prefs.nonplanar_angle` (Task 2)
  - `ui.draw`: `safe_handler_add(space_type, callback, args, region, draw_type)`, `safe_handler_remove(handle, space_type, region)`, `draw_scope(blend=, depth=, depth_mask=)`, `get_theme(context)`, `Role`
  - `ui.hud.text`: `draw(text, x, y, *, theme, role=, font_id=)`, `isolated(theme)` context manager (prevents the blf SHADOW leak on shared font 0)
- Produces (used by Task 4):
  - class `IOPS_OT_MeshNonPlanarOverlay` (`bl_idname = "iops.mesh_nonplanar_overlay"`)
  - `disable_overlay()` — module-level, idempotent, called from addon `unregister()`
  - `overlay_enabled() -> bool`
  - `collect_nonplanar(bm, matrix_world, threshold_deg) -> list[(BMFace, dev_deg, world_coords)]` — used by the headless smoke test

- [ ] **Step 1: Write the module**

Create `operators/mesh_nonplanar_overlay.py` with exactly this content:

```python
"""Non-Planar Faces Overlay — sticky edit-mesh mode that highlights
non-planar quads/ngons in real time.

Toggle operator, not modal: module-level state owns one POST_VIEW handler
(deviation-tinted face fills, cached GPU batch) and one POST_PIXEL handler
(`Non-Planar: N` corner label). `bpy.app.handlers` hooks only set a dirty
flag; the batch rebuilds lazily inside the draw callback, so orbit/pan
redraws cost one `batch.draw()`.
"""
import bpy
import bmesh
import gpu
from bpy.app.handlers import persistent
from gpu_extras.batch import batch_for_shader
from mathutils import Vector
from mathutils.geometry import tessellate_polygon

from ..ui.draw import (Role, draw_scope, get_theme,
                       safe_handler_add, safe_handler_remove)
from ..ui.hud import text as hud_text
from ..utils.planarity import deviation_alpha, face_deviation_deg

NORMAL_OFFSET = 0.002  # world-space push along the face normal (z-fight)
LABEL_X = 20
LABEL_Y_FROM_TOP = 60

_STATE = {
    "handle_view": None,    # POST_VIEW draw handle
    "handle_pixel": None,   # POST_PIXEL draw handle
    "batch": None,          # (shader, GPUBatch) or None
    "count": 0,             # non-planar faces at last rebuild
    "dirty": True,
    "obj_ptr": 0,           # as_pointer() of the object last built
    "threshold": None,      # threshold used at last rebuild
}


def overlay_enabled() -> bool:
    return _STATE["handle_view"] is not None


@persistent
def _mark_dirty(*_args):
    _STATE["dirty"] = True


def _app_handler_lists():
    h = bpy.app.handlers
    return (h.depsgraph_update_post, h.undo_post, h.redo_post, h.load_post)


def _threshold_deg() -> float:
    try:
        return float(bpy.context.preferences.addons["InteractionOps"]
                     .preferences.nonplanar_angle)
    except (KeyError, AttributeError):
        return 0.5


def collect_nonplanar(bm, matrix_world, threshold_deg):
    """[(face, deviation_deg, world_coords)] for visible non-planar
    quads/ngons. World space so non-uniform object scale is measured the
    way the user sees it."""
    out = []
    for f in bm.faces:
        if len(f.verts) <= 3 or f.hide:
            continue
        coords = [tuple(matrix_world @ v.co) for v in f.verts]
        dev = face_deviation_deg(coords)
        if dev > threshold_deg:
            out.append((f, dev, coords))
    return out


def _rebuild(context):
    _STATE["batch"] = None
    _STATE["count"] = 0
    _STATE["dirty"] = False
    obj = context.edit_object
    if obj is None or obj.type != 'MESH':
        return
    threshold = _threshold_deg()
    _STATE["threshold"] = threshold
    _STATE["obj_ptr"] = obj.as_pointer()
    try:
        bm = bmesh.from_edit_mesh(obj.data)
    except (ValueError, ReferenceError):
        return
    hits = collect_nonplanar(bm, obj.matrix_world, threshold)
    _STATE["count"] = len(hits)
    if not hits:
        return
    theme = get_theme(context)
    r, g, b, _a = theme.color_for(Role.ERROR_LINE)
    normal_mat = obj.matrix_world.inverted_safe().transposed().to_3x3()
    pos, col = [], []
    for f, dev, coords in hits:
        alpha = deviation_alpha(dev, threshold)
        world_n = (normal_mat @ f.normal)
        world_n = (world_n.normalized() if world_n.length_squared > 0.0
                   else Vector((0.0, 0.0, 0.0)))
        offset = world_n * NORMAL_OFFSET
        pts = [Vector(c) + offset for c in coords]
        rgba = (r, g, b, alpha)
        for i0, i1, i2 in tessellate_polygon([pts]):
            pos.extend((pts[i0], pts[i1], pts[i2]))
            col.extend((rgba, rgba, rgba))
    shader = gpu.shader.from_builtin('SMOOTH_COLOR')
    _STATE["batch"] = (shader,
                       batch_for_shader(shader, 'TRIS',
                                        {"pos": pos, "color": col}))


def _needs_rebuild(context) -> bool:
    obj = context.edit_object
    return (_STATE["dirty"]
            or obj.as_pointer() != _STATE["obj_ptr"]
            or _threshold_deg() != _STATE["threshold"])


def _draw_view():
    context = bpy.context
    if context.mode != 'EDIT_MESH':
        return
    obj = context.edit_object
    if obj is None or obj.type != 'MESH':
        return
    if _needs_rebuild(context):
        try:
            _rebuild(context)
        except Exception as e:
            # Never raise from a draw handler — it repeats every redraw.
            print("IOPS Non-Planar overlay: rebuild failed:", e)
            _STATE["batch"] = None
            _STATE["dirty"] = False
    if _STATE["batch"] is None:
        return
    shader, batch = _STATE["batch"]
    with draw_scope(blend='ALPHA', depth='LESS_EQUAL', depth_mask=False):
        batch.draw(shader)


def _draw_pixel():
    context = bpy.context
    if context.mode != 'EDIT_MESH' or context.edit_object is None:
        return
    region = context.region
    if region is None:
        return
    theme = get_theme(context)
    count = _STATE["count"]
    role = Role.HUD_STATS_ERROR if count else Role.HUD_LABEL
    with hud_text.isolated(theme) as font_id:
        hud_text.draw(f"Non-Planar: {count}", LABEL_X,
                      region.height - LABEL_Y_FROM_TOP,
                      theme=theme, role=role, font_id=font_id)


def _enable():
    if overlay_enabled():
        return
    _STATE["dirty"] = True
    _STATE["handle_view"] = safe_handler_add(
        bpy.types.SpaceView3D, _draw_view, (), "WINDOW", "POST_VIEW")
    _STATE["handle_pixel"] = safe_handler_add(
        bpy.types.SpaceView3D, _draw_pixel, (), "WINDOW", "POST_PIXEL")
    for lst in _app_handler_lists():
        if _mark_dirty not in lst:
            lst.append(_mark_dirty)


def disable_overlay():
    """Idempotent. Also called from the addon's unregister(); removes only
    this module's handlers."""
    safe_handler_remove(_STATE["handle_view"], bpy.types.SpaceView3D, "WINDOW")
    safe_handler_remove(_STATE["handle_pixel"], bpy.types.SpaceView3D, "WINDOW")
    for lst in _app_handler_lists():
        while _mark_dirty in lst:
            lst.remove(_mark_dirty)
    _STATE.update(handle_view=None, handle_pixel=None, batch=None,
                  count=0, dirty=True, obj_ptr=0, threshold=None)


def _tag_redraw_view3d(context):
    screen = getattr(context, "screen", None)
    if screen is None:
        return
    for area in screen.areas:
        if area.type == 'VIEW_3D':
            area.tag_redraw()


class IOPS_OT_MeshNonPlanarOverlay(bpy.types.Operator):
    """Toggle a real-time highlight of non-planar faces in Edit Mode.
    Fill intensity scales with how far each face is from planar"""
    bl_idname = "iops.mesh_nonplanar_overlay"
    bl_label = "Non-Planar Faces Overlay"
    bl_options = {"REGISTER"}

    @classmethod
    def poll(cls, context):
        # Enabling needs an edit-mesh; disabling is allowed from anywhere.
        return overlay_enabled() or (context.mode == 'EDIT_MESH'
                                     and context.edit_object is not None)

    def execute(self, context):
        if overlay_enabled():
            disable_overlay()
            self.report({'INFO'}, "Non-Planar overlay: OFF")
        else:
            _enable()
            _rebuild(context)
            self.report({'INFO'},
                        f"Non-Planar overlay: ON "
                        f"({_STATE['count']} non-planar)")
        _tag_redraw_view3d(context)
        return {'FINISHED'}
```

Implementation notes (why, for the reviewer):
- `load_post` is in the dirty-hook list and `_mark_dirty` is `@persistent`: draw handlers survive a file load, so the hooks must too, and non-persistent app handlers are cleared on load.
- Deviation is measured on world-space coords (`matrix_world @ v.co`) because non-uniform scale changes angles — measure what the user sees.
- `f.normal` is local; world normal uses the inverse-transpose.
- `tessellate_polygon` handles concave ngons; it takes 3D Vectors and returns index triples into the input ring.
- One `SMOOTH_COLOR` batch with per-vertex RGBA gives per-face alpha in a single draw call (`ui/draw/primitives.tris` is uniform-color, unsuitable here).

- [ ] **Step 2: Syntax check**

Run: `python -m py_compile D:/git/InteractionOps/operators/mesh_nonplanar_overlay.py`
Expected: exit 0. (Behavior is verified headlessly in Task 4 — the module imports bpy, so it can't run under pytest.)

- [ ] **Step 3: Commit**

```bash
git add operators/mesh_nonplanar_overlay.py
git commit -m "feat(nonplanar): non-planar faces overlay operator with cached batch"
```

---

### Task 4: Registration + headless smoke test

**Files:**
- Modify: `__init__.py` (import ~line 253; classes tuple ~line 518; unregister cleanup near the `draw_theme_preview.cleanup_live_installs()` block ~line 683)
- Create: `B:\test\nonplanar_smoke.py` (test-harness area, NOT the repo)

**Interfaces:**
- Consumes: `IOPS_OT_MeshNonPlanarOverlay`, `disable_overlay`, `overlay_enabled`, `collect_nonplanar` from Task 3.
- Produces: registered `bpy.ops.iops.mesh_nonplanar_overlay()`.

- [ ] **Step 1: Add the import**

In `__init__.py`, directly after `from .operators.mesh_visual_uv import IOPS_OT_MeshVisualUV` (~line 253), add:

```python
from .operators.mesh_nonplanar_overlay import IOPS_OT_MeshNonPlanarOverlay
```

- [ ] **Step 2: Register the class**

In the classes tuple, directly after the `IOPS_OT_MeshVisualUV,` entry (~line 518), add:

```python
    IOPS_OT_MeshNonPlanarOverlay,
```

- [ ] **Step 3: Add unregister cleanup**

In `unregister()`, directly after the `draw_theme_preview` cleanup try/except block (~lines 683-689), add:

```python
    # Kill the non-planar overlay's draw + app handlers before classes go
    # away. Removes only this addon's handlers.
    try:
        from .operators.mesh_nonplanar_overlay import disable_overlay
        disable_overlay()
    except Exception as e:
        print("IOPS: non-planar overlay cleanup failed:", e)
```

- [ ] **Step 4: Write the headless smoke test**

Create `B:\test\nonplanar_smoke.py`:

```python
"""Headless smoke test for iops.mesh_nonplanar_overlay.

Run:
V:\\SteamLibrary\\steamapps\\common\\Blender\\blender.exe --background --python B:\\test\\nonplanar_smoke.py

Grep stdout for 'SMOKE:'. Reloads the addon so the working tree in
D:\\git\\InteractionOps is what gets tested.
"""
import traceback

import addon_utils
import bmesh
import bpy


def main():
    # Pick up the current working-tree code.
    addon_utils.disable("InteractionOps", default_set=False)
    addon_utils.enable("InteractionOps", default_set=False)

    from InteractionOps.operators import mesh_nonplanar_overlay as mod

    bpy.ops.mesh.primitive_cube_add()
    obj = bpy.context.active_object
    bpy.ops.object.mode_set(mode='EDIT')
    bm = bmesh.from_edit_mesh(obj.data)
    bm.verts.ensure_lookup_table()

    # Pristine cube: all faces planar.
    hits = mod.collect_nonplanar(bm, obj.matrix_world, 0.5)
    assert not hits, f"pristine cube reported {len(hits)} non-planar faces"

    # Push one corner along the body diagonal: its 3 faces warp.
    bm.verts[0].co += bm.verts[0].co.normalized() * 0.4
    bmesh.update_edit_mesh(obj.data)
    hits = mod.collect_nonplanar(bm, obj.matrix_world, 0.5)
    assert len(hits) == 3, f"expected 3 warped faces, got {len(hits)}"
    devs = sorted(dev for _f, dev, _c in hits)
    assert devs[0] > 0.5, f"deviation {devs[0]} not above threshold"

    # Non-uniform object scale must not break detection (world-space math).
    obj.scale = (1.0, 3.0, 0.5)
    bpy.context.view_layer.update()
    hits_scaled = mod.collect_nonplanar(bm, obj.matrix_world, 0.5)
    assert len(hits_scaled) == 3, (
        f"non-uniform scale: expected 3, got {len(hits_scaled)}")
    obj.scale = (1.0, 1.0, 1.0)
    bpy.context.view_layer.update()

    # Restore planarity: the default cube's vert 0 sits at (-1, -1, -1).
    bm.verts[0].co = (-1.0, -1.0, -1.0)
    bmesh.update_edit_mesh(obj.data)
    hits = mod.collect_nonplanar(bm, obj.matrix_world, 0.5)
    assert not hits, f"flattened cube still reports {len(hits)}"

    # Operator toggle round-trip: handlers registered, then fully removed.
    # NOTE: must run while the mesh is PLANAR — the `gpu` module raises in
    # --background mode, and _rebuild only touches gpu when there are hits.
    bpy.ops.iops.mesh_nonplanar_overlay()
    assert mod.overlay_enabled(), "toggle ON did not register handlers"
    assert mod._mark_dirty in bpy.app.handlers.depsgraph_update_post
    bpy.ops.iops.mesh_nonplanar_overlay()
    assert not mod.overlay_enabled(), "toggle OFF left draw handlers"
    assert mod._mark_dirty not in bpy.app.handlers.depsgraph_update_post
    assert mod._mark_dirty not in bpy.app.handlers.undo_post
    assert mod._mark_dirty not in bpy.app.handlers.redo_post
    assert mod._mark_dirty not in bpy.app.handlers.load_post

    print("SMOKE: PASS")


try:
    main()
except Exception:
    traceback.print_exc()
    print("SMOKE: FAIL")
    raise SystemExit(1)
```

- [ ] **Step 5: Run the smoke test**

Run: `V:\SteamLibrary\steamapps\common\Blender\blender.exe --background --python B:\test\nonplanar_smoke.py`
Expected: stdout contains `IOPS Registered!` and `SMOKE: PASS`, exit code 0.

If `KeyError: 'InteractionOps'` — the addon isn't enabled in userprefs for background runs; re-check the enable call order, don't add `--factory-startup`.

- [ ] **Step 6: Commit (repo files only — B:\test is outside the repo)**

```bash
git add __init__.py
git commit -m "feat(nonplanar): register non-planar overlay operator + unregister cleanup"
```

---

### Task 5: Documentation

**Files:**
- Create: `docs/operators/op_mesh_nonplanar_overlay.md`
- Modify: `mkdocs.yml` (nav — after `- Mesh Visual UV: operators/op_mesh_visual_uv.md`, line 138)

**Interfaces:**
- Consumes: final behavior from Tasks 1-4.
- Produces: user-facing docs page wired into the mkdocs nav.

- [ ] **Step 1: Write the docs page**

Look at `docs/operators/op_mesh_visual_uv.md` first and match its heading/section style (title, What it does, How to use, Settings). Content to cover, adapted to that style:

```markdown
# Non-Planar Faces Overlay

`iops.mesh_nonplanar_overlay` — Edit Mode (mesh)

Toggles a sticky viewport overlay that highlights every non-planar face of
the active edit-mesh in real time. Fix a face — flatten it below the
threshold — and its highlight disappears on the next redraw.

## What it does

- Checks every visible quad/ngon of the active object (triangles are always
  planar and skipped). A face is non-planar when any corner's plane deviates
  from the face's best-fit plane by more than the **Non-Planar Angle**
  threshold.
- Non-planar faces are filled with the theme's error color. Fill intensity
  scales with the deviation: faces just past the threshold are faint, faces
  warped 15° or more draw at full strength.
- A `Non-Planar: N` counter in the top-left corner of the viewport shows the
  current count and confirms the mode is on even when everything is planar.
- The overlay is **sticky**: it survives object switches and mode changes
  (it only draws in Edit Mode) and stays active until toggled off.

## How to use

1. Enter Edit Mode on a mesh and run **Non-Planar Faces Overlay**
   (F3 search, or bind it to a hotkey).
2. Model. Highlights update live as you move vertices; deviation-heavy
   faces glow stronger.
3. Run the operator again to turn the overlay off.

## Settings

- **Preferences → Non-Planar Overlay → Non-Planar Angle** — threshold in
  degrees (default 0.5°). Faces below it count as planar. The full-intensity
  ceiling (15°) is fixed.

## Notes

- Only the active object is checked in multi-object edit sessions.
- Detection runs in world space, so non-uniform object scale is measured
  the way you see it.
- Hidden faces are ignored.
```

- [ ] **Step 2: Add the nav entry**

In `mkdocs.yml` after line 138 (`- Mesh Visual UV: operators/op_mesh_visual_uv.md`), add at the same indent:

```yaml
          - Non-Planar Overlay: operators/op_mesh_nonplanar_overlay.md
```

- [ ] **Step 3: Verify the nav entry**

Run: `python -m mkdocs build -f D:/git/InteractionOps/mkdocs.yml --site-dir "%TEMP%/iops_site"` (from `D:/git/InteractionOps`).
Expected: build succeeds, no "not found in nav" warning for the new page. If mkdocs isn't installed (`No module named mkdocs`), diff the new line's indentation against the `Mesh Visual UV` line above it — they must match exactly.

- [ ] **Step 4: Commit**

```bash
git add docs/operators/op_mesh_nonplanar_overlay.md mkdocs.yml
git commit -m "docs(operators): non-planar faces overlay page"
```

---

### Task 6: Live verification (main session — NOT a subagent)

Interactive Blender must be running with the MCP addon connected (port 9999). Reload infra per `reference_dev_reload_infra.md` memory (blinker reload on port 9902).

- [ ] **Step 1: Reload the addon in the live Blender** (blinker port 9902, or disable/enable via MCP `execute_blender_code`)
- [ ] **Step 2: Scripted scenario via MCP:** create a cube, enter edit mode, warp one corner, run `bpy.ops.iops.mesh_nonplanar_overlay()`
- [ ] **Step 3: Screenshot** (`get_screenshot_of_area_as_image`): confirm red fills on the 3 warped faces, `Non-Planar: 3` label top-left
- [ ] **Step 4: Flatten the corner back via MCP; screenshot: fills gone, label reads `Non-Planar: 0`**
- [ ] **Step 5: Threshold check: set `nonplanar_angle` to 45.0 via MCP, warp slightly — no highlight; reset to 0.5 — highlight returns**
- [ ] **Step 6: Toggle off; screenshot: no fills, no label. Switch modes/objects with overlay on — no errors in console**
- [ ] **Step 7: Report results to user with the screenshots**
