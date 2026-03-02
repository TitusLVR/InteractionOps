import bpy
from bpy.props import EnumProperty, StringProperty
from bpy.types import Menu

from ..utils.assets import (
    assign_catalog,
    create_catalog,
    delete_catalog,
    find_asset_browser_space,
    get_active_image,
    get_catalog_source_by_path,
    get_current_file_catalog_info,
    iter_all_asset_datablocks,
    parse_catalog_file,
    refresh_asset_browser,
    resolve_assets_from_selection,
    tag_redraw_asset_browsers,
)


# ---------------------------------------------------------------------------
#   Cascading-menu pool
# ---------------------------------------------------------------------------
#
#   Blender's layout.menu() needs a registered Menu class with a fixed
#   bl_idname.  Since asset catalogs are dynamic we pre-register a pool of
#   generic Menu classes and populate them at draw time.
#
#   Each node stored in _pool carries an "_action" field:
#     "move"   -> draws iops.asset_move_to_catalog operators
#     "delete" -> draws iops.asset_delete_catalog  operators

_POOL_SIZE = 32
_pool = {}
_pool_counter = [0]


def _reset_pool():
    _pool.clear()
    _pool_counter[0] = 0


def _alloc_pool(node):
    idx = _pool_counter[0]
    if idx >= _POOL_SIZE:
        return None
    menu_id = f"IOPS_MT_CatPool_{idx}"
    node["_menu_id"] = menu_id
    _pool[idx] = node
    _pool_counter[0] = idx + 1
    return menu_id


def _make_pool_draw(index):
    def draw(self, context):
        node = _pool.get(index)
        if node is None:
            self.layout.label(text="(empty)")
            return
        layout = self.layout
        action = node.get("_action", "move")
        cat = node.get("cat")

        if action == "move":
            if cat:
                op = layout.operator(
                    "iops.asset_move_to_catalog",
                    text="Assign Here",
                    icon="IMPORT",
                )
                op.catalog_uuid = cat["uuid"]
                op.catalog_name = cat["simple_name"]
                if node["children"]:
                    layout.separator()
            for child in node["children"]:
                child_menu = child.get("_menu_id")
                if child_menu:
                    layout.menu(child_menu, text=child["name"], icon="FILE_FOLDER")
                elif child.get("cat"):
                    op = layout.operator(
                        "iops.asset_move_to_catalog",
                        text=child["name"],
                        icon="FILE_FOLDER",
                    )
                    op.catalog_uuid = child["cat"]["uuid"]
                    op.catalog_name = child["cat"]["simple_name"]
                else:
                    layout.label(text=child["name"], icon="FILE_FOLDER")

            cat_file = node.get("_cat_file", "")
            if cat_file:
                layout.separator()
                op = layout.operator(
                    "iops.asset_create_catalog",
                    text="New Catalog",
                    icon="ADD",
                )
                op.catalog_file = cat_file

        elif action == "delete":
            cat_file = node.get("_cat_file", "")
            if cat:
                op = layout.operator(
                    "iops.asset_delete_catalog",
                    text="Delete This",
                    icon="TRASH",
                )
                op.catalog_uuid = cat["uuid"]
                op.catalog_file = cat_file
                if node["children"]:
                    layout.separator()
            for child in node["children"]:
                child_menu = child.get("_menu_id")
                if child_menu:
                    layout.menu(child_menu, text=child["name"], icon="FILE_FOLDER")
                elif child.get("cat"):
                    op = layout.operator(
                        "iops.asset_delete_catalog",
                        text=child["name"],
                        icon="TRASH",
                    )
                    op.catalog_uuid = child["cat"]["uuid"]
                    op.catalog_file = cat_file
                else:
                    layout.label(text=child["name"], icon="FILE_FOLDER")

    return draw


_pool_classes = []
for _i in range(_POOL_SIZE):
    _cls = type(
        f"IOPS_MT_CatPool_{_i}",
        (Menu,),
        {
            "bl_idname": f"IOPS_MT_CatPool_{_i}",
            "bl_label": "Catalog",
            "draw": _make_pool_draw(_i),
        },
    )
    _pool_classes.append(_cls)


