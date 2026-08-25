"""bpy-aware glue for the ported library addon.

Everything here bridges the pure helpers in ``utils.library_core`` to a live
Blender session: addon-prefs access, path normalization via
``bpy.path.abspath``, the on-disk JSON catalog cache, the overlay texture
cache used by the (later) popup draw code, and small context/event helpers.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile

import bpy
import gpu
from bpy_extras import view3d_utils

from ...utils.assets import refresh_asset_browser
from ...utils.library_core import (
    CatalogEntry,
    catalog_is_stale,
    find_master_in_entries,
    load_catalog_file,
    normalize_path,
    result_data,
    save_catalog_file,
    valid_master_file,
)

DATA_OBJECT_TYPES = {
    "ARMATURE",
    "CAMERA",
    "CURVE",
    "CURVES",
    "GREASEPENCIL",
    "LATTICE",
    "LIGHT",
    "MESH",
    "META",
    "POINTCLOUD",
    "SPEAKER",
    "VOLUME",
}

ROOT_OBJECT_PROPERTY = "iops_library_root"
LEGACY_ROOT_OBJECT_PROPERTY = "frontline_kitbash_root"

# In-session catalog state. Lazily populated by `get_catalog()` and kept in
# sync by `sync_catalog()`.
_catalog = []
_catalog_mtime = 0.0
_catalog_size = 0
_catalog_loaded = False

overlay_textures = {}
overlay_images = {}
overlay_owned_images = []


def get_prefs(context=None):
    context = context or bpy.context
    try:
        return context.preferences.addons["InteractionOps"].preferences
    except KeyError:
        return None


def abs_path(value):
    if not value:
        return ""
    return normalize_path(bpy.path.abspath(value))


def configured_master_file(context):
    preferences = get_prefs(context)
    if preferences is None:
        return ""
    return abs_path(preferences.library_master_file)


def asset_library_entries(context):
    entries = []
    libraries = context.preferences.filepaths.asset_libraries
    for library in libraries:
        path = abs_path(library.path)
        if path and os.path.isdir(path):
            entries.append((library.name, path))
    return entries


def find_master_file(context):
    return find_master_in_entries(asset_library_entries(context))


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


def catalog_json_path(master_file):
    return os.path.join(cache_directory(master_file), "catalog.json")


def get_catalog(context):
    global _catalog, _catalog_mtime, _catalog_size, _catalog_loaded

    if not _catalog_loaded:
        master_file = configured_master_file(context)
        if valid_master_file(master_file):
            data = load_catalog_file(catalog_json_path(master_file))
            _catalog = data["assets"]
            _catalog_mtime = data["master_mtime"]
            _catalog_size = data["master_size"]
        else:
            _catalog = []
        _catalog_loaded = True

    return _catalog


def worker_creation_flags():
    return subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0


def catalog_worker_command(master_file, result_file):
    worker_file = os.path.join(os.path.dirname(__file__), "catalog_worker.py")
    return [
        bpy.app.binary_path,
        "--background",
        "--factory-startup",
        "--disable-autoexec",
        master_file,
        "--python",
        worker_file,
        "--",
        cache_directory(master_file),
        result_file,
    ]


def run_catalog_worker(master_file):
    temporary_directory = tempfile.mkdtemp(prefix="iops_library_catalog_")
    result_file = os.path.join(temporary_directory, "catalog.json")
    command = catalog_worker_command(master_file, result_file)
    completed = subprocess.run(
        command,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.STDOUT,
        creationflags=worker_creation_flags(),
        timeout=120,
        check=False,
    )
    data = result_data(result_file)
    shutil.rmtree(temporary_directory, ignore_errors=True)
    if completed.returncode != 0 or not data.get("ok"):
        return None
    return data


def resolve_master_for_sync(context):
    """Resolve the master library file the same way ``sync_catalog`` does,
    without running the worker. Shared by the refresh operator's ``invoke``
    so it can validate before spawning the background process."""
    preferences = get_prefs(context)
    if preferences is None:
        return "", "IOPS Library preferences are unavailable."

    master_file = configured_master_file(context)
    if not valid_master_file(master_file):
        master_file = find_master_file(context)
        if master_file:
            preferences.library_master_file = master_file
    if not valid_master_file(master_file):
        return "", "Set or find the master library file first."
    return master_file, ""


def apply_catalog_result(context, master_file, data, report_status=True):
    """Apply a completed catalog-worker result to the in-session catalog
    state. Everything ``sync_catalog`` used to do after the worker returned,
    extracted so the modal refresh operator can call it once its background
    process exits."""
    global _catalog, _catalog_mtime, _catalog_size, _catalog_loaded

    # Collect previous thumbnail paths BEFORE the module-level catalog is
    # replaced, so stale PNGs can be cleaned up below.
    previous_thumbnails = {
        abs_path(entry.thumbnail_path)
        for entry in get_catalog(context)
        if entry.thumbnail_path
    }

    entries = [
        CatalogEntry(
            asset_name=item.get("asset_name", ""),
            library_path=master_file,
            id_type=item.get("id_type", "OBJECT"),
            data_collection=item.get("data_collection", "objects"),
            subtype=item.get("subtype", ""),
            category=item.get("category", "MISC"),
            thumbnail_path=item.get("thumbnail_path", ""),
        )
        for item in data.get("assets", [])
    ]

    master_mtime = data.get("master_mtime", os.path.getmtime(master_file))
    master_size = data.get("master_size", os.path.getsize(master_file))

    save_catalog_file(
        catalog_json_path(master_file),
        master_file,
        master_mtime,
        master_size,
        entries,
    )

    _catalog = entries
    _catalog_mtime = master_mtime
    _catalog_size = master_size
    _catalog_loaded = True

    reset_overlay_textures()

    current_thumbnails = {
        abs_path(entry.thumbnail_path)
        for entry in entries
        if entry.thumbnail_path
    }
    for filepath in previous_thumbnails - current_thumbnails:
        try:
            os.remove(filepath)
        except OSError:
            pass

    message = "Synced %d asset(s) from %s" % (
        len(entries),
        os.path.basename(master_file),
    )
    if report_status:
        context.window_manager.iops_library_status = message
    return True, message


def upsert_catalog_entry(context, master_file, entry_data):
    """Fold a just-published asset straight into the in-session catalog so
    it is available in the popup without a full re-sync. ``entry_data`` is
    the ``publish_worker`` result's ``entry`` dict."""
    global _catalog, _catalog_mtime, _catalog_size, _catalog_loaded

    entry = CatalogEntry(
        asset_name=entry_data.get("asset_name", ""),
        library_path=master_file,
        id_type=entry_data.get("id_type", "OBJECT"),
        data_collection=entry_data.get("data_collection", "objects"),
        subtype=entry_data.get("subtype", ""),
        category=entry_data.get("category", "MISC"),
        thumbnail_path=entry_data.get("thumbnail_path", ""),
    )

    catalog = get_catalog(context)
    replaced = False
    for index, existing in enumerate(catalog):
        if existing.asset_name == entry.asset_name and existing.id_type == entry.id_type:
            catalog[index] = entry
            replaced = True
            break
    if not replaced:
        catalog.append(entry)

    master_mtime = _catalog_mtime
    master_size = _catalog_size
    try:
        stat = os.stat(master_file)
    except OSError:
        pass
    else:
        master_mtime = stat.st_mtime
        master_size = stat.st_size
        _catalog_mtime = master_mtime
        _catalog_size = master_size

    _catalog = catalog
    _catalog_loaded = True

    save_catalog_file(
        catalog_json_path(master_file),
        master_file,
        master_mtime,
        master_size,
        _catalog,
    )

    reset_overlay_textures()

    return entry


