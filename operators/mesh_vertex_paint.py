"""Vertex Paint brush that works in Edit Mesh and Object mode — no switch
to Blender's Vertex Paint mode.

Why not Blender's own stroke engine: `paint.vertex_paint` polls for
OB_MODE_VERTEX_PAINT and runs on the PBVH / sculpt session that is only
built when that mode is entered. What *is* reused from Blender:

* the Brush datablock in `tool_settings.vertex_paint` (size, strength,
  color, falloff preset + custom CurveMapping, unified paint settings),
  so the brush shares settings with the native Vertex Paint tool;
* `wm.radial_control` for F / Shift+F radius / strength adjustment;
* the falloff preset formulas (utils/vertex_paint_core.py).

The stroke itself is ours: a ray against a BVH of the active object's base
mesh (built once on invoke), vertices inside the brush via a KDTree, the
weight from the falloff curve, non-accumulating per stroke. Colors are
written to the active color attribute (POINT / CORNER, FLOAT / BYTE) —
bmesh layers in Edit mode, `color_attributes` in Object mode.

Ctrl+Z / Ctrl+Shift+Z inside the modal step through a stroke history;
Esc restores the snapshot taken on invoke; Enter / Space / RMB finish and
push one global undo step for the whole session.
"""
import bpy
import bmesh
import math

from bpy.props import (BoolProperty, EnumProperty, FloatProperty,
                       FloatVectorProperty, IntProperty)
from bpy_extras import view3d_utils
from mathutils.bvhtree import BVHTree
from mathutils.kdtree import KDTree

from ..ui.draw import primitives as draw_prim, Role
from ..ui.draw import safe_handler_add, safe_handler_remove
from ..ui.draw.theme import get_theme
from ..ui.hud import (HUDOverlay, HelpOverlay, HUDSection, HUDItem,
                      ItemState, capture_event)
from ..utils.vertex_paint_core import (QUICK_COLORS, StrokeHistory,
                                       blend_color, falloff_weight,
                                       filter_color, filter_vertex_colors,
                                       neighborhood_mean, next_preset,
                                       stroke_weight)

IOPS_BRUSH_NAME = "IOPS Vertex Paint"
DEFAULT_ATTR_NAME = "Color"
# Blur tool: fraction of the way toward the neighborhood mean per dab at
# full weight and strength (accumulates over passes, like Blender's Blur).
BLUR_RATE = 0.5
# Screen-space spacing between interpolated dabs, as a fraction of radius.
DAB_SPACING = 0.25
MIN_RADIUS_PX = 2
ELEMENT_KEYS = {"ONE": "VERT", "TWO": "EDGE", "THREE": "FACE"}
# Events the brush never takes while idle, so viewport navigation keeps
# working: orbit / pan / zoom on MMB, plain wheel zoom, numpad views, NDOF.
NAV_TYPES = {"MIDDLEMOUSE", "TRACKPADPAN", "TRACKPADZOOM", "HOME",
             "NUMPAD_0", "NUMPAD_1", "NUMPAD_2", "NUMPAD_3", "NUMPAD_4",
             "NUMPAD_5", "NUMPAD_6", "NUMPAD_7", "NUMPAD_8", "NUMPAD_9",
             "NUMPAD_PERIOD", "NUMPAD_MINUS", "NUMPAD_PLUS", "NUMPAD_SLASH"}
MAX_RADIUS_PX = 2000


# ----------------------------------------------------------------------
# Brush settings (Blender Brush datablock + unified paint settings)
# ----------------------------------------------------------------------
def _vp_settings(context):
    return context.scene.tool_settings.vertex_paint


def ensure_brush(context):
    """Active vertex-paint brush, or a dedicated IOPS brush when the paint
    slot is empty (Blender 4.3+ brushes are assets; the slot is unset until
    Vertex Paint mode was entered once and is read-only from Python, so the
    fallback brush is used directly, never assigned to the slot)."""
    brush = _vp_settings(context).brush
    if brush is not None:
        return brush
    brush = bpy.data.brushes.get(IOPS_BRUSH_NAME)
    if brush is None or not brush.use_paint_vertex:
        brush = bpy.data.brushes.new(IOPS_BRUSH_NAME, mode="VERTEX_PAINT")
        brush.use_fake_user = True
    return brush


class BrushAccess:
    """Read/write radius, strength and color honoring the unified paint
    settings toggles, and expose the RNA paths radial control needs.

    When the Vertex Paint brush slot is empty the fallback brush is not
    reachable through an RNA path (the slot is read-only), so size /
    strength / color go through the unified paint settings regardless of
    their toggles — the fallback brush only supplies the falloff curve."""

    def __init__(self, context, brush):
        self.brush = brush
        vp = _vp_settings(context)
        self.ups = vp.unified_paint_settings
        self.unified_only = vp.brush is None

    @property
    def _u_size(self):
        return self.unified_only or self.ups.use_unified_size

    @property
    def _u_strength(self):
        return self.unified_only or self.ups.use_unified_strength

    @property
    def _u_color(self):
        return self.unified_only or self.ups.use_unified_color

    # -- radius (pixels) --
    @property
    def size(self):
        return int(self.ups.size if self._u_size else self.brush.size)

    @size.setter
    def size(self, value):
        v = max(MIN_RADIUS_PX, min(MAX_RADIUS_PX, int(round(value))))
        if self._u_size:
            self.ups.size = v
        else:
            self.brush.size = v

    @property
    def size_path(self):
        if self._u_size:
            return "tool_settings.vertex_paint.unified_paint_settings.size"
        return "tool_settings.vertex_paint.brush.size"

    # -- strength --
    @property
    def strength(self):
        return float(self.ups.strength if self._u_strength
                     else self.brush.strength)

    @strength.setter
    def strength(self, value):
        v = max(0.0, min(1.0, float(value)))
        if self._u_strength:
            self.ups.strength = v
        else:
            self.brush.strength = v

    @property
    def strength_path(self):
        if self._u_strength:
            return "tool_settings.vertex_paint.unified_paint_settings.strength"
        return "tool_settings.vertex_paint.brush.strength"

    # -- color (RGB) --
    @property
    def color(self):
        c = self.ups.color if self._u_color else self.brush.color
        return (float(c[0]), float(c[1]), float(c[2]))

    @color.setter
    def color(self, rgb):
        if self._u_color:
            self.ups.color = rgb
        else:
            self.brush.color = rgb

    # -- falloff --
    @property
    def preset(self):
        return self.brush.curve_distance_falloff_preset

    @preset.setter
    def preset(self, value):
        self.brush.curve_distance_falloff_preset = value

    def custom_evaluator(self):
        cm = self.brush.curve_distance_falloff
        try:
            cm.initialize()
        except Exception:
            pass
        curve = cm.curves[0]
        return lambda p, _cm=cm, _c=curve: _cm.evaluate(_c, p)

    def weight(self, p):
        preset = self.preset
        custom = self.custom_evaluator() if preset == "CUSTOM" else None
        return falloff_weight(preset, p, custom)


