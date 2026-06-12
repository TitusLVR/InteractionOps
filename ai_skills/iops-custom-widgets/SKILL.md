---
name: iops-custom-widgets
description: Use when adding, editing or debugging a persistent GPU widget panel in the InteractionOps (iOps) Blender addon — clickable viewport panels with sliders/checkboxes/buttons, widget JSON defs, iops.widget_toggle hotkeys, or "widget doesn't show/refresh/click" issues.
---

# Writing iOps Custom Widgets

## Overview

A widget is a persistent, clickable GPU panel in the 3D viewport. Framework:
`ui/widgets/` (registry, controls, render, events, state). Concrete widgets:
`widgets/`. Everything is drawn by one shared POST_PIXEL handler and clicked
through the transient `iops.widget_interact` modal — a widget only declares
**controls bound to get/set callables**. Show/hide, dragging, position
persistence, per-widget toggle hotkeys: all free.

## Decide: JSON or Python

| | JSON-composed | Python class |
|---|---|---|
| Binds | edge attributes only (BEVEL/CREASE float, SHARP/SEAM/FREESTYLE bool via `widgets/adapters.py`) | anything you can get/set from `context` |
| Lives in | `<user scripts>/presets/IOPS/widgets/<name>.json` | `widgets/<name>.py` in the repo |
| Created by | prefs Widgets tab (Add/Duplicate/Import) or by hand | code + registration wiring |

JSON schema (validated by `widgets/composed.py:validate_def`, row types
SECTION/SLIDER/PRESETS/FLIPBOX/BUTTON) — copy `EDGE_DATA_DEF` in
`widgets/composed.py` as the reference. Files auto-load at register; the
prefs Widgets tab list mirrors them.

For anything NOT edge-attribute-bound, write a Python widget:

## Python Widget — complete pattern

`widgets/my_widget.py`:

```python
from ..ui.widgets import (Widget, Section, Slider, PresetRow, FlipBox,
                          ActionButton, Row)

def _get_flag(context):
    # CONTRACT: get(context) -> (value, is_mixed).
    # value=None => control renders DISABLED (use for "source missing").
    scene = context.scene
    if not hasattr(scene, "some_prop"):
        return (None, False)
    return (bool(scene.some_prop), False)

def _set_flag(context, value):
    # CONTRACT: set(context, value) writes to ALL targets; re-resolve data
    # every call — NEVER cache RNA/bmesh references (controls cache plain
    # values only).
    if hasattr(context.scene, "some_prop"):
        context.scene.some_prop = bool(value)

class MyWidget(Widget):
    name = "my_widget"     # identity EVERYWHERE: registry, saved state,
    title = "My Widget"    # toggle-kmi properties.name
    space = "VIEW_3D"

    def build(self):
        return [
            Section("Flags"),
            Row([FlipBox("Flag", get=_get_flag, set=_set_flag)]),  # Row = N per line
            ActionButton("Run", op="some.operator", kwargs={},
                         role="default"),   # "error" = red destructive style
        ]

    def poll(self, context):
        return True   # see gotcha: False collapses panel, hardcoded hint
```

Wire into `widgets/__init__.py` inside the `_HAS_BPY` block, mirroring
`EdgeDataWidget` in all three spots: import-time `register_widget(...)`,
`register()`, and `unregister_widget(MyWidget.name)` in `unregister()`.

**Widget targets another addon that may be absent?** Register
UNCONDITIONALLY and make the bindings absence-safe: getters return
`(None, False)` (controls render disabled), setters no-op, button
`enabled_get` probes presence. Do NOT gate registration on a presence
probe like `hasattr(bpy.types.Scene, "CCP")` — addon load order isn't
ours, so the probe misses the other addon enabling after iOps and the
widget silently vanishes for the session. Never import the other addon's
modules; resolve its data lazily from `context` per call.

## Control signatures (ui/widgets/controls.py)

```
Section(label)
Slider(get, set, vmin=0.0, vmax=1.0, snap=0.125, fmt="{:.3f}",
       snapshot=None, restore=None)      # snapshot/restore: ESC-cancel hooks
PresetRow(values, set, fmt="{:g}", enabled_get=None)
FlipBox(label, get, set)
ActionButton(label, op, kwargs=None, role="default", enabled_get=None)
Row(children)                            # N controls on one panel line
```

`is_mixed` in the getter tuple is for multi-element selections (mixed
FlipBox click writes True to all); scalar bindings (a single scene/object
prop) always return `False` for it.

## Summon + hotkey

- `bpy.ops.iops.widget_toggle(name="my_widget")` — toggles at cursor.
- `events.sync_toggle_kmis()` auto-creates one unbound `iops.widget_toggle`
  keymap entry per registered widget; the prefs **Widgets tab list row**
  shows the key-capture field (Python widgets appear as locked rows).
  No code needed.

## Gotchas

| Symptom / trap | Reality |
|---|---|
| Getter returns bare value | Must return `(value, is_mixed)` tuple — bare value breaks render/interact |
| `poll() -> False` | Collapses panel to title + HARDCODED "Go back to Edit Mode" (`render.py OUT_OF_CONTEXT_TEXT`). Only use for real mode-gating; for "addon missing" return True and disable controls via `(None, False)` |
| Widget doesn't refresh after external change | Cache invalidates on depsgraph/undo/redo handlers (`ui/widgets/state.py`). No depsgraph tick = stale until one |
| ActionButton op string | Split on first dot: `"ccp_tools.update_red_file"` → `bpy.ops.ccp_tools.update_red_file("INVOKE_DEFAULT", **kwargs)`; fires on click-release; no context-override hook. INVOKE_DEFAULT matters: invoke-only operators called with EXEC_DEFAULT return `{'PASS_THROUGH'}` SILENTLY (no error, button "does nothing") |
| Renaming a widget | `name` is identity; carry hotkeys with `events.rename_toggle_kmi(old, new)` or bindings strand |
| Slider beyond 0..1 | Pass `vmin=`/`vmax=`/`snap=`/`fmt=` — defaults are 0..1, snap 0.125 |
| Imports break pytest | `ui/widgets/panel.py`+`controls.py` must stay bpy-free; your widget module may import bpy, the framework must not |
| Toggle hotkey not in Keymaps tab | Intentional — `iops.widget_toggle` entries draw ONLY in the Widgets tab list and are excluded from hotkey save files (`NEVER_SAVE`: the tuple can't carry the name property) |

## Verify

Reload addon (blinker port 9902, or disable→purge `sys.modules`→enable),
then `bpy.ops.iops.widget_toggle(name="...")` in a VIEW_3D context and
click every control. `python -m pytest tests -q` must stay green.
