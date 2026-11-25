# iOps Falloff Fields — Design (Project 1: field model, stack, transforms, redo)

Date: 2026-11-16
Status: approved (2026-11-16)

Supersedes [2026-09-07-modo-falloff-tools-design.md](2026-09-07-modo-falloff-tools-design.md).

## Intent

The current falloff tools (`iops.mesh_falloff_move / _rotate / _scale`) each own their
falloff: it exists only while the modal runs, it cannot be reused by another operation,
cannot be combined with a second falloff, and cannot be adjusted after confirming.

The replacement turns the falloff into a **field**: a thing that lives in the scene, is
positioned in the viewport with handles, can be stacked with other fields, and is *read* by
operations. Any operation that can express its result as "per-vertex amount × weight" can
then be falloff-driven. The reference for behaviour is a commercial falloff add-on the user
pointed at (public product page only; no code seen). Its feature list was catalogued from
the page's 16 demo recordings.

That catalogue is larger than one project. Agreed order:

1. **This document** — field data model, four spatial field types, stack with blend modes,
   viewport tool with handles and auto-fit, weight preview, multi-object, the four
   transform operations, adjust-after-confirm (F9).
2. Topology operations: Extrude (directed, along normals; per vertex / per island),
   Inset (region / individual), Bevel (edge / vertex).
3. Slides: Edge Slide, Vertex Slide, Offset Edge Slide.
4. Distance fields: Topological, Geodesic, anchor capture.
5. Spline field (curve object / edge chain / in-place control points, tube radius).
6. Extras: custom response curve widget + user presets, field groups + group presets,
   Proportional Editing combination, "move by field span" key, appearance preferences.

Projects 2–6 each get their own design. This one must not make them harder; the
"Constraints from later projects" section lists what they need from it.

## Goals

- One or more falloff fields exist independently of any running operator, are visible and
  draggable in the viewport, and persist in the .blend.
- Move, Rotate, Scale and Normal Offset use the current field stack.
- After confirming, F9 changes the amount and the falloff's influence settings, and the
  result is recomputed from the pre-operation geometry (never compounding).
- Works across all meshes in multi-object Edit Mode with one shared field.
- The weight maths stays bpy-free and unit-tested.

## Non-goals (this project)

- Everything in projects 2–6 above.
- UV editor, On Cage / evaluated-mesh editing, baking weights to vertex groups.
- Screen and Coplanar falloff types, the Element/connected toggle (see "Removed").

## Anti-goals

- Fields must not silently affect anything that was not invoked as a falloff operation.
  Blender's own G/R/S are untouched unless the Falloff tool is the active toolbar tool.
- No state that can leave a draw handler or gizmo group alive after add-on reload
  (reload hygiene matters here: stale handlers have crashed Blender in this codebase before).

## Approaches considered

**A. Scene-level field stack + redo-able operators + a toolbar tool with gizmo handles
(chosen).** Fields are property groups on the scene. Operators snapshot the stack at
invoke, compute weights with numpy, and are `REGISTER | UNDO` so Blender's own redo gives
adjust-after-confirm from original geometry. Handles are native gizmos, so they are
draggable with no modal running. Cost: a rewrite of `operators/falloff/common.py`, and the
repo's first WorkSpaceTool and GizmoGroup.

**B. Extend the current modal tools** with more types and an in-modal stack. Cheapest now.
Rejected: the falloff still dies with the modal, F9 cannot work (the tools bake several
drags per session and push undo manually), and every future operation would have to embed
the whole falloff UI again.

**C. Bake the field to a vertex attribute and let native operators read it.** Rejected for
interactive use: native transform/extrude/inset/bevel operators do not read per-vertex
weights. Kept in mind as the later "assign to vertex group" feature.

The user handed over the how; A is the builder's pick, not something the user chose between.

## What changes for the user

Today: start Falloff Move → the falloff appears → drag handles or drag to move → release
bakes → tool stays live → Enter.

After:

