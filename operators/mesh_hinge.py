"""Hinge: rotate the selection around one of its own edges, baking the
sweep as real segment geometry (bmesh.ops.spin).

Selection
- faces: the selected faces rotate; the axis is one of their edges.
- edges (no faces): the selected edges rotate — open boundary loops,
  wire profiles — and the spin walls become the new faces. The axis is
  one of the selected edges (it stays put).

The axis edge is whichever candidate edge is nearest to the mouse in
screen space (same pick as cursor_bisect) and it is re-picked live on
mouse move, so aiming is the whole interaction. Typed digits, Alt+Wheel
(±5°) and A (flush to the face under the cursor) set the angle;
Ctrl+Wheel sets the segment count; D flips the sign. The preview is a
draw-only ghost — the mesh does not move until confirm (LMB / Enter /
Space). Angle and segments persist in Scene.IOPS.

Bounding-box axis: the selection's min-OBB (in its plane) offers four
sides as alternative hinge lines — click a side's dot, or press F to
cycle them. Tab returns to edge-under-mouse picking.
"""
import bpy
import bmesh
import math
import gpu

from bpy_extras import view3d_utils
from mathutils import Matrix, Vector
from mathutils.bvhtree import BVHTree
from mathutils.geometry import normal as poly_normal

from ..ui.draw import primitives as draw_prim, Role
from ..ui.draw import safe_handler_add, safe_handler_remove
from ..ui.draw.theme import get_theme
from ..ui.hud import (HUDOverlay, HelpOverlay, HUDSection, HUDItem,
                      ItemState, capture_event)
from ..utils.hinge_core import flush_angle
from ..utils.picking import closest_edge_screen
from .mesh_shear import (DIGIT_TYPES, _face_normal_safe, _gather_double_verts,
                         profile_principal_axes)


def _selection_normal(faces, edges, cos):
    """Reference normal of the hinged selection (flush target + sign
    convention). Faces: their mean normal. Edges: mean of the linked
    faces' normals, else the best-fit plane of the verts, else None."""
    n = Vector((0.0, 0.0, 0.0))
    for f in faces:
        n += _face_normal_safe(f)
    if n.length > 1e-9:
        return n.normalized()
    seen = set()
    for e in edges:
        for f in e.link_faces:
            if f not in seen:
                seen.add(f)
                n += _face_normal_safe(f)
    if n.length > 1e-9:
        return n.normalized()
    if len(cos) >= 3:
        try:
            n = poly_normal(cos)
        except (ValueError, TypeError):
            n = Vector((0.0, 0.0, 0.0))
        if n.length > 1e-9:
            return n.normalized()
    return None


