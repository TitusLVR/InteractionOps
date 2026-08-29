# Change Scale

Sets the object's scale to any value you type while keeping the object looking exactly the same — the mesh is adjusted to compensate. It is the reverse of Apply Scale: use it when an exporter or pipeline expects a specific scale value (e.g. 100, 100, 100) on the transform. Object Mode.

**Hotkey:** Not bound by default — assign a key in *Preferences › iOps › Keymaps*, or run it from the iOps pie / operator search.

## Options

- **Scale** — the X/Y/Z scale to end up with. The dialog starts at the active object's current scale.

## Tips

- Only mesh objects are affected; other object types in the selection are skipped.
- Objects sharing the same mesh data are all changed, since the mesh itself is rescaled.
