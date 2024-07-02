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
