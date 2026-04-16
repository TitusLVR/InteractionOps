# Waypoint System Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add vertex waypoints (Q=auto-order, W=chain-order) to the UV Shortest Path Mark operator so the path routes through user-placed intermediate vertices.

**Architecture:** Segment-and-stitch approach — the path between terminals is split into segments at each waypoint, and each segment is computed using the existing algorithm (Dijkstra/BFS/Edge Loop) with an added `target_vert` early-stop parameter. AUTO mode tries all permutations (capped at 8) to find the shortest total path; CHAIN mode uses placement order.

**Tech Stack:** Blender Python API (bpy, bmesh, gpu, blf), no external dependencies.

**Note:** This is a Blender addon with no automated test framework. Each task includes manual verification steps to run in Blender's Edit Mode.

---

### Task 1: Add imports, constants, and class-level state

**Files:**
- Modify: `operators/mesh_uv_shortest_mark.py:1-82`

- [ ] **Step 1: Add permutations import**

At line 10, after `from collections import deque`, add:

```python
from itertools import permutations
```

- [ ] **Step 2: Add waypoint drawing constants**

After the existing drawing constants block (after line 41, `BARRIER_WIDTH = 2.5`), add:

```python
WAYPOINT_COLOR = (0.0, 0.8, 0.0, 1.0)
WAYPOINT_SIZE = 8.0
MAX_AUTO_WAYPOINTS = 8
```

- [ ] **Step 3: Add class-level waypoint state**

After line 71 (`barrier_coords = []`), add:

```python
    # Waypoints
    waypoints = []
    waypoint_mode = 'AUTO'
    waypoint_coords = []
```

- [ ] **Step 4: Commit**

```bash
git add operators/mesh_uv_shortest_mark.py
git commit -m "feat(waypoints): add imports, constants, and class-level state"
```

---

### Task 2: Add `_closest_vert_in_face` helper

**Files:**
- Modify: `operators/mesh_uv_shortest_mark.py` (after `_closest_edge_in_face` method, around line 463)

- [ ] **Step 1: Add the method**

After the `_closest_edge_in_face` method (after line 463, `return best_idx`), add:

```python
    def _closest_vert_in_face(self, context, event, face, obj):
        region = context.region
        rv3d = context.space_data.region_3d
        mx, my = event.mouse_region_x, event.mouse_region_y

        best_idx = -1
        best_dist = float('inf')

        for vert in face.verts:
            vw = obj.matrix_world @ vert.co
            s = bpy_extras.view3d_utils.location_3d_to_region_2d(
                region, rv3d, vw
            )
            if s:
                d = (Vector((mx, my)) - Vector(s)).length
                if d < best_dist:
                    best_dist = d
                    best_idx = vert.index

        return best_idx
```

- [ ] **Step 2: Commit**

```bash
git add operators/mesh_uv_shortest_mark.py
git commit -m "feat(waypoints): add _closest_vert_in_face helper"
```

---

### Task 3: Adapt algorithms for `target_vert` parameter

This is the core algorithm change. All three algorithms gain an optional `target_vert` parameter. When set, the search stops at that vertex instead of at barrier-touching vertices. `excluded_edge` becomes optional (None for waypoint segments).

**Files:**
- Modify: `operators/mesh_uv_shortest_mark.py` — methods `_vertex_touches_barrier`, `_trace_arm`, `_dijkstra_arm`, `_bfs_arm`, `_edge_loop_arm`

- [ ] **Step 1: Update `_vertex_touches_barrier` to accept optional `excluded_edge`**

Replace the current method (lines 181-188):

```python
    def _vertex_touches_barrier(self, vert, excluded_edge):
        """Return True if any edge connected to vert is a barrier."""
        for edge in vert.link_edges:
            if edge.index == excluded_edge.index:
                continue
            if self._is_barrier(edge):
                return True
        return False
```

With:

```python
    def _vertex_touches_barrier(self, vert, excluded_edge=None):
        """Return True if any edge connected to vert is a barrier."""
        for edge in vert.link_edges:
            if excluded_edge is not None and edge.index == excluded_edge.index:
                continue
            if self._is_barrier(edge):
                return True
        return False
```

- [ ] **Step 2: Update `_trace_arm` signature**

Replace the current method (lines 173-179):

