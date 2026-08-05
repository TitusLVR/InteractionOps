# Shear Hinge Sub-Modal (Q) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Q inside `iops.mesh_shear` rotates the selected faces around the active edge (hinge), with numeric angle, Ctrl+wheel segments, A flush-to-face pick, and a confirm that spins real geometry and chains back to shear.

**Architecture:** Sub-modal in the `_extrude_active` style: `_hinge_active` flag + `_hinge_data` dict, routed at the top of `_modal`. Live preview is pure vert-coord rotation (`Matrix.Rotation` about the edge midpoint); real geometry (`bmesh.ops.spin` with steps + remove doubles) is created once at confirm. Flush-angle math is a pure function in `utils/hinge_core.py` so pytest can cover it without bpy.

**Tech Stack:** Blender bmesh/bpy modal operator, mathutils, pytest (pure-python core), blender-mcp for live smoke tests.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-08-05-shear-hinge-submodal-design.md`.
- Angle input is numeric only (digits / `.` / `-` / Backspace); no mouse-drag angle.
- Steps clamped 1..64, changed only via Ctrl+wheel.
- Merge distance fixed at `0.001`.
- User preference: ONE solid commit for the whole feature at the end (spec + plan + code). No per-task commits.
- Tests in `tests/` must not import bpy (see `tests/conftest.py`).

---

### Task 1: Pure flush-angle core (`utils/hinge_core.py`)

**Files:**
- Create: `utils/hinge_core.py`
- Test: `tests/test_hinge_core.py`

**Interfaces:**
- Produces: `flush_angle(n_sel, n_tgt, axis) -> float | None` — all args
  3-tuples; `axis` need not be unit (normalized inside); returns the signed
  angle in RADIANS with the smallest magnitude that rotates `n_sel` about
  `axis` so the planes become coplanar (normal parallel OR anti-parallel to
  `n_tgt`); `None` when either normal is (near-)parallel to the axis.
- Produces: `EPS = 1e-9` module constant.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_hinge_core.py
import math
import pytest

from utils.hinge_core import flush_angle


def test_quarter_turn_about_x():
    # plane normal +Z, target normal +Y, axis +X: rotating +Z by -90deg
    # about +X gives +Y
    a = flush_angle((0, 0, 1), (0, 1, 0), (1, 0, 0))
    assert a == pytest.approx(-math.pi / 2)


def test_already_flush_is_zero():
    assert flush_angle((0, 0, 1), (0, 0, 1), (1, 0, 0)) == pytest.approx(0.0)


def test_antiparallel_target_is_zero():
    # planes already coplanar even though normals oppose
    assert flush_angle((0, 0, 1), (0, 0, -1), (1, 0, 0)) == pytest.approx(0.0)


def test_picks_smaller_magnitude_solution():
    # +Z to a normal 135deg away about +X: direct solution is +135deg but
    # the anti-parallel representative is -45deg — must pick -45deg
    s = math.sin(math.radians(135))
    c = math.cos(math.radians(135))
    a = flush_angle((0, 0, 1), (0, -s, c), (1, 0, 0))
    assert a == pytest.approx(-math.radians(45))


def test_picks_smaller_magnitude_solution_opposite():
    # +Z to the opposite normal (135deg but other quadrant): direct solution
    # is -135deg but the anti-parallel representative is +45deg — pick +45deg
    s = math.sin(math.radians(135))
    c = math.cos(math.radians(135))
    a = flush_angle((0, 0, 1), (0, s, c), (1, 0, 0))
    assert a == pytest.approx(math.radians(45))


def test_axis_parallel_normal_returns_none():
    assert flush_angle((1, 0, 0), (0, 0, 1), (1, 0, 0)) is None
    assert flush_angle((0, 0, 1), (1, 0, 0), (1, 0, 0)) is None


def test_unnormalized_inputs():
    a = flush_angle((0, 0, 7), (0, 3, 0), (2, 0, 0))
    assert a == pytest.approx(-math.pi / 2)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_hinge_core.py -v` (from repo root)
