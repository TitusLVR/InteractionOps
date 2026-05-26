import bpy
import bmesh
import math
from mathutils import Vector
from bpy_extras import view3d_utils
from bpy.props import FloatProperty, BoolProperty, IntProperty, EnumProperty
from mathutils.geometry import intersect_line_line

from ..ui.draw import primitives as draw, draw_scope, Role
from ..ui.draw import safe_handler_add, safe_handler_remove
from ..ui.draw.theme import get_theme
from ..ui.hud import (HUDOverlay, HelpOverlay, HUDSection, HUDItem,
                      HUDParam, ItemState,
                      handle_hud_toggle, handle_help_toggle, capture_event)


EPS = 1e-5


_ACTIVE_HANDLES = set()


def _purge_handles():
    """Remove any stale draw handlers left behind by a previous reload."""
    while _ACTIVE_HANDLES:
        h = _ACTIVE_HANDLES.pop()
        try:
            safe_handler_remove(h, bpy.types.SpaceView3D, "WINDOW")
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


def _arc_through_cuts(v_co, cut_a, cut_b, segs):
    """Sample `segs+1` points along the unique circular arc tangent
    to (V → cut_a) at cut_a and tangent to (V → cut_b) at cut_b.

    Approximates the curve produced by `mesh.bevel(profile_type=
    'SUPERELLIPSE', profile=0.5)` — that profile IS a circular arc.
    A naive quadratic Bezier with V as control point sags toward
    the corner for unequal cut distances or non-90° angles, which
    is why the preview used to mismatch the actual bevel.

    Returns a list of world-space Vectors, or None for degenerate
    inputs (zero-length leg, collinear V/cut_a/cut_b)."""
    dir_a = cut_a - v_co
    dir_b = cut_b - v_co
    da = dir_a.length
    db = dir_b.length
    if da < 1e-9 or db < 1e-9:
        return None
    u_axis = dir_a / da
    n = u_axis.cross(dir_b)
    if n.length < 1e-9:
        return None  # collinear corner
    n.normalize()
    w_axis = n.cross(u_axis).normalized()
    cos_th = max(-1.0, min(1.0, dir_a.dot(dir_b) / (da * db)))
    sin_th = math.sqrt(max(0.0, 1.0 - cos_th * cos_th))
    if sin_th < 1e-6:
        return None
    # Circle tangent to (V→cut_a) at cut_a, passing through cut_b.
    # In (u_axis, w_axis) coords with origin at V: cut_a = (da, 0);
    # cut_b = (db cosθ, db sinθ). Tangent-perpendicular at cut_a puts
    # the center on the line u=da, so center = (da, c_w). Requiring
    # the circle to pass through cut_b gives:
    #   c_w = (da² − 2·da·db·cosθ + db²) / (2·db·sinθ)
    # The previous formula (db − da·cosθ)/sinθ was only correct when
    # da == db; on asymmetric corners (different perpendicular offsets
    # or rail angles) the resulting circle missed cut_b — visible as
    # broken arcs whose endpoints didn't meet the cut points.
    c_u = da
    c_w = (da * da - 2.0 * da * db * cos_th + db * db) / (2.0 * db * sin_th)
    center = v_co + u_axis * c_u + w_axis * c_w
    r = math.hypot(c_u - da, c_w - 0.0)  # |cut_a − center|
    if r < 1e-9:
        return None
    # Arc angles relative to center.
    a1 = math.atan2(0.0 - c_w, da - c_u)
    a2 = math.atan2(db * sin_th - c_w, db * cos_th - c_u)
    delta = a2 - a1
    while delta > math.pi:
        delta -= 2.0 * math.pi
    while delta < -math.pi:
        delta += 2.0 * math.pi
    out = []
    for i in range(segs + 1):
        t = i / segs
        a = a1 + t * delta
        local_u = c_u + r * math.cos(a)
        local_w = c_w + r * math.sin(a)
        out.append(v_co + u_axis * local_u + w_axis * local_w)
    return out


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
        description="Perpendicular distance from the ridge to the new cut",
        default=0.05,
        min=0.0,
        soft_max=10.0,
        step=1,
        precision=4,
        subtype="DISTANCE",
    )
    mode: EnumProperty(
        name="Mode",
        description="Which bevel variant to execute",
        items=[
            ("STRAIGHT", "Straight", "Perpendicular cuts across adjacent faces"),
            ("PCT",      "Percent",  "Rounded edge bevel (mesh.bevel SUPERELLIPSE)"),
            ("FAN",      "Flat Fan", "Flat in-face bevel aligned to picked face plane"),
        ],
        default="STRAIGHT",
    )
    pct_segments: IntProperty(
        name="Pct Segments",
        description="Bevel segments for Percent mode",
        default=16, min=1, max=16,
    )
    fan_segments: IntProperty(
        name="Fan Segments",
        description="Bevel segments for Flat Fan mode",
        default=4, min=1, max=16,
    )
    fan_align_mode: EnumProperty(
        name="Fan Align",
        description="How fan boundary verts are placed on the alignment face plane",
        items=[
            ("project",   "Project",   "Project bevel boundary verts onto picked face plane"),
            ("recompute", "Recompute", "Resample arc evenly in picked face plane"),
        ],
        default="project",
    )
    cleanup_mode: BoolProperty(
        name="Cleanup",
        description="Post-bevel limited dissolve on geometry lying on alignment-face planes",
        default=False,
    )
    snap_to_endpoint: BoolProperty(
        name="Snap to Endpoint",
        description=(
            "Topologically join the cut endpoint to the boundary edge: "
            "split the boundary at the projection point and weld the "
            "cut endpoint into the new vert. Off by default — the cut "
            "endpoint just moves geometrically to the boundary position "
            "without subdividing it"
        ),
        default=False,
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
            for v, oe, direction, ridge in pair:
                L = direction.length
                if L < 1e-9 or ridge is None or not ridge.is_valid:
                    continue
                ridge_v = ridge.other_vert(v).co - v.co
                rl = ridge_v.length
                if rl < 1e-9:
                    continue
                sin_th = (direction / L).cross(ridge_v / rl).length
                if sin_th < 1e-4:
                    continue
                # Cap is the max PERPENDICULAR offset that still keeps
                # the along-rail cut within (L - base) — base is the
                # along-rail propagation correction, so subtract before
                # the sin scale.
                allowed = max(0.0, (L * 0.99 - base.get(v, 0.0))) * sin_th
                if allowed < cap:
                    cap = allowed
        self._max_user_offset = cap if cap != float("inf") else None

        self._obj = obj
        self._mouse_start_x = event.mouse_region_x
        self._initial_offset = self.offset
        self._input_str = ""
        # Percent-bevel overlay: B toggles, wheel adjusts segments.
        # The standard preview keeps drawing alongside this overlay.
        # On confirm with _pct_active, mesh.bevel runs at this segment
        # count instead of the straight-bevel cuts. Default 16 gives
        # a nicely rounded preview right after pressing B.
        self._pct_active = False
        self._pct_segments = 16
        # Flat-fan overlay: F toggles, wheel adjusts segments.
        # Mutually exclusive with _pct_active. On confirm replaces the
        # corner ngon with a fan of triangles from the corner vert to
        # `segments+1` arc points lying in the corner-cut plane. Used
        # when the user wants a flat in-face bevel instead of the
        # rounded 3D surface that mesh.bevel produces.
        self._fan_active = False
        self._fan_segments = 4
        # Fan alignment-face mode: 'project' moves boundary verts onto
        # picked face plane (keeps bevel arc samples, may distort
        # spacing); 'recompute' resamples the arc evenly in that plane
        # (uniform spacing, replaces bevel's geometry). Toggled with M.
        self._fan_align_mode = "project"
        # Cleanup toggle: post-bevel limited dissolve on geometry that
        # lies on the alignment-face planes. Single on/off — C toggles.
        self._cleanup_mode = False
        # Optional: after extending the cut endpoint onto a boundary
        # edge, also weld that new vert into v_end (the chain corner),
        # collapsing the offset at that endpoint. S toggles.
        self._snap_to_endpoint = False

        _purge_handles()

        self._hud = HUDOverlay("straight_bevel")
        self._hud.title = "Straight Bevel"
        self._hud.bind_region(context.region)
        # Live toggle params — show current state in dynamic HUD.
        self._hud.add_param(HUDParam(
            "Pct bevel (B)", lambda: self._pct_active, "bool"))
        self._hud.add_param(HUDParam(
            "Flat fan (F)", lambda: self._fan_active, "bool"))
        self._hud.add_param(HUDParam(
            "Pct segs", lambda: self._pct_segments, "int",
            active_getter=lambda: self._pct_active))
        self._hud.add_param(HUDParam(
            "Fan segs", lambda: self._fan_segments, "int",
            active_getter=lambda: self._fan_active))
        self._hud.add_param(HUDParam(
            "Align mode (W)", lambda: self._fan_align_mode, "str",
            active_getter=lambda: self._fan_active))
        self._hud.add_param(HUDParam(
            "Cleanup (C)", lambda: self._cleanup_mode, "bool"))
        self._hud.add_param(HUDParam(
            "Snap to endpoint (S)", lambda: self._snap_to_endpoint, "bool"))
        self._help = HelpOverlay("straight_bevel")
        self._help.add_section(HUDSection("Straight Bevel", [
            HUDItem("Adjust offset", "Mouse / Type", ItemState.ON, default_state=ItemState.OFF, always_show=True),
            HUDItem("Percent bevel", "B",            ItemState.ON, default_state=ItemState.OFF, always_show=True),
            HUDItem("Flat fan",      "F",            ItemState.ON, default_state=ItemState.OFF, always_show=True),
            HUDItem("Cycle align faces", "Q", ItemState.ON, default_state=ItemState.OFF, always_show=True),
            HUDItem("Align mode (proj/recomp)", "W", ItemState.ON, default_state=ItemState.OFF, always_show=True),
            HUDItem("Cleanup (limited dissolve on align faces)", "C", ItemState.ON, default_state=ItemState.OFF, always_show=True),
            HUDItem("Snap cut to chain endpoint vert", "S", ItemState.ON, default_state=ItemState.OFF, always_show=True),
            HUDItem("Segments",      "Wheel",        ItemState.ON, default_state=ItemState.OFF, always_show=True),
            HUDItem("Confirm",       "LMB / Enter",  ItemState.ON, default_state=ItemState.OFF, always_show=True),
            HUDItem("Cancel",        "Esc / RMB",    ItemState.ON, default_state=ItemState.OFF, always_show=True),
            HUDItem("Help / Toggle HUD", "H", ItemState.ON, default_state=ItemState.OFF, always_show=True),
        ]))
        self._help.bind_region(context.region)
        self._last_event = capture_event(event, getattr(self, "_last_event", None))

        self._handle = safe_handler_add(
            bpy.types.SpaceView3D, self._draw_callback, (context,), "WINDOW", "POST_PIXEL", tick=True)
        _ACTIVE_HANDLES.add(self._handle)

        context.workspace.status_text_set(self._status_text())
        context.window_manager.modal_handler_add(self)
        if context.area:
            context.area.tag_redraw()
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        if context.area:
            context.area.tag_redraw()
        self._last_event = capture_event(event, getattr(self, "_last_event", None))
        try:
            theme_prefs = context.preferences.addons["InteractionOps"].preferences.iops_theme
        except (KeyError, AttributeError):
            theme_prefs = None
        if theme_prefs is not None:
            helpo = getattr(self, "_help", None)
            hud = getattr(self, "_hud", None)
            if helpo is not None and helpo.handle_drag_event(context, event, theme_prefs):
                return {'RUNNING_MODAL'}
            if hud is not None and hud.handle_drag_event(context, event, theme_prefs):
                return {'RUNNING_MODAL'}
            if helpo is not None and helpo.handle_toggle_event(event, theme_prefs):
                return {'RUNNING_MODAL'}
            if hud is not None and hud.handle_param_toggle_event(event, theme_prefs):
                return {'RUNNING_MODAL'}

        if event.type in {"WHEELUPMOUSE", "WHEELDOWNMOUSE"} \
                and (self._pct_active or self._fan_active) and event.value == "PRESS":
            # Wheel intercepted while pct or fan overlay is on.
            # Up: more segments; down: fewer (clamped to 1..16).
            attr = "_pct_segments" if self._pct_active else "_fan_segments"
            cur = getattr(self, attr)
            if event.type == "WHEELUPMOUSE":
                setattr(self, attr, min(16, cur + 1))
            else:
                setattr(self, attr, max(1, cur - 1))
            context.workspace.status_text_set(self._status_text())
            return {"RUNNING_MODAL"}

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

            if event.type == "B":
                self._pct_active = not self._pct_active
                if self._pct_active:
                    self._fan_active = False
                context.workspace.status_text_set(self._status_text())
                return {"RUNNING_MODAL"}

            if event.type == "F":
                self._fan_active = not self._fan_active
                if self._fan_active:
                    self._pct_active = False
                context.workspace.status_text_set(self._status_text())
                return {"RUNNING_MODAL"}

            if self._fan_active and event.type == "Q":
                # Raycast under mouse cursor → pick that face as the
                # alignment face for the endpoint nearest the hit. If
                # the face isn't already in that endpoint's candidates,
                # prepend it (so pick_idx=0 selects it).
                self._raycast_pick_face(context, event)
                context.workspace.status_text_set(self._status_text())
                return {"RUNNING_MODAL"}

            if self._fan_active and event.type == "W":
                self._fan_align_mode = (
                    "recompute" if self._fan_align_mode == "project" else "project"
                )
                context.workspace.status_text_set(self._status_text())
                return {"RUNNING_MODAL"}

            if event.type == "C":
                self._cleanup_mode = not self._cleanup_mode
                context.workspace.status_text_set(self._status_text())
                return {"RUNNING_MODAL"}

            if event.type == "S":
                self._snap_to_endpoint = not self._snap_to_endpoint
                context.workspace.status_text_set(self._status_text())
                return {"RUNNING_MODAL"}

            if event.type in {"LEFTMOUSE", "RET", "NUMPAD_ENTER", "SPACE"}:
                # Sync modal-local state to operator properties so the
                # redo panel reflects (and can re-drive) the same params.
                # Manual Q-picked alignment faces are intentionally not
                # persisted — redo falls back to the auto-best candidate.
                if self._fan_active:
                    self.mode = "FAN"
                elif self._pct_active:
                    self.mode = "PCT"
                else:
                    self.mode = "STRAIGHT"
                self.pct_segments = self._pct_segments
                self.fan_segments = self._fan_segments
                self.fan_align_mode = self._fan_align_mode
                self.cleanup_mode = self._cleanup_mode
                self.snap_to_endpoint = self._snap_to_endpoint
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
                safe_handler_remove(h, bpy.types.SpaceView3D, "WINDOW")
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
        if self._pct_active:
            mode = f" | pct preview: segs={self._pct_segments} (wheel)"
        elif self._fan_active:
            n_eps = len(getattr(self, "_fan_endpoints", []))
            mode = (
                f" | fan: segs={self._fan_segments} (wheel) | "
                f"align={self._fan_align_mode} (W) | endpoints={n_eps} (Q cycle)"
            )
        else:
            mode = " | [B] pct preview | [F] flat fan"
        cleanup = f" | cleanup={'on' if self._cleanup_mode else 'off'} (C)"
        return (
            f"Straight Bevel: offset = {self.offset:.4f}{typed} | "
            "[Mouse] drag | [Ctrl] snap 0.1 | [Shift] precise | "
            "[0-9 .] type | [Backspace] del | "
            f"[Enter/LMB] confirm | [Esc/RMB] cancel{mode}{cleanup}"
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
            # Prefer a real endpoint (count=1 within the component) as
            # the BFS root. Picking a random non-shared vert can land
            # on a multi-edge corner, where the very first correction
            # step uses a poorly-defined `oe` and pollutes propagation.
            _ecount = {}
            for e in comp_edges:
                for v in e.verts:
                    _ecount[v] = _ecount.get(v, 0) + 1
            start = next((v for v in comp_verts if _ecount.get(v, 0) == 1), None)
            if start is None:
                start = next((v for v in comp_verts if v not in shared_verts), None)
            if start is None:
                start = next(iter(comp_verts))
            comp_offsets = {start: 0.0}
            visited = set()
            queue = [start]
            while queue:
                current = queue.pop()
                cur = comp_offsets[current]
                # Correction only flows through collinear interior verts
                # (shared_verts). Endpoints and L-corners stop the chain:
                # on a distorted face the projection of the next-ridge
                # direction onto -oe is geometrically meaningless once
                # the rail isn't straight, and used to balloon vert_offset
                # past the neighbour-edge cap.
                for other, ridge in sel_adj.get(current, []):
                    if ridge not in comp_set or ridge in visited:
                        continue
                    visited.add(ridge)
                    correction = 0.0
                    if current in shared_verts:
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

        # Open-chain endpoints for the fan-mode alignment face picker.
        # An endpoint is a comp vert with count==1 (one selected ridge
        # incident). Single-edge selections produce two endpoints.
        # For each endpoint we precompute candidate alignment faces
        # (incident to the vert but NOT on either side of the ridge)
        # and auto-pick the one whose normal is most parallel to the
        # ridge direction — that is the natural "cap" face the bevel
        # tapers into. User cycles with 1/2 keys.
        endpoints = []
        for comp_edges in components.values():
            comp_set = set(comp_edges)
            _ecount = {}
            for e in comp_edges:
                for v in e.verts:
                    _ecount[v] = _ecount.get(v, 0) + 1
            for v, c in _ecount.items():
                if c != 1:
                    continue
                ridge = next((e for e in v.link_edges if e in comp_set), None)
                if ridge is None:
                    continue
                rdir = (ridge.other_vert(v).co - v.co)
                if rdir.length < 1e-9:
                    continue
                rdir_n = rdir.normalized()
                ridge_faces = set(ridge.link_faces)
                cands = [f for f in v.link_faces if f not in ridge_faces and f.is_valid]
                if not cands:
                    continue
                # Find the "tip extension" direction — the longest
                # non-ridge edge from this endpoint. The natural cap
                # plane is perpendicular to it (face whose normal is
                # parallel to it). Falls back to ridge direction if no
                # non-ridge edges exist.
                tip_dir = None
                tip_len = 0.0
                for ee in v.link_edges:
                    if ee is ridge or not ee.is_valid:
                        continue
                    dd = ee.other_vert(v).co - v.co
                    L = dd.length
                    if L > tip_len:
                        tip_len = L
                        tip_dir = dd / L
                score_dir = tip_dir if tip_dir is not None else rdir_n
                cands.sort(key=lambda f: -abs(f.normal.dot(score_dir)))
                endpoints.append({
                    "vert": v,
                    "ridge": ridge,
                    "ridge_dir": rdir_n.copy(),
                    "candidates": cands,
                    "pick_idx": 0,
                })
        # Order endpoints deterministically — by vert index — so "1"
        # always cycles the same endpoint regardless of dict iteration.
        endpoints.sort(key=lambda d: d["vert"].index)
        self._fan_endpoints = endpoints

    @staticmethod
    def _cut_on_rail(v, oe, direction, ridge, offset_perp):
        """Cut point on rail `oe` at perpendicular distance
        `offset_perp` from `ridge`. Matches mesh.bevel(OFFSET,
        loop_slide=False) semantics — bevel's OFFSET parameter is the
        perpendicular distance from the new edge to the original
        ridge, NOT the distance along the rail. For an angled rail the
        cut sits further along the rail: s = offset_perp / sin(angle).
        Returns the cut Vector or None on degenerate input."""
        L = direction.length
        if L < 1e-9 or ridge is None or not ridge.is_valid:
            return None
        rail_n = direction / L
        ridge_v = ridge.other_vert(v).co - v.co
        rl = ridge_v.length
        if rl < 1e-9:
            return None
        ridge_n = ridge_v / rl
        sin_th = rail_n.cross(ridge_n).length
        if sin_th < 1e-4:
            # Rail nearly parallel to ridge — bevel would degenerate;
            # fall back to along-rail to avoid div-by-zero.
            s = offset_perp
        else:
            s = offset_perp / sin_th
        s = min(max(s, 0.0), L * 0.99)
        return v.co + rail_n * s

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
                for v, oe, direction, ridge in ridge_entries:
                    if not (v.is_valid and oe.is_valid):
                        ok = False
                        break
                    s_perp = user_o + base.get(v, 0.0)
                    cut = self._cut_on_rail(v, oe, direction, ridge, s_perp)
                    if cut is None:
                        ok = False
                        break
                    cos.append(cut)
                if not ok or len(cos) != 2:
                    continue
                segments.append((cos[0].copy(), cos[1].copy()))
        return segments

    def _draw_pct_overlay(self, region, rv3d, mw):
        """Percent-bevel preview at each ridge corner. Bridges the
        TWO cut points at each ridge-endpoint vert (the same orange
        endpoints the perpendicular preview already draws) with a
        quadratic Bezier — start = cut on face A's rail, control =
        the ridge corner V, end = cut on face B's rail. Sampled at
        `segments + 1` points. At segments=1 this collapses to a
        single chamfer line between the orange dots; higher segments
        approximate the rounded chamfer."""
        face_pairs = getattr(self, "_face_pairs", {})
        if not face_pairs:
            return
        base = getattr(self, "_vert_offset_base", {})
        user_o = max(self.offset, 0.0)
        # Group cut points per (corner V, selected ridge edge). When
        # multiple ridges meet at the same corner (e.g. consecutive
        # parallel ring selections share endpoints), V has more than
        # two cuts — pairing by V alone would draw arcs between the
        # wrong cuts. Pairing by (V, ridge) gives exactly two cuts
        # per group (one per face sharing the ridge) and one clean
        # arc per (corner, ridge).
        by_pair = {}
        for face, pair in face_pairs.items():
            if not face.is_valid:
                continue
            for v, oe, direction, ridge in pair:
                if not (v.is_valid and oe.is_valid):
                    continue
                if ridge is None or not ridge.is_valid:
                    continue
                s_perp = user_o + base.get(v, 0.0)
                cut = self._cut_on_rail(v, oe, direction, ridge, s_perp)
                if cut is None:
                    continue
                by_pair.setdefault((v, ridge), []).append(cut)

        segs = max(1, self._pct_segments)
        line_pts = []
        point_pts = []
        for (v, _ridge), cuts in by_pair.items():
            if len(cuts) < 2:
                continue
            # Two cuts per (corner, ridge): one on each face sharing
            # the ridge. Boundary edges (ridge with 1 face) only get
            # one cut and are skipped here — bevel can't form an arc.
            arc = _arc_through_cuts(v.co, cuts[0], cuts[1], segs)
            if arc is None:
                continue
            prev_2d = None
            for p_world in arc:
                p_2d = view3d_utils.location_3d_to_region_2d(
                    region, rv3d, mw @ p_world)
                if p_2d is None:
                    prev_2d = None
                    continue
                if prev_2d is not None:
                    line_pts.extend([prev_2d, p_2d])
                point_pts.append(p_2d)
                prev_2d = p_2d

        if not line_pts:
            return
        coords3 = [Vector((p[0], p[1], 0.0)) for p in line_pts]
        with draw_scope(blend="ALPHA"):
            draw.edges_3d(coords3, role=Role.PREVIEW_LINE, context=bpy.context)
            if point_pts:
                pts3 = [Vector((p[0], p[1], 0.0)) for p in point_pts]
                draw.points(pts3, role=Role.PREVIEW_POINT, context=bpy.context)

    def _raycast_pick_face(self, context, event):
        """Q-handler: cast a ray from the mouse cursor into the active
        bmesh, find the hit face, and bind it as the alignment-face
        of the endpoint nearest to the hit point.

        Lazy-builds a BVHTree from self._bm each call (cheap for the
        sizes we typically deal with; rebuild keeps it in sync with any
        mesh edits between presses)."""
        bm = self._bm
        obj = self._obj
        if bm is None or obj is None:
            return
        region = context.region
        rv3d = context.region_data
        if region is None or rv3d is None:
            return
        mx, my = event.mouse_region_x, event.mouse_region_y
        origin_w = view3d_utils.region_2d_to_origin_3d(region, rv3d, (mx, my))
        direction_w = view3d_utils.region_2d_to_vector_3d(region, rv3d, (mx, my))
        mw = obj.matrix_world
        mw_inv = mw.inverted()
        ray_origin = mw_inv @ origin_w
        ray_direction = (mw_inv.to_3x3() @ direction_w).normalized()

        from mathutils.bvhtree import BVHTree
        try:
            bvh = BVHTree.FromBMesh(bm)
        except (ReferenceError, RuntimeError):
            return
        loc, _nrm, face_idx, _dist = bvh.ray_cast(ray_origin, ray_direction)
        if loc is None or face_idx is None:
            return
        bm.faces.ensure_lookup_table()
        if face_idx < 0 or face_idx >= len(bm.faces):
            return
        picked = bm.faces[face_idx]
        if not picked.is_valid:
            return

        eps = getattr(self, "_fan_endpoints", [])
        if not eps:
            return
        # Find endpoint nearest to the hit point (world space).
        hit_w = mw @ loc
        best_ep = None
        best_d = float("inf")
        for ep in eps:
            v = ep["vert"]
            if not v.is_valid:
                continue
            d = ((mw @ v.co) - hit_w).length
            if d < best_d:
                best_d = d
                best_ep = ep
        if best_ep is None:
            return
        # Bind: ensure picked is first in candidates, set pick_idx=0.
        cands = best_ep["candidates"]
        if picked in cands:
            cands.remove(picked)
        cands.insert(0, picked)
        best_ep["pick_idx"] = 0

    def _endpoint_vert_idxs(self):
        """Indices of open-chain endpoint verts (chain count==1).
        Captured pre-finish so we can locate them in the post-bevel
        mesh for cleanup-mode 2 (apex dissolve)."""
        return [ep["vert"].index for ep in getattr(self, "_fan_endpoints", [])
                if ep["vert"].is_valid]

    def _collect_ridge_dirs(self):
        """Snapshot normalized directions of all currently selected
        ridges. Used post-bevel to tell boundary edges (parallel to a
        ridge) from diagonal subdivisions (cross-ridge)."""
        dirs = []
        bm = self._bm
        if bm is None:
            return dirs
        for e in bm.edges:
            if not e.select or not e.is_valid:
                continue
            d = e.verts[1].co - e.verts[0].co
            if d.length < 1e-9:
                continue
            dirs.append(d.normalized().copy())
        return dirs

    def _snap_apex_tips(self, me, endpoint_data, user_offset):
        """Per-endpoint pipeline (spec from user):
          1. Find apex (vert in region with MAX triangle-face count).
          2. Identify arc verts (other-vert of each short edge of apex).
          3. Project arc verts onto picked alignment face plane.
          4. Determine apex action based on its position vs the
             (post-projection) arc:
             - outside arc (r_apex > r_arc * 1.15) → snap apex to the
               original corner endpoint position.
             - on/inside arc → leave apex alone.
          5. Finally: remove_doubles on the whole mesh."""
        if not endpoint_data:
            return
        bm = bmesh.from_edit_mesh(me)
        bm.verts.ensure_lookup_table()
        search_radius = max(user_offset * 2.5, 1e-3)
        for orig, plane in endpoint_data:
            region = [v for v in bm.verts
                      if v.is_valid and (v.co - orig).length <= search_radius]
            if len(region) < 2:
                continue
            # Apex = max triangle-face count, tiebreak by closest.
            def _tri_count(v):
                return sum(1 for f in v.link_faces
                           if f.is_valid and len(f.verts) == 3)
            region.sort(key=lambda v: (-_tri_count(v), (v.co - orig).length))
            apex = region[0]

            # Arc verts = other-vert of every SHORT edge of apex
            # (every incident edge except the dominant long one).
            edges = list(apex.link_edges)
            lens = []
            for e in edges:
                d = e.other_vert(apex).co - apex.co
                if d.length < 1e-9:
                    continue
                lens.append((d.length, e, d))
            if len(lens) < 2:
                continue
            lens.sort(key=lambda x: x[0])
            long_e = lens[-1]
            shorts = lens[:-1]
            has_long = long_e[0] >= shorts[-1][0] * 2.0
            short_edges = shorts if has_long else lens
            arc = [se[1].other_vert(apex) for se in short_edges
                   if se[1].other_vert(apex).is_valid]
            if not arc:
                continue

            # Project arc verts onto picked face plane (plane =
            # (normal, point) snapshotted before bevel — BMFace refs
            # are stale after mesh.bevel rebuild).
            if plane is not None:
                pn, pp = plane
                if pn.length > 1e-9:
                    pn = pn.normalized()
                    for v in arc:
                        d = (v.co - pp).dot(pn)
                        v.co = v.co - pn * d

            # Inside/outside test via arc-centroid: compute centroid
            # of (post-projection) arc, max distance from centroid to
            # any arc vert. If apex's distance to centroid exceeds the
            # arc's max radius from centroid, apex is "outside" the
            # arc curve (sticks past it). For v16 case ratio≈0.88
            # (inside), for v22 ratio≈1.57 (outside).
            from mathutils import Vector
            centroid = Vector((0, 0, 0))
            for v in arc:
                centroid = centroid + v.co
            centroid = centroid / len(arc)
            max_arc_radius = max((v.co - centroid).length for v in arc)
            apex_radius = (apex.co - centroid).length
            if max_arc_radius < 1e-6:
                continue
            if apex_radius > max_arc_radius:
                # Apex outside arc → snap to chain-endpoint orig position
                # (= one of the bevel's source edge endpoint verts).
                apex.co = orig.copy()
            # Else apex on/inside arc → leave alone.

        # Final pass: remove_doubles on everything (apex snap can
        # collide with arc verts, projection can merge nearby verts).
        merge_thresh = max(1e-5, user_offset * 0.1)
        bmesh.ops.remove_doubles(bm, verts=list(bm.verts), dist=merge_thresh)
        bmesh.update_edit_mesh(me)

    def _post_bevel_cleanup(self, me, pre_n, mode, planes=None):
        """Cleanup post-bevel: limited dissolve on geometry lying on
        the alignment-face planes (used to project arc verts).
        Single on/off — removes redundant subdivisions inside the
        aligned cap region without touching unrelated mesh."""
        if not mode or not planes:
            return
        bm = bmesh.from_edit_mesh(me)
        bm.verts.ensure_lookup_table()
        bm.edges.ensure_lookup_table()
        tol = 1e-4
        # Find verts within tol distance of ANY align plane.
        plane_verts = set()
        for plane in planes:
            if plane is None:
                continue
            pn, pp = plane
            if pn.length < 1e-9:
                continue
            pn_n = pn.normalized()
            for v in bm.verts:
                if not v.is_valid:
                    continue
                if abs((v.co - pp).dot(pn_n)) <= tol:
                    plane_verts.add(v)
        if not plane_verts:
            return
        # Edges with BOTH ends on a plane.
        plane_edges = [e for e in bm.edges
                       if e.is_valid and e.verts[0] in plane_verts
                       and e.verts[1] in plane_verts]
        bmesh.ops.dissolve_limit(
            bm,
            angle_limit=0.087,  # ~5°
            use_dissolve_boundaries=False,
            verts=list(plane_verts),
            edges=plane_edges,
            delimit=set(),
        )
        bmesh.update_edit_mesh(me)
        return

    def _post_bevel_cleanup_OLD(self, me, pre_n, mode):
        """Dissolve fan-apex artifacts the bevel produced.

        A fan apex is a new vert (index >= pre_n) that has 3+ triangle
        faces ALL meeting at it (= triangulated bevel cap). Dissolving
        the apex merges those triangles into a single ngon, leaving
        the bevel boundary (parallel-to-ridge quads) intact.

        mode 0: no-op.
        mode 1: dissolve fan apexes only.
        mode 2: mode 1 + dissolve apex stubs that have a degenerate
            (zero-length) edge — fixes the bevel-corner cleanly.
        """
        if mode == 0:
            return
        bm = bmesh.from_edit_mesh(me)
        bm.verts.ensure_lookup_table()
        bm.edges.ensure_lookup_table()
        bm.faces.ensure_lookup_table()

        # Find fan-triangle groups by TOPOLOGY (not by pre/post-bevel
        # index) — 3+ triangle faces that share a common apex vert.
        # Pre-bevel index gating used to miss apexes created by earlier
        # ops; topology-only detection handles both fresh and stale
        # fans the same way.
        from collections import defaultdict
        apex_to_tris = defaultdict(list)
        for f in bm.faces:
            if not f.is_valid or len(f.verts) != 3:
                continue
            for v in f.verts:
                apex_to_tris[v].append(f)

        fan_faces = []
        for apex, tris in apex_to_tris.items():
            if len(tris) < 3:
                continue
            fan_faces.extend(tris)
        # De-dup faces (a tri could feed up to 3 apex buckets).
        fan_faces = list({f for f in fan_faces if f.is_valid})

        if fan_faces:
            # dissolve_faces with use_verts=True merges the triangle
            # cluster into one ngon AND drops the apex vert that becomes
            # interior — leaving the arc boundary intact.
            bmesh.ops.dissolve_faces(bm, faces=fan_faces, use_verts=True)

        if mode == 2:
            # Mode 2 extras:
            # (a) zero-length-edge stragglers (bevel sometimes leaves a
            #     collapsed-apex artifact).
            # (b) "90° corner" verts inside the cleaned ngon — the
            #     original ridge endpoint sometimes survives as a
            #     right-angle corner between two boundary edges of the
            #     merged fan-cap ngon (e.g. v42 between e55 and e50 in
            #     this case). Dissolve it so the boundary becomes a
            #     clean curve.
            bm.verts.ensure_lookup_table()
            extra_verts = []
            for v in bm.verts:
                if not v.is_valid:
                    continue
                # (a) zero-length edge
                if any(e.is_valid and (e.verts[0].co - e.verts[1].co).length < 1e-6
                       for e in v.link_edges):
                    extra_verts.append(v)
                    continue
                # (b) exactly 2 boundary-ish edges at ~90° — a vert with
                # degree 2 where the two outgoing directions are
                # perpendicular. dissolve_faces left such verts as
                # corners of the merged ngon.
                if len(v.link_edges) == 2:
                    a = v.link_edges[0].other_vert(v).co - v.co
                    b = v.link_edges[1].other_vert(v).co - v.co
                    if a.length > 1e-6 and b.length > 1e-6:
                        cos = a.normalized().dot(b.normalized())
                        if abs(cos) < 0.17:
                            extra_verts.append(v)
            if extra_verts:
                bmesh.ops.dissolve_verts(bm, verts=extra_verts)
            # (c) merge doubles near former apexes — v14/v16 case where
            # bevel left two verts at perpendicular offset distance.
            # Run remove_doubles with threshold = small fraction of the
            # user offset.
            try:
                offset = float(self.offset)
            except (AttributeError, TypeError, ValueError):
                offset = 0.0
            merge_thresh = max(1e-5, offset * 0.5)
            bmesh.ops.remove_doubles(bm, verts=list(bm.verts), dist=merge_thresh)
        bmesh.update_edit_mesh(me)

    def _pre_bevel_cleanup(self, mode, ridge_dirs):
        """Dissolve triangle-fan structures in the SOURCE mesh near the
        chain — apex vertices surrounded entirely by triangles (typical
        leftover of an earlier vertex/edge bevel). Runs BEFORE
        mesh.bevel so the bevel works on a clean quad-dominant area.
        Operates on self._bm directly.

        mode 0: no-op.
        mode 1: dissolve fan apex verts (degree>=3, all-triangle
            faces) found in 1-ring around chain verts.
        mode 2: mode 1 + dissolve "diagonal" edges adjacent to former
            fans — edges between two former-fan-boundary verts whose
            two link_faces could merge into a planar quad.
        """
        if mode == 0:
            return
        bm = self._bm
        if bm is None:
            return
        sel_set = set(e for e in bm.edges if e.select and e.is_valid)
        chain_verts = set()
        for e in sel_set:
            for v in e.verts:
                if v.is_valid:
                    chain_verts.add(v)
        # Expand to 1-ring — fan apex verts usually sit one hop off
        # the chain (the corner the previous bevel rounded into).
        ring = set(chain_verts)
        for v in chain_verts:
            for e in v.link_edges:
                ov = e.other_vert(v)
                if ov.is_valid:
                    ring.add(ov)

        # Fan apex = vert whose ALL incident faces are triangles and
        # has degree >= 3. Skip verts that are themselves selected
        # ridge endpoints — those are our bevel target.
        sel_verts = set()
        for e in sel_set:
            for v in e.verts:
                sel_verts.add(v)
        fan_apexes = []
        for v in ring:
            if v in sel_verts:
                continue
            if not v.is_valid:
                continue
            faces = list(v.link_faces)
            if len(faces) < 3:
                continue
            if all(len(f.verts) == 3 for f in faces if f.is_valid):
                fan_apexes.append(v)

        # Record boundary verts of each fan (the ring verts around an
        # apex) — used in mode 2 to find adjacent diagonals.
        fan_boundary = set()
        for apex in fan_apexes:
            for e in apex.link_edges:
                ov = e.other_vert(apex)
                if ov.is_valid:
                    fan_boundary.add(ov)

        if fan_apexes:
            bmesh.ops.dissolve_verts(bm, verts=fan_apexes)

        if mode == 2 and fan_boundary:
            # After fan dissolve, edges between former-fan-boundary
            # verts whose two faces are coplanar can be dissolved.
            bm.edges.ensure_lookup_table()
            # Refresh references — fan_boundary verts may have moved
            # indices but BMVert refs survive dissolve_verts.
            diag = []
            seen = set()
            for v in fan_boundary:
                if not v.is_valid:
                    continue
                for e in v.link_edges:
                    if e in seen or e in sel_set or not e.is_valid:
                        continue
                    seen.add(e)
                    ov = e.other_vert(v)
                    if ov not in fan_boundary or not ov.is_valid:
                        continue
                    if len(e.link_faces) != 2:
                        continue
                    fa, fb = e.link_faces
                    if not (fa.is_valid and fb.is_valid):
                        continue
                    if abs(fa.normal.dot(fb.normal)) < 0.985:
                        continue
                    diag.append(e)
            if diag:
                bmesh.ops.dissolve_edges(
                    bm, edges=diag, use_verts=False, use_face_split=False
                )
        bmesh.update_edit_mesh(self._obj.data)

    def _draw_fan_overlay(self, region, rv3d, mw):
        """Flat-fan preview: arc between the two cut points (same as
        pct overlay) plus radial spokes from the corner V to every arc
        sample. Confirming in this mode replaces the corner ngon with
        a fan of triangles using these same sample points — so the
        preview shows the exact final topology."""
        face_pairs = getattr(self, "_face_pairs", {})
        if not face_pairs:
            return
        base = getattr(self, "_vert_offset_base", {})
        user_o = max(self.offset, 0.0)
        by_pair = {}
        for face, pair in face_pairs.items():
            if not face.is_valid:
                continue
            for v, oe, direction, ridge in pair:
                if not (v.is_valid and oe.is_valid):
                    continue
                if ridge is None or not ridge.is_valid:
                    continue
                s_perp = user_o + base.get(v, 0.0)
                cut = self._cut_on_rail(v, oe, direction, ridge, s_perp)
                if cut is None:
                    continue
                # Same per-corner grouping as in _draw_pct_overlay —
                # L-corners merge cuts from multiple ridges into one arc.
                by_pair.setdefault(v, []).append(cut)

        # Index endpoints by vert for quick lookup of picked alignment
        # face. When an endpoint vert has a picked face, project the
        # arc into that face's plane so the preview matches the final
        # geometry (projection or recompute mode).
        ep_by_vert = {}
        for ep in getattr(self, "_fan_endpoints", []):
            cands = ep["candidates"]
            if not cands:
                continue
            f = cands[ep["pick_idx"] % len(cands)]
            if not f.is_valid:
                continue
            ep_by_vert[ep["vert"]] = f

        segs = max(1, self._fan_segments)
        align_mode = self._fan_align_mode
        line_pts = []
        spoke_pts = []
        point_pts = []
        for v, cuts in by_pair.items():
            if len(cuts) < 2:
                continue
            face = ep_by_vert.get(v)
            if face is not None:
                # Project cuts and corner onto face plane → final geom.
                pn = face.normal
                if pn.length < 1e-9:
                    arc = _arc_through_cuts(v.co, cuts[0], cuts[1], segs)
                else:
                    pn = pn.normalized()
                    pp = face.calc_center_median()
                    def _proj(p):
                        return p - pn * (p - pp).dot(pn)
                    c0p = _proj(cuts[0])
                    c1p = _proj(cuts[1])
                    vp = _proj(v.co)
                    if align_mode == "recompute":
                        arc = _arc_through_cuts(vp, c0p, c1p, segs)
                    else:
                        # Project the 3D arc samples onto plane — same
                        # transform as confirm's project mode.
                        arc3 = _arc_through_cuts(v.co, cuts[0], cuts[1], segs)
                        arc = [_proj(p) for p in arc3] if arc3 else None
            else:
                arc = _arc_through_cuts(v.co, cuts[0], cuts[1], segs)
            if arc is None:
                continue
            corner_2d = view3d_utils.location_3d_to_region_2d(
                region, rv3d, mw @ v.co)
            prev_2d = None
            for p_world in arc:
                p_2d = view3d_utils.location_3d_to_region_2d(
                    region, rv3d, mw @ p_world)
                if p_2d is None:
                    prev_2d = None
                    continue
                if prev_2d is not None:
                    line_pts.extend([prev_2d, p_2d])
                if corner_2d is not None:
                    spoke_pts.extend([corner_2d, p_2d])
                point_pts.append(p_2d)
                prev_2d = p_2d

        # Outline currently picked alignment faces.
        face_outline = []
        for ep in getattr(self, "_fan_endpoints", []):
            cands = ep["candidates"]
            if not cands:
                continue
            f = cands[ep["pick_idx"] % len(cands)]
            if not f.is_valid:
                continue
            fv = list(f.verts)
            for i, vrt in enumerate(fv):
                a = view3d_utils.location_3d_to_region_2d(region, rv3d, mw @ vrt.co)
                b = view3d_utils.location_3d_to_region_2d(
                    region, rv3d, mw @ fv[(i + 1) % len(fv)].co)
                if a is not None and b is not None:
                    face_outline.extend([a, b])

        if not line_pts and not spoke_pts and not face_outline:
            return
        with draw_scope(blend="ALPHA"):
            if line_pts:
                coords = [Vector((p[0], p[1], 0.0)) for p in line_pts]
                draw.edges_3d(coords, role=Role.PREVIEW_LINE, context=bpy.context)
            if spoke_pts:
                coords = [Vector((p[0], p[1], 0.0)) for p in spoke_pts]
                draw.edges_3d(coords, role=Role.PREVIEW_LINE, context=bpy.context)
            if face_outline:
                coords = [Vector((p[0], p[1], 0.0)) for p in face_outline]
                draw.edges_3d(coords, role=Role.ACTIVE_LINE, context=bpy.context)
            if point_pts:
                pts = [Vector((p[0], p[1], 0.0)) for p in point_pts]
                draw.points(pts, role=Role.PREVIEW_POINT, context=bpy.context)

    def _preview_snap_extensions(self):
        """Returns list of (sv_co, target_co) pairs showing where each
        chain-endpoint cut would be snapped if confirm with snap mode.
        Mirrors the snap pass in `_exec_straight` geometrically (without
        modifying mesh). Used by `_draw_callback` to draw extension
        lines from the hanging cut endpoint to the boundary edge it
        would land on."""
        # Extension line is always computed/drawn so the user sees
        # WHERE each endpoint would snap to. The actual weld only fires
        # on confirm when `snap_endpoints` is on; the preview line just
        # signals "if you toggle S, this is where the cut will land".
        out = []
        eps = getattr(self, "_fan_endpoints", [])
        if not eps:
            return out
        base = getattr(self, "_vert_offset_base", {})
        face_pairs = getattr(self, "_face_pairs", {})
        user_o = max(self.offset, 0.0)
        for ep in eps:
            v_end = ep["vert"]
            ridge = ep["ridge"]
            if not (v_end.is_valid and ridge.is_valid):
                continue
            other = ridge.other_vert(v_end)
            cast_dir = v_end.co - other.co
            if cast_dir.length < 1e-9:
                continue
            cast_dir = cast_dir.normalized()
            candidates = set()
            for f in v_end.link_faces:
                for ee in f.edges:
                    if not ee.is_valid:
                        continue
                    if ee.select:
                        continue
                    candidates.add(ee)
            # Collect svs at this endpoint from face_pairs entries.
            for face, pair in face_pairs.items():
                if not face.is_valid:
                    continue
                for v, oe, direction, sel_ridge in pair:
                    if v is not v_end:
                        continue
                    if sel_ridge is not ridge:
                        continue
                    s_perp = user_o + base.get(v, 0.0)
                    sv_co = self._cut_on_rail(v, oe, direction, sel_ridge, s_perp)
                    if sv_co is None:
                        continue
                    best = None
                    for ee in candidates:
                        if oe is ee:
                            continue
                        a, b = ee.verts[0].co, ee.verts[1].co
                        res = intersect_line_line(sv_co, sv_co + cast_dir, a, b)
                        if res is None:
                            continue
                        p1, p2 = res
                        if (p1 - p2).length > 1e-4:
                            continue
                        t = (p1 - sv_co).dot(cast_dir)
                        if t <= EPS:
                            continue
                        seg = b - a
                        l2 = seg.length_squared
                        if l2 < 1e-12:
                            continue
                        u = (p1 - a).dot(seg) / l2
                        if u < -EPS or u > 1 + EPS:
                            continue
                        if best is None or t < best[0]:
                            best = (t, p1.copy())
                    if best is not None:
                        out.append((sv_co.copy(), best[1]))
        return out

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
                    safe_handler_remove(h, bpy.types.SpaceView3D, "WINDOW")
                except (ValueError, RuntimeError, ReferenceError):
                    pass
            return
        # Boundary preview lines parallel to each ridge in each face —
        # always drawn (in B/F mode they ARE the bevel boundary; in
        # straight mode they're the perpendicular cut lines).
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
            coords3 = [Vector((p[0], p[1], 0.0)) for p in segs_2d]
            with draw_scope(blend="ALPHA"):
                draw.edges_3d(coords3, role=Role.PREVIEW_LINE, context=context)
                if endpoints_2d:
                    pts3 = [Vector((p[0], p[1], 0.0)) for p in endpoints_2d]
                    draw.points(pts3, role=Role.PREVIEW_POINT, context=context)

        # Snap-endpoint extension preview: dashed-ish line from the
        # hanging cut endpoint to the boundary edge it'll snap to.
        snap_ext = self._preview_snap_extensions()
        if snap_ext:
            ext_segs = []
            ext_pts = []
            for a, b in snap_ext:
                pa = view3d_utils.location_3d_to_region_2d(region, rv3d, mw @ a)
                pb = view3d_utils.location_3d_to_region_2d(region, rv3d, mw @ b)
                if pa is None or pb is None:
                    continue
                ext_segs.extend([pa, pb])
                ext_pts.append(pb)
            if ext_segs:
                coords3 = [Vector((p[0], p[1], 0.0)) for p in ext_segs]
                with draw_scope(blend="ALPHA"):
                    draw.edges_3d(coords3, role=Role.ACTIVE_LINE, context=context)
                    if ext_pts:
                        pts3 = [Vector((p[0], p[1], 0.0)) for p in ext_pts]
                        draw.points(pts3, role=Role.PREVIEW_POINT, context=context)

        if self._pct_active:
            self._draw_pct_overlay(region, rv3d, mw)
        elif self._fan_active:
            self._draw_fan_overlay(region, rv3d, mw)

        hud = getattr(self, "_hud", None)
        helpo = getattr(self, "_help", None)
        last_event = getattr(self, "_last_event", None)
        if helpo is not None:
            helpo.draw(context, last_event)
        if hud is not None:
            lines = [f"Offset: {self.offset:.4f}"]
            if self._input_str:
                lines.append(f"Typing: {self._input_str}")
            hud.set_header(*lines)
            hud.draw(context, last_event)

    # ------------------------------------------------------------------
    # Execute (topology change)
    # ------------------------------------------------------------------

    def execute(self, context):
        """Dispatcher. Called both from modal confirm (with HUD/draw
        handlers already torn down) and from the redo panel (no modal
        state at all). PCT and FAN paths rebuild their endpoint data
        from the current selection so they're safe to re-run."""
        if self.mode == "PCT":
            return self._exec_pct(context)
        if self.mode == "FAN":
            return self._exec_fan(context)
        return self._exec_straight(context)

    def _gather_endpoint_data(self, bm, selected):
        """Re-collect _fan_endpoints from the current selection and
        snapshot (orig_vert_pos, face_plane) per endpoint. Used by both
        modal confirm and redo-panel re-execution of PCT/FAN modes.
        Plane is captured as (normal, point) because BMFace refs don't
        survive the mesh.bevel topology rebuild that follows."""
        self._bm = bm
        self._collect_jobs(bm, selected)
        endpoint_data = []
        for ep in getattr(self, "_fan_endpoints", []):
            v = ep["vert"]
            if not v.is_valid:
                continue
            cands = ep["candidates"]
            face = cands[ep["pick_idx"] % len(cands)] if cands else None
            if face is not None and face.is_valid:
                plane = (face.normal.copy(), face.calc_center_median().copy())
            else:
                plane = None
            endpoint_data.append((v.co.copy(), plane))
        return endpoint_data

    def _exec_pct(self, context):
        obj = context.active_object
        if obj is None or obj.type != "MESH":
            return {"CANCELLED"}
        me = obj.data
        bm = bmesh.from_edit_mesh(me)
        bm.edges.ensure_lookup_table()
        bm.faces.ensure_lookup_table()
        bm.normal_update()
        selected = [e for e in bm.edges if e.select and len(e.link_faces) > 0]
        if not selected:
            self.report({"WARNING"}, "No edges selected")
            return {"CANCELLED"}
        endpoint_data = self._gather_endpoint_data(bm, selected)
        user_offset = self.offset
        segments = self.pct_segments
        pre_n = len(bm.verts)
        bpy.ops.mesh.bevel(
            offset_type="OFFSET",
            offset=user_offset,
            profile_type="SUPERELLIPSE",
            segments=segments,
            profile=0.5,
            affect="EDGES",
            clamp_overlap=False,
            loop_slide=False,
            release_confirm=False,
        )
        self._snap_apex_tips(me, endpoint_data, user_offset)
        planes = [p for _, p in endpoint_data]
        self._post_bevel_cleanup(me, pre_n, self.cleanup_mode, planes)
        return {"FINISHED"}

    def _exec_fan(self, context):
        obj = context.active_object
        if obj is None or obj.type != "MESH":
            return {"CANCELLED"}
        me = obj.data
        bm = bmesh.from_edit_mesh(me)
        bm.edges.ensure_lookup_table()
        bm.faces.ensure_lookup_table()
        bm.normal_update()
        selected = [e for e in bm.edges if e.select and len(e.link_faces) > 0]
        if not selected:
            self.report({"WARNING"}, "No edges selected")
            return {"CANCELLED"}
        endpoint_data = self._gather_endpoint_data(bm, selected)
        # Build ep_specs for boundary alignment (vert pos + plane + ridge dir).
        ep_specs = []
        for ep in getattr(self, "_fan_endpoints", []):
            cands = ep["candidates"]
            if not cands:
                continue
            face = cands[ep["pick_idx"] % len(cands)]
            if not face.is_valid:
                continue
            vert = ep["vert"]
            ridge = ep["ridge"]
            if not (vert.is_valid and ridge.is_valid):
                continue
            ep_specs.append({
                "v_co": vert.co.copy(),
                "plane_point": face.calc_center_median().copy(),
                "plane_normal": face.normal.copy(),
                "ridge_dir": ep["ridge_dir"].copy(),
            })
        user_offset = self.offset
        segments = self.fan_segments
        align_mode = self.fan_align_mode
        pre_n = len(bm.verts)
        bpy.ops.mesh.bevel(
            offset_type="OFFSET",
            offset=user_offset,
            profile_type="SUPERELLIPSE",
            segments=segments,
            profile=0.5,
            affect="EDGES",
            clamp_overlap=False,
            loop_slide=False,
            release_confirm=False,
        )
        bm = bmesh.from_edit_mesh(me)
        bm.verts.ensure_lookup_table()
        new_verts = [v for v in bm.verts if v.index >= pre_n and v.is_valid]
        for spec in ep_specs:
            pn = spec["plane_normal"]
            if pn.length < 1e-9:
                continue
            pn = pn.normalized()
            pp = spec["plane_point"]
            v_co = spec["v_co"]
            radius = user_offset * 1.6
            boundary = [v for v in new_verts if (v.co - v_co).length <= radius]
            if not boundary:
                continue
            if align_mode == "project":
                for v in boundary:
                    d = (v.co - pp).dot(pn)
                    v.co = v.co - pn * d
            else:  # recompute
                if len(boundary) < 2:
                    continue
                proj = []
                for v in boundary:
                    d = (v.co - pp).dot(pn)
                    proj.append(v.co - pn * d)
                far_i, far_j, far_d = 0, 1, -1.0
                for i in range(len(proj)):
                    for j in range(i + 1, len(proj)):
                        d = (proj[i] - proj[j]).length
                        if d > far_d:
                            far_d = d
                            far_i = i
                            far_j = j
                p_a = proj[far_i]
                p_b = proj[far_j]
                d_c = (v_co - pp).dot(pn)
                center_ref = v_co - pn * d_c
                arc = _arc_through_cuts(center_ref, p_a, p_b, len(boundary) - 1)
                if arc is None:
                    for v, p in zip(boundary, proj):
                        v.co = p
                    continue
                u = (p_a - center_ref)
                if u.length < 1e-9:
                    for v, p in zip(boundary, proj):
                        v.co = p
                    continue
                u.normalize()
                w = pn.cross(u).normalized()
                def _angle(p, _cr=center_ref, _u=u, _w=w):
                    d = p - _cr
                    return math.atan2(d.dot(_w), d.dot(_u))
                order = sorted(range(len(boundary)), key=lambda i: _angle(proj[i]))
                for k, idx in enumerate(order):
                    if k < len(arc):
                        boundary[idx].co = arc[k]
        bmesh.update_edit_mesh(me)
        self._snap_apex_tips(me, endpoint_data, user_offset)
        planes = [p for _, p in endpoint_data]
        self._post_bevel_cleanup(me, pre_n, self.cleanup_mode, planes)
        return {"FINISHED"}

    def _exec_straight(self, context):
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
        # Don't exclude shared_verts here. A shared (collinear interior)
        # vert sits between two ridges that live in DIFFERENT face sets;
        # without a job entry on the shared side, Pass 1's by_ridge
        # grouping never gets two jobs for those faces, so no cut is
        # produced (cuts "vanish" past the shared corner). The collinear
        # geometry guarantees the split point on the shared rail aligns
        # naturally between the two adjacent ridge cuts.
        face_pairs = {}  # face -> [(v, oe), (v, oe)]
        for e in selected:
            for v in e.verts:
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
            # Prefer count=1 in the component so BFS roots at a real
            # endpoint rather than an L-corner — see _collect_jobs for
            # the full rationale on why corner-rooted propagation
            # produces garbage corrections on deformed quads.
            _ecount = {}
            for e in comp_edges:
                for v in e.verts:
                    _ecount[v] = _ecount.get(v, 0) + 1
            start = next((v for v in comp_verts if _ecount.get(v, 0) == 1), None)
            if start is None:
                start = next((v for v in comp_verts if v not in shared_verts), None)
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
                    if current in shared_verts:
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

        # Build offsets_at per (v, oe). `s` from vert_offset is the
        # PERPENDICULAR distance from the ridge (preview semantics).
        # Convert to along-rail by /sin(θ) where θ is the angle between
        # the rail and THIS face's ridge. Without this the cut at a
        # non-90° rail lands closer to the corner than the preview, so
        # the resulting connect_vert_pair line isn't parallel to the
        # ridge — "straight bevel not straight" on trapezoidal faces.
        offsets_at = {}
        for v, s in vert_offset.items():
            if s <= EPS:
                continue
            for face in v.link_faces:
                ridge_in_face = [e for e in v.link_edges
                                 if e in selected_set and face in e.link_faces]
                if not ridge_in_face:
                    continue
                ridge = ridge_in_face[0]
                ridge_v = ridge.other_vert(v).co - v.co
                rl = ridge_v.length
                if rl < 1e-9:
                    continue
                ridge_n = ridge_v / rl
                fe_at_v = [
                    oe for oe in v.link_edges
                    if face in oe.link_faces and oe not in selected_set
                ]
                if not fe_at_v:
                    continue
                oe = fe_at_v[0]
                rail = oe.other_vert(v).co - v.co
                L = rail.length
                if L < 1e-9:
                    continue
                rail_n = rail / L
                sin_th = rail_n.cross(ridge_n).length
                s_along = s if sin_th < 1e-4 else s / sin_th
                # Stop at the neighbour vertex if the offset would
                # reach or exceed it: snap to L exactly so _get_start
                # returns the existing vert instead of producing a
                # near-zero-length split. This prevents the cut from
                # crossing past an existing vertex.
                clamped = min(max(s_along, 0.0), L)
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

        # Endpoint extension pass. ALWAYS: cast the rail-split vert
        # along -ridge_dir to the nearest face boundary edge and move
        # its coordinates there (geometric extension — cut visually
        # lands on the boundary).
        # OPTIONAL (snap_endpoints=True): also split that boundary edge
        # at the hit point and weld the cut endpoint into the new
        # boundary vert (topological join — boundary becomes subdivided
        # and shares the cut endpoint).
        for comp_edges in _components_pre.values():
            _ec = {}
            for e in comp_edges:
                for v in e.verts:
                    _ec[v] = _ec.get(v, 0) + 1
            endpoints_local = [v for v, c in _ec.items() if c == 1]
            for v_end in endpoints_local:
                if not v_end.is_valid:
                    continue
                ridge_e = next(
                    (e for e in v_end.link_edges if e in selected_set),
                    None,
                )
                if ridge_e is None or not ridge_e.is_valid:
                    continue
                other_end = ridge_e.other_vert(v_end)
                cast_dir = v_end.co - other_end.co
                if cast_dir.length < 1e-9:
                    continue
                cast_dir = cast_dir.normalized()
                candidates = set()
                for f in v_end.link_faces:
                    for ee in f.edges:
                        if ee in selected_set:
                            continue
                        candidates.add(ee)
                for (vv, oe), sv in list(split_cache.items()):
                    if vv is not v_end:
                        continue
                    if sv is None or not sv.is_valid or sv is v_end:
                        continue
                    best = None
                    for ee in candidates:
                        if not ee.is_valid or sv in ee.verts:
                            continue
                        a, b = ee.verts[0].co, ee.verts[1].co
                        res = intersect_line_line(
                            sv.co, sv.co + cast_dir, a, b
                        )
                        if res is None:
                            continue
                        p1, p2 = res
                        if (p1 - p2).length > 1e-4:
                            continue
                        t = (p1 - sv.co).dot(cast_dir)
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
                        if best is None or t < best[0]:
                            best = (t, ee, p1.copy(), u)
                    if best is None:
                        continue
                    _t, hit_edge, hit_pt, u = best
                    # Always: geometric extension. Move sv onto the
                    # boundary projection point — visually the cut now
                    # lands on the boundary edge. No topology change.
                    sv.co = hit_pt.copy()
                    if self.snap_to_endpoint:
                        # Optional: topological join. Split the boundary
                        # edge at the projection (or reuse an existing
                        # endpoint vert if u is ~0/1) and weld sv into
                        # the resulting vert so the boundary becomes
                        # subdivided and shares sv's identity.
                        if u < EPS:
                            target_v = hit_edge.verts[0]
                        elif u > 1 - EPS:
                            target_v = hit_edge.verts[1]
                        else:
                            _, target_v = bmesh.utils.edge_split(
                                hit_edge, hit_edge.verts[0], u
                            )
                        if target_v is not sv and target_v.is_valid:
                            bmesh.ops.weld_verts(
                                bm, targetmap={sv: target_v}
                            )

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
