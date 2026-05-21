# HUD Prefs Grouping Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reorganize the HUD section in the addon's Theme tab so the four shared-style blocks (Text Styles, Background panel, Shadow, Font) become collapsible sub-sections instead of flat content above the three overlay sub-sections.

**Architecture:** Pure UI refactor in `prefs/theme.py`. Add three `BoolProperty` fold flags to `IOPS_Theme`. In `draw_theme_tab()`, wrap each of the four flat blocks inside the HUD body in a `_theme_section(...)` call — the same helper already used for `Dynamic Overlay / Help Overlay / Statistics Overlay`. No property semantics change, no preset migration needed.

**Tech Stack:** Blender 4.x Python API (`bpy.types.PropertyGroup`, `bpy.props.BoolProperty`, layout API).

**Spec:** [docs/superpowers/specs/2026-05-21-hud-prefs-grouping-design.md](../specs/2026-05-21-hud-prefs-grouping-design.md)

---

## Context for the Engineer

- File to edit: `prefs/theme.py` only.
- `IOPS_Theme` is a `PropertyGroup` registered as `iops_theme` on the addon preferences. Existing UI fold flags (`show_point`, `show_line`, `show_hud`, `show_hud_placement`, `show_help`, `show_stats`, …) live on this same class as plain `BoolProperty(default=…)` fields — follow that convention.
- `_theme_section(layout, theme, prop_name, title, *, icon="NONE")` (theme.py:373) is the helper that draws a collapsible TRIA-header box. It returns a body column when expanded, or `None` when collapsed. The pattern is:

  ```python
  body = _theme_section(parent, theme, "show_xxx", "Title", icon="…")
  if body is not None:
      body.prop(theme, "…")
  ```

- The existing HUD body currently lays out its shared-style blocks **flat** between theme.py:436 and theme.py:480 (text-style loop → panel → shadow → font), and only then drops into the three nested overlay sections (theme.py:483+).
- There is no pytest harness for prefs UI. Verification is manual inside Blender using the blender-mcp skill (load the addon, open prefs, expand HUD, eyeball the rollouts).
- Theme presets are JSON files in `scripts/presets/IOPS/themes/`. Loader is in `operators/preferences/io_theme.py` — it reads property values by name, so leaving every existing property name untouched means presets keep loading.

---

## File Structure

- Modify: `prefs/theme.py`
  - Add three `BoolProperty` fold flags to `IOPS_Theme`.
  - Re-layout the HUD body inside `draw_theme_tab()`.

No other files touched.

---

## Task 1: Add fold-state flags for the three new HUD sub-sections

**Files:**
- Modify: `prefs/theme.py` (the existing fold-flag block at theme.py:286-297)

- [ ] **Step 1: Add three new BoolProperty fields**

In `IOPS_Theme`, find the existing block of UI fold flags (currently theme.py:286-297, starting with `show_point: BoolProperty(default=True)`). Add three new flags alongside `show_hud_placement`. The block should look like this afterwards:

```python
    # --- Theme tab fold state (UI only) ---
    show_point: BoolProperty(default=True)
    show_line: BoolProperty(default=False)
    show_text: BoolProperty(default=False)
    show_surfaces: BoolProperty(default=False)
    show_widgets: BoolProperty(default=False)
    show_islands: BoolProperty(default=False)
    show_font: BoolProperty(default=False)
    show_hud: BoolProperty(default=False)
    show_hud_text: BoolProperty(default=False)
    show_hud_panel: BoolProperty(default=False)
    show_hud_font: BoolProperty(default=False)
    show_hud_placement: BoolProperty(default=True)
    show_help: BoolProperty(default=False)
    show_stats: BoolProperty(default=False)
    show_behaviour: BoolProperty(default=False)
```

(Insertion point: immediately after `show_hud: BoolProperty(default=False)`. The three new flags are grouped right after `show_hud` so all HUD-related fold state stays contiguous.)

- [ ] **Step 2: Reload the addon in Blender to register the new properties**

Use the blender-mcp skill to run, in Blender's running session:

```python
import bpy
bpy.ops.preferences.addon_disable(module="InteractionOps")
bpy.ops.preferences.addon_enable(module="InteractionOps")
```

Expected: no errors. Then verify the new props exist:

```python
prefs = bpy.context.preferences.addons["InteractionOps"].preferences
t = prefs.iops_theme
print(t.show_hud_text, t.show_hud_panel, t.show_hud_font)
```

Expected output: `False False False`

