import os

import bpy

from .common import find_master_file, get_prefs, refresh_library_browsers, sync_catalog


class IOPS_OT_LibraryFindMaster(bpy.types.Operator):
    """Find the IOPS master blend file inside configured Asset Libraries."""

    bl_idname = "iops.library_find_master"
    bl_label = "Find Master Library"
    bl_description = "Find the IOPS master blend file inside configured Asset Libraries"
    bl_options = {"INTERNAL"}

    def execute(self, context):
        preferences = get_prefs(context)
        if preferences is None:
            self.report({"ERROR"}, "IOPS Library preferences are unavailable.")
            return {"CANCELLED"}

        filepath = find_master_file(context)
        if not filepath:
            self.report(
                {"ERROR"},
                "Could not identify one master library blend file in the configured Asset Libraries.",
            )
            return {"CANCELLED"}

        preferences.library_master_file = filepath
        context.window_manager.iops_library_status = (
            "Master found: %s" % os.path.basename(filepath)
        )
        sync_catalog(context)
        refresh_library_browsers()
        self.report({"INFO"}, "Master library file found and synced.")
        return {"FINISHED"}


class IOPS_OT_LibraryRefresh(bpy.types.Operator):
    """Rescan every asset-marked datablock in the master library."""

    bl_idname = "iops.library_refresh"
    bl_label = "Refresh Library"
    bl_description = "Rescan every asset-marked datablock in the master library"
    bl_options = {"REGISTER"}

    def execute(self, context):
        ok, message = sync_catalog(context)
        if ok:
            refresh_library_browsers()
            message += " Asset Browser refreshed."
            context.window_manager.iops_library_status = message
        self.report({"INFO"} if ok else {"ERROR"}, message)
        return {"FINISHED"} if ok else {"CANCELLED"}
