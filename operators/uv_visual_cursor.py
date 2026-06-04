import bpy
import bmesh
import math
from mathutils import Vector

from ..ui.draw import primitives as draw, draw_scope, Role
from ..ui.draw import safe_handler_add, safe_handler_remove
from ..ui.hud import (HUDOverlay, HelpOverlay, HUDSection, HUDItem,
                      ItemState, capture_event)


# Cage corner indices into the 9-point list (corners are points 0..3).
_CAGE_LOOP = (0, 1, 2, 3, 0)


def _bbox_snap_points(mn, mx):
    """9 UV-space snap points from a bbox (mn, mx are 2D Vectors).

    Order: 4 corners (0..3), 4 edge midpoints (4..7), center (8).
    """
    cx = (mn.x + mx.x) * 0.5
    cy = (mn.y + mx.y) * 0.5
    return [
        Vector((mn.x, mn.y)),   # 0 corner BL
        Vector((mx.x, mn.y)),   # 1 corner BR
        Vector((mx.x, mx.y)),   # 2 corner TR
        Vector((mn.x, mx.y)),   # 3 corner TL
        Vector((cx, mn.y)),     # 4 edge mid bottom
        Vector((mx.x, cy)),     # 5 edge mid right
        Vector((cx, mx.y)),     # 6 edge mid top
        Vector((mn.x, cy)),     # 7 edge mid left
        Vector((cx, cy)),       # 8 center
    ]


def _tile_bbox(uv):
    """(mn, mx) of the unit UDIM tile containing UV position `uv`."""
    mnx = math.floor(uv.x)
    mny = math.floor(uv.y)
    return Vector((mnx, mny)), Vector((mnx + 1.0, mny + 1.0))


def _selection_bbox(context):
    """Min/max of selected UV verts on the active mesh, or None if none.

    Reads selection via the Blender-5.0+ `loop.uv_select_vert` with a
    fallback to `loop[uv_layer].select` — same idiom as
    `utils.picking.build_uv_kdtree`.
    """
    obj = context.active_object
    bm = bmesh.from_edit_mesh(obj.data)
    uv_layer = bm.loops.layers.uv.verify()
    mn = None
    mx = None
    for face in bm.faces:
        for loop in face.loops:
            sel = getattr(loop, "uv_select_vert", None)
            if sel is None:
                sel = loop[uv_layer].select
            if not sel:
                continue
            uv = loop[uv_layer].uv
            if mn is None:
                mn = Vector((uv.x, uv.y))
                mx = Vector((uv.x, uv.y))
            else:
                if uv.x < mn.x: mn.x = uv.x
                if uv.y < mn.y: mn.y = uv.y
                if uv.x > mx.x: mx.x = uv.x
                if uv.y > mx.y: mx.y = uv.y
    if mn is None:
        return None
    return mn, mx


