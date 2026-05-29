# Radial Array

Modal operator that arrays selected object hierarchies around a pivot/axis with a live 3D preview. It covers full circles, fixed-angle arcs, and a free Active-to-Cursor arc, with separate alignment, source-grouping and clone-type modes, plus an interactive lock/skip system for editing individual slots before commit.

<div class="iops-meta" markdown="1">
<span class="key">bl_idname: iops.object_radial_array</span>
<span class="mode">Mode: Object</span>
<span>Context: VIEW_3D</span>
<span class="modal">Modal: yes</span>
<span class="hud">HUD: yes</span>
</div>

## Overview

The operator builds a radial array as a separate, interactive workflow rather than as a modifier. Sources can be the active object, an active subtree, the whole selection treated as a rigid group, or a pool from which random extras are picked once the slot count exceeds the source count. Pivot, axis, arc type and alignment are all hot-swappable while the modal is running, with parameters and key hints surfaced on the HUD and help overlay.

Use it instead of the Array modifier when you need a true rotational layout with per-instance control, when the axis or radius is derived from the 3D cursor or an active object's frame, or when you want to lock individual slots out before committing.

The result is a new collection `_RadialArray_<root>` containing duplicated or linked clones; in REPLACE mode the source objects are moved in place instead and overflow slots become linked instances in that same collection.

## Usage

- Object mode, VIEW_3D, with at least one selected object and an active object.
- No default keymap binding; invoke via search or menu (`iops.object_radial_array`).
- On invoke the active object marks slot 0; clones spread around the pivot from there.
- Tweak parameters with the modal keys below; commit with Space/Enter or cancel with Esc/RMB.

## Modal Controls

| Key | Action |
| --- | --- |
| <kbd>Q</kbd> | Cycle pivot: Active-Cursor / Cursor / Active. Remaps the axis letter to the new pivot's frame. |
| <kbd>W</kbd> | Cycle arc mode: 360 / 180 / 90 / 45 / Active to Cursor. |
| <kbd>E</kbd> | Toggle axis-offset mode (then LMB-drag the axis handle to slide the array along the rotation axis). |
| <kbd>R</kbd> | Cycle alignment: Align / Rotate / Random All / Random X / Random Y / Random Z. |
| <kbd>D</kbd> | Cycle clone type: Duplicate / Instance / Replace. |
| <kbd>T</kbd> | Cycle source mode: Active / Hierarchy / Group / Pool. |
| <kbd>A</kbd> | Toggle Match: snap source objects to nearest arc slot (live re-snap on parameter change); press again to restore originals. |
| <kbd>G</kbd> | Re-roll random pool seed (Pool source mode only). |
| <kbd>S</kbd> | Toggle Start point clone (also clones slot 0). |
| <kbd>F</kbd> | Toggle End point inclusive (arc modes other than 360). |
| <kbd>X</kbd> / <kbd>Y</kbd> / <kbd>Z</kbd> | Toggle axis letter between pivot-frame (cursor or local) and Global. |
| <kbd>V</kbd> | Use view axis. |
| <kbd>C</kbd> | Arm face-pick: hover a face to highlight, click to snap the 3D cursor (location and Z-normal) to the nearest face vertex / edge mid / center. Esc cancels. |
| <kbd>N</kbd> | Toggle locked-clone display: Show (tinted) / Hide. Picking is always live. |
| <kbd>M</kbd> | Lock every drawn slot (or unlock if all locked) — click slots to keep. |
| <kbd>I</kbd> | Flip the arc apex side (Active-to-Cursor arc only). |
| <kbd>B</kbd> | Reset all parameters to defaults (sources and pivot kept). |
| <kbd>1</kbd> / <kbd>2</kbd> / <kbd>3</kbd> / <kbd>4</kbd> / <kbd>5</kbd> | Set local rotation step to 1° / 5° / 15° / 45° / 90°. |
| <kbd>Left</kbd> / <kbd>Right</kbd> / <kbd>Up</kbd> | Nudge local X / Y / Z rotation by current step (hold <kbd>Shift</kbd> to reverse). |
| <kbd>Down</kbd> | Reset per-clone local rotation. |
| <kbd>+</kbd> / <kbd>=</kbd> | Count +1 (max 1024). |
| <kbd>-</kbd> | Count -1 (min 2). |
| <kbd>Ctrl</kbd> + <kbd>Wheel</kbd> | Count ±1 (±10 with Shift). |
| <kbd>LMB</kbd> on clone | Lock / unlock that slot. |
| <kbd>LMB</kbd> on ring + drag | Change radius (fixed arcs) or drag arc curve (Active-to-Cursor). |
| <kbd>LMB</kbd> on center + drag | Move arc center along the AB perpendicular bisector (Active-to-Cursor). |
| <kbd>LMB</kbd> drag (axis-offset mode) | Slide whole array along the rotation axis. |
| <kbd>Ctrl</kbd> + <kbd>Z</kbd> | Step back through parameter history. |
| <kbd>Ctrl</kbd> + <kbd>Shift</kbd> + <kbd>Z</kbd> | Redo. |
| <kbd>H</kbd> | Toggle help / HUD overlays. |
| <kbd>Space</kbd> / <kbd>Enter</kbd> | Apply. |
| <kbd>Esc</kbd> / <kbd>RMB</kbd> | Cancel. |
| <kbd>MMB</kbd>, plain <kbd>Wheel</kbd>, trackpad | Pass through (viewport navigation). |

