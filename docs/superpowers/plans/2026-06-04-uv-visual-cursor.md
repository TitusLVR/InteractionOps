# 2D Cursor Visual Placement (UV editor) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `IOPS_OT_VisualCursorUV` — a UV-editor modal that draws a 9-point bounding-box cage and snaps the 2D cursor to the picked point, mirroring the 3D Visual Origin tool.

**Architecture:** One new operator file. Pure helpers compute the 9 snap points from a UV-space bbox (selection bbox or the unit UDIM tile under the mouse). The modal re-projects points to region space each tick to pick the nearest to the mouse, draws the cage via the addon's theme `Role` primitives + HUD/Help system (copied from `drag_snap_uv`), and on confirm writes `space.cursor_location`.

**Tech Stack:** Blender Python (`bpy`, `bmesh`, `mathutils`), addon's `ui/draw` primitives + `ui/hud`. Verification is manual via the Blender MCP connection — the repo has no automated tests for GPU/modal operators (same as `visual_origin` / `drag_snap_uv`).

> **Note on testing:** Per the design spec, this tool follows repo convention: no pytest/unit-test scaffolding (mathutils/bpy only exist inside Blender). "Verify" steps run code in the live Blender instance via the MCP `execute_blender_code` tool, or check behavior interactively. Keep Blender running with the InteractionOps addon loadable from `d:\git\InteractionOps`.

**Reference files (read before starting):**
- `operators/object_visual_origin.py` — cage/pick/modal/handler pattern being mirrored.
- `operators/drag_snap_uv.py` — IMAGE_EDITOR poll, UV↔region conversion, draw-handler lifecycle on `SpaceImageEditor`, and the HUD/Help drag+toggle block (copied verbatim below).
- `utils/picking.py::build_uv_kdtree` — the Blender-5.0+ UV-selection read idiom reused in `_selection_bbox`.
- `ui/draw/primitives.py` (`line`, `polyline`, `points`), `ui/draw/theme.py` (`Role`).

---

### Task 1: Operator file — pure geometry helpers

**Files:**
- Create: `operators/uv_visual_cursor.py`

- [ ] **Step 1: Create the file with imports and the three pure helpers**

```python
import bpy
import bmesh
import math
from mathutils import Vector

from ..ui.draw import primitives as draw, draw_scope, Role
from ..ui.draw import safe_handler_add, safe_handler_remove
from ..ui.hud import (HUDOverlay, HelpOverlay, HUDSection, HUDItem,
                      ItemState, capture_event)


# Cage corner indices into the 9-point list (corners are points 0..3).
_CAGE_LOOP = (0, 1, 2, 3, 0)


def _bbox_snap_points(mn, mx):
    """9 UV-space snap points from a bbox (mn, mx are 2D Vectors).

    Order: 4 corners (0..3), 4 edge midpoints (4..7), center (8).
    """
    cx = (mn.x + mx.x) * 0.5
    cy = (mn.y + mx.y) * 0.5
    return [
        Vector((mn.x, mn.y)),   # 0 corner BL
        Vector((mx.x, mn.y)),   # 1 corner BR
        Vector((mx.x, mx.y)),   # 2 corner TR
        Vector((mn.x, mx.y)),   # 3 corner TL
        Vector((cx, mn.y)),     # 4 edge mid bottom
        Vector((mx.x, cy)),     # 5 edge mid right
        Vector((cx, mx.y)),     # 6 edge mid top
        Vector((mn.x, cy)),     # 7 edge mid left
        Vector((cx, cy)),       # 8 center
    ]


def _tile_bbox(uv):
    """(mn, mx) of the unit UDIM tile containing UV position `uv`."""
    mnx = math.floor(uv.x)
    mny = math.floor(uv.y)
    return Vector((mnx, mny)), Vector((mnx + 1.0, mny + 1.0))


def _selection_bbox(context):
    """Min/max of selected UV verts on the active mesh, or None if none.

    Reads selection via the Blender-5.0+ `loop.uv_select_vert` with a
    fallback to `loop[uv_layer].select` — same idiom as
    `utils.picking.build_uv_kdtree`.
    """
    obj = context.active_object
    bm = bmesh.from_edit_mesh(obj.data)
    uv_layer = bm.loops.layers.uv.verify()
    mn = None
    mx = None
    for face in bm.faces:
        for loop in face.loops:
            sel = getattr(loop, "uv_select_vert", None)
            if sel is None:
                sel = loop[uv_layer].select
            if not sel:
                continue
            uv = loop[uv_layer].uv
            if mn is None:
                mn = Vector((uv.x, uv.y))
                mx = Vector((uv.x, uv.y))
            else:
                if uv.x < mn.x: mn.x = uv.x
                if uv.y < mn.y: mn.y = uv.y
                if uv.x > mx.x: mx.x = uv.x
                if uv.y > mx.y: mx.y = uv.y
    if mn is None:
        return None
    return mn, mx
```

