# UV Image Slots Widget — Design

**Date:** 2026-06-30
**Branch (current):** `feat/vertex-color-widget` (new branch to be created for this work)
**Status:** Design — approved pending spec review

## Goal

A GPU widget that lets the user flip the active image of the UV/Image editor
between a few remembered choices in **one click**, operable from **both** the
3D viewport and the UV/Image editor.

Motivating workflow: the user repeatedly flips between 2–3 textures (e.g. while
texturing / unwrapping) and wants quick-access slots instead of hunting through
the image browser.

## Decisions (locked)

| Question | Decision |
|----------|----------|
| Picker style | Per-slot **dropdown** (assign) + **flip button** (one-click activate) |
| Slot count | **Fixed 3** rows, hardcoded in JSON |
| Persistence | **Session only** — on `WindowManager`, never saved to disk |
| Implementation | **Pure-JSON widget + concrete RNA properties** (Rename-Objects pattern) |
| Render scope | **Both** 3D view and UV/Image editor (one panel, anchored to whichever editor it was toggled from) |
| Generic session-ref system | **Deferred** — ship concrete `window_manager.iops_uv_slot_N` props now; extract a generic `"ref"` binding later if a 2nd use case appears |

### Why concrete props, not a generic ref system

The existing `switch` mechanism (`widgets/composed.py:258`, `switch_adapter`)
already proves a control can bind to a named session value instead of an RNA
path. A fully generic, Python-mutable, typed session-ref registry is the right
long-term abstraction, but it is a separate piece of infrastructure. Per YAGNI
we ship the concrete properties now; the switch precedent keeps a later
extraction cheap. **Out of scope for this spec.**

## Architecture

Four pieces. Piece 1 is reusable framework work; pieces 2–4 are this widget.

### 1. Framework: multi-space widget support (new, reusable)

Today the widget system is **VIEW_3D-only in practice**, even though
`widget.space` is parameterized:

- `state.SPACE_TYPES` has only `{"VIEW_3D": bpy.types.SpaceView3D}`
  (`ui/widgets/state.py:46`) → only a VIEW_3D draw handler is ever created.
- The interaction keymap is registered only on `"3D View"`
  (`ui/widgets/events.py:509`), and the stray-sweep above it
  (`events.py:500-506`) actively removes `iops.widget_interact` from any other
  keymap.
- Cursor-summon hardcodes `VIEW_3D` (`events.py:96`).

Changes to support a widget living in more than one editor:

1. **`state.SPACE_TYPES`** gains `"IMAGE_EDITOR": bpy.types.SpaceImageEditor`.
2. **`Widget.space` becomes a set of space types.** A plain string is
   normalized to a 1-element set on assignment so all existing single-space
   widgets keep working unchanged. Introduce `Widget.spaces` (the normalized
   set); keep `space` as the authored value.
3. **Audit and update every `widget.space` consumer:**
   - Anchor match (`events.py:68`): `area.type != widget.space`
     → `area.type not in widget.spaces`.
   - `find_largest_area(space)` fallback (`state.py`): when toggled from a
     non-matching area, fall back to the largest area whose type is in the
     widget's spaces (new `find_largest_area_in(spaces)` or pass the set).
   - Cursor-summon (`events.py:96`): `context.area.type == "VIEW_3D"`
     → `context.area.type in state.SPACE_TYPES`.
4. **`ensure_draw_handler`** installs a draw handler for every space type used
   by any currently-visible widget (not just VIEW_3D). The existing draw
   callback already draws only in the anchored area, so only the editor holding
   the panel actually renders it; the extra handler is inert otherwise.
5. **Keymap:** register an `"Image"` keymap (`space_type="IMAGE_EDITOR"`) with
   the same poll-gated `LEFTMOUSE PRESS any=True` → `iops.widget_interact`
   entry. **Relax the stray-sweep** (`events.py:500`) so it preserves both
   `"3D View"` and `"Image"` (sweep only keymaps that are neither).
