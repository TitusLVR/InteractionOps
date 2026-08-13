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
   one wall face per original boundary edge, the region's interior kept
   wherever the wavefront has not reached it yet (faces the front cuts
   through are clipped against it), and an ngon fill only where the front
   consumed the interior outright.

Curved regions are handled approximately by design: new verts are pulled back
onto the original surface with a BVH nearest-point query.
"""
import bpy
import bmesh
from mathutils import Vector
from mathutils.bvhtree import BVHTree
from mathutils.geometry import tessellate_polygon
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
                 "loops2d", "edge_orig_verts", "edge_orig_faces", "bvh")

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
        # core edge id -> the region BMFace that owned that boundary edge.
        # Source of material_index / loop data for the wall built on it.
        self.edge_orig_faces = []
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

    Returns ``(loops3d, borders, owners)``, all three parallel per vertex:
    ``borders[li][i]`` flags an open mesh border, ``owners[li][i]`` is the
    region face that owns the *outgoing* boundary edge of ``loops3d[li][i]``.
    """
    fset = set(faces)
    nxt = {}
    border = {}
    owner = {}
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
            owner[a] = f

    loops3d, borders, owners = [], [], []
    while nxt:
        start = next(iter(nxt))
        loop = []
        flags = []
        srcs = []
        cur = start
        while True:
            if cur not in nxt:
                raise RegionError("open/non-manifold boundary")
            nx = nxt.pop(cur)
            loop.append(cur)
            flags.append(border[cur])
            srcs.append(owner[cur])
            cur = nx
            if cur is start:
                break
        if len(loop) < 3:
            raise RegionError("boundary loop shorter than 3 verts")
        loops3d.append(loop)
        borders.append(flags)
        owners.append(srcs)
    if not loops3d:
        raise RegionError("no boundary edges")
    return loops3d, borders, owners


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


def _check_planar_enough(faces, normal):
    """Reject regions whose projection onto their own plane folds over.

    The whole wavefront runs in 2D on the fitted plane, and it assumes the
    projected boundary loops are simple. A face whose normal has a
    non-positive dot with the region normal projects with reversed
    orientation — the outline is guaranteed to self-intersect, and the core
    then leaves immortal fronts behind and reports a bogus ``max_t``. In
    practice this fires once the selection's normals sweep past ~180°
    (wrap-around selections, flipped faces); gentler bends project
    injectively per-face and stay on the documented approximate-curved
    path. Degenerate faces have a zero normal and no say either way, so
    they are skipped rather than allowed to poison the whole region.
    Non-reversing overlaps (helical strips) are caught separately by the
    loop-simplicity check in ``_build_region``.
    """
    for f in faces:
        if f.normal.length_squared > 0.0 and f.normal.dot(normal) <= 0.0:
            raise RegionError("region folds relative to its plane")


def _segments_cross(p1, p2, p3, p4):
    """True when open segments (p1,p2) and (p3,p4) properly cross."""
    d1 = _signed_area([p3, p4, p1])
    d2 = _signed_area([p3, p4, p2])
    d3 = _signed_area([p1, p2, p3])
    d4 = _signed_area([p1, p2, p4])
    return ((d1 > 0.0) != (d2 > 0.0)) and ((d3 > 0.0) != (d4 > 0.0))


def _check_loops_simple(loops2d):
    """Reject projections whose boundary outline self-intersects.

    The fold check above only catches orientation reversal; a helical or
    spiralling selection projects every face right side up yet still lays
    the outline over itself. The core cannot survive that input, so test
    every pair of boundary segments (skipping same-loop neighbours, which
    legitimately share an endpoint) before feeding it to the skeleton.
    O(n²) over boundary segments — invoke-time only, n is small.
    """
    segs = []
    for li, loop in enumerate(loops2d):
        n = len(loop)
        for i in range(n):
            segs.append((li, i, n, loop[i], loop[(i + 1) % n]))
    for a in range(len(segs)):
        la, ia, na, a1, a2 = segs[a]
        for b in range(a + 1, len(segs)):
            lb, ib, nb, b1, b2 = segs[b]
            if la == lb and (ib == (ia + 1) % na or ia == (ib + 1) % nb):
                continue
            if _segments_cross(a1, a2, b1, b2):
                raise RegionError(
                    "boundary projects to a self-intersecting outline")


def _build_region(faces):
    region = Region(faces)
    loops3d, borders, owners = _boundary_loops(faces)
    origin, normal = _fit_plane(faces)
    # Checked against the *fitted* normal, before the winding flip below:
    # that is the axis the loops are projected along, and it is the one the
    # face normals are aligned with by construction for a sane region.
    _check_planar_enough(faces, normal)
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
    for loop, flags, srcs in zip(loops3d, borders, owners):
        pts2d, verts, ws, fs = [], [], [], []
        for vt, is_border, src in zip(loop, flags, srcs):
            p = project(vt.co, u, v)
            w = 1.0 if not is_border else None   # resolved by caller flag
            if pts2d and _dist2d(p, pts2d[-1]) < MIN_EDGE_2D:
                # This vert is merged into the previous kept one; the edge
                # that physically survives is *this* vert's outgoing edge,
                # so carry its weight (and its owner face) forward -- mirrors
                # sanitize_loops.
                if ws:
                    ws[-1] = w
                    fs[-1] = src
                continue
            pts2d.append(p)
            verts.append(vt)
            ws.append(w)
            fs.append(src)
        if len(pts2d) > 1 and _dist2d(pts2d[0], pts2d[-1]) < MIN_EDGE_2D:
            pts2d.pop()
            verts.pop()
            ws.pop()
            fs.pop()
        if len(pts2d) < 3:
            raise RegionError("degenerate boundary loop")
        region.loops2d.append(pts2d)
        region.loops3d.append(verts)
        region.weights.append(ws)
        for i, vt in enumerate(verts):
            region.edge_orig_verts.append((vt, verts[(i + 1) % len(verts)]))
            region.edge_orig_faces.append(fs[i])

    _check_loops_simple(region.loops2d)
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


