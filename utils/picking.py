"""Unified picking math: raycast, nearest-vertex/edge/face, snap points.

Canonical implementations consolidated from `mesh_cursor_bisect.py` (the most
mature version) plus simpler operators (drag_snap, quick_connect, drag_snap_uv,
visual_origin). All operators should route through these helpers instead of
inlining their own raycast / nearest-X loops.

Picking thresholds and weights are exposed as module constants and as theme
attributes for user tuning. See `IOPS_AddonPreferences.cursor_bisect_snap_threshold`
for the canonical screen-space px tolerance.
"""
from __future__ import annotations

from typing import Sequence

import bpy
import bmesh
import numpy as np
from mathutils import Vector
from mathutils.bvhtree import BVHTree
from mathutils.geometry import intersect_point_line
from mathutils.kdtree import KDTree
from bpy_extras.view3d_utils import (
    region_2d_to_vector_3d,
    region_2d_to_origin_3d,
    location_3d_to_region_2d,
)


# --- Defaults -----------------------------------------------------------

SNAP_THRESHOLD_PX = 30.0
SNAP_SCREEN_WEIGHT = 0.7  # closest_snap_point: the screen share of a score, the rest is world
RAYCAST_OFFSET_DISTANCE = 0.0001
MAX_RAYCAST_ITERATIONS = 100
CORNER_FALLBACK_COORDS = (
    (0.10, 0.10), (0.90, 0.10), (0.10, 0.90), (0.90, 0.90),
    (0.50, 0.10), (0.50, 0.90), (0.10, 0.50), (0.90, 0.50),
)


# --- Pixel size ----------------------------------------------------------

def px_world_at(region, rv3d, pos):
    """World size of one screen pixel at the depth of `pos` (0 when `pos`
    is behind the camera), exact in perspective and ortho.

    A world offset parallel to the screen maps to
    `d * W00 * width / (2 * w)` pixels, with `W00` from the pure projection
    (`rv3d.window_matrix`) and `w` the clip-space w of `pos`. Do NOT derive
    this from `region_2d_to_location_3d` with a one-pixel offset: mathutils
    works in float32 and the 1 px difference drowns in rounding (measured
    0.5x..2x off, pulsing with the mouse position).
    """
    pm = rv3d.perspective_matrix
    w = pm[3][0] * pos[0] + pm[3][1] * pos[1] + pm[3][2] * pos[2] + pm[3][3]
    if w <= 1e-9 or region.width <= 0:
        return 0.0
    w00 = rv3d.window_matrix[0][0]
    if abs(w00) < 1e-12:
        return 0.0
    return 2.0 * w / (region.width * abs(w00))


def pull_toward_viewer(region, rv3d, points, px):
    """Return copies of world `points` moved `px` screen pixels toward the
    viewer (along the view ray in perspective, along the view axis in
    ortho). Use it to lift overlay lines off the surface they lie on: a
    fixed world offset z-fights on large meshes where one depth-buffer
    step is metres, while a pixel offset scales with distance. Points
    behind the camera are returned unchanged."""
    out = []
    if rv3d.is_perspective:
        cam = rv3d.view_matrix.inverted().translation
        for p in points:
            p = Vector(p)
            d = px * px_world_at(region, rv3d, p)
            if d <= 0.0:
                out.append(p)
                continue
            to_cam = cam - p
            if to_cam.length_squared <= 1e-18:
                out.append(p)
                continue
            out.append(p + to_cam.normalized() * d)
    else:
        toward = rv3d.view_matrix.to_3x3().inverted() @ Vector((0.0, 0.0, 1.0))
        toward.normalize()
        for p in points:
            p = Vector(p)
            out.append(p + toward * (px * px_world_at(region, rv3d, p)))
    return out


# --- Raycast ------------------------------------------------------------

