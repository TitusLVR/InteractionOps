"""Per-modifier target picker (the stack-row eyedropper button).

Modal, pickup logic from object_mirror_rotate: LMB picks any visible
object as the modifier's target (nearest origin in screen space, so
empties work too; the candidate is highlighted). C creates an empty
target at the current 3D cursor right away, then stays in the
face-pick mode to refine: click a vert / edge-mid / center to snap
the 3D cursor there (Z = normal) and move the empty with it.
"""

import bpy
from mathutils import Matrix, Vector

from ...ui.draw import draw_scope, safe_handler_add, safe_handler_remove
from ...ui.draw import primitives as iops_draw
from ...ui.draw.theme import Role
from ...utils.picking import raycast_from_mouse
from ..object_mirror_rotate import _draw_tpick, _tpick_update
from . import iops_mod_registry

_NAV_EVENTS = {
    "MIDDLEMOUSE", "WHEELUPMOUSE", "WHEELDOWNMOUSE",
    "MOUSEPAN", "MOUSEZOOM", "MOUSEROTATE",
    "TRACKPADPAN", "TRACKPADZOOM",
    "NDOF_MOTION", "NDOF_BUTTON_FIT",
}

# evaluated meshes above this many edges only get their bounding box as
# the hover highlight (a full wire would stall the mousemove loop)
_HOVER_WIRE_MAX_EDGES = 60_000
_HOVER_FILL_MAX_TRIS = 120_000
# ghost fill is pulled toward the eye by this fraction of its depth: the
# gpu module has no polygon offset, and a coplanar fill z-fights the
# real surface into speckle
_FILL_DEPTH_BIAS = 2e-3
# screen-space pick radius for wire objects the raycast cannot hit
_PICK_WIRE_PX = 40.0

# bound_box corner order is fixed in Blender; 12 box edges
_BBOX_EDGES = ((0, 1), (1, 2), (2, 3), (3, 0),
               (4, 5), (5, 6), (6, 7), (7, 4),
               (0, 4), (1, 5), (2, 6), (3, 7))

_STATUS_PICK = ("LMB: pick target object · C: empty target at 3D cursor · "
                "Esc / RMB: cancel")
_STATUS_CURSOR = ("LMB: snap to vert / edge-mid / center · "
                  "Enter / Space: keep at cursor · C: back to object pick · "
                  "Esc / RMB: cancel")


def _view3d_region(context):
    """The 3D viewport's WINDOW region + its RegionView3D. The button
    lives in the N-panel / popup, so context.region is a UI region."""
    area = context.area
    if area is None or area.type != "VIEW_3D":
        area = next((a for a in context.window.screen.areas
                     if a.type == "VIEW_3D"), None)
        if area is None:
            return None, None
    region = next((r for r in area.regions if r.type == "WINDOW"), None)
    if region is None:
        return None, None
    return region, area.spaces.active.region_3d


def _wire_np(coords, pairs, mw):
    """World-space segment array (N, 2, 3) from a flat coord buffer and an
    edge-index buffer, transformed by mw."""
    import numpy as np
    m = np.array(mw, dtype=np.float32)
    pts = coords[pairs] @ m[:3, :3].T + m[:3, 3]
    return pts.reshape(-1, 2, 3)


def _mesh_wire(mesh, mw, cap):
    """(wire, tris): world-space edge segments (N, 2, 3) and triangle
    coords (M, 3, 3) of the evaluated mesh; either is None over its cap."""
    import numpy as np
    nv = len(mesh.vertices)
    co = np.empty(nv * 3, dtype=np.float32)
    mesh.vertices.foreach_get("co", co)
    co = co.reshape(nv, 3)
    wire = tris = None
    ne = len(mesh.edges)
    if 0 < ne <= cap:
        idx = np.empty(ne * 2, dtype=np.int32)
        mesh.edges.foreach_get("vertices", idx)
        wire = _wire_np(co, idx, mw)
    nt = len(mesh.loop_triangles)
    if 0 < nt <= _HOVER_FILL_MAX_TRIS:
        idx = np.empty(nt * 3, dtype=np.int32)
        mesh.loop_triangles.foreach_get("vertices", idx)
        m = np.array(mw, dtype=np.float32)
        tris = (co[idx] @ m[:3, :3].T + m[:3, 3]).reshape(-1, 3, 3)
    return wire, tris


