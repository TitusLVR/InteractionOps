# Waypoint Direction & Path Smoother — Design

**File:** `operators/mesh_uv_shortest_mark.py`
**Date:** 2026-04-17

## Problem

1. Waypoint paths can loop back on themselves. In `_compute_path_with_waypoints`, each segment is traced independently by `_trace_arm`, so a segment `WP_i → WP_{i+1}` is free to revisit vertices already used by the segment `WP_{i-1} → WP_i`.
2. No way to straighten or smooth the resulting path. Users see micro-zigzags along an otherwise natural direction and have to re-mark manually.

## Goals

1. Waypoints act as directional anchors — the path progresses monotonically through them, never revisiting vertices from earlier segments.
2. A post-process smoother, adjustable via Shift+Scroll, that replaces subpaths with shorter alternatives (shortcut-based).
3. Both features integrate with existing Dijkstra / BFS / EdgeLoop algorithms, barrier enforcement, and waypoint Auto/Chain modes.

## Non-goals

- Changing the non-waypoint direction heuristics (`flow_angle` still governs that).
- Cross-segment flow-direction bias from waypoints (this is a no-revisit design, not a vector-injection design).
- Real-time smoothing during mouse move — smoothing runs as part of `_update_path`, same call path as everything else.

## Design

### Overview

- Add a `forbidden_verts` parameter to every `_trace_arm` variant. `_compute_path_with_waypoints` maintains a running forbidden set across segments so later segments cannot revisit earlier ones.
- Add `_smooth_path(bm, path_edges, forbidden_verts)` which runs shortcut-based straightening, gated by a new `smooth_level` state (0–10).
- Bind Shift+Scroll in `modal()` to adjust `smooth_level`.
- Display `smooth_level` in HUD and status bar. Persist via scene `IOPS` props.

### Component changes

#### Module constants

```
MAX_SMOOTH_LEVEL = 10
SMOOTH_STEP = 1
```

#### `_trace_arm` and variants

Add `forbidden_verts: set[int] | None = None` to:
- `_trace_arm`
- `_dijkstra_arm`
- `_bfs_arm`
- `_edge_loop_arm`

Inside each variant, wherever there is currently `if ov.index in visited: continue`, add a sibling check:
```python
if forbidden_verts is not None and ov.index in forbidden_verts:
    continue
```
`start_vert` and `target_vert` are never added to `forbidden_verts` by callers, so they remain reachable.

#### `_compute_path_with_waypoints`

Rewrite the segment-building loop:

```python
# Chain mode
if self.waypoint_mode == 'CHAIN':
    vertices = [terminal_start] + wp_verts + [terminal_end]
    path_edges = []
    forbidden = set()
    for i in range(len(vertices) - 1):
        seg_start, seg_end = vertices[i], vertices[i + 1]
        if seg_start.index == seg_end.index:
            continue
        seg_forbidden = forbidden - {seg_end.index}
        segment = self._trace_arm(bm, seg_start, target_vert=seg_end,
                                  forbidden_verts=seg_forbidden)
        if not segment:
            return []  # user-confirmed: render empty when unreachable
        segment = self._smooth_path(bm, segment, seg_start, seg_end,
                                    seg_forbidden)
        path_edges.extend(segment)
        # mark all vertices in this segment forbidden for later segments
        forbidden.update(self._segment_verts(bm, segment, seg_start))
    return path_edges
```

Auto mode identical except each permutation rebuilds `forbidden` from scratch, keeps the shortest valid total, and returns `[]` if no permutation produces a complete path.

Helper `_segment_verts(bm, edge_indices, start_vert)` walks the segment edge list (same walk pattern as `_arm_terminal_vert`) and returns the set of all vertex indices visited.

#### `_compute_path` (non-waypoint case)

Also smooth the two arms. Each arm is smoothed between its endpoints (found via the existing `_arm_terminal_vert` helper), then concatenated with `[hovered_edge.index]` as before:

```python
arm_a_end = self._arm_terminal_vert(bm, arm_a, v1)
arm_b_end = self._arm_terminal_vert(bm, arm_b, v2)
arm_a = self._smooth_path(bm, arm_a, v1, arm_a_end, forbidden_verts=None)
arm_b = self._smooth_path(bm, arm_b, v2, arm_b_end, forbidden_verts=None)
```

If `smooth_level == 0`, `_smooth_path` returns the input unchanged.

#### `_smooth_path(bm, edges, start_vert, end_vert, forbidden_verts)`

