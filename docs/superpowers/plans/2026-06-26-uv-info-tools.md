# UV Info Tools Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a UV-context "draw rectangle → report UV min/max/size" modal operator and a UV-editor sidebar panel gathering the addon's UV tools.

**Architecture:** Pure bounds/format math lives in `utils/uv_info.py` (no `bpy`, pytest-covered). The modal operator `IOPS_OT_UVInfoRect` in `operators/uv_info.py` handles drawing/interaction and calls those helpers. A sidebar panel `IOPS_PT_UV_Panel` in `ui/iops_uv_panel.py` lists UV operators. All registered in `__init__.py`.

**Tech Stack:** Python, Blender `bpy`/`gpu`, addon's own `ui.draw` primitives + `ui.hud` overlays, pytest (pure NumPy-style unit tests, no Blender), Blender MCP for live smoke tests.

## Global Constraints

- Code and comments in English.
- Pure unit tests must not import `bpy` or the addon `__init__` (see `tests/conftest.py`): testable logic goes in `utils/`, imported by the operator.
- Operators/panels verified live via Blender MCP, not pytest.
- Follow existing patterns: modal operator mirrors `operators/drag_snap_uv.py`; panel mirrors `ui/iops_object_color_panel.py`.
- Commit directly on `master`; one focused commit per task.

---

### Task 1: Pure bounds/format helpers

**Files:**
- Create: `utils/uv_info.py`
- Test: `tests/test_uv_info.py`

**Interfaces:**
- Produces:
  - `uv_rect_bounds(c0, c1) -> tuple[tuple[float,float], tuple[float,float], tuple[float,float]]`
    returns `(uv_min, uv_max, size)` where `uv_min=(min u, min v)`, `uv_max=(max u, max v)`, `size=(max u-min u, max v-min v)`. `c0`/`c1` are any `(u, v)` pairs (drag-direction independent).
  - `format_uv_rect(uv_min, uv_max, size, ndigits=6) -> str`
    returns `"min: (u, v) max: (u, v) size: (w, h)"` with each number rounded to `ndigits` and formatted via `f"{x:.{ndigits}f}"`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_uv_info.py
from utils.uv_info import uv_rect_bounds, format_uv_rect


def test_bounds_normalizes_drag_direction():
    # corner order reversed must give same min/max
    a = uv_rect_bounds((0.8, 0.1), (0.2, 0.7))
    b = uv_rect_bounds((0.2, 0.7), (0.8, 0.1))
    assert a == b
    uv_min, uv_max, size = a
    assert uv_min == (0.2, 0.1)
    assert uv_max == (0.8, 0.7)
    assert size[0] == 0.6
    assert round(size[1], 6) == 0.6


def test_format_rounds_to_six_decimals():
    s = format_uv_rect((0.1234567, 0.2), (0.8, 0.9), (0.6765433, 0.7))
    assert s == "min: (0.123457, 0.200000) max: (0.800000, 0.900000) size: (0.676543, 0.700000)"


def test_format_respects_ndigits():
    s = format_uv_rect((0.12345, 0.2), (0.8, 0.9), (0.67655, 0.7), ndigits=3)
    assert s == "min: (0.123, 0.200) max: (0.800, 0.900) size: (0.677, 0.700)"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_uv_info.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'utils.uv_info'`

- [ ] **Step 3: Write minimal implementation**

```python
# utils/uv_info.py
"""Pure UV-rectangle bounds math, free of bpy so it can be unit-tested.

Consumed by operators/uv_info.py (IOPS_OT_UVInfoRect)."""


def uv_rect_bounds(c0, c1):
    """Axis-aligned UV bounds of the rectangle spanned by corners c0, c1.

    Returns (uv_min, uv_max, size) as ((u,v),(u,v),(w,h)), independent of
    which corner was dragged first."""
    u0, v0 = c0
    u1, v1 = c1
    umin, umax = (u0, u1) if u0 <= u1 else (u1, u0)
    vmin, vmax = (v0, v1) if v0 <= v1 else (v1, v0)
    uv_min = (umin, vmin)
    uv_max = (umax, vmax)
    size = (umax - umin, vmax - vmin)
    return uv_min, uv_max, size


