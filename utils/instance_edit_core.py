"""Pure math/bookkeeping for Instance Collection Edit In Place (no bpy)."""
import numpy as np

_SEP = "\x1f"


def edit_frame(instance_matrix, instance_offset):
    """World frame of the edited collection content: M @ T(-offset)."""
    m = np.asarray(instance_matrix, dtype=float)
    t = np.eye(4)
    t[:3, 3] = -np.asarray(instance_offset, dtype=float)
    return m @ t


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
