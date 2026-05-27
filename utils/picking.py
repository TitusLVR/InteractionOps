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
from mathutils import Vector
from mathutils.geometry import intersect_point_line
from mathutils.kdtree import KDTree
from bpy_extras.view3d_utils import (
    region_2d_to_vector_3d,
    region_2d_to_origin_3d,
    location_3d_to_region_2d,
)


# --- Defaults -----------------------------------------------------------

SNAP_THRESHOLD_PX = 30.0
RAYCAST_OFFSET_DISTANCE = 0.0001
MAX_RAYCAST_ITERATIONS = 100
CORNER_FALLBACK_COORDS = (
    (0.10, 0.10), (0.90, 0.10), (0.10, 0.90), (0.90, 0.90),
    (0.50, 0.10), (0.50, 0.90), (0.10, 0.50), (0.90, 0.50),
)


# --- Raycast ------------------------------------------------------------

def raycast_from_mouse(context, mouse_coord, *, restrict_to=None, exclude=None,
                       max_iterations: int = MAX_RAYCAST_ITERATIONS):
    """Raycast from mouse position. If `restrict_to` is provided (an iterable
    of objects), the ray pierces through anything else. If `exclude` is provided
    (an iterable of objects), the ray pierces through those objects. The ray
    repeats until it hits a permitted object or runs out of iterations.

    Returns `(result, location, normal, face_index, obj, matrix)`. On miss,
    returns `(False, None, None, None, None, None)`.
    """
    region = context.region
    rv3d = context.space_data.region_3d
    if rv3d is None:
        return (False, None, None, None, None, None)

    view_vector = region_2d_to_vector_3d(region, rv3d, mouse_coord)
    ray_origin = region_2d_to_origin_3d(region, rv3d, mouse_coord)
    depsgraph = context.evaluated_depsgraph_get()
    allowed = set(restrict_to) if restrict_to is not None else None
    blocked = set(exclude) if exclude is not None else None
    view_vec_norm = view_vector.normalized()

    current_origin = ray_origin
    for _ in range(max_iterations):
        result, location, normal, face_index, obj, matrix = context.scene.ray_cast(
            depsgraph, current_origin, view_vector)
        if not result:
            break
        permitted = (allowed is None or (obj is not None and obj in allowed))
        if blocked is not None and obj is not None and obj in blocked:
            permitted = False
        if permitted:
            return (True, location, normal, face_index, obj, matrix)
        if location is None:
            break
        current_origin = location + view_vec_norm * RAYCAST_OFFSET_DISTANCE

    return (False, None, None, None, None, None)


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

def closest_snap_point(context, snap_points, obj_matrix, mouse_coord,
                       mouse_pos_world, *,
                       screen_threshold_px: float = SNAP_THRESHOLD_PX,
                       screen_weight: float = 0.7):
    """Find the snap point closest to mouse using weighted screen + world
    distance. View-frustum aware: points off-screen fall back to pure world
    scoring.

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
    rv3d = context.space_data.region_3d
    if rv3d is None:
        return _closest_snap_point_world(snap_points, obj_matrix, mouse_pos_world)

    obj_scale = obj_matrix.to_scale()
    max_scale = max(obj_scale.x, obj_scale.y, obj_scale.z)
    world_threshold = max(0.1, min(max_scale * 0.02, 10.0))

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
    """Pure-world fallback when screen projection is unavailable."""
    if not snap_points:
        return None
    obj_scale = obj_matrix.to_scale()
    max_scale = max(obj_scale.x, obj_scale.y, obj_scale.z)
    threshold = max(0.1, min(0.5 * max_scale, 50.0))

    closest = None
    closest_dist = float("inf")
    for kind, point_local in snap_points:
        point_world = obj_matrix @ point_local
        d = (point_world - mouse_pos_world).length
        if d < closest_dist:
            closest_dist = d
            closest = (kind, point_local, point_world)

    return closest if closest_dist < threshold else None


# --- Closest edge in a face --------------------------------------------

def closest_face_edge(context, face, obj_matrix, mouse_coord):
    """Find the face edge whose screen-projected segment is nearest to the
    mouse. Returns the edge's index within `face.edges` (0 on failure).
    """
    if not face or not face.edges:
        return 0

    region = context.region
    rv3d = context.space_data.region_3d
    if rv3d is None:
        return 0

    mouse_v = Vector(mouse_coord)
    closest_idx = 0
    closest_dist = float("inf")

    for i, edge in enumerate(face.edges):
        v1, v2 = edge.verts
        v1_w = obj_matrix @ v1.co
        v2_w = obj_matrix @ v2.co
        s1 = location_3d_to_region_2d(region, rv3d, v1_w)
        s2 = location_3d_to_region_2d(region, rv3d, v2_w)
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

    return closest_idx


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
