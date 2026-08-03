# Smart Inset

Modal mesh inset driven by a 2D straight-skeleton wavefront instead of a per-vertex offset. Compared to Blender's built-in `mesh.inset`, it stays self-consistent past the point where the region would normally collapse: every boundary edge moves inward at the same speed, and when opposite edges meet, the wavefront topology changes and the region resolves into its medial skeleton (an inward taper into a seam / T-junction / point, depending on shape) instead of producing flipped or degenerate faces. It also preserves the region's interior geometry wherever the front hasn't reached it yet, supports per-face or per-region grouping, an explicit outward (outset) mode, and a depth offset along the region normal.

<div class="iops-meta" markdown="1">
<span class="key">bl_idname: iops.mesh_smart_inset</span>
<span class="mode">Mode: Edit Mesh</span>
<span>Context: VIEW_3D</span>
<span class="modal">Modal: yes</span>
<span class="hud">HUD: yes</span>
</div>

## Overview

Selected faces are grouped into regions (one region per connected component in Region mode, or one region per face in Individual mode), each region's boundary is projected onto its best-fit plane, and a weighted wavefront (simplified straight skeleton) is timed out from that 2D boundary — the same math a bevel/offset skeleton uses, but simulated instead of approximated. At a requested thickness `t`:

- Every boundary edge has moved inward by `t` along the wavefront.
- If `t` is small enough that no two fronts have met yet, the result looks like a normal inset: one wall quad per original boundary edge and an inner cap face, with an option to preserve the original interior tessellation.
- If `t` runs past the first "event" (two fronts colliding), the operator does not clamp, flip, or self-intersect the way a naive per-vertex offset would — it produces the medial-axis geometry that a real straight skeleton predicts for that shape (unless collapse is disallowed, see below).

Curved regions are handled approximately: the wavefront math is inherently 2D, so new vertices are computed on the region's best-fit plane and then pulled back onto the original surface with a BVH nearest-point query.

## Usage

- One or more faces selected in Edit Mode on a mesh object.
- Default keymap: <kbd>F19</kbd> (no modifiers) in 3D View, addon's "unbound" placeholder — assign a real key in Preferences > Keymaps, or invoke via menu/search.
- Move the mouse to drag thickness, <kbd>Ctrl</kbd>+move for depth, type digits for exact values, then <kbd>LMB</kbd>/<kbd>Enter</kbd> to confirm or <kbd>Esc</kbd>/<kbd>RMB</kbd> to cancel.

## Modal Controls

| Key | Action |
| --- | --- |
| <kbd>MouseMove</kbd> | Drag thickness (horizontal travel); a quarter of the average boundary-edge length per 100 px |
| <kbd>Shift</kbd> | Precise mode: scales further mouse delta by 0.1, re-anchored at the moment Shift is pressed/released so toggling it never jumps the value |
| <kbd>Ctrl</kbd>+<kbd>MouseMove</kbd> | Drag depth instead of thickness (same sensitivity/anchor scheme, including its own Shift-precise) |
| <kbd>0</kbd>-<kbd>9</kbd>, <kbd>Numpad 0</kbd>-<kbd>9</kbd> | Append digit to a typed thickness value; overrides mouse-driven thickness while non-empty |
| <kbd>.</kbd> / <kbd>Numpad .</kbd> | Add a decimal point (once) |
| <kbd>-</kbd> / <kbd>Numpad -</kbd> | Toggle sign of the typed value |
| <kbd>Backspace</kbd> | Delete last typed character; clearing the string hands control back to the mouse without a jump |
| <kbd>I</kbd> | Toggle Region <-> Individual grouping, rebuilding the wavefront in place |
| <kbd>C</kbd> | Toggle Allow Collapse |
| <kbd>B</kbd> | Toggle Boundary (inset from open mesh borders too) |
| <kbd>LMB</kbd> / <kbd>Enter</kbd> / <kbd>Numpad Enter</kbd> | Confirm and rebuild the mesh at the current thickness/depth |
| <kbd>Esc</kbd> / <kbd>RMB</kbd> | Cancel, restoring the thickness the operator was invoked with |
| <kbd>MMB</kbd> / <kbd>Wheel</kbd> | Pass through (viewport navigation/zoom) |
| <kbd>H</kbd> | Help / HUD param toggle |