class IOPS_OT_VisualCursorUV(bpy.types.Operator):
    """Visual 2D-cursor placement: pick a bbox/tile snap point in the UV editor"""

    bl_idname = "iops.uv_visual_cursor"
    bl_label = "IOPS Visual Cursor UV"
    bl_options = {"REGISTER", "UNDO"}
    is_bindable = True  # opt into the IOPS prefs Keymaps list (unbound by default)

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

    # --- HUD -----------------------------------------------------------
    def _build_hud(self, context):
        hud = HUDOverlay("uv_visual_cursor")
        hud.title = "Visual Cursor UV"
        hud.bind_region(context.region)
        helpo = HelpOverlay("uv_visual_cursor")
        helpo.add_section(HUDSection("Visual Cursor UV", [
            HUDItem("Set 2D cursor to highlighted", "LMB/Space", ItemState.ON, default_state=ItemState.OFF, always_show=True),
            HUDItem("Tile mode (hover tile)",       "Hold Alt",  ItemState.ON, default_state=ItemState.OFF, always_show=True),
            HUDItem("Cancel",                       "Esc/RMB",   ItemState.ON, default_state=ItemState.OFF, always_show=True),
            HUDItem("Help / Toggle HUD",            "H",         ItemState.ON, default_state=ItemState.OFF, always_show=True),
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

    # --- Geometry / picking -------------------------------------------
    def _update(self, context, event):
        """Recompute the cage (selection or tile bbox) and the nearest point."""
        v2d = context.region.view2d
        mx_px, my_px = self.mouse_pos
        u, v = v2d.region_to_view(mx_px, my_px)
        mouse_uv = Vector((u, v))

        tile = bool(event.alt) or (self.sel_min is None)
        self.tile_mode = tile
        if tile:
            mn, mx = _tile_bbox(mouse_uv)
        else:
            mn, mx = self.sel_min, self.sel_max
        self.pos_batch_uv = _bbox_snap_points(mn, mx)
        self._pick_nearest(context)

    def _pick_nearest(self, context):
        if not self.pos_batch_uv:
            self.nearest = None
            return
        v2d = context.region.view2d
        mv = Vector(self.mouse_pos)
        best_i = 0
        best_d = float("inf")
        for i, p in enumerate(self.pos_batch_uv):
            rx, ry = v2d.view_to_region(p.x, p.y, clip=False)
            d = (Vector((rx, ry)) - mv).length_squared
            if d < best_d:
                best_d = d
                best_i = i
        self.nearest_idx = best_i
        self.nearest = self.pos_batch_uv[best_i]

    # --- Draw handlers (region coords, POST_PIXEL) --------------------
    def _region_pt(self, context, uv):
        rx, ry = context.region.view2d.view_to_region(uv.x, uv.y, clip=False)
        return Vector((rx, ry, 0.0))

    def _draw_cage_lines(self, context):
        if not self.pos_batch_uv:
            return
        corners = [self._region_pt(context, self.pos_batch_uv[i]) for i in _CAGE_LOOP]
        with draw_scope(blend="ALPHA"):
            draw.polyline(corners, role=Role.BBOX, context=context)

    def _draw_cage_points(self, context):
        if not self.pos_batch_uv:
            return
        coords = [self._region_pt(context, p) for p in self.pos_batch_uv]
        with draw_scope(blend="ALPHA"):
            draw.points(coords, role=Role.POINT, context=context)

    def _draw_active_point(self, context):
        if self.nearest is None:
            return
        with draw_scope(blend="ALPHA"):
            draw.points([self._region_pt(context, self.nearest)],
                        role=Role.CLOSEST_POINT, context=context)

    # --- Lifecycle -----------------------------------------------------
    def clear_draw_handlers(self):
        for handler in self.sd_handlers:
            safe_handler_remove(handler, bpy.types.SpaceImageEditor, "WINDOW")

    def _set_cursor(self, context):
        space = context.space_data
        if space is None or space.type != "IMAGE_EDITOR":
            space = context.area.spaces.active
        space.cursor_location = (self.nearest.x, self.nearest.y)

    def modal(self, context, event):
        context.area.tag_redraw()
        self._last_event = capture_event(event, getattr(self, "_last_event", None))

        # Standard HUD/Help drag + toggle handling (copied from drag_snap_uv).
        try:
            theme_prefs = context.preferences.addons["InteractionOps"]\
                .preferences.iops_theme
        except (KeyError, AttributeError):
            theme_prefs = None
        if theme_prefs is not None:
            helpo = getattr(self, "help", None)
            hud = getattr(self, "hud", None)
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

        self.mouse_pos = (event.mouse_region_x, event.mouse_region_y)
        self._update(context, event)

        if event.type in {"LEFTMOUSE", "SPACE"} and event.value == "PRESS":
            if self.nearest is not None:
                self._set_cursor(context)
            self.clear_draw_handlers()
            return {"FINISHED"}

        elif event.type in {"RIGHTMOUSE", "ESC"} and event.value == "PRESS":
            self.clear_draw_handlers()
            self.report({"INFO"}, "Visual Cursor UV - cancelled")
            return {"CANCELLED"}

        return {"RUNNING_MODAL"}

    def invoke(self, context, event):
        if context.space_data.type != "IMAGE_EDITOR":
            self.report({"WARNING"}, "Active space must be an Image Editor")
            return {"CANCELLED"}

        sb = _selection_bbox(context)
        if sb is None:
            self.sel_min = None
            self.sel_max = None
            self.report({"INFO"}, "No UV selection - tile mode")
        else:
            self.sel_min, self.sel_max = sb

        self.tile_mode = False
        self.pos_batch_uv = []
        self.nearest = None
        self.nearest_idx = 0
        self.mouse_pos = (event.mouse_region_x, event.mouse_region_y)
        self._update(context, event)

        self.hud, self.help = self._build_hud(context)
        self._last_event = capture_event(event, None)

        h_lines = safe_handler_add(bpy.types.SpaceImageEditor,
            self._draw_cage_lines, (context,), "WINDOW", "POST_PIXEL", tick=True)
        h_points = safe_handler_add(bpy.types.SpaceImageEditor,
            self._draw_cage_points, (context,), "WINDOW", "POST_PIXEL", tick=True)
        h_active = safe_handler_add(bpy.types.SpaceImageEditor,
            self._draw_active_point, (context,), "WINDOW", "POST_PIXEL", tick=True)
        h_hud = safe_handler_add(bpy.types.SpaceImageEditor,
            self._draw_hud, (context,), "WINDOW", "POST_PIXEL", tick=True)
        self.sd_handlers = [h_lines, h_points, h_active, h_hud]

        context.window_manager.modal_handler_add(self)
        return {"RUNNING_MODAL"}
