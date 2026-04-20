# Curvature Bias for Path Selection — Design

**File:** `operators/mesh_uv_shortest_mark.py`
**Date:** 2026-04-20

## Problem

Path selection currently weighs only edge length (Dijkstra, A*), directional alignment (Edge Loop), and a hard per-step turn cutoff (flow angle). For seam/feature marking on hard-surface models, users often want the path to *prefer following ridges and valleys* — edges where adjacent faces form a sharp dihedral — without forcing a hard cutoff. There is no knob for this today.

## Goals

1. Add a single signed integer knob, **Curvature**, range `-10…+10`, default `0` (disabled).
2. Positive values bias path selection toward high-dihedral (ridge/valley) edges; negative values bias toward flat regions.
3. Wire the bias into Dijkstra, A*, and Edge Loop.
4. Keep A* admissible so it still finds optimal paths under the curvature-weighted cost.
5. At curvature `0`, behavior is bit-identical to the current implementation.
6. Persist the value on the scene like the other tuning knobs.

## Non-goals

- Principal-curvature tensor computation (too heavy for a per-hover recompute).
- Affecting the post-process smoother directly — it already calls Dijkstra/A* and will inherit the bias.
- Replacing or softening `flow_angle` (flow stays a hard gate).

## Removed: BFS algorithm

BFS is removed from the algorithm cycle as part of this change — it is too slow for typical meshes and its unweighted nature makes it a poor fit for the curvature term.

- `ALGORITHM_TYPES = ('DIJKSTRA', 'ASTAR', 'EDGE_LOOP')`
- `ALGORITHM_LABELS` trimmed to the three remaining entries.
- `_bfs_arm` deleted; `_trace_arm`'s BFS branch deleted; the `from collections import deque` import deleted.
- A persisted scene value of `shortest_mark_algorithm_idx == 3` (old BFS) is clamped to `0` on load.

## Design

### Constants

```python
MAX_CURVATURE = 10
CURVATURE_STEP = 1
CURVATURE_SCALE = 0.8          # max fractional cost swing at |curvature|=10
EDGE_LOOP_CURV_WEIGHT = 0.5    # weight of curvature term in greedy score
```

### State

Class-level default on `IOPS_OT_Mesh_UV_Shortest_Mark`:

```python
curvature = 0
```

Reset in `invoke` before `_load_scene_props(context)`, consistent with the pattern used by `smooth_level` and `path_mode_idx`.

### Scene persistence

Scene-prop group (lives under `prefs/`) gains:

```python
shortest_mark_curvature: IntProperty(
    name="Curvature",
    default=0, min=-MAX_CURVATURE, max=MAX_CURVATURE,
)
```

Loaded/saved alongside the existing six fields in `_load_scene_props` / `_save_scene_props`. On load, clamp `algorithm_idx` into the new range `[0, len(ALGORITHM_TYPES))` to handle older scenes that stored BFS.

### Cost helper

```python
def _edge_curvature_multiplier(self, edge):
    if self.curvature == 0 or len(edge.link_faces) != 2:
        return 1.0
    d = edge.calc_face_angle(0.0) / math.pi   # [0,1]: 0 flat, 1 sharp
    b = 2.0 * d - 1.0                          # [-1,+1]: positive on ridges
    c = self.curvature / MAX_CURVATURE         # [-1,+1]
    return max(0.1, 1.0 - CURVATURE_SCALE * c * b)
```

- Boundary / non-manifold edges fall back to `1.0` (pure length). They have no defined dihedral.
- Floor of `0.1` keeps weights strictly positive (Dijkstra correctness requirement).
- At max setting the ratio between favored and disfavored edges is `(1 + 0.8) / (1 - 0.8) = 9:1` — strong but not overwhelming; length still matters.

### Dijkstra

Replace

```python
nd = d + edge.calc_length()
```

with

```python
nd = d + edge.calc_length() * self._edge_curvature_multiplier(edge)
```

No other changes.

### A*

Same edge-cost replacement as Dijkstra. Additionally, scale the heuristic by the minimum possible multiplier whenever `curvature != 0` so the heuristic stays admissible under the biased cost:

```python
h_scale = 1.0 - CURVATURE_SCALE if self.curvature != 0 else 1.0
...
h = (ov.co - target_co).length * h_scale
```

Applied both to the initial `h0` and to every push. At `curvature == 0`, `h_scale == 1.0` and behavior is unchanged.

### Edge Loop (greedy)

Replace the `max(candidates, …)` selection with an explicit scoring pass:

```python
if self.curvature != 0:
    c = self.curvature / MAX_CURVATURE
    def score(e):
        ev = (e.other_vert(current).co - current.co).normalized()
        alignment = prev_dir.dot(ev)
        if len(e.link_faces) == 2:
            d = e.calc_face_angle(0.0) / math.pi
            b = 2.0 * d - 1.0
        else:
            b = 0.0
        return alignment + EDGE_LOOP_CURV_WEIGHT * c * b
    best = max(candidates, key=score)
else:
    best = max(candidates, key=lambda e: prev_dir.dot(
        (e.other_vert(current).co - current.co).normalized()
    ))
```

Alignment still dominates in normal use; the curvature term tips near-ties onto the ridge (or off it, for negative values).

### Smoother

No direct changes. `_smooth_path` already calls `_astar_arm` / `_dijkstra_arm`, so shortcut searches automatically honor the curvature bias.

### Modal input

New branch in `modal`, mirroring the other wheel branches:

```python
# Ctrl+Shift+Wheel – adjust curvature bias
if event.type in {'WHEELUPMOUSE', 'WHEELDOWNMOUSE'} \
        and event.ctrl and event.shift and not event.alt:
    if event.type == 'WHEELUPMOUSE':
        self.curvature = min(self.curvature + CURVATURE_STEP, MAX_CURVATURE)
    else:
        self.curvature = max(self.curvature - CURVATURE_STEP, -MAX_CURVATURE)
    self._update_path(context)
    self._update_status(context)
    context.area.tag_redraw()
    return {'RUNNING_MODAL'}
```

### HUD and status line

`_update_status` gains one segment: `| [Ctrl+Shift+Wheel] Curvature({self.curvature})`.

`_draw_text`'s `lines` tuple gains one entry: `(f"Curvature: {self.curvature}", "Ctrl+Shift+Wheel")`, placed next to the Flow / Smooth rows.

## Testing (manual)

1. Beveled cube, curvature `+10`: paths prefer bevel ridges. Curvature `-10`: paths avoid ridges.
2. Ctrl+Shift+Wheel updates HUD and re-previews in real time; value clamps at ±10.
3. Dijkstra / A* / Edge Loop each visibly react at `±5`. BFS is gone from the cycle.
4. At `curvature == 0`, selected paths match pre-change output on a fixed test case.
5. Scene persistence: close/reopen operator, curvature value survives. Scene with stale `algorithm_idx == 3` loads without crash and falls back to Dijkstra.
6. Flow angle and smoother continue to work; smoother shortcuts honor the bias.