def remove_catalog_entry(master_file, asset_name, id_type):
    """Pop a single entry out of the in-session catalog after a background
    delete job confirms removal, mirroring ``upsert_catalog_entry`` so a
    single deletion doesn't need a full re-sync. Returns False if no
    matching entry was found (nothing to do)."""
    global _catalog, _catalog_mtime, _catalog_size, _catalog_loaded

    catalog = get_catalog(bpy.context)
    remaining = [
        entry
        for entry in catalog
        if not (entry.asset_name == asset_name and entry.id_type == id_type)
    ]
    if len(remaining) == len(catalog):
        return False

    master_mtime = _catalog_mtime
    master_size = _catalog_size
    try:
        stat = os.stat(master_file)
    except OSError:
        pass
    else:
        master_mtime = stat.st_mtime
        master_size = stat.st_size
        _catalog_mtime = master_mtime
        _catalog_size = master_size

    _catalog = remaining
    _catalog_loaded = True

    save_catalog_file(
        catalog_json_path(master_file),
        master_file,
        master_mtime,
        master_size,
        _catalog,
    )

    reset_overlay_textures()
    return True


def sync_catalog(context, report_status=True):
    master_file, error = resolve_master_for_sync(context)
    if not master_file:
        return False, error

    data = run_catalog_worker(master_file)
    if data is None:
        return False, "The master library catalog could not be read."

    return apply_catalog_result(context, master_file, data, report_status=report_status)


