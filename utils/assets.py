import bpy
import os
import uuid as _uuid_mod

CATALOG_FILENAME = "blender_assets.cats.txt"

CATALOG_FILE_HEADER = (
    "# This is an Asset Catalog Definition file for Blender.\n"
    "#\n"
    "# Empty lines and lines starting with `#` will be ignored.\n"
    "# The first non-ignored line should be the version indicator.\n"
    '# Other lines are of the format "UUID:catalog/path/for/assets:Simple Catalog Name"\n'
    "\n"
    "VERSION 1\n"
    "\n"
)


# ---- catalog file discovery ------------------------------------------------

def _catalog_filepath(directory):
    return os.path.join(directory, CATALOG_FILENAME)


def find_catalog_file(start_directory):
    """Walk up from *start_directory* until a blender_assets.cats.txt is found."""
    current = os.path.normpath(start_directory)
    while True:
        path = _catalog_filepath(current)
        if os.path.isfile(path):
            return path
        parent = os.path.dirname(current)
        if parent == current:
            break
        current = parent
    return None


# ---- parsing / writing -----------------------------------------------------

def parse_catalog_file(filepath):
    """Return list of ``{"uuid", "path", "simple_name"}`` dicts from a catalog file."""
    catalogs = []
    if not filepath or not os.path.isfile(filepath):
        return catalogs
    with open(filepath, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or line.upper().startswith("VERSION"):
                continue
            parts = line.split(":", 2)
            if len(parts) >= 2:
                catalogs.append({
                    "uuid": parts[0],
                    "path": parts[1],
                    "simple_name": parts[2] if len(parts) > 2 else parts[1].rsplit("/", 1)[-1],
                })
    return catalogs


def _ensure_catalog_file(filepath):
    """Create the catalog file with the standard header if it does not exist."""
    if os.path.isfile(filepath):
        return
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with open(filepath, "w", encoding="utf-8") as fh:
        fh.write(CATALOG_FILE_HEADER)


def create_catalog(catalog_file, catalog_path, simple_name=None):
    """Append a new catalog entry.  Returns ``(ok, message, uuid_str)``."""
    catalog_path = catalog_path.strip().strip("/")
    if not catalog_path:
        return False, "Catalog path cannot be empty", None

    if simple_name is None:
        simple_name = catalog_path.rsplit("/", 1)[-1]

    existing = parse_catalog_file(catalog_file)
    for cat in existing:
        if cat["path"] == catalog_path:
            return False, f"Catalog '{catalog_path}' already exists", None

    new_uuid = str(_uuid_mod.uuid4())
    _ensure_catalog_file(catalog_file)
    with open(catalog_file, "a", encoding="utf-8") as fh:
        fh.write(f"{new_uuid}:{catalog_path}:{simple_name}\n")

    return True, f"Created catalog '{catalog_path}'", new_uuid


def delete_catalog(catalog_file, catalog_uuid):
    """Remove a catalog entry by UUID.  Returns ``(ok, message)``."""
    if not catalog_file or not os.path.isfile(catalog_file):
        return False, "Catalog file not found"

    lines = []
    found = False
    deleted_path = ""

    with open(catalog_file, "r", encoding="utf-8") as fh:
        for line in fh:
            stripped = line.strip()
            if stripped and not stripped.startswith("#") and not stripped.upper().startswith("VERSION"):
                parts = stripped.split(":", 2)
                if parts[0] == catalog_uuid:
                    found = True
                    deleted_path = parts[1] if len(parts) > 1 else ""
                    continue
            lines.append(line)

    if not found:
        return False, "Catalog not found"

    with open(catalog_file, "w", encoding="utf-8") as fh:
        fh.writelines(lines)

    return True, f"Deleted catalog '{deleted_path}'"


# ---- querying catalogs -----------------------------------------------------

def get_current_file_catalog_info():
    """Return ``(catalog_file_path, catalogs_list)`` for the current blend file.

    *catalog_file_path* points to an existing file or to the location where one
    would be created.  Returns ``(None, [])`` when the file has not been saved.
    """
    if not bpy.data.filepath:
        return None, []
    blend_dir = os.path.dirname(bpy.data.filepath)
    found = find_catalog_file(blend_dir)
    if found:
        return found, parse_catalog_file(found)
    return _catalog_filepath(blend_dir), []


def get_catalog_source_by_path(library_path):
    """Return ``(source_name, catalog_file, catalogs)`` for a specific library
    path, or for the current file when *library_path* is empty."""
    if not library_path:
        cat_file, cats = get_current_file_catalog_info()
        return ("Current File", cat_file, cats) if cat_file else (None, None, [])

    for lib in bpy.context.preferences.filepaths.asset_libraries:
        lp = os.path.normpath(lib.path)
        if lp == os.path.normpath(library_path):
            cat_file = _catalog_filepath(lp)
            cats = parse_catalog_file(cat_file)
            return (lib.name, cat_file, cats)

    return (None, None, [])


# ---- asset helpers ----------------------------------------------------------

def assign_catalog(datablock, catalog_uuid):
    """Set the catalog on *datablock* (which must already be an asset).
    Returns ``(ok, message)``."""
    ad = getattr(datablock, "asset_data", None)
    if ad is None:
        return False, f"'{datablock.name}' is not marked as an asset"
    ad.catalog_id = catalog_uuid
    return True, f"Assigned '{datablock.name}' to catalog"


def resolve_assets_from_selection(context):
    """Find all asset data blocks related to the current selection.

    For each selected object checks:
    - The object itself (``obj.asset_data``)
    - Collections it belongs to (``collection.asset_data``)
    - Materials assigned to the object (``material.asset_data``)
    - Geometry Nodes modifiers whose node group has ``asset_data``
    - Images used in material node trees whose image has ``asset_data``

    Returns a deduplicated list of ``(datablock, type_label)`` tuples.
    """
    seen = set()
    results = []

    def _add(db, label):
        if id(db) not in seen:
            seen.add(id(db))
            results.append((db, label))

    for obj in (context.selected_objects or []):
        if getattr(obj, "asset_data", None) is not None:
            _add(obj, "Object")

        for coll in obj.users_collection:
            if getattr(coll, "asset_data", None) is not None:
                _add(coll, "Collection")

        obj_data = getattr(obj, "data", None)
        if obj_data is not None and hasattr(obj_data, "materials"):
            for mat in obj_data.materials:
                if mat and getattr(mat, "asset_data", None) is not None:
                    _add(mat, "Material")
                if mat and getattr(mat, "use_nodes", False) and mat.node_tree:
                    for node in mat.node_tree.nodes:
                        if node.type == "TEX_IMAGE" and node.image:
                            if getattr(node.image, "asset_data", None) is not None:
                                _add(node.image, "Image")

        for mod in obj.modifiers:
            if mod.type == "NODES":
                ng = getattr(mod, "node_group", None)
                if ng and getattr(ng, "asset_data", None) is not None:
                    _add(ng, "Geometry Nodes")

    return results


def iter_all_asset_datablocks():
    """Yield every datablock in the file that is marked as an asset."""
    for collection in (
        bpy.data.objects,
        bpy.data.collections,
        bpy.data.materials,
        bpy.data.images,
        bpy.data.node_groups,
        bpy.data.worlds,
        bpy.data.actions,
    ):
        for db in collection:
            if getattr(db, "asset_data", None) is not None:
                yield db


def get_active_image(context):
    """Best-effort lookup for the active image from various editors."""
    space = getattr(context, "space_data", None)
    if space and hasattr(space, "image") and space.image:
        return space.image

    obj = context.active_object
    if obj is None:
        return None

    if obj.type == "MESH" and obj.active_material:
        mat = obj.active_material
        if mat.use_nodes and mat.node_tree:
            for node in mat.node_tree.nodes:
                if node.type == "TEX_IMAGE" and node.select and node.image:
                    return node.image
            for node in mat.node_tree.nodes:
                if node.type == "TEX_IMAGE" and node.image:
                    return node.image
    return None


# ---- Asset Browser helpers --------------------------------------------------

def find_asset_browser_space():
    """Return the SpaceAssetInfo of the first open Asset Browser, or *None*."""
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            if area.ui_type == "ASSETS":
                return area.spaces.active
    return None


def tag_redraw_asset_browsers():
    """Tag every open Asset Browser area for redraw."""
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            if area.ui_type == "ASSETS":
                area.tag_redraw()


def refresh_asset_browser():
    """Refresh every open Asset Browser via temp_override + INVOKE_DEFAULT."""
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            if area.ui_type != "ASSETS":
                continue
            region = next(
                (r for r in area.regions if r.type == "WINDOW"), None
            )
            if region is None:
                continue
            try:
                with bpy.context.temp_override(
                    window=window, area=area, region=region
                ):
                    bpy.ops.asset.library_refresh('INVOKE_DEFAULT')
            except RuntimeError:
                pass
            area.tag_redraw()
