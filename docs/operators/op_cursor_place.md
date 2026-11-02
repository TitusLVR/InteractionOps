# Cursor Place

![Cursor Place](../img/ops/op_cursor_place.png)

Hold <kbd>Shift</kbd> + <kbd>RMB</kbd> and the 3D Cursor follows the surface under the mouse, oriented to it: one cursor axis follows the face normal, another follows the nearest edge. By default the cursor **slides** along the face, or along an edge when the mouse is close to one. Hold <kbd>Ctrl</kbd> and it **snaps** to the nearest **vertex**, **edge midpoint** or **face centre**, like Blender's own snapping. Release <kbd>RMB</kbd> to place the cursor. Works on the evaluated surface, so modifiers and collection instances count. Available in Object Mode and Mesh Edit Mode.

**Hotkey:** <kbd>Shift</kbd> + <kbd>RMB</kbd> (hold). This replaces Blender's own Shift+RMB cursor placement while the addon is enabled; rebind it in *Preferences › iOps › Keymaps* (`iops.cursor_place`).

## Controls
| Key | Action |
| --- | --- |
| <kbd>Shift</kbd> + <kbd>RMB</kbd> (hold + move) | Slide: the cursor follows the mouse on the face, or along the nearest edge within the snap threshold; the element is highlighted in the theme Closest colour, the landing point is the Result Preview point and the cursor axes use the axis colours (width from Theme › Axis gizmo) |
| <kbd>Ctrl</kbd> (hold) | Snap: nearest vertex, edge midpoint or face centre of the polygon under the mouse; every candidate is drawn as a theme point, the chosen one in the Result Preview colour, the element itself in Closest |
| <kbd>Shift</kbd> (press again) | Aim, toggle: the position stays put, the edge axis points at the point under the mouse (the snapped element with Ctrl, highlighted), or at the mouse itself over empty space |
| <kbd>Alt</kbd> (hold) | Move with the orientation frozen at the moment Alt went down |
| <kbd>A</kbd> (Ctrl held) | Multi-point snap, like Blender's: mark the snapped point under the mouse; the cursor lands on the centre of all marked points. <kbd>A</kbd> on a point already marked unmarks it. Marked points are drawn in the Locked colour, each tied to the landing point, the snapped point under the mouse in Active as the next candidate; they stay for the whole drag and count only while <kbd>Ctrl</kbd> is held |
| <kbd>A</kbd> (no Ctrl) | Toggle: pick only on the active object, the ray passes through everything else |
| <kbd>T</kbd> | Toggle (on by default): ignore triangulation, so a triangulated n-gon is picked whole. The source polygon is read from the original mesh by vertex index, no modifier is touched and nothing re-evaluates; when the modifier stack changed the vertex count (Bevel, Mirror, Subdivision) the evaluated polygon is used as is |
| <kbd>X</kbd> / <kbd>Y</kbd> / <kbd>Z</kbd> | Which cursor axis follows the surface normal (if it collides with the edge axis, the two swap) |
| <kbd>F</kbd> | Flip the normal axis |
| Wheel | Switch the edge axis to the other free letter |
| Release <kbd>RMB</kbd> | Place the cursor (releasing over another editor keeps the last preview) |
| <kbd>Esc</kbd> | Cancel, cursor untouched |
| <kbd>H</kbd> | Show / hide the help legend |

## Tips
- Centre between two vertices or faces: hold Ctrl, hover the first, press A, hover the second, press A, release. With points marked the cursor no longer follows the snap under the mouse: it sits on their centre, oriented to the surface under the mouse (or the last one over empty space).
- Snap (Ctrl) is nearest-wins: hover a corner for the vertex, the middle of an edge for its midpoint, the middle of a face for its centre. The orientation always comes from the face under the mouse, also on a vertex, so a cube corner aligns to the face you point at rather than to the averaged vertex normal.
- Slide uses the *Snap Threshold* from the Cursor Bisect preferences to decide when the mouse is "on" an edge. Letting go of the Shift that started the drag changes nothing: the cursor stays under the mouse.
- The edge axis points toward the edge endpoint nearest the mouse, so you can flip its direction by hovering the other half of the edge.
- Over empty space the release behaves like Blender's cursor placement: the cursor moves to the mouse on the view plane and keeps its rotation. On curves, text and other non-mesh surfaces the cursor lands on the hit point, aligned to the hit normal.
- Only what you can see counts: hidden objects (H, the monitor icon, collection eye / exclude, local view, object-type visibility) and objects displayed as Wire or Bounds are passed through by the ray.
- Right-click-select keymaps keep their Shift+RMB extend-select: the operator passes the click through. Bind it to another key in that case.
- Defaults for the two axes (normal Z, edge Y), the preview size and the axis letters live in *Preferences › iOps › Cursor Place*. Key presses during the drag override them for that placement only.
- The next pivot tool (Object Rotate, Mirror Rotate, Cursor Bisect, Three Point Rotation) now starts from a cursor that is already aligned to the surface.