```python
    def _trace_arm(self, bm, start_vert, excluded_edge):
        algo = self.algorithm
        if algo == 'DIJKSTRA':
            return self._dijkstra_arm(bm, start_vert, excluded_edge)
        if algo == 'BFS':
            return self._bfs_arm(bm, start_vert, excluded_edge)
        return self._edge_loop_arm(bm, start_vert, excluded_edge)
```

With:

```python
    def _trace_arm(self, bm, start_vert, excluded_edge=None, target_vert=None):
        algo = self.algorithm
        if algo == 'DIJKSTRA':
            return self._dijkstra_arm(bm, start_vert, excluded_edge, target_vert)
        if algo == 'BFS':
            return self._bfs_arm(bm, start_vert, excluded_edge, target_vert)
        return self._edge_loop_arm(bm, start_vert, excluded_edge, target_vert)
```

- [ ] **Step 3: Update `_dijkstra_arm`**

Replace the current method (lines 204-253):

```python
    def _dijkstra_arm(self, bm, start_vert, excluded_edge):
        self._flow_cos = math.cos(math.radians(self.flow_angle))
        initial_dir = self._initial_dir(start_vert, excluded_edge)

        dist = {start_vert.index: 0.0}
        prev = {}
        incoming = {start_vert.index: initial_dir}
        heap = [(0.0, start_vert.index)]
        visited = set()
        target = None

        while heap:
            d, vi = heapq.heappop(heap)
            if vi in visited:
                continue
            visited.add(vi)
            if len(visited) > MAX_PATH_EDGES:
                break

            vert = bm.verts[vi]

            if vi != start_vert.index and self._vertex_touches_barrier(
                vert, excluded_edge
            ):
                target = vi
                break

            inc_dir = incoming.get(vi, initial_dir)

            for edge in vert.link_edges:
                if edge.index == excluded_edge.index:
                    continue
                ov = edge.other_vert(vert)
                if ov.index in visited:
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

        if target is None and prev:
            target = max(dist, key=dist.get)
        return self._reconstruct(prev, target) if target else []
```

With:

```python
    def _dijkstra_arm(self, bm, start_vert, excluded_edge=None, target_vert=None):
        self._flow_cos = math.cos(math.radians(self.flow_angle))

        if excluded_edge is not None:
            initial_dir = self._initial_dir(start_vert, excluded_edge)
        elif target_vert is not None:
            d = target_vert.co - start_vert.co
            initial_dir = d.normalized() if d.length > 1e-8 else Vector((1, 0, 0))
        else:
            initial_dir = Vector((1, 0, 0))

        dist = {start_vert.index: 0.0}
        prev = {}
        incoming = {start_vert.index: initial_dir}
        heap = [(0.0, start_vert.index)]
        visited = set()
        target = None

        while heap:
            d, vi = heapq.heappop(heap)
            if vi in visited:
                continue
            visited.add(vi)
            if len(visited) > MAX_PATH_EDGES:
                break

            vert = bm.verts[vi]

            if vi != start_vert.index:
                if target_vert is not None:
                    if vi == target_vert.index:
                        target = vi
                        break
                elif self._vertex_touches_barrier(vert, excluded_edge):
                    target = vi
                    break

            inc_dir = incoming.get(vi, initial_dir)

            for edge in vert.link_edges:
                if excluded_edge is not None and edge.index == excluded_edge.index:
                    continue
                ov = edge.other_vert(vert)
                if ov.index in visited:
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

        if target is None and prev:
            target = max(dist, key=dist.get)
        return self._reconstruct(prev, target) if target else []
```

- [ ] **Step 4: Update `_bfs_arm`**

Replace the current method (lines 255-297):

```python
    def _bfs_arm(self, bm, start_vert, excluded_edge):
        self._flow_cos = math.cos(math.radians(self.flow_angle))
        initial_dir = self._initial_dir(start_vert, excluded_edge)

        prev = {}
        incoming = {start_vert.index: initial_dir}
        queue = deque([start_vert.index])
        visited = {start_vert.index}
        target = None

        while queue:
            vi = queue.popleft()
            if len(visited) > MAX_PATH_EDGES:
                break
            vert = bm.verts[vi]

            if vi != start_vert.index and self._vertex_touches_barrier(
                vert, excluded_edge
            ):
                target = vi
                break

            inc_dir = incoming.get(vi, initial_dir)

            for edge in vert.link_edges:
                if edge.index == excluded_edge.index:
                    continue
                ov = edge.other_vert(vert)
                if ov.index in visited:
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

        if target is None and prev:
            target = list(prev)[-1]
        return self._reconstruct(prev, target) if target else []
```

