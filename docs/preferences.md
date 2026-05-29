# Addon Preferences

InteractionOps exposes its configuration through a single `AddonPreferences`
panel (`Edit > Preferences > Add-ons > InteractionOps`). The panel is split into
three tabs driven by the `tabs` `EnumProperty`:

| Tab id    | Label         | Contents                                                                 |
| --------- | ------------- | ------------------------------------------------------------------------ |
| `PREFS`   | Preferences   | Functional settings grouped into collapsible sections (default tab).     |
| `KM`      | Keymaps       | Hotkey editor + Save / Load / Reset hotkey operators.                    |
| `THEME`   | Theme         | Unified HUD / overlay theme — see [HUD & Theme](ui/ui_hud.md).           |

Two icon-only buttons sit next to the `PREFS` tab toggle:

| Button             | Operator                          | Action                                                                          |
| ------------------ | --------------------------------- | ------------------------------------------------------------------------------- |
| `FILE_TICK`        | `iops.save_addon_preferences`     | Serialize the addon prefs to `presets/IOPS/iops_prefs_user.json`.               |
| `FILE_FOLDER`      | `iops.load_addon_preferences`     | Re-read that JSON and push the values back onto the live AddonPreferences.      |

Sources: `prefs/addon_preferences.py`, `prefs/addon_properties.py`,
`prefs/iops_prefs.py`, `prefs/theme.py`,
`operators/preferences/io_addon_preferences.py`,
`operators/preferences/io_theme.py`, `operators/hotkeys/*.py`.

---

## 1. Preferences tab (`PREFS`)

The body of this tab is a stack of collapsible sections drawn by the local
helper `_section()` — each section is gated by a `show_section_*` `BoolProperty`
on the preferences class. The list below mirrors `draw()` top-to-bottom.

### General

| Property   | Type     | Default | Effect                                                                                              |
| ---------- | -------- | ------- | --------------------------------------------------------------------------------------------------- |
| `category` | `String` | `iOps`  | N-panel category for IOPS panels. The `update_category` callback re-registers panels on each edit.  |

### Statistics Overlay

| Property             | Type   | Default | Effect                                                                                                |
| -------------------- | ------ | ------- | ----------------------------------------------------------------------------------------------------- |
| `iops_stat`          | `Bool` | `True`  | Master toggle for the persistent viewport statistics overlay (active object name, UV maps, scale...). |
| `show_filename_stat` | `Bool` | `True`  | Show / hide the current `.blend` filename inside the statistics overlay.                              |

All colors, sizes and text positioning for stats now live in the **Theme**
tab — see [HUD & Theme](ui/ui_hud.md).

### Visual UV (on-mesh)

| Property                  | Type           | Default    | Effect                                                                              |
| ------------------------- | -------------- | ---------- | ----------------------------------------------------------------------------------- |
| `visual_uv_normal_offset` | `Float`        | `0.002`    | Distance to offset the on-mesh UV overlay from the surface (avoids z-fighting).     |
| `island_palette_0..7`     | `FloatVector4` | (see code) | 8-slot per-island color palette, indexed by `island_id % 8`. Excluded from theme presets. |

Point / edge / fill sizes for Visual UV live in the Theme tab.
See [`op_mesh_visual_uv.md`](operators/op_mesh_visual_uv.md).

### Cursor Bisect

Operational params only — colors and sizes are in the Theme tab.
See [`op_mesh_cursor_bisect.md`](operators/op_mesh_cursor_bisect.md).

| Property                            | Type    | Default | Range          | Effect                                                                                 |
| ----------------------------------- | ------- | ------- | -------------- | -------------------------------------------------------------------------------------- |
| `cursor_bisect_face_depth`          | `Int`   | `5`     | `1..20`        | Face-connection traversal depth from raycast point for the cut preview.                |
| `cursor_bisect_max_faces`           | `Int`   | `1000`  | `100..10000`   | Fallback face budget when no raycast hit (whole-mesh preview).                         |
| `cursor_bisect_edge_subdivisions`   | `Int`   | `1`     | `0..100`       | Default subdivisions along each edge for snap candidates (`0` = endpoints + center).   |
| `cursor_bisect_snap_threshold`      | `Float` | `30.0`  | `5..100` px    | Screen-space snap distance in pixels.                                                  |
| `cursor_bisect_snap_use_modifiers`  | `Bool`  | `True`  | —              | Calculate snap points on the evaluated (modified) mesh.                                |
| `cursor_bisect_merge_distance`      | `Float` | `0.005` | `0..1`         | Post-bisect merge-by-distance threshold (BU).                                          |
| `cursor_bisect_rotation_step`       | `Float` | `45.0`° | `1..180`       | `Alt+Wheel` rotation step around the local Z axis during the modal.                    |
| `cursor_bisect_coplanar_angle`      | `Float` | `5.0`°  | `0..180`       | Angle threshold for treating adjacent faces as coplanar.                               |

