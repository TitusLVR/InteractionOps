# Three Point Rotation

![Three Point Rotation](../img/ops/op_object_three_point_rotation.png)

Aim the selected objects' axes at points in the scene, or land one of their faces onto any other face. The objects themselves are the live preview: as you move the mouse they follow, a click only locks the current pick. Nothing is added to the scene and the result is a single undo step. Object Mode; the active object drives, all selected objects move rigidly with it.

**Hotkey:** Not bound by default — assign a key in *Preferences › iOps › Keymaps*, or run it from the iOps pie / *3 Point Rotation* in the iOps panel.

## Modes

Press <kbd>Tab</kbd> to switch.

**Aim axes** (default). The pivot is the active object's origin. Move the mouse and the primary local axis (Z by default) aims at the point under the cursor; click to lock it. The mouse now rolls the secondary axis (Y by default) towards the cursor; click to lock. Two clicks for a full three-point orientation, one click plus <kbd>Space</kbd> for a two-point aim (the roll is then kept as close to the original as possible). <kbd>Shift</kbd>+<kbd>LMB</kbd> on the object picks a different pivot.

**Face to face.** Click a face on the selected object: that is the source. Now hover any face on another object and the object lands on it — the snap point under the cursor is the anchor and the nearest edge sets the roll, so you choose *what matches what* simply by where you point on the target face. Click to lock. By default the faces meet (normals oppose); <kbd>F</kbd> puts them on the same side instead, <kbd>R</kbd> turns the object 180° around the normal.

## Controls

| Key | Action |
| --- | --- |
| <kbd>LMB</kbd> | Lock the current pick (aim point or face) |
| <kbd>Shift</kbd>+<kbd>LMB</kbd> | Pick the pivot on the object (Aim; resets picked points) |
| <kbd>Tab</kbd> | Switch mode: Aim axes / Face to face |
| <kbd>X</kbd> / <kbd>Y</kbd> / <kbd>Z</kbd> | Primary axis; press again to flip its sign |
| <kbd>Shift</kbd>+<kbd>X</kbd> / <kbd>Y</kbd> / <kbd>Z</kbd> | Secondary axis; press again to flip its sign |
| <kbd>F</kbd> | Aim: swap the two locked points. Face: faces meet / same side |
| <kbd>R</kbd> | Face: reverse the roll (180° around the normal) |
| <kbd>S</kbd> | Snap to vertices / edge midpoints / face center (off = raw surface point) |
| <kbd>Backspace</kbd> | Undo the last pick |
| <kbd>0</kbd> | Reset everything |
| <kbd>H</kbd> | Show / hide the help legend |
| <kbd>Space</kbd> / <kbd>Enter</kbd> | Confirm |
| <kbd>Esc</kbd> / <kbd>RMB</kbd> | Cancel |

## Tips

- The HUD shows the current step, the axes in use and the resulting rotation angle. Collinear or coincident picks are reported as an error and leave the object where it was.
- When nothing is under the cursor in Aim mode, the aim point lies on the view-aligned plane through the pivot, so aiming into empty space still works.
- The picked lines are drawn in the color of the local axis they aim, with the axis letter at the tip.
