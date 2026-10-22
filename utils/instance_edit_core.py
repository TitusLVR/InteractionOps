"""Pure math/bookkeeping for Instance Collection Edit In Place (no bpy)."""
import numpy as np

_SEP = "\x1f"


def edit_frame(instance_matrix, instance_offset):
    """World frame of the edited collection content: M @ T(-offset)."""
    m = np.asarray(instance_matrix, dtype=float)
    t = np.eye(4)
    t[:3, 3] = -np.asarray(instance_offset, dtype=float)
    return m @ t


def is_similarity(frame, tol=1e-5):
    """True when the 3x3 part of ``frame`` is rotation x uniform scale
    (optionally mirrored): columns pairwise orthogonal and of equal length,
    both within ``tol`` relative to the largest column, and ``|det| >= 1e-9``.
    A sheared or non-uniformly scaled frame turns rotated objects into
    matrices ``matrix_world`` cannot represent; a zero-scale one has no
    inverse."""
    m = np.asarray(frame, dtype=float)[:3, :3]
    if not np.all(np.isfinite(m)):
        return False
    det = np.linalg.det(m)
    if abs(det) < 1e-9:
        return False
    cols = [m[:, i] for i in range(3)]
    lengths = [float(np.linalg.norm(c)) for c in cols]
    ref = max(lengths)
    if any(abs(n - ref) > tol * ref for n in lengths):
        return False
    for i in range(3):
        for j in range(i + 1, 3):
            if abs(float(np.dot(cols[i], cols[j]))) > tol * ref * ref:
                return False
    return True


def moved(frame, world):
    return np.asarray(frame, dtype=float) @ np.asarray(world, dtype=float)


def unmoved(frame, world):
    return np.linalg.inv(np.asarray(frame, dtype=float)) @ np.asarray(world, dtype=float)


def to_flat(m):
    return [float(v) for v in np.asarray(m, dtype=float).reshape(16)]


def from_flat(flat):
    return np.asarray(flat, dtype=float).reshape(4, 4)


def split_roots(names, parent_of):
    """Split names into (roots, children). A root has no ancestor, through
    any parent chain (``parent_of`` may hold names outside ``names``), inside
    names; a child follows such an ancestor and must not be moved itself."""
    inside = set(names)
    roots, children = [], []
    for n in names:
        seen = {n}
        p = parent_of.get(n)
        while p is not None and p not in seen and p not in inside:
            seen.add(p)
            p = parent_of.get(p)
        # p in seen: cycle guard (a chain looping back to n is not a parent).
        (children if p is not None and p in inside and p not in seen else roots).append(n)
    return roots, children


def layer_path(names):
    return _SEP.join(names)


def split_layer_path(path):
    return path.split(_SEP)


def plan_restore(rows, alive):
    """Return (rows whose name is alive, names of rows that are missing)."""
    to_restore, missing = [], []
    for r in rows:
        if r.name in alive:
            to_restore.append(r)
        else:
            missing.append(r.name)
    return to_restore, missing


def warnings(roots_info):
    lines = []
    for info in roots_info:
        if info["has_transform_anim"]:
            lines.append(f"{info['name']}: animated/driven transform")
        if info["has_transform_constraint"]:
            lines.append(f"{info['name']}: transform constraint")
    if lines:
        lines.insert(0, "Do not edit these objects or change the frame while editing:")
    return lines
