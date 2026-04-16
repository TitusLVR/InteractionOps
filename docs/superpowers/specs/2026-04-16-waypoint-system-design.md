# Waypoint System for UV Shortest Path Mark

**Date:** 2026-04-16
**Operator:** `IOPS_OT_Mesh_UV_Shortest_Mark` (`operators/mesh_uv_shortest_mark.py`)

## Overview

Add vertex waypoints to the UV Shortest Path Mark operator. Waypoints act as intermediate routing points that the path algorithm must pass through, giving the user fine-grained control over path shape. Two modes: **AUTO** (algorithm picks optimal visit order) and **CHAIN** (user-defined visit order with numbered preview).

## Data Model

New class-level state on the operator:

```python
waypoints = []          # list of vertex indices, in placement order
waypoint_mode = 'AUTO'  # 'AUTO' or 'CHAIN'
```

Waypoints are transient — they exist only during the modal session. No scene property persistence is needed.

## Controls

| Key | Action |
|-----|--------|
| **Q** | Toggle waypoint on the vertex closest to cursor. If vertex is already a waypoint, remove it. Switches mode to AUTO. |
| **W** | Toggle waypoint on the vertex closest to cursor. If vertex is already a waypoint, remove it. Switches mode to CHAIN. |
| **Ctrl+Q** | Clear all waypoints. |

Pressing Q when in CHAIN mode switches to AUTO (and vice versa for W), preserving existing waypoints.

## Closest Vertex Detection

New helper method `_closest_vert_in_face(context, event, face, obj)`:
- Projects each vertex of the hit face to screen space using `location_3d_to_region_2d`
- Returns the vertex index nearest to the mouse cursor
- Same pattern as the existing `_closest_edge_in_face` method

## Path Computation (Segment-and-Stitch)

### No Waypoints

Current behavior unchanged — two arms traced outward from the hovered edge until barriers are hit.

### With Waypoints

The path is computed as a chain of segments between consecutive vertices. Each segment uses the currently active algorithm (Dijkstra, BFS, or Edge Loop) via `_trace_arm`.

**Terminal vertices:** From the hovered edge, each arm traces outward (away from the edge) until hitting a barrier, just as today. The outermost vertex of each arm becomes the start/end terminal. If an arm is empty (the hovered edge vertex already touches a barrier), that vertex itself is the terminal. The waypoints are inserted between these two terminals.

**AUTO mode (Q):**
1. Determine start and end terminal vertices from the hovered edge.
2. Generate all permutations of the waypoint list (capped at 8 waypoints).
3. For each permutation, compute the path: start → wp1 → wp2 → ... → wpN → end.
4. Each segment is computed by running the active algorithm from vertex A with an early-stop at vertex B.
5. Pick the permutation with the shortest total path length.
6. If waypoints exceed 8, fall back to placement order with an info report.

**CHAIN mode (W):**
1. Determine start and end terminal vertices from the hovered edge.
2. Compute the path in placement order: start → wp1 → wp2 → ... → wpN → end.
3. No permutation search needed.

### Algorithm Adaptation: Target Vertex

`_trace_arm` (and the underlying `_dijkstra_arm`, `_bfs_arm`, `_edge_loop_arm`) gain an optional `target_vert` parameter:
- When `target_vert` is provided, the search stops as soon as that vertex is reached, rather than continuing to a barrier.
- When `target_vert` is `None`, current behavior is preserved (search until barrier).

This is the only change to the existing algorithm implementations.

### New Method: `_compute_path_with_waypoints`

A new method that orchestrates the segment-and-stitch logic:
1. Computes the terminal vertices (path start/end).
2. Builds the ordered waypoint list (auto-permuted or chain-ordered).
3. Calls `_trace_arm` for each consecutive pair of vertices.
4. Concatenates segment results into `path_edge_indices`.

`_compute_path` delegates to this method when `self.waypoints` is non-empty.

## Visualization

### Waypoint Dots

- Color: green `(0.0, 0.8, 0.0, 1.0)`
- Drawn as `POINTS` primitive via `gpu` shader at each waypoint's world-space position
- Point size: 8.0 (visible but not obstructive)
- Depth test: `ALWAYS` (visible through geometry, same as path lines)

### Chain Mode Numbers

- In CHAIN mode only, each waypoint dot gets a number label (1, 2, 3...) drawn next to it
- Uses `blf` text drawing, projected to screen space via `location_3d_to_region_2d`
- Same font styling as the existing HUD (respects addon text preferences)
- Numbers reflect placement order

### AUTO Mode

- Dots only, no numbers (order is computed, not user-defined)

### Draw Callback Changes

The existing `_draw_3d` method gets an additional section after barrier drawing:
1. Collect world-space positions of all waypoint vertices
2. Draw green points
3. If CHAIN mode, project to 2D and draw numbers via `blf` in `_draw_text`

## HUD / Status Updates

### Text HUD (viewport overlay)

Add three new lines to the `lines` tuple in `_draw_text`:

```
("Waypoint Auto", "Q")
("Waypoint Chain", "W")
("Clear Waypoints", "Ctrl+Q")
```

The active mode line should be visually distinguished (e.g., show waypoint count: `"Waypoint Auto (3)"` or `"Waypoint Chain (3)"`).

### Status Bar

Update `_update_status` to include:
```
[Q] Waypoint Auto | [W] Waypoint Chain | [Ctrl+Q] Clear Waypoints
```

Show the active mode and waypoint count.

## Modal Event Handling

New event handlers in `modal()`:

### Q Press (no modifiers)
1. Get the hit face from current raycast state.
2. Call `_closest_vert_in_face` to find nearest vertex.
3. If vertex is already in `self.waypoints`, remove it.
4. Otherwise, append it.
5. Set `self.waypoint_mode = 'AUTO'`.
6. Call `_update_path` and `_update_status`, tag redraw.

### W Press (no modifiers)
Same as Q, but sets `self.waypoint_mode = 'CHAIN'`.

### Ctrl+Q Press
1. Clear `self.waypoints`.
2. Call `_update_path` and `_update_status`, tag redraw.

## Initialization / Cleanup

In `invoke`:
- Initialize `self.waypoints = []` and `self.waypoint_mode = 'AUTO'`

No cleanup needed — waypoints are transient Python lists that go away with the operator instance.

## Edge Cases

- **Waypoint on a barrier vertex:** Allowed. The path will route to that vertex even if it sits on a barrier edge.
- **Hovered edge IS a waypoint edge:** Works normally — the hovered edge is always included in the path, waypoints guide the arms.
- **Waypoint unreachable:** If the algorithm can't reach a waypoint (isolated by barriers), that segment returns an empty path. The remaining segments still compute. The user sees a gap, signaling the waypoint is unreachable.
- **Single waypoint:** AUTO and CHAIN behave identically — path routes through that one vertex.
- **Zero waypoints:** Current behavior, no change.
- **>8 waypoints in AUTO mode:** Falls back to placement order, reports info message to user.

## Files Changed

- `operators/mesh_uv_shortest_mark.py` — all changes are in this single file
