"""Pure logic for Cursor Bisect: delimiter island walk, cut-axis cycling and
the Selection Bounds snap source (oriented box, side divisions, inset).

No bpy here. The operator feeds `walk_island` with closures over the
BMesh; the walk itself only sees opaque face / edge ids, so it is
pytest-covered in tests/test_cursor_bisect_core.py.
"""
from __future__ import annotations

import math
from collections import deque
from typing import Callable, Hashable, Iterable

DELIMIT_TYPES: tuple[str, ...] = ('ISLAND', 'SEAM', 'SHARP', 'UV', 'MATERIAL', 'NORMAL')
DELIMIT_LABELS: dict[str, str] = {
    'ISLAND': 'Mesh Island',
    'SEAM': 'Seam',
    'SHARP': 'Sharp',
    'UV': 'UV Island',
    'MATERIAL': 'Material',
    'NORMAL': 'Normal',
}

AXES: tuple[str, ...] = ('X', 'Y', 'Z')
_AXIS_VECTORS = {
    'X': (1.0, 0.0, 0.0),
    'Y': (0.0, 1.0, 0.0),
    'Z': (0.0, 0.0, 1.0),
}


def next_delimit_type(current: str) -> str:
    """Next delimiter type in `DELIMIT_TYPES` order, wrapping around."""
    try:
        i = DELIMIT_TYPES.index(current)
    except ValueError:
        return DELIMIT_TYPES[0]
    return DELIMIT_TYPES[(i + 1) % len(DELIMIT_TYPES)]


def next_axis(axis: str) -> str:
    """Cut normal axis cycle: X -> Y -> Z -> X."""
    try:
        i = AXES.index(axis)
    except ValueError:
        return AXES[0]
    return AXES[(i + 1) % len(AXES)]


def axis_vector(axis: str) -> tuple[float, float, float]:
    """Unit vector of the given cursor axis."""
    return _AXIS_VECTORS[axis]


def normals_split(n_a, n_b, angle_deg: float) -> bool:
    """True when the angle between unit normals `n_a` and `n_b` exceeds
    `angle_deg`. The dot product is clamped so float noise never feeds
    `acos` a value outside [-1, 1]."""
    d = n_a[0] * n_b[0] + n_a[1] * n_b[1] + n_a[2] * n_b[2]
    d = max(-1.0, min(1.0, d))
    return math.degrees(math.acos(d)) > angle_deg


def walk_island(start: Hashable,
                in_candidates: Callable[[Hashable], bool],
                neighbors: Callable[[Hashable], Iterable[tuple[Hashable, Hashable]]],
                is_boundary: Callable[[Hashable, Hashable, Hashable], bool]) -> set:
    """Faces reachable from `start` without crossing a boundary edge.

    `neighbors(face)` yields `(edge, other_face)` pairs; `is_boundary(edge,
    face, other_face)` is evaluated per pair, so a non-manifold edge can be
    open between some face pairs and closed between others. Only faces for
    which `in_candidates` is True are entered; a `start` outside the
    candidates gives an empty set. Iterative BFS, no recursion.
    """
    if not in_candidates(start):
        return set()
    visited = {start}
    queue = deque([start])
    while queue:
        face = queue.popleft()
        for edge, other in neighbors(face):
            if other in visited:
                continue
            if is_boundary(edge, face, other):
                continue
            if not in_candidates(other):
                continue
            visited.add(other)
            queue.append(other)
    return visited


def cut_set_for_axis(faces: set, normal_axis: str, hovered) -> set:
    """In Z the cut plane *is* the hovered face's plane, so that face is the
    blade, not a target: drop it from the cut set. Other axes: unchanged."""
    if normal_axis != 'Z':
        return faces
    return {f for f in faces if f != hovered}


def cached_island(cache, key, face):
    """Return the cached island set when `cache` was built under the same
    `key` (object, delimiter type, angle, mesh version) and `face` belongs
    to it. Every boundary test is symmetric, so an island is the same set
    from any of its faces; hovering across it never needs a new walk."""
    if cache is None:
        return None
    cached_key, faces = cache
    if cached_key != key or face not in faces:
        return None
    return set(faces)


# --- Snap source: hovered face edge or the cut set's oriented bounds --------------

SNAP_SOURCES: tuple[str, ...] = ('EDGE', 'BOUNDS')
SNAP_SOURCE_LABELS: dict[str, str] = {
    'EDGE': 'Face Edge',
    'BOUNDS': 'Selection Bounds',
}

BOUNDS_EPSILON = 1e-6


def next_snap_source(current: str) -> str:
    """Next snap source in `SNAP_SOURCES` order, wrapping around."""
    try:
        i = SNAP_SOURCES.index(current)
    except ValueError:
        return SNAP_SOURCES[0]
    return SNAP_SOURCES[(i + 1) % len(SNAP_SOURCES)]


def _dot(a, b) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def oriented_extents(points, axes):
    """Min / max of `points` projected on each of the three `axes` (unit
    world vectors of the frame). Returns `(lo, hi)`, two 3-tuples of
    frame coordinates, or None when there are no points."""
    lo = [math.inf, math.inf, math.inf]
    hi = [-math.inf, -math.inf, -math.inf]
    any_point = False
    for p in points:
        any_point = True
        for i in range(3):
            d = _dot(p, axes[i])
            if d < lo[i]:
                lo[i] = d
            if d > hi[i]:
                hi[i] = d
    if not any_point:
        return None
    return tuple(lo), tuple(hi)


