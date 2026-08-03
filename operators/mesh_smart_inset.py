"""Smart Inset — bmesh bridge over the pure 2D wavefront core.

The heavy lifting (simplified straight skeleton / weighted wavefront) lives in
``utils/smart_inset_core.py`` and knows nothing about bpy. This module is the
bridge:

1. group the selected faces into regions (connected components, or one region
   per face in INDIVIDUAL mode),
2. extract each region's boundary loops keeping the region on the left,
3. fit a plane, project the loops to 2D (outer loop CCW when viewed down the
   region normal — the winding the core requires),
4. run the core timeline and rebuild geometry at the requested thickness:
   one wall face per original boundary edge plus an ngon per surviving front
   loop.

Curved regions are handled approximately by design: new verts are pulled back
onto the original surface with a BVH nearest-point query.
"""
import bpy
import bmesh
from mathutils import Vector
from mathutils.bvhtree import BVHTree
from bpy_extras import view3d_utils
from bpy.props import FloatProperty, BoolProperty, EnumProperty

from ..utils import smart_inset_core as core
from ..ui.draw import primitives as draw, draw_scope, Role
from ..ui.draw import safe_handler_add, safe_handler_remove
from ..ui.hud import (HUDOverlay, HelpOverlay, HUDSection, HUDItem,
                      HUDParam, ItemState, capture_event)


EPS = 1e-9
# Same threshold core.sanitize_loops uses to merge near-duplicate points.
MIN_EDGE_2D = 1e-6
# Rounding used to weld skeleton nodes shared by several walls.
WELD_DIGITS = 6

DIGIT_TYPES = {
    "ZERO": "0", "ONE": "1", "TWO": "2", "THREE": "3", "FOUR": "4",
    "FIVE": "5", "SIX": "6", "SEVEN": "7", "EIGHT": "8", "NINE": "9",
    "NUMPAD_0": "0", "NUMPAD_1": "1", "NUMPAD_2": "2", "NUMPAD_3": "3",
    "NUMPAD_4": "4", "NUMPAD_5": "5", "NUMPAD_6": "6", "NUMPAD_7": "7",
    "NUMPAD_8": "8", "NUMPAD_9": "9",
}


_ACTIVE_HANDLES = set()


def _purge_handles():
    """Remove any stale draw handlers left behind by a previous reload."""
    while _ACTIVE_HANDLES:
        h = _ACTIVE_HANDLES.pop()
        try:
            safe_handler_remove(h, bpy.types.SpaceView3D, "WINDOW")
        except (ValueError, RuntimeError):
            pass


class RegionError(Exception):
    """Raised when a selection cannot be turned into a usable region."""


class Region:
    """Everything the bridge needs to know about one inset region."""

    __slots__ = ("faces", "loops3d", "plane_origin", "basis", "weights",
                 "loops2d", "edge_orig_verts", "bvh")

    def __init__(self, faces):
        self.faces = list(faces)
        self.loops3d = []          # list[list[BMVert]] — region on the left
        self.plane_origin = Vector((0.0, 0.0, 0.0))
        self.basis = (Vector((1.0, 0.0, 0.0)),
                      Vector((0.0, 1.0, 0.0)),
                      Vector((0.0, 0.0, 1.0)))
        self.weights = []          # weights[li][i] — weight of edge i->i+1
        self.loops2d = []          # list[list[(x, y)]]
        self.edge_orig_verts = []  # core edge id -> (BMVert a, BMVert b)
        self.bvh = None


# --------------------------------------------------------------------------
# Region collection
# --------------------------------------------------------------------------


def collect_regions(bm, mode):
    """Group selected faces into regions. Unusable groups are skipped.

    Returns ``(regions, warnings)`` so the caller can report per-region
    failures without aborting the whole operation.
    """
    sel = [f for f in bm.faces if f.select and not f.hide]
    if mode == 'INDIVIDUAL':
        groups = [[f] for f in sel]
    else:
        groups, seen = [], set()
        for f in sel:
            if f in seen:
                continue
            stack, comp = [f], []
            seen.add(f)
            while stack:
                cur = stack.pop()
                comp.append(cur)
                for e in cur.edges:
                    for lf in e.link_faces:
                        if lf.select and not lf.hide and lf not in seen:
                            seen.add(lf)
                            stack.append(lf)
            groups.append(comp)

    regions, warnings = [], []
    for g in groups:
        try:
            regions.append(_build_region(g))
        except RegionError as ex:
            warnings.append(str(ex))
    return regions, warnings


