# Three Point Rotation

![Three Point Rotation](../img/ops/op_object_three_point_rotation.png)

Land a face of the selected objects onto any other face in the scene, or aim their axes at points. The originals stay where they are while you work; a ghost of the selection shows the result live, and one click applies it. Nothing is added to the scene and the result is a single undo step. Object Mode; the active object drives, all selected objects (and collection instances) move rigidly with it.

**Hotkey:** Not bound by default — assign a key in *Preferences › iOps › Keymaps*, or run it from the iOps pie / *3 Point Rotation* in the iOps panel.

## Modes

Press <kbd>Tab</kbd> to switch.

**Face to face** (default). Hover your own object: the face under the cursor becomes the source, with the snap point under the cursor as its anchor. It is sticky, so it stays when you move away. Now hover any face on another object and the ghost lands there, anchor onto anchor. By default the orientation is kept: a pure move, no spins, no flips, so identical modules line up as they are. Press <kbd>R</kbd> when you do want rotation: *match normals* turns the object just enough for the faces to meet, *normals + edge* also rolls it so the picked edges line up (the nearest edge to the cursor on each face, <kbd>Alt</kbd>+wheel cycles the target edge). <kbd>F</kbd> switches between faces meeting and facing the same way. <kbd>LMB</kbd> applies and finishes. One click.

**Aim axes.** The pivot is the active object's origin. Move the mouse and the primary local axis (Z by default) aims at the point under the cursor; click to lock it. The mouse now rolls the secondary axis (Y by default) towards the cursor; click to lock, <kbd>Space</kbd> to apply. One click plus <kbd>Space</kbd> gives a two-point aim (the roll is kept as close to the original as possible). <kbd>Shift</kbd>+<kbd>LMB</kbd> on the object picks a different pivot.

## Controls

| Key | Action |
| --- | --- |
| <kbd>LMB</kbd> | Face: apply on the hovered target face. Aim: lock the current point |
| <kbd>Shift</kbd>+<kbd>LMB</kbd> | Aim: pick the pivot on the object (resets picked points) |
| <kbd>Tab</kbd> | Switch mode: Face to face / Aim axes |
| <kbd>R</kbd> | Face: rotation — keep (move only) / match normals / normals + edge |
| <kbd>F</kbd> | Face: faces meet / same side (when rotating). Aim: swap the two locked points |
| <kbd>Alt</kbd>+Wheel | Face: next / previous roll edge on the target face (switches to normals + edge) |
| <kbd>X</kbd> / <kbd>Y</kbd> / <kbd>Z</kbd> | Aim: primary axis; press again to flip its sign |
| <kbd>Shift</kbd>+<kbd>X</kbd> / <kbd>Y</kbd> / <kbd>Z</kbd> | Aim: secondary axis; press again to flip its sign |
| <kbd>S</kbd> | Snap to vertices / edge midpoints / face center (off = raw surface point) |
| <kbd>Backspace</kbd> | Aim: undo the last point |
| <kbd>0</kbd> | Reset everything |
| <kbd>H</kbd> | Show / hide the help legend |
| <kbd>Space</kbd> / <kbd>Enter</kbd> | Apply |
| <kbd>Esc</kbd> / <kbd>RMB</kbd> | Cancel |

## Tips

- Snapping is screen-space: a vertex or edge midpoint is picked only when the cursor is close to it, otherwise the face center is used. Hover the middle of a face for center-to-center, a corner for vertex-to-vertex.
- The HUD shows the current step, the rotation mode and the resulting rotation angle. Collinear or coincident picks are reported as an error and leave the ghost at the original placement.
- When nothing is under the cursor in Aim mode, the aim point lies on the view-aligned plane through the pivot, so aiming into empty space still works.
- Works on collection instances (kitbash): hovering instanced geometry picks the instancing Empty.
