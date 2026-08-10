# iOps Modifiers Panel — Design

Date: 2026-08-10
Status: approved for planning

## Purpose

A compact N-panel ("micro panel") in the 3D Viewport sidebar (iOps tab) for
assigning and managing modifiers on the active object and the whole selection.
The core UI is a grid of modifier-type icons grouped by category. It fills the
gaps vanilla Blender and existing addons leave in multi-object modifier
workflows: batch by-type operations, robust batch apply, stack sorting,
cleanup, cursor-driven targets and reverse target lookup.

## UI

### Panel

`IOPS_PT_Modifiers_Panel` in `ui/iops_modifiers_panel.py`:

- `bl_space_type = "VIEW_3D"`, `bl_region_type = "UI"`, `bl_category = "iOps"`,
  `DEFAULT_CLOSED` — same pattern as `IOPS_PT_Object_Color_Panel`.
- Layout, top to bottom:
  1. Icon grid (grouped)
  2. Tools row(s)
  3. Active-object stack list (optional via prefs)

### Icon grid

- Drawn with `layout.grid_flow(columns=prefs.modifiers_grid_columns)`;
  default 6 columns. Rows derive from the number of enabled types
  (default curated set of 18 = 3 rows → the requested 6×3 default).
- Groups with small header labels, each group its own `grid_flow`:
  - **Generate**: Bevel, Boolean, Mirror, Array, Solidify, Subdivision
    Surface, Screw, Weld, Triangulate, Decimate, Remesh, Wireframe
  - **Deform**: Curve, Lattice, Simple Deform, Displace, Shrinkwrap
  - **Utility**: Weighted Normal
- Each cell is an operator button (icon only, no text) with
  `depress=True` when a modifier of that type exists on the **active**
  object. (Built-in icons cannot be tinted from `UILayout`; `depress` is
  the standard highlight.) Tooltip = modifier name + click actions.
- Cell checks in `draw()` iterate only the active object's modifiers —
  never the selection or the scene.

### Tools row

Buttons under the grid (icon buttons, wrapped as needed):

- **Sort** — auto-sort stacks across selection
- **Cleanup** — remove dead/no-op modifiers across selection
- **Sync Vis** — `show_render = show_viewport` across selection
- **Cursor → Target** — empty at 3D cursor becomes modifier target
- **Select Users** — select objects that use the active object as a
  modifier target
- **Safe Apply Transform** — apply object transform without breaking
  modifier results (both target and carrier scenarios)

### Stack list (active object)

Shown when `prefs.modifiers_show_stack` is on (default on). One row per
modifier of the active object:

- type icon, name
- `show_viewport` toggle, `show_render` toggle — the render toggle draws
  with `alert=True` when `show_render != show_viewport`
- move up / move down
- Apply, Apply Up To Here, Remove
- Save As Default Preset (saves this modifier's settings as the type's
  default preset)

All per-row buttons are one operator (`iops.mod_stack_action`) with
`index` + `action` props.

## Interaction model

### Grid click — one generic operator

`iops.mod_grid_click` with a `mod_type` string property. `invoke()` reads
`event.ctrl / event.alt / event.shift` and dispatches:

- **Click** — add the modifier to every selected object (objects whose
  type doesn't support it are skipped and counted). New modifier settings
  come from the type's saved default preset if one exists, else from the
  hardcoded smart-defaults table.
- **Ctrl+Click — Smart Apply** all modifiers of this type across the
  selection:
  - multi-user data → `obj.data = obj.data.copy()` automatically
  - shape keys → skip the object, count it, report
    `"N objects skipped (shape keys)"`
  - modifiers with `show_viewport == False` are skipped (vanilla apply
    would bake them in — a known gotcha)
  - applied in stack order (top-down) so results match the viewport
- **Alt+Click** — remove all modifiers of this type across the selection.
- **Shift+Click** — toggle `show_viewport` for this type across the
  selection. The target state is the inverse of the active object's
  current state, applied uniformly (no per-object flip-flop).

Batch loops never abort on one bad object: skip, count, and emit one
summary `self.report` at the end.

### Smart defaults

Hardcoded per-type in each type's descriptor. Initial table (values
finalized during implementation, listed here for intent):

