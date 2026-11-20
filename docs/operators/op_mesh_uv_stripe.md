# UV Stripe

Unwraps each selected strip of faces into UV without stretch: the strip is torn where it bends and every piece is laid out at its true size, its rows straight, its ends at their real slant, every face turned the same way. A call lays the strips out at once with the options UV Stripe was last used with; change them in the redo panel, or start **UV Stripe (Interactive)** to switch every option with a key and watch the result in the UV editor while the viewport shows each piece's outline, in the warning colour where the strip is torn, and the faces whose UVs are still stretched (see *Stretched faces*). No UV editor work and no seams are needed: the seams are set to match the pieces. Edit Mesh mode.

**Hotkey:** Not bound by default — assign a key in *Preferences › iOps › Keymaps*, or run it from the operator search. *UV Stripe* lays the strips out at once; *UV Stripe (Interactive)* is a second entry in the same list and the search that starts the interactive mode below. Bind either, or both to different keys.

## Controls
The keys of the interactive mode (*UV Stripe (Interactive)*):

| Key | Action |
| --- | --- |
| <kbd>Q</kbd> | Mode: Fit 0–1 → In Place → Active |
| <kbd>W</kbd> | Orientation: Horizontal / Vertical |
| <kbd>E</kbd> | Layout: Auto → No Stretch → Rectangles → Even Rows → True Shape |
| <kbd>G</kbd> | Align (True Shape only): Auto → Longest Edge → Shortest Edge → Picked Edge |
| <kbd>V</kbd> | Pick Align Edge (True Shape only): click the edge a piece runs along (see *Aligning True Shape*); <kbd>V</kbd> again stops picking |
| <kbd>A</kbd> | Split at Bends on / off |
| <kbd>S</kbd> | Split at Seams on / off |
| <kbd>D</kbd> | Fit to Active: Height → Width and Height → Width |
| <kbd>Z</kbd> | Random Offset: None → Along Strip → Across Strip → Both |
| <kbd>X</kbd> | Mark Seams on / off |
| <kbd>C</kbd> | Pick Cut Edges: click cross edges to break a closed ring, or to mark and unmark where a strip is torn (see *Breaking a ring* and *Marking cuts*); <kbd>C</kbd> again stops picking |
| <kbd>R</kbd> | New offset seed |
| <kbd>F</kbd> | Merge Doubles on / off (applied on confirm) |
| <kbd>Tab</kbd> | More Options on / off: the HUD lists Layout, Stretch Limit, Align, Pick Align Edge and Pick Cut Edges; More Options adds every other option. Their keys work either way, and the choice is remembered |
| <kbd>Wheel</kbd> | Under Layout = Auto: Stretch Limit ±0.05 (<kbd>Ctrl</kbd>: ±0.01). Otherwise Bend Angle ±5° while Split at Bends is on (<kbd>Ctrl</kbd>: ±1°); with it off the wheel zooms the view |
| <kbd>Shift</kbd>+<kbd>Wheel</kbd> | Offset Limit ±0.05 while Random Offset is on (<kbd>Ctrl</kbd>+<kbd>Shift</kbd>: ±0.01); with it off the view pans |
| <kbd>MMB</kbd> | Navigate the viewport |
| <kbd>N</kbd> / <kbd>T</kbd> | Sidebar / toolbar, as usual |
| <kbd>H</kbd> | Show / hide the help legend |
| <kbd>LMB</kbd> / <kbd>Enter</kbd> / <kbd>Space</kbd> | Confirm |
| <kbd>Esc</kbd> / <kbd>RMB</kbd> | Cancel: the UVs and seams go back exactly as they were; while picking cut edges or the align edge, they only stop picking |

*UV Stripe* itself, run from the operator search or a key, applies the result at once; *UV Stripe (Interactive)* starts this interactive mode, and from a script `bpy.ops.iops.mesh_uv_stripe('INVOKE_DEFAULT', interactive=True)` does the same. The options confirmed here become the last-used options of the next call, and the redo panel and scripts give the same result without the interactive mode.

## Breaking a ring
A closed ring is normally cut open at one cross edge (an existing seam, else its sharpest corner) and, with Split at Bends, torn wherever it bends. To lay a ring out as **one straight strip** instead, press <kbd>C</kbd>: the cross edge nearest the cursor lights up, and on a ring that has no break yet <kbd>LMB</kbd> breaks the ring there and lays it out again. Picking stays on after each click, so you can go on to the next edge; the viewport keeps navigating while you pick, and <kbd>Esc</kbd> / <kbd>RMB</kbd> (or <kbd>C</kbd> again) stop picking without cancelling.
- A broken ring is one piece: Split at Bends does not tear it, and the seams on its other cross edges no longer cut it (Mark Seams clears them and marks the break). Cuts you mark by hand still tear it (see *Marking cuts*).
- A broken ring made **only of quads** is laid out as *Rectangles* whatever the Layout says: every face a rectangle, the strip one straight rectangle. A ring with triangles or n-gons follows the Layout as an open strip would.
- Clicking the break again removes it. To move a break, click it to remove it, then click the new edge; each ring keeps its own break. The breaks last for the redo panel, but a new run of UV Stripe starts without them.

