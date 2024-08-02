import bpy
import os
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

    def invoke(self, context, event):
        # check if bpy.data.node_groups["Smooth by Angle"] exists, if not import it
        if "Smooth by Angle" not in bpy.data.node_groups.keys():
            res_path = bpy.utils.resource_path("LOCAL")
            path = os.path.join(
                res_path, "datafiles\\assets\\geometry_nodes\\smooth_by_angle.blend"
            )

            with bpy.data.libraries.load(path) as (data_from, data_to):
                data_to.node_groups = data_from.node_groups
                print(f"Loaded {path}")
        return self.execute(context)

    def execute(self, context):
        bpy.ops.object.shade_smooth()
        count = 1
        meshes = [obj for obj in bpy.context.selected_objects if obj.type == "MESH"]
        for obj in meshes:
            auto_smooth_exists = False
            # Only change parameters if existing Auto Smooth has node_groups["Smooth by Angle"]
            for mod in obj.modifiers:
                if (
                    "Auto Smooth" in mod.name
                    and mod.type == "NODES"
                    and getattr(mod.node_group, "name", None) == "Smooth by Angle"
                ):
                    print(
                        f"Auto Smooth modifier exists on {obj.name}. Changing parameters."
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

            if getattr(obj, "auto_smooth_modifier", None) == "Auto Smooth":
                obj.auto_smooth_modifier = "Auto Smooth"
            print(
                f"Adding Auto Smooth modifier to {obj.name}, {count} of {len(bpy.context.selected_objects)}"
            )

            count += 1

            with bpy.context.temp_override(object=obj):
                # Shade Smooth
                bpy.ops.object.shade_smooth()
                # Delete existing Auto Smooth modifier
                for mod in obj.modifiers:
                    if (
                        "Auto Smooth" in mod.name
                        and mod.type == "NODES"
                        and getattr(mod.node_group, "name", None) == "Auto Smooth"
                    ):
                        try:
                            bpy.ops.object.modifier_remove(modifier=mod.name)
                        except Exception as e:
                            print(
                                f"Could not remove Auto Smooth modifier from {obj.name} — {e}"
                            )
                            break

                # Add Smooth by Angle modifier from Essentials library
                try:
                    if "Auto Smooth" not in [mod.name for mod in obj.modifiers]:
                        bpy.ops.object.modifier_add_node_group(
                            asset_library_type="ESSENTIALS",
                            asset_library_identifier="",
                            relative_asset_identifier="geometry_nodes/smooth_by_angle.blend/NodeTree/Smooth by Angle",
                        )
                        for _mod in obj.modifiers:
                            if _mod.type == "NODES" and "Smooth by Angle" in _mod.name:
                                _mod.name = "Auto Smooth"
                                _mod["Input_1"] = radians(self.angle)
                                _mod["Socket_1"] = self.ignore_sharp
                                _mod.name = "Auto Smooth"
                                mod = _mod

                        # if mod.type == "NODES":
                        #     mod.node_group = bpy.data.node_groups["Smooth by Angle"]
                        #     mod["Input_1"] = radians(self.angle)
                        #     mod["Socket_1"] = self.ignore_sharp

                    else:
                        mod = obj.modifiers["Auto Smooth"]
                except Exception as e:
                    print(f"Could not add Auto Smooth modifier to {obj.name} — {e}")
                    continue    

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
