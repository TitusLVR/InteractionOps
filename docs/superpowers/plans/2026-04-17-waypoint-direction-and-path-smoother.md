# Waypoint Direction & Path Smoother Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make waypoints act as directional anchors (no revisits between segments) and add a post-process path smoother adjustable via Shift+Scroll.

**Architecture:** Thread a `forbidden_verts` set through every path-tracing function so earlier segments can block vertices for later segments. Add `_smooth_path` as a post-process that replaces subpaths with shorter Dijkstra shortcuts, gated by a 0–10 `smooth_level` state. Wire Shift+Scroll to adjust the level. All changes are confined to `operators/mesh_uv_shortest_mark.py` with one scene-property addition in `prefs/addon_properties.py`.

**Tech Stack:** Python 3, Blender `bpy` / `bmesh` / `gpu`, existing operator `IOPS_OT_Mesh_UV_Shortest_Mark`.

**Testing Note:** This operator runs inside Blender's modal event loop with live mesh data — there is no pytest suite for it, and the existing waypoint plan ([docs/superpowers/plans/2026-04-16-waypoint-system.md](../plans/2026-04-16-waypoint-system.md)) used manual Blender verification per task. This plan follows the same convention.

---

## File Structure

- **Modify** `operators/mesh_uv_shortest_mark.py`
  - Add module constants (`MAX_SMOOTH_LEVEL`, `SMOOTH_STEP`)
  - Add class attribute `smooth_level`
  - Thread `forbidden_verts` through `_trace_arm` / `_dijkstra_arm` / `_bfs_arm` / `_edge_loop_arm`
  - Add helper `_segment_verts`
  - Add method `_smooth_path`
  - Rewrite `_compute_path_with_waypoints` (no-revisit loop)
  - Wire `_smooth_path` into `_compute_path` and `_compute_path_with_waypoints`
  - Add Shift+Scroll handler in `modal()`
  - Update `_update_status` and `_draw_text`
  - Update `_save_scene_props` / `_load_scene_props`
  - Reset `smooth_level` in `invoke()`
- **Modify** `prefs/addon_properties.py`
  - Add `shortest_mark_smooth_level` IntProperty

---

## Task 1: Add state, constants, and scene property

**Files:**
- Modify: `operators/mesh_uv_shortest_mark.py:28-46` (module constants block)
- Modify: `operators/mesh_uv_shortest_mark.py:78-89` (class attributes block)
- Modify: `operators/mesh_uv_shortest_mark.py:1017-1019` (invoke reset block)
- Modify: `prefs/addon_properties.py:183`

This task only adds plumbing. No behavior change yet — subsequent tasks use the new `smooth_level` state and the `MAX_SMOOTH_LEVEL` / `SMOOTH_STEP` constants.

- [ ] **Step 1: Add module constants**

In [operators/mesh_uv_shortest_mark.py](../../../operators/mesh_uv_shortest_mark.py), locate the constants block that ends with `MAX_AUTO_WAYPOINTS = 8` (around line 46) and append:

```python
MAX_SMOOTH_LEVEL = 10
SMOOTH_STEP = 1
```

- [ ] **Step 2: Add class attribute**

In the class attributes section (right after `_angle_marked = False` on line 89), add:

```python
    smooth_level = 0
```

- [ ] **Step 3: Reset in invoke()**

In `invoke()` around line 1019 (after `self.waypoint_coords = []`), add:

```python
        self.smooth_level = 0
```

This line must appear **before** `self._load_scene_props(context)` so the scene-prop load overrides the default (Task 10 will use this).

- [ ] **Step 4: Add scene property**

In [prefs/addon_properties.py](../../../prefs/addon_properties.py), at line 183 append:

```python
    shortest_mark_smooth_level: IntProperty(name="Smooth Level", default=0, min=0, max=10)
```

Hardcode `max=10` rather than importing `MAX_SMOOTH_LEVEL` — the prefs module is part of Blender's startup path and importing from `operators` would create a cycle.

- [ ] **Step 5: Manual verify**

Launch Blender, enter Edit Mode on a mesh, invoke `iops.mesh_uv_shortest_mark`. Expected: operator runs normally with no visible change. Hover an edge — path still appears.