### Snap Combo

| Property         | Type        | Default | Effect                                                                                       |
| ---------------- | ----------- | ------- | -------------------------------------------------------------------------------------------- |
| `snap_combo_mod` | `Enum`      | `SHIFT` | Modifier saved alongside each snap combo preset (`SHIFT`, `CTRL`, `ALT`, plus all pairs/triple). |
| `snap_combo_list`| `Enum 1..8` | `1`     | Active snap-combo slot (drives the `iops.set_snap_combo` operator via `update_combo`).        |

Snap-combo payloads (`SNAP_ELEMENTS` / `TOOL_SETTINGS` / `TRANSFORMATION` per
slot) are persisted alongside the rest of the prefs in `iops_prefs_user.json` —
see §3.

### Modifier Window

| Property                  | Type   | Default  | Options                                                                          |
| ------------------------- | ------ | -------- | -------------------------------------------------------------------------------- |
| `modifier_window_method`  | `Enum` | `RENDER` | `RENDER` (render-view-based, allows size control) / `NEW_WINDOW` (`wm.window_new`). |

### Split Pie Layout

A 3 x 3 grid (slots 1, 2, 3 / 4, _, 6 / 7, 8, 9 — slot 5 is the pie center)
configuring the *Split Area* pie. Each slot exposes four props:

| Suffix       | Type    | Default (example)        | Effect                                                              |
| ------------ | ------- | ------------------------ | ------------------------------------------------------------------- |
| `_ui`        | `Enum`  | per slot (e.g. `TIMELINE`) | Primary editor type to swap into the split area.                    |
| `_alt_ui`    | `Enum`  | per slot                 | Alternate editor type (Alt-variant of the pie button).              |
| `_pos`       | `Enum`  | `BOTTOM` / `RIGHT` / ... | Screen-space split position.                                        |
| `_factor`    | `Float` | `0.5` (slot 1: `0.2`)    | Split ratio, range `0.05..1.0`.                                     |

Default UI mapping (`_ui`): 1=`ShaderNodeTree`, 2=`TIMELINE`, 3=`PROPERTIES`,
4=`OUTLINER`, 6=`UV`, 7=`FILES`, 8=`CONSOLE`, 9=`TEXT_EDITOR`.
Items enumerate `utils/split_areas_dict.split_areas_list` /
`split_areas_position_list`.

### Script Executor

See [`op_executor.md`](operators/op_executor.md).

| Property                          | Type     | Default                            | Effect                                                                                |
| --------------------------------- | -------- | ---------------------------------- | ------------------------------------------------------------------------------------- |
| `executor_use_script_path_user`   | `Bool`   | `True`                             | If on, scripts are resolved under `bpy.utils.script_path_user()`.                     |
| `executor_scripts_subfolder`      | `String` | `iops_exec`                        | Sub-folder under the user script path (empty = root user script path).                |
| `executor_scripts_folder`         | `DirPath`| `script_path_user()`               | Effective scripts folder (auto-derived when `executor_use_script_path_user` is on).   |
| `executor_column_count`           | `Int`    | `20`                               | Scripts per column in the executor UI (`5..1000`).                                    |
| `executor_name_length`            | `Int`    | `100`                              | Display-length cap for script names (`5..600`).                                       |

### Textures to Materials

See [`op_materials_from_textures.md`](operators/op_materials_from_textures.md).

| Property                          | Type     | Default                | Effect                                                          |
| --------------------------------- | -------- | ---------------------- | --------------------------------------------------------------- |
| `texture_to_material_prefixes`    | `String` | `env_`                 | Comma-separated prefixes to strip from texture names.           |
| `texture_to_material_suffixes`    | `String` | `_df,_dfa,_mk,_emk,_nm`| Comma-separated suffixes to strip from texture names.           |

