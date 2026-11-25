"""The Falloff toolbar tool (Edit Mesh): handles for the active field and the
pivot, tool settings, and the tool keymap (G / R / S / Alt+S / Shift+F).

The fields themselves are drawn by `draw.py` (module draw handlers); this
module only adds the draggable dots. Handle geometry and drag maths are pure
functions (`handle_points`, `drag_field`, `constrain`, `project_points`,
`nearest_within`) so they are testable without a viewport.
"""
from __future__ import annotations

import bpy
import numpy as np
from bpy.types import Gizmo, GizmoGroup, Panel, UIList, WorkSpaceTool
from bpy_extras import view3d_utils
from mathutils import Matrix, Vector

from ...ui.draw import Role, get_theme
from ...utils import falloff_core as fc
from . import draw
from .base import PRECISE_FACTOR
from .draw import TOOL_IDNAME
from .props import active_field, field_to_dict

GROUP_IDNAME = "IOPS_GGT_falloff"
HANDLE_IDNAME = "IOPS_GT_falloff_handle"
HANDLE_RADIUS_PX = 6.0
SELECT_PX = 14.0
SNAP_PX = 16.0
SELECT_ALPHA = 0.35
AXES = {"X": (1.0, 0.0, 0.0), "Y": (0.0, 1.0, 0.0), "Z": (0.0, 0.0, 1.0)}
TYPE_ICONS = {"LINEAR": "IPO_LINEAR", "RADIAL": "SPHERECURVE",
              "ELLIPTICAL": "MESH_UVSPHERE", "BIDIRECTIONAL": "IPO_EASE_IN_OUT"}


# ------------------------------------------------------------------ pure helpers

def handle_points(field: dict) -> dict:
    """World positions of the active-field handles by role."""
    s = np.asarray(field["start"], dtype=np.float64)
    e = np.asarray(field["end"], dtype=np.float64)
    pts = {"START": s, "END": e, "BODY": 0.5 * (s + e)}
    if field["type"] == "ELLIPTICAL":
        axes, radii = fc.ellipsoid_frame(s, e, field["radii"], field["roll"])
        pts["RADIUS_1"] = s + axes[:, 1] * radii[1]
        pts["RADIUS_2"] = s + axes[:, 2] * radii[2]
    return pts


def drag_field(field: dict, role: str, delta) -> dict:
    """New (start, end, radii) of `field` after moving handle `role` by the
    world vector `delta` from where it was at the start of the drag."""
    s = np.asarray(field["start"], dtype=np.float64)
    e = np.asarray(field["end"], dtype=np.float64)
    radii = [float(r) for r in field["radii"]]
    d = np.asarray(delta, dtype=np.float64)
    if role == "START":
        s = s + d
    elif role == "END":
        e = e + d
    elif role == "BODY":
        s, e = s + d, e + d
    elif role in ("RADIUS_1", "RADIUS_2"):
        k = 1 if role == "RADIUS_1" else 2
        axes, _ = fc.ellipsoid_frame(s, e, field["radii"], field["roll"])
        p = handle_points(field)[role] + d
        radii[k - 1] = max(abs(float(np.dot(p - s, axes[:, k]))), fc.MIN_SIZE)
    return {"start": s, "end": e, "radii": tuple(radii)}


def toggle_constraint(current, key):
    """X / Y / Z: constrain to that world axis; the same key again frees."""
    return None if current == key else key


def constrain(delta, axis) -> np.ndarray:
    d = np.asarray(delta, dtype=np.float64)
    if axis is None:
        return d
    a = np.asarray(AXES[axis])
    return a * float(np.dot(d, a))


def project_points(P, persp, width, height):
    """World points -> region pixels with the view's perspective matrix.
    Returns ((N, 2) xy, (N,) bool in front of the view)."""
    P = np.asarray(P, dtype=np.float64)
    M = np.asarray(persp, dtype=np.float64)
    clip = np.c_[P, np.ones(len(P))] @ M.T
    w = clip[:, 3]
    ok = w > 1e-9
    ndc = clip[:, :2] / np.where(ok, w, 1.0)[:, None]
    xy = (ndc + 1.0) * 0.5 * np.array([width, height], dtype=np.float64)
    return xy, ok


