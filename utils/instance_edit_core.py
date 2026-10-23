"""Pure math/bookkeeping for Instance Collection Edit In Place (no bpy)."""
import datetime
import hashlib
import os
import re
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


CommitPaths = namedtuple("CommitPaths", "temp_blend temp_json result_json lock")


BACKUP_EXT = ".iopsbackup"
BACKUP_SIDECAR_EXT = ".iopsbackup.json"
# The folder "Next to source" backups go into, beside the library file.
BACKUP_SUBFOLDER = ".iopsbackup"
# A copy being written: outside the point grammar (never listed as a
# point), moved into place with os.replace once complete.
BACKUP_PART_EXT = ".iopsbackup.part"

_USER_MAX = 12
_USER_BAD = re.compile(r"[^A-Za-z0-9_-]")
_HASH = re.compile(r"[0-9a-f]{8}")
_STAMP = re.compile(r"\d{6}-\d{6}")
_USER = re.compile(r"[A-Za-z0-9_-]{1,%d}" % _USER_MAX)
_EPOCH = datetime.datetime(2020, 1, 1, tzinfo=datetime.timezone.utc)


def _source_key(source_path):
    """The absolute, normalised (and on Windows case-folded) source path
    the custom-folder backup names hash."""
    return os.path.normcase(os.path.normpath(os.path.abspath(source_path)))


def source_hash(source_path):
    """8 hex of sha1(absolute normalised source path): keeps two sources
    with one stem apart in the shared custom backup folder."""
    return hashlib.sha1(_source_key(source_path).encode("utf-8")).hexdigest()[:8]


def user_tag(user):
    """``user`` as it appears in a backup name: cut to 12 characters, every
    character outside ``[A-Za-z0-9_-]`` replaced by ``_`` (never empty)."""
    return _USER_BAD.sub("_", (user or "")[:_USER_MAX]) or "unknown"


def point_name(stem, user, when_utc, path_hash=None):
    """Name (no extension) of a Commit backup point: ``<stem>.<user>.
    <yymmdd-HHMMSS>``, or ``<stem>.<hash8>.<user>.<stamp>`` in the custom
    folder (``path_hash`` = ``source_hash``). The stamp is UTC (an aware
    ``when_utc`` is converted, a naive one is taken as UTC), so names of one
    user sort by time across DST and clock changes. Callers append
    ``BACKUP_EXT`` (the copy) and ``BACKUP_SIDECAR_EXT`` (its sidecar)."""
    when = when_utc
    if when.tzinfo is not None:
        when = when.astimezone(datetime.timezone.utc)
    middle = f".{path_hash}" if path_hash else ""
    return f"{stem}{middle}.{user_tag(user)}.{when:%y%m%d-%H%M%S}"


def parse_point(name):
    """``(stem, hash_or_None, user, stamp)`` of a ``point_name`` (no
    extension), parsed from the right so stems may contain dots: the
    stamp, the user, then an optional 8-hex hash when a stem is left before
    it. None when ``name`` is not a point name. A next-to-source stem that
    itself ends in ``.<8 hex>`` reads as stem + hash here; ``backup_points``
    matches against the known stem and is never fooled by that."""
    parts = name.split(".")
    if len(parts) < 3 or not _STAMP.fullmatch(parts[-1]) or not _USER.fullmatch(parts[-2]):
        return None
    rest = parts[:-2]
    path_hash = None
    if len(rest) > 1 and _HASH.fullmatch(rest[-1]):
        path_hash = rest.pop()
    stem = ".".join(rest)
    if not stem:
        return None
    return stem, path_hash, parts[-2], parts[-1]


def point_user(point):
    """The user a point's name carries, or None."""
    parsed = parse_point(point)
    return parsed[2] if parsed else None


def _stamp_of(point):
    parts = point.rsplit(".", 1)
    return parts[-1] if len(parts) == 2 and _STAMP.fullmatch(parts[-1]) else ""


def point_stamp(point):
    """The aware UTC datetime a point's name ends with (``yymmdd-HHMMSS``,
    the year taken as 20yy), or None."""
    stamp = _stamp_of(point)
    if not stamp:
        return None
    try:
        when = datetime.datetime(2000 + int(stamp[0:2]), int(stamp[2:4]), int(stamp[4:6]),
                                 int(stamp[7:9]), int(stamp[9:11]), int(stamp[11:13]))
    except ValueError:
        return None
    return when.replace(tzinfo=datetime.timezone.utc)


def point_number(point):
    """Stable enum number of a point: seconds since 2020-01-01 UTC from its
    name (the value Blender stores for the Rollback point enum, so a point
    added or removed while the dialog is open never shifts the choice).
    0 for a name without a stamp."""
    when = point_stamp(point)
    if when is None:
        return 0
    return max(0, min(int((when - _EPOCH).total_seconds()), 2 ** 31 - 1))


def _newest_first(points):
    return sorted(points, key=lambda p: (_stamp_of(p), p), reverse=True)


def _strip_ext(name, ext):
    if len(name) > len(ext) and os.path.normcase(name[-len(ext):]) == os.path.normcase(ext):
        return name[:-len(ext)]
    return None


def backup_points(listing, stem, path_hash=None, ext=BACKUP_EXT):
    """Names (no extension) of the backup points of the source with
    ``stem`` in ``listing`` (file names of one backup folder), every user's,
    newest first: ``<stem>.<user>.<stamp><ext>``, or with ``path_hash``
    ``<stem>.<path_hash>.<user>.<stamp><ext>``. Matching is anchored on the
    known stem (case-folded where the OS folds), so ``Props.v2``'s points
    are never ``Props``'s. Pass ``ext=BACKUP_SIDECAR_EXT`` for sidecars."""
    head = os.path.normcase(stem + "." + (path_hash + "." if path_hash else ""))
    found = set()
    for name in listing:
        base = _strip_ext(name, ext)
        if base is None or (ext == BACKUP_EXT and _strip_ext(name, BACKUP_SIDECAR_EXT) is not None):
            continue
        if not os.path.normcase(base).startswith(head):
            continue
        tail = base[len(head):].split(".")
        if len(tail) == 2 and _USER.fullmatch(tail[0]) and _STAMP.fullmatch(tail[1]):
            found.add(base)
    return _newest_first(found)


def prune_backups(points, keep, protect=None, mine=None):
    """The points (``backup_points`` names of one source) to delete so that
    ``keep`` remain, newest by the time stamp the names end with, whatever
    the order of ``points``. ``protect`` (the point just written) is never
    deleted and counts as one of the kept. ``mine`` (a set of names or a
    predicate on a name), when given, restricts both the counting and the
    candidates: other points are neither counted nor deleted."""
    if mine is not None:
        is_mine = mine if callable(mine) else mine.__contains__
        points = [p for p in points if is_mine(p)]
    ordered = _newest_first(points)
    keep = max(int(keep), 0)
    if protect is not None and protect in ordered:
        return [p for p in ordered if p != protect][max(keep - 1, 0):]
    return ordered[keep:]


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
    return CommitPaths(stem + ".blend", stem + ".json", stem + ".result.json", lock_path(source_path))


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
