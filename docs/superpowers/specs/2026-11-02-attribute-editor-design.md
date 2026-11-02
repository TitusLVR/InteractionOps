# iOps Attribute Editor — Design

Date: 2026-11-02
Status: approved (brief by Titus, technical calls below are the builder's)

## Purpose

A sidebar panel (`N panel › iOps › iOps Attributes`) that lists a mesh's
generic attributes, shows the active element's value per attribute, writes a
typed value to the whole selection the way the Item tab edits a vertex
position, previews an attribute in the viewport and manages several
attributes at once. Blender only offers `Mesh › Set Attribute` on the
attribute picked in the Properties editor, which is too slow.

Motivating case: a mesh used as a track spline for a geometry-nodes
generator, with per-vertex float attributes `tilt` (degrees) and `scale` and
a vertex group `marks`. Select vertices, type the values in the sidebar, see
the generator update.

## Facts verified in Blender 5.2.3 (live, `RaceTrack_GeoNode.blend`)

- `mesh.attributes` lists name / data_type / domain in Edit Mode; the `data`
  arrays are empty there (`len == 0`).
- `obj.to_mesh()` on the original object in Edit Mode returns the **stale**
  stored mesh, not the edit-bmesh state (verified headless: a bmesh write
  is invisible to it, even after `update_edit_mesh`). The live-file check
  that suggested otherwise only saw unchanged values.
  `obj.update_from_editmode()` does sync, but fires a depsgraph update of
  its own on every call, which would evaluate the generator twice per edit.
  Builder's ruling: Edit Mode reads go through `bmesh.from_edit_mesh`
  (values, positions, selection, hidden, active element in one pass) and
  only while `window.modal_operators` is empty; during a modal the panel
  and the preview keep their last data. Object Mode reads `obj.data`
  through `foreach_get`.
- `obj.evaluated_get(dg).to_mesh()` on the track object has **0 vertices**:
  the geometry-nodes output is not a mesh. The preview must read the base
  mesh, never the evaluated one.
- bmesh vertex layer accessors: `bool, color, deform, float, float_color,
  float_vector, int, string` (+ `shape`, `skin`). No `int8`, `float2`,
  `quaternion`, `float4x4`, `int16_2d`, `int32_2d`, `float4`.
- Attribute data types: FLOAT, INT, BOOLEAN, FLOAT_VECTOR, FLOAT_COLOR,
  QUATERNION, FLOAT4X4, STRING, INT8, INT16_2D, INT32_2D, FLOAT2, FLOAT4,
  BYTE_COLOR. Mesh domains: POINT, EDGE, FACE, CORNER.
- `bpy.ops.mesh.attribute_set`, `mesh.select_by_attribute`,
  `geometry.attribute_convert / attribute_add / attribute_remove` exist.

## Non-goals

- Curves, point clouds, Grease Pencil: the panel shows nothing unless the
  active object is a mesh.
- A header popover (Selection Sets has one; not needed here).
- Transfer from object, bake from evaluated mesh, batch rename/delete:
  listed in the brief as lower priority; deferred to a follow-up spec.

## Files

| File | Holds |
| --- | --- |
| `utils/attribute_editor_core.py` | Pure logic, no `bpy`: type table, filtering, domain-by-select-mode ordering, value coercion, mixed detection, math / remap / invert / round / randomize / smooth / gradient, chain ordering from an edge list, select-by-value predicates, heatmap ramp, label formatting. |
| `tests/test_attribute_editor_core.py` | pytest over the core module. |
| `operators/mesh_attribute_editor.py` | bmesh + `mesh.attributes` backends (read / write per type and domain), every operator (`iops.attr_*`). |
| `ui/iops_attribute_panel.py` | WindowManager mirror, UIList, panel, value editor properties, app handlers, preview overlay (POST_VIEW fill + POST_PIXEL labels), register/unregister. |
| `tests/blender/test_attribute_editor.py` | Headless: build a mesh with `tilt` / `scale` / vertex group, set on selection, undo, Object-Mode Set All, gradient, select by value. |
| `docs/ui/ui_attributes.md` + `mkdocs.yml` nav + `docs/ui.md` link | User page. |
| `__init__.py` | Class registration and `register_attribute_ui()` / `unregister_attribute_ui()` calls. |
| `tests/smoke_register.py` | Asserts the panel, the UIList and the WM properties register. |

## Storage and state

Source of truth: the mesh. Nothing is persisted by the addon.

`WindowManager.iops_attr` (PropertyGroup `IOPS_AttrState`), UI-only:

- `mirror: CollectionProperty(IOPS_AttrMirrorItem)` — one row per listed
  attribute: `name`, `data_type`, `domain`, `kind` (`ATTR` | `VGROUP`),
  `editable` (bool, false for types bmesh cannot write in Edit Mode),
  `count` (element count, Object Mode).
- `index: IntProperty` — active row. Its `update` writes
  `mesh.attributes.active_index` (ATTR rows) or `obj.vertex_groups.active_index`
  (VGROUP rows) so Properties › Data › Attributes and `Mesh › Set Attribute`
  agree with the panel.
- `show_hidden`, `show_builtin`, `show_vgroups: BoolProperty` — list filters.
- Row labels show Blender's full data type name (Float, Integer, Vector…),
  never an abbreviation; no `(first)` marker in the editor (user feedback
  2026-11-02: the value comes from the active element, the fallback is
  silent). The value editor shows the active UIList row only, and instead
  of a `Mixed (n)` warning a plain line under the field says
  `N vertices / edges / faces selected` (user feedback 2026-11-02).
  Same day, second round: the type column of the list is dimmed like
  Blender's own attribute list; the filter toggles show their names; the
  per-row eye is gone — the preview is one `preview` toggle (default on)
  that always shows the active UIList row (`sync_preview`); labels draw on
  translucent boxes and `preview_text_size` is a pixel IntProperty (the
  Enum tokens all mapped to the theme's Label slider, so the setting had
  no effect).
  Third round: `preview_mode` became four checkboxes (Labels, Heatmap,
  Colour, Greyscale) that combine; the fills are exclusive on the
  geometry (Heatmap > Colour > Greyscale). The panel is two nested
  frames without headings, Type / Index on one property-split line,
  one full-width Preview button and a Preview Settings sub-panel.
- Value fields with `get` / `set` callbacks, one per widget kind:
  `value_float`, `value_int`, `value_bool`, `value_vector` (3), `value_color`
  (4), `value_string`. The getter returns the cached active-element value.
  The setter writes directly (bmesh layer on the selection in Edit Mode,
  `foreach_set` in Object Mode) so mouse-drag editing of a number field
  works tick by tick like the Item tab, and schedules one
  `bpy.ops.ed.undo_push(message="iOps Attribute Value")` through a
  `bpy.app.timers` one-shot 0.3 s after the last tick, so a typed value or
  one drag is one undo step. The panel draw never writes RNA.
- `preview_mode: EnumProperty` — `LABELS` | `GREYSCALE` | `COLOUR` | `HEATMAP`
  (greyscale / colour only enabled for colour types); `preview_decimals: Int`
  (default 2); `preview_text_size: Enum(small / normal / large)` mapped to the
  HUD text size tokens.

Module-level Python state (never RNA): the per-row cache
`{row_name: {"active": value, "mixed": n, "first": bool}}`, the selection
signature, the preview batches, the `last_panel_draw` timestamp.

### Which attributes are listed

`core.list_rows(attributes, vertex_groups, show_hidden, show_builtin,
show_vgroups)`:

- Hidden: name starts with `.` → off unless `show_hidden`. Selection-set
  layers (`.iops_ss_*`, see `utils/selection_sets_core.ATTR_PREFIX`) are
  never listed.
- Multi-object Edit Mode: the **active object** defines the list, the
  active-element value, `Mixed (n)` and the `active_index` sync. Writes and
  tools fan out to every edit mesh that has an attribute with the same name,
  domain and type.
- Built-in (own UI elsewhere): `position`, `sharp_edge`, `sharp_face`,
  `material_index`, `crease_vert`, `crease_edge`, `bevel_weight_vert`,
  `bevel_weight_edge`, UV maps (FLOAT2 on CORNER that are in
  `mesh.uv_layers`), colour attributes (in `mesh.color_attributes`) → off
  unless `show_builtin`.
- Domains outside POINT / EDGE / FACE / CORNER are never listed.
- Vertex groups → one VGROUP row each (FLOAT, POINT), after the attributes.
- Order: by domain (POINT, EDGE, FACE, CORNER), then name; VGROUP rows last.
  The UIList's own filter popover handles name filtering and sort by name.

### Type table (`core.TYPES`)

| data_type | bmesh layer | Edit Mode write | widget | preview |
| --- | --- | --- | --- | --- |
| FLOAT | float | yes | float field | labels, heatmap |
| INT | int | yes | int field | labels, heatmap |
| BOOLEAN | bool | yes | checkbox | labels, heatmap (0/1) |
| FLOAT_VECTOR | float_vector | yes | 3 fields | labels (x y z), heatmap of length |
| FLOAT_COLOR | float_color | yes | colour (4) | greyscale, colour, heatmap of luminance |
| BYTE_COLOR | color | yes | colour (4) | same as FLOAT_COLOR |
| STRING | string | read-only (brief) | text, disabled | labels |
| INT8 | — | Object Mode only | int field | labels, heatmap |
| FLOAT2 | — | Object Mode only | 2 fields | labels |
| QUATERNION, FLOAT4, INT16_2D, INT32_2D, FLOAT4X4 | — | Object Mode only | read-only label | labels (components) |
| vertex group | deform | yes | float field 0–1 | labels, heatmap |

"Object Mode only" rows draw greyed in Edit Mode with the tooltip "Edit in
Object Mode (bmesh has no layer for this type)". Set All in Object Mode
writes them through `attribute.data.foreach_set`.

## Behaviour

1. **Discovery.** `rebuild_mirror(context)` runs from
   `depsgraph_update_post`, `undo_post`, `redo_post`, `load_post` and from
   every mutating operator via `tag_mirror_dirty()`, gated by a cheap
   signature `(obj name, mode, tuple of (name, type, domain) rows, vertex
   group names)`. Same pattern as `ui/iops_selection_sets_panel.py`.
2. **Active-element value.** The value cache refreshes from the same
   handlers when the *selection signature* changed. Signature and values come
   from `obj.to_mesh()` (`.select_vert` / `.select_edge` / `.select_poly`
   arrays + attribute arrays via `foreach_get`), never from Python bmesh in a
   handler. The active element index is the only thing that needs bmesh
   (`bm.select_history.active`); it is read once per selection change, which
   never happens during a plain transform (positions move, selection does
   not). Modals that do change selection while running (loop cut + slide,
   circle select) are covered by a hard rule: while
   `context.window.modal_operators` is non-empty no bmesh read happens and
   the panel keeps its last values; the next handler run or panel draw
   after the modal ends re-reads them (builder's ruling: nothing can be
   read without bmesh in Edit Mode, so "first selected" is unavailable
   during a modal too). This
   keeps the crash path documented in `operators/mesh_nonplanar_overlay.py`
   closed. No active element → the first selected element, `(first)`
   suffix; nothing selected → the fields draw disabled. CORNER domain: the active face's first corner; edits write all
   corners of selected faces.
3. **Dense meshes.** Handlers do nothing unless the panel drew in the last
   second (`last_panel_draw` stamped in `draw()`) or a preview is on. With a
   quiet sidebar the addon costs nothing.
4. **Edit applies to the selection.** `iops.attr_set_value(row, value_*)`
   (`REGISTER | UNDO`): Edit Mode → bmesh layer write on the selected
   elements of the attribute's domain (POINT: selected verts, EDGE: selected
   edges, FACE: selected faces, CORNER: loops of selected faces) regardless
   of `mesh_select_mode`, then `bmesh.update_edit_mesh(me)`, which tags the
   depsgraph so geometry-nodes modifiers refresh. Multi-object Edit Mode:
   every edit mesh that has the attribute. Object Mode → `foreach_set` on
   every element (Set All).