def nearest_within(xy, ok, mouse, max_px):
    """Index of the visible point nearest `mouse` within `max_px`, or None."""
    if not len(xy):
        return None
    dist = np.linalg.norm(np.asarray(xy) - np.asarray(mouse, dtype=np.float64), axis=1)
    dist = np.where(ok, dist, np.inf)
    i = int(np.argmin(dist))
    return i if dist[i] <= max_px else None


def handle_colors(theme, color_role, alpha=1.0):
    """(color, alpha, color_highlight, alpha_highlight) of a handle dot drawn
    in theme role `color_role`, its alpha times `alpha`."""
    c = theme.color_for(color_role)
    h = theme.color_for(Role.HANDLE_HOVER)
    return (tuple(c[:3]), float(c[3]) * alpha, tuple(h[:3]), float(h[3]))


# ------------------------------------------------------------------ gizmo

class IOPS_GT_falloff_handle(Gizmo):
    """A screen-facing dot bound to one handle (`role`, `index`)."""
    bl_idname = HANDLE_IDNAME

    def _point(self, context):
        role = getattr(self, "role", None)
        if role is None:
            return None
        settings = context.scene.IOPS.falloff
        if role == "PIVOT":
            if settings.use_custom_pivot:
                return np.array(settings.pivot[:], dtype=np.float64)
            return draw.compute_preview(context).pivot
        i = getattr(self, "index", -1)
        if not 0 <= i < len(settings.fields):
            return None
        pts = handle_points(field_to_dict(settings.fields[i]))
        return pts.get("BODY" if role.startswith("SELECT_") else role)

    def draw(self, context):
        p = self._point(context)
        if p is None:
            return
        px = draw.world_per_px(context.region, context.region_data, p)
        if px <= 0.0:
            return
        m = (Matrix.Translation(Vector(p))
             @ context.region_data.view_rotation.to_matrix().to_4x4()
             @ Matrix.Scale(px * HANDLE_RADIUS_PX, 4))
        self.draw_preset_circle(m, axis="POS_Z")

    def test_select(self, context, location):
        p = self._point(context)
        if p is None:
            return -1
        xy = view3d_utils.location_3d_to_region_2d(
            context.region, context.region_data, Vector(p))
        if xy is None:
            return -1
        return 0 if (xy - Vector(location)).length <= SELECT_PX else -1

    def invoke(self, context, event):
        settings = context.scene.IOPS.falloff
        role = getattr(self, "role", None)
        if role is None:
            return {"CANCELLED"}
        if role.startswith("SELECT_"):
            if 0 <= self.index < len(settings.fields):
                settings.active_index = self.index
            return {"FINISHED"}
        p = self._point(context)
        if p is None:
            return {"CANCELLED"}
        self.p0 = np.array(p, dtype=np.float64)
        self.mouse0 = (event.mouse_region_x, event.mouse_region_y)
        self.axis = None
        if role == "PIVOT":
            self.saved = (tuple(settings.pivot), settings.use_custom_pivot)
        else:
            self.saved = field_to_dict(settings.fields[self.index])
        return {"RUNNING_MODAL"}

    def modal(self, context, event, tweak):
        if event.type in AXES and event.value == "PRESS":
            self.axis = toggle_constraint(self.axis, event.type)
        region, rv3d = context.region, context.region_data
        mouse = (event.mouse_region_x, event.mouse_region_y)
        through = Vector(self.p0)
        a = view3d_utils.region_2d_to_location_3d(region, rv3d, self.mouse0, through)
        b = view3d_utils.region_2d_to_location_3d(region, rv3d, mouse, through)
        delta = np.array((b - a)[:], dtype=np.float64)
        if "PRECISE" in tweak:
            delta *= PRECISE_FACTOR
        if "SNAP" in tweak:
            P = draw.preview_points()
            xy, ok = project_points(P, rv3d.perspective_matrix, region.width, region.height)
            i = nearest_within(xy, ok, mouse, SNAP_PX)
            if i is not None:
                delta = P[i] - self.p0
        self._apply(context, constrain(delta, self.axis))
        if context.area:
            context.area.tag_redraw()
        return {"RUNNING_MODAL"}

    def _apply(self, context, delta):
        settings = context.scene.IOPS.falloff
        if self.role == "PIVOT":
            settings.pivot = tuple(self.p0 + delta)
            settings.use_custom_pivot = True
            return
        if not 0 <= self.index < len(settings.fields):
            return
        f = settings.fields[self.index]
        r = drag_field(self.saved, self.role, delta)
        f.start = tuple(r["start"])
        f.end = tuple(r["end"])
        f.radii = r["radii"]

    def exit(self, context, cancel):
        if not cancel or getattr(self, "saved", None) is None:
            return
        settings = context.scene.IOPS.falloff
        if self.role == "PIVOT":
            settings.pivot, settings.use_custom_pivot = self.saved
        elif 0 <= self.index < len(settings.fields):
            f = settings.fields[self.index]
            f.start, f.end, f.radii = self.saved["start"], self.saved["end"], self.saved["radii"]
        if context.area:
            context.area.tag_redraw()


