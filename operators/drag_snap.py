import bpy
import numpy as np
from mathutils import Vector
from bpy_extras.view3d_utils import location_3d_to_region_2d

from ..ui.draw import primitives as draw, draw_scope, Role
from ..ui.draw import safe_handler_add, safe_handler_remove
from ..ui.draw.theme import get_theme
from ..ui.hud import (HUDOverlay, HelpOverlay, HUDSection, HUDItem,
                      HUDParam, ItemState,
                      handle_hud_toggle, handle_help_toggle, capture_event)
from ..utils.picking import (
    raycast_from_mouse,
    nearest_vertex_screen,
    SNAP_THRESHOLD_PX,
)


class IOPS_OT_DragSnap(bpy.types.Operator):
    """Quick drag & snap point to point"""

    bl_idname = "iops.object_drag_snap"
    bl_label = "IOPS Drag Snap"
    bl_options = {"REGISTER", "UNDO"}

    source = None, None
    target = None, None
    preview = None, None
    active = None
    lmb = False

    nearest = None, None

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

    def _build_hud(self, context):
        hud = HUDOverlay("drag_snap")
        hud.title = "Drag Snap"
        hud.bind_region(context.region)
        helpo = HelpOverlay("drag_snap")
        helpo.add_section(HUDSection("Drag Snap", [
            HUDItem("Pick source / snap target", "LMB",       ItemState.ON, default_state=ItemState.OFF, always_show=True),
            HUDItem("Copy distance to clipboard","Ctrl + LMB",ItemState.ON, default_state=ItemState.OFF, always_show=True),
            HUDItem("Cancel",                    "Esc / RMB", ItemState.ON, default_state=ItemState.OFF, always_show=True),
            HUDItem("Help / Toggle HUD", "H", ItemState.ON, default_state=ItemState.OFF, always_show=True),
        ]))
        helpo.bind_region(context.region)
        return hud, helpo

    def _draw_hud(self, context):
        helpo = getattr(self, "help", None)
        if helpo is not None:
            helpo.draw(context, getattr(self, "_last_event", None))
        if getattr(self, "hud", None) is None:
            return
        self.hud.draw(context, getattr(self, "_last_event", None))

    def _draw_snap_line(self, context):
        if not self.source[0] or not self.preview[0]:
            return
        with draw_scope(blend="ALPHA", depth="ALWAYS"):
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

    def get_vector_length(self, vector):
        return np.linalg.norm(vector)

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

    def update_distances(self, context, event):
        mouse_coord = (event.mouse_region_x, event.mouse_region_y)
        hit, _location, _normal, _face_idx, hit_obj, _matrix = raycast_from_mouse(
            context, mouse_coord)

        self.nearest = None, None
        if not hit or hit_obj is None or hit_obj.type != "MESH":
            return self.nearest

        idx, v_co3d = nearest_vertex_screen(
            context, hit_obj, mouse_coord, threshold_px=SNAP_THRESHOLD_PX)
        if idx is None or v_co3d is None:
            return self.nearest

        v_co2d = location_3d_to_region_2d(context.region, context.region_data, v_co3d)
        self.nearest = v_co3d, v_co2d
        return self.nearest

    def modal(self, context, event):
        context.area.tag_redraw()
        self._last_event = capture_event(event, getattr(self, "_last_event", None))
        try:
            theme_prefs = context.preferences.addons["InteractionOps"]\
                .preferences.iops_theme
        except (KeyError, AttributeError):
            theme_prefs = None
        if theme_prefs is not None:
            helpo = getattr(self, "_help", None) or getattr(self, "help", None)
            hud = getattr(self, "_hud", None) or getattr(self, "hud", None)
            if helpo is not None and helpo.handle_toggle_event(event, theme_prefs):
                return {'RUNNING_MODAL'}
            if hud is not None and hud.handle_param_toggle_event(event, theme_prefs):
                return {'RUNNING_MODAL'}
        if event.type in {"MIDDLEMOUSE", "WHEELUPMOUSE", "WHEELDOWNMOUSE"}:
            return {"PASS_THROUGH"}

        elif event.type == "MOUSEMOVE":
            self.update_distances(context, event)
            self.preview = self.nearest
            if self.source[0]:
                self.target = self.nearest

        elif event.type in {"LEFTMOUSE"} and event.value == "PRESS":
            if self.source[0]:
                if event.ctrl:
                    DISTANCE = self.get_vector_length(self.snap())
                    bpy.context.window_manager.clipboard = str(DISTANCE)
                    self.report({"INFO"}, "DISTANCE COPIED TO BUFFER: " + str(DISTANCE))
                    try:
                        self.clear_draw_handlers()
                    except ValueError:
                        pass
                    return {"FINISHED"}
                else:
                    self.target = self.nearest
                    self.execute(context)
                return {"FINISHED"}
            self.source = self.nearest
            self.lmb = True

        elif event.type in {"LEFTMOUSE"} and event.value == "RELEASE":
            if not self.source[0]:
                self.report({"WARNING"}, "WRONG SOURCE OR TARGET")
                self.clear_draw_handlers()
                return {"CANCELLED"}
            elif not self.target[0]:
                self.source = self.nearest
                self.report({"INFO"}, "Click target now...")
            else:
                self.execute(context)
                return {"FINISHED"}

        if event.type == "LEFTMOUSE":
            self.lmb = event.value == "PRESS"
            if self.lmb:
                self.source = self.nearest

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
        self.update_distances(context, event)
        self.lmb = False

        self.hud, self.help = self._build_hud(context)
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