def _boundary_loops(faces):
    """Boundary loops of a face set, oriented with the region on the left.

    A face's own loops run CCW around its normal, so the region is on the
    left of ``loop.vert -> loop.link_loop_next.vert``. Following that
    direction gives a CCW outer loop and CW hole loops.
    """
    fset = set(faces)
    nxt = {}
    border = {}
    for f in faces:
        for loop in f.loops:
            e = loop.edge
            if sum(1 for lf in e.link_faces if lf in fset) != 1:
                continue
            a, b = loop.vert, loop.link_loop_next.vert
            if a in nxt:
                raise RegionError("non-manifold boundary junction")
            nxt[a] = b
            # True for an open mesh border (the region edge has no
            # neighbouring face at all).
            border[a] = len(e.link_faces) == 1

    loops3d, borders = [], []
    while nxt:
        start = next(iter(nxt))
        loop = []
        flags = []
        cur = start
        while True:
            if cur not in nxt:
                raise RegionError("open/non-manifold boundary")
            nx = nxt.pop(cur)
            loop.append(cur)
            flags.append(border[cur])
            cur = nx
            if cur is start:
                break
        if len(loop) < 3:
            raise RegionError("boundary loop shorter than 3 verts")
        loops3d.append(loop)
        borders.append(flags)
    if not loops3d:
        raise RegionError("no boundary edges")
    return loops3d, borders


def _fit_plane(faces):
    """Area-weighted average normal + centroid of the region."""
    n = Vector((0.0, 0.0, 0.0))
    c = Vector((0.0, 0.0, 0.0))
    total = 0.0
    for f in faces:
        a = f.calc_area()
        n += f.normal * a
        c += f.calc_center_median() * a
        total += a
    if total <= EPS or n.length <= EPS:
        raise RegionError("degenerate region (zero area)")
    return c / total, (n / total).normalized()


def _make_basis(normal, loops3d):
    """Orthonormal right-handed (u, v, n) with u along the first long edge."""
    u = None
    for loop in loops3d:
        for i, a in enumerate(loop):
            d = loop[(i + 1) % len(loop)].co - a.co
            d -= normal * d.dot(normal)
            if d.length > 1e-6:
                u = d.normalized()
                break
        if u is not None:
            break
    if u is None:
        raise RegionError("degenerate region (no usable edge)")
    v = normal.cross(u).normalized()   # u x v == normal
    return u, v, normal


def _build_region(faces):
    region = Region(faces)
    loops3d, borders = _boundary_loops(faces)
    origin, normal = _fit_plane(faces)
    u, v, n = _make_basis(normal, loops3d)

    def project(co, u, v):
        d = co - origin
        return (d.dot(u), d.dot(v))

    # Winding check: the outer loop (largest |signed area|) must be CCW when
    # viewed down +n. Flipping v flips every signed area and the handedness,
    # so the basis normal flips with it and holes stay CW.
    areas = [_signed_area([project(vt.co, u, v) for vt in loop])
             for loop in loops3d]
    outer = max(range(len(areas)), key=lambda i: abs(areas[i]))
    if areas[outer] < 0.0:
        v = -v
        n = -n

    region.plane_origin = origin
    region.basis = (u, v, n)

    # Pre-filter the 3D loops exactly the way core.sanitize_loops filters the
    # 2D ones, so core edge id j maps 1:1 onto (loop3d[j], loop3d[j+1]).
    for loop, flags in zip(loops3d, borders):
        pts2d, verts, ws = [], [], []
        for vt, is_border in zip(loop, flags):
            p = project(vt.co, u, v)
            w = 1.0 if not is_border else None   # resolved by caller flag
            if pts2d and _dist2d(p, pts2d[-1]) < MIN_EDGE_2D:
                # This vert is merged into the previous kept one; the edge
                # that physically survives is *this* vert's outgoing edge,
                # so carry its weight forward (mirrors sanitize_loops).
                if ws:
                    ws[-1] = w
                continue
            pts2d.append(p)
            verts.append(vt)
            ws.append(w)
        if len(pts2d) > 1 and _dist2d(pts2d[0], pts2d[-1]) < MIN_EDGE_2D:
            pts2d.pop()
            verts.pop()
            ws.pop()
        if len(pts2d) < 3:
            raise RegionError("degenerate boundary loop")
        region.loops2d.append(pts2d)
        region.loops3d.append(verts)
        region.weights.append(ws)
        for i, vt in enumerate(verts):
            region.edge_orig_verts.append((vt, verts[(i + 1) % len(verts)]))

    region.bvh = _build_bvh(faces)
    return region


def _signed_area(pts):
    s = 0.0
    for i, p in enumerate(pts):
        q = pts[(i + 1) % len(pts)]
        s += p[0] * q[1] - q[0] * p[1]
    return 0.5 * s


def _dist2d(a, b):
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5


def _build_bvh(faces):
    """Snapshot the region surface so it survives deleting the faces."""
    index = {}
    verts, polys = [], []
    for f in faces:
        poly = []
        for vt in f.verts:
            i = index.get(vt)
            if i is None:
                i = len(verts)
                index[vt] = i
                verts.append(vt.co.copy())
            poly.append(i)
        if len(poly) >= 3:
            polys.append(tuple(poly))
    if not polys:
        raise RegionError("degenerate region (no faces)")
    return BVHTree.FromPolygons(verts, polys, all_triangles=False, epsilon=0.0)


def resolve_weights(region, use_boundary):
    """Turn the ``None`` placeholders into concrete edge weights.

    ``None`` marks an open mesh border edge: frozen (0.0) when
    ``use_boundary`` is False, normal (1.0) otherwise.
    """
    border_w = 1.0 if use_boundary else 0.0
    return [[border_w if w is None else w for w in ws] for ws in region.weights]


