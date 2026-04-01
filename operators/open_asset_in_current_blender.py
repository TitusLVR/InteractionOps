import os

import bpy


def _norm_blend_path(path):
    if not path:
        return ""
    return os.path.normpath(bpy.path.abspath(path))


def _is_asset_system_blend(path):
    return path.lower().endswith(".asset.blend")


def resolve_open_asset_in_current_blender_path(context):
    """Return ``(filepath, None)`` or ``(None, reason_key)`` for poll / execute."""
    asset = getattr(context, "asset", None)
    if asset is not None:
        if asset.local_id:
            return None, "browser_local"
        fp = _norm_blend_path(asset.full_library_path)
        if not fp or not os.path.isfile(fp):
            return None, "missing_file"
        if _is_asset_system_blend(fp):
            return None, "asset_blend_guard"
        return fp, None

    obj = context.view_layer.objects.active
    if obj is None:
        return None, "no_active"

    olib = getattr(obj, "library", None)
    if olib is not None and getattr(olib, "filepath", ""):
        fp = _norm_blend_path(olib.filepath)
        if fp and os.path.isfile(fp):
            if _is_asset_system_blend(fp):
                return None, "asset_blend_guard"
            return fp, None

    data = getattr(obj, "data", None)
    if data is not None:
        dlib = getattr(data, "library", None)
        if dlib is not None and getattr(dlib, "filepath", ""):
            fp = _norm_blend_path(dlib.filepath)
            if fp and os.path.isfile(fp):
                if _is_asset_system_blend(fp):
                    return None, "asset_blend_guard"
                return fp, None

    if obj.type == "EMPTY" and getattr(obj, "instance_type", None) == "COLLECTION":
        coll = getattr(obj, "instance_collection", None)
        if coll is not None:
            clib = getattr(coll, "library", None)
            if clib is not None and getattr(clib, "filepath", ""):
                fp = _norm_blend_path(clib.filepath)
                if fp and os.path.isfile(fp):
                    if _is_asset_system_blend(fp):
                        return None, "asset_blend_guard"
                    return fp, None
            if getattr(coll, "asset_data", None) is not None:
                cur = bpy.data.filepath
                if cur and os.path.isfile(cur):
                    return os.path.normpath(cur), None
                return None, "unsaved_blend"

    if getattr(obj, "asset_data", None) is not None:
        cur = bpy.data.filepath
        if cur and os.path.isfile(cur):
            return os.path.normpath(cur), None
        return None, "unsaved_blend"

    return None, "no_external_asset"


_POLL_MESSAGES = {
    "browser_local": "Selected asset is contained in the current file",
    "missing_file": "Asset library file not found",
    "asset_blend_guard": "This file is managed by the asset system; manual edits should be avoided",
    "no_active": "No active object",
    "unsaved_blend": "Save the blend file to open it",
    "no_external_asset": "Not a linked asset, collection instance, or marked asset",
}


class IOPS_OT_OpenAssetInCurrentBlender(bpy.types.Operator):
    """Open the .blend that holds the asset (browser, linked object, or collection instance)."""

    bl_idname = "iops.open_asset_in_current_blender"
    bl_label = "Open in Current Blender"
    bl_options = {"REGISTER"}

    @classmethod
    def poll(cls, context):
        path, reason = resolve_open_asset_in_current_blender_path(context)
        if path:
            return True
        msg = _POLL_MESSAGES.get(reason, "Cannot open")
        cls.poll_message_set(msg)
        return False

    def execute(self, context):
        path, reason = resolve_open_asset_in_current_blender_path(context)
        if not path:
            self.report({"WARNING"}, _POLL_MESSAGES.get(reason, "Cannot open"))
            return {"CANCELLED"}

        bpy.ops.wm.open_mainfile(filepath=path)
        return {"FINISHED"}