def project_to_2d(region, co):
    """Object-space point -> (u, v) coordinates on the region plane."""
    u, v, _ = region.basis
    d = co - region.plane_origin
    return (d.dot(u), d.dot(v))


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


def clamp_cap(tl):
    """Largest thickness a no-collapse inset may use on this timeline.

    Stop just shy of the first event: exactly at ``first_event_t`` the
    colliding front verts are already dead, so ``front_at()`` would come back
    empty and the region would collapse -- the opposite of what "no collapse"
    promises. Shared by ``effective_t``, the HUD readout and the preview so
    all three agree on where the clamp sits.
    """
    return tl.first_event_t * (1.0 - 1e-6)


def effective_t(tl, t, use_collapse):
    """Clamp the requested thickness to what this timeline can deliver.

    Shared by ``apply_inset`` and the modal preview so the wireframe the user
    drags always matches the geometry confirm produces.
    """
    if use_collapse:
        return min(t, tl.max_t)
    return min(t, clamp_cap(tl))


def _copy_face_attrs(face, src):
    """Give a freshly built face the material and loop data of ``src``.

    Native ``mesh.inset`` preserves both; without this every wall, cap and
    clipped face comes out on material slot 0 with zeroed UVs. ``src`` is the
    original region face the new one derives from (the face that owned the
    boundary edge for a wall, the clipped face's own original for a clip, a
    representative region face for a cap ngon).

    ``vert=False``: the vertex-level customdata layers belong to verts that
    may be shared with untouched geometry outside the region, so only the
    per-loop (UV, colour, ...) layers are interpolated.
    """
    if src is None or not src.is_valid:
        return
    face.material_index = src.material_index
    face.smooth = src.smooth
    try:
        face.copy_from_face_interp(src, False)
    except (RuntimeError, ValueError, TypeError):
        pass


def _apply_selection(inner, walls):
    """Leave the new inner surface selected and the walls not.

    Mirrors native ``mesh.inset``, which hands back the inner faces selected
    so the operation can be chained. Walls are cleared *first*: they share the
    front verts/edges with the inner faces, so clearing them afterwards would
    strip the selection straight back off. An inner face never touches an
    original boundary vert (those are consumed by definition), so every wall
    keeps at least one unselected vert and no later select flush can resurrect
    it.
    """
    for f in walls:
        if f.is_valid:
            f.select_set(False)
    for f in inner:
        if f.is_valid:
            f.select_set(True)


def _point_in_poly(pts, p):
    """Even-odd ray cast; points exactly on an edge are unspecified."""
    inside = False
    n = len(pts)
    for i in range(n):
        a, b = pts[i], pts[(i + 1) % n]
        if (a[1] > p[1]) != (b[1] > p[1]):
            x = a[0] + (p[1] - a[1]) * (b[0] - a[0]) / (b[1] - a[1])
            if p[0] < x:
                inside = not inside
    return inside


def _nearest_on_loops(loops, p):
    """Closest point on a set of closed 2D polylines.

    Returns ``(loop_index, seg_index, u, point, distance)`` where ``u`` is
    the parameter along segment ``seg_index -> seg_index + 1``.
    """
    best = None
    for li, pts in enumerate(loops):
        n = len(pts)
        if n < 2:
            continue
        for i in range(n):
            a, b = pts[i], pts[(i + 1) % n]
            dx, dy = b[0] - a[0], b[1] - a[1]
            L2 = dx * dx + dy * dy
            if L2 < MIN_EDGE_2D * MIN_EDGE_2D:
                u = 0.0
            else:
                u = ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / L2
                u = min(1.0, max(0.0, u))
            q = (a[0] + dx * u, a[1] + dy * u)
            d = _dist2d(p, q)
            if best is None or d < best[4]:
                best = (li, i, u, q, d)
    return best


class _Crossing:
    """One point where the front crosses an original interior edge."""

    __slots__ = ("p2d", "loop", "seg", "u", "splice")

    def __init__(self, p2d, loop, seg, u, splice):
        self.p2d = p2d
        self.loop = loop      # front loop index it was snapped onto
        self.seg = seg        # segment index within that loop
        self.u = u            # parameter along the segment
        self.splice = splice  # False when it landed on a front vert itself


def _front_span(front, ca, cb):
    """Front verts passed walking forward from crossing ``ca`` to ``cb``.

    Both the original faces and the front loops wind CCW around the region
    normal, and both keep the surviving material on the left, so a cut
    polygon traverses the front in the *same* direction as the front loop's
    own order. The front verts in between must be part of the cut polygon:
    the wall faces meet the front at them, and short-cutting them with a
    straight chord would tear the surface at every front corner.
    """
    if ca.loop != cb.loop:
        raise RuntimeError("chord spans two front loops")
    pts = front[ca.loop]
    n = len(pts)
    if ca.seg == cb.seg:
        if cb.u >= ca.u:
            return []
        raise RuntimeError("face encloses a whole front loop")
    out = []
    i = (ca.seg + 1) % n
    for _ in range(n):
        out.append(pts[i])
        if i == cb.seg:
            return out
        i = (i + 1) % n
    raise RuntimeError("front span walk failed")


