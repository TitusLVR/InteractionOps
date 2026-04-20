# Curvature Bias Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a signed `Curvature` knob (-10…+10) that biases path selection toward (or away from) ridge/valley edges in Dijkstra, A*, and Edge Loop; remove the BFS algorithm.

**Architecture:** A cheap per-edge multiplier derived from the edge's face dihedral multiplies the length-based cost in Dijkstra/A* and tips the greedy score in Edge Loop. A* keeps admissibility by scaling its straight-line heuristic by the minimum possible multiplier. BFS is removed entirely as part of the same change.

**Tech Stack:** Blender 4.x Python API (`bpy`, `bmesh`), no external libs. Repo has no test framework; verification is manual in Blender.

**Spec:** [docs/superpowers/specs/2026-04-20-curvature-bias-design.md](../specs/2026-04-20-curvature-bias-design.md)

---

## File map

- Modify: [operators/mesh_uv_shortest_mark.py](../../../operators/mesh_uv_shortest_mark.py) — all logic, state, modal handling, HUD.
- Modify: [prefs/addon_properties.py](../../../prefs/addon_properties.py:179-185) — scene property registration.

No new files. No test files (repo has no test framework).

---

## Task 1: Remove BFS algorithm

**Files:**
- Modify: `operators/mesh_uv_shortest_mark.py` (constants, `_trace_arm`, delete `_bfs_arm`, delete `deque` import)

- [ ] **Step 1: Drop BFS from algorithm tuples**

Edit the constants block near the top:

```python
ALGORITHM_TYPES = ('DIJKSTRA', 'ASTAR', 'EDGE_LOOP')
ALGORITHM_LABELS = {
    'DIJKSTRA': 'Dijkstra',
    'ASTAR': 'A*',
    'EDGE_LOOP': 'Edge Loop',
}
```

- [ ] **Step 2: Remove BFS dispatch from `_trace_arm`**

In `_trace_arm` (around line 203), delete the BFS branch so the method reads:

```python
def _trace_arm(self, bm, start_vert, excluded_edge=None, target_vert=None,
               forbidden_verts=None):
    algo = self.algorithm
    if algo == 'DIJKSTRA':
        return self._dijkstra_arm(bm, start_vert, excluded_edge, target_vert,
                                  forbidden_verts)
    if algo == 'ASTAR':
        return self._astar_arm(bm, start_vert, excluded_edge, target_vert,
                               forbidden_verts)
    return self._edge_loop_arm(bm, start_vert, excluded_edge, target_vert,
                               forbidden_verts)
```

- [ ] **Step 3: Delete `_bfs_arm` method**

Remove the entire `_bfs_arm` method (roughly lines 367–422 in the current file).

- [ ] **Step 4: Remove the `deque` import**

At the top of the file change:

```python
import heapq
from collections import deque
```

to:

```python
import heapq
```

- [ ] **Step 5: Manual smoke test**

Open Blender, enter Edit Mode on a mesh, invoke the operator. Press `A` repeatedly to cycle algorithms — verify the cycle is exactly `Dijkstra → A* → Edge Loop → Dijkstra` with no BFS step. Hover the mouse to confirm each algorithm previews a path.

- [ ] **Step 6: Commit**

```bash
git add operators/mesh_uv_shortest_mark.py
git commit -m "refactor(shortest-mark): remove BFS algorithm"
```

---

## Task 2: Clamp stale `algorithm_idx` on load

**Files:**
- Modify: `operators/mesh_uv_shortest_mark.py` (`_load_scene_props`)

- [ ] **Step 1: Clamp the loaded algorithm index**

In `_load_scene_props` (around line 991), replace:

```python
self.algorithm_idx = props.shortest_mark_algorithm_idx
```

with:

```python
self.algorithm_idx = min(
    max(props.shortest_mark_algorithm_idx, 0),
    len(ALGORITHM_TYPES) - 1,
)
```

- [ ] **Step 2: Manual verify**

Temporarily set `props.shortest_mark_algorithm_idx = 3` via the Python console (`bpy.context.scene.IOPS.shortest_mark_algorithm_idx = 3`), then invoke the operator. Confirm it opens without error and starts on Dijkstra. Reset the prop to `0` afterwards.

- [ ] **Step 3: Commit**

