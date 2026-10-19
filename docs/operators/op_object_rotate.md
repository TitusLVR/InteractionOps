# Object Rotate (Arrow Keys)

Rotates every selected object by a fixed step (90° by default) around an X, Y or Z axis — each object spins in place around its own origin, not around a shared pivot. Arrow keys go one way, <kbd>Shift</kbd>+arrow the other. Object Mode; can drive the 3D cursor instead of the selection.

**Hotkey:** <kbd>Left</kbd> / <kbd>Shift</kbd>+<kbd>Left</kbd> — ±X; <kbd>Down</kbd> / <kbd>Shift</kbd>+<kbd>Down</kbd> — ±Y; <kbd>Right</kbd> / <kbd>Shift</kbd>+<kbd>Right</kbd> — ±Z.

## Options

All options except *Per Object* are shared by the six directions and remembered for the next press.

- **Space** — which axes the step is taken around: *Local* (the object's own axes), *Global* (world), *Cursor* (the 3D cursor's axes) or *View* (the viewport's axes). The pivot is always the object's own origin.
- **Angle** — the step in degrees.
- **Per Object** — rotate each selected object (on) or only the active object (off).
- **Skip Children** — leave out objects whose parent is also selected, so they are not rotated twice. On by default.
- **Snap** — before stepping, round the object's current rotation to the nearest multiple of the angle. Handy to clean up a hand-rotated object: one press and it sits on the grid of angles.
- **Respect Locks** — skip objects with a rotation lock on the axis being rotated (in *Local* space) or with any rotation lock (other spaces). On by default.
- **Cursor Only** — leave the objects alone and turn the 3D cursor itself by the same step in the chosen space (*Local* and *Cursor* both mean the cursor's own axes). Works with nothing selected.

## Tips

- The rotation is written straight into the object's transform, so parenting, rotation mode and the Transform Options panel do not get in the way; the 3D cursor is never moved as a side effect.
- Set the angle to 45 or 15 in the redo panel for finer steps.
- *Cursor Only* is the quick way to set up a cursor-based pivot or transform orientation without leaving the viewport.
