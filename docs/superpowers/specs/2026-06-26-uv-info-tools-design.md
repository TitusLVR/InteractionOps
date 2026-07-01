# UV Info Tools — Design

Date: 2026-06-26

## Overview

Start a family of UV-context information tools for the Image Editor, plus a
sidebar panel that gathers the addon's UV-context operators in one place.

First tool: **UV Info Rect** — a modal operator that lets the user rubber-band
a rectangle in the UV editor and reports its UV bounds (min, max, size),
copying them to the clipboard.

## Files

- `operators/uv_info.py` — container module for UV-info operators. Initial
  contents: `IOPS_OT_UVInfoRect`. Future UV-info tools go here as additional
  `IOPS_OT_UVInfo*` classes.
- `ui/iops_uv_panel.py` — new sidebar panel `IOPS_PT_UV_Panel` (Image Editor,
  `iOps` tab) listing the addon's UV-context operators as buttons.
- `__init__.py` — import and register both new classes alongside the existing
  operator/panel registration (mirror `IOPS_OT_DragSnapUV`).

## Operator: `IOPS_OT_UVInfoRect`

- `bl_idname`: `iops.uv_info_rect`
- `bl_label`: `IOPS UV Info Rect`
- `bl_options`: `{"REGISTER"}` (no mesh mutation, so no UNDO needed)
- `is_bindable = True` (consistent with other modal operators)

### poll

- `context.area is not None and context.area.type == "IMAGE_EDITOR"`.
- No edit-mode / mesh requirement: the tool inspects UV-space coordinates, not
  geometry.

### invoke

- Attach draw handlers to `bpy.types.SpaceImageEditor` via `safe_handler_add`
  (`WINDOW`, `POST_PIXEL`, `tick=True`): rectangle outline, corner points, HUD.
- Build HUD + Help overlays (`HUDOverlay` / `HelpOverlay`), bound to region.
- `capture_event` to seed `_last_event`; `modal_handler_add`.
- Initial state: no rectangle drawn yet (`start = end = None`, `dragging = False`).

### Drawing interaction

- LMB press: store start corner in region pixel coords, set `dragging = True`,
  clear any previous rectangle.
- `MOUSEMOVE` while dragging: update end corner.
- LMB release: `dragging = False`, rectangle stays on screen, copy bounds to
  clipboard + `report` INFO.
- A new LMB press **replaces** the existing rectangle (does not move corners of
  the old one).

### Bounds computation

- Convert both corners region→UV via `region.view2d.region_to_view`.
- `uv_min = (min(u0,u1), min(v0,v1))`, `uv_max = (max(u0,u1), max(v0,v1))` —
  independent of drag direction.
- `size = uv_max - uv_min`.

### Clipboard format (on release)

```
min: (u, v) max: (u, v) size: (w, h)
```

All values rounded to 6 decimals. Written to
`context.window_manager.clipboard`, plus a `report({"INFO"}, ...)`.

### Drawing

- Outline: `draw.polyline` closed loop (5 region-space points), role
  `PREVIEW_LINE`, inside `draw_scope(blend="ALPHA")`.
- Corner markers at uv_min / uv_max: `draw.points` (convert UV→region with
  `view2d.view_to_region`), role `ACTIVE_POINT`.
- HUD section shows **min, max, size** live during drag (all three regardless of
  what is copied).

### HUD / Help

- Follow `drag_snap_uv.py`: `_build_hud`, `_draw_hud`, drag/toggle event handling
  via `theme_prefs`, `handle_*` helpers.
- Help section keys: LMB Draw rectangle, Esc/RMB Cancel, H Help/Toggle HUD.

### Exit

- `RIGHTMOUSE` / `ESC` → remove handlers, `CANCELLED`.
- Middle mouse / wheel → `PASS_THROUGH` (allow pan/zoom).

## Panel: `IOPS_PT_UV_Panel`

- `bl_label`: `IOPS UV Tools`
- `bl_idname`: `IOPS_PT_UV_Panel`
- `bl_space_type = "IMAGE_EDITOR"`, `bl_region_type = "UI"`, `bl_category = "iOps"`
- `bl_options = {"DEFAULT_CLOSED"}`
- `draw`: a column of operator buttons.
  - "UV Info Rect" → `iops.uv_info_rect`
  - "Drag Snap UV" → `iops.uv_drag_snap_uv`
- Buttons are always shown; operators with stricter requirements (e.g.
  drag_snap_uv needs edit-mode + selected mesh) rely on their own `poll` to
  guard execution. No per-button enable/hide logic.

## Out of scope

- Persisting bounds into scene properties.
- Additional UV-info tools beyond the rectangle (added later into the same
  module and panel).
- Constrain-axis / numeric-entry behaviors.