1. Activate the **Falloff** tool in the Edit Mode toolbar and press Fit (Shift+F), or just
   press Fit, which also activates the tool. A field is fitted to the selection and drawn
   with handles.
2. Adjust handles, add more fields, change type/curve/blend in the tool settings — no
   operator is running.
3. Press G / R / S / Alt+S. The operation starts immediately like Blender's own (no button
   held), mouse moves it, LMB/Enter confirms, RMB/Esc cancels.
4. F9 to adjust amount and influence.

This is Blender-style grab instead of the current Modo-style click-drag-and-stay-live.
Confirmed by the user (2026-11-16).

## Data model

`Scene.IOPS.falloff` (new PropertyGroup; replaces the eight `falloff_*` scalars):

- `fields`: collection of `FalloffField`
- `active_index`
- `show_weights` (bool), `basis` (existing `falloff_basis` enum, moved here)
- `use_custom_pivot` (bool), `pivot` (world-space point)

`FalloffField`:

| Prop | Meaning |
|---|---|
| `name` | "Falloff 1", … |
| `type` | `LINEAR`, `RADIAL`, `ELLIPTICAL`, `BIDIRECTIONAL` (enum left open for `SPLINE`, `TOPOLOGICAL`, `GEODESIC`) |
| `start`, `end` | world-space points. Linear: 0 % at start, 100 % at end. Bidirectional: 0 % at both, 100 % at the midpoint. Radial: `start` = centre, `end` = a point on the sphere. Elliptical: `start` = centre, `end` = tip of the primary axis |
| `radii` | Elliptical only: the two secondary radii |
| `roll` | Elliptical only: rotation of the secondary axes about the primary axis |
| `curve` | response-curve preset (existing `SHAPES` list) |
| `invert` | bool |
| `strength` | 0..1 |
| `blend` | `REPLACE`, `ADD`, `SUBTRACT`, `MULTIPLY`, `MIN`, `MAX` |
| `enabled` | participates in the stack |

Geometry is **world space** (the current code is object space) because one field serves
several objects.

Direction convention changes with the reference: Linear is 0 % at Start, 100 % at End.
Radial stays 100 % at the centre, 0 % at the radius. Elliptical likewise.