def raycast_from_mouse(context, mouse_coord, *, restrict_to=None, exclude=None,
                       visible_only: bool = False,
                       max_iterations: int = MAX_RAYCAST_ITERATIONS,
                       region=None, rv3d=None, viewport=None, ray=None,
                       owner_cache: dict | None = None):
    """Raycast from mouse position. If `restrict_to` is provided (an iterable
    of objects), the ray pierces through anything else. If `exclude` is provided
    (an iterable of objects), the ray pierces through those objects. If
    `visible_only` is True, hits on objects whose `visible_get()` is False in
    the current view layer (eye-icon / H-hidden) are also pierced — depsgraph
    still contains those objects, so `scene.ray_cast` would otherwise see them.
    The ray repeats until it hits a permitted object or runs out of iterations.

    Pass `region` / `rv3d` explicitly when the caller runs outside the 3D
    viewport's WINDOW region (N-panel / popup buttons); otherwise they are
    taken from the context. `viewport` is the SpaceView3D handed to
    `visible_get` (local view, per-viewport overrides); when omitted it is
    looked up from the context, which only works while the context is the
    3D viewport itself (not the Properties editor).

    `ray=(origin, direction)` casts that world-space ray instead of the one
    under the mouse — for picking geometry that is displayed transformed
    (a ghost) by casting the inverse-transformed ray at the originals.

    `owner_cache` (a dict the caller keeps for the duration of a modal)
    memoises `hit_owner` + visibility per (object, instance matrix):
    resolving a collection-instance hit walks every depsgraph instance in
    Python, which is too slow to repeat on every mouse move in a
    kitbash scene. Instances don't change while a modal holds all events.

    Returns `(result, location, normal, face_index, obj, matrix)`. On miss,
    returns `(False, None, None, None, None, None)`.
    """
    if region is None:
        region = context.region
    if rv3d is None:
        rv3d = context.space_data.region_3d
    if region is None or rv3d is None:
        return (False, None, None, None, None, None)

    if ray is not None:
        ray_origin, view_vector = Vector(ray[0]), Vector(ray[1])
    else:
        view_vector = region_2d_to_vector_3d(region, rv3d, mouse_coord)
        ray_origin = region_2d_to_origin_3d(region, rv3d, mouse_coord)
    depsgraph = context.evaluated_depsgraph_get()
    allowed = set(restrict_to) if restrict_to is not None else None
    blocked = set(exclude) if exclude is not None else None
    view_vec_norm = view_vector.normalized()
    # Pass the active SpaceView3D to visible_get so local-view (Numpad /) and
    # per-viewport visibility overrides are respected. Fall back to area.spaces
    # when context.space_data isn't the VIEW_3D (e.g. invoked from a header).
    if visible_only and viewport is None:
        sv = getattr(context, "space_data", None)
        if sv is None or sv.type != "VIEW_3D":
            area = getattr(context, "area", None)
            sv = area.spaces.active if (area is not None and area.type == "VIEW_3D") else None
        viewport = sv if (sv is not None and sv.type == "VIEW_3D") else None
    elif not visible_only:
        viewport = None

    current_origin = ray_origin
    for _ in range(max_iterations):
        result, location, normal, face_index, obj, matrix = context.scene.ray_cast(
            depsgraph, current_origin, view_vector)
        if not result:
            break
        # Collection instances: the hit is the instanced mesh (not in the
        # view layer), so ownership / visibility belong to the instancer.
        cache_key = None
        cached = None
        if owner_cache is not None and obj is not None:
            cache_key = (obj.as_pointer(),
                         tuple(round(matrix[i][j], 5) for i in range(4) for j in range(4)))
            cached = owner_cache.get(cache_key)
        if cached is not None:
            owner, visible = cached
        else:
            owner = (hit_owner(depsgraph, obj, matrix, view_layer=context.view_layer)
                     if obj is not None else None)
            visible = True
            if visible_only and owner is not None:
                try:
                    visible = bool(owner.visible_get(viewport=viewport))
                except (ReferenceError, TypeError):
                    visible = False
            if cache_key is not None:
                owner_cache[cache_key] = (owner, visible)
        permitted = (allowed is None or (owner is not None and owner in allowed))
        if blocked is not None and owner is not None and owner in blocked:
            permitted = False
        if visible_only and not visible:
            permitted = False
        if permitted:
            return (True, location, normal, face_index, obj, matrix)
        if location is None:
            break
        current_origin = location + view_vec_norm * RAYCAST_OFFSET_DISTANCE

    return (False, None, None, None, None, None)


