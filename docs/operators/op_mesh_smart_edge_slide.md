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
| <kbd>C</kbd> | Allow collapse on / off (does nothing while Destructive is on) |
| <kbd>D</kbd> | Destructive mode on / off |
| <kbd>Q</kbd> | Auto Adjust on / off: when a slide stops on a setting, Q changes it for you |
| <kbd>U</kbd> | UV Stripe on / off |
| <kbd>F</kbd> | Flip the side of the chain nearest the cursor |
| <kbd>MMB</kbd> / <kbd>Wheel</kbd> | Navigate the viewport |
| <kbd>H</kbd> | Show / hide the help legend |
| <kbd>LMB</kbd> / <kbd>Enter</kbd> | Confirm |
| <kbd>Esc</kbd> / <kbd>RMB</kbd> | Cancel |

## Options
- **Width** — distance of the new loop from the selected edges, measured in the surface beside them. Negative values cut on the other side. Each new launch starts at 0; the redo panel keeps the width you confirmed.
- **Exact Width** — keep every new vertex at the exact width. Where a vertex's edge would miss it, the vertex goes to the exact corner instead, which adds cut points.
- **Allow Collapse** — let the width run past the point where a segment of the new loop shrinks to nothing, dropping that segment. Off stops the width there; the preview turns to the warning colour when clamped.
- **Destructive** — let the new loop run like a skeleton instead of stopping at the first trouble. See [Destructive mode](#destructive-mode). It implies Allow Collapse: the Allow Collapse row in the HUD shows on and greyed while Destructive is on, <kbd>C</kbd> does nothing, and Allow Collapse keeps its own value for when Destructive goes off. Off by default.
- **Auto Adjust** — the one switch for the angles and Tolerance in the modal: when a slide stops on a setting, <kbd>Q</kbd> changes it for you. When a chain stops at its limit and a setting would let it go on (an angle or Tolerance), the modal changes that setting by itself as you drag past the limit, and keeps going while the width is still past the new limit. The HUD names each change for two seconds ("Auto Adjust: raised Rail Bend to 41°") and says "Auto Adjust: no setting helps here" where nothing does. With Auto Adjust off, the red note on why a chain stops ends in "press Q to let it adjust" where a setting would help. It stops when no setting helps, when a setting reaches the end of its range (Tolerance goes up to 1% of the size of the faces beside the chain), or after 8 changes for one chain in one drag. The angles are shared by every chain. The redo panel keeps the new values, confirming cuts with them as they are, and cancelling puts them back. The result can look rough. Off by default.
- **Tolerance** — Destructive only (greyed out otherwise): points of the new loop closer than this merge, and two things that happen this close together as the width grows count as one. At 0 (the default) it is picked from the size of the mesh. Raise it, to 0.001 say, when a rough or noisy mesh makes the slide refuse a cut; the result may then be off by up to this much. Set in the redo panel.
- **UV Stripe** — unwrap the faces between the selected edges and each new loop as one straight, even strip in the active UV map (a UV map is created when the mesh has none). U runs along the loop and V across it, from the selected edges (V = 0) to the new loop, at one shared scale; a pocket the loop wraps is straightened into the strip, and a closed loop is cut open at its sharpest corner. Off by default.
- **UV Stripe Mode** — *Fit 0–1* stretches each strip across U 0–1 with V in proportion, and stacks several strips upward in V with a small gap. *In Place* puts each strip back where its own faces' old UVs were, scaled to the texel density of the faces around it; a strip whose surrounding faces have no UVs fits 0–1 instead. Set in the redo panel.
- **Angles** — a collapsible box in the redo panel with the angle tolerances the slide uses. See [Angles](#angles).

## Tips
- The slide does not stop at existing edge loops. Each new vertex follows its edge on across the rows of faces beyond, as straight on as the faces allow, and the new loop keeps going until it reaches the edge of the mesh (or of the visible faces), an end wall, the selected edges themselves, or a corner it cannot unfold flat, such as the corner of a box. A wider width than that is clamped, and the preview turns to the warning colour.
- An edge with more than two faces, such as a fin standing on the surface, counts as the edge of the mesh: the slide stops there.
- The new loop wraps steps such as pockets: where a face beside the chain turns away from the surface (a pocket lip), the cut is projected onto the faces under it and runs up the pocket's side, across its top and back down.
- On an open chain each end of the new loop slides along an end wall: the edge that leaves the chain's end vertex across the side (the first one at least the **End Edge Angle**, 60° by default, off the chain), continued edge by edge across the rows. The loop never reaches round the end of the chain past it. Where the two ends' walls meet, an end turns there onto the other end's wall and slides on along it. Where the border of the side surface comes before any such edge, that end slides along the border instead.
- In the default mode each chain vertex gets one new vertex. Where the source loop bends against the side's edges, the width between two new vertices can drift slightly mid-edge; Exact Width removes that drift at the cost of extra points.
- A connecting edge from a chain vertex to its new vertex is skipped where it would cross an existing edge; the face stays an n-gon there.
- With Destructive off, a closed chain round a single face, such as the border of an n-gon cap, is skipped: its new loop would lie inside that one face, with no edge to cut it into. Use [Smart Inset](op_mesh_smart_inset.md) there, or turn Destructive on: it builds that inset itself.

## Destructive mode
Press <kbd>D</kbd> (or tick **Destructive** in the redo panel) to let the new loop run like a skeleton of the chain, the way a straight skeleton grows inwards, instead of stopping at the first trouble:
- **Vertices that meet merge.** Where a segment of the loop shrinks to nothing, or two parts of it come together, they become one new vertex. Every chain vertex that merged into it keeps a connecting edge to it, unless that edge would cross an existing edge, so the strip between the loops can become a fan of triangles.
- **Walls open the loop.** Where a part of the loop meets a wall, an end wall of an open chain or an open edge of the mesh (a hole's side, say), the loop opens there: it gives two ends, each running on along the wall. A loop that is opened gives several pieces, and all of them are selected after the cut: their edges, and the vertex of a piece that ends as a single point.
- **Ends shoot on.** An end slides along its wall while the wall goes on. Past the wall's last vertex it follows the straight extension of the loop's end segment across the faces, and lands on the first edge it crosses that is turned no more than the Shoot Angle away from square-on to that line; an open edge always qualifies. If the landing point is at an existing vertex, the end goes to the vertex. As the width grows the end slides along the edge it landed on, and shoots on again where that edge ends. If the line crosses no edge before the band ends, the end stays on the wall's last vertex.
- **Pieces collapse.** A piece of the loop that runs out of room ends as a single vertex (an apex), as a ridge of edges, or, inside a branching shape, as a tree of edges along its middle, and holds that shape from then on.
- **Closed loops split where they touch.** Where two parts of a closed loop run into each other, the loop splits there into closed loops, and each goes on by itself until it collapses.
- **The width limit.** The loop goes on over existing edge loops. The width limit is the width at which every piece of the loop is used up, or earlier, where the loop reaches something the mode cannot pass yet: a corner that does not unfold flat, a fin, its own chain, or two ends of it meeting. Dragging past it holds that final shape, and the preview turns to the warning colour only then. A fin stops the loop: it does not open there the way it does at an open edge. Where the cut at that width could not be built cleanly, the limit is the largest width below it that can, so the preview always shows what confirming builds.
- **Refused cuts.** A cut the add-on cannot build cleanly, such as a loop that crosses itself, is skipped with a warning naming the reason, and the other chains are still cut. Nothing is half built: a chain is cut whole or not at all.
- **Very large faces.** Next to a face with more than 48 sides the destructive mode would be slow, so Destructive is off for that chain: it is cut as with Allow Collapse, and a warning says so. The other chains keep Destructive.
- **Rough meshes.** On a very rough or noisy mesh the slide may refuse a cut close to the width at which two parts of the loop meet. Raising **Tolerance** usually lets it through.

With **UV Stripe** on, each piece of an opened loop gets its own strip, and several strips stack as with several chains. Where merged vertices leave triangles in the strip they are laid out as they are for a collapsed Smart Inset. A piece that cannot form a strip, such as one whose end shot onto a far edge and left no strip shape, is skipped with the usual UV Stripe warning.

With Destructive off everything works as described above, unchanged.

## Angles
The **Angles** box in the redo panel holds the angle tolerances of the slide, for exact values after the cut; in the modal only Auto Adjust changes them. Their defaults are the values the slide always used, so nothing changes until you move one. Changing one runs the operator again from its properties.
- **Rail Bend** (30°) — the most a rail path may turn at a vertex, and the most a rail may lean from the middle of the corner, before the slide stops following it.
- **End Edge Angle** (60°) — how far from the chain an open chain's end edge must leave it to end the new loop there. A lower angle takes shallower edges.
- **Step Agreement** (30°) — how closely the faces on both sides of a step must face the same way to count as its flanks. It always stays below Step Difference.
- **Step Difference** (60°) — how far a face must turn away from its flanks to count as part of a step.
- **Shoot Angle** (30°) — Destructive only: how far from square-on to its path the edge an end shoots on to may be turned. An open edge always qualifies.
