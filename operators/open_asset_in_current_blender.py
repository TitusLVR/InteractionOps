import bpy


class IOPS_OT_OpenAssetInCurrentBlender(bpy.types.Operator):
    """Open asset in current Blender instance"""

    bl_idname = "iops.open_asset_in_current_blender"
    bl_label = "Open in Current Blender"
    bl_options = {"REGISTER"}


    @classmethod
    def poll(cls, context):
        asset = getattr(context, "asset", None)

        if not asset:
            cls.poll_message_set("No asset selected")
            return False
        if asset.local_id:
            cls.poll_message_set("Selected asset is contained in the current file")
            return False
        # This could become a built-in query, for now this is good enough.
        if asset.full_library_path.endswith(".asset.blend"):
            cls.poll_message_set(
                "Selected asset is contained in a file managed by the asset system, manual edits should be avoided",
            )
            return False
        return True

    def execute(self, context):
        asset = context.asset

        if asset.local_id:
            self.report({'WARNING'}, "This asset is stored in the current blend file")
            return {'CANCELLED'}

        asset_lib_path = asset.full_library_path
        bpy.ops.wm.open_mainfile(filepath=asset_lib_path)

        return {'FINISHED'}
