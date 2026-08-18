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

## Variants: Along Normals / Individual Faces

Two sibling macros cover the other native extrude flavors, each running the same Rule A / Rule B attribute fix around a different extrude+move pair. Unlike `iops.mesh_extrude_ex`, these are plain macros with no dispatcher — invoke them directly (`INVOKE_DEFAULT`), there is no separate "picks options based on selection" step:

| Operator | bl_label | Macro chain |
| --- | --- | --- |
| `iops.mesh_extrude_ex_normals` | Extrude Along Normals (Keep Edge Data) | `MESH_OT_extrude_region` → `IOPS_OT_extrude_attr_fix` → `TRANSFORM_OT_shrink_fatten` → `IOPS_OT_extrude_attr_fix_post` |
| `iops.mesh_extrude_ex_indiv` | Extrude Individual Faces (Keep Edge Data) | `MESH_OT_extrude_faces_indiv` → `IOPS_OT_extrude_attr_fix` → `TRANSFORM_OT_shrink_fatten` → `IOPS_OT_extrude_attr_fix_post` |

Both replace the translate stage with `TRANSFORM_OT_shrink_fatten` (native Alt+S), which offsets each selected vertex along its own vertex normal rather than a single shared direction/axis. `iops.mesh_extrude_ex_indiv` additionally swaps the extrude step for `MESH_OT_extrude_faces_indiv` (native Alt+E "Extrude Individual Faces"), which duplicates each selected face's own verts rather than sharing them across faces at common edges — Rule A still finds the correct source edges per individually-duplicated rail, since source identification only ever looks at the rail's own linked new-side faces.

Rule B's continuation angle matters more here than for the plain translate macro: shrink/fatten moves each vertex along its averaged vertex normal, which at a mesh corner (where more than one face meets) points diagonally rather than along any single pre-existing edge's direction. A rail whose direction sits outside the default 45° `continuation_angle` from a pre-existing marked edge simply won't pick up that edge's marks under Rule B — this is expected behavior of the angle check, not a bug; widen `continuation_angle` on the redo panel if a particular shape needs it.

Both variants ship unbound (see Hotkeys below) and are also reachable from the Alt+E extrude menu.

## Alt+E Menu

All three user-facing operators are appended to the native edit-mesh extrude menu (`VIEW3D_MT_edit_mesh_extrude`, opened with Alt+E), below a separator after the native entries:
- "Extrude (Keep Edge Data)" → `iops.mesh_extrude_ex`
- "Extrude Along Normals (Keep Edge Data)" → `iops.mesh_extrude_ex_normals`
- "Extrude Individual Faces (Keep Edge Data)" → `iops.mesh_extrude_ex_indiv`

The draw callback (`draw_extrude_menu` in `mesh_extrude_attrs.py`) is appended in `register()` and removed in `unregister()`, following the same append/remove pattern as the addon's other menu hooks.

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

Rule B runs as a second attribute-fix pass, after the translate stage (so the rails have their final direction), and only when its own `use_parent_marks` toggle is on. For each rail (one selected vertex, one unselected old vertex), it walks every other edge connected to the old vertex, skipping any edge whose far vertex is also selected (that would be new/duplicated geometry, not a pre-existing edge). Of the remaining pre-existing edges, any that are marked (sharp, bevel weight, or crease) are checked directionally: the edge's direction *into* the old vertex must be within `continuation_angle` (45° by default, a per-operation property on `iops.extrude_attr_fix_post`, see Properties below) of the rail's direction *out of* the old vertex — i.e. the rail must continue roughly the same line. Matching edges are merged (OR for sharp, max for bevel weight/crease) against the rail's *current* values rather than starting from zero, so Rule B can only raise a rail's marks, never lower them — if Rule A already set a rail's crease from the extruded source edge, a lower-valued continuation edge found by Rule B cannot downgrade it. Non-continuing edges (including the boundary edges of the loop being extruded itself, which are unmarked in this scenario) are ignored.

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

`iops.mesh_extrude_ex_normals` and `iops.mesh_extrude_ex_indiv` follow the same four-step shape (extrude → Rule A fix → move → Rule B fix) but are defined directly as macros with no wrapping dispatcher — see Variants below.

## Properties
The dispatcher and macro themselves have no `bl_props` beyond what native `MESH_OT_extrude_region` / `TRANSFORM_OT_translate` already expose; behavior there is still driven by the selection mode (face/edge/vertex) detected at invocation time. The two attribute-fix sub-operators, however, each carry their own per-operation toggle, and since they run as macro steps these show up as their own subsections of the F9 "Adjust Last Operation" redo panel alongside the translate values:

| Property | Operator | Default | Effect when off |
| --- | --- | --- | --- |
| `use_selection_marks` ("From Selection") | `iops.extrude_attr_fix` (Rule A) | On | Rule A is skipped entirely; rails get nothing from the extruded source edges |
| `clear_selection_marks` ("Clear Selected") | `iops.extrude_attr_fix` (Rule A) | Off | Off: source edges (the original extruded edges left behind) keep their marks, unchanged |
| `use_parent_marks` ("Continue Parents") | `iops.extrude_attr_fix_post` (Rule B) | On | Rule B is skipped entirely; rails get nothing from pre-existing marked edges they continue |
| `continuation_angle` ("Continuation Angle") | `iops.extrude_attr_fix_post` (Rule B) | 45° | Only used when `use_parent_marks` is on; narrows or widens which continuations Rule B accepts |

