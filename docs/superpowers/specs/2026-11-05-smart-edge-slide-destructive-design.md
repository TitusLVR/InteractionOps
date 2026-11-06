# Smart Edge Slide — Destructive Mode (D) — Design

Builds on `2026-11-04-smart-edge-slide-design.md`. Everything there still
holds unless this document says otherwise.

## Why

The slide still stops early on ordinary meshes. On the user's U-shaped open
loop (one chain round a large n-gon panel, both ends on the same straight
edge):

- **Dragged inward** it stops at 0.24. The straight edge between the two
  chain ends is the end wall for both ends. The chain meets it at a sharp
  angle near one end, so the second vertex from that end runs into the wall.
  Collapse (C) does not help: it never folds an open chain's end segment.
- **Dragged outward** it stops at 0.10. Each end wall is one edge long. At its
  far vertex every onward edge turns 90° or more, so the wall ends, and the
  whole chain clamps there.

The user wants a mode where the slide behaves like Smart Inset's skeleton:
vertices that meet become one vertex and the loop keeps going. In their
words: "nothing should limit us; for us the only end is an open edge."

## What it is

A toggle, **D (Destructive)**, in the Smart Edge Slide modal and its redo
panel. With D on, the new loop moves like a wavefront on the surface:

- it never clamps at a fold, an end wall, an existing loop or a corner;
- it loses vertices where they meet, as Smart Inset's inset does;
- it stops only at open edges, or when there is nothing left of it.

"Destructive" means the result may be messy topology: triangles and n-gons
where vertices merged, a loop that split in two, ends landed on whatever edge
they reached. That is acceptable in this mode. It does not mean existing
geometry moves or gets deleted: the slide still only cuts.

## Goals

- **Only open edges stop it.** An open edge is an edge with exactly one
  visible face: the mesh boundary, or the border of hidden faces.
- **Vertices merge like a skeleton.**
  - When two neighbouring new vertices meet, they become one vertex and the
    loop continues one vertex shorter. This now includes an open chain's
    end vertex: an end absorbs the neighbours that reach it.
  - When a vertex runs into a wall it cannot cross (an end wall, an open
    edge), it stays on that wall and slides along it, and its neighbours
    merge into it as they arrive.
- **Passes through existing loops.** The new loop crosses existing edge
  loops and cuts them; reaching another loop never stops it.
- **Ends that have nowhere to go shoot on.**
  - While its end wall continues, an end slides along it, as now.
  - Where the wall ends, the end carries on along the line of the loop's
    end segment, across faces, until that line crosses an edge that is
    roughly perpendicular to it. The end lands on that edge.
  - If the line reaches an open edge first, the end lands there.
- **Width stays honest.** Width is still the in-surface distance from the
  source chain. Exact (E) and Ctrl snapping work in D as they do now.
- **The modal stays responsive.** Same budget as the unbounded slide: about
  30 ms per mouse move on a 100×100 grid.

## Non-goals

- Moving or deleting existing vertices, edges or faces.
- Changing anything when D is off and the angles are at their defaults.
  Default, E and C then behave exactly as on master today.
- Making the result clean quads. Where vertices merged, the strip has
  triangles; that is the point of the mode.

## Anti-goals (fails even if it technically works)

- **The loop vanishes below the limit.** At no width between 0 and the
  mode's limit may the preview go blank or Apply skip a chain. The last
  attempt to loosen end walls failed exactly this way; it must be tested
  the same way (randomised meshes, every width up to the limit).
- **Invalid topology.** New edges that cross each other or an existing edge
  without a vertex, overlapping faces, zero-length edges, or a face with a
  repeated vertex.
- **Noise decides the result.** Tilting the mesh by 1e-9 must not change
  the limit or make an end jump a whole edge.
- **Hidden clamping.** If D still stops somewhere other than an open edge or
  a fully used-up loop, that is a bug, not a limit.

## Behaviour

### Toggle

- **D** toggles destructive mode in the modal. HUD param "Destructive (D)";
  the help legend gets the line "D — Destructive: merge vertices, pass
  everything, stop only at open edges".
