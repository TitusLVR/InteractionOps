# Z Ops (Grow/Shrink/Bounded Loop+Ring, Connect, Equalize, LineUp, PutOn, Mirror, Delete)

A bundle of mesh edit-mode utilities derived from the Zaloopok addon. Provides loop/ring selection growth and shrinkage, bounded loop/ring fills, edge connect (with optional Blender subdivide passthrough), edge chain equalize and line-up, face Put-On placement, in-place mirror with weld, and a context-aware delete that respects the active object type and mesh select mode.

## Overview

`z_ops.py` registers twelve operators that act on the current edit-mode mesh. The selection operators (grow/shrink loop and ring, bounded loop and ring) extend or contract edge selections by walking loop neighbours (opposite edge across a 4-valence manifold vertex) or ring neighbours (opposite edge across a quad face). The arrange operators (Equalize, Line Up) walk contiguous selected edge fragments, build vertex chains and either redistribute vertices evenly or proportionally to original spacing; closed chains are circularised, open chains are strung along the chord. Connect bisects selected edges and joins the new midpoints via `bmesh.ops.connect_verts`, or alternatively invokes the standard `mesh.subdivide` with full parameters. Put-On uses two selected faces (one active) to transform the connected region of the non-active face onto the active face. Mirror duplicates selected faces, flips them about each face's own plane and welds back. Delete dispatches to curve dissolve, armature delete, or mesh delete by select mode.

These exist as small, predictable building blocks for pie/menu wiring and keymapping; they avoid the larger Blender selection ops where simpler topology-walks are enough.

## Usage

- All operators require an active object in EDIT mode (Mirror, PutOn, Grow/Shrink Loop/Ring, Bounded Loop/Ring, Connect, Equalize, Line Up).
- Equalize and Line Up additionally require edge select mode `(False, True, False)`.
- Put-On requires exactly two selected faces, with one of them being the active face.
- Delete works on mesh (any select mode combination), curve (dissolve verts), or armature (delete) edit modes.
- None of these operators have a real default keymap binding. In `prefs/hotkeys_default.py` every `iops.z_*` entry is parked on `Ctrl+Alt+Shift+F19` as an unassigned placeholder. They are intended to be invoked via pies/menus or bound by the user.

## Grow Loop (bl_idname: iops.z_grow_loop)

<div class="iops-meta" markdown="1">
<span class="key">bl_idname: iops.z_grow_loop</span>
<span class="mode">Mode: Edit Mesh</span>
<span>Context: VIEW_3D</span>
<span class="modal">Modal: no</span>
<span class="hud">HUD: no</span>
</div>

Extends each selected edge along its loop direction by one edge in both ends when the shared vertex is 4-valence and manifold.

## Shrink Loop (bl_idname: iops.z_shrink_loop)

<div class="iops-meta" markdown="1">
<span class="key">bl_idname: iops.z_shrink_loop</span>
<span class="mode">Mode: Edit Mesh</span>
<span>Context: VIEW_3D</span>
<span class="modal">Modal: no</span>
<span class="hud">HUD: no</span>
</div>

Deselects each loop edge that sits on the boundary of a connected selected run (has at least one selected loop neighbour and at least one unselected/missing loop neighbour). Isolated selected edges with no selected neighbours are left alone.

## Grow Ring (bl_idname: iops.z_grow_ring)

<div class="iops-meta" markdown="1">
<span class="key">bl_idname: iops.z_grow_ring</span>
<span class="mode">Mode: Edit Mesh</span>
<span>Context: VIEW_3D</span>
<span class="modal">Modal: no</span>
<span class="hud">HUD: no</span>
</div>

Extends each selected edge along its ring direction (opposite edge across any incident quad).

## Shrink Ring (bl_idname: iops.z_shrink_ring)

<div class="iops-meta" markdown="1">
<span class="key">bl_idname: iops.z_shrink_ring</span>
<span class="mode">Mode: Edit Mesh</span>
<span>Context: VIEW_3D</span>
<span class="modal">Modal: no</span>
<span class="hud">HUD: no</span>
</div>