def hit_owner(depsgraph, obj, matrix, *, view_layer=None):
    """The view-layer object responsible for a `scene.ray_cast` hit: the
    object itself, or — when the hit geometry comes from a collection
    instance — the instancing Empty. Instances are matched by object and
    world matrix among `depsgraph.object_instances`; falls back to the hit
    object when no instance matches.

    The fast path (hit matrix == the object's own matrix) is only trusted
    for objects that are in `view_layer`: an instanced object sitting at
    the origin under an instancer at the origin reports the same matrix."""
    try:
        original = obj.original
    except (ReferenceError, AttributeError):
        return obj
    if view_layer is not None:
        try:
            in_layer = original.name in view_layer.objects
        except (ReferenceError, AttributeError):
            in_layer = False
        if in_layer:
            try:
                own = obj.matrix_world
                if all(abs(own[i][j] - matrix[i][j]) < 1e-5 for i in range(4) for j in range(4)):
                    return original
            except (ReferenceError, AttributeError):
                pass
    for inst in depsgraph.object_instances:
        if not inst.is_instance:
            continue
        try:
            if inst.object.original != original:
                continue
            m = inst.matrix_world
        except ReferenceError:
            continue
        if all(abs(m[i][j] - matrix[i][j]) < 1e-5 for i in range(4) for j in range(4)):
            parent = inst.parent
            return parent.original if parent is not None else original
    return original


def raycast_with_corner_fallback(context, mouse_coord, *, restrict_to,
                                 max_iterations: int = MAX_RAYCAST_ITERATIONS):
    """`raycast_from_mouse` plus an 8-corner viewport fallback. Designed for
    cases where the user's cursor is over a hole in a large face — corner
    rays often catch the same selected mesh from a different angle.

    `restrict_to` is required (the corner fallback only makes sense when
    you're looking for specific objects)."""
    hit = raycast_from_mouse(context, mouse_coord, restrict_to=restrict_to,
                             max_iterations=max_iterations)
    if hit[0]:
        return hit

    region = context.region
    for fx, fy in CORNER_FALLBACK_COORDS:
        coord = (int(region.width * fx), int(region.height * fy))
        hit = raycast_from_mouse(context, coord, restrict_to=restrict_to,
                                 max_iterations=max_iterations)
        if hit[0]:
            return hit
    return (False, None, None, None, None, None)


# --- Snap points on a face ---------------------------------------------

def face_snap_points(face, *, subdivisions: int = 0):
    """Build snap points for a bmesh face.

    Returns a list of `(kind, co_local)` tuples where kind is one of
    `'vertex'`, `'center'`, `'edge'`. The center uses an area-weighted
    centroid (fan triangulation) so n-gons get a sensible point.
    """
    if not face:
        return []

    points = [("vertex", v.co.copy()) for v in face.verts]

    verts = [v.co for v in face.verts]
    if len(verts) >= 3:
        v0 = verts[0]
        total_area = 0.0
        sum_centroid = Vector((0.0, 0.0, 0.0))
        for i in range(1, len(verts) - 1):
            a = verts[i] - v0
            b = verts[i + 1] - v0
            area = a.cross(b).length * 0.5
            centroid = (v0 + verts[i] + verts[i + 1]) / 3.0
            sum_centroid += centroid * area
            total_area += area
        if total_area > 0.0:
            center = sum_centroid / total_area
        else:
            center = face.calc_center_median()
        points.append(("center", center))

    if subdivisions > 0:
        for edge in face.edges:
            v1, v2 = edge.verts
            for i in range(1, subdivisions + 1):
                t = i / (subdivisions + 1)
                points.append(("edge", v1.co.lerp(v2.co, t)))

    return points


# --- Closest snap point (weighted screen + world) ----------------------

def _snap_points_extent(snap_points):
    """Largest axis span of the snap points in local space: a scale-free
    measure of how big the picked face is."""
    if not snap_points:
        return 0.0
    lo = Vector((float("inf"),) * 3)
    hi = Vector((float("-inf"),) * 3)
    for _kind, p in snap_points:
        for i in range(3):
            lo[i] = min(lo[i], p[i])
            hi[i] = max(hi[i], p[i])
    return max(hi - lo)


def _world_tolerance(snap_points, obj_matrix, mouse_pos_world, region, rv3d,
                     screen_threshold_px):
    """World-space snap tolerance: the screen threshold converted to metres
    at the depth of the hit, so it follows zoom and mesh size alike.

    Never derive this from the object's scale: a scale-1 object holding a
    10 km mesh and a scale-100 object holding a 100 m mesh are the same
    thing on screen. When the hit is behind the camera (pixel size 0) or
    there is no viewport, fall back to a fraction of the face's own extent.
    """
    tol = 0.0
    if region is not None and rv3d is not None:
        tol = screen_threshold_px * px_world_at(region, rv3d, mouse_pos_world)
    if tol <= 0.0:
        extent = _snap_points_extent(snap_points) * max(obj_matrix.to_scale())
        tol = extent * 0.25
    return max(tol, 1e-9)


