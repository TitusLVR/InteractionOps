# iOps Dispatcher

Context-aware dispatch operator that maps a slot key (F1-F5, ESC) plus the current modifier state and editor context to a concrete InteractionOps function. It is the base class every F-key operator inherits from, and the single lookup point that turns "user pressed F2 in UV Edit with Shift" into the correct registered action via `IOPS_Dict`.

<div class="iops-meta" markdown="1">
<span class="key">bl_idname: iops.main</span>
<span class="mode">Mode: any (resolved at runtime)</span>
<span>Context: any area (VIEW_3D, IMAGE_EDITOR, etc.)</span>
<span class="modal">Modal: no</span>
<span class="hud">HUD: no</span>
</div>

## Overview

`iops.main` is the heart of the InteractionOps dispatcher. On invoke it captures the current `event.alt / ctrl / shift` state, then on execute it builds an 8-tuple query from:

- `bpy.context.area.type`
- `tool_settings.use_uv_select_sync`
- active object `type` and `mode`
- UV select mode (prefixed `UV_`, or replaced by the 3D mesh mode when UV-sync is on)
- mesh select mode (`VERT` / `EDGE` / `FACE`)
- the class-level `operator` slot (`F1` / `F2` / `F3` / `F4` / `F5` / `ESC`)
- a modifier string (`NONE`, `ALT`, `CTRL`, `SHIFT`, or underscore-joined combinations such as `ALT_CTRL_SHIFT`)

That tuple is passed to `get_iop(IOPS_Dict.iops_dict, query)`. If the dictionary returns a callable, it is invoked; otherwise the operator reports `No operation defined for this context`. With no active area focus it reports `Focus your mouse pointer on corresponding window.`.

The class is not meant to be bound directly; it is subclassed by the F-key slot operators in `operators/modes.py` and by other dispatch-style operators (e.g. `IOPS_OT_CursorOrigin_Mesh`) that need the same context-aware behaviour but a different slot value.

## Usage

- Active area must be focused (the operator early-outs if `bpy.context.area` is missing).
- An active object in the view layer is preferred; without one the query degrades to area + slot + modifiers and only matches dictionary entries written for that "no object" case.
- Not invoked directly by the user. Trigger via the subclass slot operators: `iops.function_f1` ... `iops.function_f5` and `iops.function_esc`. The default keymap binds these to <kbd>F1</kbd>-<kbd>F5</kbd> and <kbd>Esc</kbd> respectively, with no modifiers.

## Notes

- `iops.main` has no `bl_props` and no UI. All behaviour is data-driven through `utils/iops_dict.py` and `utils/functions.get_iop`.
- Subclasses inherit invoke/execute and only override the `operator` class attribute (the slot label) and `bl_idname` / `bl_label`. Pattern (from `operators/modes.py`):

  | bl_idname | Slot | Default key |
  | --- | --- | --- |
  | `iops.function_f1` | F1 | <kbd>F1</kbd> |
  | `iops.function_f2` | F2 | <kbd>F2</kbd> |
  | `iops.function_f3` | F3 | <kbd>F3</kbd> |
  | `iops.function_f4` | F4 | <kbd>F4</kbd> |
  | `iops.function_f5` | F5 | <kbd>F5</kbd> |
  | `iops.function_esc` | ESC | <kbd>Esc</kbd> |

- `bl_options = {"REGISTER"}` only - dispatched calls handle their own undo pushes; the dispatcher itself does not register undo.
- The `CURVES` object type in `EDIT_CURVES` mode is normalised to `EDIT` before the query is built, so a single dictionary entry covers both legacy curves and the new Curves object.
- When `use_uv_select_sync` is on, the UV mode slot is overwritten with the 3D mesh mode so the same dictionary row matches both selection paradigms.
- This file registers only `IOPS_OT_Main`. The F-key subclasses live in `operators/modes.py` and are registered alongside it from `__init__.py`.

## Related

- [Modes Slots (F1-F5/ESC)](op_modes.md)
- iOps Dictionary
