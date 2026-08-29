# Vert Fuse

Closes T-junctions: for each selected vertex lying on or near another edge, splits that edge at the vertex and welds them together. Pick vertices by clicking, or press A to auto-detect all candidates within the tolerance. Preview first, then confirm. Edit Mesh mode.

**Hotkey:** Not bound by default — assign a key in *Preferences › iOps › Keymaps*, or run it from the iOps pie / operator search. Also available: iOps Pie › Vert Fuse.

## Controls
| Key | Action |
| --- | --- |
| <kbd>LMB</kbd> | Add the vertex under the cursor |
| <kbd>Ctrl</kbd>+<kbd>LMB</kbd> | Remove a vertex |
| <kbd>A</kbd> | Auto-detect all fusable vertices |
| <kbd>Wheel</kbd> / <kbd>S</kbd> | Cycle merge position |
| <kbd>Ctrl</kbd>+<kbd>Wheel</kbd> | Tolerance |
| <kbd>MMB</kbd> | Navigate the viewport |
| <kbd>H</kbd> | Show / hide the help legend |
| <kbd>Enter</kbd> / <kbd>Space</kbd> | Confirm |
| <kbd>Esc</kbd> / <kbd>RMB</kbd> | Cancel |

## Options
- **Merge Position** — *Project*: on the edge, which stays straight. *Vert*: at the vertex, bending the edge to it. *Mid*: halfway.
- **Tolerance** — maximum gap between a vertex and the edge it fuses into.
- **Interactive** — show the preview before applying.
- **Cross Island** — let auto-detect fuse vertices into edges of a different mesh island (manual picks always can).