## Marking cuts
While picking (<kbd>C</kbd>), every cross edge of a selected strip, open or closed, can be clicked. What a click does depends on the edge:
- On a closed ring with no break yet: the ring is broken there (see *Breaking a ring*).
- The ring's break: the break is removed.
- A cut you marked: the cut is removed.
- A tear made by Split at Bends: that tear is skipped, and the pieces on both sides join. The skipped tear stays drawn in the viewport, green with the default theme.
- A skipped bend tear: the tear comes back.
- A tear made by Split at Seams: nothing changes. Turn Split at Seams off, or clear the seam, to lay the strip across it.
- Any other cross edge: the strip is cut there by hand.

A cut marked by hand tears the strip whatever Split at Seams and Split at Bends are set to, also on a broken ring, and Mark Seams marks it like any other tear. A skipped tear only stops Split at Bends from tearing there. The HUD and the status bar show how many cuts are marked by hand. Like the breaks, the marked cuts and skipped tears last for the redo panel, and a new run starts without them.

## Aligning True Shape
With Layout = True Shape, or Auto for the pieces it lays out as True Shape, **Align** (<kbd>G</kbd>) sets what each unfolded piece runs along. The piece is still turned only, never mirrored or stretched, with its near row at the bottom.
- *Auto* (default) — the straighter row: its one edge longer than half the row, else the line from its first to its last vertex.
- *Longest Edge* / *Shortest Edge* — the longest or shortest edge of the piece's near and far rows (cross edges never count); on a tie the first one, near row first.
- *Picked Edge* — the edge picked on that piece. Press <kbd>V</kbd>: every edge of the laid-out pieces can be picked, the one nearest the cursor lights up, and <kbd>LMB</kbd> stores it, sets Align to Picked Edge and lays the strip out again. An edge of the near or far row runs along the strip; any other edge (a cross edge, an end, a diagonal) stands across it. Each piece keeps one picked edge: a new click on the same piece replaces it, and clicking the stored edge again removes it. An edge where the strip is torn belongs to both pieces beside it. A piece with no picked edge uses Auto. The picked edges in use are drawn in the viewport, green with the default theme. Picking stays on after each click; <kbd>V</kbd>, <kbd>Esc</kbd> or <kbd>RMB</kbd> stop it, and <kbd>C</kbd> switches to picking cut edges.

Each piece of a torn strip aligns on its own. Align is kept as a last-used value like the other options, and only UV Stripe uses it: Inset and Edge Slide always lay True Shape out as Auto. Like the cuts, the picked edges last for the redo panel, and a new run starts without them.

## What counts as a strip
Each edge-connected group of selected faces is one strip:
- **Open chain** — faces in a row, one face wide; it may bend. Quad, triangle or n-gon ends (a quad whose rails or end carry extra vertices, or whose rail steps in or out): an n-gon end is closed where its two rails come out most equal in length, so a step stays in its rail. A single n-gon selected on its own is a strip too.
- **Closed ring** — a loop of faces, such as a band round a cylinder; it is cut open at one rung, or at the cross edge you pick (see *Breaking a ring*).
- **Quad grid** — a patch several faces wide with four corners; the two longer sides become the rows.

A group that branches, touches itself at a vertex, has a hole, or is a single triangle is skipped with a warning; the other groups are still unwrapped.

## Direction
The result does not depend on how the mesh was built: an open strip runs from its end with the smaller coordinate on its main world axis (U = 0) toward the other end. A ring's lower boundary along its main axis lies on V = 0; for a flat ring it is the outer boundary.

