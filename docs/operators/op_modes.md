# Modes (F1-F5)

The Modes operators are the central dispatch for InteractionOps. Each of the six operators (F1, F2, F3, F4, F5, ESC) builds a context query from the current area type, object type, object mode, mesh/UV select mode, the operator key, and the active modifier combination, then looks up the matching callable in `IOPS_Dict` and runs it. This lets a single keypress mean different things in different contexts (e.g. F1 in Object Mode vs F1 in Edit Mesh / Vertex mode) without per-context keymaps.

<div class="iops-meta" markdown="1">
<span class="key">bl_idname: iops.function_f1, iops.function_f2, iops.function_f3, iops.function_f4, iops.function_f5, iops.function_esc</span>
<span class="mode">Mode: any (dispatch depends on active area, object type, and selection mode)</span>
<span>Context: any editor (VIEW_3D, IMAGE_EDITOR, etc.)</span>
<span class="modal">Modal: no</span>
<span class="hud">HUD: no</span>
</div>

## Overview

All six operators share a single base class (`IOPS_OT_Main` in `operators/iops.py`). The subclasses in `operators/modes.py` only set the `operator` attribute ("F1".."F5", "ESC") used as part of the lookup key.

On invoke, the operator captures `event.alt`, `event.ctrl`, `event.shift`, then builds a query tuple:

`(area_type, use_uv_select_sync, object_type, object_mode, uv_mode, mesh_mode, operator, modifier_state)`

`modifier_state` is one of `NONE`, `ALT`, `CTRL`, `SHIFT`, or any `_`-joined combination (e.g. `ALT_CTRL`). The query is resolved through `utils.functions.get_iop` against `utils.iops_dict.IOPS_Dict.iops_dict`. If a match is found, the bound function runs; otherwise the operator reports `"No operation defined for this context"`. With no active object, the query degenerates to `(area_type, None, None, None, None, None, op, event)` so area-only fallbacks still work.

Special case: when the active object is `CURVES` and its mode is `EDIT_CURVES`, the mode is rewritten to `EDIT` before the lookup so curve sculpt/edit hair contexts can share entries with classic curve edit. When `tool_settings.use_uv_select_sync` is on, `mode_uv` is overwritten with the mesh select mode.

## Usage

- Works in any editor area that has focus; the cursor must be over a Blender window (otherwise the operator reports "Focus your mouse pointer on corresponding window.").
- Invoke via default keymap (see below) or by searching for the bl_idname.
- Hold Alt / Ctrl / Shift (or combinations) while pressing the function key to select a different entry in the dispatch table for the same context.
- To customize what a given (context, key, modifier) combination does, edit `utils/iops_dict.py`.

Default keymap bindings (from `prefs/hotkeys_default.py`):

| Operator | Key | Modifiers |
| --- | --- | --- |
| `iops.function_f1` | F1 | none |
| `iops.function_f2` | F2 | none |
| `iops.function_f3` | F3 | none |
| `iops.function_f4` | F4 | none |
| `iops.function_f5` | F5 | none |
| `iops.function_esc` | ESC | none |

The same physical keys with modifiers route to other dedicated operators (e.g. Alt+F1 -> `iops.mesh_to_verts`). The Alt/Ctrl/Shift branching inside the F1..F5 operators applies only when the bound keymap entry itself fires them with those modifiers held.

## Properties

None. The operators carry no `bl_props`; behaviour is fully driven by the lookup table.

## Notes

- `bl_options = {"REGISTER"}` only - no undo push from the dispatcher itself; the dispatched function is responsible for its own undo behaviour.
- ESC (`iops.function_esc`) is a regular dispatch entry, not a modal cancel. It only runs whatever `IOPS_Dict` maps to the `"ESC"` operator for the current context.
- If the dispatch table has no entry for the resolved query, nothing happens beyond a `WARNING` report - this is the normal way to "no-op" a key in a given context.
- All six classes inherit from `IOPS_OT_Main`; that base class itself is not registered as a usable operator (it has `bl_idname = "iops.main"` but exists only as a parent).

## Related

- [Pie Menus](../ui/ui_pies.md)
- [Mesh Selection Mode (Verts/Edges/Faces)](op_mesh_convert_selection.md)