def closest_snap_point(context, snap_points, obj_matrix, mouse_coord,
                       mouse_pos_world, *,
                       screen_threshold_px: float = SNAP_THRESHOLD_PX,
                       screen_weight: float = SNAP_SCREEN_WEIGHT):
    """Find the snap point closest to mouse using weighted screen + world
    distance. View-frustum aware: points off-screen fall back to pure world
    scoring.

    Both distances are normalised by the same tolerance expressed in their
    own units: `screen_threshold_px` pixels on screen, and that many pixels
    converted to metres at the hit depth in world space (see
    `_world_tolerance`). So the result is independent of mesh size, object
    scale and zoom level.

    Args:
        snap_points: list of `(kind, co_local)` from `face_snap_points()`.
        obj_matrix:  object's matrix_world (used to bring local → world).
        mouse_coord: 2D pixel coord under the cursor.
        mouse_pos_world: ray-hit position in world space (provides depth).
        screen_threshold_px: pixel tolerance for normalizing screen scores.
        screen_weight: 0..1, blend factor for screen vs world score
                       (default 0.7 — screen-dominant).

    Returns `(kind, co_local, co_world)` or `None` if nothing within range.
    """
    if not snap_points:
        return None

    region = context.region
    rv3d = getattr(context.space_data, "region_3d", None)
    if rv3d is None or region is None:
        return _closest_snap_point_world(snap_points, obj_matrix, mouse_pos_world)

    world_threshold = _world_tolerance(snap_points, obj_matrix, mouse_pos_world,
                                       region, rv3d, screen_threshold_px)

    mouse_v = Vector(mouse_coord)
    world_weight = 1.0 - screen_weight

    closest = None
    best_score = float("inf")

    for kind, point_local in snap_points:
        point_world = obj_matrix @ point_local
        world_score = (point_world - mouse_pos_world).length / world_threshold

        screen = location_3d_to_region_2d(region, rv3d, point_world)
        if screen and 0 <= screen[0] <= region.width and 0 <= screen[1] <= region.height:
            screen_dist = (mouse_v - Vector(screen)).length
            screen_score = screen_dist / screen_threshold_px
            score = screen_score * screen_weight + world_score * world_weight
        else:
            score = world_score

        if score < 1.5 and score < best_score:
            best_score = score
            closest = (kind, point_local, point_world)

    return closest if best_score < 1.0 else None


def _closest_snap_point_world(snap_points, obj_matrix, mouse_pos_world):
    """Pure-world fallback when screen projection is unavailable. The
    tolerance is a fraction of the face's own extent, not the object scale."""
    if not snap_points:
        return None
    threshold = _world_tolerance(snap_points, obj_matrix, mouse_pos_world,
                                 None, None, 0.0)

    closest = None
    closest_dist = float("inf")
    for kind, point_local in snap_points:
        point_world = obj_matrix @ point_local
        d = (point_world - mouse_pos_world).length
        if d < closest_dist:
            closest_dist = d
            closest = (kind, point_local, point_world)

    return closest if closest_dist < threshold else None


