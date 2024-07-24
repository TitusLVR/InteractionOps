import bpy

class IOPS_OT_Reload_Images(bpy.types.Operator):
    """Reload images in the current blend file if they are existing."""
    bl_idname = "iops.reload_images"
    bl_label = "Reload Images"
    bl_description = "Reload Images in the current blend file if they are existing."

    @classmethod
    def poll(cls, context):
        return (bpy.data.images)
    
    def execute(self, context):
        for image in bpy.data.images:
            image.reload()
            self.report({'INFO'}, f"Image '{image.name}' reloaded.")
        return {'FINISHED'}