### Debug

| Property     | Type   | Default | Effect                                          |
| ------------ | ------ | ------- | ----------------------------------------------- |
| `IOPS_DEBUG` | `Bool` | `False` | Enables verbose query/debug prints from IOPS.   |

---

## 2. Keymaps tab (`KM`)

The Keymaps tab renders all IOPS keymap items using Blender's
`rna_keymap_ui.draw_kmi`, grouped into eight boxes by `bl_idname` prefix:

| Box label            | Matches `idname` prefix                                              |
| -------------------- | -------------------------------------------------------------------- |
| Main                 | `iops.function_*` (F1..F5, ESC)                                      |
| Cursor               | `iops.cursor*`                                                       |
| Object Mode          | `iops.object*`                                                       |
| Mesh or EditMode     | `iops.mesh*`, `iops.z_*` (Zaloopok operators)                        |
| UV Editor            | `iops.uv*`                                                           |
| Panels               | `iops.call_panel_*`                                                  |
| Pie Menus            | `iops.call_pie_*`                                                    |
| Scripts              | `iops.scripts*`, `iops.window*`                                      |
| UI Toggles           | `iops.ui_help_toggle`, `iops.ui_hud_params_toggle`                   |

The tab iterates these `kc_user.keymaps`: `Window`, `Mesh`, `Object Mode`,
`Screen Editing`, `UV Editor`.

### Hotkey operators

| Operator                       | Label                  | Action                                                                                                                              |
| ------------------------------ | ---------------------- | ----------------------------------------------------------------------------------------------------------------------------------- |
| `iops.save_user_hotkeys`       | Save User's Hotkeys    | Walk every `kc_user` keymap, dump items whose `idname` starts with `iops.` (and merge any missing entries from `keys_default`).     |
| `iops.load_user_hotkeys`       | Load User's Hotkeys    | Unregister current IOPS keymaps and re-register from the on-disk user file (empty list if file is missing / corrupt).               |
| `iops.load_default_hotkeys`    | Load Default Hotkeys   | Unregister and re-register from `prefs/hotkeys_default.py::keys_default`. Marked with `ERROR` icon — resets user bindings.          |

<div class="iops-meta">
<code>iops.save_user_hotkeys</code> · type: Operator<br>
<code>iops.load_user_hotkeys</code> · type: Operator<br>
<code>iops.load_default_hotkeys</code> · type: Operator
</div>

### Storage

- **Path:** `bpy.utils.script_path_user() / presets / IOPS / iops_hotkeys_user.py`
  (despite the `.py` extension the file holds a JSON list).
- **Entry tuple:** `(idname, type, value, ctrl, alt, shift, oskey)`.
- The folder is created on demand; an empty `[]` file is written on first load.

### Default keymap precedence on first install

`__init__.py::keymap_registration()` runs at addon register and:

1. Calls `fix_old_keymaps()` (in `utils/functions.py`) — opens the user hotkeys
   file, drops any entries whose `idname` is in `km_to_remove`, rewrites
   surviving entries through `old_new_km_map` to migrate renamed operators, and
   atomically rewrites the file (`.tmp` → `os.replace`).
2. If `iops_hotkeys_user.py` exists and parses to a list, those bindings are
   registered. Otherwise (missing / corrupt / not a list) `keys_default` is
   used as fallback.
3. UI toggle keymaps (`iops.ui_help_toggle`, `iops.ui_hud_params_toggle`) are
   added separately via `register_ui_toggle_keymaps()`.

So on a clean install the bundled defaults from `prefs/hotkeys_default.py` are
applied; once `Save User's Hotkeys` has been pressed at least once, the user
file takes precedence on every subsequent launch.

---

## 3. Save / Load Addon Preferences

<div class="iops-meta">
<code>iops.save_addon_preferences</code> · type: Operator<br>
<code>iops.load_addon_preferences</code> · type: Operator
</div>

| Operator                          | Behaviour                                                                                                       |
| --------------------------------- | --------------------------------------------------------------------------------------------------------------- |
| `iops.save_addon_preferences`     | Builds a dict via `prefs/iops_prefs.py::get_iops_prefs()` and `json.dump`s it atomically (`.tmp` → `os.replace`).|
| `iops.load_addon_preferences`     | Reads the same file and writes every section back onto the live `AddonPreferences`, missing keys → defaults.    |

