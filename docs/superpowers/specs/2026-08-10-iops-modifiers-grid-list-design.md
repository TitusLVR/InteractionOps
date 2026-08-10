# iOps Modifiers: user-built grid via UIList — design

Date: 2026-08-10
Status: approved (chat), option B for defaults display

## Goal

Replace the per-type checkbox toggles in addon preferences with a
user-managed list (UIList) of modifier types. The list IS the grid: item
count = button count, list order = button order, layout width comes from
the existing Grid Columns pref. The active list item shows its saved
default preset read-only.

## Data model (AddonPreferences)

- `IOPS_ModGridItem(PropertyGroup)` — single field
  `mod_type: StringProperty` (RNA enum identifier, e.g. "BEVEL").
  Registered before the prefs class (root `__init__.py` class list rule).
- On prefs: `modifiers_grid_items: CollectionProperty(type=IOPS_ModGridItem)`
  and `modifiers_grid_index: IntProperty`.
- Kept: `modifiers_grid_columns`, `modifiers_show_stack`.
- Removed: all dynamic `mod_grid_show_*` BoolProperties,
  `_register_mod_grid_toggles()`, `MOD_MENU_GROUPS`, and the grouped
  toggle UI in the prefs section.
- Persistence: Blender's own userpref storage handles the collection;
  the iops_prefs_user.json layer is not involved (grid toggles never
  were in it either).

## Seeding

If `modifiers_grid_items` is empty when the addon enables, fill it with
`CURATED_TYPES` (18 types, registry order) via a one-shot
`bpy.app.timers.register` callback — prefs must not be written during
register() at startup (restricted context). An emptied list stays empty
(empty grid is legal); Reset restores the curated set.

## Preferences UI (Modifiers Panel section)

- Row: `modifiers_grid_columns`, `modifiers_show_stack` (unchanged).
- `template_list` (custom UIList) — each row: type icon
  (`type_icon`) + human name from the RNA enum.
- Side column (standard layout):
  - Add — `iops.mod_grid_list_add`, `invoke_search_popup` over all
    modifier types from RNA not already in the list.
  - Remove — active item.
  - Move Up / Move Down.
  - Reset — replace content with `CURATED_TYPES`.
- Below the list, a box for the active item:
  - If a saved default preset exists (`iops_mod_presets.load_default`):
    read-only `prop: value` label rows + Clear Preset button (deletes
    the preset json).
  - Else if the registry descriptor has smart `defaults`: show those,
    labeled as smart defaults.
  - Else: "Blender defaults" label.
  - Hint label: presets are saved from a live modifier via the stack
    list's save button.

## Operators (operators/modifiers/iops_mod_list.py, `iops_mod_` prefix)

- `IOPS_OT_ModGridListAdd` (`iops.mod_grid_list_add`) —
  `bl_property`-driven enum search popup; enum items = RNA modifier
  types minus current list content; appends and selects the new item.
- `IOPS_OT_ModGridListAction` (`iops.mod_grid_list_action`) — enum
  action: REMOVE, UP, DOWN, RESET, CLEAR_PRESET. Index bounds guarded.

## Panel / registry wiring

- `enabled_grid_types(prefs)` (iops_mod_registry.py) → returns
  `[it.mod_type for it in prefs.modifiers_grid_items]` filtered to
  valid RNA identifiers (stale names from future/old Blender skipped).
- Panel drops GROUP_ORDER-based ordering: grid order = list order
  verbatim. GROUP_ORDER stays for Sort/descriptor semantics.

## Not doing

- Editable default params in prefs (option A — dynamic PropertyGroups
  from RNA) — rejected for now, presets stay json-file based.
- Migration of the old `mod_grid_show_*` toggle state.
- Duplicates in the list.

## Amendment (same day, user request)

The UIList is replaced by a WYSIWYG grid preview: the prefs section
draws the same icon grid as the panel (same columns), click = select
(depressed button, `SELECT` action with index). Toolbar under the grid:
Add / Remove / Move Earlier (TRIA_LEFT) / Move Later (TRIA_RIGHT) /
Reset. Add is not a search popup but an Add-Modifier-style grouped menu
(`IOPS_MT_ModGridAdd`, columns Edit/Generate/Deform/Normals/Physics +
Other, `MENU_GROUPS` in iops_mod_list.py); already-present types are
omitted. `iops.mod_grid_list_add` takes a plain string `mod_type` set
by menu entries; duplicates are CANCELLED. `IOPS_UL_ModGridList` is
gone.

## Testing (live Blender via MCP)

- Reload addon → list seeded with 18 curated types.
- Add via ops with explicit `mod_type` (search popup itself is
  interactive-only), remove, move, reset — collection state asserted.
- Panel popup draw + prefs section draw error-free.
- `enabled_grid_types` order follows list order after a move.