```bash
git add operators/mesh_uv_shortest_mark.py
git commit -m "fix(shortest-mark): clamp stale algorithm_idx on load"
```

---

## Task 3: Add curvature constants and state field

**Files:**
- Modify: `operators/mesh_uv_shortest_mark.py` (constants block, class body, `invoke`)

- [ ] **Step 1: Add the module constants**

After the `MAX_SMOOTH_LEVEL`/`SMOOTH_STEP` lines, add:

```python
MAX_CURVATURE = 10
CURVATURE_STEP = 1
CURVATURE_SCALE = 0.8
EDGE_LOOP_CURV_WEIGHT = 0.5
```

- [ ] **Step 2: Add the class-level default**

In the `IOPS_OT_Mesh_UV_Shortest_Mark` class, next to `smooth_level = 0`, add:

```python
curvature = 0
```

- [ ] **Step 3: Reset curvature in `invoke`**

In `invoke`, in the block that resets per-invocation state (where `self.smooth_level = 0` is set), add:

```python
self.curvature = 0
```

immediately before `self._load_scene_props(context)`.

- [ ] **Step 4: Commit**

```bash
git add operators/mesh_uv_shortest_mark.py
git commit -m "feat(shortest-mark): add curvature state and constants"
```

---

## Task 4: Add scene property and wire save/load

**Files:**
- Modify: `prefs/addon_properties.py:179-185`
- Modify: `operators/mesh_uv_shortest_mark.py` (`_save_scene_props`, `_load_scene_props`)

- [ ] **Step 1: Register the scene property**

In `prefs/addon_properties.py`, immediately after the `shortest_mark_path_mode_idx` line (line 185), add:

```python
    shortest_mark_curvature: IntProperty(name="Curvature", default=0, min=-10, max=10)
```

- [ ] **Step 2: Save curvature in `_save_scene_props`**

Append to `_save_scene_props`:

```python
props.shortest_mark_curvature = self.curvature
```

- [ ] **Step 3: Load curvature in `_load_scene_props`**

Append to `_load_scene_props`:

```python
self.curvature = props.shortest_mark_curvature
```

- [ ] **Step 4: Manual verify**

Restart Blender (so the new property registers), invoke the operator, confirm it starts without error. Don't change curvature yet — we only check that load/save don't crash.

- [ ] **Step 5: Commit**

```bash
git add prefs/addon_properties.py operators/mesh_uv_shortest_mark.py
git commit -m "feat(shortest-mark): persist curvature on scene"
```

---

## Task 5: Implement `_edge_curvature_multiplier`

**Files:**
- Modify: `operators/mesh_uv_shortest_mark.py` (new helper method)

- [ ] **Step 1: Add the helper**

Add this method on `IOPS_OT_Mesh_UV_Shortest_Mark`, placed directly above `_dijkstra_arm`:

```python
def _edge_curvature_multiplier(self, edge):
    if self.curvature == 0 or len(edge.link_faces) != 2:
        return 1.0
    d = edge.calc_face_angle(0.0) / math.pi      # [0, 1]: 0 flat, 1 sharp
    b = 2.0 * d - 1.0                             # [-1, +1]: positive on ridges
    c = self.curvature / MAX_CURVATURE            # [-1, +1]
    return max(0.1, 1.0 - CURVATURE_SCALE * c * b)
```

- [ ] **Step 2: Commit**

```bash
git add operators/mesh_uv_shortest_mark.py
git commit -m "feat(shortest-mark): add curvature multiplier helper"
```

---

## Task 6: Wire curvature into Dijkstra

**Files:**
- Modify: `operators/mesh_uv_shortest_mark.py` (`_dijkstra_arm` cost step)

- [ ] **Step 1: Replace the length term**

In `_dijkstra_arm`, locate:

```python
nd = d + edge.calc_length()
```

Replace with:

```python
nd = d + edge.calc_length() * self._edge_curvature_multiplier(edge)
```

- [ ] **Step 2: Manual verify**

Invoke the operator on a beveled cube (or any mesh with creases). Hover to preview a Dijkstra path. Scroll `Ctrl+Shift+Wheel`… wait — the input binding is added in Task 9. For now, verify the baseline hasn't broken: curvature defaults to `0`, so the multiplier returns `1.0` and paths must look identical to before.

