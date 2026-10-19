# Object Rotate (Arrow Keys)

Rotates every selected object by a fixed step (90° by default) around its own local X, Y or Z axis — each object spins in place around its own origin, not around a shared pivot. Arrow keys go one way, <kbd>Shift</kbd>+arrow the other. Object Mode.

**Hotkey:** <kbd>Left</kbd> / <kbd>Shift</kbd>+<kbd>Left</kbd> — ±X; <kbd>Down</kbd> / <kbd>Shift</kbd>+<kbd>Down</kbd> — ±Y; <kbd>Right</kbd> / <kbd>Shift</kbd>+<kbd>Right</kbd> — ±Z.

## Options

- **Rotation Angle** — the step in degrees; shared by all six directions and remembered for the next press.
- **Per Object** — rotate each selected object around its own origin (on) or only the active object (off).
- **Cursor Only** — leave the objects alone and turn the 3D cursor itself around its own local axis by the same step. Works with nothing selected; remembered for the next press like the angle.

## Tips

- The rotation is applied straight to the object's own transform, so parenting, rotation mode and the Transform Options panel do not get in the way; the 3D cursor is never moved.
- Set the angle to 45 or 15 in the redo panel for finer steps.
- *Cursor Only* is the quick way to set up a cursor-based pivot or transform orientation without leaving the viewport.