With:

```python
    def _bfs_arm(self, bm, start_vert, excluded_edge=None, target_vert=None):
        self._flow_cos = math.cos(math.radians(self.flow_angle))

        if excluded_edge is not None:
            initial_dir = self._initial_dir(start_vert, excluded_edge)
        elif target_vert is not None:
            d = target_vert.co - start_vert.co
            initial_dir = d.normalized() if d.length > 1e-8 else Vector((1, 0, 0))
        else:
            initial_dir = Vector((1, 0, 0))

        prev = {}
        incoming = {start_vert.index: initial_dir}
        queue = deque([start_vert.index])
        visited = {start_vert.index}
        target = None

        while queue:
            vi = queue.popleft()
            if len(visited) > MAX_PATH_EDGES:
                break
            vert = bm.verts[vi]

            if vi != start_vert.index:
                if target_vert is not None:
                    if vi == target_vert.index:
                        target = vi
                        break
                elif self._vertex_touches_barrier(vert, excluded_edge):
                    target = vi
                    break

            inc_dir = incoming.get(vi, initial_dir)

            for edge in vert.link_edges:
                if excluded_edge is not None and edge.index == excluded_edge.index:
                    continue
                ov = edge.other_vert(vert)
                if ov.index in visited:
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

        if target is None and prev:
            target = list(prev)[-1]
        return self._reconstruct(prev, target) if target else []
```

- [ ] **Step 5: Update `_edge_loop_arm`**

Replace the current method (lines 299-345):

```python
    def _edge_loop_arm(self, bm, start_vert, excluded_edge):
        self._flow_cos = math.cos(math.radians(self.flow_angle))
        path = []
        current = start_vert
        prev_edge = excluded_edge
        visited = {start_vert.index}

        for _ in range(MAX_PATH_EDGES):
            prev_dir = (current.co - prev_edge.other_vert(current).co)
            if prev_dir.length < 1e-8:
                break
            prev_dir = prev_dir.normalized()

            candidates = []
            for edge in current.link_edges:
                if edge.index == prev_edge.index:
                    continue
                ov = edge.other_vert(current)
                if ov.index in visited:
                    continue
                if self._is_barrier(edge):
                    continue
                if not self._passes_flow(prev_dir, current, ov):
                    continue
                candidates.append(edge)

            if not candidates:
                break

            best = max(
                candidates,
                key=lambda e: prev_dir.dot(
                    (e.other_vert(current).co - current.co).normalized()
                ),
            )

            path.append(best.index)
            nv = best.other_vert(current)
            visited.add(nv.index)

            if self._vertex_touches_barrier(nv, excluded_edge):
                break

            prev_edge = best
            current = nv

        return path
```

With:

```python
    def _edge_loop_arm(self, bm, start_vert, excluded_edge=None, target_vert=None):
        self._flow_cos = math.cos(math.radians(self.flow_angle))
        path = []
        current = start_vert
        prev_edge = excluded_edge
        visited = {start_vert.index}

        for _ in range(MAX_PATH_EDGES):
            if prev_edge is not None:
                prev_dir = (current.co - prev_edge.other_vert(current).co)
            elif target_vert is not None:
                prev_dir = (target_vert.co - current.co)
            else:
                prev_dir = Vector((1, 0, 0))
            if prev_dir.length < 1e-8:
                break
            prev_dir = prev_dir.normalized()

            candidates = []
            for edge in current.link_edges:
                if prev_edge is not None and edge.index == prev_edge.index:
                    continue
                ov = edge.other_vert(current)
                if ov.index in visited:
                    continue
                if self._is_barrier(edge):
                    continue
                if not self._passes_flow(prev_dir, current, ov):
                    continue
                candidates.append(edge)

            if not candidates:
                break

            best = max(
                candidates,
                key=lambda e: prev_dir.dot(
                    (e.other_vert(current).co - current.co).normalized()
                ),
            )

            path.append(best.index)
            nv = best.other_vert(current)
            visited.add(nv.index)

            if target_vert is not None:
                if nv.index == target_vert.index:
                    break
            elif self._vertex_touches_barrier(nv, excluded_edge):
                break

            prev_edge = best
            current = nv

        return path
```

- [ ] **Step 6: Verify existing behavior is unchanged**

