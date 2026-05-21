# HUD Prefs Grouping (Theme Tab)

**Date:** 2026-05-21
**Status:** Approved, ready for plan
**Scope:** UI-only reorganization of the HUD section in `prefs/theme.py` (Theme tab of addon preferences).

## Problem

The `HUD` rollout in the Theme tab is too long and flat at the top level.
Before the user reaches the three nested overlay sub-sections
(`Dynamic Overlay`, `Help Overlay`, `Statistics Overlay`) they have to
scroll past:

- 5 rows of text-style controls (color + size for header / glyph / label /
  inactive label / stats error),
- the `Background panel` block (enable + color + padding),
- the `Shadow` block (enable + color + blur + offset X/Y),
- the `Font file` field plus its info label.

These four blocks apply to *all* overlays, but visually they crowd out the
actually-frequently-used overlay sections.

## Goal

Wrap the four flat shared-style blocks into collapsible sub-sections so the
HUD parent rollout becomes a clean list of six identical TRIA toggles.
No property semantics change. No data migration. Theme presets stay
compatible.

## Resulting Structure

```
▾ HUD                                  [WINDOW]
  ▸ Text Styles                        (new sub-section, collapsed by default)
      Header / Glyph / Label / Inactive / Stats Error — color + size rows
  ▸ Panel & Shadow                     (new sub-section, collapsed by default)
      panel_bg_enabled / panel_bg_color / panel_bg_padding
      shadow_enabled / shadow_color / shadow_blur / shadow_offset_x/y
  ▸ Font                               (new sub-section, collapsed by default)
      font_path + info hint
  ▾ Dynamic Overlay                    (existing — default open as today)
  ▸ Help Overlay                       (existing — collapsed)
  ▸ Statistics Overlay                 (existing — collapsed)
```

## Changes

### 1. New UI fold-state flags in `IOPS_Theme`

Add three `BoolProperty` flags (UI-only, no preset payload concern — they
are pure fold-state, same convention as existing `show_hud_placement` /
`show_help` / `show_stats`):

- `show_hud_text: BoolProperty(default=False)`
- `show_hud_panel: BoolProperty(default=False)`
- `show_hud_font: BoolProperty(default=False)`

### 2. `draw_theme_tab()` — HUD body re-layout

Inside the existing `HUD` rollout body, wrap each of the four flat blocks
in a `_theme_section(sub, theme, <flag>, <title>, icon=…)` call, exactly
the same pattern already used for `Dynamic Overlay`, `Help Overlay`,
`Statistics Overlay` later in the same function.

Concretely, the current flat body becomes:

- `Text Styles` (icon `FONT_DATA`) — wraps the existing 5-row
  `for attr, size_attr, label in (…)` loop.
- `Panel & Shadow` (icon `MESH_PLANE`) — wraps the two blocks for
  `panel_bg_*` and `shadow_*`, keeping the existing `active = …` greying.
- `Font` (icon `FILE_FONT`) — wraps `font_path` field + the existing
  info label.

The three existing nested overlay sub-sections stay exactly as they are.

### 3. Defaults

The three new sub-sections default to **collapsed** — they are
"set-once-and-forget" controls. `Dynamic Overlay` stays default open
(`show_hud_placement: BoolProperty(default=True)`), preserving the
current first-visit experience.

## Non-Changes (Explicit)

- No property added, removed, renamed, or retyped on `IOPS_Theme` other
  than the three new fold flags above.
- No default value, min, max, description, or subtype on any existing
  prop is touched.
- Theme preset save/load (`operators/preferences/io_theme.py`) is not
  modified — preset files keep working without migration.
- Point / Line / Widgets / Behaviour sections are not touched.
- Reset-to-defaults operator (`iops.theme_reset_defaults`) needs no
  change; it iterates `bl_rna.properties`, so the new flags reset along
  with everything else.

## Risk

Effectively zero. This is a pure layout refactor of `draw_theme_tab()`
plus three additive boolean UI flags. No runtime path other than the
prefs tab draw is touched.

## Verification

- Open addon prefs → Theme tab → expand HUD: confirm the rollout shows
  six TRIA toggles with `Dynamic Overlay` open and the other five
  collapsed.
- Expand each new sub-section in turn and confirm the same controls are
  present as before the change.
- Save a theme preset, restart Blender, load it back — values restore
  identically.
- Run `iops.theme_reset_defaults` — fold-state of new sub-sections
  resets to collapsed.
