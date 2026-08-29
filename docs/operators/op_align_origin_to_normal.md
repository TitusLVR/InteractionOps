# Align Origin to Face Normal

Moves the object's origin to the active face and turns the object's local axes to match it: Z points along the face normal, X follows the face's longest edge. Handy when you want an object's transform to sit on a surface so later moves, scales and child objects follow that surface. Edit Mesh mode.

**Hotkey:** <kbd>Alt</kbd>+<kbd>F5</kbd> in Edit Mesh.

## Tips

- Click a face last so it becomes the active face before running.
- The 3D cursor is moved to the face as part of the operation.
- Any rotation on the object is applied into the mesh first, so running it repeatedly gives a stable result.
