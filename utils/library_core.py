"""Pure helpers for the ported library addon -- no bpy imports.

These are the filesystem/catalog-facing helpers ported from the source
addon's `__init__.py`, minus anything that depends on `bpy` (callers apply
`bpy.path.abspath` before calling `normalize_path`, resolve
`context.preferences.filepaths.asset_libraries` into the `entries` list
before calling `find_master_in_entries`, etc.).
"""

import hashlib
import json
import os
from dataclasses import asdict, dataclass, fields
from pathlib import Path

MASTER_FILENAMES = {
    "frontline_library.blend",
    "master_library.blend",
    "master_kitbash.blend",
    "kitbash_library.blend",
}


def normalize_path(value):
    if not value:
        return ""
    return os.path.normpath(os.path.abspath(value))


def valid_master_file(filepath):
    return bool(
        filepath
        and os.path.isfile(filepath)
        and filepath.lower().endswith(".blend")
    )


def find_master_in_entries(entries):
    candidates = []

    for _library_name, root in entries:
        for filename in MASTER_FILENAMES:
            filepath = Path(root, filename)
            if filepath.is_file():
                candidates.append(str(filepath.resolve()))

    if len(candidates) == 1:
        return candidates[0]

    for library_name, root in entries:
        searchable_name = ("%s %s" % (library_name, root)).lower()
        if not any(word in searchable_name for word in ("kitbash", "frontline", "library")):
            continue
        root_path = Path(root)
        for path in root_path.rglob("*.blend"):
            name = path.name.lower()
            # Known master names, plus any blend whose name says what it is
            # ("library_test.blend", "ships_master.blend"). Ambiguity still
            # returns "" below rather than guessing.
            if name in MASTER_FILENAMES or "master" in name or "library" in name:
                resolved = str(path.resolve())
                if resolved not in candidates:
                    candidates.append(resolved)

    if len(candidates) == 1:
        return candidates[0]

    if not candidates:
        for library_name, root in entries:
            searchable_name = ("%s %s" % (library_name, root)).lower()
            if not any(word in searchable_name for word in ("kitbash", "frontline", "library")):
                continue
            blend_files = list(Path(root).glob("*.blend"))
            if len(blend_files) == 1:
                candidates.append(str(blend_files[0].resolve()))

    return candidates[0] if len(candidates) == 1 else ""


def asset_cache_key(library_path, asset_name, id_type="OBJECT"):
    value = "%s\0%s\0%s" % (
        normalize_path(library_path),
        asset_name,
        id_type,
    )
    return hashlib.sha1(value.encode("utf-8")).hexdigest()


def thumbnail_filename(library_path, asset_name, id_type="OBJECT"):
    return "%s.png" % asset_cache_key(library_path, asset_name, id_type)


@dataclass
class CatalogEntry:
    asset_name: str = ""
    library_path: str = ""
    id_type: str = "OBJECT"
    data_collection: str = "objects"
    subtype: str = ""
    category: str = "MISC"
    thumbnail_path: str = ""


_CATALOG_ENTRY_FIELDS = tuple(field.name for field in fields(CatalogEntry))


def _empty_catalog():
    return {"master_file": "", "master_mtime": 0.0, "master_size": 0, "assets": []}


def load_catalog_file(json_path):
    try:
        with open(json_path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return _empty_catalog()

    if not isinstance(data, dict):
        return _empty_catalog()

    result = _empty_catalog()
    result["master_file"] = data.get("master_file", "")
    result["master_mtime"] = data.get("master_mtime", 0.0)
    result["master_size"] = data.get("master_size", 0)
    result["assets"] = [
        CatalogEntry(**{key: item[key] for key in _CATALOG_ENTRY_FIELDS if key in item})
        for item in data.get("assets", [])
    ]
    return result


def save_catalog_file(json_path, master_file, master_mtime, master_size, entries):
    parent = os.path.dirname(json_path)
    if parent:
        os.makedirs(parent, exist_ok=True)

    data = {
        "master_file": master_file,
        "master_mtime": master_mtime,
        "master_size": master_size,
        "assets": [asdict(entry) for entry in entries],
    }
    with open(json_path, "w", encoding="utf-8") as handle:
        json.dump(data, handle)


def catalog_is_stale(master_stat, master_mtime, master_size, has_assets):
    return (
        not has_assets
        or abs(master_stat.st_mtime - master_mtime) > 0.001
        or float(master_stat.st_size) != float(master_size)
    )


def result_data(filepath):
    try:
        with open(filepath, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return {}


def log_tail(filepath, line_count=8):
    try:
        with open(filepath, "r", encoding="utf-8", errors="replace") as handle:
            lines = handle.readlines()
    except OSError:
        return ""
    return "".join(lines[-line_count:]).strip()
