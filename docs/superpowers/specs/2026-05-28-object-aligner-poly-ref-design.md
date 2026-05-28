# Object Aligner — Polygon Reference Mode

**Date:** 2026-05-28
**Author:** Titus + Claude
**Status:** Design — pending implementation
**Operator:** `iops.object_aligner` ([operators/object_aligner.py](../../../operators/object_aligner.py))
**Related spec:** [2026-05-27-object-aligner-design.md](2026-05-27-object-aligner-design.md)

## Problem

Today the aligner uses a whole **object** as reference. That works when the rig should ride on objects with identical topology (geometry-fit) or otherwise reuse another object's transform (matrix-fit). It breaks down when the user wants to align onto a **specific region** of geometry — a flange, a socket, a panel — that does not coincide with object boundaries. The reference and the target may even live on the same object.

This spec adds a **polygon-reference mode**: the user marks a set of polygons (the "ref poly set"), then marks one or more sets of target polygons on any non-rig objects. Each connected target poly group becomes a stamp site. Topology-aware fit is used when the target group matches the ref's shape signature; a PCA-frame fallback handles non-matching groups when the user explicitly opts in.

## Goals

- Pick reference and target by **polygons**, not whole objects.
- Selection helpers: linked island (Shift), similar-by-normal/area (Ctrl), deselect (Alt).
- Strict shape matching for confident Procrustes-based fit when ref and target are the "same shape".
- Optional similarity highlight (`A`) — finds candidate groups in the scene that match the ref signature, on both target objects and the ref object itself.
- Optional force-mode (`W`) — fall back to PCA-frame fit for non-matching target groups.
- Coexist with the existing object-only flow: if the user never presses `Q`, behavior is unchanged.

## Non-goals

- Edit-mode polygon picking via Blender's built-in face select (we draw our own overlay; no mode switch).
- Cross-object connectivity (Blender connectivity does not cross datablocks — `islands` are per-mesh; multi-object selections are unions of per-mesh islands).
- Persistent ref poly sets across operator invocations.
- Vertex/edge reference picking (faces only).

## User flow

```
invoke (rig selected in viewport)
  → LMB pick ref object              [unchanged from current MODE_PICK_REF]
  → MODE_STAMP                       [unchanged: LMB now stamps onto objects]
  → press Q
  → MODE_PICK_REF_POLY               [new]
       LMB        toggle one polygon under cursor
       Shift+LMB  add linked island (per-mesh BFS across shared edges)
       Ctrl+LMB   add similar-by-normal+area on the same object
       Alt+LMB    remove polygon (or its island if no plain selection at site)
  → press Q
  → commit ref poly set; cache signature, world-space point cloud, PCA frame,
    bbox diagonal. MODE_PICK_TARGET_POLY.
       LMB / Shift / Ctrl / Alt — same picking semantics, builds target set
       A          toggle "highlight similar" search
                  (find connected components on all non-rig objects whose
                  signature matches ref; render as match-hints)
       W          toggle force-mode (allows PCA-frame fit for non-match groups)
  → press Enter / Space / RMB → Apply
       For each connected target poly group on each object:
         - if strict-match → Procrustes (Kabsch) fit, RMSE/diag < 5% → stamp
         - elif force-mode on → PCA-frame fit → stamp
         - else → skip with report
       Same _realize_pending flow as today.
  → Esc → cancel, same cleanup as today.
```

Pressing `Q` again from `MODE_PICK_TARGET_POLY` is a no-op for now (we keep `Q` for the ref-marking transition only; future extension may re-enter ref-marking).

## Key design decisions

### "Match" is two tiers

Different operations need different strictness, so we run two separate similarity criteria.

**Strict tier** — gates Procrustes-based geometry fit on Apply.
Requires **all** of:
1. Total selected vertex count equal between ref and target.
2. Face count equal.
3. Per-face vertex-count histogram equal as multisets (same number of tris, quads, n-gons grouped by vertex count).
4. After Procrustes alignment of the two point clouds (using greedy nearest-neighbor correspondence seeded by PCA-frame alignment), `RMSE / bbox_diag(ref) < ε`. Default `ε = 0.05`, exposed as a **dynamic HUD param** (`Alt+Wheel` adjusts in 0.005 steps, clamped to `[0.001, 0.5]`).

If strict-tier passes, the Procrustes transform is the fit matrix.

