# Visual UV

![Visual UV](../img/ops/op_mesh_visual_uv.png)

Edit UV islands directly on the model in the 3D Viewport. The session starts with the islands on the selected faces; click any other visible island to work on it instead, or Shift-click to add or remove islands, just like face selection. Selected islands are colour-coded and the active one shows a bounding box with handles, a pivot and a rotation knob; grab, rotate, scale, flip, align, randomise or unwrap them without opening the UV Editor. Edit Mesh mode with faces selected.

The same tool also runs in the UV Editor (see [In the UV Editor](#in-the-uv-editor)).

**Hotkey:** <kbd>Ctrl</kbd>+<kbd>Alt</kbd>+<kbd>U</kbd> (Edit Mesh, and the UV Editor). Also available: iOps Edit Pie › Visual UV; UV Editor sidebar › iOps › IOPS UV Tools › Visual UV.

## Controls
| Key | Action |
| --- | --- |
| <kbd>LMB</kbd> on an island | Select only that island and make it active (any visible island of the mesh, selected or not) |
| <kbd>Shift</kbd>+<kbd>LMB</kbd> on an island | Add it to the selection and make it active, or remove it when it is already selected |
| <kbd>LMB</kbd> / <kbd>Shift</kbd>+<kbd>LMB</kbd> on an edge of a selected island | Select the edge / add it to the edge selection; the island selection stays as it is |
| <kbd>Z</kbd> | Deselect all islands (the tool keeps running) |
| <kbd>LMB</kbd> click on a gizmo point | Make that point the pivot: any of the four corners, the four side midpoints or the centre. The picked point is marked with the pivot marker; R and S (keys and the rotation knob) then turn and scale around it. Clicking the centre point goes back to the Center pivot |
| <kbd>LMB</kbd> drag on a handle / knob | Scale from the opposite handle / move (centre point) / rotate (knob). A press becomes a drag once the mouse moves past Blender's drag threshold; released before that it is a click that picks the pivot |
| <kbd>W</kbd> | Cycle the active island |
| <kbd>Tab</kbd> | Show / hide More Options in the HUD |
| <kbd>G</kbd> / <kbd>R</kbd> / <kbd>S</kbd> | Grab / Rotate / Scale around the pivot (hover a handle to use it as the pivot for that one transform) |
| <kbd>X</kbd> / <kbd>Y</kbd> | Lock an axis while transforming |
| <kbd>Shift</kbd> | Constrain to the dominant axis (grab) / uniform scale |
| <kbd>Ctrl</kbd> | Snap: 1/16 UV steps, rotation step, 0.05 scale |
| <kbd>Ctrl</kbd>+<kbd>Wheel</kbd> | Change the rotation snap step (1…90°) |
| <kbd>Alt</kbd>+<kbd>Wheel</kbd> | Mouse sensitivity |
| <kbd>C</kbd> | Snap the UV cursor to the active island's nearest bounding-box anchor (corner, side midpoint or centre) and pivot on it |
| <kbd>P</kbd> | Cycle the pivot: Center → Cursor → the picked gizmo point (once one was picked) |
| <kbd>A</kbd> | Align selected islands to the active one's hovered handle, or pick an edge to align to |
| <kbd>I</kbd> | Transform scope: All islands ↔ Active only (affects G / R / S / F / N) |
| <kbd>F</kbd> / <kbd>Shift</kbd>+<kbd>F</kbd> | Flip horizontal / vertical |
| <kbd>D</kbd> / <kbd>Shift</kbd>+<kbd>D</kbd> / <kbd>Ctrl</kbd>+<kbd>D</kbd> | Fit selected islands onto the active one: islands transposed against it (landscape vs portrait) are turned 90° first, then their bounding box is scaled to the active island's box (both axes / width only / height only) and centred on it |
| <kbd>N</kbd> / <kbd>Shift</kbd>+<kbd>N</kbd> / <kbd>Ctrl</kbd>+<kbd>N</kbd> | Randomise offset: both axes / U only / V only, anywhere within the Randomize Range set in the add-on preferences (2 tiles from the UV origin by default) |
| <kbd>U</kbd> / <kbd>Ctrl</kbd>+<kbd>U</kbd> | Unwrap the active island / all selected islands |
| <kbd>Shift</kbd>+<kbd>U</kbd> / <kbd>Shift</kbd>+<kbd>M</kbd> | Cycle the unwrap method / toggle Keep Mirror |
| <kbd>T</kbd> | Straighten the UV edge chain under the cursor |
| <kbd>E</kbd> | Stitch: click a source edge, then move the mouse; the island is scaled, rotated and moved live onto the nearest edge of any other UV island (selected or not). <kbd>LMB</kbd> confirms, <kbd>RMB</kbd> cancels, hold <kbd>Shift</kbd> to land on the same side (overlap) |
| <kbd>Q</kbd> | Clean view: hide overlays |
| <kbd>Ctrl</kbd>+<kbd>Z</kbd> / <kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>Z</kbd> | Undo / redo inside the session |
| <kbd>RMB</kbd> | Cancel the current transform |
| <kbd>MMB</kbd> / <kbd>Wheel</kbd> | Navigate the viewport |
| <kbd>H</kbd> | Show / hide the help legend (every key of the tool, collapsed at the start) |
| <kbd>Enter</kbd> / <kbd>Space</kbd> | Confirm |
| <kbd>Esc</kbd> | Cancel and restore the original UVs and face selection |

## In the UV Editor
Start the tool in a UV Editor (an Image Editor showing the UVs of a mesh in Edit Mode) and the same gizmo works on the UV layout itself: the session starts with the selected UV islands (UV Sync Selection honoured), the bounding box hugs the active island in UV space, and G / R / S, the handles and the knob move, turn and scale the islands with the mouse. Panning and zooming the editor (<kbd>MMB</kbd> / <kbd>Wheel</kbd>) keep working and the gizmo follows.

- Picking: <kbd>LMB</kbd> selects the island whose UV faces are under the mouse, <kbd>Shift</kbd>+<kbd>LMB</kbd> adds or removes it; any island the editor shows can be picked. The session islands are the UV selection (with UV Sync on, the face selection).
- Available: island select / add / remove (<kbd>LMB</kbd>, <kbd>Shift</kbd>+<kbd>LMB</kbd>, <kbd>Z</kbd>, <kbd>W</kbd>), <kbd>G</kbd> / <kbd>R</kbd> / <kbd>S</kbd> with <kbd>X</kbd> / <kbd>Y</kbd>, the handles, the pivot (gizmo point click, <kbd>P</kbd>, <kbd>C</kbd>), scope (<kbd>I</kbd>), flip, fit, randomise, sensitivity, rotation step, undo / redo, confirm and cancel.
- The UV cursor is the editor's 2D cursor: the Cursor pivot starts on it and <kbd>C</kbd> moves it.
- Not in the UV Editor (the keys do nothing there): Align to Edge, Stitch, pins, Unwrap and its options, Straighten Chain, Align View, Clean View, Pause Modifiers, and edge / vertex hover and selection. The editor's overlays are left as they are.
- <kbd>Esc</kbd> also puts back the UV selection and the 2D cursor.

## HUD
The HUD always shows Pivot (P) (Center, Cursor or the picked point by its full name, such as Top Left Corner or Left Side), Scope (I) and the island count; Axis Lock (X / Y) appears during a move or scale and Modifiers Paused (Shift + Q) while the modifiers are paused. <kbd>Tab</kbd> adds UV Map, Sensitivity (Alt + Wheel), Rotation Step (Ctrl + Wheel), Unwrap Method (Shift + U) and Keep Mirror (Shift + M); with Tab off a row still appears while its value is away from its default. In the UV Editor the unwrap and modifier rows are left out. Every key works whether its row is shown or not; the help (<kbd>H</kbd>) lists them all.

## Options
- **Tile Limit** — how many tiles an island may drift from 0–1 before it is re-centred.
- **Rotation Step** — snap step for Ctrl-rotate.
- **Grab Sensitivity** — mouse-to-UV multiplier.

## Tips
- Each island shows its texel density next to its centre.
- A picked pivot point belongs to the gizmo, not to one island: it is read from the active island's bounding box each time a transform starts, so it follows the island as it moves and moves to the new active island after <kbd>W</kbd> or a click.
