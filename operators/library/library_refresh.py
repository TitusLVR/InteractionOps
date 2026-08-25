"""Rescan / refresh operators for the ported library addon.

``IOPS_OT_LibraryRefresh.invoke`` enqueues a refresh job on the persistent
worker session (see ``worker_session.py``) instead of spawning its own
subprocess and polling it from a modal timer; the job serializes with any
other pending publish/delete/refresh jobs against the same open master.
``execute`` (EXEC_DEFAULT / scripted calls) keeps the old synchronous
behavior via ``sync_catalog`` for headless/script use.
"""

import bpy

from . import worker_session
from .common import (
    apply_catalog_result,
    find_master_file,
    get_prefs,
    refresh_library_browsers,
    resolve_master_for_sync,
    sync_catalog,
)


def request_refresh(context):
    """Enqueue a refresh job on the persistent worker session. Shared by
    ``IOPS_OT_LibraryRefresh.invoke``, ``IOPS_OT_LibraryFindMaster``, and the
    publish/delete operators when they need a full re-sync rather than a
    single-entry catalog patch. Returns ``(ok, message)``."""
    master_file, error = resolve_master_for_sync(context)
    if not master_file:
        return False, error

    def on_done(result, error):
        if result is not None and result.get("ok"):
            try:
                _ok, message = apply_catalog_result(
                    bpy.context, master_file, result, report_status=False
                )
                refresh_library_browsers()
                message += " Asset Browser refreshed."
            except Exception as apply_error:
                print("IOPS Library: applying refresh result failed:", apply_error)
                return
            try:
                bpy.context.window_manager.iops_library_status = message
            except Exception:
                pass
            return

        message = (result or {}).get("error") if result is not None else error
        message = message or "Unknown worker error"
        try:
            bpy.context.window_manager.iops_library_status = (
                "Library sync failed: %s" % message
            )
        except Exception:
            pass
        print("IOPS Library: refresh failed:", message)

    return worker_session.enqueue(context, "refresh", {}, on_done, "Library sync")


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
        status = "Master library file found; syncing library..."
        context.window_manager.iops_library_status = status
        bpy.ops.iops.library_refresh("INVOKE_DEFAULT")
        self.report({"INFO"}, status)
        return {"FINISHED"}


class IOPS_OT_LibraryRefresh(bpy.types.Operator):
    """Rescan every asset-marked datablock in the master library."""

    bl_idname = "iops.library_refresh"
    bl_label = "Refresh Library"
    bl_description = "Rescan every asset-marked datablock in the master library"
    bl_options = {"REGISTER"}

    def invoke(self, context, event):
        ok, message = request_refresh(context)
        if not ok:
            self.report({"ERROR"}, message)
            return {"CANCELLED"}
        self.report({"INFO"}, "Library sync queued.")
        return {"FINISHED"}

    def execute(self, context):
        ok, message = sync_catalog(context)
        if ok:
            refresh_library_browsers()
            message += " Asset Browser refreshed."
            context.window_manager.iops_library_status = message
        self.report({"INFO"} if ok else {"ERROR"}, message)
        return {"FINISHED"} if ok else {"CANCELLED"}
