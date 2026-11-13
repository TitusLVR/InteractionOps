# UV Pipe and UV Stripe "Cup" break — design

Date: 2026-11-13

Two additions to the UV toolset, built on the UV Stripe core:

1. **Cup break in UV Stripe** — one key inside the existing modal that lets the
   user click the edge where a closed ring of faces is broken, so the ring lays
   out as one straight strip.
2. **UV Pipe** — a new modal operator that unwraps tubes: the wall becomes one
   island with a straight perimeter and a single lengthwise seam, cap rings
   become straight strips, cap centres stay disks.

Part 1 is small and ships first. Part 2 builds on it.

Items marked **(call)** were decided by the designer, not stated by the user.
Everything else is the user's.

## Why

UV Stripe already lays out strips of faces without stretch. Tubes and their
caps are the next most common shape in kitbash work and today need manual
seam marking, unwrap and straightening. The user wants to point at one edge
and get the finished layout, with the rest detected automatically and
correctable by clicking.

## Reference results

Two hand-made meshes in the user's scene define "correct". Rebuild them as
synthetic fixtures; do not commit the meshes, their file paths or asset names.

**Reference A — capped cylinder.** 32 sides, radius 1, height 2, four rows on
the wall. Bottom cap: two concentric flat quad rings (radius 1 → 0.671 →
0.493) and a 32-triangle fan in the centre. Top cap: one flat quad ring
(1 → 0.671) and a 32-gon in the centre. Expected: six islands.

| Part | UV result |
|---|---|
| Wall, 128 quads | One rectangle, one lengthwise seam of 4 edges. Width = circumference, height = 2. |
| Each flat cap ring (three of them) | One straight strip. Length = mean of its two circumferences, width = its real width. |
| Triangle fan | Disk, real shape. |
| 32-gon | Disk, real shape. |

All six share one texel density. Ring seams sit on the cylinder rims and on
every boundary between concentric rings.

**Reference B — bent pipe.** 12 sides, two optimised bends: 10 triangles and
poles with 6 and 8 edges on the inside of the bends, capped by two 12-gons.
Expected: three islands.

| Part | UV result |
|---|---|
| Wall, 236 faces | **One** island through both bends. One lengthwise seam of 15 edges that runs the whole pipe and passes straight through the poles. The two long sides (the seam) are exactly straight. Interior is relaxed; lines curve near the bends. |
| Two 12-gons | Disks. |

The bends are not cut out. The seam is routed through the messy topology and
the island relaxes inside a straight perimeter.

## Part 1 — Cup break in UV Stripe

### Behaviour

- **C** enters a pick sub-mode. The HUD shows it is active.
- While picking, the cross edge (rung) of a closed strip nearest the cursor is
  highlighted. Only rungs of closed strips can be picked.
- **LMB** sets that edge as the ring's break, re-lays out, and leaves the
  sub-mode. LMB confirms the operator again, as before.
- **C** again re-enters picking, so another ring or another edge can be chosen.
- In the sub-mode, **RMB / Esc** leave the sub-mode only **(call)**. Outside
  it they cancel the operator as today.
- Viewport navigation keeps working in the sub-mode.
- A ring with a picked break is one piece: **Split at Bends does not tear it**.
  (Today a flat annulus is torn into many pieces at the default 5°.)
- A ring with a picked break that consists **only of quads** is laid out as
  *Rectangles* straight away, whatever the Layout setting says: every face a
  rectangle, the strip a straight rectangle.
- A ring with a picked break that has triangles or n-gons follows the Layout
  setting like an open strip **(call)**: *Rectangles* where it can; *No
  Stretch*, *True Shape* and *Even Rows* work as on any open strip. Today a closed strip uses Even Rows
  for *No Stretch* and *True Shape* (and already honours *Rectangles*); that
  stays true for rings without a picked break.
