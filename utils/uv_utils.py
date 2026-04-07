import math
import random
from mathutils import Vector, Matrix


def get_uv_layer(bm):
    """Get the active UV layer, creating one if needed."""
    return bm.loops.layers.uv.verify()


def get_selected_face_islands(bm, uv_layer):
    """
    Detect complete UV islands that contain at least one selected face.
    Walks UV connectivity across ALL mesh faces so that partially-selected
    islands are expanded to their full extent.
    Returns list of islands (each a set of face indices) and a UV-to-faces map.
    """
    selected_set = set(f.index for f in bm.faces if f.select)
    if not selected_set:
        return [], {}

    # Build UV connectivity across the entire mesh.
    # Key = (vert_index, rounded_u, rounded_v) identifies a UV "weld point".
    uv_to_faces = {}
    for f in bm.faces:
        for loop in f.loops:
            uv = loop[uv_layer].uv
            key = (loop.vert.index, round(uv.x, 6), round(uv.y, 6))
            if key not in uv_to_faces:
                uv_to_faces[key] = set()
            uv_to_faces[key].add(f.index)

    face_to_neighbors = {}
    for f in bm.faces:
        neighbors = set()
        for loop in f.loops:
            uv = loop[uv_layer].uv
            key = (loop.vert.index, round(uv.x, 6), round(uv.y, 6))
            neighbors |= uv_to_faces.get(key, set())
        neighbors.discard(f.index)
        face_to_neighbors[f.index] = neighbors

    # Flood-fill complete islands, keep only those touching a selected face.
    visited = set()
    islands = []

    for seed_idx in selected_set:
        if seed_idx in visited:
            continue
        island = set()
        stack = [seed_idx]
        while stack:
            fi = stack.pop()
            if fi in visited:
                continue
            visited.add(fi)
            island.add(fi)
            for ni in face_to_neighbors.get(fi, set()):
                if ni not in visited:
                    stack.append(ni)
        islands.append(island)

    return islands, uv_to_faces


def get_island_uv_data(bm, island_face_indices, uv_layer):
    """
    Get UV data for an island: edges, points, and bounding box.
    Returns dict with:
      - 'edges': list of (uv1, uv2) tuples
      - 'points': list of unique UV positions
      - 'point_loops': dict mapping rounded UV tuple -> list of loops
      - 'bbox_min', 'bbox_max': bounding box corners
      - 'center': center of bounding box
      - 'loops': all loops in the island
    """
    face_lookup = {f.index: f for f in bm.faces}
    edges = []
    point_loops = {}
    all_loops = []

    for fi in island_face_indices:
        f = face_lookup.get(fi)
        if not f:
            continue
        loops_list = list(f.loops)
        for i, loop in enumerate(loops_list):
            all_loops.append(loop)
            uv = loop[uv_layer].uv.copy()
            next_loop = loops_list[(i + 1) % len(loops_list)]
            uv_next = next_loop[uv_layer].uv.copy()
            edges.append((uv, uv_next))

            key = (round(uv.x, 5), round(uv.y, 5))
            if key not in point_loops:
                point_loops[key] = []
            point_loops[key].append(loop)

    points = [Vector((k[0], k[1])) for k in point_loops.keys()]

    if not points:
        return None

    min_u = min(p.x for p in points)
    max_u = max(p.x for p in points)
    min_v = min(p.y for p in points)
    max_v = max(p.y for p in points)

    return {
        'edges': edges,
        'points': points,
        'point_loops': point_loops,
        'bbox_min': Vector((min_u, min_v)),
        'bbox_max': Vector((max_u, max_v)),
        'center': Vector(((min_u + max_u) * 0.5, (min_v + max_v) * 0.5)),
        'loops': all_loops,
    }


