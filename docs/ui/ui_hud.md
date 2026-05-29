# HUD

InteractionOps ships a single, shared HUD/overlay system that every modal operator reuses. It paints three layers in the 3D viewport:

- a **Dynamic Overlay** that follows the cursor (or anchors to a corner) and reports operator title, live values and hotkeys;
- a corner-pinned **Help Overlay** with the operator's hotkey legend, toggled with `H` and animated between its expanded/collapsed states;
- a **Statistics Overlay** in the top-left of the 3D view with scene-wide info.

All three pull colors, sizes and placement from the same `iops_theme` PropertyGroup (see `prefs/theme.py`), so a single palette ties HUD text, panel background, drop shadow and the per-state primitive colors together.

---

## Architecture

```
ui/hud/
  items.py        HUDItem / HUDSection / HUDParam / HUDParamSection + ItemState
  layout.py       compute_origin(), clamp_to_region(), DragState, side-inset helpers
  overlay.py      HUDOverlay  — cursor-following dynamic dashboard
  help.py         HelpOverlay — corner-anchored hotkey legend, animated
  text.py         blf wrapper: theme-driven font, size, shadow, measurement cache
  event_snap.py   EventSnapshot — safe event copy for POST_PIXEL draw handlers
ui/draw/
  theme.py        Role enum, Theme dataclass, get_theme(), linear→sRGB encode
  primitives.py   rect_2d / points / polyline / edges_3d bound to the theme
  shaders.py      cached gpu.shader instances (uniform-color, polyline, point-disc)
  state.py        draw_scope(blend=, depth=, ...) context manager
  handlers.py     safe_handler_add/remove — self-healing draw handlers + tick timer
utils/draw_stats.py  always-on scene-statistics overlay
```

Each layer talks to the next only through the `Theme` value object returned by `get_theme(context)`. That snapshot is built fresh every draw from `prefs.iops_theme`, with screen-space colors (HUD text, panel background, shadow) encoded from scene-linear to sRGB so the chip you pick in the prefs matches what `POST_PIXEL` actually paints. POST_VIEW colors (points, lines, ghosts) stay linear.

!!! note "Why sRGB encode"
    Blender stores `FloatVectorProperty(subtype='COLOR')` values in scene-linear. The POST_PIXEL draw path writes straight to the already color-managed framebuffer with no further encode, so raw linear values land far too dark. `_srgb_encode()` in `ui/draw/theme.py` runs `Color.from_scene_linear_to_srgb()` only for screen-space roles.

Modal operators wire the HUD in three steps:

```python
self.hud = HUDOverlay("loop_cut")
self.hud.title = "Loop cut"
self.hud.add_param(HUDParam("Cuts", lambda: self.cuts, "int"))
self.hud.bind_region(context.region)

self.help = HelpOverlay("loop_cut")
self.help.add_section(HUDSection("Modifiers", [...]))
self.help.bind_region(context.region)

# in modal():
if self.hud.handle_param_toggle_event(event, theme_prefs):
    return {"RUNNING_MODAL"}
if handle_help_toggle(self.help, context, event, hud=self.hud):
    return {"RUNNING_MODAL"}
```

`bind_region(region)` stores the region's C-pointer; the overlay no-ops in any other 3D viewport so multi-window setups don't double-draw. `safe_handler_add(..., tick=True)` claims a refcounted window-manager timer so the cursor-follow and recovery glide keep ticking even when the mouse is idle.

---

## Item types

`ui/hud/items.py` defines two item families. Both live inside a `HUDSection` or `HUDParamSection`.

### Hotkey items (legacy/help legend)

```python
HUDItem(label, key, state=ItemState.OFF, default_state=ItemState.OFF, always_show=False)
```

| Field | Drives |
|---|---|
| `key` | Glyph drawn in the **HUD Glyph** color/size (`Role.HUD_KEY`, `text_size_hud_key`). |
| `label` | Description drawn at `text_size_hud_label`. The color follows `state`. |
| `state` | `ItemState.ON` → `HUD_LABEL`, `OFF`/`DISABLED` → `HUD_LABEL_INACTIVE`. |
| `default_state` | Compact verbosity hides items whose `state == default_state` unless `always_show`. |
| `always_show` | Always render the item in compact mode (e.g. main confirm/cancel keys). |

### Live parameter rows (HUD dashboard)

```python
HUDParam(name, value_getter, kind="str", fmt=None,
        active_getter=None, visible_getter=None)
```