def format_uv_rect(uv_min, uv_max, size, ndigits=6):
    """Human-readable one-liner for the clipboard / report."""
    def fmt(p):
        return f"({p[0]:.{ndigits}f}, {p[1]:.{ndigits}f})"
    return f"min: {fmt(uv_min)} max: {fmt(uv_max)} size: {fmt(size)}"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_uv_info.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add utils/uv_info.py tests/test_uv_info.py
git commit -m "feat(uv): pure UV-rect bounds/format helpers"
```

---

### Task 2: `IOPS_OT_UVInfoRect` modal operator + registration

**Files:**
- Create: `operators/uv_info.py`
- Modify: `__init__.py` (import near line 78; class tuple near line 431)

**Interfaces:**
- Consumes: `from ..utils.uv_info import uv_rect_bounds, format_uv_rect` (Task 1).
- Consumes (existing): `..ui.draw` (`primitives as draw`, `draw_scope`, `Role`, `safe_handler_add`, `safe_handler_remove`), `..ui.draw.theme.get_theme`, `..ui.hud` (`HUDOverlay`, `HelpOverlay`, `HUDSection`, `HUDItem`, `ItemState`, `capture_event`).
- Produces: operator `bl_idname = "iops.uv_info_rect"`, class `IOPS_OT_UVInfoRect`.

- [ ] **Step 1: Write the operator**

```python
# operators/uv_info.py
"""UV-context information operators (Image Editor).

IOPS_OT_UVInfoRect: rubber-band a rectangle in the UV editor and report its
UV min/max/size, copying them to the clipboard."""

import bpy
from mathutils import Vector

from ..ui.draw import primitives as draw, draw_scope, Role
from ..ui.draw import safe_handler_add, safe_handler_remove
from ..ui.hud import (HUDOverlay, HelpOverlay, HUDSection, HUDItem,
                      ItemState, capture_event)
from ..utils.uv_info import uv_rect_bounds, format_uv_rect