def get_island_3d_data(bm, island_face_indices, uv_layer, world_matrix):
    """
    Collect 3D geometry for an island: edge positions, vertex positions,
    center, average normal -- everything needed to draw ON the mesh.
    Returns dict with:
      - 'edges_3d': list of (world_pos_a, world_pos_b) per face edge
      - 'edge_uv_pairs': list of ((uv_a, uv_b), (pos3d_a, pos3d_b))
      - 'verts_3d': dict mapping UV key -> world-space 3D position
      - 'center_3d': average world-space position of island vertices
      - 'normal_avg': average face normal (world space, normalized)
      - 'face_tris': list of (v0, v1, v2) world-space for face filling
      - 'face_colors': per-triangle island index (for batching)
    """
    face_lookup = {f.index: f for f in bm.faces}
    edges_3d = []
    edge_uv_pairs = []
    verts_3d = {}
    normals = []
    all_positions = []
    face_tris = []
    uv_tris = []

    normal_mat = world_matrix.to_3x3().inverted().transposed()

    for fi in island_face_indices:
        f = face_lookup.get(fi)
        if not f:
            continue

        fn = (normal_mat @ f.normal).normalized()
        normals.append(fn)

        fverts_world = [world_matrix @ v.co for v in f.verts]
        loops_list = list(f.loops)
        uv_coords = [(lp[uv_layer].uv.x, lp[uv_layer].uv.y)
                      for lp in loops_list]

        for i in range(1, len(fverts_world) - 1):
            face_tris.append((fverts_world[0], fverts_world[i],
                              fverts_world[i + 1]))
            uv_tris.append(((uv_coords[0], uv_coords[i], uv_coords[i + 1]),
                            (fverts_world[0], fverts_world[i],
                             fverts_world[i + 1])))

        for i, loop in enumerate(loops_list):
            uv = loop[uv_layer].uv.copy()
            next_loop = loops_list[(i + 1) % len(loops_list)]
            uv_next = next_loop[uv_layer].uv.copy()

            pos_a = world_matrix @ loop.vert.co
            pos_b = world_matrix @ next_loop.vert.co

            edges_3d.append((pos_a, pos_b))
            edge_uv_pairs.append(((uv, uv_next), (pos_a, pos_b)))

            uv_key = (round(uv.x, 5), round(uv.y, 5))
            if uv_key not in verts_3d:
                verts_3d[uv_key] = pos_a.copy()
                all_positions.append(pos_a)

    if not all_positions:
        return None

    center_3d = sum(all_positions, Vector((0, 0, 0))) / len(all_positions)
    normal_avg = sum(normals, Vector((0, 0, 0)))
    if normal_avg.length > 1e-8:
        normal_avg.normalize()
    else:
        normal_avg = Vector((0, 0, 1))

    return {
        'edges_3d': edges_3d,
        'edge_uv_pairs': edge_uv_pairs,
        'verts_3d': verts_3d,
        'center_3d': center_3d,
        'normal_avg': normal_avg,
        'face_tris': face_tris,
        'uv_tris': uv_tris,
    }


def cache_all_uvs(bm, uv_layer):
    """Cache all UV coordinates for undo. Returns dict: loop -> uv.copy()"""
    cache = {}
    for f in bm.faces:
        for loop in f.loops:
            cache[loop] = loop[uv_layer].uv.copy()
    return cache


def restore_uvs(cache, uv_layer):
    """Restore UV coordinates from cache."""
    for loop, uv in cache.items():
        loop[uv_layer].uv = uv


def move_island_uv(loops, uv_layer, offset):
    """Move all UV points of an island by offset vector."""
    moved = set()
    for loop in loops:
        lid = id(loop)
        if lid in moved:
            continue
        moved.add(lid)
        loop[uv_layer].uv += offset


def rotate_island_uv(loops, uv_layer, center, angle):
    """Rotate all UV points of an island around center by angle (radians)."""
    rot = Matrix.Rotation(angle, 2)
    moved = set()
    for loop in loops:
        lid = id(loop)
        if lid in moved:
            continue
        moved.add(lid)
        uv = loop[uv_layer].uv
        rel = uv - center
        new_rel = rot @ rel
        loop[uv_layer].uv = center + new_rel


def scale_island_uv(loops, uv_layer, center, scale_x, scale_y):
    """Scale all UV points of an island around center with independent X/Y factors."""
    moved = set()
    for loop in loops:
        lid = id(loop)
        if lid in moved:
            continue
        moved.add(lid)
        uv = loop[uv_layer].uv
        rel = uv - center
        loop[uv_layer].uv = center + Vector((rel.x * scale_x, rel.y * scale_y))


def flip_island_uv(loops, uv_layer, center, axis='H'):
    """Flip island UVs. axis='H' for horizontal (mirror X), 'V' for vertical (mirror Y)."""
    if axis == 'H':
        scale_island_uv(loops, uv_layer, center, -1.0, 1.0)
    else:
        scale_island_uv(loops, uv_layer, center, 1.0, -1.0)


def align_island_to_edge_uv(loops, uv_layer, edge_uv_a, edge_uv_b, center):
    """
    Rotate an island so the edge defined by edge_uv_a->edge_uv_b becomes
    axis-aligned (horizontal or vertical, whichever is closer).
    """
    edge_dir = edge_uv_b - edge_uv_a
    if edge_dir.length < 1e-8:
        return 0.0

    angle = math.atan2(edge_dir.y, edge_dir.x)
    snap_angles = [0, math.pi / 2, math.pi, -math.pi / 2]
    best = min(snap_angles, key=lambda a: abs(_angle_diff(angle, a)))
    rotation = best - angle

    rotate_island_uv(loops, uv_layer, center, rotation)
    return rotation


def _angle_diff(a, b):
    """Signed shortest angular difference."""
    diff = (b - a + math.pi) % (2 * math.pi) - math.pi
    return diff


