"""Cursor Place: Shift+RMB press-hold-release puts the 3D cursor on the
evaluated surface under the mouse (modifiers and collection instances
included) and orients it — one cursor axis along the surface normal,
another along the nearest edge.

Two ways to pick the position while the button is held:

* **Snap** (Shift released): nearest vertex / edge midpoint / face centre
  of the hit polygon, in screen space.
* **Slide** (Shift held): the cursor follows the mouse — projected onto a
  polygon edge when within the snap threshold of one, otherwise free on
  the face at the raycast hit point.

Hot path per mouse move: one `scene.ray_cast`, then only the hit polygon's
vertices are read from the evaluated mesh and projected. No bmesh.
"""
import bpy
from mathutils import Matrix, Vector
from mathutils.geometry import tessellate_polygon
from bpy_extras.view3d_utils import (
    location_3d_to_region_2d,
    region_2d_to_location_3d,
)

from ..ui.draw import primitives as draw, draw_scope, Role
from ..ui.draw import safe_handler_add, safe_handler_remove
from ..ui.draw.theme import get_theme, axis_color
from ..ui.hud import text as hud_text
from ..ui.hud import (HUDOverlay, HelpOverlay, HUDSection, HUDItem,
                      HUDParam, ItemState, capture_event)
from ..utils.picking import raycast_from_mouse, SNAP_THRESHOLD_PX
from ..utils.cursor_place_core import (
    AXES, Pick, pick_element, slide_element, build_frame, set_normal_axis,
    cycle_edge_axis,
)
from ..utils.three_point_core import _any_perpendicular

_KIND_LABELS = {"VERT": "Vertex", "EDGE": "Edge", "FACE": "Face"}
_LETTER_GAP_PX = 9.0
_FAR_2D = (1e9, 1e9)
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
        HUDItem("Snap to nearest vertex / edge mid / face centre", "Hover (Shift up)", ItemState.ON, default_state=ItemState.OFF, always_show=True),
        HUDItem("Slide along the face / edge under the mouse", "Hold Shift", ItemState.ON, default_state=ItemState.OFF, always_show=True),
        HUDItem("Normal axis", "X / Y / Z", ItemState.ON, default_state=ItemState.OFF, always_show=True),
        HUDItem("Flip normal", "F", ItemState.ON, default_state=ItemState.OFF, always_show=True),
        HUDItem("Edge axis", "Wheel", ItemState.ON, default_state=ItemState.OFF, always_show=True),
        HUDItem("Confirm", "Release", ItemState.ON, default_state=ItemState.OFF, always_show=True),
        HUDItem("Cancel", "Esc", ItemState.ON, default_state=ItemState.OFF, always_show=True),
        HUDItem("Help / HUD", "H (Shift up)", ItemState.ON, default_state=ItemState.OFF, always_show=True),
    ]))
    helpo.bind_region(context.region)
    return helpo


# --- Draw callbacks ----------------------------------------------------------

def _draw_preview_3d(op, context):
    """POST_VIEW: element highlight + cursor axis ghost. Reads `op._pick`
    only — no scene queries in the draw handler."""
    data = getattr(op, "_pick", None)
    if data is None:
        return
    pick, frame, verts3d, px_world, tris = data
    pos = Vector(pick.position)

    with draw_scope(blend="ALPHA", depth="NONE", face_culling="NONE"):
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

        # Cursor ghost: three equal, screen-constant axis lines in Blender's
        # axis colours and a small centre dot. Letters go in the pixel pass.
        length = op._axis_px * px_world
        for i, letter in enumerate(AXES):
            r, g, b, _ = axis_color(letter)
            draw.edges_3d([pos, pos + Vector(frame[i]) * length],
                          color=(r, g, b, 1.0), width="axis_gizmo", context=context)
        draw.points([pos], color=(1.0, 1.0, 1.0, 0.9), size=4.0, context=context)


