# iOps Falloff Tools (Move / Rotate / Scale) — Design

Date: 2026-09-07
Status: approved

Research and rationale: [2026-09-07-modo-falloff-analysis.md](2026-09-07-modo-falloff-analysis.md).

## Goal

Three modal edit-mesh tools that transform the selection with a Modo-style falloff weighting
each vertex: `iops.mesh_falloff_move`, `iops.mesh_falloff_rotate`, `iops.mesh_falloff_scale`.
Falloff type is switched inside the modal by hotkey; the HUD lists every type. v1 falloffs:
**Linear, Radial, Screen, Coplanar**, plus an **Element (connected-only)** toggle.

## Selection model

- Affected set = selected verts. If nothing is selected, every visible vert.
- Coplanar is the one falloff that grows *outside* the selection (Modo Soft-Selection-like).
- Pivot = bounding-box centre of the selected verts (Modo "Selection" action centre).
  Coplanar keeps the pivot on the original selection.
- Hidden verts are never touched.
- Active object only. Object-space math; drag deltas converted from world via
  `matrix_world.inverted()`.

## Interaction

Modo click-drag, tool stays live between drags.

- **Invoke**: build bmesh, snapshot originals `P0` (numpy, affected subset + index map),
  auto-fit the current falloff to the selection bbox, draw handles and HUD. Nothing moves.
- **LMB press on a handle** → drag that handle (Radial centre / radius ring, Linear start /
  end). Hover test `HANDLE_PX = 14` against hotspots rebuilt every draw (shear pattern).
- **LMB press elsewhere** → transform drag. Weights `W` are computed at press. Mouse move
  applies `P = f(P0, W, amount)`. **LMB release** bakes: `P0 ← P`, tool stays modal.
- **Enter / Space** confirm → `bm.normal_update()`, `update_edit_mesh`, save last-used
  params to `Scene.IOPS`, `bpy.ops.ed.undo_push`, finish.
- **Esc / RMB** cancel → restore invoke-time originals (all baked drags undone), finish.
- **Wheel up/down** adjusts the active falloff's scalar: Radial radius, Linear length
  (moves End along the ramp), Screen px radius, Coplanar angle. Shift = fine step.
- **Shift** during transform drag = precise (×0.1). **Ctrl** = snap (move: 0.1 unit steps,
  rotate: 5°, scale: 0.1).
- **Digits / minus / period / backspace** = numeric amount for the transform (existing
  `DIGIT_TYPES` idiom); Enter applies and confirms.
- **X / Y / Z** = constrain move/scale to an object axis, or set the rotation axis.
  Press again to clear. Rotate default axis = view axis.
- Navigation keys pass through (`MIDDLEMOUSE`, wheel is *not* passed through here —
  it is claimed for radius; `NDOF*`, `TRACKPAD*` pass).
