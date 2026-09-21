"""Shared modal machinery for the iOps Falloff tools
(iops.mesh_falloff_move / _rotate / _scale).

Modo-style: the falloff is drawn first, LMB on a handle edits it, LMB
anywhere else drags the transform, release bakes and the tool stays live.
All weights and transforms are numpy over the *visible* verts of the
active edit mesh (utils/falloff_core.py); only rows with weight > 0 are
written back to bmesh each tick.

Hotkeys inside the modal: L/R/S/C falloff type, E connected-only toggle,
F shape cycle, I invert, A auto-size, V weight preview, X/Y/Z axis
constraint, Shift+Wheel falloff scalar (Ctrl+Shift fine), digits numeric
amount, Enter/Space confirm, Esc/RMB cancel.
"""
from __future__ import annotations

import math

import bpy
import bmesh
import numpy as np
from bpy_extras import view3d_utils
from mathutils import Vector

from ...ui.draw import primitives as draw_prim, Role, draw_scope, axis_color
from ...ui.draw import safe_handler_add, safe_handler_remove
from ...ui.draw.theme import get_theme
from ...ui.hud import (HUDOverlay, HelpOverlay, HUDSection, HUDItem,
                       HUDParam, ItemState, capture_event)
from ...ui.hud import text as hud_text
from ...utils import falloff_core as fc
from ..mesh_shear import DIGIT_TYPES

HANDLE_PX = 14.0
SNAP_PX = 16.0          # Ctrl handle-drag: snap radius to original-selection verts
AXIS_KEYS = ("X", "Y", "Z")
GIZMO_PX = 70.0         # origin gizmo tripod length on screen
BASIS_MODES = ("LOCAL", "CURSOR", "WORLD", "NORMAL")
BASIS_LABELS = {"LOCAL": "Local", "CURSOR": "Cursor", "WORLD": "World", "NORMAL": "Normal"}
TYPE_KEYS = {"L": "LINEAR", "R": "RADIAL", "S": "SCREEN", "C": "COPLANAR"}
TYPE_LABELS = {"LINEAR": "Linear", "RADIAL": "Radial", "SCREEN": "Screen",
               "COPLANAR": "Coplanar"}
PREVIEW_LOW = (0.35, 0.10, 0.60, 1.0)    # purple = no influence
PREVIEW_HIGH = (1.00, 0.90, 0.20, 1.0)   # yellow = full influence