def register_pool_menus():
    for cls in _pool_classes:
        bpy.utils.register_class(cls)


def unregister_pool_menus():
    for cls in reversed(_pool_classes):
        bpy.utils.unregister_class(cls)


# ---------------------------------------------------------------------------
#   Tree builder
# ---------------------------------------------------------------------------

def _build_tree(catalogs):
    sorted_cats = sorted(catalogs, key=lambda c: c["path"].lower())
    nodes = {}
    roots = []

    for cat in sorted_cats:
        parts = cat["path"].split("/")
        for depth, segment in enumerate(parts):
            key = "/".join(parts[: depth + 1])
            if key in nodes:
                continue
            node = {"name": segment, "cat": None, "children": []}
            nodes[key] = node
            if depth == 0:
                roots.append(node)
            else:
                parent_key = "/".join(parts[:depth])
                nodes[parent_key]["children"].append(node)

        nodes[cat["path"]]["cat"] = cat

    return roots


def _assign_pool_ids(roots, action="move", cat_file=""):
    """Walk tree and assign a pool Menu to every node that has children."""
    for node in roots:
        node["_action"] = action
        node["_cat_file"] = cat_file
        if node["children"]:
            _alloc_pool(node)
            _assign_pool_ids(node["children"], action=action, cat_file=cat_file)


# ---------------------------------------------------------------------------
#   Operators
# ---------------------------------------------------------------------------

class IOPS_OT_AssetMoveToCatalog(bpy.types.Operator):
    """Move selected assets to this catalog"""

    bl_idname = "iops.asset_move_to_catalog"
    bl_label = "Move Asset to Catalog"
    bl_options = {"REGISTER", "UNDO"}

    catalog_uuid: StringProperty(name="Catalog UUID")
    catalog_name: StringProperty(name="Catalog Name")

    @classmethod
    def poll(cls, context):
        if context.area and context.area.type == "VIEW_3D":
            if resolve_assets_from_selection(context):
                return True
            cls.poll_message_set("No assets found in selection")
            return False
        asset = getattr(context, "asset", None)
        if asset and asset.local_id:
            return True
        if asset:
            cls.poll_message_set("Only local assets can be reassigned")
        else:
            cls.poll_message_set("No asset selected")
        return False

    def execute(self, context):
        moved = 0
        if context.area and context.area.type == "VIEW_3D":
            for db, _kind in resolve_assets_from_selection(context):
                ok, _ = assign_catalog(db, self.catalog_uuid)
                if ok:
                    moved += 1
        else:
            asset = getattr(context, "asset", None)
            if asset and asset.local_id:
                ok, _ = assign_catalog(asset.local_id, self.catalog_uuid)
                if ok:
                    moved += 1

        if moved:
            self.report({"INFO"}, f"Moved {moved} asset(s) to '{self.catalog_name}'")
            refresh_asset_browser()
            return {"FINISHED"}
        self.report({"WARNING"}, "No assets were moved")
        return {"CANCELLED"}


