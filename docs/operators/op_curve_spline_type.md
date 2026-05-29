# Spline Type

Modal operator that converts the spline type of selected curve control points to POLY, BEZIER, or NURBS via single-key shortcuts. Wraps Blender's `curve.spline_type_set` with an optional handle-preservation toggle and an on-screen HUD that shows the current spline type of the active spline.

<div class="iops-meta" markdown="1">
<span class="key">bl_idname: iops.curve_spline_type</span>
<span class="mode">Mode: Edit Curve</span>
<span>Context: VIEW_3D</span>
<span class="modal">Modal: yes</span>
<span class="hud">HUD: yes</span>
</div>

## Overview
The native Blender command `curve.spline_type_set` requires either a property dialog or a keymap entry per target type. This operator collapses the three target types onto F1/F2/F3 inside a single modal session and exposes the `use_handles` flag as a live toggle, so you can flip handle preservation on and off before committing the conversion.

## Usage
- Active object must be a curve in Edit Mode with at least one control point selected (the `poll` requires an active CURVE object in EDIT mode; the conversion itself acts on the current curve selection).
- Invoke the operator (no default keymap binding; call via menu, F3 search, or a pie).
- Press F1, F2, or F3 to pick a target type and commit. Use H beforehand if you want handles preserved on the conversion.

## Modal Controls

| Key | Action |
| --- | --- |
| <kbd>F1</kbd> | Convert selection to POLY and finish |
| <kbd>F2</kbd> | Convert selection to BEZIER and finish |
| <kbd>F3</kbd> | Convert selection to NURBS and finish |
| <kbd>H</kbd> | Toggle `use_handles` (also bound to the help overlay toggle) |
| <kbd>RMB</kbd> / <kbd>Esc</kbd> | Cancel without converting |
| <kbd>MMB</kbd> / <kbd>WheelUp</kbd> / <kbd>WheelDown</kbd> | Pass through (view navigation) |

The HUD and help overlay also consume drag and parameter-toggle events through the shared HUD framework.

## HUD
- Title bar: "Curve Spline Type".
- Header line: `Current type: <type>` reflecting the active spline's type captured at invoke.
- Help overlay (toggled via the HUD framework's help key) lists: Use handles (H), Spline POLY (F1), Spline BEZIER (F2), Spline NURBS (F3), Cancel (Esc / RMB), Help / Toggle HUD (H). The H entry mirrors the current `handles` state (ON/OFF).

HUD colours follow the addon's `iops_theme` preferences block.

## Properties

| Name | Type | Default | Description |
| --- | --- | --- | --- |
| `handles` | BoolProperty | `False` | Passed to `curve.spline_type_set` as `use_handles`; when on, Blender attempts to keep handle positions across the conversion. Reset to `False` on each invoke. |

Internal state `spl_type` (current target string) and `curv_spline_type` (active spline type read at invoke) are class attributes, not bl_props.

## Notes
- `invoke` aborts with a WARNING report if there is no active object or the area is not VIEW_3D.
- The operator finishes immediately on F1/F2/F3 press — there is no separate confirm key.
- The conversion is a single `curve.spline_type_set` call, so undo creates one step and Blender's own restrictions apply (e.g. converting between types may discard handle data when `use_handles` is off).
- `handles` and `spl_type` are reassigned every invoke, so re-running the operator never inherits the previous session's flags.

## Related
- Curves Smooth/Sharp (sibling curve-edit operator if present in your build)
- Curve Cyclic

