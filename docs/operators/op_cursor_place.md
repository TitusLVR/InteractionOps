# Cursor Place

![Cursor Place](../img/ops/op_cursor_place.png)

Hold <kbd>Shift</kbd> + <kbd>RMB</kbd> and the 3D Cursor follows the surface under the mouse, oriented to it: one cursor axis follows the face normal, another follows the nearest edge. While <kbd>Shift</kbd> stays down the cursor **slides** along the face, or along an edge when the mouse is close to one. Let go of <kbd>Shift</kbd> (keeping <kbd>RMB</kbd> down) and it **snaps** to the nearest **vertex**, **edge midpoint** or **face centre** instead. Release <kbd>RMB</kbd> to place the cursor. Works on the evaluated surface, so modifiers and collection instances count. Available in Object Mode and Mesh Edit Mode.

**Hotkey:** <kbd>Shift</kbd> + <kbd>RMB</kbd> (hold). This replaces Blender's own Shift+RMB cursor placement while the addon is enabled; rebind it in *Preferences › iOps › Keymaps* (`iops.cursor_place`).

## Controls
| Key | Action |
| --- | --- |
| <kbd>Shift</kbd> + <kbd>RMB</kbd> (hold + move) | Slide: the cursor follows the mouse on the face, or along the nearest edge within the snap threshold; the element and the cursor axes are previewed in the theme / axis colours |
| <kbd>RMB</kbd> held, <kbd>Shift</kbd> up | Snap: nearest vertex, edge midpoint or face centre of the polygon under the mouse |
| <kbd>Ctrl</kbd> (hold) | Aim: the position stays put, the edge axis points at the nearest vertex / edge midpoint / face centre under the mouse (highlighted), or at the mouse itself over empty space |
| <kbd>Alt</kbd> (hold) | Move with the orientation frozen at the moment Alt went down |
| <kbd>X</kbd> / <kbd>Y</kbd> / <kbd>Z</kbd> | Which cursor axis follows the surface normal (if it collides with the edge axis, the two swap) |
| <kbd>F</kbd> | Flip the normal axis |
| Wheel | Switch the edge axis to the other free letter |
| Release <kbd>RMB</kbd> | Place the cursor (releasing over another editor keeps the last preview) |
| <kbd>Esc</kbd> | Cancel, cursor untouched |
| <kbd>H</kbd> (Shift up) | Show / hide the help legend |

## Tips
- Snap mode is nearest-wins: hover a corner for the vertex, the middle of an edge for its midpoint, the middle of a face for its centre. The orientation always comes from the face under the mouse, also on a vertex, so a cube corner aligns to the face you point at rather than to the averaged vertex normal.
- Slide mode uses the *Snap Threshold* from the Cursor Bisect preferences to decide when the mouse is "on" an edge.
- The edge axis points toward the edge endpoint nearest the mouse, so you can flip its direction by hovering the other half of the edge.
- Over empty space the release behaves like Blender's cursor placement: the cursor moves to the mouse on the view plane and keeps its rotation. On curves, text and other non-mesh surfaces the cursor lands on the hit point, aligned to the hit normal.
- Right-click-select keymaps keep their Shift+RMB extend-select: the operator passes the click through. Bind it to another key in that case.
- Defaults for the two axes (normal Z, edge Y), the preview size and the axis letters live in *Preferences › iOps › Cursor Place*. Key presses during the drag override them for that placement only.
- The next pivot tool (Object Rotate, Mirror Rotate, Cursor Bisect, Three Point Rotation) now starts from a cursor that is already aligned to the surface.
