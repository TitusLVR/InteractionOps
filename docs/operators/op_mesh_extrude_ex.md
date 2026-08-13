# Extrude (Keep Edge Data)

Native extrude that propagates sharp, bevel weight, and crease from the original extruded edges onto the new side edges created by the extrusion, and additionally continues those marks onto rails that pick up where a pre-existing marked edge left off. Face selections translate along the region normal, just like native E; all other selections use free translate. The operator runs as a native macro combining extrude, attribute fix, translate, and a second attribute fix into a single undo step for seamless modal interaction.

<div class="iops-meta" markdown="1">
<span class="key">bl_idname: iops.mesh_extrude_ex</span>
<span class="mode">Mode: Edit Mesh</span>
<span>Context: VIEW_3D</span>
<span class="modal">Modal: yes</span>
</div>

## Overview
The operator solves the "data loss" case during extrusion: when extruding edges or faces with sharp/bevel weight/crease attributes set, the native Blender extrude leaves those attributes on the original geometry and does not propagate them to the new side edges, losing the sharp edge feature definition. This operator automatically copies sharp, bevel weight, and crease from the source edges onto the newly created rail edges at each vertex, preserving the edge hardness and bevel setup across the extrusion.

There are two propagation rules, run at different points in the macro:

- **Rule A** (immediately after extrude, before translate): a rail's sources are the edges of its linked new-side quad faces that are wholly unselected and touch the rail's old vertex — i.e. the original extruded edges left behind.
- **Rule B** (after translate): additionally continues marks from edges that were *not part of the extruded selection at all*, but that a rail geometrically continues in a straight line from its old vertex. This covers extruding an unmarked boundary (e.g. an open rim) whose corner verts terminate marked edges elsewhere on the mesh — those marks carry onto the new rails as if the marked edge kept going.

Face mode behaves identically to native E: extrude outward along the region normal, then translate along the normal axis (Z) in the transform stage. All other selection modes use free translate. Both propagation rules operate purely on topology/geometry: per-vertex attribute resolution uses OR for sharp (any source edge is sharp → rail is sharp) and max for bevel weight and crease values.

## Usage
- Edit Mode on a mesh object.
- Select one or more faces, edges, or vertices. Face selection takes priority over edges/verts when multiple types are selected.
- No default keymap binding. Bind manually to `iops.mesh_extrude_ex` in iOps hotkey preferences (or invoke via search: "Extrude (Keep Edge Data)").
- The extrude is modal: drag the mouse to set the offset, press Enter to confirm, or Esc/RMB to cancel the translate. Cancelling does **not** restore the original geometry — the extrude and attribute fix have already happened; the new geometry is left in place at zero offset, with the propagated attributes intact.
- Face mode defaults to normal-constrained Z-axis translation; press `X`, `Y`, or `Z` to switch the constraint axis, or MMB to pick an axis interactively, same as native transform.

## Attribute Propagation

Attributes propagate from the source edges (original edges left behind after extrude) onto the new rail edges (the side edges of the new quad faces). The mapping is per-vertex: for each new rail edge, its two vertices are checked — one is always new (selected), the other is always original (unselected). The operator scans the source edges of that original vertex and looks for the highest bevel weight or crease, and the logical OR of sharp flags.

| Attribute | Propagation | Layer Creation |
| --- | --- | --- |
| Sharp (edge.smooth) | OR across source edges at each vertex | Never created |
| Bevel Weight (edge.bevel_weight_edge) | Max across source edges at each vertex | Never created; only flows through existing layers |
| Crease (edge.crease_edge) | Max across source edges at each vertex | Never created; only flows through existing layers |
| Seam (edge.seam) | Never propagated | — |
| Freestyle Mark (edge.freestyle_edge.mark) | Never propagated | — |

### Rule B: continuation propagation

Rule A alone misses a common case: extruding an *unmarked* boundary edge loop (for example the open rim of a box missing one face) whose corner vertices are also endpoints of marked edges elsewhere on the mesh. Those marked edges aren't sources under Rule A (they aren't edges of the new side quads), so the new rails would come out unmarked even though, geometrically, they are a straight continuation of the marked edge.

Rule B runs as a second attribute-fix pass, after the translate stage (so the rails have their final direction). For each rail (one selected vertex, one unselected old vertex), it walks every other edge connected to the old vertex, skipping any edge whose far vertex is also selected (that would be new/duplicated geometry, not a pre-existing edge). Of the remaining pre-existing edges, any that are marked (sharp, bevel weight, or crease) are checked directionally: the edge's direction *into* the old vertex must be within `CONTINUATION_ANGLE` (45°, a module constant in `mesh_extrude_attrs.py`) of the rail's direction *out of* the old vertex — i.e. the rail must continue roughly the same line. Matching edges are merged (OR for sharp, max for bevel weight/crease) against the rail's *current* values rather than starting from zero, so Rule B can only raise a rail's marks, never lower them — if Rule A already set a rail's crease from the extruded source edge, a lower-valued continuation edge found by Rule B cannot downgrade it. Non-continuing edges (including the boundary edges of the loop being extruded itself, which are unmarked in this scenario) are ignored.

