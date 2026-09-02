"""Per-modifier target picker (the stack-row eyedropper button).

Modal, pickup logic from object_mirror_rotate: LMB picks any visible
object as the modifier's target (nearest origin in screen space, so
empties work too; the candidate is highlighted). C creates an empty
target at the current 3D cursor right away, then stays in the
face-pick mode to refine: click a vert / edge-mid / center to snap
the 3D cursor there (Z = normal) and move the empty with it.
"""

import bpy
from mathutils import Matrix, Vector

from ...ui.draw import draw_scope, safe_handler_add, safe_handler_remove
from ...ui.draw import primitives as iops_draw
from ...ui.draw.theme import Role
from ..object_mirror_rotate import _draw_tpick, _tpick_update
from . import iops_mod_registry

_NAV_EVENTS = {
    "MIDDLEMOUSE", "WHEELUPMOUSE", "WHEELDOWNMOUSE",
    "MOUSEPAN", "MOUSEZOOM", "MOUSEROTATE",
    "TRACKPADPAN", "TRACKPADZOOM",
    "NDOF_MOTION", "NDOF_BUTTON_FIT",
}

# bound_box corner order is fixed in Blender; 12 box edges
_BBOX_EDGES = ((0, 1), (1, 2), (2, 3), (3, 0),
               (4, 5), (5, 6), (6, 7), (7, 4),
               (0, 4), (1, 5), (2, 6), (3, 7))

_STATUS_PICK = ("LMB: pick target object · C: empty target at 3D cursor · "
                "Esc / RMB: cancel")
_STATUS_CURSOR = ("LMB: snap to vert / edge-mid / center · "
                  "Enter / Space / C: keep at cursor · Esc / RMB: cancel")


def _view3d_region(context):
    """The 3D viewport's WINDOW region + its RegionView3D. The button
    lives in the N-panel / popup, so context.region is a UI region."""
    area = context.area
    if area is None or area.type != "VIEW_3D":
        area = next((a for a in context.window.screen.areas
                     if a.type == "VIEW_3D"), None)
        if area is None:
            return None, None
    region = next((r for r in area.regions if r.type == "WINDOW"), None)
    if region is None:
        return None, None
    return region, area.spaces.active.region_3d


def _pick_object(context, event, region, rv3d, exclude=()):
    """Nearest visible object origin to the click, in screen space — works
    for empties too (no geometry to raycast). From object_mirror_rotate."""
    if region is None or rv3d is None:
        return None
    from bpy_extras.view3d_utils import location_3d_to_region_2d
    mouse = Vector((event.mouse_x - region.x, event.mouse_y - region.y))
    best, best_d = None, 1e9
    for obj in context.visible_objects:
        if obj in exclude:
            continue
        try:
            p2 = location_3d_to_region_2d(region, rv3d,
                                          obj.matrix_world.translation)
        except ReferenceError:
            continue
        if p2 is None:
            continue
        d = (p2 - mouse).length
        if d < best_d:
            best_d, best = d, obj
    return best if best_d <= 40.0 else None


def _hover_edges(obj):
    """World-space edge list highlighting obj: its bounding box, or an
    axis cross at the origin when the box is degenerate (empties)."""
    mw = obj.matrix_world
    corners = [mw @ Vector(c) for c in obj.bound_box]
    lo = Vector(tuple(min(c[i] for c in corners) for i in range(3)))
    hi = Vector(tuple(max(c[i] for c in corners) for i in range(3)))
    if (hi - lo).length > 1e-6:
        edges = []
        for a, b in _BBOX_EDGES:
            edges.append(corners[a])
            edges.append(corners[b])
        return edges
    size = getattr(obj, "empty_display_size", 0.0) or 0.25
    origin = mw.translation
    edges = []
    for axis in (Vector((1, 0, 0)), Vector((0, 1, 0)), Vector((0, 0, 1))):
        d = (mw.to_3x3() @ axis).normalized() * size
        edges.append(origin - d)
        edges.append(origin + d)
    return edges


def _draw_pick(op, context):
    if op.cursor_pick:
        _draw_tpick(op, context)
        return
    hover = getattr(op, "_hover", None)
    if hover is None:
        return
    try:
        edges = _hover_edges(hover)
        origin = hover.matrix_world.translation.copy()
    except ReferenceError:
        return
    with draw_scope(blend="ALPHA", depth="NONE"):
        iops_draw.edges_3d(edges, role=Role.BBOX, context=context)
        iops_draw.points([origin], role=Role.CLOSEST_POINT, context=context)


