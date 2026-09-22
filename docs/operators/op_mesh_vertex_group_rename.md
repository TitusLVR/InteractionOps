# Rename Active Group

Renames the active vertex group from a small popup, so you don't have to leave the viewport for the Properties editor. It is added to the bottom of Blender's own **Vertex Groups** menu (`Ctrl+G` in Edit Mode), next to *Set Active Group* and *Remove Active Group*.

**Hotkey:** `Ctrl+G` › *Rename Active Group* (Edit Mode). Also available from operator search as *Rename Active Group*.

## Options

- **Name** — the new name. The field starts with the current name of the active group, already focused, so you can type straight away and press `Enter`.

## Tips

- If another group already has that name, Blender adds a numeric suffix (e.g. `Group.001`) and the status bar tells you the name that was actually applied.
- An empty name is rejected and the group is left unchanged.
- The rename is undoable with `Ctrl+Z`.