class _ClipPlan:
    """Everything ``apply_inset`` needs to preserve the region's interior.

    Built before any bmesh mutation and fully validated, so a region that
    cannot be clipped consistently falls back to the plain ngon fill with
    the mesh still untouched.
    """

    __slots__ = ("kept", "clipped", "consumed", "survivors", "crossings",
                 "chains")

    def __init__(self):
        self.kept = []        # faces left exactly as they are
        # (face, entries) where an entry is ('v', BMVert) for a surviving
        # vert, ('x', weld key) for a front crossing, ('f', p2d) for a front
        # vert the cut polygon has to pass through.
        self.clipped = []
        self.consumed = []    # faces to delete (fully eaten + clipped ones)
        self.survivors = []   # interior verts that keep their position
        self.crossings = {}   # weld key -> _Crossing
        self.chains = {}      # edge id -> wall chain with crossings spliced in


def _clip_eligible(tl):
    """Interior clipping needs the plain unit-speed metric.

    ``boundary_distance`` measures the unweighted distance to the boundary,
    which only equals the wavefront arrival time when every edge moves at
    speed 1. With a frozen border (``use_boundary`` off, weight 0) the two
    disagree, so clipping is skipped and Task 6's ngon fill is used.
    """
    return all(abs(w - 1.0) <= 1e-12 for w in tl.edge_weight.values())