Open Blender, enter Edit Mode on a mesh with seams/sharp edges. Run the operator (`iops.mesh_uv_shortest_mark`). Verify:
- Hovering edges shows the cyan path as before
- All three algorithms (cycle with A) still work
- Barriers still stop the path correctly
- LMB apply, D clear, S angle mark all work

- [ ] **Step 7: Commit**

```bash
git add operators/mesh_uv_shortest_mark.py
git commit -m "feat(waypoints): add target_vert parameter to all path algorithms"
```

---

### Task 4: Add waypoint path computation

**Files:**
- Modify: `operators/mesh_uv_shortest_mark.py` — add methods after `_reconstruct`, modify `_compute_path`

- [ ] **Step 1: Add `_arm_terminal_vert` helper**

After the `_reconstruct` method (after line 358, `return edges`), add:

```python
    def _arm_terminal_vert(self, bm, arm_edges, start_vert):
        """Walk the arm edge list from start_vert and return the far-end vertex."""
        if not arm_edges:
            return start_vert
        current = start_vert
        bm.edges.ensure_lookup_table()
        for ei in arm_edges:
            edge = bm.edges[ei]
            v1, v2 = edge.verts
            current = v2 if v1.index == current.index else v1
        return current
```

- [ ] **Step 2: Add `_compute_path_with_waypoints` method**

Directly after `_arm_terminal_vert`, add:

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

        # Build valid waypoint vertex list
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
            valid = True

            for i in range(len(vertices) - 1):
                seg_start = vertices[i]
                seg_end = vertices[i + 1]

                if seg_start.index == seg_end.index:
                    continue

                segment = self._trace_arm(
                    bm, seg_start, target_vert=seg_end
                )
                if not segment:
                    valid = False
                    break

                for ei in segment:
                    total_length += bm.edges[ei].calc_length()
                path_edges.extend(segment)

            if valid and total_length < best_length:
                best_path = path_edges
                best_length = total_length

        return best_path if best_path else []
```

- [ ] **Step 3: Modify `_compute_path` to delegate**

Replace the current `_compute_path` method (lines 159-171):

```python
    def _compute_path(self, bm, hovered_edge):
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
        arm_a.reverse()
        return arm_a + [hovered_edge.index] + arm_b
```

With:

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
        arm_a.reverse()
        return arm_a + [hovered_edge.index] + arm_b
```

- [ ] **Step 4: Commit**

```bash
git add operators/mesh_uv_shortest_mark.py
git commit -m "feat(waypoints): add segment-and-stitch waypoint path computation"
```

---

### Task 5: Add waypoint visualization

**Files:**
- Modify: `operators/mesh_uv_shortest_mark.py` — add `_build_waypoint_coords`, update `_update_path`, update `_draw_3d`, update `_draw_text`

- [ ] **Step 1: Add `_build_waypoint_coords` method**

After the `_build_barrier_coords` method (after the line `self.barrier_coords.append((a, b))`), add.

Note: this method takes `context` (not `bm, obj`) and resolves the object itself. This ensures waypoint dots stay visible even when the mouse is not hovering over a mesh (hit_obj is None).

```python
    def _build_waypoint_coords(self, context):
        self.waypoint_coords = []
        if not self.waypoints:
            return
        obj = self.hit_obj if self.hit_obj else context.active_object
        if not obj or obj.type != 'MESH' or obj.mode != 'EDIT':
            return
        try:
            bm = bmesh.from_edit_mesh(obj.data)
            bm.verts.ensure_lookup_table()
            mat = obj.matrix_world
            for vi in self.waypoints:
                if 0 <= vi < len(bm.verts):
                    self.waypoint_coords.append(mat @ bm.verts[vi].co.copy())
        except (ReferenceError, AttributeError, ValueError):
            pass
```

- [ ] **Step 2: Update `_update_path` to build waypoint coords**

In the `_update_path` method, add `self._build_waypoint_coords(context)` call right after the reset block and BEFORE the early-return check. This ensures waypoint coords are always rebuilt even when there's no hovered edge.

Replace the top of `_update_path`:

```python
    def _update_path(self, context):
        self.path_edge_indices = []
        self.path_coords = []
        self.barrier_coords = []

        obj = self.hit_obj
        if not obj or obj.mode != 'EDIT' or self.hovered_edge_index < 0:
            return
```

With:

```python
    def _update_path(self, context):
        self.path_edge_indices = []
        self.path_coords = []
        self.barrier_coords = []

        # Always update waypoint coords (persists even without hovered edge)
        self._build_waypoint_coords(context)

        obj = self.hit_obj
        if not obj or obj.mode != 'EDIT' or self.hovered_edge_index < 0:
            return
```

No changes needed to the except block — waypoint_coords is rebuilt independently at the top.

- [ ] **Step 3: Add waypoint dot drawing to `_draw_3d`**

In the `_draw_3d` method, after the barrier edges drawing block (after `bb.draw(shader)`) and before the hovered edge highlight block, add:

```python
            # Waypoint dots
            if self.waypoint_coords:
                shader.uniform_float("color", WAYPOINT_COLOR)
                gpu.state.point_size_set(WAYPOINT_SIZE)
                gpu.state.depth_test_set('ALWAYS')
                wp_batch = batch_for_shader(
                    shader, 'POINTS', {"pos": self.waypoint_coords}
                )
                wp_batch.draw(shader)
```

- [ ] **Step 4: Add chain mode number labels in `_draw_text`**

In the `_draw_text` method, after the HUD key-line drawing loop (after `y += (tCSize + 5) * uifactor`), add:

```python
        # Draw waypoint chain numbers in 3D viewport
        if self.waypoint_mode == 'CHAIN' and self.waypoint_coords:
            region = context.region
            rv3d = context.space_data.region_3d
            for i, wco in enumerate(self.waypoint_coords):
                s = bpy_extras.view3d_utils.location_3d_to_region_2d(
                    region, rv3d, wco
                )
                if s:
                    blf.color(
                        font_id,
                        WAYPOINT_COLOR[0],
                        WAYPOINT_COLOR[1],
                        WAYPOINT_COLOR[2],
                        WAYPOINT_COLOR[3],
                    )
                    blf.position(font_id, s[0] + 10, s[1] + 10, 0)
                    blf.draw(font_id, str(i + 1))
```

- [ ] **Step 5: Commit**

```bash
git add operators/mesh_uv_shortest_mark.py
git commit -m "feat(waypoints): add waypoint dot and chain number visualization"
```

---

### Task 6: Add HUD lines and status bar updates

**Files:**
- Modify: `operators/mesh_uv_shortest_mark.py` — update `_draw_text` lines tuple, update `_update_status`

- [ ] **Step 1: Update HUD lines in `_draw_text`**

Replace the `lines` tuple in `_draw_text`:

```python
        lines = (
            (f"Barrier: {bl}", "E"),
            (f"Mark: {ml}", "R"),
            (f"Algorithm: {al}", "A"),
            (f"Flow: {self.flow_angle}\u00b0", "Ctrl+Wheel"),
            (f"Mark Angle: {self.sharp_angle}\u00b0", "Alt+Wheel"),
            ("Mark by Angle", "S"),
            (f"Apply ({n} edges)", "LMB"),
            ("Clear Path", "D"),
            ("Undo", "Ctrl+Z"),
            ("Finish", "Space"),
            ("Cancel", "Esc"),
        )
```

With:

```python
        wp_n = len(self.waypoints)
        wm = self.waypoint_mode

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

- [ ] **Step 2: Update status bar in `_update_status`**

Replace the current `_update_status` method:

```python
    def _update_status(self, context):
        bl = BARRIER_LABELS[self.barrier_type]
        ml = BARRIER_LABELS[self.mark_type]
        al = ALGORITHM_LABELS[self.algorithm]
        n = len(self.path_edge_indices)
        context.workspace.status_text_set(
            f"Shortest Path Mark: [E] Barrier({bl}) | [R] Mark({ml}) | "
            f"[A] Algorithm({al}) | [Ctrl+Wheel] Flow({self.flow_angle}°) | "
            f"[S] Mark by Angle | [Alt+Wheel] Angle({self.sharp_angle}°) | "
            f"[LMB] Apply({n} edges) | [D] Clear Path | "
            f"[Ctrl+Z] Undo | [Space] Finish | [Esc] Cancel"
        )
```

With:

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
            f"[S] Mark by Angle | [Alt+Wheel] Angle({self.sharp_angle}°) | "
            f"[Q] WP Auto | [W] WP Chain | WP({wm} {wp_n}) | [Ctrl+Q] Clear WP | "
            f"[LMB] Apply({n} edges) | [D] Clear Path | "
            f"[Ctrl+Z] Undo | [Space] Finish | [Esc] Cancel"
        )
```

