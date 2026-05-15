# Unified UI Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the shared `ui/draw/` + `ui/hud/` modules, the `IOPS_Theme` PropertyGroup, a debug preview operator, and migrate `mesh_cursor_bisect` as the proof case for the unified UI system designed in [2026-05-15-unified-ui-system-design.md](../specs/2026-05-15-unified-ui-system-design.md).

**Architecture:** Theme is the single source of truth (semantic roles → RGBA/sizes/widths). Stateless primitive helpers (`line`, `polyline`, `points`, `tris`, `edges_3d`, `rect_2d`) build batches against cached shaders. A `draw_scope` context manager handles GPU state push/restore. `HUDOverlay` composes `HUDSection`/`HUDItem` and renders via a `blf` wrapper with cursor/corner/free positioning.

**Tech Stack:** Blender Python API (`bpy`, `gpu`, `gpu_extras`, `blf`), GLSL for one custom `POINT_DISC` shader, pytest with `unittest.mock` for pure-Python unit tests, manual verification in Blender for GPU/HUD code.

**Out of scope (follow-up plans):**
- Migrating `mesh_shear`, `mesh_straight_bevel`, `object_visual_origin`, `mesh_visual_uv`, `object_align_to_face`, `drag_snap*`, remaining operators.
- Removing dead per-operator color properties after all operators are migrated.

---

## File Structure

**Created:**
- `ui/draw/__init__.py` — public API re-exports
- `ui/draw/theme.py` — `Theme` dataclass, `Role` enum, `get_theme(context)`
- `ui/draw/shaders.py` — shader cache + custom `POINT_DISC` shader source
- `ui/draw/state.py` — `draw_scope` context manager
- `ui/draw/primitives.py` — `line`, `polyline`, `points`, `tris`, `edges_3d`, `rect_2d`
- `ui/hud/__init__.py` — `HUDOverlay` re-export
- `ui/hud/items.py` — `HUDItem`, `HUDSection` dataclasses
- `ui/hud/layout.py` — positioning math, edge clamp, drag-state helpers
- `ui/hud/text.py` — `blf` wrapper bound to theme
- `ui/hud/overlay.py` — `HUDOverlay` class
- `prefs/theme.py` — `IOPS_Theme` PropertyGroup, theme tab UI, reset op
- `prefs/theme_migration.py` — one-shot migration of old per-op color props
- `operators/draw_theme_preview.py` — `IOPS_OT_DrawThemePreview` debug op
- `tests/conftest.py` — pytest fixtures with `bpy` mocked
- `tests/ui/__init__.py`
- `pytest.ini` — `--import-mode=importlib`

Note: do NOT create `tests/__init__.py`. The addon root has `__init__.py`,
so creating `tests/__init__.py` makes pytest resolve `tests` as a sub-package
of `InteractionOps` and tries to import the addon root before conftest mocks
load — which fails on `import bpy`. Modern pytest does not require it.
- `tests/ui/test_theme.py`
- `tests/ui/test_layout.py`
- `tests/ui/test_items.py`

**Modified:**
- `__init__.py` (addon root) — register `IOPS_Theme`, preview op, migration handler
- `prefs/addon_preferences.py` — add Theme tab, keep old props until cleanup plan
- `operators/mesh_cursor_bisect.py` — replace local draw code with shared API

**Note on imports:** This addon uses package-relative imports (`from .operators...`).
All new modules follow the same convention. From inside `operators/`, the import
is `from ..ui.draw import primitives as draw`.

---

## Task 1: Project test scaffolding

**Files:**
- Create: `tests/conftest.py`
- Create: `tests/ui/__init__.py`
- Create: `pytest.ini`

Do NOT create `tests/__init__.py` — see file structure note above.

- [ ] **Step 1: Create `pytest.ini`**

```ini
[pytest]
testpaths = tests
addopts = --import-mode=importlib
```

- [ ] **Step 2: Create `tests/ui/__init__.py`** (empty)

```python
```

- [ ] **Step 3: Create `tests/conftest.py` with `bpy` mock**

```python
import sys
from unittest.mock import MagicMock

# Mock bpy / gpu / blf so pure-Python modules can import without Blender.
for name in ("bpy", "bpy.types", "bpy.props", "bpy.utils",
             "gpu", "gpu.shader", "gpu.state", "gpu.types",
             "gpu_extras", "gpu_extras.batch", "blf", "mathutils"):
    sys.modules.setdefault(name, MagicMock())
```

- [ ] **Step 4: Verify pytest discovers the directory**

Run: `pytest tests/ -v --collect-only`
Expected: `no tests ran` (no test functions yet, but no collection errors).

- [ ] **Step 5: Commit**

```bash
git add tests/ pytest.ini
git commit -m "test: add pytest scaffolding with bpy mocks for ui tests"
```

---

## Task 2: Theme dataclass and Role enum

**Files:**
- Create: `ui/__init__.py`
- Create: `ui/draw/__init__.py`
- Create: `ui/draw/theme.py`
- Test: `tests/ui/test_theme.py`

- [ ] **Step 1: Create empty `ui/__init__.py` and `ui/draw/__init__.py`**

```python
```

- [ ] **Step 2: Write the failing test**

`tests/ui/test_theme.py`:

```python
from ui.draw.theme import Theme, Role, DEFAULT_THEME


def test_default_theme_has_every_role():
    for role in Role:
        rgba = DEFAULT_THEME.color_for(role)
        assert len(rgba) == 4
        assert all(0.0 <= c <= 1.0 for c in rgba)


def test_default_theme_primary_is_cyan_full_alpha():
    r, g, b, a = DEFAULT_THEME.color_for(Role.PRIMARY)
    assert a == 1.0
    assert b > r and b > g  # cyan-ish: blue dominant


def test_width_token_resolution():
    assert DEFAULT_THEME.width("normal") == 1.5
    assert DEFAULT_THEME.width("thick") == 3.0
    assert DEFAULT_THEME.width("preview") == 2.0


def test_point_size_token_resolution():
    assert DEFAULT_THEME.point_size("small") == 6.0
    assert DEFAULT_THEME.point_size("normal") == 9.0
    assert DEFAULT_THEME.point_size("large") == 12.0


def test_text_size_token_resolution():
    assert DEFAULT_THEME.text_size("small") == 11
    assert DEFAULT_THEME.text_size("normal") == 12
    assert DEFAULT_THEME.text_size("title") == 14


def test_unknown_token_raises():
    import pytest
    with pytest.raises(KeyError):
        DEFAULT_THEME.width("ridiculous")
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/ui/test_theme.py -v`
Expected: FAIL — `ui.draw.theme` does not exist.

- [ ] **Step 4: Write `ui/draw/theme.py`**

