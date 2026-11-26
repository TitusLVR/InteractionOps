"""Input of the iOps material shelf.

Same contract as the widget framework (ui/widgets/events.py): addon
"3D View" keymap entries call iops.material_shelf_event; its poll is a
fast path (shelf on, 3D View), invoke hit-tests the shelf of the region
under the cursor and returns PASS_THROUGH outside it, so navigation,
selection, tools and other modals get every event outside the strip
untouched. Inside it the event is consumed:
- mouse move: hover (cell, badge, tool, resize edge) + viewport highlight
- wheel: scroll one row; Ctrl+wheel: thumbnail size
- right press: swallowed (no viewport menu under the shelf)
- left press: a modal for ONE gesture: click (release on the same target),
  drag of a cell (drop on the viewport), or resize (top edge)
Clicks run the existing operators (iops.material_assign,
iops.materials_merge_duplicates, iops.materials_select_users,
iops.material_new, ...), so undo and reports match the panel.
"""
import time

import bpy
from bpy_extras import view3d_utils
from mathutils import Vector
from mathutils.bvhtree import BVHTree

from ...operators.materials import common, state
from ...utils import materials_shelf_core as core
from . import STATE, compute, highlight, shelf_active, shelf_region, \
    tag_redraw_all, ui_scale

MOVE = {"MOUSEMOVE", "INBETWEEN_MOUSEMOVE"}
# a toolbar tooltip shows after the mouse rested on the button this long
TOOLTIP_DELAY = 0.4


def _tooltip_redraw():
    tag_redraw_all()
    return None


def _schedule_tooltip():
    # one redraw once the delay passed (draw.py checks the elapsed time)
    if bpy.app.timers.is_registered(_tooltip_redraw):
        bpy.app.timers.unregister(_tooltip_redraw)
    bpy.app.timers.register(_tooltip_redraw, first_interval=TOOLTIP_DELAY)


def cancel_tooltip_timer():
    if bpy.app.timers.is_registered(_tooltip_redraw):
        bpy.app.timers.unregister(_tooltip_redraw)


def _has_dup(rows, by_key):
    def has(i):
        row = rows[i]
        mat = by_key.get(row.key)
        return row.count > 1 and mat is not None and mat.library is None
    return has


def _set_hover(context, area, kind, data, rows, by_key):
    if kind in {"cell", "dup", "users"}:
        new = (area.as_pointer(), data, kind)
        mat = by_key.get(rows[data].key)
    elif kind == "tool":
        new = (area.as_pointer(), data, "tool")
        mat = None
    elif kind == "resize":
        new = (area.as_pointer(), "resize", "tool")
        mat = None
    else:
        new, mat = None, None
    if new != STATE["hover"]:
        STATE["hover"] = new
        STATE["hover_since"] = time.monotonic()
        area.tag_redraw()
        if new is not None and new[2] == "tool" and new[1] != "resize":
            _schedule_tooltip()
    try:
        on = common.addon_prefs(context).materials_highlight_hover
    except (KeyError, AttributeError):
        on = False
    highlight.set_hover(context, mat if on else None)


# ----------------------------------------------------------------------
# drop target
# ----------------------------------------------------------------------
def _ray(context, region, rv3d, x, y):
    coord = (x, y)
    origin = view3d_utils.region_2d_to_origin_3d(region, rv3d, coord)
    direction = view3d_utils.region_2d_to_vector_3d(region, rv3d, coord)
    return origin, direction


def _original_face(obj, origin, direction, cache):
    """Index of the original polygon under the ray, -1 if none. Meshes
    without modifiers use the scene ray cast's index directly; otherwise a
    BVH of the original mesh (bmesh in Edit Mode), cached per gesture."""
    me = obj.data
    inv = obj.matrix_world.inverted()
    o = inv @ origin
    d = (inv.to_3x3() @ direction).normalized()
    key = obj.as_pointer()
    bvh = cache.get(key)
    if bvh is None:
        if me.is_editmode:
            import bmesh
            bvh = BVHTree.FromBMesh(bmesh.from_edit_mesh(me))
        else:
            verts = [v.co.copy() for v in me.vertices]
            polys = [tuple(p.vertices) for p in me.polygons]
            bvh = BVHTree.FromPolygons(verts, polys)
        cache[key] = bvh
    hit = bvh.ray_cast(o, d)
    return hit[2] if hit[0] is not None and hit[2] is not None else -1


def _face_world(obj, index):
    me = obj.data
    mw = obj.matrix_world
    if me.is_editmode:
        import bmesh
        bm = bmesh.from_edit_mesh(me)
        bm.faces.ensure_lookup_table()
        pts = [mw @ v.co for v in bm.faces[index].verts]
    else:
        pts = [mw @ me.vertices[i].co for i in me.polygons[index].vertices]
    tris = []
    for i in range(1, len(pts) - 1):
        tris.extend((pts[0][:], pts[i][:], pts[i + 1][:]))
    return tris