- [ ] **Step 3: Commit**

```bash
git add prefs/theme.py
git commit -m "feat(prefs): add fold flags for HUD shared-style sub-sections"
```

---

## Task 2: Wrap HUD shared-style blocks in collapsible sub-sections

**Files:**
- Modify: `prefs/theme.py` — `draw_theme_tab()`, HUD branch (currently theme.py:435-480, ending just before `# --- Dynamic Overlay …` at theme.py:482)

- [ ] **Step 1: Replace the flat HUD-body block with three nested sub-sections**

Locate the HUD block in `draw_theme_tab()`. It starts at:

```python
    # HUD — parent rollout. Contains all HUD-related text styles
    # …
    sub = _theme_section(layout, theme, "show_hud", "HUD", icon="WINDOW")
    if sub is not None:
```

Inside the `if sub is not None:` body, the four flat blocks currently are:

1. Text-styles `for attr, size_attr, label in (...)` loop (theme.py:440-458)
2. `panel_bg_*` block (theme.py:460-464)
3. `shadow_*` block (theme.py:466-472)
4. `font_path` block (theme.py:474-479)

…followed by three `_theme_section(...)` calls for Dynamic / Help / Statistics overlays (theme.py:482+).

Replace blocks 1–4 with three nested `_theme_section(...)` calls, leaving the three overlay sub-sections that follow untouched. The full new HUD body should read:

```python
    sub = _theme_section(layout, theme, "show_hud", "HUD", icon="WINDOW")
    if sub is not None:
        # --- Text Styles ----------------------------------------------
        body = _theme_section(sub, theme, "show_hud_text",
                              "Text Styles", icon="FONT_DATA")
        if body is not None:
            for attr, size_attr, label in (
                    ("color_hud_header",         "text_size_hud_header",
                     "HUD Header / Label Active"),
                    ("color_hud_key",            "text_size_hud_key",
                     "HUD Glyph / Active Value"),
                    ("color_hud_label",          "text_size_hud_label",
                     "HUD Label"),
                    ("color_hud_label_inactive", None,
                     "HUD Label Inactive"),
                    ("color_hud_stats_error",    None,
                     "HUD Stats Error/Warning"),
            ):
                row = body.row(align=True)
                row.label(text=label)
                if size_attr is not None:
                    row.prop(theme, size_attr, text="")
                else:
                    row.label(text="")
                row.prop(theme, attr, text="")

        # --- Panel & Shadow -------------------------------------------
        body = _theme_section(sub, theme, "show_hud_panel",
                              "Panel & Shadow", icon="MESH_PLANE")
        if body is not None:
            body.prop(theme, "panel_bg_enabled")
            bg = body.column(align=True)
            bg.active = theme.panel_bg_enabled
            bg.prop(theme, "panel_bg_color")
            bg.prop(theme, "panel_bg_padding")
            body.separator()
            body.prop(theme, "shadow_enabled")
            sh = body.column(align=True)
            sh.active = theme.shadow_enabled
            sh.prop(theme, "shadow_color")
            sh.prop(theme, "shadow_blur")
            sh.prop(theme, "shadow_offset_x")
            sh.prop(theme, "shadow_offset_y")

        # --- Font -----------------------------------------------------
        body = _theme_section(sub, theme, "show_hud_font",
                              "Font", icon="FILE_FONT")
        if body is not None:
            body.prop(theme, "font_path", text="")
            body.label(
                text="Empty = Blender default. Used by every HUD overlay.",
                icon="INFO",
            )

        sub.separator()

        # --- Dynamic Overlay (per-operator HUD) -------------------------
        body = _theme_section(sub, theme, "show_hud_placement",
                              "Dynamic Overlay", icon="WINDOW")
        if body is not None:
            body.prop(theme, "hud_mode")
            mode = theme.hud_mode
            row = body.row(align=True)
            if mode == "cursor":
                row.prop(theme, "hud_offset_x")
                row.prop(theme, "hud_offset_y")
            elif mode == "free":
                row.prop(theme, "hud_free_x")
                row.prop(theme, "hud_free_y")
            else:
                row.prop(theme, "hud_anchor_offset_x")
                row.prop(theme, "hud_anchor_offset_y")
            body.prop(theme, "hud_padding")
            body.prop(theme, "hud_key_label_spacing")
            body.prop(theme, "hud_smoothing", slider=True)
            body.prop(theme, "hud_anim_fps")
            body.label(text="Toggle: Keymaps → iops.ui_hud_params_toggle",
                       icon="INFO")

        # --- Help Overlay -----------------------------------------------
        body = _theme_section(sub, theme, "show_help",
                              "Help Overlay", icon="QUESTION")
        if body is not None:
            body.label(text="Toggle: Keymaps → iops.ui_help_toggle",
                       icon="INFO")
            body.prop(theme, "help_corner")
            row = body.row(align=True)
            if theme.help_corner == "free":
                row.prop(theme, "help_free_x")
                row.prop(theme, "help_free_y")
            else:
                row.prop(theme, "help_offset_x")
                row.prop(theme, "help_offset_y")
            body.prop(theme, "help_hint_text")
            body.separator()
            body.prop(theme, "help_anim_preset")
            preset = theme.help_anim_preset
            if preset == "wave":
                body.prop(theme, "help_anim_wave_duration")
            else:
                body.prop(theme, "help_anim_duration")
            if preset == "slide-fade":
                body.prop(theme, "help_anim_slide_amount")
            elif preset == "wave":
                body.prop(theme, "help_anim_wave_spread")
                body.prop(theme, "help_anim_wave_stagger_scale")
                body.prop(theme, "help_anim_wave_fade_window")
            elif preset == "shockwave":
                body.prop(theme, "help_anim_shockwave_radius")

        # --- Statistics Overlay -----------------------------------------
        body = _theme_section(sub, theme, "show_stats",
                              "Statistics Overlay", icon="INFO")
        if body is not None:
            body.prop(theme, "stats_text_size")
            body.prop(theme, "stats_offset_x")
            body.prop(theme, "stats_offset_y")
            body.prop(theme, "stats_row_spacing")
            body.prop(theme, "stats_column_spacing")
```