class FalloffToolMixin:
    tool_label = "Falloff"
    undo_message = "Falloff"
    amount_label = "Amount"
    amount_fmt = "{:.3f}"
    gizmo_kind = "MOVE"      # "MOVE" | "ROTATE" | "SCALE" — origin gizmo shape

    bl_options = {"REGISTER"}
    is_bindable = True

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.type == "MESH" and obj.mode == "EDIT"

    # ------------------------------------------------------------------
    # Subclass hooks (documented in the plan's Interfaces block)
    # ------------------------------------------------------------------

    def _drag_begin(self, context, event):
        raise NotImplementedError

    def _drag_amount(self, context, event):
        raise NotImplementedError

    def _amount_from_number(self, value):
        raise NotImplementedError

    def _apply_amount(self, amount):
        raise NotImplementedError

    def _amount_text(self, amount):
        return self.amount_fmt.format(amount)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def invoke(self, context, event):
        obj = context.active_object
        self.obj = obj
        self._mw = obj.matrix_world.copy()
        self._mw_inv3 = self._mw.inverted().to_3x3()
        self._rv3d = context.region_data
        if self._rv3d is None:
            self.report({"WARNING"}, f"{self.tool_label}: run from a 3D viewport")
            return {"CANCELLED"}
        self._rv3d_ptr = self._rv3d.as_pointer()
        self._region = context.region
        self.bm = bmesh.from_edit_mesh(obj.data)
        self.bm.verts.ensure_lookup_table()
        self.bm.faces.ensure_lookup_table()
        self.bm.normal_update()

        if not self._build_affected():
            self.report({"WARNING"}, f"{self.tool_label}: mesh has no visible vertices")
            return {"CANCELLED"}
        self._coplanar_ok = self._coplanar_available()

        props = context.scene.IOPS
        self._ftype = props.falloff_type
        self._shape = props.falloff_shape
        self._invert = props.falloff_invert
        self._connected = props.falloff_connected
        self._preview = props.falloff_preview
        self._screen_px = float(props.falloff_screen_radius_px)
        self._coplanar_angle = float(props.falloff_coplanar_angle)
        self._basis_mode = props.falloff_basis
        self._basis_R = np.eye(3)
        self._pivot_moved = False
        self._set_basis(context)
        if self._ftype == "COPLANAR" and not self._coplanar_ok:
            self._ftype = "RADIAL"

        self._S = None
        self._E = None
        self._C = None
        self._r = 1.0
        self._autofit()

        self._W = None
        self._drag = None
        self._current_amount = None
        self._axis = None
        self.input_str = ""
        self._baked = False
        self._hotspots = []
        self._hover_idx = None
        self._handle_drag = None
        self._handle_axis = None      # X/Y/Z lock while dragging a handle
        self._handle_start = None     # handle position at drag start (object space)
        self._snap_on = False         # Ctrl held during a handle drag
        self._snap_pt = None          # current snap target (object space) for drawing
        self._screen_center = None
        self._mouse_xy = (event.mouse_region_x, event.mouse_region_y)
        self._adj = None
        self._face_data = None
        self._dirty = set()

        self._build_hud(context)
        self._last_event = capture_event(event, None)
        self._handle = safe_handler_add(
            bpy.types.SpaceView3D, self._draw_pixel, (context,),
            "WINDOW", "POST_PIXEL", tick=True)
        self._handle_3d = safe_handler_add(
            bpy.types.SpaceView3D, self._draw_view, (context,),
            "WINDOW", "POST_VIEW", tick=False)
        context.workspace.status_text_set(self._status_text())
        context.window_manager.modal_handler_add(self)
        if context.area:
            context.area.tag_redraw()
        return {"RUNNING_MODAL"}

    def _build_affected(self):
        verts = [v for v in self.bm.verts if not v.hide]
        if not verts:
            return False
        self._verts = verts
        self._row_of = {v: i for i, v in enumerate(verts)}
        n = len(verts)
        self._P_invoke = np.array([v.co[:] for v in verts], dtype=np.float64)
        self._P0 = self._P_invoke.copy()
        sel = np.array([v.select for v in verts], dtype=bool)
        self._has_selection = bool(sel.any())
        if not sel.any():
            sel = np.ones(n, dtype=bool)
        self._sel_mask = sel
        self._sel_rows = np.nonzero(sel)[0]
        self._pivot = fc.bbox_center(self._P0[sel])
        # Edges of the original selection (row pairs) — drawn as a ghost at
        # the pre-operation positions while the mesh is displaced, and the
        # target set for Ctrl handle snapping. Skipped when nothing is
        # selected (the whole mesh would be the ghost).
        self._ghost_pairs = []
        if self._has_selection:
            row_of = self._row_of
            for e in self.bm.edges:
                a, b = e.verts
                if a.select and b.select and a in row_of and b in row_of:
                    self._ghost_pairs.append((row_of[a], row_of[b]))
        return True

    def _coplanar_available(self):
        return any(f.select for f in self.bm.faces) or any(e.select for e in self.bm.edges)

    def _finish(self, context):
        for attr in ("_handle", "_handle_3d"):
            h = getattr(self, attr, None)
            if h is not None:
                safe_handler_remove(h, bpy.types.SpaceView3D, "WINDOW")
                setattr(self, attr, None)
        context.workspace.status_text_set(None)
        if context.area:
            context.area.tag_redraw()
        # Drop every bmesh reference: Blender keeps finished operator
        # instances in the redo stack and a stale wrapper crashes in
        # bpy_bmesh_dealloc during undo (see mesh_shear._finish).
        self.bm = None
        self.obj = None
        self._verts = []
        self._row_of = {}
        self._adj = None
        self._face_data = None
        self._P0 = None
        self._P_invoke = None
        self._W = None
        self._hotspots = []

    def cancel(self, context):
        self._finish(context)

    # ------------------------------------------------------------------
    # Falloff geometry
    # ------------------------------------------------------------------

    def _autofit(self):
        Psel = self._P0[self._sel_mask]
        if self._ftype == "LINEAR":
            self._S, self._E = fc.autofit_linear(Psel)
        elif self._ftype == "RADIAL":
            self._C, self._r = fc.autofit_radial(Psel)
        self._W = None

    def _set_type(self, context, ftype):
        if ftype == self._ftype:
            return
        if ftype == "COPLANAR" and not self._coplanar_ok:
            self.report({"INFO"}, "Coplanar needs a face or edge selection")
            return
        if ftype == "SCREEN":
            # Screen is anchored to the mouse, so a live operation from
            # another falloff cannot be re-evaluated under it — commit first.
            self._commit_live(context)
        self._ftype = ftype
        self._autofit()

    def _scalar_step(self, direction, fine):
        """Shift+Wheel: grow/shrink the active falloff's scalar."""
        f = (1.02 if fine else 1.10) if direction > 0 else (1 / 1.02 if fine else 1 / 1.10)
        if self._ftype == "RADIAL":
            self._r = max(1e-4, self._r * f)
        elif self._ftype == "LINEAR":
            self._E = self._S + (self._E - self._S) * f
        elif self._ftype == "SCREEN":
            step = 2.0 if fine else 10.0
            self._screen_px = max(5.0, self._screen_px + step * direction)
        elif self._ftype == "COPLANAR":
            step = math.radians(0.1 if fine else 1.0)
            self._coplanar_angle = min(math.pi / 2, max(0.0, self._coplanar_angle + step * direction))
        self._W = None

    # ------------------------------------------------------------------
    # Weights
    # ------------------------------------------------------------------

    def _ensure_adjacency(self):
        if self._adj is not None:
            return
        row_of = self._row_of
        adj = [[] for _ in self._verts]
        for e in self.bm.edges:
            a, b = e.verts
            ra = row_of.get(a)
            rb = row_of.get(b)
            if ra is None or rb is None:
                continue
            adj[ra].append(rb)
            adj[rb].append(ra)
        self._adj = adj

    def _ensure_face_data(self):
        """Face normals, face→rows, face adjacency, coplanar reference
        normal and seed faces. Normals come from the live bmesh, so call
        bm.normal_update() before invalidating this (done on bake)."""
        if self._face_data is not None:
            return
        row_of = self._row_of
        faces = [f for f in self.bm.faces if not f.hide]
        fidx = {f: i for i, f in enumerate(faces)}
        FN = np.array([f.normal[:] for f in faces], dtype=np.float64) if faces else np.zeros((0, 3))
        face_rows = [[row_of[v] for v in f.verts if v in row_of] for f in faces]
        face_adj = [[] for _ in faces]
        for e in self.bm.edges:
            lf = [fidx[f] for f in e.link_faces if f in fidx]
            for i in range(len(lf)):
                for j in range(i + 1, len(lf)):
                    face_adj[lf[i]].append(lf[j])
                    face_adj[lf[j]].append(lf[i])
        sel_faces = [fidx[f] for f in faces if f.select]
        if sel_faces:
            n_ref = FN[sel_faces].sum(axis=0)
        else:
            seeds = set()
            for e in self.bm.edges:
                if e.select:
                    for f in e.link_faces:
                        if f in fidx:
                            seeds.add(fidx[f])
            sel_faces = sorted(seeds)
            n_ref = FN[sel_faces].sum(axis=0) if sel_faces else np.zeros(3)
        self._face_data = (FN, face_rows, face_adj, n_ref, sel_faces)

    def _ensure_weights(self, context):
        if self._W is not None:
            return
        P0 = self._P0
        n = P0.shape[0]
        if self._ftype == "LINEAR":
            w = fc.weight_linear(P0, self._S, self._E)
        elif self._ftype == "RADIAL":
            w = fc.weight_radial(P0, self._C, self._r)
        elif self._ftype == "SCREEN":
            region = self._region
            rv3d = self._rv3d
            Pw = P0 @ np.asarray(self._mw.to_3x3()).T + np.asarray(self._mw.translation)
            P2, valid = fc.project_points(Pw, np.asarray(rv3d.perspective_matrix),
                                          region.width, region.height)
            # Brush-like: the disc follows the mouse while idle and is pinned
            # to the press point for the duration of a drag.
            pinned = self._drag is not None and self._screen_center is not None
            center = self._screen_center if pinned else self._mouse_xy
            w = fc.weight_screen(P2, np.asarray(center, dtype=np.float64), self._screen_px, valid)
        else:  # COPLANAR
            self._ensure_face_data()
            FN, face_rows, face_adj, n_ref, seed_faces = self._face_data
            wf = fc.weight_coplanar_faces(FN, n_ref, self._coplanar_angle)
            if self._connected:
                keep = fc.coplanar_grow(face_adj, wf, seed_faces)
                wf = np.where(keep, wf, 0.0)
            w = fc.vertex_weights_from_faces(face_rows, wf, n)
            affected = (w > 0.0) | self._sel_mask
        w = fc.shape_curve(self._shape, w)
        if self._invert:
            w = fc.apply_invert(w)
        if self._ftype == "COPLANAR":
            w[self._sel_mask] = 1.0
            w = np.where(affected, w, 0.0)
        else:
            w = np.where(self._sel_mask, w, 0.0)
            if self._connected:
                self._ensure_adjacency()
                seeds = np.nonzero(self._sel_mask)[0]
                if not self._has_selection:
                    seeds = seeds[:1]  # nothing selected: keep the first island only
                keep = fc.connected_mask(self._adj, seeds, n)
                w = np.where(keep, w, 0.0)
        self._W = w

    # ------------------------------------------------------------------
    # Mesh write-back
    # ------------------------------------------------------------------

    def _write(self, P, rows=None):
        if rows is None:
            w_rows = np.nonzero(self._W > 0.0)[0] if self._W is not None else np.arange(P.shape[0])
            dirty_rows = (np.fromiter(self._dirty, dtype=np.int64) if self._dirty
                          else np.empty(0, dtype=np.int64))
            rows = np.union1d(w_rows, dirty_rows)
            self._dirty.update(rows.tolist())
        verts = self._verts
        Pl = P[rows].tolist()
        for k, i in enumerate(rows.tolist()):
            verts[i].co = Pl[k]
        bmesh.update_edit_mesh(self.obj.data, loop_triangles=False, destructive=False)

    def _bake(self, P):
        self._P0 = P.copy()
        self._baked = True
        self.bm.normal_update()
        self._face_data = None
        self._W = None
        self._dirty = set()

    # ------------------------------------------------------------------
    # View helpers for subclasses
    # ------------------------------------------------------------------

    def _view_axis_object(self, rv3d):
        world = rv3d.view_rotation @ Vector((0.0, 0.0, 1.0))
        v = self._mw_inv3 @ world
        return v.normalized() if v.length_squared > 1e-18 else Vector((0.0, 0.0, 1.0))

    # ------------------------------------------------------------------
    # Basis (action centre + axes): pivot `_pivot` and orthonormal `_basis_R`
    # (columns = basis X/Y/Z in object space). Axis constraints and per-axis
    # scaling work in this basis; N cycles it.
    # ------------------------------------------------------------------

    def _set_basis(self, context, keep_pivot=False):
        """Recompute pivot + axes for the current basis mode. With
        `keep_pivot`, a pivot the user placed by dragging the origin gizmo is
        preserved and only the axes are refreshed."""
        moved_pivot = self._pivot.copy() if (keep_pivot and self._pivot_moved) else None
        mode = self._basis_mode
        self._pivot_moved = False
        mw_inv = self._mw.inverted()
        if mode == "CURSOR":
            cur = context.scene.cursor
            self._pivot = np.array((mw_inv @ cur.location)[:], dtype=np.float64)
            R = np.asarray(self._mw_inv3 @ cur.matrix.to_3x3(), dtype=np.float64)
            self._basis_R = self._orthonormal_columns(R)
        elif mode == "WORLD":
            self._pivot = np.array(mw_inv.translation[:], dtype=np.float64)
            self._basis_R = self._orthonormal_columns(np.asarray(self._mw_inv3, dtype=np.float64))
        elif mode == "NORMAL":
            pivot, normal, tangent = self._active_element_frame()
            self._pivot = pivot
            self._basis_R = fc.basis_from_normal(normal, tangent)
        else:  # LOCAL
            self._pivot = fc.bbox_center(self._P0[self._sel_mask])
            self._basis_R = np.eye(3)
        if moved_pivot is not None:
            self._pivot = moved_pivot
            self._pivot_moved = True

    @staticmethod
    def _orthonormal_columns(R):
        """Normalise the columns (object scale) and re-orthogonalise via SVD
        so a sheared/non-uniformly scaled object still yields a proper frame."""
        R = np.asarray(R, dtype=np.float64)
        u, _, vt = np.linalg.svd(R)
        Q = u @ vt
        if np.linalg.det(Q) < 0:
            Q[:, 2] *= -1.0
        return Q

    def _active_element_frame(self):
        """(pivot, normal, tangent) in object space from the active element
        (select_history), else the active face, else the selection: centre of
        the ORIGINAL positions and the element's normal."""
        elem = None
        try:
            elem = self.bm.select_history.active
        except (AttributeError, ReferenceError):
            elem = None
        if elem is None:
            try:
                elem = self.bm.faces.active
            except (AttributeError, ReferenceError):
                elem = None
        row_of = self._row_of

        def orig(v):
            r = row_of.get(v)
            return self._P0[r] if r is not None else np.array(v.co[:], dtype=np.float64)

        if isinstance(elem, bmesh.types.BMFace) and elem.is_valid:
            cos = np.array([orig(v) for v in elem.verts])
            e0 = elem.edges[0] if len(elem.edges) else None
            tangent = (orig(e0.verts[1]) - orig(e0.verts[0])) if e0 is not None else None
            return cos.mean(axis=0), np.array(elem.normal[:], dtype=np.float64), tangent
        if isinstance(elem, bmesh.types.BMEdge) and elem.is_valid:
            a, b = elem.verts
            pa, pb = orig(a), orig(b)
            n = np.array((a.normal + b.normal)[:], dtype=np.float64)
            return (pa + pb) * 0.5, n, pb - pa
        if isinstance(elem, bmesh.types.BMVert) and elem.is_valid:
            return orig(elem), np.array(elem.normal[:], dtype=np.float64), None
        # Fallback: selection centre + mean normal of selected faces (or verts).
        sel_faces = [f for f in self.bm.faces if f.select]
        if sel_faces:
            n = np.sum([np.array(f.normal[:]) for f in sel_faces], axis=0)
        else:
            n = np.sum([np.array(self._verts[i].normal[:]) for i in self._sel_rows], axis=0)
        return fc.bbox_center(self._P0[self._sel_mask]), np.asarray(n, dtype=np.float64), None

    def _cycle_basis(self, context):
        i = BASIS_MODES.index(self._basis_mode)
        self._basis_mode = BASIS_MODES[(i + 1) % len(BASIS_MODES)]
        self._set_basis(context)

    def _constrain_object_vector(self, d, letters):
        """Project an object-space (3,) vector onto the allowed basis axes."""
        if not letters:
            return np.asarray(d, dtype=np.float64)
        R = self._basis_R
        db = R.T @ np.asarray(d, dtype=np.float64)
        return R @ (db * self._axis_mask(letters))

    # Axis constraints are strings of allowed basis-axis letters: "X" (one
    # axis) or "YZ" (a plane, Blender's Shift+X). None = unconstrained.

    @staticmethod
    def _toggle_axis(current, key, shift):
        """X/Y/Z press → that axis; Shift+X/Y/Z → the plane of the other two.
        Pressing the same combination again clears the constraint."""
        new = "".join(a for a in AXIS_KEYS if a != key) if shift else key
        return None if current == new else new

    @staticmethod
    def _axis_mask(letters):
        """(3,) 1/0 mask of the allowed axes; all ones when unconstrained."""
        if not letters:
            return np.ones(3, dtype=np.float64)
        return np.array([1.0 if a in letters else 0.0 for a in AXIS_KEYS], dtype=np.float64)

    def _basis_axis_vector(self, letter):
        """Object-space unit vector of one basis axis."""
        return Vector(self._basis_R[:, AXIS_KEYS.index(letter)].tolist())

    def _axis_vector_object(self):
        """Single object-space axis for the current constraint: the basis
        axis itself, or for a plane the axis perpendicular to it (rotation
        in the YZ plane is rotation about X). None when unconstrained."""
        if self._axis is None:
            return None
        letters = self._axis if len(self._axis) == 1 else "".join(
            a for a in AXIS_KEYS if a not in self._axis)
        return self._basis_axis_vector(letters)

    def _pivot_world(self):
        return self._mw @ Vector(self._pivot.tolist())

    def _world_per_px(self, context, at_world):
        """World-space length of one screen pixel at `at_world` (view-right
        direction). Falls back to a mesh-relative size when the point does
        not project."""
        region = context.region
        rv3d = context.region_data
        right = rv3d.view_rotation @ Vector((1.0, 0.0, 0.0))
        a = view3d_utils.location_3d_to_region_2d(region, rv3d, at_world)
        b = view3d_utils.location_3d_to_region_2d(region, rv3d, at_world + right)
        if a is None or b is None or (b - a).length < 1e-6:
            diag = float(np.linalg.norm(self._P0.max(axis=0) - self._P0.min(axis=0)))
            return max(diag, 1.0) * 0.002
        return 1.0 / (b - a).length

    def _pivot_region_2d(self, context):
        return view3d_utils.location_3d_to_region_2d(
            context.region, context.region_data, self._pivot_world())

    def _mouse_to_plane_object(self, context, xy, depth_world=None):
        """Region px → point on the view plane through `depth_world`
        (default: the pivot), returned in object space."""
        if depth_world is None:
            depth_world = self._pivot_world()
        p = view3d_utils.region_2d_to_location_3d(
            context.region, context.region_data, xy, depth_world)
        if p is None:
            return None
        return self._mw.inverted() @ p

    @staticmethod
    def _snap(value, step):
        return round(value / step) * step

    # ------------------------------------------------------------------
    # Modal
    # ------------------------------------------------------------------

    def modal(self, context, event):
        try:
            return self._modal(context, event)
        except ReferenceError:
            self._finish(context)
            self.report({"WARNING"}, f"{self.tool_label}: bmesh data became invalid — cancelled")
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
            if self._help.handle_drag_event(context, event, theme_prefs):
                return {"RUNNING_MODAL"}
            if self._hud.handle_drag_event(context, event, theme_prefs):
                return {"RUNNING_MODAL"}
            if self._help.handle_toggle_event(event, theme_prefs):
                return {"RUNNING_MODAL"}
            if self._hud.handle_param_toggle_event(event, theme_prefs):
                return {"RUNNING_MODAL"}

        et = event.type
        if et in {"WHEELUPMOUSE", "WHEELDOWNMOUSE"}:
            if event.shift:
                self._scalar_step(1 if et == "WHEELUPMOUSE" else -1, event.ctrl)
                self._reapply(context, event)
                context.workspace.status_text_set(self._status_text())
                return {"RUNNING_MODAL"}
            return {"PASS_THROUGH"}
        if et == "MIDDLEMOUSE" or et.startswith(("NDOF", "TRACKPAD")):
            return {"PASS_THROUGH"}

        if et == "MOUSEMOVE":
            self._mouse_xy = (event.mouse_region_x, event.mouse_region_y)
            if self._handle_drag is not None:
                self._snap_on = bool(event.ctrl)
                self._drag_handle(context)
                self._reapply(context, event)
            elif self._drag is not None:
                self._live_apply(context, event)
            elif self._ftype == "SCREEN":
                self._W = None   # disc follows the mouse while idle
            return {"RUNNING_MODAL"}

        if et == "LEFTMOUSE":
            if event.value == "PRESS":
                self._mouse_xy = (event.mouse_region_x, event.mouse_region_y)
                self._update_hover()
                kind = self._hover_kind()
                if kind is not None and kind.startswith("G"):
                    # Gizmo stud (axis tip / ring): start the transform drag
                    # constrained to that basis axis. The constraint stays set
                    # so the live result keeps re-applying about it.
                    self._axis = kind[1]
                elif kind is not None:
                    self._handle_drag = kind
                    self._handle_axis = None
                    cur = {"S": self._S, "E": self._E, "C": self._C, "P": self._pivot}.get(kind)
                    self._handle_start = cur.copy() if cur is not None else None
                    self._snap_on = bool(event.ctrl)
                    return {"RUNNING_MODAL"}
                self._commit_live(context)
                if self._ftype == "SCREEN":
                    self._screen_center = self._mouse_xy
                    self._W = None
                self._ensure_weights(context)
                self._drag = {"start": self._mouse_xy}
                self._current_amount = None
                self._drag_begin(context, event)
                return {"RUNNING_MODAL"}
            if event.value == "RELEASE":
                if self._handle_drag is not None:
                    self._handle_drag = None
                    self._handle_axis = None
                    self._handle_start = None
                    self._snap_on = False
                    self._snap_pt = None
                    return {"RUNNING_MODAL"}
                if self._drag is not None:
                    if self._ftype == "SCREEN":
                        # Soft Drag is anchored to the press point; once the
                        # disc follows the mouse again the result cannot be
                        # re-evaluated in place, so commit on release.
                        self._commit_live(context)
                    # Modo semantics: the drag stays LIVE after release —
                    # `_current_amount` is kept and re-applied whenever the
                    # falloff changes; it is committed into `_P0` only when
                    # the next drag starts or on confirm (`_commit_live`).
                    self._drag = None
                    context.workspace.status_text_set(self._status_text())
                return {"RUNNING_MODAL"}

        if self._handle_drag is not None:
            # Handle-drag modifiers: Ctrl = snap to the original selection,
            # X/Y/Z = lock the handle to an object axis. Both re-run the
            # handle placement immediately so the falloff updates in place.
            if et in {"LEFT_CTRL", "RIGHT_CTRL"}:
                self._snap_on = event.value == "PRESS"
                self._drag_handle(context)
                self._reapply(context, event)
                return {"RUNNING_MODAL"}
            if et in AXIS_KEYS and event.value == "PRESS":
                self._handle_axis = self._toggle_axis(self._handle_axis, et, event.shift)
                self._drag_handle(context)
                self._reapply(context, event)
                return {"RUNNING_MODAL"}

        if event.value != "PRESS":
            return {"RUNNING_MODAL"}

        if et in DIGIT_TYPES:
            self.input_str += DIGIT_TYPES[et]
            self._apply_typed(context)
        elif et in {"PERIOD", "NUMPAD_PERIOD"}:
            if "." not in self.input_str:
                self.input_str += "."
            self._apply_typed(context)
        elif et in {"MINUS", "NUMPAD_MINUS"}:
            self.input_str = self.input_str[1:] if self.input_str.startswith("-") else "-" + self.input_str
            self._apply_typed(context)
        elif et == "BACK_SPACE":
            self.input_str = self.input_str[:-1]
            self._apply_typed(context)
        elif et in TYPE_KEYS and self._drag is None:
            self._set_type(context, TYPE_KEYS[et])
        elif et == "E":
            self._connected = not self._connected
            self._W = None
        elif et == "F":
            i = fc.SHAPES.index(self._shape)
            self._shape = fc.SHAPES[(i + 1) % len(fc.SHAPES)]
            self._W = None
        elif et == "I":
            self._invert = not self._invert
            self._W = None
        elif et == "A":
            self._autofit()
        elif et == "V":
            self._preview = not self._preview
        elif et in AXIS_KEYS:
            self._axis = self._toggle_axis(self._axis, et, event.shift)
        elif et == "N":
            self._cycle_basis(context)
        elif et in {"RET", "NUMPAD_ENTER", "SPACE"}:
            return self._confirm(context)
        elif et in {"ESC", "RIGHTMOUSE"}:
            return self._cancel_all(context)
        self._reapply(context, event)
        context.workspace.status_text_set(self._status_text())
        return {"RUNNING_MODAL"}

    def _typed_amount(self):
        """The amount the typed number stands for, or None when the input
        buffer is empty or not (yet) a number ("-", ".", "")."""
        if not self.input_str:
            return None
        try:
            return self._amount_from_number(float(self.input_str))
        except ValueError:
            return None

    def _apply_typed(self, context):
        """Typed numbers apply live (Blender-style): the buffer replaces the
        current amount as soon as it parses. Written by the caller's
        `_reapply` at the end of the key handler."""
        amount = self._typed_amount()
        if amount is not None:
            self._current_amount = amount

    def _live_apply(self, context, event):
        # A parsable typed value overrides the mouse while dragging.
        amount = self._typed_amount()
        if amount is None:
            amount = self._drag_amount(context, event)
        self._current_amount = amount
        self._write(self._apply_amount(amount))

    def _reapply(self, context, event=None):
        """Re-evaluate the current operation after a falloff/axis change:
        mid-drag from the mouse, otherwise from the live (released) amount."""
        if self._drag is not None and event is not None:
            self._ensure_weights(context)
            self._live_apply(context, event)
        elif self._current_amount is not None:
            self._ensure_weights(context)
            self._write(self._apply_amount(self._current_amount))

    def _commit_live(self, context):
        """Bake the live (released) operation into the originals so the next
        operation starts from it."""
        if self._current_amount is None:
            return
        self._ensure_weights(context)
        self._bake(self._apply_amount(self._current_amount))
        self._current_amount = None
        # The committed geometry is the new original: Local / Normal bases
        # follow the moved selection or active element — unless the user
        # placed the pivot by hand, which only N resets.
        self._set_basis(context, keep_pivot=True)

    def _confirm(self, context):
        # A typed value has already been applied live via `_apply_typed`;
        # `_commit_live` bakes whatever the current amount is.
        self._apply_typed(context)
        self._commit_live(context)
        self.input_str = ""
        self._drag = None
        if not self._baked:
            self._save_props(context)
            self._finish(context)
            return {"CANCELLED"}
        self.bm.normal_update()
        bmesh.update_edit_mesh(self.obj.data, loop_triangles=False, destructive=False)
        self._save_props(context)
        bpy.ops.ed.undo_push(message=self.undo_message)
        self._finish(context)
        return {"FINISHED"}

    def _cancel_all(self, context):
        if self._baked or self._drag is not None or self._current_amount is not None:
            self._W = None
            self._write(self._P_invoke, rows=np.arange(self._P_invoke.shape[0]))
            self.bm.normal_update()
            bmesh.update_edit_mesh(self.obj.data, loop_triangles=False, destructive=False)
        self._save_props(context)
        self._finish(context)
        return {"CANCELLED"}

    def _save_props(self, context):
        props = context.scene.IOPS
        props.falloff_type = self._ftype
        props.falloff_shape = self._shape
        props.falloff_invert = self._invert
        props.falloff_connected = self._connected
        props.falloff_preview = self._preview
        props.falloff_screen_radius_px = int(round(self._screen_px))
        props.falloff_coplanar_angle = self._coplanar_angle
        props.falloff_basis = self._basis_mode

    # ------------------------------------------------------------------
    # Handles
    # ------------------------------------------------------------------

    def _update_hover(self):
        """Nearest hotspot within HANDLE_PX. A hotspot has either one
        `region_pt` (handles, tips) or a `region_pts` sample list (rings)."""
        mx, my = self._mouse_xy
        best = (None, HANDLE_PX * HANDLE_PX)
        for i, h in enumerate(self._hotspots):
            pts = h.get("region_pts")
            if pts is None:
                rp = h.get("region_pt")
                pts = [rp] if rp is not None else []
            for rp in pts:
                dx, dy = rp[0] - mx, rp[1] - my
                d2 = dx * dx + dy * dy
                if d2 < best[1]:
                    best = (i, d2)
        self._hover_idx = best[0]

    def _hover_kind(self):
        if self._hover_idx is None or self._hover_idx >= len(self._hotspots):
            return None
        return self._hotspots[self._hover_idx]["kind"]

    def _snap_target(self, context):
        """Nearest vertex of the ORIGINAL selection (pre-operation `_P0`
        positions) to the mouse, in screen space within SNAP_PX. Returns an
        object-space (3,) array or None."""
        rows = self._sel_rows
        if rows is None or rows.size == 0:
            return None
        mw = self._mw
        Pw = self._P0[rows] @ np.asarray(mw.to_3x3()).T + np.asarray(mw.translation)
        region = self._region
        P2, valid = fc.project_points(Pw, np.asarray(self._rv3d.perspective_matrix),
                                      region.width, region.height)
        d = np.linalg.norm(P2 - np.asarray(self._mouse_xy, dtype=np.float64), axis=1)
        d = np.where(valid, d, np.inf)
        i = int(np.argmin(d))
        if not np.isfinite(d[i]) or d[i] > SNAP_PX:
            return None
        return self._P0[rows[i]].copy()

    def _handle_target_point(self, context, depth_local):
        """Where the dragged handle wants to be: the Ctrl snap target when
        one is under the cursor, else the mouse on the view plane through
        `depth_local`. Object space, or None when the mouse cannot be mapped."""
        self._snap_pt = self._snap_target(context) if self._snap_on else None
        if self._snap_pt is not None:
            return self._snap_pt.copy()
        depth = self._mw @ Vector(depth_local.tolist())
        p = self._mouse_to_plane_object(context, self._mouse_xy, depth)
        if p is None:
            return None
        return np.array(p[:], dtype=np.float64)

    def _drag_handle(self, context):
        kind = self._handle_drag
        if kind is None:
            return
        if kind == "R":
            p = self._handle_target_point(context, self._C)
            if p is None:
                return
            self._r = max(1e-4, float(np.linalg.norm(p - self._C)))
        else:
            cur = {"S": self._S, "E": self._E, "C": self._C, "P": self._pivot}[kind]
            p = self._handle_target_point(context, cur)
            if p is None:
                return
            if self._handle_axis is not None and self._handle_start is not None:
                # Axis → slide along it; plane (Shift+axis) → stay in the plane
                # (both in the current basis).
                p = self._handle_start + self._constrain_object_vector(
                    p - self._handle_start, self._handle_axis)
            if kind == "P":
                # Origin gizmo: moves the pivot only; weights are unaffected,
                # the live operation re-applies about the new origin.
                self._pivot = p
                self._pivot_moved = True
                return
            if kind == "S":
                self._S = p
            elif kind == "E":
                self._E = p
            else:
                self._C = p
        self._W = None

    def _ring_handle_point_object(self, rv3d):
        """Point on the radial ring at the view's right, in object space."""
        right_w = rv3d.view_rotation @ Vector((1.0, 0.0, 0.0))
        right_o = (self._mw_inv3 @ right_w)
        if right_o.length_squared < 1e-18:
            right_o = Vector((1.0, 0.0, 0.0))
        right_o.normalize()
        return Vector(self._C.tolist()) + right_o * self._r

    # ------------------------------------------------------------------
    # HUD
    # ------------------------------------------------------------------

    def _build_hud(self, context):
        self._hud = HUDOverlay(f"mesh_falloff_{self.tool_label.lower()}")
        self._hud.title = f"Falloff {self.tool_label}"
        self._hud.bind_region(context.region)
        self._items = {
            "LINEAR": HUDItem("Linear", "L", always_show=True),
            "RADIAL": HUDItem("Radial", "R", always_show=True),
            "SCREEN": HUDItem("Screen", "S", always_show=True),
            "COPLANAR": HUDItem("Coplanar", "C", always_show=True),
            "E": HUDItem("Element (connected only)", "E", always_show=True),
            "I": HUDItem("Invert", "I", always_show=True),
            "V": HUDItem("Show weights", "V", always_show=True),
        }
        self._hud.add_section(HUDSection("Falloff", [
            self._items["LINEAR"], self._items["RADIAL"], self._items["SCREEN"],
            self._items["COPLANAR"], self._items["E"], self._items["I"],
            self._items["V"],
        ]))
        self._hud.add_param(HUDParam("Shape", lambda: self._shape.replace("_", " ").title(), "str"))
        self._hud.add_param(HUDParam("Radius", lambda: self._r, "float", fmt="{:.4f}",
                                     visible_getter=lambda: self._ftype == "RADIAL"))
        self._hud.add_param(HUDParam("Length", lambda: float(np.linalg.norm(self._E - self._S)), "float",
                                     fmt="{:.4f}", visible_getter=lambda: self._ftype == "LINEAR"))
        self._hud.add_param(HUDParam("Radius px", lambda: self._screen_px, "int",
                                     visible_getter=lambda: self._ftype == "SCREEN"))
        self._hud.add_param(HUDParam("Angle", lambda: math.degrees(self._coplanar_angle), "float",
                                     fmt="{:.1f}°", visible_getter=lambda: self._ftype == "COPLANAR"))
        self._hud.add_param(HUDParam(
            "Basis",
            lambda: BASIS_LABELS[self._basis_mode] + (" (moved)" if self._pivot_moved else ""),
            "str"))
        self._hud.add_param(HUDParam("Axis", lambda: self._axis or "—", "str"))
        self._hud.add_param(HUDParam(self.amount_label, self._hud_amount, "str"))
        self._hud.add_param(HUDParam("Typing", lambda: self.input_str, "str",
                                     visible_getter=lambda: bool(self.input_str)))

        self._help = HelpOverlay(f"mesh_falloff_{self.tool_label.lower()}")
        self._help.add_section(HUDSection(f"Falloff {self.tool_label}", [
            HUDItem("Drag = transform, drag handle = edit falloff", "LMB", ItemState.ON, always_show=True),
            HUDItem("Falloff type", "L / R / S / C", ItemState.ON, always_show=True),
            HUDItem("Element: connected only", "E", ItemState.ON, always_show=True),
            HUDItem("Cycle shape", "F", ItemState.ON, always_show=True),
            HUDItem("Invert", "I", ItemState.ON, always_show=True),
            HUDItem("Auto-size to selection", "A", ItemState.ON, always_show=True),
            HUDItem("Show weights", "V", ItemState.ON, always_show=True),
            HUDItem("Axis constraint (Shift = plane)", "X / Y / Z", ItemState.ON, always_show=True),
            HUDItem("Basis: Local / Cursor / World / Normal", "N", ItemState.ON, always_show=True),
            HUDItem("Drag origin gizmo = move pivot (Ctrl snap, X/Y/Z lock)", "LMB", ItemState.ON, always_show=True),
            HUDItem("Drag gizmo arrow / ring / square = transform on that axis", "LMB", ItemState.ON, always_show=True),
            HUDItem("Handle drag: snap to original selection", "Ctrl", ItemState.ON, always_show=True),
            HUDItem("Handle drag: axis lock (Shift = plane)", "X / Y / Z", ItemState.ON, always_show=True),
            HUDItem("Falloff size (fine: +Ctrl)", "Shift+Wheel", ItemState.ON, always_show=True),
            HUDItem("Precise / Snap", "Shift / Ctrl", ItemState.ON, always_show=True),
            HUDItem("Type amount", "0-9 . -", ItemState.ON, always_show=True),
            HUDItem("Confirm", "Enter / Space", ItemState.ON, always_show=True),
            HUDItem("Cancel", "Esc / RMB", ItemState.ON, always_show=True),
            HUDItem("Help legend", "H", ItemState.ON, always_show=True),
            HUDItem("Toggle HUD params", "/", ItemState.ON, always_show=True),
        ]))
        self._help.bind_region(context.region)

    def _hud_amount(self):
        if self._current_amount is None:
            return "—"
        return self._amount_text(self._current_amount)

    def _sync_hud_states(self):
        for t in fc.FALLOFF_TYPES:
            it = self._items[t]
            if t == "COPLANAR" and not self._coplanar_ok:
                it.state = ItemState.DISABLED
            else:
                it.state = ItemState.ON if self._ftype == t else ItemState.OFF
        self._items["E"].state = ItemState.ON if self._connected else ItemState.OFF
        self._items["I"].state = ItemState.ON if self._invert else ItemState.OFF
        self._items["V"].state = ItemState.ON if self._preview else ItemState.OFF

    def _status_text(self):
        typed = f" | typing: {self.input_str}" if self.input_str else ""
        return (f"Falloff {self.tool_label}: {TYPE_LABELS[self._ftype]} / "
                f"{self._shape.replace('_', ' ').title()}{' / inverted' if self._invert else ''}"
                f"{' / connected' if self._connected else ''} / {BASIS_LABELS[self._basis_mode]}{typed} | "
                "[LMB drag] transform | [L/R/S/C] type | [E] element | [F] shape | "
                "[I] invert | [A] fit | [V] weights | [N] basis | [Shift+Wheel] size | "
                "[Enter] confirm | [Esc] cancel")

    # ------------------------------------------------------------------
    # Drawing
    # ------------------------------------------------------------------

    def _guard_draw(self):
        try:
            _ = self.obj.matrix_world
            return True
        except (ReferenceError, AttributeError):
            for attr in ("_handle", "_handle_3d"):
                h = getattr(self, attr, None)
                if h is not None:
                    try:
                        safe_handler_remove(h, bpy.types.SpaceView3D, "WINDOW")
                    except (ValueError, RuntimeError, ReferenceError):
                        pass
                    setattr(self, attr, None)
            return False

    def _draw_view(self, context):
        rv3d = context.region_data
        if rv3d is None or not self._guard_draw():
            return
        if rv3d.as_pointer() != self._rv3d_ptr:
            return
        if self._P0 is None:
            return
        theme = get_theme(context)
        mw = self._mw
        with draw_scope(blend="ALPHA", depth="NONE"):
            # Ghost of the original selection while the mesh is displaced —
            # this is what Ctrl handle-snapping targets.
            if self._ghost_pairs and (self._current_amount is not None or self._drag is not None):
                idx = np.asarray(self._ghost_pairs, dtype=np.int64).ravel()
                Pw = self._P0[idx] @ np.asarray(mw.to_3x3()).T + np.asarray(mw.translation)
                draw_prim.edges_3d(Pw.tolist(), role=Role.GHOST_EDGE, context=context, theme=theme)
            # Axis-lock guide through the handle's drag-start position.
            if self._handle_drag is not None and self._handle_axis is not None \
                    and self._handle_start is not None:
                start_w = mw @ Vector(self._handle_start.tolist())
                ext = max(1.0, float(np.linalg.norm(self._P0.max(axis=0) - self._P0.min(axis=0)))) * 10.0
                for letter in self._handle_axis:      # one line per allowed axis
                    dir_w = (mw.to_3x3() @ self._basis_axis_vector(letter))
                    if dir_w.length_squared > 1e-18:
                        dir_w.normalize()
                        draw_prim.line(start_w - dir_w * ext, start_w + dir_w * ext,
                                       color=axis_color(letter), context=context, theme=theme)
            if self._snap_pt is not None:
                draw_prim.points([mw @ Vector(self._snap_pt.tolist())], role=Role.CLOSEST_POINT,
                                 context=context, theme=theme)
            if self._ftype == "LINEAR":
                S = mw @ Vector(self._S.tolist())
                E = mw @ Vector(self._E.tolist())
                draw_prim.line(S, E, role=Role.ACTIVE_LINE, context=context, theme=theme)
                d = (E - S)
                if d.length_squared > 1e-18:
                    tick = d.normalized().orthogonal().normalized() * (d.length * 0.08)
                    draw_prim.edges_3d([S - tick, S + tick, E - tick, E + tick],
                                       role=Role.LINE, context=context, theme=theme)
            elif self._ftype == "RADIAL":
                C = mw @ Vector(self._C.tolist())
                for axis in (Vector((1, 0, 0)), Vector((0, 1, 0)), Vector((0, 0, 1))):
                    n = (mw.to_3x3() @ axis)
                    draw_prim.ring_3d(C, n, self._r * mw.to_scale().x, role=Role.PREVIEW_LINE,
                                      context=context, theme=theme)
            # Origin gizmo (constant screen size): shape follows the tool —
            # arrows (Move), rings (Rotate), squares (Scale). The centre disc
            # is a drag handle (hotspot "P" in _draw_pixel).
            self._draw_gizmo(context, theme, mw)
            if self._preview:
                self._ensure_weights(context)
                W = self._W
                rows = np.nonzero(W > 0.0)[0]
                if rows.size:
                    Pw = self._P0[rows] @ np.asarray(mw.to_3x3()).T + np.asarray(mw.translation)
                    lo = np.asarray(PREVIEW_LOW)
                    hi = np.asarray(PREVIEW_HIGH)
                    cols = lo + (hi - lo) * W[rows][:, None]
                    draw_prim.points_colored(Pw.tolist(), cols.tolist(),
                                             size=theme.point_size("default"))

    def _draw_gizmo(self, context, theme, mw):
        rv3d = context.region_data
        pw = self._pivot_world()
        unit = self._world_per_px(context, pw)
        L = unit * GIZMO_PX
        view_dir = (rv3d.view_rotation @ Vector((0.0, 0.0, 1.0))).normalized()
        active = self._axis_vector_object() if self.gizmo_kind == "ROTATE" else None
        constrained = set(self._axis or "")
        hovered = self._hover_kind()
        hovered_letter = hovered[1] if (hovered and hovered.startswith("G")) else None

        def axis_dir(letter):
            d = mw.to_3x3() @ self._basis_axis_vector(letter)
            return d.normalized() if d.length_squared > 1e-18 else None

        def width_for(letter):
            # Wider when this axis is the active constraint or under the mouse.
            return "active" if (letter in constrained or letter == hovered_letter) else "default"

        if self.gizmo_kind == "ROTATE":
            # One ring per basis axis (normal = axis); the current rotation
            # axis ring is drawn wider. Unconstrained → a view-facing ring.
            for letter in AXIS_KEYS:
                d = axis_dir(letter)
                if d is None:
                    continue
                is_active = active is not None and abs((mw.to_3x3() @ active).normalized().dot(d)) > 0.999
                draw_prim.ring_3d(pw, d, L, color=axis_color(letter),
                                  width="active" if (is_active or letter == hovered_letter) else "default",
                                  context=context, theme=theme)
            if active is None:
                draw_prim.ring_3d(pw, view_dir, L * 1.15, role=Role.ACTIVE_LINE,
                                  context=context, theme=theme)
        else:
            for letter in AXIS_KEYS:
                d = axis_dir(letter)
                if d is None:
                    continue
                tip = pw + d * L
                col = axis_color(letter)
                draw_prim.line(pw, tip, color=col, width=width_for(letter),
                               context=context, theme=theme)
                # Tip glyph in the screen plane: chevron for Move, square for Scale.
                side = d.cross(view_dir)
                if side.length_squared < 1e-12:
                    side = d.orthogonal()
                side.normalize()
                g = unit * 5.0
                if self.gizmo_kind == "MOVE":
                    base = tip - d * (g * 2.0)
                    draw_prim.polyline([base + side * g, tip, base - side * g],
                                       color=col, width=width_for(letter),
                                       context=context, theme=theme)
                else:  # SCALE
                    up = d.cross(side).normalized()
                    sq = [tip + (side + up) * g, tip + (side - up) * g,
                          tip + (-side - up) * g, tip + (-side + up) * g]
                    sq.append(sq[0])
                    draw_prim.polyline(sq, color=col, width=width_for(letter),
                                       context=context, theme=theme)
        draw_prim.points([pw], role=Role.PIVOT, context=context, theme=theme)

    def _draw_pixel(self, context):
        region = context.region
        rv3d = context.region_data
        if rv3d is None or not self._guard_draw():
            return
        if rv3d.as_pointer() != self._rv3d_ptr:
            return
        if self._P0 is None:
            return
        theme = get_theme(context)
        mw = self._mw

        def s2d(co_obj):
            return view3d_utils.location_3d_to_region_2d(region, rv3d, mw @ Vector(co_obj.tolist()))

        self._hotspots = []
        if self._ftype == "LINEAR":
            for kind, co in (("S", self._S), ("E", self._E)):
                p = s2d(co)
                if p is not None:
                    self._hotspots.append({"kind": kind, "region_pt": (p.x, p.y)})
        elif self._ftype == "RADIAL":
            p = s2d(self._C)
            if p is not None:
                self._hotspots.append({"kind": "C", "region_pt": (p.x, p.y)})
            rp = view3d_utils.location_3d_to_region_2d(
                region, rv3d, mw @ self._ring_handle_point_object(rv3d))
            if rp is not None:
                self._hotspots.append({"kind": "R", "region_pt": (rp.x, rp.y)})
        # Origin gizmo centre — always draggable, after the falloff handles so
        # they win ties.
        pp = s2d(self._pivot)
        if pp is not None:
            self._hotspots.append({"kind": "P", "region_pt": (pp.x, pp.y)})
        # Gizmo studs ("GX"/"GY"/"GZ"): axis tips for Move/Scale, ring samples
        # for Rotate. Clicking one starts an axis-constrained transform drag.
        pw = self._pivot_world()
        L = self._world_per_px(context, pw) * GIZMO_PX
        for letter in AXIS_KEYS:
            d = mw.to_3x3() @ self._basis_axis_vector(letter)
            if d.length_squared < 1e-18:
                continue
            d.normalize()
            if self.gizmo_kind == "ROTATE":
                u = d.orthogonal().normalized()
                v = d.cross(u)
                pts = []
                for i in range(48):
                    a = i * (2.0 * math.pi / 48)
                    q = view3d_utils.location_3d_to_region_2d(
                        region, rv3d, pw + (u * math.cos(a) + v * math.sin(a)) * L)
                    if q is not None:
                        pts.append((q.x, q.y))
                if pts:
                    self._hotspots.append({"kind": "G" + letter, "region_pts": pts})
            else:
                q = view3d_utils.location_3d_to_region_2d(region, rv3d, pw + d * L)
                if q is not None:
                    self._hotspots.append({"kind": "G" + letter, "region_pt": (q.x, q.y)})
        if self._handle_drag is None:
            self._update_hover()

        with draw_scope(blend="ALPHA"):
            if self._ftype == "SCREEN":
                pinned = self._drag is not None and self._screen_center is not None
                c = self._screen_center if pinned else self._mouse_xy
                pts = [(c[0] + self._screen_px * math.cos(a), c[1] + self._screen_px * math.sin(a))
                       for a in np.linspace(0.0, 2.0 * math.pi, 65)]
                draw_prim.polyline(pts, role=Role.PREVIEW_LINE, context=context, theme=theme)
            # The pivot ("P") and the gizmo studs ("G*") are drawn as the origin
            # gizmo in POST_VIEW; only falloff handles get the handle dot here.
            pts = [h["region_pt"] for h in self._hotspots
                   if h["kind"] not in {"P"} and not h["kind"].startswith("G") and "region_pt" in h]
            if pts:
                draw_prim.points(pts, role=Role.HANDLE, context=context, theme=theme)
            hk = self._hover_kind()
            if hk is not None and not hk.startswith("G"):
                draw_prim.points([self._hotspots[self._hover_idx]["region_pt"]],
                                 role=Role.HANDLE_HOVER, context=context, theme=theme)

        self._sync_hud_states()
        with hud_text.isolated(theme):
            self._help.draw(context, self._last_event)
            self._hud.draw(context, self._last_event)
