"""GPU state context manager.

`draw_scope` sets requested GPU state on enter and restores on exit. Only
params that are not None are touched, so callers don't pay for state changes
they don't need.

Note: Blender's `gpu.state` has setters but no getters for blend/depth modes.
We restore to documented defaults ('NONE' / 'LESS' / 1.0 / 1.0) which matches
the implicit baseline Blender uses outside addon draw handlers.
"""
from __future__ import annotations
from contextlib import contextmanager
import gpu


@contextmanager
def draw_scope(blend: str | None = None,
               depth: str | None = None,
               line_width: float | None = None,
               point_size: float | None = None,
               face_culling: str | None = None):
    if blend is not None:
        gpu.state.blend_set(blend)
    if depth is not None:
        gpu.state.depth_test_set(depth)
    if line_width is not None:
        gpu.state.line_width_set(line_width)
    if point_size is not None:
        gpu.state.point_size_set(point_size)
    if face_culling is not None:
        gpu.state.face_culling_set(face_culling)
    try:
        yield
    finally:
        if face_culling is not None:
            gpu.state.face_culling_set("NONE")
        if line_width is not None:
            gpu.state.line_width_set(1.0)
        if point_size is not None:
            gpu.state.point_size_set(1.0)
        if depth is not None:
            gpu.state.depth_test_set("LESS")
        if blend is not None:
            gpu.state.blend_set("NONE")
