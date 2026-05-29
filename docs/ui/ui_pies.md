# Pie Menus

InteractionOps ships four pie menus. Every pie is fronted by an `iops.call_pie_*` operator that wraps `wm.call_menu_pie`.

Slot legend used below: **W** = 4 (LEFT), **E** = 6 (RIGHT), **S** = 2 (BOTTOM), **N** = 8 (TOP), **NW** = 7 (TOP-LEFT), **NE** = 9 (TOP-RIGHT), **SW** = 1 (BOTTOM-LEFT), **SE** = 3 (BOTTOM-RIGHT). Empty slots are drawn as separators.

---

## IOPS Pie Menu (main)

<div class="iops-meta" markdown="1">
<span class="key">bl_idname (call op): iops.call_pie_menu</span>
<span class="key">Menu class: IOPS_MT_Pie_Menu</span>
<span class="mode">Context: any</span>
<span>Type: Pie menu</span>
</div>

Source: `ui/iops_pie_menu.py`.

**Default binding:** `Ctrl + Shift + Q`.

Layout is not a classic radial — it uses `layout.menu_pie()` for cardinals but renders the W and S slots as full sub-panels (boxes), and N/E light up only when companion addons are present.

| Slot | Contents |
|---|---|
| W (4) | "IOPS" box. `scene.IOPS.iops_vertex_color` picker. `iops.mesh_assign_vertex_color` (Set Vertex Color). White / Grey / Black presets via the same operator with `fill_color_white/grey/black=True`. `iops.mesh_assign_vertex_color_alpha`. Then a stack of operators: `iops.materials_from_textures`, `iops.object_replace`, `iops.object_aligner`, `iops.object_radial_array`, `iops.object_align_between_two`, `iops.mesh_quick_snap`, `iops.mesh_quick_connect`, `iops.mesh_to_tris_to_quads`, `iops.object_drop_it`, `iops.object_kitbash_grid`, then the Easy Modifier group (`iops.modifier_easy_array_caps`, `_array_curve`, `_curve`, `_shwarp`), `iops.assets_render_asset_thumbnail`, `iops.reload_libraries`, `iops.reload_images`. |
| E (6) | "BMax" box if `BMAX Connector` is enabled — `bmax.export`/`bmax.import` (or USD variants depending on `prefs.file_format`), plus L/R/S reset-on-export toggles. "BMoI" box if `BMOI Connector` is enabled — `bmoi3d.export`/`bmoi3d.import`. |
| S (2) | "B2RUVL" box. UV map mode + uvMap dropdowns from `wm.B2RUVL_PanelProperties`. `b2ruvl.send_to_uvlayout` (enabled when path is set), `b2ruvl.send_to_rizomuv`, `b2ruvl.retake_rizomuv`. |
| N (8) | "ForgottenTools" box when `Forgotten Tools` is enabled AND mode is `EDIT_MESH` — `forgotten.mesh_connect_spread`, `forgotten.mesh_grid_fill_all`, `forgotten.mesh_dice_faces`, `forgotten.mesh_hinge`, `mesh.forgotten_separate_duplicate`, and a `wm.call_panel` opening `FORGOTTEN_PT_SelectionSetsPanel`. Otherwise empty. |
| NW (7) | Empty. |
| NE (9) | `mesh.optiloops` when `Optiloops` is enabled AND mode is `EDIT_MESH`. Otherwise empty. |
| SW (1) | Empty. |
| SE (3) | Empty. |

---

## IOPS Pie Edit (object-type aware)

<div class="iops-meta" markdown="1">
<span class="key">bl_idname (call op): iops.call_pie_edit</span>
<span class="key">Menu class: IOPS_MT_Pie_Edit</span>
<span class="mode">Context: VIEW_3D or IMAGE_EDITOR; needs active object or "Open Asset in Current Blender" poll</span>
<span>Type: Pie menu</span>
</div>

Source: `ui/iops_pie_edit.py`.

**Default binding:** `Ctrl + Shift + F19`.

