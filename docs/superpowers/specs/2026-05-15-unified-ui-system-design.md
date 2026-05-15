# Unified UI System for InteractionOps Operators

**Date:** 2026-05-15
**Status:** Design — awaiting implementation plan

## Problem

Every modal operator in InteractionOps re-implements its own GPU drawing and HUD text:
`mesh_cursor_bisect`, `mesh_shear`, `mesh_straight_bevel`, `object_visual_origin`,
`mesh_visual_uv`, `object_align_to_face`, `drag_snap_*`, and others each contain
hundreds of lines of `gpu.shader.from_builtin(...)`, `batch_for_shader(...)`,
`gpu.state.*`, and `blf.*` boilerplate. Visual style, colors, line widths, point
sizes, and text layout drift between operators. Per-operator color properties
have proliferated in addon preferences (`cursor_bisect_*_color`,
`vo_cage_*_color`, `align_edge_color`, `text_color`, etc.), with no shared
source of truth.

## Goals

1. One minimalistic, consistent visual language across every operator.
2. GPU-based drawing with a single shared API.
3. HUD text showing key bindings and ON/OFF state via color/brightness
   (visual feedback only — no click handling).
4. HUD positioning: cursor-follow, four screen corners, or free XY with drag.
5. All visual settings live in one centralized theme inside addon preferences.
6. Full migration of every existing operator to the new system.
7. Code split into focused modules under `ui/draw/` and `ui/hud/`.

## Non-Goals

- Clickable HUD items (deferred; visual state feedback only for now).
- Animated transitions or easing.
- Per-operator visual overrides (theme is global; if an operator needs a
  visually distinct element, it adds a new semantic role to the theme).
- Backward compatibility with old per-operator color properties. A one-shot
  migration handler reads old values into the new theme on first load, then
  the old properties are removed.

## Architecture

A thin shared layer of stateless drawing helpers, a theme that resolves
semantic roles to concrete RGBA / sizes / widths, and a HUD overlay class
that operators instantiate. Operators keep ownership of their own
`SpaceView3D.draw_handler_add` lifecycle — they just delegate visual work to
the shared layer.

```
ui/
  __init__.py
  draw/
    __init__.py        # public API re-exports
    theme.py           # Theme dataclass, get_theme(prefs)
    shaders.py         # cached shader instances, custom POINT_DISC shader
    primitives.py      # line, polyline, points, tris, edges_3d, rect_2d
    state.py           # draw_scope context manager
  hud/
    __init__.py        # HUDOverlay (entry point, re-exports)
    items.py           # HUDItem, HUDSection dataclasses
    layout.py          # positioning math, drag handling
    text.py            # blf wrapper bound to theme
prefs/
  theme.py             # IOPS_Theme PropertyGroup + preview panel
  addon_preferences.py # existing; gains a Theme tab, loses old color props
```

### Modules and responsibilities

- **`ui/draw/theme.py`** — defines `Theme` (frozen dataclass) with all colors,
  sizes, widths, shadow params, and HUD layout settings. `get_theme(context)`
  reads from the `IOPS_Theme` PropertyGroup and returns a snapshot per draw
  call. `theme.resolve(role)` returns `(rgba, width, point_size)` tuples.

- **`ui/draw/shaders.py`** — lazily creates and caches shaders. Two builtins
  (`UNIFORM_COLOR`, `POLYLINE_UNIFORM_COLOR`) and one custom GLSL shader
  `POINT_DISC` that draws antialiased filled circles with a 1px ring at
  arbitrary screen size.

- **`ui/draw/primitives.py`** — stateless functions:
  `line(p1, p2, role, width=None)`,
  `polyline(coords, role, width=None)`,
  `points(coords, role, size=None)`,
  `tris(coords, role)`,
  `edges_3d(coord_pairs, role, width=None)`,
  `rect_2d(x, y, w, h, role)`.
  Each builds a `GPUBatch` and draws it. Role drives color and default sizes.

- **`ui/draw/state.py`** — `draw_scope(blend, depth, region=None)` context
  manager that pushes GPU state (`blend_set`, `depth_test_set`,
  `line_width_set`, `point_size_set`) and restores prior values on exit.
  Removes the manual cleanup pattern (`gpu.state.line_width_set(1.0)` etc.)
  scattered through current operators.

- **`ui/hud/text.py`** — `draw_text(font_id, text, x, y, role, size_token)`,
  shadow handling, dimensions helpers. All `blf.*` lives here.

- **`ui/hud/items.py`** — `HUDItem(label, key, state)` where `state ∈
  {"on", "off", "disabled"}`; `HUDSection(title, items)`.

