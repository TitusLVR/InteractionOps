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
from bpy.props import FloatProperty, BoolProperty, EnumProperty

from ..utils import smart_inset_core as core


EPS = 1e-9
# Same threshold core.sanitize_loops uses to merge near-duplicate points.
MIN_EDGE_2D = 1e-6
# Rounding used to weld skeleton nodes shared by several walls.
WELD_DIGITS = 6


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
    sel = [f for f in bm.faces if f.select]
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
                        if lf.select and lf not in seen:
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


def apply_inset(bm, region, tl, t, depth, use_collapse):
    """Rebuild the region at thickness ``t``. Mutates ``bm``.

    Returns ``(faces_created, mutated)``. ``mutated`` is False only when the
    effective thickness degenerated to zero and ``bm`` was left untouched.
    """
    limit = tl.max_t if use_collapse else tl.first_event_t
    t_eff = min(t, limit)
    if t_eff <= EPS:
        return 0, False
    made = {}

    def bmvert(p2d):
        key = (round(p2d[0], WELD_DIGITS), round(p2d[1], WELD_DIGITS))
        vt = made.get(key)
        if vt is None:
            vt = bm.verts.new(surface_snap(region, lift_to_3d(region, p2d)))
            made[key] = vt
        return vt

    def new_face(poly):
        poly = [vt for i, vt in enumerate(poly) if vt not in poly[:i]]
        if len(poly) < 3:
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
        for vt in made.values():
            vt.co += n * depth

    bmesh.ops.delete(bm, geom=region.faces, context='FACES')
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

    def execute(self, context):
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
            return {'CANCELLED'}

        changed = 0
        mutated = False
        for region in regions:
            try:
                tl = core.build_timeline(region_to_2d(region),
                                         resolve_weights(region,
                                                         self.use_boundary))
            except ValueError as ex:
                self.report({'WARNING'},
                            "Smart Inset: region skipped (%s)" % ex)
                continue
            if tl.truncated:
                self.report({'WARNING'},
                            "Smart Inset: wavefront truncated, result may be "
                            "incomplete")
            n_faces, did = apply_inset(bm, region, tl, t, self.depth,
                                       self.use_collapse)
            changed += n_faces
            mutated = mutated or did

        if not mutated:
            return {'CANCELLED'}

        bmesh.update_edit_mesh(me, loop_triangles=True, destructive=True)
        return {'FINISHED'} if changed else {'CANCELLED'}
