# Smart Edge Slide — Design

**Date:** 2026-11-04
**Status:** Approved for planning

## Why

The user adds support and detail loops next to existing edge loops with a
third-party add-on (Kushiro's *Slide Edge*). Despite the name it does not
slide: it splits the selected chain, offsets a copy to one side by *Slide
size*, and bridges a strip of quads in between. The original loop stays put.

It breaks whenever the chosen side is not a clean strip of quads. Each new
vertex is pushed along one arbitrary edge of the vertex and clamped to that
edge's length, so the width follows the topology instead of the request.
Measured on the reference mesh (see *Reference case*) with a requested width
of 0.1:

- toward the walls: 0.094–0.1, nearly even (clean parallel rails);
- toward the slanted panel: 0.136 / 0.1 / 0.067 / 0.1 … 0.023 / 0.027 / 0.1 /
  0.066. Vertices 105 and 104 get pushed along the diagonals 105→45 and
  104→41, which run almost parallel to the loop, so 0.1 along them is about
  0.02 across. The new loop zig-zags.

The user wants the Smart Inset quality bar for this job: **exact, perfectly
even width, whatever the topology on that side**.

## What it is

`iops.mesh_smart_edge_slide` — "Smart Edge Slide". A modal Edit Mesh operator
that **cuts a new edge loop into the existing faces, parallel to each
selected edge chain, at an exact width, on one chosen side**. The selected
loop stays where it is. Mesh shape does not change: every new vertex lies on
the original surface, and every new edge lies inside an original face.

## Goals

1. **Exact width.** Width is the perpendicular distance from the selected
   chain, measured on the side surface (see *Width and the side surface*).
2. **Cut, don't move.** New geometry only splits existing faces.
3. **One new vertex per source vertex** by default, plus only the cut points
   that cannot be avoided (see *Topology*).
4. **An exact-width mode** (toggle) that adds vertices wherever one vertex
   per source vertex cannot hold the width exactly.
5. **Steps are projected through, not followed.** Where a face next to the
   chain sticks out of the side surface (face 89 in the reference case), the
   new loop is projected along the side surface onto whatever lies there, so
   it wraps pockets and bumps and stays straight when viewed down the
   surface.
6. **Ctrl snapping.** Hold Ctrl and hover a mesh vertex: the width snaps so
   the new loop passes exactly through that vertex.
7. Works on open and closed chains, several chains at once.
8. Live preview drawn through the iOps theme, Smart Inset–style modal UX,
   redo panel.

## Non-goals

- **Moving the selected loop itself** (a classic edge slide). Discussed and
  dropped by the user: "the point is cutting our edge, not shifting".
- Depth / extrusion of the new strip.
- A surface-distance ("geodesic") measure across steps. Over a step the
  width is measured on the projected side surface, not along the step face.
- Any new bevel or chamfer geometry. Per chain we add one new loop and its
  connecting edges, nothing else.
- Walking the cut across the mesh beyond the band of faces next to the
  chain. Two things go further and nothing else: step projection and the
  ends sliding along the border. A general walk would need a different core
  data model, and the user never asked for one; the user's examples are all
  about stopping exactly at a vertex.

## Anti-goals (fails even if it technically works)

- The width visibly drifts or zig-zags (the bug we are replacing).
- The silhouette or surface changes in any way.
- The default mode sprinkles extra vertices along the loop. The user's own
  test of the first preview was "there are extra points; the source loop
  doesn't have that many".
- Preview drawn with raw GPU squares or hard-coded colours. Previews use
  `ui/draw/primitives.py` with theme roles only.
- A draw handler or HUD left behind after cancel, error or reload.

## Reference case

The user's reference mesh (an interior kitbash wall section), Edit Mode. The
selected chain is open, 12 verts / 11 edges:

`50 → 41 → 45 → 25 → 26 → 44 → 43 → 24 → 105 → 104 → 100 → 42`

It runs along the junction between a slanted planar panel and a ceiling or
wall prism extruded along −X.

- **Panel side** (faces 94, 95, 96, 97, 149, all coplanar, normal ≈
  (−0.92, 0, −0.39)) is a set of n-gons with diagonals 45→105 and 41→104
  that run chain-to-chain. Most chain vertices have *no* edge into the panel.
  The chain is a planar curve in this plane: a rising edge, a fillet, a flat
  top and a falling edge. The end edges into the panel are 50→99 and 42→184.
  The panel border opposite the chain is 184→99.
  - Perpendicular distance of 99 from the end edge is 0.227 and of 184 is
    0.066. These are the user's snap examples.
  - At width 0.2 the exact cut crosses three existing edges, the diagonals
    among them.
- **Wall side** is quad strips extruded along −X to x = −6 (faces 8, 33, 40,
  38, 35, 37, 27, 82, 21, 31). The exception is between 105 and 104: there
  the face next to the chain is **face 89**, a 0.15-tall vertical lip at
  the mouth of a pocket. The pocket has top face 86 (z = 5.0) and side faces
  87 and 88. The ceiling faces 82 and 21 on either side of the pocket lie in
  z = 4.85.
  - Expected result there: the new loop runs at x = x_chain − width on 82,
    goes up 88, across 86, down 87, and continues on 21. Prototyped and
    approved by the user.
- With one vertex per source vertex on the wall side, the largest width
  error is about 3.1–3.3 % of the width, on edge 100→42 next to corner 100.
  That is 1.2 cm at a width of 40 cm. Everywhere else it is exact.

## Behaviour

### Input

- Selected edges in Edit Mode, grouped into connected **chains**. A chain is
  a simple path or a simple closed loop. Branching selections (a vertex with
  three or more selected edges) are skipped with a warning; the other chains
  still run.
- Each chain edge must have one face on the chosen side. Border edges with
  no face on that side, and non-manifold edges, skip that chain with a
  warning.

### Side and sign

- One signed **width** value drives every chain. The sign picks the side.
- **Open chains.** The positive side is the one whose band lies toward
  screen-right at invoke time, comparing the average screen X of each
  side's band as Kushiro's tool does. Dragging right sends the new loop
  screen-right.
- **Closed chains.** Screen-right is meaningless here, so the positive side
  comes from the mesh: the side to the left of the chain when it is walked
  counter-clockwise on screen at invoke time. All closed chains in one
  selection behave the same way: a set of hole rims all go the same way,
  either all inward or all outward.
- Store the side assignment per chain at invoke, and reuse it in `execute()`
  (redo), so a changed view cannot flip a redo.
- A typed negative value or a drag past zero flips every chain.
- **F** flips the one chain nearest the cursor. This is the escape hatch for
  multi-chain selections where the automatic side is wrong for some chains.
  *(Side rules are our call; see Calls made.)*

### Width and the side surface

- The **side surface** of a chain is the band of faces next to the chain on
  the chosen side.
- The width is measured in that surface. Adjacent side faces are unfolded
  across their shared edge, so on a folded strip (the fillet) the width is
  the in-surface perpendicular distance, not a 3D chord. On a planar side
  this is a plain 2D polygon offset in the face plane.
- **Steps.** A side face is a step when it turns away while the chain runs
  straight across it. Detect this with each face's *away direction* (the
  in-face direction perpendicular to its chain edge, pointing away from the
  chain), not with face normals.
  - Face 89's away direction is +Z, while its neighbours 82 and 21 both
    point −X. The chain runs straight through 24 → 105 → 104 → 100, so 89 is
    a step.
  - Both flanking neighbours must agree with each other and differ from the
    face. A chain that turns at a box corner, with two walls folding 90°
    along the corner rail, is an ordinary fold and gets unfolded, not
    projected. So is a profile with no fillet. Those are common support-loop
    cases.
  - Across a step, the reference surface continues from the neighbours (the
    z = 4.85 plane in the reference case).
  - The cut there is the intersection of the mesh with a "sheet": the offset
    line swept along the reference normal, bounded to that stretch of the
    chain and to a sensible depth.
  - Faces beyond the step get cut. The step face itself is cut only if the
    sheet crosses it.
  - The threshold that defines "far" is the builder's call (the prototype
    used |cos| < 0.5).