- **`ui/hud/layout.py`** — given `mode`, region, mouse position, and content
  size, returns `(x, y)` for the HUD root. Implements edge clamping and the
  free-mode drag interaction. Drag state is operator-scoped.

- **`ui/hud/__init__.py`** — `HUDOverlay(operator_name)`:
  `.add_section(...)`, `.set_state(key, state)`, `.draw(context, event)`.
  Operators call `.draw()` from their pixel-space draw handler.

### Theme — semantic roles

Operators never pass raw colors. They pass a role.

| Role | Purpose | Default RGB | Default alpha |
|---|---|---|---|
| `primary` | active/selected element | `#4DD0FF` | 1.0 |
| `secondary` | passive/available element | `#888A8E` | 0.7 |
| `locked` | locked/frozen state | `#FFB84D` | 1.0 |
| `snap` | snap candidate | `#FFFFFF` | 0.6 |
| `snap_closest` | closest snap under cursor | `#4DFF9E` | 1.0 |
| `preview` | preview of result | `#4DD0FF` | 0.4 |
| `fill` | plane/area fill | `#4DD0FF` | 0.10 |
| `outline` | plane/area outline | `#4DD0FF` | 0.8 |
| `hint` | guides, crosshair | `#FFFFFF` | 0.25 |
| `error` | invalid operation | `#FF5A5A` | 1.0 |
| `success` | confirmed | `#4DFF9E` | 1.0 |

If a future operator needs a role not in this list, we add a new role to the
theme rather than passing a raw color.

### Lines and points

- Lines use `POLYLINE_UNIFORM_COLOR` for antialiased output regardless of MSAA.
- Width tokens: `normal = 1.5px`, `thick = 3.0px`, `preview = 2.0px`.
- Points are always rendered with the `POINT_DISC` shader: a filled disc with
  a 1px contrasting ring. Size tokens: `small = 6px`, `normal = 9px`,
  `large = 12px`.

### Text

- `font_id = 0` everywhere.
- Size tokens: `small = 11`, `normal = 12`, `title = 14`.
- Shadow always on with theme defaults (`blur = 3`, `offset = (1, -1)`,
  color `#000000 @ 0.7`); user can disable or retune from the Theme tab.

## HUD

### Items and state

```python
HUDItem(label="Lock axis", key="X", state="on")
HUDSection(title="Bisect", items=[...])
```

State drives only the label color:
- `on` → `theme.primary`
- `off` → `theme.secondary` at 0.7 alpha
- `disabled` → `theme.secondary` at 0.35 alpha

The key glyph is always rendered in `theme.primary` for legibility.

### Layout

The HUD is a vertical stack of sections; each section is `title` followed by
rows of `KEY  label`. Key column width is fixed (`theme.hud_key_column_width`)
so rows align.

Positioning modes (in `IOPS_Theme.hud_mode`):

- `cursor` — follow mouse with `(hud_offset_x, hud_offset_y)` (default
  `(20, -20)`); placement flips to the opposite side of the cursor near
  region edges to stay fully visible.
- `top_left`, `top_right`, `bottom_left`, `bottom_right` — pinned to a region
  corner with `hud_padding` inset.
- `free` — fixed `(hud_free_x, hud_free_y)` in region coordinates, draggable
  during operator: middle-mouse drag on the HUD body moves it and persists
  the new position to prefs.

Edge clamping always applied, regardless of mode.

## Preferences

A new `IOPS_Theme` PropertyGroup replaces the scattered per-operator color
properties. Removed properties (non-exhaustive):
`cursor_bisect_plane_color`, `cursor_bisect_plane_outline_color`,
`cursor_bisect_edge_color`, `cursor_bisect_edge_locked_color`,
`cursor_bisect_snap_color`, `cursor_bisect_snap_hold_color`,
`cursor_bisect_snap_closest_color`, `cursor_bisect_snap_closest_hold_color`,
`cursor_bisect_cut_preview_color`, `cursor_bisect_distance_text_color`,
`vo_cage_color`, `vo_cage_points_color`, `vo_cage_ap_color`,
`align_edge_color`, `text_color`, `text_color_key`, `text_shadow_color`,
`visual_uv_point_size`.

`IOPS_Theme` fields:

```
# semantic colors (FloatVectorProperty subtype='COLOR', size=4)
color_primary, color_secondary, color_locked, color_snap, color_snap_closest,
color_preview, color_fill, color_outline, color_hint, color_error, color_success

# sizes / widths
line_width_normal, line_width_thick, line_width_preview
point_size_small, point_size_normal, point_size_large
text_size_small, text_size_normal, text_size_title

# text shadow
shadow_enabled, shadow_color, shadow_blur, shadow_offset_x, shadow_offset_y

# HUD
hud_mode: EnumProperty("cursor", "top_left", "top_right", "bottom_left",
                       "bottom_right", "free")
hud_offset_x, hud_offset_y          # cursor + free
hud_free_x, hud_free_y              # free mode anchor (auto-updated by drag)
hud_padding                         # corner inset
hud_section_spacing
hud_row_spacing
hud_key_column_width

# behavior
depth_test_default: EnumProperty("LESS", "ALWAYS")
```

A new **Theme** tab in addon preferences exposes everything with a live
preview panel: a small region drawing one of each primitive and a sample HUD
so users see effects without launching an operator. A **Reset to defaults**
button restores factory values.

### Migration of old prefs

On addon enable, a one-shot migration reads old per-operator color
properties (if present in user prefs from a prior version) into the closest
theme role, then clears them. Mapping is documented in code next to the
migration function. After migration runs once, the old property declarations
are removed in a subsequent release.

## Operator integration

A modal operator's draw setup collapses to:

```python
from ui.draw import primitives as draw, draw_scope
from ui.hud import HUDOverlay, HUDItem, HUDSection

class IOPS_OT_example(bpy.types.Operator):
    def invoke(self, context, event):
        self.hud = HUDOverlay("example")
        self.hud.add_section(HUDSection("Modes", [
            HUDItem("Lock X", "X", "off"),
            HUDItem("Snap",   "S", "on"),
        ]))
        self._h_view = bpy.types.SpaceView3D.draw_handler_add(
            self._draw_view, (context,), 'WINDOW', 'POST_VIEW')
        self._h_px = bpy.types.SpaceView3D.draw_handler_add(
            self._draw_px, (context,), 'WINDOW', 'POST_PIXEL')
        ...

    def _draw_view(self, context):
        with draw_scope(blend="ALPHA", depth="ALWAYS"):
            draw.edges_3d(self.edges, role="locked")
            draw.points(self.snaps, role="snap")
            if self.closest:
                draw.points([self.closest], role="snap_closest", size="large")

    def _draw_px(self, context):
        self.hud.draw(context, self.last_event)

    def modal(self, context, event):
        self.last_event = event
        if event.type == 'X' and event.value == 'PRESS':
            self.hud.set_state("X", "on" if not self.lock_x else "off")
        ...
```

No GPU state cleanup, no shader instantiation, no color tuples, no
`blf.position/draw` calls in operator code.

## Migration order

Operators are migrated in this order — heaviest first, so the API gets
stressed early:

1. `mesh_cursor_bisect` (largest draw surface, most roles in use)
2. `mesh_shear`
3. `mesh_straight_bevel`
4. `object_visual_origin`
5. `mesh_visual_uv`
6. `object_align_to_face`
7. `drag_snap`, `drag_snap_cursor`, `drag_snap_uv`
8. Remaining operators with any GPU/BLF draw

Each migration in its own commit: remove operator-local color props, switch
to `draw.*` and `HUDOverlay`, delete dead helpers. Old per-operator color
property declarations stay registered (but unused) until the final
"cleanup" commit at the end of the migration sequence, so that a user mid-
upgrade does not lose stored values before the migration handler runs.

## Testing strategy

- Unit-testable parts (theme resolution, layout math, edge clamping) get
  pytest tests under `tests/ui/`.
- Visual parts get a manual checklist per operator: run operator, verify
  every drawn element appears with theme colors, every HUD item shows the
  correct state on key toggles, HUD repositions correctly in each
  `hud_mode`.
- A debug operator `iops.draw_theme_preview` renders one of every primitive
  + a sample HUD in the viewport so theme tweaks can be inspected without
  launching a real operator.

## Risks and trade-offs

- **Custom `POINT_DISC` shader** adds one piece of GLSL to maintain. The
  payoff is a consistent point style across the addon; the alternative
  (`gl_PointSize` + builtin) gives square or blurry points depending on
  driver.
- **Theme as a single global** means operators can't deviate. That is the
  point. New visual needs are met by adding a new role, not by overriding.
- **Migration of saved prefs** is one-shot and lossy: if a user had highly
  customized per-operator colors that don't map cleanly to a role, they
  collapse to the closest role. Acceptable because the goal is a unified
  look.
- **HUD drag in free mode** requires the operator to forward mouse events
  to `HUDOverlay`. Operators that consume every mouse event (drag-snap
  family) need a small carve-out: drag begins only when the click lands
  inside the HUD bounds.

## Open questions

None at design time. Implementation plan will resolve concrete shader source,
exact default numeric values after preview testing, and per-operator role
mappings.
