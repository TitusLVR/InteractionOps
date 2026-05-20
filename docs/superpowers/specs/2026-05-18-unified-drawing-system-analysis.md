# Unified Drawing System — Duplication Analysis

**Date:** 2026-05-18
**Branch:** `feat/unified-ui-foundation`
**Goal:** Identify entities and settings that are duplicated across operators, so we can collapse them into a single shared abstraction.

## Three target layers (terminology)

| Layer | What it is | Handler kind | Position |
|---|---|---|---|
| **Viewport draw** | 3D geometry in world space (cage edges, snap points, preview lines) | `POST_VIEW` | World-space |
| **General UI** | Pixel-space overlay anchored to viewport corners (statistics, persistent panels) | `POST_PIXEL` | Fixed region offsets |
| **HUD** | Cursor-anchored modal help — key hints + live header | `POST_PIXEL` | Tracks mouse |

The goal: every operator's drawing slots cleanly into exactly these three layers.

## Duplication: SETTINGS (prefs vs theme)

### Already unified (good)
- All colors → `IOPS_Theme.color_*` (40+ entries)
- All point/line/text sizes → 5-state maps in theme
- Font → `theme.font_path`
- Shadow → `theme.shadow`
- HUD layout (offset, padding, verbosity) → `theme.hud`

### Still duplicated / should fold into theme

| Pref | Lives in | Should be |
|---|---|---|
| `visual_uv_point_size` | `IOPS_AddonPreferences` | Drop. Use `theme.point_sizes["default"]` (already there). |
| `visual_uv_edge_width` | `IOPS_AddonPreferences` | Drop. Use `theme.line_widths["default"]`. |
| `visual_uv_fill_alpha` | `IOPS_AddonPreferences` | Drop. The alpha is in `theme.color_fill[3]` — callers can `theme.color_for(Role.FILL)[3]`. Or expose explicit `theme.fill_alpha` if needed for tuning. |
| `cursor_bisect_distance_offset_x/y` | `IOPS_AddonPreferences` | Generic concept. Either drop (let HUD header handle it) or move to a new `theme.cursor_text_offset_x/y` shared by all cursor-anchored labels. |

`visual_uv_normal_offset` IS operational (geometric — distance above mesh surface), keep on AddonPreferences. Same for `cursor_bisect_face_depth`, `snap_threshold`, etc. — those are behavior, not cosmetics.

### Removable code

- 4 props in `IOPS_AddonPreferences` (`visual_uv_point_size/edge_width/fill_alpha` + ~~normal_offset stays~~)
- 2 cosmetic offsets (`cursor_bisect_distance_offset_x/y` — collapse to theme or HUD)
- Their UI rows in `draw()`
- Their save/load entries in `iops_prefs.py` / `iops_prefs_list.py` / `io_addon_preferences.py`

## Duplication: CODE PATTERNS

Every modal operator that uses the new HUD repeats the same boilerplate. Currently 17 operators each carry ~30-50 lines of identical scaffolding. Numbers below are line-counts in the current code.

### Pattern A — HUD lifecycle (in 13 operators)

Each operator has:

```python
def _build_hud(self, context):                          # ~3 lines + items
    verbosity = get_theme(context).hud.verbosity
    hud = HUDOverlay("op_name", verbosity=verbosity)
    hud.add_section(HUDSection("Title", [HUDItem(...), ...]))
    hud.bind_region(context.region)
    return hud

def _draw_hud(self, context):                           # 4 lines, identical
    hud = getattr(self, "_hud", None)
    if hud is None:
        return
    hud.draw(context, getattr(self, "_last_event", None))

def modal(self, context, event):                        # 1 line, identical
    self._last_event = event
    ...

def invoke(self, context, event):                       # ~4 lines, identical
    self._hud = self._build_hud(context)
    self._last_event = event
    self._handle_hud = bpy.types.SpaceView3D.draw_handler_add(
        self._draw_hud, (context,), "WINDOW", "POST_PIXEL")
```

**Unification target:** A `ModalDrawMixin` (or `ModalHUDOperator` base) that bakes this in. Operators subclass and supply only:

- The list of `HUDItem` instances (`hud_items()` method)
- A section title (class attribute `hud_section`)
- Optional `hud_header()` method that returns the live header string

The mixin handles: `_last_event` tracking, handle registration/cleanup, region binding, `_draw_hud` wrapper, stale-handler purge on addon reload. Per-op code drops from ~30 lines to ~10-15 lines (just the items list).

### Pattern B — Viewport handle registration (in ~10 operators)

```python
self._handle_3d = bpy.types.SpaceView3D.draw_handler_add(
    self._draw_view, (context,), "WINDOW", "POST_VIEW")
```

Plus removal on cancel/finish:
```python
bpy.types.SpaceView3D.draw_handler_remove(self._handle_3d, "WINDOW")
```

**Unification target:** Same mixin manages both POST_VIEW and POST_PIXEL handles. Operators just declare `def draw_viewport(self, context)` and the mixin adds it as POST_VIEW automatically. Same for `draw_general_ui` (POST_PIXEL fixed).

### Pattern C — Stale-handler cleanup on reload (only in 1 operator)

