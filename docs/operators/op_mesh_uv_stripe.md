# UV Stripe

Unwraps each selected strip of faces into UV with as little stretch as it can: the strip is torn only where a tear lowers the stretch, and every piece is laid out with what you ask to be straight (its long sides, its ends), the layout itself chosen by measuring the stretch. A call lays the strips out at once with the options UV Stripe was last used with; change them in the redo panel, or start **UV Stripe (Interactive)** to switch every option with a key and watch the result in the UV editor while the viewport shows the four sides of every piece, straight or free, and the faces whose UVs are still stretched (see *Stretched faces*); a click on a side makes it straight or free. No UV editor work and no seams are needed: the seams are set to match the pieces. Edit Mesh mode.

**Hotkey:** Not bound by default — assign a key in *Preferences › iOps › Keymaps*, or run it from the operator search. *UV Stripe* lays the strips out at once; *UV Stripe (Interactive)* is a second entry in the same list and the search that starts the interactive mode below. Bind either, or both to different keys.

## Controls
The keys of the interactive mode (*UV Stripe (Interactive)*):

| Key | Action |
| --- | --- |
| <kbd>Q</kbd> | Mode: Fit 0–1 → In Place → Active |
| <kbd>W</kbd> | Orientation: Horizontal / Vertical |
| <kbd>LMB</kbd> on a side | Make that side of that piece straight or free (see *Picking sides*); anywhere else LMB does nothing |
| <kbd>E</kbd> | Straight Sides: Both → Longer Side → Shorter Side → None |
| <kbd>A</kbd> | Ends: Slanted → Both → Longer End → Shorter End |
| <kbd>B</kbd> | Balance: Even Texel / Least Stretch (strips several faces wide) |
| <kbd>G</kbd> | Align (pieces unfolded at their real shape): Auto → Longest Edge → Shortest Edge → Picked Edge |
| <kbd>V</kbd> | Pick Align Edge: click the edge a piece unfolded at its real shape runs along (see *Aligning the real shape*); <kbd>V</kbd> again stops picking |
| <kbd>S</kbd> | Split at Seams on / off |
| <kbd>D</kbd> | Fit to Active: Height → Width and Height → Width |
| <kbd>Z</kbd> | Random Offset: None → Along Strip → Across Strip → Both |
| <kbd>X</kbd> | Mark Seams on / off |
| <kbd>C</kbd> | Pick Cut Edges: click cross edges to break a closed ring, or to mark and unmark where a strip is torn (see *Breaking a ring* and *Marking cuts*); <kbd>C</kbd> again stops picking |
| <kbd>R</kbd> | New offset seed |
| <kbd>F</kbd> | Merge Doubles on / off (applied on confirm) |
| <kbd>Tab</kbd> | More Options on / off: the HUD always lists Straight Sides, Ends and Stretch Limit, and Align, Manual Cuts and Doubled Vertices only while they apply; More Options adds Balance, Mode, Orientation, Fit to Active, Split at Seams, Mark Seams, Random Offset, Offset Limit, Offset Seed and Merge Doubles. With More Options off, one of these rows still shows while its option is away from its default. Every key works either way, and the choice is remembered |
| <kbd>Wheel</kbd> | Stretch Limit ±0.05 (<kbd>Ctrl</kbd>: ±0.01) |
| <kbd>Shift</kbd>+<kbd>Wheel</kbd> | Offset Limit ±0.05 while Random Offset is on (<kbd>Ctrl</kbd>+<kbd>Shift</kbd>: ±0.01); with it off the view pans |
| <kbd>MMB</kbd> | Navigate the viewport |
| <kbd>N</kbd> / <kbd>T</kbd> | Sidebar / toolbar, as usual |
| <kbd>H</kbd> | Show / hide the help legend: hidden at the start, it lists every key of the modal, grouped as Shape, Layout and General |
| <kbd>Enter</kbd> / <kbd>Space</kbd> | Confirm |
| <kbd>Esc</kbd> / <kbd>RMB</kbd> | Cancel: the UVs and seams go back exactly as they were; while picking cut edges or the align edge, they only stop picking |

While <kbd>C</kbd> or <kbd>V</kbd> is on, a line at the top of the HUD says so. The status bar shows one fixed line: *LMB side: straight/free · Tab: more · Enter: confirm · Esc: cancel*, and while picking a line of the pick mode's own.

*UV Stripe* itself, run from the operator search or a key, applies the result at once; *UV Stripe (Interactive)* starts this interactive mode, and from a script `bpy.ops.iops.mesh_uv_stripe('INVOKE_DEFAULT', interactive=True)` does the same. The options confirmed here become the last-used options of the next call, and the redo panel and scripts give the same result without the interactive mode.

