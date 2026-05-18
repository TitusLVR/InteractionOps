# Theme Palette Unification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Pull hardcoded color palettes in `mesh_visual_uv.py` and `mesh_shear.py` into the unified `IOPS_Theme`, adding 5 new utility roles, an 8-color island palette, and a Blender-axis-color helper.

**Architecture:** State-like colors reuse the existing 5-state Line/Point/Text roles. Five new utility roles (`HANDLE`, `HANDLE_HOVER`, `PIVOT`, `BBOX`, `CURSOR`) are added to `Role` enum. An `island_palette` tuple is added to `Theme`. Axis X/Y/Z colors are pulled live from Blender's `user_interface` theme via a new `axis_color()` helper. `primitives.*` and `hud_text.draw()` gain an optional `color=` override so axis-colored geometry can bypass the role lookup. Operators rewrite their inline color calls to use roles + the explicit color override.

**Tech Stack:** Python 3.11, Blender 4.x Python API (`bpy`, `gpu`, `blf`), addon's own `ui.draw` / `ui.hud` modules. No new external dependencies.

**Reference spec:** [docs/superpowers/specs/2026-05-18-theme-palette-unification-design.md](../specs/2026-05-18-theme-palette-unification-design.md)

**Validation strategy:** Addon is visual; no unit-test suite. Each implementation task ends with a Blender MCP smoke test (`mcp__blender__execute_blender_python`) that reloads the addon and asserts: (a) registration succeeds without exceptions, (b) the inspected attribute/role/theme value exists with the expected default. The smoke test is the "test passes" gate.

---

## File Structure

**Modified:**
- `ui/draw/theme.py` — add 5 roles, `island_palette` field, `axis_color()` helper, default colors, `get_theme()` plumbing
- `ui/draw/primitives.py` — add optional `color=` override to `line/polyline/edges_3d/points/tris`
- `ui/hud/text.py` — add optional `color=` override to `draw()`
- `prefs/theme.py` — add 5 widget `FloatVectorProperty` defs, 8 island-palette props, draw new UI sections
- `operators/mesh_visual_uv.py` — strip 14 `COL_*` consts + `ISLAND_COLORS`, route helpers through primitives, use `island_palette` + `axis_color`
- `operators/mesh_shear.py` — strip 13 inline `uniform_float("color", ...)` calls, route draws through primitives, use `axis_color`

**Created:** none.

---

## Task 1: Add new Role enum values and default colors

**Files:**
- Modify: `ui/draw/theme.py:6-36` (Role enum), `ui/draw/theme.py:50-84` (_DEFAULT_COLORS)

- [ ] **Step 1: Add new Role members**

Edit `ui/draw/theme.py`. After the `Role.SUCCESS = "success"` line (around line 30), and before the `# HUD-specific.` comment block, insert:

```python
    # Widgets (no per-state variants).
    HANDLE = "handle"
    HANDLE_HOVER = "handle_hover"
    PIVOT = "pivot"
    BBOX = "bbox"
    CURSOR = "cursor"
```

- [ ] **Step 2: Add default colors**

In the same file, in the `_DEFAULT_COLORS` dict, after the existing `Role.SUCCESS: (*_C_GREEN, 1.00),` line, insert:

```python
    Role.HANDLE:        (1.000, 1.000, 1.000, 0.85),
    Role.HANDLE_HOVER:  (1.000, 0.850, 0.000, 1.00),
    Role.PIVOT:         (1.000, 1.000, 1.000, 0.80),
    Role.BBOX:          (0.650, 0.650, 0.650, 0.30),
    Role.CURSOR:        (1.000, 0.200, 0.600, 1.00),
```

- [ ] **Step 3: Smoke test — roles present**

Run this via `mcp__blender__execute_blender_python`:

```python
import bpy, sys
ADDON = "InteractionOps"
bpy.ops.preferences.addon_disable(module=ADDON)
for name in list(sys.modules):
    if name == ADDON or name.startswith(ADDON + "."):
        del sys.modules[name]
bpy.ops.preferences.addon_enable(module=ADDON)
from InteractionOps.ui.draw.theme import Role, DEFAULT_THEME
result = {
    "new_roles_exist": all(hasattr(Role, n) for n in
                           ("HANDLE", "HANDLE_HOVER", "PIVOT", "BBOX", "CURSOR")),
    "handle_default": DEFAULT_THEME.color_for(Role.HANDLE),
    "cursor_default": DEFAULT_THEME.color_for(Role.CURSOR),
}
```

Expected:
```
{"new_roles_exist": true,
 "handle_default": (1.0, 1.0, 1.0, 0.85),
 "cursor_default": (1.0, 0.2, 0.6, 1.0)}
```

- [ ] **Step 4: Commit**

```bash
git add ui/draw/theme.py
git commit -m "feat(theme): add HANDLE/HANDLE_HOVER/PIVOT/BBOX/CURSOR roles"
```

---

## Task 2: Add island_palette field to Theme dataclass

**Files:**
- Modify: `ui/draw/theme.py:100-160` (Theme dataclass + DEFAULT_PALETTE)

- [ ] **Step 1: Add default palette constant**

In `ui/draw/theme.py`, after the `_DEFAULT_TEXT_SIZES = {...}` block (around line 97), insert:

```python
_DEFAULT_ISLAND_PALETTE = (
    (0.40, 0.65, 1.00, 0.50),
    (1.00, 0.50, 0.30, 0.50),
    (0.35, 0.85, 0.45, 0.50),
    (0.95, 0.80, 0.25, 0.50),
    (0.70, 0.40, 0.90, 0.50),
    (0.20, 0.80, 0.75, 0.50),
    (0.90, 0.35, 0.60, 0.50),
    (0.60, 0.80, 0.20, 0.50),
)
```

- [ ] **Step 2: Add field to Theme dataclass**