Expected: FAIL — `ModuleNotFoundError: No module named 'utils.hinge_core'`

- [ ] **Step 3: Write the implementation**

```python
# utils/hinge_core.py
"""Pure-python hinge math (no bpy) so pytest can cover it.

flush_angle: the signed rotation about `axis` that makes the plane
with normal `n_sel` coplanar with the plane with normal `n_tgt`.
Coplanar means the rotated normal is parallel OR anti-parallel to the
target normal — both representatives are computed and the smaller-
magnitude angle wins (hinging a flap "flush" onto a surface should
take the short way round).
"""
import math

EPS = 1e-9


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _cross(a, b):
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def _norm(a):
    L = math.sqrt(_dot(a, a))
    if L < EPS:
        return None
    return (a[0] / L, a[1] / L, a[2] / L)


def _perp_to_axis(v, axis):
    d = _dot(v, axis)
    return (v[0] - d * axis[0], v[1] - d * axis[1], v[2] - d * axis[2])


def flush_angle(n_sel, n_tgt, axis):
    axis = _norm(axis)
    if axis is None:
        return None
    a = _norm(_perp_to_axis(n_sel, axis))
    b = _norm(_perp_to_axis(n_tgt, axis))
    if a is None or b is None:
        return None
    ang = math.atan2(_dot(_cross(a, b), axis), _dot(a, b))
    nb = (-b[0], -b[1], -b[2])
    alt = math.atan2(_dot(_cross(a, nb), axis), _dot(a, nb))
    return ang if abs(ang) <= abs(alt) else alt
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_hinge_core.py -v`
Expected: 6 passed. Also run the full suite: `python -m pytest tests/ -v` — no regressions.

---

### Task 2: Hinge entry, live preview, numeric input, steps, cancel

**Files:**
- Modify: `operators/mesh_shear.py` — imports, `invoke` (state init + HUD),
  `_modal` (Q key + routing), new methods `_enter_hinge`, `_hinge_effective_angle`,
  `_hinge_apply`, `_hinge_restore`, `_hinge_modal`, `_cancel_hinge`; `_finish`
  (state cleanup); `_status_text` (hinge branch).

**Interfaces:**
- Consumes: existing `self.input_str` digit pattern, `DIGIT_TYPES`,
  `capture_event`, HUD classes.
- Produces: `self._hinge_active: bool`, `self._hinge_data: dict | None` with
  keys `faces` (list[BMFace]), `verts` (list[BMVert]), `orig_cos`
  (list[Vector]), `orig_co_map` (dict[BMVert, Vector]), `center` (Vector),
  `axis` (unit Vector), `edge` (BMEdge), `orig_normal` (unit Vector),
  `steps` (int), `radius` (float). `self._hinge_angle_deg: float`.
  Tasks 3-5 rely on these exact names.

- [ ] **Step 1: Add `Matrix` to the mathutils import**

```python
from mathutils import Matrix, Vector
```

- [ ] **Step 2: Init state in `invoke`** (next to the extrude state block)

```python
        # Hinge sub-modal state. Q enters; selected faces rotate around
        # the active edge from select_history. Preview is pure vert
        # rotation; bmesh.ops.spin runs once at confirm (Task 3).
        self._hinge_active = False
        self._hinge_data = None
        self._hinge_angle_deg = 0.0
```

- [ ] **Step 3: Implement `_enter_hinge` (place after `_cancel_extrude`)**