**Loose tier** — gates `A`-key candidate highlighting only. Never auto-stamps.
PCA-eigenvalue-ratio distance `< 0.10` **and** D2 shape-distribution χ² `< τ` (`τ` constant in code, calibrated empirically). PCA ratios are computed from the centered point cloud's covariance matrix eigenvalues normalized to sum=1; comparison is L1 on the sorted triple. D2 is the histogram of pairwise distances between random surface points, normalized by bbox diagonal so the comparison is scale-invariant.

Loose tier is purely visual: it draws hint overlays, the user still has to click to add the group to the target set.

### Force-mode (`W`) — PCA-frame fallback

When ref and target don't satisfy strict-tier, we cannot solve correspondence. The fallback computes a **frame** on each side and aligns them:

For both ref-set and a target-group:
- `origin` = area-weighted centroid of selected face centers.
- `Z` (normal) = normalized sum of `face_normal · face_area` over selected faces.
- `X` (tangent) = principal axis from PCA of selected vertices, projected onto plane `⊥ Z`, then renormalized. If projection length `< 1e-4` (degenerate — the principal axis is parallel to Z), fall back to projection of the second PCA axis; if that is also degenerate, pick any vector orthogonal to Z.
- `Y` = `Z × X`.

Fit matrix `T = frame_target · frame_ref⁻¹`. This handles arbitrary topology and always produces a sensible placement; the only ambiguity is 180° flip around `Z` for symmetric shapes, which we mitigate by aligning `X` so that `(target_centroid - target_ref_centroid)` has non-negative dot with target `X` (a deterministic but arbitrary tiebreak).

Force-mode is opt-in to prevent surprise garbage stamps: in default mode, non-match groups are silently skipped and reported in the final summary.

### Connected components are the unit of action

Inside both `MODE_PICK_TARGET_POLY` and the `A`-highlight search, we treat **connected components** (per-object, BFS over shared edges within the selected face set) as the atom of "a group". This is why:
- Strict-tier is computed per component, not per object — one object may contain several stamp sites.
- `A` returns per-object lists of matching components.
- Apply iterates components, not objects.

Multi-object target selections work because each object's selected faces decompose into their own components independently.

### Role of `ref_obj` once poly mode is entered

The user still picks a reference **object** (via LMB in `MODE_PICK_REF`) before pressing `Q`. After `Q` the ref *geometry* is the poly set, not the whole object. We keep `self.ref_obj` set for two reasons:
1. The hover preview before the first ref poly is marked still draws the ref-object surface as a visual hint of "where to mark from".
2. Cancel/cleanup pathways already key off `ref_obj`.

Once `op.ref_polys` is non-empty, the whole-object ref highlight in `_draw_preview_3d` is suppressed; only the marked polys are drawn.

### Picking pipeline

`raycast_from_mouse` already returns face index ([utils/picking.py](../../../utils/picking.py)). The `_pick` helper today returns `obj.original` only; in poly modes it must also return the hit `face_index`. Internal storage uses `obj.original` as the key.

`Shift+LMB` (linked island): given hit `(obj, face_idx)`, BFS expand via mesh's face-edge-face adjacency, terminating at the mesh boundary (an edge with only one face) or at non-manifold edges (>2 faces). The expansion **does not** terminate at already-selected polygons — they are simply unioned into the result, so re-shift-clicking the same island is idempotent. Pure mesh-data read (no bmesh `from_edit_mesh`); we use a cached `bmesh.new(); bm.from_mesh(obj.data)` per object created lazily and freed on operator exit.

`Ctrl+LMB` (similar-by-normal-area): on the same object, scan all faces, accept those with `angle(n, hit_n) < 5°` and `|area - hit_area| / hit_area < 10%`. Constants in code.

`Alt+LMB`: if the hit face is selected, remove it; else if it belongs to a previously-selected island (computed on the fly), remove the whole island.

### Drawing roles

New role names go in [ui/draw/theme.py](../../../ui/draw/theme.py):

| Role | Use |
|---|---|
| `GHOST_ACTIVE` (existing) | Ref poly set fill (replaces "ref object surface" highlight). |
| `GHOST_TARGET_SEL` (new) | Selected target poly set fill (current pre-Apply selection). |
| `GHOST_PREVIEW` (existing) | Hovered polygon outline in poly modes. |
| `GHOST_MATCH_HINT` (new) | `A`-key candidate components — dim fill, distinct hue. |
| `GHOST_DEFAULT` / `GHOST_EDGE` / `GHOST_PREVIEW` | Rig ghost rendering (unchanged). |

