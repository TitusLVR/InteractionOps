# Menus, Panels and Windows

This page covers everything that is **not** a pie: pop-up panels invoked through `wm.call_panel`, sidebar panels living in the `iOps` tab of the N-panel, and the floating Modifier window.

---

## IOPS TPS panel (Transformation / Pivot / Snapping)

<div class="iops-meta" markdown="1">
<span class="key">bl_idname: IOPS_PT_TPS_Panel</span>
<span class="mode">Context: VIEW_3D and IMAGE_EDITOR</span>
<span>Type: Pop-up panel</span>
</div>

Source: `ui/iops_tm_panel.py`. Invoked by `iops.call_panel_tps`.

**Default binding:** `Ctrl + BUTTON4MOUSE` (mouse back button with Ctrl).

The panel renders different layouts depending on `context.area.type`.

### VIEW_3D layout

Top toolbar row (left to right):

- `space_data.lock_cursor` toggle (also drives `inputs.use_mouse_depth_navigate`).
- `inputs.use_rotate_around_active`.
- `tool_settings.use_mesh_automerge` and `use_mesh_automerge_and_split`.
- `use_transform_correct_face_attributes`, `use_transform_correct_keep_connected`, `use_edge_path_live_unwrap`.
- `iops.transform_orientation_create` — create a custom transform orientation from the current selection.
- `iops.homonize_uvmaps_names` — rename all UV layers on selected meshes to `ch1`, `ch2`, ...
- `iops.uvmaps_cleanup` — remove every UV layer from selected meshes.
- `iops.object_name_from_active` — propagate active object's name to selection.
- Optional rows for third-party addons when detected: `Batch Operations`, `Unreal OPS` (add/remove from active collection, make active by object, select collection objects, cleanup empty), `MACHIN3tools` shading pie (smooth/flat/auto-smooth/clear-normals plus 30°/60°/90°/180° angle presets via `iops.object_auto_smooth` or `machin3.toggle_auto_smooth` depending on Blender version).

Body is a 4-column `grid_flow`:

| Column | Contents |
|---|---|
| 1 — Transformation | Gizmo toggles M/R/S (translate/rotate/scale gizmos), `transform_orientation_slots[0].type`, custom-orientation rename + `iops.transform_orientation_delete`. |
| 2 — Pivot Point | `tool_settings.transform_pivot_point` expanded, `iops.edit_origin` toggle (drives `use_transform_data_origin` and active's `show_in_front`), `use_transform_pivot_point_align`, `use_transform_skip_children`. |
| 3 — Snapping | `snap_elements` dropdown, `snap_target` expand, self/align-rotation toggles, conditional `use_snap_peel_object` when `VOLUME` is in snap elements, conditional `se_snap_to_same_target` when `FACE_NEAREST` is set, backface culling, selectable, translate/rotate/scale snap toggles, `snap_angle_increment_3d` + precision. |
| 4 — Snap Combos | Eight `iops.set_snap_combo` buttons (idx 1..8, labelled A..H) recalling stored snap presets. |

### IMAGE_EDITOR layout

- Top row: `iops.reload_images`, `space_data.display_channels` expand, `show_repeat`.
- Body (MESH + EDIT_MESH only): 3 columns — UV selection mode block (`use_uv_select_sync`, `uv_select_mode`, `uv_sticky_select_mode`), Pivot Point expand, Snap block (`snap_uv_element`, optional VERTEX target, Move/Rotate/Scale affect toggles, `snap_angle_increment_2d` + precision).

---

## IOPS Data panel

<div class="iops-meta" markdown="1">
<span class="key">bl_idname: IOPS_PT_DATA_Panel</span>
<span class="mode">Context: VIEW_3D or UV editor + active MESH</span>
<span>Type: Pop-up panel</span>
</div>

Source: `ui/iops_data_panel.py`. Invoked by `iops.call_panel_data`.

**Default binding:** `Ctrl + Shift + BUTTON4MOUSE`.

If the active object's mesh data is None (e.g. linked object) the panel reports `Mesh data not available (linked object)` and exits early.

### Top toolbar row

- `iops.homonize_uvmaps_names` (icon `UV_DATA`).
- `space_data.show_repeat` toggle when invoked from a UV editor.
- UV-channel "keep N" cleanup chain (labelled `All`, `2+`, `3+`, `4+`, `5+`, `6+`, `7+`, `8`): `iops.object_clean_uvmap_0` through `iops.object_clean_uvmap_7`.

### Body — main row with 3 lists side by side

**UVMaps**
- `template_list` of `me.uv_layers` (MESH_UL_uvmaps, 5 rows).
- Side buttons: `iops.uv_add_uvmap`, `iops.uv_remove_uvmap_by_active_name`, `iops.uv_active_uvmap_by_active_object`, `iops.mesh_uv_channel_hop`.

**Color Attributes** (Blender 3.2+)
- `template_list` of `me.color_attributes` (MESH_UL_color_attributes, 5 rows). Active index is mirrored through `props.iops_active_color_index` with a `_iops_color_sync_lock` guard to avoid retag propagation on object-switch redraws.
- Side buttons: `geometry.color_attribute_add`, `geometry.color_attribute_remove`, `MESH_MT_color_attribute_context_menu`.
- On Blender < 3.2 the panel falls back to a `MESH_UL_vcols` list with `mesh.vertex_color_add` / `mesh.vertex_color_remove`.

**Vertex Groups**
- `template_list` of `ob.vertex_groups` (MESH_UL_vgroups, 5 rows).
- Side buttons: `object.vertex_group_add`, `object.vertex_group_remove` (forced `all_unlocked = all = False`), `MESH_MT_vertex_group_context_menu`, and when a group is active, `object.vertex_group_move` UP/DOWN.
- When in EDIT or in WEIGHT_PAINT with vertex mask, a second row exposes `object.vertex_group_assign`, `vertex_group_remove_from`, `vertex_group_select`, `vertex_group_deselect`, plus a `vertex_group_weight` slider.

### Body — Materials block

- `template_list` of `ob.material_slots` (MATERIAL_UL_matslots, 3 rows or 5 if sortable).
- Side buttons: `object.material_slot_add`, `material_slot_remove`, `MATERIAL_MT_context_menu`, `material_slot_move` UP/DOWN when sortable.
- `template_ID(ob, "active_material", new="material.new")` row.
- In EDIT mode: row with `material_slot_assign`, `material_slot_select`, `material_slot_deselect`.

---

## IOPS Transform panel

<div class="iops-meta" markdown="1">
<span class="key">bl_idname: IOPS_PT_TM_Panel</span>
<span class="mode">Context: VIEW_3D, OBJECT mode, supported object type</span>
<span>Type: Pop-up panel</span>
</div>

Source: `ui/iops_tm_panel.py`. Invoked by `iops.call_panel_tm`.

**Default binding:** `Ctrl + Shift + T`.

Compact (8 ui units wide) column showing the active object's `location`, `rotation_euler`, `scale`, and — for `MESH`/`CURVE`/`FONT`/`ARMATURE`/`META`/`GPENCIL` — `dimensions`.

Poll requires an active object of any of: MESH, CURVE, EMPTY, FONT, LIGHT, CAMERA, ARMATURE, LATTICE, META, SPEAKER, GPENCIL, SURFACE, VOLUME, LIGHT_PROBE in OBJECT mode.

---

## Collection Append panel

<div class="iops-meta" markdown="1">
<span class="key">bl_idname: IOPS_PT_Collection_Append_Panel</span>
<span class="mode">Context: VIEW_3D, OBJECT mode</span>
<span>Type: Sidebar panel (iOps tab, default closed)</span>
</div>

Source: `ui/iops_tm_panel.py`. Also reachable as a pop-up via `iops.call_panel_collection_append`.

**Default binding:** no default binding.

Three-step workflow against a selected linked instance:

1. **Scan** — `iops.scan_source_collections` populates `props.iops_source_collections`.
2. **Select** — `template_list` (`IOPS_UL_SourceCollectionsList`, 5 rows) of source collections with per-row `is_selected` checkboxes. Below: `iops.select_all_collections` with `action=SELECT` and `action=DESELECT`.
3. **Append** — `iops.instance_collection_append` with a live counter `Append (N selected)`.

Empty state shows `No collections scanned yet`. A help box at the bottom restates the steps.

---

## IOPS Object Color panel

<div class="iops-meta" markdown="1">
<span class="key">bl_idname: IOPS_PT_Object_Color_Panel</span>
<span class="mode">Context: VIEW_3D, iOps sidebar tab</span>
<span>Type: Sidebar panel (default closed)</span>
</div>

Source: `ui/iops_object_color_panel.py`.

**Default binding:** no default binding (sidebar panel).

Rows:

- Color picker bound to `scene.IOPS.iops_object_color`.
- `iops.object_color_copy_from_active` (icon `EYEDROPPER`) — loads the active object's `obj.color` into the picker.
- `iops.object_color_apply` (icon `COLOR`) — pushes the picker color onto every selected object's `obj.color`.
- "Recent" two-row palette: `RECENT_SLOTS` (8 by default, imported from `operators.object_color`) swatches `iops_object_color_recent_<i>` each with a numbered `iops.object_color_apply_recent` button (`index = i`). Picking a swatch applies that color to selection and loads it into the picker; swatch order is not reshuffled by clicks.

---

## IOPS Vertex Color panel

<div class="iops-meta" markdown="1">
<span class="key">bl_idname: IOPS_PT_VCol_Panel</span>
<span class="mode">Context: VIEW_3D, iOps sidebar tab</span>
<span>Type: Sidebar panel (default closed)</span>
</div>

Source: `ui/iops_tm_panel.py`.

**Default binding:** no default binding.

- Active image-paint brush color picker (only if a brush exists).
- In OBJECT mode: `template_ID` palette picker on `tool_settings.image_paint.palette` with `palette.new`, plus `template_palette` row when a palette is set.
- `iops.mesh_assign_vertex_color` — Set Color.
- `iops.mesh_assign_vertex_color_alpha` — Set Alpha.

---

## Modifier window (floating)

<div class="iops-meta" markdown="1">
<span class="key">bl_idname: iops.window_modifiers</span>
<span class="mode">Context: any (requires a valid window context)</span>
<span>Type: Floating window (Properties editor)</span>
</div>

Source: `ui/iops_mod_window.py`. Operator label: `IOPS Modifiers Window`.

**Default binding:** `Ctrl + Shift + F19`.

Toggling behaviour — if any single-area `PROPERTIES` floating window exists it is closed and the operator returns. Otherwise a new 350x550 window is created.

Two creation modes, selected by `addon prefs.modifier_window_method`:

- `RENDER` — temporarily overwrites `scene.render.resolution_x/y` to 350x550, calls `bpy.ops.render.view_show("INVOKE_DEFAULT")`, restores resolution, removes the leftover `Render Result` image. After the window opens the operator shows the Navigation Bar and flips its alignment to the right side via `screen.region_toggle` + `screen.region_flip`.
- `NEW_WINDOW` — calls `bpy.ops.wm.window_new()` under a `temp_override(window, screen)`. After the area is retyped to `PROPERTIES` the operator looks the window up by HWND via `ctypes` (Windows-only path through `user32.EnumWindows` / `SetWindowPos`) and force-sizes it to 350x550. Header and Navigation Bar are hidden via `screen.region_toggle`.

In both modes the area is set to `PROPERTIES` and only the Modifiers tab is left visible — every other `space.show_properties_*` flag (tool, scene, render, output, view_layer, world, collection, object, constraints, data, bone, bone_constraints, material, texture, particles, physics, effects) is set to `False`; only `show_properties_modifiers` stays `True`.

The detector for "is there already a modifier window" iterates `wm.windows[1:]` looking for a single-area `PROPERTIES` window. That window is closed via `wm.window_close` under a `temp_override(window=...)`.
