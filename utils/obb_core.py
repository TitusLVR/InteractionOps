"""Oriented bounding box for a point cloud (NumPy only, no bpy so pytest
can cover it).

Used by Visual Origin (F4) to rebuild a *local* cage for meshes whose
rotation was applied: the object's own bound_box is axis-aligned, so a
rotated box reads as a bigger, wrongly oriented cage.

Pure PCA (eigenvectors of the vertex covariance) is what people usually
reach for, but it is degenerate exactly on the common case: a rotated
cube has an isotropic covariance and its eigenvectors are arbitrary. So
PCA is only one *candidate* frame here. The others come from the
dominant face normals (area-weighted, clustered by direction): every pair
of nearly perpendicular dominant normals spans a frame. Each candidate is
scored by the volume of the box it produces and the smallest wins. For
boxy hard-surface meshes the normal frames hit the exact orientation;
for organic shapes PCA tends to win.
"""
from __future__ import annotations

from collections import namedtuple

import numpy as np

OrientedBox = namedtuple("OrientedBox", "axes mins maxs")
"""`axes` is a 3x3 array whose *columns* are the unit box axes (world
space, right-handed). `mins`/`maxs` are the extents along those axes, so
a corner in world space is `axes @ corner_local`."""

MAX_NORMALS = 8
PERP_TOL = 0.1        # |dot| below this counts as perpendicular
SAME_DIR_TOL = 0.99   # |dot| above this merges two normals into one bin


class DegenerateCloud(ValueError):
    """Fewer than two distinct points: no box to fit."""


def _unit(v):
    n = np.linalg.norm(v)
    if n < 1e-12:
        return None
    return v / n


def _frame_from_two(a, b):
    """Right-handed orthonormal 3x3 (columns) with x=a exact, y from b."""
    x = _unit(a)
    if x is None:
        return None
    y = b - np.dot(b, x) * x
    y = _unit(y)
    if y is None:
        return None
    z = np.cross(x, y)
    return np.stack((x, y, z), axis=1)


def _fix_handedness(axes):
    if np.linalg.det(axes) < 0:
        axes = axes.copy()
        axes[:, 2] = -axes[:, 2]
    return axes


def _canonical_signs(axes):
    """Flip columns so each axis points to the positive side of the world
    axis it is most aligned with. Pure cosmetics: makes the result stable
    between runs (eigenvector signs are arbitrary) and keeps the cage's
    local +X/+Y/+Z roughly matching world +X/+Y/+Z."""
    # 1. permute columns so column i is the axis best aligned with world i
    #    (greedy by |dot|, largest first) -- a box's axes are unordered.
    cols = [axes[:, i] for i in range(3)]
    out = [None, None, None]
    pairs = sorted(((abs(cols[c][w]), c, w) for c in range(3) for w in range(3)),
                   reverse=True)
    used_c, used_w = set(), set()
    for _, c, w in pairs:
        if c in used_c or w in used_w:
            continue
        out[w] = cols[c]
        used_c.add(c)
        used_w.add(w)
    # 2. positive side of the matching world axis for X and Y
    x = out[0] if out[0][0] >= 0 else -out[0]
    y = out[1] if out[1][1] >= 0 else -out[1]
    # 3. Z follows from right-handedness; with x~+X and y~+Y it is ~+Z.
    z = np.cross(x, y)
    return np.stack((x, y, z), axis=1)


def pca_axes(points):
    """Eigenvectors of the covariance, columns sorted by descending variance."""
    c = points - points.mean(axis=0)
    cov = c.T @ c
    w, v = np.linalg.eigh(cov)
    order = np.argsort(w)[::-1]
    return _fix_handedness(v[:, order])


def dominant_normals(normals, areas, max_count=MAX_NORMALS):
    """Cluster unit normals by direction (sign-insensitive), sum their
    areas, return the strongest directions first."""
    if normals is None or len(normals) == 0:
        return []
    normals = np.asarray(normals, dtype=float)
    areas = np.asarray(areas, dtype=float)
    bins = []  # [direction, weight]
    order = np.argsort(areas)[::-1]
    for i in order:
        n = _unit(normals[i])
        if n is None or areas[i] <= 0:
            continue
        for b in bins:
            if abs(np.dot(b[0], n)) > SAME_DIR_TOL:
                b[1] += areas[i]
                break
        else:
            bins.append([n, areas[i]])
    bins.sort(key=lambda b: -b[1])
    return [b[0] for b in bins[:max_count]]


def _extents(points, axes):
    local = points @ axes
    return local.min(axis=0), local.max(axis=0)


def _volume(mins, maxs):
    d = np.maximum(maxs - mins, 1e-9)
    return float(d[0] * d[1] * d[2])


def candidate_frames(points, normals=None, areas=None):
    frames = [pca_axes(points)]
    doms = dominant_normals(normals, areas)
    pca_major = frames[0][:, 0]
    for i, a in enumerate(doms):
        paired = False
        for b in doms[i + 1:]:
            if abs(np.dot(a, b)) < PERP_TOL:
                f = _frame_from_two(a, b)
                if f is not None:
                    frames.append(f)
                    paired = True
        if not paired:
            # single dominant plane (e.g. a slab): spin the box around it
            # using the PCA major axis as the in-plane direction.
            f = _frame_from_two(a, pca_major)
            if f is None:
                f = _frame_from_two(a, np.roll(a, 1))
            if f is not None:
                frames.append(f)
    return frames


def oriented_bbox(points, normals=None, areas=None):
    """Fit an oriented box to `points` (Nx3). `normals`/`areas` (Mx3, M)
    are optional face data that supply extra candidate frames.

    Returns OrientedBox(axes, mins, maxs); raises DegenerateCloud when
    the cloud has no extent."""
    points = np.asarray(points, dtype=float).reshape(-1, 3)
    if len(points) < 2 or np.allclose(points, points[0]):
        raise DegenerateCloud("need at least two distinct points")
    best = None
    for axes in candidate_frames(points, normals, areas):
        mins, maxs = _extents(points, axes)
        vol = _volume(mins, maxs)
        if best is None or vol < best[0] * (1 - 1e-6):
            best = (vol, axes)
    axes = _canonical_signs(best[1])
    mins, maxs = _extents(points, axes)
    return OrientedBox(axes, mins, maxs)


def box_corners_local(mins, maxs):
    """8 corners in box-local space, Blender bound_box order
    (x-,y-,z-), (x-,y-,z+), (x-,y+,z+), (x-,y+,z-),
    (x+,y-,z-), (x+,y-,z+), (x+,y+,z+), (x+,y+,z-)."""
    x0, y0, z0 = mins
    x1, y1, z1 = maxs
    return [
        (x0, y0, z0), (x0, y0, z1), (x0, y1, z1), (x0, y1, z0),
        (x1, y0, z0), (x1, y0, z1), (x1, y1, z1), (x1, y1, z0),
    ]
