"""Headless registration smoke test. Run with isolated user folders (the
script refuses the real ones, see tests/blender/_isolation.py):
BLENDER_USER_RESOURCES="$TEMP/iops_blender_res" blender --background --factory-startup --python tests/smoke_register.py
with the add-on importable as 'InteractionOps': the repo's parent dir on
sys.path (--python-expr "import sys; sys.path.insert(0, <parent>)" before
--python), or BLENDER_USER_SCRIPTS pointing at a scripts dir under the temp
dir (iOps saves its preferences there) whose addons/ contains this repo as
'InteractionOps' (junction)."""
import os
import sys

import addon_utils
import bpy

# refuse to run against the real user resources (enable / disable write there)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "blender"))
from _isolation import require_isolated_user_resources  # noqa: E402

require_isolated_user_resources()

bpy.ops.preferences.addon_enable(module="InteractionOps")
assert "InteractionOps" in bpy.context.preferences.addons, "addon not enabled"

for op_name in (
    "library_publish",
    "library_refresh",
    "library_find_master",
    "library_insert_asset",
    "library_remove_asset",
    "library_popup",
    "mesh_falloff_move",
    "mesh_falloff_rotate",
    "mesh_falloff_scale",
    "mesh_falloff_normal_offset",
    "mesh_falloff_fit",
    "mesh_field_edge_slide",
    "mesh_field_offset_edge_slide",
    "instance_edit_start",
    "instance_edit_stop",
    "instance_edit_restore",
    "instance_edit_commit",
    "instance_edit_cancel",
    "instance_edit_rollback_source",
    "instance_edit_backups_cleanup",
    "mesh_edge_slide",
    "mesh_uv_stripe",
):
    assert hasattr(bpy.ops.iops, op_name), f"missing operator: iops.{op_name}"
    if op_name.startswith(("instance_edit_", "mesh_")):
        # hasattr is always True (lazy wrapper): resolve the RNA type.
        getattr(bpy.ops.iops, op_name).get_rna_type()

# UV Stripe (Interactive) folded into UV Stripe (every invoke is the interactive mode)
assert "IOPS_OT_mesh_uv_stripe_interactive" not in dir(bpy.types), "iops.mesh_uv_stripe_interactive still registered"

for op_name in ("node_spawn_connected", "node_pie_add_search", "call_pie_node",
                "call_pie_falloff"):
    assert hasattr(bpy.ops.iops, op_name), f"missing operator: iops.{op_name}"

assert hasattr(bpy.types, "IOPS_MT_Pie_Node"), "node pie menu not registered"
assert hasattr(bpy.types, "IOPS_MT_Pie_Falloff"), "falloff pie menu not registered"

prefs = bpy.context.preferences.addons["InteractionOps"].preferences
for prop_name in ("library_master_file", "library_preview_size", "library_shader_group"):
    assert hasattr(prefs, prop_name), f"missing pref: {prop_name}"

wm = bpy.context.window_manager
for prop_name in ("iops_library_status", "iops_library_busy", "iops_library_placement"):
    assert hasattr(wm, prop_name), f"missing WM prop: {prop_name}"

assert hasattr(bpy.types, "IOPS_PT_Library"), "panel not registered"
assert hasattr(bpy.types, "IOPS_MT_LibraryPublishSub"), "publish submenu not registered"

assert "iops_cursor_grid_step" in bpy.types.Scene.bl_rna.properties, "missing scene prop iops_cursor_grid_step"
km = bpy.context.window_manager.keyconfigs.addon.keymaps.get("3D View")
assert km is not None, "addon '3D View' keymap missing"
assert km.space_type == "VIEW_3D", "3D View keymap has wrong space_type"
assert any(
    kmi.idname == "iops.library_popup" for kmi in km.keymap_items
), "iops.library_popup not bound in 3D View keymap"

km = bpy.context.window_manager.keyconfigs.addon.keymaps.get("Node Editor")
assert km is not None, "addon 'Node Editor' keymap missing"
assert km.space_type == "NODE_EDITOR", "Node Editor keymap has wrong space_type"
assert any(
    kmi.idname == "iops.call_pie_node" for kmi in km.keymap_items
), "iops.call_pie_node not bound in Node Editor keymap"

# Cursor Place (iops.cursor_place)
# hasattr(bpy.ops.iops, ...) is always True (lazy wrapper) -- resolve the RNA type.
bpy.ops.iops.cursor_place.get_rna_type()
for prop_name in ("cursor_place_normal_axis", "cursor_place_edge_axis",
                  "cursor_place_axis_size", "cursor_place_axis_letters",
                  "cursor_place_floor_snap", "cursor_place_floor_grid_px"):
    assert hasattr(prefs, prop_name), f"missing pref: {prop_name}"