## Picking sides
Every piece has four sides, found by its corners: two long sides (the rails) and two ends. The viewport draws them all the time, a straight side in the preview colour and a free side in the plain line colour; the side under the cursor lights up (a side hidden behind other faces cannot be picked, and on an edge where the strip is torn the piece whose face is under the cursor is picked). **LMB on a side** turns it over: a long side straight ↔ free, an end upright ↔ free, and the piece is laid out again at once. A long side is drawn as it is laid out (Stretch Limit may have relaxed it); an end is drawn as asked: a free end is not forced upright, though the layout that stretches least may stand it upright all the same. A click anywhere else does nothing (it never confirms).
- **Straight Sides** (<kbd>E</kbd>) and **Ends** (<kbd>A</kbd>) set what every piece starts from; a click overrides that piece on top of them, and the override stays when you press <kbd>E</kbd> or <kbd>A</kbd> again.
- A click fixes both sides of its pair (both long sides, or both ends) as they are drawn at that moment, the clicked one turned over, so the other one stays as you see it.
- A piece whose long sides you clicked is never relaxed by **Stretch Limit**: it keeps what you set however much it stretches.
- With both long sides free the piece is unfolded at its real shape and **Align** applies; its ends then follow the faces, so a click on an end shows no change until a long side is straight again.
- The clicks last for the redo panel; a new run of UV Stripe starts from Straight Sides and Ends.

## Breaking a ring
A closed ring is normally cut open at one cross edge (an existing seam, else its sharpest corner) and torn where a tear lowers the stretch. To lay a ring out as **one straight strip** instead, press <kbd>C</kbd>: the cross edge nearest the cursor lights up, and on a ring that has no break yet <kbd>LMB</kbd> breaks the ring there and lays it out again. Picking stays on after each click, so you can go on to the next edge; the viewport keeps navigating while you pick, and <kbd>Esc</kbd> / <kbd>RMB</kbd> (or <kbd>C</kbd> again) stop picking without cancelling.
- A broken ring is laid out as an open strip starting at the break: the seams on its other cross edges no longer cut it (Mark Seams clears them and marks the break), but it is still torn where a tear lowers the stretch, like any open strip (a ring that unrolls without stretch, such as a band round a cylinder, stays one piece). Cuts you mark by hand still tear it (see *Marking cuts*), and a tear can be skipped by clicking it.
- Clicking the break again removes it. To move a break, click it to remove it, then click the new edge; each ring keeps its own break. The breaks last for the redo panel, but a new run of UV Stripe starts without them.

## Marking cuts
While picking (<kbd>C</kbd>), every cross edge of a selected strip, open or closed, can be clicked. What a click does depends on the edge:
- On a closed ring with no break yet: the ring is broken there (see *Breaking a ring*).
- The ring's break: the break is removed.
- A cut you marked: the cut is removed.
- A tear made where it lowers the stretch: that tear is skipped, and the pieces on both sides join. The skipped tear stays drawn in the viewport, green with the default theme.
- A skipped tear: the tear comes back.
- A tear made by Split at Seams: nothing changes. Turn Split at Seams off, or clear the seam, to lay the strip across it.
- Any other cross edge: the strip is cut there by hand.

A cut marked by hand tears the strip whatever Split at Seams is set to, also on a broken ring, and Mark Seams marks it like any other tear. A skipped tear only stops the stretch-lowering tear there. While picking cuts the tears are drawn in the warning colour over the sides; otherwise the sides are drawn over them, so a piece's end shows straight or free where the strip is torn. The HUD shows how many cuts are marked by hand. Like the breaks, the marked cuts and skipped tears last for the redo panel, and a new run starts without them.

## Aligning the real shape
For every piece laid out with no long side straight (Straight Sides = None, a piece whose long sides you clicked free, or one Stretch Limit relaxed that far), **Align** (<kbd>G</kbd>) sets what the unfolded piece runs along; the HUD shows its row only then. The piece is still turned only, never mirrored or stretched, with its near row at the bottom.
- *Auto* (default) — the straighter row: its one edge longer than half the row, else the line from its first to its last vertex.
- *Longest Edge* / *Shortest Edge* — the longest or shortest edge of the piece's near and far rows (cross edges never count); on a tie the first one, near row first.
- *Picked Edge* — the edge picked on that piece. Press <kbd>V</kbd>: every edge of the laid-out pieces can be picked, the one nearest the cursor lights up, and <kbd>LMB</kbd> stores it, sets Align to Picked Edge and lays the strip out again. An edge of the near or far row runs along the strip; any other edge (a cross edge, an end, a diagonal) stands across it. Each piece keeps one picked edge: a new click on the same piece replaces it, and clicking the stored edge again removes it. An edge where the strip is torn belongs to both pieces beside it. A piece with no picked edge uses Auto. The picked edges in use are drawn in the viewport, green with the default theme. Picking stays on after each click; <kbd>V</kbd>, <kbd>Esc</kbd> or <kbd>RMB</kbd> stop it, and <kbd>C</kbd> switches to picking cut edges.

