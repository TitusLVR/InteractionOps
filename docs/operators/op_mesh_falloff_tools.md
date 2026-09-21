# Falloff Move / Rotate / Scale

Modo-style soft transforms: every vertex of the selection moves, rotates or scales by a weight from a falloff you can see and edit in the viewport. Three operators share one interaction: `iops.mesh_falloff_move`, `iops.mesh_falloff_rotate`, `iops.mesh_falloff_scale`. Edit Mesh mode.

**Hotkey:** Not bound by default — assign keys in *Preferences › iOps › Keymaps* (bucket *Other*), or run them from operator search.

## Falloffs
| Key | Falloff | Weight |
| --- | --- | --- |
| <kbd>L</kbd> | Linear | 1 at the Start handle, 0 at the End handle |
| <kbd>R</kbd> | Radial | 1 at the centre, 0 at the ring |
| <kbd>S</kbd> | Screen | 1 under the mouse, 0 at the pixel radius (Soft Drag). The disc follows the mouse, pins to the press point for the drag, and commits on release |
| <kbd>C</kbd> | Coplanar | 1 on faces parallel to the selection, 0 past the angle; grows outside the selection. Needs a face or edge selection |
| <kbd>E</kbd> | Element toggle | Only geometry connected to the selection is affected |

## Controls
| Key | Action |
| --- | --- |
| <kbd>LMB</kbd> drag | Transform. After release the drag stays live: changing falloff type, shape, size, invert or Element re-applies it. The next drag or Enter commits it |
| <kbd>LMB</kbd> on a handle | Move the falloff centre / ends / radius ring |
| <kbd>LMB</kbd> on a gizmo arrow / ring / square | Start the transform constrained to that basis axis (the gizmo shows arrows for Move, rings for Rotate, squares for Scale). The constraint stays set until you change it |
| <kbd>LMB</kbd> on the origin gizmo | Drag the pivot (origin of rotation/scale and of the axis tripod). Ctrl snaps it to the original selection, X/Y/Z lock it; N resets it to the basis |
| <kbd>Ctrl</kbd> while dragging a handle | Snap the handle to a vertex of the original selection (drawn as a ghost while the mesh is displaced); the ring snaps its radius to that vertex |
| <kbd>X</kbd> / <kbd>Y</kbd> / <kbd>Z</kbd> while dragging a handle | Lock the handle to that axis; <kbd>Shift</kbd>+axis locks it to the plane of the other two (press again to unlock); combines with Ctrl |
| <kbd>F</kbd> | Cycle shape: Linear, Smooth, Sharp, Root, Sphere, Inverse Square, Constant |
| <kbd>I</kbd> | Invert weights |
| <kbd>A</kbd> | Auto-size the falloff to the selection |
| <kbd>N</kbd> | Cycle the basis (pivot + axes): Local = selection centre / object axes, Cursor = 3D cursor, World = origin / world axes, Normal = active element centre with Z along its normal. Axis constraints, per-axis scale and handle locks follow it |
| <kbd>V</kbd> | Show weights (yellow = full, purple = faint; unaffected verts are not drawn) |
| <kbd>X</kbd> / <kbd>Y</kbd> / <kbd>Z</kbd> | Constrain move/scale to that axis, or set the rotation axis (view axis by default). <kbd>Shift</kbd>+axis constrains to the plane of the other two (rotation then turns about the excluded axis) |
| <kbd>Shift</kbd>+<kbd>Wheel</kbd> | Falloff size (radius / length / pixels / angle); add <kbd>Ctrl</kbd> for fine steps |
| <kbd>Shift</kbd> / <kbd>Ctrl</kbd> while dragging | Precise / snap |
| <kbd>0</kbd>–<kbd>9</kbd>, <kbd>.</kbd>, <kbd>-</kbd>, <kbd>Backspace</kbd> | Type an amount (units along the axis constraint or object X, degrees, or factor). It applies live as you type and replaces the mouse value; <kbd>Enter</kbd> confirms |
| <kbd>MMB</kbd> / <kbd>Wheel</kbd> | Navigate |
| <kbd>H</kbd> | Help legend |
| <kbd>/</kbd> | Toggle HUD parameter rows |
| <kbd>Enter</kbd> / <kbd>Space</kbd> | Confirm (one undo step) |
| <kbd>Esc</kbd> / <kbd>RMB</kbd> | Cancel every drag of this session |

## Tips
- Nothing selected = the whole mesh is affected.
- Last-used type, shape, invert, element, preview, pixel radius and coplanar angle persist per scene.
- Coplanar with Element on behaves like a region grow that stops at hard edges.
