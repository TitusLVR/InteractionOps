"""Field Edge Slide and Field Offset Edge Slide: edge loops slide along their
rails, each vertex by `factor` times its field weight. Offset Edge Slide first
adds a loop on each side of the selected one (`bmesh.ops.offset_edgeloops`)
and slides those.

Rails are found topologically: from a loop edge, walk around each of its
vertices through the faces on one side until the next selected edge; the
unselected edges passed on the way are that side's rail candidates (one for a
vertex of valence 4, several at loop ends and poles, where `pick_rail` takes
the one pointing most into the side). Side A of the first edge is carried
along the loop through the walk, so one side stays one side.

The maths is `falloff_core.apply_edge_slide`; stack snapshot, redo, modal
keys and cleanup come from `FalloffOpMixin`.
"""
from __future__ import annotations

import bmesh
import bpy
import numpy as np
from bpy.props import BoolProperty, FloatProperty
from bpy_extras import view3d_utils
from mathutils import Vector

from ...utils import falloff_core as fc
from .base import PRECISE_FACTOR, FalloffOpMixin, snap

_MAX_FAN = 64


def _fan(v, face, edge, selected):
    """Walk around `v` from `edge` through `face` and on, until a selected
    edge. Returns (passed unselected edges, the selected edge reached or None,
    the face before it). None also when the walk hits a boundary, a
    non-manifold edge, or comes back to `edge` (a loop end)."""
    passed = []
    cur = edge
    for _ in range(_MAX_FAN):
        other = None
        for loop in face.loops:
            if loop.vert is v:
                a, b = loop.edge, loop.link_loop_prev.edge
                other = b if a is cur else a
                break
        if other is None:
            return passed, None, None
        if other in selected:
            return passed, (None if other is edge else other), face
        passed.append(other)
        nxt = [f for f in other.link_faces if f is not face]
        if len(nxt) != 1:
            return passed, None, None
        face, cur = nxt[0], other
    return passed, None, None


def _side_vec(v, face, edge):
    """Direction from `v` into `face`, perpendicular to `edge`."""
    c = face.calc_center_median() - v.co
    d = (edge.other_vert(v).co - v.co)
    if d.length > 1e-12:
        d.normalize()
        c = c - d * c.dot(d)
    return c


def _other_face(edge, face):
    fs = [f for f in edge.link_faces if f is not face]
    return fs[0] if len(fs) == 1 else None


def rails_for_entry(entry):
    """{vert: (rail end A or None, rail end B or None)} for the domain verts
    of one object that lie on selected edges; local coordinates."""
    in_domain = set(entry.verts)
    selected = {e for e in entry.bm.edges
                if e.select and not e.hide
                and e.verts[0] in in_domain and e.verts[1] in in_domain}
    cand = {"A": {}, "B": {}}
    seen = set()
    for start in selected:
        if start in seen:
            continue
        faces = list(start.link_faces)
        seen.add(start)
        queue = [(start, faces[0] if faces else None)]
        while queue:
            ed, fa = queue.pop()
            fb = _other_face(ed, fa) if fa is not None else None
            for v in ed.verts:
                for side, f in (("A", fa), ("B", fb)):
                    if f is None:
                        continue
                    passed, end_e, end_f = _fan(v, f, ed, selected)
                    if v not in cand[side]:
                        ends = [e.other_vert(v) for e in passed]
                        if ends:
                            k = fc.pick_rail(v.co[:], _side_vec(v, f, ed)[:],
                                             [x.co[:] for x in ends])
                            cand[side][v] = ends[k].co.copy() if k >= 0 else None
                    if end_e is None or end_e in seen:
                        continue
                    seen.add(end_e)
                    # the face before the next selected edge is on this side
                    queue.append((end_e, end_f if side == "A" else _other_face(end_e, end_f)))
    return {v: (cand["A"].get(v), cand["B"].get(v))
            for v in set(cand["A"]) | set(cand["B"])}


def rail_targets(domain):
    """World-space rail ends TA, TB (N,3) for the domain rows; a row with no
    rail on a side gets its own position there (it stays)."""
    TA = domain.P.copy()
    TB = domain.P.copy()
    for e in domain.entries:
        rails = rails_for_entry(e)
        if not rails:
            continue
        m = e.mw
        for i, v in enumerate(e.verts):
            r = rails.get(v)
            if r is None:
                continue
            row = e.slice.start + i
            for T, end in ((TA, r[0]), (TB, r[1])):
                if end is not None:
                    T[row] = m[:3, :3] @ np.array(end[:]) + m[:3, 3]
    return TA, TB