- [ ] **Step 6: Commit**

```bash
git add operators/mesh_uv_shortest_mark.py prefs/addon_properties.py
git commit -m "feat(waypoints): add smooth_level state and scene property"
```

---

## Task 2: Thread `forbidden_verts` through arm-tracing functions

**Files:**
- Modify: `operators/mesh_uv_shortest_mark.py:186-192` (`_trace_arm`)
- Modify: `operators/mesh_uv_shortest_mark.py:217-276` (`_dijkstra_arm`)
- Modify: `operators/mesh_uv_shortest_mark.py:278-330` (`_bfs_arm`)
- Modify: `operators/mesh_uv_shortest_mark.py:332-386` (`_edge_loop_arm`)

Each arm variant gains an optional `forbidden_verts` parameter. When provided, any edge whose *other vertex* is in the set is skipped (same location where the existing `visited` check lives). No caller passes it yet, so behavior is unchanged.

- [ ] **Step 1: Update `_trace_arm` dispatcher**

Replace the current method (lines 186–192):

```python
    def _trace_arm(self, bm, start_vert, excluded_edge=None, target_vert=None):
        algo = self.algorithm
        if algo == 'DIJKSTRA':
            return self._dijkstra_arm(bm, start_vert, excluded_edge, target_vert)
        if algo == 'BFS':
            return self._bfs_arm(bm, start_vert, excluded_edge, target_vert)
        return self._edge_loop_arm(bm, start_vert, excluded_edge, target_vert)
```

with:

```python
    def _trace_arm(self, bm, start_vert, excluded_edge=None, target_vert=None,
                   forbidden_verts=None):
        algo = self.algorithm
        if algo == 'DIJKSTRA':
            return self._dijkstra_arm(bm, start_vert, excluded_edge, target_vert,
                                      forbidden_verts)
        if algo == 'BFS':
            return self._bfs_arm(bm, start_vert, excluded_edge, target_vert,
                                 forbidden_verts)
        return self._edge_loop_arm(bm, start_vert, excluded_edge, target_vert,
                                   forbidden_verts)
```

- [ ] **Step 2: Update `_dijkstra_arm` signature and filter**

Change the signature (line 217) from:

```python
    def _dijkstra_arm(self, bm, start_vert, excluded_edge=None, target_vert=None):
```

to:

```python
    def _dijkstra_arm(self, bm, start_vert, excluded_edge=None, target_vert=None,
                      forbidden_verts=None):
```

Inside the edge-iteration loop (lines 256–272), immediately after the line `if ov.index in visited: continue` add:

```python
                if forbidden_verts is not None and ov.index in forbidden_verts:
                    continue
```

The full updated inner loop should read:

```python
            for edge in vert.link_edges:
                if excluded_edge is not None and edge.index == excluded_edge.index:
                    continue
                ov = edge.other_vert(vert)
                if ov.index in visited:
                    continue
                if forbidden_verts is not None and ov.index in forbidden_verts:
                    continue
                if self._is_barrier(edge):
                    continue
                if not self._passes_flow(inc_dir, vert, ov):
                    continue
                nd = d + edge.calc_length()
                if ov.index not in dist or nd < dist[ov.index]:
                    dist[ov.index] = nd
                    prev[ov.index] = (vi, edge.index)
                    edge_dir = ov.co - vert.co
                    incoming[ov.index] = edge_dir.normalized() if edge_dir.length > 1e-8 else inc_dir
                    heapq.heappush(heap, (nd, ov.index))
```

- [ ] **Step 3: Update `_bfs_arm` signature and filter**

Change signature (line 278) similarly:

```python
    def _bfs_arm(self, bm, start_vert, excluded_edge=None, target_vert=None,
                 forbidden_verts=None):
```

Inside the edge-iteration loop (lines 312–326), after `if ov.index in visited: continue` add:

```python
                if forbidden_verts is not None and ov.index in forbidden_verts:
                    continue
```

Full updated inner loop:

```python
            for edge in vert.link_edges:
                if excluded_edge is not None and edge.index == excluded_edge.index:
                    continue
                ov = edge.other_vert(vert)
                if ov.index in visited:
                    continue
                if forbidden_verts is not None and ov.index in forbidden_verts:
                    continue
                if self._is_barrier(edge):
                    continue
                if not self._passes_flow(inc_dir, vert, ov):
                    continue
                visited.add(ov.index)
                prev[ov.index] = (vi, edge.index)
                edge_dir = ov.co - vert.co
                incoming[ov.index] = edge_dir.normalized() if edge_dir.length > 1e-8 else inc_dir
                queue.append(ov.index)
```

- [ ] **Step 4: Update `_edge_loop_arm` signature and filter**

Change signature (line 332):

```python
    def _edge_loop_arm(self, bm, start_vert, excluded_edge=None, target_vert=None,
                       forbidden_verts=None):
```

Inside the candidate-filter loop (lines 351–361), after `if ov.index in visited: continue` add the forbidden check. Full updated filter block:

```python
            candidates = []
            for edge in current.link_edges:
                if prev_edge is not None and edge.index == prev_edge.index:
                    continue
                ov = edge.other_vert(current)
                if ov.index in visited:
                    continue
                if forbidden_verts is not None and ov.index in forbidden_verts:
                    continue
                if self._is_barrier(edge):
                    continue
                if not self._passes_flow(prev_dir, current, ov):
                    continue
                candidates.append(edge)
```

- [ ] **Step 5: Manual verify**

Launch Blender, invoke the operator. Paths should work identically to before (no caller passes `forbidden_verts` yet, so this is a pure-refactor task). Switch through all three algorithms (A-key) to confirm none broke.

- [ ] **Step 6: Commit**

```bash
git add operators/mesh_uv_shortest_mark.py
git commit -m "refactor(waypoints): thread forbidden_verts through arm tracing"
```

---

## Task 3: Add `_segment_verts` helper

**Files:**
- Modify: `operators/mesh_uv_shortest_mark.py:401-411` (add new method directly after `_arm_terminal_vert`)

`_segment_verts` walks a list of edge indices from a known start vertex and returns the set of all vertex indices that appear on that segment (including both endpoints). Needed by Task 4 to accumulate forbidden vertices across segments.

- [ ] **Step 1: Add the helper method**

Insert immediately after `_arm_terminal_vert` (after line 411, before `_compute_path_with_waypoints`):

```python
    def _segment_verts(self, bm, edge_indices, start_vert):
        """Walk segment edges and return the set of all vertex indices touched."""
        result = {start_vert.index}
        if not edge_indices:
            return result
        current = start_vert
        bm.edges.ensure_lookup_table()
        for ei in edge_indices:
            edge = bm.edges[ei]
            v1, v2 = edge.verts
            current = v2 if v1.index == current.index else v1
            result.add(current.index)
        return result
```

- [ ] **Step 2: Manual verify**

Unused yet — no runtime check possible. Launch Blender and confirm the operator still loads without syntax errors by invoking it once.

- [ ] **Step 3: Commit**

```bash
git add operators/mesh_uv_shortest_mark.py
git commit -m "feat(waypoints): add _segment_verts helper"
```

---

## Task 4: Rewrite `_compute_path_with_waypoints` to prevent loopbacks

**Files:**
- Modify: `operators/mesh_uv_shortest_mark.py:413-485` (full method replacement)

This task delivers the headline behavior change: waypoint segments can no longer revisit vertices from earlier segments. AUTO mode rebuilds the forbidden set per permutation. When a segment is unreachable under its forbidden set, the whole path returns `[]` (spec-confirmed: no fallback, empty path signals conflict).

- [ ] **Step 1: Replace `_compute_path_with_waypoints`**

Replace the entire method (lines 413–485) with:

```python
    def _compute_path_with_waypoints(self, bm, hovered_edge):
        v1, v2 = hovered_edge.verts

        # Trace arms to find terminal vertices (same as normal path)
        if self._vertex_touches_barrier(v1, hovered_edge):
            arm_a = []
        else:
            arm_a = self._trace_arm(bm, v1, excluded_edge=hovered_edge)

        if self._vertex_touches_barrier(v2, hovered_edge):
            arm_b = []
        else:
            arm_b = self._trace_arm(bm, v2, excluded_edge=hovered_edge)

        terminal_start = self._arm_terminal_vert(bm, arm_a, v1)
        terminal_end = self._arm_terminal_vert(bm, arm_b, v2)

        bm.verts.ensure_lookup_table()
        wp_verts = []
        for vi in self.waypoints:
            if 0 <= vi < len(bm.verts):
                wp_verts.append(bm.verts[vi])

        if not wp_verts:
            arm_a.reverse()
            return arm_a + [hovered_edge.index] + arm_b

        # Build orderings to try
        if self.waypoint_mode == 'CHAIN':
            orderings = [wp_verts]
        elif len(wp_verts) > MAX_AUTO_WAYPOINTS:
            self.report(
                {'INFO'},
                f"Too many waypoints ({len(wp_verts)}) for auto-ordering, "
                f"using placement order",
            )
            orderings = [wp_verts]
        else:
            orderings = list(permutations(wp_verts))

        best_path = None
        best_length = float('inf')

        for ordering in orderings:
            vertices = [terminal_start] + list(ordering) + [terminal_end]
            path_edges = []
            total_length = 0.0
            forbidden = set()
            valid = True

            for i in range(len(vertices) - 1):
                seg_start = vertices[i]
                seg_end = vertices[i + 1]

                if seg_start.index == seg_end.index:
                    continue

                # Allow the target vertex even if it got into forbidden
                # (can happen only if user placed duplicate waypoints; safe guard).
                seg_forbidden = forbidden - {seg_end.index}

                segment = self._trace_arm(
                    bm, seg_start, target_vert=seg_end,
                    forbidden_verts=seg_forbidden,
                )
                if not segment:
                    valid = False
                    break

                for ei in segment:
                    total_length += bm.edges[ei].calc_length()
                path_edges.extend(segment)

                # Mark all vertices on this segment as forbidden for later
                # segments, EXCLUDING seg_end so the next segment can start there.
                seg_verts = self._segment_verts(bm, segment, seg_start)
                seg_verts.discard(seg_end.index)
                forbidden.update(seg_verts)

            if valid and total_length < best_length:
                best_path = path_edges
                best_length = total_length

        return best_path if best_path else []
```

Key differences vs. the old method:
1. `forbidden` set is initialized empty at the start of each ordering attempt.
2. Each segment trace receives `forbidden_verts=forbidden - {seg_end.index}`.
3. After a successful segment, its vertices (minus `seg_end`) join `forbidden`.
4. Failure in any segment invalidates the ordering (same as before), and if no ordering is valid the method returns `[]`.

- [ ] **Step 2: Manual verify — Chain mode, no loopback**

In Blender, enter Edit Mode on a sphere (or any mesh with multiple possible paths). Invoke `iops.mesh_uv_shortest_mark`.

1. Hover an edge. Press **W** over a vertex to place WP1 in Chain mode.
2. Move cursor, press **W** over another vertex to place WP2.
3. Move cursor to hover a third face. Confirm the computed path from start → WP1 → WP2 → end does NOT revisit any vertex.

Compare against the pre-Task-4 behavior: the previous implementation would let the WP1→WP2 segment cross vertices already used by start→WP1. Now it cannot.

- [ ] **Step 3: Manual verify — Auto mode, no loopback**

1. Press **Ctrl+Q** to clear waypoints.
2. Place 3 waypoints via **Q** (Auto mode).
3. Hover a terminal face. Confirm the chosen path has no revisits regardless of which permutation won.

- [ ] **Step 4: Manual verify — unreachable waypoint renders empty**

1. Place waypoints such that every permutation requires a segment to revisit. An easy way: on a thin strip of mesh, place waypoints that sandwich the start such that reaching them in order forces going back through the start.
2. Confirm the path disappears (no edges drawn), but waypoints stay visible.

- [ ] **Step 5: Commit**

```bash
git add operators/mesh_uv_shortest_mark.py
git commit -m "fix(waypoints): prevent loopbacks via per-segment forbidden sets"
```

---

## Task 5: Add `_smooth_path` method

