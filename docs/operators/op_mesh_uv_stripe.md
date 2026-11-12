# UV Stripe

Unwraps each selected strip of faces into UV without stretch: the strip is torn where it bends and every piece is laid out at its true size, its rows straight, its ends at their real slant, every face turned the same way. While it runs you switch every option with a key and watch the result in the UV editor; the viewport shows each piece's outline and, in the warning colour, where the strip is torn. No UV editor work and no seams are needed: the seams are set to match the pieces. Edit Mesh mode.

**Hotkey:** Not bound by default — assign a key in *Preferences › iOps › Keymaps*, or run it from the operator search.

## Controls
| Key | Action |
| --- | --- |
| <kbd>R</kbd> | Orientation: Horizontal / Vertical |
| <kbd>M</kbd> | Mode: Fit 0–1 → In Place → Active |
| <kbd>S</kbd> | Layout: No Stretch → Rectangles → Even Rows |
| <kbd>E</kbd> | Split at Seams on / off |
| <kbd>B</kbd> | Split at Bends on / off |
| <kbd>Wheel</kbd> | Bend Angle ±5° while Split at Bends is on (<kbd>Ctrl</kbd>: ±1°); with it off the wheel zooms the view |
| <kbd>X</kbd> | Mark Seams on / off |
| <kbd>MMB</kbd> | Navigate the viewport |
| <kbd>H</kbd> | Show / hide the help legend |
| <kbd>LMB</kbd> / <kbd>Enter</kbd> / <kbd>Space</kbd> | Confirm |
| <kbd>Esc</kbd> / <kbd>RMB</kbd> | Cancel: the UVs and seams go back exactly as they were |

Run from the operator search or a key, it starts in this interactive mode; the redo panel and scripts give the same result without it.

## What counts as a strip
Each edge-connected group of selected faces is one strip:
- **Open chain** — faces in a row, one face wide; it may bend. Quad, triangle or n-gon ends (a quad whose rails or end carry extra vertices).
- **Closed ring** — a loop of faces, such as a band round a cylinder; it is cut open at one rung.
- **Quad grid** — a patch several faces wide with four corners; the two longer sides become the rows.

A group that branches, touches itself at a vertex, has a hole, or is a single triangle is skipped with a warning; the other groups are still unwrapped.

## Direction
The result does not depend on how the mesh was built: an open strip runs from its end with the smaller coordinate on its main world axis (U = 0) toward the other end. A ring's lower boundary along its main axis lies on V = 0; for a flat ring it is the outer boundary.

## Options
All options are also in the redo panel.
- **Mode** — *Fit 0–1* scales all strips by one factor so the longest spans U 0–1, keeping one texel density, and stacks them upward. *In Place* keeps each strip where its old UVs were, at the texel density of the neighbouring faces. *Active* keeps the active face where it is in UV, like Follow Active Quads: the strip continues from it at the active face's size, turned the quarter turn (never mirrored) that best matches its old corners, so the direction comes from the active face. The other pieces of a torn strip, and the other strips, take the same size and turn, each centred where its old UVs were. With no active face among the selected faces, or one without UVs, it lays out In Place and says so; another object in Edit Mode without its active face selected is laid out In Place.
- **Orientation** — *Horizontal* (default) runs the strip along U. *Vertical* turns it 90° counter-clockwise, never mirrored: Fit spans V 0–1 and stacks the strips to the right, In Place turns each strip about its own place. Not used by Active.
- **Layout** — *No Stretch* (default) keeps every row at its true length: a flat piece between straight rails comes out at its exact shape, ends at their real slant. *Rectangles* stands every cross edge vertical, so each quad becomes a rectangle; it stretches where the strip bends. *Even Rows* lays each row out by its own length, scaled to the strip's mean length. A ring laid out whole cannot close at true lengths and uses Even Rows.
- **Split at Seams** — off by default: a strip is laid out across the seams already inside it. On, those seams tear it into pieces; a ring with a single seam is cut open there instead of at its sharpest corner.
- **Split at Bends** — on by default: tears the strip at cross edges once it has turned by more than **Bend Angle** (15° by default) within its own surface since the last tear. One sharp corner tears there, a gentle arc tears at regular intervals; a strip that only folds (wrapped round a cylinder) is not torn. Works on quad, n-gon and triangulated strips one face wide. When a tear cannot be made the strip stays whole and a warning says why.
- **Mark Seams** — makes the seams match the pieces: every piece's outline (tears, and where a ring is cut open) is marked, and the seams inside a piece are cleared. Seams outside the selection are never touched; with Mark Seams off no seam changes.

## Tips
- With the defaults (No Stretch, Split at Bends) a flat strip bending in its own plane comes out as stretch-free pieces. A strip whose rails curve, or one that both bends and twists, is laid out as close as straight rows allow.
- Pinned UVs and the selection are left as they are.
- A mesh without a UV map gets one; cancelling the interactive mode removes it again.
