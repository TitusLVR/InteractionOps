"""Pure decision logic of the iOps Materials panel (no bpy, pytest-covered).

Covers numbered-duplicate names (`Steel.001`), the choice of a group's
original, the merge plan, the rows the panel lists (search, source filter,
stacking), names for new materials, fingerprint value freezing and the
report wording. The bpy side lives in operators/materials/.
"""
import ntpath
import posixpath
import re
from collections import namedtuple

# `<base>.<digits>` with 3+ digits: Blender's own collision suffix.
_NUMBERED = re.compile(r"^(?P<base>.+)\.(?P<num>\d{3,})$")

FLOAT_DIGITS = 6


def split_numbered(name):
    """(base, number) for `Steel.001` -> ("Steel", 1); (name, None) for a
    name without a numeric suffix of 3+ digits."""
    m = _NUMBERED.match(name)
    if m is None:
        return name, None
    return m.group("base"), int(m.group("num"))


def base_name(name):
    return split_numbered(name)[0]


def is_numbered(name):
    return split_numbered(name)[1] is not None


def group_by_base(names):
    """{base: [names]} preserving the input order inside each group."""
    groups = {}
    for name in names:
        groups.setdefault(base_name(name), []).append(name)
    return groups


def pick_original(base, members):
    """The group's original: the member named exactly `base`, otherwise the
    lowest-numbered member (ties broken by name)."""
    if base in members:
        return base

    def key(name):
        num = split_numbered(name)[1]
        return (num if num is not None else -1, name)
    return min(members, key=key)


MergeGroup = namedtuple(
    "MergeGroup", "base original merges kept rename")
# merges: [duplicate names merged into original]
# kept:   [duplicate names kept because they differ]
# rename: True when the original is a numbered member renamed to base


def plan_merge(names, fingerprints, force=False, only_base=None,
               taken_names=()):
    """Merge plan over local material names.

    `fingerprints` maps name -> hashable fingerprint (missing = unknown,
    never equivalent unless `force`). `only_base` limits the plan to one
    group. `taken_names` are names the rename must not collide with (other
    local materials outside the group are checked automatically).

    Groups are formed by base name; a group is planned when it contains a
    numbered member. A lone numbered member is renamed to its base when the
    base name is free."""
    groups = group_by_base(names)
    all_names = set(names) | set(taken_names)
    plans = []
    for base, members in groups.items():
        if only_base is not None and base != only_base:
            continue
        if not any(is_numbered(n) for n in members):
            continue
        original = pick_original(base, members)
        merges, kept = [], []
        fp_orig = fingerprints.get(original)
        for name in members:
            if name == original:
                continue
            fp = fingerprints.get(name)
            same = fp is not None and fp_orig is not None and fp == fp_orig
            (merges if same or force else kept).append(name)
        rename = original != base
        if rename:
            # the base name must be free once the merged duplicates are gone
            # (kept members never carry the exact base name: if one did, it
            # would be the original)
            remaining = all_names - set(merges) - {original}
            rename = base not in remaining
        plans.append(MergeGroup(base, original, merges, kept, rename))
    return plans


def plan_removal(slot_count, removed, targets=None):
    """remap[old slot] -> new slot index after removing the slots in
    `removed`. Faces of a removed slot go to the new index of
    targets[removed slot] (an old index of a kept slot) when given, else to
    the first remaining slot (0)."""
    gone = set(removed)
    targets = targets or {}
    new_index, n = [], 0
    for i in range(slot_count):
        new_index.append(n)
        if i not in gone:
            n += 1
    remap = []
    for i in range(slot_count):
        if i not in gone:
            remap.append(new_index[i])
        elif i in targets:
            remap.append(new_index[targets[i]])
        else:
            remap.append(0)
    return remap


def plan_slot_collapse(slot_keys, drop_empty=False, collapse_repeats=True):
    """Collapse repeated materials in a slot list.

    `slot_keys`: per slot a hashable material identity, None for an empty
    slot. A material repeated in later slots keeps its first slot; the later
    ones are removed and their faces move to the kept one (off with
    `collapse_repeats=False`). With `drop_empty`, empty slots are removed
    and their faces move to the first remaining slot. Other materials stay
    with their faces.

    Returns (removed slot indices ascending, remap) where remap[old index] is
    the slot index a face on that old slot points at afterwards."""
    first = {}
    removed, targets = [], {}
    for i, key in enumerate(slot_keys):
        if key is None:
            if drop_empty:
                removed.append(i)
            continue
        if key in first and collapse_repeats:
            removed.append(i)
            targets[i] = first[key]
        elif key not in first:
            first[key] = i
    return removed, plan_removal(len(slot_keys), removed, targets)


