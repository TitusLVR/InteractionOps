# Mesh Visual UV

Interactive UV island editing performed directly on the mesh surface in the 3D viewport. The operator detects UV islands on selected faces, draws their bounding box and scale/rotate handles projected through the mesh, and lets you grab/rotate/scale/flip/align/randomize/unwrap them without leaving the viewport. It is meant for quick UV cleanup and alignment work while you are still focused on the model.

<div class="iops-meta" markdown="1">
<span class="key">bl_idname: iops.mesh_visual_uv</span>
<span class="mode">Mode: Edit Mesh</span>
<span>Context: VIEW_3D</span>
<span class="modal">Modal: yes</span>
<span class="hud">HUD: yes</span>
</div>

## Overview
Working on UVs usually means context-switching to the UV/Image editor. Visual UV keeps you in the 3D view: islands are color-coded, the active island shows a UV-aligned bbox with corner/midpoint handles, and a pivot dot plus a rotation knob lifted along the face normal. Transforms operate on screen vectors decomposed into the projected UV axes, so dragging behaves consistent with the texture orientation even when the surface is angled.

It is intended for "in-place" adjustments — aligning shells to an edge, matching texel density between islands, flipping, randomizing offsets, or straightening an edge chain — without losing sight of the model.

## Usage
- Edit Mode on a mesh, at least one face selected. The operator collects UV islands from those faces.
- Default keymap: <kbd>Ctrl</kbd>+<kbd>Alt</kbd>+<kbd>U</kbd> in the 3D Viewport.
- The active island shows the bbox + 8 handles + center pivot + rotation knob. Hover over a handle to make it the implicit pivot for the next R/S press; click a handle to start a handle-driven scale; click the rotation knob to start a handle-driven rotate; click on island geometry to make that island active; <kbd>Tab</kbd> cycles active island.
- Confirm with <kbd>Enter</kbd>/<kbd>Space</kbd>, cancel with <kbd>Esc</kbd> (cancel restores the original UVs cached at invoke time).

## Modal Controls

| Key | Action |
| --- | --- |
| <kbd>LMB</kbd> on handle | Start handle scale (opposite handle = pivot) |
| <kbd>LMB</kbd> on rotation knob | Start handle rotate |
| <kbd>LMB</kbd> on island | Make that island active |
| <kbd>LMB</kbd> (in edge-pick mode) | Pick edge to align active island to |
| <kbd>LMB</kbd> (in density modes) | Pick reference, then target island |
| <kbd>G</kbd> | Grab / Move selected islands |
| <kbd>R</kbd> | Rotate around pivot (uses hovered handle if any) |
| <kbd>S</kbd> | Scale around pivot (uses hovered handle if any) |
| <kbd>X</kbd> / <kbd>Y</kbd> | Toggle axis lock (during G / S / handle-S) |
| <kbd>Shift</kbd> (during G) | Constrain dominant axis |
| <kbd>Shift</kbd> (during S corner) | Uniform scale |
| <kbd>Ctrl</kbd> (during G) | Snap offset to 1/16 UV |
| <kbd>Ctrl</kbd> (during R) | Snap to current rotation step |
| <kbd>Ctrl</kbd> (during S) | Snap factor to 0.05 |
| <kbd>Ctrl</kbd>+<kbd>Wheel</kbd> (during R) | Cycle rotation step (1, 5, 10, 15, 30, 45, 90 deg) |
| <kbd>Alt</kbd>+<kbd>Wheel</kbd> | Adjust grab/transform sensitivity (5%..300%) |
| <kbd>C</kbd> | Place UV cursor at mouse (and set pivot to CURSOR) |
| <kbd>P</kbd> | Toggle pivot mode CENTER / CURSOR |
| <kbd>A</kbd> | Align: with hovered handle, snap selected islands to active's handle on that axis; without a handle, enter edge-pick mode |
| <kbd>F</kbd> | Flip horizontal (around pivot) |
| <kbd>Shift</kbd>+<kbd>F</kbd> | Flip vertical |
| <kbd>D</kbd> | Match dimensions of selected islands to active |
| <kbd>N</kbd> | Randomize UV (both axes) per island |
| <kbd>Shift</kbd>+<kbd>N</kbd> | Randomize U only |
| <kbd>Ctrl</kbd>+<kbd>N</kbd> | Randomize V only |
| <kbd>U</kbd> | Unwrap selection (Angle Based, margin 0.001) |
| <kbd>T</kbd> | Straighten edge chain through hovered edge (>= 3 verts) |
| <kbd>Q</kbd> | Toggle clean view (hide viewport overlays + operator HUD) |
| <kbd>Tab</kbd> | Cycle active island |
| <kbd>Ctrl</kbd>+<kbd>Z</kbd> / <kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>Z</kbd> | Undo / Redo within the modal session |
| <kbd>LMB</kbd> press (in transform) | Confirm key-driven transform |
| <kbd>LMB</kbd> release (in handle transform) | Confirm handle-driven transform |
| <kbd>RMB</kbd> (in transform) | Cancel current transform |
| <kbd>Enter</kbd> / <kbd>NumpadEnter</kbd> / <kbd>Space</kbd> | Confirm transform / Confirm operator |
| <kbd>Esc</kbd> | Cancel operator (restores UVs) |
| <kbd>H</kbd> | Toggle Help overlay / HUD (handled by shared HUD layer) |
| <kbd>MMB</kbd> / <kbd>Wheel</kbd> (no modifier) | Pass-through to viewport navigation |

