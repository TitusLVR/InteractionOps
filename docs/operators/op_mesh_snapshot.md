# Mesh Snapshot

Copies the selected faces of every mesh in Edit Mode into new objects and drops them into the `iops_mesh_snapshot` collection (created under the scene root on first use, reused afterwards). The source meshes stay untouched and you remain in Edit Mode with your selection. Counterpart of MACHIN3 Smart Face in face mode.

Each snapshot is a copy of its source object with only the selected faces as data: transform, parent, material slots, UVs and attributes come along, and so does the modifier stack unless you turn it off. New objects are named `<object>_snapshot`.

**Hotkey:** Not bound by default — assign a key in *Preferences › iOps › Keymaps*, or run it from the iOps pie / operator search. Also available: iOps Pie › Mesh Snapshot.

## Options
- **Evaluated** — snapshot what the viewport shows instead of the cage: the selected faces are tagged, the full modifier stack is evaluated and only the output faces that inherit the tag are kept (bevel, subdivision, mirror and the like propagate it). The snapshot carries no modifiers — they are baked in. Off by default.
- **Keep Modifiers** — copy the source modifier stack onto the snapshot (on by default; ignored when *Evaluated* is on).
- **Copy Modifier Targets** — with modifiers kept, also clone the objects they point at (mirror / array / boolean / hook / shrinkwrap targets, UV Project projectors, Object inputs of Geometry Nodes modifiers), re-point the snapshot's modifiers to the clones and link the clones into the collection next to the snapshot. Clones get their own data and no animation; their own modifier targets are cloned recursively, and a target shared by several snapshots of one run is cloned once. On by default.
