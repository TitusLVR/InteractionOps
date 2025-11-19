import bpy
import os
from math import radians
from ..utils.functions import with_progress

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
        # Get node group reference once (cached)
        node_group = bpy.data.node_groups.get("Smooth by Angle")
        if not node_group:
            self.report({"ERROR"}, "Smooth by Angle node group not found. Please ensure the asset file exists.")
            return {"CANCELLED"}
        
        # Get all mesh objects
        meshes = [obj for obj in bpy.context.selected_objects if obj.type == "MESH"]
        if not meshes:
            return {"FINISHED"}
        
        # Apply shade smooth to all meshes at once (direct API, faster)
        angle_rad = radians(self.angle)
        needs_ui_update = False
        
        for mesh in with_progress(meshes, prefix="Adding Auto Smooth modifier"):
            # Check if modifier already exists with correct node group
            existing_mod = None
            old_mod_to_remove = None
            
            for mod in mesh.modifiers:
                if mod.name == "Auto Smooth" and mod.type == "NODES":
                    if getattr(mod.node_group, "name", None) == "Smooth by Angle":
                        # Update existing modifier parameters
                        existing_mod = mod
                        mod["Input_1"] = angle_rad
                        mod["Socket_1"] = self.ignore_sharp
                        needs_ui_update = True
                        break
                    elif getattr(mod.node_group, "name", None) == "Auto Smooth":
                        # Old modifier to remove
                        old_mod_to_remove = mod
            
            if existing_mod:
                # Modifier exists and was updated, just move it if needed
                mod = existing_mod
                needs_move = False
                if self.stack_top and mesh.modifiers[0] != mod:
                    needs_move = True
                elif not self.stack_top and mesh.modifiers[-1] != mod:
                    needs_move = True
            else:
                # Remove old modifier if exists (direct API, much faster)
                if old_mod_to_remove:
                    mesh.modifiers.remove(old_mod_to_remove)
                
                # Add new modifier (direct API, no context override needed)
                # New modifiers are added at the end by default
                mod = mesh.modifiers.new(name="Auto Smooth", type="NODES")
                mod.node_group = node_group
                mod["Input_1"] = angle_rad
                mod["Socket_1"] = self.ignore_sharp
                # Only need to move if we want it at the top
                needs_move = self.stack_top and len(mesh.modifiers) > 1
            
            # Move modifier to desired position only if needed (direct API, much faster than operator)
            if needs_move:
                if self.stack_top:
                    # Move to top by removing and re-inserting at index 0
                    mesh.modifiers.remove(mod)
                    mesh.modifiers.insert(0, mod)
                else:
                    # Move to bottom by removing and re-adding
                    mesh.modifiers.remove(mod)
                    mesh.modifiers.append(mod)
            
            # Apply shade smooth (direct API, faster)
            if not mesh.data.use_auto_smooth:
                mesh.data.use_auto_smooth = True
            mesh.data.auto_smooth_angle = angle_rad
        
        # Update UI once at the end instead of per object
        if needs_ui_update:
            for area in context.screen.areas:
                if area.type == "PROPERTIES":
                    area.tag_redraw()

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
