# Smart Edge Slide

![Smart Edge Slide](../img/ops/op_mesh_smart_edge_slide.png)

Cuts a new edge loop beside each selected chain of edges, at a set distance from it. The width is measured in the surface on one side of the chain, so on a folded strip such as a fillet it is the distance along the surface, not a straight chord. Every chain vertex is joined to its new vertex, so the strip between the two loops becomes quads where it can. Drag for width, type an exact value or Ctrl-snap it to a vertex, and flip the side of any chain with F. Edit Mesh mode.

**Hotkey:** Not bound by default — assign a key in *Preferences › iOps › Keymaps*, or run it from the iOps pie / operator search. Also available: iOps Pie › Smart Edge Slide.

## Controls
| Key | Action |
| --- | --- |
| Move mouse | Set width |
| <kbd>Shift</kbd> | Precise (slow) adjustment |
| <kbd>0</kbd>–<kbd>9</kbd>, <kbd>.</kbd>, <kbd>-</kbd>, <kbd>Backspace</kbd> | Type an exact width |
| <kbd>Ctrl</kbd> + move | Snap the width to the vertex under the cursor |
| <kbd>E</kbd> | Exact width on / off |
| <kbd>C</kbd> | Allow collapse on / off |
| <kbd>U</kbd> | UV Stripe on / off |
| <kbd>F</kbd> | Flip the side of the chain nearest the cursor |
| <kbd>MMB</kbd> / <kbd>Wheel</kbd> | Navigate the viewport |
| <kbd>H</kbd> | Show / hide the help legend |
| <kbd>LMB</kbd> / <kbd>Enter</kbd> | Confirm |
| <kbd>Esc</kbd> / <kbd>RMB</kbd> | Cancel |

## Options
- **Width** — distance of the new loop from the selected edges, measured in the surface beside them. Negative values cut on the other side.
- **Exact Width** — keep every new vertex at the exact width. Where a vertex's edge would miss it, the vertex goes to the exact corner instead, which adds cut points.
- **Allow Collapse** — let the width run past the point where a segment of the new loop shrinks to nothing, dropping that segment. Off stops the width there; the preview turns to the warning colour when clamped.
- **UV Stripe** — unwrap the faces between the selected edges and each new loop as one straight, even strip in the active UV map (a UV map is created when the mesh has none). U runs along the loop and V across it, from the selected edges (V = 0) to the new loop, at one shared scale; a pocket the loop wraps is straightened into the strip, and a closed loop is cut open at its sharpest corner. Off by default.
- **UV Stripe Mode** — *Fit 0–1* stretches each strip across U 0–1 with V in proportion, and stacks several strips upward in V with a small gap. *In Place* puts each strip back where its own faces' old UVs were, scaled to the texel density of the faces around it; a strip whose surrounding faces have no UVs fits 0–1 instead. Set in the redo panel.

## Tips
- The slide does not stop at existing edge loops. Each new vertex follows its edge on across the rows of faces beyond, as straight on as the faces allow, and the new loop keeps going until it reaches the edge of the mesh (or of the visible faces), an end wall, the selected edges themselves, or a corner it cannot unfold flat, such as the corner of a box. A wider width than that is clamped, and the preview turns to the warning colour.
- An edge with more than two faces, such as a fin standing on the surface, counts as the edge of the mesh: the slide stops there.
- The new loop wraps steps such as pockets: where a face beside the chain turns away from the surface (a pocket lip), the cut is projected onto the faces under it and runs up the pocket's side, across its top and back down.
- On an open chain each end of the new loop slides along an end wall: the edge that leaves the chain's end vertex across the side (the first one at least 60° off the chain), continued edge by edge across the rows. The loop never reaches round the end of the chain past it. Where the two ends' walls meet, an end turns there onto the other end's wall and slides on along it. Where the border of the side surface comes before any such edge, that end slides along the border instead.
- In the default mode each chain vertex gets one new vertex. Where the source loop bends against the side's edges, the width between two new vertices can drift slightly mid-edge; Exact Width removes that drift at the cost of extra points.
- A connecting edge from a chain vertex to its new vertex is skipped where it would cross an existing edge; the face stays an n-gon there.
- A closed chain round a single face, such as the border of an n-gon cap, is skipped: its new loop would lie inside that one face, with no edge to cut it into. Use [Smart Inset](op_mesh_smart_inset.md) there.