class IOPS_OT_AssetMark(bpy.types.Operator):
    """Mark selected data-blocks as assets"""

    bl_idname = "iops.asset_mark"
    bl_label = "Mark as Asset"
    bl_options = {"REGISTER", "UNDO"}

    mark_type: EnumProperty(
        name="Type",
        items=[
            ("OBJECT", "Object", "Mark selected objects as assets"),
            ("COLLECTION", "Collection", "Mark the parent collection of selected objects"),
            ("MATERIAL", "Active Material", "Mark the active material as asset"),
            ("IMAGE", "Active Image", "Mark the active image as asset"),
        ],
        default="OBJECT",
    )

    @classmethod
    def poll(cls, context):
        if context.selected_objects or context.active_object:
            return True
        cls.poll_message_set("No objects selected")
        return False

    def execute(self, context):
        count = 0

        if self.mark_type == "OBJECT":
            for obj in (context.selected_objects or []):
                if getattr(obj, "asset_data", None) is None:
                    obj.asset_mark()
                    count += 1

        elif self.mark_type == "COLLECTION":
            seen = set()
            for obj in (context.selected_objects or []):
                for coll in obj.users_collection:
                    if coll == context.scene.collection:
                        continue
                    if id(coll) not in seen:
                        seen.add(id(coll))
                        if getattr(coll, "asset_data", None) is None:
                            coll.asset_mark()
                            count += 1

        elif self.mark_type == "MATERIAL":
            obj = context.active_object
            if obj and obj.active_material:
                mat = obj.active_material
                if getattr(mat, "asset_data", None) is None:
                    mat.asset_mark()
                    count += 1
                else:
                    self.report({"INFO"}, f"'{mat.name}' is already an asset")
                    return {"FINISHED"}
            else:
                self.report({"WARNING"}, "No active material")
                return {"CANCELLED"}

        elif self.mark_type == "IMAGE":
            img = get_active_image(context)
            if img:
                if getattr(img, "asset_data", None) is None:
                    img.asset_mark()
                    count += 1
                else:
                    self.report({"INFO"}, f"'{img.name}' is already an asset")
                    return {"FINISHED"}
            else:
                self.report({"WARNING"}, "No active image found")
                return {"CANCELLED"}

        if count:
            self.report({"INFO"}, f"Marked {count} data-block(s) as assets")
            refresh_asset_browser()
        else:
            self.report({"INFO"}, "Everything already marked as asset")
        return {"FINISHED"}


class IOPS_OT_AssetClear(bpy.types.Operator):
    """Clear asset status from selection (objects, collections, materials)"""

    bl_idname = "iops.asset_clear"
    bl_label = "Clear Asset"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        if context.area and context.area.type == "VIEW_3D":
            if resolve_assets_from_selection(context):
                return True
        cls.poll_message_set("No assets found in selection")
        return False

    def execute(self, context):
        count = 0
        for db, _kind in resolve_assets_from_selection(context):
            db.asset_clear()
            count += 1
        if count:
            self.report({"INFO"}, f"Cleared {count} asset(s)")
            refresh_asset_browser()
            return {"FINISHED"}
        self.report({"WARNING"}, "Nothing to clear")
        return {"CANCELLED"}


class IOPS_OT_AssetCreateCatalog(bpy.types.Operator):
    """Create a new catalog in the active asset library"""

    bl_idname = "iops.asset_create_catalog"
    bl_label = "New Asset Catalog"
    bl_options = {"REGISTER", "UNDO"}

    catalog_name: StringProperty(
        name="Catalog Path",
        description="Path for the new catalog (use / for nesting, e.g. Props/Furniture)",
        default="New Catalog",
    )
    catalog_file: StringProperty(name="Catalog File")

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)

    def draw(self, context):
        self.layout.prop(self, "catalog_name")

    def execute(self, context):
        cat_file = self.catalog_file
        if not cat_file:
            cat_file, _ = get_current_file_catalog_info()
        if not cat_file:
            self.report({"WARNING"}, "Save the file first to create catalogs")
            return {"CANCELLED"}

        ok, msg, _ = create_catalog(cat_file, self.catalog_name)
        self.report({"INFO"} if ok else {"WARNING"}, msg)
        if ok:
            refresh_asset_browser()
            return {"FINISHED"}
        return {"CANCELLED"}


class IOPS_OT_AssetDeleteCatalog(bpy.types.Operator):
    """Delete this catalog from the asset library"""

    bl_idname = "iops.asset_delete_catalog"
    bl_label = "Delete Asset Catalog"
    bl_options = {"REGISTER", "UNDO"}

    catalog_uuid: StringProperty(name="Catalog UUID")
    catalog_file: StringProperty(name="Catalog File")

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        ok, msg = delete_catalog(self.catalog_file, self.catalog_uuid)
        self.report({"INFO"} if ok else {"WARNING"}, msg)
        if ok:
            refresh_asset_browser()
            return {"FINISHED"}
        return {"CANCELLED"}