In the same file, in the `Theme` dataclass, after the `depth_test_default: str = "LESS"` line, add:

```python
    island_palette: tuple[tuple[float, float, float, float], ...] = field(
        default_factory=lambda: _DEFAULT_ISLAND_PALETTE)
```

- [ ] **Step 3: Smoke test — palette present and indexable**

```python
import bpy, sys
ADDON = "InteractionOps"
bpy.ops.preferences.addon_disable(module=ADDON)
for name in list(sys.modules):
    if name == ADDON or name.startswith(ADDON + "."):
        del sys.modules[name]
bpy.ops.preferences.addon_enable(module=ADDON)
from InteractionOps.ui.draw.theme import DEFAULT_THEME
result = {
    "len": len(DEFAULT_THEME.island_palette),
    "first": DEFAULT_THEME.island_palette[0],
    "wraps_via_modulo": DEFAULT_THEME.island_palette[9 % 8],
}
```

Expected:
```
{"len": 8,
 "first": (0.4, 0.65, 1.0, 0.5),
 "wraps_via_modulo": (1.0, 0.5, 0.3, 0.5)}
```

- [ ] **Step 4: Commit**

```bash
git add ui/draw/theme.py
git commit -m "feat(theme): add island_palette tuple to Theme dataclass"
```

---

## Task 3: Add axis_color() helper

**Files:**
- Modify: `ui/draw/theme.py` (top imports + bottom of file)

- [ ] **Step 1: Import bpy at top of file**

At the top of `ui/draw/theme.py`, after the existing `from __future__` and dataclass imports, ensure there is:

```python
import bpy
```

(If `bpy` is already imported, skip.)

- [ ] **Step 2: Add axis_color() helper**

At the bottom of `ui/draw/theme.py`, after the `DEFAULT_THEME = Theme()` line, append:

```python
_AXIS_FALLBACK = {
    "X": (1.0, 0.27, 0.27, 1.0),
    "Y": (0.27, 0.75, 0.27, 1.0),
    "Z": (0.27, 0.27, 1.00, 1.0),
}


def axis_color(axis: str) -> tuple[float, float, float, float]:
    """Return Blender's built-in axis_x/y/z color with alpha=1.0.

    Falls back to canonical red/green/blue if user_interface theme is
    unavailable (e.g. headless contexts where themes[0] is missing the
    axis attrs).
    """
    try:
        ui = bpy.context.preferences.themes[0].user_interface
        src = {"X": ui.axis_x, "Y": ui.axis_y, "Z": ui.axis_z}[axis]
        return (src[0], src[1], src[2], 1.0)
    except (KeyError, AttributeError, IndexError):
        return _AXIS_FALLBACK[axis]
```

- [ ] **Step 3: Export from package**

Modify `ui/draw/__init__.py`. Replace:

```python
from .theme import Theme, Role, get_theme, DEFAULT_THEME
```

with:

```python
from .theme import Theme, Role, get_theme, DEFAULT_THEME, axis_color
```

And in the `__all__` list, add `"axis_color"`:

```python
__all__ = ["Theme", "Role", "get_theme", "DEFAULT_THEME", "axis_color",
           "draw_scope", "primitives", "shaders"]
```

- [ ] **Step 4: Smoke test — axis_color returns valid tuples**

```python
import bpy, sys
ADDON = "InteractionOps"
bpy.ops.preferences.addon_disable(module=ADDON)
for name in list(sys.modules):
    if name == ADDON or name.startswith(ADDON + "."):
        del sys.modules[name]
bpy.ops.preferences.addon_enable(module=ADDON)
from InteractionOps.ui.draw import axis_color
result = {
    "x": axis_color("X"),
    "y": axis_color("Y"),
    "z": axis_color("Z"),
    "x_len_4": len(axis_color("X")) == 4,
    "x_alpha_1": axis_color("X")[3] == 1.0,
}
```

Expected: all four tuples are length-4 floats, alpha is 1.0, RGB components in [0.0, 1.0]. Exact RGB depends on Blender theme; the test only validates shape, not exact values.

- [ ] **Step 5: Commit**

```bash
git add ui/draw/theme.py ui/draw/__init__.py
git commit -m "feat(theme): add axis_color() helper pulling from Blender UI theme"
```

---

## Task 4: Add IOPS_Theme widget color properties

**Files:**
- Modify: `prefs/theme.py:50-65` (after surfaces/status block)

- [ ] **Step 1: Add 5 widget color properties to IOPS_Theme**

Edit `prefs/theme.py`. Find the section that ends with the surfaces/status block:

```python
    # --- Surfaces / status ---
    color_fill:            _color((1.000, 1.000, 1.000, 0.15), "Fill")
    color_error:           _color((1.000, 0.353, 0.353, 1.00), "Error")
    color_success:         _color((0.344, 1.000, 0.653, 1.00), "Success")
```

Immediately after `color_success:`, before the `# --- HUD ---` block, insert:

```python
    # --- Widgets ---
    color_handle:          _color((1.000, 1.000, 1.000, 0.85), "Handle")
    color_handle_hover:    _color((1.000, 0.850, 0.000, 1.00), "Handle (hover)")
    color_pivot:           _color((1.000, 1.000, 1.000, 0.80), "Pivot")
    color_bbox:            _color((0.650, 0.650, 0.650, 0.30), "Selection bbox")
    color_cursor:          _color((1.000, 0.200, 0.600, 1.00), "Cursor (2D)")
```

- [ ] **Step 2: Smoke test — properties registered**

```python
import bpy, sys
ADDON = "InteractionOps"
bpy.ops.preferences.addon_disable(module=ADDON)
for name in list(sys.modules):
    if name == ADDON or name.startswith(ADDON + "."):
        del sys.modules[name]
bpy.ops.preferences.addon_enable(module=ADDON)
prefs = bpy.context.preferences.addons[ADDON].preferences
t = prefs.iops_theme
result = {
    "handle": list(t.color_handle),
    "pivot": list(t.color_pivot),
    "cursor": list(t.color_cursor),
}
```

