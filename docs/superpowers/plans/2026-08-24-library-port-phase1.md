# IOPS Library (Phase 1: mechanical port) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Port the standalone "frontline_kitbash" Blender addon (master-file asset library: publish / popup-insert / remove, all master mutations via background Blender workers) into the InteractionOps (IOPS) addon as a native module, with no behavior changes beyond the renames and storage relocation specified here.

**Architecture:** Pure-python helpers go to `utils/library_core.py` (pytest-covered, no `bpy`, following the repo's `*_core.py` pattern). bpy glue + module catalog state go to `operators/library/common.py`. Each operator gets its own file under `operators/library/`. The three worker scripts (run via `blender --background --python`) stay standalone files in the same package. The popup-asset catalog moves from AddonPreferences storage to a JSON file in the thumbnail cache directory. Registration is folded into the main `__init__.py`.

**Tech Stack:** Blender Python API (bpy, gpu, blf), pytest for the pure module.

**Spec:** No separate spec file. The "Background & Scope" section below is the binding spec; the source addon at `C:\Users\cvitk\Downloads\frontline_library\frontline_kitbash\` is the behavioral reference.

## Background & Scope

The source addon (call its `__init__.py` **SRC**, its directory **SRC_DIR**) publishes datablocks into one master .blend via background Blender subprocesses and inserts them from a GPU-drawn popup. Phase 1 = mechanical port into IOPS:

- Same behavior, IOPS naming, IOPS file layout.
- Catalog storage: JSON file on disk instead of AddonPreferences CollectionProperty.
- Thumbnail cache: directory next to the master file (fallback: temp), instead of always temp.
- Dead code dropped (see "Dropped code" below).
- NO keymap registration (that is Phase 2, via the IOPS hotkey system). The popup is reachable via the sidebar panel button and operator search.

**Dropped code (do not port):** SRC `builtin_icon_value` (81-86), `refresh_asset_browsers` (165-201, replaced by existing `utils/assets.py:refresh_asset_browser`), `run_thumbnail_worker` (243-274), `ensure_thumbnail` (277-298), `preview_icon_id` (301-322), `reset_preview_collection` (325-330), `asset_icon` (474-487), `FLT_KB_PopupAsset` (546-563), `FLT_KB_AddonPreferences` (566-611, replaced by props added to IOPS prefs), `SRC_DIR/thumbnail_worker.py` (whole file), keymap functions (1896-1914), the per-asset row listing in the prefs draw.

## Global Constraints

- Source addon path (read-only reference): `C:\Users\cvitk\Downloads\frontline_library\frontline_kitbash\` — `__init__.py` (SRC), `publish_worker.py`, `delete_worker.py`, `catalog_worker.py`.
- Repo root here IS the addon package. Addon prefs are accessed exactly as elsewhere in the repo: `bpy.context.preferences.addons["InteractionOps"].preferences`.
- The word "frontline" may appear ONLY as string data required for backward compatibility (legacy custom-prop names, legacy container-collection names, legacy master filenames). Never in identifiers, comments, docstrings, UI text, print messages, or commit messages. The word "CCP" must never appear anywhere.
- Worker scripts must remain standalone-executable (import only stdlib + bpy; no relative addon imports).
- `bpy.data.libraries.load(..., clear_asset_data=True)` exists only in Blender 4.0+; it must be version-gated (exact code in Task 5). Nothing else in the port may hard-require 4.0+ at registration time.
- No new keymaps or keymap edits in this phase.
- Tests for pure code use pytest, live in `tests/`, and must not import `bpy` (see `tests/conftest.py` for how the repo isolates pytest from the addon `__init__.py`).
- Run `python -m py_compile <file>` on every created/modified .py file before committing.
- Commit messages: short imperative subject, e.g. `feat(library): add pure core helpers`. Every commit message ends with the line: `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.

### Rename table (applies to ALL ported code)

| Source | Target |
|---|---|
| bl_idname `frontline_kitbash.find_master` | `iops.library_find_master` |
| bl_idname `frontline_kitbash.refresh_catalog` | `iops.library_refresh` |
| bl_idname `frontline_kitbash.insert_popup_asset` | `iops.library_insert_asset` |
| bl_idname `frontline_kitbash.remove_library_asset` | `iops.library_remove_asset` |
| bl_idname `frontline_kitbash.publish_active` | `iops.library_publish` |
| bl_idname `view3d.frontline_kitbash_popup` | `iops.library_popup` |
| class `FLT_KB_OT_find_master` | `IOPS_OT_LibraryFindMaster` |
| class `FLT_KB_OT_refresh_catalog` | `IOPS_OT_LibraryRefresh` |
| class `FLT_KB_OT_insert_popup_asset` | `IOPS_OT_LibraryInsertAsset` |
| class `FLT_KB_OT_remove_library_asset` | `IOPS_OT_LibraryRemoveAsset` |
| class `FLT_KB_OT_publish_active` | `IOPS_OT_LibraryPublish` |
| class `FLT_KB_OT_open_popup` | `IOPS_OT_LibraryPopup` |
| class `FLT_KB_PT_sidebar` | `IOPS_PT_Library` (bl_idname `IOPS_PT_Library`, bl_category `"iOps"`) |
| WM prop `frontline_kitbash_status` | `iops_library_status` |
| WM prop `frontline_kitbash_busy` | `iops_library_busy` |
| WM prop `frontline_kitbash_placement` | `iops_library_placement` |
| WM props `frontline_library_<cat>_expanded` | `iops_library_<cat>_expanded` |
| prefs `master_library_file` | prefs `library_master_file` |
| prefs `preview_size` | prefs `library_preview_size` |
| prefs `shader_group_name` | prefs `library_shader_group` |
| prefs `popup_assets`, `catalog_master_mtime`, `catalog_master_size` | GONE — replaced by the JSON catalog (Task 2) |
| datablock prop `"frontline_kitbash_published"` | write `"iops_library_published"` |
| datablock prop `"frontline_kitbash_owner"` | write `"iops_library_owner"`, read with legacy fallback |
| datablock prop `"frontline_kitbash_root"` | write `"iops_library_root"`, read with legacy fallback |
| collection `"Frontline Library Assets"` / `"Frontline Kitbash Assets"` | `"IOPS Library Assets"` (legacy names recognized + renamed on touch) |
| temp dir `frontline_kitbash_cache` | cache dir per Task 2 `cache_directory()` |
| temp prefixes `frontline_library_*` | `iops_library_*` |
| print tags `FRONTLINE_LIBRARY_*` | `IOPS_LIBRARY_*` |
| UI text "Frontline Library" / "Frontline Kitbash" | "IOPS Library" |
| `bpy.ops.frontline_kitbash.*` call sites | `bpy.ops.iops.library_*` |

Legacy fallback read pattern (workers and `collection_root_object`):

```python
OWNER_PROPERTY = "iops_library_owner"
LEGACY_OWNER_PROPERTY = "frontline_kitbash_owner"
ROOT_OBJECT_PROPERTY = "iops_library_root"
LEGACY_ROOT_OBJECT_PROPERTY = "frontline_kitbash_root"

# read:  obj.get(OWNER_PROPERTY, obj.get(LEGACY_OWNER_PROPERTY))
# write: always the new name only
```

### Catalog JSON contract (produced by Task 2, consumed by Tasks 4-8)

Path: `os.path.join(cache_directory(master_file), "catalog.json")`. Shape:

```json
{
  "master_file": "D:/abs/path/Master_Library.blend",
  "master_mtime": 1724500000.0,
  "master_size": 12345678,
  "assets": [
    {
      "asset_name": "Greeble_A",
      "library_path": "D:/abs/path/Master_Library.blend",
      "id_type": "OBJECT",
      "data_collection": "objects",
      "subtype": "MESH",
      "category": "GEOMETRY",
      "thumbnail_path": "D:/abs/path/.iops_library/ab12...png"
    }
  ]
}
```

In-session, entries are `CatalogEntry` dataclass instances (attribute access, so ported `entry.asset_name` code keeps working).

---

### Task 1: Pure core module + tests

**Files:**
- Create: `utils/library_core.py`
- Test: `tests/test_library_core.py`

**Interfaces:**
- Produces (later tasks import these from `..utils.library_core` / `...utils.library_core`):
  - `MASTER_FILENAMES: set[str]` — SRC 39-44 verbatim.
  - `normalize_path(value: str) -> str` — SRC 95-98 but WITHOUT `bpy.path.abspath` (callers apply that first): returns `""` for falsy, else `os.path.normpath(os.path.abspath(value))`.
  - `valid_master_file(filepath) -> bool` — SRC 157-162 verbatim.
  - `find_master_in_entries(entries: list[tuple[str, str]]) -> str` — port of SRC `find_master_file` 118-154, with the `asset_library_entries(context)` call replaced by the `entries` parameter (each item `(library_name, root_dir)`). Same three-stage candidate logic, same keyword set `("kitbash", "frontline", "library")` (allowed: string data).
  - `asset_cache_key(library_path, asset_name, id_type="OBJECT") -> str` — SRC 227-233, using `normalize_path`.
  - `thumbnail_filename(library_path, asset_name, id_type="OBJECT") -> str` — returns `"%s.png" % asset_cache_key(...)` (no directory; callers join with the cache dir).
  - `@dataclass CatalogEntry` — fields exactly: `asset_name: str = ""`, `library_path: str = ""`, `id_type: str = "OBJECT"`, `data_collection: str = "objects"`, `subtype: str = ""`, `category: str = "MISC"`, `thumbnail_path: str = ""`.
  - `load_catalog_file(json_path) -> dict` — reads the catalog JSON; returns `{"master_file": "", "master_mtime": 0.0, "master_size": 0, "assets": []}` on any `OSError`/`ValueError` or if the parsed value is not a dict; `assets` list items are converted to `CatalogEntry` (unknown keys ignored via explicit field pick, missing keys default).
  - `save_catalog_file(json_path, master_file, master_mtime, master_size, entries) -> None` — writes the JSON contract above (`entries` are `CatalogEntry`; serialize with `dataclasses.asdict`). Creates the parent dir if needed.
  - `catalog_is_stale(master_stat, master_mtime, master_size, has_assets) -> bool` — pure predicate: `True` if `not has_assets` or `abs(master_stat.st_mtime - master_mtime) > 0.001` or `float(master_stat.st_size) != float(master_size)`.
  - `result_data(filepath) -> dict` — SRC 204-209 verbatim.
  - `log_tail(filepath, line_count=8) -> str` — SRC 212-218 verbatim.
- No `bpy` import anywhere in this file. stdlib only: `os`, `json`, `hashlib`, `dataclasses`, `pathlib`.

- [ ] **Step 1: Write the failing tests**

`tests/test_library_core.py` (complete file):

```python
import json
import os

from utils.library_core import (
    CatalogEntry,
    asset_cache_key,
    catalog_is_stale,
    find_master_in_entries,
    load_catalog_file,
    log_tail,
    normalize_path,
    result_data,
    save_catalog_file,
    thumbnail_filename,
    valid_master_file,
)


class FakeStat:
    def __init__(self, mtime, size):
        self.st_mtime = mtime
        self.st_size = size


def test_normalize_path_empty():
    assert normalize_path("") == ""
    assert normalize_path(None) == ""


def test_normalize_path_normalizes(tmp_path):
    messy = str(tmp_path) + os.sep + "a" + os.sep + ".." + os.sep + "b.blend"
    assert normalize_path(messy) == os.path.normpath(str(tmp_path) + os.sep + "b.blend")


def test_valid_master_file(tmp_path):
    blend = tmp_path / "Master_Library.blend"
    blend.write_bytes(b"")
    assert valid_master_file(str(blend))
    assert not valid_master_file(str(tmp_path / "missing.blend"))
    txt = tmp_path / "notes.txt"
    txt.write_text("x")
    assert not valid_master_file(str(txt))
    assert not valid_master_file("")


def test_find_master_single_known_filename(tmp_path):
    (tmp_path / "Master_Library.blend").write_bytes(b"")
    result = find_master_in_entries([("Anything", str(tmp_path))])
    assert os.path.basename(result) == "Master_Library.blend"


def test_find_master_ambiguous_returns_empty(tmp_path):
    d1 = tmp_path / "a"
    d2 = tmp_path / "b"
    d1.mkdir()
    d2.mkdir()
    (d1 / "Master_Library.blend").write_bytes(b"")
    (d2 / "Master_Kitbash.blend").write_bytes(b"")
    result = find_master_in_entries([("A", str(d1)), ("B", str(d2))])
    assert result == ""


def test_find_master_single_blend_in_keyword_library(tmp_path):
    (tmp_path / "parts.blend").write_bytes(b"")
    assert find_master_in_entries([("My Kitbash", str(tmp_path))]) != ""
    assert find_master_in_entries([("Unrelated", str(tmp_path))]) == ""


def test_cache_key_stable_and_distinct():
    key1 = asset_cache_key("C:/lib/master.blend", "Bolt", "OBJECT")
    key2 = asset_cache_key("C:/lib/master.blend", "Bolt", "OBJECT")
    key3 = asset_cache_key("C:/lib/master.blend", "Bolt", "MATERIAL")
    assert key1 == key2
    assert key1 != key3
    assert len(key1) == 40
    assert thumbnail_filename("C:/lib/master.blend", "Bolt") == key1 + ".png"


def test_catalog_roundtrip(tmp_path):
    path = str(tmp_path / "cache" / "catalog.json")
    entries = [
        CatalogEntry(asset_name="A", library_path="m.blend", id_type="OBJECT",
                     data_collection="objects", subtype="MESH",
                     category="GEOMETRY", thumbnail_path=""),
    ]
    save_catalog_file(path, "m.blend", 12.5, 999, entries)
    data = load_catalog_file(path)
    assert data["master_file"] == "m.blend"
    assert data["master_mtime"] == 12.5
    assert data["master_size"] == 999
    assert len(data["assets"]) == 1
    assert isinstance(data["assets"][0], CatalogEntry)
    assert data["assets"][0].asset_name == "A"


def test_load_catalog_missing_and_corrupt(tmp_path):
    missing = load_catalog_file(str(tmp_path / "nope.json"))
    assert missing["assets"] == []
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    assert load_catalog_file(str(bad))["assets"] == []
    notdict = tmp_path / "list.json"
    notdict.write_text("[1, 2]")
    assert load_catalog_file(str(notdict))["assets"] == []


def test_catalog_is_stale():
    stat = FakeStat(100.0, 50)
    assert catalog_is_stale(stat, 100.0, 50, has_assets=False)
    assert not catalog_is_stale(stat, 100.0, 50, has_assets=True)
    assert catalog_is_stale(stat, 99.0, 50, has_assets=True)
    assert catalog_is_stale(stat, 100.0, 51, has_assets=True)


def test_result_data_and_log_tail(tmp_path):
    good = tmp_path / "r.json"
    good.write_text(json.dumps({"ok": True}))
    assert result_data(str(good)) == {"ok": True}
    assert result_data(str(tmp_path / "missing.json")) == {}
    log = tmp_path / "w.log"
    log.write_text("\n".join("line%d" % i for i in range(20)))
    tail = log_tail(str(log), line_count=3)
    assert tail.splitlines() == ["line17", "line18", "line19"]
    assert log_tail(str(tmp_path / "missing.log")) == ""
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_library_core.py -q`
Expected: collection error / import failure (`utils.library_core` does not exist).

- [ ] **Step 3: Implement `utils/library_core.py`**

Port from SRC per the Interfaces list above. Note: `find_master_in_entries` keeps SRC's `Path` usage; guard `Path(root).rglob`/`glob` with try/except `OSError` is NOT in SRC — do not add it (mechanical port).

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_library_core.py -q` → all pass.
Then run the full suite: `python -m pytest tests/ -q` — the only failure allowed is the pre-existing `tests/test_polygon_match.py::test_assemble_dedups_same_placement_disjoint_faces`.

- [ ] **Step 5: Commit**

```bash
git add utils/library_core.py tests/test_library_core.py
git commit -m "feat(library): pure core helpers + tests"
```

---

### Task 2: bpy glue module + WM props module

**Files:**
- Create: `operators/library/__init__.py` (empty file)
- Create: `operators/library/props.py`
- Create: `operators/library/common.py`

**Interfaces:**
- Consumes: everything from Task 1 (`from ...utils.library_core import ...` — note `operators/library/` is two levels below repo root, so THREE dots).
- Produces for Tasks 4-8 (all in `common.py` unless noted):
  - `props.CATEGORY_DEFINITIONS` — SRC 52-57 with the WM prop names renamed to `iops_library_geometry_expanded`, `iops_library_shaders_expanded`, `iops_library_lights_expanded`, `iops_library_misc_expanded`.
  - `props.register_wm_properties()` / `props.unregister_wm_properties()` — register/unregister on `bpy.types.WindowManager`: `iops_library_status` (StringProperty, SKIP_SAVE), `iops_library_busy` (BoolProperty, SKIP_SAVE), `iops_library_placement` (FloatVectorProperty size=3 subtype TRANSLATION, SKIP_SAVE), and the four expanded BoolProperties (default True, SKIP_SAVE) — port of SRC 1922-1943 / 1953-1957. `unregister_wm_properties` uses `delattr` guarded by `hasattr`.
  - `common.get_prefs(context=None)` — returns `(context or bpy.context).preferences.addons["InteractionOps"].preferences`, or `None` on KeyError.
  - `common.abs_path(value)` — `library_core.normalize_path(bpy.path.abspath(value))` for truthy value else `""` (this is the bpy-aware replacement for every SRC `normalized_path` call site).
  - `common.configured_master_file(context)` — SRC 101-105 using `get_prefs` + prefs field `library_master_file` + `abs_path`.
  - `common.asset_library_entries(context)` — SRC 108-115 (uses `abs_path`).
  - `common.find_master_file(context)` — `library_core.find_master_in_entries(asset_library_entries(context))`.
  - `common.cache_directory(master_file)` — NEW (replaces SRC 221-224):

```python
def cache_directory(master_file):
    """Thumbnail + catalog cache. Lives next to the master so it survives
    temp cleanups and travels with a synced library folder; falls back to
    the system temp dir when the master location is not writable."""
    if master_file:
        candidate = os.path.join(os.path.dirname(master_file), ".iops_library")
        try:
            os.makedirs(candidate, exist_ok=True)
            probe = os.path.join(candidate, ".write_probe")
            with open(probe, "w", encoding="utf-8"):
                pass
            os.remove(probe)
            return candidate
        except OSError:
            pass
    path = os.path.join(tempfile.gettempdir(), "iops_library_cache")
    os.makedirs(path, exist_ok=True)
    return path
```

  - `common.catalog_json_path(master_file)` — `os.path.join(cache_directory(master_file), "catalog.json")`.
  - `common.get_catalog(context)` — returns the module-level `list[CatalogEntry]`. Lazy: on first call (module flag `_catalog_loaded`), resolve `configured_master_file(context)`; if valid, `load_catalog_file(catalog_json_path(master))` into `_catalog` (also caching `_catalog_mtime`/`_catalog_size` module vars from the file's `master_mtime`/`master_size`); else `[]`.
  - `common.run_catalog_worker(master_file)` — SRC 363-392 with the temp-prefix rename and `cache_directory(master_file)` passed to the worker; worker script path is `os.path.join(os.path.dirname(__file__), "catalog_worker.py")`.
  - `common.sync_catalog(context, report_status=True)` — port of SRC 395-453 with storage swapped: master resolution identical (auto-`find_master_file` + write back to `prefs.library_master_file`); on worker success build `CatalogEntry` list (each entry gets `library_path=master_file`); collect previous thumbnail paths from the OLD `_catalog` before replacing; `save_catalog_file(catalog_json_path(master), master, data["master_mtime"], data["master_size"], entries)`; update `_catalog`/`_catalog_mtime`/`_catalog_size`/`_catalog_loaded`; call `reset_overlay_textures()`; delete stale thumbnail PNGs (previous minus current, same as SRC 436-445); status message to `context.window_manager.iops_library_status` ("Synced %d asset(s) from %s"). Returns `(ok, message)` like SRC.
  - `common.catalog_needs_sync(context)` — port of SRC 456-471 via `library_core.catalog_is_stale(os.stat(master), _catalog_mtime, _catalog_size, bool(get_catalog(context)))`; same early-outs as SRC (no prefs → False; invalid master → `not get_catalog(context)`; OSError → False).
  - `common.refresh_library_browsers()` — thin wrapper calling `refresh_asset_browser()` from `...utils.assets` (the existing IOPS helper). Returns None; ported status messages that used SRC's refresh count just append " Asset Browser refreshed." unconditionally after calling it.
  - `common.placement_from_mouse(context, event)` — SRC 490-518 verbatim.
  - `common.object_hierarchy(root)` — SRC 521-530 verbatim.
  - `common.collection_root_object(collection)` — SRC 533-543 with the legacy fallback read pattern from Global Constraints (constants `ROOT_OBJECT_PROPERTY`, `LEGACY_ROOT_OBJECT_PROPERTY` defined in this module).
  - `common.DATA_OBJECT_TYPES` — SRC 58-71 verbatim.
  - `common.worker_creation_flags()` — returns `subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0`.
  - Overlay texture cache (lives here so `sync_catalog` can reset it without importing the popup module): module dicts `overlay_textures`, `overlay_images`, list `overlay_owned_images`, functions `reset_overlay_textures()` (SRC 333-342) and `overlay_texture(entry)` (SRC 345-360, using `abs_path`).

- [ ] **Step 1: Create the three files** per the interface list. `common.py` imports: `os`, `sys`, `shutil`, `subprocess`, `tempfile`, `json`, `bpy`, `gpu`, `from bpy_extras import view3d_utils`, `from ...utils.library_core import (...)`, `from ...utils.assets import refresh_asset_browser`.
- [ ] **Step 2: Verify**

Run: `python -m py_compile operators/library/__init__.py operators/library/props.py operators/library/common.py`
Run: `python -m pytest tests/ -q` (no new failures)
Run: `grep -rn "frontline" operators/library/ | grep -iv "legacy\|LEGACY"` — expected: only lines defining legacy string constants (if grep shows anything else, fix it).

- [ ] **Step 3: Commit**

```bash
git add operators/library/
git commit -m "feat(library): bpy glue, JSON catalog state, WM props"
```

---

### Task 3: Worker scripts

**Files:**
- Create: `operators/library/publish_worker.py` (port of `SRC_DIR/publish_worker.py`)
- Create: `operators/library/delete_worker.py` (port of `SRC_DIR/delete_worker.py`)
- Create: `operators/library/catalog_worker.py` (port of `SRC_DIR/catalog_worker.py`)

**Interfaces:**
- Consumes: nothing from the addon (standalone scripts; stdlib + bpy only).
- Produces: same CLI contracts as the source workers (argv after `--`, JSON result files). `delete_worker.remove_assets(manifest)` stays importable (Task 6 calls it in-process). `catalog_worker` result JSON feeds the Task 2 catalog contract — its per-asset dict keys stay exactly `asset_name`, `id_type`, `data_collection`, `subtype`, `category`, `thumbnail_path`.

- [ ] **Step 1: Port all three files** near-verbatim with these changes only:
  - `publish_worker.py`: `ASSET_CONTAINER_NAME = "IOPS Library Assets"`; `LEGACY_ASSET_CONTAINER_NAMES = ("Frontline Library Assets", "Frontline Kitbash Assets")` — `ensure_asset_container` tries the new name, then each legacy name, renames a found legacy collection to the new name (extend the source's existing rename logic to loop over the tuple). Property constants per the Global Constraints fallback pattern: write new names (`iops_library_published`/`_owner`/`_root`), read with legacy fallback in `remove_existing_collection_asset`'s owner check. `apply_asset_metadata`: `author = "IOPS Library"`, description "Published %s asset by IOPS Library". Print tags `IOPS_LIBRARY_RESULT` / `IOPS_LIBRARY_ERROR`.
  - `delete_worker.py`: owner-check fallback (`obj.get(OWNER_PROPERTY, obj.get(LEGACY_OWNER_PROPERTY)) == data_block.name`); print tags `IOPS_LIBRARY_DELETE` / `IOPS_LIBRARY_DELETE_ERROR`.
  - `catalog_worker.py`: image datablock name "IOPS Library Catalog Thumbnail"; print tags `IOPS_LIBRARY_CATALOG` / `IOPS_LIBRARY_CATALOG_ERROR`. Everything else verbatim.
- [ ] **Step 2: Verify**

Run: `python -m py_compile operators/library/publish_worker.py operators/library/delete_worker.py operators/library/catalog_worker.py`
Run: `grep -n "^from \.\|^import \.\|from \.\." operators/library/publish_worker.py operators/library/delete_worker.py operators/library/catalog_worker.py` — expected: no output (no relative imports).

- [ ] **Step 3: Commit**

```bash
git add operators/library/*_worker.py
git commit -m "feat(library): background worker scripts"
```

---

### Task 4: Refresh + Find Master operators

**Files:**
- Create: `operators/library/library_refresh.py`

**Interfaces:**
- Consumes: `common.get_prefs`, `common.find_master_file`, `common.sync_catalog`, `common.refresh_library_browsers`.
- Produces: `IOPS_OT_LibraryFindMaster` (bl_idname `iops.library_find_master`), `IOPS_OT_LibraryRefresh` (bl_idname `iops.library_refresh`).

- [ ] **Step 1: Port** SRC 614-641 (`FLT_KB_OT_find_master`) and 644-658 (`FLT_KB_OT_refresh_catalog`) with the rename table. `find_master` writes `prefs.library_master_file`; status prop is `iops_library_status`; both call `refresh_library_browsers()` where SRC called `refresh_asset_browsers(context)` (refresh-count message adaptations per Task 2 note).
- [ ] **Step 2: Verify** `python -m py_compile operators/library/library_refresh.py`
- [ ] **Step 3: Commit** — `git add`, `git commit -m "feat(library): refresh and find-master operators"`

---

### Task 5: Insert operator + dispatch helpers

**Files:**
- Create: `operators/library/library_insert.py`

**Interfaces:**
- Consumes: `common.get_catalog`, `common.get_prefs`, `common.sync_catalog`, `common.refresh_library_browsers`, `common.collection_root_object`, `common.DATA_OBJECT_TYPES`, `common.abs_path`.
- Produces: `IOPS_OT_LibraryInsertAsset` (bl_idname `iops.library_insert_asset`, IntProperty `index`), plus module functions `append_and_use_asset(context, entry)` and the dispatch chain (names as in SRC).

- [ ] **Step 1: Port** SRC 661-782 (append + all `insert_*`/`assign_*`/`use_catalog_datablock` helpers) and SRC 785-817 (the operator), with:
  - `append_catalog_datablock` version gate:

```python
    load_kwargs = {"link": False, "assets_only": True}
    if bpy.app.version >= (4, 0, 0):
        load_kwargs["clear_asset_data"] = True
    with bpy.data.libraries.load(abs_path(entry.library_path), **load_kwargs) as (data_from, data_to):
```

  - Placement reads `context.window_manager.iops_library_placement`.
  - The operator indexes into `get_catalog(context)` instead of `preferences.popup_assets`; the missing-asset branch calls `sync_catalog(context)` + `refresh_library_browsers()` as SRC does.
- [ ] **Step 2: Verify** `python -m py_compile operators/library/library_insert.py`
- [ ] **Step 3: Commit** — `git commit -m "feat(library): insert operator with per-type dispatch"`

---

### Task 6: Remove operator

**Files:**
- Create: `operators/library/library_remove.py`

**Interfaces:**
- Consumes: `common` (catalog, prefs, master, `worker_creation_flags`, `refresh_library_browsers`, `abs_path`), `library_core.result_data`/`log_tail`/`valid_master_file`, in-process `from . import delete_worker`.
- Produces: `IOPS_OT_LibraryRemoveAsset` (bl_idname `iops.library_remove_asset`; EnumProperty `mode` DELETE_ONE/CLEAN_UNLINKED; props `index`, `asset_name`, `asset_id_type`, `asset_data_collection`, `asset_library_path` as in SRC).

- [ ] **Step 1: Port** SRC 820-1020 with the rename table. Catalog lookups via `get_catalog(context)`; busy/status props renamed; worker command uses `os.path.join(os.path.dirname(__file__), "delete_worker.py")`; temp prefix `iops_library_delete_`; poll gate reads `iops_library_busy`.
- [ ] **Step 2: Verify** `python -m py_compile operators/library/library_remove.py`
- [ ] **Step 3: Commit** — `git commit -m "feat(library): remove-from-master operator"`

---

### Task 7: Publish operator

**Files:**
- Create: `operators/library/library_publish.py`

**Interfaces:**
- Consumes: `common` (prefs, master resolution, `object_hierarchy`, `sync_catalog`, `refresh_library_browsers`, `worker_creation_flags`, `abs_path`), `library_core` (`valid_master_file`, `result_data`, `log_tail`).
- Produces: `IOPS_OT_LibraryPublish` (bl_idname `iops.library_publish`; EnumProperty `publish_kind` OBJECT/COLLECTION/MATERIAL/SHADER_GROUP).

- [ ] **Step 1: Port** SRC 1527-1781 with the rename table. Shader-group source reads `prefs.library_shader_group`; temp prefix `iops_library_publish_` (per-worker-suffixed, consistent with `iops_library_delete_` and `iops_library_catalog_`); worker path `publish_worker.py` beside this file; busy/status props renamed; master-file guard messages keep their meaning with "IOPS Library" wording.
- [ ] **Step 2: Verify** `python -m py_compile operators/library/library_publish.py`
- [ ] **Step 3: Commit** — `git commit -m "feat(library): publish operator with background worker"`

---

### Task 8: GPU popup operator

**Files:**
- Create: `operators/library/library_popup.py`

**Interfaces:**
- Consumes: `common` (`get_catalog`, `get_prefs`, `sync_catalog`, `catalog_needs_sync`, `placement_from_mouse`, `overlay_texture`), `props.CATEGORY_DEFINITIONS`.
- Produces: `IOPS_OT_LibraryPopup` (bl_idname `iops.library_popup`), module function `shutdown()` that finishes the active popup instance if any (for addon unregister), module global `active_popup_operator`.

- [ ] **Step 1: Port** SRC 72-78 (`PREVIEW_GRID_WIDTH`, `preview_column_count`), 1023-1052 (`draw_overlay_rectangle`, `draw_overlay_text`, `point_in_bounds`) and 1055-1524 (the operator) with:
  - Every `preferences.popup_assets` → `get_catalog(context)` (draw callback uses `bpy.context`); `preferences.preview_size` → `prefs.library_preview_size` via `get_prefs`; all WM props renamed; header title text "IOPS Library".
  - Click dispatch: ASSET → `bpy.ops.iops.library_insert_asset("EXEC_DEFAULT", index=value)`; REMOVE → `bpy.ops.iops.library_remove_asset("INVOKE_DEFAULT", mode="DELETE_ONE", index=value)`; REFRESH → `bpy.ops.iops.library_refresh("EXEC_DEFAULT")`.
  - Add at module level:

```python
def shutdown():
    global active_popup_operator
    if active_popup_operator is not None:
        active_popup_operator.finish()
        active_popup_operator = None
```

- [ ] **Step 2: Verify** `python -m py_compile operators/library/library_popup.py`
- [ ] **Step 3: Commit** — `git commit -m "feat(library): GPU popup grid operator"`

---

### Task 9: Panel, prefs, registration, headless smoke test

**Files:**
- Create: `ui/iops_library_panel.py`
- Create: `tests/smoke_register.py`
- Modify: `prefs/addon_preferences.py` (add 4 properties + one draw section)
- Modify: `__init__.py` (imports, `classes` tuple, `register()`/`unregister()`)

**Interfaces:**
- Consumes: all operator classes from Tasks 4-8, `props.register_wm_properties`/`unregister_wm_properties`, `common.reset_overlay_textures`, `library_popup.shutdown`.
- Produces: `IOPS_PT_Library` panel; registered addon.

- [ ] **Step 1: Panel** — port SRC 1784-1880 into `ui/iops_library_panel.py` as `IOPS_PT_Library`: `bl_space_type "VIEW_3D"`, `bl_region_type "UI"`, `bl_category "iOps"`, `bl_label "IOPS Library"`, `bl_options = {"DEFAULT_CLOSED"}`. Renames per table (prefs fields `library_master_file`/`library_preview_size`/`library_shader_group`; WM props `iops_library_busy`/`iops_library_status`; operator idnames `iops.library_*`). Drop the "Popup: Ctrl Alt Q" hotkey label lines (no keymap this phase); the synced-count label becomes `layout.label(text="%d synced asset(s)" % len(get_catalog(context)))` with `get_catalog` imported from `..operators.library.common`.
- [ ] **Step 2: Prefs** — in `prefs/addon_preferences.py` add to `IOPS_AddonPreferences` (next to the other property blocks):

```python
    library_master_file: StringProperty(
        name="Master Library File",
        description="Single Blender file that stores all published library assets",
        subtype="FILE_PATH",
        default="",
    )
    library_preview_size: IntProperty(
        name="Preview Size",
        description="Size of square asset previews in the library popup",
        default=5,
        min=3,
        max=8,
    )
    library_shader_group: StringProperty(
        name="Shader Group",
        description="Local shader node group to publish into the master library",
        default="",
    )
    show_section_library: BoolProperty(default=False)
```

Then add a "Library" section to the prefs `draw` following EXACTLY the structural pattern of the existing `show_section_*` sections in the same file (read two of them first; copy the box/row/toggle idiom): contents are `library_master_file` prop, a row with the `iops.library_find_master` and `iops.library_refresh` operators, the `iops.library_remove_asset` operator with `text="Clean Unlinked Assets"` and `mode = "CLEAN_UNLINKED"`, and the `library_preview_size` slider.
- [ ] **Step 3: Registration** — in `__init__.py`: import the six classes (5 operators + panel) in the thematically appropriate import block; append them to the `classes` tuple (order: operators, then panel, matching neighbors); in `register()` after `bpy.types.WindowManager.IOPS_AddonProperties` is set add:

```python
    from .operators.library import props as library_props
    library_props.register_wm_properties()
```

In `unregister()`, before class unregistration add (mirroring the guarded style used for widgets):

```python
    try:
        from .operators.library import library_popup as _library_popup
        from .operators.library import common as _library_common
        from .operators.library import props as _library_props
        _library_popup.shutdown()
        _library_common.reset_overlay_textures()
        _library_props.unregister_wm_properties()
    except Exception as e:
        print("IOPS: library unregister failed:", e)
```

- [ ] **Step 4: Smoke test script** — create `tests/smoke_register.py` (run inside Blender, NOT collected by pytest):

```python
"""Headless registration smoke test. Run via:
blender --background --factory-startup --python tests/smoke_register.py
with BLENDER_USER_SCRIPTS pointing at a scripts dir whose addons/
contains this repo as 'InteractionOps' (junction)."""
import bpy

bpy.ops.preferences.addon_enable(module="InteractionOps")
assert "InteractionOps" in bpy.context.preferences.addons, "addon not enabled"

for op_name in (
    "library_publish",
    "library_refresh",
    "library_find_master",
    "library_insert_asset",
    "library_remove_asset",
    "library_popup",
):
    assert hasattr(bpy.ops.iops, op_name), "missing operator: iops.%s" % op_name

prefs = bpy.context.preferences.addons["InteractionOps"].preferences
for prop_name in ("library_master_file", "library_preview_size", "library_shader_group"):
    assert hasattr(prefs, prop_name), "missing pref: %s" % prop_name

wm = bpy.context.window_manager
for prop_name in ("iops_library_status", "iops_library_busy", "iops_library_placement"):
    assert hasattr(wm, prop_name), "missing WM prop: %s" % prop_name

assert hasattr(bpy.types, "IOPS_PT_Library"), "panel not registered"

bpy.ops.preferences.addon_disable(module="InteractionOps")
print("SMOKE_OK")
```

- [ ] **Step 5: Run the smoke test** (PowerShell; repo root = this worktree):

```powershell
$scripts = "$env:TEMP\iops_smoke\scripts"
New-Item -ItemType Directory -Force "$scripts\addons" | Out-Null
if (Test-Path "$scripts\addons\InteractionOps") { (Get-Item "$scripts\addons\InteractionOps").Delete() }
New-Item -ItemType Junction -Path "$scripts\addons\InteractionOps" -Target (Get-Location).Path | Out-Null
$env:BLENDER_USER_SCRIPTS = $scripts
& "V:\SteamLibrary\steamapps\common\Blender\blender.exe" --background --factory-startup --python tests\smoke_register.py 2>&1 | Tee-Object -Variable out
if (($out -join "`n") -notmatch "SMOKE_OK" -or ($out -join "`n") -match "Traceback") { throw "smoke failed" }
```

Expected: output contains `SMOKE_OK`, no `Traceback`. If registration fails, fix and re-run before committing.
- [ ] **Step 6: Full pytest** — `python -m pytest tests/ -q`: only the pre-existing `test_polygon_match` failure allowed. Also `python -m py_compile` on all four touched/created files.
- [ ] **Step 7: Commit**

```bash
git add ui/iops_library_panel.py tests/smoke_register.py prefs/addon_preferences.py __init__.py
git commit -m "feat(library): panel, prefs section, registration + smoke test"
```