**On-disk path:** `bpy.utils.script_path_user() / presets / IOPS / iops_prefs_user.json`

**Top-level keys serialised:**

| Section              | Contents                                                                                  |
| -------------------- | ----------------------------------------------------------------------------------------- |
| `IOPS_DEBUG`         | `IOPS_DEBUG`                                                                              |
| `EXECUTOR`           | `executor_column_count`, `executor_scripts_folder`, `executor_name_length`, `executor_use_script_path_user`, `executor_scripts_subfolder` |
| `SPLIT_AREA_PIES`    | One block per slot 1..9 (no 5) with `_factor`, `_pos`, `_ui`, `_alt_ui`                   |
| `UI_TEXT_STAT`       | `iops_stat`, `show_filename_stat`                                                          |
| `TEXTURE_TO_MATERIAL`| `texture_to_material_prefixes`, `texture_to_material_suffixes`                            |
| `SNAP_COMBOS`        | `snap_combo_1..8` — each with `SNAP_ELEMENTS`, `TOOL_SETTINGS`, `TRANSFORMATION`          |
| `MODIFIER_WINDOW`    | `modifier_window_method`                                                                  |
| `CURSOR_BISECT`      | `cursor_bisect_*` (see §1 Cursor Bisect)                                                  |

The loader is defensive: on JSON decode error the corrupt file is renamed to
`.backup` and a fresh defaults file is written. The old typo
`executor_name_lenght` is honoured as a fallback for `executor_name_length`.
Numeric legacy values for `split_area_pie_*_pos` / `_ui` / `_alt_ui` are
auto-translated to their enum strings via `split_areas_dict` /
`split_areas_position_list`.

Note: `SNAP_COMBOS` are not written back onto AddonPreferences ID props at load
time — `snap_combos.py` consumes them directly from JSON.

The theme is **not** part of this JSON — it has its own `.itheme` presets (§4).

---

## 4. Theme tab (`THEME`)

The Theme tab calls `prefs/theme.py::draw_theme_tab(layout, self.iops_theme)`.
It exposes the entire `IOPS_Theme` PropertyGroup (HUD text roles, point / line /
ghost / widget colors and sizes, panel background, etc.) plus preset
management:

| Control                          | Operator / property                  | Action                                                                                                        |
| -------------------------------- | ------------------------------------ | ------------------------------------------------------------------------------------------------------------- |
| Preset dropdown                  | `IOPS_Theme.theme_preset` (Enum)     | Items come from `list_theme_files()` — union of bundled + user `.itheme` files; selecting applies the preset. |
| Save As...                       | `iops.theme_save_as`                 | Serialise current `IOPS_Theme` (skipping `show_*`, `island_palette_*`, `theme_preset`) into a new `.itheme`.  |
| Delete                           | `iops.theme_delete`                  | Delete the selected user `.itheme`; refuses to delete bundled presets.                                        |
| Open Folder                      | `iops.theme_open_folder`             | Open the user themes folder in the OS file manager.                                                           |
| Reset Defaults                   | Theme reset operator (`iops_theme` PropertyGroup defaults) | Restore PropertyGroup defaults. |
| Use Blender Theme HUD Colors     | `iops.theme_use_blender_hud_colors`  | Seed HUD colors from the running Blender theme (also auto-runs on first install when prefs are pristine, via `_sync_hud_from_blender_theme_if_pristine`). |
| Theme Preview                    | `iops.draw_theme_preview`            | Live preview overlay — see [`op_draw_theme_preview.md`](operators/op_draw_theme_preview.md).                  |

<div class="iops-meta">
<code>iops.theme_save_as</code> · type: Operator<br>
<code>iops.theme_delete</code> · type: Operator<br>
<code>iops.theme_open_folder</code> · type: Operator
</div>

### Bundled presets

Shipped read-only inside `InteractionOps/presets/themes/*.itheme`:

- `Default`
- `Dark+` (VS Code Dark+)
- `Light+` (VS Code Light+)
- `Monokai`
- `Blender Default` (sourced from `wcol_*` of the running Blender theme)
- `Solarized Dark`

