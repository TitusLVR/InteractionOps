# Asset Management

A bundle of operators that streamline the Blender Asset Browser workflow from the 3D Viewport: marking and clearing assets, navigating catalogs through cascading menus, creating and deleting catalogs, searching by name, switching libraries, and exposing the whole set through a pie menu. All catalog-mutating operators write directly to the active library's `blender_assets.cats.txt` and refresh open Asset Browsers.

## Overview

This module replaces the click-heavy round-trip between the 3D Viewport and the Asset Browser. Selection is resolved into mark-able / move-able data-blocks (objects, parent collections, active material, active image) by `utils.assets.resolve_assets_from_selection`. Catalog targets are picked from a dynamically built tree of cascading menus or via a search popup. Library switching is done in-pie without leaving the viewport.

A pool of 32 pre-registered generic `Menu` classes (`IOPS_MT_CatPool_0` ... `IOPS_MT_CatPool_31`) is used to build the nested catalog hierarchy because `layout.menu()` requires a fixed `bl_idname`. Each node carries an `_action` field ("move" or "delete") that decides which operator the menu draws.

## Operators

### Move Asset to Catalog (bl_idname: iops.asset_move_to_catalog)

<div class="iops-meta" markdown="1">
<span class="key">bl_idname: iops.asset_move_to_catalog</span>
<span class="mode">Mode: Object</span>
<span>Context: VIEW_3D / Asset Browser</span>
<span class="modal">Modal: no</span>
<span class="hud">HUD: no</span>
</div>

Assigns the catalog UUID stored on the operator to every asset resolved from the current selection (VIEW_3D) or to `context.asset.local_id` when invoked from the Asset Browser. Only local assets can be reassigned from the browser context.

#### Properties

| Name | Type | Default | Description |
| --- | --- | --- | --- |
| catalog_uuid | String | "" | Target catalog UUID. |
| catalog_name | String | "" | Display name used in the report. |

### Mark as Asset (bl_idname: iops.asset_mark)

<div class="iops-meta" markdown="1">
<span class="key">bl_idname: iops.asset_mark</span>
<span class="mode">Mode: Object</span>
<span>Context: VIEW_3D</span>
<span class="modal">Modal: no</span>
<span class="hud">HUD: no</span>
</div>

Marks selected data-blocks as assets. The `mark_type` enum picks what to mark: selected objects, their non-scene parent collections, the active material on the active object, or the active image (resolved via `get_active_image`). Already-marked data-blocks are silently skipped.

#### Properties

| Name | Type | Default | Description |
| --- | --- | --- | --- |
| mark_type | Enum | `OBJECT` | `OBJECT` (selected objects), `COLLECTION` (parent collections of selected objects, scene root excluded), `MATERIAL` (active material on active object), `IMAGE` (active image). |

### Clear Asset (bl_idname: iops.asset_clear)

<div class="iops-meta" markdown="1">
<span class="key">bl_idname: iops.asset_clear</span>
<span class="mode">Mode: Object</span>
<span>Context: VIEW_3D</span>
<span class="modal">Modal: no</span>
<span class="hud">HUD: no</span>
</div>

Calls `asset_clear()` on every asset resolved from the current selection (objects, collections, materials).

### New Asset Catalog (bl_idname: iops.asset_create_catalog)

<div class="iops-meta" markdown="1">
<span class="key">bl_idname: iops.asset_create_catalog</span>
<span class="mode">Mode: any</span>
<span>Context: VIEW_3D / Asset Browser</span>
<span class="modal">Modal: no</span>
<span class="hud">HUD: no</span>
</div>

Creates a new catalog inside the catalog file passed in `catalog_file`. If empty, falls back to the current `.blend` file's catalog info via `get_current_file_catalog_info()`; if the file is unsaved the operator cancels with a warning. Opens a props dialog asking for `catalog_name`.

#### Properties

| Name | Type | Default | Description |
| --- | --- | --- | --- |
| catalog_name | String | "New Catalog" | Path of the new catalog. Use `/` for nesting (e.g. `Props/Furniture`). |
| catalog_file | String | "" | Path of the target `blender_assets.cats.txt`. Empty = autodetect from saved file. |