def drop_target(context, region, rv3d, x, y, want_face, cache):
    """(object, face index or -1) under region pixel (x, y), or None."""
    origin, direction = _ray(context, region, rv3d, x, y)
    depsgraph = context.evaluated_depsgraph_get()
    hit, _loc, _nor, index, obj, _mat = context.scene.ray_cast(
        depsgraph, origin, direction)
    if not hit or obj is None:
        return None
    obj = getattr(obj, "original", obj)
    if not common.is_compatible(obj):
        return None
    face = -1
    if want_face and obj.type == "MESH":
        if not obj.modifiers and not obj.data.is_editmode:
            face = index
        else:
            face = _original_face(obj, origin, direction, cache)
        if face < 0:
            return None
    return obj, face


# ----------------------------------------------------------------------
# operator
# ----------------------------------------------------------------------
class IOPS_OT_material_shelf_event(bpy.types.Operator):
    """iOps material shelf input (hover, wheel, click, drag, resize)"""

    bl_idname = "iops.material_shelf_event"
    bl_label = "Material Shelf"
    bl_options = {"INTERNAL"}

    @classmethod
    def poll(cls, context):
        area = context.area
        return (area is not None and area.type == "VIEW_3D"
                and shelf_active(context))

    # -- dispatch -----------------------------------------------------
    def invoke(self, context, event):
        area, region = context.area, context.region
        if region is None or region.type != "WINDOW" \
                or shelf_region(area) != region:
            return {"PASS_THROUGH"}
        lay, rows, by_key = compute(context, area, region)
        mx, my = event.mouse_region_x, event.mouse_region_y
        kind, data = core.hit_test(lay, mx, my, _has_dup(rows, by_key))
        et = event.type
        if et in MOVE:
            _set_hover(context, area, kind, data, rows, by_key)
            return {"PASS_THROUGH"} if kind == "outside" else {"CANCELLED"}
        if kind == "outside":
            return {"PASS_THROUGH"}
        if et in {"WHEELUPMOUSE", "WHEELDOWNMOUSE"}:
            step = 1 if et == "WHEELDOWNMOUSE" else -1
            if event.ctrl:
                prefs = common.addon_prefs(context)
                prefs.materials_shelf_thumbnail = core.clamp_thumb(
                    prefs.materials_shelf_thumbnail - step * core.THUMB_STEP)
            else:
                STATE["scroll"][area.as_pointer()] = core.scroll_step(lay, step)
            area.tag_redraw()
            return {"CANCELLED"}
        if et == "RIGHTMOUSE":
            return {"CANCELLED"}
        if et == "LEFTMOUSE" and event.value == "PRESS":
            return self._begin(context, event, lay, rows, by_key, kind, data)
        return {"CANCELLED"}

    # -- gesture ------------------------------------------------------
    def _begin(self, context, event, lay, rows, by_key, kind, data):
        self.kind, self.data = kind, data
        self.region = context.region
        self.area = context.area
        self.rv3d = context.region_data
        self.tracker = core.DragTracker(event.mouse_x, event.mouse_y,
                                        core.DRAG_THRESHOLD * ui_scale(context))
        self.bvh = {}
        self.key = None
        if kind in {"cell", "dup", "users"}:
            self.key = rows[data].key
            self.row = rows[data]
        if kind == "resize":
            prefs = common.addon_prefs(context)
            self.start_h = lay.shelf.h
            self.start_y = event.mouse_y
            self.thumb = prefs.materials_shelf_thumbnail
        context.window_manager.modal_handler_add(self)
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        et, ev = event.type, event.value
        if et in MOVE:
            if self.kind == "resize":
                self._resize(context, event)
            elif self.kind == "cell" and self.tracker.update(event.mouse_x,
                                                             event.mouse_y):
                self._drag_move(context, event)
            return {"RUNNING_MODAL"}
        if et in {"LEFT_ALT", "RIGHT_ALT"} and STATE["drag"]:
            self._drag_move(context, event)
            return {"RUNNING_MODAL"}
        if et == "LEFTMOUSE" and ev == "RELEASE":
            try:
                self._finish(context, event)
            finally:
                self._end()
            return {"FINISHED"}
        if et in {"ESC", "RIGHTMOUSE"} and ev == "PRESS":
            self._end()
            return {"CANCELLED"}
        return {"RUNNING_MODAL"}

    def _end(self):
        STATE["drag"] = None
        highlight.DROP["target"] = None
        tag_redraw_all()

    def _region_xy(self, event):
        return (event.mouse_x - self.region.x, event.mouse_y - self.region.y)

    def _resize(self, context, event):
        s = ui_scale(context)
        h = core.resize_height(
            self.start_h, self.start_y, event.mouse_y, self.thumb,
            self.region.height, s,
            common.addon_prefs(context).materials_shelf_tools_direction)
        common.addon_prefs(context).materials_shelf_height = max(
            60, int(round(h / s)))
        self.area.tag_redraw()

    def _inside_region(self, x, y):
        return 0 <= x < self.region.width and 0 <= y < self.region.height

    def _over_shelf(self, context, x, y):
        lay, _rows, _by_key = compute(context, self.area, self.region)
        return core.contains(lay.shelf, x, y)

    def _drag_move(self, context, event):
        if not STATE["drag"]:
            # the hover highlight would compete with the drop target
            STATE["hover"] = None
            highlight.set_hover(context, None)
        STATE["drag"] = {"active": True, "key": self.key, "x": event.mouse_x,
                         "y": event.mouse_y, "alt": event.alt}
        x, y = self._region_xy(event)
        target = None
        if self._inside_region(x, y) and not self._over_shelf(context, x, y):
            target = drop_target(context, self.region, self.rv3d, x, y,
                                 event.alt, self.bvh)
        if target is None:
            highlight.DROP["target"] = None
        else:
            obj, face = target
            mw = obj.matrix_world
            highlight.DROP["target"] = {
                "bbox": [(mw @ Vector(c))[:] for c in obj.bound_box],
                "face": _face_world(obj, face) if face >= 0 else None,
            }
        tag_redraw_all()

    def _finish(self, context, event):
        x, y = self._region_xy(event)
        if STATE["drag"]:
            if not self._inside_region(x, y) or self._over_shelf(context, x, y):
                return
            target = drop_target(context, self.region, self.rv3d, x, y,
                                 event.alt, self.bvh)
            if target is None:
                return
            obj, face = target
            name, lib = self.key
            bpy.ops.iops.material_assign_drop(material=name, library=lib,
                                              object=obj.name, face=face)
            return
        if self.kind == "resize":
            return
        lay, rows, by_key = compute(context, self.area, self.region)
        kind, data = core.hit_test(lay, x, y, _has_dup(rows, by_key))
        if (kind, data) != (self.kind, self.data):
            return      # released somewhere else: no click
        if kind == "tool":
            self._tool(context, event, data)
        elif kind in {"cell", "dup", "users"}:
            self._cell(context, event, kind, by_key.get(self.key))

    def _cell(self, context, event, kind, mat):
        if mat is None:
            return
        name, lib = common.material_key(mat)
        if kind == "dup":
            bpy.ops.iops.materials_merge_duplicates(base=self.row.base)
        elif kind == "users":
            if bpy.ops.iops.materials_select_users.poll():
                bpy.ops.iops.materials_select_users(material=name,
                                                    library=lib)
            else:
                state.set_active(mat, context)
        elif event.ctrl:
            state.set_active(mat, context)
        else:
            bpy.ops.iops.material_assign(material=name, library=lib,
                                         mode="FACES" if event.alt
                                         else "OBJECT")
        tag_redraw_all()

    def _tool(self, context, event, name):
        st = state.get_state(context)
        if name == "new":
            bpy.ops.iops.material_new(
                assign=event.shift,
                mode="FACES" if event.shift and event.alt else "OBJECT")
        elif name == "functions":
            bpy.ops.wm.call_menu(name="IOPS_MT_materials_functions")
        elif name.startswith("src_"):
            st.source = name[4:]
        elif name == "search":
            bpy.ops.wm.call_panel(name="IOPS_PT_materials_shelf_search",
                                  keep_open=False)
        elif name == "empty":
            bpy.ops.iops.materials_remove_empty_slots(scope="SELECTED")
        tag_redraw_all()


