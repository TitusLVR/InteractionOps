import os
import subprocess

import bpy


class IOPS_OT_OpenAssetInNewBlender(bpy.types.Operator):
    """Open a .blend in a new Blender process (leaves the current file untouched)."""

    bl_idname = "iops.open_asset_in_new_blender"
    bl_label = "Open .blend in New Blender"
    bl_options = {"REGISTER"}

    blendpath: bpy.props.StringProperty(
        name="Blend Path",
        description="Absolute or blend-relative path to the .blend file",
        subtype="FILE_PATH",
    )
    library: bpy.props.StringProperty(
        name="Library Name",
        description="Linked datablock library name (optional metadata)",
        default="",
    )

    def execute(self, context):
        path = bpy.path.abspath(self.blendpath)
        if not path or not os.path.isfile(path):
            self.report({"ERROR"}, f"Blend file not found: {path}")
            return {"CANCELLED"}

        exe = bpy.app.binary_path
        if not exe or not os.path.isfile(exe):
            self.report({"ERROR"}, "Could not resolve Blender executable (bpy.app.binary_path)")
            return {"CANCELLED"}

        try:
            popen_kwargs = {}
            if os.name == "nt":
                popen_kwargs["creationflags"] = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
            subprocess.Popen([exe, path], close_fds=False, **popen_kwargs)
        except OSError as e:
            self.report({"ERROR"}, str(e))
            return {"CANCELLED"}

        self.report({"INFO"}, f"Opened in new Blender: {os.path.basename(path)}")
        return {"FINISHED"}