Because Rule B depends on the rail's post-translate direction, it is skipped as a no-op when the translate is cancelled (see Notes below) — a zero-length rail has no defined direction, so nothing propagates.

## Implementation Details

The operator is a composite of four internal operators, chained as steps of a macro rather than called individually:
- `MESH_OT_extrude_region` — the native Blender extrude
- `iops.extrude_attr_fix` — instant operator applying Rule A; copies attributes from source to rail edges; runs immediately after extrude and before the translate stage
- `TRANSFORM_OT_translate` — the native transform tool for interactive move
- `iops.extrude_attr_fix_post` — instant operator applying Rule B; continues marks from non-extruded edges onto the rails; runs after the translate, since it needs the rails' final (post-translate) direction

These are combined as sub-operators of the internal macro `iops.mesh_extrude_ex_macro` (`macro.define(...)` for each step, in the order above), which ensures all four steps happen in a single undo block and presents native modal feel: extrude, fix attributes, move, fix attributes again. The dispatcher (`iops.mesh_extrude_ex`) does not call any of these four directly — its `invoke()` picks translate options based on selection mode and then invokes the macro, which runs the chained steps itself.

`fix_extruded_attrs` (Rule A) and `fix_extruded_attrs_post` (Rule B) are separate module-level functions in `mesh_extrude_attrs.py`, each called from their own operator (`IOPS_OT_extrude_attr_fix` / `IOPS_OT_extrude_attr_fix_post`). Both operators share a `_fix_edit_objects()` helper for the multi-object edit-mode loop described below.

Scripts should call the macro, `bpy.ops.iops.mesh_extrude_ex_macro(...)`, not the dispatcher: the dispatcher only implements `invoke()` (no `execute()`), so a plain exec-mode call to `bpy.ops.iops.mesh_extrude_ex()` raises.

Face mode passes `orient_type="NORMAL"` and `constraint_axis=(False, False, True)` to the translate operator, locking movement to the region normal (Z axis in local space). Edge and vertex extrusions use the default free translate.

## Properties
No `bl_props`. Behavior is driven by the selection mode (face/edge/vertex) detected at invocation time, and passed through the macro's translate sub-operator properties.

## Notes
- Undo: a single undo step combines all four operations, named after the macro's own label, "Extrude Region and Move (Keep Edge Data)" — it is the macro that pushes the undo step, not the dispatcher. This prevents attribute fixes or translate from forming separate undo steps, keeping the workflow smooth.
- Selection is not modified after extrude: newly created geometry remains selected, originals remain unselected. The fresh geometry is ready for immediate further operations (scale, rotate, etc.).
- Attribute layers are consulted on-the-fly via `bm.edges.layers.float.get()`. If a layer does not exist (e.g. no bevel weights on any edge in the mesh), it is simply skipped — new layers are never created during propagation.
- Cancellation via Esc or RMB during the interactive drag cancels only the translate step; the extrude and Rule A fix have already run by then and are not undone. The result is the extruded geometry left at zero offset. Rule B's fix operator still runs as the macro's final step after a cancelled translate, but since the rails are zero-length in that case (`rail_dir.length_squared < 1e-12`), it is a no-op — no marks are continued onto degenerate rails. This differs from native `mesh.extrude_region_move`, which behaves the same way for the same reason — extrude happens before the move is confirmed or cancelled. The dispatcher's `invoke()` only sees a `CANCELLED` result itself in the immediate/exec-mode case (no interactive drag); once the modal translate has started, cancellation happens after `invoke()` has already returned, so it is not something the dispatcher observes or propagates.
- Four classes are registered by this module: `IOPS_OT_extrude_attr_fix`, `IOPS_OT_extrude_attr_fix_post`, `IOPS_OT_mesh_extrude_ex_macro`, and `IOPS_OT_mesh_extrude_ex` (the dispatcher). Only the dispatcher is user-facing for keymap/search purposes — the two attribute-fix operators and the macro operator are internal and should not be bound directly, though scripts call the macro (see Implementation Details). No panels, menus, or PropertyGroups.

## Related
- [Shear](op_mesh_shear.md)
- [Straight Bevel](op_mesh_straight_bevel.md)