def box_point(coords, axes) -> tuple[float, float, float]:
    """World point of frame coordinates `coords` (one value per axis)."""
    return tuple(coords[0] * axes[0][k] + coords[1] * axes[1][k] + coords[2] * axes[2][k]
                 for k in range(3))


def box_edges(lo, hi, axes, eps: float = BOUNDS_EPSILON) -> dict:
    """Edges of the oriented box `lo`..`hi`, grouped by the axis they run
    along: `{axis_index: [(start, end), ...]}` in world space, each edge
    starting at the `lo` end. An axis with zero extent has no edges, and a
    zero-thickness axis contributes one level instead of two, so a flat box
    (rectangle) yields no zero-length or duplicate edges."""
    flat = [hi[i] - lo[i] <= eps for i in range(3)]
    edges = {}
    for a in range(3):
        if flat[a]:
            edges[a] = []
            continue
        b, c = (a + 1) % 3, (a + 2) % 3
        levels_b = (lo[b],) if flat[b] else (lo[b], hi[b])
        levels_c = (lo[c],) if flat[c] else (lo[c], hi[c])
        found = []
        for vb in levels_b:
            for vc in levels_c:
                start = [0.0, 0.0, 0.0]
                end = [0.0, 0.0, 0.0]
                start[a], end[a] = lo[a], hi[a]
                start[b] = end[b] = vb
                start[c] = end[c] = vc
                found.append((box_point(start, axes), box_point(end, axes)))
        edges[a] = found
    return edges


def box_wire(lo, hi, axes, eps: float = BOUNDS_EPSILON) -> list:
    """Every edge of the oriented box as `(start, end)` world pairs, without
    zero-length or duplicate edges (see `box_edges`)."""
    edges = box_edges(lo, hi, axes, eps)
    return [e for a in range(3) for e in edges[a]]


def bounds_division_count(subdivisions: int, has_inset: bool) -> int:
    """Interior divisions on a bounds side. Mirrors the Fill Cut rule: at
    least one (the midpoint) unless inset points already give positions."""
    return subdivisions if has_inset else max(1, subdivisions)


def bounds_division_offsets(length: float, count: int,
                            eps: float = BOUNDS_EPSILON) -> list[float]:
    """`count` equally spaced interior offsets from the `lo` end of a side of
    `length` (t = i / (count + 1)). Empty for a zero-length side."""
    if length <= eps or count <= 0:
        return []
    return [length * i / (count + 1) for i in range(1, count + 1)]


def bounds_inset_offsets(length: float, distance: float,
                         eps: float = BOUNDS_EPSILON) -> list[float]:
    """Offsets `distance` in from both ends of a side of `length`. Empty when
    the distance is not positive or reaches the side length; one offset when
    both ends give the same point (distance = half the side)."""
    if length <= eps or distance <= 0.0 or distance >= length:
        return []
    offsets = [distance]
    if abs((length - distance) - distance) > eps:
        offsets.append(length - distance)
    return offsets


def bounds_layout(lo, hi, axes, axis_index: int, subdivisions: int,
                  inset_distance: float, inset_on: bool,
                  eps: float = BOUNDS_EPSILON) -> dict:
    """Everything the Selection Bounds snap source needs for one frame.

    `divisions` / `insets`: world points on every box edge parallel to the
    cut axis `axis_index`; `positions`: one world point per division and
    inset offset (taken on the first such edge; only their projection on
    the cut axis matters to a cut plane); `wire`: the box edges; `length`:
    the side length along the cut axis."""
    a = axis_index
    length = hi[a] - lo[a]
    along_cut = box_edges(lo, hi, axes, eps)[a]
    insets = bounds_inset_offsets(length, inset_distance, eps) if inset_on else []
    divs = bounds_division_offsets(length, bounds_division_count(subdivisions, bool(insets)), eps)
    axis = axes[a]

    def along(edge, offset):
        s = edge[0]
        return (s[0] + axis[0] * offset, s[1] + axis[1] * offset, s[2] + axis[2] * offset)

    return {
        'lo': tuple(lo),
        'hi': tuple(hi),
        'axes': tuple(tuple(ax) for ax in axes),
        'axis_index': a,
        'length': length,
        'wire': box_wire(lo, hi, axes, eps),
        'divisions': [along(e, o) for e in along_cut for o in divs],
        'insets': [along(e, o) for e in along_cut for o in insets],
        'positions': [along(along_cut[0], o) for o in divs + insets] if along_cut else [],
    }


def bounds_split(lo, hi, axes, axis_index: int, point) -> tuple[float, float]:
    """Side length along the cut axis and the distance from `point`
    (projected on that axis, clamped to the box) to the nearer end."""
    a = axis_index
    length = hi[a] - lo[a]
    d = _dot(point, axes[a])
    split = max(0.0, min(d - lo[a], hi[a] - d))
    return length, min(split, max(0.0, length))