Expected:
```
{"handle": [1.0, 1.0, 1.0, 0.85],
 "pivot":  [1.0, 1.0, 1.0, 0.80],
 "cursor": [1.0, 0.2, 0.6, 1.0]}
```

- [ ] **Step 3: Commit**

```bash
git add prefs/theme.py
git commit -m "feat(prefs): add handle/pivot/bbox/cursor color props to IOPS_Theme"
```

---

## Task 5: Add IOPS_Theme island_palette properties

**Files:**
- Modify: `prefs/theme.py` (after widget block from Task 4)

- [ ] **Step 1: Add 8 island palette color properties**

Edit `prefs/theme.py`. After the `color_cursor:` line added in Task 4, insert:

```python
    # --- Island palette (per-island identification, indexed by island_id % 8) ---
    island_palette_0:      _color((0.40, 0.65, 1.00, 0.50), "Island 1")
    island_palette_1:      _color((1.00, 0.50, 0.30, 0.50), "Island 2")
    island_palette_2:      _color((0.35, 0.85, 0.45, 0.50), "Island 3")
    island_palette_3:      _color((0.95, 0.80, 0.25, 0.50), "Island 4")
    island_palette_4:      _color((0.70, 0.40, 0.90, 0.50), "Island 5")
    island_palette_5:      _color((0.20, 0.80, 0.75, 0.50), "Island 6")
    island_palette_6:      _color((0.90, 0.35, 0.60, 0.50), "Island 7")
    island_palette_7:      _color((0.60, 0.80, 0.20, 0.50), "Island 8")
```

- [ ] **Step 2: Smoke test**

```python
import bpy, sys
ADDON = "InteractionOps"
bpy.ops.preferences.addon_disable(module=ADDON)
for name in list(sys.modules):
    if name == ADDON or name.startswith(ADDON + "."):
        del sys.modules[name]
bpy.ops.preferences.addon_enable(module=ADDON)
t = bpy.context.preferences.addons[ADDON].preferences.iops_theme
result = {
    "p0": list(t.island_palette_0),
    "p7": list(t.island_palette_7),
}
```

Expected:
```
{"p0": [0.4, 0.65, 1.0, 0.5],
 "p7": [0.6, 0.8, 0.2, 0.5]}
```

- [ ] **Step 3: Commit**

```bash
git add prefs/theme.py
git commit -m "feat(prefs): add 8-color island_palette props to IOPS_Theme"
```

---

## Task 6: Plumb new prefs through get_theme()

**Files:**
- Modify: `ui/draw/theme.py:162-230` (get_theme function)

- [ ] **Step 1: Add widget roles to get_theme() colors dict**

Edit `ui/draw/theme.py`. In `get_theme()`, find the `colors=` dict block. After the line:

```python
            Role.SUCCESS:            c("color_success",        _DEFAULT_COLORS[Role.SUCCESS]),
```

Insert (before the `# HUD` comment / `Role.HUD_KEY` line):

```python
            Role.HANDLE:             c("color_handle",         _DEFAULT_COLORS[Role.HANDLE]),
            Role.HANDLE_HOVER:       c("color_handle_hover",   _DEFAULT_COLORS[Role.HANDLE_HOVER]),
            Role.PIVOT:              c("color_pivot",          _DEFAULT_COLORS[Role.PIVOT]),
            Role.BBOX:               c("color_bbox",           _DEFAULT_COLORS[Role.BBOX]),
            Role.CURSOR:             c("color_cursor",         _DEFAULT_COLORS[Role.CURSOR]),
```

- [ ] **Step 2: Add island_palette to the Theme constructor call**

In the same `get_theme()` function, find the final `return Theme(...)` call. Just before the closing `)`, after the `depth_test_default=str(t.depth_test_default),` line, add:

```python
        island_palette=tuple(
            tuple(getattr(t, f"island_palette_{i}", _DEFAULT_ISLAND_PALETTE[i]))
            for i in range(8)
        ),
```

- [ ] **Step 3: Smoke test — full plumbing works**

```python
import bpy, sys
ADDON = "InteractionOps"
bpy.ops.preferences.addon_disable(module=ADDON)
for name in list(sys.modules):
    if name == ADDON or name.startswith(ADDON + "."):
        del sys.modules[name]
bpy.ops.preferences.addon_enable(module=ADDON)
from InteractionOps.ui.draw.theme import get_theme, Role
theme = get_theme(bpy.context)
result = {
    "handle": theme.color_for(Role.HANDLE),
    "pivot": theme.color_for(Role.PIVOT),
    "cursor": theme.color_for(Role.CURSOR),
    "palette_len": len(theme.island_palette),
    "palette_0": theme.island_palette[0],
}
```

Expected: handle/pivot/cursor return the defaults; palette_len is 8; palette_0 is approx `(0.4, 0.65, 1.0, 0.5)`.

- [ ] **Step 4: Commit**

```bash
git add ui/draw/theme.py
git commit -m "feat(theme): plumb widget colors + island_palette through get_theme()"
```

---

## Task 7: Draw new theme UI sections

**Files:**
- Modify: `prefs/theme.py` (`draw_theme_tab` function)

- [ ] **Step 1: Insert Widgets section in draw_theme_tab**

Edit `prefs/theme.py`. Find the existing `# Surfaces / status` section in `draw_theme_tab`:

```python
    # Surfaces / status
    box = layout.box()
    box.label(text="Surfaces & status")
    sub = box.column(align=True)
    sub.prop(theme, "color_fill")
    sub.prop(theme, "color_error")
    sub.prop(theme, "color_success")
```