```python
    def _enter_hinge(self, context, event):
        """Q: begin the hinge sub-modal. Selected faces rotate around
        the active edge (select_history), like the classic hinge tool.
        Captures current coords as the rotation base — an in-progress
        shear pose is treated as ground truth, mirroring E-extrude."""
        hist_edge = None
        try:
            for item in self.bm.select_history:
                if isinstance(item, bmesh.types.BMEdge):
                    hist_edge = item
        except (TypeError, RuntimeError):
            pass
        sel_faces = [f for f in self.bm.faces if f.select]
        if hist_edge is None or not hist_edge.is_valid or not sel_faces:
            self.report({"INFO"},
                        "hinge: needs selected faces and an active edge")
            return False
        v0, v1 = hist_edge.verts
        axis = v1.co - v0.co
        if axis.length < 1e-9:
            self.report({"INFO"}, "hinge: active edge has zero length")
            return False
        axis = axis.normalized()
        center = (v0.co + v1.co) * 0.5

        vert_set = set()
        for f in sel_faces:
            vert_set.update(f.verts)
        verts = list(vert_set)
        orig_cos = [v.co.copy() for v in verts]

        # Average selection normal at entry — the flush reference (A).
        n_sum = Vector((0.0, 0.0, 0.0))
        for f in sel_faces:
            n_sum += _face_normal_safe(f)
        orig_normal = (n_sum.normalized() if n_sum.length > 1e-9
                       else _face_normal_safe(sel_faces[0]))

        # Arc radius: fraction of the max vert distance to the axis line.
        max_d = 0.0
        for co in orig_cos:
            rel = co - center
            d = (rel - rel.dot(axis) * axis).length
            if d > max_d:
                max_d = d
        radius = max_d * 0.35 if max_d > 1e-6 else axis.length * 0.5

        self._hinge_data = {
            "faces": sel_faces,
            "verts": verts,
            "orig_cos": orig_cos,
            "orig_co_map": {v: c for v, c in zip(verts, orig_cos)},
            "center": center.copy(),
            "axis": axis.copy(),
            "edge": hist_edge,
            "orig_normal": orig_normal.copy(),
            "steps": 1,
            "radius": radius,
        }
        self._hinge_active = True
        self._hinge_angle_deg = 0.0
        self.input_str = ""
        self._hotspots = []
        self._hover_idx = None
        return True
```

- [ ] **Step 4: Implement angle helpers + apply/restore**

```python
    def _hinge_effective_angle(self):
        if self.input_str and self.input_str not in ("-", ".", "-."):
            try:
                return float(self.input_str)
            except ValueError:
                return self._hinge_angle_deg
        return self._hinge_angle_deg

    def _hinge_apply(self):
        d = self._hinge_data
        rot = Matrix.Rotation(
            math.radians(self._hinge_effective_angle()), 4, d["axis"])
        c = d["center"]
        for v, oc in zip(d["verts"], d["orig_cos"]):
            if v.is_valid:
                v.co = c + rot @ (oc - c)
        self.bm.normal_update()
        bmesh.update_edit_mesh(self.obj.data)

    def _hinge_restore(self):
        d = self._hinge_data
        for v, oc in zip(d["verts"], d["orig_cos"]):
            if v.is_valid:
                v.co = oc
        self.bm.normal_update()
        bmesh.update_edit_mesh(self.obj.data)
```

- [ ] **Step 5: Implement `_hinge_modal` and `_cancel_hinge`**

Confirm keys call `_confirm_hinge` (real body lands in Task 3) and A calls
`_hinge_flush_pick` (Task 4) — write the calls now, add temporary stubs at
the end of this step so the file stays importable:

```python
    def _hinge_modal(self, context, event):
        # Navigation passes through (Q sub-modal owns Ctrl+wheel only).
        if (event.type == "MIDDLEMOUSE" or event.type.startswith("NDOF")
                or (event.type in {"WHEELUPMOUSE", "WHEELDOWNMOUSE"}
                    and not event.ctrl)):
            return {"PASS_THROUGH"}

        if event.type in {"WHEELUPMOUSE", "WHEELDOWNMOUSE"} and event.ctrl:
            d = self._hinge_data
            delta = 1 if event.type == "WHEELUPMOUSE" else -1
            d["steps"] = max(1, min(64, d["steps"] + delta))
            context.workspace.status_text_set(self._status_text())
            if context.area:
                context.area.tag_redraw()
            return {"RUNNING_MODAL"}

        if event.type == "MOUSEMOVE":
            self._mouse_xy = (event.mouse_region_x, event.mouse_region_y)
            return {"RUNNING_MODAL"}

        if event.value == "PRESS":
            if event.type in DIGIT_TYPES:
                self.input_str += DIGIT_TYPES[event.type]
                self._hinge_apply()
            elif event.type in {"PERIOD", "NUMPAD_PERIOD"}:
                if "." not in self.input_str:
                    self.input_str += "."
            elif event.type in {"MINUS", "NUMPAD_MINUS"}:
                if self.input_str.startswith("-"):
                    self.input_str = self.input_str[1:]
                else:
                    self.input_str = "-" + self.input_str
                self._hinge_apply()
            elif event.type == "BACK_SPACE":
                self.input_str = self.input_str[:-1]
                self._hinge_apply()
            elif event.type == "D":
                if self.input_str:
                    if self.input_str.startswith("-"):
                        self.input_str = self.input_str[1:]
                    else:
                        self.input_str = "-" + self.input_str
                else:
                    self._hinge_angle_deg = -self._hinge_angle_deg
                self._hinge_apply()
            elif event.type == "A":
                self._hinge_flush_pick(context, event)   # Task 4
            elif event.type in {"RET", "NUMPAD_ENTER", "SPACE"}:
                return self._confirm_hinge(context)      # Task 3
            elif event.type in {"RIGHTMOUSE", "ESC"}:
                self._cancel_hinge(context)
            context.workspace.status_text_set(self._status_text())
            if context.area:
                context.area.tag_redraw()
            return {"RUNNING_MODAL"}
        return {"RUNNING_MODAL"}

    def _cancel_hinge(self, context):
        self._hinge_restore()
        self._hinge_active = False
        self._hinge_data = None
        self._hinge_angle_deg = 0.0
        self.input_str = ""
        self._hotspots = []
        self._hover_idx = None
        return {"RUNNING_MODAL"}
```

Temporary stubs so the file imports clean until Tasks 3-4 land:

```python
    def _confirm_hinge(self, context):
        return self._cancel_hinge(context)

    def _hinge_flush_pick(self, context, event):
        pass
```

- [ ] **Step 6: Route in `_modal` and add the Q key**

The hinge branch must run BEFORE the global wheel pass-through block
(Ctrl+wheel would be eaten otherwise). Change the top of `_modal`:

```python
        if self._hinge_active:
            return self._hinge_modal(context, event)

        if (event.type in {"MIDDLEMOUSE", "WHEELUPMOUSE", "WHEELDOWNMOUSE"}
                or event.type.startswith("NDOF")):
            return {"PASS_THROUGH"}

        if self._extrude_active:
            return self._extrude_modal(context, event)
```

Add the Q handler next to the E handler:

```python
            if event.type == "Q":
                if self._enter_hinge(context, event):
                    context.workspace.status_text_set(self._status_text())
                return {"RUNNING_MODAL"}
```

- [ ] **Step 7: `_status_text` hinge branch (before the extrude branch)**

```python
        if self._hinge_active:
            d = self._hinge_data
            typed = f" | typing: {self.input_str}" if self.input_str else ""
            return (
                f"Hinge: {self._hinge_effective_angle():.2f}° | "
                f"steps: {d['steps']}{typed} | [0-9 . -] type | "
                "[Ctrl+Wheel] steps | [D] flip | [A] flush to face | "
                "[Enter] confirm | [Esc/RMB] cancel hinge"
            )
```

- [ ] **Step 8: `_finish` cleanup** — add next to the extrude fields:

```python
        self._hinge_active = False
        self._hinge_data = None
```

- [ ] **Step 9: HUD** — in `invoke`, add to the shear items list:

```python
            HUDItem("Hinge around active edge", "Q", ItemState.ON, default_state=ItemState.OFF, always_show=True),
```

and a dedicated help section after the Shear one:

```python
        hinge_items = [
            HUDItem("Type angle",     "0-9 . -",    ItemState.ON, default_state=ItemState.OFF, always_show=True),
            HUDItem("Segments",       "Ctrl+Wheel", ItemState.ON, default_state=ItemState.OFF, always_show=True),
            HUDItem("Flip direction", "D",          ItemState.ON, default_state=ItemState.OFF, always_show=True),
            HUDItem("Flush to face",  "A",          ItemState.ON, default_state=ItemState.OFF, always_show=True),
            HUDItem("Confirm",        "Enter",      ItemState.ON, default_state=ItemState.OFF, always_show=True),
            HUDItem("Cancel hinge",   "Esc / RMB",  ItemState.ON, default_state=ItemState.OFF, always_show=True),
        ]
        self._help.add_section(HUDSection("Hinge (Q)", hinge_items))
```

- [ ] **Step 10: MCP smoke test**

Via blender-mcp (skill `blender-mcp`): reload the addon, then on a cube in
edit mode select the top face, make one of its edges the active edge
(re-click it in edge mode, then re-select the face), run
`bpy.ops.iops.mesh_shear('INVOKE_DEFAULT')` — real key events can't be
scripted, so instead drive the internals headlessly: build a bmesh cube,
instantiate nothing — just verify by manual test in the viewport. Minimum
scripted check: `_enter_hinge` math — rotate top-face verts 90° about a top
edge and assert the opposite edge verts moved onto the expected positions
using a throwaway `bmesh` + `Matrix.Rotation` replicating `_hinge_apply`.
Report results; ask the user for a quick viewport check (Q, type 45, Esc —
geometry must return exactly).

---

### Task 3: Confirm — spin, remove doubles, chain back to shear

**Files:**
- Modify: `operators/mesh_shear.py` — replace the `_confirm_hinge` stub;
  add module-level `_gather_double_verts`.

**Interfaces:**
- Consumes: `self._hinge_data` (Task 2), `build_face_record`,
  `face_principal_axes`, `restore_records`.
- Produces: `_confirm_hinge(context) -> set` (modal return value);
  `_gather_double_verts(seed_verts, dist) -> list[BMVert]` (module level,
  next to the other module helpers).

- [ ] **Step 1: Module helper — neighbor walk for remove_doubles**

Port of forgotten-tools `prepare_doubles`, but with a python set instead
of index tags (spin leaves fresh verts with stale indices):

```python
def _gather_double_verts(seed_verts, dist):
    """Grow `seed_verts` across link_loops to every vert closer than
    `dist` to an already-collected vert. Recursion via list growth."""
    verts = list(seed_verts)
    seen = set(verts)
    for v in verts:
        co = v.co
        for loop in v.link_loops:
            nv = loop.link_loop_next.vert
            if nv not in seen and (nv.co - co).length < dist:
                seen.add(nv)
                verts.append(nv)
    return verts
```

- [ ] **Step 2: Implement `_confirm_hinge`**

