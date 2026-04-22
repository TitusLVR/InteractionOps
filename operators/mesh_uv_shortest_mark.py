import bpy
import bmesh
import math
import gpu
from gpu_extras.batch import batch_for_shader
import bpy_extras
import blf
from mathutils import Vector
import heapq

try:
    from . import mesh_uv_shortest_mark_lib as _native  # packaged .pyd
    NATIVE_AVAILABLE = True
except Exception:
    try:
        import mesh_uv_shortest_mark_lib as _native
        NATIVE_AVAILABLE = True
    except Exception:
        _native = None
        NATIVE_AVAILABLE = False


BARRIER_TYPES = ('SEAM', 'SHARP', 'CREASE', 'BEVEL')
BARRIER_LABELS = {
    'SEAM': 'UV Seam',
    'SHARP': 'Sharp',
    'CREASE': 'Crease',
    'BEVEL': 'Bevel Weight',
}
ALGORITHM_TYPES = ('DIJKSTRA', 'ASTAR', 'EDGE_LOOP')
ALGORITHM_LABELS = {
    'DIJKSTRA': 'Dijkstra',
    'ASTAR': 'A*',
    'EDGE_LOOP': 'Edge Loop',
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

ANCHOR_COLOR = (0.0, 0.8, 0.0, 1.0)
ANCHOR_SIZE = 10.0

PATH_MODES = ('DIRECTION', 'BUILD')
PATH_MODE_LABELS = {'DIRECTION': 'Direction', 'BUILD': 'Build'}
MAX_SMOOTH_LEVEL = 10
SMOOTH_STEP = 1
MAX_CURVATURE = 100
CURVATURE_STEP = 10
CURVATURE_SCALE = 0.8
EDGE_LOOP_CURV_WEIGHT = 0.5

# Arch / bending bias (BUILD mode — Ctrl+Alt+Wheel)
MAX_ARCH = 10
ARCH_STEP = 1
# Arc sagitta (apex height above chord) as a fraction of chord length,
# scaled by arch/MAX_ARCH. At ±MAX_ARCH the arc is a full semicircle (h = L/2).
ARCH_MAX_SAGITTA = 0.5
# Max number of intermediate waypoints along the arc. More = rounder.
# Chosen dynamically from |arch_strength| up to this cap.
ARCH_MAX_WAYPOINTS = 8

# Smooth-marked sub-mode (F key)
SMOOTH_MAGNET_RANGE = 10
SMOOTH_MAGNET_STEP = 1
SMOOTH_MARKED_WINDOW = 5
MAX_SMOOTH_ITERATIONS = 100
SMOOTH_ITER_STEP = 1
SMOOTH_PREVIEW_COLOR = (1.0, 0.85, 0.0, 1.0)
SMOOTH_PREVIEW_WIDTH = 3.5
SMOOTH_ORIGINAL_COLOR = (0.6, 0.3, 0.3, 0.8)
SMOOTH_ORIGINAL_WIDTH = 2.0
# Weighted A*: inflates the heuristic to prune the frontier aggressively.
# Paths are at most ASTAR_H_WEIGHT× optimal length; on curved/non-convex meshes
# the Euclidean-distance heuristic is a very loose bound, so amortized paths
# stay near-optimal while search time drops drastically.
ASTAR_H_WEIGHT = 2.5


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

    # Path mode
    path_mode_idx = 0
    anchor_vert_index = -1
    anchor_coords = []
    _target_vert_index = -1

    # Settings indices
    barrier_type_idx = 0
    mark_type_idx = 0
    algorithm_idx = 0
    flow_angle = DEFAULT_FLOW_ANGLE
    sharp_angle = DEFAULT_SHARP_ANGLE
    _angle_marked = False
    smooth_level = 0
    curvature = 0
    arch_strength = 0

    # Cached BMesh layers
    _crease_layer = None
    _bevel_layer = None

    # Graph cache (mesh-stable; invalidated on topology change / undo)
    _edge_length = None
    _edge_has_angle = None
    _edge_angle_bias = None
    _edge_barrier = None
    _cache_edge_count = -1
    _cache_vert_count = -1
    _cache_barrier_idx = -1
    # CSR adjacency
    _adj_starts = None   # list[int] len V+1
    _adj_other = None    # list[int] len 2E
    _adj_edge = None     # list[int] len 2E
    _adj_dir = None      # list[Vector|None] len 2E (normalized v->other direction)
    _vert_co = None      # list[Vector] len V
    # Native (Rust) graph handle — None when unavailable or not yet built
    _native_graph = None

    # Smooth-marked sub-mode state
    _smooth_mode = False
    _smooth_magnet = 0
    _smooth_iterations = 1
    _smooth_preview_edges = []
    _smooth_preview_coords = []
    _smooth_original_coords = []
    _smooth_original_marks = set()

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

    @property
    def path_mode(self):
        return PATH_MODES[self.path_mode_idx]

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

    def _invalidate_graph_cache(self):
        self._edge_length = None
        self._edge_has_angle = None
        self._edge_angle_bias = None
        self._edge_barrier = None
        self._adj_starts = None
        self._adj_other = None
        self._adj_edge = None
        self._adj_dir = None
        self._vert_co = None
        self._native_graph = None
        self._cache_edge_count = -1
        self._cache_vert_count = -1
        self._cache_barrier_idx = -1

    def _invalidate_barrier_cache(self):
        self._edge_barrier = None
        self._cache_barrier_idx = -1
        # Native graph keeps topology; we'll push a fresh barrier mask next call
        self._native_barrier_dirty = True

    def _ensure_graph_cache(self, bm):
        """Build per-edge arrays + CSR adjacency + per-vert coord array.

        Collapses BMesh attribute access and Python-level barrier / length
        calls into pure list indexing in Dijkstra/A*. Built once per
        mesh-topology state; reused across mouse moves and inside
        _smooth_path's inner searches.
        """
        ec = len(bm.edges)
        vc = len(bm.verts)
        if (self._edge_length is None
                or self._cache_edge_count != ec
                or self._cache_vert_count != vc):
            bm.edges.ensure_lookup_table()
            bm.verts.ensure_lookup_table()

            # Per-edge scalars
            lengths = [0.0] * ec
            has_angle = [False] * ec
            bias = [0.0] * ec
            inv_pi = 1.0 / math.pi
            for i, e in enumerate(bm.edges):
                lengths[i] = e.calc_length()
                if len(e.link_faces) == 2:
                    has_angle[i] = True
                    bias[i] = 2.0 * (e.calc_face_angle(0.0) * inv_pi) - 1.0

            # Per-vertex coord snapshot
            vert_co = [v.co.copy() for v in bm.verts]

            # CSR adjacency build (two passes)
            starts = [0] * (vc + 1)
            for v in bm.verts:
                starts[v.index + 1] = len(v.link_edges)
            for i in range(1, vc + 1):
                starts[i] += starts[i - 1]
            total = starts[-1]
            other = [0] * total
            edge_idx = [0] * total
            dirs = [None] * total
            pos = list(starts)
            for v in bm.verts:
                vi = v.index
                vco = vert_co[vi]
                for e in v.link_edges:
                    ov = e.other_vert(v)
                    i = pos[vi]
                    pos[vi] = i + 1
                    other[i] = ov.index
                    edge_idx[i] = e.index
                    d = vert_co[ov.index] - vco
                    if d.length > 1e-8:
                        dirs[i] = d.normalized()

            self._edge_length = lengths
            self._edge_has_angle = has_angle
            self._edge_angle_bias = bias
            self._vert_co = vert_co
            self._adj_starts = starts
            self._adj_other = other
            self._adj_edge = edge_idx
            self._adj_dir = dirs
            self._cache_edge_count = ec
            self._cache_vert_count = vc
            self._edge_barrier = None  # force barrier rebuild

            # Build native graph (Rust) if available — one-shot per topology state
            if NATIVE_AVAILABLE:
                try:
                    edge_verts_flat = [0] * (2 * ec)
                    for i, e in enumerate(bm.edges):
                        edge_verts_flat[i * 2] = e.verts[0].index
                        edge_verts_flat[i * 2 + 1] = e.verts[1].index
                    vc_flat = [0.0] * (3 * vc)
                    for i, co in enumerate(vert_co):
                        vc_flat[i * 3] = co[0]
                        vc_flat[i * 3 + 1] = co[1]
                        vc_flat[i * 3 + 2] = co[2]
                    # Barrier mask populated below; pass zeros, set_barrier will update
                    self._native_graph = _native.Graph(
                        vc, edge_verts_flat, lengths,
                        bytes(1 if b else 0 for b in has_angle),
                        bias,
                        bytes(ec),
                        vc_flat,
                    )
                    self._native_barrier_dirty = True
                except Exception:
                    self._native_graph = None

        if (self._edge_barrier is None
                or self._cache_barrier_idx != self.barrier_type_idx):
            bm.edges.ensure_lookup_table()
            barriers = [False] * ec
            bt = self.barrier_type
            if bt == 'SEAM':
                for i, e in enumerate(bm.edges):
                    barriers[i] = e.seam
            elif bt == 'SHARP':
                for i, e in enumerate(bm.edges):
                    barriers[i] = not e.smooth
            elif bt == 'CREASE':
                layer = self._crease_layer
                if layer is not None:
                    for i, e in enumerate(bm.edges):
                        barriers[i] = e[layer] > 0.0
            elif bt == 'BEVEL':
                layer = self._bevel_layer
                if layer is not None:
                    for i, e in enumerate(bm.edges):
                        barriers[i] = e[layer] > 0.0
            self._edge_barrier = barriers
            self._cache_barrier_idx = self.barrier_type_idx
            self._native_barrier_dirty = True

        # Sync native graph barrier mask if native path is active
        if (NATIVE_AVAILABLE and self._native_graph is not None
                and getattr(self, '_native_barrier_dirty', False)):
            self._native_graph.set_barrier(
                bytes(1 if b else 0 for b in self._edge_barrier)
            )
            self._native_barrier_dirty = False

    # ─── Path algorithms ─────────────────────────────────────────────

    def _compute_path(self, bm, hovered_edge):
        if self.path_mode == 'BUILD':
            return self._compute_path_build(bm)

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

        # Smooth each arm
        if arm_a:
            arm_a = self._smooth_path(bm, arm_a, v1, forbidden_verts=None)
        if arm_b:
            arm_b = self._smooth_path(bm, arm_b, v2, forbidden_verts=None)

        arm_a.reverse()
        return arm_a + [hovered_edge.index] + arm_b

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

    def _vertex_touches_barrier(self, vert, excluded_edge=None):
        """Return True if any edge connected to vert is a barrier."""
        barrier = self._edge_barrier
        excluded_idx = excluded_edge.index if excluded_edge is not None else -1
        if barrier is not None:
            for edge in vert.link_edges:
                ei = edge.index
                if ei == excluded_idx:
                    continue
                if barrier[ei]:
                    return True
            return False
        for edge in vert.link_edges:
            if edge.index == excluded_idx:
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

    def _edge_curvature_multiplier(self, edge):
        if self.curvature == 0 or len(edge.link_faces) != 2:
            return 1.0
        d = edge.calc_face_angle(0.0) / math.pi
        b = 2.0 * d - 1.0
        c = self.curvature / MAX_CURVATURE
        return max(0.1, 1.0 - CURVATURE_SCALE * c * b)

    def _dijkstra_arm(self, bm, start_vert, excluded_edge=None, target_vert=None,
                      forbidden_verts=None):
        self._ensure_graph_cache(bm)
        self._flow_cos = math.cos(math.radians(self.flow_angle))

        start_idx = start_vert.index
        if excluded_edge is not None:
            initial_dir = self._initial_dir(start_vert, excluded_edge)
        elif target_vert is not None:
            d = target_vert.co - start_vert.co
            initial_dir = d.normalized() if d.length > 1e-8 else Vector((1, 0, 0))
        else:
            initial_dir = Vector((1, 0, 0))

        # Native fast path
        if self._native_graph is not None:
            ex_e = excluded_edge.index if excluded_edge is not None else -1
            flow_cos_native = self._flow_cos if self.flow_angle < 180 else -2.0
            curv_c = self.curvature / MAX_CURVATURE if self.curvature != 0 else 0.0
            end_idx = target_vert.index if target_vert is not None else -1
            forbidden_list = list(forbidden_verts) if forbidden_verts else None
            return list(self._native_graph.dijkstra(
                start_idx, end_idx, ex_e,
                flow_cos_native, curv_c,
                MAX_PATH_EDGES,
                [initial_dir.x, initial_dir.y, initial_dir.z],
                forbidden_list,
            ))

        # Local bindings
        edge_len = self._edge_length
        has_angle = self._edge_has_angle
        angle_bias = self._edge_angle_bias
        edge_barrier = self._edge_barrier
        adj_starts = self._adj_starts
        adj_other = self._adj_other
        adj_edge = self._adj_edge
        adj_dir = self._adj_dir
        nv = self._cache_vert_count

        curv_c = self.curvature / MAX_CURVATURE
        curv_active = self.curvature != 0
        flow_cos = self._flow_cos
        flow_active = self.flow_angle < 180
        excluded_idx = excluded_edge.index if excluded_edge is not None else -1
        target_idx = target_vert.index if target_vert is not None else -1

        INF = math.inf
        dist = [INF] * nv
        prev_v = [-1] * nv
        prev_e = [-1] * nv
        incoming = [None] * nv
        visited = bytearray(nv)
        dist[start_idx] = 0.0
        incoming[start_idx] = initial_dir
        heap = [(0.0, start_idx)]
        heappush = heapq.heappush
        heappop = heapq.heappop
        target = -1
        visited_count = 0

        while heap:
            d, vi = heappop(heap)
            if visited[vi]:
                continue
            visited[vi] = 1
            visited_count += 1
            if visited_count > MAX_PATH_EDGES:
                break

            if vi != start_idx:
                if target_idx >= 0:
                    if vi == target_idx:
                        target = vi
                        break
                else:
                    # Barrier-stop check (Direction mode without explicit target)
                    # Scan neighbors directly via CSR instead of self._vertex_touches_barrier.
                    touched = False
                    s = adj_starts[vi]; ee = adj_starts[vi + 1]
                    for k in range(s, ee):
                        ei = adj_edge[k]
                        if ei == excluded_idx:
                            continue
                        if edge_barrier[ei]:
                            touched = True
                            break
                    if touched:
                        target = vi
                        break

            inc_dir = incoming[vi]
            if inc_dir is None:
                inc_dir = initial_dir

            s = adj_starts[vi]; ee = adj_starts[vi + 1]
            for k in range(s, ee):
                ei = adj_edge[k]
                if ei == excluded_idx:
                    continue
                if edge_barrier[ei]:
                    continue
                ovi = adj_other[k]
                if visited[ovi]:
                    continue
                if forbidden_verts is not None and ovi in forbidden_verts:
                    continue
                dir_vec = adj_dir[k]
                if flow_active and dir_vec is not None:
                    if inc_dir.dot(dir_vec) < flow_cos:
                        continue
                if curv_active and has_angle[ei]:
                    mult = 1.0 - CURVATURE_SCALE * curv_c * angle_bias[ei]
                    if mult < 0.1:
                        mult = 0.1
                    nd = d + edge_len[ei] * mult
                else:
                    nd = d + edge_len[ei]
                if nd < dist[ovi]:
                    dist[ovi] = nd
                    prev_v[ovi] = vi
                    prev_e[ovi] = ei
                    incoming[ovi] = dir_vec if dir_vec is not None else inc_dir
                    heappush(heap, (nd, ovi))

        if target < 0:
            # Pick furthest reached vertex (Direction mode, unbounded expansion)
            best_d = -1.0
            for i in range(nv):
                di = dist[i]
                if di < INF and di > best_d:
                    best_d = di
                    target = i
            if target < 0 or prev_v[target] == -1:
                return []
        return self._reconstruct_arr(prev_v, prev_e, target)

    def _astar_arm(self, bm, start_vert, excluded_edge=None, target_vert=None,
                   forbidden_verts=None):
        if target_vert is None:
            return self._dijkstra_arm(bm, start_vert, excluded_edge,
                                      target_vert, forbidden_verts)

        self._ensure_graph_cache(bm)
        self._flow_cos = math.cos(math.radians(self.flow_angle))

        start_idx = start_vert.index
        target_idx = target_vert.index
        if excluded_edge is not None:
            initial_dir = self._initial_dir(start_vert, excluded_edge)
        else:
            d = target_vert.co - start_vert.co
            initial_dir = d.normalized() if d.length > 1e-8 else Vector((1, 0, 0))

        # Native fast path
        if self._native_graph is not None:
            ex_e = excluded_edge.index if excluded_edge is not None else -1
            flow_cos_native = self._flow_cos if self.flow_angle < 180 else -2.0
            curv_c = self.curvature / MAX_CURVATURE if self.curvature != 0 else 0.0
            h_weight = (1.0 - CURVATURE_SCALE if self.curvature != 0 else 1.0) * ASTAR_H_WEIGHT
            forbidden_list = list(forbidden_verts) if forbidden_verts else None
            return list(self._native_graph.astar(
                start_idx, target_idx, ex_e,
                flow_cos_native, curv_c, h_weight,
                MAX_PATH_EDGES,
                [initial_dir.x, initial_dir.y, initial_dir.z],
                forbidden_list,
            ))

        target_co = target_vert.co
        base_h = 1.0 - CURVATURE_SCALE if self.curvature != 0 else 1.0
        h_scale = base_h * ASTAR_H_WEIGHT

        edge_len = self._edge_length
        has_angle = self._edge_has_angle
        angle_bias = self._edge_angle_bias
        edge_barrier = self._edge_barrier
        adj_starts = self._adj_starts
        adj_other = self._adj_other
        adj_edge = self._adj_edge
        adj_dir = self._adj_dir
        vert_co_arr = self._vert_co
        nv = self._cache_vert_count

        curv_c = self.curvature / MAX_CURVATURE
        curv_active = self.curvature != 0
        flow_cos = self._flow_cos
        flow_active = self.flow_angle < 180
        excluded_idx = excluded_edge.index if excluded_edge is not None else -1

        INF = math.inf
        dist = [INF] * nv
        prev_v = [-1] * nv
        prev_e = [-1] * nv
        incoming = [None] * nv
        visited = bytearray(nv)
        dist[start_idx] = 0.0
        incoming[start_idx] = initial_dir
        h0 = (start_vert.co - target_co).length * h_scale
        heap = [(h0, 0.0, start_idx)]
        heappush = heapq.heappush
        heappop = heapq.heappop
        target = -1
        visited_count = 0

        while heap:
            _f, g, vi = heappop(heap)
            if visited[vi]:
                continue
            visited[vi] = 1
            visited_count += 1
            if visited_count > MAX_PATH_EDGES:
                break

            if vi == target_idx:
                target = vi
                break

            inc_dir = incoming[vi]
            if inc_dir is None:
                inc_dir = initial_dir

            s = adj_starts[vi]
            ee = adj_starts[vi + 1]
            for k in range(s, ee):
                ei = adj_edge[k]
                if ei == excluded_idx:
                    continue
                if edge_barrier[ei]:
                    continue
                ovi = adj_other[k]
                if visited[ovi]:
                    continue
                if forbidden_verts is not None and ovi in forbidden_verts:
                    continue
                dir_vec = adj_dir[k]
                if flow_active and dir_vec is not None:
                    if inc_dir.dot(dir_vec) < flow_cos:
                        continue
                if curv_active and has_angle[ei]:
                    mult = 1.0 - CURVATURE_SCALE * curv_c * angle_bias[ei]
                    if mult < 0.1:
                        mult = 0.1
                    ng = g + edge_len[ei] * mult
                else:
                    ng = g + edge_len[ei]
                if ng < dist[ovi]:
                    dist[ovi] = ng
                    prev_v[ovi] = vi
                    prev_e[ovi] = ei
                    incoming[ovi] = dir_vec if dir_vec is not None else inc_dir
                    h = (vert_co_arr[ovi] - target_co).length * h_scale
                    heappush(heap, (ng + h, ng, ovi))

        if target < 0:
            return []
        return self._reconstruct_arr(prev_v, prev_e, target)

    def _edge_loop_arm(self, bm, start_vert, excluded_edge=None, target_vert=None,
                       forbidden_verts=None):
        self._ensure_graph_cache(bm)
        self._flow_cos = math.cos(math.radians(self.flow_angle))
        edge_barrier = self._edge_barrier
        has_angle = self._edge_has_angle
        angle_bias = self._edge_angle_bias
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

            prev_idx = prev_edge.index if prev_edge is not None else -1
            candidates = []
            for edge in current.link_edges:
                ei = edge.index
                if ei == prev_idx:
                    continue
                if edge_barrier[ei]:
                    continue
                ov = edge.other_vert(current)
                if ov.index in visited:
                    continue
                if forbidden_verts is not None and ov.index in forbidden_verts:
                    continue
                if not self._passes_flow(prev_dir, current, ov):
                    continue
                candidates.append(edge)

            if not candidates:
                break

            if self.curvature != 0:
                c = self.curvature / MAX_CURVATURE

                def _score(e, _ab=angle_bias, _ha=has_angle):
                    ev = (e.other_vert(current).co - current.co).normalized()
                    alignment = prev_dir.dot(ev)
                    ei = e.index
                    b = _ab[ei] if _ha[ei] else 0.0
                    return alignment + EDGE_LOOP_CURV_WEIGHT * c * b

                best = max(candidates, key=_score)
            else:
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

    @staticmethod
    def _reconstruct_arr(prev_v, prev_e, target):
        edges = []
        cur = target
        pv = prev_v[cur]
        while pv != -1:
            edges.append(prev_e[cur])
            cur = pv
            pv = prev_v[cur]
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

    def _compute_path_build(self, bm):
        if self.anchor_vert_index < 0 or self._target_vert_index < 0:
            return []
        bm.verts.ensure_lookup_table()
        if (self.anchor_vert_index >= len(bm.verts)
                or self._target_vert_index >= len(bm.verts)):
            return []
        if self.anchor_vert_index == self._target_vert_index:
            return []
        anchor = bm.verts[self.anchor_vert_index]
        target = bm.verts[self._target_vert_index]

        # Step 1: compute baseline path normally (respects barriers, curvature, flow)
        base_path = self._trace_arm(bm, anchor, target_vert=target)
        if not base_path:
            return []

        # Step 2: optional arch post-process — deform the baseline toward a
        # perpendicular-pushed arc. If any leg fails we fall through to the
        # unarched baseline.
        if self.arch_strength != 0:
            waypoint_vis = self._compute_arch_waypoints_from_path(
                bm, base_path, anchor, target
            )
            if waypoint_vis:
                arched = self._trace_through_waypoints(
                    bm, anchor, waypoint_vis, target
                )
                if arched:
                    return self._smooth_path(bm, arched, anchor,
                                             forbidden_verts=None)

        # Step 3: smooth baseline
        return self._smooth_path(bm, base_path, anchor, forbidden_verts=None)

    def _trace_through_waypoints(self, bm, anchor, waypoint_vis, target):
        """A*-chain anchor -> wp0 -> wp1 -> ... -> target.
        Each subsequent leg forbids vertices already used (so the path can't
        self-intersect), except for the current leg's start/end. If any leg
        fails the whole arch routing is abandoned (caller falls back to
        direct A*)."""
        bm.verts.ensure_lookup_table()
        stops = [anchor]
        for vi in waypoint_vis:
            stops.append(bm.verts[vi])
        stops.append(target)
        # Dedupe consecutive stops that snapped to the same vertex
        dedup = [stops[0]]
        for v in stops[1:]:
            if v.index != dedup[-1].index:
                dedup.append(v)
        if len(dedup) < 2:
            return []

        used_verts = {dedup[0].index}
        path = []
        for i in range(len(dedup) - 1):
            a = dedup[i]
            b = dedup[i + 1]
            forbidden = used_verts - {a.index, b.index}
            leg = self._trace_arm(bm, a, target_vert=b, forbidden_verts=forbidden)
            if not leg:
                return []
            path.extend(leg)
            # Walk leg's verts and add to used set
            cur = a
            used_verts.add(cur.index)
            for ei in leg:
                e = bm.edges[ei]
                v1, v2 = e.verts
                cur = v2 if v1.index == cur.index else v1
                used_verts.add(cur.index)
        return path

    def _compute_arch_waypoints_from_path(self, bm, base_edges, anchor, target):
        """Post-process: sample the baseline path and push each sample
        perpendicular to the anchor→target chord along a view-aligned axis,
        following a parabolic sagitta profile (0 at endpoints, peak at t=0.5).

        This preserves the baseline's natural detours (from barriers /
        curvature / flow) and layers an arc deformation on top — instead of
        forcing a pristine arc from scratch."""
        try:
            rv3d = bpy.context.space_data.region_3d
            view_dir = rv3d.view_rotation @ Vector((0.0, 0.0, -1.0))
        except (AttributeError, TypeError):
            view_dir = Vector((0.0, 0.0, -1.0))

        obj = self.hit_obj
        if obj is None:
            return []
        mat = obj.matrix_world
        a_world = mat @ anchor.co
        t_world = mat @ target.co
        line_vec = t_world - a_world
        L = line_vec.length
        if L < 1e-8:
            return []
        line_dir = line_vec / L

        # Perpendicular axis in the view plane, pointing "up" on screen
        horiz = line_dir.cross(view_dir)
        if horiz.length < 1e-8:
            horiz = line_dir.cross(Vector((0.0, 0.0, 1.0)))
            if horiz.length < 1e-8:
                horiz = Vector((1.0, 0.0, 0.0))
        horiz = horiz.normalized()
        up = horiz.cross(line_dir)
        if up.length < 1e-8:
            return []
        up = up.normalized()

        # Peak sagitta along the arc (world units)
        s = self.arch_strength / MAX_ARCH
        max_offset = ARCH_MAX_SAGITTA * s * L  # signed: sign picks which side
        if abs(max_offset) < 1e-6:
            return []

        # Walk the baseline path to build an ordered world-space polyline with
        # cumulative arc-length for arc-length-uniform sampling.
        bm.edges.ensure_lookup_table()
        bm.verts.ensure_lookup_table()
        pts_world = [a_world]
        cur = anchor
        cum_len = [0.0]
        total = 0.0
        for ei in base_edges:
            e = bm.edges[ei]
            v1, v2 = e.verts
            nv = v2 if v1.index == cur.index else v1
            p = mat @ nv.co
            seg = (p - pts_world[-1]).length
            total += seg
            pts_world.append(p)
            cum_len.append(total)
            cur = nv
        if total < 1e-8 or len(pts_world) < 2:
            return []

        # How many waypoints: scale with |arch_strength|, cap at ARCH_MAX_WAYPOINTS.
        # Also don't exceed path-interior vertex count (no point oversampling a
        # 3-edge path with 8 waypoints).
        count = max(1, min(ARCH_MAX_WAYPOINTS, abs(self.arch_strength)))
        count = min(count, max(1, len(pts_world) - 2)) if len(pts_world) > 2 else count

        try:
            inv = mat.inverted()
        except ValueError:
            return []

        waypoints = []
        seen = set()
        for i in range(1, count + 1):
            t = i / (count + 1)
            target_cum = t * total
            # Binary-search-ish: find segment that contains target_cum
            seg_i = 1
            while seg_i < len(cum_len) and cum_len[seg_i] < target_cum:
                seg_i += 1
            if seg_i >= len(cum_len):
                seg_i = len(cum_len) - 1
            seg_a = cum_len[seg_i - 1]
            seg_b = cum_len[seg_i]
            seg_span = max(1e-8, seg_b - seg_a)
            local_t = (target_cum - seg_a) / seg_span
            path_pt = pts_world[seg_i - 1].lerp(pts_world[seg_i], local_t)

            # Parabolic sagitta: 0 at endpoints, peak 4×max/4=max at t=0.5
            push = 4.0 * t * (1.0 - t) * max_offset
            pushed_world = path_pt + up * push
            pushed_local = inv @ pushed_world

            if self._native_graph is not None:
                vi = int(self._native_graph.nearest_vertex(
                    [pushed_local.x, pushed_local.y, pushed_local.z]
                ))
            else:
                best_i = -1
                best_d = float('inf')
                wx, wy, wz = pushed_local.x, pushed_local.y, pushed_local.z
                for j, co in enumerate(self._vert_co or []):
                    dx = co[0] - wx
                    dy = co[1] - wy
                    dz = co[2] - wz
                    d = dx * dx + dy * dy + dz * dz
                    if d < best_d:
                        best_d = d
                        best_i = j
                vi = best_i if best_i >= 0 else -1
            if vi < 0:
                continue
            if vi == anchor.index or vi == target.index:
                continue
            if vi in seen:
                continue
            seen.add(vi)
            waypoints.append(vi)
        return waypoints


    def _smooth_path(self, bm, edge_indices, start_vert, forbidden_verts=None):
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

        window = self.smooth_level + 1
        outer = forbidden_verts if forbidden_verts is not None else set()

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

                if self.algorithm == 'ASTAR':
                    alt = self._astar_arm(
                        bm, verts[i], target_vert=verts[j],
                        forbidden_verts=locally_forbidden,
                    )
                else:
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

    # ─── Smooth-marked sub-mode ──────────────────────────────────────

    def _collect_marked_edges(self, bm):
        """Return set of edge indices currently marked with the active mark type."""
        mt = self.mark_type
        marked = set()
        bm.edges.ensure_lookup_table()
        if mt == 'SEAM':
            for e in bm.edges:
                if e.seam:
                    marked.add(e.index)
        elif mt == 'SHARP':
            for e in bm.edges:
                if not e.smooth:
                    marked.add(e.index)
        elif mt == 'CREASE':
            layer = bm.edges.layers.float.get("crease_edge")
            if layer is not None:
                for e in bm.edges:
                    if e[layer] > 0.0:
                        marked.add(e.index)
        elif mt == 'BEVEL':
            layer = bm.edges.layers.float.get("bevel_weight_edge")
            if layer is not None:
                for e in bm.edges:
                    if e[layer] > 0.0:
                        marked.add(e.index)
        return marked

    def _extract_marked_chains(self, bm, marked):
        """Split marked-edge subgraph into linear chains (endpoint-to-endpoint
        or endpoint-to-junction). Returns list of (start_vert, [edge_indices]).
        Junctions (vertex of marked-degree > 2) split chains; closed loops are
        walked from an arbitrary start.
        """
        if not marked:
            return []
        v_edges = {}
        bm.edges.ensure_lookup_table()
        for ei in marked:
            e = bm.edges[ei]
            v_edges.setdefault(e.verts[0].index, []).append(ei)
            v_edges.setdefault(e.verts[1].index, []).append(ei)

        visited = set()
        chains = []

        def walk(start_vi, start_ei):
            chain = [start_ei]
            visited.add(start_ei)
            e = bm.edges[start_ei]
            v1, v2 = e.verts[0].index, e.verts[1].index
            cur = v2 if v1 == start_vi else v1
            while True:
                edges_here = v_edges.get(cur, [])
                # Stop if not a clean through-vertex (degree != 2 in marked subgraph)
                # or if the only unvisited edge is back to start (closed loop)
                if len(edges_here) != 2:
                    break
                unvisited = [ei for ei in edges_here if ei not in visited]
                if not unvisited:
                    break
                ne_i = unvisited[0]
                visited.add(ne_i)
                chain.append(ne_i)
                ne = bm.edges[ne_i]
                v1, v2 = ne.verts[0].index, ne.verts[1].index
                cur = v2 if v1 == cur else v1
            return (start_vi, chain)

        # Walk from endpoints / junctions first
        for vi, eis in v_edges.items():
            if len(eis) != 2:
                for ei in eis:
                    if ei not in visited:
                        chains.append(walk(vi, ei))
        # Remaining closed loops
        for ei in marked:
            if ei not in visited:
                e = bm.edges[ei]
                chains.append(walk(e.verts[0].index, ei))

        return chains

    def _smooth_marked_compute(self, bm):
        """Compute the proposed smoothed edge set for the currently marked edges.
        Reuses _smooth_path with a temporary higher window + magnet-driven
        curvature bias. Returns (proposal_set, original_set).
        """
        original = self._collect_marked_edges(bm)
        if not original:
            return set(), set()
        chains = self._extract_marked_chains(bm, original)

        # Snapshot and override relevant operator state for the smoothing pass
        save_curv = self.curvature
        save_smooth = self.smooth_level
        save_algo_idx = self.algorithm_idx
        # Map magnet [-N..+N] onto curvature range [-MAX..+MAX]
        if SMOOTH_MAGNET_RANGE > 0:
            self.curvature = int(
                self._smooth_magnet * MAX_CURVATURE / SMOOTH_MAGNET_RANGE
            )
        self.smooth_level = SMOOTH_MARKED_WINDOW
        self.algorithm_idx = 1  # A*

        proposal = set()
        bm.verts.ensure_lookup_table()
        try:
            # Temporarily clear the marks so the smoothing search can use
            # them as candidate routes (edges currently marked would be
            # treated as barriers if the barrier type == mark type).
            # Instead, we forbid in-chain verts outside the current window
            # via the existing _smooth_path locally_forbidden logic, so we
            # don't need to toggle marks on the mesh. Just run it.
            iterations = max(1, min(self._smooth_iterations, MAX_SMOOTH_ITERATIONS))
            for start_vi, chain_edges in chains:
                if not chain_edges:
                    continue
                start_vert = bm.verts[start_vi]
                current = chain_edges
                for _ in range(iterations):
                    smoothed = self._smooth_path(
                        bm, current, start_vert, forbidden_verts=None
                    )
                    if not smoothed or smoothed == current:
                        current = smoothed or current
                        break  # converged (or degenerate) — further iterations won't change it
                    current = smoothed
                proposal.update(current)
        finally:
            self.curvature = save_curv
            self.smooth_level = save_smooth
            self.algorithm_idx = save_algo_idx

        return proposal, original

    def _enter_smooth_mode(self, context):
        obj = self.hit_obj or context.active_object
        if not obj or obj.type != 'MESH' or obj.mode != 'EDIT':
            self.report({'WARNING'}, "No mesh in Edit Mode")
            return
        try:
            bm = bmesh.from_edit_mesh(obj.data)
            self._cache_layers(bm)
            bm.verts.ensure_lookup_table()
            bm.edges.ensure_lookup_table()
            self._ensure_graph_cache(bm)
        except (ReferenceError, AttributeError, ValueError):
            return

        if not self._collect_marked_edges(bm):
            self.report({'INFO'}, "No marked edges to smooth")
            return

        self._smooth_mode = True
        self._smooth_magnet = 0
        self._smooth_iterations = 1
        self.hit_obj = obj
        self._refresh_smooth_preview(context)
        self._update_status(context)
        context.area.tag_redraw()

    def _exit_smooth_mode(self, context, commit=False):
        if not self._smooth_mode:
            return
        if commit:
            self._commit_smooth(context)
        self._smooth_mode = False
        self._smooth_preview_edges = []
        self._smooth_preview_coords = []
        self._smooth_original_coords = []
        self._smooth_original_marks = set()
        self._update_status(context)
        context.area.tag_redraw()

    def _refresh_smooth_preview(self, context):
        obj = self.hit_obj
        if not obj or obj.mode != 'EDIT':
            return
        try:
            bm = bmesh.from_edit_mesh(obj.data)
            self._cache_layers(bm)
            bm.edges.ensure_lookup_table()
            self._ensure_graph_cache(bm)
            proposal, original = self._smooth_marked_compute(bm)
            self._smooth_preview_edges = sorted(proposal)
            self._smooth_original_marks = original
            self._build_smooth_coords(bm, obj, proposal, original)
        except (IndexError, AttributeError, ReferenceError, ValueError):
            self._smooth_preview_edges = []
            self._smooth_preview_coords = []
            self._smooth_original_coords = []

    def _build_smooth_coords(self, bm, obj, proposal, original):
        mat = obj.matrix_world
        self._smooth_preview_coords = []
        self._smooth_original_coords = []
        # Preview: edges proposed (new additions + retained)
        for ei in proposal:
            if 0 <= ei < len(bm.edges):
                e = bm.edges[ei]
                a = mat @ e.verts[0].co.copy()
                b = mat @ e.verts[1].co.copy()
                self._smooth_preview_coords.append((a, b))
        # Original: edges that will be dropped (orig - proposal)
        for ei in original - proposal:
            if 0 <= ei < len(bm.edges):
                e = bm.edges[ei]
                a = mat @ e.verts[0].co.copy()
                b = mat @ e.verts[1].co.copy()
                self._smooth_original_coords.append((a, b))

    def _commit_smooth(self, context):
        obj = self.hit_obj
        if not obj or obj.mode != 'EDIT':
            return
        proposal = set(self._smooth_preview_edges)
        original = self._smooth_original_marks
        if proposal == original:
            self.report({'INFO'}, "Smooth: no changes")
            return
        bpy.ops.ed.undo_push(message="Smooth Marked Edges")
        bm = bmesh.from_edit_mesh(obj.data)
        self._cache_layers(bm)
        bm.edges.ensure_lookup_table()
        to_clear = original - proposal
        to_apply = proposal - original
        for ei in to_clear:
            if 0 <= ei < len(bm.edges):
                self._clear_mark(bm.edges[ei], bm)
        for ei in to_apply:
            if 0 <= ei < len(bm.edges):
                self._apply_mark(bm.edges[ei], bm)
        bmesh.update_edit_mesh(obj.data)
        self._invalidate_barrier_cache()
        self.report(
            {'INFO'},
            f"Smoothed: -{len(to_clear)} / +{len(to_apply)} edges",
        )

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

    def _build_anchor_coords(self, context):
        self.anchor_coords = []
        if self.anchor_vert_index < 0:
            return
        obj = self.hit_obj if self.hit_obj else context.active_object
        if not obj or obj.type != 'MESH' or obj.mode != 'EDIT':
            return
        try:
            bm = bmesh.from_edit_mesh(obj.data)
            bm.verts.ensure_lookup_table()
            if 0 <= self.anchor_vert_index < len(bm.verts):
                self.anchor_coords.append(
                    obj.matrix_world
                    @ bm.verts[self.anchor_vert_index].co.copy()
                )
        except (ReferenceError, AttributeError, ValueError):
            pass

    def _pick_closest_vert_of_face(self, context, face, obj):
        region = context.region
        rv3d = context.space_data.region_3d
        if region is None or rv3d is None:
            return face.verts[0].index
        mx, my = self._current_mouse_coord
        mat = obj.matrix_world
        best_i = -1
        best_d = float('inf')
        for v in face.verts:
            sc = bpy_extras.view3d_utils.location_3d_to_region_2d(
                region, rv3d, mat @ v.co
            )
            if sc is None:
                continue
            d = (sc[0] - mx) ** 2 + (sc[1] - my) ** 2
            if d < best_d:
                best_d = d
                best_i = v.index
        return best_i if best_i >= 0 else face.verts[0].index

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
        self._invalidate_barrier_cache()
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
        self._invalidate_barrier_cache()
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
        self._invalidate_barrier_cache()
        verb = "Cleared" if clearing else "Marked"
        self.report({'INFO'}, f"{verb} {count} edges as {mark_label} (angle > {self.sharp_angle}°)")
        self._update_path(context)

    def _build_mode_click(self, context):
        """In BUILD mode: set anchor on first click, apply marks + chain on second."""
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
            target_vi = self._pick_closest_vert_of_face(context, face, obj)
        except (IndexError, AttributeError, ReferenceError):
            return

        if self.anchor_vert_index < 0:
            self.anchor_vert_index = target_vi
            self._update_path(context)
            return

        if target_vi == self.anchor_vert_index:
            return

        # Apply marks on the current preview path, then chain anchor forward.
        self._execute_mark(context)
        self.anchor_vert_index = target_vi
        self._update_path(context)

    def _toggle_path_mode(self, context):
        self.path_mode_idx = (self.path_mode_idx + 1) % len(PATH_MODES)
        if self.path_mode != 'BUILD':
            self.anchor_vert_index = -1
        self._update_path(context)
        self._update_status(context)
        context.area.tag_redraw()

    def _clear_anchor(self, context):
        self.anchor_vert_index = -1
        self._update_path(context)
        self._update_status(context)
        context.area.tag_redraw()

    # ─── Path update ─────────────────────────────────────────────────

    def _update_path(self, context):
        self.path_edge_indices = []
        self.path_coords = []
        self.barrier_coords = []

        self._build_anchor_coords(context)

        obj = self.hit_obj
        if not obj or obj.mode != 'EDIT':
            return

        try:
            bm = bmesh.from_edit_mesh(obj.data)
            self._cache_layers(bm)
            bm.verts.ensure_lookup_table()
            bm.edges.ensure_lookup_table()
            bm.faces.ensure_lookup_table()
            self._ensure_graph_cache(bm)

            if self.path_mode == 'BUILD':
                if self.hit_face_index < 0 or self.hit_face_index >= len(bm.faces):
                    self._target_vert_index = -1
                    return
                face = bm.faces[self.hit_face_index]
                self._target_vert_index = self._pick_closest_vert_of_face(
                    context, face, obj
                )
                self.path_edge_indices = self._compute_path(bm, None)
                self._build_draw_coords(bm, obj)
                self._build_barrier_coords(bm, obj)
            else:
                self._target_vert_index = -1
                if self.hovered_edge_index < 0 or self.hovered_edge_index >= len(bm.edges):
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
        if self._smooth_mode:
            ml = BARRIER_LABELS[self.mark_type]
            n_prop = len(self._smooth_preview_edges)
            n_orig = len(self._smooth_original_marks)
            context.workspace.status_text_set(
                f"Smooth Marked ({ml}): "
                f"[Alt+Wheel] Magnet({self._smooth_magnet:+d}) | "
                f"[Shift+Wheel] Iterations({self._smooth_iterations}) | "
                f"proposal {n_prop} / original {n_orig} edges | "
                f"[Space] Accept | [F/Esc] Cancel"
            )
            return
        bl = BARRIER_LABELS[self.barrier_type]
        ml = BARRIER_LABELS[self.mark_type]
        al = ALGORITHM_LABELS[self.algorithm]
        pm = PATH_MODE_LABELS[self.path_mode]
        n = len(self.path_edge_indices)
        anchor_set = self.anchor_vert_index >= 0
        context.workspace.status_text_set(
            f"Shortest Path Mark: [E] Barrier({bl}) | [R] Mark({ml}) | "
            f"[A] Algorithm({al}) | [Ctrl+Wheel] Flow({self.flow_angle}°) | "
            f"[Shift+Wheel] Smooth({self.smooth_level}) | "
            f"[Ctrl+Shift+Wheel] Curvature({self.curvature}) | "
            f"[Ctrl+Alt+Wheel] Arch({self.arch_strength:+d}) | "
            f"[S] Mark by Angle | [Alt+Wheel] Angle({self.sharp_angle}°) | "
            f"[F] Smooth Marked | "
            f"[Ctrl+Q] Mode({pm}) | [Q] New Mark"
            f"{' (set)' if anchor_set else ''} | "
            f"[LMB] {'Click Start/End' if self.path_mode == 'BUILD' else 'Apply'}"
            f"({n} edges) | [D] Clear Path | "
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
        props.shortest_mark_smooth_level = self.smooth_level
        props.shortest_mark_path_mode_idx = self.path_mode_idx
        props.shortest_mark_curvature = self.curvature

    def _load_scene_props(self, context):
        props = context.scene.IOPS
        self.barrier_type_idx = props.shortest_mark_barrier_idx
        self.mark_type_idx = props.shortest_mark_mark_idx
        self.algorithm_idx = min(
            max(props.shortest_mark_algorithm_idx, 0),
            len(ALGORITHM_TYPES) - 1,
        )
        self.flow_angle = props.shortest_mark_flow_angle
        self.sharp_angle = props.shortest_mark_sharp_angle
        self.smooth_level = props.shortest_mark_smooth_level
        self.path_mode_idx = props.shortest_mark_path_mode_idx
        self.curvature = props.shortest_mark_curvature

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

            # Smooth-marked preview: dropped-original (faded) + proposed (yellow)
            if self._smooth_mode:
                if self._smooth_original_coords:
                    coords = []
                    for a, b in self._smooth_original_coords:
                        coords.extend([a, b])
                    shader.uniform_float("color", SMOOTH_ORIGINAL_COLOR)
                    gpu.state.line_width_set(SMOOTH_ORIGINAL_WIDTH)
                    gpu.state.depth_test_set('ALWAYS')
                    gpu.state.blend_set('ALPHA')
                    batch = batch_for_shader(shader, 'LINES', {"pos": coords})
                    batch.draw(shader)
                if self._smooth_preview_coords:
                    coords = []
                    for a, b in self._smooth_preview_coords:
                        coords.extend([a, b])
                    shader.uniform_float("color", SMOOTH_PREVIEW_COLOR)
                    gpu.state.line_width_set(SMOOTH_PREVIEW_WIDTH)
                    gpu.state.depth_test_set('ALWAYS')
                    gpu.state.blend_set('ALPHA')
                    batch = batch_for_shader(shader, 'LINES', {"pos": coords})
                    batch.draw(shader)

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

            # Anchor dot (build mode)
            if self.anchor_coords:
                shader.uniform_float("color", ANCHOR_COLOR)
                gpu.state.point_size_set(ANCHOR_SIZE)
                gpu.state.depth_test_set('ALWAYS')
                ab = batch_for_shader(
                    shader, 'POINTS', {"pos": self.anchor_coords}
                )
                ab.draw(shader)

            # Hover highlight: target vertex (Build) or edge (Direction)
            if self.hit_obj and self.hit_obj.mode == 'EDIT':
                try:
                    obj = self.hit_obj
                    bm = bmesh.from_edit_mesh(obj.data)
                    if (self.path_mode == 'BUILD'
                            and self._target_vert_index >= 0):
                        bm.verts.ensure_lookup_table()
                        if self._target_vert_index < len(bm.verts):
                            v = bm.verts[self._target_vert_index]
                            p = obj.matrix_world @ v.co.copy()
                            shader.uniform_float("color", HOVER_COLOR)
                            gpu.state.point_size_set(ANCHOR_SIZE)
                            tb = batch_for_shader(
                                shader, 'POINTS', {"pos": [p]}
                            )
                            tb.draw(shader)
                    elif self.path_mode != 'BUILD' and self.hovered_edge_index >= 0:
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
            gpu.state.point_size_set(1.0)
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
        pm = PATH_MODE_LABELS[self.path_mode]
        n = len(self.path_edge_indices)
        anchor_set = self.anchor_vert_index >= 0

        if self._smooth_mode:
            n_prop = len(self._smooth_preview_edges)
            n_orig = len(self._smooth_original_marks)
            lines = (
                (f"Smooth Marked: {ml}", ""),
                (f"Magnet: {self._smooth_magnet:+d}", "Alt+Wheel"),
                (f"Iterations: {self._smooth_iterations}", "Shift+Wheel"),
                (f"Proposal: {n_prop} / Orig: {n_orig}", ""),
                ("Accept", "Space"),
                ("Cancel sub-mode", "F / Esc"),
            )
        else:
            apply_label = (
                "Click Start/End" if self.path_mode == 'BUILD' else "Apply"
            )
            clear_anchor_label = (
                "New Mark (anchor set)" if anchor_set else "New Mark"
            )

            lines = (
                (f"Barrier: {bl}", "E"),
                (f"Mark: {ml}", "R"),
                (f"Algorithm: {al}", "A"),
                (f"Flow: {self.flow_angle}\u00b0", "Ctrl+Wheel"),
                (f"Smooth: {self.smooth_level}", "Shift+Wheel"),
                (f"Curvature: {self.curvature}", "Ctrl+Shift+Wheel"),
                (f"Arch: {self.arch_strength:+d}", "Ctrl+Alt+Wheel"),
                (f"Mark Angle: {self.sharp_angle}\u00b0", "Alt+Wheel"),
                ("Mark by Angle", "S"),
                ("Smooth Marked", "F"),
                (f"Mode: {pm}", "Ctrl+Q"),
                (clear_anchor_label, "Q"),
                (f"{apply_label} ({n} edges)", "LMB"),
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
        self.anchor_vert_index = -1
        self.anchor_coords = []
        self._target_vert_index = -1
        self.smooth_level = 0
        self.curvature = 0
        self.path_mode_idx = 1

        self._load_scene_props(context)
        # Force Mark (Build) mode as default on every invoke
        self.path_mode_idx = 1
        self._invalidate_graph_cache()

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

        # ── Smooth-marked sub-mode — handled first, blocks normal path modes ──
        if self._smooth_mode:
            # Alt+Wheel: adjust magnet (concave <-> convex bias)
            if event.type in {'WHEELUPMOUSE', 'WHEELDOWNMOUSE'} and event.alt and not event.ctrl and not event.shift:
                if event.type == 'WHEELUPMOUSE':
                    self._smooth_magnet = min(
                        self._smooth_magnet + SMOOTH_MAGNET_STEP, SMOOTH_MAGNET_RANGE
                    )
                else:
                    self._smooth_magnet = max(
                        self._smooth_magnet - SMOOTH_MAGNET_STEP, -SMOOTH_MAGNET_RANGE
                    )
                self._refresh_smooth_preview(context)
                self._update_status(context)
                context.area.tag_redraw()
                return {'RUNNING_MODAL'}
            # Shift+Wheel: adjust iteration count
            if event.type in {'WHEELUPMOUSE', 'WHEELDOWNMOUSE'} and event.shift and not event.ctrl and not event.alt:
                if event.type == 'WHEELUPMOUSE':
                    self._smooth_iterations = min(
                        self._smooth_iterations + SMOOTH_ITER_STEP, MAX_SMOOTH_ITERATIONS
                    )
                else:
                    self._smooth_iterations = max(
                        self._smooth_iterations - SMOOTH_ITER_STEP, 1
                    )
                self._refresh_smooth_preview(context)
                self._update_status(context)
                context.area.tag_redraw()
                return {'RUNNING_MODAL'}
            # Commit
            if event.type in {'SPACE', 'RET', 'NUMPAD_ENTER'} and event.value == 'PRESS':
                self._exit_smooth_mode(context, commit=True)
                return {'RUNNING_MODAL'}
            # Cancel / exit without committing (F or Esc)
            if event.type in {'F', 'ESC'} and event.value == 'PRESS':
                self._exit_smooth_mode(context, commit=False)
                return {'RUNNING_MODAL'}
            # Allow viewport navigation
            if event.type in {'MIDDLEMOUSE', 'WHEELUPMOUSE', 'WHEELDOWNMOUSE'}:
                return {'PASS_THROUGH'}
            if event.type == 'MOUSEMOVE':
                return {'PASS_THROUGH'}
            # Swallow all other keys while in sub-mode
            return {'RUNNING_MODAL'}

        # Enter smooth-marked sub-mode
        if (event.type == 'F' and event.value == 'PRESS'
                and not event.ctrl and not event.shift and not event.alt):
            self._enter_smooth_mode(context)
            return {'RUNNING_MODAL'}

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

        # Ctrl+Alt+Scroll – adjust arch / bending (BUILD mode: bends path off straight line)
        if event.type in {'WHEELUPMOUSE', 'WHEELDOWNMOUSE'} and event.ctrl and event.alt and not event.shift:
            if event.type == 'WHEELUPMOUSE':
                self.arch_strength = min(self.arch_strength + ARCH_STEP, MAX_ARCH)
            else:
                self.arch_strength = max(self.arch_strength - ARCH_STEP, -MAX_ARCH)
            self._update_path(context)
            self._update_status(context)
            context.area.tag_redraw()
            return {'RUNNING_MODAL'}

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
                        new_edge_idx = self._closest_edge_in_face(
                            context, event, face, obj
                        )
                        if self.path_mode == 'BUILD':
                            new_tgt = self._pick_closest_vert_of_face(
                                context, face, obj
                            )
                            if (new_tgt != self._target_vert_index
                                    or new_edge_idx != self.hovered_edge_index):
                                self.hovered_edge_index = new_edge_idx
                                self._update_path(context)
                                self._update_status(context)
                        else:
                            if new_edge_idx != self.hovered_edge_index:
                                self.hovered_edge_index = new_edge_idx
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

        # New Mark: clear build-mode anchor to start a fresh chain
        elif (
            event.type == 'Q'
            and event.value == 'PRESS'
            and not event.ctrl
            and not event.shift
        ):
            self._clear_anchor(context)
            return {'RUNNING_MODAL'}

        # Toggle path mode (Direction <-> Build)
        elif (
            event.type == 'Q'
            and event.value == 'PRESS'
            and event.ctrl
            and not event.shift
        ):
            self._toggle_path_mode(context)
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

        # LMB: apply marks (Direction) or click start/end (Build)
        elif event.type == 'LEFTMOUSE' and event.value == 'PRESS':
            if self.path_mode == 'BUILD':
                self._build_mode_click(context)
            else:
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
            self.anchor_vert_index = -1
            bpy.ops.ed.undo()
            self._invalidate_graph_cache()
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
