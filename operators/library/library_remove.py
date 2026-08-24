"""Remove-from-master operator for the ported library addon.

Confirms, then removes an asset datablock (or all unlinked asset objects)
from the master library file: in-process when the master is the currently
open file, otherwise via a background ``delete_worker`` subprocess polled
from a modal timer.
"""

import json
import os
import shutil
import subprocess
import tempfile

import bpy
from bpy.props import EnumProperty, IntProperty, StringProperty

from ...utils.library_core import log_tail, result_data, valid_master_file
from .common import (
    abs_path,
    configured_master_file,
    get_catalog,
    get_prefs,
    refresh_library_browsers,
    sync_catalog,
    worker_creation_flags,
)


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

    _process = None
    _timer = None
    _temp_directory = ""
    _result_file = ""
    _log_file = ""
    _label = ""

    @classmethod
    def poll(cls, context):
        return not getattr(context.window_manager, "iops_library_busy", False)

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
        removed_count = int(data.get("removed_count", 0))
        synced, sync_message = sync_catalog(context, report_status=False)
        refresh_library_browsers()

        if removed_count == 0:
            if self.mode == "CLEAN_UNLINKED":
                status = "No unlinked asset objects found."
            else:
                status = "%s was already absent; library resynced." % self._label
        elif self.mode == "CLEAN_UNLINKED":
            status = "Removed %d unlinked asset object(s)." % removed_count
        else:
            status = "Removed %s from the master library." % self._label
        if not synced:
            status += " %s" % sync_message
        else:
            status += " Asset Browser refreshed."

        context.window_manager.iops_library_status = status
        self.report({"INFO"}, status)
        return {"FINISHED"}

    def execute(self, context):
        try:
            master_file, manifest, self._label = self.removal_request(context)
        except RuntimeError as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}

        context.window_manager.iops_library_busy = True
        context.window_manager.iops_library_status = "Removing %s..." % self._label
        if abs_path(bpy.data.filepath) == abs_path(master_file):
            try:
                from . import delete_worker

                data = delete_worker.remove_assets(manifest)
                return self.finish_success(context, data)
            except Exception as error:
                context.window_manager.iops_library_status = "Removal failed"
                self.report({"ERROR"}, "Removal failed: %s" % error)
                return {"CANCELLED"}
            finally:
                context.window_manager.iops_library_busy = False

        self._temp_directory = tempfile.mkdtemp(prefix="iops_library_delete_")
        manifest_file = os.path.join(self._temp_directory, "manifest.json")
        self._result_file = os.path.join(self._temp_directory, "result.json")
        self._log_file = os.path.join(self._temp_directory, "worker.log")
        with open(manifest_file, "w", encoding="utf-8") as handle:
            json.dump(manifest, handle, indent=2)

        worker_file = os.path.join(os.path.dirname(__file__), "delete_worker.py")
        command = [
            bpy.app.binary_path,
            "--background",
            "--factory-startup",
            "--disable-autoexec",
            master_file,
            "--python",
            worker_file,
            "--",
            manifest_file,
            self._result_file,
        ]
        creation_flags = worker_creation_flags()
        try:
            with open(self._log_file, "w", encoding="utf-8") as log_handle:
                self._process = subprocess.Popen(
                    command,
                    stdout=log_handle,
                    stderr=subprocess.STDOUT,
                    creationflags=creation_flags,
                )
            self._timer = context.window_manager.event_timer_add(
                0.25,
                window=context.window,
            )
            context.window_manager.modal_handler_add(self)
        except Exception as error:
            self.cleanup(context)
            self.report({"ERROR"}, "Could not start removal: %s" % error)
            return {"CANCELLED"}
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        if event.type != "TIMER" or self._process is None:
            return {"RUNNING_MODAL"}
        if self._process.poll() is None:
            return {"RUNNING_MODAL"}

        data = result_data(self._result_file)
        if self._process.returncode == 0 and data.get("ok"):
            result = self.finish_success(context, data)
            self.cleanup(context)
            return result

        message = data.get("error") or log_tail(self._log_file) or "Unknown worker error"
        context.window_manager.iops_library_status = "Removal failed"
        self.report({"ERROR"}, "Removal failed: %s" % message)
        self.cleanup(context)
        return {"CANCELLED"}

    def cancel(self, context):
        self.cleanup(context)

    def cleanup(self, context):
        if self._timer is not None:
            context.window_manager.event_timer_remove(self._timer)
            self._timer = None
        context.window_manager.iops_library_busy = False
        self._process = None
        if self._temp_directory and os.path.isdir(self._temp_directory):
            shutil.rmtree(self._temp_directory, ignore_errors=True)
        self._temp_directory = ""
