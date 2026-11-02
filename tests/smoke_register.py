"""Headless registration smoke test. Run via:
blender --background --factory-startup --python tests/smoke_register.py
with BLENDER_USER_SCRIPTS pointing at a scripts dir whose addons/
contains this repo as 'InteractionOps' (junction)."""
import bpy

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
    "instance_edit_start",
    "instance_edit_stop",
    "instance_edit_restore",
    "instance_edit_commit",
    "instance_edit_cancel",
    "instance_edit_rollback_source",
    "instance_edit_backups_cleanup",
):
    assert hasattr(bpy.ops.iops, op_name), "missing operator: iops.%s" % op_name
    if op_name.startswith("instance_edit_"):
        # hasattr is always True (lazy wrapper): resolve the RNA type.
        getattr(bpy.ops.iops, op_name).get_rna_type()

for op_name in ("node_spawn_connected", "node_pie_add_search", "call_pie_node"):
    assert hasattr(bpy.ops.iops, op_name), "missing operator: iops.%s" % op_name

assert hasattr(bpy.types, "IOPS_MT_Pie_Node"), "node pie menu not registered"

prefs = bpy.context.preferences.addons["InteractionOps"].preferences
for prop_name in ("library_master_file", "library_preview_size", "library_shader_group"):
    assert hasattr(prefs, prop_name), "missing pref: %s" % prop_name

wm = bpy.context.window_manager
for prop_name in ("iops_library_status", "iops_library_busy", "iops_library_placement"):
    assert hasattr(wm, prop_name), "missing WM prop: %s" % prop_name

assert hasattr(bpy.types, "IOPS_PT_Library"), "panel not registered"
assert hasattr(bpy.types, "IOPS_MT_LibraryPublishSub"), "publish submenu not registered"

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
                  "cursor_place_axis_size", "cursor_place_axis_letters"):
    assert hasattr(prefs, prop_name), "missing pref: %s" % prop_name
km = bpy.context.window_manager.keyconfigs.addon.keymaps.get("3D View")
assert any(
    kmi.idname == "iops.cursor_place" and kmi.type == "RIGHTMOUSE" and kmi.shift
    for kmi in km.keymap_items
), "iops.cursor_place not bound to Shift+RMB in 3D View keymap"

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

bpy.ops.preferences.addon_disable(module="InteractionOps")
print("SMOKE_OK")
