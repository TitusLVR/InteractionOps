"""Material assets for the iOps Materials asset shelf.

An asset is resolved to a bpy.types.Material: a current-file asset is used
as it is; a library asset is imported first, appended (reused) or linked
per the `materials_import_method` preference. An appended material carries
the custom property SOURCE_PROP = "<normalized library .blend path>|<asset
name>" so a second import from the same library file finds it again instead
of appending `Name.001`.
"""
import os

import bpy

from ...utils import materials_core as core
from . import assign, common, state

SOURCE_PROP = "iops_asset_source"


# ----------------------------------------------------------------------
# resolving / importing
# ----------------------------------------------------------------------
def find_imported(library_file, name, method):
    """A material imported earlier from `library_file` as asset `name`."""
    if method == "LINK":
        for mat in bpy.data.materials:
            lib = mat.library
            if lib is not None and mat.name == name and core.same_path(
                    bpy.path.abspath(lib.filepath), library_file):
                return mat
        return None
    key = core.asset_source_key(library_file, name)
    for mat in bpy.data.materials:
        if mat.library is None and mat.get(SOURCE_PROP) == key:
            return mat
    return None


def import_material(library_file, name, method="APPEND_REUSE"):
    """(material, None) or (None, warning text). Never raises."""
    found = find_imported(library_file, name, method)
    if found is not None:
        return found, None
    if not library_file or not os.path.isfile(library_file):
        return None, f"Material library file not found: {library_file}"
    link = method == "LINK"
    kwargs = {"link": link, "assets_only": True}
    if not link:
        kwargs["clear_asset_data"] = True
    try:
        with bpy.data.libraries.load(library_file, **kwargs) as (src, dst):
            if name not in src.materials:
                return None, f"{name} is not a material asset in {library_file}"
            dst.materials = [name]
    except (OSError, RuntimeError, ValueError) as exc:
        return None, f"Could not read {library_file}: {exc}"
    mat = dst.materials[0] if dst.materials else None
    if mat is None:
        return None, f"Could not import {name} from {library_file}"
    if not link:
        mat[SOURCE_PROP] = core.asset_source_key(library_file, name)
    state.invalidate_sources()
    return mat, None


def asset_source(context, op=None):
    """(local material or None, library file, asset name) from the
    operator's explicit properties, else from context.asset."""
    if op is not None and op.asset_name:
        if not op.library_file:
            return common.find_material(op.asset_name), "", op.asset_name
        return None, bpy.path.abspath(op.library_file), op.asset_name
    asset = getattr(context, "asset", None)
    if asset is None or asset.id_type != "MATERIAL":
        return None, "", ""
    local = asset.local_id
    if local is not None:
        return local, "", asset.name
    return None, asset.full_library_path, asset.name


def resolve(context, op=None, import_missing=True):
    """(material, warning or None) for the asset the operator acts on."""
    local, library_file, name = asset_source(context, op)
    if local is not None:
        return local, None
    if not name:
        return None, "No material asset"
    method = common.addon_prefs(context).materials_import_method
    if not import_missing:
        return find_imported(library_file, name, method), None
    return import_material(library_file, name, method)


# ----------------------------------------------------------------------
# operators
# ----------------------------------------------------------------------
class _AssetProps:
    library_file: bpy.props.StringProperty(
        name="Library File", description="The .blend file holding the asset "
        "(empty: use the asset the shelf passes, or a current-file material)",
        subtype="FILE_PATH", options={"SKIP_SAVE"})
    asset_name: bpy.props.StringProperty(
        name="Asset", description="Material asset name (empty: use the asset "
        "the shelf passes)", options={"SKIP_SAVE"})


class IOPS_OT_MaterialAssignAsset(_AssetProps, bpy.types.Operator):
    """Click: assign to the selected objects (whole object).
Alt+click: assign to the selected faces.
Ctrl+click: only make it the panel's active material.
Library assets are imported first (Append (Reuse) or Link, see Preferences)"""

    bl_idname = "iops.material_assign_asset"
    bl_label = "Assign Material Asset"
    bl_options = {"REGISTER", "UNDO"}

    mode: bpy.props.EnumProperty(name="Assign To", items=assign._MODE_ITEMS,
                                 default="OBJECT")
    only_active: bpy.props.BoolProperty(
        name="Only Make Active", description="Import if needed and make it "
        "the panel's active material, assign nothing",
        options={"SKIP_SAVE"})

    @classmethod
    def poll(cls, context):
        return assign.assign_poll(context)

    def invoke(self, context, event):
        # the context menu sets mode / only_active explicitly; a shelf click
        # leaves them unset and the modifier keys decide
        if not self.properties.is_property_set("mode") and \
                not self.properties.is_property_set("only_active"):
            if event.ctrl:
                self.only_active = True
            elif event.alt:
                self.mode = "FACES"
        return self.execute(context)

    def execute(self, context):
        mat, warning = resolve(context, self)
        if mat is None:
            self.report({"WARNING"}, warning or "Material asset not found")
            return {"CANCELLED"}
        state.set_active(mat, context)
        common.tag_redraw(context)
        if self.only_active:
            self.report({"INFO"}, f"{mat.name} is the active material")
            return {"FINISHED"}
        result = assign.assign_material(mat, common.target_objects(context),
                                        self.mode)
        state.invalidate_sources()
        assign._report_result(self, mat, result)
        # the import stays even when nothing could take the material
        return {"FINISHED"}