# --------------------------------------------------------------------------
# 2D <-> 3D
# --------------------------------------------------------------------------


def region_to_2d(region):
    return region.loops2d


def lift_to_3d(region, p2d):
    u, v, _ = region.basis
    return region.plane_origin + u * p2d[0] + v * p2d[1]


def surface_snap(region, co3d):
    """Pull a lifted point back onto the original region surface."""
    if region.bvh is None:
        return co3d
    hit = region.bvh.find_nearest(co3d)
    if hit is None or hit[0] is None:
        return co3d
    return hit[0].copy()


# --------------------------------------------------------------------------
# Geometry construction
# --------------------------------------------------------------------------


def _is_sliver(verts):
    """True for a polygon with no meaningful area (collinear points).

    A frozen boundary edge (weight 0, ``use_boundary=False``) does not move,
    yet the interior wavefront can still drop a skeleton node onto its line.
    The resulting "wall" is then three collinear points. The test is scale
    free: area normalised by squared perimeter, which is ~0.048 for an
    equilateral triangle and 0 for a degenerate one.
    """
    n = Vector((0.0, 0.0, 0.0))
    perim = 0.0
    o = verts[0].co
    for i, vt in enumerate(verts):
        nxt = verts[(i + 1) % len(verts)]
        n += (vt.co - o).cross(nxt.co - o)
        perim += (nxt.co - vt.co).length
    if perim <= EPS:
        return True
    return 0.5 * n.length <= 1e-7 * perim * perim


def effective_t(tl, t, use_collapse):
    """Clamp the requested thickness to what this timeline can deliver.

    Shared by ``apply_inset`` and the modal preview so the wireframe the user
    drags always matches the geometry confirm produces.
    """
    if use_collapse:
        return min(t, tl.max_t)
    # Stop just shy of the first event: exactly at first_event_t the
    # colliding front verts are already dead, so front_at() would come
    # back empty and the region would collapse -- the opposite of what
    # "no collapse" promises.
    return min(t, tl.first_event_t * (1.0 - 1e-6))


def apply_inset(bm, region, tl, t, depth, use_collapse):
    """Rebuild the region at thickness ``t``. Mutates ``bm``.

    Returns ``(faces_created, mutated)``. ``mutated`` is False only when the
    effective thickness degenerated to zero and ``bm`` was left untouched.
    """
    t_eff = effective_t(tl, t, use_collapse)
    if t_eff <= EPS:
        return 0, False

    def key_of(p2d):
        return (round(p2d[0], WELD_DIGITS), round(p2d[1], WELD_DIGITS))

    # Seed the weld table with the original boundary verts. A front vert that
    # never moves (both incident edges frozen by use_boundary=False) sits
    # exactly on its original position, and must reuse the real BMVert rather
    # than spawn a coincident duplicate -- otherwise the wall face there is
    # zero-area and the inner ngon detaches from the border.
    made = {}
    for loop2d, loop3d in zip(region.loops2d, region.loops3d):
        for p2d, vt in zip(loop2d, loop3d):
            made.setdefault(key_of(p2d), vt)

    fresh = []   # only the verts this call created -- `depth` moves these

    def bmvert(p2d):
        key = key_of(p2d)
        vt = made.get(key)
        if vt is None:
            vt = bm.verts.new(surface_snap(region, lift_to_3d(region, p2d)))
            made[key] = vt
            fresh.append(vt)
        return vt

    def new_face(poly):
        poly = [vt for i, vt in enumerate(poly) if vt not in poly[:i]]
        if len(poly) < 3 or _is_sliver(poly):
            return 0
        try:
            bm.faces.new(poly)
        except ValueError:
            return 0
        return 1

    made_faces = 0
    walls = tl.walls_at(t_eff)
    for j in range(tl.edge_count):
        a3, b3 = region.edge_orig_verts[j]
        chain = [bmvert(p) for p in walls.get(j, ())]
        made_faces += new_face([a3, b3] + chain)

    for loop in tl.front_at(t_eff):
        made_faces += new_face([bmvert(tl.pos_at(vid, t_eff)) for vid in loop])

    if abs(depth) > 1e-9:
        n = region.basis[2]
        for vt in fresh:
            vt.co += n * depth

    bmesh.ops.delete(bm, geom=region.faces, context='FACES')
    # A vert created for a wall that turned out degenerate would be left
    # dangling; drop the ones nothing ended up using.
    orphans = [vt for vt in fresh if vt.is_valid and not vt.link_faces]
    if orphans:
        bmesh.ops.delete(bm, geom=orphans, context='VERTS')
    bm.normal_update()
    return made_faces, True


# --------------------------------------------------------------------------
# Operator
# --------------------------------------------------------------------------


