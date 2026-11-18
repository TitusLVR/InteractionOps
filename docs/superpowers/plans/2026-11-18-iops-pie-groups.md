# IOPS Pie Groups and IOPS External Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Regroup the IOPS Pie into contextual titled boxes over all eight slots and move every third-party addon link to a new IOPS External pie on Ctrl+`.

**Architecture:** Group contents live as plain data in a bpy-free module; one draw function in the pie menu turns a group into a box and skips empty ones. The Vertex Color box is a custom draw that shares its brush buttons with the existing sidebar panel. The External pie is a separate menu + bindable call operator.

**Tech Stack:** Blender Python API (`bpy.types.Menu`, `layout.menu_pie()`), pytest, ruff 0.12.0.

**Spec:** `docs/superpowers/specs/2026-11-18-iops-pie-groups-design.md`

## Global Constraints

- IOPS Pie holds iOps operators only; no third-party operator in `ui/iops_pie_menu.py`.
- Every operator button goes through `op_if_poll`; a box with no visible button becomes `pie.separator()`.
- All eight slots are always emitted, in Blender order: LEFT, RIGHT, BOTTOM, TOP, TOP_LEFT, TOP_RIGHT, BOTTOM_LEFT, BOTTOM_RIGHT.
- Diagonal boxes: five rows at most.
- Button labels: full names, no abbreviations.
- Line endings: keep each file's own (`git ls-files --eol <file>`): `ui/iops_pie_menu.py` and `docs/ui.md` are CRLF; `__init__.py`, `prefs/hotkeys_default.py`, `ui/iops_tm_panel.py` are LF. New files LF.
- Lint: `uvx ruff@0.12.0 check <touched files>` clean.
- No commits; leave the changes in the working tree.

## Review Focus

- B2RUVL / BMax / BMoI / ForgottenTools / Optiloops not installed: both pies draw without an exception. Pinned by Task 3 step 1 (source test) and the live check.
- Object with no vertex-paint brush yet (`tool_settings.vertex_paint.brush is None`): the Vertex Color box still draws.
- Non-mesh active object (curve, empty) or no active object: IOPS Pie opens, non-polling boxes vanish, no exception.
- A user with saved hotkeys from before this change: the new `iops.call_pie_external` entry still appears in the hotkey list (check how `operators/hotkeys/load_hotkeys.py` merges defaults; report what you find).
- An idname typo in the group tables: caught by the registration test in Task 1.

---

### Task 1: Group tables

**Files:**
- Create: `ui/iops_pie_groups.py` (no `bpy` import)
- Test: `tests/test_pie_groups.py`

**Interfaces:**
- Produces:
  - `SLOTS: tuple[str, ...]` = the eight names above, in that order.
  - `VERTEX_COLOR = "VERTEX_COLOR"` sentinel used in place of a rows list.
  - `PIE_GROUPS: dict[str, dict[str, tuple[str, list | str]]]`, keys `"OBJECT"` and `"EDIT_MESH"`, then slot name -> `(title, rows)`. `rows` is a list of rows; a row is a list of entries drawn side by side; an entry is `(idname, text, props_dict)`. A missing slot means an empty slot.
  - `groups_for_mode(mode: str) -> dict` returns `PIE_GROUPS["EDIT_MESH"]` for `"EDIT_MESH"`, else `PIE_GROUPS["OBJECT"]`.