This pie reshapes itself by `context.area.type`, `context.object.type` and `obj.mode`. Cardinal slots always call `iops.function_f1` / `_f2` / `_f3` / `_esc` (and sometimes `_f4`); only the label and icon change.

### VIEW_3D, no active object

Only "Open Asset in Current Blender" is drawn if its poll passes (via `draw_open_asset_in_pie_if_poll`).

### VIEW_3D, EMPTY with linked instance_collection (COLLECTION instance type)

Adds a multi-part layout:

- The shared "Empty Size + Display + Image-row" block from `draw_empty_pie_size_display_and_image` (see below).
- **S (2)** `object.duplicates_make_real` with `use_hierarchy=True` — "Make Instances Real".
- **N (8)** `iops.expand_instance_collection` — "Expand Collection to Scene".
- **NW (7)** `iops.open_asset_in_new_blender` (only when `instance_collection.library` is set) — labelled `Open <filename>`, sets `blendpath` and `library`.
- **NE (9)** `iops.reload_instance_library` — labelled `Reload <filename>`.

### VIEW_3D, plain EMPTY (no instance collection)

Just the shared Empty block.

### VIEW_3D, any other object type

`draw_edit_pie_cardinals` draws four cardinal slots that map to `iops.function_f1/f2/f3/esc`. Label + icon come from `get_text_icon(context, "fN" | "esc")` and depend on type/mode:

| Type | Mode | f1 | f2 | f3 | esc |
|---|---|---|---|---|---|
| MESH | any | Vertex | Edge | Face | Esc |
| ARMATURE | OBJECT | Edit Mode | Pose Mode | Set Parent to Bone | Esc |
| ARMATURE | EDIT | Object Mode | Pose Mode | Set Parent to Bone | Object Mode |
| ARMATURE | POSE | Edit Mode | Object Mode | Set Parent to Bone | Object Mode |
| EMPTY | any | Open Instance Collection .blend | Realize Instances | F3 | Esc |
| CURVE | OBJECT | Edit Mode | Duplicate | Switch Direction | Toggle Cyclic |
| CURVE | EDIT | Object Mode | Subdivide | Spline Type | Esc |
| CURVES | OBJECT | Edit Mode | Duplicate | Toggle Cyclic | Esc |
| CURVES | EDIT / EDIT_CURVES | Object Mode | Subdivide | Cyclic | Esc |
| CURVES | SCULPT_CURVES | Edit Mode | Object Mode | Sculpt Toggle | Esc |
| CAMERA | any | Active Camera | Camera View | Cam to View | Toggle DOF (also f4=Lens +5) |
| LIGHT | any | Duplicate | Toggle Shadow | Boost Power | Cycle Type (also f4=Toggle Specular) |
| FONT | OBJECT | Edit Mode | Convert to Mesh | To Curve | Esc |
| FONT | EDIT | Object Mode | Duplicate | Bold | Esc |
| LATTICE | OBJECT | Edit Mode | Duplicate | F3 | Esc |
| LATTICE | EDIT | Object Mode | Duplicate | Flip U | Esc |
| META | OBJECT | Edit Mode | Duplicate | F3 | Finer Preview |
| META | EDIT | Object Mode | Duplicate | Threshold - | Esc |
| LIGHT_PROBE | any | Duplicate | + Influence | - Influence | Hide Viewport (also f4=Clip/Parallax) |

In OBJECT mode an additional **type-extension box** is drawn next to the cardinals by `draw_edit_pie_type_extensions`, listing common RNA props for the active object via `_PIE_OBJECT_MODE_DATA_SPECS`. Supported: CURVE (bevel_depth, bevel_object, resolution_u, dimensions), CURVES (surface_scale, surface_uv_map), SURFACE (resolution_u/v), FONT (size, extrude, body_alignment, space_character), META (threshold, resolution, render_resolution), LATTICE (points_u/v/w, use_outside, interpolation_type_u), ARMATURE (display_type, show_in_front), CAMERA (type, lens, ortho_scale, clip_start/end, dof.use_dof, aperture_fstop, focus_distance), LIGHT (type, energy, color, exposure, diffuse_factor, use_temperature, temperature), LIGHT_PROBE (influence_distance, clip_start/end, show_influence, show_clip, use_data_display), SPEAKER (volume, muted), VOLUME (density, display_density), POINTCLOUD (display_percentage), GPENCIL / GREASEPENCIL (use_grease_pencil_lights, use_grease_pencil_on_back).