def _plan_interior_clip(region, tl, t_eff, chains, key_of):
    """Decide which region faces survive the front and how they are cut.

    Returns a validated ``_ClipPlan``, or None when nothing survives (the
    whole region was consumed -- Task 6's fill is exactly right then).
    Raises RuntimeError when the clip cannot be made watertight; the caller
    is expected to fall back.
    """
    loops2d = region.loops2d
    boundary = set()
    for loop in region.loops3d:
        boundary.update(loop)

    # Survival band. A vertex whose distance to the boundary is only a hair
    # above t_eff would spawn crossing points a hair away from *itself*:
    # coincident verts for any practical merge threshold. Treating the whole
    # band as consumed avoids that -- the crossings then land near a vertex
    # that is being deleted anyway. The band is relative to the region size
    # so it stays negligible at any scale.
    lo = [min(p[i] for loop in loops2d for p in loop) for i in (0, 1)]
    hi = [max(p[i] for loop in loops2d for p in loop) for i in (0, 1)]
    diag = _dist2d(lo, hi)
    tol = max(MIN_EDGE_2D, 1e-4 * diag)
    # One single iso-level for both the survival test and the crossing
    # bisection: mixing t_eff with a shifted test would leave edges whose
    # endpoints "disagree" about which side of the level they are on.
    level = t_eff + tol
    # Bucketed equivalent of ``core.boundary_distance(...) > level``; a dense
    # selection asks this thousands of times.
    lvl = core.BoundaryLevel(loops2d, level)
    survive = {}
    for f in region.faces:
        for vt in f.verts:
            if vt in survive:
                continue
            if vt in boundary:
                survive[vt] = False
                continue
            survive[vt] = lvl.beyond(project_to_2d(region, vt.co))

    plan = _ClipPlan()
    plan.survivors = [vt for vt, ok in survive.items() if ok]
    if not plan.survivors:
        return None

    front_vids = tl.front_at(t_eff)
    if not front_vids:
        raise RuntimeError("interior survives but the front is empty")
    front = [[tl.pos_at(vid, t_eff) for vid in loop] for loop in front_vids]

    cache = {}
    chords = []

    def crossing(a, b):
        """Weld key of the front crossing on edge a-b (memoised, symmetric)."""
        ck = (id(a), id(b)) if id(a) < id(b) else (id(b), id(a))
        hit = cache.get(ck)
        if hit is not None:
            return hit
        # Canonical direction so both incident faces get bit-identical
        # results out of the bisection.
        if id(a) > id(b):
            a, b = b, a
        pa = project_to_2d(region, a.co)
        pb = project_to_2d(region, b.co)
        ga = lvl.beyond(pa)
        if ga == lvl.beyond(pb):
            raise RuntimeError("edge does not straddle the front")
        # Bisect the piecewise-linear min-distance along the edge. 20 halvings
        # pin the level crossing down to ~1e-6 of the edge length.
        lo, hi = 0.0, 1.0
        for _ in range(20):
            mid = 0.5 * (lo + hi)
            pm = (pa[0] + (pb[0] - pa[0]) * mid, pa[1] + (pb[1] - pa[1]) * mid)
            if lvl.beyond(pm) == ga:
                lo = mid
            else:
                hi = mid
        s = 0.5 * (lo + hi)
        p = (pa[0] + (pb[0] - pa[0]) * s, pa[1] + (pb[1] - pa[1]) * s)

        # The distance iso-level and the straight-skeleton front agree
        # everywhere except around reflex corners, where the true offset is
        # a circular arc and the skeleton miters it. Snapping the crossing
        # onto the front polyline is what keeps the clipped faces, the walls
        # and the front welded into one watertight surface.
        near = _nearest_on_loops(front, p)
        if near is None:
            raise RuntimeError("no front polyline to snap to")
        li, si, u, q, dist = near
        # tol shows up here because the bisected level sits tol inside the
        # front by construction.
        if dist > tol + max(1e-4, 0.5 * t_eff):
            raise RuntimeError("front crossing too far off the front")
        pts = front[li]
        a2, b2 = pts[si], pts[(si + 1) % len(pts)]
        seg_len = _dist2d(a2, b2)
        splice = True
        # Land it exactly on a front vert when it is within welding distance:
        # splitting a wall's top edge that close to its end would leave a
        # duplicate vert instead of a usable one.
        if u * seg_len <= tol:
            q, splice = a2, False
        elif (1.0 - u) * seg_len <= tol:
            q, splice = b2, False
            si = (si + 1) % len(pts)
            u = 0.0
        key = key_of(q)
        plan.crossings[key] = _Crossing(q, li, si, u, splice)
        cache[ck] = key
        return key

    for f in region.faces:
        vs = list(f.verts)
        flags = [survive[vt] for vt in vs]
        if all(flags):
            plan.kept.append(f)
            continue
        if not any(flags):
            plan.consumed.append(f)
            continue
        poly = []
        n = len(vs)
        for i in range(n):
            a, b = vs[i], vs[(i + 1) % n]
            if flags[i]:
                poly.append(("v", a))
            if flags[i] != flags[(i + 1) % n]:
                poly.append(("x", crossing(a, b)))
        if len(poly) < 3:
            raise RuntimeError("degenerate clipped face")
        # Every dead span collapses to a pair of neighbouring crossings in
        # the cut polygon -- that pair is one chord along the front, and the
        # front verts it passes are spliced back in.
        m = len(poly)
        walked = []
        for i in range(m):
            walked.append(poly[i])
            j = (i + 1) % m
            if poly[i][0] == "x" and poly[j][0] == "x":
                chords.append((poly[i][1], poly[j][1]))
                ca = plan.crossings[poly[i][1]]
                cb = plan.crossings[poly[j][1]]
                for p in _front_span(front, ca, cb):
                    walked.append(("f", p))
        poly = walked
        # Orientation guard. The crossings are allowed to be snapped a fair
        # way onto the front (see the tolerance above), and a bad snap could
        # in principle turn the cut polygon inside out or make it
        # self-intersect. The original faces project CCW onto the region
        # plane, so anything not strictly CCW here is wrong -- raise into the
        # per-region fallback rather than build it.
        cut_2d = []
        for kind, val in poly:
            if kind == "v":
                cut_2d.append(project_to_2d(region, val.co))
            elif kind == "x":
                cut_2d.append(plan.crossings[val].p2d)
            else:
                cut_2d.append(val)
        if _signed_area(cut_2d) <= 0.0:
            raise RuntimeError("clipped face lost its orientation")
        plan.clipped.append((f, poly))
        plan.consumed.append(f)

    # -- validation: the chords must close the front exactly -------------
    # Every crossing sits on an interior edge shared by two faces, so it
    # must be an endpoint of exactly two chords. A degree of 1 means the
    # front cut through a face whose every vertex was already consumed --
    # nothing would cover that stretch and the result would be a hole.
    deg = {}
    for ka, kb in chords:
        if ka == kb:
            raise RuntimeError("degenerate chord")
        deg[ka] = deg.get(ka, 0) + 1
        deg[kb] = deg.get(kb, 0) + 1
    if set(deg) != set(plan.crossings):
        raise RuntimeError("crossing not bounded by a chord")
    if any(d != 2 for d in deg.values()):
        raise RuntimeError("front not closed by the clipped faces")
    covered = {c.loop for c in plan.crossings.values()}
    if len(covered) != len(front):
        raise RuntimeError("front loop left uncovered")

    # -- splice the crossings into the wall chains -----------------------
    # A crossing that landed in the middle of a front segment splits the top
    # edge of that segment's wall face; without inserting it there the wall
    # keeps a T-junction against the clipped face.
    per_seg = {}
    for key, c in plan.crossings.items():
        if c.splice:
            per_seg.setdefault((c.loop, c.seg), []).append((c.u, c.p2d))
    for (li, si), items in per_seg.items():
        items.sort()
        pts = front[li]
        vids = front_vids[li]
        a2, b2 = pts[si], pts[(si + 1) % len(pts)]
        e = tl.verts[vids[si]].right_edge
        chain = chains.get(e)
        if not chain:
            raise RuntimeError("front segment has no wall chain")
        at = None
        for k in range(len(chain) - 1):
            if (_dist2d(chain[k], a2) <= MIN_EDGE_2D
                    and _dist2d(chain[k + 1], b2) <= MIN_EDGE_2D):
                at, forward = k, True
                break
            if (_dist2d(chain[k], b2) <= MIN_EDGE_2D
                    and _dist2d(chain[k + 1], a2) <= MIN_EDGE_2D):
                at, forward = k, False
                break
        if at is None:
            raise RuntimeError("front segment not found in its wall chain")
        ins = [p for _u, p in items] if forward else [p for _u, p in reversed(items)]
        chain[at + 1:at + 1] = ins
    plan.chains = chains
    return plan


def _bbox_2d(pts):
    return (min(p[0] for p in pts), min(p[1] for p in pts),
            max(p[0] for p in pts), max(p[1] for p in pts))


