import bpy
from mathutils import Vector
from ..iops import IOPS_OT_Main

from ...ui.draw import primitives as draw, draw_scope, Role
from ...ui.draw.theme import get_theme
from ...ui.hud import HUDOverlay, HUDSection, HUDItem, ItemState, handle_hud_toggle


class IOPS_OT_CursorOrigin_Mesh(IOPS_OT_Main):
    bl_idname = "iops.cursor_origin_mesh"
    bl_label = "MESH: Object mode - Align to cursor"
    orig_mxs = []
    rotate = False
    flip = False
    target = None
    look_axis = []
    gpu_verts = []

    @classmethod
    def poll(self, context):
        return (
            context.area.type == "VIEW_3D"
            and context.mode == "OBJECT"
            and context.view_layer.objects.active.type in {"MESH", "LIGHT"}
            and context.view_layer.objects.selected[:] != []
        )

    def move_to_cursor(self, rotate):
        scene = bpy.context.scene
        objs = bpy.context.selected_objects
        for ob in objs:
            ob.location = scene.cursor.location
            if rotate:
                ob.rotation_euler = scene.cursor.rotation_euler

    def look_at(self, context, target, axis, flip):
        objs = bpy.context.selected_objects
        self.gpu_verts = []

        for o in objs:
            q = o.matrix_world.to_quaternion()
            m = q.to_matrix().to_4x4()
            o.matrix_world @= m.inverted()

            self.gpu_verts.append(o.location)
            self.gpu_verts.append(target.location)

            v = Vector(o.location - target.location)
            if flip:
                rot_mx = v.to_track_quat("-" + axis[0], axis[1]).to_matrix().to_4x4()
            else:
                rot_mx = v.to_track_quat(axis[0], axis[1]).to_matrix().to_4x4()
            o.matrix_world @= rot_mx

    def _target_name(self, context):
        if self.target == context.scene.cursor:
            return "3D Cursor"
        elif self.target == context.view_layer.objects.active:
            return "Active object"
        return "?"

    def _build_hud(self, context):
        hud = HUDOverlay("cursor_origin_mesh",
                         verbosity=get_theme(context).hud.verbosity)
        hud.add_section(HUDSection("Cursor / Origin", [
            HUDItem("Look at: Cursor",          "F1", ItemState.ON, default_state=ItemState.OFF, always_show=True),
            HUDItem("Look at: Active object",   "F2", ItemState.ON, default_state=ItemState.OFF, always_show=True),
            HUDItem("Align to cursor pos",      "F3", ItemState.ON if self.rotate else ItemState.OFF),
            HUDItem("Visual origin helper",     "F4", ItemState.ON, default_state=ItemState.OFF, always_show=True),
            HUDItem("Axis X",                   "X",  ItemState.ON, default_state=ItemState.OFF, always_show=True),
            HUDItem("Axis Y",                   "Y",  ItemState.ON, default_state=ItemState.OFF, always_show=True),
            HUDItem("Axis Z",                   "Z",  ItemState.ON, default_state=ItemState.OFF, always_show=True),
            HUDItem("Confirm",                  "LMB / Space", ItemState.ON, default_state=ItemState.OFF, always_show=True),
            HUDItem("Cancel",                   "Esc / RMB",   ItemState.ON, default_state=ItemState.OFF, always_show=True),
            HUDItem("Help / Toggle HUD", "H", ItemState.ON, default_state=ItemState.OFF, always_show=True),
        ]))
        hud.bind_region(context.region)
        return hud

    def _draw_hud(self, context):
        hud = getattr(self, "_hud", None)
        if hud is None:
            return
        hud.set_state("F3", ItemState.ON if self.rotate else ItemState.OFF)
        hud.set_header(
            f"Target: {self._target_name(context)}  Axis: {self.look_axis[0]}"
        )
        hud.draw(context, getattr(self, "_last_event", None))

    def _draw_line(self, context):
        if not self.gpu_verts:
            return
        with draw_scope(blend="ALPHA", depth="ALWAYS"):
            draw.edges_3d(list(self.gpu_verts),
                          role=Role.ACTIVE_LINE, context=context)

    def modal(self, context, event):
        context.area.tag_redraw()
        self._last_event = event
        if handle_hud_toggle(getattr(self, "_hud", None) or getattr(self, "hud", None), context, event):
            return {'RUNNING_MODAL'}
        objs = context.selected_objects

        if event.type in {"MIDDLEMOUSE"}:
            return {"PASS_THROUGH"}

        elif event.type == "F4" and event.value == "PRESS":
            bpy.ops.iops.object_visual_origin("INVOKE_DEFAULT")
            bpy.types.SpaceView3D.draw_handler_remove(self._handle_cursor, "WINDOW")
            bpy.types.SpaceView3D.draw_handler_remove(self._handle_ui, "WINDOW")
            return {"FINISHED"}

        elif event.type == "F1" and event.value == "PRESS":
            self.flip = not self.flip
            self.target = context.scene.cursor
            self.look_at(context, self.target, self.look_axis, self.flip)

        elif event.type == "F2" and event.value == "PRESS":
            self.flip = not self.flip
            self.target = context.view_layer.objects.active
            self.look_at(context, self.target, self.look_axis, self.flip)

        elif event.type == "X" and event.value == "PRESS":
            self.flip = not self.flip
            self.look_axis = [("X"), ("Z")]
            self.look_at(context, self.target, self.look_axis, self.flip)

        elif event.type == "Y" and event.value == "PRESS":
            self.flip = not self.flip
            self.look_axis = [("Y"), ("X")]
            self.look_at(context, self.target, self.look_axis, self.flip)

        elif event.type == "Z" and event.value == "PRESS":
            self.flip = not self.flip
            self.look_axis = [("Z"), ("Y")]
            self.look_at(context, self.target, self.look_axis, self.flip)

        elif event.type == "F3" and event.value == "PRESS":
            for o, m in zip(objs, self.orig_mxs):
                o.matrix_world = m
            self.rotate = not self.rotate
            self.move_to_cursor(self.rotate)

        elif event.type in {"LEFTMOUSE", "SPACE"} and event.value == "PRESS":
            bpy.types.SpaceView3D.draw_handler_remove(self._handle_cursor, "WINDOW")
            bpy.types.SpaceView3D.draw_handler_remove(self._handle_ui, "WINDOW")
            return {"FINISHED"}

        elif event.type in {"RIGHTMOUSE", "ESC"}:
            for o, m in zip(objs, self.orig_mxs):
                o.matrix_world = m
            self.orig_mxs = []

            bpy.types.SpaceView3D.draw_handler_remove(self._handle_cursor, "WINDOW")
            bpy.types.SpaceView3D.draw_handler_remove(self._handle_ui, "WINDOW")
            return {"CANCELLED"}

        return {"RUNNING_MODAL"}

    def invoke(self, context, event):
        self.orig_mxs = []
        self.gpu_verts = []
        self.look_axis = [("Z"), ("Y")]
        self.target = context.scene.cursor
        objs = context.selected_objects
        for o in objs:
            self.orig_mxs.append(o.matrix_world.copy())

        if not (context.object and context.area.type == "VIEW_3D"):
            self.report({"WARNING"}, "No active object, could not finish")
            return {"CANCELLED"}

        self._hud = self._build_hud(context)
        self._last_event = event
        self._handle_ui = bpy.types.SpaceView3D.draw_handler_add(
            self._draw_hud, (context,), "WINDOW", "POST_PIXEL"
        )
        self._handle_cursor = bpy.types.SpaceView3D.draw_handler_add(
            self._draw_line, (context,), "WINDOW", "POST_VIEW"
        )
        context.window_manager.modal_handler_add(self)
        return {"RUNNING_MODAL"}