5. **Mixed.** When the selected elements hold more than one distinct value
   the field row shows `Mixed (n)`; the field itself shows the active
   element's value.
6. **Value editor layout.** Rows for every listed attribute whose domain
   matches the current select mode (vertex → POINT, edge → EDGE, face → FACE
   and CORNER). The active row is always shown first even if its domain
   differs, with its domain icon. Object Mode shows one field + `Set All`
   for the active row only, plus `count` on every list row.
7. **Vertex groups.** VGROUP rows behave like FLOAT / POINT attributes
   through the deform layer; a selected vertex not in the group reads 0 and
   gets added on write.

## Tools

Side column: `+` (dialog: name, type, domain, default value), `−`, duplicate,
refresh. Specials menu (`IOPS_MT_attr_specials`), each an operator with
`REGISTER | UNDO` on the active row:

| Tool | Operator | Notes |
| --- | --- | --- |
| Rename | UIList double-click | `attribute.name = new` (unique-name check in core) |
| Convert type / domain | `iops.attr_convert` | wraps `geometry.attribute_convert` after syncing the active attribute |
| Set on … / Reset on … | `iops.attr_fill` | value or type default; target `SELECTED` / `UNSELECTED` / `ALL` |
| Gradient | `iops.attr_gradient` | selected vertex chain ordered by selected edges (`core.order_chain`); ends = chain end values or two typed values; `LINEAR` / `EASE_IN_OUT`; fails with a report if the selection branches |
| Math | `iops.attr_math` | `ADD`, `MULTIPLY`, `CLAMP`, `INVERT`, `REMAP`, `ROUND` on the selection; popup with operands |
| Smooth | `iops.attr_smooth` | Laplacian over selected elements, N iterations, factor; neighbours from bmesh, maths in core |
| Randomize | `iops.attr_randomize` | min, max, seed |
| Copy / Swap | `iops.attr_copy` | source → target with `core.coerce` (float / int / bool; vector component pick); `swap` flag |
| Vertex group ⇄ attribute | `iops.attr_from_vgroup`, `iops.attr_to_vgroup` | non-destructive both ways |
| Select by value | `iops.attr_select_by_value` | `EQUAL`, `NOT_EQUAL`, `LESS`, `GREATER`, `RANGE`, `ACTIVE` with tolerance; extend / replace |