User-saved presets live under `script_path_user()/presets/IOPS/themes/`. When
two presets share a filename, the user copy overrides the bundled one
(`resolve_theme_path` checks the user folder first). Legacy presets `Dark` and
`High Contrast` are auto-removed from the user folder on register
(`ensure_default_presets`).

> The actual color roles, HUD layout, role table and sRGB conversion rules are
> documented in detail in [`ui/ui_hud.md`](ui/ui_hud.md). This page only
> catalogues the tab's preset-management UI.

---

## 5. SceneProperties / AddonProperties / WindowManager bindings

Set up in `__init__.py::register()`:

| Attachment point                                          | PropertyGroup                | Holds                                                                                                                      |
| --------------------------------------------------------- | ---------------------------- | -------------------------------------------------------------------------------------------------------------------------- |
| `bpy.context.preferences.addons["InteractionOps"].preferences` | `IOPS_AddonPreferences` | Everything in §1 plus `iops_theme: PointerProperty(IOPS_Theme)`.                                                            |
| `WindowManager.IOPS_AddonProperties`                      | `IOPS_AddonProperties`       | Per-session state: `iops_panel_mesh_info`, `iops_rotation_angle`, `iops_split_previous`, `iops_exec_filter` (fuzzy filter for the Script Executor; triggers `update_exec_filter`), `iops_append_collection_name`, `iops_source_collections` (`IOPS_CollectionItem` list) + `iops_source_collections_index`, `iops_active_asset_library`, `iops_active_color_index` (propagates the active color attribute *by name* across selected meshes via `update_iops_active_color_index`). |
| `Scene.IOPS`                                              | `IOPS_SceneProperties`       | Per-file state: `executor_scripts` / `filtered_executor_scripts` (`IOPS_ExecutorScriptItem` lists), `dragsnap_point_a/b`, `iops_vertex_color`, `iops_object_color` + 8 `iops_object_color_recent_N` swatches, the `cursor_bisect_*` modal state (`snapping`, `normal_axis`, `preview_mode`, `fill_cut`, `show_distance`, `edge_subdivisions`, `inset_*`, `bevel_active`, `mark_*`), and the `shortest_mark_*` knobs (barrier idx, mark idx, algorithm, flow / sharp angle, smooth level, path mode, curvature). |
| `Scene.iops_material_override_settings`                   | `IOPS_MaterialOverrideSettings` | Settings for [`op_material_override.md`](operators/op_material_override.md).                                              |

Helper `PropertyGroup`s (defined in `prefs/addon_properties.py`):

- `IOPS_CollectionItem` — `name`, `is_selected` (used by the Append Collection pie).
- `IOPS_ExecutorScriptItem` — single `path` string (Script Executor list rows).

---

## 6. On-disk paths summary

All user-writable files live under
`bpy.utils.script_path_user() / presets / IOPS / ...`:

| Path                                         | Producer                                              | Format                                  |
| -------------------------------------------- | ----------------------------------------------------- | --------------------------------------- |
| `iops_prefs_user.json`                       | `iops.save_addon_preferences`                         | JSON (see §3 sections).                 |
| `iops_hotkeys_user.py`                       | `iops.save_user_hotkeys` (read by `iops.load_user_hotkeys` and on register) | JSON list of tuples (despite `.py` ext). |
| `themes/*.itheme`                            | `iops.theme_save_as`                                  | JSON dump of `IOPS_Theme`.              |

Bundled (read-only, ships with the addon):

| Path                                         | Contents                                              |
| -------------------------------------------- | ----------------------------------------------------- |
| `InteractionOps/presets/themes/*.itheme`     | Six bundled theme presets — see §4.                   |

---

## See also

- [HUD & Theme details](ui/ui_hud.md)
- [Pie menus](ui/ui_pies.md)
- [Menus](ui/ui_menus.md)
- [`iops.draw_theme_preview`](operators/op_draw_theme_preview.md)
- [`iops.scripts_call_mt_executor`](operators/op_executor.md)
- [`iops.mesh_cursor_bisect`](operators/op_mesh_cursor_bisect.md)
- [`iops.mesh_visual_uv`](operators/op_mesh_visual_uv.md)
- [`iops.materials_from_textures`](operators/op_materials_from_textures.md)
