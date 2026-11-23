# iOps Falloff Fields — Design (Projects 2 + 3: Extrude, Inset, Bevel, Edge Slide)

Date: 2026-11-17
Status: draft — waiting for the user's approval

Follows [2026-11-16-falloff-fields-design.md](2026-11-16-falloff-fields-design.md)
(project 1: fields, stack, tool, Move / Rotate / Scale / Normal Offset). That document
listed topology operations as project 2 and slides as project 3. The user asked
(2026-11-17) for Bevel, Inset and Edge Slide "as in the reference recordings", then added
Extrude. They are designed together here because they share one mechanism.

## Intent

Project 1 made the falloff a scene-level field that operations *read*. Only four
transforms read it. The reference product also has operations that create geometry and
size it by the field: a bevel whose width fades to nothing along the field, an inset whose
thickness varies, an extrusion whose height follows the field, an edge loop that slides
further where the weight is higher. Those are missing.

## Goals

- Five new operators that use the scene's field stack exactly like the transforms do:

  | idname | Label | Reference |
  |---|---|---|
  | `iops.mesh_field_extrude` | iOps Field Extrude | `02_extrude` |
  | `iops.mesh_field_inset` | iOps Field Inset | `04_inset` |
  | `iops.mesh_field_bevel` | iOps Field Bevel | `03_bevel`, `c_f9_bevel.png` |
  | `iops.mesh_field_edge_slide` | iOps Field Edge Slide | `05_slide` (frames 0–32, 79–127) |
  | `iops.mesh_field_offset_edge_slide` | iOps Field Offset Edge Slide | `05_slide` (frames 48–64) |

- Same interaction as project 1: starts from the mouse position with no button held,
  Shift precise, Ctrl snap, typed amount, `[` / `]` curve, Shift+I invert, LMB / Enter
  confirm, RMB / Esc cancel, status line.
- F9 after confirm: the operation's own parameters plus the participating fields
  (Enabled, Blend, Strength, Curve, Invert), recomputed from the pre-operation mesh.
- Multi-object Edit Mode with the one shared stack.
- The Falloff pie and the Falloff Tools widget list the new operators.

## Non-goals

- Vertex Slide (was in project 3's list; it is not in the reference recording and nobody
  asked for it). Stays on the roadmap.
- Projects 4–6: Topological / Geodesic fields, Spline field, custom curve widget, presets,
  groups, Proportional Editing combination.
- A custom response-curve editor in F9 (visible in `c_f9_bevel.png`; that is project 6).
  F9 keeps the curve preset dropdown.
- Replacing iOps Inset, Edge Slide, Straight Bevel or Blender's own tools. The new
  operators are separate; nothing existing changes behaviour.

## Naming