def _loop_encloses(outer, inner):
    """Is closed polyline ``inner`` nested inside closed polyline ``outer``?

    Voted over several of ``inner``'s verts instead of trusting one: a hole
    loop can touch its container (tangency at a pinch point), and
    ``_point_in_poly`` is undefined for a point exactly on an edge. The
    bounding box breaks a tie -- a nested loop's box is always inside the
    container's box, which is cheap and decides the tangent case.
    """
    votes_in = 0
    votes_out = 0
    n = len(inner)
    step = max(1, n // 8)
    for i in range(0, n, step):
        if _point_in_poly(outer, inner[i]):
            votes_in += 1
        else:
            votes_out += 1
    if votes_in != votes_out:
        return votes_in > votes_out
    ox0, oy0, ox1, oy1 = _bbox_2d(outer)
    ix0, iy0, ix1, iy1 = _bbox_2d(inner)
    return ox0 <= ix0 and oy0 <= iy0 and ix1 <= ox1 and iy1 <= oy1


def _fill_front_loops(front, bmvert, new_face, report=None):
    """Cap the front loops, keeping holes as holes.

    A front loop's winding tells what it bounds: the region-on-the-left
    convention makes outer loops CCW (positive signed area) and hole loops
    CW. A CW loop nested inside a CCW one is a genuine hole in the surviving
    material, so that pair is tessellated as a polygon-with-hole instead of
    being capped by two overlapping ngons (which is what a naive per-loop
    ngon fill produces).

    This is the *fallback* path, so it must never be the thing that raises:
    if the polygon-with-hole tessellation fails for a group, that group
    degrades to one plain ngon per loop -- pre-Task-11 behaviour.
    """
    areas = [_signed_area(pts) for pts in front]
    outers = [i for i, a in enumerate(areas) if a >= 0.0]
    holes = {}
    unhosted = []
    for h, a in enumerate(areas):
        if a >= 0.0:
            continue
        host = None
        for o in outers:
            if not _loop_encloses(front[o], front[h]):
                continue
            if host is None or areas[o] < areas[host]:
                host = o
        if host is None:
            # A CW loop bounds material on its *outside*; capping it (in
            # either winding) would fill the very area it is a hole in. With
            # no container to tessellate it against there is nothing safe to
            # build, so leave it alone.
            unhosted.append(h)
        else:
            holes.setdefault(host, []).append(h)
    if unhosted and report is not None:
        report({'WARNING'},
               "Smart Inset: %d front hole loop(s) left unfilled"
               % len(unhosted))

    made = 0
    for o in outers:
        hs = holes.get(o, ())
        if not hs:
            made += 1 if new_face([bmvert(p) for p in front[o]]) else 0
            continue
        try:
            seqs = [[Vector((p[0], p[1], 0.0)) for p in front[o]]]
            flat = list(front[o])
            for h in hs:
                seqs.append([Vector((p[0], p[1], 0.0)) for p in front[h]])
                flat.extend(front[h])
            tris = [[flat[i] for i in tri] for tri in tessellate_polygon(seqs)]
            if not tris:
                raise RuntimeError("hole tessellation produced nothing")
        except Exception:
            if report is not None:
                report({'WARNING'},
                       "Smart Inset: hole fill failed, ngon fill used")
            for li in (o,) + tuple(hs):
                made += 1 if new_face([bmvert(p) for p in front[li]]) else 0
            continue
        for pts in tris:
            if _signed_area(pts) < 0.0:
                pts.reverse()
            made += 1 if new_face([bmvert(p) for p in pts]) else 0
    return made


def apply_inset(bm, region, tl, t, depth, use_collapse, report=None):
    """Rebuild the region at thickness ``t``. Mutates ``bm``.

    Interior faces the front has not reached yet are preserved: their verts
    keep their original positions and the faces the front cuts through are
    clipped against it (see ``_plan_interior_clip``). If that cannot be done
    watertight the whole region degrades to the plain ngon fill and
    ``report`` is warned.

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

    wall_faces = []   # deselected at the end (native inset does the same)
    inner_faces = []  # the new inner surface -- left selected

    def new_face(poly, src=None, bucket=None):
        poly = [vt for i, vt in enumerate(poly) if vt not in poly[:i]]
        if len(poly) < 3 or _is_sliver(poly):
            return None
        try:
            f = bm.faces.new(poly)
        except ValueError:
            return None
        _copy_face_attrs(f, src)
        if bucket is not None:
            bucket.append(f)
        return f

    walls = tl.walls_at(t_eff)
    chains = {j: list(walls.get(j, ())) for j in range(tl.edge_count)}

    # -- interior preservation plan (nothing is mutated yet) -------------
    plan = None
    if _clip_eligible(tl):
        try:
            plan = _plan_interior_clip(
                region, tl, t_eff,
                {j: list(c) for j, c in chains.items()}, key_of)
        except Exception:
            plan = None
            if report is not None:
                report({'WARNING'},
                       "Smart Inset: interior clip failed, ngon fill used")
        if plan is not None:
            chains = plan.chains

    made_faces = 0
    for j in range(tl.edge_count):
        a3, b3 = region.edge_orig_verts[j]
        chain = [bmvert(p) for p in chains.get(j, ())]
        src = region.edge_orig_faces[j]
        if new_face([a3, b3] + chain, src, wall_faces) is not None:
            made_faces += 1

    if plan is None:
        front = [[tl.pos_at(vid, t_eff) for vid in loop]
                 for loop in tl.front_at(t_eff)]
        if front:
            # No original face maps onto a cap ngon (the front consumed the
            # interior outright), so any region face is as good a donor as
            # another -- take the first for a stable, non-zeroed result.
            cap_src = region.faces[0] if region.faces else None
            made_faces += _fill_front_loops(
                front, bmvert,
                lambda poly: new_face(poly, cap_src, inner_faces), report)
    else:
        # The clipped faces' chords already close every front loop, so no
        # cap ngon is needed -- the preserved interior *is* the cap.
        lost = 0
        for _f, poly in plan.clipped:
            verts = []
            for kind, val in poly:
                if kind == "v":
                    verts.append(val)
                elif kind == "x":
                    verts.append(bmvert(plan.crossings[val].p2d))
                else:
                    verts.append(bmvert(val))
            # A clipped face is literally the surviving part of `_f`, so it
            # inherits that face's material and loop data exactly.
            n_ok = 1 if new_face(verts, _f, inner_faces) is not None else 0
            made_faces += n_ok
            lost += 1 - n_ok
        if lost and report is not None:
            report({'WARNING'},
                   "Smart Inset: %d clipped face(s) dropped as degenerate"
                   % lost)

    if abs(depth) > 1e-9:
        n = region.basis[2]
        # The preserved interior is part of the new inner surface, so it has
        # to travel with the fresh verts or the surface tears at the clip.
        for vt in fresh:
            vt.co += n * depth
        if plan is not None:
            for vt in plan.survivors:
                vt.co += n * depth

    doomed = plan.consumed if plan is not None else region.faces
    if doomed:
        bmesh.ops.delete(bm, geom=doomed, context='FACES')
    # A vert created for a wall that turned out degenerate would be left
    # dangling; drop the ones nothing ended up using. Preserved interior verts
    # go through the same sweep: if the clipped face that was supposed to hold
    # one got dropped as degenerate, it is loose now. They are safe to delete
    # because an interior vert of a region has no faces outside it by
    # definition -- that is what put it in `survivors` in the first place.
    loose = list(fresh)
    if plan is not None:
        loose.extend(plan.survivors)
    orphans = [vt for vt in loose if vt.is_valid and not vt.link_faces]
    if orphans:
        bmesh.ops.delete(bm, geom=orphans, context='VERTS')
    # Preserved interior faces are part of the new inner surface too, so they
    # stay selected alongside the freshly built caps/clips.
    if plan is not None:
        inner_faces.extend(plan.kept)
    _apply_selection(inner_faces, wall_faces)
    bm.normal_update()
    return made_faces, True


def _outset_positions(region, weights, t_abs):
    """Per-loop outward-displaced 2D positions at ``t_abs``.

    Naive dual of the wavefront math ``core.build_timeline`` uses at each
    vertex: same ``vertex_velocity(n_prev, n_next, w_prev, w_next)`` solve,
    but with both incident edge normals negated first (outward instead of
    inward), and no wavefront/events -- every vertex just moves straight out
    by its own velocity times ``t_abs``. That means it mirrors native
    mesh.inset's "outset" checkbox: no collapse handling, so a reflex corner
    or a large enough ``t_abs`` can make the outer contour self-intersect --
    acceptable and out of scope by design (task-10 brief).

    ``weights`` is the resolved per-loop weight list (see
    ``resolve_weights``); ``weights[li][i]`` is the weight of edge i->i+1,
    matching ``region.loops2d``/``region.weights``. Returns
    ``list[list[(x, y)]]`` parallel to ``region.loops2d``.
    """
    out = []
    for loop2d, ws in zip(region.loops2d, weights):
        n = len(loop2d)
        pts = []
        for i in range(n):
            p_prev, p, p_next = loop2d[i - 1], loop2d[i], loop2d[(i + 1) % n]
            n_prev = core.edge_normal(p_prev, p)
            n_next = core.edge_normal(p, p_next)
            w_prev, w_next = ws[i - 1], ws[i]
            v = core.vertex_velocity((-n_prev[0], -n_prev[1]),
                                      (-n_next[0], -n_next[1]),
                                      w_prev, w_next)
            pts.append((p[0] + v[0] * t_abs, p[1] + v[1] * t_abs))
        out.append(pts)
    return out


def _apply_outset(bm, region, weights, t_abs, depth):
    """Build a naive outward offset of the region boundary. Mutates ``bm``.

    Unlike ``apply_inset`` the original region faces are left untouched --
    only an outer contour and the wall quads connecting it to the existing
    boundary are added. The outer verts are lifted to the region plane
    *without* a BVH surface snap: they lie outside the region by
    construction, so snapping them onto the region's own surface (the only
    thing the BVH knows about) would incorrectly pull them back toward the
    original boundary. This only matters for curved regions -- on a planar
    region lift_to_3d is exact either way.

    Returns ``(faces_created, mutated)``, same convention as ``apply_inset``.
    """
    if t_abs <= EPS:
        return 0, False

    def key_of(p2d):
        return (round(p2d[0], WELD_DIGITS), round(p2d[1], WELD_DIGITS))

    # Same weld-seeding trick as apply_inset: a boundary vert whose outward
    # velocity is zero (both incident edges frozen by use_boundary=False)
    # must land on its own original position and reuse the real BMVert
    # rather than spawn a coincident duplicate.
    made = {}
    for loop2d, loop3d in zip(region.loops2d, region.loops3d):
        for p2d, vt in zip(loop2d, loop3d):
            made.setdefault(key_of(p2d), vt)

    fresh = []   # only the verts this call created -- `depth` moves these

    def bmvert(p2d):
        key = key_of(p2d)
        vt = made.get(key)
        if vt is None:
            vt = bm.verts.new(lift_to_3d(region, p2d))
            made[key] = vt
            fresh.append(vt)
        return vt

    ring_faces = []   # the new outer ring -- left selected

    def new_face(poly, src=None):
        poly = [vt for i, vt in enumerate(poly) if vt not in poly[:i]]
        if len(poly) < 3 or _is_sliver(poly):
            return None
        try:
            f = bm.faces.new(poly)
        except ValueError:
            return None
        _copy_face_attrs(f, src)
        ring_faces.append(f)
        return f

    made_faces = 0
    outer_loops = _outset_positions(region, weights, t_abs)
    base = 0   # core edge id of loop3d[0] -- ids run loop-major, in order
    for loop3d, outer2d in zip(region.loops3d, outer_loops):
        n = len(loop3d)
        outer3d = [bmvert(p) for p in outer2d]
        for i in range(n):
            a3, b3 = loop3d[i], loop3d[(i + 1) % n]
            oa, ob = outer3d[i], outer3d[(i + 1) % n]
            src = region.edge_orig_faces[base + i]
            # a -> oa -> ob -> b keeps the wall's winding consistent with
            # the (untouched) region faces it borders -- see task-10 report.
            if new_face([a3, oa, ob, b3], src) is not None:
                made_faces += 1
        base += n

    if abs(depth) > 1e-9:
        n_axis = region.basis[2]
        for vt in fresh:
            vt.co += n_axis * depth

    orphans = [vt for vt in fresh if vt.is_valid and not vt.link_faces]
    if orphans:
        bmesh.ops.delete(bm, geom=orphans, context='VERTS')
    # Outset keeps the original faces, so the roles swap relative to inset:
    # the new ring is what stays selected, the untouched region drops out.
    _apply_selection(ring_faces, region.faces)
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
        description=(
            "Inward offset distance of the region boundary. Negative "
            "values outset instead: boundary verts move outward and no "
            "wavefront/collapse handling applies"
        ),
        default=0.05,
        soft_min=-10.0,
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
        # Cancel snapshot. Distinct from _initial_thickness on purpose: that
        # one is a *drag anchor* and is re-anchored on the current value every
        # time Shift/Ctrl is released or numeric entry is cleared, so
        # restoring from it on ESC would hand back a mid-drag value. These two
        # are written once, here, and never touched again.
        self._cancel_thickness = self.thickness
        self._cancel_depth = self.depth
        self._cancel_mode = self.mode
        self._cancel_use_collapse = self.use_collapse
        self._cancel_use_boundary = self.use_boundary
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
        self._seam_segs = []
        self._clamped = False
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
                # Cancel means cancel: every prop the modal can touch goes
                # back to its invoke-time value, toggles included.
                self.thickness = self._cancel_thickness
                self.depth = self._cancel_depth
                self.mode = self._cancel_mode
                self.use_collapse = self._cancel_use_collapse
                self.use_boundary = self._cancel_use_boundary
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
        self._seam_segs = []
        self._clamped = False
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
        caps = [clamp_cap(tl) for _region, tl in getattr(self, "_regions", ())]
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
        segs, seams, clamped = self._build_preview_layers()
        self._preview_segs = segs
        self._seam_segs = seams
        self._clamped = clamped

    def _build_preview_layers(self):
        """Compute the three preview layers in world space.

        Mirrors what ``apply_inset`` would build at the current thickness:
        the 2D positions lifted back onto the original surface and pushed
        along the region normal by ``depth``. Returns
        ``(front_segs, seam_segs, clamped)`` where each ``*_segs`` is a flat
        list of segment endpoints (pairs) and ``clamped`` is True when any
        region's requested thickness ran past its no-collapse cap.
        """
        front_segs, seam_segs = [], []
        clamped = False
        t = float(self.thickness)
        if abs(t) <= EPS:
            return front_segs, seam_segs, clamped   # zero: no-op

        if t < 0.0:
            return self._build_outset_preview_layers(-t), seam_segs, clamped

        for region, tl in getattr(self, "_regions", ()):
            t_eff = effective_t(tl, t, self.use_collapse)
            if t_eff <= EPS:
                continue
            if not self.use_collapse and t > clamp_cap(tl):
                clamped = True

            n = region.basis[2]
            offset = n * self.depth if abs(self.depth) > 1e-9 else None

            def to_world(p2d):
                co = surface_snap(region, lift_to_3d(region, p2d))
                return co + offset if offset is not None else co

            # -- front loops --------------------------------------------
            for loop in tl.front_at(t_eff):
                pts = [to_world(tl.pos_at(vid, t_eff)) for vid in loop]
                if len(pts) < 2:
                    continue
                for i, p in enumerate(pts):
                    front_segs.append(p)
                    front_segs.append(pts[(i + 1) % len(pts)])

            # -- medial seams --------------------------------------------
            # Wall-top chain segments whose both endpoints sit exactly on
            # a skeleton node born at or before t_eff: these are the
            # already-collapsed sections of the wavefront, so highlighting
            # them shows the user where collapse actually happened.
            node_keys = {
                (round(node.pos[0], WELD_DIGITS), round(node.pos[1], WELD_DIGITS))
                for node in tl.nodes if node.t <= t_eff + EPS
            }
            if not node_keys:
                continue
            walls = tl.walls_at(t_eff)
            for chain in walls.values():
                for i in range(len(chain) - 1):
                    p, q = chain[i], chain[i + 1]
                    pk = (round(p[0], WELD_DIGITS), round(p[1], WELD_DIGITS))
                    qk = (round(q[0], WELD_DIGITS), round(q[1], WELD_DIGITS))
                    if pk in node_keys and qk in node_keys:
                        seam_segs.append(to_world(p))
                        seam_segs.append(to_world(q))

        return front_segs, seam_segs, clamped

    def _build_outset_preview_layers(self, t_abs):
        """Front-loop segments for the naive outset preview (t < 0).

        No timeline/wavefront involved -- just the same per-vertex outward
        offset ``_apply_outset``/``_outset_positions`` would build, lifted to
        world space (no BVH snap, see ``_apply_outset``'s docstring) and
        pushed along the region normal by ``depth``. No seams, no clamp
        flag: those only mean something for the collapsing wavefront.
        """
        front_segs = []
        for region, _tl in getattr(self, "_regions", ()):
            weights = resolve_weights(region, self.use_boundary)
            n = region.basis[2]
            offset = n * self.depth if abs(self.depth) > 1e-9 else None
            for loop2d in _outset_positions(region, weights, t_abs):
                pts = [lift_to_3d(region, p) for p in loop2d]
                if offset is not None:
                    pts = [p + offset for p in pts]
                if len(pts) < 2:
                    continue
                for i, p in enumerate(pts):
                    front_segs.append(p)
                    front_segs.append(pts[(i + 1) % len(pts)])
        return front_segs

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
        def _project(segs):
            pts = []
            for i in range(0, len(segs) - 1, 2):
                pa = view3d_utils.location_3d_to_region_2d(
                    region_ui, rv3d, mw @ segs[i])
                pb = view3d_utils.location_3d_to_region_2d(
                    region_ui, rv3d, mw @ segs[i + 1])
                if pa is None or pb is None:
                    continue
                pts.append(Vector((pa[0], pa[1], 0.0)))
                pts.append(Vector((pb[0], pb[1], 0.0)))
            return pts

        front_2d, seam_2d = [], []
        try:
            front_2d = _project(getattr(self, "_preview_segs", None) or ())
            seam_2d = _project(getattr(self, "_seam_segs", None) or ())
        except Exception:
            front_2d, seam_2d = [], []

        if front_2d or seam_2d:
            # Clamp feedback: with collapse disallowed and the requested
            # thickness past the region's first-event cap, the front is
            # already sitting at the clamp -- flag it in the warning colour
            # instead of the normal preview cyan.
            front_role = (Role.ERROR_LINE if getattr(self, "_clamped", False)
                          else Role.PREVIEW_LINE)
            with draw_scope(blend="ALPHA"):
                if front_2d:
                    draw.edges_3d(front_2d, role=front_role, context=context)
                if seam_2d:
                    draw.edges_3d(seam_2d, role=Role.LOCKED_LINE, context=context)

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

        t = float(self.thickness)

        regions, warnings = collect_regions(bm, self.mode)
        for msg in warnings:
            self.report({'WARNING'}, "Smart Inset: region skipped (%s)" % msg)
        if not regions:
            if not warnings:
                self.report({'WARNING'}, "Smart Inset: no faces selected")
            return {'CANCELLED'}
        if abs(t) <= EPS:
            self.report({'WARNING'},
                        "Smart Inset: zero thickness — nothing to apply")
            return {'CANCELLED'}

        changed = 0
        mutated = False
        if t < 0.0:
            # Naive outset, no skeleton/timeline needed -- see _apply_outset.
            for region in regions:
                weights = resolve_weights(region, self.use_boundary)
                n_faces, did = _apply_outset(bm, region, weights, -t,
                                             self.depth)
                changed += n_faces
                mutated = mutated or did
        else:
            for region, tl in self._build_timelines(regions):
                n_faces, did = apply_inset(bm, region, tl, t, self.depth,
                                           self.use_collapse, self.report)
                changed += n_faces
                mutated = mutated or did

        if not mutated:
            # Every region's effective thickness degenerated to zero, so bm was
            # left untouched. That is a legitimate outcome (collapse off on a
            # region whose first event is at t=0, an all-frozen boundary, ...)
            # but returning CANCELLED without a word looks like a dead hotkey.
            self.report({'WARNING'},
                        "Smart Inset: effective thickness is zero for every "
                        "region — nothing to apply (try Collapse/Boundary on, "
                        "or a larger thickness)")
            return {'CANCELLED'}

        # Any mutation must be reported as FINISHED so Blender pushes an undo
        # step -- returning CANCELLED after geometry was already deleted would
        # leave the change unundoable.
        if not changed:
            self.report({'WARNING'},
                        "Smart Inset: no faces produced for this thickness")
        # apply_inset/_apply_outset set the face-level selection; propagate it
        # to whatever the mesh's actual select mode needs.
        bm.select_flush_mode()
        bmesh.update_edit_mesh(me, loop_triangles=True, destructive=True)
        return {'FINISHED'}
