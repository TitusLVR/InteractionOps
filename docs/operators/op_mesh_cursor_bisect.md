# Cursor Bisect

Modal mesh bisect driven by the 3D cursor. The cut plane is anchored to the cursor position and oriented from the face under the mouse (or a locked snapshot of it). Compared to Blender's built-in `mesh.bisect`, it adds live snapping to face vertices/midpoints/subdivisions, edge-distance inset points, a bevel mode that emits two parallel cuts, a fill-cut mode that bisects at every snap along the highlighted edge, optional edge marking (seam/sharp/crease/bevel) on the newly cut edges, and automatic disable/restore of mesh-deforming modifiers during the session.

<div class="iops-meta" markdown="1">
<span class="key">bl_idname: iops.mesh_cursor_bisect</span>
<span class="mode">Mode: Edit Mesh</span>
<span>Context: VIEW_3D</span>
<span class="modal">Modal: yes</span>
<span class="hud">HUD: yes</span>
</div>

## Overview

The operator raycasts under the mouse to find a face, snaps the 3D cursor to a chosen point on that face, aligns the cursor so that one of its axes lies along the closest face edge, and uses the cursor plane as the bisect plane. The currently highlighted edge defines the cursor orientation and is also the basis for inset points and the fill-cut sweep.

Use it when you need precise placement on a face (vertex, midpoint, regular subdivisions, fixed-distance offset from an endpoint) rather than the free-form plane of `mesh.bisect`. Bevel mode and fill-cut mode are designed for cases where a single bisect plane would otherwise need to be repeated several times in series. Modifier visibility is temporarily disabled for deforming/generative modifiers during the modal so the raycast hits the base mesh; original states are restored on exit.

## Usage

- One or more mesh objects in Edit Mode, with the mouse over a face of one of them. Selection inside the mesh is optional; if some faces are selected, only those are bisected, otherwise all visible faces are eligible.
- Default keymap: <kbd>F19</kbd> (no modifiers) in 3D View. F19 is the addon's "unbound" placeholder, so in practice you assign a real key in Preferences > Keymaps, or invoke via menu/search.
- Move the mouse over the target face, press the snap key (<kbd>S</kbd>) and subdivision controls (<kbd>Ctrl</kbd>+<kbd>Wheel</kbd>) to dial in the cut location, then <kbd>LMB</kbd> to commit. Press <kbd>Space</kbd> to finish or <kbd>Esc</kbd> to cancel.

## Modal Controls

