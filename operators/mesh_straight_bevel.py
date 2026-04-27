import bpy
import bmesh
import math
import blf
import gpu
from gpu_extras.batch import batch_for_shader
from bpy_extras import view3d_utils
from bpy.props import FloatProperty
from mathutils.geometry import intersect_line_line


EPS = 1e-5


_ACTIVE_HANDLES = set()


def _purge_handles():
    """Remove any stale draw handlers left behind by a previous reload."""
    while _ACTIVE_HANDLES:
        h = _ACTIVE_HANDLES.pop()
        try:
            bpy.types.SpaceView3D.draw_handler_remove(h, "WINDOW")
        except (ValueError, RuntimeError):
            pass


DIGIT_TYPES = {
    "ZERO": "0", "ONE": "1", "TWO": "2", "THREE": "3", "FOUR": "4",
    "FIVE": "5", "SIX": "6", "SEVEN": "7", "EIGHT": "8", "NINE": "9",
    "NUMPAD_0": "0", "NUMPAD_1": "1", "NUMPAD_2": "2", "NUMPAD_3": "3",
    "NUMPAD_4": "4", "NUMPAD_5": "5", "NUMPAD_6": "6", "NUMPAD_7": "7",
    "NUMPAD_8": "8", "NUMPAD_9": "9",
}


# --------------------------------------------------------------------------
# Geometry helpers
# --------------------------------------------------------------------------


def _find_hit_vert(face, start_vert, cut_dir):
    """Hit search from a BMVert — excludes edges sharing the start vert."""
    best = None
    best_t = float("inf")
    for edge in face.edges:
        if start_vert in edge.verts:
            continue
        a, b = edge.verts[0].co, edge.verts[1].co
        res = intersect_line_line(start_vert.co, start_vert.co + cut_dir, a, b)
        if res is None:
            continue
        p1, p2 = res
        if (p1 - p2).length > 1e-4:
            continue
        t = (p1 - start_vert.co).dot(cut_dir)
        if t <= EPS:
            continue
        seg = b - a
        l2 = seg.length_squared
        if l2 < 1e-12:
            continue
        u = (p1 - a).dot(seg) / l2
        if u < -EPS or u > 1 + EPS:
            continue
        u = max(0.0, min(1.0, u))
        if t < best_t:
            best_t = t
            best = (edge, u)
    return best


def _find_hit_point(face, start_co, exclude_edge, corner_vert, cut_dir):
    """Hit search from a free 3D point on the neighbour edge — used for preview."""
    best = None
    best_t = float("inf")
    for edge in face.edges:
        if edge is exclude_edge:
            continue
        if corner_vert in edge.verts:
            continue
        a, b = edge.verts[0].co, edge.verts[1].co
        res = intersect_line_line(start_co, start_co + cut_dir, a, b)
        if res is None:
            continue
        p1, p2 = res
        if (p1 - p2).length > 1e-4:
            continue
        t = (p1 - start_co).dot(cut_dir)
        if t <= EPS:
            continue
        seg = b - a
        l2 = seg.length_squared
        if l2 < 1e-12:
            continue
        u = (p1 - a).dot(seg) / l2
        if u < -EPS or u > 1 + EPS:
            continue
        u = max(0.0, min(1.0, u))
        if t < best_t:
            best_t = t
            best = (edge, u, p1.copy())
    return best


def _connected(v1, v2):
    return any(v2 in e.verts for e in v1.link_edges)


# --------------------------------------------------------------------------
# Operator
# --------------------------------------------------------------------------


