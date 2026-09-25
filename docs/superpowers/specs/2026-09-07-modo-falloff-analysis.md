# Modo-Style Falloff Tools in iOps — Research & Analysis

Date: 2026-09-07
Status: research only — no design approved, no code written

Goal of this document: establish what Modo's falloff system actually is, what Blender
offers natively, what exists in the addon ecosystem, what iOps infrastructure a port could
reuse, and which implementation architecture is recommended. A design spec follows once
the open questions in §8 are answered.

---

## 1. What Modo's falloffs are

### 1.1 Tool Pipe model

Modo tools are assembled from independent stages: **Action Center** (pivot + orientation),
**Action Axis**, **Falloff**, **Snap**, **Symmetry**, and the **Actor** (the actual
Move/Rotate/Scale/Push). A falloff is a persistent *modifier* that stays active across
successive tool invocations until disabled. Named presets are just pipe combinations:

| Preset | Pipe |
|---|---|
| Twist | Axis Rotate + Linear falloff |
| Taper | Transform (scale) + Linear falloff |
| Soft Move | Transform + Radial falloff |
| Soft Drag | Move + Screen falloff |
| Element Move | Move + Element falloff |
| Soft Select Move/Scale | Move/Scale + Selection action center + Soft Selection falloff |
| Falloff Weight | Soft Selection falloff written to a weight map |

SDK contract (C++ `ILxFalloffPacket`): `Evaluate(pos, vertex, polygon) -> double` and
`Screen(x, y) -> double`. Pipe ordering: action center → axis → **weight (falloff)** →
actor. The actor multiplies its per-vertex effect by the weight.

Sources: Tool Pipe docs (learn.foundry.com/modo/901/.../tool_pipe.html), SDK
`lx-tool.hpp` wiki, Spikey tool tutorial.

### 1.2 Falloff catalogue

Fifteen modelling falloffs exist. The docs never publish weight equations; formulas below
are inferred from behaviour descriptions.

| Falloff | Primitive | Key parameters | Weight w(p) (inferred) | Handles |
|---|---|---|---|---|
| **Linear** | segment Start→End | Start/End XYZ, Auto Size, Reverse, Symmetric {None, Start, End}, Shape, In/Out, Mix | t = clamp((p−S)·(E−S)/‖E−S‖²); w = shape(1−t) | drag Start/End; RMB-drag draws a fresh axis |
| **Radial** | sphere/ellipsoid | Center XYZ, Size XYZ, Auto Size, Shape, In/Out, Mix | d = ‖(p−C)/Size‖ per-axis; w = shape(1−clamp d) | center + per-axis size |
| **Cylinder** | infinite cylinder along an axis | Radial params + Axis | Radial after dropping axis component | as Radial |
| **Screen** | disc in **pixels**, projected to infinity | Center XY (screen), Size px, Transparent | w = 1 − clamp(‖proj(p)−C‖/Size) | RMB-drag = radius |
| **Element** | clicked vert/edge/face is origin | Mode {Auto, Vertex, Edge, Polygon, *Center}, Range (default 0), Connected {Ignore, Use Connectivity, Rigid, Edge Loops}, Shape | w = shape(1 − dist/Range); connectivity filters participants | click element; drag moves it |
| **Airbrush** | screen brush, accumulates during drag | Center XY, Size px, Strength, Transparent | w += Strength·brush(d) per sample | RMB-haul = size |
| **Noise** | 3D noise field | Scale | w = noise(p/Scale) | none |
| **Curvature** | surface curvature | Scale (sign flips concave/convex) | per-surface | none |
| **Vertex Map** | weight/morph/RGB map | Mode {Magnitude, Component}, Index | map value | none |
| **Path** | tube around a curve | Size | w = 1 − dist_to_curve/Size | curve points live |
| **Lasso** | screen region | Style {Lasso, Rect, Circle, Ellipse}, Soft Border px | inside 1, else ramp over border | draw region |
| **Image** | projected image | Repeat, Soft Border, UV map, Scale, Pos, Rot | luminance × border ramp | center/scale/rotate |
| **Selection** | *inside* the selection, topological | Steps (poly loops / edge rings) | 0 at border → 1 after Steps loops inward | none |
| **Soft Selection** | *outside* the selection | Radius, Use Connectivity, Shape | w = shape(1 − dist/Radius) | RMB-drag = radius |
| **Coplanar** | normal angle to selection | Angle, Use Connectivity, Shape | w = shape(1 − angle/Angle) | RMB-drag |

