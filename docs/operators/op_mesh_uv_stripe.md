# UV Stripe

Unwraps each selected strip of faces into UV without stretch: the strip is torn where it bends and every piece is laid out at its true size, its rows straight, its ends at their real slant, every face turned the same way. While it runs you switch every option with a key and watch the result in the UV editor; the viewport shows each piece's outline, in the warning colour where the strip is torn, and the faces whose UVs are still stretched (see *Stretched faces*). No UV editor work and no seams are needed: the seams are set to match the pieces. Edit Mesh mode.

**Hotkey:** Not bound by default — assign a key in *Preferences › iOps › Keymaps*, or run it from the operator search.

## Controls
| Key | Action |
| --- | --- |
| <kbd>Q</kbd> | Mode: Fit 0–1 → In Place → Active |
| <kbd>W</kbd> | Orientation: Horizontal / Vertical |
| <kbd>E</kbd> | Layout: No Stretch → Rectangles → Even Rows → True Shape |
| <kbd>A</kbd> | Split at Bends on / off |
| <kbd>S</kbd> | Split at Seams on / off |
| <kbd>D</kbd> | Fit to Active: Height → Width and Height → Width |
| <kbd>Z</kbd> | Random Offset: None → Along Strip → Across Strip → Both |
| <kbd>X</kbd> | Mark Seams on / off |
| <kbd>C</kbd> | Break Ring: pick the cross edge a closed ring is opened at (see *Breaking a ring*); <kbd>C</kbd> again stops picking |
| <kbd>R</kbd> | New offset seed |
| <kbd>F</kbd> | Merge Doubles on / off (applied on confirm) |
| <kbd>Wheel</kbd> | Bend Angle ±5° while Split at Bends is on (<kbd>Ctrl</kbd>: ±1°); with it off the wheel zooms the view |
| <kbd>Shift</kbd>+<kbd>Wheel</kbd> | Offset Limit ±0.05 while Random Offset is on (<kbd>Ctrl</kbd>+<kbd>Shift</kbd>: ±0.01); with it off the view pans |
| <kbd>MMB</kbd> | Navigate the viewport |
| <kbd>N</kbd> / <kbd>T</kbd> | Sidebar / toolbar, as usual |
| <kbd>H</kbd> | Show / hide the help legend |
| <kbd>LMB</kbd> / <kbd>Enter</kbd> / <kbd>Space</kbd> | Confirm |
| <kbd>Esc</kbd> / <kbd>RMB</kbd> | Cancel: the UVs and seams go back exactly as they were; while picking a break, they only stop picking |

Run from the operator search or a key, it starts in this interactive mode; the redo panel and scripts give the same result without it.

## Breaking a ring
A closed ring is normally cut open at one cross edge (an existing seam, else its sharpest corner) and, with Split at Bends, torn wherever it bends. To lay a ring out as **one straight strip** instead, press <kbd>C</kbd>: the cross edge of a selected ring nearest the cursor lights up, and <kbd>LMB</kbd> breaks the ring there and lays it out again. Only cross edges of closed rings can be picked; the viewport keeps navigating while you pick, and <kbd>Esc</kbd> / <kbd>RMB</kbd> (or <kbd>C</kbd> again) stop picking without cancelling.
- A broken ring is one piece: Split at Bends does not tear it, and the seams on its other cross edges no longer cut it (Mark Seams clears them and marks the break).
- A broken ring made **only of quads** is laid out as *Rectangles* whatever the Layout says: every face a rectangle, the strip one straight rectangle. A ring with triangles or n-gons follows the Layout as an open strip would.
- Picking another edge of the same ring moves its break there; each ring keeps its own break. The breaks last for the redo panel, but a new run of UV Stripe starts without them.

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
- **Layout** — *No Stretch* (default) keeps every row at its true length: a flat piece between straight rails comes out at its exact shape, ends at their real slant. The rows are lined up again at every cross edge, so a slight bend below the bend angle, or a width that tapers, only distorts the faces where it happens, not the rest of the piece. *Rectangles* stands every cross edge vertical, so each quad becomes a rectangle; it stretches where the strip bends. *Even Rows* lays each row out by its own length, scaled to the strip's mean length. *True Shape* unfolds the faces across their shared edges, the way Unwrap lays out a strip of flat faces: each face keeps its real shape and stays joined to its neighbours, so a strip whose width changes maps one to one, and a strip that turns in its surface (a chamfer going round a corner) turns in UV instead of stretching. The strip is turned so its straighter row runs along U, near row at the bottom; it is never mirrored. Tears still come only from *Split at Seams* and *Split at Bends*. A piece that cannot unfold flat without a tear (a patch two faces wide over a doubly curved surface) keeps its straighter row straight instead and places every other vertex at its real distance from it. A ring laid out whole cannot close at true lengths and uses Even Rows; a ring with a picked break is laid out as an open strip (see *Breaking a ring*).
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
- With the defaults (No Stretch, Split at Bends) a flat strip bending in its own plane comes out as stretch-free pieces. A strip whose rails curve, or one that both bends and twists, is laid out as close as straight rows allow.
- Pinned UVs and the selection are left as they are.
- A mesh without a UV map gets one; cancelling the interactive mode removes it again.