## HUD
The shortcuts/help overlay is the shared IOPS HUD. Header shows current state, pivot mode, sensitivity percent, island count and current rotation step. The help panel lists every shortcut and is toggled with the standard HUD <kbd>H</kbd> binding.

In-view drawing:
- Per-island translucent fill, color from `theme.island_palette` (8 slots, cycled). Active island brighter, selected slightly brighter, idle dimmer.
- Island outline edges drawn via line roles: `Role.ACTIVE_LINE` for active, `Role.CLOSEST_LINE` for selected, `Role.LINE` otherwise.
- UV-aligned bounding box (`Role.BBOX`), corner handles (circles) and midpoint handles (diamonds) in `Role.HANDLE`, hovered handle in `Role.HANDLE_HOVER`.
- Center pivot ring + dot and rotation knob in `Role.PIVOT`; hovered rotation knob in `Role.HANDLE_HOVER`.
- UV cursor crosshair + dot in `Role.CURSOR`.
- Hovered edge for align/straighten in `Role.PREVIEW_LINE` (pick-edge state) or `Role.LOCKED_LINE` otherwise.
- Per-island `TD:` (texel density) label near each center in island color.
- Transform feedback near the mouse uses `Role.HUD_ACTIVE_VALUE`; axis-locked text uses `axis_color('X')` / `axis_color('Y')`.

`Q` hides the overlay (and Blender's viewport overlays).

## Properties

| Name | Type | Default | Description |
| --- | --- | --- | --- |
| `tile_limit_prop` | Int (1..10) | 2 | Max tiles away from the 0-1 area before an island gets re-centered to (0.5, 0.5) during live transforms. |
| `rotation_step_prop` | Int (1..90) | 90 | Ctrl-snap rotation step in degrees. Stored as one of (1, 5, 10, 15, 30, 45, 90). |
| `grab_sensitivity_prop` | Float (0.05..3.0) | 1.0 | Multiplier on grab and pixel-derived motion. Adjusted live with Alt+Wheel. |

These three props are also written back from the live session state when the operator finishes (so the redo panel reflects the last in-modal values).

## Notes
- Cancel (`Esc`) restores the snapshot taken at invoke via `cache_all_uvs` / `restore_uvs`. Confirm finalizes the bmesh.
- Undo/Redo stacks are local to the modal session; they do not feed Blender's global undo.
- Tile bounds are enforced every live update — if any selected island drifts more than `tile_limit` UV units past 0-1 on either axis it snaps back to center (0.5, 0.5).
- `U` invokes `bpy.ops.uv.unwrap(method='ANGLE_BASED', margin=0.001)` on the current selection.
- `T` straightens a chain of UV edges traversed from the hovered edge through shared UV endpoints; needs at least 3 chain vertices.
- Grab uses the projected UV axes (`_u_dir`, `_v_dir`) when both have non-trivial screen length; otherwise it falls back to a view-distance pixel-to-UV scale.
- Density match (`match_texel_density`) is exposed in code but reached only through the pick states; key binding for entering those states is not in the current modal table — they are driven by `state` transitions in code paths (left as an internal feature).
- Only one operator class is registered in this module (`IOPS_OT_MeshVisualUV`); no panel or property group accompanies it.

## Related
- [Mesh UV Shortest Mark](op_mesh_uv_shortest_mark.md)
- [Mesh To Grid](op_mesh_to_grid.md)
- [Mesh Quick Connect](op_mesh_quick_connect.md)