We extend `_draw_preview_3d` to render these in addition to the existing ref-object surface (now suppressed when `op.ref_polys` is non-empty — the ref-polys overlay supersedes the whole-object highlight).

The dynamic RMSE threshold preview: while hovering a single component candidate (or after Apply-dry-run on toggle), show the per-component RMSE in the HUD next to the threshold value, so the user can dial `ε` to include/exclude borderline matches.

## Data model

Added to operator state:

```python
self.ref_polys = {}           # dict[obj_original -> set[face_index]]
self.target_polys = {}        # dict[obj_original -> set[face_index]] — current edit set
self.ref_signature = None     # (vert_count, face_count, face_vcount_histogram_tuple, bbox_diag)
self.ref_points_np = None     # Nx3 world-space vertex cloud for Procrustes
self.ref_pca_ratios = None    # (r1, r2, r3) normalized eigenvalues
self.ref_d2 = None            # D2 histogram (np.ndarray)
self.ref_frame = None         # mathutils.Matrix (PCA frame, world space)
self.ref_bbox_diag = 0.0
self.match_hints = {}         # dict[obj_original -> list[set[face_index]]] — from A-search
self.show_match_hints = False
self.force_mode = False
self.match_rmse_threshold = 0.05  # adjustable via Alt+Wheel
self._bmesh_cache = {}        # dict[obj_original -> bmesh] for selection helpers
```

`MODE_PICK_REF_POLY` and `MODE_PICK_TARGET_POLY` are new mode-string constants.

## File layout

**New:** `utils/polygon_match.py` — numpy + bmesh data reads only; no `bpy.ops`, no operator/UI state. Contains:
- `face_island(bm, seed_face_idx, restrict_to=None) -> set[int]` — BFS via face-edge-face.
- `similar_by_normal_area(bm, seed_face_idx, ang_tol_deg=5.0, area_tol=0.10) -> set[int]`
- `components_in_selection(bm, face_idx_set) -> list[set[int]]` — connected components within a face subset.
- `signature(world_verts: np.ndarray, faces: list[list[int]]) -> Signature` — returns `(vert_count, face_count, face_vcount_hist, bbox_diag)`.
- `pca_ratios(world_verts: np.ndarray) -> tuple[float, float, float]`
- `d2_histogram(world_verts: np.ndarray, faces, samples=512, bins=32, seed=0) -> np.ndarray`
- `pca_frame(world_verts: np.ndarray, face_normals_areas) -> Matrix` — centroid + area-weighted normal + projected PCA tangent.
- `kabsch_with_scale(ref_pts: np.ndarray, tgt_pts: np.ndarray, scale_mode: str) -> tuple[np.ndarray, float]` — returns `(4x4 transform, rmse)`. Uses [utils/alignment_fit.py](../../../utils/alignment_fit.py)'s `solve_fit` underneath; this wrapper just exists to also return RMSE.
- `greedy_correspondence(ref_pts: np.ndarray, tgt_pts: np.ndarray) -> np.ndarray` — index permutation seeded by PCA-frame pre-alignment.

**Modified:** [operators/object_aligner.py](../../../operators/object_aligner.py) — adds modes, hotkeys, drawing branches, bmesh cache lifecycle.

**Modified:** [ui/draw/theme.py](../../../ui/draw/theme.py) — adds `GHOST_TARGET_SEL`, `GHOST_MATCH_HINT` roles.

**Modified:** [utils/alignment_fit.py](../../../utils/alignment_fit.py) — possibly adds an RMSE-returning variant if `solve_fit`'s internals make it cheaper than recomputing.

## Algorithms in more detail

### Greedy correspondence for Procrustes on equal-count clouds

Strict-tier guarantees `len(ref_pts) == len(tgt_pts)`, but vertex order is not implied. We need a permutation. Doing optimal assignment (Hungarian) is O(n³) — too slow for interactive use on hundreds of vertices.

Approach:
1. Compute PCA frames on both clouds, apply `frame_ref → frame_tgt` as a rough pre-alignment of `ref_pts`.
2. Mutual nearest-neighbor via KD-tree on tgt: for each pre-aligned ref point find its nearest tgt; conflicts (multiple ref → same tgt) are resolved by sorting candidates by distance and assigning greedily, the loser falls back to its next-best tgt that is still unclaimed. Iterate this resolution until stable (typically 1-2 passes).
3. Run Kabsch on the resulting correspondence, get RMSE.
4. If RMSE/diag > 0.5 × ε (i.e. clearly not a match even by force), bail out — strict tier fails. Otherwise return the transform and RMSE.

