# Z-Fight Overlay

Toggles a live overlay that fills every face that will z-fight: two faces that lie in the same plane, face the same way and overlap each other, so the viewport flickers between them. It catches duplicated faces, partly overlapping faces, and faces of different objects that sit in one plane (overlapping kitbash pieces, for example). Faces that face each other, like an object standing on another, only touch and are not marked. Neither are faces that only share an edge or a corner, like a flat grid. Move a face or an object away and its highlight disappears. A **Z-Fight** count of all marked faces appears in the iOps statistics overlay (red while faces need fixing, green at zero). The overlay sticks across object and mode switches until you toggle it off. Object Mode and Edit Mesh mode.

- **Object Mode** — checks the selected mesh objects, inside each object and between them. With no mesh object selected, every visible mesh object is checked. Modifiers are applied: what is rendered is what is checked.
- **Edit Mode** — checks every object being edited, inside each object and between them. Hidden faces are ignored.

**Hotkey:** Not bound by default — assign a key in *Preferences › iOps › Keymaps*, or run it from the iOps pie / operator search. Also available: iOps Pie › Z-Fight Overlay (in both Object Mode and Edit Mode), and as a choice for the customizable slots of the iOps Edit Pie.

**Shift-click** the button (or the operator) to select the z-fighting faces instead of toggling the overlay. It works with the overlay on or off, over the same objects the overlay checks. In Edit Mode everything else is deselected and face select mode is switched on. In Object Mode the objects that own z-fighting faces become the selection and those faces are marked selected, so they are selected when you enter Edit Mode (linked and overridden meshes keep their own selection). One undo step reverts it. The selection is computed on the meshes without modifiers, while the overlay shows them with modifiers, so the two can differ when a modifier changes the faces.

## Options
- **Z-Fight Angle** (Preferences › iOps › Z-Fight Overlay) — two overlapping faces whose planes differ by less than this angle count as one plane (default 0.5°).
- **Z-Fight Distance** (Preferences › iOps › Z-Fight Overlay) — the largest gap between two parallel faces that still counts as z-fighting (default 0.0001).

## Tips
- Select a few objects to check only them: an object whose partner is not selected shows no conflict with it.
- Faces of all sizes are checked, triangles included, in world space.
- A tiny overlap along a shared edge (less than about a thousandth of the smaller face's size) is treated as touching, not z-fighting.