```python
from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum


class Role(Enum):
    PRIMARY = "primary"
    SECONDARY = "secondary"
    LOCKED = "locked"
    SNAP = "snap"
    SNAP_CLOSEST = "snap_closest"
    PREVIEW = "preview"
    FILL = "fill"
    OUTLINE = "outline"
    HINT = "hint"
    ERROR = "error"
    SUCCESS = "success"


_DEFAULT_COLORS: dict[Role, tuple[float, float, float, float]] = {
    Role.PRIMARY:      (0.302, 0.816, 1.000, 1.00),  # #4DD0FF
    Role.SECONDARY:    (0.533, 0.541, 0.557, 0.70),  # #888A8E
    Role.LOCKED:       (1.000, 0.722, 0.302, 1.00),  # #FFB84D
    Role.SNAP:         (1.000, 1.000, 1.000, 0.60),
    Role.SNAP_CLOSEST: (0.302, 1.000, 0.620, 1.00),  # #4DFF9E
    Role.PREVIEW:      (0.302, 0.816, 1.000, 0.40),
    Role.FILL:         (0.302, 0.816, 1.000, 0.10),
    Role.OUTLINE:      (0.302, 0.816, 1.000, 0.80),
    Role.HINT:         (1.000, 1.000, 1.000, 0.25),
    Role.ERROR:        (1.000, 0.353, 0.353, 1.00),  # #FF5A5A
    Role.SUCCESS:      (0.302, 1.000, 0.620, 1.00),
}

_DEFAULT_WIDTHS = {"normal": 1.5, "thick": 3.0, "preview": 2.0}
_DEFAULT_POINT_SIZES = {"small": 6.0, "normal": 9.0, "large": 12.0}
_DEFAULT_TEXT_SIZES = {"small": 11, "normal": 12, "title": 14}


@dataclass(frozen=True)
class HUDSettings:
    mode: str = "cursor"            # cursor|top_left|top_right|bottom_left|bottom_right|free
    offset_x: int = 20
    offset_y: int = -20
    free_x: int = 40
    free_y: int = 40
    padding: int = 12
    section_spacing: int = 8
    row_spacing: int = 2
    key_column_width: int = 60


@dataclass(frozen=True)
class ShadowSettings:
    enabled: bool = True
    color: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.7)
    blur: int = 3
    offset_x: int = 1
    offset_y: int = -1


@dataclass(frozen=True)
class Theme:
    colors: dict[Role, tuple[float, float, float, float]] = field(
        default_factory=lambda: dict(_DEFAULT_COLORS))
    widths: dict[str, float] = field(
        default_factory=lambda: dict(_DEFAULT_WIDTHS))
    point_sizes: dict[str, float] = field(
        default_factory=lambda: dict(_DEFAULT_POINT_SIZES))
    text_sizes: dict[str, int] = field(
        default_factory=lambda: dict(_DEFAULT_TEXT_SIZES))
    shadow: ShadowSettings = field(default_factory=ShadowSettings)
    hud: HUDSettings = field(default_factory=HUDSettings)
    depth_test_default: str = "LESS"

    def color_for(self, role: Role) -> tuple[float, float, float, float]:
        return self.colors[role]

    def width(self, token: str) -> float:
        return self.widths[token]

    def point_size(self, token: str) -> float:
        return self.point_sizes[token]

    def text_size(self, token: str) -> int:
        return self.text_sizes[token]


DEFAULT_THEME = Theme()
```

- [ ] **Step 5: Run tests to verify pass**

Run: `pytest tests/ui/test_theme.py -v`
Expected: 6 passed.

- [ ] **Step 6: Commit**

```bash
git add ui/__init__.py ui/draw/__init__.py ui/draw/theme.py tests/ui/test_theme.py
git commit -m "feat(ui/draw): Theme dataclass and Role enum"
```

---

## Task 3: `get_theme(context)` reading from prefs

**Files:**
- Modify: `ui/draw/theme.py` (add `get_theme`)
- Test: `tests/ui/test_theme.py` (add)

- [ ] **Step 1: Add the failing test**

Append to `tests/ui/test_theme.py`:

```python
from unittest.mock import MagicMock


def _fake_context_with_theme_prefs():
    ctx = MagicMock()
    t = ctx.preferences.addons["InteractionOps"].preferences.iops_theme
    t.color_primary = (0.1, 0.2, 0.3, 0.4)
    t.color_secondary = (0.5, 0.5, 0.5, 0.7)
    t.color_locked = (1.0, 0.7, 0.3, 1.0)
    t.color_snap = (1.0, 1.0, 1.0, 0.6)
    t.color_snap_closest = (0.3, 1.0, 0.6, 1.0)
    t.color_preview = (0.3, 0.8, 1.0, 0.4)
    t.color_fill = (0.3, 0.8, 1.0, 0.1)
    t.color_outline = (0.3, 0.8, 1.0, 0.8)
    t.color_hint = (1.0, 1.0, 1.0, 0.25)
    t.color_error = (1.0, 0.35, 0.35, 1.0)
    t.color_success = (0.3, 1.0, 0.6, 1.0)
    t.line_width_normal = 1.5
    t.line_width_thick = 3.0
    t.line_width_preview = 2.0
    t.point_size_small = 6.0
    t.point_size_normal = 9.0
    t.point_size_large = 12.0
    t.text_size_small = 11
    t.text_size_normal = 12
    t.text_size_title = 14
    t.shadow_enabled = True
    t.shadow_color = (0.0, 0.0, 0.0, 0.7)
    t.shadow_blur = 3
    t.shadow_offset_x = 1
    t.shadow_offset_y = -1
    t.hud_mode = "cursor"
    t.hud_offset_x = 20
    t.hud_offset_y = -20
    t.hud_free_x = 40
    t.hud_free_y = 40
    t.hud_padding = 12
    t.hud_section_spacing = 8
    t.hud_row_spacing = 2
    t.hud_key_column_width = 60
    t.depth_test_default = "LESS"
    return ctx


def test_get_theme_returns_default_when_prefs_missing():
    from ui.draw.theme import get_theme, DEFAULT_THEME
    ctx = MagicMock()
    ctx.preferences.addons.__getitem__.side_effect = KeyError
    theme = get_theme(ctx)
    assert theme.color_for(Role.PRIMARY) == DEFAULT_THEME.color_for(Role.PRIMARY)


def test_get_theme_reads_from_prefs():
    from ui.draw.theme import get_theme
    ctx = _fake_context_with_theme_prefs()
    theme = get_theme(ctx)
    assert theme.color_for(Role.PRIMARY) == (0.1, 0.2, 0.3, 0.4)
    assert theme.width("normal") == 1.5
    assert theme.hud.mode == "cursor"
    assert theme.shadow.blur == 3
```

- [ ] **Step 2: Run tests — expect failure**

Run: `pytest tests/ui/test_theme.py -v`
Expected: 2 new tests fail (no `get_theme`).

- [ ] **Step 3: Add `get_theme` to `ui/draw/theme.py`**

Append to the file:

```python
def get_theme(context) -> Theme:
    try:
        t = context.preferences.addons["InteractionOps"].preferences.iops_theme
    except (KeyError, AttributeError):
        return DEFAULT_THEME

    return Theme(
        colors={
            Role.PRIMARY:      tuple(t.color_primary),
            Role.SECONDARY:    tuple(t.color_secondary),
            Role.LOCKED:       tuple(t.color_locked),
            Role.SNAP:         tuple(t.color_snap),
            Role.SNAP_CLOSEST: tuple(t.color_snap_closest),
            Role.PREVIEW:      tuple(t.color_preview),
            Role.FILL:         tuple(t.color_fill),
            Role.OUTLINE:      tuple(t.color_outline),
            Role.HINT:         tuple(t.color_hint),
            Role.ERROR:        tuple(t.color_error),
            Role.SUCCESS:      tuple(t.color_success),
        },
        widths={
            "normal":  t.line_width_normal,
            "thick":   t.line_width_thick,
            "preview": t.line_width_preview,
        },
        point_sizes={
            "small":  t.point_size_small,
            "normal": t.point_size_normal,
            "large":  t.point_size_large,
        },
        text_sizes={
            "small":  t.text_size_small,
            "normal": t.text_size_normal,
            "title":  t.text_size_title,
        },
        shadow=ShadowSettings(
            enabled=bool(t.shadow_enabled),
            color=tuple(t.shadow_color),
            blur=int(t.shadow_blur),
            offset_x=int(t.shadow_offset_x),
            offset_y=int(t.shadow_offset_y),
        ),
        hud=HUDSettings(
            mode=str(t.hud_mode),
            offset_x=int(t.hud_offset_x),
            offset_y=int(t.hud_offset_y),
            free_x=int(t.hud_free_x),
            free_y=int(t.hud_free_y),
            padding=int(t.hud_padding),
            section_spacing=int(t.hud_section_spacing),
            row_spacing=int(t.hud_row_spacing),
            key_column_width=int(t.hud_key_column_width),
        ),
        depth_test_default=str(t.depth_test_default),
    )
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/ui/test_theme.py -v`
Expected: 8 passed.

- [ ] **Step 5: Commit**

```bash
git add ui/draw/theme.py tests/ui/test_theme.py
git commit -m "feat(ui/draw): get_theme reads IOPS_Theme PropertyGroup into Theme snapshot"
```

---

## Task 4: Shader cache and custom POINT_DISC shader