- [ ] **Step 2: Verify the helpers in the live Blender instance**

Use the Blender MCP `execute_blender_code` tool with this body (pure math — no scene needed):

```python
import math
from mathutils import Vector

def _bbox_snap_points(mn, mx):
    cx = (mn.x + mx.x) * 0.5
    cy = (mn.y + mx.y) * 0.5
    return [
        Vector((mn.x, mn.y)), Vector((mx.x, mn.y)),
        Vector((mx.x, mx.y)), Vector((mn.x, mx.y)),
        Vector((cx, mn.y)), Vector((mx.x, cy)),
        Vector((cx, mx.y)), Vector((mn.x, cy)),
        Vector((cx, cy)),
    ]

def _tile_bbox(uv):
    mnx = math.floor(uv.x); mny = math.floor(uv.y)
    return Vector((mnx, mny)), Vector((mnx + 1.0, mny + 1.0))

pts = _bbox_snap_points(Vector((0.0, 0.0)), Vector((2.0, 1.0)))
assert len(pts) == 9
assert pts[8] == Vector((1.0, 0.5)), pts[8]      # center
assert pts[2] == Vector((2.0, 1.0)), pts[2]      # TR corner
assert pts[4] == Vector((1.0, 0.0)), pts[4]      # bottom edge mid
mn, mx = _tile_bbox(Vector((2.3, 0.7)))
assert (mn, mx) == (Vector((2.0, 0.0)), Vector((3.0, 1.0))), (mn, mx)
mn, mx = _tile_bbox(Vector((-0.2, 1.9)))
assert (mn, mx) == (Vector((-1.0, 1.0)), Vector((0.0, 2.0))), (mn, mx)
print("helpers OK")
```
Expected output: `helpers OK` (no AssertionError).

- [ ] **Step 3: Commit**

```bash
git add operators/uv_visual_cursor.py
git commit -m "feat(uv-cursor): bbox/tile snap-point helpers"
```

---

### Task 2: The operator class (modal, picking, draw, HUD)

**Files:**
- Modify: `operators/uv_visual_cursor.py` (append the class after the helpers)

- [ ] **Step 1: Append the full operator class**