def align_islands_bbox(islands_data, uv_layer, alignment='TOP'):
    """
    Align multiple islands' bounding boxes.
    alignment: 'TOP', 'BOTTOM', 'LEFT', 'RIGHT', 'CENTER_H', 'CENTER_V'
    """
    if len(islands_data) < 2:
        return

    ref = islands_data[0]
    for idata in islands_data[1:]:
        offset = Vector((0.0, 0.0))
        if alignment == 'TOP':
            offset.y = ref['bbox_max'].y - idata['bbox_max'].y
        elif alignment == 'BOTTOM':
            offset.y = ref['bbox_min'].y - idata['bbox_min'].y
        elif alignment == 'LEFT':
            offset.x = ref['bbox_min'].x - idata['bbox_min'].x
        elif alignment == 'RIGHT':
            offset.x = ref['bbox_max'].x - idata['bbox_max'].x
        elif alignment == 'CENTER_H':
            offset.x = ref['center'].x - idata['center'].x
        elif alignment == 'CENTER_V':
            offset.y = ref['center'].y - idata['center'].y

        move_island_uv(idata['loops'], uv_layer, offset)


def compute_texel_density(bm, island_face_indices, uv_layer):
    """
    Compute texel density ratio for an island: UV area / 3D area.
    Higher = more UV space per unit of 3D surface.
    """
    face_lookup = {f.index: f for f in bm.faces}
    uv_area = 0.0
    geo_area = 0.0

    for fi in island_face_indices:
        f = face_lookup.get(fi)
        if not f:
            continue
        geo_area += f.calc_area()

        loops_list = list(f.loops)
        uvs = [lp[uv_layer].uv for lp in loops_list]
        for i in range(1, len(uvs) - 1):
            a = uvs[0]
            b = uvs[i]
            c = uvs[i + 1]
            uv_area += abs((b.x - a.x) * (c.y - a.y) - (c.x - a.x) * (b.y - a.y)) * 0.5

    if geo_area < 1e-10:
        return 0.0
    return uv_area / geo_area


def match_texel_density(bm, ref_island_indices, target_island_indices, uv_layer):
    """Scale target island to match reference island's texel density."""
    ref_density = compute_texel_density(bm, ref_island_indices, uv_layer)
    if ref_density < 1e-10:
        return

    target_density = compute_texel_density(bm, target_island_indices, uv_layer)
    if target_density < 1e-10:
        return

    ratio = math.sqrt(ref_density / target_density)
    target_data = get_island_uv_data(bm, target_island_indices, uv_layer)
    if target_data:
        scale_island_uv(
            target_data['loops'], uv_layer,
            target_data['center'], ratio, ratio
        )


def match_island_dimensions(target_loops, uv_layer, target_bbox_min,
                            target_bbox_max, ref_bbox_min, ref_bbox_max):
    """Scale and move *target* island so its bounding box matches *ref*."""
    tw = target_bbox_max.x - target_bbox_min.x
    th = target_bbox_max.y - target_bbox_min.y
    rw = ref_bbox_max.x - ref_bbox_min.x
    rh = ref_bbox_max.y - ref_bbox_min.y

    sx = rw / tw if abs(tw) > 1e-10 else 1.0
    sy = rh / th if abs(th) > 1e-10 else 1.0

    tc = Vector(((target_bbox_min.x + target_bbox_max.x) * 0.5,
                 (target_bbox_min.y + target_bbox_max.y) * 0.5))
    scale_island_uv(target_loops, uv_layer, tc, sx, sy)

    rc = Vector(((ref_bbox_min.x + ref_bbox_max.x) * 0.5,
                 (ref_bbox_min.y + ref_bbox_max.y) * 0.5))
    move_island_uv(target_loops, uv_layer, rc - tc)


def randomize_island_uv(loops, uv_layer, bbox_min, bbox_max, mode='UV'):
    """Randomize island position so it stays within the 0-1 tile.
    mode: 'UV' = both axes, 'U' = U only, 'V' = V only."""
    w = bbox_max.x - bbox_min.x
    h = bbox_max.y - bbox_min.y
    if mode in ('UV', 'U'):
        du = random.uniform(0, max(1.0 - w, 0)) - bbox_min.x
    else:
        du = 0.0
    if mode in ('UV', 'V'):
        dv = random.uniform(0, max(1.0 - h, 0)) - bbox_min.y
    else:
        dv = 0.0
    move_island_uv(loops, uv_layer, Vector((du, dv)))


def straighten_uv_edge_loop(loops_chain, uv_layer):
    """
    Straighten a chain of UV loops: distribute points evenly
    along the line between the first and last point.
    loops_chain: ordered list of loops forming an edge chain.
    """
    if len(loops_chain) < 3:
        return

    start = loops_chain[0][uv_layer].uv.copy()
    end = loops_chain[-1][uv_layer].uv.copy()
    total = len(loops_chain) - 1

    for i, loop in enumerate(loops_chain):
        t = i / total
        loop[uv_layer].uv = start.lerp(end, t)