class IOPS_GGT_falloff(GizmoGroup):
    bl_idname = GROUP_IDNAME
    bl_label = "Falloff Handles"
    bl_space_type = "VIEW_3D"
    bl_region_type = "WINDOW"
    bl_options = {"3D", "PERSISTENT"}

    @classmethod
    def poll(cls, context):
        # PERSISTENT groups live in every 3D view: show only under the tool,
        # so the dots never take clicks from other tools
        return context.mode == "EDIT_MESH" and draw.tool_active(context)

    def setup(self, context):
        self.layout_key = None
        self._sync(context)

    def refresh(self, context):
        self._sync(context)

    def draw_prepare(self, context):
        self._sync(context)
        # follow theme edits without a rebuild
        th = get_theme(context)
        for gz in self.gizmos:
            self._paint(gz, th)

    @staticmethod
    def _paint(gz, theme):
        spec = getattr(gz, "paint_spec", None)
        if spec is None:
            return
        colors = handle_colors(theme, *spec)
        if colors != getattr(gz, "painted", None):
            gz.painted = colors
            gz.color, gz.alpha, gz.color_highlight, gz.alpha_highlight = colors

    def _add(self, theme, role, index, color_role, alpha=1.0):
        gz = self.gizmos.new(HANDLE_IDNAME)
        gz.role, gz.index = role, index
        gz.paint_spec = (color_role, alpha)
        self._paint(gz, theme)
        gz.use_draw_modal = True

    def _sync(self, context):
        """Rebuild the handles when the field count, active index or active
        type changed. Reads the scene only."""
        settings = context.scene.IOPS.falloff
        f = active_field(settings)
        key = (len(settings.fields), settings.active_index, f.type if f else None)
        if key == getattr(self, "layout_key", None):
            return
        self.layout_key = key
        for gz in list(self.gizmos):
            self.gizmos.remove(gz)
        th = get_theme(context)
        if f is not None:
            roles = ["START", "END", "BODY"]
            if f.type == "ELLIPTICAL":
                roles += ["RADIUS_1", "RADIUS_2"]
            for role in roles:
                self._add(th, role, settings.active_index, Role.HANDLE)
        self._add(th, "PIVOT", -1, Role.PIVOT)
        for i in range(len(settings.fields)):
            if i != settings.active_index:
                self._add(th, f"SELECT_{i}", i, Role.HANDLE, SELECT_ALPHA)


# ------------------------------------------------------------------ settings UI

class IOPS_UL_falloff_fields(UIList):
    bl_idname = "IOPS_UL_falloff_fields"

    def draw_item(self, context, layout, data, item, icon, active_data,
                  active_propname, index):
        row = layout.row(align=True)
        row.prop(item, "enabled", text="")
        row.prop(item, "name", text="", emboss=False)
        row.label(text=item.type.title(), icon=TYPE_ICONS.get(item.type, "NONE"))


class IOPS_PT_falloff_stack(Panel):
    bl_idname = "IOPS_PT_falloff_stack"
    bl_label = "Falloff Fields"
    bl_space_type = "VIEW_3D"
    bl_region_type = "HEADER"

    def draw(self, context):
        settings = context.scene.IOPS.falloff
        row = self.layout.row()
        row.template_list("IOPS_UL_falloff_fields", "", settings, "fields",
                          settings, "active_index", rows=4)
        col = row.column(align=True)
        col.operator_menu_enum("iops.mesh_falloff_field_add", "type", text="", icon="ADD")
        col.operator("iops.mesh_falloff_field_remove", text="", icon="REMOVE")
        col.separator()
        col.operator("iops.mesh_falloff_field_move", text="", icon="TRIA_UP").direction = "UP"
        col.operator("iops.mesh_falloff_field_move", text="", icon="TRIA_DOWN").direction = "DOWN"