**Files:**
- Create: `ui/draw/shaders.py`

This module touches `gpu.shader` which is mocked at unit-test time; verification
is via the preview operator in Task 12.

- [ ] **Step 1: Write `ui/draw/shaders.py`**

```python
"""Shader cache for the unified UI draw layer.

Three shaders:
- UNIFORM_COLOR — builtin, used for filled tris and simple lines
- POLYLINE_UNIFORM_COLOR — builtin, antialiased lines independent of MSAA
- POINT_DISC — custom: antialiased filled disc with 1px contrasting ring
"""
from __future__ import annotations
import gpu


_POINT_DISC_VS = """
in vec2 pos;
uniform mat4 ModelViewProjectionMatrix;
uniform float pointSize;
void main() {
    gl_Position = ModelViewProjectionMatrix * vec4(pos, 0.0, 1.0);
    gl_PointSize = pointSize;
}
"""

_POINT_DISC_FS = """
out vec4 fragColor;
uniform vec4 color;
uniform vec4 ringColor;
uniform float pointSize;
void main() {
    vec2 uv = gl_PointCoord * 2.0 - 1.0;
    float d = length(uv);
    float radius = 1.0;
    float ring_inner = 1.0 - (2.0 / max(pointSize, 2.0));
    float aa = fwidth(d) * 1.5;
    if (d > radius) discard;
    float fill_a = 1.0 - smoothstep(ring_inner - aa, ring_inner, d);
    float ring_a = smoothstep(ring_inner - aa, ring_inner, d) *
                   (1.0 - smoothstep(radius - aa, radius, d));
    fragColor = color * fill_a + ringColor * ring_a;
}
"""


_cache: dict[str, object] = {}


def uniform_color():
    s = _cache.get("UNIFORM_COLOR")
    if s is None:
        s = gpu.shader.from_builtin("UNIFORM_COLOR")
        _cache["UNIFORM_COLOR"] = s
    return s


def polyline_uniform_color():
    s = _cache.get("POLYLINE_UNIFORM_COLOR")
    if s is None:
        s = gpu.shader.from_builtin("POLYLINE_UNIFORM_COLOR")
        _cache["POLYLINE_UNIFORM_COLOR"] = s
    return s


def point_disc():
    s = _cache.get("POINT_DISC")
    if s is None:
        s = gpu.types.GPUShader(_POINT_DISC_VS, _POINT_DISC_FS)
        _cache["POINT_DISC"] = s
    return s


def reset_cache():
    _cache.clear()
```

- [ ] **Step 2: Commit**

```bash
git add ui/draw/shaders.py
git commit -m "feat(ui/draw): shader cache with custom POINT_DISC shader"
```

---

## Task 5: `draw_scope` context manager

**Files:**
- Create: `ui/draw/state.py`
- Test: `tests/ui/test_state.py`

- [ ] **Step 1: Write the failing test**

`tests/ui/test_state.py`:

```python
from unittest.mock import patch, MagicMock


def test_draw_scope_sets_and_restores_state():
    with patch("ui.draw.state.gpu") as mock_gpu:
        from ui.draw.state import draw_scope
        with draw_scope(blend="ALPHA", depth="ALWAYS",
                        line_width=2.5, point_size=10.0):
            pass
    calls = [c[0] for c in mock_gpu.state.blend_set.call_args_list]
    # entered with ALPHA, exited with restore value
    assert calls[0] == ("ALPHA",)


def test_draw_scope_omits_unset_params():
    with patch("ui.draw.state.gpu") as mock_gpu:
        from ui.draw.state import draw_scope
        with draw_scope(blend="ALPHA"):
            pass
    mock_gpu.state.line_width_set.assert_not_called()
    mock_gpu.state.point_size_set.assert_not_called()
    mock_gpu.state.depth_test_set.assert_not_called()
```

- [ ] **Step 2: Run — expect failure**

Run: `pytest tests/ui/test_state.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Write `ui/draw/state.py`**

```python
"""GPU state context manager.

`draw_scope` sets requested GPU state on enter and restores on exit. Only
params that are not None are touched, so callers don't pay for state changes
they don't need.

Note: Blender's `gpu.state` has setters but no getters for blend/depth modes.
We restore to documented defaults ('NONE' / 'LESS' / 1.0 / 1.0) which matches
the implicit baseline Blender uses outside addon draw handlers.
"""
from __future__ import annotations
from contextlib import contextmanager
import gpu


@contextmanager
def draw_scope(blend: str | None = None,
               depth: str | None = None,
               line_width: float | None = None,
               point_size: float | None = None):
    if blend is not None:
        gpu.state.blend_set(blend)
    if depth is not None:
        gpu.state.depth_test_set(depth)
    if line_width is not None:
        gpu.state.line_width_set(line_width)
    if point_size is not None:
        gpu.state.point_size_set(point_size)
    try:
        yield
    finally:
        if line_width is not None:
            gpu.state.line_width_set(1.0)
        if point_size is not None:
            gpu.state.point_size_set(1.0)
        if depth is not None:
            gpu.state.depth_test_set("LESS")
        if blend is not None:
            gpu.state.blend_set("NONE")
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/ui/test_state.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add ui/draw/state.py tests/ui/test_state.py
git commit -m "feat(ui/draw): draw_scope context manager for GPU state push/restore"
```

---

## Task 6: Primitive helpers

**Files:**
- Create: `ui/draw/primitives.py`
- Modify: `ui/draw/__init__.py`

GPU code can't be unit-tested without Blender. Verification happens via the
preview operator in Task 12.

- [ ] **Step 1: Write `ui/draw/primitives.py`**

```python
"""Stateless drawing primitives bound to the theme.

Each function:
1. Resolves the requested role to RGBA via the theme.
2. Selects the correct cached shader.
3. Builds a one-shot GPUBatch and draws it.

Callers wrap calls in `draw_scope(...)` to control blend/depth state.
"""
from __future__ import annotations
from typing import Sequence

import gpu
from gpu_extras.batch import batch_for_shader

from . import shaders
from .theme import Role, Theme, get_theme


def _resolve_theme(theme: Theme | None, context) -> Theme:
    return theme if theme is not None else get_theme(context)


def line(p1, p2, *, role: Role, width: str = "normal",
         theme: Theme | None = None, context=None) -> None:
    polyline([p1, p2], role=role, width=width, theme=theme, context=context)


def polyline(coords: Sequence, *, role: Role, width: str = "normal",
             theme: Theme | None = None, context=None) -> None:
    th = _resolve_theme(theme, context)
    shader = shaders.polyline_uniform_color()
    batch = batch_for_shader(shader, "LINE_STRIP", {"pos": list(coords)})
    shader.bind()
    shader.uniform_float("color", th.color_for(role))
    shader.uniform_float("lineWidth", th.width(width))
    shader.uniform_float("viewportSize", gpu.state.viewport_get()[2:])
    batch.draw(shader)


def edges_3d(coord_pairs: Sequence, *, role: Role, width: str = "normal",
             theme: Theme | None = None, context=None) -> None:
    """Disjoint line segments: coord_pairs is a flat list [a, b, c, d, ...]
    where (a,b), (c,d), ... are segments."""
    th = _resolve_theme(theme, context)
    shader = shaders.polyline_uniform_color()
    batch = batch_for_shader(shader, "LINES", {"pos": list(coord_pairs)})
    shader.bind()
    shader.uniform_float("color", th.color_for(role))
    shader.uniform_float("lineWidth", th.width(width))
    shader.uniform_float("viewportSize", gpu.state.viewport_get()[2:])
    batch.draw(shader)


def points(coords: Sequence, *, role: Role, size: str = "normal",
           ring_role: Role | None = None,
           theme: Theme | None = None, context=None) -> None:
    th = _resolve_theme(theme, context)
    shader = shaders.point_disc()
    batch = batch_for_shader(shader, "POINTS", {"pos": list(coords)})
    fill = th.color_for(role)
    ring = th.color_for(ring_role) if ring_role is not None else (
        max(1.0 - fill[0], 0.0), max(1.0 - fill[1], 0.0),
        max(1.0 - fill[2], 0.0), fill[3])
    px = th.point_size(size)
    shader.bind()
    shader.uniform_float("color", fill)
    shader.uniform_float("ringColor", ring)
    shader.uniform_float("pointSize", px)
    gpu.state.point_size_set(px)
    batch.draw(shader)