class IOPS_OT_UVInfoRect(bpy.types.Operator):
    """Draw a rectangle in the UV editor; reports UV min/max/size and copies them"""

    bl_idname = "iops.uv_info_rect"
    is_bindable = True
    bl_label = "IOPS UV Info Rect"
    bl_options = {"REGISTER"}

    sd_handlers = []

    @classmethod
    def poll(cls, context):
        return context.area is not None and context.area.type == "IMAGE_EDITOR"

    def clear_draw_handlers(self):
        for handler in self.sd_handlers:
            safe_handler_remove(handler, bpy.types.SpaceImageEditor, "WINDOW")

    def _build_hud(self, context):
        hud = HUDOverlay("uv_info_rect")
        hud.title = "UV Info Rect"
        hud.bind_region(context.region)
        helpo = HelpOverlay("uv_info_rect")
        helpo.add_section(HUDSection("UV Info Rect", [
            HUDItem("Draw rectangle", "LMB", ItemState.ON, default_state=ItemState.OFF, always_show=True),
            HUDItem("Copy bounds",    "LMB release", ItemState.ON, default_state=ItemState.OFF, always_show=True),
            HUDItem("Cancel",         "Esc", ItemState.ON, default_state=ItemState.OFF, always_show=True),
            HUDItem("Help / Toggle HUD", "H", ItemState.ON, default_state=ItemState.OFF, always_show=True),
        ]))
        helpo.bind_region(context.region)
        return hud, helpo

    def _bounds_uv(self, context):
        """Current rectangle bounds in UV space, or None if no rectangle."""
        if self.start is None or self.end is None:
            return None
        v2d = context.region.view2d
        c0 = v2d.region_to_view(self.start[0], self.start[1])
        c1 = v2d.region_to_view(self.end[0], self.end[1])
        return uv_rect_bounds(c0, c1)

    def _draw_rect(self, context):
        if self.start is None or self.end is None:
            return
        x0, y0 = self.start
        x1, y1 = self.end
        loop = [Vector((x0, y0, 0.0)), Vector((x1, y0, 0.0)),
                Vector((x1, y1, 0.0)), Vector((x0, y1, 0.0)),
                Vector((x0, y0, 0.0))]
        with draw_scope(blend="ALPHA"):
            draw.polyline(loop, role=Role.PREVIEW_LINE, context=context)
        bounds = self._bounds_uv(context)
        if bounds is not None:
            uv_min, uv_max, _ = bounds
            v2d = context.region.view2d
            pmin = v2d.view_to_region(uv_min[0], uv_min[1], clip=False)
            pmax = v2d.view_to_region(uv_max[0], uv_max[1], clip=False)
            draw.points([Vector((pmin[0], pmin[1], 0.0)),
                         Vector((pmax[0], pmax[1], 0.0))],
                        role=Role.ACTIVE_POINT, context=context)

    def _draw_hud(self, context):
        bounds = self._bounds_uv(context)
        if bounds is not None and getattr(self, "hud", None) is not None:
            uv_min, uv_max, size = bounds
            self.hud.title = (f"min ({uv_min[0]:.4f}, {uv_min[1]:.4f})  "
                              f"max ({uv_max[0]:.4f}, {uv_max[1]:.4f})  "
                              f"size ({size[0]:.4f}, {size[1]:.4f})")
        helpo = getattr(self, "help", None)
        if helpo is not None:
            helpo.draw(context, getattr(self, "_last_event", None))
        if getattr(self, "hud", None) is not None:
            self.hud.draw(context, getattr(self, "_last_event", None))

    def _copy_bounds(self, context):
        bounds = self._bounds_uv(context)
        if bounds is None:
            return
        text = format_uv_rect(*bounds)
        context.window_manager.clipboard = text
        self.report({"INFO"}, text)

    def modal(self, context, event):
        context.area.tag_redraw()
        self._last_event = capture_event(event, getattr(self, "_last_event", None))
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

        elif event.type == "MOUSEMOVE":
            if self.dragging:
                self.end = (event.mouse_region_x, event.mouse_region_y)

        elif event.type == "LEFTMOUSE" and event.value == "PRESS":
            self.start = (event.mouse_region_x, event.mouse_region_y)
            self.end = (event.mouse_region_x, event.mouse_region_y)
            self.dragging = True

        elif event.type == "LEFTMOUSE" and event.value == "RELEASE":
            if self.dragging:
                self.end = (event.mouse_region_x, event.mouse_region_y)
                self.dragging = False
                self._copy_bounds(context)

        elif event.type in {"RIGHTMOUSE", "ESC"}:
            self.clear_draw_handlers()
            self.report({"INFO"}, "UV Info Rect - cancelled")
            return {"CANCELLED"}

        return {"RUNNING_MODAL"}

    def invoke(self, context, event):
        if context.space_data.type != "IMAGE_EDITOR":
            self.report({"WARNING"}, "Active space must be an Image Editor")
            return {"CANCELLED"}

        self.start = None
        self.end = None
        self.dragging = False

        self.hud, self.help = self._build_hud(context)
        self._last_event = capture_event(event, None)

        self.handle_rect = safe_handler_add(bpy.types.SpaceImageEditor,
            self._draw_rect, (context,), "WINDOW", "POST_PIXEL", tick=True)
        self.handle_hud = safe_handler_add(bpy.types.SpaceImageEditor,
            self._draw_hud, (context,), "WINDOW", "POST_PIXEL", tick=True)
        self.sd_handlers = [self.handle_rect, self.handle_hud]

        context.window_manager.modal_handler_add(self)
        self.report({"INFO"}, "UV Info Rect: drag to measure")
        return {"RUNNING_MODAL"}
```

- [ ] **Step 2: Register in `__init__.py`**

Add the import next to the other operator imports (near line 78, after the `drag_snap_uv` import):

```python
from .operators.uv_info import IOPS_OT_UVInfoRect
```

Add to the `classes` tuple, right after `IOPS_OT_DragSnapUV,` (line 431):

```python
    IOPS_OT_UVInfoRect,
```

- [ ] **Step 3: Smoke-test live in Blender via MCP**

Use the `blender-mcp` skill. Run this Python in Blender (addon already enabled):

```python
import bpy, importlib, InteractionOps
# reload so new module/registration is picked up
bpy.ops.preferences.addon_disable(module="InteractionOps")
importlib.reload(InteractionOps)
bpy.ops.preferences.addon_enable(module="InteractionOps")

op = bpy.types.IOPS_OT_UVInfoRect
print("OPERATOR_REGISTERED", op.bl_idname)