The user's decision (2026-11-17): these are **Field Extrude**, **Field Inset**, **Field
Bevel**, **Field Edge Slide** and **Field Offset Edge Slide**; idnames `iops.mesh_field_*`.
Not "Falloff …" and not "Weighted …" (the reference's wording). Move / Rotate / Scale /
Normal Offset keep their "Falloff …" names and idnames.

## One mechanism: full operation, then pull back by weight

The idea, in the user's words (2026-11-17): take the field's value at each affected
element and feed it into the operator's amount — `amount_i = amount · w_i`.

**Literal route, preferred wherever the bmesh operator can be given one amount per
element:** Individual inset (one call per face, or per group of equal weight, with its own
thickness / depth), per-island Extrude (one distance per island), both slides (the factor
is already per vertex). For Bevel, check in step 0 whether per-edge / per-vertex bevel
weights (`bevel_weight_edge` / `bevel_weight_vert` with the operator's weight option, as
the Bevel modifier's Weight limit does) are reachable from `bmesh.ops.bevel`; if they are,
write `w` there and let Blender size each edge — that is the truest result and keeps
clamp / miter correct.

**Pull route, where Blender takes a single number for a whole connected region** (Region
inset, per-vertex Extrude, Bevel if weights are not reachable): the operation runs once at
the full amount and each vertex's displacement is scaled by its weight. Same rule, applied
to the vertices instead of the operator's argument. It works in two steps:

1. **Build** — run the topology operation at the full amount (bmesh operator, on every
   object of the domain).
2. **Pull** — every vertex the operation created or moved has a **source position** `S`:
   where it sat (or the vertex it was split from sat) before the operation. Its final
   position is

   `P = S + w(S) · (P_full − S)`

   with `w(S)` the stack weight evaluated at the source position.

At weight 1 the result is the plain operation; at weight 0 the new geometry collapses onto
the original vertex, which is what the reference shows (the bevel and the inset taper to a
point at the 0 % end). This is the same "amount × weight" rule as the transforms, so
`falloff_core.stack_weights` is used unchanged — it already takes arbitrary points
(project 1's "Constraints from later projects").

**How `S` is known for new vertices.** Before the build, each domain vertex's coordinate is
written to a temporary float-vector vertex layer. Vertices created by bevel / inset /
extrude are made from an example vertex and should inherit that layer, so afterwards every
vertex carries its source position; the layer is removed at the end.

*To verify first, before anything else is built:* that `bmesh.ops.bevel`,
`inset_region`, `inset_individual`, `extrude_face_region` and `offset_edgeloops` copy a
custom vertex layer to the vertices they create (Blender 5.2 LTS and the 5.3 build on this
machine). Fallback per operator if one does not: map new vertices to sources from the
operator's returned geometry (inset, extrude: via the connecting side faces) or by running
the build once at a negligible amount to read the mapping by index (bevel).

**Weight per vertex or per island.** Extrude and Inset have `per` = `VERTEX` | `ISLAND`.
`ISLAND` evaluates the weight once, at the centroid of each connected group of selected
faces (each face, for Individual inset), and uses it for all of that group's vertices:
flat-topped steps instead of sloped tops (`02_extrude` frames 66–88 vs. 33–55).

**Degenerate geometry at weight 0.** Where `w = 0` the new vertices coincide with their
source. `merge_zero` (bool, default on) welds those at confirm / in `execute` so no
zero-area faces are left; off keeps the topology uniform.

**Known deviation.** Scaling the offset is not identical to running the operation with a
smaller width where the result is non-linear in the width (bevel profile with clamping,
miters). Within the 80 % bar; noted so it is not mistaken for a bug.

**Step 0 result (2026-11-17, Blender 5.3, bmesh probe on a 4×4 grid).**

- `inset_region`, `inset_individual`, `extrude_face_region`: new vertices **copy** the
  source layer from the vertex they were made from. Source-layer route works.
- `bevel` (edges and vertices) and `offset_edgeloops`: the layer is **interpolated** — every
  new vertex's layer equals its own new position, so it carries no source. These two need
  the fallback mapping (index / returned-geometry walk).
- `bmesh.ops.bevel` has no per-element weight option (no `use_weights` / weight-limit
  argument), so the literal route is not available for Bevel: it uses the pull route.

## Changes to the shared base (`operators/falloff/base.py`)

`FalloffOpMixin` assumes the vertex set is fixed at invoke. Topology operators need one
more stage. Add a second mixin, `FalloffTopoMixin(FalloffOpMixin)`, rather than branching
inside the transform path:

- `_build(context, domain)` — runs the bmesh operation at the current parameters; returns
  the working set: vertices, `S`, `P_full` (world space), island ids when needed.
- `_apply` becomes the pull formula above; subclasses only supply `_build` and their amount
  mapping.
- **Snapshot / restore.** The pre-operation mesh of every domain object is kept for the
  modal's lifetime. Each live update restores it and rebuilds. Changing a parameter that
  alters topology (segments, mode, per-vertex / per-island) goes through the same path, so
  there is no special case. Reuse the snapshot helper iOps Inset / Straight Bevel already
  have if it fits multi-object; otherwise one helper in `operators/falloff/`.
- Cancel restores the snapshot. `execute` (F9 / scripts) needs no snapshot: Blender's redo
  has already put the mesh back.
- Performance guard: if a rebuild takes longer than a frame budget on a heavy mesh, the
  build is cached per topology-affecting parameter set and only the pull is redone on
  mouse move (amount changes do not need a new bmesh operation for extrude, inset depth /
  thickness and slides if `P_full` is stored as a direction × amount; bevel always
  rebuilds). Builder decides how far to take this; correctness first.

Everything else — stack snapshot, copy-back, curve / invert keys, status line, draw hooks,
`cancel()` hygiene — is inherited as is.

## Operators

### Field Extrude

Selection: faces (regions). Edges / verts only: report and cancel in this project.

| Property | Meaning |
|---|---|
| `distance` | Height at weight 1 |
| `direction` | `NORMAL` (each vertex along its vertex normal — the tube in `02_extrude`), or a Basis axis via X / Y / Z in the modal. Default `NORMAL` |
| `per` | `VERTEX` / `ISLAND` |
| `merge_zero` | see above |

Mouse: distance, as Normal Offset does. Modal keys: X / Y / Z set the axis (again to go
back to normals), `V` toggles Vertex / Island.

The reference's status line reads "Auto"; taken here to mean "normals unless an axis is
set". If the recording shows something else on closer look, the reference loop will catch
it.

Cancel removes the extrusion entirely (snapshot restore). The reference, like Blender's
own extrude, keeps the new topology on Esc and only cancels the movement; that behaviour
leaves hidden doubled geometry and is deliberately not copied.

### Field Inset

Selection: faces.

| Property | Meaning |
|---|---|
| `thickness` | at weight 1 |
| `depth` | at weight 1 (also scaled by the weight) |
| `mode` | `REGION` / `INDIVIDUAL` |
| `use_even_offset` | as Blender's |
| `per` | `VERTEX` / `ISLAND` |
| `merge_zero` | |

Mouse: thickness; Ctrl-drag (as Blender's inset) or typed value for depth. Modal keys:
`I` toggles Region / Individual, `V` Vertex / Island.

### Field Bevel

Selection: edges, or vertices with `affect = VERTICES` (`03_bevel` frames 113–129).

| Property | Meaning |
|---|---|
| `width` | at weight 1 |
| `offset_type` | Offset / Width / Depth / Percent / Absolute |
| `segments` | wheel or typed; rebuilds |
| `profile_type`, `profile` | Superellipse (Custom profile out of scope) |
| `affect` | `EDGES` / `VERTICES` |
| `clamp_overlap`, `loop_slide` | |
| `miter_outer`, `miter_inner` | |
| `material`, `mark_seam`, `mark_sharp`, `face_strength_mode` | pass-through, F9 only |
| `merge_zero` | |

Mouse: width. Wheel: segments (so the wheel is not passed to navigation in this operator;
MMB still navigates). `V` toggles Edges / Vertices.

The source position of a bevel vertex is the original vertex of the bevelled corner /
edge end. With `segments > 1` every profile vertex of one corner shares that source, so the
whole profile scales toward the corner.

### Field Edge Slide

Selection: edge loops (any number, open or closed).

| Property | Meaning |
|---|---|
| `factor` | −1 … 1 at weight 1; sign picks the side |
| `use_even` | even thickness, as Blender's |
| `use_clamp` | stop at the neighbouring edge |

Each loop vertex slides along its rail edge on the chosen side by `factor · w`. Here the
source is simply the vertex's own position and no build step runs, so this operator fits
`FalloffOpMixin` directly with rails computed at invoke. Rail finding: reuse
`utils/edge_slide_core.py` where it gives per-vertex rails; otherwise the plain
"the two edges of the vertex that are not on the loop, one per side" rule. No new
geometry, no `merge_zero`.

Linear field across a cylinder's ring → slanted loop; Bidirectional → peaked loop
(`05_slide` frames 16–32 and 111–127).

### Field Offset Edge Slide

Build: `offset_edgeloops` adds a loop on each side of the selected one. The two new loops
then slide away from the original by `factor · w`, source = the original loop's vertex
(`05_slide` frames 48–64: a wedge opening toward the 100 % end). Properties as Edge Slide
plus `cap_endpoint`.

## F9

`draw_amount` of each operator lists the properties above, then the inherited field list.
Bevel's panel is the long one; order it as in `c_f9_bevel.png` (amount, width type,
segments, profile, clamp, loop slide, miters, affect, material / marks, then
"participating fields").

## Tool keymap, pie, widget

Tool keymap (only while the Falloff tool is active; all rebindable):

| Key | Operator |
|---|---|
| E | Field Extrude |
| I | Field Inset |
| Ctrl+B | Field Bevel |
| Ctrl+Shift+B | Field Bevel, `affect = VERTICES` |

Edge Slide and Offset Edge Slide get no tool key (Blender's is the G-G double tap, which a
tool keymap cannot express cleanly); they are in the pie, the widget and bindable.

Pie (`ui/iops_pie_falloff.py`): the eight slots are taken. The **Add Field** slot stays;
the operations move so that the left / right / top slots hold the transforms as now and a
new **Topology** sub-menu (Extrude, Inset, Bevel, Edge Slide, Offset Edge Slide) replaces
the standalone Normal Offset slot, with Normal Offset moved into the same menu. Final
layout is the builder's call; the user sees it in the live check.

Widget `presets/widgets/falloff_tools.json`: one more row of buttons.

## Files (expected; builder may adjust)

- `operators/falloff/base.py` — `FalloffTopoMixin`, snapshot helper.
- `operators/falloff/topo.py` — Extrude, Inset, Bevel, Offset Edge Slide.
- `operators/falloff/slide.py` — Edge Slide.
- `utils/falloff_core.py` — `pull(S, P_full, W)`, island weights (weights at centroids
  spread to members); `tests/test_falloff_core.py`.
- `operators/falloff/tool.py` (keymap), `ui/iops_pie_falloff.py`,
  `presets/widgets/falloff_tools.json`, `__init__.py`, `tests/smoke_register.py`,
  `tests/blender/test_falloff_topo.py`.
- `docs/operators/op_mesh_falloff_tools.md`, `docs/ui/ui_pies.md`.

## Build order

Cheapest and least risky first; each step is usable on its own.

0. Verify the source-layer inheritance (see above). Decides the mapping strategy.
1. Edge Slide (no topology).
2. `FalloffTopoMixin` + Offset Edge Slide (smallest build step).
3. Extrude.
4. Inset.
5. Bevel (clamp / miter / segments make it the one most likely to need rounds).
6. Tool keymap, pie, widget, docs.

## Verification

- pytest: `pull` at W = 0 / 0.5 / 1; island weights; slide factor × weight with clamp.
- Headless Blender (`tests/blender/test_falloff_topo.py`, isolated user resources): each
  operator via `execute()` with a known Linear stack —
  vertex / face counts equal the plain operation's (with `merge_zero` off); vertices at
  weight 1 match the plain bmesh operation's positions; vertices at weight 0 sit on their
  source; `execute()` twice from the same mesh gives the same result; two objects in
  multi-edit; add-on disable / enable leaves nothing behind.
- Reference loop (same rules and folder as project 1, ≥ 80 % per scenario, no item at 0):

| Reference | Scenario | Must match |
|---|---|---|
| `02_extrude` 0–22 | Top faces of a curved tube, Linear field along it, Extrude | Height grows along the field; follows the surface normals |
| `02_extrude` 33–55 | Checker selection on a plane, Linear field, per Vertex | Sloped tops; height ramps along the field; unselected faces untouched |
| `02_extrude` 66–88 | Same, per Island | Flat tops, stepped heights |
| `04_inset` 0–48 | Two strips of faces, Linear field, Region | Border width tapers to nothing at the 0 % end; changing the curve changes the taper |
| `04_inset` 61–97 | Same selection, Individual | Every face inset on its own; size of the inset varies along the field |
| `03_bevel` 0–32 | Cylinder cap edge loop, Linear field across it | Bevel width 0 at one side, full at the other; segments visible |
| `03_bevel` 48–97 | F9 on that bevel: change curve | Result recomputed, not compounded; panel lists bevel parameters and the participating field |
| `03_bevel` 113–129 | Plane, vertices mode | Vertex bevels growing along the field |
| `05_slide` 0–32 | Cylinder ring, Linear field, Edge Slide | Loop ends up slanted: unmoved at 0 %, full slide at 100 % |
| `05_slide` 48–64 | Offset Edge Slide | Two loops opening as a wedge from the 0 % end |
| `05_slide` 79–127 | Bidirectional field, Edge Slide | Peak in the middle, ends unmoved |

- Live checklist for the user: each operator from the tool key and from the pie, wheel
  segments in Bevel, `V` / `I` toggles, typed amounts, Esc mid-operation leaves the mesh
  untouched, F9 edits, Ctrl+Z after confirm.

## Decisions (2026-11-17)

1. Esc in Field Extrude behaves as in Blender: the new topology stays, only the movement
   is cancelled. This replaces the "Cancel removes the extrusion" paragraph above. The
   same holds for every operator here that builds geometry (Offset Edge Slide already
   does this).
2. Vertex Slide: not in the reference (only Edge Slide and Offset Edge Slide appear in
   `05_slide`), left out.

## Progress

- Step 0 done (see "Step 0 result").
- Step 1 done: Field Edge Slide (`operators/falloff/slide.py`, `apply_edge_slide` /
  `pick_rail` in `falloff_core`). Modal keys E (Even), C (Clamp).
- Step 2 done without `FalloffTopoMixin`: Offset Edge Slide builds the loops, selects
  them and hands them to the slide as its domain; `offset_edgeloops` puts each new vertex
  on its source, so no source mapping was needed. Redo rebuilds from the pre-operation
  mesh. The mixin is still needed for Extrude / Inset / Bevel.
- Pie: a "More" menu in the top-right slot holds Normal Offset and the slides.
- Not yet run: the reference loop for `05_slide` (needs a live Blender capture).