Fields persist because they are scene data. There is no separate "pin" switch; a Clear
operator removes them. (Builder's call: simpler than an explicit pin, same outcome.)

## Weight evaluation (`utils/falloff_core.py`, bpy-free)

Per field: raw `t` in [0, 1] from geometry → `curve(t)` → invert → that is `w_i`.

Stack, evaluated top to bottom over enabled fields, `s = strength_i · w_i`:

- first field, or `REPLACE`: `w = s`
- `ADD`: `w + s` · `SUBTRACT`: `w − s` · `MULTIPLY`: `w · (1 − strength_i + s)`
- `MIN`: `min(w, s)` · `MAX`: `max(w, s)`
- clamp to [0, 1] after each step

No enabled fields → weight 1 everywhere (the operation behaves like the plain one).

New functions: `weight_bidirectional`, `weight_elliptical`, `combine_stack`,
`autofit_pca` (principal axis of the points → Start/End at the extents), axis-aligned fits.
Existing `weight_linear` flips direction; `weight_screen`, `weight_coplanar_faces`,
`coplanar_grow`, `connected_mask` and their tests are deleted.

A plain-data description of a stack (list of dicts) is the interface between bpy property
groups and the core, so the core never sees bpy and operators can snapshot a stack.

## Domain

Selected vertices of every mesh in Edit Mode (`objects_in_mode_unique_data`). With nothing
selected anywhere: all visible vertices (kept from the current tools). Hidden vertices are
never touched. Positions are taken to world space for weights and transforms and written
back through each object's inverse matrix.

## The Falloff tool

A WorkSpaceTool in the Edit Mesh toolbar, with:

- **Gizmo handles** for the active field: Start, End, and a middle "body" handle that moves
  the whole field; Elliptical adds its two secondary-radius handles. Dragging uses the view
  plane through the handle; Ctrl snaps to mesh vertices; X/Y/Z constrain during the drag.
  Other fields in the stack are drawn dimmed; clicking one makes it active.
- **Pivot handle** (user decision: keep the movable pivot as a tool gizmo). Shows the pivot
  the operations will use. Dragging it (Ctrl snaps to vertices, X/Y/Z constrain) sets
  `use_custom_pivot`; a Reset button in tool settings, and Fit, clear it back to the
  automatic pivot. The old axis studs / rings are not carried over; X/Y/Z keys in the
  operator replace them.
- **Drawn field**: Start→End line with the 0 %→100 % gradient and percent labels; Radial /
  Elliptical wire outline (three loops). Uses the existing `ui/draw` roles and the theme's
  occluded opacity, except that hidden parts of the field drawing are drawn at no less than
  50 % opacity (a deviation from the theme's occluded opacity, decided during the visual fix
  round so a field under the mesh stays visible and grabbable); the weight dots follow the
  theme.
- **Weight preview**: a dot per domain vertex, coloured by final stack weight. Toggle in
  tool settings. Cached; recomputed when a field or the selection changes.
- **Tool settings** (header + popover): the stack list with add / remove / reorder /
  enable, and the active field's type, curve, invert, strength, blend. Fit and Clear
  buttons. New fields are named "Falloff 1", "Falloff 2", … (unique within the stack).
- **Tool keymap** (active only while the tool is the current toolbar tool; all rebindable):
  G → Falloff Move, R → Rotate, S → Scale, Alt+S → Normal Offset, Shift+F → Fit.

**Fit** (`iops.mesh_falloff_fit`): activates the tool if needed; with no fields, adds one of
the last-used type and fits it; otherwise refits the active field. First fit for a given
selection uses PCA; calling it again with the selection unchanged cycles PCA → X → Y → Z.

**When fields move (builder's calls):**

- Activating the tool never creates or changes a field. An empty stack stays empty until
  Fit or the first falloff operation (which runs Fit). No scene writes from gizmo setup.
- A field stays where it was put when the selection changes; only the preview cache is
  invalidated. Fit is how a field is brought to a new selection.
- Field edits (handle drags, add / remove / reorder, Fit, curve and invert changes) are
  **not** on the undo stack in this project: Edit Mode undo restores mesh data, not scene
  properties. Ctrl+Z after a falloff operation restores the mesh and leaves the fields as
  they are. Revisit if it proves annoying.

The four operators are also ordinary bindable iOps operators. Called while another tool is
active they still use the scene's stack, and draw the fields themselves for the duration.
Started interactively (invoke) with an empty stack they first run Fit; a scripted `execute()`
on an empty stack applies weight 1 and adds no field.

## Operators

`iops.mesh_falloff_move`, `_rotate`, `_scale` keep their idnames (existing key bindings
survive); `iops.mesh_falloff_normal_offset` is new. All `REGISTER | UNDO`.

Modal behaviour, shared:

- Starts transforming immediately from the invoke mouse position.
- X / Y / Z axis (Shift+axis = plane, for Move and Scale), in the `basis` orientation;
  Rotate defaults to the view axis.
- Shift = precise, Ctrl = snap increments, typed numbers = exact amount.
- `[` / `]` cycle the active field's curve; Shift+I toggles its invert. Both update live.
- LMB / Enter confirm; RMB / Esc restore and cancel.
- HUD/status line: operation, axis, amount, active field name and curve.
- Navigation events pass through as today.

Maths: Move / Rotate / Scale as today (`apply_move`, `apply_rotate`, `apply_scale`), in
world space. Pivot = the custom pivot when set, otherwise the bounding-box centre of the
domain's selected vertices, or per `basis`.
With several objects in Edit Mode, `LOCAL` means the active object's axes (builder's call).
Normal Offset: `P = P0 + W · d · N`, with `N` the vertex normals at invoke in world space.

**Redo (F9).** Operator properties: the amount (vector / angle / factor / distance), axis
constraint, basis, the pivot point actually used, and a **snapshot of the field stack** taken at confirm (a collection
property mirroring `FalloffField`). `execute()` rebuilds the domain from the current
selection, computes weights from the snapshot, and applies the amount. Blender's redo
undoes to the pre-operation mesh before calling `execute()`, which is what gives "replay
from original geometry". The redo panel shows the amount, then the participating fields
with blend / strength / curve / invert for each. Field *geometry* is not editable in F9.

Changes made in the redo panel are copied back to the scene's fields (matched by position
in the stack) so the viewport keeps showing what was applied. **To verify early in the
build:** that scene properties written from a redo `execute()` in Edit Mode are not rolled
back by the redo's own undo step. If they are, drop the copy-back; F9 still works.