Every tool works on the attribute's domain selection in Edit Mode and on all
elements in Object Mode (Gradient / Smooth / Select by value are Edit Mode
only).

Type matrix for the tools (rows the tool cannot handle are greyed in the
menu with the reason in the tooltip):

| Tool | FLOAT / INT / VGROUP | BOOLEAN | FLOAT_VECTOR / colours | STRING, Object-Mode-only types |
| --- | --- | --- | --- | --- |
| Set / Reset | yes | yes | yes | Set / Reset in Object Mode only |
| Gradient | yes (POINT and EDGE domains; EDGE takes the chain's edges in order) | no | per component | no |
| Math | yes (INT results rounded) | INVERT only | per component (REMAP per component over its own range) | no |
| Smooth | yes (INT rounded) | no | per component | no |
| Randomize | yes | yes | per component | no |
| Copy / Swap | with coercion | with coercion | component pick / broadcast | no |
| Select by value | yes | EQUAL / NOT_EQUAL | length for LESS / GREATER / RANGE, per component for EQUAL | no |

Vertex-group rows in Object Mode: Set All assigns every vertex to the group
with that weight; Reset sets weight 0 and keeps the membership.

## Object Mode

Same list with `count` per row; value editor collapses to one widget and a
`Set All` button for the active row; the preview works the same way reading
`obj.data` directly.

## Viewport preview

Toggle per row (eye icon, `iops.attr_preview`). One attribute previews at a
time; toggling another switches. Off by default and free when off: no
handlers registered, no redraw cost.

- Data: `obj.to_mesh()` in Edit Mode, `obj.data` in Object Mode, arrays via
  `foreach_get`, cached CPU-side and invalidated by the same handlers; the
  draw callbacks only build GPU batches and draw. Positions: vertex, edge
  midpoint, face centre (`polygons.center`), corner offset 25 % toward the
  face centre. Hidden elements (`.hide_*`) are skipped.
- `LABELS` (numeric types): `ui/hud/text` in a POST_PIXEL handler at
  `location_3d_to_region_2d`; floats use `preview_decimals`, vectors print
  components. Selected elements in `Role.ACTIVE_POINT` colour, others in
  `Role.HUD_LABEL`. More than `attr_preview_max_labels` (addon pref, default
  2000) elements → labels are skipped and a `too many elements` note appears
  in the preview block.
- `GREYSCALE` / `COLOUR` (colour types) and `HEATMAP` (any numeric type): a
  POST_VIEW SMOOTH_COLOR fill with the nonplanar overlay's clip-space depth
  shrink. POINT → points, EDGE → lines, FACE / CORNER → tris; heatmap maps
  min→max over the mesh through a fixed ramp (blue, cyan, green, yellow,
  red); the `min … max` range is a **Range** row in the Preview Settings
  sub-panel. Nothing is drawn in the viewport corners.
- `preview_selected_only` (Bool, default off): in Edit Mode the visible mask
  is `~hidden & selected`, so labels, fills and the heatmap range cover the
  selection only. Object Mode ignores it (checkbox disabled).
- Respects `space_data.overlay.show_overlays` and the viewport clipping
  region (`region_3d.use_clip_planes`); the handler is disabled when the
  active object is no longer a mesh or the mode leaves OBJECT / EDIT_MESH.

## Undo

Every tool and button is an operator with `REGISTER | UNDO`. The value
fields write directly and push one debounced undo step per edit session
(see Storage and state). After undo the handlers rebuild the mirror and the
value cache.

## Done when

- With `track_mesh` in Edit Mode, click a vertex, the panel shows
  `tilt = 20`, type 45, the geometry-nodes track rebuilds; select all, type
  45, every vertex reads 45.
- New attributes appear without registration or naming convention.
- Undo reverts one edit at a time. `Preview` on `tilt` shows a number at
  every vertex in the iOps style; `Heatmap` shows the same as a gradient; on
  a colour attribute the mesh shades greyscale, in colour with the option
  on; everything disappears when the toggle is off.
- `pytest tests/` passes, `tests/blender/test_attribute_editor.py` passes
  headless, `tests/smoke_register.py` still registers the addon, the docs
  page describes the panel.