- A picked break **replaces** any seam on another rung of the same ring
  **(call)**: with Split at Seams on, those seams no longer cut it, the ring
  is still one piece, and Mark Seams clears them.
- Rings without a picked break behave exactly as today (existing seam, else
  the sharpest corner).
- **R** takes over "new offset seed" from C (R for random).

### Constraints

- The picked breaks must survive redo (the operator is `REGISTER | UNDO`) and
  must not leak into `StripeSettings.from_last`, which Smart Inset and Smart
  Edge Slide read. How the picks are stored is the builder's choice.
- Mouse move is currently swallowed and LMB press confirms at once; the
  sub-mode needs hover handling and must take LMB before the confirm branch.
  HUD and help drag handlers still get LMB first.
- Preview goes through `ui/draw` primitives and `Role`, never raw gpu calls.
- Update what names the keys: HUD params, help overlay, status text, the
  operator doc page, and the headless tests that assert those lists
  (`test_modal_hud_and_help_list_every_key`, `test_modal_old_letters_are_free`
  — R is no longer free).

### Existing pieces to use

- `strip_from_faces(..., seam_edge=)` already starts a ring at a given rung
  and sets `strip.seam`.
- `rungs_at`, `slice_strip` / `_cut_open` cut a ring at one rung — but the
  result is still `closed=True`. Laying it out like an open strip needs a
  really open `Strip` with the break's vertices repeated (`corner_near` /
  `corner_far` exist for repeated ids). That conversion is new work.
- `bend_cut_rungs` is where the exemption from bend splitting belongs.
- `match_piece_seams` already marks a closed piece's cut rung as a seam.
- `utils/picking.py`: `raycast_edit_meshes`, `closest_face_edge`,
  `closest_edge_screen`.

## Part 2 — UV Pipe

New operator `iops.mesh_uv_pipe`, label "UV Pipe", Edit Mode on meshes,
`REGISTER | UNDO`, bindable but unbound by default, added to the same pie
menus as UV Stripe.

### Scope

- With faces selected: only those faces.
- With no faces selected: all visible faces of the objects in Edit Mode
  **(call)** — the "whole object, automatic" case.

### Analysis

On start the operator splits the faces into parts and proposes every seam.
This is pure Python, no bpy, in a new core module.

1. **Ring seams (automatic)** **(call — the whole rule)**. A ring seam is a
   **closed** loop, traced by the seam-loop walker on geometry (below), whose
   **mean** dihedral angle over its edges is at least the *Sharp Angle*
   (default 60°). Only closed loops cut; sharp edges that do not close are
   ignored. Consequences, which are the reason for the rule:
   - The lengthwise edges of a low-poly tube (30° on 12 sides, 45° on 8, 90°
     on 4) never cut the wall: followed straight they meet the rim at 90° and
     the walker stops, so they are not closed loops.
   - A rim (about 90° all round) cuts. A junction loop whose angle varies
     round the loop cuts when its mean passes the threshold.
   - A ring round a bend does not cut unless the bend at that ring is very
     sharp (mean dihedral of a mitre ring is roughly 2/π of the bend angle).
   - A chamfered or rounded rim is not found; the user clicks it.
2. **Classify each part.**
   - *Flat* part (normals agree within tolerance): a cap. Peel one-face-wide
     closed rings from its boundary inward for as long as the ring is a valid
     closed strip; each peeled ring is a **ring strip**; whatever is left in
     the middle (an n-gon, a triangle fan, anything else) is a **disk**. The
     boundaries between peeled rings are ring seams.
   - Two or more boundary loops and not peeled: a **wall**.
   - Anything else (a dome, a blob): a **free** part.
3. **Lengthwise seam per wall (automatic).** See "The seam loop".

Ring seams are placed automatically only where the tube ends or breaks: rims,
cap rings, junctions with another tube, abrupt diameter steps. With the
defaults a wall is not split at a bend; the user adds ring seams there by
clicking, or turns on Split at Bends.