```python
class IOPS_OT_VisualCursorUV(bpy.types.Operator):
    """Visual 2D-cursor placement: pick a bbox/tile snap point in the UV editor"""

    bl_idname = "iops.uv_visual_cursor"
    bl_label = "IOPS Visual Cursor UV"
    bl_options = {"REGISTER", "UNDO"}

    sd_handlers = []

    @classmethod
    def poll(cls, context):
        return (
            context.area is not None
            and context.area.type == "IMAGE_EDITOR"
            and context.active_object is not None
            and context.active_object.type == "MESH"
            and context.active_object.mode == "EDIT"
        )

    # --- HUD -----------------------------------------------------------
    def _build_hud(self, context):
        hud = HUDOverlay("uv_visual_cursor")
        hud.title = "Visual Cursor UV"
        hud.bind_region(context.region)
        helpo = HelpOverlay("uv_visual_cursor")
        helpo.add_section(HUDSection("Visual Cursor UV", [
            HUDItem("Set 2D cursor to highlighted", "LMB/Space", ItemState.ON, default_state=ItemState.OFF, always_show=True),
            HUDItem("Tile mode (hover tile)",       "Hold Alt",  ItemState.ON, default_state=ItemState.OFF, always_show=True),
            HUDItem("Cancel",                       "Esc/RMB",   ItemState.ON, default_state=ItemState.OFF, always_show=True),
            HUDItem("Help / Toggle HUD",            "H",         ItemState.ON, default_state=ItemState.OFF, always_show=True),
        ]))
        helpo.bind_region(context.region)
        return hud, helpo

    def _draw_hud(self, context):
        helpo = getattr(self, "help", None)
        if helpo is not None:
            helpo.draw(context, getattr(self, "_last_event", None))
        if getattr(self, "hud", None) is None:
            return
        self.hud.draw(context, getattr(self, "_last_event", None))

    # --- Geometry / picking -------------------------------------------
    def _update(self, context, event):
        """Recompute the cage (selection or tile bbox) and the nearest point."""
        v2d = context.region.view2d
        mx_px, my_px = self.mouse_pos
        u, v = v2d.region_to_view(mx_px, my_px)
        mouse_uv = Vector((u, v))

        tile = bool(event.alt) or (self.sel_min is None)
        self.tile_mode = tile
        if tile:
            mn, mx = _tile_bbox(mouse_uv)
        else:
            mn, mx = self.sel_min, self.sel_max
        self.pos_batch_uv = _bbox_snap_points(mn, mx)
        self._pick_nearest(context)

    def _pick_nearest(self, context):
        if not self.pos_batch_uv:
            self.nearest = None
            return
        v2d = context.region.view2d
        mv = Vector(self.mouse_pos)
        best_i = 0
        best_d = float("inf")
        for i, p in enumerate(self.pos_batch_uv):
            rx, ry = v2d.view_to_region(p.x, p.y, clip=False)
            d = (Vector((rx, ry)) - mv).length_squared
            if d < best_d:
                best_d = d
                best_i = i
        self.nearest_idx = best_i
        self.nearest = self.pos_batch_uv[best_i]

    # --- Draw handlers (region coords, POST_PIXEL) --------------------
    def _region_pt(self, context, uv):
        rx, ry = context.region.view2d.view_to_region(uv.x, uv.y, clip=False)
        return Vector((rx, ry, 0.0))

    def _draw_cage_lines(self, context):
        if not self.pos_batch_uv:
            return
        corners = [self._region_pt(context, self.pos_batch_uv[i]) for i in _CAGE_LOOP]
        with draw_scope(blend="ALPHA"):
            draw.polyline(corners, role=Role.BBOX, context=context)

    def _draw_cage_points(self, context):
        if not self.pos_batch_uv:
            return
        coords = [self._region_pt(context, p) for p in self.pos_batch_uv]
        with draw_scope(blend="ALPHA"):
            draw.points(coords, role=Role.POINT, context=context)

    def _draw_active_point(self, context):
        if self.nearest is None:
            return
        with draw_scope(blend="ALPHA"):
            draw.points([self._region_pt(context, self.nearest)],
                        role=Role.CLOSEST_POINT, context=context)

    # --- Lifecycle -----------------------------------------------------
    def clear_draw_handlers(self):
        for handler in self.sd_handlers:
            safe_handler_remove(handler, bpy.types.SpaceImageEditor, "WINDOW")

    def _set_cursor(self, context):
        space = context.space_data
        if space is None or space.type != "IMAGE_EDITOR":
            space = context.area.spaces.active
        space.cursor_location = (self.nearest.x, self.nearest.y)

    def modal(self, context, event):
        context.area.tag_redraw()
        self._last_event = capture_event(event, getattr(self, "_last_event", None))

        # Standard HUD/Help drag + toggle handling (copied from drag_snap_uv).
        try:
            theme_prefs = context.preferences.addons["InteractionOps"]\
                .preferences.iops_theme
        except (KeyError, AttributeError):
            theme_prefs = None
        if theme_prefs is not None:
            helpo = getattr(self, "help", None)
            hud = getattr(self, "hud", None)
            if helpo is not None and helpo.handle_drag_event(context, event, theme_prefs):
                return {'RUNNING_MODAL'}
            if hud is not None and hud.handle_drag_event(context, event, theme_prefs):
                return {'RUNNING_MODAL'}
            if helpo is not None and helpo.handle_toggle_event(event, theme_prefs):
                return {'RUNNING_MODAL'}
            if hud is not None and hud.handle_param_toggle_event(event, theme_prefs):
                return {'RUNNING_MODAL'}

        if event.type in {"MIDDLEMOUSE", "WHEELUPMOUSE", "WHEELDOWNMOUSE"}:
            return {"PASS_THROUGH"}

        self.mouse_pos = (event.mouse_region_x, event.mouse_region_y)
        self._update(context, event)

        if event.type in {"LEFTMOUSE", "SPACE"} and event.value == "PRESS":
            if self.nearest is not None:
                self._set_cursor(context)
            self.clear_draw_handlers()
            return {"FINISHED"}

        elif event.type in {"RIGHTMOUSE", "ESC"} and event.value == "PRESS":
            self.clear_draw_handlers()
            self.report({"INFO"}, "Visual Cursor UV - cancelled")
            return {"CANCELLED"}

        return {"RUNNING_MODAL"}

    def invoke(self, context, event):
        if context.space_data.type != "IMAGE_EDITOR":
            self.report({"WARNING"}, "Active space must be an Image Editor")
            return {"CANCELLED"}

        sb = _selection_bbox(context)
        if sb is None:
            self.sel_min = None
            self.sel_max = None
            self.report({"INFO"}, "No UV selection - tile mode")
        else:
            self.sel_min, self.sel_max = sb

        self.tile_mode = False
        self.pos_batch_uv = []
        self.nearest = None
        self.nearest_idx = 0
        self.mouse_pos = (event.mouse_region_x, event.mouse_region_y)
        self._update(context, event)

        self.hud, self.help = self._build_hud(context)
        self._last_event = capture_event(event, None)

        h_lines = safe_handler_add(bpy.types.SpaceImageEditor,
            self._draw_cage_lines, (context,), "WINDOW", "POST_PIXEL", tick=True)
        h_points = safe_handler_add(bpy.types.SpaceImageEditor,
            self._draw_cage_points, (context,), "WINDOW", "POST_PIXEL", tick=True)
        h_active = safe_handler_add(bpy.types.SpaceImageEditor,
            self._draw_active_point, (context,), "WINDOW", "POST_PIXEL", tick=True)
        h_hud = safe_handler_add(bpy.types.SpaceImageEditor,
            self._draw_hud, (context,), "WINDOW", "POST_PIXEL", tick=True)
        self.sd_handlers = [h_lines, h_points, h_active, h_hud]

        context.window_manager.modal_handler_add(self)
        return {"RUNNING_MODAL"}
```

