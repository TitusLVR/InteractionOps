# UV Pipe

Unwraps tubes and their caps in one go: the tube's wall becomes one island with a straight perimeter and a single lengthwise seam, every flat cap ring becomes a straight strip, and the middle of each cap stays a disk at its real shape. All islands share one texel density and are packed into 0–1. The seams are found automatically and set to match the islands; you correct them by selecting a loop and marking it. Edit Mesh mode.

**Hotkey:** Not bound by default — assign a key in *Preferences › iOps › Keymaps*, or run it from the operator search or the iOps pie menus next to UV Stripe.

**Scope:** the selected faces; with no face selected, every visible face of the meshes in Edit Mode.

## Controls
| Key | Action |
| --- | --- |
| <kbd>Mouse move</kbd> | Shows the edge under the cursor and the seam loop through it |
| <kbd>LMB</kbd> | Mark the loop under the cursor as a seam, or unmark it when it is one; the UVs are laid out again at once. Every loop can be marked: a ring seam, a wall seam, a ring break or an open seam |
| <kbd>C</kbd> | The same for the single edge under the cursor: mark or unmark it (on a cross edge of a ring strip: set or take back that ring's break) |
| <kbd>Alt</kbd>+<kbd>C</kbd> | Unmark the whole loop under the cursor: its seam edges stop being seams, your picked wall seam or ring break is dropped — for a loop that is only partly a seam, where <kbd>LMB</kbd> would mark the rest |
| <kbd>Alt</kbd>+<kbd>Wheel</kbd> | Step the seam of the wall under the cursor to the next / previous lengthwise loop round the tube |
| <kbd>Ctrl</kbd>+<kbd>Wheel</kbd> | Loop Angle ±5° |
| <kbd>Shift</kbd>+<kbd>Wheel</kbd> | Sharp Angle ±5° (<kbd>Ctrl</kbd>+<kbd>Shift</kbd>: ±1°) |
| <kbd>Shift</kbd>+<kbd>Alt</kbd>+<kbd>Wheel</kbd> | Bend Angle ±5° while Split at Bends is on (<kbd>Ctrl</kbd>: ±1°) |
| <kbd>Ctrl</kbd>+<kbd>Alt</kbd>+<kbd>Wheel</kbd> | Hard Edge Angle ±5° |
| <kbd>T</kbd> / <kbd>Shift</kbd>+<kbd>T</kbd> | Seam Side: Shortest → Bottom → Top → Left → Right → Front → Back (<kbd>Shift</kbd>: backward); drops the wall seams you picked |
| <kbd>G</kbd> | Loop Source: Geometry / UV (UV only when the mesh had a UV map) |
| <kbd>A</kbd> | Split at Bends on / off |
| <kbd>S</kbd> | Split at Seams on / off |
| <kbd>Z</kbd> | Random Offset: None → Along Strip → Across Strip → Both |
| <kbd>R</kbd> | New offset seed |
| <kbd>F</kbd> | Merge Doubles on / off (applied on finish) |
| <kbd>P</kbd> | Pack on / off |
| <kbd>Q</kbd> | Mode: Fit 0–1 → In Place → Active |
| <kbd>D</kbd> | Fit to Active: Width and Height → Width → Height |
| <kbd>W</kbd> | Orientation: Horizontal / Vertical |
| <kbd>E</kbd> | Layout: Rectangle → Quads → No Stretch |
| <kbd>X</kbd> | Mark Seams on / off |
| <kbd>MMB</kbd> (with any modifier) / <kbd>Wheel</kbd> | Navigate the viewport: orbit, pan, zoom |
| <kbd>N</kbd> | Sidebar, as usual |
| <kbd>H</kbd> | Show / hide the help legend |
| <kbd>Enter</kbd> / <kbd>Space</kbd> | Finish |
| <kbd>Esc</kbd> / <kbd>RMB</kbd> | Cancel: UVs, seams and options go back exactly as they were |

### What the colours mean
| Line | Meaning |
| --- | --- |
| Active Line colour | The loop under the cursor: what <kbd>LMB</kbd> marks or unmarks |
| Locked Line colour, wider | The edge under the cursor: what <kbd>C</kbd> marks or unmarks |
| Preview Line colour | Every seam the layout has now — automatic or marked by you, the part outlines, each wall's seam and each ring strip's cut: exactly the edges Mark Seams marks. It is drawn over the loop under the cursor, so a marked loop keeps the seam colour and takes the loop colour as soon as you unmark it |
| Error Line colour | A wall's fallback seam (no lengthwise loop was found) |

The HUD is kept short: its **Loop (LMB)** row says what <kbd>LMB</kbd> will do to the loop under the cursor — *Add ring seam*, *Add seam*, *Remove seam*, *Set wall seam*, *Automatic wall seam*, *Set ring break* or *Remove ring break* — and its **Edge (C)** row what <kbd>C</kbd> will do to the edge under the cursor. Rows that do not apply are hidden: Fit to Active outside Active mode, Pack outside Fit 0–1, Random Offset while packing (Offset Limit and Seed also while it is None), Bend Angle while Split at Bends is off, Loop Source when the mesh had no UV map. The wheel keys of the angles are listed in the help legend (<kbd>H</kbd>) and the table above. Notices and warnings are reported when the tool finishes.

The automatic result is laid out as soon as the tool starts, so <kbd>Enter</kbd> right away accepts it. Run from the redo panel or a script, it gives the same result without the interactive mode, the loops you committed included.

## Parts
The faces are split into parts at the ring seams, and each part is one of:
- **Wall** — a part with two or more boundary loops that is not a flat cap ring: the tube's side. It gets one lengthwise seam from one end to the other.
- **Ring** — a one-face-wide closed band peeled off the outside of a flat cap, ring after ring inward. Laid out as one straight strip whose length is the mean of its two loops.
- **Disk** — what is left in the middle of a flat cap (an n-gon, a triangle fan, anything): projected flat at its real size.
- **Free part** — anything else (a dome, a closed blob): first cut as a hard-surface part (see below); what is left is unwrapped by Blender's unwrap and scaled to its real size, and a warning names it.

### Hard-surface parts
A part that is no tube, ring or cap — a cube, a bevelled box, a bracket — is cut along its hard edges in a separate pass that runs after everything above and touches only those parts: walls, rings, disks and their seams never change, even when their own edges are sharp. A part with ends but lengthwise loops from fewer than half the vertices of its longest end (a box with holes in it) is no tube either and goes to this pass, unless you picked its wall seam or it has one under Split at Seams. The hard edges are the edges **marked Sharp** inside such parts when the mesh has any there; otherwise the edges whose angle between faces reaches **Hard Edge Angle** (30° by default). Every flat piece is projected at its real size, holes included, like a cap disk; a piece that is still curved is unwrapped by Blender's unwrap with its outline as the seam. The hard edges are marked as seams. A seam loop you removed is never cut again by this pass.

## Seams
- **Ring seams** are found automatically: a closed loop of edges whose mean angle between faces is at least **Sharp Angle** (60° by default) cuts — the rims of a tube, the edges between cap rings, junctions and diameter steps. Sharp edges that do not close into a loop do not cut, so the lengthwise edges of a low-poly tube never split the wall.
- A **seam loop** is traced edge by edge, always on along the straightest edge, through poles, triangles and n-gons alike. It goes on while the angle between consecutive edges is at least **Loop Angle** (120° by default) and stops at a sharper turn.
- Each wall's **lengthwise seam** is the shortest lengthwise loop that reaches both ends — on a bent pipe that is the inside of the bends. When no loop reaches both ends, the shortest edge path between them is used, drawn in the error colour and reported as a warning; lowering Loop Angle usually finds a real loop.
- **Seam Side** moves the automatic lengthwise seam to hide it: *Shortest* (default) is the rule above; *Bottom (−Z)*, *Top (+Z)*, *Left (−X)*, *Right (+X)*, *Front (−Y)* and *Back (+Y)* take, of the lengthwise loops, the one whose faces point most toward that world direction — on a lying tube *Bottom* puts the seam along its underside. It follows the tube's surface, so on a bent pipe the seam stays on that side of the tube round the bend. Loops that face the side equally (a direction along the tube's axis) fall back to the shortest of them. A seam you pick by hand or with <kbd>Alt</kbd>+<kbd>Wheel</kbd> overrides it, and so does an existing seam under Split at Seams; pressing <kbd>T</kbd> drops the wall seams you picked so the new side applies (ring breaks and ring seams stay). The direction is judged by the faces' normals: on a mesh whose normals point inward the opposite side is chosen.
Every loop below is marked with <kbd>LMB</kbd> on it, and a second <kbd>LMB</kbd> on it takes the mark back. <kbd>C</kbd> does the same for one edge, <kbd>Alt</kbd>+<kbd>C</kbd> unmarks the whole loop. Unmarking always takes the seam off in one press, also where an edge you added is a seam for an automatic reason as well (it is then removed).
- Marking a **ring loop** toggles a ring seam there: it adds one, or removes one already present, automatic ones included. A removed seam is not found again when the options change.
- Marking a **lengthwise loop** on a wall makes it that wall's seam; marking it again gives the wall back its automatic seam (see Seam Side).
- Any other loop is an **open seam**: from the edge under the cursor it runs both ways, through any seams it crosses, until it reaches the border of the faces or a turn sharper than Loop Angle — so every edge of a marked open seam gives the whole seam again. Marking it adds a seam along it, or removes it when all of it is already a seam (an automatic one included; the hard-surface pass then does not cut it again); a loop only partly on seams is added. <kbd>Alt</kbd>+<kbd>C</kbd> unmarks the loop under the cursor in one go: its edges that are seams stop being seams (yours are taken back, automatic ones are removed and not found again), the rest is left alone. An open seam that splits a part into two cuts it there; one that does not (a slit) turns the part into a free part, unwrapped by Blender's unwrap with the slit as a seam and no warning. On a curved part the UVs open along the slit; on a flat one the unwrap keeps the plane, so the slit is marked but its two sides stay together. To set a wall's seam, mark its lengthwise loop instead: an added open seam along a whole wall is a slit, not the wall's seam.
- Marking a **cross edge of a ring** strip picks where that ring is cut open; marking it again takes the pick back.

