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
        bm = bmesh.from_edit_mesh(me)
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
            new_offset = self._initial_offset + delta * self._pixel_to_offset
            self.offset = max(0.0, new_offset)
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

    def _status_text(self):
        typed = f" | typing: {self._input_str}" if self._input_str else ""
        return (
            f"Straight Bevel: offset = {self.offset:.4f}{typed} | "
            "[Mouse] drag | [0-9 .] type | [Backspace] del | "
            "[Enter/LMB] confirm | [Esc/RMB] cancel"
        )

    # ------------------------------------------------------------------
    # Preview
    # ------------------------------------------------------------------

    def _collect_jobs(self, bm, selected):
        selected_set = set(selected)
        # Verts shared between two or more selected edges → no cut at those corners.
        shared_verts = set()
        seen = {}
        for e in selected:
            for v in e.verts:
                if v in seen and seen[v] is not e:
                    shared_verts.add(v)
                else:
                    seen[v] = e

        self._preview_jobs = []
        per_edge_cap = {}
        for e in selected:
            for v in e.verts:
                if v in shared_verts:
                    continue
                for face in e.link_faces:
                    face_edges_at_v = [oe for oe in v.link_edges
                                       if face in oe.link_faces and oe is not e
                                       and oe not in selected_set]
                    if not face_edges_at_v:
                        continue
                    oe = face_edges_at_v[0]
                    direction = oe.other_vert(v).co - v.co
                    L = direction.length
                    if L < 1e-9:
                        continue
                    self._preview_jobs.append({
                        "corner": v,
                        "face": face,
                        "neighbour": oe,
                        "direction": direction.copy(),
                        "selected": e,
                    })
                    prev = per_edge_cap.get(e)
                    per_edge_cap[e] = L if prev is None else min(prev, L)
        self._per_edge_cap = per_edge_cap

    def _preview_segments(self):
        segments = []
        for job in self._preview_jobs:
            v = job["corner"]
            face = job["face"]
            oe = job["neighbour"]
            direction = job["direction"]
            if not (v.is_valid and face.is_valid and oe.is_valid):
                continue
            L = direction.length
            cap = self._per_edge_cap.get(job["selected"], L) * 0.99
            o = min(max(self.offset, 0.0), cap)
            dir_n = direction / L
            start_co = v.co + dir_n * o
            cut_dir = face.normal.cross(dir_n)
            if cut_dir.length < 1e-9:
                continue
            cut_dir.normalize()

            hit = _find_hit_point(face, start_co, oe, v, cut_dir)
            if hit is None:
                hit = _find_hit_point(face, start_co, oe, v, -cut_dir)
            if hit is None:
                continue

            segments.append((start_co.copy(), hit[2]))
        return segments

    def _draw_callback(self, context):
        region = context.region
        rv3d = context.region_data
        if rv3d is None:
            return

        mw = self._obj.matrix_world
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
        # Verts shared between 2+ selected edges → no cut at those corners.
        shared_verts = set()
        seen = {}
        for e in selected:
            for v in e.verts:
                if v in seen and seen[v] is not e:
                    shared_verts.add(v)
                else:
                    seen[v] = e

        corner_jobs = []
        per_edge_cap = {}
        for e in selected:
            for v in e.verts:
                if v in shared_verts:
                    continue
                for face in e.link_faces:
                    face_edges_at_v = [oe for oe in v.link_edges
                                       if face in oe.link_faces and oe is not e
                                       and oe not in selected_set]
                    if not face_edges_at_v:
                        continue
                    oe = face_edges_at_v[0]
                    direction = oe.other_vert(v).co - v.co
                    L = direction.length
                    if L < 1e-9:
                        continue
                    corner_jobs.append((v, face, oe, direction.copy(), e))
                    prev = per_edge_cap.get(e)
                    per_edge_cap[e] = L if prev is None else min(prev, L)

        start_map = {}
        for v, face, oe, direction, sel_edge in corner_jobs:
            key = (v, oe)
            if key in start_map:
                continue
            if offset <= EPS:
                start_map[key] = v
                continue
            L = direction.length
            cap = per_edge_cap.get(sel_edge, L) * 0.99
            o = min(offset, cap)
            if oe.verts[0] is v or oe.verts[1] is v:
                _, nv = bmesh.utils.edge_split(oe, v, o / L)
                start_map[key] = nv
            else:
                start_map[key] = v

        new_edges = []
        for corner, face, oe, direction, sel_edge in corner_jobs:
            if not face.is_valid:
                continue
            start = start_map.get((corner, oe), corner)
            if start is None or not start.is_valid:
                continue

            cut_dir = face.normal.cross(direction)
            if cut_dir.length < 1e-9:
                continue
            cut_dir.normalize()

            hit = _find_hit_vert(face, start, cut_dir)
            if hit is None:
                hit = _find_hit_vert(face, start, -cut_dir)
            if hit is None:
                continue

            hit_edge, u = hit
            if u < EPS:
                target = hit_edge.verts[0]
            elif u > 1 - EPS:
                target = hit_edge.verts[1]
            else:
                _, target = bmesh.utils.edge_split(
                    hit_edge, hit_edge.verts[0], u)

            if target is start or _connected(start, target):
                continue
            res = bmesh.ops.connect_vert_pair(bm, verts=[start, target])
            new_edges.extend(res.get("edges", []))

        bpy.ops.mesh.select_all(action="DESELECT")
        context.tool_settings.mesh_select_mode = (False, True, False)
        for edge in new_edges:
            if edge.is_valid:
                edge.select = True

        bmesh.update_edit_mesh(me)
        return {"FINISHED"}
