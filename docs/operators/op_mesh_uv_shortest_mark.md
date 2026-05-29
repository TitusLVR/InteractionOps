# UV Shortest Mark

Interactive modal for marking shortest paths on a mesh with seams, sharp edges, crease, or bevel-weight, bounded by user-chosen barrier edges. Hover an edge (Direction mode) or click two vertices (Build mode) to preview a path, tune it with flow/smooth/curvature/arch wheel modifiers, then commit. Also provides a one-shot "mark by angle" pass and a separate sub-mode that re-routes already-marked chains through smoother neighbours.

<div class="iops-meta" markdown="1">
<span class="key">bl_idname: iops.mesh_uv_shortest_mark</span>
<span class="mode">Mode: Edit Mesh</span>
<span>Context: VIEW_3D</span>
<span class="modal">Modal: yes</span>
<span class="hud">HUD: yes</span>
</div>

## Overview
The operator builds a per-topology graph (CSR adjacency + cached edge lengths, face-angle bias, barrier mask) and runs Dijkstra, A*, or a greedy edge-loop walk over it. A native Rust extension (`mesh_uv_shortest_mark_lib`) is used when present, with a Python fallback. The path can be steered by:

- Barrier edges (Seam / Sharp / Crease / Bevel Weight) which the search refuses to cross.
- Flow angle — caps the directional change between successive edges.
- Curvature — biases the search toward convex or concave creases.
- Smooth — a shortcut-based post-pass that tries to replace short sub-segments with shorter alternates.
- Arch (Build mode only) — deforms the baseline path into a perpendicular-pushed arc using interior waypoints.

Two path modes coexist: **Direction** projects an arm forward from the hovered edge until it hits a barrier; **Build** chains anchor-to-target hops, committing on each click. A separate "Smooth Marked" sub-mode (F) recomputes all currently marked chains under a stronger smoothing window and previews the diff before commit.

A `TRIANGULATE` modifier on the active object, if present, is temporarily hidden during the modal so raycasts hit the original geometry; it is restored on exit.

## Usage
- Active object must be a mesh in Edit Mode.
- No default keymap binding (the entry in `hotkeys_default.py` uses the `F19` placeholder). Invoke via the operator search or any user-assigned shortcut/menu entry.
- On invoke, **Build** mode is forced as the default regardless of the saved scene property.
- Direction mode: hover an edge, scroll/keys to tune, LMB to apply.
- Build mode: LMB once to set an anchor, hover to preview the path to the closest face vertex, LMB again to apply marks and chain the anchor forward to that vertex. Press `Q` to drop the anchor and start a fresh chain.

Persistent settings (barrier type, mark type, algorithm, flow, sharp angle, smooth level, path mode index, curvature) are stored on `scene.IOPS` on `Space`/`Esc`.

## Modal Controls