class IOPS_OT_mesh_hinge(bpy.types.Operator):
    """Rotate the selected faces (or edges) around the edge under the
mouse, baking the sweep as segments"""

    bl_idname = "iops.mesh_hinge"
    bl_label = "Hinge"
    bl_description = (
        "Hinge the selection around the edge under the mouse. Type the "
        "angle, Ctrl+Wheel segments, A flush to a face, LMB/Enter confirm"
    )
    bl_options = {"REGISTER"}
    is_bindable = True

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.type == "MESH" and obj.mode == "EDIT"

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def invoke(self, context, event):
        obj = context.active_object
        self.obj = obj
        self.bm = bmesh.from_edit_mesh(obj.data)
        self.bm.faces.ensure_lookup_table()
        self.bm.edges.ensure_lookup_table()
        self.bm.normal_update()

        faces = [f for f in self.bm.faces if f.select]
        if faces:
            edges = []
            seen = set()
            for f in faces:
                for e in f.edges:
                    if e not in seen:
                        seen.add(e)
                        edges.append(e)
            self.mode = "face"
        else:
            edges = [e for e in self.bm.edges if e.select]
            self.mode = "edge"
        if not edges:
            self.report({"WARNING"}, "Hinge: select faces or edges")
            return {"CANCELLED"}

        vert_set = set()
        for e in edges:
            vert_set.update(e.verts)
        verts = list(vert_set)
        orig_cos = [v.co.copy() for v in verts]

        self._faces = faces
        self._edges = edges          # axis candidates (and the edge-mode geometry)
        self._verts = verts
        self._orig_cos = orig_cos
        self._orig_co_map = {v: c for v, c in zip(verts, orig_cos)}
        self._orig_normal = _selection_normal(faces, edges, orig_cos)

        props = context.scene.IOPS
        self._steps = max(1, props.shear_hinge_last_steps)
        self._angle_deg = props.shear_hinge_last_angle
        self.input_str = ""

        self._mouse_xy = (event.mouse_region_x, event.mouse_region_y)
        self._axis_edge = None
        self._center = None
        self._axis = None
        self._axis_pts = None
        # "edge": axis follows the edge under the mouse. "bbox": axis is
        # one of the four OBB sides (F cycles, LMB on a side dot picks).
        self._axis_mode = "edge"
        self._bbox_sides = self._compute_bbox_sides()
        self._bbox_idx = 0
        self._hotspots = []          # [{"region_pt", "side_idx"}], rebuilt each draw
        self._hover_idx = None
        edge = self._pick_edge(context)
        if edge is None:
            edge_set = set(edges)
            try:
                for item in self.bm.select_history:
                    if isinstance(item, bmesh.types.BMEdge) and item in edge_set:
                        edge = item
            except (TypeError, RuntimeError):
                pass
        if edge is None:
            edge = edges[0]
        if not self._set_axis(edge):
            self.report({"WARNING"}, "Hinge: degenerate axis edge")
            return {"CANCELLED"}

        self._align_bvh = None
        self._hud = HUDOverlay("mesh_hinge")
        self._hud.title = "Hinge"
        self._hud.bind_region(context.region)
        self._help = HelpOverlay("mesh_hinge")
        self._help.add_section(HUDSection("Hinge", [
            HUDItem("Axis = edge under mouse", "Move",      ItemState.ON, default_state=ItemState.OFF, always_show=True),
            HUDItem("Axis = bbox side",  "F / LMB dot", ItemState.ON, default_state=ItemState.OFF, always_show=True),
            HUDItem("Back to edge pick", "Tab",        ItemState.ON, default_state=ItemState.OFF, always_show=True),
            HUDItem("Type angle",     "0-9 . -",    ItemState.ON, default_state=ItemState.OFF, always_show=True),
            HUDItem("Angle ±5°",      "Alt+Wheel",  ItemState.ON, default_state=ItemState.OFF, always_show=True),
            HUDItem("Segments",       "Ctrl+Wheel", ItemState.ON, default_state=ItemState.OFF, always_show=True),
            HUDItem("Flip direction", "D",          ItemState.ON, default_state=ItemState.OFF, always_show=True),
            HUDItem("Flush to face",  "A",          ItemState.ON, default_state=ItemState.OFF, always_show=True),
            HUDItem("Confirm",        "LMB / Enter", ItemState.ON, default_state=ItemState.OFF, always_show=True),
            HUDItem("Cancel",         "Esc / RMB",  ItemState.ON, default_state=ItemState.OFF, always_show=True),
            HUDItem("Help / Toggle HUD", "H",       ItemState.ON, default_state=ItemState.OFF, always_show=True),
        ]))
        self._help.bind_region(context.region)
        self._last_event = capture_event(event, getattr(self, "_last_event", None))

        self._handle = safe_handler_add(
            bpy.types.SpaceView3D, self._draw_callback, (context,),
            "WINDOW", "POST_PIXEL", tick=True)
        context.workspace.status_text_set(self._status_text())
        context.window_manager.modal_handler_add(self)
        if context.area:
            context.area.tag_redraw()
        return {"RUNNING_MODAL"}

    def _finish(self, context):
        if getattr(self, "_handle", None):
            safe_handler_remove(self._handle, bpy.types.SpaceView3D, "WINDOW")
            self._handle = None
        context.workspace.status_text_set(None)
        if context.area:
            context.area.tag_redraw()
        # Drop bmesh refs so a later undo can't leave the operator
        # instance holding a dead wrapper (see mesh_shear._finish).
        self.bm = None
        self.obj = None
        self._faces = []
        self._edges = []
        self._verts = []
        self._orig_co_map = {}
        self._axis_edge = None
        self._align_bvh = None

    def cancel(self, context):
        self._finish(context)

    # ------------------------------------------------------------------
    # Axis
    # ------------------------------------------------------------------

    def _pick_edge(self, context):
        if not self._edges or context.region_data is None:
            return None
        idx, _ = closest_edge_screen(context, self._edges,
                                     self.obj.matrix_world, self._mouse_xy)
        return None if idx is None else self._edges[idx]

    def _set_axis(self, edge):
        if edge is None or not edge.is_valid:
            return False
        v0, v1 = edge.verts
        return self._set_axis_line(v0.co, v1.co, edge)

    def _compute_bbox_sides(self):
        """Four (a, b) endpoint pairs — the sides of the selection's
        min-OBB in its plane, in order +a, +b, -a, -b (side at the
        positive/negative end of the a/b extent). Empty when the
        selection has no plane."""
        n = self._orig_normal
        cos = self._orig_cos
        if n is None or len(cos) < 2:
            return []
        pa, pb = profile_principal_axes(cos, n)
        if pa is None or pb is None:
            return []
        centroid = Vector((0.0, 0.0, 0.0))
        for co in cos:
            centroid += co
        centroid /= len(cos)
        a_projs = [(co - centroid).dot(pa) for co in cos]
        b_projs = [(co - centroid).dot(pb) for co in cos]
        a_min, a_max = min(a_projs), max(a_projs)
        b_min, b_max = min(b_projs), max(b_projs)
        c = centroid + pa * ((a_min + a_max) * 0.5) + pb * ((b_min + b_max) * 0.5)
        ha = (a_max - a_min) * 0.5
        hb = (b_max - b_min) * 0.5
        sides = []
        for off_dir, off, along, half in ((pa, ha, pb, hb), (pb, hb, pa, ha),
                                          (-pa, ha, pb, hb), (-pb, hb, pa, ha)):
            mid = c + off_dir * off
            if half < 1e-9:
                continue
            sides.append((mid - along * half, mid + along * half))
        return sides

    def _edge_matching_line(self, a, b, tol=1e-5):
        """Candidate edge whose verts coincide with line endpoints a/b,
        so a bbox side lying on a real edge keeps the flap semantics."""
        for e in self._edges:
            if not e.is_valid:
                continue
            c0, c1 = e.verts[0].co, e.verts[1].co
            if ((c0 - a).length < tol and (c1 - b).length < tol) or \
               ((c0 - b).length < tol and (c1 - a).length < tol):
                return e
        return None

    def _set_bbox_side(self, idx):
        if not self._bbox_sides:
            return False
        idx %= len(self._bbox_sides)
        a, b = self._bbox_sides[idx]
        edge = self._edge_matching_line(a, b)
        if not self._set_axis_line(a, b, edge):
            return False
        self._bbox_idx = idx
        self._axis_mode = "bbox"
        return True

    def _set_axis_line(self, a, b, edge):
        axis = b - a
        if axis.length < 1e-9:
            return False
        axis = axis.normalized()
        center = (a + b) * 0.5
        # Sign convention: a positive angle swings the selection
        # centroid toward its own normal (lifts a face off its plane),
        # independent of the axis edge's vert order.
        n = self._orig_normal
        if n is not None:
            centroid = Vector((0.0, 0.0, 0.0))
            for co in self._orig_cos:
                centroid += co
            centroid /= max(1, len(self._orig_cos))
            tangent = axis.cross(centroid - center)
            if tangent.length > 1e-9 and tangent.dot(n) < 0:
                axis = -axis
        self._axis_edge = edge
        self._axis = axis
        self._center = center.copy()
        self._axis_pts = (a.copy(), b.copy())
        return True

    def _update_hover(self):
        HOVER_PX = 14.0
        mx, my = self._mouse_xy
        best = (None, HOVER_PX * HOVER_PX)
        for i, h in enumerate(self._hotspots):
            rp = h.get("region_pt")
            if rp is None:
                continue
            dx, dy = rp[0] - mx, rp[1] - my
            d2 = dx * dx + dy * dy
            if d2 < best[1]:
                best = (i, d2)
        self._hover_idx = best[0]

    def _repick(self, context):
        if self._axis_mode != "edge":
            return False
        edge = self._pick_edge(context)
        if edge is None or edge is self._axis_edge:
            return False
        return self._set_axis(edge)

    # ------------------------------------------------------------------
    # Angle
    # ------------------------------------------------------------------

    def _effective_angle(self):
        if self.input_str and self.input_str not in ("-", ".", "-."):
            try:
                return float(self.input_str)
            except ValueError:
                return self._angle_deg
        return self._angle_deg

    def _flush_pick(self, context):
        """A: set the angle so the selection's ORIGINAL plane lands
        coplanar with the face under the cursor (smallest-magnitude
        solution). Picking a hinged face or empty space is a no-op."""
        if self._orig_normal is None:
            self.report({"INFO"}, "hinge flush: selection has no reference plane")
            return
        self.bm.normal_update()
        self.bm.faces.ensure_lookup_table()
        self._align_bvh = BVHTree.FromBMesh(self.bm)
        picked = self._raycast_face_under_cursor(context)
        self._align_bvh = None
        if picked is None or picked in set(self._faces):
            self.report({"INFO"}, "hinge flush: pick a face outside the selection")
            return
        n_t = _face_normal_safe(picked)
        if n_t.length < 1e-9:
            self.report({"INFO"}, "hinge flush: degenerate target face")
            return
        ang = flush_angle(tuple(self._orig_normal), tuple(n_t), tuple(self._axis))
        if ang is None:
            self.report({"INFO"}, "hinge flush: target parallel to hinge axis")
            return
        self._angle_deg = math.degrees(ang)
        self.input_str = ""

    def _raycast_face_under_cursor(self, context):
        if self._align_bvh is None:
            return None
        region = context.region
        rv3d = context.region_data
        if region is None or rv3d is None:
            return None
        coord = self._mouse_xy
        view_dir = view3d_utils.region_2d_to_vector_3d(region, rv3d, coord)
        ray_origin = view3d_utils.region_2d_to_origin_3d(region, rv3d, coord)
        mw = self.obj.matrix_world
        try:
            mw_inv = mw.inverted()
        except ValueError:
            return None
        local_origin = mw_inv @ ray_origin
        local_dir = (mw_inv @ (ray_origin + view_dir)) - local_origin
        if local_dir.length < 1e-12:
            return None
        hit = self._align_bvh.ray_cast(local_origin, local_dir.normalized())
        if hit is None or hit[2] is None:
            return None
        idx = hit[2]
        self.bm.faces.ensure_lookup_table()
        if 0 <= idx < len(self.bm.faces):
            return self.bm.faces[idx]
        return None

    # ------------------------------------------------------------------
    # Modal
    # ------------------------------------------------------------------

    def _status_text(self):
        typed = f" | typing: {self.input_str}" if self.input_str else ""
        return (
            f"Hinge ({self.mode}): {self._effective_angle():.2f}° | "
            f"steps: {self._steps}{typed} | axis: {self._axis_mode} | "
            "[Move] pick axis edge | [F/LMB dot] bbox side | [Tab] edge pick | "
            "[0-9 . -] type | [Alt+Wheel] ±5° | [Ctrl+Wheel] steps | "
            "[D] flip | [A] flush to face | "
            "[LMB/Enter] confirm | [Esc/RMB] cancel"
        )

    def modal(self, context, event):
        try:
            return self._modal(context, event)
        except ReferenceError:
            self._finish(context)
            self.report({"WARNING"},
                        "hinge: bmesh data became invalid — operator cancelled")
            return {"CANCELLED"}
        except Exception:
            self._finish(context)
            raise

    def _modal(self, context, event):
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
                return {"RUNNING_MODAL"}
            if hud is not None and hud.handle_drag_event(context, event, theme_prefs):
                return {"RUNNING_MODAL"}
            if helpo is not None and helpo.handle_toggle_event(event, theme_prefs):
                return {"RUNNING_MODAL"}
            if hud is not None and hud.handle_param_toggle_event(event, theme_prefs):
                return {"RUNNING_MODAL"}

        if event.type in {"WHEELUPMOUSE", "WHEELDOWNMOUSE"}:
            if event.alt:
                delta = 5.0 if event.type == "WHEELUPMOUSE" else -5.0
                self._angle_deg = self._effective_angle() + delta
                self.input_str = ""
            elif event.ctrl:
                delta = 1 if event.type == "WHEELUPMOUSE" else -1
                self._steps = max(1, self._steps + delta)
            else:
                return {"PASS_THROUGH"}
            context.workspace.status_text_set(self._status_text())
            return {"RUNNING_MODAL"}

        if (event.type == "MIDDLEMOUSE" or event.type.startswith("NDOF")
                or event.type.startswith("TRACKPAD")):
            return {"PASS_THROUGH"}

        if event.type == "MOUSEMOVE":
            self._mouse_xy = (event.mouse_region_x, event.mouse_region_y)
            self._update_hover()
            self._repick(context)
            return {"RUNNING_MODAL"}

        if event.value == "PRESS":
            if event.type in DIGIT_TYPES:
                self.input_str += DIGIT_TYPES[event.type]
            elif event.type in {"PERIOD", "NUMPAD_PERIOD"}:
                if "." not in self.input_str:
                    self.input_str += "."
            elif event.type in {"MINUS", "NUMPAD_MINUS"}:
                if self.input_str.startswith("-"):
                    self.input_str = self.input_str[1:]
                else:
                    self.input_str = "-" + self.input_str
            elif event.type == "BACK_SPACE":
                self.input_str = self.input_str[:-1]
            elif event.type == "D":
                if self.input_str:
                    if self.input_str.startswith("-"):
                        self.input_str = self.input_str[1:]
                    else:
                        self.input_str = "-" + self.input_str
                else:
                    self._angle_deg = -self._angle_deg
            elif event.type == "A":
                self._mouse_xy = (event.mouse_region_x, event.mouse_region_y)
                self._flush_pick(context)
            elif event.type == "F":
                if self._bbox_sides:
                    nxt = (self._bbox_idx + 1) if self._axis_mode == "bbox" else 0
                    self._set_bbox_side(nxt)
                else:
                    self.report({"INFO"}, "hinge: selection has no bbox plane")
            elif event.type == "TAB":
                self._axis_mode = "edge"
                self._mouse_xy = (event.mouse_region_x, event.mouse_region_y)
                edge = self._pick_edge(context)
                if edge is not None:
                    self._set_axis(edge)
            elif event.type == "LEFTMOUSE" and self._hover_idx is not None:
                h = self._hotspots[self._hover_idx]
                self._set_bbox_side(h["side_idx"])
            elif event.type in {"LEFTMOUSE", "RET", "NUMPAD_ENTER", "SPACE"}:
                return self._confirm(context)
            elif event.type in {"RIGHTMOUSE", "ESC"}:
                self._finish(context)
                return {"CANCELLED"}
            context.workspace.status_text_set(self._status_text())
            return {"RUNNING_MODAL"}
        return {"RUNNING_MODAL"}

    # ------------------------------------------------------------------
    # Confirm
    # ------------------------------------------------------------------

    def _confirm(self, context):
        angle_rad = math.radians(self._effective_angle())
        if abs(angle_rad) < 1e-6:
            self._finish(context)
            return {"CANCELLED"}
        props = context.scene.IOPS
        props.shear_hinge_last_angle = math.degrees(angle_rad)
        props.shear_hinge_last_steps = self._steps

        bm = self.bm
        axis_edge = self._axis_edge
        if self.mode == "face":
            # Flap case (every face at the hinge edge is selected): drop
            # the edge from the selection so spin bends the flap instead
            # of extruding a wall from the hinge line.
            if (axis_edge is not None and axis_edge.is_valid and axis_edge.link_faces
                    and all(f.select for f in axis_edge.link_faces)):
                axis_edge.select = False
                axis_edge.verts[0].select = False
                axis_edge.verts[1].select = False
            faces = [f for f in bm.faces if f.select]
            edges = [e for e in bm.edges if e.select]
            verts = [v for v in bm.verts if v.select]
            geom = edges + faces + verts
        else:
            # Edge mode: the axis edge stays put; every other selected
            # edge sweeps into a wall.
            edges = [e for e in self._edges if e.is_valid and e is not axis_edge]
            vert_set = set()
            for e in edges:
                vert_set.update(e.verts)
            geom = edges + list(vert_set)
        if not geom:
            self.report({"WARNING"}, "hinge: nothing to spin")
            self._finish(context)
            return {"CANCELLED"}
        for g in geom:
            g.select = False

        result = bmesh.ops.spin(
            bm, geom=geom, cent=self._center, axis=self._axis,
            angle=angle_rad, steps=self._steps, use_merge=False)
        last = result["geom_last"]

        dist = 0.001
        seed = [g for g in last if isinstance(g, bmesh.types.BMVert)]
        if seed:
            bmesh.ops.remove_doubles(
                bm, verts=_gather_double_verts(seed, dist), dist=dist)

        try:
            bm.select_history.clear()
        except (TypeError, RuntimeError):
            pass
        for v in bm.verts:
            v.select = False
        for e in bm.edges:
            e.select = False
        for f in bm.faces:
            f.select = False
        for g in last:
            if g.is_valid:
                g.select_set(True)
        bm.select_flush_mode()
        bm.normal_update()
        bmesh.update_edit_mesh(self.obj.data, loop_triangles=True,
                               destructive=True)
        bpy.ops.ed.undo_push(message="Hinge")
        self._finish(context)
        return {"FINISHED"}

    # ------------------------------------------------------------------
    # Draw
    # ------------------------------------------------------------------

    def _draw_dot(self, p, *, color, context, radius=6.0):
        if radius <= 4.0:
            size_token = "preview"
        elif radius <= 6.0:
            size_token = "default"
        elif radius <= 9.0:
            size_token = "active"
        else:
            size_token = "closest"
        draw_prim.points([p], color=color, size=size_token, context=context)

    def _draw_callback(self, context):
        region = context.region
        rv3d = context.region_data
        if rv3d is None:
            return
        try:
            mw = self.obj.matrix_world
            if self._axis is None:
                return
        except (ReferenceError, AttributeError):
            h = getattr(self, "_handle", None)
            if h is not None:
                try:
                    safe_handler_remove(h, bpy.types.SpaceView3D, "WINDOW")
                except (ValueError, RuntimeError, ReferenceError):
                    pass
            return
        theme = get_theme(context)
        gpu.state.blend_set("ALPHA")
        self._draw_ghost(region, rv3d, mw, context=context, theme=theme)
        self._draw_bbox_sides(region, rv3d, mw, context=context, theme=theme)
        gpu.state.blend_set("NONE")
        self._draw_hud(context)

    def _draw_bbox_sides(self, region, rv3d, mw, *, context, theme):
        """OBB outline (dim) with a clickable dot at each side's midpoint.
        The current bbox side (if any) is drawn amber like the axis;
        the hovered dot is highlighted white."""
        self._hotspots = []
        sides = getattr(self, "_bbox_sides", [])
        if not sides:
            return

        def s2d(co):
            return view3d_utils.location_3d_to_region_2d(region, rv3d, mw @ co)

        segs = []
        for a, b in sides:
            pa, pb = s2d(a), s2d(b)
            if pa is not None and pb is not None:
                segs.extend([pa, pb])
        if segs:
            draw_prim.edges_3d(segs, color=(0.45, 0.45, 0.45, 0.55), context=context)
        locked = theme.color_for(Role.LOCKED_POINT)
        for i, (a, b) in enumerate(sides):
            mid = (a + b) * 0.5
            rp = s2d(mid)
            if rp is None:
                continue
            self._hotspots.append({"region_pt": (rp[0], rp[1]), "side_idx": i})
            active = (self._axis_mode == "bbox" and i == self._bbox_idx)
            self._draw_dot(rp, radius=6.0 if active else 5.0,
                           color=(*locked[:3], 1.0 if active else 0.6),
                           context=context)
        self._update_hover()
        if self._hover_idx is not None and self._hover_idx < len(self._hotspots):
            self._draw_dot(self._hotspots[self._hover_idx]["region_pt"], radius=8.0,
                           color=(1.0, 1.0, 1.0, 1.0), context=context)

    def _draw_ghost(self, region, rv3d, mw, *, context, theme):
        """Ghost of the FINAL spin result: outlines at the target angle
        (bright), intermediate segment rings (dim), the wall arcs each
        vert traces, the axis (amber) and its midpoint."""
        def s2d(co):
            return view3d_utils.location_3d_to_region_2d(region, rv3d, mw @ co)

        angle_rad = math.radians(self._effective_angle())
        axis = self._axis
        center = self._center
        steps = max(1, self._steps)
        axis_edge = self._axis_edge

        step_cos = []
        for k in range(steps + 1):
            rot = Matrix.Rotation(angle_rad * (k / steps), 4, axis)
            step_cos.append({
                v: center + rot @ (oc - center)
                for v, oc in self._orig_co_map.items()
            })

        def outline_segs(co_map):
            segs = []
            if self.mode == "face":
                for f in self._faces:
                    if not f.is_valid:
                        continue
                    loop = list(f.verts)
                    n = len(loop)
                    for i in range(n):
                        a = co_map.get(loop[i])
                        b = co_map.get(loop[(i + 1) % n])
                        if a is None or b is None:
                            continue
                        pa, pb = s2d(a), s2d(b)
                        if pa is not None and pb is not None:
                            segs.extend([pa, pb])
            else:
                for e in self._edges:
                    if not e.is_valid or e is axis_edge:
                        continue
                    a = co_map.get(e.verts[0])
                    b = co_map.get(e.verts[1])
                    if a is None or b is None:
                        continue
                    pa, pb = s2d(a), s2d(b)
                    if pa is not None and pb is not None:
                        segs.extend([pa, pb])
            return segs

        def fill_tris(co_map):
            tris = []
            for f in self._faces:
                if not f.is_valid:
                    continue
                pts = []
                for v in f.verts:
                    co = co_map.get(v)
                    p = s2d(co) if co is not None else None
                    if p is None:
                        pts = []
                        break
                    pts.append(p)
                for i in range(1, len(pts) - 1):
                    tris.extend([pts[0], pts[i], pts[i + 1]])
            return tris

        moving = abs(angle_rad) > 1e-6
        if moving:
            for k in range(1, steps):
                segs = outline_segs(step_cos[k])
                if segs:
                    draw_prim.edges_3d(segs, role=Role.PREVIEW_LINE, context=context)
            wall_segs = []
            for v in self._verts:
                for k in range(steps):
                    a = step_cos[k].get(v)
                    b = step_cos[k + 1].get(v)
                    if a is None or b is None:
                        continue
                    pa, pb = s2d(a), s2d(b)
                    if pa is not None and pb is not None:
                        wall_segs.extend([pa, pb])
            if wall_segs:
                draw_prim.edges_3d(wall_segs, role=Role.PREVIEW_LINE, context=context)
        cap_tris = fill_tris(step_cos[steps])
        if cap_tris:
            draw_prim.tris(cap_tris, color=theme.color_for(Role.GHOST_ACTIVE),
                           context=context)
        final_segs = outline_segs(step_cos[steps])
        if final_segs:
            draw_prim.edges_3d(final_segs, role=Role.ACTIVE_LINE, context=context)

        pa, pb = self._axis_pts
        p0, p1 = s2d(pa), s2d(pb)
        if p0 is not None and p1 is not None:
            draw_prim.edges_3d([p0, p1], role=Role.LOCKED_LINE, context=context)
        pc = s2d(center)
        if pc is not None:
            self._draw_dot(pc, radius=5.0,
                           color=theme.color_for(Role.LOCKED_POINT), context=context)

    def _draw_hud(self, context):
        hud = getattr(self, "_hud", None)
        helpo = getattr(self, "_help", None)
        last_event = getattr(self, "_last_event", None)
        if helpo is not None:
            helpo.draw(context, last_event)
        if hud is None:
            return
        lines = [f"Mode: {self.mode} | axis: {self._axis_mode}",
                 f"Angle: {self._effective_angle():.2f}°",
                 f"Steps: {self._steps}"]
        if self.input_str:
            lines.append(f"Typing: {self.input_str}")
        hud.set_header(*lines)
        hud.draw(context, last_event)
