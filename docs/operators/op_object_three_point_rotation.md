# Three Point Rotation

![Three Point Rotation](../img/ops/op_object_three_point_rotation.png)

Place the selected objects by point pairs, one click per step: move a point onto a point, then optionally align a second pair and roll a third. The originals stay where they are while you work; a ghost of the selection shows each step live, and the click commits it. Nothing is added to the scene and the result is a single undo step. Object Mode; the active object drives, all selected objects (and collection instances) move rigidly with it.

**Hotkey:** Not bound by default — assign a key in *Preferences › iOps › Keymaps*, or run it from the iOps pie / *3 Point Rotation* in the iOps panel.

## Steps

Each step is the same gesture: hover your own object to pick a point, click to lock it (or just move away, the pick is sticky), hover the target to pick where it goes, click. From the second step on you pick your points on the ghost, where the object is going to be.

1. **Move.** Point A on your object, point A′ on the target. The ghost moves so A sits on A′. No rotation, no flips: identical modules line up as they are. <kbd>Space</kbd> here finishes with a pure move.
2. **Align.** Point B on your object (you pick it on the ghost), point B′ on the target. The ghost turns about A′ until the ray A′→B lies on A′→B′. Instead of a point pair, <kbd>R</kbd> switches to turning by the face normals of A and A′ (*by normals*: the minimal turn, faces meet; *normals + edge*: also rolls so the picked edges line up, <kbd>Alt</kbd>+wheel cycles the target edge). <kbd>F</kbd> flips between faces meeting and facing the same way.
3. **Roll.** Point C on your object, C′ on the target. The ghost turns about the axis A′→B′ until C lies in the plane of A′, B′, C′. The click finishes.

<kbd>Backspace</kbd> steps back, <kbd>Space</kbd> / <kbd>Enter</kbd> applies what is committed (plus the pending step, if any), <kbd>Esc</kbd> cancels.

## Controls

| Key | Action |
| --- | --- |
| <kbd>LMB</kbd> | On your object: lock the point. On the target: commit the step (Move A→A′, Align B→B′, Roll C→C′) |
| <kbd>R</kbd> | Align by: points / normals / normals + edge |
| <kbd>F</kbd> | Facing: faces meet / same side (normals modes) |
| <kbd>Alt</kbd>+Wheel | Roll edge: next / previous on the target face (normals + edge) |
| <kbd>S</kbd> | Snap to vertices / edge midpoints / face center (off = raw surface point) |
| <kbd>Backspace</kbd> | Step back |
| <kbd>0</kbd> | Reset everything |
| <kbd>H</kbd> | Show / hide the help legend |
| <kbd>Space</kbd> / <kbd>Enter</kbd> | Apply |
| <kbd>Esc</kbd> / <kbd>RMB</kbd> | Cancel |

## Tips

- Snapping is screen-space: a vertex, edge midpoint or face center is picked when the cursor is within a few dozen pixels of it, otherwise the face center is used. Once a point is picked on a face, sliding across that face or off the object keeps it.
- The HUD shows the step, what to hover next, the align mode and the total rotation angle. A degenerate pick (a point on the pivot or on the roll axis) is reported as an error and leaves the ghost where it was.
- Works on collection instances (kitbash): hovering instanced geometry picks the instancing Empty.
