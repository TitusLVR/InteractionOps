"""Cursor Place: Shift+RMB press-hold-release puts the 3D cursor on the
evaluated surface under the mouse (modifiers and collection instances
included) and orients it — one cursor axis along the surface normal,
another along the nearest edge.

While the button is held:

* **Slide** (default): the cursor follows the mouse — projected onto a
  polygon edge when within the snap threshold of one, otherwise free on
  the face at the raycast hit point.
* **Snap** (Ctrl held, like Blender's snapping): nearest vertex / edge
  midpoint / face centre of the hit polygon, in screen space.
* **Aim** (Shift pressed again, toggle): the position is locked and the
  edge axis points at whatever is under the mouse.
* **Alt** held: the position keeps following, the orientation is frozen.

Hot path per mouse move: one `scene.ray_cast`, then only the hit polygon's
vertices are read from the evaluated mesh and projected. No bmesh.
"""
import bpy
from mathutils import Matrix, Vector
from mathutils.geometry import tessellate_polygon
from bpy_extras.view3d_utils import (
    location_3d_to_region_2d,
    region_2d_to_location_3d,
    region_2d_to_origin_3d,
    region_2d_to_vector_3d,
)
from mathutils.geometry import intersect_line_plane
import numpy as np

from ..ui.draw import primitives as draw, draw_scope, Role
from ..ui.draw import safe_handler_add, safe_handler_remove
from ..ui.draw.theme import get_theme, axis_color
from ..ui.hud import text as hud_text
from ..ui.hud import (HUDOverlay, HelpOverlay, HUDSection, HUDItem,
                      HUDParam, ItemState, capture_event)
from ..utils.picking import raycast_from_mouse, px_world_at, SNAP_THRESHOLD_PX
from ..utils.cursor_place_core import (
    AXES, Pick, pick_element, slide_element, build_frame, set_normal_axis,
    cycle_edge_axis, aim_edge_dir,
)
from ..utils.three_point_core import _any_perpendicular

_KIND_LABELS = {"VERT": "Vertex", "EDGE": "Edge", "FACE": "Face"}
_LETTER_GAP_PX = 9.0
# Objects drawn without a surface are see-through for the ray, like for the
# eye: wire / bounds display of a geometry object shows no face to land on.
_SEE_THROUGH_DISPLAY = {"WIRE", "BOUNDS"}
_SURFACE_TYPES = {"MESH", "CURVE", "SURFACE", "FONT", "META", "CURVES", "POINTCLOUD", "VOLUME"}
# A hit polygon is trusted only when the ray hit lies (nearly) in its plane;
# otherwise `face_index` indexes some other geometry (e.g. a geometry-nodes
# instance) and the raw hit point/normal are used instead.
_PLANE_TOLERANCE = 1e-3


# --- HUD / Help builders ---------------------------------------------------

def _build_hud(context):
    hud = HUDOverlay("cursor_place")
    hud.title = "Cursor Place"
    hud.bind_region(context.region)
    return hud


def _build_help(context):
    helpo = HelpOverlay("cursor_place")
    helpo.add_section(HUDSection("Cursor Place", [
        HUDItem("Slide along the face / edge under the mouse", "Move", ItemState.ON, default_state=ItemState.OFF, always_show=True),
        HUDItem("Snap to nearest vertex / edge mid / face centre", "Hold Ctrl", ItemState.ON, default_state=ItemState.OFF, always_show=True),
        HUDItem("Aim the edge axis at the mouse (position locked)", "Shift (toggle)", ItemState.ON, default_state=ItemState.OFF, always_show=True),
        HUDItem("Move, keep the current orientation", "Hold Alt", ItemState.ON, default_state=ItemState.OFF, always_show=True),
        HUDItem("Active object only", "A", ItemState.ON, default_state=ItemState.OFF, always_show=True),
        HUDItem("Ignore triangulation (pick the source n-gon)", "T", ItemState.ON, default_state=ItemState.OFF, always_show=True),
        HUDItem("Normal axis", "X / Y / Z", ItemState.ON, default_state=ItemState.OFF, always_show=True),
        HUDItem("Flip normal", "F", ItemState.ON, default_state=ItemState.OFF, always_show=True),
        HUDItem("Edge axis", "Wheel", ItemState.ON, default_state=ItemState.OFF, always_show=True),
        HUDItem("Confirm", "Release", ItemState.ON, default_state=ItemState.OFF, always_show=True),
        HUDItem("Cancel", "Esc", ItemState.ON, default_state=ItemState.OFF, always_show=True),
        HUDItem("Help / HUD", "H", ItemState.ON, default_state=ItemState.OFF, always_show=True),
    ]))
    helpo.bind_region(context.region)
    return helpo


