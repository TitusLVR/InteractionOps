# Persistent GPU Widget System + Edge Data Widget

**Date:** 2026-06-11
**Status:** Design approved — implementation via workflow

## Problem

iOps interaction with edge data (bevel weight, crease, sharp, seam, freestyle)
currently lives in a PME pie + two dialog panels of fixed ±step buttons
(`edge_data.json` export). There is no persistent on-screen control surface:
no live values, no sliders, every adjustment is a menu round-trip.

The addon already has a unified GPU drawing layer (`ui/draw`: theme roles,
primitives, draw_scope) and a HUD layer (`ui/hud`: text, items, layout) — but
the HUD is display-only by design. This project adds the deferred piece:
**clickable, persistent GPU widgets**.

## Goals

1. A reusable widget framework: persistent GPU-drawn panels with interactive
   controls (sliders, buttons, flip-box toggles) in the 3D viewport.
2. All visuals via the existing theme system (`ui/draw/theme.py` roles).
   **No new color preferences.**
3. First concrete widget: **Edge Data** (bevel weight, crease, sharp, seam,
   freestyle mark, clear).
4. Space-type parameterized so IMAGE_EDITOR (UV) widgets can be added later.

## Non-Goals

- UV/IMAGE_EDITOR widget now (framework keeps space param; not registered).
- JSON/data-driven widget definitions (widgets are declarative Python).
- General constraint-solver layout (simple vertical row stack only).
- Animated transitions.

## Decisions (user-approved)

| Topic | Decision |
|---|---|
| Lifecycle | Hotkey/pie toggle. Appears at cursor. Draggable by title bar. Closes ONLY on explicit toggle/✕. Visibility + position persist in addon prefs across restarts. |
| Multi-view | Panel draws only in the area where summoned. If that area disappears (layout change, file load), re-anchor to largest 3D viewport. |
| Input architecture | Persistent `POST_PIXEL` draw handler + **transient modal**: keymap `LEFTMOUSE PRESS` entry whose poll passes only when cursor is inside panel bounds; modal lives for one click/drag gesture. No long-running modal. |
| Data binding | Hybrid two-way: sliders + flip boxes read selection state and write live; action buttons fire operators. |
| Mixed selection | Display `<mixed>` (slider: half-tone fill, no thumb; flip box: diagonal half-fill). Any set writes uniformly to ALL selected edges. |
| Slider snapping | Default drag snaps to 0.125 increments; **Ctrl held = smooth** free values. |
| Presets | Bevel: 0, 0.25, 0.5, 1.0. Crease: 0, 0.5, 0.9, 1.0. Absolute writes. |
| Flags | Sharp, Seam, Freestyle as **flip boxes** (checkbox + label). |
| Out of context | Panel stays but collapses to title bar + single centered message "Go back to Edit Mode" (no controls drawn); only drag/✕ active. |
| Undo | One undo push per completed gesture (slider release, flip click, preset click). Live writes during drag do not spam undo. ESC/RMB during slider drag restores pre-drag values. |

## Architecture

```
ui/widgets/
  __init__.py     # Widget registry, public API, register()/unregister()
  panel.py        # WidgetPanel: vertical row layout, bounds, edge clamping, drag
  controls.py     # Control base + Slider, PresetRow, FlipBox, ActionButton, Section, Row
  events.py       # IOPS_OT_widget_interact (transient modal), IOPS_OT_widget_toggle,
                  # keymap registration (single-register rule; unregister only own)
  render.py       # draw a WidgetPanel via ui/draw primitives + ui/hud/text
  state.py        # visibility/position/area-anchor persistence, load_post handler
widgets/
  __init__.py
  edge_data.py    # EdgeDataWidget + bmesh value adapters
```

### Three runtime pieces

1. **Persistent draw handler** — registered on `SpaceView3D`, `POST_PIXEL`,
   while any widget is visible. Draws via `ui/draw` primitives and
   `ui/hud/text` only. Callback wrapped: an exception skips the frame, never
   breaks the viewport. Handle stored module-level for clean unregister.
   Draw only when `context.area` matches the anchored area.

2. **Transient interaction modal** (`iops.widget_interact`) — keymap entry on
   `LEFTMOUSE PRESS` in the 3D View keymap. `poll()` = a visible widget exists
   in this area AND mouse is inside its bounds. Modal consumes events
   (`RUNNING_MODAL`) until release; resolves hit control from rects stored at
   draw time. Idle cost zero; clicks outside the panel never reach the
   operator (poll fails).