For MESH + EDIT mode, an extra `iops.mesh_visual_uv` button (icon `UV`) is appended.

### IMAGE_EDITOR

Cardinals: `iops.function_f1` Vertex, `iops.function_f2` Edge, `iops.function_f3` Face, `iops.function_esc`. When `tool_settings.use_uv_select_sync` is OFF an extra slot adds `iops.function_f4` Island.

### Shared Empty block (`draw_empty_pie_size_display_and_image`)

Box 1 — Size:
- Quick-set buttons calling `iops.set_empty_size` with sizes 0.1, 0.5, 1.0, 2.0, 5.0, 10.0.
- `empty_display_size` prop slider.
- `iops.copy_empty_size_from_active` (icon `COPYDOWN`).

Box 2 — Display:
- 2-column grid of `iops.set_empty_display` calls: Plain Axes / Arrows / Single Arrow / Circle / Cube / Sphere / Cone / Image.
- If `empty_display_type == "IMAGE"` and `obj.data` is an Image: extra row with `iops.reload_empty_reference_image` and `object.origin_set` (type=ORIGIN_GEOMETRY, center=MEDIAN).

There is also a sibling sub-menu class `IOPS_MT_Pie_Edit_Modes` (a regular menu, not a pie) listing `object.mode_set` for Object / Edit / Sculpt / Vertex Paint / Weight Paint — it is not currently called from inside the Edit pie itself but is registered alongside it.

---

## IOPS Pie Assets

<div class="iops-meta" markdown="1">
<span class="key">bl_idname (call op): iops.call_pie_assets</span>
<span class="key">Menu class: IOPS_MT_Pie_Assets</span>
<span class="mode">Context: any</span>
<span>Type: Pie menu (with cascading sub-menus)</span>
</div>

Source: `ui/iops_pie_assets.py`.

**Default binding:** `Ctrl + Shift + A`.

| Slot | Contents |
|---|---|
| W (4) | `iops.asset_clear` — "Clear Asset" (icon `TRASH`). |
| E (6) | Sub-menu `IOPS_MT_AssetMarkSub` — "Mark as Asset" (icon `ASSET_MANAGER`). |
| S (2) | Sub-menu `IOPS_MT_CatalogBrowseActive` — "Move to" (icon `FILE_FOLDER`). |
| N (8) | Library switcher box (see below). |
| NW (7) | `iops.assets_render_asset_thumbnail` — "Render Thumbnail" (icon `RENDER_RESULT`). |
| NE (9) | Sub-menu `IOPS_MT_AssetDeleteCatalogsSub` — "Delete Catalog" (icon `TRASH`). |
| SW (1), SE (3) | Empty. |

### Sub-menu: IOPS_MT_AssetMarkSub

Four entries, each calling `iops.asset_mark` with a different `mark_type`:

- Object (`OBJECT_DATA`) — `mark_type=OBJECT`
- Collection (`OUTLINER_COLLECTION`) — `mark_type=COLLECTION`
- Active Material (`MATERIAL`) — `mark_type=MATERIAL`
- Active Image (`IMAGE_DATA`) — `mark_type=IMAGE`

### Sub-menu: IOPS_MT_CatalogBrowseActive ("Move to")

Cascading catalog tree built from the current library's catalog file (resolved by `get_catalog_source_by_path(lib_path)`). If the file is unsaved it falls back to a `Save file first` label. Top row: `iops.asset_search_move_to_catalog` (Search). Tree nodes are either submenus (auto-IDs assigned by `_assign_pool_ids` with `action="move"`) or `iops.asset_move_to_catalog` operators carrying `catalog_uuid` and `catalog_name`. Footer: `iops.asset_create_catalog` (New Catalog), bound to the discovered `catalog_file`.

