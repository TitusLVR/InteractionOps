"""iOps Materials asset shelf: material assets of the chosen asset library
plus current-file material assets, along the bottom of the 3D Viewport.

Shown instead of the Materials panel when Preferences > iOps > Materials >
Interface is Shelf. A click runs iops.material_assign_asset (the same
assignment rules as the panel); Blender's native asset drag (drop a
material on an object) stays on. The shelf API has no header hook for
buttons, so New, Functions and the library choice sit in the shelf's own
Display Settings popover (ASSETSHELF_PT_display), which this module extends.
"""
import bpy

from ..operators.materials import assets, common
from ..utils import materials_core as core


def shelf_mode(context=None):
    try:
        return common.addon_prefs(context).materials_ui_mode == "LIBRARY_SHELF"
    except (KeyError, AttributeError):
        return False


class IOPS_AST_materials(bpy.types.AssetShelf):
    bl_space_type = "VIEW_3D"
    bl_idname = "IOPS_AST_materials"
    bl_options = {"DEFAULT_VISIBLE"}
    bl_activate_operator = "IOPS_OT_material_assign_asset"
    # thumbnail-size pref (UI units) x 20 px; re-applied on pref change by
    # apply_preview_size(), the class value only seeds new shelves
    bl_default_preview_size = core.shelf_preview_size(4)
    filter_material = True

    @classmethod
    def poll(cls, context):
        if not shelf_mode(context):
            return False
        return context.mode == "OBJECT" or context.mode.startswith("EDIT")

    @classmethod
    def asset_poll(cls, asset):
        if asset.id_type != "MATERIAL":
            return False
        if asset.local_id is not None:
            return True     # current-file assets always show
        try:
            prefs = common.addon_prefs()
        except (KeyError, AttributeError):
            return True
        name = prefs.materials_library
        if not name:
            return True     # All libraries
        lib = bpy.context.preferences.filepaths.asset_libraries.get(name)
        if lib is None:
            return True     # library gone: do not hide everything
        return core.path_in_library(asset.full_library_path,
                                    bpy.path.abspath(lib.path))

    @classmethod
    def draw_context_menu(cls, context, asset, layout):
        layout.operator_context = "INVOKE_DEFAULT"
        op = layout.operator("iops.material_assign_asset",
                             text="Assign to Object", icon="OBJECT_DATA")
        op.mode = "OBJECT"
        op = layout.operator("iops.material_assign_asset",
                             text="Assign to Selected Faces", icon="FACESEL")
        op.mode = "FACES"
        layout.operator("iops.material_assign_asset",
                        text="Make Active Material",
                        icon="RESTRICT_SELECT_OFF").only_active = True
        in_file = asset.local_id is not None or assets.find_imported(
            asset.full_library_path, asset.name,
            common.addon_prefs(context).materials_import_method) is not None
        if in_file:
            layout.operator("iops.material_asset_select_users",
                            icon="RESTRICT_SELECT_OFF")
        layout.separator()
        layout.menu("IOPS_MT_materials_functions", icon="COLLAPSEMENU")


def draw_shelf_settings(self, context):
    """Appended to ASSETSHELF_PT_display: our buttons, only in our shelf."""
    shelf = getattr(context, "asset_shelf", None)
    if shelf is None or shelf.bl_idname != IOPS_AST_materials.bl_idname:
        return
    prefs = common.addon_prefs(context)
    layout = self.layout
    layout.separator()
    row = layout.row(align=True)
    row.operator("iops.material_new", text="New", icon="ADD")
    row.menu("IOPS_MT_materials_functions", text="Functions",
             icon="COLLAPSEMENU")
    row = layout.row(align=True)
    row.prop_search(prefs, "materials_library",
                    context.preferences.filepaths, "asset_libraries",
                    text="Library", results_are_suggestions=False)
    row.operator("iops.materials_library_add", text="", icon="FILE_FOLDER")


def apply_preview_size(prefs=None):
    """Re-register the shelf when the thumbnail-size pref changed its
    default preview size (a class attribute Blender reads at registration).
    Existing shelves keep the size the user set in them."""
    try:
        prefs = prefs or common.addon_prefs()
    except (KeyError, AttributeError):
        return
    size = core.shelf_preview_size(prefs.materials_thumbnail_size)
    if IOPS_AST_materials.bl_default_preview_size == size:
        return
    registered = "bl_rna" in IOPS_AST_materials.__dict__
    if registered:
        bpy.utils.unregister_class(IOPS_AST_materials)
    IOPS_AST_materials.bl_default_preview_size = size
    if registered:
        bpy.utils.register_class(IOPS_AST_materials)


def register_shelf_ui():
    display = getattr(bpy.types, "ASSETSHELF_PT_display", None)
    if display is not None:
        display.append(draw_shelf_settings)


def unregister_shelf_ui():
    display = getattr(bpy.types, "ASSETSHELF_PT_display", None)
    if display is not None:
        try:
            display.remove(draw_shelf_settings)
        except ValueError:
            pass


UI_CLASSES = (IOPS_AST_materials,)