Immediately after this block (after `sub.prop(theme, "color_success")`), insert:

```python

    # Widgets
    box = layout.box()
    box.label(text="Widgets", icon="MOD_HUE_SATURATION")
    sub = box.column(align=True)
    sub.prop(theme, "color_handle")
    sub.prop(theme, "color_handle_hover")
    sub.prop(theme, "color_pivot")
    sub.prop(theme, "color_bbox")
    sub.prop(theme, "color_cursor")

    # Island palette
    box = layout.box()
    box.label(text="Island palette (UV)", icon="COLOR")
    row = box.row(align=True)
    for i in range(8):
        row.prop(theme, f"island_palette_{i}", text="")
```

- [ ] **Step 2: Smoke test — UI registers without errors**

```python
import bpy, sys
ADDON = "InteractionOps"
bpy.ops.preferences.addon_disable(module=ADDON)
for name in list(sys.modules):
    if name == ADDON or name.startswith(ADDON + "."):
        del sys.modules[name]
bpy.ops.preferences.addon_enable(module=ADDON)
# Force the preferences UI to redraw — registers all draw paths.
prefs = bpy.context.preferences.addons[ADDON].preferences
prefs.tabs = "THEME"
# If anything in draw_theme_tab errors, the addon would have failed to enable.
result = {"ok": True, "tabs": prefs.tabs}
```

Expected: `{"ok": true, "tabs": "THEME"}`.

- [ ] **Step 3: Manual visual check (note for the implementer, not blocking)**

Open Blender Preferences → Add-ons → InteractionOps → Theme tab. Visually confirm:
- "Widgets" box appears with 5 color swatches
- "Island palette (UV)" box appears with 8 horizontal swatches

If the swatches are missing or stacked wrong, the loop in Step 1 needs `align=True` on `row` (already there) — re-check.

- [ ] **Step 4: Commit**

```bash
git add prefs/theme.py
git commit -m "feat(prefs/ui): draw Widgets + Island palette sections in Theme tab"
```

---

## Task 8: Add color= override to ui/hud/text.py

**Files:**
- Modify: `ui/hud/text.py:23-29`

- [ ] **Step 1: Update draw() signature**

Replace the entire `draw()` function in `ui/hud/text.py` with:

```python
def draw(text: str, x: int, y: int, *, theme: Theme, role: Role | None = None,
         color: tuple[float, float, float, float] | None = None,
         size_token: str = "normal", font_id: int = 0, alpha_mul: float = 1.0):
    """Draw text. Exactly one of `role` or `color` must be provided.
    `color` lets callers pass a fully-resolved RGBA (e.g. axis colors
    from Blender's user_interface theme) instead of routing through
    a theme Role."""
    if color is None and role is None:
        raise ValueError("hud_text.draw requires either role= or color=")
    configure(theme, size_token, font_id)
    if color is not None:
        r, g, b, a = color
    else:
        r, g, b, a = theme.color_for(role)
    blf.color(font_id, r, g, b, a * alpha_mul)
    blf.position(font_id, x, y, 0)
    blf.draw(font_id, text)
```

- [ ] **Step 2: Smoke test — both call forms accepted**

```python
import bpy, sys
ADDON = "InteractionOps"
bpy.ops.preferences.addon_disable(module=ADDON)
for name in list(sys.modules):
    if name == ADDON or name.startswith(ADDON + "."):
        del sys.modules[name]
bpy.ops.preferences.addon_enable(module=ADDON)
from InteractionOps.ui.hud import text as hud_text
from InteractionOps.ui.draw.theme import get_theme, Role
theme = get_theme(bpy.context)
# This won't actually render (no draw handler), but must not raise.
try:
    # Role form
    hud_text.draw("a", 0, 0, theme=theme, role=Role.ACTIVE_TEXT)
    role_ok = True
except Exception as e:
    role_ok = repr(e)
try:
    # Color form
    hud_text.draw("b", 0, 0, theme=theme, color=(1.0, 0.0, 0.0, 1.0))
    color_ok = True
except Exception as e:
    color_ok = repr(e)
try:
    hud_text.draw("c", 0, 0, theme=theme)
    neither_ok = "should have raised"
except ValueError:
    neither_ok = "raised correctly"
result = {"role_ok": role_ok, "color_ok": color_ok, "neither_ok": neither_ok}
```

Expected:
```
{"role_ok": true,
 "color_ok": true,
 "neither_ok": "raised correctly"}
```

- [ ] **Step 3: Commit**

```bash
git add ui/hud/text.py
git commit -m "feat(hud): add optional color= override to hud_text.draw"
```

---

## Task 9: Add color= override to primitives

**Files:**
- Modify: `ui/draw/primitives.py` (all five drawing functions)

- [ ] **Step 1: Replace primitives.py**

Open `ui/draw/primitives.py` and replace the file body (after the module docstring) with the version below. The shape is identical to the current file — each function gains an optional `color=` kwarg that, when provided, overrides the role color; `role` becomes optional but at least one of the two must be supplied.