```python
    def _confirm_hinge(self, context):
        """Enter/Space: bake the hinge. Restore the preview pose, run
        bmesh.ops.spin with the chosen steps (real segment geometry),
        merge doubles at the hinge line, select the resulting cap and
        rebuild shear records on it so the modal chains back to shear.
        Zero angle is a clean no-op exit back to shear."""
        d = self._hinge_data
        angle_rad = math.radians(self._hinge_effective_angle())
        self._hinge_restore()
        if abs(angle_rad) < 1e-6:
            return self._cancel_hinge(context)

        edge = d["edge"]
        # Flap case (all faces at the hinge edge are selected): drop the
        # edge from the selection so spin bends the flap instead of
        # extruding a new wall from the hinge line. Mirrors forgotten
        # hinge.
        if (edge.is_valid and edge.link_faces
                and all(f.select for f in edge.link_faces)):
            edge.select = False
            edge.verts[0].select = False
            edge.verts[1].select = False

        faces = [f for f in self.bm.faces if f.select]
        edges = [e for e in self.bm.edges if e.select]
        verts = [v for v in self.bm.verts if v.select]
        geom = edges + faces + verts
        if not geom:
            self.report({"WARNING"}, "hinge: nothing to spin")
            return self._cancel_hinge(context)
        for g in geom:
            g.select = False

        result = bmesh.ops.spin(
            self.bm, geom=geom, cent=d["center"], axis=d["axis"],
            angle=angle_rad, steps=d["steps"], use_merge=False)
        last = result["geom_last"]

        dist = 0.001
        seed = [g for g in last if isinstance(g, bmesh.types.BMVert)]
        if seed:
            bmesh.ops.remove_doubles(
                self.bm, verts=_gather_double_verts(seed, dist), dist=dist)

        for g in last:
            if g.is_valid:
                g.select_set(True)
        self.bm.normal_update()
        bmesh.update_edit_mesh(self.obj.data, loop_triangles=True,
                               destructive=True)

        # Exit the sub-modal before rebuilding shear records.
        self._hinge_active = False
        self._hinge_data = None
        self._hinge_angle_deg = 0.0
        self.input_str = ""
        self._hotspots = []
        self._hover_idx = None

        cap_faces = [g for g in last
                     if isinstance(g, bmesh.types.BMFace) and g.is_valid]
        new_records = []
        for f in cap_faces:
            pa, _ = face_principal_axes(f)
            if pa is None:
                continue
            rec, _ = build_face_record(f, pa)
            if rec is not None:
                new_records.append(rec)
        if new_records:
            self.records = new_records
            self.mode = "face"
            self.angle_deg = 0.0
            context.workspace.status_text_set(self._status_text())
            return {"RUNNING_MODAL"}
        # No usable cap (e.g. rails gone after merge) — finish cleanly
        # rather than leaving shear pointed at dead records.
        bpy.ops.ed.undo_push(message="Shear")
        self._finish(context)
        return {"FINISHED"}
```

- [ ] **Step 3: MCP verification**

Headless-ish check via blender-mcp `execute_code`: build a plane grid
(2 faces), select one face, set its shared edge active, then replicate the
confirm path with a direct bmesh script (spin 4 steps 90°) and assert
`len(bm.faces)` grew by `steps` per side wall and the cap face count
matches. Then a live viewport pass by the user: cube top face → Q → `45`
→ Ctrl+wheel to 4 steps → Enter → shear gizmo appears on the rotated cap;
Ctrl+Z once undoes the whole shear+hinge chain.

---

### Task 4: A — flush to picked face

**Files:**
- Modify: `operators/mesh_shear.py` — replace the `_hinge_flush_pick` stub;
  import from `..utils.hinge_core`.

**Interfaces:**
- Consumes: `flush_angle` (Task 1), `self._raycast_face_under_cursor`,
  `BVHTree.FromBMesh` pattern from `_toggle_align_highlight`,
  `_face_normal_safe`, `self._hinge_data` (Task 2).

- [ ] **Step 1: Import the core (top of file, next to other imports)**

```python
from ..utils.hinge_core import flush_angle
```

(Check the actual package name used by sibling imports in `operators/` —
`from ..utils.smart_inset_core import ...` style — and match it.)

- [ ] **Step 2: Implement `_hinge_flush_pick`**