## Options
All options are also in the redo panel.
- **Mode** — *Fit 0–1* (default): all parts of an object share one texel density; with **Pack** (on by default) Blender's island packer fits them into 0–1 without rotating them and without changing their relative size. With Pack off they are stacked upward with a small gap, the longest spanning U 0–1, as UV Stripe does. *In Place* keeps each part where its old UVs were, at the neighbouring faces' texel density. *Active* fits the other parts onto the part holding the active face, as UV Stripe does.
- **Fit to Active** — used by Active, as in UV Stripe.
- **Orientation** — *Horizontal* (default) runs a wall's circumference and a ring's length along U; *Vertical* turns them 90°.
- **Layout** (walls) — *Rectangle* (default): the two seam sides are straight and parallel, each end is a straight line; width = the mean length of the two ends, height = the seam's length; the inside is relaxed. *Quads*: on a regular quad grid every quad becomes a rectangle; any other wall falls back to Rectangle with a notice. *No Stretch*: Blender's unwrap of the wall, then only the seam sides are made straight; the ends keep their natural shape.
- **Loop Source** — *Geometry* (default) measures loop angles on the 3D positions; *UV* in the UV layout the mesh had when the tool started (where a vertex has more than one UV, that step is measured on geometry).
- **Hard Edge Angle** — 30° by default: the angle between faces from which an edge cuts a part that is no tube (see Hard-surface parts); used only when no edge of such parts is marked Sharp. At 180° nothing is cut.
- **Split at Bends** — off by default: when on, a wall is cut by a ring seam each time the tube has turned by **Bend Angle** (45° by default). A bend with no clean ring of edges through it gets no cut.
- **Split at Seams** — off by default (an old unwrap leaves many seams): when on, seams already on the mesh are cuts; a seam joining a wall's two ends becomes its lengthwise seam.
- **Seam Side** — *Shortest* by default: where each wall's automatic lengthwise seam goes (see Seams).
- **Mark Seams** — on by default: every part outline, each wall's seam and each ring's cut are marked; the seams inside a part are cleared. Seams outside the faces in scope are never touched.
- **Random Offset**, **Offset Limit**, **Offset Seed** — as in UV Stripe, applied only when the islands are not packed (packing would undo them).
- **Merge Doubles** — as in UV Stripe: doubled vertices are merged before the layout (in the interactive mode, on finish).

## Limits
- A chamfered or rounded rim has no single sharp loop and is not found: click it (<kbd>LMB</kbd>) to add the ring seam.
- On a tube with 4 or 5 sides the rim's corners are sharper than the default Loop Angle, so no rim closes and the tube is no tube to UV Pipe: it is cut as a hard-surface part, into its flat faces. Lower Loop Angle (for example to 80°) and the rims are found, so it is unwrapped as a tube with one wall.
- A closed surface with no ends (a torus) is a free part.
- The selection, the active face, pins and the UVs of faces outside the scope are left as they are; a mesh without a UV map gets one, and cancelling removes it again.