### Sub-menu: IOPS_MT_AssetDeleteCatalogsSub

Same shape as Browse-Active but for deletion. Top row: `iops.asset_search_delete_catalog`. Tree leaves call `iops.asset_delete_catalog` with `catalog_uuid` + `catalog_file`. Footer: `iops.asset_delete_empty_catalogs` (icon `BRUSH_DATA`) for sweep-up.

### Library switcher (N slot box)

- Header "Library" with `ASSET_MANAGER` icon.
- "Current File" entry calling `iops.set_asset_library` with `library_path=""` — depressed/check-marked when the active library is the current file.
- One row per entry in `context.preferences.filepaths.asset_libraries`, each calling `iops.set_asset_library` with the normalised library path.
- Action row: `iops.select_in_asset_browser` (Select in Browser), `iops.clear_asset_browser_filter` (Clear Filter).
- `iops.refresh_asset_browser` (Refresh).
- When `IOPS_OT_OpenAssetInCurrentBlender.poll` passes: a button calling that operator (icon `BLENDER`) for opening the active Asset Browser asset in the current Blender instance.

---

## IOPS Pie Split (area split / switch)

<div class="iops-meta" markdown="1">
<span class="key">bl_idname (call op): iops.call_pie_split</span>
<span class="key">Menu class: IOPS_MT_Pie_Split</span>
<span class="mode">Context: any</span>
<span>Type: Pie menu</span>
</div>

Source: `ui/iops_pie_split.py`.

**Default binding:** `Ctrl + Shift + S`.

Every cardinal of this pie is fully user-configurable from add-on preferences. Each slot pulls its primary UI type, alt UI type, split position, and split factor from `prefs.split_area_pie_N_*`. Labels are derived from `split_areas_dict` via `get_text_icon` and shortened by `shorten_text` (`3D Viewport` to `3D View`, ` Editor` removed, etc.). When an alt UI is set the label becomes `Primary / Alt`. Slots with `ui == "Empty"` render as separators.

| Slot | Operator | Primary pref | Alt pref |
|---|---|---|---|
| W (4) | `iops.split_area_pie_4` | `split_area_pie_4_ui` | `split_area_pie_4_alt_ui` |
| E (6) | `iops.split_area_pie_6` | `split_area_pie_6_ui` | `split_area_pie_6_alt_ui` |
| S (2) | `iops.split_area_pie_2` | `split_area_pie_2_ui` | `split_area_pie_2_alt_ui` |
| N (8) | `iops.split_area_pie_8` | `split_area_pie_8_ui` | `split_area_pie_8_alt_ui` |
| NW (7) | `iops.split_area_pie_7` | `split_area_pie_7_ui` | `split_area_pie_7_alt_ui` |
| NE (9) | `iops.split_area_pie_9` | `split_area_pie_9_ui` | `split_area_pie_9_alt_ui` |
| SW (1) | `iops.split_area_pie_1` | `split_area_pie_1_ui` | `split_area_pie_1_alt_ui` |
| SE (3) | `iops.split_area_pie_3` | `split_area_pie_3_ui` | `split_area_pie_3_alt_ui` |

### Modifier behaviour per slot operator

All eight `iops.split_area_pie_N` operators share the same `invoke` shape:

- **No modifier** — `iops.split_screen_area` with the primary UI, `pos` and `factor` from prefs.
- **Shift** — `iops.split_screen_area` with the *alt* UI (and alt UI's pos/factor).
- **Alt** — `iops.switch_screen_area` against the primary UI (no split — converts the current area in place).
- **Ctrl** — forces `context.area.ui_type = "VIEW_3D"` (reset shortcut).

The `Call_Pie_Split` operator additionally reports the stored "previous area" coming from `wm.IOPS_AddonProperties.iops_split_previous`, used by the Switch path to round-trip.
