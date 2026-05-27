# Object Aligner — Design Spec

Date: 2026-05-27
Operator: `IOPS_OT_Object_Aligner` (`iops.object_aligner`)
File: `operators/object_aligner.py`

## Purpose

Modal operator that transfers a "rig" of objects (the current selection) from one
anchor object onto an array of identical objects, by picking the targets one by
one with a viewport raycast. For every target the whole selection is duplicated
while preserving each object's transform **relative to a picked reference
(anchor)**.

Use case: a base object has a set of objects placed around it (convex collisions,
detail props, sockets …). The user has many copies of that base object in the
scene. With Object Aligner they pick the base as reference, then click each other
copy — the full set is stamped onto it in the same relative arrangement, in one
modal session.

This complements the existing `iops.object_replace` (which needs all targets
pre-selected): the value here is **interactive raycast picking** plus
**topology-aware alignment** for baked transforms.

## Core math

Selection = source set `{S_i}` (objects to duplicate). One picked reference `R`
(anchor). Each picked target `T` produces, per source object:

```
M_new_i = T_fit @ M_sel_i
```

where `T_fit` is the transform that maps the reference onto the target. There are
two ways to obtain `T_fit`, chosen automatically per target:

### Matrix fit (fallback)
When the target's topology does **not** match the reference (different vertex
count → no correspondence):

```
T_fit = M_target_obj @ M_ref_obj⁻¹
```

Pure object-matrix relative transform. Fast, but wrong when the target's
transform was baked (Ctrl+A applied) — then `M_target_obj` no longer reflects the
geometry's real orientation/scale.

### Geometry fit (primary)
When reference and target share topology (`len(verts)` equal → known
vertex-index correspondence), recover `T_fit` from the **world-space vertex
clouds** instead of the object matrices. This is a point-set registration with
known correspondence and is correct whether or not the target's transform is
baked, because it reads the actual geometry:

```
ref_world[i]    = M_ref_obj    @ ref.data.vertices[i].co
target_world[i] = M_target_obj @ target.data.vertices[i].co
T_fit = solve(ref_world -> target_world)
```

Geometry fit is a strict superset of matrix fit: when transforms are NOT baked,
the two world clouds differ by exactly `M_target_obj @ M_ref_obj⁻¹`, so the
solve returns the same result as the matrix formula. We therefore prefer
geometry fit whenever topology matches, and fall back to matrix fit only when it
cannot apply.

### Solve methods (scale behaviour)
The registration solve is parameterized by a scale mode (Umeyama family). The
solver lives in a small reusable helper so additional methods can be added later
without touching the operator:

- **Keep** — rigid, rotation + translation only (Kabsch): centre both clouds,
  SVD of cross-covariance `H = Σ ref·targetᵀ`, `R = V·Uᵀ` with `det` correction
  against reflection, `t = c_target − R·c_ref`.
- **Uniform** (default) — similarity, rotation + translation + uniform scale
  (Umeyama): Kabsch plus `s = trace(ΣD)/σ²_ref`.
- **Stretch** — affine, allows non-uniform scale + shear: least-squares fit of a
  3×4 affine matrix over all corresponding vertices.

All three use NumPy (bundled with Blender) for SVD / least-squares. Methods not
in the initial cut (Horn quaternion, RANSAC, 3-point frame) are deliberately out
of scope but the helper signature (`method=` parameter) leaves room for them.

The HUD shows which fit was used per hovered target (`Fit: geometry` /
`Fit: matrix`) and the current scale mode (`Scale: Uniform`).

## Interaction flow

1. **Invoke** — capture `context.selected_objects` as the source set. If empty →
   report warning, `CANCELLED`. Add POST_VIEW draw handler + HUD/Help overlays,
   start modal.
2. **Pick reference** — first LMB raycast onto a scene object that is **not** in
   the source set. The picked object is highlighted with an active-state theme
   role (`GHOST_ACTIVE` tint + `ACTIVE_LINE` outline). Its `matrix_world` /
   geometry become the alignment base. HUD mode switches to *Stamp*.
3. **Pick targets** — each subsequent LMB raycast onto a non-source object stamps
   a duplicate of the whole source set, transformed by `T_fit` (auto-selected
   geometry/matrix). The modal stays open (many targets per session).
4. **Re-pick reference** — `R` re-enters reference-pick mode; the next LMB
   re-assigns the anchor.
5. **Ghost preview** — once a reference exists, hovering a valid object draws a
   live ghost of the source set where it would land if clicked, using the same
   POST_VIEW ghost machinery as `object_radial_array` (cached local geom →
   world-transformed tris/edges/points, two-pass depth fill).
