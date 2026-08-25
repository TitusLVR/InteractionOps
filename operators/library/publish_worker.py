import array
import hashlib
import json
import math
import os
import sys
import traceback

import bpy


ASSET_CONTAINER_NAME = "IOPS Library Assets"
LEGACY_ASSET_CONTAINER_NAMES = ("Frontline Library Assets", "Frontline Kitbash Assets")
PUBLISHED_PROPERTY = "iops_library_published"
OWNER_PROPERTY = "iops_library_owner"
LEGACY_OWNER_PROPERTY = "frontline_kitbash_owner"
ROOT_OBJECT_PROPERTY = "iops_library_root"

GEOMETRY_TYPES = {
    "ARMATURE",
    "COLLECTION",
    "CURVE",
    "CURVES",
    "GREASEPENCIL",
    "LATTICE",
    "MESH",
    "META",
    "POINTCLOUD",
    "VOLUME",
}


def cache_key(library_path, asset_name, id_type):
    value = "%s\0%s\0%s" % (
        os.path.normpath(os.path.abspath(library_path)),
        asset_name,
        id_type,
    )
    return hashlib.sha1(value.encode("utf-8")).hexdigest()


def crop_transparent_preview(preview, target_fill=0.9):
    width, height = preview.image_size
    pixels = list(preview.image_pixels_float)
    foreground = []
    for index in range(width * height):
        if pixels[index * 4 + 3] > 0.05:
            foreground.append((index % width, index // width))

    if not foreground or len(foreground) == width * height:
        return width, height, pixels

    minimum_x = min(point[0] for point in foreground)
    maximum_x = max(point[0] for point in foreground)
    minimum_y = min(point[1] for point in foreground)
    maximum_y = max(point[1] for point in foreground)
    content_size = max(
        maximum_x - minimum_x + 1,
        maximum_y - minimum_y + 1,
    )
    crop_size = min(
        min(width, height),
        max(content_size, int(math.ceil(content_size / target_fill))),
    )
    center_x = (minimum_x + maximum_x + 1) * 0.5
    center_y = (minimum_y + maximum_y + 1) * 0.5
    start_x = max(0, min(int(round(center_x - crop_size * 0.5)), width - crop_size))
    start_y = max(0, min(int(round(center_y - crop_size * 0.5)), height - crop_size))

    cropped = []
    for y in range(start_y, start_y + crop_size):
        row_start = (y * width + start_x) * 4
        row_end = row_start + crop_size * 4
        cropped.extend(pixels[row_start:row_end])
    return crop_size, crop_size, cropped


def save_preview(data_block, output_path):
    preview = data_block.preview
    if preview is None or not all(preview.image_size):
        return ""

    width, height, pixels = crop_transparent_preview(preview)
    image = bpy.data.images.new(
        "IOPS Library Catalog Thumbnail",
        width=width,
        height=height,
        alpha=True,
    )
    image.pixels.foreach_set(pixels)
    image.scale(256, 256)
    image.filepath_raw = output_path
    image.file_format = "PNG"
    image.save()
    bpy.data.images.remove(image)
    return output_path


def asset_subtype(data_block):
    if data_block.id_type == "OBJECT":
        return getattr(data_block, "type", "OBJECT")
    if data_block.id_type == "NODETREE":
        return getattr(data_block, "bl_idname", "NODETREE")
    return data_block.bl_rna.identifier


def asset_category(data_block, subtype):
    id_type = data_block.id_type
    if id_type == "OBJECT":
        if subtype == "LIGHT":
            return "LIGHTS"
        if subtype in {
            "ARMATURE",
            "CURVE",
            "CURVES",
            "EMPTY",
            "FONT",
            "GREASEPENCIL",
            "LATTICE",
            "MESH",
            "META",
            "POINTCLOUD",
            "SURFACE",
            "VOLUME",
        }:
            return "GEOMETRY"
    if id_type in GEOMETRY_TYPES:
        return "GEOMETRY"
    if id_type == "MATERIAL" or (
        id_type == "NODETREE" and subtype == "ShaderNodeTree"
    ):
        return "SHADERS"
    if id_type in {"LIGHT", "WORLD"}:
        return "LIGHTS"
    return "MISC"


def command_arguments():
    try:
        separator = sys.argv.index("--")
    except ValueError as error:
        raise RuntimeError("Worker arguments are missing.") from error

    arguments = sys.argv[separator + 1 :]
    if len(arguments) != 3:
        raise RuntimeError("Expected payload file, manifest file, and result file.")
    payload_file, manifest_file, result_file = arguments
    with open(manifest_file, "r", encoding="utf-8") as handle:
        manifest = json.load(handle)

    required = {"asset_name", "asset_type", "data_collection", "source_mode"}
    if not required.issubset(manifest):
        raise RuntimeError("The publish manifest is incomplete.")
    if manifest["source_mode"] not in {
        "OBJECT_HIERARCHY",
        "COLLECTION",
        "DATABLOCK",
    }:
        raise RuntimeError("Unsupported publish source mode.")
    return payload_file, manifest, result_file


def write_result(filepath, data):
    directory = os.path.dirname(filepath)
    if directory:
        os.makedirs(directory, exist_ok=True)
    with open(filepath, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2)


def ensure_asset_container():
    collection = bpy.data.collections.get(ASSET_CONTAINER_NAME)
    if collection is None:
        for legacy_name in LEGACY_ASSET_CONTAINER_NAMES:
            collection = bpy.data.collections.get(legacy_name)
            if collection is not None:
                break
    if collection is None:
        collection = bpy.data.collections.new(ASSET_CONTAINER_NAME)
    elif collection.name in LEGACY_ASSET_CONTAINER_NAMES:
        collection.name = ASSET_CONTAINER_NAME

    scene_root = bpy.context.scene.collection
    if scene_root.children.get(collection.name) is None:
        scene_root.children.link(collection)
    return collection


def remove_objects(objects):
    data_blocks = []
    for obj in objects:
        if obj is None:
            continue
        data = obj.data
        if obj.asset_data is not None:
            obj.asset_clear()
        bpy.data.objects.remove(obj, do_unlink=True)
        if data is not None:
            data_blocks.append(data)

    orphaned = [data for data in data_blocks if data.users == 0]
    if orphaned:
        bpy.data.batch_remove(ids=orphaned)


def remove_existing_object_asset(name):
    existing = bpy.data.objects.get(name)
    if existing is not None:
        remove_objects([existing])


def remove_existing_collection_asset(name):
    collection = bpy.data.collections.get(name)
    if collection is None or collection.name in {
        ASSET_CONTAINER_NAME,
        *LEGACY_ASSET_CONTAINER_NAMES,
    }:
        return

    owned_objects = [
        obj
        for obj in collection.all_objects
        if obj.get(OWNER_PROPERTY, obj.get(LEGACY_OWNER_PROPERTY)) == name
    ]
    if collection.asset_data is not None:
        collection.asset_clear()
    bpy.data.collections.remove(collection, do_unlink=True)
    remove_objects(owned_objects)


def remove_existing_datablock(data_collection, name):
    collection = getattr(bpy.data, data_collection, None)
    if collection is None:
        raise RuntimeError("Unsupported Blender data collection '%s'." % data_collection)
    existing = collection.get(name)
    if existing is None:
        return
    if existing.asset_data is not None:
        existing.asset_clear()
    collection.remove(existing, do_unlink=True)


def append_datablocks(payload_file, data_collection, names):
    requested_names = tuple(names)
    with bpy.data.libraries.load(payload_file, link=False) as (data_from, data_to):
        available = getattr(data_from, data_collection, None)
        if available is None:
            raise RuntimeError(
                "Payload does not support Blender data collection '%s'."
                % data_collection
            )
        missing = [name for name in requested_names if name not in available]
        if missing:
            raise RuntimeError("Payload item(s) missing: %s" % ", ".join(missing))
        setattr(data_to, data_collection, list(requested_names))

    loaded = list(getattr(data_to, data_collection))
    if len(loaded) != len(requested_names) or any(item is None for item in loaded):
        raise RuntimeError("Blender could not append the complete asset payload.")
    return dict(zip(requested_names, loaded))


def apply_asset_metadata(data_block, asset_type, skip_preview=False):
    if data_block.asset_data is None:
        data_block.asset_mark()
    data_block.asset_data.author = "IOPS Library"
    data_block.asset_data.description = (
        "Published %s asset by IOPS Library" % asset_type.title()
    )
    data_block[PUBLISHED_PROPERTY] = True
    if skip_preview:
        # A captured viewport thumbnail will be embedded in place of a
        # generated preview -- see publish()/embed_preview_from_png().
        return
    try:
        data_block.asset_generate_preview()
    except (AttributeError, RuntimeError, TypeError):
        pass


def embed_preview_from_png(data_block, filepath):
    """Load the PNG at *filepath* and write it into *data_block*'s ID
    preview so the master's embedded preview matches the captured
    thumbnail. Returns True on success, False on any failure (caller falls
    back to generating a preview normally)."""
    image = None
    try:
        image = bpy.data.images.load(filepath, check_existing=False)
        width, height = image.size
        if width <= 0 or height <= 0:
            return False

        pixel_buffer = array.array("f", [0.0]) * (width * height * 4)
        image.pixels.foreach_get(pixel_buffer)

        preview = data_block.preview_ensure()
        preview.image_size = (width, height)
        preview.image_pixels_float.foreach_set(pixel_buffer)
        return True
    except Exception as error:
        print("IOPS Library: embedding captured thumbnail failed:", error)
        return False
    finally:
        if image is not None:
            try:
                bpy.data.images.remove(image, do_unlink=True)
            except (RuntimeError, ReferenceError):
                pass


def center_root_at_world_origin(root):
    root.parent = None
    root.location = (0.0, 0.0, 0.0)


def publish_object(container, root, skip_preview=False):
    for collection in list(root.users_collection):
        collection.objects.unlink(root)
    container.objects.link(root)
    center_root_at_world_origin(root)
    root[OWNER_PROPERTY] = root.name
    root[ROOT_OBJECT_PROPERTY] = True
    apply_asset_metadata(root, "OBJECT", skip_preview=skip_preview)
    return root


def publish_hierarchy(container, asset_name, root_name, loaded_by_name, skip_preview=False):
    collection = bpy.data.collections.new(asset_name)
    container.children.link(collection)

    for obj in loaded_by_name.values():
        for user_collection in list(obj.users_collection):
            user_collection.objects.unlink(obj)
        collection.objects.link(obj)
        if obj.asset_data is not None:
            obj.asset_clear()
        obj[OWNER_PROPERTY] = collection.name
        obj[ROOT_OBJECT_PROPERTY] = False

    root = loaded_by_name[root_name]
    center_root_at_world_origin(root)
    root[ROOT_OBJECT_PROPERTY] = True
    collection[ROOT_OBJECT_PROPERTY] = root_name
    apply_asset_metadata(collection, "COLLECTION", skip_preview=skip_preview)
    return collection


def collection_root(collection, root_name):
    objects = list(collection.all_objects)
    root = next((obj for obj in objects if obj.name == root_name), None)
    if root is not None:
        return root
    object_set = set(objects)
    return next((obj for obj in objects if obj.parent not in object_set), None)


def center_collection(collection, root_name):
    objects = list(collection.all_objects)
    if not objects:
        return None
    object_set = set(objects)
    root = collection_root(collection, root_name)
    offset = root.location.copy() if root is not None else None
    if offset is not None:
        for obj in objects:
            if obj.parent not in object_set:
                obj.location -= offset
    for obj in objects:
        obj[OWNER_PROPERTY] = collection.name
        obj[ROOT_OBJECT_PROPERTY] = obj == root
    if root is not None:
        collection[ROOT_OBJECT_PROPERTY] = root.name
    return root


def publish_collection(container, collection, root_name, skip_preview=False):
    if container.children.get(collection.name) is None:
        container.children.link(collection)
    center_collection(collection, root_name)
    apply_asset_metadata(collection, "COLLECTION", skip_preview=skip_preview)
    return collection


def publish(payload_file, manifest):
    if not os.path.isfile(payload_file):
        raise RuntimeError("Payload file does not exist.")
    if not bpy.data.filepath:
        raise RuntimeError("The master library file is not open.")

    asset_name = manifest["asset_name"]
    asset_type = manifest["asset_type"]
    data_collection = manifest["data_collection"]
    source_mode = manifest["source_mode"]
    container = ensure_asset_container()
    thumbnail_provided = bool(manifest.get("thumbnail_provided"))

    if source_mode == "OBJECT_HIERARCHY":
        object_names = manifest.get("object_names", [])
        root_name = manifest.get("root_name", asset_name)
        if not object_names or root_name not in object_names:
            raise RuntimeError("The hierarchy payload object list is invalid.")
        remove_existing_collection_asset(asset_name)
        remove_existing_object_asset(asset_name)
        loaded_by_name = append_datablocks(payload_file, "objects", object_names)
        if len(object_names) == 1:
            root = loaded_by_name[root_name]
            if root.name != asset_name:
                root.name = asset_name
            asset = publish_object(container, root, skip_preview=thumbnail_provided)
            asset_type = "OBJECT"
        else:
            asset = publish_hierarchy(
                container, asset_name, root_name, loaded_by_name, skip_preview=thumbnail_provided
            )
            asset_type = "COLLECTION"
            data_collection = "collections"
        object_count = len(object_names)
    elif source_mode == "COLLECTION":
        remove_existing_collection_asset(asset_name)
        remove_existing_object_asset(asset_name)
        source_name = manifest.get("source_name", asset_name)
        loaded = append_datablocks(payload_file, "collections", [source_name])
        collection = loaded[source_name]
        if collection.name != asset_name:
            collection.name = asset_name
        asset = publish_collection(
            container,
            collection,
            manifest.get("root_name", ""),
            skip_preview=thumbnail_provided,
        )
        asset_type = "COLLECTION"
        object_count = len(asset.all_objects)
    else:
        remove_existing_datablock(data_collection, asset_name)
        source_name = manifest.get("source_name", asset_name)
        loaded = append_datablocks(payload_file, data_collection, [source_name])
        asset = loaded[source_name]
        if asset.name != asset_name:
            asset.name = asset_name
        apply_asset_metadata(asset, asset_type)
        object_count = 0

    master_file = bpy.data.filepath
    cache_dir = manifest.get("cache_directory", "")
    output_path = (
        os.path.join(cache_dir, "%s.png" % cache_key(master_file, asset.name, asset.id_type))
        if cache_dir
        else ""
    )

    # When the parent captured a viewport thumbnail, embed it as this
    # asset's ID preview instead of the generated preview that
    # apply_asset_metadata() skipped above. Any failure falls back to
    # generating a preview the normal way. Gated to the OBJECT_HIERARCHY /
    # COLLECTION branches -- a stray flag on a DATABLOCK publish is ignored.
    thumbnail_applicable = thumbnail_provided and source_mode in ("OBJECT_HIERARCHY", "COLLECTION")
    embedded_capture = False
    if thumbnail_applicable and output_path and os.path.isfile(output_path):
        embedded_capture = embed_preview_from_png(asset, output_path)
    if thumbnail_applicable and not embedded_capture:
        try:
            asset.asset_generate_preview()
        except (AttributeError, RuntimeError, TypeError):
            pass

    bpy.ops.wm.save_as_mainfile(filepath=master_file, check_existing=False)
    preview_size = (
        tuple(asset.preview.image_size)
        if asset.preview is not None
        else (0, 0)
    )

    if embedded_capture:
        # The capture PNG is already at output_path -- do not overwrite it
        # with a freshly cropped/scaled catalog thumbnail.
        thumbnail = output_path
    elif output_path:
        thumbnail = save_preview(asset, output_path)
    else:
        thumbnail = ""

    entry = {
        "asset_name": asset.name,
        "id_type": asset.id_type,
        "data_collection": data_collection,
        "subtype": asset_subtype(asset),
        "category": asset_category(asset, asset_subtype(asset)),
        "thumbnail_path": thumbnail,
    }

    return {
        "ok": True,
        "asset_name": asset.name,
        "asset_type": asset_type,
        "data_collection": data_collection,
        "source_mode": source_mode,
        "object_count": object_count,
        "master_file": master_file,
        "preview_size": preview_size,
        "entry": entry,
    }


def main():
    result_file = ""
    asset_name = ""
    asset_type = ""
    try:
        payload_file, manifest, result_file = command_arguments()
        asset_name = manifest["asset_name"]
        asset_type = manifest["asset_type"]
        result = publish(payload_file, manifest)
        write_result(result_file, result)
        print("IOPS_LIBRARY_RESULT", json.dumps(result))
    except Exception as error:
        result = {
            "ok": False,
            "asset_name": asset_name,
            "asset_type": asset_type,
            "error": str(error),
            "traceback": traceback.format_exc(),
        }
        if result_file:
            write_result(result_file, result)
        print("IOPS_LIBRARY_ERROR", json.dumps(result))
        raise


if __name__ == "__main__":
    main()