class IOPS_OT_smart_inset(bpy.types.Operator):
    """Inset selected faces with a straight-skeleton wavefront"""

    bl_idname = "iops.mesh_smart_inset"
    bl_label = "Smart Inset"
    bl_description = (
        "Inset the selected faces by moving every boundary edge inward at "
        "the same speed. Unlike mesh.inset the result stays self-consistent "
        "past the point where the region starts to collapse: the wavefront "
        "topology changes and the medial skeleton is produced"
    )
    bl_options = {"REGISTER", "UNDO"}

    thickness: FloatProperty(
        name="Thickness",
        description="Inward offset distance of the region boundary",
        default=0.05,
        soft_min=0.0,
        soft_max=10.0,
        step=1,
        precision=4,
        subtype="DISTANCE",
    )
    depth: FloatProperty(
        name="Depth",
        description="Offset of the new inner geometry along the region normal",
        default=0.0,
        soft_min=-10.0,
        soft_max=10.0,
        step=1,
        precision=4,
        subtype="DISTANCE",
    )
    mode: EnumProperty(
        name="Mode",
        description="How selected faces are grouped into inset regions",
        items=[
            ("REGION", "Region", "One inset per connected group of faces"),
            ("INDIVIDUAL", "Individual", "One inset per selected face"),
        ],
        default="REGION",
    )
    use_collapse: BoolProperty(
        name="Allow Collapse",
        description=(
            "Allow the thickness to run past the first wavefront event, "
            "collapsing the region down to its medial skeleton. When off, "
            "the thickness is clamped to the first event so the inset stays "
            "topologically identical to the original boundary"
        ),
        default=True,
    )
    use_boundary: BoolProperty(
        name="Boundary",
        description=(
            "Inset from open mesh borders too. When off, border edges stay "
            "in place and only interior boundary edges move"
        ),
        default=True,
    )

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.type == "MESH" and obj.mode == "EDIT"

    # ------------------------------------------------------------------
    # Modal lifecycle
    # ------------------------------------------------------------------

    def invoke(self, context, event):
        # Purge first, before any early bail: a handler leaked by a crashed
        # session must go even when this invoke turns out to have nothing to do.
        _purge_handles()

        obj = context.active_object
        me = obj.data
        bm = bmesh.from_edit_mesh(me)
        bm.faces.ensure_lookup_table()
        bm.normal_update()

        # Regions and timelines are built exactly once. Nothing between here
        # and confirm may call update_edit_mesh -- the cached Region objects
        # hold live BMVert references that a mesh update would invalidate.
        regions, warnings = collect_regions(bm, self.mode)
        for msg in warnings:
            self.report({'WARNING'}, "Smart Inset: region skipped (%s)" % msg)
        self._regions = self._build_timelines(regions)
        if not self._regions:
            if not warnings:
                self.report({'WARNING'},
                            "Smart Inset: no usable face selection")
            return {'CANCELLED'}

        self._obj = obj
        self._bm = bm

        # Sensitivity baseline: a quarter of the average boundary-edge length
        # per 100 px of horizontal mouse travel.
        total, count = 0.0, 0
        for region, _tl in self._regions:
            for loop in region.loops3d:
                for i, vt in enumerate(loop):
                    total += (loop[(i + 1) % len(loop)].co - vt.co).length
                    count += 1
        avg_L = total / count if count else 1.0
        self._pixel_to_t = max(avg_L * 0.25 / 100.0, 1e-6)

        self._mouse_start_x = event.mouse_region_x
        self._initial_thickness = self.thickness
        # Shift-precision works off a second anchor captured at Shift-press,
        # so entering/leaving precise mode never jumps the value.
        self._shift_anchor_x = None
        self._shift_anchor_t = 0.0
        # Ctrl held: mouse X drives depth instead of thickness. Same
        # re-anchor trick as Shift so toggling Ctrl never jumps either value.
        self._ctrl_anchor_x = None
        self._ctrl_anchor_depth = 0.0
        # Depth's own Shift-precision anchor, independent of the thickness
        # one above -- mirrors _shift_anchor_x/_t so toggling Shift while
        # Ctrl is held re-anchors instead of re-multiplying the whole
        # accumulated delta by the new sensitivity.
        self._depth_shift_anchor_x = None
        self._depth_shift_anchor_v = 0.0
        # Numeric entry: digits/./-/Backspace build this; non-empty overrides
        # mouse-driven thickness (see _sync_typed_thickness).
        self._input_str = ""

        # Preview is cached in 3D and only re-projected per redraw -- see
        # _rebuild_preview.
        self._preview_segs = []
        self._preview_key = None
        self._rebuild_preview()

        self._hud = HUDOverlay("smart_inset")
        self._hud.title = "Smart Inset"
        self._hud.bind_region(context.region)
        self._hud.add_param(HUDParam(
            "Thickness", self._hud_thickness, "float", fmt="{:.4f}"))
        self._hud.add_param(HUDParam(
            "Depth", lambda: self.depth, "float", fmt="{:.4f}"))
        self._hud.add_param(HUDParam("Mode (I)", lambda: self.mode, "enum"))
        self._hud.add_param(HUDParam(
            "Collapse (C)", lambda: self.use_collapse, "bool"))
        self._hud.add_param(HUDParam(
            "Boundary (B)", lambda: self.use_boundary, "bool"))

        self._help = HelpOverlay("smart_inset")
        self._help.add_section(HUDSection("Smart Inset", [
            HUDItem("Adjust thickness", "Mouse / Type", ItemState.ON, default_state=ItemState.OFF, always_show=True),
            HUDItem("Depth",            "Ctrl + Mouse", ItemState.ON, default_state=ItemState.OFF, always_show=True),
            HUDItem("Mode",             "I",            ItemState.ON, default_state=ItemState.OFF, always_show=True),
            HUDItem("Collapse",         "C",            ItemState.ON, default_state=ItemState.OFF, always_show=True),
            HUDItem("Boundary",         "B",            ItemState.ON, default_state=ItemState.OFF, always_show=True),
            HUDItem("Confirm",          "LMB / Enter",  ItemState.ON, default_state=ItemState.OFF, always_show=True),
            HUDItem("Cancel",           "Esc / RMB",    ItemState.ON, default_state=ItemState.OFF, always_show=True),
            HUDItem("Help / Toggle HUD", "H",           ItemState.ON, default_state=ItemState.OFF, always_show=True),
        ]))
        self._help.bind_region(context.region)
        self._last_event = capture_event(event, getattr(self, "_last_event", None))

        self._handle = safe_handler_add(
            bpy.types.SpaceView3D, self._draw_callback, (context,),
            "WINDOW", "POST_PIXEL", tick=True)
        _ACTIVE_HANDLES.add(self._handle)

        context.workspace.status_text_set(self._status_text())
        context.window_manager.modal_handler_add(self)
        if context.area:
            context.area.tag_redraw()
        return {'RUNNING_MODAL'}

    def _build_timelines(self, regions):
        """Pair every usable region with its wavefront timeline.

        Kept separate from ``invoke`` so a later boundary-mode toggle can
        rebuild the timelines (the edge weights depend on ``use_boundary``)
        without re-collecting the regions.
        """
        out = []
        for region in regions:
            try:
                tl = core.build_timeline(
                    region_to_2d(region),
                    resolve_weights(region, self.use_boundary))
            except ValueError as ex:
                self.report({'WARNING'},
                            "Smart Inset: region skipped (%s)" % ex)
                continue
            if tl.truncated:
                self.report({'WARNING'},
                            "Smart Inset: wavefront truncated, result may be "
                            "incomplete")
            out.append((region, tl))
        return out

    def modal(self, context, event):
        try:
            return self._modal(context, event)
        except ReferenceError:
            # bmesh element invalidated mid-modal (undo, addon reload, or some
            # other op that freed the underlying data). Tear the draw handler
            # down so the viewport is not left with a dangling callback.
            self._finish(context)
            self.report({'WARNING'},
                        "Smart Inset: bmesh data became invalid — cancelled")
            return {'CANCELLED'}
        except Exception:
            self._finish(context)
            raise

    def _modal(self, context, event):
        if context.area:
            context.area.tag_redraw()
        self._last_event = capture_event(event, getattr(self, "_last_event", None))

        try:
            theme_prefs = context.preferences.addons["InteractionOps"].preferences.iops_theme
        except (KeyError, AttributeError):
            theme_prefs = None
        if theme_prefs is not None:
            helpo = getattr(self, "_help", None)
            hud = getattr(self, "_hud", None)
            if helpo is not None and helpo.handle_drag_event(context, event, theme_prefs):
                return {'RUNNING_MODAL'}
            if hud is not None and hud.handle_drag_event(context, event, theme_prefs):
                return {'RUNNING_MODAL'}
            # H (iops.ui_help_toggle) lives here.
            if helpo is not None and helpo.handle_toggle_event(event, theme_prefs):
                return {'RUNNING_MODAL'}
            if hud is not None and hud.handle_param_toggle_event(event, theme_prefs):
                return {'RUNNING_MODAL'}

        if (event.type in {"MIDDLEMOUSE", "WHEELUPMOUSE", "WHEELDOWNMOUSE"}
                or event.type.startswith("NDOF")):
            return {'PASS_THROUGH'}

        if event.type == "MOUSEMOVE":
            if event.ctrl:
                self._update_depth(event)
            else:
                if self._ctrl_anchor_x is not None:
                    # Leaving depth mode: re-anchor the thickness baseline on
                    # the current mouse position/value, mirroring the Shift
                    # re-anchor above, so releasing Ctrl never snaps. Also
                    # drop depth's own Shift anchor so a later Ctrl-press
                    # doesn't resume it from a stale position.
                    self._ctrl_anchor_x = None
                    self._depth_shift_anchor_x = None
                    self._mouse_start_x = event.mouse_region_x
                    self._initial_thickness = self.thickness
                if not self._input_str:
                    self._update_thickness(event)
            self._rebuild_preview()
            context.workspace.status_text_set(self._status_text())
            return {'RUNNING_MODAL'}

        if event.value == "PRESS":
            if event.type in DIGIT_TYPES:
                self._input_str += DIGIT_TYPES[event.type]
                self._sync_typed_thickness()
                self._rebuild_preview()
                context.workspace.status_text_set(self._status_text())
                return {'RUNNING_MODAL'}

            if event.type in {"PERIOD", "NUMPAD_PERIOD"}:
                if "." not in self._input_str:
                    self._input_str += "."
                context.workspace.status_text_set(self._status_text())
                return {'RUNNING_MODAL'}

            if event.type in {"MINUS", "NUMPAD_MINUS"}:
                had_input = bool(self._input_str)
                if self._input_str.startswith("-"):
                    self._input_str = self._input_str[1:]
                else:
                    self._input_str = "-" + self._input_str
                self._sync_typed_thickness()
                if had_input and not self._input_str:
                    self._reanchor_thickness_mouse(event)
                self._rebuild_preview()
                context.workspace.status_text_set(self._status_text())
                return {'RUNNING_MODAL'}

            if event.type == "BACK_SPACE":
                had_input = bool(self._input_str)
                self._input_str = self._input_str[:-1]
                self._sync_typed_thickness()
                if had_input and not self._input_str:
                    self._reanchor_thickness_mouse(event)
                self._rebuild_preview()
                context.workspace.status_text_set(self._status_text())
                return {'RUNNING_MODAL'}

            if event.type == "I":
                self._toggle_mode()
                self._rebuild_preview()
                context.workspace.status_text_set(self._status_text())
                return {'RUNNING_MODAL'}

            if event.type == "C":
                self.use_collapse = not self.use_collapse
                self._rebuild_preview()
                context.workspace.status_text_set(self._status_text())
                return {'RUNNING_MODAL'}

            if event.type == "B":
                self._toggle_boundary()
                self._rebuild_preview()
                context.workspace.status_text_set(self._status_text())
                return {'RUNNING_MODAL'}

            if event.type in {"LEFTMOUSE", "RET", "NUMPAD_ENTER"}:
                self._finish(context)
                return self._run(context)

            if event.type in {"RIGHTMOUSE", "ESC"}:
                self.thickness = self._initial_thickness
                self._finish(context)
                return {'CANCELLED'}

        return {'RUNNING_MODAL'}

    def _update_thickness(self, event):
        """Map horizontal mouse travel onto ``thickness``.

        Shift scales the delta accumulated *since Shift was pressed* by 0.1,
        so toggling precise mode never snaps the value.
        """
        if event.shift:
            if self._shift_anchor_x is None:
                self._shift_anchor_x = event.mouse_region_x
                self._shift_anchor_t = self.thickness
            delta = event.mouse_region_x - self._shift_anchor_x
            self.thickness = self._shift_anchor_t + delta * self._pixel_to_t * 0.1
            return
        if self._shift_anchor_x is not None:
            # Leaving precise mode: re-anchor the coarse baseline on the
            # current value instead of snapping back to the invoke-time one.
            self._shift_anchor_x = None
            self._mouse_start_x = event.mouse_region_x
            self._initial_thickness = self.thickness
            return
        delta = event.mouse_region_x - self._mouse_start_x
        self.thickness = self._initial_thickness + delta * self._pixel_to_t

    def _update_depth(self, event):
        """Map horizontal mouse travel onto ``depth`` while Ctrl is held.

        Anchored on the mouse position/depth at the moment Ctrl went down,
        exactly like ``_update_thickness`` is anchored on Shift-press: a
        second anchor (``_depth_shift_anchor_*``) is captured the instant
        Shift's state changes during the Ctrl-hold, so toggling Shift
        re-anchors the delta instead of re-multiplying the whole
        accumulated-since-Ctrl-press delta by the new sensitivity (which
        would jump depth ~10x on that frame).
        """
        if event.shift:
            if self._depth_shift_anchor_x is None:
                self._depth_shift_anchor_x = event.mouse_region_x
                self._depth_shift_anchor_v = self.depth
            delta = event.mouse_region_x - self._depth_shift_anchor_x
            self.depth = self._depth_shift_anchor_v + delta * self._pixel_to_t * 0.1
            return
        if self._depth_shift_anchor_x is not None:
            # Leaving precise mode: re-anchor the coarse (Ctrl) baseline on
            # the current value instead of snapping back to the
            # Ctrl-press-time one.
            self._depth_shift_anchor_x = None
            self._ctrl_anchor_x = event.mouse_region_x
            self._ctrl_anchor_depth = self.depth
            return
        if self._ctrl_anchor_x is None:
            self._ctrl_anchor_x = event.mouse_region_x
            self._ctrl_anchor_depth = self.depth
        delta = event.mouse_region_x - self._ctrl_anchor_x
        self.depth = self._ctrl_anchor_depth + delta * self._pixel_to_t

    def _sync_typed_thickness(self):
        """Push a valid numeric ``_input_str`` into ``self.thickness``.

        Silently ignored while the string is not yet a parseable float (e.g.
        just "-" or "."), so partial input never raises mid-typing.
        """
        if self._input_str and self._input_str not in ("-", "."):
            try:
                self.thickness = float(self._input_str)
            except ValueError:
                pass

    def _reanchor_thickness_mouse(self, event):
        """Re-anchor mouse-driven thickness on the here-and-now.

        Called whenever ``_input_str`` empties back out (Backspace or Minus
        clearing the last character). While numeric entry had focus the
        mouse baseline (``_mouse_start_x``/``_initial_thickness``) sat
        frozen at whatever it was when typing started; handing control back
        to it unchanged would apply however far the mouse drifted in the
        meantime as an instant jump. Re-anchoring on the current mouse
        position/value makes the handoff a no-op instead.
        """
        self._mouse_start_x = event.mouse_region_x
        self._initial_thickness = self.thickness

    def _toggle_mode(self):
        """Flip REGION<->INDIVIDUAL, rebuilding regions + timelines in place.

        Uses the same collection/timeline code path as ``invoke``. If the
        new mode yields no usable regions (e.g. an INDIVIDUAL selection that
        was only valid as one connected REGION), the mode reverts and a
        warning is reported instead of leaving the operator with an empty
        region list.
        """
        new_mode = "INDIVIDUAL" if self.mode == "REGION" else "REGION"
        regions, warnings = collect_regions(self._bm, new_mode)
        built = self._build_timelines(regions)
        for msg in warnings:
            self.report({'WARNING'}, "Smart Inset: region skipped (%s)" % msg)
        if not built:
            self.report({'WARNING'},
                        "Smart Inset: mode change left no usable regions "
                        "— reverted")
            return
        self.mode = new_mode
        self._regions = built
        self._preview_key = None

    def _toggle_boundary(self):
        """Flip ``use_boundary``, rebuilding timelines (weights depend on it).

        Mirrors ``_toggle_mode``'s revert-on-failure guard: rebuilding with
        the flipped flag can legitimately empty out ``_regions`` (e.g. a
        single triangle whose only non-border edges can't sustain a
        timeline once its border edges freeze), and committing that would
        permanently blank the preview for the rest of the session with no
        way back via B. So the flag only commits once the rebuild is
        confirmed non-empty; otherwise it reverts and reports a warning.
        """
        prev_use_boundary = self.use_boundary
        self.use_boundary = not prev_use_boundary
        regions = [region for region, _tl in self._regions]
        built = self._build_timelines(regions)
        if not built:
            self.use_boundary = prev_use_boundary
            self.report({'WARNING'},
                        "Smart Inset: boundary toggle left no usable "
                        "regions — reverted")
            return
        self._regions = built
        self._preview_key = None

    def _finish(self, context):
        h = getattr(self, "_handle", None)
        if h is not None:
            _ACTIVE_HANDLES.discard(h)
            try:
                safe_handler_remove(h, bpy.types.SpaceView3D, "WINDOW")
            except (ValueError, RuntimeError):
                pass
            self._handle = None
        context.workspace.status_text_set(None)
        if context.area:
            context.area.tag_redraw()
        # Blender keeps finished operator instances alive in the redo stack.
        # Dropping every bmesh-derived reference here stops a later addon
        # reload from dealloc'ing them against freed mesh data.
        self._regions = []
        self._preview_segs = []
        self._preview_key = None
        self._bm = None
        self._obj = None
        self._hud = None
        self._help = None

    def _status_text(self):
        typed = f" | typing: {self._input_str}" if self._input_str else ""
        return (
            f"Smart Inset: thickness = {self.thickness:.4f}{typed} | "
            f"depth = {self.depth:.4f} | "
            f"mode = {self.mode} (I) | "
            f"collapse = {'on' if self.use_collapse else 'off'} (C) | "
            f"boundary = {'on' if self.use_boundary else 'off'} (B) | "
            "[Mouse] drag | [Ctrl+Mouse] depth | [Shift] precise | "
            "[Enter/LMB] confirm | [Esc/RMB] cancel"
        )

    def _hud_thickness(self):
        """Thickness value shown in the HUD.

        With ``use_collapse`` off, ``apply_inset``/the preview clamp each
        region to its own ``first_event_t`` — the requested thickness can
        keep climbing past that with no visible effect. Showing the
        requested value there would silently lie about what the preview
        displays, so the HUD instead shows the effective (capped) value:
        the smallest per-region cap, or the requested thickness itself when
        that is lower (or when collapse is allowed, in which case there is
        no cap to speak of).
        """
        t = float(self.thickness)
        if self.use_collapse or t <= EPS:
            return t
        caps = [tl.first_event_t * (1.0 - 1e-6)
                for _region, tl in getattr(self, "_regions", ())]
        return min([t] + caps) if caps else t

    # ------------------------------------------------------------------
    # Preview
    # ------------------------------------------------------------------

    def _rebuild_preview(self):
        """Refresh the cached 3D preview segments if a parameter moved.

        Walking the wavefront (``front_at`` + ``pos_at``) and snapping every
        front vert onto the surface through the region BVH is far too heavy for
        a draw callback: the HUD keeps a ~``hud_anim_fps`` tick timer alive, so
        the handler fires continuously even with the mouse idle. The timer is
        still wanted -- it drives the HUD cursor-follow and the Help overlay
        animations -- so the fix is to cache instead of dropping the tick.
        Recomputation is keyed on every input the segments depend on.
        """
        key = (self.thickness, self.depth, self.mode,
               self.use_collapse, self.use_boundary)
        if key == self._preview_key:
            return
        self._preview_key = key
        self._preview_segs = self._front_segments()

    def _front_segments(self):
        """Flat list of world-space segment endpoints for every front loop.

        Mirrors what ``apply_inset`` would build at the current thickness:
        the 2D front positions lifted back onto the original surface and
        pushed along the region normal by ``depth``.
        """
        segs = []
        t = float(self.thickness)
        if t <= EPS:
            return segs   # negative/zero is a no-op until outset lands
        for region, tl in getattr(self, "_regions", ()):
            t_eff = effective_t(tl, t, self.use_collapse)
            if t_eff <= EPS:
                continue
            n = region.basis[2]
            offset = n * self.depth if abs(self.depth) > 1e-9 else None
            for loop in tl.front_at(t_eff):
                pts = []
                for vid in loop:
                    co = surface_snap(
                        region, lift_to_3d(region, tl.pos_at(vid, t_eff)))
                    if offset is not None:
                        co = co + offset
                    pts.append(co)
                if len(pts) < 2:
                    continue
                for i, p in enumerate(pts):
                    segs.append(p)
                    segs.append(pts[(i + 1) % len(pts)])
        return segs

    def _draw_callback(self, context):
        region_ui = context.region
        rv3d = context.region_data
        if rv3d is None:
            return

        # Guard against an in-place addon reload freeing this operator's RNA
        # struct while the draw handler is still registered.
        try:
            mw = self._obj.matrix_world
        except (ReferenceError, AttributeError):
            h = getattr(self, "_handle", None)
            if h is not None:
                _ACTIVE_HANDLES.discard(h)
                try:
                    safe_handler_remove(h, bpy.types.SpaceView3D, "WINDOW")
                except (ValueError, RuntimeError, ReferenceError):
                    pass
            return

        # Cached 3D segments -- this path only projects them. Any exception
        # escaping a draw handler repeats every single frame and can wedge the
        # UI, so the whole projection falls back to drawing nothing.
        pts_2d = []
        try:
            segs = getattr(self, "_preview_segs", None) or ()
            for i in range(0, len(segs) - 1, 2):
                pa = view3d_utils.location_3d_to_region_2d(
                    region_ui, rv3d, mw @ segs[i])
                pb = view3d_utils.location_3d_to_region_2d(
                    region_ui, rv3d, mw @ segs[i + 1])
                if pa is None or pb is None:
                    continue
                pts_2d.append(Vector((pa[0], pa[1], 0.0)))
                pts_2d.append(Vector((pb[0], pb[1], 0.0)))
        except Exception:
            pts_2d = []

        if pts_2d:
            with draw_scope(blend="ALPHA"):
                draw.edges_3d(pts_2d, role=Role.PREVIEW_LINE, context=context)

        hud = getattr(self, "_hud", None)
        helpo = getattr(self, "_help", None)
        last_event = getattr(self, "_last_event", None)
        if helpo is not None:
            helpo.draw(context, last_event)
        if hud is not None:
            hud.set_header(f"Thickness: {self.thickness:.4f}")
            hud.draw(context, last_event)

    # ------------------------------------------------------------------
    # Execute (topology change)
    # ------------------------------------------------------------------

    def execute(self, context):
        """Redo-panel / scripting entry point. The modal confirm goes through
        the same ``_run`` body after tearing its overlays down."""
        return self._run(context)

    def _run(self, context):
        obj = context.active_object
        me = obj.data
        bm = bmesh.from_edit_mesh(me)

        # Negative thickness is a no-op in this task (outset lands later).
        t = max(0.0, float(self.thickness))

        regions, warnings = collect_regions(bm, self.mode)
        for msg in warnings:
            self.report({'WARNING'}, "Smart Inset: region skipped (%s)" % msg)
        if not regions:
            if not warnings:
                self.report({'WARNING'}, "Smart Inset: no faces selected")
            return {'CANCELLED'}
        if t <= EPS:
            # Silence here reads as "the operator did nothing and won't say
            # why". The property is deliberately left unclamped -- negative
            # thickness becomes outset later.
            self.report({'WARNING'},
                        "Smart Inset: zero thickness — nothing to apply")
            return {'CANCELLED'}

        changed = 0
        mutated = False
        for region, tl in self._build_timelines(regions):
            n_faces, did = apply_inset(bm, region, tl, t, self.depth,
                                       self.use_collapse)
            changed += n_faces
            mutated = mutated or did

        if not mutated:
            return {'CANCELLED'}

        # Any mutation must be reported as FINISHED so Blender pushes an undo
        # step -- returning CANCELLED after geometry was already deleted would
        # leave the change unundoable.
        if not changed:
            self.report({'WARNING'},
                        "Smart Inset: no faces produced for this thickness")
        bmesh.update_edit_mesh(me, loop_triangles=True, destructive=True)
        return {'FINISHED'}