def snap_points_in_reach(context, cos, obj_matrix, mouse_coord,
                         mouse_pos_world, *,
                         screen_threshold_px: float = SNAP_THRESHOLD_PX,
                         screen_weight: float = SNAP_SCREEN_WEIGHT):
    """Indices, in order, of the snap points `closest_snap_point` can pick
    with the same arguments; None where it scores them all against their
    own extent (no view, or the hit behind it), so rank them all there.

    For many candidates, such as every vertex of a large mesh, rank only
    these: the pick is the same. `cos` holds the points' local coordinates,
    an (N, 3) array. A point on screen scores at least `screen_weight` x
    its pixel distance over `screen_threshold_px`, one off screen its world
    distance over the world tolerance, and only a score under 1 is picked,
    so the rest never are. Pixel and world margins cover the float32
    rounding of `closest_snap_point`'s own projection.
    """
    region = context.region
    rv3d = getattr(context.space_data, "region_3d", None)
    if region is None or rv3d is None:
        return None
    tol = screen_threshold_px * px_world_at(region, rv3d, mouse_pos_world)
    if tol <= 0.0:
        return None
    cos = np.asarray(cos, dtype=float).reshape(-1, 3)
    mw = np.array(obj_matrix, dtype=float)
    at = np.array(mouse_pos_world, dtype=float)
    to_clip = np.array(rv3d.perspective_matrix, dtype=float) @ mw
    clip = cos @ to_clip[:, :3].T + to_clip[:, 3]
    gap = cos @ mw[:3, :3].T + mw[:3, 3] - at
    reach_world = max(tol, 1e-9) * 1.001 + 1e-6 * (1.0 + float(np.abs(at).max()))
    near = (gap * gap).sum(axis=1) <= reach_world * reach_world
    if screen_weight > 0.0:
        w = clip[:, 3]
        with np.errstate(all="ignore"):
            dx = region.width / 2.0 * (1.0 + clip[:, 0] / w) - mouse_coord[0]
            dy = region.height / 2.0 * (1.0 + clip[:, 1] / w) - mouse_coord[1]
            screen = np.where(w > 0.0, dx * dx + dy * dy, np.inf)
        reach_px = screen_threshold_px / screen_weight + 2.0
        near |= screen <= reach_px * reach_px
    return np.flatnonzero(near).tolist()


# --- Closest edge in a face --------------------------------------------

def closest_edge_screen(context, edges, obj_matrix, mouse_coord):
    """Among ``edges`` (BMEdge iterable) find the one whose screen-projected
    segment is nearest to the mouse. Returns ``(index, distance_px)`` into
    the iteration order, or ``(None, inf)`` when nothing projects.
    """
    region = context.region
    rv3d = getattr(context.space_data, "region_3d", None) or context.region_data
    if rv3d is None:
        return None, float("inf")

    mouse_v = Vector(mouse_coord)
    closest_idx = None
    closest_dist = float("inf")

    for i, edge in enumerate(edges):
        v1, v2 = edge.verts
        s1 = location_3d_to_region_2d(region, rv3d, obj_matrix @ v1.co)
        s2 = location_3d_to_region_2d(region, rv3d, obj_matrix @ v2.co)
        if not (s1 and s2):
            continue

        edge_vec = Vector((s2[0] - s1[0], s2[1] - s1[1]))
        mouse_vec = mouse_v - Vector(s1)
        if edge_vec.length_squared == 0.0:
            continue
        t = max(0.0, min(1.0, mouse_vec.dot(edge_vec) / edge_vec.length_squared))
        proj = Vector(s1) + t * edge_vec
        d = (mouse_v - proj).length

        if d < closest_dist:
            closest_dist = d
            closest_idx = i

    return closest_idx, closest_dist


def closest_face_edge(context, face, obj_matrix, mouse_coord):
    """Find the face edge whose screen-projected segment is nearest to the
    mouse. Returns the edge's index within `face.edges` (0 on failure).
    """
    if not face or not face.edges:
        return 0
    idx, _ = closest_edge_screen(context, face.edges, obj_matrix, mouse_coord)
    return 0 if idx is None else idx


# --- Nearest vertex (screen-space) -------------------------------------