class IOPS_OT_ModPickTarget(bpy.types.Operator):
    """Pick a target for this modifier.
    LMB: pick any visible object (empties too, candidate highlighted).
    C: create an empty target at the 3D cursor, then face-pick to
    refine — click a vert / edge-mid / center to snap the cursor and
    the empty there; Enter / Space keeps the cursor position.
    Esc / RMB: cancel"""

    bl_idname = "iops.mod_pick_target"
    bl_label = "Pick Modifier Target"
    bl_options = {"REGISTER", "UNDO"}

    index: bpy.props.IntProperty(options={"SKIP_SAVE"})

    def _modifier(self):
        try:
            return self._obj.modifiers[self.index]
        except (ReferenceError, IndexError):
            return None

    def _assign(self, md, obj):
        field = iops_mod_registry.object_fields(md)[0]
        setattr(md, field, obj)
        # RNA pointer polls can reject some object types (e.g. an
        # empty for a Boolean object)
        return getattr(md, field, None) == obj

    def invoke(self, context, event):
        obj = context.active_object
        if obj is None or not (0 <= self.index < len(obj.modifiers)):
            return {"CANCELLED"}
        md = obj.modifiers[self.index]
        fields = iops_mod_registry.object_fields(md)
        if not fields:
            self.report({"WARNING"}, "Modifier has no object target field")
            return {"CANCELLED"}
        region, rv3d = _view3d_region(context)
        if region is None or rv3d is None:
            self.report({"WARNING"}, "No 3D viewport")
            return {"CANCELLED"}
        self._obj = obj
        self._region = region
        self._rv3d = rv3d
        self._prev_target = getattr(md, fields[0], None)
        self._empty = None               # created by C, removed on cancel
        self._hover = None
        self.cursor_pick = False
        self._tpick = None
        self._handle = safe_handler_add(
            bpy.types.SpaceView3D, _draw_pick, (self, context),
            "WINDOW", "POST_VIEW", tick=False,
        )
        context.window.cursor_modal_set("EYEDROPPER")
        context.workspace.status_text_set(_STATUS_PICK)
        context.window_manager.modal_handler_add(self)
        return {"RUNNING_MODAL"}

    def _finish(self, context, cancelled=False):
        if cancelled and self._empty is not None:
            md = self._modifier()
            if md is not None:
                try:
                    self._assign(md, self._prev_target)
                except ReferenceError:
                    self._assign(md, None)
            try:
                bpy.data.objects.remove(self._empty)
            except ReferenceError:
                pass
            self._empty = None
        if getattr(self, "_handle", None) is not None:
            safe_handler_remove(self._handle, bpy.types.SpaceView3D, "WINDOW")
            self._handle = None
        context.window.cursor_modal_restore()
        context.workspace.status_text_set(None)
        self._region.tag_redraw()
        return {"CANCELLED"} if cancelled else {"FINISHED"}

    def _spawn_empty_at_cursor(self, context, md):
        empty = bpy.data.objects.new(f"iops_target_{md.type.lower()}", None)
        empty.empty_display_type = "PLAIN_AXES"
        empty.empty_display_size = 0.5
        context.collection.objects.link(empty)
        empty.matrix_world = context.scene.cursor.matrix.copy()
        return empty

    def modal(self, context, event):
        if event.type in _NAV_EVENTS:
            return {"PASS_THROUGH"}

        if event.type in {"ESC", "RIGHTMOUSE"} and event.value == "PRESS":
            return self._finish(context, cancelled=True)

        md = self._modifier()
        if md is None:
            self.report({"WARNING"}, "Modifier is gone")
            return self._finish(context, cancelled=True)

        if event.type == "C" and event.value == "PRESS":
            if not self.cursor_pick:
                # take the cursor position right away: the empty target
                # exists from this moment; face-pick only refines it
                self._empty = self._spawn_empty_at_cursor(context, md)
                if not self._assign(md, self._empty):
                    bpy.data.objects.remove(self._empty)
                    self._empty = None
                    self.report({"WARNING"},
                                f"{md.name}: does not accept an empty")
                    return {"RUNNING_MODAL"}
                self.cursor_pick = True
                self._hover = None
                _tpick_update(self, context, event, self._region, self._rv3d)
                context.workspace.status_text_set(_STATUS_CURSOR)
                self._region.tag_redraw()
                return {"RUNNING_MODAL"}
            # second C = keep the empty where the cursor is now
            self.report({"INFO"},
                        f"{md.name}: target = {self._empty.name} (at cursor)")
            return self._finish(context)

        if (self.cursor_pick and event.value == "PRESS"
                and event.type in {"RET", "NUMPAD_ENTER", "SPACE"}):
            self.report({"INFO"},
                        f"{md.name}: target = {self._empty.name} (at cursor)")
            return self._finish(context)

        if event.type == "MOUSEMOVE":
            if self.cursor_pick:
                _tpick_update(self, context, event, self._region, self._rv3d)
            else:
                self._hover = _pick_object(context, event,
                                           self._region, self._rv3d,
                                           exclude={self._obj})
            self._region.tag_redraw()
            return {"RUNNING_MODAL"}

        if event.type == "LEFTMOUSE" and event.value == "PRESS":
            if self.cursor_pick:
                _tpick_update(self, context, event, self._region, self._rv3d)
                tp = self._tpick
                if tp is None:
                    self.report({"WARNING"}, "No face under cursor")
                    return {"RUNNING_MODAL"}
                quat = tp["normal"].to_track_quat("Z", "Y")
                cursor = context.scene.cursor
                cursor.location = tp["closest"].copy()
                cursor.rotation_mode = "XYZ"
                cursor.rotation_euler = quat.to_euler()
                self._empty.matrix_world = Matrix.LocRotScale(
                    tp["closest"], quat, None)
                self.report({"INFO"},
                            f"{md.name}: target = {self._empty.name} "
                            "(snapped to face)")
                return self._finish(context)
            picked = self._hover or _pick_object(context, event,
                                                 self._region, self._rv3d,
                                                 exclude={self._obj})
            if picked is None:
                self.report({"WARNING"}, "No object near the click")
                return {"RUNNING_MODAL"}
            if not self._assign(md, picked):
                self.report({"WARNING"},
                            f"{md.name}: rejected {picked.name} — "
                            "pick another object")
                return {"RUNNING_MODAL"}
            self.report({"INFO"}, f"{md.name}: target = {picked.name}")
            return self._finish(context)

        return {"RUNNING_MODAL"}