**Files:**
- Modify: `operators/mesh_uv_shortest_mark.py` — insert new method after `_compute_path_with_waypoints` (after current line 485)

`_smooth_path` performs one pass of shortcut-based smoothing. Level 0 returns input unchanged. At level `k`, the window is `k + 1` — for each vertex `v_i`, look ahead up to `window` positions for a shorter Dijkstra path to `v_j` that bypasses intermediate path vertices but respects the outer `forbidden_verts`.

Method is not wired into path computation yet; Tasks 7–8 call it.

- [ ] **Step 1: Insert `_smooth_path`**

Add this method directly after `_compute_path_with_waypoints` (before `_build_draw_coords`):

```python
    def _smooth_path(self, bm, edge_indices, start_vert, end_vert, forbidden_verts=None):
        """Shortcut-based post-process. Returns input unchanged at level 0."""
        if self.smooth_level <= 0 or len(edge_indices) < 2:
            return edge_indices

        # Walk edges to build the ordered vertex list [start, ..., end]
        verts = [start_vert]
        current = start_vert
        bm.edges.ensure_lookup_table()
        for ei in edge_indices:
            edge = bm.edges[ei]
            v1, v2 = edge.verts
            current = v2 if v1.index == current.index else v1
            verts.append(current)

        window = self.smooth_level + 1  # k=1..10 → window 2..11
        outer = forbidden_verts if forbidden_verts is not None else set()

        # Precompute per-edge length for fast subpath length sum
        def subpath_length(edges):
            return sum(bm.edges[ei].calc_length() for ei in edges)

        i = 0
        out_edges = []
        while i < len(verts) - 1:
            # Default: keep the single original edge from verts[i] to verts[i+1]
            best_j = i + 1
            best_sub = [edge_indices[i]]
            best_improvement = 0.0

            # Try shortcuts from verts[i] to verts[j] for j up to i + window.
            # Pick the j with the largest length reduction vs. the original
            # subpath edge_indices[i:j]. Advance by that j.
            for j in range(i + 2, min(i + window + 1, len(verts))):
                original_sub = edge_indices[i:j]
                original_len = subpath_length(original_sub)

                # Forbid: outer forbidden set + all path vertices outside
                # [i, j]. Allow verts[i], verts[j], and any vertex strictly
                # between them (the alternative route may use them).
                locally_forbidden = set(outer)
                for k, v in enumerate(verts):
                    if k < i or k > j:
                        locally_forbidden.add(v.index)
                locally_forbidden.discard(verts[i].index)
                locally_forbidden.discard(verts[j].index)

                alt = self._dijkstra_arm(
                    bm, verts[i], target_vert=verts[j],
                    forbidden_verts=locally_forbidden,
                )
                if not alt:
                    continue
                alt_len = subpath_length(alt)
                if alt_len < original_len:
                    improvement = original_len - alt_len
                    if improvement > best_improvement:
                        best_improvement = improvement
                        best_j = j
                        best_sub = alt

            out_edges.extend(best_sub)
            i = best_j

        return out_edges
```

- [ ] **Step 2: Manual verify**

Unused by callers yet. Launch Blender, invoke the operator, confirm paths still render normally. No behavior change expected.

- [ ] **Step 3: Commit**

```bash
git add operators/mesh_uv_shortest_mark.py
git commit -m "feat(smoother): add _smooth_path shortcut post-process"
```

---

## Task 6: Add Shift+Scroll handler

**Files:**
- Modify: `operators/mesh_uv_shortest_mark.py:1064-1073` (insert new handler before Alt+Scroll)

Mirrors the existing Ctrl+Scroll / Alt+Scroll pattern.

- [ ] **Step 1: Add the handler**

In `modal()`, directly after the Ctrl+Scroll block (ending around line 1062) and before the Alt+Scroll block (starting around line 1065), insert:

```python
        # Shift+Scroll – adjust post-process smooth level
        if event.type in {'WHEELUPMOUSE', 'WHEELDOWNMOUSE'} and event.shift and not event.ctrl and not event.alt:
            if event.type == 'WHEELUPMOUSE':
                self.smooth_level = min(self.smooth_level + SMOOTH_STEP, MAX_SMOOTH_LEVEL)
            else:
                self.smooth_level = max(self.smooth_level - SMOOTH_STEP, 0)
            self._update_path(context)
            self._update_status(context)
            context.area.tag_redraw()
            return {'RUNNING_MODAL'}
```