### Delete Asset Catalog (bl_idname: iops.asset_delete_catalog)

<div class="iops-meta" markdown="1">
<span class="key">bl_idname: iops.asset_delete_catalog</span>
<span class="mode">Mode: any</span>
<span>Context: VIEW_3D / Asset Browser</span>
<span class="modal">Modal: no</span>
<span class="hud">HUD: no</span>
</div>

Removes a single catalog from a catalog file. Invokes a confirmation popup before executing.

#### Properties

| Name | Type | Default | Description |
| --- | --- | --- | --- |
| catalog_uuid | String | "" | UUID of the catalog to delete. |
| catalog_file | String | "" | Catalog file path. |

### Delete Empty Catalogs (bl_idname: iops.asset_delete_empty_catalogs)

<div class="iops-meta" markdown="1">
<span class="key">bl_idname: iops.asset_delete_empty_catalogs</span>
<span class="mode">Mode: any</span>
<span>Context: VIEW_3D / Asset Browser</span>
<span class="modal">Modal: no</span>
<span class="hud">HUD: no</span>
</div>

Walks every asset data-block (`iter_all_asset_datablocks`), collects used catalog UUIDs, and deletes every catalog in `catalog_file` whose UUID is not in that set. Confirmation popup before running.

#### Properties

| Name | Type | Default | Description |
| --- | --- | --- | --- |
| catalog_file | String | "" | Catalog file path. Required (cancels if empty). |

### Search Catalog (Move) (bl_idname: iops.asset_search_move_to_catalog)

<div class="iops-meta" markdown="1">
<span class="key">bl_idname: iops.asset_search_move_to_catalog</span>
<span class="mode">Mode: Object</span>
<span>Context: VIEW_3D / Asset Browser</span>
<span class="modal">Modal: no</span>
<span class="hud">HUD: no</span>
</div>

Opens an `invoke_search_popup` listing every catalog in the active library (`wm.IOPS_AddonProperties.iops_active_asset_library`). Catalog items show a shortened name (last two path segments) with the full path in the tooltip. Picking a catalog assigns it to the resolved selection.

#### Properties

| Name | Type | Default | Description |
| --- | --- | --- | --- |
| catalog_choice | Enum (dynamic) | first item | Catalogs from the active library, or `NONE` if the library has none. |

### Search Catalog (Delete) (bl_idname: iops.asset_search_delete_catalog)

<div class="iops-meta" markdown="1">
<span class="key">bl_idname: iops.asset_search_delete_catalog</span>
<span class="mode">Mode: any</span>
<span>Context: VIEW_3D / Asset Browser</span>
<span class="modal">Modal: no</span>
<span class="hud">HUD: no</span>
</div>

Same search popup as above, but deletes the chosen catalog from the active library's catalog file.

#### Properties

| Name | Type | Default | Description |
| --- | --- | --- | --- |
| catalog_choice | Enum (dynamic) | first item | Catalog list from the active library. |

### Set Asset Library (bl_idname: iops.set_asset_library)

<div class="iops-meta" markdown="1">
<span class="key">bl_idname: iops.set_asset_library</span>
<span class="mode">Mode: any</span>
<span>Context: VIEW_3D</span>
<span class="modal">Modal: no</span>
<span class="hud">HUD: no</span>
</div>

Stores `library_path` into `wm.IOPS_AddonProperties.iops_active_asset_library` and re-opens the assets pie (`IOPS_MT_Pie_Assets`).

#### Properties

| Name | Type | Default | Description |
| --- | --- | --- | --- |
| library_path | String | "" | Filesystem path of the library to activate. |

### Select in Asset Browser (bl_idname: iops.select_in_asset_browser)

<div class="iops-meta" markdown="1">
<span class="key">bl_idname: iops.select_in_asset_browser</span>
<span class="mode">Mode: Object</span>
<span>Context: VIEW_3D</span>
<span class="modal">Modal: no</span>
<span class="hud">HUD: no</span>
</div>