def remap_indices(indices, remap):
    """Face / spline material indices through a remap; an index past the
    slot list (drawn with the last slot) follows the last slot."""
    if not remap:
        return [0 if i < 0 else i for i in indices]
    last = len(remap) - 1
    return [remap[min(max(i, 0), last)] for i in indices]


Row = namedtuple("Row", "key display count base members")
# key:     key of the item the row stands for (the group's original)
# display: text drawn for the row
# count:   group size (1 when stacking is off or the material is alone)
# base:    group base name ("" when stacking is off)
# members: keys of all materials the row stands for


def matches_search(query, *names):
    """Case-insensitive: every whitespace-separated token of `query` occurs
    in at least one of `names`. Empty query matches everything."""
    tokens = query.lower().split()
    if not tokens:
        return True
    hay = [n.lower() for n in names]
    return all(any(t in h for h in hay) for t in tokens)


def build_rows(entries, query="", stack=True):
    """Rows for the panel.

    `entries`: ordered [(key, name, library, in_source)] where key is any
    hashable identifying the material, library is "" for local materials
    and in_source tells whether the source filter (Scene / Selected / File)
    includes it.

    Stacking groups materials by (library, base name); a group is listed
    once, under its base name, standing for its original, when any member is
    in the source and the search matches the base or any member name. Without
    stacking every material that is in the source and matches is a row of
    its own."""
    if not stack:
        return [Row(key, name, 1, "", (key,))
                for key, name, _lib, in_source in entries
                if in_source and matches_search(query, name)]
    groups = {}
    order = []
    for key, name, lib, in_source in entries:
        gkey = (lib, base_name(name))
        if gkey not in groups:
            groups[gkey] = []
            order.append(gkey)
        groups[gkey].append((key, name, in_source))
    rows = []
    for gkey in order:
        members = groups[gkey]
        if not any(m[2] for m in members):
            continue
        base = gkey[1]
        names = [m[1] for m in members]
        if not matches_search(query, base, *names):
            continue
        original = pick_original(base, names)
        okey = next(m[0] for m in members if m[1] == original)
        rows.append(Row(okey, base, len(members), base,
                        tuple(m[0] for m in members)))
    # rows follow the position of their original in the input order
    position = {e[0]: i for i, e in enumerate(entries)}
    rows.sort(key=lambda r: position[r.key])
    return rows


def next_material_name(taken, stem="Material"):
    """`stem`, else `stem 2`, `stem 3`, ... — never a `.001` suffix, which
    would itself read as a numbered duplicate."""
    taken = set(taken)
    if stem not in taken:
        return stem
    i = 2
    while f"{stem} {i}" in taken:
        i += 1
    return f"{stem} {i}"


def freeze(value, digits=FLOAT_DIGITS):
    """Hashable, comparison-stable copy of a property value: floats rounded,
    sequences to tuples (recursively), -0.0 folded into 0.0."""
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, float):
        r = round(value, digits)
        return 0.0 if r == 0 else r
    if isinstance(value, (int, str)):
        return value
    if isinstance(value, (set, frozenset)):
        return tuple(sorted(freeze(v, digits) for v in value))
    if isinstance(value, dict):
        return tuple(sorted((k, freeze(v, digits)) for k, v in value.items()))
    try:
        return tuple(freeze(v, digits) for v in value)
    except TypeError:
        return repr(value)


def plural(n, word, words=None):
    return f"{n} {word if n == 1 else (words or word + 's')}"


def format_skipped(skipped):
    """'1 skipped (Empty)' / '3 skipped (2 Empty, 1 Camera)' from
    {label: count}; '' when nothing was skipped."""
    total = sum(skipped.values())
    if not total:
        return ""
    parts = sorted(skipped.items(), key=lambda kv: (-kv[1], kv[0]))
    if len(parts) == 1:
        detail = parts[0][0]
    else:
        detail = ", ".join(f"{n} {label}" for label, n in parts)
    return f"{total} skipped ({detail})"


def format_assign_report(material, objects, skipped, faces=None):
    """Report line of an assignment: objects / faces done plus skipped."""
    if faces is None:
        text = f"Assigned {material} to {plural(objects, 'object')}"
    else:
        text = (f"Assigned {material} to {plural(faces, 'face')} "
                f"on {plural(objects, 'object')}")
    tail = format_skipped(skipped)
    return f"{text}, {tail}" if tail else text