# --- Draw callbacks ----------------------------------------------------------

def _build_vert_poly_lookup(mesh):
    """(sorted loop vertex ids, matching polygon ids, mesh) for `mesh`.
    numpy foreach_get + one argsort: ~0.1 s per million loops, done once
    per original mesh per modal."""
    try:
        n_loops = len(mesh.loops)
        n_polys = len(mesh.polygons)
        if n_loops == 0 or n_polys == 0:
            return (None, None, mesh)
        loop_verts = np.empty(n_loops, dtype=np.int32)
        mesh.loops.foreach_get("vertex_index", loop_verts)
        loop_total = np.empty(n_polys, dtype=np.int32)
        mesh.polygons.foreach_get("loop_total", loop_total)
        loop_polys = np.repeat(np.arange(n_polys, dtype=np.int32), loop_total)
        order = np.argsort(loop_verts, kind="stable")
        return (loop_verts[order], loop_polys[order], mesh)
    except (ReferenceError, AttributeError, ValueError):
        return (None, None, mesh)


def _newell_normal(verts3d):
    n = Vector((0.0, 0.0, 0.0))
    count = len(verts3d)
    for i in range(count):
        a = verts3d[i]
        b = verts3d[(i + 1) % count]
        n.x += (a.y - b.y) * (a.z + b.z)
        n.y += (a.z - b.z) * (a.x + b.x)
        n.z += (a.x - b.x) * (a.y + b.y)
    if n.length_squared <= 0.0:
        return Vector((0.0, 0.0, 1.0))
    return n.normalized()


def _snap_candidates(verts3d, chosen):
    """Snap candidates of one polygon (vertices, edge midpoints, centre)
    minus the chosen one, which is drawn separately as the Preview point."""
    n = len(verts3d)
    if n < 3:
        return []
    pts = list(verts3d)
    pts += [(verts3d[i] + verts3d[(i + 1) % n]) * 0.5 for i in range(n)]
    pts.append(sum(verts3d, Vector()) / n)
    c = Vector(chosen)
    tol = 1e-10 * max(1.0, c.length_squared)
    return [p for p in pts if (p - c).length_squared > tol]


def _draw_preview_3d(op, context):
    """POST_VIEW: element highlight + cursor axis ghost. Reads `op._pick`
    only — no scene queries in the draw handler."""
    data = getattr(op, "_pick", None)
    if data is None:
        return
    pick, frame, verts3d, axis_len, tris, aim, snap_pts = data
    pos = Vector(pick.position)

    with draw_scope(blend="ALPHA", depth="NONE", face_culling="NONE"):
        # Element under the mouse (or the frozen one in aim mode): Closest.
        if pick.kind == "FACE":
            if tris:
                draw.tris(tris, role=Role.GHOST_CLOSEST, context=context)
            if len(verts3d) >= 2:
                draw.polyline(list(verts3d) + [verts3d[0]], role=Role.CLOSEST_LINE,
                              width="closest", context=context)
        elif pick.kind == "EDGE":
            draw.edges_3d([Vector(pick.edge[0]), Vector(pick.edge[1])],
                          role=Role.CLOSEST_LINE, width="closest", context=context)
        else:
            draw.points([pos], role=Role.CLOSEST_POINT, context=context)

        # Snap (Ctrl): every candidate of the hit polygon as a plain theme
        # point; the chosen one is drawn in Preview below, on top.
        if snap_pts:
            draw.points(snap_pts, role=Role.POINT, context=context)

        if aim is not None:
            tpick, tverts = aim
            tpos = Vector(tpick.position)
            if tpick.kind == "FACE" and len(tverts) >= 2:
                draw.polyline(list(tverts) + [tverts[0]], role=Role.ACTIVE_LINE,
                              width="active", context=context)
            elif tpick.kind == "EDGE":
                draw.edges_3d([Vector(tpick.edge[0]), Vector(tpick.edge[1])],
                              role=Role.ACTIVE_LINE, width="active", context=context)
            draw.points([tpos], role=Role.ACTIVE_POINT, context=context)
            draw.edges_3d([pos, tpos], role=Role.PREVIEW_LINE, width="preview",
                          context=context)

        # Cursor ghost: three equal, screen-constant axis lines in Blender's
        # axis colours and a small centre dot. Letters go in the pixel pass.
        length = axis_len
        for i, letter in enumerate(AXES):
            r, g, b, _ = axis_color(letter)
            draw.edges_3d([pos, pos + Vector(frame[i]) * length],
                          color=(r, g, b, 1.0), width="axis_gizmo", context=context)
        # Where the cursor will land (slide point or snapped candidate):
        # the Result Preview point of the theme.
        draw.points([pos], role=Role.PREVIEW_POINT, context=context)