Common to all shaped falloffs:

- **Shape preset**: Linear, Ease-In (stronger toward Start), Ease-Out (stronger toward
  End), Smooth (stronger in the middle), Custom (In/Out sliders act as curve tangents).
  Most plausible equivalents: Linear `t`, Ease-In `t^2`, Ease-Out `1−(1−t)^2`, Smooth
  `3t^2−2t^3`. Not officially confirmed.
- **Mix Mode** for stacking: Multiply, Add, Subtract, Max, Min. Multiple falloffs may be
  active at once (Falloff menu → Add). Default mix mode unconfirmed.
- **Use World Transforms**: treat all selected meshes as one surface (Modo 14+).
- **Auto Size**: fit falloff to the selection's bounding box; selecting a falloff while a
  tool is active auto-fits it.
- **Invert Falloff** command; **Show Falloffs** view option colours vertices purple→yellow.
- Activation gesture: first click sets origin on the Work Plane, drag sets size.

### 1.3 How weight is applied per actor

Documented only as "attenuated". Behavioural evidence gives the model:

- Move: `p' = p + w·Δ`
- Rotate (Twist): `p' = C + R(axis, w·θ)·(p−C)` — per-vertex *angle* scaling, not a
  position lerp (a lerp would collapse geometry toward the axis).
- Scale (Taper): `p' = C + (1 + w·(s−1))·(p−C)`
- Airbrush accumulates weight over the stroke.
- Copy/Paste/Delete ignore falloffs. Bevel unconfirmed.

### 1.4 Distance metric