3. **Toggle operator** (`iops.widget_toggle`, `name` prop) — bindable in the
   iOps hotkey system / PME. On: anchor to current area, place panel at
   cursor (edge-clamped). Off: hide, persist position.

### Widget API (declarative Python)

```python
class EdgeDataWidget(Widget):
    name = "edge_data"
    title = "Edge Data"
    space = 'VIEW_3D'

    def build(self):
        return [
            Section("Bevel Weight"),
            Slider(get=get_bevel, set=set_bevel, snap=0.125),
            PresetRow([0, 0.25, 0.5, 1.0], set=set_bevel),
            Section("Crease"),
            Slider(get=get_crease, set=set_crease, snap=0.125),
            PresetRow([0, 0.5, 0.9, 1.0], set=set_crease),
            Section("Flags"),
            Row([FlipBox("Sharp", get=..., set=...),
                 FlipBox("Seam", get=..., set=...),
                 FlipBox("Freestyle", get=..., set=...)]),
            ActionButton("Clear", op="iops.executor",
                         kwargs={"script": "B:\\scripts\\iops_exec\\CLEAN_Edge_Data_Clear.py"},
                         role="error"),
        ]

    def poll(self, context):
        return context.mode == 'EDIT_MESH'
```

- Getters return `(value, is_mixed)`; setters write to all selected edges.
- Value adapters (bmesh code) live with the widget, not the framework.
- Layout: vertical stack of fixed-height rows; panel width derived from theme
  text sizes. `Row` splits width equally among children.

### Value adapters (Blender 5.1)

- Bevel weight / crease are float attributes (`bevel_weight_edge`,
  `crease_edge`) — access via bmesh edge float layers; **verify exact layer
  API against bundled `data/api` RST docs at implementation time**.
- Sharp = `not edge.smooth`; Seam = `edge.seam`; Freestyle = freestyle edge
  layer (verify 5.1 API).
- Never cache bmesh/edge references between events — re-acquire
  `bmesh.from_edit_mesh()` per interaction. Cached display values are plain
  floats/bools only.

### Two-way refresh

- Cached `(value, is_mixed)` per control, recomputed only when dirty.
- Dirty triggers: `depsgraph_update_post`, own writes, `undo_post`/`redo_post`,
  mode change. Recompute = single pass over selected edges.

### Theme mapping (existing roles only)

| Element | Role |
|---|---|
| Panel fill / outline | `fill` / `outline` |
| Slider fill, flip box ON, value text | `primary` |
| Labels, idle buttons | `secondary` |
| Disabled (no selection / out of context) | `secondary` @ 0.35 alpha |
| Clear button | `error` |
| Section labels, "Go back to Edit Mode" | `hint` |

All text through `ui/hud/text.py` (handles SHADOW reset — avoids the font-0
leak that caused outliner flicker previously).

## Error handling

- **No selection:** value controls disabled; presets/Clear inert; drag/✕ work.
- **Out of context:** collapsed panel (title + message only).
- **Anchor area gone:** re-anchor to largest VIEW_3D region.
- **Exception in draw:** skip frame, log once.
- **Keymap:** single registration at addon register; unregister removes only
  our own entries (per `project_hotkey_system` rules).

## Testing

- `tests/ui/widgets/` pytest (bpy-free): row layout math, bounds, edge
  clamping, hit-testing, slider pixel↔value mapping incl. snap/Ctrl,
  mixed-state aggregation on synthetic data.
- Headless Blender (`V:\SteamLibrary\steamapps\common\Blender\blender.exe
  --background --python ...`): addon registers cleanly; value adapters tested
  on a built mesh (select edges, get/set, assert attributes, mixed detection,
  write-to-all).
- Manual checklist: toggle, drag, anchor fallback, undo granularity, Ctrl
  smooth drag, out-of-context placeholder, theme colors.

## Risks

- **LEFTMOUSE keymap entry** is global to 3D View; the poll gate must be
  cheap and exact or it eats clicks. Mitigation: poll checks a module-level
  "visible + bounds" fast path only.
- **depsgraph_update_post** may over- or under-fire for edit-mode selection
  changes; fallback is recompute-on-gesture plus the handler. Verify
  empirically in 5.1.
- **Persistent draw handler across file load** — re-registered via
  `load_post`; anchor area pointer invalid after load → largest-viewport
  fallback covers it.
