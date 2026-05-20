"""IOPS_OT_DrawThemePreview — modal preview of all theme primitives + HUD.

Run from preferences "Theme" tab. Renders one of each primitive in the
viewport plus a sample HUD (live params near cursor) and a sample Help
overlay (corner). ESC or right-click to exit.

Implementation note: draw handlers receive a plain `state` dict, not the
operator instance. This avoids `ReferenceError: StructRNA ... has been
removed` when the operator is destroyed (addon reload, exceptions during
invoke, unusual exit paths) while Blender still holds the draw handler.
"""
import bpy

from ..ui.draw import (primitives as draw, draw_scope, Role,
                       safe_handler_add, safe_handler_remove)


# Module-level registry of live preview installs. We need this so the
# addon's unregister() can tear down handlers + timer when the user
# reloads while a preview is still running — otherwise the draw handlers
# stay subscribed to a stale module and keep firing into a dead state.
_LIVE_INSTALLS: list[dict] = []


def cleanup_live_installs():
    """Force-remove any preview draw handlers and timers. Idempotent.
    Called from the addon's unregister()."""
    while _LIVE_INSTALLS:
        entry = _LIVE_INSTALLS.pop()
        state = entry.get("state")
        if state is not None:
            state["dead"] = True
        safe_handler_remove(entry.get("h_view"),
                            bpy.types.SpaceView3D, "WINDOW")
        safe_handler_remove(entry.get("h_px"),
                            bpy.types.SpaceView3D, "WINDOW")
        timer = entry.get("timer")
        if timer is not None:
            try:
                bpy.context.window_manager.event_timer_remove(timer)
            except Exception:
                pass
    IOPS_OT_DrawThemePreview.is_running = False
    IOPS_OT_DrawThemePreview._stop_requested = False
from ..ui.hud import (HUDOverlay, HelpOverlay, HUDSection, HUDItem,
                      HUDParam, ItemState)


_STATE_LABELS = ("Default", "Closest", "Active", "Locked",
                 "Result Preview", "Error")
_POINT_ROLES = (Role.POINT, Role.CLOSEST_POINT, Role.ACTIVE_POINT,
                Role.LOCKED_POINT, Role.PREVIEW_POINT, Role.ERROR_POINT)
_LINE_ROLES = (Role.LINE, Role.CLOSEST_LINE, Role.ACTIVE_LINE,
               Role.LOCKED_LINE, Role.PREVIEW_LINE, Role.ERROR_LINE)
_TEXT_ROLES = (Role.TEXT, Role.CLOSEST_TEXT, Role.ACTIVE_TEXT,
               Role.LOCKED_TEXT, Role.PREVIEW_TEXT, Role.ERROR_TEXT)
_TEXT_SIZE_TOKENS = ("default", "closest", "active", "locked",
                     "preview", "error")


def _draw_view(state):
    if state.get("dead"):
        return
    # Resolve the theme freshly each frame against the current context —
    # otherwise the primitives' default `_resolve_theme(None, None)` path
    # falls back to `DEFAULT_THEME` and the preview ignores live edits to
    # colors / point sizes / line widths in the prefs.
    from ..ui.draw.theme import get_theme
    th = get_theme(bpy.context)
    with draw_scope(blend="ALPHA", depth="ALWAYS"):
        # 5-state point row.
        for pt, role in zip(state["pts_row"], _POINT_ROLES):
            draw.points([pt], role=role, theme=th)
        # 5-state line column.
        pairs = state["line_pairs"]
        for i, role in enumerate(_LINE_ROLES):
            draw.edges_3d(pairs[i*2:i*2+2], role=role, theme=th)
        draw.polyline(state["preview_polyline"], role=Role.PREVIEW_LINE,
                      theme=th)
        # Extras row: handles / pivot / cursor + a bbox frame around them.
        draw.points([state["handle_pt"]],       role=Role.HANDLE,       theme=th)
        draw.points([state["handle_hover_pt"]], role=Role.HANDLE_HOVER, theme=th)
        draw.points([state["pivot_pt"]],        role=Role.PIVOT,        theme=th)
        draw.points([state["cursor_pt"]],       role=Role.CURSOR,       theme=th)
        draw.edges_3d(state["bbox_edges"],      role=Role.BBOX,         theme=th)
        # Island palette: 8 translucent quads, one per slot.
        for i, quad_tris in enumerate(state["island_quads"]):
            draw.tris(quad_tris, color=th.island_palette[i], theme=th)