`use_selection_marks` and `clear_selection_marks` toggle independently: source-edge identification (the topology walk that finds, for each rail, the original extruded edges left behind) always runs when either toggle is on, so `clear_selection_marks` works the same whether `use_selection_marks` is on or off. Both toggles default to on/off respectively, reproducing the previous (pre-toggle) behavior exactly when `clear_selection_marks` is left off. Unticking both `use_selection_marks` and `use_parent_marks` (with `clear_selection_marks` off) turns the operator into a plain native extrude-and-move: no attribute propagation happens at all. The angle slider only has an effect while "Continue Parents" is enabled.

### Clear Selected

`clear_selection_marks` ("Clear Selected") zeroes sharp/bevel weight/crease on the original extruded source edges themselves, immediately after they have been read for propagation (Rule A always reads the marks first, so clearing can never starve the rail values it computes in the same pass). This is for the common modeling case of extending a shape: the edges that used to be the boundary/rim become interior once the shape grows past them, so their sharp/bevel/crease marks are usually no longer wanted there — only the new rim should keep them (which it already does, unaffected by this toggle: see Notes below). Clearing only ever touches layers that already exist (bevel weight / crease) and never touches seam or Freestyle mark.

Two limitations:
- **Face-region extrudes only clear the region boundary.** When extruding a face region, edges strictly interior to the extruded selection are not topologically distinguishable from the rest of the mesh once the extrude has happened (they aren't rail sources, and there is no "old" copy of them left behind to identify), so only the boundary edges of the extruded region actually get cleared — interior originals that were part of the selection are left untouched.
- **Cancelling the translate (Esc) still leaves the originals cleared.** Clearing happens in Rule A, before the translate stage even starts, so an Esc/RMB cancel of the interactive drag does not undo it — same caveat as Rule A's propagation itself (see Notes below).

## Notes
- Undo: a single undo step combines all four operations, named after the macro's own label, "Extrude Region and Move (Keep Edge Data)" — it is the macro that pushes the undo step, not the dispatcher. This prevents attribute fixes or translate from forming separate undo steps, keeping the workflow smooth.
- Selection is not modified after extrude: newly created geometry remains selected, originals remain unselected. The fresh geometry is ready for immediate further operations (scale, rotate, etc.).
- Attribute layers are consulted on-the-fly via `bm.edges.layers.float.get()`. If a layer does not exist (e.g. no bevel weights on any edge in the mesh), it is simply skipped — new layers are never created during propagation.
- Cancellation via Esc or RMB during the interactive drag cancels only the translate step; the extrude and Rule A fix have already run by then and are not undone. The result is the extruded geometry left at zero offset. Rule B's fix operator still runs as the macro's final step after a cancelled translate, but since the rails are zero-length in that case (`rail_dir.length_squared < 1e-12`), it is a no-op — no marks are continued onto degenerate rails. This differs from native `mesh.extrude_region_move`, which behaves the same way for the same reason — extrude happens before the move is confirmed or cancelled. The dispatcher's `invoke()` only sees a `CANCELLED` result itself in the immediate/exec-mode case (no interactive drag); once the modal translate has started, cancellation happens after `invoke()` has already returned, so it is not something the dispatcher observes or propagates.
- Six classes are registered by this module: `IOPS_OT_extrude_attr_fix`, `IOPS_OT_extrude_attr_fix_post` (the two `{"REGISTER", "INTERNAL"}` attribute-fix operators, shared by all three macros — not user-facing for keymap/search purposes), `IOPS_OT_mesh_extrude_ex_macro`, `IOPS_OT_mesh_extrude_ex_normals`, `IOPS_OT_mesh_extrude_ex_indiv` (all three macros are `{"REGISTER", "UNDO"}`; the first sits behind the `iops.mesh_extrude_ex` dispatcher and scripts should call it directly rather than the dispatcher, the normals/indiv macros have no dispatcher at all and are invoked directly), and `IOPS_OT_mesh_extrude_ex` (`{"REGISTER"}`, the dispatcher for the translate variant only — invoke-only, no `execute()`). `INTERNAL` only hides an operator from operator search (F3) and equivalent listings; it has no effect on a macro's F9 "Adjust Last Operation" redo panel, which walks the macro's own step list regardless of any step's `INTERNAL` flag — so the two fix operators' `use_selection_marks` / `clear_selection_marks` / `use_parent_marks` / `continuation_angle` properties still appear there as their own subsections, right alongside the translate/shrink-fatten values, for all three macros.
- Hotkeys: all three user-facing operators (`iops.mesh_extrude_ex`, `iops.mesh_extrude_ex_normals`, `iops.mesh_extrude_ex_indiv`) ship as unbound `F19` placeholder rows in `prefs/hotkeys_default.py`, ready to rebind (e.g. over native `E`) in iOps hotkey preferences.

## Related
- [Shear](op_mesh_shear.md)
- [Straight Bevel](op_mesh_straight_bevel.md)
