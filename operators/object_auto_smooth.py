import bpy
from math import radians
from ..utils.functions import with_progress


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
        
        
        # Set the angle and clean up modifiers on all meshes
        for mesh in with_progress(meshes, prefix="Adding Auto Smooth"):
            # First delete all modifiers with names containing "Auto Smooth" or "Smooth by Angle"
            modifiers_to_remove = []
            for mod in mesh.modifiers:
                if mod.type == "NODES":
                    mod_name = mod.name
                    if "Auto Smooth" in mod_name or "Smooth by Angle" in mod_name:
                        modifiers_to_remove.append(mod)
            
            # Remove the modifiers
            for mod in modifiers_to_remove:
                mesh.modifiers.remove(mod)

        # Apply auto smooth to all selected objects at once
        bpy.ops.object.shade_auto_smooth(use_auto_smooth=True, angle=angle_rad)

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
