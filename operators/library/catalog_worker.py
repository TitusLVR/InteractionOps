import hashlib
import json
import math
import os
import sys
import traceback

import bpy


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


def command_arguments():
    try:
        separator = sys.argv.index("--")
    except ValueError as error:
        raise RuntimeError("Catalog worker arguments are missing.") from error

    arguments = sys.argv[separator + 1 :]
    if len(arguments) != 2:
        raise RuntimeError("Expected thumbnail cache directory and result file.")
    return arguments


def write_result(filepath, data):
    directory = os.path.dirname(filepath)
    if directory:
        os.makedirs(directory, exist_ok=True)
    with open(filepath, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2)


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


def data_collection_lookup():
    lookup = {}
    for prop in bpy.data.bl_rna.properties:
        if prop.type != "COLLECTION" or prop.identifier == "all_ids":
            continue
        for data_block in getattr(bpy.data, prop.identifier, []):
            lookup[data_block.as_pointer()] = prop.identifier
    return lookup


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


def catalog_assets(cache_directory):
    master_file = os.path.normpath(os.path.abspath(bpy.data.filepath))
    collection_lookup = data_collection_lookup()
    entries = []
    seen = set()

    os.makedirs(cache_directory, exist_ok=True)
    for data_block in bpy.data.all_ids:
        if data_block.asset_data is None or data_block.library is not None:
            continue
        key = (data_block.id_type, data_block.name_full)
        if key in seen:
            continue
        seen.add(key)

        data_collection = collection_lookup.get(data_block.as_pointer(), "")
        if not data_collection:
            continue
        subtype = asset_subtype(data_block)
        output_path = os.path.join(
            cache_directory,
            "%s.png" % cache_key(master_file, data_block.name, data_block.id_type),
        )
        thumbnail = save_preview(data_block, output_path)
        entries.append(
            {
                "asset_name": data_block.name,
                "id_type": data_block.id_type,
                "data_collection": data_collection,
                "subtype": subtype,
                "category": asset_category(data_block, subtype),
                "thumbnail_path": thumbnail,
            }
        )

    category_order = {"GEOMETRY": 0, "SHADERS": 1, "LIGHTS": 2, "MISC": 3}
    entries.sort(
        key=lambda entry: (
            category_order.get(entry["category"], 99),
            entry["asset_name"].lower(),
            entry["id_type"],
        )
    )
    return entries


def main():
    result_file = ""
    try:
        cache_directory, result_file = command_arguments()
        entries = catalog_assets(cache_directory)
        result = {
            "ok": True,
            "master_file": bpy.data.filepath,
            "master_mtime": os.path.getmtime(bpy.data.filepath),
            "master_size": os.path.getsize(bpy.data.filepath),
            "assets": entries,
        }
        write_result(result_file, result)
        print("IOPS_LIBRARY_CATALOG", json.dumps(result))
    except Exception as error:
        result = {
            "ok": False,
            "error": str(error),
            "traceback": traceback.format_exc(),
        }
        if result_file:
            write_result(result_file, result)
        print("IOPS_LIBRARY_CATALOG_ERROR", json.dumps(result))
        raise


if __name__ == "__main__":
    main()