6. **Reload integration:** `_reload_keymaps()` (see `load_hotkeys.py`) must
   re-register both keymaps after a user keymap reload — verify the image
   keymap is included.

**Behavior:** one widget instance, anchored to whichever editor it was toggled
from (3D view *or* UV/Image editor), one place at a time. Not rendered in two
areas simultaneously.

`iops.widget_interact` poll already gates on `context.area.type in
state.SPACE_TYPES` (`events.py:119`), so adding IMAGE_EDITOR to the map enables
clicks there automatically once the keymap exists.

### 2. State — session-only, on WindowManager

Three slots. Each slot needs two backing fields, registered once at addon load
(before they are referenced; Rename-Objects ordering pattern):

- `iops_uv_slot_N` — a dynamic `EnumProperty` whose `items` callback returns the
  current `bpy.data.images`, with `get`/`set` functions bridged to a backing
  `StringProperty` holding the **image name**. The DROPDOWN control binds to
  this enum.
- `iops_uv_slot_N_name` — the backing `StringProperty` (the durable store,
  survives image-list reordering — the enum's int index would not).

Registered on `bpy.types.WindowManager` (e.g. `wm.iops_uv_slot_0` …
`wm.iops_uv_slot_2`). WindowManager properties are **not** written to the
`.blend`, satisfying session-only.

**Enum/string bridge rationale:** Blender dynamic enums (items-as-callback)
store the selected *integer index*, which shifts when the image list reorders
and risks the well-known string-GC crash. Bridging `get`/`set` to a name-holding
`StringProperty` makes the stored selection stable and reorder-proof. The enum's
`get` looks up the stored name's current index (or 0 / a sentinel if missing);
`set` writes the chosen item's name into the string.

> Implementation note (to verify in Blender 5.1.2): keep a module-level
> reference to the items list returned by the enum callback to avoid the
> string-lifetime crash, per the standard dynamic-enum idiom.

### 3. Flip operator — `iops.uv_image_slot_flip`

```
iops.uv_image_slot_flip(slot: IntProperty)
```

- Reads slot N's stored image name from `wm.iops_uv_slot_N_name`.
- Resolves it via `bpy.data.images.get(name)`.
- **Targets an image editor regardless of where it was invoked:**
  - if `context.space_data` is a `SpaceImageEditor` → set `context.space_data.image`;
  - else find the largest `IMAGE_EDITOR` area in `context.window.screen` and set
    that space's `.image`.
- No-op with an `INFO` report when: slot empty, stored image was deleted, or no
  image editor is open. Returns `{"CANCELLED"}` in those cases, `{"FINISHED"}`
  otherwise. One undo step.

`op_kwargs={"slot": N}` is passed from the JSON button (the existing
`ActionButton` `kwargs` path).

### 4. The widget — pure JSON

File: `presets/IOPS/widgets/uv_image_slots.json` (source path on the dev
symlink: `B:\scripts\presets\iops\widgets\uv_image_slots.json`).

```jsonc
{
  "name": "uv_image_slots",
  "label": "UV Image Slots",
  "space": ["VIEW_3D", "IMAGE_EDITOR"],
  "rows": [
    { "type": "ROW", "cells": [
      { "type": "DROPDOWN", "prop": "window_manager.iops_uv_slot_0", "label": "1" },
      { "type": "BUTTON", "label": "▶", "op": "iops.uv_image_slot_flip", "op_kwargs": { "slot": 0 } }
    ]},
    { "type": "ROW", "cells": [
      { "type": "DROPDOWN", "prop": "window_manager.iops_uv_slot_1", "label": "2" },
      { "type": "BUTTON", "label": "▶", "op": "iops.uv_image_slot_flip", "op_kwargs": { "slot": 1 } }
    ]},
    { "type": "ROW", "cells": [
      { "type": "DROPDOWN", "prop": "window_manager.iops_uv_slot_2", "label": "3" },
      { "type": "BUTTON", "label": "▶", "op": "iops.uv_image_slot_flip", "op_kwargs": { "slot": 2 } }
    ]}
  ]
}
```

- **DROPDOWN** shows/assigns each slot's image (items read live each draw via
  `rna_enum_items` → the enum callback). Selecting only *assigns* the slot; it
  does not activate (the dropdown's RNA write just stores the name).
- **BUTTON** flips the editor to the slot's image in one click.
- `"space"` accepts a list (the JSON schema / `validate_def` must allow a list
  of space types in addition to a single string).

**Schema / validation changes:** `widgets/composed.py validate_def` (and the
JSON schema doc) must accept `"space"` as either a string or a list of valid
space-type strings.

## Data flow

```
Assign:  user picks image in DROPDOWN
         → rna_value_adapter.set writes name into wm.iops_uv_slot_N (enum set → string)
Flip:    user clicks BUTTON
         → iops.uv_image_slot_flip(slot=N)
         → read wm.iops_uv_slot_N_name → bpy.data.images.get(name)
         → locate target SpaceImageEditor (current or largest in screen)
         → space.image = img   (INFO no-op if missing)
```

## Error handling

- Stored image deleted between assign and flip → `images.get` returns `None`
  → INFO no-op. The dropdown's enum `get` falls back to a sentinel/0 so the
  control never errors on a stale name.
- No image editor open when flipping from the 3D view → INFO no-op.
- Empty slot (never assigned) → INFO no-op.
- Multi-space draw/anchor failures are already swallowed by the existing
  per-widget draw guard (`state._draw_error_logged`).

## Testing

Mirror the existing `tests/ui/widgets` pytest suite (bpy-free where possible):

- **Pure logic, no Blender:**
  - Enum↔string bridge: `set` stores the chosen name; `get` returns the index
    of the stored name; missing name → sentinel; reorder-stability.
  - Flip target resolution: given a fake context (space is image editor vs.
    not, with/without an IMAGE_EDITOR area in the screen), the operator picks
    the right target or no-ops. Factor the resolution into a pure helper
    (`resolve_image_space(context)`) so it is testable without `bpy`.
  - `validate_def` accepts list-valued `"space"`; rejects unknown space types.
  - `find_largest_area_in(spaces)` selection logic.
- **Live-verify in Blender 5.1.2** (manual — MCP cannot inject modal clicks):
  toggle widget in 3D view and in UV editor; assign 3 images; flip from each
  space; delete an assigned image and confirm graceful no-op; reload via dev
  infra and confirm both keymaps re-register.

## Out of scope

- Generic session-ref / custom-property binding system (deferred; see above).
- Cross-file or cross-session persistence of slot assignments.
- Configurable slot count.
- Auto-recency / history slots.
- Simultaneous render of the same widget in two areas at once.
- Setting the active image for texture paint / material nodes (UV-Image editor
  only).

## Affected files

- `ui/widgets/state.py` — `SPACE_TYPES`, `find_largest_area` for a space set,
  draw-handler-per-space.
- `ui/widgets/events.py` — multi-space anchor match, cursor-summon, `"Image"`
  keymap, stray-sweep relaxation.
- `ui/widgets/__init__.py` — `Widget.space` set normalization (`spaces`).
- `widgets/composed.py` — `validate_def` list-valued `"space"`.
- New: WM property registration + `iops.uv_image_slot_flip` operator (location
  to follow existing widget-operator conventions, e.g. an `operators/` module
  or alongside the widget registration).
- New JSON: `presets/IOPS/widgets/uv_image_slots.json`.
- `load_hotkeys.py` `_reload_keymaps()` — include the image keymap.
- Docs: JSON schema reference — `"space"` may be a list.
- Tests: `tests/ui/widgets/` additions.
