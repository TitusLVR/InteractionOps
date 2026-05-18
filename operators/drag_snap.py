import bpy
import numpy as np
from mathutils import Vector
from bpy_extras import view3d_utils
from bpy_extras.view3d_utils import location_3d_to_region_2d

from ..ui.draw import primitives as draw, draw_scope, Role
from ..ui.draw.theme import get_theme
from ..ui.hud import HUDOverlay, HUDSection, HUDItem, ItemState


SNAP_DIST_SQ = 30**2  # Pixels Squared Tolerance


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
            bpy.types.SpaceView3D.draw_handler_remove(handler, "WINDOW")

    def _build_hud(self, context):
        verbosity = get_theme(context).hud.verbosity
        hud = HUDOverlay("drag_snap", verbosity=verbosity)
        hud.add_section(HUDSection("Drag Snap", [
            HUDItem("Pick source / snap target", "LMB",       ItemState.ON, default_state=ItemState.OFF, always_show=True),
            HUDItem("Copy distance to clipboard","Ctrl + LMB",ItemState.ON, default_state=ItemState.OFF, always_show=True),
            HUDItem("Cancel",                    "Esc / RMB", ItemState.ON, default_state=ItemState.OFF, always_show=True),
        ]))
        hud.bind_region(context.region)
        return hud

    def _draw_hud(self, context):
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
        scene = context.scene
        region = context.region
        mouse_pos = Vector((event.mouse_region_x, event.mouse_region_y))
        rv3d = context.region_data
        view_vector = view3d_utils.region_2d_to_vector_3d(region, rv3d, mouse_pos)
        ray_origin = view3d_utils.region_2d_to_origin_3d(region, rv3d, mouse_pos)
        depsgraph = context.evaluated_depsgraph_get()

        hit, _, _, _, hit_obj, _ = scene.ray_cast(
            depsgraph, ray_origin, view_vector, distance=1.70141e38
        )

        self.nearest = None, None
        min_dist = float("inf")

        if hit and hit_obj.type is not None:
            for v in hit_obj.data.vertices:
                v_co3d = hit_obj.matrix_world @ v.co
                v_co2d = location_3d_to_region_2d(context.region, rv3d, v_co3d)

                if v_co2d is not None:
                    d_squared = (mouse_pos - v_co2d).length_squared
                    if d_squared > SNAP_DIST_SQ:
                        continue
                    if d_squared < min_dist:
                        min_dist = d_squared
                        self.nearest = v_co3d, v_co2d

        return self.nearest

    def modal(self, context, event):
        context.area.tag_redraw()
        self._last_event = event
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

        self.hud = self._build_hud(context)
        self._last_event = event

        self.handle_snap_line = bpy.types.SpaceView3D.draw_handler_add(
            self._draw_snap_line, (context,), "WINDOW", "POST_VIEW"
        )
        self.handle_snap_points = bpy.types.SpaceView3D.draw_handler_add(
            self._draw_snap_points, (context,), "WINDOW", "POST_VIEW"
        )
        self.handle_iops_text = bpy.types.SpaceView3D.draw_handler_add(
            self._draw_hud, (context,), "WINDOW", "POST_PIXEL"
        )
        self.sd_handlers = [
            self.handle_snap_line,
            self.handle_snap_points,
            self.handle_iops_text,
        ]
        context.window_manager.modal_handler_add(self)
        return {"RUNNING_MODAL"}
