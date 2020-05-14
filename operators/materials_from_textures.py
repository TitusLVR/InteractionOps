import bpy
import os
from bpy.props import CollectionProperty
from bpy_extras.io_utils import ImportHelper
from bpy.types import Operator



class IOPS_OT_MaterialsFromTextures(Operator, ImportHelper):
    """Create Materials from Selected Textures in the File Browser"""
    bl_idname = "iops.materials_from_textures"
    bl_label = "IOPS Materials from Textures"
    
    files : CollectionProperty(type=bpy.types.PropertyGroup)

    def execute(self, context):
        dirname = os.path.dirname(self.filepath)
        for f in self.files:
            path = os.path.join(dirname, f.name)
            mat = bpy.data.materials.new(name=f.name)
            mat.use_nodes = True
            bsdf = mat.node_tree.nodes["Principled BSDF"]
            texImage = mat.node_tree.nodes.new('ShaderNodeTexImage')
            texImage.image = bpy.data.images.load(path)
            mat.node_tree.links.new(bsdf.inputs['Base Color'], texImage.outputs['Color'])
            mat.use_fake_user = True
        return {'FINISHED'}

