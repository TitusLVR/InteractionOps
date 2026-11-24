import bpy
from mathutils import Vector
from bpy_extras.view3d_utils import location_3d_to_region_2d

from ..ui.draw import primitives as draw, draw_scope, Role
from ..ui.draw import safe_handler_add, safe_handler_remove
from ..ui.hud import HUDOverlay, HUDParam, capture_event
from ..ui.hud.more import build_help
from ..utils.picking import (
    build_vertex_snap_cache,
    nearest_element_scene,
    face_center_under_mouse,
    SNAP_THRESHOLD_PX,
)


# Snap element per held modifier, checked in this order.
_MODE_LABELS = {
    "VERTEX": "Vertex",
    "EDGE": "Edge",
    "EDGE_MIDDLE": "Edge middle",
    "FACE_CENTER": "Face center",
}
_MODIFIER_KEYS = {"LEFT_SHIFT", "RIGHT_SHIFT", "LEFT_CTRL", "RIGHT_CTRL",
                  "LEFT_ALT", "RIGHT_ALT"}


def _mode_from_event(event):
    if event.ctrl:
        return "FACE_CENTER"
    if event.shift:
        return "EDGE"
    if event.alt:
        return "EDGE_MIDDLE"
    return "VERTEX"


class IOPS_OT_DragSnap(bpy.types.Operator):
    """Move the selection from one snap point to another: vertex, point on an
    edge (Shift), edge middle (Alt) or face center (Ctrl), chosen per click"""

    bl_idname = "iops.object_drag_snap"
    is_bindable = True
    bl_label = "IOPS Drag Snap"
    bl_options = {"REGISTER", "UNDO"}

    # (co_world, co_region) pairs
    source = None, None
    target = None, None
    preview = None, None
    nearest = None, None
    active = None
    lmb = False

    sd_handlers = []

    @classmethod
    def poll(cls, context):
        return (
            context.area.type == "VIEW_3D"
            and context.mode == "OBJECT"
            and len(context.view_layer.objects.selected) != 0
        )

    def clear_draw_handlers(self):
        for handler in self.sd_handlers:
            safe_handler_remove(handler, bpy.types.SpaceView3D, "WINDOW")

    # --- HUD -----------------------------------------------------------

    def _build_overlays(self, region):
        hud = self._hud = HUDOverlay("drag_snap")
        hud.title = "Drag Snap"
        hud.bind_region(region)
        hud.add_param(HUDParam("Action (C)", lambda: "Measure" if self._measure else "Move", "str"))
        hud.add_param(HUDParam("Snap To", lambda: _MODE_LABELS[self._mode], "str"))
        hud.add_param(HUDParam("Source", lambda: _MODE_LABELS.get(self._source_mode, "-"), "str",
                               visible_getter=lambda: self.source[0] is not None))
        hud.add_param(HUDParam("Distance", lambda: self._distance_label(), "str",
                               visible_getter=lambda: self.source[0] is not None
                               and self.preview[0] is not None))
        self._help = build_help("drag_snap", [
            ("Drag Snap", [
                ("Pick source / snap target (Confirm)", "LMB"),
                ("Point on edge", "Shift"),
                ("Face center", "Ctrl"),
                ("Edge middle", "Alt"),
                ("Measure: copy distance instead of moving", "C"),
                ("Cancel", "Esc / RMB"),
            ]),
        ], region)

    def _distance_label(self):
        if self.source[0] is None or self.preview[0] is None:
            return "-"
        return f"{(self.preview[0] - self.source[0]).length:.4f}"

    def _draw_hud(self, context):
        helpo = getattr(self, "_help", None)
        if helpo is not None:
            helpo.draw(context, getattr(self, "_last_event", None))
        if getattr(self, "_hud", None) is None:
            return
        self._hud.draw(context, getattr(self, "_last_event", None))

    # --- Viewport preview --------------------------------------------------

    def _draw_snap_line(self, context):
        with draw_scope(blend="ALPHA", depth="ALWAYS"):
            # the element the next click takes: an edge or a face outline
            shape = self._preview_shape
            if shape:
                pts = list(shape) + ([shape[0]] if len(shape) > 2 else [])
                for a, b in zip(pts, pts[1:]):
                    draw.line(a, b, role=Role.CLOSEST_LINE, context=context)
            shape = self._source_shape
            if shape and self.source[0] is not None:
                pts = list(shape) + ([shape[0]] if len(shape) > 2 else [])
                for a, b in zip(pts, pts[1:]):
                    draw.line(a, b, role=Role.LOCKED_LINE, context=context)
            if self.source[0] is not None and self.preview[0] is not None:
                draw.line(self.source[0], self.preview[0],
                          role=Role.PREVIEW_LINE, context=context)

    def _draw_snap_points(self, context):
        coords = []
        if self.source[0] is not None:
            coords.append(self.source[0])
        if self.preview[0] is not None:
            coords.append(self.preview[0])
        if not coords:
            return
        with draw_scope(blend="ALPHA", depth="ALWAYS"):
            draw.points(coords, role=Role.ACTIVE_POINT, context=context)

    # --- Snapping ----------------------------------------------------------

    def execute(self, context):
        if self.target[0] == self.source[0]:
            context.scene.cursor.location = self.target[0]
        else:
            bpy.ops.transform.translate(value=self.snap(), orient_type="GLOBAL")

        try:
            self.clear_draw_handlers()
        except ValueError:
            pass
        return {"FINISHED"}

    def snap(self):
        if not self.target[0]:
            return Vector((0, 0, 0))
        return self.target[0] - self.source[0]

    def update_distances(self, context, event=None):
        """Find the snap point under the mouse for the held modifier:
        a vertex, a point on an edge, an edge middle or a face center, on
        any visible object (instances and modifier geometry included)."""
        if event is not None:
            self._mouse = (event.mouse_region_x, event.mouse_region_y)
            self._mode = _mode_from_event(event)
        mouse_coord = self._mouse
        self.nearest = None, None
        self._nearest_shape = None
        cache = getattr(self, "_snap_cache", None)
        if cache is None:
            cache = self._snap_cache = build_vertex_snap_cache(context)

        if self._mode == "FACE_CENTER":
            co3d, shape = face_center_under_mouse(
                context, mouse_coord, owner_cache=cache.setdefault("owner_cache", {}))
        else:
            co3d, shape = nearest_element_scene(
                context, mouse_coord, cache=cache, element=self._mode,
                threshold_px=SNAP_THRESHOLD_PX)
        if co3d is None:
            return self.nearest

        co2d = location_3d_to_region_2d(context.region, context.region_data, co3d)
        self.nearest = co3d, co2d
        self._nearest_shape = shape
        return self.nearest

    def _take_preview(self):
        self.preview = self.nearest
        self._preview_shape = self._nearest_shape
        if self.source[0]:
            self.target = self.nearest

    def _set_source(self):
        self.source = self.nearest
        self._source_shape = self._nearest_shape
        self._source_mode = self._mode

    def _copy_distance(self):
        distance = (self.target[0] - self.source[0]).length
        bpy.context.window_manager.clipboard = str(distance)
        self.report({"INFO"}, f"Distance copied to clipboard: {distance}")

    def _toggle_measure(self):
        self._measure = not self._measure
        self.report({"INFO"}, "Drag Snap: measure (the target click copies the distance)"
                    if self._measure else "Drag Snap: move")

    def modal(self, context, event):
        context.area.tag_redraw()
        self._last_event = capture_event(event, getattr(self, "_last_event", None))
        try:
            theme_prefs = context.preferences.addons["InteractionOps"]\
                .preferences.iops_theme
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
        if event.type in {"MIDDLEMOUSE", "WHEELUPMOUSE", "WHEELDOWNMOUSE"}:
            return {"PASS_THROUGH"}

        if event.type == "MOUSEMOVE" or event.type in _MODIFIER_KEYS:
            # a modifier pressed or released switches the element at once
            self.update_distances(context, event)
            self._take_preview()

        elif event.type == "C" and event.value == "PRESS":
            self._toggle_measure()

        elif event.type == "LEFTMOUSE" and event.value == "PRESS":
            # the element is the one for the modifiers held at this click
            self.update_distances(context, event)
            self._take_preview()
            if self.source[0]:
                self.target = self.nearest
                if self.target[0] is None:
                    self.report({"WARNING"}, "No snap target under the mouse")
                    return {"RUNNING_MODAL"}
                if self._measure:
                    self._copy_distance()
                    self.clear_draw_handlers()
                    return {"FINISHED"}
                self.execute(context)
                return {"FINISHED"}
            self._set_source()
            self.lmb = True

        elif event.type == "LEFTMOUSE" and event.value == "RELEASE":
            self.lmb = False
            if not self.source[0]:
                self.report({"WARNING"}, "WRONG SOURCE OR TARGET")
                self.clear_draw_handlers()
                return {"CANCELLED"}
            if self.target[0] and self.target[0] != self.source[0]:
                # dragged from the source to a target and released there
                if self._measure:
                    self._copy_distance()
                    self.clear_draw_handlers()
                    return {"FINISHED"}
                self.execute(context)
                return {"FINISHED"}
            self.target = None, None
            self.report({"INFO"}, "Click target now...")

        elif event.type in {"RIGHTMOUSE", "ESC"}:
            self.clear_draw_handlers()
            self.report({"INFO"}, "Drag snap - cancelled")
            return {"CANCELLED"}

        return {"RUNNING_MODAL"}

    def invoke(self, context, event):
        self.report({"INFO"}, "Snap Drag started: Pick source")
        if context.space_data.type != "VIEW_3D":
            self.report({"WARNING"}, "Active space must be a View3d")
            return {"CANCELLED"}

        self.active = context.view_layer.objects.active
        self.source = self.target = self.preview = self.nearest = (None, None)
        self._mode = "VERTEX"
        self._measure = False
        self._source_mode = None
        self._nearest_shape = self._preview_shape = self._source_shape = None
        self._snap_cache = build_vertex_snap_cache(context)
        self.update_distances(context, event)
        self._take_preview()
        self.lmb = False

        self._build_overlays(context.region)
        self._last_event = capture_event(event, getattr(self, "_last_event", None))

        self.handle_snap_line = safe_handler_add(bpy.types.SpaceView3D,
            self._draw_snap_line, (context,), "WINDOW", "POST_VIEW", tick=True)
        self.handle_snap_points = safe_handler_add(bpy.types.SpaceView3D,
            self._draw_snap_points, (context,), "WINDOW", "POST_VIEW", tick=True)
        self.handle_iops_text = safe_handler_add(bpy.types.SpaceView3D,
            self._draw_hud, (context,), "WINDOW", "POST_PIXEL", tick=True)
        self.sd_handlers = [
            self.handle_snap_line,
            self.handle_snap_points,
            self.handle_iops_text,
        ]
        context.window_manager.modal_handler_add(self)
        return {"RUNNING_MODAL"}
