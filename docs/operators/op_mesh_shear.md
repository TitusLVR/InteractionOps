# Shear

Smart shear that auto-detects the active selection and dispatches to either a face-shear or an edge-shear path. A selected face tilts around its centroid with each face vert sliding along its external "rail" edge; a selected edge tilts in its face plane by sliding the active endpoint along its rail. The operator runs modal, accepts a typed numeric angle, and offers extra actions for axis picking, perpendicular reset, and rail-mirrored extrude.

<div class="iops-meta" markdown="1">
<span class="key">bl_idname: iops.mesh_shear</span>
<span class="mode">Mode: Edit Mesh</span>
<span>Context: VIEW_3D</span>
<span class="modal">Modal: yes</span>
<span class="hud">HUD: yes</span>
</div>

## Overview
The operator solves the "saw-off" shear case: when a face or edge needs to tilt while its corner verts stay anchored to the surrounding mesh, plain Blender shear moves verts off their incident edges and breaks the surrounding topology. Here each active vert is constrained to slide along a rail edge (an incident non-face edge, or a face-adjacent fallback), so the result stays welded to the rest of the mesh.

Face mode shears every face vert by `-(proj_along_axis * tan(angle))` along its own rail. The axis can be steered with F (toggle between two world-aligned in-plane axes), A (align to the intersection line with a picked face), B (longer side of the face's minimum oriented bounding box), or by clicking one of the four orange axis handles on the widget.

Edge mode shears the "active" endpoint of each selected edge along its rail by `edge_length * tan(angle)`. The other endpoint is the fixed pivot.

## Usage
- Edit Mode on a mesh object.
- Select at least one face (face mode) OR at least one edge with at least one adjacent face (edge mode). Face selection takes priority.
- Selection history is consulted: the last `BMEdge` in `select_history` seeds the face-mode axis when it belongs to the selected face; the last `BMVert` selects the active endpoint of the corresponding selected edge.
- No default keymap binding. Invoke via search ("Shear (Smart)") or bind manually to `iops.mesh_shear`.
- Type digits to set the angle; press Enter to confirm, Esc or RMB to cancel.

## Modal Controls

| Key | Action |
| --- | --- |
| <kbd>0</kbd>-<kbd>9</kbd> / <kbd>Numpad 0-9</kbd> | Append digit to angle input |
| <kbd>.</kbd> / <kbd>Numpad .</kbd> | Append decimal point (one allowed) |
| <kbd>-</kbd> / <kbd>Numpad -</kbd> | Toggle sign of typed input |
| <kbd>Backspace</kbd> | Delete last typed character |
| <kbd>F</kbd> | Face mode: toggle between the two principal in-plane axes. Edge mode: flip active vert |
| <kbd>D</kbd> | If typing: flip sign of input. Else face mode: flip axis_dir (pivot moves to opposite face edge). Edge mode: negate current angle |
| <kbd>R</kbd> | Snap perpendicular to rails (resets to 0, rebuilds records at the snapped pose) |
| <kbd>E</kbd> | Enter the extrude sub-modal (rail-mirrored saw-off extrude) |
| <kbd>A</kbd> | Face mode: raycast face under cursor, align axis to the intersection of the two face planes (highlights picked face 35% red) |
| <kbd>B</kbd> | Face mode: set axis to the longer side of the face's minimum OBB |
| <kbd>H</kbd> | Toggle HUD / help overlay |
| <kbd>LMB</kbd> | Pick the hotspot under the cursor (never confirms; misclicks are absorbed) |
| <kbd>Enter</kbd> / <kbd>Numpad Enter</kbd> / <kbd>Space</kbd> | Confirm, push undo step |
| <kbd>Esc</kbd> / <kbd>RMB</kbd> | Cancel, restore original geometry |
| <kbd>MMB</kbd> / <kbd>Wheel</kbd> / NDOF | Pass-through (orbit/zoom) |

Extrude sub-modal (after <kbd>E</kbd>):

| Key | Action |
| --- | --- |
| Mouse move | Drag extrude distance along the on-screen direction of the rail-mirror arrow |
| <kbd>Shift</kbd> | Precision (sensitivity x0.1) |
| <kbd>LMB</kbd> / <kbd>Enter</kbd> / <kbd>Numpad Enter</kbd> / <kbd>Space</kbd> | Confirm extrude, rebuild shear record on the new geometry, return to shear modal |
| <kbd>Esc</kbd> / <kbd>RMB</kbd> | Cancel extrude (deletes the new geometry, returns to shear modal) |

## HUD
On-screen overlay shows:

- Header lines: current mode (`face` / `edge`), effective angle, and the typing buffer when present.
- Help section "Shear" listing all bindings; toggled with <kbd>H</kbd>.
- Per-record gizmo handles drawn over the geometry:
  - Grey ghost outline of the pre-shear face/edge.
  - Sheared geometry drawn with the `ACTIVE_LINE` role; on-pivot boundary edges with the `LOCKED_LINE` role (amber).
  - Face mode: a bbox-anchored widget with four orange `LOCKED_POINT` dots at the cross ends (click to set axis_dir so the saw-off pivot snaps to that side) and a saw-entry tick at the pivot side. Centre `CLOSEST_POINT` dot resets perpendicular to rails (= <kbd>R</kbd>).
  - Edge mode: two `LOCKED_POINT` endpoint dots (click to set that vert as the fixed anchor) and a centre `CLOSEST_POINT` dot to reset angle to 0.
- Hover highlight is a white dot drawn over the hotspot under the cursor (within 14 px).
- During <kbd>E</kbd>: a single white arrow tail-at-centre, head along the average rail-mirror direction, scaling with drag distance.
- During <kbd>A</kbd>: 35% `ERROR_LINE` (red) triangle-fan fill over the latched target face.

Colours come from the active theme via `ui.draw.theme.get_theme` (roles: `ACTIVE_LINE`, `ACTIVE_POINT`, `LOCKED_LINE`, `LOCKED_POINT`, `CLOSEST_POINT`, `ERROR_LINE`).

## Properties
No `bl_props`. All state is internal to the modal (typed angle, selection records, hover state, extrude/align sub-modals).

## Notes
- Undo: a single `ed.undo_push` named "Shear" is issued AFTER the final apply on confirm. This puts the undo boundary after the shear so changes land in their own step rather than getting folded into a subsequent operator. Cancel restores the original positions and does not push.
- Selection requirements: a face needs >=3 edges and at least one non-face external rail edge per corner (falls back to a face-adjacent rail for isolated faces). An edge needs at least one adjacent face. Verts/faces that fail these checks are skipped with a single-reason report.
- Face axis seeding: world +Z projected onto the face plane (falls back to +Y, then +X). If the last `BMEdge` in `select_history` belongs to the selected face it is used as the seed direction instead.
- Edge mode uses select_history's last `BMVert` to choose the active endpoint when one of the edge's two verts is in history; otherwise the second edge vert is active.
- Extrude sub-modal mirrors the rail across the sheared face plane (edge mode: across the sheared edge direction) so the extruded segment forms matched mitred ends. Per-vert delays equal `(proj_max - proj) * tan(angle)`, so the pivot edge starts moving only after the saw-off offset is consumed. Confirm deletes the original (interior) face; cancel keeps it.
- The operator catches `ReferenceError` mid-modal (e.g. external bmesh invalidation) and tears down the draw handler cleanly. `_finish` drops the bmesh wrapper and stored element refs so a later undo can free the operator instance without crashing Blender.
- Only `IOPS_OT_mesh_shear` is registered by this module — no panels, menus, or PropertyGroups.

## Related
- [Straight Bevel](op_mesh_straight_bevel.md)
- [Edge Slide and Flatten](op_mesh_shear.md)