Symmetric of Shrink Loop along ring topology. Deselects boundary edges of contiguous ring runs.

## Select Bounded Loop (bl_idname: iops.z_select_bounded_loop)

<div class="iops-meta" markdown="1">
<span class="key">bl_idname: iops.z_select_bounded_loop</span>
<span class="mode">Mode: Edit Mesh</span>
<span>Context: VIEW_3D</span>
<span class="modal">Modal: no</span>
<span class="hud">HUD: no</span>
</div>

For every loop associated with the current selection, fills the gaps between selected edges. On finite loops it ignores tail gaps (gaps touching a loop end) when interior gaps exist. On infinite loops the single longest gap is left unfilled if it is strictly longest, otherwise all gaps fill.

## Select Bounded Ring (bl_idname: iops.z_select_bounded_ring)

<div class="iops-meta" markdown="1">
<span class="key">bl_idname: iops.z_select_bounded_ring</span>
<span class="mode">Mode: Edit Mesh</span>
<span>Context: VIEW_3D</span>
<span class="modal">Modal: no</span>
<span class="hud">HUD: no</span>
</div>

Ring-topology counterpart of Select Bounded Loop. Same gap-filling logic applied along rings.

## Delete Selection (bl_idname: iops.z_delete_mode)

<div class="iops-meta" markdown="1">
<span class="key">bl_idname: iops.z_delete_mode</span>
<span class="mode">Mode: Edit Mesh / Edit Curve / Edit Armature</span>
<span>Context: VIEW_3D</span>
<span class="modal">Modal: no</span>
<span class="hud">HUD: no</span>
</div>

Context-aware delete:

- Curve: `curve.dissolve_verts()`.
- Armature: `armature.delete()`.
- Mesh: iterates the active mesh select mode tuple and calls `mesh.delete(type=...)` for each enabled mode in reverse order (`FACE`, `EDGE`, `VERT`). If multiple select modes are enabled simultaneously, multiple deletes run in sequence.

There is no poll; the operator assumes a valid active object and edit context.

## Equalize (bl_idname: iops.z_eq_edges)

<div class="iops-meta" markdown="1">
<span class="key">bl_idname: iops.z_eq_edges</span>
<span class="mode">Mode: Edit Mesh (edge select mode only)</span>
<span>Context: VIEW_3D</span>
<span class="modal">Modal: no</span>
<span class="hud">HUD: no</span>
</div>

Groups the selected edges into connected fragments, builds a vertex chain per fragment (fragments with branching are skipped — `vert_chain` returns `None` if any chain vertex has more than two selected incident edges). For each chain:

- Closed chain: place vertices on a fitted circle (average radius, normal averaged from consecutive cross products) at equal angular spacing.
- Open chain: place vertices at equal spacing along the straight line from first to last vertex.

## Line Up (bl_idname: iops.z_line_up_edges)

<div class="iops-meta" markdown="1">
<span class="key">bl_idname: iops.z_line_up_edges</span>
<span class="mode">Mode: Edit Mesh (edge select mode only)</span>
<span>Context: VIEW_3D</span>
<span class="modal">Modal: no</span>
<span class="hud">HUD: no</span>
</div>

Same chain construction as Equalize, but spacing is proportional to original segment lengths:

- Closed: angular spacing per vertex weighted by original edge length / total length.
- Open: vertices distributed along the chord, each segment keeping its original length ratio.

## Connect (bl_idname: iops.z_connect)

<div class="iops-meta" markdown="1">
<span class="key">bl_idname: iops.z_connect</span>
<span class="mode">Mode: Edit Mesh</span>
<span>Context: VIEW_3D</span>
<span class="modal">Modal: no</span>
<span class="hud">HUD: no</span>
</div>

Two modes:

- `use_subdivide_op=False` (default): with edge select mode active, bisects each selected edge that shares a face with at least one other selected edge, then connects the resulting midpoint verts via `bmesh.ops.connect_verts`. The new edges become the selection. Outside edge select mode reports "No Selected Edges".
- `use_subdivide_op=True`: forwards to `bpy.ops.mesh.subdivide(...)` with all exposed parameters.

