import bpy

class IOPS_OT_Reload_Libraries(bpy.types.Operator):
    """Reload Libraries in the current blend file if they are existing."""
    bl_idname = "iops.reload_libraries"
    bl_label = "Reload Libraries"
    bl_description = "Reload Libraries in the current blend file if they are existing."

    @classmethod
    def poll(cls, context):
        return (bpy.data.libraries)
    
    def execute(self, context):
        for lib in bpy.data.libraries:
            lib.reload()
            self.report({'INFO'}, f"Library '{lib.name}' reloaded.")
        return {'FINISHED'}