```python
    def _hinge_flush_pick(self, context, event):
        """A: raycast the face under the cursor; set the hinge angle so
        the selection's ORIGINAL plane lands coplanar with the picked
        face's plane (smallest-magnitude solution). Picking one of the
        hinged faces or empty space is a no-op."""
        d = self._hinge_data
        self.bm.normal_update()
        self.bm.faces.ensure_lookup_table()
        self._align_bvh = BVHTree.FromBMesh(self.bm)
        self._mouse_xy = (event.mouse_region_x, event.mouse_region_y)
        picked = self._raycast_face_under_cursor(context)
        self._align_bvh = None
        if picked is None or picked in set(d["faces"]):
            self.report({"INFO"}, "hinge flush: pick a face outside the selection")
            return
        n_t = _face_normal_safe(picked)
        if n_t.length < 1e-9:
            self.report({"INFO"}, "hinge flush: degenerate target face")
            return
        ang = flush_angle(tuple(d["orig_normal"]), tuple(n_t),
                          tuple(d["axis"]))
        if ang is None:
            self.report({"INFO"}, "hinge flush: target parallel to hinge axis")
            return
        self._hinge_angle_deg = math.degrees(ang)
        self.input_str = ""
        self._hinge_apply()
```

- [ ] **Step 3: MCP verification**

The raycast needs a real viewport cursor, so the scripted check covers only
the math: in blender-mcp, for a cube with top face selected and a top edge
active, compute `flush_angle` against the adjacent side face's normal and
assert it returns ±90°. Viewport pass by the user: Q on a flap, hover a
slanted face, A — the flap must land flush on the first press.

---

### Task 5: Drawing + HUD polish

**Files:**
- Modify: `operators/mesh_shear.py` — `_draw_callback` routing, new
  `_draw_hinge` method.

**Interfaces:**
- Consumes: `draw_prim.edges_3d`, `Role`, `self._draw_dot`,
  `view3d_utils.location_3d_to_region_2d`, `self._hinge_data` (Task 2).

- [ ] **Step 1: Route in `_draw_callback`**

