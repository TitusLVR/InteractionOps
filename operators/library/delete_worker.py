import json
import os
import sys
import traceback

import bpy


OWNER_PROPERTY = "iops_library_owner"
LEGACY_OWNER_PROPERTY = "frontline_kitbash_owner"


def command_arguments():
    try:
        separator = sys.argv.index("--")
    except ValueError as error:
        raise RuntimeError("Delete worker arguments are missing.") from error

    arguments = sys.argv[separator + 1 :]
    if len(arguments) != 2:
        raise RuntimeError("Expected manifest file and result file.")
    manifest_file, result_file = arguments
    with open(manifest_file, "r", encoding="utf-8") as handle:
        manifest = json.load(handle)
    if manifest.get("mode") not in {"DELETE_ONE", "CLEAN_UNLINKED"}:
        raise RuntimeError("Unsupported library removal mode.")
    return manifest, result_file


def write_result(filepath, data):
    directory = os.path.dirname(filepath)
    if directory:
        os.makedirs(directory, exist_ok=True)
    with open(filepath, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2)


def remove_objects(objects):
    object_data = []
    removed_names = []
    for obj in objects:
        if obj is None:
            continue
        removed_names.append(obj.name)
        if obj.data is not None:
            object_data.append(obj.data)
        if obj.asset_data is not None:
            obj.asset_clear()
        bpy.data.objects.remove(obj, do_unlink=True)

    orphaned_data = [data for data in object_data if data.users == 0]
    if orphaned_data:
        bpy.data.batch_remove(ids=orphaned_data)
    return removed_names


def remove_one(manifest):
    required = {"asset_name", "id_type", "data_collection"}
    if not required.issubset(manifest):
        raise RuntimeError("The asset removal manifest is incomplete.")

    name = manifest["asset_name"]
    data_collection = manifest["data_collection"]
    collection = getattr(bpy.data, data_collection, None)
    if collection is None:
        raise RuntimeError(
            "Unsupported Blender data collection '%s'." % data_collection
        )
    data_block = collection.get(name)
    if data_block is None or data_block.asset_data is None:
        return []

    if data_block.id_type == "OBJECT":
        return remove_objects([data_block])

    if data_block.id_type == "COLLECTION":
        owned_objects = [
            obj
            for obj in data_block.all_objects
            if obj.get(OWNER_PROPERTY, obj.get(LEGACY_OWNER_PROPERTY)) == data_block.name
        ]
        data_block.asset_clear()
        bpy.data.collections.remove(data_block, do_unlink=True)
        removed = [name]
        removed.extend(remove_objects(owned_objects))
        return removed

    data_block.asset_clear()
    collection.remove(data_block, do_unlink=True)
    return [name]


def clean_unlinked_object_assets():
    objects = [
        obj
        for obj in bpy.data.objects
        if obj.asset_data is not None and not obj.users_collection
    ]
    return remove_objects(objects)


def remove_assets(manifest):
    if not bpy.data.filepath:
        raise RuntimeError("The master library file is not open.")
    if manifest["mode"] == "DELETE_ONE":
        removed_names = remove_one(manifest)
    else:
        removed_names = clean_unlinked_object_assets()

    master_file = bpy.data.filepath
    if removed_names:
        bpy.ops.wm.save_as_mainfile(filepath=master_file, check_existing=False)
    return {
        "ok": True,
        "mode": manifest["mode"],
        "removed_names": removed_names,
        "removed_count": len(removed_names),
        "master_file": master_file,
    }


def main():
    result_file = ""
    try:
        manifest, result_file = command_arguments()
        result = remove_assets(manifest)
        write_result(result_file, result)
        print("IOPS_LIBRARY_DELETE", json.dumps(result))
    except Exception as error:
        result = {
            "ok": False,
            "error": str(error),
            "traceback": traceback.format_exc(),
        }
        if result_file:
            write_result(result_file, result)
        print("IOPS_LIBRARY_DELETE_ERROR", json.dumps(result))
        raise


if __name__ == "__main__":
    main()
