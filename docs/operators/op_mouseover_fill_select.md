# Mouseover Fill Select

Selects all faces linked to the face under the mouse cursor in a single click, extending the current selection. The operator briefly hides the current mesh, performs a hover pick, expands selection via linked-by-normal, then reveals the mesh so the linked island is added to the existing selection.

<div class="iops-meta" markdown="1">
<span class="key">bl_idname: iops.mesh_mouseover_fill_select</span>
<span class="mode">Mode: Edit Mesh</span>
<span>Context: VIEW_3D</span>
<span class="modal">Modal: no</span>
<span class="hud">HUD: no</span>
</div>

## Overview
This is a one-shot helper for picking a connected face island under the cursor without first having to click-select a seed face. It chains `mesh.hide`, `view3d.select`, `mesh.select_linked` (delimited by `NORMAL`), and `mesh.reveal(select=True)` so the result is added to the current selection in extend mode. Use it when you want to grow a selection across a flat patch (faces sharing normals) directly from a hover position.

## Usage
- Requires an active mesh object in Edit Mode.
- Hover the cursor over the target face and trigger the operator.
- The face under the cursor and all faces linked to it (delimited by normal continuity) are added to the existing selection.

Default keymap binding: bound to `F19` with Ctrl+Alt+Shift in `prefs/hotkeys_default.py`, which is an unreachable placeholder on most keyboards — effectively no usable default binding. Assign a real shortcut in the addon preferences or invoke via search.

## Notes
- The operator extends the current selection (`extend=True`); it never clears it.
- Internally relies on hiding and revealing the mesh as a trick to let `view3d.select` pick under the cursor without disturbing existing selection state, then `reveal(select=True)` brings everything back with the new linked island selected.
- Linked expansion uses `delimit={"NORMAL"}`, so the spread stops at sharp normal changes (typically across hard edges or split-normal boundaries).
- Registered with `REGISTER, UNDO` — one undo step rolls back the whole chain.

## Related
- [Mesh To Verts](op_mesh_convert_selection.md)
- [Mesh To Edges](op_mesh_convert_selection.md)
- [Mesh To Faces](op_mesh_convert_selection.md)