def tris(coords: Sequence, *, role: Role,
         theme: Theme | None = None, context=None) -> None:
    th = _resolve_theme(theme, context)
    shader = shaders.uniform_color()
    batch = batch_for_shader(shader, "TRIS", {"pos": list(coords)})
    shader.bind()
    shader.uniform_float("color", th.color_for(role))
    batch.draw(shader)


def rect_2d(x: float, y: float, w: float, h: float, *, role: Role,
            theme: Theme | None = None, context=None) -> None:
    coords = [(x, y), (x + w, y), (x + w, y + h),
              (x, y), (x + w, y + h), (x, y + h)]
    tris(coords, role=role, theme=theme, context=context)
```

- [ ] **Step 2: Update `ui/draw/__init__.py` to expose public API**

```python
from .theme import Theme, Role, get_theme, DEFAULT_THEME
from .state import draw_scope
from . import primitives
from . import shaders

__all__ = ["Theme", "Role", "get_theme", "DEFAULT_THEME",
           "draw_scope", "primitives", "shaders"]
```

- [ ] **Step 3: Commit**

```bash
git add ui/draw/primitives.py ui/draw/__init__.py
git commit -m "feat(ui/draw): primitives (line, polyline, edges_3d, points, tris, rect_2d)"
```

---

## Task 7: HUD items dataclasses

**Files:**
- Create: `ui/hud/__init__.py`
- Create: `ui/hud/items.py`
- Test: `tests/ui/test_items.py`

- [ ] **Step 1: Write the failing test**

`tests/ui/test_items.py`:

```python
from ui.hud.items import HUDItem, HUDSection, ItemState


def test_item_defaults():
    item = HUDItem(label="Lock", key="X")
    assert item.state is ItemState.OFF


def test_section_holds_items_in_order():
    a = HUDItem("A", "A")
    b = HUDItem("B", "B")
    s = HUDSection("modes", [a, b])
    assert s.items == [a, b]
    assert s.title == "modes"


def test_state_transitions():
    item = HUDItem("Snap", "S", state=ItemState.ON)
    assert item.state is ItemState.ON
    item.state = ItemState.DISABLED
    assert item.state is ItemState.DISABLED
```

- [ ] **Step 2: Run — expect failure**

Run: `pytest tests/ui/test_items.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Create empty `ui/hud/__init__.py`**

```python
```

- [ ] **Step 4: Write `ui/hud/items.py`**

```python
from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum


class ItemState(Enum):
    ON = "on"
    OFF = "off"
    DISABLED = "disabled"


@dataclass
class HUDItem:
    label: str
    key: str
    state: ItemState = ItemState.OFF


@dataclass
class HUDSection:
    title: str
    items: list[HUDItem] = field(default_factory=list)
```

- [ ] **Step 5: Run — expect pass**

Run: `pytest tests/ui/test_items.py -v`
Expected: 3 passed.

- [ ] **Step 6: Commit**

```bash
git add ui/hud/__init__.py ui/hud/items.py tests/ui/test_items.py
git commit -m "feat(ui/hud): HUDItem, HUDSection, ItemState dataclasses"
```

---

## Task 8: HUD layout math

**Files:**
- Create: `ui/hud/layout.py`
- Test: `tests/ui/test_layout.py`

- [ ] **Step 1: Write the failing test**

`tests/ui/test_layout.py`:

```python
from ui.hud.layout import compute_origin, clamp_to_region


def _region(w=1920, h=1080):
    class R:
        width = w
        height = h
    return R()


def test_corner_top_left():
    x, y = compute_origin("top_left", region=_region(), mouse=(0, 0),
                          content_size=(200, 100), padding=12,
                          offset=(0, 0), free=(0, 0))
    assert x == 12
    assert y == 1080 - 12 - 100  # top-left origin = top of region minus content


def test_corner_bottom_right():
    x, y = compute_origin("bottom_right", region=_region(), mouse=(0, 0),
                          content_size=(200, 100), padding=12,
                          offset=(0, 0), free=(0, 0))
    assert x == 1920 - 200 - 12
    assert y == 12


def test_cursor_follow_default_offset():
    x, y = compute_origin("cursor", region=_region(), mouse=(500, 500),
                          content_size=(200, 100), padding=12,
                          offset=(20, -20), free=(0, 0))
    assert x == 520
    assert y == 380  # 500 - 20 - content_h(100) + base? actual: y = mouse_y + offset_y - h


def test_free_uses_free_coords():
    x, y = compute_origin("free", region=_region(), mouse=(0, 0),
                          content_size=(200, 100), padding=12,
                          offset=(0, 0), free=(300, 400))
    assert (x, y) == (300, 400)


def test_clamp_keeps_hud_inside_region():
    # Off-screen top-right
    x, y = clamp_to_region(2000, 1200, content_size=(200, 100),
                           region=_region(), padding=4)
    assert x + 200 <= 1920 - 4
    assert y + 100 <= 1080 - 4


def test_clamp_keeps_hud_off_negative_corners():
    x, y = clamp_to_region(-50, -50, content_size=(200, 100),
                           region=_region(), padding=4)
    assert x >= 4
    assert y >= 4
```

- [ ] **Step 2: Run — expect failure**

Run: `pytest tests/ui/test_layout.py -v`

- [ ] **Step 3: Write `ui/hud/layout.py`**

```python
from __future__ import annotations
from typing import Tuple


def compute_origin(mode: str, *, region, mouse: Tuple[int, int],
                   content_size: Tuple[int, int], padding: int,
                   offset: Tuple[int, int],
                   free: Tuple[int, int]) -> Tuple[int, int]:
    """Return (x, y) bottom-left origin of the HUD block in region coords."""
    cw, ch = content_size
    rw, rh = region.width, region.height
    mx, my = mouse
    ox, oy = offset

    if mode == "top_left":
        return padding, rh - padding - ch
    if mode == "top_right":
        return rw - cw - padding, rh - padding - ch
    if mode == "bottom_left":
        return padding, padding
    if mode == "bottom_right":
        return rw - cw - padding, padding
    if mode == "free":
        return clamp_to_region(free[0], free[1], (cw, ch), region, padding)
    # cursor
    x = mx + ox
    y = my + oy - ch  # offset_y is negative by default → HUD above-right of cursor
    return clamp_to_region(x, y, (cw, ch), region, padding)


def clamp_to_region(x: int, y: int, content_size, region, padding: int):
    cw, ch = content_size
    x = max(padding, min(int(x), region.width - cw - padding))
    y = max(padding, min(int(y), region.height - ch - padding))
    return x, y


class DragState:
    """Tracks a free-mode drag in progress."""
    def __init__(self):
        self.active = False
        self.grab_dx = 0
        self.grab_dy = 0

    def begin(self, mouse_xy, hud_origin):
        self.active = True
        self.grab_dx = mouse_xy[0] - hud_origin[0]
        self.grab_dy = mouse_xy[1] - hud_origin[1]

    def update(self, mouse_xy):
        return (mouse_xy[0] - self.grab_dx,
                mouse_xy[1] - self.grab_dy)

    def end(self):
        self.active = False


def is_inside(x: int, y: int, origin, size) -> bool:
    return (origin[0] <= x <= origin[0] + size[0] and
            origin[1] <= y <= origin[1] + size[1])
```

- [ ] **Step 4: Run — expect pass**

Run: `pytest tests/ui/test_layout.py -v`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add ui/hud/layout.py tests/ui/test_layout.py
git commit -m "feat(ui/hud): layout math, edge clamp, free-mode drag state"
```

---

## Task 9: HUD text wrapper

**Files:**
- Create: `ui/hud/text.py`

Pure Blender API; verified via preview operator.

- [ ] **Step 1: Write `ui/hud/text.py`**

```python
"""Thin blf wrapper bound to the theme.

All BLF calls in the addon should route through this module so font size,
shadow, and color stay consistent.
"""
from __future__ import annotations
import blf