### Topology

- **Default mode (one vertex per source vertex).**
  - **Has a rail.** If the source vertex has an edge into the side surface
    that runs roughly across the loop, the new vertex sits on that edge.
    This is the normal case on quad strips.
  - **No rail.** If the source vertex has no edge into the side surface (an
    n-gon border vertex: most panel vertices), the new vertex sits at the
    exact offset corner (miter) inside the face.
  - **Width at rail vertices.** Each new vertex lies on the exact-width
    offset. The edges between vertices are straight, so where the rail does
    not bisect the loop's angle at that vertex, the width mid-edge is off by
    a little (the 3 % figure above).
  - **Fans.** When a vertex has several edges into the side, the rail is the
    one closest to the bisector. The others are crossed (see below).
  - **Shallow edges.** An edge that runs too close to parallel with the loop
    is not a rail. For example, 105→45 is 13° off the loop; sliding along it
    is exactly the Kushiro bug.
- **Connecting edges (user's choice: variant B).** Every source vertex is
  joined to its new vertex by an edge, so the strip between the two loops
  becomes quads, as with Kushiro's tool.
  - Where the source vertex has a rail, the rail piece is that edge already.
  - Where it has no rail (the panel n-gons), a new edge is added inside the
    face.
  - **Skipping.** If a new connecting edge would cross an existing edge, it
    is not added: the face stays an n-gon there, and no point is added for
    it. In the reference case that happens on the fillet: at width 0.2, five
    connecting edges would cross the diagonal 45→105. The user picked this
    after comparing both variants in the viewport.
- **Unavoidable cut points.** These appear in every mode:
  - where the new loop crosses an existing edge that is not a rail (the
    panel diagonals, the edges of the faces a step projects onto);
  - the pocket corners, where the projected cut turns.

  The user accepted these.
- **Exact-width mode** (toggle, off by default).
  - Each new vertex goes at the exact miter. Where that miter is not on a
    fold edge, the loop also gets a vertex where it crosses the fold.
  - Add points only where the default placement would actually miss the
    width beyond a tight tolerance. Do not add them at every fold.
  - User: "perfect width and one point per vertex without extra points; if
    that's impossible, the extra points are an additional mode." It is
    impossible in general. One point on a rail can match the width in both
    neighbouring faces only when the rail bisects the loop's angle there.

### Ends of open chains

- The end of the new loop is the offset of the end edge, extended until it
  meets the border of the side surface that starts at the chain's end
  vertex.
- It lands first on the end edge (42→184). Once the width passes that
  edge's far vertex, the end keeps sliding along the next border edges
  (184→99).
- Ctrl near such a border vertex snaps the end exactly into it. Agreed with
  the user.

### Width past the available room

- **Hard limits, always.** The width cannot go past:
  - the point where a new vertex reaches the far end of its rail;
  - the point where the cut reaches the far border of the band.

  The band is the faces next to the chain, plus what a step projects onto.
  Open-chain ends sliding along the border are the one exception (see
  *Ends*).
- **Shrinking segments.** At a convex corner, a segment of the new loop can
  shrink to zero length. By default (C off) the width **clamps** there, and
  the preview turns the warning colour, as in Smart Inset's clamp mode. With
  C ("Allow Collapse") on, such segments are dropped, like Smart Inset's
  collapse, and the width runs on to the hard limits.
- **Clamp is per chain**, like Smart Inset's per-region `effective_t`. A
  chain with a short rail stops while the others keep going. The Width prop
  and the HUD show the requested width, and the HUD flags "clamped" when
  any chain is held. A snapped width is clamped by each chain's own limit
  in the same way.

*(Limits, clamp default and per-chain clamping are our call; see Calls
made.)*

### Ctrl snapping

- While Ctrl is held, the vertex nearest the cursor sets the width. Use
  `utils/picking.py` (`closest_snap_point` and its screen and world
  tolerance).
  - The candidates are every visible mesh vertex, not only the selection.
  - The width becomes that vertex's side-surface distance from the chain,
    measured through projection (a vertex straight above a step projects
    onto the chain, so its width is about 0).
  - The side becomes the side the vertex lies on.
- The snapped vertex is drawn with the theme's CLOSEST_POINT role. Releasing
  Ctrl keeps the snapped value as the new drag anchor, so nothing jumps.
- With several chains, the vertex is measured against the nearest chain, and
  every chain uses that signed width.

### Modal UX (mirrors Smart Inset)

| Input | Action |
|---|---|
| Mouse X | Width (sensitivity from average chain-edge length; Shift = precise) |
| Digits / `.` / `-` / Backspace | Type an exact width |
| Ctrl + hover | Snap width to the vertex under the cursor |
| E | Exact-width mode on/off |
| C | Allow collapse on/off (off = clamp) |
| F | Flip the side of the chain nearest the cursor |
| H | Help legend / HUD toggle |
| MMB / Wheel / NDOF | Navigate |
| LMB / Enter | Confirm |
| RMB / Esc | Cancel (every prop back to its invoke value) |

- **HUD:** title "Smart Edge Slide". Params: Width, Exact (E), Collapse (C).
  Help overlay with the table above. Use the same `HUDOverlay` / `HelpOverlay`
  wiring as `IOPS_OT_smart_inset`.
- **Preview:**
  - new loop: `PREVIEW_LINE`;
  - new vertices: `PREVIEW_POINT`;
  - snap target: `CLOSEST_POINT`;
  - clamped: `ERROR_LINE`.

  Draw everything through `ui/draw/primitives` inside `draw_scope`. Register
  the handler with `safe_handler_add` and purge it with the `_purge_handles`
  pattern.
- **Redo panel props:** `width`, `use_exact`, `use_collapse`. `execute()`
  re-runs from props, as Smart Inset's does.
- **After confirm:** the new loops are selected (edges), so another slide
  can follow straight away. *(Our call.)*

### Errors

- No usable chain → `CANCELLED` and a warning.
- Per-chain problems (branching, missing side face, a step with no usable
  neighbour) skip that chain with a warning; the others still run.
- Any exception in `modal` removes the draw handler and HUD (same
  try/except shape as Smart Inset).

## UV Stripe (added 2026-11-04, applies to Smart Edge Slide and Smart Inset)

**Why.** The new strip is usually textured with a trim sheet. The user
wants it unwrapped as one straight, even strip as part of the same
operation, without a separate unwrap step.

**What.**
- **Toggle.** "UV Stripe" in both operators: key **U** in the modal, and a
  redo-panel property. Off by default.
- **Which faces are unwrapped:**
  - **Smart Edge Slide:** the faces between the selected loop and the new
    loop, including the pieces where the cut wraps a step (pocket).
  - **Smart Inset:** the wall faces between the original boundary and the
    new inner contour, including the triangles where the inset collapsed.
    For a negative thickness (outset) this is the new outer ring.
- **Result: one straight, even strip per loop.**
  - **U runs along the loop.** Curves and wrapped steps are straightened.
  - **V runs across**, from the original edge (V = 0) to the new one (V =
    the strip height).
  - **U and V share one scale**, so the aspect is kept: no stretching
    (user's decision).
- **Edges of the rectangle.**
  - Every vertex on the original edge lies on the bottom, and every vertex
    on the new edge lies on the top.
  - The columns at the source vertices are straight verticals.
  - Faces inside a step (the lip and the pocket pieces) are squeezed into
    the rectangle, so the strip stays a perfect rectangle. *(Our call.)*
- **Closed loops** (inset rings, closed edge loops) are cut at the sharpest
  corner of the original loop. On a tie, the first vertex in loop order wins.
  *(Our call.)*
- **Modes:**
  - **Fit 0–1** (default):
    - the strip spans U 0–1;
    - V is scaled by the same factor, with its bottom at V = 0 (user's
      decision);
    - several strips (several loops, or an inset with holes) are stacked
      upward in V, with a 0.01 gap between them. *(Our call.)*
  - **In Place:**
    - the strip goes where the affected faces' UVs were before the operation
      (centred on their UV bounding box);
    - its scale matches the texel density of the neighbouring faces;
    - only when those faces had UVs; otherwise Fit 0–1 is used (user's
      decision).
- **UV channel.** The active UV channel. If the mesh has none, one is
  created. *(Our call.)*

## Architecture

Follow the Smart Inset split.

- **`utils/smart_edge_slide_core.py`** — pure Python, no `bpy`.
  - Input: the chain in local 2D strip coordinates (unfolded) plus rail
    directions per vertex, and border paths at the ends.
  - Output: new-vertex positions for a given width in both modes, cut
    crossings, the clamp limit and collapse events.
  - Unit-testable with plain pytest.
  - Reuse `smart_inset_core` maths (`vertex_velocity`, weighted offset)
    where it fits. Do not import from or copy code out of Kushiro's add-on:
    it is third-party GPL code, and we use it as behaviour reference only.
- **`operators/mesh_smart_edge_slide.py`** — the bridge and the modal.
  - Chain extraction and side-surface collection.
  - Unfolding and step detection.
  - The projected cut through steps (sheet ∩ mesh; the prototype used
    `bmesh.ops.bisect_plane` on a copy plus span clipping, and the real
    implementation should cut only the faces involved).
  - bmesh face splitting.
  - Ctrl snapping, HUD, preview.
- **Wiring**, the same places Smart Inset is registered:
  - `__init__.py` (import and class list);
  - `prefs/hotkeys_default.py` (unbound F-key slot, like Smart Inset's F19);
  - `ui/iops_pie_edit.py` and `ui/iops_pie_menu.py` (next to Smart Inset);
  - docs: `docs/operators/op_mesh_smart_edge_slide.md`, `docs/operators.md`,
    `docs/index.md`, `mkdocs.yml`, `docs/ui/ui_pies.md`.

## Testing

1. **Pytest on the core** (`tests/test_smart_edge_slide_core.py`, no bpy):
   - straight chain with rails perpendicular → one vertex per source vertex,
     exact width;
   - bent chain on folded strips → default mode within a stated error bound,
     exact mode exact with extra points only where the bound is exceeded;
   - n-gon side with no rails → exact miters;
   - open chain end sliding past the end edge onto the next border edge;
   - closed loop;
   - clamp limit equals the first event.
2. **Integration via blender-mcp** on a copy of the reference mesh (follow
   the file-protection rules: the user's file is usually open and dirty).
   Assertions, both sides, a few widths:
   - every new vertex within EPS of the original surface (shape unchanged);
   - measured width per new vertex;
   - wall side at default: 12 + 2 new vertices (two pocket corners);
   - panel side: one connecting edge per interior source vertex, except
     those that would cross an existing edge (they are skipped, and no
     vertex is added for them);
   - no degenerate faces;
   - manifoldness unchanged.

## Calls made (not discussed with the user)

- **Side.** Open chains take screen-right as positive. Closed chains take
  the left of the chain walked counter-clockwise on screen. The sign flips
  every chain, and F flips the chain nearest the cursor. The assignment is
  stored for redo.
- **Scope.** The cut stays in the band of faces next to the chain. Only step
  projection and the end-slide go further; there is no general walk across
  the mesh.
- **Clamp.** Clamp is the default and C allows collapse. Collapse only drops
  shrinking segments. Clamping is per chain.
- **Steps.** A step is detected by the away directions of the faces, with
  both flanking neighbours agreeing, not by face normals.
- E toggles exact-width mode.
- The new loops stay selected after confirm.
- Ctrl snapping covers mesh vertices only; no edge midpoints or face centres
  for now.
- **UV Stripe:**
  - closed loops are cut at the sharpest corner;
  - step faces are squeezed into the rectangle;
  - Fit 0–1 stacks strips with a 0.01 gap;
  - a missing UV channel is created;
  - U is the toggle key.

## Left to the builder

- The step-detection threshold and the sheet depth limit.
- The rail-acceptance angle and how a fan picks its rail.
- The error tolerance at which exact mode adds a point.
- How the width error is balanced between the two faces at a rail vertex.
- The bmesh cutting strategy and the core data structures.
