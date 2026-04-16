import bpy
import bmesh
import math
import gpu
from gpu_extras.batch import batch_for_shader
import bpy_extras
import blf
from mathutils import Vector
import heapq
from collections import deque
from itertools import permutations


BARRIER_TYPES = ('SEAM', 'SHARP', 'CREASE', 'BEVEL')
BARRIER_LABELS = {
    'SEAM': 'UV Seam',
    'SHARP': 'Sharp',
    'CREASE': 'Crease',
    'BEVEL': 'Bevel Weight',
}
ALGORITHM_TYPES = ('DIJKSTRA', 'EDGE_LOOP', 'BFS')
ALGORITHM_LABELS = {
    'DIJKSTRA': 'Dijkstra',
    'EDGE_LOOP': 'Edge Loop',
    'BFS': 'BFS',
}

MAX_RAYCAST_ITERATIONS = 50
RAYCAST_OFFSET = 0.0001
MAX_PATH_EDGES = 50000
DEFAULT_FLOW_ANGLE = 180
FLOW_STEP = 5
DEFAULT_SHARP_ANGLE = 30
SHARP_ANGLE_STEP = 5

# Drawing
PATH_COLOR = (0.0, 1.0, 1.0, 1.0)
PATH_WIDTH = 3.0
HOVER_COLOR = (1.0, 1.0, 0.0, 1.0)
HOVER_WIDTH = 4.0
BARRIER_COLOR = (1.0, 0.2, 0.2, 0.8)
BARRIER_WIDTH = 2.5

WAYPOINT_COLOR = (0.0, 0.8, 0.0, 1.0)
WAYPOINT_SIZE = 8.0
MAX_AUTO_WAYPOINTS = 8