from ..draw.theme import Theme, Role


def configure(theme: Theme, size_token: str = "normal", font_id: int = 0):
    blf.size(font_id, theme.text_size(size_token))
    if theme.shadow.enabled:
        blf.enable(font_id, blf.SHADOW)
        sc = theme.shadow.color
        blf.shadow(font_id, theme.shadow.blur, sc[0], sc[1], sc[2], sc[3])
        blf.shadow_offset(font_id, theme.shadow.offset_x, theme.shadow.offset_y)
    else:
        blf.disable(font_id, blf.SHADOW)


def draw(text: str, x: int, y: int, *, theme: Theme, role: Role,
         size_token: str = "normal", font_id: int = 0, alpha_mul: float = 1.0):
    configure(theme, size_token, font_id)
    r, g, b, a = theme.color_for(role)
    blf.color(font_id, r, g, b, a * alpha_mul)
    blf.position(font_id, x, y, 0)
    blf.draw(font_id, text)


def measure(text: str, *, theme: Theme, size_token: str = "normal",
            font_id: int = 0):
    configure(theme, size_token, font_id)
    return blf.dimensions(font_id, text)
```

- [ ] **Step 2: Commit**

```bash
git add ui/hud/text.py
git commit -m "feat(ui/hud): blf wrapper bound to theme"
```

---

## Task 10: HUDOverlay class

**Files:**
- Create: `ui/hud/overlay.py`
- Modify: `ui/hud/__init__.py`

- [ ] **Step 1: Write `ui/hud/overlay.py`**

```python
"""HUDOverlay — composes sections and items, computes layout, draws via blf.

State color rules (from spec):
- ItemState.ON       → primary
- ItemState.OFF      → secondary @ alpha * 0.7
- ItemState.DISABLED → secondary @ alpha * 0.35

Key glyph is always rendered in `primary` for legibility.
"""
from __future__ import annotations
from typing import Iterable

from ..draw.theme import Role, get_theme
from . import text as hud_text
from .items import HUDItem, HUDSection, ItemState
from .layout import (compute_origin, DragState, is_inside)


_STATE_ALPHA = {
    ItemState.ON: 1.0,
    ItemState.OFF: 0.7,
    ItemState.DISABLED: 0.35,
}
_STATE_ROLE = {
    ItemState.ON: Role.PRIMARY,
    ItemState.OFF: Role.SECONDARY,
    ItemState.DISABLED: Role.SECONDARY,
}


class HUDOverlay:
    def __init__(self, operator_name: str):
        self.operator_name = operator_name
        self.sections: list[HUDSection] = []
        self._items_by_key: dict[str, HUDItem] = {}
        self._drag = DragState()
        self._last_origin = (0, 0)
        self._last_size = (0, 0)

    def add_section(self, section: HUDSection) -> None:
        self.sections.append(section)
        for it in section.items:
            self._items_by_key[it.key] = it

    def set_state(self, key: str, state: ItemState | str) -> None:
        if key not in self._items_by_key:
            return
        if isinstance(state, str):
            state = ItemState(state)
        self._items_by_key[key].state = state

    def _measure(self, theme) -> tuple[int, int]:
        max_w = 0
        h = 0
        title_h = theme.text_size("title")
        row_h = theme.text_size("normal")
        for i, sec in enumerate(self.sections):
            if i > 0:
                h += theme.hud.section_spacing
            if sec.title:
                tw, _ = hud_text.measure(sec.title, theme=theme,
                                         size_token="title")
                max_w = max(max_w, int(tw))
                h += title_h + theme.hud.row_spacing
            for it in sec.items:
                row = f"{it.key}    {it.label}"
                rw, _ = hud_text.measure(row, theme=theme,
                                         size_token="normal")
                max_w = max(max_w, int(rw))
                h += row_h + theme.hud.row_spacing
        return max_w, h

    def draw(self, context, event=None) -> None:
        if not self.sections:
            return
        theme = get_theme(context)
        region = context.region
        size = self._measure(theme)
        self._last_size = size
        mouse = (0, 0)
        if event is not None:
            mouse = (event.mouse_region_x, event.mouse_region_y)
        if self._drag.active and event is not None:
            new = self._drag.update(mouse)
            free = (int(new[0]), int(new[1]))
        else:
            free = (theme.hud.free_x, theme.hud.free_y)
        origin = compute_origin(
            theme.hud.mode, region=region, mouse=mouse,
            content_size=size, padding=theme.hud.padding,
            offset=(theme.hud.offset_x, theme.hud.offset_y), free=free)
        self._last_origin = origin
        self._render(theme, origin, size)

    def _render(self, theme, origin, size) -> None:
        x0, y0 = origin
        _, h = size
        y = y0 + h  # top of block
        title_h = theme.text_size("title")
        row_h = theme.text_size("normal")
        key_col_w = theme.hud.key_column_width
        for i, sec in enumerate(self.sections):
            if i > 0:
                y -= theme.hud.section_spacing
            if sec.title:
                y -= title_h
                hud_text.draw(sec.title, x0, y, theme=theme,
                              role=Role.PRIMARY, size_token="title")
                y -= theme.hud.row_spacing
            for it in sec.items:
                y -= row_h
                # Key glyph
                hud_text.draw(it.key, x0, y, theme=theme,
                              role=Role.PRIMARY, size_token="normal")
                # Label
                label_role = _STATE_ROLE[it.state]
                label_alpha = _STATE_ALPHA[it.state]
                hud_text.draw(it.label, x0 + key_col_w, y, theme=theme,
                              role=label_role, size_token="normal",
                              alpha_mul=label_alpha)
                y -= theme.hud.row_spacing

    # Drag support (free mode)
    def try_begin_drag(self, mouse_xy) -> bool:
        if is_inside(mouse_xy[0], mouse_xy[1],
                     self._last_origin, self._last_size):
            self._drag.begin(mouse_xy, self._last_origin)
            return True
        return False

    def end_drag(self, context) -> None:
        if not self._drag.active:
            return
        self._drag.end()
        try:
            prefs = context.preferences.addons["InteractionOps"].preferences
            prefs.iops_theme.hud_free_x = int(self._last_origin[0])
            prefs.iops_theme.hud_free_y = int(self._last_origin[1])
        except (KeyError, AttributeError):
            pass
```

- [ ] **Step 2: Re-export from `ui/hud/__init__.py`**

```python
from .items import HUDItem, HUDSection, ItemState
from .overlay import HUDOverlay

__all__ = ["HUDItem", "HUDSection", "ItemState", "HUDOverlay"]
```

- [ ] **Step 3: Commit**

```bash
git add ui/hud/overlay.py ui/hud/__init__.py
git commit -m "feat(ui/hud): HUDOverlay composes sections and draws via blf"
```

---

## Task 11: `IOPS_Theme` PropertyGroup

**Files:**
- Create: `prefs/theme.py`
- Modify: `prefs/addon_preferences.py`

- [ ] **Step 1: Read existing `prefs/addon_preferences.py` to confirm where to register IOPS_Theme**

Run: open and inspect `prefs/addon_preferences.py:1-100` to find the
`AddonPreferences` class declaration and existing PointerProperty usage.

- [ ] **Step 2: Write `prefs/theme.py`**

```python
import bpy
from bpy.props import (BoolProperty, EnumProperty, FloatProperty,
                       FloatVectorProperty, IntProperty)


def _color(default, name=""):
    return FloatVectorProperty(name=name, subtype="COLOR", size=4,
                               min=0.0, max=1.0, default=default)