Each piece of a torn strip aligns on its own. Align is kept as a last-used value like the other options, and only UV Stripe uses it: Inset and Edge Slide always align an unfolded piece by Auto. Like the cuts, the picked edges last for the redo panel, and a new run starts without them.

## What counts as a strip
Each edge-connected group of selected faces is one strip:
- **Open chain** — faces in a row, one face wide; it may bend. Quad, triangle or n-gon ends (a quad whose rails or end carry extra vertices, or whose rail steps in or out): an n-gon end is closed where its two rails come out most equal in length, so a step stays in its rail. A single n-gon selected on its own is a strip too.
- **Closed ring** — a loop of faces, such as a band round a cylinder; it is cut open at one rung, or at the cross edge you pick (see *Breaking a ring*).
- **Wide patch** — a patch several faces wide (a profile swept along an arc: a ledge, a wall, a flange) with four corners; the two longer sides become the rails, the other two the ends. Quads, triangles and n-gons may mix. The corners are the four boundary vertices used by one face only; when a collapsed vertex took one or two of them (two or three left), the missing ones are the boundary vertices on two faces with the smallest angle within the surface (the sum of their faces' corners there), each sharper than 150° and sharper by more than 15° than every other boundary vertex. A disc, a cap or a patch with no clear corner is skipped. Measured within the surface, a vertex where the patch folds along its end is no corner, and a corner dulled by a collapse still is.

A group that branches, touches itself at a vertex, has a hole, or is a single triangle is skipped with a warning; the other groups are still unwrapped.

## Direction
The result does not depend on how the mesh was built: an open strip runs from its end with the smaller coordinate on its main world axis (U = 0) toward the other end. A ring's lower boundary along its main axis lies on V = 0; for a flat ring it is the outer boundary.

## Options
All options are also in the redo panel. They are the settings of every UV Stripe layout in iOps: Inset and Edge Slide lay their strips out with the values UV Stripe was last used with.
- **Mode** — *Active* (default) lays out the strip holding the active face as In Place does, then fits every other piece to its UV bounding box without stretching it: each piece is scaled by one factor for both axes (see **Fit to Active**) and centred on the reference. A piece is never turned: every piece of a run is laid out by the same Orientation, so its length already runs along the reference's. With no active face among the selected faces, or no UV map to place it by, everything is laid out In Place and a short note says so. *Fit 0–1* scales all strips by one factor so the longest spans U 0–1, keeping one texel density, and stacks them upward. *In Place* keeps each strip where its old UVs were, at the texel density of the neighbouring faces.
- **Fit to Active** — used by Active; every choice scales a piece by one factor, so it keeps its proportions. *Height* (default) matches the reference's height, the width following by the same factor; *Width* matches its width; *Width and Height* fits the piece inside the reference's bounding box. For trim textures: Height puts every piece on the reference's band at one texel density, running past it along U; with Orientation = Vertical the band runs along V, so use Width.
- **Orientation** — *Horizontal* (default) runs the strip along U. *Vertical* turns it 90° counter-clockwise, never mirrored: Fit spans V 0–1 and stacks the strips to the right, In Place turns each strip about its own place. Under Active the reference strip turns and the other pieces follow it.
- **Straight Sides** — what is straight along every piece. *Both* (default): both long sides and every line of edges running along the piece straight and horizontal. *Longer Side* / *Shorter Side*: only that long side (by its 3D length; the near one on a tie) straight, the other long side and the lines inside placed by the least stretch alone. *None*: nothing straightened, every face unfolded at its real shape (each face keeps its shape and stays joined to its neighbours, the piece turned by **Align**, never mirrored); a piece that cannot unfold flat keeps its straighter row straight and places every other vertex at its real distance from it.
- **Ends** — which ends stand upright (across the strip, at a right angle to its length). *Slanted* (default): both free, not forced either way: they keep their real slant unless a layout with upright ends stretches less. *Both*: both upright. *Longer End* / *Shorter End*: only the end whose cross edges are longer / shorter in 3D (on a tie the end at U = 0). On a strip one face wide an upright end is its cross edge standing vertical. Not used under Straight Sides = None.
- **How a piece is laid out** — UV Stripe measures every layout that keeps what is asked and takes the one whose worst face stretches least (the first on a tie); a layout that folds a face loses to one that does not. Both long sides with free ends (Slanted): the rows at their true lengths (the faces of a flat piece between straight rails at their exact shape), every cross edge vertical (each quad a rectangle), each row by its own length scaled to the mean, the balanced layout with free ends, or balanced with upright ends. Both long sides with both ends upright: the three with upright ends. One end upright: balanced. One long side straight: balanced, with the ends as asked (free ends: free or upright). The balanced layouts, the costly ones, are only tried on a strip one face wide when none of the straight-row layouts already lays it out with no face stretched beyond 5 %. The balanced layout spreads the stretch that cannot be avoided over all the faces, quads, triangles and n-gons alike, instead of letting it land on one row, and keeps straight exactly what is asked. When every layout that keeps what is asked folds a face, a straight-row layout that folds fewer is taken instead.
- **Tears** — a strip one face wide is torn where its bends make the faces stretch: every bend is a candidate; a candidate that cannot be torn yet is tried again once the others are in (so a rectangular frame tears at all four corners into equal pieces, never three), and a candidate is dropped when the faces stretch no more without it, so a sharp corner is torn, a gentle arc whose faces stay true in one piece is not, and a strip that only folds is never torn. A patch several faces wide is never torn. Seams (Split at Seams), cuts marked by hand, skipped tears and a ring's break apply as described above. A ring laid out whole keeps every row at the mean length, closed.
- **Stretch Limit** — 1.25 by default, 1.0 to 3.0: a piece whose worst face stretches more than this is relaxed one step at a time, both long sides → the longer one only → none (its real shape), and stops at the first step within the limit, else at the least stretched. A piece whose long sides you clicked is not relaxed. At 1.0 every piece that stretches at all is relaxed.
- **Balance** — under More Options; for strips several faces wide only (one face wide nothing changes). *Even Texel* (default) keeps every face near its real size: an even texel density, with some stretch left where the rows must differ in length. *Least Stretch* minimises the measured stretch itself: far less stretch, with the texel density differing by up to about 1.3× between faces. It never folds a face; where it cannot improve on Even Texel, Even Texel stands.
- **Split at Seams** — on by default: seams already inside a strip tear it into pieces; a ring with a single seam is cut open there instead of at its sharpest corner. Off, the strip is laid out across them (and Mark Seams clears them).
- **Mark Seams** — makes the seams match the pieces: every piece's outline (tears, and where a ring is cut open) is marked, and the seams inside a piece are cleared. Seams outside the selection are never touched; with Mark Seams off no seam changes.
- **Random Offset** — *Along Strip* (default) shifts every piece but the Active reference by a random amount along the strip's length (U for a horizontal strip, V for a vertical one), so strips stacked on one reference show different parts of the texture. *Across Strip* shifts across the strip, *Both* along and across, *None* leaves the pieces where the mode put them.
- **Offset Limit** — the largest random shift, in UV units (0.25 by default): each piece moves by a random amount between minus and plus this.
- **Offset Seed** — the same seed gives the same arrangement every time; change it for another.
- **Merge Doubles** — on by default (it changes the mesh only where it finds doubles). Vertices of the strip closer than 1 % of its typical edge (an unmerged double, such as two rail vertices 0.0002 apart) are always treated as one point, so they never skew the layout, and with Merge Doubles off UV Stripe warns how many it found. On, it merges exactly those vertices before laying the strip out (in the interactive mode, on confirm; the preview already looks the same).

## Stretched faces
After the layout every laid-out face is measured against its real shape: how much more its UVs scale it along one direction than along another (a uniform scale or a turn does not count). A face stretched by more than 5 % is drawn in the viewport, the HUD counts them, and the redo panel or a script reports the count as a warning. Typical causes: Ends = Both on a strip that bends, a skipped tear, a long side clicked straight on a piece that tapers, and rails that curve.

## Tips
- With the defaults (Straight Sides Both, Ends Slanted, Stretch Limit 1.25) a flat strip bending in its own plane comes out as stretch-free pieces, torn only where a tear lowers the stretch; a tapered piece that both straight sides would stretch beyond the limit keeps only its longer side straight, or its real shape. A strip whose rails curve, or one that both bends and twists, is laid out as close as straight sides allow.
- For a trim sheet, keep Straight Sides on Both and set Ends to Both where the ends must meet the trim's edges; click a single piece's side where one piece needs something else.
- Pinned UVs and the selection are left as they are.
- A mesh without a UV map gets one; cancelling the interactive mode removes it again.