class IOPS_OT_AssetDeleteEmptyCatalogs(bpy.types.Operator):
    """Delete all catalogs that have no assets assigned"""

    bl_idname = "iops.asset_delete_empty_catalogs"
    bl_label = "Delete Empty Catalogs"
    bl_options = {"REGISTER", "UNDO"}

    catalog_file: StringProperty(name="Catalog File")

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        cat_file = self.catalog_file
        if not cat_file:
            self.report({"WARNING"}, "No catalog file")
            return {"CANCELLED"}

        catalogs = parse_catalog_file(cat_file)
        if not catalogs:
            self.report({"INFO"}, "No catalogs found")
            return {"CANCELLED"}

        used_uuids = set()
        for db in iter_all_asset_datablocks():
            ad = db.asset_data
            if ad.catalog_id:
                used_uuids.add(ad.catalog_id)

        empty = [c for c in catalogs if c["uuid"] not in used_uuids]
        if not empty:
            self.report({"INFO"}, "No empty catalogs")
            return {"CANCELLED"}

        deleted = 0
        for cat in empty:
            ok, _ = delete_catalog(cat_file, cat["uuid"])
            if ok:
                deleted += 1

        self.report({"INFO"}, f"Deleted {deleted} empty catalog(s)")
        if deleted:
            refresh_asset_browser()
        return {"FINISHED"}


def _short_catalog_path(path, max_segments=2):
    """Return a shortened display name keeping the last *max_segments* parts."""
    parts = [p.strip() for p in path.split("/") if p.strip()]
    if len(parts) <= max_segments:
        return " / ".join(parts)
    return "… / " + " / ".join(parts[-max_segments:])


_catalog_search_items_cache = []


def _catalog_search_items(self, context):
    """EnumProperty items callback — shortened name, full path in tooltip."""
    global _catalog_search_items_cache
    lib_path = context.window_manager.IOPS_AddonProperties.iops_active_asset_library
    _name, _cat_file, catalogs = get_catalog_source_by_path(lib_path)
    if not catalogs:
        _catalog_search_items_cache = [("NONE", "No catalogs", "")]
    else:
        _catalog_search_items_cache = [
            (c["uuid"], _short_catalog_path(c["path"]), c["path"])
            for c in catalogs
        ]
    return _catalog_search_items_cache


class IOPS_OT_AssetSearchMoveToCatalog(bpy.types.Operator):
    """Search catalogs by name and move selected assets to the chosen one"""

    bl_idname = "iops.asset_search_move_to_catalog"
    bl_label = "Search Catalog (Move)"
    bl_options = {"REGISTER", "UNDO"}
    bl_property = "catalog_choice"

    catalog_choice: EnumProperty(name="Catalog", items=_catalog_search_items)

    @classmethod
    def poll(cls, context):
        if context.area and context.area.type == "VIEW_3D":
            if resolve_assets_from_selection(context):
                return True
            cls.poll_message_set("No assets found in selection")
            return False
        asset = getattr(context, "asset", None)
        if asset and asset.local_id:
            return True
        cls.poll_message_set("No asset selected")
        return False

    def invoke(self, context, event):
        context.window_manager.invoke_search_popup(self)
        return {"CANCELLED"}

    def execute(self, context):
        if self.catalog_choice == "NONE":
            self.report({"WARNING"}, "No catalog selected")
            return {"CANCELLED"}

        cat_uuid = self.catalog_choice
        lib_path = context.window_manager.IOPS_AddonProperties.iops_active_asset_library
        _name, _cat_file, catalogs = get_catalog_source_by_path(lib_path)
        cat_path = next((c["path"] for c in catalogs if c["uuid"] == cat_uuid), "")

        moved = 0
        if context.area and context.area.type == "VIEW_3D":
            for db, _kind in resolve_assets_from_selection(context):
                ok, _ = assign_catalog(db, cat_uuid)
                if ok:
                    moved += 1
        else:
            asset = getattr(context, "asset", None)
            if asset and asset.local_id:
                ok, _ = assign_catalog(asset.local_id, cat_uuid)
                if ok:
                    moved += 1

        if moved:
            self.report({"INFO"}, f"Moved {moved} asset(s) to '{cat_path}'")
            refresh_asset_browser()
            return {"FINISHED"}
        self.report({"WARNING"}, "No assets were moved")
        return {"CANCELLED"}