Element and Soft Selection are Euclidean with an optional connectivity *filter* ("Use
Connectivity" drops unconnected geometry inside the range). The only truly topological
metric is the Selection falloff's Steps. Modo does **not** do geodesic distance.

Comparative baselines: Maya Soft Select offers Volume / Surface (geodesic-ish) / Global
modes plus an editable curve; 3ds Max Soft Selection is a sphere with Pinch/Bubble and
an optional Edge Distance (edge-step limit), curve
`w = (3u·bubble·s + 3u^2(1−pinch))·s + u^3`, `u = 1 − d/r`, `s = 1−u`.

---

## 2. Blender native baseline: proportional editing

Verified against Blender `main` source (`transform_generics.cc :: calculatePropRatio`,
`transform_convert.cc :: set_prop_dist`, `transform_convert_mesh.cc`).

**Curves**, with `x = (r − d)/r` clamped to [0,1] (1 at selection, 0 at radius):

| Enum | factor |
|---|---|
| SHARP | x^2 |
| SMOOTH | min(1, 3x^2 − 2x^3) |
| ROOT | sqrt(x) |
| LINEAR | x |
| CONSTANT | 1 |
| SPHERE | sqrt(2x − x^2) |
| RANDOM | rand()·x (wall-clock seeded) |
| INVERSE_SQUARE | x(2 − x) |

**Application**: translate `loc = iloc + factor·tvec`; rotate `angle·factor` per element;
resize `loc = iloc + factor·((S(iloc−C)+C) − iloc)`. Same model as Modo — good.

**Distance**: Euclidean via KD-tree of selected elements (world space). *Projected from
View* strips the view-axis component before measuring (world units in the view plane, not
pixels). *Connected Only* is a wavefront over edges with triangle-crossing geodesic
refinement (`geodesic_distance_propagate_across_triangle`), edit mode only.

**Why it is not enough**

- One sphere, always centred on the selection. No linear ramp, cylinder, screen disc,
  element origin, or arbitrary centre.
- No handles; radius by wheel / PageUp/Down during the modal only.
- Eight hardcoded curves, no In/Out shaping (custom curve requested on devtalk since 2019).
- Nothing is persistent between invocations except the scalar radius.
- No stacking, no invert, no per-vertex map input.

**Can Python inject weights into the native transform? No.** `bpy.ops.transform.*`
exposes only `use_proportional_edit`, `proportional_edit_falloff`, `proportional_size`,
`use_proportional_connected`, `use_proportional_projected`, `center_override`. The factor
is computed internally from distances. Vertex groups and attributes are never read.
`center_override` moves the pivot but distances are still measured from the selection.
Sculpt Grab (`sculpt.brush_stroke`) has richer curves but requires Sculpt mode and ignores
selection. **Conclusion: a custom modal operator is mandatory.**

---

## 3. Prior art in the Blender ecosystem

| Addon | Falloffs | Implementation | Notes |
|---|---|---|---|
| **YT-Tools** (Yoshiaki Tazaki, ex-Foundry, closed, $20) | Linear Transform (diamond widget, Reverse, Mirror, Symmetry, Selection Island), Radial Transform (centre + per-axis handles, Invert), Linear/Radial Weight → vertex group, Bend, Soft Drag (screen px, occlusion test), Smooth Brush | modal operators + GPU handles; G/R/S switches actor inside one modal | closest to Modo; falloff re-fits on each activation, does not persist |
| **rmKit** (roosterMAP, GPL) | Falloff Transform: two endpoints, G/S/R, C cycles ease, I reverses, works in UV editor | `linear_deformer.py` modal | open source, compact reference |
| **Mira Tools** (mifth, GPL) | Linear Deformer: 3D line auto-fitted to selection bounds; B bend, Shift+B spiral, G/S/T/Shift+T twist | weight = distance to start plane / length, clamped; per-vert `(index, weight, co)`; POST_PIXEL drawing; in-modal Ctrl+Z history | linear ramp only, no ease |
| **Bezier Mesh Shaper** (closed) | curve deform with Off/Distance/Connected falloff, Smooth/Linear/Constant | own implementation | |
| **Modo-Me** | action centers + "Element Edit with Falloff" | undocumented | |
| **Falloff Lens** | visualiser for native proportional radius only | GPU overlay | |
| Falloff Tool (Studio Speets) | Geometry Nodes fields | irrelevant to edit-mode transforms | |

Takeaways: nobody has shipped Modo's *persistent, stackable* falloff-as-mode in Blender.
All existing tools bind one falloff to one modal. Mira Tools and rmKit are the code to
read for handle/drag plumbing.

---

## 4. Implementation facts for Blender 5.x Python

**Data access**

- `mesh.vertices.foreach_get/set` do not work in edit mode. Use `bmesh.from_edit_mesh`.
- `BMVertSeq` has no `foreach_get`; extracting coords to numpy is a one-time Python loop
  in `invoke` (~50–100 ms at 100k verts, acceptable).
- Per-frame write-back is the real cost: assign `v.co` only for verts with `w > 0`, then
  `bmesh.update_edit_mesh(me, loop_triangles=False, destructive=False)`. Skip
  `normal_update()` until confirm. GPU re-upload of the edit mesh is the dominant fixed
  cost on dense meshes.
- Blender ships numpy 2.3 but **no scipy**. Topology distances = pure-Python `heapq`
  multi-source Dijkstra with early exit at `radius`. Adding face-diagonal virtual edges
  halves grid over-estimation cheaply. Or Rust via pyo3 (see §5).

**Vectorised math** (P0 original local coords, W weights, idx = nonzero weights):

```python
P = P0a + Wa * delta_local                              # move
P = C + (1.0 + Wa * (s - 1.0)) * (P0a - C)              # scale (uniform or per-axis)
v = P0a - C; k = axis                                   # rotate, Rodrigues per-vertex
c, s_ = np.cos(Wa*theta), np.sin(Wa*theta)
P = C + v*c + np.cross(k, v)*s_ + k*(v @ k)[:, None]*(1 - c)
```

**Undo**: `{'REGISTER', 'UNDO'}` pushes on `FINISHED`. Do not call `ed.undo_push` mid-modal.
iOps precedent: shear/hinge use `{"REGISTER"}` and push manually *after* the final apply
(`mesh_shear.py:1983`, rationale at `:1426-1433`); straight bevel uses `REGISTER, UNDO`
with `execute()` redo. Either pattern is fine; pick one per operator.

**GPU (5.x)**: `bgl` gone; `GPUShader(vert, frag)` constructor gone; wide lines need
`POLYLINE_UNIFORM_COLOR` with `viewportSize` + `lineWidth` uniforms; points need
`POINT_UNIFORM_COLOR`. iOps `ui/draw/shaders.py` already wraps these.

**Gizmos**: `GIZMO_GT_arrow_3d / dial_3d / move_3d / cage_3d` exist and bind via
`target_set_handler`. Blender's own Shear/To Sphere/Spin tools are gizmo-driven *redo*
operators, not modals. A running Python modal owns the event loop, so gizmo groups do not
receive events while it runs. Two viable patterns: (a) modal draws and hit-tests its own
handles (Mira, YT-Tools, all current iOps tools); (b) persistent `GizmoGroup` edits
falloff state stored on `WindowManager`, and a separate lightweight modal applies the
transform.

**Persistence**: `WindowManager` PointerProperty = session state, not saved with the file
(right for "falloff currently active"). `Scene.IOPS` = per-file (iOps already uses this for
last-used tool values). Addon prefs = cross-session defaults.

---

## 5. What iOps already has

Verified by codebase survey (file:line refs current as of `ececb8e`).

**Modal skeleton** — identical across `mesh_shear.py`, `mesh_hinge.py`,
`mesh_straight_bevel.py`: `invoke` builds bmesh + records, seeds params from `Scene.IOPS`,
attaches `HUDOverlay` + `HelpOverlay`, `safe_handler_add(..., "POST_PIXEL", tick=True)`;
`modal` is a two-layer wrapper catching `ReferenceError`; `_finish` nulls every bmesh ref
(redo-stack crash guard, `mesh_shear.py:2001-2005`). **Shear is the template for a
falloff actor**: it mutates bmesh every tick, always from stored originals
(`apply_records` / `restore_records`, `mesh_shear.py:650-679`), never incrementally.

**Drag input idioms** to reuse: pixel→unit calibration (`_pixel_to_offset`,
`mesh_straight_bevel.py:283`), projected-onto-screen-axis drag with cursor warp
(`ExtrudeMixin._extrude_modal`, `mesh_shear.py:1057-1154`), hover-then-grab handle with
`HANDLE_PX = 14`, `DIGIT_TYPES` numeric entry, Shift precise / Ctrl snap.

**Drawing** — `ui/draw/primitives.py` (`line`, `polyline`, `edges_3d`, `points`, `tris`,
`rect_2d`, role-themed), `ui/draw/state.py :: draw_scope`, `Role.HANDLE / HANDLE_HOVER /
PIVOT / GHOST_*`. World-space `POST_VIEW` precedent with depth pre-pass and axis-as-handle
in `object_radial_array.py:1009-1075`. Ring/circle drawing exists only in pixel space
(`mesh_visual_uv.py:120-127`) — a world-space ring primitive is a gap.

**Widgets** — `ui/widgets/` is a 2D panel system (`Slider`, `Dropdown`, `ButtonGroup`,
`InputField`), pytest-covered, bpy-free controls. Suitable for a **Falloff panel**
(type dropdown, shape, radius slider, invert, mix mode) that persists like Modo's tool
properties. Not a 3D gizmo system; no `bpy.types.Gizmo` anywhere in the repo.

**Spatial** — `mathutils.kdtree` already used (`utils/picking.py:421`), `BVHTree`
raycasts, `closest_edge_screen`, `nearest_vertex_screen` for element picking.

**Math cores** — bpy-free `utils/*_core.py` modules with pytest mirrors
(`tests/test_<name>_core.py`). A `utils/falloff_core.py` (shape curves, primitive weight
functions, mix modes, Dijkstra) follows the established convention exactly.

**Rust** — pyo3 workspace with one crate (`mesh_uv_shortest_mark_lib`) that already
implements graph `dijkstra`/`astar`/`nearest_vertex`. No `.pyd` is checked in; Python
fallback is mandatory. A topology-distance path for Element/Soft-Selection falloffs could
extend that crate rather than adding one.

**Absent** — zero references to `use_proportional_edit`, soft selection, per-vertex
weighted transforms, or easing outside HUD animation. Greenfield.

---

## 6. Architecture options

### Option A — Falloff as a parameter of one new "Soft Transform" modal

One operator `iops.mesh_soft_transform` with G/R/S sub-modes (rmKit / YT-Tools model).
Falloff type and handles live inside the modal; state resets each invoke (optionally
re-seeded from `Scene.IOPS` last-used values).

- Pros: matches every existing iOps modal; smallest surface; no cross-operator state.
- Cons: not Modo's mental model — falloff dies with the tool; cannot combine with other
  iOps actors (shear, hinge, extrude) without duplicating code.

### Option B — Persistent falloff state + falloff-aware actors (recommended)

Split Modo-style:

1. **Falloff state** on `WindowManager` (session) mirrored to `Scene.IOPS` for last-used:
   `type`, `center`, `axis/start/end`, `size`, `shape`, `in/out`, `invert`, `strength`,
   `mix_mode`, `use_connectivity`. Possibly a small collection for stacking.
2. **`utils/falloff_core.py`** (bpy-free): `weight_linear`, `weight_radial`,
   `weight_cylinder`, `weight_screen`, `weight_element`, `weight_soft_selection`,
   `shape_curve`, `mix`, `topo_distances`. pytest-covered.
3. **`iops.mesh_falloff` modal** — the *setup* tool: pick type, draw/drag handles
   (center, radius ring, start/end), Auto Size, Invert, Shape cycle. Confirms into state
   and exits; falloff stays "armed" (HUD badge + optional weight-colour preview via a
   persistent `POST_VIEW` handler).
4. **`iops.mesh_soft_transform` modal** — the actor: G/R/S with mouse drag, reads armed
   falloff, computes weights once at invoke (cached by mesh/selection hash), applies the
   §4 formulas each tick from originals, one undo step on confirm.
5. Later: existing iOps actors (shear, hinge, extrude offset) read
   `falloff_core.weights_for(bm, state)` and multiply — cheap once the core exists.

- Pros: true Modo semantics (persist, re-use, stack), follows iOps split of core/modal/HUD,
  incremental delivery (Radial + Linear first), testable math.
- Cons: two operators + shared state; need a clear "falloff armed" indicator and an
  Esc/(none) to disarm; weight cache invalidation on topology edits.

### Option C — GizmoGroup-driven redo operator

Blender-native pattern (Shear/To Sphere): persistent `GizmoGroup` handles edit props on a
`REGISTER, UNDO` operator and call `execute()` on every drag.

- Pros: handles are native, tool-system integration, no custom hit-testing.
- Cons: redo-execute re-runs the full weight computation per drag tick; gizmos cannot
  coexist with the modal input style every other iOps tool uses; keymap/tool-system
  plumbing is foreign to the codebase. Not recommended for v1.

**Recommendation**: Option B, phased.

| Phase | Scope |
|---|---|
| 1 | `falloff_core.py` + tests: shape curves, Linear, Radial, Cylinder, mix/invert |
| 2 | `iops.mesh_falloff` setup modal for Radial + Linear with Auto Size, handles, HUD; WM state |
| 3 | `iops.mesh_soft_transform` G/R/S actor reading armed falloff |
| 4 | Screen falloff (Soft Drag), Element falloff, Soft Selection with connectivity (Dijkstra; Rust optional) |
| 5 | Weight preview overlay, stacking with mix modes, bake to vertex group |
| Parked | Airbrush, Noise, Curvature, Path, Lasso, Image, Coplanar, Selection (inward Steps) |

---

## 7. Risks and unknowns

- **Performance** on 100k+ vert meshes: Python `v.co` assignment loop per tick plus
  edit-mesh GPU upload. Mitigation: only touch `w > 0` verts; numpy for math; measure
  before optimising; Rust write-back is *not* possible (bmesh is Python-side).
- **Weight cache invalidation**: any topology edit between arming and transforming
  invalidates vertex indices. Key cache on `(mesh.session_uid, len(bm.verts),
  len(bm.edges), selection hash)`; recompute on mismatch.
- **Modo shape curves are unpublished.** Ship Blender's eight curves plus Modo's four
  names mapped to plausible formulas; expose In/Out only if a Bezier-tangent model proves
  worth it.
- **Multi-object edit mode**: Modo's Use World Transforms. v1 = active object only.
- **UV editor**: rmKit and YT-Tools support UV falloff transforms. Out of scope for v1
  but `falloff_core` should stay dimension-agnostic (2D/3D tuples).
- **blf SHADOW** convention and the `_finish` bmesh-null rule apply to both new modals.

---

## 8. Open questions for the user

1. Scope of v1: Radial + Linear only, or also Screen (Soft Drag) and Element?
2. Modo-persistent falloff (Option B) vs one-shot tool (Option A)?
3. Should existing iOps actors (shear, hinge, extrude) honour the armed falloff, or is
   a dedicated Soft Transform enough?
4. Preferred activation: dedicated hotkey for the setup modal, or a widget panel
   (`ui/widgets`) with type/shape/radius controls plus a hotkey for the actor?
5. Weight preview colouring while armed: always, toggle, or never?
6. Rust for topology distance in Phase 4, or Python-only?

---

## Sources

Modo: learn.foundry.com/modo/content/help/pages/modeling/selection_falloffs/*.html
(linear, radial, cylinder, screen, element, airbrush, noise, curvature, vertex_map, path,
lasso, image, selection, soft_selection, coplanar), tool_pipe.html, deform_geometry/twist,
taper, soft_move, soft_drag, element_move, soft_selection_move; SDK `lx-tool.hpp` wiki,
Meta.falloff.html, Tool spikey tutorial; Pixel Fondue "Introduction to Falloffs" (2018);
kondratiki.pro Modo course (falloff pages).
Blender: `transform_generics.cc`, `transform_convert.cc`, `transform_convert_mesh.cc`,
`transform_mode*.cc`, `brush.cc`, `math_geom.cc`, sculpt `grab.cc`,
`scripts/templates_py/Gizmo/operator.py`; release notes 4.5 / 5.0 / 5.1 / 5.2 Python API;
issues #106459, #88021; devtalk #28499, #6903, #12767; local manual RST
`proportional_editing.rst`, `bpy.ops.transform.rst`, `gpu.shader.rst`, `bpy.types.Gizmo.rst`.
Addons: tazee.github.io/yt-tools, github.com/roosterMAP/rmKit,
github.com/mifth/mifthtools (`mi_linear_deformer.py`, `mi_widget_linear_deform.py`),
Bezier Mesh Shaper / Falloff Lens / Falloff Tool on Superhive, Modo-Me thread on
blenderartists. Maya Soft Select and 3ds Max Soft Selection help pages; 3ds Max SDK
`meshadj.h`.