`mesh_cursor_bisect` has `_ACTIVE_HANDLES` set + `_drop_stale_handles()` to prevent leaked handlers across addon reloads. **Other operators don't**, which is why we see `ReferenceError: StructRNA has been removed` in stderr after reload (visual_uv, draw_theme_preview, etc.).

**Unification target:** Same mixin tracks all handles in a module-level `_ACTIVE_HANDLES` set, drops stale ones on every fresh `invoke`. Eliminates an entire class of error-spam.

### Pattern D — 2D-to-3D lifting (in 4 operators)

Several operators draw pixel-space shapes through `primitives.*` (which expects 3D coords) and need `_v3()` lifting:

```python
def _v3(p):
    return Vector((p[0], p[1], 0.0))
```

Currently duplicated in `mesh_visual_uv.py`, `drag_snap_uv.py`, `mesh_quick_connect.py`, `mesh_straight_bevel.py`.

**Unification target:** Add `ui/draw/pixels.py` with `lift(p) -> Vector` plus pixel-space convenience helpers (`line_2d`, `points_2d`, `circle_2d`, `ring_2d`, `diamond_2d`) that wrap `primitives.*` and lift coords. Remove inline helpers from operators.

### Pattern E — Cursor-anchored ephemeral text (in 2 operators)

- `mesh_visual_uv._draw_transform_feedback`: draws "G along X" near mouse using `hud_text.draw` directly
- `mesh_cursor_bisect`: similar live distance label, now folded into `hud.set_header`

Two different conventions: (1) raw `hud_text.draw` at `mouse_x + 18, mouse_y + 10`, (2) `hud.set_header()` rendered above HUD section. **They're conceptually the same thing**.

**Unification target:** Standardize on `hud.set_header(line, role=...)` for all live state text. Drop ad-hoc near-mouse `hud_text.draw` calls. The HUD already follows the cursor — its header IS the "near mouse text".

## Duplication: HANDLERS (3D in POST_PIXEL — broken layer)

Three operators draw 3D geometry inside their POST_PIXEL callback instead of POST_VIEW. They manually project world → screen and rasterize. This breaks depth handling and makes them inconsistent with the rest.

| Operator | What it draws in POST_PIXEL that should be POST_VIEW |
|---|---|
| `mesh_shear` | sheared edge preview, axis rails, snap targets |
| `mesh_quick_connect` | the connection path between picked verts |
| `mesh_straight_bevel` | bevel cut lines, segment markers |

**Unification target:** Split each into two handlers — POST_VIEW for world-space geometry (via `primitives.line/points/edges_3d`), POST_PIXEL only for the HUD. Mixin from Pattern A+B makes this automatic.

## Plus: hardcoded color literals still present

`mesh_quick_connect` has **zero** theme integration (all hardcoded RGBs from the legacy era). `mesh_shear` has a few literal hover-white / muted-grey tuples. Migrating these as part of the layer-split fix is natural.

## Summary table

| Concern | Files affected | Lines saved (est.) | Risk |
|---|---|---|---|
| `ModalDrawMixin` for HUD lifecycle | 13 operators | ~200 | Low — pure refactor |
| Mixin handles POST_VIEW too | ~10 operators | ~100 | Low |
| Shared stale-handler cleanup | All operators with draw handlers | ~30 (eliminates error spam) | Low |
| `ui/draw/pixels.py` for 2D lifting | 4 operators | ~80 | Low |
| Standardize cursor-text on `hud.set_header` | 2 operators | ~30 | Low |
| Drop `visual_uv_*` cosmetic prefs | 1 op + prefs/save/load | ~40 | Low |
| Drop `cursor_bisect_distance_offset_*` cosmetic prefs | 1 op + prefs/save/load | ~20 | Low |
| Split 3D-in-POST_PIXEL operators | mesh_shear, mesh_quick_connect, mesh_straight_bevel | refactor, not removal | Medium — visual regression risk |
| Migrate `mesh_quick_connect` to theme roles | 1 operator | hardcoded → role-based | Low |

**Total estimated reduction:** ~500 lines of boilerplate + the cosmetic-pref tail.

## Proposed execution order

1. **`ModalDrawMixin`** in `ui/modal_drawing.py` (new file) — handles HUD lifecycle, 3-layer handle registration, stale cleanup, `_last_event` tracking. Operators inherit and supply layer methods.
2. **`ui/draw/pixels.py`** — pixel-space convenience layer with `lift()` and 2D primitives.
3. **Migrate one operator** (start with `drag_snap_cursor` — smallest, HUD-only) onto the mixin. Verify nothing breaks.
4. **Migrate the rest** in batches: HUD-only operators (4), then operators with POST_VIEW (8), then operators with mixed POST_PIXEL geometry (3 — these need the layer-split fix too).
5. **Drop cosmetic prefs** (`visual_uv_*` cosmetics, `cursor_bisect_distance_offset_*`).
6. **`mesh_quick_connect`** — convert hardcoded colors to roles as part of its migration.
7. **Live smoke test** — invoke every operator, verify each layer renders.

After this: a single mixin owns drawing lifecycle, a single `ui.draw` package owns rendering primitives (3D + 2D), a single `IOPS_Theme` owns all cosmetics, and operators contain only their domain logic.