# ----------------------------------------------------------------------
# Mesh color access — one class per mode so the stroke code is identical
# ----------------------------------------------------------------------
def _ensure_color_attribute(me):
    """Active color attribute of `me`, created (FLOAT_COLOR / POINT) when
    the mesh has none. Returns (name, domain, data_type)."""
    ca = me.color_attributes
    attr = ca.active_color
    if attr is None:
        if len(ca) == 0:
            attr = ca.new(DEFAULT_ATTR_NAME, "FLOAT_COLOR", "POINT")
        else:
            attr = ca[0]
        ca.active_color = attr
    return attr.name, attr.domain, attr.data_type


class _EditMeshColors:
    """bmesh-backed color access (Edit Mesh mode)."""

    def __init__(self, obj):
        self.obj = obj
        self.me = obj.data
        name, self.domain, dtype = _ensure_color_attribute(self.me)
        self.bm = bmesh.from_edit_mesh(self.me)
        self.bm.verts.ensure_lookup_table()
        if self.domain == "POINT":
            layers = (self.bm.verts.layers.float_color if dtype == "FLOAT_COLOR"
                      else self.bm.verts.layers.color)
        else:
            layers = (self.bm.loops.layers.float_color if dtype == "FLOAT_COLOR"
                      else self.bm.loops.layers.color)
        self.layer = layers.get(name)
        if self.layer is None:
            # Layer just created by _ensure_color_attribute: re-fetch bmesh.
            self.bm = bmesh.from_edit_mesh(self.me)
            self.bm.verts.ensure_lookup_table()
            if self.domain == "POINT":
                layers = (self.bm.verts.layers.float_color if dtype == "FLOAT_COLOR"
                          else self.bm.verts.layers.color)
            else:
                layers = (self.bm.loops.layers.float_color if dtype == "FLOAT_COLOR"
                          else self.bm.loops.layers.color)
            self.layer = layers.get(name)
        if self.layer is None:
            raise RuntimeError(f"color attribute '{name}' has no bmesh layer")

    def count(self):
        return len(self.bm.verts)

    def coords(self):
        return [v.co.copy() for v in self.bm.verts]

    def normals(self):
        return [v.normal.copy() for v in self.bm.verts]

    def bvh(self):
        return BVHTree.FromBMesh(self.bm)

    def get(self, i):
        """Color(s) of vertex i: a 4-tuple (POINT) or a list of 4-tuples,
        one per linked loop (CORNER)."""
        v = self.bm.verts[i]
        if self.domain == "POINT":
            return tuple(v[self.layer])
        return [tuple(lp[self.layer]) for lp in v.link_loops]

    def set(self, i, value):
        v = self.bm.verts[i]
        if self.domain == "POINT":
            v[self.layer] = value
        else:
            for lp, c in zip(v.link_loops, value):
                lp[self.layer] = c

    def snapshot(self):
        return [self.get(i) for i in range(len(self.bm.verts))]

    def flush(self):
        bmesh.update_edit_mesh(self.me, loop_triangles=False, destructive=False)
        self.me.update_tag()

    def hidden(self, i):
        return self.bm.verts[i].hide

    def neighbors(self):
        """Edge-adjacent vertex indices per vertex."""
        nb = [[] for _ in range(len(self.bm.verts))]
        for e in self.bm.edges:
            a, b = e.verts
            nb[a.index].append(b.index)
            nb[b.index].append(a.index)
        return nb

    def selected(self):
        return {v.index for v in self.bm.verts if v.select and not v.hide}

    def edge_data(self):
        """(midpoints, vert index pairs) for EDGE mode."""
        self.bm.edges.ensure_lookup_table()
        mids, pairs = [], []
        for e in self.bm.edges:
            a, b = e.verts
            mids.append((a.co + b.co) * 0.5)
            pairs.append((a.index, b.index))
        return mids, pairs

    def face_data(self):
        """(centers, normals, vert index lists, per-face loop slots) for
        FACE mode. Loop slots map each face corner to (vert index, position
        in that vertex's link_loops) so CORNER colors can be written per
        face; None for POINT domain."""
        self.bm.faces.ensure_lookup_table()
        centers, normals, fverts, slots = [], [], [], []
        corner = self.domain == "CORNER"
        for f in self.bm.faces:
            centers.append(f.calc_center_median())
            normals.append(f.normal.copy())
            fverts.append([v.index for v in f.verts])
            if corner:
                fs = []
                for lp in f.loops:
                    v = lp.vert
                    pos = 0
                    for k, l2 in enumerate(v.link_loops):
                        if l2 == lp:
                            pos = k
                            break
                    fs.append((v.index, pos))
                slots.append(fs)
        return centers, normals, fverts, (slots if corner else None)