def nearest_vertex_screen(context, obj, mouse_coord, *,
                          threshold_px: float = SNAP_THRESHOLD_PX,
                          check_occlusion: bool = False):
    """Find the index of the mesh vertex with smallest screen distance to
    `mouse_coord`. Returns `(index, co_world_2d_vector)` or `(None, None)`.

    If `check_occlusion=True`, each candidate is ray-tested against the
    scene to skip vertices hidden behind other geometry.
    """
    if obj is None or not hasattr(obj, "data"):
        return None, None

    region = context.region
    rv3d = context.space_data.region_3d
    if rv3d is None:
        return None, None

    # Allow both edit-mode (bmesh) and object-mode (Mesh.vertices) access.
    if obj.mode == "EDIT":
        bm = bmesh.from_edit_mesh(obj.data)
        bm.verts.ensure_lookup_table()
        verts_iter = ((v.index, v.co) for v in bm.verts)
    else:
        verts_iter = ((i, v.co) for i, v in enumerate(obj.data.vertices))

    mw = obj.matrix_world
    mouse_v = Vector(mouse_coord)
    threshold_sq = threshold_px * threshold_px

    best_idx = None
    best_co = None
    best_dist_sq = float("inf")
    candidates: list[tuple[float, int, Vector]] = []

    for idx, co_local in verts_iter:
        co_world = mw @ co_local
        co_screen = location_3d_to_region_2d(region, rv3d, co_world)
        if co_screen is None:
            continue
        dx = mouse_v.x - co_screen[0]
        dy = mouse_v.y - co_screen[1]
        d_sq = dx * dx + dy * dy
        if d_sq > threshold_sq:
            continue
        if check_occlusion:
            candidates.append((d_sq, idx, co_world))
        elif d_sq < best_dist_sq:
            best_dist_sq = d_sq
            best_idx = idx
            best_co = co_world

    if not check_occlusion:
        return best_idx, best_co

    # Sort by 2D distance, return first one that isn't occluded by another
    # mesh closer to the camera than the candidate vertex.
    candidates.sort(key=lambda c: c[0])
    depsgraph = context.evaluated_depsgraph_get()
    ray_origin = region_2d_to_origin_3d(region, rv3d, mouse_coord)
    for _d_sq, idx, co_world in candidates:
        direction = (co_world - ray_origin)
        dist = direction.length
        if dist <= 1e-6:
            return idx, co_world
        result, *_ = context.scene.ray_cast(
            depsgraph, ray_origin, direction.normalized(),
            distance=dist - 0.001)
        if not result:
            return idx, co_world
    return None, None


# --- Closest bbox corner (object mode) ---------------------------------

def nearest_bbox_corner(context, obj, mouse_coord):
    """Return `(corner_index, world_pos)` of the closest `obj.bound_box`
    corner to `mouse_coord` in screen space. None on failure."""
    if obj is None:
        return None, None
    region = context.region
    rv3d = context.space_data.region_3d
    if rv3d is None:
        return None, None

    mw = obj.matrix_world
    mouse_v = Vector(mouse_coord)
    best_idx = None
    best_co = None
    best_dist_sq = float("inf")
    for i, local in enumerate(obj.bound_box):
        world = mw @ Vector(local)
        screen = location_3d_to_region_2d(region, rv3d, world)
        if screen is None:
            continue
        dx = mouse_v.x - screen[0]
        dy = mouse_v.y - screen[1]
        d_sq = dx * dx + dy * dy
        if d_sq < best_dist_sq:
            best_dist_sq = d_sq
            best_idx = i
            best_co = world
    return best_idx, best_co


# --- Closest point on segment ------------------------------------------

def closest_point_on_segment(point, a, b):
    """Project `point` onto segment `a..b`, clamped to `[a, b]`.
    Returns `(closest_point, t)` where `t ∈ [0, 1]`. Wraps mathutils'
    `intersect_point_line` and clamps."""
    closest, t = intersect_point_line(point, a, b)
    if t < 0.0:
        return a.copy(), 0.0
    if t > 1.0:
        return b.copy(), 1.0
    return closest, t


# --- UV KDTree ---------------------------------------------------------

def build_uv_kdtree(bm, uv_layer, *, only_selected: bool = False, extras=()):
    """Pre-balanced 3D KDTree built from UV coords (z=0). `extras` is an
    iterable of (u, v) tuples to also insert (e.g. UV cursor)."""
    coords = []
    for face in bm.faces:
        for loop in face.loops:
            if only_selected:
                # Blender 5.0+ moves uv_select_vert onto the loop directly
                sel = getattr(loop, "uv_select_vert", None)
                if sel is None:
                    sel = loop[uv_layer].select
                if not sel:
                    continue
            uv = loop[uv_layer].uv
            coords.append((uv.x, uv.y, 0.0))
    for extra in extras:
        coords.append((float(extra[0]), float(extra[1]), 0.0))

    kd = KDTree(len(coords))
    for i, c in enumerate(coords):
        kd.insert(c, i)
    kd.balance()
    return kd


# --- Edit-mode BMesh raycast ---------------------------------------------