- Contents: exactly the two tables in the spec. Idnames (verify each in `operators/`, report any that cannot run from a pie):
  - Object LEFT "Transform & Align": `iops.object_aligner`, `iops.object_align_between_two`, `iops.object_modal_three_point_rotation`, `iops.object_mirror_rotate`, `iops.object_match_transform_active`, `iops.object_normalize`, `iops.object_change_scale`, `iops.object_visual_origin`, `iops.object_drop_it`.
  - Object RIGHT "Arrange": `iops.object_replace`, `iops.object_radial_array`, row [`iops.object_kitbash_grid` "Grid", `iops.object_kitbash_grid` "Grid to Center" `{"arrange_mode": "CENTER"}`], `iops.object_to_grid_from_active`.
  - Object TOP "Select & Name": `iops.object_select_similar_name`, `iops.object_name_from_active`, `iops.object_search_rename`, `iops.object_select_boolean_operands`, `iops.object_select_boolean_targets`, `iops.object_select_mirror_objects`, `iops.object_negative_scale_overlay`.
  - Object TOP_LEFT "Modifiers": `iops.modifier_easy_array_caps`, `iops.modifier_easy_array_curve`, `iops.modifier_easy_curve`, `iops.modifier_easy_shwarp`.
  - Object TOP_RIGHT "Assets & Files": `iops.materials_from_textures`, `iops.call_panel_material_override`, `iops.assets_render_asset_thumbnail`, `iops.reload_libraries`, `iops.reload_images`.
  - Edit LEFT "Mesh": `iops.mesh_inset`, `iops.mesh_edge_slide`, `iops.mesh_straight_bevel`, `iops.mesh_shear`, `iops.mesh_hinge`, `iops.mesh_converge`, `iops.mesh_vert_fuse`, `iops.mesh_quick_connect`, `iops.mesh_quick_snap`, `iops.mesh_to_tris_to_quads`, `iops.mesh_cursor_bisect`, `iops.mesh_to_grid`, `iops.mesh_snapshot`.
  - Edit RIGHT "UV": `iops.mesh_uv_stripe`, `iops.mesh_uv_pipe`, `iops.mesh_uv_shortest_mark`, `iops.mesh_uv_channel_hop`, `iops.mesh_visual_uv`.
  - Edit TOP "Measure & Align": `iops.mesh_copy_edge_length`, `iops.mesh_copy_edges_angle`, `iops.mesh_align_origin_to_normal`, `iops.mesh_align_object_to_face`, `iops.mesh_nonplanar_overlay`.
  - Edit TOP_LEFT "Bevel": `iops.pin_unwrap_bevel`, `iops.bevel_edge_data_fix`.
  - BOTTOM in both modes: `("Vertex Color", VERTEX_COLOR)`.

- [ ] **Step 1: Write the failing tests** in `tests/test_pie_groups.py` (load the module by path the way other `tests/test_*_core.py` files load bpy-free modules):
  - `test_slots_order`: `SLOTS == ("LEFT","RIGHT","BOTTOM","TOP","TOP_LEFT","TOP_RIGHT","BOTTOM_LEFT","BOTTOM_RIGHT")`.
  - `test_slot_names_valid`: every slot key in both modes is in `SLOTS`.
  - `test_diagonals_short`: every diagonal group has `len(rows) <= 5`.
  - `test_only_iops_operators`: every entry idname starts with `"iops."`.
  - `test_vertex_color_bottom_in_both_modes`.
  - `test_idnames_exist_in_source`: every idname appears as `bl_idname = "<idname>"` in some `.py` under `operators/` or `ui/`.
  - `test_groups_for_mode`: `"EDIT_MESH"` -> edit table, `"OBJECT"` and `"EDIT_CURVE"` -> object table.
- [ ] **Step 2:** run `pytest tests/test_pie_groups.py -v`; expect import failure.
- [ ] **Step 3:** implement `ui/iops_pie_groups.py`.
- [ ] **Step 4:** run again; expect all pass.

### Task 2: IOPS Pie draws from the tables

**Files:**
- Modify: `ui/iops_pie_menu.py` (CRLF), `ui/iops_tm_panel.py:768-791` (LF)

**Interfaces:**
- Consumes: `SLOTS`, `VERTEX_COLOR`, `groups_for_mode` from Task 1.
- Produces:
  - In `ui/iops_tm_panel.py`: `draw_vertex_paint_buttons(layout)` draws the Paint button and the palette swatch row (the code now at lines 775-791); `IOPS_PT_VCol_Panel.draw` calls it, panel look unchanged.
  - In `ui/iops_pie_menu.py`: `draw_group_box(pie, context, group) -> bool` (False and `pie.separator()` emitted when nothing was drawn); `draw_vertex_color_box(pie, context) -> bool`.

