"""Publish-to-master operator for the ported library addon.

Builds a payload (datablocks + JSON manifest) from the active object
hierarchy, collection, material, or shader node group, writes it to a temp
``.blend`` via ``bpy.data.libraries.write``, and hands it to a background
``publish_worker`` subprocess polled from a modal timer.
"""

import json
import os
import shutil
import subprocess
import tempfile

import bpy
from bpy.props import EnumProperty

from ...utils.library_core import log_tail, result_data, valid_master_file
from .common import (
    abs_path,
    configured_master_file,
    find_master_file,
    get_prefs,
    object_hierarchy,
    refresh_library_browsers,
    sync_catalog,
    worker_creation_flags,
)


class IOPS_OT_LibraryPublish(bpy.types.Operator):
    """Publish the chosen local datablock into the master library."""

    bl_idname = "iops.library_publish"
    bl_label = "Publish to IOPS Library"
    bl_description = "Publish the chosen local datablock into the master library"
    bl_options = {"REGISTER"}

    publish_kind: EnumProperty(
        items=(
            ("OBJECT", "Object", "Publish the active object and its descendants"),
            ("COLLECTION", "Collection", "Publish the active collection"),
            ("MATERIAL", "Material", "Publish the active object's material"),
            ("SHADER_GROUP", "Shader Group", "Publish the chosen shader node group"),
        ),
        default="OBJECT",
        options={"HIDDEN"},
    )

    _process = None
    _timer = None
    _temp_directory = ""
    _result_file = ""
    _log_file = ""
    _asset_name = ""
    _asset_type = "OBJECT"

    @classmethod
    def poll(cls, context):
        return not context.window_manager.iops_library_busy

    def resolve_master_file(self, context):
        preferences = get_prefs(context)
        if preferences is None:
            return ""

        filepath = configured_master_file(context)
        if valid_master_file(filepath):
            return filepath

        filepath = find_master_file(context)
        if filepath:
            preferences.library_master_file = filepath
        return filepath

    def publish_source(self, context):
        if self.publish_kind == "OBJECT":
            obj = context.active_object
            if obj is None or context.mode != "OBJECT":
                raise RuntimeError("Select one active object in Object Mode.")
            hierarchy = object_hierarchy(obj)
            if any(item.library is not None for item in hierarchy):
                raise RuntimeError(
                    "The active object and all descendants must be local and editable."
                )
            return (
                set(hierarchy),
                {
                    "asset_name": obj.name,
                    "asset_type": "COLLECTION" if len(hierarchy) > 1 else "OBJECT",
                    "data_collection": "objects",
                    "source_mode": "OBJECT_HIERARCHY",
                    "root_name": obj.name,
                    "object_names": [item.name for item in hierarchy],
                },
                "%s (%d object(s))" % (obj.name, len(hierarchy)),
            )

        if self.publish_kind == "COLLECTION":
            collection = context.view_layer.active_layer_collection.collection
            if collection is None or collection == context.scene.collection:
                raise RuntimeError("Make a non-scene collection active first.")
            if collection.library is not None or any(
                obj.library is not None for obj in collection.all_objects
            ):
                raise RuntimeError("The active collection and its objects must be local.")
            active = context.active_object
            collection_objects = set(collection.all_objects)
            root_name = (
                active.name
                if (
                    active is not None
                    and active in collection_objects
                    and active.parent not in collection_objects
                )
                else ""
            )
            return (
                {collection},
                {
                    "asset_name": collection.name,
                    "asset_type": "COLLECTION",
                    "data_collection": "collections",
                    "source_mode": "COLLECTION",
                    "root_name": root_name,
                },
                "%s collection" % collection.name,
            )

        if self.publish_kind == "MATERIAL":
            obj = context.active_object
            material = obj.active_material if obj is not None else None
            if material is None:
                raise RuntimeError("The active object has no active material.")
            if material.library is not None:
                raise RuntimeError("The active material must be local and editable.")
            return (
                {material},
                {
                    "asset_name": material.name,
                    "asset_type": "MATERIAL",
                    "data_collection": "materials",
                    "source_mode": "DATABLOCK",
                },
                "%s material" % material.name,
            )

        preferences = get_prefs(context)
        node_group = (
            bpy.data.node_groups.get(preferences.library_shader_group)
            if preferences is not None
            else None
        )
        if node_group is None or node_group.bl_idname != "ShaderNodeTree":
            raise RuntimeError("Choose a local shader node group first.")
        if node_group.library is not None:
            raise RuntimeError("The shader node group must be local and editable.")
        return (
            {node_group},
            {
                "asset_name": node_group.name,
                "asset_type": "NODETREE",
                "data_collection": "node_groups",
                "source_mode": "DATABLOCK",
            },
            "%s shader group" % node_group.name,
        )

    def start_worker(self, context, master_file, data_blocks, manifest, label):
        self._temp_directory = tempfile.mkdtemp(prefix="iops_library_publish_")
        payload_file = os.path.join(self._temp_directory, "payload.blend")
        manifest_file = os.path.join(self._temp_directory, "manifest.json")
        self._result_file = os.path.join(self._temp_directory, "result.json")
        self._log_file = os.path.join(self._temp_directory, "worker.log")
        self._asset_name = manifest["asset_name"]
        self._asset_type = manifest["asset_type"]
        with open(manifest_file, "w", encoding="utf-8") as handle:
            json.dump(manifest, handle, indent=2)

        bpy.data.libraries.write(
            payload_file,
            set(data_blocks),
            path_remap="ABSOLUTE",
            fake_user=True,
            compress=True,
        )

        worker_file = os.path.join(os.path.dirname(__file__), "publish_worker.py")
        command = [
            bpy.app.binary_path,
            "--background",
            "--factory-startup",
            "--disable-autoexec",
            master_file,
            "--python",
            worker_file,
            "--",
            payload_file,
            manifest_file,
            self._result_file,
        ]
        creation_flags = worker_creation_flags()
        with open(self._log_file, "w", encoding="utf-8") as log_handle:
            self._process = subprocess.Popen(
                command,
                stdout=log_handle,
                stderr=subprocess.STDOUT,
                creationflags=creation_flags,
            )

        window_manager = context.window_manager
        window_manager.iops_library_busy = True
        window_manager.iops_library_status = "Publishing %s..." % label
        self._timer = window_manager.event_timer_add(0.25, window=context.window)
        window_manager.modal_handler_add(self)

    def invoke(self, context, event):
        master_file = self.resolve_master_file(context)
        if not valid_master_file(master_file):
            self.report(
                {"ERROR"},
                "Set Master Library File or register its folder as an Asset Library.",
            )
            return {"CANCELLED"}
        if abs_path(bpy.data.filepath) == abs_path(master_file):
            self.report({"ERROR"}, "Publish from the workflow file, not the master file.")
            return {"CANCELLED"}

        try:
            data_blocks, manifest, label = self.publish_source(context)
            self.start_worker(
                context,
                master_file,
                data_blocks,
                manifest,
                label,
            )
        except Exception as error:
            self.cleanup(context)
            self.report({"ERROR"}, "Could not start publishing: %s" % error)
            return {"CANCELLED"}
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        if event.type != "TIMER" or self._process is None:
            return {"RUNNING_MODAL"}
        if self._process.poll() is None:
            return {"RUNNING_MODAL"}

        return_code = self._process.returncode
        data = result_data(self._result_file)
        if return_code == 0 and data.get("ok"):
            synced, sync_message = sync_catalog(context, report_status=False)
            refresh_library_browsers()
            status = "Published %s" % data.get("asset_name", self._asset_name)
            if synced:
                status += " and synced library"
            status += " and refreshed Asset Browser"
            if not synced:
                status += "; %s" % sync_message
            context.window_manager.iops_library_status = status
            self.report({"INFO"}, status)
            self.cleanup(context)
            return {"FINISHED"}

        message = data.get("error") or log_tail(self._log_file) or "Unknown worker error"
        context.window_manager.iops_library_status = "Publish failed"
        self.report({"ERROR"}, "Publish failed: %s" % message)
        self.cleanup(context)
        return {"CANCELLED"}

    def cancel(self, context):
        self.cleanup(context)

    def cleanup(self, context):
        window_manager = context.window_manager
        if self._timer is not None:
            window_manager.event_timer_remove(self._timer)
            self._timer = None
        window_manager.iops_library_busy = False
        self._process = None
        if self._temp_directory and os.path.isdir(self._temp_directory):
            shutil.rmtree(self._temp_directory, ignore_errors=True)
        self._temp_directory = ""
