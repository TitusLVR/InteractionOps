# UVMaps Add / Remove

Three small tools that manage UV maps across every selected mesh at once, instead of one object at a time. Add a new UV map to all of them, remove the UV map that is active on the active object from all of them, or make the same UV slot active everywhere. Useful when prepping a batch of assets for a lightmap channel or a bake. Object Mode.

**Hotkey:** Not bound by default — assign a key in *Preferences › iOps › Keymaps*, or run it from the iOps pie / operator search. Also available: the *IOPS TPS* sidebar panel, next to the UVMaps list (+, −, and the active-layer buttons).

- **Add UVMap** — adds a new UV map (named `ch2`, `ch3`, ...) to each selected mesh. Linked duplicates get it only once.
- **Remove UVMap by Active Name** — reads the active UV map name from the active object and removes a UV map with that name from every selected mesh.
- **Set Active UVMap by Active Object** — copies the active UV slot number from the active object to the whole selection. It matches by slot position, not by name.

## Tips
- Only visible meshes with faces are touched; other objects are skipped.
- Everything is undoable with Ctrl+Z.