## HUD

Always-on parameters: Count, Pivot, arc Type, Alignment, Axis, Source.

Contextual parameters appear only when relevant: Axis offset (in offset mode or when nonzero), Start point (when on), End point (any arc mode but 360), Rot step and Local Rot (when local rotation is nonzero), Skip/delete (mode plus locked-slot count, when locked slots exist or HIDE), Match (when active), Clone type (when not Duplicate).

3D preview uses theme roles: `GHOST_DEFAULT` for clone fill, `GHOST_LOCKED` for locked clones (in Show mode), `GHOST_CLOSEST` for the hovered clone, `GHOST_EDGE` for all clone wireframes, `PREVIEW_LINE` / `PREVIEW_POINT` for the ring and slot markers, `PIVOT` for the arc center, `ACTIVE_POINT` for the arc-end marker, `ACTIVE_LINE` for the axis handle in offset mode, and `LOCKED_POINT` for locked-slot markers. The face-pick overlay also uses `CLOSEST_LINE` / `CLOSEST_POINT`.

## Notes

- The operator declares `bl_options = {"REGISTER", "UNDO"}` but the in-modal Ctrl+Z / Ctrl+Shift+Z step through an internal 64-state history snapshot of parameters, not Blender's undo stack. Drags collapse to a single history entry; Match is excluded from history (it has its own toggle).
- Match mutates the original objects in place. Toggling Match off restores the captured matrices; applying with Match active commits those positions and creates no clones.
- Apply outputs into a fresh `_RadialArray_<root_name>` collection. In Duplicate mode mesh data is also copied; in Instance mode data is shared. In Replace mode the source objects move to the slots; if the slot count exceeds the source count (Pool) or in non-Pool source modes, additional slots become linked instances inside the same `_RadialArray_` collection.
- Per-mesh vertex / edge / loop-triangle caches are built once on source rebuild so the per-frame preview is matrix-multiplies only.
- Locked slots are stored as an in-modal set of slot indices and excluded at apply time.
- Slot 0 always sits at the active object's angle around the pivot (every arc mode), so the active is the visual anchor of the array.
- Pivot `ACTIVE_CURSOR` keeps the axis from the 3D cursor but lifts the circle plane to pass through the active object; the center recomputes whenever axis or pivot changes.

## Related

- [Three-Point Rotation](op_object_three_point_rotation.md)
- [Object Rotate (axis variants)](op_object_rotate.md)
- [Drag Snap](op_drag_snap.md)
- [Grid From Active](op_grid_from_active.md)
- [Cursor Rotate](op_cursor_rotate.md)
