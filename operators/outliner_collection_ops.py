# Include/Exclude collections from view layer

import bpy

from ..utils.collection_group_core import group_duplicates


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


class IOPS_OT_Collections_Group_Duplicates(bpy.types.Operator):
    """Group same-named object copies into per-name sub-collections.

    For every selected collection, direct objects whose names differ only by
    Blender's ``.NNN`` suffix are moved into a child collection named
    ``<collection>_<base name>``. Singletons and nested collections are left
    untouched; other collection memberships of moved objects are preserved.
    """

    bl_idname = "iops.collections_group_duplicates"
    bl_label = "Group Duplicates by Name"
    bl_description = (
        "Move same-named object copies (box, box.001, ...) out of the "
        "selected collection(s) into child collections named "
        "<collection>_<name>"
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

        groups_made = 0
        moved = 0
        for col in selected_cols:
            groups = group_duplicates([obj.name for obj in col.objects])
            for key, names in groups.items():
                target = self._child_collection(col, f"{col.name}_{key}")
                for name in names:
                    obj = col.objects[name]
                    if obj.name not in target.objects:
                        target.objects.link(obj)
                    col.objects.unlink(obj)
                    moved += 1
                groups_made += 1

        self.report(
            {"INFO"},
            f"{moved} object(s) moved into {groups_made} collection(s)",
        )
        return {"FINISHED"}

    @staticmethod
    def _child_collection(parent, name):
        """Return the direct child of ``parent`` called ``name``, creating it.

        Matching by parent-local name (not bpy.data lookup) avoids grabbing an
        unrelated collection that merely shares the name elsewhere.
        """
        existing = parent.children.get(name)
        if existing is not None:
            return existing
        new_col = bpy.data.collections.new(name)
        parent.children.link(new_col)
        return new_col


# --- Object <-> collection helpers (ported from UEOps) ----------------------


def _find_layer_collection(layer_coll, collection):
    """Return the LayerCollection wrapping ``collection`` under ``layer_coll``."""
    if layer_coll.collection == collection:
        return layer_coll
    for child in layer_coll.children:
        found = _find_layer_collection(child, collection)
        if found is not None:
            return found
    return None


def _object_home_collection(context, obj):
    """First collection of ``obj`` that lives in the current view layer.

    The scene master collection counts too, so an object sitting at the scene
    root returns ``scene.collection``.
    """
    root = context.view_layer.layer_collection
    for col in obj.users_collection:
        if _find_layer_collection(root, col) is not None:
            return col
    return None


def _move_object_to(obj, target):
    """Link ``obj`` to ``target`` and unlink it from every other collection."""
    if obj.name not in target.objects:
        target.objects.link(obj)
    for col in list(obj.users_collection):
        if col != target:
            col.objects.unlink(obj)


def _outliner_show_active(context):
    """Scroll the first Outliner in the current screen to the active item."""
    screen = context.screen
    if screen is None:
        return
    for area in screen.areas:
        if area.type != "OUTLINER":
            continue
        for region in area.regions:
            if region.type == "WINDOW":
                with context.temp_override(area=area, region=region):
                    bpy.ops.outliner.show_active()
                return


def _set_active_layer_collection(context, collection):
    layer = _find_layer_collection(context.view_layer.layer_collection, collection)
    if layer is not None:
        context.view_layer.active_layer_collection = layer
    return layer


class IOPS_OT_Object_Move_To_Active_Collection(bpy.types.Operator):
    """Move selected objects into the collection of the active object"""

    bl_idname = "iops.object_move_to_active_collection"
    bl_label = "Move to Active Object Collection"
    bl_description = (
        "Move selected objects into the active object's collection, "
        "removing them from all other collections"
    )
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return context.active_object is not None and len(context.selected_objects) > 1

    def execute(self, context):
        active = context.active_object
        target = _object_home_collection(context, active)
        if target is None:
            self.report({"WARNING"}, "Active object is not in this view layer")
            return {"CANCELLED"}

        moved = 0
        for obj in context.selected_objects:
            if obj == active:
                continue
            _move_object_to(obj, target)
            moved += 1

        _set_active_layer_collection(context, target)
        _outliner_show_active(context)
        self.report({"INFO"}, f"{moved} object(s) moved to '{target.name}'")
        return {"FINISHED"}


class IOPS_OT_Object_Move_To_Scene_Collection(bpy.types.Operator):
    """Move selected objects to the scene collection"""

    bl_idname = "iops.object_move_to_scene_collection"
    bl_label = "Move to Scene Collection"
    bl_description = (
        "Remove selected objects from their collections and place them "
        "in the scene collection"
    )
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return len(context.selected_objects) > 0

    def execute(self, context):
        root = context.scene.collection
        moved = 0
        for obj in context.selected_objects:
            if list(obj.users_collection) == [root]:
                continue
            _move_object_to(obj, root)
            moved += 1

        if not moved:
            self.report({"INFO"}, "Object(s) already in Scene Collection")
            return {"CANCELLED"}

        _outliner_show_active(context)
        self.report({"INFO"}, f"{moved} object(s) moved to Scene Collection")
        return {"FINISHED"}


class IOPS_OT_Collection_Activate_By_Object(bpy.types.Operator):
    """Make the active object's collection the active Outliner collection"""

    bl_idname = "iops.collection_activate_by_object"
    bl_label = "Activate Object Collection"
    bl_description = "Make the active object's collection active in the Outliner"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return context.active_object is not None

    def execute(self, context):
        target = _object_home_collection(context, context.active_object)
        if target is None or _set_active_layer_collection(context, target) is None:
            self.report({"WARNING"}, "Active object is not in this view layer")
            return {"CANCELLED"}
        _outliner_show_active(context)
        return {"FINISHED"}


class IOPS_OT_Collection_Select_Objects(bpy.types.Operator):
    """Select all objects in the active object's collection"""

    bl_idname = "iops.collection_select_objects"
    bl_label = "Select Collection Objects"
    bl_description = "Select all objects inside the active object's collection"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return context.active_object is not None

    def execute(self, context):
        target = _object_home_collection(context, context.active_object)
        if target is None:
            self.report({"WARNING"}, "Active object is not in this view layer")
            return {"CANCELLED"}
        view_objects = context.view_layer.objects
        count = 0
        for obj in target.objects:
            if obj.name in view_objects and obj.visible_get():
                obj.select_set(True)
                count += 1
        self.report({"INFO"}, f"{count} object(s) selected in '{target.name}'")
        return {"FINISHED"}


class IOPS_OT_Collections_Cleanup_Empty(bpy.types.Operator):
    """Remove all empty collections, including nested empty chains"""

    bl_idname = "iops.collections_cleanup_empty"
    bl_label = "Cleanup Empty Collections"
    bl_description = (
        "Remove collections with no objects and no child collections. "
        "Repeats until nested empty collections are gone"
    )
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        removed = 0
        while True:
            empty = [
                col
                for col in bpy.data.collections
                if col.library is None
                and col.override_library is None
                and not col.objects
                and not col.children
            ]
            if not empty:
                break
            for col in empty:
                bpy.data.collections.remove(col)
                removed += 1
        self.report({"INFO"}, f"{removed} empty collection(s) removed")
        return {"FINISHED"}