def _object_wire(context, obj):
    """World-space wire of the depsgraph result as an (N, 2, 3) float32
    array, its triangles (M, 3, 3) or None, plus a flag telling whether
    the object has raycastable faces.

    MESH: evaluated edges. Curve-like types (CURVE / FONT / SURFACE /
    CURVES / GREASEPENCIL / META / VOLUME...): the evaluated object
    converted to a mesh. ARMATURE: bone head-tail segments. LATTICE:
    deformed points joined along U/V/W. Anything else (empties, lights,
    cameras, probes, speakers): the evaluated bounding box, or an axis
    cross when it is degenerate. Returns (wire, tris | None, has_faces)."""
    import numpy as np
    depsgraph = context.evaluated_depsgraph_get()
    ev = obj.evaluated_get(depsgraph)
    mw = ev.matrix_world
    wire, tris, has_faces = None, None, False
    if ev.type == "MESH":
        mesh = ev.data
        has_faces = len(mesh.polygons) > 0
        wire, tris = _mesh_wire(mesh, mw, _HOVER_WIRE_MAX_EDGES)
    elif ev.type == "ARMATURE":
        segs = [(mw @ pb.head, mw @ pb.tail) for pb in ev.pose.bones]
        if segs:
            wire = np.array(segs, dtype=np.float32)
    elif ev.type == "LATTICE":
        lat = ev.data
        u, v, w = lat.points_u, lat.points_v, lat.points_w
        pts = np.empty(len(lat.points) * 3, dtype=np.float32)
        lat.points.foreach_get("co_deform", pts)
        pts = pts.reshape(-1, 3)
        pairs = []
        for k in range(w):
            for jj in range(v):
                for ii in range(u):
                    a = ii + u * (jj + v * k)
                    if ii + 1 < u:
                        pairs.append((a, a + 1))
                    if jj + 1 < v:
                        pairs.append((a, a + u))
                    if k + 1 < w:
                        pairs.append((a, a + u * v))
        if pairs:
            wire = _wire_np(pts, np.array(pairs, dtype=np.int32).ravel(), mw)
    elif ev.type in {"CURVE", "FONT", "SURFACE", "CURVES", "GREASEPENCIL",
                     "GPENCIL", "META", "VOLUME", "POINTCLOUD"}:
        try:
            mesh = ev.to_mesh()
        except RuntimeError:
            mesh = None
        if mesh is not None:
            has_faces = len(mesh.polygons) > 0
            wire, tris = _mesh_wire(mesh, mw, _HOVER_WIRE_MAX_EDGES)
            ev.to_mesh_clear()
    if wire is None:
        bbox = _bbox_edges(ev, mw)
        if bbox is None:
            size = getattr(obj, "empty_display_size", 0.0) or 0.25
            origin = mw.translation
            bbox = []
            for axis in (Vector((1, 0, 0)), Vector((0, 1, 0)),
                         Vector((0, 0, 1))):
                d = (mw.to_3x3() @ axis).normalized() * size
                bbox.append(origin - d)
                bbox.append(origin + d)
        wire = np.array(bbox, dtype=np.float32).reshape(-1, 2, 3)
    return wire, tris, has_faces


def _wire_screen_distance(wire, persp, region, mouse):
    """Min screen-space distance (px) from mouse to the projected segments
    of an (N, 2, 3) world-space wire; inf when nothing projects in
    front of the camera."""
    import numpy as np
    n = wire.shape[0]
    pts = wire.reshape(-1, 3)
    hom = np.concatenate(
        [pts, np.ones((pts.shape[0], 1), dtype=np.float32)], axis=1) @ persp.T
    w = hom[:, 3]
    ok = w > 1e-6
    if not ok.any():
        return float("inf")
    w = np.where(ok, w, 1.0)
    sx = (hom[:, 0] / w * 0.5 + 0.5) * region.width
    sy = (hom[:, 1] / w * 0.5 + 0.5) * region.height
    p2 = np.stack([sx, sy], axis=1).reshape(n, 2, 2)
    ok = ok.reshape(n, 2).all(axis=1)
    if not ok.any():
        return float("inf")
    a, b = p2[ok, 0], p2[ok, 1]
    ab = b - a
    ap = mouse - a
    denom = (ab * ab).sum(axis=1)
    t = np.where(denom > 1e-9,
                 (ap * ab).sum(axis=1) / np.maximum(denom, 1e-9), 0.0)
    t = np.clip(t, 0.0, 1.0)
    closest = a + ab * t[:, None]
    d = np.linalg.norm(closest - mouse, axis=1)
    return float(d.min())