This is the same pattern as in [object_radial_array.py](../../../operators/object_radial_array.py)'s spoke-matching — not novel for this codebase.

### D2 distance histogram

Sample N random points uniformly on the surface (per-face barycentric, face probability ∝ area), compute pairwise distances between random pairs, histogram into 32 bins normalized by bbox diag. Cache for ref. For each candidate component during `A`-search, compute D2 with the same RNG seed (so identical shape → identical histogram up to sampling noise). Compare via χ² distance.

Random sampling uses a fixed seed (0) per shape so repeated `A` presses give deterministic hints.

### Hovered-component RMSE preview

When the user hovers a face that belongs to a component in `op.target_polys` (or in `op.match_hints`), we run the strict-tier check on that component and surface its RMSE in the HUD. Cached per component to avoid recompute on every mouse-move.

## Failure modes and edge cases

- **Empty ref poly set on commit**: refuse `Q` commit, keep `MODE_PICK_REF_POLY`. Report "Ref set is empty".
- **Single polygon in ref**: PCA is degenerate (2D). Use that polygon's normal as Z, longest-edge direction as X. Strict-tier requires exact vertex/face match anyway, so degenerate-PCA only matters for force fit; this is a fine fallback.
- **Ref vertices coplanar (PCA λ₃ ≈ 0)**: use face-normal sum as Z directly (skip projection step).
- **Force-mode with target group of single polygon**: same handling as single-poly ref — well-defined frame, fits the use case of stamping onto flat panels.
- **Object deleted between ref capture and Apply**: stored `obj_original` references go stale. Wrap each access in `try/except ReferenceError` and drop the dead entry, matching existing patterns in the operator.
- **bmesh cache lifecycle**: bmesh instances are created lazily on first access per object and `bm.free()` is called from both `_finish` and `_cancel`. We do not mutate the mesh, but we still free to release C memory.
- **Rig overlapping ref/target objects**: rig is in `op.source_set`; poly picks exclude it via the same `exclude` set used for object pick. Ref object is *not* excluded from target picking (per user — target group may be on the ref object itself).
- **Modifier stack on ref/target**: `raycast` hits evaluated geometry but `face_index` maps to base-mesh face (Blender guarantee for non-displacement modifiers). For mirror/array, the index can be > base face count — guard with `if face_idx >= len(mesh.polygons): ignore`.

## HUD and Help

HUD adds:

| Param | Value source |
|---|---|
| Mode | `"Pick ref polys"` / `"Pick target polys"` / current `MODE_STAMP` label |
| Ref polys | total count across all objects, or `—` |
| Target polys | total count across all objects, or `—` |
| Match RMSE ε | `f"{op.match_rmse_threshold:.3f}"` — dynamic, `Alt+Wheel` adjustable |
| Force fit | `"on" / "off"` (only visible when in target-poly mode) |
| Hover match | per-component RMSE when hovering — only when relevant |

Help adds:

```
Mark / unmark polygon          LMB / Alt+LMB
Linked island                  Shift+LMB
Similar by normal & area       Ctrl+LMB
Enter / commit ref polys       Q
Toggle match highlight         A
Toggle force fit               W
Adjust match threshold         Alt+Wheel
```

Existing entries (D, S, R, Enter/Esc/H) stay.

## Compatibility

The object-only flow is preserved verbatim. `Q` is a no-op outside `MODE_STAMP` and `MODE_PICK_REF_POLY`. Users who never press `Q` see no behavior change. Pre-existing keybindings are not reassigned.

## Open questions left for plan

- Exact loose-tier D2 threshold `τ` — needs empirical calibration during implementation against a few test scenes. Plan should include a calibration step.
- Whether to expose `ε` adjustment in real time as a redraw trigger that re-classifies the current target groups (probably yes — cheap recompute, lots of UX value).
- Whether `Ctrl+LMB` similar-by-normal-area should also be available cross-object (currently same-object only per user). Punt to a follow-up.

## Out-of-scope follow-ups

- Save/load ref poly set as a named preset.
- Mirror/symmetry-aware matching (auto-detect mirrored components and stamp with reflected rig).
- Multi-ref blending (interpolate between two ref poly sets).
