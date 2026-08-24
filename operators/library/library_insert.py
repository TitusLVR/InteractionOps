"""Insert operator + per-type dispatch helpers for the ported library addon.

Appends a catalog asset's datablock from the master library and hands it off
to a type-specific "use" helper (link an object into the scene, assign a
material, wire a node group, etc.).
"""

import os

import bpy
from bpy.props import IntProperty

from .common import (
    DATA_OBJECT_TYPES,
    abs_path,
    collection_root_object,
    get_catalog,
    get_prefs,
    refresh_library_browsers,
    sync_catalog,
)


def append_catalog_datablock(entry):
    data_collection = entry.data_collection
    if not data_collection:
        raise RuntimeError("This catalog entry has no Blender data collection.")
    load_kwargs = {"link": False, "assets_only": True}
    if bpy.app.version >= (4, 0, 0):
        load_kwargs["clear_asset_data"] = True
    with bpy.data.libraries.load(abs_path(entry.library_path), **load_kwargs) as (
        data_from,
        data_to,
    ):
        available = getattr(data_from, data_collection, None)
        if available is None or entry.asset_name not in available:
            raise RuntimeError("The asset is no longer present in the master library.")
        setattr(data_to, data_collection, [entry.asset_name])
    loaded = list(getattr(data_to, data_collection))
    if not loaded or loaded[0] is None:
        raise RuntimeError("Blender could not append the asset datablock.")
    return loaded[0]


def select_inserted_objects(context, objects, active):
    for selected in context.selected_objects:
        selected.select_set(False)
    for obj in objects:
        obj.select_set(True)
    context.view_layer.objects.active = active


def insert_object_asset(context, obj):
    target_collection = context.collection or context.scene.collection
    if not obj.users_collection:
        target_collection.objects.link(obj)
    obj.location = context.window_manager.iops_library_placement
    select_inserted_objects(context, [obj], obj)
    return "Inserted editable object %s" % obj.name


def insert_collection_asset(context, collection):
    target_collection = context.collection or context.scene.collection
    if target_collection.children.get(collection.name) is None:
        target_collection.children.link(collection)
    objects = list(collection.all_objects)
    root = collection_root_object(collection)
    if root is None:
        return "Appended empty collection %s" % collection.name
    root.location = context.window_manager.iops_library_placement
    select_inserted_objects(context, objects, root)
    return "Inserted editable collection %s (%d object(s))" % (
        collection.name,
        len(objects),
    )


def insert_data_object(context, data_block):
    obj = bpy.data.objects.new(data_block.name, data_block)
    target_collection = context.collection or context.scene.collection
    target_collection.objects.link(obj)
    obj.location = context.window_manager.iops_library_placement
    select_inserted_objects(context, [obj], obj)
    return "Created object %s from %s asset" % (obj.name, data_block.id_type)


def assign_material_asset(context, material):
    obj = context.active_object
    if obj is None or not hasattr(getattr(obj, "data", None), "materials"):
        return "Appended material %s; select a material-capable object to assign it" % material.name
    if obj.material_slots and obj.active_material_index < len(obj.material_slots):
        obj.material_slots[obj.active_material_index].material = material
    else:
        obj.data.materials.append(material)
    return "Assigned material %s to %s" % (material.name, obj.name)


def insert_node_group_asset(context, node_group):
    obj = context.active_object
    if node_group.bl_idname == "GeometryNodeTree" and obj is not None:
        modifier = obj.modifiers.new(node_group.name, "NODES")
        modifier.node_group = node_group
        return "Added Geometry Nodes modifier %s to %s" % (node_group.name, obj.name)

    if node_group.bl_idname == "ShaderNodeTree" and obj is not None:
        material = obj.active_material
        if material is not None:
            material.use_nodes = True
            group_node = material.node_tree.nodes.new("ShaderNodeGroup")
            group_node.node_tree = node_group
            group_node.location = (-300.0, 0.0)
            return "Added shader group %s to %s" % (node_group.name, material.name)
    return "Appended node group %s" % node_group.name


def use_catalog_datablock(context, entry, data_block):
    if entry.id_type == "OBJECT":
        return insert_object_asset(context, data_block)
    if entry.id_type == "COLLECTION":
        return insert_collection_asset(context, data_block)
    if entry.id_type == "MATERIAL":
        return assign_material_asset(context, data_block)
    if entry.id_type == "NODETREE":
        return insert_node_group_asset(context, data_block)
    if entry.id_type == "WORLD":
        context.scene.world = data_block
        return "Set scene world to %s" % data_block.name
    if entry.id_type == "ACTION" and context.active_object is not None:
        if context.active_object.animation_data is None:
            context.active_object.animation_data_create()
        context.active_object.animation_data.action = data_block
        return "Assigned action %s to %s" % (
            data_block.name,
            context.active_object.name,
        )
    if entry.id_type in DATA_OBJECT_TYPES:
        return insert_data_object(context, data_block)
    return "Appended %s asset %s" % (entry.id_type.title(), data_block.name)


def append_and_use_asset(context, entry):
    library_path = abs_path(entry.library_path)
    if not os.path.isfile(library_path):
        raise RuntimeError("The asset library file no longer exists.")
    data_block = append_catalog_datablock(entry)
    return use_catalog_datablock(context, entry, data_block)


class IOPS_OT_LibraryInsertAsset(bpy.types.Operator):
    """Append and use this asset in the current file."""

    bl_idname = "iops.library_insert_asset"
    bl_label = "Use Library Asset"
    bl_description = "Append and use this asset in the current file"
    bl_options = {"REGISTER", "UNDO"}

    index: IntProperty(default=-1, options={"HIDDEN"})

    def execute(self, context):
        preferences = get_prefs(context)
        if preferences is None:
            return {"CANCELLED"}

        catalog = get_catalog(context)
        if self.index < 0 or self.index >= len(catalog):
            self.report({"ERROR"}, "Popup asset assignment no longer exists.")
            return {"CANCELLED"}

        entry = catalog[self.index]
        try:
            message = append_and_use_asset(context, entry)
        except (OSError, RuntimeError, TypeError, ValueError) as error:
            if "no longer present in the master library" in str(error):
                sync_catalog(context)
                refresh_library_browsers()
                message = "Removed the missing asset from the popup."
                context.window_manager.iops_library_status = message
                self.report({"WARNING"}, message)
                return {"CANCELLED"}
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}

        context.window_manager.iops_library_status = message
        self.report({"INFO"}, message)
        return {"FINISHED"}