- Redo panel: `use_destructive` (bool, default off).
- D implies collapse. With D on, C is shown as on and greyed in the HUD.
  Pressing C does nothing while D is on, and C's own value comes back when D
  is turned off.
- Cancel restores D to its invoke value, like the other props.

### Tunable angles (all modes)

The user asked for every angle tolerance to be adjustable, not only the new
one. The current constants become operator props. Their defaults are today's
values, so with defaults nothing changes.

| Prop (label) | Default | What it does | Today |
|---|---|---|---|
| Rail Bend | 30° | How far a rail may turn when it continues into the next row; the same bound decides when an edge is too shallow to be a rail | `RAIL_MAX_DEV` |
| End Edge Angle | 60° | The smallest angle at which an edge leaving an open chain's end can be its end edge (end wall) | `END_SHALLOW` (today derived as 90° − Rail Bend; now separate) |
| Step Agreement | 30° | Faces whose away directions differ by less than this count as one surface | `STEP_AGREE_COS` |
| Step Difference | 60° | Faces whose away directions differ by more than this form a step | `STEP_DIFFER_COS` |
| Shoot Angle | 30° | D only: how far from perpendicular the edge a shooting end lands on may be | new |

- They live in the redo panel, in a collapsible "Angles" box under Width, E,
  C and D. Blender remembers the last used values. *(Our call.)*
- Changing one re-runs the operator from props, like any redo change.
- The labels use full words, no abbreviations.
- Step Agreement must stay below Step Difference; the panel clamps it.

### Merging (edge events)

- Two neighbouring new vertices that meet become one vertex. This is the
  existing collapse (C) drop, extended:
  - an open chain's end segments may fold too (today they never do): the
    end vertex absorbs its neighbour and keeps sliding along its wall;
  - a vertex whose path runs into a wall (an end wall or an open edge)
    **opens the loop there** (a split). The vertex becomes two new ends that
    slide apart along the wall, each staying on its own segment's offset
    line, so the width stays exact. The stretch of wall between them is not
    part of the new loop. This is the same thing an open chain's end does
    today, so a closed loop that reaches an open edge becomes an open one.
    That is a new event; today it clamps the chain. *(Our call: it keeps the
    width honest and matches how ends already behave; a pinned vertex would
    drift off the width.)*
- **Used up.** A piece of the loop is used up when it reaches its final
  skeleton state, as Smart Inset's inset does at full collapse:
  - a closed piece shrinks to an apex vertex or a ridge line;
  - an open piece pressed onto a wall leaves only its points on that wall.

  Apply then builds that final state: the apex or ridge vertices, or the
  points on the wall, with the connecting edges from the source vertices
  fanning into them. It never builds a microscopic copy of the loop or a
  sliver along the wall. *(Our call, following Smart Inset.)*
- **Pieces finish one by one.** After a split, a piece that is used up stays
  in its final state while the other pieces go on. Nothing waits for the
  first piece to finish, so there is no hidden clamping. *(Our call.)*

### Self-contact (split events)

- When a part of the new loop runs into a non-neighbouring part of itself,
  the loop splits in two at that point, as Smart Inset's wavefront does.
  Each piece goes on by itself. *(Our call, following Smart Inset.)*
- When the new loop reaches the source chain (a band that wraps round, such
  as a cylinder), the part that reaches it stops on the chain, as on an
  open edge. *(Our call.)*

### Ends: shooting on

- The end slides along its end wall while the wall continues, by today's
  rule (straight on within `RAIL_MAX_DEV`).
- Past the wall's last vertex, the end follows the straight extension of
  the loop's end segment, developed across the faces it crosses.
- It lands on the first crossed edge whose direction is within the Shoot
  Angle (default 30°) of perpendicular to the extension line. The user said
  "perpendicular, or close to it" and asked for the angle to be adjustable.
- If an open edge comes first, it lands on the open edge.
- If the landing point is within the snap tolerance of an existing vertex,
  the end goes to that vertex instead of making a sliver edge. *(Our call.)*
