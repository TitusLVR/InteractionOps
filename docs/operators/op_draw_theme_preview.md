# Draw Theme Preview

Modal viewport preview that renders one instance of every unified UI primitive — state points, state lines, preview polyline, extras (handles, pivot, cursor, bbox), and a row of ghost spheres — alongside a sample HUD and a sample Help overlay. Used from the addon Preferences "Theme" tab to verify colours, point sizes, line widths, and HUD layout against live edits.

<div class="iops-meta" markdown="1">
<span class="key">bl_idname: iops.draw_theme_preview</span>
<span class="mode">Mode: any</span>
<span>Context: VIEW_3D (auto-retargets if invoked from Preferences)</span>
<span class="modal">Modal: yes</span>
<span class="hud">HUD: yes</span>
</div>

<div class="iops-meta" markdown="1">
<span class="key">bl_idname: iops.stop_theme_preview</span>
<span class="mode">Mode: any</span>
<span>Context: any</span>
<span class="modal">Modal: no</span>
<span class="hud">HUD: no</span>
</div>

## Overview
The preview is the visual smoke test for the `ui.draw` primitive layer and the `ui.hud` overlay system. It draws every theme role that addon operators consume, so any tweak made in the Theme prefs tab is reflected in the viewport on the next frame. The draw handlers resolve the theme fresh per frame via `get_theme(context)` rather than caching, which is what makes live editing work.

The operator can be launched from the Preferences window. Because `context.area` there is `USER_PREFERENCES`, `invoke()` finds the largest open 3D viewport and re-invokes itself under a `temp_override` so the modal runs in that viewport and cursor-follow works as expected. The companion `iops.stop_theme_preview` operator flips the prefs button between "Preview" and "Stop" and requests an exit from outside the modal.

## Usage
- Open Preferences and switch to the InteractionOps Theme tab.
- Click the Preview button (calls `iops.draw_theme_preview`). At least one 3D viewport must be open; otherwise the operator reports an error and cancels.
- The preview renders at the scene cursor location in the chosen viewport.
- Click Stop, press <kbd>ESC</kbd>, or right-click in the viewport to exit.
- No default keymap binding.

## Modal Controls

| Key | Action |
| --- | --- |
| <kbd>ESC</kbd> | exit preview |
| <kbd>RMB</kbd> | exit preview |
| <kbd>S</kbd> | toggle the `Snap` HUD param (drives the `S` HUDItem state highlight) |
| <kbd>Ctrl</kbd>+<kbd>Wheel Up</kbd> / <kbd>Ctrl</kbd>+<kbd>=</kbd> / <kbd>Ctrl</kbd>+<kbd>+</kbd> | subdivisions + 1 (clamped to 20) |
| <kbd>Ctrl</kbd>+<kbd>Wheel Down</kbd> / <kbd>Ctrl</kbd>+<kbd>-</kbd> | subdivisions - 1 (clamped to 0) |
| <kbd>H</kbd> | toggle Help overlay (handled by `HelpOverlay.handle_toggle_event`) |
| <kbd>/</kbd> | hide / show HUD params (handled by `HUDOverlay.handle_param_toggle_event`) |
| <kbd>Shift</kbd>+<kbd>Ctrl</kbd>+<kbd>Alt</kbd>+<kbd>LMB</kbd> drag | reposition HUD or Help overlay |

Plain mouse wheel without <kbd>Ctrl</kbd> passes through so viewport zoom still works.

## HUD
The preview renders two overlays plus in-viewport state labels:

- **Dynamic Overlay (HUDOverlay)** — title "Dynamic Overlay". Live params:
  - `Mouse` — region-space cursor coordinates from the captured `EventSnapshot`.
  - `Snap` — boolean, toggled by <kbd>S</kbd>.
  - `Subdivisions` — integer, driven by <kbd>Ctrl</kbd>+<kbd>Wheel</kbd>.
  - `Offset` — float `{:.3f}`, dimmed unless `Snap` is on.
  Also carries a single `HUDItem("Snap toggle marker", "S")` whose ON/OFF state mirrors the `Snap` param — kept to exercise the legacy item-highlight path.
- **Help Overlay (HelpOverlay)** — corner overlay listing the modal hotkeys: Toggle snap (S), More / fewer subs (Ctrl+Wheel), Hide params (/), Toggle this help (H), Drag overlay (Shift+Ctrl+Alt+LMB), Exit (ESC/RMB).
- **In-viewport state labels** — each of the six state points is captioned with its label (`Default`, `Closest`, `Active`, `Locked`, `Result Preview`, `Error`) in the matching POINT colour and `hud_label` size. The ghost sphere row is captioned (`Default`, `Closest`, `Active`, `Locked`, `Preview`, `Target Sel`, `Match Hint`) in `Role.HUD_LABEL` so labels don't compete with the translucent fills.

What's drawn in the viewport, per `_draw_view`:

- Six-state point row using roles `POINT`, `CLOSEST_POINT`, `ACTIVE_POINT`, `LOCKED_POINT`, `PREVIEW_POINT`, `ERROR_POINT`.
- Six-state line column below the points, using roles `LINE`, `CLOSEST_LINE`, `ACTIVE_LINE`, `LOCKED_LINE`, `PREVIEW_LINE`, `ERROR_LINE`.
- A sine-shaped preview polyline above the points (`Role.PREVIEW_LINE`).
- Extras row: `HANDLE`, `HANDLE_HOVER`, `PIVOT`, `CURSOR` points enclosed in a `BBOX` rectangle.
- Ghost sphere row using fills `GHOST_DEFAULT`, `GHOST_CLOSEST`, `GHOST_ACTIVE`, `GHOST_LOCKED`, `GHOST_PREVIEW`, `GHOST_TARGET_SEL`, `GHOST_MATCH_HINT` with a single shared `GHOST_EDGE` wireframe pass.

## Notes
- The operator registers under `bl_options = {"REGISTER"}` only (no UNDO); it does not modify scene data.
- Draw handlers receive a plain `state` dict rather than the operator instance, so they survive operator destruction (addon reload, abnormal exit) without raising `ReferenceError: StructRNA ... has been removed`. The module keeps a registry `_LIVE_INSTALLS` and exposes `cleanup_live_installs()` for the addon's `unregister()` to forcibly tear handlers down.
- A 60 Hz `event_timer_add` keeps the modal alive while the cursor is idle so `HelpOverlay` animations don't stall.
- The companion `iops.stop_theme_preview` operator polls `IOPS_OT_DrawThemePreview.is_running` (false when nothing is active) and sets `_stop_requested` plus tags all VIEW_3D areas for redraw so the modal wakes and exits.
- Both operators are listed in `classes = (IOPS_OT_DrawThemePreview, IOPS_OT_StopThemePreview)`.

## Related
- Theme system internals live under `ui/draw/` and `ui/hud/`; this operator is the user-facing verifier for those layers.
