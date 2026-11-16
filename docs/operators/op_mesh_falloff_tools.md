# Falloff Fields

Soft transforms driven by falloff fields. A field lives in the scene, is positioned in the viewport with handles, and can be stacked with other fields. Move, Rotate, Scale and Normal Offset read the field stack and apply their amount to every selected vertex multiplied by its weight. Operators: `iops.mesh_falloff_move`, `iops.mesh_falloff_rotate`, `iops.mesh_falloff_scale`, `iops.mesh_falloff_normal_offset`, plus `iops.mesh_falloff_fit` and `iops.mesh_falloff_clear`. Edit Mesh mode.

This is new, and the interaction differs from the earlier Falloff tools: the field is no longer created and edited inside the operator. You place the field first, then run an operation that uses it.

**Hotkey:** the operations are bound while the **Falloff** tool is the active toolbar tool in Edit Mesh mode (see below). They are also ordinary iOps operators: assign keys in *Preferences › iOps › Keymaps*, or run them from operator search. Called while another tool is active, they still use the scene's fields and draw them for the duration of the operation.

## Fields
A field turns a position in space into a weight from 0 to 1. Every selected vertex is weighted by the field stack; an operation applies its full amount at weight 1 and nothing at weight 0.

| Type | Weight |
| --- | --- |
| Linear | 0 at Start, 1 at End |
| Radial | 1 at the centre, 0 at the radius |
| Elliptical | 1 at the centre, 0 on the ellipsoid; two independent secondary radii and a roll about the main axis |
| Bidirectional | 0 at Start and at End, 1 in the middle |

Field geometry is stored in world space, so one field serves every object in multi-object Edit Mode. Each field also has:

- **Curve** — response shape: Linear, Smooth, Sharp, Root, Sphere, Inverse Square, Constant.
- **Invert** — flips the weights.
- **Strength** — 0 to 1.
- **Blend** — how the field combines with the ones above it in the stack.
- **Enabled** — takes part in the stack or not.

Changing a field's type refits it to the current selection. New fields are named *Falloff 1*, *Falloff 2*, … (unique within the stack); rename them in the stack popover.

### The stack
Fields are evaluated top to bottom. The first enabled field, or any field set to Replace, sets the weight. The others change it:

| Blend | Result |
| --- | --- |
| Replace | The field's weight |
| Add | Running weight plus the field's |
| Subtract | Running weight minus the field's |
| Multiply | Running weight times the field's (Strength fades the effect) |
| Min / Max | The smaller / larger of the two |

The weight is clamped to 0–1 after every step. With no enabled field, every weight is 1 and the operation behaves like the plain Blender one.

## The Falloff tool
Pick **Falloff** in the Edit Mesh toolbar. Activating the tool does not create or change anything; the stack stays empty until you press Fit or start a falloff operation.

**Tool keymap** (only while the tool is active)

| Key | Action |
| --- | --- |
| <kbd>G</kbd> | Falloff Move |
| <kbd>R</kbd> | Falloff Rotate |
| <kbd>S</kbd> | Falloff Scale |
| <kbd>Alt</kbd>+<kbd>S</kbd> | Falloff Normal Offset |
| <kbd>Shift</kbd>+<kbd>F</kbd> | Fit |

The active field is drawn with its handles: every type has a Start to End line with a gradient of its weight; Radial and Elliptical are also drawn as wire outlines (three loops around the sphere / ellipsoid). Drag **Start**, **End** or the middle **body** handle (moves the whole field); Elliptical adds a handle for each secondary radius. Other fields in the stack are drawn dimmed; click the dim dot at the midpoint of one to make it active. A separate **pivot** handle shows the pivot the operations will use; dragging it sets a custom pivot, **Reset Pivot** or Fit goes back to the automatic one.

A coloured dot per vertex shows the final weight of the whole stack (**Weights** toggle). It refreshes when a field or the selection changes.

While dragging a handle: <kbd>Ctrl</kbd> snaps it to the nearest vertex, <kbd>Shift</kbd> moves it slowly, and <kbd>X</kbd> / <kbd>Y</kbd> / <kbd>Z</kbd> constrain it to that **world** axis (press again to free). The operations, unlike the handles, constrain to the Basis axes.

Parts of the field drawing that geometry hides are drawn at no less than 50 % opacity, whatever the theme's occluded opacity, so a field under the mesh can still be seen and grabbed. The weight dots follow the theme's setting.

Tool settings (header): the stack popover (add, remove, reorder, enable, rename), the active field's type, curve, invert, strength and blend, the Weights toggle, the **Basis**, and the Fit, Clear and Reset Pivot buttons.

