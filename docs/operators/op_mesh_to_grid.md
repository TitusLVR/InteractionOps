# Mesh to Grid

Snaps every vertex of the active mesh to the nearest multiple of a configurable grid step on all three axes. Operates in Edit Mode on the active object's full vertex set (selection is ignored) and is useful for cleaning up coordinates that have drifted off integer/round positions.

<div class="iops-meta" markdown="1">
<span class="key">bl_idname: iops.mesh_to_grid</span>
<span class="mode">Mode: Edit Mesh</span>
<span>Context: VIEW_3D</span>
<span class="modal">Modal: no</span>
<span class="hud">HUD: no</span>
</div>

## Overview
A one-shot quantizer for vertex coordinates. For each vertex it rounds X, Y and Z independently to the nearest multiple of `base` (in scene units), then writes the result back into the bmesh. Use it to recover clean coordinates after sculpting, importing, or accumulated transforms, or to force a mesh onto a known grid step before booleans / array workflows.

It is not a snap-to-Blender-grid in the viewport sense — the step is the operator's own `base` property, not the overlay grid. The whole mesh is processed, regardless of vertex selection.

## Usage
- Active object must be a mesh in Edit Mode, in a 3D Viewport.
- Default keymap: <kbd>Up Arrow</kbd> (no modifiers).
- After invocation, adjust `Base` in the redo panel (F9) to change the grid step; the operator is registered with `UNDO` so re-running with a new value is safe.

## Properties

| Name | Type | Default | Description |
| --- | --- | --- | --- |
| `base` | Float | `0.01` | Grid step in scene units. Soft range `0.01`–`10` (0.01 = 1 cm, 10 = 10 m at default unit scale). Vertex coordinates are rounded to the nearest multiple of this value on each axis. |

## Notes
- Acts on all vertices in the active mesh, not just the current selection.
- The active object is taken from `view_layer.objects.active`; other objects in a multi-object edit session are not touched.
- Calls `bmesh.update_edit_mesh` and a depsgraph update after writing; reports `Vertices snapped to grid` on completion.
- Pure quantization — there is no tolerance check, so vertices already on grid are rewritten to identical values (cheap no-op).

## Related
- [Mesh to Verts](op_mesh_convert_selection.md)
- [Mesh to Edges](op_mesh_convert_selection.md)
- [Mesh to Faces](op_mesh_convert_selection.md)
- [Object to Grid From Active](op_grid_from_active.md)