def format_merge_report(plans, linked_skipped=0, collapsed=None,
                        empty_removed=None, slot_skipped=None):
    """Report line of a merge / slot cleanup run.

    `plans` is None when merging was switched off; `collapsed` /
    `empty_removed` are None when that part was switched off.
    `slot_skipped` is {label: count} of data whose slots were left alone."""
    parts = []
    if plans is not None:
        merged = sum(len(p.merges) for p in plans)
        kept = [n for p in plans for n in p.kept]
        renamed = sum(1 for p in plans if p.rename)
        parts.append(f"merged {plural(merged, 'duplicate')}")
        if renamed:
            parts.append(f"renamed {renamed}")
        if kept:
            shown = ", ".join(kept[:3]) + (", ..." if len(kept) > 3 else "")
            parts.append(f"kept {len(kept)} different ({shown})")
        if linked_skipped:
            parts.append(f"skipped {linked_skipped} linked")
    if collapsed is not None:
        parts.append(f"collapsed {plural(collapsed, 'slot')}")
    if empty_removed is not None:
        parts.append(f"removed {plural(empty_removed, 'empty slot')}")
    if slot_skipped:
        total = sum(slot_skipped.values())
        detail = ", ".join(f"{n} {label}" for label, n in
                           sorted(slot_skipped.items()))
        parts.append(f"slots left on {plural(total, 'object')} ({detail})")
    if not parts:
        return "Nothing to do"
    text = ", ".join(parts)
    return text[0].upper() + text[1:]


def list_rows(visible, max_rows):
    """Rows a list shows: as many as there are items, at least 1, at most
    `max_rows` (beyond that the list scrolls)."""
    return max(1, min(int(visible), int(max_rows)))


def gallery_columns(width_units, cell_units, gap_units=0.4, margin_units=1.0):
    """Columns that fit `width_units` with cells of `cell_units`."""
    usable = width_units - margin_units
    return max(1, int(usable // (cell_units + gap_units)))


def normalize_path(path, windows=None):
    """Comparable form of a file or folder path: separators unified, `..`
    resolved, trailing separators dropped, case folded on Windows paths.
    `windows` forces the flavour (default: a drive letter or backslash
    means Windows)."""
    if not path:
        return ""
    if windows is None:
        windows = "\\" in path or (len(path) > 1 and path[1] == ":")
    if windows:
        norm = ntpath.normcase(ntpath.normpath(path.replace("/", "\\")))
        return norm.rstrip("\\") if len(norm) > 3 else norm
    norm = posixpath.normpath(path)
    return norm.rstrip("/") if len(norm) > 1 else norm


def path_in_library(file_path, library_root):
    """True when `file_path` lies inside the folder `library_root` (or is
    that folder)."""
    f, root = normalize_path(file_path), normalize_path(library_root)
    if not f or not root:
        return False
    if f == root:
        return True
    sep = "\\" if "\\" in root or "\\" in f else "/"
    return f.startswith(root if root.endswith(sep) else root + sep)


def same_path(a, b):
    return bool(a) and normalize_path(a) == normalize_path(b)


def asset_source_key(library_file, asset_name):
    """Key stored on an appended material to find it again: the normalized
    library .blend path and the asset (datablock) name."""
    return f"{normalize_path(library_file)}|{asset_name}"


def library_name_for_folder(folder, taken):
    """Asset library name from the folder name, made unique against
    `taken` with ` 2`, ` 3`, ..."""
    norm = folder.replace("\\", "/").rstrip("/")
    stem = norm.rsplit("/", 1)[-1] if norm else ""
    if not stem or stem.endswith(":"):
        stem = "Materials"
    return next_material_name(taken, stem)


def find_library_by_path(libraries, folder):
    """Name of the first (name, path) pair whose path is `folder`, else
    None."""
    for name, path in libraries:
        if same_path(path, folder):
            return name
    return None


def shelf_preview_size(thumbnail_units, unit_px=20, lo=16, hi=256):
    """Asset shelf preview size in pixels from the thumbnail-size pref in
    interface units (one unit = 20 px at 1.0 resolution scale)."""
    return max(lo, min(hi, int(thumbnail_units) * unit_px))


def page_slice(total, per_page, page):
    """(start, stop, page, pages) with `page` clamped into range."""
    per_page = max(1, per_page)
    pages = max(1, -(-total // per_page))
    page = min(max(0, page), pages - 1)
    start = page * per_page
    return start, min(total, start + per_page), page, pages
