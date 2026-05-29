# Quick Connect

Modal vertex-to-vertex connect for Edit Mesh. Drag from one vertex to another to cut a path between them (equivalent to Blender's `mesh.vert_connect_path`), or hold a modifier to split a hovered edge first and connect to the new vertex. Stays in modal so you can chain multiple connects in one session and undo back to the entry state on cancel.

<div class="iops-meta" markdown="1">
<span class="key">bl_idname: iops.mesh_quick_connect</span>
<span class="mode">Mode: Edit Mesh</span>
<span>Context: VIEW_3D</span>
<span class="modal">Modal: yes</span>
<span class="hud">HUD: yes</span>
</div>

## Overview
Blender's vertex-connect requires explicit selection of the two endpoints, then a keystroke. Quick Connect collapses that into one drag: press LMB on a vertex, drag to a second, release. Selection state is managed internally; the active mesh's current selection is overwritten during the operation.

The operator keeps running after each connect, so successive cuts can be made without reinvoking. Holding `A` over a face lets you subdivide one of its edges at the cursor (or its midpoint) and immediately connect the in-progress start vertex to the freshly created vertex.

## Usage
- Active object must be a mesh in Edit Mode. If not, the operator cancels on invoke.
- Default keymap: no default keymap binding (entry is registered with the `F19` placeholder in `prefs/hotkeys_default.py`). Invoke via search, pie, or a user-assigned shortcut.
- Click to start drag, move to target vertex, release LMB to commit. Press `Space` when done, or `Esc` / RMB to cancel and roll back every connect made in this session.

## Modal Controls
| Key | Action |
| --- | --- |
| <kbd>LMB</kbd> Press | Pick start vertex under cursor |
| <kbd>LMB</kbd> Drag | Track end vertex under cursor |
| <kbd>LMB</kbd> Release | Connect start and end via `mesh.vert_connect_path` |
| <kbd>A</kbd> Hold | Enter edge-split preview: hover an edge of the face under the cursor; release `A` to split it at the preview point and (if a start vertex is set) connect to the new vertex |
| <kbd>S</kbd> | Toggle Snap Midpoint — edge-split preview snaps to the edge midpoint instead of the cursor's closest point on the segment |
| <kbd>W</kbd> | Toggle Screen Space — vertex picking uses occlusion-checked screen-space search instead of raycast-then-nearest-vertex |
| <kbd>MMB</kbd> / <kbd>Wheel</kbd> / NDOF | Pass through to viewport navigation |
| <kbd>Space</kbd> | Finish, keep changes |
| <kbd>Esc</kbd> / <kbd>RMB</kbd> | Cancel: undo every push made during the session |
| <kbd>/</kbd> | Hide / show HUD parameter list (via HUD framework) |
| <kbd>H</kbd> | Toggle help overlay (via HUD framework) |

The HUD and help overlay also handle their own drag-to-move events; those are consumed before the operator's key handling.

## HUD
Cursor-following HUD shows the title "Quick Connect" and two live boolean params: `Snap midpoint` and `Screen space`. A corner help overlay lists the modal keymap; the `S` and `W` rows reflect the current toggle state.

Viewport drawing uses theme roles:

- `Role.CLOSEST_POINT` — hover vertex highlight when no drag is active (only when the cursor is within ~20 px of the candidate vertex on screen).
- `Role.ACTIVE_LINE` — the start-to-end (or start-to-cursor) line during a drag.
- `Role.ACTIVE_POINT` — the start and end vertex markers.
- `Role.PREVIEW_POINT` — the edge-split preview point while `A` is held.

A status bar string is also written to the workspace while modal, summarising the controls.

## Notes
- Each successful `vert_connect_path` and each edge split pushes its own undo step; the operator counts them and rewinds them all on cancel. Finishing with `Space` leaves them in place.
- Edge split is implemented via `bmesh.ops.subdivide_edges` and then a `vert_connect_path` from the existing start vertex (if any) to the new vertex. The new vertex is positioned at the cursor's hit point on the edge (or the edge midpoint if Snap Midpoint is on).
- If the same vertex is set as both start and end, the release is a no-op (selection still gets reset).
- Vertex picking has two modes: when Screen Space is off, the operator raycasts to find the active mesh's surface, then snaps to the bmesh vertex closest to the hit in object space (this can pick vertices behind the visible face); when on, it uses the occlusion-checked screen-space scan from `utils.picking.nearest_vertex_screen`.
- Edge picking always raycasts and then evaluates only the edges of the hit face.
- The internal `handle_a_key` method is dead code; behaviour lives in `update_edge_preview` and `execute_edge_split`.

## Related
- [Cursor Bisect](op_mesh_cursor_bisect.md)
- [Mesh to Grid](op_mesh_to_grid.md)
- [Mouseover Fill Select](op_mouseover_fill_select.md)
