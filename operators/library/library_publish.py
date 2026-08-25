"""Publish-to-master operator for the ported library addon.

Builds a payload (datablocks + JSON manifest) from the active object
hierarchy, collection, material, or shader node group, writes it to a temp
``.blend``, and enqueues a publish job on the persistent worker session
(see ``worker_session.py``) instead of spawning its own subprocess. The
operator returns immediately once the job is queued -- it no longer runs
modally, and jobs serialize against the one open master in submission order.
"""

import os
import shutil
import tempfile

import bpy
import gpu
from bpy.props import EnumProperty, StringProperty
from mathutils import Vector

from ...utils.library_core import thumbnail_filename, valid_master_file
from .. import render_asset_thumbnail as _thumb_rig
from . import worker_session
from .common import (
    abs_path,
    cache_directory,
    configured_master_file,
    find_master_file,
    get_catalog,
    get_prefs,
    object_hierarchy,
    upsert_catalog_entry,
)
from .library_refresh import request_refresh


# Thumbnail capture geometry mirrors render_asset_thumbnail's temp-camera
# path defaults (90mm lens, "TIGHT" framing style -> 1.05x margin).
_THUMBNAIL_LENS_MM = 90.0
_THUMBNAIL_SIZE = 512


def _capture_viewport_thumbnail(context, objects, output_path):
    """Best-effort capture of the current viewport's view of *objects*,
    isolated and framed, to *output_path* as a transparent-background PNG.

    Reuses ``render_asset_thumbnail``'s temp-camera framing math (see that
    module) but rasterizes it via a ``gpu.types.GPUOffScreen`` instead of
    ``bpy.ops.render.opengl`` -- the visible viewport's camera/perspective
    state is never touched, so there is no camera-frame flash. Returns True
    on success, False on any graceful-skip condition or failure -- publishing
    must never fail because a thumbnail could not be captured.
    """
    try:
        area = getattr(context, "area", None)
        if area is None or area.type != "VIEW_3D":
            return False
        space = area.spaces.active
        region_3d = getattr(space, "region_3d", None) if space else None
        if region_3d is None:
            return False
        region = None
        for candidate in area.regions:
            if candidate.type == "WINDOW":
                region = candidate
                break
        if region is None:
            return False

        framable = [ob for ob in objects if _thumb_rig._is_framable(ob)]
        if not framable:
            return False
    except Exception as error:
        print("IOPS Library: thumbnail capture precondition check failed:", error)
        return False

    scene = context.scene
    view_layer = context.view_layer

    view_dir = _thumb_rig._view_dir_from_region(region_3d)
    bbox = _thumb_rig.compute_combined_bound_box(framable, context)
    center = (bbox[0] + bbox[1]) * 0.5 if bbox else Vector((0.0, 0.0, 0.0))
    margin = _thumb_rig._get_framing_margin("TIGHT", 0.16)
    fov = _thumb_rig._lens_to_fov_rad(_THUMBNAIL_LENS_MM)
    distance = _thumb_rig._fit_persp(bbox, view_dir, fov, margin)

    # Expand the keep set through any collection-instance empties so their
    # instance-source objects stay visible -- otherwise the dupli instances
    # they spawn stop rendering even though the empty itself is kept. Shared
    # with render_asset_thumbnail's batch isolation path.
    keep = _thumb_rig._expand_render_keepalive(framable)
    hidden_by_us = []
    unhidden_by_us = []
    cam_obj = None
    cam_data = None
    offscreen = None

    try:
        # Isolate: hide everything else in the view layer so only the
        # published objects (and any instance sources they depend on)
        # render. Keep-set members that are themselves already hidden get
        # unhidden for the capture and hidden again afterward.
        for ob in view_layer.objects:
            if ob in keep:
                if ob.hide_viewport:
                    try:
                        ob.hide_viewport = False
                        unhidden_by_us.append(ob)
                    except (AttributeError, ReferenceError):
                        pass
                continue
            if ob.hide_viewport:
                continue
            try:
                ob.hide_viewport = True
                hidden_by_us.append(ob)
            except (AttributeError, ReferenceError):
                pass
        try:
            # Isolation must be reflected in the depsgraph before the
            # offscreen draw below reads it.
            view_layer.update()
        except AttributeError:
            pass

        # Temp camera, fitted to the object bbox from the current view angle.
        # Never made the scene camera and never assigned to region_3d --
        # its matrix_world/lens are only used to build the view/projection
        # matrices for the offscreen draw, so the visible viewport is never
        # touched.
        cam_data = bpy.data.cameras.new("IOPS_Library_Thumb_Cam")
        cam_obj = bpy.data.objects.new("IOPS_Library_Thumb_Cam", cam_data)
        scene.collection.objects.link(cam_obj)
        cam_data.type = "PERSP"
        cam_data.lens = _THUMBNAIL_LENS_MM
        cam_obj.matrix_world = _thumb_rig._camera_world_matrix(center, view_dir, distance)

        depsgraph = context.evaluated_depsgraph_get()
        view_matrix = cam_obj.matrix_world.inverted()
        projection_matrix = cam_obj.calc_matrix_camera(
            depsgraph,
            x=_THUMBNAIL_SIZE,
            y=_THUMBNAIL_SIZE,
            scale_x=1.0,
            scale_y=1.0,
        )

        # Offscreen render: draws the 3D View's own current shading into a
        # GPU buffer, bypassing bpy.ops.render.opengl entirely -- no camera
        # assignment, no view_perspective flip, no scene.render mutation.
        # Overlays (grid, wires, origins, frustums) would pollute the
        # thumbnail -- master-toggle them off for the synchronous draw; the
        # visible viewport never redraws in between.
        offscreen = gpu.types.GPUOffScreen(_THUMBNAIL_SIZE, _THUMBNAIL_SIZE)
        overlays_were_on = space.overlay.show_overlays
        space.overlay.show_overlays = False
        try:
            offscreen.draw_view3d(
                scene,
                view_layer,
                space,
                region,
                view_matrix,
                projection_matrix,
                do_color_management=True,
                draw_background=False,
            )
        finally:
            space.overlay.show_overlays = overlays_were_on
        with offscreen.bind():
            framebuffer = gpu.state.active_framebuffer_get()
            buffer = framebuffer.read_color(
                0, 0, _THUMBNAIL_SIZE, _THUMBNAIL_SIZE, 4, 0, "UBYTE"
            )
        buffer.dimensions = _THUMBNAIL_SIZE * _THUMBNAIL_SIZE * 4
        # GL readback rows are bottom-up, matching bpy Image.pixels'
        # row order, so this is a straight flat copy (see gpu.types docs
        # example "Copy Off-screen Rendering result back to RAM").
        pixels = [component / 255.0 for component in buffer]

        directory = os.path.dirname(output_path)
        if directory:
            os.makedirs(directory, exist_ok=True)

        image = bpy.data.images.new(
            "IOPS Library Thumbnail",
            width=_THUMBNAIL_SIZE,
            height=_THUMBNAIL_SIZE,
            alpha=True,
        )
        try:
            image.pixels.foreach_set(pixels)
            image.filepath_raw = output_path
            image.file_format = "PNG"
            image.save()
        finally:
            bpy.data.images.remove(image)
        return os.path.exists(output_path)
    except Exception as error:
        print("IOPS Library: thumbnail capture failed:", error)
        return False
    finally:
        if offscreen is not None:
            try:
                offscreen.free()
            except (RuntimeError, ReferenceError):
                pass
        if cam_obj is not None:
            try:
                bpy.data.objects.remove(cam_obj, do_unlink=True)
            except (RuntimeError, ReferenceError):
                pass
        if cam_data is not None:
            try:
                if cam_data.name in bpy.data.cameras:
                    bpy.data.cameras.remove(cam_data, do_unlink=True)
            except (RuntimeError, ReferenceError):
                pass
        for ob in hidden_by_us:
            try:
                ob.hide_viewport = False
            except (AttributeError, ReferenceError):
                pass
        for ob in unhidden_by_us:
            try:
                ob.hide_viewport = True
            except (AttributeError, ReferenceError):
                pass