def _draw_pixel(op, context):
    """POST_PIXEL: axis letters at the gizmo tips, then help + HUD."""
    data = getattr(op, "_pick", None)
    region = context.region
    rv3d = context.region_data
    if (data is not None and region is not None and rv3d is not None
            and getattr(op, "_axis_letters", True)):
        pick, frame, _verts3d, axis_len, _tris, _aim, _snap_pts = data
        pos = Vector(pick.position)
        length = axis_len
        theme = get_theme(context)
        origin2d = location_3d_to_region_2d(region, rv3d, pos)
        for i, letter in enumerate(AXES):
            tip = pos + Vector(frame[i]) * length
            p2 = location_3d_to_region_2d(region, rv3d, tip)
            if p2 is None:
                continue
            # Letter sits a few pixels past the tip, continuing the axis
            # direction on screen. An axis pointing (almost) at the camera
            # projects to a stub, so the gap shrinks with the stub instead
            # of flipping around a noisy direction.
            if origin2d is not None:
                d2 = p2 - origin2d
                l2 = d2.length
                if l2 > 1e-3:
                    gap = min(_LETTER_GAP_PX, l2)
                    p2 = p2 + d2 * (gap / l2)
            r, g, b, _ = axis_color(letter)
            w, h = hud_text.measure(letter, theme=theme, size_token="axis_letter")
            hud_text.draw(letter, int(p2.x - w * 0.5), int(p2.y - h * 0.5),
                          theme=theme, color=(r, g, b, 1.0),
                          size_token="axis_letter")

    helpo = getattr(op, "_help", None)
    hud = getattr(op, "_hud", None)
    last_event = getattr(op, "_last_event", None)
    if helpo is not None:
        helpo.draw(context, last_event)
    if hud is not None:
        hud.draw(context, last_event)


def _gizmo_length(context, region, rv3d, pos, axis_px):
    """World length of the axis ghost: `axis_px` pixels at the depth of
    `pos`, clamped in perspective so the tips stay in front of the near
    clipping plane (otherwise an axis pointing at a close camera gets cut
    off and its letter blinks)."""
    length = axis_px * px_world_at(region, rv3d, pos)
    if length <= 0.0:
        return 0.0
    if rv3d.is_perspective:
        try:
            if rv3d.view_perspective == "CAMERA" and context.scene.camera is not None:
                clip_start = context.scene.camera.data.clip_start
            else:
                clip_start = context.space_data.clip_start
        except AttributeError:
            clip_start = 0.1
        view_inv = rv3d.view_matrix.inverted()
        cam_pos = view_inv.translation
        view_dir = -view_inv.col[2].xyz.normalized()
        depth = (pos - cam_pos).dot(view_dir)
        room = (depth - clip_start) * 0.85
        if room < length:
            length = max(room, 0.0)
    return length


def _face_tris(verts3d):
    """Triangulate a polygon once per pick change (concave n-gons included)."""
    if len(verts3d) < 3:
        return []
    if len(verts3d) == 3:
        return list(verts3d)
    if len(verts3d) == 4:
        return [verts3d[0], verts3d[1], verts3d[2], verts3d[0], verts3d[2], verts3d[3]]
    try:
        return [verts3d[i] for tri in tessellate_polygon([verts3d]) for i in tri]
    except Exception:
        return []


# --- Operator ----------------------------------------------------------------