def _wire_for(op, context, obj):
    """Per-session cache of _object_wire (world space; survives view
    navigation, dropped when the pick session ends)."""
    key = obj.as_pointer()
    entry = op._wire_cache.get(key)
    if entry is None:
        entry = _object_wire(context, obj)
        op._wire_cache[key] = entry
    return entry


def _pick_object(op, context, event, region, rv3d, exclude=()):
    """Object under the mouse. A depsgraph raycast against the evaluated
    (modifier result) geometry first, so objects whose visible surface is
    far from their origin (array / mirror / boolean / displaced) are
    picked where the user actually clicks. Everything the ray cannot hit
    (curves, armatures, lattices, empties, lights, cameras, wire-only
    meshes) is picked by screen-space distance to its projected wire."""
    if region is None or rv3d is None:
        return None
    import numpy as np
    mouse = Vector((event.mouse_x - region.x, event.mouse_y - region.y))
    hit, _loc, _n, _idx, obj, _mat = raycast_from_mouse(
        context, mouse, exclude=exclude, visible_only=True,
        region=region, rv3d=rv3d)
    if hit and obj is not None:
        try:
            return obj.original
        except ReferenceError:
            pass
    persp = np.array(rv3d.perspective_matrix, dtype=np.float32)
    m2 = np.array((mouse.x, mouse.y), dtype=np.float32)
    best, best_d = None, _PICK_WIRE_PX
    for cand in context.visible_objects:
        if cand in exclude:
            continue
        try:
            wire, _tris, has_faces = _wire_for(op, context, cand)
        except (ReferenceError, RuntimeError):
            continue
        if has_faces or wire is None:
            continue          # surfaces are the raycast's job
        d = _wire_screen_distance(wire, persp, region, m2)
        if d < best_d:
            best_d, best = d, cand
    return best


def _bbox_edges(obj, mw):
    corners = [mw @ Vector(c) for c in obj.bound_box]
    lo = Vector(tuple(min(c[i] for c in corners) for i in range(3)))
    hi = Vector(tuple(max(c[i] for c in corners) for i in range(3)))
    if (hi - lo).length <= 1e-6:
        return None
    edges = []
    for a, b in _BBOX_EDGES:
        edges.append(corners[a])
        edges.append(corners[b])
    return edges


def _fill_coords(op, hover, tris, rv3d):
    """Ghost-fill vertex list with a view-dependent depth bias (poor man's
    polygon offset): every vertex moves toward the eye by
    _FILL_DEPTH_BIAS of its distance (perspective) or of the view
    distance along the view axis (ortho). Cached per hover object and
    view matrix, so navigation recomputes it once per view change."""
    import numpy as np
    vm = rv3d.view_matrix
    key = (hover.as_pointer(), tuple(tuple(r) for r in vm), rv3d.is_perspective)
    cache = getattr(op, "_fill_cache", None)
    if cache is not None and cache[0] == key:
        return cache[1]
    pts = tris.reshape(-1, 3)
    inv = vm.inverted()
    if rv3d.is_perspective:
        eye = np.array(inv.translation, dtype=np.float32)
        out = pts + (eye - pts) * _FILL_DEPTH_BIAS   # scales with depth
    else:
        view_dir = np.array(inv.col[2][:3], dtype=np.float32)  # toward eye
        out = pts + view_dir * (rv3d.view_distance * _FILL_DEPTH_BIAS)
    coords = out.tolist()
    op._fill_cache = (key, coords)
    return coords


