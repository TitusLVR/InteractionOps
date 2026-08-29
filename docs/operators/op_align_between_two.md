# Align Between Two

Fills the gap between two objects with evenly spaced copies of the active object. Select two objects (the active one is one of the anchors), or three objects to place copies along a two-segment chain. Optionally rotate each copy so a chosen axis points along the line. Object Mode.

**Hotkey:** Not bound by default — assign a key in *Preferences › iOps › Keymaps*, or run it from the iOps pie / operator search. Also available: iOps Pie (<kbd>Ctrl</kbd>+<kbd>Alt</kbd>+<kbd>Shift</kbd>+<kbd>Q</kbd>) › Align Between Two, and as a custom slot in the Edit pie.

## Options

- **Count** — how many copies to place per segment. The endpoints stay empty.
- **Align** — rotate copies to follow the line between the anchors.
- **Track / Up** — which local axis points along the line and which points up. They must differ.
- **Select Duplicated** — select the new copies when done instead of keeping your original selection.

## Tips

- Copies land in a new collection called "Objects Between".
- Each copy gets its own mesh data; for many heavy objects consider instancing afterwards.
