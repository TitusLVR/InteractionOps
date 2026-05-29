# Easy Mod — Array

Two operators that wire up Array (and optionally Curve) modifiers from the current selection. The "Caps" variant is modal and lets you tweak cap orientation, count, and an optional curve interactively; the "Curve" variant is a one-shot setup that builds an Array + Curve combo from a mesh and a curve. Both target the common pain point of manually picking cap objects, fixing origins, and configuring fit type by hand.

## IOPS_OT_Easy_Mod_Array_Caps (bl_idname: iops.modifier_easy_array_caps)

<div class="iops-meta" markdown="1">
<span class="key">bl_idname: iops.modifier_easy_array_caps</span>
<span class="mode">Mode: Object</span>
<span>Context: VIEW_3D</span>
<span class="modal">Modal: yes</span>
<span class="hud">HUD: yes</span>
</div>

### Overview
Modal helper that takes three or four selected objects — an active mid mesh, one or two cap meshes, and an optional curve — and builds a "CappedArray" Array modifier (plus optional "CappedArrayCurve" Curve modifier) on the active object. Cap origins are snapped to the mid object's bounding-box extents along the chosen axis so caps land cleanly against the array's start and end. Use it when you want to set up capped trims/extrusions without bouncing through the modifier panel and the origin tools.

### Usage
- Selection: 3 or 4 objects in Object Mode. Active is the mid mesh; remaining mesh objects become caps (1 = end cap only; 2 = start + end), and a CURVE in the selection becomes the deform curve. Curve gets `use_stretch` and `use_deform_bounds` enabled, and is renamed `<mid>_CURVE`.
- Context: VIEW_3D with an active object.
- Invocation: no default keymap binding — call via menu/search/Pie.
- The modal runs until you confirm or cancel; each key edits the live scene.

### Modal Controls
| Key | Action |
| --- | --- |
| <kbd>F</kbd> | Swap start/end caps (only when two caps are present); rewires `start_cap` / `end_cap` on the modifier |
| <kbd>X</kbd> | Place cap origins along world X relative to mid object dimensions |
| <kbd>Y</kbd> | Place cap origins along world Y relative to mid object dimensions |
| <kbd>Z</kbd> | Place cap origins along world Z relative to mid object dimensions |
| <kbd>A</kbd> | Toggle the `CappedArray` Array modifier on the mid object; wires caps when added |
| <kbd>NumpadPlus</kbd> | Increase array count by 1 |
| <kbd>NumpadMinus</kbd> | Decrease array count by 1 (min 1) |
| <kbd>C</kbd> | Toggle the `CappedArrayCurve` Curve modifier; snaps curve origin to mid object, sets Array `fit_type` to `FIT_CURVE` and links the curve |
| <kbd>H</kbd> | Toggle HUD / Help overlay (via shared HUD handlers) |
| <kbd>MMB</kbd> / <kbd>WheelUp</kbd> / <kbd>WheelDown</kbd> | Pass-through for viewport navigation |
| <kbd>LMB</kbd> / <kbd>Space</kbd> / <kbd>Enter</kbd> | Confirm — selects mid object, removes HUD handler |
| <kbd>RMB</kbd> / <kbd>Esc</kbd> | Cancel — selects mid object, removes HUD handler (scene edits are not rolled back) |

HUD and Help overlays also handle drag and parameter-toggle events via the shared `HUDOverlay` / `HelpOverlay` machinery.

### HUD
Two overlays drawn via `safe_handler_add` on `SpaceView3D` in `POST_PIXEL`:

- `HUDOverlay("easy_mod_array")` titled "Easy Array" — bound to the active region.
- `HelpOverlay("easy_mod_array")` with a single "Easy Array" section listing every modal key (Flip, X/Y/Z, A, +/-, C, Apply, Help) as always-shown items.

Colours come from the addon's `iops_theme` preferences; both overlays are draggable and the help overlay can be toggled with `H`.

