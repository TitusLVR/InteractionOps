import bpy
import os
from bpy.props import CollectionProperty
from bpy_extras.io_utils import ImportHelper
from bpy.types import Operator

def material_name_generator(name):
    prefs = bpy.context.preferences.addons['InteractionOps'].preferences
    prefixes = prefs.texture_to_material_prefixes.split(",")    
    suffixes = prefs.texture_to_material_suffixes.split(",")
    extension = name.find('.')    
    name = name[:extension]
    for pref in prefixes:        
        if name.startswith(pref):
            name = name[len(pref):]
    for suf in suffixes:
        if name.endswith(suf):
            name = name[:-len(suf)]    
    return name

class IOPS_OT_MaterialsFromTextures(Operator, ImportHelper):
    """Create Materials from Selected Textures in the File Browser"""
    bl_idname = "iops.materials_from_textures"
    bl_label = "IOPS Materials from Textures"
    
    files : CollectionProperty(type=bpy.types.PropertyGroup)

    def execute(self, context):
        dirname = os.path.dirname(self.filepath)
        for f in self.files:
            path = os.path.join(dirname, f.name)
            mat_name = material_name_generator(f.name)
            mat = bpy.data.materials.new(name=mat_name)
            mat.use_nodes = True
            bsdf = mat.node_tree.nodes["Principled BSDF"]
            texImage = mat.node_tree.nodes.new('ShaderNodeTexImage')
            texImage.image = bpy.data.images.load(path)
            mat.node_tree.links.new(bsdf.inputs['Base Color'], texImage.outputs['Color'])
            mat.use_fake_user = True
        return {'FINISHED'}

