# Select Boolean Operands / Targets / Mirror Objects

Three Object-mode selectors that follow modifier pointers so you can hop between a mesh and the objects wired into its stack without hunting through the outliner. All three live in *3D View › Select* (and in Hard Ops' *Select Grouped* menu when it is installed).

- **Select Boolean Operands** — selects the cutters used by the Boolean modifiers on the selected objects. Operand collections are expanded to their member objects.
- **Select Boolean Targets** — the reverse: selects every object whose Boolean modifier cuts with any of the selected objects, directly or through an operand collection.
- **Select Mirror Objects** — selects the mirror objects (usually empties) referenced by the Mirror modifiers on the selected objects.

Each one works on the whole selection (falling back to the active object), replaces the selection with the results and makes the first result active, so you can chain them: target → operands → back to targets.

**Hotkey:** Not bound by default — assign one in *Preferences › iOps › Keymaps*, or run them from the Select menu / operator search.

## Redo panel
- **Extend** — keep the current selection instead of replacing it.
- **Reveal Hidden / Reveal Disabled / Make Selectable** — results hidden with `H`, disabled in viewports (monitor icon) or locked from selection are revealed first. All on by default; untick to leave such objects alone (they are still selected where Blender allows it).
- **Add to Local View** — when the 3D View is in local view, results are added to that local view instead of staying invisible outside it. On by default.

## Tips
- Cutters parked in an excluded or hidden collection are selected but stay invisible: the operators change object flags, not collection visibility. The report in the status bar lists objects that are not in the current view layer at all.
- The Modifiers panel's **Users** button does a similar jump for any modifier type from the active modifier; these operators are the Boolean / Mirror specific, whole-selection versions.
