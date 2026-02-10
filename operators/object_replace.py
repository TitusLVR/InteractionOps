import bpy
from bpy.props import BoolProperty, EnumProperty, StringProperty
from mathutils import Matrix
from ..utils.functions import get_active_and_selected


def serialize_matrices(matrices):
    """Serialize a list of Matrix to a string for storage in operator property."""
    if not matrices:
        return ""
    n = len(matrices) * 16
    parts = [None] * n
    idx = 0
    for mx in matrices:
        for i in range(4):
            for j in range(4):
                parts[idx] = mx[i][j]
                idx += 1
    return " ".join(str(x) for x in parts)


def deserialize_matrices(s):
    """Deserialize a string back to a list of Matrix. Returns empty list if invalid."""
    if not s or not s.strip():
        return []
    try:
        floats = [float(x) for x in s.split()]
    except ValueError:
        return []
    if len(floats) % 16 != 0:
        return []
    matrices = []
    for i in range(0, len(floats), 16):
        matrices.append(Matrix((tuple(floats[i : i + 4]), tuple(floats[i + 4 : i + 8]),
                               tuple(floats[i + 8 : i + 12]), tuple(floats[i + 12 : i + 16]))))
    return matrices


def is_group_empty(obj):
    """Return True if obj is an Empty used as a group (has at least one child)."""
    return obj.type == "EMPTY" and len(obj.children) > 0


def get_source_group_root(source):
    """
    Return the group root Empty when source is a group or a member of a group.
    - If source is an Empty with children, return source.
    - If source is parented to an Empty (with children), walk up and return the top such Empty.
    - Otherwise return None.
    """
    if source is None:
        return None
    if is_group_empty(source):
        # Source is the group Empty; walk up to top group Empty
        root = source
        while root.parent and is_group_empty(root.parent):
            root = root.parent
        return root
    # Source is a child; find parent Empty (group root)
    if source.parent and is_group_empty(source.parent):
        root = source.parent
        while root.parent and is_group_empty(root.parent):
            root = root.parent
        return root
    return None


def duplicate_group_hierarchy(root, placement_matrix, collection, use_linked_data=False):
    """
    Duplicate the whole group (root Empty + all descendants), place root at placement_matrix.
    When use_linked_data is True, mesh data is shared (instanced copies).
    Returns (new_root, list of all new objects including new_root).
    """
    new_root = root.copy()
    if not use_linked_data and root.type == "MESH" and root.data and root.data.library is None:
        new_root.data = root.data.copy()
    new_root.matrix_world = placement_matrix.copy()
    new_root.parent = None
    collection.objects.link(new_root)
    all_new = [new_root]

    def duplicate_children(obj, new_parent):
        for child in obj.children:
            new_ob = child.copy()
            if not use_linked_data and child.type == "MESH" and child.data and child.data.library is None:
                new_ob.data = child.data.copy()
            new_ob.parent = new_parent
            new_ob.matrix_local = child.matrix_local.copy()
            collection.objects.link(new_ob)
            all_new.append(new_ob)
            duplicate_children(child, new_ob)

    duplicate_children(root, new_root)
    return new_root, all_new


def _count_children_recursive(obj):
    """Count descendants without building a list. Used for remove order (leaves first)."""
    return sum(1 for _ in obj.children_recursive)


