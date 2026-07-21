# Widgets Per-File UI State — visibility, positions, switches in the .blend

**Date:** 2026-07-21
**Status:** Approved design, pending implementation plan

## Problem

Widget UI state (`visible`, panel `x`/`y`, local `switches`) persists
globally in addon preferences as a JSON StringProperty (`widgets_state`,
`ui/widgets/state.py`). The same set of open widgets follows the user
across every .blend. Wanted instead: each .blend remembers its own set of
open widgets (and their positions and switch states), restored on file
load.

## Decisions (user-confirmed)

- **Per-file list is the only source of truth.** A file with no stored
  record (old .blend, File > New) opens with **all widgets closed**. The
  global prefs visible-persistence is removed, not kept as fallback.
- **Positions (x/y) are per-file too**, not just open/closed.
- **Switches are per-file too.** The prefs `widgets_state` property and
  its prefs-JSON round-trip are removed entirely — one source of truth.
- **No dirtying on open/close events.** The per-file record is written
  only during `save_pre` (snapshot of the live state at save time), never
  on the open/close/drag/switch events themselves. Accepted consequence:
  open a widget, don't save, reload the file → the widget is closed.

## Approaches considered

- **A. JSON StringProperty on `Scene.IOPS` (chosen).** Same JSON shape
  the runtime already serializes; one property; no new PropertyGroup
  classes; defensive access degrades to session-only.
- B. Reserved `"__ui__"` blocks inside the existing `widget_data`
  CollectionProperty — no new property, but collides with the purge
  operator's purge-all semantics and the string-KV shape is awkward for
  nested switches. Rejected.
- C. Structured RNA PropertyGroups (BoolProperty visible, FloatProperty
  x/y per widget) — RNA-native, but extra classes and registration order
  for no benefit when writes happen only at save time. Rejected.

## Storage

```python
# prefs/addon_properties.py
class IOPS_SceneProperties(PropertyGroup):
    ...existing...
    widgets_ui_state: StringProperty(default="")
```

JSON payload, identical in shape to today's prefs JSON:

```json
{ "<widget name>": { "visible": true, "x": 80.0, "y": 400.0,
                     "switches": { "<switch>": true } } }
```

Per-scene storage is the standard Blender approximation of per-file.
The snapshot is written to **every scene** in the file (one small string;
keeps multi-scene files consistent regardless of which scene is active
at load time).

## Write path — `save_pre` only

New `@persistent` `_on_save_pre` handler in `ui/widgets/state.py`:

1. Build the snapshot dict from runtime `_states`, refreshing each
   visible widget's live `widget.panel.x/y` and `widget.switches` first
   (drag/switch events no longer persist anything themselves).
2. `json.dumps` → write to `scene.IOPS.widgets_ui_state` for every scene
   in `bpy.data.scenes`.
3. Defensive: missing `Scene.IOPS` / property (framework half-registered)
   → silent no-op.

Because the write happens inside the save, the saved file contains it and
the save itself clears the dirty flag — no visible dirtying, no undo-step
interaction.

**Single exception:** `unregister()` also writes the snapshot to the
scenes, so dev reloads (blinker reload infra) don't lose open widgets.
This can dirty the file on addon disable/reload — dev-only path, accepted
deliberately.

## Read path — `load_post`

The existing `_on_load_post` grows the restore step (replacing the
current prefs-based `load_states()` at register time):

1. Read `widgets_ui_state` from the window scene (`bpy.context.scene`).
2. Replace `_states` **wholesale**: parse failure, empty string, or
   missing property → `{}` → all widgets closed. File > New lands here
   too (startup blend carries no IOPS state).
3. For each entry: set `visible`/`x`/`y`, sync `switches` into the live
   widget object, push `x`/`y` into `widget.panel`, reset
   `anchor_area_ptr` to 0 (pointers invalid across loads — existing
   rule).
4. `ensure_draw_handler()` / `remove_draw_handler()` per resulting
   visibility; mark dirty; redraw.

`register()` (addon enabled mid-session) applies the same restore from
the current scene instead of reading prefs.

## Pure core

Snapshot and apply are factored as pure dict→dict functions
(`snapshot_states(states) -> dict` / `parse_states(raw: str) -> dict`)
so serialization round-trip, defaults, and malformed-input handling are
plain pytest — matching the framework's existing pure/live test split.

## Removals

- Prefs `widgets_state` StringProperty and every `save_states()` call in
  `show_widget` / `hide_widget` / `store_position` / `store_switches`
  (these become runtime-only mutations).
- `load_states()` prefs reader.
- The WIDGETS section of the prefs-JSON round-trip
  (`prefs/iops_prefs.py`, `operators/preferences/io_addon_preferences.py`).
  A leftover `widgets_state` key in previously exported prefs JSON files
  is silently ignored.

## Edge cases

- **Scene.IOPS missing** (half-registered addon): all reads/writes
  defensive no-ops; framework degrades to session-only state.
- **Undo:** no writes outside save → nothing to revert. The existing
  undo/depsgraph dirty handlers are unchanged.
- **Linked/appended scenes:** the property travels with the scene like
  any scene custom data; harmless — restore only ever reads the window
  scene at load time.
- **Multiple windows:** `bpy.context.scene` at `load_post` is the loading
  window's scene; since all scenes carry the same snapshot, the choice is
  irrelevant.

## Files touched

| File | Change |
|---|---|
| `prefs/addon_properties.py` | +`widgets_ui_state` StringProperty on `IOPS_SceneProperties` |
| `ui/widgets/state.py` | save_pre handler; load_post restore; remove prefs persistence; pure snapshot/parse helpers |
| `prefs/iops_prefs.py` | remove WIDGETS section |
| `operators/preferences/io_addon_preferences.py` | remove `widgets_state` round-trip |
| `tests/ui/widgets/` | pytest for snapshot/parse |
| `docs/ui/` | update widget docs (persistence section) |

## Testing

- **Pure pytest:** snapshot/parse round-trip; malformed JSON → `{}`;
  unknown keys ignored; switch coercion to bool.
- **Live (reload harness):** open two widgets, move one, flip a switch,
  save, File > New → none visible; reopen file → both restored at
  positions with switch state; file with no record → all closed;
  unsaved open/close does not dirty the file.
