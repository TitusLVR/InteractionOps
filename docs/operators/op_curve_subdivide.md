# Curve Subdivide

Modal operator that inserts evenly-spaced cuts between selected bezier control points on the active curve. The mouse wheel adjusts the cut count in real time and a viewport overlay previews the resulting points along the bezier segments before the cut is committed.

<div class="iops-meta" markdown="1">
<span class="key">bl_idname: iops.curve_subdivide</span>
<span class="mode">Mode: Edit Curve</span>
<span>Context: VIEW_3D</span>
<span class="modal">Modal: yes</span>
<span class="hud">HUD: yes</span>
</div>

## Overview
Blender's built-in `curve.subdivide` requires opening the redo panel to change the number of cuts. This operator wraps the same call in a modal loop so the cut count can be scrubbed with the mouse wheel while a live preview shows where new points will land along each selected bezier segment. The actual subdivision is performed once on confirm via `bpy.ops.curve.subdivide(number_cuts=...)`.

## Usage
- Active object must be a `CURVE` in `EDIT` mode.
- Select two or more adjacent bezier control points on the spline(s) to subdivide.
- Invoke the operator (no default keymap binding — call via menu, search, or a user-assigned shortcut).
- Scroll the wheel to set the cut count, then confirm.

## Modal Controls
| Key | Action |
| --- | --- |
| <kbd>WheelUp</kbd> | Increase cut count by 1 |
| <kbd>WheelDown</kbd> | Decrease cut count by 1 (clamped at minimum 1) |
| <kbd>MMB</kbd> | Pass-through (view navigation) |
| <kbd>LMB</kbd> / <kbd>Space</kbd> | Confirm — run subdivide and exit |
| <kbd>Esc</kbd> / <kbd>RMB</kbd> | Cancel — discard and exit |
| <kbd>H</kbd> | Toggle help overlay / HUD (handled by HUD subsystem) |

The HUD subsystem also consumes drag events on HUD/help panels and param-toggle clicks before the operator's own key handling.

## HUD
The header shows `Cuts: <N>` reflecting the current cut count. The help overlay (toggle with <kbd>H</kbd>) lists:

- Cuts — Wheel
- Confirm — LMB / Space
- Cancel — Esc / RMB
- Help / Toggle HUD — H

A POST_VIEW handler draws the predicted new point positions in 3D using `Role.PREVIEW_POINT` from the active theme, sampled along the cubic bezier between each pair of consecutive selected control points using `1 / (cuts + 1)` parametric spacing.

## Properties
| Name | Type | Default | Description |
| --- | --- | --- | --- |
| `points_num` | Int | 1 | Number of cuts inserted between each pair of selected control points. Reset to 1 on `invoke`. |

## Notes
- Cancelling removes the draw handlers without performing the subdivide, leaving the curve untouched.
- The live preview samples only consecutive entries of selected control points in iteration order; non-adjacent selections still produce preview points, but the underlying `curve.subdivide` operator only cuts genuinely connected selected segments.
- Registered as `REGISTER | UNDO`, so the post-confirm redo panel can still adjust `Number of cuts`.
- `invoke` requires a `VIEW_3D` area and an active object; otherwise it reports a warning and cancels.

## Related
- [Curve Spline Type Toggle](op_curve_spline_type.md)
- Curve Set Handles