def get_replace_targets_and_matrix(target_ob, source, keep_rotation, keep_scale, use_groups, depsgraph=None, source_eval=None):
    """
    For a target object, return (matrix_world, collection_for_target, objects_to_remove_if_replace).
    If source_eval is provided, use it instead of evaluating source again (faster when called in a loop).
    """
    if depsgraph:
        target_eval = target_ob.evaluated_get(depsgraph)
        if source_eval is None:
            source_eval = source.evaluated_get(depsgraph)
    else:
        target_eval = target_ob
        source_eval = source_eval if source_eval is not None else source
    if use_groups and is_group_empty(target_ob):
        loc = target_eval.matrix_world.translation.copy()
        if keep_rotation and keep_scale:
            rot = source_eval.matrix_world.to_quaternion()
            scale = source_eval.matrix_world.to_scale()
        elif keep_rotation:
            rot = source_eval.matrix_world.to_quaternion()
            scale = target_eval.matrix_world.to_scale()
        elif keep_scale:
            rot = target_eval.matrix_world.to_quaternion()
            scale = source_eval.matrix_world.to_scale()
        else:
            rot = target_eval.matrix_world.to_quaternion()
            scale = target_eval.matrix_world.to_scale()
        mx = Matrix.LocRotScale(loc, rot, scale)
        to_remove = [target_ob, *target_ob.children_recursive]
        return mx, target_ob, to_remove
    # Normal object
    loc = target_eval.matrix_world.translation.copy()
    if keep_rotation and keep_scale:
        rot = source_eval.matrix_world.to_quaternion()
        scale = source_eval.matrix_world.to_scale()
    elif keep_rotation:
        rot = source_eval.matrix_world.to_quaternion()
        scale = target_eval.matrix_world.to_scale()
    elif keep_scale:
        rot = target_eval.matrix_world.to_quaternion()
        scale = source_eval.matrix_world.to_scale()
    else:
        rot = target_eval.matrix_world.to_quaternion()
        scale = target_eval.matrix_world.to_scale()
    mx = Matrix.LocRotScale(loc, rot, scale)
    return mx, target_ob, [target_ob]