| Type | Defaults |
|---|---|
| BEVEL | width 0.02, segments 2, limit ANGLE 30°, clamp overlap, harden normals off |
| BOOLEAN | solver EXACT, no object (user assigns / Cursor→Target) |
| MIRROR | axis X, clipping on |
| ARRAY | count 2, relative offset X = 1 |
| SOLIDIFY | thickness 0.02, even thickness on |
| SUBSURF | levels 2, render levels 2 |
| SCREW | axis Z, steps 16 |
| WELD | merge distance 0.001 |
| TRIANGULATE | keep custom normals, min vertices 5 |
| DECIMATE | collapse, ratio 0.5 |
| REMESH | voxel, voxel size 0.05 |
| WIREFRAME | thickness 0.02, replace original on |
| CURVE | deform axis X, no target |
| LATTICE | no target |
| SIMPLE_DEFORM | bend, 45° |
| DISPLACE | strength 0.1, direction NORMAL |
| SHRINKWRAP | nearest surface point, no target |
| WEIGHTED_NORMAL | keep sharp on, weight 50 |

## Architecture

### File layout

```
ui/iops_modifiers_panel.py      # the panel (draw only, no logic)
operators/modifiers/
    __init__.py                  # collects classes + descriptors for registration
    base.py                      # type registry, batch helpers, generic
                                 # grid-click operator, Smart Apply core
    presets.py                   # default-preset JSON storage
    iops_bevel.py                # one file per modifier type (18 files):
    iops_boolean.py              #   descriptor: icon, group, smart defaults,
    iops_mirror.py               #   object-field names, identity check for
    iops_array.py                #   Cleanup, sort weight, optional custom
    iops_solidify.py             #   add hook
    iops_subsurf.py
    iops_screw.py
    iops_weld.py
    iops_triangulate.py
    iops_decimate.py
    iops_remesh.py
    iops_wireframe.py
    iops_curve.py
    iops_lattice.py
    iops_simple_deform.py
    iops_displace.py
    iops_shrinkwrap.py
    iops_weighted_normal.py
    iops_sort.py                 # tool operators, one file each
    iops_cleanup.py
    iops_sync_vis.py
    iops_cursor_target.py
    iops_select_users.py
    iops_safe_apply.py
    iops_stack.py                # stack-list row actions
```

### Type registry (`base.py`)

Each per-type file registers a descriptor:

```python
ModDescriptor(
    mod_type="MIRROR",          # bpy modifier type enum
    icon="MOD_MIRROR",
    group="GENERATE",           # GENERATE | DEFORM | UTILITY
    defaults={...},             # smart-defaults dict, prop name -> value
    object_fields=("mirror_object",),  # pointer props referencing objects
    sort_weight=10,             # position band for Sort
    is_noop=callable | None,    # identity check for Cleanup
)
```

Adding a new modifier type to the panel = adding one file. The registry
drives:

- grid drawing (icon, group, enabled state)
- grid click (defaults)
- **Sort** (sort_weight)
- **Cleanup** (object_fields for dead targets, is_noop)
- **Cursor → Target** (first empty object_field gets the empty)
- **Select Users** / **Safe Apply Transform** (object_fields for reverse
  lookup)

For modifier types not in the registry (users can enable any type from
prefs), object fields are discovered once via RNA pointer-property
introspection and cached per type; defaults fall back to Blender's own.

### Tool operators

- **`iops.mod_sort_stack`** — rule-based reorder per selected object:
  weight bands pin Mirror/Array early; Bevel mid; Weighted Normal,
  Triangulate, Smooth by Angle (geometry-nodes modifier detected by node
  group name), Simple Deform at the end in a defined order. Uses
  `obj.modifiers.move()` directly, no `bpy.ops`.
- **`iops.mod_cleanup`** — per selected object remove modifiers that:
  have a dead/empty required object field (Boolean, Shrinkwrap, Curve,
  Lattice, Hook, Data Transfer, …); have both `show_viewport` and
  `show_render` off; or pass the type's `is_noop` check (Bevel width 0,
  Array count 1, Subsurf levels 0, …). Reports
  `"removed N modifiers on M objects"`.