class IOPS_Theme(bpy.types.PropertyGroup):
    # Semantic colors
    color_primary:      _color((0.302, 0.816, 1.000, 1.00), "Primary")
    color_secondary:    _color((0.533, 0.541, 0.557, 0.70), "Secondary")
    color_locked:       _color((1.000, 0.722, 0.302, 1.00), "Locked")
    color_snap:         _color((1.000, 1.000, 1.000, 0.60), "Snap")
    color_snap_closest: _color((0.302, 1.000, 0.620, 1.00), "Snap closest")
    color_preview:      _color((0.302, 0.816, 1.000, 0.40), "Preview")
    color_fill:         _color((0.302, 0.816, 1.000, 0.10), "Fill")
    color_outline:      _color((0.302, 0.816, 1.000, 0.80), "Outline")
    color_hint:         _color((1.000, 1.000, 1.000, 0.25), "Hint")
    color_error:        _color((1.000, 0.353, 0.353, 1.00), "Error")
    color_success:      _color((0.302, 1.000, 0.620, 1.00), "Success")

    # Widths & sizes
    line_width_normal:  FloatProperty(name="Line normal",  default=1.5, min=0.5, max=8.0)
    line_width_thick:   FloatProperty(name="Line thick",   default=3.0, min=0.5, max=12.0)
    line_width_preview: FloatProperty(name="Line preview", default=2.0, min=0.5, max=8.0)
    point_size_small:   FloatProperty(name="Point small",  default=6.0, min=2.0, max=32.0)
    point_size_normal:  FloatProperty(name="Point normal", default=9.0, min=2.0, max=32.0)
    point_size_large:   FloatProperty(name="Point large",  default=12.0, min=2.0, max=48.0)
    text_size_small:    IntProperty(name="Text small",  default=11, min=8, max=64)
    text_size_normal:   IntProperty(name="Text normal", default=12, min=8, max=64)
    text_size_title:    IntProperty(name="Text title",  default=14, min=8, max=72)

    # Shadow
    shadow_enabled:  BoolProperty(name="Shadow", default=True)
    shadow_color:    _color((0.0, 0.0, 0.0, 0.7), "Shadow color")
    shadow_blur:     IntProperty(name="Blur", default=3, min=0, max=10)
    shadow_offset_x: IntProperty(name="Offset X", default=1, min=-8, max=8)
    shadow_offset_y: IntProperty(name="Offset Y", default=-1, min=-8, max=8)

    # HUD
    hud_mode: EnumProperty(
        name="HUD position",
        items=[
            ("cursor",       "Cursor",       "Follow mouse cursor"),
            ("top_left",     "Top left",     ""),
            ("top_right",    "Top right",    ""),
            ("bottom_left",  "Bottom left",  ""),
            ("bottom_right", "Bottom right", ""),
            ("free",         "Free",         "Fixed position (draggable in op)"),
        ],
        default="cursor",
    )
    hud_offset_x: IntProperty(name="Cursor offset X", default=20)
    hud_offset_y: IntProperty(name="Cursor offset Y", default=-20)
    hud_free_x: IntProperty(name="Free X", default=40, min=0)
    hud_free_y: IntProperty(name="Free Y", default=40, min=0)
    hud_padding: IntProperty(name="Padding", default=12, min=0, max=64)
    hud_section_spacing: IntProperty(name="Section spacing", default=8, min=0, max=64)
    hud_row_spacing: IntProperty(name="Row spacing", default=2, min=0, max=16)
    hud_key_column_width: IntProperty(name="Key column width", default=60, min=20, max=240)

    # Behaviour
    depth_test_default: EnumProperty(
        name="Depth test",
        items=[("LESS", "Less", ""), ("ALWAYS", "Always", "")],
        default="LESS",
    )


class IOPS_OT_ThemeResetDefaults(bpy.types.Operator):
    bl_idname = "iops.theme_reset_defaults"
    bl_label = "Reset Theme to Defaults"
    bl_description = "Restore all theme values to defaults"
    bl_options = {"REGISTER"}

    def execute(self, context):
        prefs = context.preferences.addons["InteractionOps"].preferences
        t = prefs.iops_theme
        # Clearing each property via property_unset triggers default re-init.
        for prop_name in t.bl_rna.properties.keys():
            if prop_name in {"name", "rna_type"}:
                continue
            t.property_unset(prop_name)
        return {"FINISHED"}


def draw_theme_tab(layout, theme):
    box = layout.box()
    box.label(text="Colors")
    grid = box.grid_flow(columns=2, even_columns=True, align=True)
    for prop in ("color_primary", "color_secondary", "color_locked",
                 "color_snap", "color_snap_closest", "color_preview",
                 "color_fill", "color_outline", "color_hint",
                 "color_error", "color_success"):
        grid.prop(theme, prop)

    box = layout.box()
    box.label(text="Lines, points, text")
    col = box.column(align=True)
    col.prop(theme, "line_width_normal")
    col.prop(theme, "line_width_thick")
    col.prop(theme, "line_width_preview")
    col.separator()
    col.prop(theme, "point_size_small")
    col.prop(theme, "point_size_normal")
    col.prop(theme, "point_size_large")
    col.separator()
    col.prop(theme, "text_size_small")
    col.prop(theme, "text_size_normal")
    col.prop(theme, "text_size_title")

    box = layout.box()
    box.label(text="Shadow")
    col = box.column(align=True)
    col.prop(theme, "shadow_enabled")
    sub = col.column(align=True)
    sub.active = theme.shadow_enabled
    sub.prop(theme, "shadow_color")
    sub.prop(theme, "shadow_blur")
    sub.prop(theme, "shadow_offset_x")
    sub.prop(theme, "shadow_offset_y")

    box = layout.box()
    box.label(text="HUD")
    col = box.column(align=True)
    col.prop(theme, "hud_mode")
    col.prop(theme, "hud_offset_x")
    col.prop(theme, "hud_offset_y")
    col.prop(theme, "hud_padding")
    col.prop(theme, "hud_section_spacing")
    col.prop(theme, "hud_row_spacing")
    col.prop(theme, "hud_key_column_width")

    box = layout.box()
    box.label(text="Behaviour")
    box.prop(theme, "depth_test_default")

    layout.separator()
    row = layout.row()
    row.operator("iops.theme_reset_defaults", icon="LOOP_BACK")
    row.operator("iops.draw_theme_preview",  icon="HIDE_OFF")


classes = (IOPS_Theme, IOPS_OT_ThemeResetDefaults)
```

- [ ] **Step 3: Modify `prefs/addon_preferences.py` to register the theme**

Locate the `AddonPreferences` subclass (likely `IOPS_Preferences`). Add the
property and the tab. Concretely:

At the top of the file with other imports, add:
```python
from .theme import IOPS_Theme, draw_theme_tab
```

In the `AddonPreferences` class body, add the pointer:
```python
    iops_theme: bpy.props.PointerProperty(type=IOPS_Theme)
```

In the `draw(self, context)` method, find where existing tabs are rendered
and add a new tab branch:
```python
        if self.prefs_tabs == "THEME":
            draw_theme_tab(layout, self.iops_theme)
```

Locate the `prefs_tabs` EnumProperty definition and add the entry:
```python
            ("THEME", "Theme", "Unified UI theme"),
```

If there is no `prefs_tabs` enum (the file uses a different tab mechanism),
add a new collapsible section using `layout.box()` titled "Theme" that calls
`draw_theme_tab(box, self.iops_theme)`.

- [ ] **Step 4: Register classes in addon root**

In `__init__.py`, find the `classes = (...)` tuple (or equivalent
registration site) and add `IOPS_Theme` and `IOPS_OT_ThemeResetDefaults`
**before** the `AddonPreferences` subclass is registered (PointerProperty
needs its target class registered first):

```python
from .prefs.theme import classes as theme_classes
# ... in register(): for cls in theme_classes: bpy.utils.register_class(cls)
# ... in unregister(): for cls in reversed(theme_classes): bpy.utils.unregister_class(cls)
```

- [ ] **Step 5: Verify enable/disable doesn't crash**

In Blender via the blender-mcp skill, run:

```python
import bpy
bpy.ops.preferences.addon_disable(module="InteractionOps")
bpy.ops.preferences.addon_enable(module="InteractionOps")
prefs = bpy.context.preferences.addons["InteractionOps"].preferences
assert hasattr(prefs, "iops_theme")
print(tuple(prefs.iops_theme.color_primary))
```

Expected: prints `(0.302, 0.816, 1.0, 1.0)` (with small float rounding).

- [ ] **Step 6: Commit**

```bash
git add prefs/theme.py prefs/addon_preferences.py __init__.py
git commit -m "feat(prefs): IOPS_Theme PropertyGroup + Theme tab + reset op"
```

---

## Task 12: Debug preview operator

**Files:**
- Create: `operators/draw_theme_preview.py`
- Modify: `__init__.py`

- [ ] **Step 1: Write `operators/draw_theme_preview.py`**

```python
"""IOPS_OT_DrawThemePreview — modal preview of all theme primitives + HUD.

Run from preferences "Theme" tab. Renders one of each primitive in the
viewport and a sample HUD. ESC or right-click to exit.
"""
import bpy