Note: the Dynamic / Help / Statistics sub-section bodies are identical to the current code — they are reproduced in full here only because the surrounding block is being rewritten. Do not delete or alter the three overlay sub-sections; they continue exactly as before.

Also: delete the now-obsolete `sub.separator()` calls that used to live between the four flat blocks (the only `sub.separator()` left inside the HUD body should be the single one right before `Dynamic Overlay`, as shown above).

The introductory comment above `sub = _theme_section(layout, theme, "show_hud", …)` (theme.py:431-434) should be updated to reflect the new structure. Replace it with:

```python
    # HUD — parent rollout. Contains three shared-style sub-sections
    # (text, panel+shadow, font) used by every HUD overlay, followed by
    # three per-overlay sub-sections (Dynamic, Help, Statistics).
```

- [ ] **Step 2: Reload the addon and verify the new structure visually**

Use blender-mcp to reload the addon:

```python
import bpy
bpy.ops.preferences.addon_disable(module="InteractionOps")
bpy.ops.preferences.addon_enable(module="InteractionOps")
bpy.ops.screen.userpref_show()
```

Then in the Preferences window: Add-ons → InteractionOps → expand the addon → Theme tab → expand HUD.

Expected: HUD body shows exactly six TRIA toggles in this order:

1. ▸ Text Styles (collapsed)
2. ▸ Panel & Shadow (collapsed)
3. ▸ Font (collapsed)
4. ▾ Dynamic Overlay (expanded)
5. ▸ Help Overlay (collapsed)
6. ▸ Statistics Overlay (collapsed)

Click each of the three new sub-sections in turn and confirm the controls inside match what used to be flat: 5 text-style rows, panel+shadow block with greying tied to enable toggles, font field + info label.

- [ ] **Step 3: Verify theme preset load still works**

Apply a saved preset via the preset dropdown at the top of the Theme tab. Expected: colors/sizes update normally, no console errors. (Presets reference property names like `color_hud_header`, `panel_bg_color`, `font_path` — none of which were renamed.)

- [ ] **Step 4: Verify Reset Defaults still works**

Click the `Reset Theme to Defaults` button at the bottom of the Theme tab. Expected: all values reset including the three new fold flags (sub-sections collapse back). No errors.

- [ ] **Step 5: Commit**

```bash
git add prefs/theme.py
git commit -m "refactor(prefs): collapse HUD shared-style blocks into sub-sections"
```

---

## Verification Checklist (final)

- [ ] HUD rollout shows exactly six TRIA toggles, with the new three at the top.
- [ ] Each new sub-section, when expanded, exposes the same controls as before the change.
- [ ] No property was renamed/removed (verified by successful preset load).
- [ ] `iops.theme_reset_defaults` resets without error.
- [ ] No console warnings on addon enable/disable.