A field stays where you put it when the selection changes. Use Fit to bring it to the new selection.

## Fit
`iops.mesh_falloff_fit` activates the Falloff tool if needed. With no field it adds one of the last used type and fits it; otherwise it refits the active field. The first Fit for a selection follows the selection's long direction (principal axis). Pressing it again on the same selection cycles X, Y, Z, then back to the principal axis. Fit always clears a custom pivot, also when it adds the first field.

**Clear** (`iops.mesh_falloff_clear`) removes all fields and the custom pivot.

## Operations
Move, Rotate, Scale and Normal Offset start transforming immediately from the mouse position, like Blender's own G / R / S: no button is held. Started interactively with an empty stack, they fit a field first. Run from a script (`execute()`) with an empty stack, they apply weight 1 to every vertex and add no field.

| Key | Action |
| --- | --- |
| Move mouse | Set the amount |
| <kbd>X</kbd> / <kbd>Y</kbd> / <kbd>Z</kbd> | Constrain to that axis of the Basis; press again to clear. Move and Scale: <kbd>Shift</kbd>+axis constrains to the plane of the other two. Rotate: sets the rotation axis (the view axis by default). Not used by Normal Offset |
| <kbd>Shift</kbd> | Precise (slow) adjustment |
| <kbd>Ctrl</kbd> | Snap to steps (0.1 units, 5 degrees, 0.1 scale) |
| <kbd>0</kbd>–<kbd>9</kbd>, <kbd>.</kbd>, <kbd>-</kbd>, <kbd>Backspace</kbd> | Type an exact amount: units along the constraint (or X), degrees, scale factor, or distance |
| <kbd>[</kbd> / <kbd>]</kbd> | Previous / next curve of the active field, applied live |
| <kbd>Shift</kbd>+<kbd>I</kbd> | Invert the active field, applied live |
| <kbd>MMB</kbd> / <kbd>Wheel</kbd> | Navigate the viewport |
| <kbd>LMB</kbd> / <kbd>Enter</kbd> | Confirm |
| <kbd>Esc</kbd> / <kbd>RMB</kbd> | Cancel; the mesh and any curve or invert change made during the operation are restored |

The status line shows the operation, axis, amount, and the active field's name and curve.

- **Move** — offset at full weight.
- **Rotate** — angle about the pivot; positive is counter-clockwise when the rotation axis points toward the viewer.
- **Scale** — factor about the pivot, along the Basis axes; uniform unless an axis is set.
- **Normal Offset** — pushes each vertex along its own normal by distance times weight.

### Basis and pivot
**Basis** (Local, Cursor, World, Normal) sets the axes for X / Y / Z. The pivot is the custom pivot if you dragged it, otherwise the automatic one for the basis (Local: centre of the selection; Cursor: the 3D cursor; World: the origin; Normal: the active element). With several objects in Edit Mode, Local means the active object's axes.

### Adjust last operation (F9)
After confirming, the redo panel shows the amount, the pivot used, then each field that took part with Enabled, Blend, Strength, Curve and Invert. Changing any of these recomputes the result from the original geometry, so it never compounds. Field geometry (start, end, radii) is not editable there. Changes made in the panel are copied back to the scene's fields so the viewport shows what was applied.

## Multi-object
All meshes in Edit Mode are included and share the one field stack. With nothing selected anywhere, all visible vertices are used. Hidden vertices are never touched.

## Undo
Field edits (handle drags, adding, removing or reordering fields, Fit, curve and invert changes) are **not undoable**: Edit Mode undo restores the mesh, not scene properties. Ctrl+Z after an operation restores the mesh and leaves the fields as they are.

## Widget
The built-in **Falloff Tools** widget has Fit, Clear, Move, Rotate, Scale and Normal Offset buttons (Edit Mesh mode), the Basis dropdown and the Weights toggle. It has no per-field controls; use the tool settings for those. If you keep your own copy of the Falloff Tools widget in your widgets folder, it still points at the old `scene.IOPS.falloff_*` properties and must be updated: the new ones are `scene.IOPS.falloff.basis` and `scene.IOPS.falloff.show_weights`.

## Removed
- **Screen** and **Coplanar** falloff types and the **Element** (connected only) toggle.
- Editing the falloff inside the operator (the L / R / S / C type keys, handle dragging, auto-size, the V weight preview, the gizmo arrows and rings). The tool does this now.
- The old scene properties `falloff_type`, `falloff_shape`, `falloff_invert`, `falloff_connected`, `falloff_preview`, `falloff_screen_radius_px`, `falloff_coplanar_angle`, `falloff_basis`; the basis now lives in `scene.IOPS.falloff.basis`.
