# Negative Scale Overlay

Toggles a live overlay that tints every visible object with negative scale — red by default. An object is flagged when any of its scale axes is below zero, or when it inherits a mirror from a negatively scaled parent. Flip the scale back to positive (or apply it) and the tint disappears. The overlay sticks across mode switches until you toggle it off. Works in any mode.

**Hotkey:** Not bound by default — assign a key in *Preferences › iOps › Keymaps*, or run it from operator search. Can also be put on an iOps Edit Pie diagonal slot.

## Options
- **Highlight Color** (Preferences › iOps › Negative Scale Overlay) — fill colour and opacity of the tint (default red, 35%).

## Tips
- Meshes, curves, surfaces, text and metaballs are tinted with their evaluated shape, modifiers included. Empties, lights and other non-geometry objects are not drawn.
- Collection instances are covered: a negatively scaled instancer tints everything it instances, and a negative object inside an instanced collection is tinted wherever the collection is instanced, nested instances included.
- Hidden objects and objects outside local view are skipped.