def _draw_pixel(op, context):
    """POST_PIXEL: axis letters at the gizmo tips, then help + HUD."""
    data = getattr(op, "_pick", None)
    region = context.region
    rv3d = context.region_data
    if data is not None and region is not None and rv3d is not None:
        pick, frame, _verts3d, px_world, _tris = data
        pos = Vector(pick.position)
        length = op._axis_px * px_world
        theme = get_theme(context)
        origin2d = location_3d_to_region_2d(region, rv3d, pos)
        for i, letter in enumerate(AXES):
            tip = pos + Vector(frame[i]) * length
            p2 = location_3d_to_region_2d(region, rv3d, tip)
            if p2 is None:
                continue
            # Letter sits a few pixels past the tip, continuing the axis
            # direction on screen, centred on that point.
            if origin2d is not None and (p2 - origin2d).length_squared > 1.0:
                p2 = p2 + (p2 - origin2d).normalized() * _LETTER_GAP_PX
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
    surface normal and nearest edge. Shift released: snap to the nearest
    vertex / edge midpoint / face centre. Shift held: slide along the face
    or edge. Release to place, Esc to cancel"""

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
            self._slide_px = float(getattr(prefs, "cursor_bisect_snap_threshold",
                                           SNAP_THRESHOLD_PX))
        except (KeyError, AttributeError):
            self._normal_axis, self._edge_axis, self._axis_px = "Z", "X", 60.0
            self._slide_px = SNAP_THRESHOLD_PX
        if self._normal_axis == self._edge_axis:
            self._edge_axis = cycle_edge_axis(self._normal_axis, self._normal_axis)
        self._flip = False
        self._slide = bool(event.shift)
        # The key/button whose release confirms: whatever invoked us.
        self._trigger = event.type if event.value == "PRESS" else "RIGHTMOUSE"
        self._mesh_cache = {}
        self._owner_cache = {}
        self._pick = None
        self._sig = None
        self._mouse = (event.mouse_region_x, event.mouse_region_y)
        self._handles = []

        self._hud = _build_hud(context)
        self._hud.add_param(HUDParam("Mode", lambda: "Slide" if self._slide else "Snap", "str"))
        self._hud.add_param(HUDParam("Element", lambda: self._snap_label(), "str"))
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
        self._slide = bool(event.shift)

        hit, loc, nrm, face_index, obj, matrix = raycast_from_mouse(
            context, (mx, my), visible_only=True, region=region, rv3d=rv3d,
            owner_cache=self._owner_cache)
        new_pick = None
        sig = None
        if hit:
            pick, verts3d = self._pick_on_hit(region, rv3d, (mx, my), loc, nrm,
                                              face_index, obj, matrix)
            frame = build_frame(pick.normal, pick.edge_dir,
                                self._normal_axis, self._edge_axis,
                                flip=self._flip)
            pos = Vector(pick.position)
            p2 = location_3d_to_region_2d(region, rv3d, pos)
            if p2 is not None:
                px_world = (region_2d_to_location_3d(
                    region, rv3d, (p2.x + 1.0, p2.y), pos) - pos).length
            else:
                px_world = 0.0
            tris = _face_tris(verts3d) if pick.kind == "FACE" else []
            new_pick = (pick, frame, verts3d, px_world, tris)
            sig = (pick.kind, pick.index,
                   tuple(round(c, 6) for c in pick.position),
                   tuple(round(c, 5) for row in frame for c in row),
                   round(px_world, 9), len(verts3d))

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
            nmat = matrix.inverted_safe().transposed().to_3x3()
            poly_normal = (nmat @ poly.normal).normalized()
            center = matrix @ poly.center
            if abs((loc - center).dot(poly_normal)) <= _PLANE_TOLERANCE * max(1.0, center.length):
                verts = mesh.vertices
                verts3d = [matrix @ verts[i].co for i in poly.vertices]
                verts2d = []
                for v in verts3d:
                    p2 = location_3d_to_region_2d(region, rv3d, v)
                    verts2d.append((p2.x, p2.y) if p2 is not None else _FAR_2D)
                if self._slide:
                    pick = slide_element(verts3d, verts2d, mouse, hit_location=loc,
                                         poly_normal=poly_normal,
                                         threshold_px=self._slide_px)
                else:
                    c2 = location_3d_to_region_2d(region, rv3d, center)
                    center2d = (c2.x, c2.y) if c2 is not None else _FAR_2D
                    pick = pick_element(verts3d, verts2d, mouse,
                                        poly_normal=poly_normal, poly_center=center,
                                        poly_center2d=center2d)
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

    # --- commit -------------------------------------------------------------

    def _commit(self, context):
        scene = context.scene
        data = self._pick
        if data is not None:
            pick, frame, _verts3d, _px, _tris = data
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
            if et in {"WHEELUPMOUSE", "WHEELDOWNMOUSE"}:
                self._edge_axis = cycle_edge_axis(self._normal_axis, self._edge_axis)
                self._update(context, event)
                return {"RUNNING_MODAL"}

        return {"RUNNING_MODAL"}


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