def catalog_needs_sync(context):
    preferences = get_prefs(context)
    if preferences is None:
        return False
    master_file = configured_master_file(context)
    if not valid_master_file(master_file):
        return not get_catalog(context)
    try:
        stat = os.stat(master_file)
    except OSError:
        return False
    # Force the lazy load first: on a cold session `_catalog_mtime`/
    # `_catalog_size` are still their 0-valued defaults until `get_catalog`
    # populates them from catalog.json, so it must run before they're read.
    has_catalog = bool(get_catalog(context))
    return catalog_is_stale(stat, _catalog_mtime, _catalog_size, has_catalog)


def refresh_library_browsers():
    refresh_asset_browser()


def placement_from_mouse(context, event):
    fallback = context.scene.cursor.location.copy()
    if (
        context.area is None
        or context.area.type != "VIEW_3D"
        or context.region is None
        or context.region.type != "WINDOW"
        or context.region_data is None
    ):
        return fallback

    coordinate = (event.mouse_region_x, event.mouse_region_y)
    origin = view3d_utils.region_2d_to_origin_3d(
        context.region,
        context.region_data,
        coordinate,
    )
    direction = view3d_utils.region_2d_to_vector_3d(
        context.region,
        context.region_data,
        coordinate,
    )
    hit, location, _normal, _face, _obj, _matrix = context.scene.ray_cast(
        context.evaluated_depsgraph_get(),
        origin,
        direction,
        distance=1.0e6,
    )
    return location if hit else fallback


def object_hierarchy(root):
    objects = []

    def visit(obj):
        objects.append(obj)
        for child in obj.children:
            visit(child)

    visit(root)
    return objects


def collection_root_object(collection):
    objects = list(collection.all_objects)
    for obj in objects:
        if obj.get(ROOT_OBJECT_PROPERTY, obj.get(LEGACY_ROOT_OBJECT_PROPERTY)):
            return obj

    object_set = set(objects)
    for obj in objects:
        if obj.parent not in object_set:
            return obj
    return objects[0] if objects else None


def reset_overlay_textures():
    overlay_textures.clear()
    overlay_images.clear()
    for image in list(overlay_owned_images):
        try:
            if image.users == 0:
                bpy.data.images.remove(image)
        except ReferenceError:
            pass
    overlay_owned_images.clear()


def overlay_texture(entry):
    filepath = abs_path(entry.thumbnail_path)
    if not filepath or not os.path.isfile(filepath):
        return None
    texture = overlay_textures.get(filepath)
    if texture is not None:
        return texture

    known_images = {image.as_pointer() for image in bpy.data.images}
    image = bpy.data.images.load(filepath, check_existing=True)
    if image.as_pointer() not in known_images:
        overlay_owned_images.append(image)
    # Keep the PNG's display-referred values: with the default sRGB
    # colorspace, from_image() linearizes and the popup (drawn straight
    # into the display framebuffer) shows every thumbnail darkened.
    try:
        image.colorspace_settings.name = "Non-Color"
    except (AttributeError, TypeError):
        pass
    texture = gpu.texture.from_image(image)
    overlay_images[filepath] = image
    overlay_textures[filepath] = texture
    return texture
