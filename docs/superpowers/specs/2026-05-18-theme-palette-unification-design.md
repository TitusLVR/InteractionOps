# Theme palette unification: visual_uv & shear → unified theme

**Status:** Draft
**Date:** 2026-05-18
**Branch:** `feat/unified-ui-foundation`

## Problem

After the unified HUD/draw migration, two operators still carry hardcoded color palettes:

- **`mesh_visual_uv.py`** — 14 `COL_*` constants + an 8-color `ISLAND_COLORS` palette
- **`mesh_shear.py`** — ~13 inline `shader.uniform_float("color", (r,g,b,a))` calls

These colors fall into four semantic groups:

1. **State-like** (selected / active / hover / align / preview) — already covered by the 5-state Line/Point/Text model
2. **Identity** (8 island ID colors) — not state, pure identification
3. **Axis feedback** (X / Y / Z highlight) — semantically tied to Blender's built-in axis colors
4. **Widgets** (handles, pivot, bbox, UV cursor) — neither state nor identity, but reusable across operators

Goal: pull all four groups into `IOPS_Theme` so users can restyle the whole addon from one place, and so future operators have a vocabulary instead of inventing new hardcoded colors.

## Design

### Role enum additions

`ui/draw/theme.py` gains 5 new roles in the "utility / surface" group:

```python
class Role(Enum):
    ...
    HANDLE        = "handle"          # neutral corner/mid diamond
    HANDLE_HOVER  = "handle_hover"    # handle under cursor
    PIVOT         = "pivot"           # pivot center + rotation handle
    BBOX          = "bbox"            # selection bounding box
    CURSOR        = "cursor"          # UV/2D cursor marker
```

Defaults derived from the existing hardcoded constants:

```python
Role.HANDLE:        (1.000, 1.000, 1.000, 0.85),
Role.HANDLE_HOVER:  (1.000, 0.850, 0.000, 1.00),
Role.PIVOT:         (1.000, 1.000, 1.000, 0.80),
Role.BBOX:          (0.650, 0.650, 0.650, 0.30),
Role.CURSOR:        (1.000, 0.200, 0.600, 1.00),
```

### Theme dataclass: island palette

`Theme` (`ui/draw/theme.py`) gains an immutable 8-tuple:

```python
@dataclass(frozen=True)
class Theme:
    ...
    island_palette: tuple[tuple[float, float, float, float], ...] = ()
```

Defaults match the current `ISLAND_COLORS` in `mesh_visual_uv.py`.

Consumers index by `island_idx % 8`. The `% 8` happens at the call site, not in the theme — keeps the theme dumb.

### Axis colors: live from Blender theme

No prefs for axis colors. A helper in `ui/draw/theme.py`:

```python
def axis_color(axis: str) -> tuple[float, float, float, float]:
    """Return Blender's built-in axis_x/y/z with alpha=1.0.
    Falls back to red/green/blue if user_interface theme is unavailable
    (e.g. headless contexts)."""
    try:
        ui = bpy.context.preferences.themes[0].user_interface
        src = {"X": ui.axis_x, "Y": ui.axis_y, "Z": ui.axis_z}[axis]
        return (src[0], src[1], src[2], 1.0)
    except (KeyError, AttributeError, IndexError):
        return {
            "X": (1.0, 0.27, 0.27, 1.0),
            "Y": (0.27, 0.75, 0.27, 1.0),
            "Z": (0.27, 0.27, 1.00, 1.0),
        }[axis]
```

Called fresh each frame — Blender's user_interface theme can change at runtime.

### IOPS_Theme PropertyGroup additions

`prefs/theme.py` adds:

```python
# --- Widgets ---
color_handle:        _color((1.000, 1.000, 1.000, 0.85), "Handle")
color_handle_hover:  _color((1.000, 0.850, 0.000, 1.00), "Handle (hover)")
color_pivot:         _color((1.000, 1.000, 1.000, 0.80), "Pivot")
color_bbox:          _color((0.650, 0.650, 0.650, 0.30), "Selection bbox")
color_cursor:        _color((1.000, 0.200, 0.600, 1.00), "Cursor (2D)")

# --- Island palette (per-island identification, indexed by island_id % 8) ---
island_palette_0: _color((0.40, 0.65, 1.00, 0.50), "Island 1")
island_palette_1: _color((1.00, 0.50, 0.30, 0.50), "Island 2")
island_palette_2: _color((0.35, 0.85, 0.45, 0.50), "Island 3")
island_palette_3: _color((0.95, 0.80, 0.25, 0.50), "Island 4")
island_palette_4: _color((0.70, 0.40, 0.90, 0.50), "Island 5")
island_palette_5: _color((0.20, 0.80, 0.75, 0.50), "Island 6")
island_palette_6: _color((0.90, 0.35, 0.60, 0.50), "Island 7")
island_palette_7: _color((0.60, 0.80, 0.20, 0.50), "Island 8")
```

`get_theme()` reads all of these into the `Theme` instance.

### Theme tab UI (prefs/theme.py `draw_theme_tab`)

New "Widgets" section after "Surfaces & status":

```
┌─ Widgets ────────────────────────┐
│ Handle           [color]         │
│ Handle (hover)   [color]         │
│ Pivot            [color]         │
│ Selection bbox   [color]         │
│ Cursor (2D)      [color]         │
└──────────────────────────────────┘
```

New "Island palette" section (separate box, horizontal layout):

```
┌─ Island palette ─────────────────┐
│ [1][2][3][4][5][6][7][8]         │
│   (8 color swatches in a row)    │
└──────────────────────────────────┘
```

Drawn via:
```python
row = box.row(align=True)
for i in range(8):
    row.prop(theme, f"island_palette_{i}", text="")
```

### Draw primitives: optional color override

`primitives.line/polyline/edges_3d/points/tris` and `hud_text.draw` gain an optional `color` parameter. When passed, it overrides the role's color. Used for axis feedback (color comes from Blender theme, not from a role).

```python
def line(p1, p2, *, role=None, color=None, width=None, theme=None, context=None):
    ...
    c = color if color is not None else th.color_for(role)
    shader.uniform_float("color", c)
```

`role` becomes optional when `color` is explicitly passed. At least one of the two must be provided (assertion).

### Operator changes

**`mesh_visual_uv.py`:**
- Drop 14 `COL_*` module constants and `ISLAND_COLORS`
- Replace `_draw_circle/_draw_ring/_draw_polyline/_draw_diamond` helpers with calls to `primitives.points/polyline/edges_3d/tris` (the diamond can stay as a thin local helper that calls `primitives.tris` with a custom 4-vertex shape — primitives don't have a diamond primitive and shouldn't).
- Map each former constant to its role per the table below
- Island fill: `theme.island_palette[island_idx % 8]` passed as explicit `color=` to `primitives.tris`
- Axis feedback text in `_draw_transform_feedback`: `hud_text.draw(..., color=axis_color('X'))`

| Legacy constant | New target |
|---|---|
| `COL_EDGE` | `Role.LINE` |
| `COL_EDGE_SELECTED` | `Role.CLOSEST_LINE` |
| `COL_EDGE_ACTIVE` | `Role.ACTIVE_LINE` |
| `COL_EDGE_HOVER` | `Role.LOCKED_LINE` |
| `COL_EDGE_ALIGN` | `Role.PREVIEW_LINE` |
| `COL_CENTER` | `Role.PIVOT` |
| `COL_ROT_HANDLE` | `Role.PIVOT` |
| `COL_ROT_LINE` | `Role.PIVOT` with `alpha_mul=0.44` (0.35/0.80) |
| `COL_HANDLE` | `Role.HANDLE` |
| `COL_HANDLE_HOVER` | `Role.HANDLE_HOVER` |
| `COL_BBOX` | `Role.BBOX` |
| `COL_CURSOR` | `Role.CURSOR` |
| `COL_FEEDBACK` | `Role.ACTIVE_TEXT` (already migrated) |
| `COL_AXIS_X` | `axis_color('X')` |
| `COL_AXIS_Y` | `axis_color('Y')` |
| `ISLAND_COLORS[i]` | `theme.island_palette[i % 8]` |