- [ ] **Step 3: Commit**

```bash
git add operators/mesh_uv_shortest_mark.py
git commit -m "feat(shortest-mark): apply curvature bias in Dijkstra"
```

---

## Task 7: Wire curvature into A* (with admissible heuristic)

**Files:**
- Modify: `operators/mesh_uv_shortest_mark.py` (`_astar_arm` cost step and heuristic)

- [ ] **Step 1: Scale the heuristic at init**

In `_astar_arm`, directly after `target_co = target_vert.co`, add:

```python
h_scale = 1.0 - CURVATURE_SCALE if self.curvature != 0 else 1.0
```

Then change:

```python
h0 = (start_vert.co - target_co).length
```

to:

```python
h0 = (start_vert.co - target_co).length * h_scale
```

- [ ] **Step 2: Replace the edge cost**

In the same method, change:

```python
ng = g + edge.calc_length()
```

to:

```python
ng = g + edge.calc_length() * self._edge_curvature_multiplier(edge)
```

- [ ] **Step 3: Scale the heuristic at push**

Change:

```python
h = (ov.co - target_co).length
```

to:

```python
h = (ov.co - target_co).length * h_scale
```

- [ ] **Step 4: Manual verify**

With curvature still at default `0`: hover in Build mode (A* kicks in when a target is known). The previewed path must be identical to pre-change behavior.

- [ ] **Step 5: Commit**

```bash
git add operators/mesh_uv_shortest_mark.py
git commit -m "feat(shortest-mark): apply curvature bias in A* with admissible heuristic"
```

---

## Task 8: Wire curvature into Edge Loop

**Files:**
- Modify: `operators/mesh_uv_shortest_mark.py` (`_edge_loop_arm` selection step)

- [ ] **Step 1: Replace the `best = max(...)` block**

In `_edge_loop_arm`, locate:

```python
best = max(
    candidates,
    key=lambda e: prev_dir.dot(
        (e.other_vert(current).co - current.co).normalized()
    ),
)
```

Replace with:

```python
if self.curvature != 0:
    c = self.curvature / MAX_CURVATURE

    def _score(e):
        ev = (e.other_vert(current).co - current.co).normalized()
        alignment = prev_dir.dot(ev)
        if len(e.link_faces) == 2:
            d = e.calc_face_angle(0.0) / math.pi
            b = 2.0 * d - 1.0
        else:
            b = 0.0
        return alignment + EDGE_LOOP_CURV_WEIGHT * c * b

    best = max(candidates, key=_score)
else:
    best = max(
        candidates,
        key=lambda e: prev_dir.dot(
            (e.other_vert(current).co - current.co).normalized()
        ),
    )
```

- [ ] **Step 2: Manual verify**

Cycle to Edge Loop algorithm (`A` key). With curvature `0`, behavior must match pre-change.

- [ ] **Step 3: Commit**

```bash
git add operators/mesh_uv_shortest_mark.py
git commit -m "feat(shortest-mark): apply curvature bias in Edge Loop"
```

---

## Task 9: Add `Ctrl+Shift+Wheel` modal input

**Files:**
- Modify: `operators/mesh_uv_shortest_mark.py` (`modal`)

- [ ] **Step 1: Insert the new branch**

In `modal`, directly after the `Alt+Scroll – adjust sharp angle threshold` branch (and before the `MIDDLEMOUSE`/pass-through branch), add:

```python
# Ctrl+Shift+Scroll – adjust curvature bias
if event.type in {'WHEELUPMOUSE', 'WHEELDOWNMOUSE'} and event.ctrl and event.shift and not event.alt:
    if event.type == 'WHEELUPMOUSE':
        self.curvature = min(self.curvature + CURVATURE_STEP, MAX_CURVATURE)
    else:
        self.curvature = max(self.curvature - CURVATURE_STEP, -MAX_CURVATURE)
    self._update_path(context)
    self._update_status(context)
    context.area.tag_redraw()
    return {'RUNNING_MODAL'}
```

- [ ] **Step 2: Manual verify**

Invoke the operator. Press `Ctrl+Shift+ScrollUp` → the value should climb by 1 per tick, clamping at +10. `ScrollDown` → drops by 1, clamping at -10. The path preview should visibly re-route at ±5 and ±10 on a mesh with ridges. (The HUD/status label is added in the next task — for now confirm via Python console: `bpy.context.window_manager.operators[-1]` or observe the path change.)