## HUD

A cyan preview outlines the current front (or the outward contour for outset, `t < 0`); if Allow Collapse is off and the requested thickness has run past the region's no-collapse cap, the preview switches to the warning colour to flag the clamp. A second colour highlights medial "seam" segments — wall-top edges whose both ends sit on a skeleton node that has already formed at the current thickness, i.e. where the wavefront has actually collapsed. The workspace status bar and a `HUDOverlay("smart_inset")` both track thickness, depth, mode, collapse, and boundary state live.

## Properties

| Name | Type | Default | Description |
| --- | --- | --- | --- |
| `thickness` | FloatProperty | `0.05` | Inward offset of the region boundary. Negative values outset instead (see below) |
| `depth` | FloatProperty | `0.0` | Offset of the new inner geometry along the region normal |
| `mode` | EnumProperty | `REGION` | `REGION` — one inset per connected group of selected faces. `INDIVIDUAL` — one inset per selected face, independent of its neighbours (matches native inset's per-face mode) |
| `use_collapse` | BoolProperty | `True` | Allow thickness to run past the first wavefront event; see below |
| `use_boundary` | BoolProperty | `True` | Also inset from open mesh borders; when off, border edges stay frozen and only interior boundary edges move |

## Collapse vs. Clamp

This is the core difference from `mesh.inset`. Every boundary edge moves inward at unit speed (scaled per-edge by weight); a vertex's velocity is solved from its two incident edge normals, exactly like a real straight-skeleton wavefront. Two things can happen as thickness increases:

- **Allow Collapse on (default):** thickness may run past the point where opposing fronts first meet. At that "event" the wavefront's topology changes — colliding vertices merge, edges are retired, new nodes are born — and the simulation keeps going from there. Past enough events, a region degenerates into its **medial axis**: a stretched rectangle collapses to a line segment down its middle, an L-shape collapses into a Y-shaped skeleton, and so on. The final geometry always stays watertight and non-self-intersecting for straight (planar) regions, because it is the mathematically exact result of the offset process rather than a per-vertex extrapolation.
- **Allow Collapse off:** thickness is clamped to just under the first event (`first_event_t`), so the inset never changes the region's topology — it looks like a normal, uncollapsed inset no matter how far the mouse is dragged or what value is typed. The HUD thickness readout reflects this clamp, and the preview switches to the warning colour when the requested value would have gone further.

## Outset and Depth

- **Negative thickness (`t < 0`)** switches to a naive outward offset: every boundary vertex moves outward by the same per-vertex weighted-normal solve, mirroring native `mesh.inset`'s "Outset" checkbox. There is no wavefront/event handling in this direction — the original region faces are left completely untouched, and only a new outer ring plus connecting wall quads are added.
- **Depth** translates the new inner (or outer) geometry along the region's fitted normal after the 2D offset is computed. It only ever moves vertices the operator itself created (and, for inset, any preserved-interior vertices that travel with the new inner surface) — the original untouched boundary never moves.

## Interior Preservation

When insetting (not outsetting) a region whose interior faces are large enough that the front hasn't swept over them yet, those faces are kept as-is: their vertices retain their exact original positions, and only the faces the front actually cuts through are re-triangulated against it. The preserved interior becomes part of the new inner surface directly — no extra ngon cap is built where it isn't needed. If some but not all of a region's original faces get consumed, the surviving faces (and any interior holes, e.g. from an unselected face inside a selected ring) stay intact and are not overwritten or double-filled.

This clipping needs the plain unit-speed wavefront metric to line up with straight-line distance to the boundary, so it only applies when every edge weight is 1.0 (i.e. `use_boundary=True`, since a frozen border edge has weight 0). It also degrades automatically to a plain ngon fill covering the whole front — pre-clipping behaviour — if the interior can't be clipped watertight for any reason (a warning is reported when that happens); the mesh is left completely untouched until a valid plan exists, so a failed clip never leaves a partial or broken result.

## Limitations

- **Outset can self-intersect.** The naive per-vertex outward offset has no collision/collapse handling, so a reflex (concave) corner or a large enough negative thickness can push the outer contour into itself, just like native `mesh.inset`'s outset does. This is by design, not a bug — outset stays a simple offset rather than a full skeleton.
- **Approximate on strongly curved surfaces.** The wavefront runs entirely in 2D on the region's best-fit plane; new vertices are snapped back onto the original surface with a nearest-point query afterward. This tracks a moderately curved surface well, but on strongly curved regions (or ones far from planar) the offset amount and shape are an approximation, not an exact geodesic offset.
- **`use_boundary=False` disables interior clipping.** Freezing open mesh borders changes the wavefront's edge weights away from unit speed, which breaks the distance metric interior clipping depends on — regions insetted with borders frozen always get the plain ngon/hole fill instead of the finer clipped-interior result.
- **Regions that fold over their own plane are skipped.** The wavefront needs the projected boundary loops to be simple. A selection that bends far enough that some face normal points away from the region's average normal (a selection wrapping more than ~180°, e.g. most of a cylinder, or a region with mixed/flipped face normals) would project to a self-intersecting outline, so it is rejected with a `region folds relative to its plane` warning instead of producing silently wrong geometry. Moderately curved selections are still handled approximately (see above).
- **Non-manifold or open boundaries per region.** A region whose selected faces don't form a single closed manifold boundary (e.g. a non-manifold edge junction, or a selection with a dangling face) is skipped with a warning rather than aborting the whole operation; other valid regions in the same selection still process normally.

## Notes

- New faces inherit `material_index`, the smooth flag and interpolated loop data (UVs, vertex colours) from the original face they derive from — the face that owned the boundary edge for a wall, the face it was cut out of for a clipped face, and a representative region face for a cap ngon. This matches native `mesh.inset`.
- The result leaves the new inner surface selected (the caps, clipped and preserved interior faces; for outset, the new outer ring) with the walls deselected, so the operation can be chained straight into another one. In vertex select mode Blender's own flush rules still light up any face whose every vertex ended up selected.
- Cancelling (<kbd>Esc</kbd>/<kbd>RMB</kbd>) restores both `thickness` and `depth` to their invoke-time values, not to a mid-drag anchor.
- Only `IOPS_OT_smart_inset` is registered from this file. The heavy 2D wavefront/straight-skeleton math lives in `utils/smart_inset_core.py` and has no `bpy` dependency (it is unit-tested directly under `tests/test_smart_inset_core.py`).
- Regions and their timelines are built once on `invoke` and cached; nothing between invoke and confirm touches `bmesh.update_edit_mesh`, since that would invalidate the cached `BMVert` references the regions hold.
- Toggling Mode (<kbd>I</kbd>) or Boundary (<kbd>B</kbd>) mid-modal rebuilds regions/timelines in place; if the new configuration would leave no usable regions, the toggle reverts and a warning is reported instead of leaving the operator with nothing to preview.
- Draw handlers are tracked in a module-level set so a fresh `invoke` drops stale handlers left behind by addon reloads or crashed sessions.
- `bl_options = {"REGISTER", "UNDO"}`: the redo panel re-runs `execute()` with the stored properties, exactly like confirming the modal.

## Related

- [Mesh Cursor Bisect](op_mesh_cursor_bisect.md)
- [Mesh Straight Bevel](op_mesh_straight_bevel.md)
- [Mesh Quick Connect](op_mesh_quick_connect.md)