class IOPS_OT_AssetSearchDeleteCatalog(bpy.types.Operator):
    """Search catalogs by name and delete the chosen one"""

    bl_idname = "iops.asset_search_delete_catalog"
    bl_label = "Search Catalog (Delete)"
    bl_options = {"REGISTER", "UNDO"}
    bl_property = "catalog_choice"

    catalog_choice: EnumProperty(name="Catalog", items=_catalog_search_items)

    def invoke(self, context, event):
        context.window_manager.invoke_search_popup(self)
        return {"CANCELLED"}

    def execute(self, context):
        if self.catalog_choice == "NONE":
            self.report({"WARNING"}, "No catalog selected")
            return {"CANCELLED"}

        cat_uuid = self.catalog_choice
        lib_path = context.window_manager.IOPS_AddonProperties.iops_active_asset_library
        _name, cat_file, _catalogs = get_catalog_source_by_path(lib_path)

        if not cat_file:
            self.report({"WARNING"}, "No catalog file found")
            return {"CANCELLED"}

        ok, msg = delete_catalog(cat_file, cat_uuid)
        self.report({"INFO"} if ok else {"WARNING"}, msg)
        if ok:
            refresh_asset_browser()
            return {"FINISHED"}
        return {"CANCELLED"}


class IOPS_OT_SetAssetLibrary(bpy.types.Operator):
    """Switch the active library in the asset management pie"""

    bl_idname = "iops.set_asset_library"
    bl_label = "Set Asset Library"

    library_path: StringProperty(name="Library Path")

    def execute(self, context):
        context.window_manager.IOPS_AddonProperties.iops_active_asset_library = self.library_path
        bpy.ops.wm.call_menu_pie(name="IOPS_MT_Pie_Assets")
        return {"FINISHED"}


class IOPS_OT_SelectInAssetBrowser(bpy.types.Operator):
    """Filter the Asset Browser to show the asset related to the selection"""

    bl_idname = "iops.select_in_asset_browser"
    bl_label = "Select in Asset Browser"

    @classmethod
    def poll(cls, context):
        if resolve_assets_from_selection(context):
            return True
        cls.poll_message_set("No assets found in selection")
        return False

    def execute(self, context):
        space = find_asset_browser_space()
        if space is None:
            self.report({"WARNING"}, "No Asset Browser open")
            return {"CANCELLED"}

        params = getattr(space, "params", None)
        if params is None or not hasattr(params, "filter_search"):
            self.report({"WARNING"}, "Cannot access Asset Browser filter")
            return {"CANCELLED"}

        assets = resolve_assets_from_selection(context)
        first_name = assets[0][0].name
        params.filter_search = first_name
        tag_redraw_asset_browsers()

        label = ", ".join(f"{db.name} ({kind})" for db, kind in assets)
        self.report({"INFO"}, f"Found: {label}")
        return {"FINISHED"}


class IOPS_OT_ClearAssetBrowserFilter(bpy.types.Operator):
    """Clear the Asset Browser search filter"""

    bl_idname = "iops.clear_asset_browser_filter"
    bl_label = "Clear Asset Browser Filter"

    def execute(self, context):
        space = find_asset_browser_space()
        if space is None:
            self.report({"WARNING"}, "No Asset Browser open")
            return {"CANCELLED"}

        params = getattr(space, "params", None)
        if params is None or not hasattr(params, "filter_search"):
            self.report({"WARNING"}, "Cannot access Asset Browser filter")
            return {"CANCELLED"}

        params.filter_search = ""
        tag_redraw_asset_browsers()
        self.report({"INFO"}, "Filter cleared")
        return {"FINISHED"}


class IOPS_OT_RefreshAssetBrowser(bpy.types.Operator):
    """Refresh all open Asset Browsers"""

    bl_idname = "iops.refresh_asset_browser"
    bl_label = "Refresh Asset Browser"

    def execute(self, context):
        refresh_asset_browser()
        self.report({"INFO"}, "Asset Browser refreshed")
        return {"FINISHED"}


class IOPS_OT_Call_Pie_Assets(bpy.types.Operator):
    """Call the asset management pie menu"""

    bl_idname = "iops.call_pie_assets"
    bl_label = "IOPS Asset Management Pie"

    def execute(self, context):
        bpy.ops.wm.call_menu_pie(name="IOPS_MT_Pie_Assets")
        return {"FINISHED"}
