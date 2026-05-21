import bpy

from ..ui.draw import safe_handler_add, safe_handler_remove
from ..ui.draw.theme import get_theme
from ..ui.hud import (HUDOverlay, HelpOverlay, HUDSection, HUDItem,
                      HUDParam, ItemState,
                      handle_hud_toggle, handle_help_toggle, capture_event)


class IOPS_OT_DragSnapCursor(bpy.types.Operator):
    """Quick drag & snap using 3D Cursor"""

    bl_idname = "iops.object_drag_snap_cursor"
    bl_label = "IOPS Drag Snap Cursor"
    bl_description = (
        "Hold Q and LMB Click to quickly snap point to point using 3D Cursor"
    )
    bl_options = {"REGISTER", "UNDO"}

    step = 1
    count = 0
    old_type = None
    old_value = None

    def clear_draw_handlers(self):
        for handler in self.vp_handlers:
            safe_handler_remove(handler, bpy.types.SpaceView3D, "WINDOW")

    @classmethod
    def poll(cls, context):
        return (
            context.area.type == "VIEW_3D"
            and context.mode == "OBJECT"
            and len(context.view_layer.objects.selected) != 0
        )

    def _build_hud(self, context):
        hud = HUDOverlay("drag_snap_cursor")
        hud.title = "Drag Snap (Cursor)"
        hud.bind_region(context.region)
        return hud

    def _build_help(self, context):
        helpo = HelpOverlay("drag_snap_cursor")
        helpo.add_section(HUDSection("Drag Snap (Cursor)", [
            HUDItem("Place point",  "Q",   ItemState.ON, default_state=ItemState.OFF, always_show=True),
            HUDItem("Snap target",  "LMB", ItemState.ON, default_state=ItemState.OFF, always_show=True),
            HUDItem("Cancel",       "Esc", ItemState.ON, default_state=ItemState.OFF, always_show=True),
            HUDItem("Help / Toggle HUD", "H", ItemState.ON, default_state=ItemState.OFF, always_show=True),
        ]))
        helpo.bind_region(context.region)
        return helpo

    def _draw_hud(self, context):
        helpo = getattr(self, "_help", None)
        last_event = getattr(self, "_last_event", None)
        if helpo is not None:
            helpo.draw(context, last_event)
        if getattr(self, "hud", None) is not None:
            self.hud.draw(context, last_event)

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
            hud = getattr(self, "hud", None)
            if helpo is not None and helpo.handle_drag_event(context, event, theme_prefs):
                return {'RUNNING_MODAL'}
            if hud is not None and hud.handle_drag_event(context, event, theme_prefs):
                return {'RUNNING_MODAL'}
            if helpo is not None and helpo.handle_toggle_event(event, theme_prefs):
                return {'RUNNING_MODAL'}
            if hud is not None and hud.handle_param_toggle_event(event, theme_prefs):
                return {'RUNNING_MODAL'}

        if (
            event.type in {"MIDDLEMOUSE", "WHEELUPMOUSE", "WHEELDOWNMOUSE"}
            and event.value == "PRESS"
        ):
            return {"PASS_THROUGH"}
        elif event.type in {"ESC", "RIGHTMOUSE"} and event.value == "PRESS":
            try:
                self.clear_draw_handlers()
            except ValueError:
                pass
            return {"CANCELLED"}

        elif event.type == "Q" and event.value == "PRESS":
            bpy.ops.transform.translate(
                "INVOKE_DEFAULT",
                cursor_transform=True,
                use_snap_self=True,
                snap_target="CLOSEST",
                use_snap_nonedit=True,
                snap_elements={"VERTEX"},
                snap=True,
                release_confirm=True,
            )
            self.count += 1
            if self.count == 1:
                self.report({"INFO"}, "Step 2: Q to place cursor at point B")
            elif self.count == 2:
                bpy.context.scene.IOPS.dragsnap_point_a = (
                    bpy.context.scene.cursor.location
                )
                self.report({"INFO"}, "Step 3: press Q")
            elif self.count == 3:
                bpy.context.scene.IOPS.dragsnap_point_b = (
                    bpy.context.scene.cursor.location
                )
                vector = (
                    bpy.context.scene.IOPS.dragsnap_point_b
                    - bpy.context.scene.IOPS.dragsnap_point_a
                )
                bpy.ops.transform.translate(value=vector, orient_type="GLOBAL")
                try:
                    self.clear_draw_handlers()
                except ValueError:
                    pass
                return {"FINISHED"}

        return {"RUNNING_MODAL"}

    def invoke(self, context, event):
        if context.space_data.type != "VIEW_3D":
            self.report({"WARNING"}, "Active space must be a View3d")
            return {"CANCELLED"}

        self.hud = self._build_hud(context)
        self._help = self._build_help(context)
        self._last_event = capture_event(event, getattr(self, "_last_event", None))
        self._handle_iops_text = safe_handler_add(
            bpy.types.SpaceView3D, self._draw_hud, (context,), "WINDOW", "POST_PIXEL", tick=True)
        self.vp_handlers = [self._handle_iops_text]
        self.report({"INFO"}, "Step 1: Q to place cursor at point A")
        context.window_manager.modal_handler_add(self)
        return {"RUNNING_MODAL"}
