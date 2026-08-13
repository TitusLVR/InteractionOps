# Extrude Wrapper with Edge-Attribute Continuation — Design

**Date:** 2026-08-13
**Status:** Approved

## Problem

Native Blender extrude (`E` / `MESH_OT_extrude_region_move`) copies edge
attributes onto the duplicated edge, but the **rail edges** — the new edges
created between each original vertex and its extruded copy — get nothing.
Sharp marks, bevel weights, and creases stop dead at the extrusion boundary,
forcing manual re-marking after every extrude. Loop-cut workarounds only work
on straight geometry.

## Goal

A drop-in replacement for `E` that behaves identically to native extrude
(mouse-follow modal translate, single undo step) and additionally propagates
edge data onto rail edges so marked borders continue through the extrusion.

Reference file: `V:\temp_blends\extrude_wrapper.blend` — object `start`
(plane, right edge marked sharp / bevel weight 1 / crease 1) extruded +X must
produce the `target` semantics: original edge keeps marks, duplicated edge
keeps marks, and both rail edges receive the marks.

## Behavior

- New operator **`iops.mesh_extrude_ex`** — bindable over `E` in Edit Mode.
- Propagated attributes: `use_edge_sharp` (via `edge.smooth`),
  `bevel_weight_edge`, `crease_edge`. UV seams and freestyle marks are
  explicitly NOT propagated.
- Rule A (extruded sources): each rail edge inherits the attribute values of
  the marked **extruded** edges incident to its old (non-moved) vertex. When
  two marked extruded edges meet at that vertex, take the max per attribute
  (sharp is OR).
- Rule B (continuation sources): each rail edge also inherits from marked
  **non-extruded** pre-existing edges at its old vertex that the rail
  geometrically continues — the edge's direction into the old vertex is
  within 45° of the rail's direction out of it. This covers the
  `open_box_start` case: extruding an uncreased rim whose corner verts
  terminate creased edges must crease the new rails
  (reference objects `open_box_start_target` vs `_finish` in the test
  blend). Rule B needs final geometry, so it runs as a fourth macro step
  AFTER the translate (Blender macros continue past modal sub-operators —
  `MESH_OT_loopcut_slide` chains two). On a cancelled translate the rails
  are zero-length and Rule B is a no-op — accepted limitation.
- Vertices whose incident extruded edges carry no marks produce clean rails.
- Vertex-only extrusion: fixup is a no-op.
- The duplicated edge and the original edge need no handling — native extrude
  already preserves their data (verified empirically in Blender 5.1).

## Architecture

New file `operators/mesh_extrude_attrs.py`, two classes:

1. **`IOPS_OT_extrude_attr_fix`** — instant (non-modal) operator. Runs the
   topology-based Rule A fixup on the edit-mesh bmesh. Position of the new
   geometry is irrelevant, so it can run before any translation.
2. **`IOPS_OT_extrude_attr_fix_post`** — instant operator for Rule B. Runs
   after the translate, when rail directions exist; matches marked
   non-extruded edges at each rail's old vertex by colinearity (45°
   threshold, module constant) and copies their attributes onto the rail.
3. **`IOPS_OT_mesh_extrude_ex(bpy.types.Macro)`** — macro defined as:
   `MESH_OT_extrude_region` → `IOPS_OT_extrude_attr_fix` →
   `TRANSFORM_OT_translate` → `IOPS_OT_extrude_attr_fix_post`. This mirrors
   how native `MESH_OT_extrude_region_move` is built: one undo step,
   identical modal feel. Translate sub-operator properties are set at
   define/invoke time to match native extrude defaults (normal-constrained
   for face extrusion). Both fix operators handle multi-object edit mode
   via `context.objects_in_mode_unique_data`.

Registration follows the existing iops operator-list pattern. Hotkey exposure
goes through the iops hotkey system; registration/unregistration must follow
the established single-register rule and only touch addon keymaps.

## Fixup Algorithm (runs post-extrude, pre-translate)

After `MESH_OT_extrude_region`: new geometry is selected, original vertices
are deselected, and original element indices are unchanged (new elements are
appended).

1. Get edit-mesh bmesh; fetch/ensure `bevel_weight_edge` and `crease_edge`
   float layers (create only if a source edge actually carries a nonzero
   value — avoid polluting meshes that never used the attribute).
2. **Rails:** edges with exactly one selected vertex. The unselected one is
   the old vertex.
3. **Sources:** for each rail, look at the old vertex's other incident edges
   that share a face with the rail and whose both vertices are unselected —
   these are the original extruded edges left behind. Read their
   sharp/bw/crease.
4. Apply per-attribute max (OR for sharp) to the rail edge.
5. `bmesh.update_edit_mesh(me)`.

## Edge Cases

- **Face extrude, one marked boundary edge:** only the two rails at that
  edge's vertices get marks; the rest stay clean.
- **Corner vertex with two marked extruded edges:** rail gets max of both.
- **Interior marked edges of an extruded face region:** no rails exist there;
  duplicates keep data natively. No action.
- **Cancelled translate (Esc/RMB):** geometry remains at zero offset with
  fixed attributes — identical to native extrude-cancel behavior.
- **Meshes without bevel/crease layers:** layers created only when needed.

## Testing

Live testing in the open Blender instance against
`extrude_wrapper.blend`. Each iteration goes into its own collection
(`v1`, `v2`, `v3`, …) for easy tracking.

Cases:
1. `start` edge extrude +X → must match `target` semantics (rails marked
   sharp/bw/crease, duplicated edge marked, original keeps marks).
2. Face extrude with one marked boundary edge.
3. Multi-edge extrude including a corner where two marked edges meet.
4. Vertex extrude (no-op, no errors).
5. Mesh with no bevel-weight/crease layers → no spurious layers unless
   sources carry values.
6. Modal feel: invoke via hotkey, confirm mouse-follow + cancel behavior.
