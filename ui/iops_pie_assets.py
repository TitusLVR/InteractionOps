import os

import bpy
from bpy.types import Menu

from ..operators.assets_management import (
    _reset_pool,
    _build_tree,
    _assign_pool_ids,
)
from ..utils.assets import get_catalog_source_by_path


class IOPS_MT_AssetMarkSub(Menu):
    """Choose what to mark as asset"""

    bl_idname = "IOPS_MT_AssetMarkSub"
    bl_label = "Mark as Asset"

    def draw(self, context):
        layout = self.layout
        op = layout.operator("iops.asset_mark", text="Object", icon="OBJECT_DATA")
        op.mark_type = "OBJECT"
        op = layout.operator("iops.asset_mark", text="Collection", icon="OUTLINER_COLLECTION")
        op.mark_type = "COLLECTION"
        op = layout.operator("iops.asset_mark", text="Active Material", icon="MATERIAL")
        op.mark_type = "MATERIAL"
        op = layout.operator("iops.asset_mark", text="Active Image", icon="IMAGE_DATA")
        op.mark_type = "IMAGE"


class IOPS_MT_CatalogBrowseActive(Menu):
    """Cascading catalog menu for the active library"""

    bl_idname = "IOPS_MT_CatalogBrowseActive"
    bl_label = "Move to"

    def draw(self, context):
        _reset_pool()
        layout = self.layout
        lib_path = context.window_manager.IOPS_AddonProperties.iops_active_asset_library
        _name, cat_file, catalogs = get_catalog_source_by_path(lib_path)

        if not cat_file:
            layout.label(text="Save file first")
            return

        layout.operator("iops.asset_search_move_to_catalog", text="Search", icon="VIEWZOOM")
        layout.separator()

        if catalogs:
            tree = _build_tree(catalogs)
            _assign_pool_ids(tree, action="move", cat_file=cat_file)

            for node in tree:
                menu_id = node.get("_menu_id")
                if menu_id:
                    layout.menu(menu_id, text=node["name"], icon="FILE_FOLDER")
                elif node.get("cat"):
                    op = layout.operator(
                        "iops.asset_move_to_catalog",
                        text=node["name"],
                        icon="FILE_FOLDER",
                    )
                    op.catalog_uuid = node["cat"]["uuid"]
                    op.catalog_name = node["cat"]["simple_name"]
                else:
                    layout.label(text=node["name"], icon="FILE_FOLDER")

            layout.separator()

        op = layout.operator(
            "iops.asset_create_catalog",
            text="New Catalog",
            icon="ADD",
        )
        op.catalog_file = cat_file


class IOPS_MT_AssetDeleteCatalogsSub(Menu):
    """Cascading submenu for deleting catalogs from the active library"""

    bl_idname = "IOPS_MT_AssetDeleteCatalogsSub"
    bl_label = "Delete Catalog"

    def draw(self, context):
        _reset_pool()
        layout = self.layout
        lib_path = context.window_manager.IOPS_AddonProperties.iops_active_asset_library
        _name, cat_file, catalogs = get_catalog_source_by_path(lib_path)

        if not catalogs:
            layout.label(text="No catalogs to delete")
            return

        layout.operator("iops.asset_search_delete_catalog", text="Search", icon="VIEWZOOM")
        layout.separator()

        tree = _build_tree(catalogs)
        _assign_pool_ids(tree, action="delete", cat_file=cat_file)

        for node in tree:
            menu_id = node.get("_menu_id")
            if menu_id:
                layout.menu(menu_id, text=node["name"], icon="FILE_FOLDER")
            elif node.get("cat"):
                op = layout.operator(
                    "iops.asset_delete_catalog",
                    text=node["name"],
                    icon="TRASH",
                )
                op.catalog_uuid = node["cat"]["uuid"]
                op.catalog_file = cat_file
            else:
                layout.label(text=node["name"], icon="FILE_FOLDER")

        layout.separator()
        op = layout.operator(
            "iops.asset_delete_empty_catalogs",
            text="Delete Empty Catalogs",
            icon="BRUSH_DATA",
        )
        op.catalog_file = cat_file


class IOPS_MT_Pie_Assets(Menu):
    """Asset management pie menu"""

    bl_label = "IOPS Asset Management"

    def draw(self, context):
        layout = self.layout
        pie = layout.menu_pie()

        lib_path = context.window_manager.IOPS_AddonProperties.iops_active_asset_library

        # --- 4 - LEFT: Clear Asset ------------------------------------------
        pie.operator("iops.asset_clear", text="Clear Asset", icon="TRASH")

        # --- 6 - RIGHT: Mark as Asset (sub-menu) ---------------------------
        pie.menu("IOPS_MT_AssetMarkSub", text="Mark as Asset", icon="ASSET_MANAGER")

        # --- 2 - BOTTOM: Move to (cascading catalog menu) -------------------
        pie.menu(
            "IOPS_MT_CatalogBrowseActive",
            text="Move to",
            icon="FILE_FOLDER",
        )

        # --- 8 - TOP: Library switcher --------------------------------------
        col = pie.split().column()
        self._draw_library_switcher(context, col, lib_path)

        # --- 7 - TOP-LEFT: Render Thumbnail --------------------------------
        pie.operator(
            "iops.assets_render_asset_thumbnail",
            text="Render Thumbnail",
            icon="RENDER_RESULT",
        )

        # --- 9 - TOP-RIGHT: Delete Catalog (cascading) ---------------------
        pie.menu(
            "IOPS_MT_AssetDeleteCatalogsSub",
            text="Delete Catalog",
            icon="TRASH",
        )

    @staticmethod
    def _draw_library_switcher(context, parent, active_path):
        b = parent.box()
        col = b.column(align=True)
        col.label(text="Library", icon="ASSET_MANAGER")
        col.separator()

        is_current = (active_path == "")
        row = col.row(align=True)
        row.active = is_current
        op = row.operator(
            "iops.set_asset_library",
            text="Current File",
            icon="CHECKMARK" if is_current else "BLANK1",
            depress=is_current,
        )
        op.library_path = ""

        for lib in context.preferences.filepaths.asset_libraries:
            lib_path = os.path.normpath(lib.path)
            is_active = (lib_path == active_path)

            row = col.row(align=True)
            row.active = is_active
            op = row.operator(
                "iops.set_asset_library",
                text=lib.name,
                icon="CHECKMARK" if is_active else "BLANK1",
                depress=is_active,
            )
            op.library_path = lib_path

        col.separator()
        row = col.row(align=True)
        row.operator(
            "iops.select_in_asset_browser",
            text="Select in Browser",
            icon="VIEWZOOM",
        )
        row.operator(
            "iops.clear_asset_browser_filter",
            text="Clear Filter",
            icon="X",
        )
        col.operator(
            "iops.refresh_asset_browser",
            text="Refresh",
            icon="FILE_REFRESH",
        )