def _suggest_variant(name, catalog):
    """First 'name_v2', 'name_v3', ... not already present in the catalog."""
    existing_names = {entry.asset_name for entry in catalog}
    index = 2
    candidate = "%s_v%d" % (name, index)
    while candidate in existing_names:
        index += 1
        candidate = "%s_v%d" % (name, index)
    return candidate


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

    conflict_action: EnumProperty(
        name="Name Conflict",
        items=(
            ("OVERWRITE", "Overwrite", "Replace the existing library asset"),
            ("VARIANT", "Make Variant", "Publish under a new name"),
        ),
        default="OVERWRITE",
        options={"HIDDEN", "SKIP_SAVE"},
    )
    variant_name: StringProperty(name="Variant Name", default="", options={"HIDDEN", "SKIP_SAVE"})
    _has_conflict = False
    _conflict_name = ""

    _master_file = ""

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
        temp_directory = tempfile.mkdtemp(prefix="iops_library_publish_")
        try:
            payload_file = os.path.join(temp_directory, "payload.blend")
            asset_name = manifest["asset_name"]
            manifest["cache_directory"] = cache_directory(master_file)

            # The payload is a temp handoff file (written once, read once by
            # the worker, deleted). compress=True runs zlib on the main
            # thread and freezes the UI for tens of seconds on heavy assets
            # -- keep it off.
            bpy.data.libraries.write(
                payload_file,
                set(data_blocks),
                path_remap="ABSOLUTE",
                fake_user=True,
            )

            payload = dict(manifest)
            payload["payload_file"] = payload_file

            def on_done(result, error):
                shutil.rmtree(temp_directory, ignore_errors=True)

                if result is not None and result.get("ok"):
                    reported_name = result.get("asset_name", asset_name)
                    entry_data = result.get("entry")
                    try:
                        if entry_data:
                            upsert_catalog_entry(bpy.context, master_file, entry_data)
                            status = "Published %s — available in the library." % (
                                reported_name
                            )
                        else:
                            status = "Published %s; syncing library..." % reported_name
                            request_refresh(bpy.context)
                    except Exception as apply_error:
                        print(
                            "IOPS Library: applying publish result failed:",
                            apply_error,
                        )
                        return
                    try:
                        bpy.context.window_manager.iops_library_status = status
                    except Exception:
                        pass
                    return

                message = (
                    (result or {}).get("error") if result is not None else error
                )
                message = message or "Unknown worker error"
                try:
                    bpy.context.window_manager.iops_library_status = (
                        "Publish failed: %s" % message
                    )
                except Exception:
                    pass
                print("IOPS Library: publish failed:", message)
                traceback_text = None if result is None else result.get("traceback")
                if traceback_text:
                    print(traceback_text)

            ok, enqueue_error = worker_session.enqueue(
                context, "publish", payload, on_done, label
            )
            if not ok:
                raise RuntimeError(enqueue_error)
        except Exception:
            shutil.rmtree(temp_directory, ignore_errors=True)
            raise

        context.window_manager.iops_library_status = "Publishing %s (queued)..." % label

    def _attach_thumbnail(self, context, manifest, data_blocks):
        """Capture a viewport thumbnail of the objects about to be published
        and flag the manifest so the worker embeds it instead of generating
        its own. Best-effort -- any failure here is swallowed; the worker
        falls back to its normal preview generation."""
        try:
            if self.publish_kind == "COLLECTION":
                collection = next(iter(data_blocks))
                capture_objects = list(collection.all_objects)
            else:
                capture_objects = list(data_blocks)

            id_type = "COLLECTION" if manifest.get("asset_type") == "COLLECTION" else "OBJECT"
            output_path = os.path.join(
                cache_directory(self._master_file),
                thumbnail_filename(self._master_file, manifest["asset_name"], id_type),
            )
            if _capture_viewport_thumbnail(context, capture_objects, output_path):
                manifest["thumbnail_provided"] = True
        except Exception as error:
            print("IOPS Library: viewport thumbnail capture skipped:", error)

    def _start_publish(self, context, override_name=None):
        try:
            data_blocks, manifest, label = self.publish_source(context)
            manifest["source_name"] = manifest["asset_name"]
            if override_name is not None:
                manifest["asset_name"] = override_name
            if self.publish_kind in ("OBJECT", "COLLECTION"):
                self._attach_thumbnail(context, manifest, data_blocks)
            self.start_worker(
                context,
                self._master_file,
                data_blocks,
                manifest,
                label,
            )
        except Exception as error:
            self.report({"ERROR"}, "Could not start publishing: %s" % error)
            return {"CANCELLED"}
        return {"FINISHED"}

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
        self._master_file = master_file

        try:
            _data_blocks, manifest, _label = self.publish_source(context)
        except Exception as error:
            self.report({"ERROR"}, "Could not start publishing: %s" % error)
            return {"CANCELLED"}

        name = manifest["asset_name"]
        catalog = get_catalog(context)
        if not any(entry.asset_name == name for entry in catalog):
            self._has_conflict = False
            return self._start_publish(context)

        self._has_conflict = True
        self._conflict_name = name
        self.conflict_action = "OVERWRITE"
        self.variant_name = _suggest_variant(name, catalog)
        return context.window_manager.invoke_props_dialog(self)

    def draw(self, context):
        layout = self.layout
        layout.label(
            text="'%s' already exists in the library" % self._conflict_name,
            icon="ERROR",
        )
        layout.prop(self, "conflict_action", expand=True)
        row = layout.row()
        row.enabled = self.conflict_action == "VARIANT"
        row.prop(self, "variant_name", text="Name")

    def execute(self, context):
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
        self._master_file = master_file

        if not self._has_conflict or self.conflict_action == "OVERWRITE":
            return self._start_publish(context)

        target_name = self.variant_name.strip()
        if not target_name:
            self.report({"ERROR"}, "Variant name is empty.")
            return {"CANCELLED"}
        if any(entry.asset_name == target_name for entry in get_catalog(context)):
            self.report({"ERROR"}, "That name also exists — pick another.")
            return {"CANCELLED"}
        return self._start_publish(context, override_name=target_name)