class IOPS_OT_CursorPlace(bpy.types.Operator):
    """Hold Shift+RMB: place the 3D cursor on the surface under the mouse
    (modifiers and collection instances included) and orient it to the
    surface normal and nearest edge. Move: slide along the face or edge.
    Ctrl: snap to the nearest vertex / edge midpoint / face centre. Shift
    again: lock the position and aim the edge axis. Alt: move with the
    orientation frozen. Release to place, Esc to cancel"""

    bl_idname = "iops.cursor_place"
    bl_label = "IOPS Cursor Place"
    bl_options = {"REGISTER", "UNDO"}
    is_bindable = True

    @classmethod
    def poll(cls, context):
        return (
            context.area is not None
            and context.area.type == "VIEW_3D"
            and context.mode in {"OBJECT", "EDIT_MESH"}
        )

    # --- lifecycle ----------------------------------------------------------

    def invoke(self, context, event):
        if context.space_data is None or context.space_data.type != "VIEW_3D":
            self.report({"WARNING"}, "Active space must be a 3D Viewport")
            return {"CANCELLED"}
        # Right-click-select users have Shift+RMB as extend-select; the
        # shipped default must not take that away from them.
        if event.type == "RIGHTMOUSE" and _select_mouse_is_right(context):
            return {"PASS_THROUGH"}
        try:
            prefs = context.preferences.addons["InteractionOps"].preferences
            self._normal_axis = prefs.cursor_place_normal_axis
            self._edge_axis = prefs.cursor_place_edge_axis
            self._axis_px = float(prefs.cursor_place_axis_size)
            self._axis_letters = bool(prefs.cursor_place_axis_letters)
            self._slide_px = float(getattr(prefs, "cursor_bisect_snap_threshold",
                                           SNAP_THRESHOLD_PX))
        except (KeyError, AttributeError):
            self._normal_axis, self._edge_axis, self._axis_px = "Z", "Y", 42.0
            self._axis_letters = True
            self._slide_px = SNAP_THRESHOLD_PX
        if self._normal_axis == self._edge_axis:
            self._edge_axis = cycle_edge_axis(self._normal_axis, self._normal_axis)
        self._flip = False
        self._snap = bool(event.ctrl)
        self._aim = False          # Shift (toggle): aim mode on/off
        self._active_only = False  # A: raycast only the active object
        self._ignore_tri = True    # T: pick the pre-triangulation polygon (see _ngon_for)
        self._ngon_cache = {}      # original-mesh pointer -> (loop_verts_sorted, loop_poly_sorted, mesh)
        self._aim_lock = None      # aim mode: (pick, verts3d) frozen when it was switched on
        self._orient_lock = None   # Alt: (normal, edge_dir) frozen at the first Alt move
        # The key/button whose release confirms: whatever invoked us.
        self._trigger = event.type if event.value == "PRESS" else "RIGHTMOUSE"
        self._mesh_cache = {}
        self._owner_cache = {}
        self._exclude = _see_through_objects(context)
        self._pick = None
        self._sig = None
        self._mouse = (event.mouse_region_x, event.mouse_region_y)
        self._handles = []

        self._hud = _build_hud(context)
        self._hud.add_param(HUDParam("Mode", lambda: self._mode_label(), "str"))
        self._hud.add_param(HUDParam("Element", lambda: self._snap_label(), "str"))
        self._hud.add_param(HUDParam("Active only", lambda: self._active_only, "bool"))
        self._hud.add_param(HUDParam("Ignore Triangulate", lambda: self._ignore_tri, "bool"))
        self._hud.add_param(HUDParam("Normal axis", lambda: ("-" if self._flip else "") + self._normal_axis, "str"))
        self._hud.add_param(HUDParam("Edge axis", lambda: self._edge_axis, "str"))
        self._help = _build_help(context)
        self._last_event = capture_event(event, None)

        self._handles.append(safe_handler_add(
            bpy.types.SpaceView3D, _draw_preview_3d, (self, context),
            "WINDOW", "POST_VIEW", tick=False))
        self._handles.append(safe_handler_add(
            bpy.types.SpaceView3D, _draw_pixel, (self, context),
            "WINDOW", "POST_PIXEL", tick=True))

        self._update(context, event)
        context.window_manager.modal_handler_add(self)
        return {"RUNNING_MODAL"}

    def _mode_label(self):
        base = "Snap" if self._snap else "Slide"
        if self._aim:
            return base + " · Aim edge axis"
        if self._orient_lock is not None:
            return base + " · Orientation locked"
        return base

    def _snap_label(self):
        data = self._pick
        if data is None:
            return "—"
        return _KIND_LABELS.get(data[0].kind, "?")

    def _cleanup(self, context):
        for h in self._handles:
            try:
                safe_handler_remove(h, bpy.types.SpaceView3D, "WINDOW")
            except ValueError:
                pass
        self._handles = []
        self._mesh_cache = {}
        self._owner_cache = {}
        self._ngon_cache = {}
        if context.area is not None:
            context.area.tag_redraw()

    # --- picking ------------------------------------------------------------

    def _update(self, context, event):
        region = context.region
        rv3d = context.region_data
        if region is None or rv3d is None:
            return
        mx, my = event.mouse_region_x, event.mouse_region_y
        self._mouse = (mx, my)
        self._snap = bool(event.ctrl)
        alt = bool(event.alt)
        if not self._aim:
            self._aim_lock = None
        if not alt or self._aim:
            self._orient_lock = None

        pick = verts3d = None
        aim = None
        restrict = None
        if self._active_only:
            active = context.view_layer.objects.active
            restrict = [active] if active is not None else []
        hit, loc, nrm, face_index, obj, matrix = raycast_from_mouse(
            context, (mx, my), visible_only=True, region=region, rv3d=rv3d,
            owner_cache=self._owner_cache, restrict_to=restrict,
            exclude=self._exclude)
        if self._aim and self._aim_lock is not None:
            # Aim: the position (and element) stay where aim mode was
            # switched on; the edge axis points at the pick under the mouse
            # (slide point, or the snapped element with Ctrl), or at the
            # mouse itself in the tangent plane when nothing is hit.
            pick, verts3d = self._aim_lock
            pos = Vector(pick.position)
            if hit:
                tpick, tverts = self._pick_on_hit(region, rv3d, (mx, my), loc, nrm,
                                                  face_index, obj, matrix)
                target = tpick.position
                aim = (tpick, tverts)
            else:
                origin = region_2d_to_origin_3d(region, rv3d, (mx, my))
                direction = region_2d_to_vector_3d(region, rv3d, (mx, my))
                t = intersect_line_plane(origin, origin + direction, pos, Vector(pick.normal))
                target = tuple(t) if t is not None else None
            aimed = aim_edge_dir(pick.position, pick.normal, target)
            if aimed is not None:
                pick = pick._replace(edge_dir=aimed)
            self._aim_lock = (pick, verts3d)
        else:
            if hit:
                pick, verts3d = self._pick_on_hit(region, rv3d, (mx, my), loc, nrm,
                                                  face_index, obj, matrix)
                if self._aim:
                    self._aim_lock = (pick, verts3d)
                elif alt:
                    # Alt: move freely, keep the orientation from the first
                    # Alt move (axis letters / flip still apply on top).
                    if self._orient_lock is None:
                        self._orient_lock = (pick.normal, pick.edge_dir)
                    pick = pick._replace(normal=self._orient_lock[0],
                                         edge_dir=self._orient_lock[1])

        new_pick = None
        sig = None
        if pick is not None:
            frame = build_frame(pick.normal, pick.edge_dir,
                                self._normal_axis, self._edge_axis,
                                flip=self._flip)
            pos = Vector(pick.position)
            axis_len = _gizmo_length(context, region, rv3d, pos, self._axis_px)
            tris = _face_tris(verts3d) if pick.kind == "FACE" else []
            # Candidates belong to the polygon under the mouse: the aim
            # target while aiming, the pick itself otherwise.
            under = aim[1] if aim is not None else verts3d
            snapped = aim[0].position if aim is not None else pick.position
            snap_pts = _snap_candidates(under, snapped) if self._snap else []
            new_pick = (pick, frame, verts3d, axis_len, tris, aim, snap_pts)
            sig = (pick.kind, pick.index, self._snap,
                   tuple(round(c, 6) for c in pick.position),
                   tuple(round(c, 5) for row in frame for c in row),
                   round(axis_len, 9), len(verts3d),
                   None if aim is None else (aim[0].kind, aim[0].index,
                                             tuple(round(c, 6) for c in aim[0].position)))

        # Always keep the freshest pick (the commit reads it); the signature
        # only decides whether the viewport needs a redraw.
        self._pick = new_pick
        if sig != self._sig:
            self._sig = sig
            region.tag_redraw()

    def _pick_on_hit(self, region, rv3d, mouse, loc, nrm, face_index, obj, matrix):
        """Pick from the hit polygon; when the polygon can't be read or does
        not contain the hit point, degrade to a FACE pick at the raw hit."""
        mesh = self._mesh_for(obj) if obj is not None else None
        if (mesh is not None and face_index is not None
                and 0 <= face_index < len(mesh.polygons)):
            poly = mesh.polygons[face_index]
            verts = mesh.vertices
            vert_ids = None
            if self._ignore_tri:
                vert_ids = self._ngon_for(obj, mesh, poly)
            if vert_ids is None:
                vert_ids = list(poly.vertices)
            verts3d = [matrix @ verts[i].co for i in vert_ids]
            poly_normal = _newell_normal(verts3d)
            center = sum(verts3d, Vector()) / len(verts3d)
            # Sanity guard against a stale face index: the hit must lie on
            # the polygon. For a non-planar polygon the ray lands on one of
            # its loop triangles, i.e. within the vertices' own spread
            # about the mean plane, so allow that spread on top of the
            # absolute tolerance.
            spread = max(abs((v - center).dot(poly_normal)) for v in verts3d)
            tol = _PLANE_TOLERANCE * max(1.0, center.length) + spread
            if abs((loc - center).dot(poly_normal)) <= tol:
                if not self._snap:
                    # Edge threshold is a pixel pref: convert at the hit depth.
                    threshold = self._slide_px * px_world_at(region, rv3d, loc)
                    pick = slide_element(verts3d, loc, poly_normal=poly_normal,
                                         threshold=threshold)
                else:
                    pick = pick_element(verts3d, loc, poly_normal=poly_normal,
                                        poly_center=center)
                return pick, verts3d
        # Fallback: the raw ray hit (curves/text/GN instances, bad indices).
        n = tuple(nrm) if nrm is not None and nrm.length_squared > 0.0 else (0.0, 0.0, 1.0)
        edge_dir = _any_perpendicular(tuple(Vector(n).normalized()))
        pick = Pick("FACE", None, tuple(loc), n, edge_dir, (tuple(loc), tuple(loc)))
        return pick, []

    def _mesh_for(self, obj):
        """Evaluated mesh of a ray_cast hit object, cached per object."""
        key = obj.as_pointer()
        mesh = self._mesh_cache.get(key)
        if mesh is not None:
            try:
                len(mesh.polygons)
                return mesh
            except ReferenceError:
                pass
        try:
            if not obj.is_evaluated:
                obj = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
            mesh = obj.data if obj.type == "MESH" else None
        except (ReferenceError, AttributeError):
            mesh = None
        if mesh is not None:
            self._mesh_cache[key] = mesh
        return mesh

    def _ngon_for(self, obj, mesh, poly):
        """Vertex indices of the *original* polygon the evaluated polygon
        `poly` is a piece of, or None when the mapping is not safe.

        Triangulate (and any topology-preserving stack around it) keeps the
        vertex count and order of the original mesh, so the triangle's
        vertex ids name the original polygon directly. No modifier is
        touched, so nothing re-evaluates: in a multi-million-tri scene the
        old show_viewport toggle cost a full depsgraph pass on entry and
        again on release. Anything that changed the vertex count (Bevel,
        Mirror, Subdivision...) falls back to the evaluated polygon."""
        try:
            orig = obj.original.data if obj.is_evaluated else obj.data
        except (ReferenceError, AttributeError):
            return None
        if orig is None or len(orig.vertices) != len(mesh.vertices):
            return None
        if len(orig.polygons) >= len(mesh.polygons):
            return None     # nothing was triangulated
        key = orig.as_pointer()
        entry = self._ngon_cache.get(key)
        if entry is None:
            entry = _build_vert_poly_lookup(orig)
            self._ngon_cache[key] = entry
        loop_verts, loop_polys, _keep = entry
        if loop_verts is None:
            return None
        ids = list(poly.vertices)
        if len(ids) < 3:
            return None
        cands = None
        for v in ids[:3]:
            lo = np.searchsorted(loop_verts, v, side="left")
            hi = np.searchsorted(loop_verts, v, side="right")
            ps = set(loop_polys[lo:hi].tolist())
            cands = ps if cands is None else (cands & ps)
            if not cands:
                return None
        if len(cands) != 1:
            return None
        return list(orig.polygons[cands.pop()].vertices)

    # --- commit -------------------------------------------------------------

    def _commit(self, context):
        scene = context.scene
        data = self._pick
        if data is not None:
            pick, frame, _verts3d, _px, _tris, _aim, _snap_pts = data
            rot = Matrix((frame[0], frame[1], frame[2])).transposed()
            scene.cursor.matrix = Matrix.Translation(Vector(pick.position)) @ rot.to_4x4()
        else:
            region = context.region
            rv3d = context.region_data
            if region is None or rv3d is None:
                return
            pos = region_2d_to_location_3d(region, rv3d, self._mouse,
                                           scene.cursor.location)
            if pos is None:
                return
            scene.cursor.matrix = (Matrix.Translation(pos)
                                   @ scene.cursor.matrix.to_3x3().to_4x4())

    # --- modal ----------------------------------------------------------------

    def modal(self, context, event):
        self._last_event = capture_event(event, getattr(self, "_last_event", None))

        try:
            theme_prefs = context.preferences.addons["InteractionOps"].preferences.iops_theme
        except (KeyError, AttributeError):
            theme_prefs = None
        if theme_prefs is not None:
            for ov in (self._help, self._hud):
                if ov is not None and ov.handle_drag_event(context, event, theme_prefs):
                    return {"RUNNING_MODAL"}
            if self._help.handle_toggle_event(event, theme_prefs):
                return {"RUNNING_MODAL"}
            if self._hud.handle_param_toggle_event(event, theme_prefs):
                return {"RUNNING_MODAL"}

        et, ev = event.type, event.value

        if et in {"MOUSEMOVE", "INBETWEEN_MOUSEMOVE"}:
            self._update(context, event)
            return {"RUNNING_MODAL"}

        if et in {"LEFT_SHIFT", "RIGHT_SHIFT"}:
            # The Shift that invoked us is simply released at some point;
            # every later Shift press toggles aim mode, locking the pick.
            if ev == "PRESS" and not event.is_repeat:
                self._aim = not self._aim
                if self._aim and self._pick is not None:
                    self._aim_lock = (self._pick[0], self._pick[2])
                else:
                    self._aim_lock = None
                self._update(context, event)
            return {"RUNNING_MODAL"}

        if et in {"LEFT_CTRL", "RIGHT_CTRL", "LEFT_ALT", "RIGHT_ALT"}:
            self._update(context, event)
            return {"RUNNING_MODAL"}

        if et == self._trigger and ev == "RELEASE":
            # A release outside the viewport region (over another editor)
            # keeps the last in-region preview instead of re-picking there.
            if _inside_region(context.region, event):
                self._update(context, event)
            self._commit(context)
            self._cleanup(context)
            return {"FINISHED"}

        if (et == "ESC" and ev == "PRESS") or et == "WINDOW_DEACTIVATE":
            self._cleanup(context)
            return {"CANCELLED"}

        if ev == "PRESS" and not event.is_repeat:
            if et in {"X", "Y", "Z"}:
                self._normal_axis, self._edge_axis = set_normal_axis(
                    self._normal_axis, self._edge_axis, et)
                self._update(context, event)
                return {"RUNNING_MODAL"}
            if et == "F":
                self._flip = not self._flip
                self._update(context, event)
                return {"RUNNING_MODAL"}
            if et == "A":
                self._active_only = not self._active_only
                self._update(context, event)
                return {"RUNNING_MODAL"}
            if et == "T":
                self._ignore_tri = not self._ignore_tri
                self._update(context, event)
                return {"RUNNING_MODAL"}
            if et in {"WHEELUPMOUSE", "WHEELDOWNMOUSE"}:
                self._edge_axis = cycle_edge_axis(self._normal_axis, self._edge_axis)
                self._update(context, event)
                return {"RUNNING_MODAL"}

        return {"RUNNING_MODAL"}


def _see_through_objects(context):
    """View-layer objects the ray must pierce: geometry displayed as wire or
    bounds. Scanned once per modal (hundreds of objects, microseconds)."""
    out = []
    try:
        for ob in context.view_layer.objects:
            if ob.type in _SURFACE_TYPES and ob.display_type in _SEE_THROUGH_DISPLAY:
                out.append(ob)
    except (ReferenceError, AttributeError):
        return None
    return out or None


def _inside_region(region, event):
    if region is None:
        return True
    return (0 <= event.mouse_region_x < region.width
            and 0 <= event.mouse_region_y < region.height)


def _select_mouse_is_right(context):
    try:
        kc = context.window_manager.keyconfigs.active
        return getattr(kc.preferences, "select_mouse", "LEFT") == "RIGHT"
    except (AttributeError, ReferenceError):
        return False
