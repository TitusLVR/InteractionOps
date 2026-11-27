# iOps Materials Panel — Design

Date: 2026-11-26
Status: stages 1, 2 and 2b built; stage 3 planned

## Purpose

A light, unobtrusive "Materials" panel in the 3D Viewport sidebar (iOps tab)
that is also callable as a hotkey popup. It lists materials; a click assigns
one. It works in Object Mode and Edit Mode without a mode switch in the UI and
never raises an error on objects that cannot take materials: such objects are
skipped and counted in the report. It also cleans numbered duplicates
(`Steel.001`, `Steel.002`) back into one material with the users relinked.
The feature grows in stages; stage 1 is the panel, assignment, the functions
menu and deduplication.

## Layout in the code base

- `utils/materials_core.py` — pure Python, no `bpy`, covered by pytest:
  numbered-name parsing and grouping, choice of the original in a group, the
  merge plan, list rows (search, source filter, stacking), names for new
  materials, value freezing for fingerprints, report wording.
- `operators/materials/` — operators and `bpy` glue (assignment, new
  material, deduplication, the functions, the panel state).
- `ui/iops_materials_panel.py` — panel, UIList, functions menu, call-panel
  operator.

## Panel

`IOPS_PT_Materials_Panel`: `VIEW_3D`, `UI` region, category `iOps`, label
"Materials". `iops.call_panel_materials` (bindable, default `F16`) opens the
same panel as a popup; the popup draws a fake header like the Modifiers panel.

Top to bottom:

1. Header row: **New** material, **Functions** menu, List/Gallery toggle.
   (A Library button arrives with stage 2, not before.)
2. Search field and source filter: **Scene** (materials used by objects in
   the scene), **Selected** (used by selected objects), **File** (all
   `bpy.data.materials`).
3. List view or gallery view.

### List view

A UIList over `bpy.data.materials`, one compact row per material: preview
icon, name, duplicate badge `×N` when stacking is on, user count (drawn as
alert when 0; a fake user does not count). Visible row count comes from the
preferences.

### Gallery view

A grid of larger previews (`template_icon`) with a name button under each.
The cell size comes from the thumbnail-size preference; the number of columns
follows from the panel width and the cell size; the number of rows per page
comes from the preferences, with page buttons when the set is longer.

### Previews

Previews come from `UILayout.icon(material)`, the same lazy call Blender's
own material lists use: it starts a background preview job for a missing
preview and never renders inside `draw()`. Only drawn rows (visible list rows,
the current gallery page) request previews. No operator re-renders all
previews (the cause of the stalls the Material Override panel avoids).

### Clicks

A material row or gallery cell is a button:

- click — assign to the object(s), whole object;
- Alt+click — assign to the selected faces;
- Ctrl+click — only make it the panel's active material, no assignment.

The tooltip states these. Results are reported with `self.report`
("Assigned Steel to 2 objects, 1 skipped (Empty)").

The panel stays minimal: no pass index, node counts, viewport-colour tools or
per-row expanders.

## Assignment — `iops.material_assign`

Properties: material name, material library path (empty for local), mode
`OBJECT` / `FACES`. `invoke` reads `event.alt` (faces) and `event.ctrl`
(active only). The logic lives in plain functions taking an explicit material
and target list so later stages reuse it.

- Targets: in Edit Mode all objects in edit mode; otherwise the selected
  objects, else the active object.
- Compatible: `obj.data` exists, has a `materials` collection, and object and
  data are editable (not linked library data). Everything else is skipped
  silently and counted in the report. If nothing is compatible a single
  warning is reported and nothing changes.
- Whole object: the object ends up with exactly this material on all faces —
  its slots collapse to one slot holding it, all face indices go to 0. Shared
  data is processed once. Works in Edit Mode (face indices through bmesh).
- Faces (meshes only): selected faces get the material — an existing slot
  holding it is reused, otherwise a slot is appended — through bmesh across
  all edit objects in Edit Mode, through the mesh's stored face selection in
  Object Mode. No selected faces: reported, nothing changes. Other types are
  skipped.
- Linked library materials can be assigned; assignment never duplicates a
  material.
- One undo step (`REGISTER`, `UNDO`).

## New material — `iops.material_new`

Creates a node material (Principled BSDF into Material Output) named
"Material", or "Material 2", "Material 3"… when taken. The space-number form
is deliberate: a `.001` name would itself become a numbered duplicate. The
new material becomes the panel's active material. Shift+click (or the
`assign` property) also assigns it to the selection by the rules above
(Shift+Alt+click: to the selected faces).

## Functions menu — `IOPS_MT_materials_functions`

Grouped by separators:

- Duplicates: **Merge Duplicates and Relink**.
- Reassign: **Remap Materials…** (two-column table source → target, List /
  Thumbnails, scope Selected Objects / Scene / File, applied simultaneously;
  replaced the stage 1 Replace Material dialog), **Copy Materials from Active** (slots of the active object to
  the other selected compatible objects), **Select Objects Using Material**
  (the panel's active material; Object Mode).
- Cleanup: **Remove Unused Slots** (selected objects: slots no face uses and
  empty slots), **Clear All Materials (Selected)**, **Clear All Materials
  (Scene)…** (confirmation), **Delete Unused Materials…** (file: zero real
  users, fake user not counted; the confirmation shows the count).

All obey the compatibility rule and report counts.

## Deduplication

- A duplicate is a local material whose name matches `<base>.<digits>` with
  3+ digits. Materials are grouped by base.
- The original is the material named exactly `<base>` when it exists;
  otherwise the lowest-numbered one, renamed to `<base>` after the merge.
- A duplicate merges automatically only when it is equivalent to the
  original: same fingerprint. The fingerprint covers the editable settings of
  the material itself (blend, shadow, backface, displacement, viewport
  display, …) and the node tree: per node its type, editable properties, ID
  pointers by name, unlinked input default values and output default values,
  plus all links. Cosmetic node data (location, size, label, colour, frames,
  selection) is ignored. Floats are compared rounded to 6 decimals.
- Equivalent: `user_remap` to the original, then the duplicate is removed.
  Different: kept and reported; the `force` option merges it anyway.
- Linked library materials are never removed or renamed; they are skipped
  and counted in the report.
- "Stack numbered duplicates" preference (default on): the list shows one
  row per group under the base name with a `×N` badge; the row assigns the
  group's original; clicking the badge merges that group by the same rules.
  Off: every material is listed under its real name.

## Preferences (section "Materials")

Stored in all three places (property, `prefs/iops_prefs.py` section
`MATERIALS_PANEL`, `case` in `io_addon_preferences.py`):

- Thumbnail Size — gallery cell size in UI units.
- List Rows — visible rows of the list view.
- Gallery Rows — rows per gallery page (columns follow from the width).
- Stack Numbered Duplicates.
- Default View — List / Gallery (the panel toggle overrides it per session).

## Tests

- pytest for `utils/materials_core.py`.
- Headless Blender tests (`tests/blender/test_materials.py`): compatibility
  skipping in a mixed selection, whole-object assignment incl. shared data and
  Edit Mode, face assignment in Edit and Object Mode, deduplication
  (equivalent merged and relinked, different kept, missing base renamed,
  linked skipped), every cleanup function.
- `tests/smoke_register.py` checks the new classes and preferences.

## Stage 2 (built)

- Preference **Interface** (`materials_ui_mode`): Panel / Shelf. Panel: the
  panel polls, the shelf never does. Shelf: the panel does not poll, the shelf
  does; `iops.call_panel_materials` toggles `show_region_asset_shelf` of the
  3D View under the cursor instead of opening the popup.
- `IOPS_AST_materials` (`ui/iops_materials_shelf.py`): `VIEW_3D`,
  `DEFAULT_VISIBLE`, `filter_material`, Object Mode and every Edit Mode.
  `asset_poll` keeps material assets of the chosen library (asset library
  path contains the asset's `full_library_path`) and every current-file
  material asset. `bl_default_preview_size` = thumbnail-size pref × 20 px
  (clamped 16-256); the class is re-registered when the pref changes, which
  seeds new shelves only.
- `bl_activate_operator = "IOPS_OT_material_assign_asset"`. The asset comes
  from `context.asset` (`local_id` for current-file assets,
  `full_library_path` + `name` for library assets); the operator also takes
  explicit `library_file` / `asset_name` properties for other callers and
  tests. Click / Alt / Ctrl as in the panel through `assign_material()`.
- Import (`materials_import_method`): Append (Reuse) appends with
  `assets_only` and `clear_asset_data` and stores `iops_asset_source =
  "<normalized library .blend path>|<asset name>"` on the copy; the next use
  of the same asset finds that copy. Link reuses an already linked material
  of that library file. A missing or unreadable file: one warning.
- Native asset drag stays (no `NO_ASSET_DRAG`).
- Context menu: Assign to Object, Assign to Selected Faces, Make Active
  Material, Select Objects Using It (only when already in the file), the
  Functions menu. No `ACTIVATE_FOR_CONTEXT_MENU` (it would assign on
  right-click).
- The shelf API offers no header hook for buttons: New, Functions and the
  library choice are appended to the shelf's Display Settings popover
  (`ASSETSHELF_PT_display`), drawn only for this shelf.
- Library (`materials_library`): a library name, empty = all, picked with
  `prop_search` over `preferences.filepaths.asset_libraries` (a name string
  survives reordering, an enum index would not). `iops.materials_library_add`
  registers a picked folder (name from the folder, made unique; an already
  registered path is only selected) and selects it — it changes the user's
  Blender Preferences.
- Functions menu: Mark as Asset (with generated preview) and Clear Asset for
  the panel's active material.

## Stage 2b (built): the iOps shelf

The native asset shelf only shows assets and has no room for the panel's
tools; the user wanted the shelf to work like the panel. Stage 2b adds an
addon-drawn strip; the native shelf stays as "Library Shelf".

- **Interface** (`materials_ui_mode`): Panel / Shelf (`IOPS_SHELF`) /
  Library Shelf (`LIBRARY_SHELF`). Enum values PANEL 0, LIBRARY_SHELF 1,
  IOPS_SHELF 2: Blender's own prefs store the value, and 1 used to be the
  asset shelf. The prefs JSON maps a saved `"SHELF"` to `LIBRARY_SHELF`.
  Panel polls only in Panel mode, the native shelf only in Library Shelf;
  F16 toggles the iOps shelf (one switch for all 3D Views, session only),
  the native region, or opens the popup.
- **Layout and hit-testing** are pure (`utils/materials_shelf_core.py`):
  strip at the bottom of the region inside the insets, a tool cluster on
  the left, a cell grid that wraps by width and scrolls in whole rows,
  badges, the resize edge.
- **Insets** come from the real rectangles of the area's toolbar, sidebar,
  headers and asset-shelf regions that overlap the window region, so they
  are right with Region Overlap on or off and in each quad-view region.
  Quad view: the shelf lives in the bottom-right region.
- **Drawing** (`ui/materials_shelf/draw.py`, POST_PIXEL): `ui/draw`
  primitives (new `image_2d`, `tris_batch`, `draw_batch`), HUD text, theme
  roles; the strip is the HUD background at least 85 % opaque.
- **Thumbnails** (`thumbs.py`): GPU textures from the material previews,
  made only for drawn cells, at most 6 per redraw, cached by material,
  rebuilt when the preview pixels change (checked by a 0.5 s timer for
  recently drawn materials), freed on unregister and file load. Missing
  previews are requested from the timer with `asset_generate_preview()`
  (a background job), never from the draw callback, one at a time and
  only while no preview job runs: the call stops running preview jobs and
  waits for them, which freezes Blender when a Cycles preview thread is
  waiting for Python.
- **Input** (`events.py`): the widget framework's contract, not its control
  model. Addon "3D View" keymap entries (LMB / RMB press, wheel, mouse
  move, any modifiers) call `iops.material_shelf_event`; poll is the fast
  path, invoke hit-tests and returns PASS_THROUGH outside the strip; inside
  the event is consumed. A left press starts a modal for one gesture:
  click (on release over the same target), drag of a cell, resize. The
  entries are programmatic (`save_hotkeys.NEVER_SAVE`, re-added by Load
  Hotkeys).
- **Clicks** call the existing operators (assign, merge, select users,
  new, remove empty slots); Ctrl+click only sets the active material.
- **Drag and drop**: scene ray cast at release; whole object by default,
  with Alt the original polygon under the cursor (the ray cast's index for
  meshes without modifiers, otherwise a BVH of the original mesh or edit
  bmesh, built once per gesture), through `iops.material_assign_drop` /
  `assign.assign_face()`: existing slot, else an empty slot no other face
  uses, else a new slot. Ghost at the cursor; the target's bounding box and
  face are drawn while dragging.
- **Hover highlight** (`highlight.py`, POST_VIEW): faces using the hovered
  material on visible meshes, from the evaluated meshes, cached per
  (material, depsgraph generation), at most 300,000 triangles, drawn with
  the Non-Planar overlay's depth-shrink shader in `GHOST_PREVIEW`.
- **Search** is a small native popup panel with the shared search field (a
  text field cannot be edited inside a drawn strip).
- Preferences (three places): `materials_shelf_height` (px at 1.0 scale,
  default 150), `materials_shelf_thumbnail` (px, default 72),
  `materials_highlight_hover` (default on).

## Shelf toolbar icons (built)

The iOps shelf's tools are square icon buttons without labels: Functions,
New, Search, Scene, Selected, File, plus an empty-slots button (slot mark
and count) that exists only while there are empty slots.

- Glyphs: normalised strokes in a 0..1 box in
  `utils/materials_shelf_glyphs.py` (lines, closed loops, circles, dots),
  pytest-checked; drawn as anti-aliased hairlines of max(1, UI scale) px
  through `primitives.polyline`, which now takes a pixel width as well as
  a theme token. Straight strokes snap to pixel centres; circles do not.
  The repo had no icon system: only the widget title bar's pen and close
  marks (`ui/widgets/panel.py`), pure rect-fitted geometry, which set the
  pattern.
- Layout (`utils/materials_shelf_core.toolbar`): Row = one row at the top
  of the shelf, aligned left / centre / right, the cell grid under it at
  full width; Column = one column at the left or right edge (Center =
  right), wrapping column-first when the shelf is too short, the grid
  beside it at full height. Minimum height: Row = toolbar + one cell row,
  Column = one cell row.
- States: the current source and an active search get the accent glyph on
  a stronger plate; hover gives the soft plate; no outlines.
- Tooltips: after 0.4 s at rest on an icon (a one-shot timer asks for the
  redraw), a one-line label on a darkened HUD plate with a faint hairline,
  above the icon or below it when there is no room, clamped to the region.
- Preferences (three places): `materials_shelf_tools_direction` (Row /
  Column, default Row), `materials_shelf_tools_position` (Left / Center /
  Right, default Center).

## Stage 3 (planned, not built)

A viewport eyedropper (pick the material under the cursor, click to apply
elsewhere) and an overlay highlighting faces that use a material, drawn with
`ui/draw` and `Role`.