```python
from __future__ import annotations
from typing import Sequence

import gpu
from gpu_extras.batch import batch_for_shader

from . import shaders
from .theme import Role, Theme, get_theme


def _resolve_theme(theme: Theme | None, context) -> Theme:
    return theme if theme is not None else get_theme(context)


def _resolve_color(role, color, theme):
    if color is not None:
        return color
    if role is None:
        raise ValueError("primitives draw call requires role= or color=")
    return theme.color_for(role)


def line(p1, p2, *, role: Role | None = None,
         color: tuple[float, float, float, float] | None = None,
         width: str | None = None,
         theme: Theme | None = None, context=None) -> None:
    polyline([p1, p2], role=role, color=color, width=width,
             theme=theme, context=context)


def polyline(coords: Sequence, *, role: Role | None = None,
             color: tuple[float, float, float, float] | None = None,
             width: str | None = None,
             theme: Theme | None = None, context=None) -> None:
    th = _resolve_theme(theme, context)
    shader = shaders.polyline_uniform_color()
    batch = batch_for_shader(shader, "LINE_STRIP", {"pos": list(coords)})
    if width is not None:
        w = th.width(width)
    elif role is not None:
        w = th.line_width_for(role)
    else:
        w = th.width("default")
    c = _resolve_color(role, color, th)
    shader.bind()
    shader.uniform_float("color", c)
    shader.uniform_float("lineWidth", w)
    shader.uniform_float("viewportSize", gpu.state.viewport_get()[2:])
    batch.draw(shader)


def edges_3d(coord_pairs: Sequence, *, role: Role | None = None,
             color: tuple[float, float, float, float] | None = None,
             width: str | None = None,
             theme: Theme | None = None, context=None) -> None:
    th = _resolve_theme(theme, context)
    shader = shaders.polyline_uniform_color()
    batch = batch_for_shader(shader, "LINES", {"pos": list(coord_pairs)})
    if width is not None:
        w = th.width(width)
    elif role is not None:
        w = th.line_width_for(role)
    else:
        w = th.width("default")
    c = _resolve_color(role, color, th)
    shader.bind()
    shader.uniform_float("color", c)
    shader.uniform_float("lineWidth", w)
    shader.uniform_float("viewportSize", gpu.state.viewport_get()[2:])
    batch.draw(shader)


def points(coords: Sequence, *, role: Role | None = None,
           color: tuple[float, float, float, float] | None = None,
           size: str | None = None,
           ring_role: Role | None = None,
           theme: Theme | None = None, context=None) -> None:
    th = _resolve_theme(theme, context)
    shader = shaders.point_disc()
    batch = batch_for_shader(shader, "POINTS", {"pos": list(coords)})
    fill = _resolve_color(role, color, th)
    ring = th.color_for(ring_role if ring_role is not None else Role.POINT_OUTLINE)
    if size is not None:
        px = th.point_size(size)
    elif role is not None:
        px = th.point_size_for(role)
    else:
        px = th.point_size("default")
    shader.bind()
    shader.uniform_float("color", fill)
    shader.uniform_float("ringColor", ring)
    shader.uniform_float("pointSize", px)
    gpu.state.point_size_set(px)
    batch.draw(shader)


def tris(coords: Sequence, *, role: Role | None = None,
         color: tuple[float, float, float, float] | None = None,
         theme: Theme | None = None, context=None) -> None:
    th = _resolve_theme(theme, context)
    shader = shaders.uniform_color()
    batch = batch_for_shader(shader, "TRIS", {"pos": list(coords)})
    c = _resolve_color(role, color, th)
    shader.bind()
    shader.uniform_float("color", c)
    batch.draw(shader)


def rect_2d(x: float, y: float, w: float, h: float, *,
            role: Role | None = None,
            color: tuple[float, float, float, float] | None = None,
            theme: Theme | None = None, context=None) -> None:
    coords = [(x, y), (x + w, y), (x + w, y + h),
              (x, y), (x + w, y + h), (x, y + h)]
    tris(coords, role=role, color=color, theme=theme, context=context)
```

Keep the module docstring at the top unchanged.

- [ ] **Step 2: Smoke test — existing roles still work, new color override works**

```python
import bpy, sys
ADDON = "InteractionOps"
bpy.ops.preferences.addon_disable(module=ADDON)
for name in list(sys.modules):
    if name == ADDON or name.startswith(ADDON + "."):
        del sys.modules[name]
bpy.ops.preferences.addon_enable(module=ADDON)
# Reloading should not break any operator that uses primitives.
# Spot-check mesh_cursor_bisect is still loadable (it uses draw.line/points heavily).
result = {
    "ok": True,
    "bisect": hasattr(bpy.ops.iops, "mesh_cursor_bisect"),
    "visual_uv": hasattr(bpy.ops.iops, "mesh_visual_uv"),
}
```

Expected: `{"ok": true, "bisect": true, "visual_uv": true}`.

- [ ] **Step 3: Commit**

```bash
git add ui/draw/primitives.py
git commit -m "feat(primitives): add optional color= override to all draw calls"
```

---

## Task 10: Migrate mesh_visual_uv low-level draw helpers

**Files:**
- Modify: `operators/mesh_visual_uv.py:70-145` (constants + draw helpers)

- [ ] **Step 1: Replace hardcoded constants and 2D helpers**

In `operators/mesh_visual_uv.py`, find the block starting at `# Colors -- clean, UV-editor style palette` (around line 70) and ending after `def _draw_diamond(...)` (around line 145). Replace that whole block with:

```python
# Per-island identification colors and widget palette now live in
# the unified IOPS_Theme. State-like edge colors are sourced from
# the existing 5-state Line/Point/Text roles. See
# docs/superpowers/specs/2026-05-18-theme-palette-unification-design.md.

from mathutils import Vector

from ..ui.draw import primitives as draw_prim, draw_scope, Role
from ..ui.draw.theme import axis_color


def _v3(p):
    """Lift a 2D pixel-space point into a Vector for primitives.*"""
    return Vector((p[0], p[1], 0.0))


def _draw_polyline(pts, *, role=None, color=None, width="default"):
    """Pixel-space polyline through unified primitives."""
    if len(pts) < 2:
        return
    coords = [_v3(p) for p in pts]
    draw_prim.polyline(coords, role=role, color=color, width=width,
                       context=bpy.context)


def _draw_circle(cx, cy, radius, *, role=None, color=None, segs=16):
    """Filled disc in pixel space. Uses primitives.tris with a fan."""
    verts = [_v3((cx, cy))]
    for i in range(segs + 1):
        a = 2 * math.pi * i / segs
        verts.append(_v3((cx + math.cos(a) * radius,
                          cy + math.sin(a) * radius)))
    tris_flat = []
    for i in range(1, segs + 1):
        nxt = i + 1 if i + 1 <= segs else 1
        tris_flat.extend([verts[0], verts[i], verts[nxt]])
    draw_prim.tris(tris_flat, role=role, color=color, context=bpy.context)


def _draw_ring(cx, cy, radius, *, role=None, color=None,
               width="default", segs=32):
    """Open ring in pixel space."""
    pts = [(cx + math.cos(2 * math.pi * i / segs) * radius,
            cy + math.sin(2 * math.pi * i / segs) * radius)
           for i in range(segs + 1)]
    _draw_polyline(pts, role=role, color=color, width=width)


def _draw_diamond(cx, cy, half, *, role=None, color=None):
    """Filled diamond handle (4-vert quad as 2 triangles)."""
    verts = [_v3((cx, cy - half)),
             _v3((cx + half, cy)),
             _v3((cx, cy + half)),
             _v3((cx - half, cy))]
    coords = [verts[0], verts[1], verts[2],
              verts[0], verts[2], verts[3]]
    draw_prim.tris(coords, role=role, color=color, context=bpy.context)
```

Note: this removes `gpu` / `batch_for_shader` usage from these helpers, so they go away. If any other code in the file uses `gpu` directly, leave that alone for now.

- [ ] **Step 2: Drop unused imports**

In the file's top imports, you can now remove:
```python
import gpu
from gpu_extras.batch import batch_for_shader
```

if and only if nothing else in the file references them. Grep to confirm:

```
grep -n "^import gpu\|gpu\.\|batch_for_shader" operators/mesh_visual_uv.py
```

If only the removed helpers used them, drop the imports. Otherwise leave them in place — the migration is incremental.

- [ ] **Step 3: Smoke test**

```python
import bpy, sys
ADDON = "InteractionOps"
bpy.ops.preferences.addon_disable(module=ADDON)
for name in list(sys.modules):
    if name == ADDON or name.startswith(ADDON + "."):
        del sys.modules[name]
bpy.ops.preferences.addon_enable(module=ADDON)
result = {
    "ok": True,
    "visual_uv": hasattr(bpy.ops.iops, "mesh_visual_uv"),
}
```

Expected: `{"ok": true, "visual_uv": true}`.

- [ ] **Step 4: Commit**

```bash
git add operators/mesh_visual_uv.py
git commit -m "refactor(visual_uv): route low-level draw helpers through primitives"
```

---

## Task 11: Migrate mesh_visual_uv callsites to roles + theme palette

**Files:**
- Modify: `operators/mesh_visual_uv.py:355-510` (`draw_3d_callback`, `draw_pixel_callback`)

- [ ] **Step 1: Inventory callsites**

Run this grep to locate every COL_* / ISLAND_COLORS reference:

```
grep -n "COL_\|ISLAND_COLORS" operators/mesh_visual_uv.py
```

You'll get ~30 lines. Each one needs replacement per the mapping table below.

| Old reference | New form |
|---|---|
| `COL_EDGE` | `role=Role.LINE` |
| `COL_EDGE_SELECTED` | `role=Role.CLOSEST_LINE` |
| `COL_EDGE_ACTIVE` | `role=Role.ACTIVE_LINE` |
| `COL_EDGE_HOVER` | `role=Role.LOCKED_LINE` |
| `COL_EDGE_ALIGN` | `role=Role.PREVIEW_LINE` |
| `COL_CENTER` | `role=Role.PIVOT` |
| `COL_ROT_HANDLE` | `role=Role.PIVOT` |
| `COL_ROT_LINE` | `role=Role.PIVOT` + caller does `color=(_with_alpha 0.35)`; in practice pass `color=(*get_theme(ctx).color_for(Role.PIVOT)[:3], 0.35)` |
| `COL_HANDLE` | `role=Role.HANDLE` |
| `COL_HANDLE_HOVER` | `role=Role.HANDLE_HOVER` |
| `COL_BBOX` | `role=Role.BBOX` |
| `COL_CURSOR` | `role=Role.CURSOR` |
| `ISLAND_COLORS[i]` | `theme.island_palette[i % 8]` (passed as `color=`) |

- [ ] **Step 2: Update draw_3d_callback**

Open `operators/mesh_visual_uv.py` and find `def draw_3d_callback(op, context):`. Near the top of the function, add:

```python
    from ..ui.draw.theme import get_theme
    theme = get_theme(context)
```

(If `get_theme` is already imported at the file level, skip the inner import.)

Then for each callsite inside `draw_3d_callback`:

- **Island fills** — wherever `ISLAND_COLORS[i]` (or `island_col`) is passed as a color into a `batch_for_shader` or one of the helpers, replace with `theme.island_palette[i % 8]`. Pass it via the new `color=` kwarg to `_draw_polyline / _draw_circle / draw_prim.tris`.
- **Edges (`gpu`/`batch` direct draw of edge fills/lines)** — these are still using `shader_flat` / `shader_line` directly. Convert each `shader_*.uniform_float("color", COL_*)` + matching `batch.draw()` into a single call to `draw_prim.tris(...)` (for `'TRIS'`) or `draw_prim.edges_3d(...)` (for `'LINES'`). Pass the role per the mapping table.

Concretely: the existing code shape

```python
batch = batch_for_shader(shader_flat, 'TRIS', {"pos": pos_list})
shader_flat.bind()
shader_flat.uniform_float("color", island_col)
batch.draw(shader_flat)
```

becomes

```python
draw_prim.tris(pos_list, color=theme.island_palette[island_idx % 8],
               context=context)
```

And