| Field | Drives |
|---|---|
| `name` | Drawn as `"name:"` in **HUD Label** (active) or **HUD Label Inactive** (inactive). |
| `value_getter()` | Called every draw — keep it O(1). Return value formatted per `kind`. |
| `kind` | `"bool"` → ✓/✗, `"int"`, `"float"` (with `fmt` default `"{:.3f}"`), `"str"`, `"enum"`. |
| `active_getter()` | Returns False to render the row as inactive (greyed). |
| `visible_getter()` | Returns False to omit the row entirely from layout and draw. |

The value column is rendered in **HUD Active Value** (`Role.HUD_ACTIVE_VALUE`) when active, otherwise in **HUD Label Inactive**.

### Sections and special rows

| Construct | Role / size | Notes |
|---|---|---|
| `HUDOverlay.title` (str) | `HUD_HEADER` / `text_size_hud_header` | Operator name, drawn first; visible whenever overlay is visible (even when params are hidden via `/`). |
| `HUDOverlay.set_header(*lines)` | `HUD_LABEL` + `HUD_ACTIVE_VALUE` | Live state lines. Split on the first `:` — label half in HUD Label, value half in HUD Active Value. Lines without `:` render fully as HUD Label. |
| `HUDSection.title` | `HUD_HEADER` / `text_size_hud_header` | Group title above its items. |
| `HUDParamSection.title` | `HUD_HEADER` / `text_size_hud_header` | Group title above its params. |
| Stats error/warn value | `HUD_STATS_ERROR` / `stats_text_size` | Used by `utils/draw_stats.py` for dirty/unsaved file, non-uniform scale, etc. |
| `ItemState.DISABLED` label | `HUD_LABEL_INACTIVE` | Same role as `OFF`; future-facing distinction kept for callers. |

The "Separator" between sections is not a row type — it is the gap controlled by `hud_section_spacing` (auto-derived from text size).

---

## Layout and placement

### Anchor mode (`hud_mode`)

`hud_mode` is an `EnumProperty` on `iops_theme`. Bottom-left origin in region pixels is computed by `compute_origin()` (`ui/hud/layout.py`).

| `hud_mode` value | Behaviour |
|---|---|
| `cursor` | Follows the mouse. Uses `hud_offset_x` / `hud_offset_y` (negative Y puts the HUD above the cursor). The only mode that runs through `EventSnapshot`. |
| `top_left`, `top_center`, `top_right` | Top edge anchor; `hud_anchor_offset_x/y` shifts from that anchor (X is signed for center anchors). |
| `left_center`, `center`, `right_center` | Vertical-center anchors. |
| `bottom_left`, `bottom_center`, `bottom_right` | Bottom edge anchors. |
| `free` | Fixed `(hud_free_x, hud_free_y)`. Set automatically when the user `Shift+Ctrl+Alt`-drags the HUD. |

All non-`cursor` modes also call `region_side_insets()` so the HUD never hides behind the toolbar (TOOLS region) or the N-panel (UI region). Each anchor result is clamped through `clamp_to_region()` against `hud_padding` + the side insets.

### Spacing knobs

| Prop | Default | Effect |
|---|---|---|
| `hud_padding` | 12 | Min distance kept from region edges (and from side insets in anchor modes). |
| `hud_key_label_spacing` | 16 | Gap between the widest key glyph column and the label column. |
| `hud_section_spacing` | auto | Vertical gap between sections. Auto-derived: `max(4, max(key_size, label_size) * 0.6)`. |
| `hud_row_spacing` | auto | Vertical gap between rows. Auto-derived: `max(2, max(key_size, label_size) * 0.25)`. |
| `hud_smoothing` | 0.70 | Post-freeze recovery lerp. **Not** applied during normal mouse motion — only after a viewport-navigation freeze ends, so cursor tracking stays instant. |

### Cursor smoothing / nav freeze

`HUDOverlay` watches the active `region_data.view_matrix` between successive draws. While the matrix changes (any view navigation — rotate, dolly, wheel zoom, numpad, scripted) the HUD origin is frozen in place. As soon as the matrix settles, the overlay enters a one-shot recovery glide whose stiffness is `1.0 - hud_smoothing`. Operators can also call `hud.pin_for(seconds)` explicitly for MMB/wheel-driven pins.

Single-frame mouse warps (Blender wraps the cursor across region edges during MMB pan/rotate) would yank a cursor-following HUD — the view-matrix watcher catches every form of nav and prevents that.

---