- [ ] **Step 2: Manual verify**

Invoke the operator, Shift+ScrollUp / Shift+ScrollDown. No visible change yet (smoother isn't called by anything), but the operator must not error. To confirm the value actually moves, add one temporary debug line inside the handler (e.g. `print("smooth:", self.smooth_level)`) during testing, scroll up and down, then **remove it before committing**.

- [ ] **Step 3: Commit**

```bash
git add operators/mesh_uv_shortest_mark.py
git commit -m "feat(smoother): bind Shift+Scroll to smooth_level"
```

---

## Task 7: Wire smoother into non-waypoint `_compute_path`

**Files:**
- Modify: `operators/mesh_uv_shortest_mark.py:169-184` (method body)

The non-waypoint path builds two arms from the hovered edge endpoints out to barriers, then joins them with the hovered edge in the middle. Smooth each arm independently. The hovered edge itself is never smoothed (it defines the exact user intent).

- [ ] **Step 1: Update `_compute_path`**

Replace the method body (lines 169–184):

```python
    def _compute_path(self, bm, hovered_edge):
        if self.waypoints:
            return self._compute_path_with_waypoints(bm, hovered_edge)

        v1, v2 = hovered_edge.verts
        # If start vertex already touches a barrier, arm is empty
        if self._vertex_touches_barrier(v1, hovered_edge):
            arm_a = []
        else:
            arm_a = self._trace_arm(bm, v1, hovered_edge)
        if self._vertex_touches_barrier(v2, hovered_edge):
            arm_b = []
        else:
            arm_b = self._trace_arm(bm, v2, hovered_edge)

        # Smooth each arm between its endpoints
        if arm_a:
            arm_a_end = self._arm_terminal_vert(bm, arm_a, v1)
            arm_a = self._smooth_path(bm, arm_a, v1, arm_a_end, forbidden_verts=None)
        if arm_b:
            arm_b_end = self._arm_terminal_vert(bm, arm_b, v2)
            arm_b = self._smooth_path(bm, arm_b, v2, arm_b_end, forbidden_verts=None)

        arm_a.reverse()
        return arm_a + [hovered_edge.index] + arm_b
```

- [ ] **Step 2: Manual verify — level 0 unchanged**

Invoke the operator with no waypoints. Paths should render identically to before (smooth_level is 0 by default).

- [ ] **Step 3: Manual verify — smoother engages at level > 0**

1. Find a mesh area where the default path has visible micro-zigzag.
2. Shift+ScrollUp a few times. Path should progressively straighten as `smooth_level` rises.
3. Shift+ScrollDown back to 0. Path returns to the raw form.

- [ ] **Step 4: Manual verify — barriers respected**

Mark a seam across the area. Smoothed path must route around it, never across.

- [ ] **Step 5: Commit**

```bash
git add operators/mesh_uv_shortest_mark.py
git commit -m "feat(smoother): apply smoothing to non-waypoint path arms"
```

---

## Task 8: Wire smoother into `_compute_path_with_waypoints`

**Files:**
- Modify: `operators/mesh_uv_shortest_mark.py` — inside the per-segment loop of `_compute_path_with_waypoints` (rewritten in Task 4)

Smooth each segment between its waypoint endpoints. Pass the running `forbidden` set so smoothing can't detour through future-forbidden regions.

- [ ] **Step 1: Update the per-segment loop**

Locate this block inside `_compute_path_with_waypoints` (added in Task 4):

```python
                segment = self._trace_arm(
                    bm, seg_start, target_vert=seg_end,
                    forbidden_verts=seg_forbidden,
                )
                if not segment:
                    valid = False
                    break

                for ei in segment:
                    total_length += bm.edges[ei].calc_length()
                path_edges.extend(segment)
```

Insert a call to `_smooth_path` between the trace and the length summation:

```python
                segment = self._trace_arm(
                    bm, seg_start, target_vert=seg_end,
                    forbidden_verts=seg_forbidden,
                )
                if not segment:
                    valid = False
                    break

                segment = self._smooth_path(
                    bm, segment, seg_start, seg_end,
                    forbidden_verts=seg_forbidden,
                )

                for ei in segment:
                    total_length += bm.edges[ei].calc_length()
                path_edges.extend(segment)
```

The `seg_forbidden` passed to `_smooth_path` is the same set passed to `_trace_arm`, so smoothing respects the same barrier of previously-used vertices.

- [ ] **Step 2: Manual verify — waypoints preserved**

1. Place 2 waypoints via **W** (Chain mode).
2. Shift+ScrollUp to increase smoothing.
3. Confirm that each waypoint vertex still has an edge on each side of it on the path (waypoints stay on the path at every level).

- [ ] **Step 3: Manual verify — segment smoothing doesn't break no-revisit**

1. Place 3 waypoints that produced visible zigzags pre-smoothing.
2. Shift+ScrollUp to level 5+. Confirm path still does not revisit vertices from earlier segments.

- [ ] **Step 4: Manual verify — Auto mode**

Repeat step 2 in Auto mode (**Q** key). Confirm smoothing applies per-segment for the winning permutation.

- [ ] **Step 5: Commit**

```bash
git add operators/mesh_uv_shortest_mark.py
git commit -m "feat(smoother): apply smoothing to each waypoint segment"
```

---

## Task 9: Update HUD and status bar

**Files:**
- Modify: `operators/mesh_uv_shortest_mark.py:791-805` (`_update_status`)
- Modify: `operators/mesh_uv_shortest_mark.py:926-941` (`_draw_text` lines tuple)

Expose `smooth_level` in both displays, matching the existing `Flow` / `Mark Angle` conventions.

- [ ] **Step 1: Update status bar**

In `_update_status` (lines 791–805), replace the `context.workspace.status_text_set(...)` call body:

```python
    def _update_status(self, context):
        bl = BARRIER_LABELS[self.barrier_type]
        ml = BARRIER_LABELS[self.mark_type]
        al = ALGORITHM_LABELS[self.algorithm]
        n = len(self.path_edge_indices)
        wp_n = len(self.waypoints)
        wm = self.waypoint_mode
        context.workspace.status_text_set(
            f"Shortest Path Mark: [E] Barrier({bl}) | [R] Mark({ml}) | "
            f"[A] Algorithm({al}) | [Ctrl+Wheel] Flow({self.flow_angle}°) | "
            f"[Shift+Wheel] Smooth({self.smooth_level}) | "
            f"[S] Mark by Angle | [Alt+Wheel] Angle({self.sharp_angle}°) | "
            f"[Q] WP Auto | [W] WP Chain | WP({wm} {wp_n}) | [Ctrl+Q] Clear WP | "
            f"[LMB] Apply({n} edges) | [D] Clear Path | "
            f"[Ctrl+Z] Undo | [Space] Finish | [Esc] Cancel"
        )
```

- [ ] **Step 2: Update HUD lines**

In `_draw_text` (lines 926–941), insert a new tuple entry in the `lines` sequence. Replace:

```python
        lines = (
            (f"Barrier: {bl}", "E"),
            (f"Mark: {ml}", "R"),
            (f"Algorithm: {al}", "A"),
            (f"Flow: {self.flow_angle}\u00b0", "Ctrl+Wheel"),
            (f"Mark Angle: {self.sharp_angle}\u00b0", "Alt+Wheel"),
            ("Mark by Angle", "S"),
            (f"Waypoint Auto ({wp_n})" if wm == 'AUTO' else "Waypoint Auto", "Q"),
            (f"Waypoint Chain ({wp_n})" if wm == 'CHAIN' else "Waypoint Chain", "W"),
            ("Clear Waypoints", "Ctrl+Q"),
            (f"Apply ({n} edges)", "LMB"),
            ("Clear Path", "D"),
            ("Undo", "Ctrl+Z"),
            ("Finish", "Space"),
            ("Cancel", "Esc"),
        )
```

with:

```python
        lines = (
            (f"Barrier: {bl}", "E"),
            (f"Mark: {ml}", "R"),
            (f"Algorithm: {al}", "A"),
            (f"Flow: {self.flow_angle}\u00b0", "Ctrl+Wheel"),
            (f"Smooth: {self.smooth_level}", "Shift+Wheel"),
            (f"Mark Angle: {self.sharp_angle}\u00b0", "Alt+Wheel"),
            ("Mark by Angle", "S"),
            (f"Waypoint Auto ({wp_n})" if wm == 'AUTO' else "Waypoint Auto", "Q"),
            (f"Waypoint Chain ({wp_n})" if wm == 'CHAIN' else "Waypoint Chain", "W"),
            ("Clear Waypoints", "Ctrl+Q"),
            (f"Apply ({n} edges)", "LMB"),
            ("Clear Path", "D"),
            ("Undo", "Ctrl+Z"),
            ("Finish", "Space"),
            ("Cancel", "Esc"),
        )
```

- [ ] **Step 3: Manual verify**

Invoke the operator. The status bar (bottom of Blender) and the viewport HUD both show "Smooth: 0" / "Shift+Wheel". Scroll Shift+WheelUp — the number updates.

- [ ] **Step 4: Commit**

```bash
git add operators/mesh_uv_shortest_mark.py
git commit -m "feat(smoother): show smooth level in HUD and status bar"
```

---

## Task 10: Persist `smooth_level` across invocations

**Files:**
- Modify: `operators/mesh_uv_shortest_mark.py:809-823` (`_save_scene_props` / `_load_scene_props`)

Mirror the pattern used for `flow_angle` and `sharp_angle`.

- [ ] **Step 1: Update `_save_scene_props`**

Append one line to the method (after line 815):

```python
    def _save_scene_props(self, context):
        props = context.scene.IOPS
        props.shortest_mark_barrier_idx = self.barrier_type_idx
        props.shortest_mark_mark_idx = self.mark_type_idx
        props.shortest_mark_algorithm_idx = self.algorithm_idx
        props.shortest_mark_flow_angle = self.flow_angle
        props.shortest_mark_sharp_angle = self.sharp_angle
        props.shortest_mark_smooth_level = self.smooth_level
```

- [ ] **Step 2: Update `_load_scene_props`**

Append one line (after line 823):

```python
    def _load_scene_props(self, context):
        props = context.scene.IOPS
        self.barrier_type_idx = props.shortest_mark_barrier_idx
        self.mark_type_idx = props.shortest_mark_mark_idx
        self.algorithm_idx = props.shortest_mark_algorithm_idx
        self.flow_angle = props.shortest_mark_flow_angle
        self.sharp_angle = props.shortest_mark_sharp_angle
        self.smooth_level = props.shortest_mark_smooth_level
```

- [ ] **Step 3: Manual verify**

1. Invoke the operator, Shift+ScrollUp to level 5, press **Space** to finish.
2. Invoke again. Confirm the HUD shows "Smooth: 5" (loaded from scene prop).
3. Shift+ScrollDown to 0, press **Esc** to cancel. Re-invoke. Confirm HUD shows 0.

- [ ] **Step 4: Commit**

```bash
git add operators/mesh_uv_shortest_mark.py
git commit -m "feat(smoother): persist smooth_level across invocations"
```

---

## Final integration pass

After all tasks complete, run the Testing plan from the spec, end-to-end:

1. **Baseline path** — no waypoints, level 0. Path renders unchanged.
2. **Waypoint no-revisit, Chain** — 3 waypoints, confirm no loopback.
3. **Waypoint no-revisit, Auto** — 3 waypoints, confirm winner has no loopback.
4. **Waypoint unreachable** — forbidden makes segment impossible, path renders empty.
5. **Smoother off → on** — zigzag at level 0, Shift+ScrollUp 5×, progressive straightening.
6. **Smoother with waypoints** — waypoints stay on path at every level.
7. **Persistence** — finish/cancel + re-invoke restores level.
8. **Ctrl+Z** — undo still clears waypoints and resets path.

If any step fails, go back to the task that introduced the behavior and debug there.
