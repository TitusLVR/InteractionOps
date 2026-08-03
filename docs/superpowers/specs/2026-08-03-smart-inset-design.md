# Smart Inset — Design

**Date:** 2026-08-03
**Status:** Approved for planning

## Problem

Blender's native `mesh.inset_faces` produces garbage geometry when the inset
thickness exceeds what the region can hold: on narrow faces, sharp corners,
and long thin polygons the opposite inset walls cross each other and the
result self-intersects. There is no clamp, no merge, no feedback — the user
has to eyeball the safe thickness and clean up by hand.

## Goal

A modal operator `iops.mesh_smart_inset` ("Smart Inset") that behaves like
native inset for small thickness, and stays *correct* for any thickness:

- **Collapse-merge (default):** where inset walls meet, front vertices merge
  into medial-axis seams — the inset degenerates gracefully into a clean
  variable-width result (narrow parts collapse to an edge, wide parts keep
  growing). No self-intersections at any thickness.
- **Clamp (toggle):** thickness stops at the maximum collision-free value,
  like bevel's `clamp_overlap`.
- Region + individual modes, negative thickness = outset, depth (extrude
  along normal) in the same modal.
- Interactive on typical hard-surface selections (tens–hundreds of faces in
  the selection, meshes up to ~1M polys): all heavy computation happens once
  at modal start; every mouse tick is pure playback.

## Non-goals (YAGNI)

- Smart collapse for **outset** — negative thickness runs a naive outward
  offset (native-like), no skeleton events. Skeleton-based outset is a
  possible future extension.
- Exact geodesic offsets on strongly curved surfaces — the wavefront runs in
  local tangent planes (see below); on hard-surface geometry this is
  accurate, on organic blobs it is an approximation and that is accepted.
- Per-region thickness variation, edge-rail insets, profile shapes.

## Core algorithm: wavefront timeline (simplified straight skeleton)

### Setup (once, in `invoke`)

1. Collect selected faces, split into connected **regions**
   (region mode: each connected component = one wavefront;
   individual mode: every face = its own single-face region, strictly 2D
   in the face plane — the most robust case).
2. For each region, extract its boundary loops (outer loop + hole loops).
3. Each boundary vertex gets a velocity: direction = bisector of its two
   adjacent boundary edges in the vertex's averaged tangent plane; speed =
   `1/sin(θ/2)` where θ is the interior angle, so that the perpendicular
   distance from the original boundary equals `t` (even offset).
   Front vertex position is linear between events: `P(t) = P0 + V·t`.
4. Compute the full **event timeline** with a priority queue until every
   front dies:
   - **Edge collapse:** a front edge shrinks to a point (adjacent front
     vertices meet). Time solved from a linear equation. The two vertices
     merge; the merged vertex gets a recomputed bisector/speed; neighbouring
     event times are updated.
   - **Split:** a reflex vertex (interior angle > 180°) hits an opposite
     front edge; the front splits into two independent loops. Time is a
     quadratic (moving point vs. moving edge), solved in closed form.
   - Simultaneous events (equal `t`, e.g. a square collapsing to a point)
     are processed as a batch, order-independent.

### Non-planarity

The wavefront does not live in a single plane: each vertex moves in the
averaged tangent plane of its adjacent region faces, and after displacement
the position is pulled back onto the region surface (projection onto the
nearest region face, shrinkwrap-style). Event times are computed in a local
2D unfolding of adjacent face pairs. Accurate for hard-surface (near-planar
regions, chamfers, mildly curved shells); approximate on strongly curved
surfaces by design.

### Playback (every mouse tick, and on confirm)

- Take the timeline prefix with event time `< t`; the post-event front
  topology is already known.
- Live vertices: `P0 + V·t` (+ surface pull).
- **Clamp mode** = `t_max` is the first event time; `t` never exceeds it.

### Applying to bmesh (confirm / `execute`)

- Live front vertices → new BMVerts.
- Walls: one quad per surviving boundary edge; triangles/fans where merges
  happened along the way.
- Vertices that died in events before `t` produce the medial-axis **seam**
  vertices — walls from both sides meet in shared edges (the clean
  collapse-merge result).
- Interior faces of the region are rebuilt against the new front contour;
  interior topology survives only where the front has not consumed it.
- Depth: after inset, translate front vertices along the averaged region
  normal by `depth`.

## Architecture

New files:

- **`operators/mesh_smart_inset_core.py`** — pure Python, no `bpy`.
  Input: bare coordinates + boundary connectivity. Output: event timeline +
  `playback(t)` → front positions/topology. Unit-testable with pytest
  without Blender.
- **`operators/mesh_smart_inset.py`** — the operator:
  - *Bridge:* bmesh regions → core input; core output → bmesh mutation.
  - *Modal/UI:* HUD, GPU preview, input handling, redo-panel `execute()`.

Follows the `mesh_straight_bevel.py` patterns: `invoke` builds caches,
`HUDOverlay`/`HelpOverlay`, `safe_handler_add` + `_purge_handles`, numeric
input parser, `REGISTER | UNDO` with property-driven `execute()`.

## Modal UX

| Input | Action |
|---|---|
| Mouse X | Thickness (sensitivity from average region size; Shift = precise ×0.1) |
| Digits / `.` / `-` / Backspace | Numeric thickness input |
| `Ctrl` + mouse | Depth (release Ctrl → back to thickness) |
| `I` | Region ↔ Individual (timelines rebuilt on the fly) |
| `C` | Collapse-merge ↔ Clamp |
| `B` | Boundary toggle: treat open mesh borders as inset boundary |
| `H` | HUD / Help toggle |
| LMB / Enter | Confirm |
| RMB / Esc | Cancel |

Negative thickness (mouse past zero or typed `-`) = outset; no separate key.

**HUD:** title "Smart Inset"; params: Thickness (live float), Depth,
Mode (Region/Individual), Collapse (on/off). HelpOverlay with the key table.

**GPU preview:** front contour as themed lines; medial-axis seams (edges
born from events) highlighted in a second colour; in clamp mode, hitting
`t_max` changes the contour colour so it is obvious why the mouse "stopped".

**Redo panel props:** `thickness`, `depth`, `mode`, `use_collapse`,
`use_boundary`.

## Error handling / degenerate cases

- No selected faces → `CANCELLED` + warning.
- Non-manifold region boundary: boundary built from region membership; if a
  loop cannot be assembled unambiguously, that region is skipped with a
  report warning, other regions still work.
- Zero-length boundary edges (< EPS) are virtually collapsed in core before
  wave start; the source mesh is untouched until confirm.
- θ → 0° (spike): speed → ∞ — capped, resolved as an immediate edge
  collapse; no NaNs. θ → 180°: speed is small and finite, fine.
- Simultaneous events processed as an order-independent batch.
- Any exception in `modal` → draw handler removal guaranteed
  (`_purge_handles` pattern); a stuck HUD is unacceptable.

## Testing

1. **Pytest on core** (`tests/operators/test_smart_inset_core.py`, no bpy):
   - timelines on reference shapes: square (collapses to a point at
     t = half-width), 1×4 rectangle (collapses to a medial-axis segment),
     L-shape (split event), star (reflex vertices), polygon with a hole
     (two loops, waves meet);
   - playback invariants: positions continuous in `t`; even-offset invariant
     (perpendicular front-to-boundary distance = `t` before first event);
   - clamp: `t_max` equals the first event time.
2. **Integration smoke via blender-mcp** (FakeOp recipe): build test meshes
   in live Blender, run the operator through `execute()` with fixed props,
   assert vert/face counts, no self-intersections, manifold result.
