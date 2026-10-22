"""Pure math/bookkeeping for Instance Collection Edit In Place (no bpy)."""
import os
from collections import namedtuple
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


OwnedRow = namedtuple("OwnedRow", "index id_type source_name local_name")


def merge_plan(owned_rows, tagged, untagged_added, existing, users_outside,
               update_shared):
    """Plan a linked write-back merge as sorted ``(id_type, name)`` lists."""
    replaced, added, kept, shared = [], [], [], []
    for row in owned_rows:
        key = (row.id_type, row.source_name)
        if row.index not in tagged:
            continue
        if key not in existing:
            added.append(key)
            continue
        is_shared = key in users_outside
        if is_shared:
            shared.append(key)
        if is_shared and key not in update_shared:
            kept.append(key)
        else:
            replaced.append(key)
    added.extend(untagged_added)
    return {"replaced": sorted(replaced), "added": sorted(added),
            "kept": sorted(kept), "shared": sorted(shared),
            "unlinked": [], "deleted": [], "discarded": []}


PLAN_KEYS = ("replaced", "added", "kept", "unlinked", "deleted", "discarded")


def plans_match(a, b):
    """Same sets of ``(id_type, name)`` per plan list (JSON lists accepted)."""
    return all({tuple(x) for x in a[k]} == {tuple(x) for x in b[k]} for k in PLAN_KEYS)


def source_changed(recorded, current):
    return abs(recorded[0] - current[0]) > 1e-3 or recorded[1] != current[1]


CommitPaths = namedtuple("CommitPaths", "temp_blend temp_json result_json backup sidecar lock")


def backup_paths(source_path):
    """``(backup, sidecar)`` of a source: ``<source>.blend.iops_bak`` (no
    ``.blend`` extension, so asset libraries and master-file detection never
    index it) and ``<source>.blend.iops_bak.json``."""
    return source_path + ".iops_bak", source_path + ".iops_bak.json"


def lock_path(source_path):
    """``<source>.blend.iops_lock``: one Commit at a time per source."""
    return source_path + ".iops_lock"


def commit_temp_paths(source_path, run_id):
    """Every file one Commit run uses next to the source. ``run_id`` (a short
    uuid hex) keeps two runs on one source from sharing temp files:
    ``<stem>.iops_commit-<run_id>.blend`` / ``.json`` / ``.result.json``."""
    if not run_id or not all(ch.isalnum() for ch in run_id):
        raise ValueError("run_id must be a non-empty alphanumeric string: %r" % (run_id,))
    folder, base = os.path.split(source_path)
    stem = os.path.join(folder, os.path.splitext(base)[0] + ".iops_commit-" + run_id)
    backup, sidecar = backup_paths(source_path)
    return CommitPaths(stem + ".blend", stem + ".json", stem + ".result.json",
                       backup, sidecar, lock_path(source_path))


def newer_blender(source_version, running_version):
    """Whether a file saved by ``source_version`` comes from a newer Blender
    than ``running_version`` (major/minor compared, the patch / file
    subversion ignored). Saving such a file would silently down-version it."""
    if not source_version or not running_version:
        return False
    return tuple(int(v) for v in source_version[:2]) > tuple(int(v) for v in running_version[:2])


def _keyset(plan, name):
    return {tuple(x) for x in plan.get(name) or ()}


def ticked_plan_problem(confirmed, ticked, update_shared):
    """Why a plan computed with ``update_shared`` ticked is not the confirmed
    dry run (computed with nothing ticked) plus the ticks, or None.

    Ticking moves shared IDs (and the dependencies they pull) from ``kept``
    to ``replaced`` and can only rescue ``discarded`` IDs into ``added``;
    the set of shared IDs never changes. Membership lists (``unlinked`` /
    ``deleted``) may change with a ticked child collection and are not
    compared."""
    if _keyset(confirmed, "shared") != _keyset(ticked, "shared"):
        return "the shared datablocks changed"
    kept_c, kept_t = _keyset(confirmed, "kept"), _keyset(ticked, "kept")
    repl_c, repl_t = _keyset(confirmed, "replaced"), _keyset(ticked, "replaced")
    if not kept_t <= kept_c or not repl_c <= repl_t or kept_c - kept_t != repl_t - repl_c:
        return "replaced/kept changed beyond the ticked datablocks"
    missing = {tuple(k) for k in update_shared} - repl_t
    if missing:
        return "ticked datablocks not replaced: " + ", ".join(sorted(n for _t, n in missing))
    disc_c, disc_t = _keyset(confirmed, "discarded"), _keyset(ticked, "discarded")
    add_c, add_t = _keyset(confirmed, "added"), _keyset(ticked, "added")
    if not disc_t <= disc_c or not add_c <= add_t or not add_t - add_c <= disc_c:
        return "added/discarded changed beyond the ticked datablocks"
    return None
