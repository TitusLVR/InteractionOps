import bpy
import os

class IOPS_OT_Reload_Libraries(bpy.types.Operator):
    """Reload Libraries in the current blend file if they are existing."""
    bl_idname = "iops.reload_libraries"
    bl_label = "Reload Libraries"
    bl_description = "Reload Libraries in the current blend file if they are existing."

    @classmethod
    def poll(cls, context):
        return (bpy.data.libraries)
    
    def execute(self, context):
        for lib in list(bpy.data.libraries):
            lib_name = lib.name
            lib_path = bpy.path.abspath(lib.filepath) if lib.filepath else ""

            if not lib_path or not os.path.exists(lib_path):
                self.report(
                    {'WARNING'},
                    f"Library '{lib_name}' skipped (missing path: '{lib_path or lib.filepath}').",
                )
                continue

            try:
                lib.reload()
                self.report({'INFO'}, f"Library '{lib_name}' reloaded.")
            except RuntimeError as err:
                self.report({'WARNING'}, f"Library '{lib_name}' failed to reload: {err}")
        return {'FINISHED'}