**`mesh_shear.py`:**
- Each `self.shader.uniform_float("color", (r,g,b,a))` call site is rewritten to use `primitives.{line,edges_3d,points,tris}` with the appropriate `role=`
- The 13 hardcoded colors map per the table below
- Drop `self.shader = gpu.shader.from_builtin(...)` — no longer needed once all draw paths route through primitives
- Axis-related text/highlights use `axis_color('X'/'Y')`

| Hardcoded (RGBA) | Context | New target |
|---|---|---|
| `(1.0, 1.0, 1.0, 1.0)` | rail fixed | `Role.LINE` |
| `(1.0, 0.0, 0.0, 0.35)` | error fill | `Role.ERROR` with `alpha_mul=0.35` |
| `(1.0, 0.6, 0.1, 1.0)` | active rail / dots | `Role.ACTIVE_LINE` / `Role.ACTIVE_POINT` |
| `(1.0, 0.85, 0.3, 1.0)` | strong highlight | `Role.LOCKED_POINT` |
| `(1.0, 0.85, 0.3, 0.75)` | softer highlight | `Role.LOCKED_POINT` with `alpha_mul=0.75` |
| `(1.0, 0.9, 0.4, 1.0)` | bright dot | `Role.LOCKED_POINT` (variant) |
| `(0.3, 0.55, 1.0, 0.75)` | snap target | `Role.CLOSEST_POINT` with `alpha_mul=0.75` |
| `(0.45, 0.45, 0.45, 0.55)` | muted edge | `Role.LINE` with `alpha_mul≈0.92` |
| axis_x highlight | rail aligned to X | `axis_color('X')` |
| axis_y highlight | rail aligned to Y | `axis_color('Y')` |

Exact role choices for shear's mid-tones (locked vs preview, etc.) will be finalized during implementation by reading each call site's context.

### Backward compat

Theme is additive — old saved prefs without the new properties default to the listed defaults. No migration script needed; `get_theme()` already uses `getattr(t, name, fallback)`.

`primitives.*` API change is backward-compatible: existing callers pass `role=` and get the same behavior. `color=` is opt-in.

## Out of scope

- Sizes for handles/pivot/bbox (the 5-state `point_sizes` map already covers this — handle = "default", handle hover = "locked", pivot = "active")
- Reset-island-palette button (cosmetic; can add later if requested)
- Test suite — addon is visual, validated via Blender MCP smoke tests

## Implementation order

1. `ui/draw/theme.py` — add `Role.{HANDLE,HANDLE_HOVER,PIVOT,BBOX,CURSOR}`, defaults, `Theme.island_palette`, `axis_color()` helper, `get_theme()` plumbing
2. `prefs/theme.py` — add 5 widget color props, 8 island palette props, UI section
3. `ui/draw/primitives.py` + `ui/hud/text.py` — add optional `color=` override
4. `mesh_visual_uv.py` — strip constants, route all draws through primitives, switch to theme palette + axis_color
5. `mesh_shear.py` — strip inline colors, route all draws through primitives, switch axis to axis_color
6. MCP smoke test — reload addon, verify ops invoke + a frame renders without errors

## Risks

- **Blender PropertyGroup with 8 sibling color props**: tested pattern (Visual Origin uses 4 colors in one group); 8 should be fine. UI just needs horizontal layout.
- **`bpy.context` access in `axis_color()`**: called from draw callbacks which always have an active context. Headless fallback handles edge cases.
- **`Role.ERROR` reuse in shear for the soft red fill**: semantically the shear's red fill *is* an error/over-extent indicator (it lights up when the shear would create degenerate geometry), so reuse is fine. If a later operator needs a non-error red, add a dedicated role then.
