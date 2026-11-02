"""Pure logic for Cursor Bisect: delimiter island walk and cut-axis cycling.

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