from ..ui.draw import primitives as draw, draw_scope, Role
from ..ui.hud import HUDOverlay, HUDSection, HUDItem, ItemState


class IOPS_OT_DrawThemePreview(bpy.types.Operator):
    bl_idname = "iops.draw_theme_preview"
    bl_label = "Preview Theme"
    bl_description = "Modal preview of all unified UI primitives"
    bl_options = {"REGISTER"}

    def invoke(self, context, event):
        self._build_geometry(context)
        self._build_hud()
        self._last_event = event
        self._h_view = bpy.types.SpaceView3D.draw_handler_add(
            self._draw_view, (context,), "WINDOW", "POST_VIEW")
        self._h_px = bpy.types.SpaceView3D.draw_handler_add(
            self._draw_px, (context,), "WINDOW", "POST_PIXEL")
        context.window_manager.modal_handler_add(self)
        context.area.tag_redraw()
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        self._last_event = event
        context.area.tag_redraw()
        if event.type in {"ESC", "RIGHTMOUSE"} and event.value == "PRESS":
            self._cleanup()
            return {"FINISHED"}
        if event.type == "S" and event.value == "PRESS":
            self.hud.set_state("S",
                ItemState.ON if self.hud._items_by_key["S"].state is ItemState.OFF
                else ItemState.OFF)
        return {"PASS_THROUGH"}

    def _cleanup(self):
        bpy.types.SpaceView3D.draw_handler_remove(self._h_view, "WINDOW")
        bpy.types.SpaceView3D.draw_handler_remove(self._h_px,   "WINDOW")

    def _build_geometry(self, context):
        from mathutils import Vector
        c = context.scene.cursor.location
        self.edges = [
            c + Vector((-1, 0, 0)), c + Vector((1, 0, 0)),
            c + Vector((0, -1, 0)), c + Vector((0, 1, 0)),
        ]
        self.snaps = [c + Vector((1, 1, 0)), c + Vector((-1, 1, 0)),
                      c + Vector((1, -1, 0))]
        self.closest = c + Vector((-1, -1, 0))
        self.preview = [c + Vector((-1.5, 0, 0)), c + Vector((1.5, 0, 0))]

    def _build_hud(self):
        self.hud = HUDOverlay("theme_preview")
        self.hud.add_section(HUDSection("Theme preview", [
            HUDItem("Toggle snap",    "S", ItemState.OFF),
            HUDItem("Locked example", "L", ItemState.ON),
            HUDItem("Disabled item",  "D", ItemState.DISABLED),
            HUDItem("Exit",           "ESC", ItemState.ON),
        ]))

    def _draw_view(self, context):
        with draw_scope(blend="ALPHA", depth="ALWAYS",
                        line_width=context.preferences.addons[
                            "InteractionOps"].preferences.iops_theme.line_width_normal):
            draw.edges_3d(self.edges,   role=Role.LOCKED)
            draw.polyline(self.preview, role=Role.PREVIEW, width="preview")
            draw.points(self.snaps,     role=Role.SNAP)
            draw.points([self.closest], role=Role.SNAP_CLOSEST, size="large")

    def _draw_px(self, context):
        self.hud.draw(context, self._last_event)


classes = (IOPS_OT_DrawThemePreview,)
```

- [ ] **Step 2: Register in `__init__.py`**

Import and add to the registration tuple:
```python
from .operators.draw_theme_preview import IOPS_OT_DrawThemePreview
```
Add `IOPS_OT_DrawThemePreview` to the existing `classes` tuple (or
equivalent registration list).

- [ ] **Step 3: Run in Blender via blender-mcp**

```python
import bpy
bpy.ops.preferences.addon_disable(module="InteractionOps")
bpy.ops.preferences.addon_enable(module="InteractionOps")
# Hover viewport then call:
bpy.ops.iops.draw_theme_preview('INVOKE_DEFAULT')
```

Visually verify in the running Blender:
- Cross of locked-amber lines around 3D cursor
- Three white snap points at corners (top-left/top-right/bottom-right of cross)
- One large green disc at bottom-left (snap_closest)
- One translucent cyan polyline through the cross (preview)
- HUD near cursor showing: title "Theme preview", four rows with state colors
- Pressing `S` toggles its label brightness; ESC exits cleanly.

- [ ] **Step 4: Commit**

```bash
git add operators/draw_theme_preview.py __init__.py
git commit -m "feat(operators): debug IOPS_OT_DrawThemePreview for live theme inspection"
```

---

## Task 13: One-shot migration of old per-operator color prefs

**Files:**
- Create: `prefs/theme_migration.py`
- Modify: `__init__.py` (call from `register()`)

- [ ] **Step 1: Write `prefs/theme_migration.py`**

```python
"""One-shot migration of legacy per-operator color/size prefs into IOPS_Theme.

Runs exactly once per addon enable. Reads any of the legacy properties that
still exist on AddonPreferences and copies them into the closest theme role.
Sets a marker property `theme_migrated_v1 = True` so we don't run twice.

Mapping (legacy → role):
- cursor_bisect_edge_color        → color_primary (active edge)
- cursor_bisect_edge_locked_color → color_locked
- cursor_bisect_snap_color        → color_snap
- cursor_bisect_snap_closest_color→ color_snap_closest
- cursor_bisect_cut_preview_color → color_preview
- cursor_bisect_plane_color       → color_fill
- cursor_bisect_plane_outline_color → color_outline
- vo_cage_color                   → color_outline
- vo_cage_points_color            → color_secondary
- vo_cage_ap_color                → color_primary
- align_edge_color                → color_primary
- text_color                      → color_secondary
- text_color_key                  → color_primary
- text_shadow_color               → shadow_color
- visual_uv_point_size            → point_size_normal
"""
from __future__ import annotations
import bpy


_COLOR_MAP = {
    "cursor_bisect_edge_color":          "color_primary",
    "cursor_bisect_edge_locked_color":   "color_locked",
    "cursor_bisect_snap_color":          "color_snap",
    "cursor_bisect_snap_closest_color":  "color_snap_closest",
    "cursor_bisect_cut_preview_color":   "color_preview",
    "cursor_bisect_plane_color":         "color_fill",
    "cursor_bisect_plane_outline_color": "color_outline",
    "vo_cage_color":                     "color_outline",
    "vo_cage_points_color":              "color_secondary",
    "vo_cage_ap_color":                  "color_primary",
    "align_edge_color":                  "color_primary",
    "text_color":                        "color_secondary",
    "text_color_key":                    "color_primary",
    "text_shadow_color":                 "shadow_color",
}
_SCALAR_MAP = {
    "visual_uv_point_size": "point_size_normal",
}
_MARKER = "theme_migrated_v1"


def run_if_needed():
    try:
        prefs = bpy.context.preferences.addons["InteractionOps"].preferences
    except KeyError:
        return
    if getattr(prefs, _MARKER, False):
        return
    theme = prefs.iops_theme
    for legacy, role in _COLOR_MAP.items():
        if hasattr(prefs, legacy):
            try:
                setattr(theme, role, tuple(getattr(prefs, legacy)))
            except (TypeError, ValueError):
                pass
    for legacy, role in _SCALAR_MAP.items():
        if hasattr(prefs, legacy):
            try:
                setattr(theme, role, float(getattr(prefs, legacy)))
            except (TypeError, ValueError):
                pass
    try:
        setattr(prefs, _MARKER, True)
    except AttributeError:
        # Marker property not declared yet — declare in addon prefs next release.
        pass
