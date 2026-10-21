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
        # Snapshot names only. A reload can free other Library datablocks
        # (duplicate-path merge, indirect libraries re-read from the parent,
        # unused linked data purged), so a pre-built list of Library wrappers
        # goes stale mid-loop and raises "StructRNA ... has been removed".
        # Re-resolve each library by name right before touching it.
        lib_names = [lib.name for lib in bpy.data.libraries]
        for lib_name in lib_names:
            lib = bpy.data.libraries.get(lib_name)
            if lib is None:
                self.report(
                    {'INFO'},
                    f"Library '{lib_name}' skipped (removed by an earlier reload).",
                )
                continue

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