## Options
All options are also in the redo panel. They are the settings of every UV Stripe layout in iOps: Inset and Edge Slide lay their strips out with the values UV Stripe was last used with.
- **Mode** — *Active* (default) lays out the strip holding the active face as In Place does, then fits every other piece to its UV bounding box without stretching it: each piece is scaled by one factor for both axes (see **Fit to Active**) and centred on the reference. A piece is never turned: every piece of a run is laid out by the same Orientation, so its length already runs along the reference's. With no active face among the selected faces, or no UV map to place it by, everything is laid out In Place and a short note says so. *Fit 0–1* scales all strips by one factor so the longest spans U 0–1, keeping one texel density, and stacks them upward. *In Place* keeps each strip where its old UVs were, at the texel density of the neighbouring faces.
- **Fit to Active** — used by Active; every choice scales a piece by one factor, so it keeps its proportions. *Height* (default) matches the reference's height, the width following by the same factor; *Width* matches its width; *Width and Height* fits the piece inside the reference's bounding box. For trim textures: Height puts every piece on the reference's band at one texel density, running past it along U; with Orientation = Vertical the band runs along V, so use Width.
- **Orientation** — *Horizontal* (default) runs the strip along U. *Vertical* turns it 90° counter-clockwise, never mirrored: Fit spans V 0–1 and stacks the strips to the right, In Place turns each strip about its own place. Under Active the reference strip turns and the other pieces follow it.
- **Layout** — *Auto* (default) chooses the tears and each piece's layout from the measured stretch. Every bend at all is a candidate tear, and a candidate is dropped when the faces stretch no more without it, so a sharp corner is torn, a gentle arc whose faces stay true in one piece is not, and a strip that only folds is never torn. Each piece is then laid out by the straightest layout that stretches it least (No Stretch, then Rectangles, then Even Rows) while its worst face stays within **Stretch Limit**; beyond it the piece is laid out as True Shape when that stretches it less. Split at Bends and Bend Angle do not apply; seams, cuts marked by hand, skipped tears and a ring's break do, and a broken ring goes through the same steps. A ring laid out whole uses Even Rows. *No Stretch* keeps every row at its true length: a flat piece between straight rails comes out at its exact shape, ends at their real slant. The rows are lined up again at every cross edge, so a slight bend below the bend angle, or a width that tapers, only distorts the faces where it happens, not the rest of the piece. *Rectangles* stands every cross edge vertical, so each quad becomes a rectangle; it stretches where the strip bends. *Even Rows* lays each row out by its own length, scaled to the strip's mean length. *True Shape* unfolds the faces across their shared edges, the way Unwrap lays out a strip of flat faces: each face keeps its real shape and stays joined to its neighbours, so a strip whose width changes maps one to one, and a strip that turns in its surface (a chamfer going round a corner) turns in UV instead of stretching. The strip is turned so its straighter row runs along U, near row at the bottom; it is never mirrored. **Align** chooses another direction: the longest or shortest row edge, or an edge you pick (see *Aligning True Shape*). Tears still come only from *Split at Seams* and *Split at Bends*. A piece that cannot unfold flat without a tear (a patch two faces wide over a doubly curved surface) keeps its straighter row straight instead and places every other vertex at its real distance from it. A ring laid out whole cannot close at true lengths and uses Even Rows; a ring with a picked break is laid out as an open strip (see *Breaking a ring*).
- **Stretch Limit** — used by Auto (1.25 by default, 1.0 to 3.0): the largest stretch of a piece's worst face that Auto still lays out in straight rows; beyond it the piece becomes True Shape when that stretches less. At 1.0 every piece that stretches at all becomes True Shape.
- **Split at Seams** — on by default: seams already inside a strip tear it into pieces; a ring with a single seam is cut open there instead of at its sharpest corner. Off, the strip is laid out across them (and Mark Seams clears them).
- **Split at Bends** — on by default: tears the strip at cross edges once it has turned by more than **Bend Angle** (5° by default) within its own surface since the last tear. One sharp corner tears there, a gentle arc tears at regular intervals; a strip that only folds (wrapped round a cylinder) is not torn. Works on quad, n-gon and triangulated strips one face wide. When a tear cannot be made the strip stays whole and a warning says why.
- **Mark Seams** — makes the seams match the pieces: every piece's outline (tears, and where a ring is cut open) is marked, and the seams inside a piece are cleared. Seams outside the selection are never touched; with Mark Seams off no seam changes.
- **Random Offset** — *Along Strip* (default) shifts every piece but the Active reference by a random amount along the strip's length (U for a horizontal strip, V for a vertical one), so strips stacked on one reference show different parts of the texture. *Across Strip* shifts across the strip, *Both* along and across, *None* leaves the pieces where the mode put them.
- **Offset Limit** — the largest random shift, in UV units (0.25 by default): each piece moves by a random amount between minus and plus this.
- **Offset Seed** — the same seed gives the same arrangement every time; change it for another.
- **Merge Doubles** — on by default (it changes the mesh only where it finds doubles). Vertices of the strip closer than 1 % of its typical edge (an unmerged double, such as two rail vertices 0.0002 apart) are always treated as one point, so they never skew the layout, and with Merge Doubles off UV Stripe warns how many it found. On, it merges exactly those vertices before laying the strip out (in the interactive mode, on confirm; the preview already looks the same).

## Stretched faces
After the layout every laid-out face is measured against its real shape: how much more its UVs scale it along one direction than along another (a uniform scale or a turn does not count). A face stretched by more than 5 % is drawn in the viewport, the HUD and the status bar count them, and the redo panel or a script reports the count as a warning. Typical causes: *Rectangles* on a strip that bends, a bend below the Bend Angle (or Split at Bends off), and rails that curve or taper.

## Tips
- With the defaults (Auto, Stretch Limit 1.25) a flat strip bending in its own plane comes out as stretch-free pieces, torn only where a tear lowers the stretch; a tapered piece that straight rows would stretch beyond the limit comes out as True Shape. A strip whose rails curve, or one that both bends and twists, is laid out as close as straight rows allow.
- Pinned UVs and the selection are left as they are.
- A mesh without a UV map gets one; cancelling the interactive mode removes it again.