km = bpy.context.window_manager.keyconfigs.addon.keymaps.get("3D View")
assert any(
    kmi.idname == "iops.cursor_place" and kmi.type == "RIGHTMOUSE" and kmi.shift
    for kmi in km.keymap_items
), "iops.cursor_place not bound to Shift+RMB in 3D View keymap"

# Visual UV runs in the 3D viewport ("Mesh") and the UV Editor: its binding
# is mirrored into "UV Editor" once (utils/functions.MIRROR_KEYMAPS), and the
# mirror is not saved with the user's hotkeys.
for km_name in ("Mesh", "UV Editor"):
    km = bpy.context.window_manager.keyconfigs.addon.keymaps.get(km_name)
    hits = [kmi for kmi in km.keymap_items if kmi.idname == "iops.mesh_visual_uv"]
    assert len(hits) == 1, f"iops.mesh_visual_uv bound {len(hits)} times in {km_name}"
    assert (hits[0].type, hits[0].ctrl, hits[0].alt) == ("U", True, True), f"{km_name}: {hits[0].type}"
from InteractionOps.operators.hotkeys.save_hotkeys import get_iops_keys  # noqa: E402
assert sum(1 for k in get_iops_keys() if k[0] == "iops.mesh_visual_uv") == 1, "the mirror would be saved"

# iOps Attributes (Task 4 operators)
for op_name in ("attr_set_value", "attr_fill", "attr_new", "attr_remove",
                "attr_duplicate", "attr_convert", "attr_refresh"):
    getattr(bpy.ops.iops, op_name).get_rna_type()

# iOps Attributes panel (Task 5)
assert hasattr(bpy.types, "IOPS_PT_attributes_panel"), "attributes panel not registered"
assert hasattr(bpy.types, "IOPS_UL_Attributes"), "attributes UIList not registered"
assert hasattr(bpy.types, "IOPS_MT_attr_specials"), "attributes specials menu not registered"
assert hasattr(wm, "iops_attr"), "missing WM prop: iops_attr"

# iOps Attributes tools (Task 6)
for op_name in ("attr_gradient", "attr_math", "attr_smooth", "attr_randomize",
                "attr_copy", "attr_from_vgroup", "attr_to_vgroup",
                "attr_select_by_value"):
    getattr(bpy.ops.iops, op_name).get_rna_type()

# iOps Attributes preview (Task 7)
assert "preview" in wm.iops_attr.bl_rna.properties, "missing preview toggle"
assert hasattr(bpy.types, "IOPS_PT_attributes_preview"), "preview sub-panel not registered"
assert hasattr(prefs, "attr_preview_max_labels"), "missing pref: attr_preview_max_labels"

# iOps Materials panel
for op_name in ("material_assign", "material_new", "materials_merge_duplicates",
                "materials_remap", "materials_remove_empty_slots",
                "materials_copy_from_active",
                "materials_select_users", "materials_remove_unused_slots",
                "materials_clear", "materials_delete_unused",
                "materials_gallery_page", "call_panel_materials",
                "material_assign_asset", "material_asset_select_users",
                "materials_mark_asset", "materials_clear_asset",
                "materials_library_add", "material_assign_drop",
                "material_shelf_event"):
    getattr(bpy.ops.iops, op_name).get_rna_type()
for cls_name in ("IOPS_PT_Materials_Panel", "IOPS_UL_Materials",
                 "IOPS_MT_materials_functions", "IOPS_AST_materials",
                 "IOPS_PT_materials_shelf_search"):
    assert hasattr(bpy.types, cls_name), f"{cls_name} not registered"
assert hasattr(wm, "iops_materials"), "missing WM prop: iops_materials"
for prop_name in ("materials_thumbnail_size", "materials_list_rows",
                  "materials_gallery_rows", "materials_stack_duplicates",
                  "materials_default_view", "materials_ui_mode",
                  "materials_import_method", "materials_library",
                  "materials_popup_width", "materials_shelf_height",
                  "materials_shelf_thumbnail", "materials_highlight_hover",
                  "materials_shelf_tools_direction", "materials_shelf_align",
                  "materials_shelf_width",
                  "materials_shelf_tools_position"):
    assert hasattr(prefs, prop_name), f"missing pref: {prop_name}"
from InteractionOps.prefs.iops_prefs import get_iops_prefs  # noqa: E402
assert "MATERIALS_PANEL" in get_iops_prefs(), "prefs JSON lacks MATERIALS_PANEL"

# not the preferences operator: it also re-syncs the extension wheels of the
# user resource folder for the (empty) set of extensions a factory session has
addon_utils.disable("InteractionOps", default_set=True, refresh_handled=True)
print("SMOKE_OK")
