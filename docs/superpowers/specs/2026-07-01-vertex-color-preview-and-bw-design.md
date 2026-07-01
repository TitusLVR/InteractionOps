# Vertex Color Preview Toggle + Black/White Swatches — Design

**Date:** 2026-07-01
**Status:** Approved (design), pending implementation plan

## Goal

Two additions to the existing **Vertex Color** widget:

1. **Preview toggle** — one flipbox that renders every object as its vertex
   color (full RGBA, unlit) so the color is visible in **EEVEE and Cycles**
   rendered shading, and reverts cleanly when toggled off.
2. **Black / White swatches** — two more fill swatches alongside R/G/B, using
   the same explicit-color override path.

Both are widget-level additions. They require **no widget-framework changes**
(literal-color `SWATCH` and `prop`-bound `FLIPBOX` already exist).

## Part A — Preview toggle

### Mechanism: `view_layer.material_override`

The preview uses the view-layer material override (the same mechanism as
`operators/material_override.py`), **not** node injection into user materials.
A single temporary material is assigned to `view_layer.material_override`;
toggling off clears that one field. This mutates zero user materials and is
fully reversible, unlike injecting an Attribute node into each object's material
(which needs fragile save/restore of the original Surface link).

**Accepted trade-off:** the override is view-layer-wide — while preview is on,
every object in the view layer renders as its vertex color. This is the standard
technique and reverts instantly.

### Temp material `IOPS_VC_Preview`

Created once and reused (looked up by name). Node graph, rebuilt on each enable
so it always reflects the current attribute:

```
Color Attribute (ShaderNodeVertexColor, layer_name = <active color attr>)
    → Emission (ShaderNodeEmission)
        → Material Output (ShaderNodeOutputMaterial, Surface)
```

Emission makes the surface unlit, so the raw vertex color displays identically
under EEVEE and Cycles. `layer_name` is taken from the active object's active
color attribute name (the "current" vertex color); if there is no active mesh /
color attribute, `layer_name` is left `""` (the node then uses each object's
active render color attribute).

### State + control

Two new properties on `IOPS_SceneProperties` (`prefs/addon_properties.py`):

- `iops_vc_preview: BoolProperty(default=False, update=_iops_vc_preview_update)`
- `iops_vc_preview_prev_shading: StringProperty(default="")` — remembers the
  viewport shading type to restore on toggle-off.

The widget binds a `FLIPBOX` to `scene.IOPS.iops_vc_preview`; clicking it writes
the bool, which fires the update callback. The callback lazily imports and calls
a helper in `operators/assign_vertex_color.py` (lazy import avoids a circular
import at module load):

```python
def _iops_vc_preview_update(self, context):
    from ..operators.assign_vertex_color import vc_preview_set
    vc_preview_set(context, self.iops_vc_preview)
```

### `vc_preview_set(context, enable)` — behavior

Lives in `operators/assign_vertex_color.py` (same feature file). Constant
`VC_PREVIEW_MAT = "IOPS_VC_Preview"`.

- **enable=True:**
  1. Determine `layer_name` from `context.object` active color attribute (else `""`).
  2. Build/reuse `IOPS_VC_Preview` (clear + rebuild the 3-node graph above).
  3. `context.view_layer.material_override = mat`.
  4. Find the active `VIEW_3D` space; if `iops_vc_preview_prev_shading` is empty,
     store the current `shading.type`; set `shading.type = 'RENDERED'`.
  5. `context.area.tag_redraw()`.
- **enable=False:**
  1. `context.view_layer.material_override = None`.
  2. If a stored shading type exists, restore `shading.type` to it; clear the
     stored value.
  3. Redraw.

Helper `_active_view3d_space(context)`: return `context.space_data` if it is
`VIEW_3D`, else the active space of the first `VIEW_3D` area in
`context.screen`, else `None` (all shading steps are skipped when `None`).

`vc_preview_set` re-resolves all data from `context` per call and caches no
references. It is invoked only from a UI-driven property update (data-API work
only — no operator calls), which is safe in an update callback.

## Part B — Black / White swatches

Two `SWATCH` cells in a new row, reusing the explicit-color override on
`iops.mesh_assign_vertex_color` exactly like R/G/B:

- Black → `op_kwargs {use_override_color: true, override_color: [0,0,0,1]}`
- White → `op_kwargs {use_override_color: true, override_color: [1,1,1,1]}`

