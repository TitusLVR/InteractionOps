# Smart Edge Slide Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Modal operator `iops.mesh_smart_edge_slide` ("Smart Edge Slide") that cuts a new edge loop into the existing faces, parallel to each selected edge chain, at an exact width on one chosen side. The selected loop and the mesh shape stay unchanged.

**Architecture:** A pure-Python core (`utils/smart_edge_slide_core.py`, no bpy) works on a *band*: the faces on one side of one chain, given as plain vertex and face dicts. It develops each chain vertex's wedge of faces into 2D, places the new vertices (rail or miter), traces straight cuts across faces, and handles open-chain ends, limits, collapse and snapping. A bmesh bridge (`operators/mesh_smart_edge_slide_bridge.py`) does three things:
- builds bands from the edit mesh, replacing step faces with virtual *lids*;
- projects the cut through steps;
- applies the cut with `edge_split` / `face_split`.

The modal operator (`operators/mesh_smart_edge_slide.py`) copies the lifecycle, HUD and preview patterns of `operators/mesh_smart_inset.py`.

**Tech Stack:** Blender 5.2 Python API (bpy, bmesh, mathutils, gpu); stdlib-only core (math, dataclasses); pytest for the core; headless Blender scripts in `tests/blender/` for the bridge; blender-mcp for the live check.

**Spec:** `docs/superpowers/specs/2026-11-04-smart-edge-slide-design.md`. Read it before any task. It contains the reference case, the behaviour rules and the user's decisions this plan implements.

## Global Constraints

**Code**
- `utils/smart_edge_slide_core.py` imports stdlib only. It must run under plain pytest (`tests/conftest.py` keeps bpy out).
- Core tests are flat in `tests/` and import as `from utils.smart_edge_slide_core import ...`. Run them from the repo root: `python -m pytest tests/test_smart_edge_slide_core.py -q`.
- Code and comments in English. User-facing labels use full words, no abbreviations (repo rule).
- Every viewport preview draws through `ui/draw/primitives` with theme `Role`s, never raw gpu shaders or hard-coded colours.
- Never copy code from Kushiro's `slide_edge` add-on (third-party GPL). It is a behaviour reference only.

**Constants**, defined once in the core and imported elsewhere:
- `EPS = 1e-9`
- `RAIL_MAX_DEV = math.radians(30.0)`
- `EXACT_TOL = 1e-3` (relative to width)
- `STEP_AGREE_COS = 0.8660254`
- `STEP_DIFFER_COS = 0.5`
- `LIMIT_ITERS = 60`
- `SNAP_ITERS = 50`

**Headless Blender runs** set every `BLENDER_USER_*` variable to scratch dirs, or Blender's wheel sync strips the user's extension wheels. Command (Git Bash, repo root):

```bash
S="$TMPDIR/ses_blender"; mkdir -p "$S"/{res,scripts,config,ext,data}
BLENDER_USER_RESOURCES="$S/res" BLENDER_USER_SCRIPTS="$S/scripts" BLENDER_USER_CONFIG="$S/config" \
BLENDER_USER_EXTENSIONS="$S/ext" BLENDER_USER_DATAFILES="$S/data" \
"/c/Program Files/Blender Foundation/Blender 5.2/blender.exe" --background --factory-startup \
  --python-exit-code 1 --python tests/blender/test_smart_edge_slide.py
```

**Line endings** (mixed repo): check `git ls-files --eol <file>` before patching and keep each file's own ending.
- CRLF: `ui/iops_pie_edit.py`, `ui/iops_pie_menu.py`.
- Mixed: `docs/ui/ui_pies.md`. Keep each line's ending.
- New files: LF.

**Lint** with `uvx ruff@0.12.0 check <changed .py files>`.

**Git**
- Work on branch `feat/smart-edge-slide`, one commit per task.
- Commit messages are conventional (`feat(smart-edge-slide): ...`) and end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Never push. Squash with the `squash-feature-commits` skill only when the user asks to push.

**The live Blender usually has the user's real file open and dirty.** Before any scene-changing MCP call, follow the blender-mcp skill's file-protection rules. Reload the addon only with `addon_disable` / `addon_enable` plus clearing `sys.modules`.

## Review Focus

These five failure modes are the most likely to bite a user. No feature test exercises them, so each gets a pinned test in its owning task:

1. **Ctrl-snap to an existing vertex.** The new loop lands exactly on existing vertices (for example an existing mid loop). The cut must reuse those vertices: no duplicates, no zero-length edges, no zero-area faces. Pinned in Task 2 (a trace ending on or passing through a vertex reports `kind == "vert"`) and Task 7 (two-row strip at width 0.5 adds no vertices or faces and selects the mid loop).
2. **Hidden faces next to the chain** must never be cut. A chain whose side face is hidden is skipped with a warning. Pinned in Task 6.
3. **Redo after orbiting the view must not flip the side.** `execute()` uses the stored `chain_sides`, never the current view. Pinned in Task 7 (the same props give the same result; `"-"` gives the other side).
4. **A chain on an open mesh border** with no face on the chosen side is skipped with a warning, and the other chains still cut. Pinned in Task 6 and Task 7.
5. **Slightly non-planar quads in the band.** New vertices must lie on the actual mesh surface, not on a best-fit plane. Pinned in Task 2 (3D points come from barycentric coordinates on the face's own triangles) and Task 7 (lifted corner, every new vertex within 1e-6 of the original surface).

---

## File Structure

- `utils/smart_edge_slide_core.py` — **create.** Band model, wedges, surface tracing, placement, `Slider` (`solve`, `limit`, `snap_width`), screen-side helpers.
- `tests/test_smart_edge_slide_core.py` — **create.** Pytest suite for the core, with synthetic bands.
- `operators/mesh_smart_edge_slide_bridge.py` — **create.** bmesh to band (chains, sides, steps, lids), step projection, `apply_cut`, preview layers.
- `operators/mesh_smart_edge_slide.py` — **create.** `IOPS_OT_smart_edge_slide`: props, `execute()`, modal, HUD, preview.
- `tests/blender/test_smart_edge_slide.py` — **create.** Headless bridge and operator tests.
- `__init__.py`, `prefs/hotkeys_default.py`, `ui/iops_pie_edit.py`, `ui/iops_pie_menu.py` — **modify** (registration and access).
- `tests/smoke_register.py` — **modify** (assert the operator registers).
- `docs/operators/op_mesh_smart_edge_slide.md` — **create.**
- `docs/operators.md`, `docs/index.md`, `mkdocs.yml`, `docs/ui/ui_pies.md` — **modify.**
- `utils/uv_stripe_core.py` — **create** (Task 10). Pure strip unwrap: rectangle layout, seam choice, Fit and In Place placement.
- `tests/test_uv_stripe_core.py` — **create** (Task 10).
- `operators/uv_stripe_bridge.py` — **create** (Task 11). UV context capture, writing strip UVs into the active UV layer.
- `operators/mesh_smart_inset.py`, `docs/operators/op_mesh_smart_inset.md` (CRLF), `tests/blender/test_smart_inset_uv_stripe.py` — **modify / create** (Task 12).

## Shared fixtures

Tasks 1–5 use these bands in `tests/test_smart_edge_slide_core.py`. All points are in the z = 0 plane unless noted. Faces list vertex ids; the core never relies on winding.

| Name | verts (id: xyz) | faces (id: verts) | chain | side_faces |
|---|---|---|---|---|
| `strip()` | 0:(0,0,0) 1:(1,0,0) 2:(2,0,0) 3:(3,0,0) 4:(0,1,0) 5:(1,1,0) 6:(2,1,0) 7:(3,1,0) | 0:(0,1,5,4) 1:(1,2,6,5) 2:(2,3,7,6) | [0,1,2,3] open | [0,1,2] |
| `strip2()` | `strip()` with rows at y = 0, 0.5, 1: 0–3 bottom, 4–7 at y=0.5, 8–11 at y=1 | 0:(0,1,5,4) 1:(1,2,6,5) 2:(2,3,7,6) 3:(4,5,9,8) 4:(5,6,10,9) 5:(6,7,11,10) | [0,1,2,3] open | [0,1,2] |
| `box_corner()` | 0:(0,0,1) 1:(1,0,1) 2:(1,1,1) 3:(0,0,0) 4:(1,0,0) 5:(1,1,0) | 0:(3,4,1,0) 1:(4,5,2,1) | [0,1,2] open | [0,1] |
| `bent()` | 0:(0,0,0) 1:(1,0,0) 2:(2,0.5,0) 3:(0,2,0) 4:(1,2,0) 5:(2,2.5,0) | 0:(0,1,4,3) 1:(1,2,5,4) | [0,1,2] open | [0,1] |
| `fan()` | 0:(0,0,0) 1:(1,0,0) 2:(2,0,0) 3:(0,1,0) 4:(0.5,1,0) 5:(1.4,1,0) 6:(2,1,0) | 0:(0,1,4,3) 1:(1,5,4) 2:(1,2,6,5) | [0,1,2] open | [0,2] |
| `ngon_diag()` | 0:(0,0,0) 1:(2,0,0) 2:(4,0,0) 3:(4,0.5,0) 4:(4,1,0) 5:(0,1,0) | 0:(0,1,3,4,5) 1:(1,2,3) | [0,1,2] open | [0,1] |
| `sliver()` | 0:(0,0,0) 1:(1,-0.1,0) 2:(2,0,0) 3:(2,1,0) 4:(0,1,0) | 0:(0,1,2) 1:(0,2,3,4) | [0,1,2] open | [0,0] |
| `ring()` | 0:(-1,-1,0) 1:(1,-1,0) 2:(1,1,0) 3:(-1,1,0) 4:(-2,-2,0) 5:(2,-2,0) 6:(2,2,0) 7:(-2,2,0) | 0:(0,1,5,4) 1:(1,2,6,5) 2:(2,3,7,6) 3:(3,0,4,7) | [0,1,2,3] closed | [0,1,2,3] |
| `end_slide()` | 0:(0,0,0) 1:(2,0,0) 2:(2,0.1,0) 3:(1,1,0) 4:(0,1,0) | 0:(0,1,2,3,4) | [0,1] open | [0] |
| `u_turn()` | 0:(0,0,0) 1:(2,0,0) 2:(2.1414214,0.1414214,0) 3:(2.1414214,1.1414214,0) 4:(0,1.1414214,0) | 0:(0,1,2,3,4) | [0,1,2,3] open | [0,0,0] |

---

### Task 1: Core — band model and wedges

**Files:**
- Create: `utils/smart_edge_slide_core.py`
- Test: `tests/test_smart_edge_slide_core.py`

**Interfaces:**
- Produces:
  - `Vec2 = tuple[float, float]` and `Vec3 = tuple[float, float, float]`; all constants from Global Constraints.
  - `@dataclass class Band: verts: dict[int, Vec3]; faces: dict[int, tuple[int, ...]]; chain: list[int]; closed: bool; side_faces: list[int]`.
    - `side_faces[i]` is the face on the cut side of edge `(chain[i], chain[(i+1) % n])`. Its length is `len(chain) - 1` for open chains and `len(chain)` for closed ones.
    - `__post_init__` raises `ValueError` when a side face does not contain its chain edge.
  - `@dataclass(frozen=True) class Rail: far: int; angle: float; length: float; border: bool`.
  - `@dataclass class Wedge: k: int; theta: float; faces: list[int]; rails: list[Rail]`.
  - `def wedge(band: Band, k: int) -> Wedge`.
- **Angle convention** (every later task uses it): in the wedge of `chain[k]`, angle 0 is the direction to `chain[k+1]`. Angles grow through the side faces up to `theta`, the direction to `chain[k-1]`.
  - At the first vertex of an open chain, `theta` is the end-border edge.
  - At the last vertex, angle 0 is the end-border edge.
  - `Wedge.faces` lists the side faces in that sweep order.
  - `Wedge.rails` holds the interior edges between consecutive wedge faces, ascending by angle, plus the end-border edge with `border=True`.
  - `theta` is the sum of the side faces' corner angles at `chain[k]` (the intrinsic angle). The sweep moves from face to face across edges that share `chain[k]`, using only faces in `band.faces`.

- [ ] **Step 1: Create the branch and commit the design docs**

```bash
git checkout -b feat/smart-edge-slide
git add docs/superpowers/specs/2026-11-04-smart-edge-slide-design.md docs/superpowers/plans/2026-11-04-smart-edge-slide.md
git commit -m "docs(smart-edge-slide): design and implementation plan"
```

- [ ] **Step 2: Write the failing tests**

Add the fixture builders from *Shared fixtures* (as plain functions returning `Band`, floats everywhere), then:

```python
def test_wedge_flat_strip_interior():
    w = wedge(strip(), 1)
    assert w.theta == pytest.approx(math.pi)
    assert w.faces == [1, 0]
    assert len(w.rails) == 1
    r = w.rails[0]
    assert (r.far, r.border) == (5, False)
    assert r.angle == pytest.approx(math.pi / 2) and r.length == pytest.approx(1.0)

def test_wedge_open_ends_carry_border_rails():
    w0, w3 = wedge(strip(), 0), wedge(strip(), 3)
    assert w0.theta == pytest.approx(math.pi / 2)
    assert w0.rails[-1].far == 4 and w0.rails[-1].border and w0.rails[-1].angle == pytest.approx(math.pi / 2)
    assert w3.theta == pytest.approx(math.pi / 2)
    assert w3.rails[0].far == 7 and w3.rails[0].border and w3.rails[0].angle == pytest.approx(0.0)

def test_wedge_box_corner_unfolds_to_straight():
    w = wedge(box_corner(), 1)
    assert w.theta == pytest.approx(math.pi)
    assert [r.far for r in w.rails] == [4]
    assert w.rails[0].angle == pytest.approx(math.pi / 2)

def test_wedge_ngon_shallow_rail():
    w = wedge(ngon_diag(), 1)
    assert w.theta == pytest.approx(math.pi)
    assert [r.far for r in w.rails] == [3]
    assert w.rails[0].angle == pytest.approx(math.atan2(0.5, 2.0))
    assert w.rails[0].length == pytest.approx(math.hypot(2.0, 0.5))

def test_wedge_fan_two_rails_sorted():
    w = wedge(fan(), 1)
    assert [r.far for r in w.rails] == [5, 4]
    assert w.rails[0].angle == pytest.approx(math.atan2(1.0, 0.4))
    assert w.rails[1].angle == pytest.approx(math.atan2(1.0, -0.5))
    assert w.faces == [2, 1, 0]

def test_wedge_sliver_has_no_rail():
    w = wedge(sliver(), 1)
    assert w.rails == []
    assert w.theta == pytest.approx(math.radians(168.5788137), abs=1e-6)

def test_band_rejects_side_face_without_its_edge():
    b = strip()
    with pytest.raises(ValueError):
        Band(verts=b.verts, faces=b.faces, chain=b.chain, closed=False, side_faces=[1, 1, 2])
```

- [ ] **Step 3: Run the tests to make sure they fail**

Run: `python -m pytest tests/test_smart_edge_slide_core.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'utils.smart_edge_slide_core'`.

- [ ] **Step 4: Implement `Band`, `Rail`, `Wedge` and `wedge()`** in `utils/smart_edge_slide_core.py`.

Corner angles come from 3D vectors: `acos(clamp(dot(u, v)))` with `u` and `v` the unit edge directions at the vertex. Sweep from the outgoing chain edge's side face to the incoming one by stepping across the face edges that share `chain[k]`. For open ends, continue to the band border.

- [ ] **Step 5: Run the tests to make sure they pass**

Run: `python -m pytest tests/test_smart_edge_slide_core.py -q`
Expected: PASS (7 passed).

- [ ] **Step 6: Commit**

```bash
git add utils/smart_edge_slide_core.py tests/test_smart_edge_slide_core.py
git commit -m "feat(smart-edge-slide): core band model and wedge development"
```

---

### Task 2: Core — straight traces across band faces

**Files:**
- Modify: `utils/smart_edge_slide_core.py`
- Test: `tests/test_smart_edge_slide_core.py`

**Interfaces:**
- Consumes: `Band`, `wedge()`.
- Produces:
  - `@dataclass(frozen=True) class SurfacePoint: kind: str; face: int; co: Vec3; vert: int | None = None; edge: tuple[int, int] | None = None; t: float = 0.0`.
    - `kind` is `"vert"`, `"edge"` or `"face"`.
    - For `"edge"`, `co == lerp(verts[a], verts[b], t)` with `edge == (a, b)` stored in sorted vertex-id order.
  - `@dataclass class Trace: crossings: list[SurfacePoint]; end: SurfacePoint; blocked: bool; end_xy: Vec2`.
    - It also carries a private `_face: int` and `_xf` (the end face's 2D development transform) so a later trace can continue from its end.
  - `def trace_from_vertex(band: Band, k: int, angle: float, length: float) -> Trace`. The development is the wedge frame of `chain[k]`: `chain[k]` at the origin, angle 0 along +x.
  - `def trace_segment(band: Band, k: int, a: Trace, b: Trace) -> Trace`:
    - `a` was traced from `chain[k]` and `b` from `chain[k + 1]` (wrapping for closed chains).
    - It maps `b.end_xy` into chain edge `k`'s frame (the wedge frame of `chain[k]`) and traces straight from `a.end` to it.
    - It raises `ValueError("inconsistent development")` when the end misses `b.end` by more than 1e-6.
- **Trace rules:**
  - Points within `1e-9 × band scale` of a vertex snap to `kind="vert"`; within that distance of an edge, to `kind="edge"`.
  - A trace that passes exactly through a vertex reports one `"vert"` crossing, not two edge crossings. It continues in the face around that vertex whose corner contains the travel direction.
  - Leaving the band, across a border edge or a chain edge, sets `blocked=True`, and `end` is the exit point.
  - 3D positions inside a face come from barycentric coordinates in the face's own triangulation (2D tessellation in the face frame mapped back to the face's 3D corners), so non-planar faces keep points on their surface.

- [ ] **Step 1: Write the failing tests**

```python
def test_trace_crosses_one_rail():
    tr = trace_from_vertex(strip(), 0, math.atan2(0.5, 1.5), math.hypot(1.5, 0.5))
    assert [(c.kind, c.edge) for c in tr.crossings] == [("edge", (1, 5))]
    assert tr.crossings[0].t == pytest.approx(1 / 3)
    assert tr.end.kind == "face" and tr.end.face == 1
    assert tr.end.co == pytest.approx((1.5, 0.5, 0.0))
    assert not tr.blocked

def test_trace_unfolds_across_box_corner():
    tr = trace_from_vertex(box_corner(), 0, math.atan2(0.3, 1.5), math.hypot(1.5, 0.3))
    assert tr.crossings[0].edge == (1, 4) and tr.crossings[0].t == pytest.approx(0.2)
    assert tr.crossings[0].co == pytest.approx((1.0, 0.0, 0.8))
    assert tr.end.co == pytest.approx((1.0, 0.5, 0.7))

def test_trace_blocked_at_border():
    tr = trace_from_vertex(strip(), 1, math.atan2(1.0, 0.5), 3.0)
    assert tr.blocked
    assert tr.end.kind == "edge" and tr.end.edge == (5, 6) and tr.end.t == pytest.approx(0.5)

def test_trace_ends_on_vertex():                      # Review Focus 1
    tr = trace_from_vertex(strip2(), 0, math.atan2(0.5, 1.0), math.hypot(1.0, 0.5))
    assert tr.end.kind == "vert" and tr.end.vert == 5

def test_trace_through_vertex_is_one_crossing():      # Review Focus 1
    tr = trace_from_vertex(strip2(), 0, math.atan2(1.0, 2.0), math.hypot(2.0, 1.0))
    assert [(c.kind, c.vert) for c in tr.crossings] == [("vert", 5)]

def test_trace_on_non_planar_face_stays_on_surface():  # Review Focus 5
    b = strip()
    b.verts[4] = (0.0, 1.0, 0.05)
    # (0.3, 0.6) is on vertex 4's side of both possible quad diagonals
    tr = trace_from_vertex(b, 1, math.atan2(0.6, -0.7), math.hypot(0.7, 0.6))
    x, y, z = tr.end.co
    assert (x, y) == pytest.approx((0.3, 0.6), abs=1e-3)
    assert 0.0 < z < 0.05    # on face 0's triangles, not on a flat fit

def test_trace_segment_meets_partner():
    b = bent()
    a = trace_from_vertex(b, 1, math.radians(40.0), 0.5)    # inside face 1, off the rail
    w2 = wedge(b, 2)
    c = trace_from_vertex(b, 2, w2.theta / 2, 0.5)
    seg = trace_segment(b, 1, a, c)
    assert seg.end.co == pytest.approx(c.end.co, abs=1e-6)
    assert not seg.blocked
```

- [ ] **Step 2: Run the tests to make sure they fail**

Run: `python -m pytest tests/test_smart_edge_slide_core.py -q -k trace`
Expected: FAIL with `ImportError` for `trace_from_vertex`.

- [ ] **Step 3: Implement the trace types, `trace_from_vertex` and `trace_segment`.**

Keep a current face and its 2D-to-development rigid transform. For the segment from the current point to the target, find the first exit edge (parameter in `(EPS, 1]`), excluding the entry edge. Then unfold the neighbour face across the shared edge and continue. A target inside the current face ends the trace.

- [ ] **Step 4: Run the tests to make sure they pass**

Run: `python -m pytest tests/test_smart_edge_slide_core.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add utils/smart_edge_slide_core.py tests/test_smart_edge_slide_core.py
git commit -m "feat(smart-edge-slide): surface traces across band faces"
```

---

### Task 3: Core — vertex placement and solve for closed chains

**Files:**
- Modify: `utils/smart_edge_slide_core.py`
- Test: `tests/test_smart_edge_slide_core.py`

**Interfaces:**
- Consumes: `wedge`, `trace_from_vertex`, `trace_segment`.
- Produces:
  - `class OutOfRoom(Exception)`, raised when any placement or segment trace is blocked.
  - `@dataclass class Placement: trace: Trace; rail: Rail | None; width_error: float`.
  - `@dataclass class Cut: points: list[SurfacePoint]; anchors: list[int | None]; connectors: list[tuple[int, int]]; width: float; clamped: bool`.
    - `points` is the new loop in chain order (a closed loop wraps). Between consecutive anchors it holds that segment's crossings.
    - `anchors[k]` is the index in `points` of `chain[k]`'s new vertex.
    - `connectors` holds pairs `(chain vertex id, points index)` for the variant-B edges to add.
  - `class Slider` with `__init__(self, band: Band)`, `place(self, k: int, width: float, *, exact: bool = False) -> Placement` and `solve(self, width: float, *, exact: bool = False, collapse: bool = False) -> Cut`.
    - In this task, `solve` supports closed chains and raises `NotImplementedError` for open ones (Task 4).
    - `collapse` is accepted and ignored until Task 5.
    - `width <= EPS` returns an empty `Cut` (`points=[]`, `anchors=[None] * n`, `connectors=[]`, `width=0.0`, `clamped=False`).
- **Placement rules** (`w` = width, `θ` = `wedge.theta`):
  - **Accepted rails:** non-border rails with `|rail.angle - θ/2| <= RAIL_MAX_DEV`. Take the one closest to `θ/2`.
  - **On a rail at angle β:** `t = 2w / (sin β + sin(θ - β))` and `width_error = max(|t·sin β - w|, |t·sin(θ - β) - w|)`. The point is `trace_from_vertex(k, β, t)`. If `t > rail.length + EPS`, raise `OutOfRoom`.
  - **Miter:** `trace_from_vertex(k, θ/2, w / sin(θ/2))`, with `width_error = 0`. Used when no rail is accepted, or when `exact` and `width_error > EXACT_TOL·w`.
- **Connector rule:** add `(chain[k], anchors[k])` only when the anchor is a miter (`rail is None`), its trace has no crossings, and it is not blocked. Rail anchors need no connector, because the rail piece is the edge.

- [ ] **Step 1: Write the failing tests**

```python
def test_place_on_perpendicular_rail_is_exact():
    p = Slider(strip()).place(1, 0.25)
    assert p.rail.far == 5 and p.width_error == pytest.approx(0.0)
    assert p.trace.end.co == pytest.approx((1.0, 0.25, 0.0)) and p.trace.end.kind == "edge"

def test_place_bent_default_uses_rail_with_small_error():
    p = Slider(bent()).place(1, 0.2)
    assert p.rail.far == 4
    assert p.trace.end.co == pytest.approx((1.0, 0.2111456, 0.0), abs=1e-6)
    assert p.width_error == pytest.approx(0.0111456, abs=1e-6)

def test_place_bent_exact_uses_miter():
    p = Slider(bent()).place(1, 0.2, exact=True)
    assert p.rail is None
    assert p.trace.end.co == pytest.approx((0.9527864, 0.2, 0.0), abs=1e-6)

def test_place_fan_picks_rail_nearest_bisector():
    p = Slider(fan()).place(1, 0.3)
    assert p.rail.far == 5
    assert p.trace.end.co == pytest.approx((1.12, 0.3, 0.0), abs=1e-6)

def test_place_rejects_shallow_diagonal():
    p = Slider(ngon_diag()).place(1, 0.25)
    assert p.rail is None and p.trace.crossings == []
    assert p.trace.end.kind == "face" and p.trace.end.face == 0
    assert p.trace.end.co == pytest.approx((2.0, 0.25, 0.0))

def test_place_sliver_miter_crosses_chord():
    p = Slider(sliver()).place(1, 0.2)
    assert [c.edge for c in p.trace.crossings] == [(0, 2)]
    assert p.trace.end.face == 1
    assert p.trace.end.co == pytest.approx((1.0, 0.1009975, 0.0), abs=1e-6)

def test_solve_ring_closed():
    cut = Slider(ring()).solve(0.5)
    assert [pt.co for pt in cut.points] == [pytest.approx(c) for c in
        [(-1.5, -1.5, 0.0), (1.5, -1.5, 0.0), (1.5, 1.5, 0.0), (-1.5, 1.5, 0.0)]]
    assert cut.anchors == [0, 1, 2, 3] and cut.connectors == [] and not cut.clamped

def test_solve_tiny_width_is_empty():
    cut = Slider(ring()).solve(0.0)
    assert cut.points == [] and cut.anchors == [None] * 4
```

- [ ] **Step 2: Run the tests to make sure they fail**

Run: `python -m pytest tests/test_smart_edge_slide_core.py -q -k "place or solve"`
Expected: FAIL with `ImportError` for `Slider`.

- [ ] **Step 3: Implement `OutOfRoom`, `Placement`, `Cut`, `Slider.place` and the closed-chain `Slider.solve`.**

For every edge `k`, `solve` takes `trace_segment(k, place(k), place(k+1))`. It appends the crossings and then the partner anchor, and deduplicates points that coincide (vert or edge ids equal, or `co` within 1e-9).

- [ ] **Step 4: Run the tests to make sure they pass**

Run: `python -m pytest tests/test_smart_edge_slide_core.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add utils/smart_edge_slide_core.py tests/test_smart_edge_slide_core.py
git commit -m "feat(smart-edge-slide): rail and miter placement, closed-chain solve"
```

---

### Task 4: Core — open-chain ends sliding along the border

**Files:**
- Modify: `utils/smart_edge_slide_core.py`
- Test: `tests/test_smart_edge_slide_core.py`

**Interfaces:**
- Consumes: Task 3's `Slider`, `Cut`, `OutOfRoom`; the border rails from `wedge()`.
- Produces: `Slider.solve` works for open chains. A private `Slider._end(self, at_start: bool, width: float) -> Trace` returns the end point as a `Trace` that `trace_segment` accepts.
- **End rule:**
  - The end point is the intersection of the end chain edge's offset line (at distance `w`) with the border path that starts at the end vertex. That path is the end wedge's border rail, then the band-border edges that follow it.
  - Each border edge is developed into the end wedge frame by rotating about its start vertex by the band-side corner angle between the previous border edge and this one.
  - The first edge hit wins. If the path ends first, raise `OutOfRoom`.
  - The point is `kind="edge"` (or `"vert"` exactly at a border vertex) on that border edge.

- [ ] **Step 1: Write the failing tests**

```python
def _cos(cut): return [pt.co for pt in cut.points]

def test_solve_strip_open():
    cut = Slider(strip()).solve(0.25)
    assert _cos(cut) == [pytest.approx((x, 0.25, 0.0)) for x in (0.0, 1.0, 2.0, 3.0)]
    assert cut.anchors == [0, 1, 2, 3] and cut.connectors == []

def test_solve_ngon_diagonal_crossing_and_connector():
    cut = Slider(ngon_diag()).solve(0.25)
    assert _cos(cut) == [pytest.approx(c) for c in
        [(0.0, 0.25, 0.0), (2.0, 0.25, 0.0), (3.0, 0.25, 0.0), (4.0, 0.25, 0.0)]]
    assert [pt.kind for pt in cut.points] == ["edge", "face", "edge", "edge"]
    assert cut.points[2].edge == (1, 3) and cut.points[2].t == pytest.approx(0.5)
    assert cut.anchors == [0, 1, 3]
    assert cut.connectors == [(1, 1)]

def test_solve_sliver_skips_connector_that_crosses_chord():
    cut = Slider(sliver()).solve(0.2)
    assert _cos(cut) == [pytest.approx(c, abs=1e-6) for c in
        [(0.0, 0.2009975, 0.0), (1.0, 0.1009975, 0.0), (2.0, 0.2009975, 0.0)]]
    assert cut.connectors == []

def test_end_slides_past_short_end_edge():
    cut = Slider(end_slide()).solve(0.3)
    end = cut.points[-1]
    assert end.kind == "edge" and end.edge == (2, 3)
    assert end.t == pytest.approx(0.2222222, abs=1e-6)
    assert end.co == pytest.approx((1.7777778, 0.3, 0.0), abs=1e-6)

def test_end_on_short_end_edge():
    end = Slider(end_slide()).solve(0.05).points[-1]
    assert end.edge == (1, 2) and end.t == pytest.approx(0.5)

def test_bent_default_and_exact():
    d = Slider(bent()).solve(0.2)
    assert _cos(d) == [pytest.approx(c, abs=1e-6) for c in
        [(0.0, 0.2, 0.0), (1.0, 0.2111456, 0.0), (2.0, 0.7236068, 0.0)]]
    e = Slider(bent()).solve(0.2, exact=True)
    assert _cos(e) == [pytest.approx(c, abs=1e-6) for c in
        [(0.0, 0.2, 0.0), (0.9527864, 0.2, 0.0), (1.0, 0.2236068, 0.0), (2.0, 0.7236068, 0.0)]]
```

- [ ] **Step 2: Run the tests to make sure they fail**

Run: `python -m pytest tests/test_smart_edge_slide_core.py -q -k "solve or end_ or bent_default"`
Expected: FAIL with `NotImplementedError`.

- [ ] **Step 3: Implement `Slider._end` and the open-chain branch of `Slider.solve`.**

- [ ] **Step 4: Run the tests to make sure they pass**

Run: `python -m pytest tests/test_smart_edge_slide_core.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add utils/smart_edge_slide_core.py tests/test_smart_edge_slide_core.py
git commit -m "feat(smart-edge-slide): open-chain ends slide along the band border"
```

---

### Task 5: Core — limits, clamp, collapse, snapping, screen-side helpers

**Files:**
- Modify: `utils/smart_edge_slide_core.py`
- Test: `tests/test_smart_edge_slide_core.py`

**Interfaces:**
- Consumes: `Slider.solve`, `OutOfRoom`.
- Produces:
  - `Slider.limit(self, *, exact: bool = False, collapse: bool = False) -> float`, cached per `(exact, collapse)`.
  - `Slider.solve` now clamps: `Cut.width = min(width, limit)` and `Cut.clamped = width > limit + EPS`.
  - `Slider.snap_width(self, target: SurfacePoint, *, exact: bool = False) -> float | None`.
  - `def positive_side(chain_xy: list[Vec2], plus_xy: Vec2 | None, minus_xy: Vec2 | None, closed: bool) -> int`, which returns `+1` or `-1`.
  - `def nearest_chain(chains_xy: list[list[Vec2]], closed: list[bool], mouse: Vec2) -> int`.
- **Limits and collapse:**
  - **Shrink event.** A shrink event is the width at which a new-loop segment's length, measured along its chain edge in that edge's frame, reaches 0.
  - **`collapse=False`.** `limit` is the largest width at which `solve` raises no `OutOfRoom` and has no shrink event. Find it by bisection on `[0, 4 × band bbox diagonal]` with `LIMIT_ITERS` iterations.
  - **`collapse=True`.** Shrink events no longer limit. In `solve`, a segment that would shrink is dropped: its two chain vertices share one new vertex, placed at the intersection of the neighbouring segments' offset lines (developed in the dropped edge's frame, located with a trace from the dropped edge's start vertex). Both anchors point to it. Repeat until no segment shrinks. Only `OutOfRoom` limits.
- **Snapping:** bisection over `w ∈ (0, limit]` (`SNAP_ITERS` iterations) of the signed in-surface offset of `target` from the new loop. Use the loop segment nearest to `target`; the offset is positive when `target` lies beyond the loop. Return `None` when there is no sign change.
- **Screen side:**
  - **Open chains:** the side whose projected band centroid has the larger screen x.
  - **Closed chains:** the side whose centroid lies inside the projected chain polygon.
  - **Missing side:** if one side is `None`, return the other. When neither side wins, return `+1`.

- [ ] **Step 1: Write the failing tests**

```python
def test_limits_rail_length_and_ring():
    assert Slider(strip()).limit() == pytest.approx(1.0, abs=1e-6)
    assert Slider(ring()).limit() == pytest.approx(1.0, abs=1e-6)

def test_u_turn_clamps_at_shrink_event():
    s = Slider(u_turn())
    assert s.limit() == pytest.approx(0.2414214, abs=1e-6)
    cut = s.solve(0.3)
    assert cut.clamped and cut.width == pytest.approx(0.2414214, abs=1e-6)

def test_u_turn_collapse_drops_short_segment():
    s = Slider(u_turn())
    assert s.limit(collapse=True) == pytest.approx(1.1414214, abs=1e-6)
    cut = s.solve(0.3, collapse=True)
    assert [pt.co for pt in cut.points] == [pytest.approx(c, abs=1e-6) for c in
        [(0.0, 0.3, 0.0), (1.8414214, 0.3, 0.0), (1.8414214, 1.1414214, 0.0)]]
    assert cut.anchors == [0, 1, 1, 2] and not cut.clamped

def test_snap_to_border_vertex():
    sp = SurfacePoint(kind="vert", face=0, co=(2.0, 0.1, 0.0), vert=2)
    assert Slider(end_slide()).snap_width(sp) == pytest.approx(0.1, abs=1e-6)

def test_snap_on_rail_default_and_exact():
    sp = SurfacePoint(kind="edge", face=0, co=(1.0, 0.3, 0.0), edge=(1, 4), t=0.15)
    s = Slider(bent())
    assert s.snap_width(sp) == pytest.approx(0.2841641, abs=1e-6)
    assert s.snap_width(sp, exact=True) == pytest.approx(0.2683282, abs=1e-6)

def test_snap_outside_band_is_none():
    sp = SurfacePoint(kind="face", face=0, co=(0.5, -0.5, 0.0))
    assert Slider(strip()).snap_width(sp) is None

def test_positive_side_open_is_screen_right():
    chain = [(0.0, 0.0), (0.0, 10.0)]
    assert positive_side(chain, (5.0, 5.0), (-5.0, 5.0), False) == 1
    assert positive_side(chain, (-5.0, 5.0), (5.0, 5.0), False) == -1
    assert positive_side(chain, None, (5.0, 5.0), False) == -1

def test_positive_side_closed_is_inside():
    sq = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)]
    assert positive_side(sq, (5.0, 5.0), (20.0, 5.0), True) == 1
    assert positive_side(sq, (20.0, 5.0), (5.0, 5.0), True) == -1
    assert positive_side(sq, (20.0, 5.0), (30.0, 5.0), True) == 1

def test_nearest_chain():
    a = [(0.0, 0.0), (10.0, 0.0)]; b = [(0.0, 5.0), (10.0, 5.0)]
    assert nearest_chain([a, b], [False, False], (3.0, 4.0)) == 1
```

- [ ] **Step 2: Run the tests to make sure they fail**

Run: `python -m pytest tests/test_smart_edge_slide_core.py -q -k "limit or u_turn or snap or positive or nearest"`
Expected: FAIL (`AttributeError: 'Slider' object has no attribute 'limit'`).

- [ ] **Step 3: Implement `limit`, clamping in `solve`, collapse, `snap_width`, `positive_side` and `nearest_chain`.**

- [ ] **Step 4: Run the full core suite**

Run: `python -m pytest tests/test_smart_edge_slide_core.py -q && uvx ruff@0.12.0 check utils/smart_edge_slide_core.py tests/test_smart_edge_slide_core.py`
Expected: all tests pass; ruff reports no errors.

- [ ] **Step 5: Commit**

```bash
git add utils/smart_edge_slide_core.py tests/test_smart_edge_slide_core.py
git commit -m "feat(smart-edge-slide): limits, clamp, collapse, snapping and side helpers"
```

---

### Task 6: Bridge — chains, sides, bands and step lids

**Files:**
- Create: `operators/mesh_smart_edge_slide_bridge.py`
- Create: `tests/blender/test_smart_edge_slide.py`

**Interfaces:**
- Consumes: `core.Band`, `core.wedge`.
- Produces:
  - `@dataclass class ChainSrc: verts: list[BMVert]; closed: bool`.
  - `def collect_chains(bm) -> tuple[list[ChainSrc], list[str]]`.
    - Collects selected, visible edges and splits them into connected components.
    - A component with a vertex of selected-degree ≥ 3 is skipped with the warning `"branching selection"`.
    - **Deterministic order** (redo stability):
      - components sorted by their smallest vertex index;
      - open chains start at the end vertex with the smaller index;
      - closed chains start at their smallest-index vertex and go toward its smaller-index neighbour.
  - `@dataclass class StepSpan: lid: int; first: int; last: int; normal: Vector; region: list[BMFace]`.
  - `@dataclass class BandBuild: band: core.Band; chain: list[BMVert]; faces: dict[int, BMFace]; steps: list[StepSpan]`.
  - `def build_band(bm, src: ChainSrc, side: int) -> tuple[BandBuild | None, str | None]`.
    - **Side faces:** `side=+1` means faces whose loop runs the chain edge in chain order (`loop.vert is a and loop.link_loop_next.vert is b`); `side=-1` means the other face.
    - **Band:** the side faces of all chain edges, plus the wedge faces around each chain vertex on that side. Hidden faces never join it.
    - **Real ids:** real faces use `BMFace.index` (call `bm.faces.ensure_lookup_table()` and `index_update()` first). Lids use `-(n + 1)`.
    - **Failures** return `(None, msg)`. A missing or hidden side face gives `"chain edge without a visible face on that side"`. A step with no flank rail gives `"step without a flank rail"`.
- **Step rule** (spec, *Steps*):
  - `away_i` is the unit in-face direction of `side_faces[i]` perpendicular to chain edge `i`, pointing into the face.
  - A maximal run of edges `a..b-1` is a step when both flanks `a-1` and `b` exist and are not steps, `cos(away_{a-1}, away_b) >= STEP_AGREE_COS`, and every edge in the run has `cos(away_j, normalize(away_{a-1} + away_b)) < STEP_DIFFER_COS`.
  - **Lid polygon:** `(P_a … P_b, R_b, R_a)`, where `R_a` is the far vertex of the edge of `side_faces[a-1]` at `P_a` other than chain edge `a-1`, and `R_b` is the same for `side_faces[b]` at `P_b`.
  - The lid replaces the run's side faces and the wedge faces between the flank rails; `side_faces[a..b-1] = lid`.
  - **Region:** flood fill from the replaced faces. Do not cross chain edges or flank rails. Keep faces whose vertices all project, along `normal = normalize(n_{flank a-1} + n_{flank b})`, inside the lid polygon (tolerance 1e-5) and within `2 × max(|R_a - P_a|, |R_b - P_b|)` of the lid plane.
- **Test mesh builders** in `tests/blender/test_smart_edge_slide.py`, using the same structure as `tests/blender/test_cursor_bisect_delimit.py` (`enable_addon()`, plain `test_*` functions, a runner that exits non-zero on failure):
  - `_strip(rows=1)`: the core fixtures `strip()` / `strip2()` as a bmesh.
  - `_ngon_diag()` and `_sliver()`: the core fixtures.
  - `_box_corner()`.
  - `_pocket()`:
    - chain (0,0,0)→(1,0,0)→(2,0,0)→(3,0,0);
    - ceiling quads at z=0 for x∈[0,1] and x∈[2,3], y∈[0,2];
    - pocket at x∈[1,2], y∈[0,2]: lip (1,0,0)-(2,0,0)-(2,0,0.15)-(1,0,0.15); sides at x=1 and x=2; top at z=0.15; far wall at y=2;
    - slanted faces on the other side: (x,0,0)→(x,-1,-1) for x∈[0,1],[1,2],[2,3].
  - Every builder creates chain vertices first, in chain order, so `collect_chains` starts at the first one.
  - Wind every builder face so that the side the tests cut (strip, n-gon and sliver: +y; box corner: the walls; pocket: the ceiling and lip) runs each chain edge in chain order. That side is `+1`.
  - The test file imports `from InteractionOps.operators import mesh_smart_edge_slide_bridge as bridge` and `from InteractionOps.utils import smart_edge_slide_core as core` inside `enable_addon()`, as the cursor-bisect test does.

- [ ] **Step 1: Write the failing headless tests**

```python
def test_collect_chains_orders_and_rejects_branching():
    bm = _strip(); _select_chain(bm, [0, 1, 2, 3])
    chains, warns = bridge.collect_chains(bm)
    assert [[v.index for v in c.verts] for c in chains] == [[0, 1, 2, 3]] and warns == []
    bm.edges.get((bm.verts[1], bm.verts[5])).select = True       # T-junction
    chains, warns = bridge.collect_chains(bm)
    assert chains == [] and warns == ["branching selection"]

def test_build_band_strip_side():
    bm = _strip(); src = _chain(bm, [0, 1, 2, 3])
    build, err = bridge.build_band(bm, src, +1)
    assert err is None and len(build.band.side_faces) == 3 and build.steps == []
    build, err = bridge.build_band(bm, src, -1)
    assert build is None and err == "chain edge without a visible face on that side"   # Review Focus 4

def test_hidden_side_face_skips_chain():                                              # Review Focus 2
    bm = _strip(); bm.faces[1].hide = True
    build, err = bridge.build_band(bm, _chain(bm, [0, 1, 2, 3]), +1)
    assert build is None and err == "chain edge without a visible face on that side"

def test_box_corner_has_no_step():
    bm = _box_corner()
    build, _ = bridge.build_band(bm, _chain(bm, [0, 1, 2]), +1)
    assert build.steps == []

def test_pocket_lip_becomes_lid():
    bm = _pocket(); build, err = bridge.build_band(bm, _chain(bm, [0, 1, 2, 3]), +1)
    assert err is None and len(build.steps) == 1
    st = build.steps[0]
    assert (st.first, st.last) == (1, 2) and build.band.side_faces[1] == st.lid < 0
    assert {tuple(round(c, 3) for c in f.calc_center_median()) for f in st.region} >= {
        (1.5, 0.0, 0.075), (1.0, 1.0, 0.075), (2.0, 1.0, 0.075), (1.5, 1.0, 0.15)}
    assert tuple(round(c, 6) for c in st.normal) in {(0.0, 0.0, 1.0), (0.0, 0.0, -1.0)}
```

(Helpers `_select_chain` and `_chain(bm, ids) -> ChainSrc` live in the test file.)

- [ ] **Step 2: Run them to make sure they fail**

Run: the headless command from Global Constraints.
Expected: exit code 1, with `ModuleNotFoundError: No module named 'InteractionOps.operators.mesh_smart_edge_slide_bridge'`.

- [ ] **Step 3: Implement `ChainSrc`, `collect_chains`, `StepSpan`, `BandBuild` and `build_band`.**

- [ ] **Step 4: Run the headless tests to make sure they pass**

Run: the headless command.
Expected: exit code 0, every test printing PASS.

- [ ] **Step 5: Commit**

```bash
git add operators/mesh_smart_edge_slide_bridge.py tests/blender/test_smart_edge_slide.py
git commit -m "feat(smart-edge-slide): bridge builds bands, sides and step lids"
```

---

### Task 7: Bridge — apply cuts, step projection, operator `execute()`

**Files:**
- Modify: `operators/mesh_smart_edge_slide_bridge.py`
- Create: `operators/mesh_smart_edge_slide.py`
- Modify: `__init__.py` (import next to `IOPS_OT_smart_inset` at `__init__.py:336`; class list next to it at `__init__.py:707`)
- Modify: `tests/blender/test_smart_edge_slide.py`

**Interfaces:**
- Consumes: Task 6 bridge; `core.Slider`, `core.Cut`.
- Produces:
  - `def project_step(span: StepSpan, a: Vector, b: Vector) -> list[tuple[Vector, BMEdge | None, BMFace]] | None`.
    - The sheet is the plane through `a` and `b` that contains `span.normal`. Intersect it with every `span.region` face.
    - Keep the pieces whose projection onto `b - a` lies in `[0, |b - a|]`, and chain them from `a` to `b`.
    - Each entry is `(point, edge the point lies on or None, face the next piece lies in)`.
    - Return `None` when the pieces leave a gap larger than 1e-5.
  - `def apply_cut(bm, build: BandBuild, cut: core.Cut) -> list[BMEdge]`, which returns the new loop's edges in order.
    - Edge points use `bmesh.utils.edge_split`. Several points on one edge are split far-to-near so the parameters stay valid.
    - Vertex points reuse the vertex.
    - Each piece within one face uses `bmesh.utils.face_split(face, va, vb, coords=[interior "face" points])`. When `va` and `vb` are already joined by an edge, skip the split and take that edge (Review Focus 1).
    - Pieces on a lid are replaced by `project_step`, and each projected piece gets its own `face_split`.
    - Connectors use `face_split` in the face that holds both vertices after the loop cut.
    - **Custom data:** before splitting a face, keep a detached duplicate (`face.copy(verts=True, edges=True)`). Afterwards, call `loop.copy_from_face_interp(dup)` for every loop of every new vertex, then delete the duplicates' vertices.
  - `class IOPS_OT_smart_edge_slide(bpy.types.Operator)`:
    - `bl_idname = "iops.mesh_smart_edge_slide"`, `bl_label = "Smart Edge Slide"`, `bl_options = {"REGISTER", "UNDO"}`.
    - `width: FloatProperty(name="Width", default=0.05, soft_min=-10.0, soft_max=10.0, step=1, precision=4, subtype="DISTANCE")`.
    - `use_exact: BoolProperty(name="Exact Width", default=False)` and `use_collapse: BoolProperty(name="Allow Collapse", default=False)`.
    - `chain_sides: StringProperty(default="", options={'HIDDEN'})`: one `+` or `-` per chain in `collect_chains` order. An empty or short string defaults the missing chains to `+`.
    - `poll` is the same as Smart Inset's.
    - `execute()`:
      - negative `width` flips every chain's side and uses `|width|`;
      - for each chain: `build_band`, then `Slider(build.band).solve(|width|, exact=..., collapse=...)`, then `apply_cut`;
      - skipped chains report `{'WARNING'}` with `"Smart Edge Slide: chain skipped (<msg>)"`;
      - then deselect everything, select the new loop edges, `select_flush_mode()`, and `update_edit_mesh(me, loop_triangles=True, destructive=True)`;
      - return `{'CANCELLED'}` with a warning when nothing was cut.

- [ ] **Step 1: Write the failing headless tests**

```python
def _run(bm_obj, **props):
    return bpy.ops.iops.mesh_smart_edge_slide('EXEC_DEFAULT', **props)

def test_execute_strip():                       # new loop at exact width, selected
    obj = _edit_object(_strip(), chain=[0, 1, 2, 3])
    assert _run(obj, width=0.25, chain_sides="+") == {'FINISHED'}
    assert _new_coords(obj) == _round_set([(x, 0.25, 0.0) for x in range(4)])
    assert _selected_edge_count(obj) == 3

def test_execute_reuses_existing_mid_loop():    # Review Focus 1
    obj = _edit_object(_strip(rows=2), chain=[0, 1, 2, 3])
    v0, f0 = _counts(obj)
    _run(obj, width=0.5, chain_sides="+")
    assert _counts(obj) == (v0, f0) and _selected_edge_count(obj) == 3

def test_execute_ngon_connector_and_crossing():
    obj = _edit_object(_ngon_diag(), chain=[0, 1, 2])
    _run(obj, width=0.25, chain_sides="+")
    assert _new_coords(obj) == _round_set([(0, .25, 0), (2, .25, 0), (3, .25, 0), (4, .25, 0)])
    assert _edge_between(obj, (2, 0, 0), (2, .25, 0))

def test_execute_sliver_skips_connector():
    obj = _edit_object(_sliver(), chain=[0, 1, 2])
    _run(obj, width=0.2, chain_sides="+")
    assert not _edge_between(obj, (1, -0.1, 0), (1, 0.1009975, 0))

def test_execute_pocket_wraps():
    obj = _edit_object(_pocket(), chain=[0, 1, 2, 3])
    _run(obj, width=0.5, chain_sides="+")
    assert _new_coords(obj) == _round_set([(0, .5, 0), (1, .5, 0), (1, .5, .15),
                                           (2, .5, .15), (2, .5, 0), (3, .5, 0)])

def test_execute_side_is_stored_not_viewed():   # Review Focus 3
    a = _edit_object(_pocket(), chain=[0, 1, 2, 3]); _run(a, width=0.3, chain_sides="-")
    b = _edit_object(_pocket(), chain=[0, 1, 2, 3]); _run(b, width=-0.3, chain_sides="+")
    assert _new_coords(a) == _new_coords(b)
    assert all(y < 0 for _x, y, _z in _new_coords(a))

def test_execute_border_chain_skipped_others_cut():   # Review Focus 4
    obj = _edit_object(_strip_plus_border_chain(), chain=None)   # two selected chains
    assert _run(obj, width=0.25, chain_sides="++") == {'FINISHED'}
    assert len(_new_coords(obj)) == 4

def test_execute_non_planar_on_surface():       # Review Focus 5
    obj = _edit_object(_strip(lift=((0, 1, 0), 0.05)), chain=[0, 1, 2, 3])
    bvh = _bvh_before(obj); _run(obj, width=0.25, chain_sides="+")
    assert max(bvh.find_nearest(Vector(c))[3] for c in _new_coords(obj)) < 1e-6

def test_execute_interpolates_uvs():
    obj = _edit_object(_strip(uv=True), chain=[0, 1, 2, 3])
    _run(obj, width=0.25, chain_sides="+")
    assert all(abs(v - 0.25) < 1e-6 for v in _uv_v_of_new_verts(obj))
```

The helpers live in the test file:
- `_edit_object(bm, chain)` makes a mesh object, enters Edit Mode and selects the chain. With `chain=None` it keeps the builder's selection.
- `_new_coords` is the set of rounded coordinates (6 decimals) of vertices that did not exist before, and `_round_set` rounds the same way.
- `_counts` returns `(vertex count, face count)`.
- `_edge_between`, `_selected_edge_count`, `_bvh_before` (a BVHTree of the triangulated mesh before the run) and `_uv_v_of_new_verts`.
- `_strip_plus_border_chain()` returns the strip with its bottom chain plus a second selected chain along the strip's open top border, which has no `+` face.

- [ ] **Step 2: Run them to make sure they fail**

Run: the headless command.
Expected: exit code 1, with `AttributeError` for `bpy.ops.iops.mesh_smart_edge_slide`.

- [ ] **Step 3: Implement `project_step`, `apply_cut`, the operator class with props, `poll` and `execute()`, and register it in `__init__.py`.**

- [ ] **Step 4: Run the headless tests and the core suite to make sure they pass**

Run: the headless command, then `python -m pytest tests/test_smart_edge_slide_core.py -q`.
Expected: exit code 0 and all PASS.

- [ ] **Step 5: Commit**

```bash
git add operators/mesh_smart_edge_slide_bridge.py operators/mesh_smart_edge_slide.py __init__.py tests/blender/test_smart_edge_slide.py
git commit -m "feat(smart-edge-slide): apply cuts with step projection, execute() operator"
```

---

### Task 8: Modal — interaction, HUD, preview, Ctrl snap, F flip

**Files:**
- Modify: `operators/mesh_smart_edge_slide.py`
- Modify: `operators/mesh_smart_edge_slide_bridge.py`
- Modify: `tests/blender/test_smart_edge_slide.py`

**Interfaces:**
- Consumes: Tasks 5–7.
- Produces:
  - `def preview_layers(builds: list[BandBuild], cuts: list[core.Cut]) -> tuple[list[Vector], list[Vector], bool]` in the bridge. It returns `(loop segment endpoint pairs, new-vertex points, any_clamped)` in object space. Lid pieces are replaced by `project_step` points, exactly as `apply_cut` would cut them.
  - `def snap_candidates(builds: list[BandBuild]) -> list[tuple[BMVert, int, int]]` in the bridge. It returns `(vertex, chain index, side)` for the vertices of band faces, step-region faces and border paths. Only these can yield a width.
  - **Modal operator.** Mirror `operators/mesh_smart_inset.py` exactly for:
    - `_ACTIVE_HANDLES` / `_purge_handles`, `safe_handler_add(..., "POST_PIXEL", tick=True)`, the `modal` try/except teardown, `capture_event`;
    - `DIGIT_TYPES` numeric input, Shift precision anchors, HUD and help drag/toggle handling, MMB/wheel/NDOF pass-through;
    - cancel restoring every prop, and `_finish` dropping every bmesh reference.
- **Invoke:**
  - Build both sides for every chain: `build_band(bm, src, +1)` and `build_band(bm, src, -1)`, plus a `Slider` for each available side.
  - Set `chain_sides` from `core.positive_side`, using screen projections of each side's band-face centroid and the chain (`view3d_utils.location_3d_to_region_2d`).
  - Sensitivity: a quarter of the average chain-edge length per 100 px (Smart Inset's rule).
- **Keys:**
  - **Ctrl held:** the candidate from `snap_candidates` nearest the cursor, by `utils.picking.closest_snap_point` (pass `[("vertex", v.co) ...]`), sets `width = ±slider.snap_width(SurfacePoint(kind="vert", ...))`, signed so the side matches the candidate's side for that chain. Releasing Ctrl re-anchors the drag, as Smart Inset's Ctrl release does.
  - **E** toggles `use_exact`; **C** toggles `use_collapse`.
  - **F** flips `chain_sides[nearest_chain(...)]`, using the projected chains and the mouse position.
- **HUD and help:**
  - `HUDOverlay("smart_edge_slide")` with title "Smart Edge Slide".
  - Params: `HUDParam("Width", ..., "float", fmt="{:.4f}")`, `HUDParam("Exact Width (E)", ..., "bool")`, `HUDParam("Allow Collapse (C)", ..., "bool")`, `HUDParam("Clamped", ..., "bool")`.
  - `HelpOverlay("smart_edge_slide")` items: Adjust width (Mouse / Type), Snap to vertex (Ctrl), Exact width (E), Allow collapse (C), Flip chain side (F), Confirm (LMB / Enter), Cancel (Esc / RMB), Help / Toggle HUD (H).
  - Status text in the same format as Smart Inset's.
- **Preview** (projected to pixels as in Smart Inset `_draw_callback`, inside `draw_scope(blend="ALPHA")`):
  - loop: `Role.PREVIEW_LINE`, or `Role.ERROR_LINE` when clamped;
  - new vertices: `Role.PREVIEW_POINT`;
  - the snapped candidate: `Role.CLOSEST_POINT`.
  - Cache keyed on `(width, use_exact, use_collapse, chain_sides)`.

- [ ] **Step 1: Write the failing headless tests**

```python
def test_preview_layers_match_apply():
    bm = _pocket(); src = _chain(bm, [0, 1, 2, 3])
    build, _ = bridge.build_band(bm, src, +1)
    cut = core.Slider(build.band).solve(0.5)
    segs, pts, clamped = bridge.preview_layers([build], [cut])
    assert not clamped and len(segs) == 2 * 5
    assert _round_set(pts) >= _round_set([(1, .5, .15), (2, .5, .15)])

def test_snap_candidates_cover_band_and_step_region():
    bm = _pocket(); build, _ = bridge.build_band(bm, _chain(bm, [0, 1, 2, 3]), +1)
    cos = _round_set([v.co for v, _c, _s in bridge.snap_candidates([build])])
    assert (1.0, 0.0, 0.15) in cos and (0.0, 2.0, 0.0) in cos
```

- [ ] **Step 2: Run them to make sure they fail**

Run: the headless command.
Expected: exit code 1, with `AttributeError: module ... has no attribute 'preview_layers'`.

- [ ] **Step 3: Implement `preview_layers`, `snap_candidates` and the modal (`invoke`, `modal`, `_finish`, `_draw_callback`, HUD and help, E/C/F/Ctrl handling).**

- [ ] **Step 4: Run the headless tests and lint**

Run: the headless command, then `uvx ruff@0.12.0 check operators/mesh_smart_edge_slide.py operators/mesh_smart_edge_slide_bridge.py`.
Expected: exit code 0; ruff reports no errors.

- [ ] **Step 5: Live smoke over MCP.** Modal operators cannot be driven over MCP.

Reload the addon in the user's Blender (live-reload rule in Global Constraints). On a scratch object in a scratch scene, call the invoke-path helpers (`build_band` for both sides, `Slider`, `preview_layers`) and construct the HUD and help classes. Confirm nothing raises. Leave the scene as you found it.

- [ ] **Step 6: Commit**

```bash
git add operators/mesh_smart_edge_slide.py operators/mesh_smart_edge_slide_bridge.py tests/blender/test_smart_edge_slide.py
git commit -m "feat(smart-edge-slide): modal with HUD, themed preview, Ctrl snap and side flip"
```

---

### Task 9: Wiring, docs and the reference-mesh check

**Files:**
- Modify: `prefs/hotkeys_default.py` — add `("iops.mesh_smart_edge_slide", "F19", "PRESS", False, False, False, False),` after the Smart Inset line (LF file).
- Modify: `ui/iops_pie_edit.py` — add `("iops.mesh_smart_edge_slide", "Smart Edge Slide", ""),` after the Smart Inset entry (CRLF file).
- Modify: `ui/iops_pie_menu.py` — add `op_if_poll(col, "iops.mesh_smart_edge_slide", text="Smart Edge Slide")` after the Smart Inset line (CRLF file).
- Modify: `tests/smoke_register.py` — add `"mesh_smart_edge_slide"` to the operator tuple.
- Create: `docs/operators/op_mesh_smart_edge_slide.md`.
- Modify: `docs/operators.md`, `docs/index.md` and `mkdocs.yml` — add an entry after Smart Inset in the *Mesh — Editing* lists.
- Modify: `docs/ui/ui_pies.md` — add **Smart Edge Slide** to the Edit Mesh tools row (mixed line endings: keep each line's own ending).

**Interfaces:**
- Consumes: the finished operator.
- Produces: user access through the pie, the keymap slot and the docs, plus a verified result on the reference mesh.

- [ ] **Step 1: Wire hotkey, pies and smoke registration; run the smoke test**

Run: the headless command with `--python tests/smoke_register.py`. It needs the `scripts/addons/InteractionOps` junction to the repo, as described in that script's docstring.
Expected: exit code 0.

- [ ] **Step 2: Write `docs/operators/op_mesh_smart_edge_slide.md`.**

Follow the structure of `docs/operators/op_mesh_smart_inset.md`: title, one-paragraph summary, Hotkey line, Controls table (the modal keys from Task 8), Options (Width, Exact Width, Allow Collapse), and Tips. The tips cover four things:
- the loop wraps steps such as pockets;
- open ends slide along the border;
- in the default mode the width can drift slightly mid-edge where the source loop bends against the side's edges, and Exact Width removes that drift;
- connecting edges are skipped where they would cross an existing edge.

The image line points to `../img/ops/op_mesh_smart_edge_slide.png`. The user supplies the image later; leave it referenced. Add the index, operators and mkdocs entries.

- [ ] **Step 3: Check the result on the reference mesh over MCP.**

Ask the user before touching the open file. Then, following the blender-mcp file-protection rules, duplicate the reference mesh into a scratch object, select the reference chain, and run `bpy.ops.iops.mesh_smart_edge_slide('EXEC_DEFAULT', ...)` on both sides. Assert:
- **Shape.** Every new vertex lies within 1e-6 of the original surface.
- **Wall side, width 0.4, default mode.** 12 + 2 new vertices (the two pocket corners), and the loop runs over pocket faces 86, 87 and 88.
- **Panel side, width 0.2.** Every anchor's distance to the chain, measured in the panel plane, is within 1e-6 of 0.2.
- **Cleanup.** Delete the scratch object and leave the user's file as it was.

- [ ] **Step 4: Run every suite one last time**

Run: `python -m pytest tests/test_smart_edge_slide_core.py -q`, the headless command, and `uvx ruff@0.12.0 check utils/smart_edge_slide_core.py operators/mesh_smart_edge_slide.py operators/mesh_smart_edge_slide_bridge.py`. Then run `git ls-files --eol` on every changed file and compare with `git show master:<file>`.
Expected: all green, and no line-ending churn (a small change must not show hundreds of lines).

- [ ] **Step 5: Commit**

```bash
git add prefs/hotkeys_default.py ui/iops_pie_edit.py ui/iops_pie_menu.py tests/smoke_register.py docs/operators/op_mesh_smart_edge_slide.md docs/operators.md docs/index.md mkdocs.yml docs/ui/ui_pies.md
git commit -m "feat(smart-edge-slide): pie, keymap slot, docs and reference-mesh check"
```

---

### Task 10: UV Stripe core — straight strip layout and placement

Spec: *UV Stripe* section.

**Files:**
- Create: `utils/uv_stripe_core.py`
- Test: `tests/test_uv_stripe_core.py`

**Interfaces:**
- Produces:
  - `@dataclass class Strip`, with these fields:
    - `verts: dict[int, Vec3]` and `faces: dict[int, tuple[int, ...]]`;
    - `near: list[int]`: vertices along the original edge, in order;
    - `far: list[int]`: vertices along the new edge, in the same direction. A vertex id may repeat, as on collapsed inset seams.
    - `rungs: list[tuple[int, int]]`: ascending `(index into near, index into far)` pairs where the columns line up;
    - `closed: bool` and `height: float`;
    - `sides: tuple[list[int], list[int]] = ([], [])`: for open strips, the vertices strictly between `near[0]` and `far[0]`, and between `near[-1]` and `far[-1]`, along the strip's two ends, ordered from near to far;
    - `corner_far: dict[tuple[int, int], int] = field(default_factory=dict)`: `(face id, vertex id) → index into far`, needed only for vertices that occur more than once in `far`.
  - `def sharpest_rung(strip: Strip) -> int`: the rung whose near vertex has the smallest 3D angle between its two near-loop edges. On a tie, the lowest rung index wins. Closed strips only.
  - `def stripe_uvs(strip: Strip) -> dict[tuple[int, int], tuple[float, float]]`: `(face id, vertex id) → (u, v)` in world units.
  - `def strip_length(strip: Strip) -> float`.
  - `def place_fit(maps: list[dict], heights: list[float], lengths: list[float], gap: float = 0.01) -> list[dict]`.
  - `def place_in_place(uv: dict, length: float, height: float, center: tuple[float, float], density: float) -> dict`.
- **Layout rules:**
  - **Rung positions.** `u` at the rungs is the cumulative mid-line length: each step adds `(near path length + far path length) / 2` between consecutive rungs. A closed strip starts at `sharpest_rung` and wraps, so the seam rung's vertices get `u = 0` on one side and `u = L` on the other.
  - **Boundary vertices.** Near vertices get `v = 0` and far vertices `v = height`. Their `u` is interpolated by arc length between the rung `u` values on their own side. Side vertices get `u = 0` or `u = L`, with `v` by arc length along that side, scaled to `[0, height]`.
  - **Interior vertices** (on no boundary) use a uniform-weight Tutte embedding. Run Gauss–Seidel over face-edge neighbours until the largest move is below `1e-12 · L`, or for 1000 iterations.
  - **Fit.** Scale every strip by `1 / L`, and stack them upward from `v = 0` with `gap` between them.
  - **In Place.** Scale by `density` and centre the strip's UV bounding box on `center`.

- [ ] **Step 1: Write the failing tests**

```python
def quad_strip():      # near 0..3 on y=0, far 4..7 on y=0.25, unit columns
    v = {i: (float(i), 0.0, 0.0) for i in range(4)} | {4 + i: (float(i), 0.25, 0.0) for i in range(4)}
    f = {0: (0, 1, 5, 4), 1: (1, 2, 6, 5), 2: (2, 3, 7, 6)}
    return Strip(verts=v, faces=f, near=[0, 1, 2, 3], far=[4, 5, 6, 7],
                 rungs=[(i, i) for i in range(4)], closed=False, height=0.25)

def square_ring():     # 2x2 outer square, 0.2 inset walls
    o = [(0, 0), (2, 0), (2, 2), (0, 2)]; i_ = [(0.2, 0.2), (1.8, 0.2), (1.8, 1.8), (0.2, 1.8)]
    v = {k: (float(x), float(y), 0.0) for k, (x, y) in enumerate(o + i_)}
    f = {0: (0, 1, 5, 4), 1: (1, 2, 6, 5), 2: (2, 3, 7, 6), 3: (3, 0, 4, 7)}
    return Strip(verts=v, faces=f, near=[0, 1, 2, 3], far=[4, 5, 6, 7],
                 rungs=[(k, k) for k in range(4)], closed=True, height=0.2)

def test_quad_strip_maps_to_itself():
    uv = stripe_uvs(quad_strip())
    assert uv[(0, 0)] == pytest.approx((0.0, 0.0)) and uv[(2, 7)] == pytest.approx((3.0, 0.25))
    assert strip_length(quad_strip()) == pytest.approx(3.0)

def test_ring_unrolls_with_seam_at_first_corner():
    s = square_ring()
    assert sharpest_rung(s) == 0 and strip_length(s) == pytest.approx(7.2)
    uv = stripe_uvs(s)
    assert uv[(0, 0)] == pytest.approx((0.0, 0.0)) and uv[(0, 5)] == pytest.approx((1.8, 0.2))
    assert uv[(3, 0)] == pytest.approx((7.2, 0.0)) and uv[(3, 4)] == pytest.approx((7.2, 0.2))
    assert uv[(3, 3)] == pytest.approx((5.4, 0.0))

def test_interior_vertex_goes_to_the_middle():
    v = {0: (0.0, 0.0, 0.0), 1: (1.0, 0.0, 0.0), 2: (0.0, 1.0, 0.0), 3: (1.0, 1.0, 0.0), 4: (0.5, 0.5, 0.3)}
    f = {0: (0, 1, 4), 1: (1, 3, 4), 2: (3, 2, 4), 3: (2, 0, 4)}
    s = Strip(verts=v, faces=f, near=[0, 1], far=[2, 3], rungs=[(0, 0), (1, 1)], closed=False, height=1.0)
    uv = stripe_uvs(s)
    assert all(uv[(fi, 4)] == pytest.approx((0.5, 0.5)) for fi in f)

def test_end_side_vertex_on_the_strip_edge():
    v = {0: (0.0, 0.0, 0.0), 1: (2.0, 0.0, 0.0), 2: (0.0, 0.3, 0.0), 3: (1.7777778, 0.3, 0.0), 4: (2.0, 0.1, 0.0)}
    s = Strip(verts=v, faces={0: (0, 1, 4, 3, 2)}, near=[0, 1], far=[2, 3], rungs=[(0, 0), (1, 1)],
              closed=False, height=0.3, sides=([], [4]))
    assert stripe_uvs(s)[(0, 4)] == pytest.approx((1.8888889, 0.0751937), abs=1e-6)

def test_fit_stacks_strips():
    a, b = quad_strip(), square_ring()
    out = place_fit([stripe_uvs(a), stripe_uvs(b)], [a.height, b.height], [3.0, 7.2])
    us_a = [u for u, _v in out[0].values()]; vs_a = [v for _u, v in out[0].values()]
    vs_b = [v for _u, v in out[1].values()]
    assert (min(us_a), max(us_a)) == pytest.approx((0.0, 1.0))
    assert max(vs_a) == pytest.approx(0.0833333, abs=1e-6)
    assert (min(vs_b), max(vs_b)) == pytest.approx((0.0933333, 0.1211111), abs=1e-6)

def test_in_place_scales_by_density_and_centres():
    out = place_in_place(stripe_uvs(quad_strip()), 3.0, 0.25, center=(0.75, 0.0625), density=0.5)
    us = [u for u, _v in out.values()]; vs = [v for _u, v in out.values()]
    assert (min(us), max(us)) == pytest.approx((0.0, 1.5))
    assert (min(vs), max(vs)) == pytest.approx((0.0, 0.125))
```

- [ ] **Step 2: Run them to make sure they fail**

Run: `python -m pytest tests/test_uv_stripe_core.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'utils.uv_stripe_core'`.

- [ ] **Step 3: Implement `utils/uv_stripe_core.py`** (stdlib only).

- [ ] **Step 4: Run the tests and lint**

Run: `python -m pytest tests/test_uv_stripe_core.py -q && uvx ruff@0.12.0 check utils/uv_stripe_core.py tests/test_uv_stripe_core.py`
Expected: PASS; ruff clean.

- [ ] **Step 5: Commit**

```bash
git add utils/uv_stripe_core.py tests/test_uv_stripe_core.py
git commit -m "feat(uv-stripe): straight strip UV layout core"
```

---

### Task 11: UV Stripe in Smart Edge Slide

**Files:**
- Create: `operators/uv_stripe_bridge.py`
- Modify: `operators/mesh_smart_edge_slide_bridge.py`, `operators/mesh_smart_edge_slide.py`, `tests/blender/test_smart_edge_slide.py`, `docs/operators/op_mesh_smart_edge_slide.md`

**Interfaces:**
- Consumes: `uv_stripe_core`, plus Task 7's `apply_cut` and Task 8's modal.
- Produces:
  - In `operators/uv_stripe_bridge.py`:
    - `@dataclass class StripeContext: center: tuple[float, float]; density: float`.
    - `def uv_context(bm, faces: list[BMFace]) -> StripeContext | None`:
      - `center` is the centre of the active-layer UV bounding box of `faces`;
      - `density` is the sum of UV edge lengths divided by the sum of 3D edge lengths, over the edges of faces that share an edge with `faces` but are not in it;
      - returns `None` without a UV layer or when the density is 0.
    - `def apply_stripes(bm, strips: list[uv_stripe_core.Strip], faces: dict[int, BMFace], mode: str, ctx: StripeContext | None) -> None`:
      - use the active UV layer, or create one;
      - `mode` is `"FIT"` or `"IN_PLACE"`; `"IN_PLACE"` with `ctx is None` falls back to `"FIT"`;
      - write the UV of every strip face corner.
  - `apply_cut` returns `Applied(loop_edges: list[BMEdge], loop_verts: list[BMVert], anchors: list[int | None], strip_faces: list[BMFace])` instead of the bare edge list. Update `execute()` to match.
    - `strip_faces` are found by flood fill from the side faces of the chain edges. The fill crosses any edge except chain edges, new-loop edges, and edges with only one face in the fill.
  - `def stripe_for(build: BandBuild, applied: Applied, width: float) -> tuple[uv_stripe_core.Strip, dict[int, BMFace]]`:
    - `near` is the chain, `far` is the loop vertices, and `rungs` are the `(k, anchors[k])` pairs with an anchor;
    - for open chains, `sides` are the strip-boundary vertices walked from `near[0]` to `far[0]` and from `near[-1]` to `far[-1]`;
    - `height` is the applied width.
  - Operator props:
    - `use_uv_stripe: BoolProperty(name="UV Stripe", default=False)`;
    - `uv_stripe_mode: EnumProperty(name="UV Stripe Mode", items=[("FIT", "Fit 0–1", "Stretch the strip across U 0–1, V in proportion"), ("IN_PLACE", "In Place", "Keep the old UV location and the neighbours' texel density")], default="FIT")`.
  - Modal: **U** toggles `use_uv_stripe`, with `HUDParam("UV Stripe (U)", ..., "bool")` and the help item "UV Stripe (U)". The mode is set in the redo panel only.
  - `execute()`: after `apply_cut`, when `use_uv_stripe` is set, call `uv_context` on all strip faces (before writing), then `stripe_for` per chain, then `apply_stripes`.

- [ ] **Step 1: Write the failing headless tests**

```python
def test_uv_stripe_fit_strip():
    obj = _edit_object(_strip(uv=True), chain=[0, 1, 2, 3])
    _run(obj, width=0.25, chain_sides="+", use_uv_stripe=True)
    uvs = _strip_corner_uvs(obj)                 # {(rounded co): set of uv} for strip faces
    assert uvs[(0.0, 0.0, 0.0)] == {(0.0, 0.0)} and uvs[(3.0, 0.25, 0.0)] == {(1.0, 0.083333)}

def test_uv_stripe_fit_pocket_is_a_rectangle():
    obj = _edit_object(_pocket(), chain=[0, 1, 2, 3])
    _run(obj, width=0.5, chain_sides="+", use_uv_stripe=True)
    us, vs = _strip_uv_ranges(obj)
    assert us == (0.0, 1.0) and vs == (0.0, 0.15873)

def test_uv_stripe_in_place():
    obj = _edit_object(_strip(uv="half"), chain=[0, 1, 2, 3])   # u = x/2, v = y/2
    _run(obj, width=0.25, chain_sides="+", use_uv_stripe=True, uv_stripe_mode="IN_PLACE")
    us, vs = _strip_uv_ranges(obj)
    assert us == (0.0, 1.5) and vs == (0.0, 0.125)

def test_uv_stripe_creates_missing_layer():
    obj = _edit_object(_strip(), chain=[0, 1, 2, 3])            # no UV layer
    _run(obj, width=0.25, chain_sides="+", use_uv_stripe=True)
    assert len(obj.data.uv_layers) == 1
```

The helpers `_strip_corner_uvs` and `_strip_uv_ranges` round to 6 decimals and look only at faces between the chain and the new loop. `_strip(uv=...)` supports `True` (u = x/3, v = y/3) and `"half"` (u = x/2, v = y/2).

- [ ] **Step 2: Run them to make sure they fail.** Expected: exit code 1 with `TypeError` for the unknown property `use_uv_stripe`.

- [ ] **Step 3: Implement `uv_stripe_bridge`, the `Applied` / `stripe_for` changes, the props, the U key, the HUD and help entries, and add a UV Stripe line to the docs page's Controls and Options.**

- [ ] **Step 4: Run the headless tests, `python -m pytest tests -q`, and ruff on the changed files.** Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add operators/uv_stripe_bridge.py operators/mesh_smart_edge_slide_bridge.py operators/mesh_smart_edge_slide.py tests/blender/test_smart_edge_slide.py docs/operators/op_mesh_smart_edge_slide.md
git commit -m "feat(smart-edge-slide): UV Stripe unwraps the new strip"
```

---

### Task 12: UV Stripe in Smart Inset

**Files:**
- Modify: `operators/mesh_smart_inset.py`, `docs/operators/op_mesh_smart_inset.md` (CRLF: keep its endings)
- Create: `tests/blender/test_smart_inset_uv_stripe.py` (same structure as `tests/blender/test_cursor_bisect_delimit.py`)

**Interfaces:**
- Consumes: `uv_stripe_core`, `uv_stripe_bridge`.
- Produces:
  - `apply_inset` and `_apply_outset` return `(faces_created, mutated, strips)`. Their two callers in the operator (`_run`, and the preview path where relevant) are updated.
    - `strips` is a `list[tuple[uv_stripe_core.Strip, dict[int, BMFace]]]`, one per boundary loop of the region.
    - **Inset:** `near` is the loop's original vertices (closed). `far` is the wall-top chains concatenated in loop order. Each rung is `(i, index in far of the first chain vertex of wall i)`. `corner_far` covers vertices that repeat on collapsed seams. `height` is `t_eff`.
    - **Outset:** `far` is the outer ring and `height` is `|t|`.
  - Same props as Task 11 (`use_uv_stripe`, `uv_stripe_mode`), the U key in the modal, `HUDParam("UV Stripe (U)", ..., "bool")` and the help item.
  - `_run`: when `use_uv_stripe` is set, call `uv_context` on all wall or ring faces, then `apply_stripes` with every strip from every region.

- [ ] **Step 1: Write the failing headless tests**

```python
def test_inset_square_fit():
    obj = _plane(2.0); _select_all_faces(obj)
    bpy.ops.iops.mesh_smart_inset('EXEC_DEFAULT', thickness=0.2, use_uv_stripe=True)
    us, vs = _wall_uv_ranges(obj)
    assert us == (0.0, 1.0) and vs == (0.0, 0.027778)
    assert _seam_vertex_has_u0_and_u1(obj)

def test_outset_square_fit():
    obj = _plane(2.0); _select_all_faces(obj)
    bpy.ops.iops.mesh_smart_inset('EXEC_DEFAULT', thickness=-0.2, use_uv_stripe=True)
    assert _wall_uv_ranges(obj)[1] == (0.0, 0.022727)

def test_collapsed_rectangle_still_a_rectangle():
    obj = _plane_rect(1.0, 4.0); _select_all_faces(obj)
    bpy.ops.iops.mesh_smart_inset('EXEC_DEFAULT', thickness=99.0, use_collapse=True, use_uv_stripe=True)
    assert _wall_uv_ranges(obj) == ((0.0, 1.0), (0.0, 0.0625))

def test_uv_stripe_off_keeps_old_behaviour():
    obj = _plane(2.0, uv=True); _select_all_faces(obj)
    before = _uv_bbox(obj)
    bpy.ops.iops.mesh_smart_inset('EXEC_DEFAULT', thickness=0.2)
    assert _uv_bbox(obj) == before
```

The helpers round to 6 decimals:
- `_wall_uv_ranges` returns `((u_min, u_max), (v_min, v_max))` over the wall or ring faces, which are the unselected new faces after the operator.
- `_seam_vertex_has_u0_and_u1` checks that one 3D vertex carries both u = 0 and u = 1 on different faces.

- [ ] **Step 2: Run them to make sure they fail.** Expected: exit code 1 with `TypeError` for the unknown property `use_uv_stripe`.

- [ ] **Step 3: Implement the Smart Inset changes, and document the U key and the UV Stripe option in `docs/operators/op_mesh_smart_inset.md`.**

- [ ] **Step 4: Run the new headless test, `python -m pytest tests -q` (Smart Inset core tests included), and ruff on the changed files.** Expected: all green, and the existing Smart Inset behaviour is unchanged when UV Stripe is off.

- [ ] **Step 5: Commit**

```bash
git add operators/mesh_smart_inset.py docs/operators/op_mesh_smart_inset.md tests/blender/test_smart_inset_uv_stripe.py
git commit -m "feat(smart-inset): UV Stripe unwraps the inset walls"
```

---

## Self-Review Notes

**Spec coverage**

| Spec requirement | Task |
|---|---|
| Exact width | 3–5 |
| Cut, don't move | 7 |
| One vertex per source vertex, unavoidable crossings | 3 |
| Exact-width mode | 3, 4 |
| Steps projected through | 6, 7 |
| Ctrl snapping | 5, 8 |
| Open, closed and several chains | 3, 4, 6, 7 |
| Ends slide along the border | 4 |
| Hard limits, per-chain clamp, collapse | 5 |
| Variant B connectors and skip rule | 3, 4, 7 |
| Side rules, F flip, stored sides | 5, 7, 8 |
| Modal UX, HUD, themed preview, redo | 7, 8 |
| Errors and warnings | 6, 7 |
| Wiring and docs | 9 |
| Reference-case check | 9 |
| UV Stripe layout, seam, Fit and In Place | 10 |
| UV Stripe in Smart Edge Slide | 11 |
| UV Stripe in Smart Inset | 12 |

**Known risk:** the trace in Task 2 is the foundation. If the reference mesh check finds inconsistent developments (`trace_segment` raising) on real n-gons, fix it in Task 2's code with a new pinned test; do not paper over it in the bridge.