- [ ] **Step 3: Commit**

```bash
git add operators/mesh_uv_shortest_mark.py
git commit -m "feat(waypoints): add waypoint HUD lines and status bar info"
```

---

### Task 7: Add modal event handlers and invoke initialization

**Files:**
- Modify: `operators/mesh_uv_shortest_mark.py` — add `_toggle_waypoint` helper, add Q/W/Ctrl+Q handlers in `modal()`, update `invoke()`

- [ ] **Step 1: Add `_toggle_waypoint` helper method**

Add this method before `_update_path` (in the mark execution section, after `_execute_mark_by_angle`):

```python
    def _toggle_waypoint(self, context, event, mode):
        """Add or remove a waypoint at the closest vertex. Set waypoint_mode."""
        if not self.hit_obj or self.hit_face_index < 0:
            return
        obj = self.hit_obj
        if obj.mode != 'EDIT':
            return

        try:
            bm = bmesh.from_edit_mesh(obj.data)
            bm.faces.ensure_lookup_table()
            if self.hit_face_index >= len(bm.faces):
                return
            face = bm.faces[self.hit_face_index]
            vi = self._closest_vert_in_face(context, event, face, obj)
            if vi < 0:
                return
        except (IndexError, AttributeError, ReferenceError):
            return

        if vi in self.waypoints:
            self.waypoints.remove(vi)
        else:
            self.waypoints.append(vi)

        self.waypoint_mode = mode
        self._update_path(context)
        self._update_status(context)
        context.area.tag_redraw()
```

- [ ] **Step 2: Add Q handler in `modal()`**

In the `modal` method, after the "Cycle algorithm" block (after `return {'RUNNING_MODAL'}` for the `A` key), add:

```python
        # Toggle waypoint (Auto mode)
        elif (
            event.type == 'Q'
            and event.value == 'PRESS'
            and not event.ctrl
            and not event.shift
        ):
            self._toggle_waypoint(context, event, 'AUTO')
            return {'RUNNING_MODAL'}
```

- [ ] **Step 3: Add W handler in `modal()`**

Directly after the Q handler, add:

```python
        # Toggle waypoint (Chain mode)
        elif (
            event.type == 'W'
            and event.value == 'PRESS'
            and not event.ctrl
            and not event.shift
        ):
            self._toggle_waypoint(context, event, 'CHAIN')
            return {'RUNNING_MODAL'}
```

- [ ] **Step 4: Add Ctrl+Q handler in `modal()`**

Directly after the W handler, add:

```python
        # Clear all waypoints
        elif (
            event.type == 'Q'
            and event.value == 'PRESS'
            and event.ctrl
            and not event.shift
        ):
            self.waypoints = []
            self._update_path(context)
            self._update_status(context)
            context.area.tag_redraw()
            return {'RUNNING_MODAL'}
```

- [ ] **Step 5: Initialize waypoint state in `invoke`**

In the `invoke` method, after `self._angle_marked = False` (line 779), add:

```python
        self.waypoints = []
        self.waypoint_mode = 'AUTO'
        self.waypoint_coords = []
```

Note: do NOT add `self.waypoint_coords = []` to the MOUSEMOVE else-block — waypoint dots should stay visible even when the cursor leaves the mesh. The `_build_waypoint_coords(context)` call in `_update_path` handles keeping them current.

- [ ] **Step 6: Verify the complete feature in Blender**

Open Blender, enter Edit Mode on a subdivided plane with some seams marked.

1. Run `iops.mesh_uv_shortest_mark`
2. Hover over an edge — cyan path appears (unchanged behavior)
3. Press Q near a vertex — green dot appears at that vertex, path reroutes through it
4. Press Q near another vertex — second green dot, path routes through both (auto-order)
5. Press W near a third vertex — mode switches to CHAIN, numbers 1/2/3 appear next to dots
6. Press Q on an existing waypoint — it gets removed
7. Press Ctrl+Q — all waypoints cleared
8. Cycle algorithms with A — waypoint routing works with all three
9. LMB to apply — edges along waypoint-routed path get marked
10. Space to finish

- [ ] **Step 7: Commit**

```bash
git add operators/mesh_uv_shortest_mark.py
git commit -m "feat(waypoints): add Q/W/Ctrl+Q handlers and invoke init"
```