Labels are omitted (`""`) — the swatch color is self-explanatory, and a light
label glyph on a white swatch would be unreadable.

## Widget layout (`vertex_color.json`)

```json
{
  "version": 1, "name": "vertex_color", "title": "Vertex Color", "space": "VIEW_3D",
  "rows": [
    {"type": "SECTION", "label": "Fill RGB"},
    {"type": "ROW", "cells": [
      {"type": "SWATCH", "color": [1,0,0,1], "label": "R", "op": "iops.mesh_assign_vertex_color", "op_kwargs": {"use_override_color": true, "override_color": [1,0,0,1]}},
      {"type": "SWATCH", "color": [0,1,0,1], "label": "G", "op": "iops.mesh_assign_vertex_color", "op_kwargs": {"use_override_color": true, "override_color": [0,1,0,1]}},
      {"type": "SWATCH", "color": [0,0,1,1], "label": "B", "op": "iops.mesh_assign_vertex_color", "op_kwargs": {"use_override_color": true, "override_color": [0,0,1,1]}}
    ]},
    {"type": "ROW", "cells": [
      {"type": "SWATCH", "color": [0,0,0,1], "label": "", "op": "iops.mesh_assign_vertex_color", "op_kwargs": {"use_override_color": true, "override_color": [0,0,0,1]}},
      {"type": "SWATCH", "color": [1,1,1,1], "label": "", "op": "iops.mesh_assign_vertex_color", "op_kwargs": {"use_override_color": true, "override_color": [1,1,1,1]}}
    ]},
    {"type": "SECTION", "label": "Alpha", "show_if": {"mode": "EDIT_MESH"}},
    {"type": "ROW", "show_if": {"mode": "EDIT_MESH"}, "cells": [
      {"type": "SWATCH", "color": [0.5,0.5,0.5,0], "show_alpha": true, "label": "A0", "op": "iops.mesh_assign_vertex_color_alpha", "op_kwargs": {"vertex_color_alpha": 0.0}},
      {"type": "SWATCH", "color": [0.5,0.5,0.5,1], "show_alpha": true, "label": "A1", "op": "iops.mesh_assign_vertex_color_alpha", "op_kwargs": {"vertex_color_alpha": 1.0}}
    ]},
    {"type": "SECTION", "label": "Preview"},
    {"type": "FLIPBOX", "prop": "scene.IOPS.iops_vc_preview", "label": "Preview VC (Rendered)"}
  ]
}
```

7 rows. The single bare `FLIPBOX` is preceded by a `SECTION`, so no flipbox
auto-merge applies. The JSON lives in the Blender user-scripts widgets folder
(`B:\scripts\presets\iops\widgets\`), consistent with every other widget — it is
not repo-tracked.

## Error handling / edge cases

- No active mesh / no active color attribute → `layer_name=""`; the Color
  Attribute node falls back to each object's active render color attribute.
  Preview still toggles (shows whatever render attribute each object has).
- No `VIEW_3D` space resolvable → material override still applies; shading
  switch/restore is skipped (no crash).
- Preview left on when the user manually changes shading: toggling off restores
  the stored shading type (may differ from the user's manual change — acceptable).
- Toggling off with no stored shading (never switched) → just clears the override.
- `IOPS_VC_Preview` material persists in `bpy.data` after toggle-off for reuse;
  it has no fake user, so it is discarded on save/reload if unused.

## Testing

- **bpy-free:** confirm the updated `vertex_color.json` validates
  (`composed.validate_def` → `errors == []`, 7 rows, black/white swatches carry
  `color` + override `op_kwargs`, preview row is a `prop`-flipbox). No new
  framework code, so no new `composed.py` unit tests.
- **Live Blender 5.1.2:**
  - Black/White swatches fill the selection with `(0,0,0,1)` / `(1,1,1,1)`.
  - Preview toggle **on**: `view_layer.material_override == IOPS_VC_Preview`,
    viewport switches to Rendered, objects display their vertex color under
    **both** EEVEE and Cycles. Toggle **off**: override cleared, shading restored.
  - Re-toggle reuses the single `IOPS_VC_Preview` material (no duplicates).

## Out of scope

Per-channel isolation (R/G/B/A greyscale), a channel selector, per-object
(non-override) preview, grey swatch, previewing alpha as a mask. The full-color
override toggle is the agreed scope.