| Key | Action |
| --- | --- |
| <kbd>MouseMove</kbd> | Raycast and update hovered edge / target vertex and preview path |
| <kbd>LMB</kbd> | Direction: apply marks to preview path. Build: set anchor (first click) or apply + chain (second click) |
| <kbd>E</kbd> | Cycle barrier type (Seam → Sharp → Crease → Bevel Weight) |
| <kbd>R</kbd> | Cycle mark type (same enum as barrier) |
| <kbd>A</kbd> | Cycle algorithm (Dijkstra → A* → Edge Loop) |
| <kbd>Q</kbd> | New mark — clear Build-mode anchor |
| <kbd>Ctrl</kbd>+<kbd>Q</kbd> | Toggle path mode (Direction ↔ Build) |
| <kbd>S</kbd> | Mark / unmark every edge whose dihedral exceeds the current sharp-angle threshold (toggles each press) |
| <kbd>D</kbd> | Clear marks of the current mark type along the preview path |
| <kbd>F</kbd> | Enter Smooth Marked sub-mode |
| <kbd>Ctrl</kbd>+<kbd>Wheel</kbd> | Adjust flow angle (0–180°, step 5) |
| <kbd>Shift</kbd>+<kbd>Wheel</kbd> | Adjust smooth level (0–10, step 1) |
| <kbd>Alt</kbd>+<kbd>Wheel</kbd> | Adjust sharp-angle threshold (0–180°, step 5; also resets the angle-mark toggle state) |
| <kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>Wheel</kbd> | Adjust curvature bias (−100…+100, step 10) |
| <kbd>Ctrl</kbd>+<kbd>Alt</kbd>+<kbd>Wheel</kbd> | Adjust arch strength (−10…+10, step 1; Build mode) |
| <kbd>MMB</kbd> / <kbd>Wheel</kbd> (unmodified) | Pass through to viewport navigation |
| <kbd>Ctrl</kbd>+<kbd>Z</kbd> | Pop one undo step, invalidate graph cache, redraw preview |
| <kbd>H</kbd> | Toggle HUD / help overlay (handled by shared HUD layer) |
| <kbd>Space</kbd> / <kbd>Enter</kbd> / <kbd>NumpadEnter</kbd> | Finish (saves scene props) |
| <kbd>Esc</kbd> | Cancel (also saves scene props) |

Smooth Marked sub-mode (entered with <kbd>F</kbd>):

| Key | Action |
| --- | --- |
| <kbd>Alt</kbd>+<kbd>Wheel</kbd> | Magnet (−10…+10) — maps to curvature bias for the re-route |
| <kbd>Shift</kbd>+<kbd>Wheel</kbd> | Iteration count (1…100) |
| <kbd>Space</kbd> / <kbd>Enter</kbd> / <kbd>NumpadEnter</kbd> | Accept proposal (clears dropped marks, applies new marks) |
| <kbd>F</kbd> / <kbd>Esc</kbd> | Cancel sub-mode without committing |
| <kbd>MMB</kbd> / <kbd>Wheel</kbd> / <kbd>MouseMove</kbd> | Pass through to viewport navigation |

All other keys are swallowed while the sub-mode is active.

## HUD
The HUD overlay (`uv_shortest_mark`) and the status bar both show the live parameter set:

- Barrier → Mark labels, current algorithm, path mode.
- Flow angle, smooth level, curvature, arch, sharp angle, current path edge count.
- In Smooth Marked sub-mode the header switches to magnet / iteration / proposal-vs-original edge counts.

3D viewport draw layers (depth test forced to `ALWAYS`):

- Path edges — cyan, width 3.
- Hover highlight — yellow (edge in Direction mode, point in Build mode), width 4 / size 10.
- Barrier edges adjacent to path vertices — red, width 2.5.
- Build-mode anchor — green dot, size 10.
- Smooth preview: proposed edges in amber (width 3.5), edges being dropped in faded red (width 2).

A help overlay (`H` toggle) lists every shortcut above.

## Notes
- The graph cache (edge lengths, face-angle bias, CSR adjacency, native graph handle) is keyed on `(len(bm.edges), len(bm.verts))`. Changing topology mid-modal invalidates it; an explicit `Ctrl+Z` also invalidates it.
- The barrier mask is cached separately and rebuilt when the barrier type changes or marks are committed.
- Path size is hard-capped at `MAX_PATH_EDGES = 50000`.
- A* falls back to Dijkstra when no target vertex is set (Direction mode).
- `_apply_mark` lazily creates the `crease_edge` / `bevel_weight_edge` float layers when first needed.
- Each mark / clear / angle-mark / smooth commit pushes its own `ed.undo_push` so individual steps can be rolled back.
- Operator commits are normal Blender undo steps; `bl_options = {'REGISTER', 'UNDO'}`.

## Related
- [Quick Connect](op_mesh_quick_connect.md)
- [Visual UV](op_mesh_visual_uv.md)
- [Tris to Quads](op_mesh_to_tris_to_quad.md)