- **`iops.mod_sync_vis`** — `md.show_render = md.show_viewport` for all
  modifiers across the selection.
- **`iops.mod_cursor_target`** — create one empty at the 3D cursor's
  location **and rotation**, then assign it: to the active object's
  active modifier's first object field, and to same-type modifiers across
  the selection whose object field is empty. One shared empty for the
  whole batch.
- **`iops.mod_select_target_users`** — select every object in
  `context.view_layer.objects` that has a modifier referencing the active
  object. Fast path: registry `object_fields` (1–3 attribute reads per
  modifier, identity comparison `is active_obj`); unknown types use the
  cached RNA-introspection fallback. Selection applied in one batch via
  `select_set(True)`, no `bpy.ops`, no depsgraph churn in the loop.
- **`iops.mod_safe_apply_transform`** — two scenarios, auto-detected per
  selected object:
  1. *Object is a target of other objects' modifiers*: apply its
     transform, then compensate the referencing modifiers so the visual
     result of those objects does not move. Empties are skipped with a
     report (nothing to apply into; compensation happens on the modifier
     side).
  2. *Object carries modifiers with external targets* (Mirror, Curve,
     Lattice, …): apply its transform without shifting the modifier
     result.
  Exact compensation math per modifier type is worked out at
  implementation-plan stage; the operator contract is "world-space result
  looks identical before and after".
- **`iops.mod_stack_action`** — stack-list row actions: move up/down,
  apply, **apply up to here** (for each selected object apply modifiers
  top-down through the matching type/name — order always respected),
  remove, save-as-default-preset.

### Presets (`presets.py`)

- v1: exactly one "default preset" per modifier type.
- Stored as JSON at `bpy.utils.user_resource('CONFIG')` /
  `iops_mod_presets.json`: `{mod_type: {prop: value}}`, serializable
  props only (no pointers).
- Save: stack-list button snapshots the modifier's non-default,
  serializable properties.
- Load: grid click applies the preset dict after creating the modifier;
  missing/renamed props are skipped silently (version tolerance).
- Named multi-presets are out of scope for v1.

## Preferences

Added to the existing addon preferences:

- `modifiers_grid_columns`: IntProperty, default 6, min 2, max 12.
- `modifiers_enabled_types`: EnumProperty with `ENUM_FLAG` options
  listing all modifier types; default = the curated 18. Prefs UI draws it
  expanded as a checkbox grid. Grid shows only enabled types (curated
  descriptors first, then any extra enabled types via the fallback path).
- `modifiers_show_stack`: BoolProperty, default True — show/hide the
  active-object stack list in the panel.

## Performance rules

- `draw()` never scans the selection or the scene: depress state and
  visibility-mismatch alerts read only the active object's modifiers.
- Scene/selection scans happen only inside operator `execute()`.
- Batch operators use direct data API (`modifiers.move`, `select_set`,
  attribute writes); `bpy.ops` only where unavoidable
  (`object.modifier_apply` with `temp_override` per object).
- Registry object-field lookup is O(1) per modifier; RNA introspection
  runs at most once per unknown modifier type per session.

## Error handling

- All operators: `poll()` requires Object Mode and a valid active object.
- Type compatibility filtered per object (e.g. Curve modifier valid on
  meshes/curves; Weld only on meshes); incompatible objects are skipped
  and counted.
- Batch operations never abort mid-way on one object; every operator ends
  with a single summary `report()` (added/applied/removed/skipped counts
  and why).
- Smart Apply specifics: multi-user → auto single-user copy; shape keys →
  skip + count; disabled modifiers → skip.

## Testing

- Live smoke tests via the blender-mcp bridge
  (`mcp__blender__execute_blender_python`): build a scene with a
  multi-object selection including multi-user meshes, an object with
  shape keys, empties as targets, and verify each operator's counts and
  resulting stacks.
- Manual visual pass for the panel layout at different UI scales and grid
  column settings.

## Out of scope (v1)

- Named multi-presets per type.
- Settings-sync on click when the type already exists (research item #6)
  — plain click always adds.
- Physics/simulation modifier types in the curated set (still available
  via prefs enum).
- Popup/pie entry point (panel only; can be added later reusing the same
  draw code).