class IOPS_WT_falloff(WorkSpaceTool):
    bl_space_type = "VIEW_3D"
    bl_context_mode = "EDIT_MESH"
    bl_idname = TOOL_IDNAME
    bl_label = "Falloff"
    bl_description = ("Position falloff fields with handles; G / R / S / Alt+S "
                      "run the falloff Move / Rotate / Scale / Normal Offset")
    bl_icon = "ops.transform.vertex_random"
    bl_widget = GROUP_IDNAME
    bl_keymap = (
        ("iops.mesh_falloff_move", {"type": "G", "value": "PRESS"}, None),
        ("iops.mesh_falloff_rotate", {"type": "R", "value": "PRESS"}, None),
        ("iops.mesh_falloff_scale", {"type": "S", "value": "PRESS"}, None),
        ("iops.mesh_falloff_normal_offset", {"type": "S", "value": "PRESS", "alt": True}, None),
        ("iops.mesh_falloff_fit", {"type": "F", "value": "PRESS", "shift": True}, None),
    )

    def draw_settings(context, layout, tool):
        settings = context.scene.IOPS.falloff
        f = active_field(settings)
        layout.popover("IOPS_PT_falloff_stack", text=f.name if f else "No Field")
        if f is not None:
            layout.prop(f, "type", text="")
            layout.prop(f, "curve", text="")
            layout.prop(f, "invert", text="", icon="ARROW_LEFTRIGHT")
            layout.prop(f, "strength")
            layout.prop(f, "blend", text="")
        layout.prop(settings, "show_weights", text="Weights")
        layout.prop(settings, "basis", text="")
        layout.operator("iops.mesh_falloff_fit", text="Fit")
        layout.operator("iops.mesh_falloff_clear", text="Clear")
        layout.operator("iops.mesh_falloff_pivot_reset", text="Reset Pivot")


# ------------------------------------------------------------------ register

def _drop_tool_defs(idname) -> None:
    """Remove toolbar entries with `idname` left by an earlier import of this
    module (dev reload after a failed unregister)."""
    from bl_ui.space_toolsystem_common import ToolSelectPanelHelper
    cls = ToolSelectPanelHelper._tool_class_from_space_type("VIEW_3D")
    tools = cls._tools[IOPS_WT_falloff.bl_context_mode]
    found = False
    for i in range(len(tools) - 1, -1, -1):
        item = tools[i]
        if isinstance(item, tuple):
            kept = tuple(t for t in item if getattr(t, "idname", None) != idname)
            if len(kept) != len(item):
                tools[i] = kept if kept else None
                found = True
        elif getattr(item, "idname", None) == idname:
            tools[i] = None
            found = True
    if not found:
        return
    # trim separators left at the end or doubled
    while tools and tools[-1] is None:
        del tools[-1]
    for i in range(len(tools) - 1, 0, -1):
        if tools[i] is None and tools[i - 1] is None:
            del tools[i]


def register() -> None:
    try:
        try:
            bpy.utils.register_tool(IOPS_WT_falloff, separator=True)
        except Exception:
            _drop_tool_defs(TOOL_IDNAME)
            bpy.utils.register_tool(IOPS_WT_falloff, separator=True)
    except Exception as e:
        print("IOPS falloff: tool register failed:", e)
    try:
        draw.install()
    except Exception as e:
        print("IOPS falloff: draw handlers install failed:", e)


def unregister() -> None:
    try:
        draw.uninstall()
    except Exception as e:
        print("IOPS falloff: draw handlers uninstall failed:", e)
    try:
        if hasattr(IOPS_WT_falloff, "_bl_tool"):
            bpy.utils.unregister_tool(IOPS_WT_falloff)
        else:
            _drop_tool_defs(TOOL_IDNAME)
    except Exception as e:
        print("IOPS falloff: tool unregister failed:", e)
