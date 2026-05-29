# Straight Bevel

Interactive modal bevel that places perpendicular cuts across the faces adjacent to each selected edge. At every ridge corner the cut is slid along the neighbouring (non-selected) edge so that the new edge sits at a fixed perpendicular distance from the original ridge, matching `mesh.bevel(OFFSET, loop_slide=False)` semantics. Two alternative modes (rounded percent bevel and flat in-face fan) are exposed from the same modal session.

<div class="iops-meta" markdown="1">
<span class="key">bl_idname: iops.mesh_straight_bevel</span>
<span class="mode">Mode: Edit Mesh</span>
<span>Context: VIEW_3D</span>
<span class="modal">Modal: yes</span>
<span class="hud">HUD: yes</span>
</div>

## Overview
The operator targets corner ridges where Blender's stock bevel either bows the new edge into the face or refuses to maintain a true perpendicular offset on asymmetric corners. It collects every (corner vertex, adjacent face, neighbouring edge) triple along the selected chain, propagates a base offset around connected open chains so a single user value stays consistent across the whole selection, and drops perpendicular cuts on confirm.

The same modal session can be redirected into a Percent (rounded `mesh.bevel` SUPERELLIPSE) preview or a Flat Fan that rebuilds the corner ngon as a triangle fan whose boundary samples lie in a picked alignment-face plane. Use Flat Fan when the bevel terminates into a cap face and you need the boundary to remain coplanar with that cap.

## Usage
- Edit Mode on a mesh with at least one selected edge that has at least one adjacent face.
- No default keymap binding — invoke via search (F3) or wire to a custom shortcut / pie.
- Drag the mouse horizontally to scrub offset, or type a numeric value. Press `B` for rounded percent preview, `F` for flat fan. In flat fan mode, `Q` raycasts under the cursor to pick the alignment face for the nearest open-chain endpoint, `W` toggles boundary placement strategy. Confirm with LMB / Enter / Space; cancel with Esc / RMB.

## Modal Controls

| Key | Action |
| --- | --- |
| <kbd>MouseMove</kbd> | Scrub offset horizontally |
| <kbd>Shift</kbd> + drag | Precise mode (0.1x sensitivity) |
| <kbd>Ctrl</kbd> + drag | Snap offset to 0.1 increments |
| <kbd>0</kbd>–<kbd>9</kbd> / Numpad | Type numeric offset |
| <kbd>.</kbd> / Numpad <kbd>.</kbd> | Decimal point in typed offset |
| <kbd>Backspace</kbd> | Delete last typed character |
| <kbd>B</kbd> | Toggle Percent bevel preview (mutually exclusive with Flat Fan) |
| <kbd>F</kbd> | Toggle Flat Fan preview (mutually exclusive with Percent) |
| <kbd>Q</kbd> | Flat Fan: raycast under cursor to bind alignment face to nearest endpoint |
| <kbd>W</kbd> | Flat Fan: toggle align mode (project / recompute) |
| <kbd>C</kbd> | Toggle post-bevel cleanup (limited dissolve on alignment-face planes) |
| <kbd>S</kbd> | Toggle snap cut endpoint to chain-endpoint vert |
| <kbd>WheelUp</kbd> / <kbd>WheelDown</kbd> | Adjust segments when Percent or Flat Fan is active (clamped 1..16); otherwise passes through to viewport |
| <kbd>MMB</kbd> / NDOF | Pass through to viewport navigation |
| <kbd>H</kbd> | Toggle help / HUD (handled by HUD overlay) |
| <kbd>LMB</kbd> / <kbd>Enter</kbd> / <kbd>Numpad Enter</kbd> / <kbd>Space</kbd> | Confirm |
| <kbd>Esc</kbd> / <kbd>RMB</kbd> | Cancel and restore initial offset |

## HUD
A dynamic HUD overlay (`straight_bevel`) shows current state for every toggle, with a paired help overlay listing all bindings. Live parameters:

- `Pct bevel (B)` — bool, on when Percent mode is armed.
- `Flat fan (F)` — bool, on when Flat Fan mode is armed.
- `Pct segs` — int, active only while Percent is on.
- `Fan segs` — int, active only while Flat Fan is on.
- `Align mode (W)` — `project` or `recompute`, active only while Flat Fan is on.
- `Cleanup (C)` — bool.
- `Snap to endpoint (S)` — bool.

Viewport previews use the `PREVIEW_LINE` and `PREVIEW_POINT` theme roles. The straight cut preview is always drawn; Percent overlays a circular arc through the two cut points at each ridge corner; Flat Fan adds radial spokes from the corner vertex to every arc sample and, if an alignment face is bound at an endpoint, projects/resamples the arc into that face's plane.

## Properties

| Name | Type | Default | Description |
| --- | --- | --- | --- |
| `offset` | Float (DISTANCE) | 0.05 | Perpendicular distance from the ridge to the new cut. min 0.0, soft max 10.0, precision 4. |
| `mode` | Enum | `STRAIGHT` | Bevel variant: `STRAIGHT` (perpendicular cuts), `PCT` (rounded `mesh.bevel` SUPERELLIPSE), `FAN` (flat in-face triangle fan). |
| `pct_segments` | Int | 16 | Segments for Percent mode. Range 1..16. |
| `fan_segments` | Int | 4 | Segments for Flat Fan mode. Range 1..16. |
| `fan_align_mode` | Enum | `project` | Fan boundary placement: `project` (project bevel boundary verts onto picked face plane) or `recompute` (resample arc evenly in that plane). |
| `cleanup_mode` | Bool | False | Run a limited dissolve on geometry coplanar with the alignment faces after the bevel. |
| `snap_to_endpoint` | Bool | False | Split the boundary edge at the projection point and weld the cut endpoint into the new vertex, instead of only moving it geometrically. |

## Notes
- Offset is hard-capped at modal start to the largest perpendicular value that still keeps every cut within 99% of its neighbour-edge length (accounting for per-vertex propagation correction); the cap is computed across every `(vert, neighbour edge)` pair, not just the deduped preview jobs, so multi-rail corners do not bypass it.
- Open-chain interior vertices that sit at the centre of two collinear selected edges are detected and suppressed so the chain is treated as a single ridge. Each connected component propagates a per-vertex base correction along the chain so a single user offset produces consistent perpendicular spacing on bent chains.
- Manual `Q`-picked alignment faces are not persisted to the redo panel; redo falls back to the auto-best candidate (the face whose normal is most parallel to the longest non-ridge edge at the endpoint, falling back to the ridge direction).
- Wheel events are intercepted only while Percent or Flat Fan is active; otherwise they pass through so viewport zoom keeps working.
- On cancel the original `offset` value is restored. Cancel and confirm both purge the cached bmesh / BMElement-keyed dicts so a later addon reload cannot resurrect freed mesh data through the redo stack.
- Single registered class: `IOPS_OT_straight_bevel`. No companion Panel, Menu or PropertyGroup.

## Related
- [Quick Connect](op_mesh_quick_connect.md)
- [Cursor Bisect](op_mesh_cursor_bisect.md)
- [Tris to Quads](op_mesh_to_tris_to_quad.md)
