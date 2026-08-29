# Z Ops

A set of small Edit Mode helpers (from the Zaloopok addon) for growing, shrinking and filling edge loops and rings, connecting and evening out edges, placing one face onto another, mirroring, and a smart delete. Each one does a single, predictable thing, so they are ideal for pies and custom hotkeys.

**Hotkey:** Not bound by default — assign a key in *Preferences › iOps › Keymaps*, or run it from the iOps pie / operator search.

| Tool | What it does |
| --- | --- |
| **Grow Loop** / **Shrink Loop** | Extend the selected edges one step along their loop, or peel one edge off each end |
| **Grow Ring** / **Shrink Ring** | Same, but along the edge ring (across quads) |
| **Select Bounded Loop** / **Ring** | Fill the gap between two selected edges on the same loop or ring |
| **Connect** | Cut the selected edges in the middle and connect the new points (or use Blender's Subdivide with all its options) |
| **Equalize** | Space the vertices of a selected edge chain evenly; closed chains become circles |
| **Line Up** | Straighten a selected edge chain while keeping the original spacing ratios |
| **Put On** | With two faces selected, move the non-active face (and everything attached to it) onto the active face; an extra *Turn* angle rotates it in place |
| **Mirror** | Replace each selected face with its mirror image across its own plane, welded to the surrounding mesh |
| **Delete Selection** | Delete whatever is selected, according to the current select mode — also works on curves and armatures |

## Tips
- Equalize and Line Up need edge select mode and skip chains that branch.
- Connect without Subdivide works only in edge select mode.