class IOPS_OT_MaterialAssetSelectUsers(_AssetProps, bpy.types.Operator):
    """Select the objects that use this material (it must already be in the
    file)"""

    bl_idname = "iops.material_asset_select_users"
    bl_label = "Select Objects Using It"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return context.mode == "OBJECT"

    def execute(self, context):
        mat, _warning = resolve(context, self, import_missing=False)
        if mat is None:
            self.report({"INFO"}, "This material is not in the file")
            return {"CANCELLED"}
        state.set_active(mat, context)
        return bpy.ops.iops.materials_select_users()


def _active_local(context):
    mat = state.active_material(context)
    return mat if mat is not None and mat.library is None else None


class IOPS_OT_MaterialsMarkAsset(bpy.types.Operator):
    """Mark the panel's active material as an asset of this file, with a
    generated preview, so the asset shelf shows it"""

    bl_idname = "iops.materials_mark_asset"
    bl_label = "Mark as Asset"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        mat = _active_local(context)
        return mat is not None and mat.asset_data is None

    def execute(self, context):
        mat = _active_local(context)
        mat.asset_mark()
        try:
            mat.asset_generate_preview()
        except RuntimeError:
            pass    # no preview renderer (background): marked without one
        self.report({"INFO"}, f"Marked {mat.name} as an asset")
        return {"FINISHED"}


class IOPS_OT_MaterialsClearAsset(bpy.types.Operator):
    """Clear the asset mark of the panel's active material (the material
    itself stays)"""

    bl_idname = "iops.materials_clear_asset"
    bl_label = "Clear Asset"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        mat = _active_local(context)
        return mat is not None and mat.asset_data is not None

    def execute(self, context):
        mat = _active_local(context)
        mat.asset_clear()
        self.report({"INFO"}, f"Cleared the asset mark of {mat.name}")
        return {"FINISHED"}


def register_library(folder):
    """Register `folder` as a Blender asset library unless a library with
    that path exists. Returns (library name, newly added)."""
    libraries = bpy.context.preferences.filepaths.asset_libraries
    existing = core.find_library_by_path(
        [(lib.name, bpy.path.abspath(lib.path)) for lib in libraries], folder)
    if existing is not None:
        return existing, False
    taken = [lib.name for lib in libraries]
    name = core.library_name_for_folder(folder, taken)
    before = {lib.as_pointer() for lib in libraries}
    bpy.ops.preferences.asset_library_add(directory=folder)
    added = [lib for lib in libraries if lib.as_pointer() not in before]
    if not added:
        raise RuntimeError(f"Blender did not add the asset library {folder}")
    added[0].name = name
    return added[0].name, True


class IOPS_OT_MaterialsLibraryAdd(bpy.types.Operator):
    """Pick a folder and register it as a Blender asset library (this
    changes your Blender Preferences, File Paths > Asset Libraries), then use
    it for the Materials shelf. A folder that is already registered is only
    selected"""

    bl_idname = "iops.materials_library_add"
    bl_label = "Add Material Library"
    bl_options = {"REGISTER"}

    directory: bpy.props.StringProperty(name="Folder", subtype="DIR_PATH")

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def execute(self, context):
        folder = bpy.path.abspath(self.directory)
        if not folder or not os.path.isdir(folder):
            self.report({"WARNING"}, f"Not a folder: {self.directory}")
            return {"CANCELLED"}
        try:
            name, added = register_library(folder)
        except RuntimeError as exc:
            self.report({"WARNING"}, str(exc))
            return {"CANCELLED"}
        common.addon_prefs(context).materials_library = name
        common.tag_redraw(context)
        if added:
            self.report({"INFO"}, f"Registered asset library {name}")
        else:
            self.report({"INFO"}, f"{name} is already an asset library, "
                                  f"selected it")
        return {"FINISHED"}