## Panel background and shadow

Both the Dynamic Overlay and the Help Overlay share the same background panel and drop-shadow settings.

| Prop | Default | Effect |
|---|---|---|
| `panel_bg_enabled` | True | Toggles the rectangle behind text. |
| `panel_bg_color` | `(0, 0, 0, 0.25)` | RGBA. Stored scene-linear, **converted to sRGB at draw time** (see the sRGB encoding note below). |
| `panel_bg_padding` | 10 | Pixels added on all four sides of the content rectangle. Used by `clamp_to_region(..., padding=bg_pad)` so the panel never hides behind side regions either. |
| `shadow_enabled` | True | Per-glyph drop shadow via `blf.SHADOW`. |
| `shadow_color` | `(0, 0, 0, 1)` | Encoded linear→sRGB on draw. |
| `shadow_blur` | 0 | `blf.shadow` blur radius. |
| `shadow_offset_x` | 1 | Horizontal pixel offset. |
| `shadow_offset_y` | -1 | Vertical pixel offset. |

Shadow alpha is multiplied by the glyph's `alpha_mul` so fading text doesn't leave opaque shadow ghosts behind (relevant for the shockwave preset).

---

## Help overlay

`HelpOverlay` is corner-pinned. Two states: **expanded** (full section/item list) and **collapsed** (single hint line `prefs.help_hint_text`, default `"Press {key} for help"`, with `{key}` substituted from the live keymap).

### Toggle key

<div class="iops-meta" markdown="1">
<span class="key">Keymap id: iops.ui_help_toggle</span>
<span>Default binding: none (set in Preferences → Keymaps)</span>
<span class="mode">Context: per-operator modal</span>
</div>

The toggle is a real keymap item, not a string preference — there is no hard-coded `H` binding. Look up `iops.ui_help_toggle` in the addon's Keymaps tab and bind it to whatever you like; the default fallback `"H"` only applies when the keymap entry is missing. `event.shift/ctrl/alt/oskey` must all be False for the press to count.

The companion `iops.ui_hud_params_toggle` keymap item (default fallback `SLASH`) toggles the Dynamic Overlay's parameter list while keeping the title visible.

### Placement (`help_corner`)

Identical option list to `hud_mode` except there is no `cursor` mode (Help is always pinned). `help_offset_x` / `help_offset_y` shift from the anchored corner; `help_free_x/y` are used in `free` mode. `Shift+Ctrl+Alt`-drag on the Help box flips it to `free` and writes the new position.

### Animation presets (`help_anim_preset`)

| Preset | Effect | Knobs |
|---|---|---|
| `none` | Instant swap — no interpolation. | — |
| `fade` | Cross-fade between collapsed and expanded states with `_ease_in_out` ramps on both halves. | `help_anim_duration` (default 0.5 s). |
| `slide-fade` | Outgoing state slides toward the anchored edge while fading out; incoming state slides in from that edge while fading in. Swap happens at `progress=0.5` when both pieces are fully transparent. | `help_anim_duration`, `help_anim_slide_amount` (default 28 px). |
| `wave` | Per-letter staggered reveal — letters fly in from a horizontal offset (`spread`) into their final position with eased alpha. | `help_anim_wave_duration` (default 2.0 s, replaces the shared one), `help_anim_wave_spread`, `help_anim_wave_stagger_scale`, `help_anim_wave_fade_window`. |
| `shockwave` | New content fades in underneath; outgoing letters explode radially outward from the box centre, alpha decaying as `(1-progress)²`. | `help_anim_duration`, `help_anim_shockwave_radius` (default 160 px). |

Animations are time-based (`time.perf_counter()` against `_anim_start`) and tick on `bpy.app.timers` at `hud_anim_fps` Hz (default 240 Hz). The animation duration is independent of FPS — FPS only controls how many in-between frames are rendered along the eased curve.

The corner-Help and the HUD's nav-recovery glide all use the same `hud_anim_fps` value, which also drives the refcounted window-manager timer kept by `safe_handler_add(..., tick=True)`.

---

## Statistics overlay

`utils/draw_stats.py` draws a persistent block in the top-left of every 3D view (offset from the TOOLS region so it never overlaps the toolbar). It is the only HUD layer that is not bound to a modal operator. Enable/disable via `prefs.iops_stat`.

Rows reported (each conditionally on per-row toggles in prefs):