- [ ] **Step 2: Verify the module imports cleanly inside Blender**

Use the Blender MCP `execute_blender_code` tool:

```python
import importlib, InteractionOps.operators.uv_visual_cursor as m
importlib.reload(m)
print(m.IOPS_OT_VisualCursorUV.bl_idname)
```
Expected output: `iops.uv_visual_cursor` (no ImportError / AttributeError). If the addon module name differs, use the actual package name shown by `__import__("addon_utils")` — the package folder is `InteractionOps`.

- [ ] **Step 3: Commit**

```bash
git add operators/uv_visual_cursor.py
git commit -m "feat(uv-cursor): visual 2D-cursor placement operator"
```

---

### Task 3: Register the operator and its keymap

**Files:**
- Modify: `__init__.py` (import near line 76; classes tuple near line 407)
- Modify: `prefs/hotkeys_default.py` (after the `iops.uv_drag_snap_uv` line, ~line 43)

- [ ] **Step 1: Add the import in `__init__.py`**

Find the line:
```python
from .operators.drag_snap_uv import IOPS_OT_DragSnapUV
```
Add immediately after it:
```python
from .operators.uv_visual_cursor import IOPS_OT_VisualCursorUV
```

- [ ] **Step 2: Add the class to the `classes` registration tuple in `__init__.py`**

Find the line (in the `classes` tuple):
```python
    IOPS_OT_DragSnapUV,
```
Add immediately after it:
```python
    IOPS_OT_VisualCursorUV,
```

- [ ] **Step 3: Add the default keymap entry in `prefs/hotkeys_default.py`**

