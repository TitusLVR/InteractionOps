import bpy
from bpy.props import FloatProperty,BoolProperty
import os

def get_path():
    return os.path.dirname(os.path.dirname(os.path.realpath(__file__)))


class IOPS_OT_RenderCollectionAssetThumbnail(bpy.types.Operator):
    bl_idname = "iops.render_collection_asset_thumbnail"
    bl_label = "Render Active Collection Asset Thumbnail"
    bl_description = "Render Active Collection Asset Thumbnail"
    bl_options = {'REGISTER', 'UNDO'}

   
    thumbnail_lens: FloatProperty(name="Thumbnail Lens", default=100)    
    toggle_overlays: BoolProperty(name="Toggle Overlays", default=True)    

    def render_viewport(self, context, filepath):
         resolution = (context.scene.render.resolution_x, context.scene.render.resolution_y)
         file_format = context.scene.render.image_settings.file_format
         lens = context.space_data.lens
         show_overlays = context.space_data.overlay.show_overlays

         context.scene.render.resolution_x = 500
         context.scene.render.resolution_y = 500
         context.scene.render.image_settings.file_format = 'JPEG'

         context.space_data.lens = self.thumbnail_lens

         if show_overlays and self.toggle_overlays:
               context.space_data.overlay.show_overlays = False

         bpy.ops.render.opengl()


         thumb = bpy.data.images.get('Render Result')

         if thumb:
               thumb.save_render(filepath=filepath)

         context.scene.render.resolution_x = resolution[0]
         context.scene.render.resolution_y = resolution[1]
         context.space_data.lens = lens

         context.scene.render.image_settings.file_format = file_format

         if show_overlays and self.toggle_overlays:
               context.space_data.overlay.show_overlays = True

    def execute(self, context):
        active_collection = bpy.context.collection
        
        thumbpath = os.path.join(get_path(), 'resources', 'thumb.png')
        self.render_viewport(context, thumbpath)

        if os.path.exists(thumbpath):            
            bpy.ops.ed.lib_id_load_custom_preview({'id': active_collection}, filepath=thumbpath)
            os.unlink(thumbpath)

        return {'FINISHED'}