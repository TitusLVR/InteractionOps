# Bevel Edge Data Fix

Restores seams, sharp edges, creases and bevel weights that a Bevel modifier destroys, by projecting them back onto the centre loop of each bevel strip. The tool builds a hidden pre-bevel copy, inserts the fix right after the Bevel, and lets you keep it live (procedural) or collapse it into the mesh. Requires a Bevel with an even segment count and profile 1.0. Object mode, active mesh with a Bevel modifier.

**Hotkey:** Not bound by default — assign a key in *Preferences › iOps › Keymaps*, or run it from the iOps pie / operator search.

## Controls
| Key | Action |
| --- | --- |
| <kbd>Enter</kbd> / <kbd>Space</kbd> | Keep the live fix in the modifier stack |
| <kbd>C</kbd> | Collapse: apply the stack, re-unwrap the bevel strips, remove the helper |
| <kbd>U</kbd> | Also project UVs from the pre-bevel layout (toggle) |
| <kbd>H</kbd> | Show / hide the help legend |
| <kbd>Esc</kbd> | Revert everything |

## Options
- **Collapse** — apply the stack through the fix and remove the helper.
- **Unwrap (project UVs)** — rebuild the UV map pinned to the pre-bevel layout.
- **Pin & Unwrap after collapse** — after collapsing, re-unwrap only the bevel strips with everything else pinned.

## Pin & Unwrap Bevel

Duplicates and applies the bevel stack, then unwraps only the bevel strips while every other UV stays pinned — your existing atlas layout is untouched. Run it on an object that already carries the live fix from above.

**Hotkey:** Not bound by default — assign a key in *Preferences › iOps › Keymaps*, or run it from the iOps pie / operator search.

- **Tolerance** — how close a vertex must be to an original beveled edge to count as strip geometry.
- **Unwrap Margin** — island margin for the strip unwrap.