```
if smooth_level == 0 or len(edges) < 3: return edges

window = smooth_level + 1  # k=1..10 → window 2..11
verts = walk(edges, start_vert)  # [start, v1, v2, ..., end]

# One pass, left-to-right greedy shortcut
i = 0
out_edges = []
while i < len(verts) - 1:
    best_j = i + 1
    best_sub = [edges[i]]
    best_len = bm.edges[edges[i]].calc_length()
    for j in range(i + 2, min(i + window + 1, len(verts))):
        # vertices strictly between i and j are allowed to be replaced;
        # vertices strictly before i or strictly after j are forbidden
        locally_forbidden = (forbidden_verts or set()) | set(
            v.index for k, v in enumerate(verts) if k < i or k > j
        ) - {verts[i].index, verts[j].index}
        alt = self._dijkstra_arm(bm, verts[i], target_vert=verts[j],
                                 forbidden_verts=locally_forbidden)
        if alt and sum_len(alt) < best_len:
            best_j, best_sub, best_len = j, alt, sum_len(alt)
    out_edges.extend(best_sub)
    i = best_j
return out_edges
```

Barrier enforcement comes for free — `_dijkstra_arm` already skips barrier edges. Shortcut uses Dijkstra regardless of the user's current algorithm selection so smoothing is deterministic and length-optimal within its window.

#### `modal()` — Shift+Scroll handler

Add between the existing Ctrl+Scroll and Alt+Scroll handlers:

```python
if event.type in {'WHEELUPMOUSE', 'WHEELDOWNMOUSE'} and event.shift \
   and not event.ctrl and not event.alt:
    if event.type == 'WHEELUPMOUSE':
        self.smooth_level = min(self.smooth_level + SMOOTH_STEP, MAX_SMOOTH_LEVEL)
    else:
        self.smooth_level = max(self.smooth_level - SMOOTH_STEP, 0)
    self._update_path(context)
    self._update_status(context)
    context.area.tag_redraw()
    return {'RUNNING_MODAL'}
```

#### State, HUD, persistence

- Class attribute: `smooth_level = 0`
- Reset in `invoke()` via `_load_scene_props`.
- `_update_status`: add `[Shift+Wheel] Smooth({self.smooth_level})`.
- `_draw_text` lines tuple: add `(f"Smooth: {self.smooth_level}", "Shift+Wheel")` between Mark Angle and Mark by Angle.
- `_save_scene_props` / `_load_scene_props`: add `shortest_mark_smooth_level`.
- `prefs/` (IOPS scene property group): add `shortest_mark_smooth_level: IntProperty(default=0, min=0, max=MAX_SMOOTH_LEVEL)`.

### Data flow

```
mouse move / key / scroll
  → _update_path
      → _compute_path (no waypoints)
          → _trace_arm × 2 (arms)
          → _smooth_path × 2
      OR _compute_path_with_waypoints
          → per segment:
              _trace_arm with forbidden
              _smooth_path with forbidden
          → accumulate forbidden vertices
      → _build_draw_coords / _build_barrier_coords / _build_waypoint_coords
```

### Failure modes

| Case | Behavior |
|---|---|
| Segment unreachable with `forbidden` applied (no fallback) | `_compute_path_with_waypoints` returns `[]`, path renders empty. User sees waypoints but no path, signalling conflict. |
| Auto mode and no permutation produces a complete path | Returns `[]`, same empty-path signal. |
| `smooth_level > 0` but shortcut finds no improvement | `_smooth_path` returns input unchanged. |
| `smooth_level > 0` and shortcut would cross a barrier | Dijkstra skips barriers, so shortcut is never found. Original subpath preserved. |

### Testing plan

Manual (Blender modal, no unit tests exist in this operator):

1. **Baseline path** — hover edge on a cylinder, confirm path still renders without waypoints at `smooth_level=0`.
2. **Waypoint no-revisit, Chain** — place 3 waypoints on a sphere such that old loopback behavior was observable. Confirm no segment revisits an earlier segment's vertex.
3. **Waypoint no-revisit, Auto** — place 3 waypoints in arbitrary order. Confirm chosen permutation produces a non-crossing path and total length is shortest across valid orderings.
4. **Waypoint unreachable** — place waypoints such that forbidden constraints make a segment impossible. Confirm path renders empty, waypoints still visible.
5. **Smoother off → on** — zigzag path at level 0, Shift+ScrollUp 5×, confirm path straightens progressively, edges on a barrier stay respected.
6. **Smoother with waypoints** — place 2 waypoints, Shift+Scroll up. Confirm waypoint vertices stay on the path at every level.
7. **Persistence** — set smooth level, finish with Space, re-invoke, confirm level restored.
8. **Ctrl+Z** — confirm undo still clears waypoints and resets path (existing behavior unchanged).

### Out of scope

- Visualizing the "forbidden" region.
- Per-waypoint direction vectors.
- Smoothing that modifies non-contiguous parts of the path simultaneously (more complex algorithms like simulated annealing).
