# Hidden Faces Overlay

Toggles a live overlay that fills every face that cannot be seen from outside the model: faces inside a closed shell, faces buried in other geometry (a part pushed into another, a leftover cap inside a tube), back walls nobody can look at. They cost polygons and texture space and are never seen. A **Hidden** count of all marked faces appears in the iOps statistics overlay (red while faces need fixing, green at zero). The overlay sticks across object and mode switches until you toggle it off. Object Mode and Edit Mesh mode.

- **Object Mode** — checks the selected mesh objects together; with no mesh object selected, every visible mesh object. Modifiers are applied: what is rendered is what is checked.
- **Edit Mode** — checks every object being edited, together. Hidden (H) faces are not marked but still block the view.

A face counts as hidden when, from its front side (the side its normal points to), no straight line reaches the outside. From several points on the face (the center and near each corner of every triangle of it) rays go out over the whole half-space in front of it, grazing directions included; any geometry of the checked objects stops a ray, front or back side. One ray that gets out makes the face visible, so only fully hidden faces are marked; a face that is half buried is not. Most faces are cleared by their first ray; only faces that look into a pocket or a crevice get the full ray budget, and those take most of the time.

**Shift-click** the button (or the operator) to select the hidden faces instead of toggling the overlay. It works with the overlay on or off, over the same objects the overlay checks. In Edit Mode everything else is deselected and face select mode is switched on. In Object Mode the objects that own hidden faces become the selection and those faces are marked selected, so they are selected when you enter Edit Mode (linked and overridden meshes keep their own selection). One undo step reverts it. The selection is computed on the meshes without modifiers, while the overlay shows them with modifiers, so the two can differ when a modifier changes the faces.

**Hotkey:** Not bound by default — assign a key in *Preferences › iOps › Keymaps*, or run it from the iOps pie / operator search. Also available: iOps Pie › Hidden Faces Overlay (in both Object Mode and Edit Mode, with its **Rays** field next to the button), and as a choice for the customizable slots of the iOps Edit Pie.

## Options
- **Rays** (Preferences › iOps › Hidden Faces Overlay, and next to the button in the iOps Pie) — rays cast from each sample point of a face before it is declared hidden (default 128). A quad has eight sample points, each looking along its own directions, so the default tests a quad along about 1,000 directions. More rays find narrower openings; fewer rays are faster. Changing it updates the overlay right away.

## Known consequences
- The walls of a fully closed interior (a sealed room, the inside of a closed box with an inner surface) are hidden: no line from them reaches the outside.
- Rays are samples: a face visible only through a very thin gap or from a very narrow range of directions can be marked hidden. Raise **Rays** if a face you can see is marked.
- To keep faces buried in other objects fast, a point that a couple of rays find inside a closed solid (they cross more back sides of faces than front sides on the way out) counts as hidden without further rays. Inside a mesh that is not closed or has flipped normals, a face seen only through a hole can be marked hidden.

## Tips
- Select the objects to check: an object that is not selected does not block the view of the selected ones.
- The overlay recalculates when geometry changes; on dense scenes with many faces in pockets, lower **Rays** or check a selection instead of the whole scene.