- **H** help overlay, **/** HUD params toggle via the shared `handle_*` calls.

### Falloff hotkeys (HUD "Falloff" section, `HUDItem` per row, active row highlighted)

| Key | Action |
|---|---|
| **L** | Linear |
| **R** | Radial |
| **S** | Screen |
| **C** | Coplanar (disabled row when no face/edge selection) |
| **E** | Element toggle (connected only) |
| **F** | cycle Shape |
| **I** | Invert |
| **A** | Auto-size: refit active falloff to selection bbox |
| **V** | weight preview toggle |

Switching type mid-drag is ignored; type/shape/invert/element changes between drags
re-fit nothing except when **A** is pressed or the type changes (a type change auto-fits
the new type once).

## Falloff definitions

All weights clamp to `[0, 1]`, then `w = shape(w)`, then `w = 1 − w` if inverted.
`shape` ∈ {LINEAR `x`, SMOOTH `3x²−2x³`, SHARP `x²`, ROOT `√x`, SPHERE `√(2x−x²)`,
INVERSE_SQUARE `x(2−x)`, CONSTANT `1`} — Blender's names and formulas (Random omitted).
Modo Ease-In ≈ SHARP, Ease-Out ≈ INVERSE_SQUARE, Smooth ≈ SMOOTH.

**Linear** — Start `S`, End `E` in object space. `t = clamp(((p−S)·(E−S)) / ‖E−S‖²)`,
`w = 1 − t` (full weight at Start). Auto-fit: along the longest bbox axis, `S`/`E` at the
bbox faces. Handles: `S`, `E` (drag in the view plane through the handle). Draws the segment
plus a short perpendicular tick at each end.

**Radial** — centre `C`, radius `r`. `w = 1 − ‖p−C‖/r`. Auto-fit: `C` = bbox centre,
`r` = half bbox diagonal (min 1e-4). Handles: `C` (drag in view plane), ring (drag changes
`r` = distance from `C` to the projected mouse ray point). Draws three orthogonal rings.

**Screen** — centre = mouse position at LMB press (region px), radius `r_px`.
`w = 1 − ‖proj(p) − mouse‖ / r_px` where `proj` = `location_3d_to_region_2d` of the
world-space vert; verts behind the camera or off-region get 0. Re-centres on every drag
(Modo Soft Drag). No handles; wheel sets `r_px`. Draws a 2D ring at the last centre.

**Coplanar** — reference normal `n_ref` = normalised mean of selected face normals; with an
edge-only selection use the mean of the faces adjacent to the selected edges. Angle range
`α` (default 15°). Per-face weight `w_f = 1 − angle(n_f, n_ref)/α`; per-vertex weight =
max over its faces. Affected set = all verts of faces with `w_f > 0`, plus the original
selection at weight 1. With Element on, only faces reachable from the selection by walking
across edges between faces with `w_f > 0` participate (region grow). Coplanar row is
disabled and cannot be activated when the selection holds no faces or edges.

**Element toggle** (all types) — BFS over `link_edges` from the selected verts; any affected
vert not reached gets `w = 0`. Coplanar applies its own grow instead (above). Cached per
invoke and invalidated on bake (topology does not change during the modal, so the cache
survives).

## Transform math

Applied every tick from the current originals `P0` (N×3 numpy, object space), pivot `Cp`,
weights `W` (N×1):

- Move: `P = P0 + W · Δ`. `Δ` = mouse delta mapped into the view plane through `Cp` via
  `region_2d_to_location_3d`, converted to object space, then projected onto the axis
  constraint if set.
- Rotate: axis `k` (view axis or X/Y/Z), angle `θ` from the mouse's `atan2` around the
  projected pivot (Blender R feel). Rodrigues with per-vertex angle `W·θ`:
  `v = P0 − Cp; P = Cp + v cos(Wθ) + (k×v) sin(Wθ) + k (v·k)(1 − cos(Wθ))`.
- Scale: `s` = current mouse–pivot distance / press distance (uniform), or per-axis vector
  when constrained. `P = Cp + (1 + W (s − 1)) (P0 − Cp)`.
- Write back only rows with `W > 0`: Python loop assigning `v.co`, then
  `bmesh.update_edit_mesh(me, loop_triangles=False, destructive=False)`. `normal_update`
  only on confirm.

## Drawing

- `POST_VIEW` handler: falloff geometry (Linear segment + ticks, Radial rings, handles as
  `Role.HANDLE` / `HANDLE_HOVER` points, pivot as `Role.PIVOT`), and the weight preview:
  affected verts as points coloured purple (0) → yellow (1). Needs two new primitives in
  `ui/draw/primitives.py`: `ring_3d(center, normal, radius, *, role|color, segments=64)`
  and `points_colored(coords, colors, size)` (POINT_FLAT_COLOR).
- `POST_PIXEL` handler: Screen falloff ring, HUD (`HUDOverlay` with a "Falloff" section of
  `HUDItem`s and `HUDParam`s for radius/angle/amount), Help overlay. Wrap text in
  `text.isolated()`.
- Both via `safe_handler_add(..., tick=True)` for the POST_PIXEL one.

## State and persistence

- Modal-local: `P0`, index map, `W`, pivot, falloff geometry (`S`, `E`, `C`, `r`, `r_px`,
  `α`), drag phase, numeric input, hotspots.
- `Scene.IOPS` last-used (read at invoke, written at confirm): `falloff_type` (enum),
  `falloff_shape` (enum), `falloff_invert`, `falloff_connected`, `falloff_preview`,
  `falloff_screen_radius_px` (default 150), `falloff_coplanar_angle` (default 15°).
  Geometry is never persisted; auto-fit rebuilds it.

## Undo / safety

- `bl_options = {"REGISTER"}`; `bpy.ops.ed.undo_push(message="Falloff Move|Rotate|Scale")`
  after the final `update_edit_mesh` on confirm only (shear rationale, `mesh_shear.py:1426`).
- `modal()` two-layer wrapper: `ReferenceError` → `_finish` + `CANCELLED`.
- `_finish` removes both handlers, clears status text, nulls `bm`, `obj`, numpy arrays,
  vert list (redo-stack dealloc crash guard).
- Cancel restores invoke-time coordinates even after several baked drags.

## Files

- `utils/falloff_core.py` — bpy-free, tuple/numpy math: `shape_curve(name, x)`,
  `weight_linear(P, S, E)`, `weight_radial(P, C, r)`, `weight_screen(P2, c2, r_px)`,
  `weight_coplanar_faces(face_normals, n_ref, angle)`, `connected_mask(adjacency, seeds, n)`,
  `coplanar_grow(face_adjacency, face_weights, seed_faces)`, `apply_invert`,
  `apply_move(P0, W, delta)`, `apply_rotate(P0, W, pivot, axis, angle)`,
  `apply_scale(P0, W, pivot, s)`.
- `tests/test_falloff_core.py` — written first; one behaviour per test, `pytest.approx`.
- `operators/falloff/__init__.py`, `common.py` (`FalloffToolMixin`: state, HUD build,
  hotkeys, handles, weights, drawing, finish), `ops.py` (three operators).
- `ui/draw/primitives.py` — `ring_3d`, `points_colored`.
- `prefs/addon_properties.py` — the seven `Scene.IOPS` props.
- `__init__.py` — import + `classes` entries.
- `docs/operators/op_mesh_falloff_tools.md` + `mkdocs.yml` nav entry.

## Testing

- pytest on `falloff_core`: curve endpoints and monotonicity; linear weights at S/E/mid and
  beyond; radial at centre/edge/outside; screen off-region → 0; coplanar angle threshold;
  connected mask on a two-island graph; coplanar grow stops at a hard edge; move/rotate/
  scale with `W=1` equal rigid transforms and with `W=0` leave `P0` untouched; rotate with
  `W=0.5` gives half angle.
- Live Blender: cube + subdivided plane fixtures; each type × each tool; Element toggle on a
  two-island mesh; cancel after two baked drags restores exactly; undo pops one step;
  redo-stack crash check (confirm, then Ctrl+Z twice).

## Out of scope (parked)

Cylinder, Element-origin mode (click element as origin), Soft Selection radius outside the
selection, stacking / mix modes, In/Out custom curve, UV editor, multi-object edit,
bake-to-vertex-group, in-modal Ctrl+Z drag history, Rust acceleration (revisit if profiling
shows the BFS or `v.co` loop dominates on 100k+ verts).