class _EventSnapshot:
    """Minimal stand-in for `bpy.types.Event`. Blender invalidates the live
    event object once `modal()` returns, so reading `event.mouse_x` from a
    POST_PIXEL handler that fires later gives garbage (we've seen 1e6+).
    The modal copies the few fields the HUD reads into one of these each
    frame and the draw handler uses the snapshot instead."""
    __slots__ = ("mouse_x", "mouse_y", "mouse_region_x", "mouse_region_y",
                 "shift", "ctrl", "alt", "oskey", "type", "value")

    def __init__(self):
        self.mouse_x = 0
        self.mouse_y = 0
        self.mouse_region_x = 0
        self.mouse_region_y = 0
        self.shift = False
        self.ctrl = False
        self.alt = False
        self.oskey = False
        self.type = ""
        self.value = ""

    def update(self, event, *, modal_window, target_window, region):
        # Modal events always arrive in the invoke window's coord system
        # (here: the prefs popup). Translate through screen coords into
        # the target viewport's window, then subtract region.x/y to get
        # region-relative coords usable by the HUD's cursor-follow.
        if modal_window is not None and target_window is not None:
            screen_x = modal_window.x + event.mouse_x
            screen_y = modal_window.y + event.mouse_y
            tx = screen_x - target_window.x
            ty = screen_y - target_window.y
            self.mouse_x = tx
            self.mouse_y = ty
            self.mouse_region_x = tx - region.x
            self.mouse_region_y = ty - region.y
        else:
            self.mouse_x = event.mouse_x
            self.mouse_y = event.mouse_y
            self.mouse_region_x = event.mouse_region_x
            self.mouse_region_y = event.mouse_region_y
        self.shift = bool(event.shift)
        self.ctrl = bool(event.ctrl)
        self.alt = bool(event.alt)
        self.oskey = bool(event.oskey)
        self.type = event.type
        self.value = event.value


def _draw_px(state):
    """POST_PIXEL handler. Uses bpy.context — NOT a captured context —
    because the operator is launched from the Preferences area, so the
    invoke-time context.region points to the prefs region, not the 3D
    viewport region Blender is currently drawing."""
    if state.get("dead"):
        return
    ctx = bpy.context
    snap = state.get("event_snap")
    _draw_state_labels(ctx, state)
    state["hud"].draw(ctx, snap)
    state["help"].draw(ctx, snap)


def _draw_state_labels(context, state):
    """Project the column anchor points and draw state names above them.
    Each label is rendered in the per-state text role + per-state size."""
    region = context.region
    rv3d = context.region_data
    if region is None or rv3d is None:
        return
    from bpy_extras import view3d_utils
    from ..ui.draw.theme import get_theme
    from ..ui.hud import text as hud_text
    theme = get_theme(context)
    for pt, role, size_token, label in zip(state["pts_row"], _TEXT_ROLES,
                                            _TEXT_SIZE_TOKENS, _STATE_LABELS):
        scr = view3d_utils.location_3d_to_region_2d(region, rv3d, pt)
        if scr is None:
            continue
        w, h = hud_text.measure(label, theme=theme, size_token=size_token)
        hud_text.draw(label, int(scr.x - w * 0.5), int(scr.y + 18),
                      theme=theme, role=role, size_token=size_token)


