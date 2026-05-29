# Copy Edges Angle

Computes the angle between two selected mesh edges and copies the value, in degrees, to the system clipboard. Useful when you need to feed a measured angle into another operator field (bevel, rotate, array) without eyeballing it.

<div class="iops-meta" markdown="1">
<span class="key">bl_idname: iops.mesh_copy_edges_angle</span>
<span class="mode">Mode: Edit Mesh</span>
<span>Context: VIEW_3D</span>
<span class="modal">Modal: no</span>
<span class="hud">HUD: no</span>
</div>

## Overview
The operator takes the two selected edges, normalizes their direction vectors, and returns the angle between them via `Vector.angle()`. The result is written to `window_manager.clipboard` as a plain string, ready to paste into any numeric input.

Edge direction is taken as `v2 - v1` in BMesh vertex order, so the reported angle can land between 0 and 180 degrees depending on how the edges are oriented. This is a one-shot action — no modal, no HUD, no properties.

## Usage
- Edit Mesh mode on a `MESH` object.
- Select exactly two edges.
- Run the operator (no default keymap binding — invoke via menu or F3 search).
- The angle in degrees is reported in the info bar and pushed to the clipboard.

If the selection count is not exactly two, the operator reports an error and cancels. If the computed angle is exactly `0` (parallel edges), it reports a warning "Edges do not intersect" and still returns `FINISHED` without writing to the clipboard.

## Notes
- The clipboard value is the raw Python float string (e.g. `45.00000000000001`); no rounding or formatting is applied.
- Angles are unsigned and lie in the range `[0, 180]`; the operator does not distinguish acute vs. obtuse based on edge orientation.
- The two edges do not need to share a vertex — the angle is between direction vectors, not at an intersection.

## Related
- [Copy/Paste Edge Length](op_mesh_copy_edges_length.md)
- [Edges Angle Bisector](op_mesh_copy_edges_angle.md)