- [ ] **Step 1:** extract `draw_vertex_paint_buttons` in the panel file; panel calls it.
- [ ] **Step 2:** rewrite `IOPS_MT_Pie_Menu.draw`: loop `SLOTS`, look the slot up in `groups_for_mode(context.mode)`, call `draw_group_box` / `draw_vertex_color_box`, else `pie.separator()`. Keep `op_if_poll` and its import users (`grep op_if_poll` first; other modules may import it). Remove all BMax / BMoI / B2RUVL / ForgottenTools / Optiloops code and the unused `get_addon` import.
- [ ] **Step 3:** toggles: `iops.mesh_nonplanar_overlay` keeps `depress=overlay_enabled()`; give `iops.object_negative_scale_overlay` the same treatment if its module exposes an enabled-state function, otherwise a plain button.
- [ ] **Step 4:** Vertex Color box: `scene.IOPS.iops_vertex_color` swatch, Set Vertex Color, White / Grey / Black row, Set Vertex Alpha (all as today, through `op_if_poll`), separator, `draw_vertex_paint_buttons` when `iops.mesh_vertex_paint` polls, row Blur / Sharpen = `iops.mesh_vertex_color_filter` with `mode="BLUR"` / `"SHARPEN"`. No box when nothing polls.
- [ ] **Step 5:** `pytest tests -q` (bpy-free suite) still green; ruff clean.

### Task 3: IOPS External pie

**Files:**
- Create: `ui/iops_pie_external.py`
- Modify: `__init__.py` (import next to line 228, classes next to 567-568), `prefs/hotkeys_default.py` (after line 66)
- Test: `tests/test_pie_groups.py`

**Interfaces:**
- Produces: `IOPS_MT_Pie_External(Menu)` with `bl_label = "IOPS External"`; `IOPS_OT_Call_Pie_External` with `bl_idname = "iops.call_pie_external"`, `is_bindable = True`, `bl_label = "IOPS Pie External"`; hotkey row `("iops.call_pie_external", "ACCENT_GRAVE", "PRESS", True, False, False, False)`.
- Layout: LEFT BMax, RIGHT BMoI, BOTTOM B2RUVL, TOP ForgottenTools, TOP_RIGHT Optiloops; contents as the code removed in Task 2 (ForgottenTools: connect_spread, grid_fill_all, dice_faces, hinge, forgotten_separate_duplicate, Selection Sets panel call). Every addon read is guarded: `get_addon(...)` first and `preferences.addons.get("B2RUVL")` / `.get("BMAX_Connector")`, never `addons[...]` unguarded. A missing addon or an all-hidden box is a `pie.separator()`. No addon at all: one label "No external addons installed" in the LEFT slot.

- [ ] **Step 1: failing tests:** `test_external_hotkey`: `keys_default` contains exactly the row above; `test_external_pie_guards_addons`: source of `ui/iops_pie_external.py` contains no `addons["`; `test_main_pie_has_no_external_ops`: source of `ui/iops_pie_menu.py` contains none of `bmax.`, `bmoi3d.`, `b2ruvl.`, `mesh.optiloops`, `B2RUVL`.
- [ ] **Step 2:** run; expect fail.
- [ ] **Step 3:** implement, register, add the hotkey row. Read how `keys_default` rows become keymap items and confirm `iops.call_pie_external` gets a 3D View keymap like `iops.call_pie_menu`.
- [ ] **Step 4:** tests pass; `tests/smoke_register.py` passes in headless Blender if you can run it (see the brief for the environment rule); otherwise report it as not run.

### Task 4: Docs

**Files:**
- Modify: `docs/ui/ui_pies.md`, `docs/ui.md` if it lists pies (check each file's EOL)

- [ ] **Step 1:** rewrite the IOPS Pie section as the two tables from the spec; add an IOPS External section with its hotkey and boxes. English, no internal paths or asset names.