Finds an open Asset Browser (`find_asset_browser_space`) and sets its `params.filter_search` to the name of the first asset resolved from the selection. Reports every matching asset and its kind. No-op (warning) if no Asset Browser is open or its `params` are unavailable.

### Clear Asset Browser Filter (bl_idname: iops.clear_asset_browser_filter)

<div class="iops-meta" markdown="1">
<span class="key">bl_idname: iops.clear_asset_browser_filter</span>
<span class="mode">Mode: any</span>
<span>Context: VIEW_3D / Asset Browser</span>
<span class="modal">Modal: no</span>
<span class="hud">HUD: no</span>
</div>

Empties `params.filter_search` on the first found Asset Browser and tags it for redraw.

### Refresh Asset Browser (bl_idname: iops.refresh_asset_browser)

<div class="iops-meta" markdown="1">
<span class="key">bl_idname: iops.refresh_asset_browser</span>
<span class="mode">Mode: any</span>
<span>Context: VIEW_3D / Asset Browser</span>
<span class="modal">Modal: no</span>
<span class="hud">HUD: no</span>
</div>

Calls `refresh_asset_browser()` to force every open Asset Browser to re-read its library. Use after external catalog edits.

### Expand Collection to Scene (bl_idname: iops.expand_instance_collection)

<div class="iops-meta" markdown="1">
<span class="key">bl_idname: iops.expand_instance_collection</span>
<span class="mode">Mode: Object</span>
<span>Context: VIEW_3D</span>
<span class="modal">Modal: no</span>
<span class="hud">HUD: no</span>
</div>

Active object must be an `EMPTY` with `instance_type == "COLLECTION"` and a non-null `instance_collection`. Wraps `bpy.ops.object.duplicates_make_real(use_base_parent=True, use_hierarchy=True)` to turn the collection instance into real hierarchy parented to the instancer empty.

### IOPS Asset Management Pie (bl_idname: iops.call_pie_assets)

<div class="iops-meta" markdown="1">
<span class="key">bl_idname: iops.call_pie_assets</span>
<span class="mode">Mode: any</span>
<span>Context: VIEW_3D</span>
<span class="modal">Modal: no</span>
<span class="hud">HUD: no</span>
</div>

Wraps `wm.call_menu_pie(name="IOPS_MT_Pie_Assets")`. Default keymap: <kbd>Ctrl</kbd>+<kbd>Alt</kbd>+<kbd>Shift</kbd>+<kbd>A</kbd>.

## Usage

- The pie (`iops.call_pie_assets`) is the canonical entry point — every other operator here is reachable through it.
- Default keymap binding: <kbd>Ctrl</kbd>+<kbd>Alt</kbd>+<kbd>Shift</kbd>+<kbd>A</kbd> in 3D View. All other operators in this module have no default keymap binding and are invoked via the pie, the Asset Browser context menu, or operator search.
- For mark/move/clear, selection must resolve at least one valid asset; the pie's library switching depends on `IOPS_AddonProperties.iops_active_asset_library` being set.
- Creating catalogs requires the current `.blend` to be saved unless `catalog_file` is supplied explicitly.

## Notes

- 32 pool `Menu` classes (`IOPS_MT_CatPool_0` ... `IOPS_MT_CatPool_31`) are registered alongside the operators via `register_pool_menus()`. Catalog trees deeper than 32 inner nodes will draw orphan leaves (no submenu) rather than crash.
- Search popups (`iops.asset_search_move_to_catalog`, `iops.asset_search_delete_catalog`) cache the enum items in a module-level list (`_catalog_search_items_cache`) so Blender keeps strong references during the popup's lifetime.
- The pie operator (`iops.set_asset_library`) re-opens the same pie after switching libraries, so library switches feel instantaneous.
- `iops.asset_clear` does not unmark images (only objects, collections, materials) because `resolve_assets_from_selection` does not return images.
- All catalog-mutating operators call `refresh_asset_browser()` on success.

## Related

- [Asset Pie Menu](../ui/ui_pies.md) — `IOPS_MT_Pie_Assets`, the pie this module feeds.
