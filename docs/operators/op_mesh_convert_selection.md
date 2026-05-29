# Convert Selection

Three small operators that switch the active mesh selection mode to vertices, edges, or faces while expanding or extending the current selection so the conversion is non-destructive where possible. They wrap `bpy.ops.mesh.select_mode` with sensible flags so a single keystroke does the right thing from any source mode.

<div class="iops-meta" markdown="1">
<span class="key">bl_idname: iops.mesh_to_verts</span>
<span class="mode">Mode: Edit Mesh</span>
<span>Context: VIEW_3D</span>
<span class="modal">Modal: no</span>
<span class="hud">HUD: no</span>
</div>

<div class="iops-meta" markdown="1">
<span class="key">bl_idname: iops.mesh_to_edges</span>
<span class="mode">Mode: Edit Mesh</span>
<span>Context: VIEW_3D</span>
<span class="modal">Modal: no</span>
<span class="hud">HUD: no</span>
</div>

<div class="iops-meta" markdown="1">
<span class="key">bl_idname: iops.mesh_to_faces</span>
<span class="mode">Mode: Edit Mesh</span>
<span>Context: VIEW_3D</span>
<span class="modal">Modal: no</span>
<span class="hud">HUD: no</span>
</div>

## Overview
Blender's default select-mode switch either keeps the same elements selected (no expand) or always expands. These three operators pick the conversion behaviour per target mode so the resulting selection matches what you usually want when hopping modes mid-workflow:

- To vertices: extend, so going from edges or faces to verts keeps every endpoint vert selected.
- To edges: expand only when the source was vertex mode; otherwise plain switch (faces collapse to their boundary edges as Blender's default).
- To faces: always expand, so verts/edges promote to the faces they fully define.

After each call the operator also writes `tool_settings.mesh_select_mode` explicitly to lock in the single-element mode (no multi-mode left over).

## Usage
- Requires an active mesh in Edit Mode.
- Default keymap (Window keymap, from `prefs/hotkeys_default.py`):
  - `iops.mesh_to_verts` — <kbd>Alt</kbd>+<kbd>F1</kbd>
  - `iops.mesh_to_edges` — <kbd>Alt</kbd>+<kbd>F2</kbd>
  - `iops.mesh_to_faces` — <kbd>Alt</kbd>+<kbd>F3</kbd>

## Notes
- `iops.mesh_to_edges` checks `mesh_select_mode[0]` (vertex) to decide whether to pass `use_expand=True`; from face mode it switches without expand, which gives the boundary-edge result.
- `iops.mesh_to_verts` uses `use_extend=True`, `iops.mesh_to_faces` uses `use_expand=True`.
- All three force a single active select-mode tuple after the switch, even if you were in a multi-mode combination.
- Registered as `REGISTER, UNDO`; each conversion is a single undo step.

## Related
- [Mouseover Fill Select](op_mouseover_fill_select.md)
- [Quick Connect](op_mesh_quick_connect.md)
