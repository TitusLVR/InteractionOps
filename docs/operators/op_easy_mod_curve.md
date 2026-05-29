# Easy Mod — Curve

Wires a Curve modifier between a selected mesh and a selected curve in one click. With a single mesh selected it jumps to the curve already driving its Curve modifier; with a mesh and a curve both selected it aligns origins, sets curve flags, and adds or replaces the Curve modifier on the mesh.

<div class="iops-meta" markdown="1">
<span class="key">bl_idname: iops.modifier_easy_curve</span>
<span class="mode">Mode: Object</span>
<span>Context: VIEW_3D</span>
<span class="modal">Modal: no</span>
<span class="hud">HUD: no</span>
</div>

## Overview
The operator covers two scenarios. With one mesh selected, it walks the active object's modifier stack, finds the first Curve modifier, and selects/activates the curve it points to — useful for navigating from a deformed mesh back to its driving spline. With a mesh and a curve selected together, it configures the curve (radius, stretch, deform bounds), snaps the curve's origin to the first spline point if origins differ, moves the mesh to the curve's location, and then either updates an existing Curve modifier on the mesh or appends a new one named "iOps Curve". Optionally it also retargets an Array modifier on the same mesh to Fit Curve with that curve.

## Usage
- Object Mode, 3D Viewport.
- One selected mesh with an existing Curve modifier: run to jump to the curve object.
- One mesh + one curve selected (mesh and curve in either role): run to bind the curve to a Curve modifier on the mesh.
- No default keymap binding — invoke via menu or operator search (`F3` -> "Easy Modifier - Curve").

## Properties
| Name | Type | Default | Description |
| --- | --- | --- | --- |
| `use_curve_radius` | Bool | True | Sets `curve.data.use_radius` — scales deformed mesh by spline radius. |
| `use_curve_stretch` | Bool | True | Sets `curve.data.use_stretch` — stretches or squeezes mesh across the full curve length. |
| `use_curve_bounds_clamp` | Bool | True | Sets `curve.data.use_deform_bounds` — ignores offset along deform axis. |
| `curve_modifier_axis` | Enum | `POS_X` | Modifier deform axis. Items: `POS_X` (X), `POS_Y` (Y), `POS_Z` (Z), `NEG_X` (-X), `NEG_Y` (-Y), `NEG_Z` (-Z). |
| `find_array_and_set_curve_fit` | Bool | False | If the mesh also has an Array modifier, switch its `fit_type` to `FIT_CURVE` and point it at the selected curve. |
| `Replace_Curve_Modifier` | Bool | True | When True, reuse the existing Curve modifier on the mesh; when False, always add a new "iOps Curve" modifier. |

## Notes
- Origin alignment: if mesh and curve origins differ, the operator moves the 3D cursor to the first spline point (POLY: `points[0].co`; BEZIER: `bezier_points[0].co`, both transformed by `curve.matrix_world.transposed()`), runs `object.origin_set` ORIGIN_CURSOR on the curve, then sets the mesh location equal to the curve location. The 3D cursor is moved as a side effect and not restored.
- The "jump to curve" branch only fires when exactly one object is selected and it is a mesh; it stops at the first Curve modifier found.
- The "add modifier" branch requires exactly two selected objects, one MESH and one CURVE — any other combination produces a "Mesh or Curve missing!!!" warning.
- If the mesh has no modifiers at all, a new "iOps Curve" modifier is appended regardless of `Replace_Curve_Modifier`.
- Registered as `REGISTER`/`UNDO`; tweak the operator panel (F6) to retune axis and flags after running.

## Related
- Easy Mod — Boolean
- Easy Mod — Mirror
- Easy Mod — Lattice
