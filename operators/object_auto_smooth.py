import bpy
from math import radians

# Check box to put the modifier at the top of the stack or bottom

# def move_modifier_to_top(obj, mod):
#     if obj.modifiers:
#         while obj.modifiers[0] != mod:
#             bpy.ops.object.modifier_move_up(modifier=mod.name)


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

    def execute(self, context):
        count = 1
        meshes = [obj for obj in bpy.context.selected_objects if obj.type == "MESH"]
        for obj in meshes:
            if getattr(obj, "auto_smooth_modifier", None) == "Auto Smooth":
                obj.auto_smooth_modifier = "Auto Smooth"
            print(
                f"Adding Auto Smooth modifier to {obj.name}, {count} of {len(bpy.context.selected_objects)}"
            )
            count += 1
            with bpy.context.temp_override(object=obj):
                #Delete existing Auto Smooth modifier
                for mod in obj.modifiers:
                    if (
                        "Auto Smooth" in mod.name 
                        and mod.type == "NODES" 
                        and mod.node_group.name == "Auto Smooth"
                        ):
                        bpy.ops.object.modifier_remove(modifier=mod.name)

                # Add Smooth by Angle modifier from Essentials library
                if not "Auto Smooth" in [mod.name for mod in obj.modifiers]:
                    bpy.ops.object.modifier_add_node_group(
                        asset_library_type="ESSENTIALS",
                        asset_library_identifier="",
                        relative_asset_identifier="geometry_nodes/smooth_by_angle.blend/NodeTree/Smooth by Angle",
                    )
                    mod = obj.modifiers[-1]
                    mod.name = "Auto Smooth"
                else:
                    mod = obj.modifiers["Auto Smooth"]

                mod.node_group = bpy.data.node_groups["Smooth by Angle"]
                mod["Input_1"] = radians(self.angle)
                mod["Socket_1"] = self.ignore_sharp

                if self.stack_top:
                    bpy.ops.object.modifier_move_to_index(modifier=mod.name, index=0)
                else:
                    bpy.ops.object.modifier_move_to_index(
                        modifier=mod.name, index=len(obj.modifiers) - 1
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