### Properties
This operator exposes no `bl_props`; all state is captured from the selection at `invoke()` time.

### Notes
- Cap objects are renamed to `<mid>_START_CAP` / `<mid>_END_CAP` as soon as the modal starts processing events.
- With one cap only, the cap is assigned as `end_cap`; `start_cap` is left untouched and `F` becomes a no-op.
- Cancel does not undo scene changes (origin moves, renames, modifier add/remove) — those are persisted on the underlying data.
- `invoke()` aborts with a "Tree objects needed, start, middle and end" warning if the selection count is not 3 or 4.

## IOPS_OT_Easy_Mod_Array_Curve (bl_idname: iops.modifier_easy_array_curve)

<div class="iops-meta" markdown="1">
<span class="key">bl_idname: iops.modifier_easy_array_curve</span>
<span class="mode">Mode: Object</span>
<span>Context: VIEW_3D</span>
<span class="modal">Modal: no</span>
<span class="hud">HUD: no</span>
</div>

### Overview
One-shot setup for an Array-along-Curve combo. With a mesh + curve selected, it snaps the curve's origin to its first spline point, aligns the mesh location to the curve, and adds an `iOps Array` modifier configured to `FIT_CURVE`, plus an optional `iOps Curve` modifier wired to the same curve. With a single mesh selected, if that mesh already has an Array+FIT_CURVE modifier, it selects the linked curve instead — handy as a "jump to my path" shortcut.

### Usage
- Selection (mode A): exactly two objects, one MESH and one CURVE.
- Selection (mode B): one MESH that already has an Array modifier with `fit_type == 'FIT_CURVE'` and a linked curve — runs the "select the curve" shortcut.
- Mode: Object (`poll` requires `context.mode == 'OBJECT'` and `area.type == 'VIEW_3D'`).
- Invocation: no default keymap binding — call via menu/search/F3.
- Supports POLY, BEZIER, and NURBS curves for the origin-snap step.

### Properties
| Name | Type | Default | Description |
| --- | --- | --- | --- |
| `use_array_fit_curve` | BoolProperty | True | When the mesh already has an Array modifier, switch its `fit_type` to `FIT_CURVE` and link the picked curve; otherwise leave the existing setting |
| `use_array_merge` | BoolProperty | True | On a newly created Array modifier, enable `use_merge_vertices` |
| `array_merge_distance` | FloatProperty | 0.001 | Merge threshold (soft_min 0.0, soft_max 1_000_000.0) used when `use_array_merge` is on |
| `add_curve_mod` | BoolProperty | True | Add an `iOps Curve` modifier after the Array modifier on a fresh setup |
| `use_curve_radius` | BoolProperty | True | Sets `curve.data.use_radius` — deformed object scales by curve radius |
| `use_curve_stretch` | BoolProperty | True | Sets `curve.data.use_stretch` — mesh stretches/squeezes over the curve length |
| `use_curve_bounds_clamp` | BoolProperty | True | Sets `curve.data.use_deform_bounds` — ignore offset along deform axis |
| `curve_modifier_axis` | EnumProperty | `POS_X` | Curve modifier `deform_axis`. Items: `POS_X` (X), `POS_Y` (Y), `POS_Z` (Z), `NEG_X` (-X), `NEG_Y` (-Y), `NEG_Z` (-Z) |

### Notes
- When the mesh already has any modifiers, the operator iterates them in reverse and rewires the **first** Array modifier it finds to the picked curve (if `use_array_fit_curve` is on); it does not add a new Array modifier in that branch, and `use_array_merge` / `add_curve_mod` are skipped.
- A fresh `iOps Curve` modifier is created with `show_in_editmode = True` and `show_on_cage = True`.
- The mesh's `location` is overwritten with the curve's location after the origin snap, so it visually starts at the curve's first point.
- Falls through to `return {"FINISHED"}` even when the selection does not match either branch — no warning is reported.

## Related
- Easy Mod — Boolean
- Easy Mod — Mirror
- Easy Mod — Solidify