# poll must be False outside IMAGE_EDITOR
print("POLL_VIEW3D", bpy.ops.iops.uv_info_rect.poll())
```

Expected output: `OPERATOR_REGISTERED iops.uv_info_rect` and `POLL_VIEW3D False` (no Image Editor in the default context → poll False, no traceback). A clean enable with no import/registration error is the pass condition.

- [ ] **Step 4: Commit**

```bash
git add operators/uv_info.py __init__.py
git commit -m "feat(uv): UV Info Rect modal operator (draw rect -> min/max/size)"
```

---

### Task 3: `IOPS_PT_UV_Panel` sidebar panel + registration

**Files:**
- Create: `ui/iops_uv_panel.py`
- Modify: `__init__.py` (import near line 114; class tuple near line 442)

**Interfaces:**
- Consumes: operator ids `iops.uv_info_rect` (Task 2) and existing `iops.uv_drag_snap_uv`.
- Produces: panel class `IOPS_PT_UV_Panel`.

- [ ] **Step 1: Write the panel**

```python
# ui/iops_uv_panel.py
"""UV Tools sidebar panel (Image Editor, iOps tab).

Gathers the addon's UV-context operators as buttons. Buttons are always
shown; each operator's own poll() guards execution (e.g. drag_snap_uv needs
edit-mode + selected mesh)."""

import bpy


class IOPS_PT_UV_Panel(bpy.types.Panel):
    """IOPS UV Tools"""

    bl_label = "IOPS UV Tools"
    bl_idname = "IOPS_PT_UV_Panel"
    bl_space_type = "IMAGE_EDITOR"
    bl_region_type = "UI"
    bl_category = "iOps"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        layout = self.layout
        col = layout.column(align=True)
        col.scale_y = 1.1
        col.operator("iops.uv_info_rect", icon="MESH_PLANE", text="UV Info Rect")
        col.operator("iops.uv_drag_snap_uv", icon="SNAP_ON", text="Drag Snap UV")
```

- [ ] **Step 2: Register in `__init__.py`**

Add the import next to the other panel imports (near line 114):

```python
from .ui.iops_uv_panel import IOPS_PT_UV_Panel
```

Add to the `classes` tuple, after `IOPS_PT_Object_Color_Panel,` (line 442):

```python
    IOPS_PT_UV_Panel,
```

- [ ] **Step 3: Smoke-test live in Blender via MCP**

Use the `blender-mcp` skill. Run in Blender:

```python
import bpy, importlib, InteractionOps
bpy.ops.preferences.addon_disable(module="InteractionOps")
importlib.reload(InteractionOps)
bpy.ops.preferences.addon_enable(module="InteractionOps")

pt = bpy.types.IOPS_PT_UV_Panel
print("PANEL_REGISTERED", pt.bl_idname, pt.bl_space_type, pt.bl_region_type, pt.bl_category)
```

Expected: `PANEL_REGISTERED IOPS_PT_UV_Panel IMAGE_EDITOR UI iOps`, no traceback. Pass condition: clean enable + panel type present.

- [ ] **Step 4: Commit**

```bash
git add ui/iops_uv_panel.py __init__.py
git commit -m "feat(uv): UV Tools sidebar panel in Image Editor"
```

---

## Self-Review

**Spec coverage:**
- `operators/uv_info.py` + `IOPS_OT_UVInfoRect` → Task 2. ✓
- poll IMAGE_EDITOR only, no edit-mode → Task 2 poll. ✓
- invoke: draw handlers + HUD + modal → Task 2. ✓
- LMB press starts/replaces rect, MOUSEMOVE drags, release copies + keeps rect → Task 2 modal. ✓
- bounds via region_to_view, direction-independent min/max/size → Task 1 (`uv_rect_bounds`) + Task 2 `_bounds_uv`. ✓
- clipboard format `min: (..) max: (..) size: (w, h)`, 6 decimals → Task 1 (`format_uv_rect`). ✓
- outline polyline PREVIEW_LINE, corner points ACTIVE_POINT, HUD shows min/max/size → Task 2. ✓
- Esc/RMB cancel + remove handlers; wheel/MMB pass-through → Task 2. ✓
- `ui/iops_uv_panel.py` `IOPS_PT_UV_Panel`, IMAGE_EDITOR/UI/iOps, buttons for uv_info_rect + drag_snap_uv, always shown → Task 3. ✓
- Registration in `__init__.py` → Tasks 2 & 3. ✓

**Placeholder scan:** none — all code and commands are concrete.

**Type consistency:** `uv_rect_bounds`/`format_uv_rect` signatures identical across Task 1 definition and Task 2 usage (`format_uv_rect(*bounds)` where `bounds=(uv_min, uv_max, size)`). ✓
