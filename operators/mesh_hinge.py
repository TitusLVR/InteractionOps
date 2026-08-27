"""Hinge: rotate the selection around one of its own edges, baking the
sweep as real segment geometry (bmesh.ops.spin).

Selection
- faces: the selected faces rotate; the axis is one of their edges.
- edges (no faces): the selected edges rotate — open boundary loops,
  wire profiles — and the spin walls become the new faces. The axis is
  one of the selected edges (it stays put), or the *virtual edge*: the
  chord between the first and last vert of an open chain, drawn with
  the chain and pickable like any real edge.
- B toggles the bounding-box axis set: the four sides of the
  selection's min-OBB (the same box Shear builds — faces: mean face
  normal; edges: best-fit plane of the chain) replace the edges as
  pick candidates, so the hinge can run along a box side that has no
  edge under it. B again returns to edges.

The axis edge is whichever candidate edge is nearest to the mouse in
screen space (same pick as cursor_bisect) and it is re-picked live on
mouse move, so aiming is the whole interaction. Typed digits, Alt+Wheel
(±5°) and A (flush to the face under the cursor) set the angle;
Ctrl+Wheel sets the segment count; D flips the sign. The preview is a
draw-only ghost — the mesh does not move until confirm (LMB / Enter /
Space). Angle and segments persist in Scene.IOPS.
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
                         chains_from_edges, chain_normal, profile_principal_axes)


class _Pt:
    __slots__ = ("co", "is_valid")

    def __init__(self, co):
        self.co = co
        self.is_valid = True


class _LineCandidate:
    """Axis candidate given by two fixed points (a bbox side). Quacks like
    a BMEdge for the picker and the axis setter; never selectable."""
    is_virtual = True
    link_faces = ()
    is_valid = True

    def __init__(self, a, b):
        self.verts = (_Pt(a.copy()), _Pt(b.copy()))


def _bbox_sides(cos, normal):
    """Four (a, b) side segments of the min-OBB of ``cos`` in the plane
    ``normal`` — the same box Shear builds for its profile."""
    if normal is None or len(cos) < 3:
        return []
    pa, pb = profile_principal_axes(cos, normal)
    if pa is None or pb is None:
        return []
    centroid = Vector((0.0, 0.0, 0.0))
    for co in cos:
        centroid += co
    centroid /= len(cos)
    a_p = [(co - centroid).dot(pa) for co in cos]
    b_p = [(co - centroid).dot(pb) for co in cos]
    a0, a1, b0, b1 = min(a_p), max(a_p), min(b_p), max(b_p)
    if a1 - a0 < 1e-9 or b1 - b0 < 1e-9:
        return []
    corners = [centroid + pa * a + pb * b
               for a, b in ((a0, b0), (a1, b0), (a1, b1), (a0, b1))]
    return [(corners[i], corners[(i + 1) % 4]) for i in range(4)]


class _VirtualEdge:
    """Axis candidate that isn't in the mesh: the chord between the first
    and last vert of an open edge chain. Quacks like a BMEdge for the
    picker (``verts`` with ``.co``) and the axis setter."""
    is_virtual = True
    link_faces = ()

    def __init__(self, v0, v1):
        self.verts = (v0, v1)

    @property
    def is_valid(self):
        return self.verts[0].is_valid and self.verts[1].is_valid


def _virtual_edges(edges):
    """One chord per open chain of ``edges`` (2+ edges, distinct ends)."""
    out = []
    try:
        chains = chains_from_edges([e for e in edges if e.is_valid])
    except ValueError:
        return out
    for verts, chain, closed in chains:
        if closed or len(chain) < 2:
            continue
        v0, v1 = verts[0], verts[-1]
        if v0 is v1 or (v0.co - v1.co).length < 1e-9:
            continue
        out.append(_VirtualEdge(v0, v1))
    return out


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
        self._geom_edges = edges     # real edges (edge-mode spin geometry)
        self._virtual = _virtual_edges(edges) if not faces else []
        self._edge_candidates = edges + self._virtual
        self._edges = self._edge_candidates   # current axis candidates
        self._bbox_mode = False
        self._verts = verts
        self._orig_cos = orig_cos
        self._orig_co_map = {v: c for v, c in zip(verts, orig_cos)}
        self._orig_normal = _selection_normal(faces, edges, orig_cos)
        # Box plane: faces -> their mean normal; edges -> best-fit plane
        # of the chain verts (what Shear uses for its virtual face).
        if faces:
            box_normal = self._orig_normal
        else:
            # Best-fit needs the polygon ORDER: walk the chain (largest
            # one when several) exactly like Shear does for its
            # virtual face; an unordered vert set gives a bogus plane.
            box_normal = None
            try:
                chains = chains_from_edges([e for e in edges if e.is_valid])
            except ValueError:
                chains = []
            if chains:
                verts_o, chain_o, _closed = max(chains, key=lambda c: len(c[1]))
                box_normal = chain_normal(chain_o, [v.co for v in verts_o])
            if box_normal is not None and self._orig_normal is not None                     and not faces:
                # Keep flush/sign reference consistent with the box plane.
                self._orig_normal = box_normal
        self._bbox = [_LineCandidate(a, b)
                      for a, b in _bbox_sides(orig_cos, box_normal)]

        props = context.scene.IOPS
        self._steps = max(1, props.shear_hinge_last_steps)
        self._angle_deg = props.shear_hinge_last_angle
        self.input_str = ""

        self._mouse_xy = (event.mouse_region_x, event.mouse_region_y)
        self._axis_edge = None
        self._center = None
        self._axis = None
        self._axis_pts = None
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
            edge = self._edges[0]
        if not self._set_axis(edge):
            self.report({"WARNING"}, "Hinge: degenerate axis edge")
            return {"CANCELLED"}

        self._align_bvh = None
        # A flush mode: while active, the face under the cursor is
        # highlighted (theme match-hint tint) and the hinge angle
        # follows it live; the axis edge stops re-picking meanwhile.
        self._flush_active = False
        self._flush_face = None
        self._hud = HUDOverlay("mesh_hinge")
        self._hud.title = "Hinge"
        self._hud.bind_region(context.region)
        self._help = HelpOverlay("mesh_hinge")
        self._help.add_section(HUDSection("Hinge", [
            HUDItem("Axis = edge under mouse", "Move",      ItemState.ON, default_state=ItemState.OFF, always_show=True),
            HUDItem("Type angle",     "0-9 . -",    ItemState.ON, default_state=ItemState.OFF, always_show=True),
            HUDItem("Angle ±5°",      "Alt+Wheel",  ItemState.ON, default_state=ItemState.OFF, always_show=True),
            HUDItem("Segments",       "Ctrl+Wheel", ItemState.ON, default_state=ItemState.OFF, always_show=True),
            HUDItem("Flip direction", "D",          ItemState.ON, default_state=ItemState.OFF, always_show=True),
            HUDItem("Flush to face under mouse (toggle)", "A", ItemState.ON, default_state=ItemState.OFF, always_show=True),
            HUDItem("Bbox sides as axes (toggle)", "B", ItemState.ON, default_state=ItemState.OFF, always_show=True),
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
        self._geom_edges = []
        self._virtual = []
        self._verts = []
        self._orig_co_map = {}
        self._axis_edge = None
        self._align_bvh = None
        self._flush_active = False
        self._flush_face = None
        self._edge_candidates = []
        self._bbox = []

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
        axis = v1.co - v0.co
        if axis.length < 1e-9:
            return False
        axis = axis.normalized()
        center = (v0.co + v1.co) * 0.5
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
        self._axis_pts = (v0.co.copy(), v1.co.copy())
        return True

    def _bbox_toggle(self, context):
        """B: swap the axis candidates between the mesh edges (+ virtual
        chords) and the four bbox sides, then re-pick under the mouse."""
        if not self._bbox:
            self.report({"INFO"}, "hinge: selection has no bbox plane")
            return
        self._bbox_mode = not self._bbox_mode
        self._edges = self._bbox if self._bbox_mode else self._edge_candidates
        edge = self._pick_edge(context)
        if edge is None:
            edge = self._edges[0]
        self._set_axis(edge)

    def _repick(self, context):
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

    def _flush_toggle(self, context):
        """A: enter/leave flush mode. Entering snapshots a BVH of the
        mesh (it doesn't change during the modal) and runs one pick."""
        if self._flush_active:
            self._flush_active = False
            self._flush_face = None
            self._align_bvh = None
            return
        if self._orig_normal is None:
            self.report({"INFO"}, "hinge flush: selection has no reference plane")
            return
        self.bm.normal_update()
        self.bm.faces.ensure_lookup_table()
        self._align_bvh = BVHTree.FromBMesh(self.bm)
        self._flush_active = True
        self._flush_face = None
        self._flush_update(context)

    def _flush_update(self, context):
        """Flush mode MOUSEMOVE: highlight the face under the cursor
        and set the angle so the selection's ORIGINAL plane lands
        coplanar with it (smallest-magnitude solution). Hinged faces
        and empty space leave the last angle alone."""
        picked = self._raycast_face_under_cursor(context)
        if picked is None or picked in set(self._faces):
            self._flush_face = None
            return
        n_t = _face_normal_safe(picked)
        if n_t.length < 1e-9:
            self._flush_face = None
            return
        # Fold the flap ONTO the target face — lid-on-box: the two end
        # up facing each other (normals anti-parallel), not the shortest
        # way round and not the coplanar continuation. D flips if needed.
        ang = flush_angle(tuple(self._orig_normal), tuple(n_t), tuple(self._axis),
                          prefer="antiparallel")
        self._flush_face = picked
        if ang is None:
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
            f"steps: {self._steps}{typed}"
            f"{' | FLUSH: aim at a face' if self._flush_active else ''}"
            f"{' | axis: bbox' if self._bbox_mode else ''} | "
            "[Move] pick axis | [B] bbox sides | "
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
            if self._flush_active:
                self._flush_update(context)
                context.workspace.status_text_set(self._status_text())
            else:
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
                self._flush_toggle(context)
            elif event.type == "B":
                self._mouse_xy = (event.mouse_region_x, event.mouse_region_y)
                self._bbox_toggle(context)
            elif event.type in {"LEFTMOUSE", "RET", "NUMPAD_ENTER", "SPACE"}:
                return self._confirm(context)
            elif event.type in {"RIGHTMOUSE", "ESC"}:
                if self._flush_active:
                    # First Esc only leaves flush mode (angle kept).
                    self._flush_toggle(context)
                else:
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
            edges = [e for e in self._geom_edges
                     if e.is_valid and e is not axis_edge]
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

        # Snapshot the final ring's vert positions BEFORE the doubles
        # pass: welding a ring vert that landed on the axis splices its
        # edges, so `last` may hold dead BMEdge refs afterwards. The
        # result selection is rebuilt from positions instead.
        dist = 0.001
        seed = [g for g in last if isinstance(g, bmesh.types.BMVert)]
        last_cos = [v.co.copy() for v in seed]
        # Edge mode: the axis edge stays part of the profile. Its verts
        # join the ring snapshot so whatever edge survives the weld
        # between them gets selected (the original BMEdge is spliced
        # away when its verts absorb their spun copies).
        if (self.mode == "edge" and axis_edge is not None
                and not getattr(axis_edge, "is_virtual", False)):
            last_cos.extend(v.co.copy() for v in axis_edge.verts)
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
        def ring_verts():
            out = set()
            for v in bm.verts:
                for co in last_cos:
                    if (v.co - co).length <= dist:
                        out.add(v)
                        break
            return out

        # Spinning a vert that sits ON the axis leaves zero-length edges
        # between its (now welded) copies; dissolve them around the ring.
        ring = ring_verts()
        degenerate = [e for e in bm.edges
                      if (e.verts[0] in ring or e.verts[1] in ring)
                      and (e.verts[0].co - e.verts[1].co).length <= dist]
        if degenerate:
            bmesh.ops.dissolve_degenerate(bm, dist=dist, edges=degenerate)
            ring = ring_verts()
        for g in last:
            if isinstance(g, bmesh.types.BMFace) and g.is_valid:
                g.select_set(True)
        # Every edge between ring verts: the spun profile copy, and —
        # in edge mode — the axis edge itself, which stayed put and is
        # still part of the profile (both its verts are ring verts
        # after the weld). Virtual chords have nothing to select.
        for e in bm.edges:
            if e.verts[0] in ring and e.verts[1] in ring:
                e.select_set(True)
        if self.mode == "edge":
            # Flush UP only: select_flush_mode in face select mode would
            # drop edges that don't complete a selected face — the
            # result profile is edges, not faces.
            bm.select_flush(True)
        else:
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
        if self._flush_active:
            self._draw_flush_face(region, rv3d, mw, context=context, theme=theme)
        gpu.state.blend_set("NONE")
        self._draw_hud(context)

    def _draw_flush_face(self, region, rv3d, mw, *, context, theme):
        """Flush target under the cursor: theme match-hint fill + outline."""
        f = self._flush_face
        if f is None or not f.is_valid:
            return
        pts = []
        for vt in f.verts:
            p = view3d_utils.location_3d_to_region_2d(region, rv3d, mw @ vt.co)
            if p is None:
                return
            pts.append(p)
        if len(pts) < 3:
            return
        tris = []
        for i in range(1, len(pts) - 1):
            tris.extend([pts[0], pts[i], pts[i + 1]])
        draw_prim.tris(tris, color=theme.color_for(Role.GHOST_MATCH_HINT),
                       context=context)
        segs = []
        for i in range(len(pts)):
            segs.extend([pts[i], pts[(i + 1) % len(pts)]])
        draw_prim.edges_3d(segs, role=Role.CLOSEST_LINE, context=context)

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
                # Real chain edges plus the virtual chords — the chord
                # sweeps with the chain so it reads as part of the
                # profile; as the axis it stays put (amber line below).
                for e in self._geom_edges + self._virtual:
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

        # Virtual chords at rest: dim, so the pick target is visible
        # even at zero angle (the real edges are already on screen).
        rest_segs = []
        for ve in self._virtual:
            if not ve.is_valid or ve is axis_edge:
                continue
            p0, p1 = s2d(ve.verts[0].co), s2d(ve.verts[1].co)
            if p0 is not None and p1 is not None:
                rest_segs.extend([p0, p1])
        if rest_segs:
            draw_prim.edges_3d(rest_segs, color=(0.6, 0.6, 0.6, 0.6), context=context)
        # Bbox mode: the box outline (theme BBOX role); the picked side
        # is the amber axis line below.
        if self._bbox_mode:
            box_segs = []
            for ln in self._bbox:
                if ln is axis_edge:
                    continue
                p0, p1 = s2d(ln.verts[0].co), s2d(ln.verts[1].co)
                if p0 is not None and p1 is not None:
                    box_segs.extend([p0, p1])
            if box_segs:
                draw_prim.edges_3d(box_segs, role=Role.BBOX, context=context)

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
        lines = [f"Mode: {self.mode}",
                 f"Angle: {self._effective_angle():.2f}°",
                 f"Steps: {self._steps}"]
        if self.input_str:
            lines.append(f"Typing: {self.input_str}")
        hud.set_header(*lines)
        hud.draw(context, last_event)