```

- [ ] **Step 2: Declare the marker property in `AddonPreferences`**

In `prefs/addon_preferences.py` add inside the `AddonPreferences` class:
```python
    theme_migrated_v1: bpy.props.BoolProperty(default=False)
```

- [ ] **Step 3: Call migration from `register()` in `__init__.py`**

In the `register()` function, after all class registration is done:
```python
from .prefs.theme_migration import run_if_needed as _migrate_theme_v1
# ... after registrations:
_migrate_theme_v1()
```

- [ ] **Step 4: Verify in Blender**

Via blender-mcp:
```python
import bpy
prefs = bpy.context.preferences.addons["InteractionOps"].preferences
prefs.theme_migrated_v1 = False     # force re-run
bpy.ops.preferences.addon_disable(module="InteractionOps")
bpy.ops.preferences.addon_enable(module="InteractionOps")
assert prefs.theme_migrated_v1 is True
print(tuple(prefs.iops_theme.color_primary))
```

Expected: `theme_migrated_v1` is True, primary color is whatever the legacy
mapping pulled in (or default if no legacy values were customised).

- [ ] **Step 5: Commit**

```bash
git add prefs/theme_migration.py prefs/addon_preferences.py __init__.py
git commit -m "feat(prefs): one-shot migration of legacy per-op colors into IOPS_Theme"
```

---

## Task 14: Migrate `mesh_cursor_bisect` to unified UI

**Files:**
- Modify: `operators/mesh_cursor_bisect.py`

`mesh_cursor_bisect` is the heaviest draw in the addon (~500 lines of GPU/BLF
code). Migrating it proves the API.

- [ ] **Step 1: Map legacy roles**

Identify in the current file (read it section-by-section if too large):
- bisect plane fill → `Role.FILL`
- bisect plane outline → `Role.OUTLINE`
- edges (unlocked) → `Role.PRIMARY`
- edges (locked) → `Role.LOCKED`
- snap points → `Role.SNAP`
- snap point hold → `Role.HINT`
- closest snap → `Role.SNAP_CLOSEST`
- closest snap hold → `Role.PRIMARY`
- cut preview lines → `Role.PREVIEW`
- distance text → `Role.PRIMARY` (size_token "small")
- new/fresh edges from cut → `Role.SUCCESS`
- fill preview lines → `Role.PREVIEW`

- [ ] **Step 2: Replace draw imports**

At the top of `operators/mesh_cursor_bisect.py`, remove:
```python
import gpu
import blf
from gpu_extras.batch import batch_for_shader
```

Replace with:
```python
from ..ui.draw import primitives as draw, draw_scope, Role
from ..ui.hud import HUDOverlay, HUDSection, HUDItem, ItemState
```

- [ ] **Step 3: Replace each gpu/blf block**

For every block that currently does:
```python
shader = gpu.shader.from_builtin('UNIFORM_COLOR')
batch = batch_for_shader(shader, '<MODE>', {"pos": coords})
shader.bind()
shader.uniform_float("color", <some_color>)
gpu.state.blend_set('ALPHA')
gpu.state.line_width_set(N)
batch.draw(shader)
gpu.state.line_width_set(1.0)
gpu.state.blend_set('NONE')
```

…rewrite as:
```python
with draw_scope(blend="ALPHA", depth="ALWAYS"):
    draw.edges_3d(coords, role=Role.LOCKED, width="thick")
```

(Pick the correct primitive: `edges_3d` for `LINES`, `polyline` for
`LINE_STRIP`, `points` for `POINTS`, `tris` for `TRIS`/`TRI_FAN`.)

Concretely, work through every match in
[mesh_cursor_bisect.py:2050-2282](../../operators/mesh_cursor_bisect.py#L2050-L2282)
and the text block at [mesh_cursor_bisect.py:1922-1958](../../operators/mesh_cursor_bisect.py#L1922-L1958).

- [ ] **Step 4: Replace HUD text loop with HUDOverlay**

The block at [mesh_cursor_bisect.py:1922-1958](../../operators/mesh_cursor_bisect.py#L1922-L1958)
walks lines of `(action, key)` tuples and calls blf for each. Replace with a
HUDOverlay built in `invoke()`:

```python
self.hud = HUDOverlay("cursor_bisect")
self.hud.add_section(HUDSection("Bisect", [
    HUDItem("Lock plane", "SPACE", ItemState.OFF),
    HUDItem("Snap",        "S",     ItemState.OFF),
    HUDItem("Mark sharp",  "M",     ItemState.OFF),
    # ...all existing rows
]))
```

In modal, on every state change (`event.type == 'S' and event.value == 'PRESS'`),
call `self.hud.set_state("S", ItemState.ON if ... else ItemState.OFF)`.

In the pixel draw handler replace the manual blf loop with:
```python
self.hud.draw(context, self._last_event)
```

(Store `self._last_event = event` at the top of `modal()`.)

- [ ] **Step 5: Remove operator-local cleanup of GPU state**

Delete any remaining `gpu.state.line_width_set(1.0)`, `blend_set('NONE')`,
`depth_test_set('LESS')`, `point_size_set(1.0)` lines — `draw_scope` handles
restoration.

- [ ] **Step 6: Verify in Blender via blender-mcp**

```python
import bpy
bpy.ops.preferences.addon_disable(module="InteractionOps")
bpy.ops.preferences.addon_enable(module="InteractionOps")
# Set up a mesh + cursor, then:
bpy.ops.iops.cursor_bisect('INVOKE_DEFAULT')
```

Manual checklist (run the operator and confirm each visually):
- [ ] Bisect plane visible with theme `fill` color and `outline` border
- [ ] Edge highlight changes colour between primary and locked when toggled
- [ ] Snap points render with theme `snap` color; closest one stands out in `snap_closest`
- [ ] Cut preview renders in theme `preview` with `preview` line width
- [ ] HUD shows section title + rows; toggling a key changes only the affected row's label brightness
- [ ] HUD respects `hud_mode` setting (test `cursor`, `top_right`, `free`)
- [ ] No GPU state bleed-through after operator exits (other addons / viewport unaffected)

- [ ] **Step 7: Commit**

```bash
git add operators/mesh_cursor_bisect.py
git commit -m "refactor(mesh_cursor_bisect): migrate to unified UI (draw + HUDOverlay)"
```

---

## Task 15: Run all tests + final smoke

- [ ] **Step 1: Run full test suite**

Run: `pytest tests/ -v`
Expected: All tests pass.

- [ ] **Step 2: Smoke-check in Blender**

Via blender-mcp:
```python
import bpy
bpy.ops.preferences.addon_disable(module="InteractionOps")
bpy.ops.preferences.addon_enable(module="InteractionOps")
bpy.ops.iops.draw_theme_preview('INVOKE_DEFAULT')
# ESC out, then:
bpy.ops.iops.cursor_bisect('INVOKE_DEFAULT')
# ESC out.
```

Both must run without console errors and exit cleanly.

- [ ] **Step 3: Final commit if any docstring/lint touch-ups needed**

```bash
git add -p
git commit -m "chore(ui): final polish after smoke testing"
```

---

## Follow-up plans (not in scope here)

After this plan lands, each remaining operator gets its own short migration
plan following the exact pattern of Task 14:

- `2026-MM-DD-migrate-mesh-shear-to-unified-ui.md`
- `2026-MM-DD-migrate-mesh-straight-bevel-to-unified-ui.md`
- `2026-MM-DD-migrate-object-visual-origin-to-unified-ui.md`
- `2026-MM-DD-migrate-mesh-visual-uv-to-unified-ui.md`
- `2026-MM-DD-migrate-object-align-to-face-to-unified-ui.md`
- `2026-MM-DD-migrate-drag-snap-family-to-unified-ui.md`
- `2026-MM-DD-remove-legacy-per-op-color-prefs.md` (final cleanup)