### Properties

| Name | Type | Default | Description |
| --- | --- | --- | --- |
| `use_subdivide_op` | Bool | False | Use Blender's `mesh.subdivide` instead of the bmesh bisect+connect path |
| `number_cuts` | Int (0..10000) | 1 | Subdivide cuts (passthrough) |
| `smoothness` | Float (soft 0..1) | 0.0 | Subdivide smoothness (passthrough) |
| `ngon` | Bool | True | Allow n-gons when subdividing; if False results are limited to tris/quads |
| `quadcorner` | Enum | FAN | Quad corner strategy: `INNERVERT`, `PATH`, `STRAIGHT_CUT`, `FAN` |
| `fractal` | Float (0..1) | 0.0 | Subdivide fractal amount (passthrough) |
| `fractal_along_normal` | Float (0..1) | 0.0 | Subdivide fractal along normal (passthrough) |
| `seed` | Int (0..255) | 0 | Random seed for fractal subdivide |

The redo panel only shows subdivide parameters when `use_subdivide_op` is enabled.

## Put On (bl_idname: iops.z_put_on)

<div class="iops-meta" markdown="1">
<span class="key">bl_idname: iops.z_put_on</span>
<span class="mode">Mode: Edit Mesh</span>
<span>Context: VIEW_3D</span>
<span class="modal">Modal: no</span>
<span class="hud">HUD: no</span>
</div>

Requires exactly two selected faces, one of which is the active face (`bm.faces.active`). The non-active face is the "source"; the operator computes a transform that maps source face center to active face center, rotates source's `+Z`-aligned frame to land flipped (`-Z`) onto the active face's frame, then applies an optional `turn` rotation around the destination Z. The transform is applied to the entire connected region reachable from the source face by edge-walk (`extend_region`), so the source face's island moves as a rigid body. Cancels silently otherwise.

### Properties

| Name | Type | Default | Description |
| --- | --- | --- | --- |
| `turn` | Float (-180..180) | 0.0 | Extra rotation around the destination face normal after placement, in degrees |

## Mirror (bl_idname: iops.z_mirror)

<div class="iops-meta" markdown="1">
<span class="key">bl_idname: iops.z_mirror</span>
<span class="mode">Mode: Edit Mesh</span>
<span>Context: VIEW_3D</span>
<span class="modal">Modal: no</span>
<span class="hud">HUD: no</span>
</div>

For each selected face, duplicates the full face list, flips the duplicate's normals, reflects the duplicate across the original face's own plane (scale -1 along face normal through face center), removes both the original face and its duplicate counterpart, then welds duplicate verts of the original face's boundary to the original verts. Net effect: each selected face is replaced by a mirrored copy attached to the surrounding mesh.

Note: the duplication call passes the entire `orig_faces` list per selected face, so this is O(selected_faces * total_faces) and not intended for large bulk selections.

## Notes

- All eleven mesh operators add `REGISTER, UNDO`; redo-panel works.
- Grow/Shrink Loop/Ring operate purely on selected edges regardless of current select mode, but only edit-mode is enforced.
- `Z_OT_ContextDelete` has no `poll`; calling it outside a valid edit context may error.
- Equalize / Line Up silently skip any fragment that branches (a vertex with three or more selected incident edges).
- Connect's non-subdivide path only fires when edge select mode is active; otherwise it reports "No Selected Edges" and finishes.
- Default keymap entries for every `iops.z_*` bl_idname are placeholders on `Ctrl+Alt+Shift+F19` — treat as "no default keymap binding" in practice.

## Related

- [Mesh To Verts / Edges / Faces](op_mesh_convert_selection.md)
- [Mesh Quick Connect](op_mesh_quick_connect.md)
- [Mesh Cursor Bisect](op_mesh_cursor_bisect.md)
- [Mesh To Grid](op_mesh_to_grid.md)