class IOPS_OT_DrawThemePreview(bpy.types.Operator):
    bl_idname = "iops.draw_theme_preview"
    bl_label = "Preview Theme"
    bl_description = "Modal preview of all unified UI primitives"
    bl_options = {"REGISTER"}

    # Class-level coordination with IOPS_OT_StopThemePreview so the
    # Theme tab can flip the button between "Preview" and "Stop" and
    # request an exit from outside the modal.
    is_running: bool = False
    _stop_requested: bool = False

    @staticmethod
    def _find_viewport(context):
        """Return (area, region, window) for the biggest open 3D viewport,
        or (None, None, None) if there isn't one."""
        target_area = None
        target_region = None
        target_window = None
        biggest = 0
        for win in context.window_manager.windows:
            for area in win.screen.areas:
                if area.type != "VIEW_3D":
                    continue
                size = area.width * area.height
                if size <= biggest:
                    continue
                rgn = next((r for r in area.regions if r.type == "WINDOW"),
                           None)
                if rgn is None:
                    continue
                target_area = area
                target_region = rgn
                target_window = win
                biggest = size
        return target_area, target_region, target_window

    def invoke(self, context, event):
        # Launched from the Preferences "Theme" button → `context.area`
        # is USER_PREFERENCES, events would come from the prefs window
        # and cursor-follow couldn't work natively. Find a 3D viewport,
        # re-invoke ourselves under its context, and let the modal run
        # there. The re-invoked instance hits this same `invoke` with
        # `context.area.type == "VIEW_3D"` and falls through to the
        # normal modal setup below.
        if context.area is None or context.area.type != "VIEW_3D":
            area, region, window = self._find_viewport(context)
            if window is None:
                self.report({"ERROR"}, "No 3D viewport open — open one and try again")
                return {"CANCELLED"}
            with context.temp_override(window=window, area=area, region=region):
                bpy.ops.iops.draw_theme_preview('INVOKE_DEFAULT')
            return {"FINISHED"}

        target_area = context.area
        target_region = context.region
        target_window = context.window

        self._target_region_ptr = target_region.as_pointer()
        self._target_window_ptr = target_window.as_pointer()
        self._target_region = target_region
        self._state = {
            "dead": False,
            "event_snap": _EventSnapshot(),
            "snap_on": False,
            "subdivisions": 2,
            "offset": 0.25,
            "target_region_ptr": target_region.as_pointer(),
            "target_window_ptr": self._target_window_ptr,
        }
        try:
            self._build_geometry(target_area, self._state)
            self._state["hud"] = self._build_hud(self._state)
            self._state["hud"].bind_region(target_region)
            self._state["help"] = self._build_help(target_region)
            self._h_view = safe_handler_add(
                bpy.types.SpaceView3D,
                _draw_view, (self._state,), "WINDOW", "POST_VIEW")
            self._h_px = safe_handler_add(
                bpy.types.SpaceView3D,
                _draw_px, (self._state,), "WINDOW", "POST_PIXEL")
            # ~60 fps timer keeps the modal alive even when the cursor is
            # idle — needed so HelpOverlay animations keep ticking and
            # don't stall between mouse events.
            self._timer = context.window_manager.event_timer_add(
                1.0 / 60.0, window=target_window)
            context.window_manager.modal_handler_add(self)
            target_area.tag_redraw()
            self._install_entry = {
                "state": self._state,
                "h_view": self._h_view,
                "h_px": self._h_px,
                "timer": self._timer,
            }
            _LIVE_INSTALLS.append(self._install_entry)
            type(self).is_running = True
            type(self)._stop_requested = False
        except Exception:
            self._cleanup()
            raise
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        # Snapshot event values now — the live event object is invalid as
        # soon as this function returns, so the draw handler can't read it.
        target_window = None
        for win in context.window_manager.windows:
            if win.as_pointer() == self._target_window_ptr:
                target_window = win
                break
        self._state["event_snap"].update(
            event,
            modal_window=context.window,
            target_window=target_window,
            region=self._target_region)
        # tag the 3D viewport (not whatever area received the modal event)
        for win in context.window_manager.windows:
            for area in win.screen.areas:
                if area.type == "VIEW_3D":
                    area.tag_redraw()
        try:
            theme_prefs = context.preferences.addons["InteractionOps"]\
                .preferences.iops_theme
        except (KeyError, AttributeError):
            theme_prefs = None

        if (event.type in {"ESC", "RIGHTMOUSE"} and event.value == "PRESS"
                or type(self)._stop_requested):
            self._cleanup()
            return {"FINISHED"}

        hud = self._state["hud"]
        helpo = self._state["help"]

        if theme_prefs is not None:
            if hud.handle_param_toggle_event(event, theme_prefs):
                return {"RUNNING_MODAL"}
            if helpo.handle_toggle_event(event, theme_prefs):
                return {"RUNNING_MODAL"}

        if event.value == "PRESS":
            if event.type == "S":
                self._state["snap_on"] = not self._state["snap_on"]
                hud.set_state(
                    "S",
                    ItemState.ON if self._state["snap_on"] else ItemState.OFF)
            elif event.type in {"WHEELUPMOUSE", "EQUAL", "PLUS"}:
                self._state["subdivisions"] = min(
                    20, self._state["subdivisions"] + 1)
            elif event.type in {"WHEELDOWNMOUSE", "MINUS"}:
                self._state["subdivisions"] = max(
                    0, self._state["subdivisions"] - 1)

        return {"PASS_THROUGH"}

    def _cleanup(self):
        if getattr(self, "_state", None) is not None:
            self._state["dead"] = True
        safe_handler_remove(getattr(self, "_h_view", None),
                            bpy.types.SpaceView3D, "WINDOW")
        safe_handler_remove(getattr(self, "_h_px", None),
                            bpy.types.SpaceView3D, "WINDOW")
        self._h_view = None
        self._h_px = None
        timer = getattr(self, "_timer", None)
        if timer is not None:
            try:
                bpy.context.window_manager.event_timer_remove(timer)
            except Exception:
                pass
            self._timer = None
        entry = getattr(self, "_install_entry", None)
        if entry is not None and entry in _LIVE_INSTALLS:
            _LIVE_INSTALLS.remove(entry)
        self._install_entry = None
        type(self).is_running = False
        type(self)._stop_requested = False

    def _build_geometry(self, target_area, state):
        from mathutils import Vector
        c = bpy.context.scene.cursor.location
        # --- main 6-state demo: points (z=0), lines (z=-0.7..-1.5),
        #     preview polyline (z=0.7..1.3), state text labels overhead.
        col_offsets = [Vector((dx, 0, 0))
                       for dx in (-1.25, -0.75, -0.25, 0.25, 0.75, 1.25)]
        state["pts_row"] = [c + off for off in col_offsets]
        line_pairs = []
        for off in col_offsets:
            line_pairs.append(c + off + Vector((0, 0, -0.7)))
            line_pairs.append(c + off + Vector((0, 0, -1.5)))
        state["line_pairs"] = line_pairs
        state["preview_polyline"] = [
            c + Vector((-1.25, 0, 0.9)),
            c + Vector((-0.75, 0, 1.3)),
            c + Vector((-0.25, 0, 0.7)),
            c + Vector(( 0.25, 0, 1.3)),
            c + Vector(( 0.75, 0, 0.9)),
            c + Vector(( 1.25, 0, 1.1)),
        ]
        # --- "extras" row below the line column, demoing the remaining
        # roles so every theme color visibly maps to something on screen:
        # handle / handle-hover / pivot / cursor points along a row, and
        # a bbox rectangle drawn as a closed loop around them.
        extras_z = -2.4
        state["handle_pt"]       = c + Vector((-1.0, 0, extras_z))
        state["handle_hover_pt"] = c + Vector((-0.5, 0, extras_z))
        state["pivot_pt"]        = c + Vector(( 0.0, 0, extras_z))
        state["cursor_pt"]       = c + Vector(( 0.5, 0, extras_z))
        # BBox: closed rectangle around the extras row.
        bbox_pad_x = 1.3
        bbox_pad_z = 0.35
        bx0, bx1 = -bbox_pad_x, bbox_pad_x
        bz0, bz1 = extras_z - bbox_pad_z, extras_z + bbox_pad_z
        bbox_pts = [Vector((bx0, 0, bz0)), Vector((bx1, 0, bz0)),
                    Vector((bx1, 0, bz1)), Vector((bx0, 0, bz1))]
        bbox_pts = [c + p for p in bbox_pts]
        # Flat pair list for edges_3d (4 closing edges).
        state["bbox_edges"] = [
            bbox_pts[0], bbox_pts[1],
            bbox_pts[1], bbox_pts[2],
            bbox_pts[2], bbox_pts[3],
            bbox_pts[3], bbox_pts[0],
        ]
        # --- island palette: row of 8 translucent fill quads on the
        # right, one per `island_palette_N`.
        pal_x = 2.4
        pal_w = 0.35
        pal_h = 0.30
        pal_z0 = 1.4
        island_tris = []  # flat tri list, each quad → two triangles
        for i in range(8):
            z = pal_z0 - i * (pal_h + 0.04)
            a = Vector((pal_x,         0, z - pal_h))
            b = Vector((pal_x + pal_w, 0, z - pal_h))
            d = Vector((pal_x,         0, z))
            e = Vector((pal_x + pal_w, 0, z))
            island_tris.append([c + a, c + b, c + e,
                                c + a, c + e, c + d])
        state["island_quads"] = island_tris

    def _build_hud(self, state):
        hud = HUDOverlay("theme_preview")
        hud.title = "Theme preview"
        # Honor the theme's hud_mode setting so the preview is a faithful
        # demo. Cursor-follow only produces sensible coords while the
        # mouse is actually over the bound viewport — when it isn't (e.g.
        # the user is interacting with the prefs window), the snapshot
        # holds the last valid position and the HUD freezes there.

        def _mouse_xy() -> str:
            ev = state.get("event_snap")
            if ev is None:
                return "—"
            return f"{ev.mouse_region_x}, {ev.mouse_region_y}"

        hud.add_param(HUDParam(
            "Mouse", _mouse_xy, kind="str"))
        hud.add_param(HUDParam(
            "Snap", lambda: state["snap_on"], kind="bool"))
        hud.add_param(HUDParam(
            "Subdivisions", lambda: state["subdivisions"], kind="int"))
        hud.add_param(HUDParam(
            "Offset", lambda: state["offset"], kind="float", fmt="{:.3f}",
            active_getter=lambda: state["snap_on"]))
        # Keep one HUDItem section so the legacy `S`-toggle highlight works
        # for the smoke-test, but the hotkeys list will move to Help.
        hud.add_section(HUDSection("", [
            HUDItem("Snap toggle marker", "S", ItemState.OFF,
                    always_show=False),
        ]))
        return hud

    def _build_help(self, target_region):
        helpo = HelpOverlay("theme_preview")
        helpo.bind_region(target_region)
        helpo.add_section(HUDSection("Theme preview", [
            HUDItem("Toggle snap",      "S",       ItemState.ON),
            HUDItem("More / fewer subs", "Wheel",  ItemState.ON),
            HUDItem("Hide params",      "/",       ItemState.ON),
            HUDItem("Toggle this help", "H",       ItemState.ON),
            HUDItem("Exit",             "ESC/RMB", ItemState.ON),
        ]))
        return helpo


class IOPS_OT_StopThemePreview(bpy.types.Operator):
    bl_idname = "iops.stop_theme_preview"
    bl_label = "Stop Preview"
    bl_description = "Stop the running theme preview"
    bl_options = {"REGISTER"}

    @classmethod
    def poll(cls, context):
        return IOPS_OT_DrawThemePreview.is_running

    def execute(self, context):
        IOPS_OT_DrawThemePreview._stop_requested = True
        # Nudge the viewport so the preview's modal wakes up.
        for win in context.window_manager.windows:
            for area in win.screen.areas:
                if area.type == "VIEW_3D":
                    area.tag_redraw()
        return {"FINISHED"}


classes = (IOPS_OT_DrawThemePreview, IOPS_OT_StopThemePreview)