def _draw_pick(op, context):
    if op.cursor_pick:
        _draw_tpick(op, context)
        return
    hover = getattr(op, "_hover", None)
    if hover is None:
        return
    try:
        wire, tris, _has_faces = _wire_for(op, context, hover)
        origin = hover.matrix_world.translation.copy()
    except (ReferenceError, RuntimeError):
        return
    if tris is not None:
        # result preview: ghost fill of the evaluated faces, no lines
        rv3d = context.region_data or op._rv3d
        with draw_scope(blend="ALPHA", depth="LESS_EQUAL",
                        face_culling="NONE", depth_mask=False):
            iops_draw.tris(_fill_coords(op, hover, tris, rv3d),
                           role=Role.GHOST_PREVIEW, context=context)
    elif wire is not None:
        # nothing to fill (curves, armatures, lattices, empties...):
        # the wire is the only thing there is to highlight; X-ray
        with draw_scope(blend="ALPHA", depth="NONE"):
            iops_draw.edges_3d(wire.reshape(-1, 3).tolist(),
                               role=Role.LINE, context=context)
    with draw_scope(blend="ALPHA", depth="NONE"):
        iops_draw.points([origin], role=Role.CLOSEST_POINT, context=context)


class IOPS_OT_ModPickTarget(bpy.types.Operator):
    """Pick a target for this modifier.
    LMB: pick any visible object (empties too, candidate highlighted).
    C: create an empty target at the 3D cursor, then face-pick to
    refine — click a vert / edge-mid / center to snap the cursor and
    the empty there; Enter / Space keeps the cursor position, C again
    drops the empty and returns to object pick.
    Esc / RMB: cancel"""

    bl_idname = "iops.mod_pick_target"
    bl_label = "Pick Modifier Target"
    bl_options = {"REGISTER", "UNDO"}

    index: bpy.props.IntProperty(options={"SKIP_SAVE"})

    def _modifier(self):
        try:
            return self._obj.modifiers[self.index]
        except (ReferenceError, IndexError):
            return None

    def _assign(self, md, obj):
        field = iops_mod_registry.object_fields(md)[0]
        setattr(md, field, obj)
        # RNA pointer polls can reject some object types (e.g. an
        # empty for a Boolean object)
        return getattr(md, field, None) == obj

    def invoke(self, context, event):
        obj = context.active_object
        if obj is None or not (0 <= self.index < len(obj.modifiers)):
            return {"CANCELLED"}
        md = obj.modifiers[self.index]
        fields = iops_mod_registry.object_fields(md)
        if not fields:
            self.report({"WARNING"}, "Modifier has no object target field")
            return {"CANCELLED"}
        region, rv3d = _view3d_region(context)
        if region is None or rv3d is None:
            self.report({"WARNING"}, "No 3D viewport")
            return {"CANCELLED"}
        self._obj = obj
        self._region = region
        self._rv3d = rv3d
        self._prev_target = getattr(md, fields[0], None)
        self._empty = None               # created by C, removed on cancel
        self._hover = None
        self._wire_cache = {}            # obj pointer -> (wire, tris, has_faces)
        self._fill_cache = None          # (key, coords) for _fill_coords
        self.cursor_pick = False
        self._tpick = None
        self._handle = safe_handler_add(
            bpy.types.SpaceView3D, _draw_pick, (self, context),
            "WINDOW", "POST_VIEW", tick=False,
        )
        context.window.cursor_modal_set("EYEDROPPER")
        context.workspace.status_text_set(_STATUS_PICK)
        context.window_manager.modal_handler_add(self)
        return {"RUNNING_MODAL"}

    def _drop_empty(self):
        """Remove the C-created empty and put the previous target back."""
        if self._empty is None:
            return
        md = self._modifier()
        if md is not None:
            try:
                self._assign(md, self._prev_target)
            except ReferenceError:
                self._assign(md, None)
        try:
            bpy.data.objects.remove(self._empty)
        except ReferenceError:
            pass
        self._empty = None

    def _finish(self, context, cancelled=False):
        if cancelled:
            self._drop_empty()
        if getattr(self, "_handle", None) is not None:
            safe_handler_remove(self._handle, bpy.types.SpaceView3D, "WINDOW")
            self._handle = None
        context.window.cursor_modal_restore()
        context.workspace.status_text_set(None)
        self._region.tag_redraw()
        return {"CANCELLED"} if cancelled else {"FINISHED"}

    def _spawn_empty_at_cursor(self, context, md):
        empty = bpy.data.objects.new(f"iops_target_{md.type.lower()}", None)
        empty.empty_display_type = "PLAIN_AXES"
        empty.empty_display_size = 0.5
        context.collection.objects.link(empty)
        empty.matrix_world = context.scene.cursor.matrix.copy()
        return empty

    def modal(self, context, event):
        if event.type in _NAV_EVENTS:
            return {"PASS_THROUGH"}

        if event.type in {"ESC", "RIGHTMOUSE"} and event.value == "PRESS":
            return self._finish(context, cancelled=True)

        md = self._modifier()
        if md is None:
            self.report({"WARNING"}, "Modifier is gone")
            return self._finish(context, cancelled=True)

        if event.type == "C" and event.value == "PRESS":
            if not self.cursor_pick:
                # take the cursor position right away: the empty target
                # exists from this moment; face-pick only refines it
                self._empty = self._spawn_empty_at_cursor(context, md)
                if not self._assign(md, self._empty):
                    bpy.data.objects.remove(self._empty)
                    self._empty = None
                    self.report({"WARNING"},
                                f"{md.name}: does not accept an empty")
                    return {"RUNNING_MODAL"}
                self.cursor_pick = True
                self._hover = None
                _tpick_update(self, context, event, self._region, self._rv3d)
                context.workspace.status_text_set(_STATUS_CURSOR)
                self._region.tag_redraw()
                return {"RUNNING_MODAL"}
            # second C = toggle back to object pick: the cursor empty was
            # provisional, drop it and restore the previous target
            self._drop_empty()
            self.cursor_pick = False
            self._tpick = None
            self._hover = _pick_object(self, context, event,
                                       self._region, self._rv3d,
                                       exclude={self._obj})
            context.workspace.status_text_set(_STATUS_PICK)
            self._region.tag_redraw()
            return {"RUNNING_MODAL"}

        if (self.cursor_pick and event.value == "PRESS"
                and event.type in {"RET", "NUMPAD_ENTER", "SPACE"}):
            self.report({"INFO"},
                        f"{md.name}: target = {self._empty.name} (at cursor)")
            return self._finish(context)

        if event.type == "MOUSEMOVE":
            if self.cursor_pick:
                _tpick_update(self, context, event, self._region, self._rv3d)
            else:
                self._hover = _pick_object(self, context, event,
                                           self._region, self._rv3d,
                                           exclude={self._obj})
            self._region.tag_redraw()
            return {"RUNNING_MODAL"}

        if event.type == "LEFTMOUSE" and event.value == "PRESS":
            if self.cursor_pick:
                _tpick_update(self, context, event, self._region, self._rv3d)
                tp = self._tpick
                if tp is None:
                    self.report({"WARNING"}, "No face under cursor")
                    return {"RUNNING_MODAL"}
                quat = tp["normal"].to_track_quat("Z", "Y")
                cursor = context.scene.cursor
                cursor.location = tp["closest"].copy()
                cursor.rotation_mode = "XYZ"
                cursor.rotation_euler = quat.to_euler()
                self._empty.matrix_world = Matrix.LocRotScale(
                    tp["closest"], quat, None)
                self.report({"INFO"},
                            f"{md.name}: target = {self._empty.name} "
                            "(snapped to face)")
                return self._finish(context)
            picked = self._hover or _pick_object(self, context, event,
                                                 self._region, self._rv3d,
                                                 exclude={self._obj})
            if picked is None:
                self.report({"WARNING"}, "No object near the click")
                return {"RUNNING_MODAL"}
            if not self._assign(md, picked):
                self.report({"WARNING"},
                            f"{md.name}: rejected {picked.name} — "
                            "pick another object")
                return {"RUNNING_MODAL"}
            self.report({"INFO"}, f"{md.name}: target = {picked.name}")
            return self._finish(context)

        return {"RUNNING_MODAL"}
