# Save/Load Space Data

Two small helpers that remember how an editor is trimmed — header shown or hidden, menus shown or hidden, and for the Outliner its display mode, column toggles and sorting — and put that look back later. The Split pie uses them automatically, so editors you close and reopen keep their settings.

**Hotkey:** Not bound by default — run *Save space_data* / *Load space_data* from operator search with the mouse over the editor.

## Tips
- Settings are stored per editor type inside the current scene, so they travel with the .blend file.
- Save overwrites the previous entry for that editor type without asking.
