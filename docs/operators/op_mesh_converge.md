# Converge

Finds pairs of selected edges that cross or lie in one plane and welds their nearest ends together at the point where they would meet — closing gaps between edges that should share a corner. Preview the result, cycle the pairing strategy, add more edges with Shift+click, then confirm. Edit Mesh mode.

**Hotkey:** Not bound by default — assign a key in *Preferences › iOps › Keymaps*, or run it from the iOps pie / operator search. Also available: iOps Pie › Converge.

## Controls
| Key | Action |
| --- | --- |
| <kbd>Wheel</kbd> / <kbd>S</kbd> | Cycle strategy |
| <kbd>Shift</kbd>+<kbd>LMB</kbd> | Add the edge under the cursor to the selection |
| <kbd>MMB</kbd> | Navigate the viewport |
| <kbd>H</kbd> | Show / hide the help legend |
| <kbd>LMB</kbd> / <kbd>Enter</kbd> / <kbd>Space</kbd> | Confirm |
| <kbd>Esc</kbd> / <kbd>RMB</kbd> | Cancel |

## Options
- **Strategy** — *Greedy*: nearest pairs first, each edge used once. *All*: collapse every selected edge into the meeting point of the two outer rails. *Order*: pair edges by selection order (1st+2nd, 3rd+4th…).
- **Interactive** — show the preview before applying; turn off to apply immediately.