- [ ] **Step 3: Commit**

```bash
git add operators/mesh_uv_shortest_mark.py
git commit -m "feat(shortest-mark): bind Ctrl+Shift+Wheel to curvature"
```

---

## Task 10: HUD + status line entry

**Files:**
- Modify: `operators/mesh_uv_shortest_mark.py` (`_update_status`, `_draw_text`)

- [ ] **Step 1: Extend the status line**

In `_update_status`, update the f-string. Change:

```python
f"[A] Algorithm({al}) | [Ctrl+Wheel] Flow({self.flow_angle}°) | "
f"[Shift+Wheel] Smooth({self.smooth_level}) | "
```

to:

```python
f"[A] Algorithm({al}) | [Ctrl+Wheel] Flow({self.flow_angle}°) | "
f"[Shift+Wheel] Smooth({self.smooth_level}) | "
f"[Ctrl+Shift+Wheel] Curvature({self.curvature}) | "
```

- [ ] **Step 2: Extend the HUD `lines` tuple**

In `_draw_text`, update the `lines` tuple. Insert the Curvature entry directly after the Smooth entry:

```python
lines = (
    (f"Barrier: {bl}", "E"),
    (f"Mark: {ml}", "R"),
    (f"Algorithm: {al}", "A"),
    (f"Flow: {self.flow_angle}\u00b0", "Ctrl+Wheel"),
    (f"Smooth: {self.smooth_level}", "Shift+Wheel"),
    (f"Curvature: {self.curvature}", "Ctrl+Shift+Wheel"),
    (f"Mark Angle: {self.sharp_angle}\u00b0", "Alt+Wheel"),
    ("Mark by Angle", "S"),
    (f"Mode: {pm}", "Q"),
    (clear_anchor_label, "Ctrl+Q"),
    (f"{apply_label} ({n} edges)", "LMB"),
    ("Clear Path", "D"),
    ("Undo", "Ctrl+Z"),
    ("Finish", "Space"),
    ("Cancel", "Esc"),
)
```

- [ ] **Step 3: Manual verify**

Invoke the operator. Confirm the new `Curvature: 0` row appears in the HUD overlay and that `Ctrl+Shift+Wheel` updates it live. Check the bottom-of-screen status text also shows the `Curvature(…)` segment.

- [ ] **Step 4: Commit**

```bash
git add operators/mesh_uv_shortest_mark.py
git commit -m "feat(shortest-mark): display curvature in HUD and status line"
```

---

## Task 11: End-to-end verification

**Files:** none (manual test only)

- [ ] **Step 1: Prepare a test mesh**

Create a new Blender file, add a default cube, enter Edit Mode, beveled a few edges with `Ctrl+B` so the mesh has ridge (high-dihedral) and flat regions.

- [ ] **Step 2: Bias toward ridges**

Invoke the operator. Set curvature to `+10` (`Ctrl+Shift+ScrollUp` ten times). Hover across the cube; the previewed path should visibly run along bevel ridges whenever plausible.

- [ ] **Step 3: Bias toward flat**

Set curvature to `-10`. Previewed paths should avoid bevel ridges and prefer flat quads.

- [ ] **Step 4: Neutral check**

Set curvature to `0`. Paths must match pre-feature behavior (length-only). Cross-check against a branch without this work by flipping to `master` if any doubt.

- [ ] **Step 5: Algorithm coverage**

Cycle algorithms (`A`) at curvature `+5` and `-5`. Dijkstra, A*, and Edge Loop should each produce visibly different paths versus curvature `0`.

- [ ] **Step 6: Persistence**

Set curvature to `+3`, finish the operator with `Space`, re-invoke — the HUD should read `Curvature: 3`. Save the file, reopen, re-invoke — value still `3`.

- [ ] **Step 7: Smoother compatibility**

Set curvature `+5`, smooth level `5`. Confirm paths still preview without error; the smoother's shortcut search inherits the bias via Dijkstra/A*, so smoothed paths should also favor ridges.

- [ ] **Step 8: No-op commit if clean**

If steps 1–7 all pass there is no code change to commit here — this task is verification only. If a bug surfaced, fix it, then commit under the relevant task's scope.
