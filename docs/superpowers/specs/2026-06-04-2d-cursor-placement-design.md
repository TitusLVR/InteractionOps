# 2D Cursor Visual Placement (UV editor) — Design

> UV-editor equivalent of the 3D "Visual Origin" tool. A bounding-box visual
> picker that places the **2D cursor** (`space.cursor_location`, which doubles
> as the UV transform pivot) in the Image/UV editor.

## Goal

Mirror `IOPS_OT_VisualOrigin` (3D) in the UV editor: draw a bounding-box cage
with snap points, highlight the point nearest the mouse, and on confirm set the
2D cursor to that point. Reuse the existing IMAGE_EDITOR draw/HUD plumbing from
`IOPS_OT_DragSnapUV`.

## Reference implementations

- `operators/object_visual_origin.py` — `IOPS_OT_VisualOrigin`: cage build,
  per-tick reprojection + nearest-point pick (`calc_distance`), draw handler
  lifecycle, HUD/Help overlay, modal structure.
- `operators/drag_snap_uv.py` — `IOPS_OT_DragSnapUV`: IMAGE_EDITOR poll, UV↔screen
  via `view2d.region_to_view` / `view_to_region`, 2D cursor access
  (`area.spaces.active.cursor_location`), draw handlers on
  `bpy.types.SpaceImageEditor` (POST_PIXEL), and the HUD/Help drag+toggle
  handling block.
- `ui/draw/primitives.py` (`line`, `points`), `ui/draw/theme.py` (`Role`),
  `ui/hud` (HUDOverlay/HelpOverlay/HUDSection/HUDItem/ItemState, capture_event).

## Operator

- Class `IOPS_OT_VisualCursorUV`, idname `iops.uv_visual_cursor`.
- `bl_options = {"REGISTER", "UNDO"}`.
- New file `operators/uv_visual_cursor.py`.
- **Poll** (mirror `drag_snap_uv`): `area.type == "IMAGE_EDITOR"`, active object
  is MESH in EDIT mode.

## Modes

Mode is read each modal tick from `event.alt`.

### Selection mode (default, Alt not held)
- BBox of currently-selected UV verts on the **active** mesh only.
- Selection bbox (`sel_min`, `sel_max`) computed once at `invoke` — selection
  cannot change during the modal.
- 9 snap points: 4 corners + 4 edge midpoints + center.

### Tile mode (hold Alt, or auto when selection empty)
- Ignore selection. Take mouse UV (`region_to_view`), compute the unit UDIM tile
  containing it: `tile_min = (floor(u), floor(v))`, `tile_max = tile_min + (1,1)`.
- Build the same 9-point cage for that tile.
- Recomputed on every `MOUSEMOVE` so the cage follows the mouse across tiles.
- Releasing Alt returns to selection mode.
- **Auto-start:** if there are no selected UVs at invoke, the tool behaves as if
  Alt were held (tile mode) until/unless a selection bbox is available. With an
  empty selection, selection mode draws no cage; tile mode is always usable.

## Snap-point construction

Given `mn`/`mx` (Vector, UV space):

```
corners = (mn.x,mn.y), (mx.x,mn.y), (mx.x,mx.y), (mn.x,mx.y)
edge midpoints = midpoints of the 4 corner pairs
center = ((mn.x+mx.x)/2, (mn.y+mx.y)/2)
```

Stored as a list of 9 `Vector` in UV space (`pos_batch_uv`). Recomputed each tick
(selection mode: constant; tile mode: depends on mouse).

## Picking

Each tick: project the 9 UV points to region coords with
`view2d.view_to_region(u, v, clip=False)`, then pick the min screen-distance to
the mouse region position → `nearest` (index + UV target). Same screen-space
approach as `visual_origin.calc_distance` — what the user sees, and self-correct
under pan/zoom.

## Draw handlers

Attach to `bpy.types.SpaceImageEditor`, `WINDOW`, `POST_PIXEL`, `tick=True` (same
as `drag_snap_uv`). All coords converted UV→region via `view_to_region` and
passed as `Vector((x, y, 0))` inside `draw_scope(blend="ALPHA")`. UI follows the
general addon convention — cage/point colors come from the theme `Role` enum,
tooltips/help from the shared HUD system.

- **Cage rectangle** — 4 edges between the 4 corners → `Role.BBOX` (fall back to
  `Role.LINE` if BBOX unsuitable).
- **Cage points** — 9 points → `Role.POINT`.
- **Nearest point** — the highlighted snap point → `Role.CLOSEST_POINT`.
- **HUD + Help overlay** — `HUDOverlay`/`HelpOverlay` built as in `drag_snap_uv`,
  listing the modal keys below.

## Modal keys

- `MOUSEMOVE` — update mouse pos, recompute cage (tile mode follows), repick nearest.
- `MIDDLEMOUSE`/`WHEELUPMOUSE`/`WHEELDOWNMOUSE` — `PASS_THROUGH` (pan/zoom).
- `LEFTMOUSE`/`SPACE` (PRESS) — **confirm**: set
  `area.spaces.active.cursor_location = Vector((nearest.x, nearest.y))`, remove
  draw handlers, return `FINISHED`.
- `RIGHTMOUSE`/`ESC` — cancel: remove handlers, return `CANCELLED`.
- `H` — help toggle; `/` (SLASH) — HUD params toggle. Handled by the standard
  HUD/Help drag+toggle block copied from `drag_snap_uv.modal` (reads
  `preferences.addons["InteractionOps"].preferences.iops_theme`).

Confirm action is **cursor only** — no move-selection-to-cursor modes.

## Registration

- `__init__.py`: `from .operators.uv_visual_cursor import IOPS_OT_VisualCursorUV`
  and add to the `classes` tuple beside `IOPS_OT_DragSnapUV`.
- `prefs/hotkeys_default.py`: add
  `("iops.uv_visual_cursor", "F19", "PRESS", True, True, True, False)` — the
  `iops.uv` prefix routes it into the "UV Editor" keymap automatically
  (`utils/functions.py::register_keymaps`). `Ctrl+Alt+Shift+F19` is the repo's
  placeholder chord; the user rebinds in addon preferences. Note: Alt is consumed
  by tile-mode inside the modal, so a real rebind should avoid relying on Alt.

## Edge cases

- **No UVs selected** → auto tile mode (see above). Selection mode with empty
  selection draws nothing and is harmless.
- **2D cursor beyond 0..1** — allowed; no clamping.
- **Selection spanning multiple tiles** — selection-mode bbox spans them; fine.

## Testing / verification

Interactive modal + GPU draw. The repo has no unit tests for `visual_origin` or
`drag_snap_uv`; this tool follows the same convention (no automated test).
Verify manually in the live Blender via MCP:

1. Select some UVs, invoke in the UV editor → 9-point cage on the selection bbox;
   moving the mouse highlights the nearest point; LMB/Space snaps the 2D cursor
   to it.
2. Hold Alt → cage switches to the hovered unit tile and follows the mouse across
   tiles; confirm snaps to a tile point.
3. With nothing selected, invoke → starts in tile mode directly.
4. RMB/Esc cancels without moving the cursor; H and `/` toggle help/params.

## Out of scope (YAGNI)

- Move-selected-UVs-to-cursor modes (kept in `drag_snap_uv`).
- Multi-object UV edit (active mesh only).
- Subdivision snap-point layer (9 points only).
- Chaining from another UV cursor op (standalone).