class IOPS_PT_materials_shelf_search(bpy.types.Panel):
    """Search field of the iOps material shelf (a small native popup: a
    text field cannot be edited inside a drawn strip)"""

    bl_label = "Search Materials"
    bl_idname = "IOPS_PT_materials_shelf_search"
    bl_space_type = "VIEW_3D"
    bl_region_type = "WINDOW"
    bl_ui_units_x = 12

    def draw(self, context):
        layout = self.layout
        st = state.get_state(context)
        row = layout.row(align=True)
        row.activate_init = True
        row.prop(st, "search", text="", icon="VIEWZOOM")


CLASSES = (IOPS_OT_material_shelf_event, IOPS_PT_materials_shelf_search)

# ----------------------------------------------------------------------
# keymap: programmatic, never saved (save_hotkeys.NEVER_SAVE)
# ----------------------------------------------------------------------
_KMI = []
_EVENTS = (
    ("LEFTMOUSE", "PRESS"),
    ("RIGHTMOUSE", "PRESS"),
    ("WHEELUPMOUSE", "PRESS"),
    ("WHEELDOWNMOUSE", "PRESS"),
    ("MOUSEMOVE", "ANY"),
)


def register_keymap():
    kc = bpy.context.window_manager.keyconfigs.addon
    if kc is None or _KMI:
        return
    km = kc.keymaps.new("3D View", space_type="VIEW_3D")
    for etype, value in _EVENTS:
        kmi = km.keymap_items.new(IOPS_OT_material_shelf_event.bl_idname,
                                  etype, value, any=True)
        _KMI.append((km, kmi))
    # merge the new addon items into the active keymaps now, not at the
    # next keyconfig refresh (otherwise the first events miss them)
    bpy.context.window_manager.keyconfigs.update()


def unregister_keymap():
    cancel_tooltip_timer()
    for km, kmi in _KMI:
        try:
            km.keymap_items.remove(kmi)
        except (ReferenceError, RuntimeError):
            pass
    _KMI.clear()


def keymap_item_count():
    return len(_KMI)
