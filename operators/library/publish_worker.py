import json
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


def apply_asset_metadata(data_block, asset_type):
    if data_block.asset_data is None:
        data_block.asset_mark()
    data_block.asset_data.author = "IOPS Library"
    data_block.asset_data.description = (
        "Published %s asset by IOPS Library" % asset_type.title()
    )
    data_block[PUBLISHED_PROPERTY] = True
    try:
        data_block.asset_generate_preview()
    except (AttributeError, RuntimeError, TypeError):
        pass


def center_root_at_world_origin(root):
    root.parent = None
    root.location = (0.0, 0.0, 0.0)


def publish_object(container, root):
    for collection in list(root.users_collection):
        collection.objects.unlink(root)
    container.objects.link(root)
    center_root_at_world_origin(root)
    root[OWNER_PROPERTY] = root.name
    root[ROOT_OBJECT_PROPERTY] = True
    apply_asset_metadata(root, "OBJECT")
    return root


def publish_hierarchy(container, root_name, loaded_by_name):
    collection = bpy.data.collections.new(root_name)
    container.children.link(collection)

    for obj in loaded_by_name.values():
        for user_collection in list(obj.users_collection):
            user_collection.objects.unlink(obj)
        collection.objects.link(obj)
        if obj.asset_data is not None:
            obj.asset_clear()
        obj[OWNER_PROPERTY] = root_name
        obj[ROOT_OBJECT_PROPERTY] = False

    root = loaded_by_name[root_name]
    center_root_at_world_origin(root)
    root[ROOT_OBJECT_PROPERTY] = True
    collection[ROOT_OBJECT_PROPERTY] = root_name
    apply_asset_metadata(collection, "COLLECTION")
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


def publish_collection(container, collection, root_name):
    if container.children.get(collection.name) is None:
        container.children.link(collection)
    center_collection(collection, root_name)
    apply_asset_metadata(collection, "COLLECTION")
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

    if source_mode == "OBJECT_HIERARCHY":
        object_names = manifest.get("object_names", [])
        root_name = manifest.get("root_name", asset_name)
        if not object_names or root_name not in object_names:
            raise RuntimeError("The hierarchy payload object list is invalid.")
        remove_existing_collection_asset(asset_name)
        remove_existing_object_asset(asset_name)
        loaded_by_name = append_datablocks(payload_file, "objects", object_names)
        if len(object_names) == 1:
            asset = publish_object(container, loaded_by_name[root_name])
            asset_type = "OBJECT"
        else:
            asset = publish_hierarchy(container, root_name, loaded_by_name)
            asset_type = "COLLECTION"
        object_count = len(object_names)
    elif source_mode == "COLLECTION":
        remove_existing_collection_asset(asset_name)
        remove_existing_object_asset(asset_name)
        loaded = append_datablocks(payload_file, "collections", [asset_name])
        asset = publish_collection(
            container,
            loaded[asset_name],
            manifest.get("root_name", ""),
        )
        asset_type = "COLLECTION"
        object_count = len(asset.all_objects)
    else:
        remove_existing_datablock(data_collection, asset_name)
        loaded = append_datablocks(payload_file, data_collection, [asset_name])
        asset = loaded[asset_name]
        apply_asset_metadata(asset, asset_type)
        object_count = 0

    master_file = bpy.data.filepath
    bpy.ops.wm.save_as_mainfile(filepath=master_file, check_existing=False)
    preview_size = (
        tuple(asset.preview.image_size)
        if asset.preview is not None
        else (0, 0)
    )
    return {
        "ok": True,
        "asset_name": asset.name,
        "asset_type": asset_type,
        "data_collection": data_collection,
        "source_mode": source_mode,
        "object_count": object_count,
        "master_file": master_file,
        "preview_size": preview_size,
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