- If the line finds no edge before leaving the band (rare), the end stays on
  the wall's last vertex: it is "on its own", as the user allowed.
- As the width grows, the end slides along the edge it landed on, the same
  way it slides along a wall. If that edge ends, it shoots on again.

### Corners and steps

- A vertex with angle defect (a box corner) inside the strip no longer
  stops the slide. The trace goes on past it, splitting the turn evenly
  either side. *(Our call; the user's rule is "only open edges stop".)*
- Step lids work as now. Where a lid's far side is a real mesh edge, the
  trace goes on over the real faces behind it, as today.
- Where the far side is not a real edge, in D the lid keeps projecting as a
  sheet for as long as real faces lie under it. This is the projection the
  user asked for in the first place. Where nothing lies under the sheet any
  more, the trace drops onto the real surface it meets along the step
  normal, and goes on there. *(Our call; today the trace stops there.)*
- **Fins** (edges held by three or more visible faces) do not stop the
  trace in D. It crosses into the face that continues the current one most
  nearly flat, which is the smallest fold. A fin standing on the strip is
  therefore stepped over, not climbed. If two faces tie, the fin stops the
  trace like an open edge. *(Our call; the user's rule is "only open edges
  stop".)*

### Width limit and clamping in D

- A chain's limit is the width at which every piece of its loop is used up
  (see Merging).
- Dragging past the limit holds the final state. The HUD shows "clamped"
  only then.
- Clamping stays per chain, as now.

### Topology

- A merged vertex is one new mesh vertex.
- Connecting edges (variant B) as now. Where several source vertices merged
  into one new vertex, each of them gets a connecting edge to it unless that
  edge would cross an existing edge. That gives the skeleton fan. *(Our
  call.)*
- A split loop gives two loops, and both are selected after confirm.
- Crossings with existing edges get vertices, as now.

### Preview

- Same theme roles as now: `PREVIEW_LINE`, `PREVIEW_POINT`, `CLOSEST_POINT`,
  `ERROR_LINE`, drawn through `ui/draw/primitives`.
- No new colours. A merged vertex is drawn once.

### UV Stripe in D

- U still works. Where vertices merged, the strip has triangles, which UV
  Stripe already handles for collapsed Smart Inset insets.
- A split loop gives one strip per piece.
- Where a strip cannot be built (an end that shot onto a far edge and left
  no strip shape), UV Stripe skips that loop with its usual warning.

## Reference cases

- **The user's U loop.** The plan's first step captures it read-only from
  the open scene into a scratch JSON, the way `reference_mesh.json` was
  captured. It is never committed. Expected results:
  - inward, D on: the slide goes past 0.24. The vertices nearest the ends
    merge into the ends as they reach the bottom wall, and the loop goes on
    until it is used up on that wall;
  - outward, D on: past 0.10, the ends shoot on to the near-perpendicular
    edges of the bevel strip and keep going.
- **Collapse fixtures from the unbounded slide** keep their results when D is
  off.
- **A closed loop on a box** (round a cube's top): D passes the corners.

## Constraints

- Pure-Python core (`utils/smart_edge_slide_core.py`), unit-tested with
  pytest; bmesh work in the bridge; headless Blender tests through
  PowerShell with scratch `BLENDER_USER_*` dirs.
- The repo is public: no internal paths, asset names or mesh data in
  committed files.
- Previews only through the iOps theme.
- One squashed commit per feature on master.

## Left to the builder

- How to run the wavefront. Two obvious routes:
  - extend the slide's fold schedule (`_fold_events`) with the new events
    (end folds, wall hits, wall ends, splits);
  - or run Smart Inset's 2D wavefront (`utils/smart_inset_core.py`) on the
    band's development.
  Either way the development must stay local (a band is not flat in
  general), and `limit()` must stay exact.
- How default-mode rails and the skeleton interact. Default mode keeps
  following rails where they exist, and merges add on top; exact mode is
  the pure offset.
- Event-time tolerances, and how near-simultaneous events are ordered, as
  long as the noise anti-goal holds.
- Caching, so the modal budget holds.