6. **Finish** — `Enter` / `Space` / RMB applies and exits. `Esc` cancels and
   removes everything stamped during the session.

## Keys (mirrors object_radial_array conventions)

- **LMB** — pick reference (first) / pick target (after)
- **R** — re-pick reference
- **D** — Clone type: `DUPLICATE` (full copy) ↔ `INSTANCE` (linked data)
- **S** — Scale mode: `Keep` / `Uniform` / `Stretch` (cycles)
- **H** — toggle HUD / Help
- **Enter / Space / RMB** — apply & exit
- **Esc** — cancel

## Picking

Use `utils/picking.raycast_from_mouse`. Source-set objects must be excluded from
picking (the rig must never be selectable as reference/target). Add a blocklist
path: iterate raycast hits, piercing through any object that is in the source set
(or is the current reference, for target picks), until a permitted object is hit
or iterations run out. This reuses the existing iterate-and-offset loop in
`raycast_from_mouse`; extend it with an `exclude=` set rather than only the
`restrict_to=` allowlist.

## Duplication

- **Data**: `D` toggles full copy vs linked instance, like
  `object_replace.use_linked_data` — full copy duplicates mesh data, instance
  shares it.
- **Hierarchies**: each source object's child hierarchy is duplicated preserving
  `matrix_local` (same approach as `object_replace.duplicate_group_hierarchy`),
  then the root is placed at `T_fit @ M_sel_root`.
- **Collection**: stamped copies go into a **sub-collection of the source
  object's collection**, named `<source_collection_name>_<target_object_name>`.
  The sub-collection is created on first use per target and reused on subsequent
  stamps onto the same target.

## Rendering (reuses object_radial_array infra)

- POST_VIEW ghost preview of the source set at the hovered target position:
  `_mesh_geom_cache(obj)` → cached `(verts_local, edge_pairs, tri_idx)` →
  `_mesh_edge_segments_world` / `_mesh_face_tris_world` → `iops_draw.tris`,
  `edges_3d`, `points`. Two-pass depth-prepass + `depth=EQUAL` fill to avoid
  alpha stacking on overlapping clones.
- Reference object highlighted via active theme roles (`GHOST_ACTIVE`,
  `ACTIVE_LINE`, `ACTIVE_POINT`).
- All colours come from `ui/draw/theme.Role` (`GHOST_DEFAULT`, `GHOST_EDGE`,
  `PREVIEW_POINT`, …) — no hard-coded colours.
- `safe_handler_add` / `safe_handler_remove` for handler lifecycle.

## HUD (reuses object_radial_array infra)

- `HUDOverlay("object_aligner")`, title "Object Aligner", with `HUDParam` rows:
  - Mode (`Pick reference` / `Stamp`)
  - Reference name (`visible_getter` → only after reference picked)
  - Clone type (`DUPLICATE` / `INSTANCE`)
  - Scale mode (`Keep` / `Uniform` / `Stretch`)
  - Fit method of last hovered target (`geometry` / `matrix`)
  - Stamped count (int)
- `HelpOverlay("object_aligner")` listing all keys above; `H` toggles via
  `handle_hud_toggle` / `handle_help_toggle`; `capture_event` feeds the last
  event to the draw callback.

## Edge cases

- **Reference == target** (clicking the same object): `T_fit` ≈ identity → places
  the rig on top of the originals. Allowed; no special handling beyond it being
  visible to the user.
- **Topology mismatch** (different vert count): geometry fit cannot run → matrix
  fit fallback, surfaced in HUD as `Fit: matrix`.
- **Reflection**: Kabsch/Umeyama force `det = +1` (no accidental mirror). Genuine
  mirrored targets are not handled in this cut — would need the affine `Stretch`
  mode or a future reflection-aware method.
- **No selection on invoke** → warning + `CANCELLED`.
- **Picked object deleted / matrix invalid mid-modal** — guard `matrix_world`
  access with `ReferenceError` try/except, as radial array does.

## Registration

Register the operator class in the addon `__init__` and add it to `utils/iops_dict`
and the default hotkeys (`prefs/hotkeys_default.py`) following the pattern of the
other object operators. Exact wiring is determined during the implementation
plan.

## Out of scope (future)

- Horn quaternion, RANSAC, and 3-point-frame solve methods (helper API leaves
  room via a `method=` parameter).
- A REPLACE clone type (delete the target on stamp) — explicitly excluded.
- Redo-panel re-execution with stored matrices (this operator is interactive;
  it does not need the `stored_matrices` mechanism `object_replace` uses).
