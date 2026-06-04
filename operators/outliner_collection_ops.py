# Include/Exclude collections from view layer

import bpy


def exclude_layer_col_by_name(layerColl, collName, exclude):
    found = None
    if layerColl.name == collName:
        layerColl.exclude = exclude
        return layerColl
    for layer in layerColl.children:
        found = exclude_layer_col_by_name(layer, collName, exclude)
        if found:
            found.exclude = exclude
            return found


class IOPS_OT_Collections_Include(bpy.types.Operator):
    """Include collection and children in view layer"""

    bl_idname = "iops.collections_include"
    bl_label = "Include All"
    bl_description = "Include collection and children in view layer"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        selected_cols = [
            col
            for col in bpy.context.selected_ids
            if isinstance(col, bpy.types.Collection)
        ]
        selected_cols_children = []

        # Get all children from selected_cols withoud duplicates
        for col in selected_cols:
            for child in col.children_recursive:
                if child not in selected_cols_children:
                    selected_cols_children.append(child)

        all_colls = selected_cols + selected_cols_children

        master_col = bpy.context.view_layer.layer_collection
        # Get layer collection from selected_cols names
        for col in all_colls:
            exclude_layer_col_by_name(master_col, col.name, False)

        return {"FINISHED"}


class IOPS_OT_Collections_Exclude(bpy.types.Operator):
    """Exclude collection and children from view layer"""

    bl_idname = "iops.collections_exclude"
    bl_label = "Exclude All"
    bl_description = "Exclude collection and children from view layer"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        selected_cols = [
            col
            for col in bpy.context.selected_ids
            if isinstance(col, bpy.types.Collection)
        ]
        selected_cols_children = []

        # Get all children from selected_cols withoud duplicates
        for col in selected_cols:
            for child in col.children_recursive:
                if child not in selected_cols_children:
                    selected_cols_children.append(child)

        all_colls = selected_cols + selected_cols_children

        master_col = bpy.context.view_layer.layer_collection
        # Get layer collection from selected_cols names
        for col in all_colls:
            exclude_layer_col_by_name(master_col, col.name, True)

        return {"FINISHED"}


class IOPS_OT_Collections_Remove_Keep_Objects(bpy.types.Operator):
    """Remove collection(s) and their sub-collections without flattening.

    Uses the data API instead of the outliner delete, so objects keep every
    collection membership outside the removed subtree. Only objects that would
    be left with no home are relinked to the scene root.
    """

    bl_idname = "iops.collections_remove_keep_objects"
    bl_label = "Remove (Keep Objects)"
    bl_description = (
        "Remove the selected collection(s) and all sub-collections, keeping "
        "objects in their other collections. Truly orphaned objects are "
        "relinked to the scene root"
    )
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return any(
            isinstance(_id, bpy.types.Collection)
            for _id in getattr(context, "selected_ids", [])
        )

    def execute(self, context):
        selected_cols = [
            _id
            for _id in context.selected_ids
            if isinstance(_id, bpy.types.Collection)
        ]

        # Build the full removal set: selected collections + their descendants.
        to_remove = []
        for col in selected_cols:
            if col not in to_remove:
                to_remove.append(col)
            for child in col.children_recursive:
                if child not in to_remove:
                    to_remove.append(child)

        # Gather unique objects living anywhere inside the removal set.
        objects = []
        for col in to_remove:
            for obj in col.objects:
                if obj not in objects:
                    objects.append(obj)

        # Relink only the objects that would otherwise be left homeless.
        scene_root = context.scene.collection
        relinked = 0
        for obj in objects:
            if all(home in to_remove for home in obj.users_collection):
                if obj.name not in scene_root.objects:
                    scene_root.objects.link(obj)
                    relinked += 1

        removed = 0
        for col in to_remove:
            bpy.data.collections.remove(col)
            removed += 1

        self.report(
            {"INFO"},
            f"{removed} collection(s) removed, "
            f"{relinked} object(s) relinked to scene root",
        )
        return {"FINISHED"}