class IOPS_OT_Object_Replace(bpy.types.Operator):
    """Replace targets with source (active = source, selected = targets)"""

    bl_idname = "iops.object_replace"
    bl_label = "IOPS Object Replace"
    bl_options = {"REGISTER", "UNDO"}

    mode: EnumProperty(
        name="Mode",
        description="Add: place source copies at targets without removing. Replace: place and remove targets",
        items=[
            ("ADD", "Add", "Place source copies at each target; do not remove targets"),
            ("REPLACE", "Replace", "Place source copies at each target and remove targets"),
        ],
        default="REPLACE",
    )
    select_replaced: BoolProperty(
        name="Select Result",
        description="Select created objects (replaced/added). Disabled = keep current selection",
        default=True,
    )

    keep_rotation: BoolProperty(
        name="Keep Rotation",
        description="Use Source rotation. Disabled = use Target rotation",
        default=False,
    )

    keep_scale: BoolProperty(
        name="Keep Scale",
        description="Use Source scale. Disabled = use Target scale",
        default=False,
    )

    keep_source_collection: BoolProperty(
        name="Keep Source Collection",
        description="Use Source object collection. Disabled = use Object Replace collection",
        default=True,
    )

    keep_target_collection: BoolProperty(
        name="Keep Target Collection",
        description="Use each Target object collection. Disabled = use Object Replace collection. Overrides Keep Source Collection for placement.",
        default=True,
    )

    use_groups: BoolProperty(
        name="Use Groups",
        description="Source = group Empty or object in group. Targets = selected. Each target gets the full group (Empty + children)",
        default=True,
    )

    use_linked_data: BoolProperty(
        name="Use Linked Data",
        description="Create instanced copies (share mesh data) instead of full copies",
        default=False,
    )

    # Internal: store placement matrices so re-execution from history panel keeps positions
    stored_matrices: StringProperty(default="", options={"HIDDEN", "SKIP_SAVE"})

    def execute(self, context):
        source, targets = get_active_and_selected()
        use_stored = bool(self.stored_matrices.strip())
        stored_matrices_list = deserialize_matrices(self.stored_matrices) if use_stored else []

        # Use stored matrices only when re-executing with no other selection (e.g. one duplicate selected).
        use_stored = use_stored and bool(stored_matrices_list) and len(targets) == 0

        if use_stored:
            if not source:
                self.report({"ERROR"}, "Select Source (active) and Target(s)")
                return {"FINISHED"}
        elif not source or not targets:
            self.report({"ERROR"}, "Select Source (active) and Target(s)")
            return {"FINISHED"}

        if self.use_groups:
            group_root = get_source_group_root(source)
            if not group_root:
                self.report(
                    {"ERROR"},
                    "Use Groups: set Source to a group Empty or an object in a group",
                )
                return {"FINISHED"}
            source_for_collection = group_root
            source_for_matrix = group_root
        else:
            group_root = None
            source_for_collection = source
            source_for_matrix = source

        if self.keep_source_collection:
            default_collection = source_for_collection.users_collection[0]
        else:
            default_collection = bpy.data.collections.new("Object Replace")
            context.scene.collection.children.link(default_collection)

        new_objects = []
        to_remove = []
        matrices_used = []

        if use_stored and stored_matrices_list:
            collection = (
                source_for_collection.users_collection[0]
                if self.keep_target_collection
                else default_collection
            )
            for mx in stored_matrices_list:
                matrices_used.append(mx)
                if self.use_groups and group_root:
                    new_root, group_new = duplicate_group_hierarchy(
                        group_root, mx, collection, self.use_linked_data
                    )
                    for new_ob in group_new:
                        new_ob.select_set(False)
                    new_objects.extend(group_new)
                else:
                    new_ob = source.copy()
                    if not self.use_linked_data and source.type == "MESH" and source.data and source.data.library is None:
                        new_ob.data = source.data.copy()
                    new_ob.matrix_world = mx.copy()
                    collection.objects.link(new_ob)
                    new_ob.select_set(False)
                    new_objects.append(new_ob)
            if self.mode == "REPLACE":
                to_remove = list(context.view_layer.objects.selected)
        else:
            depsgraph = context.evaluated_depsgraph_get()
            source_eval = source_for_matrix.evaluated_get(depsgraph) if depsgraph else None
            for target_ob in targets:
                mx, collection_for_target, ob_to_remove = get_replace_targets_and_matrix(
                    target_ob, source_for_matrix, self.keep_rotation, self.keep_scale, self.use_groups,
                    depsgraph, source_eval=source_eval
                )
                collection = (
                    collection_for_target.users_collection[0]
                    if self.keep_target_collection
                    else default_collection
                )
                matrices_used.append(mx)

                if self.use_groups and group_root:
                    new_root, group_new = duplicate_group_hierarchy(
                        group_root, mx, collection, self.use_linked_data
                    )
                    for new_ob in group_new:
                        new_ob.select_set(False)
                    new_objects.extend(group_new)
                else:
                    new_ob = source.copy()
                    if not self.use_linked_data and source.type == "MESH" and source.data and source.data.library is None:
                        new_ob.data = source.data.copy()
                    new_ob.matrix_world = mx
                    collection.objects.link(new_ob)
                    new_ob.select_set(False)
                    new_objects.append(new_ob)

                if self.mode == "REPLACE":
                    to_remove.extend(sorted(ob_to_remove, key=_count_children_recursive))

        if self.select_replaced and new_objects:
            source.select_set(False)
            for target_ob in targets:
                target_ob.select_set(False)
            for new_ob in new_objects:
                new_ob.select_set(True)
            if self.use_groups and group_root:
                last_roots = [o for o in new_objects if o.parent is None]
                context.view_layer.objects.active = (
                    last_roots[-1] if last_roots else new_objects[-1]
                )
            else:
                context.view_layer.objects.active = new_objects[-1]

        if self.mode == "REPLACE" and to_remove:
            # When re-executing from the redo panel, selection can be our previous
            # output (duplicated group). Do not remove objects that belong to the
            # source group (group_root or its descendants), or we would delete the
            # duplicated content when the user only clicked to change a property.
            if self.use_groups and group_root:
                group_members = {group_root} | set(group_root.children_recursive)
                to_remove = [ob for ob in to_remove if ob not in group_members]
            for ob in to_remove:
                bpy.data.objects.remove(
                    ob, do_unlink=True, do_id_user=True, do_ui_user=True
                )

        # Store placement matrices so re-execution from history panel keeps positions
        self.stored_matrices = serialize_matrices(matrices_used)

        mode_str = "Added" if self.mode == "ADD" else "Replaced"
        self.report({"INFO"}, f"Objects Were {mode_str}")
        return {"FINISHED"}

    def draw(self, context):
        layout = self.layout

        # Mode
        box = layout.box()
        box.label(text="Mode")
        col = box.column(align=True)
        col.prop(self, "mode")
        col.prop(self, "select_replaced")
        col.prop(self, "use_linked_data")

        # Groups (Source = group, Targets = selected)
        box = layout.box()
        box.label(text="Groups")
        box.prop(self, "use_groups")

        # Collection (Source vs Target)
        box = layout.box()
        box.label(text="Collection")
        col = box.column(align=True)
        col.prop(self, "keep_source_collection")
        col.prop(self, "keep_target_collection")

        # Transform (Source vs Target)
        box = layout.box()
        box.label(text="Transform")
        col = box.column(align=True)
        col.prop(self, "keep_rotation")
        col.prop(self, "keep_scale")