## Removed

- Screen and Coplanar types, Element (connected-only) toggle, their props and tests.
  Not in the reference; Coplanar grows outside the selection, which conflicts with
  "influence is computed inside the selection". Topological (project 4) replaces
  connected-only. Removal confirmed by the user (2026-11-16).
- In-modal falloff editing (L/R/S/C type keys, handle dragging inside the operator,
  bake-per-drag, A auto-size, V preview). The tool does these now.
- `Scene.IOPS.falloff_type / _shape / _invert / _connected / _preview /
  _screen_radius_px / _coplanar_angle / _basis`.

## Constraints from later projects

- Weight evaluation takes "points + stack description" and returns weights, with no
  assumption that points are existing vertices — topology operations need weights for
  per-island centroids and for vertices created by the operation.
- Field types that need mesh context (Topological, Geodesic) will need the domain's
  connectivity; keep the evaluation entry point able to accept optional per-object mesh
  data without changing callers.
- The stack snapshot + redo pattern must be reusable by non-transform operators (a mixin
  or helper, not code inside the transform operators).
- The modal curve/invert keys, HUD line and field drawing are shared by all later
  operators.

## Files (expected; builder may adjust)

- `utils/falloff_core.py`, `tests/test_falloff_core.py` — extended / pruned as above.
- `operators/falloff/` — `fields.py` (property groups ↔ plain stack, fit, add/remove/clear
  operators), `tool.py` (WorkSpaceTool, gizmo group, drawing, preview cache),
  `base.py` (shared modal + redo mixin), `ops.py` (four operators). `common.py` goes away.
- `presets/widgets/falloff_tools.json` — the built-in widget binds all eight removed
  `scene.IOPS.falloff_*` props; rewrite it against the new property group. User override
  copies in the user's widget folder will need the same edit (mention in the docs page).
- `prefs/addon_properties.py`, `__init__.py` (register/unregister incl. the tool),
  `docs/operators/op_mesh_falloff_tools.md`, `tests/test_renamed_idnames.py` if idnames
  are checked there.

## Verification

- pytest: every field type at its 0 % / 50 % / 100 % points and outside; each blend mode on
  two known weight arrays; strength; no-fields → ones; PCA fit on an elongated cloud and
  axis fits; transforms with W = 0 / 1 / 0.5.
- Headless Blender (existing `B:\test` harness; verify the test blend first): each operator
  via `execute()` with a known stack on a subdivided plane; two objects in multi-edit share
  one Linear field and get stepped results; calling `execute()` twice from the same
  starting mesh gives the same result (no compounding); add-on disable/enable leaves no
  tool, gizmo group or draw handler behind.
- The reference loop below, for everything visible: every scenario at ≥ 80 %.
- Live checklist for the user (cannot be automated): handle drag / snap / constrain, Fit
  cycling, preview refresh on selection change, G/R/S/Alt+S from the tool, `[` `]` and
  Shift+I mid-operation, F9 edits, Ctrl+Z after confirm, reload via the dev blinker.

## Reference loop (target: ~80 % match)

The user's bar: the iOps result should match the reference recordings about 80 % — same
behaviour and the same things visible, without chasing pixel parity or the reference's
exact styling.

