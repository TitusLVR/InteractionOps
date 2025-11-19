import bpy
import os
from math import radians

# Check box to put the modifier at the top of the stack or bottom

# def move_modifier_to_top(obj, mod):
#     if obj.modifiers:
#         while obj.modifiers[0] != mod:
#             bpy.ops.object.modifier_move_up(modifier=mod.name)


def append_nodetree(filepath, nodetree_name):
    """Append a node tree from a blend file"""
    with bpy.data.libraries.load(filepath, link=False) as (data_from, data_to):
        if nodetree_name in data_from.node_groups:
            data_to.node_groups = [nodetree_name]
    
    # Return the appended node group
    if nodetree_name in bpy.data.node_groups:
        return bpy.data.node_groups[nodetree_name]
    return None


class IOPS_OT_AutoSmooth(bpy.types.Operator):
    bl_idname = "iops.object_auto_smooth"
    bl_description = "Add Auto Smooth modifier to selected objects"
    bl_label = "Add Auto Smooth Modifier"
    bl_options = {"REGISTER", "UNDO"}

    angle: bpy.props.FloatProperty(
        name="Smooth Angle",
        description="Smooth Angle",
        default=30.0,
        min=0.0,
        max=180.0,
    )

    ignore_sharp: bpy.props.BoolProperty(
        name="Ignore Sharp Edges",
        description="Ignore Sharp Edges",
        default=False,
    )

    stack_top: bpy.props.BoolProperty(
        name="Top of Stack",
        description="Add modifier to top of stack",
        default=True,
    )

    @classmethod
    def poll(self, context):
        # True if any of the selected objects are meshes
        return any(obj.type == "MESH" for obj in bpy.context.selected_objects)

    def invoke(self, context, event):
        # Check if "Smooth by Angle" node group already exists
        smooth_by_angles = [tree for tree in bpy.data.node_groups if tree.name.startswith('Smooth by Angle')]
        
        if not smooth_by_angles:
            # Determine path based on Blender version
            # Try system_resource first (if available), fallback to resource_path
            try:
                if hasattr(bpy.utils, 'system_resource'):
                    datafiles_path = bpy.utils.system_resource('DATAFILES')
                else:
                    # Fallback for older Blender versions
                    datafiles_path = os.path.join(bpy.utils.resource_path("LOCAL"), "datafiles")
            except (AttributeError, TypeError):
                datafiles_path = os.path.join(bpy.utils.resource_path("LOCAL"), "datafiles")
            
            if bpy.app.version >= (5, 0, 0):
                path = os.path.join(datafiles_path, 'assets', 'nodes', 'geometry_nodes_essentials.blend')
            else:
                path = os.path.join(datafiles_path, 'assets', 'geometry_nodes', 'smooth_by_angle.blend')
            
            # Append the node group
            ng = append_nodetree(path, 'Smooth by Angle')
            
            if ng:
                # Clear asset data if it exists (to avoid asset system issues)
                if hasattr(ng, 'asset_data') and ng.asset_data:
                    ng.asset_clear()
            else:
                self.report({"WARNING"}, "Could not import 'Smooth by Angle' node group from ESSENTIALS! Asset file may be missing.")
        
        return self.execute(context)

    def execute(self, context):
        if context.object.mode == 'OBJECT':
            bpy.ops.object.shade_smooth()
        else:
            bpy.ops.object.mode_set(mode='OBJECT')
            bpy.ops.object.shade_smooth()
            bpy.ops.object.mode_set(mode='EDIT')
        count = 1
        meshes = [obj for obj in bpy.context.selected_objects if obj.type == "MESH"]
        for mesh in meshes:
            auto_smooth_exists = False
            # Only change parameters if existing Auto Smooth has node_groups["Smooth by Angle"]
            for mod in mesh.modifiers:
                if (
                    "Auto Smooth" in mod.name
                    and mod.type == "NODES"
                    and getattr(mod.node_group, "name", None) == "Smooth by Angle"
                ):
                    print(
                        f"Auto Smooth modifier exists on {mesh.name}. Changing parameters."
                    )
                    mod["Input_1"] = radians(self.angle)
                    mod["Socket_1"] = self.ignore_sharp
                    # redraw ui
                    areas = [
                        area
                        for area in bpy.context.screen.areas
                        if area.type == "PROPERTIES"
                    ]
                    if areas:
                        for area in areas:
                            with bpy.context.temp_override():
                                area.tag_redraw()
                    auto_smooth_exists = True
                    break

            if auto_smooth_exists:
                continue

            if getattr(mesh, "auto_smooth_modifier", None) == "Auto Smooth":
                mesh.auto_smooth_modifier = "Auto Smooth"
            print(
                f"Adding Auto Smooth modifier to {mesh.name}, {count} of {len(bpy.context.selected_objects)}"
            )

            count += 1

            with bpy.context.temp_override(object=mesh, active_object=mesh, selected_objects=[mesh]):
                # Shade Smooth
                # bpy.ops.object.shade_smooth()
                # Delete existing Auto Smooth modifier
                for mod in mesh.modifiers:
                    if (
                        "Auto Smooth" in mod.name
                        and mod.type == "NODES"
                        and getattr(mod.node_group, "name", None) == "Auto Smooth"
                    ):
                        try:
                            bpy.ops.object.modifier_remove(modifier=mod.name)
                        except Exception as e:
                            print(
                                f"Could not remove Auto Smooth modifier from {mesh.name} — {e}"
                            )
                            break

                # Add Smooth by Angle modifier from Essentials library
                try:
                    if "Auto Smooth" not in [mod.name for mod in mesh.modifiers]:
                        # Try asset system first
                        try:
                            bpy.ops.object.modifier_add_node_group(
                                asset_library_type="ESSENTIALS",
                                asset_library_identifier="",
                                relative_asset_identifier="geometry_nodes_essentials.blend/NodeTree/Smooth by Angle",
                            )
                            for _mod in mesh.modifiers:
                                if _mod.type == "NODES" and "Smooth by Angle" in _mod.name:
                                    _mod.name = "Auto Smooth"
                                    _mod["Input_1"] = radians(self.angle)
                                    _mod["Socket_1"] = self.ignore_sharp
                                    _mod.name = "Auto Smooth"
                                    mod = _mod
                        except Exception as asset_error:
                            # Fallback: Use directly loaded node group
                            if "Smooth by Angle" in bpy.data.node_groups:
                                mod = mesh.modifiers.new(name="Auto Smooth", type="NODES")
                                mod.node_group = bpy.data.node_groups["Smooth by Angle"]
                                mod["Input_1"] = radians(self.angle)
                                mod["Socket_1"] = self.ignore_sharp
                            else:
                                raise asset_error

                    else:
                        mod = mesh.modifiers["Auto Smooth"]
                except Exception as e:
                    self.report({"ERROR"}, f"Could not add Auto Smooth modifier to {mesh.name} — {e}")
                    print(f"Could not add Auto Smooth modifier to {mesh.name} — {e}")
                    continue
                mod.show_viewport = False
                mod.show_viewport = True
                if self.stack_top:
                    bpy.ops.object.modifier_move_to_index(modifier=mod.name, index=0)

                else:
                    bpy.ops.object.modifier_move_to_index(
                        modifier=mod.name, index=len(mesh.modifiers) - 1
                    )

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