class _SlideMixin(FalloffOpMixin):
    """Amount side shared by both slides. Subclasses supply `_targets(domain)`
    -> (TA, TB) world-space rail ends."""

    op_prefix = "Field"
    use_axis_keys = False
    free_axis_label = "Rail"
    snap_step = 0.1
    _transient = ("_TA", "_TB", "_d2", "_sign")

    factor: FloatProperty(name="Factor", soft_min=-1.0, soft_max=1.0, options={"SKIP_SAVE"},
                          description="Slide at full weight: 1 reaches the rail end; "
                                      "the sign picks the side")
    use_even: BoolProperty(name="Even", default=False,
                           description="Every vertex slides the same distance (times its weight)")
    use_clamp: BoolProperty(name="Clamp", default=True,
                            description="Do not slide past the end of a rail")

    def _targets(self, domain):
        raise NotImplementedError

    def _apply(self, P0, W, N):
        return fc.apply_edge_slide(P0, W, self._TA, self._TB, self.factor,
                                   even=self.use_even, clamp=self.use_clamp)

    def _resolve_unset(self, context, domain):
        self._TA, self._TB = self._targets(domain)

    def _begin(self, context, event):
        self._TA, self._TB = self._targets(self._domain)
        self.factor = 0.0
        self._d2, self._sign = None, 1.0
        P0 = self._P0
        for T, sign in ((self._TA, 1.0), (self._TB, -1.0)):
            has = np.linalg.norm(T - P0, axis=1) > 1e-9
            if not has.any():
                continue
            a = view3d_utils.location_3d_to_region_2d(
                self._region, self._rv3d, Vector(P0[has].mean(axis=0)))
            b = view3d_utils.location_3d_to_region_2d(
                self._region, self._rv3d, Vector(T[has].mean(axis=0)))
            if a is None or b is None or (b - a).length < 1.0:
                continue
            self._d2, self._sign = b - a, sign
            break
        if self._d2 is None:
            self.report({"WARNING"}, f"Field {self.op_label}: no edge loop with a rail "
                                     "in the selection")

    def _update_amount(self, context, event):
        typed = self._typed_value()
        if typed is not None:
            self.factor = typed
            return
        if self._d2 is None:
            return
        x, y = self._mouse_xy(event)
        sx, sy = self._start_xy
        d2 = self._d2
        f = ((x - sx) * d2.x + (y - sy) * d2.y) / d2.length_squared * self._sign
        if event.shift:
            f *= PRECISE_FACTOR
        if event.ctrl:
            f = snap(f, self.snap_step)
        self.factor = f

    def _extra_key(self, context, event):
        if event.type == "E":
            self.use_even = not self.use_even
        elif event.type == "C":
            self.use_clamp = not self.use_clamp
        else:
            return False
        return True

    def _amount_text(self):
        return (f"{self.factor:.4f} · Even {self.use_even} · Clamp {self.use_clamp}"
                " (E / C)")

    def draw_amount(self, layout):
        layout.prop(self, "factor")
        layout.prop(self, "use_even")
        layout.prop(self, "use_clamp")


class IOPS_OT_mesh_field_edge_slide(_SlideMixin, bpy.types.Operator):
    bl_idname = "iops.mesh_field_edge_slide"
    bl_label = "iOps Field Edge Slide"
    bl_description = ("Slide the selected edge loops along their rails, "
                      "each vertex by the falloff fields' weight")
    op_label = "Edge Slide"

    def _targets(self, domain):
        return rail_targets(domain)


# ------------------------------------------------------------------ offset

def offset_loops(obj):
    """Run `offset_edgeloops` on the selected edges of `obj` (edit mode).
    Each new vert starts on its source loop vertex and is joined to it and to
    the far end of the rail it split. Selects exactly the new loops and
    returns {new vert index: rail end (local)}; empty when no edge was
    selected. Keyed by index: BMVert wrappers are not stable across
    `from_edit_mesh` calls."""
    bm = bmesh.from_edit_mesh(obj.data)
    edges = [e for e in bm.edges if e.select and not e.hide]
    if not edges:
        return {}
    old = set(bm.verts)
    res = bmesh.ops.offset_edgeloops(bm, edges=edges, use_cap_endpoint=False)
    bm.verts.index_update()
    rails = {}
    for v in bm.verts:
        if v in old:
            continue
        far = [e.other_vert(v) for e in v.link_edges
               if e.other_vert(v) in old and (e.other_vert(v).co - v.co).length > 1e-9]
        if far:
            rails[v.index] = far[0].co.copy()
    for seq in (bm.verts, bm.edges, bm.faces):
        for x in seq:
            x.select = False
    for v in bm.verts:
        if v.index in rails:
            v.select = True
    for e in res["edges"]:
        if e.verts[0].index in rails and e.verts[1].index in rails:
            e.select = True
    bm.select_flush_mode()
    bmesh.update_edit_mesh(obj.data)
    return rails


class IOPS_OT_mesh_field_offset_edge_slide(_SlideMixin, bpy.types.Operator):
    bl_idname = "iops.mesh_field_offset_edge_slide"
    bl_label = "iOps Field Offset Edge Slide"
    bl_description = ("Add a loop on each side of the selected edge loops and slide "
                      "them apart, each vertex by the falloff fields' weight")
    op_label = "Offset Edge Slide"
    _transient = _SlideMixin._transient + ("_rails",)

    def _build(self, context):
        """Add the new loops and select them; False when no object had
        selected edges. As in Blender, the loops stay when the slide is
        cancelled."""
        self._rails = {}
        for obj in context.objects_in_mode_unique_data:
            if obj.type == "MESH":
                rails = offset_loops(obj)
                if rails:
                    self._rails[obj.data.name] = rails
        return bool(self._rails)

    def _targets(self, domain):
        TA = domain.P.copy()
        for e in domain.entries:
            m = e.mw
            rails = self._rails.get(e.obj.data.name, {})
            for i, v in enumerate(e.verts):
                end = rails.get(v.index)
                if end is not None:
                    TA[e.slice.start + i] = m[:3, :3] @ np.array(end[:]) + m[:3, 3]
        return TA, domain.P.copy()

    def execute(self, context):
        if not self._build(context):
            self.report({"WARNING"}, "Field Offset Edge Slide: no selected edges")
            return {"CANCELLED"}
        return super().execute(context)

    def invoke(self, context, event):
        if context.region_data is None:
            self.report({"WARNING"}, "Field Offset Edge Slide: run from a 3D viewport")
            return {"CANCELLED"}
        if not self._build(context):
            self.report({"WARNING"}, "Field Offset Edge Slide: no selected edges")
            return {"CANCELLED"}
        return super().invoke(context, event)


classes = (IOPS_OT_mesh_field_edge_slide, IOPS_OT_mesh_field_offset_edge_slide)