class IOPS_OT_straight_bevel(bpy.types.Operator):
    """Bevel the ends of selected edges with perpendicular cuts across the adjacent faces"""

    bl_idname = "iops.mesh_straight_bevel"
    bl_label = "Straight Bevel"
    bl_description = (
        "At each endpoint of a selected edge, slide `offset` along the "
        "neighbouring edge (away from the corner) and drop a perpendicular "
        "cut across the adjacent face. Mouse drag adjusts offset"
    )
    bl_options = {"REGISTER", "UNDO"}

    offset: FloatProperty(
        name="Offset",
        description="Distance along the neighbouring edge from the corner where the perpendicular cut starts",
        default=0.05,
        min=0.0,
        soft_max=10.0,
        step=1,
        precision=4,
        subtype="DISTANCE",
    )

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.type == "MESH" and obj.mode == "EDIT"

    # ------------------------------------------------------------------
    # Modal lifecycle
    # ------------------------------------------------------------------

    def invoke(self, context, event):
        obj = context.active_object
        me = obj.data
        self._bm = bmesh.from_edit_mesh(me)
        bm = self._bm
        bm.edges.ensure_lookup_table()
        bm.faces.ensure_lookup_table()
        bm.normal_update()

        selected = [e for e in bm.edges if e.select and len(e.link_faces) > 0]
        if not selected:
            self.report({"WARNING"}, "Select at least one edge with an adjacent face")
            return {"CANCELLED"}

        self._collect_jobs(bm, selected)
        if not self._preview_jobs:
            self.report({"WARNING"}, "No valid corners for bevel")
            return {"CANCELLED"}

        # Sensitivity baseline: 1/4 of avg neighbour-edge length per 100px.
        avg_L = sum(j["direction"].length for j in self._preview_jobs) / len(self._preview_jobs)
        self._pixel_to_offset = max(avg_L * 0.25 / 100.0, 1e-4)

        # Hard cap on user offset: the smallest neighbour-edge length
        # minus that vert's propagation base, across EVERY (v, oe)
        # pair in face_pairs (not just the deduped preview_jobs list).
        # Multi-rail corners — the same vert with two different
        # non-selected edges in different faces — would otherwise
        # bypass the cap on whichever rail wasn't picked for the
        # preview job. Once any cut point would reach an existing
        # rail/face vertex the offset stops growing.
        cap = float("inf")
        base = getattr(self, "_vert_offset_base", {})
        face_pairs = getattr(self, "_face_pairs", {})
        for face, pair in face_pairs.items():
            for v, oe, direction, _e in pair:
                L = direction.length
                if L < 1e-9:
                    continue
                allowed = L - base.get(v, 0.0)
                if allowed < cap:
                    cap = allowed
        self._max_user_offset = cap if cap != float("inf") else None

        self._obj = obj
        self._mouse_start_x = event.mouse_region_x
        self._initial_offset = self.offset
        self._input_str = ""

        _purge_handles()

        self._shader = gpu.shader.from_builtin("UNIFORM_COLOR")
        self._handle = bpy.types.SpaceView3D.draw_handler_add(
            self._draw_callback, (context,), "WINDOW", "POST_PIXEL")
        _ACTIVE_HANDLES.add(self._handle)

        context.workspace.status_text_set(self._status_text())
        context.window_manager.modal_handler_add(self)
        if context.area:
            context.area.tag_redraw()
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        if context.area:
            context.area.tag_redraw()

        if (event.type in {"MIDDLEMOUSE", "WHEELUPMOUSE", "WHEELDOWNMOUSE"}
                or event.type.startswith("NDOF")):
            return {"PASS_THROUGH"}

        if event.type == "MOUSEMOVE" and not self._input_str:
            delta = event.mouse_region_x - self._mouse_start_x
            sensitivity = self._pixel_to_offset
            if event.shift:
                sensitivity *= 0.1  # precise mode
            new_offset = self._initial_offset + delta * sensitivity
            if event.ctrl:
                new_offset = round(new_offset / 0.1) * 0.1  # snap to 0.1
            new_offset = max(0.0, new_offset)
            cap = getattr(self, "_max_user_offset", None)
            if cap is not None:
                new_offset = min(new_offset, cap)
            self.offset = new_offset
            context.workspace.status_text_set(self._status_text())
            return {"RUNNING_MODAL"}

        if event.value == "PRESS":
            if event.type in DIGIT_TYPES:
                self._input_str += DIGIT_TYPES[event.type]
                self._sync_typed_offset()
                context.workspace.status_text_set(self._status_text())
                return {"RUNNING_MODAL"}

            if event.type in {"PERIOD", "NUMPAD_PERIOD"}:
                if "." not in self._input_str:
                    self._input_str += "."
                    context.workspace.status_text_set(self._status_text())
                return {"RUNNING_MODAL"}

            if event.type == "BACK_SPACE":
                self._input_str = self._input_str[:-1]
                self._sync_typed_offset()
                context.workspace.status_text_set(self._status_text())
                return {"RUNNING_MODAL"}

            if event.type in {"LEFTMOUSE", "RET", "NUMPAD_ENTER", "SPACE"}:
                self._finish(context)
                return self.execute(context)

            if event.type in {"RIGHTMOUSE", "ESC"}:
                self.offset = self._initial_offset
                self._finish(context)
                return {"CANCELLED"}

        return {"RUNNING_MODAL"}

    def _sync_typed_offset(self):
        if self._input_str and self._input_str not in (".",):
            try:
                self.offset = max(0.0, float(self._input_str))
            except ValueError:
                pass

    def _finish(self, context):
        h = getattr(self, "_handle", None)
        if h is not None:
            _ACTIVE_HANDLES.discard(h)
            try:
                bpy.types.SpaceView3D.draw_handler_remove(h, "WINDOW")
            except (ValueError, RuntimeError):
                pass
            self._handle = None
        context.workspace.status_text_set(None)
        if context.area:
            context.area.tag_redraw()
        # Drop the bmesh wrapper and every dict/list keyed on BMElements.
        # Blender keeps finished operator instances in the redo stack; if
        # the addon is later reloaded (blinker timer fires), those stale
        # bmesh references are dealloc'd against freed mesh data and
        # crash in bpy_bmesh_dealloc → CustomData_free_layer_active.
        self._bm = None
        self._obj = None
        self._vert_offset_base = {}
        self._face_pairs = {}
        self._preview_jobs = []
        self._per_edge_cap = {}

    def _status_text(self):
        typed = f" | typing: {self._input_str}" if self._input_str else ""
        return (
            f"Straight Bevel: offset = {self.offset:.4f}{typed} | "
            "[Mouse] drag | [Ctrl] snap 0.1 | [Shift] precise | "
            "[0-9 .] type | [Backspace] del | "
            "[Enter/LMB] confirm | [Esc/RMB] cancel"
        )

    # ------------------------------------------------------------------
    # Preview
    # ------------------------------------------------------------------

    def _collect_jobs(self, bm, selected):
        selected_set = set(selected)

        # Build components and shared_verts (open-path interior suppression).
        parent = {e: e for e in selected}

        def _fp(x):
            while parent[x] is not x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        def _up(a, b):
            ra, rb = _fp(a), _fp(b)
            if ra is not rb:
                parent[ra] = rb

        for e in selected:
            for v in e.verts:
                for e2 in v.link_edges:
                    if e2 is not e and e2 in selected_set:
                        _up(e, e2)

        components = {}
        for e in selected:
            components.setdefault(_fp(e), []).append(e)

        shared_verts = set()
        for comp in components.values():
            if len(comp) < 2:
                continue
            counts = {}
            for e in comp:
                for v in e.verts:
                    counts[v] = counts.get(v, 0) + 1
            endpoints = [v for v, c in counts.items() if c == 1]
            if len(endpoints) == 2:
                for v, c in counts.items():
                    if v in endpoints or c != 2:
                        continue
                    sel_at = [ee for ee in v.link_edges if ee in selected_set]
                    if len(sel_at) != 2:
                        continue
                    d1 = sel_at[0].other_vert(v).co - v.co
                    d2 = sel_at[1].other_vert(v).co - v.co
                    if d1.length < 1e-9 or d2.length < 1e-9:
                        continue
                    if abs(d1.normalized().dot(d2.normalized()) + 1.0) < 1e-3:
                        shared_verts.add(v)

        # Face-pair structure for preview drawing.
        face_pairs = {}
        for e in selected:
            for v in e.verts:
                if v in shared_verts:
                    continue
                for face in e.link_faces:
                    oe = next(
                        (ee for ee in v.link_edges
                         if face in ee.link_faces and ee is not e and ee not in selected_set),
                        None,
                    )
                    if oe is None:
                        continue
                    direction = oe.other_vert(v).co - v.co
                    if direction.length < 1e-9:
                        continue
                    face_pairs.setdefault(face, []).append((v, oe, direction.copy(), e))

        # Propagate offsets around each component (same algorithm as execute).
        sel_adj = {}
        for e in selected:
            for v in e.verts:
                sel_adj.setdefault(v, []).append((e.other_vert(v), e))

        self._vert_offset_base = {}  # v -> correction relative to the component's minimum
        for comp_edges in components.values():
            comp_set = set(comp_edges)
            comp_verts = set()
            for e in comp_edges:
                comp_verts.update(e.verts)
            start = None
            for v in comp_verts:
                if v not in shared_verts:
                    start = v
                    break
            if start is None:
                start = next(iter(comp_verts))
            comp_offsets = {start: 0.0}
            visited = set()
            queue = [start]
            while queue:
                current = queue.pop()
                cur = comp_offsets[current]
                for other, ridge in sel_adj.get(current, []):
                    if ridge not in comp_set or ridge in visited:
                        continue
                    visited.add(ridge)
                    correction = 0.0
                    for face in ridge.link_faces:
                        fe = [
                            ee for ee in current.link_edges
                            if face in ee.link_faces and ee is not ridge
                            and ee not in selected_set
                        ]
                        if not fe:
                            continue
                        d = fe[0].other_vert(current).co - current.co
                        if d.length < 1e-9:
                            continue
                        correction = (other.co - current.co).dot(-(d.normalized()))
                        break
                    comp_offsets[other] = cur + correction
                    queue.append(other)
            if comp_offsets:
                min_off = min(comp_offsets.values())
                for v, o in comp_offsets.items():
                    self._vert_offset_base[v] = o - min_off

        self._face_pairs = face_pairs
        # Legacy fields for draw pipeline compatibility.
        self._preview_jobs = []
        for face, pair in face_pairs.items():
            for v, oe, direction, e in pair:
                self._preview_jobs.append({
                    "corner": v, "face": face,
                    "neighbour": oe, "direction": direction,
                    "selected": e,
                })
        self._per_edge_cap = {}

    def _preview_segments(self):
        segments = []
        face_pairs = getattr(self, "_face_pairs", {})
        base = getattr(self, "_vert_offset_base", {})
        user_o = max(self.offset, 0.0)
        for face, pair in face_pairs.items():
            if not face.is_valid:
                continue
            # Group entries by selected ridge edge so a face with N ridges
            # produces N preview segments (one perpendicular cut per ridge).
            by_ridge = {}
            for entry in pair:
                by_ridge.setdefault(entry[3], []).append(entry)
            for ridge_entries in by_ridge.values():
                if len(ridge_entries) != 2:
                    continue
                cos = []
                ok = True
                for v, oe, direction, _e in ridge_entries:
                    if not (v.is_valid and oe.is_valid):
                        ok = False
                        break
                    L = direction.length
                    if L < 1e-9:
                        ok = False
                        break
                    s = user_o + base.get(v, 0.0)
                    s = min(max(s, 0.0), L * 0.99)
                    cos.append(v.co + (direction / L) * s)
                if not ok or len(cos) != 2:
                    continue
                segments.append((cos[0].copy(), cos[1].copy()))
        return segments

    def _draw_callback(self, context):
        region = context.region
        rv3d = context.region_data
        if rv3d is None:
            return

        # Guard against blinker (and any in-place addon reload) freeing
        # this operator's RNA struct while the draw handler is still
        # registered. Touching any attribute through path_resolve
        # raises ReferenceError; self-remove the handle and bail.
        try:
            mw = self._obj.matrix_world
        except (ReferenceError, AttributeError):
            h = getattr(self, "_handle", None)
            if h is not None:
                _ACTIVE_HANDLES.discard(h)
                try:
                    bpy.types.SpaceView3D.draw_handler_remove(h, "WINDOW")
                except (ValueError, RuntimeError, ReferenceError):
                    pass
            return
        segs_2d = []
        endpoints_2d = []
        for a, b in self._preview_segments():
            pa = view3d_utils.location_3d_to_region_2d(region, rv3d, mw @ a)
            pb = view3d_utils.location_3d_to_region_2d(region, rv3d, mw @ b)
            if pa is None or pb is None:
                continue
            segs_2d.extend([pa, pb])
            endpoints_2d.append(pa)
            endpoints_2d.append(pb)

        if segs_2d:
            gpu.state.blend_set("ALPHA")
            gpu.state.line_width_set(2.0)
            self._shader.bind()
            self._shader.uniform_float("color", (1.0, 0.7, 0.2, 1.0))
            batch = batch_for_shader(self._shader, "LINES", {"pos": segs_2d})
            batch.draw(self._shader)

            segs = 24
            radius = 6.0
            tris = []
            for ep in endpoints_2d:
                cx, cy = ep
                ring = [
                    (cx + math.cos(2 * math.pi * i / segs) * radius,
                     cy + math.sin(2 * math.pi * i / segs) * radius)
                    for i in range(segs)
                ]
                for i in range(segs):
                    j = (i + 1) % segs
                    tris.extend([(cx, cy), ring[i], ring[j]])
            if tris:
                batch = batch_for_shader(self._shader, "TRIS", {"pos": tris})
                batch.draw(self._shader)

            gpu.state.line_width_set(1.0)
            gpu.state.blend_set("NONE")

        font_id = 0
        try:
            prefs = context.preferences.addons["InteractionOps"].preferences
            tCSize = getattr(prefs, "text_size", 18)
            tCPosX = getattr(prefs, "text_pos_x", 30)
            tCPosY = getattr(prefs, "text_pos_y", 90)
            tColor = getattr(prefs, "text_color", (1.0, 1.0, 1.0, 1.0))
        except (KeyError, AttributeError):
            tCSize, tCPosX, tCPosY = 18, 30, 90
            tColor = (1.0, 1.0, 1.0, 1.0)
        ui = context.preferences.system.ui_scale
        blf.size(font_id, int(tCSize * ui))
        blf.color(font_id, *tColor)
        blf.position(font_id, tCPosX * ui, tCPosY * ui, 0)
        label = f"Straight Bevel: {self.offset:.4f}"
        if self._input_str:
            label += f"  (typing: {self._input_str})"
        blf.draw(font_id, label)

    # ------------------------------------------------------------------
    # Execute (topology change)
    # ------------------------------------------------------------------

    def execute(self, context):
        obj = context.active_object
        me = obj.data
        bm = bmesh.from_edit_mesh(me)

        selected = [e for e in bm.edges if e.select]
        if not selected:
            self.report({"WARNING"}, "No edges selected")
            return {"CANCELLED"}

        offset = self.offset

        selected_set = set(selected)

        # Build components first so we can tell open paths (shared interior
        # verts suppressed) from closed loops (every vert needs a cut).
        _parent = {e: e for e in selected}

        def _fp(x):
            while _parent[x] is not x:
                _parent[x] = _parent[_parent[x]]
                x = _parent[x]
            return x

        def _up(a, b):
            ra, rb = _fp(a), _fp(b)
            if ra is not rb:
                _parent[ra] = rb

        for _e in selected:
            for _v in _e.verts:
                for _e2 in _v.link_edges:
                    if _e2 is not _e and _e2 in selected_set:
                        _up(_e, _e2)

        _components_pre = {}
        for _e in selected:
            _components_pre.setdefault(_fp(_e), []).append(_e)

        shared_verts = set()
        for _comp in _components_pre.values():
            if len(_comp) < 2:
                continue
            _counts = {}
            for _e in _comp:
                for _v in _e.verts:
                    _counts[_v] = _counts.get(_v, 0) + 1
            _endpoints = [v for v, c in _counts.items() if c == 1]
            # Only suppress an intermediate vert if its two selected edges are
            # colinear (anti-parallel). A corner in the path (staircase) needs
            # its own cut. Closed loops (no endpoints) never suppress.
            if len(_endpoints) == 2:
                for _v, _c in _counts.items():
                    if _v in _endpoints or _c != 2:
                        continue
                    _sel_at = [
                        _e for _e in _v.link_edges if _e in selected_set
                    ]
                    if len(_sel_at) != 2:
                        continue
                    _d1 = _sel_at[0].other_vert(_v).co - _v.co
                    _d2 = _sel_at[1].other_vert(_v).co - _v.co
                    if _d1.length < 1e-9 or _d2.length < 1e-9:
                        continue
                    _dot = _d1.normalized().dot(_d2.normalized())
                    if abs(_dot + 1.0) < 1e-3:
                        shared_verts.add(_v)

        # Find neighbour edge at each (vert, face) for each ridge edge.
        # Collect per-face pairs (v1, oe1, v2, oe2) so we can compute offsets
        # that yield perpendicular cuts.
        face_pairs = {}  # face -> [(v, oe), (v, oe)]
        for e in selected:
            for v in e.verts:
                if v in shared_verts:
                    continue
                for face in e.link_faces:
                    face_edges_at_v = [
                        oe for oe in v.link_edges
                        if face in oe.link_faces and oe is not e and oe not in selected_set
                    ]
                    if not face_edges_at_v:
                        continue
                    oe = face_edges_at_v[0]
                    direction = oe.other_vert(v).co - v.co
                    if direction.length < 1e-9:
                        continue
                    face_pairs.setdefault(face, []).append((v, oe, direction.copy(), e))

        # Propagate offsets around each selected-edge component. At each
        # ridge edge (v1, v2) in a chosen reference face, compute the
        # correction and set offset_v2 = offset_v1 + correction. Subdivision
        # verts along axis-aligned segments inherit their connected corner's
        # offset; diagonal segments shift by the correction amount.

        # Build adjacency in selected_set: vert -> list of (other_vert, edge).
        sel_adj = {}
        for e in selected:
            for v in e.verts:
                sel_adj.setdefault(v, []).append((e.other_vert(v), e))

        vert_offset = {}  # v -> propagated offset

        for comp_key, comp_edges in _components_pre.items():
            comp_set = set(comp_edges)
            comp_verts = set()
            for e in comp_edges:
                comp_verts.update(e.verts)

            # Pick a starting vert (endpoint for open path; any for closed loop).
            start = None
            for v in comp_verts:
                if v not in shared_verts:
                    start = v
                    break
            if start is None:
                start = next(iter(comp_verts))
            comp_offsets = {start: 0.0}

            visited_edges = set()
            queue = [start]
            while queue:
                current = queue.pop()
                cur_off = comp_offsets.get(current, 0.0)
                for other, ridge in sel_adj.get(current, []):
                    if ridge not in comp_set or ridge in visited_edges:
                        continue
                    visited_edges.add(ridge)
                    correction = 0.0
                    for face in ridge.link_faces:
                        fe_at_cur = [
                            oe for oe in current.link_edges
                            if face in oe.link_faces and oe is not ridge
                            and oe not in selected_set
                        ]
                        if not fe_at_cur:
                            continue
                        oe = fe_at_cur[0]
                        d = oe.other_vert(current).co - current.co
                        if d.length < 1e-9:
                            continue
                        d_n = d.normalized()
                        correction = (other.co - current.co).dot(-d_n)
                        break
                    comp_offsets[other] = cur_off + correction
                    queue.append(other)

            # Shift so min = user_offset (inner side gets user_offset).
            if comp_offsets:
                min_off = min(comp_offsets.values())
                for v, o in comp_offsets.items():
                    vert_offset[v] = (o - min_off) + offset

        # Build offsets_at per (v, oe).
        offsets_at = {}
        for v, s in vert_offset.items():
            if s <= EPS:
                continue
            for face in v.link_faces:
                ridge_in_face = [e for e in v.link_edges
                                 if e in selected_set and face in e.link_faces]
                if not ridge_in_face:
                    continue
                fe_at_v = [
                    oe for oe in v.link_edges
                    if face in oe.link_faces and oe not in selected_set
                ]
                if not fe_at_v:
                    continue
                oe = fe_at_v[0]
                L = (oe.other_vert(v).co - v.co).length
                # Stop at the neighbour vertex if the offset would
                # reach or exceed it: snap to L exactly so _get_start
                # returns the existing vert instead of producing a
                # near-zero-length split. This prevents the cut from
                # crossing past an existing vertex.
                clamped = min(max(s, 0.0), L)
                key = (v, oe)
                if key not in offsets_at or clamped > offsets_at[key]:
                    offsets_at[key] = clamped

        split_cache = {}

        def _get_start(v, oe):
            key = (v, oe)
            if key in split_cache:
                return split_cache[key]
            s = offsets_at.get(key)
            if s is None or s <= EPS:
                split_cache[key] = v
                return v
            L = (oe.other_vert(v).co - v.co).length
            if L < 1e-9:
                split_cache[key] = v
                return v
            # Cut hits the neighbour vertex: don't split, reuse the
            # existing vert so connect_vert_pair stitches to it cleanly.
            if s >= L - EPS:
                other = oe.other_vert(v)
                split_cache[key] = other
                return other
            if oe.verts[0] is v or oe.verts[1] is v:
                _, nv = bmesh.utils.edge_split(oe, v, s / L)
                split_cache[key] = nv
                return nv
            split_cache[key] = v
            return v

        corner_jobs_ext = []
        for face, pair in face_pairs.items():
            for v, oe, direction, sel_edge in pair:
                start = _get_start(v, oe)
                corner_jobs_ext.append((v, face, oe, direction, sel_edge, start))

        # Build connected components of selected edges (path detection).
        parent = {e: e for e in selected}

        def _find(x):
            while parent[x] is not x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        def _union(a, b):
            ra, rb = _find(a), _find(b)
            if ra is not rb:
                parent[ra] = rb

        for e in selected:
            for v in e.verts:
                for e2 in v.link_edges:
                    if e2 is not e and e2 in selected_set:
                        _union(e, e2)

        components = {}
        for e in selected:
            components.setdefault(_find(e), []).append(e)

        new_edges = []
        handled_faces = set()

        # Pass 1: direct connect. For each face with exactly 2 corner jobs,
        # connect_vert_pair between their start verts. Keeps topology clean
        # (no ngons) and produces perpendicular cuts when the two neighbour
        # directions are parallel (typical bevel scenarios).
        def _face_has_vert(face, target):
            if not face.is_valid:
                return False
            for fv in face.verts:
                if fv is target:
                    return True
            return False

        face_groups = {}
        for j in corner_jobs_ext:
            face_groups.setdefault(j[1], []).append(j)
        for face, jobs_here in face_groups.items():
            # Group jobs in this face by their selected ridge edge.
            # A face hosting N ridges produces N independent perpendicular cuts;
            # the original "exactly 2 jobs" rule only handled the N=1 case.
            by_ridge = {}
            for j in jobs_here:
                by_ridge.setdefault(j[4], []).append(j)
            for ridge_jobs in by_ridge.values():
                if len(ridge_jobs) != 2:
                    continue
                s1 = ridge_jobs[0][5]
                s2 = ridge_jobs[1][5]
                if s1 is None or s2 is None:
                    continue
                if not (s1.is_valid and s2.is_valid):
                    continue
                if s1 is s2:
                    continue
                if _connected(s1, s2):
                    # Both ridge endpoints reached existing verts
                    # already joined by an edge — typically the
                    # opposite face edge when offset hits its max on
                    # both sides of a perpendicular ridge. Select that
                    # existing edge as the cut so the result is visible
                    # instead of silently producing nothing.
                    for e in s1.link_edges:
                        if e.other_vert(s1) is s2:
                            new_edges.append(e)
                            break
                    continue
                res = bmesh.ops.connect_vert_pair(bm, verts=[s1, s2])
                new_edges.extend(res.get("edges", []))
            handled_faces.add(face)

        # Pass 2: path-chain for multi-edge open paths.
        for component in components.values():
            comp_set = set(component)

            if len(component) == 1:
                continue  # handled by face-pair

            # Multi-edge path: sort edges from one endpoint to the other.
            comp_verts = set()
            for e in component:
                for v in e.verts:
                    comp_verts.add(v)
            endpoints = [v for v in comp_verts if v not in shared_verts]
            if len(endpoints) != 2:
                continue

            # Walk the path.
            start_v = endpoints[0]
            path_edges = []
            current_v = start_v
            current_e = next((e for e in component if start_v in e.verts), None)
            if current_e is None:
                continue
            visited = set()
            end_v = None
            while current_e is not None and current_e not in visited:
                path_edges.append(current_e)
                visited.add(current_e)
                next_v = current_e.other_vert(current_v)
                if next_v not in shared_verts:
                    end_v = next_v
                    break
                nxt = None
                for e2 in next_v.link_edges:
                    if e2 in comp_set and e2 not in visited:
                        nxt = e2
                        break
                current_e = nxt
                current_v = next_v
            if end_v is None:
                continue

            # For each face-side of the first edge, walk the face strip.
            for first_face in path_edges[0].link_faces:
                strip = [first_face]
                ok = True
                for i in range(1, len(path_edges)):
                    prev_face = strip[-1]
                    candidates = [f for f in path_edges[i].link_faces if f is not prev_face]
                    if not candidates:
                        candidates = list(path_edges[i].link_faces)
                    best = None
                    prev_edge_set = set(prev_face.edges)
                    for f in candidates:
                        if set(f.edges) & prev_edge_set:
                            best = f
                            break
                    if best is None:
                        ok = False
                        break
                    strip.append(best)
                if not ok or len(strip) != len(path_edges):
                    continue

                start_oe = next(
                    (e for e in start_v.link_edges
                     if strip[0] in e.link_faces and e is not path_edges[0]
                     and e not in selected_set),
                    None,
                )
                end_oe = next(
                    (e for e in end_v.link_edges
                     if strip[-1] in e.link_faces and e is not path_edges[-1]
                     and e not in selected_set),
                    None,
                )
                if start_oe is None or end_oe is None:
                    continue
                s_start = next(
                    (j[5] for j in corner_jobs_ext
                     if j[0] is start_v and j[2] is start_oe),
                    start_v,
                )
                s_end = next(
                    (j[5] for j in corner_jobs_ext
                     if j[0] is end_v and j[2] is end_oe),
                    end_v,
                )
                if s_start is None or s_end is None:
                    continue
                if not (s_start.is_valid and s_end.is_valid):
                    continue

                # Build chain of verts across the strip.
                chain = [s_start]
                ok = True
                for i in range(len(strip) - 1):
                    prev_face = strip[i]
                    next_face = strip[i + 1]
                    shared_edge = next(
                        (e for e in prev_face.edges if e in next_face.edges), None
                    )
                    if shared_edge is None:
                        ok = False
                        break

                    # Cut line: parallel to the selected edge in prev_face, offset o
                    # perpendicular in-plane toward the face interior.
                    sel_edge = path_edges[i]
                    sa, sb = sel_edge.verts[0].co, sel_edge.verts[1].co
                    seg_len = (sb - sa).length
                    if seg_len < 1e-9:
                        ok = False
                        break
                    sel_dir = (sb - sa) / seg_len
                    perp = prev_face.normal.cross(sel_dir)
                    if perp.length < 1e-9:
                        ok = False
                        break
                    perp.normalize()
                    face_center = prev_face.calc_center_median()
                    edge_mid = (sa + sb) * 0.5
                    into_face = face_center - edge_mid
                    if perp.dot(into_face) < 0:
                        perp = -perp
                    line_point = edge_mid + perp * offset

                    a = shared_edge.verts[0].co
                    b = shared_edge.verts[1].co
                    seg = b - a
                    l2 = seg.length_squared
                    if l2 < 1e-12:
                        ok = False
                        break
                    hit = intersect_line_line(
                        line_point, line_point + sel_dir, a, b
                    )
                    if hit is None:
                        ok = False
                        break
                    p1, p2 = hit
                    if (p1 - p2).length > 1e-3:
                        ok = False
                        break
                    u = (p1 - a).dot(seg) / l2
                    if u < -EPS or u > 1 + EPS:
                        ok = False
                        break
                    u = max(0.0, min(1.0, u))

                    if u < EPS:
                        chain.append(shared_edge.verts[0])
                    elif u > 1 - EPS:
                        chain.append(shared_edge.verts[1])
                    else:
                        _, nv = bmesh.utils.edge_split(
                            shared_edge, shared_edge.verts[0], u
                        )
                        chain.append(nv)
                if not ok:
                    continue
                chain.append(s_end)

                # Connect consecutive verts in the chain.
                for i in range(len(chain) - 1):
                    a, b = chain[i], chain[i + 1]
                    if not (a.is_valid and b.is_valid):
                        continue
                    if a is b or _connected(a, b):
                        continue
                    res = bmesh.ops.connect_vert_pair(bm, verts=[a, b])
                    new_edges.extend(res.get("edges", []))
                handled_faces.update(strip)

        # Continuity pass: weld cut endpoints that landed at (numerically)
        # the same position from independent splits on a shared edge.
        # Threshold is absolute, NOT scaled to the offset — scaling caused
        # legit nearby geometry to be merged at large offsets.
        merge_targets = set()
        for nv in split_cache.values():
            if nv is not None and nv.is_valid:
                merge_targets.add(nv)
        for e in new_edges:
            if e.is_valid:
                merge_targets.update(e.verts)
        merge_list = [v for v in merge_targets if v.is_valid]
        if merge_list:
            bmesh.ops.remove_doubles(
                bm, verts=merge_list, dist=1e-4
            )

        bpy.ops.mesh.select_all(action="DESELECT")
        context.tool_settings.mesh_select_mode = (False, True, False)
        for edge in new_edges:
            if edge.is_valid:
                edge.select = True

        bmesh.update_edit_mesh(me)
        return {"FINISHED"}