| Key | Action |
| --- | --- |
| <kbd>MouseMove</kbd> | Raycast under cursor, update hit face, highlighted edge, snap point, and cursor transform |
| <kbd>LMB</kbd> | Execute bisect (fill cut if Fill mode is on) without exiting the modal |
| <kbd>RMB</kbd> | Toggle selection of the face under the cursor |
| <kbd>Shift</kbd>+<kbd>RMB</kbd> | Add/remove coplanar faces around the clicked face (uses `mesh.select_similar FACE_COPLANAR`) |
| <kbd>MMB</kbd> | Pass through (viewport navigation); HUD pins briefly |
| <kbd>Wheel</kbd> | Pass through (viewport zoom); HUD pins briefly |
| <kbd>Ctrl</kbd>+<kbd>Wheel</kbd> | Edge subdivisions for snap points, clamped to 0..100 (always consumed to suppress `mesh.select_more`) |
| <kbd>Alt</kbd>+<kbd>Wheel</kbd> | Rotate cursor around its local Z by the preferences rotation step (sign by wheel direction) |
| <kbd>S</kbd> | Toggle snapping on/off |
| <kbd>D</kbd> | Toggle hold snap points (freeze current snap set so mouse-over different faces doesn't recompute) |
| <kbd>A</kbd> | Toggle orientation lock; stores cursor rotation and the highlighted edge in world space |
| <kbd>X</kbd> | Toggle which cursor axis defines the bisect normal: X or Y |
| <kbd>W</kbd> | Cycle world-axis alignment for the cursor: X -> Y -> Z |
| <kbd>P</kbd> | Toggle cut preview between LINES and PLANE |
| <kbd>F</kbd> | Toggle fill-cut mode (bisect at every snap along the highlighted edge) |
| <kbd>V</kbd> | Toggle inset points (extra snap points at fixed distance from edge endpoints); force-enables snap |
| <kbd>B</kbd> | Toggle bevel mode (two parallel cuts offset perpendicular to the cut line, distance shared with V) |
| <kbd>M</kbd> | Toggle marking newly cut edges with the current mark type |
| <kbd>N</kbd> | Cycle mark type: SEAM -> SHARP -> CREASE -> BEVEL |
| <kbd>I</kbd> | Toggle distance info text (edge length / split distance) near the cursor |
| <kbd>0</kbd>..<kbd>9</kbd>, <kbd>Numpad 0</kbd>..<kbd>9</kbd> | Append digit to inset/bevel distance (only when V or B is active) |
| <kbd>.</kbd> / <kbd>Numpad .</kbd> | Add decimal point to inset/bevel distance (once) |
| <kbd>Backspace</kbd> | Delete last char from inset/bevel distance |
| <kbd>Enter</kbd> / <kbd>Numpad Enter</kbd> | Commit typed inset/bevel distance |
| <kbd>Z</kbd> | Deselect all in every Edit-Mode mesh in the selection |
| <kbd>Ctrl</kbd>+<kbd>Z</kbd> | `ed.undo` and refresh bmesh/caches |
| <kbd>Space</kbd> | Finish (returns FINISHED, runs cleanup) |
| <kbd>Esc</kbd> | Cancel (returns CANCELLED, runs cleanup) |
| <kbd>H</kbd> | Help / HUD param toggle (handled by HUD, configurable via `iops.ui_help_toggle` / `iops.ui_hud_params_toggle` keymap items) |

Drag events on the HUD and Help overlays are intercepted before the operator handles them, so HUD panels can be repositioned by dragging.

## HUD

Header text is updated every frame with the current operator state (snap on/off, hold, fill, inset/bevel values with display units, mark type, preview mode, axes, etc.). The workspace status bar at the bottom of the screen is also kept in sync via `workspace.status_text_set`.

A `HUDOverlay("cursor_bisect")` shows a "Bisect" section with per-toggle items reflecting current state (Snap, Subdivide, Hold Points, Fill Cut, Inset Points, Bevel Points, Mark Cut Edges, Mark Type, Select Face, Coplanar Select, Rotate, Lock Orientation, Select Direction, World Align, Preview, Distance Info, Help/Toggle HUD, Bisect, Finish, Cancel). Each item carries an ON/OFF state, the `always_show` items (Help, LMB, Space, Esc) remain visible even when params are hidden.

When distance info is enabled, the edge total length and the smaller of the two split distances are rendered in scene units near the mouse cursor (offsets +20 px / -30 px, size 16). Snap-point and cut-line rendering uses the addon's theme `Role` palette via `ui.draw.primitives`; HUD background colors follow the InteractionOps theme.

## Properties

| Name | Type | Default | Description |
| --- | --- | --- | --- |
| `merge_doubles` | BoolProperty | `True` | After bisect, run `bmesh.ops.remove_doubles` with the merge distance from addon preferences (`cursor_bisect_merge_distance`, fallback 0.005). |

The redo panel also exposes the addon preference `cursor_bisect_merge_distance` when `merge_doubles` is on, for read/write convenience.

Persistent state stored on `Scene.IOPS` (saved on cancel/finish, reloaded on next invoke): `cursor_bisect_snapping`, `cursor_bisect_normal_axis`, `cursor_bisect_preview_mode`, `cursor_bisect_fill_cut`, `cursor_bisect_show_distance`, `cursor_bisect_edge_subdivisions`, `cursor_bisect_inset_active`, `cursor_bisect_inset_distance`, `cursor_bisect_inset_input`, `cursor_bisect_bevel_active`, `cursor_bisect_mark_active`, `cursor_bisect_mark_type_idx`.

Addon preference keys consulted at runtime: `cursor_bisect_coplanar_angle` (default 5 deg), `cursor_bisect_rotation_step` (default 45 deg), `cursor_bisect_merge_distance` (default 0.005), `cursor_bisect_snap_threshold` (default 30 px).

## Notes

- Only `IOPS_OT_Mesh_Cursor_Bisect` is registered from this file. No panel/menu/property-group classes live here.
- Undo: each `LMB` execution pushes an `ed.undo_push("Cursor Bisect")` step. `Ctrl+Z` calls `ed.undo` and resyncs the bmesh and snap caches.
- Selection preservation across bisect+remove_doubles is done via a private int layer `cursor_bisect_sel` on `bm.faces`. The layer is removed at the end of each execution and a stray copy is cleaned up on error.
- Modifier handling: deforming/generative modifier types listed in `DISABLE_MODIFIER_TYPES` (subsurf, multires, solidify, array, screw, shrinkwrap, lattice, smooth variants, cloth, etc.) are switched off on `invoke` and their original `show_viewport` is restored on `cancel`. Mirror, Bevel, Edge Split, Weighted Normal, Normal Edit, UV Project, UV Warp are left enabled (`KEEP_MODIFIER_TYPES`).
- Bevel mode produces two `bisect_plane` passes with the perpendicular in-face offset; the second pass operates on the geometry produced by the first, so newly created edges are also cut.
- Fill-cut mode bisects at every snap point along the currently highlighted edge in a single `LMB`, not just at the cursor location.
- Draw handlers are tracked in a module-level `_ACTIVE_HANDLES` set so a fresh `invoke` can drop stale handlers left behind by addon reloads or crashed instances.
- `BISECT_PLANE_EPSILON = 1e-4` matches Blender's default bisect threshold so near-plane vertices snap rather than producing slivers.

## Related

- [Mesh Quick Connect](op_mesh_quick_connect.md)
- [Mesh Mouseover Fill Select](op_mouseover_fill_select.md)
- [Mesh Align Origin to Normal](op_align_origin_to_normal.md)
- [Cursor Rotate](op_cursor_rotate.md)
