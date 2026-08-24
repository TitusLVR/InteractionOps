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
):
    assert hasattr(bpy.ops.iops, op_name), "missing operator: iops.%s" % op_name

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

bpy.ops.preferences.addon_disable(module="InteractionOps")
print("SMOKE_OK")
