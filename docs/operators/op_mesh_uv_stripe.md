# UV Stripe

Unwraps each selected strip of faces as one straight, even UV rectangle: the two long boundaries become straight rows, the faces between them keep their proportions in world units, and every face is oriented the same way. No UV editor and no seams are needed. Edit Mesh mode.

**Hotkey:** Not bound by default — assign a key in *Preferences › iOps › Keymaps*, or run it from the operator search.

## What counts as a strip
Each edge-connected group of selected faces is unwrapped on its own:
- **Open chain** — faces in a row, one face wide; it may bend. Quad or triangle ends.
- **Closed ring** — a loop of faces, such as a band round a cylinder; it is cut open at one rung.
- **Quad grid** — a patch several faces wide with four corners; the two longer sides become the rows.

A group that branches, touches itself at a vertex, has a hole, or is a single triangle is skipped with a warning; the other groups are still unwrapped.

## Direction
The result does not depend on how the mesh was built: an open strip runs from its end with the smaller coordinate on its main world axis (U = 0) toward the other end. A ring's lower boundary along its main axis lies on V = 0; for a flat ring it is the outer boundary.

## Options
- **Mode** — *Fit 0–1* stretches each strip across U 0–1 with V in proportion and stacks several strips upward. *In Place* keeps each strip where its old UVs were, at the texel density of the neighbouring faces.

## Tips
- Seams, pinned UVs and the selection are left as they are.
- A mesh without a UV map gets one.
