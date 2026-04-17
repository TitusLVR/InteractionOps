# A* Path-Finding Algorithm — Design

**File:** `operators/mesh_uv_shortest_mark.py`
**Date:** 2026-04-17

## Problem

The operator currently cycles between Dijkstra, Edge-Loop, and BFS via Ctrl+Scroll. Dijkstra is optimal but expands the frontier uniformly in all directions. With waypoints, we always have known endpoints, so a goal-aware search can prune large regions of the mesh.

## Goals

1. Add A* as a 4th algorithm in the Ctrl+Scroll cycle.
2. A* matches Dijkstra's optimality (admissible heuristic) while pruning the frontier toward the target.
3. When no target is known (non-waypoint arm tracing), A* falls back to Dijkstra internally.
4. The smoother can optionally use A* for shortcut search when A* is the active algorithm.

## Non-goals

- Changing Dijkstra, BFS, or Edge-Loop behavior.
- Non-admissible heuristics (no weighting knobs).
- Bidirectional A*.

## Design

### Algorithm list

```python
ALGORITHM_TYPES = ('DIJKSTRA', 'ASTAR', 'EDGE_LOOP', 'BFS')
ALGORITHM_LABELS = {
    'DIJKSTRA': 'Dijkstra',
    'ASTAR': 'A*',
    'EDGE_LOOP': 'Edge Loop',
    'BFS': 'BFS',
}
```

A* slots right after Dijkstra so related algorithms cycle together.

### `_astar_arm`

Mirrors `_dijkstra_arm` with one change: priority queue key is `f = g + h` instead of `g`.

```python
def _astar_arm(self, bm, start_vert, excluded_edge=None, target_vert=None,
               forbidden_verts=None):
    if target_vert is None:
        return self._dijkstra_arm(bm, start_vert, excluded_edge,
                                  target_vert, forbidden_verts)

    target_co = target_vert.co
    # priority queue entries: (f, counter, g, vert_index, prev_edge_index)
    # f = g + h, h = (vert.co - target_co).length
    ...
```

- `g`: accumulated edge length (same as Dijkstra's cost).
- `h`: `(vert.co - target_vert.co).length` in local space (vertex coordinates are already in object space — no matrix transform needed; the heuristic is admissible because straight-line distance ≤ any path length).
- All other behavior identical to `_dijkstra_arm`: barrier skip, `flow_angle` check, `forbidden_verts` check, `excluded_edge` skip, `visited` dedup.

### Dispatcher

`_trace_arm` gets one more branch:

```python
if algo == 'ASTAR':
    return self._astar_arm(bm, start_vert, excluded_edge, target_vert,
                           forbidden_verts)
```

### Smoother

`_smooth_path` currently hardcodes `_dijkstra_arm` for shortcut search. Change to dispatch based on active algorithm:

```python
if self.algorithm == 'ASTAR':
    alt = self._astar_arm(bm, verts[i], target_vert=verts[j],
                          forbidden_verts=locally_forbidden)
else:
    alt = self._dijkstra_arm(bm, verts[i], target_vert=verts[j],
                             forbidden_verts=locally_forbidden)
```

BFS/Edge-Loop stay on Dijkstra for the smoother (length-optimal, deterministic). A* is length-optimal too, so swapping it in is safe.

### Persistence

`algorithm_idx` is already persisted via `_save_scene_props` / `_load_scene_props`. The widened tuple means previously saved indices `0..2` still map correctly (Dijkstra=0 stays Dijkstra=0; old index 1 Edge-Loop now maps to A*, old 2 BFS now maps to Edge-Loop). This is a one-time drift on upgrade — acceptable since users re-cycle with Ctrl+Scroll.

### HUD / status

No code changes — both already read from `ALGORITHM_LABELS[self.algorithm]`.

## Failure modes

| Case | Behavior |
|---|---|
| `target_vert is None` | Fall back to Dijkstra. |
| Target unreachable | Queue drains, returns `[]` (same as Dijkstra). |
| `forbidden_verts` blocks all paths | Returns `[]`. |

## Testing plan

Manual (Blender modal):

1. **Cycle** — Ctrl+Scroll: confirm order is Dijkstra → A* → Edge-Loop → BFS → Dijkstra. HUD shows "A*".
2. **A* with waypoint** — place one waypoint, switch to A*, confirm path equals Dijkstra's path (both optimal). Visually verify frontier prunes (optional: log expanded-node count).
3. **A* no target** — no waypoints, A* active, hover an edge. Path should match Dijkstra's (since A* falls back).
4. **A* with barriers** — barrier edge across natural path, confirm A* routes around it like Dijkstra.
5. **Smoother with A*** — A* active, smooth_level > 0, confirm smoother still straightens correctly.
6. **Persistence** — set A*, finish with Space, re-invoke, confirm A* restored.

## Out of scope

- Goal-aware BFS.
- Tunable heuristic weight.
- Visualizing the A* frontier.
