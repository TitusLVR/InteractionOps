# Align Object to Face

Rotates the whole object so the active face's normal lines up with a world axis, using one of the face's edges as the "forward" direction. The object stays where it is; only the rotation changes. Cycle through the face edges, flip the normal, switch the target axis and nudge the position, then confirm. Edit Mesh mode.

**Hotkey:** <kbd>F5</kbd> in Edit Mesh with face select mode (see [Modes](op_modes.md)). Otherwise assign a key in *Preferences › iOps › Keymaps* or run it from operator search.

## Controls

| Key | Action |
| --- | --- |
| <kbd>X</kbd> / <kbd>Y</kbd> / <kbd>Z</kbd> | Align the face normal to this world axis; pressing again flips the normal |
| <kbd>Wheel Up</kbd> / <kbd>Wheel Down</kbd> | Next / previous reference edge of the face |
| <kbd>Shift</kbd>+<kbd>X</kbd> / <kbd>Y</kbd> / <kbd>Z</kbd> | Choose the axis for nudging |
| <kbd>Shift</kbd>+<kbd>Wheel</kbd> | Nudge the object by 0.5 along the chosen axis |
| <kbd>MMB</kbd> | Navigate the viewport |
| <kbd>H</kbd> | Show / hide the help legend |
| <kbd>LMB</kbd> / <kbd>Space</kbd> | Confirm |
| <kbd>Esc</kbd> / <kbd>RMB</kbd> | Cancel and restore the original rotation |

## Tips

- The current reference edge is highlighted in the viewport; the HUD shows the edge number and target axis.
- Make sure a face is active (click it last) before running.