class _ObjectMeshColors:
    """color_attributes-backed access (Object mode)."""

    def __init__(self, obj):
        self.obj = obj
        self.me = obj.data
        name, self.domain, _dtype = _ensure_color_attribute(self.me)
        self.attr = self.me.color_attributes[name]
        self.vert_loops = None
        if self.domain == "CORNER":
            vl = [[] for _ in range(len(self.me.vertices))]
            for lp in self.me.loops:
                vl[lp.vertex_index].append(lp.index)
            self.vert_loops = vl

    def count(self):
        return len(self.me.vertices)

    def coords(self):
        return [v.co.copy() for v in self.me.vertices]

    def normals(self):
        return [v.normal.copy() for v in self.me.vertices]

    def bvh(self):
        verts = [v.co for v in self.me.vertices]
        polys = [tuple(p.vertices) for p in self.me.polygons]
        return BVHTree.FromPolygons(verts, polys, all_triangles=False)

    def get(self, i):
        data = self.attr.data
        if self.domain == "POINT":
            return tuple(data[i].color)
        return [tuple(data[li].color) for li in self.vert_loops[i]]

    def set(self, i, value):
        data = self.attr.data
        if self.domain == "POINT":
            data[i].color = value
        else:
            for li, c in zip(self.vert_loops[i], value):
                data[li].color = c

    def snapshot(self):
        return [self.get(i) for i in range(len(self.me.vertices))]

    def flush(self):
        self.me.update_tag()

    def hidden(self, i):
        return self.me.vertices[i].hide

    def neighbors(self):
        nb = [[] for _ in range(len(self.me.vertices))]
        for e in self.me.edges:
            a, b = e.vertices
            nb[a].append(b)
            nb[b].append(a)
        return nb

    def selected(self):
        return {v.index for v in self.me.vertices if v.select and not v.hide}

    def edge_data(self):
        verts = self.me.vertices
        mids, pairs = [], []
        for e in self.me.edges:
            a, b = e.vertices
            mids.append((verts[a].co + verts[b].co) * 0.5)
            pairs.append((a, b))
        return mids, pairs

    def face_data(self):
        centers, normals, fverts, slots = [], [], [], []
        corner = self.domain == "CORNER"
        loops = self.me.loops
        for p in self.me.polygons:
            centers.append(p.center.copy())
            normals.append(p.normal.copy())
            fverts.append(list(p.vertices))
            if corner:
                fs = []
                for li in p.loop_indices:
                    v = loops[li].vertex_index
                    fs.append((v, self.vert_loops[v].index(li)))
                slots.append(fs)
        return centers, normals, fverts, (slots if corner else None)