**Split at Bends** (key A, **off by default (call)**). When on, a wall is cut
by ring seams where it bends: walking the wall's closed ring loops from one
end to the other, the turn of the tube's direction is summed, and a ring seam
is placed at the ring where the sum passes the *Bend Angle* (default 45°
**(call)**); the sum then restarts. A messy bend with no closed ring loop
through it gets no cut there. These are automatic seams and follow the state
model below.

**Split at Seams** (key S, **off by default (call)** — UV Pipe proposes its
own seams, and a mesh that was unwrapped before is full of old ones). When on,
seams already on the mesh between two processed faces are cuts: a closed one
is a ring seam, one that joins a wall's two ends is that wall's lengthwise
seam, anything else simply cuts and the parts are classified as usual.

**State model (call).** Seams = automatic seams + loops the user added − loops
the user removed. The automatic set is recomputed when Sharp Angle or Loop
Angle changes; the user's additions and removals are kept and re-applied. A
removed seam is not found again. After any change every part is classified
again by the same rules:

- Removing the seam between two peeled rings stops the peel at that boundary;
  the merged flat ring, several faces wide, is a wall and gets a lengthwise
  (radial) seam like any other wall.
- Removing a rim merges wall and cap; if the merged part fits no rule it is a
  free part.

### The seam loop

A loop is traced edge by edge: at each vertex it continues along the edge that
is straightest with respect to the edge it came by. It goes through poles,
triangles and n-gons and does not depend on quad topology.

- **Loop Angle**, default **120°**: the minimum angle between consecutive
  edges of the loop. The loop continues while the bend at a vertex is no
  sharper than this (deviation from straight up to 60°) and stops at a sharper
  one. Exposed in the HUD, the redo panel and on the wheel.
- **Loop source**, two modes:
  - *Geometry* (default): angles measured on 3D positions. Always available.
  - *UV*: angles measured in the UV layout the mesh had when the operator
    started. Unavailable when there is no UV layer; the HUD shows it disabled.
    At a vertex with more than one UV position (an old island border) that one
    step is measured on geometry instead. The automatic seam choice uses
    whichever source is current. Default, availability and the border rule are
    **(call)**.
- A loop that returns to its start is a **ring** loop. A loop that ends on two
  boundaries of its part is a **lengthwise** loop. This is how a clicked edge
  is told apart; no axis estimation **(call)**.
- A lengthwise loop that stops before reaching both ends is invalid: drawn in
  the error colour and not confirmable **(call)**. Lowering the Loop Angle
  usually fixes it.
- Automatic choice for a wall: among the valid lengthwise loops starting on
  one end, the **shortest by 3D length** **(call)** — on a bent pipe that is
  the inside of the bends, as in reference B. Ties go to the lowest start
  position, so the result is deterministic.
- A wall's **ends** are the two boundary loops its seam connects. With more
  than two boundary loops (a junction hole, a smooth tee) the automatic seam
  runs between the two longest loops; the user may click a loop between any
  two. Width is the mean of the two connected loops; the others float
  **(call)**.
- When a wall has no valid lengthwise loop, the automatic seam is the shortest
  edge path between its two ends, and the HUD says it is a fallback
  **(call)**. A wall always gets a seam, so the modal opens with a full layout
  and `execute()` never skips a wall. Only a part where even that fails
  becomes a free part, with a warning.
- A lengthwise loop clicked on a ring strip picks that ring's break
  **(call)**.

`mesh_uv_shortest_mark.py` has a working angle-based walker
(`_edge_loop_arm`), but as methods on operator caches. Write the Pipe walker
as a pure function in the new core; do not refactor UV Shortest Mark.

### Modal interaction

Same shell as UV Stripe: snapshot of UVs and seam flags, re-layout on every
change, restore on cancel, HUD and help overlays, status text, navigation
pass-through, N and T passed through.

