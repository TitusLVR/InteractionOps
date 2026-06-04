import bpy
import bmesh
import numpy as np
from mathutils import Vector

from ..ui.draw import primitives as draw, draw_scope, Role
from ..ui.draw import safe_handler_add, safe_handler_remove
from ..ui.draw.theme import get_theme
from ..ui.hud import (HUDOverlay, HelpOverlay, HUDSection, HUDItem,
                      HUDParam, ItemState,
                      handle_hud_toggle, handle_help_toggle, capture_event)
from ..utils.picking import build_uv_kdtree


class IOPS_OT_DragSnapUV(bpy.types.Operator):
    """Quick drag & snap uv to another uv"""

    bl_idname = "iops.uv_drag_snap_uv"
    is_bindable = True
    bl_label = "IOPS Drag Snap UV"
    bl_options = {"REGISTER", "UNDO"}

    source = None
    target = None
    preview = None
    active = None
    lmb = False

    nearest = None

    sd_handlers = []

    @classmethod
    def poll(cls, context):
        return (
            context.area is not None
            and context.area.type == "IMAGE_EDITOR"
            and context.active_object is not None
            and context.active_object.type == "MESH"
            and context.active_object.mode == "EDIT"
        )

    def clear_draw_handlers(self):
        for handler in self.sd_handlers:
            safe_handler_remove(handler, bpy.types.SpaceImageEditor, "WINDOW")

    def _build_hud(self, context):
        hud = HUDOverlay("drag_snap_uv")
        hud.title = "Drag Snap UV"
        hud.bind_region(context.region)
        helpo = HelpOverlay("drag_snap_uv")
        helpo.add_section(HUDSection("Drag Snap UV", [
            HUDItem("Move sel → 2D Cursor (highlighted)", "1",   ItemState.ON, default_state=ItemState.OFF, always_show=True),
            HUDItem("Move sel → 2D Cursor (nearest)",     "2",   ItemState.ON, default_state=ItemState.OFF, always_show=True),
            HUDItem("2D Cursor → Highlighted",            "4",   ItemState.ON, default_state=ItemState.OFF, always_show=True),
            HUDItem("Pick / Snap",                        "LMB", ItemState.ON, default_state=ItemState.OFF, always_show=True),
            HUDItem("Constrain X",                        "X",   ItemState.ON, default_state=ItemState.OFF, always_show=True),
            HUDItem("Constrain Y",                        "Y",   ItemState.ON, default_state=ItemState.OFF, always_show=True),
            HUDItem("Cancel",                             "Esc", ItemState.ON, default_state=ItemState.OFF, always_show=True),
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

    def _draw_snap_points(self, context):
        coords = []
        if self.source is not None:
            coords.append(context.region.view2d.view_to_region(
                self.source.x, self.source.y, clip=False))
        if self.preview is not None:
            coords.append(context.region.view2d.view_to_region(
                self.preview.x, self.preview.y, clip=False))
        if not coords:
            return
        with draw_scope(blend="ALPHA"):
            draw.points([Vector((c[0], c[1], 0.0)) for c in coords],
                        role=Role.ACTIVE_POINT, context=context)

    def _draw_snap_line(self, context):
        if not self.source or not self.target or self.preview is None:
            return
        start = context.region.view2d.view_to_region(
            self.source.x, self.source.y, clip=False)
        end = context.region.view2d.view_to_region(
            self.preview.x, self.preview.y, clip=False)
        with draw_scope(blend="ALPHA"):
            draw.line(Vector((start[0], start[1], 0.0)),
                      Vector((end[0], end[1], 0.0)),
                      role=Role.PREVIEW_LINE, context=context)

    def get_vector_length(self, vector):
        return np.linalg.norm(vector)

    def build_tree(self, context, type):
        """Build a UV KDTree via utils.picking.build_uv_kdtree.
        `type` is 'all' (include UV cursor as a snap target) or 'selected'."""
        cursor = None
        for area in bpy.context.screen.areas:
            if area.type == "IMAGE_EDITOR":
                cursor = area.spaces.active.cursor_location
                break
        bm = bmesh.from_edit_mesh(bpy.context.active_object.data)
        uv_layer = bm.loops.layers.uv.verify()
        extras = ((cursor.x, cursor.y),) if (type == "all" and cursor is not None) else ()
        return build_uv_kdtree(bm, uv_layer,
                               only_selected=(type == "selected"),
                               extras=extras)

    def execute(self, context):
        bpy.ops.transform.translate(
            value=self.snap(self.x, self.y), orient_type="GLOBAL"
        )
        try:
            self.clear_draw_handlers()
        except ValueError:
            pass
        return {"FINISHED"}

    def snap(self, x, y):
        if not self.target:
            return Vector((0, 0, 0))

        dir = self.target - self.source

        if x and y:
            return dir
        elif not x:
            return (0, dir[1], 0)
        elif not y:
            return (dir[0], 0, 0)

    def update_distances(self, context, event, kd):
        mouse_pos_uv = Vector(
            (
                context.region.view2d.region_to_view(
                    event.mouse_region_x, event.mouse_region_y
                )
            )
        )
        self.nearest = None
        nearest, _, _ = kd.find((mouse_pos_uv.x, mouse_pos_uv.y, 0))
        self.nearest = nearest
        return self.nearest

    def move_closest_to_cursor(self, context, kd):
        for area in bpy.context.screen.areas:
            if area.type == "IMAGE_EDITOR":
                cursor = area.spaces.active.cursor_location
        nearest, _, _ = kd.find((cursor.x, cursor.y, 0))

        if nearest:
            dx = cursor.x - nearest.x
            dy = cursor.y - nearest.y
            bpy.ops.transform.translate(value=(dx, dy, 0), orient_type="GLOBAL")
        else:
            self.report({"WARNING"}, "UVs are not selected?")

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

        elif event.type == "TWO" and event.value == "PRESS":
            self.move_closest_to_cursor(context, self.kd_selected)
            self.clear_draw_handlers()
            return {"FINISHED"}

        elif event.type == "FOUR" and event.value == "PRESS":
            for area in bpy.context.screen.areas:
                if area.type == "IMAGE_EDITOR":
                    cursor = area.spaces.active.cursor_location
            cursor.x, cursor.y = self.nearest.x, self.nearest.y
            self.clear_draw_handlers()
            return {"FINISHED"}

        elif event.type == "ONE" and event.value == "PRESS":
            for area in bpy.context.screen.areas:
                if area.type == "IMAGE_EDITOR":
                    cursor = area.spaces.active.cursor_location
            self.source = self.nearest
            self.target = Vector((*cursor, 0))
            self.execute(context)
            return {"FINISHED"}

        elif event.type == "MOUSEMOVE":
            self.update_distances(context, event, self.kd)
            self.preview = self.nearest
            if self.source:
                self.target = self.nearest

        elif event.type in {"LEFTMOUSE"} and event.value == "PRESS":
            if self.source:
                if event.ctrl:
                    DISTANCE = self.get_vector_length(self.snap(self.x, self.y))
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

        elif event.type == "X" and event.value == "PRESS":
            if self.source and self.target:
                self.y = False
                self.execute(context)
            else:
                try:
                    self.report({"WARNING"}, "Nothing to move")
                    self.clear_draw_handlers()
                except ValueError:
                    pass
            return {"FINISHED"}

        elif event.type == "Y" and event.value == "PRESS":
            if self.source and self.target:
                self.x = False
                self.execute(context)
            else:
                try:
                    self.report({"WARNING"}, "Nothing to move")
                    self.clear_draw_handlers()
                except ValueError:
                    pass
            return {"FINISHED"}

        elif event.type in {"LEFTMOUSE"} and event.value == "RELEASE":
            if not self.source:
                self.report({"WARNING"}, "WRONG SOURCE OR TARGET")
                self.clear_draw_handlers()
                return {"CANCELLED"}
            elif not self.target:
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

        self.kd = self.build_tree(context, type="all")
        self.kd_selected = self.build_tree(context, type="selected")

        self.x = True
        self.y = True

        if context.space_data.type != "IMAGE_EDITOR":
            self.report({"WARNING"}, "Active space must be an Image Editor")
            return {"CANCELLED"}

        self.active = context.view_layer.objects.active
        self.update_distances(context, event, self.kd)
        self.lmb = False

        self.hud, self.help = self._build_hud(context)
        self._last_event = capture_event(event, getattr(self, "_last_event", None))

        self.handle_snap_line = safe_handler_add(bpy.types.SpaceImageEditor,
            self._draw_snap_line, (context,), "WINDOW", "POST_PIXEL", tick=True)
        self.handle_snap_points = safe_handler_add(bpy.types.SpaceImageEditor,
            self._draw_snap_points, (context,), "WINDOW", "POST_PIXEL", tick=True)
        self.handle_iops_text = safe_handler_add(bpy.types.SpaceImageEditor,
            self._draw_hud, (context,), "WINDOW", "POST_PIXEL", tick=True)
        self.sd_handlers = [
            self.handle_snap_line,
            self.handle_snap_points,
            self.handle_iops_text,
        ]
        context.window_manager.modal_handler_add(self)
        return {"RUNNING_MODAL"}