# ----------------------------------------------------------------------
# Operator
# ----------------------------------------------------------------------
class IOPS_OT_MeshVertexPaint(bpy.types.Operator):
    """Paint vertex colors with a brush in Edit Mesh or Object mode, without
    entering Vertex Paint mode. Uses the Vertex Paint brush settings
    (size / strength / color / falloff)"""

    bl_idname = "iops.mesh_vertex_paint"
    bl_label = "Vertex Paint Brush"
    bl_options = {"REGISTER", "UNDO"}

    use_start_color: BoolProperty(
        name="Use Start Color",
        description="Set the brush color to Start Color when the brush starts",
        default=False,
        options={"SKIP_SAVE"},
    )
    start_color: FloatVectorProperty(
        name="Start Color",
        description="Brush RGB to start with (alpha is the brush alpha)",
        size=4, subtype="COLOR", min=0.0, max=1.0,
        default=(1.0, 1.0, 1.0, 1.0),
        options={"SKIP_SAVE"},
    )

    @classmethod
    def poll(cls, context):
        obj = context.object
        return (obj is not None and obj.type == "MESH"
                and context.mode in {"EDIT_MESH", "OBJECT"}
                and context.area is not None and context.area.type == "VIEW_3D")

    # ------------------------------------------------------------------
    # Invoke / setup
    # ------------------------------------------------------------------
    def invoke(self, context, event):
        obj = context.object
        self.obj = obj
        self.mode = context.mode
        try:
            self.colors = (_EditMeshColors(obj) if self.mode == "EDIT_MESH"
                           else _ObjectMeshColors(obj))
        except RuntimeError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        if self.colors.count() == 0:
            self.report({"WARNING"}, "Mesh has no vertices")
            return {"CANCELLED"}

        self.brush = ensure_brush(context)
        self.ba = BrushAccess(context, self.brush)
        if self.use_start_color:
            self.ba.color = tuple(self.start_color[:3])
            context.scene.IOPS.iops_vp_alpha = float(self.start_color[3])

        # Geometry caches (object local space).
        self._coords = self.colors.coords()
        self._normals = self.colors.normals()
        self._bvh = self.colors.bvh()
        self._kd = KDTree(len(self._coords))
        for i, co in enumerate(self._coords):
            self._kd.insert(co, i)
        self._kd.balance()
        # EDGE / FACE mode caches, built on first use.
        self._kd_edges = None
        self._edge_verts = None
        self._kd_faces = None
        self._neighbors = None
        self._face_normals = None
        self._face_verts = None
        self._face_slots = None
        self._mw = obj.matrix_world.copy()
        self._mw_inv = self._mw.inverted_safe()

        # Session snapshot (Esc + eraser target) and stroke history.
        self._orig = self.colors.snapshot()
        self._hist = StrokeHistory(limit=128)
        self._stroke_max = {}        # vert index -> per-stroke max weight
        self._stroke_base = {}       # vert index -> color at stroke start
        self._painting = False
        self._erase_now = False
        self._last_dab = None        # last dab mouse position (px)
        self._hit_local = None       # hit under the cursor (local) or None
        self._mouse = (event.mouse_region_x, event.mouse_region_y)
        self._radius_world = 0.0
        self._pressure = 1.0      # tablet pressure of the current stroke

        self._muted_mods = []
        if context.scene.IOPS.iops_vp_mute_modifiers:
            self._mute_modifiers(True)

        self._build_hud(context, event)
        self._handle = safe_handler_add(
            bpy.types.SpaceView3D, self._draw_callback, (context,),
            "WINDOW", "POST_PIXEL", tick=True)
        context.window_manager.modal_handler_add(self)
        context.workspace.status_text_set(self._status_text(context))
        context.area.tag_redraw()
        return {"RUNNING_MODAL"}

    def _build_hud(self, context, event):
        self._hud = HUDOverlay("mesh_vertex_paint")
        self._hud.title = "Vertex Paint"
        self._hud.bind_region(context.region)
        self._help = HelpOverlay("mesh_vertex_paint")
        def item(label, key):
            return HUDItem(label, key, ItemState.ON, default_state=ItemState.OFF,
                           always_show=True)

        self._help.add_section(HUDSection("Brush", [
            item("Radius / Strength (radial)", "F / Shift+F"),
            item("Radius / Strength", "Ctrl+Wheel / Shift+Wheel"),
            item("Radius", "[ / ]"),
            item("Falloff preset", "Alt+Wheel"),
            item("Front faces only (toggle)", "N"),
            item("Mute modifiers (toggle)", "M"),
            item("Preview VC (toggle)", "P"),
            item("Wireframe overlay (toggle)", "V"),
        ]))
        self._help.add_section(HUDSection("Element", [
            item("Vert / Edge / Face", "1 / 2 / 3"),
        ]))
        self._help.add_section(HUDSection("Color", [
            item("Red / Green / Blue", "R / G / B"),
            item("Black / White", "K / W"),
            item("RGB / Alpha channel (toggle)", "A"),
            item("Alpha 0 / 1", "Shift+0 / Shift+1"),
        ]))
        self._help.add_section(HUDSection("Paint", [
            item("Paint", "LMB drag"),
            item("Erase (restore original)", "Ctrl+LMB / E"),
            item("Paint / Blur tool (toggle)", "T"),
            item("Undo / Redo stroke", "Ctrl+Z / Ctrl+Shift+Z"),
        ]))
        self._help.add_section(HUDSection("Session", [
            item("Finish", "Enter / Space / RMB"),
            item("Cancel (restore all)", "Esc"),
            item("Orbit / Zoom / Views", "MMB / Wheel / Numpad"),
            item("Help / Toggle HUD", "H"),
        ]))
        self._help.bind_region(context.region)
        self._last_event = capture_event(event, None)

    # ------------------------------------------------------------------
    # Modifiers
    # ------------------------------------------------------------------
    def _mute_modifiers(self, mute):
        try:
            mods = self.obj.modifiers
        except ReferenceError:
            return
        if mute:
            if self._muted_mods:
                return
            for m in mods:
                if m.show_viewport:
                    m.show_viewport = False
                    self._muted_mods.append(m.name)
        else:
            for name in self._muted_mods:
                m = mods.get(name)
                if m is not None:
                    m.show_viewport = True
            self._muted_mods = []

    # ------------------------------------------------------------------
    # Picking
    # ------------------------------------------------------------------
    def _ray_local(self, context, mx, my):
        region, rv3d = context.region, context.region_data
        origin = view3d_utils.region_2d_to_origin_3d(region, rv3d, (mx, my))
        direction = view3d_utils.region_2d_to_vector_3d(region, rv3d, (mx, my))
        o = self._mw_inv @ origin
        d = (self._mw_inv.to_3x3() @ direction)
        if d.length_squared < 1e-20:
            return None, None
        return o, d.normalized()

    def _pick(self, context, mx, my):
        """Hit on the base mesh under (mx, my): (local_point, local_ray_dir,
        face_index) or (None, None, None)."""
        o, d = self._ray_local(context, mx, my)
        if o is None:
            return None, None, None
        loc, _normal, idx, _dist = self._bvh.ray_cast(o, d)
        if loc is None:
            return None, None, None
        return loc, d, idx

    def _edge_kd(self):
        if self._kd_edges is None:
            mids, self._edge_verts = self.colors.edge_data()
            kd = KDTree(len(mids))
            for i, co in enumerate(mids):
                kd.insert(co, i)
            kd.balance()
            self._kd_edges = kd
        return self._kd_edges

    def _face_kd(self):
        if self._kd_faces is None:
            centers, self._face_normals, self._face_verts, self._face_slots = \
                self.colors.face_data()
            kd = KDTree(len(centers))
            for i, co in enumerate(centers):
                kd.insert(co, i)
            kd.balance()
            self._kd_faces = kd
        return self._kd_faces

    def _radius_local(self, context, mx, my, hit_local):
        """Brush radius in object-local units at the depth of `hit_local`."""
        region, rv3d = context.region, context.region_data
        hit_world = self._mw @ hit_local
        px = float(self.ba.size)
        if self.brush.use_pressure_size:
            px *= self._pressure
        p1 = view3d_utils.region_2d_to_location_3d(region, rv3d, (mx, my), hit_world)
        p2 = view3d_utils.region_2d_to_location_3d(region, rv3d, (mx + px, my), hit_world)
        self._radius_world = (p2 - p1).length
        return ((self._mw_inv @ p2) - (self._mw_inv @ p1)).length

    # ------------------------------------------------------------------
    # Painting
    # ------------------------------------------------------------------
    def _target_for(self, i, context):
        """Color to blend toward for vertex i: brush RGBA, or the session
        original when erasing."""
        if self._erase_now:
            return self._orig[i]
        rgb = self.ba.color
        a = float(context.scene.IOPS.iops_vp_alpha)
        return (rgb[0], rgb[1], rgb[2], a)

    def _dab(self, context, mx, my):
        hit, ray_dir, hit_face = self._pick(context, mx, my)
        self._hit_local = hit
        if hit is None:
            return False
        r = self._radius_local(context, mx, my, hit)
        if r <= 0.0:
            return False
        props = context.scene.IOPS
        front_only = props.iops_vp_front_only
        preset = self.ba.preset
        custom = self.ba.custom_evaluator() if preset == "CUSTOM" else None
        element = props.iops_vp_element
        changed = False

        if element == "VERT":
            for _co, i, dist in self._kd.find_range(hit, r):
                if front_only and self._normals[i].dot(ray_dir) > 0.0:
                    continue
                w = falloff_weight(preset, dist / r, custom)
                if w > 0.0:
                    changed |= self._paint_vertex(context, i, w, None)
        elif element == "EDGE":
            kd = self._edge_kd()
            for _co, ei, dist in kd.find_range(hit, r):
                w = falloff_weight(preset, dist / r, custom)
                if w <= 0.0:
                    continue
                for i in self._edge_verts[ei]:
                    if front_only and self._normals[i].dot(ray_dir) > 0.0:
                        continue
                    changed |= self._paint_vertex(context, i, w, None)
        else:  # FACE
            kd = self._face_kd()
            faces = {}
            for _co, fi, dist in kd.find_range(hit, r):
                faces[fi] = falloff_weight(preset, dist / r, custom)
            if hit_face is not None and 0 <= hit_face < len(self._face_verts):
                faces[hit_face] = 1.0      # the face under the cursor always
            slots = self._face_slots
            for fi, w in faces.items():
                if w <= 0.0:
                    continue
                if front_only and self._face_normals[fi].dot(ray_dir) > 0.0:
                    continue
                if slots is None:
                    for i in self._face_verts[fi]:
                        changed |= self._paint_vertex(context, i, w, None)
                else:
                    for i, pos in slots[fi]:
                        changed |= self._paint_vertex(context, i, w, pos)
        return changed

    def _paint_vertex(self, context, i, w, slot):
        """Blend vertex i toward the brush target by weight `w` (before
        strength). `slot` restricts a CORNER-domain write to one linked
        loop (FACE mode); None writes every loop / the point color.
        Non-accumulating within a stroke: keyed per vertex, or per
        (vertex, slot) for face corners."""
        colors = self.colors
        if colors.hidden(i):
            return False
        strength = self.ba.strength
        if self.brush.use_pressure_strength:
            strength *= self._pressure
        if context.scene.IOPS.iops_vp_tool == "BLUR" and not self._erase_now:
            return self._blur_vertex(context, i, w * strength, slot)
        key = i if slot is None else (i, slot)
        prev = self._stroke_max.get(key, 0.0)
        m, eff = stroke_weight(prev, w, strength)
        if m <= prev:
            return False
        self._stroke_max[key] = m
        if i not in self._stroke_base:
            base = colors.get(i)
            self._stroke_base[i] = base
            self._hist.touch(i, base)
        base = self._stroke_base[i]
        target = self._target_for(i, context)
        channel = context.scene.IOPS.iops_vp_channel
        if isinstance(base, list):
            # CORNER domain: one color per linked loop. The eraser target
            # is the per-loop original list; the brush target is a single
            # RGBA applied to the written loops.
            tg = target if isinstance(target, list) else [target] * len(base)
            if slot is None:
                value = [blend_color(b, t, eff, channel) for b, t in zip(base, tg)]
            else:
                value = list(colors.get(i))
                value[slot] = blend_color(base[slot], tg[slot], eff, channel)
        else:
            value = blend_color(base, target, eff, channel)
        colors.set(i, value)
        return True

    def _blur_vertex(self, context, i, eff, slot):
        """Blur tool: move vertex i's corners toward the mean of its
        neighborhood (own corners + edge-adjacent vertices' corners) by
        eff * BLUR_RATE. Accumulates across dabs; reads live colors so
        repeated passes keep smoothing."""
        eff = max(0.0, min(1.0, eff)) * BLUR_RATE
        if eff <= 0.0:
            return False
        colors = self.colors
        if self._neighbors is None:
            self._neighbors = colors.neighbors()
        if i not in self._stroke_base:
            base = colors.get(i)
            self._stroke_base[i] = base
            self._hist.touch(i, base)
        cur = colors.get(i)
        pool_vals = {i: cur if isinstance(cur, list) else [cur]}
        for j in self._neighbors[i]:
            cj = colors.get(j)
            pool_vals[j] = cj if isinstance(cj, list) else [cj]
        nb = {i: self._neighbors[i]}
        mean = neighborhood_mean(i, pool_vals, nb)
        channel = context.scene.IOPS.iops_vp_channel
        if isinstance(cur, list):
            if slot is None:
                value = [filter_color(c, mean, "BLUR", eff, channel) for c in cur]
            else:
                value = list(cur)
                value[slot] = filter_color(cur[slot], mean, "BLUR", eff, channel)
        else:
            value = filter_color(cur, mean, "BLUR", eff, channel)
        colors.set(i, value)
        return True

    def _stroke_begin(self, context, event):
        self._painting = True
        self._erase_now = bool(event.ctrl) or bool(context.scene.IOPS.iops_vp_eraser)
        self._pressure = _event_pressure(event)
        self._stroke_max = {}
        self._stroke_base = {}
        self._hist.begin()
        self._last_dab = (event.mouse_region_x, event.mouse_region_y)
        if self._dab(context, *self._last_dab):
            self.colors.flush()

    def _stroke_move(self, context, event):
        self._pressure = _event_pressure(event)
        mx, my = event.mouse_region_x, event.mouse_region_y
        lx, ly = self._last_dab if self._last_dab else (mx, my)
        dist = math.hypot(mx - lx, my - ly)
        step = max(1.0, self.ba.size * DAB_SPACING)
        changed = False
        if dist > step:
            n = int(dist // step)
            for k in range(1, n + 1):
                t = k / (n + 1)
                changed |= self._dab(context, lx + (mx - lx) * t, ly + (my - ly) * t)
        changed |= self._dab(context, mx, my)
        self._last_dab = (mx, my)
        if changed:
            self.colors.flush()

    def _stroke_end(self, context):
        self._painting = False
        self._hist.commit(self.colors.get)
        self._stroke_max = {}
        self._stroke_base = {}
        self._last_dab = None

    def _apply_map(self, values):
        if not values:
            return
        for i, v in values.items():
            self.colors.set(i, v)
        self.colors.flush()

    # ------------------------------------------------------------------
    # Modal
    # ------------------------------------------------------------------
    def modal(self, context, event):
        try:
            return self._modal(context, event)
        except ReferenceError:
            # Object or mesh went away (file reload, delete) — bail cleanly.
            self._cleanup(context)
            return {"CANCELLED"}

    def _modal(self, context, event):
        if context.area:
            context.area.tag_redraw()
        self._last_event = capture_event(event, getattr(self, "_last_event", None))
        props = context.scene.IOPS
        mx, my = event.mouse_region_x, event.mouse_region_y
        self._mouse = (mx, my)

        try:
            theme_prefs = context.preferences.addons["InteractionOps"].preferences.iops_theme
        except (KeyError, AttributeError):
            theme_prefs = None
        if theme_prefs is not None and not self._painting:
            if self._help.handle_drag_event(context, event, theme_prefs):
                return {"RUNNING_MODAL"}
            if self._hud.handle_drag_event(context, event, theme_prefs):
                return {"RUNNING_MODAL"}
            if self._help.handle_toggle_event(event, theme_prefs):
                return {"RUNNING_MODAL"}
            if self._hud.handle_param_toggle_event(event, theme_prefs):
                return {"RUNNING_MODAL"}

        # Let viewport navigation through (plain wheel = zoom; the brush
        # uses the wheel only with Ctrl / Shift / Alt).
        if not self._painting:
            if event.type in NAV_TYPES or event.type.startswith("NDOF"):
                return {"PASS_THROUGH"}
            if event.type in {"WHEELUPMOUSE", "WHEELDOWNMOUSE"} \
                    and not (event.ctrl or event.shift or event.alt):
                return {"PASS_THROUGH"}

        # Clicks on iOps widget panels (e.g. the Vertex Color widget) pass
        # through so its swatches / flipboxes stay usable while painting.
        if not self._painting and event.type in {"LEFTMOUSE", "MOUSEMOVE"}:
            if self._over_widget(context, mx, my):
                self._hit_local = None
                return {"PASS_THROUGH"}

        # Stroke in progress.
        if self._painting:
            if event.type == "MOUSEMOVE":
                self._stroke_move(context, event)
                return {"RUNNING_MODAL"}
            if event.type == "LEFTMOUSE" and event.value == "RELEASE":
                self._stroke_move(context, event)
                self._stroke_end(context)
                return {"RUNNING_MODAL"}
            if event.type == "ESC" and event.value == "PRESS":
                self._apply_map(self._hist.cancel())
                self._painting = False
                self._stroke_max = {}
                self._stroke_base = {}
                return {"RUNNING_MODAL"}
            return {"RUNNING_MODAL"}

        if event.type == "MOUSEMOVE":
            self._hit_local, _d, _f = self._pick(context, mx, my)
            if self._hit_local is not None:
                self._radius_local(context, mx, my, self._hit_local)
            return {"RUNNING_MODAL"}

        if event.type == "LEFTMOUSE" and event.value == "PRESS":
            self._stroke_begin(context, event)
            return {"RUNNING_MODAL"}

        # -- wheel: radius / strength / preset --
        if event.type in {"WHEELUPMOUSE", "WHEELDOWNMOUSE"}:
            up = event.type == "WHEELUPMOUSE"
            if event.ctrl:
                s = self.ba.size
                self.ba.size = s * (1.15 if up else 1.0 / 1.15) + (1 if up else -1)
            elif event.shift:
                self.ba.strength = self.ba.strength + (0.05 if up else -0.05)
            elif event.alt:
                self.ba.preset = next_preset(self.ba.preset, 1 if up else -1)
            if self._hit_local is not None:
                self._radius_local(context, mx, my, self._hit_local)
            self._set_status(context)
            return {"RUNNING_MODAL"}

        if event.value != "PRESS":
            return {"RUNNING_MODAL"}

        # -- keys --
        if event.type == "F":
            path = self.ba.strength_path if event.shift else self.ba.size_path
            try:
                bpy.ops.wm.radial_control("INVOKE_DEFAULT", data_path_primary=path,
                                          release_confirm=False)
            except RuntimeError as exc:
                self.report({"WARNING"}, f"Radial control unavailable: {exc}")
            return {"RUNNING_MODAL"}
        if event.type in QUICK_COLORS and not (event.ctrl or event.alt):
            self.ba.color = QUICK_COLORS[event.type]
            self._set_status(context)
            return {"RUNNING_MODAL"}
        if event.type == "A":
            props.iops_vp_channel = "ALPHA" if props.iops_vp_channel == "RGB" else "RGB"
            self._set_status(context)
            return {"RUNNING_MODAL"}
        if event.type in {"LEFT_BRACKET", "RIGHT_BRACKET"}:
            up = event.type == "RIGHT_BRACKET"
            s = self.ba.size
            self.ba.size = s * (1.15 if up else 1.0 / 1.15) + (1 if up else -1)
            self._set_status(context)
            return {"RUNNING_MODAL"}
        if event.type == "ZERO" and event.shift:
            props.iops_vp_alpha = 0.0
            self._set_status(context)
            return {"RUNNING_MODAL"}
        if event.type == "ONE" and event.shift:
            props.iops_vp_alpha = 1.0
            self._set_status(context)
            return {"RUNNING_MODAL"}
        if event.type in ELEMENT_KEYS and not (event.ctrl or event.alt):
            props.iops_vp_element = ELEMENT_KEYS[event.type]
            self._set_status(context)
            return {"RUNNING_MODAL"}
        if event.type == "E":
            props.iops_vp_eraser = not props.iops_vp_eraser
            self._set_status(context)
            return {"RUNNING_MODAL"}
        if event.type == "N":
            props.iops_vp_front_only = not props.iops_vp_front_only
            self._set_status(context)
            return {"RUNNING_MODAL"}
        if event.type == "T":
            props.iops_vp_tool = "BLUR" if props.iops_vp_tool == "PAINT" else "PAINT"
            self._set_status(context)
            return {"RUNNING_MODAL"}
        if event.type == "V":
            ov = getattr(context.space_data, "overlay", None)
            if ov is not None:
                ov.show_wireframes = not ov.show_wireframes
            return {"RUNNING_MODAL"}
        if event.type == "P":
            # Property update runs vc_preview_set (material override +
            # shading switch); the same toggle the widget / panel use.
            props.iops_vc_preview = not props.iops_vc_preview
            self._set_status(context)
            return {"RUNNING_MODAL"}
        if event.type == "M":
            props.iops_vp_mute_modifiers = not props.iops_vp_mute_modifiers
            self._mute_modifiers(props.iops_vp_mute_modifiers)
            self._set_status(context)
            return {"RUNNING_MODAL"}
        if event.type == "Z" and event.ctrl:
            values = self._hist.redo() if event.shift else self._hist.undo()
            if values is None:
                self.report({"INFO"}, "Nothing to redo" if event.shift else "Nothing to undo")
            else:
                self._apply_map(values)
            return {"RUNNING_MODAL"}
        if event.type in {"RET", "NUMPAD_ENTER", "SPACE", "RIGHTMOUSE"}:
            return self._finish(context)
        if event.type == "ESC":
            return self._cancel(context)
        return {"RUNNING_MODAL"}

    def _over_widget(self, context, mx, my):
        try:
            from ..ui.widgets import state as widget_state
            return widget_state.widget_under_mouse(context.area, mx, my) is not None
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Finish / cancel
    # ------------------------------------------------------------------
    def _finish(self, context):
        if self._painting:
            self._stroke_end(context)
        self._cleanup(context)
        n = len(self._hist)
        self.report({"INFO"}, f"Vertex paint: {n} stroke(s)")
        return {"FINISHED"}

    def _cancel(self, context):
        if self._painting:
            self._apply_map(self._hist.cancel())
            self._painting = False
        self._apply_map({i: c for i, c in enumerate(self._orig)})
        self._cleanup(context)
        return {"CANCELLED"}

    def _cleanup(self, context):
        self._mute_modifiers(False)
        h = getattr(self, "_handle", None)
        if h is not None:
            try:
                safe_handler_remove(h, bpy.types.SpaceView3D, "WINDOW")
            except (ValueError, RuntimeError, ReferenceError):
                pass
            self._handle = None
        try:
            context.workspace.status_text_set(None)
        except (AttributeError, ReferenceError):
            pass
        if context.area:
            context.area.tag_redraw()

    # ------------------------------------------------------------------
    # Status / HUD / draw
    # ------------------------------------------------------------------
    def _status_text(self, context):
        props = context.scene.IOPS
        erase = "Erase" if props.iops_vp_eraser else props.iops_vp_tool.title()
        return (f"Vertex Paint — {erase} | {props.iops_vp_element} | {props.iops_vp_channel} | "
                f"Radius {self.ba.size}px  Strength {self.ba.strength:.2f}  "
                f"Falloff {self.ba.preset} | LMB paint  Ctrl+LMB erase  "
                f"F/Shift+F radius/strength  R G B K W colors  A alpha  "
                f"Ctrl+Z undo  Enter finish  Esc cancel")

    def _set_status(self, context):
        try:
            context.workspace.status_text_set(self._status_text(context))
        except (AttributeError, ReferenceError):
            pass

    def _draw_callback(self, context):
        try:
            _ = self.obj.name
        except (ReferenceError, AttributeError):
            h = getattr(self, "_handle", None)
            if h is not None:
                try:
                    safe_handler_remove(h, bpy.types.SpaceView3D, "WINDOW")
                except (ValueError, RuntimeError, ReferenceError):
                    pass
            return
        import gpu
        theme = get_theme(context)
        props = context.scene.IOPS
        gpu.state.blend_set("ALPHA")
        self._draw_brush(context, theme, props)
        gpu.state.blend_set("NONE")
        self._draw_hud(context, props)

    def _draw_brush(self, context, theme, props):
        mx, my = self._mouse
        r = float(self.ba.size)
        rgb = self.ba.color
        srgb = _to_srgb(rgb)
        erase = props.iops_vp_eraser or (self._painting and self._erase_now)
        if erase:
            ring = theme.color_for(Role.ERROR_LINE)
        elif props.iops_vp_tool == "BLUR":
            ring = theme.color_for(Role.HANDLE)
        elif props.iops_vp_channel == "ALPHA":
            a = props.iops_vp_alpha
            ring = (a, a, a, 1.0)
        else:
            ring = (srgb[0], srgb[1], srgb[2], 1.0)
        on_mesh = self._hit_local is not None
        alpha = 1.0 if on_mesh else 0.35
        ring = (ring[0], ring[1], ring[2], alpha)
        segs = 48
        pts = [(mx + math.cos(2 * math.pi * k / segs) * r,
                my + math.sin(2 * math.pi * k / segs) * r, 0.0) for k in range(segs)]
        pts.append(pts[0])
        draw_prim.polyline(pts, color=ring, width="default", theme=theme, context=context)
        # Falloff hint: ring where the weight drops to 50%.
        p50 = self._half_weight_fraction()
        if 0.0 < p50 < 1.0:
            r2 = r * p50
            pts2 = [(mx + math.cos(2 * math.pi * k / segs) * r2,
                     my + math.sin(2 * math.pi * k / segs) * r2, 0.0) for k in range(segs)]
            pts2.append(pts2[0])
            draw_prim.polyline(pts2, color=(ring[0], ring[1], ring[2], alpha * 0.4),
                               width="default", theme=theme, context=context)
        # Color chip at the center.
        chip = 5.0
        draw_prim.rect_2d(mx - chip, my - chip, chip * 2, chip * 2,
                          color=(srgb[0], srgb[1], srgb[2], 0.9 if on_mesh else 0.4),
                          theme=theme, context=context)

    def _half_weight_fraction(self):
        try:
            preset = self.ba.preset
            custom = self.ba.custom_evaluator() if preset == "CUSTOM" else None
            lo, hi = 0.0, 1.0
            for _ in range(12):
                mid = (lo + hi) * 0.5
                if falloff_weight(preset, mid, custom) > 0.5:
                    lo = mid
                else:
                    hi = mid
            return (lo + hi) * 0.5
        except Exception:
            return 0.0

    def _draw_hud(self, context, props):
        last_event = getattr(self, "_last_event", None)
        self._help.draw(context, last_event)
        rgb = self.ba.color
        lines = [
            "Mode: " + ("ERASE" if props.iops_vp_eraser else props.iops_vp_tool),
            f"Element: {props.iops_vp_element}   Channel: {props.iops_vp_channel}",
            f"Color: {rgb[0]:.2f} {rgb[1]:.2f} {rgb[2]:.2f}  A {props.iops_vp_alpha:.2f}",
            f"Radius: {self.ba.size}px  Strength: {self.ba.strength:.2f}",
            f"Falloff: {self.ba.preset}",
            f"Strokes: {len(self._hist)}" + (f"  (redo {self._hist.redo_depth})" if self._hist.redo_depth else ""),
        ]
        if self._muted_mods:
            lines.append(f"Modifiers muted: {len(self._muted_mods)}")
        if not props.iops_vp_front_only:
            lines.append("Back faces: painted")
        if props.iops_vc_preview:
            lines.append("Preview VC: ON")
        self._hud.set_header(*lines)
        self._hud.draw(context, last_event)


class IOPS_OT_MeshVertexColorFilter(bpy.types.Operator):
    """Blur or sharpen the active color attribute over the whole mesh
    (Object mode) or the selected vertices (Edit Mesh mode) — a
    post-process pass, adjustable in the redo panel"""

    bl_idname = "iops.mesh_vertex_color_filter"
    bl_label = "Vertex Color Blur / Sharpen"
    bl_options = {"REGISTER", "UNDO"}

    mode: EnumProperty(
        name="Mode",
        items=[("BLUR", "Blur", "Move every color toward its neighborhood mean"),
               ("SHARPEN", "Sharpen", "Push every color away from its neighborhood mean")],
        default="BLUR",
    )
    amount: FloatProperty(name="Amount", default=0.5, min=0.0, max=1.0, subtype="FACTOR")
    iterations: IntProperty(name="Iterations", default=1, min=1, max=50)
    channel: EnumProperty(
        name="Channels",
        items=[("RGB", "RGB", "Color only, alpha kept"),
               ("ALPHA", "Alpha", "Alpha only"),
               ("RGBA", "RGBA", "Color and alpha")],
        default="RGB",
    )
    selected_only: BoolProperty(
        name="Selected Only",
        description="Edit Mesh mode: change only the selected vertices "
                    "(unselected ones still contribute to the means)",
        default=True,
    )

    @classmethod
    def poll(cls, context):
        obj = context.object
        return (obj is not None and obj.type == "MESH"
                and context.mode in {"EDIT_MESH", "OBJECT"})

    def execute(self, context):
        obj = context.object
        try:
            colors = (_EditMeshColors(obj) if context.mode == "EDIT_MESH"
                      else _ObjectMeshColors(obj))
        except RuntimeError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        n = colors.count()
        if n == 0:
            return {"CANCELLED"}
        snap = colors.snapshot()
        vals = [c if isinstance(c, list) else [c] for c in snap]
        mask = None
        if context.mode == "EDIT_MESH" and self.selected_only:
            mask = colors.selected()
            if not mask:
                self.report({"WARNING"}, "No selected vertices")
                return {"CANCELLED"}
        out = filter_vertex_colors(vals, colors.neighbors(), self.mode,
                                   self.amount, self.iterations, mask,
                                   self.channel)
        point = colors.domain == "POINT"
        for i in range(n):
            if mask is not None and i not in mask:
                continue
            colors.set(i, out[i][0] if point else out[i])
        colors.flush()
        if context.area:
            context.area.tag_redraw()
        return {"FINISHED"}

    def draw(self, context):
        col = self.layout.column(align=True)
        col.prop(self, "mode", expand=True)
        col.prop(self, "amount", slider=True)
        col.prop(self, "iterations")
        col.prop(self, "channel", expand=True)
        if context.mode == "EDIT_MESH":
            col.prop(self, "selected_only")


def _event_pressure(event):
    """Tablet pressure in (0, 1]; a mouse reports 1.0."""
    try:
        p = float(event.pressure)
    except (AttributeError, TypeError):
        return 1.0
    return max(0.05, min(1.0, p)) if p > 0.0 else 1.0


def _to_srgb(rgb):
    out = []
    for c in rgb:
        c = max(0.0, min(1.0, float(c)))
        out.append(12.92 * c if c <= 0.0031308 else 1.055 * (c ** (1.0 / 2.4)) - 0.055)
    return tuple(out)