- File name + dirty flag (red `HUD_STATS_ERROR` when unsaved or modified).
- Active mesh stats: scale (`HUD_STATS_ERROR` when scale ≠ 1 or non-uniform), modifier count, vertex/edge/face counts, UV channel info, vertex colors, selection stats.
- Scene info.

Theme controls:

| Prop | Default | Effect |
|---|---|---|
| `stats_offset_x` | 8 | Horizontal offset from the right edge of the toolbar. |
| `stats_offset_y` | 220 | Distance from the top of the 3D view to the first row. |
| `stats_text_size` | 11 | Text size (slider in the **Statistics Overlay** rollout). |
| `stats_row_spacing` | 1.5 | Vertical row pitch as a multiple of the line height. |
| `stats_column_spacing` | 5.0 | Horizontal offset of the value column from the label column, as a multiple of the line height. |

When `space_data.overlay.show_overlays` is off, every row's effective alpha is multiplied by 0 — the overlay respects the viewport's overlay toggle.

---

## Theme roles and sync

### HUD text roles

All theme colors live on `iops_theme` and are looked up by `Theme.color_for(role)`. The HUD roles, with their backing color prefs and size sliders:

| Role | Color pref | Size pref | Used for |
|---|---|---|---|
| `HUD_HEADER` | `color_hud_header` | `text_size_hud_header` | Operator title, section titles, `HUDOverlay.title`. |
| `HUD_KEY` | `color_hud_key` | `text_size_hud_key` | Key glyph in hotkey rows. Also used for the "flash" highlight on Help toggle. |
| `HUD_ACTIVE_VALUE` | `color_hud_active_value` | `text_size_hud_label` | Value half of `set_header()` lines, and active parameter values. |
| `HUD_LABEL_ACTIVE` | `color_hud_active_value` (shared) | `text_size_hud_label` | Reserved alias — same backing pref as `HUD_ACTIVE_VALUE`. |
| `HUD_LABEL` | `color_hud_label` | `text_size_hud_label` | Item label when `state == ON`, parameter name when active, label half of `set_header()` lines. |
| `HUD_LABEL_INACTIVE` | `color_hud_label_inactive` | `text_size_hud_label` | Item label when `state` is `OFF` or `DISABLED`. Parameter rows when `active_getter()` returns False. Help's collapsed hint text. |
| `HUD_STATS_ERROR` | `color_hud_stats_error` | `stats_text_size` | Statistics overlay error/warning values. |

Help's collapsed hint is rendered with `HUD_LABEL_INACTIVE` so it reads as ambient information. All HUD roles are screen-space, so they round-trip through `_srgb_encode()` in `get_theme()`.

### Point / line / ghost state tables

These are not HUD roles, but operators draw them alongside the HUD. Each primitive carries a 6-state table:

| State | Point role | Line role | Ghost role |
|---|---|---|---|
| Default | `POINT` | `LINE` | `GHOST_DEFAULT` |
| Closest | `CLOSEST_POINT` | `CLOSEST_LINE` | `GHOST_CLOSEST` |
| Active | `ACTIVE_POINT` | `ACTIVE_LINE` | `GHOST_ACTIVE` |
| Locked | `LOCKED_POINT` | `LOCKED_LINE` | `GHOST_LOCKED` |
| Preview | `PREVIEW_POINT` | `PREVIEW_LINE` | `GHOST_PREVIEW` |
| Error | `ERROR_POINT` | `ERROR_LINE` | (uses `color_error_ghost`) |

Two extra ghost roles handle interaction patterns:

- `GHOST_TARGET_SEL` — warm fill for selected target polys in poly-reference modes.
- `GHOST_MATCH_HINT` — dim green fill for `A`-key match candidates.

Widgets (`HANDLE`, `HANDLE_HOVER`, `PIVOT`, `BBOX`, `CURSOR`) each have their own single color + size pref and bypass the state table.

### Sync from Blender's theme

<div class="iops-meta" markdown="1">
<span class="key">bl_idname: iops.theme_use_blender_hud_colors</span>
<span>Class: IOPS_OT_ThemeUseBlenderHUDColors</span>
<span class="mode">Context: Preferences → Theme → HUD → Text Styles</span>
</div>

`iops.theme_use_blender_hud_colors` copies HUD-relevant colors out of Blender's active theme into the addon palette, converting each from sRGB back to scene-linear so they store cleanly in the `COLOR` props:

| HUD pref | Source in Blender theme |
|---|---|
| `color_hud_header` | `user_interface.panel_title` |
| `color_hud_key` | `view_3d.object_active` |
| `color_hud_active_value` (drives `HUD_LABEL_ACTIVE` too) | `view_3d.editmesh_active` |
| `color_hud_label` | `user_interface.wcol_text.text` |
| `color_hud_label_inactive` | same as label, alpha forced to 0.5 |
| `color_hud_stats_error` | `user_interface.wcol_state.error` |
| `panel_bg_color` | `user_interface.panel_back` (keeps native alpha) |

### First-install auto-sync

On `register()`, `__init__.py:_sync_hud_from_blender_theme_if_pristine()` runs the same sync **only** when every HUD color/panel pref is still at its hardcoded default. As soon as the user touches any HUD color the auto-sync stops firing — manual edits are never overwritten.

---

## Behaviour

### Depth test default

`depth_test_default` (`LESS` or `ALWAYS`, default `ALWAYS`) is the depth-test mode primitive helpers pick up when their caller doesn't pass `depth=` explicitly. `ALWAYS` makes overlays draw on top of geometry; `LESS` lets the mesh occlude them.

### Animation FPS

`hud_anim_fps` (default 240 Hz) is the redraw rate for HelpOverlay animations *and* the refcounted window-manager tick timer kept alive while any `safe_handler_add(..., tick=True)` handler is installed. Match it to your monitor's refresh rate for smoothest motion. Because animations are time-based the duration of any preset is unchanged — only the number of in-between frames varies.

### Font override

`font_path` (file path, default empty) loads a custom TTF/OTF via `blf.load()` and caches it in `ui/hud/text.py:_FONT_CACHE`. Empty falls back to Blender's default font (id 0). Changing this invalidates the measurement cache automatically via `invalidate_caches()`.

---

## Per-operator HUD usage

Many modal operators wire their own HUD/Help overlays through this exact system. A non-exhaustive list of operators that ship full HUD overlays:

- [Object Aligner](../operators/op_object_aligner.md) — ghost-preview poly modes with live param dashboard.
- [Align Object to Face](../operators/op_object_align_to_face.md) — face-pick HUD + axis-flip hints.
- [Drop It](../operators/op_object_drop_it.md) — preview ray HUD.
- [Cursor Bisect](../operators/op_mesh_cursor_bisect.md) — bisect plane params.
- [Drag Snap](../operators/op_drag_snap.md), [Drag Snap Cursor](../operators/op_drag_snap_cursor.md), [Drag Snap UV](../operators/op_drag_snap_uv.md) — snap distance, axis lock, projection mode.
- [Quick Snap](../operators/op_mesh_quick_snap.md) and [Mesh Quick Snap](../operators/op_mesh_quick_snap.md).
- [Three Point Rotation](../operators/op_object_three_point_rotation.md).
- [Complex Modal Rotation](../operators/op_object_three_point_rotation.md).
- [Cursor Rotate](../operators/op_cursor_rotate.md).
- [Easy Mod — Array / Curve / Shwarp](../operators/op_easy_mod_array.md).
- [Mesh Cursor Bisect](../operators/op_mesh_cursor_bisect.md), [Connect](../operators/op_z_ops.md), [Equalize](../operators/op_z_ops.md), [Line Up](../operators/op_z_ops.md), [Mirror](../operators/op_z_ops.md).

All of them share one palette, one font, one panel background, one shadow, one set of animations — change them once in Preferences → Theme → HUD and every operator picks up the change on the next redraw.

---

## Theme preview operator

<div class="iops-meta" markdown="1">
<span class="key">bl_idname: iops.draw_theme_preview</span>
<span>Class: IOPS_OT_DrawThemePreview</span>
<span class="mode">Context: Preferences → Theme tab (button at the bottom)</span>
</div>

`iops.draw_theme_preview` installs a pair of draw handlers (POST_VIEW + POST_PIXEL) that render one swatch of every primitive — the 6-state point row, the 6-state line row, the ghost-surface roles, the widget primitives — alongside a live `HUDOverlay` (with sample `HUDParam` rows) and a sample `HelpOverlay` pinned to the configured corner. ESC or right-click stops it; the button in the Theme tab flips to "Stop" while running.

Draw handlers receive a plain `state` dict rather than the operator instance so they survive addon reloads without raising `ReferenceError: StructRNA of type ... has been removed`. The module also keeps a `_LIVE_INSTALLS` registry that the addon's `unregister()` walks to tear down any still-alive handlers and timers.

Use it to tune colors and sizes against actual primitives instead of guessing from chip swatches.