While hinge is active the shear record gizmos are stale noise (the hinged
faces usually aren't the record faces) — skip them:

```python
        self._hotspots = []
        if self._hinge_active:
            self._draw_hinge(region, rv3d, mw, context=context, theme=theme)
        else:
            for ri, r in enumerate(self.records):
                if r["type"] == "edge":
                    self._draw_edge_record(region, rv3d, mw, r, ri, context=context, theme=theme)
                else:
                    self._draw_face_record(region, rv3d, mw, r, ri, context=context, theme=theme)
            self._update_hover()
```

(the hover-highlight block below stays as is — with `_hotspots` empty it
draws nothing while hinge is active).

- [ ] **Step 2: Implement `_draw_hinge`**

```python
    def _draw_hinge(self, region, rv3d, mw, *, context, theme):
        """Ghost of the original face outlines, current outlines, the
        hinge axis (amber), and an angle arc with per-segment ticks
        around the edge midpoint."""
        d = self._hinge_data
        if d is None:
            return

        def s2d(co):
            return view3d_utils.location_3d_to_region_2d(
                region, rv3d, mw @ co)

        ghost_segs = []
        curr_segs = []
        for f in d["faces"]:
            if not f.is_valid:
                continue
            loops = list(f.verts)
            n = len(loops)
            for i in range(n):
                a, b = loops[i], loops[(i + 1) % n]
                oa = d["orig_co_map"].get(a)
                ob = d["orig_co_map"].get(b)
                if oa is not None and ob is not None:
                    pa, pb = s2d(oa), s2d(ob)
                    if pa is not None and pb is not None:
                        ghost_segs.extend([pa, pb])
                pa, pb = s2d(a.co), s2d(b.co)
                if pa is not None and pb is not None:
                    curr_segs.extend([pa, pb])
        if ghost_segs:
            draw_prim.edges_3d(ghost_segs, color=(0.45, 0.45, 0.45, 0.55),
                               context=context)
        if curr_segs:
            draw_prim.edges_3d(curr_segs, role=Role.ACTIVE_LINE,
                               context=context)

        # Hinge axis along the active edge — amber (locked role).
        edge = d["edge"]
        if edge.is_valid:
            p0 = s2d(edge.verts[0].co)
            p1 = s2d(edge.verts[1].co)
            if p0 is not None and p1 is not None:
                draw_prim.edges_3d([p0, p1], role=Role.LOCKED_LINE,
                                   context=context)

        # Angle arc + segment ticks in the plane perpendicular to the
        # axis. Basis u points from the axis toward the selection's
        # original centroid so the arc starts on the flap.
        angle_rad = math.radians(self._hinge_effective_angle())
        axis = d["axis"]
        center = d["center"]
        centroid = center * 0.0
        for oc in d["orig_cos"]:
            centroid = centroid + oc
        centroid = centroid / max(1, len(d["orig_cos"]))
        u = centroid - center
        u = u - u.dot(axis) * axis
        if u.length < 1e-9:
            return
        u = u.normalized()
        w = axis.cross(u)
        r = d["radius"]
        n_seg = max(12, int(abs(math.degrees(angle_rad)) / 5.0))
        arc_pts = []
        for i in range(n_seg + 1):
            t = angle_rad * (i / n_seg)
            p = s2d(center + (u * math.cos(t) + w * math.sin(t)) * r)
            if p is None:
                arc_pts = []
                break
            arc_pts.append(p)
        if arc_pts:
            segs = []
            for i in range(len(arc_pts) - 1):
                segs.extend([arc_pts[i], arc_pts[i + 1]])
            draw_prim.edges_3d(segs, role=Role.ACTIVE_LINE, context=context)
        # Ticks at each spin-segment boundary (steps > 1 only).
        steps = d["steps"]
        if steps > 1 and abs(angle_rad) > 1e-6:
            for k in range(1, steps):
                t = angle_rad * (k / steps)
                dir_v = u * math.cos(t) + w * math.sin(t)
                pa = s2d(center + dir_v * (r * 0.9))
                pb = s2d(center + dir_v * (r * 1.1))
                if pa is not None and pb is not None:
                    draw_prim.edges_3d([pa, pb], role=Role.LOCKED_LINE,
                                       context=context)
        # Center dot at the hinge midpoint.
        pc = s2d(center)
        if pc is not None:
            self._draw_dot(pc, radius=5.0,
                           color=theme.color_for(Role.LOCKED_POINT),
                           context=context)
```

- [ ] **Step 3: HUD header** — in `_draw_hud`, prepend hinge lines when active:

```python
        if self._hinge_active and self._hinge_data is not None:
            lines = [f"Mode: hinge",
                     f"Angle: {self._hinge_effective_angle():.2f}°",
                     f"Steps: {self._hinge_data['steps']}"]
        else:
            lines = [f"Mode: {self.mode}",
                     f"Angle: {self._effective_angle():.2f}°"]
```

- [ ] **Step 4: Full verification + single commit**

1. `python -m pytest tests/ -v` — all green.
2. blender-mcp: reload addon, confirm no import errors, run the Task 2/3
   scripted checks once more.
3. User viewport pass (Q → type angle → Ctrl+wheel steps → A flush →
   Enter → continue shearing → Enter; Esc paths at each stage).
4. One commit for everything:

```bash
git add utils/hinge_core.py tests/test_hinge_core.py operators/mesh_shear.py docs/superpowers/specs/2026-08-05-shear-hinge-submodal-design.md docs/superpowers/plans/2026-08-05-shear-hinge-submodal.md
git commit -m "feat(shear): Q hinge sub-modal — rotate selection around active edge

Numeric angle, Ctrl+wheel segments (spin at confirm), A flush-to-face
pick, arc gizmo with segment ticks, auto merge doubles, chains back to
shear on the rotated cap.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```
