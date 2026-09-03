# Mesh Snapshot

Copies the selected faces of every mesh in Edit Mode into new objects and drops them into the `iops_mesh_snapshot` collection (created under the scene root on first use, reused afterwards). The source meshes stay untouched and you remain in Edit Mode with your selection. Counterpart of MACHIN3 Smart Face in face mode.

Each snapshot is a copy of its source object with only the selected faces as data: transform, parent, material slots, UVs and attributes come along, and so does the modifier stack unless you turn it off. New objects are named `<object>_snapshot`.

**Hotkey:** Not bound by default — assign a key in *Preferences › iOps › Keymaps*, or run it from the iOps pie / operator search. Also available: iOps Pie › Mesh Snapshot.

## Options
- **Keep Modifiers** — copy the source modifier stack onto the snapshot (on by default).
