"""Remove-from-master operator for the ported library addon.

Confirms, then removes an asset datablock (or all unlinked asset objects)
from the master library file: in-process when the master is the currently
open file, otherwise via a job enqueued on the persistent worker session
(see ``worker_session.py``). The operator returns immediately once the job
is queued -- jobs serialize against the one open master in submission order.
"""

import bpy
from bpy.props import EnumProperty, IntProperty, StringProperty

from ...utils.library_core import valid_master_file
from . import worker_session
from .common import (
    abs_path,
    configured_master_file,
    get_catalog,
    get_prefs,
    remove_catalog_entry,
)
from .library_refresh import request_refresh


def _removal_status_message(mode, label, removed_count):
    if removed_count == 0:
        if mode == "CLEAN_UNLINKED":
            message = "No unlinked asset objects found."
        else:
            message = "%s was already absent; library resynced." % label
    elif mode == "CLEAN_UNLINKED":
        message = "Removed %d unlinked asset object(s)." % removed_count
    else:
        message = "Removed %s from the master library." % label
    return message + "; syncing library..."


class IOPS_OT_LibraryRemoveAsset(bpy.types.Operator):
    """Permanently remove asset data from the master library."""

    bl_idname = "iops.library_remove_asset"
    bl_label = "Remove From Master Library"
    bl_description = "Permanently remove asset data from the master library"
    bl_options = {"REGISTER"}

    mode: EnumProperty(
        items=(
            ("DELETE_ONE", "Selected Asset", "Remove this asset from the master"),
            (
                "CLEAN_UNLINKED",
                "Unlinked Assets",
                "Remove asset objects that are no longer linked to any collection",
            ),
        ),
        default="DELETE_ONE",
        options={"HIDDEN"},
    )
    index: IntProperty(default=-1, options={"HIDDEN"})
    asset_name: StringProperty(default="", options={"HIDDEN"})
    asset_id_type: StringProperty(default="", options={"HIDDEN"})
    asset_data_collection: StringProperty(default="", options={"HIDDEN"})
    asset_library_path: StringProperty(default="", options={"HIDDEN"})

    _label = ""

    def invoke(self, context, event):
        preferences = get_prefs(context)
        if preferences is None:
            return {"CANCELLED"}
        if self.mode == "DELETE_ONE":
            catalog = get_catalog(context)
            if self.asset_name:
                self._label = self.asset_name
            elif 0 <= self.index < len(catalog):
                self._label = catalog[self.index].asset_name
            else:
                self.report({"ERROR"}, "The library asset no longer exists.")
                return {"CANCELLED"}
        else:
            self._label = "all unlinked asset objects"
        return context.window_manager.invoke_confirm(self, event)

    def removal_request(self, context):
        preferences = get_prefs(context)
        if preferences is None:
            raise RuntimeError("IOPS Library preferences are unavailable.")

        if self.mode == "CLEAN_UNLINKED":
            master_file = configured_master_file(context)
            manifest = {"mode": "CLEAN_UNLINKED"}
            label = "unlinked asset objects"
        elif self.asset_name:
            master_file = abs_path(self.asset_library_path)
            manifest = {
                "mode": "DELETE_ONE",
                "asset_name": self.asset_name,
                "id_type": self.asset_id_type,
                "data_collection": self.asset_data_collection,
            }
            label = self.asset_name
        else:
            catalog = get_catalog(context)
            if self.index < 0 or self.index >= len(catalog):
                raise RuntimeError("The library asset no longer exists.")
            entry = catalog[self.index]
            master_file = abs_path(entry.library_path)
            manifest = {
                "mode": "DELETE_ONE",
                "asset_name": entry.asset_name,
                "id_type": entry.id_type,
                "data_collection": entry.data_collection,
            }
            label = entry.asset_name

        if not valid_master_file(master_file):
            raise RuntimeError("The master library file could not be found.")
        return master_file, manifest, label

    def finish_success(self, context, data):
        status = _removal_status_message(
            self.mode, self._label, int(data.get("removed_count", 0))
        )
        context.window_manager.iops_library_status = status
        self.report({"INFO"}, status)
        return {"FINISHED"}

    def execute(self, context):
        try:
            master_file, manifest, self._label = self.removal_request(context)
        except RuntimeError as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}

        if abs_path(bpy.data.filepath) == abs_path(master_file):
            context.window_manager.iops_library_status = "Removing %s..." % self._label
            succeeded = False
            try:
                from . import delete_worker

                data = delete_worker.remove_assets(manifest)
                result = self.finish_success(context, data)
                succeeded = True
            except Exception as error:
                context.window_manager.iops_library_status = "Removal failed"
                self.report({"ERROR"}, "Removal failed: %s" % error)
                result = {"CANCELLED"}
            if succeeded:
                bpy.ops.iops.library_refresh("INVOKE_DEFAULT")
            return result

        label = self._label
        mode = manifest.get("mode", "DELETE_ONE")
        asset_name = manifest.get("asset_name", "")
        id_type = manifest.get("id_type", "")

        def on_done(result, error):
            if result is not None and result.get("ok"):
                status = _removal_status_message(
                    mode, label, int(result.get("removed_count", 0))
                )
                try:
                    if mode == "DELETE_ONE" and asset_name and id_type:
                        remove_catalog_entry(master_file, asset_name, id_type)
                    else:
                        request_refresh(bpy.context)
                except Exception as apply_error:
                    print(
                        "IOPS Library: applying removal result failed:",
                        apply_error,
                    )
                try:
                    bpy.context.window_manager.iops_library_status = status
                except Exception:
                    pass
                return

            message = (result or {}).get("error") if result is not None else error
            message = message or "Unknown worker error"
            try:
                bpy.context.window_manager.iops_library_status = (
                    "Removal failed: %s" % message
                )
            except Exception:
                pass
            print("IOPS Library: removal failed:", message)

        context.window_manager.iops_library_status = "Removing %s (queued)..." % label
        ok, enqueue_error = worker_session.enqueue(
            context, "delete", dict(manifest), on_done, label
        )
        if not ok:
            self.report({"ERROR"}, "Could not queue removal: %s" % enqueue_error)
            return {"CANCELLED"}
        return {"FINISHED"}