| Input | Action |
|---|---|
| Mouse move | Highlight the edge under the cursor and the loop it would make. |
| LMB on an edge | First click: the loop becomes pending and is drawn as such. Second click on the same loop commits it and the UVs are laid out again. |
| committed lengthwise loop | Replaces that wall's seam. |
| committed ring loop | Toggles a ring seam there (adds, or removes one already present, automatic ones included). |
| Alt + Wheel | Step the seam of the wall under the cursor to the next / previous lengthwise loop around the section **(call: the wheel is the stepping input)**. |
| Wheel (Ctrl: fine) | Loop Angle ±5° (±1°). |
| Shift + Wheel (Ctrl: fine) | Sharp Angle ±5° (±1°) **(call)**. |
| Shift + Alt + Wheel (Ctrl: fine) | Bend Angle ±5° (±1°), while Split at Bends is on **(call)**. |
| G | Loop source: Geometry / UV **(call)**. |
| A | Split at Bends. |
| S | Split at Seams. |
| Z | Random Offset axis: None / Along / Across / Both. |
| R | New offset seed. |
| F | Merge Doubles (applied on finish, as in UV Stripe). |
| P | Pack **(call)**. |
| Q | Mode: Fit 0–1 / In Place / Active. |
| D | Fit to Active: Both / Width / Height. |
| W | Orientation: Horizontal / Vertical. |
| E | Layout (below). |
| X | Mark Seams. |
| Enter / Space | Finish. |
| RMB / Esc | Drop the pending loop if there is one; otherwise cancel and restore. |

The second click commits the cut and unwraps, and the modal **stays open** for
more cuts and option changes; Enter or Space finishes **(call)**. The user's
words were "second click confirms the cut and the unwrap happens".

The automatic result is already laid out when the modal opens, so Enter right
away accepts it.

Letters shared with UV Stripe keep their UV Stripe meaning.

### Layout of each part

- **Wall.** The perimeter is fixed first: the two seam sides are straight and
  parallel, each end loop is a straight line with vertices spaced by arc
  length. Width = mean length of the two end loops, height = mean length of
  the two seam sides. Interior vertices are relaxed inside it (the mean-value
  Tutte solve in `uv_stripe_core` is the existing tool). Extra boundary loops
  inside a wall — a junction hole — float free in the relax. Triangles and
  poles are fine: only the perimeter has to be exact.
- **Layout setting for walls** (key E):
  - *Rectangle* (default) — as above, straight perimeter. This is "with
    tightening".
  - *Quads* — where the wall is a regular quad grid, every quad becomes a
    rectangle (rows at mean ring spacing, columns at mean side width). A wall that is not a
    full grid falls back to *Rectangle* with a HUD notice.
  - *No Stretch* — "without tightening": the seam sides stay straight, the
    ends are not forced straight and keep their natural shape. How this is
    solved is the builder's choice (Blender's own unwrap followed by
    straightening the seam sides is acceptable).
  The three names and the default are **(call)**; the user asked for an
  all-quads result, tolerance of triangles, a straight perimeter, and
  with / without tightening modes.
- **Ring strip.** Through the UV Stripe core as a closed strip cut at one
  rung, Even Rows: length = mean of the two loop lengths. The cut rung is
  chosen as UV Stripe does today **(call)**.
- **Disk.** Flat: projected onto its plane at real size.
- **Free part.** Blender's unwrap, scaled to real size **(call)**.

### Placement

As UV Stripe, same code path where possible (`apply_stripes` /
`finish_stripes`):

- *Fit 0–1*: all parts of an object share one texel density. With **Pack** on
  (default **(call)**) the islands are packed into 0–1 without rotation and
  without changing their relative scale, as in reference A; Blender's own
  island packer is the expected tool **(call)**. With Pack off they are
  stacked with the 0.01 gap, the longest spanning 0–1, as UV Stripe does.