Find the line:
```python
    ("iops.uv_drag_snap_uv", "G", "PRESS", True, True, True, False),
```
Add immediately after it:
```python
    ("iops.uv_visual_cursor", "F19", "PRESS", True, True, True, False),
```
(The `iops.uv` prefix routes it into the "UV Editor" keymap automatically via `utils/functions.py::register_keymaps`. `Ctrl+Alt+Shift+F19` is the repo's unreachable placeholder chord — the user rebinds in addon preferences.)

- [ ] **Step 4: Verify registration in the live Blender instance**

Reload the addon, then use the Blender MCP `execute_blender_code` tool:

```python
import bpy
# Confirm the operator is registered and discoverable.
op = getattr(bpy.types, "IOPS_OT_VisualCursorUV", None)
assert op is not None, "class not registered"
assert hasattr(bpy.ops.iops, "uv_visual_cursor"), "idname not registered"
# Confirm the keymap entry landed in the UV Editor keymap.
kc = bpy.context.window_manager.keyconfigs.addon
km = kc.keymaps.get("UV Editor")
hits = [kmi.idname for kmi in km.keymap_items if kmi.idname == "iops.uv_visual_cursor"]
assert hits, "keymap entry missing"
print("registration OK")
```
Expected output: `registration OK`. (Reload the addon from Preferences > Add-ons, or disable/enable InteractionOps, so the new import and keymap entry take effect before running this.)

- [ ] **Step 5: Commit**

```bash
git add __init__.py prefs/hotkeys_default.py
git commit -m "feat(uv-cursor): register operator + UV-editor keymap entry"
```

---

### Task 4: Documentation page

**Files:**
- Create: `docs/operators/op_uv_visual_cursor.md`

- [ ] **Step 1: Write the doc page (follows `op_drag_snap_uv.md` format)**

```markdown
# Visual Cursor UV

Interactive modal for the UV/Image Editor that places the 2D cursor on a snap point of a bounding-box cage — the UV-editor counterpart of the 3D Visual Origin tool. Draws a 9-point cage (4 corners + 4 edge midpoints + center) over the selected UVs, highlights the point nearest the mouse, and on confirm sets `space.cursor_location` (which doubles as the UV transform pivot) to that point.

<div class="iops-meta" markdown="1">
<span class="key">bl_idname: iops.uv_visual_cursor</span>
<span class="mode">Mode: Edit Mesh</span>
<span>Context: IMAGE_EDITOR</span>
<span class="modal">Modal: yes</span>
<span class="hud">HUD: yes</span>
</div>

## Overview
On invoke the operator computes the bounding box of the currently selected UV verts on the active mesh and builds 9 snap points from it. Each tick the points are re-projected to region space to find the one nearest the mouse, which is highlighted. Confirming writes that point to the 2D cursor.

Holding <kbd>Alt</kbd> switches to **tile mode**: the cage ignores the selection and snaps to the unit UDIM tile (`floor(u),floor(v)`..`+1,+1`) under the mouse, following the mouse across tiles. If nothing is selected when the tool starts, it begins in tile mode automatically.

## Usage
- Active object must be a mesh in Edit Mode, and the active area must be the UV/Image Editor.
- Default keymap: `Ctrl+Alt+Shift+F19` placeholder (rebind in addon preferences before using).
- Flow: hover to highlight the nearest cage point, <kbd>LMB</kbd>/<kbd>Space</kbd> to set the 2D cursor there. Hold <kbd>Alt</kbd> to snap against the hovered UDIM tile instead of the selection.

## Modal Controls
| Key | Action |
| --- | --- |
| <kbd>MouseMove</kbd> | Update highlighted cage point (and, in tile mode, the hovered tile) |
| <kbd>LMB</kbd> / <kbd>Space</kbd> | Set the 2D cursor to the highlighted point and finish |
| <kbd>Alt</kbd> (hold) | Tile mode: cage snaps to the unit UDIM tile under the mouse |
| <kbd>H</kbd> | Toggle help / HUD overlay |
| <kbd>MMB</kbd> / <kbd>WheelUp</kbd> / <kbd>WheelDown</kbd> | Pass through (pan / zoom) |
| <kbd>RMB</kbd> / <kbd>Esc</kbd> | Cancel |

## HUD
Overlay rendered in the Image Editor:
- The bounding-box cage via `Role.BBOX` and its 9 snap points via `Role.POINT`.
- The highlighted (nearest) point via `Role.CLOSEST_POINT`.
- HUD title "Visual Cursor UV" plus a help section listing the modal shortcuts. Supports the standard drag-to-reposition and parameter-toggle interactions provided by `HUDOverlay` / `HelpOverlay`, driven by the addon's theme preferences.

## Notes
- Scope is the active mesh only; multi-object UV edit is not aggregated.
- Confirm only moves the 2D cursor — it does not move the UV selection (see [Drag Snap UV](op_drag_snap_uv.md) for selection moves).
- The 2D cursor value is not clamped to 0..1; tiles outside the unit square are valid targets.

## Related
- [Drag Snap UV](op_drag_snap_uv.md)
- [Visual Origin (3D)](op_visual_origin.md)
```

(If `op_visual_origin.md` does not exist in `docs/operators/`, drop that last bullet from the Related list.)

- [ ] **Step 2: Commit**

```bash
git add docs/operators/op_uv_visual_cursor.md
git commit -m "docs(uv-cursor): operator reference page"
```

---

### Task 5: Live interactive verification

**Files:** none (manual verification against the design spec's acceptance criteria)

- [ ] **Step 1: Prepare the scene**

In the live Blender instance: open an Image/UV editor, select a mesh, enter Edit Mode, select some UVs. Confirm the addon is reloaded so the new keymap/operator are active.

- [ ] **Step 2: Verify selection mode**

Invoke the operator (run via MCP `execute_blender_code`: `bpy.ops.iops.uv_visual_cursor('INVOKE_DEFAULT')` from a UV-editor context override, or bind a key and press it). Confirm:
- A rectangular cage with 9 points appears on the selected-UV bbox.
- Moving the mouse highlights the nearest point.
- <kbd>LMB</kbd>/<kbd>Space</kbd> moves the 2D cursor to the highlighted point.
Capture a screenshot via the MCP `get_screenshot_of_area_as_image` tool to confirm visually.

- [ ] **Step 3: Verify tile mode**

Re-invoke and hold <kbd>Alt</kbd>. Confirm the cage switches to the unit tile under the mouse and follows the mouse across tiles; releasing <kbd>Alt</kbd> returns to the selection cage. Confirm a tile point can be confirmed.

- [ ] **Step 4: Verify empty-selection auto-tile and cancel**

Deselect all UVs, re-invoke. Confirm it starts directly in tile mode. Confirm <kbd>Esc</kbd>/<kbd>RMB</kbd> cancels and leaves the 2D cursor unchanged; confirm <kbd>H</kbd> and <kbd>/</kbd> toggle the help/params overlay.

- [ ] **Step 5: Final commit (if any doc/screenshot notes were added)**

```bash
git status   # confirm clean tree, or commit any verification notes
```

---

## Self-Review (completed during planning)

- **Spec coverage:** selection mode (T1 `_selection_bbox`, T2 `_update`), tile mode + auto-start (T2 `_update` `tile = event.alt or sel_min is None`), 9-point set (T1 `_bbox_snap_points`), picking (T2 `_pick_nearest`), theme `Role` draw + HUD (T2 draw handlers + `_build_hud`), confirm = cursor only (T2 `_set_cursor`), cancel (T2 modal), registration + F19 keymap (T3), docs (T4), manual verification (T5). All spec sections map to a task.
- **Placeholder scan:** no TBD/TODO; every code step is complete and self-contained.
- **Type consistency:** `pos_batch_uv` (list of 2D `Vector`), `nearest`/`nearest_idx`, `sel_min`/`sel_max`, `tile_mode`, `mouse_pos` used consistently across `invoke`/`_update`/`_pick_nearest`/draw handlers. `_region_pt`, `_set_cursor`, `clear_draw_handlers`, `_build_hud`/`_draw_hud` names consistent. Draw role names (`Role.BBOX`/`POINT`/`CLOSEST_POINT`) verified against `ui/draw/theme.py`. Primitive signatures (`polyline`/`points` with `role=`/`context=`) verified against `ui/draw/primitives.py`.
