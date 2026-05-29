# Copy Edges Length

Copies a length measurement from the active mesh into the system clipboard as a plain string. If edges are selected, it copies the sum of their lengths; otherwise, if exactly two vertices are selected, it copies the distance between them. Useful for piping a measured value into another numeric field (modifier, transform, custom property) without retyping.

<div class="iops-meta" markdown="1">
<span class="key">bl_idname: iops.mesh_copy_edge_length</span>
<span class="mode">Mode: Edit Mesh</span>
<span>Context: VIEW_3D</span>
<span class="modal">Modal: no</span>
<span class="hud">HUD: no</span>
</div>

## Overview
The operator reads the current edit-mesh selection via BMesh and writes the resulting length to `window_manager.clipboard`. The value is divided by the active scene's length unit scale (micrometers, millimeters, centimeters, meters, kilometers, or adaptive/default 1.0), so the number placed on the clipboard matches what Blender would display in the chosen unit rather than always being raw meters.

Use it when you need to feed an exact edge length (or vertex-to-vertex distance) into another input — a Bevel offset, an Array offset, a driver, or a property in another addon — without round-tripping through manual measurement.

## Usage
- Requires Edit Mode on an active mesh object.
- Selection rules:
  - One or more selected edges: copies the sum of all selected edge lengths.
  - Exactly two selected vertices (and no selected edges): copies the straight-line distance between them.
  - Anything else: reports `Invalid Selection` and cancels.
- No default keymap binding. Invoke via F3 search ("Copy Active Edge Length to Clipboard") or wire it up in your own keymap / pie.

## Notes
- The vertex-distance branch uses local-space coordinates (`v.co`) and is not divided by the unit scale — only the edge-sum branch applies the unit conversion.
- The clipboard receives `str(value)`, i.e. a full-precision Python float representation; no rounding.
- The unit scale is resolved from `bpy.data.scenes["Scene"].unit_settings.length_unit`, which assumes the scene is literally named `Scene`. In renamed scenes this lookup will raise.
- Despite the name "Copy Active Edge Length", the operator does not single out the active edge — it sums all selected edges.
- Operator does not modify mesh data and produces no undo step.

## Related
- [Mesh To Grid](op_mesh_to_grid.md)
- [Quick Connect](op_mesh_quick_connect.md)