- *Random Offset* (axis, limit, seed) and *Merge Doubles* behave as in UV
  Stripe. Offset Limit is set in the HUD-visible property and the redo panel;
  it has no wheel binding in UV Pipe **(call)**. Random offset is applied
  after packing and only when Pack is off or the mode is not Fit 0–1
  **(call)** — an offset would undo a pack.
- *In Place*: each part keeps its old UV centre and takes the neighbours'
  texel density.
- *Active*: as UV Stripe **(call — the user named only the first two)**.
- The default mode is *Fit 0–1* **(call)**, not UV Stripe's *Active*, which
  would fit disks and rings to the active island and break the shared texel
  density.
- *Mark Seams*: seams follow the part outlines; seams inside a part are
  cleared.

### Redo and execute

`execute()` without the modal runs the automatic analysis with the current
properties. Loops committed in the modal must survive redo; encoding is the
builder's choice, same constraint as Part 1.

## Non-goals (this round)

- Reading UV Pipe's settings from Smart Inset or Smart Edge Slide.
- Packing in UV Stripe.
- Changing UV Shortest Mark.

## Anti-goals

- A wall torn into pieces at an optimised bend when the user did not ask.
- A seam loop that stops at the first pole or triangle.
- Any change in how UV Stripe lays out open strips, or rings without a picked
  break. Smart Inset and Smart Edge Slide must be unaffected.
- Previews drawn outside the iOps theme.

## Where things go

| What | Where |
|---|---|
| Pipe analysis, loop walker, wall layout (pure) | `utils/uv_pipe_core.py` |
| bmesh layer for Pipe | `operators/uv_pipe_bridge.py` |
| Pipe operator | `operators/mesh_uv_pipe.py` |
| Cup changes | `operators/mesh_uv_stripe.py`, `operators/uv_stripe_bridge.py`, `utils/uv_stripe_select_core.py`, `utils/uv_stripe_core.py` |
| Pure tests | `tests/test_uv_pipe_core.py`, additions to the `tests/test_uv_stripe_*.py` files |
| Headless tests | `tests/blender/test_uv_pipe_operator.py`, additions to `tests/blender/test_uv_stripe_operator.py` |
| Docs | `docs/operators/op_mesh_uv_pipe.md`, `docs/operators/op_mesh_uv_stripe.md`, `docs/operators.md`, `docs/index.md`, `mkdocs.yml` |
| Registration | `__init__.py`, `ui/iops_pie_edit.py`, `ui/iops_pie_menu.py` |

## Acceptance

- Reference A as a synthetic fixture: six islands as in the table, one texel
  density, wall width : height = 2πr : h, each ring strip length = mean
  circumference.
- Reference B as a synthetic fixture (a 12-sided tube with one bend collapsed
  to triangles and a pole of more than four edges is enough): the wall is one
  island, the automatic seam reaches both ends through the pole, both seam
  sides are straight in UV, no face is flipped.
- Loop Angle: a loop over a 90° corner stops at 120° and continues at 80°.
- Split at Bends: off, the bent fixture's wall is one island; on at 45°, a
  tube with one 90° bend made of clean rings is cut into two walls.
- Split at Seams: on, a wall with an old lengthwise seam keeps that seam.
- Pack: reference A in Fit 0–1 with Pack on lies inside 0–1 with no overlap
  and one texel density.
- Cup: a flat 8-segment quad annulus with a picked break is one piece with
  Split at Bends on at 5°; the picked edge is the seam; it is eight rectangles
  with Layout left on *No Stretch*.
- Existing UV Stripe, Smart Inset and Smart Edge Slide tests pass, apart from
  the two key-list tests updated for C and R.
- Cancel restores UVs and seam flags exactly, in both operators.

## Left to the builder

- Storage of picked breaks and committed loops for redo.
- Flatness tolerance and the other numeric tolerances.
- The solve behind *No Stretch* walls.
- HUD wording and row order, following the UV Stripe HUD.
- How much of the modal shell is shared between the two operators.