def _edit_mesh_bvh(obj, cache, version):
    """BVH over the visible faces of `obj`'s edit BMesh plus the map from
    tree polygon index to `bm.faces` index. Memoised in `cache` (a dict the
    caller keeps for the duration of a modal) under (object name, `version`);
    bump `version` or call `invalidate_edit_mesh_cache` after a cut / undo.
    Returns `(None, [])` for a mesh with no visible faces."""
    key = (obj.name, version)
    if cache is not None:
        entry = cache.get(key)
        if entry is not None:
            return entry
        # A new version supersedes every older tree of the same object.
        for stale in [k for k in cache if k[0] == obj.name]:
            del cache[stale]
    bm = bmesh.from_edit_mesh(obj.data)
    bm.verts.ensure_lookup_table()
    bm.faces.ensure_lookup_table()
    vert_index = {v: i for i, v in enumerate(bm.verts)}
    verts = [v.co.copy() for v in bm.verts]
    polys = []
    face_map = []
    for f in bm.faces:
        if f.hide:
            continue
        polys.append([vert_index[v] for v in f.verts])
        face_map.append(f.index)
    tree = BVHTree.FromPolygons(verts, polys) if polys else None
    entry = (tree, face_map)
    if cache is not None:
        cache[key] = entry
    return entry


def invalidate_edit_mesh_cache(cache, obj=None):
    """Drop the cached BVH of `obj` (or of every object when `obj` is None)."""
    if not cache:
        return
    if obj is None:
        cache.clear()
        return
    for key in [k for k in cache if k[0] == obj.name]:
        del cache[key]


def raycast_edit_meshes(context, mouse_coord, objects, *, cache=None, version=0,
                        region=None, rv3d=None, ray=None):
    """Raycast the edit-mode BMesh of each object in `objects` and return the
    nearest hit as `(result, location, normal, face_index, obj, matrix)` in
    world space, `(False, None, None, None, None, None)` on a miss.

    Unlike `scene.ray_cast`, which hits the *evaluated* mesh, this casts at
    the cage the user is editing: `face_index` is always a valid `bm.faces`
    index no matter which modifiers (Triangulate, Mirror, Bevel, Subdivision
    ...) are enabled in the viewport, modifier-only geometry (a mirrored
    half) is not hit, and faces hidden with H are pierced.

    `ray=(origin, direction)` casts that world-space ray instead of the one
    under `mouse_coord`; `cache` / `version` are forwarded to
    `_edit_mesh_bvh`."""
    if ray is not None:
        ray_origin, view_vector = Vector(ray[0]), Vector(ray[1])
    else:
        if region is None:
            region = context.region
        if rv3d is None:
            rv3d = context.space_data.region_3d
        if region is None or rv3d is None:
            return (False, None, None, None, None, None)
        view_vector = region_2d_to_vector_3d(region, rv3d, mouse_coord)
        ray_origin = region_2d_to_origin_3d(region, rv3d, mouse_coord)

    best = None
    best_dist = None
    for obj in objects:
        if obj is None or obj.type != 'MESH' or obj.mode != 'EDIT':
            continue
        tree, face_map = _edit_mesh_bvh(obj, cache, version)
        if tree is None:
            continue
        matrix = obj.matrix_world
        inv = matrix.inverted_safe()
        local_origin = inv @ ray_origin
        local_dir = inv.to_3x3() @ view_vector
        if local_dir.length_squared == 0.0:
            continue
        hit = tree.ray_cast(local_origin, local_dir)
        if hit[0] is None:
            continue
        loc_world = matrix @ hit[0]
        dist = (loc_world - ray_origin).length
        if best is None or dist < best_dist:
            normal_world = (inv.to_3x3().transposed() @ hit[1]).normalized()
            best = (True, loc_world, normal_world, face_map[hit[2]], obj, matrix.copy())
            best_dist = dist
    return best if best is not None else (False, None, None, None, None, None)


def raycast_edit_meshes_with_corner_fallback(context, mouse_coord, objects, **kwargs):
    """`raycast_edit_meshes` plus the 8-corner viewport fallback of
    `raycast_with_corner_fallback`, for commit actions over a hole in a
    large face."""
    hit = raycast_edit_meshes(context, mouse_coord, objects, **kwargs)
    if hit[0]:
        return hit
    region = kwargs.get("region") or context.region
    if region is None:
        return hit
    for fx, fy in CORNER_FALLBACK_COORDS:
        coord = (int(region.width * fx), int(region.height * fy))
        hit = raycast_edit_meshes(context, coord, objects, **kwargs)
        if hit[0]:
            return hit
    return (False, None, None, None, None, None)