The recordings are saved locally, outside the repo (they are someone else's product
material and must never be committed): `B:\test\falloff_reference\` — `gif\NN_name.gif`
(originals), `sheets\NN_name.jpg` (9-frame contact sheets, frame index stamped on each
tile), plus zoomed crops of the F9 panel and preferences. `sheet.py` and `crop.py` there
regenerate sheets or cut any frame.

Every visible piece of this project goes through this loop before it counts as done:

1. **Stage** the reference scenario in a dedicated Blender instance on a throwaway test
   blend (never the user's working session — see the verify-test-blend rule): same kind of
   mesh, selection, field type and placement, similar view angle.
2. **Capture** viewport screenshots of the iOps result at the matching moments (field at
   rest, mid-operation, after confirm, F9 open).
3. **Score** side by side against the reference frames, by a reviewer that did not write
   the code. Each "must match" item of the scenario (table below) gets 1 (matches),
   0.5 (present but visibly off) or 0 (missing / wrong). Scenario score = sum ÷ item count.
   Judge behaviour and readability, not pixels. iOps theme colours, HUD style and wording
   are allowed to differ and are not scored down.
4. **Pass** when the scenario scores ≥ 80 % **and** no item is 0. Otherwise list what cost
   points, fix, and go back to step 2. Stop and report to the user if a scenario is still
   below 80 % after three rounds instead of looping on.
5. **Record** the final score per scenario and keep the final iOps capture next to the
   reference frame (in `B:\test\falloff_reference\iops\`) as evidence. The project is done
   when every scenario passes; the hand-over lists the scores and what was left unmatched.

Scenarios for this project (sheet → scored items, separated by `;`):

| Reference | Scenario | Must match |
|---|---|---|
| `06_linear` | Strip of a plane selected, Linear field along it, Move on Z | Even ramp, 0 at Start and full height at End; line gizmo with gradient; % labels at the ends; middle handle; weight dots on the selection |
| `01_transforms` | Same ramp, then F9: curve Linear → Ease In; then Scale on X | Ramp turns concave; it is recomputed from the original geometry (no compounding); F9 lists the participating field; F9 exposes Blend, Strength and Curve (`c_f9_move.png`); Scale narrows the ramp progressively |
| `11_topo` (frames 67–111, Rotate only) | Torus half selected, Linear field, Rotate on Z | Progressive unroll along the field; angle shown while rotating. The topological anchoring in that clip is project 4 and is not scored |
| `07_radial` | Field display only | Sphere volume outline; radius line from the centre; handles at centre and radius |
| `08_elliptical` | Field display + Move on Z | Ellipsoid volume; independently adjustable radii; vault-shaped result |
| `09_bidir` | Plane, Bidirectional field, Move on Z | Arch with 0 at both ends; peak at the middle; single line gizmo |
| `13_stack` | Two crossing fields combined; Linear + Radial with Subtract | Groin-vault shape from the two crossing fields; dip where the Radial is subtracted; both fields drawn, active one distinguishable |
| `14_multiobj` | Four cubes in multi-object edit, top faces, one Linear field, Move on Z | All four objects move in one operation; stepped heights follow one shared ramp; one field drawn across all |
| `15_placement` (frames 0–137) | Fit on a zig-zag selection, repeat Fit, drag Start / End / Body | First Fit follows the selection's long direction; repeat cycles X / Y / Z; Start and End drag independently; Body moves the whole field. Spline frames (171+) are project 5 |
| `16_visual` | Weight preview on a dense grid | Dots readable at 0 % and at 100 %; gradient between them; occluded parts dimmed |

The same folder and the same loop serve projects 2–6 (`02`–`05`, `10`, `12` and the rest
of `11`, `15`).

## Left to the builder

Gizmo implementation details (custom Gizmo classes vs. built-in move gizmos), preview
caching strategy, HUD layout, exact theme colours for the gradient, default hotkey
registration through the iOps hotkey system vs. tool keymap only, file split inside
`operators/falloff/`.
