import os
import bpy
from math import radians
from ..utils.functions import with_progress


def get_smooth_by_angle_node_group():
    """Return the essentials 'Smooth by Angle' node group, linking it once
    if it is not in the file yet.

    bpy.ops.object.shade_auto_smooth resolves the node group through the
    asset system on every call, which stalls for seconds in files with
    linked libraries — so we fetch the group directly instead.
    """
    for ng in bpy.data.node_groups:
        if (
            ng.name == "Smooth by Angle"
            and ng.library
            and "geometry_nodes_essentials" in ng.library.filepath
        ):
            return ng

    path = os.path.join(
        bpy.utils.system_resource("DATAFILES"),
        "assets",
        "nodes",
        "geometry_nodes_essentials.blend",
    )
    with bpy.data.libraries.load(path, link=True) as (data_from, data_to):
        data_to.node_groups = [
            name for name in data_from.node_groups if name == "Smooth by Angle"
        ]
    return data_to.node_groups[0] if data_to.node_groups else None


class IOPS_OT_AutoSmooth(bpy.types.Operator):
    bl_idname = "iops.object_auto_smooth"
    bl_description = "Add Auto Smooth to selected objects"
    bl_label = "Add Auto Smooth"
    bl_options = {"REGISTER", "UNDO"}

    angle: bpy.props.FloatProperty(
        name="Smooth Angle",
        description="Smooth Angle",
        default=30.0,
        min=0.0,
        max=180.0,
    )

    @classmethod
    def poll(self, context):
        # True if any of the selected objects are meshes
        return any(obj.type == "MESH" for obj in bpy.context.selected_objects)

    def execute(self, context):
        # Get all mesh objects
        meshes = [obj for obj in context.selected_objects if obj.type == "MESH"]
        if not meshes:
            return {"FINISHED"}
        
        angle_rad = radians(self.angle)
        
        # Track and handle edit mode
        # Store original mode states and active object
        original_active = context.active_object
        objects_in_edit_mode = []
        
        # Check which objects are in edit mode and exit temporarily
        for obj in meshes:
            if obj.mode == 'EDIT':
                objects_in_edit_mode.append(obj)
                # Exit edit mode for this object
                with context.temp_override(object=obj):
                    bpy.ops.object.mode_set(mode='OBJECT')
        
        try:
            node_group = get_smooth_by_angle_node_group()
            if node_group is None:
                self.report({"ERROR"}, "Smooth by Angle node group not found")
                return {"CANCELLED"}

            angle_socket = next(
                (
                    item.identifier
                    for item in node_group.interface.items_tree
                    if item.item_type == "SOCKET"
                    and item.in_out == "INPUT"
                    and item.name == "Angle"
                ),
                None,
            )

            for mesh in with_progress(meshes, prefix="Adding Auto Smooth"):
                # First delete all modifiers with names containing "Auto Smooth" or "Smooth by Angle"
                for mod in [
                    mod
                    for mod in mesh.modifiers
                    if mod.type == "NODES"
                    and ("Auto Smooth" in mod.name or "Smooth by Angle" in mod.name)
                ]:
                    mesh.modifiers.remove(mod)

                # Shade smooth the mesh data
                mesh.data.polygons.foreach_set(
                    "use_smooth", [True] * len(mesh.data.polygons)
                )
                mesh.data.update()

                # Add the modifier directly and move it to the top of the stack
                mod = mesh.modifiers.new("Smooth by Angle", "NODES")
                mod.node_group = node_group
                if angle_socket:
                    getattr(mod.properties.inputs, angle_socket).value = angle_rad
                if len(mesh.modifiers) > 1:
                    mesh.modifiers.move(len(mesh.modifiers) - 1, 0)
        
        finally:
            # Restore edit mode for objects that were in edit mode
            for obj in objects_in_edit_mode:
                if obj and obj.name in context.scene.objects:
                    # Only restore if object still exists and is still selected
                    if obj in context.selected_objects:
                        with context.temp_override(object=obj):
                            bpy.ops.object.mode_set(mode='EDIT')
            
            # Restore original active object if it still exists
            if original_active and original_active.name in context.scene.objects:
                context.view_layer.objects.active = original_active

        return {"FINISHED"}


class IOPS_OT_ClearCustomNormals(bpy.types.Operator):
    bl_idname = "iops.object_clear_normals"
    bl_description = "Remove custom normals from selected objects"
    bl_label = "Clear Custom Normals"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(self, context):
        # True if any of the selected objects are meshes and have custom normals (obj.data.has_custom_normals)
        return any(
            obj.type == "MESH" and getattr(obj.data, "has_custom_normals", False)
            for obj in bpy.context.selected_objects
        )

    def execute(self, context):
        count = 1
        for obj in bpy.context.selected_objects:
            print(
                f"Clearing custom normals from {obj.name}, {count} of {len(bpy.context.selected_objects)}"
            )
            count += 1
            with bpy.context.temp_override(object=obj):
                if obj.type == "MESH":
                    bpy.ops.mesh.customdata_custom_splitnormals_clear()
        return {"FINISHED"}
