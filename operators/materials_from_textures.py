import bpy
import os
from bpy.props import CollectionProperty, BoolProperty
from bpy_extras.io_utils import ImportHelper
from bpy.types import Operator


def material_name_generator(name):
    prefs = bpy.context.preferences.addons["InteractionOps"].preferences
    prefixes = prefs.texture_to_material_prefixes.split(",")
    suffixes = prefs.texture_to_material_suffixes.split(",")
    extension = name.find(".")
    name = name[:extension]
    for pref in prefixes:
        if name.startswith(pref):
            name = name[len(pref) :]
    for suf in suffixes:
        if name.endswith(suf):
            name = name[: -len(suf)]
    return name


class IOPS_OT_MaterialsFromTextures(Operator, ImportHelper):
    """Create Materials from Selected Textures in the File Browser"""

    bl_idname = "iops.materials_from_textures"
    bl_label = "IOPS Materials from Textures"

    files: CollectionProperty(type=bpy.types.PropertyGroup)
    import_all: BoolProperty(
        name="Import all textures",
        description="Import all related textures",
        default=True,
    )

    def execute(self, context):
        dirname = os.path.dirname(self.filepath)
        print("DIRNAME", dirname)
        for f in self.files:
            path = os.path.join(dirname, f.name)
            # Create Shader/Matrial
            mat_name = material_name_generator(f.name)
            mat = bpy.data.materials.new(name=mat_name)
            mat.use_nodes = True
            bsdf = mat.node_tree.nodes["Principled BSDF"]
            bsdf.location = (0, 0)
            mat.node_tree.nodes["Material Output"].location = (350, 0)
            # Create Image
            texImage = mat.node_tree.nodes.new("ShaderNodeTexImage")
            texImage.image = bpy.data.images.load(path)
            texImage.image.use_fake_user = True
            texImage.location = (-600, 120)
            mat.node_tree.links.new(
                bsdf.inputs["Base Color"], texImage.outputs["Color"]
            )
            mat.use_fake_user = True
            offset = -350
            if self.import_all:
                directory = os.listdir(dirname)
                for file in directory:
                    if mat_name in file and file != f.name:
                        normal_map = mat_name + "_nm"
                        mask_map = mat_name + "_mk"
                        if normal_map in file:
                            path = os.path.join(dirname, file)
                            NormalImage = mat.node_tree.nodes.new("ShaderNodeTexImage")
                            NormalImage.name = normal_map
                            NormalImage.image = bpy.data.images.load(path)
                            NormalImage.image.colorspace_settings.name = "Non-Color"
                            NormalImage.image.use_fake_user = True
                            NormalImage.location = (-600, -720)

                            NormalMap = mat.node_tree.nodes.new("ShaderNodeNormalMap")
                            NormalMap.location = (-250, -600)

                            mat.node_tree.links.new(
                                NormalMap.inputs["Color"], NormalImage.outputs["Color"]
                            )
                            mat.node_tree.links.new(
                                bsdf.inputs["Normal"], NormalMap.outputs["Normal"]
                            )
                        elif mask_map in file:
                            path = os.path.join(dirname, file)
                            MaskImage = mat.node_tree.nodes.new("ShaderNodeTexImage")
                            MaskImage.name = mask_map
                            MaskImage.image = bpy.data.images.load(path)
                            MaskImage.image.colorspace_settings.name = "Non-Color"
                            MaskImage.image.use_fake_user = True
                            MaskImage.location = (-600, -300)

                            SeparateRGB = mat.node_tree.nodes.new(
                                "ShaderNodeSeparateRGB"
                            )
                            SeparateRGB.location = (-250, -250)

                            mat.node_tree.links.new(
                                SeparateRGB.inputs["Image"], MaskImage.outputs["Color"]
                            )
                            mat.node_tree.links.new(
                                bsdf.inputs["Metallic"], SeparateRGB.outputs["R"]
                            )
                            mat.node_tree.links.new(
                                bsdf.inputs["Roughness"], SeparateRGB.outputs["G"]
                            )
                        else:
                            path = os.path.join(dirname, file)
                            texImage = mat.node_tree.nodes.new("ShaderNodeTexImage")
                            texImage.name = file
                            texImage.image = bpy.data.images.load(path)
                            texImage.image.use_fake_user = True
                            texImage.location = (350, offset)
                            offset -= 450

        return {"FINISHED"}
