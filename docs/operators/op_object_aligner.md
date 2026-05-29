# Object Aligner

Stamps a selected "rig" (one or more source objects) onto other objects in the scene, preserving its transform relative to a picked reference. A modal raycast workflow with two paths: whole-object alignment (Q/W) and polygon-pattern matching (E) that auto-finds copies of a marked face pattern across the scene, including mirrored variants.

<div class="iops-meta" markdown="1">
<span class="key">bl_idname: iops.object_aligner</span>
<span class="mode">Mode: Object</span>
<span>Context: VIEW_3D</span>
<span class="modal">Modal: yes</span>
<span class="hud">HUD: yes</span>
</div>

## Overview

The aligner solves "I have this assembly placed correctly on object A — now place a copy on every B, C, D that matches". It supports two correspondence strategies and picks per target:

- Topology-equal mesh targets get a Kabsch fit over vertex positions (geometry fit).
- Anything else falls back to a matrix transfer `T = M_target @ M_ref^-1`.

The polygon-pattern path (E) marks a face set on the reference mesh, then searches every visible mesh (the user-picked target set plus the reference object itself) for face subsets whose adjacency and per-face area/normal pattern match. Each candidate is validated by a face-anchor Kabsch fit with automatic mirror detection. Final placement uses a face-correspondence procrustes fit, so symmetrical halves are placed with the correct handedness.

Nothing is realized in the scene until confirm — every committed pick is drawn as a GPU ghost.

## Usage

- Selection: at least one object selected (the rig to transfer). The selected objects, plus inner objects of any EMPTY-instancer in the selection, are excluded from raycast picks.
- Default keymap: no default keymap binding — invoke via search (F3) or a custom binding.
- Workflow (object mode, Q/W):
  1. Invoke. State starts in PICK_REF.
  2. LMB on the reference object (Q re-enters this mode).
  3. State auto-advances to PICK_TGT_OBJS; LMB toggles each target object in/out of the set (W re-enters this mode).
  4. Enter / Space / RMB to stamp.
- Workflow (poly-pattern, E):
  1. Pick reference (Q) and at least one target object (W). The reference object itself is implicitly included in the search.
  2. Press E to enter PICK_REF_POLY; LMB faces on the reference mesh to build the pattern.
  3. Press E again to commit the pattern; the operator scans all picked targets (+ ref) and shows auto-found components as hints.
  4. State is now PICK_TGT_POLY: LMB a face on any hint component toggles that whole component in/out of the stamp set. C clears all, I inverts.
  5. Enter / Space / RMB to stamp. Faces selected outside any auto-hint are decomposed by edge-connectivity and fit via PCA-frame.

## Modal Controls

| Key | Action |
| --- | --- |
| <kbd>LMB</kbd> | Pick / toggle per mode: set ref (PICK_REF), toggle target object (PICK_TGT_OBJS), toggle ref face (PICK_REF_POLY), toggle hint component (PICK_TGT_POLY) |
| <kbd>MouseMove</kbd> | Update hover highlight (object or face depending on mode) |
| <kbd>Q</kbd> | Switch to PICK_REF |
| <kbd>W</kbd> | Switch to PICK_TGT_OBJS |
| <kbd>E</kbd> | Enter PICK_REF_POLY; pressed again from PICK_REF_POLY commits the ref pattern, runs the match search, and advances to PICK_TGT_POLY |
| <kbd>R</kbd> | Full reset — clear ref, targets, polys, hints, pending; return to PICK_REF |
| <kbd>C</kbd> | In PICK_TGT_POLY: clear all kept match components (skip everything) |
| <kbd>I</kbd> | In PICK_TGT_POLY: invert kept-component selection per object |
| <kbd>D</kbd> | Cycle clone mode: Duplicate -> Instance |
| <kbd>S</kbd> | Cycle scale mode: Uniform -> Keep -> Stretch |
| <kbd>X</kbd> | Toggle source rig viewport visibility (restored on finish/cancel) |
| <kbd>H</kbd> | Toggle help / HUD overlay (handled by overlay framework) |
| <kbd>Enter</kbd> / <kbd>Numpad Enter</kbd> / <kbd>Space</kbd> / <kbd>RMB</kbd> | Confirm — realize pending stamps and finish |
| <kbd>Esc</kbd> | Cancel — remove stamped objects, drop created empty sub-collections |

HUD/Help overlays also intercept LMB drags and their own toggle clicks before mode dispatch.

## HUD

On-screen overlay titled "Object Aligner" with the following parameters (some conditional on state):

- **Mode** — current pick mode (Pick reference / Pick targets / Pick ref polys / Pick target polys).
- **Reference** — name of the picked ref object (when set).
- **Ref polys** — count of marked reference faces (when any).
- **Target polys** — count of currently kept target faces (when any).
- **Targets** — number of explicitly picked target objects (when any).
- **Clone** — DUPLICATE or INSTANCE.
- **Scale** — Keep / Uniform / Stretch.
- **Fit** — last fit kind: `geometry`, `matrix`, `poly-strict`, `poly-mirror`, or `poly-force`.
- **Stamped** — running count of pending placements.
- **Rig hidden** — shown when X has hidden the source rig.

Viewport ghost colour roles (from the addon theme):

- `GHOST_ACTIVE` — reference object highlight (and marked ref polys).
- `GHOST_CLOSEST` — picked target objects, plus the hover-face preview in poly modes.
- `GHOST_TARGET_SEL` — currently kept target faces.
- `GHOST_LOCKED` — auto-found hint components that have been skipped (amber, click to re-enable).
- `GHOST_PREVIEW` — rig ghost at every committed/pending placement.
- `GHOST_EDGE` — ghost wireframe overlay.

## Properties

The operator has no `bl_props` — all state lives on the modal instance and is driven by the keymap above.

## Notes

- The operator reads the **evaluated** mesh of each object (modifiers applied) for raycast hit resolution, pattern matching, vertex sampling, and ghost rendering — Mirror/Array/SubD geometry participates in picks and previews.
- EMPTY-instancers in the source selection are supported: the dupli'd inner mesh is excluded from picks, and the ghost is drawn from the instance collection.
- A raycast under the mouse may pierce up to 100 layers; source objects and their dupli geometry are transparent to the ray.
- Cancel removes every object stamped during this invocation and deletes any sub-collection (`<source_collection>_<target_name>`) the operator created if it ended up empty.
- Pattern search runs in two tiers (area_tol 0.20 / fit_rmse 0.05, then 0.35 / 0.15). If the tight tier finds matches, the loose tier is skipped. Topology + adjacency are matched first, then Kabsch fit on face-anchor points (centroid + offset along face normal) gates geometry similarity. Mirror detection is automatic per match.
- When the reference is not a mesh, polygon-pattern mode is rejected; only the object-pick (Q/W) path is usable.
- Stamps are realized in `_realize_pending` only on confirm; child hierarchies are duplicated recursively from each top-level root in the source selection.

## Related

- [Object Rotate](op_object_rotate.md)
- [Object Radial Array](op_object_radial_array.md)
- Object Distribute