```python
batch = batch_for_shader(shader_line, 'LINES', {"pos": ep})
shader_line.bind()
shader_line.uniform_float("viewportSize", (region.width, region.height))
shader_line.uniform_float("lineWidth", edge_w)
shader_line.uniform_float("color", edge_col)
batch.draw(shader_line)
```

becomes (when `edge_col` was `COL_EDGE_ACTIVE`):

```python
draw_prim.edges_3d(ep, role=Role.ACTIVE_LINE, context=context)
```

The `edge_w` width parameter was a custom value from prefs — the unified line width comes from the role's state. If the previous custom width really mattered, pass `width="active"` (or "locked", etc.) explicitly. Default behavior is fine.

- [ ] **Step 3: Update draw_pixel_callback**

Same approach for `def draw_pixel_callback(op, context):`. Add `theme = get_theme(context)` near the top. Replace each `_draw_circle/_draw_ring/_draw_polyline/_draw_diamond(..., COL_X)` call with the role= form per the mapping table.

For `COL_ROT_LINE` (the 0.35-alpha rotation guide line), pass an explicit color:

```python
pivot = theme.color_for(Role.PIVOT)
_draw_polyline([csp, rsp], color=(pivot[0], pivot[1], pivot[2], 0.35), width="default")
```

For axis feedback text inside `_draw_transform_feedback` (already migrated in an earlier session to `hud_text.draw(... role=Role.ERROR/SUCCESS)`), replace those role= calls with axis-color:

```python
from ..ui.draw.theme import axis_color
# ...
if op.grab_axis == 'X':
    _t(f"S X {sx:.3f}", color=axis_color('X'))
elif op.grab_axis == 'Y':
    _t(f"S Y {sy:.3f}", color=axis_color('Y'))
else:
    _t(f"S {sx:.3f} x {sy:.3f}", role=Role.ACTIVE_TEXT)
```

And update the inner `_t` helper to accept either `role=` or `color=`:

```python
def _t(text, *, role=None, color=None):
    hud_text_draw(text, mx + 18, my + 10, theme=theme,
                  role=role, color=color, size_token="active")
```

Apply the same role/color split to the `STATE_ROTATE` and `STATE_GRAB` branches: rotation still uses `Role.ACTIVE_TEXT`; X-axis grab/scale uses `color=axis_color('X')`; Y-axis grab/scale uses `color=axis_color('Y')`; neutral grab/scale uses `Role.ACTIVE_TEXT`.

- [ ] **Step 4: Smoke test — operator still registers, draw paths don't crash on invoke+cancel**

```python
import bpy, sys
ADDON = "InteractionOps"
bpy.ops.preferences.addon_disable(module=ADDON)
for name in list(sys.modules):
    if name == ADDON or name.startswith(ADDON + "."):
        del sys.modules[name]
bpy.ops.preferences.addon_enable(module=ADDON)
# Need a mesh in edit mode with at least one UV-island to invoke.
# Just check registration and presence of the bound operator.
result = {
    "ok": True,
    "visual_uv_op": hasattr(bpy.ops.iops, "mesh_visual_uv"),
}
```

Expected: `{"ok": true, "visual_uv_op": true}`. Live drag/UV-island test is a manual follow-up.

- [ ] **Step 5: Commit**

```bash
git add operators/mesh_visual_uv.py
git commit -m "refactor(visual_uv): map all hardcoded palettes to theme roles + island_palette"
```

---

## Task 12: Migrate mesh_shear color callsites

**Files:**
- Modify: `operators/mesh_shear.py:1750-2000` (the ~13 inline `shader.uniform_float("color", ...)` sites)

- [ ] **Step 1: Inventory callsites**

Run:

```
grep -nE 'uniform_float\("color"' operators/mesh_shear.py
```

You will see roughly 13 lines. The mapping for each color literal:

| Color literal | Role / source |
|---|---|
| `(1.0, 1.0, 1.0, 1.0)` | `role=Role.LINE` |
| `(1.0, 0.0, 0.0, 0.35)` | `role=Role.ERROR, alpha_mul=0.35` |
| `(1.0, 0.6, 0.1, 1.0)` | `role=Role.ACTIVE_LINE` / `role=Role.ACTIVE_POINT` (depending on whether the call draws lines or points — check the surrounding `batch_for_shader` mode) |
| `(0.45, 0.45, 0.45, 0.55)` | `role=Role.LINE` (alpha 0.55 is already baked in via the LINE default; if it isn't close enough, pass `color=(0.45, 0.45, 0.45, 0.55)` for the one-off) |
| `(1.0, 0.85, 0.3, 0.75)` | `role=Role.LOCKED_POINT, alpha_mul=0.75` |
| `(1.0, 0.85, 0.3, 1.0)` | `role=Role.LOCKED_POINT` |
| `(1.0, 0.9, 0.4, 1.0)` | `role=Role.LOCKED_POINT` |
| `(0.3, 0.55, 1.0, 0.75)` | `role=Role.CLOSEST_POINT, alpha_mul=0.75` |

Axis-aligned highlights (which currently use a literal X/Y color tied to the active axis) get `color=axis_color('X' or 'Y')`.

- [ ] **Step 2: Rewrite each callsite**

For each `shader.uniform_float("color", ...)` followed by `batch.draw(shader)`, replace the pair (plus the `batch_for_shader` that immediately precedes it) with the matching `draw_prim.{line,edges_3d,points,tris}` call. Use `draw_scope(blend="ALPHA")` once around any group of consecutive draws if not already wrapped.

Example transformation:

```python
# Before
batch = batch_for_shader(self.shader, "LINES", {"pos": segs})
self.shader.bind()
self.shader.uniform_float("color", (1.0, 0.6, 0.1, 1.0))
batch.draw(self.shader)
```

```python
# After
with draw_scope(blend="ALPHA"):
    draw_prim.edges_3d(segs, role=Role.ACTIVE_LINE, context=context)
```

For the alpha-multiplied roles, primitives doesn't currently expose `alpha_mul=` on its kwargs (only `hud_text.draw` does). For those cases, pass an explicit color:

```python
base = theme.color_for(Role.LOCKED_POINT)
draw_prim.points(pts, color=(base[0], base[1], base[2], base[3] * 0.75),
                 context=context)
```

For the two axis-X/axis-Y inline calls (search the shear code for axis branches that pick a red or green color), use:

```python
draw_prim.edges_3d(rails, color=axis_color('X'), context=context)
```

(Replace `'X'` with the active axis at that callsite.)

At the top of the file add (if not already there):

```python
from ..ui.draw import primitives as draw_prim, draw_scope, Role
from ..ui.draw.theme import axis_color, get_theme
```

And in `_draw_callback` (or whatever function owns the inline shader calls), near the top, add `theme = get_theme(context)` so the `theme.color_for(...)` lookups for alpha-mul cases are cheap.

- [ ] **Step 3: Drop the unified shader**

Once all inline `self.shader.uniform_float(...)` calls are removed, the line

```python
self.shader = gpu.shader.from_builtin("UNIFORM_COLOR")
```

in `invoke()` is dead. Remove it. Also remove the `import gpu` and `from gpu_extras.batch import batch_for_shader` imports **only if nothing else in the file uses them**. Verify with:

```
grep -nE '\bgpu\.|batch_for_shader' operators/mesh_shear.py
```

If the grep returns nothing, drop the imports. If it still finds matches, leave both imports in place.

- [ ] **Step 4: Smoke test**

```python
import bpy, sys
ADDON = "InteractionOps"
bpy.ops.preferences.addon_disable(module=ADDON)
for name in list(sys.modules):
    if name == ADDON or name.startswith(ADDON + "."):
        del sys.modules[name]
bpy.ops.preferences.addon_enable(module=ADDON)
result = {
    "ok": True,
    "shear_op": hasattr(bpy.ops.iops, "mesh_shear"),
}
```

Expected: `{"ok": true, "shear_op": true}`.

- [ ] **Step 5: Commit**

```bash
git add operators/mesh_shear.py
git commit -m "refactor(shear): map all inline shader colors to theme roles + axis_color"
```

---

## Task 13: Full live verification

**Files:** none (validation only)

- [ ] **Step 1: Full reload + op registration check**

```python
import bpy, sys
ADDON = "InteractionOps"
try:
    bpy.ops.preferences.addon_disable(module=ADDON)
except Exception as e:
    print("disable:", e)
for name in list(sys.modules):
    if name == ADDON or name.startswith(ADDON + "."):
        del sys.modules[name]
try:
    bpy.ops.preferences.addon_enable(module=ADDON)
    result = {"ok": True, "ops": {
        "visual_uv": hasattr(bpy.ops.iops, "mesh_visual_uv"),
        "shear": hasattr(bpy.ops.iops, "mesh_shear"),
        "bisect": hasattr(bpy.ops.iops, "mesh_cursor_bisect"),
    }}
except Exception as e:
    import traceback
    result = {"ok": False, "error": repr(e), "tb": traceback.format_exc()}
```

Expected: `{"ok": true, "ops": {"visual_uv": true, "shear": true, "bisect": true}}`. Any other shape is a regression.

- [ ] **Step 2: Verify no legacy COL_* / ISLAND_COLORS / hardcoded uniform_float colors remain in target files**

```
grep -nE 'COL_[A-Z]+\s*=|ISLAND_COLORS\s*=' operators/mesh_visual_uv.py
```

Expected: zero matches (the constants are gone).

```
grep -nE 'uniform_float\("color"' operators/mesh_shear.py
```

Expected: zero matches.

- [ ] **Step 3: Manual UI check (note for human)**

Open Blender Preferences → Add-ons → InteractionOps → Theme tab. Confirm:
- "Widgets" box with 5 swatches renders
- "Island palette (UV)" box with 8 swatches renders
- Changing a swatch and re-invoking Visual UV / Shear reflects the change

This is a human check, not automated. Note any issues; otherwise the migration is done.

- [ ] **Step 4: Commit (no-op if nothing left to stage)**

```bash
git status
# If clean, skip. If something was left out during the previous tasks, stage and commit it now.
```

---

## Self-Review

**Spec coverage:**
- ✅ Role enum additions → Task 1
- ✅ Theme.island_palette field → Task 2
- ✅ axis_color() helper → Task 3
- ✅ IOPS_Theme widget props → Task 4
- ✅ IOPS_Theme island_palette props → Task 5
- ✅ get_theme() plumbing → Task 6
- ✅ draw_theme_tab UI sections → Task 7
- ✅ hud_text.draw color= override → Task 8
- ✅ primitives color= override → Task 9
- ✅ mesh_visual_uv helpers → Task 10
- ✅ mesh_visual_uv callsites + axis colors → Task 11
- ✅ mesh_shear callsites → Task 12
- ✅ Full verification → Task 13

**Placeholder scan:** No "TBD"/"TODO"/"similar to". Every step has concrete code or commands.

**Type consistency:** `Role` enum names match the spec table exactly (`HANDLE`, `HANDLE_HOVER`, `PIVOT`, `BBOX`, `CURSOR`). `island_palette_0..7` naming matches between `prefs/theme.py` (Task 5) and `get_theme()` (Task 6). `axis_color()` signature matches in Task 3 (definition) and Task 11/12 (usage). `color=` parameter added to `hud_text.draw` (Task 8), `primitives.*` (Task 9), and both consumers (Tasks 11, 12).

**Open consideration:** Task 11's pre-existing axis-feedback `_t()` helper signature update — the agent may need to read the current state of `_draw_transform_feedback` to confirm the helper still looks the way it did in the last commit. If it diverged, fall back to inlining `hud_text.draw(... color=axis_color(...))` directly.