class IOPS_OT_Mesh_UV_Shortest_Mark(bpy.types.Operator):
    bl_idname = "iops.mesh_uv_shortest_mark"
    bl_label = "UV Shortest Path Mark"
    bl_description = (
        "Interactive shortest path edge marking bounded by barrier edges. "
        "E-cycle barrier type, R-cycle mark type, A-cycle algorithm, LMB-apply"
    )
    bl_options = {'REGISTER', 'UNDO'}

    # Draw handlers
    _handle = None
    _handle_text = None
    _timer = None

    # Triangulate modifier state
    _tri_mod = None
    _tri_mod_show_viewport = None

    # Raycast state
    hit_obj = None
    hit_face_index = -1
    hovered_edge_index = -1
    _current_mouse_coord = (0, 0)

    # Path
    path_edge_indices = []
    path_coords = []
    barrier_coords = []

    # Waypoints
    waypoints = []
    waypoint_mode = 'AUTO'
    waypoint_coords = []

    # Settings indices
    barrier_type_idx = 0
    mark_type_idx = 0
    algorithm_idx = 0
    flow_angle = DEFAULT_FLOW_ANGLE
    sharp_angle = DEFAULT_SHARP_ANGLE
    _angle_marked = False

    # Cached BMesh layers
    _crease_layer = None
    _bevel_layer = None

    # ─── Properties ──────────────────────────────────────────────────

    @property
    def barrier_type(self):
        return BARRIER_TYPES[self.barrier_type_idx]

    @property
    def mark_type(self):
        return BARRIER_TYPES[self.mark_type_idx]

    @property
    def algorithm(self):
        return ALGORITHM_TYPES[self.algorithm_idx]

    @classmethod
    def poll(cls, context):
        return (
            context.active_object is not None
            and context.active_object.type == 'MESH'
            and context.active_object.mode == 'EDIT'
        )

    # ─── Barrier / Mark helpers ──────────────────────────────────────

    def _is_barrier(self, edge):
        bt = self.barrier_type
        if bt == 'SEAM':
            return edge.seam
        if bt == 'SHARP':
            return not edge.smooth
        if bt == 'CREASE':
            if self._crease_layer is not None:
                return edge[self._crease_layer] > 0.0
            return False
        if bt == 'BEVEL':
            if self._bevel_layer is not None:
                return edge[self._bevel_layer] > 0.0
            return False
        return False

    def _apply_mark(self, edge, bm):
        mt = self.mark_type
        if mt == 'SEAM':
            edge.seam = True
        elif mt == 'SHARP':
            edge.smooth = False
        elif mt == 'CREASE':
            if self._crease_layer is None:
                self._crease_layer = bm.edges.layers.float.new("crease_edge")
            edge[self._crease_layer] = 1.0
        elif mt == 'BEVEL':
            if self._bevel_layer is None:
                self._bevel_layer = bm.edges.layers.float.new("bevel_weight_edge")
            edge[self._bevel_layer] = 1.0

    def _clear_mark(self, edge, bm):
        mt = self.mark_type
        if mt == 'SEAM':
            edge.seam = False
        elif mt == 'SHARP':
            edge.smooth = True
        elif mt == 'CREASE':
            if self._crease_layer is not None:
                edge[self._crease_layer] = 0.0
        elif mt == 'BEVEL':
            if self._bevel_layer is not None:
                edge[self._bevel_layer] = 0.0

    def _cache_layers(self, bm):
        self._crease_layer = bm.edges.layers.float.get("crease_edge")
        self._bevel_layer = bm.edges.layers.float.get("bevel_weight_edge")

    # ─── Path algorithms ─────────────────────────────────────────────

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

    def _trace_arm(self, bm, start_vert, excluded_edge=None, target_vert=None):
        algo = self.algorithm
        if algo == 'DIJKSTRA':
            return self._dijkstra_arm(bm, start_vert, excluded_edge, target_vert)
        if algo == 'BFS':
            return self._bfs_arm(bm, start_vert, excluded_edge, target_vert)
        return self._edge_loop_arm(bm, start_vert, excluded_edge, target_vert)

    def _vertex_touches_barrier(self, vert, excluded_edge=None):
        """Return True if any edge connected to vert is a barrier."""
        for edge in vert.link_edges:
            if excluded_edge is not None and edge.index == excluded_edge.index:
                continue
            if self._is_barrier(edge):
                return True
        return False

    def _initial_dir(self, start_vert, excluded_edge):
        other = excluded_edge.other_vert(start_vert)
        d = start_vert.co - other.co
        return d.normalized() if d.length > 1e-8 else Vector((1, 0, 0))

    def _passes_flow(self, incoming_dir, vert, other_vert):
        if self.flow_angle >= 180:
            return True
        outgoing = other_vert.co - vert.co
        if outgoing.length < 1e-8:
            return True
        dot = incoming_dir.dot(outgoing.normalized())
        return dot >= self._flow_cos

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

    @staticmethod
    def _reconstruct(prev, target):
        if target is None:
            return []
        edges = []
        cur = target
        while cur in prev:
            pv, ei = prev[cur]
            edges.append(ei)
            cur = pv
        edges.reverse()
        return edges

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

    # ─── Draw coordinate builders ────────────────────────────────────

    def _build_draw_coords(self, bm, obj):
        self.path_coords = []
        mat = obj.matrix_world
        bm.edges.ensure_lookup_table()
        for ei in self.path_edge_indices:
            if 0 <= ei < len(bm.edges):
                e = bm.edges[ei]
                a = mat @ e.verts[0].co.copy()
                b = mat @ e.verts[1].co.copy()
                self.path_coords.append((a, b))

    def _build_barrier_coords(self, bm, obj):
        """Collect all barrier edges touching any vertex on the path."""
        self.barrier_coords = []
        if not self.path_edge_indices:
            return
        mat = obj.matrix_world
        path_edge_set = set(self.path_edge_indices)
        seen = set()

        # Gather every vertex that sits on the path
        path_verts = set()
        for ei in self.path_edge_indices:
            if 0 <= ei < len(bm.edges):
                e = bm.edges[ei]
                path_verts.add(e.verts[0].index)
                path_verts.add(e.verts[1].index)

        # For each path vertex, collect adjacent barrier edges
        for vi in path_verts:
            vert = bm.verts[vi]
            for edge in vert.link_edges:
                if edge.index in seen or edge.index in path_edge_set:
                    continue
                if self._is_barrier(edge):
                    seen.add(edge.index)
                    a = mat @ edge.verts[0].co.copy()
                    b = mat @ edge.verts[1].co.copy()
                    self.barrier_coords.append((a, b))

    # ─── Mouse / raycast ─────────────────────────────────────────────

    def _mouse_raycast(self, context, event):
        region = context.region
        rv3d = context.space_data.region_3d
        coord = (event.mouse_region_x, event.mouse_region_y)
        view_vec = bpy_extras.view3d_utils.region_2d_to_vector_3d(
            region, rv3d, coord
        )
        origin = bpy_extras.view3d_utils.region_2d_to_origin_3d(
            region, rv3d, coord
        )
        depsgraph = context.evaluated_depsgraph_get()
        selected = {
            o for o in context.selected_objects if o.type == 'MESH'
        }
        if not selected:
            return False, None, None, None

        cur_origin = origin
        for _ in range(MAX_RAYCAST_ITERATIONS):
            ok, loc, _nrm, fi, obj, mtx = context.scene.ray_cast(
                depsgraph, cur_origin, view_vec
            )
            if not ok:
                return False, None, None, None
            if obj in selected:
                return True, fi, obj, mtx
            if loc:
                cur_origin = loc + view_vec.normalized() * RAYCAST_OFFSET

        return False, None, None, None

    def _closest_edge_in_face(self, context, event, face, obj):
        region = context.region
        rv3d = context.space_data.region_3d
        mx, my = event.mouse_region_x, event.mouse_region_y

        best_idx = -1
        best_dist = float('inf')

        for edge in face.edges:
            v1w = obj.matrix_world @ edge.verts[0].co
            v2w = obj.matrix_world @ edge.verts[1].co
            s1 = bpy_extras.view3d_utils.location_3d_to_region_2d(
                region, rv3d, v1w
            )
            s2 = bpy_extras.view3d_utils.location_3d_to_region_2d(
                region, rv3d, v2w
            )
            if s1 and s2:
                ev = Vector((s2[0] - s1[0], s2[1] - s1[1]))
                mv = Vector((mx - s1[0], my - s1[1]))
                if ev.length > 0:
                    t = max(0.0, min(1.0, mv.dot(ev) / ev.length_squared))
                    proj = Vector(s1) + t * ev
                    d = (Vector((mx, my)) - proj).length
                    if d < best_dist:
                        best_dist = d
                        best_idx = edge.index

        return best_idx

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

    # ─── Mark execution ──────────────────────────────────────────────

    def _execute_mark(self, context):
        if not self.path_edge_indices or not self.hit_obj:
            return
        obj = self.hit_obj
        if obj.mode != 'EDIT':
            return

        bpy.ops.ed.undo_push(message="UV Shortest Path Mark")

        bm = bmesh.from_edit_mesh(obj.data)
        self._cache_layers(bm)
        bm.edges.ensure_lookup_table()
        count = 0
        for ei in self.path_edge_indices:
            if 0 <= ei < len(bm.edges):
                self._apply_mark(bm.edges[ei], bm)
                count += 1
        bmesh.update_edit_mesh(obj.data)
        self.report(
            {'INFO'},
            f"Marked {count} edges as {BARRIER_LABELS[self.mark_type]}",
        )

        self._update_path(context)

    def _execute_clear(self, context):
        """Clear marks of the current mark type from the displayed path edges."""
        if not self.path_edge_indices or not self.hit_obj:
            return
        obj = self.hit_obj
        if obj.mode != 'EDIT':
            return

        bpy.ops.ed.undo_push(message="Clear Marked Path")

        bm = bmesh.from_edit_mesh(obj.data)
        self._cache_layers(bm)
        bm.edges.ensure_lookup_table()
        count = 0
        for ei in self.path_edge_indices:
            if 0 <= ei < len(bm.edges):
                self._clear_mark(bm.edges[ei], bm)
                count += 1
        bmesh.update_edit_mesh(obj.data)
        self.report(
            {'INFO'},
            f"Cleared {count} edges ({BARRIER_LABELS[self.mark_type]})",
        )

        self._update_path(context)

    def _execute_mark_by_angle(self, context):
        """Toggle mark/clear edges using the current mark type based on face angle threshold."""
        obj = self.hit_obj
        if not obj or obj.mode != 'EDIT':
            obj = context.active_object
        if not obj or obj.type != 'MESH' or obj.mode != 'EDIT':
            self.report({'WARNING'}, "No mesh in Edit Mode")
            return

        clearing = self._angle_marked
        mark_label = BARRIER_LABELS[self.mark_type]
        action = "Clear" if clearing else "Mark"
        bpy.ops.ed.undo_push(message=f"{action} {mark_label} by Angle")

        bm = bmesh.from_edit_mesh(obj.data)
        self._cache_layers(bm)
        bm.edges.ensure_lookup_table()
        threshold = math.radians(self.sharp_angle)
        count = 0

        for edge in bm.edges:
            if len(edge.link_faces) == 2:
                angle = edge.calc_face_angle(0.0)
                if angle > threshold:
                    if clearing:
                        self._clear_mark(edge, bm)
                    else:
                        self._apply_mark(edge, bm)
                    count += 1
            elif len(edge.link_faces) < 2:
                if clearing:
                    self._clear_mark(edge, bm)
                else:
                    self._apply_mark(edge, bm)
                count += 1

        self._angle_marked = not clearing
        bmesh.update_edit_mesh(obj.data)
        verb = "Cleared" if clearing else "Marked"
        self.report({'INFO'}, f"{verb} {count} edges as {mark_label} (angle > {self.sharp_angle}°)")
        self._update_path(context)

    # ─── Path update ─────────────────────────────────────────────────

    def _update_path(self, context):
        self.path_edge_indices = []
        self.path_coords = []
        self.barrier_coords = []

        obj = self.hit_obj
        if not obj or obj.mode != 'EDIT' or self.hovered_edge_index < 0:
            return

        try:
            bm = bmesh.from_edit_mesh(obj.data)
            self._cache_layers(bm)
            bm.verts.ensure_lookup_table()
            bm.edges.ensure_lookup_table()
            bm.faces.ensure_lookup_table()

            if self.hovered_edge_index >= len(bm.edges):
                return

            he = bm.edges[self.hovered_edge_index]
            self.path_edge_indices = self._compute_path(bm, he)
            self._build_draw_coords(bm, obj)
            self._build_barrier_coords(bm, obj)

        except (IndexError, AttributeError, ReferenceError, ValueError):
            self.path_edge_indices = []
            self.path_coords = []
            self.barrier_coords = []

    # ─── Status / HUD ────────────────────────────────────────────────

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

    # ─── Scene property persistence ──────────────────────────────────

    def _save_scene_props(self, context):
        props = context.scene.IOPS
        props.shortest_mark_barrier_idx = self.barrier_type_idx
        props.shortest_mark_mark_idx = self.mark_type_idx
        props.shortest_mark_algorithm_idx = self.algorithm_idx
        props.shortest_mark_flow_angle = self.flow_angle
        props.shortest_mark_sharp_angle = self.sharp_angle

    def _load_scene_props(self, context):
        props = context.scene.IOPS
        self.barrier_type_idx = props.shortest_mark_barrier_idx
        self.mark_type_idx = props.shortest_mark_mark_idx
        self.algorithm_idx = props.shortest_mark_algorithm_idx
        self.flow_angle = props.shortest_mark_flow_angle
        self.sharp_angle = props.shortest_mark_sharp_angle

    # ─── Draw callbacks ──────────────────────────────────────────────

    def _draw_3d(self, context):
        try:
            _ = self.path_coords
        except ReferenceError:
            return
        if not context or not context.scene:
            return

        try:
            shader = gpu.shader.from_builtin('UNIFORM_COLOR')
            shader.bind()

            # Path edges
            if self.path_coords:
                coords = []
                for a, b in self.path_coords:
                    coords.extend([a, b])
                shader.uniform_float("color", PATH_COLOR)
                gpu.state.line_width_set(PATH_WIDTH)
                gpu.state.depth_test_set('ALWAYS')
                gpu.state.blend_set('ALPHA')
                batch = batch_for_shader(shader, 'LINES', {"pos": coords})
                batch.draw(shader)

            # Barrier edges on the hovered face
            if self.barrier_coords:
                bcoords = []
                for a, b in self.barrier_coords:
                    bcoords.extend([a, b])
                shader.uniform_float("color", BARRIER_COLOR)
                gpu.state.line_width_set(BARRIER_WIDTH)
                gpu.state.depth_test_set('ALWAYS')
                bb = batch_for_shader(shader, 'LINES', {"pos": bcoords})
                bb.draw(shader)

            # Hovered edge highlight
            if self.hit_obj and self.hovered_edge_index >= 0:
                try:
                    obj = self.hit_obj
                    if obj.mode == 'EDIT':
                        bm = bmesh.from_edit_mesh(obj.data)
                        bm.edges.ensure_lookup_table()
                        if self.hovered_edge_index < len(bm.edges):
                            e = bm.edges[self.hovered_edge_index]
                            a = obj.matrix_world @ e.verts[0].co.copy()
                            b = obj.matrix_world @ e.verts[1].co.copy()
                            shader.uniform_float("color", HOVER_COLOR)
                            gpu.state.line_width_set(HOVER_WIDTH)
                            hb = batch_for_shader(
                                shader, 'LINES', {"pos": [a, b]}
                            )
                            hb.draw(shader)
                except (IndexError, AttributeError, ReferenceError):
                    pass

            gpu.state.line_width_set(1.0)
            gpu.state.depth_test_set('LESS')
            gpu.state.blend_set('NONE')

        except (ReferenceError, AttributeError, ValueError):
            pass

    def _draw_text(self, context):
        try:
            prefs = context.preferences.addons[
                "InteractionOps"
            ].preferences
            tColor = prefs.text_color
            tKColor = prefs.text_color_key
            tCSize = prefs.text_size
            tCPosX = prefs.text_pos_x
            tCPosY = prefs.text_pos_y
            tShadow = prefs.text_shadow_toggle
            tSColor = prefs.text_shadow_color
            tSBlur = prefs.text_shadow_blur
            tSPosX = prefs.text_shadow_pos_x
            tSPosY = prefs.text_shadow_pos_y
        except (KeyError, AttributeError):
            return

        bl = BARRIER_LABELS[self.barrier_type]
        ml = BARRIER_LABELS[self.mark_type]
        al = ALGORITHM_LABELS[self.algorithm]
        n = len(self.path_edge_indices)

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

        uifactor = context.preferences.system.ui_scale
        font_id = 0
        blf.size(font_id, tCSize)

        if tShadow:
            blf.enable(font_id, blf.SHADOW)
            blf.shadow(
                font_id,
                int(tSBlur),
                tSColor[0],
                tSColor[1],
                tSColor[2],
                tSColor[3],
            )
            blf.shadow_offset(font_id, tSPosX, tSPosY)
        else:
            blf.disable(font_id, blf.SHADOW)

        max_w = max(blf.dimensions(font_id, l[0])[0] for l in lines)
        x0 = tCPosX * uifactor
        padding = (tCSize * 2) * uifactor
        right = x0 + max_w + padding + (tCSize * 15) * uifactor
        y = tCPosY

        for action, key in reversed(lines):
            blf.color(
                font_id, tColor[0], tColor[1], tColor[2], tColor[3]
            )
            blf.position(font_id, x0, y, 0)
            blf.draw(font_id, action)

            blf.color(
                font_id, tKColor[0], tKColor[1], tKColor[2], tKColor[3]
            )
            kw = blf.dimensions(font_id, key)[0]
            blf.position(font_id, right - kw, y, 0)
            blf.draw(font_id, key)

            y += (tCSize + 5) * uifactor

    # ─── Invoke / Modal / Cleanup ────────────────────────────────────

    def invoke(self, context, event):
        if context.area.type != 'VIEW_3D':
            self.report({'WARNING'}, "View3D not found")
            return {'CANCELLED'}

        self.hit_obj = None
        self.hit_face_index = -1
        self.hovered_edge_index = -1
        self.path_edge_indices = []
        self.path_coords = []
        self.barrier_coords = []
        self._current_mouse_coord = (0, 0)
        self._angle_marked = False

        self._load_scene_props(context)

        # Disable Triangulate modifier for accurate raycast on original geometry
        self._tri_mod = None
        self._tri_mod_show_viewport = None
        obj = context.active_object
        for mod in obj.modifiers:
            if mod.type == 'TRIANGULATE':
                self._tri_mod = mod
                self._tri_mod_show_viewport = mod.show_viewport
                mod.show_viewport = False
                break

        self._handle = bpy.types.SpaceView3D.draw_handler_add(
            self._draw_3d, (context,), 'WINDOW', 'POST_VIEW'
        )
        self._handle_text = bpy.types.SpaceView3D.draw_handler_add(
            self._draw_text, (context,), 'WINDOW', 'POST_PIXEL'
        )
        self._timer = context.window_manager.event_timer_add(
            0.1, window=context.window
        )

        self._update_status(context)
        context.window_manager.modal_handler_add(self)
        context.area.tag_redraw()
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        if event.type == 'TIMER':
            return {'PASS_THROUGH'}

        # Ctrl+Scroll – adjust flow angle
        if event.type in {'WHEELUPMOUSE', 'WHEELDOWNMOUSE'} and event.ctrl and not event.shift and not event.alt:
            if event.type == 'WHEELUPMOUSE':
                self.flow_angle = min(self.flow_angle + FLOW_STEP, 180)
            else:
                self.flow_angle = max(self.flow_angle - FLOW_STEP, 0)
            self._update_path(context)
            self._update_status(context)
            context.area.tag_redraw()
            return {'RUNNING_MODAL'}

        # Alt+Scroll – adjust sharp angle threshold
        if event.type in {'WHEELUPMOUSE', 'WHEELDOWNMOUSE'} and event.alt and not event.ctrl and not event.shift:
            if event.type == 'WHEELUPMOUSE':
                self.sharp_angle = min(self.sharp_angle + SHARP_ANGLE_STEP, 180)
            else:
                self.sharp_angle = max(self.sharp_angle - SHARP_ANGLE_STEP, 0)
            self._angle_marked = False
            self._update_status(context)
            context.area.tag_redraw()
            return {'RUNNING_MODAL'}

        if event.type in {'MIDDLEMOUSE', 'WHEELUPMOUSE', 'WHEELDOWNMOUSE'}:
            return {'PASS_THROUGH'}

        # Mouse move – update hovered edge and path
        if event.type == 'MOUSEMOVE':
            self._current_mouse_coord = (
                event.mouse_region_x,
                event.mouse_region_y,
            )
            ok, fi, obj, _ = self._mouse_raycast(context, event)
            if ok and obj and obj.type == 'MESH' and obj.mode == 'EDIT':
                self.hit_obj = obj
                self.hit_face_index = fi
                try:
                    bm = bmesh.from_edit_mesh(obj.data)
                    bm.faces.ensure_lookup_table()
                    if fi < len(bm.faces):
                        face = bm.faces[fi]
                        new_idx = self._closest_edge_in_face(
                            context, event, face, obj
                        )
                        if new_idx != self.hovered_edge_index:
                            self.hovered_edge_index = new_idx
                            self._update_path(context)
                            self._update_status(context)
                except (IndexError, AttributeError, ReferenceError):
                    pass
            else:
                if self.hit_obj is not None:
                    self.hit_obj = None
                    self.hovered_edge_index = -1
                    self.path_edge_indices = []
                    self.path_coords = []
                    self.barrier_coords = []
                    self._update_status(context)

            context.area.tag_redraw()

        # Cycle barrier type
        elif (
            event.type == 'E'
            and event.value == 'PRESS'
            and not event.ctrl
            and not event.shift
        ):
            self.barrier_type_idx = (
                (self.barrier_type_idx + 1) % len(BARRIER_TYPES)
            )
            self._update_path(context)
            self._update_status(context)
            context.area.tag_redraw()
            return {'RUNNING_MODAL'}

        # Cycle mark type
        elif (
            event.type == 'R'
            and event.value == 'PRESS'
            and not event.ctrl
            and not event.shift
        ):
            self.mark_type_idx = (
                (self.mark_type_idx + 1) % len(BARRIER_TYPES)
            )
            self._angle_marked = False
            self._update_status(context)
            context.area.tag_redraw()
            return {'RUNNING_MODAL'}

        # Cycle algorithm
        elif (
            event.type == 'A'
            and event.value == 'PRESS'
            and not event.ctrl
            and not event.shift
        ):
            self.algorithm_idx = (
                (self.algorithm_idx + 1) % len(ALGORITHM_TYPES)
            )
            self._update_path(context)
            self._update_status(context)
            context.area.tag_redraw()
            return {'RUNNING_MODAL'}

        # Mark sharp by angle
        elif (
            event.type == 'S'
            and event.value == 'PRESS'
            and not event.ctrl
            and not event.shift
        ):
            self._execute_mark_by_angle(context)
            self._update_status(context)
            context.area.tag_redraw()
            return {'RUNNING_MODAL'}

        # Clear marked path
        elif (
            event.type == 'D'
            and event.value == 'PRESS'
            and not event.ctrl
            and not event.shift
        ):
            self._execute_clear(context)
            self._update_status(context)
            context.area.tag_redraw()
            return {'RUNNING_MODAL'}

        # Apply marks
        elif event.type == 'LEFTMOUSE' and event.value == 'PRESS':
            self._execute_mark(context)
            self._update_status(context)
            context.area.tag_redraw()
            return {'RUNNING_MODAL'}

        # Undo
        elif (
            event.type == 'Z'
            and event.value == 'PRESS'
            and event.ctrl
            and not event.shift
        ):
            bpy.ops.ed.undo()
            self._update_path(context)
            self._update_status(context)
            context.area.tag_redraw()
            return {'RUNNING_MODAL'}

        # Finish
        elif event.type == 'SPACE' and event.value == 'PRESS':
            self._save_scene_props(context)
            self._cleanup(context)
            return {'FINISHED'}

        # Cancel
        elif event.type == 'ESC':
            self._save_scene_props(context)
            self._cleanup(context)
            return {'CANCELLED'}

        return {'RUNNING_MODAL'}

    def _cleanup(self, context):
        # Restore Triangulate modifier state
        if self._tri_mod is not None and self._tri_mod_show_viewport is not None:
            self._tri_mod.show_viewport = self._tri_mod_show_viewport
            self._tri_mod = None
            self._tri_mod_show_viewport = None

        if self._handle:
            bpy.types.SpaceView3D.draw_handler_remove(
                self._handle, 'WINDOW'
            )
            self._handle = None
        if self._handle_text:
            bpy.types.SpaceView3D.draw_handler_remove(
                self._handle_text, 'WINDOW'
            )
            self._handle_text = None
        if self._timer:
            context.window_manager.event_timer_remove(self._timer)
            self._timer = None
        context.workspace.status_text_set(None)
        context.area.tag_redraw()
